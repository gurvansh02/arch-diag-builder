"""
Main Streamlit application for Architecture Diagram Builder.

This module is routing only - each page lives in its own module under ui/.
"""

import logging
import os

import streamlit as st

# Streamlit Cloud has no .env file - secrets set in the app dashboard land in
# st.secrets. Everything downstream (config/settings.py, auth/) reads plain
# os.getenv(), so mirror secrets into the environment before those import.
for _key, _value in st.secrets.items():
    os.environ.setdefault(_key, str(_value))

from config import initialize_models, model_fallback
from storage import log_activity
from ui import admin, chat, diagrams, login, review
from ui.styles import inject_css

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Architecture Diagram Builder",
    page_icon="📐",
    layout="wide",
    initial_sidebar_state="expanded",
)

# (page key, icon, sidebar label, render function, admin only)
PAGES = [
    ("chat", "💬", "Design", chat.render, False),
    ("review", "🔍", "Review", review.render, False),
    ("diagrams", "📊", "My diagrams", diagrams.render, False),
    ("admin", "🛠️", "Admin", admin.render, True),
]

SESSION_DEFAULTS = {
    "authenticated": False,
    "user_id": None,
    "username": None,
    "is_admin": False,
    "page": "chat",
    "current_conversation": None,
    "review_result": None,
    # Cleared on logout like everything else here - a validation holds another
    # user's diagram contents, so it must not survive a session change.
    "validation_result": None,
    "validation_xml": None,
}


# ==================== Session ====================

def initialize_session() -> None:
    """Populate session state with its defaults on first run."""
    for key, value in SESSION_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def logout() -> None:
    """Clear the session. Logs first, or the entry records no user."""
    log_activity(user_id=st.session_state.user_id, action="logout")
    for key, value in SESSION_DEFAULTS.items():
        st.session_state[key] = value


# ==================== Sidebar ====================

def sidebar() -> None:
    """Narrow navigation rail."""
    with st.sidebar:
        st.markdown("##### 🏗️ Diagram Builder")

        available = [p for p in PAGES if not p[4] or st.session_state.is_admin]

        # An admin who was demoted mid-session must not stay on the admin page.
        if st.session_state.page not in {p[0] for p in available}:
            st.session_state.page = "chat"

        for key, icon, label, _render, _admin_only in available:
            active = st.session_state.page == key
            if st.button(
                f"{icon}  {label}",
                key=f"nav_{key}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state.page = key
                st.rerun()

        st.markdown("---")

        if model_fallback.offline_mode():
            st.markdown("🔒 **Offline mode**")
            st.caption("Local models only")
        else:
            st.markdown("🌐 **Online mode**")
            st.caption("Cloud models first")

        st.markdown("---")
        st.caption(
            f"**{st.session_state.username}**"
            + ("  ·  admin" if st.session_state.is_admin else "")
        )

        if st.button("🚪  Log out", use_container_width=True):
            logout()
            st.rerun()


# ==================== Routing ====================

def main_app() -> None:
    """Render the sidebar and the selected page."""
    sidebar()
    provider_banner()

    for key, _icon, _label, render, _admin_only in PAGES:
        if key == st.session_state.page:
            render()
            return

    chat.render()


def provider_banner() -> None:
    """Warn when nothing can serve requests, and say how to fix it."""
    if model_fallback.llm_candidates():
        return

    if model_fallback.offline_mode():
        message = (
            "**Offline mode is on but no local model is available.** Install "
            "Ollama and download a model"
        )
    else:
        message = (
            "**No AI provider is configured.** Set `GROQ_API_KEY`, "
            "`GOOGLE_API_KEY` or `ANTHROPIC_API_KEY` in `.env`, or download a "
            "local model"
        )

    where = (
        " from **Admin → Local models**."
        if st.session_state.is_admin
        else ". Ask an administrator to set this up."
    )
    st.error(message + where)


# ==================== Entry point ====================

initialize_session()

inject_css()

if "models_initialized" not in st.session_state:
    with st.spinner("Checking AI model availability..."):
        st.session_state.models_initialized = initialize_models()

if st.session_state.authenticated:
    main_app()
else:
    login.render()
