"""
Simplified service glyphs for the PNG preview.

services/diagram_renderer.py draws with Pillow only - no headless browser and
no network - so it cannot load the mxGraph stencils that carry the real vendor
icons in the exported .drawio file. These painters stand in for them: each one
draws a recognisable silhouette for a class of service (a bucket for object
storage, a cylinder for a database, a funnel for a load balancer) inside a
square tile.

The aim is not to reproduce the vendor artwork. It is that someone reading the
preview can tell a queue from a database from a CDN at a glance, and that the
preview and the downloaded file agree about what each node is.

Every painter takes the same arguments:
    canvas : PIL.ImageDraw.ImageDraw
    box    : (x0, y0, x1, y1) square region to draw inside
    color  : RGBA tuple for the strokes and fills
    weight : stroke width in pixels, already scaled
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, Tuple

logger = logging.getLogger(__name__)

Box = Tuple[float, float, float, float]


def _unit(box: Box):
    """Return a mapper from 0..1 coordinates to device pixels within `box`."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0

    def point(u: float, v: float) -> Tuple[float, float]:
        return x0 + u * width, y0 + v * height

    return point


def _rect(canvas, box: Box, u0, v0, u1, v1, color, weight, fill=None, radius=0):
    point = _unit(box)
    a, b = point(u0, v0)
    c, d = point(u1, v1)
    if radius:
        canvas.rounded_rectangle((a, b, c, d), radius=radius, outline=color,
                                 width=weight, fill=fill)
    else:
        canvas.rectangle((a, b, c, d), outline=color, width=weight, fill=fill)


def _line(canvas, box: Box, u0, v0, u1, v1, color, weight):
    point = _unit(box)
    canvas.line((*point(u0, v0), *point(u1, v1)), fill=color, width=weight)


def _ellipse(canvas, box: Box, u0, v0, u1, v1, color, weight, fill=None):
    point = _unit(box)
    a, b = point(u0, v0)
    c, d = point(u1, v1)
    canvas.ellipse((a, b, c, d), outline=color, width=weight, fill=fill)


def _poly(canvas, box: Box, points, color, weight, fill=None):
    point = _unit(box)
    device = [point(u, v) for u, v in points]
    canvas.polygon(device, outline=color, width=weight, fill=fill)


# ==================== Compute ====================

def _compute(canvas, box, color, weight):
    """A chip: square body with pins on each side."""
    _rect(canvas, box, 0.24, 0.24, 0.76, 0.76, color, weight)
    _rect(canvas, box, 0.40, 0.40, 0.60, 0.60, color, weight, fill=color)
    for offset in (0.36, 0.50, 0.64):
        _line(canvas, box, offset, 0.12, offset, 0.24, color, weight)
        _line(canvas, box, offset, 0.76, offset, 0.88, color, weight)
        _line(canvas, box, 0.12, offset, 0.24, offset, color, weight)
        _line(canvas, box, 0.76, offset, 0.88, offset, color, weight)


def _function(canvas, box, color, weight):
    """A lambda-ish bolt: the serverless shorthand."""
    _poly(canvas, box, [
        (0.56, 0.10), (0.26, 0.56), (0.46, 0.56),
        (0.40, 0.90), (0.74, 0.42), (0.52, 0.42),
    ], color, weight, fill=color)


def _container(canvas, box, color, weight):
    """Stacked boxes: a container or a group of them."""
    _rect(canvas, box, 0.14, 0.30, 0.52, 0.58, color, weight)
    _rect(canvas, box, 0.54, 0.30, 0.86, 0.58, color, weight)
    _rect(canvas, box, 0.14, 0.60, 0.52, 0.86, color, weight)
    _rect(canvas, box, 0.54, 0.60, 0.86, 0.86, color, weight)
    _line(canvas, box, 0.14, 0.22, 0.86, 0.22, color, weight)


