"""Top-level supervisor graph — ReAct planner that orchestrates domain agents.

Graph topology (NEW — planner pattern):

    __start__ --> supervisor_llm --> [conditional routing]
                    ^                   |
                    |                   v
                    +--- agent_dispatcher
                    (loop while supervisor emits tool_calls)

The supervisor LLM has each domain agent bound as a tool. It analyzes user
intent, decides which agent(s) to call, and loops until it has a final answer.

Agent sub-graphs are pre-built and stored in a dict, then injected via
``config.configurable.subgraphs`` so the agent_dispatcher can invoke them.

Adding a new agent directory under .agents/ automatically:
- Adds it as a tool for the supervisor LLM.
- Makes it available in the subgraphs dict for dispatch.
No graph topology changes needed.
"""

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from self_agent.app.registries.agent_registry import AgentRegistry
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.registries.skill_registry import SkillRegistry
from self_agent.app.graph.state import OrchestrationState
from self_agent.app.graph.nodes.supervisor_node import make_supervisor_node
from self_agent.app.graph.nodes.agent_dispatcher_node import make_agent_dispatcher_node
from self_agent.app.graph.nodes.agent_subgraph import build_agent_subgraph

logger = logging.getLogger(__name__)


# ── Conditional routing ──────────────────────────────────────────────────

def _should_dispatch(state: dict) -> Literal["agent_dispatcher", "__end__"]:
    """Check whether the last supervisor message contains tool_calls.

    - tool_calls present → route to agent_dispatcher (execute sub-agent).
    - no tool_calls → the supervisor has a final answer, route to END.
    """
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", None) or []
    if tool_calls:
        return "agent_dispatcher"
    return "__end__"


# ── Graph builder ────────────────────────────────────────────────────────

def build_supervisor_graph(
    agent_registry: AgentRegistry,
    skill_registry: SkillRegistry,
    agent_loader: AgentLoader,
    checkpointer=None,
) -> StateGraph:
    """Build and compile the ReAct orchestration graph.

    Architecture:
    1. Build a compiled ReAct subgraph for each domain agent.
    2. Store them in ``subgraphs`` dict (passed via config.configurable).
    3. Build the top-level graph with two nodes:
       - ``supervisor_llm`` — LLM planner with agent tools.
       - ``agent_dispatcher`` — executes subgraphs when supervisor calls.

    Args:
        agent_registry: Scanned from .agents/*/agent.yml at startup.
        skill_registry: Scanned from .agents/*/skills/*.yml at startup.
        agent_loader: Used to build ToolExecutors for each agent.
        checkpointer: LangGraph checkpointer for state persistence.

    Returns:
        A compiled LangGraph StateGraph ready for astream_events / ainvoke.
    """
    builder = StateGraph(state_schema=OrchestrationState)

    # ── Pre-build agent subgraphs ───────────────────────────────────
    # Each domain agent gets its own ReAct subgraph.
    # They are stored in a dict and passed via config.configurable so
    # agent_dispatcher can invoke them at runtime.
    subgraphs: dict = {}

    for agent_def in agent_registry.list():
        if agent_def.name == "supervisor":
            continue
        try:
            subgraph = build_agent_subgraph(agent_def, skill_registry, agent_loader)
            subgraphs[agent_def.name] = subgraph
            logger.info(
                "Built agent subgraph: %s (skills: %s)",
                agent_def.name,
                agent_def.equipped_skills,
            )
        except Exception:
            logger.exception(
                "Failed to build subgraph for agent: %s", agent_def.name
            )

    logger.info("Total agent subgraphs built: %d", len(subgraphs))

    # ── Supervisor LLM node ─────────────────────────────────────────
    supervisor_node = make_supervisor_node(agent_registry)
    builder.add_node("supervisor_llm", supervisor_node)

    # ── Agent dispatcher node ───────────────────────────────────────
    # Pass subgraphs dict directly — the dispatcher closes over it.
    # This avoids threading subgraphs through config.configurable.
    agent_dispatcher_node = make_agent_dispatcher_node(subgraphs)
    builder.add_node("agent_dispatcher", agent_dispatcher_node)

    # ── Edges ───────────────────────────────────────────────────────
    builder.set_entry_point("supervisor_llm")

    # After supervisor_llm: if tool_calls → dispatch, else → END
    builder.add_conditional_edges(
        "supervisor_llm",
        _should_dispatch,
        {
            "agent_dispatcher": "agent_dispatcher",
            "__end__": END,
        },
    )

    # After agent_dispatcher → back to supervisor_llm (ReAct loop)
    builder.add_edge("agent_dispatcher", "supervisor_llm")

    # ── Compile ─────────────────────────────────────────────────────
    compiled = builder.compile(checkpointer=checkpointer)
    logger.info(
        "Supervisor graph compiled (planner pattern): %d agents available as tools",
        len(subgraphs),
    )
    return compiled
