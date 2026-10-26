"""Contract tests for standalone VietDub STT service adapter (no model downloads)."""
from types import SimpleNamespace

import pytest

from asr.funasr_adapter import ASRError
from asr.vietdub_stt_adapter import VietDubSTTAdapter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeDiarizer:
    def __init__(self, turns):
        self.turns = turns

    def transcribe(self, path):
        return self.turns


def payload(speaker_id=None):
    return {
        "schema_version": "1.0",
        "status": "complete",
        "segments": [
            {"start": 0.5, "end": 1.5, "text": "你好。", "speaker_id": speaker_id},
            {"start": 2.0, "end": 3.0, "text": "再见。", "speaker_id": speaker_id},
        ],
    }


@pytest.fixture
def source(monkeypatch, tmp_path):
    path = tmp_path / "test.wav"
    path.write_bytes(b"fake wav fixture")
    monkeypatch.setattr("asr.vietdub_stt_adapter._wav_duration_sec", lambda p: 5.0)
    return path


def stub_response(monkeypatch, data):
    def fake_post(url, files, data, timeout):
        assert url == "http://127.0.0.1:8768/v1/transcribe"
        assert files["file"][1].read(4) == b"fake"
        assert timeout[0] == 5
        return FakeResponse(data)
    monkeypatch.setattr("asr.vietdub_stt_adapter.requests.post", fake_post)


def test_optional_adapter_keeps_unknown_speakers_for_review(monkeypatch, source):
    stub_response(monkeypatch, payload())
    out = VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)
    assert [x.text_src for x in out] == ["你好。", "再见。"]
    assert [x.speaker for x in out] == [0, 0]
    assert all(x.needs_review for x in out)


def test_diarizer_assigns_only_supported_speaker_turns(monkeypatch, source):
    stub_response(monkeypatch, payload())
    turns = [SimpleNamespace(start=0.3, end=1.6, speaker=2),
             SimpleNamespace(start=2.0, end=2.3, speaker=3)]
    out = VietDubSTTAdapter(
        stt_url="http://127.0.0.1:8768", diarizer=FakeDiarizer(turns)).transcribe(source)
    assert out[0].speaker == 2 and not out[0].needs_review
    assert out[1].speaker == 0 and out[1].needs_review


def test_invalid_timestamp_causes_failure(monkeypatch, source):
    doc = payload()
    doc["segments"][0]["end"] = 500.0
    stub_response(monkeypatch, doc)
    with pytest.raises(ASRError, match="timestamp"):
        VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)


def test_unsupported_schema_rejected(monkeypatch, source):
    doc = payload()
    doc["schema_version"] = "2.0"
    stub_response(monkeypatch, doc)
    with pytest.raises(ASRError, match="schema"):
        VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)


def test_localhost_only_blocks_remote():
    with pytest.raises(ValueError, match="localhost"):
        VietDubSTTAdapter(stt_url="https://remote.example/api")
