import pytest
from PIL import Image, ImageDraw, ImageFilter

from recipe_slides.candidates import (
    FrameCandidate,
    assign_candidates_to_steps,
    brightness_metrics,
    clamp_timestamp,
    crop_box,
    crop_frame,
    rank_burst_frames,
    move_frame,
    rank_candidates,
    remove_duplicates,
    select_frame_finder_output,
    sharpness_score,
)
from recipe_slides.ffmpeg import (
    clip_scenes_to_range,
    scene_sample_timestamps,
    validate_analysis_range,
)


def candidate(timestamp: float, **overrides: object) -> FrameCandidate:
    values: dict[str, object] = {
        "path": f"frame-{timestamp}.jpg",
        "timestamp": timestamp,
        "scene_start": 0.0,
        "scene_end": 100.0,
        "brightness": 0.5,
        "brightness_score": 1.0,
        "sharpness": 100.0,
        "crop_score": 1.0,
        "image_hash": f"{int(timestamp):016x}",
        "uniqueness": 1.0,
    }
    values.update(overrides)
    return FrameCandidate(**values)  # type: ignore[arg-type]


def test_scene_sampling_uses_stable_middle_and_preserves_order() -> None:
    samples = scene_sample_timestamps([(0.0, 10.0), (10.0, 30.0)], 3)

    assert [round(item[0], 2) for item in samples] == [3.33, 5.0, 6.67, 16.67, 20.0, 23.33]
    assert all(scene[0] < timestamp < scene[1] for timestamp, scene in samples)


def test_analysis_range_clips_scene_candidates() -> None:
    scenes = [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]

    assert clip_scenes_to_range(scenes, 3.0, 9.0) == [
        (3.0, 4.0),
        (4.0, 8.0),
        (8.0, 9.0),
    ]
    assert validate_analysis_range(12.0, 3.0, 20.0) == (3.0, 12.0)


def test_analysis_range_rejects_reversed_boundaries() -> None:
    with pytest.raises(ValueError, match="start must be before"):
        validate_analysis_range(12.0, 9.0, 3.0)


def test_brightness_scoring_rejects_extremes_in_favor_of_midtones() -> None:
    dark = brightness_metrics(Image.new("RGB", (100, 100), (0, 0, 0)))
    middle = brightness_metrics(Image.new("RGB", (100, 100), (132, 132, 132)))
    bright = brightness_metrics(Image.new("RGB", (100, 100), (255, 255, 255)))

    assert dark[0] == 0.0
    assert bright[0] == 1.0
    assert middle[1] > dark[1]
    assert middle[1] > bright[1]


def test_sharpness_score_distinguishes_detail_from_motion_blur() -> None:
    detailed = Image.new("L", (320, 320), 0)
    draw = ImageDraw.Draw(detailed)
    for x in range(0, 320, 12):
        draw.rectangle((x, 0, x + 5, 319), fill=255)
    blurred = detailed.filter(ImageFilter.GaussianBlur(8))

    assert sharpness_score(detailed) > sharpness_score(blurred) * 2


def test_duplicate_removal_keeps_chronological_first_and_distinct_frames() -> None:
    first = candidate(1, image_hash="0000000000000000")
    duplicate = candidate(2, image_hash="0000000000000001")
    distinct = candidate(3, image_hash="ffffffffffffffff")

    assert remove_duplicates([distinct, duplicate, first]) == [first, distinct]


def test_chronological_assignment_is_disjoint_and_keeps_early_steps_early() -> None:
    values = [candidate(float(value)) for value in range(12)]
    groups = assign_candidates_to_steps(list(reversed(values)), 3)

    assert [[item.timestamp for item in group] for group in groups] == [
        [0.0, 1.0, 2.0, 3.0],
        [4.0, 5.0, 6.0, 7.0],
        [8.0, 9.0, 10.0, 11.0],
    ]
    assert max(item.timestamp for item in groups[0]) < min(item.timestamp for item in groups[-1])


def test_ranking_combines_quality_and_step_timing() -> None:
    weak = candidate(15, sharpness=10.0, brightness_score=0.1, uniqueness=0.1, crop_score=0.1)
    strong = candidate(17, sharpness=200.0, brightness_score=1.0, uniqueness=1.0, crop_score=1.0)

    assert rank_candidates([weak, strong], step_index=0, step_count=3, duration=100)[0] is strong


def test_burst_ranking_prefers_sharp_stable_well_exposed_frame() -> None:
    blurred = candidate(10.0, sharpness=20.0, brightness_score=1.0, stability=1.0)
    transition = candidate(10.25, sharpness=500.0, brightness_score=1.0, stability=0.1)
    clear = candidate(10.5, sharpness=180.0, brightness_score=0.95, stability=1.0)

    ranked = rank_burst_frames([blurred, transition, clear])

    assert ranked[0] is clear
    assert transition not in ranked


def test_frame_finder_output_is_chronological_after_quality_selection() -> None:
    values = [
        candidate(30.0, sharpness=250.0, image_hash="ffffffffffffffff"),
        candidate(10.0, sharpness=200.0, image_hash="0000000000000000"),
        candidate(20.0, sharpness=5.0, image_hash="aaaaaaaaaaaaaaaa"),
    ]

    selected = select_frame_finder_output(values, 2)

    assert [item.timestamp for item in selected] == [10.0, 30.0]


def test_frame_first_ordering_is_user_controlled() -> None:
    original = ["cover.jpg", "mix.jpg", "serve.jpg"]

    reordered = move_frame(original, 2, -1)

    assert reordered == ["cover.jpg", "serve.jpg", "mix.jpg"]
    assert original == ["cover.jpg", "mix.jpg", "serve.jpg"]


def test_crop_position_moves_portrait_window_horizontally() -> None:
    source = Image.new("RGB", (400, 200), "red")
    ImageDraw.Draw(source).rectangle((200, 0, 399, 199), fill="blue")

    assert crop_box(source.size, x_position=0.0)[0] == 0
    assert crop_box(source.size, x_position=1.0)[2] == 400
    left = crop_frame(source, (60, 80), x_position=0.0)
    right = crop_frame(source, (60, 80), x_position=1.0)
    assert left.getpixel((30, 40))[0] > left.getpixel((30, 40))[2]
    assert right.getpixel((30, 40))[2] > right.getpixel((30, 40))[0]


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(-4.0, 0.0), (12.0, 12.0), (101.0, 99.95)],
)
def test_timestamp_boundaries(requested: float, expected: float) -> None:
    assert clamp_timestamp(requested, 100.0) == pytest.approx(expected)
