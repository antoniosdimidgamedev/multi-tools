"""Thin, testable wrapper around python-libtorrent (the `libtorrent` module).

Design notes
------------
* libtorrent-rasterbar is the reputable, actively-maintained BitTorrent
  engine used by qBittorrent/Deluge. We drive its C++ session from a single
  background poll thread so the Qt UI never blocks.
* Privacy-safe defaults: DHT and local peer discovery are OFF unless the
  user enables them; upload slots limited. DeskHub never searches for or
  indexes content — it only downloads what the user explicitly adds.
* Torrent handles are looked up by info-hash string via get_torrents(),
  because this binding has no find_torrent().
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import libtorrent as lt

from deskhub.logging_setup import get_logger
from deskhub.util import parse_magnet, sanitize_display_name

log = get_logger("downloads.engine")


@dataclass
class TorrentInfo:
    """UI-facing snapshot of one download."""
    handle_key: str
    name: str
    total_want: int = 0
    total_done: int = 0
    progress: float = 0.0          # 0..1
    download_rate: float = 0.0     # B/s
    upload_rate: float = 0.0       # B/s
    state: str = "queued"          # downloading|paused|seeding|checking|error|metadata|unknown
    error: str = ""
    peers: int = 0
    seeds: int = 0
    save_path: str = ""
    done: bool = False


def _key(h) -> str:
    try:
        return str(h.info_hash())          # hex string in these bindings
    except Exception:
        return str(h.id())


def _state_name(st) -> str:
    if getattr(st, "paused", False):
        return "paused"
    err = getattr(st, "errc", None)
    if err is not None:
        msg = str(err)
        low = msg.lower()
        if msg and "success" not in low and "no error" not in low and low != "none":
            return "error"
    if st.state == lt.torrent_status.downloading_metadata:
        return "metadata"
    if st.state in (lt.torrent_status.checking_files,
                    lt.torrent_status.checking_resume_data):
        return "checking"
    if st.state == lt.torrent_status.seeding:
        return "seeding"
    if st.state == lt.torrent_status.downloading:
        return "downloading"
    return "unknown"


class TorrentEngine:
    """Owns the libtorrent session; status polled from a daemon thread."""

    def __init__(self, download_dir: str | Path, *, enable_dht: bool = False,
                 max_uploads: int = 8, poll_interval: float = 1.0):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._poll_interval = poll_interval

        params = lt.session_params()
        sp = params.settings
        sp["save_path"] = str(self.download_dir)
        sp["disable_lsd"] = True
        sp["active_uploads"] = max_uploads
        sp["connections_limit"] = 120
        sp["user_agent"] = "DeskHub"
        try:
            sp["dht_mode"] = "dht_enabled" if enable_dht else "dht_disabled"
        except Exception:
            pass  # very old/new bindings may name this differently
        self._session = lt.session(params)

        self._lock = threading.Lock()
        self._infos: dict[str, TorrentInfo] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True,
                                        name="lt-poll")
        self._thread.start()
        log.info("engine started dht=%s", enable_dht)

    # ---- public API -----------------------------------------------------
    def add_magnet(self, url: str) -> str:
        parsed = parse_magnet(url)  # raises ValueError on bad input
        atp = lt.parse_magnet_uri(url)
        atp.save_path = str(self.download_dir)
        h = self._session.add_torrent(atp)
        key = _key(h)
        name = sanitize_display_name(parsed["display_name"],
                                     fallback=parsed["info_hash"][:12])
        with self._lock:
            self._infos[key] = TorrentInfo(handle_key=key, name=name,
                                           save_path=str(self.download_dir))
        log.info("added magnet (%d-char url)", len(url))
        return key

    def add_torrent_file(self, path: str | Path) -> str:
        p = Path(str(path))
        if p.suffix.lower() != ".torrent":
            raise ValueError("File must be a .torrent file.")
        if not p.is_file():
            raise ValueError("That .torrent file does not exist.")
        size = p.stat().st_size
        if size == 0 or size > 50 * 1024 * 1024:
            raise ValueError("Invalid .torrent file size.")
        try:
            ti = lt.torrent_info(str(p))
        except Exception as exc:
            raise ValueError(
                f"Could not parse torrent file: {type(exc).__name__}") from exc
        at = lt.add_torrent_params()
        at.ti = ti
        at.save_path = str(self.download_dir)
        h = self._session.add_torrent(at)
        key = _key(h)
        with self._lock:
            self._infos[key] = TorrentInfo(
                handle_key=key,
                name=sanitize_display_name(ti.name(), fallback="torrent"),
                total_want=ti.total_wanted(),
                save_path=str(self.download_dir))
        log.info("added torrent file (%d bytes meta)", size)
        return key

    def pause(self, key: str) -> None:
        h = self._handle(key)
        if h:
            h.pause()

    def resume(self, key: str) -> None:
        h = self._handle(key)
        if h:
            h.resume()

    def cancel(self, key: str, delete_files: bool = False) -> None:
        h = self._handle(key)
        if h:
            try:
                self._session.remove_torrent(
                    h, lt.options_t.delete_files if delete_files
                    else lt.options_t.none)
            except (AttributeError, TypeError):
                self._session.remove_torrent(h, 2 if delete_files else 0)
        with self._lock:
            self._infos.pop(key, None)

    def snapshots(self) -> list[TorrentInfo]:
        with self._lock:
            return [TorrentInfo(**vars(i)) for i in self._infos.values()]

    def shutdown(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=3)
        finally:
            try:
                self._session.close()
            except Exception:
                pass
        log.info("engine stopped")

    # ---- internals ------------------------------------------------------
    def _handle(self, key: str):
        for h in self._session.get_torrents():
            if _key(h) == key:
                return h
        return None

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._update_once()
            except Exception as exc:  # keep loop alive; log category only
                log.warning("poll error: %s", type(exc).__name__)
            self._stop.wait(self._poll_interval)

    def _update_once(self) -> None:
        for h in self._session.get_torrents():
            key = _key(h)
            st = h.status()
            state = _state_name(st)
            with self._lock:
                info = self._infos.get(key)
                if info is None:
                    info = TorrentInfo(
                        handle_key=key,
                        name=sanitize_display_name(st.name, key[:12]),
                        save_path=str(self.download_dir))
                    self._infos[key] = info
                info.name = sanitize_display_name(st.name, info.name)
                info.total_want = st.total_wanted
                info.total_done = st.total_done
                info.progress = float(st.progress)
                info.download_rate = float(st.download_rate)
                info.upload_rate = float(st.upload_rate)
                info.peers = st.num_peers
                try:
                    info.seeds = st.num_seeds
                except Exception:
                    pass
                info.state = state
                info.error = str(st.errc) if state == "error" else ""
                info.done = st.state == lt.torrent_status.seeding
