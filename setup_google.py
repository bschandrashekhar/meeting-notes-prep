"""One-time Google OAuth setup.

Run this script once to authorise Calendar (read) + Gmail (send) + Drive (read)
access.  It saves token.json in the project root for future use.

Prerequisites
-------------
1. Go to https://console.cloud.google.com/apis/credentials
2. Create an OAuth 2.0 Client ID (Desktop application)
3. Download the JSON and save it as  credentials.json  in this folder
4. Enable the following APIs in your GCP project:
   - Google Calendar API
   - Gmail API
   - Google Drive API
"""

from google_auth_oauthlib.flow import InstalledAppFlow

from src.config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_SCOPES


def main() -> None:
    print("Starting Google OAuth flow …")
    print(f"Credentials file : {GOOGLE_CREDENTIALS_FILE}")
    print(f"Token will save to: {GOOGLE_TOKEN_FILE}")
    print(f"Scopes requested  : {GOOGLE_SCOPES}\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
    )
    creds = flow.run_local_server(port=0)

    GOOGLE_TOKEN_FILE.write_text(creds.to_json())
    print(f"\nToken saved to {GOOGLE_TOKEN_FILE}")
    print("You can now run the pipeline with:  python -m src")


if __name__ == "__main__":
    main()
