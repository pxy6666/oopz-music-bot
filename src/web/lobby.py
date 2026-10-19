"""本机登录和进频道页面。

启动机器人不会进入语音频道。这个页面只负责登录，以及在双击时调用进入频道。
页面和接口只接受本机连接，因为这里会收到手机号和密码。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from oopz_sdk.exceptions import OopzConnectionError, OopzPasswordLoginError
from web.lobby_rules import is_loopback_host, needs_visible_browser, voice_rows_from_groups

router = APIRouter(prefix="/lobby")

_PAGE = os.path.join(os.path.dirname(__file__), "assets", "lobby", "index.html")
# 验证码要人手输入，窗口最多留 5 分钟。
_BROWSER_TIMEOUT = 300.0
_API_TIMEOUT = 20.0


def _reject_remote(request: Request) -> JSONResponse | None:
    host = request.client.host if request.client is not None else ""
    if is_loopback_host(host):
        return None
    return JSONResponse(
        {"ok": False, "error": "登录页只允许本机打开，请使用 http://127.0.0.1:8080/lobby"},
        status_code=403,
    )


def _mask_phone(phone: str) -> str:
    text = str(phone or "").strip()
    if len(text) < 7:
        return ""
    return f"{text[:3]}****{text[-4:]}"


def _runtime():
    import web.web_player as web_player

    return web_player.get_sender(), web_player.get_music()


async def _areas_and_channels(sender) -> list[dict]:
    areas = await sender.get_joined_areas(quiet=True)
    listed: list[dict] = []
    for area in areas or []:
        if not isinstance(area, dict):
            continue
        area_id = str(area.get("id") or "").strip()
        if not area_id:
            continue
        area_name = str(area.get("name") or area_id)
        groups = await sender.get_area_channels(area=area_id, quiet=True)
        listed.append({
            "id": area_id,
            "name": area_name,
            "channels": voice_rows_from_groups(area_id, area_name, groups if isinstance(groups, list) else []),
        })
    return listed


async def _rebind_voice(sender, music) -> None:
    """热更新凭据会换掉 SDK 会话，推流要跟着换，否则双击进的是旧连接。"""
    if music is None or sender is None:
        return
    voice = getattr(music, "voice", None)
    bot = getattr(sender, "bot", None)
    new_voice = getattr(bot, "voice", None)
    rebind = getattr(voice, "rebind", None)
    if new_voice is None or rebind is None:
        return
    await rebind(new_voice)


async def _login_with_browser(phone: str, password: str) -> Any:
    from oopz_sdk.auth import login_with_playwright_password

    return await login_with_playwright_password(
        phone,
        password,
        timeout=_BROWSER_TIMEOUT,
        headless=False,
        manual_challenge=True,
        submit_form=bool(password),
        browser_data_dir=None,
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def lobby_page(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    with open(_PAGE, encoding="utf-8") as handle:
        return HTMLResponse(
            handle.read(),
            headers={"Cache-Control": "no-store"},
        )


@router.get("/api/status")
async def lobby_status(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    from config import OOPZ_CONFIG

    sender, music = _runtime()
    area_id, channel_id = ("", "")
    if music is not None and hasattr(music, "current_voice_channel"):
        area_id, channel_id = music.current_voice_channel()
    phone = str(OOPZ_CONFIG.get("login_phone") or "")
    ready = bool(sender is not None and getattr(sender, "ready", False))
    return JSONResponse({
        "ok": True,
        "connected": ready,
        "has_credentials": bool(OOPZ_CONFIG.get("person_uid") and OOPZ_CONFIG.get("jwt_token")),
        "phone": _mask_phone(phone),
        "voice": {"area": area_id, "channel": channel_id},
    })


@router.post("/api/login")
async def lobby_login(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected

    from web.admin.shared._oopz import _oopz_login_lock, _refresh_oopz_runtime

    if _oopz_login_lock.locked():
        return JSONResponse({"ok": False, "error": "已经有一个登录在进行，请等浏览器窗口结束"}, status_code=409)

    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    phone = str(body.get("phone") or "").strip()
    password = str(body.get("password") or "")
    if not phone:
        return JSONResponse({"ok": False, "error": "请填写手机号"}, status_code=400)

    from config import OOPZ_CONFIG
    from oopz.credentials import persist_credentials, persist_login_account
    from oopz_sdk.auth import login_with_password

    device_id = str(OOPZ_CONFIG.get("device_id") or "").strip()
    async with _oopz_login_lock:
        try:
            if password:
                try:
                    credentials = await login_with_password(
                        phone,
                        password,
                        device_id=device_id or None,
                        timeout=_API_TIMEOUT,
                    )
                    via = "api"
                except OopzPasswordLoginError as exc:
                    if not needs_visible_browser(str(exc)):
                        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
                    credentials = await _login_with_browser(phone, password)
                    via = "browser"
            else:
                credentials = await _login_with_browser(phone, "")
                via = "browser"
        except OopzConnectionError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        except OopzPasswordLoginError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"登录失败: {exc}"}, status_code=500)

        try:
            await persist_login_account(phone, password)
            saved = await persist_credentials(credentials)
            sender, music = _runtime()
            runtime = await _refresh_oopz_runtime(credentials)
            await _rebind_voice(sender, music)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"登录成功，但保存或重连失败: {exc}"}, status_code=500)

    if sender is not None and hasattr(sender, "wait_ready"):
        try:
            await sender.wait_ready(20)
        except Exception:
            pass
    message = "登录成功。启动不会进入频道，请在下面双击语音频道。"
    if not runtime.get("sdk_session"):
        message += " 这次没有连上正在运行的机器人，请重新启动后再打开本页。"
    return JSONResponse({
        "ok": True,
        "via": via,
        "saved": saved,
        "runtime": runtime,
        "message": message,
    })


@router.get("/api/channels")
async def lobby_channels(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    sender, music = _runtime()
    if sender is None:
        return JSONResponse({"ok": False, "error": "机器人还没连上 OOPZ"}, status_code=503)
    try:
        areas = await _areas_and_channels(sender)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"读取频道失败: {exc}"}, status_code=502)
    area_id, channel_id = ("", "")
    if music is not None and hasattr(music, "current_voice_channel"):
        area_id, channel_id = music.current_voice_channel()
    return JSONResponse({
        "ok": True,
        "areas": areas,
        "voice": {"area": area_id, "channel": channel_id},
    })


@router.post("/api/join")
async def lobby_join(request: Request):
    """只有这个接口会进入语音频道。打开页面和刷新列表都不会调用它。"""
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    area = str(body.get("area") or "").strip()
    channel = str(body.get("channel") or "").strip()
    if not area or not channel:
        return JSONResponse({"ok": False, "error": "缺少域或频道"}, status_code=400)

    sender, music = _runtime()
    if sender is None or music is None or not hasattr(music, "enter_voice_channel"):
        return JSONResponse({"ok": False, "error": "语音模块还没准备好"}, status_code=503)
    groups = await sender.get_area_channels(area=area, quiet=True)
    allowed = {
        row["id"]
        for row in voice_rows_from_groups(area, "", groups if isinstance(groups, list) else [])
    }
    if channel not in allowed:
        return JSONResponse({"ok": False, "error": "只能进入语音频道"}, status_code=400)

    result = await music.enter_voice_channel(channel, area)
    if isinstance(result, dict) and result.get("error"):
        return JSONResponse({"ok": False, "error": str(result["error"])}, status_code=502)
    return JSONResponse({"ok": True, "area": area, "channel": channel, "message": "已进入语音频道"})


@router.get("/api/music")
async def lobby_music_status(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    from web.music_qr import music_login_summary

    return JSONResponse({"ok": True, **music_login_summary()})


@router.post("/api/music/qr")
async def lobby_music_qr_start(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    platform = str(body.get("platform") or "").strip()
    from web.music_qr import start_qr

    try:
        data = await asyncio.to_thread(start_qr, platform)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, **data})


@router.get("/api/music/qr")
async def lobby_music_qr_poll(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    platform = str(request.query_params.get("platform") or "").strip()
    from web.music_qr import poll_qr

    try:
        data = await asyncio.to_thread(poll_qr, platform)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
    return JSONResponse({"ok": True, **data})


@router.post("/api/leave")
async def lobby_leave(request: Request):
    rejected = _reject_remote(request)
    if rejected is not None:
        return rejected
    _sender, music = _runtime()
    if music is None or not hasattr(music, "leave_voice_channel"):
        return JSONResponse({"ok": False, "error": "语音模块还没准备好"}, status_code=503)
    await music.leave_voice_channel()
    return JSONResponse({"ok": True, "message": "已离开语音频道"})
