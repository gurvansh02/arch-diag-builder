"""
Validate tab - cross-check whether a diagram is correct.

This is deliberately a different question from the Review tab. Review asks how
good an architecture is; validation asks whether what is drawn is internally
consistent and workable, and - just as importantly - how much the answer can be
trusted.

Two things drive the display:

- **Structural findings** come from deterministic graph rules. They are facts
  about the file and are shown as such.
- **Model findings** come from asking every available model the same question
  independently. Their agreement level is shown on every finding, and anything
  only one model raised is separated out as disputed rather than presented at
  the same weight as a corroborated result.

Validation needs the graph, so it takes draw.io XML: a .drawio/.xml upload or
one of the user's saved diagrams. A screenshot cannot be checked structurally,
and saying so is better than quietly running only half the checks.
"""

import logging

import streamlit as st

from agents.validation_agent import validation_agent
from config.models import Agreement
from config.settings import MAX_UPLOAD_SIZE
from storage import diagram_store, log_activity
from ui.preview import show_preview
from ui.styles import severity_badge

logger = logging.getLogger(__name__)

VALIDATE_TYPES = ["drawio", "xml"]

VERDICT_STYLE = {
    "Pass": ("#1B7F4B", "#E6F4EC", "✅"),
    "Pass with warnings": ("#8A6100", "#FFF4DA", "⚠️"),
    "Fail": ("#B3261E", "#FCE8E6", "❌"),
    "Unknown": ("#5A6672", "#EEF0F3", "•"),
}

AGREEMENT_HELP = {
    Agreement.STRUCTURAL: "A deterministic check of the file, not a model opinion.",
    Agreement.UNANIMOUS: "Every model consulted raised this independently.",
    Agreement.MAJORITY: "More than half the models consulted raised this.",
    Agreement.SINGLE: "Only one model raised this - treat it as a lead, not a fact.",
}

AGREEMENT_BADGE = {
    Agreement.STRUCTURAL: ("#1B4F9C", "#E7EEF9"),
    Agreement.UNANIMOUS: ("#1B7F4B", "#E6F4EC"),
    Agreement.MAJORITY: ("#8A6100", "#FFF4DA"),
    Agreement.SINGLE: ("#5A6672", "#EEF0F3"),
}

SEVERITY_ORDER = ["Critical", "High", "Medium", "Low", "Info"]


def render() -> None:
    """Draw the Validate tab."""
    st.markdown(
        "Check a diagram for internal correctness. Deterministic graph checks "
        "run first, then every available model reviews it **independently** and "
        "their answers are compared - a point two models reach separately is "
        "worth more than one model's confident guess."
    )

    source_column, guide_column = st.columns([3, 2])

    with source_column:
        _source_panel()

    with guide_column:
        _guide_panel()

    result = st.session_state.get("validation_result")
    if result:
        st.markdown("---")
        _render_result(result)


# ==================== Input ====================

def _source_panel() -> None:
    """Choose a saved diagram or upload one."""
    saved = diagram_store.get_user_diagrams(st.session_state.user_id)

    options = ["Upload a file"]
    if saved:
        options.insert(0, "One of my diagrams")

    choice = st.radio("What should I validate?", options, horizontal=True,
                      key="validate_source")

    if choice == "One of my diagrams":
        _saved_picker(saved)
    else:
        _upload_picker()


def _saved_picker(saved) -> None:
    """Pick from diagrams this user has already generated."""
    labels = {
        f"{item.project_description[:60]} · {item.created_at.strftime('%Y-%m-%d %H:%M')}":
        item.diagram_id
        for item in saved[:40]
    }

    selected = st.selectbox("Diagram", list(labels))
    diagram_id = labels[selected]

    if st.button("Validate", type="primary", width="stretch",
                 key="validate_saved"):
        xml = diagram_store.load_diagram(st.session_state.user_id, diagram_id)
        if not xml:
            st.error("That diagram could not be loaded.")
            return
        _run(xml, selected.split(" · ")[0])


def _upload_picker() -> None:
    """Upload a .drawio / .xml file."""
    uploaded = st.file_uploader(
        "draw.io file",
        type=VALIDATE_TYPES,
        help=(
            "Validation reads the diagram's graph, so it needs the draw.io "
            "source (.drawio or .xml). A screenshot cannot be checked "
            "structurally - use the Review tab for images."
        ),
        key="validate_upload",
    )

    if uploaded is None:
        st.caption(f"Maximum size: {MAX_UPLOAD_SIZE / 1_048_576:.0f} MB")
        return

    if uploaded.size > MAX_UPLOAD_SIZE:
        st.error(
            f"File is {uploaded.size / 1_048_576:.1f} MB - the limit is "
            f"{MAX_UPLOAD_SIZE / 1_048_576:.0f} MB."
        )
        return

    if st.button("Validate", type="primary", width="stretch",
                 key="validate_uploaded"):
        try:
            xml = uploaded.getvalue().decode("utf-8", errors="replace")
        except Exception as e:  # pragma: no cover - defensive
            st.error(f"Could not read that file: {e}")
            return
        _run(xml, uploaded.name)


