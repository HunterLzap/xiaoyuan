"""Bounded, secret-redacted system error store for Web UI diagnostics."""
from __future__ import annotations

from collections import deque
from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any

from .audit_store import redact_value

_QUERY_SECRET_RE = re.compile(r"([?&](?:key|token|secret|password)=)[^&\s\"']+", re.IGNORECASE)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-+/=]+", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_error_text(text: str, secrets=()) -> str:
    redacted = redact_value(str(text or ""), secrets)
    s = str(redacted or "")
    s = _QUERY_SECRET_RE.sub(r"\1***", s)
    s = _BEARER_RE.sub(r"\1***", s)
    return s[:1200]


class ErrorLogStore:
    """Stores recent sanitized system/device/desktop/model errors in SQLite or memory."""

    def __init__(self, path: Path | None = None, max_rows: int = 300):
        self.path = path
        self.max_rows = max(50, int(max_rows))
        self._lock = threading.Lock()
        self._memory: deque[dict[str, Any]] = deque(maxlen=self.max_rows)
        self._next_id = 1
        if self.path is not None:
            self._init_db()

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    source TEXT NOT NULL,
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail_json TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_errors_ts ON system_errors(ts DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_system_errors_source ON system_errors(source, id DESC)")

    def record(
        self,
        source: str,
        code: str,
        message: str,
        *,
        detail: dict | None = None,
        secrets=(),
    ) -> dict[str, Any] | None:
        ts = _utc_now()
        clean_source = str(source or "system")[:32]
        clean_code = str(code or "unknown_error")[:80]
        clean_msg = sanitize_error_text(message, secrets) or clean_code
        clean_detail: dict | None = None
        if isinstance(detail, dict) and detail:
            redacted = redact_value(detail, secrets)
            if isinstance(redacted, dict):
                clean_detail = {
                    str(k)[:48]: sanitize_error_text(v, secrets) if isinstance(v, str) else v
                    for k, v in list(redacted.items())[:16]
                }
        detail_json = json.dumps(clean_detail, ensure_ascii=False) if clean_detail else None
        with suppress(sqlite3.Error, OSError, ValueError, TypeError):
            with self._lock:
                if self.path is None:
                    entry = {
                        "id": self._next_id,
                        "ts": ts,
                        "source": clean_source,
                        "code": clean_code,
                        "message": clean_msg,
                        "detail": clean_detail,
                    }
                    self._next_id += 1
                    self._memory.appendleft(entry)
                    return entry
                with self._connect() as conn:
                    cur = conn.execute(
                        "INSERT INTO system_errors(ts, source, code, message, detail_json) VALUES (?, ?, ?, ?, ?)",
                        (ts, clean_source, clean_code, clean_msg, detail_json),
                    )
                    row_id = cur.lastrowid
                    conn.execute(
                        "DELETE FROM system_errors WHERE id NOT IN "
                        "(SELECT id FROM system_errors ORDER BY id DESC LIMIT ?)",
                        (self.max_rows,),
                    )
                    return {
                        "id": row_id,
                        "ts": ts,
                        "source": clean_source,
                        "code": clean_code,
                        "message": clean_msg,
                        "detail": clean_detail,
                    }
        return None

    def list(self, limit: int = 50, offset: int = 0, source: str = "", q: str = "") -> dict[str, Any]:
        lim = max(1, min(int(limit), 200))
        off = max(0, int(offset))
        src = (source or "").strip()
        needle = (q or "").strip().lower()
        with self._lock:
            if self.path is None:
                items = list(self._memory)
                if src:
                    items = [item for item in items if item["source"] == src]
                if needle:
                    items = [
                        item for item in items
                        if needle in item["code"].lower()
                        or needle in item["message"].lower()
                        or (item["detail"] and needle in json.dumps(item["detail"], ensure_ascii=False).lower())
                    ]
                return {"items": items[off:off + lim], "total": len(items)}
            clauses = []
            params: list[Any] = []
            if src:
                clauses.append("source = ?")
                params.append(src)
            if needle:
                clauses.append("(LOWER(code) LIKE ? OR LOWER(message) LIKE ? OR LOWER(COALESCE(detail_json, '')) LIKE ?)")
                pat = f"%{needle}%"
                params.extend([pat, pat, pat])
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            with self._connect() as conn:
                total = conn.execute(f"SELECT COUNT(*) FROM system_errors {where}", params).fetchone()[0]
                rows = conn.execute(
                    f"SELECT id, ts, source, code, message, detail_json FROM system_errors {where} "
                    "ORDER BY id DESC LIMIT ? OFFSET ?",
                    [*params, lim, off],
                ).fetchall()
            out = []
            for row in rows:
                detail_obj = None
                if row["detail_json"]:
                    with suppress(ValueError):
                        detail_obj = json.loads(row["detail_json"])
                out.append({
                    "id": row["id"],
                    "ts": row["ts"],
                    "source": row["source"],
                    "code": row["code"],
                    "message": row["message"],
                    "detail": detail_obj,
                })
            return {"items": out, "total": int(total)}

    def clear(self) -> int:
        with self._lock:
            if self.path is None:
                count = len(self._memory)
                self._memory.clear()
                return count
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM system_errors")
                return int(cur.rowcount or 0)
