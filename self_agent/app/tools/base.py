"""ToolExecutor: safe tool execution with workspace isolation and output management."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Maximum output characters before truncation ──────────────────────────
# Prevents a single tool result from overwhelming the LLM context window.
MAX_OUTPUT_CHARS = 4000


@dataclass
class ToolResult:
    """Structured result from a tool execution."""

    tool_name: str
    success: bool
    output: str
    error: str | None = None
    truncated: bool = False


@dataclass
class ToolSpec:
    """Complete tool definition: metadata for the LLM + the actual function."""

    name: str
    display_name: str
    description: str
    function: Callable[..., Any]
    # OpenAI-compatible JSON Schema for function parameters.
    # Example: {"type": "object", "properties": {...}, "required": [...]}
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    permission_level: str = "read"
    timeout_seconds: int = 30


class ToolExecutor:
    """Register and safely execute tool functions.

    Responsibilities:
      - Tool lookup by name
      - Workspace directory constraint enforcement
      - Timeout guard
      - Output truncation
      - Error isolation (one tool failure doesn't crash the agent)
    """

    def __init__(self, workspace_dir: str, allowed_paths: list[str] | None = None) -> None:
        self.workspace_dir = str(Path(workspace_dir).resolve())
        self.allowed_paths = [str(Path(p).resolve()) for p in (allowed_paths or [])]
        self._tools: dict[str, ToolSpec] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, spec: ToolSpec) -> None:
        """Register a tool function with its metadata."""
        self._tools[spec.name] = spec
        logger.debug("Tool registered: %s (permission=%s)", spec.name, spec.permission_level)

    def get(self, name: str) -> ToolSpec | None:
        """Look up a tool by name. Returns None if not found."""
        return self._tools.get(name)

    def list_specs(self) -> list[ToolSpec]:
        """Return all registered tool specs."""
        return list(self._tools.values())

    # ── OpenAI-compatible tool definitions ────────────────────────────────

    def openai_tool_definitions(self) -> list[dict[str, Any]]:
        """Build tool definitions in OpenAI-compatible format for the Chat Completions API.

        Returns a list of {"type": "function", "function": {...}} dicts.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameter_schema or {"type": "object", "properties": {}},
                },
            }
            for spec in self._tools.values()
        ]

    # ── Execution ─────────────────────────────────────────────────────────

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Execute a registered tool with arguments.

        Args:
            name: Tool name (must be registered).
            arguments: Keyword arguments forwarded to the tool function.

        Returns:
            ToolResult with success/failure status and output.
        """
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(tool_name=name, success=False, output="", error=f"Unknown tool: {name}")

        try:
            # Always inject workspace_dir so tools operate on the right directory.
            merged = {"workspace_dir": self.workspace_dir, **arguments}
            coro = spec.function(**merged)
            result_value = await asyncio.wait_for(asyncio.ensure_future(coro), timeout=spec.timeout_seconds)
            output = str(result_value) if result_value is not None else "(no output)"
            truncated = False
            if len(output) > MAX_OUTPUT_CHARS:
                output = output[:MAX_OUTPUT_CHARS] + f"\n\n...[truncated {len(output) - MAX_OUTPUT_CHARS} chars]"
                truncated = True
            return ToolResult(
                tool_name=name, success=True, output=output, truncated=truncated
            )
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=name, success=False, output="",
                error=f"Tool {name} timed out after {spec.timeout_seconds}s",
            )
        except Exception as exc:
            logger.exception("Tool %s failed: %s", name, exc)
            return ToolResult(
                tool_name=name, success=False, output="", error=str(exc),
            )

    def tool_names(self) -> list[str]:
        """Return registered tool names (for logging / SSE events)."""
        return list(self._tools.keys())
