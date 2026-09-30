"""Admin dashboard - system health, users, local models and maintenance."""

import logging

import requests
import streamlit as st

from auth import admin_manager
from config.model_fallback import model_fallback
from config.runtime_config import runtime_config
from services import ollama_service
from services.ollama_service import INSTALL_URL
from ui.styles import page_header

logger = logging.getLogger(__name__)


def render() -> None:
    """Draw the admin dashboard."""
    page_header(
        "🛠️",
        "Admin dashboard",
        "Visible to administrators only: system health, user accounts, local AI "
        "models and data maintenance.",
    )

    health_tab, users_tab, models_tab, maintenance_tab = st.tabs(
        ["System health", "Users", "Local models", "Maintenance"]
    )

    with health_tab:
        _health_tab()
    with users_tab:
        _users_tab()
    with models_tab:
        _models_tab()
    with maintenance_tab:
        _maintenance_tab()


# ==================== System health ====================

def _health_tab() -> None:
    stats = admin_manager.get_admin_dashboard_stats()

    users, active, diagrams, logins = st.columns(4)
    users.metric("Total users", stats.get("total_users", 0))
    active.metric("Active users", stats.get("active_users", 0))
    diagrams.metric("Total diagrams", stats.get("total_diagrams", 0))
    logins.metric("Logins today", stats.get("logins_today", 0))

    st.markdown("---")

    configuration = admin_manager.get_model_configuration()

    if configuration.get("offline_mode"):
        st.success("🔒 Offline mode is on - only models on this machine are used.")
    else:
        st.info("🌐 Online mode - cloud providers are used first, cheapest first.")

    active_llm, active_vision = st.columns(2)
    active_llm.markdown(f"**Active LLM**\n\n`{configuration.get('active_llm') or 'none'}`")
    active_vision.markdown(
        f"**Active vision model**\n\n`{configuration.get('active_vision_model') or 'none'}`"
    )

    st.markdown("**Resolved chains**")
    st.markdown(
        "- LLM: " + (" → ".join(configuration.get("llm_chain") or []) or "_none available_")
    )
    st.markdown(
        "- Vision: " + (" → ".join(configuration.get("vision_chain") or []) or "_none available_")
    )

    with st.expander("Raw model configuration"):
        st.json(configuration)

    storage = (stats.get("system_health") or {}).get("storage") or {}
    if storage:
        with st.expander("Storage usage"):
            st.json(storage)


# ==================== Users ====================

def _users_tab() -> None:
    st.markdown("#### Create a user")
    st.caption(
        "Standard users get the Design, Review and My Diagrams pages. "
        "Administrators additionally get this dashboard."
    )

    with st.form("create_user_form", clear_on_submit=True):
        name_field, password_field, admin_field = st.columns([2, 2, 1])
        username = name_field.text_input("Username")
        password = password_field.text_input("Password", type="password")
        is_admin = admin_field.checkbox("Administrator")
        submitted = st.form_submit_button("Create user")

    if submitted:
        if not username or not password:
            st.warning("A username and password are required.")
        else:
            created, error = admin_manager.create_user(
                username=username, password=password, is_admin=is_admin
            )
            if created:
                st.success(f"Created {'admin' if is_admin else 'user'} “{username}”.")
                st.rerun()
            else:
                st.error(error or "Could not create the user.")

    st.markdown("---")
    st.markdown("#### Accounts")

    for user in admin_manager.get_all_users_with_stats():
        details, role, toggle, delete = st.columns([3, 1, 1, 1])
        username = user["username"]
        is_self = username == st.session_state.username

        with details:
            st.markdown(f"**{username}**" + (" *(you)*" if is_self else ""))
            st.caption(
                f"{user.get('diagrams_created', 0)} conversations · "
                f"last login: {user.get('last_login') or 'never'}"
            )

        with role:
            st.markdown("👑 **Admin**" if user.get("is_admin") else "👤 User")

        with toggle:
            if not is_self:
                label = "Revoke admin" if user.get("is_admin") else "Make admin"
                if st.button(label, key=f"admin_{user['user_id']}", use_container_width=True):
                    admin_manager.toggle_admin_status(username)
                    st.rerun()

        with delete:
            if not is_self:
                if st.button("🗑️", key=f"deluser_{user['user_id']}", use_container_width=True):
                    admin_manager.delete_user(username)
                    st.rerun()

        st.divider()


