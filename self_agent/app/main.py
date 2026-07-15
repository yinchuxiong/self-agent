"""
FastAPI 应用工厂 —— 创建和配置 Web 服务。

这个模块是整个后端应用的"入口"：它创建 FastAPI 实例，配置日志、CORS、
注册所有 API 路由，最后导出一个 `app` 对象给 uvicorn 启动。

架构说明：
- 使用"应用工厂"模式（create_app 函数）而不是全局变量，便于测试
- 模块末尾的 `app = create_app()` 创建了模块级单例，供 uvicorn 使用

Python 语法要点：
- from ... import ...：相对/绝对导入，从其他模块引入需要的函数和类
- @app.get("/path")：FastAPI 装饰器（decorator），将函数注册为 HTTP GET 处理器
- async def：异步函数，可以并发处理多个请求而不阻塞
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 从项目的其他模块导入所需组件
# Python 的 import 路径规则：self_agent 是顶级包名，点号表示子模块
from self_agent.app.api import agents, chat, placeholders, skills, statistics, tools
from self_agent.app.core.config import get_settings
from self_agent.app.state import state


def setup_logging(settings) -> None:
    """配置日志系统：同时输出到控制台和文件。

    日志级别（从低到高）：
    - DEBUG（10）：详细的调试信息，开发时使用
    - INFO（20）：一般信息，记录正常运行状态
    - WARNING（30）：警告信息，可能有问题但系统仍能运行
    - ERROR（40）：错误信息，某些功能无法正常工作

    日志轮转：每天午夜自动创建新的日志文件，旧文件保留 90 天。

    Python 语法要点：
    - TimedRotatingFileHandler：按时间自动轮转日志文件的处理器
    - setLevel()：设置日志级别，低于该级别的日志不会被记录
    - logging.getLogger(name)：获取指定名称的 logger，相同名称返回同一个实例
    - -> None：函数返回值类型注解，None 表示不返回任何值
    """

    root = logging.getLogger()  # 获取根 logger

    # 防止重复添加 handler（当 main.py 被多次导入时）
    if root.handlers:
        return

    # 确保日志目录存在
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 日志格式：时间 | 级别 | 模块:行号 | 消息
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── 文件处理器 —— 每日轮转 ──────────────────────────────────────────
    file_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "app.log"),  # 日志文件路径
        when="midnight",                     # 每天午夜轮转
        interval=1,                          # 每 1 天轮转一次
        backupCount=settings.log_retention_days,  # 保留 90 天的旧日志
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别（DEBUG 及以上）
    file_handler.setFormatter(fmt)

    # ── 控制台处理器 —— 输出到终端（stderr） ────────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    # 控制台只显示配置的级别及以上（如 INFO 时隐藏 DEBUG）
    console_handler.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    console_handler.setFormatter(fmt)

    # ── 配置根 logger ────────────────────────────────────────────────────
    root.setLevel(logging.DEBUG)  # 根级别设为 DEBUG，具体输出由各 handler 控制
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # ── 降低第三方库的日志噪音 ──────────────────────────────────────────
    # uvicorn、httpx、LangChain 等库默认输出大量 DEBUG 日志，调高它们到 WARNING
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "httpx",
        "urllib3",
        # LangChain / LangGraph 内部日志
        "langchain",
        "langchain_core",
        "langchain_openai",
        "langgraph",
        "langsmith",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。

    这个函数执行以下步骤：
    1. 加载配置
    2. 初始化日志
    3. 创建 FastAPI 实例
    4. 配置 CORS 中间件
    5. 注册 API 路由

    应用工厂模式的好处：
    - 测试时可以创建多个独立的 app 实例，互不干扰
    - 不同环境（开发/测试/生产）可以有不同的配置

    Python 语法要点：
    - FastAPI(title=..., version=...)：创建 FastAPI 应用实例
    - @app.get("/path")：将函数注册为 GET 路由处理器
    - @app.on_event("shutdown")：注册应用关闭时的回调函数
    - app.add_middleware(...)：添加中间件（在请求处理链中插入额外逻辑）
    - app.include_router(router, prefix=...)：注册子路由，prefix 会加到所有路由前面

    Returns:
        配置好的 FastAPI 应用实例
    """
    settings = get_settings()
    setup_logging(settings)

    # 创建 FastAPI 应用
    app = FastAPI(title=settings.app_name, version="0.1.0")

    # ── CORS 中间件配置 ──────────────────────────────────────────────────
    # 前端开发服务器（Vite）运行在 localhost:5173，后端在 localhost:8000，
    # 浏览器会因为"同源策略"阻止前端请求后端。CORS 中间件告诉浏览器"这个跨域请求是允许的"。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,  # 允许哪些前端地址可以访问
        allow_credentials=True,                # 允许携带 Cookie
        allow_methods=["*"],                   # 允许所有 HTTP 方法（GET, POST, DELETE 等）
        allow_headers=["*"],                   # 允许所有请求头
    )

    # ── 健康检查端点 ────────────────────────────────────────────────────
    # 这是一个简单的 GET 接口，用于确认服务是否正常运行。
    # 访问 http://localhost:8000/api/health
    # Decorator（装饰器）语法：@app.get(...) 将下面的函数注册为路由处理器
    @app.get("/api/health")
    async def health() -> dict:
        """健康检查接口。"""
        return {"status": "ok", "app": settings.app_name, "env": settings.app_env}

    # ── 应用关闭时的清理回调 ─────────────────────────────────────────
    # 使用 on_event("shutdown") 注册关闭事件处理器。
    # 注意：FastAPI 新版本推荐使用 lifespan 上下文管理器替代 on_event
    @app.on_event("shutdown")
    async def shutdown() -> None:
        """应用关闭时清理资源（关闭数据库连接等）。"""
        state.close()

    # ── 注册 API 子路由 ────────────────────────────────────────────────
    # include_router：将子路由模块"挂载"到主应用上
    # prefix=settings.api_prefix：所有子路由的路径会自动加上 /api 前缀
    # 例如：chat.router 中定义了 /chat/sessions，实际路径变为 /api/chat/sessions
    app.include_router(chat.router, prefix=settings.api_prefix)
    app.include_router(agents.router, prefix=settings.api_prefix)
    app.include_router(skills.router, prefix=settings.api_prefix)
    app.include_router(tools.router, prefix=settings.api_prefix)
    app.include_router(statistics.router, prefix=settings.api_prefix)
    app.include_router(placeholders.router, prefix=settings.api_prefix)

    return app


# ── 模块级应用实例 ────────────────────────────────────────────────────────
# 当 uvicorn 启动时（如 uvicorn self_agent.app.main:app），它会加载这个模块，
# 然后读取这个 `app` 变量作为 ASGI 应用入口。
app = create_app()
