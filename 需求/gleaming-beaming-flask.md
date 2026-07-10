# 个人工作助手 — 需求文档 v0.3

## 一、项目定位

基于 **LangChain + LangGraph** 构建的**多 Agent 协作系统**，独立 Python 应用，部署在个人服务器上长期运行。核心特征：

- **Agent 独立可运行**：每个领域 Agent 是自包含的，有专属工具 + 共享公共工具，可独立对外提供服务
- **多 Agent 协同**：一次用户请求可能涉及多个 Agent 协作，由 Supervisor 编排调度
- **多入口交互**：Web UI（管理面板+对话）+ 飞书 Bot + CLI
- **知识库驱动**：向量数据库支撑长期记忆、文档检索、上下文增强

---

## 二、Agent 体系架构

### 2.1 四层架构

```
                        ┌──────────────────────┐
                        │    Supervisor Agent    │
                        │  意图识别 · 编排 · 聚合 │
                        └──┬───────┬───────┬────┘
               ┌───────────┘       │       └───────────┐
               ▼                   ▼                   ▼
        ┌────────────┐      ┌────────────┐      ┌────────────┐
        │  Agent A   │      │  Agent B   │      │  Agent C   │    ← 领域自治
        │            │      │            │      │            │
        │ ┌────────┐ │      │ ┌────────┐ │      │ ┌────────┐ │
        │ │Skill A1│ │      │ │Skill B1│ │      │ │Skill C1│ │    ← 可复用能力包
        │ │┌──────┐│ │      │ │┌──────┐│ │      │ │┌──────┐│ │
        │ ││Tools ││ │      │ ││Tools ││ │      │ ││Tools ││ │    ← 原子函数
        │ │└──────┘│ │      │ │└──────┘│ │      │ │└──────┘│ │
        │ └────────┘ │      │ └────────┘ │      │ └────────┘ │
        │ ┌────────┐ │      │ ┌────────┐ │      │ ┌────────┐ │
        │ │Skill A2│ │      │ │Skill B2│ │      │ │Skill C2│ │
        │ └────────┘ │      │ └────────┘ │      │ └────────┘ │
        │            │      │            │      │            │
        │ ┌────────┐ │      │ ┌────────┐ │      │ ┌────────┐ │
        │ │公共工具 │ │      │ │公共工具 │ │      │ │公共工具 │ │  ← 跨 Agent 共享
        │ └────────┘ │      │ └────────┘ │      │ └────────┘ │
        └────────────┘      └────────────┘      └────────────┘
```

**四层职责**：

| 层级 | 概念 | 职责 | 生命周期 |
|------|------|------|---------|
| L1 | **Supervisor** | 意图识别、跨 Agent 编排、结果聚合 | 请求级 |
| L2 | **Agent** | 领域自治、管理一组 Skill、维护领域状态 | 持久运行 |
| L3 | **Skill** | 可复用能力包（Prompt + Tools + Knowledge），动态装配 | 装配/卸载 |
| L4 | **Tool** | 原子函数，单一职责，无状态 | 调用即执行 |

**关键设计**：
- **每个 Agent 独立可运行**：有自己的 prompt、Skill 装配列表、状态机，可脱离 Supervisor 直接调用
- **Skill 可动态装配**：Agent 运行时可根据意图自动激活 Skill，也可在 Web UI 手动装配/卸载
- **Tool 归属 Skill**：Tool 不直接挂在 Agent 上，而是属于某个 Skill；Agent 通过装配 Skill 获得 Tool
- **公共工具也是 Skill**：`common` 分类的 Skill 自动装配到所有 Agent
- **多 Agent 协同**：Supervisor 识别出跨领域需求时，编排多个 Agent 协作完成

### 2.2 Agent 间协作模式

| 模式 | 场景举例 | 实现方式 |
|------|---------|---------|
| 单个 Agent | "帮我格式化这个 JSON" | Supervisor 直接路由到 Tools Agent |
| 串行协作 | "review 代码后生成日报" → Programming → Work | Supervisor 按序调度，上下文传递 |
| 并行协作 | "同时检查仓库A和仓库B的健康状态" | Supervisor 并行派发，结果汇聚 |
| 定时触发 | Scheduler 定时触发 Work Agent 生成日报 | Scheduler 调用其他 Agent |
| Agent 自主调用 | Work Agent 生成日报时自己调 Programming Agent 拿 git log | Agent 间的 Tool 调用 |

---

## 三、工具体系

### 3.1 公共工具（所有 Agent 可用）

| 工具 | 功能 | 实现 |
|------|------|------|
| **知识库检索** | 向量相似度搜索、关键词搜索、混合检索 | 向量数据库 SDK |
| **知识库写入** | 文档入库、分片、索引 | 向量数据库 SDK |
| **文件读写** | 读取/写入本地文件系统 | Python 标准库 |
| **Shell 执行** | 执行系统命令（沙箱约束） | subprocess |
| **网络请求** | HTTP GET/POST，调用外部 API | httpx / requests |
| **LLM 调用** | 让 LLM 做总结/翻译/分类等通用 NLP | LangChain ChatModel |
| **通知推送** | 发送飞书消息、系统通知 | 飞书 SDK |

### 3.2 各 Agent 专属工具

#### Programming Agent 专属工具

| 工具 | 功能 |
|------|------|
| git_status | 查看仓库状态、分支列表 |
| git_log | 查看提交历史（支持时间范围、作者过滤） |
| git_diff | 查看暂存区/工作区/commit 间差异 |
| git_branch | 创建/切换/合并/删除分支 |
| git_commit | 暂存文件并提交（含 conventional commit 生成） |
| git_push | 推送到远程 |
| git_stash | 暂存/恢复工作区 |
| git_tag | 创建/列出标签 |
| code_review | 对 diff 做分级审查（bug/安全/性能/风格） |
| generate_commit_msg | 读 diff 生成 conventional commit message |
| conflict_analyze | 分析合并冲突，给出两边改动和解决建议 |
| dependency_audit | npm/pip 依赖安全检查 |
| repo_health | 僵尸分支/大文件/.gitignore 检查、仓库统计 |
| project_scaffold | 从模板生成项目骨架 |

#### Personal Tools Agent 专属工具

| 工具 | 功能 |
|------|------|
| excel_read | 读取 xlsx/xls/csv，返回 DataFrame/摘要 |
| excel_write | 写入/更新 Excel 文件 |
| excel_pivot | 生成数据透视表 |
| excel_chart | 生成图表（柱状/折线/饼图） |
| pdf_extract_text | 从 PDF 提取文本 |
| pdf_extract_table | 从 PDF 提取表格为 DataFrame |
| pdf_merge | 合并多个 PDF |
| pdf_split | 拆分 PDF（按页数/书签） |
| pdf_ocr | 对扫描件 PDF 做 OCR 识别 |
| json_format | 格式化/压缩 JSON |
| json_query | 用 JMESPath/jq 语法查询 JSON |
| json_validate | 校验 JSON Schema |
| json_diff | 两个 JSON 结构/值差异对比 |
| text_diff | 文本差异对比（行级/词级） |
| text_similarity | 文本相似度计算 |
| format_convert | 格式互转（xlsx↔csv↔json↔markdown↔pdf） |
| markdown_to_pdf | Markdown 渲染转 PDF |
| image_ocr | 图片 OCR 文字识别 |

#### Work Agent 专属工具

| 工具 | 功能 |
|------|------|
| daily_report_gen | 生成日报：聚合当日 git commits + 手动输入 → 填入模板 |
| weekly_report_gen | 生成周报：聚合 5 天日报 + 本周统计 |
| monthly_report_gen | 生成月报：聚合周报 + 月度统计 |
| feishu_create_doc | 在飞书创建/更新文档 |
| feishu_send_message | 发送飞书消息（个人/群聊） |
| feishu_read_doc | 读取飞书文档内容 |
| feishu_list_docs | 列出飞书文档列表 |
| meeting_minutes_gen | 从会议录音/文字稿提取要点 → 生成纪要 + 待办 |
| task_tracker | 管理工作任务：创建/更新/完成/列表 |
| work_summary | 根据时间范围汇总工作产出（git + 飞书 + 手动） |
| calendar_query | 查询飞书/Outlook 日历事件 |

