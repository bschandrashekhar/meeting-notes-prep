"""Email composer — Jinja2 rendering + Gmail API send with attachments."""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from jinja2 import Environment, FileSystemLoader

from src.config import ANTHROPIC_MODEL, TARGET_EMAIL, TEMPLATES_DIR
from src.google_calendar import authenticate
from src.models import EnrichedMeeting

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_meeting_email(meeting: EnrichedMeeting) -> str:
    """Render an enriched meeting into an HTML email via the Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("meeting_brief.html")

    return template.render(
        meeting=meeting,
        generated_at=datetime.now().strftime("%I:%M %p on %B %d, %Y"),
        ai_model=ANTHROPIC_MODEL,
    )


# ---------------------------------------------------------------------------
# Attachment fetching (Google Drive)
# ---------------------------------------------------------------------------

def _fetch_attachment(drive_service, file_id: str) -> tuple[str, bytes, str] | None:
    """Download a file from Google Drive by its file ID.

    Returns (filename, content_bytes, mime_type) or None on failure.
    """
    try:
        meta = drive_service.files().get(fileId=file_id, fields="name,mimeType").execute()
        content = drive_service.files().get_media(fileId=file_id).execute()
        return meta["name"], content, meta.get("mimeType", "application/octet-stream")
    except Exception as e:
        logger.warning("Failed to fetch attachment %s: %s", file_id, e)
        return None


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_meeting_email(
    enriched: EnrichedMeeting,
    to_email: str = TARGET_EMAIL,
) -> bool:
    """Render and send the meeting brief email via Gmail API."""
    try:
        creds = authenticate()
        gmail = build("gmail", "v1", credentials=creds)

        html_content = render_meeting_email(enriched)

        message = MIMEMultipart("mixed")
        message["to"] = to_email
        message["subject"] = enriched.input.subject

        # HTML body
        body_part = MIMEMultipart("alternative")
        plain_fallback = (
            f"Meeting Prep Brief: {enriched.input.subject}\n\n"
            "Please view this email in an HTML-capable client for the full brief."
        )
        body_part.attach(MIMEText(plain_fallback, "plain"))
        body_part.attach(MIMEText(html_content, "html"))
        message.attach(body_part)

        # Attachments from the calendar event
        if enriched.input.attachments:
            drive = build("drive", "v3", credentials=creds)
            for att_meta in enriched.input.attachments:
                file_id = att_meta.get("file_id", "")
                if not file_id:
                    continue
                result = _fetch_attachment(drive, file_id)
                if result is None:
                    continue
                filename, content_bytes, mime_type = result
                part = MIMEApplication(content_bytes)
                part.add_header(
                    "Content-Disposition", "attachment", filename=filename
                )
                part["Content-Type"] = mime_type
                message.attach(part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        gmail.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        logger.info("Email sent: '%s' -> %s", enriched.input.subject, to_email)
        return True

    except Exception as e:
        logger.error("Failed to send email for '%s': %s", enriched.input.subject, e)
        return False
