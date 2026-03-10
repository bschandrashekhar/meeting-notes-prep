import json
import logging
import re
from typing import Optional

import anthropic

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from src.models import (
    AttendeeInsight,
    CaseStudyMatch,
    Meeting,
    MeetingBrief,
    ZoomInfoEnrichment,
    Attendee,
)

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _chat(system: str, user: str, model: str = ANTHROPIC_MODEL) -> tuple[str, list[str]]:
    """Call Anthropic API with web search tool.

    Returns (response_text, source_urls).
    Raises anthropic.AuthenticationError on auth failures.
    """
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}],
        messages=[{"role": "user", "content": user}],
    )

    text_parts = []
    source_urls = []

    for block in response.content:
        if getattr(block, "type", "") == "text":
            text_parts.append(block.text)
            for citation in getattr(block, "citations", None) or []:
                url = getattr(citation, "url", "")
                if url:
                    source_urls.append(url)
        elif getattr(block, "type", "") == "web_search_tool_result":
            for result in getattr(block, "search_results", []):
                url = getattr(result, "url", "")
                if url:
                    source_urls.append(url)

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for url in source_urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    return "\n".join(text_parts), unique_urls


def research_attendee(
    attendee: Attendee,
    zoominfo: Optional[ZoomInfoEnrichment],
    meeting_title: str = "",
) -> AttendeeInsight:
    """Research an attendee using Claude with web search."""

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
        "Use web search to research the attendee and their company to help prepare for an upcoming meeting.\n\n"
        "IMPORTANT: Do NOT research or include results about CloudChillies or MindRuby — "
        "these are our own companies. Focus only on the external attendee and their organisation.\n\n"
        "Search for:\n"
        "1. The person's current role, background, and recent public activity\n"
        "2. Their company's latest news, funding, product launches (last 3 months)\n"
        "3. Company size, industry position, and competitive landscape\n"
        "4. Recent job postings that reveal strategic priorities\n"
        "5. Technology stack and tools the company likely uses (from job postings, tech blogs, or public info)\n\n"
        "Respond in this exact JSON format:\n"
        "{\n"
        '    "web_research_summary": ["key finding 1", "key finding 2", "key finding 3", "..."],\n'
        '    "talking_points": ["point 1", "point 2", "point 3", "point 4", "point 5"]\n'
        "}\n\n"
        "web_research_summary: 5-7 bullet points covering the person's role, company news, "
        "industry position, strategic priorities, and likely technology stack / tools in use. "
        "Each bullet should be 1-2 sentences.\n\n"
        "talking_points: 3-5 personalised ice-breakers specific to THIS person — things you "
        "can say to build rapport based on their background, recent activity, or company news. "
        "Keep each point to 1-2 sentences."
    )

    user_message = (
        f"Research this meeting attendee and their company.\n\n"
        f"KNOWN DATA:\n{context}\n\n"
        f"Find the latest information and provide your research summary and talking points as JSON."
    )

    logger.info("Researching attendee: %s", attendee.name)

    try:
        result_text, citations = _chat(system_prompt, user_message)
        parsed = _parse_json_response(result_text)

        summary_raw = parsed.get("web_research_summary", [])
        # Handle if model returns a string instead of list
        if isinstance(summary_raw, str):
            summary_raw = [s.strip() for s in summary_raw.split("\n") if s.strip()]
        # Handle if model returns list of dicts like {"finding": "...", "citations": [...]}
        summary_raw = [
            item["finding"] if isinstance(item, dict) and "finding" in item
            else str(item) if not isinstance(item, str) else item
            for item in summary_raw
        ]

        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=summary_raw,
            source_urls=citations[:10],
            talking_points=parsed.get("talking_points", []),
        )

    except anthropic.AuthenticationError:
        raise  # propagate auth errors so main.py can fall back
    except Exception as e:
        logger.error("Research failed for %s: %s", attendee.name, e)
        return AttendeeInsight(
            attendee=attendee,
            zoominfo=zoominfo,
            web_research_summary=[f"Research unavailable: {e}"],
            talking_points=[],
        )


