"""Shared LLM client factory — builds ChatOpenAI instances with correct SSL config.

This module exists because on Windows with SSL-intercepting proxies (e.g. Avast Web Shield,
corporate MITM proxies), Python's httpx cannot verify TLS certificates unless the proxy's
CA cert is injected. The Settings.llm_ssl_verify flag allows disabling verification for
development, while keeping it on by default for production safety.
"""

import json
import logging

import httpx
from langchain_openai import ChatOpenAI

from self_agent.app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ── Debug flag for logging raw API requests ──────────────────────────
# Set to False once the message-format issue is resolved.
_DEBUG_LOG_API_REQUESTS = True


class _LoggingTransport(httpx.AsyncHTTPTransport):
    """An httpx transport wrapper that logs the request body for debugging.

    Wraps the default async transport and dumps the JSON payload of every
    POST request so we can see exactly what is being sent to the LLM provider.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if _DEBUG_LOG_API_REQUESTS and request.method == "POST":
            # Try to log the JSON body (truncated for readability)
            try:
                body = request.content
                if body:
                    payload = json.loads(body)
                    # Truncate message contents for readability
                    if "messages" in payload:
                        msgs = payload["messages"]
                        for m in msgs:
                            if "content" in m and isinstance(m["content"], str) and len(m["content"]) > 150:
                                m["content"] = m["content"][:150] + "...(truncated)"
                    logger.info(
                        "🚀 API REQUEST to %s:\n%s",
                        str(request.url),
                        json.dumps(payload, ensure_ascii=False, indent=2)[:4000],
                    )
            except Exception:
                logger.info("🚀 API REQUEST (non-JSON): %s", request.content[:500])
        return await super().handle_async_request(request)


def _build_http_async_client(settings: Settings) -> httpx.AsyncClient:
    """Build an httpx AsyncClient respecting the llm_ssl_verify setting.

    When SSL verification is disabled, we also suppress the InsecureRequestWarning
    that httpx emits on every unverified request.
    """
    verify = settings.llm_ssl_verify
    if not verify:
        logger.warning(
            "LLM SSL verification is DISABLED (LLM_SSL_VERIFY=false). "
            "This is insecure — only use behind a trusted SSL-intercepting proxy."
        )
    transport = _LoggingTransport(verify=verify)
    return httpx.AsyncClient(transport=transport)


def build_chat_openai(
    settings: Settings | None = None,
    *,
    model: str | None = None,
    temperature: float = 0.3,
    streaming: bool = True,
    **kwargs,
) -> ChatOpenAI:
    """Build a ChatOpenAI instance with the correct httpx SSL configuration.

    Args:
        settings: App settings. If None, calls get_settings().
        model: Model name override. Defaults to settings.default_model.
        temperature: Sampling temperature.
        streaming: Whether to enable token streaming.
        **kwargs: Passed through to ChatOpenAI (e.g. model_kwargs).

    Returns:
        A configured ChatOpenAI instance ready for .ainvoke() / .astream().
    """
    if settings is None:
        settings = get_settings()

    return ChatOpenAI(
        model=model or settings.default_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url.rstrip("/"),
        temperature=temperature,
        streaming=streaming,
        http_async_client=_build_http_async_client(settings),
        **kwargs,
    )
