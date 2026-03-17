"""Case study vector search via Supabase pgvector + Voyage AI embeddings + reranking."""

import logging
from typing import Optional

import voyageai
from supabase import create_client, Client

from src.config import SUPABASE_SERVICE_KEY, SUPABASE_URL, VOYAGE_API_KEY
from src.models import AttendeeInsight, CaseStudyMatch, ClientReference, Meeting

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


def _fetch_all_capability_docs() -> list[CaseStudyMatch]:
    """Fetch all Capability Documents from Supabase (no matching needed)."""
    try:
        supabase = _get_supabase()
        response = (
            supabase.table("case_studies")
            .select("filename, company_name, use_case, doc_type, tags, industry, summary")
            .eq("doc_type", "Capability Document")
            .execute()
        )
        docs = []
        for row in response.data or []:
            match = CaseStudyMatch(
                filename=row["filename"],
                company_name=row.get("company_name", ""),
                use_case=row.get("use_case", ""),
                doc_type=row.get("doc_type", ""),
                tags=row.get("tags", ""),
                industry=row.get("industry", ""),
                summary=row.get("summary", ""),
            )
            # Generate signed URL
            try:
                signed = supabase.storage.from_("case-studies").create_signed_url(
                    match.filename, 86400
                )
                if signed and signed.get("signedURL"):
                    match.download_url = signed["signedURL"]
            except Exception:
                pass
            docs.append(match)
        logger.info("Fetched %d capability documents", len(docs))
        return docs
    except Exception as e:
        logger.error("Failed to fetch capability documents: %s", e)
        return []


