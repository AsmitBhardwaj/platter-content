from pathlib import Path

import pytest

from recipe_slides.youtube import (
    DOWNLOAD_FORMAT,
    YouTubeDownloadError,
    download_youtube_video,
    friendly_download_error,
    is_same_youtube_video,
    is_valid_youtube_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtube.com/shorts/abc123",
        "https://m.youtube.com/watch?v=abc123&feature=share",
        "https://youtu.be/abc123",
        "https://www.youtube.com/embed/abc123",
        "https://www.youtube-nocookie.com/embed/abc123",
        "https://www.youtube.com/live/abc123",
    ],
)
def test_accepts_supported_youtube_urls(url: str) -> None:
    assert is_valid_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a URL",
        "https://example.com/watch?v=abc123",
        "https://youtube.com.evil.example/watch?v=abc123",
        "https://www.youtube.com/playlist?list=abc123",
        "ftp://youtu.be/abc123",
    ],
)
def test_rejects_non_video_or_non_youtube_urls(url: str) -> None:
    assert not is_valid_youtube_url(url)


def test_equivalent_youtube_links_identify_the_same_cached_source() -> None:
    assert is_same_youtube_video(
        "https://www.youtube.com/watch?v=abc123&feature=share",
        "https://youtu.be/abc123",
    )
    assert not is_same_youtube_video(
        "https://youtu.be/abc123",
        "https://youtu.be/different",
    )


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("ERROR: Private video", "private"),
        ("Sign in to confirm your age", "age-restricted"),
        ("ERROR: Video unavailable", "unavailable"),
        ("Requested format is not available", "requested quality"),
        ("HTTP Error 500", "download failed"),
    ],
)
def test_download_errors_are_mapped_to_useful_messages(detail: str, expected: str) -> None:
    assert expected in friendly_download_error(detail)


def test_real_yt_dlp_message_is_surfaced() -> None:
    message = friendly_download_error(
        "\x1b[0;31mERROR:\x1b[0m [youtube] abc: Sign in to confirm you\u2019re not a bot"
    )
    assert "yt-dlp: [youtube] abc: Sign in to confirm" in message
    assert "\x1b" not in message


def test_download_wraps_yt_dlp_errors_and_cleans_partial_files(tmp_path: Path) -> None:
    class FailingDownloader:
        def __init__(self, options: dict[str, object]) -> None:
            self.options = options

        def __enter__(self) -> "FailingDownloader":
            (tmp_path / "youtube-download.mp4.part").write_bytes(b"partial")
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, object]:
            raise RuntimeError("ERROR: Private video")

    with pytest.raises(YouTubeDownloadError, match="private"):
        download_youtube_video(
            "https://youtu.be/abc123",
            tmp_path,
            ydl_factory=FailingDownloader,
        )

    assert not list(tmp_path.glob("youtube-download*"))


def test_download_returns_local_video_title_and_thumbnail(tmp_path: Path) -> None:
    captured_options: dict[str, object] = {}
    progress_updates: list[tuple[float, str]] = []

    class SuccessfulDownloader:
        def __init__(self, options: dict[str, object]) -> None:
            self.options = options
            captured_options.update(options)

        def __enter__(self) -> "SuccessfulDownloader":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def extract_info(self, url: str, download: bool) -> dict[str, object]:
            hook = self.options["progress_hooks"][0]  # type: ignore[index]
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "finished"})
            template = str(self.options["outtmpl"])
            Path(template.replace("%(ext)s", "mp4")).write_bytes(b"video")
            Path(template.replace("%(ext)s", "webp")).write_bytes(b"thumbnail")
            return {"title": "Test recipe video"}

    result = download_youtube_video(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path,
        lambda update: progress_updates.append((update.fraction, update.message)),
        ydl_factory=SuccessfulDownloader,
    )

    assert result.title == "Test recipe video"
    assert result.video_path == tmp_path / "source-youtube.mp4"
    assert result.video_path.read_bytes() == b"video"
    assert result.thumbnail_path == tmp_path / "thumbnail.webp"
    assert captured_options["format"] == DOWNLOAD_FORMAT
    assert "+ba[" in DOWNLOAD_FORMAT and DOWNLOAD_FORMAT.endswith("/b")
    assert captured_options["merge_output_format"] == "mp4"
    assert progress_updates[-1] == (1.0, "Download complete")
    assert any("Downloading video" in message for _, message in progress_updates)
