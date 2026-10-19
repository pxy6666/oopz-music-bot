"""与应用事件循环共存的 QQ 音乐 API 子进程。"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from core.http_constants import HTTP_TIMEOUT_HEALTH
from core.logger_config import setup_logger

logger = setup_logger("QqApiRuntime")


class QqApiRuntime:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._stop_event = asyncio.Event()

    @staticmethod
    def _project_root() -> Path:
        from core.paths import PROJECT_ROOT_PATH

        return PROJECT_ROOT_PATH

    def _api_dir(self) -> Path:
        return self._project_root() / "qq-music-api"

    def _base_url(self) -> str:
        try:
            from config import QQ_MUSIC_CONFIG

            return str(QQ_MUSIC_CONFIG.get("base_url") or "http://127.0.0.1:3300").rstrip("/")
        except Exception:
            return "http://127.0.0.1:3300"

    def _should_start(self) -> bool:
        try:
            from config import QQ_MUSIC_CONFIG

            return bool(QQ_MUSIC_CONFIG.get("auto_start", True))
        except Exception:
            return True

    async def start(self) -> None:
        self._stop_event.clear()
        if not self._should_start():
            return
        if await self._api_is_ready():
            logger.info("QQ 音乐 API 已在运行，跳过重复启动。")
            return
        api_dir = self._api_dir()
        if not (api_dir / "start.js").is_file() or not (api_dir / "node_modules").is_dir():
            logger.warning(
                "QQ 音乐接口还没安装。请在 qq-music-api 目录执行 npm install 后重启机器人。"
            )
            return
        env = os.environ.copy()
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            env.pop(key, None)
        port = urlparse(self._base_url()).port or 3300
        env["QQ_MUSIC_PORT"] = str(port)
        env["PORT"] = str(port)
        logger.info("正在启动 QQ 音乐 API: %s", self._base_url())
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._find_node_binary(),
                "start.js",
                cwd=str(api_dir),
                env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
        except Exception as exc:
            logger.warning("启动 QQ 音乐 API 失败: %s", exc)
            self._process = None
            return
        await self._wait_until_ready()

    async def _api_is_ready(self) -> bool:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_HEALTH)
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout, trust_env=False) as session,
                session.get(f"{self._base_url()}/") as response,
            ):
                return response.status < 500
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False

    async def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=max(0.0, timeout))
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        except ProcessLookupError:
            pass
        except Exception as exc:
            logger.warning("停止 QQ 音乐 API 时出现异常: %s", exc)
        finally:
            logger.info("QQ 音乐 API 已停止。")

    @staticmethod
    def _find_node_binary() -> str:
        node_cmd = shutil.which("node")
        if node_cmd:
            return node_cmd
        portable = (
            Path(__file__).resolve().parents[4]
            / "ts3-music-bot"
            / ".node"
            / "node-v22.23.3-win-x64"
            / "node.exe"
        )
        if portable.is_file():
            return str(portable)
        return "node"

    async def _wait_until_ready(self) -> None:
        for _ in range(30):
            if self._stop_event.is_set():
                return
            process = self._process
            if process is not None and process.returncode is not None:
                detail = ""
                if process.stderr is not None:
                    try:
                        raw = await process.stderr.read()
                        detail = raw.decode("utf-8", errors="replace").strip()
                    except Exception:
                        detail = ""
                logger.warning(
                    "QQ 音乐 API 子进程已退出 (code=%s) %s",
                    process.returncode,
                    detail[:300],
                )
                return
            if await self._api_is_ready():
                logger.info("QQ 音乐 API 已就绪: %s", self._base_url())
                return
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.5)
        logger.warning("QQ 音乐 API 启动超时。登录页上的 QQ 二维码会连不上。")
