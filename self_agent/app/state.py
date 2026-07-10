from self_agent.app.core.config import get_settings
from self_agent.app.observability.call_logger import CallLogger, SQLiteCallLogger
from self_agent.app.registries.agent_registry import AgentRegistry
from self_agent.app.registries.skill_registry import SkillRegistry
from self_agent.app.runtime.agent_runtime import AgentRuntime
from self_agent.app.runtime.store import InMemoryStore, SQLiteStore


class AppState:
    """Application singleton for the MVP.

    Later milestones can replace individual services with database-backed or distributed
    implementations while keeping router dependencies stable.
    """

    def __init__(self) -> None:
        settings = get_settings()
        sqlite_enabled = settings.database_url.startswith(("sqlite:///", "sqlite+aiosqlite:///"))
        self.store = SQLiteStore(settings.database_url) if sqlite_enabled else InMemoryStore()
        self.agent_registry = AgentRegistry(settings.default_workspace_dir)
        self.skill_registry = SkillRegistry()
        self.call_logger = (
            SQLiteCallLogger(settings.database_url) if sqlite_enabled else CallLogger()
        )
        self.runtime = AgentRuntime(
            store=self.store,
            agent_registry=self.agent_registry,
            skill_registry=self.skill_registry,
            call_logger=self.call_logger,
        )

    def close(self) -> None:
        for service in (self.store, self.call_logger):
            close = getattr(service, "close", None)
            if close is not None:
                close()


state = AppState()
