"""AI Studio page: load a local GGUF model, check compatibility, chat locally.

Consent-first downloads: the optional "Download from Hugging Face" action
queries only public file *metadata* (sizes) via huggingface_hub and shows an
explicit consent dialog with the size before any bytes are transferred.
Inference itself is 100% offline. Chat history stays in memory only.
"""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from deskhub.features.ai_studio.backends import (
    RuntimeInfo, check_compatibility, detect_runtime, read_gguf_metadata,
    validate_repo_id,
)
from deskhub.logging_setup import get_logger
from deskhub.settings import Settings
from deskhub.util import human_size

log = get_logger("ai_studio")


class _WorkerSignals(QWidget):
    """Tiny signal relay so worker threads can touch the UI safely."""
    pass


class AIStudioPage(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings
        self._runtime: RuntimeInfo = detect_runtime()
        self._model_path: Path | None = None
        self._llm = None                       # llama_cpp.Llama instance
        self._busy = False
        self._history: list[dict] = []         # in-memory only, never persisted
        self._pending: dict = {}               # id -> {"text":..,"label":..}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(8)

        rt = QLabel(self._runtime_line())
        rt.setObjectName("runtimeLine")
        rt.setWordWrap(True)
        root.addWidget(rt)
        self._rt_label = rt

        row = QHBoxLayout()
        self.btn_load = QPushButton("Load GGUF model…")
        self.btn_load.setProperty("role", "accent")
        self.btn_load.clicked.connect(self._choose_model)
        self.btn_download = QPushButton("Download a model…")
        self.btn_download.setToolTip("Optional. Shows the size and asks for consent "
                                     "before anything is downloaded.")
        self.btn_download.clicked.connect(self._download_flow)
        self.model_label = QLabel("No model loaded.")
        self.model_label.setStyleSheet("color:#5F5F5F;")
        row.addWidget(self.btn_load)
        row.addWidget(self.btn_download)
        row.addWidget(self.model_label, 1)
        root.addLayout(row)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Context tokens:"))
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(256, 8192)
        self.ctx_spin.setSingleStep(256)
        self.ctx_spin.setValue(1024)
        opts.addWidget(self.ctx_spin)
        opts.addWidget(QLabel("Max reply tokens:"))
        self.n_predict = QSpinBox()
        self.n_predict.setRange(32, 2048)
        self.n_predict.setValue(256)
        opts.addWidget(self.n_predict)
        opts.addStretch(1)
        self.status = QLabel("")
        self.status.setStyleSheet("color:#5F5F5F;")
        opts.addWidget(self.status)
        root.addLayout(opts)

        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Chat output appears here. Nothing you type "
                                     "is saved or sent anywhere.")
        root.addWidget(self.chat, 1)

        inp = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask the model something…  (Enter to send)")
        self.input.setAccessibleName("Prompt input")
        self.send_btn = QPushButton("Send")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        btn_clear = QPushButton("Clear chat")
        btn_clear.clicked.connect(self._clear_chat)
        inp.addWidget(self.input, 1)
        inp.addWidget(self.send_btn)
        inp.addWidget(btn_clear)
        root.addLayout(inp)

        self._done_sig = QTimer(self)
        self._done_sig.setInterval(120)
        self._done_sig.timeout.connect(self._drain)

    # ------------------------------------------------------------------ misc
    def _runtime_line(self) -> str:
        r = self._runtime
        if r.llama_cpp_python and r.cli_binary:
            return f"Local runtime ready: llama-cpp-python + {r.cli_binary}"
        if r.llama_cpp_python:
            return "Local runtime ready: llama-cpp-python."
        if r.cli_binary:
            return (f"CLI runtime found: {r.cli_binary}. Install llama-cpp-python "
                    "for in-app chat.")
        return ("⚠ No local inference runtime installed. " + r.detail)

    def on_shown(self):
        self._runtime = detect_runtime()
        self._rt_label.setText(self._runtime_line())

    # ------------------------------------------------------------ model load
    def _choose_model(self):
        start = self._settings.get("ai_model_dir") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a GGUF model", start, "GGUF models (*.gguf)")
        if not path:
            return
        self._load_model(Path(path))

    def _load_model(self, path: Path):
        meta = read_gguf_metadata(path)
        report = check_compatibility(path, self._runtime)
        text = "\n".join(report.messages)
        if not report.ok:
            box = QMessageBox(self)
            box.setWindowTitle("Compatibility check")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText(text)
            box.setInformativeText(
                "DeskHub will not run this model in its current state. "
                "See README → AI Studio for supported formats and install steps.")
            box.exec()
            return
        if not self._runtime.llama_cpp_python:
            QMessageBox.information(
                self, "Runtime needed",
                "The model passed all checks, but in-app chat needs the "
                "`llama-cpp-python` package:\n\n    pip install llama-cpp-python\n\n"
                "(CPU-only wheels are fine; CUDA builds are faster.)")
            return
        self.model_label.setText(f"{meta.get('general.name', path.name)} · "
                                 f"{human_size(path.stat().st_size)}")
        self._settings.set("ai_model_dir", str(path.parent))
        self._settings.set("ai_last_model", str(path))
        self._model_path = path
        self._start_worker_load(path)

    def _start_worker_load(self, path: Path):
        self._set_busy(True, "Loading model (first load can take a minute)…")
        t = threading.Thread(target=self._worker_load, args=(path,), daemon=True)
        t.start()
        self._done_sig.start()

    def _worker_load(self, path: Path):
        try:
            from llama_cpp import Llama
            llm = Llama(model_path=str(path), n_ctx=self.ctx_spin.value(),
                        verbose=False)
            self._pending["loaded"] = {"ok": True, "llm": llm}
        except Exception as exc:
            log.error("model load failed: %s", type(exc).__name__)
            self._pending["loaded"] = {"ok": False,
                                       "error": f"{type(exc).__name__}: {exc}"[:300]}

    # ------------------------------------------------------------------ chat
    def _send(self):
        text = self.input.text().strip()
        if not text or self._busy or self._llm is None:
            return
        self.input.clear()
        self._append("You", text)
        self._history.append({"role": "user", "content": text})
        self._set_busy(True, "Generating…")
        t = threading.Thread(target=self._worker_chat, daemon=True)
        t.start()
        self._done_sig.start()

    def _worker_chat(self):
        prompt_msgs = self._history[-12:]     # bounded context window
        try:
            resp = self._llm.create_chat_completion(
                messages=prompt_msgs, max_tokens=self.n_predict.value())
            out = resp["choices"][0]["message"]["content"].strip()
            self._pending["reply"] = {"ok": True, "text": out}
        except Exception as exc:
            log.error("inference error: %s", type(exc).__name__)
            self._pending["reply"] = {
                "ok": False,
                "text": f"Model error ({type(exc).__name__}). Try lowering "
                        "context/max tokens or choosing a smaller quantisation."}

    def _drain(self):
        if "loaded" in self._pending:
            res = self._pending.pop("loaded")
            if res["ok"]:
                self._llm = res["llm"]
                self.send_btn.setEnabled(True)
                self._set_busy(False, "Model ready — chat is fully local.")
                self._append("System", "Model loaded. Everything below stays on "
                                       "this computer.")
            else:
                self._set_busy(False, "")
                QMessageBox.critical(self, "Could not load model", res["error"])
        if "reply" in self._pending:
            res = self._pending.pop("reply")
            text = res["text"]
            if res["ok"]:
                self._history.append({"role": "assistant", "content": text})
            self._append("Model", text)
            self._set_busy(False, "")
        if self._pending:
            self._pending.clear()

    def _append(self, who: str, text: str):
        self.chat.appendPlainText(f"{who}:\n{text}\n")
        sb = self.chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_chat(self):
        self.chat.clear()
        self._history.clear()
        self.status.setText("Chat cleared (was only ever in memory).")

    # ------------------------------------------------------------- downloads
    def _download_flow(self):
        repo, ok = QInputDialog_gettext(
            self, "Download a model from Hugging Face",
            "Type a GGUF model repo id, e.g.\nTheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF\n\n"
            "DeskHub will first look up the file sizes and ask again before "
            "downloading anything.")
        if not ok or not repo:
            return
        try:
            repo = validate_repo_id(repo)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid repo id", str(exc))
            return
        self._set_busy(True, "Querying file list (metadata only)…")
        threading.Thread(target=self._query_sizes, args=(repo,), daemon=True).start()
        self._done_sig.start()

    def _query_sizes(self, repo: str):
        try:
            from huggingface_hub import HfApi
            api = HfApi()
            files = api.list_repo_files(repo)
            ggufs = [f for f in files if f.endswith(".gguf")]
            info = {}
            for f in ggufs:
                try:
                    s = api.get_paths_info(repo, paths=[f])
                    size = sum(getattr(x, "size", 0) or 0 for x in s)
                except Exception:
                    size = 0
                info[f] = size
            self._pending["sizes"] = {"ok": True, "files": info}
        except Exception as exc:
            log.error("hf metadata query failed: %s", type(exc).__name__)
            self._pending["sizes"] = {"ok": False,
                                      "error": f"{type(exc).__name__}: {exc}"[:200]}

    def _handle_sizes(self):
        res = self._pending.pop("sizes")
        self._set_busy(False, "")
        if not res["ok"]:
            QMessageBox.warning(self, "Lookup failed",
                                f"Could not reach Hugging Face: {res['error']}\n"
                                "You can still download manually and Load the "
                                ".gguf file here.")
            return
        files = res["files"]
        if not files:
            QMessageBox.information(self, "No GGUF files",
                                    "That repository has no .gguf files.")
            return
        lines = "\n".join(f"• {name}  —  {human_size(size) if size else 'size unknown'}"
                          for name, size in sorted(files.items()))
        total_note = ("\nDownloads resume automatically if interrupted; partial "
                      "data is kept in your cache folder until completed.")
        choice, ok = QInputDialog_gettext(
            self, "Confirm large download",
            f"Files in {files_first_key(files)}:\n{lines}\n\n"
            "⚠ Model files are often several gigabytes and use significant "
            "disk space and bandwidth.\n\n"
            "Type the exact filename you want to download to consent:"
            + total_note)
        if not ok or choice.strip() not in files:
            return
        fname = choice.strip()
        target_dir = self._settings.get("ai_model_dir") or str(Path.home() / "models")
        self._set_busy(True, f"Downloading {fname} … (see progress in status)")
        threading.Thread(target=self._do_download,
                         args=(files_first_key(files), fname, Path(target_dir)),
                         daemon=True).start()
        self._dl_progress_timer.start()

    def _do_download(self, repo: str, fname: str, dest_dir: Path):
        try:
            from huggingface_hub import hf_hub_download
            p = hf_hub_download(repo_id=repo, filename=fname,
                                local_dir=None,  # default HF cache
                                tqdm_class=None)
            dest_dir.mkdir(parents=True, exist_ok=True)
            src = Path(p)
            dst = dest_dir / src.name
            if not dst.exists():
                try:
                    dst.hardlink_to(src)
                except OSError:
                    import shutil
                    shutil.copy2(src, dst)
            self._pending["dl"] = {"ok": True, "path": str(dst)}
        except Exception as exc:
            log.error("download failed: %s", type(exc).__name__)
            self._pending["dl"] = {"ok": False,
                                   "error": f"{type(exc).__name__}: {exc}"[:300]}

    def _handle_dl(self):
        res = self._pending.pop("dl")
        self._dl_progress_timer.stop()
        self._set_busy(False, "")
        if res["ok"]:
            QMessageBox.information(self, "Download complete",
                                    f"Saved to:\n{res['path']}")
            self._load_model(Path(res["path"]))
        else:
            QMessageBox.critical(self, "Download failed", res["error"])

    # ---------------------------------------------------------------- busy
    def _set_busy(self, busy: bool, msg: str):
        self._busy = busy
        for b in (self.btn_load, self.btn_download, self.send_btn):
            b.setEnabled(not busy and (b is not self.send_btn or self._llm is not None))
        self.input.setEnabled(not busy)
        if msg is not None:
            self.status.setText(msg)

    def shutdown(self):
        self._llm = None


def files_first_key(files: dict) -> str:
    return next(iter(sorted(files)))


# QInputDialog wrapper kept separate for testability
def QInputDialog_gettext(parent, title: str, label: str) -> tuple[str, bool]:
    from PySide6.QtWidgets import QInputDialog
    text, ok = QInputDialog.getText(parent, title, label,
                                    QLineEdit.EchoMode.Normal)
    return text, ok
