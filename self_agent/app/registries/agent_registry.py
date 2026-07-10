from collections.abc import Iterable

from self_agent.app.core.models import AgentDefinition, PermissionLevel


class AgentRegistry:
    """In-memory Agent registry for M1.

    The API shape mirrors the future database-backed registry so persistence can replace
    this class without changing callers.
    """

    def __init__(self, workspace_dir: str) -> None:
        self._agents: dict[str, AgentDefinition] = {}
        self._seed(workspace_dir)

    def _seed(self, workspace_dir: str) -> None:
        # Built-in agents from the technical plan. They give the UI useful data immediately.
        agents = [
            AgentDefinition(
                id="agent_supervisor",
                name="supervisor",
                display_name="Supervisor Agent",
                description="负责意图识别、任务路由和结果聚合。",
                workspace_dir=workspace_dir,
                allowed_paths=[workspace_dir],
                permission_level=PermissionLevel.read,
                equipped_skills=[],
            ),
            AgentDefinition(
                id="agent_programming",
                name="programming",
                display_name="Programming Agent",
                description="处理代码、Git、仓库健康、代码审查和依赖相关任务。",
                workspace_dir=workspace_dir,
                allowed_paths=[workspace_dir],
                permission_level=PermissionLevel.execute,
                equipped_skills=["git-manager", "code-reviewer", "repo-doctor"],
            ),
            AgentDefinition(
                id="agent_personal_tools",
                name="personal_tools",
                display_name="Personal Tools Agent",
                description="处理文件、PDF、Excel、JSON、文本转换和轻量数据加工。",
                workspace_dir=workspace_dir,
                allowed_paths=[workspace_dir],
                permission_level=PermissionLevel.write,
                equipped_skills=["json-master", "format-shifter", "pdf-master"],
            ),
            AgentDefinition(
                id="agent_work",
                name="work",
                display_name="Work Agent",
                description="处理日报、会议纪要、任务追踪和飞书发布前的内容准备。",
                workspace_dir=workspace_dir,
                allowed_paths=[workspace_dir],
                permission_level=PermissionLevel.external_publish,
                equipped_skills=["daily-reporter", "task-tracker", "feishu-publisher"],
            ),
            AgentDefinition(
                id="agent_scheduler",
                name="scheduler",
                display_name="Scheduler Agent",
                description="管理提醒、周期任务和 Workflow 定时触发。",
                workspace_dir=workspace_dir,
                allowed_paths=[workspace_dir],
                permission_level=PermissionLevel.write,
                equipped_skills=["reminder", "cron-master", "schedule-auditor"],
            ),
        ]
        self._agents = {agent.name: agent for agent in agents}

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
