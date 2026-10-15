"""File > Import / File > Export of map variant files (SPEC 8.4, 8.5, 8.12).

``import_scene.mjolnir_mvar`` and ``export_scene.mjolnir_mvar`` replace the old live-memory operators.
Both talk to the library ONLY through ``provider.get_provider()``: the glue builds every api object as
``P.ExportObject(...)`` / ``P.Issue(...)``, catches ``P.MvarError`` and never uses ``isinstance`` on api
types, so a stub provider with its own copy of the dataclasses works.

Export never changes the scene. It checks everything before a single byte is written, collects every
problem into one report (the text datablock ``Mjolnir Export Report``; the console gets a short summary
and every problem, not the whole report) and refuses before writing anything when a problem is an error.
Writing goes through ``write_atomic`` (temp file in the same folder, then ``os.replace``; never the source
file, never a protected folder) and the report is written AFTER it, so ``Result: ok`` is only ever said
about a file that exists; a write that fails gives ``Result: FAILED`` with ``E_WRITE_FAILED``.
"""
import os
import re
import sys
import traceback

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty
from bpy.types import Operator
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import mjolnir, palette, provider, state

MAX_IMPORT_BYTES = 1 << 20
REPORT_NAME = "Mjolnir Export Report"
FALLBACK_EXPORT_DIR = "~/Documents/Mjolnir Exports"
OUTPUT_SUFFIX = "_mjolnir.mvar"
MENU_TEXT = "Halo Reach Map Variant (.mvar)"
MENU_ICON = 'ANTIALIASED'
MAX_LISTED_WARNINGS = 5
MAX_CONSOLE_PROBLEMS = 12            # problem lines on the console; the text datablock has them all
MAX_IMPORT_TRACEBACKS = 3            # full tracebacks of failed objects printed during one import
MAX_IMPORT_KINDS = 5                 # failure kinds named in the summary line
MAX_CONSOLE_WARNINGS = 20            # library warnings printed during one import


# --- helpers -----------------------------------------------------------------------------------------
def library_version(P):
    """Version string of the library behind the provider ('' for the stub)."""
    version = getattr(P, "__version__", "")
    if not version:
        parent_name = getattr(P, "__name__", "").rpartition(".")[0]          # <package>.mvarlib.api -> <package>.mvarlib
        parent = sys.modules.get(parent_name) if parent_name else None
        version = getattr(parent, "__version__", "") if parent is not None else ""
    return str(version)


def path_issue(P, target, source_path):
    """The path-policy ``Issue`` for ``target`` (never the source file, never a protected folder), or ``None``."""
    sources = [source_path] if source_path else []
    issue = P.check_output_path(target, sources, None)
    if issue is None:
        extra = palette.extra_protected_folders()
        if extra:
            issue = P.check_output_path(target, sources, extra)
    return issue


def propose_output_path(P, source_path):
    """``<source dir>/<source stem>_mjolnir.mvar``, or the fallback folder when that is not allowed (2.13)."""
    stem = os.path.splitext(os.path.basename(source_path or "map"))[0] or "map"
    name = stem + OUTPUT_SUFFIX
    if source_path:
        candidate = os.path.join(os.path.dirname(os.path.abspath(source_path)), name)
        if path_issue(P, candidate, source_path) is None:
            return candidate
    return os.path.join(os.path.expanduser(FALLBACK_EXPORT_DIR), name)


def _issue(P, code, severity, message, obj_name=None, slot=None):
    return P.Issue(code, severity, message, slot, obj_name)


def _dedupe(issues):
    seen = set()
    out = []
    for issue in issues:
        key = (issue.code, issue.object_name, issue.slot, issue.message)
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return out


_FAILED_SLOT_NOT_STOCK = ("Slot %d ('%s') could not be imported and is not a stock object on %s, so it cannot be checked and "
                          "would be written without the stock check. Tick Forge Scene > \"Keep objects this tool does not "
                          "recognise\" to keep it exactly as it is, or choose a different file.")
