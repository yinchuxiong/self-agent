"""
数据模型模块 —— 定义整个应用中使用的所有数据结构。

这个模块使用 Pydantic BaseModel 来定义数据结构，Pydantic 会：
1. 自动校验数据类型（如 str 字段不能填数字）
2. 自动生成 JSON Schema（用于 API 文档）
3. 提供类型提示（IDE 自动补全）

Python 语法要点：
- class XXX(BaseModel)：创建一个 Pydantic 数据模型
- StrEnum：字符串枚举，每个值都是字符串，可以用于限定字段的可选值
- Field(default_factory=...)：动态默认值，避免可变默认参数陷阱
- str | None：等价于 Union[str, None]（Python 3.10+ 语法）
"""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


# ── 工具函数 ──────────────────────────────────────────────────────────────

def utc_now() -> datetime:
    """获取当前 UTC 时间。

    UTC（协调世界时）是全球统一的时间标准，不随时区变化。
    使用 UTC 存储时间可以避免时区转换问题，显示时再转为本地时间。

    Python 语法要点：
    - datetime.now(timezone.utc)：带时区信息的当前时间
    - 如果写成 datetime.utcnow()，得到的是不带时区的"裸"时间（不推荐）
    """
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """生成唯一 ID，格式为 {前缀}_{16位随机十六进制字符}。

    例如：new_id("sess") → "sess_a1b2c3d4e5f6g7h8"
    这种 ID 比 UUID 短，方便日志查看和调试。

    Python 语法要点：
    - uuid4().hex：生成随机 UUID 并转为十六进制字符串（32 位）
    - [:16]：字符串切片，取前 16 个字符
    - f"{prefix}_{...}"：f-string 格式化字符串
    """
    return f"{prefix}_{uuid4().hex[:16]}"


# ── 枚举类（Enum）──────────────────────────────────────────────────────
# 枚举用于限定某个字段只能取固定的几个值，比直接用字符串更安全（IDE 可以补全，写错会报错）

class PermissionLevel(StrEnum):
    """权限级别枚举 —— 控制 Agent / Skill / Tool 的权限边界。

    用于安全控制：不同操作需要不同的权限级别。
    StrEnum 是 Python 3.11 新增的类型，每个枚举值都是字符串，
    可以直接用于字符串比较和 JSON 序列化。
    """
    read = "read"               # 只读：查看状态、读取文件
    write = "write"             # 写入：修改文件、创建提交
    execute = "execute"         # 执行：运行脚本、执行命令
    external_publish = "external_publish"  # 外部发布：发送飞书消息等
    dangerous = "dangerous"     # 危险操作：删除文件、强制推送等


class CallStatus(StrEnum):
    """调用状态枚举 —— 记录每次 Agent/Tool 调用的执行结果。"""
    success = "success"                 # 成功
    failed = "failed"                   # 失败
    timeout = "timeout"                 # 超时
    cancelled = "cancelled"             # 被取消
    permission_denied = "permission_denied"  # 权限不足


# ── 核心数据模型（Pydantic BaseModel）───────────────────────────────────
# 每个类都是一个"数据模具"，创建实例时 Pydantic 会自动校验类型

class AgentDefinition(BaseModel):
    """Agent 定义 —— 描述一个 AI Agent 的配置信息。

    每个 Agent 是一个独立的 AI 角色（如编程助手、工作助手等），
    有自己的名称、描述、权限、工作目录和配备的技能。

    Python 语法要点：
    - id: str：类型注解，Pydantic 会校验这个字段必须是字符串
    - enabled: bool = True：有默认值的字段，创建实例时可以省略
    - Field(default_factory=list)：每次创建实例时生成新的空列表，避免共享可变对象
    """
    id: str                              # 唯一标识，如 "agent_programming"
    name: str                            # 内部名称，如 "programming"
    display_name: str                    # 显示名称，如 "编程 Agent"
    description: str                     # 功能描述
    enabled: bool = True                 # 是否启用（禁用后不会出现在路由选项中）
    default_model: str = "deepseek-chat" # 默认使用的 LLM 模型
    workspace_dir: str                   # Agent 的工作目录
    allowed_paths: list[str] = Field(default_factory=list)  # 允许访问的目录列表（安全沙箱）
    permission_level: PermissionLevel = PermissionLevel.read  # 权限级别
    equipped_skills: list[str] = Field(default_factory=list) # 配备的技能名称列表
    status: str = "idle"                 # 状态：idle（空闲）/ running（运行中）/ disabled（已禁用）


