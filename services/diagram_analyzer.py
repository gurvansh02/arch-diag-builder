"""
Structural analysis of a draw.io diagram.

These checks are deterministic: they read the graph and apply rules, with no
model involved. That matters for validation, because a language model asked
"is this diagram correct?" will happily invent a plausible-sounding answer.
Whether a node has no connections, or an edge points at a component that was
never declared, is not a matter of opinion - it is a fact about the file.

The model-based half of validation lives in agents/validation_agent.py and
treats these findings as ground truth it is not allowed to contradict.
"""

from __future__ import annotations

import logging
import re
import xml.sax.saxutils as saxutils
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from lxml import etree

logger = logging.getLogger(__name__)

# Style fragments that mark a node as an entry point into the system.
ENTRY_HINTS = ("actor", "mxgraph.aws4.user", "internet", "cloud")
ENTRY_GLYPHS = {"user", "internet", "cdn", "dns", "gateway", "loadbalancer", "firewall"}

# Glyphs that hold state. A diagram with none is usually incomplete.
STORE_GLYPHS = {"database", "nosql", "storage", "cache", "warehouse", "filestore", "archive"}

_TAG = re.compile(r"<[^>]+>")


@dataclass
class Node:
    """One component in the diagram."""

    cell_id: str
    label: str
    style: Dict[str, str] = field(default_factory=dict)

    @property
    def glyph(self) -> str:
        return self.style.get("adbGlyph", "")

    @property
    def shape(self) -> str:
        return self.style.get("shape", "")

    def is_entry(self) -> bool:
        if self.glyph in ENTRY_GLYPHS:
            return True
        raw = ";".join(f"{k}={v}" for k, v in self.style.items()).lower()
        return any(hint in raw for hint in ENTRY_HINTS)

    def is_store(self) -> bool:
        if self.glyph in STORE_GLYPHS:
            return True
        return self.shape in {"cylinder3", "datastore"}


@dataclass
class Edge:
    """One directed connection."""

    source: str
    target: str
    label: str = ""


@dataclass
class Finding:
    """One structural observation about the diagram."""

    check: str          # stable id, e.g. "orphan_node"
    severity: str       # Critical | High | Medium | Low | Info
    title: str
    detail: str
    components: List[str] = field(default_factory=list)


@dataclass
class Graph:
    """The parsed diagram."""

    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    title: str = ""

    @property
    def by_id(self) -> Dict[str, Node]:
        return {node.cell_id: node for node in self.nodes}

    def summary(self) -> str:
        """A compact text rendering, used as the prompt for model validation."""
        lookup = self.by_id
        lines = [f"Diagram: {self.title or 'untitled'}", "", "Components:"]

        for node in self.nodes:
            kind = node.glyph or node.shape or "component"
            lines.append(f"- {node.label or '(unnamed)'} [{kind}]")

        lines += ["", "Connections:"]
        if not self.edges:
            lines.append("- (none)")
        for edge in self.edges:
            source = lookup.get(edge.source)
            target = lookup.get(edge.target)
            arrow = f"{_name(source)} -> {_name(target)}"
            lines.append(f"- {arrow}" + (f" [{edge.label}]" if edge.label else ""))

        return "\n".join(lines)


def _name(node: Optional[Node]) -> str:
    return (node.label if node else None) or "(unknown)"


def _plain(value: str) -> str:
    """draw.io labels may contain HTML; strip it down to readable text."""
    if not value:
        return ""
    text = value.replace("<br>", " ").replace("<br/>", " ").replace("&nbsp;", " ")
    text = _TAG.sub("", text)
    return saxutils.unescape(text).strip()


