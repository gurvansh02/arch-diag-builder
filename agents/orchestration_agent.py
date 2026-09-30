"""Orchestration agent - routes user requests"""

import logging

from config.models import DiagramState, DiagramType, TaskType
from config.settings import ORCHESTRATION_SYSTEM_PROMPT
from services import extract_json, llm_service

logger = logging.getLogger(__name__)


class OrchestrationAgent:
    """Routes user requests to the generate / review workflows."""

    ROUTING_PROMPT = """Classify this request and extract its parameters.

User request:
{user_input}

Determine:
1. task_type - "generate" to create a new diagram, "review" to analyse an
   existing one, "both" if the user wants a diagram created and critiqued.
2. cloud_providers - any of AWS, Azure, GCP mentioned or implied.
3. architectural_pattern - microservices, serverless, monolithic, event-driven,
   three-tier, hybrid, or similar.
4. requirements - a clear, self-contained summary of what to build.

Respond with exactly this JSON shape:
{{
    "task_type": "generate",
    "cloud_providers": ["AWS"],
    "architectural_pattern": "microservices",
    "requirements": "..."
}}"""

    def __init__(self):
        self.name = "orchestration_agent"

    def route(self, state: DiagramState) -> DiagramState:
        """Determine what the user is asking for and populate the state."""
        logger.info("Orchestration: routing request from user %s", state.user_id)

        # An upload with no text is unambiguously a review request, and needs
        # no model call to classify.
        if state.uploaded_file_path and not (state.user_input or "").strip():
            state.task_type = TaskType.REVIEW
            state.project_description = "Review of uploaded architecture"
            logger.info("Orchestration: upload with no prompt -> REVIEW")
            return state

        response = llm_service.generate_text(
            prompt=self.ROUTING_PROMPT.format(user_input=state.user_input),
            system_prompt=ORCHESTRATION_SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=800,
        )

        if not response:
            state.error = (
                "Could not reach any language model. Check the Admin Dashboard "
                "for provider status."
            )
            state.execution_status = "failed"
            return state

        routing = extract_json(response) or {}
        if not isinstance(routing, dict):
            routing = {}

        state.task_type = self._parse_task_type(routing.get("task_type"), state)
        state.diagram_type = DiagramType.INFRASTRUCTURE  # Phase 1
        state.cloud_providers = self._parse_providers(routing.get("cloud_providers"))
        state.architectural_pattern = routing.get("architectural_pattern")
        state.project_description = routing.get("requirements") or state.user_input

        logger.info(
            "Orchestration: %s | %s | %s",
            state.task_type.value,
            ", ".join(state.cloud_providers),
            state.architectural_pattern or "no pattern",
        )
        return state

    @staticmethod
    def _parse_task_type(value, state: DiagramState) -> TaskType:
        """Map the model's answer onto a TaskType, defaulting sensibly."""
        try:
            return TaskType(str(value).strip().lower())
        except (ValueError, AttributeError):
            # Unrecognised value: infer from whether a file was uploaded
            # rather than failing the request.
            fallback = TaskType.REVIEW if state.uploaded_file_path else TaskType.GENERATE
            logger.warning("Unrecognised task_type %r, defaulting to %s", value, fallback.value)
            return fallback

    @staticmethod
    def _parse_providers(value) -> list:
        """Normalise cloud provider names, defaulting to AWS."""
        known = {"aws": "AWS", "azure": "Azure", "gcp": "GCP", "google": "GCP"}

        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return ["AWS"]

        providers = []
        for item in value:
            match = known.get(str(item).strip().lower())
            if match and match not in providers:
                providers.append(match)

        return providers or ["AWS"]


orchestration_agent = OrchestrationAgent()
