"""Upload case study PDFs to Supabase Storage bucket for Streamlit Cloud access."""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from supabase import create_client
from src.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CASE_STUDIES_DIR = PROJECT_ROOT / "all_casestudies_for_rag"
BUCKET_NAME = "case-studies"


def main():
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Create bucket if it doesn't exist
    try:
        supabase.storage.create_bucket(BUCKET_NAME, options={"public": True})
        logger.info("Created bucket: %s", BUCKET_NAME)
    except Exception as e:
        if "already exists" in str(e).lower() or "Duplicate" in str(e):
            logger.info("Bucket '%s' already exists", BUCKET_NAME)
        else:
            logger.warning("Bucket creation: %s", e)

    # List existing files in bucket
    existing = set()
    try:
        files = supabase.storage.from_(BUCKET_NAME).list()
        existing = {f["name"] for f in files if f.get("name")}
        logger.info("Found %d existing files in bucket", len(existing))
    except Exception as e:
        logger.warning("Could not list bucket contents: %s", e)

    # Upload PDFs
    pdf_files = sorted(CASE_STUDIES_DIR.glob("*.pdf"))
    logger.info("Found %d local PDFs", len(pdf_files))

    uploaded = 0
    skipped = 0
    for pdf in pdf_files:
        if pdf.name in existing:
            skipped += 1
            continue

        try:
            with open(pdf, "rb") as f:
                supabase.storage.from_(BUCKET_NAME).upload(
                    pdf.name,
                    f,
                    file_options={"content-type": "application/pdf"},
                )
            uploaded += 1
            logger.info("  Uploaded: %s", pdf.name)
        except Exception as e:
            if "Duplicate" in str(e) or "already exists" in str(e).lower():
                skipped += 1
            else:
                logger.error("  Failed to upload %s: %s", pdf.name, e)

    logger.info("Done: uploaded=%d, skipped=%d", uploaded, skipped)


if __name__ == "__main__":
    main()
