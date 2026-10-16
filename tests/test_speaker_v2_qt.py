"""Native PySide6 smoke for per-video speaker V2 review (QT_QPA_PLATFORM=offscreen)."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog
from core import job as job_module
from core.job import Job
from project import io as pio
from project.schema import Project, Segment
from ui.speaker_verification import SpeakerVerificationDialog
from ui.review_source import ReviewSourceWindow


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setattr(job_module, "JOBS_ROOT", tmp_path)
    video = tmp_path / "source.mp4"
    video.write_bytes(b"original movie bytes")
    job = Job(job_id="voice-test-job", project=Project(
        name="Multilingual drama", video_in=str(video), src_lang="auto"))
    wav = job.stages_dir / "audio.wav"
    wav.write_bytes(b"audio-file-identity-original")
    lines = [
        Segment(index=0, start=1, end=3, speaker=0,
                text_src="Hello", source_lang="en"),
        Segment(index=1, start=4, end=6, speaker=0,
                text_src="你好", source_lang="zh"),
    ]
    pio.save_segments(job.job_dir, "asr", lines)
    anchor_dir = job.stages_dir / "voice_anchor_review"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    (anchor_dir / "voice_anchor_candidates.json").write_text(json.dumps({
        "clusters": ["S0"],
        "candidates": [{"candidate_id": "sample_a", "start": 1, "end": 2.5,
                        "cluster": "S0", "file": "clips/a.wav",
                        "source_asr_ids": [0]}],
    }), encoding="utf-8")
    (anchor_dir / "clips").mkdir(exist_ok=True)
    (anchor_dir / "clips" / "a.wav").write_bytes(b"audio-sample")
    return job, wav, lines


def test_native_dialog_saves_only_human_confirmed_line(app, sample):
    job, wav, lines = sample
    dlg = SpeakerVerificationDialog(job, lines, wav)
    assert dlg.tabs.count() == 2
    assert dlg.anchors_table.rowCount() == 1
    assert dlg.lines_table.rowCount() == 2
    dlg.anchors_table.selectRow(0)
    dlg.name.setCurrentText("Maddie")
    dlg.heard.setChecked(True)
    dlg.watched.setChecked(True)
    dlg.verify_selected()
    assert dlg.store.summary()["verified_lines"] == 0
    dlg.tabs.setCurrentIndex(1)
    dlg.lines_table.selectRow(0)
    dlg.name.setCurrentText("Maddie")
    dlg.heard.setChecked(True)
    dlg.watched.setChecked(True)
    dlg.verify_selected()
    assert dlg.store.summary()["verified_lines"] == 1
    assert lines[1].identity_status == "UNVERIFIED"
    dlg.save()
    assert dlg.result() == QDialog.Accepted
    assert lines[0].character_name == "Maddie"
    assert not dlg.store.state["translation_approved"]


def test_close_without_save_reverts_in_memory_changes(app, sample):
    job, wav, lines = sample
    dlg = SpeakerVerificationDialog(job, lines, wav)
    before = [dict(x.__dict__) for x in lines]
    dlg.tabs.setCurrentIndex(1)
    dlg.lines_table.selectRow(1)
    dlg.name.setCurrentText("Ethan")
    dlg.heard.setChecked(True)
    dlg.watched.setChecked(True)
    dlg.verify_selected()
    assert lines[1].identity_status == "VERIFIED"
    dlg.reject()
    assert [dict(x.__dict__) for x in lines] == before


def test_asr_review_displays_character_column(app, sample):
    job, wav, lines = sample
    pio.save_segments(job.job_dir, "asr", lines)
    dlg = ReviewSourceWindow(job, None, lambda: None, lambda: None)
    assert dlg.tbl.columnCount() == 8
    assert dlg.btn_anchor.text() == "Xác minh nhân vật V2"
    assert dlg.tbl.item(0, 7).text() in ("Chưa xác minh", "Maddie ✓")
    dlg.close()