#### Scheduler Agent 专属工具

| 工具 | 功能 |
|------|------|
| cron_add | 添加定时任务（cron 表达式 + 触发目标） |
| cron_remove | 移除定时任务 |
| cron_list | 列出所有定时任务及状态 |
| cron_pause | 暂停/恢复定时任务 |
| cron_update | 更新定时任务配置 |
| reminder_once | 设置一次性提醒（相对时间/绝对时间） |
| reminder_list | 列出待触发的一次性提醒 |
| health_check_add | 添加周期性健康检查（URL/服务/脚本） |
| health_check_list | 列出健康检查及最近状态 |
| schedule_audit | 任务执行日志审计 |

### 3.3 MCP 接入体系

MCP（Model Context Protocol）用于接入外部系统能力，定位上属于 **Tool 的外部适配层**。系统内部不直接把 MCP 暴露给用户使用，而是通过 Skill 或 Tool Registry 包装后提供给 Agent。

| MCP 类型 | 典型能力 | 建议归属 |
|----------|----------|----------|
| GitHub / GitLab MCP | issue、PR、commit、CI 状态、release | Programming Agent / `git-manager`、`release-manager` Skill |
| 飞书 MCP | 消息、文档、表格、日历、审批 | Work Agent / `feishu-publisher`、`calendar-sync` Skill |
| Browser MCP | 页面打开、点击、表单填写、截图、网页解析 | Personal Tools Agent 或独立 Browser Automation Agent |
| Database MCP | 查询数据库、执行只读 SQL、数据摘要 | Work Agent / Data Skill |
| File System MCP | 文件浏览、读取、写入、移动、搜索 | common / `file-ops` Skill |
| Email MCP | 邮件读取、搜索、草稿、发送 | Work Agent / `mail-assistant` Skill |
| Notion / Docs MCP | 文档读取、创建、更新、知识同步 | Work Agent / Knowledge Agent |

**MCP 接入原则**：
- MCP 是外部能力连接器，不直接等同于业务能力。
- MCP Server 需要统一注册、启用、禁用、配置认证信息和默认工作目录。
- Agent 使用 MCP 前，应通过 Skill 包装出明确的业务语义，例如"发布飞书日报"而不是裸调用"发送消息 API"。
- 高风险 MCP 操作（发送消息、删除文件、执行写入 SQL、发布文档）必须支持预览确认和权限控制。
- MCP 调用也必须进入统一调用日志和统计体系。

### 3.4 Tool / MCP / Skill 统一管理

系统需要提供统一的 **能力注册与管理中心**，集中管理 Agent、Skill、Tool、MCP 和 Workflow 的注册、配置、启停、权限、统计。

```
Capability Registry
  ├── Agent Registry       # 子 Agent 注册、状态、路由描述
  ├── Skill Registry       # Skill 元信息、装配关系、触发规则
  ├── Tool Registry        # 本地 Tool 函数注册、参数 schema、权限
  ├── MCP Registry         # MCP Server 配置、认证、连接状态
  └── Workflow Registry    # 可复用工作流链、触发方式、执行历史
```

#### 统一管理对象

| 对象 | 管理内容 | 操作 |
|------|----------|------|
| Agent | 名称、描述、领域、状态、默认模型、默认工作目录、可用 Skill | 新增、编辑、启用、禁用、删除、测试 |
| Skill | 元信息、触发词、Prompt、引用资料、依赖/冲突、可用 Tool/MCP | 新增、编辑、装配、卸载、启用、禁用、删除、版本切换 |
| Tool | 名称、参数 schema、返回 schema、所属 Skill、权限等级、超时时间 | 注册、编辑、启用、禁用、删除、测试调用 |
| MCP Server | 启动命令、连接方式、认证配置、暴露工具、工作目录、健康状态 | 新增、编辑、连接测试、启用、禁用、删除、刷新工具列表 |
| Workflow | 步骤 DAG、涉及 Agent/Skill、输入输出映射、失败策略 | 新增、编辑、启用、禁用、手动执行、定时触发、删除 |

#### 工作目录与运行上下文

每个 Agent / Skill / Tool / MCP / Workflow 都应支持配置运行上下文：

| 配置项 | 说明 |
|--------|------|
| `workspace_dir` | 默认工作目录，例如某个代码仓库、文档目录、临时处理目录 |
| `allowed_paths` | 允许读写的目录白名单 |
| `readonly_paths` | 只读目录白名单 |
| `env_vars` | 运行所需环境变量，敏感值只保存引用，不明文展示 |
| `timeout_seconds` | 单次调用超时时间 |
| `max_output_tokens` | 工具输出注入上下文的最大 token 数 |
| `permission_level` | 权限等级：read / write / execute / external_publish / dangerous |
| `confirm_required` | 是否需要用户确认后才能执行 |

#### 删除与禁用策略

- **禁用**：保留配置和历史统计，但不再参与匹配和执行。
- **删除**：移除配置，但历史调用日志保留，避免统计断层。
- **强依赖保护**：被 Workflow 或 Skill 依赖的 Tool/MCP 删除前必须提示影响范围。
- **版本回滚**：Skill、Workflow 配置变更需要保留历史版本，支持回滚。
- **热加载**：新增/修改 Skill、Tool、MCP 后，优先支持热加载；无法热加载时提示需要重启服务。

### 3.5 调用统计与可观测性

所有 Agent、Skill、Tool、MCP、Workflow 都要记录详细调用统计，既用于排查问题，也用于评估哪些能力值得优化。

#### 核心指标

| 指标 | 说明 |
|------|------|
| `call_count` | 调用总次数 |
| `success_count` / `failed_count` | 成功/失败次数 |
| `success_rate` | 成功率 |
| `avg_latency_ms` / `p95_latency_ms` | 平均耗时 / P95 耗时 |
| `avg_input_tokens` / `avg_output_tokens` | 平均输入/输出 token |
| `llm_cost_estimate` | LLM 调用成本估算 |
| `last_called_at` | 最近调用时间 |
| `last_error` | 最近失败原因摘要 |
| `user_confirm_count` | 需要确认的操作次数 |
| `cancel_count` | 用户取消次数 |

#### 统计维度

| 维度 | 示例 |
|------|------|
| 时间 | 最近 1 小时 / 今天 / 7 天 / 30 天 |
| 调用对象 | Agent / Skill / Tool / MCP / Workflow |
| 用户入口 | Web UI / 飞书 Bot / CLI / Scheduler |
| 结果 | 成功 / 失败 / 超时 / 用户取消 / 权限拒绝 |
| Agent | Programming / Work / Personal Tools / Scheduler |
| 工作目录 | 不同仓库、不同文档目录、不同项目空间 |

#### 调用日志字段

```yaml
call_log:
  id: call_xxx
  trace_id: trace_xxx
  session_id: sess_xxx
  entrypoint: web_ui | feishu_bot | cli | scheduler
  agent: programming
  skill: code-reviewer
  tool: git_diff
  mcp_server: null
  workflow: null
  workspace_dir: E:/projects/demo
  started_at: 2026-07-07T13:00:00+08:00
  finished_at: 2026-07-07T13:00:03+08:00
  latency_ms: 3000
  status: success | failed | timeout | cancelled | permission_denied
  input_summary: "review staged changes"
  output_summary: "found 2 warnings"
  error_type: null
  error_message: null
  input_tokens: 1200
  output_tokens: 800
  cost_estimate: 0.002
```

**日志存储原则**：
- 结构化统计数据写入关系数据库（生产 PostgreSQL，本地开发可用 SQLite），便于 Web UI 查询。
- 大体积工具输出不直接全量入库，只保存摘要和引用路径。
- 敏感参数（API Key、Token、密码）必须脱敏。
- 每次复杂请求应有统一 `trace_id`，串起 Supervisor、多个 Agent、Skill、Tool/MCP 的完整链路。

---

## 四、Skill 系统

### 4.1 概念定位：Agent / Skill / Tool 三层关系

