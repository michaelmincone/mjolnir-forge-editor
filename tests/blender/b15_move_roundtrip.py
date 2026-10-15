"""B-15 (SPEC 9.4, 9.8 row 2, gate G6): THE OWNER'S ACCEPTANCE TEST on the REAL Halo: Reach map variant.

    import (File > Import) -> move one object in Blender -> export (File > Export) -> re-import -> compare

Blender 5.2.1 headless, the add-on installed in an isolated profile and enabled at startup, the REAL provider (the
library behind the add-on, no stub), the one real map variant ``0aaaf8c7-...mvar`` ("Headstrong", Breakneck, map id
10050), read in place and never copied or modified. What is proved, each step judged against the independent walker of
the fixture builder (``tests/fixturebuilder/selfcheck.py``, written separately from ``mvarlib``) and ``hashlib``:

1. File > Import (``import_scene.mjolnir_mvar``) makes 610 Blender objects, one per occupied slot.
2. A no-op File > Export (``export_scene.mjolnir_mvar``) reproduces the original 59,392 bytes EXACTLY (passthrough).
3. One VERTICAL prop is moved by a known offset in Blender, then (from a fresh import) one TILTED prop. The exported
   file differs from the original in exactly the position bits of that object (the bits where the old and the expected
   new cell differ) and the 20 SHA-1 bytes: the stored length L, the trailer of 29,911 zero bytes, every other byte and
   the SHA-1 recipe (plain_le32, length stored big-endian) are as before; a tilted object keeps its orientation bits.
4. The exported file is imported again in a FRESH scene: the moved object is where it was asked to be (within the
   quantisation step 40000 / 2**23 = 0.00477), and the other 609 objects are unchanged (identical slot records).
5. Duplicate an imported object: a new slot 610 needs the rotation gate, and is refused with ``E_QUOTA`` when the quota
   maximum would be exceeded (``Cover, Large`` is at its maximum) unless "Raise quota maximum (unverified)" is ticked, in
   which case it is written with ``W_QUOTA_MAX_RAISED``; delete an imported object: the slot becomes absent and its quota
   row goes down by one.

Prints one line per step (``B-15 ...``): ``moved slot S dx=.. other slots bit-identical N/N``. Needs the real file; without
it the test is SKIPPED with a loud notice (it is not part of the repository).
"""
import os
import re
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_close, check_eq  # noqa: E402

ID = "b15"
TITLE = "OWNER ACCEPTANCE: real Breakneck file: import, move, export, re-import, duplicate, delete"
NEEDS_STUB = False
REAL_ONLY = True

VERTICAL_PROPS = ("Cover, Large", "Capture Plate", "Door, Human", "Flag Stand")
TILTED_PROPS = ("Fusion Coil", "Street Cone", "Crate, Heavy, Small", "Wall", "I-Beam")
VERTICAL_OFFSET = (1.0, -0.5, 0.25)
TILTED_OFFSET = (-0.75, 0.5, 0.125)


def say(text):
    print("B-15 " + text)
    sys.stdout.flush()


# --- picking and describing objects ------------------------------------------------------------------
def type_of(obj):
    """The type name from the object name ``"<slot> - <type>"`` (a second scene's copies carry Blender's ``.001``)."""
    name = obj.name.split(" - ", 1)[1] if " - " in obj.name else obj.name
    return re.sub(r"\.\d{3,}$", "", name)


def is_vertical(obj):
    """From the record's own numbers (``mj_pose`` = position, forward, up): up is exactly +Z."""
    up = [float(v) for v in obj["mj_pose"][6:9]]
    return abs(up[0]) < 1e-6 and abs(up[1]) < 1e-6 and abs(up[2] - 1.0) < 1e-6


def pick(objs, types, vertical):
    for wanted in types:
        for obj in sorted(objs, key=lambda o: o["mj_slot"]):
            if type_of(obj) == wanted and is_vertical(obj) == vertical:
                return obj
    raise AssertionError("no %s object of %s in the scene" % ("vertical" if vertical else "tilted", types))


