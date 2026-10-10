"""Tests for DramaTip extractor and stream resolver."""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from downloader import (
    validate_url,
    _decrypt_dramatip_enc,
    _resolve_dramatip_stream,
    _prepare_download_target,
    DRAMATIP_PATH_RE,
)


class TestDramaTipExtraction:
    def test_validate_url(self):
        assert validate_url("https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado") is True
        assert validate_url("https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado/episode-2") is True
        assert validate_url("https://sub.dramatip.net/series/test-slug") is True
        assert validate_url("https://invalid-site.com/video") is False

    def test_path_regex(self):
        m1 = DRAMATIP_PATH_RE.match("/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado")
        assert m1 is not None
        assert m1.group(1) == "es"
        assert m1.group(2) == "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado"
        assert m1.group(3) is None

        m2 = DRAMATIP_PATH_RE.match("/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado/episode-5")
        assert m2 is not None
        assert m2.group(1) == "es"
        assert m2.group(2) == "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado"
        assert m2.group(3) == "5"

        m3 = DRAMATIP_PATH_RE.match("/series/simple-slug/episode-12/")
        assert m3 is not None
        assert m3.group(1) is None
        assert m3.group(2) == "simple-slug"
        assert m3.group(3) == "12"

    def test_decrypt_enc(self):
        # Known encrypted vector for chapter 1 of "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado"
        enc = "xPKC48ziBfLuqUOePqlY5v8IqrUk7ztMKXqZk7GUbzvibnXehC30+xfVhqYrLI/x9tjOp1qaAgnDd0tR4ILVh6/Xp9wT/eFdNidWtSh1ThZMCRwBtsermluAFx8L54n6CmcxAXseaYz2WEvsayfe4XJGFjLbQA=="
        decrypted = _decrypt_dramatip_enc(enc)
        assert decrypted == "https://akamai-static.shorttv.live/hls/26746e75-d9a9-4dd1-a887-da9145d3e360_1080/main.m3u8"

    def test_resolve_live_stream(self):
        url = "https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado"
        stream_url, headers, custom_title = _resolve_dramatip_stream(url)
        assert "akamai-static.shorttv.live" in stream_url
        assert stream_url.endswith(".m3u8")
        assert "Referer" in headers
        assert "User-Agent" in headers
        assert custom_title == "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado-capitulo-1"

    def test_prepare_download_target_integration(self):
        url = "https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado/episode-2"
        stream_url, headers, custom_title = _prepare_download_target(url)
        assert "akamai-static.shorttv.live" in stream_url
        assert custom_title == "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado-capitulo-2"

    def test_get_series_info(self):
        from downloader import get_dramatip_series_info
        url = "https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado"
        info = get_dramatip_series_info(url)
        assert info is not None
        assert info["book_id"] == "43167"
        assert info["total_episodes"] == 25
        assert info["episodes"] == list(range(1, 26))
        assert "Mi hermana creyó haber ganado" in info["title"]

    def test_resolve_episode_stream(self):
        from downloader import _resolve_dramatip_episode_stream
        stream_url, headers, custom_title = _resolve_dramatip_episode_stream(
            netloc="dramatip.net",
            book_id="43167",
            slug="mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado",
            lang="es",
            episode=5,
        )
        assert "akamai-static.shorttv.live" in stream_url
        assert custom_title == "mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado-capitulo-5"
