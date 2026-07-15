# ── DEPRECATED ────────────────────────────────────────────────────────────
# AgentRuntime has been replaced by the LangGraph orchestration graph.
# The SSE streaming is now handled by:
#   self_agent/app/graph/sse_adapter.py (stream_chat_with_langgraph)
#   self_agent/app/graph/supervisor_graph.py (build_supervisor_graph)
# This file is preserved for reference and test backward compatibility.
# ───────────────────────────────────────────────────────────────────────────
#
# ── 标准库 ──────────────────────────────────────────────────────────────
import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

# ── Agent 层：各类业务 Agent ───────────────────────────────────────────
from self_agent.app.agents.base import AgentRunResult, BaseAgent
from self_agent.app.agents.supervisor import Supervisor

# ── 配置 ────────────────────────────────────────────────────────────────
from self_agent.app.core.config import get_settings

# ── 核心数据模型 ───────────────────────────────────────────────────────
from self_agent.app.core.models import (
    CallLog,
    CallStatus,
    ChatEvent,
    ChatMessage,
    ChatRequest,
    new_id,
    utc_now,
)

# ── 工具执行器 ─────────────────────────────────────────────────────────
from self_agent.app.tools.base import ToolExecutor

# ── 可观测性与注册表 ──────────────────────────────────────────────────
from self_agent.app.observability.call_logger import CallLogger
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.registries.agent_registry import AgentRegistry
from self_agent.app.registries.skill_registry import SkillRegistry

# ── 存储层 ─────────────────────────────────────────────────────────────
from self_agent.app.runtime.store import InMemoryStore

logger = logging.getLogger(__name__)


