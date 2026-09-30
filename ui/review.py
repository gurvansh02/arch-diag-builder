"""Review page - upload an existing architecture diagram and have it critiqued."""

import logging
import os
import tempfile
from pathlib import Path

import streamlit as st

from agents.review_agent import review_agent
from config.models import DiagramState, TaskType
from config.settings import MAX_UPLOAD_SIZE
from storage import log_activity, review_store
from ui import validate
from ui.styles import CATEGORY_ICONS, page_header, score_badge, severity_badge

logger = logging.getLogger(__name__)

UPLOAD_TYPES = ["png", "jpg", "jpeg", "drawio", "xml", "pdf"]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low"]

# Reviews are run outside any chat thread, so they get a fixed marker instead
# of a real conversation id.
STANDALONE_CONVERSATION_ID = "standalone-review"


def render() -> None:
    """Draw the review page: critique on one tab, correctness on the other."""
    page_header(
        "🔍",
        "Review a diagram",
        "Assess an existing architecture, or cross-check that it is correct.",
    )

    # Two different questions, so two tabs. Review asks how good the design is;
    # Validate asks whether what is drawn actually holds together.
    review_tab, validate_tab = st.tabs(["🔍  Review", "✅  Validate"])

    with review_tab:
        _review_tab()

    with validate_tab:
        validate.render()


def _review_tab() -> None:
    """Upload an architecture and have it critiqued."""
    st.markdown(
        "Upload an architecture you already have and get it assessed for "
        "security, cost, performance, scalability and compliance."
    )

    upload_column, guide_column = st.columns([3, 2])

    with upload_column:
        _upload_panel()

    with guide_column:
        _guide_panel()

    result = st.session_state.get("review_result")
    if result:
        st.markdown("---")
        _render_review(result)

    st.markdown("---")
    _history_panel()


# ==================== Upload ====================

def _upload_panel() -> None:
    """File picker and the button that starts the review."""
    uploaded_file = st.file_uploader(
        "Architecture file",
        type=UPLOAD_TYPES,
        help="PNG / JPG screenshot, PDF document, or a draw.io (.drawio / .xml) file.",
    )

    if uploaded_file is None:
        st.caption(f"Maximum size: {MAX_UPLOAD_SIZE / 1_048_576:.0f} MB")
        return

    size_mb = uploaded_file.size / 1_048_576
    st.caption(f"**{uploaded_file.name}** · {size_mb:.1f} MB")

    if Path(uploaded_file.name).suffix.lower() in IMAGE_SUFFIXES:
        st.image(uploaded_file, use_container_width=True)

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        st.error(
            f"File is {size_mb:.1f} MB - the limit is "
            f"{MAX_UPLOAD_SIZE / 1_048_576:.0f} MB."
        )
        return

    if st.button("Run review", type="primary", use_container_width=True):
        with st.spinner("Reading the diagram and reviewing the architecture..."):
            _run_review(uploaded_file)


