"""个人知识库「多库」迁移脚本（默认库承载旧数据）。

**默认不执行。** 由 Lead 备份数据库后手动运行：

    .venv\\Scripts\\python.exe scripts\\migrate_kb_libraries.py --db data/personal_kb.sqlite3

幂等，只做结构补齐与归属回填，不删除/不改写任何资料正文。失败即整体回滚：
1) 前置校验：库文件必须已存在且含 kb_documents，否则直接报错、绝不新建空库；
2) 单事务 BEGIN IMMEDIATE 内建 kb_libraries、补 library_id、建/复用唯一默认库；
3) 回填空归属到默认库，并校验没有指向未知库的孤儿；
4) 安装索引/触发器约束后提交，打印迁移前后计数、默认库 ID 与回填数供核对。
"""
import argparse
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.personal_kb import install_library_constraints  # noqa: E402

DEFAULT_DB = ROOT / "data" / "personal_kb.sqlite3"
DEFAULT_LIBRARY_NAME = "默认知识库"


def _precheck(db_path: Path) -> None:
    if not db_path.is_file():
        raise SystemExit(f"数据库不存在，拒绝新建：{db_path}")
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kb_documents'").fetchone()
    finally:
        conn.close()
    if not has:
        raise SystemExit(f"不是个人知识库（缺 kb_documents），拒绝迁移：{db_path}")


def migrate(db_path: Path) -> dict:
    _precheck(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        before = conn.execute("SELECT count(*) FROM kb_documents").fetchone()[0]
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS kb_libraries (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0)""")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(kb_documents)")}
            if "library_id" not in columns:
                conn.execute("ALTER TABLE kb_documents ADD COLUMN library_id TEXT")
            defaults = conn.execute("SELECT id FROM kb_libraries WHERE is_default=1").fetchall()
            if len(defaults) > 1:
                raise RuntimeError("存在多个默认库，请先人工确认后再迁移。")
            if defaults:
                default_id = defaults[0][0]
            else:
                default_id = uuid.uuid4().hex
                conn.execute("INSERT INTO kb_libraries(id,name,created_at,is_default) VALUES(?,?,?,1)",
                             (default_id, DEFAULT_LIBRARY_NAME, datetime.now(timezone.utc).isoformat()))
            backfilled = conn.execute(
                "UPDATE kb_documents SET library_id=? WHERE library_id IS NULL OR library_id=''",
                (default_id,)).rowcount
            orphans = conn.execute("""SELECT count(*) FROM kb_documents d WHERE d.library_id IS NULL
                OR NOT EXISTS(SELECT 1 FROM kb_libraries l WHERE l.id=d.library_id)""").fetchone()[0]
            if orphans:
                raise RuntimeError(f"仍有 {orphans} 份资料无有效库归属，已回滚。")
            install_library_constraints(conn)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        after = conn.execute("SELECT count(*) FROM kb_documents").fetchone()[0]
        return {"db": str(db_path), "documents_before": before, "documents_after": after,
                "default_library_id": default_id, "backfilled_documents": backfilled, "orphans": 0}
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="个人知识库多库迁移（幂等，默认库承载旧数据）")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    print(migrate(Path(args.db)))