```
┌─────────────────────────────────────────────────┐
│                    Agent                         │
│   (领域边界，独立运行，有自己的状态和生命周期)      │
│                                                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│   │ Skill A  │ │ Skill B  │ │ Skill C  │  ...   │
│   │ ┌──────┐ │ │ ┌──────┐ │ │ ┌──────┐ │        │
│   │ │Prompt│ │ │ │Prompt│ │ │ │Prompt│ │        │
│   │ ├──────┤ │ │ ├──────┤ │ │ ├──────┤ │        │
│   │ │Tool 1│ │ │ │Tool 3│ │ │ │Tool 5│ │        │
│   │ │Tool 2│ │ │ │Tool 4│ │ │ │Tool 6│ │        │
│   │ ├──────┤ │ │ ├──────┤ │ │ ├──────┤ │        │
│   │ │Ref   │ │ │ │Ref   │ │ │ │Ref   │ │        │
│   │ └──────┘ │ │ └──────┘ │ │ └──────┘ │        │
│   └──────────┘ └──────────┘ └──────────┘        │
│                                                  │
│   ┌──────────────────────────────────────┐       │
│   │           公共工具（所有 Skill 可用）  │       │
│   └──────────────────────────────────────┘       │
└─────────────────────────────────────────────────┘
```

| 概念 | 定位 | 类比 | 特点 |
|------|------|------|------|
| **Agent** | 领域自治实体 | 一个"部门" | 独立运行、有状态、管理一组 Skill |
| **Skill** | 可复用能力包 | 一个"技能证书" | Prompt+Tool+Knowledge 的打包，可动态装配/卸载 |
| **Tool** | 原子函数 | 一个"螺丝刀" | 单一职责、无状态、输入→输出 |

**核心区别**：
- **Tool 是死的**：一个函数，被调用就执行，不调用就不存在
- **Skill 是活的**：包含 Tool + 专属 Prompt + 参考知识，装配后会影响 Agent 的行为和思考方式
- **Agent 是自主的**：决定什么时候激活哪个 Skill，Skill 之间如何协作

### 4.2 Skill 的定义结构

```python
class Skill:
    name: str                    # 唯一标识，如 "code-review"
    display_name: str            # 显示名，如 "代码审查"
    description: str             # 一句话描述能力
    version: str                 # 版本号
    enabled: bool                 # 是否启用
    
    # —— 核心 ——
    system_prompt: str           # 装配后注入到 Agent 的 system prompt
    tools: List[Tool]            # 该 Skill 专属工具
    mcp_servers: List[str]        # 该 Skill 可调用的 MCP Server（可选）
    references: List[str]        # 参考知识文件路径（Markdown/代码片段/模板）
    
    # —— 触发 ——
    triggers: List[str]          # 激活关键词/意图描述，如 "review|审查|代码检查"
    auto_activate: bool          # 是否由 Agent 自动判断激活
    
    # —— 元信息 ——
    category: str                # 分类：programming / tools / work / common
    requires: List[str]          # 依赖的其他 Skill（可选）
    conflicts: List[str]         # 互斥的 Skill（同时只能激活一个）

    # —— 运行约束 ——
    workspace_dir: str            # 默认工作目录，可继承 Agent 配置
    allowed_paths: List[str]      # 可访问路径白名单
    permission_level: str         # read/write/execute/external_publish/dangerous
    confirm_required: bool        # 高风险操作是否需要确认
    timeout_seconds: int          # 单次执行超时
```

**Skill 配置要求**：
- Skill 必须可以在 Web UI 中新增、编辑、启用、禁用、删除、装配、卸载。
- Skill 可以直接绑定本地 Tool，也可以绑定 MCP Server 暴露出来的外部 Tool。
- Skill 的 `workspace_dir` 默认继承所属 Agent；用户也可以为某个 Skill 单独覆盖。
- Skill 的权限不能超过所属 Agent 的权限上限。
- Skill 被禁用后，不参与自动匹配，但历史调用记录和统计数据保留。
- Skill 被删除前，需要检查是否被 Agent 默认装配、Workflow 引用或其他 Skill 依赖。

### 4.3 Skill 装配机制

```
┌─────────────────────────────────────────────────────┐
│                  Skill Registry                      │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐  │
│  │git-mgr  │ │code-rev  │ │excel   │ │daily-rpt │  │
│  └─────────┘ └──────────┘ └────────┘ └──────────┘  │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌──────────┐  │
│  │pdf-proc │ │translate │ │json-df │ │feishu    │  │
│  └─────────┘ └──────────┘ └────────┘ └──────────┘  │
│                         ...                         │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Agent A  │ │ Agent B  │ │ Agent C  │
    │          │ │          │ │          │
    │ 装配:    │ │ 装配:    │ │ 装配:    │
    │ git-mgr  │ │ excel    │ │ daily-rpt│
    │ code-rev │ │ pdf-proc │ │ feishu   │
    │          │ │ json-diff│ │ translate│
    └──────────┘ └──────────┘ └──────────┘
```

**装配方式**：

| 方式 | 说明 | 场景 |
|------|------|------|
| **静态装配** | 配置文件中写明 Agent 装哪些 Skill，启动时加载 | 领域 Agent 的默认能力 |
| **动态装配** | Agent 运行时根据意图识别自动激活 Skill | 用户说"审查代码"→ 临时激活 code-review Skill |
| **手动装配** | 用户在 Web UI 中给 Agent 添加/移除 Skill | 扩展现有 Agent 能力 |
| **全局 Skill** | 注册为 `common` 分类，所有 Agent 自动拥有 | 翻译、知识库检索等通用能力 |

### 4.4 Skill 与 Agent 的运行时协作

```
用户："帮我 review 一下代码，然后把结果用飞书发给团队"

  Supervisor 意图识别：
    → 涉及 Programming Agent + Work Agent
    → 串行：先 review，再发送

  ┌─ Programming Agent ─────────────────────────┐
  │ 已装配 Skill: [git-mgr, code-review, ...]    │
  │                                              │
  │ 意图识别 → 激活 code-review Skill             │
  │   → code-review 的 system_prompt 注入        │
  │   → code-review 的 tools 可用                │
  │   → code-review 的 references 作为上下文     │
  │                                              │
  │ 执行 → 输出 review 报告                       │
  └──────────────────────────────────────────────┘
    │
    │ (报告传给 Work Agent)
    ▼
  ┌─ Work Agent ────────────────────────────────┐
  │ 已装配 Skill: [daily-rpt, feishu-pub, ...]   │
  │                                              │
  │ 意图识别 → 激活 feishu-publish Skill          │
  │   → 读取飞书 API 配置                         │
  │   → 调用 feishu_send_message tool           │
  │                                              │
  │ 执行 → 发送成功，返回链接                      │
  └──────────────────────────────────────────────┘
```

### 4.5 Skill 清单（按领域划分）

#### common（全局 Skill，所有 Agent 自动装配）

| Skill | 功能 | 包含的 Tool |
|-------|------|------------|
| **kb-search** | 知识库检索 | kb_vector_search, kb_keyword_search, kb_hybrid_search |
| **kb-write** | 知识库写入 | kb_insert_doc, kb_delete_doc, kb_update_doc |
| **file-ops** | 文件操作 | file_read, file_write, file_list, file_delete |
| **translate** | 多语言翻译 | translate_text, translate_doc, detect_language |
| **web-fetch** | 网页抓取 | web_fetch, web_search |
| **summarize** | 通用摘要 | summarize_text, summarize_long_doc, extract_keywords |

#### programming（编程领域 Skill）

| Skill | 功能 | 包含的 Tool |
|-------|------|------------|
| **git-manager** | Git 仓库管理 | git_status, git_log, git_diff, git_branch, git_commit, git_push, git_stash, git_tag |
| **code-reviewer** | 代码审查 | code_review, generate_review_report, check_security, check_performance |
| **commit-helper** | Commit 信息生成 | generate_commit_msg, analyze_diff_scope, suggest_commit_split |
| **conflict-resolver** | 冲突解决 | conflict_analyze, conflict_resolve, merge_abort |
| **repo-doctor** | 仓库健康检查 | repo_health, branch_cleanup, large_file_scan, gitignore_check |
| **dep-guardian** | 依赖管理 | dependency_audit, dependency_update, license_check |
| **project-scaffold** | 项目脚手架 | scaffold_project, list_templates, init_gitignore |

#### personal-tools（文件处理 Skill）