def _kubernetes(canvas, box, color, weight):
    """A heptagon-ish wheel with spokes."""
    _poly(canvas, box, [
        (0.50, 0.10), (0.82, 0.28), (0.90, 0.62),
        (0.68, 0.88), (0.32, 0.88), (0.10, 0.62), (0.18, 0.28),
    ], color, weight)
    _ellipse(canvas, box, 0.40, 0.40, 0.60, 0.60, color, weight)
    for u, v in ((0.50, 0.10), (0.90, 0.62), (0.10, 0.62)):
        _line(canvas, box, 0.50, 0.50, u, v, color, weight)


def _batch(canvas, box, color, weight):
    """A queue of jobs feeding a worker."""
    for index, top in enumerate((0.22, 0.44, 0.66)):
        _rect(canvas, box, 0.14, top, 0.52, top + 0.14, color, weight,
              fill=color if index == 0 else None)
    _rect(canvas, box, 0.62, 0.38, 0.88, 0.64, color, weight)


# ==================== Storage ====================

def _storage(canvas, box, color, weight):
    """A bucket: tapered body with a rim."""
    _poly(canvas, box, [
        (0.20, 0.30), (0.80, 0.30), (0.70, 0.86), (0.30, 0.86),
    ], color, weight)
    _ellipse(canvas, box, 0.20, 0.20, 0.80, 0.40, color, weight)


def _filestore(canvas, box, color, weight):
    """A document with a folded corner."""
    _poly(canvas, box, [
        (0.26, 0.12), (0.62, 0.12), (0.76, 0.28), (0.76, 0.88), (0.26, 0.88),
    ], color, weight)
    _poly(canvas, box, [(0.62, 0.12), (0.62, 0.28), (0.76, 0.28)], color, weight)
    for v in (0.46, 0.60, 0.74):
        _line(canvas, box, 0.36, v, 0.66, v, color, weight)


def _archive(canvas, box, color, weight):
    """A crate with a latch: cold storage."""
    _rect(canvas, box, 0.16, 0.24, 0.84, 0.40, color, weight, fill=color)
    _rect(canvas, box, 0.16, 0.40, 0.84, 0.84, color, weight)
    _rect(canvas, box, 0.42, 0.52, 0.58, 0.64, color, weight)


# ==================== Data ====================

def _database(canvas, box, color, weight):
    """The classic cylinder."""
    _ellipse(canvas, box, 0.20, 0.16, 0.80, 0.34, color, weight)
    _line(canvas, box, 0.20, 0.25, 0.20, 0.75, color, weight)
    _line(canvas, box, 0.80, 0.25, 0.80, 0.75, color, weight)
    _ellipse(canvas, box, 0.20, 0.44, 0.80, 0.62, color, weight)
    _ellipse(canvas, box, 0.20, 0.66, 0.80, 0.84, color, weight)


def _nosql(canvas, box, color, weight):
    """A document store: overlapping rounded cards."""
    _rect(canvas, box, 0.18, 0.20, 0.66, 0.68, color, weight, radius=weight * 2)
    _rect(canvas, box, 0.34, 0.36, 0.82, 0.84, color, weight, radius=weight * 2)


def _cache(canvas, box, color, weight):
    """A bolt inside a store: fast access."""
    _ellipse(canvas, box, 0.18, 0.16, 0.82, 0.34, color, weight)
    _line(canvas, box, 0.18, 0.25, 0.18, 0.78, color, weight)
    _line(canvas, box, 0.82, 0.25, 0.82, 0.78, color, weight)
    _ellipse(canvas, box, 0.18, 0.70, 0.82, 0.88, color, weight)
    _poly(canvas, box, [
        (0.56, 0.32), (0.38, 0.56), (0.50, 0.56), (0.44, 0.76),
        (0.64, 0.50), (0.52, 0.50),
    ], color, weight, fill=color)


