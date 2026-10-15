from pathlib import Path

from recipe_slides.models import Project
from recipe_slides.storage import ProjectStore


def test_clear_source_preserves_frames_thumbnail_and_exports(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = Project("test-project", "Test", "1", ["Cook it"])
    store.save(project)
    project_dir = store.project_dir(project.project_id)
    media_dir = project_dir / "media"
    media_dir.mkdir()
    video = media_dir / "source-youtube.mp4"
    thumbnail = media_dir / "thumbnail.webp"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"thumbnail")
    store.register_youtube_video(
        project,
        video,
        url="https://youtu.be/abc123",
        title="Test video",
        thumbnail_path=thumbnail,
    )
    frame = store.candidates_dir(project) / "frame-001.jpg"
    exported = store.export_dir(project) / "01-step.png"
    frame.write_bytes(b"frame")
    exported.write_bytes(b"slide")

    assert store.clear_source_video(project)

    assert not video.exists()
    assert thumbnail.exists()
    assert frame.exists()
    assert exported.exists()
    assert store.video_path(project) is None
    assert store.load(project.project_id).video_filename is None
    assert project.settings.delete_source_after_export is True


def test_frame_only_project_round_trips_without_recipe_steps(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path / "projects")
    project = store.create(
        "Frame Finder",
        "",
        [],
        workflow_mode="frame_finder",
        target_slide_count=6,
    )
    project.frame_order = ["candidates/frame-0001.jpg"]
    project.frame_texts = {"candidates/frame-0001.jpg": ""}
    store.save(project)

    loaded = store.load(project.project_id)

    assert loaded.workflow_mode == "frame_finder"
    assert loaded.steps == []
    assert loaded.target_slide_count == 6
    assert loaded.frame_order == ["candidates/frame-0001.jpg"]


def test_legacy_project_defaults_to_recipe_workflow() -> None:
    project = Project.from_dict(
        {
            "project_id": "legacy-project",
            "title": "Legacy",
            "episode": "3",
            "steps": ["Cook it"],
        }
    )

    assert project.workflow_mode == "recipe_steps"
