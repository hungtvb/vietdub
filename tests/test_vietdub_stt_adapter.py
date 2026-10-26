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
            {"start": 0.5, "end": 1.5, "text": "你好。", "speaker_id": speaker_id,
             "confidence": 0.92},
            {"start": 2.0, "end": 3.0, "text": "再见。", "speaker_id": speaker_id,
             "confidence": 0.85},
        ],
    }


@pytest.fixture
def source(monkeypatch, tmp_path):
    path = tmp_path / "test.wav"
    path.write_bytes(b"fake wav fixture")
    monkeypatch.setattr("asr.vietdub_stt_adapter._wav_duration_sec", lambda p: 5.0)
    return path


def stub_response(monkeypatch, expected_payload):
    def fake_post(session, url, data, headers, timeout):
        assert url == "http://127.0.0.1:8768/v1/transcribe"
        assert session.trust_env is False
        assert data.fields["file"][1].read(4) == b"fake"
        assert headers["Content-Type"].startswith("multipart/form-data;")
        assert timeout[0] == 5
        return FakeResponse(expected_payload)
    monkeypatch.setattr("asr.vietdub_stt_adapter.requests.Session.post", fake_post)


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


def test_missing_confidence_forces_review(monkeypatch, source):
    doc = payload(speaker_id=1)
    for segment in doc["segments"]:
        segment["confidence"] = None
    stub_response(monkeypatch, doc)
    out = VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)
    assert all(s.confidence == 0.0 and s.needs_review for s in out)


def test_unknown_confidence_remains_review_after_diarization(monkeypatch, source):
    doc = payload()
    doc["segments"][0]["confidence"] = None
    stub_response(monkeypatch, doc)
    diarizer = FakeDiarizer([SimpleNamespace(start=0.0, end=4.0, speaker=3)])
    out = VietDubSTTAdapter(stt_url="http://127.0.0.1:8768",
                            diarizer=diarizer).transcribe(source)
    assert out[0].speaker == 3 and out[0].needs_review
    assert out[1].speaker == 3 and not out[1].needs_review


def test_no_speech_stops_dubbing_pipeline(monkeypatch, source):
    doc = {"schema_version": "1.0", "status": "no_speech", "segments": []}
    stub_response(monkeypatch, doc)
    with pytest.raises(ASRError, match="không phát hiện thoại"):
        VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)


def test_invalid_confidence_rejected(monkeypatch, source):
    doc = payload()
    doc["segments"][0]["confidence"] = 2.0
    stub_response(monkeypatch, doc)
    with pytest.raises(ASRError, match="confidence"):
        VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)


def test_upload_cap(monkeypatch, source):
    monkeypatch.setattr("asr.vietdub_stt_adapter.Path.stat",
                        lambda self: SimpleNamespace(st_size=513 * 1024 * 1024))
    with pytest.raises(ASRError, match="512 MiB"):
        VietDubSTTAdapter(stt_url="http://127.0.0.1:8768").transcribe(source)


def test_noun_limits_match_service():
    names = [f"name-{i}" for i in range(40)]
    adapter = VietDubSTTAdapter(stt_url="http://127.0.0.1:8768",
                                proper_nouns=names)
    assert len(adapter.proper_nouns) == 30
