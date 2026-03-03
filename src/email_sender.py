import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from googleapiclient.discovery import build
from jinja2 import Environment, FileSystemLoader

from src.config import GOOGLE_TOKEN_FILE, GOOGLE_SCOPES, TEMPLATES_DIR, TARGET_EMAIL
from src.google_calendar import authenticate
from src.models import DailyBrief

logger = logging.getLogger(__name__)


def render_email(daily_brief: DailyBrief) -> str:
    """Render the daily brief into an HTML email using the Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("email_brief.html")

    return template.render(
        brief=daily_brief,
        meeting_count=len(daily_brief.meeting_briefs),
        target_date=daily_brief.target_date.strftime("%A, %B %d, %Y"),
        generated_at=daily_brief.generated_at.strftime("%I:%M %p on %B %d, %Y"),
    )


def send_email(
    html_content: str,
    subject: str,
    to_email: str = TARGET_EMAIL,
) -> bool:
    """Send an HTML email via Gmail API."""
    try:
        creds = authenticate()
        service = build("gmail", "v1", credentials=creds)

        message = MIMEMultipart("alternative")
        message["to"] = to_email
        message["subject"] = subject

        # Plain text fallback
        plain_text = (
            f"Meeting Prep Brief\n\n"
            f"Please view this email in an HTML-capable email client "
            f"for the full formatted brief."
        )
        message.attach(MIMEText(plain_text, "plain"))
        message.attach(MIMEText(html_content, "html"))

        raw_message = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        service.users().messages().send(
            userId="me",
            body={"raw": raw_message},
        ).execute()

        logger.info("Email sent successfully to %s", to_email)
        return True

    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return False


def send_daily_brief(daily_brief: DailyBrief) -> bool:
    """Render and send the daily brief email."""
    meeting_count = len(daily_brief.meeting_briefs)
    date_str = daily_brief.target_date.strftime("%B %d, %Y")
    subject = f"Meeting Prep Brief — {date_str} ({meeting_count} meeting{'s' if meeting_count != 1 else ''})"

    logger.info("Rendering email for %s", date_str)
    html_content = render_email(daily_brief)

    logger.info("Sending email: %s", subject)
    return send_email(html_content, subject)
