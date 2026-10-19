"""网易云和 QQ 音乐的扫码登录。

二维码和检查必须走同一串 Cookie。浏览器里单独打开检查地址会丢掉这串
Cookie，网易云就返回 800。这里由本机页面发起，服务端自己记住会话并轮询。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import requests
except Exception:
    requests = None

_COOKIE_ATTRS = frozenset({
    "path",
    "domain",
    "expires",
    "max-age",
    "samesite",
    "secure",
    "httponly",
})


@dataclass
class QrTicket:
    platform: str
    key: str = ""
    image: str = ""
    cookie: str = ""
    qrsig: str = ""
    ptqrtoken: str = ""
    session: Any = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_tickets: dict[str, QrTicket] = {}
_lock = threading.Lock()


def merge_cookie(*parts: object) -> str:
    """把多次响应里的 name=value 收成一条 Cookie，丢掉 Path、Secure 这类属性。"""
    pairs: dict[str, str] = {}
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple)):
            for item in part:
                pairs.update(_pairs_from_text(str(item)))
            continue
        pairs.update(_pairs_from_text(str(part)))
    return "; ".join(f"{name}={value}" for name, value in pairs.items() if value)


def _pairs_from_text(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for piece in text.split(";"):
        piece = piece.strip()
        if "=" not in piece:
            continue
        name, value = piece.split("=", 1)
        name = name.strip()
        if not name or name.lower() in _COOKIE_ATTRS:
            continue
        pairs[name] = value.strip()
    return pairs


def netease_qr_status(payload: dict) -> str:
    """把网易云 /login/qr/check 的 code 收成和 TeamSpeak 机器人一样的四种状态。"""
    code = _first_code(payload, (800, 801, 802, 803))
    return {
        800: "expired",
        801: "waiting",
        802: "scanned",
        803: "confirmed",
    }.get(code, "expired")


def qq_qr_status(payload: dict) -> str:
    """QQ 接口：登录成功、二维码失效，或还在等扫描。"""
    if not isinstance(payload, dict):
        return "expired"
    if payload.get("isOk") is True:
        return "confirmed"
    if payload.get("refresh") is True:
        return "expired"
    message = str(payload.get("message") or "")
    if "失效" in message or "过期" in message:
        return "expired"
    return "waiting"


def cookie_from_payload(payload: dict, response: Any = None) -> str:
    chunks: list[object] = []
    if isinstance(payload, dict):
        chunks.append(payload.get("cookie"))
        data = payload.get("data")
        if isinstance(data, dict):
            chunks.append(data.get("cookie"))
        session = payload.get("session")
        if isinstance(session, dict):
            chunks.append(session.get("cookie"))
    jar = getattr(response, "cookies", None)
    if jar is not None:
        try:
            chunks.append([f"{item.name}={item.value}" for item in jar])
        except Exception:
            pass
    headers = getattr(response, "headers", None)
    if headers is not None:
        raw = headers.get("set-cookie") if hasattr(headers, "get") else ""
        chunks.append(raw)
    return merge_cookie(*chunks)


def _first_code(payload: dict, allowed: tuple[int, ...]) -> int:
    data = payload.get("data") if isinstance(payload, dict) else None
    values = []
    if isinstance(data, dict):
        values.append(data.get("code"))
    if isinstance(payload, dict):
        values.append(payload.get("code"))
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in allowed:
            return parsed
    return 0


def _now_ms() -> str:
    return str(int(time.time() * 1000))


def _require_requests():
    if requests is None:
        raise RuntimeError("缺少 requests 依赖，请先安装 requirements.txt")


def _get_json(session: Any, url: str, params: dict) -> tuple[dict, Any]:
    """用 GET，并把时间放在地址上。

    网易云接口会缓存两分钟内地址相同的成功响应。时间如果只放在请求正文里，
    检查会一直拿到第一次的「等待扫码」，再点显示也还是那张已经过期的二维码。
    """
    query = dict(params)
    query["timestamp"] = _now_ms()
    response = session.get(
        url,
        params=query,
        timeout=20,
        headers={
            "Cache-Control": "no-store",
            "x-apicache-bypass": "true",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("音乐接口返回的不是 JSON 对象")
    return payload, response


def _qr_image(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("data:"):
        return text
    return f"data:image/png;base64,{text}"


def _base_url(group: str, fallback: str) -> str:
    import web.web_player_config as cfg

    source = cfg.NETEASE_CLOUD if group == "netease" else cfg.QQ_MUSIC_CONFIG
    return str(source.get("base_url") or fallback).rstrip("/")


def start_qr(platform: str) -> dict:
    """生成一张二维码，并把这次会话留在本进程里。"""
    platform = str(platform or "").strip()
    if platform not in {"netease", "qq"}:
        raise ValueError("只支持网易云或 QQ 音乐")
    _require_requests()
    session = requests.Session()
    session.headers["Cache-Control"] = "no-store"
    if platform == "netease":
        ticket = _start_netease(session)
    else:
        ticket = _start_qq(session)
    ticket.session = session
    with _lock:
        _tickets[platform] = ticket
    return {"platform": platform, "image": ticket.image, "status": "waiting"}


def poll_qr(platform: str) -> dict:
    """查看当前二维码。确认后把 Cookie 写入配置，不把 Cookie 返回给页面。"""
    platform = str(platform or "").strip()
    with _lock:
        ticket = _tickets.get(platform)
    if ticket is None or ticket.session is None:
        return {"platform": platform, "status": "expired", "message": "请先生成二维码"}
    _require_requests()
    with ticket.lock:
        if ticket.cookie:
            ticket.session.headers["Cookie"] = ticket.cookie
        if platform == "netease":
            result = _poll_netease(ticket.session, ticket)
        else:
            result = _poll_qq(ticket.session, ticket)
    if result["status"] == "confirmed":
        nickname = _save_cookie(platform, result.pop("cookie"))
        with _lock:
            _tickets.pop(platform, None)
        result["nickname"] = nickname
        result["message"] = f"已登录{nickname}" if nickname else "登录成功，Cookie 已保存"
    return result


def _start_netease(session: Any) -> QrTicket:
    base = _base_url("netease", "http://localhost:3000")
    ticket = QrTicket(platform="netease")
    payload, response = _get_json(session, f"{base}/login/qr/key", {})
    ticket.cookie = cookie_from_payload(payload, response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    ticket.key = str(data.get("unikey") or payload.get("unikey") or "").strip()
    if not ticket.key:
        raise RuntimeError("网易云没有返回二维码 key")
    created, response = _get_json(
        session,
        f"{base}/login/qr/create",
        {"key": ticket.key, "qrimg": "true", "cookie": ticket.cookie},
    )
    ticket.cookie = merge_cookie(ticket.cookie, cookie_from_payload(created, response))
    image_data = created.get("data") if isinstance(created.get("data"), dict) else {}
    ticket.image = _qr_image(str(image_data.get("qrimg") or created.get("qrimg") or ""))
    if not ticket.image:
        raise RuntimeError("网易云没有返回二维码图片")
    return ticket


def _poll_netease(session: Any, ticket: QrTicket) -> dict:
    base = _base_url("netease", "http://localhost:3000")
    payload, response = _get_json(
        session,
        f"{base}/login/qr/check",
        {"key": ticket.key, "cookie": ticket.cookie},
    )
    status = netease_qr_status(payload)
    found = cookie_from_payload(payload, response)
    if found:
        ticket.cookie = merge_cookie(ticket.cookie, found)
    message = str(payload.get("message") or payload.get("msg") or "")
    if status != "confirmed":
        return {"platform": "netease", "status": status, "message": message}
    if "MUSIC_U=" not in ticket.cookie:
        raise RuntimeError("扫码成功，但没有拿到 MUSIC_U，请重新生成二维码")
    return {"platform": "netease", "status": "confirmed", "cookie": ticket.cookie, "message": message}


def _start_qq(session: Any) -> QrTicket:
    base = _base_url("qq", "http://localhost:3300")
    response = session.get(
        f"{base}/getQQLoginQr",
        params={"timestamp": _now_ms()},
        timeout=20,
        headers={"Cache-Control": "no-store"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("QQ 音乐接口返回的不是 JSON 对象")
    ticket = QrTicket(platform="qq")
    ticket.qrsig = str(payload.get("qrsig") or "")
    ticket.ptqrtoken = str(payload.get("ptqrtoken") or "")
    ticket.image = _qr_image(str(payload.get("img") or ""))
    if not ticket.qrsig or not ticket.ptqrtoken or not ticket.image:
        raise RuntimeError("QQ 音乐没有返回完整二维码。请确认本机 3300 端口的 QQ 音乐接口已经启动")
    return ticket


def _poll_qq(session: Any, ticket: QrTicket) -> dict:
    base = _base_url("qq", "http://localhost:3300")
    response = session.post(
        f"{base}/checkQQLoginQr",
        params={"qrsig": ticket.qrsig, "ptqrtoken": ticket.ptqrtoken, "timestamp": _now_ms()},
        timeout=20,
        headers={"Cache-Control": "no-store"},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("QQ 音乐接口返回的不是 JSON 对象")
    status = qq_qr_status(payload)
    message = str(payload.get("message") or "")
    if status != "confirmed":
        return {"platform": "qq", "status": status, "message": message}
    session_body = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    cookie = str(session_body.get("cookie") or "")
    if "uin=" not in cookie:
        raise RuntimeError("QQ 扫码成功，但没有拿到登录 Cookie")
    return {"platform": "qq", "status": "confirmed", "cookie": cookie, "message": message}


def _save_cookie(platform: str, cookie: str) -> str:
    import web.web_player_config as cfg

    group = "netease" if platform == "netease" else "qq_music"
    patch: dict[str, object] = {"cookie": cookie}
    if platform == "qq":
        patch["enabled"] = True
    _applied, errors, payload = cfg.apply_config_updates({group: patch})
    if errors:
        raise RuntimeError("；".join(errors))
    cfg.persist_config_updates(payload)
    try:
        import web.web_player as web_player

        if platform == "netease":
            web_player.reset_netease()
        web_player.refresh_music_platforms()
    except Exception:
        pass
    return _nickname(platform, cookie)


def _nickname(platform: str, cookie: str) -> str:
    if platform == "qq":
        import re

        matched = re.search(r"(?:^|; )uin=o?0?(\d+)", cookie)
        return f"QQ {matched.group(1)}" if matched else ""
    try:
        from web.admin.shared._netease import _netease_account_status

        status = _netease_account_status(_base_url("netease", "http://localhost:3000"), cookie)
        profile = status.get("profile") if isinstance(status, dict) else None
        if isinstance(profile, dict):
            return str(profile.get("nickname") or "")
    except Exception:
        return ""
    return ""


def music_login_summary() -> dict:
    """给登录页看当前是否已经有音乐 Cookie，不返回 Cookie 本身。"""
    import web.web_player_config as cfg

    netease_cookie = str(cfg.NETEASE_CLOUD.get("cookie") or "")
    qq_cookie = str(cfg.QQ_MUSIC_CONFIG.get("cookie") or "")
    return {
        "netease": {"logged_in": "MUSIC_U=" in netease_cookie},
        "qq": {
            "logged_in": "uin=" in qq_cookie,
            "enabled": bool(cfg.QQ_MUSIC_CONFIG.get("enabled")),
        },
    }
