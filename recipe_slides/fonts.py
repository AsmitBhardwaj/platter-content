from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import ImageFont


@dataclass(frozen=True)
class FontFace:
    family: str
    file_id: str
    path: Path
    weight: str = "normal"
    italic: bool = False
    custom: bool = False


_SYSTEM_FONTS = {
    ("Arial", "normal", False): [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    ("Arial", "bold", False): [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ],
    ("Arial", "normal", True): [
        "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ],
    ("Arial", "bold", True): [
        "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-BoldItalic.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
    ],
    ("Georgia", "normal", False): [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    ],
    ("Verdana", "normal", False): [
        "/System/Library/Fonts/Supplemental/Verdana.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ],
    ("Courier New", "normal", False): [
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ],
}


def curated_fonts() -> list[FontFace]:
    faces: list[FontFace] = []
    for (family, weight, italic), candidates in _SYSTEM_FONTS.items():
        path = next((Path(item) for item in candidates if Path(item).is_file()), None)
        if path:
            suffix = "-bold" if weight == "bold" else ""
            suffix += "-italic" if italic else ""
            faces.append(
                FontFace(family, f"curated/{family.replace(' ', '-')}{suffix}{path.suffix}", path, weight, italic)
            )
    return faces


def project_fonts(project_dir: Path) -> list[FontFace]:
    faces = curated_fonts()
    uploads = project_dir / "fonts" / "uploads"
    if uploads.exists():
        for path in sorted(uploads.iterdir()):
            if path.suffix.lower() in {".ttf", ".otf"}:
                faces.append(FontFace(path.stem, str(path.relative_to(project_dir)), path, custom=True))
    return faces


def resolve_font(project_dir: Path, file_id: str, family: str = "Arial") -> tuple[Path | None, str | None]:
    face = next((item for item in project_fonts(project_dir) if item.file_id == file_id), None)
    if face:
        return face.path, None
    fallback = next((item for item in curated_fonts() if item.family == "Arial" and item.weight == "normal" and not item.italic), None)
    message = f'Font “{family}” is unavailable; Arial is used as a fallback.'
    return (fallback.path if fallback else None), message


def font_payload(project_dir: Path) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for face in project_fonts(project_dir):
        data = base64.b64encode(face.path.read_bytes()).decode("ascii")
        mime = "font/otf" if face.path.suffix.lower() == ".otf" else "font/ttf"
        payload.append(
            {
                "family": face.family,
                "file_id": face.file_id,
                "weight": face.weight,
                "italic": face.italic,
                "data_url": f"data:{mime};base64,{data}",
                "custom": face.custom,
            }
        )
    return payload


def save_uploaded_font(project_dir: Path, uploaded: BinaryIO, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".ttf", ".otf"}:
        raise ValueError("Upload a .ttf or .otf font file.")
    safe_stem = "".join(character for character in Path(filename).stem if character.isalnum() or character in "-_ ").strip()
    if not safe_stem:
        raise ValueError("The font filename is invalid.")
    directory = project_dir / "fonts" / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{safe_stem}{suffix}"
    data = uploaded.read()
    target.write_bytes(data)
    try:
        ImageFont.truetype(str(target), 24)
    except OSError as error:
        target.unlink(missing_ok=True)
        raise ValueError("That file is not a readable TrueType or OpenType font.") from error
    return target
