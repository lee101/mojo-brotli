"""Python API compatible with the Brotli package, backed by Mojo."""

from __future__ import annotations

import ctypes
import operator

from ._lib import as_bytes, buffer_address, lib, writable_buffer

MODE_GENERIC = 0
MODE_TEXT = 1
MODE_FONT = 2

_PROCESS = 0
_FLUSH = 1
_FINISH = 2
_DECODER_ERROR = 0
_DECODER_SUCCESS = 1
_DECODER_NEEDS_MORE_INPUT = 2
_DECODER_NEEDS_MORE_OUTPUT = 3
_STREAM_BUFFER_SIZE = 32768


class error(Exception):
    """An error occurred in the Brotli implementation."""


def _byte_integer(value) -> int:
    integer = operator.index(value)
    if integer < 0:
        raise OverflowError("unsigned byte integer is less than minimum")
    if integer > 255:
        raise OverflowError("unsigned byte integer is greater than maximum")
    return integer


def _settings(mode, quality, lgwin, lgblock) -> tuple[int, int, int, int]:
    mode = _byte_integer(mode)
    quality = _byte_integer(quality)
    lgwin = _byte_integer(lgwin)
    lgblock = _byte_integer(lgblock)
    if mode not in (MODE_GENERIC, MODE_TEXT, MODE_FONT):
        raise error("brotli: invalid mode")
    if quality > 11:
        raise error("brotli: invalid quality; range is 0 to 11")
    if not 10 <= lgwin <= 24:
        raise error("brotli: invalid lgwin; range is 10 to 24")
    if lgblock != 0 and not 16 <= lgblock <= 24:
        raise error("brotli: invalid lgblock; range is 16 to 24, or 0")
    return mode, quality, lgwin, lgblock


def _version_string(number: int) -> str:
    return f"{number >> 24}.{(number >> 12) & 0xfff}.{number & 0xfff}"


_encoder_version = int(lib().mb_encoder_version())
_decoder_version = int(lib().mb_decoder_version())
if _encoder_version != _decoder_version:
    raise ImportError("linked Brotli encoder and decoder versions differ")
version = _version_string(_encoder_version)
__version__ = version


def compress(string, mode=MODE_GENERIC, quality=11, lgwin=22, lgblock=0):
    """Compress a C-contiguous bytes-like object."""
    mode, quality, lgwin, lgblock = _settings(mode, quality, lgwin, lgblock)
    source = as_bytes(string)
    if lgblock or len(source) == 0:
        compressor = Compressor(mode, quality, lgwin, lgblock)
        return compressor.process(source) + compressor.finish()
    source_address, source_size, source_keepalive = buffer_address(source)
    encoded_address = ctypes.c_void_p()
    encoded_size = ctypes.c_size_t()
    try:
        succeeded = lib().mb_encoder_compress_alloc(
            quality,
            lgwin,
            mode,
            source_size,
            source_address,
            ctypes.addressof(encoded_address),
            ctypes.addressof(encoded_size),
        )
        _ = source_keepalive
        if not succeeded:
            raise error("brotli: compressor failed")
        return ctypes.string_at(encoded_address.value, encoded_size.value)
    finally:
        if encoded_address.value:
            lib().mb_free(encoded_address.value)


class Compressor:
    """Incremental Brotli compressor."""

    def __init__(self, mode=MODE_GENERIC, quality=11, lgwin=22, lgblock=0):
        mode, quality, lgwin, lgblock = _settings(mode, quality, lgwin, lgblock)
        self._state = int(lib().mb_encoder_create(mode, quality, lgwin, lgblock))
        if not self._state:
            raise error("brotli: failed to create encoder")
        self._finished = False
        self._healthy = True

    def _close(self):
        state, self._state = getattr(self, "_state", 0), 0
        if state:
            lib().mb_encoder_destroy(state)

    def __del__(self):
        self._close()

    def _fail(self, message):
        self._healthy = False
        self._close()
        raise error(message)

    def _run(self, data: bytes, operation: int) -> bytes:
        source_address, source_size, source_keepalive = buffer_address(data)
        available_input = ctypes.c_size_t(source_size)
        next_input = ctypes.c_void_p(source_address)
        pieces = []
        while True:
            destination, destination_address, destination_keepalive = writable_buffer(
                _STREAM_BUFFER_SIZE
            )
            available_output = ctypes.c_size_t(_STREAM_BUFFER_SIZE)
            next_output = ctypes.c_void_p(destination_address)
            succeeded = lib().mb_encoder_stream(
                self._state,
                operation,
                ctypes.addressof(available_input),
                ctypes.addressof(next_input),
                ctypes.addressof(available_output),
                ctypes.addressof(next_output),
            )
            produced = _STREAM_BUFFER_SIZE - available_output.value
            if produced:
                pieces.append(bytes(memoryview(destination)[:produced]))
            _ = destination_keepalive
            if not succeeded:
                self._fail("brotli: encoder failed")
            if operation == _FINISH:
                if lib().mb_encoder_is_finished(self._state):
                    break
            elif (
                available_input.value == 0
                and not lib().mb_encoder_has_more_output(self._state)
            ):
                break
        _ = source_keepalive
        return b"".join(pieces)

    def process(self, data):
        if not self._healthy:
            raise error("brotli: encoder is unhealthy")
        if self._finished:
            self._fail("brotli: encoder failed")
        return self._run(as_bytes(data), _PROCESS)

    def flush(self):
        if not self._healthy or self._finished:
            raise error("brotli: encoder is unhealthy")
        return self._run(b"", _FLUSH)

    def finish(self):
        if not self._healthy or self._finished:
            raise error("brotli: encoder is unhealthy")
        result = self._run(b"", _FINISH)
        self._finished = True
        self._close()
        return result


