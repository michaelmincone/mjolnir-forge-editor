#!/bin/bash
# Headless Blender suite of SPEC 9.4 in an isolated profile (nothing touches ~/Library/Application Support/Blender).
#
#   tools/run_blender_tests.sh [--provider stub|real|all] [--only ID...] [--real-library] [--dev] [--keep-scratch]
#
# Default flow (what the acceptance of gates G4 and G6 runs):
#   1. build the DEFAULT package (no game asset, no ForgeBridge.dll) with --allow-placeholders into a scratch folder
#      OUTSIDE the repository, install it into an isolated profile (BLENDER_USER_RESOURCES, plural),
#   2. B-01 alone with the add-on enabled at STARTUP (this is what exposes bpy.data being restricted in register()),
#   3. the whole suite (tests/blender/run_all.py) with the add-on enabled at startup, for every chosen provider.
# --provider stub   (default) the glue against the canned provider of tests/stubs: 19 tests.
# --provider real   the whole catalogue of SPEC 9.4 against the library behind the add-on, with fixtures of the independent
#                   builder and the one real map variant: B-01 .. B-23 plus b03r, b07, b15, b16, b18, b20.
# --provider all    stub, then real, in one profile; the exit status covers both.
# --real-library    links the real Halo Reach.blend (read-only) instead of the synthetic stand-in; local run only. The SHA-256 and
#                   modification time of that file, of the real .mvar and of every sample file are compared before and after.
# --dev             skips the package and symlinks Addon/ into the profile as a legacy add-on named mjolnir_forge (fast loop).
# Exit status: 0 only when the package built, every Blender run exited 0, every run printed its RESULT line (a run that printed
#                nothing, or whose RESULT line says anything but PASSED, is never a pass) and NO test was skipped;
#              1 when anything failed (package, install, a Blender run, a FAIL line, a missing RESULT line, a changed original);
#              3 when nothing failed but some test was SKIPPED (the last line says "SKIPPED"; a skipped test proves nothing, so it
#                is never reported as a pass).
set -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BL="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
PY39=/usr/bin/python3                       # PATH order is not trusted: /opt/homebrew/bin/python3 is 3.14 here

provider=stub
only=()
real_library=0
dev=0
while [ $# -gt 0 ]; do
    case "$1" in
        --provider) provider="$2"; shift 2 ;;
        --only) shift; while [ $# -gt 0 ] && [[ "$1" != --* ]]; do only+=("$1"); shift; done ;;
        --real-library) real_library=1; shift ;;
        --dev) dev=1; shift ;;
        --keep-scratch) shift ;;            # accepted for symmetry: the scratch folder is never deleted
        -h|--help) sed -n 2,28p "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "run_blender_tests.sh: unknown option $1" >&2; exit 2 ;;
    esac
done
case "$provider" in
    stub|real) providers=("$provider") ;;
    all) providers=(stub real) ;;
    *) echo "run_blender_tests.sh: --provider must be stub, real or all" >&2; exit 2 ;;
esac
if [ ! -x "$BL" ]; then echo "run_blender_tests.sh: Blender not found at $BL (set BLENDER=...)" >&2; exit 2; fi
if [ "$("$PY39" -I -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" != "3.9" ]; then
    echo "run_blender_tests.sh: $PY39 is not Python 3.9" >&2; exit 2
