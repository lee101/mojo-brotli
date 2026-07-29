"""ctypes bridge to the Mojo Brotli bindings."""

from __future__ import annotations

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB_PATH = os.path.join(ROOT, "dist", "libmojo-brotli.so")

I = ctypes.c_int64
_SIGNATURES = {
    "mb_encoder_version": ([], I),
    "mb_decoder_version": ([], I),
    "mb_encoder_max_compressed_size": ([I], I),
    "mb_encoder_compress": ([I] * 7, I),
    "mb_encoder_compress_alloc": ([I] * 7, I),
    "mb_encoder_create": ([I] * 4, I),
    "mb_encoder_destroy": ([I], None),
    "mb_encoder_stream": ([I] * 6, I),
    "mb_encoder_has_more_output": ([I], I),
    "mb_encoder_is_finished": ([I], I),
    "mb_decoder_create": ([], I),
    "mb_decoder_destroy": ([I], None),
    "mb_decoder_stream": ([I] * 5, I),
    "mb_decoder_decompress_alloc": ([I] * 4, I),
    "mb_free": ([I], None),
    "mb_decoder_is_finished": ([I], I),
    "mb_decoder_error_code": ([I], I),
}


class LibraryError(RuntimeError):
    pass


_library: ctypes.CDLL | None = None


class _PyBuffer(ctypes.Structure):
    _fields_ = [
        ("buf", ctypes.c_void_p),
        ("obj", ctypes.c_void_p),
        ("length", ctypes.c_ssize_t),
        ("itemsize", ctypes.c_ssize_t),
        ("readonly", ctypes.c_int),
        ("ndim", ctypes.c_int),
        ("format", ctypes.c_char_p),
        ("shape", ctypes.POINTER(ctypes.c_ssize_t)),
        ("strides", ctypes.POINTER(ctypes.c_ssize_t)),
        ("suboffsets", ctypes.POINTER(ctypes.c_ssize_t)),
        ("internal", ctypes.c_void_p),
    ]


_get_buffer = ctypes.pythonapi.PyObject_GetBuffer
_get_buffer.argtypes = [ctypes.py_object, ctypes.POINTER(_PyBuffer), ctypes.c_int]
_get_buffer.restype = ctypes.c_int
_release_buffer = ctypes.pythonapi.PyBuffer_Release
_release_buffer.argtypes = [ctypes.POINTER(_PyBuffer)]
_release_buffer.restype = None


class _BufferLease:
    def __init__(self, data):
        self.view = _PyBuffer()
        _get_buffer(data, ctypes.byref(self.view), 0)

    def __del__(self):
        if self.view.obj:
            _release_buffer(ctypes.byref(self.view))


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        if not os.path.exists(LIB_PATH):
            raise LibraryError("shared library is missing; run `pixi run build`")
        _library = ctypes.CDLL(LIB_PATH)
        for name, (argtypes, restype) in _SIGNATURES.items():
            function = getattr(_library, name)
            function.argtypes = argtypes
            function.restype = restype
    return _library


def as_bytes(data) -> bytes | memoryview:
    if isinstance(data, bytes):
        return data
    try:
        view = memoryview(data)
    except TypeError as exc:
        raise TypeError("brotli: data must be a C-contiguous buffer") from exc
    if view.ndim != 1 or not view.c_contiguous:
        raise TypeError("brotli: data must be a C-contiguous buffer")
    return view.cast("B")


def buffer_address(data: bytes | memoryview) -> tuple[int, int, object]:
    size = len(data)
    if isinstance(data, bytes):
        storage = data or b"\0"
        keepalive = ctypes.c_char_p(storage)
        address = ctypes.cast(keepalive, ctypes.c_void_p).value or 0
        return address, size, keepalive
    if not size:
        storage = b"\0"
        keepalive = ctypes.c_char_p(storage)
        address = ctypes.cast(keepalive, ctypes.c_void_p).value or 0
        return address, 0, (data, keepalive)
    if data.readonly:
        keepalive = _BufferLease(data)
        return keepalive.view.buf or 0, size, keepalive
    keepalive = ctypes.c_ubyte.from_buffer(data)
    return ctypes.addressof(keepalive), size, (data, keepalive)


def writable_buffer(size: int) -> tuple[bytearray, int, object]:
    storage = bytearray(max(1, size))
    keepalive = ctypes.c_ubyte.from_buffer(storage)
    return storage, ctypes.addressof(keepalive), keepalive
