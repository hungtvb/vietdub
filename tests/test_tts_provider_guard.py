"""Unsupported TTS engines must fail explicitly, never impersonate Edge-TTS."""
import pytest

from core.job import Job
from core.orchestrator import Orchestrator
from core.settings import Settings
from project.schema import Project


def test_unsupported_engine_does_not_silently_generate_with_edge(tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    settings = Settings(path=tmp_path / "settings.json")
    settings.set("tts_provider", "unsupported-engine")
    project = Project()
    # Old jobs read the global provider; new jobs pin it per project.
    # Both paths must reject a genuinely unsupported provider explicitly.
    if hasattr(project, "tts_provider"):
        project.tts_provider = "unsupported-engine"
    job = Job(project=project)
    from project import io as pio
    from project.schema import Segment
    # The translate stage must have at least one line or the pipeline
    # legitimately rejects missing content before selecting any provider.
    pio.save_segments(job.job_dir, "translate", [
        Segment(index=0, start=0, end=1, speaker=0,
                text_src="Hello", text_vi="Xin chào")
    ])
    orchestrator = Orchestrator(job, settings)
    with pytest.raises(ValueError, match="(?i)unsupported.*provider"):
        orchestrator._step_tts()
