# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Route feature-module logs to the job running in the current thread/task."""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Callable, Optional


_current_job: ContextVar[str | None] = ContextVar("vietdub_job_id", default=None)
_job_handlers: dict[str, list[logging.Handler]] = {}
_lock = RLock()
_namespace_state: tuple[int, bool] | None = None


def activate_job_logger(job_id: str) -> None:
    """Select the job for logs emitted by feature modules in this task."""
    _current_job.set(job_id)


def _belongs_to(job_id: str, record: logging.LogRecord) -> bool:
    if record.name.startswith("vietdub.job."):
        return record.name == f"vietdub.job.{job_id}" or record.name.startswith(
            f"vietdub.job.{job_id}.")
    return _current_job.get() == job_id


def setup_job_logger(job_id: str, job_dir: Path,
                     log_cb: Optional[Callable[[str], None]] = None) -> logging.Logger:
    # Module loggers (vietdub.tts, vietdub.translate, ...) share this parent.
    # Each handler filters by current job so concurrent jobs stay separate.
    global _namespace_state
    namespace = logging.getLogger("vietdub")
    logger = logging.getLogger(f"vietdub.job.{job_id}")
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(Path(job_dir) / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    handlers: list[logging.Handler] = [fh, sh]

    if log_cb is not None:
        class _CbHandler(logging.Handler):
            def emit(self, record):
                try:
                    log_cb(self.format(record))
                except Exception:
                    pass
        ch = _CbHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        handlers.append(ch)

    with _lock:
        if job_id in _job_handlers:
            _remove_job_handlers(namespace, job_id)
        if _namespace_state is None:
            _namespace_state = (namespace.level, namespace.propagate)
        namespace.setLevel(logging.DEBUG)
        namespace.propagate = False
        logger.setLevel(logging.DEBUG)
        logger.propagate = True
        for handler in handlers:
            handler.addFilter(lambda record, jid=job_id: _belongs_to(jid, record))
            namespace.addHandler(handler)
        _job_handlers[job_id] = handlers
    activate_job_logger(job_id)
    return logger


def close_job_logger(job_id: str) -> None:
    """Close only this job's handlers and restore namespace when idle."""
    global _namespace_state
    namespace = logging.getLogger("vietdub")
    with _lock:
        _remove_job_handlers(namespace, job_id)
        if not _job_handlers and _namespace_state is not None:
            namespace.setLevel(_namespace_state[0])
            namespace.propagate = _namespace_state[1]
            _namespace_state = None
    if _current_job.get() == job_id:
        _current_job.set(None)


def _remove_job_handlers(namespace: logging.Logger, job_id: str) -> None:
    for handler in _job_handlers.pop(job_id, []):
        namespace.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001 - logging cleanup is best effort
            pass
