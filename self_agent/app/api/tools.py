from fastapi import APIRouter

from self_agent.app.core.models import ToolDefinition
from self_agent.app.state import state

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolDefinition])
async def list_tools() -> list[ToolDefinition]:
    return state.skill_registry.list_tools()

