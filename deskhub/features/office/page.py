"""Office page: launcher + Writer / Spreadsheet / Presenter editors.

Data-loss protection: every editor tracks a dirty flag, prompts on close and
on switching documents, and never silently overwrites (deskhub.util.safe_save_path).
"""
from __future__ import annotations

import html as _html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from deskhub.features.office import io_docs
from deskhub.features.office.io_docs import DocIOError
from deskhub.features.office.logic import FormulaError, SheetModel, cell_name
from deskhub.theme import ACCENT, BORDER, CARD
from deskhub.util import safe_save_path


def _qss_btn():
    return (f"QPushButton{{background:{CARD};border:1px solid {BORDER};"
            "border-radius:6px;padding:5px 10px;}"
            "QPushButton:hover{background:#F3F3F3;}")


class _EditorBase(QWidget):
    """Shared toolbar plumbing + dirty tracking + save/open helpers."""

    NAME = "Document"
    FILTERS = "*.docx;;*.txt;;*.md"

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.path: Path | None = None
        self.dirty = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        back = QPushButton("← Home")
        back.setStyleSheet(_qss_btn())
        back.clicked.connect(self._go_home)
        for label, slot in (("New", self._new), ("Open…", self._open),
                            ("Save", self._save), ("Save As…", self._save_as)):
            b = QPushButton(label)
            b.setStyleSheet(_qss_btn())
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addWidget(back)
        self.extra_buttons: list[QPushButton] = []
        self.title_lbl = QLabel("Untitled")
        self.title_lbl.setStyleSheet("color:#5F5F5F; margin-left:8px;")
        bar.addStretch(1)
        bar.addWidget(self.title_lbl)
        lay.addLayout(bar)

        self.body = QVBoxLayout()
        lay.addLayout(self.body)

        for seq, slot in (("Ctrl+N", self._new), ("Ctrl+O", self._open),
                          ("Ctrl+S", self._save), ("Ctrl+Shift+S", self._save_as)):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    # -- hooks -------------------------------------------------------------
    def add_toolbar_button(self, label, slot):
        b = QPushButton(label)
        b.setStyleSheet(_qss_btn())
        b.clicked.connect(slot)
        self.layout().itemAt(0).layout().insertWidget(len(self.layout().itemAt(0).layout()).count() - 2, b)
        self.extra_buttons.append(b)
        return b

    def content_changed(self):
        raise NotImplementedError

    def make_new(self):
        raise NotImplementedError

    def load_from(self, path: Path):
        raise NotImplementedError

    def save_to(self, path: Path):
        raise NotImplementedError

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        resp = QMessageBox.question(
            self, "Unsaved changes",
            f"You have unsaved changes in {self.current_name()}.\nSave before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if resp == QMessageBox.StandardButton.Save:
            return self._save()
        return resp == QMessageBox.StandardButton.Discard

    def current_name(self) -> str:
        return self.path.name if self.path else "Untitled"

    def set_dirty(self, d: bool = True):
        self.dirty = d
        self.title_lbl.setText(("● " if d else "") + self.current_name())

    # -- actions -----------------------------------------------------------
    def _go_home(self):
        if self.confirm_discard():
            self.shell.go_home()

    def _new(self):
        if not self.confirm_discard():
            return
        self.make_new()
        self.path = None
        self.set_dirty(False)

    def _open(self):
        if not self.confirm_discard():
            return
        fn, _ = QFileDialog.getOpenFileName(self, f"Open {self.NAME}", str(Path.home()),
                                            self.FILTERS)
        if not fn:
            return
        try:
            self.load_from(Path(fn))
            self.path = Path(fn)
            self.set_dirty(False)
        except DocIOError as exc:
            QMessageBox.warning(self, f"Can't open file — {self.NAME}", str(exc))

    def _save(self) -> bool:
        if self.path is None:
            return self._save_as()
        try:
            self.save_to(self.path)
            self.set_dirty(False)
            return True
        except DocIOError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False

    def _save_as(self) -> bool:
        suggested = str((self.path or Path.home() / f"Untitled_{self.NAME.lower()}")) 
        fn, _ = QFileDialog.getSaveFileName(self, f"Save {self.NAME}", suggested, self.FILTERS)
        if not fn:
            return False
        try:
            target = safe_save_path(fn, allow_overwrite=False)
            if target.exists():
                q = QMessageBox.question(
                    self, "File exists",
                    f"{target.name} already exists.\nOverwrite it? (choosing No keeps the "
                    f"suggested alternate name)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if q == QMessageBox.StandardButton.Yes:
                    target = Path(fn)
            self.save_to(target)
            self.path = target
            self.set_dirty(False)
            return True
        except (DocIOError, ValueError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class WriterEditor(_EditorBase):
    NAME = "Document"
    FILTERS = "Word/Text (*.docx *.txt *.md);;All files (*)"

    def __init__(self, shell):
        super().__init__(shell)
        row = QHBoxLayout()
        self.style = QComboBox()
        self.style.addItems(["Paragraph", "Heading 1", "Heading 2", "Heading 3"])
        self.style.currentIndexChanged.connect(self._apply_style)
        self.size = QSpinBox()
        self.size.setRange(8, 72)
        self.size.setValue(11)
        self.size.valueChanged.connect(self._apply_size)
        self.bold_b = QPushButton("B")
        self.bold_b.setCheckable(True)
        self.bold_b.setStyleSheet(_qss_btn() + "QPushButton{font-weight:bold;}")
        self.bold_b.clicked.connect(lambda: self._toggle_fmt("bold"))
        self.ital_b = QPushButton("I")
        self.ital_b.setCheckable(True)
        self.ital_b.setStyleSheet(_qss_btn() + "QPushButton{font-style:italic;}")
        self.ital_b.clicked.connect(lambda: self._toggle_fmt("italic"))
        center = QPushButton("≡ Center")
        center.setStyleSheet(_qss_btn())
        center.clicked.connect(lambda: self.edit.setAlignment(Qt.AlignmentFlag.AlignHCenter))
        left = QPushButton("≡ Left")
        left.setStyleSheet(_qss_btn())
        left.clicked.connect(lambda: self.edit.setAlignment(Qt.AlignmentFlag.AlignLeft))
        pdf = QPushButton("Export PDF")
        pdf.setStyleSheet(_qss_btn())
        pdf.clicked.connect(self._export_pdf)
        for w in (QLabel("Style:"), self.style, QLabel("Size:"), self.size,
                  self.bold_b, self.ital_b, center, left, pdf):
            row.addWidget(w)
        row.addStretch(1)
        self.body.addLayout(row)

        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.textChanged.connect(lambda: self.set_dirty(True))
        self.body.addWidget(self.edit)

    def _fmt(self, html_fragment):
        c = self.edit.textCursor()
        c.insertHtml(html_fragment)

    def _apply_size(self, pt: int):
        cur = self.edit.currentCharFormat()
        cur.setFontPointSize(pt)
        self.edit.setCurrentCharFormat(cur)
        tc = self.edit.textCursor()
        if tc.hasSelection():
            tc.mergeCharFormat(cur)

    def _toggle_fmt(self, which):
        cur = self.edit.textCursor()
        fmt = cur.charFormat()
        key = "Bold" if which == "bold" else "Italic"
        on = getattr(self, which + "_b").isChecked()
        getattr(fmt, "set" + key)(on)
        cur.mergeCharFormat(fmt)
        self.edit.setCurrentCharFormat(fmt)

    def _apply_style(self, idx):
        from PySide6.QtGui import QTextBlockFormat
        bf = QTextBlockFormat()
        if idx:
            if hasattr(bf, "setHeadingLevel"):
                bf.setHeadingLevel(idx)
        sizes = [11, 20, 16, 13]
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.MoveOperation.Document)
        fmt = cur.charFormat()
        fmt.setFontPointSize(sizes[idx])
        fmt.setFontWeight(700 if idx else 400)
        cur.mergeCharFormat(fmt)
        cur.setBlockFormat(bf)
        self.edit.setTextCursor(cur)

    def make_new(self):
        self.edit.clear()

    def load_from(self, path: Path):
        blocks = io_docs.writer_load(path)
        if path.suffix.lower() == ".docx":
            from docx import Document
            doc = Document(str(path))
            self.edit.setHtml(_docx_to_html(doc))
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
            self.edit.setPlainText(text)

    def save_to(self, path: Path):
        ext = path.suffix.lower()
        if ext == ".docx":
            io_docs.writer_save(self._blocks(), path)
        elif ext in (".txt", ".md"):
            path.write_text(self.edit.toPlainText(), encoding="utf-8")
        else:
            raise DocIOError(f"Writer saves .docx/.txt/.md only, not {ext!r}.")

    def _blocks(self) -> list[dict]:
        from PySide6.QtGui import QTextCursor
        out = []
        doc = self.edit.document()
        blk = doc.begin()
        while blk.isValid():
            cur = QTextCursor(blk)
            tf = cur.charFormat()
            txt = blk.text()
            bf = blk.blockFormat()
            heading = 0
            if hasattr(bf, "headingLevel"):
                heading = int(bf.headingLevel() or 0)
            align_flag = getattr(Qt.AlignmentFlag, "AlignHCenter", None)
            centered = bool(align_flag is not None and (int(bf.alignment()) & int(align_flag)))
            out.append({
                "text": txt, "heading": heading,
                "bold": bool(tf.fontWeight() and tf.fontWeight() >= 700),
                "italic": bool(tf.fontItalic()),
                "size_pt": tf.fontPointSize() or None,
                "align": "center" if centered else "left",
            })
            blk = blk.next()
        return out

    def _export_pdf(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Export PDF",
                                            str((self.path or Path.home()) .with_suffix(".pdf")),
                                            "PDF (*.pdf)")
        if not fn:
            return
        try:
            target = safe_save_path(fn, allow_overwrite=True)
            io_docs.export_pdf_html(self.edit.toHtml(), target)
            QMessageBox.information(self, "Exported", f"PDF written to\n{target}")
        except (DocIOError, ValueError) as exc:
            QMessageBox.critical(self, "PDF export failed", str(exc))


def _docx_to_html(doc) -> str:
    parts = []
    for p in doc.paragraphs:
        t = "".join(
            f"<i>{_html.escape(r.text)}</i>" if r.italic else _html.escape(r.text)
            for r in (p.runs or [])) or _html.escape(p.text)
        style = (p.style.name or "").lower()
        if style.startswith("heading"):
            lvl = style.rsplit(" ", 1)[-1] if style[-1].isdigit() else "1"
            parts.append(f"<h{min(int(lvl), 4)}>{t}</h{lvl}>")
        else:
            bold = any(r.bold for r in p.runs)
            if bold:
                t = f"<b>{t}</b>"
            parts.append(f"<p>{t}</p>")
    return "".join(parts) or "<p></p>"


# ---------------------------------------------------------------------------
# Spreadsheet
# ---------------------------------------------------------------------------

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractItemView  # noqa: E402
from deskhub.features.office.logic import col_letters, fmt_number  # noqa: E402


class SheetGrid(QTableWidget):
    def __init__(self, model: SheetModel, on_edit, rows=60, cols=15):
        super().__init__(rows, cols)
        self.model = model
        self.on_edit = on_edit
        self.setHorizontalHeaderLabels([col_letters(c) for c in range(cols)])
        self.setVerticalHeaderLabels([str(i + 1) for i in range(rows)])
        self._loading = False
        self.itemChanged.connect(self._changed)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)

    def _changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        self.model.set_raw(item.row(), item.column(), item.text())
        self.on_edit()

    def refresh_display(self):
        """Show computed values; keep raw formula in edit buffer."""
        try:
            vals = self.model.evaluate_all()
            err = None
        except FormulaError as e:
            vals, err = {}, str(e)
        self._loading = True
        for (r, c), raw in self.model.raw.items():
            if r >= self.rowCount() or c >= self.columnCount():
                continue
            it = self.item(r, c) or QTableWidgetItem()
            v = vals.get((r, c), raw)
            if isinstance(v, float):
                it.setText(fmt_number(v))
            else:
                it.setText("" if v is None else str(v))
            it.setData(Qt.ItemDataRole.UserRole, raw)
            if raw.startswith("="):
                it.setBackground(Qt.GlobalColor.lightGray)
            if not (self.item(r, c) is it):
                self.removeCellWidget(r, c)
                super().setItem(r, c, None)
                self.setItem(r, c, it)
        self._loading = False
        if err:
            self.last_error = err
        return err


class SpreadsheetEditor(_EditorBase):
    NAME = "Spreadsheet"
    FILTERS = "Spreadsheets (*.xlsx *.csv);;All files (*)"

    def __init__(self, shell):
        super().__init__(shell)
        self.model = SheetModel()
        self.cellinfo = QLineEdit()
        self.cellinfo.setPlaceholderText("Selected cell — type a number, text, or =SUM(A1:A4)")
        self.cellinfo.setStyleSheet(f"border:1px solid {BORDER}; border-radius:6px; padding:4px;")
        self.status = QLabel("")
        self.status.setStyleSheet("color:#5F5F5F;")
        self.grid = SheetGrid(self.model, self._after_edit)
        self.grid.currentCellChanged.connect(self._cell_moved)
        self.body.addWidget(self.cellinfo)
        self.body.addWidget(self.grid, 1)
        self.body.addWidget(self.status)

    def _cell_moved(self, r, c, *_):
        if r < 0:
            return
        raw = self.model.get_raw(r, c)
        self.cellinfo.setText(raw)
        self.cellinfo.placeholderText()

    def _after_edit(self):
        self.set_dirty(True)
        err = self.grid.refresh_display()
        self.status.setText(f"⚠ {err}" if err else
                            "Formulas: =SUM =AVERAGE =MIN =MAX =COUNT =ROUND =ABS, refs A1:B4, + - * / ^")

    def make_new(self):
        self.model.raw.clear()
        self.grid.clear()
        self.status.setText("")

    def load_from(self, path: Path):
        self.model = io_docs.sheet_load(path)
        self.grid.model = self.model
        self.grid.clear()
        for (r, c), raw in self.model.raw.items():
            if r < self.grid.rowCount() and c < self.grid.columnCount():
                self.grid.setItem(r, c, QTableWidgetItem(raw))
        self._after_edit()

    def save_to(self, path: Path):
        io_docs.sheet_save(self.model, path)


# ---------------------------------------------------------------------------
# Presenter
# ---------------------------------------------------------------------------

class PresenterEditor(_EditorBase):
    NAME = "Presentation"
    FILTERS = "PowerPoint (*.pptx);;All files (*)"

    def __init__(self, shell):
        super().__init__(shell)
        self.slides: list[dict] = []
        self.index = -1
        sp = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        btnrow = QHBoxLayout()
        for label, slot in (("＋ Slide", self._add_slide), ("－ Delete", self._del_slide),
                             ("▲", lambda: self._move(-1)), ("▼", lambda: self._move(1))):
            b = QPushButton(label)
            b.setStyleSheet(_qss_btn())
            b.clicked.connect(slot)
            btnrow.addWidget(b)
        ll.addLayout(btnrow)
        self.listw = QListWidget()
        self.listw.currentRowChanged.connect(self._select)
        ll.addWidget(self.listw, 1)
        self.preview = QLabel("(no slides)")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"background:{CARD};border:1px solid {BORDER};border-radius:8px;")
        self.preview.setMinimumWidth(260)
        ll.addWidget(self.preview, 1)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.layout_cb = QComboBox()
        self.layout_cb.addItems(["title", "content", "blank"])
        self.layout_cb.currentTextChanged.connect(self._set_layout)
        self.title_ed = QLineEdit()
        self.title_ed.setPlaceholderText("Slide title")
        self.body_ed = QTextEdit()
        self.body_ed.setPlaceholderText("Bullet lines — one per line")
        imgrow = QHBoxLayout()
        self.img_btn = QPushButton("Insert image…")
        self.img_btn.setStyleSheet(_qss_btn())
        self.img_btn.clicked.connect(self._pick_image)
        self.img_lbl = QLabel("no image")
        self.img_lbl.setStyleSheet("color:#5F5F5F;")
        imgrow.addWidget(self.img_btn)
        imgrow.addWidget(self.img_lbl)
        imgrow.addStretch(1)
        rl.addWidget(QLabel("Layout:"))
        rl.addWidget(self.layout_cb)
        rl.addWidget(self.title_ed)
        rl.addWidget(self.body_ed, 1)
        rl.addLayout(imgrow)
        exp = QPushButton("Export PDF")
        exp.setStyleSheet(_qss_btn())
        exp.clicked.connect(self._export_pdf)
        rl.addWidget(exp)

        sp.addWidget(left)
        sp.addWidget(right)
        sp.setStretchFactor(1, 1)
        self.body.addWidget(sp, 1)
        self.title_ed.textChanged.connect(lambda: self._patch(title=self.title_ed.text()))
        self.body_ed.textChanged.connect(lambda: self._patch(body=self.body_ed.toPlainText()))
        self._loading = False

    # -- slide ops ----------------------------------------------------------
    def _add_slide(self):
        self.slides.append({"title": "", "body": "", "image": None, "layout": "content"})
        self._relist()
        self.listw.setCurrentRow(len(self.slides) - 1)
        self.set_dirty(True)

    def _del_slide(self):
        if 0 <= self.index < len(self.slides) and self.slides:
            del self.slides[self.index]
            self._relist()
            self.set_dirty(True)

    def _move(self, d):
        i = self.index
        j = i + d
        if 0 <= i < len(self.slides) and 0 <= j < len(self.slides):
            self.slides[i], self.slides[j] = self.slides[j], self.slides[i]
            self._relist()
            self.listw.setCurrentRow(j)
            self.set_dirty(True)

    def _relist(self):
        self.listw.clear()
        for n, s in enumerate(self.slides, 1):
            self.listw.addItem(f"{n}. {s['title'] or '(untitled)'}")
        if self.slides:
            self.index = min(self.index, len(self.slides) - 1)
        else:
            self.index = -1
        self._update_preview()

    def _select(self, row):
        self.index = row
        self._loading = True
        if 0 <= row < len(self.slides):
            s = self.slides[row]
            self.title_ed.setText(s["title"])
            self.body_ed.setPlainText(s["body"])
            self.layout_cb.setCurrentText(s["layout"])
            self.img_lbl.setText(Path(s["image"]).name if s.get("image") else "no image")
        self._loading = False
        self._update_preview()

    def _patch(self, **kw):
        if self._loading or not (0 <= self.index < len(self.slides)):
            return
        self.slides[self.index].update(kw)
        self.set_dirty(True)
        self.listw.item(self.index).setText(
            f"{self.index + 1}. {self.slides[self.index]['title'] or '(untitled)'}")
        self._update_preview()

    def _set_layout(self, val):
        self._patch(layout=val)

    def _pick_image(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Insert image", str(Path.home()),
                                            "Images (*.png *.jpg *.jpeg *.bmp *.gif)")
        if fn:
            self._patch(image=fn)
            self.img_lbl.setText(Path(fn).name)
            self._update_preview()

    def _update_preview(self):
        if not (0 <= self.index < len(self.slides)):
            self.preview.setText("(no slides)")
            return
        s = self.slides[self.index]
        pix = ""
        if s.get("image") and Path(s["image"]).exists():
            from PySide6.QtGui import QPixmap
            pm = QPixmap(s["image"]).scaled(240, 140,
                                           Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
            self.preview.setPixmap(pm)
            return
        txt = (s["title"] or "") + ("\n\n" + s["body"] if s["body"] else "")
        self.preview.setText(txt.strip() or "(empty slide)")

    # -- persistence --------------------------------------------------------
    def make_new(self):
        self.slides = [{"title": "My Presentation", "body": "", "image": None, "layout": "title"},
                       {"title": "", "body": "", "image": None, "layout": "content"}]
        self._relist()
        self.listw.setCurrentRow(0)

    def load_from(self, path: Path):
        self.slides = io_docs.presenter_load(path)
        self._relist()
        if self.slides:
            self.listw.setCurrentRow(0)

    def save_to(self, path: Path):
        io_docs.presenter_save(self.slides, path)

    def _export_pdf(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Export PDF",
                                            str((self.path or Path.home() / "slides").with_suffix(".pdf")),
                                            "PDF (*.pdf)")
        if not fn:
            return
        try:
            target = safe_save_path(fn, allow_overwrite=True)
            pages = []
            for s in self.slides:
                body = _html.escape(s["body"]).replace("\n", "<br/>")
                img = ""
                if s.get("image") and Path(s["image"]).exists():
                    uri = Path(s["image"]).as_uri()
                    img = f'<img src="{uri}" style="max-width:38%;float:right"/>'
                pages.append(
                    f'<div style="width:100%;height:96vh;border:1px solid #ccc;'
                    f'padding:24px;margin-bottom:12px;page-break-after:always;">'
                    f'<h1>{_html.escape(s["title"])}</h1>{img}<p style="font-size:16pt">{body}</p></div>')
            io_docs.export_pdf_html("".join(pages) or "<p>(empty)</p>", target)
            QMessageBox.information(self, "Exported", f"PDF written to\n{target}")
        except (DocIOError, ValueError) as exc:
            QMessageBox.critical(self, "PDF export failed", str(exc))


# ---------------------------------------------------------------------------
# Office landing page with three sub-launchers
# ---------------------------------------------------------------------------

class OfficePage(QStackedWidget):
    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.writer = WriterEditor(shell)
        self.sheet = SpreadsheetEditor(shell)
        self.deck = PresenterEditor(shell)
        home = self._make_home()
        self.addWidget(home)
        self.addWidget(self.writer)
        self.addWidget(self.sheet)
        self.addWidget(self.deck)
        self._home_widget = home

    def _make_home(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 24, 28, 24)
        title = QLabel("Office")
        title.setStyleSheet("font-size:28px;font-weight:600;")
        sub = QLabel("Lightweight offline editors. Everything is saved locally — no accounts, no cloud.")
        sub.setStyleSheet("color:#5F5F5F;")
        lay.addWidget(title)
        lay.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(16)
        specs = [("📝", "Writer", "Docs with headings, bold/italic, export to PDF. "
                                 "Opens/saves .docx, .txt, .md."),
                 ("📊", "Spreadsheet", "Cells with formulas (=SUM, =AVERAGE…), CSV and .xlsx."),
                 ("🖼", "Presenter", "Slides with text and images, .pptx files, PDF export.")]
        for icon, name, desc in specs:
            b = QPushButton()
            b.setAccessibleName(name)
            b.setMinimumHeight(150)
            b.setMinimumWidth(220)
            b.setStyleSheet(f"QPushButton{{background:{CARD};border:1px solid {BORDER};"
                            "border-radius:8px;text-align:left;padding:14px;}"
                            "QPushButton:hover{border:2px solid " + ACCENT + ";}")
            bl = QVBoxLayout(b)
            ic = QLabel(icon)
            ic.setStyleSheet("font-size:30px;background:transparent;border:none;")
            nm = QLabel(name)
            nm.setStyleSheet("font-size:18px;font-weight:600;background:transparent;border:none;")
            ds = QLabel(desc)
            ds.setWordWrap(True)
            ds.setStyleSheet("color:#5F5F5F;background:transparent;border:none;")
            for x in (ic, nm, ds):
                x.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            bl.addWidget(ic)
            bl.addWidget(nm)
            bl.addWidget(ds)
            target = {"Writer": self.writer, "Spreadsheet": self.sheet,
                      "Presenter": self.deck}[name]
            b.clicked.connect(lambda _=False, t=target: self._open_editor(t))
            row.addWidget(b)
        lay.addLayout(row)
        note = QLabel("Format notes: complex Word/Excel features (tables, charts, macros) are not "
                      "supported; files round-trip plain text, basic styles, formulas and images.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#5F5F5F;")
        lay.addWidget(note)
        lay.addStretch(1)
        return w

    def _open_editor(self, ed: _EditorBase):
        self.setCurrentWidget(ed)
        if not getattr(ed, "_initialized", False):
            ed.make_new()
            ed._initialized = True

    def on_shown(self):
        self.setCurrentWidget(self._home_widget)
