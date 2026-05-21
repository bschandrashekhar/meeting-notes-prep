"""Streamlit web UI for the Meeting Preparation Pipeline."""

from __future__ import annotations

import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path

# Load config FIRST (ensures .env is loaded before client_referencing)
from src.config import IST, SIGNALS_TO_LOOK_FOR, TARGET_EMAIL
from src.google_calendar import get_meetings_for_date
from src.enrichment import enrich_meeting
from src.email_composer import render_meeting_email, send_meeting_email

st.set_page_config(
    page_title="Meeting Preparation Pipeline",
    page_icon="📋",
    layout="wide",
)

st.title("Meeting Preparation Pipeline")

# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------
if "enriched_list" not in st.session_state:
    st.session_state.enriched_list = []
if "meetings_raw" not in st.session_state:
    st.session_state.meetings_raw = []
if "pipeline_done" not in st.session_state:
    st.session_state.pipeline_done = False

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    logo_path = Path(__file__).parent / "assets" / "logo.svg"
    if logo_path.exists():
        st.image(str(logo_path), width=200)
    tomorrow = datetime.now(IST).date() + timedelta(days=1)
    tdate = st.date_input("Select Date to read Meetings", value=tomorrow)
    run_btn = st.button("🚀 Run Pipeline", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Run pipeline (only when button is clicked)
# ---------------------------------------------------------------------------
if run_btn:
    # Clear previous results so old content disappears immediately
    st.session_state.enriched_list = []
    st.session_state.meetings_raw = []
    st.session_state.pipeline_done = False

    status = st.status("Running pipeline …", expanded=True)

    # ── Stage 1A: Fetch meetings ─────────────────────────────────────────
    status.write(f"Fetching meetings for **{tdate}** …")
    meetings = get_meetings_for_date(tdate)
    status.write(f"Found **{len(meetings)}** meeting(s)")

    if not meetings:
        status.update(label="No meetings found", state="complete")
        st.info(f"No meetings found on the calendar for {tdate}.")
        st.stop()

    st.session_state.meetings_raw = meetings
    enriched_list = []

    for idx, meeting in enumerate(meetings):
        status.write(f"Enriching: **{meeting.subject}** …")
        with st.spinner(f"Enriching {meeting.subject} …"):
            enriched = enrich_meeting(meeting)
        enriched_list.append(enriched)

    st.session_state.enriched_list = enriched_list
    st.session_state.pipeline_done = True
    status.update(label=f"Pipeline complete — {len(enriched_list)} meeting(s) processed", state="complete")

# ---------------------------------------------------------------------------
# Display results (persists across re-runs via session_state)
# ---------------------------------------------------------------------------
if st.session_state.pipeline_done:
    meetings = st.session_state.meetings_raw
    enriched_list = st.session_state.enriched_list

    for idx, (meeting, enriched) in enumerate(zip(meetings, enriched_list)):
        meeting_label = f"Meeting {idx + 1}: {meeting.subject}"

        # ── Before enrichment ────────────────────────────────────────────
        with st.expander(f"📝 {meeting_label} — Before Enrichment", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Subject:** " + meeting.subject)
                st.markdown("**Agenda:**")
                st.text(meeting.agenda)
                st.markdown("**Company Information:**")
                st.text(meeting.company_information)
            with col2:
                if meeting.company_tech_info:
                    st.markdown("**Company Tech Background:**")
                    st.text(meeting.company_tech_info)
                st.markdown(f"**Industry:** {meeting.prospect_industry}")
                st.markdown(f"**Country:** {meeting.company_country}")
                st.markdown(f"**SIGNALS_TO_LOOK_FOR:** {', '.join(sorted(SIGNALS_TO_LOOK_FOR))}")
                if meeting.attendees:
                    st.markdown("**Attendees:**")
                    for att in meeting.attendees:
                        parts = [f"**{att.name}**"]
                        if att.title:
                            parts.append(f" — {att.title}")
                        if att.linkedin_url:
                            parts.append(f" ([LinkedIn]({att.linkedin_url}))")
                        st.markdown("".join(parts))

        # ── After enrichment ─────────────────────────────────────────────
        with st.expander(f"✅ {meeting_label} — After Enrichment", expanded=False):
            st.markdown("**Prospect Context:**")
            st.text(enriched.prospect_context)

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.markdown(f"**Industry:** {enriched.input.prospect_industry}")
            with col2:
                st.markdown("**Extracted Technologies:**")
                if enriched.prospect_technologies:
                    st.write(", ".join(enriched.prospect_technologies))
                else:
                    st.write("None extracted")
            with col3:
                st.markdown(f"**Normalized Country:** {enriched.normalized_country}")
            with col4:
                st.markdown(f"**Brand:** {enriched.brand_result.get('brand', 'N/A')}")

            col_left, col_right = st.columns(2)
            with col_left:
                st.markdown(f"**Case Study Matches ({len(enriched.case_study_matches)}):**")
                for cs in enriched.case_study_matches:
                    st.markdown(f"- {cs.get('casestudy_name', 'N/A')}")
            with col_right:
                st.markdown(f"**Client Matches ({len(enriched.client_matches)}):**")
                for cl in enriched.client_matches:
                    st.markdown(f"- {cl.get('client_name', 'N/A')}")

            # Attendee Insights
            if enriched.attendee_insights:
                st.markdown("---")
                st.markdown("**Attendee Insights:**")
                for insight in enriched.attendee_insights:
                    if not insight.linkedin_url and not insight.enrichment_error:
                        continue  # skip attendees with no LinkedIn
                    st.markdown(f"**{insight.attendee_name}**")
                    if insight.profile_summary:
                        st.markdown(insight.profile_summary)
                    if insight.signal_matches:
                        st.success(f"Signals detected: {', '.join(insight.signal_matches)}")
                    if insight.client_matches:
                        st.success(f"Client matches: {', '.join(insight.client_matches)}")
                    if insight.suggested_questions:
                        st.markdown("**Suggested Questions:**")
                        for i, q in enumerate(insight.suggested_questions, 1):
                            st.markdown(f"{i}. {q}")
                    if insight.enrichment_error:
                        st.warning(f"Could not enrich: {insight.enrichment_error}")

        # ── Final email preview ──────────────────────────────────────────
        with st.expander(f"📧 {meeting_label} — Final eMail", expanded=False):
            html = render_meeting_email(enriched)
            st.components.v1.html(html, height=800, scrolling=True)

    # ── Stage 2: Optional email sending ─────────────────────────────────
    st.divider()
    send_emails = st.checkbox("Send emails after preview", value=False)

    if send_emails:
        to_email = st.text_input("Send briefs to", value="bschandrashekhar@yahoo.com")
        if st.button("📤 Send All Emails", type="secondary"):
            sent = 0
            for enriched in enriched_list:
                if send_meeting_email(enriched, to_email=to_email):
                    sent += 1
                    st.success(f"Sent: {enriched.input.subject}")
                else:
                    st.error(f"Failed: {enriched.input.subject}")
            st.info(f"Sent {sent}/{len(enriched_list)} email(s) to {to_email}")
