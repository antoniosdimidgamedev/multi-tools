"""Shared pytest fixtures for DeskHub tests.

Tests are headless: Qt is only touched where strictly necessary and with
QT_QPA_PLATFORM=offscreen (set here so `pytest` works out of the box).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------------ GGUF writer
GGUF_TYPE_STRING = 8
GGUF_TYPE_UINT32 = 4
GGUF_TYPE_INT32 = 5
GGUF_TYPE_UINT64 = 18
GGUF_TYPE_BOOL = 7


def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def write_fake_gguf(path, kv: dict, n_tensors: int = 1, version: int = 3) -> None:
    """Write a minimal-but-valid GGUF header (metadata only) for tests."""
    items = b""
    for k, v in kv.items():
        if isinstance(v, str):
            items += _s(k) + struct.pack("<B", GGUF_TYPE_STRING) + _s(v)
        elif isinstance(v, bool):
            items += _s(k) + struct.pack("<B", GGUF_TYPE_BOOL) + struct.pack("<?", v)
        elif isinstance(v, int):
            items += _s(k) + struct.pack("<B", GGUF_TYPE_UINT32) + struct.pack("<I", v)
        else:
            raise TypeError(v)
    data = b"GGUF" + struct.pack("<I", version)
    data += struct.pack("<Q", n_tensors)
    data += struct.pack("<I", len(kv))
    data += items
    # Serialized tensor-info records (name, ndim, dims, dtype, offset) so the
    # parser can walk them like a real GGUF file.
    for i in range(n_tensors):
        tname = f"tensor.{i}.weight".encode()
        data += struct.pack("<Q", len(tname)) + tname
        data += struct.pack("<I", 2)                    # rank 2
        data += struct.pack("<Q", 32) + struct.pack("<Q", 32)   # dims
        data += struct.pack("<I", 1)                    # dtype f32
        if version >= 3:
            data += struct.pack("<Q", i)                # u64 offset
        else:
            data += struct.pack("<I", i)                # u32 offset (v1/v2)
    data += b"\x00" * 64  # fake alignment padding
    with open(path, "wb") as f:
        f.write(data)


@pytest.fixture()
def fake_gguf(tmp_path):
    p = tmp_path / "model.gguf"
    write_fake_gguf(p, {
        "general.name": "Test Model",
        "general.architecture": "llama",
        "tokenizer.chat_template": "{% for m in messages %}{{ m.content }}{% endfor %}",
    })
    return p
