"""Tool execution node — executes tool calls from the LLM response.

Replaces the inline tool-calling loop in `ProgrammingAgent.run()` with a
LangGraph node that:
1. Extracts tool_calls from the last AIMessage in state.
2. Calls executor.execute() for each tool.
3. Emits tool_started / tool_result custom events for SSE streaming.
4. Returns ToolMessage objects that LangGraph appends to messages.
"""

import asyncio
import logging
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer

from self_agent.app.core.models import AgentDefinition
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.tools.base import ToolExecutor

logger = logging.getLogger(__name__)


def make_tool_node(
    agent_def: AgentDefinition,
    agent_loader: AgentLoader,
):
    """Return an async tool execution node for the given agent.

    The node reads the last AIMessage from state, extracts tool_calls,
    executes each via the ToolExecutor, and returns ToolMessage results.

    Args:
        agent_def: The agent definition (provides agent name for logging).
        agent_loader: Passed through from the graph builder (not used
                      directly here — executors come from config.configurable).
    """

    agent_name = agent_def.name

    async def tool_node(state: dict, config: RunnableConfig) -> dict:
        configurable = config.get("configurable", {})
        executors: dict[str, ToolExecutor] = configurable.get("executors", {})
        executor = executors.get(agent_name)

        if not executor:
            logger.warning("Tool node [%s]: no executor configured", agent_name)
            return {"messages": []}

        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_msg = messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None) or []
        if not tool_calls:
            return {"messages": []}

        trace_id: str = state.get("trace_id", "")
        writer = get_stream_writer()

        tool_messages: list[ToolMessage] = []

        for tc in tool_calls:
            tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
            tool_args = (
                tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
            )
            tool_call_id = (
                tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
            )

            # ── Emit tool_started event ─────────────────────────────
            writer(
                {
                    "event": "tool_started",
                    "trace_id": trace_id,
                    "agent": agent_name,
                    "message": f"\U0001f527 调用工具: {tool_name}",
                    "data": {"tool": tool_name, "arguments": tool_args},
                }
            )
            await asyncio.sleep(0.02)

            # ── Execute tool ────────────────────────────────────────
            result = await executor.execute(tool_name, tool_args)

            output_summary = (
                result.output[:200] + "..."
                if len(result.output) > 200
                else result.output
            )

            # ── Emit tool_result event ──────────────────────────────
            writer(
                {
                    "event": "tool_result",
                    "trace_id": trace_id,
                    "agent": agent_name,
                    "message": (
                        f"✅ {tool_name} 完成"
                        if result.success
                        else f"❌ {tool_name} 失败: {result.error}"
                    ),
                    "data": {
                        "tool": tool_name,
                        "success": result.success,
                        "error": result.error,
                        "summary": output_summary,
                    },
                }
            )
            await asyncio.sleep(0.02)

            # ── Build ToolMessage ───────────────────────────────────
            tool_messages.append(
                ToolMessage(
                    content=result.output if result.success else f"Error: {result.error}",
                    tool_call_id=tool_call_id,
                )
            )

        return {"messages": tool_messages}

    return tool_node
