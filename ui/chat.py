"""Chat page - describe an architecture, get a diagram back."""

import logging

import streamlit as st

from agents import run_workflow
from config.models import DiagramState
from storage import conversation_store, diagram_store, log_activity
from ui.preview import show_preview
from ui.styles import page_header

logger = logging.getLogger(__name__)


def render() -> None:
    """Draw the chat page."""
    page_header(
        "💬",
        "Design a diagram",
        "Describe what you want to build. To review a diagram you already have, "
        "use the Review page.",
    )

    conversations = conversation_store.get_all_conversations(st.session_state.user_id)
    _conversation_bar(conversations)

    conv = st.session_state.current_conversation

    if conv is None:
        st.info(
            "Start by describing your architecture below - for example: "
            "*\"A serverless order processing system on AWS with a queue and a "
            "managed database.\"*"
        )
    else:
        for message in conv.messages:
            with st.chat_message(message.role):
                st.write(message.content)
                if message.type == "diagram":
                    _diagram_result(message)

    user_input = st.chat_input("Describe your architecture...")
    if user_input:
        with st.spinner("Designing your architecture..."):
            _handle_send(user_input)


# ==================== Conversation picker ====================

def _conversation_bar(conversations) -> None:
    """Conversation selector plus a new-chat button."""
    picker, new_chat = st.columns([4, 1])

    with picker:
        if conversations:
            current = st.session_state.current_conversation
            options = [None] + conversations
            index = 0

            if current:
                for position, conv in enumerate(options[1:], start=1):
                    if conv.conversation_id == current.conversation_id:
                        index = position
                        break

            selected = st.selectbox(
                "Conversation",
                options,
                index=index,
                format_func=lambda c: (
                    "New conversation" if c is None
                    else f"{c.title} · {len(c.messages)} messages"
                ),
                key="conversation_select",
                label_visibility="collapsed",
            )
            st.session_state.current_conversation = selected
        else:
            st.caption("No conversations yet.")

    with new_chat:
        if st.button("＋ New", use_container_width=True):
            st.session_state.current_conversation = None
            st.rerun()

    st.markdown("---")


def _diagram_result(message) -> None:
    """Show the diagram a chat message produced, and offer it for download."""
    diagram_id = message.metadata.get("diagram_id")
    if not diagram_id:
        return

    xml = diagram_store.load_diagram(st.session_state.user_id, diagram_id)
    if not xml:
        return

    png = show_preview(xml)
    image, drawio, _spacer = st.columns([1, 1, 3])

    if png:
        with image:
            st.download_button(
                "🖼️ PNG",
                png,
                file_name=f"{diagram_id}.png",
                mime="image/png",
                key=f"chat_png_{message.id}",
                use_container_width=True,
            )

    with drawio:
        st.download_button(
            "📥 .drawio",
            xml,
            file_name=f"{diagram_id}.drawio",
            mime="application/xml",
            key=f"chat_dl_{message.id}",
            use_container_width=True,
        )


# ==================== Sending ====================

def _handle_send(user_input: str) -> None:
    """Run the workflow for one message and persist the results."""
    conv = st.session_state.current_conversation

    # Conversations are created on the first message, not on page load -
    # visiting the page used to leave an empty conversation behind every time.
    if conv is None:
        existing = conversation_store.get_all_conversations(st.session_state.user_id)
        conv = conversation_store.create_conversation(
            user_id=st.session_state.user_id,
            title=_title_from(user_input, len(existing) + 1),
        )
        st.session_state.current_conversation = conv

    state = DiagramState(
        user_id=st.session_state.user_id,
        conversation_id=conv.conversation_id,
        user_input=user_input,
        conversation_history=conv.messages,
    )

    state = run_workflow(state)

    conversation_store.add_message(
        st.session_state.user_id, conv.conversation_id, "user", user_input
    )

    if state.generated_diagram:
        _record_diagram(conv, state)
    elif state.review_results:
        _record_review(conv, state)
    else:
        error = state.error or "The request could not be completed."
        conversation_store.add_message(
            st.session_state.user_id, conv.conversation_id, "assistant", f"❌ {error}"
        )

    st.session_state.current_conversation = conversation_store.load_conversation(
        st.session_state.user_id, conv.conversation_id
    )
    st.rerun()


def _title_from(user_input: str, index: int) -> str:
    """A readable conversation title taken from the first message."""
    text = " ".join(user_input.split())
    if not text:
        return f"Conversation {index}"
    return text[:47] + "…" if len(text) > 48 else text


def _record_diagram(conv, state) -> None:
    """Persist and show a generated diagram."""
    providers = ", ".join(state.cloud_providers) or "unspecified cloud"
    text = (
        f"✅ Architecture diagram created for **{providers}**.\n\n"
        f"Open it from **My Diagrams**, or download it below."
    )
    conversation_store.add_message(
        st.session_state.user_id,
        conv.conversation_id,
        "assistant",
        text,
        "diagram",
        metadata={"diagram_id": state.diagram_id},
    )
    log_activity(
        user_id=st.session_state.user_id,
        action="create_diagram",
        details={"diagram_id": state.diagram_id},
    )


def _record_review(conv, state) -> None:
    """Persist and show a review result."""
    review = state.review_results
    score = f"{review.overall_score:.0f}/100" if review.overall_score is not None else "n/a"
    text = (
        f"✅ Architecture review completed.\n\n"
        f"Issues found: {len(review.issues)}\n\nScore: {score}"
    )
    conversation_store.add_message(
        st.session_state.user_id, conv.conversation_id, "assistant", text, "review"
    )
    log_activity(
        user_id=st.session_state.user_id,
        action="review_diagram",
        details={"issues": len(review.issues)},
    )
