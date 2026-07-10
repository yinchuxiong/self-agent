"""Programming Agent: LLM + Tool Calling loop for code, Git, and repository tasks.

This is the first domain agent with real tool execution capability.
It uses the OpenAI-compatible tool_calling API to let the LLM decide when
to call git tools, executes them in a sandboxed workspace, and streams
progress back to the frontend via SSE events.
"""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any

from self_agent.app.agents.base import AgentRunResult, AgentRunStep, BaseAgent
from self_agent.app.core.config import Settings, get_settings
from self_agent.app.core.models import ChatEvent, SkillDefinition
from self_agent.app.tools.base import ToolExecutor

logger = logging.getLogger(__name__)

# ── Maximum iterations for the tool-calling loop ──────────────────────────
MAX_TOOL_ITERATIONS = 5

# ── System prompt template ────────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是 Programming Agent，一个专注于编程和代码仓库管理的 AI 助手。

## 你的职责
- 帮助用户查看和管理 Git 仓库
- 分析代码变更（diff）
- 查看提交历史
- 审查代码质量

## 工具使用规则
1. **主动使用工具**：当用户的问题涉及仓库状态、代码差异、提交历史时，主动调用相应的工具获取最新数据。
2. **一次一个工具**：每次只调用一个工具，等待结果后再决定下一步。
3. **结果解读**：获取工具结果后，用清晰的中文向用户解释结果的含义，不要直接粘贴原始输出。
4. **空结果处理**：如果工具返回空结果，如实告知用户（如"工作区是干净的，没有未提交的改动"）。
5. **错误处理**：如果工具执行失败，告诉用户失败原因并给出建议（如"当前目录不是 Git 仓库，是否需要初始化？"）。

## 当前工作目录
{workspace_dir}

## 重要提示
- 你只能使用提供的工具，不能执行其他操作。
- 对于只读操作（查看状态、差异、历史），直接执行并返回结果。
- 对于写入操作（提交、推送等），必须提示用户这个版本暂不支持。
"""

# ── Maximum tokens allowed for tool result content ─────────────────────────
MAX_TOOL_OUTPUT_TOKENS_ESTIMATE = 6000  # ~24K chars at 4 chars/token


class ProgrammingAgent(BaseAgent):
    """Autonomous programming agent with LLM-driven tool calling.

    The agent:
    1. Receives user prompt + activated skills
    2. Loads corresponding tools into a ToolExecutor
    3. Enters a tool-calling loop with the DeepSeek API
    4. Streams tool progress as ChatEvent yields
    5. Returns the final LLM answer as AgentRunResult
    """

    def __init__(
        self,
        definition: Any,  # AgentDefinition
        tool_executor: ToolExecutor,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(definition)
        self.executor = tool_executor
        self.settings = settings or get_settings()

    # ── Main entry point ──────────────────────────────────────────────────

    async def run(
        self, prompt: str, skills: list[SkillDefinition]
    ) -> AsyncIterator[AgentRunStep]:
        """Execute the agent loop, yielding progress events and final result."""
        skill_names = [skill.name for skill in skills]
        trace_id = f"agent_programming_{id(prompt)}"

        # ── Build messages ────────────────────────────────────────────────
        system_content = SYSTEM_PROMPT.format(
            workspace_dir=self.definition.workspace_dir
        )
        if skill_names:
            system_content += f"\n\n本次激活的能力：{', '.join(skill_names)}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        tool_definitions = self.executor.openai_tool_definitions()
        tool_names = self.executor.tool_names()
        logger.info(
            "ProgrammingAgent starting: prompt=%.120s skills=%s tools=%s",
            prompt, skill_names, tool_names,
        )

        answer = ""
        activated_tools: list[str] = []

        # ── Tool calling loop ─────────────────────────────────────────────
        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self._call_llm(messages, tool_definitions)

            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})

            # Check for tool_calls in the response
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                # ── Execute tool(s) ───────────────────────────────────────
                # Append the assistant's tool_call message to history
                messages.append(message)

                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    arguments = self._parse_tool_args(func.get("arguments", "{}"))

                    activated_tools.append(tool_name)

                    # Yield tool_started event
                    yield ChatEvent(
                        event="tool_started",
                        trace_id=trace_id,
                        agent=self.definition.name,
                        message=f"🔧 调用工具: {tool_name}",
                        data={"tool": tool_name, "arguments": arguments},
                    )
                    await asyncio.sleep(0.02)

                    # Execute the tool
                    result = await self.executor.execute(tool_name, arguments)

                    # Yield tool_result event
                    output_summary = (
                        result.output[:200] + "..."
                        if len(result.output) > 200
                        else result.output
                    )
                    yield ChatEvent(
                        event="tool_result",
                        trace_id=trace_id,
                        agent=self.definition.name,
                        message=(
                            f"✅ {tool_name} 完成"
                            if result.success
                            else f"❌ {tool_name} 失败: {result.error}"
                        ),
                        data={
                            "tool": tool_name,
                            "success": result.success,
                            "error": result.error,
                            "summary": output_summary,
                        },
                    )
                    await asyncio.sleep(0.02)

                    # Append tool result to conversation
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result.output if result.success else f"Error: {result.error}",
                    })

                # Continue the loop — LLM will process tool results
                continue

            # ── No tool calls → this is the final answer ──────────────────
            answer = message.get("content") or choice.get("text") or ""
            if not answer:
                answer = "(LLM returned empty response)"
            break

        else:
            # Loop exhausted without a final answer
            answer = "已达到最大工具调用次数，但任务可能未完成。请尝试更具体的提问。"

        # ── Return final result ───────────────────────────────────────────
        yield AgentRunResult(
            agent=self.definition.name,
            answer=answer,
            activated_skills=skill_names + activated_tools,
        )

    # ── LLM integration ───────────────────────────────────────────────────

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send messages to DeepSeek API with tool definitions, return parsed JSON."""
        url = self.settings.deepseek_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.settings.default_model,
            "messages": messages,
            "temperature": 0.3,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        return await asyncio.to_thread(self._post_completion, url, headers, payload)

    def _post_completion(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Synchronous HTTP POST for LLM API call (runs in thread pool)."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error("DeepSeek API HTTP %s: %s", exc.code, error_body[:500])
            raise
        except urllib.error.URLError as exc:
            logger.error("DeepSeek API connection error: %s", exc.reason)
            raise

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_tool_args(raw: str | dict[str, Any]) -> dict[str, Any]:
        """Parse tool arguments from string or dict into a dict."""
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
