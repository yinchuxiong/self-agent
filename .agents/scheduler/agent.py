"""Scheduler Agent: manages reminders, cron tasks, and scheduled workflow triggers."""

from collections.abc import AsyncIterator

from self_agent.app.agents.base import AgentRunResult, AgentRunStep, BaseAgent
from self_agent.app.core.models import SkillDefinition


class SchedulerAgent(BaseAgent):
    async def run(self, prompt: str, skills: list[SkillDefinition]) -> AsyncIterator[AgentRunStep]:
        skill_names = [skill.name for skill in skills] or ["reminder"]
        answer = (
            "我把这条请求路由给了 Scheduler Agent。\n\n"
            f"- 识别到的能力：{', '.join(skill_names)}\n"
            "- 初版先登记任务模型和管理页，真正触发执行会接 APScheduler。\n"
            "- 高风险定时任务不会静默执行，需要预授权或转待确认。"
        )
        yield AgentRunResult(agent=self.definition.name, answer=answer, activated_skills=skill_names)
