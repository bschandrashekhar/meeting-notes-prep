"""
Case Study Ingestion Script — Sync PDFs to Supabase pgvector

Usage:
    python -m scripts.ingest_case_studies                  # Full sync
    python -m scripts.ingest_case_studies --dry-run        # Preview changes
    python -m scripts.ingest_case_studies --file "Acme_CRM_MP.pdf"  # Single file
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import pdfplumber
import voyageai
from supabase import create_client

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    VOYAGE_API_KEY,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

CASE_STUDIES_DIR = PROJECT_ROOT / "all_casestudies_for_rag"
TABLE_NAME = "case_studies"


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract all text from a PDF file."""
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n\n".join(text_parts)


def parse_filename_metadata(filename: str) -> dict:
    """Parse company name, use case, and doc type from filename.

    Expected pattern: CompanyName_UseCase_Type.pdf
    e.g., Acme_InventoryManagement_MP.pdf
    """
    stem = Path(filename).stem  # strip extension
    parts = stem.rsplit("_", maxsplit=1)

    doc_type = ""
    name_use = stem
    if len(parts) == 2 and len(parts[1]) <= 4:
        name_use = parts[0]
        doc_type = parts[1]

    # Split remaining on first underscore for company vs use case
    name_parts = name_use.split("_", maxsplit=1)
    company_name = name_parts[0].replace("-", " ")
    use_case = name_parts[1].replace("-", " ").replace("_", " ") if len(name_parts) > 1 else ""

    return {
        "company_name": company_name,
        "use_case": use_case,
        "doc_type": doc_type,
    }


def generate_summary(text: str, filename: str) -> str:
    """Generate a 2-3 sentence summary of a case study using Claude."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Truncate text to avoid excessive token usage
    truncated = text[:8000] if len(text) > 8000 else text

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=256,
        system="You summarize case study documents in 2-3 concise sentences. Focus on the client, the problem solved, and the outcome.",
        messages=[{
            "role": "user",
            "content": f"Summarize this case study (filename: {filename}):\n\n{truncated}",
        }],
    )
    return response.content[0].text.strip()


def generate_embedding(text: str) -> list[float]:
    """Generate a 1024-dim embedding using Voyage AI."""
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    # Truncate to stay within model limits
    truncated = text[:16000] if len(text) > 16000 else text
    result = client.embed([truncated], model="voyage-3-large", input_type="document")
    return result.embeddings[0]


def get_local_files() -> dict[str, Path]:
    """Return a dict of filename -> path for all PDFs in the case studies folder."""
    files = {}
    if not CASE_STUDIES_DIR.exists():
        logger.warning("Case studies directory not found: %s", CASE_STUDIES_DIR)
        return files
    for f in CASE_STUDIES_DIR.iterdir():
        if f.suffix.lower() == ".pdf":
            files[f.name] = f
    return files


def get_existing_records(supabase) -> dict[str, dict]:
    """Fetch all existing records from Supabase. Returns filename -> record dict."""
    result = supabase.table(TABLE_NAME).select("id, filename, updated_at").execute()
    return {row["filename"]: row for row in result.data}


def sync(dry_run: bool = False, single_file: str | None = None):
    """Synchronize local PDFs with Supabase vector store."""

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)
    if not VOYAGE_API_KEY:
        logger.error("VOYAGE_API_KEY must be set")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY must be set for summary generation")
        sys.exit(1)

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    local_files = get_local_files()
    logger.info("Found %d local PDF files", len(local_files))

    if single_file:
        if single_file not in local_files:
            logger.error("File '%s' not found in %s", single_file, CASE_STUDIES_DIR)
            sys.exit(1)
        local_files = {single_file: local_files[single_file]}

    existing = get_existing_records(supabase)
    logger.info("Found %d existing records in Supabase", len(existing))

    # Determine actions
    to_add = []
    to_update = []
    to_delete = []
    to_skip = []

    for filename, path in local_files.items():
        if filename in existing:
            # Check if file was modified after the Supabase record
            file_mtime = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            )
            db_updated = existing[filename].get("updated_at", "")
            if db_updated:
                db_time = datetime.fromisoformat(db_updated.replace("Z", "+00:00"))
                if file_mtime > db_time:
                    to_update.append(filename)
                else:
                    to_skip.append(filename)
            else:
                to_update.append(filename)
        else:
            to_add.append(filename)

    if not single_file:
        # Files in DB but not on disk → delete
        for filename in existing:
            if filename not in local_files:
                to_delete.append(filename)

    logger.info(
        "Sync plan: add=%d, update=%d, delete=%d, skip=%d",
        len(to_add), len(to_update), len(to_delete), len(to_skip),
    )

    if dry_run:
        if to_add:
            logger.info("Would ADD: %s", ", ".join(sorted(to_add)))
        if to_update:
            logger.info("Would UPDATE: %s", ", ".join(sorted(to_update)))
        if to_delete:
            logger.info("Would DELETE: %s", ", ".join(sorted(to_delete)))
        logger.info("Dry run complete — no changes made.")
        return

    # Delete removed files
    deleted = 0
    for filename in to_delete:
        record = existing[filename]
        supabase.table(TABLE_NAME).delete().eq("id", record["id"]).execute()
        logger.info("  Deleted: %s", filename)
        deleted += 1

    # Process new and updated files
    processed = 0
    for filename in to_add + to_update:
        path = local_files[filename]
        action = "Adding" if filename in to_add else "Updating"
        logger.info("  %s: %s", action, filename)

        try:
            # Extract text and strip null bytes (Postgres rejects \u0000)
            text = extract_text_from_pdf(path).replace('\x00', '')
            if not text.strip():
                logger.warning("  Skipping %s — no text extracted", filename)
                continue

            # Parse metadata from filename
            meta = parse_filename_metadata(filename)

            # Generate summary
            summary = generate_summary(text, filename)
            logger.info("    Summary: %s", summary[:100] + "..." if len(summary) > 100 else summary)

            # Generate embedding
            embedding = generate_embedding(text)
            logger.info("    Embedding generated (dim=%d)", len(embedding))

            # Upsert to Supabase
            row = {
                "filename": filename,
                "company_name": meta["company_name"],
                "use_case": meta["use_case"],
                "doc_type": meta["doc_type"],
                "content_text": text[:50000],  # cap at 50k chars
                "summary": summary,
                "embedding": embedding,
                "metadata": {
                    "file_size": path.stat().st_size,
                    "pages": _count_pages(path),
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            supabase.table(TABLE_NAME).upsert(row, on_conflict="filename").execute()
            processed += 1
            logger.info("    Upserted successfully")

        except Exception as e:
            logger.error("  Failed to process %s: %s", filename, e)

    logger.info(
        "Sync complete: added/updated=%d, deleted=%d, skipped=%d",
        processed, deleted, len(to_skip),
    )


def _count_pages(pdf_path: Path) -> int:
    """Count pages in a PDF."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description="Sync case study PDFs to Supabase vector store")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    parser.add_argument("--file", type=str, default=None, help="Process a single file by name")
    args = parser.parse_args()

    sync(dry_run=args.dry_run, single_file=args.file)


if __name__ == "__main__":
    main()
