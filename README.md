# 个人工作助手 v0.1

这是按 `需求/技术方案.md` 落地的初版工程骨架，当前目标对齐 M1：从 Web UI 发消息，经 Supervisor 路由到单个领域 Agent，并通过 SSE 返回过程事件和最终答案。

## 当前已实现

- FastAPI 后端应用入口和健康检查。
- 会话创建、会话详情、消息发送和 SSE 流式输出。
- SQLite 持久化会话、消息和调用日志；默认使用 `DATABASE_URL=sqlite+aiosqlite:///./data/self_agent.db`。
- AgentRegistry：Supervisor、Programming、Personal Tools、Work、Scheduler 默认配置。
- SkillRegistry / ToolRegistry：第一批 Skill 与 Tool 元信息。
- Supervisor 规则路由：按请求内容或手动指定 Agent 分发。
- 调用日志与统计总览。
- React + TypeScript + Ant Design 工作台：
  - 对话
  - Agent 管理
  - 能力管理
  - 知识库
  - 任务
  - 统计
  - 设置
- Docker Compose 草案：api、frontend、postgres、qdrant。

## 本地开发

后端需要 Python 3.11：

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e .
uvicorn self_agent.app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

打开 `http://localhost:5173`。

## Docker Compose

复制环境变量：

```bash
cp .env.example .env
```

启动：

```bash
docker compose up --build
```

## 后续里程碑

1. 在 SQLite 持久化基础上接 PostgreSQL，补齐 Agent/Skill 配置持久化。
2. 接 LangGraph + LangChain ChatModel，把当前规则 Agent 替换为真实 Agent Graph。
3. 实现 PermissionService、ConfirmationService 和 ToolExecutor。
4. 接 WorkflowRegistry / WorkflowEngine / APScheduler。
5. 接 Qdrant 知识库与长期记忆。
6. 接 MCPRegistry 和飞书 Bot。
