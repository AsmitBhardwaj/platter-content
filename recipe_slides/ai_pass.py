"""One vision pass that turns Frame Finder candidates into captioned slides.

The model sees downscaled candidate frames (each labeled with its index and
timestamp), the extraction mode, the video title and any user-supplied steps,
and returns structured JSON: a dish name plus ordered {frame_index, caption}.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .candidates import FrameCandidate

LOGGER = logging.getLogger("recipe_slides.ai")

MODEL = "gpt-5.4-mini"
MAX_FRAMES = 40
IMAGE_LONG_SIDE = 512
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "recipe_slides",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["dish_name", "slides"],
        "properties": {
            "dish_name": {"type": "string"},
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["frame_index", "caption"],
                    "properties": {
                        "frame_index": {"type": "integer"},
                        "caption": {"type": "string"},
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You turn a cooking video's candidate frames into TikTok photo-mode recipe slides.

Choose the frames that best show each distinct cooking step and write one caption per chosen frame.

Caption voice: all lowercase, very short, direct, casual, an occasional ";)" at the end. Examples:
"add 4 tbsp of sugar", "heat it up ;)", "whisk it well ;)", "add 1 cup of milk and mix it well ;)".

Rules:
- Each caption must describe what is actually visible in its frame. Read any on-screen text (ingredient amounts, times) and use it when present. Do not invent quantities that are not shown or given.
- Typically 8-12 slides, one per distinct step. Skip redundant, blurry or near-duplicate frames.
- frame_index must be one of the provided frame indexes. Use each index at most once and keep slides in cooking order.
- If the user supplied steps, align captions to them but still describe what the frame shows.
- dish_name is the name of the dish, short and plain."""


class AIPassError(RuntimeError):
    """A failure with a message that is safe to show to the user."""


@dataclass(frozen=True)
class FrameInput:
    index: int
    path: str  # project-relative path
    timestamp: float
    in_analysis_range: bool


@dataclass(frozen=True)
class AISlide:
    frame: str  # project-relative path
    caption: str
    timestamp: float


@dataclass(frozen=True)
class AIResult:
    dish_name: str
    slides: list[AISlide]
    input_tokens: int = 0
    output_tokens: int = 0


def load_api_key(env_path: Path | None = None) -> str | None:
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path or ENV_PATH, override=False)
    except ImportError:  # python-dotenv is optional at runtime
        pass
    return os.environ.get("OPENAI_API_KEY") or None


def select_frames(
    candidates: list[FrameCandidate], candidates_rel_dir: str, limit: int = MAX_FRAMES
) -> list[FrameInput]:
    """Chronological frame list, capped at ``limit`` (cooking frames first)."""
    ordered = sorted(candidates, key=lambda item: item.timestamp)
    if len(ordered) > limit:
        inside = [item for item in ordered if item.in_analysis_range]
        outside = [item for item in ordered if not item.in_analysis_range]
        if len(inside) >= limit:
            step = len(inside) / limit
            inside = [inside[int(position * step)] for position in range(limit)]
            outside = []
        else:
            outside = outside[: limit - len(inside)]
        ordered = sorted(inside + outside, key=lambda item: item.timestamp)
    return [
        FrameInput(
            index=index,
            path=f"{candidates_rel_dir}/{item.path}",
            timestamp=item.timestamp,
            in_analysis_range=item.in_analysis_range,
        )
        for index, item in enumerate(ordered)
    ]


