from pathlib import Path

from PIL import Image

from recipe_slides.models import Project, SlideSettings
from recipe_slides.rendering import (
    SLIDE_SIZE,
    export_frame_finder_project,
    export_project,
    load_font,
    render_step_slide,
    wrap_text,
)


def test_wrap_text_respects_measured_width() -> None:
    font = load_font(42)
    lines = wrap_text("Chop the tomatoes and roast them until deeply caramelized", font, 320)
    assert len(lines) > 1
    assert " ".join(lines) == "Chop the tomatoes and roast them until deeply caramelized"


def test_wrap_text_preserves_explicit_line_breaks() -> None:
    font = load_font(32)
    assert wrap_text("First line\nSecond line", font, 1000) == ["First line", "Second line"]


def test_wrap_text_splits_a_word_wider_than_the_canvas() -> None:
    font = load_font(32)
    lines = wrap_text("supercalifragilisticexpialidocious", font, 100)
    assert len(lines) > 1
    assert "".join(lines) == "supercalifragilisticexpialidocious"


def test_render_step_slide_has_expected_size() -> None:
    frame = Image.new("RGB", (1600, 900), "tomato")
    rendered = render_step_slide(frame, 2, "Fold in the herbs and serve.", "white")
    assert rendered.size == SLIDE_SIZE
    assert rendered.mode == "RGB"


def test_render_step_slide_respects_saved_crop_position() -> None:
    frame = Image.new("RGB", (400, 200), "red")
    for x in range(200, 400):
        for y in range(200):
            frame.putpixel((x, y), (0, 0, 255))

    rendered = render_step_slide(frame, 1, "Cook", "white", x_position=1.0)

    assert rendered.getpixel((540, 100))[2] > rendered.getpixel((540, 100))[0]


def test_export_project_renders_numbered_pngs(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    Image.new("RGB", SLIDE_SIZE, "navy").save(candidates / "frame-001.jpg")
    project = Project(
        project_id="test-project",
        title="Tomato Pasta",
        episode="7",
        steps=["Roast the tomatoes."],
        selections={"0": "candidates/frame-001.jpg"},
        settings=SlideSettings(text_color="white", closing_text="Enjoy"),
    )

    outputs = export_project(project, tmp_path, tmp_path / "exports")

    assert [path.name for path in outputs] == ["00-cover.png", "01-step.png", "02-closing.png"]
    for output in outputs:
        with Image.open(output) as image:
            assert image.size == SLIDE_SIZE
            assert image.format == "PNG"


def test_frame_finder_exports_clean_frames_without_text(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    Image.new("RGB", (1600, 900), (28, 120, 70)).save(candidates / "frame-0001.jpg")
    project = Project(
        project_id="frame-only-project",
        title="Frame Finder",
        episode="",
        steps=[],
        workflow_mode="frame_finder",
        frame_order=["candidates/frame-0001.jpg"],
        frame_texts={"candidates/frame-0001.jpg": "This text must not render"},
    )

    outputs = export_frame_finder_project(
        project, tmp_path, tmp_path / "exports", include_text=False
    )

    assert [path.name for path in outputs] == ["01-frame.png"]
    with Image.open(outputs[0]) as image:
        assert image.size == SLIDE_SIZE
        center = image.getpixel((SLIDE_SIZE[0] // 2, SLIDE_SIZE[1] // 2))
        assert center[1] > center[0]
