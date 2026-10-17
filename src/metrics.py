"""Prometheus metrics module for Multimedia Downloader Bot.

Provides Prometheus metrics (counters, gauges, histograms) and an embedded
HTTP metrics exporter server for scraping by Prometheus.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from prometheus_client import Counter, Gauge, Histogram, Info, start_http_server

logger = logging.getLogger(__name__)

# --- Bot Info & Status ---
BOT_INFO = Info(
    "mediabot_build",
    "Multimedia Downloader Bot build and runtime metadata",
)

BOT_START_TIMESTAMP = Gauge(
    "mediabot_start_time_seconds",
    "Timestamp unix de inicio del servicio",
)

BOT_UPTIME_SECONDS = Gauge(
    "mediabot_uptime_seconds",
    "Tiempo de actividad del bot en segundos",
)

BOT_AUTHORIZED_USERS = Gauge(
    "mediabot_authorized_users_total",
    "Total de usuarios autorizados en la base de datos",
)

# --- Interactions & Traffic ---
REQUESTS_TOTAL = Counter(
    "mediabot_requests_total",
    "Total de interacciones recibidas por el bot",
    ["type", "status"],  # type: url, command_start, command_help, command_admin, command_events, callback
)

UNAUTHORIZED_ATTEMPTS_TOTAL = Counter(
    "mediabot_unauthorized_attempts_total",
    "Total de intentos de acceso no autorizados",
    ["command"],
)

# --- Active In-Flight Work ---
ACTIVE_DOWNLOADS = Gauge(
    "mediabot_active_downloads",
    "Número actual de descargas en progreso",
)

ACTIVE_TRANSCODES = Gauge(
    "mediabot_active_transcodes",
    "Número actual de transcodificaciones ffmpeg en progreso",
)

# --- Downloads Pipeline ---
DOWNLOADS_TOTAL = Counter(
    "mediabot_downloads_total",
    "Total de descargas solicitadas",
    ["platform", "status", "action"],  # platform: youtube, tiktok, etc.; status: success, failed, file_too_large; action: send, save, save_and_send
)

DOWNLOAD_DURATION_SECONDS = Histogram(
    "mediabot_download_duration_seconds",
    "Duración de las descargas en segundos",
    ["platform"],
    buckets=[1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0, 600.0],
)

DOWNLOAD_BYTES_TOTAL = Counter(
    "mediabot_download_bytes_total",
    "Bytes totales descargados acumulados",
    ["platform"],
)

DOWNLOAD_FILE_SIZE_BYTES = Histogram(
    "mediabot_download_file_size_bytes",
    "Distribución del tamaño de los archivos descargados en bytes",
    ["platform"],
    buckets=[
        1 * 1024 * 1024,      # 1 MB
        5 * 1024 * 1024,      # 5 MB
        10 * 1024 * 1024,     # 10 MB
        20 * 1024 * 1024,     # 20 MB
        35 * 1024 * 1024,     # 35 MB
        50 * 1024 * 1024,     # 50 MB (límite telegram bot)
        100 * 1024 * 1024,    # 100 MB
        250 * 1024 * 1024,    # 250 MB
        500 * 1024 * 1024,    # 500 MB
        1024 * 1024 * 1024,   # 1 GB
    ],
)

# --- Transcoding (ffmpeg) ---
TRANSCODES_TOTAL = Counter(
    "mediabot_transcodes_total",
    "Total de transcodificaciones a MP4 H.264 para Telegram",
    ["status"],  # success, failed, skipped
)

TRANSCODE_DURATION_SECONDS = Histogram(
    "mediabot_transcode_duration_seconds",
    "Duración de la transcodificación ffmpeg en segundos",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0],
)

# --- Telegram Delivery ---
TELEGRAM_UPLOADS_TOTAL = Counter(
    "mediabot_telegram_uploads_total",
    "Total de envíos de video a Telegram",
    ["status"],  # success, failed_413, failed_size_limit, error
)

TELEGRAM_UPLOAD_DURATION_SECONDS = Histogram(
    "mediabot_telegram_upload_duration_seconds",
    "Tiempo de envío de video a través de la API de Telegram",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0],
)

# --- Errors & Diagnostics ---
ERRORS_TOTAL = Counter(
    "mediabot_errors_total",
    "Total de errores agrupados por categoría",
    ["category", "platform"],  # category: unsupported_url, auth_or_ratelimit, not_found, size_limit, transcode_error, timeout, network_error, general_error
)

# --- Latest Execution State (KPI Cards in Grafana) ---
LAST_DOWNLOAD_TIMESTAMP_SECONDS = Gauge(
    "mediabot_last_download_timestamp_seconds",
    "Timestamp de la última descarga realizada",
)

LAST_DOWNLOAD_SUCCESS = Gauge(
    "mediabot_last_download_success",
    "Estado de la última descarga (1 = exitosa, 0 = fallida)",
)

LAST_DOWNLOAD_DURATION_SECONDS = Gauge(
    "mediabot_last_download_duration_seconds",
    "Duración de la última descarga en segundos",
)

LAST_DOWNLOAD_SIZE_BYTES = Gauge(
    "mediabot_last_download_size_bytes",
    "Tamaño del último archivo descargado en bytes",
)

LAST_DOWNLOAD_PLATFORM = Info(
    "mediabot_last_download_info",
    "Información sobre la plataforma y acción de la última descarga",
)

# --- Series Pipeline ---
SERIES_DOWNLOADS_TOTAL = Counter(
    "mediabot_series_downloads_total",
    "Total de series descargadas completas",
    ["platform", "status"],
)

SERIES_EPISODES_TOTAL = Counter(
    "mediabot_series_episodes_total",
    "Total de episodios procesados en series",
    ["platform", "status"],
)

# --- Persistent Storage Metrics ---
STORAGE_SAVED_VIDEOS_COUNT = Gauge(
    "mediabot_storage_saved_videos_count",
    "Número total de archivos de video en almacenamiento persistente",
)

STORAGE_SAVED_VIDEOS_BYTES = Gauge(
    "mediabot_storage_saved_videos_bytes",
    "Bytes totales ocupados por videos en almacenamiento persistente",
)

# Internal state
KNOWN_PLATFORMS = (
    "youtube",
    "tiktok",
    "instagram",
    "facebook",
    "x_twitter",
    "dramatip",
    "dramabox",
    "dailymotion",
    "reddit",
    "flixgaze",
    "other",
)
_metrics_server_started = False
_service_start_time: float = time.time()


def detect_platform(url: str) -> str:
    """Classify the target platform from URL domain."""
    if not url:
        return "unknown"
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if "@" in host:
            host = host.split("@", 1)[1]
        if ":" in host:
            host = host.split(":", 1)[0]

        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return "tiktok"
        elif host == "instagram.com" or host.endswith(".instagram.com"):
            return "instagram"
        elif host == "youtube.com" or host.endswith(".youtube.com") or host == "youtu.be" or host.endswith(".youtu.be"):
            return "youtube"
        elif host == "x.com" or host.endswith(".x.com") or host == "twitter.com" or host.endswith(".twitter.com"):
            return "x_twitter"
        elif host == "facebook.com" or host.endswith(".facebook.com") or host == "fb.watch" or host.endswith(".fb.watch"):
            return "facebook"
        elif host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it" or host.endswith(".redd.it"):
            return "reddit"
        elif host == "dailymotion.com" or host.endswith(".dailymotion.com") or host == "dai.ly" or host.endswith(".dai.ly"):
            return "dailymotion"
        elif "dramabox" in host:
            return "dramabox"
        elif "dramatip" in host:
            return "dramatip"
        elif "flixgaze" in host:
            return "flixgaze"
        return "other"
    except Exception:
        return "unknown"


def categorize_error(error_msg: str) -> str:
    """Classify error messages into actionable diagnostic categories."""
    msg = (error_msg or "").lower()
    if "unsupported url" in msg or "no válida o dominio no soportado" in msg:
        return "unsupported_url"
    if "rate-limit" in msg or "login required" in msg or "autenticación" in msg or "cookies" in msg:
        return "auth_or_ratelimit"
    if "not found" in msg or "no existe" in msg:
        return "not_found"
    if "excede el límite" in msg or "too_large" in msg or "413" in msg:
        return "size_limit"
    if "transcode" in msg or "ffmpeg" in msg:
        return "transcode_error"
    if "timeout" in msg:
        return "timeout"
    if "network" in msg or "connection" in msg:
        return "network_error"
    return "general_error"


def record_request(req_type: str, status: str = "authorized") -> None:
    """Record an incoming interaction."""
    try:
        REQUESTS_TOTAL.labels(type=req_type, status=status).inc()
    except Exception as e:
        logger.debug(f"Failed to record request metric: {e}")


def record_unauthorized_attempt(command: str) -> None:
    """Record an unauthorized access attempt."""
    try:
        cmd_clean = command.strip().split()[0] if command else "unknown"
        UNAUTHORIZED_ATTEMPTS_TOTAL.labels(command=cmd_clean[:32]).inc()
        REQUESTS_TOTAL.labels(type="unauthorized_event", status="unauthorized").inc()
    except Exception as e:
        logger.debug(f"Failed to record unauthorized metric: {e}")


def record_download_start(platform: str) -> None:
    """Track beginning of a download job."""
    try:
        ACTIVE_DOWNLOADS.inc()
    except Exception as e:
        logger.debug(f"Failed to record download start metric: {e}")


def record_download_result(
    platform: str,
    action: str,
    success: bool,
    duration: float,
    size_bytes: int = 0,
    error_msg: str = "",
) -> None:
    """Track outcome of a download job and update KPI gauges."""
    try:
        ACTIVE_DOWNLOADS.dec()
    except Exception:
        pass

    now = time.time()
    status = "success" if success else ("file_too_large" if "too_large" in error_msg else "failed")

    try:
        DOWNLOADS_TOTAL.labels(platform=platform, status=status, action=action).inc()
        DOWNLOAD_DURATION_SECONDS.labels(platform=platform).observe(max(0.001, duration))

        LAST_DOWNLOAD_TIMESTAMP_SECONDS.set(now)
        LAST_DOWNLOAD_SUCCESS.set(1 if success else 0)
        LAST_DOWNLOAD_DURATION_SECONDS.set(duration)

        LAST_DOWNLOAD_PLATFORM.info({
            "platform": platform,
            "action": action,
            "status": status,
        })

        if success and size_bytes > 0:
            DOWNLOAD_BYTES_TOTAL.labels(platform=platform).inc(size_bytes)
            DOWNLOAD_FILE_SIZE_BYTES.labels(platform=platform).observe(size_bytes)
            LAST_DOWNLOAD_SIZE_BYTES.set(size_bytes)
        elif not success:
            err_cat = categorize_error(error_msg)
            ERRORS_TOTAL.labels(category=err_cat, platform=platform).inc()
    except Exception as e:
        logger.debug(f"Failed to record download result metric: {e}")


def record_episode_download(
    platform: str,
    success: bool,
    duration: float,
    size_bytes: int = 0,
    error_msg: str = "",
) -> None:
    """Record outcome of an individual episode within a series batch."""
    now = time.time()
    status = "success" if success else "failed"

    try:
        DOWNLOADS_TOTAL.labels(platform=platform, status=status, action="save").inc()
        SERIES_EPISODES_TOTAL.labels(platform=platform, status=status).inc()
        DOWNLOAD_DURATION_SECONDS.labels(platform=platform).observe(max(0.001, duration))

        LAST_DOWNLOAD_TIMESTAMP_SECONDS.set(now)
        LAST_DOWNLOAD_SUCCESS.set(1 if success else 0)
        LAST_DOWNLOAD_DURATION_SECONDS.set(duration)

        LAST_DOWNLOAD_PLATFORM.info({
            "platform": platform,
            "action": "save",
            "status": status,
        })

        if success and size_bytes > 0:
            DOWNLOAD_BYTES_TOTAL.labels(platform=platform).inc(size_bytes)
            DOWNLOAD_FILE_SIZE_BYTES.labels(platform=platform).observe(size_bytes)
            LAST_DOWNLOAD_SIZE_BYTES.set(size_bytes)
        elif not success:
            err_cat = categorize_error(error_msg)
            ERRORS_TOTAL.labels(category=err_cat, platform=platform).inc()
    except Exception as e:
        logger.debug(f"Failed to record episode download metric: {e}")


def record_series_start(platform: str) -> None:
    """Track beginning of a batch series download job."""
    try:
        ACTIVE_DOWNLOADS.inc()
    except Exception as e:
        logger.debug(f"Failed to record series start metric: {e}")


def record_series_result(
    platform: str,
    success: bool,
    total_episodes: int,
    successful_episodes: int,
    duration: float = 0.0,
) -> None:
    """Track completion of a batch series download job."""
    try:
        ACTIVE_DOWNLOADS.dec()
    except Exception:
        pass

    status = "success" if success else "failed"
    try:
        SERIES_DOWNLOADS_TOTAL.labels(platform=platform, status=status).inc()
    except Exception as e:
        logger.debug(f"Failed to record series result metric: {e}")


def init_metrics_registry() -> None:
    """Pre-initialize Prometheus counters and gauges so Grafana doesn't show No Data on fresh start."""
    try:
        ACTIVE_DOWNLOADS.set(0)
        ACTIVE_TRANSCODES.set(0)
        LAST_DOWNLOAD_SUCCESS.set(-1)
        LAST_DOWNLOAD_TIMESTAMP_SECONDS.set(0)
        LAST_DOWNLOAD_DURATION_SECONDS.set(0)
        LAST_DOWNLOAD_SIZE_BYTES.set(0)
        STORAGE_SAVED_VIDEOS_COUNT.set(0)
        STORAGE_SAVED_VIDEOS_BYTES.set(0)

        for p in KNOWN_PLATFORMS:
            DOWNLOADS_TOTAL.labels(platform=p, status="success", action="save")
            DOWNLOADS_TOTAL.labels(platform=p, status="success", action="send")
            DOWNLOADS_TOTAL.labels(platform=p, status="failed", action="save")
            DOWNLOAD_BYTES_TOTAL.labels(platform=p)
            SERIES_DOWNLOADS_TOTAL.labels(platform=p, status="success")
            SERIES_EPISODES_TOTAL.labels(platform=p, status="success")

        for st in ("success", "failed", "skipped"):
            TRANSCODES_TOTAL.labels(status=st)

        for st in ("success", "failed_413", "failed_size_limit", "error"):
            TELEGRAM_UPLOADS_TOTAL.labels(status=st)

        for req in ("url", "command_start", "command_help", "command_admin", "callback"):
            REQUESTS_TOTAL.labels(type=req, status="authorized")
    except Exception as e:
        logger.debug(f"Failed to pre-initialize metrics registry: {e}")


