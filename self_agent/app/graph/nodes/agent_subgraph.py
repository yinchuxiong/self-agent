"""Agent sub-graph builder — compiles a ReAct loop for a single domain agent.

Each agent sub-graph is a LangGraph StateGraph with the topology:

    __start__ --> skill_matcher --> llm_call --> [conditional]
                                     ^              |
                                     |              v
                                     +--- tool_executor
                                     (loop while tool_calls exist)

The sub-graph is compiled and returned. It is then added as a node in the
top-level supervisor graph.
"""

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from self_agent.app.core.models import AgentDefinition
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.registries.skill_registry import SkillRegistry
from self_agent.app.graph.state import OrchestrationState
from self_agent.app.graph.nodes.skill_matcher import make_skill_matcher_node
from self_agent.app.graph.nodes.llm_node import make_llm_node
from self_agent.app.graph.nodes.tool_node import make_tool_node

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5


def _should_continue_tools(state: dict) -> Literal["tool_executor", "__end__"]:
    """Conditional edge: check if the last AI message has tool calls.

    Returns "tool_executor" to continue the ReAct loop, or "__end__" to
    terminate and emit the final answer.
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_msg = messages[-1]

    # LangChain AIMessage has tool_calls attribute
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls:
        return "tool_executor"

    # No tool calls → loop ends, answer is in last message content
    content = getattr(last_msg, "content", "") or ""
    return "__end__"


def build_agent_subgraph(
    agent_def: AgentDefinition,
    skill_registry: SkillRegistry,
    agent_loader: AgentLoader,
) -> StateGraph:
    """Build and compile a ReAct agent sub-graph.

    Args:
        agent_def: The agent definition (name, display_name, workspace_dir, etc.).
        skill_registry: Global skill registry for trigger-based matching.
        agent_loader: Agent filesystem loader (for future prompt customization).

    Returns:
        A compiled LangGraph StateGraph (can be used as a node in a parent graph).
    """
    agent_name = agent_def.name

    builder = StateGraph(state_schema=OrchestrationState)

    # ── Nodes ─────────────────────────────────────────────────────────
    skill_matcher_node = make_skill_matcher_node(agent_def, skill_registry)
    llm_node = make_llm_node(agent_def, agent_loader)
    tool_node = make_tool_node(agent_def, agent_loader)

    builder.add_node("skill_matcher", skill_matcher_node)
    builder.add_node("llm_call", llm_node)
    builder.add_node("tool_executor", tool_node)

    # ── Edges ─────────────────────────────────────────────────────────
    builder.set_entry_point("skill_matcher")
    builder.add_edge("skill_matcher", "llm_call")
    builder.add_conditional_edges(
        "llm_call",
        _should_continue_tools,
        {
            "tool_executor": "tool_executor",
            "__end__": END,
        },
    )
    builder.add_edge("tool_executor", "llm_call")

    compiled = builder.compile()
    logger.info("Compiled agent sub-graph: %s", agent_name)
    return compiled
