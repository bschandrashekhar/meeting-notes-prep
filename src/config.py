"""Configuration — single source of truth for env vars, paths, and constants."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

# ---------------------------------------------------------------------------
# Helper (supports Streamlit Cloud secrets + local .env)
# ---------------------------------------------------------------------------

def _get_secret(key: str) -> str:
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, "")


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
VOYAGE_API_KEY = _get_secret("VOYAGE_API_KEY")
SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _get_secret("SUPABASE_SERVICE_KEY")
SERPER_API_KEY = _get_secret("SERPER_API_KEY")
APOLLO_API_KEY = _get_secret("APOLLO_API_KEY")

# ---------------------------------------------------------------------------
# Meeting Prep
# ---------------------------------------------------------------------------
CALENDAR_NAME = _get_secret("CALENDAR_NAME") or "MyClientMeetings"
TARGET_EMAIL = _get_secret("TARGET_EMAIL") or "sateesh@mindruby.com"
RESEND_API_KEY = _get_secret("RESEND_API_KEY")
RESEND_FROM = _get_secret("RESEND_FROM") or "Meeting Prep <meetings@mindruby.com>"

# ---------------------------------------------------------------------------
# Google Service Account
# ---------------------------------------------------------------------------
GOOGLE_SERVICE_ACCOUNT_KEY = _get_secret("GOOGLE_SERVICE_ACCOUNT_KEY")
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------
TEMPLATES_DIR = PROJECT_ROOT / "templates"
LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------
IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# Country normalisation
# ---------------------------------------------------------------------------
_COUNTRY_MAP: dict[str, str] = {
    # USA
    "united states": "USA", "united states of america": "USA",
    "america": "USA", "us": "USA", "usa": "USA",
    # UK
    "united kingdom": "UK", "great britain": "UK",
    "gb": "UK", "britain": "UK", "uk": "UK",
    # Australia / Canada pass-through
    "australia": "Australia", "canada": "Canada",
    # EMEA — Middle East
    "saudi arabia": "EMEA", "uae": "EMEA", "united arab emirates": "EMEA",
    "qatar": "EMEA", "bahrain": "EMEA", "kuwait": "EMEA", "oman": "EMEA",
    "iraq": "EMEA", "iran": "EMEA", "jordan": "EMEA", "lebanon": "EMEA",
    "israel": "EMEA", "turkey": "EMEA", "syria": "EMEA", "yemen": "EMEA",
    "palestine": "EMEA",
    # EMEA — Africa
    "south africa": "EMEA", "nigeria": "EMEA", "kenya": "EMEA",
    "egypt": "EMEA", "ghana": "EMEA", "ethiopia": "EMEA",
    "tanzania": "EMEA", "morocco": "EMEA", "algeria": "EMEA",
    "tunisia": "EMEA", "uganda": "EMEA", "rwanda": "EMEA",
    "senegal": "EMEA", "cameroon": "EMEA", "ivory coast": "EMEA",
    # EMEA — Europe
    "germany": "EMEA", "france": "EMEA", "italy": "EMEA", "spain": "EMEA",
    "netherlands": "EMEA", "belgium": "EMEA", "switzerland": "EMEA",
    "austria": "EMEA", "sweden": "EMEA", "norway": "EMEA", "denmark": "EMEA",
    "finland": "EMEA", "poland": "EMEA", "portugal": "EMEA",
    "ireland": "EMEA", "czech republic": "EMEA", "romania": "EMEA",
    "hungary": "EMEA", "greece": "EMEA",
    # Direct
    "emea": "EMEA",
}

ALLOWED_COUNTRIES = {"EMEA", "USA", "Australia", "Canada", "UK"}


def normalize_country(raw: str) -> str:
    """Map a free-text country name to one of the five allowed regions."""
    key = raw.strip().lower()
    mapped = _COUNTRY_MAP.get(key)
    if mapped and mapped in ALLOWED_COUNTRIES:
        return mapped
    return "USA"  # default
