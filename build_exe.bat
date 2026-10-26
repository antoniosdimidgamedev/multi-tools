@echo off
REM DeskHub Windows build script. Run from the repository root in cmd.exe:  build_exe.bat
REM Requires Python 3.12 (NOT 3.15). The script uses ONLY py -3.12; it never trusts PATH.

setlocal
chcp 65001 >nul

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] The Python launcher "py" was not found. Install Python 3.12 from python.org.
    pause & exit /b 1
)

py -3.12 --version >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.12 is not installed. Install 3.12.x ^(64-bit^) from python.org.
    echo         Do NOT use Python 3.15: PySide6 and libtorrent have no wheels for it.
    pause & exit /b 1
)

cd /d "%~dp0"

echo [1/5] Recreating virtual environment with Python 3.12...
if exist .venv rmdir /s /q .venv
py -3.12 -m venv .venv
if errorlevel 1 ( echo [ERROR] venv creation failed. & pause & exit /b 1 )

set VPIP=%~dp0.venv\Scripts\python.exe -m pip
"%~dp0.venv\Scripts\python.exe" --version

echo [2/5] Installing dependencies into the venv...
%VPIP% install --upgrade pip || ( echo [ERROR] pip upgrade failed. & pause & exit /b 1 )
%VPIP% install -r requirements.txt || ( echo [ERROR] Dependency install failed. See messages above. & pause & exit /b 1 )
%VPIP% install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu || echo [WARN] llama-cpp-python failed; AI Studio will show a clear runtime error but the rest still works.
%VPIP% install pytest pyinstaller || ( echo [ERROR] pytest/pyinstaller install failed. & pause & exit /b 1 )

echo [3/5] Sanity check imports...
%~dp0.venv\Scripts\python.exe -c "import PySide6, docx, openpyxl, pptx, reportlab, huggingface_hub, psutil; print('core deps OK')" || ( echo [ERROR] Core deps missing - venv is broken. & pause & exit /b 1 )
%~dp0.venv\Scripts\python.exe -c "import libtorrent; print('libtorrent OK', libtorrent.version)" || echo [WARN] libtorrent missing: Downloads feature disabled at runtime.

echo [4/5] Running tests...
%~dp0.venv\Scripts\python.exe -m pytest tests -q
if errorlevel 1 echo [WARN] Some tests failed. Review output; continuing to build.

echo [5/5] Building DeskHub.exe with PyInstaller...
%~dp0.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name DeskHub ^
  --collect-all libtorrent --collect-all PySide6 ^
  --collect-binaries llama_cpp ^
  --hidden-import docx --hidden-import openpyxl --hidden-import pptx ^
  --hidden-import reportlab --hidden-import huggingface_hub --hidden-import psutil ^
  app.py

if exist dist\DeskHub\DeskHub.exe (
    echo.
    echo ============ SUCCESS: %~dp0dist\DeskHub\DeskHub.exe ============
    echo Keep the whole dist\DeskHub folder together when distributing.
) else (
    echo [ERROR] Build did not produce dist\DeskHub\DeskHub.exe. Scroll up for errors.
    exit /b 1
)
pause
