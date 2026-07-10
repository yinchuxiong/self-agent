from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from self_agent.app.core.models import AgentDefinition
from self_agent.app.state import state

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentPatch(BaseModel):
    enabled: bool | None = None


@router.get("", response_model=list[AgentDefinition])
async def list_agents() -> list[AgentDefinition]:
    return state.agent_registry.list()


@router.patch("/{agent_name}", response_model=AgentDefinition)
async def update_agent(agent_name: str, patch: AgentPatch) -> AgentDefinition:
    try:
        if patch.enabled is None:
            return state.agent_registry.get(agent_name)
        return state.agent_registry.set_enabled(agent_name, patch.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

