import asyncio
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable, Tuple
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)
ProgressCallback = Callable[[dict], Awaitable[None]]

TRANSCODE_FOR_TELEGRAM = (str(os.getenv("TRANSCODE_FOR_TELEGRAM", "1")).lower() not in {"0", "false", "no"})
FFMPEG_CRF = os.getenv("FFMPEG_CRF", "23")
FFMPEG_PRESET = os.getenv("FFMPEG_PRESET", "veryfast")
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
YTDLP_COOKIES_FROM_BROWSER = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()
YTDLP_FORMAT = os.getenv(
    "YTDLP_FORMAT",
    "bv*[height<=480]+ba/b[height<=480]/best[height<=480]/best",
).strip()
YTDLP_DOWNLOAD_SECTIONS = os.getenv("YTDLP_DOWNLOAD_SECTIONS", "").strip()
YTDLP_TIKTOK_APP_INFO = os.getenv(
    "YTDLP_TIKTOK_APP_INFO",
    "musical_ly/35.1.3/2023501030/1233",
).strip()
YTDLP_TIKTOK_API_HOSTNAME = os.getenv(
    "YTDLP_TIKTOK_API_HOSTNAME",
    "api16-normal-c-alisg.tiktokv.com",
).strip()
YTDLP_TIKTOK_RETRIES = int(os.getenv("YTDLP_TIKTOK_RETRIES", "10"))
YTDLP_YOUTUBE_PLAYER_CLIENT = os.getenv("YTDLP_YOUTUBE_PLAYER_CLIENT", "android").strip()
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:138.0) Gecko/20100101 Firefox/138.0"
)
FLIXGAZE_PLAYER_RE = re.compile(
    r'const\s+pathId="(?P<path>[^"]+)",\s*domainId="(?P<domain>[^"]+)",\s*videoId="(?P<video>[^"]+)"',
    re.IGNORECASE,
)
DRAMATIP_KEY = base64.b64decode("QC6Ir2trghxRAyyyWZEOEFR4GgLhnfQ4A19I3QBlQkc=")
GOODSHORT_OFFLINE_KEY = bytes.fromhex("0b89258a7355bd7b0dc6e53a8b728b39")
_cached_goodshort_key: bytes | None = None
DRAMATIP_PATH_RE = re.compile(
    r"^/(?:([a-z]{2}(?:-[a-zA-Z]{2})?)/)?series/([^/]+)(?:/episode-(\d+))?/?$",
    re.IGNORECASE,
)
DRAMABOX_PATH_RE = re.compile(
    r"^/(?:([a-z]{2}(?:-[a-zA-Z]{2})?)/)?(?:movie/(\d+)(?:/([^/?#]+))?|ep/(\d+)(?:_([^/?#]+))?/(\d+)_Episode-(\d+))/?$",
    re.IGNORECASE,
)
MIN_VALID_EPISODE_BYTES = 500_000

async def probe_video_metadata(input_path: Path) -> dict[str, int]:
    """Return width/height/duration metadata for Telegram uploads."""
    try:
        src = input_path.expanduser().resolve()
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "default=noprint_wrappers=1:nokey=0",
            str(src),
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return {}

        metadata: dict[str, int] = {}
        for line in stdout.decode(errors="ignore").splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            try:
                if key in {"width", "height"}:
                    metadata[key] = int(float(value))
                elif key == "duration":
                    metadata[key] = max(1, int(float(value)))
            except (TypeError, ValueError):
                continue
        return metadata
    except Exception as e:
        logger.warning(f"Could not probe video metadata for {input_path}: {e}")
        return {}


async def transcode_to_telegram_mp4(input_path: Path) -> Tuple[bool, str, Path]:
    """Transcode to a Telegram-friendly MP4 (H.264/AAC, yuv420p).

    Many sources deliver AV1/HEVC which some Telegram clients show as a still frame + audio.
    The explicit scale/setsar filter preserves the display aspect ratio for vertical videos.
    """
    if not TRANSCODE_FOR_TELEGRAM:
        return True, "transcode disabled", input_path

    try:
        src = input_path.expanduser().resolve()
        if not src.exists() or not src.is_file():
            return False, "input file not found", input_path

        out_path = src.with_name(f"{src.stem}_tg.mp4")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-preset",
            str(FFMPEG_PRESET),
            "-crf",
            str(FFMPEG_CRF),
            "-vf",
            "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            msg = stderr.decode(errors="ignore").strip()[-800:]
            return False, f"ffmpeg transcode failed: {msg}", input_path

        if not out_path.exists() or out_path.stat().st_size == 0:
            return False, "ffmpeg produced empty output", input_path

        return True, "transcoded", out_path
    except Exception as e:
        logger.error(f"Error transcoding video: {e}")
        return False, f"transcode error: {e}", input_path

