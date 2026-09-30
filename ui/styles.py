"""
Shared styling and small render helpers.

Streamlit here is 1.32, so anything newer than that (st.badge, st.popover,
st.segmented_control) is deliberately avoided - the badges below are plain
markdown spans instead.
"""

import streamlit as st

# The sidebar defaults to ~21rem, which crowds the diagram content on a
# laptop screen. The nav is short, so a fixed narrow rail is enough.
SIDEBAR_WIDTH_PX = 200

SEVERITY_COLORS = {
    "Critical": ("#7f1d1d", "#fee2e2"),
    "High": ("#9a3412", "#ffedd5"),
    "Medium": ("#854d0e", "#fef9c3"),
    "Low": ("#1e40af", "#dbeafe"),
}

CATEGORY_ICONS = {
    "Security": "🔒",
    "Cost Optimization": "💰",
    "Performance": "⚡",
    "Scalability": "📈",
    "Compliance": "📋",
    "Architecture": "🏗️",
}


def inject_css() -> None:
    """Apply the app-wide stylesheet. Call once per script run."""
    st.markdown(
        f"""
        <style>
        /* ---------- Narrow sidebar rail ---------- */
        section[data-testid="stSidebar"] {{
            width: {SIDEBAR_WIDTH_PX}px !important;
            min-width: {SIDEBAR_WIDTH_PX}px !important;
            max-width: {SIDEBAR_WIDTH_PX}px !important;
            background-color: #f7f9fc;
            border-right: 1px solid #e5e9f0;
        }}
        section[data-testid="stSidebar"] > div:first-child {{
            width: {SIDEBAR_WIDTH_PX}px !important;
            padding-top: 1.1rem;
        }}
        section[data-testid="stSidebar"] .block-container {{
            padding: 0.75rem 0.6rem;
        }}
        /* Compact nav buttons */
        section[data-testid="stSidebar"] .stButton > button {{
            text-align: left;
            justify-content: flex-start;
            padding: 0.3rem 0.55rem;
            font-size: 0.86rem;
            font-weight: 500;
            border-radius: 6px;
            min-height: 0;
        }}
        section[data-testid="stSidebar"] hr {{
            margin: 0.6rem 0;
        }}
        section[data-testid="stSidebar"] p {{
            font-size: 0.82rem;
            margin-bottom: 0.2rem;
        }}

        /* ---------- Main area ---------- */
        .main .block-container {{
            padding-top: 2.2rem;
            padding-bottom: 3rem;
            max-width: 1250px;
        }}

        /* ---------- Page header ---------- */
        .adb-header {{
            display: flex;
            align-items: baseline;
            gap: 0.7rem;
            margin-bottom: 0.15rem;
        }}
        .adb-header h1 {{
            font-size: 1.65rem;
            font-weight: 700;
            margin: 0;
            padding: 0;
        }}
        .adb-subtitle {{
            color: #64748b;
            font-size: 0.9rem;
            margin: 0 0 1.1rem 0;
        }}

        /* ---------- Badges ---------- */
        .adb-badge {{
            display: inline-block;
            padding: 0.1rem 0.5rem;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.02em;
            text-transform: uppercase;
        }}
        .adb-pill {{
            display: inline-block;
            padding: 0.12rem 0.55rem;
            margin-right: 0.3rem;
            border-radius: 6px;
            background: #eef2f7;
            color: #475569;
            font-size: 0.75rem;
        }}

        /* ---------- Cards ---------- */
        .adb-card {{
            border: 1px solid #e5e9f0;
            border-radius: 10px;
            padding: 0.85rem 1rem;
            margin-bottom: 0.65rem;
            background: #ffffff;
        }}
        .adb-card h4 {{
            margin: 0 0 0.25rem 0;
            font-size: 0.98rem;
        }}
        .adb-muted {{
            color: #64748b;
            font-size: 0.82rem;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(icon: str, title: str, subtitle: str = "") -> None:
    """Consistent page title block."""
    st.markdown(
        f'<div class="adb-header"><h1>{icon} {title}</h1></div>'
        f'<p class="adb-subtitle">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def severity_badge(severity: str) -> str:
    """Coloured pill for a review severity, as an HTML string."""
    text_color, background = SEVERITY_COLORS.get(severity, ("#334155", "#e2e8f0"))
    return (
        f'<span class="adb-badge" style="color:{text_color};'
        f'background:{background}">{severity}</span>'
    )


def score_badge(score) -> str:
    """Coloured pill for an overall review score."""
    if score is None:
        return '<span class="adb-badge" style="color:#334155;background:#e2e8f0">No score</span>'

    if score >= 80:
        text_color, background = "#14532d", "#dcfce7"
    elif score >= 60:
        text_color, background = "#854d0e", "#fef9c3"
    else:
        text_color, background = "#7f1d1d", "#fee2e2"

    return (
        f'<span class="adb-badge" style="color:{text_color};'
        f'background:{background}">{score:.0f} / 100</span>'
    )
