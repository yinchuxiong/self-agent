from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Use timezone-aware UTC timestamps for logs and future database persistence."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Generate compact, readable IDs that remain stable across API responses."""
    return f"{prefix}_{uuid4().hex[:16]}"


class PermissionLevel(StrEnum):
    read = "read"
    write = "write"
    execute = "execute"
    external_publish = "external_publish"
    dangerous = "dangerous"


class CallStatus(StrEnum):
    success = "success"
    failed = "failed"
    timeout = "timeout"
    cancelled = "cancelled"
    permission_denied = "permission_denied"


class AgentDefinition(BaseModel):
    """Runtime-facing Agent configuration shown in the UI and used by Supervisor."""

    id: str
    name: str
    display_name: str
    description: str
    enabled: bool = True
    default_model: str = "deepseek-chat"
    workspace_dir: str
    allowed_paths: list[str] = Field(default_factory=list)
    permission_level: PermissionLevel = PermissionLevel.read
    equipped_skills: list[str] = Field(default_factory=list)
    status: str = "idle"


class SkillDefinition(BaseModel):
    """Skill metadata. The first version is registry-driven, later versions can load YAML."""

    id: str
    name: str
    display_name: str
    description: str
    category: str
    version: str = "0.1.0"
    enabled: bool = True
    triggers: list[str] = Field(default_factory=list)
    owner_agents: list[str] = Field(default_factory=list)
    permission_level: PermissionLevel = PermissionLevel.read
    confirm_required: bool = False


class ToolDefinition(BaseModel):
    """Tool metadata only; actual execution is intentionally deferred to ToolExecutor."""

    id: str
    name: str
    display_name: str
    description: str
    owner_skill: str
    permission_level: PermissionLevel = PermissionLevel.read
    timeout_seconds: int = 30
    enabled: bool = True
    parameter_schema: dict[str, Any] = Field(default_factory=dict)


class ChatSession(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sess"))
    title: str = "新会话"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    session_id: str
    role: str
    content: str
    agent_name: str | None = None
    trace_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ChatRequest(BaseModel):
    content: str
    agent_name: str | None = None
    entrypoint: str = "web_ui"


class ChatEvent(BaseModel):
    """SSE event payload shared by backend streaming and frontend event rendering."""

    event: str
    trace_id: str
    message: str
    agent: str | None = None
    skill: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class CallLog(BaseModel):
    """Structured observability record for one user request or tool/workflow call."""

    id: str = Field(default_factory=lambda: new_id("call"))
    trace_id: str
    session_id: str | None = None
    entrypoint: str = "web_ui"
    agent_name: str | None = None
    skill_name: str | None = None
    tool_name: str | None = None
    workflow_name: str | None = None
    workspace_dir: str | None = None
    status: CallStatus
    started_at: datetime
    finished_at: datetime
    latency_ms: int
    input_summary: str
    output_summary: str
    error_type: str | None = None
    error_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_estimate: float = 0
    created_at: datetime = Field(default_factory=utc_now)


class MetricOverview(BaseModel):
    total_calls: int
    success_rate: float
    failed_calls: int
    avg_latency_ms: int
    p95_latency_ms: int
    token_usage: int
    cost_estimate: float
    recent_errors: list[CallLog]
