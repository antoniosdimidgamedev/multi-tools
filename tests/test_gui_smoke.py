"""Headless (offscreen) GUI smoke tests.

Verify the whole app boots, every feature page constructs, navigation works,
and PDF export produces a real file. conftest.py forces QT_QPA_PLATFORM=offscreen.
"""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

import deskhub.features.office.io_docs as io_docs  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def full_app(qapp, tmp_path, monkeypatch):
    """Boot the real app entry point up to (not including) exec()."""
    monkeypatch.setenv("DESKHUB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    import app as appmod

    monkeypatch.setattr(QApplication, "exec", lambda self: 0)
    rc = appmod.main()
    assert rc == 0
    win = getattr(qapp, "_deskhub_window", None)
    assert win is not None, "main() must create the DeskHub window"
    shell = win.centralWidget()
    yield qapp, win, shell
    for page in shell.pages.values():
        fn = getattr(page, "shutdown", None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
    win.deleteLater()


def test_all_four_tiles_present(full_app):
    _, win, shell = full_app
    assert set(shell.pages) >= {"home", "downloads", "games", "ai_studio", "office"}


def test_navigation_roundtrip(full_app):
    _, win, shell = full_app
    for key in ("downloads", "games", "ai_studio", "office"):
        shell.open_feature(key)
        assert shell.currentWidget() is shell.pages[key]
        assert "DeskHub" in win.windowTitle()
    shell.go_home()
    assert shell.currentWidget() is shell.home
    assert win.windowTitle() == "DeskHub"


def test_pdf_export_produces_file(qapp, tmp_path):
    out = tmp_path / "doc.pdf"
    io_docs.export_pdf_html("<h1>Hello DeskHub</h1><p>Export test.</p>", out)
    assert out.is_file()
    assert out.read_bytes()[:5] == b"%PDF-"


def test_downloads_page_rejects_bad_magnet(qapp, tmp_path, monkeypatch):
    """Malformed magnet input must be rejected without creating a download."""
    monkeypatch.setenv("DESKHUB_DATA_DIR", str(tmp_path))
    from deskhub.settings import Settings
    from deskhub.features.downloads.page import DownloadsPage

    page = DownloadsPage(Settings(tmp_path / "s.json"))
    try:
        box = page.findChild(QLineEdit)
        assert box is not None, "page should have a magnet input field"
        box.setText("magnet:?bogus")
        page._add_magnet()          # must not raise
        assert page._engine is None or page._engine.snapshots() == []
    finally:
        page.shutdown()
        page.deleteLater()