def snapshot(obj):
    """Everything about an imported object that an unrelated edit must not change."""
    fp = obj.forge
    return (obj["mj_slot"], type_of(obj), bytes(obj["mj_raw"]), int(obj["mj_raw_bits"]), tuple(obj["mj_pose"]),
            fp.physics, fp.team, fp.color, fp.symmetry, fp.placeAtStart, fp.gameSpecific, fp.gtLabel, fp.spawnSequence,
            fp.spawnTime, fp.cachedType, fp.otherInfoA, fp.otherInfoB, fp.shape, round(fp.width, 6), round(fp.length, 6),
            round(fp.top, 6), round(fp.bottom, 6), int(obj["mj_parent_slot"]))


def by_slot(objs):
    return dict((o["mj_slot"], o) for o in objs)


def imported_objects(scene):
    return [o for o in scene.objects if o.get("isForgeObject") and "mj_slot" in o]


def move(obj, offset):
    """Move ``obj`` in Blender by ``offset``; returns the position Blender holds afterwards (float32 values)."""
    obj.location = Vector(obj.location) + Vector(offset)
    bpy.context.view_layer.update()
    return tuple(float(c) for c in obj.matrix_world.translation)


def report_has(env, *needles):
    text = env.report_text()
    for needle in needles:
        check(needle in text, "%r not in the export report:\n%s" % (needle, text[:2500]))


# --- the checks ---------------------------------------------------------------------------------------
def check_original_untouched(path, fingerprint, where):
    check_eq(rd.file_fingerprint(path), fingerprint, "the real map variant changed (%s)" % where)


def check_container_unchanged(original, out, allowed_stream_bits, what):
    """Everything except the allowed stream bits and the 20 SHA-1 bytes is byte-identical (SPEC 5.9)."""
    check_eq(len(out), rd.REAL_SIZE, what + ": file length")
    changed = rd.changed_bytes(original, out)
    outside = rd.bytes_outside_stream(changed)
    check(set(outside) <= set(range(rd.HASH_AT, rd.HASH_AT + 20)),
          "%s: bytes outside the stream other than the SHA-1 changed: %s" % (what, outside[:10]))
    diff = rd.stream_diff(original, out)
    check_eq(diff, sorted(allowed_stream_bits), what + ": differing stream bits")
    check_eq(out[rd.LENGTH_AT:rd.LENGTH_AT + 4], original[rd.LENGTH_AT:rd.LENGTH_AT + 4], what + ": stored length bytes")
    check_eq(rd.stored_length(out), rd.stored_length(original), what + ": L")
    check_eq(out[rd.REAL_PLAIN_SIZE:], bytes(rd.REAL_SIZE - rd.REAL_PLAIN_SIZE), what + ": the 29,911-byte trailer")
    check_eq(out[:rd.HASH_AT], original[:rd.HASH_AT], what + ": everything before the SHA-1")
    return changed


def check_hash(out, what):
    """The SHA-1 is the template's recipe (plain_le32, length stored big-endian) recomputed with hashlib."""
    check_eq(rd.stored_hash(out), rd.sha1_plain_le32(out), what + ": SHA-1 = SHA1(LE32(L) || stream[:L])")
    flavour = rd.read_result(out)["flavour"]
    check_eq((flavour["length_endian"], flavour["recipe"]), (">", "plain_le32"),
             what + ": the independent walker detects the template's flavour in the output")


def move_and_export(env, original, path, label, chooser, offset):
    """Import the real file, move one object by ``offset``, export; returns the data of every check below."""
    result = env.import_file(path)
    check_eq(result, {'FINISHED'}, label + ": import")
    scene = bpy.context.scene
    objs = imported_objects(scene)
    check_eq(len(objs), rd.REAL_OBJECTS, label + ": Blender objects after File > Import")
    slots = by_slot(objs)
    obj = chooser(objs)
    slot = obj["mj_slot"]
    before = dict((s, snapshot(o)) for s, o in slots.items())
    old_position = tuple(float(c) for c in obj.matrix_world.translation)
    new_position = move(obj, offset)
    check_close([new_position[i] - old_position[i] for i in range(3)], offset, 1e-5, label + ": Blender moved the object")
    target = os.path.join(env.tmp, "b15_%s.mvar" % label.split()[0])
    out_result, out_path = env.export_to(os.path.basename(target))
    check_eq(out_result, {'FINISHED'}, label + ": File > Export: %r\n%s" % (out_result, env.report_text()[:1500]))
    check(os.path.isfile(out_path), label + ": the file was written")
    exported = rd.read_bytes(out_path)
    return slot, obj, before, old_position, new_position, exported, out_path


