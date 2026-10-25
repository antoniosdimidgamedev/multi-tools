"""JSON settings stored under %APPDATA%\\DeskHub (or platform equivalent).

Keeps only non-sensitive preferences. Never stores user document contents,
chat prompts, or downloaded file names beyond what a session needs live.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def appdata_dir() -> Path:
    """Per-user app data folder for DeskHub (created if missing)."""
    base = os.environ.get("DESKHUB_DATA_DIR")  # used by tests
    if base:
        root = Path(base)
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home()))) / "DeskHub"
    else:  # dev/CI fallback (Linux/macOS)
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "DeskHub"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_download_dir() -> Path:
    dl = Path.home() / "Downloads" / "DeskHub"
    try:
        dl.mkdir(parents=True, exist_ok=True)
    except OSError:
        dl = appdata_dir() / "downloads"
        dl.mkdir(parents=True, exist_ok=True)
    return dl


DEFAULTS: dict = {
    "download_dir": None,          # filled lazily with default_download_dir()
    "seed_limit": 0,               # 0 = no upload limit is NOT safe; we set below
    "max_uploads": 8,
    "enable_dht": False,           # privacy-safe default: don't expose node unless needed
    "enable_lsd": False,
    "ai_model_dir": None,
    "ai_last_model": None,
    "theme_accent": "#0078D4",
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or (appdata_dir() / "settings.json")
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data.update({k: v for k, v in raw.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError):
            # Corrupt settings should not crash the app; start from defaults.
            pass

    def save(self) -> None:
        # Atomic write so a crash can't leave a half-written JSON file.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def get(self, key: str, default=None):
        v = self._data.get(key, default)
        if key == "download_dir" and not v:
            v = str(default_download_dir())
        return v

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()
