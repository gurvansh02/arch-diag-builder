"""Streamlit UI package - one module per page, plus shared styling."""

from ui.preview import diagram_png, show_preview, slugify
from ui.styles import inject_css, page_header, severity_badge, score_badge

__all__ = [
    "inject_css",
    "page_header",
    "severity_badge",
    "score_badge",
    "diagram_png",
    "show_preview",
    "slugify",
]
