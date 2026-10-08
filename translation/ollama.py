# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
#
# Adapted from pyVideoTrans (https://github.com/jianchang512/pyvideotrans)
# by jianchang512, GPL-3.0: translator/_localllm.py (Ollama-compatible
# subclass of the OpenAI-compatible client).
"""Ollama provider (local LLM). Same prompts as 9Router; quality depends on
the model the user pulled.

Edge case 14: Ollama not running / model not pulled -> health check
/api/tags first, clear message with the `ollama pull` fix.
"""
from __future__ import annotations

import logging
import time
from typing import List

from translation.base import (BaseTranslator, TranslateError,
                              google_translate_free)
from translation import prompts

# re-exported from translation.base (kept here so existing imports keep working)
__all__ = ["OllamaTranslator", "google_translate_free"]

log = logging.getLogger("vietdub.translate.ollama")


class OllamaTranslator(BaseTranslator):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "", temperature: float = 0.2,
                 batch_size: int = 20, proper_nouns: List[str] | None = None,
                 timeout: int = 300, max_retries: int = 2):
        super().__init__(temperature=temperature, batch_size=batch_size,
                         proper_nouns=proper_nouns)
        if not model:
            raise TranslateError(
                "Chưa chọn model Ollama.\n"
                "Cách khắc phục: mở Cài đặt -> nhập tên model Ollama "
                "(vd qwen2.5:7b) rồi chạy lại.")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = None

    def health_check(self) -> None:
        """Edge case 14: fail fast with a helpful message."""
        import requests
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as e:  # noqa: BLE001
            raise TranslateError(
                "Không kết nối được Ollama.\n"
                f"Cách khắc phục: chạy 'ollama serve', rồi 'ollama pull {self.model}'. "
                f"Chi tiết: {e}") from e
        if not any(self.model in m or m in self.model for m in models):
            raise TranslateError(
                f"Ollama chưa có model '{self.model}'.\n"
                f"Cách khắc phục: chạy 'ollama pull {self.model}' rồi thử lại.")

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise TranslateError(
                    "Chưa cài thư viện openai.\n"
                    "Cách khắc phục: pip install openai") from e
            self.health_check()
            self._client = OpenAI(api_key="ollama",
                                  base_url=f"{self.base_url}/v1",
                                  timeout=self.timeout)
        return self._client

    def _chat(self, system: str, user: str) -> str:
        client = self._get_client()
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=self.temperature,
                )
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise RuntimeError("LLM trả về rỗng")
                return text
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("Ollama attempt %d/%d lỗi: %s",
                            attempt + 1, self.max_retries, str(e)[:200])
                if attempt < self.max_retries - 1:
                    time.sleep(3)
        raise TranslateError(
            f"Ollama lỗi sau {self.max_retries} lần thử: {last_err}\n"
            "Cách khắc phục: kiểm tra 'ollama serve' còn chạy không.") from last_err
