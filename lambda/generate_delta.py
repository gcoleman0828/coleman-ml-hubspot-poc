import json
import logging
import uuid
from datetime import datetime, timezone

import boto3

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
logger = logging.getLogger()

# ── Constants ─────────────────────────────────────────────────────────────────
BUCKET_NAME = "coleman-poc-dataconnect-339713097106"
S3_PREFIX   = "delta"

# ── S3 Client ─────────────────────────────────────────────────────────────────
s3_client = boto3.client("s3", region_name="us-east-1")


def generate_records() -> list[dict]:
    """
    Generates a mixed set of synthetic loan records.
    Deliberately includes records that should be filtered out
    so the Lambda filter logic gets exercised on every test run.

    Expected Lambda behavior:
        Pass:   Records 1, 2, 3  (Booked + valid loan type)
        Skip:   Record 4         (Pending status)
        Skip:   Record 5         (CreditCard - invalid loan type)
    """
    now = datetime.now(timezone.utc).isoformat()

    return [
        {
            "application_id": str(uuid.uuid4()),
            "member_email":   "gcoleman@broadviewfcu.com",
            "first_name":     "Gregg",
            "last_name":      "Coleman",
            "loan_type":      "HELOC",
            "loan_amount":    125000.00,
            "status":         "Booked",
            "gclid":          str(uuid.uuid4()),
            "booked_date":    now,
        },
        {
            "application_id": str(uuid.uuid4()),
            "member_email":   "gcoleman@broadviewfcu.com",
            "first_name":     "Gregg",
            "last_name":      "Coleman",
            "loan_type":      "Mortgage",
            "loan_amount":    320000.00,
            "status":         "Booked",
            "gclid":          str(uuid.uuid4()),
            "booked_date":    now,
        },
        {
            "application_id": str(uuid.uuid4()),
            "member_email":   "gcoleman@broadviewfcu.com",
            "first_name":     "Gregg",
            "last_name":      "Coleman",
            "loan_type":      "Retail",
            "loan_amount":    15000.00,
            "status":         "Booked",
            "gclid":          str(uuid.uuid4()),
            "booked_date":    now,
        },
        {
            # Should be skipped - status is Pending not Booked
            "application_id": str(uuid.uuid4()),
            "member_email":   "gcoleman@broadviewfcu.com",
            "first_name":     "Gregg",
            "last_name":      "Coleman",
            "loan_type":      "Retail",
            "loan_amount":    8000.00,
            "status":         "Pending",
            "gclid":          str(uuid.uuid4()),
            "booked_date":    None,
        },
        {
            # Should be skipped - CreditCard is not a valid loan type
            "application_id": str(uuid.uuid4()),
            "member_email":   "gcoleman@broadviewfcu.com",
            "first_name":     "Gregg",
            "last_name":      "Coleman",
            "loan_type":      "CreditCard",
            "loan_amount":    5000.00,
            "status":         "Booked",
            "gclid":          str(uuid.uuid4()),
            "booked_date":    now,
        },
    ]


def upload_to_s3(records: list[dict]) -> str:
    """
    Serializes records to JSON and uploads to S3.
    Uses a timestamped filename to ensure each run
    creates a new object and triggers a fresh S3 event.
    Returns the S3 key of the uploaded file.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    s3_key    = f"{S3_PREFIX}/{timestamp}_delta.json"
    payload   = json.dumps(records, indent=2, default=str)

    s3_client.put_object(
        Bucket=      BUCKET_NAME,
        Key=         s3_key,
        Body=        payload,
        ContentType= "application/json"
    )

    logger.info(f"Uploaded {len(records)} records → s3://{BUCKET_NAME}/{s3_key}")
    return s3_key


def main():
    """
    Orchestration only - generates records and uploads to S3.
    Prints a summary so you can verify before checking Lambda logs.
    """
    logger.info("Generating synthetic delta file...")
    records = generate_records()

    logger.info(f"Generated {len(records)} records "
                f"(expect 3 to pass Lambda filter, 2 to be skipped)")

    s3_key = upload_to_s3(records)

    print(f"\n✅ Delta file uploaded successfully")
    print(f"   Bucket : {BUCKET_NAME}")
    print(f"   Key    : {s3_key}")
    print(f"   Records: {len(records)} total / 3 expected to pass filter")
    print(f"\n→ Check Lambda logs in CloudWatch to verify processing")


if __name__ == "__main__":
    main()