# ==================== Local models ====================

def _models_tab() -> None:
    """Offline mode, model downloads and local model housekeeping."""
    _flash()

    running, message = ollama_service.status()

    if running:
        st.success(f"✅ {message}")
    else:
        st.warning(f"⚠️ {message}")
        with st.expander("How to run this app fully offline", expanded=True):
            st.markdown(
                f"""
                1. Install **Ollama** from [{INSTALL_URL}]({INSTALL_URL}) - it is
                   free and runs entirely on this machine.
                2. Start it: it runs as a background service after install, or
                   run `ollama serve` in a terminal.
                3. Reload this page, then download a model below.
                4. Turn on **Offline mode** so no request leaves the network.
                """
            )
        return

    _offline_mode_control()
    st.markdown("---")
    _active_model_control()
    st.markdown("---")
    _download_catalogue()
    st.markdown("---")
    _installed_models()


def _offline_mode_control() -> None:
    """Toggle that restricts the app to on-machine providers."""
    st.markdown("#### Offline mode")

    current = bool(runtime_config.get("offline_mode"))
    chosen = st.toggle(
        "Use only models on this machine",
        value=current,
        help="Skips Groq, Gemini and Claude even when API keys are set. Nothing "
             "is sent over the internet.",
    )

    if chosen != current:
        runtime_config.set(offline_mode=chosen)
        model_fallback.refresh_model_availability()
        st.rerun()

    if chosen and not model_fallback.llm_candidates():
        st.error(
            "Offline mode is on but no local model is downloaded yet - requests "
            "will fail until you download one below."
        )
    elif chosen:
        st.caption("Requests are served entirely by Ollama on this machine.")
    else:
        st.caption(
            "Cloud providers are tried first (cheapest first), with local models "
            "as a fallback."
        )


def _active_model_control() -> None:
    """Pick which downloaded model serves text and vision requests."""
    st.markdown("#### Active local models")

    installed = [m["name"] for m in ollama_service.installed_models()]

    if not installed:
        st.caption("No models downloaded yet.")
        return

    text_column, vision_column = st.columns(2)

    with text_column:
        _model_selector(
            "Text model (blueprints, reviews)",
            key="ollama_llm_model",
            installed=installed,
            widget_key="llm_model_select",
        )

    with vision_column:
        _model_selector(
            "Vision model (reads uploaded images)",
            key="ollama_vision_model",
            installed=installed,
            widget_key="vision_model_select",
        )


def _model_selector(label: str, key: str, installed: list, widget_key: str) -> None:
    """One selectbox bound to a runtime_config key."""
    current = runtime_config.get(key)

    # Ollama tags bare names as ":latest", so a configured "mistral" and an
    # installed "mistral:latest" are the same model - show it once.
    tagged = current if ":" in current else f"{current}:latest"
    downloaded = current in installed or tagged in installed

    # A model that is configured but not downloaded stays in the list, so the
    # selectbox cannot silently switch the app to a different model.
    options = installed if downloaded else [current] + installed
    selected = tagged if tagged in installed else current

    chosen = st.selectbox(
        label, options, index=options.index(selected), key=widget_key
    )

    if chosen != selected:
        runtime_config.set(**{key: chosen})
        model_fallback.refresh_model_availability()
        st.rerun()

    if not downloaded:
        st.caption(f"⚠️ `{current}` is not downloaded on this machine.")


