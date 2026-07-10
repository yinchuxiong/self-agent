from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from self_agent.app.core.events import encode_sse
from self_agent.app.core.models import ChatRequest, ChatSession
from self_agent.app.state import state

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSession)
async def create_session() -> ChatSession:
    return state.store.create_session()


@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions() -> list[ChatSession]:
    return state.store.list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    try:
        session = state.store.get_session(session_id)
        messages = state.store.list_messages(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session": session, "messages": messages}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str) -> None:
    state.store.delete_session(session_id)


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, request: ChatRequest) -> StreamingResponse:
    try:
        state.store.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def stream():
        # Convert typed runtime events into SSE packets consumed by the React chat page.
        async for event in state.runtime.stream_chat(session_id, request):
            yield encode_sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")
