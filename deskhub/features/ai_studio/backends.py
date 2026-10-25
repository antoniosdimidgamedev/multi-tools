"""Local inference backends + hardware/compatibility checks for AI Studio.

Supported formats (documented in README):
* GGUF quantised models (llama.cpp ecosystem) — preferred.
  * via `llama-cpp-python` if the user installed it, or
  * via a user-supplied `llama-cli` / `llama-server` binary on PATH.

Nothing here ever contacts a remote service during inference. Model
downloads are only possible through an explicit, consented action that
explains size first (see studio.py → huggingface_hub metadata query).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


# ------------------------------------------------------------------ GGUF parse
GGUF_MAGIC = b"GGUF"


def read_gguf_metadata(path: str | Path, max_kv: int = 400) -> dict:
    """Parse the KV-metadata header of a GGUF v1–v3 file.

    Returns {"valid": bool, "version": int, "n_tensors": int,
             "general.name": ..., "chat_template": ..., "size_bytes": ...}
    Never raises for non-GGUF files; returns valid=False with a reason.
    """
    out: dict = {"valid": False, "reason": "", "size_bytes": 0}
    p = Path(str(path))
    if not p.is_file():
        out["reason"] = "File does not exist."
        return out
    out["size_bytes"] = p.stat().st_size
    try:
        with p.open("rb") as f:
            if f.read(4) != GGUF_MAGIC:
                out["reason"] = "Not a GGUF file (bad magic)."
                return out
            version = int.from_bytes(f.read(4), "little")
            if version not in (1, 2, 3):
                out["reason"] = f"Unsupported GGUF version {version}."
                return out
            n_tensors = int.from_bytes(f.read(8), "little")
            kv_count = int.from_bytes(f.read(4), "little")
            out["version"] = version
            out["n_tensors"] = n_tensors
            kv = {}

            def read_bytes_exact(n: int) -> bytes:
                """Return exactly n bytes or raise (EOF-safe against truncated files)."""
                raw = f.read(n)
                if len(raw) != n:
                    raise ValueError("truncated GGUF header")
                return raw

            def read_u64() -> int:
                return int.from_bytes(read_bytes_exact(8), "little")

            def read_str() -> str:
                ln = read_u64()
                if ln > 1_000_000:
                    raise ValueError("string too long")
                return read_bytes_exact(ln).decode("utf-8", errors="replace")

            TYPE_UINT8, TYPE_INT8, TYPE_UINT16, TYPE_INT16, TYPE_UINT32, \
                TYPE_INT32, TYPE_FLOAT32, TYPE_BOOL, TYPE_STRING, TYPE_ARRAY, \
                TYPE_UINT64, TYPE_INT64, TYPE_FLOAT64 = range(13)

            def read_scalar(t):
                if t == TYPE_BOOL:
                    return read_bytes_exact(1) == b"\x01"
                if t == TYPE_STRING:
                    return read_str()
                sizes = {TYPE_UINT8: (1, False), TYPE_INT8: (1, True),
                         TYPE_UINT16: (2, False), TYPE_INT16: (2, True),
                         TYPE_UINT32: (4, False), TYPE_INT32: (4, True),
                         TYPE_FLOAT32: (4, "f"),
                         TYPE_UINT64: (8, False), TYPE_INT64: (8, True),
                         TYPE_FLOAT64: (8, "d")}
                n, signed = sizes[t]
                raw = read_bytes_exact(n)
                if signed == "f":
                    import struct
                    return struct.unpack("<f", raw)[0]
                if signed == "d":
                    import struct
                    return struct.unpack("<d", raw)[0]
                return int.from_bytes(raw, "little", signed=bool(signed))

            for _ in range(min(kv_count, max_kv)):
                key = read_str()
                vtype = int.from_bytes(read_bytes_exact(1), "little")
                if vtype == TYPE_ARRAY:
                    elem = int.from_bytes(read_bytes_exact(1), "little")
                    cnt = read_u64()
                    if cnt > 1_000_000:
                        raise ValueError("array too long")
                    if elem == TYPE_ARRAY:
                        raise ValueError("nested arrays unsupported")
                    items = []
                    scan = min(cnt, 512)          # cap stored items
                    for i in range(cnt):
                        v = read_scalar(elem)
                        if i < scan:
                            items.append(v)
                    kv[key] = items
                elif vtype in range(13):
                    kv[key] = read_scalar(vtype)
                else:
                    raise ValueError(f"unknown gguf value type {vtype}")
            if len(kv) != kv_count:
                raise ValueError("truncated header")
            # Tensor-info section: walk it so a file truncated mid-header is
            # detected (read_bytes_exact raises), not silently accepted.
            for _t in range(n_tensors):
                read_str()                                   # tensor name
                nd = int.from_bytes(read_bytes_exact(4), "little")
                if nd > 16:
                    raise ValueError("implausible tensor rank")
                for _d in range(nd):
                    read_u64()                               # dims
                read_bytes_exact(4)                          # dtype
                read_u64() if version >= 3 else read_bytes_exact(4)  # offset
            out.update(kv)
            out["valid"] = True
    except Exception as exc:
        out["reason"] = f"Could not fully parse GGUF header: {type(exc).__name__}"
        # partial metadata may still be useful
        out.setdefault("version", None)
    return out


def sys_little(raw: bytes) -> bool:
    import sys
    return sys.byteorder == "little"


# ------------------------------------------------------------------ runtimes
@dataclass
class RuntimeInfo:
    llama_cpp_python: bool = False
    cli_binary: str | None = None      # e.g. "llama-cli"
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.llama_cpp_python or bool(self.cli_binary)

    @property
    def name(self) -> str:
        """Human-readable runtime label (for UI display)."""
        if self.llama_cpp_python:
            return "llama-cpp-python"
        if self.cli_binary:
            return Path(self.cli_binary).name
        return ""


def detect_runtime() -> RuntimeInfo:
    info = RuntimeInfo()
    try:
        import llama_cpp  # noqa: F401
        info.llama_cpp_python = True
        info.detail = "llama-cpp-python found."
    except ImportError:
        pass
    for cand in ("llama-cli", "llama-cli.exe", "llama", "llama-server"):
        w = shutil.which(cand)
        if w:
            info.cli_binary = w
            info.detail = (info.detail + " " + f"{cand} on PATH.").strip()
            break
    if not info.available:
        info.detail = ("No local runtime found. Install one of: "
                       "pip install llama-cpp-python, or put llama-cli on PATH.")
    return info


# ------------------------------------------------------------------ hardware
def total_ram_bytes() -> int:
    try:
        import psutil
        return psutil.virtual_memory().total
    except ImportError:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 0


def gpu_free_mib() -> int | None:
    """Best-effort NVIDIA VRAM check via nvidia-smi; None if unavailable."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=4)
        if r.returncode == 0:
            vals = [int(x.strip()) for x in r.stdout.splitlines() if x.strip()]
            return max(vals) if vals else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


