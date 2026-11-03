# Edge case 16: corrupt checkpoint -> drop, re-run from previous step
import json

from core import checkpoint as cp


def test_save_load_roundtrip(job_dir):
    from project.schema import Segment
    row = Segment(index=0, start=0.0, end=1.0, speaker=1,
                  detected_speaker=None, character_name="Maddie").to_dict()
    cp.save_step(job_dir, "asr", {"segments": [row]})
    data = cp.load_step(job_dir, "asr")
    assert data == {"segments": [row]}


def test_missing_returns_none(job_dir):
    assert cp.load_step(job_dir, "nope") is None
    assert cp.has_step(job_dir, "nope") is False


def test_corrupt_json_dropped(job_dir):
    # edge case 16: garbage file -> load returns None, file renamed .corrupt
    p = cp.stage_path(job_dir, "translate")
    p.write_text("{not valid json!!!", encoding="utf-8")
    assert cp.load_step(job_dir, "translate") is None
    assert not p.exists()
    assert p.with_suffix(".json.corrupt").exists()


def test_corrupt_structure_dropped(job_dir):
    # valid JSON but wrong shape for the step
    cp.save_step(job_dir, "fetch", {"nope": 1})
    assert cp.load_step(job_dir, "fetch") is None


def test_mark_done(job_dir):
    proj = {}
    cp.mark_done(job_dir, proj, "asr")
    assert "asr" in proj["stages_done"]
    saved = json.loads((job_dir / "project.json").read_text(encoding="utf-8"))
    assert "asr" in saved["stages_done"]


def test_mark_done_updates_project_in_ram(job_dir):
    # review fix: the in-RAM Project must see the finished step too
    from project.schema import Project
    proj = Project(name="x")
    cp.mark_done(job_dir, proj, "asr")
    assert proj.stages_done == ["asr"]
    saved = json.loads((job_dir / "project.json").read_text(encoding="utf-8"))
    assert saved["stages_done"] == ["asr"]
    cp.mark_done(job_dir, proj, "asr")  # idempotent
    assert proj.stages_done == ["asr"]


def test_multilingual_checkpoint_accepts_verified_speaker_fields(job_dir):
    from project.schema import Speaker, Segment
    seg = Segment(index=1, start=0.2, end=2.0, speaker=3,
                  detected_speaker=7, source_lang="en")
    cp.save_step(job_dir, "asr", {"segments": [seg.to_dict()]})
    assert cp.load_step(job_dir, "asr") is not None
    speaker = Speaker(id=3, identity_verified=True, character_name="Maddie")
    cp.save_step(job_dir, "gender", {"speakers": [speaker.to_dict()]})
    assert cp.load_step(job_dir, "gender") is not None


def test_invalid_multilingual_speaker_field_is_rejected(job_dir):
    from project.schema import Segment
    row = Segment(index=0, start=0, end=1, speaker=0).to_dict()
    row["detected_speaker"] = "not-an-integer"
    cp.save_step(job_dir, "asr", {"segments": [row]})
    assert cp.load_step(job_dir, "asr") is None
