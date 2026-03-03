import logging
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from src.config import GOOGLE_CREDENTIALS_FILE, GOOGLE_TOKEN_FILE, GOOGLE_SCOPES
from src.models import Attendee, Meeting

logger = logging.getLogger(__name__)

# Email to exclude from attendees (the user's own email)
OWN_EMAIL_DOMAIN = "mindruby.com"


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


def get_meetings_for_date(target_date: datetime) -> list[Meeting]:
    """Fetch all meetings for a given date from Google Calendar."""
    creds = authenticate()
    service = build("calendar", "v3", credentials=creds)

    # Build time range for the target date (local timezone)
    time_min = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(
        target_date + timedelta(days=1), datetime.min.time()
    ).isoformat() + "Z"

    logger.info("Fetching meetings for %s", target_date.strftime("%Y-%m-%d"))

    events_result = (
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

    # Extract attendees
    raw_attendees = event.get("attendees", [])
    attendees = []
    for att in raw_attendees:
        # Skip declined attendees
        if att.get("responseStatus") == "declined":
            continue

        email = att.get("email", "")

        # Skip the user's own email
        if email.endswith(f"@{OWN_EMAIL_DOMAIN}"):
            continue

        # Skip resource rooms
        if att.get("resource", False):
            continue

        name = att.get("displayName", "")
        if not name:
            name = _name_from_email(email)

        attendees.append(
            Attendee(
                name=name,
                email=email,
                is_organizer=att.get("organizer", False),
            )
        )

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


def _name_from_email(email: str) -> str:
    """Derive a display name from an email address."""
    local_part = email.split("@")[0]
    # Handle common patterns: first.last, first_last, firstlast
    parts = local_part.replace("_", ".").replace("-", ".").split(".")
    return " ".join(part.capitalize() for part in parts)
