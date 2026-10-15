from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

from .candidates import crop_frame
from .fonts import font_payload
from .models import EditorSlide, Project, TextLayer


DEFAULT_STYLES = {
    "Heading": {"font_size": 92, "font_weight": "bold", "line_height": 1.0, "letter_spacing": -12},
    "Instruction": {"font_size": 58, "font_weight": "bold", "line_height": 1.16, "letter_spacing": 0},
    "Label": {"font_size": 38, "font_weight": "bold", "line_height": 1.0, "letter_spacing": 80, "capitalization": "uppercase"},
    "CTA": {"font_size": 68, "font_weight": "bold", "alignment": "center", "line_height": 1.1},
    "Previous fixed overlay": {
        "font_size": 58,
        "font_weight": "bold",
        "line_height": 1.16,
        "background": {"enabled": True, "color": "#000000", "opacity": 0.74, "padding": 40, "corner_radius": 34},
    },
}


def _layer(text: str, **values: object) -> TextLayer:
    if "font_file" not in values and values.get("font_weight") == "bold":
        values["font_file"] = "curated/Arial-bold.ttf"
    return TextLayer(text=text, **values)


def initialize_editor(project: Project) -> bool:
    """Migrate the old fixed layouts into editable slides exactly once."""
    if project.editor_initialized:
        return False
    color = "#000000" if project.settings.text_color == "black" else "#FFFFFF"
    slides: list[EditorSlide] = []
    if project.workflow_mode == "frame_finder":
        for index, frame in enumerate(project.frame_order, 1):
            text = project.frame_texts.get(frame, "").strip()
            layers = []
            if text:
                layers.append(
                    _layer(
                        text,
                        x=0.078,
                        y=0.68,
                        width=0.844,
                        font_size=58,
                        font_weight="bold",
                        color=color,
                        background={"enabled": True, "color": "#000000" if color == "#FFFFFF" else "#FFFFFF", "opacity": 0.74, "padding": 40, "corner_radius": 34},
                    )
                )
            slides.append(EditorSlide(name=f"Frame {index:02d}", kind="frame", source_frame=frame, crop=dict(project.frame_crops.get(frame, {"x": 0.5, "y": 0.5})), layers=layers))
    else:
        eyebrow = project.settings.cover_heading
        if project.episode:
            eyebrow += f" · EPISODE {project.episode}"
        slides.append(
            EditorSlide(
                name="Cover",
                kind="cover",
                background_color="#F5F1E8" if color == "#000000" else "#141414",
                layers=[
                    _layer(eyebrow, x=0.078, y=0.104, width=0.84, font_size=42, font_weight="bold", color=color, z_index=0),
                    _layer(project.title, x=0.078, y=0.27, width=0.84, font_size=96, font_weight="bold", line_height=1.08, color=color, z_index=1),
                ],
            )
        )
        for index, text in enumerate(project.steps, 1):
            frame = project.selections.get(str(index - 1))
            slides.append(
                EditorSlide(
                    name=f"Step {index:02d}", kind="recipe", source_frame=frame,
                    crop=dict(project.crop_positions.get(str(index - 1), {"x": 0.5, "y": 0.5})),
                    layers=[
                        _layer(
                            f"STEP {index:02d}\n{text}", x=0.078, y=0.66, width=0.844,
                            font_size=58, font_weight="bold", color=color,
                            background={"enabled": True, "color": "#000000" if color == "#FFFFFF" else "#FFFFFF", "opacity": 0.74, "padding": 40, "corner_radius": 34},
                        )
                    ],
                )
            )
        slides.append(
            EditorSlide(
                name="Closing", kind="closing",
                background_color="#F5F1E8" if color == "#000000" else "#141414",
                layers=[_layer(project.settings.closing_text, x=0.10, y=0.40, width=0.80, font_size=82, font_weight="bold", alignment="center", color=color)],
            )
        )
    project.editor_slides = slides
    project.saved_text_styles = {**DEFAULT_STYLES, **project.saved_text_styles}
    project.editor_initialized = True
    return True


def image_data_url(image: Image.Image, *, quality: int = 88) -> str:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def editor_payload(project: Project, project_dir: Path) -> dict[str, object]:
    slides = []
    for slide in project.editor_slides:
        data = slide.__dict__.copy()
        data["layers"] = [layer.__dict__ for layer in slide.layers]
        if slide.source_frame and (project_dir / slide.source_frame).exists():
            with Image.open(project_dir / slide.source_frame) as source:
                crop = slide.crop or {}
                preview = crop_frame(source, x_position=float(crop.get("x", 0.5)), y_position=float(crop.get("y", 0.5)))
            data["image"] = image_data_url(preview)
        else:
            data["image"] = None
        slides.append(data)
    return {
        "slides": slides,
        "saved_styles": project.saved_text_styles,
        "fonts": font_payload(project_dir),
        "canvas": {"width": 1080, "height": 1440},
    }


def apply_editor_value(project: Project, value: dict[str, object]) -> None:
    slides = value.get("slides")
    if not isinstance(slides, list):
        return
    clean_slides = []
    for raw in slides:
        if not isinstance(raw, dict):
            continue
        raw = {key: item for key, item in raw.items() if key != "image"}
        clean_slides.append(EditorSlide.from_dict(raw))
    if clean_slides:
        project.editor_slides = clean_slides
    styles = value.get("saved_styles")
    if isinstance(styles, dict):
        project.saved_text_styles = styles


def add_blank_slide(project: Project) -> None:
    project.editor_slides.append(EditorSlide(id=f"slide-{uuid4().hex[:12]}", name=f"Blank {len(project.editor_slides) + 1}", kind="blank", background_color="#141414"))