def update_storage_metrics(saved_videos_dir: Optional[Path] = None) -> None:
    """Scan saved_videos directory and update storage gauges and last download info if needed."""
    if not saved_videos_dir:
        saved_videos_path = os.getenv("SAVED_VIDEOS_DIR", "/data/saved_videos")
        saved_videos_dir = Path(saved_videos_path)

    try:
        target_dir = saved_videos_dir.expanduser().resolve()
        if not target_dir.exists():
            return

        video_extensions = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
        total_count = 0
        total_bytes = 0
        latest_file = None
        latest_mtime = 0.0

        for path in target_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in video_extensions:
                try:
                    stat = path.stat()
                    size = stat.st_size
                    if size > 0:
                        total_count += 1
                        total_bytes += size
                        mtime = stat.st_mtime
                        if mtime > latest_mtime:
                            latest_mtime = mtime
                            latest_file = path
                except Exception:
                    continue

        STORAGE_SAVED_VIDEOS_COUNT.set(total_count)
        STORAGE_SAVED_VIDEOS_BYTES.set(total_bytes)

        # Bootstrap last download state if starting clean or rebooted
        if latest_file and (LAST_DOWNLOAD_TIMESTAMP_SECONDS._value.get() == 0 or LAST_DOWNLOAD_SUCCESS._value.get() == -1):
            LAST_DOWNLOAD_TIMESTAMP_SECONDS.set(latest_mtime)
            LAST_DOWNLOAD_SIZE_BYTES.set(latest_file.stat().st_size)
            LAST_DOWNLOAD_SUCCESS.set(1)

            plat = "other"
            p_str = str(latest_file).lower()
            for kp in KNOWN_PLATFORMS:
                if kp in p_str:
                    plat = kp
                    break
            LAST_DOWNLOAD_PLATFORM.info({
                "platform": plat,
                "action": "save",
                "status": "success",
            })
    except Exception as e:
        logger.debug(f"Failed to scan storage metrics: {e}")