def _warehouse(canvas, box, color, weight):
    """Bar chart on a slab: analytics."""
    _rect(canvas, box, 0.14, 0.76, 0.86, 0.88, color, weight, fill=color)
    _rect(canvas, box, 0.22, 0.46, 0.36, 0.76, color, weight)
    _rect(canvas, box, 0.43, 0.24, 0.57, 0.76, color, weight)
    _rect(canvas, box, 0.64, 0.38, 0.78, 0.76, color, weight)


# ==================== Network ====================

def _cdn(canvas, box, color, weight):
    """A globe: edge locations."""
    _ellipse(canvas, box, 0.14, 0.14, 0.86, 0.86, color, weight)
    _ellipse(canvas, box, 0.38, 0.14, 0.62, 0.86, color, weight)
    _line(canvas, box, 0.14, 0.50, 0.86, 0.50, color, weight)
    _line(canvas, box, 0.20, 0.30, 0.80, 0.30, color, weight)
    _line(canvas, box, 0.20, 0.70, 0.80, 0.70, color, weight)


def _loadbalancer(canvas, box, color, weight):
    """One inbound arrow fanning out to three targets."""
    _line(canvas, box, 0.50, 0.10, 0.50, 0.38, color, weight)
    _line(canvas, box, 0.18, 0.38, 0.82, 0.38, color, weight)
    for u in (0.18, 0.50, 0.82):
        _line(canvas, box, u, 0.38, u, 0.62, color, weight)
        _rect(canvas, box, u - 0.12, 0.62, u + 0.12, 0.86, color, weight)


def _dns(canvas, box, color, weight):
    """A globe with a pointer: name resolution."""
    _ellipse(canvas, box, 0.16, 0.16, 0.74, 0.74, color, weight)
    _line(canvas, box, 0.16, 0.45, 0.74, 0.45, color, weight)
    _ellipse(canvas, box, 0.36, 0.16, 0.54, 0.74, color, weight)
    _poly(canvas, box, [(0.62, 0.62), (0.90, 0.74), (0.74, 0.90)], color, weight, fill=color)


def _gateway(canvas, box, color, weight):
    """A doorway with traffic passing through."""
    _poly(canvas, box, [
        (0.28, 0.86), (0.28, 0.34), (0.50, 0.16), (0.72, 0.34), (0.72, 0.86),
    ], color, weight)
    _line(canvas, box, 0.10, 0.58, 0.28, 0.58, color, weight)
    _line(canvas, box, 0.72, 0.58, 0.90, 0.58, color, weight)
    _ellipse(canvas, box, 0.44, 0.52, 0.56, 0.64, color, weight, fill=color)


def _network(canvas, box, color, weight):
    """A bounded region with nodes inside: a VPC."""
    _rect(canvas, box, 0.12, 0.18, 0.88, 0.82, color, weight, radius=weight * 2)
    for u, v in ((0.30, 0.38), (0.70, 0.38), (0.50, 0.66)):
        _ellipse(canvas, box, u - 0.08, v - 0.08, u + 0.08, v + 0.08, color, weight, fill=color)
    _line(canvas, box, 0.30, 0.38, 0.70, 0.38, color, weight)
    _line(canvas, box, 0.30, 0.38, 0.50, 0.66, color, weight)
    _line(canvas, box, 0.70, 0.38, 0.50, 0.66, color, weight)


# ==================== Integration ====================

def _queue(canvas, box, color, weight):
    """Messages lined up, oldest leaving on the right."""
    _rect(canvas, box, 0.10, 0.34, 0.90, 0.66, color, weight)
    for u in (0.28, 0.46, 0.64):
        _line(canvas, box, u, 0.34, u, 0.66, color, weight)
    _poly(canvas, box, [(0.68, 0.42), (0.86, 0.50), (0.68, 0.58)], color, weight, fill=color)


