"""Case Study Finder — manual form-based Streamlit app.

Users fill in prospect details and get case study matches, existing client
matches, and brand recommendations without requiring Google Calendar access.
"""

# CRITICAL: src.config must be imported first — it loads .env and sets API keys
# before any client_referencing imports happen.
import src.config  # noqa: F401

import streamlit as st

from src.config import normalize_country
from src.enrichment import (
    extract_technologies,
    generate_case_study_narrative,
    _fetch_client_logos,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Case Study Finder",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------

if "enrichment_result" not in st.session_state:
    st.session_state.enrichment_result = None
if "form_submitted" not in st.session_state:
    st.session_state.form_submitted = False

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("Case Study Finder")
st.caption("Fill in the prospect details below and click **Find** to surface relevant case studies, existing clients, and brand recommendations.")

# ---------------------------------------------------------------------------
# Stage 1 — Input form
# ---------------------------------------------------------------------------

with st.form("prospect_form"):
    st.subheader("Prospect Details")

    col1, col2 = st.columns(2)

    with col1:
        agenda = st.text_area(
            "AGENDA (Optional)",
            placeholder="Meeting topic, goals, discussion points…",
            height=120,
        )
        company_information = st.text_area(
            "COMPANY INFORMATION (Optional)",
            placeholder="Requirement overview, company background, pain points…",
            height=120,
        )

    with col2:
        prospect_industry = st.text_input(
            "PROSPECT INDUSTRY *",
            placeholder="e.g. Healthcare, Financial Services, Retail…",
        )
        company_country = st.text_input(
            "COMPANY COUNTRY *",
            placeholder="e.g. United States, United Kingdom, UAE…",
        )

    company_tech_info = st.text_area(
        "COMPANY TECH INFO *",
        placeholder="Tech platforms in use, IT team size, ongoing tech initiatives…",
        height=120,
    )

    submitted = st.form_submit_button("Find Case Studies", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Form submission handler
# ---------------------------------------------------------------------------

if submitted:
    # Validate mandatory fields
    errors = []
    if not company_tech_info.strip():
        errors.append("COMPANY TECH INFO is required.")
    if not prospect_industry.strip():
        errors.append("PROSPECT INDUSTRY is required.")
    if not company_country.strip():
        errors.append("COMPANY COUNTRY is required.")

    if errors:
        for err in errors:
            st.error(err)
    else:
        prospect_context = " ".join(
            filter(None, [agenda.strip(), company_information.strip(), company_tech_info.strip()])
        )

        try:
            with st.status("Running enrichment…", expanded=True) as status:

                # Step 0: Extract technologies
                status.write("Extracting technologies via Claude…")
                prospect_technologies = extract_technologies(company_tech_info)
                techs_csv = ", ".join(prospect_technologies)

                # Normalize country
                normalized_country = normalize_country(company_country)

                # Step 1: Case study matching
                status.write("Finding case study matches…")
                from client_referencing import find_casestudy_matches
                cs_result = find_casestudy_matches(
                    prospect_context=prospect_context,
                    prospect_industry=prospect_industry,
                    prospect_technologies=techs_csv,
                    max_matches=5,
                )
                cs_matches = [m.to_dict() for m in cs_result.get("matches", [])]

                # Step 2: Existing client matching
                status.write("Finding existing client matches…")
                from client_referencing import find_matches
                client_result = find_matches(
                    prospect_industry=prospect_industry,
                    prospect_technologies=techs_csv,
                    prospect_country=normalized_country,
                    max_matches=6,
                )
                client_matches = [m.to_dict() for m in client_result.get("matches", [])]

                # Fetch logo URLs
                client_names = [m["client_name"] for m in client_matches]
                logos = _fetch_client_logos(client_names)
                for m in client_matches:
                    m["logo_url"] = logos.get(m["client_name"], "")

                # Step 3: Brand matching
                status.write("Finding brand match…")
                from client_referencing.brand_matcher import find_brand_match
                brand_result = find_brand_match(prospect_industry=prospect_industry)

                # Step 3b: Case study narrative
                status.write("Generating conversational narratives via Claude…")
                narrative = generate_case_study_narrative(cs_matches, prospect_context)

                status.update(label="Enrichment complete!", state="complete")

            # Persist results across reruns
            st.session_state.enrichment_result = {
                "prospect_context": prospect_context,
                "prospect_industry": prospect_industry.strip(),
                "prospect_technologies": prospect_technologies,
                "prospect_technologies_csv": techs_csv,
                "prospect_country": normalized_country,
                "prospect_country_raw": company_country.strip(),
                "case_study_matches": cs_matches,
                "client_matches": client_matches,
                "brand_result": brand_result,
                "case_study_narrative": narrative,
            }
            st.session_state.form_submitted = True

        except Exception as exc:
            st.error(f"Enrichment failed: {exc}")
            st.session_state.form_submitted = False

# ---------------------------------------------------------------------------
# Results (read from session state — persists across reruns)
# ---------------------------------------------------------------------------

if st.session_state.form_submitted and st.session_state.enrichment_result:
    r = st.session_state.enrichment_result

    st.divider()

    # Country normalisation warning
    raw = r["prospect_country_raw"].lower()
    if r["prospect_country"] == "USA" and raw not in {"usa", "us", "united states", "united states of america", "america"}:
        st.warning(f"'{r['prospect_country_raw']}' was not recognized and defaulted to **USA**.")

    # --- Enrichment summary ---
    with st.expander("Meeting after enrichment", expanded=False):
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f"**PROSPECT_CONTEXT**\n\n{r['prospect_context']}")
            st.markdown(f"**PROSPECT_INDUSTRY:** {r['prospect_industry']}")
            st.markdown(f"**PROSPECT_TECHNOLOGIES:** {r['prospect_technologies_csv'] or '*(none extracted)*'}")
            st.markdown(f"**PROSPECT_COUNTRY:** {r['prospect_country']}")
        with col_b:
            cs_count = len(r["case_study_matches"])
            cl_count = len(r["client_matches"])
            brand = r["brand_result"].get("brand", "N/A") if isinstance(r["brand_result"], dict) else "N/A"
            st.markdown(f"**case_study_matching_result:** {cs_count} match{'es' if cs_count != 1 else ''}")
            st.markdown(f"**existing_client_matching_result:** {cl_count} match{'es' if cl_count != 1 else ''}")
            st.markdown(f"**brand_result:** {brand}")

    # --- Stage 2: Case Studies ---
    with st.expander("Case Studies to Reference", expanded=True):
        cs_matches = r["case_study_matches"]
        narrative = r["case_study_narrative"]

        if not cs_matches:
            st.info("No case studies matched for this prospect.")
        else:
            for i, cs in enumerate(cs_matches):
                name = cs.get("casestudy_name", "Unnamed")
                exact_techs = cs.get("exact_techs", [])
                tech_label = f" [{', '.join(exact_techs)}]" if exact_techs else ""

                st.markdown(f"**{name}{tech_label}**")

                if i < len(narrative) and narrative[i]:
                    st.markdown(f"- {narrative[i]}")
                else:
                    # Fallback to summary_solution
                    fallback = cs.get("summary_solution", "")
                    if fallback:
                        st.markdown(f"- {fallback}")

                if i < len(cs_matches) - 1:
                    st.markdown("---")

    # --- Stage 2: Existing Clients ---
    with st.expander("Existing Clients to Reference", expanded=True):
        client_matches = r["client_matches"]

        if not client_matches:
            st.info("No existing client matches found.")
        else:
            cols_per_row = 3
            for row_start in range(0, len(client_matches), cols_per_row):
                row_clients = client_matches[row_start : row_start + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, client in zip(cols, row_clients):
                    with col:
                        logo_url = client.get("logo_url", "")
                        client_name = client.get("client_name", "")
                        client_url = client.get("client_url", "")

                        if logo_url:
                            st.image(logo_url, width=120)
                        else:
                            st.markdown(
                                f"<div style='width:120px;height:64px;background:#e8e8e8;"
                                f"border-radius:6px;display:flex;align-items:center;"
                                f"justify-content:center;color:#999;font-size:12px;'>No logo</div>",
                                unsafe_allow_html=True,
                            )

                        if client_url:
                            st.markdown(f"[{client_name}]({client_url})")
                        else:
                            st.markdown(client_name)

    # --- Reset ---
    st.divider()
    if st.button("Reset / Start Over"):
        st.session_state.enrichment_result = None
        st.session_state.form_submitted = False
        st.rerun()