def synthesize_meeting_brief(
    meeting: Meeting,
    attendee_insights: list[AttendeeInsight],
    case_studies: list[CaseStudyMatch] | None = None,
    capability_docs: list[CaseStudyMatch] | None = None,
) -> MeetingBrief:
    """Synthesize a meeting brief from all attendee insights and case studies."""

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
        parts.append(f"Research: {'; '.join(insight.web_research_summary)}")
        if insight.talking_points:
            parts.append("Talking points: " + "; ".join(insight.talking_points))
        insights_text.append("\n".join(parts))

    all_insights = "\n".join(insights_text)

    # Build case study context
    case_study_context = ""
    if case_studies:
        cs_parts = ["\n\nRelevant Case Studies (from our portfolio):"]
        for i, cs in enumerate(case_studies, 1):
            cs_parts.append(
                f"\n{i}. {cs.filename} (Company: {cs.company_name}, "
                f"Use Case: {cs.use_case}, Match: {cs.similarity_score:.0%})\n"
                f"   Summary: {cs.summary}"
            )
        case_study_context = "\n".join(cs_parts)

    if capability_docs:
        cd_parts = ["\n\nIndustry Capability Documents (for reference):"]
        for i, cd in enumerate(capability_docs, 1):
            cd_parts.append(
                f"\n{i}. {cd.filename} (Company: {cd.company_name}, "
                f"Use Case: {cd.use_case}, Match: {cd.similarity_score:.0%})\n"
                f"   Summary: {cd.summary}"
            )
        case_study_context += "\n".join(cd_parts)

    case_study_json_schema = ""
    case_study_instruction = ""
    if case_studies:
        case_study_json_schema = (
            ',\n'
            '    "case_study_relevance": {"filename1.pdf": "Why this case study is relevant", '
            '"filename2.pdf": "Why this one is relevant"},\n'
            '    "case_study_briefs": {"filename1.pdf": "A concise 2-line description of the case study", '
            '"filename2.pdf": "A concise 2-line description"},\n'
            '    "conversation_flow": ["Step 1: how to introduce first case study", '
            '"Step 2: transition to next case study", "Step 3: ..."]'
        )
        case_study_instruction = (
            "\nFor each case study:\n"
            "- In case_study_relevance: explain in 1-2 sentences why it's relevant to this meeting.\n"
            "- In case_study_briefs: write a concise 2-line description of what the case study covers "
            "(the client problem and the outcome achieved).\n\n"
            "For conversation_flow: provide 3-5 bullet points as a list, each describing a step "
            "in the conversation where you naturally bring up a case study. Include specific transition "
            "phrases like 'We recently worked with...' or 'This reminds me of a similar challenge at...'. "
            "Each bullet should name the case study and suggest when/how to introduce it."
        )

    system_prompt = (
        "You are a meeting preparation strategist. Given research on meeting "
        "attendees, synthesize key themes and suggest strategic questions.\n\n"
        "Respond in this exact JSON format:\n"
        "{\n"
        '    "key_themes": ["theme 1", "theme 2", "theme 3"],\n'
        '    "suggested_questions": ["question 1", "question 2", "question 3", "question 4", "question 5"]'
        f"{case_study_json_schema}\n"
        "}\n\n"
        "key_themes: 3-5 cross-cutting patterns or insights that span across all attendees "
        "and the meeting agenda — industry trends, shared challenges, or strategic opportunities.\n\n"
        "suggested_questions: 4-6 strategic, open-ended questions to drive the meeting discussion. "
        "These should be about the business problem, decision criteria, and next steps — NOT about "
        "the person's background (those are covered separately as talking points)."
        f"{case_study_instruction}"
    )

    user_message = (
        f"Meeting: {meeting.title}\n"
        f"Time: {meeting.start_time.strftime('%I:%M %p')} - {meeting.end_time.strftime('%I:%M %p')}\n"
    )
    if meeting.agenda:
        user_message += f"Agenda: {meeting.agenda}\n"
    user_message += (
        f"\nAttendee Research:\n{all_insights}"
        f"{case_study_context}\n\n"
        f"Synthesize key themes and suggest strategic questions for this meeting."
    )

    logger.info("Synthesizing brief for meeting: %s", meeting.title)

    try:
        result_text, _ = _chat(system_prompt, user_message)
        parsed = _parse_json_response(result_text)

        # Populate relevance notes and brief descriptions on case studies
        enriched_case_studies = list(case_studies) if case_studies else []
        enriched_capability_docs = list(capability_docs) if capability_docs else []
        relevance_map = parsed.get("case_study_relevance", {})
        briefs_map = parsed.get("case_study_briefs", {})
        for cs in enriched_case_studies + enriched_capability_docs:
            cs.relevance_note = relevance_map.get(cs.filename, "")
            cs.brief_description = briefs_map.get(cs.filename, "")

        return MeetingBrief(
            meeting=meeting,
            attendee_insights=attendee_insights,
            key_themes=parsed.get("key_themes", []),
            suggested_questions=parsed.get("suggested_questions", []),
            recommended_case_studies=enriched_case_studies,
            reference_capabilities=enriched_capability_docs,
            conversation_flow=parsed.get("conversation_flow", []),
        )

    except Exception as e:
        logger.error("Synthesis failed for %s: %s", meeting.title, e)
        return MeetingBrief(
            meeting=meeting,
            attendee_insights=attendee_insights,
            recommended_case_studies=list(case_studies) if case_studies else [],
            reference_capabilities=list(capability_docs) if capability_docs else [],
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
