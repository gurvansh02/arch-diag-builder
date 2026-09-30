"""Generation agent - creates architecture diagrams"""

import logging
import uuid

from config.models import DiagramState
from config.settings import ARCHITECTURE_BLUEPRINT_SYSTEM_PROMPT, CLOUD_ICONS
from services import cloud_icons, drawio_service, extract_json, llm_service
from storage import diagram_store

logger = logging.getLogger(__name__)


class GenerationAgent:
    """Turns a project description into a draw.io diagram."""

    BLUEPRINT_PROMPT = """Design an architecture for this project:

{project_description}

Cloud provider: {cloud_provider}
Architectural pattern: {architectural_pattern}

Use these {cloud_provider} service keys wherever one fits (key=Service name):
{service_catalogue}

Respond with exactly this JSON shape:
{{
    "components": [
        {{"name": "Public API", "type": "service", "service": "apigateway",
          "layer": "Application"}}
    ],
    "connections": [
        {{"from": "Public API", "to": "Order Service", "type": "HTTPS"}}
    ]
}}

Rules:
- "service" is the key from the catalogue above and decides which official
  cloud icon is drawn. Set it on every component backed by a cloud service.
- Omit "service" only for a person or the public internet, and set "type" to
  "user" or "internet" instead.
- "type" must be one of: service, database, container, queue, cdn, user, internet
- Every "from" and "to" must match a component "name" exactly
- Give components their real service names, not generic labels"""

    def __init__(self):
        self.name = "generation_agent"

    def generate(self, state: DiagramState) -> DiagramState:
        """Generate and persist an architecture diagram."""
        logger.info("Generation: creating %s diagram", state.diagram_type)

        if not state.project_description:
            state.error = "No project description provided"
            state.execution_status = "failed"
            return state

        cloud_provider = state.cloud_providers[0] if state.cloud_providers else "AWS"

        response = llm_service.generate_text(
            prompt=self.BLUEPRINT_PROMPT.format(
                project_description=state.project_description,
                cloud_provider=cloud_provider,
                architectural_pattern=state.architectural_pattern or "microservices",
                service_catalogue=self._service_catalogue(cloud_provider),
            ),
            system_prompt=ARCHITECTURE_BLUEPRINT_SYSTEM_PROMPT,
            temperature=0.4,
        )

        if not response:
            state.error = (
                "Could not reach any language model. Check the Admin Dashboard "
                "for provider status."
            )
            state.execution_status = "failed"
            return state

        blueprint = extract_json(response)
        if not isinstance(blueprint, dict):
            logger.error("Blueprint was not valid JSON: %s", response[:300])
            state.error = "The model did not return a usable architecture. Try rephrasing."
            state.execution_status = "failed"
            return state

        components = blueprint.get("components") or []
        connections = blueprint.get("connections") or []

        if not components:
            state.error = "The model returned an architecture with no components."
            state.execution_status = "failed"
            return state

        drawio_xml = drawio_service.create_infrastructure_diagram(
            project_name=state.project_description[:60],
            components=components,
            connections=connections,
            cloud_provider=cloud_provider,
        )

        if not drawio_xml:
            state.error = "Failed to render the diagram XML"
            state.execution_status = "failed"
            return state

        diagram_id = str(uuid.uuid4())
        metadata = diagram_store.save_diagram(
            user_id=state.user_id,
            conversation_id=state.conversation_id,
            diagram_type=state.diagram_type,
            drawio_xml=drawio_xml,
            project_description=state.project_description,
            cloud_providers=state.cloud_providers,
            architectural_pattern=state.architectural_pattern,
            diagram_id=diagram_id,
        )

        if not metadata:
            state.error = "Failed to save the diagram"
            state.execution_status = "failed"
            return state

        state.generated_diagram = drawio_xml
        state.diagram_id = diagram_id
        state.execution_status = "completed"

        logger.info(
            "Generation: created %s with %d components", diagram_id, len(components)
        )
        return state

    @staticmethod
    def _service_catalogue(cloud_provider: str) -> str:
        """
        `key=Label` pairs the model answers with, so each component resolves to
        an official cloud icon rather than a generic box.
        """
        catalogue = cloud_icons.catalogue_for_prompt(cloud_provider)
        if catalogue:
            return catalogue

        # No icon registry for this provider - fall back to the plain service
        # name list, which still steers the vocabulary even without icons.
        services = CLOUD_ICONS.get(cloud_provider, {}).get("common_services", [])
        return ", ".join(services) if services else "(no catalogue available)"


generation_agent = GenerationAgent()