class AgentRuntime:
    """Agent 运行时：协调一次请求的完整生命周期。

    职责（按调用顺序）：
    1. 解析会话级工作目录（支持对话中动态切换项目）
    2. 持久化用户消息（即使后续失败也能审计追溯）
    3. 通过 Supervisor 识别意图，路由到对应的业务 Agent
    4. 匹配并激活相关 Skill
    5. 执行 Agent 并流式推送回答（SSE 事件）
    6. 记录调用日志（CallLog）用于统计和排错
    7. 异常时推送错误事件并记录失败日志
    """

    def __init__(
        self,
        store: InMemoryStore,
        agent_registry: AgentRegistry,
        skill_registry: SkillRegistry,
        call_logger: CallLogger,
    ) -> None:
        self.store = store
        self.agent_registry = agent_registry
        self.skill_registry = skill_registry
        self.call_logger = call_logger
        self.supervisor = Supervisor(agent_registry)
        self._settings = get_settings()

        # AgentLoader for dynamic agent class & tool loading
        self._loader = AgentLoader(
            agents_dir=str(Path(self._settings.default_workspace_dir) / ".agents"),
            workspace_dir=self._settings.default_workspace_dir,
        )

    def _resolve_workspace(self, session_id: str, request: ChatRequest) -> str:
        """解析当前请求的工作目录，优先级：
        1. 请求中显式指定的 workspace_dir
        2. 会话已有的 workspace_dir
        3. 全局配置的 default_workspace_dir
        """
        session = self.store.get_session(session_id)
        if request.workspace_dir:
            resolved = str(Path(request.workspace_dir).resolve())
            session.workspace_dir = resolved
            return resolved
        if session.workspace_dir:
            return session.workspace_dir
        return self._settings.default_workspace_dir

    def _agent(self, name: str, workspace_dir: str) -> BaseAgent:
        """根据 Agent 名称动态构建业务 Agent 实例。

        从 .agents/{name}/agent.py 动态加载 Agent 类，
        从 .agents/{name}/tools/ 动态加载工具模块并注入 ToolExecutor。
        """
        definition = self.agent_registry.get(name)
        wd = workspace_dir or definition.workspace_dir

        # ── Dynamic agent class loading ──────────────────────────────
        agent_class = self._loader.load_agent_class(name)
        if agent_class is None:
            raise RuntimeError(
                f"Agent '{name}' not found: .agents/{name}/agent.py does not exist "
                f"or does not export a BaseAgent subclass."
            )

        logger.info("Loaded agent class for: %s", name)

        # ── Build executor and load tools ────────────────────────────
        executor = ToolExecutor(
            workspace_dir=wd,
            allowed_paths=[wd],
        )
        registered = self._loader.register_tools_from_dir(name, executor)

        if registered:
            logger.info("Loaded %d tool modules for agent %s: %s", len(registered), name, registered)
            for tool_name in executor.tool_names():
                spec = executor.get(tool_name)
                if spec is not None:
                    self.skill_registry.register_tool_metadata(
                        name=spec.name,
                        display_name=spec.display_name,
                        description=spec.description,
                        owner_skill=name,
                        permission_level=spec.permission_level,
                        timeout_seconds=spec.timeout_seconds,
                        parameter_schema=spec.parameter_schema,
                    )

        # Try to instantiate with tool_executor first (ProgrammingAgent pattern),
        # then fall back to plain definition-only init (simple agents)
        try:
            return agent_class(definition, executor)
        except TypeError:
            return agent_class(definition)

    async def stream_chat(
        self,
        session_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[ChatEvent]:
        """处理一次聊天请求，通过 SSE 事件流式推送进度给前端。

        这是 AgentRuntime 的核心方法，整个请求生命周期如下：

        ┌─ 1. 初始化：解析工作目录 ────────────────────────────────┐
        │  优先级：请求指定 > 会话已有 > 全局配置                      │
        ├─ 2. 存储用户消息 ─────────────────────────────────────┤
        │  先持久化用户输入，即使后续执行失败也能在历史中查到     │
        ├─ 3. 意图识别 (Supervisor) ────────────────────────────┤
        │  发送 supervisor_started 事件 → 路由到目标 Agent       │
        ├─ 4. 启用检查 ─────────────────────────────────────────┤
        │  检查 Agent 是否 enabled，未启用的抛出 RuntimeError     │
        ├─ 5. Skill 匹配 ───────────────────────────────────────┤
        │  根据 Agent 名称和用户内容匹配 Skill，推送激活事件      │
        ├─ 6. Agent 执行 ───────────────────────────────────────┤
        │  调用 Agent.run() 获取结果，将回答分块流式推送          │
        ├─ 7. 存储助手消息 ─────────────────────────────────────┤
        │  将 Agent 回答持久化到会话存储                          │
        ├─ 8. 记录调用日志 ─────────────────────────────────────┤
        │  写入 CallLog（成功路径），包含耗时、token 估算等       │
        ├─ 9. 推送最终事件 ─────────────────────────────────────┤
        │  final 事件携带完整回答和激活的 Skill 列表              │
        └─ 异常路径 ─────────────────────────────────────────────┘
          任意步骤失败 → 记录失败 CallLog → 推送 error 事件

        返回 AsyncIterator[ChatEvent]，前端通过 SSE 逐条消费。
        """
        # ═══ 1. 初始化 ═══
        trace_id = new_id("trace")
        started_at = utc_now()
        workspace_dir = self._resolve_workspace(session_id, request)

        # ═══ 2. 持久化用户消息 ═══
        self.store.add_message(
            ChatMessage(
                session_id=session_id,
                role="user",
                content=request.content,
                trace_id=trace_id,
            )
        )

        # ═══ 3. Supervisor 开始识别意图 ═══
        yield ChatEvent(
            event="supervisor_started",
            trace_id=trace_id,
            message="Supervisor 正在识别意图",
        )
        await asyncio.sleep(0.05)

        try:
            # ═══ 4. 路由 ═══
            route_decision = await self.supervisor.route(request.content, request.agent_name)
            agent_name = route_decision.agent_name

            # ═══ 5. 启用检查 ═══
            definition = self.agent_registry.get(agent_name)
            if not definition.enabled:
                raise RuntimeError(f"{definition.display_name} 当前已禁用")

            # ═══ 6. Agent 已确定 ═══
            agent_started_message = f"已路由到 {definition.display_name}"
            if route_decision.reason:
                agent_started_message += f"：{route_decision.reason}"
            yield ChatEvent(
                event="agent_started",
                trace_id=trace_id,
                agent=agent_name,
                message=agent_started_message,
                data={
                    "route": {
                        "agent": route_decision.agent_name,
                        "intent": route_decision.intent,
                        "reason": route_decision.reason,
                        "confidence": route_decision.confidence,
                        "source": route_decision.source,
                    }
                },
            )
            await asyncio.sleep(0.05)

            # ═══ 7. Skill 匹配与激活 ═══
            skills = self.skill_registry.match_skills(agent_name, request.content)
            for skill in skills:
                yield ChatEvent(
                    event="skill_activated",
                    trace_id=trace_id,
                    agent=agent_name,
                    skill=skill.name,
                    message=f"激活 {skill.display_name}",
                )
                await asyncio.sleep(0.03)

            # ═══ 8. 执行 Agent ═══
            agent = self._agent(agent_name, workspace_dir)
            result: AgentRunResult | None = None
            async for step in agent.run(request.content, skills):
                if isinstance(step, AgentRunResult):
                    result = step
                elif isinstance(step, ChatEvent):
                    yield step
                    await asyncio.sleep(0.01)

            if result is None:
                result = AgentRunResult(
                    agent=agent_name,
                    answer="Agent 执行完成但未返回结果，请重试。",
                )

            # ═══ 9. 流式推送回答 ═══
            for chunk in _chunk_text(result.answer, 42):
                yield ChatEvent(
                    event="answer_delta",
                    trace_id=trace_id,
                    agent=agent_name,
                    message=chunk,
                    data={"delta": chunk},
                )
                await asyncio.sleep(0.02)

            # ═══ 10. 持久化助手消息 ═══
            self.store.add_message(
                ChatMessage(
                    session_id=session_id,
                    role="assistant",
                    content=result.answer,
                    agent_name=agent_name,
                    trace_id=trace_id,
                )
            )

            # ═══ 11. 记录成功调用日志 ═══
            finished_at = utc_now()
            self.call_logger.add(
                CallLog(
                    trace_id=trace_id,
                    session_id=session_id,
                    entrypoint=request.entrypoint,
                    agent_name=agent_name,
                    skill_name=",".join(result.activated_skills) or None,
                    status=CallStatus.success,
                    started_at=started_at,
                    finished_at=finished_at,
                    latency_ms=CallLogger.latency_ms(started_at, finished_at),
                    input_summary=request.content[:120],
                    output_summary=result.answer[:160],
                    input_tokens=max(1, len(request.content) // 4),
                    output_tokens=max(1, len(result.answer) // 4),
                )
            )

            # ═══ 12. 推送最终事件 ═══
            yield ChatEvent(
                event="final",
                trace_id=trace_id,
                agent=agent_name,
                message=result.answer,
                data={
                    "message": result.answer,
                    "activated_skills": result.activated_skills,
                },
            )

        except Exception as exc:
            # ═══ 异常路径 ═══
            finished_at = utc_now()
            self.call_logger.add(
                CallLog(
                    trace_id=trace_id,
                    session_id=session_id,
                    entrypoint=request.entrypoint,
                    status=CallStatus.failed,
                    started_at=started_at,
                    finished_at=finished_at,
                    latency_ms=CallLogger.latency_ms(started_at, finished_at),
                    input_summary=request.content[:120],
                    output_summary="",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )
            yield ChatEvent(event="error", trace_id=trace_id, message=str(exc))


def _chunk_text(text: str, size: int) -> list[str]:
    """将文本按固定长度切块，用于模拟流式输出的打字机效果。"""
    return [text[index : index + size] for index in range(0, len(text), size)]
