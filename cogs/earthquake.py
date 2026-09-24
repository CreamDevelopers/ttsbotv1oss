from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import timeutil, ui
from core.earthquake import (
    SCALE_LABELS,
    SELECTABLE_SCALES,
    EarthquakeMonitor,
    QuakeEvent,
    sample_event,
    scale_label,
)

log = logging.getLogger("tts.cog.earthquake")

NotifyChannel = discord.TextChannel | discord.VoiceChannel

SCALE_CHOICES = [
    app_commands.Choice(name=f"震度{SCALE_LABELS[scale]}以上", value=scale)
    for scale in SELECTABLE_SCALES
]
TEST_SCALE_CHOICES = [
    app_commands.Choice(name=f"震度{SCALE_LABELS[scale]}", value=scale)
    for scale in SELECTABLE_SCALES
]


def _colour(event: QuakeEvent) -> discord.Colour:
    if event.is_cancelled:
        return discord.Colour.light_grey()
    if event.is_eew or event.max_scale >= 55:
        return discord.Colour.from_rgb(214, 48, 49)
    if event.max_scale >= 45:
        return discord.Colour.from_rgb(230, 126, 34)
    if event.max_scale >= 40:
        return discord.Colour.from_rgb(241, 196, 15)
    return discord.Colour.from_rgb(52, 152, 219)


def build_notice(event: QuakeEvent) -> discord.ui.LayoutView:
    icon = "🚨" if event.is_eew else "🌏"

    if event.is_cancelled:
        body = event.speech_text()
    else:
        fields: list[tuple[str, str]] = []
        if event.hypocenter:
            fields.append(("震源地", event.hypocenter))
        if event.max_scale > 0:
            fields.append(
                ("予想最大震度" if event.is_eew else "最大震度", f"**震度{event.scale_text}**")
            )
        if event.magnitude:
            fields.append(("規模", f"M{event.magnitude}"))
        if event.depth:
            fields.append(("震源の深さ", event.depth))
        if event.occurred_at:
            fields.append(("発生時刻", event.occurred_at))
        if event.areas:
            fields.append(("対象地域" if event.is_eew else "主な観測地点", "、".join(event.areas)))
        if event.tsunami:
            fields.append(("津波", event.tsunami))
        body = ui.field_lines(fields)

    if event.is_test:
        body = "-# テスト通知です。実際の地震ではありません。\n" + body

    footer = "緊急地震速報" if event.is_eew else "気象庁発表"
    if event.serial:
        footer += f"（第{event.serial}報）"

    view = ui.NoticeView(event.title, body, emoji=icon, footer=f"{footer}　出典: P2P地震情報")
    view.children[0].accent_colour = _colour(event)
    return view


class EarthquakeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.monitor = EarthquakeMonitor(
            config.QUAKE_WS_URL,
            config.QUAKE_API_URL,
            poll_interval=config.QUAKE_POLL_INTERVAL,
        )
        self.monitor.add_listener(self.on_quake_event)
        self.alert_sound = self._resolve_alert_sound()

    def _resolve_alert_sound(self) -> Optional[str]:
        path = Path(config.QUAKE_ALERT_SOUND)
        if path.is_file():
            return str(path)
        for suffix in (".mp3", ".wav", ".ogg"):
            candidate = path.with_suffix(suffix)
            if candidate.is_file():
                log.info("警報音として %s を使用します", candidate)
                return str(candidate)
        log.warning(
            "警報音のファイルが見つかりません: %s（読み上げのみ行います。"
            "python tools/generate_alert.py で生成できます）",
            path,
        )
        return None

    async def cog_load(self) -> None:
        if not config.QUAKE_ENABLED:
            log.info("地震速報の監視は無効化されています（QUAKE_ENABLED=false）")
            return
        await self.monitor.start()

    async def cog_unload(self) -> None:
        await self.monitor.stop()

    async def on_quake_event(self, event: QuakeEvent) -> None:
        if event.is_test:
            log.info("テスト電文を受信しました（通知はしません）: %s", event.id)
            return
        log.info(
            "地震速報を受信しました: %s / %s / 最大震度%s", event.title, event.hypocenter, event.scale_text
        )
        await self.dispatch(event)

    async def dispatch(self, event: QuakeEvent, *, only_guild_id: Optional[int] = None) -> int:
        notified = 0
        for guild in self.bot.guilds:
            if only_guild_id is not None and guild.id != only_guild_id:
                continue
            settings = await self.bot.db.get_guild_settings(guild.id)
            if only_guild_id is None and not self._should_notify(event, settings):
                continue
            try:
                await self._notify_guild(guild, event, settings)
                notified += 1
            except Exception:
                log.exception("地震速報の通知に失敗しました: %s", guild.name)
        return notified

    def _should_notify(self, event: QuakeEvent, settings: dict) -> bool:
        if not settings["quake_enabled"]:
            return False
        if event.is_eew and not settings["quake_eew"]:
            return False
        if event.is_cancelled:
            return True
        min_scale = settings["quake_min_scale"] or config.QUAKE_DEFAULT_MIN_SCALE
        if event.max_scale < 0:
            return False
        return event.max_scale >= min_scale

    def notify_channel(
        self, guild: discord.Guild, settings: dict
    ) -> Optional[NotifyChannel]:
        for key in ("quake_channel_id", "text_channel_id"):
            channel_id = settings.get(key)
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                return channel
        return None

    async def _notify_guild(self, guild: discord.Guild, event: QuakeEvent, settings: dict) -> None:
        channel = self.notify_channel(guild, settings)
        if channel is not None:
            try:
                await channel.send(view=build_notice(event))
            except discord.HTTPException:
                log.warning("地震速報の投稿に失敗しました: %s / %s", guild.name, channel.name)

        if not settings["quake_speak"]:
            return
        if not self.bot.audio.is_connected(guild.id):
            return

        tts = self.bot.get_cog("TTSCog")
        if tts is None:
            log.warning("TTSCogが読み込まれていないため、地震速報を読み上げられません")
            return

        await tts.speak(
            guild.id,
            event.speech_text(),
            speaker_id=config.DEFAULT_SPEAKER_ID,
            prelude=None if event.is_cancelled else self.alert_sound,
            interrupt=True,
        )

    quake_group = app_commands.Group(
        name="earthquake", description="地震速報の通知設定", guild_only=True
    )

    @quake_group.command(name="enable", description="地震速報の通知をON/OFFします")
    @app_commands.describe(enabled="ONにすると地震速報を通知します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, quake_enabled=int(enabled))
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        fields = [("地震速報の通知", "**ON**" if enabled else "**OFF**")]
        if enabled:
            channel = self.notify_channel(interaction.guild, settings)
            fields += [
                ("通知先", channel.mention if channel else "未設定（`/earthquake channel` で指定）"),
                ("通知する震度", f"震度{scale_label(settings['quake_min_scale'])}以上"),
            ]
        await interaction.response.send_message(
            view=ui.success("設定を変更しました", ui.field_lines(fields)), ephemeral=True
        )

    @quake_group.command(name="channel", description="地震速報を投稿するチャンネルを設定します")
    @app_commands.describe(channel="投稿先のチャンネル（ボイスチャンネルのチャット欄も選べます）")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(self, interaction: discord.Interaction, channel: NotifyChannel):
        await self.bot.db.set_guild_settings(interaction.guild_id, quake_channel_id=channel.id)
        await interaction.response.send_message(
            view=ui.success("通知チャンネルを設定しました", f"地震速報を {channel.mention} に投稿します。"),
            ephemeral=True,
        )

    @quake_group.command(name="min_scale", description="通知する最小の震度を設定します")
    @app_commands.describe(scale="この震度以上の地震だけを通知します")
    @app_commands.choices(scale=SCALE_CHOICES)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def min_scale(self, interaction: discord.Interaction, scale: app_commands.Choice[int]):
        await self.bot.db.set_guild_settings(interaction.guild_id, quake_min_scale=scale.value)
        await interaction.response.send_message(
            view=ui.success(
                "通知する震度を変更しました",
                f"**震度{scale_label(scale.value)}以上** の地震を通知します。",
            ),
            ephemeral=True,
        )

    @quake_group.command(name="eew", description="緊急地震速報（警報）を通知するかを設定します")
    @app_commands.describe(enabled="OFFにすると、発生後の地震情報だけを通知します")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def eew(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, quake_eew=int(enabled))
        await interaction.response.send_message(
            view=ui.success(
                "設定を変更しました", f"緊急地震速報の通知を **{'ON' if enabled else 'OFF'}** にしました。"
            ),
            ephemeral=True,
        )

    @quake_group.command(name="speak", description="ボイスチャンネルでの読み上げをON/OFFします")
    @app_commands.describe(enabled="OFFにすると、テキストチャンネルへの投稿だけを行います")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def speak(self, interaction: discord.Interaction, enabled: bool):
        await self.bot.db.set_guild_settings(interaction.guild_id, quake_speak=int(enabled))
        await interaction.response.send_message(
            view=ui.success(
                "設定を変更しました", f"地震速報の読み上げを **{'ON' if enabled else 'OFF'}** にしました。"
            ),
            ephemeral=True,
        )

    @quake_group.command(name="show", description="地震速報の現在の設定を表示します")
    async def show(self, interaction: discord.Interaction):
        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        channel = self.notify_channel(interaction.guild, settings)
        source = "受信中" if self.monitor.connected else "再接続中（HTTP取得で継続）"
        if not config.QUAKE_ENABLED:
            source = "BOT全体で無効"
        body = ui.field_lines(
            [
                ("通知", "ON" if settings["quake_enabled"] else "OFF"),
                ("通知チャンネル", channel.mention if channel else "未設定"),
                ("通知する震度", f"震度{scale_label(settings['quake_min_scale'])}以上"),
                ("緊急地震速報", "ON" if settings["quake_eew"] else "OFF"),
                ("VCでの読み上げ", "ON" if settings["quake_speak"] else "OFF"),
                ("警報音", "あり" if self.alert_sound else "なし（ファイル未配置）"),
                ("配信元の状態", source),
                ("最後に受信した速報", timeutil.format_datetime(self.monitor.last_event_at)),
            ]
        )
        await interaction.response.send_message(
            view=ui.notice("地震速報の設定", body, emoji="🌏", footer="時刻はすべて日本時間です。"),
            ephemeral=True,
        )

    @quake_group.command(name="test", description="サンプルの地震速報を流して、通知と読み上げを確認します")
    @app_commands.describe(
        scale="テストに使う震度（既定: 震度5強）",
        kind="テストする速報の種類（既定: 地震情報）",
    )
    @app_commands.choices(
        scale=TEST_SCALE_CHOICES,
        kind=[
            app_commands.Choice(name="地震情報（発生後）", value="info"),
            app_commands.Choice(name="緊急地震速報（警報）", value="eew"),
        ],
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(
        self,
        interaction: discord.Interaction,
        scale: Optional[app_commands.Choice[int]] = None,
        kind: Optional[app_commands.Choice[str]] = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        scale_value = scale.value if scale else 50
        kind_value = kind.value if kind else "info"
        event = sample_event(scale_value, kind=kind_value)

        await self.dispatch(event, only_guild_id=interaction.guild_id)

        settings = await self.bot.db.get_guild_settings(interaction.guild_id)
        notes: list[str] = []
        if not settings["quake_enabled"]:
            notes.append("⚠️ 通知はOFFのままです（`/earthquake enable enabled:True` で有効化）")
        elif not self._should_notify(event, settings):
            notes.append(
                f"⚠️ 実際の地震では、この内容は通知されません"
                f"（設定は震度{scale_label(settings['quake_min_scale'])}以上）"
            )
        if self.notify_channel(interaction.guild, settings) is None:
            notes.append("⚠️ 通知チャンネルが未設定です（`/earthquake channel` で指定）")
        if not settings["quake_speak"]:
            notes.append("ℹ️ VCでの読み上げはOFFです（`/earthquake speak enabled:True` で有効化）")
        elif not self.bot.audio.is_connected(interaction.guild_id):
            notes.append("ℹ️ VCに接続していないため、読み上げは行われていません（`/join` で接続）")
        if not self.alert_sound:
            notes.append("⚠️ 警報音のファイルがありません（`python tools/generate_alert.py` で生成）")

        await interaction.followup.send(
            view=ui.notice(
                "テストの地震速報を流しました",
                "\n".join(notes) if notes else "実際の通知と同じ経路で送信しました。",
                emoji="🧪",
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EarthquakeCog(bot))
