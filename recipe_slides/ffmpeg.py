from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from .candidates import (
    FrameCandidate,
    acceptable,
    analyze_frame,
    rank_burst_frames,
    remove_duplicates,
    save_manifest,
    select_frame_finder_output,
)


class FFmpegError(RuntimeError):
    pass


def tools_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def video_duration(video_path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise FFmpegError(result.stderr.strip() or "ffprobe could not read the video")
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FFmpegError("Could not determine video duration") from error


def validate_analysis_range(
    duration: float, start_time: float = 0.0, end_time: float | None = None
) -> tuple[float, float]:
    if duration <= 0:
        raise ValueError("duration must be positive")
    start = max(0.0, float(start_time))
    end = duration if end_time is None else min(duration, float(end_time))
    if start >= end:
        raise ValueError("analysis start must be before analysis end")
    return start, end


def clip_scenes_to_range(
    scenes: list[tuple[float, float]], start_time: float, end_time: float
) -> list[tuple[float, float]]:
    """Return only the portions of scenes that intersect an analysis range."""
    clipped = []
    for start, end in scenes:
        clipped_start = max(start, start_time)
        clipped_end = min(end, end_time)
        if clipped_end - clipped_start >= 0.10:
            clipped.append((clipped_start, clipped_end))
    return clipped


def detect_scenes(
    video_path: Path,
    duration: float,
    threshold: float = 0.30,
    *,
    start_time: float = 0.0,
    end_time: float | None = None,
) -> list[tuple[float, float]]:
    """Detect scene boundaries with FFmpeg's scene score filter."""
    start, end = validate_analysis_range(duration, start_time, end_time)
    if start == 0.0 and end == duration:
        video_filter = f"select='gt(scene,{threshold})',showinfo"
        time_offset = 0.0
    else:
        video_filter = (
            f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            f"select='gt(scene,{threshold})',showinfo"
        )
        time_offset = start
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video_path),
        "-filter:v", video_filter, "-f", "null", "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        raise FFmpegError(result.stderr.strip() or "FFmpeg could not detect scenes")
    changes = [
        float(value) + time_offset
        for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", result.stderr)
    ]
    boundaries = [start] + [value for value in changes if start + 0.05 < value < end - 0.05] + [end]
    boundaries = sorted(set(boundaries))
    return [(start, end) for start, end in zip(boundaries, boundaries[1:]) if end - start >= 0.10]


def scene_sample_timestamps(
    scenes: list[tuple[float, float]], samples_per_scene: int = 3, stable_fraction: float = 0.5
) -> list[tuple[float, tuple[float, float]]]:
    if samples_per_scene < 1 or not 0 < stable_fraction <= 1:
        raise ValueError("samples_per_scene must be positive and stable_fraction must be in (0, 1]")
    samples: list[tuple[float, tuple[float, float]]] = []
    for scene in scenes:
        start, end = scene
        span = end - start
        stable_start = start + span * (1 - stable_fraction) / 2
        stable_end = end - span * (1 - stable_fraction) / 2
        for index in range(samples_per_scene):
            timestamp = stable_start + (index + 0.5) * (stable_end - stable_start) / samples_per_scene
            samples.append((min(max(timestamp, start), end), scene))
    return samples


def extract_frame(video_path: Path, destination: Path, timestamp: float) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, timestamp):.3f}",
        "-i", str(video_path), "-frames:v", "1", "-vf",
        "scale=1920:1920:force_original_aspect_ratio=decrease", "-q:v", "2", "-y", str(destination),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode or not destination.exists():
        raise FFmpegError(result.stderr.strip() or "Failed to extract frame")
    return destination


def extract_candidate_frames(
    video_path: Path, output_dir: Path, samples_per_scene: int = 3, step_count: int = 1
) -> list[FrameCandidate]:
    if not tools_available():
        raise FFmpegError("FFmpeg and ffprobe must be installed and available on PATH")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in output_dir.glob("frame-*.jpg"):
        old_frame.unlink()

    duration = video_duration(video_path)
    scenes = detect_scenes(video_path, duration)
    samples_per_scene = max(samples_per_scene, math.ceil(step_count * 4 / max(1, len(scenes))))
    analyzed: list[FrameCandidate] = []
    for index, (timestamp, scene) in enumerate(scene_sample_timestamps(scenes, samples_per_scene), 1):
        destination = output_dir / f"frame-{index:04d}-{timestamp:010.3f}.jpg"
        extract_frame(video_path, destination, timestamp)
        candidate = analyze_frame(destination, timestamp, scene)
        if acceptable(candidate):
            analyzed.append(candidate)
        else:
            destination.unlink(missing_ok=True)
    candidates = remove_duplicates(analyzed)
    kept = {item.path for item in candidates}
    for item in analyzed:
        if item.path not in kept:
            (output_dir / item.path).unlink(missing_ok=True)
    save_manifest(output_dir / "manifest.json", candidates, duration)
    return candidates