def safe_quote_url(url: str) -> str:
    """Ensures URL path is safely ASCII-encoded for HTTP request lines without double-encoding."""
    p = urlsplit(url)
    unquoted_path = unquote(p.path)
    safe_path = quote(unquoted_path, safe="/:@&=+$,-_.!~*'()")
    return urlunsplit((p.scheme, p.netloc, safe_path, p.query, p.fragment))


def extract_first_url(text: str | None) -> str | None:
    """Extracts the first HTTP/HTTPS URL from a string, handling accents and surrounding text."""
    if not text:
        return None
    m = re.search(r"https?://[^\s<>\"'`]+", text, re.IGNORECASE)
    if m:
        raw = m.group(0).rstrip(".,;!?:)]}\"'")
        return safe_quote_url(raw)
    return None


def validate_url(url: str) -> bool:
    """Validate URL to ensure it's from a trusted domain."""
    trusted_base_domains = {
        'instagram.com',
        'facebook.com',
        'tiktok.com',
        'youtube.com',
        'x.com',
        'reddit.com',
        'redd.it',
        'dailymotion.com',
        'flixgaze.com',
        'dramatip.net',
        'dramaboxdb.com',
    }
    trusted_exact_hosts = {
        'youtu.be',
    }

    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False

        host = (parsed.netloc or '').lower()
        # Strip credentials/port if present
        if '@' in host:
            host = host.split('@', 1)[1]
        if ':' in host:
            host = host.split(':', 1)[0]

        if host in trusted_exact_hosts:
            return True

        return any(host == base or host.endswith(f".{base}") for base in trusted_base_domains)
    except Exception:
        return False

def ensure_directories(*dirs: Path) -> bool:
    """
    Ensure all required directories exist and are accessible.
    Returns True if all directories are ready to use, False otherwise.
    """
    try:
        for dir_path in dirs:
            # Convert to absolute path
            abs_path = dir_path.expanduser().resolve()
            # Create directory and parents if they don't exist
            abs_path.mkdir(parents=True, exist_ok=True)
            # Verify write permissions by trying to create a test file
            test_file = abs_path / '.write_test'
            try:
                test_file.touch()
                test_file.unlink()
            except (PermissionError, OSError):
                logger.error(f"No hay permisos de escritura en el directorio: {abs_path}")
                return False
        return True
    except Exception as e:
        logger.error(f"Error al crear/verificar directorios: {e}")
        return False

def _fetch_text(url: str, referer: str | None = None) -> str:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = safe_quote_url(referer)

    safe_url = safe_quote_url(url)
    request = Request(safe_url, headers=headers)
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def _resolve_flixgaze_stream(url: str) -> tuple[str, dict[str, str]]:
    page = _fetch_text(url)
    match = FLIXGAZE_PLAYER_RE.search(page)
    if not match:
        raise ValueError("No se pudo extraer el reproductor de FlixGaze")

    path_id = match.group("path")
    domain_id = match.group("domain").replace("\\/", "/")
    video_id = match.group("video")
    stream_url = f"{domain_id}/{path_id}/{video_id}.m3u8"
    return stream_url, {"Referer": url, "User-Agent": DEFAULT_USER_AGENT}


def _decrypt_dramatip_enc(enc: str) -> str:
    raw = base64.b64decode(enc)
    iv = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(DRAMATIP_KEY)
    decrypted = aesgcm.decrypt(iv, ciphertext, None)
    return decrypted.decode("utf-8")


def _resolve_dramatip_episode_stream(
    netloc: str,
    book_id: str,
    slug: str,
    lang: str,
    episode: int,
) -> tuple[str, dict[str, str], str]:
    series_url = f"https://{netloc}/{lang}/series/{slug}"
    api_url = f"https://{netloc}/api/episode-source/{book_id}/{episode}?lang={lang}&refresh=1"
    api_req = Request(
        api_url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": series_url,
            "Accept": "application/json, text/plain, */*",
        },
    )
    enc = None
    try:
        with urlopen(api_req, timeout=15) as api_resp:
            data = json.loads(api_resp.read().decode("utf-8"))
            chain = data.get("descriptor", {}).get("chain", [])
            if chain and chain[0].get("enc"):
                enc = chain[0]["enc"]
    except Exception as e:
        logger.warning(f"Error consultando API episode-source de DramaTip para ep {episode}: {e}")

    if not enc:
        raise ValueError(f"No se pudo obtener el token de reproducción del episodio {episode}")

    stream_url = _decrypt_dramatip_enc(enc)
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
    custom_title = f"{safe_slug} - S01E{episode:02d}"
    # Do not pass Referer to CDN HLS streams: acfs1.goodreels.com rejects Referer: https://dramatip.net/ with HTTP 403
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
    }
    return stream_url, headers, custom_title