@dataclass
class CompatReport:
    ok: bool
    messages: list[str]
    estimated_ram_bytes: int = 0


def estimate_model_ram(model_path: str | Path) -> int:
    """Rough RAM need: file size + ~40% context/compute overhead, min 1 GiB."""
    size = Path(str(model_path)).stat().st_size
    return int(size * 1.4) + (1 << 30) // 2


def check_compatibility(model_path: str | Path, runtime: RuntimeInfo) -> CompatReport:
    msgs: list[str] = []
    ok = True
    meta = read_gguf_metadata(model_path)
    if not meta.get("valid"):
        return CompatReport(False, [meta.get("reason") or
                                    "This file is not a readable GGUF model."])
    name = meta.get("general.name") or Path(str(model_path)).stem
    msgs.append(f"Model: {name} (GGUF v{meta.get('version')}, "
                f"{meta.get('n_tensors', '?')} tensors, "
                f"{Path(str(model_path)).stat().st_size / 2**20:.0f} MiB on disk)")
    if not meta.get("tokenizer.chat_template") and not meta.get("general.chat_template"):
        msgs.append("No chat template embedded — completions will use plain prompt style.")
    if not runtime.available:
        return CompatReport(False, msgs + ["No local inference runtime is installed. "
                                           "See README → AI Studio requirements."])
    est = estimate_model_ram(model_path)
    ram = total_ram_bytes()
    if ram and est > ram * 0.85:
        ok = False
        msgs.append(f"Not enough memory: this model needs roughly "
                    f"{est / 2**30:.1f} GiB but the system has only "
                    f"{ram / 2**30:.1f} GiB total. Use a smaller quantisation "
                    "(e.g. Q4_K_M) or a smaller model.")
    else:
        msgs.append(f"Estimated RAM need ≈ {est / 2**30:.1f} GiB "
                    f"(system total {ram / 2**30:.1f} GiB).")
    gpu = gpu_free_mib()
    if gpu is not None:
        msgs.append(f"NVIDIA GPU free VRAM: {gpu} MiB "
                    "(offload will be attempted automatically by the runtime).")
    return CompatReport(ok, msgs, est)


# ------------------------------------------------------------------ HF sizes
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9._-]+)+$")


def validate_repo_id(repo_id: str) -> str:
    repo_id = (repo_id or "").strip()
    if not repo_id or len(repo_id) > 200:
        raise ValueError("Repo id must look like 'organization/model-name'.")
    if not _HF_REPO_RE.match(repo_id) or ".." in repo_id:
        raise ValueError("Repo id must look like 'organization/model-name'.")
    return repo_id
