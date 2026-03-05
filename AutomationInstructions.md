Stage 1 — From Google Calendar pull the upcoming meeting for tomorrow's date (tdate) in IST along with attendee lists. Run this as a cron job every day at 7:00 PM for (tdate). Use the calendar called "mindruby-cloudchillies-meetings".

Calendar event description format:
```
Agenda: <meeting agenda text>

Attendees:
1. Name - Title
2. Name - Title
```

Client attendee names are in the description field, listed in bullets/numbers with name and designation after a hyphen, each on a new line. The "Agenda:" line (if present) captures the meeting topic for use in Stage 3b.

If there is no attendee name in the description, then use the distribution list of the event to see who all it is being sent to. Then figure out their designation from their email address if possible. Omit any email on mindruby.com and cloudchillies.com domain.

Stage 2 — ZoomInfo API enriches each attendee and company with:
	- Contact profiles (title, phone, LinkedIn, employment history, education)
	- Company data (revenue, employee count, industry, funding)
	- Technographics (full tech stack by category)
	- Intent signals (buying topics with scores)
	- News/scoops

Stage 3 — Once all the ZoomInfo data as context is received, use Claude Sonnet 4.6 with web search to fill gaps and find the latest news, job postings, producing the final prep brief. The AI research prompt is included in the email for transparency.

Stage 3b — Case Study RAG (Retrieval Augmented Generation):
After attendee research is complete, search the internal case study library for relevant case studies to recommend for the meeting.

Architecture:
- 133 PDF case studies stored in `all_casestudies_for_rag/` folder
- Each PDF is ingested into Supabase pgvector: text extracted with pdfplumber, summarized by Claude, embedded with Voyage AI `voyage-3-large` (1024 dims)
- At runtime, a search query is built from the meeting agenda (primary signal) + attendee company/industry (secondary signals)
- The query is embedded and matched against case study vectors via cosine similarity (top 10 candidates)
- Voyage AI `rerank-2` cross-encoder reranks the candidates for precision, returning the top 5
- Claude synthesis generates a relevance note explaining why each case study is relevant to this specific meeting
- Results appear in the email as a "Recommended Case Studies" section

Ingestion (run when PDFs are added/updated/deleted):
```
python -m scripts.ingest_case_studies            # Full sync
python -m scripts.ingest_case_studies --dry-run   # Preview changes
python -m scripts.ingest_case_studies --file "Acme_CRM_MP.pdf"  # Single file
```

Dependencies: Voyage AI (embeddings + reranking, free tier: 200M tokens), Supabase (pgvector storage), pdfplumber (PDF text extraction).

This stage is optional — gated on SUPABASE_URL being set. Pipeline continues without case studies if the search fails.

Stage 4 — Synthesize meeting brief and email to sateesh@mindruby.com.

One email to be prepared for each meeting. The subject of the email includes the subject of the calendar event. The email contains:
- Meeting details (time, location, join link)
- Per-attendee cards: ZoomInfo data, research summary, talking points
- Key themes and suggested questions for the meeting
- Recommended case studies (from Stage 3b, if available)
- The AI research prompt used (collapsible, for transparency) 