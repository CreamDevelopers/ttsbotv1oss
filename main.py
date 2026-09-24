from __future__ import annotations

import asyncio
import logging
import sys

import discord
from discord import app_commands
from discord.ext import commands

import config
from core import timeutil
from core.audio_manager import AudioManager
from core.database import Database
from core.ffmpeg_installer import ensure_ffmpeg
from core.ui import error as error_notice
from core.voicevox import VoicevoxClient

timeutil.configure_logging(config.LOG_LEVEL)
log = logging.getLogger("tts.main")

INITIAL_COGS = [
    "cogs.tts",
    "cogs.voice_settings",
    "cogs.dictionary",
    "cogs.admin",
    "cogs.earthquake",
    "cogs.sound",
    "cogs.help",
    "cogs.presence",
]


class TTSBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

        self.db = Database(
            config.DB_PATH,
            default_speaker_id=config.DEFAULT_SPEAKER_ID,
            default_max_length=config.MAX_MESSAGE_LENGTH,
        )
        self.voicevox = VoicevoxClient(config.VOICEVOX_URL)
        self.audio = AudioManager(config.FFMPEG_PATH, duck_volume=config.SOUND_DUCK_VOLUME)
        self._voice_restored = False

    async def setup_hook(self) -> None:
        await self.db.connect()

        self.audio.ffmpeg_path = await asyncio.to_thread(ensure_ffmpeg, config.FFMPEG_PATH)

        for ext in INITIAL_COGS:
            try:
                await self.load_extension(ext)
            except Exception:
                log.exception("Cogの読み込みに失敗しました: %s", ext)

        self.tree.error(on_tree_error)

        if config.DEV_GUILD_ID:
            guild = discord.Object(id=int(config.DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("スラッシュコマンドをサーバー %s に同期しました", config.DEV_GUILD_ID)
        else:
            await self.tree.sync()
            log.info("スラッシュコマンドを同期しました（反映まで数分かかることがあります）")

    async def on_ready(self) -> None:
        log.info("ログインしました: %s (ID: %s)", self.user, self.user.id)
        log.info(
            "招待URL: https://discord.com/oauth2/authorize?client_id=%s&permissions=3263552&scope=bot+applications.commands",
            self.user.id,
        )
        # on_ready は再接続のたびに呼ばれる
        if not self._voice_restored:
            self._voice_restored = True
            restored = await self.audio.restore_connections(self)
            if restored:
                log.info("%d件のボイスチャンネル接続を復帰しました", restored)

        if not await self.voicevox.is_available():
            log.warning("VOICEVOXエンジンに接続できません: %s", config.VOICEVOX_URL)

    async def close(self) -> None:
        await self.audio.shutdown()
        await self.voicevox.close()
        await self.db.close()
        await super().close()


async def _safe_respond(interaction: discord.Interaction, heading: str, body: str | None = None) -> None:
    try:
        view = error_notice(heading, body)
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        else:
            await interaction.response.send_message(view=view, ephemeral=True)
    except Exception:
        log.exception("エラーメッセージの送信に失敗しました")


async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.MissingPermissions):
        await _safe_respond(interaction, "権限が足りません", "この操作にはサーバー管理権限が必要です。")
    elif isinstance(error, app_commands.CommandOnCooldown):
        await _safe_respond(
            interaction, "クールダウン中です", f"{error.retry_after:.1f}秒後に再試行してください。"
        )
    elif isinstance(error, app_commands.NoPrivateMessage):
        await _safe_respond(interaction, "サーバー内で実行してください", "このコマンドはDMでは使用できません。")
    else:
        log.exception("スラッシュコマンドの実行中にエラーが発生しました", exc_info=error)
        await _safe_respond(interaction, "エラーが発生しました", "コマンドの実行中に問題が起きました。")


async def main() -> None:
    bot = TTSBot()
    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        log.error("DISCORD_TOKEN が設定されていません。.env に書くか、起動スクリプトから設定してください。")
        sys.exit(1)
    try:
        asyncio.run(main())
    except discord.LoginFailure:
        log.error("ログインに失敗しました。DISCORD_TOKEN が正しいか確認してください。")
        sys.exit(1)
    except discord.PrivilegedIntentsRequired:
        log.error(
            "Developer Portal の Bot 設定で MESSAGE CONTENT INTENT と SERVER MEMBERS INTENT を有効にしてください。"
        )
        sys.exit(1)
    except KeyboardInterrupt:
        pass
