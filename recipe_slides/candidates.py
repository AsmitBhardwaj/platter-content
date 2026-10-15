from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat


@dataclass
class FrameCandidate:
    path: str
    timestamp: float
    scene_start: float
    scene_end: float
    brightness: float
    brightness_score: float
    sharpness: float
    crop_score: float
    image_hash: str
    uniqueness: float = 1.0
    stability: float = 1.0
    in_analysis_range: bool = True

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "FrameCandidate":
        return cls(**value)  # type: ignore[arg-type]


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def clamp_timestamp(seconds: float, duration: float, end_margin: float = 0.05) -> float:
    """Keep extraction timestamps inside the decodable video interval."""
    if duration <= 0:
        raise ValueError("duration must be positive")
    return min(max(0.0, seconds), max(0.0, duration - end_margin))


def brightness_metrics(image: Image.Image) -> tuple[float, float]:
    """Return mean luminance and a score favoring useful mid-range exposure."""
    mean = ImageStat.Stat(ImageOps.grayscale(image).resize((160, 160))).mean[0] / 255.0
    score = max(0.0, 1.0 - abs(mean - 0.52) / 0.52)
    return mean, score


def sharpness_score(image: Image.Image) -> float:
    """Estimate detail using the variance of a high-pass filtered luminance image."""
    gray = ImageOps.grayscale(image).resize((320, 320))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).var[0])


def crop_box(
    source_size: tuple[int, int],
    output_size: tuple[int, int] = (1080, 1440),
    x_position: float = 0.5,
    y_position: float = 0.5,
) -> tuple[int, int, int, int]:
    """Compute a cover crop, with positions ranging from 0 (start) to 1 (end)."""
    width, height = source_size
    target_ratio = output_size[0] / output_size[1]
    source_ratio = width / height
    x_position = min(1.0, max(0.0, x_position))
    y_position = min(1.0, max(0.0, y_position))
    if source_ratio > target_ratio:
        crop_width = max(1, round(height * target_ratio))
        left = round((width - crop_width) * x_position)
        return left, 0, left + crop_width, height
    crop_height = max(1, round(width / target_ratio))
    top = round((height - crop_height) * y_position)
    return 0, top, width, top + crop_height


def crop_frame(
    image: Image.Image,
    output_size: tuple[int, int] = (1080, 1440),
    x_position: float = 0.5,
    y_position: float = 0.5,
) -> Image.Image:
    box = crop_box(image.size, output_size, x_position, y_position)
    return image.convert("RGB").crop(box).resize(output_size, Image.Resampling.LANCZOS)


def crop_quality_score(image: Image.Image) -> float:
    """Favor crops that retain the source frame's visible edge/detail energy."""
    gray = ImageOps.grayscale(image).resize((320, 320))
    full = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    cropped = crop_frame(gray, (240, 320)).filter(ImageFilter.FIND_EDGES)
    retained = ImageStat.Stat(cropped).mean[0]
    if full <= 0.01:
        return 0.5
    return min(1.0, retained / full)


