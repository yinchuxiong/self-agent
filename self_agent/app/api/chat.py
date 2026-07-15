"""
聊天 API —— 处理会话和消息的 HTTP 接口。

这是前端最主要的交互接口，提供了完整的会话管理（CRUD）和消息发送功能。

核心端点：
- POST   /api/chat/sessions          创建新会话
- GET    /api/chat/sessions          列出所有会话
- GET    /api/chat/sessions/{id}     获取会话详情（含消息列表）
- DELETE /api/chat/sessions/{id}     删除会话
- POST   /api/chat/sessions/{id}/messages  发送消息（核心！返回 SSE 流）

Python 语法要点：
- APIRouter(prefix="/chat")：创建子路由，所有路径自动加 /chat 前缀
- @router.post("/path")：装饰器，将函数注册为 POST 路由处理器
- async def：异步函数，FastAPI 自动在线程池中运行
- StreamingResponse：特殊的响应类型，数据不是一次性返回，而是持续"流"给客户端
- async for ... in ...：异步迭代，每次迭代等一个事件就立即发送，实现实时流式输出
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from self_agent.app.core.events import encode_sse
from self_agent.app.core.models import ChatRequest, ChatSession, new_id, utc_now
from self_agent.app.graph.sse_adapter import stream_chat_with_langgraph
from self_agent.app.state import state

# 创建子路由，prefix="/chat" 会被加到所有端点路径前
# tags=["chat"] 用于 API 文档分组
router = APIRouter(prefix="/chat", tags=["chat"])


# ── 请求模型 ─────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """创建会话的请求体。

    Python 语法要点：
    - title: str | None = None：可选字段，不传就是 None
      str | None 等价于 typing.Optional[str]
    """
    title: str | None = None       # 会话标题（可选，默认"新会话"）
    workspace_dir: str = ""        # 工作目录（可选，默认空）


# ── 会话管理接口 ─────────────────────────────────────────────────────────

@router.post("/sessions", response_model=ChatSession)
async def create_session(body: CreateSessionRequest = CreateSessionRequest()) -> ChatSession:
    """创建新会话。

    Python 语法要点：
    - body: CreateSessionRequest = CreateSessionRequest()：
      参数默认值是 CreateSessionRequest 的一个新实例（所有字段都是默认值），
      这样前端可以不传任何 body，FastAPI 会使用默认的空请求体。

    Returns:
        新创建的 ChatSession 对象（由 response_model 自动序列化为 JSON）
    """
    return state.store.create_session(title=body.title, workspace_dir=body.workspace_dir)


@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions() -> list[ChatSession]:
    """获取所有会话列表。

    返回按更新时间倒序排列的会话列表，前端左侧面板使用此接口。

    Python 语法要点：
    - response_model=list[ChatSession]：告诉 FastAPI 返回类型是 ChatSession 列表，
      FastAPI 会自动将每个元素序列化为 JSON
    """
    return state.store.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    """获取单个会话的详情（包含消息列表）。

    Python 语法要点：
    - {session_id}：路径参数，FastAPI 自动从 URL 中提取并传给函数
    - try/except KeyError as exc：捕获 KeyError 异常并转为 HTTP 404 响应
    - raise HTTPException(status_code=404) from exc：抛出 HTTP 异常，
      FastAPI 会将其转为对应的 HTTP 错误响应
      "from exc" 保留了原始异常信息，便于调试时追踪错误链
    """
    try:
        session = state.store.get_session(session_id)
        messages = state.store.list_messages(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session": session, "messages": messages}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    """删除会话。

    HTTP 204 No Content：删除成功但不返回内容（标准的 REST 删除响应）。
    FastAPI 看到 status_code=204 和返回 None 时，自动返回空响应体。

    Python 语法要点：
    - -> None：声明返回值类型为 None（不返回数据）
    """
    state.store.delete_session(session_id)


# ── 消息发送接口（核心！）────────────────────────────────────────────────

@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, request: ChatRequest) -> StreamingResponse:
    """发送消息并获取 AI 回复（SSE 流式输出）。

    这是整个应用最核心的 API 端点。工作流程：
    1. 验证会话存在
    2. 构建 LangGraph 初始状态
    3. 通过 RunnableConfig 注入依赖（settings、executors、registries）
    4. 调用 LangGraph 图执行，通过 SSE 流式推送进度给前端

    SSE（Server-Sent Events）流式输出：
    不是等待全部结果完成后一次返回，而是把每一步的进展实时推送给前端。
    用户可以看到：
    - "Supervisor 正在分析意图..."
    - "已路由到编程 Agent"
    - "🔧 调用工具: git_status"
    - AI 回答文字逐字出现（打字机效果）

    Python 语法要点：
    - StreamingResponse(stream(), media_type="text/event-stream")：
      StreamingResponse 是 FastAPI 的流式响应，传入一个异步生成器函数，
      media_type 告诉浏览器这是 SSE 格式（不是普通 JSON）
    - async def stream()：嵌套的异步生成器函数，
      使用 yield 逐个产出事件，前端逐个接收
    - async for event in ...：异步迭代，每收到一个事件就 yield 出去
    """
    # ── 验证会话是否存在 ────────────────────────────────────────────────
    try:
        session = state.store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ── 异步生成器：逐个产生 SSE 事件 ──────────────────────────────────
    async def stream():
        """
        Python 语法要点：
        - 这是一个"异步生成器函数"（async generator）
        - yield 语句：产出一个值后暂停，等调用方消费后再继续执行
        - 与普通 return 的区别：return 一次性返回所有结果，yield 分多次返回
        - async for：异步迭代，用于消费另一个异步生成器
        """

        # 生成追踪 ID，用于串联这次请求的所有事件
        trace_id = new_id("trace")

        # 解析工作目录：优先使用请求中指定的，否则用会话的，最后用全局默认
        workspace_dir = request.workspace_dir or session.workspace_dir or ""

        # 构建 LangGraph 的初始状态
        # LangGraph 使用状态图（StateGraph），initial_state 是图的输入状态
        initial_state = {
            "messages": [HumanMessage(content=request.content)],  # 消息列表，初始只有用户消息
            "trace_id": trace_id,
            "session_id": session_id,
            "workspace_dir": workspace_dir,
            "user_input": request.content,  # 保留原始输入文本
        }

        # ── 构建 RunnableConfig ────────────────────────────────────────
        # configurable 是 LangGraph 的依赖注入机制：
        # 图节点可以通过 config.get("configurable", {}) 获取这些依赖
        from self_agent.app.core.config import get_settings

        config = RunnableConfig(
            configurable={
                "thread_id": session_id,                 # LangGraph checkpointer 所需的线程 ID
                "settings": get_settings(),          # 应用配置
                "agent_registry": state.agent_registry,  # Agent 注册表
                "skill_registry": state.skill_registry,  # Skill 注册表
                "executors": state.executors,            # 工具执行器字典
                "requested_agent": request.agent_name,   # 用户指定的 Agent
            },
        )

        # ── 通过 LangGraph SSE 适配器流式推事件 ────────────────────
        # stream_chat_with_langgraph 是一个异步生成器，逐个产出 ChatEvent
        # 每收到一个事件，就编码为 SSE 格式字符串并发送给前端
        async for event in stream_chat_with_langgraph(
            graph=state.graph,         # 编译好的 LangGraph 图
            initial_state=initial_state,
            config=config,
            session_id=session_id,
            request=request,
            store=state.store,
            call_logger=state.call_logger,
        ):
            # yield 暂停函数，把编码后的事件发送给前端，然后继续等下一个事件
            yield encode_sse(event)

    # 返回流式响应，media_type 告诉浏览器这是 SSE 格式
    return StreamingResponse(stream(), media_type="text/event-stream")