def encode_frame(path: Path, long_side: int = IMAGE_LONG_SIDE) -> str:
    """Downscale to ``long_side`` pixels and return a base64 JPEG data URL."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        scale = long_side / max(image.size)
        if scale < 1:
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=75)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _mode_description(mode: str) -> str:
    if mode == "interval-fallback":
        return (
            "The video had few hard cuts, so frames were sampled at fixed time intervals "
            "(about every 1.5s). Several consecutive frames may show the same step."
        )
    return "Frames were chosen from detected scene changes, roughly one per scene."


def build_messages(
    frames: list[FrameInput],
    project_dir: Path,
    *,
    title: str,
    mode: str,
    steps: list[str] | None = None,
) -> list[dict[str, Any]]:
    intro = [
        f"Video title: {title or 'unknown'}",
        f"Extraction mode: {mode}. {_mode_description(mode)}",
        f"There are {len(frames)} frames, labeled with index and timestamp.",
    ]
    if steps:
        intro.append(
            "User-provided steps (may be incomplete):\n"
            + "\n".join(f"{number}. {step}" for number, step in enumerate(steps, 1))
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": "\n".join(intro)}]
    for frame in frames:
        scope = "" if frame.in_analysis_range else ", outside the cooking range"
        content.append(
            {"type": "text", "text": f"Frame {frame.index} (t={frame.timestamp:.1f}s{scope}):"}
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": encode_frame(project_dir / frame.path), "detail": "low"},
            }
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def normalize_caption(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def parse_response(text: str, frames: list[FrameInput]) -> tuple[str, list[AISlide]]:
    """Validate the model's JSON and map frame indexes to project frames."""
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError) as error:
        raise AIPassError("The model returned invalid JSON.") from error
    if not isinstance(data, dict) or not isinstance(data.get("slides"), list):
        raise AIPassError("The model response did not include a slides list.")
    by_index = {frame.index: frame for frame in frames}
    seen: set[int] = set()
    slides: list[AISlide] = []
    for item in data["slides"]:
        if not isinstance(item, dict):
            continue
        index = item.get("frame_index")
        caption = normalize_caption(item.get("caption", ""))
        if isinstance(index, bool) or not isinstance(index, int):
            continue
        if index not in by_index or index in seen or not caption:
            continue
        seen.add(index)
        frame = by_index[index]
        slides.append(AISlide(frame=frame.path, caption=caption, timestamp=frame.timestamp))
    if not slides:
        raise AIPassError("The model did not return any usable slides.")
    # Cooking order follows video time, regardless of how the model ordered them.
    slides.sort(key=lambda slide: slide.timestamp)
    dish_name = str(data.get("dish_name") or "").strip()
    return dish_name, slides


def _usage(response: Any) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def run_ai_pass(
    candidates: list[FrameCandidate],
    *,
    project_dir: Path,
    candidates_rel_dir: str,
    title: str,
    mode: str,
    steps: list[str] | None = None,
    client: Any | None = None,
    model: str = MODEL,
) -> AIResult:
    frames = select_frames(candidates, candidates_rel_dir)
    if not frames:
        raise AIPassError("There are no candidate frames to send to the model.")
    if client is None:
        key = load_api_key()
        if not key:
            raise AIPassError("OPENAI_API_KEY is not set. Add it to a .env file to use the AI pass.")
        try:
            from openai import OpenAI
        except ImportError as error:
            raise AIPassError("The openai package is not installed.") from error
        client = OpenAI(api_key=key)
    try:
        messages = build_messages(frames, project_dir, title=title, mode=mode, steps=steps)
    except OSError as error:
        raise AIPassError(f"Could not read a candidate frame: {error}") from error
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
        )
    except Exception as error:  # SDK exceptions carry a readable message
        raise AIPassError(f"The AI request failed: {error}") from error
    input_tokens, output_tokens = _usage(response)
    LOGGER.info(
        "AI pass: model=%s frames=%d mode=%s input_tokens=%d output_tokens=%d",
        model, len(frames), mode, input_tokens, output_tokens,
    )
    print(
        f"[ai-pass] model={model} frames={len(frames)} mode={mode} "
        f"input_tokens={input_tokens} output_tokens={output_tokens}",
        flush=True,
    )
    try:
        text = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as error:
        raise AIPassError("The model response was empty.") from error
    dish_name, slides = parse_response(text, frames)
    return AIResult(dish_name, slides, input_tokens, output_tokens)


def read_manifest_mode(manifest_path: Path) -> str:
    """Return the extraction mode recorded by Frame Finder ("scenes" or "interval-fallback")."""
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return str(data.get("analysis", {}).get("mode", "scenes"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return "scenes"


def apply_ai_result(project: Any, result: AIResult) -> None:
    """Pre-fill a Frame Finder project so the editor opens on captioned slides."""
    project.frame_order = [slide.frame for slide in result.slides]
    project.frame_texts = {slide.frame: slide.caption for slide in result.slides}
    project.frame_roles = {slide.frame: "recipe" for slide in result.slides}
    project.frame_crops = {}
    if result.dish_name:
        project.title = result.dish_name
    # Force the editor to rebuild its slides from the new frames and captions.
    project.editor_slides = []
    project.editor_initialized = False
    project.editor_source_signature = None
