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
            '-f', 'best',
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
