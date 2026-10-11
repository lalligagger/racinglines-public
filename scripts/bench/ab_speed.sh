#!/usr/bin/env bash
# A/B speed test: the same read-only backtest on two git refs (default origin/main vs origin/staging), timed, with
# a check that both print exactly the same results; then, optionally, the same maker replays as WebAssembly.
#
# The backtest is `racinglines f1 replay --runs <ids> --sweep`: one weekend's tape loaded from the archive, then
# 18 maker replays (touch, through and sweep()'s 16-combo grid). It only reads the database.
#
#   # VM (production database, read-only): the env file and the app's venv
#   ENV_FILE=/etc/racinglines.env bash scripts/bench/ab_speed.sh 1298,1299,1300,1301,1302
#   # anywhere else with DATABASE_URL set:
#   bash scripts/bench/ab_speed.sh 1298,1299,1300,1301,1302
#
# Settings: REF_A / REF_B (git refs, fetched from origin when they look like origin/<branch>), REPEAT (default 3:
# the best of N is reported), PY (default .venv/bin/python), CMD (the racinglines arguments, default the replay
# above), WASM=1 to add the WebAssembly run (needs cargo with the wasm32-wasip1 target and node 20+; the VM has
# neither, so run that part in a cloud session or on the Mac). Each ref is exported with `git archive` to a temp
# folder: the checkout itself is not touched.
set -euo pipefail
export PYTHONUNBUFFERED=1
RUNS="${1:?diagnostic run ids, e.g. 1298,1299,1300,1301,1302 (one weekend's stages, as for f1 replay --runs)}"
case "$RUNS" in *[!0-9,]*) echo "ab_speed: run ids must be digits and commas" >&2; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
if [ -n "${ENV_FILE:-}" ]; then set -a; . "$ENV_FILE"; set +a; fi
export RACINGLINES_DATA=${RACINGLINES_DATA:-$ROOT/data}    # both refs read this checkout's data/ (it isn't in git)
REF_A=${REF_A:-origin/main}
REF_B=${REF_B:-origin/staging}
REPEAT=${REPEAT:-3}
PY=${PY:-$ROOT/.venv/bin/python}
CMD=${CMD:-f1 replay --runs $RUNS --sweep}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
log() { echo "[ab_speed $(date -u +%H:%M:%S)] $*"; }

export_ref() {        # <ref> <dir>: the ref's tree in <dir> (fetching origin/<branch> first)
    case "$1" in origin/*) git fetch -q origin "${1#origin/}" ;; esac
    mkdir -p "$2"
    git archive "$1" | tar -x -C "$2"
    echo "$(git rev-parse --short "$1")"
}

declare -A BEST SHA
for side in A B; do
    ref_var="REF_$side"; ref=${!ref_var}
    SHA[$side]=$(export_ref "$ref" "$TMP/$side")
    log "$side = $ref (${SHA[$side]}): $CMD, best of $REPEAT"
    best=""
    for i in $(seq 1 "$REPEAT"); do
        s=$(date +%s%N)
        # PYTHONPATH puts this ref's package ahead of the installed one; the data paths come from the env as usual
        (cd "$TMP/$side" && PYTHONPATH="$TMP/$side" RACINGLINES_PROGRESS_SEC=${RACINGLINES_PROGRESS_SEC:-300} \
            "$PY" -m racinglines $CMD > "$TMP/$side.out" 2> "$TMP/$side.err") \
            || { log "$side failed:"; tail -20 "$TMP/$side.err"; exit 1; }
        dt=$(awk -v a="$s" -v b="$(date +%s%N)" 'BEGIN { printf "%.2f", (b - a) / 1e9 }')
        log "  run $i: ${dt} s"
        if [ -z "$best" ] || awk -v a="$dt" -v b="$best" 'BEGIN { exit !(a < b) }'; then best=$dt; fi
    done
    BEST[$side]=$best
done

if cmp -s "$TMP/A.out" "$TMP/B.out"; then
    same="identical output"
else
    same="OUTPUT DIFFERS"
    diff "$TMP/A.out" "$TMP/B.out" | head -40
fi
printf '\n%-6s %-24s %-9s %10s\n' side ref sha "best (s)"
printf '%-6s %-24s %-9s %10.2f\n' A "$REF_A" "${SHA[A]}" "${BEST[A]}" B "$REF_B" "${SHA[B]}" "${BEST[B]}"
printf 'speedup B vs A: %sx, %s\n' "$(awk -v a="${BEST[A]}" -v b="${BEST[B]}" 'BEGIN { printf "%.2f", a / b }')" "$same"
[ "$same" = "identical output" ] || exit 1

if [ "${WASM:-0}" = 1 ]; then
    K=scripts/bench/replay_kernel
    command -v cargo >/dev/null && command -v node >/dev/null || { log "WASM=1 needs cargo and node"; exit 1; }
    log "kernel inputs: the same weekend and the same 18 replays (read-only)"
    "$PY" scripts/bench/replay_dump.py --runs "$RUNS" --out "$TMP/in.json"
    log "Rust native"
    (cd "$K" && cargo build -q --release && ./target/release/replay_kernel "$TMP/in.json" "$TMP/native.json" 5)
    "$PY" scripts/bench/replay_dump.py --runs "$RUNS" --check "$TMP/native.json"
    log "WebAssembly (wasm32-wasip1 under node)"
    (cd "$K" && cargo build -q --release --target wasm32-wasip1 && node run_wasi.mjs "$TMP" in.json wasm.json 5)
    cmp -s "$TMP/native.json" "$TMP/wasm.json" && log "wasm output identical to native" \
        || { log "wasm output differs from native"; exit 1; }
fi
