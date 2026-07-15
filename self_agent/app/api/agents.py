"""
Agent 管理 API —— 列出和配置 AI Agent。

这些接口供前端"Agent 管理"页面使用，可以查看所有可用的 Agent 并启用/禁用它们。

Python 语法要点：
- PATCH 方法：HTTP PATCH 用于部分更新资源，只传需要修改的字段
  （对比 PUT：PUT 要求传完整的资源对象）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from self_agent.app.core.models import AgentDefinition
from self_agent.app.state import state

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentPatch(BaseModel):
    """Agent 部分更新请求体。

    只传需要修改的字段，未传的字段保持原值。
    enabled: bool | None = None 表示可以不传这个字段（此时为 None，表示不修改）。

    Python 语法要点：
    - bool | None：这个字段接受三种情况：True、False、不传（None）
      这是"部分更新"模式的关键设计
    """
    enabled: bool | None = None


@router.get("", response_model=list[AgentDefinition])
async def list_agents() -> list[AgentDefinition]:
    """列出所有已注册的 Agent。

    返回的数据来自 AgentRegistry，包括从 .agents/ 目录扫描到的
    所有业务 Agent 以及内置的 Supervisor Agent。
    """
    return state.agent_registry.list()


@router.patch("/{agent_name}", response_model=AgentDefinition)
async def update_agent(agent_name: str, patch: AgentPatch) -> AgentDefinition:
    """启用或禁用一个 Agent。

    路径参数 {agent_name} 是 Agent 的内部名称（如 "programming"、"work" 等）。

    Python 语法要点：
    - try/except KeyError as exc：如果 agent_name 不存在，AgentRegistry.get() 抛出 KeyError
    - raise HTTPException(...) from exc：将 KeyError 转为 HTTP 404 错误，
      "from exc" 保留异常链，方便调试
    """
    try:
        # 如果 patch.enabled 是 None（没传），返回 Agent 当前状态
        if patch.enabled is None:
            return state.agent_registry.get(agent_name)
        # 否则更新启用状态
        return state.agent_registry.set_enabled(agent_name, patch.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
