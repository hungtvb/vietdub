"""Per-job visual cleanup reproducibility tests (no OCR weights required)."""
from core.job import Job
from core.orchestrator import Orchestrator
from core.settings import Settings
from project.schema import Project


def test_visual_cleanup_snapshot_is_independent_of_global_preferences(tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    settings = Settings(path=tmp_path / "settings.json")
    settings.set("visual_cleanup_enabled", True)
    settings.set("visual_cleanup_backend", "cv")
    project = Project(visual_cleanup_options={
        "visual_cleanup_enabled": True,
        "visual_cleanup_backend": "cv",
        "visual_cleanup_mode": "blur",
        "visual_cleanup_review_plan": "",
    })
    job = Job(project=project)
    orchestrator = Orchestrator(job, settings)
    original = orchestrator._visual_cleanup_signature()
    assert original["backend"] == "cv"

    # Another job's UI actions must not silently alter this job's render.
    settings.set("visual_cleanup_enabled", False)
    settings.set("visual_cleanup_backend", "vsr")
    settings.set("visual_cleanup_mode", "inpaint")
    assert orchestrator._visual_cleanup_signature() == original
    assert project.to_dict()["visual_cleanup_options"] == project.visual_cleanup_options
    assert Project.from_dict(project.to_dict()).visual_cleanup_options == project.visual_cleanup_options


def test_legacy_jobs_continue_using_settings(tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    settings = Settings(path=tmp_path / "settings.json")
    job = Job(project=Project())  # Old project.json has no visual options
    orchestrator = Orchestrator(job, settings)
    assert orchestrator._visual_cleanup_signature() is None
    settings.set("visual_cleanup_enabled", True)
    assert orchestrator._visual_cleanup_signature()["enabled"] is True


def test_snapshot_weight_signature_survives_json_roundtrip(tmp_path, monkeypatch):
    import json
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    weights = tmp_path / "model.pt"
    weights.write_bytes(b"dummy")
    options = {
        "visual_cleanup_enabled": True,
        "visual_cleanup_backend": "lama-cpu",
        "visual_lama_weight_path": str(weights),
        "visual_cleanup_review_plan": "",
    }
    orch = Orchestrator(Job(project=Project(visual_cleanup_options=options)),
                        Settings(path=tmp_path / "s.json"))
    signature = orch._visual_cleanup_signature()
    assert signature == json.loads(json.dumps(signature))
