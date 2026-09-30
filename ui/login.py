"""Login page."""

import streamlit as st

from auth import auth_manager
from config.model_fallback import model_fallback


def render() -> None:
    """Draw the login screen and sign the user in on success."""
    _, middle, _ = st.columns([1, 2, 1])

    with middle:
        st.markdown("# 🏗️ Architecture Diagram Builder")
        st.caption(
            "Generate cloud architecture diagrams and review existing ones with AI."
        )
        st.markdown("---")

        login_tab, about_tab = st.tabs(["Sign in", "About"])

        with login_tab:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", use_container_width=True)

            if submitted:
                _attempt_login(username, password)

            st.caption(
                "Accounts are created by an administrator - there is no self-service "
                "sign-up."
            )

        with about_tab:
            mode = "Offline (local models only)" if model_fallback.offline_mode() else "Online"
            st.markdown(
                f"""
                **What this app does**

                - Describe an architecture in plain English and get a draw.io diagram
                - Upload an existing diagram (image, PDF or `.drawio`) for a review
                  covering security, cost, performance, scalability and compliance
                - Keep every diagram and review in your own workspace

                **Current AI mode:** {mode}
                """
            )


def _attempt_login(username: str, password: str) -> None:
    """Validate credentials and populate the session on success."""
    if not username or not password:
        st.warning("Enter both a username and a password.")
        return

    success, user_id, error = auth_manager.login(username, password)

    if not success:
        st.error(f"Login failed: {error}")
        return

    st.session_state.authenticated = True
    st.session_state.user_id = user_id
    st.session_state.username = username
    st.session_state.is_admin = auth_manager.is_admin(username)
    st.rerun()
