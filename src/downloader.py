import logging
import asyncio
import re
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse
from models import sanitize_path

logger = logging.getLogger(__name__)

def validate_url(url: str) -> bool:
    """Validate URL to ensure it's from a trusted domain."""
    trusted_domains = {
        'instagram.com', 'www.instagram.com',
        'facebook.com', 'www.facebook.com',
        'tiktok.com', 'www.tiktok.com',
        'youtube.com', 'www.youtube.com', 'youtu.be'
    }
    
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower() in trusted_domains and parsed.scheme in ('http', 'https')
    except Exception:
        return False

async def download_video(url: str, output_dir: Path) -> Tuple[bool, str, Path]:
    """
    Download video from supported platforms using yt-dlp.
    Returns: (success: bool, message: str, file_path: Path)
    """
    # Validate URL before processing
    if not validate_url(url):
        return False, "URL no válida o dominio no soportado", Path()
    
    try:
        # Sanitize output path and create a safe template for yt-dlp
        safe_dir = str(output_dir)
        safe_template = sanitize_path('%(title)s')
        
        # Prepare the command with sanitized inputs
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--restrict-filenames',  # Use only ASCII characters in filenames
            '-f', 'best',
            '-o', f"{safe_dir}/{safe_template}.%(ext)s",
            '--no-cache-dir',  # Prevent cache-based attacks
            '--no-progress',   # Disable progress to prevent terminal escape sequences
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
            
        # Find the downloaded file safely
        files = list(output_dir.glob("*"))
        if not files:
            return False, "No se encontró el archivo descargado", Path()
            
        # Get the most recently modified file
        latest_file = max(files, key=lambda x: x.stat().st_mtime)
        
        # Validate the file extension
        allowed_extensions = {'.mp4', '.mkv', '.webm', '.mov'}
        if latest_file.suffix.lower() not in allowed_extensions:
            latest_file.unlink()  # Remove file if extension not allowed
            return False, "Tipo de archivo no permitido", Path()
            
        return True, "Descarga exitosa", latest_file
        
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return False, f"Error: {str(e)}", Path()

def ensure_directories(dirs: list[Path]):
    """Ensure all required directories exist and have proper permissions."""
    for dir_path in dirs:
        dir_path.mkdir(mode=0o755, exist_ok=True)  # Set secure permissions