def get_dramatip_series_info(url: str) -> dict | None:
    """Extracts series metadata, bookId, and list of all available episodes from a DramaTip URL."""
    parsed = urlparse(url)
    match = DRAMATIP_PATH_RE.match(parsed.path)
    if not match:
        return None

    lang_match, slug, ep_match = match.groups()
    lang = lang_match or "es"
    netloc = (parsed.netloc or "dramatip.net").lower()

    series_url = f"https://{netloc}/{lang}/series/{slug}"
    try:
        html = _fetch_text(series_url, referer=f"https://{netloc}/")
    except Exception as e:
        logger.warning(f"Error obteniendo página de serie DramaTip: {e}")
        return None

    book_match = re.search(r'bookId[\'":\s\\]+(\d+)', html)
    if not book_match:
        return None
    book_id = book_match.group(1)

    serials = re.findall(r'serial_number[\'":\s\\]+(\d+)', html)
    links = re.findall(r'/series/[^/]+/episode-(\d+)', html)
    all_eps = set(map(int, serials + links))
    if not all_eps:
        all_eps = {1}
    episodes = sorted(list(all_eps))

    title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
    title = title_match.group(1).strip() if title_match else slug.replace("-", " ").title()

    return {
        "book_id": book_id,
        "slug": slug,
        "lang": lang,
        "title": title,
        "episodes": episodes,
        "total_episodes": len(episodes),
        "series_url": series_url,
        "current_episode": int(ep_match) if ep_match else None,
        "netloc": netloc,
    }


def _resolve_dramatip_stream(url: str) -> tuple[str, dict[str, str], str]:
    parsed = urlparse(url)
    match = DRAMATIP_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(
            "URL de DramaTip no válida. Formato esperado: https://dramatip.net/es/series/<slug> o .../episode-<num>"
        )

    lang_match, slug, ep_match = match.groups()
    lang = lang_match or "es"
    episode = int(ep_match) if ep_match else 1
    netloc = (parsed.netloc or "dramatip.net").lower()

    series_url = f"https://{netloc}/{lang}/series/{slug}"
    html = _fetch_text(series_url, referer=f"https://{netloc}/")

    book_match = re.search(r'bookId[\'":\s\\]+(\d+)', html)
    if not book_match:
        raise ValueError("No se pudo obtener el identificador de la serie en DramaTip")
    book_id = book_match.group(1)

    try:
        return _resolve_dramatip_episode_stream(netloc, book_id, slug, lang, episode)
    except Exception:
        # Fallback a datos incrustados en HTML si la API falla
        enc = None
        if episode == 1:
            m = re.search(r'sourceFirst[\'":\s\\]+[^{]*\{[^}]*\"enc\":\"([^\"]+)\"', html)
            if m:
                enc = m.group(1)
        elif episode == 2:
            m = re.search(r'nextSourceFirst[\'":\s\\]+[^{]*\{[^}]*\"enc\":\"([^\"]+)\"', html)
            if m:
                enc = m.group(1)

        if not enc:
            raise ValueError(f"No se pudo obtener el token de reproducción del episodio {episode}")

        stream_url = _decrypt_dramatip_enc(enc)
        safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)
        custom_title = f"{safe_slug} - S01E{episode:02d}"
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
        }
        return stream_url, headers, custom_title


def _normalize_slug(slug: str) -> str:
    unquoted = unquote(slug)
    normalized = unicodedata.normalize("NFKD", unquoted).encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", normalized).strip("_")
    return safe or "series"


