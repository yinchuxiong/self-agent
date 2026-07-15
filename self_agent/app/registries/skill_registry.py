"""Skill and Tool registry: scans .agents/*/skills/*.yml for skill definitions.

Skills are loaded from the filesystem at startup. Tool metadata is populated
at runtime when agent tools are registered into their ToolExecutor — the
ToolSpec is converted to a ToolDefinition for API/UI consumption.
"""

import logging
from pathlib import Path

from self_agent.app.core.models import PermissionLevel, SkillDefinition, ToolDefinition
from self_agent.app.registries.agent_loader import AgentLoader

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Filesystem-driven Skill and Tool registry.

    Skills are discovered from .agents/*/skills/*.yml.
    Tool metadata is registered at runtime from ToolSpec objects.
    """

    def __init__(self, agents_dir: str | None = None) -> None:
        # Resolve agents_dir: use provided path or default to project root .agents/
        # __file__ = self_agent/app/registries/skill_registry.py → ×4 parent = project root
        if agents_dir is None:
            agents_dir = str(Path(__file__).resolve().parent.parent.parent.parent / ".agents")

        self._loader = AgentLoader(
            agents_dir=agents_dir,
            workspace_dir="",  # not needed for skill loading
        )
        self._skills: dict[str, SkillDefinition] = {}
        self._tools: dict[str, ToolDefinition] = {}
        self._seed()

    def _seed(self) -> None:
        """Load skills and tool metadata from .agents/ directory."""
        for skill in self._loader.load_skill_definitions():
            self._skills[skill.name] = skill

        # Eagerly scan tool directories to populate tool metadata for API/UI
        self._preload_tool_metadata()

    def _preload_tool_metadata(self) -> None:
        """Scan .agents/*/tools/*.py and extract ToolSpec metadata at startup.

        Uses a lightweight approach: imports each tool module, captures ToolSpec
        objects created by register(), and registers their metadata without
        keeping the executor alive.
        """
        from self_agent.app.tools.base import ToolExecutor, ToolSpec

        # Find all agent directories that have agent.yml
        agents_dir = Path(self._loader.agents_dir)
        if not agents_dir.is_dir():
            return

        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir() or not (agent_dir / "agent.yml").is_file():
                continue

            agent_name = agent_dir.name
            tool_paths = self._loader.discover_tool_modules(agent_name)
            if not tool_paths:
                continue

            # Create a temporary executor to capture ToolSpec registrations
            temp_executor = ToolExecutor(workspace_dir="")
            registered = self._loader.register_tools_from_dir(agent_name, temp_executor)

            for tool_name in temp_executor.tool_names():
                spec = temp_executor.get(tool_name)
                if spec is not None:
                    self.register_tool_metadata(
                        name=spec.name,
                        display_name=spec.display_name,
                        description=spec.description,
                        owner_skill=agent_name,
                        permission_level=spec.permission_level,
                        timeout_seconds=spec.timeout_seconds,
                        parameter_schema=spec.parameter_schema,
                    )

    # ── Skill API ───────────────────────────────────────────────────────

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def match_skills(self, agent_name: str, text: str) -> list[SkillDefinition]:
        """Match enabled skills by trigger keywords for the given agent."""
        normalized = text.lower()
        matched: list[SkillDefinition] = []
        for skill in self._skills.values():
            if not skill.enabled or agent_name not in skill.owner_agents:
                continue
            if any(trigger.lower() in normalized for trigger in skill.triggers):
                matched.append(skill)
        return matched

    # ── Tool metadata API ───────────────────────────────────────────────

    def register_tool_metadata(
        self,
        name: str,
        display_name: str,
        description: str,
        owner_skill: str,
        permission_level: str = "read",
        timeout_seconds: int = 30,
        parameter_schema: dict | None = None,
    ) -> ToolDefinition:
        """Register tool metadata from a ToolSpec at runtime.

        Called when tools are loaded from .agents/{agent}/tools/.
        """
        tool_def = ToolDefinition(
            id=f"tool_{name}",
            name=name,
            display_name=display_name,
            description=description,
            owner_skill=owner_skill,
            permission_level=PermissionLevel(permission_level),
            timeout_seconds=timeout_seconds,
            parameter_schema=parameter_schema or {},
        )
        self._tools[name] = tool_def
        return tool_def

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)