BURST_OFFSETS = (-0.5, -0.25, 0.0, 0.25, 0.5)


def extract_frame_finder_candidates(
    video_path: Path,
    output_dir: Path,
    target_count: int,
    *,
    start_time: float = 0.0,
    end_time: float | None = None,
) -> list[FrameCandidate]:
    """Extract a burst around each scene midpoint and retain its clearest frame."""
    if not tools_available():
        raise FFmpegError("FFmpeg and ffprobe must be installed and available on PATH")
    if target_count < 1:
        raise ValueError("target_count must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in output_dir.glob("frame-*.jpg"):
        old_frame.unlink()

    duration = video_duration(video_path)
    analysis_start, analysis_end = validate_analysis_range(duration, start_time, end_time)
    scenes = detect_scenes(
        video_path,
        duration,
        start_time=analysis_start,
        end_time=analysis_end,
    )
    representatives: list[FrameCandidate] = []
    extracted_paths: list[Path] = []
    for scene_index, scene in enumerate(scenes, 1):
        start, end = scene
        scene_duration = end - start
        if scene_duration < 0.5:
            continue
        midpoint = (start + end) / 2
        burst: list[FrameCandidate] = []
        used_timestamps: set[float] = set()
        for burst_index, offset in enumerate(BURST_OFFSETS, 1):
            timestamp = min(max(midpoint + offset, start + 0.04), end - 0.04)
            timestamp = min(max(0.0, timestamp), max(0.0, duration - 0.05))
            rounded = round(timestamp, 3)
            if rounded in used_timestamps:
                continue
            used_timestamps.add(rounded)
            destination = output_dir / (
                f"frame-burst-{scene_index:04d}-{burst_index}-{timestamp:010.3f}.jpg"
            )
            extract_frame(video_path, destination, timestamp)
            extracted_paths.append(destination)
            candidate = analyze_frame(destination, timestamp, scene)
            candidate.in_analysis_range = True
            boundary_distance = min(timestamp - start, end - timestamp)
            candidate.stability = min(1.0, max(0.0, boundary_distance / 0.5))
            burst.append(candidate)
        ranked_burst = rank_burst_frames(burst)
        if ranked_burst:
            representatives.append(ranked_burst[0])

    candidates = select_frame_finder_output(representatives, target_count)

    outside_ranges = []
    if analysis_start >= 0.5:
        outside_ranges.append((0.0, analysis_start, "cover"))
    if duration - analysis_end >= 0.5:
        outside_ranges.append((analysis_end, duration, "closing"))
    for range_start, range_end, label in outside_ranges:
        midpoint = (range_start + range_end) / 2
        burst = []
        for burst_index, offset in enumerate(BURST_OFFSETS, 1):
            timestamp = min(max(midpoint + offset, range_start + 0.04), range_end - 0.04)
            destination = output_dir / (
                f"frame-outside-{label}-{burst_index}-{timestamp:010.3f}.jpg"
            )
            if destination in extracted_paths:
                continue
            extract_frame(video_path, destination, timestamp)
            extracted_paths.append(destination)
            candidate = analyze_frame(destination, timestamp, (range_start, range_end))
            candidate.in_analysis_range = False
            boundary_distance = min(timestamp - range_start, range_end - timestamp)
            candidate.stability = min(1.0, max(0.0, boundary_distance / 0.5))
            burst.append(candidate)
        ranked = rank_burst_frames(burst)
        if ranked:
            candidates.append(ranked[0])

    candidates.sort(key=lambda item: item.timestamp)
    kept = {item.path for item in candidates}
    for path in extracted_paths:
        if path.name not in kept:
            path.unlink(missing_ok=True)
    save_manifest(output_dir / "manifest.json", candidates, duration)
    return candidates
