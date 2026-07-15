"""LangGraph checkpointer factory — returns AsyncSqliteSaver or PostgresSaver.

The checkpointer persists LangGraph state across invocations, enabling:
- Conversation continuity (state restored by thread_id)
- Interrupt/resume for human-in-the-loop (future)
- Fault tolerance (crash recovery)

LangGraph >= 1.0 with astream_events requires async checkpointers.
We use AsyncSqliteSaver from langgraph.checkpoint.sqlite.aio.

The challenge: AsyncSqliteSaver.from_conn_string() returns an async context
manager, but AppState.__init__ is synchronous and may be called from within
uvicorn's running event loop (where asyncio.run() is forbidden).  We bridge
this gap with a dedicated thread that owns its own event loop.

Usage:
    from self_agent.app.graph.checkpointer import get_checkpointer
    checkpointer, cleanup = get_checkpointer()
    graph = builder.compile(checkpointer=checkpointer)
    # ... on shutdown: cleanup()
"""

import asyncio
import logging
import threading
from pathlib import Path

from self_agent.app.core.config import get_settings

logger = logging.getLogger(__name__)


def _enter_async_cm(ctx):
    """Enter an async context manager from synchronous code.

    Spawns a fresh thread with its own event loop, enters the context manager,
    and returns (result, cleanup_fn).  The cleanup_fn likewise spawns a thread
    to exit the context manager gracefully.

    This is safe to call regardless of whether an event loop is already running
    in the calling thread (e.g. inside uvicorn).
    """
    result = None
    error = None
    lock = threading.Event()

    def _enter():
        nonlocal result, error
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(ctx.__aenter__())
            finally:
                loop.close()
        except Exception as exc:
            error = exc
        finally:
            lock.set()

    t = threading.Thread(target=_enter, daemon=True)
    t.start()
    lock.wait()
    if error:
        raise error

    def cleanup():
        exc = None
        lock2 = threading.Event()

        def _exit():
            nonlocal exc
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(ctx.__aexit__(None, None, None))
                finally:
                    loop.close()
            except Exception as e:
                exc = e
            finally:
                lock2.set()

        t2 = threading.Thread(target=_exit, daemon=True)
        t2.start()
        lock2.wait()
        if exc:
            logger.warning("Checkpointer cleanup error: %s", exc)

    return result, cleanup


def get_checkpointer():
    """Return (checkpointer, cleanup_fn) for use with LangGraph astream_events.

    Returns:
        Tuple of (checkpointer_instance, cleanup_callable).
    """
    settings = get_settings()

    if settings.checkpoint_backend == "postgres":
        return _make_postgres_saver(settings)

    return _make_sqlite_saver()


def _make_sqlite_saver():
    """Create an AsyncSqliteSaver via thread-bridged async context manager."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_dir = Path("data")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "checkpoints.db"

    logger.info("Using AsyncSqliteSaver: %s", db_path)
    ctx = AsyncSqliteSaver.from_conn_string(str(db_path))
    return _enter_async_cm(ctx)


def _make_postgres_saver(settings):
    """Create an AsyncPostgresSaver via thread-bridged async context manager."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError:
        logger.warning(
            "langgraph-checkpoint-postgres not installed, falling back to AsyncSqliteSaver"
        )
        return _make_sqlite_saver()

    db_url = settings.checkpoint_db_url or settings.database_url
    if db_url.startswith("sqlite"):
        logger.warning(
            "Checkpoint backend is 'postgres' but database_url is sqlite. Falling back."
        )
        return _make_sqlite_saver()

    try:
        logger.info("Using AsyncPostgresSaver: %s", _mask_url(db_url))
        ctx = AsyncPostgresSaver.from_conn_string(db_url)
        return _enter_async_cm(ctx)
    except Exception:
        logger.exception("Failed to create AsyncPostgresSaver, falling back to AsyncSqliteSaver")
        return _make_sqlite_saver()


def _mask_url(url: str) -> str:
    """Mask password in connection URL for safe logging."""
    if "@" in url:
        return url.split("@")[0].rsplit(":", 1)[0] + ":***@" + url.split("@")[1]
    return url