def _topic(canvas, box, color, weight):
    """One publisher broadcasting to many: pub/sub."""
    _ellipse(canvas, box, 0.36, 0.10, 0.64, 0.38, color, weight, fill=color)
    for u in (0.16, 0.50, 0.84):
        _line(canvas, box, 0.50, 0.38, u, 0.64, color, weight)
        _ellipse(canvas, box, u - 0.10, 0.64, u + 0.10, 0.86, color, weight)


def _events(canvas, box, color, weight):
    """A bus line with events attached."""
    _rect(canvas, box, 0.10, 0.44, 0.90, 0.58, color, weight, fill=color)
    for u in (0.24, 0.50, 0.76):
        _line(canvas, box, u, 0.20, u, 0.44, color, weight)
        _ellipse(canvas, box, u - 0.09, 0.08, u + 0.09, 0.26, color, weight)


def _stream(canvas, box, color, weight):
    """Parallel shards flowing left to right."""
    for v in (0.28, 0.48, 0.68):
        _line(canvas, box, 0.12, v, 0.74, v, color, weight)
        _poly(canvas, box, [(0.74, v - 0.07), (0.90, v), (0.74, v + 0.07)],
              color, weight, fill=color)


def _workflow(canvas, box, color, weight):
    """Sequenced steps with a branch: a state machine."""
    _rect(canvas, box, 0.36, 0.08, 0.64, 0.28, color, weight, radius=weight * 2)
    _line(canvas, box, 0.50, 0.28, 0.50, 0.40, color, weight)
    _poly(canvas, box, [(0.50, 0.40), (0.68, 0.54), (0.50, 0.68), (0.32, 0.54)],
          color, weight)
    _line(canvas, box, 0.50, 0.68, 0.50, 0.80, color, weight)
    _rect(canvas, box, 0.36, 0.80, 0.64, 0.94, color, weight, radius=weight * 2)


# ==================== Operations ====================

def _monitor(canvas, box, color, weight):
    """A trace on a screen."""
    _rect(canvas, box, 0.12, 0.20, 0.88, 0.70, color, weight, radius=weight * 2)
    _line(canvas, box, 0.50, 0.70, 0.50, 0.82, color, weight)
    _line(canvas, box, 0.30, 0.82, 0.70, 0.82, color, weight)
    point = _unit(box)
    trace = [(0.20, 0.56), (0.32, 0.56), (0.40, 0.36), (0.50, 0.60),
             (0.60, 0.44), (0.68, 0.52), (0.80, 0.52)]
    canvas.line([point(u, v) for u, v in trace], fill=color, width=weight, joint="curve")


def _identity(canvas, box, color, weight):
    """A person on a badge."""
    _rect(canvas, box, 0.18, 0.12, 0.82, 0.88, color, weight, radius=weight * 2)
    _ellipse(canvas, box, 0.40, 0.28, 0.60, 0.48, color, weight, fill=color)
    _poly(canvas, box, [(0.30, 0.76), (0.34, 0.58), (0.66, 0.58), (0.70, 0.76)],
          color, weight)


def _firewall(canvas, box, color, weight):
    """A brick wall: filtering at the edge."""
    _rect(canvas, box, 0.10, 0.24, 0.90, 0.80, color, weight)
    _line(canvas, box, 0.10, 0.42, 0.90, 0.42, color, weight)
    _line(canvas, box, 0.10, 0.61, 0.90, 0.61, color, weight)
    _line(canvas, box, 0.36, 0.24, 0.36, 0.42, color, weight)
    _line(canvas, box, 0.64, 0.24, 0.64, 0.42, color, weight)
    _line(canvas, box, 0.50, 0.42, 0.50, 0.61, color, weight)
    _line(canvas, box, 0.24, 0.61, 0.24, 0.80, color, weight)
    _line(canvas, box, 0.76, 0.61, 0.76, 0.80, color, weight)


