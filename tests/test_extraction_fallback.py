import shutil
import subprocess
from pathlib import Path

import pytest

from recipe_slides.analysis_settings import AnalysisSettings, load_settings
from recipe_slides.ffmpeg import extract_frame_finder_candidates, interval_windows

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is not installed",
)


def _make_video(path: Path, source: str, seconds: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"{source}:size=640x360:rate=30:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path


def test_interval_windows_cover_range() -> None:
    windows = interval_windows(0.0, 4.0, 1.5)
    assert [window for _, window in windows] == [(0.0, 1.5), (1.5, 3.0), (3.0, 4.0)]


def test_settings_validation_and_relaxation() -> None:
    with pytest.raises(ValueError):
        AnalysisSettings(scene_threshold=0)
    relaxed = AnalysisSettings().relaxed(2)
    assert relaxed.min_sharpness == 0.0 and relaxed.max_brightness == 1.0


def test_load_settings_reads_config_file(tmp_path: Path) -> None:
    config = tmp_path / "analysis_settings.json"
    config.write_text('{"scene_threshold": 0.5, "max_hash_distance": 3, "unknown": 1}')
    loaded = load_settings(config)
    assert loaded.scene_threshold == 0.5 and loaded.max_hash_distance == 3


@needs_ffmpeg
def test_continuous_clip_falls_back_to_interval_sampling(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "continuous.mp4", "testsrc2", 15)
    found = extract_frame_finder_candidates(video, tmp_path / "frames", 8, settings=AnalysisSettings())
    assert len(found) >= 6
    assert all(item.in_analysis_range for item in found)


@needs_ffmpeg
def test_all_rejected_frames_relax_instead_of_empty(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "dark.mp4", "color=c=0x050505", 6)
    found = extract_frame_finder_candidates(video, tmp_path / "frames", 4, settings=AnalysisSettings())
    assert found
