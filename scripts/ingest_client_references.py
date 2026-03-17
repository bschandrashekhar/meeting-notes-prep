"""
Client References Ingestion — Sync client list to Supabase with logos

Usage:
    python -m scripts.ingest_client_references              # Full sync
    python -m scripts.ingest_client_references --dry-run     # Preview changes
"""

import argparse
import logging
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import openpyxl
from supabase import create_client

from src.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

MASTERLIST_PATH = PROJECT_ROOT / "all_casestudies_for_rag" / "Case_studies_masterlist.xlsx"
TABLE_NAME = "client_references"
LOGO_BUCKET = "client-logos"


def _sanitize_filename(name: str) -> str:
    """Convert client name to a safe filename for storage."""
    name = name.strip().lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    return name.strip('-') + ".png"


def _fetch_favicon(url: str) -> bytes | None:
    """Fetch a 64px favicon using Google's favicon service."""
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        domain = parsed.netloc or parsed.path.split("/")[0]
        favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
        req = urllib.request.Request(favicon_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            if len(data) > 100:  # skip tiny/empty responses
                return data
    except Exception as e:
        logger.warning("  Failed to fetch favicon for %s: %s", url, e)
    return None


def load_clients() -> list[dict]:
    """Load clients from the Excel masterlist."""
    if not MASTERLIST_PATH.exists():
        logger.error("Masterlist not found at %s", MASTERLIST_PATH)
        sys.exit(1)

    wb = openpyxl.load_workbook(MASTERLIST_PATH, read_only=True)
    ws = wb["Clients to Reference"]
    clients = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        name = (row[0] or "").strip()
        if not name:
            continue
        clients.append({
            "client_name": name,
            "industry": (row[1] or "").strip(),
            "geography": (row[2] or "").strip(),
            "website_url": (row[3] or "").strip(),
        })
    wb.close()
    logger.info("Loaded %d clients from masterlist", len(clients))
    return clients


def sync(dry_run: bool = False):
    """Sync client references to Supabase."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        sys.exit(1)

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    clients = load_clients()

    if dry_run:
        logger.info("Dry run — would upsert %d client references:", len(clients))
        for c in clients:
            logger.info("  %s (%s, %s)", c["client_name"], c["industry"], c["geography"])
        return

    processed = 0
    logo_ok = 0
    for client in clients:
        name = client["client_name"]
        logger.info("Processing: %s", name)

        # Fetch and upload logo
        logo_url = ""
        if client["website_url"]:
            favicon_data = _fetch_favicon(client["website_url"])
            if favicon_data:
                logo_filename = _sanitize_filename(name)
                try:
                    # Upload to Supabase Storage (upsert mode)
                    supabase.storage.from_(LOGO_BUCKET).upload(
                        logo_filename, favicon_data,
                        file_options={"content-type": "image/png", "upsert": "true"},
                    )
                    logo_url = f"{SUPABASE_URL}/storage/v1/object/public/{LOGO_BUCKET}/{logo_filename}"
                    logo_ok += 1
                    logger.info("  Logo uploaded: %s", logo_filename)
                except Exception as e:
                    logger.warning("  Logo upload failed: %s", e)

        # Upsert to table
        row = {
            "client_name": name,
            "industry": client["industry"],
            "geography": client["geography"],
            "website_url": client["website_url"],
            "logo_url": logo_url,
        }
        try:
            supabase.table(TABLE_NAME).upsert(row, on_conflict="client_name").execute()
            processed += 1
        except Exception as e:
            logger.error("  Failed to upsert %s: %s", name, e)

    logger.info("Sync complete: %d upserted, %d logos uploaded", processed, logo_ok)


def main():
    parser = argparse.ArgumentParser(description="Sync client references to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying")
    args = parser.parse_args()
    sync(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
