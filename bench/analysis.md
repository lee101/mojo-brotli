# mojo-brotli — ANALYZE phase

Run in this session on: Intel Xeon E5-2697 v4 @ 2.30 GHz, Linux x86_64, Python 3.13.14, Brotli 1.2.0 both sides.
All numbers below are best-of-7 warmed runs measured in this session; `pixi run bench` (8 MiB, best-of-7) agrees within run noise.

## Where the time goes (one line)

For big inputs the kernel is ~97%+ of wall time; Python/ctypes glue is ~2–4 µs/call. All hotspot movement is inside `libbrotli`, not in the Mojo wrapper. This is an FFI port of upstream's Python binding, not a Mojo reimplementation of the codec, so most "next phases" are `none` — there is almost no Mojo-side work to optimize.

Key measured glue units (this session):

- bare ctypes export call: 0.31–0.39 µs
- `_settings(...)`: 0.67 µs; `as_bytes(8 MiB bytes)`: 0.17 µs; `buffer_address(bytes)`: 1.85 µs; NumPy read-only: 3.99 µs
- `BytesWriter` alloc + shrink-resize: 0.004–0.007 ms (negligible)
- numpy copy 8 MiB (memcpy floor): 0.58 ms → 13.8 GB/s effective; `bytes(8 MiB)`: 0.37 ms
- SHA-256 8 MiB (dense integer-hash reference): 23.9 ms → 351 MB/s

## Ranked hotspot table

"FLOPs" here counts integer ops as the flop analog (Brotli has no floating point). Per-byte figures use `touched = input + output` with 2.3 GHz and ~2 instr/cycle; they are ±2× estimates of instruction intensity, sufficient for the GPU threshold test (< 2 flops/byte).

| Rank | function | input size | time (mojo / upstream) | bytes touched | flops | flops/byte | memory- or compute-bound | glue vs kernel | next phase |
|---:|---|---|---:|---:|---:|---:|---|---|---|
| 1 | `compress` random 8 MiB, q5 | 8.00 MiB | 70.30 / 87.31 ms | 16.8 MiB (in+out) | ~3.2×10⁸ | 19.3 | compute-bound | kernel ~100%; glue ~3 µs (0.004%) | **none** — slowest row, but mojo is 1.24× *faster* than upstream; both are libbrotli |
| 2 | `compress` text 8 MiB, q11 | 8.00 MiB | 202.13 / 198.37 ms | 8.0 MiB | ~9.3×10⁸ | 110.8 | heavily compute-bound | kernel ~100% | **none** — 0.98×, within noise of upstream; q11 is brute-force search in libbrotli |
| 3 | `compress` text 8 MiB, q5 | 8.00 MiB | 17.53 / 11.75 ms | 8.0 MiB | ~8.0×10⁷ | 9.6 | compute-bound | kernel ~100% (incl. output page-fault ring) | **none** — **SLOWER than upstream (0.67×)**; cause is allocation footprint (below), not codec |
| 4 | `compress` text 8 MiB, q0 | 8.00 MiB | 1.69 / 1.53 ms | 8.0 MiB | ~7.6×10⁶ | 0.9 | memory-bound | kernel ~100% | **none** — **SLOWER than upstream (0.91×)** by 0.16 ms; 0.9 flops/byte ≪ GPU threshold and no Mojo loop exists to move |
| 5 | `decompress` text (140 B → 8 MiB) | 140 B in / 8.00 MiB out | 10.29 / 11.57 ms | 8.0 MiB | ~4.7×10⁷ | 5.6 | compute-bound (entropy decode) | kernel ~100% | **none** — mojo 1.12× faster |
| 6 | `decompress` random 8 MiB | 8.00 MiB | 2.08 / 2.45 ms | 16.8 MiB | ~1.0×10⁷ | 0.6 | memory-bound | kernel ~100% | **none** — mojo 1.18× faster; 0.6 flops/byte also rules out GPU (transfer would cost 10× the work) |
| 7 | `Decompressor.process` log-style streaming, 32 KiB chunks ×257 | 8.00 MiB | 6.08 / (one-shot 1.70) ms | 16.8 MiB | ~2.8×10⁷ | 1.7 | memory-bound + per-call glue | **glue ~70%** (257 ctypes crossings × ~17 µs for `writable_buffer` + `as_bytes` + `_run` loop) | **unroll** (batch the 32 KiB loop) — only non-`none` row; see § Flags |
| 8 | `Compressor.process` log-style streaming, 32 KiB chunks | 8.00 MiB | 14.52 / 17.11 ms | 8.0 MiB | ~6.7×10⁷ | 8.0 | compute-bound | kernel ~85%, glue ~15% | **none** — faster than one-shot at this quality; gap to upstream is libbrotli state, not Mojo |
| 9 | `compress` text 1 MiB, q11 | 1.00 MiB | 19.27 / 20.90 ms | 1.0 MiB | ~8.8×10⁷ | 84.5 | compute-bound | kernel ~100% | **none** |
| 10 | small-call glue (`compress`/`decompress` ≤ 16 KiB) | 1–16 KiB | 0.016–0.040 / 0.005–0.026 ms | 2–32 KiB | ~10³ | 1–5 | memory-bound (call overhead) | **glue ~60–75%**: fixed ~20–25 µs floor vs upstream's ~5–10 µs | **unroll** — fold `_settings`/`as_bytes`/`buffer_address` into one crossing at small sizes; worth doing only if a caller is in a µs-critical loop |

