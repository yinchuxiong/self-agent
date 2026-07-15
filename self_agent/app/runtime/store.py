import sqlite3
from datetime import datetime
from threading import RLock

from self_agent.app.core.models import ChatMessage, ChatSession, utc_now
from self_agent.app.runtime.sqlite_utils import sqlite_path_from_url


class InMemoryStore:
    """Temporary session/message store.

    This keeps M1 self-contained; the method boundaries match the future database service.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._messages: dict[str, list[ChatMessage]] = {}

    def create_session(self, title: str | None = None, workspace_dir: str = "") -> ChatSession:
        session = ChatSession(title=title or "新会话", workspace_dir=workspace_dir)
        self._sessions[session.id] = session
        self._messages[session.id] = []
        return session

    def list_sessions(self) -> list[ChatSession]:
        return sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)

    def get_session(self, session_id: str) -> ChatSession:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session: {session_id}")
        return self._sessions[session_id]

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._messages.pop(session_id, None)

    def add_message(self, message: ChatMessage) -> ChatMessage:
        # First user message becomes the session title, mirroring common chat UX.
        self.get_session(message.session_id)
        self._messages[message.session_id].append(message)
        session = self._sessions[message.session_id]
        if message.role == "user" and session.title == "新会话":
            session.title = message.content[:24]
        session.updated_at = utc_now()
        return message

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        self.get_session(session_id)
        return list(self._messages[session_id])


class SQLiteStore:
    """SQLite-backed session/message store for local development and small deployments."""

    def __init__(self, database_url: str) -> None:
        self._lock = RLock()
        self._conn = sqlite3.connect(
            sqlite_path_from_url(database_url),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                workspace_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_name TEXT,
                trace_id TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
                ON chat_messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
                ON chat_sessions(updated_at);
            """
        )
        # M2 migration: add workspace_dir column if upgrading from M1 schema
        try:
            self._conn.execute(
                "ALTER TABLE chat_sessions ADD COLUMN workspace_dir TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
        except Exception:
            pass  # column already exists
        self._conn.commit()

    def create_session(self, title: str | None = None, workspace_dir: str = "") -> ChatSession:
        session = ChatSession(title=title or "新会话", workspace_dir=workspace_dir)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_sessions (id, title, workspace_dir, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.title,
                    session.workspace_dir,
                    _dump_datetime(session.created_at),
                    _dump_datetime(session.updated_at),
                ),
            )
            self._conn.commit()
        return session

    def list_sessions(self) -> list[ChatSession]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, title, workspace_dir, created_at, updated_at
                FROM chat_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> ChatSession:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT id, title, workspace_dir, created_at, updated_at
                FROM chat_sessions
                WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown session: {session_id}")
        return _session_from_row(row)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    def add_message(self, message: ChatMessage) -> ChatMessage:
        with self._lock:
            session = self._conn.execute(
                """
                SELECT id, title, workspace_dir, created_at, updated_at
                FROM chat_sessions
                WHERE id = ?
                """,
                (message.session_id,),
            ).fetchone()
            if session is None:
                raise KeyError(f"Unknown session: {message.session_id}")

            updated_at = utc_now()
            title = session["title"]
            if message.role == "user" and title == "新会话":
                title = message.content[:24]

            self._conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, role, content, agent_name, trace_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.session_id,
                    message.role,
                    message.content,
                    message.agent_name,
                    message.trace_id,
                    _dump_datetime(message.created_at),
                ),
            )
            self._conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, _dump_datetime(updated_at), message.session_id),
            )
            self._conn.commit()
        return message

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        self.get_session(session_id)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, session_id, role, content, agent_name, trace_id, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (session_id,),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _dump_datetime(value: datetime) -> str:
    return value.isoformat()


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _session_from_row(row: sqlite3.Row) -> ChatSession:
    return ChatSession(
        id=row["id"],
        title=row["title"],
        workspace_dir=row["workspace_dir"] if "workspace_dir" in row.keys() else "",
        created_at=_parse_datetime(row["created_at"]),
        updated_at=_parse_datetime(row["updated_at"]),
    )


def _message_from_row(row: sqlite3.Row) -> ChatMessage:
    return ChatMessage(
        id=row["id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        agent_name=row["agent_name"],
        trace_id=row["trace_id"],
        created_at=_parse_datetime(row["created_at"]),
    )
