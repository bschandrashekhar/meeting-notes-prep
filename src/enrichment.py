"""Enrichment — tech extraction (Claude), case study / client / brand matching."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
from supabase import create_client

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    SIGNALS_TO_LOOK_FOR,
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
    normalize_country,
)
from src.models import AttendeeInsight, EnrichedMeeting, MeetingInput

logger = logging.getLogger(__name__)

# Lazy-init Anthropic client
_anthropic: anthropic.Anthropic | None = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic


# ---------------------------------------------------------------------------
# Step 0 — Technology extraction
# ---------------------------------------------------------------------------

_TECH_SYSTEM_PROMPT = (
    "You will be given COMPANY_TECH_INFO for a prospect company. "
    "Based solely on these snippets, extract a list of technologies. "
    "Only include technologies explicitly mentioned in the input. "
    "Return a JSON array of strings, e.g. [\"Salesforce\", \"Snowflake\"]. "
    "If no technologies are found, return an empty array []."
)


def extract_technologies(company_tech_info: str) -> list[str]:
    """Use Claude to extract technology names from free-text tech info."""
    if not company_tech_info.strip():
        return []

    client = _get_anthropic()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=_TECH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": company_tech_info}],
    )

    text = response.content[0].text.strip()

    # Extract JSON array from response (may be wrapped in markdown)
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Failed to parse tech JSON: %s", text)
            return []
    return []


# ---------------------------------------------------------------------------
# Step helper — Fetch logo URLs for matched clients
# ---------------------------------------------------------------------------

def _fetch_client_logos(client_names: list[str]) -> dict[str, str]:
    """Query Supabase for logo_url of matched client names."""
    if not client_names:
        return {}

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    result = (
        sb.table("client_referencing_data")
        .select("client_name, logo_url")
        .in_("client_name", client_names)
        .execute()
    )
    return {
        row["client_name"]: row.get("logo_url", "")
        for row in (result.data or [])
        if row.get("logo_url")
    }


# ---------------------------------------------------------------------------
# Step 3 — Case study narrative generation
# ---------------------------------------------------------------------------

_NARRATIVE_SYSTEM_PROMPT = (
    "You are a sales meeting preparation assistant. "
    "Given the prospect context and matched case studies, write a conversational "
    "bullet point for each case study. Each bullet should explain how to naturally "
    "reference that case study during the meeting, connecting the solution to the "
    "prospect's specific situation. Keep each bullet to 2-3 sentences. "
    "Return ONLY a JSON array of strings (one per case study)."
)


def _generate_case_study_narrative(
    matches: list[dict[str, Any]], prospect_context: str
) -> list[str]:
    """Use Claude to weave case study summaries into conversational bullets."""
    if not matches:
        return []

    summaries = []
    for m in matches:
        name = m.get("casestudy_name", "Unnamed")
        solution = m.get("summary_solution", "")
        summaries.append(f"Case Study: {name}\nSolution: {solution}")

    user_msg = (
        f"PROSPECT CONTEXT:\n{prospect_context}\n\n"
        f"MATCHED CASE STUDIES:\n" + "\n\n".join(summaries)
    )

    client = _get_anthropic()
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=2048,
        system=_NARRATIVE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Failed to parse narrative JSON: %s", text)

    # Fallback — return raw text split by newlines
    return [line.strip("- •").strip() for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Step 4 — Attendee LinkedIn enrichment
# ---------------------------------------------------------------------------

def _fetch_all_client_names() -> list[str]:
    """Get all client names from client_referencing_data for signal detection."""
    from client_referencing.matcher import fetch_all_rows
    rows = fetch_all_rows()
    return list({row["client_name"] for row in rows if row.get("client_name")})


_LINKEDIN_SYSTEM_PROMPT = (
    "You are a sales meeting preparation assistant. "
    "You will be given a LinkedIn URL to search, a list of signal terms to look for, "
    "and a list of client company names to check against. "
    "Do a single first-level web search for the LinkedIn URL. Do NOT do follow-up searches. "
    "Based on whatever you find, return a JSON object with these keys:\n"
    '- "profile_summary": brief summary of what you found (title, company, notable points)\n'
    '- "signal_matches": array of signal terms (from the provided list) found in the search results\n'
    '- "client_matches": array of client names (from the provided list) found in the search results (loose matching — abbreviations or slight variations count)\n'
    '- "suggested_questions": array of exactly 3 compelling questions to ask this person in a meeting\n'
    "Return ONLY the JSON object, no other text."
)


def _enrich_attendee_via_linkedin(
    attendee: "Attendee",
    prospect_context: str,
    signals: set[str],
    client_names: list[str],
) -> AttendeeInsight:
    """Use Claude web search to research an attendee's LinkedIn profile."""
    from src.models import Attendee

    if not attendee.linkedin_url.strip():
        return AttendeeInsight(attendee_name=attendee.name)

    user_msg = (
        f"LinkedIn URL: {attendee.linkedin_url}\n"
        f"Person: {attendee.name}"
        + (f" — {attendee.title}" if attendee.title else "")
        + f"\n\nSIGNALS TO LOOK FOR (check if any of these terms appear in the search results):\n"
        f"{json.dumps(sorted(signals))}\n\n"
        f"CLIENT NAMES TO CHECK (check if any of these company names appear):\n"
        f"{json.dumps(client_names)}\n\n"
        f"PROSPECT CONTEXT (use this to craft the 3 suggested questions):\n"
        f"{prospect_context}"
    )

    try:
        client = _get_anthropic()
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2048,
            system=_LINKEDIN_SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": user_msg}],
        )

        # Extract text blocks from response (may have tool_use blocks interspersed)
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        full_text = "\n".join(text_parts).strip()

        # Parse JSON — handle markdown code blocks
        if "```json" in full_text:
            full_text = full_text.split("```json")[1].split("```")[0].strip()
        elif "```" in full_text:
            full_text = full_text.split("```")[1].split("```")[0].strip()

        data = json.loads(full_text)
        return AttendeeInsight(
            attendee_name=attendee.name,
            linkedin_url=attendee.linkedin_url,
            profile_summary=data.get("profile_summary", ""),
            signal_matches=data.get("signal_matches", []),
            client_matches=data.get("client_matches", []),
            suggested_questions=data.get("suggested_questions", [])[:3],
        )

    except json.JSONDecodeError:
        logger.warning("Failed to parse LinkedIn enrichment JSON for %s", attendee.name)
        return AttendeeInsight(
            attendee_name=attendee.name,
            linkedin_url=attendee.linkedin_url,
            enrichment_error="Failed to parse response",
        )
    except Exception as exc:
        logger.warning("LinkedIn enrichment failed for %s: %s", attendee.name, exc)
        return AttendeeInsight(
            attendee_name=attendee.name,
            linkedin_url=attendee.linkedin_url,
            enrichment_error=str(exc),
        )


