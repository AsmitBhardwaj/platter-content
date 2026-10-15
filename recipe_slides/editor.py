from __future__ import annotations

import base64
import hashlib
import json
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


def _source_signature(project: Project) -> str:
    """Fingerprint upstream content that determines the editor's slide roster."""
    if project.workflow_mode == "frame_finder":
        value = {
            "mode": project.workflow_mode,
            "frames": [
                {
                    "path": frame,
                    "crop": project.frame_crops.get(frame, {"x": 0.5, "y": 0.5}),
                    "role": project.frame_roles.get(frame, "recipe"),
                }
                for frame in project.frame_order
            ],
        }
    else:
        value = {
            "mode": project.workflow_mode,
            "title": project.title,
            "episode": project.episode,
            "steps": project.steps,
            "selections": project.selections,
            "crops": project.crop_positions,
            "cover_heading": project.settings.cover_heading,
            "closing_text": project.settings.closing_text,
            "text_color": project.settings.text_color,
        }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frame_slide(project: Project, frame: str, index: int) -> EditorSlide:
    role = project.frame_roles.get(frame, "recipe")
    role_name = {"cover": "Cover", "recipe": "Recipe step", "closing": "Closing"}[role]
    text = project.frame_texts.get(frame, "").strip()
    layers: list[TextLayer] = []
    if text:
        color = "#000000" if project.settings.text_color == "black" else "#FFFFFF"
        layers.append(
            _layer(
                text,
                x=0.078,
                y=0.68,
                width=0.844,
                font_size=58,
                font_weight="bold",
                color=color,
                background={
                    "enabled": True,
                    "color": "#000000" if color == "#FFFFFF" else "#FFFFFF",
                    "opacity": 0.74,
                    "padding": 40,
                    "corner_radius": 34,
                },
            )
        )
    return EditorSlide(
        name=f"{role_name} {index:02d}",
        kind=role,
        source_frame=frame,
        crop=dict(project.frame_crops.get(frame, {"x": 0.5, "y": 0.5})),
        layers=layers,
    )


def _recipe_step_slide(project: Project, index: int, text: str) -> EditorSlide:
    color = "#000000" if project.settings.text_color == "black" else "#FFFFFF"
    return EditorSlide(
        name=f"Step {index:02d}",
        kind="recipe",
        source_frame=project.selections.get(str(index - 1)),
        crop=dict(project.crop_positions.get(str(index - 1), {"x": 0.5, "y": 0.5})),
        layers=[
            _layer(
                f"STEP {index:02d}\n{text}",
                x=0.078,
                y=0.66,
                width=0.844,
                font_size=58,
                font_weight="bold",
                color=color,
                background={
                    "enabled": True,
                    "color": "#000000" if color == "#FFFFFF" else "#FFFFFF",
                    "opacity": 0.74,
                    "padding": 40,
                    "corner_radius": 34,
                },
            )
        ],
    )


def initialize_editor(project: Project) -> bool:
    """Migrate the old fixed layouts into editable slides exactly once."""
    if project.editor_initialized:
        return False
    color = "#000000" if project.settings.text_color == "black" else "#FFFFFF"
    slides: list[EditorSlide] = []
    if project.workflow_mode == "frame_finder":
        for index, frame in enumerate(project.frame_order, 1):
            slides.append(_frame_slide(project, frame, index))
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
            slides.append(_recipe_step_slide(project, index, text))
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
    project.editor_source_signature = _source_signature(project)
    return True


def sync_editor(project: Project) -> bool:
    """Reconcile upstream frame/recipe changes without discarding canvas edits."""
    if not project.editor_initialized:
        return initialize_editor(project)
    signature = _source_signature(project)
    if project.editor_source_signature == signature:
        return False

    if project.workflow_mode == "frame_finder":
        existing = {
            slide.source_frame: slide
            for slide in project.editor_slides
            if slide.source_frame
        }
        synchronized: list[EditorSlide] = []
        for index, frame in enumerate(project.frame_order, 1):
            slide = existing.get(frame)
            if slide is None:
                slide = _frame_slide(project, frame, index)
            else:
                role = project.frame_roles.get(frame, "recipe")
                role_name = {
                    "cover": "Cover",
                    "recipe": "Recipe step",
                    "closing": "Closing",
                }[role]
                slide.name = f"{role_name} {index:02d}"
                slide.kind = role
                slide.crop = dict(project.frame_crops.get(frame, {"x": 0.5, "y": 0.5}))
            synchronized.append(slide)
        # Blank/custom slides belong to the editor rather than the frame picker.
        synchronized.extend(slide for slide in project.editor_slides if not slide.source_frame)
        project.editor_slides = synchronized
    else:
        existing_steps = [slide for slide in project.editor_slides if slide.kind == "recipe"]
        synchronized_steps: list[EditorSlide] = []
        for index, text in enumerate(project.steps, 1):
            slide = (
                existing_steps[index - 1]
                if index <= len(existing_steps)
                else _recipe_step_slide(project, index, text)
            )
            slide.name = f"Step {index:02d}"
            slide.source_frame = project.selections.get(str(index - 1))
            slide.crop = dict(
                project.crop_positions.get(str(index - 1), {"x": 0.5, "y": 0.5})
            )
            synchronized_steps.append(slide)
        cover = next((slide for slide in project.editor_slides if slide.kind == "cover"), None)
        closing = next((slide for slide in project.editor_slides if slide.kind == "closing"), None)
        custom = [
            slide
            for slide in project.editor_slides
            if slide.kind not in {"cover", "recipe", "closing"}
        ]
        project.editor_slides = (
            ([cover] if cover else [])
            + synchronized_steps
            + ([closing] if closing else [])
            + custom
        )

    project.editor_source_signature = signature
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
