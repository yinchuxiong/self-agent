"""
应用全局状态 —— 初始化和管理所有核心服务。

这个模块是应用的"依赖注入容器"（Dependency Injection Container），
在启动时创建所有核心服务实例，并将它们组装在一起。

核心服务包括：
- store：会话和消息存储（SQLite 或内存）
- agent_registry：Agent 注册表（从 .agents/ 目录扫描）
- skill_registry：Skill 和 Tool 注册表
- call_logger：调用日志（统计页面数据源）
- executors：每个 Agent 的工具执行器
- graph：LangGraph 编排图（核心！取代了旧的 AgentRuntime）

Python 语法要点：
- state = AppState()：模块级单例，整个应用共享这一个实例
- __file__：当前文件的路径，用于计算项目根目录
- Path(...).resolve()：将相对路径转为绝对路径
- .parent：Path 的属性，返回父目录（相当于 cd ..）
"""

from pathlib import Path

from self_agent.app.core.config import get_settings
from self_agent.app.graph.checkpointer import get_checkpointer
from self_agent.app.graph.supervisor_graph import build_supervisor_graph
from self_agent.app.observability.call_logger import CallLogger, SQLiteCallLogger
from self_agent.app.registries.agent_loader import AgentLoader
from self_agent.app.registries.agent_registry import AgentRegistry
from self_agent.app.registries.skill_registry import SkillRegistry
from self_agent.app.runtime.agent_runtime import AgentRuntime
from self_agent.app.runtime.store import InMemoryStore, SQLiteStore
from self_agent.app.tools.base import ToolExecutor


