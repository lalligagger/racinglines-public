#!/usr/bin/env bash
# Build the maker replay for the browser and copy it to racinglines/web/static/replay.wasm (committed, so the VM
# needs no Rust toolchain). Run after any change to src/lib.rs, then the parity test:
#   bash wasm/build.sh && python -m pytest tests/test_wasm_replay.py
# Needs cargo and `rustup target add wasm32-unknown-unknown`.
set -euo pipefail
cd "$(dirname "$0")"
cargo build -q --release --lib --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/racinglines_replay.wasm ../racinglines/web/static/replay.wasm
ls -l ../racinglines/web/static/replay.wasm
