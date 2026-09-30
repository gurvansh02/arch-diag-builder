"""
Agent workflow: route the request, then generate and/or review.

Deliberately synchronous. The three agents do no concurrent I/O, so the
previous async wrapper bought nothing and needed nest_asyncio plus manual
event-loop juggling to survive Streamlit's execution model.
"""

import logging

from agents.generation_agent import generation_agent
from agents.orchestration_agent import orchestration_agent
from agents.review_agent import review_agent
from config.models import DiagramState, TaskType

logger = logging.getLogger(__name__)


class DiagramWorkflow:
    """Runs the agent pipeline for one request."""

    def __init__(self):
        self.name = "diagram_workflow"

    def execute(self, state: DiagramState) -> DiagramState:
        """Route the request and run the matching agents."""
        try:
            logger.info("Workflow: starting for user %s", state.user_id)

            state.execution_status = "processing"

            state = orchestration_agent.route(state)
            if state.error:
                return state

            if state.task_type == TaskType.GENERATE:
                state = generation_agent.generate(state)

            elif state.task_type == TaskType.REVIEW:
                state = review_agent.review(state)

            elif state.task_type == TaskType.BOTH:
                state = generation_agent.generate(state)
                # Reviewing needs a file to read. Without one, the diagram we
                # just generated is the whole answer - failing the request on a
                # review step the user never asked for would throw it away.
                if not state.error and state.uploaded_file_path:
                    state = review_agent.review(state)

            logger.info("Workflow: finished with status %s", state.execution_status)
            return state

        except Exception as e:
            logger.error("Workflow error: %s", e, exc_info=True)
            state.error = str(e)
            state.execution_status = "failed"
            return state


workflow = DiagramWorkflow()


def run_workflow(state: DiagramState) -> DiagramState:
    """Entry point used by the Streamlit app."""
    return workflow.execute(state)
