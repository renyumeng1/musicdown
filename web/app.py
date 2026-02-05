from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import (
    HTMLResponse,
    StreamingResponse,
    FileResponse,
    RedirectResponse,
    JSONResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio
import io
import os
import time
import zipfile

import sys
# 确保可以导入项目根目录的模块
if __name__ == "__main__":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from api.qqmusic import QQMusicAPI
from downloader.music_downloader import MusicDownloader
from utils.config import config
from utils.formatters import format_singers, format_interval, clean_html_tags
from utils.logger import logger

app = FastAPI(title="Music Downloader Web")
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

qq_api = QQMusicAPI()
music_downloader = MusicDownloader()

qr_bytes = b""
login_status = "not_started"
login_task: asyncio.Task | None = None

# 应用启动事件


@app.on_event("startup")
async def startup_event():
    # 启动时异步验证凭证
    try:
        await qq_api.validate_credential()
        global login_status
        if await qq_api.is_logged_in():
            login_status = "success"
            logger.info("已成功加载登录凭证")
        else:
            login_status = "not_started"
            logger.warning("未找到有效的登录凭证或凭证已过期")
    except Exception as e:
        logger.error(f"验证凭证时出错: {e}")
        login_status = "not_started"


def login_callback(event: str, data):
    global qr_bytes, login_status
    if event == "qr_generated":
        qr_bytes = data
        login_status = "waiting_scan"
    elif event == "waiting_scan":
        login_status = "waiting_scan"
    elif event == "waiting_confirm":
        login_status = "waiting_confirm"
    elif event == "login_success":
        login_status = "success"
        # 登录成功后更新凭证并保存到文件
        qq_api.save_credential(data)
    elif event in {"timeout", "refused", "error"}:
        login_status = event


def get_available_formats(song: dict) -> dict:
    """Return available audio formats with their keys and human readable names"""
    if not song.get("file"):
        return {"readable": "未知", "formats": []}

    file_info = song["file"]
    available = []
    format_map = {
        "size_48aac": {"name": "M4A 48k", "quality": "m4a", "ext": "m4a"},
        "size_96aac": {"name": "M4A 96k", "quality": "m4a", "ext": "m4a"},
        "size_192aac": {"name": "M4A 192k", "quality": "m4a", "ext": "m4a"},
        "size_128mp3": {"name": "MP3 128k", "quality": "128", "ext": "mp3"},
        "size_320mp3": {"name": "MP3 320k", "quality": "320", "ext": "mp3"},
        "size_96ogg": {"name": "OGG 96k", "quality": "ogg", "ext": "ogg"},
        "size_192ogg": {"name": "OGG 192k", "quality": "ogg", "ext": "ogg"},
        "size_flac": {"name": "FLAC", "quality": "flac", "ext": "flac"},
    }

    for key, info in format_map.items():
        if file_info.get(key, 0) > 0:
            available.append(info)

    size_new = file_info.get("size_new", [])
    if len(size_new) >= 6:
        if size_new[0] > 0:
            available.append({"name": "母带", "quality": "MASTER", "ext": "flac"})
        if size_new[1] > 0:
            available.append(
                {"name": "全景声", "quality": "ATMOS_2", "ext": "flac"})
        if size_new[2] > 0:
            available.append({"name": "臻品音质", "quality": "ATMOS_51", "ext": "flac"})

    readable = ", ".join([fmt["name"]
                         for fmt in available]) if available else "无可用格式"
    return {"readable": readable, "formats": available}

def _as_web_song(song: dict) -> dict:
    formats_data = get_available_formats(song)
    return {
        "name": clean_html_tags(song.get("name", "")),
        "mid": song.get("mid", ""),
        "singers": format_singers(song.get("singer", [])),
        "album_name": clean_html_tags(song.get("album", {}).get("name", "")),
        "duration": format_interval(song.get("interval", 0)),
        "formats": formats_data["readable"],
        "available_formats": formats_data["formats"],
    }

def _safe_filename(name: str, fallback: str) -> str:
    safe = "".join(c for c in (name or "") if c.isalnum() or c in " -_.").strip()
    return safe or fallback

async def _download_songs_concurrently(
    songs: list[dict],
    download_dir: Path,
    quality: str,
    *,
    concurrency: int = 4,
) -> list[Path]:
    concurrency = max(1, min(int(concurrency or 4), 10))
    semaphore = asyncio.Semaphore(concurrency)
    downloaded_files: list[Path] = []

    async def _download_one(song_info: dict) -> Path | None:
        async with semaphore:
            try:
                return await music_downloader.download_song(song_info, download_dir, quality)
            except Exception as e:
                logger.warning(f"下载歌曲失败: {song_info.get('name')}: {e}")
                return None

    tasks = [asyncio.create_task(_download_one(song_info)) for song_info in songs]
    for finished in asyncio.as_completed(tasks):
        fp = await finished
        if fp:
            downloaded_files.append(fp)

    return downloaded_files

async def _require_login() -> bool:
    return await qq_api.is_logged_in()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not await qq_api.is_logged_in():
        return RedirectResponse("/login")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "use_light_mode": config.LIGHT_DOWNLOAD_MODE},
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    # 如果已经登录，直接重定向到首页
    if await qq_api.is_logged_in():
        return RedirectResponse("/")

    global login_task, login_status
    if login_task is None or login_task.done():
        login_status = "starting"
        login_task = asyncio.create_task(qq_api.login_with_qr(callback=login_callback))
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login/qrcode")
async def login_qrcode():
    if qr_bytes:
        return StreamingResponse(io.BytesIO(qr_bytes), media_type="image/png")
    return Response(status_code=404)


