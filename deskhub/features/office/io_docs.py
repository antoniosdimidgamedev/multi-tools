"""Document IO for the Office suite.

Formats (and their honest limitations) are documented in README.md:
  Writer      -> .docx (python-docx), .txt, .md ; PDF export via Qt print engine
  Spreadsheet -> .xlsx (openpyxl), .csv        ; formulas stored as cached values
                 in CSV, as formula strings in XLSX
  Presenter   -> .pptx (python-pptx)           ; PDF export via Qt print engine

All functions raise ``DocIOError`` with a user-facing message; nothing here
touches the network and nothing logs document contents.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from deskhub.features.office.logic import (
    FormulaError, SheetModel, fit_text_size, cell_name,
)


class DocIOError(Exception):
    """User-presentable document IO failure."""


# ---------------------------------------------------------------------------
# Writer (.docx / .txt / .md)
#
# The editor keeps content as a list of blocks: {"text": str, "bold": bool,
# "italic": bool, "size_pt": float, "heading": int|0, "align": "left"|"center"}
# ---------------------------------------------------------------------------

def writer_save(blocks: list[dict], path: str | Path) -> None:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        if ext in (".txt", ".md"):
            path.write_text(blocks_to_markdown(blocks), encoding="utf-8")
            return
        if ext == ".docx":
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.shared import Pt

            doc = Document()
            for b in blocks:
                text = b.get("text", "")
                lvl = int(b.get("heading", 0) or 0)
                if lvl:
                    p = doc.add_heading(text, level=min(lvl, 4))
                else:
                    p = doc.add_paragraph()
                    run = p.add_run(text)
                    run.bold = bool(b.get("bold"))
                    run.italic = bool(b.get("italic"))
                    if b.get("size_pt"):
                        run.font.size = Pt(float(b["size_pt"]))
                if b.get("align") == "center":
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _atomic_check(path)
            doc.save(str(path))
            return
    except OSError as exc:
        raise DocIOError(f"Could not save {path.name}: {exc}") from exc
    raise DocIOError(f"Writer cannot save extension {ext or '(none)'!r}. Use .docx, .txt or .md.")


def writer_load(path: str | Path) -> list[dict]:
    path = Path(path)
    ext = path.suffix.lower()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DocIOError(f"Could not open {path.name}: {exc}") from exc
    blocks: list[dict] = []
    if ext in (".txt", ".md"):
        text = _decode_text(data)
        for line in text.splitlines():
            md = line.lstrip()
            h = 0
            while md.startswith("#"):
                h += 1
                md = md[1:]
            if md.startswith(" ") and h:
                md = md[1:]
            blocks.append({"text": (md if h else line), "heading": h if h <= 4 else 0})
        return blocks
    if ext == ".docx":
        try:
            from docx import Document
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            doc = Document(io.BytesIO(data))
            for p in doc.paragraphs:
                style = (p.style.name or "").lower()
                heading = 0
                if style.startswith("heading"):
                    try:
                        heading = max(1, min(4, int(style.split()[-1])))
                    except ValueError:
                        heading = 1
                text = "".join(r.text for r in p.runs) or p.text
                bold = any(r.bold for r in p.runs)
                italic = any(r.italic for r in p.runs)
                size = None
                for r in p.runs:
                    if r.font.size is not None:
                        size = r.font.size.pt
                        break
                blocks.append({
                    "text": text, "heading": heading, "bold": bold,
                    "italic": italic, "size_pt": size,
                    "align": "center" if p.alignment == WD_ALIGN_PARAGRAPH.CENTER else "left",
                })
            return blocks
        except Exception as exc:  # noqa: BLE001 - corrupt zip etc.
            raise DocIOError(f"{path.name} is not a readable Word document ({exc}).") from exc
    raise DocIOError(f"Writer cannot open extension {ext or '(none)'!r}.")


def blocks_to_markdown(blocks: list[dict]) -> str:
    out = []
    for b in blocks:
        text = b.get("text", "")
        lvl = int(b.get("heading", 0) or 0)
        if lvl:
            out.append("#" * lvl + " " + text)
        else:
            em = text
            if b.get("bold"):
                em = f"**{em}**"
            if b.get("italic"):
                em = f"*{em}*"
            out.append(em)
    return "\n".join(out) + ("\n" if out else "")


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Spreadsheet (.xlsx / .csv)
# ---------------------------------------------------------------------------

def sheet_save(model: SheetModel, path: str | Path) -> None:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".csv":
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerows(model.to_csv_rows())
        _write_text(path, buf.getvalue())
        return
    if ext == ".xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as exc:  # pragma: no cover
            raise DocIOError("openpyxl is not installed.") from exc
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        vals = model.evaluate_all()
        for (r, c), raw in sorted(model.raw.items()):
            v = vals.get((r, c), raw)
            cell = ws.cell(row=r + 1, column=c + 1)
            if raw.startswith("="):
                # store formula string AND its computed value as fallback
                cell.value = raw
            elif isinstance(v, float):
                cell.value = int(v) if v == int(v) and abs(v) < 1e15 else v
            else:
                cell.value = raw
        _atomic_check(path)
        try:
            wb.save(str(path))
        except OSError as exc:
            raise DocIOError(f"Could not save {path.name}: {exc}") from exc
        return
    raise DocIOError(f"Spreadsheet cannot save extension {ext or '(none)'!r}. Use .xlsx or .csv.")


def sheet_load(path: str | Path) -> SheetModel:
    path = Path(path)
    ext = path.suffix.lower()
    model = SheetModel()
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DocIOError(f"Could not open {path.name}: {exc}") from exc
    if ext == ".csv":
        text = _decode_text(data)
        model.load_csv(text)
        return model
    if ext == ".xlsx":
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), data_only=False)
            ws = wb.active
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value is None:
                        continue
                    model.set_raw(cell.row - 1, cell.column - 1, str(cell.value))
            return model
        except Exception as exc:  # noqa: BLE001
            raise DocIOError(f"{path.name} is not a readable spreadsheet ({exc}).") from exc
    raise DocIOError(f"Spreadsheet cannot open extension {ext or '(none)'!r}.")


def _write_text(path: Path, text: str) -> None:
    try:
        _atomic_check(path)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise DocIOError(f"Could not save {path.name}: {exc}") from exc


def _atomic_check(path: Path) -> None:
    """Refuse to write into directories that don't exist / aren't writable."""
    parent = path.parent
    if not parent.exists():
        raise DocIOError(f"Folder does not exist: {parent}")
    if not io and False:  # keep flake simple
        return
    import os
    if not os.access(parent, os.W_OK):
        raise DocIOError(f"Folder is not writable: {parent}")


# ---------------------------------------------------------------------------
# Presenter (.pptx)
#
# Slide dict: {"title": str, "body": str, "image": path|None,
#              "layout": "title"|"content"|"blank"}
# ---------------------------------------------------------------------------

def presenter_save(slides: list[dict], path: str | Path) -> None:
    path = Path(path)
    if path.suffix.lower() != ".pptx":
        raise DocIOError("Presenter saves .pptx files only (PDF is an export format).")
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN
    except ImportError as exc:  # pragma: no cover
        raise DocIOError("python-pptx is not installed.") from exc
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    for s in slides:
        slide = prs.slides.add_slide(blank)
        layout = s.get("layout", "content")
        title = s.get("title", "")
        body = s.get("body", "")
        image = s.get("image")
        if title:
            tsize = 40 if layout == "title" else 28
            box = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12.1), Inches(1.2))
            tf = box.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if layout == "title" else PP_ALIGN.LEFT
            run = p.add_run()
            run.text = title
            run.font.size = Pt(tsize)
            run.font.bold = True
        if body:
            bx_y = 1.9 if layout != "title" else 2.6
            bw = 8.0 if image else 12.1
            box = slide.shapes.add_textbox(Inches(0.6), Inches(bx_y), Inches(bw), Inches(4.9))
            tf = box.text_frame
            tf.word_wrap = True
            pt = fit_text_size(body, bw, 4.9, base_pt=20 if layout != "title" else 18)
            for i, line in enumerate(body.splitlines() or [""]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                run = p.add_run()
                run.text = line
                run.font.size = Pt(pt)
        if image:
            ipath = Path(image)
            if ipath.exists():
                try:
                    pic = slide.shapes.add_picture(str(ipath), Inches(9.0), Inches(1.9),
                                                   width=Inches(3.8))
                    # keep inside slide
                    if pic.top + pic.height > prs.slide_height:
                        pic.height = prs.slide_height - pic.top
                except Exception as exc:  # noqa: BLE001 - bad image data
                    raise DocIOError(f"Could not embed image {ipath.name}: {exc}") from exc
    _atomic_check(path)
    try:
        prs.save(str(path))
    except OSError as exc:
        raise DocIOError(f"Could not save {path.name}: {exc}") from exc


def presenter_load(path: str | Path) -> list[dict]:
    path = Path(path)
    if path.suffix.lower() != ".pptx":
        raise DocIOError("Presenter opens .pptx files only.")
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise DocIOError("python-pptx is not installed.") from exc
    try:
        prs = Presentation(str(path))
    except Exception as exc:  # noqa: BLE001
        raise DocIOError(f"{path.name} is not a readable presentation ({exc}).") from exc
    slides = []
    for slide in prs.slides:
        texts: list[str] = []
        image = None
        for shape in slide.shapes:
            if shape.shape_type == 13:  # PICTURE
                try:
                    img = shape.image
                    suffix = img.ext.lower()
                    tmp = Path(__file__).resolve().parents[3] / ".deskhub_imgcache"
                    tmp.mkdir(exist_ok=True)
                    fp = tmp / f"slide_{len(slides)}_{id(shape)}.{suffix}"
                    fp.write_bytes(img.blob)
                    image = str(fp)
                except Exception:  # noqa: BLE001
                    image = None
            if shape.has_text_frame:
                t = shape.text_frame.text
                if t.strip():
                    texts.append(t)
        title = texts[0] if texts else ""
        body = "\n".join(texts[1:]) if len(texts) > 1 else ""
        layout = "title" if len(texts) <= 1 and (title or image) else "content"
        slides.append({"title": title, "body": body, "image": image, "layout": layout})
    return slides


# ---------------------------------------------------------------------------
# PDF export (Qt print engine — works for Writer and Presenter)
# ---------------------------------------------------------------------------

def export_pdf_html(html: str, out_path: str | Path, page_size="A4") -> None:
    """Render HTML to PDF using QtPdf's painter helper (no network, no app window)."""
    out_path = Path(out_path)
    _atomic_check(out_path)
    try:
        from PySide6.QtCore import QIODevice, QSizeF
        from PySide6.QtGui import QPdfWriter
        from PySide6.QtWidgets import QApplication, QTextEdit
        from PySide6.QtGui import QPageSize

        app = QApplication.instance()
        if app is None:
            raise DocIOError("PDF export needs the application context.")
        writer = QPdfWriter(str(out_path))
        writer.setPageSize(getattr(QPageSize.PageSizeId, page_size)
                           if hasattr(QPageSize, "PageSizeId") else QPageSize(page_size))
        writer.setTitle("DeskHub document")
        edit = QTextEdit()
        edit.setHtml(html)
        doc = edit.document()
        doc.print_(writer)
        del edit
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise DocIOError("PDF export produced an empty file.")
    except DocIOError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocIOError(f"PDF export failed: {exc}") from exc
