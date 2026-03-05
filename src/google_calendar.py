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
    calendars = result.get("items", [])
    logger.info("Available calendars (%d):", len(calendars))
    for cal in calendars:
        logger.info("  - '%s' (id: %s)", cal.get("summary", "?"), cal["id"])
    for cal in calendars:
        if cal.get("summary", "").strip().lower() == name.strip().lower():
            logger.info("Using calendar '%s' with id: %s", name, cal["id"])
            return cal["id"]
    logger.warning("Calendar '%s' not found — falling back to primary", name)
    return "primary"


def _parse_description(description: str) -> tuple[str, list[Attendee]]:
    """Parse agenda and attendees from event description.

    Expected format:
        Agenda: This is the meeting agenda...

        Attendees:
        1. Name - Designation
        2. Name - Designation

    Legacy format (no Agenda/Attendees headers) is still supported:
        • Name - Designation
        - Name - Designation
    """
    agenda = ""
    attendees = []
    lines = description.splitlines()

    # Check if description uses the new structured format
    has_attendees_header = any(
        line.strip().lower().startswith("attendees:") for line in lines
    )

    if has_attendees_header:
        in_attendees_section = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Extract agenda
            if stripped.lower().startswith("agenda:"):
                agenda = stripped[len("agenda:"):].strip()
                continue
            # Detect attendees section
            if stripped.lower().startswith("attendees:"):
                in_attendees_section = True
                # Check if there's content after "Attendees:" on the same line
                after = stripped[len("attendees:"):].strip()
                if after:
                    att = _parse_attendee_line(after)
                    if att:
                        attendees.append(att)
                continue
            if in_attendees_section:
                att = _parse_attendee_line(stripped)
                if att:
                    attendees.append(att)
    else:
        # Legacy format: every non-empty line is an attendee
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            att = _parse_attendee_line(stripped)
            if att:
                attendees.append(att)

    return agenda, attendees


def _parse_attendee_line(line: str) -> Attendee | None:
    """Parse a single attendee line, stripping bullets/numbers."""
    # Strip common bullet characters (•, -, *, –) and numbered prefixes (1., 2.)
    line = re.sub(r'^(?:\d+[.)]\s*|[•\-\*–]\s*)', '', line).strip()
    if not line:
        return None
    # Split on first " - " to separate name from designation
    parts = re.split(r'\s*-\s*', line, maxsplit=1)
    name = parts[0].strip()
    title = parts[1].strip() if len(parts) > 1 else ""
    if name:
        return Attendee(name=name, title=title)
    return None


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
    logger.info("Time range: %s to %s", time_min, time_max)

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
    logger.info("Found %d events on '%s'", len(events), CALENDAR_NAME)

    if not events:
        # Diagnostic: also check primary calendar for events
        logger.info("Diagnostic: checking primary calendar for events on %s...",
                     target_date.strftime("%Y-%m-%d"))
        primary_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        primary_events = primary_result.get("items", [])
        if primary_events:
            logger.info("Found %d events on PRIMARY calendar:", len(primary_events))
            for ev in primary_events:
                logger.info("  - '%s' at %s",
                            ev.get("summary", "(no title)"),
                            ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "?")))
        else:
            logger.info("No events found on primary calendar either.")

    meetings = []
    for event in events:
        meeting = _parse_event(event)
        if meeting and meeting.attendees:
            meetings.append(meeting)
        elif meeting:
            logger.info("Skipping event '%s' — no external attendees", meeting.title)
        else:
            logger.info("Skipping all-day or unparseable event: '%s'",
                        event.get("summary", "(no title)"))

    logger.info("Returning %d meetings with external attendees", len(meetings))
    return meetings


def _extract_external_domain(raw_attendees: list[dict]) -> str:
    """Return the first external (non-internal) email domain from the invite list."""
    for att in raw_attendees:
        email = att.get("email", "")
        if not email or att.get("resource", False):
            continue
        domain = email.split("@")[-1].lower()
        if domain not in SKIP_DOMAINS:
            return domain
    return ""


def _parse_event(event: dict) -> Meeting | None:
    """Parse a Google Calendar event into a Meeting model."""
    # Skip all-day events (no dateTime field)
    start = event.get("start", {})
    end = event.get("end", {})
    if "dateTime" not in start:
        return None

    raw_invite_list = event.get("attendees", [])

    # Primary: parse attendees (and agenda) from description
    description = event.get("description", "")
    agenda, attendees = _parse_description(description)

    if attendees:
        # Description attendees have no email/domain. Infer the company domain
        # from the external email addresses the invite was sent to.
        external_domain = _extract_external_domain(raw_invite_list)
        if external_domain:
            logger.info("Inferred company domain '%s' from invite list for description attendees",
                        external_domain)
            for att in attendees:
                if not att.domain:
                    att.domain = external_domain
    else:
        # Fallback: use the invite distribution list if description had no attendees
        logger.debug("No attendees in description for '%s' — falling back to invite list",
                     event.get("summary", ""))
        attendees = _parse_attendees_from_invite_list(raw_invite_list)

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
        agenda=agenda,
        attendees=attendees,
        meet_link=meet_link,
        calendar_id=event.get("id", ""),
    )


