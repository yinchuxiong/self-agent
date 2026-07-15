"""LLM call node — invokes the ChatOpenAI model with tools bound.

Replaces `ProgrammingAgent._call_llm()` with a LangGraph node that:
1. Creates a ChatOpenAI instance pointed at the configured DeepSeek API.
2. Binds tool definitions from the agent's ToolExecutor.
3. Builds a system prompt from the agent definition + activated skills.
4. Invokes the LLM and returns the response message.
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from self_agent.app.core.config import get_settings
from self_agent.app.core.models import AgentDefinition
from self_agent.app.graph.llm_client import build_chat_openai
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.tools.base import ToolExecutor

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5

# ── Default system prompts per agent category ──────────────────────────

_DEFAULT_SYSTEM_PROMPTS: dict[str, str] = {
    "programming": """\
你是 Programming Agent，一个专注于编程和代码仓库管理的 AI 助手。

## 你的职责
- 帮助用户查看和管理 Git 仓库
- 执行代码变更和 Git 提交
- 分析代码变更（diff）和提交历史
- 审查代码质量
- 管理分支、解决依赖问题、调试代码

## 工具使用规则
1. **主动使用工具**：当用户的问题涉及仓库状态、代码差异、提交历史时，主动调用相应的工具获取最新数据。
2. **一次一个工具**：每次只调用一个工具，等待结果后再决定下一步。
3. **结果解读**：获取工具结果后，用清晰的中文向用户解释结果的含义，不要直接粘贴原始输出。
4. **空结果处理**：如果工具返回空结果，如实告知用户（如"工作区是干净的，没有未提交的改动"）。
5. **错误处理**：如果工具执行失败，告诉用户失败原因并给出建议（如"当前目录不是 Git 仓库，是否需要初始化？"）。

## 当前工作目录
{workspace_dir}

## 重要提示
- 你只能使用提供的工具完成任务。
- 对于 Git 写入操作（commit、push、分支创建等），在充分理解用户意图后执行。
- 执行危险操作前（如 force push、hard reset），先向用户确认。
""",
    "personal_tools": """\
你是 Personal Tools Agent，一个专注于文件处理和格式转换的 AI 助手。

## 你的职责
- 处理 JSON / PDF / Excel / CSV 文件
- 格式转换（xlsx↔csv↔json↔markdown）
- 文本比对和 OCR 识别
- 轻量数据加工

## 当前工作目录
{workspace_dir}

## 重要提示
- 主动使用可用工具处理用户请求。
- 用清晰的中文解释处理结果。
""",
    "work": """\
你是 Work Agent，一个专注于工作流程和文档管理的 AI 助手。

## 你的职责
- 生成日报、周报、月报
- 管理会议纪要和待办任务
- 发布飞书消息和文档
- 汇总工作产出

## 当前工作目录
{workspace_dir}

## 重要提示
- 主动使用可用工具完成工作流程任务。
- 对于发布操作，必须先预览再确认。
""",
    "scheduler": """\
你是 Scheduler Agent，一个专注于定时任务和提醒管理的 AI 助手。

## 你的职责
- 管理 cron 定时任务
- 设置一次性提醒
- 执行周期健康检查
- 审计任务执行历史

## 当前工作目录
{workspace_dir}

