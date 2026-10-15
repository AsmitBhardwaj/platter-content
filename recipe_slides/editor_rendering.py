from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont

from .candidates import crop_frame
from .fonts import resolve_font
from .models import EditorSlide, TextLayer
from .rendering import SLIDE_SIZE


def _rgba(value: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    try:
        rgb = ImageColor.getrgb(value)
    except ValueError:
        rgb = (255, 255, 255)
    return (*rgb[:3], round(max(0.0, min(1.0, opacity)) * 255))


def _display_text(layer: TextLayer) -> str:
    if layer.capitalization == "uppercase":
        return layer.text.upper()
    if layer.capitalization == "lowercase":
        return layer.text.lower()
    if layer.capitalization == "capitalize":
        return layer.text.title()
    return layer.text


def _tracking(layer: TextLayer) -> float:
    return layer.font_size * layer.letter_spacing / 1000.0


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, tracking: float) -> float:
    if not text:
        return 0.0
    length = draw.textlength(text, font=font)
    return float(length + max(0, len(text) - 1) * tracking)


def _wrap(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, width: int, tracking: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        if not words or words == [""]:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            proposed = current + " " + word
            if _measure(draw, proposed, font, tracking) <= width:
                current = proposed
            else:
                lines.append(current)
                current = word
        # Character-wrap unbroken words wider than the text box.
        while _measure(draw, current, font, tracking) > width and len(current) > 1:
            cut = 1
            while cut < len(current) and _measure(draw, current[: cut + 1], font, tracking) <= width:
                cut += 1
            lines.append(current[:cut])
            current = current[cut:]
        lines.append(current)
    return lines or [""]


def _draw_tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: float,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    x, y = xy
    if abs(tracking) < 0.01:
        draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return
    for character in text:
        draw.text((x, y), character, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += draw.textlength(character, font=font) + tracking


def _render_layer(
    layer: TextLayer, project_dir: Path, warnings: list[str]
) -> tuple[Image.Image, int, tuple[int, int]]:
    width = max(2, round(layer.width * SLIDE_SIZE[0]))
    font_path, warning = resolve_font(project_dir, layer.font_file, layer.font_family)
    if warning and warning not in warnings:
        warnings.append(warning)
    try:
        font = ImageFont.truetype(str(font_path), round(layer.font_size)) if font_path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    scratch = Image.new("RGBA", (width + 512, SLIDE_SIZE[1] * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(scratch)
    tracking = _tracking(layer)
    lines = _wrap(_display_text(layer), draw, font, width, tracking)
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (round(layer.font_size), 0)
    line_height = max(1, round(layer.font_size * layer.line_height))
    text_height = max(ascent + descent, line_height * len(lines))
    background = layer.background or {}
    padding = round(float(background.get("padding", 0))) if background.get("enabled") else 0
    stroke = layer.stroke or {}
    stroke_width = max(0, round(float(stroke.get("width", 0))))
    margin = padding + stroke_width + 96
    surface = Image.new("RGBA", (width + margin * 2, text_height + margin * 2), (0, 0, 0, 0))
    if background.get("enabled"):
        panel = ImageDraw.Draw(surface)
        panel.rounded_rectangle(
            (margin - padding, margin - padding, margin + width + padding, margin + text_height + padding),
            radius=max(0, round(float(background.get("corner_radius", 0)))),
            fill=_rgba(str(background.get("color", "#000000")), float(background.get("opacity", 1))),
        )

    shadow = layer.shadow or {}
    shadow_opacity = float(shadow.get("opacity", 0))
    if shadow_opacity > 0:
        shadow_image = Image.new("RGBA", surface.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_image)
        for index, line in enumerate(lines):
            measured = _measure(shadow_draw, line, font, tracking)
            offset = 0 if layer.alignment in {"left", "justify"} else (width - measured) / (2 if layer.alignment == "center" else 1)
            _draw_tracked(
                shadow_draw,
                (margin + offset + float(shadow.get("offset_x", 0)), margin + index * line_height + float(shadow.get("offset_y", 0))),
                line, font=font, fill=_rgba(str(shadow.get("color", "#000000")), shadow_opacity), tracking=tracking,
            )
        blur = float(shadow.get("blur", 0))
        if blur > 0:
            shadow_image = shadow_image.filter(ImageFilter.GaussianBlur(blur))
        surface.alpha_composite(shadow_image)

    layer_draw = ImageDraw.Draw(surface)
    fill = _rgba(layer.color, layer.opacity)
    stroke_fill = _rgba(str(stroke.get("color", "#000000")), layer.opacity)
    for index, line in enumerate(lines):
        measured = _measure(layer_draw, line, font, tracking)
        offset = 0 if layer.alignment in {"left", "justify"} else (width - measured) / (2 if layer.alignment == "center" else 1)
        y = margin + index * line_height
        _draw_tracked(layer_draw, (margin + offset, y), line, font=font, fill=fill, tracking=tracking, stroke_width=stroke_width, stroke_fill=stroke_fill)
        if layer.underline and line:
            underline_y = y + ascent + max(1, round(layer.font_size * 0.04))
            layer_draw.line((margin + offset, underline_y, margin + offset + measured, underline_y), fill=fill, width=max(1, round(layer.font_size * 0.045)))
    unrotated_size = surface.size
    if layer.rotation:
        surface = surface.rotate(-layer.rotation, resample=Image.Resampling.BICUBIC, expand=True)
    return surface, margin, unrotated_size


def render_editor_slide(slide: EditorSlide, project_dir: Path, warnings: list[str] | None = None) -> Image.Image:
    messages = warnings if warnings is not None else []
    if slide.source_frame and (project_dir / slide.source_frame).exists():
        with Image.open(project_dir / slide.source_frame) as source:
            crop = slide.crop or {}
            base = crop_frame(source, SLIDE_SIZE, float(crop.get("x", 0.5)), float(crop.get("y", 0.5))).convert("RGBA")
    else:
        base = Image.new("RGBA", SLIDE_SIZE, _rgba(slide.background_color))
    for layer in sorted(slide.layers, key=lambda item: item.z_index):
        rendered, margin, unrotated_size = _render_layer(layer, project_dir, messages)
        x = round(layer.x * SLIDE_SIZE[0]) - margin
        y = round(layer.y * SLIDE_SIZE[1]) - margin
        if layer.rotation:
            # Rotation expansion grows around the layer center.
            x -= round((rendered.width - unrotated_size[0]) / 2)
            y -= round((rendered.height - unrotated_size[1]) / 2)
        base.alpha_composite(rendered, (x, y))
    return base.convert("RGB")


def export_editor_project(project_slides: Iterable[EditorSlide], project_dir: Path, export_dir: Path) -> tuple[list[Path], list[str]]:
    export_dir.mkdir(parents=True, exist_ok=True)
    for existing in export_dir.glob("*.png"):
        existing.unlink()
    outputs: list[Path] = []
    warnings: list[str] = []
    for index, slide in enumerate(project_slides, 1):
        destination = export_dir / f"{index:02d}-{slide.kind}.png"
        render_editor_slide(slide, project_dir, warnings).save(destination)
        outputs.append(destination)
    return outputs, warnings
