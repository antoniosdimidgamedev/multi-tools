"""Tests for shared path/input validation helpers."""
import pytest

from deskhub.util import (
    human_size, human_rate, is_valid_filename, parse_magnet,
    safe_save_path, sanitize_display_name, validate_download_dir,
)


class TestFilenames:
    @pytest.mark.parametrize("name", [
        "report.docx", "my file 1.txt", "a" * 100 + ".md", "notes_v2.csv",
    ])
    def test_valid(self, name):
        assert is_valid_filename(name)

    @pytest.mark.parametrize("name", [
        "", ".", "..", "bad:name.txt", 'quote".txt', "slash/a.txt",
        "back\\slash", "pipe|char", "star*", "q?", "con.txt", "NUL.log",
        "com1.dat", "trailing.", "trailing ", "x" * 300, "\x00null",
    ])
    def test_invalid(self, name):
        assert not is_valid_filename(name)


class TestDownloadDir:
    def test_creates_and_resolves(self, tmp_path):
        target = tmp_path / "Downloads" / "DeskHub"
        p = validate_download_dir(str(target))
        assert p.is_dir() and p.is_absolute()

    def test_empty_rejected(self):
        with pytest.raises(ValueError):
            validate_download_dir("   ")

    def test_relative_rejected(self):
        with pytest.raises(ValueError, match="absolute"):
            validate_download_dir("relative/dir")

    def test_bad_component_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid folder"):
            validate_download_dir(str(tmp_path / "ba:d"))


class TestSafeSavePath:
    def test_no_silent_overwrite(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"x")
        got = safe_save_path(f)
        assert got != f and got.name == "doc (1).docx"

    def test_overwrite_allowed(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"x")
        assert safe_save_path(f, allow_overwrite=True) == f

    def test_bad_extension_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported extension"):
            safe_save_path(tmp_path / "evil.exe")

    def test_bad_name_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            safe_save_path(tmp_path / "bad:name.txt")


class TestMagnets:
    HASH40 = "0123456789abcdef0123456789abcdef01234567"

    def test_hex40_with_dn_and_trackers(self):
        url = (f"magnet:?xt=urn:btih:{self.HASH40}"
               "&dn=Big+Buck+Bunny&tr=http%3A%2F%2Ftracker.example%2Fannounce")
        r = parse_magnet(url)
        assert r["info_hash"] == self.HASH40
        assert r["display_name"] == "Big Buck Bunny"
        assert r["trackers"] == ["http://tracker.example/announce"]

    def test_base32_decoded(self):
        # base32 of the raw 20 bytes of HASH40
        import base64
        b32 = base64.b32encode(bytes.fromhex(self.HASH40)).decode().rstrip("=")
        r = parse_magnet(f"magnet:?xt=urn:btih:{b32}")
        assert r["info_hash"] == self.HASH40

    @pytest.mark.parametrize("url", [
        "", "http://example.com/file.torrent", "magnet:?xt=hello",
        "magnet:?xt=urn:btih:" + "z" * 40,
        "magnet:?xt=urn:btih:" + "0" * 39,  # wrong length
    ])
    def test_invalid_rejected(self, url):
        with pytest.raises(ValueError):
            parse_magnet(url)

    def test_dn_length_capped(self):
        r = parse_magnet("magnet:?xt=urn:btih:" + self.HASH40 + "&dn=" + "A" * 500)
        assert len(r["display_name"]) <= 200


class TestMisc:
    def test_human_size(self):
        assert human_size(None) == "—"
        assert human_size(512) == "512 B"
        assert human_size(1536) == "1.5 KB"
        assert human_size(3 * 2**30) == "3.0 GB"

    def test_human_rate(self):
        assert human_rate(1024) == "1.0 KB/s"

    def test_sanitize_display_name_traversal(self):
        assert "/" not in sanitize_display_name("../../etc/passwd", "fb")
        assert sanitize_display_name(None, "fb") == "fb"
        # dots are legal inside Windows file names and must be preserved
        assert sanitize_display_name("C:\\evil\\name:*.txt", "fb") == "name.txt"
        assert sanitize_display_name("..\\..\\x", "fb") == "x"
        assert sanitize_display_name("...", "fb") == "fb"  # pure dots -> fallback
