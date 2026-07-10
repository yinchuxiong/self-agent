from collections.abc import AsyncIterator

from self_agent.app.agents.base import AgentRunResult, AgentRunStep, BaseAgent
from self_agent.app.core.models import SkillDefinition


class PersonalToolsAgent(BaseAgent):
    async def run(self, prompt: str, skills: list[SkillDefinition]) -> AsyncIterator[AgentRunStep]:
        skill_names = [skill.name for skill in skills] or ["format-shifter"]
        answer = (
            "我把这条请求路由给了 Personal Tools Agent。\n\n"
            f"- 识别到的能力：{', '.join(skill_names)}\n"
            "- 初版先完成工具注册、权限信息和界面测试入口。\n"
            "- 后续会把 JSON、PDF、Excel、格式转换工具接到统一 ToolExecutor。"
        )
        yield AgentRunResult(agent=self.definition.name, answer=answer, activated_skills=skill_names)