class SkillDefinition(BaseModel):
    """Skill 定义 —— 描述一个技能的元数据。

    Skill 是 Agent 可以调用的能力单元，如"代码审查"、"JSON 格式化"等。
    每个 Skill 可以设置触发关键词，当用户消息包含关键词时自动激活。

    关于 Pydantic v1 vs v2：
    本项目使用 Pydantic v2，主要区别：
    - v1: class Config: orm_mode = True
    - v2: model_config = ConfigDict(from_attributes=True)
    """
    id: str                              # 唯一标识
    name: str                            # 内部名称
    display_name: str                    # 显示名称
    description: str                     # 功能描述
    category: str                        # 分类：programming / file / workflow 等
    version: str = "0.1.0"              # 版本号
    enabled: bool = True                 # 是否启用
    triggers: list[str] = Field(default_factory=list)  # 触发关键词列表
    owner_agents: list[str] = Field(default_factory=list)  # 绑定到哪些 Agent
    permission_level: PermissionLevel = PermissionLevel.read  # 权限级别
    confirm_required: bool = False       # 是否需要用户确认后才能执行


class ToolDefinition(BaseModel):
    """Tool 定义 —— 描述一个工具的元数据（不含实际执行逻辑）。

    Tool 是比 Skill 更底层的操作单元，如"git_status"、"read_file" 等。
    实际的工具执行由 ToolExecutor 负责，这里只存储元数据用于 API 展示。

    Python 语法要点：
    - dict[str, Any]：泛型类型注解，表示键为字符串、值为任意类型的字典
    """
    id: str                              # 唯一标识
    name: str                            # 工具名称
    display_name: str                    # 显示名称
    description: str                     # 功能描述
    owner_skill: str                     # 所属 Skill 名称
    permission_level: PermissionLevel = PermissionLevel.read  # 权限级别
    timeout_seconds: int = 30            # 超时时间（秒）
    enabled: bool = True                 # 是否启用
    parameter_schema: dict[str, Any] = Field(default_factory=dict)  # 参数 JSON Schema


class ChatSession(BaseModel):
    """聊天会话 —— 代表一次对话。

    每个会话包含多条消息，有自己的标题和工作目录。
    前端左侧的会话列表就是由这个模型驱动的。

    Python 语法要点：
    - Field(default_factory=lambda: new_id("sess"))：使用 lambda 生成动态默认值
      不能写成 Field(default=new_id("sess"))，因为 Python 在类定义时就会计算 default 值，
      导致所有实例共享同一个 ID。default_factory 在创建每个实例时才调用。
    """
    id: str = Field(default_factory=lambda: new_id("sess"))  # 会话 ID
    title: str = "新会话"               # 会话标题（首条用户消息的前 24 字自动成为标题）
    workspace_dir: str = ""             # 此会话绑定的工作目录
    created_at: datetime = Field(default_factory=utc_now)   # 创建时间
    updated_at: datetime = Field(default_factory=utc_now)   # 最后更新时间


class ChatMessage(BaseModel):
    """聊天消息 —— 对话中的一条记录。

    既包括用户发送的消息（role="user"），也包括 AI 的回复（role="assistant"）。

    Python 语法要点：
    - agent_name: str | None = None：表示这个字段可以是 str 或 None，默认为 None
      str | None 是 Python 3.10+ 的语法糖，等价于 Optional[str]
    """
    id: str = Field(default_factory=lambda: new_id("msg"))  # 消息 ID
    session_id: str                      # 所属会话 ID
    role: str                            # 角色：user（用户）/ assistant（AI）
    content: str                         # 消息内容
    agent_name: str | None = None        # 处理此消息的 Agent 名称（用户消息为 None）
    trace_id: str | None = None          # 追踪 ID，用于 LangSmith 调试
    created_at: datetime = Field(default_factory=utc_now)  # 创建时间


