# DeskHub

A Windows 11 launcher app with four offline-first tools: **Downloads** (BitTorrent), **Games** (Minesweeper, Sudoku, Memory Match), **AI Studio** (local GGUF models via llama.cpp), and **Office** (text editor, spreadsheet, presentation).

## Requirements — read this first

- **Python 3.12 (64-bit)** is required. Do **not** use Python 3.14/3.15 preview builds:
  PySide6 and `python3-libtorrent` publish wheels only up to 3.13, so installs will fail or silently skip features on newer versions.
  Download Python 3.12.x from <https://www.python.org/downloads/release/python-31210/> (check “Add python.exe to PATH”).
- Windows 10/11 x64.
- Optional: NVIDIA CUDA + Visual Studio Build Tools for compiling `llama-cpp-python` with GPU support (CPU-only prebuilt wheels also exist; see below).

## Setup

```powershell
cd %USERPROFILE%\multi-tools

# Delete the venv created with the wrong Python, then recreate it with 3.12:
rmdir /s /q .venv
"C:\Program Files\Python312\python.exe" -m venv .venv
.venv\Scripts\activate.bat        # (cmd)  — or Activate.ps1 in PowerShell

python -V                          # must print "Python 3.12.x"
python -m pip install --upgrade pip
pip install -r requirements.txt    # PySide6, libtorrent, office libs, pytest, …

# AI runtime (optional but recommended):
# Simplest reliable option — CPU-only prebuilt wheel:
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
# CUDA variant (needs VS Build Tools + CMake installed):
# pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

If `llama-cpp-python` fails to build from source, DeskHub still runs — AI Studio will report the runtime as unavailable until you install a working wheel.

## Run & test

```powershell
python -m pytest tests -q
python app.py
```

## Build the .exe (must be done on Windows)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --windowed --name DeskHub ^
  --collect-all libtorrent ^
  --collect-binaries llama_cpp ^
  --hidden-import docx --hidden-import openpyxl --hidden-import pptx ^
  --hidden-import reportlab --hidden-import huggingface_hub --hidden-import psutil ^
  app.py
```

Output: `dist\DeskHub\DeskHub.exe` (keep the whole folder together). Add `--onefile` if you prefer a single file (slower startup). Note: the package imported as `libtorrent` comes from the `python3-libtorrent` wheel; PyInstaller collects it under the name `libtorrent`.

Optional installer: point [Inno Setup](https://jrsoftware.org/isinfo.php) at `dist\DeskHub`, or wrap the app folder in an MSIX with `msix pack`.

## Privacy & safety notes

- Downloads: you are responsible for content you download/share. No search or piracy indexes are included. Peer-to-peer means your IP is visible to peers; the app does not share files beyond what BitTorrent requires.
- AI Studio: nothing is sent anywhere. Models run locally; downloads only happen after you explicitly consent, with size shown first.
- Office: standard file dialogs; unsaved-changes prompts prevent data loss.
- Logs (`%APPDATA%\DeskHub\logs`) never record document contents, chat prompts, or downloaded file names.

## Project layout

```
app.py                 entry point
deskhub/shell.py       home page + navigation
deskhub/features/      downloads / games / ai_studio / office modules
tests/                 pytest suite (headless Qt)
packaging/             build helpers
PLAN.md                stack rationale & architecture
```
 
