"""Streamlit app for searching case studies via Voyage AI + Supabase pgvector."""

import hashlib
import hmac
import os
import secrets
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

/* ---- Hide default Streamlit branding & remove top padding ---- */
#MainMenu, footer, [data-testid="stDecoration"] {visibility: hidden; height: 0; margin: 0; padding: 0; display: none !important;}
.stApp > header, header[data-testid="stHeader"] {background: transparent !important; height: 0 !important; min-height: 0 !important; max-height: 0 !important; padding: 0 !important; display: none !important; overflow: hidden !important;}
header [data-testid="stToolbar"] {display: none !important;}
/* Ensure sidebar toggle stays visible */
[data-testid="collapsedControl"] {z-index: 999; top: 0.5rem !important;}
.stMainBlockContainer {padding-top: 1rem !important;}
section[data-testid="stSidebar"] > div:first-child {padding-top: 1rem !important;}

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

/* ---- Secondary form button (Forgot Password / Back to Sign In) ---- */
.stForm [data-testid="stHorizontalBlock"] .stFormSubmitButton:last-child > button {
    background: transparent !important;
    color: var(--teal) !important;
    border: 1.5px solid var(--teal) !important;
    box-shadow: none !important;
    font-weight: 600 !important;
}
.stForm [data-testid="stHorizontalBlock"] .stFormSubmitButton:last-child > button:hover {
    background: var(--teal-glow) !important;
    color: var(--teal-dark) !important;
    border-color: var(--teal-dark) !important;
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
    margin-left: 0;
    margin-right: 0;
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

/* ---- Tabs ---- */
.stTabs [data-baseweb="tab-list"] {
    gap: 0 !important;
    background: var(--card-bg) !important;
    border-radius: 10px !important;
    padding: 4px !important;
    border: 1px solid var(--border) !important;
    box-shadow: var(--shadow) !important;
}
.stTabs [data-baseweb="tab"] {
    flex: 1 !important;
    justify-content: center !important;
    border-radius: 8px !important;
    padding: 0.6rem 1.5rem !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    background: transparent !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
/* Inactive tab text */
.stTabs [data-baseweb="tab"] p,
.stTabs [data-baseweb="tab"] span,
.stTabs [data-baseweb="tab"] {
    color: var(--text-secondary) !important;
}
.stTabs [data-baseweb="tab"]:hover,
.stTabs [data-baseweb="tab"]:hover p,
.stTabs [data-baseweb="tab"]:hover span {
    color: var(--teal-dark) !important;
    background: var(--teal-glow) !important;
}
/* Active tab */
.stTabs [aria-selected="true"],
.stTabs [aria-selected="true"] p,
.stTabs [aria-selected="true"] span {
    background: linear-gradient(135deg, var(--navy) 0%, var(--navy-light) 100%) !important;
    color: #ffffff !important;
    box-shadow: 0 2px 8px rgba(15, 27, 45, 0.25) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* ---- Scrollbar styling ---- */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_clients():
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    voyage = voyageai.Client(api_key=VOYAGE_API_KEY)
    return supabase, voyage


# --- Authentication ---

def _hash_password(password: str) -> str:
    """Hash a password for storage."""
    return hashlib.sha256(f"css-salt:{password}".encode()).hexdigest()


def _get_stored_password_hash() -> str | None:
    """Get password hash from Supabase app_settings."""
    try:
        supabase, _ = get_clients()
        resp = supabase.table("app_settings").select("value").eq("key", "admin_password_hash").execute()
        if resp.data:
            return resp.data[0]["value"]
    except Exception:
        pass
    return None


def _set_stored_password(password: str):
    """Store hashed password in Supabase app_settings."""
    supabase, _ = get_clients()
    new_hash = _hash_password(password)
    # Delete any existing rows first, then insert fresh (avoids duplicate key issues)
    supabase.table("app_settings").delete().eq("key", "admin_password_hash").execute()
    supabase.table("app_settings").insert({
        "key": "admin_password_hash",
        "value": new_hash,
    }).execute()


def _verify_password(password: str) -> bool:
    """Verify password against Supabase store, fall back to env var."""
    stored_hash = _get_stored_password_hash()
    if stored_hash:
        return _hash_password(password) == stored_hash
    return password == ADMIN_PASSWORD


def _make_auth_token() -> str:
    """Create a hash token for session persistence across refreshes."""
    stored_hash = _get_stored_password_hash() or ADMIN_PASSWORD
    raw = f"{ADMIN_USERNAME}:{stored_hash}:css-auth".encode()
    return hmac.new(b"case-study-search", raw, hashlib.sha256).hexdigest()[:16]


def check_login():
    """Show login form and gate access."""
    if st.session_state.get("authenticated"):
        return True

    # Check query params for auth token (survives page refresh)
    token = st.query_params.get("auth")
    if token and token == _make_auth_token():
        st.session_state["authenticated"] = True
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
            Powered by AI
        </div>
        """, unsafe_allow_html=True)

    return False


def _login_form():
    with st.form("login_form"):
        st.text_input("Username", value="admin", key="login_username")
        st.text_input("Password", type="password", key="login_password")

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            submitted = st.form_submit_button("Sign In", use_container_width=True)
        with btn_c2:
            forgot = st.form_submit_button("Forgot Password?", use_container_width=True)

        if submitted:
            if (st.session_state.login_username == ADMIN_USERNAME
                    and _verify_password(st.session_state.login_password)):
                st.session_state["authenticated"] = True
                st.query_params["auth"] = _make_auth_token()
                st.rerun()
            else:
                st.error("Invalid username or password.")
        if forgot:
            st.session_state["show_forgot_password"] = True
            st.rerun()

    # Autofocus the password field
    st.components.v1.html("""
    <script>
    const passInputs = window.parent.document.querySelectorAll('input[type="password"]');
    if (passInputs.length > 0) passInputs[0].focus();
    </script>
    """, height=0)


def _forgot_password_form():
    st.markdown("##### Password Recovery")

    with st.form("forgot_password_form"):
        email = st.text_input("Enter your recovery email address")

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            submitted = st.form_submit_button("Send Password", use_container_width=True)
        with btn_c2:
            back = st.form_submit_button("Back to Sign In", use_container_width=True)

        if submitted:
            if email == RECOVERY_EMAIL:
                if _send_recovery_email():
                    st.success(f"Password sent to {_mask_email(email)}. Check your inbox.")
                else:
                    st.error("Could not send email. Please contact the administrator.")
            else:
                st.error("Email address does not match the recovery email on file.")
        if back:
            st.session_state["show_forgot_password"] = False
            st.rerun()


def _mask_email(email: str) -> str:
    """Mask email for display: b***@yahoo.com"""
    local, domain = email.split("@")
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def _send_recovery_email() -> bool:
    """Generate a new random password, store it, and email it."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        return False

    new_password = secrets.token_urlsafe(8)
    try:
        _set_stored_password(new_password)
    except Exception:
        return False

    msg = MIMEText(
        f"Your Case Study Search password has been reset.\n\n"
        f"Username: {ADMIN_USERNAME}\n"
        f"New Password: {new_password}\n\n"
        f"You can change this after logging in via Settings > Change Password.\n\n"
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
        if "auth" in st.query_params:
            del st.query_params["auth"]
        st.rerun()



def search(query: str, top_k: int = 5) -> list[dict]:
    supabase, voyage = get_clients()

    # Embed query
    embed_result = voyage.embed(
        [query[:8000]],
        model="voyage-3-large",
        input_type="query",
    )
    query_embedding = embed_result.embeddings[0]

    # Hybrid search: vector similarity + full-text keyword matching (RRF)
    response = supabase.rpc(
        "match_case_studies",
        {
            "query_embedding": query_embedding,
            "match_count": top_k * 4,
            "match_threshold": 0.15,
            "search_query": query,
        },
    ).execute()

    if not response.data:
        return []

    # Rerank with cross-encoder (include tags/industry for better scoring)
    rerank_docs = []
    for row in response.data:
        parts = [f"{row.get('company_name', '')} — {row.get('use_case', '')}"]
        if row.get("industry"):
            parts.append(f"Industry: {row['industry']}")
        if row.get("tags"):
            parts.append(f"Tags: {row['tags']}")
        parts.append(row.get("summary", ""))
        rerank_docs.append(". ".join(parts))
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
            "tags": row.get("tags", ""),
            "industry": row.get("industry", ""),
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

tab_keyword, tab_agenda, tab_settings = st.tabs(["Keyword Search", "Meeting Agenda Search", "Settings"])

# --- Tab 1: Keyword Search ---
with tab_keyword:
    search_col1, search_col2, search_col3 = st.columns([5, 1, 1])
    with search_col1:
        query = st.text_input(
            "Search",
            placeholder="e.g., inventory management, mobile app development, healthcare platform",
            label_visibility="collapsed",
        )
    with search_col2:
        top_k = st.selectbox("Results", [3, 5, 10], index=1, format_func=lambda x: f"Top {x}", label_visibility="collapsed")
    with search_col3:
        search_clicked = st.button("Search", use_container_width=True)

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
                if r.get("industry"):
                    meta_parts.append(r["industry"])
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
                            f'border-radius:20px; white-space:nowrap;">Relevance {r["relevance_score"]}%</span>',
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

# --- Tab 2: Meeting Agenda Search ---
with tab_agenda:
    st.markdown(
        '<p style="font-size: 0.85rem; color: #64748b; margin-bottom: 0.75rem;">'
        'Paste a meeting agenda to find matching case studies and get a conversation flow for weaving them in.</p>',
        unsafe_allow_html=True,
    )

    agenda_col1, agenda_col2 = st.columns([6, 1])
    with agenda_col1:
        agenda_text = st.text_input(
            "Meeting Agenda",
            placeholder="e.g., Discuss inventory management software for retail chain with 200+ stores",
            label_visibility="collapsed",
            key="agenda_input",
        )
    with agenda_col2:
        agenda_search_clicked = st.button("Find & Flow", use_container_width=True, key="agenda_btn")

    if agenda_text:
        with st.spinner("Finding relevant case studies..."):
            agenda_results = search(agenda_text, top_k=5)

        if not agenda_results:
            st.warning("No matching case studies found for this agenda.")
        else:
            st.markdown(
                f'<div class="results-count">{len(agenda_results)} case studies for this agenda</div>',
                unsafe_allow_html=True,
            )

            for i, r in enumerate(agenda_results, 1):
                title = r["company_name"]
                if r["use_case"]:
                    title += f" — {r['use_case']}"

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

                    st.caption(r["filename"])
                    st.write(r["summary"])

                    try:
                        supabase, _ = get_clients()
                        signed = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
                            r["filename"], 3600
                        )
                        if signed and signed.get("signedURL"):
                            st.link_button("View Case Study", signed["signedURL"])
                    except Exception:
                        pass


# --- Tab 3: Settings ---
with tab_settings:
    st.markdown("#### Change Password")
    with st.form("change_password_form"):
        current_pw = st.text_input("Current Password", type="password", key="cp_current")
        new_pw = st.text_input("New Password", type="password", key="cp_new")
        confirm_pw = st.text_input("Confirm New Password", type="password", key="cp_confirm")
        btn_col1, btn_col2, _ = st.columns([1, 1, 3])
        with btn_col1:
            change_submitted = st.form_submit_button("Update Password", use_container_width=True)
        with btn_col2:
            logout_submitted = st.form_submit_button("Logout", use_container_width=True)

        if logout_submitted:
            st.session_state["authenticated"] = False
            if "auth" in st.query_params:
                del st.query_params["auth"]
            st.rerun()

        if change_submitted:
            if not _verify_password(current_pw):
                st.error("Current password is incorrect.")
            elif len(new_pw) < 4:
                st.error("New password must be at least 4 characters.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            else:
                try:
                    _set_stored_password(new_pw)
                    st.query_params["auth"] = _make_auth_token()
                    st.success("Password updated successfully.")
                except Exception as e:
                    st.error(f"Failed to update: {e}")

# Footer
st.markdown("""
<div class="powered-by">
    Powered by AI
</div>
""", unsafe_allow_html=True)
