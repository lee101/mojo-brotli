# mojo-brotli — VERIFY phase (re-run)

Run in this session on: Intel Xeon E5-2697 v4 @ 2.30 GHz, Linux x86_64,
Python 3.13.14 (via `pixi run python --version`), Brotli 1.2.0 on both sides
(verified: `mojo.version=1.2.0`, `upstream.version=1.2.0`,
`mojo.__version__=upstream.__version__=1.2.0`).
Method: `pixi run build && pixi run test` (69 passed), then `pixi run bench`
(8 MiB, best-of-7 warmed runs, `bench/bench.py`), sequentially.
Ran `pixi run bench` 8 times total in this session (1 initial + 7 repeat)
and took medians per row.

## What reproduced

README figures (before this session) vs VERIFY measured medians (8 runs):

| case | README (before) | VERIFY measured (median) | within 20%? |
| --- | --- | --- | --- |
| compress repetitive 8 MiB, quality 5 | 11.53 / 11.48 ms, 1.00x | 12.00 / 12.20 ms, 1.01x | yes — mojo +4.1%, upstream +6.2% |
| decompress repetitive 8 MiB | 10.25 / 11.04 ms, 1.08x | 11.31 / 12.04 ms, 1.06x | yes — mojo +10.4%, upstream +9.0% |
| compress random 8 MiB, quality 5 | 62.33 / 68.70 ms, 1.10x | 63.14 / 70.44 ms, 1.12x | yes — mojo +1.3%, upstream +2.5% |
| decompress random 8 MiB | 1.36 / 2.22 ms, 1.64x | 1.53 / 2.40 ms, 1.57x | yes — mojo +12.5%, upstream +8.1% |
| compress repetitive 8 MiB, quality 11 | 183.11 / 185.57 ms, 1.01x | 193.30 / 190.38 ms, 0.98x | yes — mojo +5.6%, upstream +2.6% |

All 5 rows reproduce within 20% on every figure (both times and relative).
Per-run relative ranges: compress-repetitive q5 0.99–1.03x (README 1.00x),
decompress-repetitive 0.99–1.18x (README 1.08x), compress-random 1.03–1.30x
(README 1.10x), decompress-random 1.48–1.89x (README 1.64x), compress-q11
0.95–1.01x (README 1.01x). Run-to-run scatter is ±10% for compress
(allocation/page-fault noise on this shared host), decompress-random up to
±30% on its small (~1.5 ms) base.

No row was off by more than 20%. README numbers left unchanged.

Slow rows: no README row shows mojo-brotli clearly slower than upstream
beyond noise. q11 relative is 0.98x median (0.95–1.01x per-run) — essentially
parity; README's 1.01x is within scatter and was kept as-is, unreworded.
All 5 rows were kept; none removed, none reworded to look better.

## What could not be reproduced

Nothing in the README table failed to reproduce within 20%. The closest to a
miss was `decompress random` (mojo median +12.5%) and `decompress repetitive`
(+10.4%), both on the slower side of the shared host this session; within the
20% tolerance, so no correction applied.

## Fairness checks (same input, no skipped work)

`bench/bench.py` re-measured directly in this session (not trusted on
inspection):
- Same `text` (8 MiB repetitive log record) and same `random_data`
  (`os.urandom`, 8 MiB) objects feed both sides; decompress rows use one
  shared upstream-produced frame for both decoders.
- Bench asserts per row: decompress outputs equal source on both sides;
  compress outputs cross-decode
  (`upstream.decompress(mojo_result)==source` and
  `mojo.decompress(upstream_result)==source`) so a side cannot win by
  skipping work.
- Verified outputs explicitly in this session: compress random q5 is
  byte-identical between mojo and upstream (8,388,621 B); decompress rows
  decode identically to source. No skipped/lazy work found in
  `__init__.py`/`_lib.py` — every call goes through the native libbrotli
  entry point (`mb_encoder_compress` / `mb_decoder_stream` /
  `mb_encoder_stream`) and materializes the full output before returning.

Noted (not a bench flaw, re-verified this session): on the 8 MiB repetitive
input at the default `lgwin=22`, mojo one-shot compress produces a
different-but-cross-decodable stream (139 B vs 140 B at q5; 89 B vs 90 B at
q11), while compress random q5 is byte-identical. This is the same one-shot
caveat documented in the prior `bench/verify.md` (the bench asserts
cross-decodability, not byte-identity, for compress — correctly, since a
different valid stream can still be timed, and both sides do full libbrotli
work). It is not a timing correction, and was not changed (no failing test
demonstrated a bug; per rules, code was not changed).

## Test parity audit (`git log -p -- tests/`)

History over `7132bb7` (initial) → `5a88859` (accel) → `6631866` (mojo 1.2.0)
→ `37b965b` (prior verify):

- `test_module_metadata_matches_upstream`: loosened in `6631866` (replaced
  `brotli.version == upstream.version` with a linked-`libbrotlienc` check),
  then restored in `37b965b` (prior verify). Current HEAD already has the
  restored form:
  ```python
  assert brotli.version == upstream.version
  assert brotli.__version__ == upstream.__version__
  ```
  This passes in this session (both are `1.2.0`). No further loosening or
  restoration needed this session. No tolerance was loosened elsewhere, and no
  parity assertions were removed.

Other test history (kept, stricter than before):
- `test_contiguous_decoder_growth_boundaries` gained `type/len` assertions
  (`5a88859`) — strengthening, kept.
- `test_one_shot_compressor_returns_exact_owned_bytes` was added (`5a88859`)
  — new coverage, kept.

## Changes made

- `README.md`: unchanged (all figures reproduce within 20%; no numbers were
  invented).
- `tests/test_parity.py`: unchanged (restoration already present at HEAD; no
  loosened assertions found this session).
- `bench/bench.py`, `python/mojo_brotli/*`, `src/brotli.mojo`: unchanged (no
  bug with a failing test was found; per rules, code was not changed).
- `bench/verify.md`: this file (re-run of the VERIFY phase; replaces the
  prior session's version with this session's measurements).

Final gate: `pixi run build && pixi run test` — build OK (only pre-existing
`UnsafePointer` deprecation warnings), 69 tests passed.
