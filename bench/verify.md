# mojo-brotli — VERIFY phase

Run in this session on: Intel Xeon E5-2697 v4 @ 2.30 GHz, Linux x86_64, Python 3.13.14, Brotli 1.2.0 both sides (verified: `mojo.version=1.2.0`, `upstream.version=1.2.0`, linked `libbrotlienc.so.1` = 1.2.0).
Method: `pixi run build && pixi run test` (69 passed), then `pixi run bench` (8 MiB, best-of-7 warmed runs, `bench/bench.py`). Ran `pixi run bench` 9 times total in this session and took medians per row.

## What reproduced

| case | README (before) | VERIFY measured (median) | within 20%? |
| --- | --- | --- | --- |
| compress repetitive 8 MiB, quality 5 | 11.53 / 11.48 ms, 1.00x | 12.06 / 12.29 ms, 1.02x | yes — all 9 runs 11.7–14.2 / 11.6–12.7 ms |
| decompress repetitive 8 MiB | 10.25 / 11.04 ms, 1.08x | 11.36 / 11.77 ms, 1.04x | yes — 10.4–11.5 / 11.2–12.8 ms |
| compress random 8 MiB, quality 5 | 62.33 / 68.70 ms, 1.10x | 65.82 / 78.03 ms, 1.19x | yes — mojo 60–72 ms brackets 62.33; upstream noisier 66–82 ms |
| decompress random 8 MiB | 1.36 / 2.22 ms, 1.64x | 1.70 / 2.80 ms, 1.65x | yes — 1.33–2.08 / 2.1–5.5 ms; 1.64x well within run scatter |
| compress repetitive 8 MiB, quality 11 | 183.11 / 185.57 ms, 1.01x | 194.32 / 184.93 ms, 0.95x | yes — 179–204 / 181–196 ms; relative 0.90–1.07 across runs |

No row was off by more than 20%. README numbers left unchanged. Run-to-run scatter is ±10% for compress (allocation/page-fault noise on this shared host), with decompress-random showing one 5.53 ms upstream outlier; medians are stable across the 9 runs.

Slow rows: none in the README table shows mojo-brotli slower than upstream beyond noise (q11 median 0.95x, individual runs 0.90–1.07x). All 5 rows were kept as-is, unreworded.

## What could not be reproduced

Nothing in the README table failed to reproduce within 20%. The closest to a miss was `compress random`, whose upstream median (78 ms) sits 13.5% above the README's 68.70 ms while mojo-brotli matches closely; within the 20% tolerance, so no correction applied.

## Fairness checks (same input, no skipped work)

`bench/bench.py` re-measured directly (not trusted on inspection):
- Same `text` (8 MiB repetitive log record) and same `random_data` (`os.urandom`, 8 MiB) objects feed both sides; decompress rows use one shared upstream-produced frame for both decoders.
- Bench asserts per row: decompress outputs equal source on both sides; compress outputs cross-decode (`upstream.decompress(mojo_result)==source` and `mojo.decompress(upstream_result)==source`) so a side cannot win by skipping work.
- Verified outputs explicitly: compress random q5 is byte-identical between mojo and upstream (8,388,628 B); decompress rows decode identically to source. No skipped/lazy work found in `__init__.py`/`_lib.py` — every call goes through the native libbrotli entry point and materializes the full output before returning.

Noted (not a bench flaw): on the 8 MiB repetitive input at the default `lgwin=22`, mojo one-shot compress produces a 3-byte-different stream (139 B vs 140 B) that is still cross-decodable, while the streaming `Compressor` path is byte-identical to upstream — consistent with `test_one_shot_compressor_returns_exact_owned_bytes` covering a different payload (1.1 MB random) than the bench input. Byte-identical one-shot parity at the exact bench payload was not asserted and is not claimed by the bench. This is a parity caveat, not a timing correction, and was not changed (no failing test demonstrated a bug).

## Test parity audit (`git log -p -- tests/`)

Only one assertion had been loosened since the initial commit:

- `test_module_metadata_matches_upstream` (commit `6631866`, mojo 1.2.0 migration): replaced `assert brotli.version == upstream.version` (and `__version__`) with a check against the linked `libbrotlienc.so.1` version, i.e. a weaker claim that the shim matches itself. Restored to the original:
  ```python
  assert brotli.version == upstream.version
  assert brotli.__version__ == upstream.__version__
  ```
  This passes in this session (both are `1.2.0`), so there is no environment where the loosened form was needed. No tolerance was loosened elsewhere, and no parity assertions were removed.

Other test history (kept, stricter than before):
- `test_contiguous_decoder_growth_boundaries` gained `type/len` assertions (commit `5a88859`) — strengthening, kept.
- `test_one_shot_compressor_returns_exact_owned_bytes` was added (commit `5a88859`) — new coverage, kept.

## Changes made

- `tests/test_parity.py`: restored the two upstream-version assertions in `test_module_metadata_matches_upstream`.
- `README.md`: unchanged (all figures reproduce within 20%; no numbers were invented).
- `bench/bench.py`, `python/mojo_brotli/*`, `src/brotli.mojo`: unchanged (no bug with a failing test was found; per rules, code was not changed).
- `bench/verify.md`: this file.

Final gate: `pixi run build && pixi run test` — build OK (only pre-existing `UnsafePointer` deprecation warnings), 69 tests passed.
