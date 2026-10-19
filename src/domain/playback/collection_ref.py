"""从歌名、编号或链接里认出网易云、QQ 的歌单和专辑。"""

from __future__ import annotations

import re

_NETEASE_PLAYLIST = re.compile(r"(?:playlist\?.*?id=|/playlist/)(\d+)", re.IGNORECASE)
_NETEASE_ALBUM = re.compile(r"(?:album\?.*?id=|/album/)(\d+)", re.IGNORECASE)
_QQ_PLAYLIST = re.compile(r"(?:playlist/|disstid=)(\d+)", re.IGNORECASE)
_QQ_ALBUM = re.compile(r"(?:album(?:/detail)?/|albummid=)([0-9A-Za-z]+)", re.IGNORECASE)
_PLAIN_ID = re.compile(r"^[0-9A-Za-z]+$")


def collection_ref(text: str, kind: str) -> tuple[str, str]:
    """返回 (平台, 编号)。认不出链接时平台为空，调用方再按名字搜索。"""
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    if "qq.com" in raw.lower() or "y.qq.com" in raw.lower():
        matched = (_QQ_PLAYLIST if kind == "playlist" else _QQ_ALBUM).search(raw)
        return ("qq", matched.group(1)) if matched else ("", "")
    if "163.com" in raw.lower() or "music.163" in raw.lower():
        matched = (_NETEASE_PLAYLIST if kind == "playlist" else _NETEASE_ALBUM).search(raw)
        return ("netease", matched.group(1)) if matched else ("", "")
    if _PLAIN_ID.fullmatch(raw):
        return "", raw
    return "", ""
