from collections.abc import AsyncIterator
from typing import Union

from pydantic import BaseModel, Field

from self_agent.app.core.models import AgentDefinition, ChatEvent, SkillDefinition


class AgentRunResult(BaseModel):
    agent: str
    answer: str
    activated_skills: list[str] = Field(default_factory=list)


# A run step is either an intermediate SSE event (tool progress) or the final result.
AgentRunStep = Union[ChatEvent, AgentRunResult]


class BaseAgent:
    def __init__(self, definition: AgentDefinition) -> None:
        self.definition = definition

    async def run(self, prompt: str, skills: list[SkillDefinition]) -> AsyncIterator[AgentRunStep]:
        """Execute the agent logic, yielding progress events and ending with AgentRunResult.

        Subclasses should yield ChatEvent for intermediate progress (tool calls, etc.)
        and end the generator with yield of AgentRunResult.
        """
        raise NotImplementedError

    # Keep the old signature as a convenience wrapper for simple agents.
    async def run_simple(self, prompt: str, skills: list[SkillDefinition]) -> AgentRunResult:
        """Default: iterate run() and return the final result, ignoring intermediate events."""
        result = AgentRunResult(agent=self.definition.name, answer="")
        async for step in self.run(prompt, skills):
            if isinstance(step, AgentRunResult):
                result = step
        return result

