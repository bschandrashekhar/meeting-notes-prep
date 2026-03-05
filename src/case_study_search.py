"""Case study vector search via Supabase pgvector + Voyage AI embeddings."""

import logging
from typing import Optional

import voyageai
from supabase import create_client, Client

from src.config import SUPABASE_SERVICE_KEY, SUPABASE_URL, VOYAGE_API_KEY
from src.models import AttendeeInsight, CaseStudyMatch, Meeting

logger = logging.getLogger(__name__)

_supabase: Optional[Client] = None
_voyage: Optional[voyageai.Client] = None


def _get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _supabase


def _get_voyage() -> voyageai.Client:
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
    return _voyage


def search_case_studies(
    meeting: Meeting,
    attendee_insights: list[AttendeeInsight],
    match_count: int = 5,
) -> list[CaseStudyMatch]:
    """Search for relevant case studies based on meeting context.

    Uses the meeting agenda as the primary signal, supplemented by
    attendee company/industry information.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not VOYAGE_API_KEY:
        logger.info("Case study search skipped — missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or VOYAGE_API_KEY")
        return []

    # Build search query from meeting context
    query_parts = []

    # Primary signal: agenda
    if meeting.agenda:
        query_parts.append(f"Meeting agenda: {meeting.agenda}")
    else:
        query_parts.append(f"Meeting topic: {meeting.title}")

    # Secondary signals: attendee context
    for insight in attendee_insights:
        if insight.zoominfo and insight.zoominfo.company:
            co = insight.zoominfo.company
            if co.industry:
                query_parts.append(f"Client industry: {co.industry}")
            if co.description:
                query_parts.append(f"Client business: {co.description[:200]}")
        elif insight.attendee.domain:
            query_parts.append(f"Client domain: {insight.attendee.domain}")

    query_text = "\n".join(query_parts)
    logger.info("Case study search query:\n%s", query_text[:300])

    try:
        # Generate query embedding
        voyage = _get_voyage()
        result = voyage.embed(
            [query_text[:8000]],
            model="voyage-3-large",
            input_type="query",
        )
        query_embedding = result.embeddings[0]

        # Search Supabase via RPC
        supabase = _get_supabase()
        response = supabase.rpc(
            "match_case_studies",
            {
                "query_embedding": query_embedding,
                "match_count": match_count,
                "match_threshold": 0.3,
            },
        ).execute()

        matches = []
        for row in response.data:
            matches.append(CaseStudyMatch(
                filename=row["filename"],
                company_name=row.get("company_name", ""),
                use_case=row.get("use_case", ""),
                doc_type=row.get("doc_type", ""),
                summary=row.get("summary", ""),
                similarity_score=round(row.get("similarity", 0.0), 3),
            ))

        logger.info("Found %d matching case studies", len(matches))
        for m in matches:
            logger.info("  %.3f — %s (%s)", m.similarity_score, m.filename, m.company_name)

        return matches

    except Exception as e:
        logger.error("Case study search failed: %s", e)
        return []