class AppState:
    """应用全局状态 —— 单例模式，管理所有服务实例。

    这个类在模块加载时被实例化一次（见文件末尾的 state = AppState()），
    之后所有 API 路由和模块都通过 `from self_agent.app.state import state` 来访问服务。

    Python 语法要点：
    - self.xxx = ...：在 __init__ 中设置的属性成为实例属性
    - 每个 self.xxx 都是这个对象"持有"的服务引用
    - 单例模式确保全局只有一个 AppState，所有服务只初始化一次
    """

    def __init__(self) -> None:
        """初始化所有核心服务。

        初始化顺序很重要：
        1. 先加载配置
        2. 根据配置决定使用 SQLite 还是内存存储
        3. 创建注册表（扫描 .agents/ 目录）
        4. 为每个 Agent 创建 ToolExecutor
        5. 构建 LangGraph 编排图
        """
        settings = get_settings()

        # ── 判断是否使用 SQLite ──────────────────────────────────────────
        # 如果数据库 URL 以 sqlite:/// 开头，使用 SQLiteStore，否则用内存存储
        # Python str.startswith() 可以接受元组，检查是否以其中任意一个开头
        sqlite_enabled = settings.database_url.startswith(("sqlite:///", "sqlite+aiosqlite:///"))

        # ── 计算项目根目录 ───────────────────────────────────────────────
        # __file__ 是当前文件路径（如 E:\selfAgent\self_agent\app\state.py）
        # .parent 返回父目录，三次 .parent 回到项目根目录
        # 然后拼接 .agents/ 得到 Agent 配置目录
        agents_dir = str(Path(__file__).resolve().parent.parent.parent / ".agents")

        # ── 核心服务初始化 ───────────────────────────────────────────────
        # 三元表达式：如果 sqlite_enabled 为 True 用 SQLiteStore，否则用 InMemoryStore
        self.store = SQLiteStore(settings.database_url) if sqlite_enabled else InMemoryStore()

        # 创建 Agent 注册表 —— 扫描 .agents/ 目录加载所有 Agent 配置
        self.agent_registry = AgentRegistry(settings.default_workspace_dir, agents_dir)

        # 创建 Skill 注册表 —— 扫描 .agents/*/skills/ 目录
        self.skill_registry = SkillRegistry(agents_dir)

        # 创建调用日志记录器
        self.call_logger = (
            SQLiteCallLogger(settings.database_url) if sqlite_enabled else CallLogger()
        )

        # ── 旧版运行时（保留以兼容旧代码） ──────────────────────────────
        # AgentRuntime 是旧的非图架构，已被 LangGraph 取代，但保留以供参考
        self.runtime = AgentRuntime(
            store=self.store,
            agent_registry=self.agent_registry,
            skill_registry=self.skill_registry,
            call_logger=self.call_logger,
        )

        # ── LangGraph：Agent 加载器 ─────────────────────────────────────
        # AgentLoader 负责从文件系统加载 Agent 类、工具模块、MCP 配置等
        agent_loader = AgentLoader(
            agents_dir=agents_dir,
            workspace_dir=settings.default_workspace_dir,
        )

        # ── LangGraph：为每个 Agent 创建工具执行器 ─────────────────────
        # executors 是一个字典，键是 Agent 名称，值是 ToolExecutor 实例
        # ToolExecutor 负责安全管理工具函数的注册和执行
        self.executors: dict[str, ToolExecutor] = {}

        # 遍历所有注册的 Agent（跳过 supervisor，它是路由器不是业务 Agent）
        for agent_def in self.agent_registry.list():
            if agent_def.name == "supervisor":
                continue  # supervisor 是框架级 Agent，不需要工具

            # 为当前 Agent 创建工具执行器
            executor = ToolExecutor(
                workspace_dir=agent_def.workspace_dir,
                allowed_paths=agent_def.allowed_paths,
            )

            try:
                # 从文件系统加载工具模块并注册到执行器中
                # 例如：.agents/programming/tools/ 目录下的 Python 文件
                registered = agent_loader.register_tools_from_dir(
                    agent_def.name, executor
                )
                if registered:
                    import logging
                    logging.getLogger(__name__).info(
                        "Registered %d tools for agent %s: %s",
                        len(registered),
                        agent_def.name,
                        registered,
                    )
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to register tools for agent: %s", agent_def.name,
                    exc_info=True,  # 打印完整异常堆栈便于排查
                )

            # 将创建好的执行器存入字典
            self.executors[agent_def.name] = executor

        # ── LangGraph：创建检查点保存器 ───────────────────────────────
        # 检查点用于持久化图执行状态，支持会话恢复
        # get_checkpointer() 返回 (checkpointer, cleanup_fn)
        self.checkpointer, self._checkpointer_cleanup = get_checkpointer()

        # ── LangGraph：构建并编译编排图 ───────────────────────────────
        # 这是整个应用的核心 —— 一个 LangGraph 状态图，包含了：
        # Supervisor（路由器）→ 4 个 Agent 子图（ReAct 循环）
        self.graph = build_supervisor_graph(
            agent_registry=self.agent_registry,
            skill_registry=self.skill_registry,
            agent_loader=agent_loader,
            checkpointer=self.checkpointer,
        )

    def close(self) -> None:
        """清理资源 —— 关闭所有需要关闭的服务。

        在应用关闭时（on_event("shutdown")）调用，确保数据库连接等资源被正确释放。

        Python 语法要点：
        - getattr(service, "close", None)：安全地获取对象的 close 属性，
          如果对象没有 close 方法，返回 None 而不是抛出 AttributeError
        - if close is not None：检查 close 是否可调用
        - close()：如果有 close 方法就调用它
        """
        for service in (self.store, self.call_logger):
            close = getattr(service, "close", None)
            if close is not None:
                close()
        # Clean up checkpointer context manager
        if hasattr(self, "_checkpointer_cleanup") and self._checkpointer_cleanup:
            self._checkpointer_cleanup()


# ── 全局应用状态单例 ─────────────────────────────────────────────────────
# 这行代码在模块被第一次 import 时执行，创建唯一的 AppState 实例。
# 之后所有模块通过 `from self_agent.app.state import state` 访问同一个实例。
state = AppState()
