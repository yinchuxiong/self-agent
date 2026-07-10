from self_agent.app.core.models import PermissionLevel, SkillDefinition, ToolDefinition


class SkillRegistry:
    """In-memory Skill and Tool registry.

    M2 can extend this with YAML hot-loading while preserving these list/match methods.
    """

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}
        self._tools: dict[str, ToolDefinition] = {}
        self._seed()

    def _seed(self) -> None:
        # Seed enough capability metadata for routing, management pages, and audit previews.
        skills = [
            SkillDefinition(
                id="skill_git_manager",
                name="git-manager",
                display_name="Git 管理",
                description="读取仓库状态、分支、提交历史和差异，为后续执行做准备。",
                category="programming",
                triggers=["git", "提交", "分支", "diff", "commit"],
                owner_agents=["programming"],
                permission_level=PermissionLevel.execute,
                confirm_required=True,
            ),
            SkillDefinition(
                id="skill_code_reviewer",
                name="code-reviewer",
                display_name="代码审查",
                description="对代码差异做风险分级审查，输出问题、证据和修复建议。",
                category="programming",
                triggers=["review", "审查", "代码检查", "bug"],
                owner_agents=["programming"],
                permission_level=PermissionLevel.read,
            ),
            SkillDefinition(
                id="skill_repo_doctor",
                name="repo-doctor",
                display_name="仓库体检",
                description="检查依赖、仓库结构、忽略规则和潜在维护风险。",
                category="programming",
                triggers=["仓库", "依赖", "健康", "体检"],
                owner_agents=["programming"],
                permission_level=PermissionLevel.read,
            ),
            SkillDefinition(
                id="skill_json_master",
                name="json-master",
                display_name="JSON 工具",
                description="格式化、校验、查询和比较 JSON 数据。",
                category="tools",
                triggers=["json", "schema", "格式化"],
                owner_agents=["personal_tools"],
                permission_level=PermissionLevel.write,
            ),
            SkillDefinition(
                id="skill_format_shifter",
                name="format-shifter",
                display_name="格式转换",
                description="在 Markdown、CSV、JSON、文本等格式之间转换。",
                category="tools",
                triggers=["转换", "导出", "格式"],
                owner_agents=["personal_tools"],
                permission_level=PermissionLevel.write,
            ),
            SkillDefinition(
                id="skill_pdf_master",
                name="pdf-master",
                display_name="PDF 处理",
                description="提取、合并、拆分 PDF，并预留 OCR 接口。",
                category="tools",
                triggers=["pdf", "ocr", "提取"],
                owner_agents=["personal_tools"],
                permission_level=PermissionLevel.write,
            ),
            SkillDefinition(
                id="skill_daily_reporter",
                name="daily-reporter",
                display_name="日报生成",
                description="汇总输入、提交记录和任务进展，生成日报草稿。",
                category="work",
                triggers=["日报", "周报", "总结"],
                owner_agents=["work"],
                permission_level=PermissionLevel.read,
            ),
            SkillDefinition(
                id="skill_feishu_publisher",
                name="feishu-publisher",
                display_name="飞书发布",
                description="准备飞书消息、文档和交互卡片，发布动作默认需要确认。",
                category="work",
                triggers=["飞书", "发送", "发布"],
                owner_agents=["work"],
                permission_level=PermissionLevel.external_publish,
                confirm_required=True,
            ),
            SkillDefinition(
                id="skill_reminder",
                name="reminder",
                display_name="提醒",
                description="创建一次性提醒，后续接入 APScheduler 持久化执行。",
                category="scheduled",
                triggers=["提醒", "定时", "稍后"],
                owner_agents=["scheduler"],
                permission_level=PermissionLevel.write,
            ),
        ]
        self._skills = {skill.name: skill for skill in skills}
        self._tools = {
            "git_status": ToolDefinition(
                id="tool_git_status",
                name="git_status",
                display_name="查看仓库状态",
                description="返回目标仓库的当前分支和工作区状态。",
                owner_skill="git-manager",
                permission_level=PermissionLevel.read,
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "include_untracked": {
                            "type": "boolean",
                            "description": "是否包含未跟踪的文件，默认 true",
                        },
                    },
                },
            ),
            "git_diff": ToolDefinition(
                id="tool_git_diff",
                name="git_diff",
                display_name="查看代码差异",
                description="读取工作区、暂存区或提交间差异。",
                owner_skill="git-manager",
                permission_level=PermissionLevel.read,
                timeout_seconds=30,
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "staged": {
                            "type": "boolean",
                            "description": "为 true 时查看暂存区差异（git diff --staged），默认 false 查看工作区差异",
                        },
                        "target": {
                            "type": "string",
                            "description": "可选，指定文件路径或 commit hash 来限制差异范围",
                        },
                    },
                },
            ),
            "git_log": ToolDefinition(
                id="tool_git_log",
                name="git_log",
                display_name="查看提交历史",
                description="查看 Git 提交历史，支持按数量、作者和时间范围过滤。",
                owner_skill="git-manager",
                permission_level=PermissionLevel.read,
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "count": {
                            "type": "integer",
                            "description": "返回的提交记录数量，默认 20",
                        },
                        "author": {
                            "type": "string",
                            "description": "可选，按作者过滤",
                        },
                        "since": {
                            "type": "string",
                            "description": "可选，起始日期，如 '2026-07-01' 或 'today'",
                        },
                    },
                },
            ),
            "code_review": ToolDefinition(
                id="tool_code_review",
                name="code_review",
                display_name="代码审查",
                description="对 diff 做 bug、安全和可维护性审查。",
                owner_skill="code-reviewer",
                permission_level=PermissionLevel.read,
            ),
            "json_format": ToolDefinition(
                id="tool_json_format",
                name="json_format",
                display_name="格式化 JSON",
                description="格式化或压缩 JSON 文本。",
                owner_skill="json-master",
                permission_level=PermissionLevel.write,
            ),
            "daily_report_gen": ToolDefinition(
                id="tool_daily_report_gen",
                name="daily_report_gen",
                display_name="生成日报草稿",
                description="根据输入和模板生成日报草稿。",
                owner_skill="daily-reporter",
                permission_level=PermissionLevel.read,
            ),
            "reminder_once": ToolDefinition(
                id="tool_reminder_once",
                name="reminder_once",
                display_name="一次性提醒",
                description="登记一次性提醒任务。",
                owner_skill="reminder",
                permission_level=PermissionLevel.write,
            ),
        }

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def match_skills(self, agent_name: str, text: str) -> list[SkillDefinition]:
        """Match enabled skills by simple triggers for the MVP routing loop."""
        normalized = text.lower()
        matched: list[SkillDefinition] = []
        for skill in self._skills.values():
            if not skill.enabled or agent_name not in skill.owner_agents:
                continue
            if any(trigger.lower() in normalized for trigger in skill.triggers):
                matched.append(skill)
        return matched
