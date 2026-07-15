"""Supervisor node — LLM planner that orchestrates domain agents via ReAct loop.

Replaces the old single-choice classifier with a full ReAct-style planner:
- The supervisor LLM has each domain agent bound as a callable tool.
- It analyzes user intent, decides which agent(s) to invoke, and in what order.
- After each agent returns a result, the supervisor decides: call more agents, or finish.

Graph topology (see supervisor_graph.py):

    __start__ --> supervisor_llm --> [conditional]
                    ^                   |
                    |                   v
                    +--- agent_dispatcher
                    (loop while tool_calls exist)

The supervisor emits AIMessage with tool_calls when it wants to delegate, and
a plain AIMessage when it's ready to answer the user.
"""

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from self_agent.app.core.config import get_settings
from self_agent.app.core.models import AgentDefinition
from self_agent.app.graph.llm_client import build_chat_openai
from self_agent.app.graph.nodes.llm_node import (
    _sanitize_messages,
    _get_msg_role,
    _is_ai,
    _is_tool,
    _get_tool_calls,
    _get_tool_call_id,
    _get_tool_msg_id,
)
from self_agent.app.registries.agent_registry import AgentRegistry

logger = logging.getLogger(__name__)


# ── Agent → tool definition mapping ─────────────────────────────────────

# Per-agent scenario hints help the LLM decide when to call each agent.
_AGENT_SCENARIOS: dict[str, str] = {
    "programming": (
        "代码编写、Git 提交/推送/分支管理、代码审查(code review)、"
        "查看 diff、仓库状态、依赖管理、bug 调试、工程实现"
    ),
    "personal_tools": (
        "JSON/PDF/Excel/CSV 文件处理、格式转换、OCR 识别、"
        "文本比对、轻量数据加工"
    ),
    "work": (
        "日报/周报/月报生成、会议纪要整理、任务追踪、"
        "工作总结、飞书消息或文档的发布预览"
    ),
    "scheduler": (
        "设置提醒、定时任务、cron 计划、周期任务管理"
    ),
}


def _tool_name(agent_name: str) -> str:
    """Convert agent name to tool name: 'programming' → 'programming_agent'."""
    return f"{agent_name}_agent"


def _agent_name_from_tool(tool_name: str) -> str:
    """Convert tool name back to agent name: 'programming_agent' → 'programming'."""
    return tool_name.replace("_agent", "")


def _build_agent_tool_def(agent_def: AgentDefinition) -> dict:
    """Build an OpenAI function-call tool definition for a domain agent.

    Each agent becomes a tool the supervisor LLM can invoke. The tool's single
    parameter is ``prompt`` — the exact instruction forwarded to the sub-agent.
    """
    scenarios = _AGENT_SCENARIOS.get(agent_def.name, agent_def.description)
    return {
        "type": "function",
        "function": {
            "name": _tool_name(agent_def.name),
            "description": (
                f"{agent_def.display_name} — {agent_def.description}\n"
                f"适用场景：{scenarios}\n"
                f"当用户请求涉及以上场景时，调用此工具将任务委派给 {agent_def.display_name}。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            f"要委派给 {agent_def.display_name} 的详细指令。"
                            "请包含用户原始请求中的所有相关上下文和具体要求。"
                        ),
                    }
                },
                "required": ["prompt"],
            },
        },
    }


