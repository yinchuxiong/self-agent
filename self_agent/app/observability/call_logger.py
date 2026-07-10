import sqlite3
from datetime import datetime
from statistics import mean
from threading import RLock

from self_agent.app.core.models import CallLog, MetricOverview
from self_agent.app.runtime.sqlite_utils import sqlite_path_from_url


class CallLogger:
    """Small in-memory call log used by the statistics page before database persistence."""

    def __init__(self) -> None:
        self._logs: list[CallLog] = []

    def add(self, log: CallLog) -> CallLog:
        self._logs.append(log)
        return log

    def list(self, limit: int = 100) -> list[CallLog]:
        return list(reversed(self._logs[-limit:]))

    def overview(self) -> MetricOverview:
        """Compute the dashboard summary from recent call logs."""
        if not self._logs:
            return MetricOverview(
                total_calls=0,
                success_rate=0,
                failed_calls=0,
                avg_latency_ms=0,
                p95_latency_ms=0,
                token_usage=0,
                cost_estimate=0,
                recent_errors=[],
            )
        latencies = sorted(log.latency_ms for log in self._logs)
        p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
        success_count = sum(1 for log in self._logs if log.status == "success")
        failed = [log for log in self._logs if log.status != "success"]
        return MetricOverview(
            total_calls=len(self._logs),
            success_rate=round(success_count / len(self._logs), 4),
            failed_calls=len(failed),
            avg_latency_ms=int(mean(latencies)),
            p95_latency_ms=latencies[p95_index],
            token_usage=sum(log.input_tokens + log.output_tokens for log in self._logs),
            cost_estimate=round(sum(log.cost_estimate for log in self._logs), 6),
            recent_errors=list(reversed(failed[-5:])),
        )

    @staticmethod
    def latency_ms(started_at: datetime, finished_at: datetime) -> int:
        return int((finished_at - started_at).total_seconds() * 1000)


class SQLiteCallLogger:
    """SQLite-backed call log used by statistics and future audit views."""

    def __init__(self, database_url: str) -> None:
        self._lock = RLock()
        self._conn = sqlite3.connect(
            sqlite_path_from_url(database_url),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS call_logs (
                id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                session_id TEXT,
                entrypoint TEXT NOT NULL,
                agent_name TEXT,
                skill_name TEXT,
                tool_name TEXT,
                workflow_name TEXT,
                workspace_dir TEXT,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                latency_ms INTEGER NOT NULL,
                input_summary TEXT NOT NULL,
                output_summary TEXT NOT NULL,
                error_type TEXT,
                error_message TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_estimate REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_call_logs_created
                ON call_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_call_logs_status
                ON call_logs(status);
            CREATE INDEX IF NOT EXISTS idx_call_logs_trace
                ON call_logs(trace_id);
            """
        )
        self._conn.commit()

    def add(self, log: CallLog) -> CallLog:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO call_logs (
                    id, trace_id, session_id, entrypoint, agent_name, skill_name, tool_name,
                    workflow_name, workspace_dir, status, started_at, finished_at, latency_ms,
                    input_summary, output_summary, error_type, error_message, input_tokens,
                    output_tokens, cost_estimate, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.id,
                    log.trace_id,
                    log.session_id,
                    log.entrypoint,
                    log.agent_name,
                    log.skill_name,
                    log.tool_name,
                    log.workflow_name,
                    log.workspace_dir,
                    log.status.value,
                    _dump_datetime(log.started_at),
                    _dump_datetime(log.finished_at),
                    log.latency_ms,
                    log.input_summary,
                    log.output_summary,
                    log.error_type,
                    log.error_message,
                    log.input_tokens,
                    log.output_tokens,
                    log.cost_estimate,
                    _dump_datetime(log.created_at),
                ),
            )
            self._conn.commit()
        return log

    def list(self, limit: int = 100) -> list[CallLog]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM call_logs
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [_call_log_from_row(row) for row in rows]

    def overview(self) -> MetricOverview:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM call_logs ORDER BY created_at ASC, rowid ASC"
            ).fetchall()
        logs = [_call_log_from_row(row) for row in rows]
        if not logs:
            return MetricOverview(
                total_calls=0,
                success_rate=0,
                failed_calls=0,
                avg_latency_ms=0,
                p95_latency_ms=0,
                token_usage=0,
                cost_estimate=0,
                recent_errors=[],
            )
        latencies = sorted(log.latency_ms for log in logs)
        p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95))
        success_count = sum(1 for log in logs if log.status == "success")
        failed = [log for log in logs if log.status != "success"]
        return MetricOverview(
            total_calls=len(logs),
            success_rate=round(success_count / len(logs), 4),
            failed_calls=len(failed),
            avg_latency_ms=int(mean(latencies)),
            p95_latency_ms=latencies[p95_index],
            token_usage=sum(log.input_tokens + log.output_tokens for log in logs),
            cost_estimate=round(sum(log.cost_estimate for log in logs), 6),
            recent_errors=list(reversed(failed[-5:])),
        )

    @staticmethod
    def latency_ms(started_at: datetime, finished_at: datetime) -> int:
        return int((finished_at - started_at).total_seconds() * 1000)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _dump_datetime(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _call_log_from_row(row: sqlite3.Row) -> CallLog:
    return CallLog(
        id=row["id"],
        trace_id=row["trace_id"],
        session_id=row["session_id"],
        entrypoint=row["entrypoint"],
        agent_name=row["agent_name"],
        skill_name=row["skill_name"],
        tool_name=row["tool_name"],
        workflow_name=row["workflow_name"],
        workspace_dir=row["workspace_dir"],
        status=row["status"],
        started_at=_parse_datetime(row["started_at"]),
        finished_at=_parse_datetime(row["finished_at"]),
        latency_ms=row["latency_ms"],
        input_summary=row["input_summary"],
        output_summary=row["output_summary"],
        error_type=row["error_type"],
        error_message=row["error_message"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_estimate=row["cost_estimate"],
        created_at=_parse_datetime(row["created_at"]),
    )
