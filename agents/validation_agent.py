"""
Validation agent - cross-checks whether an architecture diagram is correct.

The Review page answers "how good is this architecture?". Validation answers a
narrower and harder question: "is what this diagram says actually true, and can
we trust the answer?"

A single language model is a poor validator on its own. Asked whether a diagram
is correct it will produce a fluent, confident answer whether or not it has
grounds for one, and it will give a different answer next time. Two things are
done about that here:

1. **Structural checks first.** services/diagram_analyzer.py reads the graph and
   applies deterministic rules - dangling edges, orphaned components, islands,
   duplicate names. These are facts about the file, they are reproducible, and
   they are reported separately from anything a model said.

2. **Independent cross-examination.** The same question is put to every model
   the fallback chain has available, each in its own request with no knowledge
   of the others. Their findings are then matched up. A problem both models
   raise independently is far more likely to be real than one raised by a single
   model, and that difference is surfaced rather than hidden: agreement level is
   attached to every finding, and single-model claims are listed as disputed.

What this does not do is claim certainty. Two models can be wrong together,
particularly when they share training data. The structural half is the part that
is actually reliable; the model half is a second opinion, labelled as such.
"""

from __future__ import annotations

import logging
import re
import uuid
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from config.model_fallback import model_fallback
from config.models import (
    Agreement,
    ModelVerdict,
    ValidationFinding,
    ValidationResult,
)
from config.settings import VALIDATION_SYSTEM_PROMPT
from services import diagram_analyzer, extract_json, llm_service

logger = logging.getLogger(__name__)

# Keep the prompt inside the smallest context in the chain.
MAX_SUMMARY_CHARS = 10000

# Two findings whose titles are at least this similar are treated as the same
# point made by different models. Tuned by hand: 0.6 merged unrelated issues,
# 0.8 missed obvious restatements.
SIMILARITY_THRESHOLD = 0.72

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
SEVERITY_WEIGHT = {"Critical": 25, "High": 12, "Medium": 5, "Low": 2, "Info": 0}

VALID_SEVERITIES = set(SEVERITY_ORDER)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "no", "not", "has", "have", "of", "to",
    "and", "or", "in", "on", "for", "with", "this", "that", "it", "its",
    "diagram", "architecture", "component", "components",
}
_WORD = re.compile(r"[a-z0-9]+")


