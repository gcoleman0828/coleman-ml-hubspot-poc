import json
import logging
import os

import boto3
import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Constants ─────────────────────────────────────────────────────────────────
VALID_LOAN_TYPES = {"Retail", "HELOC", "Mortgage"}
BOOKED_STATUS    = "Booked"

# ── S3 Client ─────────────────────────────────────────────────────────────────
s3_client = boto3.client("s3")


def get_s3_file(bucket: str, key: str) -> list[dict]:
    """
    Downloads the delta file from S3 and parses it as a JSON array.
    Returns a list of raw loan record dictionaries.
    """
    logger.info(f"Downloading s3://{bucket}/{key}")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    raw      = response["Body"].read().decode("utf-8")
    records  = json.loads(raw)
    logger.info(f"Parsed {len(records)} total records from file")
    return records


def filter_records(records: list[dict]) -> list[dict]:
    """
    Filters raw records to only those that are Booked
    and match a valid loan type.
    Single responsibility: filtering only, no other logic.
    """
    filtered = [
        r for r in records
        if r.get("status")    == BOOKED_STATUS
        and r.get("loan_type") in VALID_LOAN_TYPES
    ]
    logger.info(
        f"After filtering: {len(filtered)} qualifying records "
        f"(skipped {len(records) - len(filtered)})"
    )
    return filtered


def deduplicate_records(records: list[dict]) -> list[dict]:
    """
    Deduplicates records on application_id.
    Later records overwrite earlier ones — delta files list
    updates chronologically so the last entry is always newest state.
    Single responsibility: deduplication only, no filtering or mapping.
    Returns a flat list of unique records.
    """
    deduped = {}
    for r in records:
        app_id = r.get("application_id")
        if app_id:
            deduped[app_id] = r
    logger.info(f"After dedup: {len(deduped)} unique records to post")
    return list(deduped.values())


def build_payload(record: dict) -> dict:
    """
    Extracts and maps fields from a raw MeridianLink record
    into the Workato webhook contract.
    Single responsibility: schema translation only.
    This is the anti-corruption layer between ML's field names
    and our integration contract — if ML renames a field,
    only this function needs to change.
    """
    return {
        "application_id": record.get("application_id"),
        "member_email":   record.get("member_email"),
        "first_name":     record.get("first_name"),
        "last_name":      record.get("last_name"),
        "loan_type":      record.get("loan_type"),
        "loan_amount":    record.get("loan_amount"),
        "gclid":          record.get("gclid"),
        "booked_date":    record.get("booked_date"),
        "status":         record.get("status"),
    }


def post_to_workato(record: dict, webhook_url: str) -> bool:
    """
    Builds the payload and POSTs it to the Workato webhook.
    Returns True on success, False on failure.
    Failures are logged but do not raise — processing continues
    for remaining records.
    """
    payload = build_payload(record)
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        logger.info(
            f"Posted application_id={payload['application_id']} "
            f"→ HTTP {response.status_code}"
        )
        return True

    except requests.exceptions.RequestException as e:
        logger.error(
            f"Failed to post application_id={payload.get('application_id')} "
            f"→ {str(e)}"
        )
        return False


def main(event: dict, context) -> dict:
    """
    Lambda entry point - orchestration only.
    No business logic lives here - delegates entirely
    to single-responsibility functions.
    """
    # ── Validate environment ──────────────────────────────────────────────────
    webhook_url = os.environ.get("WORKATO_WEBHOOK_URL")
    if not webhook_url or webhook_url == "REPLACE_ME":
        logger.error("WORKATO_WEBHOOK_URL is not configured")
        raise ValueError("WORKATO_WEBHOOK_URL is missing or not set")

    results = {"processed": 0, "skipped": 0, "failed": 0}

    # ── Process each S3 file in the event ────────────────────────────────────
    for s3_record in event["Records"]:
        bucket = s3_record["s3"]["bucket"]["name"]
        key    = s3_record["s3"]["object"]["key"]

        raw_records    = get_s3_file(bucket, key)
        filtered       = filter_records(raw_records)
        unique_records = deduplicate_records(filtered)

        results["skipped"] += len(raw_records) - len(filtered)

        for record in unique_records:
            success = post_to_workato(record, webhook_url)
            if success:
                results["processed"] += 1
            else:
                results["failed"] += 1

    logger.info(f"Run complete → {results}")
    return results