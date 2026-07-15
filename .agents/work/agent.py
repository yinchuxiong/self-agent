"""Work Agent: handles daily reports, meeting notes, task tracking, and Feishu publishing."""

from collections.abc import AsyncIterator

from self_agent.app.agents.base import AgentRunResult, AgentRunStep, BaseAgent
from self_agent.app.core.models import SkillDefinition


class WorkAgent(BaseAgent):
    async def run(self, prompt: str, skills: list[SkillDefinition]) -> AsyncIterator[AgentRunStep]:
        skill_names = [skill.name for skill in skills] or ["daily-reporter"]
        answer = (
            "我把这条请求路由给了 Work Agent。\n\n"
            f"- 识别到的能力：{', '.join(skill_names)}\n"
            "- 当前可生成日报、任务和会议内容草稿。\n"
            "- 飞书发布属于外部影响操作，后续会默认走预览确认。"
        )
        yield AgentRunResult(agent=self.definition.name, answer=answer, activated_skills=skill_names)
