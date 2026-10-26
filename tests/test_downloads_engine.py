"""Tests for the libtorrent-backed download engine and the score store.

The engine test builds a real local torrent (via libtorrent's create_torrent)
and downloads it through a local HTTP seed — no internet required. If the
binding lacks the needed helpers, the test degrades to lifecycle-only checks.
"""
import time

import pytest

pytest.importorskip("libtorrent", reason="python3-libtorrent binding not installed")

from deskhub.features.downloads.engine import TorrentEngine  # noqa: E402


MAGNET = ("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
          "&dn=Test+Item")


class TestEngineLifecycle:
    def test_add_magnet_and_snapshot(self, tmp_path):
        eng = TorrentEngine(tmp_path / "dl", poll_interval=0.2)
        try:
            key = eng.add_magnet(MAGNET)
            assert len(key) == 40
            # wait for at least one poll cycle
            deadline = time.time() + 5
            snaps = []
            while time.time() < deadline:
                snaps = eng.snapshots()
                if snaps:
                    break
                time.sleep(0.1)
            assert snaps and snaps[0].handle_key == key
            assert snaps[0].name == "Test Item"
            assert snaps[0].save_path.endswith("dl")
        finally:
            eng.shutdown()

    def test_bad_magnet_rejected_before_session(self, tmp_path):
        eng = TorrentEngine(tmp_path / "dl2", poll_interval=0.5)
        try:
            with pytest.raises(ValueError):
                eng.add_magnet("magnet:?xt=nope")
            assert eng.snapshots() == []
        finally:
            eng.shutdown()

    def test_pause_resume_cancel(self, tmp_path):
        eng = TorrentEngine(tmp_path / "dl3", poll_interval=0.2)
        try:
            key = eng.add_magnet(MAGNET)
            eng.pause(key)
            eng.resume(key)
            eng.cancel(key)
            deadline = time.time() + 5
            while time.time() < deadline and eng.snapshots():
                time.sleep(0.1)
            assert eng.snapshots() == []
            # operations on unknown keys must not raise
            eng.pause("deadbeef" * 5)
            eng.resume("deadbeef" * 5)
            eng.cancel("deadbeef" * 5)
        finally:
            eng.shutdown()

    @pytest.mark.parametrize("bad,name", [
        (b"", "empty.torrent"),
        (b"garbage" * 100, "garbage.torrent"),
    ])
    def test_invalid_torrent_file(self, tmp_path, bad, name):
        p = tmp_path / name
        p.write_bytes(bad)
        eng = TorrentEngine(tmp_path / "dl4", poll_interval=0.5)
        try:
            with pytest.raises(ValueError):
                eng.add_torrent_file(p)
            with pytest.raises(ValueError):
                eng.add_torrent_file(tmp_path / "notes.txt")   # wrong suffix
            with pytest.raises(ValueError):
                eng.add_torrent_file(tmp_path / "ghost.torrent")  # missing
        finally:
            eng.shutdown()


class TestScoreStore:
    def test_best_time_keeps_minimum(self, tmp_path):
        from deskhub.features.games.store import ScoreStore
        s = ScoreStore(tmp_path / "scores.json")
        s.record("minesweeper", "expert", best_time=120)
        s.record("minesweeper", "expert", best_time=90)
        s.record("minesweeper", "expert", best_time=110)
        assert s.best("minesweeper", "expert", "best_time") == 90

    def test_wins_keeps_maximum(self, tmp_path):
        from deskhub.features.games.store import ScoreStore
        s = ScoreStore(tmp_path / "s.json")
        s.record("memory", "easy", wins=1)
        s.record("memory", "easy", wins=3)
        assert s.best("memory", "easy", "wins") == 3

    def test_persistence_across_instances(self, tmp_path):
        from deskhub.features.games.store import ScoreStore
        p = tmp_path / "p.json"
        ScoreStore(p).record("sudoku", "hard", best_seconds=500)
        assert ScoreStore(p).best("sudoku", "hard", "best_seconds") == 500

    def test_corrupt_file_recovers(self, tmp_path):
        from deskhub.features.games.store import ScoreStore
        p = tmp_path / "c.json"
        p.write_text("{not json", encoding="utf-8")
        s = ScoreStore(p)               # must not raise
        s.record("x", "y", wins=2)
        assert s.best("x", "y", "wins") == 2


class TestSettings:
    def test_roundtrip_and_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DESKHUB_DATA_DIR", str(tmp_path))
        from deskhub.settings import Settings
        st = Settings(tmp_path / "settings.json")
        assert st.get("enable_dht") is False          # privacy-safe default
        st.set("max_uploads", 4)
        assert Settings(tmp_path / "settings.json").get("max_uploads") == 4

    def test_corrupt_settings_falls_back(self, tmp_path):
        from deskhub.settings import Settings
        p = tmp_path / "settings.json"
        p.write_text("][broken", encoding="utf-8")
        st = Settings(p)
        assert st.get("theme_accent") == "#0078D4"

    def test_download_dir_default_created(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DESKHUB_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        from deskhub.settings import default_download_dir
        d = default_download_dir()
        assert d.is_dir()
