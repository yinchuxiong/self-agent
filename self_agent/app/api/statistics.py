from fastapi import APIRouter

from self_agent.app.core.models import CallLog, MetricOverview
from self_agent.app.state import state

router = APIRouter(prefix="/statistics", tags=["statistics"])


@router.get("/overview", response_model=MetricOverview)
async def overview() -> MetricOverview:
    return state.call_logger.overview()


@router.get("/calls", response_model=list[CallLog])
async def calls(limit: int = 100) -> list[CallLog]:
    return state.call_logger.list(limit)

