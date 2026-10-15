#!/bin/bash
# The tests of the block-star pipeline (S1 preparation) in an isolated Blender profile.
#
#   tools/run_star_tests.sh [--dev] [--unit]
#
# Default: build the DEFAULT package (no game asset) into a scratch folder OUTSIDE the repository, install it into an
# isolated profile (BLENDER_USER_RESOURCES, plural), then run tests/blender/s1_star_stub.py with the add-on enabled at
# startup (the stub providers and the synthetic stand-in library; the real Halo Reach.blend is never used).
# --dev    symlink Addon/ into the profile as the legacy add-on "mjolnir_forge" instead of building the package (fast).
# --unit   also run the pure-Python star tests (test_star_layout, test_star_build_tool, test_star_roundtrip_stub) on
#          Python 3.9 and on Blender's 3.13, as `tools/run_tests.py --only ...`.
# The pure tests (and the rest of the suite) are also part of `tools/run_tests.py`; the Blender test is not part of
# `tools/run_blender_tests.sh`.
# No Python bytecode is written (PYTHONDONTWRITEBYTECODE=1 with Blender's --python-use-system-env, which it needs to honour the
# variable; python -B): the run leaves nothing in the repository.
# Exit status: 0 everything passed, 1 something failed, 2 usage / environment.
set -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BL="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
BLPY="${BLENDER_PYTHON:-/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13}"
PY39=/usr/bin/python3

dev=0
unit=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dev) dev=1; shift ;;
        --unit) unit=1; shift ;;
        -h|--help) sed -n 2,16p "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "run_star_tests.sh: unknown option $1" >&2; exit 2 ;;
    esac
done
if [ ! -x "$BL" ]; then echo "run_star_tests.sh: Blender not found at $BL (set BLENDER=...)" >&2; exit 2; fi

unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE   # --python-use-system-env below would otherwise honour them
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1                           # honoured by Blender only with --python-use-system-env
cd "$REPO" || exit 2
failures=0
if [ $unit -eq 1 ]; then
    for py in "$PY39" "$BLPY"; do
        if [ -x "$py" ]; then
            "$py" -B -I tools/run_tests.py --only test_star_layout test_star_build_tool test_star_roundtrip_stub | tail -n 3
            [ ${PIPESTATUS[0]} -eq 0 ] || failures=$((failures + 1))
        else
            echo "run_star_tests.sh: $py not found" >&2; failures=$((failures + 1))
        fi
    done
fi

TMPBASE="$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)"
case "$TMPBASE" in ""|"$REPO"|"$REPO"/*) echo "run_star_tests.sh: the temporary folder (${TMPDIR:-/tmp}) is missing or inside the repository" >&2; exit 2 ;; esac
SCRATCH="$(mktemp -d "$TMPBASE/mjolnir-startest.XXXXXX")"
export BLENDER_USER_RESOURCES="$SCRATCH/user_res"
export PYTHONUNBUFFERED=1
echo "scratch: $SCRATCH"
if [ $dev -eq 1 ]; then
    mkdir -p "$BLENDER_USER_RESOURCES/scripts/addons"
    ln -s "$REPO/Addon" "$BLENDER_USER_RESOURCES/scripts/addons/mjolnir_forge"
    ADD=mjolnir_forge
else
    mkdir -p "$SCRATCH/dist"
    "$PY39" -B -I tools/build_package.py --out "$SCRATCH/dist" --allow-placeholders || { echo "PACKAGE BUILD FAILED"; exit 1; }
    zip="$(ls "$SCRATCH"/dist/mjolnir_forge-*.zip | head -n 1)"
    "$BL" --command extension install-file -r user_default "$zip" < /dev/null > "$SCRATCH/install.log" 2>&1
    status=$?
    cat "$SCRATCH/install.log"
    if [ $status -ne 0 ]; then echo "EXTENSION INSTALL FAILED ($status)"; exit 1; fi
    ADD=bl_ext.user_default.mjolnir_forge
fi
export MJOLNIR_ADDON_MODULE="$ADD"

"$BL" -b --factory-startup --python-use-system-env --python-exit-code 1 --addons "$ADD" \
    --python tests/blender/s1_star_stub.py -- --provider stub > "$SCRATCH/s1.log" 2>&1
status=$?
echo "BLENDER_EXIT=$status (s1)"
if [ $status -ne 0 ] || grep -q "^FAIL " "$SCRATCH/s1.log"; then
    cat "$SCRATCH/s1.log"
    failures=$((failures + 1))
else
    grep -E "^(PASS|SKIP) " "$SCRATCH/s1.log"
fi
echo
if [ $failures -gt 0 ]; then
    echo "run_star_tests.sh: $failures RUN(S) FAILED (logs in $SCRATCH)"
    exit 1
fi
echo "run_star_tests.sh: ALL STAR TESTS PASSED ($ADD)"
exit 0
