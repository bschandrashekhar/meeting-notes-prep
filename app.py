"""Streamlit app for searching case studies via Voyage AI + Supabase pgvector."""

import os
import smtplib
from email.mime.text import MIMEText

import streamlit as st
import voyageai
from dotenv import load_dotenv
from supabase import create_client

# Support both .env (local) and st.secrets (Streamlit Cloud)
load_dotenv()


def _get_secret(key: str) -> str:
    """Get secret from Streamlit Cloud secrets or environment variables."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, "")


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_SERVICE_KEY = _get_secret("SUPABASE_SERVICE_KEY")
VOYAGE_API_KEY = _get_secret("VOYAGE_API_KEY")
ADMIN_USERNAME = _get_secret("ADMIN_USERNAME") or "admin"
ADMIN_PASSWORD = _get_secret("ADMIN_PASSWORD")
RECOVERY_EMAIL = _get_secret("RECOVERY_EMAIL")
SMTP_HOST = _get_secret("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(_get_secret("SMTP_PORT") or "587")
SMTP_USERNAME = _get_secret("SMTP_USERNAME")
SMTP_PASSWORD = _get_secret("SMTP_PASSWORD")

STORAGE_BUCKET = "case-studies"

st.set_page_config(
    page_title="Case Study Search | Cloud Chillies",
    page_icon="https://cloudchillies.com/favicon.ico",
    layout="wide",
)

# --- Custom CSS for modern sleek look ---
st.markdown("""
<style>
/* ---- Google Font ---- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ---- Root variables ---- */
:root {
    --navy: #0f1b2d;
    --navy-light: #1a2d47;
    --teal: #00bfa6;
    --teal-dark: #009e8c;
    --teal-glow: rgba(0, 191, 166, 0.15);
    --surface: #f8f9fc;
    --card-bg: #ffffff;
    --text-primary: #1a1a2e;
    --text-secondary: #64748b;
    --border: #e2e8f0;
    --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
    --shadow-lg: 0 10px 25px rgba(0,0,0,0.1);
    --radius: 12px;
}

/* ---- Global ---- */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

.stApp {
    background: var(--surface) !important;
    color: var(--text-primary) !important;
}

/* Force dark text on main Streamlit widgets only */
.stApp .stMainBlockContainer .stMarkdown p,
.stApp .stMainBlockContainer .stMarkdown span,
.stApp .stMainBlockContainer .stMarkdown strong,
.stApp .stMainBlockContainer .stMarkdown h1,
.stApp .stMainBlockContainer .stMarkdown h2,
.stApp .stMainBlockContainer .stMarkdown h3,
.stApp .stMainBlockContainer .stMarkdown h4 {
    color: var(--text-primary) !important;
}
.stApp .stMainBlockContainer .stCaption,
.stApp .stMainBlockContainer .stCaption * {
    color: var(--text-secondary) !important;
}
/* Override: hero-banner must keep its own colors */
.stApp .stMainBlockContainer .hero-banner h1,
.stApp .stMainBlockContainer .hero-banner p,
.stApp .stMainBlockContainer .hero-banner span,
.stApp .stMainBlockContainer .hero-banner div {
    color: #ffffff !important;
}
.stApp .stMainBlockContainer .hero-banner p {
    color: #94a3b8 !important;
}
.stApp .stMainBlockContainer .hero-banner .accent {
    color: var(--teal) !important;
}
/* Override: results-count badge */
.stApp .stMainBlockContainer .results-count {
    color: white !important;
}
/* Override: powered-by footer */
.stApp .stMainBlockContainer .powered-by {
    color: var(--text-secondary) !important;
}

/* ---- Hide default Streamlit branding ---- */
#MainMenu, footer, header {visibility: hidden;}

/* ---- Sidebar ---- */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--navy) 0%, var(--navy-light) 100%) !important;
}
section[data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
}
section[data-testid="stSidebar"] .stButton > button {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    color: #e2e8f0 !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(255,255,255,0.15) !important;
    border-color: var(--teal) !important;
}

/* ---- Buttons (unified sizing) ---- */
.stButton > button,
.stFormSubmitButton > button {
    background: linear-gradient(135deg, var(--teal), var(--teal-dark)) !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 0.5rem 1.25rem !important;
    transition: all 0.25s ease !important;
    box-shadow: 0 2px 8px rgba(0, 191, 166, 0.3) !important;
    min-height: 2.5rem !important;
    height: 2.5rem !important;
}
.stButton > button:hover,
.stFormSubmitButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 16px rgba(0, 191, 166, 0.4) !important;
}

