"""
Meeting Prep Automation — Main Orchestrator

Usage:
    python -m src.main                     # Prep for tomorrow's meetings
    python -m src.main --date 2026-03-05   # Prep for a specific date
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

from src.config import LOGS_DIR
from src.models import AttendeeInsight, DailyBrief, MeetingBrief

# Configure logging
log_file = LOGS_DIR / f"prep_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def run_prep(target_date: date) -> None:
    """Execute the full meeting prep pipeline."""

    logger.info("=" * 60)
    logger.info("Meeting Prep — %s", target_date.strftime("%A, %B %d, %Y"))
    logger.info("=" * 60)

    # --- Stage 1: Fetch meetings from Google Calendar ---
    logger.info("Stage 1: Fetching meetings from Google Calendar...")
    from src.google_calendar import get_meetings_for_date

    meetings = get_meetings_for_date(target_date)

    if not meetings:
        logger.info("No meetings with external attendees found for %s", target_date)
        return

    logger.info("Found %d meetings with external attendees", len(meetings))
    for m in meetings:
        attendee_info = ", ".join(
            f"{a.name} ({a.title})" if a.title else a.name for a in m.attendees
        )
        logger.info("  - %s (%s) — Attendees: %s", m.title,
                     m.start_time.strftime("%I:%M %p"), attendee_info)

    # --- Stage 2: Enrich attendees via ZoomInfo ---
    logger.info("Stage 2: Enriching attendees via ZoomInfo...")
    from src.zoominfo_client import ZoomInfoClient

    zi_client = ZoomInfoClient()
    try:
        zi_client.authenticate()
    except Exception as e:
        logger.warning("ZoomInfo authentication failed: %s. Continuing without enrichment.", e)
        zi_client = None

    # Deduplicate attendees across meetings (same name = same person)
    all_attendees = {}
    for meeting in meetings:
        for att in meeting.attendees:
            if att.name not in all_attendees:
                all_attendees[att.name] = att

    logger.info("Enriching %d unique attendees...", len(all_attendees))

    enrichments = {}  # name -> ZoomInfoEnrichment
    for name, attendee in all_attendees.items():
        if zi_client:
            try:
                enrichments[name] = zi_client.enrich_attendee(attendee)
                logger.info("  Enriched: %s", attendee.name)
            except Exception as e:
                logger.warning("  Failed to enrich %s: %s", attendee.name, e)
                enrichments[name] = None
        else:
            enrichments[name] = None

    # --- Stage 3: Research with Claude AI (skipped if no API key) ---
    from src.config import ANTHROPIC_API_KEY

    _use_ai = bool(ANTHROPIC_API_KEY)

    if _use_ai:
        logger.info("Stage 3: Researching attendees with Claude AI (web search)...")
        from src.research import research_attendee, synthesize_meeting_brief

        try:
            meeting_briefs = []
            for meeting in meetings:
                attendee_insights = []
                for att in meeting.attendees:
                    zoominfo = enrichments.get(att.name)
                    insight = research_attendee(att, zoominfo, meeting_title=meeting.title)
                    attendee_insights.append(insight)
                    logger.info("  Researched: %s (for %s)", att.name, meeting.title)

                # --- Stage 3b: Case study search ---
                case_studies = []
                capability_docs = []
                from src.config import SUPABASE_URL
                if SUPABASE_URL:
                    try:
                        logger.info("Stage 3b: Searching case studies for: %s", meeting.title)
                        from src.case_study_search import search_case_studies
                        case_studies, capability_docs = search_case_studies(meeting, attendee_insights)
                        logger.info("  Found %d case studies + %d capability docs", len(case_studies), len(capability_docs))
                    except Exception as e:
                        logger.warning("  Case study search failed: %s. Continuing without.", e)
                else:
                    logger.info("Stage 3b: Skipping case study search (SUPABASE_URL not set)")

                brief = synthesize_meeting_brief(
                    meeting, attendee_insights,
                    case_studies=case_studies, capability_docs=capability_docs,
                )
                meeting_briefs.append(brief)
                logger.info("  Synthesized brief for: %s", meeting.title)

        except anthropic.AuthenticationError as e:
            logger.warning(
                "Stage 3: Anthropic API auth error — "
                "falling back to ZoomInfo-only briefs. %s", e
            )
            _use_ai = False

    if not _use_ai:
        if not ANTHROPIC_API_KEY:
            logger.info("Stage 3: Skipping AI research (ANTHROPIC_API_KEY not set)...")
        # Build basic insights from ZoomInfo data only
        insights_by_name = {
            name: AttendeeInsight(
                attendee=attendee,
                zoominfo=enrichments.get(name),
            )
            for name, attendee in all_attendees.items()
        }

        meeting_briefs = []
        for meeting in meetings:
            attendee_insights = [
                insights_by_name[att.name]
                for att in meeting.attendees
                if att.name in insights_by_name
            ]
            meeting_briefs.append(MeetingBrief(
                meeting=meeting,
                attendee_insights=attendee_insights,
            ))
            logger.info("  Built basic brief for: %s", meeting.title)

    daily_brief = DailyBrief(
        target_date=target_date,
        meeting_briefs=meeting_briefs,
    )

    # --- Stage 4: Send email ---
    logger.info("Stage 4: Sending email...")
    from src.email_sender import send_daily_brief

    success = send_daily_brief(daily_brief)

    if success:
        logger.info("Email sent successfully!")
    else:
        logger.error("Failed to send email.")

    logger.info("=" * 60)
    logger.info("Meeting prep complete. Log saved to: %s", log_file)
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Meeting Prep Automation — generates intelligence briefs for upcoming meetings"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (default: tomorrow)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            sys.exit(1)
    else:
        IST = ZoneInfo("Asia/Kolkata")
        target_date = datetime.now(IST).date() + timedelta(days=1)

    try:
        run_prep(target_date)
    except Exception as e:
        logger.exception("Meeting prep failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
