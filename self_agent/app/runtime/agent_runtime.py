# ── 标准库 ──────────────────────────────────────────────────────────────
import asyncio  # 异步 I/O 支持，用于 async/await 和 sleep 模拟流式延迟
from collections.abc import AsyncIterator  # 异步迭代器类型标注，定义 stream_chat 的返回类型

# ── Agent 层：各类业务 Agent ───────────────────────────────────────────
from self_agent.app.agents.base import AgentRunResult, BaseAgent  # AgentRunResult: 最终执行结果
from self_agent.app.agents.personal_tools import PersonalToolsAgent  # 个人工具 Agent（日历、提醒等）
from self_agent.app.agents.programming import ProgrammingAgent  # 编程 Agent（代码生成、调试等）
from self_agent.app.agents.scheduler import SchedulerAgent  # 调度 Agent（定时任务管理）
from self_agent.app.agents.supervisor import Supervisor  # 监督者：根据用户输入内容识别意图，路由到合适的 Agent
from self_agent.app.agents.work import WorkAgent  # 通用工作 Agent（默认回退，处理未分类请求）

# ── 核心数据模型 ───────────────────────────────────────────────────────
from self_agent.app.core.models import (
    CallLog,  # 调用日志条目：记录一次完整请求的元数据（耗时、token、状态等）
    CallStatus,  # 调用状态枚举：success / failed
    ChatEvent,  # SSE 事件：流式推送给前端的一条消息（含事件类型、trace_id、数据等）
    ChatMessage,  # 聊天消息：存储在会话中的一条对话记录（用户或助手）
    ChatRequest,  # 聊天请求：前端发来的输入（内容、入口点、指定 agent 等）
    new_id,  # 工具函数：生成带前缀的唯一 ID（如 "trace_xxx"）
    utc_now,  # 工具函数：获取当前 UTC 时间
)

# ── 工具执行器 ─────────────────────────────────────────────────────────
from self_agent.app.tools.base import ToolExecutor  # 工具注册与安全执行
from self_agent.app.tools.git_tools import register_git_tools  # 注册 git 工具到 executor

# ── 可观测性与注册表 ──────────────────────────────────────────────────
from self_agent.app.observability.call_logger import CallLogger  # 调用日志记录器：持久化 CallLog，支持统计查询
from self_agent.app.registries.agent_registry import AgentRegistry  # Agent 注册表：管理所有已注册 Agent 的定义信息
from self_agent.app.registries.skill_registry import SkillRegistry  # Skill 注册表：管理 Skill 定义，按 Agent + 内容匹配

# ── 存储层 ─────────────────────────────────────────────────────────────
from self_agent.app.runtime.store import InMemoryStore  # 内存存储：会话和消息的 CRUD（非持久化，重启丢失）


