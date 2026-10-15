"""B-08 (SPEC 9.4, 8.7 #7, 3.9): placement byte display and refusal passthrough (glue half).

Display: the file reading of the placement byte (physics bits 6-7, symmetry bits 2-3, place-at-start = bit 4
clear, game-specific = bit 5). The identity token keeps the raw bits. Physics is editable; the unused raw
value 2 is handed back unchanged until the user changes the enum. Symmetry, place-at-start and game-specific
edits are handed to the library as they are (it refuses them with ``E_FLAG_UNVERIFIED``, 3.9): the stub is
told to refuse, and the glue must show the message, write the report and write NO file.

Real variant (``run_real``, G6): the same with the REAL library and a fixture of the independent builder that holds one block
per interesting placement byte. Display, a byte-level zero diff for the unchanged file (including the unused physics value 2),
physics edits landing in bits 6 and 7 of the placement byte and nothing else, and the REAL refusal ``E_FLAG_UNVERIFIED`` for
symmetry, place at start and game specific, with the library's own message and no file.
"""
import dataclasses
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b08"
TITLE = "placement byte display, physics edit, E_FLAG_UNVERIFIED passthrough"
NEEDS_STUB = True


def exported(env, slot):
    result, path = env.export_to("b08_%d.mvar" % slot)
    check_eq(result, {'FINISHED'}, "export")
    return dict((o.slot, o) for o in env.stub.LAST_EXPORT[1])[slot], path


def run(env):
    stub = env.stub
    # --- display decode of a few bytes (all 256 are imported by b21) -------------------------------------
    records = [stub.make_record(1, "Forge World", "Block, 1x1", (0, 0, 0), placement=0xCC),     # phased, both
               stub.make_record(2, "Forge World", "Block, 1x1", (1, 0, 0), placement=0x48),     # fixed, symmetric-only (0x08)
               stub.make_record(3, "Forge World", "Block, 1x1", (2, 0, 0), placement=0x34),     # normal, asymmetric 0x04, not at start, game specific
               stub.make_record(4, "Forge World", "Block, 1x1", (3, 0, 0), placement=0x80)]     # physics raw 2 (unused)
    load = dataclasses.replace(stub.CANNED, objects=records)
    env.import_stub(load=load)
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    fp = lambda s: (by[s].forge.physics, by[s].forge.symmetry, by[s].forge.placeAtStart, by[s].forge.gameSpecific)
    check_eq(fp(1), ("PHASED", "BOTH", True, False))
    check_eq(fp(2), ("FIXED", "SYMMETRIC", True, False))
    check_eq(fp(3), ("NORMAL", "ASYMMETRIC", False, True))
    check_eq(fp(4), ("NORMAL", "NEITHER", True, False), "raw physics 2 is shown as NORMAL, symmetry 0 as NEITHER")
    for s in (1, 2, 3, 4):                                    # the raw bits stay in the identity token
        check_eq(bytes(by[s]["mj_raw"]), dict((r.slot, r) for r in records)[s].raw, "token slot %d" % s)

    # --- unchanged objects hand the file's own values back (including the unused physics 2) ----------------
    for rec in records:
        eo, _path = exported(env, rec.slot)
        check_eq(bl_common.record_vs_export(rec, eo), [], "slot %d unchanged" % rec.slot)
        check_eq(eo.physics, rec.physics)

    # --- physics edits are written as the new value; restoring the display restores the file's value -------
    by[4].forge.physics = "FIXED"
    eo, _path = exported(env, 4)
    check_eq(eo.physics, 1, "physics edit")
    by[4].forge.physics = "PHASED"
    eo, _path = exported(env, 4)
    check_eq(eo.physics, 3)
    by[4].forge.physics = "NORMAL"
    eo, _path = exported(env, 4)
    check_eq(eo.physics, 2, "back to the original display: the original raw value")
    by[1].forge.physics = "NORMAL"
    eo, _path = exported(env, 1)
    check_eq(eo.physics, 0)

    # --- the other flags are passed on; the library refuses them ------------------------------------------------
    by[1].forge.physics = "PHASED"
    for prop, value, field, expected in (("symmetry", "SYMMETRIC", "symmetry", 2),
                                         ("placeAtStart", False, "place_at_start", False),
                                         ("gameSpecific", True, "game_specific", True)):
        old = getattr(by[1].forge, prop)
        setattr(by[1].forge, prop, value)
        message = "Object '%s': %s cannot be changed yet; how it is stored is unverified." % (by[1].name, prop)
        stub.preset_refusal(stub.Issue("E_FLAG_UNVERIFIED", "error", message, 1, by[1].name))
        result, path = env.export_to("b08_refused_%s.mvar" % prop)
        check(isinstance(result, RuntimeError), "the refusal reaches the caller: %r" % (result,))
        check(message in str(result), "message in the error: %s" % result)
        check(not os.path.exists(path), "nothing written")
        eo = dict((o.slot, o) for o in stub.LAST_EXPORT[1])[1]
        check_eq(getattr(eo, field), expected, "%s handed to the library" % field)
        report = env.report_text()
        check("ERROR E_FLAG_UNVERIFIED slot 1 '%s': %s" % (by[1].name, message) in report, report)
        check("REFUSED, nothing was written" in report)
        setattr(by[1].forge, prop, old)


