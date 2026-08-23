import ctypes
import os

import brotli as upstream
import numpy as np
import pytest

import mojo_brotli as brotli
from mojo_brotli._lib import as_bytes, buffer_address, lib


def payload(size=250_000):
    record = (
        b'{"timestamp":"2026-07-29T12:00:00Z","service":"mojo-brotli",'
        b'"status":200,"message":"request complete"}\n'
    )
    return (record * (size // len(record) + 1))[:size]


@pytest.mark.parametrize("size", [0, 1, 2, 17, 255, 4096, 250_000])
def test_roundtrip_sizes(size):
    source = payload(size)
    assert brotli.decompress(brotli.compress(source)) == source


@pytest.mark.parametrize("quality", [0, 1, 4, 6, 9, 11])
def test_mojo_compression_is_byte_identical_to_upstream(quality):
    source = payload(80_000)
    assert brotli.compress(source, quality=quality) == upstream.compress(
        source, quality=quality
    )


@pytest.mark.parametrize("quality", [0, 1, 5, 9, 11])
def test_upstream_compresses_mojo_decompresses(quality):
    source = payload(100_000)
    encoded = upstream.compress(source, quality=quality)
    assert brotli.decompress(encoded) == upstream.decompress(encoded) == source


@pytest.mark.parametrize(
    "mode", [brotli.MODE_GENERIC, brotli.MODE_TEXT, brotli.MODE_FONT]
)
def test_modes_match_upstream(mode):
    source = payload(60_000)
    assert brotli.compress(source, mode=mode, quality=6) == upstream.compress(
        source, mode=mode, quality=6
    )


@pytest.mark.parametrize("lgwin", [10, 12, 18, 22, 24])
def test_window_sizes_match_upstream(lgwin):
    source = payload(70_000)
    assert brotli.compress(source, quality=5, lgwin=lgwin) == upstream.compress(
        source, quality=5, lgwin=lgwin
    )


@pytest.mark.parametrize("lgblock", [0, 16, 18, 20, 24])
def test_block_sizes_match_upstream(lgblock):
    source = payload(150_000)
    encoded = brotli.compress(source, quality=5, lgblock=lgblock)
    assert encoded == upstream.compress(source, quality=5, lgblock=lgblock)
    assert upstream.decompress(encoded) == source


def test_incompressible_data_cross_compatibility():
    source = os.urandom(300_000)
    mojo_encoded = brotli.compress(source, quality=4)
    upstream_encoded = upstream.compress(source, quality=4)
    assert upstream.decompress(mojo_encoded) == source
    assert brotli.decompress(upstream_encoded) == source


def test_incremental_mojo_compression_matches_upstream():
    source = payload()
    ours = brotli.Compressor(mode=brotli.MODE_TEXT, quality=7, lgwin=20)
    theirs = upstream.Compressor(
        mode=upstream.MODE_TEXT, quality=7, lgwin=20
    )
    ours_parts = []
    their_parts = []
    for position in range(0, len(source), 7919):
        chunk = source[position : position + 7919]
        ours_parts.append(ours.process(chunk))
        their_parts.append(theirs.process(chunk))
    ours_parts.append(ours.finish())
    their_parts.append(theirs.finish())
    assert b"".join(ours_parts) == b"".join(their_parts)
    assert upstream.decompress(b"".join(ours_parts)) == source


def test_incremental_flush_keeps_encoder_open():
    first = payload(50_000)
    second = os.urandom(40_000)
    ours = brotli.Compressor(quality=5)
    theirs = upstream.Compressor(quality=5)
    ours_encoded = (
        ours.process(first)
        + ours.flush()
        + ours.process(second)
        + ours.flush()
        + ours.finish()
    )
    their_encoded = (
        theirs.process(first)
        + theirs.flush()
        + theirs.process(second)
        + theirs.flush()
        + theirs.finish()
    )
    assert ours_encoded == their_encoded
    assert upstream.decompress(ours_encoded) == first + second


def test_compressor_rejects_calls_after_finish():
    compressor = brotli.Compressor()
    compressor.finish()
    with pytest.raises(brotli.error):
        compressor.process(b"late")
    with pytest.raises(brotli.error):
        compressor.flush()
    with pytest.raises(brotli.error):
        compressor.finish()


def test_incremental_mojo_decompression_of_upstream_chunks():
    source = payload()
    encoded = upstream.compress(source, quality=9)
    decoder = brotli.Decompressor()
    pieces = [
        decoder.process(encoded[position : position + 7])
        for position in range(0, len(encoded), 7)
    ]
    assert b"".join(pieces) == source
    assert decoder.is_finished()
    assert decoder.can_accept_more_data()
    assert decoder.process(b"") == b""


def test_output_buffer_limit_drains_incrementally():
    source = payload(200_000)
    encoded = upstream.compress(source, quality=4)
    decoder = brotli.Decompressor()
    pieces = [decoder.process(encoded, output_buffer_limit=1)]
    while not decoder.is_finished():
        pieces.append(decoder.process(bytearray(), output_buffer_limit=1))
    assert len(pieces) > 1
    assert b"".join(pieces) == source


def test_decoder_reports_backpressure_for_unconsumed_input():
    source = os.urandom(1_000_000)
    encoded = upstream.compress(source, quality=1)
    decoder = brotli.Decompressor()
    pieces = [decoder.process(encoded, output_buffer_limit=1)]
    if not decoder.can_accept_more_data():
        with pytest.raises(brotli.error, match="can_accept_more_data"):
            decoder.process(b"new input", output_buffer_limit=1)
    while not decoder.is_finished():
        pieces.append(decoder.process(b"", output_buffer_limit=1))
    assert b"".join(pieces) == source


def test_concatenated_streams_and_trailing_data_are_rejected():
    first = upstream.compress(payload(5000))
    second = upstream.compress(payload(4000))
    with pytest.raises(brotli.error):
        brotli.decompress(first + second)
    with pytest.raises(brotli.error):
        brotli.decompress(first + b"trailing")
    decoder = brotli.Decompressor()
    with pytest.raises(brotli.error):
        decoder.process(first + second)
    with pytest.raises(brotli.error, match="unhealthy"):
        decoder.is_finished()


@pytest.mark.parametrize(
    "bad_data",
    [b"", b"not a brotli stream", b"\x8b", b"\xff" * 20],
)
def test_invalid_or_truncated_data_raises(bad_data):
    with pytest.raises(brotli.error):
        brotli.decompress(bad_data)


def test_empty_stream_matches_upstream():
    assert brotli.compress(b"") == upstream.compress(b"")
    assert brotli.decompress(upstream.compress(b"")) == b""
    decoder = brotli.Decompressor()
    assert decoder.process(b"") == b""
    assert not decoder.is_finished()


@pytest.mark.parametrize(
    "factory",
    [
        bytes,
        bytearray,
        memoryview,
    ],
)
def test_bytes_like_inputs(factory):
    source = payload(20_000)
    encoded = brotli.compress(factory(source))
    assert brotli.decompress(factory(encoded)) == source


def test_numpy_inputs_remain_zero_copy_across_validation():
    source = np.frombuffer(payload(20_000), dtype=np.uint8).copy()
    validated = as_bytes(source)
    assert isinstance(validated, memoryview)
    assert validated.obj is source
    address, size, keepalive = buffer_address(validated)
    assert address == source.ctypes.data
    assert size == source.nbytes
    _ = keepalive
    encoded = brotli.compress(source)
    encoded_array = np.frombuffer(encoded, dtype=np.uint8).copy()
    assert brotli.decompress(encoded_array) == source.tobytes()

    source.flags.writeable = False
    readonly = as_bytes(source)
    address, size, keepalive = buffer_address(readonly)
    assert address == source.ctypes.data
    assert size == source.nbytes
    _ = keepalive


@pytest.mark.parametrize("size", [32767, 32768, 32769, 1048575, 1048576, 1048577])
def test_contiguous_decoder_growth_boundaries(size):
    source = payload(size)
    encoded = upstream.compress(source, quality=5)
    decoded = brotli.decompress(encoded)
    assert type(decoded) is bytes
    assert len(decoded) == size
    assert decoded == source


def test_one_shot_compressor_returns_exact_owned_bytes():
    source = os.urandom(1_100_003)
    encoded = brotli.compress(memoryview(source), quality=5)
    assert type(encoded) is bytes
    assert encoded == upstream.compress(source, quality=5)


def test_noncontiguous_and_nonbuffer_inputs_are_rejected():
    noncontiguous = memoryview(bytearray(b"abcdef"))[::2]
    multidimensional = np.zeros((2, 3), dtype=np.uint8)
    with pytest.raises(TypeError, match="C-contiguous"):
        brotli.compress(noncontiguous)
    with pytest.raises(TypeError, match="C-contiguous"):
        brotli.compress(multidimensional)
    with pytest.raises(TypeError, match="C-contiguous"):
        brotli.decompress("not bytes")
    with pytest.raises(TypeError, match="C-contiguous"):
        brotli.Compressor().process(None)


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("mode", 3),
        ("quality", 12),
        ("lgwin", 9),
        ("lgwin", 25),
        ("lgblock", 15),
        ("lgblock", 25),
    ],
)
def test_invalid_settings_raise_brotli_error(keyword, value):
    with pytest.raises(brotli.error):
        brotli.Compressor(**{keyword: value})
    with pytest.raises(brotli.error):
        brotli.compress(b"data", **{keyword: value})


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("mode", -1),
        ("quality", -1),
        ("lgwin", 256),
        ("lgblock", 256),
    ],
)
def test_settings_outside_unsigned_byte_raise_overflow(keyword, value):
    with pytest.raises(OverflowError):
        brotli.Compressor(**{keyword: value})


