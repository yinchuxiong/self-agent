"""Git tool implementations for Programming Agent.

Each function is async and accepts workspace_dir as its first parameter (injected by ToolExecutor).
All commands run via subprocess with timeout and are scoped to the workspace directory.
"""

import asyncio
import subprocess

from self_agent.app.tools.base import ToolExecutor, ToolSpec

# ── Tool parameter schemas (OpenAI-compatible JSON Schema) ────────────────

GIT_STATUS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "include_untracked": {
            "type": "boolean",
            "description": "是否包含未跟踪的文件，默认 true",
        },
    },
}

GIT_DIFF_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "staged": {
            "type": "boolean",
            "description": "为 true 时查看暂存区差异（git diff --staged），默认 false 查看工作区差异",
        },
        "target": {
            "type": "string",
            "description": "可选，指定文件路径或 commit hash 来限制差异范围",
        },
    },
}

GIT_LOG_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "count": {
            "type": "integer",
            "description": "返回的提交记录数量，默认 20",
        },
        "author": {
            "type": "string",
            "description": "可选，按作者过滤",
        },
        "since": {
            "type": "string",
            "description": "可选，起始日期，如 '2026-07-01' 或 'today'",
        },
    },
}

# ── Helper ────────────────────────────────────────────────────────────────


async def _run_git(workspace_dir: str, args: list[str], timeout: int = 15) -> str:
    """Run a git command and return its stdout (or stderr on failure)."""
    cmd = ["git"] + args
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return (proc.stdout.strip() or proc.stderr.strip() or "(no output)")


# ── Tool functions ────────────────────────────────────────────────────────


async def git_status(workspace_dir: str, include_untracked: bool = True) -> str:
    """Return current branch and working-tree status."""
    args = ["status", "--short", "-b"]
    if not include_untracked:
        args.append("-uno")
    return await _run_git(workspace_dir, args)


async def git_diff(workspace_dir: str, staged: bool = False, target: str = "") -> str:
    """Return working-tree or staged diff as unified diff text."""
    args = ["diff"]
    if staged:
        args.append("--staged")
    if target:
        args.append("--")
        args.append(target)
    return await _run_git(workspace_dir, args, timeout=30)


async def git_log(workspace_dir: str, count: int = 20, author: str = "", since: str = "") -> str:
    """Return recent commit history in one-line format."""
    args = ["log", f"--oneline", f"-n{count}"]
    if author:
        args.append(f"--author={author}")
    if since:
        args.append(f"--since={since}")
    return await _run_git(workspace_dir, args)


# ── Registration helper ───────────────────────────────────────────────────


def register_git_tools(executor: ToolExecutor) -> None:
    """Register all git tools on the given executor."""
    executor.register(
        ToolSpec(
            name="git_status",
            display_name="查看仓库状态",
            description="返回当前分支名和工作区文件状态（修改/新增/删除）。用于了解仓库当前的整体情况。",
            function=git_status,
            parameter_schema=GIT_STATUS_SCHEMA,
            permission_level="read",
        )
    )
    executor.register(
        ToolSpec(
            name="git_diff",
            display_name="查看代码差异",
            description="查看工作区或暂存区的代码差异。不传参数时返回工作区未暂存的改动；staged=true 时返回已暂存的改动。",
            function=git_diff,
            parameter_schema=GIT_DIFF_SCHEMA,
            permission_level="read",
            timeout_seconds=30,
        )
    )
    executor.register(
        ToolSpec(
            name="git_log",
            display_name="查看提交历史",
            description="查看最近的 Git 提交记录，支持按数量和作者过滤。用于了解项目的提交历史。",
            function=git_log,
            parameter_schema=GIT_LOG_SCHEMA,
            permission_level="read",
        )
    )
