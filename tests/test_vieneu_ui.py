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
