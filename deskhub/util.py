"""Path/input validation and safe file helpers shared by every feature.

All functions here are pure-python so they can be unit-tested headlessly.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

# Characters forbidden in Windows file names (plus control chars).
# NOTE: spaces are legal inside Windows file names ("my file 1.txt"), so they
# are intentionally NOT part of this class.
_INVALID_NAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED_WIN = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

SAFE_EXTENSIONS = {
    ".txt", ".md", ".docx", ".pdf",
    ".csv", ".xlsx",
    ".pptx",
    ".torrent", ".gguf",
}


def is_valid_filename(name: str) -> bool:
    """True if *name* is a legal, non-reserved Windows base file name."""
    if not name or name in (".", ".."):
        return False
    if len(name) > 255:
        return False
    if name.endswith(".") or name.endswith(" "):
        return False
    if _INVALID_NAME_CHARS.search(name):
        return False
    if name.split(".")[0].lower() in _RESERVED_WIN:
        return False
    return True


def validate_download_dir(path: str | os.PathLike) -> Path:
    """Validate a user-chosen download folder; create it if missing.

    Raises ValueError with a user-facing message on any problem.
    """
    raw = str(path or "").strip().strip('"')
    if not raw:
        raise ValueError("Download folder path is empty.")
    p = Path(raw)
    if not p.is_absolute():
        raise ValueError("Download folder must be an absolute path.")
    for part in p.parts:
        # Skip drive prefixes like 'C:\\' or '/' roots.
        if len(part) <= 3 and ":" in part:
            continue
        if part in ("/", "\\"):
            continue
        cleaned = part.rstrip("\\")
        if cleaned and not is_valid_filename(cleaned):
            raise ValueError(f"Invalid folder name in path: {part!r}")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Cannot create download folder: {exc}") from exc
    if not os.access(p, os.W_OK):
        raise ValueError("Download folder is not writable.")
    return p.resolve()


def safe_save_path(target: str | os.PathLike, allow_overwrite: bool = False) -> Path:
    """Return a validated save target, refusing silent overwrite.

    If *target* exists and allow_overwrite is False, suggest ``name (1).ext``.
    """
    t = Path(str(target))
    name = t.name
    if not is_valid_filename(name):
        raise ValueError(f"Not a valid file name: {name!r}")
    if t.suffix.lower() not in SAFE_EXTENSIONS:
        raise ValueError(
            f"Unsupported extension {t.suffix or '(none)'!r}. "
            "Allowed: " + ", ".join(sorted(SAFE_EXTENSIONS))
        )
    if t.exists() and not allow_overwrite:
        stem, ext = t.stem, t.suffix
        parent = t.parent
        n = 1
        while True:
            cand = parent / f"{stem} ({n}){ext}"
            if not cand.exists():
                return cand
            n += 1
    return t


def disk_free_bytes(path: str | os.PathLike) -> int:
    return shutil.disk_usage(str(path)).free


def human_size(n: float | None) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_rate(bytes_per_sec: float | None) -> str:
    if bytes_per_sec is None:
        return "—"
    return human_size(bytes_per_sec) + "/s"


MAGNET_RE = re.compile(
    r"^magnet:[^\s]*xt=urn:btih:(?P<hash>[0-9a-fA-F]{40}|[A-Za-z2-7]{32})(?![\w-])",
    re.IGNORECASE,
)


def parse_magnet(url: str) -> dict:
    """Lightly validate a magnet URI and extract info-hash / dn / trackers.

    Returns {"info_hash": hex40, "display_name": str|None, "trackers": [str]}.
    Raises ValueError for malformed input (never trusts the pasted string).
    """
    url = (url or "").strip()
    m = MAGNET_RE.match(url)
    if not m:
        raise ValueError(
            "That does not look like a valid magnet link. "
            "It must start with magnet:?…xt=urn:btih:<info-hash>"
        )
    h = m.group("hash")
    if len(h) == 32:  # base32-encoded
        try:
            info_hash = base64.b32decode(h.upper()).hex()
        except Exception as exc:
            raise ValueError("Magnet info-hash is not valid base32/hex.") from exc
    else:
        info_hash = h.lower()
    qs = url.split("?", 1)[1]
    display_name = None
    trackers: list[str] = []
    for pair in qs.split("&"):
        k, _, v = pair.partition("=")
        v = unquote(v.replace("+", " "))
        if k == "dn" and v:
            display_name = v[:200]
        elif k == "tr" and v:
            trackers.append(v[:500])
    if not re.fullmatch(r"[0-9a-f]{40}", info_hash):
        raise ValueError("Magnet info-hash could not be decoded to 40 hex characters.")
    return {"info_hash": info_hash, "display_name": display_name, "trackers": trackers}


def sanitize_display_name(name: str | None, fallback: str) -> str:
    """Make a torrent/magnet display name safe to show/store (no path traversal)."""
    if not name:
        return fallback
    name = os.path.basename(name.replace("\\", "/"))
    name = _INVALID_NAME_CHARS.sub("", name)
    # Collapse any run of whitespace so the name stays single-line and tidy.
    name = re.sub(r"\s+", " ", name).strip(" .")
    # A lone dot/dot-dot would be a path reference; drop it in favour of fallback.
    if name in (".", ".."):
        return fallback
    return (name[:120] or fallback)
