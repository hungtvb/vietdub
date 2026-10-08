# Edge case 14: Ollama down / model missing -> clear message + ollama pull hint.
from unittest import mock

import pytest
import requests

from translation.base import TranslateError
from translation.ollama import OllamaTranslator, google_translate_free


def _tr():
    return OllamaTranslator(model="qwen2.5:7b", max_retries=1)


def test_ollama_down_clear_message():
    tr = _tr()
    with mock.patch("requests.get", side_effect=requests.ConnectionError("refused")):
        with pytest.raises(TranslateError) as e:
            tr.health_check()
    assert "ollama serve" in str(e.value)
    assert "ollama pull qwen2.5:7b" in str(e.value)


def test_ollama_model_missing_hint():
    tr = _tr()
    fake_r = mock.Mock()
    fake_r.json.return_value = {"models": [{"name": "llama3:8b"}]}
    fake_r.raise_for_status.return_value = None
    with mock.patch("requests.get", return_value=fake_r):
        with pytest.raises(TranslateError) as e:
            tr.health_check()
    assert "ollama pull qwen2.5:7b" in str(e.value)


def test_ollama_model_present_ok():
    tr = _tr()
    fake_r = mock.Mock()
    fake_r.json.return_value = {"models": [{"name": "qwen2.5:7b"}]}
    fake_r.raise_for_status.return_value = None
    with mock.patch("requests.get", return_value=fake_r):
        tr.health_check()  # no raise


def test_missing_model_config():
    with pytest.raises(TranslateError) as e:
        OllamaTranslator(model="")
    assert "model Ollama" in str(e.value)


def test_google_free_fallback_keeps_source_on_error():
    with mock.patch("requests.get", side_effect=Exception("429")):
        out = google_translate_free(["你好"])
    assert out == ["你好"]  # never drops the line