_FAILED_SLOT_KEPT = ("Slot %d ('%s') could not be imported and is not a stock object on %s; it was kept exactly as it was "
                     "in the imported file, without the stock check.")


def failed_slot_issues(P, st, failed_nonstock, keep_unrecognised):
    """Glue problems for the slots that failed to import and whose object is not stock.

    The library keeps a slot it was told was not imported exactly as it is and runs no stock check on it
    (``W_SLOT_NOT_IMPORTED``), so without this a non-stock object could slip through an export that is meant to
    contain stock objects only. Refused by default (``E_FAILED_SLOT_NOT_STOCK``, the same rule as an imported
    unrecognised object, DEC-7.4); a warning (``W_FAILED_SLOT_KEPT``) when the user keeps unrecognised objects.
    """
    map_name = (st or {}).get("map_name") or "this map"
    issues = []
    for slot in sorted(failed_nonstock):
        name = failed_nonstock[slot]
        if keep_unrecognised:
            issues.append(_issue(P, "W_FAILED_SLOT_KEPT", "warning", _FAILED_SLOT_KEPT % (slot, name, map_name),
                                 "%d - %s" % (slot, name), slot))
        else:
            issues.append(_issue(P, "E_FAILED_SLOT_NOT_STOCK", "error", _FAILED_SLOT_NOT_STOCK % (slot, name, map_name),
                                 "%d - %s" % (slot, name), slot))
    return issues


class Collected(object):
    """Result of :func:`collect_export_objects`."""
    def __init__(self):
        self.objects = []
        self.errors = []
        self.warnings = []
        self.hidden = 0


def collect_export_objects(scene, context=None):
    """Scene -> ``[ExportObject]`` plus glue-level problems (SPEC 8.5 step 3).

    Pass B first (array instances from the evaluated depsgraph), then pass A over ``scene.objects``
    (eye-hidden, ``hide_viewport`` and excluded-collection objects included). An array source with no
    evaluated instance is refused with ``E_ARRAY_NOT_EVALUATED`` instead of being skipped (which would
    make its slot look deleted).
    """
    P = provider.get_provider()
    ctx = context or bpy.context
    ctx.view_layer.update()
    items = mjolnir.collect_forge_items(scene, ctx.evaluated_depsgraph_get(), ctx.view_layer)
    out = Collected()
    objs = out.objects
    for source, matrices in items.array_sources:
        for k, matrix in enumerate(matrices):
            name = source.name if k == 0 else "%s [%04d]" % (source.name, k)
            eo, problems = mjolnir.to_export_object(P, source, matrix, name=name, claim_slot=(k == 0),
                                                    from_array=(k > 0))
            objs.append(eo)
            out.errors.extend(problems)
    for obj in items.plain:
        hidden = mjolnir.is_hidden(obj, items.excluded)
        out.hidden += 1 if hidden else 0
        eo, problems = mjolnir.to_export_object(P, obj, mjolnir.world_matrix(obj, items.excluded), hidden=hidden)
        objs.append(eo)
        out.errors.extend(problems)
    for obj in items.unevaluated:
        out.errors.append(_issue(
            P, "E_ARRAY_NOT_EVALUATED", "error",
            "Array '%s' is hidden, excluded or empty, so its instances cannot be read. Unhide it, include its "
            "collection or apply the array, then export again." % obj.name, obj.name))
        eo, _problems = mjolnir.to_export_object(P, obj, mjolnir.world_matrix(obj, items.excluded), hidden=True)
        objs.append(eo)                                  # keeps the slot claimed in the (refused) diff
    if out.hidden:
        out.warnings.append(_issue(
            P, "W_HIDDEN_EXPORTED", "warning",
            "%d hidden object(s) were exported. Hidden objects are not skipped; delete them to remove them from "
            "the map." % out.hidden))
    objs.sort(key=lambda o: (o.slot is None, o.slot if o.slot is not None else 0, o.name))
    return out


# --- import --------------------------------------------------------------------------------------------
_DIGITS = re.compile(r"\d+")


