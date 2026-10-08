# Edge case 16: corrupt checkpoint -> drop, re-run from previous step
import json

from core import checkpoint as cp


def test_save_load_roundtrip(job_dir):
    cp.save_step(job_dir, "asr", {"segments": [{"index": 0}]})
    data = cp.load_step(job_dir, "asr")
    assert data == {"segments": [{"index": 0}]}


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
