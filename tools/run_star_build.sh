#!/bin/bash
# Build the block star: runs tools/build_star_mvar.py in headless Blender with the add-on from this working tree.
#
#   tools/run_star_build.sh --template TEMPLATE.mvar --out NEW.mvar [any other option of build_star_mvar.py]
#
# Everything after the script name is handed to build_star_mvar.py (see its --help):
#   --provider real|stub|stub-roundtrip (default real)   --real-library   --block auto|NAME   --cells N|auto   --outline
#   --dry-run   --center X,Y,Z   --margin M   --overwrite ...
#
# What this wrapper adds: an ISOLATED Blender profile (BLENDER_USER_RESOURCES, plural) in a fresh scratch folder
# outside the repository, with Addon/ linked into it as the legacy add-on "mjolnir_forge", enabled at startup. Your own
# Blender profile (~/Library/Application Support/Blender) is not touched, and nothing is installed. The scratch folder
# is left in place (a few kilobytes); its path is printed. No Python bytecode is written, so the run leaves nothing in the
# repository (Addon/ is linked in, and the add-on is imported before the script runs). Blender's embedded Python ignores
# PYTHONDONTWRITEBYTECODE unless it is started with --python-use-system-env, so this wrapper passes both; the other
# PYTHON* variables that could change the interpreter (PYTHONPATH, PYTHONHOME, ...) are cleared first.
#
# The object library is whatever the add-on resolves, in its own order: the add-on preference 'Library path' (empty in the
# isolated profile), then $MJOLNIR_LIBRARY, then <Addon>/Resources/Halo Reach.blend, which in this working tree is the REAL,
# read-only game library. The real one is only used when you pass --real-library (it sets $MJOLNIR_LIBRARY); without that
# flag the run is refused (exit 2) unless $MJOLNIR_LIBRARY names a stand-in library. The line "library  :" of the log names the
# file that is really linked.
#
# Relative --template / --out paths are resolved against the directory you run this from (the wrapper does not change
# directory). Absolute paths and ~ work as usual.
#
# Exit status is Blender's: 0 the star was built and verified, 1 something failed or a check failed, 2 the request was
# refused before anything was written (bad path, over the 650-object limit, centre outside the map, wrong library, ...).
set -o pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
BL="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    sed -n 2,28p "${BASH_SOURCE[0]}" | grep -v '^set '
    exit 0
fi
if [ ! -x "$BL" ]; then echo "run_star_build.sh: Blender not found at $BL (set BLENDER=...)" >&2; exit 2; fi

TMPBASE="$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)"
case "$TMPBASE" in ""|"$REPO"|"$REPO"/*) echo "run_star_build.sh: the temporary folder (${TMPDIR:-/tmp}) is missing or inside the repository" >&2; exit 2 ;; esac
SCRATCH="$(mktemp -d "$TMPBASE/mjolnir-star.XXXXXX")"
export BLENDER_USER_RESOURCES="$SCRATCH/user_res"          # PLURAL; the singular name is silently ignored
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE   # --python-use-system-env below would otherwise honour them
export PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1                           # honoured only with --python-use-system-env (next to --factory-startup)
mkdir -p "$BLENDER_USER_RESOURCES/scripts/addons"
ln -s "$REPO/Addon" "$BLENDER_USER_RESOURCES/scripts/addons/mjolnir_forge"
echo "run_star_build.sh: isolated profile $SCRATCH (add-on mjolnir_forge -> $REPO/Addon)"

"$BL" -b --factory-startup --python-use-system-env --python-exit-code 1 --addons mjolnir_forge \
    --python "$REPO/tools/build_star_mvar.py" -- "$@"
status=$?
echo "run_star_build.sh: Blender exit status $status"
exit $status
