"""OpenAI API provider used for speaker analysis and translation."""
from __future__ import annotations

import logging
import time
from typing import List

from translation.base import BaseTranslator, TranslateError

log = logging.getLogger("vietdub.translate.openai")

_NO_RETRY_STATUS = {400, 401, 403, 404, 422}


class OpenAITranslator(BaseTranslator):
    """Chat Completions provider for OpenAI models such as gpt-4.1."""

    name = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4.1", temperature: float = 0.2,
                 batch_size: int = 20, proper_nouns: List[str] | None = None,
                 timeout: int = 120, max_retries: int = 3):
        super().__init__(temperature=temperature, batch_size=batch_size,
                         proper_nouns=proper_nouns)
        self.api_key = (api_key or "").strip()
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = (model or "gpt-4.1").strip()
        self.timeout = timeout
        self.max_retries = max_retries

    def _chat(self, system: str, user: str) -> str:
        import requests

        if not self.api_key:
            raise TranslateError(
                "Chưa nhập OpenAI API key. Mở Cài đặt → Dịch thuật để nhập key.")

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": 4096,
        }
        if self.base_url == "https://api.openai.com/v1":
            body["response_format"] = {"type": "json_object"}
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(url, headers=headers, json=body,
                                         timeout=self.timeout)
                if response.status_code in _NO_RETRY_STATUS:
                    detail = response.text[:300]
                    raise TranslateError(
                        f"OpenAI API trả HTTP {response.status_code}: {detail}")
                if response.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {response.status_code}: {response.text[:300]}")
                data = response.json()
                content = (data["choices"][0]["message"].get("content") or "")
                if isinstance(content, list):
                    content = "".join(
                        part.get("text", "") for part in content
                        if isinstance(part, dict))
                text = str(content).strip()
                if not text:
                    raise RuntimeError("OpenAI API trả về nội dung rỗng")
                return text
            except TranslateError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("OpenAI attempt %d/%d lỗi: %s",
                            attempt + 1, self.max_retries, str(e)[:200])
                if attempt + 1 < self.max_retries:
                    time.sleep(2 * (attempt + 1))

        raise TranslateError(
            f"OpenAI API không phản hồi sau {self.max_retries} lần thử: "
            f"{last_err}") from last_err
