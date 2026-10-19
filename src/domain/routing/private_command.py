"""私信里哪些内容要当成命令。普通聊天不回复，避免每条私信都提示未知命令。"""

from __future__ import annotations

_PREFIXES = (
    "播放歌单",
    "播放专辑",
    "添加歌单",
    "添加专辑",
    "播放",
    "放",
    "点播",
    "来一首",
    "唱",
    "添加",
    "搜歌",
    "搜索歌曲",
    "选歌",
    "选择",
    "停止",
    "停",
    "停止播放",
    "下一首",
    "切歌",
    "跳过",
    "下一个",
    "队列",
    "列表",
    "播放列表",
    "随机",
    "随机播放",
    "喜欢列表",
    "喜欢",
    "随便来一首",
    "模式",
    "音源",
    "退出",
    "离开",
    "进入频道",
    "进入",
    "帮助",
    "help",
)


def looks_like_private_command(content: str, bot_mention: str = "") -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    if bot_mention and bot_mention in text:
        text = text.replace(bot_mention, "").strip()
    if text.startswith("/"):
        return True
    return any(text == prefix or text.startswith(prefix) for prefix in _PREFIXES)