/* ---- "Forgot Password?" / "Back to Sign In" link-style button ---- */
.forgot-btn .stButton > button {
    background: transparent !important;
    color: var(--teal) !important;
    box-shadow: none !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    padding: 0.25rem 0 !important;
    min-height: unset !important;
    height: auto !important;
    text-decoration: underline !important;
}
.forgot-btn .stButton > button:hover {
    background: transparent !important;
    color: var(--teal-dark) !important;
    transform: none !important;
    box-shadow: none !important;
}

/* ---- Text inputs ---- */
.stTextInput > div > div > input,
.stTextInput input {
    border-radius: 8px !important;
    border: 1.5px solid var(--border) !important;
    padding: 0.65rem 1rem !important;
    font-size: 0.95rem !important;
    transition: border-color 0.2s ease !important;
    background: #ffffff !important;
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
}
.stTextInput > div > div > input::placeholder,
.stTextInput input::placeholder {
    color: #94a3b8 !important;
    -webkit-text-fill-color: #94a3b8 !important;
    opacity: 1 !important;
}
.stTextInput > div > div > input:focus,
.stTextInput input:focus {
    border-color: var(--teal) !important;
    box-shadow: 0 0 0 3px var(--teal-glow) !important;
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
}
/* Labels */
.stTextInput label, .stSelectbox label {
    color: var(--text-primary) !important;
}

/* ---- Select box ---- */
.stSelectbox > div > div {
    border-radius: 8px !important;
    background: #ffffff !important;
    color: #1a1a2e !important;
}
.stSelectbox > div > div > div,
.stSelectbox [data-baseweb="select"] > div {
    background: #ffffff !important;
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
}
.stSelectbox [data-baseweb="select"] span {
    color: #1a1a2e !important;
    -webkit-text-fill-color: #1a1a2e !important;
}
/* Dropdown menu items */
[data-baseweb="menu"] {
    background: #ffffff !important;
}
[data-baseweb="menu"] li {
    color: #1a1a2e !important;
    background: #ffffff !important;
}
[data-baseweb="menu"] li:hover {
    background: var(--teal-glow) !important;
}

/* ---- Metric ---- */
[data-testid="stMetricValue"] {
    color: var(--teal) !important;
    font-weight: 700 !important;
}

/* ---- Alerts ---- */
.stAlert > div {
    border-radius: var(--radius) !important;
    border: none !important;
}

/* ---- Hero banner (injected via markdown) ---- */
.hero-banner {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-light) 60%, #1e3a5f 100%);
    border-radius: 16px;
    padding: 2.5rem 2rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.hero-banner::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -20%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, var(--teal-glow) 0%, transparent 70%);
    border-radius: 50%;
}
.hero-banner, .hero-banner * {
    color: #ffffff !important;
}
.hero-banner h1 {
    color: #ffffff !important;
    font-size: 2rem;
    font-weight: 700;
    margin: 0 0 0.5rem 0;
    position: relative;
}
.hero-banner p {
    color: #94a3b8 !important;
    font-size: 1.05rem;
    margin: 0;
    position: relative;
}
.hero-banner .accent {
    color: var(--teal) !important;
    font-weight: 600;
}

/* ---- Result containers ---- */
div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
    border-radius: var(--radius) !important;
    border-color: var(--border) !important;
    box-shadow: var(--shadow) !important;
    transition: all 0.25s ease !important;
    background: var(--card-bg) !important;
}
div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"]:hover {
    box-shadow: var(--shadow-md) !important;
    border-color: var(--teal) !important;
}

/* ---- Link button (Download PDF) ---- */
.stLinkButton > a {
    background: linear-gradient(135deg, var(--teal), var(--teal-dark)) !important;
    color: white !important;
    border: none !important;
    border-radius: 6px !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    padding: 0.4rem 1rem !important;
    min-height: unset !important;
    height: auto !important;
    box-shadow: 0 2px 6px rgba(0, 191, 166, 0.25) !important;
    transition: all 0.2s ease !important;
}
.stLinkButton > a:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(0, 191, 166, 0.35) !important;
}

/* ---- Login card ---- */
.login-card {
    background: var(--card-bg);
    border-radius: 16px;
    padding: 2.5rem;
    box-shadow: var(--shadow-lg);
    max-width: 420px;
    margin: 3rem auto;
    border: 1px solid var(--border);
}
.login-card h2 {
    text-align: center;
    color: var(--navy);
    font-weight: 700;
    margin-bottom: 0.25rem;
}
.login-card .subtitle {
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
}

/* ---- Stats row ---- */
.stats-row {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
}
.stat-card {
    flex: 1;
    background: var(--card-bg);
    border-radius: var(--radius);
    padding: 1.25rem;
    text-align: center;
    box-shadow: var(--shadow);
    border: 1px solid var(--border);
}
.stat-card .stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--teal);
}
.stat-card .stat-label {
    font-size: 0.82rem;
    color: var(--text-secondary);
    margin-top: 0.25rem;
}

