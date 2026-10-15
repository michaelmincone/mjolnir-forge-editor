#!/bin/bash
# Everything the pure-Python gates need, in one command (SPEC 9.2):
#   - the repo guard (no game asset in the tree, ignored files included)
#   - the Python 3.9 import and lint scan (U-19)
#   - the full unit suite on system Python 3.9 and on Blender's bundled Python 3.13
# Usage: tools/run_tests.sh [run_tests.py options]      (default option: --samples)
# Exit status 0 only if every step passed.
set -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY39=/usr/bin/python3                                   # PATH order is not trusted: /opt/homebrew/bin/python3 is 3.14 here
PY313="${PY313:-/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13}"

cd "$REPO" || exit 2

version39="$("$PY39" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
if [ "$version39" != "3.9" ]; then
    echo "run_tests.sh: $PY39 reports Python '$version39', expected 3.9.x; refusing to run" >&2
    exit 2
fi
if [ ! -x "$PY313" ]; then
    echo "run_tests.sh: Blender's Python 3.13 not found at $PY313 (set PY313=...)" >&2
    exit 2
fi

args=("$@")
if [ ${#args[@]} -eq 0 ]; then
    args=(--samples)
fi

failures=0
step() {
    local label="$1"
    shift
    echo
    echo "=== $label"
    "$@"
    local status=$?
    if [ $status -ne 0 ]; then
        echo "=== FAILED ($status): $label"
        failures=$((failures + 1))
    fi
}

step "repo guard: no game assets (scans ignored files too)" "$PY39" -I tools/check_no_game_assets.py
step "repo guard self-test (planted temp repositories)" "$PY39" -I tools/check_no_game_assets.py --self-test
step "Python 3.9 import and lint scan (U-19)" "$PY39" -I tools/run_tests.py --only py39_syntax
step "unit suite on Python 3.9" "$PY39" -I tools/run_tests.py "${args[@]}"
step "unit suite on Python 3.13" "$PY313" -I tools/run_tests.py "${args[@]}"

echo
if [ $failures -eq 0 ]; then
    echo "run_tests.sh: ALL STEPS PASSED"
    exit 0
fi
echo "run_tests.sh: $failures STEP(S) FAILED"
exit 1
