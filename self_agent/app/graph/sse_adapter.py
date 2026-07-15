"""SSE adapter — maps LangGraph astream_events to frontend ChatEvent protocol.

This module is the bridge between LangGraph's internal event stream and the
existing frontend SSE contract. It wraps graph.astream_events(version="v2")
and translates each event into a ChatEvent that the React frontend already
knows how to render.

Event mapping summary:

    LangGraph Event                  → SSE ChatEvent
    ─────────────────────────────────────────────────────
    (manual, before graph)           → supervisor_started
    on_chain_end (name=supervisor)   → agent_started
    on_custom_event (skill_activated)→ skill_activated
    on_custom_event (tool_started)   → tool_started
    on_custom_event (tool_result)    → tool_result
    on_chat_model_stream             → answer_delta
    (manual, after graph)            → final
    (exception)                      → error
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from self_agent.app.core.config import get_settings
from self_agent.app.core.models import (
    CallLog,
    CallStatus,
    ChatEvent,
    ChatMessage,
    ChatRequest,
    MetricOverview,
    new_id,
    utc_now,
)
from self_agent.app.observability.call_logger import CallLogger
from self_agent.app.runtime.store import InMemoryStore

logger = logging.getLogger(__name__)

# ── Answer chunking (typewriter effect fallback) ─────────────────────

ANSWER_CHUNK_SIZE = 42


async def _chunk_answer(
    text: str,
    trace_id: str,
    agent_name: str | None,
    chunk_size: int = ANSWER_CHUNK_SIZE,
    delay: float = 0.02,
) -> AsyncIterator[ChatEvent]:
    """Yield answer_delta events chunk-by-chunk for typewriter effect."""
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield ChatEvent(
            event="answer_delta",
            trace_id=trace_id,
            agent=agent_name,
            message=chunk,
            data={"delta": chunk},
        )
        await asyncio.sleep(delay)


# ── State helpers ─────────────────────────────────────────────────────

def _extract_final_answer(state: dict) -> str:
    """Extract the agent's final answer from the last AI message in state."""
    messages = state.get("messages", [])
    if not messages:
        return ""
    # Find the last AI message (reversed search)
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "ai":
            content = getattr(msg, "content", "") or ""
            if content:
                # Skip messages that are tool-call-only (no text content)
                tool_calls = getattr(msg, "tool_calls", None) or []
                if not tool_calls or content.strip():
                    return content
    return ""


# ── Event mapping ──────────────────────────────────────────────────────

def _map_langgraph_event(
    evt: dict,
    trace_id: str,
    current_agent: str | None,
) -> ChatEvent | None:
    """Map a single astream_events v2 event to a ChatEvent, or None if ignored.

    Args:
        evt: Raw astream_events v2 event dict.
        trace_id: Request trace id (attached to every outgoing ChatEvent).
        current_agent: Currently executing agent name (set when agent_started
                       is emitted, used to label answer_delta chunks).

    Returns:
        A ChatEvent if this event should be forwarded to the frontend, or None.
    """
    kind = evt.get("event", "")
    name = evt.get("name", "")
    data = evt.get("data", {})

    # ── Custom events dispatched by our nodes ─────────────────────
    # agent_started, tool_started, answer_delta, tool_result, etc.
    # are now emitted by agent_dispatcher_node as custom events.
    if kind == "on_custom_event":
        custom = evt.get("data") or data
        if isinstance(custom, dict) and "event" in custom:
            return ChatEvent(**custom)

    # ── LLM token streaming ───────────────────────────────────────
    # Stream both supervisor and sub-agent tokens. The dispatcher
    # forwards sub-agent streaming as custom events (handled above).
    # Native on_chat_model_stream events come from the supervisor_llm
    # node and are shown when current_agent tracks "supervisor".
    if kind == "on_chat_model_stream":
        if current_agent is None:
            return None
        chunk = data.get("chunk")
        if chunk is None:
            return None
        content = getattr(chunk, "content", None)
        if not content:
            return None
        # content may be a string or a list of content blocks
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        else:
            return None
        if not text:
            return None
        return ChatEvent(
            event="answer_delta",
            trace_id=trace_id,
            agent=current_agent,
            message=text,
            data={"delta": text},
        )

    return None


# ── Main streaming entry point ─────────────────────────────────────────