def get_dramabox_series_info(url: str) -> dict | None:
    """Extracts series metadata, bookId, and list of all available episodes from a DramaBox URL."""
    parsed = urlparse(url)
    match = DRAMABOX_PATH_RE.match(parsed.path)
    if not match:
        return None

    lang_match, m_book_id, m_slug, ep_book_id, ep_slug, ch_id, ep_num = match.groups()
    lang = lang_match or "es"
    book_id = m_book_id or ep_book_id
    raw_slug = m_slug or ep_slug or "series"
    slug = _normalize_slug(raw_slug)
    netloc = (parsed.netloc or "dramaboxdb.com").lower()

    movie_url = f"https://{netloc}/{lang}/movie/{book_id}/{raw_slug}" if raw_slug else f"https://{netloc}/{lang}/movie/{book_id}"
    try:
        html = _fetch_text(movie_url, referer=f"https://{netloc}/")
    except Exception as e:
        logger.warning(f"Error obteniendo página de serie DramaBox: {e}")
        return None

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None

    try:
        data = json.loads(m.group(1))
        props = data.get("props", {}).get("pageProps", {})
        book_info = props.get("bookInfo", {})
        chapter_list = props.get("chapterList", [])
    except Exception as e:
        logger.warning(f"Error parseando datos __NEXT_DATA__ de DramaBox: {e}")
        return None

    book_name = book_info.get("bookName") or slug.replace("-", " ").title()
    chapters: dict[int, dict] = {}
    episodes: list[int] = []
    unlocked_count = 0
    for idx, ch in enumerate(chapter_list):
        ep_no = ch.get("index", idx) + 1
        episodes.append(ep_no)
        is_unlock = bool(ch.get("unlock"))
        if is_unlock:
            unlocked_count += 1
        chapters[ep_no] = {
            "id": str(ch.get("id")),
            "name": ch.get("name"),
            "unlock": is_unlock,
            "mp4": ch.get("mp4"),
            "m3u8": ch.get("m3u8Url"),
            "duration": ch.get("duration"),
        }

    return {
        "platform": "dramabox",
        "book_id": book_id,
        "slug": slug,
        "raw_slug": raw_slug,
        "lang": lang,
        "title": book_name,
        "episodes": sorted(episodes),
        "total_episodes": len(episodes),
        "unlocked_count": unlocked_count,
        "chapters": chapters,
        "series_url": movie_url,
        "current_episode": int(ep_num) if ep_num else None,
        "netloc": netloc,
    }


def _resolve_dramabox_episode_stream(
    netloc: str,
    book_id: str,
    slug: str,
    raw_slug: str,
    lang: str,
    episode: int,
    chapters: dict | None = None,
    ch_id: str | None = None,
) -> tuple[str, dict[str, str], str]:
    ch = (chapters or {}).get(episode)
    stream_url = None
    if ch:
        stream_url = ch.get("mp4") or ch.get("m3u8")

    if not stream_url:
        if not ch_id and ch:
            ch_id = ch.get("id")
        if not ch_id:
            info = get_dramabox_series_info(f"https://{netloc}/{lang}/movie/{book_id}/{raw_slug}")
            if info and info.get("chapters", {}).get(episode):
                ch = info["chapters"][episode]
                stream_url = ch.get("mp4") or ch.get("m3u8")
                ch_id = ch.get("id")
        if not stream_url and ch_id:
            ep_url = f"https://{netloc}/{lang}/ep/{book_id}_{raw_slug}/{ch_id}_Episode-{episode}"
            try:
                ep_html = _fetch_text(ep_url, referer=f"https://{netloc}/{lang}/movie/{book_id}/{raw_slug}")
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', ep_html, re.DOTALL)
                if m:
                    props = json.loads(m.group(1)).get("props", {}).get("pageProps", {})
                    stream_url = props.get("freeSource")
            except Exception as e:
                logger.warning(f"Error consultando preview de capítulo {episode} en DramaBox: {e}")

    if not stream_url:
        raise ValueError(f"No se pudo obtener el enlace de reproducción para el capítulo {episode} en DramaBox.")

    custom_title = f"{slug} - S01E{episode:02d}"
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    return stream_url, headers, custom_title


def _resolve_dramabox_stream(url: str) -> tuple[str, dict[str, str], str]:
    parsed = urlparse(url)
    match = DRAMABOX_PATH_RE.match(parsed.path)
    if not match:
        raise ValueError(
            "URL de DramaBox no válida. Formato esperado: https://www.dramaboxdb.com/es/movie/<id>/<slug> o .../ep/<id>_<slug>/<ch_id>_Episode-<num>"
        )

    lang_match, m_book_id, m_slug, ep_book_id, ep_slug, ch_id, ep_num = match.groups()
    lang = lang_match or "es"
    book_id = m_book_id or ep_book_id
    raw_slug = m_slug or ep_slug or "series"
    slug = _normalize_slug(raw_slug)
    netloc = (parsed.netloc or "dramaboxdb.com").lower()
    episode = int(ep_num) if ep_num else 1

    info = get_dramabox_series_info(f"https://{netloc}/{lang}/movie/{book_id}/{raw_slug}")
    chapters = info.get("chapters", {}) if info else {}
    return _resolve_dramabox_episode_stream(
        netloc=netloc,
        book_id=book_id,
        slug=slug,
        raw_slug=raw_slug,
        lang=lang,
        episode=episode,
        chapters=chapters,
        ch_id=ch_id,
    )


