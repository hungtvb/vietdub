# Edge case 15: 9Router 503/timeout -> retry 3x -> clear message.
# Auth errors (401/403/404) -> no retry, Vietnamese fix hint.
# Calling method mirrors test_9router_free.py (bypass headers, stream SSE).
import json
from unittest import mock

import pytest

from translation.base import TranslateError
from translation.nine_router import NineRouterTranslator, _gen_session


def _sse_resp(text):
    """Fake requests.Response yielding one SSE data line."""
    chunk = {"choices": [{"delta": {"content": text}}]}
    lines = [b"data: " + json.dumps(chunk).encode(), b"data: [DONE]"]
    r = mock.Mock()
    r.status_code = 200
    r.iter_lines.return_value = iter(lines)
    return r


def test_chat_ok_and_headers():
    tr = NineRouterTranslator()
    with mock.patch("requests.post", return_value=_sse_resp("你好")) as p:
        assert tr._chat("sys", "user") == "你好"
    _, kwargs = p.call_args
    h = kwargs["headers"]
    assert h["User-Agent"] == "opencode/1.18.31"
    assert h["x-opencode-client"] == "desktop"
    assert h["x-opencode-session"].startswith("ses_")
    body = kwargs["json"]
    assert body["stream"] is True
    assert body["tool_choice"] == "none"
    assert len(body["tools"]) == 4  # decoy fingerprint tools


def test_session_fresh_each_call():
    assert _gen_session() != _gen_session()


def test_503_retries_three_times_then_raises():
    tr = NineRouterTranslator(max_retries=3)
    bad = mock.Mock()
    bad.status_code = 503
    bad.text = "Service Unavailable"
    with mock.patch("requests.post", return_value=bad) as p, \
         mock.patch("translation.nine_router.time.sleep"):
        with pytest.raises(TranslateError) as e:
            tr._chat("sys", "user")
    assert p.call_count == 3
    assert "9Router không phản hồi" in str(e.value)


def test_401_no_retry_vietnamese():
    tr = NineRouterTranslator()
    bad = mock.Mock()
    bad.status_code = 401
    bad.text = "unauthorized"
    with mock.patch("requests.post", return_value=bad) as p:
        with pytest.raises(TranslateError) as e:
            tr._chat("sys", "user")
    assert p.call_count == 1
    assert "API key" in str(e.value)


def test_timeout_retried():
    tr = NineRouterTranslator(max_retries=2)
    import requests
    with mock.patch("requests.post",
                    side_effect=requests.Timeout("t")) as p, \
         mock.patch("translation.nine_router.time.sleep"):
        with pytest.raises(TranslateError):
            tr._chat("sys", "user")
    assert p.call_count == 2


def test_api_key_sent_as_bearer_when_set():
    tr = NineRouterTranslator(api_key="k123")
    with mock.patch("requests.post", return_value=_sse_resp("ok")) as p:
        tr._chat("sys", "user")
    assert p.call_args[1]["headers"]["Authorization"] == "Bearer k123"


def test_empty_llm_output_retried():
    tr = NineRouterTranslator(max_retries=2)
    with mock.patch("requests.post",
                    side_effect=[_sse_resp(""), _sse_resp("ok")]) as p, \
         mock.patch("translation.nine_router.time.sleep"):
        assert tr._chat("sys", "user") == "ok"
    assert p.call_count == 2


def _sse_multi_resp(*contents):
    """Fake SSE response with several content chunks (None allowed)."""
    lines = [b"data: " + json.dumps(
        {"choices": [{"delta": {"content": c}}]}).encode()
        for c in contents]
    lines.append(b"data: [DONE]")
    r = mock.Mock()
    r.status_code = 200
    r.iter_lines.return_value = iter(lines)
    return r


def test_null_content_chunk_does_not_crash_join():
    # SSE thỉnh thoảng có chunk content=null -> trước đây "".join() văng
    # TypeError (tốn 1 retry); giờ coi như "".
    tr = NineRouterTranslator()
    with mock.patch("requests.post",
                    return_value=_sse_multi_resp(None, "xin ", None, "chào")):
        assert tr._chat("sys", "user") == "xin chào"


def test_all_null_content_counts_as_empty():
    tr = NineRouterTranslator(max_retries=1)
    with mock.patch("requests.post",
                    return_value=_sse_multi_resp(None, None)), \
         mock.patch("translation.nine_router.time.sleep"):
        with pytest.raises(TranslateError) as e:
            tr._chat("sys", "user")
    assert "9Router không phản hồi" in str(e.value)