def _guide_panel() -> None:
    """What the reviewer looks at, and what makes a good upload."""
    st.markdown(
        """
        <div class="adb-card">
        <h4>What gets checked</h4>
        <p class="adb-muted">
        🔒 Security gaps &nbsp; 💰 Cost optimisation &nbsp; ⚡ Performance<br>
        📈 Scalability &nbsp; 📋 Compliance &nbsp; 🏗️ Missing components
        </p>
        </div>

        <div class="adb-card">
        <h4>Getting a good review</h4>
        <p class="adb-muted">
        • <b>.drawio / .xml</b> files read best - the component names are exact.<br>
        • Screenshots need a vision model; check Admin → Local Models if image
          reading fails.<br>
        • Crop to the diagram itself and keep the labels legible.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _run_review(uploaded_file) -> None:
    """Write the upload to a temp file and hand it to the review agent."""
    # Keep the real extension - file type detection is extension-based, so a
    # suffix-less temp file is rejected as "not supported".
    suffix = Path(uploaded_file.name).suffix
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getbuffer())
            temp_path = tmp.name

        state = DiagramState(
            user_id=st.session_state.user_id,
            conversation_id=STANDALONE_CONVERSATION_ID,
            user_input="",
            task_type=TaskType.REVIEW,
            uploaded_file_path=temp_path,
            uploaded_file_name=uploaded_file.name,
        )

        # The review agent is called directly: an upload with no prompt is
        # unambiguously a review, so routing it through the orchestrator would
        # only spend an extra model call to reach the same conclusion.
        state = review_agent.review(state)

        if state.error:
            st.session_state.review_result = None
            st.error(state.error)
            return

        st.session_state.review_result = state.review_results
        log_activity(
            user_id=st.session_state.user_id,
            action="review_diagram",
            details={
                "issues": len(state.review_results.issues),
                "file": uploaded_file.name,
            },
        )
        st.rerun()

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError as e:
                logger.warning("Could not remove temp upload %s: %s", temp_path, e)


# ==================== Results ====================

def _render_review(review) -> None:
    """Score, summary and the issue list for one review."""
    title = review.source_filename or "Uploaded architecture"
    st.markdown(f"### Review of {title}")

    score, issues, critical = st.columns([1, 1, 1])
    with score:
        st.markdown("**Overall score**")
        st.markdown(score_badge(review.overall_score), unsafe_allow_html=True)
    with issues:
        st.metric("Issues found", len(review.issues))
    with critical:
        blocking = sum(1 for i in review.issues if i.severity.value in ("Critical", "High"))
        st.metric("Critical / High", blocking)

    if review.summary:
        st.markdown(f"> {review.summary}")

    if not review.issues:
        st.success("No issues were raised for this architecture.")
    else:
        _render_issues(review)

    st.download_button(
        "📄 Download report (Markdown)",
        _report_markdown(review),
        file_name=f"review_{review.review_id[:8]}.md",
        mime="text/markdown",
        key=f"report_{review.review_id}",
    )


def _render_issues(review) -> None:
    """Issues grouped by severity, worst first."""
    by_severity = {level: [] for level in SEVERITY_ORDER}
    for issue in review.issues:
        by_severity.setdefault(issue.severity.value, []).append(issue)

    for level in SEVERITY_ORDER:
        found = by_severity.get(level) or []
        if not found:
            continue

        st.markdown(
            f"{severity_badge(level)} &nbsp;<b>{len(found)} "
            f"issue{'s' if len(found) != 1 else ''}</b>",
            unsafe_allow_html=True,
        )

        for position, issue in enumerate(found):
            icon = CATEGORY_ICONS.get(issue.category.value, "•")
            headline = issue.description.split(". ")[0][:90]

            with st.expander(f"{icon} {issue.category.value} — {headline}"):
                st.markdown(issue.description)
                st.markdown(f"**Suggested fix:** {issue.suggestion}")
                if issue.affected_components:
                    pills = "".join(
                        f'<span class="adb-pill">{component}</span>'
                        for component in issue.affected_components
                    )
                    st.markdown(f"**Affected:** {pills}", unsafe_allow_html=True)


def _report_markdown(review) -> str:
    """The review as a self-contained Markdown document."""
    score = f"{review.overall_score:.0f}/100" if review.overall_score is not None else "n/a"

    lines = [
        f"# Architecture review — {review.source_filename or 'uploaded architecture'}",
        "",
        f"- **Date:** {review.created_at.strftime('%Y-%m-%d %H:%M')} UTC",
        f"- **Source type:** {review.uploaded_file_type}",
        f"- **Overall score:** {score}",
        f"- **Issues found:** {len(review.issues)}",
        "",
    ]

    if review.summary:
        lines += ["## Summary", "", review.summary, ""]

    if review.issues:
        lines += ["## Issues", ""]

    for level in SEVERITY_ORDER:
        for issue in review.issues:
            if issue.severity.value != level:
                continue
            lines += [
                f"### [{level}] {issue.category.value}",
                "",
                issue.description,
                "",
                f"**Suggested fix:** {issue.suggestion}",
                "",
            ]
            if issue.affected_components:
                lines += [
                    f"**Affected components:** {', '.join(issue.affected_components)}",
                    "",
                ]

    return "\n".join(lines)


# ==================== History ====================

def _history_panel() -> None:
    """Previously run reviews, with re-open and delete."""
    reviews = review_store.get_user_reviews(st.session_state.user_id)

    st.markdown("#### Past reviews")

    if not reviews:
        st.caption("Reviews you run are kept here.")
        return

    current = st.session_state.get("review_result")

    for review in reviews[:15]:
        details, open_button, delete_button = st.columns([5, 1, 1])

        with details:
            name = review.source_filename or review.uploaded_file_type
            when = review.created_at.strftime("%Y-%m-%d %H:%M")
            st.markdown(
                f"**{name}** &nbsp;{score_badge(review.overall_score)}"
                f'<br><span class="adb-muted">{when} · {len(review.issues)} issues</span>',
                unsafe_allow_html=True,
            )

        with open_button:
            is_open = current is not None and current.review_id == review.review_id
            if st.button(
                "Open",
                key=f"open_{review.review_id}",
                disabled=is_open,
                use_container_width=True,
            ):
                st.session_state.review_result = review
                st.rerun()

        with delete_button:
            if st.button("🗑️", key=f"delrev_{review.review_id}", use_container_width=True):
                review_store.delete_review(st.session_state.user_id, review.review_id)
                if current is not None and current.review_id == review.review_id:
                    st.session_state.review_result = None
                st.rerun()

        st.divider()
