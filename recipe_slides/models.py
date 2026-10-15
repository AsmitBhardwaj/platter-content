from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SlideSettings:
    text_color: str = "white"
    cover_heading: str = "RECIPE"
    closing_text: str = "Save this recipe\nand try it later"
    delete_source_after_export: bool = True

    def __post_init__(self) -> None:
        if self.text_color not in {"black", "white"}:
            raise ValueError("text_color must be 'black' or 'white'")


@dataclass
class Project:
    project_id: str
    title: str
    episode: str
    steps: list[str]
    video_filename: str | None = None
    video_source: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_thumbnail: str | None = None
    selections: dict[str, str] = field(default_factory=dict)
    crop_positions: dict[str, dict[str, float]] = field(default_factory=dict)
    workflow_mode: str = "recipe_steps"
    target_slide_count: int = 8
    frame_order: list[str] = field(default_factory=list)
    frame_texts: dict[str, str] = field(default_factory=dict)
    frame_crops: dict[str, dict[str, float]] = field(default_factory=dict)
    frame_roles: dict[str, str] = field(default_factory=dict)
    analysis_start: float = 0.0
    analysis_end: float | None = None
    settings: SlideSettings = field(default_factory=SlideSettings)

    def __post_init__(self) -> None:
        if self.workflow_mode not in {"recipe_steps", "frame_finder"}:
            raise ValueError("workflow_mode must be 'recipe_steps' or 'frame_finder'")
        if self.target_slide_count < 1:
            raise ValueError("target_slide_count must be positive")
        if self.analysis_start < 0:
            raise ValueError("analysis_start cannot be negative")
        if self.analysis_end is not None and self.analysis_end <= self.analysis_start:
            raise ValueError("analysis_end must be after analysis_start")
        if any(role not in {"cover", "recipe", "closing"} for role in self.frame_roles.values()):
            raise ValueError("frame roles must be cover, recipe, or closing")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Project":
        values = dict(data)
        values["settings"] = SlideSettings(**values.get("settings", {}))
        values["steps"] = list(values.get("steps", []))
        values["selections"] = dict(values.get("selections", {}))
        values["crop_positions"] = dict(values.get("crop_positions", {}))
        # Projects saved before workflow modes existed are recipe-step projects.
        values["workflow_mode"] = values.get("workflow_mode", "recipe_steps")
        values["target_slide_count"] = int(values.get("target_slide_count", 8))
        values["frame_order"] = list(values.get("frame_order", []))
        values["frame_texts"] = dict(values.get("frame_texts", {}))
        values["frame_crops"] = dict(values.get("frame_crops", {}))
        values["frame_roles"] = dict(values.get("frame_roles", {}))
        values["analysis_start"] = float(values.get("analysis_start", 0.0))
        values["analysis_end"] = (
            float(values["analysis_end"]) if values.get("analysis_end") is not None else None
        )
        return cls(**values)