class FailureLog(object):
    """Keeps the console of one import bounded.

    A bug that hits every object (610 in a real map) used to print 610 tracebacks. Now the first
    ``MAX_IMPORT_TRACEBACKS`` are printed in full, every failure is counted by kind (exception type and the first
    line of its message), and :meth:`summary` names the commonest kinds and says how many tracebacks were left out.
    """

    def __init__(self, limit=MAX_IMPORT_TRACEBACKS):
        self.limit = limit
        self.total = 0
        self.kinds = {}
        self.order = []

    def add(self, exc):
        self.total += 1
        text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        kind = "%s: %s" % (type(exc).__name__, _DIGITS.sub("#", text)[:100])      # "slot 3" and "slot 4" are one kind
        if kind not in self.kinds:
            self.kinds[kind] = 0
            self.order.append(kind)
        self.kinds[kind] += 1
        if self.total <= self.limit:
            traceback.print_exception(type(exc), exc, exc.__traceback__)

    def summary(self):
        """Console lines ('' list when nothing failed)."""
        if not self.total:
            return []
        lines = ["Mjolnir: %d object(s) could not be imported (%d kind(s) of failure)." % (self.total, len(self.kinds))]
        ranked = sorted(self.order, key=lambda k: (-self.kinds[k], self.order.index(k)))
        for kind in ranked[:MAX_IMPORT_KINDS]:
            lines.append("Mjolnir:   %d x %s" % (self.kinds[kind], kind))
        if len(ranked) > MAX_IMPORT_KINDS:
            lines.append("Mjolnir:   ... and %d more kind(s)" % (len(ranked) - MAX_IMPORT_KINDS))
        if self.total > self.limit:
            lines.append("Mjolnir:   %d traceback(s) were printed above, %d left out." % (self.limit, self.total - self.limit))
        return lines


