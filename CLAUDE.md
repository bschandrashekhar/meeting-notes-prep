# Meeting Preparation Pipeline

## Overview
Reads tomorrow's Google Calendar meetings, enriches each with case study / client / brand matches from the `client_referencing` package, then emails a formatted HTML brief per meeting.

## Running
- **CLI (cron):** `python -m src` or `python -m src --date 2026-05-20`
- **Web UI:** `streamlit run app.py`
- **First-time Google OAuth:** `python setup_google.py`

## Environment Variables
All in `.env` — API keys for Anthropic, Voyage AI, Supabase, Serper, Apollo, plus:
- `CALENDAR_NAME` — Google Calendar display name
- `TARGET_EMAIL` — where to send meeting briefs

## Key Dependency
`client_referencing` package from `git+https://github.com/bschandrashekhar/smo-cold-message.git` provides:
- `find_casestudy_matches(prospect_context, prospect_industry, prospect_technologies, max_matches)`
- `find_matches(prospect_industry, prospect_technologies, prospect_country, max_matches)` (min 6)
- `find_brand_match(prospect_industry)`

## Pipeline Stages
1. **Stage 1:** Read Google Calendar → parse structured description → enrich (tech extraction via Claude, case study/client/brand matching)
2. **Stage 2:** Render HTML email via Jinja2 → send via Gmail API

## Conventions
- Python 3.10+, Pydantic v2 models
- `src/config.py` must be imported before `client_referencing` (loads .env)
- Country normalization: Middle East/Africa → EMEA, US variants → USA, UK variants → UK, default → USA
- Cron skips Friday and Saturday (IST)