async def stream_chat_with_langgraph(
    graph,  # compiled LangGraph StateGraph
    initial_state: dict,
    config: RunnableConfig,
    session_id: str,
    request: ChatRequest,
    store: InMemoryStore,  # or SQLiteStore
    call_logger: CallLogger,  # or SQLiteCallLogger
) -> AsyncIterator[ChatEvent]:
    """Stream LangGraph execution as SSE ChatEvents for the frontend.

    This replaces AgentRuntime.stream_chat(). It:
    1. Yields supervisor_started before graph execution.
    2. Runs graph.astream_events(version="v2") and maps events.
    3. Collects answer_delta text chunks (from LLM streaming or manual chunking).
    4. Persists the assistant message and call log.
    5. Yields a final event with the complete answer.

    Args:
        graph: Compiled supervisor graph from build_supervisor_graph().
        initial_state: Dict with messages, trace_id, session_id,
                       workspace_dir, user_input.
        config: RunnableConfig with callbacks and configurable dependencies.
        session_id: Chat session id for message persistence.
        request: Original ChatRequest for logging.
        store: Session/message store (InMemoryStore or SQLiteStore).
        call_logger: Call log store (CallLogger or SQLiteCallLogger).

    Yields:
        ChatEvent objects to be SSE-encoded by the API layer.
    """
    trace_id: str = initial_state.get("trace_id", "")
    if not trace_id:
        trace_id = new_id("trace")
        initial_state["trace_id"] = trace_id

    started_at = utc_now()
    # Start with "supervisor" so its final-answer streaming is captured.
    # The dispatcher will emit agent_started to switch to sub-agents,
    # and supervisor_resumed to switch back.
    current_agent: str | None = "supervisor"
    answer_parts: list[str] = []
    got_streaming_answer = False
    final_state: dict = {}

    # ── Emit supervisor_started ───────────────────────────────────────
    yield ChatEvent(
        event="supervisor_started",
        trace_id=trace_id,
        message="Supervisor is identifying intent",
    )
    await asyncio.sleep(0.05)

    try:
        # ── Run graph with event streaming ──────────────────────────
        async for evt in graph.astream_events(
            initial_state, config, version="v2"
        ):
            # Capture final state from root chain end event
            # The root graph emits on_chain_end with name="LangGraph" (or custom name)
            # containing the full accumulated state.
            if evt.get("event") == "on_chain_end":
                output = evt.get("data", {}).get("output", {})
                if isinstance(output, dict) and "messages" in output:
                    final_state = output

            sse_event = _map_langgraph_event(evt, trace_id, current_agent)
            if sse_event is None:
                continue

            # Track current agent for answer_delta labeling
            if sse_event.event == "agent_started":
                current_agent = sse_event.agent
            elif sse_event.event == "supervisor_resumed":
                current_agent = "supervisor"

            # Collect answer chunks for final event reconstruction
            if sse_event.event == "answer_delta":
                answer_parts.append(sse_event.message)
                got_streaming_answer = True

            yield sse_event

        # ── Build final answer ─────────────────────────────────────
        if got_streaming_answer and answer_parts:
            final_answer = "".join(answer_parts)
        else:
            # Extract from state captured during astream_events
            final_answer = _extract_final_answer(final_state)

        # If still no answer, chunk it from the extracted answer
        if not got_streaming_answer and final_answer:
            async for delta in _chunk_answer(
                final_answer, trace_id, current_agent
            ):
                yield delta

        if not final_answer:
            final_answer = "Agent completed but returned no content. Please retry."

        # ── Persist assistant message ──────────────────────────────
        store.add_message(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=final_answer,
                agent_name=current_agent,
                trace_id=trace_id,
            )
        )

        # ── Log success ────────────────────────────────────────────
        finished_at = utc_now()
        call_logger.add(
            CallLog(
                trace_id=trace_id,
                session_id=session_id,
                entrypoint=request.entrypoint,
                agent_name=current_agent,
                status=CallStatus.success,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=call_logger.latency_ms(started_at, finished_at),
                input_summary=request.content[:120],
                output_summary=final_answer[:160],
                input_tokens=max(1, len(request.content) // 4),
                output_tokens=max(1, len(final_answer) // 4),
            )
        )

        # ── Emit final event ───────────────────────────────────────
        yield ChatEvent(
            event="final",
            trace_id=trace_id,
            agent=current_agent,
            message=final_answer,
            data={
                "message": final_answer,
                "activated_skills": initial_state.get("activated_skills", []),
            },
        )

    except Exception as exc:
        logger.exception("Graph execution failed for trace %s", trace_id)
        finished_at = utc_now()
        call_logger.add(
            CallLog(
                trace_id=trace_id,
                session_id=session_id,
                entrypoint=request.entrypoint,
                status=CallStatus.failed,
                started_at=started_at,
                finished_at=finished_at,
                latency_ms=call_logger.latency_ms(started_at, finished_at),
                input_summary=request.content[:120],
                output_summary="",
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        )
        yield ChatEvent(event="error", trace_id=trace_id, message=str(exc))
