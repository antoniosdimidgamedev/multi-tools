"""Downloads page: torrent list + add controls, wired to TorrentEngine."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from deskhub.features.downloads.engine import TorrentEngine, TorrentInfo
from deskhub.logging_setup import get_logger
from deskhub.settings import Settings
from deskhub.util import human_rate, human_size, validate_download_dir

log = get_logger("downloads.ui")

_COLUMNS = ["Name", "Progress", "Down", "Up", "Peers", "State"]


class DownloadsPage(QWidget):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self._settings = settings
        self._engine: TorrentEngine | None = None
        dl_dir = validate_download_dir(settings.get("download_dir"))
        settings.set("download_dir", str(dl_dir))
        self._engine = TorrentEngine(
            dl_dir,
            enable_dht=bool(settings.get("enable_dht", False)),
            max_uploads=int(settings.get("max_uploads", 8)),
            poll_interval=1.0,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(10)

        banner = QLabel(
            "You are responsible for downloading and sharing only content you "
            "are authorized to access. DeskHub has no search feature and does "
            "not share your files or machine beyond what an active download requires."
        )
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background:#FFF4CE; border:1px solid #E8D9A0; border-radius:6px; padding:8px;")
        root.addWidget(banner)

        top = QHBoxLayout()
        self.magnet_edit = QLineEdit()
        self.magnet_edit.setPlaceholderText("Paste a magnet link (magnet:?xt=urn:btih:…)")
        self.magnet_edit.setAccessibleName("Magnet link input")
        btn_magnet = QPushButton("Add magnet")
        btn_magnet.setProperty("role", "accent")
        btn_magnet.clicked.connect(self._add_magnet)
        btn_file = QPushButton("Open .torrent…")
        btn_file.clicked.connect(self._add_file)
        btn_dir = QPushButton("Download folder…")
        btn_dir.clicked.connect(self._pick_folder)
        top.addWidget(self.magnet_edit, 1)
        top.addWidget(btn_magnet)
        top.addWidget(btn_file)
        top.addWidget(btn_dir)
        root.addLayout(top)

        self.dir_label = QLabel(f"Saving to: {dl_dir}")
        self.dir_label.setObjectName("dirLabel")
        root.addWidget(self.dir_label)

        self.table = QTableWidget(0, len(_COLUMNS) + 3)
        self.table.setHorizontalHeaderLabels(_COLUMNS + ["", "", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(_COLUMNS)):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        for c in range(len(_COLUMNS), len(_COLUMNS) + 3):
            hdr.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, 78)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        b_pause = QPushButton("Pause")
        b_resume = QPushButton("Resume")
        b_cancel = QPushButton("Cancel (keep files)")
        b_remove = QPushButton("Remove + delete files")
        for b in (b_pause, b_resume, b_cancel, b_remove):
            b.clicked.connect(lambda _=False, fn=b.text(): self._act(fn))
            actions.addWidget(b)
        actions.addStretch(1)
        self.status_label = QLabel("Idle")
        actions.addWidget(self.status_label)
        root.addLayout(actions)
        self._buttons = {"Pause": b_pause, "Resume": b_resume,
                         "Cancel (keep files)": b_cancel,
                         "Remove + delete files": b_remove}

        self._rows: dict[str, int] = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

    # ---- actions --------------------------------------------------------
    def on_shown(self):
        self._refresh()

    def _add_magnet(self):
        url = self.magnet_edit.text().strip()
        try:
            self._engine.add_magnet(url)
            self.magnet_edit.clear()
            self.status_label.setText("Magnet added.")
            self._refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid magnet link", str(exc))
        except Exception as exc:
            log.error("magnet add failed: %s", type(exc).__name__)
            QMessageBox.critical(self, "Could not add magnet",
                                 "The torrent engine rejected this link. "
                                 "Check your network connection and try again.")

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open torrent file",
                                              str(Path.home()), "Torrent files (*.torrent)")
        if not path:
            return
        try:
            self._engine.add_torrent_file(path)
            self.status_label.setText("Torrent file added.")
            self._refresh()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid torrent file", str(exc))
        except OSError as exc:
            QMessageBox.critical(self, "Disk error", f"Cannot read file: {exc}")

    def _pick_folder(self):
        start = self._settings.get("download_dir")
        d = QFileDialog.getExistingDirectory(self, "Choose download folder", start)
        if not d:
            return
        try:
            p = validate_download_dir(d)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid folder", str(exc))
            return
        self._settings.set("download_dir", str(p))
        self.dir_label.setText(f"Saving to: {p}")
        # Engine keeps its old save_path for running torrents; new ones use it too
        # after restart. Ask user whether to restart now.
        r = QMessageBox.question(
            self, "Restart downloads?",
            "Changing the download folder applies to new torrents immediately "
            "after restarting the engine. Restart now? Active downloads will "
            "resume from where they stopped.",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self._restart_engine(p)

    def _restart_engine(self, folder: Path):
        self._engine.shutdown()
        self._rows.clear()
        self.table.setRowCount(0)
        self._engine = TorrentEngine(
            folder, enable_dht=bool(self._settings.get("enable_dht", False)),
            max_uploads=int(self._settings.get("max_uploads", 8)))

    def _selected_key(self) -> str | None:
        items = self.table.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.UserRole)

    def _act(self, which: str):
        key = self._selected_key()
        if not key:
            self.status_label.setText("Select a torrent first.")
            return
        if which == "Pause":
            self._engine.pause(key)
        elif which == "Resume":
            self._engine.resume(key)
        elif which == "Cancel (keep files)":
            self._engine.cancel(key, delete_files=False)
        else:
            r = QMessageBox.question(
                self, "Delete downloaded data?",
                "This removes the torrent AND deletes any partially/fully "
                "downloaded files belonging to it. This cannot be undone.",
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            self._engine.cancel(key, delete_files=True)
        self._refresh()

    # ---- refresh --------------------------------------------------------
    def _refresh(self):
        infos: list[TorrentInfo] = self._engine.snapshots()
        order = sorted(infos, key=lambda i: i.name.lower())
        # rebuild rows keyed by info-hash stored in UserRole of col-0 item
        self._rows.clear()
        self.table.setRowCount(len(order))
        for r, info in enumerate(order):
            name_item = QTableWidgetItem(info.name)
            name_item.setData(Qt.UserRole, info.handle_key)
            name_item.setToolTip(info.handle_key)
            self.table.setItem(r, 0, name_item)

            prog = QTableWidgetItem(f"{info.progress*100:.1f}%")
            if info.total_want:
                prog.setToolTip(f"{human_size(info.total_done)} of "
                                f"{human_size(info.total_want)}")
            self.table.setItem(r, 1, prog)
            self.table.setItem(r, 2, QTableWidgetItem(human_rate(info.download_rate)))
            self.table.setItem(r, 3, QTableWidgetItem(human_rate(info.upload_rate)))
            self.table.setItem(r, 4, QTableWidgetItem(
                f"{info.peers}" + (f" ({info.seeds} seeds)" if info.seeds else "")))
            state_txt = info.state
            if info.error:
                state_txt += " — see tooltip"
            st_item = QTableWidgetItem(state_txt)
            if info.error:
                st_item.setToolTip(info.error[:500])
            self.table.setItem(r, 5, st_item)

    # ---- lifecycle ------------------------------------------------------
    def shutdown(self):
        if self._engine:
            self._engine.shutdown()
            self._engine = None