class ValidationAgent:
    """Validates a diagram structurally, then cross-examines it with models."""

    VALIDATION_PROMPT = """Validate this architecture diagram.

{architecture}

Check specifically for:
- Flows that cannot work as drawn (wrong direction, impossible protocol,
  a component talking to something it cannot reach)
- Services used for a purpose they do not serve
- Missing components the drawn flows require to function
- Security boundaries that are absent or crossed incorrectly
- Internal contradictions between the components and the connections

Judge only what is shown. Do not invent components that are not in the
diagram, and do not report a problem you cannot point at.

Respond with exactly this JSON shape:
{{
    "verdict": "Correct with issues",
    "score": 72,
    "summary": "One or two sentences.",
    "findings": [
        {{
            "title": "Short statement of the problem",
            "detail": "What is wrong and why it matters.",
            "severity": "High",
            "components": ["exact component name from the diagram"]
        }}
    ]
}}

Rules:
- "verdict" must be one of: Correct, Correct with issues, Incorrect
- "severity" must be one of: Critical, High, Medium, Low
- "score" is 0-100, where 100 is a diagram with nothing wrong in it
- Return an empty "findings" list if the diagram is sound
- Every name in "components" must appear in the diagram exactly as written"""

    def __init__(self):
        self.name = "validation_agent"

    # ==================== Entry point ====================

    def validate(
        self,
        drawio_xml: str,
        user_id: str,
        source_name: str = "diagram",
        max_models: int = 3,
    ) -> ValidationResult:
        """
        Validate one diagram.

        Always returns a result: a diagram that cannot be parsed, or a run where
        no model is reachable, is still a meaningful validation outcome and is
        reported as one rather than raised.
        """
        result = ValidationResult(
            validation_id=str(uuid.uuid4()),
            user_id=user_id,
            source_name=source_name,
        )

        # ---- 1. Structural checks (deterministic) ----
        graph, failure = diagram_analyzer.parse(drawio_xml)

        if failure is not None:
            result.findings.append(_as_finding(failure))
            result.structural_ok = False
            result.verdict = "Fail"
            result.notes = "The file could not be read, so no model was consulted."
            return result

        result.component_count = len(graph.nodes)
        result.connection_count = len(graph.edges)

        structural = diagram_analyzer.analyze(drawio_xml)
        for finding in structural:
            result.findings.append(_as_finding(finding))

        result.structural_ok = not any(
            finding.severity in ("Critical", "High") for finding in structural
        )

        # ---- 2. Independent model cross-examination ----
        summary = graph.summary()
        if len(summary) > MAX_SUMMARY_CHARS:
            logger.warning(
                "Diagram summary is %d chars; validating the first %d.",
                len(summary), MAX_SUMMARY_CHARS,
            )
            summary = summary[:MAX_SUMMARY_CHARS]

        candidates = model_fallback.llm_candidates()[:max_models]

        if not candidates:
            result.notes = (
                "No language model was available, so only the structural checks "
                "ran. Those results are unaffected - they need no model."
            )
            result.verdict = self._verdict(result)
            return result

        per_model: List[Tuple[str, List[Dict]]] = []

        for config in candidates:
            label = f"{config['provider']}/{config['model']}"
            verdict, findings = self._ask_one(config, label, summary)
            result.model_verdicts.append(verdict)
            if verdict.reachable:
                per_model.append((label, findings))

        # ---- 3. Merge what the models said, by agreement ----
        merged = self._merge(per_model)
        merged = _absorb_into_structural(result.findings, merged)
        result.findings.extend(merged)

        scores = [v.score for v in result.model_verdicts if v.score is not None]
        if scores:
            result.consensus_score = round(sum(scores) / len(scores), 1)

        result.findings.sort(
            key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), -f.confidence)
        )
        result.verdict = self._verdict(result)

        logger.info(
            "Validation: %s | %d findings | %d model(s) consulted",
            result.verdict, len(result.findings), result.models_consulted,
        )
        return result

    # ==================== One model ====================

    def _ask_one(
        self, config: Dict, label: str, summary: str
    ) -> Tuple[ModelVerdict, List[Dict]]:
        """Put the validation question to a single model."""
        logger.info("Validation: asking %s", label)

        response = llm_service.generate_with(
            config=config,
            prompt=self.VALIDATION_PROMPT.format(architecture=summary),
            system_prompt=VALIDATION_SYSTEM_PROMPT,
            # Low but not zero: the point is each model's own reading, and
            # greedy decoding makes some models terser than is useful here.
            temperature=0.2,
            max_tokens=4000,
        )

        if not response:
            return ModelVerdict(
                model_label=label,
                reachable=False,
                error="No response from this provider.",
            ), []

        payload = extract_json(response)
        if not isinstance(payload, dict):
            logger.warning("%s did not return usable JSON", label)
            return ModelVerdict(
                model_label=label,
                reachable=False,
                error="Response was not valid JSON.",
            ), []

        findings = [
            item for item in (payload.get("findings") or [])
            if isinstance(item, dict) and (item.get("title") or item.get("detail"))
        ]

        return ModelVerdict(
            model_label=label,
            reachable=True,
            verdict=_clean_verdict(payload.get("verdict")),
            score=_clean_score(payload.get("score")),
            summary=(payload.get("summary") or None),
            finding_count=len(findings),
        ), findings

    # ==================== Consensus ====================

    def _merge(self, per_model: List[Tuple[str, List[Dict]]]) -> List[ValidationFinding]:
        """
        Group equivalent findings across models and score them by agreement.

        Each model's findings are matched against the groups built so far. One
        model can only reinforce a group once - otherwise a model that lists the
        same problem twice would look like corroboration.
        """
        if not per_model:
            return []

        answering = len(per_model)
        groups: List[Dict] = []

        for label, findings in per_model:
            for raw in findings:
                title = str(raw.get("title") or "").strip()
                detail = str(raw.get("detail") or "").strip()
                if not title and not detail:
                    continue
                if not title:
                    title = detail[:80]

                components = _clean_components(raw.get("components"))
                target = self._match(groups, title, detail, components)

                if target is None:
                    groups.append({
                        "title": title,
                        "detail": detail,
                        "severity": _clean_severity(raw.get("severity")),
                        "components": components,
                        "raised_by": [label],
                    })
                    continue

                if label not in target["raised_by"]:
                    target["raised_by"].append(label)

                # Keep the most serious severity any model assigned, and the
                # fullest description - models vary a lot in how much they say.
                if SEVERITY_ORDER.get(_clean_severity(raw.get("severity")), 9) < \
                        SEVERITY_ORDER.get(target["severity"], 9):
                    target["severity"] = _clean_severity(raw.get("severity"))
                if len(detail) > len(target["detail"]):
                    target["detail"] = detail
                for component in _clean_components(raw.get("components")):
                    if component not in target["components"]:
                        target["components"].append(component)

        merged: List[ValidationFinding] = []
        for group in groups:
            raised = len(group["raised_by"])
            agreement, confidence = _agreement(raised, answering)

            merged.append(ValidationFinding(
                check="model_finding",
                severity=group["severity"],
                title=group["title"],
                detail=group["detail"],
                components=group["components"][:12],
                source="model",
                agreement=agreement,
                raised_by=group["raised_by"],
                confidence=confidence,
            ))

        return merged

    @staticmethod
    def _match(
        groups: List[Dict], title: str, detail: str, components: List[str]
    ) -> Optional[Dict]:
        """
        Find an existing group describing the same problem, if any.

        Wording is a weak signal on its own. Two models describing the same
        reversed arrow produced "SQL flow direction is reversed" and "Inverted
        connection direction between Orders DB and Orders Service" - almost no
        shared vocabulary, but both named the same two components. Which
        components a finding points at is the more reliable signal, so a strong
        component overlap lets a much weaker textual match count.
        """
        best: Optional[Dict] = None
        best_score = 0.0

        for group in groups:
            text = _similarity(title, group["title"])

            # Titles can be worded very differently for the same point, so a
            # strong overlap in the detail rescues those cases.
            if detail and group["detail"]:
                text = max(text, _similarity(detail, group["detail"]) * 0.9)

            shared = _component_overlap(components, group["components"])

            if shared >= 0.5 and text >= 0.25:
                # Same components, recognisably related wording.
                score = max(text, SIMILARITY_THRESHOLD)
            elif shared >= 0.5:
                # Same components but unrelated wording - two genuinely
                # different problems with one component can look like this,
                # so nudge rather than merge outright.
                score = text + 0.25
            else:
                score = text

            if score > best_score:
                best, best_score = group, score

        return best if best_score >= SIMILARITY_THRESHOLD else None

    # ==================== Verdict ====================

    @staticmethod
    def _verdict(result: ValidationResult) -> str:
        """Pass / Pass with warnings / Fail, from the findings that survived."""
        # A single-model claim is not enough to fail a diagram on when other
        # models saw the same thing and said nothing.
        def counts(severity: str) -> int:
            return sum(
                1 for finding in result.findings
                if finding.severity == severity
                and not (
                    finding.source == "model"
                    and finding.agreement == Agreement.SINGLE
                    and result.models_consulted > 1
                )
            )

        if counts("Critical"):
            return "Fail"
        if counts("High") >= 2:
            return "Fail"
        if counts("High") or counts("Medium"):
            return "Pass with warnings"
        if any(f.severity == "Low" for f in result.findings):
            return "Pass with warnings"
        return "Pass"


