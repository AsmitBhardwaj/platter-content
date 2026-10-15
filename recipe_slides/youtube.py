from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


class YouTubeDownloadError(RuntimeError):
    """A download failure with a safe, user-facing message."""


@dataclass(frozen=True)
class DownloadProgress:
    fraction: float
    message: str


@dataclass(frozen=True)
class YouTubeDownload:
    video_path: Path
    title: str
    thumbnail_path: Path | None


ProgressCallback = Callable[[DownloadProgress], None]

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def youtube_video_id(value: str) -> str | None:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in _YOUTUBE_HOSTS:
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname == "youtu.be":
        return path_parts[0] if len(path_parts) == 1 else None
    if parsed.path.rstrip("/") == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        return video_id or None
    if len(path_parts) == 2 and path_parts[0] in {"shorts", "embed", "live", "v"}:
        return path_parts[1]
    return None


def is_valid_youtube_url(value: str) -> bool:
    return youtube_video_id(value) is not None


def is_same_youtube_video(first: str, second: str) -> bool:
    first_id = youtube_video_id(first)
    return first_id is not None and first_id == youtube_video_id(second)


def friendly_download_error(error: BaseException | str) -> str:
    detail = str(error).lower()
    if any(marker in detail for marker in ("private video", "video is private")):
        return "This YouTube video is private. Use a public video or upload the file locally."
    if any(
        marker in detail
        for marker in ("confirm your age", "age-restricted", "age restricted", "inappropriate content")
    ):
        return (
            "This video is age-restricted and cannot be downloaded without account cookies. "
            "For privacy, this app does not accept cookies; upload the video locally instead."
        )
    if any(
        marker in detail
        for marker in (
            "video unavailable",
            "video is unavailable",
            "not available in your country",
            "removed by the uploader",
            "copyright claim",
        )
    ):
        return "This YouTube video is unavailable or restricted in your region."
    if "requested format is not available" in detail:
        return "YouTube did not offer an MP4-compatible version of this video."
    if any(marker in detail for marker in ("unable to download webpage", "timed out", "name resolution")):
        return "Could not reach YouTube. Check your internet connection and try again."
    if any(marker in detail for marker in ("http error 403", "http error 429", "too many requests")):
        return "YouTube refused the download. Wait a while, update yt-dlp, and try again."
    return "The YouTube download failed. Check the link and your connection, then try again."


def _progress_hook(callback: ProgressCallback | None) -> Callable[[dict[str, Any]], None]:
    def hook(status: dict[str, Any]) -> None:
        if callback is None:
            return
        phase = status.get("status")
        if phase == "downloading":
            downloaded = float(status.get("downloaded_bytes") or 0)
            total = float(status.get("total_bytes") or status.get("total_bytes_estimate") or 0)
            fraction = min(0.9, (downloaded / total) * 0.9) if total else 0.05
            callback(DownloadProgress(fraction, "Downloading video-only source…"))
        elif phase == "finished":
            callback(DownloadProgress(0.95, "Saving temporary source…"))
        elif phase == "error":
            callback(DownloadProgress(0.0, "Download failed"))

    return hook


def _clean_temporary_downloads(output_dir: Path) -> None:
    for path in output_dir.glob("youtube-download*"):
        if path.is_file():
            path.unlink()


def download_youtube_video(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    *,
    ydl_factory: Callable[[dict[str, Any]], Any] | None = None,
) -> YouTubeDownload:
    if not is_valid_youtube_url(url):
        raise ValueError("Enter a valid YouTube video URL.")

    if ydl_factory is None:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise YouTubeDownloadError(
                "yt-dlp is not installed. Install the project requirements and restart the app."
            ) from error

        ydl_factory = YoutubeDL

    output_dir.mkdir(parents=True, exist_ok=True)
    _clean_temporary_downloads(output_dir)
    output_template = str(output_dir / "youtube-download.%(ext)s")
    options: dict[str, Any] = {
        # Strictly video-only: audio is unnecessary for candidate frame extraction.
        "format": "bestvideo[height<=1080][ext=mp4]",
        "outtmpl": output_template,
        "noplaylist": True,
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook(progress_callback)],
    }

    try:
        with ydl_factory(options) as downloader:
            info = downloader.extract_info(url.strip(), download=True)
    except Exception as error:
        _clean_temporary_downloads(output_dir)
        raise YouTubeDownloadError(friendly_download_error(error)) from error

    video_path = output_dir / "youtube-download.mp4"
    if not video_path.exists():
        _clean_temporary_downloads(output_dir)
        raise YouTubeDownloadError(
            "The download completed but no MP4 video was produced. Try uploading the video locally."
        )

    final_video = output_dir / "source-youtube.mp4"
    if final_video.exists():
        final_video.unlink()
    video_path.replace(final_video)

    thumbnail_path: Path | None = None
    thumbnails = sorted(output_dir.glob("youtube-download.*"))
    for thumbnail in thumbnails:
        if thumbnail.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
            candidate = output_dir / f"thumbnail{thumbnail.suffix.lower()}"
            if candidate.exists():
                candidate.unlink()
            thumbnail.replace(candidate)
            thumbnail_path = candidate
            break
    _clean_temporary_downloads(output_dir)

    title = str((info or {}).get("title") or "YouTube video")
    if progress_callback:
        progress_callback(DownloadProgress(1.0, "Download complete"))
    return YouTubeDownload(final_video, title, thumbnail_path)
