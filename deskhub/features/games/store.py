"""Local best-score store for games (JSON under appdata, no network)."""
from __future__ import annotations

import json
from pathlib import Path

from deskhub.settings import appdata_dir


class ScoreStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (appdata_dir() / "scores.json")
        self._data: dict[str, dict] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    def _flush(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except OSError:
            pass  # scores are non-critical; never crash a game over this

    def best(self, game: str, variant: str, key: str):
        return self._data.get(game, {}).get(variant, {}).get(key)

    def record(self, game: str, variant: str, **values) -> dict:
        """Merge values; keep minimum for keys starting 'best_' and maximum for 'wins'."""
        g = self._data.setdefault(game, {})
        v = g.setdefault(variant, {})
        for k, val in values.items():
            if k.startswith("best_"):
                cur = v.get(k)
                v[k] = val if cur is None else min(cur, val)
            elif k == "last":
                v[k] = val
            else:
                cur = v.get(k)
                v[k] = val if cur is None else max(cur, val)
        self._flush()
        return dict(v)
