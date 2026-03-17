"""
Test pipeline with research caching.

First run:  Runs stages 1-3 (calendar + ZoomInfo + Claude research), saves to cache JSON.
Next runs:  Loads from cache, re-runs case study matching + synthesis + email only.

Usage:
    python -m scripts.test_pipeline                    # Use cache if exists, else full run
    python -m scripts.test_pipeline --fresh            # Force full run, overwrite cache
    python -m scripts.test_pipeline --no-email         # Skip sending email (just render HTML)
    python -m scripts.test_pipeline --date 2026-03-12  # Specific date
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import LOGS_DIR
from src.models import (
    Attendee, AttendeeInsight, CaseStudyMatch, CompanyData, ContactProfile,
    DailyBrief, Meeting, MeetingBrief, ZoomInfoEnrichment,
)

CACHE_DIR = PROJECT_ROOT / "logs"
CACHE_FILE = CACHE_DIR / "test_cache.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _serialize_cache(meetings, insights_by_meeting) -> dict:
    """Serialize meetings and attendee insights to JSON-safe dict."""
    data = {"meetings": [], "cached_at": datetime.now().isoformat()}
    for meeting in meetings:
        m_data = meeting.model_dump(mode="json")
        m_data["_attendee_insights"] = [
            insight.model_dump(mode="json")
            for insight in insights_by_meeting[meeting.title]
        ]
        data["meetings"].append(m_data)
    return data


def _deserialize_cache(data: dict):
    """Deserialize cached JSON back to Meeting and AttendeeInsight objects."""
    meetings = []
    insights_by_meeting = {}
    for m_data in data["meetings"]:
        insight_data = m_data.pop("_attendee_insights")
        meeting = Meeting(**m_data)
        meetings.append(meeting)
        insights_by_meeting[meeting.title] = [
            AttendeeInsight(**i) for i in insight_data
        ]
    return meetings, insights_by_meeting


def run_stages_1_to_3(target_date: date):
    """Run calendar + ZoomInfo + Claude research. Returns (meetings, insights_by_meeting)."""
    import anthropic
    from src.google_calendar import get_meetings_for_date
    from src.zoominfo_client import ZoomInfoClient
    from src.research import research_attendee

    logger.info("Stage 1: Fetching meetings from Google Calendar...")
    meetings = get_meetings_for_date(target_date)
    if not meetings:
        logger.info("No meetings found for %s", target_date)
        return [], {}

    logger.info("Found %d meetings", len(meetings))

    logger.info("Stage 2: Enriching attendees via ZoomInfo...")
    zi_client = ZoomInfoClient()
    try:
        zi_client.authenticate()
    except Exception as e:
        logger.warning("ZoomInfo auth failed: %s. Continuing without.", e)
        zi_client = None

    all_attendees = {}
    for meeting in meetings:
        for att in meeting.attendees:
            if att.name not in all_attendees:
                all_attendees[att.name] = att

    enrichments = {}
    for name, attendee in all_attendees.items():
        if zi_client:
            try:
                enrichments[name] = zi_client.enrich_attendee(attendee)
                logger.info("  Enriched: %s", name)
            except Exception as e:
                logger.warning("  Failed: %s: %s", name, e)
                enrichments[name] = None
        else:
            enrichments[name] = None

    logger.info("Stage 3: Researching attendees with Claude AI...")
    insights_by_meeting = {}
    for meeting in meetings:
        attendee_insights = []
        for att in meeting.attendees:
            zoominfo = enrichments.get(att.name)
            insight = research_attendee(att, zoominfo, meeting_title=meeting.title)
            attendee_insights.append(insight)
            logger.info("  Researched: %s (for %s)", att.name, meeting.title)
        insights_by_meeting[meeting.title] = attendee_insights

    return meetings, insights_by_meeting


def run_stages_3b_to_4(meetings, insights_by_meeting, send_email: bool = True):
    """Run case study matching + synthesis + email."""
    from src.config import SUPABASE_URL
    from src.research import synthesize_meeting_brief

    meeting_briefs = []
    for meeting in meetings:
        attendee_insights = insights_by_meeting[meeting.title]

        # Stage 3b: Case study search
        case_studies = []
        industry_showcase = []
        capability_docs = []
        if SUPABASE_URL:
            try:
                logger.info("Stage 3b: Searching case studies for: %s", meeting.title)
                from src.case_study_search import search_case_studies
                case_studies, industry_showcase, capability_docs = search_case_studies(
                    meeting, attendee_insights
                )
                logger.info("  Found %d case studies + %d industry showcase + %d capability docs",
                            len(case_studies), len(industry_showcase), len(capability_docs))
            except Exception as e:
                logger.warning("  Case study search failed: %s", e)

        # Client references by industry overlap
        client_references = []
        if SUPABASE_URL:
            try:
                from src.case_study_search import search_client_references
                client_references = search_client_references(attendee_insights, meeting=meeting)
                logger.info("  Found %d client references", len(client_references))
            except Exception as e:
                logger.warning("  Client reference search failed: %s", e)

        # Stage 4: Synthesis
        brief = synthesize_meeting_brief(
            meeting, attendee_insights,
            case_studies=case_studies, industry_showcase=industry_showcase,
            capability_docs=capability_docs,
            client_references=client_references,
        )
        meeting_briefs.append(brief)
        logger.info("  Synthesized brief for: %s", meeting.title)

    daily_brief = DailyBrief(
        target_date=meetings[0].start_time.date() if meetings else date.today(),
        meeting_briefs=meeting_briefs,
    )

    if send_email:
        logger.info("Stage 4: Sending email...")
        from src.email_sender import send_daily_brief
        success = send_daily_brief(daily_brief)
        if success:
            logger.info("Email sent successfully!")
        else:
            logger.error("Failed to send email.")
    else:
        # Render HTML to file for inspection
        from jinja2 import Environment, FileSystemLoader
        env = Environment(loader=FileSystemLoader(str(PROJECT_ROOT / "templates")))
        template = env.get_template("email_brief.html")
        from src.config import ANTHROPIC_MODEL
        html = template.render(
            brief=daily_brief,
            meeting_count=len(daily_brief.meeting_briefs),
            target_date=daily_brief.target_date.strftime("%A, %B %d, %Y"),
            generated_at=daily_brief.generated_at.strftime("%I:%M %p on %B %d, %Y"),
            ai_model=ANTHROPIC_MODEL,
        )
        out_path = CACHE_DIR / "test_email.html"
        out_path.write_text(html, encoding="utf-8")
        logger.info("Email HTML rendered to: %s", out_path)


def main():
    parser = argparse.ArgumentParser(description="Test pipeline with research caching")
    parser.add_argument("--fresh", action="store_true", help="Force full run, overwrite cache")
    parser.add_argument("--no-email", action="store_true", help="Render HTML only, don't send email")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: tomorrow)")
    args = parser.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        IST = ZoneInfo("Asia/Kolkata")
        target_date = datetime.now(IST).date() + timedelta(days=1)

    CACHE_DIR.mkdir(exist_ok=True)

    if not args.fresh and CACHE_FILE.exists():
        logger.info("Loading research from cache: %s", CACHE_FILE)
        cache_data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("Cached at: %s", cache_data.get("cached_at", "unknown"))
        meetings, insights_by_meeting = _deserialize_cache(cache_data)
        logger.info("Loaded %d meetings from cache", len(meetings))
    else:
        logger.info("Running full pipeline (stages 1-3) for %s...", target_date)
        meetings, insights_by_meeting = run_stages_1_to_3(target_date)
        if not meetings:
            logger.info("No meetings found. Nothing to cache.")
            return
        # Save cache
        cache_data = _serialize_cache(meetings, insights_by_meeting)
        CACHE_FILE.write_text(json.dumps(cache_data, indent=2, default=str), encoding="utf-8")
        logger.info("Research cached to: %s", CACHE_FILE)

    if not meetings:
        logger.info("No meetings in cache.")
        return

    # Run case study matching + synthesis + email (always re-runs)
    run_stages_3b_to_4(meetings, insights_by_meeting, send_email=not args.no_email)

    logger.info("Done!")


if __name__ == "__main__":
    main()
