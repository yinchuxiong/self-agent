"""Agent dispatcher node — executes domain agent subgraphs on behalf of the supervisor.

When the supervisor LLM emits a tool_call targeting a domain agent (e.g.
``programming_agent``), this node:

1. Extracts the agent name and prompt from the tool_call.
2. Builds a fresh sub-state for the targeted agent.
3. Runs the agent's compiled ReAct subgraph with full streaming.
4. Forwards internal events (tool_started, answer_delta, tool_result) to the
   parent graph's SSE stream via ``get_stream_writer()``.
5. Returns a ``ToolMessage`` carrying the agent's final answer, which the
   supervisor LLM sees on the next ReAct iteration.

Result-passing pattern
----------------------
Supervisor → AIMessage(tool_calls=[{name: "programming_agent", args: {prompt: "..."}}])
           → AgentDispatcher runs programming subgraph
           → ToolMessage(content="(agent's final answer)", tool_call_id=...)
           → Supervisor sees the ToolMessage → decides next step
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from self_agent.app.core.config import get_settings
from self_agent.app.core.models import new_id
from self_agent.app.graph.nodes.supervisor_node import _agent_name_from_tool

logger = logging.getLogger(__name__)

# Maximum characters for an agent result to avoid overflowing the supervisor
# context window with huge tool outputs.
MAX_RESULT_CHARS = 8000


def _extract_final_answer(messages: list) -> str:
    """Extract the final text answer from a sub-agent's message list.

    Walks the message list in reverse, looking for the last AI message that
    has text content (skipping tool-call-only messages).
    """
    for msg in reversed(messages):
        if not hasattr(msg, "type") or msg.type != "ai":
            continue
        content = getattr(msg, "content", "") or ""
        tool_calls = getattr(msg, "tool_calls", None) or []
        # Skip AIMessages that are only tool calls with no text
        if content.strip():
            return content
        if not tool_calls:
            return content
    return ""


# ── Node factory ────────────────────────────────────────────────────────

def make_agent_dispatcher_node(subgraphs: dict):
    """Return an async node that executes domain agent subgraphs.

    The node reads the last AIMessage from state, extracts tool_calls that
    target domain agents (tool names ending in ``_agent``), runs each
    corresponding subgraph, and returns ToolMessage results.

    Args:
        subgraphs: Dict mapping agent name → compiled LangGraph StateGraph.
                   The dispatcher closes over this dict — no config needed.
    """

    async def agent_dispatcher_node(state: dict, config: RunnableConfig) -> dict:
        configurable = config.get("configurable", {})
        settings = configurable.get("settings") or get_settings()
        executors: dict = configurable.get("executors", {})

        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_msg = messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        if not tool_calls:
            return {"messages": []}

        writer = get_stream_writer()
        trace_id: str = state.get("trace_id", "")

        tool_messages: list[ToolMessage] = []

        for tc in tool_calls:
            # Normalize tool_call to dict
            if isinstance(tc, dict):
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tool_call_id = tc.get("id", "")
            else:
                tool_name = getattr(tc, "name", "")
                tool_args = getattr(tc, "args", {})
                tool_call_id = getattr(tc, "id", "")

            agent_name = _agent_name_from_tool(tool_name)
            prompt = tool_args.get("prompt", "") if isinstance(tool_args, dict) else str(tool_args)

            logger.info(
                "Agent dispatcher: delegating to %s (prompt: %s...)",
                agent_name,
                prompt[:100],
            )

            # ── Validate agent exists ────────────────────────────────
            subgraph = subgraphs.get(agent_name)
            if subgraph is None:
                logger.warning("Agent %s not found in subgraphs", agent_name)
                tool_messages.append(ToolMessage(
                    content=f"Error: Agent '{agent_name}' is not available. Available agents: {list(subgraphs.keys())}",
                    tool_call_id=tool_call_id,
                ))
                continue

            # ── Emit agent_started event ─────────────────────────────
            writer({
                "event": "agent_started",
                "trace_id": trace_id,
                "agent": agent_name,
                "message": f"Routed to {agent_name}",
                "data": {
                    "agent": agent_name,
                    "prompt_preview": prompt[:200],
                },
            })

            # ── Build sub-agent initial state ────────────────────────
            sub_state = {
                "user_input": prompt,
                "messages": [HumanMessage(content=prompt)],
                "trace_id": trace_id,
                "workspace_dir": state.get("workspace_dir", ""),
            }

            # ── Build sub-config (injects executors) ─────────────────
            # CRITICAL: use a unique thread_id per sub-agent invocation so
            # that the parent graph's checkpointer does NOT restore stale
            # state from a previous run (which would overwrite the fresh
            # sub_state above and cause orphaned ToolMessage errors).
            sub_thread_id = f"{state.get('session_id', '')}:{agent_name}:{new_id('sub')}"
            sub_config = RunnableConfig(configurable={
                "thread_id": sub_thread_id,
                "settings": settings,
                "executors": executors,
            })

            # ── Run agent subgraph with streaming ────────────────────
            final_answer = ""
            try:
                async for evt in subgraph.astream_events(
                    sub_state, sub_config, version="v2"
                ):
                    kind = evt.get("event", "")

                    # ── Forward custom events to parent SSE stream ──
                    if kind == "on_custom_event":
                        custom_data = evt.get("data")
                        if isinstance(custom_data, dict) and "event" in custom_data:
                            # Override agent name so frontend attributes correctly
                            if "agent" not in custom_data:
                                custom_data["agent"] = agent_name
                            writer(custom_data)

                    # ── Forward LLM token streaming ──────────────────
                    elif kind == "on_chat_model_stream":
                        chunk = evt.get("data", {}).get("chunk")
                        if chunk is None:
                            continue
                        content = getattr(chunk, "content", None)
                        if not content:
                            continue
                        if isinstance(content, str):
                            text = content
                        elif isinstance(content, list):
                            text = "".join(
                                c.get("text", "") if isinstance(c, dict) else str(c)
                                for c in content
                            )
                        else:
                            continue
                        if not text:
                            continue
                        final_answer += text
                        writer({
                            "event": "answer_delta",
                            "trace_id": trace_id,
                            "agent": agent_name,
                            "message": text,
                            "data": {"delta": text},
                        })

                    # ── Capture final state from graph end ───────────
                    elif kind == "on_chain_end":
                        output = evt.get("data", {}).get("output", {})
                        if isinstance(output, dict) and "messages" in output:
                            extracted = _extract_final_answer(output["messages"])
                            if extracted:
                                final_answer = extracted

            except Exception as exc:
                logger.exception(
                    "Agent %s execution failed for trace %s", agent_name, trace_id
                )
                final_answer = f"Agent execution failed: {type(exc).__name__}: {exc}"

            # ── Fallback: try state extraction if no streaming answer ─
            if not final_answer:
                final_answer = "(Agent completed but returned no content)"

            # ── Truncate if needed ───────────────────────────────────
            if len(final_answer) > MAX_RESULT_CHARS:
                final_answer = (
                    final_answer[:MAX_RESULT_CHARS]
                    + f"\n...(truncated, {len(final_answer) - MAX_RESULT_CHARS} more chars)"
                )

            logger.info(
                "Agent %s finished: %d chars", agent_name, len(final_answer)
            )

            # ── Return ToolMessage to supervisor ─────────────────────
            tool_messages.append(ToolMessage(
                content=final_answer,
                tool_call_id=tool_call_id,
            ))

        # ── Signal supervisor has resumed control ─────────────────
        # This lets the SSE adapter switch current_agent back to
        # "supervisor" so its final-answer streaming is shown.
        writer({
            "event": "supervisor_resumed",
            "trace_id": trace_id,
            "agent": "supervisor",
            "message": "Supervisor is analyzing results",
        })

        return {"messages": tool_messages}

    return agent_dispatcher_node
