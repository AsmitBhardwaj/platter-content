from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Project
from .candidates import crop_frame

SLIDE_SIZE = (1080, 1440)
MARGIN = 84


def _font_candidates(bold: bool) -> list[str]:
    env_font = os.environ.get("RECIPE_SLIDES_FONT")
    candidates = [env_font] if env_font else []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
    return [candidate for candidate in candidates if candidate]


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _font_candidates(bold):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap_text(
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    draw: ImageDraw.ImageDraw | None = None,
) -> list[str]:
    """Wrap text by measured pixel width while preserving explicit newlines."""
    canvas = draw or ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words: list[str] = []
        for word in paragraph.split():
            if canvas.textbbox((0, 0), word, font=font)[2] <= max_width:
                words.append(word)
                continue
            chunk = ""
            for character in word:
                if chunk and canvas.textbbox((0, 0), chunk + character, font=font)[2] > max_width:
                    words.append(chunk)
                    chunk = character
                else:
                    chunk += character
            if chunk:
                words.append(chunk)
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            proposed = f"{current} {word}"
            if canvas.textbbox((0, 0), proposed, font=font)[2] <= max_width:
                current = proposed
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _contain_cover(image: Image.Image, x_position: float = 0.5, y_position: float = 0.5) -> Image.Image:
    return crop_frame(image, SLIDE_SIZE, x_position, y_position)


def _text_fill(color: str) -> tuple[int, int, int]:
    if color not in {"black", "white"}:
        raise ValueError("Text color must be black or white")
    return (0, 0, 0) if color == "black" else (255, 255, 255)


def render_step_slide(
    frame: Path | Image.Image,
    step_number: int,
    text: str,
    color: str,
    x_position: float = 0.5,
    y_position: float = 0.5,
) -> Image.Image:
    source = Image.open(frame) if isinstance(frame, Path) else frame
    slide = _contain_cover(source, x_position, y_position)
    draw = ImageDraw.Draw(slide, "RGBA")
    fill = _text_fill(color)
    panel_fill = (255, 255, 255, 205) if color == "black" else (0, 0, 0, 190)
    number_font = load_font(52, bold=True)
    body_size = 58
    while True:
        body_font = load_font(body_size, bold=True)
        lines = wrap_text(text, body_font, SLIDE_SIZE[0] - 2 * MARGIN, draw)
        line_height = round(body_size * 1.24)
        if len(lines) * line_height <= 1040 or body_size == 32:
            break
        body_size = max(32, body_size - 2)
    body_height = max(line_height, len(lines) * line_height)
    panel_top = SLIDE_SIZE[1] - body_height - 2 * MARGIN - 70
    draw.rounded_rectangle(
        (44, panel_top, SLIDE_SIZE[0] - 44, SLIDE_SIZE[1] - 44),
        radius=34,
        fill=panel_fill,
    )
    draw.text((MARGIN, panel_top + 42), f"STEP {step_number:02d}", font=number_font, fill=fill)
    y = panel_top + 112
    for line in lines:
        draw.text((MARGIN, y), line, font=body_font, fill=fill)
        y += line_height
    return slide


def render_cover_slide(title: str, episode: str, color: str, heading: str = "RECIPE") -> Image.Image:
    background = (245, 241, 232) if color == "black" else (20, 20, 20)
    slide = Image.new("RGB", SLIDE_SIZE, background)
    draw = ImageDraw.Draw(slide)
    fill = _text_fill(color)
    eyebrow_font = load_font(42, bold=True)
    title_font = load_font(96, bold=True)
    eyebrow = f"{heading} · EPISODE {episode}" if episode else heading
    draw.text((MARGIN, 150), eyebrow, font=eyebrow_font, fill=fill)
    lines = wrap_text(title, title_font, SLIDE_SIZE[0] - 2 * MARGIN, draw)
    y = 390
    for line in lines:
        draw.text((MARGIN, y), line, font=title_font, fill=fill)
        y += 118
    draw.rectangle((MARGIN, 1250, MARGIN + 210, 1268), fill=fill)
    return slide


def render_closing_slide(text: str, color: str) -> Image.Image:
    background = (245, 241, 232) if color == "black" else (20, 20, 20)
    slide = Image.new("RGB", SLIDE_SIZE, background)
    draw = ImageDraw.Draw(slide)
    fill = _text_fill(color)
    font = load_font(82, bold=True)
    lines = wrap_text(text, font, SLIDE_SIZE[0] - 2 * MARGIN, draw)
    line_height = 104
    y = (SLIDE_SIZE[1] - len(lines) * line_height) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (SLIDE_SIZE[0] - (bbox[2] - bbox[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return slide


def export_project(project: Project, project_dir: Path, export_dir: Path) -> list[Path]:
    export_dir.mkdir(parents=True, exist_ok=True)
    for existing in export_dir.glob("*.png"):
        existing.unlink()

    outputs: list[Path] = []
    cover = export_dir / "00-cover.png"
    render_cover_slide(
        project.title,
        project.episode,
        project.settings.text_color,
        project.settings.cover_heading,
    ).save(cover)
    outputs.append(cover)

    for index, step in enumerate(project.steps, 1):
        relative_frame = project.selections.get(str(index - 1))
        if not relative_frame:
            raise ValueError(f"Choose a frame for step {index}")
        frame = project_dir / relative_frame
        if not frame.exists():
            raise FileNotFoundError(f"Selected frame is missing for step {index}")
        destination = export_dir / f"{index:02d}-step.png"
        position = project.crop_positions.get(str(index - 1), {})
        render_step_slide(
            frame,
            index,
            step,
            project.settings.text_color,
            float(position.get("x", 0.5)),
            float(position.get("y", 0.5)),
        ).save(destination)
        outputs.append(destination)

    closing = export_dir / f"{len(project.steps) + 1:02d}-closing.png"
    render_closing_slide(project.settings.closing_text, project.settings.text_color).save(closing)
    outputs.append(closing)
    return outputs


def export_frame_finder_project(
    project: Project,
    project_dir: Path,
    export_dir: Path,
    *,
    include_text: bool = False,
) -> list[Path]:
    """Export selected Frame Finder images, optionally overlaying their instructions."""
    if not project.frame_order:
        raise ValueError("Select at least one frame to export")
    export_dir.mkdir(parents=True, exist_ok=True)
    for existing in export_dir.glob("*.png"):
        existing.unlink()

    outputs: list[Path] = []
    for index, relative_frame in enumerate(project.frame_order, 1):
        frame = project_dir / relative_frame
        if not frame.exists():
            raise FileNotFoundError(f"Selected frame is missing: {relative_frame}")
        crop = project.frame_crops.get(relative_frame, {})
        x_position = float(crop.get("x", 0.5))
        y_position = float(crop.get("y", 0.5))
        text = project.frame_texts.get(relative_frame, "").strip()
        if include_text and text:
            image = render_step_slide(
                frame,
                index,
                text,
                project.settings.text_color,
                x_position,
                y_position,
            )
        else:
            with Image.open(frame) as source:
                image = crop_frame(source, SLIDE_SIZE, x_position, y_position)
        destination = export_dir / f"{index:02d}-frame.png"
        image.save(destination)
        outputs.append(destination)
    return outputs
