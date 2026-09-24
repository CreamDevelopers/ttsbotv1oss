from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

log = logging.getLogger("tts.voicevox")


class VoicevoxError(Exception):
    pass


class VoicevoxClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._speakers_cache: Optional[list[dict[str, Any]]] = None
        self._speaker_info_cache: dict[str, dict[str, Any]] = {}
        self._speakers_lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def is_available(self) -> bool:
        try:
            session = await self._ensure_session()
            timeout = aiohttp.ClientTimeout(total=5)
            async with session.get(f"{self.base_url}/version", timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def get_speakers(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        async with self._speakers_lock:
            if self._speakers_cache is not None and not force_refresh:
                return self._speakers_cache
            session = await self._ensure_session()
            async with session.get(f"{self.base_url}/speakers") as resp:
                if resp.status != 200:
                    raise VoicevoxError(f"speakers取得に失敗しました (status={resp.status})")
                data = await resp.json()
            self._speakers_cache = data
            return data

    async def get_speaker_info(self, speaker_uuid: str) -> dict[str, Any]:
        if speaker_uuid in self._speaker_info_cache:
            return self._speaker_info_cache[speaker_uuid]
        session = await self._ensure_session()
        async with session.get(
            f"{self.base_url}/speaker_info", params={"speaker_uuid": speaker_uuid}
        ) as resp:
            if resp.status != 200:
                raise VoicevoxError(f"speaker_info取得に失敗しました (status={resp.status})")
            data = await resp.json()
        self._speaker_info_cache[speaker_uuid] = data
        return data

    async def audio_query(self, text: str, speaker_id: int) -> dict[str, Any]:
        session = await self._ensure_session()
        async with session.post(
            f"{self.base_url}/audio_query", params={"text": text, "speaker": speaker_id}
        ) as resp:
            if resp.status != 200:
                raise VoicevoxError(f"audio_queryに失敗しました (status={resp.status})")
            return await resp.json()

    async def synthesis(self, query: dict[str, Any], speaker_id: int) -> bytes:
        session = await self._ensure_session()
        async with session.post(
            f"{self.base_url}/synthesis", params={"speaker": speaker_id}, json=query
        ) as resp:
            if resp.status != 200:
                raise VoicevoxError(f"synthesisに失敗しました (status={resp.status})")
            return await resp.read()

    async def build_speech(
        self,
        text: str,
        speaker_id: int,
        *,
        speed: float = 1.0,
        pitch: float = 0.0,
        intonation: float = 1.0,
        volume: float = 1.0,
    ) -> bytes:
        query = await self.audio_query(text, speaker_id)
        query["speedScale"] = speed
        query["pitchScale"] = pitch
        query["intonationScale"] = intonation
        query["volumeScale"] = volume
        return await self.synthesis(query, speaker_id)

    def find_speaker_and_style(
        self, speakers: list[dict[str, Any]], speaker_id: int
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        for sp in speakers:
            for st in sp["styles"]:
                if st["id"] == speaker_id:
                    return sp, st
        return None, None
