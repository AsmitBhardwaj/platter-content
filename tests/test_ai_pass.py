import base64
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from recipe_slides import ai_pass
from recipe_slides.ai_pass import (
    AIPassError,
    FrameInput,
    apply_ai_result,
    parse_response,
    read_manifest_mode,
    run_ai_pass,
    select_frames,
)
from recipe_slides.candidates import FrameCandidate, save_manifest
from recipe_slides.editor import initialize_editor
from recipe_slides.models import Project


def candidate(name: str, timestamp: float, inside: bool = True) -> FrameCandidate:
    return FrameCandidate(
        path=name, timestamp=timestamp, scene_start=0, scene_end=10, brightness=0.5,
        brightness_score=1, sharpness=100, crop_score=1, image_hash="0" * 16,
        in_analysis_range=inside,
    )


class FakeClient:
    def __init__(self, content: str, prompt_tokens: int = 1200, completion_tokens: int = 90) -> None:
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content
        self._usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content))],
            usage=self._usage,
        )


@pytest.fixture
def frames_dir(tmp_path: Path) -> tuple[Path, list[FrameCandidate]]:
    folder = tmp_path / "candidates"
    folder.mkdir()
    items = []
    for number in range(4):
        Image.new("RGB", (1920, 1080), (40 * number, 80, 120)).save(folder / f"f{number}.jpg")
        items.append(candidate(f"f{number}.jpg", number * 2.5))
    return tmp_path, items


def test_select_frames_is_chronological_and_capped() -> None:
    many = [candidate(f"f{i}.jpg", float(100 - i)) for i in range(60)]
    selected = select_frames(many, "candidates", limit=40)
    assert len(selected) == 40
    assert [f.timestamp for f in selected] == sorted(f.timestamp for f in selected)
    assert [f.index for f in selected] == list(range(40))
    assert selected[0].path.startswith("candidates/")


def test_select_frames_prefers_cooking_range_when_over_cap() -> None:
    inside = [candidate(f"i{i}.jpg", float(i)) for i in range(39)]
    outside = [candidate(f"o{i}.jpg", float(100 + i), inside=False) for i in range(5)]
    selected = select_frames(inside + outside, "c", limit=40)
    assert len(selected) == 40
    assert sum(not f.in_analysis_range for f in selected) == 1


FRAMES = [
    FrameInput(0, "c/a.jpg", 1.0, True),
    FrameInput(1, "c/b.jpg", 4.0, True),
    FrameInput(2, "c/c.jpg", 8.0, True),
]


def test_parse_maps_indexes_to_frames_and_normalizes_captions() -> None:
    text = json.dumps(
        {
            "dish_name": " Tiramisu ",
            "slides": [
                {"frame_index": 2, "caption": "  Whisk It Well ;)  "},
                {"frame_index": 0, "caption": "add 4 tbsp of sugar"},
            ],
        }
    )
    dish, slides = parse_response(text, FRAMES)
    assert dish == "Tiramisu"
    assert [(s.frame, s.caption) for s in slides] == [
        ("c/a.jpg", "add 4 tbsp of sugar"),
        ("c/c.jpg", "whisk it well ;)"),
    ]


def test_parse_drops_invalid_duplicate_and_empty_slides() -> None:
    text = json.dumps(
        {
            "dish_name": "x",
            "slides": [
                {"frame_index": 9, "caption": "out of range"},
                {"frame_index": 1, "caption": "mix it"},
                {"frame_index": 1, "caption": "mix it again"},
                {"frame_index": 0, "caption": "   "},
                {"frame_index": "2", "caption": "string index"},
                {"frame_index": True, "caption": "bool index"},
            ],
        }
    )
    _, slides = parse_response(text, FRAMES)
    assert [(s.frame, s.caption) for s in slides] == [("c/b.jpg", "mix it")]


@pytest.mark.parametrize("bad", ["not json", "[]", '{"dish_name": "x"}', '{"slides": []}'])
def test_parse_rejects_unusable_responses(bad: str) -> None:
    with pytest.raises(AIPassError):
        parse_response(bad, FRAMES)


def test_run_ai_pass_sends_downscaled_labeled_frames(frames_dir, capsys) -> None:
    project_dir, items = frames_dir
    reply = json.dumps(
        {"dish_name": "Pancakes", "slides": [{"frame_index": 1, "caption": "heat it up ;)"}]}
    )
    client = FakeClient(reply)
    result = run_ai_pass(
        items, project_dir=project_dir, candidates_rel_dir="candidates",
        title="My video", mode="interval-fallback", steps=["heat pan"], client=client,
    )
    assert result.dish_name == "Pancakes"
    assert result.slides[0].frame == "candidates/f1.jpg"
    assert (result.input_tokens, result.output_tokens) == (1200, 90)

    call = client.calls[0]
    assert call["model"] == "gpt-5.4-mini"
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["strict"] is True
    content = call["messages"][1]["content"]
    text = "\n".join(part["text"] for part in content if part["type"] == "text")
    assert "interval-fallback" in text and "My video" in text and "heat pan" in text
    assert "Frame 1 (t=2.5s)" in text
    images = [part for part in content if part["type"] == "image_url"]
    assert len(images) == 4
    data = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1])
    assert max(Image.open(BytesIO(data)).size) == 512
    assert "input_tokens=1200 output_tokens=90" in capsys.readouterr().out


def test_missing_key_is_a_clean_error(frames_dir, monkeypatch, tmp_path) -> None:
    project_dir, items = frames_dir
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(ai_pass, "ENV_PATH", tmp_path / "missing.env")
    with pytest.raises(AIPassError, match="OPENAI_API_KEY"):
        run_ai_pass(items, project_dir=project_dir, candidates_rel_dir="candidates", title="t", mode="scenes")


def test_api_failure_becomes_ai_pass_error(frames_dir) -> None:
    project_dir, items = frames_dir

    class Boom:
        chat = SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(RuntimeError("rate limited")))
        )

    with pytest.raises(AIPassError, match="rate limited"):
        run_ai_pass(items, project_dir=project_dir, candidates_rel_dir="candidates",
                    title="t", mode="scenes", client=Boom())


def test_apply_result_prefills_editor_slides(frames_dir) -> None:
    project_dir, items = frames_dir
    reply = json.dumps(
        {"dish_name": "Pancakes", "slides": [
            {"frame_index": 0, "caption": "add 2 eggs"},
            {"frame_index": 2, "caption": "whisk it well ;)"},
        ]}
    )
    result = run_ai_pass(items, project_dir=project_dir, candidates_rel_dir="candidates",
                         title="t", mode="scenes", client=FakeClient(reply))
    project = Project(project_id="p", title="Frame Finder", episode="", steps=[], workflow_mode="frame_finder",
                      frame_order=["candidates/f3.jpg"])
    project.editor_initialized = True
    apply_ai_result(project, result)
    assert project.title == "Pancakes"
    assert project.frame_order == ["candidates/f0.jpg", "candidates/f2.jpg"]
    initialize_editor(project)
    assert [s.source_frame for s in project.editor_slides] == project.frame_order
    assert [s.layers[0].text for s in project.editor_slides] == ["add 2 eggs", "whisk it well ;)"]


def test_read_manifest_mode(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    save_manifest(path, [], 10.0, {"mode": "interval-fallback"})
    assert read_manifest_mode(path) == "interval-fallback"
    assert read_manifest_mode(tmp_path / "none.json") == "scenes"
