"""Draw.io XML generation service for creating diagrams"""

import logging
from typing import Dict, List

from lxml import etree

from services import cloud_icons

logger = logging.getLogger(__name__)


class DrawIOService:
    """Generates draw.io (mxGraph) XML from an architecture blueprint."""

    # Shape geometry and style per component type. Colours are applied
    # separately from the provider palette - baking them in here and then
    # appending a second fillColor produced duplicate keys and an invalid
    # 8-digit hex like "#FF990020", which draw.io renders as no fill.
    #
    # Kept for the generic fallback path only. Recognised cloud services get a
    # real vendor stencil from services/cloud_icons.py instead.
    SHAPES = {
        "service": ("rounded=1;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 60),
        "database": (
            "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;"
            "backgroundOutline=1;strokeWidth=2;",
            140,
            80,
        ),
        "container": ("rounded=0;whiteSpace=wrap;html=1;strokeWidth=2;", 180, 60),
        "queue": ("shape=process;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 60),
        "cdn": ("shape=cloud;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 90),
        "internet": ("shape=cloud;whiteSpace=wrap;html=1;strokeWidth=2;", 160, 90),
        "user": ("shape=actor;whiteSpace=wrap;html=1;strokeWidth=2;", 60, 80),
    }

    # Light fill + brand stroke per cloud provider.
    PALETTE = {
        "AWS": ("#FFF2E0", "#FF9900"),
        "Azure": ("#E5F1FB", "#0078D4"),
        "GCP": ("#E8F0FE", "#4285F4"),
    }
    DEFAULT_PALETTE = ("#F5F5F5", "#666666")

    # Layout grid. Vendor icons are square with the label underneath, so rows
    # need more vertical room than the old label-inside boxes did.
    COLUMNS = 4
    COL_WIDTH = 200
    ROW_HEIGHT = 160
    ORIGIN_X = 40
    ORIGIN_Y = 80

    def __init__(self):
        self.next_id = 1

    def _get_id(self) -> str:
        shape_id = f"node_{self.next_id}"
        self.next_id += 1
        return shape_id

    def create_infrastructure_diagram(
        self,
        project_name: str,
        components: List[Dict],
        connections: List[Dict],
        cloud_provider: str = "AWS",
    ) -> str:
        """Render an infrastructure blueprint as draw.io XML."""
        try:
            self.next_id = 1

            root = etree.Element("mxfile")
            root.set("host", "app.diagrams.net")
            root.set("type", "device")

            diagram = etree.SubElement(root, "diagram")
            diagram.set("name", project_name or "Architecture")
            diagram.set("id", "architecture")

            graph = etree.SubElement(diagram, "mxGraphModel")
            for key, value in (
                ("dx", "1400"), ("dy", "900"), ("grid", "1"), ("gridSize", "10"),
                ("guides", "1"), ("tooltips", "1"), ("connect", "1"),
                ("arrows", "1"), ("fold", "1"), ("page", "1"),
                ("pageWidth", "1169"), ("pageHeight", "826"),
            ):
                graph.set(key, value)

            cells = etree.SubElement(graph, "root")

            base = etree.SubElement(cells, "mxCell")
            base.set("id", "0")

            layer = etree.SubElement(cells, "mxCell")
            layer.set("id", "1")
            layer.set("parent", "0")

            self._add_title(cells, project_name)

            # name -> cell id, so connections can be resolved by name.
            node_ids: Dict[str, str] = {}

            for index, component in enumerate(components):
                name = str(component.get("name") or f"Component {index + 1}")

                x = self.ORIGIN_X + (index % self.COLUMNS) * self.COL_WIDTH
                y = self.ORIGIN_Y + (index // self.COLUMNS) * self.ROW_HEIGHT

                shape_id = self._add_component(
                    cells,
                    name=name,
                    component_type=str(component.get("type") or "service").lower(),
                    x=x,
                    y=y,
                    cloud_provider=cloud_provider,
                    service=component.get("service"),
                )

                # First occurrence wins if the model repeats a name.
                node_ids.setdefault(name, shape_id)

            for connection in connections:
                source = node_ids.get(str(connection.get("from")))
                target = node_ids.get(str(connection.get("to")))

                if source and target:
                    self._add_connector(
                        cells, source, target, str(connection.get("type") or "")
                    )
                else:
                    logger.debug(
                        "Skipping connection with unknown endpoint: %s -> %s",
                        connection.get("from"),
                        connection.get("to"),
                    )

            return etree.tostring(root, pretty_print=True, encoding="unicode")

        except Exception as e:
            logger.error("Error creating diagram: %s", e, exc_info=True)
            return self._create_minimal_diagram(project_name)

    def _add_component(
        self,
        parent: etree._Element,
        name: str,
        component_type: str,
        x: int,
        y: int,
        cloud_provider: str,
        service: str = None,
    ) -> str:
        """Add one component node and return its cell id."""
        shape_id = self._get_id()

        spec = cloud_icons.resolve(
            name=name,
            component_type=component_type,
            provider=cloud_provider,
            service=service,
        )

        if cloud_icons.is_vendor_icon(spec):
            # The stencil carries its own colours and puts the label below the
            # icon, so the provider palette must not be appended here - a second
            # fillColor would override the vendor's.
            style = spec.stencil
            width, height = spec.width, spec.height

            # The PNG preview draws with Pillow and cannot load an mxGraph
            # stencil, so record which glyph stands in for it. draw.io ignores
            # style keys it does not know, so this rides along harmlessly.
            #
            # Only vendor icons get this. A person, the public internet or an
            # unrecognised component keeps its classic silhouette in both the
            # preview and the file, which is what visually separates "a cloud
            # service" from everything else.
            style += f"adbGlyph={spec.glyph};adbAccent={spec.accent};"
        else:
            shape_style, width, height = self.SHAPES.get(
                component_type, self.SHAPES["service"]
            )
            fill, stroke = self.PALETTE.get(cloud_provider, self.DEFAULT_PALETTE)
            style = f"{shape_style}fillColor={fill};strokeColor={stroke};"

        cell = etree.SubElement(parent, "mxCell")
        cell.set("id", shape_id)
        cell.set("value", name)
        cell.set("style", style)
        cell.set("parent", "1")
        cell.set("vertex", "1")

        geometry = etree.SubElement(cell, "mxGeometry")
        geometry.set("x", str(x))
        geometry.set("y", str(y))
        geometry.set("width", str(width))
        geometry.set("height", str(height))
        geometry.set("as", "geometry")

        return shape_id

    def _add_connector(
        self, parent: etree._Element, source_id: str, target_id: str, label: str = ""
    ) -> None:
        """Add a directed edge between two components."""
        cell = etree.SubElement(parent, "mxCell")
        cell.set("id", self._get_id())
        cell.set("value", label)
        cell.set(
            "style",
            "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;jettySize=auto;"
            "orthogonalLoop=1;endArrow=blockThin;endFill=1;fontSize=10;",
        )
        cell.set("parent", "1")
        cell.set("source", source_id)
        cell.set("target", target_id)
        cell.set("edge", "1")

        geometry = etree.SubElement(cell, "mxGeometry")
        geometry.set("relative", "1")
        geometry.set("as", "geometry")

    def _add_title(self, parent: etree._Element, title: str) -> None:
        """Add the diagram title as a text cell."""
        cell = etree.SubElement(parent, "mxCell")
        cell.set("id", self._get_id())
        cell.set("value", title or "Architecture")
        cell.set(
            "style",
            "text;html=1;strokeColor=none;fillColor=none;align=left;"
            "verticalAlign=middle;whiteSpace=wrap;fontSize=16;fontStyle=1;",
        )
        cell.set("parent", "1")
        cell.set("vertex", "1")

        geometry = etree.SubElement(cell, "mxGeometry")
        geometry.set("x", str(self.ORIGIN_X))
        geometry.set("y", "20")
        geometry.set("width", "700")
        geometry.set("height", "30")
        geometry.set("as", "geometry")

    def _create_minimal_diagram(self, project_name: str) -> str:
        """Empty but valid draw.io file, used if rendering fails."""
        root = etree.Element("mxfile")
        root.set("host", "app.diagrams.net")

        diagram = etree.SubElement(root, "diagram")
        diagram.set("name", project_name or "Architecture")
        diagram.set("id", "architecture")

        graph = etree.SubElement(diagram, "mxGraphModel")
        cells = etree.SubElement(graph, "root")

        base = etree.SubElement(cells, "mxCell")
        base.set("id", "0")

        layer = etree.SubElement(cells, "mxCell")
        layer.set("id", "1")
        layer.set("parent", "0")

        return etree.tostring(root, pretty_print=True, encoding="unicode")


drawio_service = DrawIOService()
