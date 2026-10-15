"""Run Frame Finder extraction plus the AI pass on one video from the command line.

    python -m recipe_slides.ai_cli path/to/video.mp4 [--count 10] [--steps "a|b|c"]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .ai_pass import AIPassError, read_manifest_mode, run_ai_pass
from .ffmpeg import extract_frame_finder_candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--count", type=int, default=12, help="approximate frame count")
    parser.add_argument("--steps", default="", help='optional steps separated by "|"')
    args = parser.parse_args(argv)
    if not args.video.is_file():
        print(f"No such file: {args.video}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as folder:
        project_dir = Path(folder)
        frames_dir = project_dir / "candidates"
        found = extract_frame_finder_candidates(args.video, frames_dir, args.count)
        mode = read_manifest_mode(frames_dir / "manifest.json")
        print(f"extracted {len(found)} frames (mode: {mode})")
        try:
            result = run_ai_pass(
                found, project_dir=project_dir, candidates_rel_dir="candidates",
                title=args.video.stem, mode=mode,
                steps=[step.strip() for step in args.steps.split("|") if step.strip()] or None,
            )
        except AIPassError as error:
            print(f"AI pass failed: {error}", file=sys.stderr)
            return 1
    print(f"dish: {result.dish_name}")
    for number, slide in enumerate(result.slides, 1):
        print(f"{number:2d}. t={slide.timestamp:6.1f}s  {slide.caption}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