class IMPORT_OT_mjolnir_mvar(Operator, ImportHelper):
    """Import a Halo: Reach map variant (.mvar): one Empty per object, the file embedded in the scene for export"""
    bl_idname = "import_scene.mjolnir_mvar"
    bl_label = MENU_TEXT
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".mvar"
    filter_glob: StringProperty(default="*.mvar", options={'HIDDEN'}, maxlen=255)
    replace_existing: BoolProperty(
        name="Replace Existing",
        description="Delete the objects imported earlier (with their shape and camera helpers) and replace the "
                    "stored map variant; one scene holds exactly one template. Your own Forge objects are kept",
        default=True)
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})

    def _target_path(self):
        if self.files and self.directory:
            return os.path.join(self.directory, self.files[0].name)
        return self.filepath

    def invoke(self, context, event):
        # ImportHelper.invoke always opens the browser in 5.2.1, so a preset path (drag and drop) is handled here
        if self._target_path():
            if state.get(context.scene) is not None and self.replace_existing:
                message = ("Replace the map variant already in this scene? Imported objects, including edits, "
                           "are deleted. Undo is available.")
                try:
                    return context.window_manager.invoke_confirm(self, event, message=message)
                except TypeError:
                    return context.window_manager.invoke_confirm(self, event)
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = self._target_path()
        if not path:
            self.report({'ERROR'}, "No file was chosen.")
            return {'CANCELLED'}
        if len(self.files) > 1:
            self.report({'WARNING'}, "Only the first of %d files is imported." % len(self.files))
        scene = context.scene
        P = provider.get_provider()

        # 1. read (refuse above 1 MiB)
        try:
            with open(path, "rb") as fh:
                data = fh.read(MAX_IMPORT_BYTES + 1)
        except OSError as exc:
            self.report({'ERROR'}, "Cannot read %s: %s" % (path, exc))
            return {'CANCELLED'}
        if len(data) > MAX_IMPORT_BYTES:
            self.report({'ERROR'}, "This does not look like a map variant (file too large).")
            return {'CANCELLED'}

        # 2. parse; a refusal creates nothing
        try:
            result = P.load_map_variant(data, os.path.basename(path))
        except P.MvarError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        except Exception as exc:
            traceback.print_exc()
            self.report({'ERROR'}, "Unexpected error: %s: %s" % (type(exc).__name__, exc))
            return {'CANCELLED'}

        # 3. an earlier map variant in this scene
        if state.get(scene) is not None:
            if not self.replace_existing:
                self.report({'ERROR'}, "This scene already contains a map variant; tick Replace Existing or use a "
                                       "new scene.")
                return {'CANCELLED'}
            for obj in mjolnir.imported_objects(scene):
                mjolnir.remove_with_helpers(obj)
            state.clear(scene)

        # 4. palette (a missing library is a warning: arrow empties)
        have_palette = palette.ensure_palette()
        if not have_palette:
            self.report({'WARNING'}, palette.palette_missing_warning())

        # 5/6/7. state before the objects (the label enum reads it), then the objects: one failing object never aborts the
        # import; anything else leaves NOTHING half-built (a state that says "no slot was imported" would make every slot look
        # "not imported" at export and skip the checks)
        imported, failed, created, failed_nonstock = [], [], [], {}
        try:
            state.set_from_load(scene, data, result, path, mjolnir.VERSION, library_version(P))
            coll_index = palette.collection_index()
            failures = FailureLog()
            for rec in result.objects:
                try:
                    created.append(mjolnir.create_import_object(context, rec, scene, coll_index))
                    imported.append(rec.slot)
                except Exception as exc:
                    failures.add(exc)
                    failed.append((rec.slot, "%s: %s" % (type(exc).__name__, exc)))
                    if not getattr(rec, "stock", True):
                        failed_nonstock[rec.slot] = rec.type_name
            state.set_import_results(scene, imported, [slot for slot, _msg in failed], failed_nonstock)
            for line in failures.summary():
                print(line)
        except Exception as exc:
            traceback.print_exc()
            for obj in created:
                try:
                    mjolnir.remove_with_helpers(obj)
                except Exception:
                    pass
            state.clear(scene)
            self.report({'ERROR'}, "Unexpected error while importing: %s: %s. Nothing was imported." % (type(exc).__name__, exc))
            return {'CANCELLED'}
        try:                                         # the "where was it after import" pose the export compares against
            mjolnir.capture_pose_baselines(context, created)
        except Exception as exc:
            traceback.print_exc()
            self.report({'WARNING'}, "Could not record the imported positions (%s: %s); the export will hand every "
                                     "position to the library as Blender has it." % (type(exc).__name__, exc))

        # 8. report
        info = result.info
        self.report({'INFO'}, "Imported %d objects from %s (%s, %d of %d slots used)" % (
            len(imported), os.path.basename(path), info.map_name or "unknown map", info.occupied,
            mjolnir.MAX_OBJECTS))
        if failed:
            for slot, message in failed[:MAX_LISTED_WARNINGS]:
                print("Mjolnir: slot %d could not be imported: %s" % (slot, message))
            if len(failed) > MAX_LISTED_WARNINGS:
                print("Mjolnir: ... and %d more slot(s)" % (len(failed) - MAX_LISTED_WARNINGS))
            self.report({'WARNING'}, "%d objects could not be imported (see console); they will be left unchanged "
                                     "on export" % len(failed))
            if failed_nonstock:
                self.report({'WARNING'}, "%d of them are not stock objects of this map; export will refuse them unless "
                                         "Keep objects this tool does not recognise is ticked." % len(failed_nonstock))
        warnings = list(getattr(result, "warnings", []) or []) + list(getattr(info, "warnings", []) or [])
        warnings = [w for w in _dedupe(warnings) if getattr(w, "severity", "warning") != "info"]
        for issue in warnings[:MAX_LISTED_WARNINGS]:
            self.report({'WARNING'}, issue.message)
        if len(warnings) > MAX_LISTED_WARNINGS:
            self.report({'WARNING'}, "%d more library warning(s); see the console." % (len(warnings) - MAX_LISTED_WARNINGS))
        for issue in warnings[:MAX_CONSOLE_WARNINGS]:
            print("Mjolnir: %s: %s" % (issue.code, issue.message))
        if len(warnings) > MAX_CONSOLE_WARNINGS:
            print("Mjolnir: ... and %d more library warning(s)" % (len(warnings) - MAX_CONSOLE_WARNINGS))
        return {'FINISHED'}


