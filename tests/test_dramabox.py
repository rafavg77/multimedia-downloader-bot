"""Tests for DramaBox extractor and stream resolver."""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from downloader import (
    validate_url,
    get_dramabox_series_info,
    _resolve_dramabox_stream,
    _prepare_download_target,
    DRAMABOX_PATH_RE,
)
from metrics import detect_platform


class TestDramaBoxExtraction:
    def test_validate_url(self):
        assert validate_url("https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado") is True
        assert validate_url("https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1") is True
        assert validate_url("https://dramaboxdb.com/movie/41000120981") is True
        assert validate_url("https://invalid-site.com/movie/123") is False

    def test_detect_platform(self):
        assert detect_platform("https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado") == "dramabox"
        assert detect_platform("https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1") == "dramabox"

    def test_path_regex(self):
        m1 = DRAMABOX_PATH_RE.match("/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado")
        assert m1 is not None
        lang, m_bid, m_slug, ep_bid, ep_slug, ch_id, ep_num = m1.groups()
        assert lang == "es"
        assert m_bid == "41000120981"
        assert "el-dolor" in m_slug
        assert ep_num is None

        m2 = DRAMABOX_PATH_RE.match("/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126914_Episode-14")
        assert m2 is not None
        lang, m_bid, m_slug, ep_bid, ep_slug, ch_id, ep_num = m2.groups()
        assert lang == "es"
        assert ep_bid == "41000120981"
        assert ch_id == "600126914"
        assert ep_num == "14"

    def test_get_series_info(self):
        url = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado"
        info = get_dramabox_series_info(url)
        assert info is not None
        assert info["platform"] == "dramabox"
        assert info["book_id"] == "41000120981"
        assert info["total_episodes"] == 75
        assert info["unlocked_count"] == 13
        assert info["episodes"] == list(range(1, 76))
        assert "El dolor después del adiós" in info["title"]
        assert info["chapters"][1]["unlock"] is True
        assert info["chapters"][14]["unlock"] is False

    def test_resolve_unlocked_stream(self):
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1"
        stream_url, headers, custom_title = _resolve_dramabox_stream(url)
        assert "dramaboxdb.com" in stream_url
        assert ".mp4" in stream_url
        assert "User-Agent" in headers
        assert custom_title == "el-dolor-despues-del-adios-doblado-capitulo-1"

    def test_resolve_locked_stream_free_preview(self):
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126914_Episode-14"
        stream_url, headers, custom_title = _resolve_dramabox_stream(url)
        assert "dramaboxdb.com" in stream_url
        assert "nav2.15s.mp4" in stream_url
        assert custom_title == "el-dolor-despues-del-adios-doblado-capitulo-14"

    def test_prepare_download_target_integration(self):
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1"
        stream_url, headers, custom_title = _prepare_download_target(url)
        assert "dramaboxdb.com" in stream_url
        assert custom_title == "el-dolor-despues-del-adios-doblado-capitulo-1"
