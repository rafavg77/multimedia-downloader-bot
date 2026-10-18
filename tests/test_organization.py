"""Tests for platform folders and Jellyfin series organization."""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from downloader import (
    get_platform_folder,
    extract_series_slug,
    _normalize_slug,
)
from metrics import detect_platform


def test_get_platform_folder():
    assert get_platform_folder("youtube") == "youtube"
    assert get_platform_folder("facebook") == "facebook"
    assert get_platform_folder("tiktok") == "tiktok"
    assert get_platform_folder("dramatip") == "dramatip"
    assert get_platform_folder("dramabox") == "dramabox"
    assert get_platform_folder("instagram") == "instagram"
    assert get_platform_folder("dailymotion") == "dailymotion"
    assert get_platform_folder("x_twitter") == "twitter"
    assert get_platform_folder("twitter") == "twitter"
    assert get_platform_folder("unknown") == "unknown"


def test_detect_platform_and_folder_integration():
    url_yt = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert get_platform_folder(detect_platform(url_yt)) == "youtube"

    url_fb = "https://www.facebook.com/watch/?v=123456789"
    assert get_platform_folder(detect_platform(url_fb)) == "facebook"

    url_tt = "https://www.tiktok.com/@user/video/7675509752880844052"
    assert get_platform_folder(detect_platform(url_tt)) == "tiktok"

    url_db = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despues-del-adios-doblado"
    assert get_platform_folder(detect_platform(url_db)) == "dramabox"

    url_dt = "https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado"
    assert get_platform_folder(detect_platform(url_dt)) == "dramatip"


def test_extract_series_slug_dramabox():
    url_movie = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despues-del-adios-doblado"
    assert extract_series_slug(url_movie, "dramabox") == "el-dolor-despues-del-adios-doblado"

    url_ep = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despues-del-adios-doblado/600126901_Episode-1"
    assert extract_series_slug(url_ep, "dramabox") == "el-dolor-despues-del-adios-doblado"

    # URL without slug should fallback to book_id
    url_id_only = "https://www.dramaboxdb.com/es/movie/41000120981"
    assert extract_series_slug(url_id_only, "dramabox") == "41000120981"


def test_extract_series_slug_dramatip():
    url_series = "https://dramatip.net/es/series/mi-serie-favorita"
    assert extract_series_slug(url_series, "dramatip") == "mi-serie-favorita"

    url_ep = "https://dramatip.net/es/series/mi-serie-favorita/episode-5"
    assert extract_series_slug(url_ep, "dramatip") == "mi-serie-favorita"


def test_extract_series_slug_other_platforms():
    url_yt = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert extract_series_slug(url_yt, "youtube") is None

    url_fb = "https://www.facebook.com/watch/?v=123456789"
    assert extract_series_slug(url_fb, "facebook") is None

    url_tt = "https://www.tiktok.com/@user/video/7675509752880844052"
    assert extract_series_slug(url_tt, "tiktok") is None