# --- export --------------------------------------------------------------------------------------------
_NOTE_BUDGET = ("Budget was not recalculated: item prices are not stored in the map variant, so the spent-budget value "
                "was copied unchanged. Open the map in Forge and check the budget meter before playing.")
_NOTE_UNVERIFIED = ("This tool has never been checked against a real MCC load. Follow the test ladder in the "
                    "documentation (NOTES.md) before relying on the output.")


def _fmt_issue(issue):
    where = ""
    if issue.slot is not None:
        where += " slot %d" % issue.slot
    if issue.object_name:
        where += " '%s'" % issue.object_name
    return "%s %s%s: %s" % (issue.severity.upper(), issue.code, where, issue.message)


STATUS_OK = "ok"
STATUS_REFUSED = "refused"           # the glue or the library refused: nothing was written
STATUS_FAILED = "failed"             # the export was accepted but the file could not be written
_RESULT_TEXT = {
    STATUS_OK: "ok, file written",
    STATUS_REFUSED: "REFUSED, nothing was written",
    STATUS_FAILED: "FAILED, nothing was written (the file could not be written)",
}


def build_report(target, st, errors, warnings, diff, stats, status):
    """Lines of the text datablock. ``status`` is one of ``STATUS_OK`` / ``STATUS_REFUSED`` / ``STATUS_FAILED``.

    ``STATUS_OK`` must only be passed after the file was really written: the result line is the first thing
    the user reads.
    """
    lines = ["Mjolnir export report", "Target: %s" % target]
    if st is not None:
        lines.append("Template: %s (sha256 %s), map %s %s" % (st.get("source_name", ""),
                                                             str(st.get("template_sha256", ""))[:16],
                                                             st.get("map_name") or "unknown", st.get("map_id_hex", "")))
    lines.append("Result: %s" % _RESULT_TEXT[status])
    lines.append("")
    lines.append("Problems (%d error(s), %d warning(s))" % (len(errors), len([w for w in warnings
                                                                           if w.severity != "info"])))
    for issue in list(errors) + list(warnings):
        lines.append("  " + _fmt_issue(issue))
    lines.append("")
    lines.append("Changes")
    if not diff:
        lines.append("  (none reported)")
    for entry in diff:
        lines.append("  %s slot %s \"%s\" %s" % (entry.kind.upper().replace("_", " "),
                                                  "-" if entry.slot is None else entry.slot, entry.name, entry.detail))
    lines.append("")
    lines.append("Stats")
    stats = stats or {}
    shown = set()                                   # every key is written exactly once
    if "occupied_before" in stats or "occupied_after" in stats:
        lines.append("  Objects: %s before, %s after (limit %d)" % (stats.get("occupied_before", "?"),
                                                                   stats.get("occupied_after", "?"), mjolnir.MAX_OBJECTS))
        shown.update(("occupied_before", "occupied_after"))
    if "end_bit" in stats and "capacity_bits" in stats:
        lines.append("  Bits used: {:,} of {:,}".format(int(stats["end_bit"]), int(stats["capacity_bits"])))
        shown.update(("end_bit", "capacity_bits"))
    if "L" in stats:
        lines.append("  Stored stream length L: %s" % stats["L"])
        shown.add("L")
    if "hash_flavour" in stats:
        lines.append("  Hash: %s" % stats["hash_flavour"])
        shown.add("hash_flavour")
    for key in sorted(stats):
        if key not in shown:
            lines.append("  %s: %s" % (key, stats[key]))
    codes = set(i.code for i in list(errors) + list(warnings))
    notes = []
    if "I_BUDGET" not in codes:
        notes.append(_NOTE_BUDGET)
    if "I_UNVERIFIED" not in codes:
        notes.append(_NOTE_UNVERIFIED)
    if notes:
        lines.append("")
        lines.extend(notes)
    return lines


