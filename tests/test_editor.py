from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from recipe_slides.editor import apply_editor_value, initialize_editor
from recipe_slides.editor_rendering import export_editor_project, render_editor_slide
from recipe_slides.models import EditorSlide, Project, TextLayer


def test_legacy_recipe_layout_migrates_to_independent_editable_slides() -> None:
    project = Project(
        "legacy-project",
        "Tomato pasta",
        "4",
        ["Roast until jammy"],
        selections={"0": "candidates/frame.jpg"},
        crop_positions={"0": {"x": 0.2, "y": 0.7}},
    )

    assert initialize_editor(project)

    assert [slide.kind for slide in project.editor_slides] == ["cover", "recipe", "closing"]
    step = project.editor_slides[1]
    assert step.source_frame == "candidates/frame.jpg"
    assert step.crop == {"x": 0.2, "y": 0.7}
    assert step.layers[0].text == "STEP 01\nRoast until jammy"
    assert step.layers[0].background["enabled"] is True
    assert not initialize_editor(project)


def test_old_frame_instruction_becomes_one_editable_layer() -> None:
    frame = "candidates/frame-0001.jpg"
    project = Project(
        "finder-project",
        "Frames",
        "",
        [],
        workflow_mode="frame_finder",
        frame_order=[frame],
        frame_texts={frame: "Fold in the herbs"},
    )

    initialize_editor(project)

    assert len(project.editor_slides) == 1
    assert [layer.text for layer in project.editor_slides[0].layers] == ["Fold in the herbs"]


def test_component_value_round_trips_normalized_layer_geometry() -> None:
    project = Project("round-trip", "Test", "", [], workflow_mode="frame_finder")
    project.editor_initialized = True
    project.editor_slides = [EditorSlide(name="Blank", kind="blank")]
    raw = {
        "slides": [
            {
                "id": "slide-a",
                "name": "Blank",
                "kind": "blank",
                "background_color": "#222222",
                "layers": [
                    {
                        **TextLayer(text="Anywhere").__dict__,
                        "x": 0.371,
                        "y": 0.624,
                        "width": 0.413,
                        "rotation": 17.5,
                    }
                ],
            }
        ],
        "saved_styles": {"Personal": {"font_size": 71}},
    }

    apply_editor_value(project, raw)

    layer = project.editor_slides[0].layers[0]
    assert (layer.x, layer.y, layer.width, layer.rotation) == (0.371, 0.624, 0.413, 17.5)
    assert project.saved_text_styles["Personal"]["font_size"] == 71


def test_deterministic_renderer_composites_multiple_layers_in_z_order(tmp_path: Path) -> None:
    bottom = TextLayer(
        text="BOTTOM",
        x=0.1,
        y=0.2,
        width=0.55,
        color="#FF0000",
        font_size=80,
        background={"enabled": True, "color": "#00FF00", "opacity": 1, "padding": 18, "corner_radius": 12},
        z_index=0,
    )
    top = TextLayer(
        text="TOP",
        x=0.13,
        y=0.22,
        width=0.4,
        color="#FFFFFF",
        font_size=72,
        rotation=-9,
        stroke={"color": "#000000", "width": 3},
        shadow={"color": "#000000", "opacity": 0.8, "blur": 5, "offset_x": 8, "offset_y": 9},
        z_index=1,
    )
    slide = EditorSlide(name="Fixture", kind="blank", background_color="#112233", layers=[top, bottom])

    first = render_editor_slide(slide, tmp_path)
    second = render_editor_slide(slide, tmp_path)

    assert first.size == (1080, 1440)
    assert ImageChops.difference(first, second).getbbox() is None
    assert first.getpixel((10, 10)) == (17, 34, 51)
    assert ImageChops.difference(first, Image.new("RGB", first.size, "#112233")).getbbox()


def test_editor_export_keeps_text_optional_and_numbered(tmp_path: Path) -> None:
    slides = [
        EditorSlide(name="Clean", kind="blank", background_color="#123456"),
        EditorSlide(name="Text", kind="closing", layers=[TextLayer(text="SAVE", x=0.2, y=0.4)]),
    ]

    outputs, warnings = export_editor_project(slides, tmp_path, tmp_path / "exports")

    assert [path.name for path in outputs] == ["01-blank.png", "02-closing.png"]
    assert all(Image.open(path).size == (1080, 1440) for path in outputs)
    assert isinstance(warnings, list)
