"""OrchestrationState — shared state schema flowing through all graph nodes.

Uses LangGraph's ``add_messages`` reducer so each node **appends** messages
rather than replacing the entire list.  Without this reducer a node that
returns ``{"messages": [ToolMessage(...)]}`` would wipe out the preceding
``AIMessage(tool_calls=[...])`` and cause the LLM provider to reject the
request with:

    "Messages with role 'tool' must be a response to a preceding
     message with 'tool_calls'"
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from langchain_core.messages import BaseMessage


class OrchestrationState(TypedDict, total=False):
    """Shared state for the full orchestration graph (supervisor + sub-agents).

    ``total=False`` means every key is optional — a node only returns the
    keys it wants to update.  LangGraph merges partial returns into the
    accumulated state.

    The **messages** key uses the ``add_messages`` reducer so that each
    node appends its messages (SystemMessage, HumanMessage, AIMessage,
    ToolMessage) to the existing list instead of replacing it.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    """Accumulated chat history.  Nodes append, never replace."""

    trace_id: str
    """Request-level tracing id (e.g. "trace_abcdef1234567890")."""

    session_id: str
    """Chat session id."""

    workspace_dir: str
    """Resolved workspace directory for this request."""

    user_input: str
    """Original user text (preserved for skill matching & logging)."""

    activated_skills: list[str]
    """Skill names matched by the skill matcher node."""

    final_answer: str
    """Agent's final text response (set when ReAct loop ends)."""

    error: str | None
    """Error message if a node fails."""
