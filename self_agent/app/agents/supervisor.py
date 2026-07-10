import asyncio
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from self_agent.app.core.config import Settings, get_settings
from self_agent.app.registries.agent_registry import AgentRegistry


@dataclass(frozen=True)
class RouteDecision:
    agent_name: str
    intent: str | None = None
    reason: str | None = None
    confidence: float | None = None
    source: str = "llm"


class Supervisor:
    """Supervisor that routes user requests with an LLM intent classifier."""

    def __init__(self, agent_registry: AgentRegistry, settings: Settings | None = None) -> None:
        self.agent_registry = agent_registry
        self.settings = settings or get_settings()

    async def route(self, prompt: str, requested_agent: str | None = None) -> RouteDecision:
        # Manual selection from the UI always wins over automatic routing.
        if requested_agent and requested_agent != "auto":
            agent = self.agent_registry.get(requested_agent)
            return RouteDecision(
                agent_name=requested_agent,
                intent="手动指定 Agent",
                reason=f"用户已在入口中指定 {agent.display_name}",
                confidence=1.0,
                source="manual",
            )

        try:
            return await self._route_with_llm(prompt)
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            KeyError,
            ValueError,
            json.JSONDecodeError,
        ):
            return self._fallback_route(prompt)

    async def _route_with_llm(self, prompt: str) -> RouteDecision:
        if not self.settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        response = await self._chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self._routing_system_prompt(),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        )
        content = (
            response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        payload = self._parse_json_object(content)
        agent_name = str(payload.get("agent", "")).strip()
        if agent_name not in self._routable_agent_names():
            raise ValueError(f"LLM selected an unsupported agent: {agent_name}")
        self.agent_registry.get(agent_name)
        return RouteDecision(
            agent_name=agent_name,
            intent=self._optional_text(payload.get("intent")),
            reason=self._optional_text(payload.get("reason")),
            confidence=self._optional_float(payload.get("confidence")),
            source="llm",
        )

    async def _chat_completion(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        url = self.settings.deepseek_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.default_model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        return await asyncio.to_thread(self._post_chat_completion, url, headers, payload)

    def _post_chat_completion(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def _routing_system_prompt(self) -> str:
        agent_names = ", ".join(self._routable_agent_names())
        return (
            "你是个人多 Agent 助手的 Supervisor，只负责做意图识别和路由。\n"
            f"只能从这些 agent name 中选择一个：{agent_names}\n\n"
            "判断规则：\n"
            "- programming: 代码、仓库、Git、diff、review、bug、依赖、调试、工程实现。\n"
            "- personal_tools: JSON/PDF/Excel/CSV/OCR、文件处理、格式转换、轻量数据加工。\n"
            "- work: 日报、周报、会议、任务、工作总结、飞书消息或文档准备、飞书发布预览。\n"
            "- scheduler: 提醒、定时、周期任务、cron、未来某个时间触发的计划。\n"
            "只输出一个 JSON 对象，不要解释，不要 Markdown。格式："
            '{"agent":"work","confidence":0.0,"intent":"简短意图","reason":"一句话原因"}'
        )

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match is None:
                raise
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("LLM routing response is not a JSON object")
        return parsed

    def _routable_agent_names(self) -> tuple[str, ...]:
        return tuple(name for name in self.agent_registry.names() if name != "supervisor")

    def _fallback_route(self, prompt: str) -> RouteDecision:
        text = prompt.lower()
        programming_keys = ["git", "repo", "代码", "仓库", "commit", "diff", "review", "依赖", "bug"]
        tools_keys = ["json", "pdf", "excel", "csv", "格式", "转换", "ocr", "文件"]
        work_keys = ["日报", "周报", "会议", "任务", "飞书", "发送", "发布", "总结"]
        schedule_keys = ["提醒", "定时", "cron", "每天", "明天", "稍后", "计划"]

        buckets = [
            ("programming", programming_keys),
            ("personal_tools", tools_keys),
            ("work", work_keys),
            ("scheduler", schedule_keys),
        ]
        for agent_name, keys in buckets:
            if any(key in text for key in keys):
                return RouteDecision(
                    agent_name=agent_name,
                    intent="本地回退匹配",
                    reason="LLM 意图识别不可用，已使用本地兜底规则完成路由。",
                    confidence=None,
                    source="fallback",
                )
        return RouteDecision(
            agent_name="work",
            intent="默认工作请求",
            reason="LLM 意图识别不可用，且本地规则未命中特定 Agent，默认交给 Work Agent。",
            confidence=None,
            source="fallback",
        )

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
