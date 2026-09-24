from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import ui

log = logging.getLogger("tts.cog.sound")

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".webm", ".opus", ".aac"}


def _looks_like_audio(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("audio/"):
        return True
    return Path(attachment.filename).suffix.lower() in ALLOWED_EXTENSIONS


def _ffprobe_path(ffmpeg_path: str) -> str:
    p = Path(ffmpeg_path)
    name = "ffprobe.exe" if p.suffix.lower() == ".exe" else "ffprobe"
    if p.parent != Path("."):
        candidate = p.parent / name
        if candidate.is_file():
            return str(candidate)
    return name


async def _probe_duration(path: str, ffmpeg_path: str) -> Optional[float]:
    ffprobe = _ffprobe_path(ffmpeg_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return float(out.decode().strip())
    except Exception:
        log.warning("音声ファイルの長さを取得できませんでした: %s", path, exc_info=True)
        return None


class SoundCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    sound_group = app_commands.Group(
        name="sound", description="音声ファイルの再生", guild_only=True
    )

    @sound_group.command(name="play", description="音声ファイルをボイスチャンネルで再生します")
    @app_commands.describe(
        file="再生する音声ファイル（mp3 / wav / ogg など）",
        loop="ONにすると、停止するまで繰り返し再生します（既定: OFF）",
        volume="再生音量（%、既定: 100）",
    )
    async def play(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        loop: bool = False,
        volume: app_commands.Range[int, 10, 200] = 100,
    ):
        if not self.bot.audio.is_connected(interaction.guild_id):
            await interaction.response.send_message(
                view=ui.warning("接続していません", "先に `/join` でボイスチャンネルに接続してください。"),
                ephemeral=True,
            )
            return

        if not _looks_like_audio(file):
            await interaction.response.send_message(
                view=ui.warning(
                    "音声ファイルではないようです",
                    "対応形式の例: mp3 / wav / ogg / m4a / flac / opus",
                ),
                ephemeral=True,
            )
            return

        if file.size > config.SOUND_MAX_FILE_SIZE:
            mb = config.SOUND_MAX_FILE_SIZE / (1024 * 1024)
            await interaction.response.send_message(
                view=ui.warning("ファイルが大きすぎます", f"{mb:.0f}MBまでのファイルに対応しています。"),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        suffix = Path(file.filename).suffix or ".dat"
        path = self.bot.audio.make_temp_path(interaction.guild_id, suffix)
        try:
            await file.save(path)
        except discord.HTTPException:
            log.exception("音声ファイルのダウンロードに失敗しました")
            await interaction.followup.send(
                view=ui.error("ダウンロードに失敗しました", "もう一度お試しください。"), ephemeral=True
            )
            return

        duration = await _probe_duration(path, self.bot.audio.ffmpeg_path)
        if duration is None:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            await interaction.followup.send(
                view=ui.error(
                    "音声ファイルを読み込めませんでした",
                    "壊れているか、対応していない形式の可能性があります。",
                ),
                ephemeral=True,
            )
            return

        if duration > config.SOUND_MAX_DURATION:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)
            minutes = config.SOUND_MAX_DURATION / 60
            await interaction.followup.send(
                view=ui.warning("再生時間が長すぎます", f"{minutes:.0f}分までの音声に対応しています。"),
                ephemeral=True,
            )
            return

        await self.bot.audio.play_sound(
            interaction.guild_id,
            path,
            volume=volume / 100,
            loop=loop,
            tmp_path=path,
            name=file.filename,
        )

        await interaction.followup.send(
            view=ui.success(
                "再生を開始しました",
                ui.field_lines(
                    [
                        ("ファイル", file.filename),
                        ("音量", f"{volume}%"),
                        ("ループ再生", "ON" if loop else "OFF"),
                    ]
                ),
                footer="読み上げが入ると、この音量は自動的に少し下がります。",
            ),
            ephemeral=True,
        )

    @sound_group.command(name="stop", description="再生中の音声ファイルを停止します")
    async def stop(self, interaction: discord.Interaction):
        stopped = self.bot.audio.stop_sound(interaction.guild_id)
        if stopped:
            await interaction.response.send_message(
                view=ui.notice("再生を停止しました", emoji="⏹️"), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                view=ui.warning("再生中の音声ファイルはありません"), ephemeral=True
            )

    @sound_group.command(name="volume", description="再生中の音声ファイルの音量を変更します")
    @app_commands.describe(level="音量（%）")
    async def volume(self, interaction: discord.Interaction, level: app_commands.Range[int, 0, 200]):
        changed = self.bot.audio.set_sound_volume(interaction.guild_id, level / 100)
        if changed:
            await interaction.response.send_message(
                view=ui.success("音量を変更しました", f"再生中の音声ファイルの音量を **{level}%** にしました。"),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                view=ui.warning("再生中の音声ファイルはありません"), ephemeral=True
            )

    @sound_group.command(name="status", description="音声ファイルの再生状況を表示します")
    async def status(self, interaction: discord.Interaction):
        info = self.bot.audio.current_sound(interaction.guild_id)
        if not info:
            await interaction.response.send_message(
                view=ui.notice("再生中の音声ファイルはありません", emoji="🔈"), ephemeral=True
            )
            return
        await interaction.response.send_message(
            view=ui.notice(
                "再生中の音声ファイル",
                ui.field_lines(
                    [
                        ("ファイル", info["name"] or "不明"),
                        ("音量", f"{round(info['volume'] * 100)}%"),
                        ("ループ再生", "ON" if info["loop"] else "OFF"),
                    ]
                ),
                emoji="🔊",
                footer="読み上げが入ると自動的に少し下がります（ダッキング）。",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SoundCog(bot))
