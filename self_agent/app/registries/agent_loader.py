"""Agent loader: scans .agents/ directory for agent definitions, skills, and MCP configs.

This module replaces the hardcoded _seed() methods in AgentRegistry and SkillRegistry
with filesystem-driven discovery. Each agent lives in its own directory:

    .agents/{name}/
    ├── agent.yml          # AgentDefinition fields
    ├── agent.py           # Agent class (optional, can fall back to package)
    ├── tools/             # Tool modules (each exports a register() function)
    ├── skills/            # Skill YAML definitions
    └── mcp.yml            # MCP server configurations
"""

import importlib.util
import logging
from pathlib import Path
from typing import Any

import yaml

from self_agent.app.core.models import (
    AgentDefinition,
    PermissionLevel,
    SkillDefinition,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


class AgentLoader:
    """Scans the .agents/ directory and loads all agent-related configuration.

    The loader reads YAML files for lightweight metadata (agents, skills, MCP)
    and uses importlib to dynamically load Python tool modules and agent classes.
    """

    def __init__(self, agents_dir: str, workspace_dir: str) -> None:
        self.agents_dir = Path(agents_dir)
        self.workspace_dir = workspace_dir

    # ── Agent definitions (.agents/*/agent.yml) ─────────────────────────

    def load_agent_definitions(self) -> list[AgentDefinition]:
        """Scan .agents/*/agent.yml and return AgentDefinition objects.

        Only directories that contain an agent.yml are considered valid agents.
        """
        definitions: list[AgentDefinition] = []
        if not self.agents_dir.is_dir():
            logger.warning("Agents directory not found: %s", self.agents_dir)
            return definitions

        for agent_dir in sorted(self.agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            yml_path = agent_dir / "agent.yml"
            if not yml_path.is_file():
                continue

            try:
                data = self._read_yaml(yml_path)
                definition = AgentDefinition(
                    id=data.get("id", f"agent_{agent_dir.name}"),
                    name=data["name"],
                    display_name=data.get("display_name", data["name"]),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                    default_model=data.get("default_model", "deepseek-chat"),
                    workspace_dir=self.workspace_dir,
                    allowed_paths=data.get("allowed_paths", [self.workspace_dir]),
                    permission_level=PermissionLevel(
                        data.get("permission_level", "read")
                    ),
                    equipped_skills=data.get("equipped_skills", []),
                )
                definitions.append(definition)
                logger.info("Loaded agent: %s from %s", definition.name, yml_path)
            except Exception:
                logger.exception("Failed to load agent from %s", yml_path)

        return definitions

    # ── Skill definitions (.agents/*/skills/*.yml) ──────────────────────

    def load_skill_definitions(self) -> list[SkillDefinition]:
        """Scan .agents/*/skills/*.yml and return SkillDefinition objects.

        Each skill YAML is associated with its parent agent directory,
        so owner_agents is automatically populated.
        """
        definitions: list[SkillDefinition] = []
        if not self.agents_dir.is_dir():
            return definitions

        for agent_dir in sorted(self.agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            skills_dir = agent_dir / "skills"
            if not skills_dir.is_dir():
                continue

            agent_name = agent_dir.name
            for skill_yml in sorted(skills_dir.glob("*.yml")):
                try:
                    data = self._read_yaml(skill_yml)
                    definition = SkillDefinition(
                        id=data.get("id", f"skill_{skill_yml.stem}"),
                        name=data["name"],
                        display_name=data.get("display_name", data["name"]),
                        description=data.get("description", ""),
                        category=data.get("category", "general"),
                        version=data.get("version", "0.1.0"),
                        enabled=data.get("enabled", True),
                        triggers=data.get("triggers", []),
                        owner_agents=[agent_name],
                        permission_level=PermissionLevel(
                            data.get("permission_level", "read")
                        ),
                        confirm_required=data.get("confirm_required", False),
                    )
                    definitions.append(definition)
                    logger.debug("Loaded skill: %s from %s", definition.name, skill_yml)
                except Exception:
                    logger.exception("Failed to load skill from %s", skill_yml)

        return definitions

    # ── Tool definitions (derived from .agents/*/tools/ registration) ───

    def discover_tool_modules(self, agent_name: str) -> list[Path]:
        """Find all Python tool modules for a given agent.

        Returns a list of absolute paths to .py files in .agents/{agent_name}/tools/.
        """
        tools_dir = self.agents_dir / agent_name / "tools"
        if not tools_dir.is_dir():
            return []
        return sorted(
            p for p in tools_dir.glob("*.py")
            if p.name != "__init__.py" and not p.name.startswith("_")
        )

    # ── MCP configuration (.agents/*/mcp.yml) ───────────────────────────

    def load_mcp_config(self, agent_name: str) -> dict[str, Any]:
        """Load MCP server configuration for a specific agent.

        Returns a dict with a 'servers' key, or an empty dict if no config exists.
        """
        mcp_path = self.agents_dir / agent_name / "mcp.yml"
        if not mcp_path.is_file():
            return {"servers": []}
        try:
            return self._read_yaml(mcp_path)
        except Exception:
            logger.exception("Failed to load MCP config from %s", mcp_path)
            return {"servers": []}

    # ── Dynamic Python module loading ───────────────────────────────────

    def load_agent_class(self, agent_name: str) -> type | None:
        """Dynamically load the agent class from .agents/{name}/agent.py.

        The module must export a class named {Name}Agent (e.g. ProgrammingAgent).
        Returns the class if found, None otherwise — callers should fall back
        to the package's built-in agent implementations.
        """
        agent_py = self.agents_dir / agent_name / "agent.py"
        if not agent_py.is_file():
            logger.debug("No agent.py found for %s, will use built-in", agent_name)
            return None

        try:
            module_name = f"_agents_{agent_name}"
            spec = importlib.util.spec_from_file_location(module_name, agent_py)
            if spec is None or spec.loader is None:
                logger.warning("Could not create module spec for %s", agent_py)
                return None

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Find the agent class by naming convention
            expected_class = f"{self._to_camel(agent_name)}Agent"
            agent_class = getattr(module, expected_class, None)
            if agent_class is not None:
                logger.info("Loaded agent class %s from %s", expected_class, agent_py)
                return agent_class

            # Fallback: find any class that extends BaseAgent
            from self_agent.app.agents.base import BaseAgent

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseAgent)
                    and attr is not BaseAgent
                ):
                    logger.info("Loaded agent class %s from %s", attr_name, agent_py)
                    return attr

            logger.warning("No BaseAgent subclass found in %s", agent_py)
            return None
        except Exception:
            logger.exception("Failed to load agent class from %s", agent_py)
            return None

    def register_tools_from_dir(
        self, agent_name: str, executor: Any  # ToolExecutor
    ) -> list[str]:
        """Load all tool modules from .agents/{name}/tools/ and register them.

        Each tool module must export a `register(executor: ToolExecutor)` function.
        Returns a list of registered tool names.
        """
        tool_paths = self.discover_tool_modules(agent_name)
        registered: list[str] = []

        for tool_path in tool_paths:
            try:
                module_name = f"_tools_{agent_name}_{tool_path.stem}"
                spec = importlib.util.spec_from_file_location(module_name, tool_path)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                register_fn = getattr(module, "register", None)
                if callable(register_fn):
                    register_fn(executor)
                    registered.append(tool_path.stem)
                    logger.info("Registered tools from %s", tool_path)
                else:
                    logger.warning("No register() function in %s", tool_path)
            except Exception:
                logger.exception("Failed to load tool module %s", tool_path)

        return registered

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        """Read a YAML file and return its contents as a dict."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
        return data

    @staticmethod
    def _to_camel(snake_str: str) -> str:
        """Convert snake_case to PascalCase: 'personal_tools' -> 'PersonalTools'."""
        return "".join(word.capitalize() for word in snake_str.split("_"))
