"""
Render draw.io (mxGraph) XML to a PNG preview.

The app already stores diagrams as draw.io XML, but a user cannot tell whether
a diagram is any good without opening it in draw.io first. This renders the
same XML to an image so the diagram can be judged in place, before deciding to
download it.

It draws with Pillow only - no headless browser, no draw.io CLI, no network
call - so previews work in offline mode exactly as they do online. Only the
subset of mxGraph this app generates is supported: absolutely positioned
vertices, orthogonal edges, and the shapes in drawio_service.SHAPES. Anything
unrecognised falls back to a labelled rectangle, which is the right failure
mode for a preview.
"""

import io
import logging
import xml.sax.saxutils as saxutils
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

from lxml import etree

from services import icon_glyphs
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# Pixels per diagram unit in the returned image.
DEFAULT_SCALE = 2.0
# Everything is drawn at SUPERSAMPLE x the target size and then reduced, which
# is what gives the shapes and text smooth edges - Pillow has no anti-aliasing
# of its own.
SUPERSAMPLE = 2
# Guard against a pathological diagram allocating gigabytes.
MAX_PIXELS = 30_000_000

PADDING = 40
BACKGROUND = (255, 255, 255, 255)
DEFAULT_FILL = (255, 255, 255, 255)
DEFAULT_STROKE = (85, 85, 85, 255)
TEXT_COLOR = (35, 39, 47, 255)
EDGE_COLOR = (90, 98, 112, 255)

DEFAULT_FONT_SIZE = 12
LABEL_PADDING = 6

# Font files by weight, in preference order. truetype() resolves bare names
# against the OS font directories, so this covers Windows, most Linux images
# and macOS without hard-coded paths.
FONT_FILES = {
    False: ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Helvetica.ttc"),
    True: ("arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Helvetica.ttc"),
}

# Shape silhouettes built from overlapping ellipses, as fractions of the cell
# box. The union is filled and outlined in one pass (see _draw_blob).
CLOUD_ELLIPSES = (
    (0.00, 0.42, 0.44, 1.00),
    (0.16, 0.06, 0.64, 0.74),
    (0.46, 0.20, 0.94, 0.86),
    (0.56, 0.44, 1.00, 1.00),
    (0.22, 0.50, 0.80, 1.00),
)
# Head plus shoulders; the shoulders ellipse runs past the bottom of the box
# and is clipped there, which is what gives the actor its flat base.
ACTOR_ELLIPSES = (
    (0.28, 0.00, 0.72, 0.38),
    (0.00, 0.42, 1.00, 1.70),
)


@dataclass
class _Vertex:
    """One positioned node from the diagram."""
    cell_id: str
    x: float
    y: float
    width: float
    height: float
    label: str
    style: Dict[str, str] = field(default_factory=dict)

    @property
    def center(self) -> Tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


@dataclass
class _Edge:
    """One connection between two nodes."""
    source: str
    target: str
    label: str = ""


@dataclass
class _Route:
    """A planned connector: the corner points to draw, plus its caption."""
    points: List[Tuple[float, float]]
    label: str = ""


# Two anchors this close on the cross axis are treated as aligned, and the
# connector is drawn straight rather than with a barely visible jog.
ALIGNMENT_TOLERANCE = 20.0
# Share of a node's side that fanned-out connectors may spread across.
FAN_OUT_SPAN = 0.66
# Clearance kept between a connector and the nodes it is routed around.
OBSTACLE_MARGIN = 10.0
# How far a detour leaves a node before turning into a corridor.
STUB_LENGTH = 26.0

HORIZONTAL_SIDES = ("left", "right")


