"""Stable content identity for operator-approved video cleanup plans.

A path and matching dimensions do not prove that the source video is unchanged.
Hash the complete file in bounded chunks; never keep video bytes in memory.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: str | Path) -> str:
    source = Path(path)
    h = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
