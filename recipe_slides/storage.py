from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import Project


def make_project_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    slug = slug or "recipe"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{stamp}-{uuid4().hex[:6]}"


class ProjectStore:
    def __init__(self, root: Path | str = "data/projects") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", project_id):
            raise ValueError("Invalid project id")
        return self.root / project_id

    def create(
        self,
        title: str,
        episode: str,
        steps: list[str],
        *,
        workflow_mode: str = "recipe_steps",
        target_slide_count: int = 8,
    ) -> Project:
        project = Project(
            make_project_id(title),
            title,
            episode,
            steps,
            workflow_mode=workflow_mode,
            target_slide_count=target_slide_count,
        )
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        directory = self.project_dir(project.project_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "project.json"
        temporary = directory / "project.json.tmp"
        temporary.write_text(
            json.dumps(project.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(target)

    def load(self, project_id: str) -> Project:
        metadata = self.project_dir(project_id) / "project.json"
        return Project.from_dict(json.loads(metadata.read_text(encoding="utf-8")))

    def list_projects(self) -> list[Project]:
        projects: list[Project] = []
        for metadata in self.root.glob("*/project.json"):
            try:
                projects.append(
                    Project.from_dict(json.loads(metadata.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return sorted(projects, key=lambda item: item.project_id, reverse=True)

    def save_video(self, project: Project, uploaded_file: object) -> Path:
        suffix = Path(getattr(uploaded_file, "name", "video.mp4")).suffix.lower()
        if suffix not in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}:
            raise ValueError("Unsupported video type")
        directory = self.project_dir(project.project_id) / "media"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"source{suffix}"
        with target.open("wb") as output:
            shutil.copyfileobj(uploaded_file, output)
        project.video_filename = str(target.relative_to(self.project_dir(project.project_id)))
        project.video_source = "upload"
        project.source_url = None
        project.source_title = getattr(uploaded_file, "name", target.name)
        project.source_thumbnail = None
        self.clear_candidates(project)
        project.selections = {}
        project.crop_positions = {}
        project.frame_order = []
        project.frame_texts = {}
        project.frame_crops = {}
        project.frame_roles = {}
        project.editor_slides = []
        project.editor_initialized = False
        project.editor_source_signature = None
        self.save(project)
        return target

    def register_youtube_video(
        self,
        project: Project,
        video_path: Path,
        *,
        url: str,
        title: str,
        thumbnail_path: Path | None,
    ) -> None:
        directory = self.project_dir(project.project_id)
        project.video_filename = str(video_path.relative_to(directory))
        project.video_source = "youtube"
        project.source_url = url
        project.source_title = title
        project.source_thumbnail = (
            str(thumbnail_path.relative_to(directory)) if thumbnail_path else None
        )
        self.clear_candidates(project)
        project.selections = {}
        project.crop_positions = {}
        project.frame_order = []
        project.frame_texts = {}
        project.frame_crops = {}
        project.frame_roles = {}
        project.editor_slides = []
        project.editor_initialized = False
        project.editor_source_signature = None
        self.save(project)

    def convert_to_frame_finder(self, project: Project) -> None:
        """Convert workflow metadata without touching source media or candidate assets."""
        project.workflow_mode = "frame_finder"
        project.target_slide_count = max(1, len(project.steps) or project.target_slide_count)
        # Old numeric selections came from chronological step partitioning, so they are
        # intentionally not promoted to the new user-authored frame sequence.
        project.frame_order = []
        project.frame_texts = {}
        project.frame_crops = {}
        project.frame_roles = {}
        project.editor_slides = []
        project.editor_initialized = False
        project.editor_source_signature = None
        self.save(project)

    def video_path(self, project: Project) -> Path | None:
        if not project.video_filename:
            return None
        path = self.project_dir(project.project_id) / project.video_filename
        return path if path.exists() else None

    def clear_source_video(self, project: Project) -> bool:
        """Delete only the cached source, preserving frames, thumbnails, and exports."""
        path = self.video_path(project)
        deleted = False
        if path is not None:
            path.unlink()
            deleted = True
        project.video_filename = None
        self.save(project)
        return deleted

    def candidates_dir(self, project: Project) -> Path:
        path = self.project_dir(project.project_id) / "candidates"
        path.mkdir(parents=True, exist_ok=True)
        return path
    def clear_candidates(self, project: Project) -> None:
        directory = self.project_dir(project.project_id) / "candidates"
        if directory.exists():
            for frame in directory.glob("frame-*.jpg"):
                frame.unlink()
            manifest = directory / "manifest.json"
            manifest.unlink(missing_ok=True)

    def thumbnail_path(self, project: Project) -> Path | None:
        if not project.source_thumbnail:
            return None
        path = self.project_dir(project.project_id) / project.source_thumbnail
        return path if path.exists() else None

    def export_dir(self, project: Project) -> Path:
        path = self.project_dir(project.project_id) / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path
