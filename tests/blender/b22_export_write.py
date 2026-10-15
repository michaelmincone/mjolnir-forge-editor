"""B-22 (extra, SPEC 8.5 steps 4 to 7, 2.13): the export writes through ``P.write_atomic`` and reports what happened.

* **Write path.** The only thing allowed to write the output file is ``provider.write_atomic`` (temp file in the
  same folder, ``os.replace``, never the source, never a protected folder). The test records the call (target, bytes,
  source paths, protected=None) and makes every other write below the test folder fail: a glue that used a plain
  ``open(target, 'wb')``, ``io.open``, ``pathlib`` or ``os.open`` instead would fail here.
* **Report after the write.** The text datablock ``Mjolnir Export Report`` and the console say ``ok`` only about a file
  that exists: no report exists yet when the writer runs, and an ``OSError`` or a ``PathPolicyError`` from the
  writer gives ``Result: FAILED`` (never ``Result: ok``) with ``E_WRITE_FAILED``, an ERROR to the caller and no file.
* **Short console.** An export prints a few lines (outcome, problems, a pointer to the text), not the whole report;
  every stats key is written once in the report.
* **Options.** ``ExportOptions`` carries what the user set: the two scene checkboxes and the three operator options,
  each one independently (a swapped pair would show), and (decision D11) the opt-in ``raise_quota_max``.

Real variant (``run_real``, G6): the same with the REAL library. The write goes through ``P.write_atomic`` of the real
``mvarlib.api`` (recorded, every other write below the test folder fails); a writer that raises ``OSError``, ``PathPolicyError``
OR ``ValueError`` (polish item 1) gives ``Result: FAILED`` and an ERROR, never a traceback and never a stale ``ok``; the console is
short; and each option is proved by its EFFECT on the file: ``hash_policy`` gives the independent builder's ``plain_le32`` fixture,
``force_reencode`` the forced mode with the same bytes, ``fsm_policy`` removes the ``_fsm`` block, the two scene checkboxes
(each one alone) let a rotation and an unrecognised object through, ``raise_quota_max`` alone lets a full quota row grow.
"""
import builtins
import errno
import io
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq, check_raises  # noqa: E402

ID = "b22"
TITLE = "export: written through P.write_atomic, report after the write, short console, options from the UI"
NEEDS_STUB = True

PAYLOAD = b"B22-TEMPLATE\x00\x01\x02\x03"
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class WriteGuard(object):
    """Records ``write_atomic`` calls and fails every other file write below ``folder``."""

    def __init__(self, folder):
        self.folder = os.path.realpath(folder)
        self.depth = 0                       # > 0 while the recorded write_atomic runs
        self.calls = []
        self.violations = []
        self.report_existed_at_call = None
        self._saved = {}

    def _under(self, path):
        try:
            real = os.path.realpath(os.fspath(path))
        except (TypeError, ValueError):      # a file descriptor
            return False
        return real == self.folder or real.startswith(self.folder + os.sep)

    def _refuse_if_write(self, what, path, writing):
        if writing and not self.depth and self._under(path):
            self.violations.append((what, os.fspath(path)))
            raise AssertionError("%s(%r) wrote below the test folder without going through write_atomic" % (what, path))

    def recorder(self, original, env):
        def write_atomic(*args, **kwargs):
            self.calls.append((args, kwargs))
            self.report_existed_at_call = bpy.data.texts.get(env.io_ops.REPORT_NAME) is not None
            self.depth += 1
            try:
                return original(*args, **kwargs)
            finally:
                self.depth -= 1
        return write_atomic

    def __enter__(self):
        guard = self
        real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

        def guarded_open(file, mode="r", *args, **kwargs):
            guard._refuse_if_write("open", file, any(c in str(mode) for c in "wax+"))
            return real_open(file, mode, *args, **kwargs)

        def guarded_io_open(file, mode="r", *args, **kwargs):
            guard._refuse_if_write("io.open", file, any(c in str(mode) for c in "wax+"))
            return real_io_open(file, mode, *args, **kwargs)

        def guarded_os_open(path, flags, *args, **kwargs):
            guard._refuse_if_write("os.open", path, bool(flags & WRITE_FLAGS))
            return real_os_open(path, flags, *args, **kwargs)

        self._saved = {"open": real_open, "io.open": real_io_open, "os.open": real_os_open}
        builtins.open, io.open, os.open = guarded_open, guarded_io_open, guarded_os_open
        return self

    def __exit__(self, *exc):
        builtins.open, io.open, os.open = self._saved["open"], self._saved["io.open"], self._saved["os.open"]
        return False


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def export_raw(path, **kwargs):
    """Run the operator; ``(result set or None, error text or None)``."""
    try:
        return bpy.ops.export_scene.mjolnir_mvar(filepath=path, **kwargs), None
    except RuntimeError as exc:
        return None, str(exc)


