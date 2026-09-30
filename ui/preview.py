"""
Shared diagram preview helpers.

Rendering is cached on the XML itself, so a diagram is drawn once per process
however many times the page reruns - Streamlit reruns the whole script on
every click, and re-rendering a gallery each time would be visibly slow.
"""

import re
from typing import Optional

import streamlit as st

from services import diagram_renderer

# Pixels per diagram unit. Enough to stay sharp on a high-density screen
# without making the gallery slow to draw.
PREVIEW_SCALE = 1.6


@st.cache_data(show_spinner=False, max_entries=64)
def diagram_png(drawio_xml: str, scale: float = PREVIEW_SCALE) -> Optional[bytes]:
    """PNG bytes for a draw.io diagram, or None if it could not be rendered."""
    return diagram_renderer.render_png(drawio_xml, scale=scale)


def show_preview(drawio_xml: str, caption: Optional[str] = None) -> Optional[bytes]:
    """Render a diagram inline and return its PNG bytes for downloading."""
    png = diagram_png(drawio_xml)

    if png:
        st.image(png, use_container_width=True, caption=caption)
    else:
        st.info(
            "This diagram could not be previewed. Download the .drawio file and "
            "open it at app.diagrams.net."
        )

    return png


def slugify(text: str, fallback: str = "diagram", limit: int = 40) -> str:
    """A filename-safe stem taken from the diagram's description."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:limit].strip("-") or fallback
