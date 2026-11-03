"""Human-approved character names survive gender/LLM analysis pipeline stages."""
from core import checkpoint as cp
from core import job as job_module
from core.job import Job
from core.orchestrator import Orchestrator
from project import io as pio
from project.schema import Project, Segment, Speaker
from translation.base import BaseTranslator


class TestSettings:
    def get(self, key, default=None):
        return default


def test_verified_character_survives_missing_pitch_model(tmp_path, monkeypatch):
    monkeypatch.setattr(job_module, "JOBS_ROOT", tmp_path)
    job = Job(job_id="verified-speaker-test", project=Project(name="English video"))
    wav = job.stages_dir / "audio.wav"
    wav.write_bytes(b"test")
    cp.save_step(job.job_dir, "extract", {"wav_path": str(wav)})
    segment = Segment(index=0, start=1, end=2, speaker=7,
                      text_src="Hello", character_id="CHAR_001",
                      character_name="Maddie", identity_status="VERIFIED",
                      detected_speaker=0)
    pio.save_segments(job.job_dir, "asr", [segment])
    pio.save_speakers(job.job_dir, "gender", {
        7: Speaker(id=7, character_name="Maddie",
                   identity_verified=True, role="Maddie")})
    import speaker.gender as g
    monkeypatch.setattr(g, "estimate_genders", lambda *args, **kwargs: {})
    orchestrator = Orchestrator(job, TestSettings())
    orchestrator._step_gender()
    saved = pio.load_speakers(job.job_dir, "gender")
    assert 7 in saved
    assert saved[7].character_name == "Maddie"
    assert saved[7].identity_verified is True
    assert pio.load_segments(job.job_dir, "asr")[0].character_name == "Maddie"


def test_translation_headers_only_disclose_explicitly_verified_names():
    verified = Segment(index=0, start=0, end=2, speaker=7,
                       text_src="Hello", character_name="Maddie",
                       identity_status="VERIFIED")
    inferred = Segment(index=1, start=2, end=4, speaker=0,
                       text_src="Hi", character_name="Ethan",
                       identity_status="UNVERIFIED")
    assert "[verified character: Maddie]" in BaseTranslator._line_header(verified)
    assert "Ethan" not in BaseTranslator._line_header(inferred)


def test_source_review_gender_overrides_low_confidence_and_filters_stale_speakers(tmp_path, monkeypatch):
    monkeypatch.setattr(job_module, "JOBS_ROOT", tmp_path)
    job = Job(job_id="gender-review-override", project=Project())
    wav = job.stages_dir / "audio.wav"
    wav.write_bytes(b"test")
    cp.save_step(job.job_dir, "extract", {"wav_path": str(wav)})
    pio.save_segments(job.job_dir, "asr", [
        Segment(index=0, start=0, end=1, speaker=7, text_src="Hello"),
        Segment(index=1, start=1, end=2, speaker=8, text_src="Hi"),
    ])
    # The source review checkpoint is a single atomic snapshot of both
    # reviewed segments and speakers. A speakers-only checkpoint is invalid.
    cp.save_step(job.job_dir, "source_review", {
        "segments": [seg.to_dict() for seg in
                     pio.load_segments(job.job_dir, "asr")],
        "speakers": [
            Speaker(id=7, gender="female", confidence=1,
                    character_name="Maddie", identity_verified=True).to_dict(),
            Speaker(id=99, gender="male", confidence=1,
                    character_name="Stale", identity_verified=True).to_dict(),
        ],
    })
    import speaker.gender as gender
    monkeypatch.setattr(gender, "estimate_genders", lambda *a, **kw: {
        7: Speaker(id=7, gender="male", confidence=0.4),
        8: Speaker(id=8, gender="female", confidence=0.2),
    })
    orch = Orchestrator(job, TestSettings())
    orch._step_gender()
    speakers = pio.load_speakers(job.job_dir, "gender")
    assert speakers[7].gender == "female"
    assert speakers[7].character_name == "Maddie"
    assert speakers[7].identity_verified
    assert 99 not in speakers
    lines = pio.load_segments(job.job_dir, "asr")
    assert lines[0].gender == "female"
    assert not lines[0].needs_review
    assert lines[1].needs_review  # no reviewed label and weak pitch evidence
