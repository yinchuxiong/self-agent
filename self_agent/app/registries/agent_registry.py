"""Agent registry: scans .agents/ directory for agent definitions.

The registry discovers agents from the filesystem. Each agent lives in its own
directory under .agents/{name}/ with an agent.yml config file.

Supervisor is always available as a built-in agent (it's infrastructure, not a
domain agent directory).
"""

from collections.abc import Iterable
from pathlib import Path

from self_agent.app.core.models import AgentDefinition, PermissionLevel
from self_agent.app.registries.agent_loader import AgentLoader


class AgentRegistry:
    """Filesystem-driven Agent registry.

    Scans .agents/*/agent.yml at startup. Supervisor is injected as a built-in
    since it's framework infrastructure rather than a domain agent.
    """

    def __init__(self, workspace_dir: str, agents_dir: str | None = None) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._loader = AgentLoader(
            agents_dir=agents_dir or str(Path(workspace_dir) / ".agents"),
            workspace_dir=workspace_dir,
        )
        self._seed()

    def _seed(self) -> None:
        """Load agents from .agents/ directory, then add built-in supervisor."""
        # Load domain agents from the filesystem
        for definition in self._loader.load_agent_definitions():
            self._agents[definition.name] = definition

        # Always add supervisor as a built-in (it routes to domain agents)
        if "supervisor" not in self._agents:
            self._agents["supervisor"] = AgentDefinition(
                id="agent_supervisor",
                name="supervisor",
                display_name="Supervisor Agent",
                description="负责意图识别、任务路由和结果聚合。",
                workspace_dir=self._loader.workspace_dir,
                allowed_paths=[self._loader.workspace_dir],
                permission_level=PermissionLevel.read,
                equipped_skills=[],
            )

    # ── Public API ──────────────────────────────────────────────────────

    def list(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def names(self) -> Iterable[str]:
        return self._agents.keys()

    def get(self, name: str) -> AgentDefinition:
        if name not in self._agents:
            raise KeyError(f"Unknown agent: {name}")
        return self._agents[name]

    def set_enabled(self, name: str, enabled: bool) -> AgentDefinition:
        agent = self.get(name)
        agent.enabled = enabled
        agent.status = "idle" if enabled else "disabled"
        return agent
