"""Google Calendar integration — OAuth, event fetching, description parsing."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.config import (
    GOOGLE_CREDENTIALS_FILE,
    GOOGLE_SCOPES,
    GOOGLE_TOKEN_FILE,
    CALENDAR_NAME,
    IST,
)
from src.models import Attendee, MeetingInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

def authenticate() -> Credentials:
    """Return valid Google credentials, refreshing or re-authing as needed."""
    creds: Credentials | None = None

    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(
            str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES
        )

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        GOOGLE_TOKEN_FILE.write_text(creds.to_json())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
        )
        creds = flow.run_local_server(port=0)
        GOOGLE_TOKEN_FILE.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Calendar look-up
# ---------------------------------------------------------------------------

def _find_calendar_id(service: Any) -> str:
    """Find the calendar ID by display name (CALENDAR_NAME)."""
    page_token = None
    while True:
        calendars = service.calendarList().list(pageToken=page_token).execute()
        for cal in calendars.get("items", []):
            if cal["summary"].lower() == CALENDAR_NAME.lower():
                return cal["id"]
        page_token = calendars.get("nextPageToken")
        if not page_token:
            break
    raise ValueError(
        f"Calendar '{CALENDAR_NAME}' not found. "
        "Check CALENDAR_NAME in .env and ensure it matches exactly."
    )


# ---------------------------------------------------------------------------
# Fetch events
# ---------------------------------------------------------------------------

def get_meetings_for_date(target_date: date) -> list[MeetingInput]:
    """Pull all meetings for *target_date* from the configured calendar."""
    creds = authenticate()
    service = build("calendar", "v3", credentials=creds)

    calendar_id = _find_calendar_id(service)

    day_start = datetime.combine(target_date, time.min, tzinfo=IST).isoformat()
    day_end = datetime.combine(target_date, time.max, tzinfo=IST).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=day_start,
            timeMax=day_end,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    meetings: list[MeetingInput] = []
    for event in events_result.get("items", []):
        # Skip all-day events
        if "dateTime" not in event.get("start", {}):
            continue

        description = event.get("description", "")
        if not description.strip():
            logger.warning("Event '%s' has no description — skipping", event.get("summary"))
            continue

        parsed = _parse_description(description)

        # Attachments from Google Calendar (stored as Drive files)
        attachments = [
            {
                "filename": att.get("title", "attachment"),
                "file_id": att.get("fileId", ""),
                "mime_type": att.get("mimeType", "application/octet-stream"),
                "file_url": att.get("fileUrl", ""),
            }
            for att in event.get("attachments", [])
        ]

        meetings.append(
            MeetingInput(
                subject=parsed.get("subject", event.get("summary", "")),
                agenda=parsed.get("agenda", ""),
                company_information=parsed.get("company_information", ""),
                company_tech_info=parsed.get("company_tech_info", ""),
                prospect_industry=parsed.get("prospect_industry", ""),
                company_country=parsed.get("company_country", ""),
                attendees=parsed.get("attendees", []),
                attachments=attachments,
                start_time=event["start"]["dateTime"],
                end_time=event["end"]["dateTime"],
                calendar_event_id=event.get("id", ""),
            )
        )

    logger.info("Found %d meetings for %s", len(meetings), target_date)
    return meetings


# ---------------------------------------------------------------------------
# Description parser
# ---------------------------------------------------------------------------

# Recognised section headers (case-insensitive)
_HEADERS = [
    ("agenda", re.compile(r"^agenda\s*:", re.IGNORECASE)),
    ("company_information", re.compile(r"^company\s+information\s*:", re.IGNORECASE)),
    ("company_tech_info", re.compile(r"^company\s+tech\s+background\s*:", re.IGNORECASE)),
    ("prospect_industry", re.compile(r"^company\s+industry\s*:", re.IGNORECASE)),
    ("company_country", re.compile(r"^company\s+country\s*:", re.IGNORECASE)),
    ("attendees", re.compile(r"^attendees\s*:", re.IGNORECASE)),
    ("subject", re.compile(r"^subject\s*:", re.IGNORECASE)),
]


def _match_header(line: str) -> tuple[str | None, str]:
    """If *line* starts with a known header, return (key, remainder). Else (None, line)."""
    stripped = line.strip()
    for key, pattern in _HEADERS:
        m = pattern.match(stripped)
        if m:
            remainder = stripped[m.end():].strip()
            return key, remainder
    return None, line


def _parse_description(description: str) -> dict[str, Any]:
    """Parse the structured calendar event description into a dict."""
    # Normalise HTML line breaks that Google Calendar sometimes injects
    text = description.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    # Strip any remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    lines = text.splitlines()

    sections: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in lines:
        header_key, remainder = _match_header(line)
        if header_key is not None:
            current_key = header_key
            sections.setdefault(current_key, [])
            if remainder:
                sections[current_key].append(remainder)
        elif current_key is not None:
            sections[current_key].append(line)

    # Join multi-line sections into strings
    result: dict[str, Any] = {}
    for key in ("agenda", "company_information", "company_tech_info",
                "prospect_industry", "company_country", "subject"):
        result[key] = "\n".join(sections.get(key, [])).strip()

    # Parse attendees
    attendee_lines = sections.get("attendees", [])
    result["attendees"] = _parse_attendees(attendee_lines)

    return result


# ---------------------------------------------------------------------------
# Attendee parser
# ---------------------------------------------------------------------------

_ATTENDEE_NUM = re.compile(r"^\d+\.\s*(.+)")
_TITLE_LINE = re.compile(r"^[-–•]\s*title\s*:\s*(.+)", re.IGNORECASE)
_LINKEDIN_LINE = re.compile(r"^[-–•]\s*linkedin\s+url\s*:\s*(.+)", re.IGNORECASE)


def _parse_attendees(lines: list[str]) -> list[Attendee]:
    """Parse the numbered attendee block into Attendee objects."""
    attendees: list[Attendee] = []
    current: dict[str, str] | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # New attendee (numbered line)
        m = _ATTENDEE_NUM.match(line)
        if m:
            if current:
                attendees.append(Attendee(**current))
            current = {"name": m.group(1).strip(), "title": "", "linkedin_url": ""}
            continue

        if current is None:
            continue

        # Title sub-bullet
        m = _TITLE_LINE.match(line)
        if m:
            current["title"] = m.group(1).strip()
            continue

        # LinkedIn sub-bullet
        m = _LINKEDIN_LINE.match(line)
        if m:
            current["linkedin_url"] = m.group(1).strip()
            continue

    # Flush last attendee
    if current:
        attendees.append(Attendee(**current))

    return attendees
