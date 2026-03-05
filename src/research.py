import json
import logging
import re
from typing import Optional

import requests

from src.config import PERPLEXITY_API_KEY, PERPLEXITY_MODEL, PERPLEXITY_BASE_URL
from src.models import (
    AttendeeInsight,
    Meeting,
    MeetingBrief,
    ZoomInfoEnrichment,
    Attendee,
)

logger = logging.getLogger(__name__)

CHAT_URL = f"{PERPLEXITY_BASE_URL}/chat/completions"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json",
    }


def _chat(system: str, user: str, model: str = PERPLEXITY_MODEL) -> tuple[str, list[str]]:
    """Call Perplexity chat completions API.

    Returns (response_text, citations).
    Raises requests.HTTPError on auth or other failures.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "search_recency_filter": "month",
    }

    resp = requests.post(CHAT_URL, json=payload, headers=_headers(), timeout=60)
    resp.raise_for_status()

    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    citations = data.get("citations", [])
    return text, citations


def research_attendee(
    attendee: Attendee,
    zoominfo: Optional[ZoomInfoEnrichment],
    meeting_title: str = "",
) -> AttendeeInsight:
    """Research an attendee using Perplexity Sonar (web search built-in)."""

    # Build context from ZoomInfo data
    context_parts = [f"Attendee: {attendee.name}"]
    if meeting_title:
        context_parts.append(f"Meeting: {meeting_title}")
    if attendee.email:
        context_parts.append(f"Email: {attendee.email}")
    if attendee.domain:
        context_parts.append(f"Company domain: {attendee.domain}")
    if attendee.title:
        context_parts.append(f"Title (from calendar): {attendee.title}")

    if zoominfo:
        if zoominfo.contact:
            c = zoominfo.contact
            if c.title:
                context_parts.append(f"Title: {c.title}")
            if c.phone:
                context_parts.append(f"Phone: {c.phone}")
            if c.linkedin_url:
                context_parts.append(f"LinkedIn: {c.linkedin_url}")
            if c.employment_history:
                context_parts.append(
                    f"Employment history: {json.dumps(c.employment_history[:5], default=str)}"
                )

        if zoominfo.company:
            co = zoominfo.company
            context_parts.append(f"\nCompany: {co.name}")
            if co.industry:
                context_parts.append(f"Industry: {co.industry}")
            if co.revenue:
                context_parts.append(f"Revenue: {co.revenue}")
            if co.employee_count:
                context_parts.append(f"Employees: {co.employee_count}")
            if co.description:
                context_parts.append(f"Description: {co.description}")

        if zoominfo.tech_stack:
            tech_summary = "; ".join(
                f"{ts.category}: {', '.join(ts.technologies[:5])}"
                for ts in zoominfo.tech_stack[:10]
            )
            context_parts.append(f"\nTech stack: {tech_summary}")

        if zoominfo.news:
            news = "; ".join(
                f"{n.headline} ({n.date})" for n in zoominfo.news[:5]
            )
            context_parts.append(f"\nRecent news: {news}")

    context = "\n".join(context_parts)

    system_prompt = (
        "You are a meeting preparation research assistant. "
        "Research the attendee and their company to help prepare for an upcoming meeting.\n\n"
        "IMPORTANT: Do NOT research or include results about CloudChillies or MindRuby — "
        "these are our own companies. Focus only on the external attendee and their organisation.\n\n"
        "Search for:\n"
        "1. The person's current role, background, and recent public activity\n"
        "2. Their company's latest news, funding, product launches (last 3 months)\n"
        "3. Company size, industry position, and competitive landscape\n"
        "4. Recent job postings that reveal strategic priorities\n\n"
        "Respond in this exact JSON format:\n"
        "{\n"
        '    "web_research_summary": "A 2-3 paragraph summary of key findings",\n'
        '    "talking_points": ["point 1", "point 2", "point 3", "point 4", "point 5"]\n'
        "}\n\n"
        "Talking points should be specific, actionable conversation starters. "
        "Keep each point to 1-2 sentences."
    )

    user_message = (
        f"Research this meeting attendee and their company.\n\n"
        f"KNOWN DATA:\n{context}\n\n"
        f"Find the latest information and provide your research summary and talking points as JSON."
    )

    # Capture the full prompt for transparency
    full_prompt = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_message}"

    logger.info("Researching attendee: %s", attendee.name)

    try:
        result_text, citations = _chat(system_prompt, user_message)
        parsed = _parse_json_response(result_text)

        # Append citation URLs to the research summary
        summary = parsed.get("web_research_summary", result_text)
        if citations:
            source_list = "\n".join(f"- {url}" for url in citations[:10])
            summary += f"\n\nSources:\n{source_list}"

        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=summary,
            talking_points=parsed.get("talking_points", []),
            research_prompt=full_prompt,
        )

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            raise  # propagate auth errors so main.py can fall back
        logger.error("Research failed for %s: %s", attendee.name, e)
        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=f"Research unavailable: {e}",
            talking_points=[],
        )
    except Exception as e:
        logger.error("Research failed for %s: %s", attendee.name, e)
        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=f"Research unavailable: {e}",
            talking_points=[],
        )


def synthesize_meeting_brief(
    meeting: Meeting,
    attendee_insights: list[AttendeeInsight],
) -> MeetingBrief:
    """Synthesize a meeting brief from all attendee insights."""

    # Build context from all attendee insights
    insights_text = []
    for insight in attendee_insights:
        parts = [f"\n--- {insight.attendee.name} ---"]
        if insight.attendee.title:
            parts.append(f"Title: {insight.attendee.title}")
        if insight.zoominfo and insight.zoominfo.contact:
            parts.append(f"ZoomInfo title: {insight.zoominfo.contact.title}")
        if insight.zoominfo and insight.zoominfo.company:
            parts.append(f"Company: {insight.zoominfo.company.name}")
        parts.append(f"Research: {insight.web_research_summary}")
        if insight.talking_points:
            parts.append("Talking points: " + "; ".join(insight.talking_points))
        insights_text.append("\n".join(parts))

    all_insights = "\n".join(insights_text)

    system_prompt = (
        "You are a meeting preparation strategist. Given research on meeting "
        "attendees, synthesize key themes and suggest strategic questions.\n\n"
        "Respond in this exact JSON format:\n"
        "{\n"
        '    "key_themes": ["theme 1", "theme 2", "theme 3"],\n'
        '    "suggested_questions": ["question 1", "question 2", "question 3", "question 4", "question 5"]\n'
        "}\n\n"
        "Key themes should capture cross-cutting patterns across attendees.\n"
        "Questions should be strategic, open-ended, and designed to build rapport."
    )

    user_message = (
        f"Meeting: {meeting.title}\n"
        f"Time: {meeting.start_time.strftime('%I:%M %p')} - {meeting.end_time.strftime('%I:%M %p')}\n\n"
        f"Attendee Research:\n{all_insights}\n\n"
        f"Synthesize key themes and suggest strategic questions for this meeting."
    )

    logger.info("Synthesizing brief for meeting: %s", meeting.title)

    try:
        result_text, _ = _chat(system_prompt, user_message)
        parsed = _parse_json_response(result_text)

        return MeetingBrief(
            meeting=meeting,
            attendee_insights=attendee_insights,
            key_themes=parsed.get("key_themes", []),
            suggested_questions=parsed.get("suggested_questions", []),
        )

    except Exception as e:
        logger.error("Synthesis failed for %s: %s", meeting.title, e)
        return MeetingBrief(
            meeting=meeting,
            attendee_insights=attendee_insights,
        )


def _parse_json_response(text: str) -> dict:
    """Parse JSON from the response, handling markdown code blocks."""
    text = text.strip()

    # Try to extract JSON from markdown code block
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end])
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse JSON from response")
        return {}
