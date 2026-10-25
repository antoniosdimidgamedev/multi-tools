# DeskHub — Proposed Stack, Architecture & Implementation Plan

## 1. Framework tradeoff analysis (Windows 11 target)

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **WPF (.NET 8)** | Mature, native XAML theming, great packaging (MSIX/self-contained) | C# codebase; no mature maintained pure-C# torrent engine; GGUF runtime needs interop glue | Good, but weak library ecosystem for the two hardest features |
| **WinUI 3** | Most "Windows 11" of all | Rough packaging story, heavier ceremony, same C# ecosystem gaps as WPF | No |
| **Electron** | Rich web UI | ~200 MB footprint, not native-feeling, heavy RAM, awkward Python-lib integration | No |
| **Tauri** | Light | Rust core needed for torrents/AI; slower to build correctly | No |
| **Python 3.12 + PySide6 (Qt 6.7), Fluent-Frameless styling** ✅ | One language across app + all four features; `python-bencode/bt` = actively maintained async BitTorrent 1.0/2.0 lib; `llama-cpp-python` = established GGUF runtime; `python-docx`, `openpyxl`, `python-pptx`, `reportlab` = battle-tested office libs; `qt-material`/Fluent frameless window gives Win11 Mica-like look; `pytest` headless via offscreen Qt; package with PyInstaller on Windows + optional MSIX | Slightly less "pure-native" than WPF | **Selected** |

**Chosen stack:** Python 3.12 · PySide6 · `bt` (BitTorrent) · `llama-cpp-python` (optional extra) · `python-docx` / `openpyxl` / `python-pptx` / `reportlab` · `pytest` · PyInstaller spec for packaging. No accounts, no telemetry, no remote services.

## 2. Architecture

```
deskhub/
  app.py            # QApplication bootstrap, single-window shell, navigation
  shell.py          # Home page with 4 launch tiles + in-app page stack
  theme.py          # Windows 11-ish palette, fluent frameless title bar
  settings.py       # JSON settings in %APPDATA%\DeskHub (download folder, model dir…)
  logging_setup.py  # Rotating file log; NEVER records prompts/documents/file names of user content
  util/             # paths.py (validation/safe-save), human.py
  features/
    downloads/      # bt_engine.py (thin wrapper over `bt`), manager.py (UI), models.py
    games/          # minesweeper.py, sudoku.py, matching.py, store.py (best scores)
    ai_studio/      # backends.py (runtime/hw checks), worker.py (QThread inference), studio.py (UI)
    office/         # text_editor.py, spreadsheet.py, presentation.py, files.py (format IO)
tests/              # pytest suite, headless (QT_QPA_PLATFORM=offscreen)
packaging/deskhub.spec  # PyInstaller
```

Principles: each feature is a self-contained module exposing a QWidget page; all blocking work (torrent I/O, model load/inference, file parsing) runs on QThreads/workers so the UI stays responsive; every external input (magnet strings, .torrent bytes, file paths, model folders) is validated before use.

## 3. Feature plans

- **Downloads:** parse magnet links (info-hash + dn + trackers) and .torrent bencode; add via file picker or paste; pause/resume/cancel; progress, speed, peers from `bt` session stats; configurable download folder (validated, default `%USERPROFILE%\Downloads\DeskHub`). DHT disabled by default → we do not expose the local machine to other peers beyond what an active download requires. Explicit responsibility banner. No search/indexing features ever.
- **Games:** Minesweeper (9×9/16×16 flags+mines), Sudoku (generator/solver/backtracking best-time), Memory Match (emoji pairs, move counter). Instructions dialog, restart buttons, best scores persisted to JSON in APPDATA. Zero network.
- **AI Studio:** pick a folder containing `.gguf` models (or paste HF repo ID → consent screen explaining size/storage before any download, using huggingface_hub when available). Compatibility check (magic header, chat-template metadata), hardware check (RAM/CPU/GPU estimate vs model size), load progress, chat on QThread, clear errors for unsupported model / insufficient memory. Prompts never leave the machine; logs never contain prompt text.
- **Office:** Text editor (DOCX open/save via python-docx, bold/italic/underline/size/font, PDF export via reportlab); Spreadsheet (XLSX via openpyxl, CSV import/export, formula parser supporting `=A1+B2*SUM(A1:A5)` etc.); Presentation (PPTX via python-pptx, add/delete slides, text + image placement, PDF export via reportlab). Unsaved-changes prompts, no silent overwrite (safe-save: refuse existing file unless explicit replace).

## 4. Stages
1. Scaffold + shell/home tiles + settings/logging/util + tests (this pass)
2. Downloads engine + UI + tests
3. Games ×3 + score store + tests
4. AI Studio backend checks + worker + UI + tests
5. Office three editors + format IO + tests
6. Packaging (PyInstaller spec, build script), README polish, full test run, commit

## 5. Delivery note
This environment is Linux without GitHub credentials or a configured remote, so the app is developed/tested here (Qt offscreen) and committed locally; final Windows packaging/push instructions are in README. See README §Packaging.
