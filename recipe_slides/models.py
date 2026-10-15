from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@dataclass
class TextLayer:
    """A canvas text object stored in slide-space, not preview pixels."""

    id: str = field(default_factory=lambda: _new_id("text"))
    text: str = "Double-click to edit"
    x: float = 0.08
    y: float = 0.10
    width: float = 0.70
    rotation: float = 0.0
    font_family: str = "Arial"
    font_file: str = "curated/Arial.ttf"
    font_size: float = 64.0
    font_weight: str = "normal"
    italic: bool = False
    underline: bool = False
    alignment: str = "left"
    line_height: float = 1.16
    letter_spacing: float = 0.0
    capitalization: str = "none"
    color: str = "#FFFFFF"
    opacity: float = 1.0
    stroke: dict[str, Any] = field(
        default_factory=lambda: {"color": "#000000", "width": 0.0}
    )
    shadow: dict[str, Any] = field(
        default_factory=lambda: {
            "color": "#000000",
            "opacity": 0.0,
            "blur": 0.0,
            "offset_x": 0.0,
            "offset_y": 4.0,
        }
    )
    background: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": False,
            "color": "#000000",
            "opacity": 0.72,
            "padding": 24.0,
            "corner_radius": 24.0,
        }
    )
    z_index: int = 0

    def __post_init__(self) -> None:
        self.x = max(-1.0, min(2.0, float(self.x)))
        self.y = max(-1.0, min(2.0, float(self.y)))
        self.width = max(0.02, min(2.0, float(self.width)))
        self.opacity = max(0.0, min(1.0, float(self.opacity)))
        self.font_size = max(1.0, float(self.font_size))
        self.line_height = max(0.5, float(self.line_height))
        if self.alignment not in {"left", "center", "right", "justify"}:
            self.alignment = "left"
        if self.capitalization not in {"none", "uppercase", "lowercase", "capitalize"}:
            self.capitalization = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextLayer":
        allowed = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class EditorSlide:
    id: str = field(default_factory=lambda: _new_id("slide"))
    name: str = "Slide"
    kind: str = "frame"
    source_frame: str | None = None
    crop: dict[str, float] = field(default_factory=lambda: {"x": 0.5, "y": 0.5})
    background_color: str = "#141414"
    layers: list[TextLayer] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in {"cover", "recipe", "closing", "frame", "blank"}:
            self.kind = "frame"
        self.layers = [
            layer if isinstance(layer, TextLayer) else TextLayer.from_dict(layer)
            for layer in self.layers
        ]
        for index, layer in enumerate(sorted(self.layers, key=lambda item: item.z_index)):
            layer.z_index = index

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditorSlide":
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        values["layers"] = [TextLayer.from_dict(item) for item in values.get("layers", [])]
        return cls(**values)


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
    editor_slides: list[EditorSlide] = field(default_factory=list)
    editor_initialized: bool = False
    saved_text_styles: dict[str, dict[str, Any]] = field(default_factory=dict)
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
        self.editor_slides = [
            slide if isinstance(slide, EditorSlide) else EditorSlide.from_dict(slide)
            for slide in self.editor_slides
        ]

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
        values["editor_slides"] = [
            EditorSlide.from_dict(item) for item in values.get("editor_slides", [])
        ]
        values["editor_initialized"] = bool(values.get("editor_initialized", False))
        values["saved_text_styles"] = dict(values.get("saved_text_styles", {}))
        return cls(**values)
