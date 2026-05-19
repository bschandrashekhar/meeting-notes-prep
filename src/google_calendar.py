"""Google Calendar integration — Service Account auth, event fetching, description parsing."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from src.config import (
    GOOGLE_SERVICE_ACCOUNT_KEY,
    GOOGLE_SCOPES,
    CALENDAR_NAME,
    IST,
)
from src.models import Attendee, MeetingInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Service Account auth
# ---------------------------------------------------------------------------

def authenticate() -> Credentials:
    """Return Google credentials from the Service Account key (JSON string)."""
    key_data = json.loads(GOOGLE_SERVICE_ACCOUNT_KEY)
    creds = Credentials.from_service_account_info(key_data, scopes=GOOGLE_SCOPES)
    return creds


# ---------------------------------------------------------------------------
# Calendar look-up
# ---------------------------------------------------------------------------

def _find_calendar_id(service: Any) -> str:
    """Resolve the calendar ID from CALENDAR_NAME.

    CALENDAR_NAME can be either a calendar ID (e.g. "abc@group.calendar.google.com")
    or a display name. For service accounts, shared calendars don't appear in
    calendarList automatically, so we try CALENDAR_NAME as a direct ID first.
    """
    # Try CALENDAR_NAME as a direct calendar ID
    try:
        cal = service.calendars().get(calendarId=CALENDAR_NAME).execute()
        logger.info("Calendar resolved by ID: %s", cal.get("summary", CALENDAR_NAME))
        return CALENDAR_NAME
    except Exception:
        pass

    # Fall back to searching by display name
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
        "Set CALENDAR_NAME to the Calendar ID from Google Calendar settings "
        "(under Integrate calendar), or ensure the calendar is shared with "
        "the service account."
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
        raw_attachments = event.get("attachments", [])
        logger.info(
            "Event '%s' has %d attachment(s): %s",
            event.get("summary", "?"), len(raw_attachments), raw_attachments,
        )
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
                subject=parsed.get("subject") or event.get("summary", ""),
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
    ("agenda", re.compile(r"^agenda\s*:+", re.IGNORECASE)),
    ("company_information", re.compile(r"^company\s+information\s*:+", re.IGNORECASE)),
    ("company_tech_info", re.compile(r"^company\s+tech\s+background\s*:+", re.IGNORECASE)),
    ("prospect_industry", re.compile(r"^company\s+industry\s*:+", re.IGNORECASE)),
    ("company_country", re.compile(r"^company\s+country\s*:+", re.IGNORECASE)),
    ("attendees", re.compile(r"^attendees\s*:+", re.IGNORECASE)),
    ("subject", re.compile(r"^subject\s*:+", re.IGNORECASE)),
]


def _match_header(line: str) -> tuple[str | None, str]:
    """If *line* starts with a known header, return (key, remainder). Else (None, line)."""
    # Strip leading bullets/dashes and whitespace
    stripped = re.sub(r"^[-–•]\s*", "", line.strip())
    for key, pattern in _HEADERS:
        m = pattern.match(stripped)
        if m:
            remainder = stripped[m.end():].strip()
            # Strip trailing punctuation left over (e.g. "Attendees:.")
            remainder = re.sub(r"^[.\s]+", "", remainder)
            return key, remainder
    return None, line


def _parse_description(description: str) -> dict[str, Any]:
    """Parse the structured calendar event description into a dict."""
    text = description
    # Convert block-level closing tags to newlines
    text = re.sub(r"</(?:p|div|li|ol|ul|tr)>", "\n", text, flags=re.IGNORECASE)
    # Convert <br> variants to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Strip inline formatting tags (bold, italic, links keep text)
    text = re.sub(r"<(?:strong|b|em|i|u|span)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</(?:strong|b|em|i|u|span)>", "", text, flags=re.IGNORECASE)
    # Extract href from links and keep the text
    text = re.sub(r'<a\s[^>]*href="([^"]*)"[^>]*>[^<]*</a>', r"\1", text, flags=re.IGNORECASE)
    # Strip any remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalise non-breaking spaces and HTML entities
    text = text.replace("\xa0", " ")
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")

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
            name = m.group(1).strip()
            # Strip "Full Name :" placeholder prefix if present
            name = re.sub(r"^full\s+name\s*:\s*", "", name, flags=re.IGNORECASE)
            current = {"name": name.strip(), "title": "", "linkedin_url": ""}
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