/* ---- Results count badge ---- */
.results-count {
    display: inline-block;
    background: var(--navy);
    color: white !important;
    padding: 0.4rem 1rem;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 500;
    margin-bottom: 1rem;
}

/* ---- Stat cards text ---- */
.stat-card .stat-value {
    color: var(--teal) !important;
}
.stat-card .stat-label {
    color: var(--text-secondary) !important;
}

/* ---- Powered by footer ---- */
.powered-by {
    text-align: center;
    color: var(--text-secondary);
    font-size: 0.78rem;
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
}

/* ---- Scrollbar styling ---- */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
""", unsafe_allow_html=True)


# --- Authentication ---

def check_login():
    """Show login form and gate access."""
    if st.session_state.get("authenticated"):
        return True

    # Centered login layout
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div style="text-align:center; margin-top: 2rem; margin-bottom: 1rem;">
            <img src="https://cloudchillies.com/img/logo.svg" alt="Cloud Chillies"
                 style="height: 40px; margin-bottom: 1.25rem;" />
            <h1 style="color: #0f1b2d; font-size: 1.8rem; font-weight: 700; margin-bottom: 0.25rem;">
                Case Study Search
            </h1>
            <p style="color: #64748b; font-size: 0.95rem;">
                AI-powered semantic search across your case study library
            </p>
        </div>
        """, unsafe_allow_html=True)

        if st.session_state.get("show_forgot_password"):
            _forgot_password_form()
        else:
            _login_form()

        st.markdown("""
        <div class="powered-by">
            Powered by Voyage AI & Supabase
        </div>
        """, unsafe_allow_html=True)

    return False


def _login_form():
    with st.form("login_form"):
        st.text_input("Username", key="login_username")
        st.text_input("Password", type="password", key="login_password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if (st.session_state.login_username == ADMIN_USERNAME
                    and st.session_state.login_password == ADMIN_PASSWORD):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with st.container():
        st.markdown('<div class="forgot-btn">', unsafe_allow_html=True)
        if st.button("Forgot Password?"):
            st.session_state["show_forgot_password"] = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


def _forgot_password_form():
    st.markdown("##### Password Recovery")

    with st.form("forgot_password_form"):
        email = st.text_input("Enter your recovery email address")
        submitted = st.form_submit_button("Send Password", use_container_width=True)

        if submitted:
            if email == RECOVERY_EMAIL:
                if _send_recovery_email():
                    st.success(f"Password sent to {_mask_email(email)}. Check your inbox.")
                else:
                    st.error("Could not send email. Please contact the administrator.")
            else:
                st.error("Email address does not match the recovery email on file.")

    with st.container():
        st.markdown('<div class="forgot-btn">', unsafe_allow_html=True)
        if st.button("Back to Sign In"):
            st.session_state["show_forgot_password"] = False
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


def _mask_email(email: str) -> str:
    """Mask email for display: b***@yahoo.com"""
    local, domain = email.split("@")
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def _send_recovery_email() -> bool:
    """Send the admin password to the recovery email via SMTP."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False

    msg = MIMEText(
        f"Your Case Study Search login credentials:\n\n"
        f"Username: {ADMIN_USERNAME}\n"
        f"Password: {ADMIN_PASSWORD}\n\n"
        f"— Case Study Search App",
        "plain",
    )
    msg["Subject"] = "Case Study Search — Password Recovery"
    msg["From"] = SMTP_USERNAME
    msg["To"] = RECOVERY_EMAIL

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        return False


# --- Gate access ---
if not check_login():
    st.stop()


# --- Authenticated content below ---

# Sidebar
with st.sidebar:
    st.markdown(f"""
    <div style="padding: 1rem 0; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 1rem;">
        <img src="https://cloudchillies.com/img/logo.svg" alt="Cloud Chillies"
             style="height: 28px; filter: brightness(0) invert(1); opacity: 0.85; margin-bottom: 1rem;" />
        <div style="font-size: 0.82rem; color: #94a3b8; margin-bottom: 0.25rem;">Signed in as</div>
        <div style="font-weight: 600; font-size: 1rem;">{ADMIN_USERNAME}</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Sign Out", use_container_width=True):
        st.session_state["authenticated"] = False
        st.rerun()


@st.cache_resource
def get_clients():
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
    return supabase, voyage