fi

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/mjolnir-run.XXXXXX")"; export SCRATCH   # a fresh private folder outside the repo; nothing is deleted
case "$SCRATCH" in "$REPO"|"$REPO"/*) echo "run_blender_tests.sh: scratch folder inside the repository: $SCRATCH" >&2; exit 2 ;; esac
mkdir -p "$SCRATCH/dist"
export BLENDER_USER_RESOURCES="$SCRATCH/user_res"      # PLURAL; the singular name is silently ignored
export PYTHONUNBUFFERED=1
echo "scratch: $SCRATCH"

cd "$REPO" || exit 2

# --- originals: fingerprint before, compare after ------------------------------------------------------------------------
REAL_MVAR="${MJOLNIR_REAL_MVAR:-$HOME/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar}"
fingerprint() {   # prints "<sha256> <mtime> <size> <path>" lines for every original this run must not touch
    local f
    for f in "$REPO/Addon/Resources/Halo Reach.blend" "$REPO/Addon/Resources/ForgeBridge.dll" "$REAL_MVAR" \
             "$HOME"/Local_Documents/Halo-MCC/variant-tool/test-samples/*.bin "$HOME"/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library/macos/Fixtures/*.bin; do
        [ -f "$f" ] && echo "$(shasum -a 256 "$f" | cut -d' ' -f1) $(stat -f '%m %z' "$f") $f"
    done
}
fingerprint > "$SCRATCH/originals.before"

if [ $dev -eq 1 ]; then
    mkdir -p "$BLENDER_USER_RESOURCES/scripts/addons"
    ln -s "$REPO/Addon" "$BLENDER_USER_RESOURCES/scripts/addons/mjolnir_forge"
    ADD=mjolnir_forge
    # the dev loop must not leave bytecode in Addon/: Blender's Python ignores PYTHON* variables unless it is started with
    # --python-use-system-env (used below), so the variables are cleaned first and PYTHONDONTWRITEBYTECODE is set
    unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE
    export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
else
    "$PY39" -I tools/build_package.py --out "$SCRATCH/dist" --allow-placeholders || { echo "PACKAGE BUILD FAILED"; exit 1; }
    zip="$(ls "$SCRATCH"/dist/mjolnir_forge-*.zip | head -n 1)"
    "$BL" --command extension install-file -r user_default "$zip" < /dev/null > "$SCRATCH/install.log" 2>&1
    status=$?
    cat "$SCRATCH/install.log"
    if [ $status -ne 0 ]; then echo "EXTENSION INSTALL FAILED ($status)"; exit 1; fi
    ADD=bl_ext.user_default.mjolnir_forge
fi
export MJOLNIR_ADDON_MODULE="$ADD"

failures=0
skipped=0
run_blender() {   # label script requirement args...      requirement: a regex the log must contain (the RESULT line)
    local label="$1" script="$2" requirement="$3"; shift 3
    local extra=()
    [ $dev -eq 1 ] && extra=(--python-use-system-env)
    "$BL" -b --factory-startup --python-exit-code 1 "${extra[@]}" --addons "$ADD" --python "$script" -- "$@" > "$SCRATCH/$label.log" 2>&1
    local status=$?
    echo "BLENDER_EXIT=$status ($label)"
    if { [ $status -ne 0 ] && [ $status -ne 3 ]; } || grep -q "^FAIL " "$SCRATCH/$label.log"; then
        cat "$SCRATCH/$label.log"
        failures=$((failures + 1))
    elif ! grep -Eq "$requirement" "$SCRATCH/$label.log"; then
        # exit 0 and no failure line, but the run never said how it ended (nothing ran, the script never reached its end)
        cat "$SCRATCH/$label.log"
        echo "run_blender_tests.sh: NO RESULT LINE in the $label run (expected /$requirement/): that is not a pass"
        failures=$((failures + 1))
    else
        grep -E "^(PASS|SKIP|B-[0-9]|run_all:|  SKIPPED)" "$SCRATCH/$label.log"
        if [ $status -eq 3 ] || grep -q "^SKIP " "$SCRATCH/$label.log"; then skipped=$((skipped + 1)); fi
    fi
}

for prov in "${providers[@]}"; do
    echo
    echo "=== provider: $prov$([ $real_library -eq 1 ] && echo ', real object library (read-only)') ==="
    args=(--provider "$prov")
    [ ${#only[@]} -gt 0 ] && args+=(--only "${only[@]}")
    [ $real_library -eq 1 ] && args+=(--real-library)
    if [ ${#only[@]} -eq 0 ] || [[ " ${only[*]} " == *" b01 "* ]]; then
        run_blender "b01_$prov" tests/blender/b01_startup.py '^PASS b01' --provider "$prov"
    fi
    run_blender "run_all_$prov" tests/blender/run_all.py '^run_all: RESULT: (PASSED|FAILED|SKIPPED)$' "${args[@]}"
done

# --- the originals did not change --------------------------------------------------------------------------------------------
fingerprint > "$SCRATCH/originals.after"
if ! cmp -s "$SCRATCH/originals.before" "$SCRATCH/originals.after"; then
    echo "ORIGINALS CHANGED during the run (sha256, mtime, size, path):"
    diff "$SCRATCH/originals.before" "$SCRATCH/originals.after"
    failures=$((failures + 1))
else
    echo "originals untouched: $(wc -l < "$SCRATCH/originals.after" | tr -d ' ') files (sha256, mtime, size) identical before and after"
fi

echo
if [ $failures -gt 0 ]; then
    echo "run_blender_tests.sh: $failures BLENDER RUN(S) FAILED (logs in $SCRATCH)"
    exit 1
fi
if [ $skipped -gt 0 ]; then
    echo "run_blender_tests.sh: SKIPPED: no test failed, but tests were skipped (see the SKIPPED lines above); this is not a pass ($ADD, provider $provider; logs in $SCRATCH)"
    exit 3
fi
echo "run_blender_tests.sh: ALL BLENDER RUNS PASSED ($ADD, provider $provider$([ $real_library -eq 1 ] && echo ', real library'))"
exit 0
