# mojo-brotli

`mojo-brotli` provides Brotli compression and decompression through a
Mojo-built shared library, with a Python API matching the public surface of
the upstream [`brotli`](https://pypi.org/project/Brotli/) package. It produces
standard RFC 7932 streams and interoperates in both directions with upstream
Brotli 1.2.0.

The covered API is:

- `compress(data, mode=MODE_GENERIC, quality=11, lgwin=22, lgblock=0)`
- `decompress(data)`
- `Compressor(mode=..., quality=..., lgwin=..., lgblock=...)`, including
  `process()`, `flush()`, and `finish()`
- `Decompressor()`, including `process(data, output_buffer_limit=-1)`,
  `is_finished()`, and `can_accept_more_data()`
- `MODE_GENERIC`, `MODE_TEXT`, `MODE_FONT`, `error`, `version`, and
  `__version__`

This is an FFI port of the upstream Python binding, not a pure-Mojo
reimplementation of the Brotli codec. It covers the complete public
compression/decompression interface of the upstream Python module listed
above. Each listed function, class method, constant, and metadata attribute is
exercised by the test suite.

It does not port Brotli's compression algorithm into Mojo, and it does not
provide a command-line tool, custom allocator hooks, shared-dictionary
construction, or experimental large-window controls. Those capabilities are
outside the public upstream Python API mirrored here. The package currently
targets Linux x86-64 and builds a shared object; wheels and other operating
systems are not covered.

## Install

Install [Pixi](https://pixi.sh/), then create the pinned environment and build
the shared library:

```bash
pixi install
pixi run build
```

The Pixi environment sets `PYTHONPATH=python`, so no separate editable install
is needed for development.

## Usage

```python
import mojo_brotli as brotli

source = (b"request complete\n" * 10_000)
encoded = brotli.compress(source, quality=6, mode=brotli.MODE_TEXT)
assert brotli.decompress(encoded) == source

compressor = brotli.Compressor(quality=5)
stream = compressor.process(source[:1000])
stream += compressor.process(source[1000:])
stream += compressor.finish()

decoder = brotli.Decompressor()
decoded = b"".join(
    decoder.process(stream[pos : pos + 17])
    for pos in range(0, len(stream), 17)
)
assert decoder.is_finished()
assert decoded == source
```

Run the validation suite with:

```bash
pixi run test
```

The suite checks byte-for-byte encoder parity across qualities, modes, window
sizes, block sizes, empty input, and streaming flush boundaries. It also
cross-decodes Mojo and upstream streams, exercises incremental backpressure,
verifies input-buffer ownership and zero-copy NumPy inputs, covers decoder
growth boundaries, rejects invalid native pointer/length combinations, and
verifies error behavior.

## Benchmark

Measured with `pixi run bench` on an Intel Xeon E5-2697 v4 at 2.30 GHz,
Linux x86_64, Python 3.13.14, using Brotli 1.2.0 on both sides. Times are the
best of seven warmed runs over 8 MiB inputs. Relative is upstream time divided
by mojo-brotli time, so values above 1.00x favor mojo-brotli.

| case | mojo-brotli | upstream brotli | relative |
| --- | ---: | ---: | ---: |
| compress repetitive 8 MiB, quality 5 | 11.53 ms | 11.48 ms | 1.00x |
| decompress repetitive 8 MiB | 10.25 ms | 11.04 ms | 1.08x |
| compress random 8 MiB, quality 5 | 62.33 ms | 68.70 ms | 1.10x |
| decompress random 8 MiB | 1.36 ms | 2.22 ms | 1.64x |
| compress repetitive 8 MiB, quality 11 | 183.11 ms | 185.57 ms | 1.01x |

There is no separate SIMD, threaded, or GPU path. The Mojo compilation unit
contains ABI and buffer-management code, while all arithmetic, match finding,
entropy coding, and existing platform-specific optimization are inside
production libbrotli. A single Brotli stream is ordered by its sliding window
and entropy state, so splitting it across CPU workers would change the stream
and break byte parity. The wrapper has effectively zero floating-point
arithmetic intensity, making GPU transfer and launch overhead unjustified.
Consequently this package does not add the `max` runtime dependency.

## How it works

`src/brotli.mojo` is the single compilation unit. It uses Mojo's foreign
function interface to drive the production `libbrotlienc` and `libbrotlidec`
state machines, and exports a small fixed C ABI. This keeps the compute-bound
Brotli implementation fully RFC-compatible instead of substituting a partial
codec.

The ctypes layer passes C-contiguous buffers as integer addresses and sizes.
Bytes and writable or read-only NumPy buffers remain zero-copy on input.
One-shot compression allocates Brotli's maximum encoded size directly as an
unexposed Python bytes object and shrinks it to the encoded size after
libbrotli fills it. One-shot decompression writes into the eventual Python
bytes result and grows it geometrically because a Brotli stream does not
expose its uncompressed size. This avoids a full-size native-to-Python output
copy. The incremental decoder uses a contiguous geometrically grown buffer
for unrestricted output and retains the bounded 32 KiB behavior for
backpressure limits. Streaming encoder and decoder contexts are created and
destroyed through the Mojo library, while no language-owned heap object
crosses the ABI.

The build produces `dist/libmojo-brotli.so` and links it against the Brotli
libraries supplied by the pinned Pixi environment.