# =====================================================================================================
# the real-provider variant (G6)
# =====================================================================================================
PLACEMENTS = {1: 0xCC, 2: 0x48, 3: 0x34, 4: 0x80}


def placement_fixture():
    spec = rd.w1_spec("b08_placement", "four blocks with different placement bytes")
    spec["slots"] = [{"index": slot, "folder": 70, "item": 0, "pos": [524288 + 3000 * slot, 1048576, 262144], "placement": byte}
                     for slot, byte in sorted(PLACEMENTS.items())]
    spec["quotas"]["rows"] = {"70": [0, 16, 4]}
    return rd.build_spec(spec)


def real_export(env, name, **options):
    result, path = env.export_to(name, **options)
    check_eq(result, {'FINISHED'}, "%s: %r\n%s" % (name, result, env.report_text()[:2000]))
    return rd.read_bytes(path)


def run_real(env):
    data = placement_fixture()
    dec = rd.decode(data)
    for slot, byte in PLACEMENTS.items():
        check_eq(dec["slots"][slot]["placement"], byte)
    env.import_bytes(data, "b08_placement.mvar")
    by = dict((o["mj_slot"], o) for o in env.forge_objects())
    fp = lambda s: (by[s].forge.physics, by[s].forge.symmetry, by[s].forge.placeAtStart, by[s].forge.gameSpecific)
    check_eq(fp(1), ("PHASED", "BOTH", True, False))
    check_eq(fp(2), ("FIXED", "SYMMETRIC", True, False))
    check_eq(fp(3), ("NORMAL", "ASYMMETRIC", False, True))
    check_eq(fp(4), ("NORMAL", "NEITHER", True, False), "raw physics 2 is shown as NORMAL, symmetry 0 as NEITHER")
    for slot in PLACEMENTS:
        check_eq(by[slot]["mj_physics"], PLACEMENTS[slot] >> 6, "the raw physics bits are kept for slot %d" % slot)

    # the unchanged file comes back byte for byte (the unused physics value 2 included)
    check(real_export(env, "b08_noop.mvar") == data, "unchanged: passthrough, byte for byte")

    # physics edits are written into bits 6 and 7 of the placement byte, nothing else changes
    def edit_physics(slot, value, expected_byte):
        env.reset()
        env.import_bytes(data, "b08_edit.mvar")
        obj = dict((o["mj_slot"], o) for o in env.forge_objects())[slot]
        obj.forge.physics = value
        out = rd.decode(real_export(env, "b08_edit_out.mvar"))
        check_eq(rd.slots_equal(dec, out, ignore=(slot,)), [], "physics of slot %d: the other slots are unchanged" % slot)
        check_eq(rd.fields_differing(dec["slots"][slot], out["slots"][slot]), ["placement"], "physics=%s on slot %d" % (value, slot))
        check_eq(out["slots"][slot]["placement"], expected_byte, "the placement byte after physics=%s on slot %d" % (value, slot))

    edit_physics(4, "FIXED", 0x40)               # 0x80 (raw physics 2) -> fixed
    edit_physics(4, "PHASED", 0xC0)
    edit_physics(1, "NORMAL", 0x0C)              # 0xCC -> 0x0C
    edit_physics(1, "FIXED", 0x4C)
    edit_physics(2, "PHASED", 0xC8)              # 0x48 -> 0xC8 (symmetry bits kept)
    edit_physics(3, "FIXED", 0x74)               # 0x34 -> 0x74 (not-at-start and game-specific kept)
    # back to the original display: the original bytes (no change at all)
    env.reset()
    env.import_bytes(data, "b08_back.mvar")
    obj = dict((o["mj_slot"], o) for o in env.forge_objects())[4]
    obj.forge.physics = "FIXED"
    obj.forge.physics = "NORMAL"
    check(real_export(env, "b08_back_out.mvar") == data, "NORMAL again shows the original raw value 2: unchanged")

    # the other flags are refused by the library with its own message; nothing is written
    for prop, value, label in (("symmetry", "SYMMETRIC", "symmetry"), ("placeAtStart", False, "place at start"),
                               ("gameSpecific", True, "game specific")):
        env.reset()
        env.import_bytes(data, "b08_refused.mvar")
        obj = dict((o["mj_slot"], o) for o in env.forge_objects())[1]
        setattr(obj.forge, prop, value)
        result, path = env.export_to("b08_refused_%s.mvar" % prop)
        check(isinstance(result, RuntimeError), "the refusal reaches the caller: %r" % (result,))
        report = env.report_text()
        check("ERROR E_FLAG_UNVERIFIED '%s': Object '%s': %s cannot be changed yet; how it is stored is unverified." % (obj.name, obj.name, label) in report, report[:1800])
        check("REFUSED, nothing was written" in report)
        check(not os.path.exists(path), "nothing written")


if __name__ == "__main__":
    bl_common.main_module(sys.modules[__name__])