async def download_series(
    series_info: dict,
    output_dir: Path,
    progress_callback: Callable[[dict], Awaitable[None]] | None = None,
    episode_done_callback: Callable[[int, bool, float, int, str], None] | None = None,
) -> tuple[int, int, list[Path]]:
    """
    Downloads all episodes of a series into output_dir/<safe_slug>/.
    Returns: (successful_count: int, total_count: int, downloaded_paths: list[Path])
    """
    platform = series_info.get("platform", "dramatip")
    netloc = series_info.get("netloc", "dramatip.net" if platform == "dramatip" else "dramaboxdb.com")
    book_id = series_info.get("book_id")
    slug = series_info.get("slug", "series")
    raw_slug = series_info.get("raw_slug", slug)
    lang = series_info.get("lang", "es")
    episodes = series_info.get("episodes", [])
    chapters = series_info.get("chapters", {})
    total = len(episodes)
    safe_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", slug)

    series_base_dir = output_dir.expanduser().resolve() / safe_slug
    series_dir = series_base_dir / "Season 01"
    if not ensure_directories(series_dir):
        raise ValueError(f"Error: No se puede acceder al directorio {series_dir}")

    safe_dir = str(series_dir)
    successful_count = 0
    downloaded_paths: list[Path] = []
    loop = asyncio.get_running_loop()

    for ep in episodes:
        target_name = f"{safe_slug} - S01E{ep:02d}.mp4"
        target_path = series_dir / target_name

        candidate_paths = [
            target_path,
            series_base_dir / target_name,
            series_base_dir / f"{safe_slug}-capitulo-{ep}.mp4",
            series_dir / f"{safe_slug}-capitulo-{ep}.mp4",
            output_dir / f"{safe_slug}-capitulo-{ep}.mp4",
        ]
        found_existing = next(
            (p for p in candidate_paths if p.exists() and p.stat().st_size >= MIN_VALID_EPISODE_BYTES),
            None,
        )

        if found_existing:
            logger.info(f"Capítulo {ep} ya existe ({found_existing.stat().st_size} bytes en {found_existing.name}), omitiendo descarga.")
            successful_count += 1
            downloaded_paths.append(found_existing)
            if progress_callback:
                try:
                    await progress_callback({
                        "episode": ep,
                        "total_episodes": total,
                        "percent": 100,
                        "completed_count": successful_count,
                        "status": "finished",
                    })
                except Exception:
                    pass
            continue

        if target_path.exists():
            logger.warning(
                f"Capítulo {ep} existente parece truncado ({target_path.stat().st_size} bytes < {MIN_VALID_EPISODE_BYTES}), re-descargando."
            )
            try:
                target_path.unlink()
            except Exception:
                pass

        t_ep_start = time.time()
        try:
            if progress_callback:
                try:
                    await progress_callback({
                        "episode": ep,
                        "total_episodes": total,
                        "percent": 0,
                        "completed_count": successful_count,
                        "status": "downloading",
                    })
                except Exception:
                    pass

            if platform == "dramabox":
                stream_url, headers, custom_title = _resolve_dramabox_episode_stream(
                    netloc=netloc,
                    book_id=book_id,
                    slug=safe_slug,
                    raw_slug=raw_slug,
                    lang=lang,
                    episode=ep,
                    chapters=chapters,
                )
            else:
                stream_url, headers, custom_title = _resolve_dramatip_episode_stream(
                    netloc=netloc,
                    book_id=book_id,
                    slug=slug,
                    lang=lang,
                    episode=ep,
                )
            outtmpl = f"{safe_dir}/{custom_title}.%(ext)s"

            def ep_hook(info: dict) -> None:
                if not progress_callback:
                    return
                st = info.get("status")
                total_b = info.get("total_bytes") or info.get("total_bytes_estimate")
                down_b = info.get("downloaded_bytes") or 0
                pct = int(down_b * 100 / total_b) if total_b else 0
                if st == "finished":
                    pct = 100
                payload = {
                    "episode": ep,
                    "total_episodes": total,
                    "percent": pct,
                    "completed_count": successful_count,
                    "status": st,
                }
                asyncio.run_coroutine_threadsafe(progress_callback(payload), loop)

            await asyncio.to_thread(_run_ytdlp_download, stream_url, outtmpl, headers, ep_hook)

            ep_path = None
            if target_path.exists() and target_path.stat().st_size > 0:
                ep_path = target_path
            else:
                candidates = [p for p in Path(safe_dir).glob(f"{custom_title}.*") if p.is_file() and p.stat().st_size > 0]
                if candidates:
                    ep_path = max(candidates, key=lambda x: x.stat().st_mtime)

            if ep_path:
                successful_count += 1
                downloaded_paths.append(ep_path)
                ep_duration = time.time() - t_ep_start
                ep_size = ep_path.stat().st_size
                if episode_done_callback:
                    try:
                        episode_done_callback(ep, True, ep_duration, ep_size, "")
                    except Exception:
                        pass
            else:
                if episode_done_callback:
                    try:
                        episode_done_callback(ep, False, time.time() - t_ep_start, 0, "Archivo no encontrado tras descarga")
                    except Exception:
                        pass

            if progress_callback:
                try:
                    await progress_callback({
                        "episode": ep,
                        "total_episodes": total,
                        "percent": 100,
                        "completed_count": successful_count,
                        "status": "finished",
                    })
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error descargando capítulo {ep} de {slug}: {e}")
            if episode_done_callback:
                try:
                    episode_done_callback(ep, False, time.time() - t_ep_start, 0, str(e))
                except Exception:
                    pass

    return successful_count, total, downloaded_paths


