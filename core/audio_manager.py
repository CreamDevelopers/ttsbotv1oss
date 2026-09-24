from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
import time
from typing import Optional

import discord

from core.mixer import DEFAULT_DUCK_VOLUME, GuildMixer, make_source

log = logging.getLogger("tts.audio")


class GuildAudioState:
    def __init__(self, guild_id: int, duck_volume: float = DEFAULT_DUCK_VOLUME):
        self.guild_id = guild_id
        self.voice_client: Optional[discord.VoiceClient] = None
        self.last_group = 0
        self.mixer = GuildMixer(duck_volume=duck_volume)
        self.sound_name: Optional[str] = None
        self.sound_volume: float = 1.0
        self.sound_loop: bool = False


class AudioManager:
    def __init__(self, ffmpeg_path: str = "ffmpeg", duck_volume: float = DEFAULT_DUCK_VOLUME):
        self.ffmpeg_path = ffmpeg_path
        self.duck_volume = duck_volume
        self._states: dict[int, GuildAudioState] = {}
        self._tmp_dir = tempfile.mkdtemp(prefix="tts_bot_")
        self._skipped_groups: dict[int, set[int]] = {}
        self._active_groups: dict[int, int] = {}

    def _get_state(self, guild_id: int) -> GuildAudioState:
        if guild_id not in self._states:
            self._states[guild_id] = GuildAudioState(guild_id, duck_volume=self.duck_volume)
        return self._states[guild_id]

    def make_temp_path(self, guild_id: int, suffix: str = ".wav") -> str:
        return os.path.join(self._tmp_dir, f"{guild_id}_{time.monotonic_ns()}{suffix}")

    def is_connected(self, guild_id: int) -> bool:
        state = self._states.get(guild_id)
        return bool(state and state.voice_client and state.voice_client.is_connected())

    def get_voice_channel(self, guild_id: int) -> Optional[discord.VoiceChannel]:
        state = self._states.get(guild_id)
        if state and state.voice_client and state.voice_client.is_connected():
            return state.voice_client.channel
        return None

    def queue_size(self, guild_id: int) -> int:
        state = self._states.get(guild_id)
        return state.mixer.speech_queue_size() if state else 0

    async def connect(self, channel: discord.VoiceChannel) -> discord.VoiceClient:
        state = self._get_state(channel.guild.id)
        if state.voice_client and state.voice_client.is_connected():
            await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect()
        return state.voice_client

    async def restore_connections(self, bot) -> int:
        restored = 0
        for guild in bot.guilds:
            me = guild.me
            if me is None or me.voice is None or me.voice.channel is None:
                continue
            if self.is_connected(guild.id):
                continue

            channel = me.voice.channel
            try:
                # Discord 側に古いボイスセッションが残っていると接続に失敗するので一度抜ける
                await guild.change_voice_state(channel=None)
                await asyncio.sleep(1)
                await self.connect(channel)
                restored += 1
                log.info("ボイスチャンネルへの接続を復帰しました: %s / %s", guild.name, channel.name)
            except Exception:
                log.warning(
                    "ボイスチャンネルへの復帰に失敗しました: %s / %s", guild.name, channel.name, exc_info=True
                )
        return restored

    async def disconnect(self, guild_id: int) -> None:
        state = self._states.get(guild_id)
        if not state:
            return
        if state.voice_client:
            with contextlib.suppress(Exception):
                await state.voice_client.disconnect(force=True)
            state.voice_client = None
        state.mixer.cleanup()
        state.sound_name = None
        self._skipped_groups.pop(guild_id, None)
        self._active_groups.pop(guild_id, None)

    def new_group(self, guild_id: int) -> int:
        state = self._get_state(guild_id)
        state.last_group += 1
        return state.last_group

    async def enqueue(
        self,
        guild_id: int,
        wav_bytes: bytes,
        group_id: Optional[int] = None,
        *,
        priority: bool = False,
    ) -> None:
        state = self._get_state(guild_id)
        if group_id is None:
            group_id = self.new_group(guild_id)
        path = self.make_temp_path(guild_id, ".wav")
        with open(path, "wb") as f:
            f.write(wav_bytes)
        source = make_source(path, self.ffmpeg_path, tmp_path=path)
        state.mixer.push_speech(group_id, source, priority=(0 if priority else 1))
        await self._ensure_playing(guild_id)

    async def enqueue_file(self, guild_id: int, path: str, group_id: Optional[int] = None) -> None:
        state = self._get_state(guild_id)
        if group_id is None:
            group_id = self.new_group(guild_id)
        source = make_source(str(path), self.ffmpeg_path)
        state.mixer.push_speech(group_id, source)
        await self._ensure_playing(guild_id)

    def skip(self, guild_id: int) -> None:
        state = self._states.get(guild_id)
        if not state:
            return
        group = state.mixer.skip_current_speech()
        if group is not None:
            self._skipped_groups.setdefault(guild_id, set()).add(group)

    def stop_queue(self, guild_id: int) -> None:
        state = self._states.get(guild_id)
        if not state:
            return
        skipped = self._skipped_groups.setdefault(guild_id, set())
        group = state.mixer.clear_speech()
        if group is not None:
            skipped.add(group)
        active = self._active_groups.get(guild_id)
        if active is not None:
            skipped.add(active)

    def set_active_group(self, guild_id: int, group_id: int) -> None:
        self._active_groups[guild_id] = group_id

    def clear_active_group(self, guild_id: int, group_id: int) -> None:
        if self._active_groups.get(guild_id) == group_id:
            del self._active_groups[guild_id]
        groups = self._skipped_groups.get(guild_id)
        if groups:
            groups.discard(group_id)

    def was_skipped(self, guild_id: int, group_id: int) -> bool:
        groups = self._skipped_groups.get(guild_id)
        return bool(groups and group_id in groups)

    async def play_sound(
        self,
        guild_id: int,
        path: str,
        *,
        volume: float = 1.0,
        loop: bool = False,
        tmp_path: Optional[str] = None,
        name: Optional[str] = None,
    ) -> None:
        state = self._get_state(guild_id)
        source = make_source(path, self.ffmpeg_path, tmp_path=tmp_path, loop=loop)
        state.mixer.set_background(source, volume=volume)
        state.sound_name = name
        state.sound_volume = volume
        state.sound_loop = loop
        await self._ensure_playing(guild_id)

    def stop_sound(self, guild_id: int) -> bool:
        state = self._states.get(guild_id)
        if not state or not state.mixer.has_background():
            return False
        state.mixer.set_background(None)
        state.sound_name = None
        return True

    def set_sound_volume(self, guild_id: int, volume: float) -> bool:
        state = self._states.get(guild_id)
        if not state or not state.mixer.has_background():
            return False
        state.mixer.set_background_volume(volume)
        state.sound_volume = volume
        return True

    def current_sound(self, guild_id: int) -> Optional[dict]:
        state = self._states.get(guild_id)
        if not state or not state.mixer.has_background():
            if state:
                state.sound_name = None
            return None
        return {"name": state.sound_name, "volume": state.sound_volume, "loop": state.sound_loop}

    async def _ensure_playing(self, guild_id: int) -> None:
        state = self._states.get(guild_id)
        if not state or not state.voice_client or not state.voice_client.is_connected():
            return
        vc = state.voice_client
        if vc.is_playing() or vc.is_paused():
            return
        if state.mixer.is_idle():
            return

        loop = asyncio.get_running_loop()

        def _after(error: Optional[Exception]) -> None:
            if error:
                log.warning("再生中にエラーが発生しました: %s", error)
            # 停止直後に新しい音声が積まれていることがあるので再確認する
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._ensure_playing(guild_id)))

        vc.play(state.mixer, after=_after)

    async def shutdown(self) -> None:
        for guild_id in list(self._states.keys()):
            await self.disconnect(guild_id)
        with contextlib.suppress(Exception):
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
