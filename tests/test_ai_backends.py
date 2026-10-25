"""Tests for GGUF metadata parsing, hardware/compat checks and repo-id validation."""
import sys

import pytest

from deskhub.features.ai_studio import backends as B
from conftest import write_fake_gguf


class TestGgufParsing:
    def test_valid_header(self, fake_gguf):
        meta = B.read_gguf_metadata(fake_gguf)
        assert meta["valid"] is True
        assert meta["general.name"] == "Test Model"
        assert meta["general.architecture"] == "llama"
        assert meta["version"] == 3
        assert meta["size_bytes"] == fake_gguf.stat().st_size

    def test_not_a_file(self, tmp_path):
        meta = B.read_gguf_metadata(tmp_path / "ghost.gguf")
        assert meta["valid"] is False and "does not exist" in meta["reason"]

    def test_bad_magic(self, tmp_path):
        p = tmp_path / "x.gguf"
        p.write_bytes(b"NOPE" + b"\x00" * 100)
        meta = B.read_gguf_metadata(p)
        assert meta["valid"] is False and "magic" in meta["reason"]

    def test_unsupported_version(self, tmp_path):
        p = tmp_path / "v9.gguf"
        write_fake_gguf(p, {"general.name": "future"}, version=9)
        meta = B.read_gguf_metadata(p)
        assert meta["valid"] is False and "version" in meta["reason"]

    def test_truncated_file_no_crash(self, fake_gguf):
        raw = fake_gguf.read_bytes()
        truncated = raw[: len(raw) // 2]
        fake_gguf.write_bytes(truncated)
        meta = B.read_gguf_metadata(fake_gguf)
        assert meta["valid"] is False  # graceful, no exception


class TestCompat:
    def test_missing_runtime_blocks_with_message(self, fake_gguf, monkeypatch):
        monkeypatch.setattr(B, "detect_runtime",
                            lambda: B.RuntimeInfo(llama_cpp_python=False, cli_binary=None, detail="none"))
        rep = B.check_compatibility(fake_gguf, B.detect_runtime())
        assert rep.ok is False
        assert any("runtime" in m.lower() for m in rep.messages)

    def test_non_gguf_rejected(self, tmp_path, monkeypatch):
        p = tmp_path / "doc.docx"
        p.write_bytes(b"PK\x03\x04fake")
        rt = B.RuntimeInfo(llama_cpp_python=True, detail="test")
        rep = B.check_compatibility(p, rt)
        assert rep.ok is False

    def test_ram_estimate_positive(self, fake_gguf):
        est = B.estimate_model_ram(fake_gguf)
        assert est > 0

    def test_huge_model_flagged_when_over_ram(self, tmp_path, monkeypatch):
        big = tmp_path / "big.gguf"
        write_fake_gguf(big, {"general.name": "BIG"})
        # pretend the file is 500 GiB without writing it
        real_stat = big.stat

        import stat as _stat

        class S:
            st_size = 500 * 2**30
            st_mode = _stat.S_IFREG | 0o644

        monkeypatch.setattr(type(big), "stat", lambda self, **kw: S(), raising=False)
        rt = B.RuntimeInfo(llama_cpp_python=True, detail="test")
        rep = B.check_compatibility(big, rt)
        monkeypatch.undo()
        assert rep.ok is False or any("memory" in m.lower() for m in rep.messages)


class TestRuntimeDetect:
    def test_reports_without_llama_installed(self, monkeypatch):
        # In CI llama-cpp-python may or may not exist; either way it must not raise.
        monkeypatch.setattr(B.shutil, "which", lambda *a, **k: None)
        monkeypatch.setitem(sys.modules, "llama_cpp", None)  # force ImportError
        info = B.detect_runtime()
        assert isinstance(info.available, bool)
        assert info.available is False
        assert info.name == ""
        assert "Install" in info.detail or "runtime" in info.detail.lower()

    def test_total_ram_positive(self):
        assert B.total_ram_bytes() > 0


class TestRepoId:
    @pytest.mark.parametrize("good", ["TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF",
                                      "org/model.bin-x"])
    def test_valid(self, good):
        assert B.validate_repo_id(good) == good

    @pytest.mark.parametrize("bad", [
        "", "no-slash", "/leading", "trailing/", "..\\escape",
        "a" * 300, "with spaces/here", "semi;colon/x",
    ])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            B.validate_repo_id(bad)
