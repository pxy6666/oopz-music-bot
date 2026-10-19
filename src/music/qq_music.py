"""QQ 音乐平台实现。
配置 QQ_MUSIC_CONFIG.base_url 指向该服务地址。
"""

from __future__ import annotations

from core.async_http import ManagedHttpClient
from core.http_constants import HTTP_TIMEOUT_DEFAULT
from core.logger_config import get_logger

logger = get_logger("QQMusic")

# 专辑封面 CDN 模板，{mid} 为专辑 mid。
_ALBUM_COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R300x300M000{mid}.jpg"


def _url_from_payload(data: dict | None, song_id: str = "") -> str:
    """从播放接口里取出真实音频地址。320 拿不到时这里是空字符串。"""
    if not isinstance(data, dict):
        return ""
    body = data.get("data") if isinstance(data.get("data"), dict) else data
    direct = str(body.get("url") or "")
    if direct:
        return direct
    play_url = body.get("playUrl")
    if isinstance(play_url, dict):
        preferred = play_url.get(song_id) if song_id else None
        if isinstance(preferred, dict) and preferred.get("url"):
            return str(preferred["url"])
        for item in play_url.values():
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return ""


_cached_config: dict | None = None


def _first_named(data: dict | None, id_keys: tuple[str, ...], name_keys: tuple[str, ...]) -> dict | None:
    """从搜索结果里取出第一条带编号的歌单或专辑。"""
    if not isinstance(data, dict):
        return None
    candidates = []
    for key in ("list", "data", "album", "playlists"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict):
            for nested in ("list", "album", "playlists"):
                inner = value.get(nested)
                if isinstance(inner, list):
                    candidates.extend(inner)
    response = data.get("response")
    if isinstance(response, dict):
        for key in ("data", "list", "album", "playlists"):
            inner = response.get(key)
            if isinstance(inner, list):
                candidates.extend(inner)
            elif isinstance(inner, dict):
                deeper = inner.get("list")
                if isinstance(deeper, list):
                    candidates.extend(deeper)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        item_id = ""
        for key in id_keys:
            if item.get(key):
                item_id = str(item.get(key))
                break
        if not item_id:
            continue
        name = ""
        for key in name_keys:
            if item.get(key):
                name = str(item.get(key))
                break
        return {"id": item_id, "name": name or item_id}
    return None


def _load_config() -> dict:
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    try:
        from config import QQ_MUSIC_CONFIG
        _cached_config = QQ_MUSIC_CONFIG
        return _cached_config
    except (ImportError, AttributeError):
        _cached_config = {}
        return _cached_config


