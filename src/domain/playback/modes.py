"""播放模式。顺序、循环、随机、随机循环，和原来的列表模式并存。"""

from __future__ import annotations

PLAY_MODE_SEQ = "seq"
PLAY_MODE_LOOP = "loop"
PLAY_MODE_RANDOM = "random"
PLAY_MODE_RLOOP = "rloop"

MODE_LABELS = {
    PLAY_MODE_SEQ: "顺序播放",
    PLAY_MODE_LOOP: "顺序循环",
    PLAY_MODE_RANDOM: "随机播放",
    PLAY_MODE_RLOOP: "随机循环",
}

_MODE_INPUT = {
    "seq": PLAY_MODE_SEQ,
    "sequential": PLAY_MODE_SEQ,
    "shunxu": PLAY_MODE_SEQ,
    "顺序": PLAY_MODE_SEQ,
    "顺序播放": PLAY_MODE_SEQ,
    "单次": PLAY_MODE_SEQ,
    "loop": PLAY_MODE_LOOP,
    "xunhuan": PLAY_MODE_LOOP,
    "shunxuxunhuan": PLAY_MODE_LOOP,
    "循环": PLAY_MODE_LOOP,
    "顺序循环": PLAY_MODE_LOOP,
    "列表循环": PLAY_MODE_LOOP,
    "random": PLAY_MODE_RANDOM,
    "suiji": PLAY_MODE_RANDOM,
    "随机": PLAY_MODE_RANDOM,
    "随机播放": PLAY_MODE_RANDOM,
    "rloop": PLAY_MODE_RLOOP,
    "suijixunhuan": PLAY_MODE_RLOOP,
    "随机循环": PLAY_MODE_RLOOP,
}


def parse_play_mode(text: str) -> str:
    """把命令里的模式词收成 seq、loop、random、rloop。认不出就返回空字符串。"""
    return _MODE_INPUT.get(str(text or "").strip().lower(), "") or _MODE_INPUT.get(str(text or "").strip(), "")


def mode_label(mode: str) -> str:
    return MODE_LABELS.get(mode, mode)


_SOURCE_INPUT = {
    "netease": "netease",
    "wangyiyun": "netease",
    "wy": "netease",
    "网易": "netease",
    "网易云": "netease",
    "qq": "qq",
    "qq音乐": "qq",
    "bili": "bilibili",
    "bilibili": "bilibili",
    "b站": "bilibili",
}

_SOURCE_LABELS = {
    "netease": "网易云",
    "qq": "QQ音乐",
    "bilibili": "B站",
}


def parse_source(text: str) -> str:
    raw = str(text or "").strip()
    return _SOURCE_INPUT.get(raw.lower(), "") or _SOURCE_INPUT.get(raw, "")


def source_label(platform: str) -> str:
    return _SOURCE_LABELS.get(platform, platform)


def shuffles_new_batch(mode: str) -> bool:
    """随机和随机循环只打乱这一次加进去的歌，不动原来的队列。"""
    return mode in {PLAY_MODE_RANDOM, PLAY_MODE_RLOOP}