class DiagramRenderer:
    """Turns draw.io XML into a PNG."""

    def render_png(
        self,
        drawio_xml: str,
        scale: float = DEFAULT_SCALE,
        padding: int = PADDING,
    ) -> Optional[bytes]:
        """
        Render a diagram to PNG bytes.

        Returns None when the XML cannot be parsed or holds nothing to draw -
        callers fall back to offering the .drawio file on its own.
        """
        try:
            vertices, edges = self._parse(drawio_xml)
        except Exception as e:
            logger.warning("Could not parse diagram XML: %s", e)
            return None

        if not vertices:
            logger.info("Diagram has no drawable cells")
            return None

        try:
            return self._draw(vertices, edges, scale, padding)
        except Exception as e:
            logger.error("Could not render diagram: %s", e, exc_info=True)
            return None

    # ==================== Parsing ====================

    def _parse(self, drawio_xml: str) -> Tuple[List[_Vertex], List[_Edge]]:
        """Pull the vertices and edges out of an mxGraphModel."""
        # A stored file starts with an XML declaration when it came back from
        # disk as text, which lxml refuses on a str - encode first.
        root = etree.fromstring(drawio_xml.encode("utf-8"))

        vertices: List[_Vertex] = []
        edges: List[_Edge] = []

        for cell in root.iter("mxCell"):
            style = self._parse_style(cell.get("style") or "")
            label = self._plain_text(cell.get("value") or "")

            if cell.get("edge") == "1":
                source, target = cell.get("source"), cell.get("target")
                if source and target and source != target:
                    edges.append(_Edge(source=source, target=target, label=label))
                continue

            if cell.get("vertex") != "1":
                continue

            geometry = cell.find("mxGeometry")
            if geometry is None:
                continue

            vertices.append(
                _Vertex(
                    cell_id=cell.get("id") or "",
                    x=self._number(geometry.get("x")),
                    y=self._number(geometry.get("y")),
                    width=self._number(geometry.get("width"), 120),
                    height=self._number(geometry.get("height"), 60),
                    label=label,
                    style=style,
                )
            )

        return vertices, edges

    @staticmethod
    def _parse_style(style: str) -> Dict[str, str]:
        """Turn "rounded=1;fillColor=#FFF;" into a dict. Bare keys map to "1"."""
        parsed: Dict[str, str] = {}

        for token in style.split(";"):
            token = token.strip()
            if not token:
                continue
            key, separator, value = token.partition("=")
            parsed[key.strip()] = value.strip() if separator else "1"

        return parsed

    @staticmethod
    def _plain_text(value: str) -> str:
        """Flatten a draw.io label (which may carry HTML) to plain text."""
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return saxutils.unescape(text).strip()

    @staticmethod
    def _number(value: Optional[str], default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    # ==================== Drawing ====================

    def _draw(
        self,
        vertices: List[_Vertex],
        edges: List[_Edge],
        scale: float,
        padding: int,
    ) -> bytes:
        """Lay the diagram out on a canvas and encode it as PNG."""
        min_x = min(v.x for v in vertices)
        min_y = min(v.y for v in vertices)
        max_x = max(v.x + v.width for v in vertices)
        max_y = max(v.y + v.height for v in vertices)

        width = max_x - min_x + 2 * padding
        height = max_y - min_y + 2 * padding

        draw_scale = self._fit_scale(width, height, scale)
        canvas_size = (
            max(int(width * draw_scale), 1),
            max(int(height * draw_scale), 1),
        )

        origin = (padding - min_x, padding - min_y)
        image = Image.new("RGBA", canvas_size, BACKGROUND)
        canvas = ImageDraw.Draw(image)

        def to_device(x: float, y: float) -> Tuple[float, float]:
            return (x + origin[0]) * draw_scale, (y + origin[1]) * draw_scale

        by_id = {v.cell_id: v for v in vertices}
        routes = self._plan_routes(by_id, edges, vertices)

        # Lines first, so nodes sit on top of the connectors that meet them...
        for route in routes:
            self._draw_route(canvas, route, to_device, draw_scale)

        for vertex in vertices:
            self._draw_vertex(image, canvas, vertex, to_device, draw_scale)

        # ...but connector captions last, or a shape drawn afterwards clips
        # the text that describes the line running into it.
        for route in routes:
            if route.label:
                self._draw_edge_label(canvas, route, to_device, draw_scale)

        if SUPERSAMPLE > 1 and draw_scale > scale:
            target = (
                max(int(canvas_size[0] * scale / draw_scale), 1),
                max(int(canvas_size[1] * scale / draw_scale), 1),
            )
            image = image.resize(target, Image.LANCZOS)

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    @staticmethod
    def _fit_scale(width: float, height: float, scale: float) -> float:
        """Supersample unless that would make the canvas unreasonably large."""
        if width * height * (scale * SUPERSAMPLE) ** 2 <= MAX_PIXELS:
            return scale * SUPERSAMPLE
        return scale

    # ==================== Vertices ====================

    def _draw_vertex(self, image, canvas, vertex: _Vertex, to_device, scale: float) -> None:
        """Draw one node: its shape, then its label."""
        style = vertex.style
        left, top = to_device(vertex.x, vertex.y)
        right, bottom = to_device(vertex.x + vertex.width, vertex.y + vertex.height)
        box = (left, top, right, bottom)

        fill = self._color(style.get("fillColor"), DEFAULT_FILL)
        stroke = self._color(style.get("strokeColor"), DEFAULT_STROKE)
        stroke_width = max(int(self._number(style.get("strokeWidth"), 1) * scale), 1)
        shape = style.get("shape", "")

        # A text cell (the diagram title) has no shape of its own.
        if "text" in style and not shape:
            self._draw_label(canvas, box, vertex, scale, inside=True)
            return

        # A recognised cloud service. The .drawio file carries the real vendor
        # stencil, which Pillow cannot load, so draw the tile-and-glyph stand-in
        # that services/icon_glyphs.py provides.
        if shape.startswith("mxgraph.") or "adbGlyph" in style:
            self._draw_service_icon(canvas, box, vertex, scale)
            return

        if shape == "cylinder3":
            self._draw_cylinder(canvas, box, fill, stroke, stroke_width)
        elif shape == "process":
            self._draw_process(canvas, box, fill, stroke, stroke_width)
        elif shape == "cloud":
            self._draw_blob(image, box, CLOUD_ELLIPSES, fill, stroke, stroke_width)
        elif shape == "actor":
            self._draw_blob(image, box, ACTOR_ELLIPSES, fill, stroke, stroke_width)
            # An actor box is too narrow for its name; draw.io overlaps them,
            # which is unreadable at preview size, so it goes underneath.
            self._draw_label(canvas, box, vertex, scale, below=True)
            return
        elif style.get("rounded") == "1":
            radius = min((bottom - top) / 4, 12 * scale)
            canvas.rounded_rectangle(box, radius=radius, fill=fill,
                                     outline=stroke, width=stroke_width)
        else:
            canvas.rectangle(box, fill=fill, outline=stroke, width=stroke_width)

        self._draw_label(canvas, box, vertex, scale, inside=True)

    def _draw_service_icon(self, canvas, box, vertex: _Vertex, scale: float) -> None:
        """
        A cloud service: a coloured tile with a white glyph, name underneath.

        This is the preview's stand-in for the vendor stencil in the exported
        file. The tile is squared off inside the cell so a wide cell does not
        stretch the glyph, and the label sits below it the same way draw.io
        places it for AWS/Azure/GCP resource icons.
        """
        left, top, right, bottom = box
        style = vertex.style

        accent = self._color(style.get("adbAccent"), (90, 98, 112, 255))
        glyph = style.get("adbGlyph", "service")

        # Square the tile and centre it horizontally; the label needs the space
        # below, so the tile hugs the top of the cell.
        side = min(right - left, bottom - top)
        center_x = (left + right) / 2
        tile = (center_x - side / 2, top, center_x + side / 2, top + side)

        radius = max(side * 0.16, 1)
        canvas.rounded_rectangle(tile, radius=radius, fill=accent)

        # The glyph is drawn white on the accent tile, inset so it does not
        # touch the rounded corners.
        inset = side * 0.2
        inner = (tile[0] + inset, tile[1] + inset, tile[2] - inset, tile[3] - inset)
        weight = max(int(2.0 * scale), 1)

        if not icon_glyphs.paint(canvas, glyph, inner, (255, 255, 255, 255), weight):
            # No painter for this glyph - the tile plus the label still reads,
            # so fall back rather than leaving an empty square.
            icon_glyphs.paint(canvas, "service", inner, (255, 255, 255, 255), weight)

        # Anchored to the tile, not the cell, so the name sits directly under
        # the icon. _draw_label(below=True) wraps to 2.4x the anchor width,
        # which is what lets a long service name use the gap between columns.
        self._draw_label(canvas, tile, vertex, scale, below=True)

    def _draw_cylinder(self, canvas, box, fill, stroke, width) -> None:
        """A database: a rectangle capped with an ellipse at each end."""
        left, top, right, bottom = box
        cap = min((bottom - top) * 0.22, (right - left) * 0.35)

        canvas.ellipse((left, bottom - cap, right, bottom), fill=fill,
                       outline=stroke, width=width)
        canvas.rectangle((left, top + cap / 2, right, bottom - cap / 2), fill=fill)
        canvas.line((left, top + cap / 2, left, bottom - cap / 2), fill=stroke, width=width)
        canvas.line((right, top + cap / 2, right, bottom - cap / 2), fill=stroke, width=width)
        canvas.ellipse((left, top, right, top + cap), fill=fill,
                       outline=stroke, width=width)

    def _draw_process(self, canvas, box, fill, stroke, width) -> None:
        """A queue: a rectangle with an inner rule on each side."""
        left, top, right, bottom = box
        inset = (right - left) * 0.1

        canvas.rectangle(box, fill=fill, outline=stroke, width=width)
        canvas.line((left + inset, top, left + inset, bottom), fill=stroke, width=width)
        canvas.line((right - inset, top, right - inset, bottom), fill=stroke, width=width)

    def _draw_blob(self, image, box, ellipses: Sequence, fill, stroke, width) -> None:
        """
        Fill and outline the union of several ellipses (cloud, actor).

        Drawing the ellipses one by one would leave their overlapping arcs
        showing inside the shape. Instead the union is built as a mask, filled
        in one go, and its outline recovered with an edge filter so only the
        silhouette is stroked.
        """
        left, top, right, bottom = box
        box_width = max(int(right - left), 1)
        box_height = max(int(bottom - top), 1)

        # A margin keeps the edge filter from clipping the outline at the
        # mask border.
        margin = max(width * 2, 4)
        mask = Image.new("L", (box_width + margin * 2, box_height + margin * 2), 0)
        mask_draw = ImageDraw.Draw(mask)

        for x0, y0, x1, y1 in ellipses:
            mask_draw.ellipse(
                (
                    margin + x0 * box_width,
                    margin + y0 * box_height,
                    margin + x1 * box_width,
                    margin + y1 * box_height,
                ),
                fill=255,
            )

        # Clip to the cell box, so an ellipse that runs past it (the actor's
        # shoulders) ends in a flat edge instead of a bulge.
        clip = Image.new("L", mask.size, 0)
        ImageDraw.Draw(clip).rectangle(
            (margin, margin, margin + box_width, margin + box_height), fill=255
        )
        mask = Image.composite(mask, Image.new("L", mask.size, 0), clip)

        outline = mask.filter(ImageFilter.FIND_EDGES)
        if width > 1:
            outline = outline.filter(ImageFilter.MaxFilter(3 if width <= 3 else 5))

        position = (int(left) - margin, int(top) - margin)
        image.paste(Image.new("RGBA", mask.size, fill), position, mask)
        image.paste(Image.new("RGBA", mask.size, stroke), position, outline)

    # ==================== Labels ====================

    def _draw_label(
        self,
        canvas,
        box,
        vertex: _Vertex,
        scale: float,
        inside: bool = False,
        below: bool = False,
    ) -> None:
        """Draw a node's label, wrapped to the width of its shape."""
        if not vertex.label:
            return

        style = vertex.style
        size = max(int(self._number(style.get("fontSize"), DEFAULT_FONT_SIZE) * scale), 6)
        font = _font(size, bold=style.get("fontStyle") == "1")

        left, top, right, bottom = box
        pad = LABEL_PADDING * scale

        if below:
            # Actors are narrow; let the name use the space between columns.
            available = max((right - left) * 2.4, 80 * scale)
            center_x = (left + right) / 2
            lines = self._wrap(vertex.label, font, available)
            self._draw_lines(canvas, lines, font, center_x, bottom + pad, "center", "top")
            return

        available = (right - left) - 2 * pad
        lines = self._wrap(vertex.label, font, available)

        if style.get("align") == "left":
            self._draw_lines(canvas, lines, font, left, (top + bottom) / 2, "left", "middle")
        else:
            self._draw_lines(
                canvas, lines, font, (left + right) / 2, (top + bottom) / 2,
                "center", "middle",
            )

    def _draw_lines(self, canvas, lines, font, x, y, align, valign) -> None:
        """Draw wrapped text with the given anchor point."""
        if not lines:
            return

        line_height = font.size * 1.25
        block_height = line_height * len(lines)
        start_y = y - block_height / 2 if valign == "middle" else y

        for index, line in enumerate(lines):
            canvas.text(
                (x, start_y + index * line_height),
                line,
                font=font,
                fill=TEXT_COLOR,
                anchor="ma" if align == "center" else "la",
            )

    @staticmethod
    def _wrap(text: str, font, max_width: float) -> List[str]:
        """Greedy word wrap to a pixel width, keeping explicit line breaks."""
        lines: List[str] = []

        for paragraph in text.split("\n"):
            words = paragraph.split()
            if not words:
                continue

            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if font.getlength(candidate) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)

        return lines

    # ==================== Edges ====================

    def _plan_routes(
        self,
        by_id: Dict[str, _Vertex],
        edges: List[_Edge],
        vertices: List[_Vertex],
    ) -> List[_Route]:
        """
        Work out where every connector leaves, turns and arrives.

        Done for all edges at once because the anchor points depend on each
        other: several connectors meeting the same side of a node are fanned
        out along it, so a node with an inbound and an outbound edge on the
        same side does not end up with one line carrying two arrowheads.
        """
        plans = []

        for edge in edges:
            source, target = by_id.get(edge.source), by_id.get(edge.target)
            if not source or not target:
                continue

            sx, sy = source.center
            tx, ty = target.center

            if abs(tx - sx) >= abs(ty - sy):
                sides = ("right", "left") if tx >= sx else ("left", "right")
            else:
                sides = ("bottom", "top") if ty >= sy else ("top", "bottom")

            plans.append({"edge": edge, "source": source, "target": target,
                          "sides": sides})

        anchors = self._fan_out(plans)

        routes = []
        for index, plan in enumerate(plans):
            start = anchors[(index, "source")]
            end = anchors[(index, "target")]
            horizontal = plan["sides"][0] in HORIZONTAL_SIDES
            obstacles = self._obstacles(vertices, plan["source"], plan["target"])

            routes.append(
                _Route(
                    points=self._path(start, end, horizontal, obstacles),
                    label=plan["edge"].label,
                )
            )

        return routes

    @staticmethod
    def _obstacles(
        vertices: List[_Vertex], source: _Vertex, target: _Vertex
    ) -> List[Tuple[float, float, float, float]]:
        """Boxes a connector should avoid: every node except its own ends."""
        boxes = []

        for vertex in vertices:
            if vertex is source or vertex is target:
                continue
            # A title has no shape to collide with.
            if "text" in vertex.style and not vertex.style.get("shape"):
                continue
            boxes.append(
                (
                    vertex.x - OBSTACLE_MARGIN,
                    vertex.y - OBSTACLE_MARGIN,
                    vertex.x + vertex.width + OBSTACLE_MARGIN,
                    vertex.y + vertex.height + OBSTACLE_MARGIN,
                )
            )

        return boxes

    def _fan_out(self, plans: List[Dict]) -> Dict[Tuple[int, str], Tuple[float, float]]:
        """Spread the connectors that share a node side evenly along it."""
        buckets: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}

        for index, plan in enumerate(plans):
            for end, side in (("source", plan["sides"][0]), ("target", plan["sides"][1])):
                buckets.setdefault((plan[end].cell_id, side), []).append((index, end))

        anchors: Dict[Tuple[int, str], Tuple[float, float]] = {}

        for (_cell_id, side), members in buckets.items():
            node = plans[members[0][0]][members[0][1]]

            # Order by where the other end sits, so the connectors leaving one
            # side keep their relative order and do not cross each other.
            members.sort(key=lambda m: self._opposite_key(plans[m[0]], m[1], side))

            count = len(members)
            step = min(FAN_OUT_SPAN / count, 0.3) if count > 1 else 0.0

            for position, (index, end) in enumerate(members):
                offset = (position - (count - 1) / 2) * step
                anchors[(index, end)] = self._point_on_side(node, side, 0.5 + offset)

        self._straighten(plans, buckets, anchors)
        return anchors

    @staticmethod
    def _opposite_key(plan: Dict, end: str, side: str) -> float:
        """Position of the far end of a connector, along the fanned-out axis."""
        far = plan["target" if end == "source" else "source"]
        return far.center[1] if side in HORIZONTAL_SIDES else far.center[0]

    @staticmethod
    def _point_on_side(node: _Vertex, side: str, fraction: float) -> Tuple[float, float]:
        """A point on one side of a node, `fraction` of the way along it."""
        if side == "left":
            return node.x, node.y + node.height * fraction
        if side == "right":
            return node.x + node.width, node.y + node.height * fraction
        if side == "top":
            return node.x + node.width * fraction, node.y
        return node.x + node.width * fraction, node.y + node.height

    def _straighten(self, plans, buckets, anchors) -> None:
        """
        Pull nearly-aligned connectors into a straight line.

        Two nodes in the same row rarely have exactly the same centre - a
        cloud is taller than a service box - and the resulting 10px dog-leg
        looks like a mistake. Only connectors that are alone on both of their
        sides are moved, so this never undoes the fan-out above.
        """
        for index, plan in enumerate(plans):
            source_side, target_side = plan["sides"]

            alone = (
                len(buckets[(plan["source"].cell_id, source_side)]) == 1
                and len(buckets[(plan["target"].cell_id, target_side)]) == 1
            )
            if not alone:
                continue

            start = anchors[(index, "source")]
            end = anchors[(index, "target")]
            axis = 1 if source_side in HORIZONTAL_SIDES else 0

            if abs(start[axis] - end[axis]) > ALIGNMENT_TOLERANCE:
                continue

            shared = (start[axis] + end[axis]) / 2
            if not (
                self._within(plan["source"], axis, shared)
                and self._within(plan["target"], axis, shared)
            ):
                continue

            anchors[(index, "source")] = self._replace(start, axis, shared)
            anchors[(index, "target")] = self._replace(end, axis, shared)

    @staticmethod
    def _within(node: _Vertex, axis: int, value: float, margin: float = 6.0) -> bool:
        """True when a coordinate stays comfortably inside a node's span."""
        low = node.y + margin if axis else node.x + margin
        high = (node.y + node.height - margin) if axis else (node.x + node.width - margin)
        return low <= value <= high

    @staticmethod
    def _replace(point: Tuple[float, float], axis: int, value: float) -> Tuple[float, float]:
        return (point[0], value) if axis else (value, point[1])

    @staticmethod
    def _corner_points(start, end, horizontal: bool) -> List[Tuple[float, float]]:
        """Orthogonal path between two anchors: straight, or with one jog."""
        (sx, sy), (tx, ty) = start, end

        if horizontal:
            if abs(sy - ty) < 0.5:
                return [(sx, sy), (tx, ty)]
            middle = (sx + tx) / 2
            return [(sx, sy), (middle, sy), (middle, ty), (tx, ty)]

        if abs(sx - tx) < 0.5:
            return [(sx, sy), (tx, ty)]
        middle = (sy + ty) / 2
        return [(sx, sy), (sx, middle), (tx, middle), (tx, ty)]

    # ==================== Obstacle avoidance ====================

    def _path(self, start, end, horizontal: bool, obstacles) -> List[Tuple[float, float]]:
        """
        The route to draw: the direct one, or a detour around what blocks it.

        A one-turn route between distant nodes often crosses whatever sits
        between them. When it does, the connector is taken out of the node, along
        a clear corridor between the rows (or columns), and back in - which is
        what a person drawing the same diagram by hand would do.
        """
        direct = self._corner_points(start, end, horizontal)
        if self._is_clear(direct, obstacles):
            return direct

        for corridor in self._corridors(start, end, horizontal, obstacles):
            detour = self._detour_points(start, end, horizontal, corridor)
            if self._is_clear(detour, obstacles):
                return detour

        # Nothing clear: the direct route at least reads as a straight line.
        return direct

    @staticmethod
    def _detour_points(start, end, horizontal: bool, corridor: float):
        """Out of the node, along the corridor, and back in."""
        (sx, sy), (tx, ty) = start, end
        out = STUB_LENGTH if tx >= sx else -STUB_LENGTH
        down = STUB_LENGTH if ty >= sy else -STUB_LENGTH

        if horizontal:
            return [
                (sx, sy), (sx + out, sy), (sx + out, corridor),
                (tx - out, corridor), (tx - out, ty), (tx, ty),
            ]

        return [
            (sx, sy), (sx, sy + down), (corridor, sy + down),
            (corridor, ty - down), (tx, ty - down), (tx, ty),
        ]

    def _corridors(self, start, end, horizontal: bool, obstacles) -> List[float]:
        """
        Free lanes to route a detour along, nearest the direct path first.

        The lanes are the gaps between the obstacle boxes projected onto the
        cross axis - for a grid layout that is exactly the space between one
        row of components and the next.
        """
        axis = 1 if horizontal else 0
        spans = sorted((box[axis], box[axis + 2]) for box in obstacles)

        merged: List[List[float]] = []
        for low, high in spans:
            if merged and low <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], high)
            else:
                merged.append([low, high])

        ideal = (start[axis] + end[axis]) / 2
        candidates = []

        for before, after in zip(merged, merged[1:]):
            candidates.append((before[1] + after[0]) / 2)

        if merged:
            candidates.append(merged[0][0] - STUB_LENGTH)
            candidates.append(merged[-1][1] + STUB_LENGTH)

        return sorted(candidates, key=lambda value: abs(value - ideal))

    def _is_clear(self, points, obstacles) -> bool:
        """True when no segment of a path passes through an obstacle."""
        return all(
            not self._hits(first, second, box)
            for first, second in zip(points, points[1:])
            for box in obstacles
        )

    @staticmethod
    def _hits(first, second, box) -> bool:
        """Axis-aligned segment against a box."""
        left, top, right, bottom = box
        x_low, x_high = sorted((first[0], second[0]))
        y_low, y_high = sorted((first[1], second[1]))

        return x_low < right and x_high > left and y_low < bottom and y_high > top

    def _draw_route(self, canvas, route: _Route, to_device, scale: float) -> None:
        """Draw one planned connector with an arrowhead at the target."""
        device = [to_device(x, y) for x, y in route.points]
        width = max(int(1.6 * scale), 1)

        canvas.line(device, fill=EDGE_COLOR, width=width, joint="curve")
        self._draw_arrow_head(canvas, device[-2], device[-1], 7 * scale)

    @staticmethod
    def _draw_arrow_head(canvas, previous, tip, size: float) -> None:
        """Filled triangle pointing along the final segment."""
        px, py = previous
        tx, ty = tip

        if abs(tx - px) >= abs(ty - py):
            direction = 1 if tx >= px else -1
            points = [
                (tx, ty),
                (tx - direction * size, ty - size * 0.6),
                (tx - direction * size, ty + size * 0.6),
            ]
        else:
            direction = 1 if ty >= py else -1
            points = [
                (tx, ty),
                (tx - size * 0.6, ty - direction * size),
                (tx + size * 0.6, ty - direction * size),
            ]

        canvas.polygon(points, fill=EDGE_COLOR)

    def _draw_edge_label(self, canvas, route: _Route, to_device, scale: float) -> None:
        """Small caption at the half-way point of the connector."""
        font = _font(max(int(9 * scale), 6), bold=False)
        label = route.label

        center_x, center_y = to_device(*self._halfway(route.points))

        text_width = font.getlength(label)
        pad = 3 * scale
        canvas.rectangle(
            (
                center_x - text_width / 2 - pad,
                center_y - font.size / 2 - pad,
                center_x + text_width / 2 + pad,
                center_y + font.size / 2 + pad,
            ),
            fill=BACKGROUND,
        )
        canvas.text((center_x, center_y), label, font=font, fill=EDGE_COLOR, anchor="mm")

    @staticmethod
    def _halfway(points) -> Tuple[float, float]:
        """The point half way along a path, measured by length."""
        segments = [
            (first, second, abs(second[0] - first[0]) + abs(second[1] - first[1]))
            for first, second in zip(points, points[1:])
        ]
        target = sum(length for _f, _s, length in segments) / 2

        travelled = 0.0
        for first, second, length in segments:
            if travelled + length >= target and length:
                share = (target - travelled) / length
                return (
                    first[0] + (second[0] - first[0]) * share,
                    first[1] + (second[1] - first[1]) * share,
                )
            travelled += length

        return points[len(points) // 2]

    # ==================== Colours ====================

    @staticmethod
    def _color(value: Optional[str], default) -> Tuple[int, int, int, int]:
        """Parse a draw.io colour. "none" and anything unparseable go clear."""
        if not value:
            return default
        if value.lower() == "none":
            return (0, 0, 0, 0)

        text = value.lstrip("#")
        if len(text) == 3:
            text = "".join(character * 2 for character in text)
        if len(text) != 6:
            return default

        try:
            return (
                int(text[0:2], 16),
                int(text[2:4], 16),
                int(text[4:6], 16),
                255,
            )
        except ValueError:
            return default


@lru_cache(maxsize=64)
def _font(size: int, bold: bool):
    """Best available system font at this size, falling back to Pillow's own."""
    for name in FONT_FILES[bold]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue

    try:
        # Pillow >= 10.1 returns a scalable default; older versions ignore size.
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


diagram_renderer = DiagramRenderer()