def console_summary(target, status, errors, warnings, diff):
    """A few console lines: the outcome, every problem, the pointer to the full report (not the whole report)."""
    shown = [w for w in warnings if w.severity != "info"]
    changes = sum(1 for e in diff if e.kind not in ("kept",))
    lines = ["export %s: %s (%d error(s), %d warning(s), %d change(s))" % (
        status.upper(), os.path.basename(target) or target, len(errors), len(shown), changes)]
    problems = list(errors) + shown
    for issue in problems[:MAX_CONSOLE_PROBLEMS]:
        lines.append("  " + _fmt_issue(issue))
    if len(problems) > MAX_CONSOLE_PROBLEMS:
        lines.append("  ... and %d more problem(s)" % (len(problems) - MAX_CONSOLE_PROBLEMS))
    lines.append("  full report: text '%s' in the Text Editor" % REPORT_NAME)
    return lines


def write_report(lines, console=()):
    """Replace the text datablock ``Mjolnir Export Report`` with ``lines``; print ``console`` (short) to the console."""
    text = bpy.data.texts.get(REPORT_NAME)
    if text is None:
        text = bpy.data.texts.new(REPORT_NAME)
    text.clear()
    text.write("\n".join(lines) + "\n")
    for line in console:
        print("Mjolnir: " + line)
    return text


