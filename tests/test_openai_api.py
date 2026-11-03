from unittest import mock

import pytest

from translation.base import TranslateError
from translation.openai_api import OpenAITranslator


def _response(status, payload=None, body=""):
    r = mock.Mock()
    r.status_code = status
    r.text = body
    r.json.return_value = payload or {}
    return r


def test_chat_sends_messages_and_reads_response():
    tr = OpenAITranslator(api_key="secret", model="gpt-4.1")
    response = _response(200, {"choices": [{"message": {"content": "你好"}}]})
    with mock.patch("requests.post", return_value=response) as post:
        assert tr._chat("system prompt", "user prompt") == "你好"
    args, kwargs = post.call_args
    assert args[0] == "https://api.openai.com/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["json"]["model"] == "gpt-4.1"
    assert kwargs["json"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_missing_key_fails_before_request():
    tr = OpenAITranslator(api_key="")
    with mock.patch("requests.post") as post, pytest.raises(
            TranslateError, match="OpenAI API key"):
        tr._chat("sys", "user")
    post.assert_not_called()


def test_auth_error_is_not_retried():
    tr = OpenAITranslator(api_key="wrong")
    response = _response(401, body='{"error":"invalid key"}')
    with mock.patch("requests.post", return_value=response) as post:
        with pytest.raises(TranslateError, match="HTTP 401"):
            tr._chat("sys", "user")
    post.assert_called_once()
