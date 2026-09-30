"""My Diagrams page - the user's generated diagram library, with previews."""

import streamlit as st

from storage import diagram_store
from ui.preview import show_preview, slugify
from ui.styles import page_header


def render() -> None:
    """Draw the diagram library."""
    page_header(
        "📊",
        "My diagrams",
        "Every diagram you have generated, rendered as an image. Download the "
        "PNG to share it, or the .drawio file to edit it at app.diagrams.net.",
    )

    diagrams = diagram_store.get_user_diagrams(st.session_state.user_id)

    if not diagrams:
        st.info("No diagrams yet. Describe an architecture on the Design page to create one.")
        return

    diagrams = _filter_bar(diagrams)
    if diagrams is None:
        return

    st.markdown("---")

    for diagram in diagrams:
        _diagram_card(diagram)


# ==================== Controls ====================

def _filter_bar(diagrams):
    """Search box and the previews toggle. Returns the diagrams to show."""
    search, previews = st.columns([3, 1])

    with search:
        query = st.text_input(
            "Search",
            placeholder="Filter by description, cloud or tag…",
            label_visibility="collapsed",
        )

    with previews:
        # Each preview is drawn once and then cached, but a large library
        # still costs a second or two on the first visit - so it can be off.
        st.session_state.show_previews = st.toggle(
            "Previews", value=st.session_state.get("show_previews", True)
        )

    if not query:
        st.caption(f"{len(diagrams)} saved")
        return diagrams

    matches = diagram_store.search_diagrams(st.session_state.user_id, query)
    if not matches:
        st.warning(f"No diagrams match “{query}”.")
        return None

    st.caption(f"{len(matches)} of {len(diagrams)} match “{query}”")
    return matches


# ==================== One diagram ====================

def _diagram_card(diagram) -> None:
    """Preview, metadata and the download / delete actions for one diagram."""
    st.markdown(f"**{diagram.project_description[:120]}**")

    meta = f"{diagram.diagram_type} · {diagram.created_at:%Y-%m-%d %H:%M}"
    if diagram.cloud_providers:
        meta += " · " + ", ".join(diagram.cloud_providers)
    st.caption(meta)

    png = None
    if st.session_state.get("show_previews", True):
        png = show_preview(diagram.drawio_xml)

    _actions(diagram, png)

    with st.expander("View draw.io XML"):
        st.code(diagram.drawio_xml, language="xml")

    st.divider()


def _actions(diagram, png) -> None:
    """Download buttons and delete, under the preview."""
    stem = f"{slugify(diagram.project_description)}-{diagram.diagram_id[:8]}"
    image, drawio, delete, _spacer = st.columns([1, 1, 1, 3])

    with image:
        if png:
            st.download_button(
                "🖼️ PNG",
                png,
                file_name=f"{stem}.png",
                mime="image/png",
                key=f"png_{diagram.diagram_id}",
                use_container_width=True,
            )
        else:
            # Previews are off, or this diagram could not be rendered.
            st.button(
                "🖼️ PNG",
                key=f"png_off_{diagram.diagram_id}",
                disabled=True,
                help="Turn previews on to download the image.",
                use_container_width=True,
            )

    with drawio:
        # Rendered directly rather than behind an st.button branch - nesting
        # it made the button vanish on the next rerun.
        st.download_button(
            "📥 .drawio",
            diagram.drawio_xml,
            file_name=f"{stem}.drawio",
            mime="application/xml",
            key=f"dl_{diagram.diagram_id}",
            use_container_width=True,
        )

    with delete:
        if st.button("🗑️ Delete", key=f"del_{diagram.diagram_id}", use_container_width=True):
            diagram_store.delete_diagram(st.session_state.user_id, diagram.diagram_id)
            st.rerun()