class EXPORT_OT_mjolnir_mvar(Operator, ExportHelper):
    """Export the objects of this scene into a copy of the imported map variant (the original file is never touched)"""
    bl_idname = "export_scene.mjolnir_mvar"
    bl_label = MENU_TEXT

    filename_ext = ".mvar"
    filter_glob: StringProperty(default="*.mvar", options={'HIDDEN'}, maxlen=255)
    check_extension = True
    force_reencode: BoolProperty(name="Rewrite whole stream", description="Diagnostic: rewrite the whole stream",
                                 default=False)
    fsm_policy: EnumProperty(name="File-share block", default='KEEP', items=[
        ('KEEP', "Keep", "Keep the _fsm block of the template unchanged"),
        ('DROP', "Drop", "Leave the _fsm block out of the exported file"),
    ])
    hash_policy: EnumProperty(name="Hash (advanced)", default='REPRODUCE', items=[
        ('REPRODUCE', "Reproduce", "Use the hash recipe of the template"),
        ('SALTED_BE32', "Salted BE32", "Force the salted recipe"),
        ('PLAIN_LE32', "Plain LE32", "Force the plain recipe"),
    ])
    raise_quota_max: BoolProperty(
        name="Raise quota maximum (unverified)",
        description="When a palette entry would hold more objects than the maximum stored in the map variant (a finished "
                    "matchmaking map often allows exactly what it holds), raise that maximum to the new count instead of "
                    "refusing the export. Never lowers a value and never touches a minimum. UNVERIFIED: the game may rebuild "
                    "the quotas from the scenario, or refuse the file; nothing here has been checked against a real game load",
        default=False, options={'SKIP_SAVE'})        # never remembered between runs: it must not come back pre-ticked

    def invoke(self, context, event):
        st = state.get(context.scene)
        if st is None:                                   # nothing to patch: say so now instead of after the file dialog
            self.report({'ERROR'}, "This scene has no imported map variant. Import a .mvar first: export patches the "
                                   "imported file.")
            return {'CANCELLED'}
        if not self.filepath:
            self.filepath = propose_output_path(provider.get_provider(), st.get("source_path", ""))
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "force_reencode")
        layout.prop(self, "fsm_policy")
        layout.prop(self, "hash_policy")
        layout.prop(self, "raise_quota_max")
        layout.prop(context.scene.forge, "allowUnverifiedRotation")
        layout.prop(context.scene.forge, "keepUnrecognisedObjects")
        mjolnir.wrapTextPanel(self, "Checked before anything is written: stock map and stock objects only, at "
                                    "most 650 objects, positions inside the map bounds, quotas and file capacity. "
                                    "A report is written to the text 'Mjolnir Export Report'.")

    def _refuse(self, errors, warnings, st, target, diff=(), stats=None, status=STATUS_REFUSED):
        """Report problems that stop the export: the text datablock, a short console summary, one ERROR line."""
        errors = _dedupe(errors)
        warnings = _dedupe(warnings)
        write_report(build_report(target, st, errors, warnings, diff, stats, status),
                     console_summary(target, status, errors, warnings, diff))
        first = errors[0].message if errors else "unknown problem"
        if status == STATUS_FAILED:
            self.report({'ERROR'}, "Export failed, nothing was written: %s See the text '%s'." % (first, REPORT_NAME))
        else:
            self.report({'ERROR'}, "Export refused: %d problem(s); first: %s See the text '%s'." % (
                len(errors), first, REPORT_NAME))
        return {'CANCELLED'}

    def execute(self, context):
        scene = context.scene
        P = provider.get_provider()
        target = self.filepath
        st = state.get(scene)

        # 1. the template
        ok, why = state.verify_template(scene)
        if not ok:
            if why == "E_NO_TEMPLATE":
                issue = _issue(P, "E_NO_TEMPLATE", "error", "This scene has no imported map variant. Import a .mvar "
                               "first: export patches the imported file.")
            else:
                issue = _issue(P, "E_TEMPLATE_CORRUPT", "error", "The map variant stored in this scene is damaged "
                               "(checksum mismatch). Import the original file again.")
            return self._refuse([issue], [], st, target)
        template = state.template_bytes(scene)

        # 2. path policy, before anything is collected
        if not target:
            return self._refuse([_issue(P, "E_NO_TARGET", "error", "No output file was chosen.")], [], st, target)
        issue = path_issue(P, target, st.get("source_path", ""))
        if issue is not None:
            return self._refuse([issue], [], st, target)

        # 3. collect (glue-level problems stay in `collected`)
        try:
            collected = collect_export_objects(scene, context)
        except Exception as exc:
            traceback.print_exc()
            return self._refuse([_issue(P, "E_INTERNAL", "error", "The scene could not be read for export: %s: %s"
                                        % (type(exc).__name__, exc))], [], st, target)

        # 4. the library
        forge = scene.forge
        options = P.ExportOptions(
            allow_unverified_rotation=bool(forge.allowUnverifiedRotation),
            keep_unrecognised_imported=bool(forge.keepUnrecognisedObjects),
            force_reencode=bool(self.force_reencode),
            fsm_policy=self.fsm_policy,
            hash_policy=self.hash_policy,
            raise_quota_max=bool(self.raise_quota_max),
            imported_slots=list(st.get("imported_slots", [])),
        )
        errors = list(collected.errors)
        warnings = list(collected.warnings)
        failed_issues = failed_slot_issues(P, st, state.failed_nonstock(scene), bool(forge.keepUnrecognisedObjects))
        errors.extend(i for i in failed_issues if i.severity == "error")
        warnings.extend(i for i in failed_issues if i.severity != "error")
        diff, stats, data, result_ok = [], {}, None, False
        try:
            result = P.export_map_variant(template, collected.objects, options)
            errors.extend(result.errors)
            warnings.extend(result.warnings)
            diff, stats, data, result_ok = list(result.diff), dict(result.stats or {}), result.data, bool(result.ok)
        except P.MvarError as exc:
            errors.append(_issue(P, "E_TEMPLATE_UNREADABLE", "error", str(exc)))
        except Exception as exc:
            traceback.print_exc()
            errors.append(_issue(P, "E_INTERNAL", "error", "Unexpected error: %s: %s" % (type(exc).__name__, exc)))

        # 5/6. report (always), refuse before writing when anything is an error
        if errors or not result_ok:
            if not errors:
                errors.append(_issue(P, "E_INTERNAL", "error", "The library refused the export without giving a reason."))
            return self._refuse(errors, warnings, st, target, diff, stats)
        if data is None:
            return self._refuse([_issue(P, "E_INTERNAL", "error", "The library returned no data.")], warnings, st,
                                target, diff, stats)
        # the library re-parsed its output (5.10 step 12); for a changed file the glue checks once more that the
        # bytes read back (a passthrough is the template itself, which was parsed at import)
        if bytes(data) != template:
            try:
                P.load_map_variant(bytes(data), os.path.basename(target))
            except Exception as exc:
                return self._refuse([_issue(P, "E_INTERNAL", "error", "The exported data could not be read back "
                                            "(%s); nothing was written." % exc)], warnings, st, target, diff, stats)
        warnings = _dedupe(warnings)

        # 7. write FIRST; the report says "ok" only about a file that exists
        sources = [st.get("source_path", "")] if st.get("source_path") else []
        try:
            P.write_atomic(target, bytes(data), sources, None)
        except P.PathPolicyError as exc:
            return self._refuse([_issue(P, "E_WRITE_FAILED", "error", str(exc))], warnings, st, target, diff, stats,
                                STATUS_FAILED)
        except OSError as exc:
            return self._refuse([_issue(P, "E_WRITE_FAILED", "error", "Could not write %s: %s." % (target, exc))],
                                warnings, st, target, diff, stats, STATUS_FAILED)
        except Exception as exc:                         # anything else (a ValueError from the writer, ...): a FAILED report,
            return self._refuse([_issue(P, "E_WRITE_FAILED", "error", "Could not write %s: %s: %s."   # never a stale "ok"
                                        % (target, type(exc).__name__, exc))], warnings, st, target, diff, stats,
                                STATUS_FAILED)
        write_report(build_report(target, st, [], warnings, diff, stats, STATUS_OK),
                     console_summary(target, STATUS_OK, [], warnings, diff))
        counts = dict((k, 0) for k in ("kept", "moved", "edited", "retargeted", "added", "removed", "not_imported"))
        for entry in diff:
            if entry.kind in counts:
                counts[entry.kind] += 1
        message = "Exported %s: %d kept, %d moved, %d added, %d removed." % (
            os.path.basename(target), counts["kept"], counts["moved"], counts["added"], counts["removed"])
        edited = counts["edited"] + counts["retargeted"]
        if edited:
            message += " %d edited." % edited
        if counts["not_imported"]:
            message += " %d not imported earlier, left unchanged." % counts["not_imported"]
        self.report({'INFO'}, message)
        shown = [w for w in warnings if w.severity == "warning"]
        for issue in shown[:MAX_LISTED_WARNINGS]:
            self.report({'WARNING'}, issue.message)
        if len(shown) > MAX_LISTED_WARNINGS:
            self.report({'WARNING'}, "%d more warning(s); see the text '%s'." % (len(shown) - MAX_LISTED_WARNINGS,
                                                                              REPORT_NAME))
        return {'FINISHED'}