def difference_hash(image: Image.Image, size: int = 8) -> str:
    gray = ImageOps.grayscale(image).resize((size + 1, size), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    bits = []
    for row in range(size):
        offset = row * (size + 1)
        bits.extend(pixels[offset + col] > pixels[offset + col + 1] for col in range(size))
    value = sum(int(bit) << index for index, bit in enumerate(bits))
    return f"{value:0{math.ceil(size * size / 4)}x}"


def hash_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def analyze_frame(path: Path, timestamp: float, scene: tuple[float, float]) -> FrameCandidate:
    with Image.open(path) as image:
        image.load()
        brightness, exposure = brightness_metrics(image)
        return FrameCandidate(
            path=path.name,
            timestamp=timestamp,
            scene_start=scene[0],
            scene_end=scene[1],
            brightness=brightness,
            brightness_score=exposure,
            sharpness=sharpness_score(image),
            crop_score=crop_quality_score(image),
            image_hash=difference_hash(image),
        )


def acceptable(candidate: FrameCandidate, *, min_sharpness: float = 45.0) -> bool:
    return 0.10 <= candidate.brightness <= 0.92 and candidate.sharpness >= min_sharpness


def burst_frame_score(
    candidate: FrameCandidate, *, sharpness_range: tuple[float, float]
) -> float:
    """Score a frame inside a short burst, strongly favoring crisp stable moments."""
    low, high = sharpness_range
    sharpness = 1.0 if high == low else (candidate.sharpness - low) / (high - low)
    return min(
        1.0,
        max(
            0.0,
            0.45 * sharpness
            + 0.25 * candidate.brightness_score
            + 0.20 * candidate.stability
            + 0.10 * candidate.crop_score,
        ),
    )


def rank_burst_frames(candidates: list[FrameCandidate]) -> list[FrameCandidate]:
    """Reject unusable/transition frames and rank the remaining burst frames."""
    usable = [item for item in candidates if acceptable(item) and item.stability >= 0.25]
    if not usable:
        return []
    sharpness_range = (
        min(item.sharpness for item in usable),
        max(item.sharpness for item in usable),
    )
    return sorted(
        usable,
        key=lambda item: (burst_frame_score(item, sharpness_range=sharpness_range), -item.timestamp),
        reverse=True,
    )


def frame_finder_quality_score(
    candidate: FrameCandidate, *, sharpness_range: tuple[float, float]
) -> float:
    """Score a retained scene representative for the Frame Finder gallery."""
    low, high = sharpness_range
    sharpness = 1.0 if high == low else (candidate.sharpness - low) / (high - low)
    return min(
        1.0,
        max(
            0.0,
            0.32 * sharpness
            + 0.22 * candidate.brightness_score
            + 0.18 * candidate.uniqueness
            + 0.18 * candidate.stability
            + 0.10 * candidate.crop_score,
        ),
    )


def select_frame_finder_output(
    candidates: list[FrameCandidate], target_count: int
) -> list[FrameCandidate]:
    """Keep approximately the best requested number, always returning chronological output."""
    if target_count < 1:
        raise ValueError("target_count must be positive")
    distinct = remove_duplicates(candidates)
    if len(distinct) <= target_count:
        return sorted(distinct, key=lambda item: item.timestamp)
    sharpness_range = (
        min(item.sharpness for item in distinct),
        max(item.sharpness for item in distinct),
    )
    best = sorted(
        distinct,
        key=lambda item: frame_finder_quality_score(
            item, sharpness_range=sharpness_range
        ),
        reverse=True,
    )[:target_count]
    return sorted(best, key=lambda item: item.timestamp)


def remove_duplicates(
    candidates: list[FrameCandidate], *, max_hash_distance: int = 7
) -> list[FrameCandidate]:
    kept: list[FrameCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.timestamp):
        distances = [hash_distance(candidate.image_hash, item.image_hash) for item in kept]
        if distances and min(distances) <= max_hash_distance:
            continue
        if distances:
            candidate.uniqueness = min(1.0, min(distances) / 24.0)
        kept.append(candidate)
    return kept


def assign_candidates_to_steps(
    candidates: list[FrameCandidate], step_count: int
) -> list[list[FrameCandidate]]:
    """Split the chronological sequence into disjoint, ordered step groups."""
    if step_count < 1:
        raise ValueError("step_count must be positive")
    ordered = sorted(candidates, key=lambda item: item.timestamp)
    groups: list[list[FrameCandidate]] = []
    for index in range(step_count):
        start = math.floor(index * len(ordered) / step_count)
        end = math.floor((index + 1) * len(ordered) / step_count)
        groups.append(ordered[start:end])
    return groups


def rank_candidates(
    candidates: list[FrameCandidate], *, step_index: int, step_count: int, duration: float
) -> list[FrameCandidate]:
    if not candidates:
        return []
    sharp_values = [item.sharpness for item in candidates]
    low, high = min(sharp_values), max(sharp_values)
    target = (step_index + 0.5) / step_count

    def score(item: FrameCandidate) -> float:
        return candidate_quality_score(
            item,
            sharpness_range=(low, high),
            step_index=step_index,
            step_count=step_count,
            duration=duration,
        )

    return sorted(candidates, key=lambda item: (score(item), -item.timestamp), reverse=True)


def candidate_quality_score(
    candidate: FrameCandidate,
    *,
    sharpness_range: tuple[float, float],
    step_index: int,
    step_count: int,
    duration: float,
) -> float:
    """Return the same normalized quality score used by candidate ranking."""
    low, high = sharpness_range
    sharp = 1.0 if high == low else (candidate.sharpness - low) / (high - low)
    target = (step_index + 0.5) / step_count
    timing = 1.0 - min(
        1.0,
        abs(candidate.timestamp / max(duration, 0.001) - target) * step_count,
    )
    score = (
        0.30 * sharp
        + 0.22 * candidate.brightness_score
        + 0.20 * candidate.uniqueness
        + 0.18 * timing
        + 0.10 * candidate.crop_score
    )
    return min(1.0, max(0.0, score))


def save_manifest(path: Path, candidates: list[FrameCandidate], duration: float) -> None:
    path.write_text(
        json.dumps({"duration": duration, "candidates": [asdict(item) for item in candidates]}, indent=2),
        encoding="utf-8",
    )


def load_manifest(path: Path) -> tuple[float, list[FrameCandidate]]:
    if not path.exists():
        return 0.0, []
    data = json.loads(path.read_text(encoding="utf-8"))
    return float(data.get("duration", 0)), [
        FrameCandidate.from_dict(item) for item in data.get("candidates", [])
    ]


def migrate_legacy_frames(frames: list[Path], duration: float = 0.0) -> tuple[float, list[FrameCandidate]]:
    """Build metadata for candidates created by the earlier evenly-spaced workflow."""
    ordered = sorted(frames)
    effective_duration = duration if duration > 0 else float(max(1, len(ordered)))
    candidates = []
    for index, frame in enumerate(ordered):
        timestamp = effective_duration * (index + 0.5) / len(ordered)
        candidates.append(analyze_frame(frame, timestamp, (0.0, effective_duration)))
    return effective_duration, candidates
