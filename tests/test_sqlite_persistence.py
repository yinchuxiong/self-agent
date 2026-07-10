from self_agent.app.core.models import CallLog, CallStatus, ChatMessage, utc_now
from self_agent.app.observability.call_logger import SQLiteCallLogger
from self_agent.app.runtime.store import SQLiteStore


def _sqlite_url(path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def test_sqlite_store_persists_sessions_and_messages(tmp_path):
    database_url = _sqlite_url(tmp_path / "self_agent.db")
    store = SQLiteStore(database_url)

    session = store.create_session()
    store.add_message(
        ChatMessage(
            session_id=session.id,
            role="user",
            content="帮我 review 今日代码",
            trace_id="trace_1",
        )
    )
    store.add_message(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content="已路由到 Programming Agent",
            agent_name="programming",
            trace_id="trace_1",
        )
    )

    reopened = SQLiteStore(database_url)
    sessions = reopened.list_sessions()
    messages = reopened.list_messages(session.id)

    assert len(sessions) == 1
    assert sessions[0].title == "帮我 review 今日代码"
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[1].agent_name == "programming"

    reopened.delete_session(session.id)
    assert reopened.list_sessions() == []
    store.close()
    reopened.close()


def test_sqlite_call_logger_persists_and_computes_overview(tmp_path):
    database_url = _sqlite_url(tmp_path / "self_agent.db")
    logger = SQLiteCallLogger(database_url)
    started_at = utc_now()
    finished_at = utc_now()

    logger.add(
        CallLog(
            trace_id="trace_success",
            session_id="sess_1",
            status=CallStatus.success,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=120,
            input_summary="hello",
            output_summary="world",
            input_tokens=2,
            output_tokens=3,
        )
    )
    logger.add(
        CallLog(
            trace_id="trace_failed",
            session_id="sess_1",
            status=CallStatus.failed,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=240,
            input_summary="bad",
            output_summary="",
            error_type="RuntimeError",
            error_message="boom",
        )
    )

    reopened = SQLiteCallLogger(database_url)
    logs = reopened.list()
    overview = reopened.overview()

    assert len(logs) == 2
    assert overview.total_calls == 2
    assert overview.success_rate == 0.5
    assert overview.failed_calls == 1
    assert overview.token_usage == 5
    assert overview.recent_errors[0].error_message == "boom"
    logger.close()
    reopened.close()