def test_module_metadata_matches_upstream():
    assert brotli.version == upstream.version
    assert brotli.__version__ == upstream.__version__
    assert (
        brotli.MODE_GENERIC,
        brotli.MODE_TEXT,
        brotli.MODE_FONT,
    ) == (
        upstream.MODE_GENERIC,
        upstream.MODE_TEXT,
        upstream.MODE_FONT,
    )


def test_multiple_encoder_and_decoder_instances_are_independent():
    left = payload(30_000)
    right = os.urandom(30_000)
    left_encoder = brotli.Compressor(quality=3)
    right_encoder = brotli.Compressor(quality=8)
    left_frame = left_encoder.process(left) + left_encoder.finish()
    right_frame = right_encoder.process(right) + right_encoder.finish()
    assert brotli.decompress(left_frame) == left
    assert brotli.decompress(right_frame) == right


def test_native_entry_points_reject_invalid_addresses_and_lengths():
    native = lib()
    output_address = ctypes.c_void_p()
    output_size = ctypes.c_size_t()
    assert not native.mb_encoder_compress_alloc(
        5, 22, brotli.MODE_GENERIC, -1, 0,
        ctypes.addressof(output_address), ctypes.addressof(output_size)
    )
    assert not native.mb_encoder_compress_alloc(
        5, 22, brotli.MODE_GENERIC, 1, 0,
        ctypes.addressof(output_address), ctypes.addressof(output_size)
    )
    assert not native.mb_encoder_compress_alloc(
        2**40, 22, brotli.MODE_GENERIC, 0, 1,
        ctypes.addressof(output_address), ctypes.addressof(output_size)
    )
    assert not native.mb_encoder_create(brotli.MODE_GENERIC, 2**40, 22, 0)
    assert not native.mb_decoder_decompress_alloc(
        1, 0, ctypes.addressof(output_address), ctypes.addressof(output_size)
    )