@app.get("/login/status")
async def login_status_api():
    # 如果登录成功，确保凭证已正确加载
    if login_status == "success":
        await qq_api.validate_credential()
    return {"status": login_status, "user": qq_api.get_user_info()}


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = ""):
    if not q:
        return templates.TemplateResponse(
            "search.html",
            {
                "request": request,
                "songs": [],
                "use_light_mode": config.LIGHT_DOWNLOAD_MODE,
            },
        )
    result = await qq_api.search(q, limit=20, page=1)
    songs = [_as_web_song(s) for s in result.get("songs", [])]
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "songs": songs,
            "query": q,
            "use_light_mode": config.LIGHT_DOWNLOAD_MODE,
            "default_quality": config.DEFAULT_QUALITY,
        },
    )


@app.get("/playlist", response_class=HTMLResponse)
async def playlist(request: Request, url: str = ""):
    if not await _require_login():
        return RedirectResponse("/login")

    playlist_name = None
    songs = []
    error = None
    resolved_url = None

    if url:
        result = await qq_api.playlist_from_link(url)
        if result.get("code") == 1:
            data = result.get("data", {})
            playlist_name = clean_html_tags(str(data.get("name", "")))
            resolved_url = data.get("resolved_url")
            songs = [_as_web_song(s) for s in data.get("songs", []) if isinstance(s, dict)]
        else:
            error = result.get("error") or "获取歌单失败"

    return templates.TemplateResponse(
        "playlist.html",
        {
            "request": request,
            "url": url,
            "playlist_name": playlist_name,
            "resolved_url": resolved_url,
            "songs": songs,
            "error": error,
            "use_light_mode": config.LIGHT_DOWNLOAD_MODE,
            "default_quality": config.DEFAULT_QUALITY,
        },
    )


@app.get("/playlist/download_zip")
async def playlist_download_zip(url: str, quality: str | None = None, concurrency: int = 4):
    if not await _require_login():
        return RedirectResponse("/login")

    quality = quality or config.DEFAULT_QUALITY
    result = await qq_api.playlist_from_link(url)
    if result.get("code") != 1:
        return JSONResponse({"error": result.get("error", "获取歌单失败")}, status_code=400)

    data = result.get("data", {})
    playlist_id = data.get("id")
    playlist_name = clean_html_tags(str(data.get("name", "playlist")))
    songs = [s for s in data.get("songs", []) if isinstance(s, dict)]

    download_root = Path("downloads")
    download_dir = download_root / f"playlist_{playlist_id or int(time.time())}"
    download_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files = await _download_songs_concurrently(
        songs, download_dir, quality, concurrency=concurrency
    )

    if not downloaded_files:
        return JSONResponse({"error": "没有成功下载任何歌曲"}, status_code=500)

    zip_name = f"{_safe_filename(playlist_name, 'playlist')}_{int(time.time())}.zip"
    zip_path = download_root / zip_name

    def _build_zip():
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in downloaded_files:
                if fp.exists():
                    zf.write(fp, arcname=fp.name)

    await asyncio.to_thread(_build_zip)
    return FileResponse(zip_path, filename=zip_name)


