from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import ui
from core.text_processor import clean_text, split_text

log = logging.getLogger("tts.cog.tts")

SKIP_KEYWORDS = {"s", "ｓ"}
STOP_QUEUE_KEYWORDS = {"sall", "ｓａｌｌ"}

ACCENT_COLOUR = discord.Colour.from_rgb(108, 92, 231)


class JoinNoticeView(discord.ui.LayoutView):
    def __init__(
        self,
        voice_channel: discord.abc.GuildChannel,
        text_channel: discord.abc.GuildChannel,
        *,
        auto: bool = False,
    ):
        super().__init__(timeout=None)
        container = discord.ui.Container(accent_colour=ACCENT_COLOUR)

        heading = "## 🔊 自動で接続しました" if auto else "## 🔊 接続しました"
        container.add_item(
            discord.ui.TextDisplay(
                f"{heading}\n"
                f"**{voice_channel.name}** に参加しました。\n"
                f"これ以降 {text_channel.mention} のメッセージを読み上げます。"
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "**使い方**\n"
                "`/voice` — 読み上げの声を選ぶ（設定はユーザーごとに保存されます）\n"
                "`s` — 読み上げ中のメッセージをスキップ（`/skip` と同じ）\n"
                "`sall` — 読み上げ待ちのメッセージをすべて破棄（`/stopqueue` と同じ）\n"
                "`/dictionary add` — 読み間違える単語の読み方を登録\n"
                "`/leave` — 切断"
            )
        )
        if config.SUPPORT_URL:
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.TextDisplay("-# 使い方の質問・不具合の報告・要望はサポートへどうぞ。")
            )
            container.add_item(
                discord.ui.ActionRow(
                    discord.ui.Button(
                        style=discord.ButtonStyle.link,
                        label="サポート",
                        url=config.SUPPORT_URL,
                        emoji="🛟",
                    )
                )
            )

        self.add_item(container)


class TTSCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._speech_locks: dict[int, asyncio.Lock] = {}
        self._auto_join_locks: dict[int, asyncio.Lock] = {}

    async def speak(
        self,
        guild_id: int,
        text: str,
        *,
        speaker_id: int,
        speed: float = 1.0,
        pitch: float = 0.0,
        intonation: float = 1.0,
        volume: float = 1.0,
        prelude: Optional[str] = None,
        interrupt: bool = False,
        priority: bool = False,
    ) -> None:
        chunks = split_text(text, config.TTS_CHUNK_LENGTH)
        if not chunks:
            return

        lock = self._speech_locks.setdefault(guild_id, asyncio.Lock())
        async with lock:
            if not self.bot.audio.is_connected(guild_id):
                return
            if interrupt:
                self.bot.audio.stop_queue(guild_id)

            group_id = self.bot.audio.new_group(guild_id)
            self.bot.audio.set_active_group(guild_id, group_id)
            try:
                if prelude:
                    await self.bot.audio.enqueue_file(guild_id, prelude, group_id)

                for chunk in chunks:
                    if not self.bot.audio.is_connected(guild_id):
                        return
                    # 合成中にスキップされたチャンクはミキサーがまだ知らないので、ここで捨てる
                    if self.bot.audio.was_skipped(guild_id, group_id):
                        break
                    try:
                        wav = await self.bot.voicevox.build_speech(
                            chunk,
                            speaker_id,
                            speed=speed,
                            pitch=pitch,
                            intonation=intonation,
                            volume=volume,
                        )
                    except Exception:
                        log.exception("音声合成に失敗しました（該当チャンクを読み飛ばします）: %r", chunk[:30])
                        continue
                    if self.bot.audio.was_skipped(guild_id, group_id):
                        break
                    await self.bot.audio.enqueue(guild_id, wav, group_id, priority=priority)
            finally:
                self.bot.audio.clear_active_group(guild_id, group_id)

    @app_commands.guild_only()
    @app_commands.command(name="join", description="ボイスチャンネルに接続し、このテキストチャンネルの読み上げを開始します")
    @app_commands.describe(channel="接続するボイスチャンネル（省略時はあなたが参加しているチャンネル）")
    async def join(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.VoiceChannel] = None,
    ):
        if channel is None:
            member = interaction.user
            if isinstance(member, discord.Member) and member.voice and member.voice.channel:
                channel = member.voice.channel
            else:
                await interaction.response.send_message(
                    view=ui.warning(
                        "接続先が分かりません",
                        "先にボイスチャンネルに参加するか、`channel` オプションで指定してください。",
                    ),
                    ephemeral=True,
                )
                return

        await interaction.response.defer(thinking=True)
        try:
            await self.bot.audio.connect(channel)
        except Exception:
            log.exception("ボイスチャンネルへの接続に失敗しました")
            await interaction.followup.send(
                view=ui.error(
                    "接続に失敗しました",
                    "BOTに「接続」と「発言」の権限があるか確認してください。",
                )
            )
            return

        await self.bot.db.set_guild_settings(interaction.guild_id, text_channel_id=interaction.channel_id)
        await interaction.followup.send(view=JoinNoticeView(channel, interaction.channel))

    @app_commands.guild_only()
    @app_commands.command(name="leave", description="ボイスチャンネルから切断します")
    async def leave(self, interaction: discord.Interaction):
        if not self.bot.audio.is_connected(interaction.guild_id):
            await interaction.response.send_message(
                view=ui.warning("接続していません", "`/join` でボイスチャンネルに接続できます。"), ephemeral=True
            )
            return
        await self.bot.audio.disconnect(interaction.guild_id)
        await interaction.response.send_message(view=ui.notice("切断しました", emoji="👋"), ephemeral=False)

    @app_commands.guild_only()
    @app_commands.command(name="skip", description="現在読み上げ中のメッセージをスキップします")
    async def skip(self, interaction: discord.Interaction):
        self.bot.audio.skip(interaction.guild_id)
        await interaction.response.send_message(
            view=ui.notice("スキップしました", emoji="⏭️"), ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.command(name="stopqueue", description="読み上げ待ちのメッセージをすべて破棄します")
    async def stopqueue(self, interaction: discord.Interaction):
        self.bot.audio.stop_queue(interaction.guild_id)
        await interaction.response.send_message(
            view=ui.notice("読み上げキューをクリアしました", emoji="🗑️"), ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.command(name="read_here", description="このチャンネルを読み上げ対象チャンネルに設定します")
    async def read_here(self, interaction: discord.Interaction):
        await self.bot.db.set_guild_settings(interaction.guild_id, text_channel_id=interaction.channel_id)
        await interaction.response.send_message(
            view=ui.success(
                "読み上げ対象を変更しました",
                f"これ以降 {interaction.channel.mention} のメッセージを読み上げます。",
            ),
            ephemeral=False,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not self.bot.audio.is_connected(message.guild.id):
            return

        settings = await self.bot.db.get_guild_settings(message.guild.id)
        if settings["text_channel_id"] != message.channel.id:
            return

        stripped_content = message.content.strip().lower()
        if stripped_content in STOP_QUEUE_KEYWORDS:
            self.bot.audio.stop_queue(message.guild.id)
            with contextlib.suppress(discord.HTTPException):
                await message.add_reaction("🗑️")
            return
        if stripped_content in SKIP_KEYWORDS:
            self.bot.audio.skip(message.guild.id)
            with contextlib.suppress(discord.HTTPException):
                await message.add_reaction("⏭️")
            return

        content = message.content
        if message.attachments:
            content = f"{content} 添付ファイル".strip()
        if not content.strip():
            return

        dictionary = await self.bot.db.get_dictionary(message.guild.id)
        text = clean_text(content, message.guild, dictionary, settings["max_length"])
        if not text:
            return

        voice = await self.bot.db.get_user_voice(message.author.id)

        speaker_id = voice["speaker_id"]
        try:
            speakers = await self.bot.voicevox.get_speakers()
        except Exception:
            speakers = []
        if speakers and self.bot.voicevox.find_speaker_and_style(speakers, speaker_id)[1] is None:
            speaker_id = config.DEFAULT_SPEAKER_ID

        if settings["read_display_name"]:
            text = f"{message.author.display_name}、{text}"

        await self.speak(
            message.guild.id,
            text,
            speaker_id=speaker_id,
            speed=voice["speed"],
            pitch=voice["pitch"],
            intonation=voice["intonation"],
            volume=voice["volume"],
        )

    async def _try_auto_join(self, guild: discord.Guild, channel: discord.VoiceChannel) -> bool:
        lock = self._auto_join_locks.setdefault(guild.id, asyncio.Lock())
        if lock.locked():
            return False

        async with lock:
            if self.bot.audio.is_connected(guild.id):
                return False
            try:
                await self.bot.audio.connect(channel)
            except Exception:
                log.warning("自動接続に失敗しました: %s / %s", guild.name, channel.name, exc_info=True)
                return False

            await self.bot.db.set_guild_settings(guild.id, text_channel_id=channel.id)

        log.info("自動接続し、読み上げ対象を %s のチャットにしました: %s", channel.name, guild.name)

        try:
            await channel.send(view=JoinNoticeView(channel, channel, auto=True))
        except discord.HTTPException:
            log.warning("自動接続の案内を送信できませんでした: %s / %s", guild.name, channel.name)
        return True

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        guild = member.guild
        settings = await self.bot.db.get_guild_settings(guild.id)
        channel = self.bot.audio.get_voice_channel(guild.id)

        if channel is None:
            if not settings["auto_join"]:
                return
            if after.channel is None or after.channel == before.channel:
                return
            if not await self._try_auto_join(guild, after.channel):
                return
            channel = after.channel
            settings = await self.bot.db.get_guild_settings(guild.id)

        joined = after.channel == channel and before.channel != channel
        left = before.channel == channel and after.channel != channel
        if not (joined or left):
            return

        if settings["notify_join_leave"]:
            text = f"{member.display_name}さんが{'参加しました' if joined else '退出しました'}"
            await self.speak(guild.id, text, speaker_id=config.DEFAULT_SPEAKER_ID)

        if settings["auto_leave_when_alone"] and left:
            non_bot_members = [m for m in channel.members if not m.bot]
            if len(non_bot_members) == 0:
                await self.bot.audio.disconnect(guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(TTSCog(bot))
