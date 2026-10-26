# VietDub - Vietnamese dubbing for Chinese videos (PySide6 desktop app)
# Copyright (C) 2026 VietDub contributors
# License: GNU General Public License v3.0 (see LICENSE)
"""Choose unused export names and publish completed files without replacing them."""
from __future__ import annotations

import os
from pathlib import Path


def next_available_output_path(requested: str | Path,
                               paired_extensions: tuple[str, ...] = ()) -> Path:
    """Find a name whose main file and paired files are all unused.

    This only selects a name. The caller must use ``publish_no_replace`` to
    guard against another file appearing before publication.
    """
    requested = Path(requested)
    number = 1
    while True:
        candidate = (requested if number == 1 else
                     requested.with_name(f"{requested.stem}_{number}{requested.suffix}"))
        paths = (candidate, *(candidate.with_suffix(ext) for ext in paired_extensions))
        if all(not os.path.lexists(path) for path in paths):
            return candidate
        number += 1


def publish_no_replace(temp_path: Path, target_path: Path) -> Path:
    """Publish a completed temporary file on the same filesystem atomically.

    The hard link creation fails with ``FileExistsError`` if the destination
    already exists. Once linked, remove the temporary name; if that removal
    fails, remove only the destination this call created.
    """
    temp_path, target_path = Path(temp_path), Path(target_path)
    source_stat = temp_path.stat(follow_symlinks=False)
    os.link(temp_path, target_path)
    try:
        temp_path.unlink()
    except OSError:
        try:
            if os.path.samestat(source_stat,
                                target_path.stat(follow_symlinks=False)):
                target_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return target_path
