"""Review agent - analyzes and reviews architectures"""

import logging
import uuid
from pathlib import Path
from typing import Optional

from config.models import (
    DiagramState,
    Review,
    ReviewCategory,
    ReviewIssue,
    ReviewSeverity,
)
from config.settings import DIAGRAM_REVIEW_SYSTEM_PROMPT
from services import extract_json, file_processor, llm_service, vision_service
from storage import review_store

logger = logging.getLogger(__name__)

# Roughly 3k tokens of architecture description - fits the smallest model in
# the chain (Ollama) with room for the prompt and the response.
MAX_ARCHITECTURE_CHARS = 12000

# The model is asked for these labels; map them onto the ReviewCategory enum.
# Without this, every "Cost" issue failed enum validation and was dropped.
CATEGORY_ALIASES = {
    "security": ReviewCategory.SECURITY,
    "cost": ReviewCategory.COST,
    "cost optimization": ReviewCategory.COST,
    "cost optimisation": ReviewCategory.COST,
    "performance": ReviewCategory.PERFORMANCE,
    "scalability": ReviewCategory.SCALABILITY,
    "compliance": ReviewCategory.COMPLIANCE,
    "architecture": ReviewCategory.ARCHITECTURE,
}

SEVERITY_ALIASES = {
    "critical": ReviewSeverity.CRITICAL,
    "high": ReviewSeverity.HIGH,
    "medium": ReviewSeverity.MEDIUM,
    "low": ReviewSeverity.LOW,
}


class ReviewAgent:
    """Reviews and analyses architecture diagrams."""

    REVIEW_PROMPT = """Review this architecture:

{architecture_description}

Assess it for security, cost optimization, performance, scalability, and
compliance.

Respond with exactly this JSON shape:
{{
    "issues": [
        {{
            "category": "Security",
            "severity": "High",
            "description": "...",
            "suggestion": "...",
            "affected_components": ["component name"]
        }}
    ],
    "overall_score": 75,
    "summary": "..."
}}

Rules:
- "category" must be one of: Security, Cost, Performance, Scalability,
  Compliance, Architecture
- "severity" must be one of: Critical, High, Medium, Low
- "overall_score" is 0-100, where 100 is a production-ready design"""

    def __init__(self):
        self.name = "review_agent"

    def review(self, state: DiagramState) -> DiagramState:
        """Review an uploaded architecture."""
        logger.info("Review: analysing architecture for user %s", state.user_id)

        if not state.uploaded_file_path:
            state.error = (
                "No file to review. Upload your diagram on the Review page "
                "(image, PDF or .drawio)."
            )
            state.execution_status = "failed"
            return state

        is_valid, file_type = file_processor.is_valid_file(state.uploaded_file_path)
        if not is_valid:
            state.error = f"Invalid file: {file_type}"
            state.execution_status = "failed"
            return state

        state.uploaded_file_type = file_type

        architecture_text = self._extract_architecture(state.uploaded_file_path, file_type)
        if not architecture_text or not architecture_text.strip():
            state.error = (
                "Could not read the architecture from that file. For images, "
                "check the Admin Dashboard for vision provider status."
            )
            state.execution_status = "failed"
            return state

        state.extracted_architecture = architecture_text

        review_data = self._analyze(architecture_text)
        if review_data is None:
            state.error = (
                "Could not reach any language model. Check the Admin Dashboard "
                "for provider status."
            )
            state.execution_status = "failed"
            return state

        review = Review(
            review_id=str(uuid.uuid4()),
            diagram_id=state.diagram_id or "unknown",
            user_id=state.user_id,
            uploaded_file_type=file_type,
            uploaded_file_path=state.uploaded_file_path,
            source_filename=state.uploaded_file_name or Path(state.uploaded_file_path).name,
            summary=review_data.get("summary"),
            overall_score=self._parse_score(review_data.get("overall_score")),
        )

        for issue_data in review_data.get("issues") or []:
            issue = self._parse_issue(issue_data)
            if issue:
                review.issues.append(issue)

        review_store.save_review(review)

        state.review_results = review
        state.execution_status = "completed"

        logger.info("Review: completed with %d issues", len(review.issues))
        return state

    # ==================== Extraction ====================

    def _extract_architecture(self, file_path: str, file_type: str) -> Optional[str]:
        """Read an architecture description out of the uploaded file."""
        try:
            if file_type == "image":
                logger.info("Reading architecture from image")
                return vision_service.analyze_architecture_from_image(file_path)

            if file_type == "drawio":
                logger.info("Reading draw.io XML")
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()

            if file_type == "pdf":
                logger.info("Extracting text from PDF")
                return self._extract_pdf_text(file_path)

            logger.warning("No extractor for file type: %s", file_type)
            return None

        except Exception as e:
            logger.error("Error extracting architecture: %s", e)
            return None

    @staticmethod
    def _extract_pdf_text(file_path: str) -> Optional[str]:
        """Extract text from a PDF, skipping pages that have none."""
        try:
            import pdfplumber
        except ImportError:
            logger.warning("pdfplumber not installed - cannot read PDFs")
            return None

        with pdfplumber.open(file_path) as pdf:
            # extract_text() returns None for image-only pages, which used to
            # crash the join.
            pages = [page.extract_text() for page in pdf.pages]
            return "\n".join(text for text in pages if text)

    # ==================== Analysis ====================

    def _analyze(self, architecture_text: str) -> Optional[dict]:
        """Ask the model to review the architecture."""
        if len(architecture_text) > MAX_ARCHITECTURE_CHARS:
            logger.warning(
                "Architecture description is %d chars; reviewing the first %d "
                "to stay within model context.",
                len(architecture_text),
                MAX_ARCHITECTURE_CHARS,
            )
            architecture_text = architecture_text[:MAX_ARCHITECTURE_CHARS]

        response = llm_service.generate_text(
            prompt=self.REVIEW_PROMPT.format(architecture_description=architecture_text),
            system_prompt=DIAGRAM_REVIEW_SYSTEM_PROMPT,
            temperature=0.3,
        )

        if not response:
            return None

        review_data = extract_json(response)
        if not isinstance(review_data, dict):
            logger.warning("Review response was not valid JSON: %s", response[:300])
            return {
                "issues": [],
                "overall_score": None,
                "summary": response.strip()[:1000],
            }

        return review_data

    # ==================== Parsing ====================

    @staticmethod
    def _parse_issue(issue_data) -> Optional[ReviewIssue]:
        """Build a ReviewIssue, tolerating the label variants models produce."""
        if not isinstance(issue_data, dict):
            return None

        description = issue_data.get("description")
        if not description:
            return None

        category = CATEGORY_ALIASES.get(
            str(issue_data.get("category", "")).strip().lower(),
            ReviewCategory.ARCHITECTURE,
        )
        severity = SEVERITY_ALIASES.get(
            str(issue_data.get("severity", "")).strip().lower(),
            ReviewSeverity.MEDIUM,
        )

        components = issue_data.get("affected_components") or []
        if isinstance(components, str):
            components = [components]

        return ReviewIssue(
            category=category,
            severity=severity,
            description=str(description),
            suggestion=str(issue_data.get("suggestion") or "No suggestion provided"),
            affected_components=[str(c) for c in components],
        )

    @staticmethod
    def _parse_score(value) -> Optional[float]:
        """Coerce the score to a 0-100 float, or None."""
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return None


review_agent = ReviewAgent()