def search_case_studies(
    meeting: Meeting,
    attendee_insights: list[AttendeeInsight],
    match_count: int = 5,
) -> tuple[list[CaseStudyMatch], list[CaseStudyMatch], list[CaseStudyMatch]]:
    """Search for relevant case studies based on meeting context.

    Uses the meeting agenda as the primary signal, supplemented by
    attendee company/industry information.

    Returns (case_studies, industry_showcase, capability_documents):
      - case_studies: top matches by relevance (excludes capability docs)
      - industry_showcase: top matches by industry/vertical (excludes capability docs and duplicates from case_studies)
      - capability_documents: all capability docs from DB (no matching)
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not VOYAGE_API_KEY:
        logger.info("Case study search skipped — missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or VOYAGE_API_KEY")
        return [], [], []

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
        # Include web research findings for richer context
        if insight.web_research_summary:
            query_parts.append(f"Client background: {' '.join(insight.web_research_summary[:3])}")

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

        # Build keyword search query from key terms
        keyword_parts = []
        if meeting.agenda:
            keyword_parts.append(meeting.agenda)
        for insight in attendee_insights:
            if insight.zoominfo and insight.zoominfo.company:
                co = insight.zoominfo.company
                if co.industry:
                    keyword_parts.append(co.industry)
            if insight.web_research_summary:
                keyword_parts.extend(insight.web_research_summary[:2])
        search_query = " ".join(keyword_parts)[:1000]

        # Hybrid search: vector similarity + full-text keyword matching (RRF)
        supabase = _get_supabase()
        response = supabase.rpc(
            "match_case_studies",
            {
                "query_embedding": query_embedding,
                "match_count": match_count * 4,
                "match_threshold": 0.15,
                "search_query": search_query,
            },
        ).execute()

        if not response.data:
            logger.info("No case studies matched the similarity threshold")
            return [], [], _fetch_all_capability_docs()

        # Build candidate list from vector search results (exclude capability docs)
        candidates = []
        for row in response.data:
            if row.get("doc_type") == "Capability Document":
                continue
            candidates.append({
                "match": CaseStudyMatch(
                    filename=row["filename"],
                    company_name=row.get("company_name", ""),
                    use_case=row.get("use_case", ""),
                    doc_type=row.get("doc_type", ""),
                    tags=row.get("tags", ""),
                    industry=row.get("industry", ""),
                    summary=row.get("summary", ""),
                    similarity_score=round(row.get("similarity", 0.0), 3),
                ),
                "summary": row.get("summary", ""),
            })

        logger.info("Vector search returned %d case study candidates (capability docs excluded), reranking...", len(candidates))

        # Rerank candidates using Voyage AI cross-encoder
        rerank_docs = []
        for c in candidates:
            m = c["match"]
            parts = [f"{m.company_name} — {m.use_case}"]
            if m.industry:
                parts.append(f"Industry: {m.industry}")
            if m.tags:
                parts.append(f"Tags: {m.tags}")
            parts.append(c["summary"])
            rerank_docs.append(". ".join(parts))
        rerank_result = voyage.rerank(
            query=query_text[:8000],
            documents=rerank_docs,
            model="rerank-2",
            top_k=min(match_count * 3, len(candidates)),
        )

        # Top 5 case studies by relevance
        case_studies = []
        for item in rerank_result.results:
            candidate = candidates[item.index]["match"]
            candidate.similarity_score = round(item.relevance_score, 3)
            case_studies.append(candidate)
        case_studies = case_studies[:match_count]
        top_filenames = {cs.filename for cs in case_studies}

        # Industry showcase: find attendee industries, then search by industry
        industries = set()
        for insight in attendee_insights:
            if insight.zoominfo and insight.zoominfo.company and insight.zoominfo.company.industry:
                industries.add(insight.zoominfo.company.industry)
        # Also try to extract industry from web research
        if not industries and candidates:
            # Use the top candidate's industry as a fallback signal
            for c in candidates:
                if c["match"].industry:
                    industries.add(c["match"].industry)
                    break

        industry_showcase = []
        if industries:
            industry_query = " ".join(industries)
            logger.info("Industry showcase search for: %s", industry_query)

            # Rerank all candidates against industry query
            industry_rerank = voyage.rerank(
                query=f"Industry: {industry_query}",
                documents=rerank_docs,
                model="rerank-2",
                top_k=min(match_count + len(top_filenames), len(candidates)),
            )
            for item in industry_rerank.results:
                candidate = candidates[item.index]["match"]
                if candidate.filename in top_filenames:
                    continue  # already in case studies
                candidate.similarity_score = round(item.relevance_score, 3)
                industry_showcase.append(candidate)
                if len(industry_showcase) >= match_count:
                    break

        # Generate signed download URLs for all matched documents
        all_matches = case_studies + industry_showcase
        for m in all_matches:
            try:
                signed = supabase.storage.from_("case-studies").create_signed_url(
                    m.filename, 86400  # 24-hour link
                )
                if signed and signed.get("signedURL"):
                    m.download_url = signed["signedURL"]
            except Exception as e:
                logger.warning("Could not generate signed URL for %s: %s", m.filename, e)

        # Fetch all capability documents (no matching)
        capability_docs = _fetch_all_capability_docs()

        logger.info("Results: %d case studies + %d industry showcase + %d capability docs",
                     len(case_studies), len(industry_showcase), len(capability_docs))
        for m in case_studies:
            logger.info("  [CS] %.3f — %s (%s)", m.similarity_score, m.filename, m.company_name)
        for m in industry_showcase:
            logger.info("  [IS] %.3f — %s (%s) [%s]", m.similarity_score, m.filename, m.company_name, m.industry)
        for m in capability_docs:
            logger.info("  [CD] %s (%s)", m.filename, m.company_name)

        return case_studies, industry_showcase, capability_docs

    except Exception as e:
        logger.error("Case study search failed: %s", e)
        return [], [], []


def _normalize_tags(text: str) -> set[str]:
    """Split comma-separated tags, normalize to lowercase stripped strings."""
    return {t.strip().lower() for t in text.split(",") if t.strip()}


def search_client_references(
    attendee_insights: list[AttendeeInsight],
    meeting: Meeting | None = None,
    max_results: int = 15,
) -> list[ClientReference]:
    """Find client references in the same industry as meeting attendees.

    Matches by industry tag overlap — no vectors needed.
    Extracts industry signals from ZoomInfo, web research, and meeting agenda.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return []

    # Known industry keywords to scan for in free text
    _INDUSTRY_KEYWORDS = {
        "healthcare", "non profit", "npo", "manufacturing",
        "financial services", "financial service", "loan", "lending", "banking",
        "education", "government", "retail", "logistics", "field services",
        "facility services", "mining", "telecom", "media & entertainment",
        "hitech", "iot", "security", "consulting", "insurance", "real estate",
        "staffing services", "recruitment", "human resource", "law & legal",
        "food",
    }

    # Collect prospect industry tags
    prospect_tags: set[str] = set()
    for insight in attendee_insights:
        if insight.zoominfo and insight.zoominfo.company and insight.zoominfo.company.industry:
            prospect_tags |= _normalize_tags(insight.zoominfo.company.industry)
        # Scan web research summaries for industry keywords
        for bullet in insight.web_research_summary:
            bullet_lower = bullet.lower()
            for kw in _INDUSTRY_KEYWORDS:
                if kw in bullet_lower:
                    prospect_tags.add(kw)

    # Scan meeting agenda for industry keywords
    if meeting and meeting.agenda:
        agenda_lower = meeting.agenda.lower()
        for kw in _INDUSTRY_KEYWORDS:
            if kw in agenda_lower:
                prospect_tags.add(kw)

    if not prospect_tags:
        logger.info("Client references: no prospect industry tags found, skipping")
        return []

    logger.info("Client references: matching against tags: %s", prospect_tags)

    try:
        supabase = _get_supabase()
        response = (
            supabase.table("client_references")
            .select("client_name, industry, geography, website_url, logo_url")
            .execute()
        )

        if not response.data:
            logger.info("Client references: no records in table")
            return []

        # Score by tag overlap
        scored = []
        for row in response.data:
            client_tags = _normalize_tags(row.get("industry", ""))
            overlap = prospect_tags & client_tags
            if overlap:
                scored.append((len(overlap), row))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for _, row in scored[:max_results]:
            results.append(ClientReference(
                client_name=row["client_name"],
                industry=row.get("industry", ""),
                geography=row.get("geography", ""),
                website_url=row.get("website_url", ""),
                logo_url=row.get("logo_url", ""),
            ))

        logger.info("Client references: found %d matches", len(results))
        return results

    except Exception as e:
        logger.error("Client reference search failed: %s", e)
        return []
