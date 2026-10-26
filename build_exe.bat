@echo off
REM DeskHub Windows build script. Run from the repository root in cmd.exe.
REM Requires Python 3.12 (NOT 3.15) on PATH as "py -3.12".

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] The Python launcher "py" was not found. Install Python 3.12 from python.org.
    exit /b 1
)

py -3.12 -c "print" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 is not installed. Install it from python.org and check "Add to PATH".
    echo         Do NOT use Python 3.15: PySide6 and python3-libtorrent have no wheels for it.
    exit /b 1
)

if not exist .venv (
    echo [1/4] Creating virtual environment with Python 3.12...
    py -3.12 -m venv .venv
)

echo [2/4] Activating venv and installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
pip install pytest pyinstaller

echo [3/4] Running tests...
python -m pytest tests -q
if errorlevel 1 (
    echo [WARN] Some tests failed. Continuing anyway; review output above.
)

echo [4/4] Building DeskHub.exe with PyInstaller...
pyinstaller --noconfirm --clean --windowed --name DeskHub ^
  --collect-all libtorrent --collect-all PySide6 ^
  --collect-binaries llama_cpp ^
  --hidden-import docx --hidden-import openpyxl --hidden-import pptx ^
  --hidden-import reportlab --hidden-import huggingface_hub --hidden-import psutil ^
  app.py

if exist dist\DeskHub\DeskHub.exe (
    echo.
    echo SUCCESS: dist\DeskHub\DeskHub.exe
    echo Keep the whole dist\DeskHub folder together when distributing.
) else (
    echo [ERROR] Build did not produce dist\DeskHub\DeskHub.exe. Scroll up for errors.
    exit /b 1
)
pause
