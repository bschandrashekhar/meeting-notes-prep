"""Streamlit app for searching case studies via Voyage AI + Supabase pgvector."""

import base64
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
    page_title="Case Study Search",
    page_icon="🔍",
    layout="wide",
)


# --- Authentication ---

def check_login():
    """Show login form and gate access."""
    if st.session_state.get("authenticated"):
        return True

    st.title("Case Study Search")
    st.markdown("Please log in to continue.")

    # Toggle between login and forgot password
    if st.session_state.get("show_forgot_password"):
        _forgot_password_form()
    else:
        _login_form()

    return False


def _login_form():
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in", use_container_width=True)

        if submitted:
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Invalid username or password.")

    if st.button("Forgot Password?"):
        st.session_state["show_forgot_password"] = True
        st.rerun()


def _forgot_password_form():
    st.subheader("Password Recovery")

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

    if st.button("Back to Login"):
        st.session_state["show_forgot_password"] = False
        st.rerun()


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

st.title("Case Study Search")
st.markdown("Search across **133 case studies** using AI-powered semantic search with reranking.")

# Logout button in sidebar
with st.sidebar:
    st.markdown(f"Logged in as **{ADMIN_USERNAME}**")
    if st.button("Logout"):
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
    st.error("Missing environment variables. Set SUPABASE_URL, SUPABASE_SERVICE_KEY, and VOYAGE_API_KEY in .env")
    st.stop()

# Search input
query = st.text_input(
    "What are you looking for?",
    placeholder="e.g., inventory management, mobile app development, healthcare platform",
)

col1, col2 = st.columns([1, 4])
with col1:
    top_k = st.selectbox("Results", [3, 5, 10], index=1)

# Search
if query:
    with st.spinner("Searching and reranking..."):
        results = search(query, top_k=top_k)

    if not results:
        st.warning("No matching case studies found. Try a broader query.")
    else:
        st.markdown(f"**{len(results)} results** for: *{query}*")
        st.divider()

        for i, r in enumerate(results, 1):
            with st.container():
                title = r["company_name"]
                if r["use_case"]:
                    title += f" — {r['use_case']}"

                col_title, col_score = st.columns([4, 1])
                with col_title:
                    st.subheader(f"{i}. {title}")
                with col_score:
                    st.metric("Relevance", f"{r['relevance_score']}%")

                if r["doc_type"]:
                    st.caption(f"Type: {r['doc_type']}  |  File: {r['filename']}")
                else:
                    st.caption(f"File: {r['filename']}")

                st.write(r["summary"])

                try:
                    supabase, _ = get_clients()
                    signed = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
                        r["filename"], 3600
                    )
                    if signed and signed.get("signedURL"):
                        st.markdown(f"[Download PDF]({signed['signedURL']})")
                except Exception:
                    pass

                st.divider()
else:
    # Show total count on load
    try:
        supabase, _ = get_clients()
        count_resp = supabase.table("case_studies").select("id", count="exact").execute()
        total = count_resp.count if count_resp.count else len(count_resp.data)
        st.info(f"Ready to search across **{total}** case studies. Enter a query above to get started.")
    except Exception:
        st.info("Enter a query above to search case studies.")
