"""Programming Agent: LLM + Tool Calling loop for code, Git, and repository tasks.

This agent lives under .agents/programming/ — its tools are in ./tools/,
skills in ./skills/, and MCP config in ../mcp.yml.
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

MAX_TOOL_ITERATIONS = 5

SYSTEM_PROMPT = """\
你是 Programming Agent，一个专注于编程和代码仓库管理的 AI 助手。

## 你的职责
- 帮助用户查看和管理 Git 仓库（状态、差异、日志、分支、标签等）
- 分析代码变更（diff）、审查代码质量
- 运行 Python/Node 脚本、管理依赖（pip/npm/poetry）
- 浏览项目文件（ls/cat/grep/find）

## 核心工具：execute_command
你有一个核心工具 `execute_command`，用于在工作目录中执行 shell 命令。
这个工具自带沙箱保护——危险命令（rm -rf、sudo、git push -f 等）会被自动拦截。

## 工具使用规则
1. **用你的 CLI 知识构造命令**：你精通 git 和各种 CLI 工具，直接写出你需要的确切命令。
   - 查看状态 → `git status --short -b`
   - 查看差异 → `git diff` 或 `git diff --staged` 或 `git diff -- <file>`
   - 查看日志 → `git log --oneline -n20` 或 `git log --oneline --author=xxx`
   - 查看某次提交 → `git show <commit>`
   - 列出分支 → `git branch -a`
   - 包管理 → `pip list` / `npm list` / `poetry show`
2. **一次一个命令**：每次只调用一个工具，等待结果后再决定下一步。
3. **结果解读**：获取命令输出后，用清晰的中文向用户解释结果的含义，不要直接粘贴原始输出。
4. **空结果处理**：如果命令返回空，如实告知用户（如"工作区是干净的，没有未提交的改动"）。
5. **错误处理**：如果命令执行失败，告诉用户失败原因并给出建议。

## 当前工作目录
{workspace_dir}

## 重要提示
- 所有命令在沙箱中执行，只能操作当前工作目录内的文件。
- 对于只读操作，直接执行并返回结果。
- 对于写入操作（提交、推送等），提示用户当前版本暂不支持。
"""

MAX_TOOL_OUTPUT_TOKENS_ESTIMATE = 6000


class ProgrammingAgent(BaseAgent):
    """Autonomous programming agent with LLM-driven tool calling."""

    def __init__(
        self,
        definition: Any,
        tool_executor: ToolExecutor,
        settings: Settings | None = None,
    ) -> None:
        super().__init__(definition)
        self.executor = tool_executor
        self.settings = settings or get_settings()

    async def run(
        self, prompt: str, skills: list[SkillDefinition]
    ) -> AsyncIterator[AgentRunStep]:
        skill_names = [skill.name for skill in skills]
        trace_id = f"agent_programming_{id(prompt)}"

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

        for iteration in range(MAX_TOOL_ITERATIONS):
            response = await self._call_llm(messages, tool_definitions)
            choice = response.get("choices", [{}])[0]
            message = choice.get("message", {})
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                messages.append(message)
                for tc in tool_calls:
                    func = tc.get("function", {})
                    tool_name = func.get("name", "")
                    arguments = self._parse_tool_args(func.get("arguments", "{}"))
                    activated_tools.append(tool_name)

                    yield ChatEvent(
                        event="tool_started",
                        trace_id=trace_id,
                        agent=self.definition.name,
                        message=f"🔧 调用工具: {tool_name}",
                        data={"tool": tool_name, "arguments": arguments},
                    )
                    await asyncio.sleep(0.02)

                    result = await self.executor.execute(tool_name, arguments)

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

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result.output if result.success else f"Error: {result.error}",
                    })
                continue

            answer = message.get("content") or choice.get("text") or ""
            if not answer:
                answer = "(LLM returned empty response)"
            break
        else:
            answer = "已达到最大工具调用次数，但任务可能未完成。请尝试更具体的提问。"

        yield AgentRunResult(
            agent=self.definition.name,
            answer=answer,
            activated_skills=skill_names + activated_tools,
        )

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
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
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
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

    @staticmethod
    def _parse_tool_args(raw: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