| Skill | 功能 | 包含的 Tool |
|-------|------|------------|
| **excel-master** | Excel 处理 | excel_read, excel_write, excel_pivot, excel_chart, excel_merge |
| **pdf-master** | PDF 处理 | pdf_extract_text, pdf_extract_table, pdf_merge, pdf_split, pdf_ocr |
| **json-master** | JSON 处理 | json_format, json_query, json_validate, json_diff, json_to_excel |
| **text-differ** | 文本比对 | text_diff, text_similarity, text_patch, text_merge |
| **format-shifter** | 格式互转 | xlsx_to_csv, csv_to_json, json_to_md, md_to_pdf, pdf_to_md |
| **image-ocr** | 图片识别 | image_ocr, image_extract_text, batch_ocr |

#### work（工作领域 Skill）

| Skill | 功能 | 包含的 Tool |
|-------|------|------------|
| **daily-reporter** | 日报生成 | daily_report_gen, collect_git_commits, collect_tasks |
| **weekly-reporter** | 周报生成 | weekly_report_gen, aggregate_daily_reports, weekly_stats |
| **monthly-reporter** | 月报生成 | monthly_report_gen, aggregate_weekly_reports, monthly_stats |
| **feishu-publisher** | 飞书发布 | feishu_create_doc, feishu_send_msg, feishu_read_doc, feishu_update_doc |
| **meeting-recorder** | 会议纪要 | meeting_transcribe, meeting_extract_todos, meeting_summary |
| **task-tracker** | 任务追踪 | task_create, task_update, task_list, task_statistics |
| **calendar-sync** | 日历同步 | calendar_query, calendar_create_event, calendar_conflicts |

#### scheduled（定时任务 Skill）

| Skill | 功能 | 包含的 Tool |
|-------|------|------------|
| **cron-master** | 定时任务管理 | cron_add, cron_remove, cron_list, cron_pause, cron_update |
| **reminder** | 提醒管理 | reminder_once, reminder_list, reminder_cancel |
| **health-watcher** | 健康巡检 | health_check_add, health_check_run, health_check_report |
| **schedule-auditor** | 执行审计 | schedule_log, schedule_stats, schedule_alert |

### 4.6 Skill 定义文件格式

每个 Skill 一个目录，`~/.work-assistant/skills/<skill-name>/`：

```
skills/
├── code-reviewer/
│   ├── skill.yaml          ← 元信息 + 配置
│   ├── prompt.md           ← system prompt 模板（Jinja2）
│   ├── tools.py            ← 专属 Tool 实现
│   └── references/
│       ├── review-checklist.md
│       └── security-patterns.md
│
├── excel-master/
│   ├── skill.yaml
│   ├── prompt.md
│   ├── tools.py
│   └── references/
│       ├── excel-recipes.md
│       └── chart-templates.py
│
└── daily-reporter/
    ├── skill.yaml
    ├── prompt.md
    ├── tools.py
    └── references/
        └── report-template.md
```

**skill.yaml 示例**：

```yaml
name: code-reviewer
display_name: 代码审查
version: 0.1.0
enabled: true
description: >
  对代码变更进行多维度审查：正确性、安全性、性能、可维护性、风格。
  输出分级报告（Critical / Warning / Suggestion）。
category: programming

triggers:
  - "review"
  - "审查"
  - "代码检查"
  - "code review"
  - "检查代码"
  - "看看这段代码"
  - "有没有问题"
auto_activate: true

requires: []
conflicts: []

tools:
  - code_review
  - generate_review_report
  - check_security
  - check_performance

mcp_servers: []

references:
  - review-checklist.md
  - security-patterns.md

runtime:
  workspace_dir: "${AGENT_WORKSPACE_DIR}"
  allowed_paths:
    - "${AGENT_WORKSPACE_DIR}"
  permission_level: read
  confirm_required: false
  timeout_seconds: 120
  max_output_tokens: 12000

observability:
  log_calls: true
  collect_metrics: true
  trace_enabled: true
```

### 4.7 Skill 的扩展方式

```
新增一个 Skill 的步骤：

1. mkdir skills/<skill-name>/
2. 写 skill.yaml（元信息）
3. 写 prompt.md（system prompt）
4. 写 tools.py（Tool 实现）
5. 可选加入 references/
6. 如需外部系统能力，在 skill.yaml 中声明 mcp_servers
7. 在 Web UI 或配置文件中把该 Skill 装配到目标 Agent
8. Registry 热加载 → Web UI 中可见、可管理；无法热加载时提示重启服务
```

无需修改 Agent 代码、无需改路由逻辑、无需动其他 Skill。

### 4.8 Skill / MCP / Tool 的扩展边界

| 扩展目标 | 推荐方式 | 判断标准 |
|----------|----------|----------|
| 增加一个领域内能力 | 新增 Skill | 需要专属 Prompt、触发词、参考资料、工具组合 |
| 增加一个原子动作 | 新增 Tool | 只是一个函数能力，如读取文件、调用 API、格式转换 |
| 接入外部系统 | 新增 MCP Server，再由 Skill 包装 | 能力来自外部服务或本地外部进程 |
| 固定多步骤任务 | 新增 Workflow | 多个 Agent/Skill 串联或并行，有明确输入输出 |
| 新领域自治 | 新增 Agent | 有独立领域边界、独立状态、独立权限和多组 Skill |

**设计原则**：
- Agent 数量保持少而稳定，避免为了每个小能力都新增 Agent。
- Skill 是主要扩展单位，负责把 Tool/MCP 组织成业务能力。
- Tool/MCP 不直接承担复杂业务流程，只提供可调用动作。
- Workflow 用于沉淀可重复执行的跨 Agent / 跨 Skill 流程。

---

## 五、请求处理流程

### 5.1 核心原则

- **Skill 是可选的**：一个 Agent 装配 0 个 Skill 也能正常工作（靠 LLM + 公共工具）
- **Skill 是动态发现的**：请求进来后扫描 Skill Registry，检查触发条件，不是固定依赖链
- **流程由意图驱动**：简单提问走短路径，复杂提问走完整编排，不预设死板流程

### 5.2 Skill 匹配机制

```
请求到达 Agent
    │
    ▼
┌─────────────────────────────────────────┐
│         Skill Registry 扫描              │
│                                         │
│  遍历该 Agent 装配的所有 Skill：          │
│                                         │
│  for skill in agent.equipped_skills:    │
│      score = match(request, skill)      │
│      if score > threshold:              │
│          candidates.append((skill,score))│
│                                         │
│  返回按相关性排序的候选 Skill 列表         │
│  → 也可能返回空列表（没有任何匹配）        │
└─────────────────────────────────────────┘
    │
    ├── 匹配到 Skill(es) ──▶ 激活（注入 prompt + 加载 tools）
    │
    └── 无匹配 ──▶ Agent 用基础 prompt + 公共工具直接处理
```

**匹配方式**（可组合）：

| 方式 | 说明 | 示例 |
|------|------|------|
| **关键词匹配** | skill.yaml 中 `triggers` 字段与用户输入做关键词命中 | "review 代码" → 命中 `code-reviewer` |
| **语义匹配** | 将用户输入 embedding 与 Skill 描述做余弦相似度 | "帮我看看这段有没有性能问题" → 语义上接近 code-reviewer |
| **LLM 分类** | 让轻量 LLM 判断用户意图属于哪个 Skill 的能力范围 | 复杂表述的意图分类 |

### 5.3 简单提问流程

**特征**：单一领域、无需跨 Agent 协作、Skill 匹配 0~2 个

```
用户输入: "帮我 review 暂存区的改动"
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                   Supervisor Node                     │
│                                                      │
│  ① 意图识别：                                        │
│     - 领域？ → Programming（代码审查）                 │
│     - 复杂度？ → 简单（单一领域，单一任务）            │
│     - 是否需要跨 Agent？ → 否                         │
│                                                      │
│  ② 路由决策：直接派发到 Programming Agent            │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│               Programming Agent Node                  │
│                                                      │
│  ③ 扫描 Skill Registry：                             │
│     ├── code-reviewer: triggers=["review","审查",...] │
│     │   → 关键词命中 "review" ← ✅ 匹配，score=0.95   │
│     ├── commit-helper: triggers=["commit","提交",...] │
│     │   → 未命中                                      │
│     ├── git-manager: triggers=["git","branch",...]    │
│     │   → 模糊命中，score=0.3 ← 低于阈值，跳过        │
│     └── ...其他 Skill 均未命中                        │
│                                                      │
│  ④ 激活 code-reviewer Skill：                        │
│     → 注入 code-reviewer 的 system_prompt            │
│     → 加载 tools: [code_review, check_security, ...] │
│                                                      │
│  ⑤ 执行（LLM 推理 + Tool 调用）：                    │
│     → 调用 git_diff 获取变更                          │
│     → LLM 分析代码                                    │
│     → 生成分级审查报告                                │
│                                                      │
│  ⑥ 返回结果                                          │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
                    返回给用户
```