class AgentRuntime:
    """Agent 运行时：协调一次请求的完整生命周期。

    职责（按调用顺序）：
    1. 持久化用户消息（即使后续失败也能审计追溯）
    2. 通过 Supervisor 识别意图，路由到对应的业务 Agent
    3. 匹配并激活相关 Skill
    4. 执行 Agent 并流式推送回答（SSE 事件）
    5. 记录调用日志（CallLog）用于统计和排错
    6. 异常时推送错误事件并记录失败日志
    """

    def __init__(
        self,
        store: InMemoryStore,
        agent_registry: AgentRegistry,
        skill_registry: SkillRegistry,
        call_logger: CallLogger,
    ) -> None:
        # 依赖注入：所有外部依赖通过构造函数传入，便于测试和替换
        self.store = store  # 会话存储（消息持久化）
        self.agent_registry = agent_registry  # Agent 定义注册表
        self.skill_registry = skill_registry  # Skill 定义注册表
        self.call_logger = call_logger  # 调用日志记录器
        self.supervisor = Supervisor(agent_registry)  # 意图识别 + 路由决策

    def _agent(self, name: str) -> BaseAgent:
        """根据 Agent 名称构建对应的业务 Agent 实例。

        这是一个工厂方法：根据 Supervisor 路由得到的名称，
        返回具体的 Agent 实现（ProgrammingAgent / PersonalToolsAgent 等）。
        未匹配到的名称默认使用 WorkAgent 作为通用回退。

        ProgrammingAgent 会额外注入 ToolExecutor，使其具备真实的工具执行能力。
        """
        definition = self.agent_registry.get(name)  # 从注册表获取 Agent 定义
        if name == "programming":
            executor = ToolExecutor(
                workspace_dir=definition.workspace_dir,
                allowed_paths=definition.allowed_paths,
            )
            register_git_tools(executor)
            return ProgrammingAgent(definition, executor)
        if name == "personal_tools":
            return PersonalToolsAgent(definition)
        if name == "scheduler":
            return SchedulerAgent(definition)
        return WorkAgent(definition)  # 默认回退：通用工作 Agent

    async def stream_chat(
        self,
        session_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[ChatEvent]:
        """处理一次聊天请求，通过 SSE 事件流式推送进度给前端。

        这是 AgentRuntime 的核心方法，整个请求生命周期如下：

        ┌─ 1. 初始化 ──────────────────────────────────────────┐
        │  生成 trace_id（全链路追踪标识），记录开始时间          │
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
        # ═══ 1. 初始化：生成追踪 ID 和开始时间 ═══
        trace_id = new_id("trace")  # 全链路追踪标识，如 "trace_a1b2c3d4"
        started_at = utc_now()  # UTC 时间戳，用于计算总耗时

        # ═══ 2. 持久化用户消息（在一切执行之前） ═══
        # 这样即使 Agent 执行失败，用户的问题也不会丢失，确保可审计
        self.store.add_message(
            ChatMessage(
                session_id=session_id,
                role="user",  # 角色：用户
                content=request.content,  # 用户输入的原始文本
                trace_id=trace_id,  # 关联到本次 trace
            )
        )

        # ═══ 3. 通知前端：Supervisor 开始识别意图 ═══
        yield ChatEvent(
            event="supervisor_started",  # SSE 事件类型
            trace_id=trace_id,
            message="Supervisor 正在识别意图",
        )
        await asyncio.sleep(0.05)  # 短暂延迟，确保前端有时间渲染过渡动画

        try:
            # ═══ 4. 路由：Supervisor 根据用户内容决定用哪个 Agent ═══
            # request.agent_name 若用户显式指定了 Agent 则优先使用，否则由 AI 判断
            route_decision = await self.supervisor.route(request.content, request.agent_name)
            agent_name = route_decision.agent_name

            # ═══ 5. 启用检查：被禁用的 Agent 拒绝执行 ═══
            definition = self.agent_registry.get(agent_name)
            if not definition.enabled:
                raise RuntimeError(f"{definition.display_name} 当前已禁用")

            # ═══ 6. 通知前端：Agent 已确定，开始执行 ═══
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
            # 根据 Agent 名称和用户输入内容，从注册表中匹配可用 Skill
            # Skill 激活事件先于真实工具调用，给前端展示"即将使用哪些能力"
            skills = self.skill_registry.match_skills(agent_name, request.content)
            for skill in skills:
                yield ChatEvent(
                    event="skill_activated",
                    trace_id=trace_id,
                    agent=agent_name,
                    skill=skill.name,
                    message=f"激活 {skill.display_name}",
                )
                await asyncio.sleep(0.03)  # 每个 Skill 激活间隔，逐一展示

            # ═══ 8. 执行 Agent ═══
            # 新版 Agent.run() 是异步生成器：yield ChatEvent（工具进度）→ 最终 yield AgentRunResult
            agent = self._agent(agent_name)
            result: AgentRunResult | None = None
            async for step in agent.run(request.content, skills):
                if isinstance(step, AgentRunResult):
                    result = step
                elif isinstance(step, ChatEvent):
                    # 透传中间事件（tool_started / tool_result 等）
                    yield step
                    await asyncio.sleep(0.01)

            if result is None:
                result = AgentRunResult(
                    agent=agent_name,
                    answer="Agent 执行完成但未返回结果，请重试。",
                )

            # ═══ 9. 流式推送回答 ═══
            # 将完整回答按固定长度分块，逐块以 answer_delta 事件发送
            # 模拟流式输出的打字机效果（Agent 目前是同步返回完整结果的）
            for chunk in _chunk_text(result.answer, 42):
                yield ChatEvent(
                    event="answer_delta",
                    trace_id=trace_id,
                    agent=agent_name,
                    message=chunk,
                    data={"delta": chunk},  # data 字段携带增量文本，前端可直接追加渲染
                )
                await asyncio.sleep(0.02)  # 块间延迟，控制打字速度

            # ═══ 10. 持久化助手消息 ═══
            self.store.add_message(
                ChatMessage(
                    session_id=session_id,
                    role="assistant",  # 角色：助手
                    content=result.answer,  # Agent 返回的完整回答
                    agent_name=agent_name,  # 记录是哪个 Agent 回答的
                    trace_id=trace_id,
                )
            )

            # ═══ 11. 记录成功调用日志 ═══
            finished_at = utc_now()
            self.call_logger.add(
                CallLog(
                    trace_id=trace_id,
                    session_id=session_id,
                    entrypoint=request.entrypoint,  # 入口来源（如 web / cli / api）
                    agent_name=agent_name,
                    # 将激活的 Skill 名称用逗号拼接成一个字符串
                    skill_name=",".join(result.activated_skills) or None,
                    status=CallStatus.success,  # 标记为成功
                    started_at=started_at,
                    finished_at=finished_at,
                    latency_ms=CallLogger.latency_ms(started_at, finished_at),  # 总耗时（毫秒）
                    input_summary=request.content[:120],  # 输入摘要（截取前 120 字符）
                    output_summary=result.answer[:160],  # 输出摘要（截取前 160 字符）
                    # token 数估算：简单按字符数 / 4 近似（后续可接入真实 tokenizer）
                    input_tokens=max(1, len(request.content) // 4),
                    output_tokens=max(1, len(result.answer) // 4),
                )
            )

            # ═══ 12. 推送最终事件 ═══
            # final 事件标志本次请求结束，携带完整回答和 Skill 列表供前端做最终渲染
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
            # ═══ 异常路径：记录失败日志并推送错误事件 ═══
            finished_at = utc_now()
            self.call_logger.add(
                CallLog(
                    trace_id=trace_id,
                    session_id=session_id,
                    entrypoint=request.entrypoint,
                    status=CallStatus.failed,  # 标记为失败
                    started_at=started_at,
                    finished_at=finished_at,
                    latency_ms=CallLogger.latency_ms(started_at, finished_at),
                    input_summary=request.content[:120],
                    output_summary="",  # 失败时无输出
                    error_type=type(exc).__name__,  # 异常类型（如 RuntimeError）
                    error_message=str(exc),  # 异常消息
                )
            )
            # 推送 error 事件给前端，前端可据此展示错误提示
            yield ChatEvent(event="error", trace_id=trace_id, message=str(exc))


def _chunk_text(text: str, size: int) -> list[str]:
    """将文本按固定长度切块，用于模拟流式输出的打字机效果。

    Args:
        text: 要切分的完整文本（Agent 返回的完整回答）
        size: 每块的字符数（默认 42 个字符，约一行终端宽度的一半）

    Returns:
        字符串列表，每个元素是原文本的一个切片

    Example:
        >>> _chunk_text("你好世界", 2)
        ['你好', '世界']
        >>> _chunk_text("abc", 5)
        ['abc']  # 比 size 短时直接返回单元素列表

    注意：这是纯字符切分，不考虑中英文边界，可能在多字节字符中间切断。
    生产环境中应使用更智能的分块策略（按词边界、按标点等）。
    """
    return [text[index : index + size] for index in range(0, len(text), size)]
