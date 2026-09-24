from __future__ import annotations

import base64
import contextlib
import io
import logging
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core import ui

log = logging.getLogger("tts.cog.voice_settings")

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "speed": (0.5, 2.0),
    "pitch": (-0.15, 0.15),
    "intonation": (0.0, 2.0),
    "volume": (0.0, 2.0),
}
PARAM_LABELS = {
    "speed": "速度",
    "pitch": "音高",
    "intonation": "抑揚",
    "volume": "音量",
}


def ClosedView() -> discord.ui.LayoutView:
    return ui.notice("ボイス設定画面を閉じました", emoji="🔒", kind="neutral")


class VoiceSettingsView(discord.ui.LayoutView):
    PAGE_SIZE = 25

    def __init__(
        self,
        bot: commands.Bot,
        user_id: int,
        speakers: list[dict[str, Any]],
        user_voice: dict[str, Any],
    ):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id
        self.speakers = speakers
        self.character_names = sorted({sp["name"] for sp in speakers})

        self.speaker_id: int = user_voice["speaker_id"]
        self.speed: float = user_voice["speed"]
        self.pitch: float = user_voice["pitch"]
        self.intonation: float = user_voice["intonation"]
        self.volume: float = user_voice["volume"]
        self.page = 0
        self.message: Optional[discord.Message] = None

        self.selected_character_name = ""
        self.selected_style_name = ""
        self.selected_speaker_uuid = ""
        self._sync_from_speaker_id()

    def _sync_from_speaker_id(self) -> None:
        for sp in self.speakers:
            for st in sp["styles"]:
                if st["id"] == self.speaker_id:
                    self.selected_character_name = sp["name"]
                    self.selected_style_name = st["name"]
                    self.selected_speaker_uuid = sp["speaker_uuid"]
                    return
        sp = self.speakers[0]
        self.selected_character_name = sp["name"]
        self.selected_style_name = sp["styles"][0]["name"]
        self.selected_speaker_uuid = sp["speaker_uuid"]
        self.speaker_id = sp["styles"][0]["id"]

    def _current_speaker(self) -> dict[str, Any]:
        for sp in self.speakers:
            if sp["name"] == self.selected_character_name:
                return sp
        return self.speakers[0]

    def _ensure_page_contains_selection(self) -> None:
        if self.selected_character_name in self.character_names:
            idx = self.character_names.index(self.selected_character_name)
            self.page = idx // self.PAGE_SIZE

    async def build(self) -> Optional[discord.File]:
        self.clear_items()
        self._ensure_page_contains_selection()

        total_pages = max(1, (len(self.character_names) - 1) // self.PAGE_SIZE + 1)
        start = self.page * self.PAGE_SIZE
        page_names = self.character_names[start : start + self.PAGE_SIZE]

        container = discord.ui.Container(accent_colour=discord.Colour.from_rgb(83, 209, 138))

        header = (
            "## 🎙️ ボイス設定\n"
            f"**{self.selected_character_name}**（{self.selected_style_name}）\n"
            f"速度 `{self.speed:.2f}` ／ 音高 `{self.pitch:+.2f}` ／ "
            f"抑揚 `{self.intonation:.2f}` ／ 音量 `{self.volume:.2f}`"
        )
        container.add_item(discord.ui.TextDisplay(header))
        container.add_item(discord.ui.Separator())

        char_options = [
            discord.SelectOption(
                label=name[:100], value=name, default=(name == self.selected_character_name)
            )
            for name in page_names
        ]
        container.add_item(discord.ui.ActionRow(CharacterSelect(self, char_options, total_pages)))

        if total_pages > 1:
            container.add_item(
                discord.ui.ActionRow(
                    PageButton(self, -1, disabled=(self.page <= 0)),
                    PageIndicator(self.page, total_pages),
                    PageButton(self, 1, disabled=(self.page >= total_pages - 1)),
                )
            )

        current_speaker = self._current_speaker()
        styles = current_speaker["styles"]
        if len(styles) > 1:
            style_options = [
                discord.SelectOption(
                    label=st["name"][:100], value=str(st["id"]), default=(st["id"] == self.speaker_id)
                )
                for st in styles
            ]
            container.add_item(discord.ui.ActionRow(StyleSelect(self, style_options)))

        file: Optional[discord.File] = None
        try:
            info = await self.bot.voicevox.get_speaker_info(self.selected_speaker_uuid)
            style_infos = info.get("style_infos", [])
            style_info = next(
                (s for s in style_infos if s["id"] == self.speaker_id),
                style_infos[0] if style_infos else None,
            )
            if style_info and style_info.get("icon"):
                icon_bytes = base64.b64decode(style_info["icon"])
                file = discord.File(io.BytesIO(icon_bytes), filename="portrait.png")
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(f"全 {len(styles)} スタイル収録"),
                        accessory=discord.ui.Thumbnail(media=file),
                    )
                )
        except Exception:
            log.warning("キャラクター画像の取得に失敗しました", exc_info=True)

        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.ActionRow(
                ParamButton(self, "speed", -0.1, "🐢 速度-"),
                ParamButton(self, "speed", 0.1, "🐇 速度+"),
                ParamButton(self, "pitch", -0.05, "🔽 音高-"),
                ParamButton(self, "pitch", 0.05, "🔼 音高+"),
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                ParamButton(self, "intonation", -0.1, "📉 抑揚-"),
                ParamButton(self, "intonation", 0.1, "📈 抑揚+"),
                ParamButton(self, "volume", -0.1, "🔈 音量-"),
                ParamButton(self, "volume", 0.1, "🔊 音量+"),
            )
        )
        container.add_item(
            discord.ui.ActionRow(
                ResetButton(self),
                PreviewButton(self),
                SaveButton(self),
                CloseButton(self),
            )
        )

        self.add_item(container)
        return file

    async def refresh(self, interaction: discord.Interaction) -> None:
        file = await self.build()
        await interaction.response.edit_message(view=self, attachments=[file] if file else [])

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                view=ui.warning(
                    "他の人の設定画面です", "`/voice` を実行すると、自分の設定画面を開けます。"
                ),
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            with contextlib.suppress(Exception):
                await self.message.edit(view=ClosedView(), attachments=[])