**如果 0 个 Skill 匹配**（例如用户问 "Python 的 GIL 是什么"）：

```
Agent 收到请求 → 扫描 Skill Registry → 无匹配
    │
    ▼
用 Agent 基础 prompt + 公共工具直接处理：
  → LLM 用自己的知识回答
  → 可选调用 web_search 获取最新信息
  → 返回答案
```

### 5.4 复杂提问流程

**特征**：跨领域、多步骤、需要多 Agent 串行或并行协作

```
用户输入: "review 今天的代码改动，汇总成日报草稿，然后发给飞书团队群"
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                   Supervisor Node                     │
│                                                      │
│  ① 意图识别 + 任务拆解：                              │
│                                                      │
│     拆解出 3 个子任务：                               │
│     ┌─────────────────────────────────────┐          │
│     │ Task 1: review 代码改动              │          │
│     │   → 领域: Programming               │          │
│     │   → 依赖: 无                         │          │
│     ├─────────────────────────────────────┤          │
│     │ Task 2: 汇总日报草稿                  │          │
│     │   → 领域: Work                       │          │
│     │   → 依赖: Task 1 的输出              │          │
│     │   → 还需要: 今天的 git commits       │          │
│     ├─────────────────────────────────────┤          │
│     │ Task 3: 发送到飞书团队群              │          │
│     │   → 领域: Work                       │          │
│     │   → 依赖: Task 2 的输出              │          │
│     └─────────────────────────────────────┘          │
│                                                      │
│  ② 编排决策：                                        │
│     Task 1 ──(输出)──▶ Task 2 ──(输出)──▶ Task 3     │
│     串行依赖链，不能并行                               │
└──────────────────────┬───────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     (按依赖顺序串行执行)

                       │
                       ▼
┌─ Step 1: Programming Agent ──────────────────────────┐
│                                                      │
│  扫描 Skill Registry → 命中 code-reviewer             │
│  激活 Skill → 注入 prompt + 加载 tools                │
│  执行 → 输出: { review_report: "...", files: [...] } │
└──────────────────────┬───────────────────────────────┘
                       │ review_report 传入 Step 2
                       ▼
┌─ Step 2: Work Agent ─────────────────────────────────┐
│                                                      │
│  扫描 Skill Registry → 命中 daily-reporter            │
│  激活 Skill → 注入 prompt + 加载 tools                │
│  执行：                                              │
│    → 内部调用 git_log 获取今日 commits                │
│    → 融合 review_report + commits → 日报草稿          │
│  输出: { draft: "...", date: "2026-07-07" }          │
└──────────────────────┬───────────────────────────────┘
                       │ draft 传入 Step 3
                       ▼
┌─ Step 3: Work Agent ─────────────────────────────────┐
│                                                      │
│  扫描 Skill Registry → 命中 feishu-publisher          │
│  激活 Skill → 加载 feishu_send_msg tool              │
│  执行 → 发送成功，返回消息链接                         │
│  输出: { msg_id: "...", url: "..." }                 │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│               Supervisor 聚合结果                     │
│                                                      │
│  ① 审查报告 ✓                                        │
│  ② 日报草稿 ✓                                        │
│  ③ 飞书已发送 ✓                                      │
│                                                      │
│  汇总呈现给用户                                       │
└──────────────────────────────────────────────────────┘
```

### 5.5 复杂提问 — 含并行分支

```
用户输入: "检查仓库 A 和仓库 B 的健康状态，同时把我这周的 git log 汇总一下"
    │
    ▼
 Supervisor 拆解：
   Task 1: 检查仓库 A → Programming Agent (无依赖)
   Task 2: 检查仓库 B → Programming Agent (无依赖)
   Task 3: 汇总本周 git log → Programming Agent (无依赖)
   
   编排决策：三个任务完全独立 → 并行执行
    │
    ├─► Programming Agent (仓库A) ──┐
    ├─► Programming Agent (仓库B) ──┤  并行
    └─► Programming Agent (周报)  ──┘
    │
    ▼
 Supervisor 聚合三个结果 → 呈现给用户
```

### 5.6 Skill 扫描在不同流程中的位置

```
                    用户输入
                       │
                       ▼
              ┌─────────────────┐
              │   Supervisor     │  ← 第一层意图识别（领域）
              │   (不扫描Skill)  │
              └────────┬────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ Agent A  │ │ Agent B  │ │ Agent C  │  ← 第二层意图识别（Skill）
    │          │ │          │ │          │
    │  ┌────┐  │ │  ┌────┐  │ │  ┌────┐  │
    │  │扫描│  │ │  │扫描│  │ │  │扫描│  │  ← Skill Registry 动态匹配
    │  │Skill│  │ │  │Skill│  │ │  │Skill│  │
    │  └────┘  │ │  └────┘  │ │  └────┘  │
    │    │     │ │    │     │ │    │     │
    │    ▼     │ │    ▼     │ │    ▼     │
    │ 激活/不  │ │ 激活/不  │ │ 激活/不  │
    │ 激活后   │ │ 激活后   │ │ 激活后   │
    │ 执行     │ │ 执行     │ │ 执行     │
    └──────────┘ └──────────┘ └──────────┘
```

**关键点**：
- Supervisor 不做 Skill 扫描，只做领域级意图识别和编排
- Skill 扫描发生在每个 Agent 内部，是第二层意图识别
- 扫描结果可以是 0（直接用基础能力处理）、1（激活单个 Skill）、N（激活多个 Skill）
- Agent 间通过 Supervisor 传递上下文，不直接感知对方的 Skill

### 5.7 Workflow 工作流链

Workflow 用于沉淀可重复执行的多步骤任务，可以由用户手动触发、Scheduler 定时触发，也可以由 Supervisor 在识别到固定模式时自动匹配执行。

#### Workflow 定位

| 对象 | 负责什么 |
|------|----------|
| Supervisor | 临时拆解、动态编排、结果聚合 |
| Workflow | 固定流程模板，可复用、可配置、可统计 |
| Agent | 执行某个领域子任务 |
| Skill | 提供某个业务能力 |
| Tool / MCP | 执行具体动作 |

#### Workflow 示例

```yaml
name: daily-code-review-report
display_name: 今日代码审查日报
enabled: true
description: review 今日代码改动，生成日报草稿，确认后发送飞书群

trigger:
  manual: true
  scheduler: "0 18 * * 1-5"
  intent_examples:
    - "review 今天代码并生成日报"
    - "帮我发今日开发日报"

runtime:
  workspace_dir: E:/projects/current
  confirm_required: true
  timeout_seconds: 600

steps:
  - id: collect_git_changes
    agent: programming
    skill: git-manager
    tool: git_log
    inputs:
      since: today

  - id: code_review
    agent: programming
    skill: code-reviewer
    depends_on: [collect_git_changes]

  - id: generate_report
    agent: work
    skill: daily-reporter
    depends_on: [collect_git_changes, code_review]

  - id: send_feishu
    agent: work
    skill: feishu-publisher
    depends_on: [generate_report]
    confirm_required: true
```

#### Workflow 执行要求

- 支持串行、并行、条件分支、失败重试、失败跳过、人工确认节点。
- 每一步都要产生结构化输出，供后续步骤引用。
- Workflow 可以直接绑定 Tool/MCP，但推荐优先绑定 Agent + Skill，保留业务语义。
- 每次 Workflow 执行都必须生成 `trace_id`，串联所有步骤调用日志。
- Workflow 本身也要统计调用量、成功率、平均耗时、失败步骤分布、用户取消次数。
- Workflow 可在 Web UI 中新增、编辑、启用、禁用、删除、手动执行、复制和查看历史。

