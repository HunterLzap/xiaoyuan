"""Per-mode and per-provider voice profile storage in SQLite.

Keeps voice selections, speaking instructions, clone references, and rate/pitch
scoped to (voice_mode, provider, model) so switching away never overwrites or deletes
the previous setup and switching back restores it directly.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from pydantic import ValidationError

from .config import Settings

BUSINESS_STATE_FIELDS = frozenset({
    "selected_tool_ids",
    "selected_kb_ids",
    "m5stack_enabled",
    "personal_kb_enabled",
    "weather_enabled",
    "weather_default_city",
    "embedding_enabled",
    "desktop_enabled",
    "desktop_vision_model",
    "desktop_planner_model",
    "tts_rate",
    "tts_pitch",
    "system_prompt",
    "agent_profile",
    "voice_mode",
})


def realtime_scope(provider: str, model: str) -> str:
    return f"realtime:{(provider or '').strip()}:{(model or '').strip()}"


def tts_scope(provider: str, model: str) -> str:
    return f"tts:{(provider or '').strip()}:{(model or '').strip()}"


class VoiceProfileStore:
    def __init__(self, path: Path | None):
        self.path = path
        self._memory: dict[str, dict] = {}
        self._settings_memory: dict[str, object] = {}
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
                CREATE TABLE IF NOT EXISTS voice_profiles (
                    scope_key TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    instruction TEXT NOT NULL DEFAULT '',
                    clone_sample TEXT NOT NULL DEFAULT '',
                    rate REAL NOT NULL DEFAULT 1.0,
                    pitch REAL NOT NULL DEFAULT 0.0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get_settings(self) -> dict[str, object]:
        if self.path is None:
            return dict(self._settings_memory)
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM assistant_settings").fetchall()
        result: dict[str, object] = {}
        for row in rows:
            if row["key"] not in BUSINESS_STATE_FIELDS:
                continue
            try:
                result[row["key"]] = json.loads(row["value_json"])
            except ValueError:
                continue
        return result

    def save_settings(self, values: dict[str, object]) -> dict[str, object]:
        filtered = {k: v for k, v in values.items() if k in BUSINESS_STATE_FIELDS}
        if not filtered:
            return self.get_settings()
        if self.path is None:
            self._settings_memory.update(filtered)
            return dict(self._settings_memory)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO assistant_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                [(k, json.dumps(v, ensure_ascii=False), now) for k, v in filtered.items()],
            )
        return self.get_settings()

    def overlay_settings(self, settings: Settings) -> Settings:
        saved = self.get_settings()
        if not saved:
            return settings
        try:
            return Settings.model_validate({**settings.model_dump(), **saved})
        except ValidationError:
            return settings

    def get(self, scope_key: str) -> dict | None:
        if self.path is None:
            item = self._memory.get(scope_key)
            return dict(item) if item else None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scope_key, mode, provider, model, voice, instruction, clone_sample, rate, pitch, updated_at "
                "FROM voice_profiles WHERE scope_key = ?",
                (scope_key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def all_profiles(self) -> dict[str, dict]:
        if self.path is None:
            return {key: dict(value) for key, value in self._memory.items()}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope_key, mode, provider, model, voice, instruction, clone_sample, rate, pitch, updated_at "
                "FROM voice_profiles"
            ).fetchall()
        return {row["scope_key"]: dict(row) for row in rows}

    def save_scope(
        self,
        *,
        scope_key: str,
        mode: str,
        provider: str,
        model: str,
        voice: str,
        instruction: str = "",
        clone_sample: str = "",
        rate: float = 1.0,
        pitch: float = 0.0,
    ) -> dict:
        record = {
            "scope_key": scope_key,
            "mode": mode,
            "provider": provider,
            "model": model,
            "voice": voice,
            "instruction": instruction,
            "clone_sample": clone_sample,
            "rate": float(rate),
            "pitch": float(pitch),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.path is None:
            self._memory[scope_key] = record
            return dict(record)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO voice_profiles (
                    scope_key, mode, provider, model, voice, instruction, clone_sample, rate, pitch, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key) DO UPDATE SET
                    mode = excluded.mode,
                    provider = excluded.provider,
                    model = excluded.model,
                    voice = excluded.voice,
                    instruction = excluded.instruction,
                    clone_sample = excluded.clone_sample,
                    rate = excluded.rate,
                    pitch = excluded.pitch,
                    updated_at = excluded.updated_at
                """,
                (
                    record["scope_key"],
                    record["mode"],
                    record["provider"],
                    record["model"],
                    record["voice"],
                    record["instruction"],
                    record["clone_sample"],
                    record["rate"],
                    record["pitch"],
                    record["updated_at"],
                ),
            )
        return record

    def seed_from_settings(self, settings: Settings) -> None:
        """Ensure initial active profiles exist without overwriting saved user profiles."""
        rt_key = realtime_scope(settings.rt_provider, settings.rt_model)
        if self.get(rt_key) is None and settings.rt_voice:
            self.save_scope(
                scope_key=rt_key,
                mode="realtime",
                provider=settings.rt_provider,
                model=settings.rt_model,
                voice=settings.rt_voice,
                rate=settings.tts_rate,
                pitch=settings.tts_pitch,
            )
        tts_key = tts_scope(settings.tts_provider, settings.tts_model)
        if self.get(tts_key) is None and settings.tts_voice:
            self.save_scope(
                scope_key=tts_key,
                mode="pipeline",
                provider=settings.tts_provider,
                model=settings.tts_model,
                voice=settings.tts_voice,
                instruction=settings.tts_instruction,
                clone_sample=settings.tts_clone_sample,
                rate=settings.tts_rate,
                pitch=settings.tts_pitch,
            )

    def record_from_settings(self, settings: Settings, *, save_realtime: bool = True, save_tts: bool = True) -> None:
        if save_realtime:
            existing_rt = self.get(realtime_scope(settings.rt_provider, settings.rt_model))
            use_tuning = settings.voice_mode == "realtime"
            self.save_scope(
                scope_key=realtime_scope(settings.rt_provider, settings.rt_model),
                mode="realtime",
                provider=settings.rt_provider,
                model=settings.rt_model,
                voice=settings.rt_voice,
                rate=settings.tts_rate if use_tuning or existing_rt is None else existing_rt["rate"],
                pitch=settings.tts_pitch if use_tuning or existing_rt is None else existing_rt["pitch"],
            )
        if save_tts:
            existing_tts = self.get(tts_scope(settings.tts_provider, settings.tts_model))
            use_tuning = settings.voice_mode == "pipeline"
            self.save_scope(
                scope_key=tts_scope(settings.tts_provider, settings.tts_model),
                mode="pipeline",
                provider=settings.tts_provider,
                model=settings.tts_model,
                voice=settings.tts_voice,
                instruction=settings.tts_instruction,
                clone_sample=settings.tts_clone_sample,
                rate=settings.tts_rate if use_tuning or existing_tts is None else existing_tts["rate"],
                pitch=settings.tts_pitch if use_tuning or existing_tts is None else existing_tts["pitch"],
            )
