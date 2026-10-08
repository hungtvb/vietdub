# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Client pattern adapted from pyVideoTrans
# (https://github.com/jianchang512/pyvideotrans) by jianchang512, GPL-3.0:
#   - translator/_openaicompat.py (OpenAI-compatible chat API, retry on
#     5xx/timeout, no-retry on 4xx auth errors)
"""9Router provider (default): OpenAI-compatible endpoint, model
mimo-v2.6-flash-free. Tested 2026-10-08: best free model for zh->vi
pronouns (您->ngai, boss->em/anh).

Calling method replicates exactly the tested bypass in
pyvideotrans-demo/test_9router_free.py: headers
(User-Agent: opencode/1.18.31, x-opencode-client: desktop,
x-opencode-session: <fresh per request>), stream: true, decoy tools +
tool_choice "none", SSE parsing. No API key needed for the free tier;
a key can be set in Settings (sent as Bearer) for users who have one.

Edge case 15: 503/timeout -> retry 3x with backoff -> caller falls
back to Ollama, then Google free (with quality warning).
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import List

from translation.base import BaseTranslator, TranslateError

log = logging.getLogger("vietdub.translate.9router")

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _gen_session() -> str:
    # same fingerprint scheme as the tested 9Router bypass script
    ts = int(time.time() * 1000)
    cur = ts * 0x1000 + 1
    val = ~cur & ((1 << 48) - 1)
    timehex = "".join(f"{(val >> (40 - 8 * i)) & 0xFF:02x}" for i in range(6))
    return "ses_" + timehex + "".join(secrets.choice(BASE62) for _ in range(14))


def _decoy_tools():
    # fingerprint tools required by the free-tier bypass (must not be used)
    def decoy(n):
        return {"type": "function",
                "function": {"name": n,
                             "description": "This tool is currently unavailable "
                                            "and must not be used.",
                             "parameters": {"type": "object",
                                            "properties": {}}}}
    return [decoy(n) for n in ("bash", "glob", "grep", "read")]


# errors that must NOT be retried (auth / bad request / not found)
NO_RETRY_STATUS = {400, 401, 403, 404}


class NineRouterTranslator(BaseTranslator):
    name = "9router"

    def __init__(self, api_key: str = "",
                 base_url: str = "https://opencode.ai/zen/v1",
                 model: str = "mimo-v2.6-flash-free",
                 temperature: float = 0.2, batch_size: int = 20,
                 proper_nouns: List[str] | None = None,
                 timeout: int = 120, max_retries: int = 3):
        super().__init__(temperature=temperature, batch_size=batch_size,
                         proper_nouns=proper_nouns)
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def _headers(self) -> dict:
        h = {"User-Agent": "opencode/1.18.31",
             "x-opencode-client": "desktop",
             "x-opencode-session": _gen_session(),
             "Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _chat(self, system: str, user: str) -> str:
        import requests
        url = f"{self.base_url}/chat/completions"
        body = {"model": self.model, "stream": True,
                "tools": _decoy_tools(), "tool_choice": "none",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": self.temperature,
                "max_tokens": 4096}
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = requests.post(url, headers=self._headers(), json=body,
                                  timeout=self.timeout, stream=True)
                if r.status_code in NO_RETRY_STATUS:
                    raise TranslateError(
                        _auth_message(r.status_code, r.text[:200]))
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}: "
                                       f"{r.text[:200]}")
                out = []
                for line in r.iter_lines():
                    if not line.startswith(b"data: "):
                        continue
                    d = line[6:]
                    if d.strip() == b"[DONE]":
                        break
                    try:
                        out.append(json.loads(d)["choices"][0]
                                   .get("delta", {}).get("content", ""))
                    except (json.JSONDecodeError, KeyError, IndexError,
                            TypeError):
                        continue
                text = "".join(out).strip()
                if not text:
                    raise RuntimeError("LLM trả về rỗng")
                return text
            except TranslateError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("9Router attempt %d/%d lỗi: %s",
                            attempt + 1, self.max_retries, str(e)[:200])
                if attempt < self.max_retries - 1:
                    time.sleep(2 * (attempt + 1))
        raise TranslateError(
            "9Router không phản hồi (timeout/503) sau "
            f"{self.max_retries} lần thử.\n"
            "Cách khắc phục: kiểm tra mạng, thử lại sau ít phút, hoặc "
            "chuyển nguồn dịch sang Ollama trong Cài đặt.") from last_err


def _auth_message(status, detail) -> str:
    if status == 401:
        return ("API key 9Router sai hoặc hết hạn (401).\n"
                "Cách khắc phục: kiểm tra lại API key trong Cài đặt, "
                "hoặc bỏ trống để dùng free tier.")
    if status == 403:
        return ("9Router từ chối truy cập (403).\n"
                "Cách khắc phục: kiểm tra tài khoản/quota 9Router.")
    if status == 404:
        return ("Không tìm thấy model trên 9Router (404).\n"
                "Cách khắc phục: kiểm tra tên model trong Cài đặt.")
    return (f"9Router báo lỗi {status}: {detail}\n"
            "Cách khắc phục: kiểm tra Cài đặt nguồn dịch.")
