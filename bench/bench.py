"""Benchmark mojo-brotli against the upstream Python Brotli bindings."""

from __future__ import annotations

import os
import platform
import sys
import time

import brotli as upstream

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "python",
    ),
)

import mojo_brotli as mojo  # noqa: E402


def best_time(function, repetitions=7):
    function()
    best = float("inf")
    result = None
    for _ in range(repetitions):
        start = time.perf_counter()
        result = function()
        best = min(best, time.perf_counter() - start)
    return best, result


def machine():
    model = "unknown CPU"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as cpuinfo:
            for line in cpuinfo:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return (
        f"{model}; {platform.system()} {platform.machine()}; "
        f"Python {platform.python_version()}"
    )


def main():
    size = 8 * 1024 * 1024
    record = (
        b'{"time":"2026-07-29T12:00:00Z","level":"info",'
        b'"service":"compressor","message":"request completed","status":200}\n'
    )
    text = (record * (size // len(record) + 1))[:size]
    random_data = os.urandom(size)
    text_frame = upstream.compress(text, quality=5)
    random_frame = upstream.compress(random_data, quality=5)

    cases = [
        (
            "compress repetitive 8 MiB, quality 5",
            lambda: mojo.compress(text, quality=5),
            lambda: upstream.compress(text, quality=5),
            "compress",
            text,
        ),
        (
            "decompress repetitive 8 MiB",
            lambda: mojo.decompress(text_frame),
            lambda: upstream.decompress(text_frame),
            "decompress",
            text,
        ),
        (
            "compress random 8 MiB, quality 5",
            lambda: mojo.compress(random_data, quality=5),
            lambda: upstream.compress(random_data, quality=5),
            "compress",
            random_data,
        ),
        (
            "decompress random 8 MiB",
            lambda: mojo.decompress(random_frame),
            lambda: upstream.decompress(random_frame),
            "decompress",
            random_data,
        ),
        (
            "compress repetitive 8 MiB, quality 11",
            lambda: mojo.compress(text, quality=11),
            lambda: upstream.compress(text, quality=11),
            "compress",
            text,
        ),
    ]

    print(f"Machine: {machine()}")
    print(f"Mojo linked Brotli: {mojo.version}")
    print(f"Upstream Brotli: {upstream.version}")
    print()
    print("| case | mojo-brotli | upstream brotli | relative |")
    print("| --- | ---: | ---: | ---: |")
    for name, mojo_function, upstream_function, kind, source in cases:
        mojo_seconds, mojo_result = best_time(mojo_function)
        upstream_seconds, upstream_result = best_time(upstream_function)
        if kind == "decompress":
            if mojo_result != source or upstream_result != source:
                raise AssertionError(f"benchmark outputs differ for {name}")
        else:
            if upstream.decompress(mojo_result) != source:
                raise AssertionError(f"Mojo output is invalid for {name}")
            if mojo.decompress(upstream_result) != source:
                raise AssertionError(f"upstream output is invalid for {name}")
        relative = upstream_seconds / mojo_seconds
        print(
            f"| {name} | {mojo_seconds * 1000:.2f} ms | "
            f"{upstream_seconds * 1000:.2f} ms | {relative:.2f}x |"
        )


if __name__ == "__main__":
    main()
