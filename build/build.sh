#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "${repo_root}/dist"
link_dirs=()
if [[ -n "${CONDA_PREFIX:-}" ]]; then
    link_dirs+=(-Xlinker "-L${CONDA_PREFIX}/lib")
fi
mojo build --emit shared-lib "${repo_root}/src/brotli.mojo" \
    -o "${repo_root}/dist/libmojo-brotli.so" \
    "${link_dirs[@]}" \
    -Xlinker -lbrotlienc \
    -Xlinker -lbrotlidec
