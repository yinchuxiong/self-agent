"""Shell execution tool for Programming Agent.

Single-file tool: sandbox validation + subprocess execution + ToolSpec registration.
Replaces individual git_status / git_diff / git_log wrappers with one general
execute_command tool — the LLM uses its own CLI knowledge to craft commands;
the sandbox enforces safety and path confinement.
"""

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass

from self_agent.app.tools.base import ToolExecutor, ToolSpec

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Sandbox: security policy
# ═══════════════════════════════════════════════════════════════════════════

# Blocked patterns (case-insensitive regex)
BLOCKED_PATTERNS: list[str] = [
    # Destructive filesystem
    r"\brm\s+-rf\b",
    r"\brm\s+-r\s+/",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r">\s*/dev/",
    # Privilege escalation
    r"\bsudo\b",
    r"\bsu\s+-",
    # Git destructive
    r"git\s+push\s+.*(-f|--force)",
    r"git\s+reset\s+--hard",
    r"\bgit\s+clean\s+-[fdx]",
    # Network hazards
    r"\bcurl\b.*\|\s*(ba)?sh",
    r"\bwget\b.*\|\s*(ba)?sh",
    # Path traversal
    r"\.\.\/\.\.\/",
    r"\bchmod\s+777\b",
]

MAX_TIMEOUT = 60       # seconds
MAX_OUTPUT = 8000      # characters


@dataclass
class ShellResult:
    """Structured result from shell execution."""
    success: bool
    output: str
    stderr: str = ""
    exit_code: int = 0
    truncated: bool = False
    blocked: bool = False
    block_reason: str = ""


def _is_within(path: str, workspace_dir: str) -> bool:
    """Check if *path* is inside *workspace_dir* (or equal to it)."""
    try:
        resolved = os.path.normpath(os.path.abspath(path)).lower()
        wd = os.path.normpath(os.path.abspath(workspace_dir)).lower()
        return resolved == wd or resolved.startswith(wd + os.sep)
    except (ValueError, OSError):
        return False


def _extract_external_paths(command: str, workspace_dir: str) -> list[str]:
    """Find absolute paths in *command* that are outside *workspace_dir*."""
    violations: list[str] = []

    # Windows absolute paths: C:\..., D:\path\...
    for match in re.finditer(r'\b([A-Za-z]:[/\\][^\s"\';&|`]*)', command):
        path = match.group(1)
        if os.path.isabs(path) and not _is_within(path, workspace_dir):
            violations.append(path)

    # Unix-style absolute paths (common prefixes)
    for match in re.finditer(
        r'(?<![A-Za-z])/(?:home|etc|tmp|var|usr|opt|root|sys|proc|dev|bin|sbin|mnt|media)/[^\s"\';&|`]*',
        command,
    ):
        path = match.group(0)
        if os.path.isabs(path) and not _is_within(path, workspace_dir):
            violations.append(path)

    return violations


def validate_command(command: str, workspace_dir: str) -> str | None:
    """Validate a command before execution.  Returns None if OK, else error string."""
    # Gate 1: blocklist
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            logger.warning("Shell blocked by '%s': %.120s", pattern, command)
            return f"Command blocked (matches: {pattern})"

    # Gate 2: git escape vectors
    for flag in ("--git-dir", "--work-tree"):
        m = re.search(rf'{flag}[= ]+([^\s"\';&|`]+)', command)
        if m:
            path = m.group(1).strip("'\"")
            if os.path.isabs(path) and not _is_within(path, workspace_dir):
                return f"git {flag} escapes workspace: {path}"

    m = re.search(r'\bgit\s+-C\s+([^\s"\';&|`]+)', command)
    if m:
        path = m.group(1).strip("'\"")
        if os.path.isabs(path) and not _is_within(path, workspace_dir):
            return f"git -C escapes workspace: {path}"

    # Gate 3: absolute path confinement
    violations = _extract_external_paths(command, workspace_dir)
    if violations:
        return f"Command references paths outside workspace: {', '.join(violations[:3])}"

    return None


async def run_command(command: str, workspace_dir: str, timeout: int = 30) -> ShellResult:
    """Validate and execute a shell command in *workspace_dir*."""
    rejection = validate_command(command, workspace_dir)
    if rejection:
        return ShellResult(success=False, output=rejection, blocked=True, block_reason=rejection)

    actual_timeout = min(timeout, MAX_TIMEOUT)

    logger.debug("Shell exec (timeout=%ds): %.100s", actual_timeout, command)
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            command,
            shell=True,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=actual_timeout,
        )
    except subprocess.TimeoutExpired:
        return ShellResult(success=False, output=f"Command timed out ({actual_timeout}s)", exit_code=-1)
    except Exception as exc:
        logger.exception("Shell exec error: %s", exc)
        return ShellResult(success=False, output=f"Command error: {exc}", exit_code=-1)

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    truncated = False

    if len(stdout) > MAX_OUTPUT:
        stdout = stdout[:MAX_OUTPUT] + f"\n\n... [truncated, original length {len(stdout)} chars]"
        truncated = True

    if proc.returncode == 0:
        return ShellResult(success=True, output=stdout or "(no output)", stderr=stderr, truncated=truncated)
    else:
        return ShellResult(
            success=False,
            output=f"Command failed (exit: {proc.returncode})\n{stderr or stdout}",
            stderr=stderr or stdout,
            exit_code=proc.returncode,
            truncated=truncated,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Tool: execute_command
# ═══════════════════════════════════════════════════════════════════════════

EXECUTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": (
                "Shell command to execute in the sandboxed workspace directory. "
                "Supports git (status/diff/log/branch/show/etc.), pip/npm/poetry "
                "(package management), python/node (script execution), "
                "ls/cat/grep/find (file browsing). "
                "Dangerous commands (rm -rf, sudo, git push -f, git reset --hard, "
                "curl|sh) are blocked by the sandbox."
            ),
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default 30, max 60)",
        },
    },
    "required": ["command"],
}


async def execute_command(workspace_dir: str, command: str, timeout: int = 30) -> str:
    """Execute a sandboxed shell command.

    The sandbox enforces:
      - Blocklist filtering (no rm -rf, sudo, force push, curl|sh, etc.)
      - Git escape prevention (--git-dir / -C / --work-tree must stay in workspace)
      - Path confinement (no references to /etc, /home, C:\\Windows, ...)
      - Timeout clamp (max 60s) and output truncation (max 8000 chars)
    """
    result = await run_command(command, workspace_dir, timeout)
    if result.blocked:
        return f"[SANDBOX BLOCKED] {result.block_reason}"
    if result.truncated:
        return result.output  # already contains truncation note
    return result.output


def register(executor: ToolExecutor) -> None:
    """Register execute_command as the primary programming tool."""
    executor.register(
        ToolSpec(
            name="execute_command",
            display_name="Execute Command",
            description=(
                "Execute a shell command in the sandboxed workspace directory. "
                "Use this for ALL git operations, package management, script "
                "execution, and file browsing. Use your own CLI knowledge to "
                "construct the right command — the sandbox will validate safety "
                "automatically. "
                "Examples: git status --short -b / git log --oneline -n20 / "
                "git diff -- src/main.py / pip list / python --version"
            ),
            function=execute_command,
            parameter_schema=EXECUTE_SCHEMA,
            permission_level="execute",
            timeout_seconds=60,
        )
    )
