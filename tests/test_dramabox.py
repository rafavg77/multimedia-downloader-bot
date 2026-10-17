"""Tests for DramaBox extractor and stream resolver."""

import json
import pytest
import sys
import urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import downloader
from downloader import (
    validate_url,
    extract_first_url,
    get_dramabox_series_info,
    _resolve_dramabox_stream,
    _resolve_dramabox_episode_stream,
    _prepare_download_target,
    DRAMABOX_PATH_RE,
)
from metrics import detect_platform


MOCK_MOVIE_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "bookInfo": {
        "bookId": "41000120981",
        "bookName": "El dolor después del adiós (Doblado)",
        "chapterCount": 2,
        "cover": "https://thwztvideo.dramaboxdb.com/cover.jpg"
      },
      "chapterList": [
        {
          "id": "600126901",
          "name": "Capítulo 1",
          "index": 0,
          "indexStr": "001",
          "unlock": true,
          "mp4": "https://hwvideoseo.dramaboxdb.com/sample_ep1.mp4",
          "m3u8Url": "https://hwzthls.dramaboxdb.com/sample_ep1.m3u8",
          "duration": 98000
        },
        {
          "id": "600126902",
          "name": "Capítulo 2",
          "index": 1,
          "indexStr": "002",
          "unlock": false,
          "mp4": null,
          "m3u8Url": null,
          "duration": 56000
        }
      ]
    }
  }
}
</script>
</head>
<body></body>
</html>
"""

MOCK_EP2_PAGE_HTML = """
<!DOCTYPE html>
<html>
<head>
<script id="__NEXT_DATA__" type="application/json">
{
  "props": {
    "pageProps": {
      "chapterId": "600126902",
      "freeSource": "https://hwztvideo.dramaboxdb.com/sample_ep2.nav2.15s.mp4"
    }
  }
}
</script>
</head>
<body></body>
</html>
"""


class TestDramaBoxExtraction:
    def test_validate_url(self):
        assert validate_url("https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado") is True
        assert validate_url("https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1") is True
        assert validate_url("https://dramaboxdb.com/movie/41000120981") is True
        assert validate_url("https://invalid-site.com/movie/123") is False

    def test_detect_platform(self):
        assert detect_platform("https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado") == "dramabox"
        assert detect_platform("https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1") == "dramabox"

    def test_extract_first_url(self):
        raw_accented = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-después-del-adiós-doblado"
        expected = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado"
        assert extract_first_url(raw_accented) == expected
        assert extract_first_url(f"Mira este drama: {raw_accented}!") == expected
        assert extract_first_url("Texto sin ninguna url") is None
        assert extract_first_url("") is None

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

    def test_get_series_info_mocked(self, monkeypatch):
        monkeypatch.setattr(downloader, "_fetch_text", lambda *args, **kwargs: MOCK_MOVIE_PAGE_HTML)
        url = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado"
        info = get_dramabox_series_info(url)
        assert info is not None
        assert info["platform"] == "dramabox"
        assert info["book_id"] == "41000120981"
        assert info["total_episodes"] == 2
        assert info["unlocked_count"] == 1
        assert info["episodes"] == [1, 2]
        assert "El dolor después del adiós" in info["title"]
        assert info["chapters"][1]["unlock"] is True
        assert info["chapters"][2]["unlock"] is False

    def test_resolve_unlocked_stream_mocked(self, monkeypatch):
        monkeypatch.setattr(downloader, "_fetch_text", lambda *args, **kwargs: MOCK_MOVIE_PAGE_HTML)
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1"
        stream_url, headers, custom_title = _resolve_dramabox_stream(url)
        assert stream_url == "https://hwvideoseo.dramaboxdb.com/sample_ep1.mp4"
        assert "User-Agent" in headers
        assert custom_title == "el-dolor-despues-del-adios-doblado - S01E01"

    def test_resolve_locked_stream_free_preview_mocked(self, monkeypatch):
        def mock_fetch(url, referer=None):
            if "/ep/" in url:
                return MOCK_EP2_PAGE_HTML
            return MOCK_MOVIE_PAGE_HTML

        monkeypatch.setattr(downloader, "_fetch_text", mock_fetch)
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126902_Episode-2"
        stream_url, headers, custom_title = _resolve_dramabox_stream(url)
        assert stream_url == "https://hwztvideo.dramaboxdb.com/sample_ep2.nav2.15s.mp4"
        assert custom_title == "el-dolor-despues-del-adios-doblado - S01E02"

    def test_prepare_download_target_integration_mocked(self, monkeypatch):
        monkeypatch.setattr(downloader, "_fetch_text", lambda *args, **kwargs: MOCK_MOVIE_PAGE_HTML)
        url = "https://www.dramaboxdb.com/es/ep/41000120981_el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado/600126901_Episode-1"
        stream_url, headers, custom_title = _prepare_download_target(url)
        assert stream_url == "https://hwvideoseo.dramaboxdb.com/sample_ep1.mp4"
        assert custom_title == "el-dolor-despues-del-adios-doblado - S01E01"

    def test_live_network_probe(self):
        """Attempts live probe if network/CDN permits, skips cleanly on 403 or network restriction."""
        url = "https://www.dramaboxdb.com/es/movie/41000120981/el-dolor-despu%C3%A9s-del-adi%C3%B3s-doblado"
        try:
            info = get_dramabox_series_info(url)
            if info is None:
                pytest.skip("DramaBox returned empty or blocked response to this IP")
            assert info["total_episodes"] >= 75
            assert info["unlocked_count"] >= 10
        except urllib.error.HTTPError as e:
            if e.code == 403:
                pytest.skip(f"DramaBox blocked IP: {e}")
            raise
