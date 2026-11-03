# GUI smoke tests. No TTS model or sound device required.
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from core.job import Job
from core.settings import Settings
from ui.main_window import MainWindow, VoicePreviewWorker
from ui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_switch_tts_engines_keeps_independent_voice_choices(app, tmp_path, monkeypatch):
    import core.job as jobmod
    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    settings = Settings(path=tmp_path / "settings.json")
    win = MainWindow(settings)
    try:
        win.voice_male.setCurrentText("Giọng Edge")
        win.tts_provider.setCurrentIndex(win.tts_provider.findData("vieneu"))
        assert win.voice_male.currentText() == "Hải Đăng"
        win.voice_male.setCurrentText("Quang Sơn")
        win.tts_provider.setCurrentIndex(win.tts_provider.findData("edge"))
        assert win.voice_male.currentText() == "Giọng Edge"
        win.tts_provider.setCurrentIndex(win.tts_provider.findData("vieneu"))
        assert win.voice_male.currentText() == "Quang Sơn"

        settings.set("vieneu_backend", "onnx")
        settings.set("vieneu_precision", "fp32")
        source = tmp_path / "test.mp4"
        source.write_bytes(b"source-for-ui-test")
        job = win._configure_job(Job(), str(source))
        assert job.project.tts_provider == "vieneu"
        assert job.project.voice_male == "Quang Sơn"
        assert job.project.vieneu_backend == "onnx"
        assert job.project.vieneu_precision == "fp32"

        settings.set("vieneu_backend", "pytorch")
        settings.set("vieneu_precision", "int8")
        assert job.project.vieneu_backend == "onnx"
        assert job.project.vieneu_precision == "fp32"
    finally:
        win.close()


def test_settings_dialog_persists_vieneu_configuration(app, tmp_path):
    settings = Settings(path=tmp_path / "settings.json")
    dialog = SettingsDialog(settings)
    dialog.tts_provider.setCurrentIndex(dialog.tts_provider.findData("vieneu"))
    dialog.vieneu_voice_male.setText("Thiện Minh")
    dialog.vieneu_voice_female.setText("Trúc Ly")
    dialog.vieneu_backend.setCurrentIndex(dialog.vieneu_backend.findData("onnx"))
    dialog.vieneu_precision.setCurrentIndex(dialog.vieneu_precision.findData("fp32"))
    dialog.save()
    reloaded = Settings(path=tmp_path / "settings.json")
    assert reloaded.get("tts_provider") == "vieneu"
    assert reloaded.get("vieneu_voice_male") == "Thiện Minh"
    assert reloaded.get("vieneu_voice_female") == "Trúc Ly"
    assert reloaded.get("vieneu_backend") == "onnx"
    assert reloaded.get("vieneu_precision") == "fp32"
    dialog.close()


def test_voice_preview_uses_selected_provider_without_loading_model(
        app, tmp_path, monkeypatch):
    seen = {}
    class Stub:
        def synthesize(self, segs, out_dir):
            segs[0].audio_vi = str(tmp_path / "preview.wav")

    def fake_create(settings, **kwargs):
        seen.update(kwargs)
        return Stub()

    monkeypatch.setattr("tts.provider.create_tts", fake_create)
    worker = VoicePreviewWorker("Mai Anh", "female", tmp_path, "vieneu",
                                Settings(path=tmp_path / "s.json"))
    done = []
    worker.done.connect(done.append)
    worker.run()
    assert seen["provider"] == "vieneu"
    assert seen["voice_female"] == "Mai Anh"
    assert done == [str(tmp_path / "preview.wav")]


def test_multilingual_language_selection_survives_combined_vieneu_visual_job(
        app, tmp_path, monkeypatch):
    """A displayed source-language choice must flow into the saved job.

    This protects against integration merges silently dropping the UI to
    Project.src_lang assignment while TTS/visual controls remain visible.
    """
    import core.job as jobmod
    from project import io as pio
    from media.visual_source_identity import file_sha256

    monkeypatch.setattr(jobmod, "JOBS_ROOT", tmp_path / "jobs")
    settings = Settings(path=tmp_path / "settings.json")
    settings.set("visual_cleanup_enabled", True)
    settings.set("visual_cleanup_backend", "cv")
    source = tmp_path / "japanese-video.mp4"
    source.write_bytes(b"source-identity-for-ui-regression")
    win = MainWindow(settings)
    try:
        lang_idx = win.source_lang.findData("ja")
        assert lang_idx >= 0
        win.source_lang.setCurrentIndex(lang_idx)

        tts_idx = win.tts_provider.findData("vieneu")
        assert tts_idx >= 0
        win.tts_provider.setCurrentIndex(tts_idx)

        job = win._configure_job(Job(), str(source))
        saved = pio.load_project(job.job_dir)
        assert job.project.src_lang == "ja"
        assert saved.src_lang == "ja"
        assert saved.detected_src_lang == "und"
        assert saved.tts_provider == "vieneu"
        assert saved.visual_cleanup_options["visual_cleanup_enabled"] is True
        assert (saved.visual_cleanup_options["visual_cleanup_source_sha256"]
                == file_sha256(source))
        assert settings.get("source_language") == "ja"

        # Editing the next job's UI selection cannot rewrite a saved job.
        win.source_lang.setCurrentIndex(win.source_lang.findData("en"))
        settings.set("visual_cleanup_enabled", False)
        assert pio.load_project(job.job_dir).src_lang == "ja"
        assert pio.load_project(job.job_dir).visual_cleanup_options[
            "visual_cleanup_enabled"] is True
    finally:
        win.close()