def _prepare_download_target(url: str) -> tuple[str, dict[str, str], str | None]:
    host = (urlparse(url).netloc or "").lower()
    if host == "www.flixgaze.com" or host.endswith(".flixgaze.com"):
        stream_url, headers = _resolve_flixgaze_stream(url)
        return stream_url, headers, None
    if host == "dramatip.net" or host.endswith(".dramatip.net"):
        return _resolve_dramatip_stream(url)
    if host == "dramaboxdb.com" or host.endswith(".dramaboxdb.com"):
        return _resolve_dramabox_stream(url)
    return url, {}, None


def _build_yt_dlp_command(url: str, outtmpl: str, headers: dict[str, str]) -> list[str]:
    cmd = [
        'yt-dlp',
        '--no-warnings',
        '--restrict-filenames',
        # Prefer a Telegram/server-friendly format by default; override with YTDLP_FORMAT.
        '-f', YTDLP_FORMAT,
        '--merge-output-format', 'mp4',
        '-o', outtmpl,
        '--no-cache-dir',
        '--no-progress',
    ]

    if YTDLP_COOKIES_FILE:
        cmd.extend(['--cookies', YTDLP_COOKIES_FILE])
    elif YTDLP_COOKIES_FROM_BROWSER:
        cmd.extend(['--cookies-from-browser', YTDLP_COOKIES_FROM_BROWSER])

    if YTDLP_DOWNLOAD_SECTIONS:
        cmd.extend(['--download-sections', YTDLP_DOWNLOAD_SECTIONS])

    host = (urlparse(url).netloc or "").lower()
    if YTDLP_YOUTUBE_PLAYER_CLIENT and (host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")):
        cmd.extend(['--extractor-args', f'youtube:player_client={YTDLP_YOUTUBE_PLAYER_CLIENT}'])

    for key, value in headers.items():
        cmd.extend(['--add-header', f'{key}:{value}'])

    cmd.append(url)
    return cmd


def _format_download_error(stderr_text: str) -> str:
    compact = " ".join(stderr_text.split())[-1500:]

    if 'There is no video in this post' in stderr_text:
        return 'La publicación de Instagram no contiene video; parece ser una foto o carrusel sin video.'

    if 'Requested content is not available, rate-limit reached or login required' in stderr_text:
        message = 'Instagram pidió autenticación o bloqueó temporalmente la extracción anónima.'
        if YTDLP_COOKIES_FILE or YTDLP_COOKIES_FROM_BROWSER:
            return f'{message} Revisa que las cookies montadas sigan vigentes.\n\nDetalle: {compact}'
        return (
            message
            + ' Configura YTDLP_COOKIES_FILE con un cookies.txt exportado del navegador '
            + 'o YTDLP_COOKIES_FROM_BROWSER si el contenedor tiene acceso al perfil del navegador.\n\n'
            + f'Detalle: {compact}'
        )

    if 'Unsupported URL' in stderr_text:
        return f'yt-dlp no pudo extraer una fuente descargable para esta URL.\n\nDetalle: {compact}'

    if 'Not found.' in stderr_text and '[dailymotion]' in stderr_text:
        return f'Dailymotion respondió que el video ya no existe o no está disponible públicamente.\n\nDetalle: {compact}'

    return f'Error: {compact}'


def _parse_time_to_seconds(value: str) -> float:
    parts = [float(part) for part in value.split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _parse_download_sections(value: str) -> list[tuple[float | None, float | None]]:
    ranges: list[tuple[float | None, float | None]] = []
    for section in value.split(","):
        section = section.strip()
        if not section:
            continue
        if section.startswith("*"):
            section = section[1:]
        if "-" not in section:
            continue
        start, end = section.split("-", 1)
        ranges.append((
            _parse_time_to_seconds(start) if start else None,
            _parse_time_to_seconds(end) if end else None,
        ))
    return ranges


def _get_goodshort_aes_key(netloc: str = "dramatip.net") -> bytes:
    global _cached_goodshort_key
    if _cached_goodshort_key is not None:
        return _cached_goodshort_key
    try:
        req = Request(
            f"https://{netloc}/api/goodshort-key",
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": f"https://{netloc}/",
            },
        )
        with urlopen(req, timeout=10) as resp:
            key = resp.read()
            if len(key) == 16:
                _cached_goodshort_key = key
                return key
    except Exception as e:
        logger.warning(f"No se pudo obtener /api/goodshort-key, usando llave por defecto: {e}")
    _cached_goodshort_key = GOODSHORT_OFFLINE_KEY
    return _cached_goodshort_key


def _download_goodshort_hls(url: str, outtmpl: str, headers: dict[str, str], progress_hook) -> bool:
    """
    Downloads and decrypts GoodReels / GoodShort HLS streams that use
    #EXT-X-KEY:METHOD=AES-128,URI="local://offline-key/..." encryption.
    Returns True if handled, False if caller should fall back to yt-dlp.
    """
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not (host.endswith(".goodreels.com") or host == "goodreels.com"):
        return False

    req_headers = {"User-Agent": (headers or {}).get("User-Agent", DEFAULT_USER_AGENT)}
    m3u8_text = None
    active_url = url
    try:
        with urlopen(Request(url, headers=req_headers), timeout=15) as resp:
            m3u8_text = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        if re.search(r"(^|\.)acfs\d*\.goodreels\.com$", host, re.IGNORECASE):
            fallback_url = urlunparse(parsed._replace(netloc="v2-akm.goodreels.com"))
            with urlopen(Request(fallback_url, headers=req_headers), timeout=15) as resp:
                m3u8_text = resp.read().decode("utf-8", errors="ignore")
                active_url = fallback_url
        else:
            raise

    if not m3u8_text or "#EXT-X-STREAM-INF" in m3u8_text:
        return False

    segments: list[tuple[str, bool, bytes | None]] = []
    encrypted = False
    current_iv: bytes | None = None
    needs_key = False

    for raw_line in m3u8_text.splitlines():
        line = raw_line.strip()
        if line.startswith("#EXT-X-KEY:"):
            if "METHOD=NONE" in line:
                encrypted = False
                current_iv = None
            elif "METHOD=AES-128" in line:
                encrypted = True
                needs_key = True
                iv_m = re.search(r"IV=0x([0-9a-fA-F]+)", line)
                current_iv = bytes.fromhex(iv_m.group(1).zfill(32)) if iv_m else None
        elif line and not line.startswith("#"):
            seg_url = urljoin(active_url, line)
            segments.append((seg_url, encrypted, current_iv))

    if not segments:
        return False

    aes_key = _get_goodshort_aes_key() if needs_key else b""
    target_mp4 = (
        outtmpl.replace("%(ext)s", "mp4")
        .replace("%(title).100B", "video")
        .replace("%(title)s", "video")
        .replace("%(id)s", "stream")
    )
    total_segs = len(segments)

    with tempfile.TemporaryDirectory() as tmp:
        ts_path = os.path.join(tmp, "merged.ts")
        with open(ts_path, "wb") as out_f:
            for idx, (seg_url, is_enc, iv) in enumerate(segments):
                with urlopen(Request(seg_url, headers=req_headers), timeout=20) as seg_resp:
                    raw = seg_resp.read()
                if is_enc:
                    iv_bytes = iv if iv is not None else idx.to_bytes(16, "big")
                    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv_bytes))
                    decryptor = cipher.decryptor()
                    dec = decryptor.update(raw) + decryptor.finalize()
                    if dec:
                        pad_len = dec[-1]
                        if 1 <= pad_len <= 16 and dec.endswith(bytes([pad_len]) * pad_len):
                            dec = dec[:-pad_len]
                    out_f.write(dec)
                else:
                    out_f.write(raw)

                if progress_hook:
                    try:
                        progress_hook({
                            "status": "downloading",
                            "downloaded_bytes": idx + 1,
                            "total_bytes": total_segs,
                        })
                    except Exception:
                        pass

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                ts_path,
                "-c",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
                target_mp4,
            ],
            check=True,
        )

    if progress_hook:
        try:
            progress_hook({
                "status": "finished",
                "downloaded_bytes": total_segs,
                "total_bytes": total_segs,
            })
        except Exception:
            pass

    return True


