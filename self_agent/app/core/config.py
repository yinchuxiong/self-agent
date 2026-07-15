"""
应用配置模块 —— 从 .env 文件读取所有配置项。

这个模块是整个应用的"配置中心"，所有其他模块都通过 get_settings() 获取配置。
配置使用 Pydantic Settings，会自动从项目根目录的 .env 文件加载环境变量。

Python 语法要点：
- from functools import lru_cache：导入缓存装饰器，避免重复创建 Settings 对象
- class Settings(BaseSettings)：继承语法，Settings 继承了 BaseSettings 的所有功能
- str | None：类型联合语法（Python 3.10+），表示这个字段可以是 str 或 None
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── SSL certificate fix for Windows ──────────────────────────────────────
# On Windows, Python's ssl module often can't find the system CA bundle.
# certifi ships a maintained CA bundle that httpx/openai can use directly.
# Set SSL_CERT_FILE early so all subsequent httpx clients pick it up.
if "SSL_CERT_FILE" not in os.environ:
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass  # certifi not installed, let httpx fall back to its own logic


class Settings(BaseSettings):
    """应用设置类 —— 所有配置项的统一入口。

    继承自 pydantic_settings.BaseSettings，会自动从 .env 文件和环境变量中加载配置。
    每个类属性对应一个配置项，可以在 .env 文件中用大写形式设置（如 APP_NAME=我的助手）。

    Python 语法要点：
    - model_config：Pydantic 的特殊属性，用于配置模型行为，这里指定了 .env 文件路径
    - Field(default_factory=lambda: ...)：当默认值需要动态计算时使用，lambda 是一个匿名函数
    """

    # ── Pydantic 模型配置 ──────────────────────────────────────────────────
    # env_file=".env"：从项目根目录的 .env 文件加载配置
    # extra="ignore"：忽略 .env 中未定义的额外配置项，不会报错
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── 应用基本信息 ─────────────────────────────────────────────────────
    app_name: str = "个人工作助手"  # 应用名称，显示在页面标题和日志中
    app_env: str = "development"  # 运行环境：development（开发）/ production（生产）
    api_prefix: str = "/api"  # 所有 API 路由的统一前缀

    # ── CORS 跨域配置 ─────────────────────────────────────────────────────
    # CORS（跨域资源共享）：前端（如 localhost:5173）和后端（如 localhost:8000）不在同一个端口时，
    # 浏览器会阻止前端请求后端。配置 CORS 允许这种跨域访问。
    # Field(default_factory=...) 表示每次创建实例时都会执行 lambda 生成新的默认值，
    # 而不是所有实例共享同一个 list 对象（这是 Python 的可变默认参数陷阱的解决方案）
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ── LLM 大模型配置 ────────────────────────────────────────────────────
    # DeepSeek 是目前使用的 LLM 服务商（国产大模型，性价比高，API 兼容 OpenAI 格式）
    default_model: str = "deepseek-chat"  # 默认使用的模型名称
    deepseek_api_key: str | None = None  # API 密钥，从 .env 文件读取（str | None 表示可为空）
    deepseek_base_url: str = "https://api.deepseek.com"  # DeepSeek API 基础地址
    llm_ssl_verify: bool = True  # 是否验证 LLM API 的 SSL 证书。
    # 如果环境中有 SSL 拦截代理（如杀毒软件的 Web Shield），需要设为 false。
    # 生产环境务必保持 true。

    # ── 数据库配置 ────────────────────────────────────────────────────────
    # SQLite 数据库文件路径（开发环境）。生产环境可以换成 PostgreSQL 连接字符串。
    # sqlite+aiosqlite:/// 前缀表示使用异步 SQLite 驱动
    database_url: str = "sqlite+aiosqlite:///./data/self_agent.db"

    # Qdrant 向量数据库地址（用于未来的 RAG 知识库功能）
    qdrant_url: str = "http://localhost:6333"

    # ── 工作目录 ─────────────────────────────────────────────────────────
    # 默认的工作目录，Agent 在这个目录下执行工具操作（如 Git 命令、文件处理等）
    # Path.cwd() 返回当前进程的工作目录（通常是项目根目录）
    default_workspace_dir: str = Field(default_factory=lambda: str(Path.cwd()))

    # ── 日志配置 ─────────────────────────────────────────────────────────
    log_level: str = "INFO"  # 日志级别：DEBUG / INFO / WARNING / ERROR
    log_dir: str = "data/logs"  # 日志文件存放目录
    log_retention_days: int = 90  # 日志保留天数，超过自动删除

    # ── LangSmith 可观测性配置 ──────────────────────────────────────────
    # LangSmith 是 LangChain 官方提供的调试/监控平台，
    # 可以追踪每次 LLM 调用的输入、输出、耗时、token 消耗等
    langsmith_api_key: str | None = None  # LangSmith API 密钥
    langsmith_project: str = "self-agent"  # LangSmith 项目名称
    langsmith_tracing_v2: bool = True  # 是否启用 v2 版本的追踪
    langsmith_endpoint: str = "https://api.smith.langchain.com"  # LangSmith 服务地址

    # ── LangGraph 检查点配置 ─────────────────────────────────────────────
    # 检查点用于保存 LangGraph 的执行状态（对话历史、中间结果等），
    # 支持断点续传和会话恢复
    checkpoint_backend: str = "sqlite"  # 检查点存储后端：sqlite / postgres
    checkpoint_db_url: str | None = None  # 检查点数据库连接字符串（PostgreSQL 时使用）


# ── 全局配置获取函数 ──────────────────────────────────────────────────────
# @lru_cache 是 Python 标准库中的装饰器（decorator），用于缓存函数返回值。
# 这里的作用：第一次调用 get_settings() 时创建 Settings 对象并缓存，
# 之后每次调用都返回同一个对象，避免重复读取 .env 文件。
# 这是单例模式（Singleton）的一种轻量实现。
@lru_cache
def get_settings() -> Settings:
    """获取应用配置的单例对象（带缓存）。

    用法：
        from self_agent.app.core.config import get_settings
        settings = get_settings()
        print(settings.app_name)  # "个人工作助手"

    Returns:
        Settings 对象，包含所有配置项
    """
    return Settings()
