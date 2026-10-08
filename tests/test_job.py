# Job/overnight: overnight=True forces review_stops off (enforced in code).
# Job owns its directory; settings JSON load/save roundtrip.
from core.job import DONE, FAILED, IDLE, REVIEW, Job
from core.settings import Settings
from project.schema import Project


def test_overnight_forces_no_review_stops():
    p = Project(review_stops=True, overnight=True)
    assert p.effective_review_stops() is False


def test_review_stops_normal():
    p = Project(review_stops=True, overnight=False)
    assert p.effective_review_stops() is True
    p2 = Project(review_stops=False, overnight=False)
    assert p2.effective_review_stops() is False


def test_job_dirs_created(tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    job = Job()
    assert job.status == IDLE
    assert job.job_dir.exists()
    assert job.stages_dir.exists()
    assert job.run_log_path.parent == job.job_dir


def test_job_serialization(tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    job = Job()
    job.project.video_source = "url"
    job.project.video_url = "https://example.com/v"
    d = job.to_dict()
    job2 = Job.from_dict(d)
    assert job2.job_id == job.job_id
    assert job2.project.video_url == "https://example.com/v"


def test_settings_save_load(tmp_path):
    s = Settings(path=tmp_path / "settings.json")
    s.set("nine_router_key", "secret123")
    s.set("crf", 23)
    s.save()
    s2 = Settings(path=tmp_path / "settings.json")
    assert s2.get("nine_router_key") == "secret123"
    assert s2.get("crf") == 23
    assert s2.get("nine_router_model") == "mimo-v2.6-flash-free"  # default


def test_settings_corrupt_file_uses_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{broken", encoding="utf-8")
    s = Settings(path=p)
    assert s.get("crf") == 20


def test_settings_get_unknown_key():
    s = Settings(path="/tmp/vd_settings_nonexistent_xyz/settings.json")
    assert s.get("nope", "dflt") == "dflt"
