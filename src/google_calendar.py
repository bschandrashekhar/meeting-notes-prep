import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from src.config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_SCOPES
from src.models import Attendee, Meeting

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# The Google Calendar to read meetings from
CALENDAR_NAME = "mindruby-cloudchillies-meetings"

# Domains to exclude from the invite-list fallback (internal teams)
SKIP_DOMAINS = {"mindruby.com", "cloudchillies.com"}


def authenticate() -> Credentials:
    """Authenticate with Google OAuth2, reusing cached token when possible."""
    creds = None

    if GOOGLE_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google token...")
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials not found at {GOOGLE_CREDENTIALS_FILE}. "
                    "Run 'python setup_google.py' first."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        GOOGLE_TOKEN_FILE.write_text(creds.to_json())
        logger.info("Google token saved to %s", GOOGLE_TOKEN_FILE)

    return creds


def _get_calendar_id(service, name: str) -> str:
    """Find a calendar's ID by its display name. Falls back to 'primary' if not found."""
    result = service.calendarList().list().execute()
    for cal in result.get("items", []):
        if cal.get("summary", "").strip().lower() == name.strip().lower():
            logger.info("Found calendar '%s' with id: %s", name, cal["id"])
            return cal["id"]
    logger.warning("Calendar '%s' not found — falling back to primary", name)
    return "primary"


def _parse_attendees_from_description(description: str) -> list[Attendee]:
    """Parse attendees from event description.

    Expected format — one attendee per line, bulleted:
        • Name - Designation
        - Name - Designation
        * Name - Designation
    """
    attendees = []
    for line in description.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip common bullet characters (•, -, *, –)
        line = re.sub(r'^[•\-\*–]\s*', '', line).strip()
        if not line:
            continue
        # Split on first " - " to separate name from designation
        parts = re.split(r'\s*-\s*', line, maxsplit=1)
        name = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ""
        if name:
            attendees.append(Attendee(name=name, title=title))
    return attendees


def _name_from_email(email: str) -> str:
    """Derive a display name from an email address local part."""
    local_part = email.split("@")[0]
    parts = local_part.replace("_", ".").replace("-", ".").split(".")
    return " ".join(part.capitalize() for part in parts)


def _parse_attendees_from_invite_list(raw_attendees: list[dict]) -> list[Attendee]:
    """Fallback: parse attendees from the event invite list.

    Skips internal domains (mindruby.com, cloudchillies.com), declined
    attendees, and calendar resource rooms. Name is derived from the email
    local part; title is left empty for ZoomInfo to fill in later.
    """
    attendees = []
    for att in raw_attendees:
        if att.get("responseStatus") == "declined":
            continue
        if att.get("resource", False):
            continue
        email = att.get("email", "")
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain in SKIP_DOMAINS:
            continue
        name = att.get("displayName", "") or _name_from_email(email)
        attendees.append(Attendee(name=name, email=email))
    return attendees


def get_meetings_for_date(target_date: datetime) -> list[Meeting]:
    """Fetch all meetings for a given date from Google Calendar."""
    creds = authenticate()
    service = build("calendar", "v3", credentials=creds)

    calendar_id = _get_calendar_id(service, CALENDAR_NAME)

    # Build time range for the target date in IST (midnight to midnight IST)
    start_ist = datetime(target_date.year, target_date.month, target_date.day,
                         0, 0, 0, tzinfo=IST)
    end_ist = start_ist + timedelta(days=1)
    time_min = start_ist.isoformat()
    time_max = end_ist.isoformat()

    logger.info("Fetching meetings for %s from calendar '%s'",
                target_date.strftime("%Y-%m-%d"), CALENDAR_NAME)

    events_result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])
    logger.info("Found %d events", len(events))

    meetings = []
    for event in events:
        meeting = _parse_event(event)
        if meeting and meeting.attendees:
            meetings.append(meeting)

    logger.info("Returning %d meetings with external attendees", len(meetings))
    return meetings


def _parse_event(event: dict) -> Meeting | None:
    """Parse a Google Calendar event into a Meeting model."""
    # Skip all-day events (no dateTime field)
    start = event.get("start", {})
    end = event.get("end", {})
    if "dateTime" not in start:
        return None

    # Primary: parse attendees from description (bullet list: Name - Designation)
    description = event.get("description", "")
    attendees = _parse_attendees_from_description(description)

    # Fallback: use the invite distribution list if description had no attendees
    if not attendees:
        logger.debug("No attendees in description for '%s' — falling back to invite list",
                     event.get("summary", ""))
        attendees = _parse_attendees_from_invite_list(event.get("attendees", []))

    # Extract Google Meet link
    meet_link = ""
    conference_data = event.get("conferenceData", {})
    for entry_point in conference_data.get("entryPoints", []):
        if entry_point.get("entryPointType") == "video":
            meet_link = entry_point.get("uri", "")
            break

    return Meeting(
        title=event.get("summary", "(No title)"),
        start_time=datetime.fromisoformat(start["dateTime"]),
        end_time=datetime.fromisoformat(end["dateTime"]),
        location=event.get("location", ""),
        description=event.get("description", ""),
        attendees=attendees,
        meet_link=meet_link,
        calendar_id=event.get("id", ""),
    )