def search(query: str, top_k: int = 5) -> list[dict]:
    supabase, voyage = get_clients()

    # Embed query
    embed_result = voyage.embed(
        [query[:8000]],
        model="voyage-3-large",
        input_type="query",
    )
    query_embedding = embed_result.embeddings[0]

    # Vector search — fetch 2x for reranking
    response = supabase.rpc(
        "match_case_studies",
        {
            "query_embedding": query_embedding,
            "match_count": top_k * 2,
            "match_threshold": 0.3,
        },
    ).execute()

    if not response.data:
        return []

    # Rerank with cross-encoder
    rerank_docs = [
        f"{row.get('company_name', '')} — {row.get('use_case', '')}: {row.get('summary', '')}"
        for row in response.data
    ]
    rerank_result = voyage.rerank(
        query=query[:8000],
        documents=rerank_docs,
        model="rerank-2",
        top_k=top_k,
    )

    # Build results ordered by rerank score
    results = []
    for item in rerank_result.results:
        row = response.data[item.index]
        results.append({
            "company_name": row.get("company_name", ""),
            "use_case": row.get("use_case", ""),
            "doc_type": row.get("doc_type", ""),
            "summary": row.get("summary", ""),
            "filename": row.get("filename", ""),
            "relevance_score": round(item.relevance_score * 100, 1),
        })

    return results


# --- Check config ---
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not VOYAGE_API_KEY:
    st.error("Missing environment variables. Set SUPABASE_URL, SUPABASE_SERVICE_KEY, and VOYAGE_API_KEY.")
    st.stop()

# Get total count for hero banner
total_count = 133
try:
    supabase, _ = get_clients()
    count_resp = supabase.table("case_studies").select("id", count="exact").execute()
    total_count = count_resp.count if count_resp.count else len(count_resp.data)
except Exception:
    pass

# Hero banner
st.markdown(f"""
<div class="hero-banner">
    <div style="display: flex; align-items: center; gap: 1rem; margin-bottom: 0.75rem; position: relative;">
        <img src="https://cloudchillies.com/img/logo.svg" alt="Cloud Chillies"
             style="height: 32px; filter: brightness(0) invert(1); opacity: 0.9;" />
    </div>
    <h1>Case Study Search</h1>
    <p>Search across <span class="accent">{total_count} case studies</span> using AI-powered
    semantic search with cross-encoder reranking</p>
</div>
""", unsafe_allow_html=True)

# Search input — all on one line
search_col1, search_col2, search_col3 = st.columns([5, 1, 1])
with search_col1:
    query = st.text_input(
        "Search",
        placeholder="e.g., inventory management, mobile app development, healthcare platform",
        label_visibility="collapsed",
    )
with search_col2:
    top_k = st.selectbox("Results", [3, 5, 10], index=1, label_visibility="collapsed")
with search_col3:
    search_clicked = st.button("Search", use_container_width=True)

# Search
if query:
    with st.spinner("Searching and reranking..."):
        results = search(query, top_k=top_k)

    if not results:
        st.warning("No matching case studies found. Try a broader query.")
    else:
        st.markdown(
            f'<div class="results-count">{len(results)} results for "{query}"</div>',
            unsafe_allow_html=True,
        )

        for i, r in enumerate(results, 1):
            title = r["company_name"]
            if r["use_case"]:
                title += f" — {r['use_case']}"

            meta_parts = []
            if r["doc_type"]:
                meta_parts.append(r["doc_type"])
            meta_parts.append(r["filename"])
            meta_text = " · ".join(meta_parts)

            with st.container(border=True):
                col_title, col_score = st.columns([5, 1])
                with col_title:
                    st.markdown(f"**{i}. {title}**")
                with col_score:
                    st.markdown(
                        f'<span style="background:rgba(0,191,166,0.15); color:#009e8c; '
                        f'font-weight:700; font-size:0.85rem; padding:0.3rem 0.75rem; '
                        f'border-radius:20px; white-space:nowrap;">{r["relevance_score"]}%</span>',
                        unsafe_allow_html=True,
                    )

                st.caption(meta_text)
                st.write(r["summary"])

                try:
                    supabase, _ = get_clients()
                    signed = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
                        r["filename"], 3600
                    )
                    if signed and signed.get("signedURL"):
                        st.link_button("Download PDF", signed["signedURL"])
                except Exception:
                    pass

else:
    # Welcome state — stats cards
    st.markdown(f"""
    <div class="stats-row">
        <div class="stat-card">
            <div class="stat-value">{total_count}</div>
            <div class="stat-label">Case Studies</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">AI</div>
            <div class="stat-label">Semantic Search</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">2-Stage</div>
            <div class="stat-label">Vector + Reranking</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.info("Enter a query above to search across your case study library.")

# Footer
st.markdown("""
<div class="powered-by">
    Powered by Voyage AI embeddings, Supabase pgvector & cross-encoder reranking
</div>
""", unsafe_allow_html=True)
