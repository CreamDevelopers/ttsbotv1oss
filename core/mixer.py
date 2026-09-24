from __future__ import annotations

import contextlib
import itertools
import logging
import os
import queue
import threading
from typing import Optional

import discord

# Python 3.13 以降は audioop-lts が同じ名前で入る
import audioop

log = logging.getLogger("tts.mixer")

FRAME_BYTES = discord.opus.Encoder.FRAME_SIZE
SAMPLE_WIDTH = 2

DEFAULT_DUCK_VOLUME = 0.4

DUCK_RAMP_FRAMES = 10


class _FileCleanupSource(discord.FFmpegPCMAudio):
    def __init__(self, path: str, *, tmp_path: Optional[str] = None, **kwargs):
        super().__init__(path, **kwargs)
        self._tmp_path = tmp_path

    def cleanup(self) -> None:
        super().cleanup()
        if self._tmp_path:
            with contextlib.suppress(FileNotFoundError, PermissionError):
                os.remove(self._tmp_path)
            self._tmp_path = None


def make_source(
    path: str,
    ffmpeg_path: str,
    *,
    tmp_path: Optional[str] = None,
    loop: bool = False,
) -> discord.AudioSource:
    before_options = "-stream_loop -1" if loop else None
    return _FileCleanupSource(
        path, executable=ffmpeg_path, tmp_path=tmp_path, before_options=before_options
    )


# read() は discord.py の再生スレッドから 20ms ごとに呼ばれるので、共有状態は _lock で守る
class GuildMixer(discord.AudioSource):
    def __init__(self, duck_volume: float = DEFAULT_DUCK_VOLUME):
        self._lock = threading.Lock()
        self.duck_volume = duck_volume

        self._background: Optional[discord.AudioSource] = None
        self._background_volume: float = 1.0

        self._speech_queue: "queue.PriorityQueue[tuple[int, int, int, discord.AudioSource]]" = (
            queue.PriorityQueue()
        )
        self._seq_counter = itertools.count()
        self._current_speech: Optional[discord.AudioSource] = None
        self._current_group: Optional[int] = None
        self._interrupt_current = False

        self._duck_factor = 1.0

    def set_background(self, source: Optional[discord.AudioSource], *, volume: float = 1.0) -> None:
        with self._lock:
            old, self._background, self._background_volume = self._background, source, volume
        if old is not None and old is not source:
            old.cleanup()

    def set_background_volume(self, volume: float) -> None:
        with self._lock:
            self._background_volume = volume

    def has_background(self) -> bool:
        with self._lock:
            return self._background is not None

    def push_speech(self, group_id: int, source: discord.AudioSource, *, priority: int = 1) -> None:
        self._speech_queue.put((priority, next(self._seq_counter), group_id, source))

    def skip_current_speech(self) -> Optional[int]:
        with self._lock:
            group = self._current_group
            self._interrupt_current = True

        if group is None:
            return None

        pending: list[tuple[int, int, int, discord.AudioSource]] = []
        while True:
            try:
                item = self._speech_queue.get_nowait()
            except queue.Empty:
                break
            if item[2] == group:
                item[3].cleanup()
            else:
                pending.append(item)
        for item in pending:
            self._speech_queue.put(item)
        return group

    def clear_speech(self) -> Optional[int]:
        with self._lock:
            group = self._current_group
            self._interrupt_current = True
        while True:
            try:
                item = self._speech_queue.get_nowait()
            except queue.Empty:
                break
            item[3].cleanup()
        return group

    def is_idle(self) -> bool:
        with self._lock:
            has_background = self._background is not None
            has_current = self._current_speech is not None
        return not has_background and not has_current and self._speech_queue.empty()

    def speech_queue_size(self) -> int:
        return self._speech_queue.qsize()

    def read(self) -> bytes:
        with self._lock:
            background = self._background
            bg_volume = self._background_volume
            interrupt = self._interrupt_current
            self._interrupt_current = False
            current = self._current_speech
            interrupted_group = self._current_group if interrupt else None

        if interrupt and current is not None:
            current.cleanup()
            with self._lock:
                if self._current_speech is current:
                    self._current_speech = None
                    self._current_group = None
            current = None

        bg_frame: Optional[bytes] = None
        if background is not None:
            bg_frame = background.read()
            if not bg_frame:
                background.cleanup()
                with self._lock:
                    if self._background is background:
                        self._background = None
                bg_frame = None

        if current is None:
            while True:
                try:
                    _, _, group_id, source = self._speech_queue.get_nowait()
                except queue.Empty:
                    break
                if interrupted_group is not None and group_id == interrupted_group:
                    source.cleanup()
                    continue
                with self._lock:
                    self._current_speech = source
                    self._current_group = group_id
                current = source
                break

        speech_frame: Optional[bytes] = None
        if current is not None:
            speech_frame = current.read()
            if not speech_frame:
                current.cleanup()
                with self._lock:
                    if self._current_speech is current:
                        self._current_speech = None
                        self._current_group = None
                speech_frame = None

        if bg_frame is None and speech_frame is None:
            return b""

        if bg_frame is not None:
            target = self.duck_volume if speech_frame is not None else 1.0
            step = 1.0 / DUCK_RAMP_FRAMES
            if self._duck_factor < target:
                self._duck_factor = min(target, self._duck_factor + step)
            elif self._duck_factor > target:
                self._duck_factor = max(target, self._duck_factor - step)

            volume = bg_volume * self._duck_factor
            if volume != 1.0:
                bg_frame = audioop.mul(bg_frame, SAMPLE_WIDTH, volume)

        if bg_frame is not None and speech_frame is not None:
            return audioop.add(bg_frame, speech_frame, SAMPLE_WIDTH)
        return bg_frame if bg_frame is not None else speech_frame

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        with self._lock:
            bg, self._background = self._background, None
            current, self._current_speech = self._current_speech, None
            self._current_group = None
        if bg is not None:
            bg.cleanup()
        if current is not None:
            current.cleanup()
        while True:
            try:
                item = self._speech_queue.get_nowait()
            except queue.Empty:
                break
            item[3].cleanup()
