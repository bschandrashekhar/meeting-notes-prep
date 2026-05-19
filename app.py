"""Streamlit web UI for the Meeting Preparation Pipeline."""

from __future__ import annotations

import streamlit as st
from datetime import datetime, timedelta

# Load config FIRST (ensures .env is loaded before client_referencing)
from src.config import IST, TARGET_EMAIL
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
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")
    tomorrow = datetime.now(IST).date() + timedelta(days=1)
    tdate = st.date_input("Select Date to read Meetings", value=tomorrow)
    to_email = st.text_input("Send briefs to", value=TARGET_EMAIL)
    run_btn = st.button("🚀 Run Pipeline", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if run_btn:
    status = st.status("Running pipeline …", expanded=True)

    # ── Stage 1A: Fetch meetings ─────────────────────────────────────────
    status.write(f"Fetching meetings for **{tdate}** …")
    meetings = get_meetings_for_date(tdate)
    status.write(f"Found **{len(meetings)}** meeting(s)")

    if not meetings:
        status.update(label="No meetings found", state="complete")
        st.info(f"No meetings found on the calendar for {tdate}.")
        st.stop()

    enriched_list = []

    for idx, meeting in enumerate(meetings):
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
                if meeting.attendees:
                    st.markdown("**Attendees:**")
                    for att in meeting.attendees:
                        parts = [f"**{att.name}**"]
                        if att.title:
                            parts.append(f" — {att.title}")
                        if att.linkedin_url:
                            parts.append(f" ([LinkedIn]({att.linkedin_url}))")
                        st.markdown("".join(parts))

        # ── Enrich ───────────────────────────────────────────────────────
        status.write(f"Enriching: **{meeting.subject}** …")
        with st.spinner(f"Enriching {meeting.subject} …"):
            enriched = enrich_meeting(meeting)
        enriched_list.append(enriched)

        # ── After enrichment ─────────────────────────────────────────────
        with st.expander(f"✅ {meeting_label} — After Enrichment", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Extracted Technologies:**")
                if enriched.prospect_technologies:
                    st.write(", ".join(enriched.prospect_technologies))
                else:
                    st.write("None extracted")

                st.markdown(f"**Normalized Country:** {enriched.normalized_country}")
                st.markdown(f"**Brand:** {enriched.brand_result.get('brand', 'N/A')}")

            with col2:
                st.markdown(f"**Case Study Matches:** {len(enriched.case_study_matches)}")
                for cs in enriched.case_study_matches:
                    st.markdown(f"- {cs.get('casestudy_name', 'N/A')}")

                st.markdown(f"**Client Matches:** {len(enriched.client_matches)}")
                for cl in enriched.client_matches:
                    st.markdown(f"- {cl.get('client_name', 'N/A')}")

            if enriched.case_study_narrative:
                st.markdown("**Conversational Flow:**")
                for bullet in enriched.case_study_narrative:
                    st.markdown(f"- {bullet}")

        # ── Final email preview ──────────────────────────────────────────
        with st.expander(f"📧 {meeting_label} — Final eMail", expanded=False):
            html = render_meeting_email(enriched)
            st.components.v1.html(html, height=800, scrolling=True)

    # ── Stage 2: Send emails ─────────────────────────────────────────────
    st.divider()
    st.subheader("Send Emails")

    if st.button("📤 Send All Emails", type="secondary"):
        sent = 0
        for enriched in enriched_list:
            if send_meeting_email(enriched, to_email=to_email):
                sent += 1
                st.success(f"Sent: {enriched.input.subject}")
            else:
                st.error(f"Failed: {enriched.input.subject}")
        st.info(f"Sent {sent}/{len(enriched_list)} email(s) to {to_email}")

    status.update(label=f"Pipeline complete — {len(enriched_list)} meeting(s) processed", state="complete")
