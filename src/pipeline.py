"""Pipeline orchestrator — Stage 1 (fetch + enrich) and Stage 2 (email)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Callable

from src.config import IST, TARGET_EMAIL
from src.email_composer import send_meeting_email
from src.enrichment import enrich_meeting
from src.google_calendar import get_meetings_for_date
from src.models import EnrichedMeeting

logger = logging.getLogger(__name__)


def should_run_today() -> bool:
    """Return False on Friday (4) and Saturday (5) in IST — skip cron on those days."""
    weekday = datetime.now(IST).weekday()
    # Monday=0 … Friday=4, Saturday=5, Sunday=6
    return weekday not in (4, 5)


def run_pipeline(
    target_date: date,
    on_progress: Callable[[str], None] | None = None,
    to_email: str = TARGET_EMAIL,
) -> list[EnrichedMeeting]:
    """Execute the full pipeline: fetch meetings, enrich, email.

    Parameters
    ----------
    target_date : date
        Which day's meetings to pull from the calendar.
    on_progress : callable, optional
        Called with a status string at each milestone (useful for Streamlit UI).
    to_email : str
        Recipient email address.

    Returns
    -------
    list[EnrichedMeeting]
        All enriched meetings (for UI display).
    """

    def _log(msg: str) -> None:
        logger.info(msg)
        if on_progress:
            on_progress(msg)

    # ── Stage 1: Fetch meetings ──────────────────────────────────────────
    _log(f"Fetching meetings for {target_date} …")
    meetings = get_meetings_for_date(target_date)
    _log(f"Found {len(meetings)} meeting(s)")

    if not meetings:
        return []

    enriched_list: list[EnrichedMeeting] = []

    for i, meeting in enumerate(meetings, 1):
        _log(f"[{i}/{len(meetings)}] Enriching: {meeting.subject}")

        enriched = enrich_meeting(meeting)
        enriched_list.append(enriched)

        _log(f"[{i}/{len(meetings)}] Enrichment complete for: {meeting.subject}")

    # ── Stage 2: Email ───────────────────────────────────────────────────
    sent = 0
    for i, enriched in enumerate(enriched_list, 1):
        _log(f"[{i}/{len(enriched_list)}] Sending email: {enriched.input.subject}")
        if send_meeting_email(enriched, to_email=to_email):
            sent += 1

    _log(f"Done — sent {sent}/{len(enriched_list)} email(s)")
    return enriched_list
