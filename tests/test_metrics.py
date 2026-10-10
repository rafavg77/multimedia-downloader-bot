"""Tests for Prometheus metrics and platform detection in Multimedia Downloader Bot."""

import pytest
from prometheus_client import REGISTRY, generate_latest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from metrics import (
    detect_platform,
    categorize_error,
    record_request,
    record_unauthorized_attempt,
    record_download_start,
    record_download_result,
    record_transcode_start,
    record_transcode_result,
    record_telegram_upload,
    set_authorized_users_count,
    update_uptime,
    ACTIVE_DOWNLOADS,
    ACTIVE_TRANSCODES,
    LAST_DOWNLOAD_SUCCESS,
    LAST_DOWNLOAD_DURATION_SECONDS,
    LAST_DOWNLOAD_SIZE_BYTES,
    BOT_AUTHORIZED_USERS,
)


class TestPlatformDetection:
    def test_youtube_urls(self):
        assert detect_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "youtube"
        assert detect_platform("https://youtu.be/dQw4w9WgXcQ") == "youtube"
        assert detect_platform("https://m.youtube.com/shorts/abcdef12345") == "youtube"

    def test_tiktok_urls(self):
        assert detect_platform("https://www.tiktok.com/@user/video/1234567890") == "tiktok"
        assert detect_platform("https://vt.tiktok.com/ZS123456/") == "tiktok"

    def test_instagram_urls(self):
        assert detect_platform("https://www.instagram.com/reel/C1234567890/") == "instagram"
        assert detect_platform("https://instagram.com/p/B1234567890/") == "instagram"

    def test_x_twitter_urls(self):
        assert detect_platform("https://x.com/user/status/1234567890") == "x_twitter"
        assert detect_platform("https://twitter.com/user/status/1234567890") == "x_twitter"

    def test_facebook_urls(self):
        assert detect_platform("https://www.facebook.com/watch/?v=1234567890") == "facebook"
        assert detect_platform("https://fb.watch/1234567890/") == "facebook"

    def test_reddit_urls(self):
        assert detect_platform("https://www.reddit.com/r/videos/comments/123456/title/") == "reddit"
        assert detect_platform("https://redd.it/123456") == "reddit"

    def test_dailymotion_urls(self):
        assert detect_platform("https://www.dailymotion.com/video/x123456") == "dailymotion"

    def test_flixgaze_urls(self):
        assert detect_platform("https://www.flixgaze.com/embed/123456") == "flixgaze"

    def test_dramatip_urls(self):
        assert detect_platform("https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado") == "dramatip"
        assert detect_platform("https://dramatip.net/es/series/mi-hermana-creyo-haber-ganado-hasta-que-nacio-mi-heredero-dorado/episode-2") == "dramatip"

    def test_unknown_and_invalid(self):
        assert detect_platform("https://example.com/video.mp4") == "other"
        assert detect_platform("") == "unknown"


class TestErrorCategorization:
    def test_error_categories(self):
        assert categorize_error("Unsupported URL: https://invalid.com") == "unsupported_url"
        assert categorize_error("Rate-limit reached, login required") == "auth_or_ratelimit"
        assert categorize_error("Not found. Video is removed") == "not_found"
        assert categorize_error("File too_large: exceeds limit") == "size_limit"
        assert categorize_error("ffmpeg transcode failed with error 1") == "transcode_error"
        assert categorize_error("Connection timeout") == "timeout"
        assert categorize_error("Network connection reset") == "network_error"
        assert categorize_error("Random unforeseen issue") == "general_error"


class TestMetricsRecording:
    def test_requests_metrics(self):
        record_request("url", "authorized")
        record_request("command_start", "authorized")
        record_unauthorized_attempt("/admin")

        metrics_text = generate_latest(REGISTRY).decode("utf-8")
        assert "mediabot_requests_total" in metrics_text
        assert 'type="url"' in metrics_text
        assert 'type="command_start"' in metrics_text
        assert 'mediabot_unauthorized_attempts_total{command="/admin"}' in metrics_text

    def test_download_pipeline_metrics(self):
        # Start download
        record_download_start("youtube")
        assert ACTIVE_DOWNLOADS._value.get() >= 1

        # Successful download
        record_download_result(
            platform="youtube",
            action="send",
            success=True,
            duration=3.5,
            size_bytes=10485760,  # 10 MB
        )
        assert LAST_DOWNLOAD_SUCCESS._value.get() == 1
        assert LAST_DOWNLOAD_DURATION_SECONDS._value.get() == 3.5
        assert LAST_DOWNLOAD_SIZE_BYTES._value.get() == 10485760

        # Failed download
        record_download_start("instagram")
        record_download_result(
            platform="instagram",
            action="save",
            success=False,
            duration=1.2,
            error_msg="Rate-limit reached, login required",
        )
        assert LAST_DOWNLOAD_SUCCESS._value.get() == 0

        metrics_text = generate_latest(REGISTRY).decode("utf-8")
        assert 'mediabot_downloads_total{action="send",platform="youtube",status="success"}' in metrics_text
        assert 'mediabot_downloads_total{action="save",platform="instagram",status="failed"}' in metrics_text
        assert 'mediabot_errors_total{category="auth_or_ratelimit",platform="instagram"}' in metrics_text

    def test_transcode_and_upload_metrics(self):
        record_transcode_start()
        record_transcode_result(success=True, duration=2.1)
        record_telegram_upload(status="success", duration=1.4)

        metrics_text = generate_latest(REGISTRY).decode("utf-8")
        assert 'mediabot_transcodes_total{status="success"}' in metrics_text
        assert 'mediabot_telegram_uploads_total{status="success"}' in metrics_text

    def test_user_count_and_uptime(self):
        set_authorized_users_count(5)
        assert BOT_AUTHORIZED_USERS._value.get() == 5

        update_uptime()
        metrics_text = generate_latest(REGISTRY).decode("utf-8")
        assert "mediabot_authorized_users_total 5.0" in metrics_text
        assert "mediabot_uptime_seconds" in metrics_text
