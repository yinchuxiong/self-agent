from fastapi import APIRouter

from self_agent.app.core.models import SkillDefinition
from self_agent.app.state import state

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("", response_model=list[SkillDefinition])
async def list_skills() -> list[SkillDefinition]:
    return state.skill_registry.list_skills()