# ==================== Helpers ====================

def _as_finding(finding) -> ValidationFinding:
    """Wrap a deterministic analyzer finding, marked as structural."""
    return ValidationFinding(
        check=finding.check,
        severity=finding.severity,
        title=finding.title,
        detail=finding.detail,
        components=list(finding.components),
        source="structural",
        agreement=Agreement.STRUCTURAL,
        raised_by=["structural checks"],
        # Deterministic: it either holds or it does not.
        confidence=1.0,
    )


# Structural checks that name specific components, and so can be matched
# against a model finding by the components it cites.
_COMPONENT_CHECKS = {
    "orphan_node",
    "duplicate_name",
    "self_loop",
    "disconnected_graph",
    "unnamed_component",
}


def _absorb_into_structural(
    structural: List[ValidationFinding], model_findings: List[ValidationFinding]
) -> List[ValidationFinding]:
    """
    Drop model findings that restate something the structural checks proved.

    If a model independently reports the orphaned component the analyzer had
    already found, that is corroboration, not a second problem. Listing it
    twice would double-count it in the verdict and pad the report. The model is
    instead credited on the structural finding, which keeps the evidence
    visible without inflating the count.
    """
    anchors = [
        finding for finding in structural
        if finding.source == "structural" and finding.check in _COMPONENT_CHECKS
        and finding.components
    ]
    if not anchors:
        return model_findings

    kept: List[ValidationFinding] = []

    for finding in model_findings:
        absorbed = False

        for anchor in anchors:
            if _component_overlap(finding.components, anchor.components) >= 0.5:
                for label in finding.raised_by:
                    if label not in anchor.raised_by:
                        anchor.raised_by.append(label)
                logger.debug(
                    "Model finding %r absorbed into structural check %s",
                    finding.title, anchor.check,
                )
                absorbed = True
                break

        if not absorbed:
            kept.append(finding)

    return kept


