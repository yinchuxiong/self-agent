"""Skill matcher node — scans the SkillRegistry for matching skills.

Replicates the trigger-based keyword matching that was previously done
inside AgentRuntime.stream_chat(). Each match emits a skill_activated
custom event via dispatch_custom_event for SSE streaming.
"""

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from self_agent.app.core.models import AgentDefinition
from self_agent.app.registries.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)


def make_skill_matcher_node(
    agent_def: AgentDefinition,
    skill_registry: SkillRegistry,
):
    """Return an async node that matches skills against user input.

    Args:
        agent_def: The target agent definition (provides agent name).
        skill_registry: The global skill registry (provides match_skills).
    """

    agent_name = agent_def.name

    async def skill_matcher_node(state: dict, config: RunnableConfig) -> dict:
        user_input: str = state.get("user_input", "")
        trace_id: str = state.get("trace_id", "")

        if not user_input:
            return {"activated_skills": []}

        matched = skill_registry.match_skills(agent_name, user_input)

        writer = get_stream_writer()
        for skill in matched:
            logger.info(
                "Skill activated: %s for agent %s (trigger match)",
                skill.name,
                agent_name,
            )
            writer(
                {
                    "event": "skill_activated",
                    "trace_id": trace_id,
                    "agent": agent_name,
                    "skill": skill.name,
                    "message": f"Activated skill: {skill.display_name}",
                    "data": {
                        "skill": skill.name,
                        "display_name": skill.display_name,
                        "category": skill.category,
                    },
                }
            )

        return {"activated_skills": [s.name for s in matched]}

    return skill_matcher_node
