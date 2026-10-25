"""Round-trip tests for Office document IO (docx/xlsx/csv/pptx).

PDF export needs a QApplication and is covered in test_gui_smoke.py.
"""
import pytest

from deskhub.features.office import io_docs as io
from deskhub.features.office.logic import SheetModel


BLOCKS = [
    {"text": "Title Here", "heading": 1, "bold": True, "italic": False,
     "size_pt": 0, "align": "center"},
    {"text": "Normal paragraph.", "heading": 0, "bold": False, "italic": True,
     "size_pt": 12, "align": "left"},
]


class TestWriter:
    def test_docx_roundtrip(self, tmp_path):
        p = tmp_path / "doc.docx"
        io.writer_save(BLOCKS, p)
        assert p.is_file() and p.stat().st_size > 0
        back = io.writer_load(p)
        assert any(b["text"] == "Title Here" for b in back)
        assert any("Normal paragraph." in b["text"] for b in back)

    def test_txt_export_contains_text(self, tmp_path):
        p = tmp_path / "doc.txt"
        io.writer_save(BLOCKS, p)
        text = p.read_text(encoding="utf-8")
        assert "Title Here" in text and "Normal paragraph." in text

    def test_unknown_extension_rejected(self, tmp_path):
        with pytest.raises(io.DocIOError, match="cannot save"):
            io.writer_save(BLOCKS, tmp_path / "x.ods")

    def test_missing_folder_error(self, tmp_path):
        with pytest.raises(io.DocIOError):
            io.writer_save(BLOCKS, tmp_path / "nope" / "a.docx")

    def test_load_nonexistent_raises_user_error(self, tmp_path):
        with pytest.raises(io.DocIOError):
            io.writer_load(tmp_path / "ghost.docx")


class TestSheet:
    def test_xlsx_roundtrip_with_formula(self, tmp_path):
        m = SheetModel()
        m.set_raw(0, 0, "10")
        m.set_raw(1, 0, "32")
        m.set_raw(2, 0, "=SUM(A1:A2)")
        p = tmp_path / "b.xlsx"
        io.sheet_save(m, p)
        m2 = io.sheet_load(p)
        assert m2.get_raw(2, 0) == "=SUM(A1:A2)"
        vals = m2.evaluate_all()
        assert vals[(2, 0)] == 42.0

    def test_csv_roundtrip(self, tmp_path):
        m = SheetModel()
        m.set_raw(0, 0, "hello, world")
        m.set_raw(0, 1, "5")
        p = tmp_path / "s.csv"
        io.sheet_save(m, p)
        m2 = io.sheet_load(p)
        assert m2.get_raw(0, 0) == "hello, world"
        assert float(m2.evaluate_all()[(0, 1)]) == 5.0

    def test_corrupt_xlsx_gives_clear_error(self, tmp_path):
        p = tmp_path / "bad.xlsx"
        p.write_bytes(b"not really a xlsx")
        with pytest.raises(io.DocIOError, match="not a readable spreadsheet"):
            io.sheet_load(p)

    def test_unsupported_open_ext(self, tmp_path):
        p = tmp_path / "x.pdf"
        p.write_bytes(b"%PDF-1.4")
        with pytest.raises(io.DocIOError, match="cannot open"):
            io.sheet_load(p)


class TestPresenter:
    SLIDES = [
        {"title": "DeskHub", "body": "Offline presentations", "image": None,
         "layout": "title"},
        {"title": "Points", "body": "One\nTwo\nThree", "image": None,
         "layout": "content"},
    ]

    def test_pptx_roundtrip(self, tmp_path):
        p = tmp_path / "deck.pptx"
        io.presenter_save(self.SLIDES, p)
        assert p.is_file() and p.stat().st_size > 0
        back = io.presenter_load(p)
        assert len(back) == 2
        assert back[0]["title"] == "DeskHub"
        assert "Two" in back[1]["body"]

    def test_wrong_ext_rejected(self, tmp_path):
        with pytest.raises(io.DocIOError, match="pptx"):
            io.presenter_save(self.SLIDES, tmp_path / "deck.odp")

    def test_image_embedded(self, tmp_path):
        img = tmp_path / "pic.png"
        # 1x1 red PNG
        img.write_bytes(bytes.fromhex(
            "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
            "de0000000c4944415408d763f8c0000003010100" "18dd8b0000000049454e44ae426082"))
        slides = [{"title": "With image", "body": "", "image": str(img),
                   "layout": "content"}]
        p = tmp_path / "img.pptx"
        io.presenter_save(slides, p)
        assert p.stat().st_size > 5000  # pptx skeleton + embedded png
