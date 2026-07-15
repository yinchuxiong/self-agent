import asyncio
from typing import Any

from self_agent.app.agents.supervisor import Supervisor
from self_agent.app.core.config import Settings
from self_agent.app.registries.agent_registry import AgentRegistry


class FakeSupervisor(Supervisor):
    def __init__(
        self,
        agent_registry: AgentRegistry,
        response: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__(
            agent_registry,
            Settings(deepseek_api_key="test-key", default_workspace_dir="E:/selfAgent"),
        )
        self.response = response or {}
        self.error = error

    async def _chat_completion(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.response


def test_manual_agent_selection_wins() -> None:
    registry = AgentRegistry("E:/selfAgent")
    supervisor = FakeSupervisor(registry, error=AssertionError("LLM should not be called"))

    decision = asyncio.run(supervisor.route("帮我写日报", requested_agent="programming"))

    assert decision.agent_name == "programming"
    assert decision.intent == "手动指定 Agent"
    assert decision.confidence == 1.0


def test_llm_route_selects_agent_from_json() -> None:
    registry = AgentRegistry("E:/selfAgent")
    supervisor = FakeSupervisor(
        registry,
        response={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"agent":"personal_tools","confidence":0.94,'
                            '"intent":"转换 CSV","reason":"用户要处理文件格式"}'
                        )
                    }
                }
            ]
        },
    )

    decision = asyncio.run(supervisor.route("把这个 CSV 转成 JSON"))

    assert decision.agent_name == "personal_tools"
    assert decision.intent == "转换 CSV"
    assert decision.reason == "用户要处理文件格式"
    assert decision.confidence == 0.94


def test_llm_failure_falls_back_to_local_router() -> None:
    registry = AgentRegistry("E:/selfAgent")
    supervisor = FakeSupervisor(registry, error=TimeoutError("offline"))

    decision = asyncio.run(supervisor.route("明天上午 10 点提醒我喝水"))

    assert decision.agent_name == "scheduler"
    assert decision.source == "fallback"


def test_routable_agent_names_come_from_registry() -> None:
    registry = AgentRegistry("E:/selfAgent")
    supervisor = FakeSupervisor(registry)

    assert set(supervisor._routable_agent_names()) == {
        "programming",
        "personal_tools",
        "work",
        "scheduler",
    }