def _tokens(text: str) -> List[str]:
    return [
        word for word in _WORD.findall((text or "").lower())
        if word not in _STOPWORDS and len(word) > 2
    ]


def _similarity(left: str, right: str) -> float:
    """
    How alike two statements are, 0-1.

    Token overlap catches the same point worded differently ("RDS is publicly
    reachable" / "the database is exposed to the internet" share 'rds' or
    'database' plus 'public'/'internet'); character ratio catches near-identical
    phrasing. The stronger of the two wins.
    """
    left_tokens, right_tokens = set(_tokens(left)), set(_tokens(right))

    overlap = 0.0
    if left_tokens and right_tokens:
        shared = left_tokens & right_tokens
        overlap = len(shared) / min(len(left_tokens), len(right_tokens))

    ratio = SequenceMatcher(None, (left or "").lower(), (right or "").lower()).ratio()
    return max(overlap, ratio)


def _component_overlap(left: List[str], right: List[str]) -> float:
    """
    Jaccard overlap of two component name lists, 0-1.

    Names are normalised because models are inconsistent about case and
    punctuation ("Orders DB", "orders-db", "Orders  DB").
    """
    left_set = {" ".join(_WORD.findall((name or "").lower())) for name in left}
    right_set = {" ".join(_WORD.findall((name or "").lower())) for name in right}
    left_set.discard("")
    right_set.discard("")

    if not left_set or not right_set:
        return 0.0

    return len(left_set & right_set) / len(left_set | right_set)


def _agreement(raised_by: int, answering: int) -> Tuple[Agreement, float]:
    """Map "n of m models said this" onto an agreement level and confidence."""
    if answering <= 1:
        # With one model there is nothing to corroborate against. Say so rather
        # than implying consensus from a single opinion.
        return Agreement.SINGLE, 0.5

    if raised_by >= answering:
        return Agreement.UNANIMOUS, 0.95
    if raised_by * 2 > answering:
        return Agreement.MAJORITY, 0.75
    return Agreement.SINGLE, 0.4


def _clean_severity(value) -> str:
    text = str(value or "").strip().title()
    return text if text in VALID_SEVERITIES else "Medium"


def _clean_verdict(value) -> Optional[str]:
    text = str(value or "").strip()
    for allowed in ("Correct with issues", "Incorrect", "Correct"):
        if text.lower() == allowed.lower():
            return allowed
    return text or None


def _clean_score(value) -> Optional[float]:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, score))


def _clean_components(value) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


validation_agent = ValidationAgent()
