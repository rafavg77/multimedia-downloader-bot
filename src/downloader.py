import logging
import asyncio
import re
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse
from models import sanitize_path

logger = logging.getLogger(__name__)

TRANSCODE_FOR_TELEGRAM = (str(__import__("os").getenv("TRANSCODE_FOR_TELEGRAM", "1")).lower() not in {"0", "false", "no"})
FFMPEG_CRF = __import__("os").getenv("FFMPEG_CRF", "23")
FFMPEG_PRESET = __import__("os").getenv("FFMPEG_PRESET", "veryfast")

async def transcode_to_telegram_mp4(input_path: Path) -> Tuple[bool, str, Path]:
    """Transcode to a Telegram-friendly MP4 (H.264/AAC, yuv420p).

    Many sources deliver AV1/HEVC which some Telegram clients show as a still frame + audio.
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

async def download_video(url: str, output_dir: Path) -> Tuple[bool, str, Path]:
    """
    Download video from supported platforms using yt-dlp.
    Returns: (success: bool, message: str, file_path: Path)
    """
    # Validate URL before processing
    if not validate_url(url):
        return False, "URL no válida o dominio no soportado", Path()
    
    # Ensure output directory exists and is writable
    if not ensure_directories(output_dir):
        return False, f"Error: No se puede acceder al directorio {output_dir}", Path()
    
    try:
        # Convert to absolute path and sanitize
        safe_dir = str(output_dir.expanduser().resolve())
        safe_template = sanitize_path('%(title)s')
        
        # Prepare the command with sanitized inputs
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--restrict-filenames',
            # Some sites (e.g. Reddit) expose separate video+audio streams.
            # This selector downloads best video+audio when available, otherwise falls back.
            '-f', 'bv*+ba/best',
            '--merge-output-format', 'mp4',
            '-o', f"{safe_dir}/{safe_template}.%(ext)s",
            '--no-cache-dir',
            '--no-progress',
            url
        ]
        
        # Run the command
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            return False, f"Error: {stderr.decode()}", Path()
            
        # Find the downloaded file safely (avoid picking metadata like .info.json)
        allowed_extensions = {'.mp4', '.mkv', '.webm', '.mov'}
        candidate_files = [
            p for p in output_dir.iterdir()
            if p.is_file() and p.suffix.lower() in allowed_extensions
        ]
        if not candidate_files:
            return False, "No se encontró el archivo de video descargado", Path()

        # Get the most recently modified video file
        latest_file = max(candidate_files, key=lambda x: x.stat().st_mtime)
            
        return True, "Descarga exitosa", latest_file
        
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return False, f"Error: {str(e)}", Path()
