"""B-21 (SPEC 9.4, 8.7 #4 #7): every placement byte 0x00..0xFF imports and comes back unchanged.

The stub's ``CANNED_PLACEMENT_ALL`` has 256 objects, one per byte, decoded with the file reading (physics keeps
the raw 2-bit value, so the unused value 2 occurs). The display decoding must be total (no ``KeyError`` on
"neither symmetry" or odd bits), nothing may fail, and every object must hand the same flags back.

Real variant (``run_real``, G6): a fixture of the independent builder with 256 blocks, one per placement byte. The display
is derived from the byte by the spec's file reading (physics bits 6-7, symmetry bits 2-3, place-at-start = bit 4 clear,
game-specific = bit 5), not from the library; the unchanged scene exports the fixture byte for byte (all 256 flag bytes
come back), and an edit of the physics of every object lands in bits 6 and 7 of its own byte only.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b21"
TITLE = "all 256 placement bytes import without exception and hand their flags back"
NEEDS_STUB = True


def run(env):
    stub = env.stub
    mj = env.mjolnir
    result, _ = env.import_stub(load=stub.CANNED_PLACEMENT_ALL)
    check_eq(result, {'FINISHED'})
    st = env.state.get(bpy.context.scene)
    check_eq(st["failed_slots"], [], "no failed slot")
    check_eq(len(st["imported_slots"]), 256)
    objs = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_eq(len(objs), 256)
    records = dict((r.slot, r) for r in stub.CANNED_PLACEMENT_ALL.objects)
    seen_symmetry = set()
    for slot, rec in records.items():
        fp = objs[slot].forge
        check_eq(fp.physics, mj.PHYSICS_TO_ENUM[rec.physics], "physics of byte 0x%02X" % rec.placement)
        check_eq(fp.symmetry, mj.SYMMETRY_TO_ENUM[rec.symmetry], "symmetry of byte 0x%02X" % rec.placement)
        check_eq(fp.placeAtStart, rec.place_at_start, "place at start of byte 0x%02X" % rec.placement)
        check_eq(fp.gameSpecific, rec.game_specific, "game specific of byte 0x%02X" % rec.placement)
        check_eq(objs[slot]["mj_physics"], rec.physics)
        seen_symmetry.add(fp.symmetry)
    check_eq(seen_symmetry, {"BOTH", "SYMMETRIC", "ASYMMETRIC", "NEITHER"}, "all four symmetry values occur and display")
    check_eq(sorted(set(r.physics for r in records.values())), [0, 1, 2, 3], "the unused raw physics 2 occurs")
    # every object hands its own flags (raw physics included) back
    collected = env.io_ops.collect_export_objects(bpy.context.scene)
    check_eq([i.code for i in collected.errors], [])
    for eo in collected.objects:
        diffs = bl_common.record_vs_export(records[eo.slot], eo)
        check_eq(diffs, [], "byte 0x%02X comes back unchanged" % records[eo.slot].placement)


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
def placement_all_data():
    spec = rd.w1_spec("b21_placement_all", "256 blocks, one per placement byte")
    slots = []
    for byte in range(256):
        folder = 70 if byte < 128 else 71
        slots.append({"index": byte, "folder": folder, "item": 0, "placement": byte,
                      "pos": [100000 + 2000 * (byte % 16), 200000 + 2000 * (byte // 16), 262144]})
    spec["slots"] = slots
    spec["quotas"]["rows"] = {"70": [0, 255, 128], "71": [0, 255, 128]}
    return rd.build_spec(spec)


def run_real(env):
    mj = env.mjolnir
    data = placement_all_data()
    dec = rd.decode(data)
    check_eq(sorted(s["placement"] for s in dec["slots"].values()), list(range(256)), "the fixture holds every placement byte")
    result, _ = env.import_bytes(data, "b21_all.mvar")
    check_eq(result, {'FINISHED'})
    st = env.state.get(bpy.context.scene)
    check_eq((st["failed_slots"], len(st["imported_slots"])), ([], 256), "no failed slot")
    objs = dict((o["mj_slot"], o) for o in env.forge_objects())
    check_eq(len(objs), 256)
    seen_symmetry = set()
    for byte in range(256):
        fp = objs[byte].forge
        check_eq(fp.physics, mj.PHYSICS_TO_ENUM[byte >> 6], "physics of byte 0x%02X" % byte)
        check_eq(fp.symmetry, {0: "NEITHER", 1: "ASYMMETRIC", 2: "SYMMETRIC", 3: "BOTH"}[(byte >> 2) & 3], "symmetry of byte 0x%02X" % byte)
        check_eq(fp.placeAtStart, not (byte & 0x10), "place at start of byte 0x%02X" % byte)
        check_eq(fp.gameSpecific, bool(byte & 0x20), "game specific of byte 0x%02X" % byte)
        check_eq(objs[byte]["mj_physics"], byte >> 6)
        seen_symmetry.add(fp.symmetry)
    check_eq(seen_symmetry, {"BOTH", "SYMMETRIC", "ASYMMETRIC", "NEITHER"}, "all four symmetry values occur and display")
    # all 256 flag bytes come back: the unchanged scene exports the fixture
    result, path = env.export_to("b21_out.mvar")
    check_eq(result, {'FINISHED'}, "%r\n%s" % (result, env.report_text()[:1500]))
    check(rd.read_bytes(path) == data, "256 placement bytes: a zero diff, byte for byte")
    # a physics edit of every object lands in its own byte's bits 6 and 7 and nowhere else
    for obj in objs.values():
        obj.forge.physics = "FIXED"
    result, path = env.export_to("b21_fixed.mvar")
    check_eq(result, {'FINISHED'}, "%r\n%s" % (result, env.report_text()[:1500]))
    after = rd.decode(rd.read_bytes(path))
    for byte in range(256):
        want = (byte & 0x3F) | 0x40
        check_eq(after["slots"][byte]["placement"], want, "byte 0x%02X with physics FIXED" % byte)
        check_eq(rd.fields_differing(dec["slots"][byte], after["slots"][byte]), ["placement"] if want != byte else [], "slot %d" % byte)


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
