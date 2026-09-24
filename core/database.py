from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

import aiosqlite

log = logging.getLogger("tts.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_voice (
    user_id INTEGER PRIMARY KEY,
    speaker_id INTEGER NOT NULL,
    speed REAL NOT NULL DEFAULT 1.0,
    pitch REAL NOT NULL DEFAULT 0.0,
    intonation REAL NOT NULL DEFAULT 1.0,
    volume REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER PRIMARY KEY,
    text_channel_id INTEGER,
    read_display_name INTEGER NOT NULL DEFAULT 1,
    max_length INTEGER NOT NULL DEFAULT 200,
    notify_join_leave INTEGER NOT NULL DEFAULT 1,
    auto_leave_when_alone INTEGER NOT NULL DEFAULT 1,
    auto_join INTEGER NOT NULL DEFAULT 0,
    quake_enabled INTEGER NOT NULL DEFAULT 0,
    quake_channel_id INTEGER,
    quake_min_scale INTEGER NOT NULL DEFAULT 40,
    quake_eew INTEGER NOT NULL DEFAULT 1,
    quake_speak INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS dictionary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    reading TEXT NOT NULL,
    UNIQUE(guild_id, word)
);
"""


MIGRATIONS: dict[str, dict[str, str]] = {}


class Database:
    def __init__(self, path: str, *, default_speaker_id: int = 3, default_max_length: int = 200):
        self.path = path
        self.default_speaker_id = default_speaker_id
        self.default_max_length = default_max_length
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()
        await self._migrate()

    async def _migrate(self) -> None:
        changed = False
        for table, columns in MIGRATIONS.items():
            cur = await self._conn.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in await cur.fetchall()}
            for name, ddl in columns.items():
                if name in existing:
                    continue
                await self._conn.execute(ddl)
                log.info("データベースに %s.%s を追加しました", table, name)
                changed = True
        if changed:
            await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def get_user_voice(self, user_id: int) -> dict[str, Any]:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT * FROM user_voice WHERE user_id = ?", (user_id,)
            )
            row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "user_id": user_id,
            "speaker_id": self.default_speaker_id,
            "speed": 1.0,
            "pitch": 0.0,
            "intonation": 1.0,
            "volume": 1.0,
        }

    async def set_user_voice(self, user_id: int, **fields: Any) -> None:
        current = await self.get_user_voice(user_id)
        current.update(fields)
        async with self._lock:
            await self._conn.execute(
                """
                INSERT INTO user_voice (user_id, speaker_id, speed, pitch, intonation, volume)
                VALUES (:user_id, :speaker_id, :speed, :pitch, :intonation, :volume)
                ON CONFLICT(user_id) DO UPDATE SET
                    speaker_id=excluded.speaker_id,
                    speed=excluded.speed,
                    pitch=excluded.pitch,
                    intonation=excluded.intonation,
                    volume=excluded.volume
                """,
                current,
            )
            await self._conn.commit()

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any]:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
            )
            row = await cur.fetchone()
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "text_channel_id": None,
            "read_display_name": 1,
            "max_length": self.default_max_length,
            "notify_join_leave": 1,
            "auto_leave_when_alone": 1,
            "auto_join": 0,
            "quake_enabled": 0,
            "quake_channel_id": None,
            "quake_min_scale": 40,
            "quake_eew": 1,
            "quake_speak": 1,
        }

    async def set_guild_settings(self, guild_id: int, **fields: Any) -> None:
        current = await self.get_guild_settings(guild_id)
        current.update(fields)
        async with self._lock:
            await self._conn.execute(
                """
                INSERT INTO guild_settings
                    (guild_id, text_channel_id, read_display_name, max_length,
                     notify_join_leave, auto_leave_when_alone, auto_join,
                     quake_enabled, quake_channel_id, quake_min_scale, quake_eew, quake_speak)
                VALUES
                    (:guild_id, :text_channel_id, :read_display_name, :max_length,
                     :notify_join_leave, :auto_leave_when_alone, :auto_join,
                     :quake_enabled, :quake_channel_id, :quake_min_scale, :quake_eew, :quake_speak)
                ON CONFLICT(guild_id) DO UPDATE SET
                    text_channel_id=excluded.text_channel_id,
                    read_display_name=excluded.read_display_name,
                    max_length=excluded.max_length,
                    notify_join_leave=excluded.notify_join_leave,
                    auto_leave_when_alone=excluded.auto_leave_when_alone,
                    auto_join=excluded.auto_join,
                    quake_enabled=excluded.quake_enabled,
                    quake_channel_id=excluded.quake_channel_id,
                    quake_min_scale=excluded.quake_min_scale,
                    quake_eew=excluded.quake_eew,
                    quake_speak=excluded.quake_speak
                """,
                current,
            )
            await self._conn.commit()

    async def add_dictionary_entry(self, guild_id: int, word: str, reading: str) -> None:
        async with self._lock:
            await self._conn.execute(
                """
                INSERT INTO dictionary (guild_id, word, reading) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, word) DO UPDATE SET reading=excluded.reading
                """,
                (guild_id, word, reading),
            )
            await self._conn.commit()

    async def remove_dictionary_entry(self, guild_id: int, word: str) -> bool:
        async with self._lock:
            cur = await self._conn.execute(
                "DELETE FROM dictionary WHERE guild_id = ? AND word = ?", (guild_id, word)
            )
            await self._conn.commit()
            return cur.rowcount > 0

    async def get_dictionary(self, guild_id: int) -> list[tuple[str, str]]:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT word, reading FROM dictionary WHERE guild_id = ? ORDER BY LENGTH(word) DESC",
                (guild_id,),
            )
            rows = await cur.fetchall()
        return [(r["word"], r["reading"]) for r in rows]