# --- drag and drop, File menu ----------------------------------------------------------------------------
class MJOLNIR_FH_mvar(bpy.types.FileHandler):
    bl_idname = "MJOLNIR_FH_mvar"
    bl_label = "Halo Reach Map Variant"
    bl_import_operator = IMPORT_OT_mjolnir_mvar.bl_idname
    bl_export_operator = EXPORT_OT_mjolnir_mvar.bl_idname
    bl_file_extensions = ".mvar"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'


def menu_func_import(self, context):
    self.layout.operator(IMPORT_OT_mjolnir_mvar.bl_idname, text=MENU_TEXT, icon=MENU_ICON)


def menu_func_export(self, context):
    self.layout.operator(EXPORT_OT_mjolnir_mvar.bl_idname, text=MENU_TEXT, icon=MENU_ICON)


CLASSES = [IMPORT_OT_mjolnir_mvar, EXPORT_OT_mjolnir_mvar, MJOLNIR_FH_mvar]
_registered = False


def register():
    global _registered
    if _registered:
        unregister()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for menu, fn in ((bpy.types.TOPBAR_MT_file_import, menu_func_import),
                     (bpy.types.TOPBAR_MT_file_export, menu_func_export)):
        menu.remove(fn)
        menu.append(fn)
    _registered = True


def unregister():
    global _registered
    for menu, fn in ((bpy.types.TOPBAR_MT_file_import, menu_func_import),
                     (bpy.types.TOPBAR_MT_file_export, menu_func_export)):
        try:
            menu.remove(fn)
        except Exception:
            pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _registered = False
