"""Incremental static check gate for Ruff and Pyright against a recorded baseline."""

from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).resolve().with_name("lint_baseline.json")

DiagnosticKey = tuple[str, str, str, str, str]


def _tool_bin(name: str) -> str:
    sibling = Path(sys.executable).with_name(name + (".exe" if sys.platform == "win32" else ""))
    if sibling.is_file():
        return str(sibling)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Missing required tool executable: {name}")


def _read_source_line(rel_path: str, row: int, cache: dict[str, list[str]]) -> str:
    if rel_path not in cache:
        target = ROOT / rel_path
        cache[rel_path] = target.read_text(encoding="utf-8", errors="replace").splitlines() if target.is_file() else []
    lines = cache[rel_path]
    return lines[row - 1].strip() if 1 <= row <= len(lines) else ""


def _rel_path(raw_path: str) -> str:
    return Path(raw_path).resolve().relative_to(ROOT.resolve()).as_posix()


def _run_ruff(line_cache: dict[str, list[str]]) -> list[dict]:
    proc = subprocess.run(
        [_tool_bin("ruff"), "check", "--output-format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ruff failed (exit {proc.returncode}): {proc.stderr.strip()}")
    items = json.loads(proc.stdout or "[]")
    records = []
    for item in items:
        rel_path = _rel_path(item["filename"])
        row = int(item["location"]["row"])
        records.append({
            "tool": "ruff",
            "path": rel_path,
            "line": row,
            "code": item.get("code") or "syntax",
            "message": item["message"],
            "source_line": _read_source_line(rel_path, row, line_cache),
        })
    return records


def _run_pyright(line_cache: dict[str, list[str]]) -> list[dict]:
    proc = subprocess.run(
        [_tool_bin("pyright"), "--outputjson"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"pyright failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    payload = json.loads(proc.stdout or "{}")
    records = []
    for item in payload.get("generalDiagnostics", []):
        rel_path = _rel_path(item["file"])
        row = int(item["range"]["start"]["line"]) + 1
        records.append({
            "tool": "pyright",
            "path": rel_path,
            "line": row,
            "code": item.get("rule") or item.get("severity") or "error",
            "message": item["message"],
            "source_line": _read_source_line(rel_path, row, line_cache),
        })
    return records


def _fingerprint(record: dict) -> DiagnosticKey:
    return (record["tool"], record["path"], record["code"], record["message"], record["source_line"])


def collect_diagnostics() -> list[dict]:
    line_cache: dict[str, list[str]] = {}
    records = _run_ruff(line_cache) + _run_pyright(line_cache)
    records.sort(key=lambda item: (item["tool"], item["path"], item["line"], item["code"], item["message"]))
    return records


def write_baseline() -> int:
    records = collect_diagnostics()
    entries = [
        {key: item[key] for key in ("tool", "path", "code", "message", "source_line")}
        for item in records
    ]
    entries.sort(key=lambda item: (item["tool"], item["path"], item["code"], item["message"], item["source_line"]))
    BASELINE_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Baseline updated: {len(entries)} diagnostics saved to {BASELINE_PATH.relative_to(ROOT).as_posix()}")
    return 0


def check_incremental() -> int:
    if not BASELINE_PATH.is_file():
        print(f"Missing baseline file: {BASELINE_PATH}", file=sys.stderr)
        return 2
    baseline_entries = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline_counts: Counter[DiagnosticKey] = Counter(_fingerprint(item) for item in baseline_entries)
    current_records = collect_diagnostics()
    remaining_baseline = Counter(baseline_counts)
    new_records = []
    for record in current_records:
        key = _fingerprint(record)
        if remaining_baseline[key] > 0:
            remaining_baseline[key] -= 1
        else:
            new_records.append(record)
    ruff_total = sum(1 for item in current_records if item["tool"] == "ruff")
    pyright_total = sum(1 for item in current_records if item["tool"] == "pyright")
    print(
        f"Incremental lint check: ruff={ruff_total}, pyright={pyright_total}, "
        f"baseline={len(baseline_entries)}, new={len(new_records)}"
    )
    if new_records:
        for item in new_records:
            first_line = item["message"].splitlines()[0]
            print(f"NEW [{item['tool']}] {item['path']}:{item['line']} [{item['code']}] {first_line}")
        return 1
    return 0


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--update-baseline":
        return write_baseline()
    if len(sys.argv) != 1:
        print("Usage: lint_incremental.py [--update-baseline]", file=sys.stderr)
        return 2
    return check_incremental()


if __name__ == "__main__":
    raise SystemExit(main())
