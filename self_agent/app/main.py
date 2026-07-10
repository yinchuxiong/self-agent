from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from self_agent.app.api import agents, chat, placeholders, skills, statistics, tools
from self_agent.app.core.config import get_settings
from self_agent.app.state import state


def create_app() -> FastAPI:
    """Create the FastAPI application and mount the MVP API surface."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0")

    # Frontend development runs on Vite, so CORS stays explicit and environment-driven.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "app": settings.app_name, "env": settings.app_env}

    @app.on_event("shutdown")
    async def shutdown() -> None:
        state.close()

    # M1 scope: chat loop, capability registry views, statistics, and placeholder endpoints.
    app.include_router(chat.router, prefix=settings.api_prefix)
    app.include_router(agents.router, prefix=settings.api_prefix)
    app.include_router(skills.router, prefix=settings.api_prefix)
    app.include_router(tools.router, prefix=settings.api_prefix)
    app.include_router(statistics.router, prefix=settings.api_prefix)
    app.include_router(placeholders.router, prefix=settings.api_prefix)
    return app


app = create_app()