def verify_move(env, original, dec_old, label, slot, before, old_position, new_position, offset, exported, out_path,
                tilted):
    new_cells = [rd.cell_for(c) for c in new_position]
    old_cells = list(dec_old["slots"][slot]["pos"])
    check(new_cells != old_cells, label + ": the move changes at least one cell")
    expected_bits = rd.pos_bits_changed(dec_old, slot, new_cells)
    check(expected_bits, label + ": expected position bits")
    # 3. bit-diff contract: only that object's position bits and the SHA-1
    check_container_unchanged(original, exported, expected_bits, label)
    check(rd.stored_hash(exported) != rd.stored_hash(original), label + ": the SHA-1 was recomputed")
    check_hash(exported, label)
    # independent decode of the output: only the position of that slot differs
    dec_new = rd.decode(exported)
    check_eq(rd.slots_equal(dec_old, dec_new, ignore=(slot,)), [], label + ": the other slots decode identically")
    check_eq(rd.fields_differing(dec_old["slots"][slot], dec_new["slots"][slot]), ["pos"],
             label + ": only the position field of the moved slot differs (%s)" % ("tilted: orientation bits kept" if tilted else "vertical"))
    check_eq(list(dec_new["slots"][slot]["pos"]), new_cells, label + ": the new cells are the floor cells of the requested position")
    check_eq(dec_new["quotas"], dec_old["quotas"], label + ": quota rows")
    check_eq(rd.decode_summary(dec_new), rd.decode_summary(dec_old), label + ": header, body, labels")
    check_eq(len(dec_new["slots"]), rd.REAL_OBJECTS, label + ": 610 occupied slots")
    report_has(env, "Result: ok, file written", "MOVED slot %d " % slot)
    return dec_new


def verify_reimport(env, label, slot, before, new_position, offset, old_position, exported, out_path, tilted):
    """4. File > Import of the exported file in a FRESH scene."""
    first_scene = bpy.context.scene
    with bl_common.fresh_scene("Reimport") as scene2:
        check(scene2 is not first_scene and bpy.context.scene is scene2, "a second, fresh scene is the context scene")
        check_eq(env.state.get(scene2), None, "the fresh scene holds no map variant yet")
        result = env.import_file(out_path)
        check_eq(result, {'FINISHED'}, label + ": re-import")
        objs2 = imported_objects(scene2)
        check_eq(len(objs2), rd.REAL_OBJECTS, label + ": 610 objects after the re-import")
        st = env.state.get(scene2)
        check_eq(st["occupied_at_import"], rd.REAL_OBJECTS)
        check_eq(st["failed_slots"], [], label + ": nothing failed")
        check_eq(env.state.template_bytes(scene2), exported, label + ": the fresh scene embeds the exported bytes")
        after = by_slot(objs2)
        check_eq(sorted(after), sorted(before), label + ": the same 610 slots")
        moved = after[slot]
        got = tuple(float(c) for c in moved.matrix_world.translation)
        for axis in range(3):
            requested = old_position[axis] + offset[axis]
            check(abs(got[axis] - requested) <= rd.REAL_CELL + 1e-5,
                  "%s: axis %d is at %.6f, requested %.6f (quantisation step %.6f)" % (label, axis, got[axis], requested, rd.REAL_CELL))
        # the moved object keeps everything else; its slot record differs in the position bits only
        snap_old, snap_new = before[slot], snapshot(moved)
        check_eq(snap_old[1], snap_new[1], label + ": same type")
        check_eq(snap_old[5:], snap_new[5:], label + ": the moved object keeps every property")
        check(snap_old[2] != snap_new[2], label + ": its slot record changed")
        # forward / up of the moved object are the record's own numbers (the orientation bits were not rewritten)
        check_eq(tuple(snap_old[4][3:9]), tuple(snap_new[4][3:9]), label + ": forward and up unchanged")
        # 609 others identical
        same = [s for s in after if s != slot and snapshot(after[s]) == before[s]]
        check_eq(len(same), rd.REAL_OBJECTS - 1, label + ": the other 609 objects are unchanged")
        raw_same = [s for s in after if s != slot and bytes(after[s]["mj_raw"]) == before[s][2]]
        check_eq(len(raw_same), rd.REAL_OBJECTS - 1)
        say("%s: moved slot %d dx=%+.3f dy=%+.3f dz=%+.3f (%s) -> re-imported at (%.4f, %.4f, %.4f), error %.5f of a %.5f step; other slots bit-identical %d/%d"
            % (label, slot, offset[0], offset[1], offset[2], "tilted" if tilted else "vertical", got[0], got[1], got[2],
               max(abs(got[a] - (old_position[a] + offset[a])) for a in range(3)), rd.REAL_CELL, len(raw_same),
               rd.REAL_OBJECTS - 1))