class Decompressor:
    """Incremental Brotli decompressor."""

    def __init__(self):
        self._state = int(lib().mb_decoder_create())
        if not self._state:
            raise error("brotli: failed to create decoder")
        self._healthy = True
        self._finished = False
        self._pending = b""

    def _close(self):
        state, self._state = getattr(self, "_state", 0), 0
        if state:
            lib().mb_decoder_destroy(state)

    def __del__(self):
        self._close()

    def _fail(self, message="brotli: decoder failed"):
        self._healthy = False
        self._close()
        raise error(message)

    def can_accept_more_data(self):
        if not self._healthy:
            raise error("brotli: decoder is unhealthy")
        return not self._pending

    def is_finished(self):
        if not self._healthy:
            raise error("brotli: decoder is unhealthy")
        return self._finished

    def _process(self, data, output_buffer_limit, initial_output_size):
        if not self._healthy:
            raise error("brotli: decoder is unhealthy")
        incoming = as_bytes(data)
        if self._finished:
            if incoming:
                self._fail()
            return b""
        if self._pending and incoming:
            raise error(
                "brotli: decoder process called with data when "
                "'can_accept_more_data()' is False"
            )
        limit = operator.index(output_buffer_limit)
        source = self._pending if self._pending else incoming
        self._pending = b""
        source_address, source_size, source_keepalive = buffer_address(source)
        available_input = ctypes.c_size_t(source_size)
        next_input = ctypes.c_void_p(source_address)
        if limit < 0:
            capacity = max(initial_output_size, source_size, 1)
            destination, destination_address, destination_keepalive = writable_buffer(
                capacity
            )
            produced_total = 0
            while True:
                available_output = ctypes.c_size_t(capacity - produced_total)
                next_output = ctypes.c_void_p(
                    destination_address + produced_total
                )
                result = int(
                    lib().mb_decoder_stream(
                        self._state,
                        ctypes.addressof(available_input),
                        ctypes.addressof(next_input),
                        ctypes.addressof(available_output),
                        ctypes.addressof(next_output),
                    )
                )
                produced_total = capacity - available_output.value
                if result == _DECODER_ERROR:
                    self._fail()
                if result == _DECODER_SUCCESS:
                    consumed = source_size - available_input.value
                    if consumed != source_size:
                        self._fail()
                    self._finished = True
                    break
                if result == _DECODER_NEEDS_MORE_INPUT:
                    break
                if result != _DECODER_NEEDS_MORE_OUTPUT:
                    self._fail()
                del destination_keepalive
                growth = capacity
                destination.extend(bytes(growth))
                capacity += growth
                destination_keepalive = ctypes.c_ubyte.from_buffer(destination)
                destination_address = ctypes.addressof(destination_keepalive)
            _ = source_keepalive, destination_keepalive
            return bytes(memoryview(destination)[:produced_total])
        pieces = []
        produced_total = 0
        while True:
            destination, destination_address, destination_keepalive = writable_buffer(
                _STREAM_BUFFER_SIZE
            )
            available_output = ctypes.c_size_t(_STREAM_BUFFER_SIZE)
            next_output = ctypes.c_void_p(destination_address)
            result = int(
                lib().mb_decoder_stream(
                    self._state,
                    ctypes.addressof(available_input),
                    ctypes.addressof(next_input),
                    ctypes.addressof(available_output),
                    ctypes.addressof(next_output),
                )
            )
            produced = _STREAM_BUFFER_SIZE - available_output.value
            if produced:
                pieces.append(bytes(memoryview(destination)[:produced]))
                produced_total += produced
            _ = destination_keepalive
            if result == _DECODER_ERROR:
                self._fail()
            if result == _DECODER_SUCCESS:
                consumed = source_size - available_input.value
                if consumed != source_size:
                    self._fail()
                self._finished = True
                break
            if limit >= 0 and produced_total >= limit:
                consumed = source_size - available_input.value
                self._pending = source[consumed:]
                break
            if result == _DECODER_NEEDS_MORE_INPUT:
                break
            if result != _DECODER_NEEDS_MORE_OUTPUT:
                self._fail()
        _ = source_keepalive
        return b"".join(pieces)

    def process(self, data, output_buffer_limit=-1):
        return self._process(data, output_buffer_limit, _STREAM_BUFFER_SIZE)


def decompress(data):
    """Decompress one complete Brotli stream."""
    source = as_bytes(data)
    source_address, source_size, source_keepalive = buffer_address(source)
    decoded_address = ctypes.c_void_p()
    decoded_size = ctypes.c_size_t()
    try:
        succeeded = lib().mb_decoder_decompress_alloc(
            source_size,
            source_address,
            ctypes.addressof(decoded_address),
            ctypes.addressof(decoded_size),
        )
        _ = source_keepalive
        if not succeeded:
            raise error("brotli: decoder failed")
        return ctypes.string_at(decoded_address.value, decoded_size.value)
    finally:
        if decoded_address.value:
            lib().mb_free(decoded_address.value)


__all__ = [
    "Compressor",
    "Decompressor",
    "MODE_FONT",
    "MODE_GENERIC",
    "MODE_TEXT",
    "compress",
    "decompress",
    "error",
    "version",
]
