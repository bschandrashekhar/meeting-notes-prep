import os
from pathlib import Path

from dotenv import load_dotenv

# Project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env from project root (no-op if file doesn't exist, e.g. in GitHub Actions)
load_dotenv(PROJECT_ROOT / ".env")

# --- API Keys ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
ZOOMINFO_USERNAME = os.getenv("ZOOMINFO_USERNAME", "")
ZOOMINFO_PASSWORD = os.getenv("ZOOMINFO_PASSWORD", "")

# --- Email ---
TARGET_EMAIL = os.getenv("TARGET_EMAIL", "sateesh@mindruby.com")

# --- Google OAuth ---
GOOGLE_CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
GOOGLE_TOKEN_FILE = PROJECT_ROOT / "token.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# In GitHub Actions, the workflow writes these files from secrets before running.
# As a fallback, also support env vars GOOGLE_CREDENTIALS_JSON and GOOGLE_TOKEN_JSON.
_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
if _creds_json and not GOOGLE_CREDENTIALS_FILE.exists():
    GOOGLE_CREDENTIALS_FILE.write_text(_creds_json)

_token_json = os.getenv("GOOGLE_TOKEN_JSON", "")
if _token_json and not GOOGLE_TOKEN_FILE.exists():
    GOOGLE_TOKEN_FILE.write_text(_token_json)

# --- Voyage AI (embeddings) ---
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")

# --- Supabase (vector store) ---
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# --- ZoomInfo ---
ZOOMINFO_BASE_URL = "https://api.zoominfo.com"

# --- Anthropic Claude AI ---
ANTHROPIC_MODEL = "claude-sonnet-4-6"

# --- Perplexity AI (fallback) ---
PERPLEXITY_MODEL = "sonar-pro"
PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

# --- Paths ---
TEMPLATES_DIR = PROJECT_ROOT / "templates"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure logs dir exists
LOGS_DIR.mkdir(exist_ok=True)
