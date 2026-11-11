import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

KB_SURFACES = ("kb_search",)
TOOL_SURFACES = ("tool_call",)


class FilterRequired(Exception):
    pass


class CountMismatch(Exception):
    def __init__(self, count):
        self.count = count
        super().__init__("matched record count changed")
SENSITIVE_KEY = re.compile(r"authorization|cookie|password|passwd|token|secret|api[-_]?key|credential", re.I)
_PATTERNS = (
    re.compile(r"(?i)sk-[a-z0-9_-]{8,}"),
    re.compile(r"(?i)(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?key|secret|token|password|passwd)\s*[:=]\s*)([^\s,;\"'&]+)"),
    re.compile(r'''(?i)((?:["'])(?:api[_-]?key|access[_-]?key|secret|token|password|passwd)(?:["'])\s*:\s*)(["'])(.*?)(\2)'''),
)


def _normalize_time(value, end=False):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        text = text + ("T23:59:59.999999+00:00" if end else "T00:00:00+00:00")
    return text


def _redact_text(text, secrets=()):
    for secret in sorted(set(value for value in secrets if value), key=len, reverse=True):
        text = text.replace(secret, "[已隐藏]")
        encoded = json.dumps(secret)[1:-1]
        if encoded != secret:
            text = text.replace(encoded, "[已隐藏]")
    for pattern in _PATTERNS:
        if pattern.groups >= 1:
            text = pattern.sub(lambda match: match.group(1) + '"[已隐藏]"', text)
        else:
            text = pattern.sub("[已隐藏]", text)
    return text


def redact_value(value, secrets=()):
    if isinstance(value, dict):
        if isinstance(value.get("key"), str) and (value.get("secret") or SENSITIVE_KEY.search(value["key"])):
            return {key: "[已隐藏]" if key == "value" else redact_value(val, secrets) for key, val in value.items()}
        if isinstance(value.get("name"), str) and SENSITIVE_KEY.search(value["name"]):
            return {key: "[已隐藏]" if key == "value" else redact_value(val, secrets) for key, val in value.items()}
        return {key: "[已隐藏]" if SENSITIVE_KEY.search(str(key)) and val is not None
                else redact_value(val, secrets) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, str):
        if value[:1] in ("{", "["):
            try:
                parsed = json.loads(value)
                return json.dumps(redact_value(parsed, secrets), ensure_ascii=False)
            except (ValueError, TypeError, RecursionError):
                pass
        return _redact_text(value, secrets)
    return value


def redact_summary(text):
    return redact_value((text or "").strip())


class AuditStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS kb_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, surface TEXT NOT NULL,
                    session_id TEXT, query_summary TEXT NOT NULL DEFAULT '', tool_name TEXT,
                    permission TEXT, hit INTEGER NOT NULL DEFAULT 0, top_k INTEGER NOT NULL DEFAULT 0,
                    sources TEXT NOT NULL DEFAULT '[]', elapsed_ms INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'ok', error_code TEXT
                );
                CREATE INDEX IF NOT EXISTS kb_audit_surface ON kb_audit(surface,id DESC);
                CREATE TABLE IF NOT EXISTS kb_audit_details (
                    audit_id INTEGER PRIMARY KEY, question TEXT, answer TEXT, correct_answer TEXT,
                    answer_type TEXT NOT NULL, snapshots TEXT NOT NULL, calls TEXT NOT NULL,
                    parse_errors TEXT NOT NULL, turn_id TEXT, call_id TEXT, source TEXT
                );
            """)
        except Exception:
            connection.close()
            raise
        return connection

    def record(self, surface, *, session_id=None, query_summary="", tool_name=None,
               permission=None, hit=False, top_k=0, sources=None, elapsed_ms=0,
               status="ok", error_code=None, question=None, answer=None,
               snapshots=None, calls=None, parse_errors=None, turn_id=None, call_id=None,
               source="manual", secrets=(), answer_type=None):
        safe = redact_value({"summary": query_summary, "question": question, "answer": answer,
                             "sources": sources or [], "snapshots": snapshots or [],
                             "calls": calls or [], "parse_errors": parse_errors or []}, secrets)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute("""INSERT INTO kb_audit
                (ts,surface,session_id,query_summary,tool_name,permission,hit,top_k,sources,elapsed_ms,status,error_code)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (datetime.now(timezone.utc).isoformat(), surface, str(session_id) if session_id else None,
                 safe["summary"][:200], tool_name, permission, int(bool(hit)), top_k,
                 json.dumps(safe["sources"], ensure_ascii=False), int(elapsed_ms), status, error_code))
            audit_id = cursor.lastrowid
            answer_type = answer_type or ("retrieval_only" if surface == "kb_search" else "tool_only" if surface == "tool_call" else "parse_diagnostic")
            connection.execute("INSERT INTO kb_audit_details VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (audit_id, safe["question"][:4000] if safe["question"] is not None else None,
                 safe["answer"][:32000] if safe["answer"] is not None else None, None, answer_type,
                 json.dumps(safe["snapshots"], ensure_ascii=False), json.dumps(safe["calls"], ensure_ascii=False),
                 json.dumps(safe["parse_errors"], ensure_ascii=False), str(turn_id) if turn_id else None, call_id, source))
        return audit_id

    @staticmethod
    def _public(row):
        item = dict(row)
        item["hit"] = bool(item["hit"])
        item["sources"] = json.loads(item.get("sources") or "[]")
        item["evaluation_score"] = None
        return item

    @staticmethod
    def _filter_parts(surfaces, q="", answer_type=None, status=None,
                      tool_name=None, since=None, until=None):
        clauses = ["a.surface IN (" + ",".join("?" for _ in surfaces) + ")"]
        params = list(surfaces)
        needle = (q or "").strip()
        if needle:
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            like = "%" + escaped + "%"
            clauses.append("(a.query_summary LIKE ? ESCAPE '\\' OR a.tool_name LIKE ? ESCAPE '\\'"
                           " OR d.question LIKE ? ESCAPE '\\' OR d.answer LIKE ? ESCAPE '\\')")
            params += [like, like, like, like]
        if answer_type:
            clauses.append("d.answer_type = ?")
            params.append(answer_type)
        if status:
            clauses.append("a.status = ?")
            params.append(status)
        if tool_name:
            clauses.append("a.tool_name = ?")
            params.append(tool_name)
        since_value = _normalize_time(since, end=False)
        until_value = _normalize_time(until, end=True)
        if since_value:
            clauses.append("a.ts >= ?")
            params.append(since_value)
        if until_value:
            clauses.append("a.ts <= ?")
            params.append(until_value)
        base = ("FROM kb_audit a LEFT JOIN kb_audit_details d ON d.audit_id=a.id WHERE "
                + " AND ".join(clauses))
        return base, params

    @staticmethod
    def _has_filter(q="", answer_type=None, status=None, tool_name=None, since=None, until=None):
        return bool((q or "").strip() or answer_type or status or tool_name or since or until)

    def _list(self, surfaces, limit, offset, q="", answer_type=None, status=None,
              tool_name=None, since=None, until=None):
        base, params = self._filter_parts(surfaces, q=q, answer_type=answer_type, status=status,
                                          tool_name=tool_name, since=since, until=until)
        with closing(self._connect()) as connection:
            rows = connection.execute("""SELECT a.*,substr(d.question,1,200) AS question,
                    substr(d.answer,1,500) AS answer,d.answer_type,d.source,d.turn_id,d.call_id """
                + base + " ORDER BY a.id DESC LIMIT ? OFFSET ?",
                (*params, max(1, min(int(limit), 200)), max(0, int(offset)))).fetchall()
            total = connection.execute("SELECT count(*) " + base, params).fetchone()[0]
        return {"items": [self._public(row) for row in rows], "total": total}

    def list_kb(self, limit=50, offset=0, **filters):
        return self._list(KB_SURFACES, limit, offset, **filters)

    def list_tools(self, limit=50, offset=0, **filters):
        return self._list(TOOL_SURFACES, limit, offset, **filters)

    def list_parsing(self, limit=50, offset=0, **filters):
        return self._list(("kb_ingest",), limit, offset, **filters)

    def delete_one(self, audit_id, surface):
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT id FROM kb_audit WHERE id=? AND surface=?",
                                     (audit_id, surface)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM kb_audit_details WHERE audit_id=?", (audit_id,))
            connection.execute("DELETE FROM kb_audit WHERE id=? AND surface=?", (audit_id, surface))
        return True

    def delete_filtered(self, surfaces, expected_total=None, q="", answer_type=None, status=None,
                        tool_name=None, since=None, until=None):
        if not self._has_filter(q=q, answer_type=answer_type, status=status,
                                tool_name=tool_name, since=since, until=until):
            raise FilterRequired()
        base, params = self._filter_parts(surfaces, q=q, answer_type=answer_type, status=status,
                                          tool_name=tool_name, since=since, until=until)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            ids = [row[0] for row in connection.execute("SELECT a.id " + base, params)]
            if expected_total is not None and len(ids) != int(expected_total):
                raise CountMismatch(len(ids))
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(f"DELETE FROM kb_audit_details WHERE audit_id IN ({placeholders})", ids)
                connection.execute(f"DELETE FROM kb_audit WHERE id IN ({placeholders})", ids)
        return len(ids)

    def detail(self, audit_id, surface):
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM kb_audit WHERE id=? AND surface=?", (audit_id, surface)).fetchone()
            if row is None:
                return None
            detail = connection.execute("SELECT * FROM kb_audit_details WHERE audit_id=?", (audit_id,)).fetchone()
        result = self._public(row)
        result.update({"question": None, "answer": None, "correct_answer": None, "answer_type": None,
                       "snapshots": [], "calls": [], "parse_errors": [], "turn_id": None,
                       "call_id": None, "source": None, "snapshot_recorded": detail is not None and detail["source"] is not None})
        if detail is not None:
            result.update({key: detail[key] for key in detail.keys() if key != "audit_id"})
            for name in ("snapshots", "calls", "parse_errors"):
                result[name] = json.loads(result[name])
        return result

    def save_correct_answer(self, audit_id, answer, secrets=()):
        safe = redact_value(answer, secrets) if answer is not None else None
        with closing(self._connect()) as connection, connection:
            row = connection.execute("SELECT id FROM kb_audit WHERE id=? AND surface='kb_search'", (audit_id,)).fetchone()
            if row is None:
                return None
            connection.execute("""INSERT INTO kb_audit_details
                (audit_id,correct_answer,answer_type,snapshots,calls,parse_errors)
                VALUES(?,?,'retrieval_only','[]','[]','[]')
                ON CONFLICT(audit_id) DO UPDATE SET correct_answer=excluded.correct_answer""", (audit_id, safe))
        return self.detail(audit_id, "kb_search")
