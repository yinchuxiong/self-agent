from fastapi import APIRouter

router = APIRouter(tags=["mvp-placeholders"])


@router.get("/mcps")
async def list_mcps() -> list[dict]:
    return [
        {
            "name": "feishu-mcp",
            "display_name": "飞书 MCP",
            "enabled": False,
            "status": "pending_config",
            "tool_count": 0,
            "confirm_required": True,
        }
    ]


@router.get("/workflows")
async def list_workflows() -> list[dict]:
    return [
        {
            "name": "daily-report-draft",
            "display_name": "日报草稿",
            "enabled": True,
            "trigger": "manual",
            "steps": ["collect_context", "generate_draft", "confirm"],
        }
    ]


@router.get("/knowledge/documents")
async def list_documents() -> list[dict]:
    return []


@router.get("/settings")
async def get_settings_view() -> dict:
    return {
        "llm_provider": "deepseek",
        "database": "sqlite-dev/postgres-prod",
        "vector_store": "qdrant",
        "log_retention_days": 90,
    }

