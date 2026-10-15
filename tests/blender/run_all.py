"""Runs the headless Blender tests of SPEC 9.4 in one Blender process.

    blender -b --factory-startup --python-exit-code 1 --addons bl_ext.user_default.mjolnir_forge \\
        --python tests/blender/run_all.py -- --provider stub [--only b02 b05] [--real-library]

Options after ``--``: ``--provider stub|real`` (stub = the canned provider of ``tests/stubs``; real = the
library behind the add-on), ``--only ID...`` (file name prefixes such as ``b02``), ``--real-library`` (link the
real ``Halo Reach.blend`` read-only instead of the synthetic stand-in; a local run), ``--addon-module NAME``
(default ``bl_ext.user_default.mjolnir_forge``, or ``$MJOLNIR_ADDON_MODULE``; the legacy development loop uses
``mjolnir_forge``).

The add-on must be enabled at STARTUP by ``--addons`` (this is what exposes a ``bpy.data`` access in
``register()``). Each test gets an emptied scene (see ``bl_common.Env.reset``).

Which tests run: ``--provider stub`` runs every file that has a ``run`` (the glue against the canned provider);
files that exist only for the real library (``REAL_ONLY``, no ``run``) are not part of a stub run. ``--provider real``
runs the whole catalogue of SPEC 9.4: ``run_real`` where a file has one, else a provider-agnostic ``run``; a file
that has neither is SKIPPED with the reason, which is never a pass.

Exit status: 0 only when every test PASSED; 1 when any test FAILED (or none was found); 3 when nothing failed but
some test was SKIPPED (a skipped test proves nothing, so a run with skips is never reported as green; the last line
says ``RESULT: SKIPPED``). The last line is always ``run_all: RESULT: PASSED|FAILED|SKIPPED`` (the shell driver
requires it, so a run that printed nothing can never count as a pass).
"""
import glob
import importlib.util
import os
import sys
import time

sys.dont_write_bytecode = True                  # keep __pycache__ out of the work tree
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bl_common  # noqa: E402

EXIT_SKIPPED = 3                                # no failure, but not every test ran


def discover(only):
    paths = sorted(glob.glob(os.path.join(HERE, "b[0-9][0-9]*_*.py")))
    if only:
        paths = [p for p in paths if any(os.path.basename(p).startswith(o) for o in only)]
    return paths


def selected_for(module, provider):
    """True when the file belongs to a run with ``provider`` (a real-only file is not part of a stub run)."""
    if provider == "stub":
        return getattr(module, "run", None) is not None
    return getattr(module, "REAL_VARIANT", None) is None      # B-03 under the real provider is b03r_persist_real.py


def load(path):
    spec = importlib.util.spec_from_file_location("mjolnir_btest_" + os.path.basename(path)[:-3], path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    args = bl_common.parse_args()
    paths = discover(args["only"])
    if not paths:
        print("run_all: no test matches %s" % args["only"])
        print("run_all: RESULT: FAILED")
        sys.exit(1)
    if args["real_library"] and not os.path.isfile(bl_common.REAL_LIBRARY):
        print("run_all: --real-library: %s not found" % bl_common.REAL_LIBRARY)
        print("run_all: RESULT: FAILED")
        sys.exit(1)
    env = bl_common.Env(args)
    results = []
    start = time.time()
    for path in paths:
        module = load(path)
        if not selected_for(module, args["provider"]):
            continue
        test_id = getattr(module, "ID", os.path.basename(path)[:3])
        t0 = time.time()
        status, detail = bl_common.run_test(module, test_id, env)
        results.append((test_id, getattr(module, "TITLE", ""), status, detail))
        line = "%s %s %s (%.2fs)" % (status, test_id, getattr(module, "TITLE", ""), time.time() - t0)
        print(line)
        if status != "PASS":
            print(detail)
        sys.stdout.flush()
    env.cleanup()
    if not results:
        print("run_all: no test ran (provider %s, only %s)" % (args["provider"], args["only"]))
        print("run_all: RESULT: FAILED")
        sys.exit(1)
    counts = dict((s, sum(1 for r in results if r[2] == s)) for s in ("PASS", "FAIL", "SKIP"))
    print("run_all: provider=%s library=%s: %d passed, %d failed, %d skipped in %.1fs" % (
        args["provider"], "real" if args["real_library"] else "stand-in", counts["PASS"], counts["FAIL"],
        counts["SKIP"], time.time() - start))
    for test_id, title, status, detail in results:
        if status == "SKIP":
            print("  SKIPPED %s: %s" % (test_id, detail))
    if counts["FAIL"]:
        verdict, code = "FAILED", 1
    elif counts["SKIP"]:
        verdict, code = "SKIPPED", EXIT_SKIPPED
    else:
        verdict, code = "PASSED", 0
    print("run_all: RESULT: %s" % verdict)
    sys.exit(code)


main()