## 重要提示
- 所有时间相关操作请明确确认时区和时间格式。
""",
}


def _build_system_prompt(
    agent_def: AgentDefinition,
    activated_skills: list[str] | None,
) -> str:
    """Build the system prompt for the agent.

    Uses the agent's default prompt template or a generic fallback.
    Appends activated skill information if any skills were matched.
    """
    agent_name = agent_def.name
    workspace_dir = agent_def.workspace_dir

    prompt = _DEFAULT_SYSTEM_PROMPTS.get(
        agent_name,
        f"你是 {agent_def.display_name}。\n工作目录：{workspace_dir}\n",
    ).format(workspace_dir=workspace_dir)

    if activated_skills:
        prompt += f"\n\n本次激活的能力：{', '.join(activated_skills)}"

    return prompt


def _get_msg_role(m) -> str | None:
    """Return the role string for a message, whether it's a BaseMessage object or a dict.

    LangChain BaseMessage: ``m.type`` → ``"ai"`` / ``"human"`` / ``"system"`` / ``"tool"``
    Dict (checkpoint):   ``m["role"]`` → ``"assistant"`` / ``"user"`` / ``"system"`` / ``"tool"``
    """
    if isinstance(m, dict):
        return m.get("role")
    if hasattr(m, "type"):
        return m.type  # type: ignore[return-value]
    return None


def _is_ai(m) -> bool:
    """True if the message is an AI/assistant message (object or dict)."""
    role = _get_msg_role(m)
    return role in ("ai", "assistant")


def _is_tool(m) -> bool:
    """True if the message is a tool message (object or dict)."""
    return _get_msg_role(m) == "tool"


def _get_tool_calls(m) -> list:
    """Extract tool_call dicts from an AI/assistant message (object or dict)."""
    if isinstance(m, dict):
        return m.get("tool_calls") or []
    if hasattr(m, "tool_calls"):
        return getattr(m, "tool_calls") or []
    return []


def _get_tool_call_id(tc) -> str:
    """Extract the id from a single tool_call entry (dict or ToolCall object)."""
    if isinstance(tc, dict):
        return tc.get("id", "")
    if hasattr(tc, "id"):
        return getattr(tc, "id") or ""
    return ""


def _get_tool_msg_id(m) -> str:
    """Extract tool_call_id from a tool message (object or dict)."""
    if isinstance(m, dict):
        return m.get("tool_call_id") or ""
    if hasattr(m, "tool_call_id"):
        return getattr(m, "tool_call_id") or ""
    return ""


def _sanitize_messages(messages: list) -> list:
    """Remove ToolMessages that violate the OpenAI/DeepSeek API ordering contract.

    The API requires that EVERY message with ``role: "tool"`` has a
    **preceding** message with ``role: "assistant"`` whose ``tool_calls``
    array contains a matching ``id``.  Three violations are caught:

    1. **Orphan** — no assistant message anywhere in the list has a matching id.
    2. **Misordered** — a matching assistant message exists, but it appears
       *after* the ToolMessage (e.g. due to a buggy reducer or stale checkpoint).
    3. **Empty id** — the ToolMessage's ``tool_call_id`` is missing / empty.

    Messages can arrive as either LangChain ``BaseMessage`` subclasses *or* as
    plain dicts (when restored from a LangGraph checkpoint).  This function
    normalises both representations.
    """
    # ── Pass 1: collect every valid tool_call_id AND note first AI index ──
    valid_tool_call_ids: set[str] = set()
    first_ai_pos: dict[str, int] = {}  # tool_call_id → index of first matching assistant msg

    for i, m in enumerate(messages):
        if _is_ai(m):
            for tc in _get_tool_calls(m):
                tid = _get_tool_call_id(tc)
                if tid:
                    valid_tool_call_ids.add(tid)
                    if tid not in first_ai_pos:
                        first_ai_pos[tid] = i

    # ── Pass 2: keep only ToolMessages that pass all checks ───────────
    cleaned: list = []
    dropped = 0

    for i, m in enumerate(messages):
        if _is_tool(m):
            tid = _get_tool_msg_id(m)
            if not tid:
                dropped += 1
                logger.warning(
                    "Dropping ToolMessage at position %d (empty/missing tool_call_id "
                    "— API will reject it). msg=%s",
                    i,
                    str(m)[:200],
                )
                continue
            if tid not in valid_tool_call_ids:
                dropped += 1
                logger.warning(
                    "Dropping orphaned ToolMessage at position %d: "
                    "tool_call_id=%s has no matching assistant message anywhere in the list",
                    i,
                    tid,
                )
                continue
            ai_pos = first_ai_pos.get(tid, -1)
            if ai_pos > i:
                dropped += 1
                logger.warning(
                    "Dropping misordered ToolMessage at position %d: "
                    "tool_call_id=%s — matching assistant message is at position %d "
                    "(appears AFTER the tool result, API will reject)",
                    i,
                    tid,
                    ai_pos,
                )
                continue
        cleaned.append(m)

    if dropped:
        logger.warning(
            "Sanitized %d ToolMessage(s) — %d messages remain",
            dropped,
            len(cleaned),
        )

    return cleaned


def make_llm_node(
    agent_def: AgentDefinition,
    agent_loader: AgentLoader,
):
    """Return an async LLM call node function for the given agent.

    The node:
    1. Gets or creates a ToolExecutor for this agent from config.configurable.executors.
    2. Creates a ChatOpenAI(model, streaming=True) with bound tools.
    3. Builds a full message list from state and invokes the LLM.

    Args:
        agent_def: The agent definition for system prompt generation.
        agent_loader: Used for agent-specific tool loading (executor
                      creation happens at graph-build time, not here).
    """

    agent_name = agent_def.name

    async def llm_node(state: dict, config: RunnableConfig) -> dict:
        configurable = config.get("configurable", {})
        settings = configurable.get("settings") or get_settings()
        executors: dict[str, ToolExecutor] = configurable.get("executors", {})
        executor = executors.get(agent_name)

        # ── Build the LLM ────────────────────────────────────────────
        llm = build_chat_openai(
            settings,
            temperature=0.3,
            streaming=True,  # Token streaming picked up by astream_events
        )

        # Bind tools if available
        tool_definitions = executor.openai_tool_definitions() if executor else []
        if tool_definitions:
            llm = llm.bind_tools(tool_definitions)

        # ── Build messages ───────────────────────────────────────────
        activated_skills: list[str] = state.get("activated_skills", []) or []
        system_content = _build_system_prompt(agent_def, activated_skills)

        # Collect messages from state: system prompt + existing conversation
        existing_messages = state.get("messages", [])

        # Build the full message list
        # Only prepend system message if not already present
        # (Works with both BaseMessage objects and dict-form checkpoint messages.)
        has_system = any(
            _get_msg_role(m) in ("system",) for m in existing_messages
        )
        if has_system:
            messages = list(existing_messages)
        else:
            messages = [SystemMessage(content=system_content)] + list(existing_messages)

        # Ensure there's a user message — add the user_input if messages are minimal
        if not messages:
            user_input = state.get("user_input", "")
            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=user_input),
            ]

        # ── Sanitize: drop orphaned ToolMessages ─────────────────
        # Defense-in-depth: stale checkpoints or reducer bugs can leave
        # ToolMessages without a preceding AIMessage(tool_calls=[...]).
        messages = _sanitize_messages(messages)

        # ── Diagnostic: dump message roles & tool_calls ─────────
        _dump_msg = []
        for i, m in enumerate(messages):
            role = _get_msg_role(m) or "unknown"
            if _is_ai(m):
                tc_ids = [_get_tool_call_id(tc) for tc in _get_tool_calls(m)]
            else:
                tc_ids = None
            tcid = _get_tool_msg_id(m) if _is_tool(m) else None
            # Get content safely from either format
            if isinstance(m, dict):
                content = str(m.get("content", ""))[:80]
            else:
                content = str(getattr(m, "content", "") if hasattr(m, "content") else "")[:80]
            _dump_msg.append(
                f"  [{i}] {role} tc_ids={tc_ids} tcid={tcid} content={content!r}"
            )
        logger.info(
            "LLM node [%s]: %d messages, %d tools\n%s",
            agent_name,
            len(messages),
            len(tool_definitions),
            "\n".join(_dump_msg),
        )

        # ── Diagnostic: dump API-format payload (what DeepSeek sees) ──
        _api_msgs = []
        for m in messages:
            if isinstance(m, dict):
                _api_msgs.append(m)
            elif hasattr(m, "type"):
                # Mimic ChatOpenAI._convert_message_to_dict
                d: dict = {"role": m.type}
                content = getattr(m, "content", None)
                if content is not None:
                    d["content"] = content
                if m.type == "ai":
                    tcs = getattr(m, "tool_calls", None)
                    if tcs:
                        d["tool_calls"] = tcs
                if m.type == "tool":
                    tcid = getattr(m, "tool_call_id", None)
                    if tcid:
                        d["tool_call_id"] = tcid
                _api_msgs.append(d)
        logger.info(
            "LLM node [%s]: API payload (what DeepSeek receives):\n%s",
            agent_name,
            str(_api_msgs)[:3000],
        )

        # ── Invoke ───────────────────────────────────────────────────
        response = await llm.ainvoke(messages)

        # Check for empty response
        if not hasattr(response, "tool_calls") or not response.tool_calls:
            content = getattr(response, "content", None)
            if not content or not str(content).strip():
                return {
                    "messages": [
                        AIMessage(content="(Agent returned empty response, please retry.)")
                    ],
                    "final_answer": "(Agent returned empty response)",
                }

        return {"messages": [response]}

    return llm_node
