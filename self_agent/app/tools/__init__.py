"""Tool implementations and executor for Programming Agent.

Each tool is an async Python function registered in the ToolExecutor.
Tools are the L4 atomic layer — single responsibility, stateless, input → output.
"""

from self_agent.app.tools.base import ToolExecutor
from self_agent.app.tools.git_tools import register_git_tools

__all__ = ["ToolExecutor", "register_git_tools"]
