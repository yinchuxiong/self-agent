"""Tool infrastructure: executor, spec, and result types.

Actual tool implementations live under .agents/{name}/tools/ — each module
exports a register(executor) function.
"""

from self_agent.app.tools.base import ToolExecutor, ToolResult, ToolSpec

__all__ = ["ToolExecutor", "ToolResult", "ToolSpec"]