class QQMusic:
    """QQ 音乐平台，实现 MusicPlatform 协议。"""

    name = "qq"
    display_name = "QQ音乐"

    def __init__(self):
        cfg = _load_config()
        self.enabled = cfg.get("enabled", False)
        self.base_url = str(cfg.get("base_url", "")).rstrip("/")
        self.cookie = cfg.get("cookie", "")
        self._http = ManagedHttpClient()
        if self.enabled and not self.base_url:
            logger.warning("QQ 音乐 API 地址未配置 (QQ_MUSIC_CONFIG.base_url)")

    async def _get(self, path: str, params: dict | None = None) -> dict | None:
        if not self.base_url:
            return None
        try:
            headers = {}
            query = dict(params or {})
            if self.cookie:
                headers["Cookie"] = self.cookie
                query.setdefault("cookie", self.cookie)
            return await self._http.request_json(
                "GET",
                f"{self.base_url}{path}",
                params=query,
                headers=headers,
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
        except Exception as e:
            logger.error("QQ 音乐 API 请求失败: %s", e)
            return None

    async def search(self, keyword: str, limit: int = 1) -> dict | None:
        data = await self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": 1})
        if not data:
            return None
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        if not songs:
            data2 = await self._get("/search", params={"key": keyword, "limit": limit, "page": 1})
            if data2:
                songs = (data2.get("data") or {}).get("list") or []
        if not songs:
            return None
        return self._parse_song(songs[0])

    async def search_many(self, keyword: str, limit: int = 10, offset: int = 0) -> list[dict]:
        page = (offset // max(limit, 1)) + 1
        data = await self._get("/getSearchByKey", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            data = await self._get("/search", params={"key": keyword, "limit": limit, "page": page})
        if not data:
            return []
        songs = (data.get("response") or data.get("data") or {}).get("song", {}).get("list") or \
                (data.get("data") or {}).get("list") or []
        return [p for s in songs if (p := self._parse_song(s))]

    async def get_song_url(self, song_id) -> str | None:
        song_id = str(song_id)
        # 先要 320kbps。这个账号听不了时接口给空链接，再退回默认档。
        for path, params in (
            ("/getMusicPlay", {"songmid": song_id, "quality": "320"}),
            ("/getMusicPlay", {"songmid": song_id}),
            ("/song/url", {"id": song_id}),
        ):
            url = _url_from_payload(await self._get(path, params=params), song_id)
            if url:
                return url
        return None

    async def get_song_detail(self, song_id) -> dict | None:
        data = await self._get("/getSongInfo", params={"songmid": str(song_id)})
        if not data or not data.get("data"):
            return None
        return self._parse_song(data["data"])

    async def get_lyric(self, song_id) -> str | None:
        data = await self._get("/getLyric", params={"songmid": str(song_id)})
        if not data:
            return None
        lyric = (data.get("data") or {}).get("lyric") or data.get("lyric") or ""
        return lyric if lyric and "[" in lyric else None

    async def summarize(self, keyword: str) -> dict:
        song = await self.search(keyword)
        if not song:
            return {"code": "error", "message": f"QQ音乐未找到: {keyword}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = await self.get_song_url(mid)
        if not url:
            return {"code": "error", "message": f"QQ音乐无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        msg = (
            f"歌曲: {song['name']}\n"
            f"歌手: {song['artists']}\n"
            f"专辑: {song['album']}\n"
            f"时长: {song['durationText']}"
        )
        return {"code": "success", "message": msg, "data": song}

    async def summarize_by_id(self, song_id) -> dict:
        song = await self.get_song_detail(song_id)
        if not song:
            return {"code": "error", "message": f"QQ音乐无法获取歌曲信息: {song_id}", "data": None}
        mid = song.get("mid") or song.get("id")
        url = await self.get_song_url(mid)
        if not url:
            return {"code": "error", "message": f"QQ音乐无法获取播放链接: {song['name']}", "data": None}
        song["url"] = url
        return {"code": "success", "message": "", "data": song}

    async def search_playlist(self, keyword: str) -> dict | None:
        data = await self._get("/search", params={"key": keyword, "t": 3, "page": 1, "limit": 1})
        item = _first_named(data, ("dissid", "disstid", "id"), ("dissname", "name"))
        if item is None:
            return None
        return item

    async def search_album(self, keyword: str) -> dict | None:
        data = await self._get("/search", params={"key": keyword, "t": 2, "page": 1, "limit": 1})
        return _first_named(data, ("albummid", "mid", "id"), ("albumName", "name"))

    async def get_playlist_songs(self, playlist_id: str) -> list[dict]:
        data = await self._get("/getSongListDetail", params={"disstid": playlist_id})
        cdlist = ((data or {}).get("response") or {}).get("cdlist") or []
        songs = (cdlist[0].get("songlist") if cdlist else None) or []
        return [parsed for song in songs if (parsed := self._parse_song(song))][:1000]

    async def get_album_songs(self, album_id: str) -> list[dict]:
        data = await self._get("/getAlbumInfo", params={"albummid": album_id})
        response = (data or {}).get("response") or {}
        songs = ((response.get("data") or {}).get("list") if isinstance(response, dict) else None) or []
        return [parsed for song in songs if (parsed := self._parse_song(song))][:1000]

    async def close(self) -> None:
        await self._http.close()

    def _parse_song(self, song: dict) -> dict | None:
        if not song:
            return None
        song_id = song.get("songmid") or song.get("mid") or song.get("id") or ""
        if not song_id:
            return None
        singers = song.get("singer") or []
        if isinstance(singers, list):
            artists = " / ".join(s.get("name") or "未知" for s in singers) or "未知"
        else:
            artists = str(singers)
        album = song.get("album") or {}
        album_name = album.get("name") or "" if isinstance(album, dict) else str(album)
        duration_s = int(song.get("interval") or song.get("duration") or 0)
        duration_ms = duration_s * 1000
        cover = ""
        if isinstance(album, dict) and album.get("mid"):
            cover = _ALBUM_COVER_URL.format(mid=album["mid"])
        return {
            "id": song_id,
            "mid": song_id,
            "name": song.get("songname") or song.get("name") or "未知歌曲",
            "artists": artists,
            "album": album_name,
            "duration": duration_ms,
            "durationText": f"{duration_s // 60}:{duration_s % 60:02d}",
            "cover": cover,
        }