class CharacterSelect(discord.ui.Select):
    def __init__(self, parent: VoiceSettingsView, options: list[discord.SelectOption], total_pages: int):
        placeholder = "キャラクターを選択" + (f"（{total_pages}ページ中）" if total_pages > 1 else "")
        super().__init__(placeholder=placeholder, options=options)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        name = self.values[0]
        self.parent_view.selected_character_name = name
        speaker = self.parent_view._current_speaker()
        self.parent_view.speaker_id = speaker["styles"][0]["id"]
        self.parent_view.selected_style_name = speaker["styles"][0]["name"]
        self.parent_view.selected_speaker_uuid = speaker["speaker_uuid"]
        await self.parent_view.refresh(interaction)


class StyleSelect(discord.ui.Select):
    def __init__(self, parent: VoiceSettingsView, options: list[discord.SelectOption]):
        super().__init__(placeholder="スタイルを選択", options=options)
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        style_id = int(self.values[0])
        self.parent_view.speaker_id = style_id
        speaker = self.parent_view._current_speaker()
        style = next(s for s in speaker["styles"] if s["id"] == style_id)
        self.parent_view.selected_style_name = style["name"]
        await self.parent_view.refresh(interaction)


class PageButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView, direction: int, disabled: bool = False):
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="◀ 前へ" if direction < 0 else "次へ ▶",
            disabled=disabled,
        )
        self.parent_view = parent
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.page += self.direction
        await self.parent_view.refresh(interaction)


class PageIndicator(discord.ui.Button):
    def __init__(self, page: int, total_pages: int):
        super().__init__(style=discord.ButtonStyle.secondary, label=f"{page + 1} / {total_pages}", disabled=True)


class ParamButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView, attr: str, delta: float, label: str):
        super().__init__(style=discord.ButtonStyle.secondary, label=label)
        self.parent_view = parent
        self.attr = attr
        self.delta = delta

    async def callback(self, interaction: discord.Interaction):
        low, high = PARAM_BOUNDS[self.attr]
        current = getattr(self.parent_view, self.attr)
        new_value = round(min(high, max(low, current + self.delta)), 2)
        setattr(self.parent_view, self.attr, new_value)
        await self.parent_view.refresh(interaction)


class ResetButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView):
        super().__init__(style=discord.ButtonStyle.secondary, label="↩️ リセット")
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.speed = 1.0
        self.parent_view.pitch = 0.0
        self.parent_view.intonation = 1.0
        self.parent_view.volume = 1.0
        await self.parent_view.refresh(interaction)


class PreviewButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView):
        super().__init__(style=discord.ButtonStyle.primary, label="▶️ 試聴")
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        if not pv.bot.audio.is_connected(interaction.guild_id):
            await interaction.response.send_message(
                view=ui.warning("接続していません", "先に `/join` でボイスチャンネルに接続してください。"),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        text = f"こんにちは、{pv.selected_character_name}です。この声で読み上げます。"
        try:
            wav = await pv.bot.voicevox.build_speech(
                text,
                pv.speaker_id,
                speed=pv.speed,
                pitch=pv.pitch,
                intonation=pv.intonation,
                volume=pv.volume,
            )
        except Exception:
            log.exception("試聴音声の生成に失敗しました")
            await interaction.followup.send(
                view=ui.error("試聴に失敗しました", "VOICEVOXエンジンの状態を確認してください。"),
                ephemeral=True,
            )
            return
        await pv.bot.audio.enqueue(interaction.guild_id, wav)
        await interaction.followup.send(
            view=ui.notice("試聴を再生しました", emoji="🔊"), ephemeral=True
        )


class SaveButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView):
        super().__init__(style=discord.ButtonStyle.success, label="💾 保存")
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        await pv.bot.db.set_user_voice(
            pv.user_id,
            speaker_id=pv.speaker_id,
            speed=pv.speed,
            pitch=pv.pitch,
            intonation=pv.intonation,
            volume=pv.volume,
        )
        await interaction.response.send_message(
            view=ui.success(
                "ボイス設定を保存しました",
                ui.field_lines(
                    [
                        ("キャラクター", f"{pv.selected_character_name}（{pv.selected_style_name}）"),
                        ("速度／音高", f"`{pv.speed:.2f}` ／ `{pv.pitch:+.2f}`"),
                        ("抑揚／音量", f"`{pv.intonation:.2f}` ／ `{pv.volume:.2f}`"),
                    ]
                ),
                footer="この設定は、参加しているすべてのサーバーで使われます。",
            ),
            ephemeral=True,
        )


class CloseButton(discord.ui.Button):
    def __init__(self, parent: VoiceSettingsView):
        super().__init__(style=discord.ButtonStyle.danger, label="✖️ 閉じる")
        self.parent_view = parent

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.stop()
        await interaction.response.edit_message(view=ClosedView(), attachments=[])


class VoiceSettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="voice", description="読み上げボイス（キャラクター）を設定します")
    async def voice(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            speakers = await self.bot.voicevox.get_speakers()
        except Exception:
            log.exception("VOICEVOXのスピーカー一覧取得に失敗しました")
            await interaction.followup.send(
                view=ui.error(
                    "VOICEVOXに接続できません",
                    "エンジンが起動しているか確認してください。",
                )
            )
            return

        if not speakers:
            await interaction.followup.send(
                view=ui.error("キャラクターが見つかりません", "VOICEVOXの設定を確認してください。")
            )
            return

        user_voice = await self.bot.db.get_user_voice(interaction.user.id)

        view = VoiceSettingsView(self.bot, interaction.user.id, speakers, user_voice)
        file = await view.build()

        kwargs: dict[str, Any] = {"view": view}
        if file:
            kwargs["files"] = [file]
        await interaction.followup.send(**kwargs)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceSettingsCog(bot))
