"""Verify Google Service Account setup.

Run this script to confirm the service account can access the configured calendar.
"""

from src.config import CALENDAR_NAME
from src.google_calendar import authenticate, _find_calendar_id
from googleapiclient.discovery import build


def main() -> None:
    print("Verifying Google Service Account access ...")
    print(f"Calendar name: {CALENDAR_NAME}\n")

    creds = authenticate()
    print("Service account credentials loaded OK.")

    service = build("calendar", "v3", credentials=creds)
    cal_id = _find_calendar_id(service)
    print(f"Calendar found! ID: {cal_id}")
    print("\nSetup is working. You can now run the pipeline with:  python -m src")


if __name__ == "__main__":
    main()
