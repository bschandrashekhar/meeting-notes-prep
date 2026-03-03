"""
One-time Google OAuth setup script.

SETUP INSTRUCTIONS:
===================
1. Go to https://console.cloud.google.com
2. Create a new project (or select existing)
3. Enable these APIs:
   - Google Calendar API
   - Gmail API
4. Go to "APIs & Services" > "OAuth consent screen"
   - Choose "External" user type
   - Fill in app name (e.g., "Meeting Prep")
   - Add your email as a test user
5. Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth 2.0 Client ID"
   - Application type: "Desktop app"
   - Download the JSON file
   - Save it as 'credentials.json' in this project's root directory
6. Run this script: python setup_google.py
7. A browser window will open - sign in and grant access
8. The script will save 'token.json' for future use
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_SCOPES
from google_auth_oauthlib.flow import InstalledAppFlow


def main():
    print("=" * 60)
    print("  Google OAuth Setup for Meeting Prep")
    print("=" * 60)
    print()

    if not GOOGLE_CREDENTIALS_FILE.exists():
        print(f"ERROR: credentials.json not found at:")
        print(f"  {GOOGLE_CREDENTIALS_FILE}")
        print()
        print("Please follow the setup instructions at the top of this file")
        print("to create OAuth credentials and download credentials.json.")
        sys.exit(1)

    if GOOGLE_TOKEN_FILE.exists():
        print(f"Token file already exists at: {GOOGLE_TOKEN_FILE}")
        response = input("Overwrite? (y/N): ").strip().lower()
        if response != "y":
            print("Aborted.")
            sys.exit(0)

    print("Opening browser for Google sign-in...")
    print(f"Scopes requested: {', '.join(GOOGLE_SCOPES)}")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
    )
    creds = flow.run_local_server(port=0)

    GOOGLE_TOKEN_FILE.write_text(creds.to_json())

    print()
    print("SUCCESS! Token saved to:", GOOGLE_TOKEN_FILE)
    print("You can now run the meeting prep tool.")


if __name__ == "__main__":
    main()
