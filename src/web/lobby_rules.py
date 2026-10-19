"""登录窗口用的纯判断：本机访问、要不要弹出浏览器、哪些是语音频道。"""

from __future__ import annotations

import ipaddress

VOICE_CHANNEL_TYPES = frozenset({"VOICE", "AUDIO"})

# 这些是账号本身不对，弹浏览器也填不对。
_PASSWORD_REJECTED = (
    "密码错误",
    "密码不正确",
    "账号不存在",
    "用户不存在",
    "手机号或密码",
    "账号或密码错误",
    "不能为空",
)


def is_loopback_host(host: str | None) -> bool:
    """只认本机地址。不看转发头，避免别人伪造成 127.0.0.1。"""
    text = str(host or "").strip().strip("[]")
    if not text or text.lower() == "localhost":
        return text.lower() == "localhost"
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return bool(address.is_loopback)


def needs_visible_browser(message: str) -> bool:
    """密码被明确拒绝时不弹窗。验证码、风控和其他登录失败留给可见浏览器。"""
    text = str(message or "")
    return not any(part in text for part in _PASSWORD_REJECTED)


def is_voice_channel(channel_type: str) -> bool:
    return str(channel_type or "").strip().upper() in VOICE_CHANNEL_TYPES


def voice_rows_from_groups(area_id: str, area_name: str, groups: list) -> list[dict]:
    """从域的频道分组里抽出语音频道。文字频道不出现在双击列表里。"""
    rows: list[dict] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        group_name = str(group.get("name") or "")
        for channel in group.get("channels") or []:
            if not isinstance(channel, dict):
                continue
            if not is_voice_channel(str(channel.get("type") or "")):
                continue
            channel_id = str(channel.get("id") or "").strip()
            if not channel_id:
                continue
            rows.append({
                "area_id": area_id,
                "area_name": area_name,
                "group": group_name,
                "id": channel_id,
                "name": str(channel.get("name") or channel_id),
                "type": str(channel.get("type") or "").strip().upper(),
            })
    return rows
