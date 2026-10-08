# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Per-job file logging: every job writes jobs/<job_id>/run.log.

Overnight runs are unattended, so the morning-after review happens by
reading this file. Both the logging module and an optional UI callback
receive each line."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable, Optional


def setup_job_logger(job_id: str, job_dir: Path,
                     log_cb: Optional[Callable[[str], None]] = None) -> logging.Logger:
    logger = logging.getLogger(f"vietdub.job.{job_id}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(Path(job_dir) / "run.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

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
        logger.addHandler(ch)

    return logger