@app.get("/daily", response_class=HTMLResponse)
async def daily(request: Request, url: str = ""):
    if not await _require_login():
        return RedirectResponse("/login")

    daily_name = None
    songs = []
    error = None

    if url:
        result = await qq_api.playlist_from_link(url)
    else:
        result = await qq_api.daily_recommendations()

    if result.get("code") == 1:
        data = result.get("data", {})
        daily_name = clean_html_tags(str(data.get("name", "每日推荐")))
        songs = [_as_web_song(s) for s in data.get("songs", []) if isinstance(s, dict)]
    else:
        error = result.get("error") or "获取每日推荐失败"

    return templates.TemplateResponse(
        "daily.html",
        {
            "request": request,
            "url": url,
            "daily_name": daily_name,
            "songs": songs,
            "error": error,
            "use_light_mode": config.LIGHT_DOWNLOAD_MODE,
            "default_quality": config.DEFAULT_QUALITY,
        },
    )


@app.get("/daily/download_zip")
async def daily_download_zip(quality: str | None = None, url: str = "", concurrency: int = 4):
    if not await _require_login():
        return RedirectResponse("/login")

    quality = quality or config.DEFAULT_QUALITY
    result = await qq_api.playlist_from_link(url) if url else await qq_api.daily_recommendations()
    if result.get("code") != 1:
        return JSONResponse({"error": result.get("error", "获取每日推荐失败")}, status_code=400)

    data = result.get("data", {})
    daily_name = clean_html_tags(str(data.get("name", "daily")))
    songs = [s for s in data.get("songs", []) if isinstance(s, dict)]

    download_root = Path("downloads")
    download_dir = download_root / f"daily_{int(time.time())}"
    download_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files = await _download_songs_concurrently(
        songs, download_dir, quality, concurrency=concurrency
    )

    if not downloaded_files:
        return JSONResponse({"error": "没有成功下载任何歌曲"}, status_code=500)

    zip_name = f"{_safe_filename(daily_name, 'daily')}_{int(time.time())}.zip"
    zip_path = download_root / zip_name

    def _build_zip():
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fp in downloaded_files:
                if fp.exists():
                    zf.write(fp, arcname=fp.name)

    await asyncio.to_thread(_build_zip)
    return FileResponse(zip_path, filename=zip_name)


@app.get("/download")
async def download(mid: str, name: str, singer: str, album: str, quality: str = None):
    song_info = {
        "mid": mid,
        "name": name,
        "singer": [{"name": singer}],
        "album": {"name": album, "mid": ""},
    }

    # 如果未指定音质，使用默认音质
    quality = quality or config.DEFAULT_QUALITY

    # 创建自定义文件名 "标题-歌手"
    custom_filename = f"{name}-{singer}"

    # 轻量下载模式
    if config.LIGHT_DOWNLOAD_MODE:
        song_url_result = await qq_api.song_url(song_info["mid"], quality)
        if song_url_result.get("code") == 0 and song_url_result.get("url"):
            # 无法直接修改浏览器下载的文件名，因为这里是重定向
            return RedirectResponse(song_url_result["url"])
        return JSONResponse({"error": "Cannot fetch song URL"}, status_code=500)

    # 完整下载模式
    path = await music_downloader.download_song(
        song_info, Path("downloads"), quality
    )
    if not path:
        return JSONResponse({"error": "Download failed"}, status_code=500)

    # 获取文件扩展名
    file_ext = os.path.splitext(path.name)[1]
    # 设置自定义文件名，保留原扩展名
    custom_filename = f"{custom_filename}{file_ext}"

    return FileResponse(path, filename=custom_filename)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
