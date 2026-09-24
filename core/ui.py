from __future__ import annotations

from typing import Iterable, Optional

import discord

KIND_STYLE: dict[str, tuple[discord.Colour, Optional[str]]] = {
    "info": (discord.Colour.from_rgb(108, 92, 231), "ℹ️"),
    "success": (discord.Colour.from_rgb(46, 204, 113), "✅"),
    "warning": (discord.Colour.from_rgb(230, 126, 34), "⚠️"),
    "error": (discord.Colour.from_rgb(214, 48, 49), "⛔"),
    "neutral": (discord.Colour.from_rgb(149, 165, 166), None),
}

BODY_MAX = 3800


def truncate(text: str, limit: int = BODY_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…(以下省略)"


class NoticeView(discord.ui.LayoutView):
    def __init__(
        self,
        heading: str,
        body: Optional[str] = None,
        *,
        kind: str = "info",
        emoji: Optional[str] = None,
        footer: Optional[str] = None,
        items: Optional[Iterable[discord.ui.Item]] = None,
    ):
        super().__init__(timeout=None)
        colour, default_emoji = KIND_STYLE.get(kind, KIND_STYLE["info"])
        container = discord.ui.Container(accent_colour=colour)

        icon = default_emoji if emoji is None else emoji
        container.add_item(discord.ui.TextDisplay(f"## {icon + ' ' if icon else ''}{heading}"))

        if body:
            container.add_item(discord.ui.TextDisplay(truncate(body)))
        for item in items or ():
            container.add_item(item)
        if footer:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        self.add_item(container)


def notice(heading: str, body: Optional[str] = None, **kwargs) -> NoticeView:
    return NoticeView(heading, body, **kwargs)


def success(heading: str, body: Optional[str] = None, **kwargs) -> NoticeView:
    return NoticeView(heading, body, kind="success", **kwargs)


def warning(heading: str, body: Optional[str] = None, **kwargs) -> NoticeView:
    return NoticeView(heading, body, kind="warning", **kwargs)


def error(heading: str, body: Optional[str] = None, **kwargs) -> NoticeView:
    return NoticeView(heading, body, kind="error", **kwargs)


def field_lines(pairs: Iterable[tuple[str, str]]) -> str:
    return "\n".join(f"**{name}**　{value}" for name, value in pairs)


async def respond(
    interaction: discord.Interaction, view: discord.ui.LayoutView, *, ephemeral: bool = True
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(view=view, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(view=view, ephemeral=ephemeral)