# ---------------------------------------------------------------------------
# Main enrichment orchestrator
# ---------------------------------------------------------------------------

def enrich_meeting(meeting: MeetingInput) -> EnrichedMeeting:
    """Run all three enrichment steps for a single meeting."""
    # Import client_referencing here (after config.py has loaded .env)
    from client_referencing import find_casestudy_matches, find_matches
    from client_referencing.brand_matcher import find_brand_match

    # Build prospect context
    prospect_context = " ".join(
        filter(None, [
            meeting.agenda,
            meeting.company_information,
            meeting.company_tech_info,
        ])
    )

    # Step 0: Extract technologies
    logger.info("Extracting technologies for '%s'", meeting.subject)
    prospect_technologies = extract_technologies(meeting.company_tech_info)
    techs_csv = ", ".join(prospect_technologies)
    logger.info("Extracted technologies: %s", techs_csv)

    # Normalize country
    normalized_country = normalize_country(meeting.company_country)
    logger.info("Country '%s' -> '%s'", meeting.company_country, normalized_country)

    # Step 1: Case study matching
    logger.info("Finding case study matches …")
    cs_result = find_casestudy_matches(
        prospect_context=prospect_context,
        prospect_industry=meeting.prospect_industry,
        prospect_technologies=techs_csv,
        max_matches=5,
    )
    cs_matches = [m.to_dict() for m in cs_result.get("matches", [])]

    # Step 2: Client matching
    logger.info("Finding client matches …")
    client_result = find_matches(
        prospect_industry=meeting.prospect_industry,
        prospect_technologies=techs_csv,
        prospect_country=normalized_country,
        max_matches=6,
    )
    client_matches_raw = client_result.get("matches", [])
    client_matches = [m.to_dict() for m in client_matches_raw]

    # Fetch logo URLs
    client_names = [m["client_name"] for m in client_matches]
    logos = _fetch_client_logos(client_names)
    for m in client_matches:
        m["logo_url"] = logos.get(m["client_name"], "")

    # Step 3: Brand matching
    logger.info("Finding brand match …")
    brand_result = find_brand_match(prospect_industry=meeting.prospect_industry)

    # Generate conversational narrative for case studies
    logger.info("Generating case study narrative …")
    narrative = _generate_case_study_narrative(cs_matches, prospect_context)

    # Step 4: Attendee LinkedIn enrichment
    logger.info("Enriching attendees via LinkedIn …")
    all_client_names = _fetch_all_client_names()
    attendee_insights = []
    for att in meeting.attendees:
        if att.linkedin_url.strip():
            logger.info("Researching LinkedIn for %s …", att.name)
            insight = _enrich_attendee_via_linkedin(
                att, prospect_context, SIGNALS_TO_LOOK_FOR, all_client_names
            )
        else:
            insight = AttendeeInsight(attendee_name=att.name)
        attendee_insights.append(insight)

    return EnrichedMeeting(
        input=meeting,
        prospect_context=prospect_context,
        prospect_technologies=prospect_technologies,
        normalized_country=normalized_country,
        case_study_matches=cs_matches,
        client_matches=client_matches,
        brand_result=brand_result,
        case_study_narrative=narrative,
        attendee_insights=attendee_insights,
    )