## The 0.67× row, honestly explained

Rows 3 and 4 are slower than upstream. That is not a codec regression: both sides call the *same* `BrotliEncoderCompress` in the *same* `libbrotli 1.2.0`.

- Reused, resident output buffer: kernel = 12.3 ms (= upstream's 11.75–12.0 ms). Kernel parity confirmed.
- Fresh `BytesWriter(max_size)` (8.4 MiB): kernel = 17.5–18.9 ms. Pre-faulting the buffer did *not* help (22.4 ms); the delta is malloc/page-fault latency inside the call, ~5–6 ms for the 8 MiB ring.
- For highly compressible data the encoder writes only 139 B of the 8.4 MiB ring, but mojo allocates the max-size ring up front. Upstream allocates only what it writes (geometric growth), so it touches ~139 B + its state, not 8.4 MiB.
- For random data mojo is 1.24× *faster* — there the max-size preallocation touches everything anyway, and geometric growth upstream wastes reallocs. One alloc, no copying, wins.

So rows 3–4 should not survive rank-ordering into later "make it faster" work: the fix is `unroll`-class glue (allocate output lazily / in chunks) and it would make mojo *identical to upstream*, not faster than it. It changes nothing about the algorithm and must preserve byte-parity, which the bench asserts.

## Flags: per-element ctypes re-entry and per-call allocations

1. **No element-wise re-entry exists.** There are no Python-level loops over data elements anywhere: every entry point issues exactly `O(1)` ctypes crossings per public call (one `mb_encoder_compress`, one `mb_decoder_stream` per 32 KiB of stream buffer). The `while` loops in `Compressor._run` (`__init__.py:122`) and `Decompressor._process` (`__init__.py:233,270`) iterate over 32 KiB chunks, not bytes. Call count therefore scales with `output / 32 KiB`, not with bytes — at 8 MiB random that is 257 stream calls in the worst case (`process()` in 32 KiB inputs), which is exactly row 7's glue-dominated cost. Nothing re-enters per byte.
2. **Per-call allocations:** `BytesWriter(capacity)` (max-size, § above) in `_lib.py:88`; `ctypes.c_size_t` scalars per loop iteration; `b"".join(pieces)` in `_run`/`_process` copies the entire accumulated output once per `process()` call. All measured negligible (≤0.01 ms) except the 8 MiB max-size pre-touch on compressible data (~5 ms), which dominates row 3.
3. **Streaming equality:** `join` in `Decompressor._process` (limit ≥ 0 path, `__init__.py:307`) allocates one buffer per 32 KiB of output; unavoidable given the API contract, and its cost is counted in row 7.

## SIMD / parallel / GPU verdicts

- **SIMD: none.** There is no vectorizable Mojo loop in the wrapper — the wrapper is glue; all compute is inside opaque `libbrotli` calls. There is nothing to vectorize at the Mojo level.
- **parallelize: none.** One Brotli stream is sequentially ordered (sliding window + entropy state). Splitting it across workers changes the stream and breaks byte-parity. Explicitly out of bounds.
- **GPU: none.** Every row except q5-rank-1 measures < 20 flops/byte, and the two near-memcpy rows (q0, decompress-random: 0.6–0.9 flops/byte) are the cheapest possible work — a device copy alone (PCIe round-trip of 16 MiB at ~25 GB/s host↔device) would cost ~1.3 ms, which is comparable to or larger than the *entire* kernel time of those rows (1.7–2.1 ms), before any launch or entropy state transfer. The encoder's match search and arithmetic coding are data-dependent and serial per stream; there is no data-parallel kernel hiding in the wrapper.
- **unroll: rows 7 and 10 only** (batch small streaming chunks / collapse small-call glue). Rank 7's 3.6× glue overhead is the single actionable finding in this analysis, and it is also the smallest absolute win (~4 ms at 8 MiB once, ~17 µs per streamed call).

## Summary for the next phases

Do not spend effort on SIMD, parallel, or GPU: the measured flops/byte profile and the single-stream serial dependency rule them out, and the wrapper contains zero Mojo-side arithmetic to accelerate. The only measured, actionable item is the Python/ctypes glue around streaming/small calls (**unroll** on rows 7 and 10, ~17 µs/call). The one "slower than upstream" artifact (compressing compressible data) is a max-size output preallocation effect — fixing it returns mojo to parity with upstream, and preserving byte-for-byte parity is the constraint.
