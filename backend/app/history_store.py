"""Single local SQLite file; each complete conversation snapshot is atomic."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from uuid import UUID

from .schemas import SessionDetail, SessionSummary


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT PRIMARY KEY,
                snapshot TEXT NOT NULL
            )""")

    def load(self) -> list[SessionDetail]:
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT snapshot FROM conversations").fetchall()
        try:
            return [SessionDetail.model_validate_json(row[0]) for row in rows]
        except ValueError:
            raise RuntimeError("本机会话记录格式损坏；请备份 data/conversations.sqlite3 后修复，未自动清空。") from None

    def get(self, session_id: UUID) -> SessionDetail | None:
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT snapshot FROM conversations WHERE session_id=?", (str(session_id),),
            ).fetchone()
        if row is None:
            return None
        try:
            return SessionDetail.model_validate_json(row[0])
        except ValueError:
            raise RuntimeError("本机会话记录格式损坏；未自动清空，请先备份数据库。") from None

    def summaries(self, limit: int | None = None, offset: int = 0, q: str = "",
                  overrides: list[SessionSummary] | None = None) -> list[SessionSummary]:
        cached = json.dumps([item.model_dump(mode="json") for item in overrides or []])
        sql = """WITH cached AS (
                    SELECT json_extract(value, '$.session_id') AS session_id,
                           json_extract(value, '$.title') AS title,
                           json_extract(value, '$.created_at') AS created_at,
                           json_extract(value, '$.updated_at') AS updated_at,
                           json_extract(value, '$.message_count') AS message_count,
                           json_extract(value, '$.history_persisted') AS history_persisted
                    FROM json_each(?)
                 ), entries AS (
                    SELECT session_id, json_extract(snapshot, '$.title') AS title,
                           json_extract(snapshot, '$.created_at') AS created_at,
                           json_extract(snapshot, '$.updated_at') AS updated_at,
                           json_array_length(json_extract(snapshot, '$.messages')) AS message_count,
                           1 AS history_persisted
                    FROM conversations WHERE session_id NOT IN (SELECT session_id FROM cached)
                    UNION ALL SELECT * FROM cached
                 )
                 SELECT session_id,title,created_at,updated_at,message_count,history_persisted
                 FROM entries WHERE instr(lower(title), lower(?)) > 0
                 ORDER BY updated_at DESC, session_id DESC LIMIT ? OFFSET ?"""
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(sql, (cached, q.strip(), limit if limit is not None else -1, offset)).fetchall()
        return [SessionSummary(
            session_id=row[0], title=row[1], created_at=row[2], updated_at=row[3],
            message_count=row[4], history_persisted=row[5],
        ) for row in rows]

    def save(self, conversation: SessionDetail) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""INSERT INTO conversations(session_id, snapshot) VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET snapshot=excluded.snapshot""",
                (str(conversation.session_id), conversation.model_dump_json()))

    def delete(self, session_id: UUID) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DELETE FROM conversations WHERE session_id=?", (str(session_id),))