class ChatRequest(BaseModel):
    """聊天请求 —— 前端发送给后端的请求数据。

    当前端用户输入消息并点击发送时，会构造这个请求发送给 POST /api/chat/sessions/{id}/messages。
    """
    content: str                         # 用户输入的消息内容
    agent_name: str | None = None        # 指定使用的 Agent（None 或 "auto" 表示自动路由）
    workspace_dir: str | None = None     # 临时指定工作目录
    entrypoint: str = "web_ui"          # 入口来源：web_ui（网页）/ api（API 调用）等


class ChatEvent(BaseModel):
    """SSE 事件 —— 后端推送给前端的实时进度事件。

    SSE（Server-Sent Events）是一种服务器主动向客户端推送数据的技术。
    前端通过 EventSource API 接收这些事件，实时显示 Agent 的工作进度。

    事件类型包括：
    - supervisor_started：Supervisor 开始分析意图
    - agent_started：路由到了某个 Agent
    - skill_activated：激活了某个 Skill
    - tool_started / tool_result：工具执行开始 / 结果
    - answer_delta：AI 回答的增量文本（流式输出，打字机效果）
    - final：最终完整回答
    - error：错误事件
    """
    event: str                           # 事件类型
    trace_id: str                        # 追踪 ID
    message: str                         # 事件描述文本
    agent: str | None = None             # 当前 Agent 名称
    skill: str | None = None             # 当前 Skill 名称
    data: dict[str, Any] = Field(default_factory=dict)  # 附加数据（路由信息、工具参数等）


class CallLog(BaseModel):
    """调用日志 —— 记录一次完整的 Agent 调用过程。

    用于统计页面的指标展示（调用次数、成功率、P95 延迟等）和问题排查。

    Python 语法要点：
    - 这个模型字段很多，但都遵循同样的模式：
      必需字段（无默认值）+ 可选字段（有默认值 None 或 0）
    """
    id: str = Field(default_factory=lambda: new_id("call"))  # 日志 ID
    trace_id: str                        # 追踪 ID
    session_id: str | None = None        # 会话 ID
    entrypoint: str = "web_ui"          # 入口来源
    agent_name: str | None = None        # 使用的 Agent
    skill_name: str | None = None        # 激活的 Skill
    tool_name: str | None = None         # 使用的 Tool
    workflow_name: str | None = None     # 执行的工作流
    workspace_dir: str | None = None     # 工作目录
    status: CallStatus                   # 执行状态
    started_at: datetime                 # 开始时间
    finished_at: datetime                # 结束时间
    latency_ms: int                      # 延迟（毫秒），finished_at - started_at
    input_summary: str                   # 输入摘要（截取前 120 字符）
    output_summary: str                  # 输出摘要（截取前 160 字符）
    error_type: str | None = None        # 错误类型（如 "ValueError"）
    error_message: str | None = None     # 错误信息
    input_tokens: int = 0                # 输入 token 数（用于成本估算）
    output_tokens: int = 0               # 输出 token 数
    cost_estimate: float = 0             # 预估费用（元）
    created_at: datetime = Field(default_factory=utc_now)  # 日志创建时间


class MetricOverview(BaseModel):
    """指标概览 —— 统计页面仪表盘展示的汇总数据。

    Python 语法要点：
    - P95 延迟：95% 的请求都在这个时间内完成，
      比平均值更能反映真实用户体验（排除极端慢的请求）
    """
    total_calls: int                     # 总调用次数
    success_rate: float                  # 成功率（0.0 ~ 1.0）
    failed_calls: int                    # 失败次数
    avg_latency_ms: int                  # 平均延迟（毫秒）
    p95_latency_ms: int                  # P95 延迟（毫秒）
    token_usage: int                     # 总 token 消耗
    cost_estimate: float                 # 总预估费用
    recent_errors: list[CallLog]         # 最近的错误日志列表
