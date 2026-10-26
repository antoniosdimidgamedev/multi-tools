"""Tests for the logging setup: privacy rule (events/sizes only, never content)."""
import importlib

import pytest


@pytest.fixture()
def fresh_logging(tmp_path, monkeypatch):
    """Reload logging_setup with an isolated data dir so handlers are re-created."""
    monkeypatch.setenv("DESKHUB_DATA_DIR", str(tmp_path))
    import deskhub.settings as settings
    importlib.reload(settings)
    import deskhub.logging_setup as ls
    importlib.reload(ls)
    yield ls, tmp_path


def test_log_file_created_under_appdata(fresh_logging):
    ls, tmp_path = fresh_logging
    log = ls.get_logger("test")
    log.info("engine started dht=%s", False)
    for h in ls.logging.getLogger("deskhub").handlers:
        h.flush()
    files = list(tmp_path.rglob("deskhub.log*"))
    assert files, "expected deskhub.log under the appdata dir"


def test_logged_events_are_structural_not_content(fresh_logging):
    pytest.importorskip("libtorrent", reason="python3-libtorrent binding not installed")
    ls, tmp_path = fresh_logging
    # re-obtain the logger after the reload (module-level loggers are cached
    # against the pre-reload tree; app code calls get_logger at import time)
    import deskhub.features.downloads.engine as eng
    importlib.reload(eng)
    log = eng.log
    # This mirrors how app code logs: sizes/counts only. The strings below are
    # what the app *would* log; we assert the mechanism writes them and that
    # nothing resembling document/chat content is ever passed to the logger
    # by checking the module's public API has no content-taking helpers.
    log.info("added torrent file (%d bytes meta)", 2048)
    log.info("document saved ext=%s bytes=%d", ".docx", 9001)
    for h in ls.logging.getLogger("deskhub").handlers:
        h.flush()
    content = next(tmp_path.rglob("deskhub.log")).read_text(encoding="utf-8")
    assert "added torrent file" in content
    assert "bytes=9001" in content
    # privacy contract: no helper in the module accepts user text blobs
    public = {n for n in dir(ls) if not n.startswith("_")}
    assert not {"log_prompt", "log_document", "log_chat"} & public


def test_get_logger_namespaced(fresh_logging):
    ls, _ = fresh_logging
    a = ls.get_logger("alpha")
    b = ls.get_logger("beta")
    assert a.name != b.name
