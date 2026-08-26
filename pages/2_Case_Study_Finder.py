"""Case Study Finder — manual form-based Streamlit app.

Users fill in prospect details and get case study matches, existing client
matches, and brand recommendations without requiring Google Calendar access.
"""

# CRITICAL: src.config must be imported first — it loads .env and sets API keys
# before any client_referencing imports happen.
import src.config  # noqa: F401

import streamlit as st

from src.enrichment import _fetch_client_logos

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
        company_country = st.selectbox(
            "COUNTRY *",
            options=["USA", "EMEA", "Australia", "Canada", "UK"],
            index=0,
        )

    prospect_technologies = st.text_area(
        "PROSPECT TECHNOLOGIES * (comma-separated tech names, e.g. Salesforce, MuleSoft)",
        placeholder="Tech platforms in use, IT team size, ongoing tech initiatives…",
        height=120,
    )

    col3, col4 = st.columns(2)
    with col3:
        max_matches_cs = st.slider("MAX MATCHES — Case Studies", min_value=1, max_value=10, value=5)
    with col4:
        max_matches_c = st.slider("MAX MATCHES — Clients", min_value=1, max_value=10, value=6)

    submitted = st.form_submit_button("Find Case Studies", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Form submission handler
# ---------------------------------------------------------------------------

if submitted:
    errors = []
    if not prospect_technologies.strip():
        errors.append("PROSPECT TECHNOLOGIES is required.")
    if not prospect_industry.strip():
        errors.append("PROSPECT INDUSTRY is required.")

    if errors:
        for err in errors:
            st.error(err)
    else:
        prospect_context = " ".join(
            filter(None, [agenda.strip(), company_information.strip()])
        )
        techs_csv = prospect_technologies.strip()

        try:
            with st.status("Running enrichment…", expanded=True) as status:

                # Step 1: Case study matching
                status.write("Finding case study matches…")
                from client_referencing import find_casestudy_matches
                cs_result = find_casestudy_matches(
                    prospect_context=prospect_context,
                    prospect_industry=prospect_industry,
                    prospect_technologies=techs_csv,
                    max_matches=max_matches_cs,
                )
                cs_matches = [m.to_dict() for m in cs_result.get("matches", [])]

                # Step 2: Existing client matching
                status.write("Finding existing client matches…")
                from client_referencing import find_matches
                client_result = find_matches(
                    prospect_industry=prospect_industry,
                    prospect_technologies=techs_csv,
                    prospect_country=company_country,
                    max_matches=max_matches_c,
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

                status.update(label="Enrichment complete!", state="complete")

            st.session_state.enrichment_result = {
                "prospect_context": prospect_context,
                "prospect_industry": prospect_industry.strip(),
                "prospect_technologies": techs_csv,
                "prospect_country": company_country,
                "case_study_matches": cs_matches,
                "client_matches": client_matches,
                "brand_result": brand_result,
                "max_matches_cs": max_matches_cs,
                "max_matches_c": max_matches_c,
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

    # --- Debug: parameters sent to find_casestudy_matches ---
    with st.expander("Debug — Parameters sent to matching functions", expanded=False):
        st.markdown("**find_casestudy_matches**")
        st.json({
            "prospect_context": r["prospect_context"],
            "prospect_industry": r["prospect_industry"],
            "prospect_technologies": r["prospect_technologies"],
            "max_matches": r.get("max_matches_cs"),
        })
        st.markdown("**find_matches**")
        st.json({
            "prospect_industry": r["prospect_industry"],
            "prospect_technologies": r["prospect_technologies"],
            "prospect_country": r["prospect_country"],
            "max_matches": r.get("max_matches_c"),
        })

    # --- Stage 2: Case Studies ---
    with st.expander("Case Studies to Reference", expanded=True):
        cs_matches = r["case_study_matches"]

        if not cs_matches:
            st.info("No case studies matched for this prospect.")
        else:
            lines = []
            for cs in cs_matches:
                name = cs.get("casestudy_name", "Unnamed")
                exact_techs = cs.get("exact_techs", [])
                tech_label = f" [{', '.join(exact_techs)}]" if exact_techs else ""
                url = cs.get("url", "")
                download = f"  [Download ↓]({url})" if url else ""
                lines.append(f"- **{name}{tech_label}**{download}")
            st.markdown("\n".join(lines))

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
                            st.image(logo_url, width=64)
                        else:
                            st.markdown(
                                "<div style='width:64px;height:40px;background:#e8e8e8;"
                                "border-radius:4px;display:flex;align-items:center;"
                                "justify-content:center;color:#999;font-size:10px;'>No logo</div>",
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
