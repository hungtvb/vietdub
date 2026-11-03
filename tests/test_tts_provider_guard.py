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
    settings.set("tts_provider", "vieneu")  # available only after provider integration
    orchestrator = Orchestrator(Job(project=Project()), settings)
    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        orchestrator._step_tts()