---

## 六、上下文管理与记忆系统

### 6.1 记忆分层架构

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   ┌──────────────────────────────────────────────┐      │
│   │          L1: 会话级短期记忆                     │      │
│   │  - 当前对话的完整消息历史                        │      │
│   │  - 生命周期：单次会话                           │      │
│   │  - 存储：内存（LangGraph State）                │      │
│   │  - 关键问题：上下文窗口有限，需要压缩策略        │      │
│   └────────────────────┬─────────────────────────┘      │
│                        │ 过期后压缩写入                  │
│                        ▼                                │
│   ┌──────────────────────────────────────────────┐      │
│   │          L2: 摘要级中期记忆                     │      │
│   │  - 历史会话的压缩摘要                           │      │
│   │  - 生命周期：跨会话（近期）                      │      │
│   │  - 存储：关系数据库 + 可选向量化                  │      │
│   │  - 内容：关键决策、用户偏好、未完成任务           │      │
│   └────────────────────┬─────────────────────────┘      │
│                        │ 提炼关键信息                    │
│                        ▼                                │
│   ┌──────────────────────────────────────────────┐      │
│   │          L3: 持久长期记忆                       │      │
│   │  - 用户画像：偏好、习惯、常用路径                 │      │
│   │  - 实体记忆：项目、仓库、人员、文档               │      │
│   │  - 经验记忆：历史决策原因、踩过的坑               │      │
│   │  - 生命周期：永久（除非主动删除）                 │      │
│   │  - 存储：Qdrant（语义检索）+ 关系数据库（结构化） │      │
│   └──────────────────────────────────────────────┘      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 6.2 短期记忆：会话上下文管理

#### 问题

LLM 有最大上下文限制（如 DeepSeek 64K tokens）。多轮对话中消息持续增长，超出限制后：
- 最旧的对话被截断，丢失关键上下文
- 多 Agent 协作时，每个 Agent 的消息也占 token
- Skill 的 system prompt 和工具描述也要消耗 token

#### 策略：分层压缩

```
消息数量 / Token 用量
    │
    │                    ┌──────────────────┐
    │                    │  超出限制，强制压缩 │
    │                    │  移除旧轮次        │
    │              ┌─────┤  仅保留摘要        │
    │              │     └──────────────────┘
    │              │
    │         ┌────┴────────────────────────┐
    │         │  警戒区 (80% of max)         │
    │         │  触发增量摘要压缩              │
    │         │  保留最近 N 轮完整消息         │
    │    ┌────┤  早期轮次 → LLM 生成摘要      │
    │    │    └─────────────────────────────┘
    │    │
    │    │    ┌─────────────────────────────┐
    │    │    │  安全区 (< 60%)              │
    │    │    │  正常存储完整消息              │
    │    └────┤  不做压缩                     │
    │         └─────────────────────────────┘
    │
    └──────────────────────────────────────────▶ 时间
```

**压缩策略表**：

| 策略 | 触发条件 | 操作 | 效果 |
|------|---------|------|------|
| **增量摘要** | Token 用量达到 60% | 将最早 30% 的消息交给 LLM 压缩为结构化摘要，摘要替换原始消息 | 回收 ~25% token，保留语义 |
| **滑动窗口** | Token 用量达到 80% | 仅保留最近 K 轮完整消息（K 可配置），之前全部替换为摘要 | 回收 ~40% token |
| **关键消息保护** | 任何压缩操作 | 被标记为"重要"的消息（决策、偏好、待办）不压缩，始终保留原文 | 关键信息零丢失 |
| **工具输出截断** | 单条 Tool 输出 > N tokens | 保留前 N + 后 M tokens，中间用 `...[truncated]...` 替换 | 避免单条输出撑爆上下文 |
| **紧急压缩** | Token 用量达到 95% | 激进压缩：保留最后 2 轮 + 摘要，丢弃其余 | 防止 API 报错，最后手段 |

#### 摘要格式

```json
{
  "session_id": "sess_xxx",
  "compressed_range": {"from_turn": 1, "to_turn": 15},
  "summary": "用户正在开发 Hexo 博客的暗色模式功能。已检查了 theme.js 和 main.css...",
  "key_decisions": [
    "确定使用 CSS 变量方案而非两套样式表",
    "暗色模式切换按钮放在导航栏右侧"
  ],
  "user_preferences_found": [
    "用户偏好 CSS 变量方案",
    "用户习惯先 review 再提交"
  ],
  "unfinished_tasks": [
    "待修改 footer 的暗色适配",
    "待写暗色模式的单元测试"
  ],
  "important_context": [
    "当前仓库: E:/anzhiyu-blog，分支: feature/dark-mode"
  ]
}
```

#### 多 Agent 场景的上下文隔离

```
Supervisor
  │
  ├─► Agent A 会话上下文（独立 64K 窗口）
  │     └── Agent A 的消息 + 工具调用 + 压缩后摘要
  │
  ├─► Agent B 会话上下文（独立 64K 窗口）
  │     └── Agent B 的消息 + 工具调用 + 压缩后摘要
  │
  └─► 仅传递必要信息：
        - Supervisor 给 Agent: 拆解后的子任务 + 关键上下文
        - Agent 回 Supervisor: 结构化结果（不传全部对话历史）
```

### 6.3 长期记忆：跨会话持久化

#### 记忆类型

| 类型 | 内容 | 更新方式 | 存储 |
|------|------|---------|------|
| **用户画像** | 身份、角色、技术水平、常用工具 | 会话结束时从摘要中提取 | 关系数据库 |
| **偏好记忆** | 编码风格、报告格式、通知偏好、确认阈值 | 用户显式设定 / 从行为推断 | 关系数据库 |
| **实体记忆** | 项目路径、仓库地址、飞书文档 ID、常用联系人 | 使用中自动记录 | Qdrant |
| **经验记忆** | 历史决策及原因、踩过的坑、解决方案 | 会话摘要提炼 | Qdrant |
| **任务记忆** | 待办事项、未完成的任务、deadline | 每次任务操作时更新 | 关系数据库 |
| **知识片段** | 用户教助手的规则（"以后遇到 X 就 Y"） | 用户显式教 / 从对话提取 | Qdrant |

#### 记忆生命周期

```
会话进行中：
  ┌──────────┐
  │ 当前会话  │ → 所有消息保持在 L1 短期记忆
  └────┬─────┘
       │ 会话结束
       ▼
  ┌──────────┐
  │ 压缩摘要  │ → LLM 生成结构化摘要
  └────┬─────┘
       │
       ├── 关键决策/偏好 ──▶ L3 长期记忆（关系数据库 + Qdrant）
       ├── 未完成任务   ──▶ L3 任务记忆
       └── 一般对话     ──▶ L2 中期记忆（保留最近 N 个会话摘要）

下一次会话开始时：
  ┌──────────┐
  │ 记忆召回  │
  └────┬─────┘
       │
       ├── 从关系数据库加载用户画像 + 偏好 → 注入 System Prompt
       ├── 从 Qdrant 语义检索相关记忆 → 注入上下文
       └── 从中期记忆加载最近 N 个会话摘要 → 注入上下文
```

#### 记忆检索流程

```
新请求进来
    │
    ▼
┌─────────────────────────────────────┐
│  ① 提取检索查询                       │
│  - 用户当前问题本身                    │
│  - 当前 Agent 的领域                  │
│  - 当前 session 已有的上下文           │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  ② 多路召回                          │
│                                     │
│  关系数据库精确查：                    │
│  → 用户偏好（始终加载）                 │
│  → 用户画像（始终加载）                 │
│  → 未完成任务                         │
│                                     │
│  Qdrant 语义查：                      │
│  → 向量相似度搜索，top_k=5             │
│  → 按领域 metadata 过滤               │
│  → 按时间衰减加权                      │
│                                     │
│  关键词匹配：                         │
│  → 实体名、文件名、项目名精确匹配        │
│  → BM25 文本检索                     │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  ③ 融合排序                          │
│                                     │
│  score = α·vector_score              │
│        + β·keyword_score             │
│        + γ·recency_score             │
│        + δ·importance_score          │
│                                     │
│  Rerank（Cross-Encoder）取 top_3     │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────┐
│  ④ 注入上下文                        │
│                                     │
│  将召回的长期记忆 + 中期摘要           │
│  注入到 Agent 的 System Prompt：      │
│                                     │
│  "## 你的长期记忆                     │
│   - 用户偏好: ...                    │
│   - 相关历史: ...                    │
│   - 上次未完成: ..."                  │
└─────────────────────────────────────┘
```