def _guide_panel() -> None:
    """What validation does, and what it cannot promise."""
    st.markdown(
        """
        <div class="adb-card">
        <h4>What gets checked</h4>
        <p class="adb-muted">
        <b>Structurally</b> — dangling connections, orphaned components,
        duplicate names, disconnected groups, missing entry point,
        unlabelled flows.<br><br>
        <b>By model</b> — impossible flows, services used for the wrong job,
        missing components the drawn flows require, security boundaries.
        </p>
        </div>

        <div class="adb-card">
        <h4>How much to trust it</h4>
        <p class="adb-muted">
        Structural findings are facts about the file — reproducible, no model
        involved.<br><br>
        Model findings are opinions. Agreement between independent models makes
        one more credible, but models can be wrong together. Anything marked
        <b>Single model</b> is a lead to check, not a defect.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _run(drawio_xml: str, source_name: str) -> None:
    """Run validation and stash the result."""
    with st.spinner("Running structural checks, then cross-examining with each model..."):
        result = validation_agent.validate(
            drawio_xml=drawio_xml,
            user_id=st.session_state.user_id,
            source_name=source_name,
        )

    st.session_state.validation_result = result
    st.session_state.validation_xml = drawio_xml

    log_activity(
        user_id=st.session_state.user_id,
        action="validate_diagram",
        details={
            "verdict": result.verdict,
            "findings": len(result.findings),
            "models": result.models_consulted,
            "source": source_name,
        },
    )
    st.rerun()


# ==================== Results ====================

def _render_result(result) -> None:
    """Verdict, per-model panel, findings."""
    st.markdown(f"### Validation of {result.source_name}")

    colour, background, icon = VERDICT_STYLE.get(
        result.verdict, VERDICT_STYLE["Unknown"]
    )

    verdict_col, score_col, size_col, models_col = st.columns([2, 1, 1, 1])

    with verdict_col:
        st.markdown("**Verdict**")
        st.markdown(
            f'<span style="background:{background};color:{colour};padding:6px 14px;'
            f'border-radius:14px;font-weight:700;font-size:15px;">'
            f"{icon} {result.verdict}</span>",
            unsafe_allow_html=True,
        )
    with score_col:
        score = f"{result.consensus_score:.0f}" if result.consensus_score is not None else "—"
        st.metric("Consensus score", score)
    with size_col:
        st.metric("Components", result.component_count)
    with models_col:
        st.metric("Models agreed with", result.models_consulted)

    if result.notes:
        st.info(result.notes)

    _model_panel(result)

    if not result.findings:
        st.success(
            "Nothing was found. The structural checks passed and no model "
            "raised an issue."
        )
    else:
        _findings_panel(result)

    _preview_panel()

    st.download_button(
        "📄 Download validation report (Markdown)",
        _report_markdown(result),
        file_name=f"validation_{result.validation_id[:8]}.md",
        mime="text/markdown",
        key=f"valreport_{result.validation_id}",
    )


def _model_panel(result) -> None:
    """What each model concluded on its own."""
    if not result.model_verdicts:
        return

    with st.expander(
        f"Per-model verdicts ({result.models_consulted} of "
        f"{len(result.model_verdicts)} reachable)",
        expanded=False,
    ):
        for verdict in result.model_verdicts:
            if not verdict.reachable:
                st.markdown(
                    f"❌ **{verdict.model_label}** — not reachable "
                    f'<span class="adb-muted">({verdict.error})</span>',
                    unsafe_allow_html=True,
                )
                continue

            score = f"{verdict.score:.0f}/100" if verdict.score is not None else "no score"
            st.markdown(
                f"✅ **{verdict.model_label}** — {verdict.verdict or 'no verdict'} "
                f"· {score} · {verdict.finding_count} finding(s)"
            )
            if verdict.summary:
                st.caption(verdict.summary)

        if result.models_consulted < 2:
            st.warning(
                "Only one model answered, so nothing could be cross-checked. "
                "Every model finding below is a single unverified opinion. "
                "Configure a second provider in `.env` for a real cross-check."
            )


def _findings_panel(result) -> None:
    """Findings ordered by severity, with agreement shown on each."""
    corroborated = [
        finding for finding in result.findings if finding not in result.disputed
    ]

    st.markdown(f"#### Findings ({len(result.findings)})")

    for finding in corroborated:
        _finding_row(finding)

    if result.disputed:
        st.markdown("---")
        st.markdown(
            f"#### Disputed ({len(result.disputed)})  "
            f'<span class="adb-muted">raised by one model, not corroborated by '
            f"the others</span>",
            unsafe_allow_html=True,
        )
        st.caption(
            "These did not count towards the verdict. A model seeing something "
            "the others missed is sometimes right - and sometimes inventing it."
        )
        for finding in result.disputed:
            _finding_row(finding)


def _finding_row(finding) -> None:
    """One finding as an expander with its agreement badge."""
    colour, background = AGREEMENT_BADGE.get(finding.agreement, ("#5A6672", "#EEF0F3"))

    badge = (
        f'<span style="background:{background};color:{colour};padding:2px 9px;'
        f'border-radius:10px;font-size:11px;font-weight:600;">'
        f"{finding.agreement.value}</span>"
    )

    with st.expander(f"{finding.severity} — {finding.title[:90]}"):
        st.markdown(
            f"{severity_badge(finding.severity)} &nbsp; {badge} &nbsp;"
            f'<span class="adb-muted">confidence {finding.confidence:.0%}</span>',
            unsafe_allow_html=True,
        )
        st.markdown(finding.detail)

        st.caption(AGREEMENT_HELP.get(finding.agreement, ""))

        if finding.components:
            pills = "".join(
                f'<span class="adb-pill">{component}</span>'
                for component in finding.components
            )
            st.markdown(f"**Components:** {pills}", unsafe_allow_html=True)

        if finding.raised_by:
            st.caption("Raised by: " + ", ".join(finding.raised_by))


def _preview_panel() -> None:
    """The diagram that was validated, so findings can be read against it."""
    xml = st.session_state.get("validation_xml")
    if not xml:
        return

    with st.expander("The diagram that was validated", expanded=False):
        show_preview(xml)


# ==================== Report ====================

def _report_markdown(result) -> str:
    """The validation as a self-contained Markdown document."""
    score = (
        f"{result.consensus_score:.0f}/100"
        if result.consensus_score is not None else "n/a"
    )

    lines = [
        f"# Architecture validation — {result.source_name}",
        "",
        f"- **Date:** {result.created_at.strftime('%Y-%m-%d %H:%M')} UTC",
        f"- **Verdict:** {result.verdict}",
        f"- **Consensus score:** {score}",
        f"- **Components / connections:** {result.component_count} / {result.connection_count}",
        f"- **Models consulted:** {result.models_consulted}",
        f"- **Structural checks passed:** {'yes' if result.structural_ok else 'no'}",
        "",
        "## How to read this",
        "",
        "Structural findings are deterministic checks of the diagram file and "
        "are reproducible. Model findings are opinions from language models "
        "reviewing the diagram independently; the agreement level records how "
        "many of them raised the same point. A finding marked *Single model* "
        "was not corroborated and did not count towards the verdict.",
        "",
    ]

    if result.notes:
        lines += [f"> {result.notes}", ""]

    if result.model_verdicts:
        lines += ["## Per-model verdicts", ""]
        for verdict in result.model_verdicts:
            if not verdict.reachable:
                lines.append(f"- **{verdict.model_label}** — unreachable ({verdict.error})")
                continue
            model_score = f"{verdict.score:.0f}" if verdict.score is not None else "n/a"
            lines.append(
                f"- **{verdict.model_label}** — {verdict.verdict or 'no verdict'}, "
                f"score {model_score}, {verdict.finding_count} finding(s)"
            )
            if verdict.summary:
                lines.append(f"  - {verdict.summary}")
        lines.append("")

    disputed = result.disputed
    corroborated = [f for f in result.findings if f not in disputed]

    if corroborated:
        lines += ["## Findings", ""]
        lines += _finding_lines(corroborated)

    if disputed:
        lines += [
            "## Disputed findings",
            "",
            "Raised by a single model and not corroborated. These did not "
            "count towards the verdict.",
            "",
        ]
        lines += _finding_lines(disputed)

    if not result.findings:
        lines += ["## Findings", "", "None. Nothing was raised.", ""]

    return "\n".join(lines)


def _finding_lines(findings) -> list:
    lines = []
    for level in SEVERITY_ORDER:
        for finding in findings:
            if finding.severity != level:
                continue
            lines += [
                f"### [{level}] {finding.title}",
                "",
                f"- **Source:** {finding.source} · {finding.agreement.value} "
                f"· confidence {finding.confidence:.0%}",
            ]
            if finding.raised_by:
                lines.append(f"- **Raised by:** {', '.join(finding.raised_by)}")
            if finding.components:
                lines.append(f"- **Components:** {', '.join(finding.components)}")
            lines += ["", finding.detail, ""]
    return lines
