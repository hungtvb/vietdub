"""Smoke test real HTTP transport between VietDub and local STT server.

No neural weights needed; this validates multipart upload, request options,
schema parsing and failure behavior over a real 127.0.0.1 TCP connection.
"""
from __future__ import annotations

import json
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from asr.funasr_adapter import ASRError
from asr.vietdub_stt_adapter import VietDubSTTAdapter


def create_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 32000)


def start_server(payload: dict):
    observed: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            observed.append({"path": self.path, "type": self.headers.get("Content-Type"),
                             "body": body, "length": length})
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, observed


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "spoken.wav"
    create_wav(path)
    # This transport-only smoke test uses stdlib wave instead of bringing the
    # full installed soundfile/FunASR inference stack into light CI.
    monkeypatch.setattr("asr.vietdub_stt_adapter._wav_duration_sec", lambda _: 2.0)
    return path


def test_real_loopback_upload_and_unknown_speaker(source):
    payload = {
        "schema_version": "1.0", "status": "complete",
        "segments": [{"start": 0.2, "end": 1.4, "text": "你好。", "speaker_id": None,
                      "confidence": None, "needs_review": False}],
    }
    server, thread, observed = start_server(payload)
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        output = VietDubSTTAdapter(stt_url=base, quality="fast",
                                   proper_nouns=["刘勇武"]).transcribe(source)
        assert len(output) == 1
        assert output[0].text_src == "你好。"
        assert output[0].needs_review is True
        assert output[0].confidence == 0.0
        assert observed[0]["path"] == "/v1/transcribe"
        assert observed[0]["type"].startswith("multipart/form-data;")
        assert b"RIFF" in observed[0]["body"]
        assert b"quality" in observed[0]["body"]
        assert b"fast" in observed[0]["body"]
        assert observed[0]["length"] > source.stat().st_size
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_real_loopback_no_speech_is_error(source):
    server, thread, _ = start_server({
        "schema_version": "1.0", "status": "no_speech", "segments": []})
    try:
        with pytest.raises(ASRError, match="không phát hiện thoại"):
            VietDubSTTAdapter(
                stt_url=f"http://127.0.0.1:{server.server_port}").transcribe(source)
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
