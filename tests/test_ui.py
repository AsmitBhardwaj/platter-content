from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

from recipe_slides.candidates import FrameCandidate, save_manifest
from recipe_slides.storage import ProjectStore


APP_PATH = Path(__file__).parents[1] / "app.py"


def run_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=10).run()


def assert_stage(app: AppTest, heading: str) -> None:
    assert not app.exception
    assert heading in [item.value for item in app.subheader]


def create_project_fixture(tmp_path: Path):
    store = ProjectStore(tmp_path / "data" / "projects")
    project = store.create("Test Pasta", "8", ["Toss the pasta with the sauce."])
    candidates_dir = store.candidates_dir(project)
    candidates = []
    colors = [(170, 70, 40), (75, 105, 65), (205, 160, 80)]
    hashes = ["0000000000000000", "00ff00ff00ff00ff", "ffffffffffffffff"]
    for index, (color, image_hash) in enumerate(zip(colors, hashes), 1):
        filename = f"frame-{index:04d}.jpg"
        Image.new("RGB", (640, 360), color).save(candidates_dir / filename)
        candidates.append(
            FrameCandidate(
                path=filename,
                timestamp=float(index * 5),
                scene_start=0.0,
                scene_end=20.0,
                brightness=0.5,
                brightness_score=0.9,
                sharpness=80.0 + index,
                crop_score=0.8,
                image_hash=image_hash,
            )
        )
    save_manifest(candidates_dir / "manifest.json", candidates, 20.0)
    return store, project


def test_all_four_workflow_stages_render_without_exceptions(tmp_path: Path, monkeypatch) -> None:
    stage_one = tmp_path / "stage-one"
    stage_one.mkdir()
    monkeypatch.chdir(stage_one)

    new_project_app = run_app()
    assert_stage(new_project_app, "Find the strongest moments")

    stage_two = tmp_path / "stage-two"
    stage_two.mkdir()
    monkeypatch.chdir(stage_two)
    store = ProjectStore(stage_two / "data" / "projects")
    project = store.create("Source Stage", "1", ["Prepare the ingredients."])
    source_app = run_app()
    assert_stage(source_app, "Choose a video source")

    stage_three = tmp_path / "stage-three"
    stage_three.mkdir()
    monkeypatch.chdir(stage_three)
    store, project = create_project_fixture(stage_three)
    frame_app = run_app()
    assert_stage(frame_app, "Select frames")
    assert "Quality" in " ".join(item.value for item in frame_app.markdown)
    assert "No frame is assigned yet" in " ".join(item.value for item in frame_app.info)
    assert "Convert to Frame Finder" in [item.label for item in frame_app.button]

    project.selections["0"] = "candidates/frame-0001.jpg"
    project.crop_positions["0"] = {"x": 0.5, "y": 0.5}
    store.save(project)
    review_app = run_app()
    assert_stage(review_app, "Edit slides")
    assert "Export slideshow" in [item.label for item in review_app.button]


def test_frame_finder_gallery_and_export_stages_render(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    store, project = create_project_fixture(tmp_path)
    project.workflow_mode = "frame_finder"
    project.steps = []
    project.target_slide_count = 3
    project.selections = {}
    store.save(project)

    gallery_app = run_app()
    assert_stage(gallery_app, "Refine your frame gallery")
    captions = " ".join(item.value for item in gallery_app.caption)
    assert "Sharpness" in captions
    assert "Overall quality" in captions

    project.frame_order = [
        "candidates/frame-0001.jpg",
        "candidates/frame-0002.jpg",
    ]
    store.save(project)
    export_app = run_app()
    assert_stage(export_app, "Edit slides")
    assert "Export frames" in [item.label for item in export_app.button]


def test_frame_finder_new_project_offers_upload_first() -> None:
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30)
    app.session_state["creating-project"] = True
    app.run()
    assert not app.exception
    source = next(item for item in app.radio if item.label == "Video source")
    assert source.options == ["Upload video file", "YouTube link"]
    assert source.value == "Upload video file"
    assert len(app.get("file_uploader")) == 1
