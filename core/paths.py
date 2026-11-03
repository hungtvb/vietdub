"""Platform-specific paths used by VietDub."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def user_data_dir() -> Path:
    """Return VietDub's per-user data directory without creating it."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "VietDub"
        return Path.home() / "AppData" / "Local" / "VietDub"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VietDub"

    root = os.environ.get("XDG_DATA_HOME")
    if root:
        return Path(root) / "VietDub"
    return Path.home() / ".local" / "share" / "VietDub"
