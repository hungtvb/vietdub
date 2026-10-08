# Orchestrator: review stops, overnight enforcement, resume, failure.
# Heavy steps are stubbed; the integration test runs the real ones.
from unittest import mock

import pytest

from core import checkpoint as cp
from core.job import DONE, FAILED, REVIEW, Job
from core.orchestrator import STEPS, Orchestrator
from core.settings import Settings
from project.schema import Project


class StubOrchestrator(Orchestrator):
    """Stubs each step: writes its checkpoint, records call order."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.called = []
        self.fail_on = None

    def _run_step(self, step):
        self.called.append(step)
        if self.fail_on == step:
            raise RuntimeError(f"boom at {step}")
        shapes = {
            "fetch": {"video_path": "/tmp/x.mp4"},
            "extract": {"wav_path": "/tmp/x.wav"},
            "asr": {"segments": []},
            "gender": {"speakers": []},
            "analyze": {"speakers": []},
            "translate": {"segments": []},
            "tts": {"segments": []},
            "mix": {"mixed_wav": "/tmp/x.wav"},
            "render": {"video_out": "/tmp/x.mp4"},
        }
        cp.save_step(self.job.job_dir, step, shapes[step])


def _job(tmp_path, monkeypatch, **proj_kw):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    kw = dict(review_stops=True, overnight=False)
    kw.update(proj_kw)
    job = Job(project=Project(video_in="/tmp/x.mp4", **kw))
    return job


def test_review_stop_after_asr(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    orch = StubOrchestrator(job, Settings(
        path=tmp_path / "s.json"))
    status = orch.run()
    assert status == REVIEW
    assert job.resume_from == "gender"
    assert orch.called == ["fetch", "extract", "asr"]


def test_resume_continues_after_review(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    orch = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    assert orch.run() == REVIEW
    orch2 = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    assert orch2.run() == REVIEW  # stops again after translate
    assert orch2.called[0] == "gender"
    orch3 = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    assert orch3.run() == DONE


def test_overnight_skips_review_stops(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch, overnight=True, review_stops=True)
    orch = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    assert orch.run() == DONE
    assert orch.called == STEPS  # all 9, no pause


def test_failure_keeps_checkpoints(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch, review_stops=False)  # no review pause
    orch = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    orch.fail_on = "gender"
    assert orch.run() == FAILED
    assert cp.has_step(job.job_dir, "asr")
    assert not cp.has_step(job.job_dir, "gender")
    # resume reruns from the failed step, straight to done (no review stops)
    orch2 = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    assert orch2.run() == DONE
    assert orch2.called[0] == "gender"


def test_run_log_written(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    orch = StubOrchestrator(job, Settings(path=tmp_path / "s.json"))
    orch.run()
    assert job.run_log_path.exists()
    content = job.run_log_path.read_text(encoding="utf-8")
    assert "[2] Nghe + tách loa" in content


def test_no_blocking_input_in_core():
    # core must NEVER wait for user input (overnight safety).
    # Use AST so prose mentions in comments/docstrings don't false-positive.
    import ast
    import pathlib
    core_dir = pathlib.Path(__file__).resolve().parents[1] / "core"
    hits = []
    for f in core_dir.glob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "input":
                hits.append(f"{f.name}:{node.lineno}")
    assert not hits, f"blocking input() calls in core: {hits}"


# --- split-and-retry loop (edge 1) regression tests -------------------------
# The old for/else loop raised RuntimeError even when the final split had
# already fixed the problem. _fit_and_track is a while loop: plan() always
# runs again after a split.
from project.schema import Segment
from tts import duration_fit as mfit


def _fit_job(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch, review_stops=False)
    return Orchestrator(job, Settings(path=tmp_path / "s.json"))


def _long_seg():
    return Segment(index=0, start=0.0, end=5.0, speaker=0,
                   text_vi="câu này rất dài, cần phải tách ra, để vừa khung giờ")


def test_fit_reruns_plan_after_last_split(tmp_path, monkeypatch):
    orch = _fit_job(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_plan(segments, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise mfit.TooLongError(segments[0], 2.0)
        return [(s, "keep", 1.0) for s in segments]

    monkeypatch.setattr(mfit, "plan", fake_plan)
    out, decisions = orch._fit_and_track([_long_seg()], tmp_path,
                                         lambda segs: segs)
    assert calls["n"] == 2  # plan ran again after the split -> no raise
    assert len(out) == 2  # sentence was split
    assert decisions[0][1] == "keep"


def test_fit_unsplittable_gets_overflow(tmp_path, monkeypatch):
    # sentence with no punctuation that cannot be split -> max squeeze +
    # overflow (edge 2 treatment), job does NOT die
    orch = _fit_job(tmp_path, monkeypatch)
    seg = Segment(index=0, start=0.0, end=5.0, speaker=0,
                  text_vi="ừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừừ")

    def fake_plan(segments, **kw):
        force = kw.get("force_overflow") or set()
        if id(segments[0]) in force:
            return [(segments[0], "overflow", 1.25)]
        raise mfit.TooLongError(segments[0], 2.0)

    def no_split(s):
        raise ValueError("không tách được")

    monkeypatch.setattr(mfit, "plan", fake_plan)
    monkeypatch.setattr(mfit, "split_segment", no_split)
    out, decisions = orch._fit_and_track([seg], tmp_path,
                                         lambda segs: segs)
    assert decisions[0][1] == "overflow"
    assert len(out) == 1


def test_fit_gives_up_after_max_rounds(tmp_path, monkeypatch):
    orch = _fit_job(tmp_path, monkeypatch)

    def always_long(segments, **kw):
        raise mfit.TooLongError(segments[0], 2.0)

    monkeypatch.setattr(mfit, "plan", always_long)
    with pytest.raises(RuntimeError) as e:
        orch._fit_and_track([_long_seg()], tmp_path, lambda segs: segs)
    assert "3 lần" in str(e.value)


def test_tts_falls_back_to_gtts(tmp_path, monkeypatch):
    # Edge-TTS total failure -> gTTS (single voice), logged
    from tts import edge_tts as metts
    from tts import gtts as mgtts
    orch = _fit_job(tmp_path, monkeypatch)
    bad_tts = mock.Mock()
    bad_tts.synthesize.side_effect = metts.TTSError("websocket down")
    fake_g = mock.Mock()
    fake_g.synthesize.side_effect = lambda segs, d: segs
    monkeypatch.setattr(mgtts, "GTTS", lambda: fake_g)
    out = orch._synthesize_tts(bad_tts, [_long_seg()], tmp_path)
    assert fake_g.synthesize.called
    assert out[0].text_vi