def _run_ytdlp_download(url: str, outtmpl: str, headers: dict[str, str], progress_hook) -> None:
    if _download_goodshort_hls(url, outtmpl, headers, progress_hook):
        return

    ydl_opts = {
        "outtmpl": outtmpl,
        "restrictfilenames": True,
        "format": YTDLP_FORMAT,
        "merge_output_format": "mp4",
        "cachedir": False,
        "noprogress": True,
        "progress_hooks": [progress_hook] if progress_hook else [],
        "http_headers": headers or {},
        "quiet": True,
        "no_warnings": True,
    }
    if YTDLP_COOKIES_FILE:
        ydl_opts["cookiefile"] = YTDLP_COOKIES_FILE
    elif YTDLP_COOKIES_FROM_BROWSER:
        ydl_opts["cookiesfrombrowser"] = tuple(YTDLP_COOKIES_FROM_BROWSER.split(":"))
    if YTDLP_DOWNLOAD_SECTIONS:
        ranges = _parse_download_sections(YTDLP_DOWNLOAD_SECTIONS)
        if ranges:
            ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(None, ranges)

    parsed_host = (urlparse(url).netloc or "").lower()
    extractor_args: dict[str, dict[str, list[str]]] = {}
    if YTDLP_YOUTUBE_PLAYER_CLIENT and (
        parsed_host == "youtu.be"
        or parsed_host == "youtube.com"
        or parsed_host.endswith(".youtube.com")
    ):
        extractor_args["youtube"] = {"player_client": [YTDLP_YOUTUBE_PLAYER_CLIENT]}

    if parsed_host == "vt.tiktok.com" or parsed_host.endswith(".tiktok.com"):
        tiktok_args: dict[str, list[str]] = {}
        if YTDLP_TIKTOK_APP_INFO:
            # Force yt-dlp to try TikTok's mobile API before falling back to brittle webpage data.
            tiktok_args["app_info"] = [YTDLP_TIKTOK_APP_INFO]
        if YTDLP_TIKTOK_API_HOSTNAME:
            tiktok_args["api_hostname"] = [YTDLP_TIKTOK_API_HOSTNAME]
        if tiktok_args:
            extractor_args["tiktok"] = tiktok_args

    if extractor_args:
        ydl_opts["extractor_args"] = extractor_args

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