def run_real(env):
    if not rd.real_available():
        print("=" * 78)
        print("NOTICE: the real map variant is absent (%s); B-15, the owner's acceptance test, is SKIPPED, not passed." % rd.real_mvar_path())
        print("=" * 78)
        raise bl_common.Skip("the real map variant is absent: %s" % rd.real_mvar_path())
    path = rd.real_mvar_path()
    original = rd.real_bytes()
    fingerprint = rd.file_fingerprint(path)
    env.use_library()
    dec_old = rd.decode(original)
    check_eq(len(dec_old["slots"]), rd.REAL_OBJECTS, "the independent walker finds 610 occupied slots")
    P = env.provider.get_provider()
    check(P.__name__.endswith(".mvarlib.api") and not getattr(P, "IS_STUB", False), "the REAL library is the provider: %r" % (P,))
    say("Blender %s, add-on %s, provider %s, profile %s" % (bpy.app.version_string, env.addon_name, P.__name__,
                                                          os.environ.get("BLENDER_USER_RESOURCES", "(default profile)")))
    say("real file %s: %d bytes, %d occupied slots, sha256 %s..." % (os.path.basename(path), len(original), len(dec_old["slots"]),
                                                                    fingerprint[2][:16]))

    # --- 1 + 2. File > Import, then a no-op File > Export gives the original bytes back -----------------------------------
    result = env.import_file(path)
    check_eq(result, {'FINISHED'}, "import")
    scene = bpy.context.scene
    objs = imported_objects(scene)
    check_eq(len(objs), rd.REAL_OBJECTS, "File > Import made 610 Blender objects")
    st = env.state.get(scene)
    check_eq((st["map_name"], st["map_id_hex"], st["quota_count"], st["occupied_at_import"]), ("Breakneck", "0x00002742", 82, 610))
    check_eq(st["failed_slots"], [])
    check_eq(st["hash_flavour"], "plain_le32/>")
    check_eq(env.state.template_bytes(scene), original, "the template embedded in the scene is the file, verbatim")
    noop_result, noop_path = env.export_to("b15_noop.mvar")
    check_eq(noop_result, {'FINISHED'}, "no-op export: %r\n%s" % (noop_result, env.report_text()[:1500]))
    noop = rd.read_bytes(noop_path)
    check_eq(len(noop), rd.REAL_SIZE)
    check(noop == original, "a no-op import -> export must reproduce the original bytes exactly (passthrough)")
    report_has(env, "Result: ok, file written", "Objects: 610 before, 610 after")
    say("no-op import -> export: %d bytes, identical to the original (passthrough, 610 kept)" % len(noop))
    # the exported no-op file imports again to the same 610 objects
    with bl_common.fresh_scene("NoopReimport") as scene2:
        check_eq(env.import_file(noop_path), {'FINISHED'})
        check_eq(len(imported_objects(scene2)), rd.REAL_OBJECTS)
    check_original_untouched(path, fingerprint, "after the no-op export")

    # --- 3 + 4. move a vertical prop, then a tilted one ------------------------------------------------------------------------
    for label, types, vertical, offset in (("vertical prop", VERTICAL_PROPS, True, VERTICAL_OFFSET),
                                           ("tilted prop", TILTED_PROPS, False, TILTED_OFFSET)):
        env.reset()
        env.use_library()
        slot, obj, before, old_position, new_position, exported, out_path = move_and_export(
            env, original, path, label, lambda objs, t=types, v=vertical: pick(objs, t, v), offset)
        say("%s: slot %d (%s) at (%.4f, %.4f, %.4f) moved in Blender by (%+.3f, %+.3f, %+.3f)" % (
            label, slot, type_of(obj), old_position[0], old_position[1], old_position[2], offset[0], offset[1], offset[2]))
        check_eq(is_vertical(obj), vertical, label + ": picked the right kind of object")
        verify_move(env, original, dec_old, label, slot, before, old_position, new_position, offset, exported, out_path,
                    not vertical)
        verify_reimport(env, label, slot, before, new_position, offset, old_position, exported, out_path, not vertical)
        check_original_untouched(path, fingerprint, "after " + label)

    # --- 5a. duplicate an imported object: slot 610 ------------------------------------------------------------------------------
    env.reset()
    env.use_library()
    check_eq(env.import_file(path), {'FINISHED'})
    scene = bpy.context.scene
    objs = imported_objects(scene)
    source = pick(objs, ("Cover, Large",), True)
    src_slot = source["mj_slot"]
    folder_row = dec_old["slots"][src_slot]["folder"]
    check_eq(dec_old["quotas"][folder_row], [0, 7, 7], "the Cover, Large row is exactly at its maximum")
    for o in bpy.context.selected_objects:
        o.select_set(False)
    source.select_set(True)
    bpy.context.view_layer.objects.active = source
    check_eq(bpy.ops.object.duplicate(), {'FINISHED'})
    dups = [o for o in imported_objects(scene) if o is not source and o["mj_slot"] == src_slot]
    check_eq(len(dups), 1, "the duplicate inherits the slot (it is a copy)")
    dup = dups[0]
    dup_position = move(dup, (2.0, 0.0, 0.0))
    # the rotation gate: adding any object needs it
    result, out_path = env.export_to("b15_dup_nogate.mvar")
    check(isinstance(result, RuntimeError) and "E_ROTATION_GATED" in env.report_text(), "a new object needs the rotation gate: %r" % (result,))
    check(not os.path.exists(out_path), "refused: nothing written")
    scene.forge.allowUnverifiedRotation = True
    # the quota: Cover, Large is at its maximum
    result, out_path = env.export_to("b15_dup_quota.mvar")
    check(isinstance(result, RuntimeError), "refused over the quota: %r" % (result,))
    report_has(env, "ERROR E_QUOTA: Palette entry %d (" % folder_row, ") would have 8 placed; the maximum on this map variant is 7.",
               "REFUSED, nothing was written")
    check(not os.path.exists(out_path), "E_QUOTA: nothing written")
    # with the opt-in option: success
    result, out_path = env.export_to("b15_dup_ok.mvar", raise_quota_max=True)
    check_eq(result, {'FINISHED'}, "duplicate with 'Raise quota maximum': %r\n%s" % (result, env.report_text()[:1500]))
    exported = rd.read_bytes(out_path)
    report_has(env, "W_QUOTA_MAX_RAISED", "ADDED slot 610", "Objects: 610 before, 611 after")
    dec_new = rd.decode(exported)
    check_eq(len(dec_new["slots"]), rd.REAL_OBJECTS + 1, "611 occupied slots")
    check_eq(rd.slots_equal(dec_old, dec_new, ignore=(610,)), [], "the 610 original slots decode identically")
    new_slot = dec_new["slots"][610]
    old_slot = dec_old["slots"][src_slot]
    check_eq((new_slot["folder"], new_slot["item"]), (old_slot["folder"], old_slot["item"]), "slot 610 is a Cover, Large")
    check_eq(list(new_slot["pos"]), [rd.cell_for(c) for c in dup_position], "slot 610 sits where the duplicate was moved to")
    check_eq(dec_new["quotas"][folder_row], [0, 8, 8], "the quota row was raised to the new count")
    check_eq([i for i, (a, b) in enumerate(zip(dec_old["quotas"], dec_new["quotas"])) if a != b], [folder_row], "no other quota row changed")
    check_eq(rd.decode_summary(dec_new), rd.decode_summary(dec_old))
    check(len(exported) == rd.REAL_SIZE and exported[rd.REAL_PLAIN_SIZE:] == bytes(rd.REAL_SIZE - rd.REAL_PLAIN_SIZE), "trailer kept")
    check(rd.stored_length(exported) > rd.stored_length(original), "the stream grew, so L grew")
    check_hash(exported, "duplicate")
    check_eq(rd.read_bytes(path), original, "the original is untouched")
    say("duplicate of slot %d (Cover, Large): refused without the gate (E_ROTATION_GATED), refused over the quota (E_QUOTA: 8 > 7), "
        "written with 'Raise quota maximum' as slot 610, row %d (0, 7, 7) -> (0, 8, 8), L %d -> %d, the 610 original slots identical"
        % (src_slot, folder_row, rd.stored_length(original), rd.stored_length(exported)))

    # --- 5b. delete an imported object -----------------------------------------------------------------------------------------------
    env.reset()
    env.use_library()
    check_eq(env.import_file(path), {'FINISHED'})
    scene = bpy.context.scene
    objs = imported_objects(scene)
    victim = pick(objs, ("Cover, Large",), True)
    victim_slot = victim["mj_slot"]
    env.mjolnir.remove_with_helpers(victim)
    result, out_path = env.export_to("b15_delete.mvar")
    check_eq(result, {'FINISHED'}, "delete: %r\n%s" % (result, env.report_text()[:1500]))
    exported = rd.read_bytes(out_path)
    report_has(env, "REMOVED slot %d " % victim_slot, "Objects: 610 before, 609 after")
    dec_new = rd.decode(exported)
    check_eq(len(dec_new["slots"]), rd.REAL_OBJECTS - 1)
    check(victim_slot not in dec_new["slots"], "the slot is absent now")
    check_eq(rd.slots_equal(dec_old, dec_new, ignore=(victim_slot,)), [], "the other 609 slots decode identically")
    row = dec_old["slots"][victim_slot]["folder"]
    check_eq(dec_new["quotas"][row], [0, 7, 6], "the quota row went down by one")
    check_eq([i for i, (a, b) in enumerate(zip(dec_old["quotas"], dec_new["quotas"])) if a != b], [row])
    check(rd.stored_length(exported) < rd.stored_length(original), "the stream shrank, so L shrank")
    check(exported[rd.REAL_PLAIN_SIZE:] == bytes(rd.REAL_SIZE - rd.REAL_PLAIN_SIZE) and len(exported) == rd.REAL_SIZE, "trailer kept")
    check_hash(exported, "delete")
    with bl_common.fresh_scene("DeleteReimport") as scene2:
        check_eq(env.import_file(out_path), {'FINISHED'})
        check_eq(len(imported_objects(scene2)), rd.REAL_OBJECTS - 1, "re-import: 609 objects")
    say("delete of slot %d: the slot is absent, row %d (0, 7, 7) -> (0, 7, 6), L %d -> %d, the other 609 slots identical, re-import gives 609 objects"
        % (victim_slot, row, rd.stored_length(original), rd.stored_length(exported)))

    check_original_untouched(path, fingerprint, "at the end")
    say("PASS: import 610 -> move (vertical, tilted) -> export -> re-import; no-op passthrough; duplicate and delete; "
        "the original file is byte-for-byte untouched (%s)" % fingerprint[2][:16])


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
