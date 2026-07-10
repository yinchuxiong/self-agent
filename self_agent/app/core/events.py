import json

from self_agent.app.core.models import ChatEvent


def encode_sse(event: ChatEvent) -> str:
    """Encode a typed event into the Server-Sent Events wire format."""
    payload = event.model_dump(mode="json")
    return f"event: {event.event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