def record_transcode_start() -> None:
    """Track beginning of a transcode job."""
    try:
        ACTIVE_TRANSCODES.inc()
    except Exception as e:
        logger.debug(f"Failed to record transcode start metric: {e}")


def record_transcode_result(success: bool, duration: float, skipped: bool = False) -> None:
    """Track outcome of a transcode job."""
    try:
        ACTIVE_TRANSCODES.dec()
    except Exception:
        pass

    status = "skipped" if skipped else ("success" if success else "failed")
    try:
        TRANSCODES_TOTAL.labels(status=status).inc()
        if not skipped:
            TRANSCODE_DURATION_SECONDS.observe(max(0.001, duration))
    except Exception as e:
        logger.debug(f"Failed to record transcode result metric: {e}")


def record_telegram_upload(status: str, duration: float) -> None:
    """Track Telegram video delivery result and latency."""
    try:
        TELEGRAM_UPLOADS_TOTAL.labels(status=status).inc()
        TELEGRAM_UPLOAD_DURATION_SECONDS.observe(max(0.001, duration))
    except Exception as e:
        logger.debug(f"Failed to record telegram upload metric: {e}")


def set_authorized_users_count(count: int) -> None:
    """Update authorized users count gauge."""
    try:
        BOT_AUTHORIZED_USERS.set(count)
    except Exception as e:
        logger.debug(f"Failed to set authorized users gauge: {e}")


def update_uptime() -> None:
    """Update uptime gauge."""
    try:
        BOT_UPTIME_SECONDS.set(time.time() - _service_start_time)
    except Exception as e:
        logger.debug(f"Failed to update uptime gauge: {e}")


def start_metrics_server(port: int = 9099, host: str = "0.0.0.0") -> bool:
    """Start the Prometheus HTTP server in a background daemon thread."""
    global _metrics_server_started, _service_start_time
    if _metrics_server_started:
        return True

    try:
        _service_start_time = time.time()
        BOT_START_TIMESTAMP.set(_service_start_time)
        BOT_UPTIME_SECONDS.set(0)
        BOT_INFO.info({
            "version": "1.0.0",
            "service": "multimedia-downloader-bot",
        })

        init_metrics_registry()
        try:
            update_storage_metrics()
        except Exception:
            pass

        start_http_server(port=port, addr=host)
        _metrics_server_started = True
        logger.info(f"Prometheus metrics HTTP server successfully listening on {host}:{port}/metrics")
        return True
    except Exception as e:
        logger.error(f"Failed to start Prometheus metrics server on {host}:{port}: {e}")
        return False
