from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "analysis_settings.json"


@dataclass(frozen=True)
class AnalysisSettings:
    """Tunable thresholds for frame extraction and filtering."""

    scene_threshold: float = 0.30
    min_sharpness: float = 45.0
    max_hash_distance: int = 7
    min_brightness: float = 0.10
    max_brightness: float = 0.92
    # Interval fallback: used when scene detection yields fewer than this many frames.
    min_scene_frames: int = 6
    fallback_interval: float = 1.5

    def __post_init__(self) -> None:
        if not 0 < self.scene_threshold < 1:
            raise ValueError("scene_threshold must be between 0 and 1")
        if self.min_sharpness < 0:
            raise ValueError("min_sharpness cannot be negative")
        if self.max_hash_distance < 0:
            raise ValueError("max_hash_distance cannot be negative")
        if not 0 <= self.min_brightness < self.max_brightness <= 1:
            raise ValueError("brightness bounds must satisfy 0 <= min < max <= 1")
        if self.fallback_interval <= 0:
            raise ValueError("fallback_interval must be positive")

    def relaxed(self, level: int) -> "AnalysisSettings":
        """Progressively looser filters, used when every frame was rejected."""
        if level <= 0:
            return self
        if level == 1:
            return replace(
                self,
                min_sharpness=self.min_sharpness * 0.4,
                min_brightness=min(self.min_brightness, 0.04),
                max_brightness=max(self.max_brightness, 0.97),
            )
        return replace(self, min_sharpness=0.0, min_brightness=0.0, max_brightness=1.0)


RELAXATION_LEVELS = 2


def load_settings(path: Path | None = None) -> AnalysisSettings:
    """Load defaults, overridden by an optional analysis_settings.json file."""
    config = path or CONFIG_PATH
    if not config.is_file():
        return AnalysisSettings()
    try:
        raw = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {config.name}: {error}") from error
    allowed = {item.name for item in fields(AnalysisSettings)}
    return AnalysisSettings(**{key: value for key, value in raw.items() if key in allowed})


def settings_to_dict(settings: AnalysisSettings) -> dict[str, float | int]:
    return asdict(settings)
