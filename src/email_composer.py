"""Email composer — Jinja2 rendering + Resend API for sending."""

from __future__ import annotations

import base64
import logging
from datetime import datetime

import resend
from jinja2 import Environment, FileSystemLoader

from src.config import ANTHROPIC_MODEL, RESEND_API_KEY, RESEND_FROM, TARGET_EMAIL, TEMPLATES_DIR
from src.google_calendar import authenticate
from src.models import EnrichedMeeting

logger = logging.getLogger(__name__)

resend.api_key = RESEND_API_KEY


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
# Attachment fetching (Google Drive — only when token.json exists locally)
# ---------------------------------------------------------------------------

def _fetch_attachments(att_list: list[dict]) -> list[dict]:
    """Fetch calendar attachments from Google Drive.

    Returns a list of Resend attachment dicts: [{filename, content}].
    Requires the service account to have Drive read access.
    """
    from src.config import GOOGLE_SERVICE_ACCOUNT_KEY

    if not att_list or not GOOGLE_SERVICE_ACCOUNT_KEY:
        return []

    try:
        from googleapiclient.discovery import build

        creds = authenticate()
        drive = build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.warning("Cannot access Google Drive for attachments: %s", e)
        return []

    attachments = []
    for att_meta in att_list:
        file_id = att_meta.get("file_id", "")
        if not file_id:
            continue
        try:
            meta = drive.files().get(fileId=file_id, fields="name,mimeType").execute()
            content = drive.files().get_media(fileId=file_id).execute()
            attachments.append({
                "filename": meta["name"],
                "content": list(content),  # Resend expects bytes-like content
            })
        except Exception as e:
            logger.warning("Failed to fetch attachment %s: %s", file_id, e)

    return attachments


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

def send_meeting_email(
    enriched: EnrichedMeeting,
    to_email: str = TARGET_EMAIL,
) -> bool:
    """Render and send the meeting brief email via Resend."""
    try:
        html_content = render_meeting_email(enriched)

        params: dict = {
            "from": RESEND_FROM,
            "to": [to_email],
            "subject": enriched.input.subject,
            "html": html_content,
        }

        # Attach calendar attachments if available
        attachments = _fetch_attachments(enriched.input.attachments)
        if attachments:
            params["attachments"] = attachments

        resend.Emails.send(params)
        logger.info("Email sent: '%s' -> %s", enriched.input.subject, to_email)
        return True

    except Exception as e:
        logger.error("Failed to send email for '%s': %s", enriched.input.subject, e)
        return False