### 6.4 记忆更新机制

| 触发时机 | 更新动作 |
|---------|---------|
| **会话结束** | LLM 生成会话摘要 → 提取关键信息 → 写入 L2/L3 |
| **用户显式教** | "记住，以后 X 就 Y" → 直接写入 L3 偏好记忆 |
| **Agent 执行任务后** | 任务结果 + 用户反馈 → 提炼经验 → 写入 L3 |
| **定期整理** | 每周自动合并/去重 L3 记忆，清理过期信息 |
| **手动管理** | Web UI 中查看/编辑/删除记忆条目 |

### 6.5 记忆配置示例

```yaml
# memory_config.yaml
memory:
  short_term:
    max_tokens: 64000            # 上下文窗口上限
    summary_trigger: 0.6         # 60% 触发增量摘要
    window_trigger: 0.8          # 80% 触发滑动窗口
    emergency_trigger: 0.95      # 95% 紧急压缩
    protected_message_types:     # 不压缩的消息类型
      - user_preference
      - decision
      - task_assignment
    
  mid_term:
    max_sessions: 20             # 保留最近 20 个会话摘要
    summary_max_tokens: 2000     # 每个摘要上限
    
  long_term:
    vector_topk: 5               # 语义检索召回数
    rerank_topk: 3               # Rerank 后保留数
    recency_decay_days: 30       # 超过 30 天开始衰减
    auto_cleanup_interval: 7d    # 每 7 天整理一次记忆
```

---

## 七、知识库系统

### 7.1 向量数据库选型推荐

| 数据库 | 特点 | 适用场景 | 推荐度 |
|--------|------|---------|--------|
| **Qdrant** | Rust 实现，高性能；支持全文+向量混合检索；有 Web Dashboard；Docker 部署简单；过滤/分组/payload 索引 | 首选，功能最均衡 | ⭐⭐⭐⭐⭐ |
| **Milvus** | 分布式、千万级向量；功能最全但重 | 企业级大规模，个人使用过重 | ⭐⭐⭐ |
| **ChromaDB** | Python 原生，零配置；嵌入式/CS 双模式 | 原型开发、数据量 <10 万 | ⭐⭐⭐⭐ |
| **Weaviate** | GraphQL 接口；自带向量化模块 | 适合需要 GraphQL 和内置 embedding 的场景 | ⭐⭐⭐ |
| **LanceDB** | Serverless，列式存储；支持多模态 | 不需要单独服务，但生态较新 | ⭐⭐⭐ |
| **FAISS** | Meta 出品，纯向量检索快；不持久化、无语义过滤 | 只做向量检索的基础层，需要自己封装 | ⭐⭐ |

**推荐方案**：**Qdrant**（主力）+ **ChromaDB**（轻量备份）

理由：
- Qdrant 有 Docker 镜像，服务器一行命令部署，自带 Dashboard 方便管理
- 支持 `filter` + `vector` 混合检索，可以按文档类型/日期/标签筛选
- 支持多 Collection（每个领域一个 Collection）
- Python SDK 成熟，与 LangChain 集成良好
- ChromaDB 作为本地开发时的零配置替代

### 7.2 知识库功能设计

#### 文档类型支持

| 类型 | 格式 | 解析方式 |
|------|------|---------|
| 纯文本 | `.txt` `.md` `.log` | 直接读取 |
| 富文本文档 | `.docx` `.doc` | python-docx |
| PDF | `.pdf` | pdfplumber（文本）+ EasyOCR（扫描件） |
| 表格 | `.xlsx` `.csv` | pandas + openpyxl |
| 代码文件 | `.py` `.js` `.ts` `.java` `.go` ... | 按语言语法解析 |
| 网页 | URL | WebFetch → 提取正文 → Markdown 化 |
| JSON/YAML | `.json` `.yaml` `.yml` | 结构化展开 |
| 飞书文档 | 飞书 URL | 飞书 API 获取内容 |
| 图片 | `.png` `.jpg` | OCR 提取文字（EasyOCR） |
| 邮件 | `.eml` | email 库解析 |

#### 分片策略

| 策略 | 适用场景 | 说明 |
|------|---------|------|
| **固定大小分片** | 通用 | N 字符一块，overlap M 字符 |
| **递归分片** | 代码/结构化文档 | 按 `\n\n` → `\n` → `。` → ` ` 优先级递归切分 |
| **语义分片** | 长文/报告 | 用 embedding 判断语义边界，在语义转折点切分 |
| **文档结构分片** | Markdown/HTML | 按标题层级（h1→h2→h3）分片，保留结构 | Path上下文 |
| **按页分片** | PDF | 一页一片，保留页码元数据 |
| **代码感知分片** | 代码文件 | 按函数/类边界分片，保留 AST 结构 |
| **表格分片** | Excel/CSV | 按行/Sheet 分片，保留表头作为元数据 |

#### 知识库 Collection 设计

```
Collection: common          ← 公共知识（编码规范、API 文档、个人偏好）
Collection: programming     ← 编程相关（Git 规范、项目文档、技术笔记）
Collection: work            ← 工作相关（日报模板、会议纪要、项目上下文）
Collection: tools           ← 工具使用记录（处理脚本、数据模板）
Collection: scheduled       ← 定时任务配置和日志
```

每个 Collection 支持：
- **metadata 过滤**：文档类型、创建日期、标签、来源
- **混合检索**：向量 + BM25 关键词
- **Rerank**：召回后用 Cross-Encoder 重排序
- **增量更新**：文档变更后重新分片入库，旧分片标记删除

---

## 八、Web UI 前端需求

### 8.1 功能模块

```
┌──────────────────────────────────────────────────────┐
│  导航栏  [对话] [Agent管理] [能力管理] [知识库] [任务] [统计] [设置] │
├──────────────────────────────────────────────────────┤
│                                                      │
│   主内容区（根据导航切换）                              │
│                                                      │
└──────────────────────────────────────────────────────┘
```

#### 对话页面
- 聊天界面：Markdown 渲染、代码高亮、文件上传
- Agent 选择：手动指定用哪个 Agent，或自动（Supervisor 分发）
- 会话历史：左侧会话列表，可切换/搜索/删除历史会话
- 实时流式输出：Agent 执行过程的中间步骤可见
- 多轮上下文：保持对话上下文，支持澄清追问

#### Agent 管理页面
- Agent 列表：展示每个 Agent 名称、描述、状态（运行中/空闲/禁用）
- Agent 详情：查看已装配 Skill、可用 Tool/MCP、最近执行记录、配置参数
- Agent 启用/禁用开关
- Agent 默认工作目录、允许访问路径、默认模型、权限上限配置
- 给 Agent 装配/卸载 Skill
- 查看 Agent 维度统计：调用量、成功率、平均耗时、最近失败

#### 能力管理页面
- Skill 管理：
  - Skill 列表：名称、分类、版本、启用状态、装配到哪些 Agent
  - Skill 新增/编辑/删除/启用/禁用/复制/版本回滚
  - 编辑触发词、Prompt、引用资料、依赖、冲突、默认工作目录、权限等级
  - 查看 Skill 绑定的 Tool 和 MCP
- Tool 管理：
  - Tool 注册表：名称、所属 Skill、参数 schema、返回 schema、权限等级、超时配置
  - Tool 启用/禁用/删除/测试调用
  - 查看 Tool 调用量、成功率、耗时、最近错误
- MCP 管理：
  - MCP Server 列表：名称、连接方式、启动命令、状态、暴露工具数量
  - MCP 新增/编辑/删除/启用/禁用/连接测试/刷新工具列表
  - MCP 工作目录、环境变量、认证配置、权限等级配置
  - 查看 MCP 调用量、成功率、连接失败次数、最近错误