def _secret(canvas, box, color, weight):
    """A padlock."""
    _rect(canvas, box, 0.24, 0.46, 0.76, 0.86, color, weight, radius=weight * 2)
    point = _unit(box)
    a, b = point(0.34, 0.20)
    c, d = point(0.66, 0.60)
    canvas.arc((a, b, c, d), start=180, end=360, fill=color, width=weight)
    _line(canvas, box, 0.34, 0.40, 0.34, 0.46, color, weight)
    _line(canvas, box, 0.66, 0.40, 0.66, 0.46, color, weight)
    _ellipse(canvas, box, 0.45, 0.60, 0.55, 0.70, color, weight, fill=color)


def _key(canvas, box, color, weight):
    """A key: encryption material."""
    _ellipse(canvas, box, 0.14, 0.34, 0.46, 0.66, color, weight)
    _ellipse(canvas, box, 0.24, 0.44, 0.36, 0.56, color, weight)
    _line(canvas, box, 0.44, 0.50, 0.88, 0.50, color, weight)
    _line(canvas, box, 0.70, 0.50, 0.70, 0.66, color, weight)
    _line(canvas, box, 0.84, 0.50, 0.84, 0.70, color, weight)


# ==================== Generic ====================

def _service(canvas, box, color, weight):
    """Unrecognised service: a plain rounded tile with a dot grid."""
    _rect(canvas, box, 0.18, 0.18, 0.82, 0.82, color, weight, radius=weight * 2)
    for u in (0.36, 0.50, 0.64):
        for v in (0.36, 0.50, 0.64):
            _ellipse(canvas, box, u - 0.04, v - 0.04, u + 0.04, v + 0.04,
                     color, weight, fill=color)


def _user(canvas, box, color, weight):
    """Head and shoulders."""
    _ellipse(canvas, box, 0.34, 0.14, 0.66, 0.46, color, weight)
    point = _unit(box)
    a, b = point(0.18, 0.52)
    c, d = point(0.82, 1.06)
    canvas.arc((a, b, c, d), start=180, end=360, fill=color, width=weight)


def _internet(canvas, box, color, weight):
    """A cloud outline."""
    _ellipse(canvas, box, 0.08, 0.44, 0.44, 0.80, color, weight)
    _ellipse(canvas, box, 0.28, 0.24, 0.66, 0.66, color, weight)
    _ellipse(canvas, box, 0.54, 0.38, 0.88, 0.76, color, weight)
    _rect(canvas, box, 0.20, 0.60, 0.78, 0.78, color, weight, fill=color)


GLYPHS: Dict[str, Callable] = {
    "compute": _compute,
    "function": _function,
    "container": _container,
    "kubernetes": _kubernetes,
    "batch": _batch,
    "storage": _storage,
    "filestore": _filestore,
    "archive": _archive,
    "database": _database,
    "nosql": _nosql,
    "cache": _cache,
    "warehouse": _warehouse,
    "cdn": _cdn,
    "loadbalancer": _loadbalancer,
    "dns": _dns,
    "gateway": _gateway,
    "network": _network,
    "queue": _queue,
    "topic": _topic,
    "events": _events,
    "stream": _stream,
    "workflow": _workflow,
    "monitor": _monitor,
    "identity": _identity,
    "firewall": _firewall,
    "secret": _secret,
    "key": _key,
    "service": _service,
    "user": _user,
    "internet": _internet,
}


def paint(canvas, name: str, box: Box, color, weight: int) -> bool:
    """
    Draw glyph `name` inside `box`. Returns False if there is no such glyph.

    A failure here must never lose the diagram, so any drawing error is logged
    and swallowed - the caller still has the tile and the label.
    """
    painter = GLYPHS.get((name or "").strip().lower())
    if painter is None:
        return False

    try:
        painter(canvas, box, color, max(int(weight), 1))
        return True
    except Exception as e:  # pragma: no cover - defensive
        logger.debug("Glyph %r failed to draw: %s", name, e)
        return False
