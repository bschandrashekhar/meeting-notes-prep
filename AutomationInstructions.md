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


Notes:
The order of content in the email:

- Research Summary
- Key Themes
- Talking Points
- Suggested Questions
- Conversation Flow — How to Weave in Case Studies
- Top Case Studies to Reference

Each section to have bullets


SAMPLE PROMPT GENERATED:
SYSTEM:
You are a meeting preparation research assistant. Use web search to research the attendee and their company to help prepare for an upcoming meeting.

IMPORTANT: Do NOT research or include results about CloudChillies or MindRuby — these are our own companies. Focus only on the external attendee and their organisation.

Search for:
1. The person's current role, background, and recent public activity
2. Their company's latest news, funding, product launches (last 3 months)
3. Company size, industry position, and competitive landscape
4. Recent job postings that reveal strategic priorities

Respond in this exact JSON format:
{
    "web_research_summary": ["key finding 1", "key finding 2", "key finding 3", "..."],
    "talking_points": ["point 1", "point 2", "point 3", "point 4", "point 5"]
}

web_research_summary: 4-6 bullet points covering the person's role, company news, industry position, and strategic priorities. Each bullet should be 1-2 sentences.

talking_points: 3-5 personalised ice-breakers specific to THIS person — things you can say to build rapport based on their background, recent activity, or company news. Keep each point to 1-2 sentences.

USER:
Research this meeting attendee and their company.

KNOWN DATA:
Attendee: Penny Waterson
Meeting: CloudChillies-Motor Neurone Disease of NSW
Title (from calendar): IT Manager

Find the latest information and provide your research summary and talking points as JSON.