- Workflow 管理：
  - Workflow 列表：名称、启用状态、触发方式、最近执行结果
  - Workflow 新增/编辑/删除/复制/启用/禁用/手动执行
  - 可视化查看步骤 DAG、依赖关系、输入输出映射
  - 查看 Workflow 调用量、成功率、平均耗时、失败步骤分布

#### 知识库页面
- 文档上传：拖拽上传，自动识别类型 → 分片 → 入库
- 文档列表：按 Collection 筛选，支持搜索、删除、重新分片
- 分片策略配置：每种文档类型可调整分片参数
- 检索测试：输入 query，查看召回结果和得分
- 导入状态：批量导入进度条、失败文档列表

#### 任务页面
- 定时任务列表：CRUD 管理
- 任务执行历史：最近执行时间、结果、日志
- 一次性提醒列表
- 定时触发 Workflow：选择 Workflow、配置 cron、启停、查看最近执行结果

#### 统计页面
- 总览指标：今日调用量、成功率、失败数、平均耗时、P95 耗时、Token 用量、成本估算
- 按 Agent / Skill / Tool / MCP / Workflow 分组查看统计
- 按入口筛选：Web UI / 飞书 Bot / CLI / Scheduler
- 按时间筛选：最近 1 小时、今天、7 天、30 天、自定义范围
- 调用链路追踪：通过 `trace_id` 查看一次复杂请求经过的 Supervisor、Agent、Skill、Tool/MCP、Workflow 步骤
- 错误分析：失败原因分类、最近错误、超时分布、权限拒绝分布
- 工作目录维度统计：不同项目/仓库/文档目录的调用情况

#### 设置页面
- LLM 配置（API Key、Base URL、Model）
- 飞书配置（App ID、App Secret、Bot Token）
- 数据库连接配置
- 通知偏好
- 全局工作目录、临时目录、文件访问白名单
- 统计保留周期、日志脱敏规则、调用成本单价配置

### 8.2 技术栈建议

| 层面 | 选项 A | 选项 B |
|------|--------|--------|
| 前端框架 | **React + TypeScript** | Vue 3 + TypeScript |
| UI 组件库 | **Ant Design** | shadcn/ui |
| 后端框架 | **FastAPI（Python）** | 直接用 LangServe |
| 实时通信 | **WebSocket** 或 SSE | |
| 构建工具 | Vite | |
| 状态管理 | Zustand / Jotai | |

---

## 九、飞书 Bot 集成

- 接收飞书用户消息 → 转发到 Supervisor → 流式返回结果
- 支持私聊和群聊 @机器人
- 消息格式适配：卡片消息、富文本、文件发送
- Bot 身份认证，区分不同用户

---

## 十、非功能需求

### 10.1 记忆系统
详见 **第六章"上下文管理与记忆系统"**，三层架构：
- L1 会话级短期记忆（LangGraph State + 分层压缩）
- L2 摘要级中期记忆（关系数据库，保留最近 20 个会话摘要）
- L3 持久长期记忆（关系数据库 + Qdrant，用户画像/偏好/经验）

### 10.2 可扩展性
- 新增 Agent：实现 Agent 接口 → 注册到 Supervisor 路由表 → 自动出现在 Web UI
- 新增 Skill：创建 skill.yaml + prompt.md + tools.py → 放入 skills/ 目录 → Agent 装配即可用
- 新增 Tool：用 `@tool` 装饰器注册 → 归属到对应 Skill
- 新增 MCP：配置 MCP Server → 连接测试 → 刷新工具列表 → 绑定到 Skill
- 新增 Workflow：定义步骤 DAG → 配置输入输出映射 → 注册到 Workflow Registry
- 新增文档类型：实现 DocumentLoader 子类 → 注册到知识库解析器

### 10.3 安全
- API Key 用环境变量/.env，不入库
- Git 操作白名单目录
- 飞书发布前预览确认
- 定时任务启停需确认
- Agent / Skill / Tool / MCP / Workflow 都要支持权限等级和工作目录隔离
- 高风险操作默认需要确认：删除文件、执行 shell、发布外部消息、写入数据库、推送 Git、修改远程文档
- 敏感配置只允许保存环境变量引用或加密值，不在日志和统计页面明文展示

### 10.4 可观测性与统计
- 所有 Agent、Skill、Tool、MCP、Workflow 调用必须写入结构化调用日志
- 每次用户请求生成统一 `trace_id`，跨 Supervisor、Agent、Skill、Tool/MCP、Workflow 贯穿链路
- 统计必须至少支持：调用量、成功率、失败率、平均耗时、P95 耗时、最近错误、Token 用量、成本估算
- 统计维度必须至少支持：时间、入口、Agent、Skill、Tool、MCP、Workflow、工作目录、状态
- Web UI 必须提供统计总览、分组统计、调用链详情、失败原因分析
- 日志需要支持脱敏、保留周期配置、按时间清理

### 10.5 管理与审计
- 所有能力配置变更需要记录审计日志：谁在什么时候新增/修改/删除/启用/禁用了什么
- Skill、MCP、Workflow 删除前必须做依赖检查，列出受影响 Agent / Workflow / 定时任务
- 能力配置需要支持导入/导出，便于迁移服务器或备份
- 关键配置变更建议支持版本历史和回滚，尤其是 Skill Prompt、Workflow DAG、MCP 认证配置
- Scheduler 自动执行的任务需要记录触发来源、执行人/系统身份、执行结果和失败告警

---

## 十一、技术选型总览

| 层面 | 选型 | 说明 |
|------|------|------|
| Agent 框架 | LangGraph | 有状态多 Agent，条件路由+循环 |
| LLM 调用 | LangChain + DeepSeek API | ChatModel 统一接口 |
| Skill 注册中心 | 自建 SkillRegistry（YAML 驱动） | 热加载、版本管理、依赖检查 |
| Tool 注册中心 | 自建 ToolRegistry | 参数 schema、权限、调用统计、测试调用 |
| MCP 注册中心 | 自建 MCPRegistry | MCP Server 配置、连接测试、工具刷新、权限隔离 |
| Workflow 注册中心 | 自建 WorkflowRegistry / LangGraph 子图 | 固定流程模板、DAG、执行历史 |
| 向量数据库 | **Qdrant**（推荐） | Docker 部署，混合检索，有 Dashboard |
| 关系存储 | PostgreSQL（生产）/ SQLite（本地开发） | 用户配置、Skill 装配表、MCP 配置、任务列表、调用日志、统计聚合 |
| 定时任务 | APScheduler | cron 表达式，持久化 |
| 后端 API | FastAPI | WebSocket 支持，异步 |
| 前端 | React + TypeScript + Ant Design | 成熟稳定 |
| 飞书 SDK | lark-oapi | 官方 Python SDK |
| 部署 | Docker Compose | 一键部署 Agent 服务 + Qdrant + Web UI |
| Python | 3.11 | 用户已有环境 |

---

## 十二、待确认问题（更新）

1. ~~交互入口~~ → 已确认：Web UI + 飞书 Bot
2. ~~部署方式~~ → 已确认：服务器 Docker Compose 部署
3. **向量数据库** → 默认推荐 Qdrant，最终可再确认
4. **前端技术栈**：React + Ant Design 还是 Vue + shadcn/ui？还是你有其他偏好？
5. **飞书 Bot**：已申请好还是需要从零开发？
6. **日报数据源**：纯 Git commits 自动汇总优先，还是手动口述为主？
7. **优先级**：建议先搭 **Agent 骨架 + Web UI 对话** → 知识库 → 各领域 Agent → 飞书 Bot → 定时任务？你觉得这个顺序如何？
8. **代码仓库**：新建还是放在已有仓库？
9. ~~MCP 是否需要~~ → 已确认需要；具体第三方 MCP 后续再配置
10. ~~工作目录策略~~ → 已确认默认基于 Agent 部署目录/默认目录，Skill/Workflow 可在白名单内覆盖
11. **高风险操作确认策略**：当前建议 Web UI 弹窗、飞书卡片、CLI 确认码；需确认是否接受
12. ~~统计保留周期~~ → 已确认调用日志和统计明细默认保留 90 天
13. ~~Workflow 编辑方式~~ → 已确认第一期不做可视化页面编排，先用 YAML + 表单
14. **外部 Skill 沙箱**：第一期是否接受“受限 subprocess + 默认禁用”，后续升级 Docker 沙箱？