def _parse_style(style: str) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    for part in (style or "").split(";"):
        if not part:
            continue
        key, _, value = part.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def parse(drawio_xml: str) -> Tuple[Optional[Graph], Optional[Finding]]:
    """
    Read a draw.io file into a Graph.

    Returns (graph, None) or (None, finding) - a file that will not parse is
    itself the most important validation result, so it comes back as a Finding
    rather than an exception.
    """
    if not (drawio_xml or "").strip():
        return None, Finding(
            check="empty_file",
            severity="Critical",
            title="The file is empty",
            detail="No diagram content was supplied.",
        )

    try:
        parser = etree.XMLParser(recover=False, resolve_entities=False)
        root = etree.fromstring(drawio_xml.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError as e:
        return None, Finding(
            check="malformed_xml",
            severity="Critical",
            title="The diagram XML is malformed",
            detail=(
                f"draw.io could not be parsed: {e}. If this came from an "
                "export, re-save it from draw.io as Uncompressed XML."
            ),
        )

    # A .drawio saved with compression stores base64 in <diagram>, with no
    # mxGraphModel inside. Detect that rather than reporting "no components".
    model = root.find(".//mxGraphModel")
    if model is None:
        diagram = root.find(".//diagram")
        if diagram is not None and (diagram.text or "").strip():
            return None, Finding(
                check="compressed_file",
                severity="Critical",
                title="The diagram is stored compressed",
                detail=(
                    "This file holds draw.io's compressed payload rather than "
                    "readable XML. In draw.io use File -> Properties and turn "
                    "off Compressed, then save again."
                ),
            )
        return None, Finding(
            check="no_model",
            severity="Critical",
            title="No diagram model found",
            detail="The file contains no <mxGraphModel> element.",
        )

    graph = Graph()

    diagram_el = root.find(".//diagram")
    if diagram_el is not None:
        graph.title = diagram_el.get("name") or ""

    for cell in model.iter("mxCell"):
        cell_id = cell.get("id") or ""
        style = _parse_style(cell.get("style") or "")
        label = _plain(cell.get("value") or "")

        if cell.get("edge") == "1":
            graph.edges.append(
                Edge(source=cell.get("source") or "", target=cell.get("target") or "",
                     label=label)
            )
        elif cell.get("vertex") == "1":
            # The title is a text cell, not a component.
            if "text" in style and not style.get("shape"):
                continue
            graph.nodes.append(Node(cell_id=cell_id, label=label, style=style))

    return graph, None


# ==================== Rules ====================

def analyze(drawio_xml: str) -> List[Finding]:
    """Run every structural rule and return what it found."""
    graph, failure = parse(drawio_xml)
    if failure is not None:
        return [failure]

    findings: List[Finding] = []
    findings += _check_empty(graph)
    findings += _check_dangling_edges(graph)
    findings += _check_duplicate_names(graph)
    findings += _check_unnamed(graph)
    findings += _check_self_loops(graph)
    findings += _check_orphans(graph)
    findings += _check_islands(graph)
    findings += _check_entry_point(graph)
    findings += _check_data_store(graph)
    findings += _check_edge_labels(graph)
    return findings


def _check_empty(graph: Graph) -> List[Finding]:
    if graph.nodes:
        return []
    return [Finding(
        check="no_components",
        severity="Critical",
        title="The diagram has no components",
        detail="No vertices were found, so there is nothing to validate.",
    )]


def _check_dangling_edges(graph: Graph) -> List[Finding]:
    """An edge pointing at a cell that does not exist."""
    known = set(graph.by_id)
    broken = [
        edge for edge in graph.edges
        if (edge.source and edge.source not in known)
        or (edge.target and edge.target not in known)
        or not edge.source or not edge.target
    ]
    if not broken:
        return []
    return [Finding(
        check="dangling_edge",
        severity="High",
        title=f"{len(broken)} connection(s) have a missing endpoint",
        detail=(
            "These edges reference a component that is not in the file, so the "
            "flow they describe is incomplete. This usually means a component "
            "was deleted without removing its connections."
        ),
    )]


def _check_duplicate_names(graph: Graph) -> List[Finding]:
    counts = Counter(node.label for node in graph.nodes if node.label)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if not duplicates:
        return []
    return [Finding(
        check="duplicate_name",
        severity="Medium",
        title=f"{len(duplicates)} component name(s) are used more than once",
        detail=(
            "Two components sharing a name make the diagram ambiguous, and any "
            "connection naming them cannot be resolved to a single node."
        ),
        components=duplicates[:12],
    )]


def _check_unnamed(graph: Graph) -> List[Finding]:
    unnamed = [node for node in graph.nodes if not node.label]
    if not unnamed:
        return []
    return [Finding(
        check="unnamed_component",
        severity="Medium",
        title=f"{len(unnamed)} component(s) have no label",
        detail="An unlabelled box cannot be reviewed - name it after the service it represents.",
    )]


def _check_self_loops(graph: Graph) -> List[Finding]:
    lookup = graph.by_id
    loops = [edge for edge in graph.edges if edge.source and edge.source == edge.target]
    if not loops:
        return []
    return [Finding(
        check="self_loop",
        severity="Low",
        title=f"{len(loops)} component(s) connect to themselves",
        detail="A self-connection is usually an editing slip rather than a real flow.",
        components=[_name(lookup.get(edge.source)) for edge in loops][:12],
    )]


def _check_orphans(graph: Graph) -> List[Finding]:
    if len(graph.nodes) < 2:
        return []

    connected: Set[str] = set()
    for edge in graph.edges:
        connected.add(edge.source)
        connected.add(edge.target)

    orphans = [node for node in graph.nodes if node.cell_id not in connected]
    if not orphans:
        return []
    return [Finding(
        check="orphan_node",
        severity="High",
        title=f"{len(orphans)} component(s) are not connected to anything",
        detail=(
            "A component with no inbound or outbound flow is either missing its "
            "connections or does not belong in the diagram."
        ),
        components=[_name(node) for node in orphans][:12],
    )]


def _check_islands(graph: Graph) -> List[Finding]:
    """More than one weakly-connected group means the diagram is in pieces."""
    if len(graph.nodes) < 2:
        return []

    known = set(graph.by_id)
    neighbours: Dict[str, Set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.source in known and edge.target in known:
            neighbours[edge.source].add(edge.target)
            neighbours[edge.target].add(edge.source)

    seen: Set[str] = set()
    groups: List[List[str]] = []
    for node in graph.nodes:
        if node.cell_id in seen:
            continue
        stack, group = [node.cell_id], []
        seen.add(node.cell_id)
        while stack:
            current = stack.pop()
            group.append(current)
            for neighbour in neighbours[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        groups.append(group)

    # Fully isolated nodes are already reported as orphans; only flag genuine
    # multi-node islands here so the same problem is not listed twice.
    islands = [group for group in groups if len(group) > 1]
    if len(groups) < 2 or len(islands) < 2:
        return []

    lookup = graph.by_id
    return [Finding(
        check="disconnected_graph",
        severity="Medium",
        title=f"The diagram splits into {len(islands)} unconnected groups",
        detail=(
            "Each group is internally connected but there is no path between "
            "them. If these are meant to be one system, a connection is missing."
        ),
        components=[_name(lookup.get(group[0])) for group in islands][:12],
    )]


def _check_entry_point(graph: Graph) -> List[Finding]:
    if not graph.nodes or any(node.is_entry() for node in graph.nodes):
        return []
    return [Finding(
        check="no_entry_point",
        severity="Medium",
        title="No entry point is shown",
        detail=(
            "Nothing in the diagram represents a user, the public internet, or "
            "an edge service (CDN, DNS, gateway, load balancer), so it is not "
            "clear how traffic reaches the system."
        ),
    )]


def _check_data_store(graph: Graph) -> List[Finding]:
    if not graph.nodes or any(node.is_store() for node in graph.nodes):
        return []
    return [Finding(
        check="no_data_store",
        severity="Low",
        title="No data store is shown",
        detail=(
            "The architecture has no database, cache or object store. That is "
            "valid for a purely stateless design, but is worth confirming."
        ),
    )]


def _check_edge_labels(graph: Graph) -> List[Finding]:
    if len(graph.edges) < 3:
        return []
    unlabelled = [edge for edge in graph.edges if not edge.label]
    if len(unlabelled) * 2 <= len(graph.edges):
        return []
    return [Finding(
        check="unlabelled_edges",
        severity="Low",
        title=f"{len(unlabelled)} of {len(graph.edges)} connections have no protocol label",
        detail=(
            "Labelling edges with the protocol (HTTPS, SQL, gRPC, SQS) is what "
            "makes a diagram reviewable for security - an unlabelled line hides "
            "whether the traffic is encrypted."
        ),
    )]
