from __future__ import annotations

import logging

import discord
from discord.ext import commands, tasks

import config

log = logging.getLogger("tts.cog.presence")

MAX_NAME_LENGTH = 60


class PresenceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._index = 0

    async def cog_load(self) -> None:
        self.rotate_presence.start()

    async def cog_unload(self) -> None:
        self.rotate_presence.cancel()

    def _reading_label(self) -> str | None:
        reading = [g for g in self.bot.guilds if self.bot.audio.is_connected(g.id)]
        if not reading:
            return None
        if len(reading) == 1:
            name = reading[0].name
            if len(name) > MAX_NAME_LENGTH:
                name = name[: MAX_NAME_LENGTH - 1] + "…"
            return f"{name} で読み上げ中"
        return f"{len(reading)}サーバーで読み上げ中"

    def _activities(self) -> list[discord.Activity]:
        items: list[discord.Activity] = []
        reading = self._reading_label()
        if reading:
            items.append(discord.Activity(type=discord.ActivityType.listening, name=reading))
        items.append(
            discord.Activity(type=discord.ActivityType.listening, name="/voice で声を設定")
        )
        return items

    @tasks.loop(seconds=config.PRESENCE_INTERVAL)
    async def rotate_presence(self) -> None:
        activities = self._activities()
        self._index %= len(activities)
        try:
            await self.bot.change_presence(activity=activities[self._index])
        except Exception:
            log.warning("ステータスの更新に失敗しました", exc_info=True)
        self._index = (self._index + 1) % len(activities)

    @rotate_presence.before_loop
    async def before_rotate(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(PresenceCog(bot))
