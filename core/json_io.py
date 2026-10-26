"""Small helpers for durable JSON metadata writes."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via a temporary sibling and atomically replace ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2,
                      allow_nan=False)
            stream.write("\n")
        temporary.replace(path)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def quarantine_file(path: Path) -> Path:
    """Preserve a bad JSON file at an exclusive ``.corrupt`` sibling.

    The source is left in place. Linking the temporary copy creates the
    destination only when no file or symlink already occupies its name.
    """
    path = Path(path)
    corrupt = path.with_name(path.name + ".corrupt")
    fd, name = tempfile.mkstemp(prefix=f".{corrupt.name}.", suffix=".tmp",
                                dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as destination, path.open("rb") as source:
            shutil.copyfileobj(source, destination)
        os.link(temporary, corrupt, follow_symlinks=False)
        return corrupt
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
