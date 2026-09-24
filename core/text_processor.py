from __future__ import annotations

import re
from typing import Iterable, Optional

import discord

_CODEBLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
_URL_RE = re.compile(r"https?://\S+")
_MENTION_USER_RE = re.compile(r"<@!?(\d+)>")
_MENTION_CHANNEL_RE = re.compile(r"<#(\d+)>")
_MENTION_ROLE_RE = re.compile(r"<@&(\d+)>")
_MARKDOWN_RE = re.compile(r"(\*\*\*|\*\*|\*|__|_|~~|>{1,3})")

_SINGLE_CHAR_SEP = " 　,，、"
_SINGLE_CHAR_RUN_RE = re.compile(
    rf"[^{_SINGLE_CHAR_SEP}](?:[{_SINGLE_CHAR_SEP}][^{_SINGLE_CHAR_SEP}]){{2,}}"
)
_SINGLE_CHAR_SEP_RE = re.compile(f"[{_SINGLE_CHAR_SEP}]")


def _collapse_single_char_runs(text: str) -> str:
    return _SINGLE_CHAR_RUN_RE.sub(lambda m: _SINGLE_CHAR_SEP_RE.sub("", m.group(0)), text)


def apply_dictionary(text: str, dictionary: Iterable[tuple[str, str]]) -> str:
    entries = sorted(((w, r) for w, r in dictionary if w), key=lambda e: len(e[0]), reverse=True)
    if not entries:
        return text
    table = dict(entries)
    # 1語ずつ replace すると置換結果がさらに置換されるので、1回の走査で済ませる
    pattern = re.compile("|".join(re.escape(word) for word, _ in entries))
    return pattern.sub(lambda m: table[m.group(0)], text)


def clean_text(
    content: str,
    guild: Optional[discord.Guild],
    dictionary: Optional[Iterable[tuple[str, str]]] = None,
    max_length: int = 200,
) -> str:
    text = content

    text = _CODEBLOCK_RE.sub("、コードブロック、", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _CUSTOM_EMOJI_RE.sub(lambda m: m.group(1), text)
    text = _URL_RE.sub("URL省略", text)

    if guild is not None:
        def _user_repl(m: re.Match) -> str:
            member = guild.get_member(int(m.group(1)))
            return f"{member.display_name}さん" if member else "メンション"

        def _channel_repl(m: re.Match) -> str:
            ch = guild.get_channel(int(m.group(1)))
            return f"{ch.name}チャンネル" if ch else "チャンネル"

        def _role_repl(m: re.Match) -> str:
            role = guild.get_role(int(m.group(1)))
            return f"{role.name}ロール" if role else "ロール"

        text = _MENTION_USER_RE.sub(_user_repl, text)
        text = _MENTION_CHANNEL_RE.sub(_channel_repl, text)
        text = _MENTION_ROLE_RE.sub(_role_repl, text)
    else:
        text = _MENTION_USER_RE.sub("メンション", text)
        text = _MENTION_CHANNEL_RE.sub("チャンネル", text)
        text = _MENTION_ROLE_RE.sub("ロール", text)

    text = _MARKDOWN_RE.sub("", text)
    text = _collapse_single_char_runs(text)

    text = apply_dictionary(text, dictionary or ())

    text = re.sub(r"\n+", "。", text)
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_length:
        text = text[:max_length] + "、以下略"

    return text


_SENTENCE_RE = re.compile(r"[^。．！？!?\n]*(?:[。．！？!?\n]+|$)")
_CLAUSE_RE = re.compile(r"(?<=[、，,])")


def _hard_split(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def _split_sentence(sentence: str, size: int) -> list[str]:
    if len(sentence) <= size:
        return [sentence]

    parts: list[str] = []
    buf = ""
    for clause in _CLAUSE_RE.split(sentence):
        if not clause:
            continue
        if buf and len(buf) + len(clause) > size:
            parts.append(buf)
            buf = ""
        if len(clause) > size:
            if buf:
                parts.append(buf)
                buf = ""
            chunks = _hard_split(clause, size)
            parts.extend(chunks[:-1])
            buf = chunks[-1]
        else:
            buf += clause
    if buf:
        parts.append(buf)
    return parts


def split_text(text: str, max_chunk: int = 60) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chunk:
        return [text]

    pieces: list[str] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if sentence:
            pieces.extend(_split_sentence(sentence, max_chunk))

    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) > max_chunk:
            chunks.append(buf)
            buf = piece
        else:
            buf += piece
    if buf:
        chunks.append(buf)
    return chunks
