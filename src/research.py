import json
import logging
from typing import Optional

import anthropic

from src.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from src.models import (
    AttendeeInsight,
    DailyBrief,
    Meeting,
    MeetingBrief,
    ZoomInfoEnrichment,
    Attendee,
)

logger = logging.getLogger(__name__)

# Server-side tools for web search
WEB_SEARCH_TOOLS = [
    {"type": "web_search_20250305", "name": "web_search"},
]


def _get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def research_attendee(
    attendee: Attendee,
    zoominfo: Optional[ZoomInfoEnrichment],
) -> AttendeeInsight:
    """Research an attendee using Claude with web search to fill gaps."""
    client = _get_client()

    # Build context from ZoomInfo data
    context_parts = [f"Attendee: {attendee.name} ({attendee.email})"]
    context_parts.append(f"Company domain: {attendee.domain}")

    if zoominfo:
        if zoominfo.contact:
            c = zoominfo.contact
            context_parts.append(f"Title: {c.title}")
            if c.phone:
                context_parts.append(f"Phone: {c.phone}")
            if c.linkedin_url:
                context_parts.append(f"LinkedIn: {c.linkedin_url}")
            if c.employment_history:
                context_parts.append(
                    f"Employment history: {json.dumps(c.employment_history[:5], default=str)}"
                )
            if c.education:
                context_parts.append(
                    f"Education: {json.dumps(c.education[:3], default=str)}"
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
            if co.funding:
                context_parts.append(f"Funding: {co.funding}")
            if co.description:
                context_parts.append(f"Description: {co.description}")
            if co.headquarters:
                context_parts.append(f"HQ: {co.headquarters}")

        if zoominfo.tech_stack:
            tech_summary = "; ".join(
                f"{ts.category}: {', '.join(ts.technologies[:5])}"
                for ts in zoominfo.tech_stack[:10]
            )
            context_parts.append(f"\nTech stack: {tech_summary}")

        if zoominfo.intent_signals:
            signals = "; ".join(
                f"{s.topic} (score: {s.score})"
                for s in zoominfo.intent_signals[:10]
            )
            context_parts.append(f"\nIntent signals: {signals}")

        if zoominfo.news:
            news = "; ".join(
                f"{n.headline} ({n.date})" for n in zoominfo.news[:5]
            )
            context_parts.append(f"\nRecent news: {news}")

    context = "\n".join(context_parts)

    system_prompt = """You are a meeting preparation research assistant. Your job is to research
meeting attendees and their companies to help prepare for an upcoming meeting.

Given the ZoomInfo data (which may have gaps), use web search to:
1. Fill in any missing information about the person and their company
2. Find the latest news about the company (last 3 months)
3. Check for recent job postings that reveal strategic priorities
4. Look for the person's recent public activity (talks, articles, social media)
5. Identify the competitive landscape

Respond in this exact JSON format:
{
    "web_research_summary": "A 2-3 paragraph summary of key findings from web research that adds to or updates the ZoomInfo data",
    "talking_points": ["point 1", "point 2", "point 3", "point 4", "point 5"]
}

The talking_points should be specific, actionable conversation starters relevant to this
person and their company. Focus on recent developments, shared interests, or strategic topics.
Keep each point to 1-2 sentences."""

    user_message = f"""Research this meeting attendee and their company. Fill gaps in the data
and find the latest relevant information.

KNOWN DATA:
{context}

Search the web to find the latest information, then provide your research summary and
talking points as JSON."""

    logger.info("Researching attendee: %s", attendee.name)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=WEB_SEARCH_TOOLS,
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract the final text response (after any web search tool calls)
        result_text = _extract_text(response)

        # Handle the server-side tool loop (web search may need multiple turns)
        messages = [{"role": "user", "content": user_message}]
        while response.stop_reason == "tool_use" or response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})

            # For server-side tools, just send back the response to continue
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Continue searching.",
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=4096,
                system=system_prompt,
                tools=WEB_SEARCH_TOOLS,
                messages=messages,
            )

        result_text = _extract_text(response)
        parsed = _parse_json_response(result_text)

        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=parsed.get("web_research_summary", result_text),
            talking_points=parsed.get("talking_points", []),
        )

    except anthropic.AuthenticationError:
        raise  # propagate so main.py can fall back to ZoomInfo-only briefs
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
    client = _get_client()

    # Build context from all attendee insights
    insights_text = []
    for insight in attendee_insights:
        parts = [f"\n--- {insight.attendee.name} ({insight.attendee.email}) ---"]
        if insight.zoominfo and insight.zoominfo.contact:
            parts.append(f"Title: {insight.zoominfo.contact.title}")
        if insight.zoominfo and insight.zoominfo.company:
            parts.append(f"Company: {insight.zoominfo.company.name}")
        parts.append(f"Research: {insight.web_research_summary}")
        if insight.talking_points:
            parts.append("Talking points: " + "; ".join(insight.talking_points))
        insights_text.append("\n".join(parts))

    all_insights = "\n".join(insights_text)

    system_prompt = """You are a meeting preparation strategist. Given research on meeting
attendees, synthesize key themes and suggest strategic questions for the meeting.

Respond in this exact JSON format:
{
    "key_themes": ["theme 1", "theme 2", "theme 3"],
    "suggested_questions": ["question 1", "question 2", "question 3", "question 4", "question 5"]
}

Key themes should capture cross-cutting patterns across attendees.
Suggested questions should be strategic, open-ended, and designed to build rapport
and advance the conversation."""

    user_message = f"""Meeting: {meeting.title}
Time: {meeting.start_time.strftime("%I:%M %p")} - {meeting.end_time.strftime("%I:%M %p")}

Attendee Research:
{all_insights}

Synthesize the key themes and suggest strategic questions for this meeting."""

    logger.info("Synthesizing brief for meeting: %s", meeting.title)

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        result_text = _extract_text(response)
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


def _extract_text(response) -> str:
    """Extract text content from a Claude API response."""
    texts = []
    for block in response.content:
        if hasattr(block, "text"):
            texts.append(block.text)
    return "\n".join(texts)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from Claude's response, handling markdown code blocks."""
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