async def download_video(url: str, output_dir: Path, progress_callback: ProgressCallback | None = None) -> Tuple[bool, str, Path]:
    """
    Download video from supported platforms using yt-dlp.
    Returns: (success: bool, message: str, file_path: Path)
    """
    if not validate_url(url):
        return False, "URL no válida o dominio no soportado", Path()

    if not ensure_directories(output_dir):
        return False, f"Error: No se puede acceder al directorio {output_dir}", Path()

    try:
        safe_dir = str(output_dir.expanduser().resolve())
        effective_url, headers, custom_title = _prepare_download_target(url)
        if custom_title:
            outtmpl = f"{safe_dir}/{custom_title}.%(ext)s"
        else:
            outtmpl = f"{safe_dir}/%(title).200B-%(id)s.%(ext)s"
        loop = asyncio.get_running_loop()

        def hook(info: dict) -> None:
            if not progress_callback:
                return
            clean = {
                "status": info.get("status"),
                "downloaded_bytes": info.get("downloaded_bytes"),
                "total_bytes": info.get("total_bytes") or info.get("total_bytes_estimate"),
                "speed": info.get("speed"),
                "eta": info.get("eta"),
                "filename": info.get("filename"),
            }
            asyncio.run_coroutine_threadsafe(progress_callback(clean), loop)

        last_download_error: DownloadError | None = None
        max_attempts = max(1, YTDLP_TIKTOK_RETRIES if "tiktok.com" in (urlparse(effective_url).netloc or "").lower() else 3)
        for attempt in range(1, max_attempts + 1):
            try:
                await asyncio.to_thread(_run_ytdlp_download, effective_url, outtmpl, headers, hook)
                last_download_error = None
                break
            except DownloadError as e:
                last_download_error = e
                error_text = str(e)
                transient_tiktok_error = (
                    "[TikTok]" in error_text
                    and "Unable to extract universal data for rehydration" in error_text
                )
                if not transient_tiktok_error or attempt >= max_attempts:
                    raise
                logger.warning(
                    "TikTok extraction failed with universal-data error; retrying attempt %s/%s",
                    attempt + 1,
                    max_attempts,
                )
                await asyncio.sleep(2 * attempt)

        if last_download_error is not None:
            raise last_download_error

        allowed_extensions = {'.mp4', '.mkv', '.webm', '.mov'}
        candidate_files = [p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed_extensions]
        if not candidate_files:
            return False, "No se encontró el archivo de video descargado", Path()

        latest_file = max(candidate_files, key=lambda x: x.stat().st_mtime)
        return True, "Descarga exitosa", latest_file

    except DownloadError as e:
        return False, _format_download_error(str(e)), Path()
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return False, f"Error: {str(e)}", Path()
