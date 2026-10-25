"""DeskHub — Windows 11 launcher for Downloads, Games, AI Studio and Office.

Run:  python app.py
"""
from __future__ import annotations

import sys


def main() -> int:
    # High-DPI / Win11 rounding behaviour is automatic in Qt6; keep style native.
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette, QColor

    app = QApplication(sys.argv)
    app.setApplicationName("DeskHub")
    app.setOrganizationName("DeskHub")
    app.setStyle("Fusion")

    # Light palette close to Win11 defaults.
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#F3F3F3"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1A1A1A"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1A1A1A"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FBFBFB"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#0078D4"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(pal)

    from deskhub.logging_setup import setup_logging
    setup_logging()

    from deskhub.settings import Settings
    settings = Settings()

    from deskhub.shell import HomePage, Shell
    from deskhub.features.downloads.page import DownloadsPage
    from deskhub.features.games.page import GamesPage
    from deskhub.features.ai_studio.studio import AIStudioPage
    from deskhub.features.office.page import OfficePage

    win_title = {"v": "DeskHub"}

    def set_title(t: str):
        win_title["v"] = t
        if hasattr(app, "_deskhub_window"):
            app._deskhub_window.setWindowTitle(t)

    shell = Shell(set_title)
    launchers = {k: (lambda kk=k: shell.open_feature(kk))
                 for k in ("downloads", "games", "ai_studio", "office")}
    home = HomePage(launchers, accent=settings.get("theme_accent", "#0078D4"))
    shell.home = home
    shell.add_page("home", home, "Home")

    dl = DownloadsPage(settings, shell)
    shell.add_page("downloads", dl, "Downloads")
    games = GamesPage(settings, shell)
    shell.add_page("games", games, "Games")
    ai = AIStudioPage(settings)
    shell.add_page("ai_studio", ai, "AI Studio")
    office = OfficePage(shell)
    shell.add_page("office", office, "Office")

    from PySide6.QtWidgets import QMainWindow
    window = QMainWindow()
    window.setWindowTitle("DeskHub")
    window.setCentralWidget(shell)
    window.resize(1100, 720)
    window.setMinimumSize(900, 600)
    app._deskhub_window = window

    shell.bind_shortcuts(window)
    shell.go_home()

    def _cleanup():
        try:
            dl.shutdown()
        except Exception:
            pass
        try:
            ai.shutdown()
        except Exception:
            pass

    app.aboutToQuit.connect(_cleanup)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