def drop_report():
    text = bpy.data.texts.get("Mjolnir Export Report")
    if text is not None:
        bpy.data.texts.remove(text)


def failing_writer(exc):
    def writer(*args, **kwargs):
        raise exc
    return writer


def run(env):
    stub = env.stub
    scene = bpy.context.scene
    source = env.write_template("b22_source.mvar", PAYLOAD)
    env.import_stub(path=source)
    target = os.path.join(env.tmp, "b22.mvar")

    # --- the guard itself works (a plain write below the folder fails), so passing below means something ----------------
    plain = os.path.join(env.tmp, "plain.mvar")
    with WriteGuard(env.tmp):
        check_raises(AssertionError, open, plain, "wb")
        check_raises(AssertionError, io.open, plain, "wb")
        check_raises(AssertionError, os.open, plain, os.O_WRONLY | os.O_CREAT)
        with open(source, "rb") as fh:                      # reading is fine
            check_eq(fh.read(), PAYLOAD)
    check(not os.path.exists(plain), "the guard stopped the plain writes")

    # --- the export goes through P.write_atomic, and the report is written after it ---------------------------------------
    check(bpy.data.texts.get("Mjolnir Export Report") is None, "no report yet")
    guard = WriteGuard(env.tmp)
    with guard, bl_common.patched(stub, "write_atomic", guard.recorder(stub.write_atomic, env)):
        with bl_common.capture_output() as out:
            result, error = export_raw(target)
    check_eq((result, error), ({'FINISHED'}, None), "export")
    check_eq(guard.violations, [], "nothing else wrote a file")
    check_eq(len(guard.calls), 1, "write_atomic was called exactly once")
    args, kwargs = guard.calls[0]
    check_eq(kwargs, {})
    check_eq(len(args), 4, "target, data, source_paths, protected")
    check_eq(args[0], target, "the target the user chose")
    check_eq(bytes(args[1]), PAYLOAD, "the bytes the library returned (the stub hands the template back)")
    check_eq(list(args[2]), [source], "the imported file is a source path: it can never be overwritten")
    check_eq(args[3], None, "the built-in protected folders")
    check_eq(guard.report_existed_at_call, False, "the report is written after the file, not before")
    check_eq(read_bytes(target), PAYLOAD, "the file on disk")
    leftovers = sorted(n for n in os.listdir(env.tmp) if ".tmp-" in n)
    check_eq(leftovers, [], "no temporary file is left behind")
    report = env.report_text()
    check("Result: ok, file written" in report, report)
    check_eq(report.count("Result:"), 1)
    check("FAILED" not in report and "REFUSED" not in report, report)

    # --- the console is short, the report is complete, every stats key appears once -------------------------------------
    console = [line for line in out[0].splitlines() if line.startswith("Mjolnir:")]
    check(1 <= len(console) <= 5, "console lines: %r" % console)
    check(console[0].startswith("Mjolnir: export OK: b22.mvar (0 error(s)"), console[0])
    check(any("full report: text 'Mjolnir Export Report'" in line for line in console), console)
    for needle in ("Template:", "Stats", "Changes", "KEPT slot", "Bits used", "Hash:"):
        check(needle not in out[0], "the console must not echo the report (%r): %s" % (needle, out[0]))
    check("KEPT slot 1" in report and "KEPT slot 11" in report, "the report lists every change")
    check("Objects: 5 before, 5 after (limit 650)" in report, report)
    check("Bits used: 0 of 229,376" in report and "Stored stream length L: 0" in report and "Hash: stub" in report, report)
    for key in ("occupied_before", "occupied_after", "end_bit", "capacity_bits", "hash_flavour", "  L:"):
        check(key not in report, "stats key %r is already said by a summary line:\n%s" % (key, report))
    check_eq(report.count("quota_changes:"), 1)
    check_eq(report.count("mode:"), 1)
    template = stub.LAST_EXPORT[0]
    stub.NEXT_EXPORT = stub.ExportResult(ok=True, data=template, diff=[], errors=[], warnings=[],
                                         stats={"mode": "patched", "zzz_extra": 7, "L": 12, "end_bit": 5})
    result, error = export_raw(os.path.join(env.tmp, "b22_stats.mvar"))
    check_eq(result, {'FINISHED'})
    report = env.report_text()
    check_eq(report.count("zzz_extra: 7"), 1, "an unknown stats key is written once")
    check_eq(report.count("mode: patched"), 1)
    check_eq(report.count("Stored stream length L: 12"), 1)
    check("end_bit: 5" in report, "end_bit alone (no capacity) is not lost:\n" + report)
    check("Bits used" not in report)

    # --- a write that fails never reports ok ----------------------------------------------------------------------------
    failing_target = os.path.join(env.tmp, "b22_fail.mvar")
    for label, exc, needle in (
            ("OSError", OSError(errno.ENOSPC, "No space left on device"), "No space left on device"),
            ("PathPolicyError", stub.PathPolicyError("Refusing to write: the target is a folder, not a file."),
             "Refusing to write: the target is a folder, not a file.")):
        drop_report()
        with bl_common.patched(stub, "write_atomic", failing_writer(exc)):
            with bl_common.capture_output() as out:
                result, error = export_raw(failing_target)
        check(result is None and error is not None, "%s: the operator reports an ERROR: %r" % (label, result))
        check("Export failed, nothing was written" in error and needle in error, "%s: %s" % (label, error))
        check(not os.path.exists(failing_target), "%s: no file" % label)
        report = env.report_text()
        check(report != "", "%s: the report exists" % label)
        check("Result: ok" not in report and "ok, file written" not in report, "%s: the report must not say ok:\n%s" % (label, report))
        check("Result: FAILED, nothing was written" in report, "%s:\n%s" % (label, report))
        check("ERROR E_WRITE_FAILED: " in report and needle in report, "%s:\n%s" % (label, report))
        check("Problems (1 error(s), 0 warning(s))" in report, report)
        check("export FAILED: b22_fail.mvar" in out[0] and "export OK" not in out[0], "%s console: %s" % (label, out[0]))
        check(sum(1 for line in out[0].splitlines() if line.startswith("Mjolnir:")) <= 5, out[0])

    # the same with the real writer: the target's parent is a regular file, so the folder cannot be made
    blocker = env.write_template("b22_blocker", b"not a folder")
    impossible = os.path.join(blocker, "sub", "out.mvar")
    drop_report()
    result, error = export_raw(impossible)
    check(result is None and error is not None and "Export failed, nothing was written" in error, repr((result, error)))
    report = env.report_text()
    check("Result: FAILED" in report and "Result: ok" not in report and "E_WRITE_FAILED" in report, report)
    check(not os.path.exists(impossible))
    check_eq(read_bytes(blocker), b"not a folder", "the blocking file is untouched")
    check_eq(read_bytes(source), PAYLOAD, "the imported file is untouched")

    # a failed export after a good one replaces the "ok" report (the text is never stale)
    drop_report()
    result, error = export_raw(target)
    check_eq(result, {'FINISHED'})
    check("Result: ok, file written" in env.report_text())
    with bl_common.patched(stub, "write_atomic", failing_writer(OSError(errno.EIO, "Input/output error"))):
        result, error = export_raw(os.path.join(env.tmp, "b22_later.mvar"))
    check(result is None)
    check("Result: ok" not in env.report_text() and "Result: FAILED" in env.report_text(), env.report_text())
    check_eq(len([t for t in bpy.data.texts if t.name == "Mjolnir Export Report"]), 1, "one report datablock, replaced")

    # --- the options reach the library exactly as set ---------------------------------------------------------------------
    cases = [
        # (allow rotation, keep unrecognised, force_reencode, fsm_policy, hash_policy)
        (True, False, False, "KEEP", "REPRODUCE"),
        (False, True, False, "KEEP", "REPRODUCE"),
        (False, False, True, "KEEP", "REPRODUCE"),
        (False, False, False, "DROP", "REPRODUCE"),
        (False, False, False, "KEEP", "SALTED_BE32"),
        (False, False, False, "KEEP", "PLAIN_LE32"),
        (True, True, True, "DROP", "PLAIN_LE32"),
        (False, False, False, "KEEP", "REPRODUCE"),
    ]
    for allow, keep, force, fsm, hash_policy in cases:
        scene.forge.allowUnverifiedRotation = allow
        scene.forge.keepUnrecognisedObjects = keep
        result, path = env.export_to("b22_options.mvar", force_reencode=force, fsm_policy=fsm, hash_policy=hash_policy)
        check_eq(result, {'FINISHED'}, "export with %r" % ((allow, keep, force, fsm, hash_policy),))
        got_template, objects, options = stub.LAST_EXPORT
        got = (options.allow_unverified_rotation, options.keep_unrecognised_imported, options.force_reencode,
               options.fsm_policy, options.hash_policy)
        check_eq(got, (allow, keep, force, fsm, hash_policy), "ExportOptions built from the UI")
        check_eq(options.imported_slots, [1, 2, 5, 9, 11])
        check_eq(options.max_objects, 650)
        check_eq(options.raise_quota_max, False, "D11: the quota option stays off unless it is ticked")
        check_eq(got_template, PAYLOAD, "the embedded template")
        check_eq(len(objects), 5)

    # --- B-22b (decision D11): "Raise quota maximum (unverified)" reaches ExportOptions.raise_quota_max, alone ------------
    prop = bpy.ops.export_scene.mjolnir_mvar.get_rna_type().properties["raise_quota_max"]
    check_eq(prop.name, "Raise quota maximum (unverified)")
    check_eq(prop.default, False, "default off")
    check("UNVERIFIED" in prop.description and "Never lowers" in prop.description, prop.description)
    scene.forge.allowUnverifiedRotation = False
    scene.forge.keepUnrecognisedObjects = False
    for flag in (True, False, True):
        result, path = env.export_to("b22_quota.mvar", raise_quota_max=flag)
        check_eq(result, {'FINISHED'}, "export with raise_quota_max=%r" % flag)
        got_template, objects, options = stub.LAST_EXPORT
        check_eq(options.raise_quota_max, flag, "ExportOptions.raise_quota_max built from the UI")
        check_eq((options.allow_unverified_rotation, options.keep_unrecognised_imported, options.force_reencode,
                  options.fsm_policy, options.hash_policy), (False, False, False, "KEEP", "REPRODUCE"),
                 "the other options are not disturbed by the new one")

    # --- many problems: the console shows a handful, the report all of them ---------------------------------------------
    env.reset()
    env.import_stub(load=stub.CANNED_PLACEMENT_ALL)
    mirrored = env.forge_objects()[:30]
    for obj in mirrored:
        obj.scale = (-1.0, 1.0, 1.0)
    with bl_common.capture_output() as out:
        result, error = export_raw(os.path.join(env.tmp, "b22_many.mvar"))
    check(result is None and "Export refused: 30 problem(s)" in error, repr((result, error)))
    report = env.report_text()
    check_eq(report.count("ERROR E_MIRRORED"), 30, "the report lists every problem")
    check("Result: REFUSED, nothing was written" in report and "Result: ok" not in report)
    console = [line for line in out[0].splitlines() if line.startswith("Mjolnir:")]
    check(len(console) <= 3 + env.io_ops.MAX_CONSOLE_PROBLEMS, "the console stays short (%d lines)" % len(console))
    check(any("and 18 more problem(s)" in line for line in console), console)
    check(not os.path.exists(os.path.join(env.tmp, "b22_many.mvar")))


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def run_real(env):
    scene = bpy.context.scene
    P = env.provider.get_provider()
    w1 = rd.fixture("w1_minimal")
    source = os.path.join(env.tmp, "b22_source.mvar")
    with open(source, "wb") as fh:
        fh.write(w1)
    check_eq(env.import_file(source), {'FINISHED'})
    target = os.path.join(env.tmp, "b22.mvar")

    # --- the guard itself works, so passing below means something ------------------------------------------------------------
    plain = os.path.join(env.tmp, "plain.mvar")
    with WriteGuard(env.tmp):
        check_raises(AssertionError, open, plain, "wb")
        check_raises(AssertionError, os.open, plain, os.O_WRONLY | os.O_CREAT)
    check(not os.path.exists(plain))

    # --- the export goes through P.write_atomic, and the report is written after it ---------------------------------------------
    check(bpy.data.texts.get("Mjolnir Export Report") is None, "no report yet")
    guard = WriteGuard(env.tmp)
    with guard, bl_common.patched(P, "write_atomic", guard.recorder(P.write_atomic, env)):
        with bl_common.capture_output() as out:
            result, error = export_raw(target)
    check_eq((result, error), ({'FINISHED'}, None), "export")
    check_eq(guard.violations, [], "nothing else wrote a file")
    check_eq(len(guard.calls), 1, "write_atomic was called exactly once")
    args, kwargs = guard.calls[0]
    check_eq((kwargs, len(args), args[0], bytes(args[1]), list(args[2]), args[3]), ({}, 4, target, w1, [source], None))
    check_eq(guard.report_existed_at_call, False, "the report is written after the file, not before")
    check_eq(read_bytes(target), w1, "the file on disk")
    check_eq(sorted(n for n in os.listdir(env.tmp) if ".tmp-" in n), [], "no temporary file is left behind")
    report = env.report_text()
    check("Result: ok, file written" in report and report.count("Result:") == 1 and "FAILED" not in report and "REFUSED" not in report, report)

    # --- the console is short, the report is complete, every stats key appears once ----------------------------------------------------
    console = [line for line in out[0].splitlines() if line.startswith("Mjolnir:")]
    check(1 <= len(console) <= 5, "console lines: %r" % console)
    check(console[0].startswith("Mjolnir: export OK: b22.mvar (0 error(s)"), console[0])
    for needle in ("Template:", "Stats", "Changes", "KEPT slot", "Bits used", "Hash:"):
        check(needle not in out[0], "the console must not echo the report (%r): %s" % (needle, out[0]))
    check("KEPT slot 1 " in report and "KEPT slot 650 " in report and "Objects: 3 before, 3 after (limit 650)" in report, report)
    check("Bits used: 4,970 of 229,376" in report and "Stored stream length L: 622" in report and "Hash: salted_be32/>" in report, report)
    for key in ("occupied_before", "occupied_after", "end_bit", "capacity_bits", "hash_flavour", "  L:"):
        check(key not in report, "stats key %r is already said by a summary line:\n%s" % (key, report))
    check_eq((report.count("quota_changes:"), report.count("mode:")), (1, 1))

    # --- a write that fails never reports ok (OSError, PathPolicyError, and ANY other exception: polish item 1) --------------------------
    failing_target = os.path.join(env.tmp, "b22_fail.mvar")
    for label, exc, needle in (
            ("OSError", OSError(errno.ENOSPC, "No space left on device"), "No space left on device"),
            ("PathPolicyError", P.PathPolicyError("Refusing to write: the target is a folder, not a file."),
             "Refusing to write: the target is a folder, not a file."),
            ("ValueError", ValueError("bad value from the writer"), "ValueError: bad value from the writer"),
            ("TypeError", TypeError("not bytes"), "TypeError: not bytes")):
        export_raw(target)                                           # a good export first: its "ok" report must not survive
        check("Result: ok, file written" in env.report_text())
        with bl_common.patched(P, "write_atomic", failing_writer(exc)):
            with bl_common.capture_output(stderr=True) as out:
                result, error = export_raw(failing_target)
        check(result is None and error is not None, "%s: the operator reports an ERROR: %r" % (label, result))
        check("Export failed, nothing was written" in error and needle in error, "%s: %s" % (label, error))
        check(not os.path.exists(failing_target), "%s: no file" % label)
        report = env.report_text()
        check("Result: ok" not in report and "ok, file written" not in report, "%s: a stale ok report:\n%s" % (label, report))
        check("Result: FAILED, nothing was written" in report and "ERROR E_WRITE_FAILED: " in report and needle in report, "%s:\n%s" % (label, report))
        check("Problems (1 error(s), 0 warning(s))" in report, report)
        check("export FAILED: b22_fail.mvar" in out[0] and "export OK" not in out[0], "%s console: %s" % (label, out[0]))
        check("Traceback" not in out[0], "%s: a FAILED report, not a traceback:\n%s" % (label, out[0]))
        check(sum(1 for line in out[0].splitlines() if line.startswith("Mjolnir:")) <= 5, out[0])
    # the real writer: the parent of the target is a regular file, so the folder cannot be made
    blocker = os.path.join(env.tmp, "b22_blocker")
    with open(blocker, "wb") as fh:
        fh.write(b"not a folder")
    impossible = os.path.join(blocker, "sub", "out.mvar")
    result, error = export_raw(impossible)
    check(result is None and error is not None and "Export failed, nothing was written" in error, repr((result, error)))
    report = env.report_text()
    check("Result: FAILED" in report and "Result: ok" not in report and "E_WRITE_FAILED" in report, report)
    check_eq(read_bytes(blocker), b"not a folder")
    check_eq(read_bytes(source), w1, "the imported file is untouched")
    check_eq(len([t for t in bpy.data.texts if t.name == "Mjolnir Export Report"]), 1, "one report datablock, replaced")

    # --- the options reach the library: proved by their effect on the file ---------------------------------------------------------------
    def out_bytes(name="b22_opt.mvar", **options):
        result, path = env.export_to(name, **options)
        check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (options, result, env.report_text()[:1500]))
        return rd.read_bytes(path)

    plain_le32 = rd.fixture("plain_le32")
    check(rd.changed_bytes(w1, plain_le32) and set(rd.changed_bytes(w1, plain_le32)) <= set(range(rd.HASH_AT, rd.HASH_AT + 20)),
          "the plain_le32 fixture is W1 with another SHA-1")
    check(out_bytes(hash_policy="PLAIN_LE32") == plain_le32, "hash_policy PLAIN_LE32: the independent builder's plain_le32 fixture")
    check(out_bytes(hash_policy="SALTED_BE32") == w1, "hash_policy SALTED_BE32 on a salted template: unchanged")
    check(out_bytes(hash_policy="REPRODUCE") == w1, "REPRODUCE keeps the template's recipe")
    out = out_bytes(force_reencode=True)
    check(out == w1 and "mode: forced" in env.report_text(), "force_reencode: the whole stream rewritten, the same bytes, mode forced")
    # fsm_policy: a template with an _fsm block keeps it (KEEP) or loses it (DROP)
    fsm = rd.fixture("fsm")
    env.reset()
    fsm_path = os.path.join(env.tmp, "b22_fsm.mvar")
    with open(fsm_path, "wb") as fh:
        fh.write(fsm)
    check_eq(env.import_file(fsm_path), {'FINISHED'})
    check(out_bytes("b22_fsm_keep.mvar", fsm_policy="KEEP") == fsm, "fsm_policy KEEP: the template, _fsm block included")
    dropped = out_bytes("b22_fsm_drop.mvar", fsm_policy="DROP")
    check(len(dropped) < len(fsm) and b"_fsm" in fsm and b"_fsm" not in dropped, "fsm_policy DROP removes the _fsm block (%d -> %d bytes)" % (len(fsm), len(dropped)))
    check_eq(rd.read_result(dropped)["shape"], "plain4")
    check_eq(rd.read_result(fsm)["shape"], "plain4+fsm")

    # each scene checkbox ALONE does its own job (a swapped pair would show)
    env.reset()
    env.import_bytes(rd.fixture("holes"), "b22_holes.mvar")
    scene = bpy.context.scene
    scene.forge.allowUnverifiedRotation = True
    scene.forge.keepUnrecognisedObjects = False
    result, path = env.export_to("b22_swap1.mvar")
    check(isinstance(result, RuntimeError) and "E_OBJ_NOT_STOCK" in env.report_text(), "only the rotation gate ticked: unrecognised objects are still refused")
    scene.forge.allowUnverifiedRotation = False
    scene.forge.keepUnrecognisedObjects = True
    check(out_bytes("b22_swap2.mvar") == rd.fixture("holes"), "only 'keep unrecognised' ticked: they are kept")
    env.reset()
    env.import_bytes(w1, "b22_w1b.mvar")
    scene = bpy.context.scene
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    by[1].rotation_euler.z = 0.5
    scene.forge.allowUnverifiedRotation = False
    scene.forge.keepUnrecognisedObjects = True
    result, path = env.export_to("b22_swap3.mvar")
    check(isinstance(result, RuntimeError) and "E_ROTATION_GATED" in env.report_text(), "only 'keep unrecognised' ticked: a rotation is still gated")
    scene.forge.allowUnverifiedRotation = True
    scene.forge.keepUnrecognisedObjects = False
    after = rd.decode(out_bytes("b22_swap4.mvar"))
    check(after["slots"][1]["angle"] != 8192, "only the rotation gate ticked: the rotation is written")

    # raise_quota_max alone lets a full quota row grow; the other options are not needed for it
    env.reset()
    env.import_bytes(w1, "b22_quota.mvar")
    scene = bpy.context.scene
    scene.forge.allowUnverifiedRotation = True            # a new object needs the gate; the quota option is the one under test
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    twin = by[5].copy()                                   # Kill Boundary: row 61 holds at most 1
    scene.collection.objects.link(twin)
    twin.location.x += 4.0
    result, path = env.export_to("b22_quota_off.mvar", raise_quota_max=False)
    check(isinstance(result, RuntimeError) and "E_QUOTA" in env.report_text(), "raise_quota_max off: E_QUOTA")
    after = rd.decode(out_bytes("b22_quota_on.mvar", raise_quota_max=True))
    check_eq(after["quotas"][61], [0, 2, 2], "raise_quota_max on: the row grows")
    check("W_QUOTA_MAX_RAISED" in env.report_text())

    # --- many problems: the console shows a handful, the report all of them ---------------------------------------------------------------
    env.reset()
    import b21_symmetry_import as b21
    env.import_bytes(b21.placement_all_data(), "b22_many.mvar")
    for obj in env.forge_objects()[:30]:
        obj.scale = (-1.0, 1.0, 1.0)
    with bl_common.capture_output() as out:
        result, error = export_raw(os.path.join(env.tmp, "b22_many_out.mvar"))
    check(result is None and "Export refused: 30 problem(s)" in error, repr((result, error)))
    report = env.report_text()
    check_eq(report.count("ERROR E_MIRRORED"), 30, "the report lists every problem")
    check("Result: REFUSED, nothing was written" in report and "Result: ok" not in report)
    console = [line for line in out[0].splitlines() if line.startswith("Mjolnir:")]
    check(len(console) <= 3 + env.io_ops.MAX_CONSOLE_PROBLEMS, "the console stays short (%d lines)" % len(console))
    check(any("and 18 more problem(s)" in line for line in console), console)
    check(not os.path.exists(os.path.join(env.tmp, "b22_many_out.mvar")))


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
