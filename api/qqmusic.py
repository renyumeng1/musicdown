"""
QQ音乐API统一封装
使用qqmusic-api-python库提供统一的音乐数据接口
"""
import asyncio
import json
import re
from typing import Dict, List, Optional
from pathlib import Path
from urllib.parse import urljoin

import httpx

from utils.logger import logger
from utils.quality import best_available_fallback_qualities, canonical_quality
from utils.app_paths import get_app_data_dir, get_credential_file_path, get_config_file_path

try:
    from qqmusic_api import search, song, album, songlist, lyric, login, recommend
    from qqmusic_api.utils.credential import Credential
    from qqmusic_api.utils.network import RequestGroup
    from qqmusic_api.exceptions.api_exception import ResponseCodeError
    from qqmusic_api.login import (
        QRLoginType, QRCodeLoginEvents, PhoneLoginEvents,
        get_qrcode, check_qrcode, send_authcode, phone_authorize
    )
    QQMUSIC_API_AVAILABLE = True
except ImportError:
    QQMUSIC_API_AVAILABLE = False
    logger.warning("警告: qqmusic-api-python 未安装")


class QQMusicAPI:
    """QQ音乐API统一封装类"""

    _DEFAULT_QIMEI36 = "6c9d3cd110abca9b16311cee10001e717614"

    def __init__(self):
        if not QQMUSIC_API_AVAILABLE:
            raise ImportError(
                "qqmusic-api-python 库未安装，请先安装: pip install qqmusic-api-python")

        self.credential: Optional[Credential] = None
        # 使用可写路径确保在任何环境下都能正确读写凭证文件
        self.credential_file = get_credential_file_path()
        self._configure_qqmusic_api_runtime()
        self._load_credential_basic()

    def _qimei_store_path(self) -> Path:
        return get_app_data_dir() / "cache" / "qimei36.txt"

    def _read_stored_qimei36(self) -> str:
        try:
            path = self._qimei_store_path()
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def _store_qimei36(self, q36: str) -> None:
        q36 = (q36 or "").strip()
        if not q36:
            return
        try:
            path = self._qimei_store_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(q36, encoding="utf-8")
        except Exception:
            pass

    def _configure_qqmusic_api_runtime(self) -> None:
        """修正三方库的缓存路径/会话初始化行为，避免在 macOS .app 内写入导致权限/签名问题。"""
        try:
            from qqmusic_api.utils import device as qq_device

            # 默认 device.json 位于 site-packages 内部，打包后会落在 .app 里，写入会导致权限失败/签名失效。
            qq_device.device_path = get_app_data_dir() / "cache" / "qqmusic_device.json"
        except Exception:
            pass

        try:
            from qqmusic_api.utils import session as qq_session

            if getattr(qq_session, "_musicdown_qimei_patched", False):
                return

            original_get_qimei = qq_session.get_qimei

            def patched_get_qimei(version: str):  # type: ignore[no-redef]
                stored = self._read_stored_qimei36()
                if stored and len(stored) == 36:
                    return {"q16": "", "q36": stored}

                try:
                    res = original_get_qimei(version)
                    q36 = (res or {}).get("q36") if isinstance(res, dict) else ""
                    if q36:
                        self._store_qimei36(str(q36))
                    return res
                except Exception as e:
                    logger.warning(f"获取 QIMEI 失败，使用默认值兜底: {e}")
                    q36 = self._DEFAULT_QIMEI36
                    self._store_qimei36(q36)
                    return {"q16": "", "q36": q36}

            qq_session.get_qimei = patched_get_qimei  # type: ignore[assignment]
            qq_session._musicdown_qimei_patched = True  # type: ignore[attr-defined]
        except Exception:
            pass

    def _load_credential_basic(self):
        """同步读取凭证（不判断有效期）"""
        if self.credential_file.exists():
            try:
                with open(self.credential_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.credential = Credential.from_cookies_dict(data)
                    logger.info(
                        f"已加载本地登录凭证: {getattr(self.credential, 'musicid', None)}")
            except Exception as e:
                logger.error(f"加载登录凭证失败: {e}")
                self.credential = None

    async def validate_credential(self):
        """异步校验并自动刷新凭证，无法刷新时清理"""
        if not self.credential:
            return False

        try:
            # 为确保在新的事件循环中调用时不会复用旧的 Session
            from qqmusic_api.utils.session import clear_session
            clear_session()
            if await self.credential.is_expired():
                logger.warning("凭证已过期，尝试自动刷新...")
                if await self.credential.can_refresh():
                    await self.credential.refresh()
                    self.save_credential(self.credential)
                    logger.info("凭证刷新成功！")
                    return True
                else:
                    logger.warning("凭证无法刷新，已清除")
                    self.credential = None
                    if self.credential_file.exists():
                        self.credential_file.unlink()
                    return False
            else:
                logger.info("凭证有效")
                return True
        except Exception as e:
            logger.error(f"校验凭证时出错: {e}")
            self.credential = None
            if self.credential_file.exists():
                self.credential_file.unlink()
            return False

    async def is_logged_in(self) -> bool:
        """异步判断登录状态，并保证凭证有效"""
        return await self.validate_credential()

    def save_credential(self, credential: Credential):
        """保存登录凭证"""
        self.credential = credential
        try:
            # 确保目录存在
            self.credential_file.parent.mkdir(parents=True, exist_ok=True)

            data = credential.as_dict()
            with open(self.credential_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"登录凭证已保存: {credential.musicid}")
        except Exception as e:
            logger.error(f"保存登录凭证失败: {e}")

    def logout(self):
        """退出登录"""
        self.credential = None
        if self.credential_file.exists():
            self.credential_file.unlink()
        logger.info("登录凭证已清除")

    def _build_qqmusic_cookies(self) -> httpx.Cookies | None:
        """构造访问 QQ 音乐页面所需的 Cookie（用于解析分享链接等网页请求）"""
        if not self.credential:
            return None
        if not getattr(self.credential, "musicid", 0) or not getattr(self.credential, "musickey", ""):
            return None

        cookies = httpx.Cookies()
        cookies.set("uin", str(self.credential.musicid), domain=".qq.com")
        cookies.set("qqmusic_key", self.credential.musickey, domain=".qq.com")
        cookies.set("qm_keyst", self.credential.musickey, domain=".qq.com")
        cookies.set("tmeLoginType", str(getattr(self.credential, "login_type", 0)), domain=".qq.com")
        return cookies

    async def _resolve_share_url(self, url: str, *, max_hops: int = 8) -> str:
        """尽可能解析 QQ 音乐分享短链，返回最终可解析的 URL。

        说明：
        - 会处理 3xx 跳转
        - 也会尝试解析 HTML 中的 meta refresh / JS 跳转（部分 QQ 分享页会用这种方式跳转）
        """
        current_url = url.strip()
        if not current_url:
            return current_url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        cookies = self._build_qqmusic_cookies()

        async with httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            follow_redirects=False,
            timeout=httpx.Timeout(10.0, connect=10.0),
        ) as client:
            for _ in range(max_hops):
                try:
                    resp = await client.get(current_url)
                except Exception as e:
                    logger.warning(f"解析分享链接失败: {e}")
                    return current_url

                # 3xx 跳转
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("location") or resp.headers.get("Location")
                    if not location:
                        return str(resp.url)
                    current_url = urljoin(str(resp.url), location)
                    continue

                # 某些页面 200 但用 meta refresh 或 JS 跳转
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type.lower():
                    text = resp.text or ""

                    # meta refresh: <meta http-equiv="refresh" content="0;url=...">
                    m = re.search(
                        r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\'>]+)',
                        text,
                        re.IGNORECASE,
                    )
                    if m:
                        next_url = m.group(1).strip()
                        current_url = urljoin(str(resp.url), next_url)
                        continue

                    # JS redirect patterns
                    js_patterns = [
                        r'location\.href\s*=\s*["\']([^"\']+)["\']',
                        r'window\.location\.href\s*=\s*["\']([^"\']+)["\']',
                        r'window\.location\s*=\s*["\']([^"\']+)["\']',
                        r'top\.location\.href\s*=\s*["\']([^"\']+)["\']',
                    ]
                    for pat in js_patterns:
                        jm = re.search(pat, text, re.IGNORECASE)
                        if jm:
                            next_url = jm.group(1).strip()
                            current_url = urljoin(str(resp.url), next_url)
                            break
                    else:
                        return str(resp.url)
                    continue

                return str(resp.url)

        return current_url

    @staticmethod
    def _extract_playlist_id(url: str) -> int | None:
        """从 URL 中尽可能提取歌单 ID（disstid/id 等）"""
        if not url:
            return None

        patterns = [
            r"/playlistDetail/(\d+)",
            r"/playlist/(\d+)",
            r"/songlist/(\d+)",
            r"taoge\.html[^#]*[?&]id=(\d+)",
            r"[?&](?:id|disstid|dissid|songlist_id|playlist_id)=(\d+)",
        ]
        for pat in patterns:
            m = re.search(pat, url, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    continue
        return None

    async def playlist_from_link(self, url: str) -> Dict:
        """从分享链接解析歌单并返回歌曲列表（支持短链）"""
        if not url or not url.strip():
            return {"code": -1, "error": "链接不能为空"}

        # 确保三方库缓存路径已修正（防止写入 .app 内部导致问题）
        self._configure_qqmusic_api_runtime()

        resolved = await self._resolve_share_url(url)
        playlist_id = self._extract_playlist_id(resolved) or self._extract_playlist_id(url)
        if not playlist_id:
            return {"code": -1, "error": f"无法从链接解析歌单ID: {resolved}"}

        try:
            detail = await songlist.get_detail(
                songlist_id=playlist_id,
                dirid=0,
                num=100,
                page=1,
                onlysong=False,
                tag=False,
                userinfo=False,
                credential=self.credential,
            )
            dirinfo = detail.get("dirinfo", {}) if isinstance(detail, dict) else {}
            playlist_name = (
                dirinfo.get("title")
                or dirinfo.get("dirname")
                or dirinfo.get("name")
                or f"歌单 {playlist_id}"
            )

            songs = await self._fetch_songlist_songs(playlist_id, dirid=0)
            songs_count = len(songs) if isinstance(songs, list) else int(detail.get("total_song_num", 0) or 0)

            return {
                "code": 1,
                "data": {
                    "id": playlist_id,
                    "name": playlist_name,
                    "songs": songs if isinstance(songs, list) else [],
                    "songs_count": songs_count,
                    "resolved_url": resolved,
                },
            }
        except Exception as e:
            logger.error(f"从链接获取歌单失败: {e}")
            return {"code": -1, "error": str(e)}

    async def _fetch_songlist_songs(self, playlist_id: int, *, dirid: int = 0) -> list[dict]:
        """获取歌单全部歌曲列表（关闭 tag/userinfo，降低风控触发概率）。"""
        first = await songlist.get_detail(
            songlist_id=playlist_id,
            dirid=dirid,
            num=100,
            page=1,
            onlysong=True,
            tag=False,
            userinfo=False,
            credential=self.credential,
        )
        songs = list(first.get("songlist", []) or []) if isinstance(first, dict) else []
        total = int(first.get("total_song_num", len(songs)) or len(songs)) if isinstance(first, dict) else len(songs)

        if total <= 100:
            return songs

        rg = RequestGroup(credential=self.credential)
        # page 从 2 开始；每页 100 首
        for p in range(2, (total + 99) // 100 + 1):
            rg.add_request(
                songlist.get_detail,
                songlist_id=playlist_id,
                dirid=dirid,
                num=100,
                page=p,
                onlysong=True,
                tag=False,
                userinfo=False,
            )
        response = await rg.execute()
        for res in response:
            if isinstance(res, dict):
                songs.extend(res.get("songlist", []) or [])
        return songs

    async def daily_recommendations(self, fallback_url: str | None = None) -> Dict:
        """尝试获取账号的每日推荐歌曲（优先从推荐 Feed 中解析）。"""
        # 确保三方库缓存路径已修正（防止写入 .app 内部导致问题）
        self._configure_qqmusic_api_runtime()

        if not await self.is_logged_in():
            return {"code": -1, "error": "未登录或凭证已过期，请先登录"}

        def _contains_keywords(text: str) -> bool:
            t = (text or "").lower()
            keywords = ["每日", "30首", "今日推荐", "daily"]
            return any(k.lower() in t for k in keywords)

        def _walk(obj):
            if isinstance(obj, dict):
                yield obj
                for v in obj.values():
                    yield from _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    yield from _walk(item)

        try:
            feed = await recommend.get_home_feed(credential=self.credential)
        except Exception as e:
            logger.warning(f"获取推荐 Feed 失败: {e}")
            # Feed 拉取失败时也允许直接用兜底链接
            return await self._daily_fallback_from_link(fallback_url)

        # 收集所有可能的“每日推荐”候选歌单 ID（避免误选导致 500032）
        candidate_ids: list[int] = []
        seen: set[int] = set()

        for d in _walk(feed):
            title = ""
            for k in ("title", "name", "desc", "subtitle", "label"):
                if isinstance(d.get(k), str) and d.get(k):
                    title = d.get(k)
                    break
            if not title or not _contains_keywords(title):
                continue

            for id_key in ("disstid", "dissid", "songlist_id", "playlist_id", "id", "dirid"):
                val = d.get(id_key)
                pid: int | None = None
                if isinstance(val, int) and val > 0:
                    pid = val
                elif isinstance(val, str) and val.isdigit():
                    pid = int(val)
                if pid and pid not in seen:
                    candidate_ids.append(pid)
                    seen.add(pid)

        if not candidate_ids:
            return await self._daily_fallback_from_link(fallback_url)

        last_error: str | None = None
        for playlist_id in candidate_ids:
            try:
                # 每日推荐一般只有 30 首，直接取第一页即可；同时关闭 tag/userinfo 以降低风控触发概率。
                detail = await songlist.get_detail(
                    songlist_id=playlist_id,
                    dirid=0,
                    num=100,
                    page=1,
                    onlysong=True,
                    tag=False,
                    userinfo=False,
                    credential=self.credential,
                )

                dirinfo = detail.get("dirinfo", {}) if isinstance(detail, dict) else {}
                playlist_name = (
                    dirinfo.get("title")
                    or dirinfo.get("dirname")
                    or dirinfo.get("name")
                    or "每日推荐"
                )
                songs = detail.get("songlist", []) if isinstance(detail, dict) else []
                if songs and isinstance(songs, list):
                    return {
                        "code": 1,
                        "data": {
                            "id": playlist_id,
                            "name": playlist_name,
                            "songs": songs,
                            "songs_count": int(detail.get("total_song_num", len(songs)) or len(songs)),
                        },
                    }
            except ResponseCodeError as e:
                # 对于不符合预期的 code，尝试下一个候选 ID
                last_error = str(e)
                logger.warning(
                    "每日推荐候选歌单获取失败: %s (id=%s, req=%s, raw=%s)",
                    e,
                    playlist_id,
                    getattr(e, "data", None),
                    getattr(e, "raw", None),
                )
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"每日推荐候选歌单获取失败: {e} (id={playlist_id})")
                continue

        logger.error(f"获取每日推荐歌单失败: {last_error}")
        return await self._daily_fallback_from_link(fallback_url, last_error=last_error)

    async def _daily_fallback_from_link(self, fallback_url: str | None, *, last_error: str | None = None) -> Dict:
        # 兜底：优先使用调用方传入的分享链接，其次使用配置文件中的链接
        url = (fallback_url or "").strip()
        if not url:
            try:
                from utils.config import config as app_config
                url = getattr(app_config, "DAILY_RECOMMEND_URL", "") or ""
                url = url.strip()
            except Exception:
                url = ""

        if url:
            logger.info("使用每日推荐分享链接作为兜底")
            result = await self.playlist_from_link(url)
            if result.get("code") == 1:
                return result
            err = result.get("error") or "未知错误"
            if last_error and last_error not in str(err):
                err = f"{last_error}; fallback: {err}"
            return {"code": -1, "error": err}

        msg = (
            "未能获取每日推荐（可在 "
            f"{get_config_file_path()} 配置 daily_recommend.url 作为兜底）"
        )
        if last_error:
            msg = f"{msg}\n最后一次错误: {last_error}"
        return {"code": -1, "error": msg}

    async def search(self, keyword: str, limit: int = 10, page: int = 1) -> Dict:
        """搜索歌曲
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
            page: 页码
            
        Returns:
            搜索结果字典
        """
        try:
            limit = min(limit, 100)
            result = await search.search_by_type(
                keyword=keyword,
                search_type=search.SearchType.SONG,
                page=page,
                num=limit
            )
            logger.debug("search_song result: %s", result)
            return {
                "code": 0,
                "songs": result if isinstance(result, list) else [],
                "total": len(result) if isinstance(result, list) else 0
            }
        except Exception as e:
            logger.error(f"搜索歌曲失败: {e}")
            return {"code": -1, "songs": [], "total": 0, "error": str(e)}

    async def song_detail(self, song_mid: str) -> Dict:
        """获取歌曲详细信息
        
        Args:
            song_mid: 歌曲MID
            
        Returns:
            歌曲详细信息
        """
        try:
            # qqmusic_api.song 模块中并未提供 get_song_detail 方法，
            # 正确的接口为 get_detail
            result = await song.get_detail(song_mid)
            return {"code": 0, "data": result}
        except Exception as e:
            logger.error(f"获取歌曲详情失败: {e}")
            return {"code": -1, "data": None, "error": str(e)}

    async def song_url(self, song_mid: str, quality: str = "128", *, allow_fallback: bool = True) -> Dict:
        """获取歌曲下载链接
        
        Args:
            song_mid: 歌曲MID
            quality: 音质 (128/320/flac/ATMOS_51/ATMOS_2/MASTER等)
            allow_fallback: 是否启用相邻音质兜底（优先指定音质，不可用则尝试相邻更低/更高一档）
            
        Returns:
            下载链接信息
        """
        try:
            requested = canonical_quality(quality) or "128"

            # 质量映射到 SongFileType 枚举
            quality_map = {
                "m4a": song.SongFileType.ACC_192,
                "128": song.SongFileType.MP3_128,
                "320": song.SongFileType.MP3_320,
                "flac": song.SongFileType.FLAC,
                "ATMOS_51": song.SongFileType.ATMOS_51,
                "ATMOS_2": song.SongFileType.ATMOS_2,
                "MASTER": song.SongFileType.MASTER,
                "ogg": song.SongFileType.OGG_320,
            }

            candidates = best_available_fallback_qualities(requested) if allow_fallback else [requested]
            if not candidates:
                candidates = ["128"]

            last_error: str | None = None
            for q in candidates:
                file_type = quality_map.get(q)
                if not file_type:
                    continue
                try:
                    result = await song.get_song_urls([song_mid], file_type, credential=self.credential)
                except Exception as e:
                    last_error = str(e)
                    continue

                logger.debug("song_url result (%s): %s", q, result)
                if isinstance(result, dict) and song_mid in result:
                    url = result[song_mid]
                    if url:
                        return {"code": 0, "url": url, "quality": q}

            return {
                "code": -1,
                "url": "",
                "error": last_error or "Cannot fetch song URL",
                "tried": candidates,
            }
        except Exception as e:
            logger.error(f"获取歌曲URL失败: {e}")
            return {'code': -1, 'url': '', 'error': str(e)}

    async def search_album(self, keyword: str, limit: int = 10, page: int = 1) -> Dict:
        """搜索专辑
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
            page: 页码
            
        Returns:
            专辑搜索结果
        """
        try:
            limit = min(limit, 100)
            result = await search.search_by_type(
                keyword=keyword,
                search_type=search.SearchType.ALBUM,
                page=page,
                num=limit
            )
            logger.debug("search_album result: %s", result)
            return {
                "code": 0,
                "albums": result if isinstance(result, list) else [],
                "total": len(result) if isinstance(result, list) else 0
            }
        except Exception as e:
            logger.error(f"搜索专辑失败: {e}")
            return {"code": -1, "albums": [], "total": 0, "error": str(e)}

    async def album_detail(self, album_mid: str) -> Dict:
        """获取专辑详细信息
        
        Args:
            album_mid: 专辑MID
            
        Returns:
            专辑详细信息和歌曲列表
        """
        try:
            result = await album.get_song(album_mid, num=100, page=1)
            logger.debug("album_detail result: %s", result)
            return {
                "code": 0,
                "songs": result if isinstance(result, list) else [],
                "songList": result if isinstance(result, list) else [],
                "total": len(result) if isinstance(result, list) else 0
            }
        except Exception as e:
            logger.error(f"获取专辑详情失败: {e}")
            return {"code": -1, "songs": [], "songList": [], "total": 0, "error": str(e)}

    async def search_playlist(self, keyword: str, limit: int = 10, page: int = 1) -> Dict:
        """搜索歌单
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
            page: 页码
            
        Returns:
            歌单搜索结果
        """
        try:
            limit = min(limit, 100)
            result = await search.search_by_type(
                keyword=keyword,
                search_type=search.SearchType.SONGLIST,
                page=page,
                num=limit
            )
            logger.debug("search_playlist result: %s", result)
            return {
                "code": 0,
                "playlists": result if isinstance(result, list) else [],
                "total": len(result) if isinstance(result, list) else 0
            }
        except Exception as e:
            logger.error(f"搜索歌单失败: {e}")
            return {"code": -1, "playlists": [], "total": 0, "error": str(e)}

    async def playlist_detail(self, playlist_id: int) -> Dict:
        """获取歌单详细信息

        Args:
            playlist_id: 歌单ID

        Returns:
            歌单详细信息和歌曲列表
        """
        try:
            # 根据文档，get_songlist返回的是歌曲列表，不是字典
            result = await songlist.get_songlist(playlist_id, dirid=0)

            if isinstance(result, list):
                # 正常情况：返回歌曲列表
                return {
                    "code": 0,
                    "songs": result,
                    "songList": result,
                    "total": len(result)
                }
            else:
                logger.warning(f"歌单详情返回了意外的数据类型: {type(result)}")
                return {"code": -1, "songs": [], "songList": [], "total": 0, "error": f"意外的数据类型: {type(result)}"}

        except Exception as e:
            logger.error(f"获取歌单详情失败: {e}")
            return {"code": -1, "songs": [], "songList": [], "total": 0, "error": str(e)}

    async def get_lyrics(self, song_mid: str) -> Dict:
        """获取歌词
        
        Args:
            song_mid: 歌曲MID
            
        Returns:
            歌词信息
        """
        try:
            result = await lyric.get_lyric(song_mid, trans=True, roma=True)
            logger.debug("lyric result: %s", result)
            if isinstance(result, dict):
                return {
                    "code": 0,
                    "lyric": result.get("lyric", ""),
                    "trans": result.get("trans", ""),
                    "roma": result.get("roma", "")
                }
            else:
                return {
                    "code": 0,
                    "lyric": str(result) if result else "",
                    "trans": "",
                    "roma": ""
                }
        except Exception as e:
            logger.error(f"获取歌词失败: {e}")
            return {"code": -1, "lyric": "", "trans": "", "roma": "", "error": str(e)}

    # 登录相关方法
    async def login_with_qr(self, login_type: str = "QQ", callback=None) -> tuple:
        """二维码登录

        Args:
            login_type: 登录类型 ("QQ" 或 "WX")
            callback: 回调函数

        Returns:
            (成功状态, 二维码数据, 错误信息)
        """
        try:
            qr_type = QRLoginType.QQ if login_type.upper() == "QQ" else QRLoginType.WX
            qr = await get_qrcode(qr_type)

            logger.info("二维码已生成，准备显示")

            if callback:
                callback("qr_generated", qr.data)

            max_attempts = 60  # 最多检查60次，约2分钟
            attempt = 0

            while attempt < max_attempts:
                event, credential = await check_qrcode(qr)

                if event == QRCodeLoginEvents.DONE:
                    self.save_credential(credential)
                    if callback:
                        callback("login_success", credential)
                    return True, qr.data, ""

                elif event == QRCodeLoginEvents.TIMEOUT:
                    error_msg = "二维码已过期"
                    logger.error(error_msg)
                    if callback:
                        callback("timeout", error_msg)
                    return False, qr.data, error_msg

                elif event == QRCodeLoginEvents.REFUSE:
                    error_msg = "用户拒绝登录"
                    logger.error(error_msg)
                    if callback:
                        callback("refused", error_msg)
                    return False, qr.data, error_msg

                elif event == QRCodeLoginEvents.SCAN:
                    logger.info("等待扫描二维码")
                    if callback:
                        callback("waiting_scan", "等待扫描二维码")

                elif event == QRCodeLoginEvents.CONF:
                    logger.info("已扫码未确认登录")
                    if callback:
                        callback("waiting_confirm", "已扫码未确认登录")

                else:
                    logger.warning("出现未知状态")

                await asyncio.sleep(2)
                attempt += 1

            error_msg = "登录超时，请重试"
            if callback:
                callback("timeout", error_msg)
            return False, qr.data, error_msg

        except Exception as e:
            error_msg = f"二维码登录失败: {e}"
            logger.error(error_msg)
            if callback:
                callback("error", error_msg)
            return False, b"", error_msg



    async def login_with_phone(self, phone: int, country_code: int = 86, callback=None) -> tuple:
        """手机号登录

        Args:
            phone: 手机号
            country_code: 国家代码
            callback: 回调函数

        Returns:
            (成功状态, 错误信息)
        """
        try:
            # 发送验证码
            if callback:
                callback("sending_code", "正在发送验证码...")

            event, info = await send_authcode(phone, country_code)

            if event == PhoneLoginEvents.CAPTCHA:
                error_msg = f"需要验证，访问链接: {info}"
                logger.error(error_msg)
                if callback:
                    callback("captcha_required", error_msg)
                return False, error_msg

            elif event == PhoneLoginEvents.FREQUENCY:
                error_msg = "操作过于频繁，请稍后再试"
                logger.error(error_msg)
                if callback:
                    callback("frequency_limit", error_msg)
                return False, error_msg

            logger.info("验证码已发送")
            if callback:
                callback("code_sent", "验证码已发送，请输入验证码")

            # 这里需要通过回调获取验证码
            if callback:
                auth_code = callback("get_auth_code", "请输入验证码")
                if not auth_code:
                    return False, "未输入验证码"
            else:
                # 命令行环境的备用方案
                auth_code = input("请输入验证码: ").strip()

            # 执行登录
            if callback:
                callback("authorizing", "正在验证...")

            credential = await phone_authorize(phone, int(auth_code), country_code)
            self.save_credential(credential)

            if callback:
                callback("login_success", credential)
            return True, ""

        except Exception as e:
            error_msg = f"手机号登录失败: {e}"
            logger.error(error_msg)
            if callback:
                callback("error", error_msg)
            return False, error_msg

    def get_user_info(self) -> Optional[Dict]:
        """获取用户信息"""
        if self.credential:
            return {
                'musicid': self.credential.musicid,
                'uin': getattr(self.credential, 'uin', ''),
                'logged_in': True
            }
        return {'logged_in': False}
