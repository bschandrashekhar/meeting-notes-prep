# Meeting Prep Automation

Automated daily meeting prep pipeline that researches attendees and recommends relevant case studies, delivered via email.

## Project Structure

```
src/
  config.py          — Environment variables and paths
  models.py          — Pydantic v2 data models (Meeting, Attendee, MeetingBrief, CaseStudyMatch, etc.)
  google_calendar.py — Google Calendar API: fetch tomorrow's meetings, parse description (agenda + attendees)
  zoominfo_client.py — ZoomInfo API: contact/company enrichment, tech stack, intent signals, news
  research.py        — Claude Sonnet 4.6 with web search: attendee research + meeting brief synthesis
  case_study_search.py — Voyage AI embedding + Supabase pgvector search + rerank-2 reranking
  email_sender.py    — Gmail API: render Jinja2 template and send HTML email
  main.py            — Pipeline orchestrator (Stages 1 → 2 → 3 → 3b → 4)
scripts/
  ingest_case_studies.py — Sync PDFs to Supabase: extract text, summarize, embed, upsert
templates/
  email_brief.html   — Jinja2 HTML email template (inline CSS for email clients)
all_casestudies_for_rag/ — PDF case studies (not in git)
app.py                 — Streamlit search UI for case studies
```

## Running

```bash
# Full pipeline (fetches tomorrow's meetings and sends prep emails)
python -m src.main

# With a specific date
python -m src.main --date 2026-03-06

# Case study ingestion (run when PDFs change)
python -m scripts.ingest_case_studies
python -m scripts.ingest_case_studies --dry-run
python -m scripts.ingest_case_studies --file "Acme_CRM_MP.pdf"

# Case study search UI
streamlit run app.py

# Google OAuth setup (one-time, generates token.json)
python setup_google.py
```

## Environment Variables (.env)

Required:
- `ANTHROPIC_API_KEY` — Claude API key
- `TARGET_EMAIL` — Recipient email address

Optional (enable features when set):
- `ZOOMINFO_USERNAME`, `ZOOMINFO_PASSWORD` — ZoomInfo enrichment (Stage 2)
- `VOYAGE_API_KEY` — Voyage AI embeddings + reranking (Stage 3b)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — Supabase pgvector store (Stage 3b)
- `PERPLEXITY_API_KEY` — Not currently used (was previous research provider)

Google OAuth files (not env vars): `credentials.json`, `token.json`

## Tech Stack

- Python 3.11+, Pydantic v2
- Anthropic SDK — Claude Sonnet 4.6 (`claude-sonnet-4-6`) with `web_search_20250305` tool
- Voyage AI — `voyage-3-large` embeddings (1024 dims) + `rerank-2` cross-encoder
- Supabase — pgvector for case study vector storage, RPC function `match_case_studies`
- Google APIs — Calendar (readonly) + Gmail (send) via OAuth2
- Jinja2 — HTML email templating
- pdfplumber — PDF text extraction for ingestion
- Streamlit — Case study search UI

## Pipeline Stages

1. **Calendar** — Fetch tomorrow's meetings, parse agenda + attendees from description
2. **ZoomInfo** — Enrich attendees with contact/company data (skipped if credentials not set)
3. **Research** — Claude web search for each attendee (latest news, background)
3b. **Case Studies** — Vector search + rerank for relevant case studies (skipped if Supabase not configured)
4. **Synthesis + Email** — Claude synthesizes brief, render template, send via Gmail

## Conventions

- All stages gracefully degrade: missing API keys = stage skipped, errors = logged and continue
- Models in `src/models.py` use Pydantic v2 `BaseModel` with `model_config = ConfigDict(arbitrary_types_allowed=True)`
- Calendar description format: `Agenda: ...` line + `Attendees:` header + numbered/bulleted names. Legacy format (no headers) supported.
- Case study filenames follow `CompanyName_UseCase_Type.pdf` pattern
- GitHub Actions runs daily at `30 1 * * *` UTC (7:00 AM IST)

## Deployment

GitHub Actions workflow: `.github/workflows/meeting_prep.yml`
Secrets needed: `ANTHROPIC_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`, `VOYAGE_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