def _download_catalogue() -> None:
    """Curated free models, each with a one-click download."""
    st.markdown("#### Download a free model")
    st.caption(
        "Open-weights models that run locally at no cost. Downloads are large - "
        "keep this tab open until one finishes."
    )

    installed = {m["name"] for m in ollama_service.installed_models()}

    for role, heading in (("llm", "Text models"), ("vision", "Vision models")):
        st.markdown(f"**{heading}**")

        for model in ollama_service.curated(role):
            details, size, action = st.columns([5, 1, 1])
            downloaded = model.name in installed or f"{model.name}:latest" in installed

            with details:
                st.markdown(f"**{model.name}**")
                st.caption(model.blurb)

            with size:
                st.caption(f"{model.size_gb:.1f} GB\n\n{model.ram_gb} GB RAM")

            with action:
                if downloaded:
                    st.caption("✅ Installed")
                elif st.button(
                    "Download", key=f"pull_{model.name}", use_container_width=True
                ):
                    _download_model(model.name)

        st.markdown("")

    with st.expander("Download another model by name"):
        st.caption(
            "Any tag from the Ollama library, for example `llama3.2:1b` or "
            "`qwen2.5-coder:7b`."
        )
        name_field, button_field = st.columns([3, 1])
        custom = name_field.text_input("Model name", label_visibility="collapsed")
        if button_field.button("Download", key="pull_custom", use_container_width=True):
            if custom.strip():
                _download_model(custom.strip())
            else:
                st.warning("Enter a model name first.")


def _download_model(name: str) -> None:
    """Pull a model, showing real download progress."""
    progress = st.progress(0.0, text=f"Preparing {name}…")

    try:
        for update in ollama_service.pull(name):
            total = update["total"]
            completed = update["completed"]
            fraction = min(completed / total, 1.0) if total else 0.0

            if total:
                label = (
                    f"{update['status']} — "
                    f"{ollama_service.format_size(completed)} of "
                    f"{ollama_service.format_size(total)}"
                )
            else:
                label = update["status"] or f"Downloading {name}…"

            progress.progress(fraction, text=label)

    except requests.RequestException as e:
        progress.empty()
        st.error(f"Could not reach Ollama while downloading {name}: {e}")
        return
    except RuntimeError as e:
        progress.empty()
        st.error(f"Ollama could not download {name}: {e}")
        return

    progress.progress(1.0, text=f"{name} downloaded")
    model_fallback.refresh_model_availability()

    st.session_state.models_flash = ("success", f"Downloaded {name}.")
    st.rerun()


def _installed_models() -> None:
    """Everything downloaded on this machine, with disk usage."""
    st.markdown("#### Downloaded on this machine")

    installed = ollama_service.installed_models()
    if not installed:
        st.caption("Nothing downloaded yet.")
        return

    total = sum(m["size_bytes"] for m in installed)
    st.caption(
        f"{len(installed)} model(s) · {ollama_service.format_size(total)} on disk"
    )

    in_use = {
        runtime_config.get("ollama_llm_model"),
        runtime_config.get("ollama_vision_model"),
    }

    for model in installed:
        name_column, size_column, delete_column = st.columns([4, 1, 1])

        bare_name = model["name"].split(":")[0]
        active = model["name"] in in_use or bare_name in in_use

        name_column.markdown(f"`{model['name']}`" + ("  ·  **in use**" if active else ""))
        size_column.caption(ollama_service.format_size(model["size_bytes"]))

        if delete_column.button(
            "🗑️", key=f"rmmodel_{model['name']}", use_container_width=True
        ):
            deleted, message = ollama_service.delete(model["name"])
            model_fallback.refresh_model_availability()
            st.session_state.models_flash = ("success" if deleted else "error", message)
            st.rerun()


def _flash() -> None:
    """Show and clear a one-shot message set before a rerun."""
    flash = st.session_state.pop("models_flash", None)
    if not flash:
        return

    level, message = flash
    if level == "success":
        st.success(message)
    else:
        st.error(message)


# ==================== Maintenance ====================

def _maintenance_tab() -> None:
    st.markdown("#### Models")
    if st.button("Re-check provider availability"):
        admin_manager.refresh_model_availability()
        st.success("Providers re-checked.")

    st.markdown("---")
    st.markdown("#### Data")

    days = st.number_input(
        "Delete conversations, diagrams and logs older than (days)",
        min_value=7,
        max_value=3650,
        value=90,
        step=1,
    )
    if st.button("Clean up old data"):
        _, message = admin_manager.cleanup_old_data(int(days))
        st.success(message)

    if st.button("Create backup"):
        success, message = admin_manager.backup_data()
        st.success(message) if success else st.error(message)

    st.markdown("---")
    st.markdown("#### Runtime settings")
    st.caption("Offline mode and the chosen local models, as stored on disk.")
    st.json(runtime_config.all())

    if st.button("Reset to .env defaults"):
        runtime_config.reset()
        model_fallback.refresh_model_availability()
        st.rerun()