def _build_supervisor_system_prompt(
    agent_registry: AgentRegistry,
    workspace_dir: str,
) -> str:
    """Build the supervisor's system prompt from registered domain agents.

    The prompt is fully dynamic — adding a new agent directory under .agents/
    automatically adds it to the supervisor's tool belt on next restart.
    """
    agent_lines: list[str] = []
    for agent_def in agent_registry.list():
        if agent_def.name == "supervisor":
            continue
        scenarios = _AGENT_SCENARIOS.get(agent_def.name, agent_def.description)
        agent_lines.append(
            f"  - **{_tool_name(agent_def.name)}**: {agent_def.description} "
            f"（{scenarios}）"
        )

    agent_bullets = "\n".join(agent_lines) if agent_lines else "  (无可用子 Agent)"

    return f"""\
你是个人多 Agent 助手的 Supervisor，负责理解用户意图、规划任务并将工作委派给子 Agent 执行。

## 可用子 Agent（每个都是一个可调用的工具）

{agent_bullets}

## 工作方式

1. **分析意图**：理解用户真正想要完成什么。
2. **委派任务**：调用对应的 agent 工具，给出清晰、具体的指令（包含用户的所有上下文）。
3. **查看结果**：根据子 Agent 的返回结果，判断是否还需要调用其他 Agent。
4. **串联协作**：对于复杂任务，可以依次调用多个 Agent（例如先让 programming_agent 提交代码，再让 work_agent 发飞书通知）。
5. **总结回复**：当任务全部完成时，用清晰的中文向用户总结做了什么、结果是什么。

## 重要规则

- **必须通过调用工具来委派工作**，你自己不能直接执行代码、操作文件或访问系统。
- "提交代码"、"git commit"、"commit 代码" 等代码/Git 操作 → 调用 programming_agent。
- "提交报告"、"提交日报" 等文档/报告操作 → 调用 work_agent。
- 每次只调用一个 Agent，等待结果后再决定下一步。
- 给子 Agent 的 instruction 要包含用户原始请求的完整上下文。

## 当前工作目录

{workspace_dir}
"""


# ── Node factory ────────────────────────────────────────────────────────

def make_supervisor_node(agent_registry: AgentRegistry):
    """Return an async supervisor LLM node that plans and delegates.

    The node:
    1. Builds a system prompt describing all available agents as tools.
    2. Binds agent tool definitions to the LLM.
    3. Invokes the LLM — it may return tool_calls (delegate) or a plain
       message (final answer).

    The returned function matches LangGraph's node signature:
        async def node(state: dict, config: RunnableConfig) -> dict
    """

    # Pre-compute tool definitions from the registry (static after startup).
    agent_tool_defs: list[dict] = [
        _build_agent_tool_def(agent_def)
        for agent_def in agent_registry.list()
        if agent_def.name != "supervisor"
    ]
    logger.info(
        "Supervisor agent tools: %s",
        [t["function"]["name"] for t in agent_tool_defs],
    )

    async def supervisor_node(state: dict, config: RunnableConfig) -> dict:
        configurable = config.get("configurable", {})
        settings = configurable.get("settings") or get_settings()
        workspace_dir: str = state.get("workspace_dir", "")

        # ── Build the LLM with agent tools bound ────────────────────
        llm = build_chat_openai(
            settings,
            temperature=0.3,
            streaming=True,
        )

        if agent_tool_defs:
            llm = llm.bind_tools(agent_tool_defs)

        # ── Build message list ──────────────────────────────────────
        system_content = _build_supervisor_system_prompt(
            agent_registry, workspace_dir
        )

        messages = list(state.get("messages", []))

        # Prepend system prompt if not already present
        # (Works with both BaseMessage objects and dict-form checkpoint messages.)
        has_system = any(
            _get_msg_role(m) == "system" for m in messages
        )
        if not has_system:
            messages.insert(0, SystemMessage(content=system_content))

        # Ensure there's always at least a user message
        if not messages:
            user_input = state.get("user_input", "")
            messages = [
                SystemMessage(content=system_content),
                HumanMessage(content=user_input),
            ]

        # ── Sanitize: drop orphaned ToolMessages ─────────────────
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
            if isinstance(m, dict):
                content = str(m.get("content", ""))[:80]
            else:
                content = str(getattr(m, "content", "") if hasattr(m, "content") else "")[:80]
            _dump_msg.append(
                f"  [{i}] {role} tc_ids={tc_ids} tcid={tcid} content={content!r}"
            )
        logger.info(
            "Supervisor LLM: %d messages, %d tools available\n%s",
            len(messages),
            len(agent_tool_defs),
            "\n".join(_dump_msg),
        )

        # ── Invoke ──────────────────────────────────────────────────
        response = await llm.ainvoke(messages)

        # Log the decision
        tool_calls = getattr(response, "tool_calls", None) or []
        if tool_calls:
            logger.info(
                "Supervisor → delegating to: %s",
                [tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                 for tc in tool_calls],
            )
        else:
            content_preview = (
                str(getattr(response, "content", ""))[:120]
            )
            logger.info("Supervisor → final answer: %s", content_preview)

        return {"messages": [response]}

    return supervisor_node
