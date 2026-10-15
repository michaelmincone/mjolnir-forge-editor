"""U-13 (SPEC 9.3, tier T2; gate G5): every library-side ``E_``/``W_``/``I_`` code of SPEC 7.3 is triggered once with its exact message.

``CASES`` pairs a code with a scenario and the message written out literally (not computed from the library's table), so a
changed word fails here. A second group of tests compares ``mvarlib.validate.MESSAGES`` with the tables of
``docs/mvar/SPEC-mvar.md`` (7.3 and 5.8), checks the codes that the Blender glue and ``io.py`` produce against the sources of
those files, and covers the rules around the codes: the two DEC-7.4 cases, ``E_TOO_MANY`` for ``full650`` plus one object and
for ``over650`` unchanged, a moved or new object on a zero-range axis, ``E_TRANSFORM_INVALID`` before any codec call, all
problems reported together, and a refusal never leaves bytes.

Everything is built in memory.
"""
import ast
import copy
import math
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import helpers_g5 as h  # noqa: E402

from mvarlib import api, validate  # noqa: E402
from mvarlib.model import MapVariant  # noqa: E402

REPO = h.REPO
W1 = "w1_minimal"


def w1():
    return h.g3.data(W1)


def spec_variant(edit, name=W1):
    """Bytes of the committed fixture spec ``name`` after ``edit(spec_dict)`` (built with the independent builder)."""
    build, _ = h.build_modules()
    spec = copy.deepcopy(build.load_spec(name))
    edit(spec)
    return build.build(spec).data


def block(name="N", cells=(5, 5, 5), **fields):
    fields.setdefault("position", h.cell_centre(h.g3.model(W1), cells))
    return h.new_like_example(w1(), "Block, 1x1", name, **fields)


def with_new(objects_or_data, *new):
    objs = h.objects_for(objects_or_data) if isinstance(objects_or_data, bytes) else list(objects_or_data)
    return objs + list(new)


def issue(result, code, object_name=None):
    found = [i for i in list(result.errors) + list(result.warnings) if i.code == code
             and (object_name is None or i.object_name == object_name)]
    return found[0] if found else None


CASES = []


def case(code, message):
    """Register a scenario ``f() -> ExportResult`` for ``code``; ``message`` is the exact expected text."""
    def register(fn):
        CASES.append((code, message, fn))
        return fn
    return register


# ------------------------------------------------------------------------------------------------ container, map, limits
@case("E_TEMPLATE_UNREADABLE", "The imported map variant could not be read again: This file is not a Halo BLF file (first block is 'XXXX', expected '_blf').")
def _template_unreadable():
    return h.export(b"XXXX" * 10, [])


@case("E_MAP_UNKNOWN", "Map id 4294967295 (0xFFFFFFFF) is not one of the 20 stock Halo: Reach maps this tool supports. Export is limited to stock maps.")
def _map_unknown():
    data = h.g3.data("unknown_map")
    return h.export(data, h.objects_for(data), keep_unrecognised_imported=True)


def other_shape_template():
    """W1 with an unknown block between ``mvar`` and ``_eof``: the block list is not one of the supported shapes."""
    data = w1()
    unknown = b"abcd" + (16).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + bytes(4)
    cut = h.MVAR + 0x7028
    return data[:cut] + unknown + data[cut:]


@case("E_CONTAINER_SHAPE", "This file's block layout (_blf, chdr, mvar, abcd, _eof) cannot be modified safely.")
def _container_shape():
    data = other_shape_template()
    objs = h.objects_for(data)
    pos = h.by_slot(objs, 1).position
    h.change(objs, 1, position=(pos[0] + 5.0, pos[1], pos[2]))
    return h.export(data, objs)


@case("E_TOO_MANY", "651 objects would be written; the limit is 650. Remove 1 object(s). (A file that already holds more than 650 objects cannot be exported.)")
def _too_many():
    data = h.g3.data("full650")
    objs = h.objects_for(data)
    objs.append(h.new_like_example(data, "Block, 1x1", "One too many"))
    return h.export(data, objs, **h.GATE, raise_quota_max=True)


@case("E_NO_FREE_SLOT", "No free object slot is left for 'B'.")
def _no_free_slot():
    data = h.g3.data("full650")                           # 650 occupied: one absent slot is left
    objs = h.objects_for(data)
    objs.append(h.new_like_example(data, "Block, 1x1", "A"))
    objs.append(h.new_like_example(data, "Block, 1x1", "B"))
    return h.export(data, objs, **h.GATE, raise_quota_max=True, max_objects=1000)


# ------------------------------------------------------------------------------------------------ types and folders
@case("E_OBJ_NO_TYPE", "Object 'T' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object.")
def _obj_no_type():
    return h.export(w1(), with_new(w1(), h.new_object("T", type_name="", position=(1.0, 1.0, 1.0))), **h.GATE)


@case("E_OBJ_NAME_UNKNOWN", "Object 'N' uses 'Wibble', which is not a stock object on Forge World.")
def _name_unknown():
    return h.export(w1(), with_new(w1(), h.new_object("N", type_name="Wibble", position=(1.0, 1.0, 1.0))), **h.GATE)


@case("E_OBJ_NOT_STOCK", "Object '4 - Unknown (0x0C04)' (id 0x0C04) is not a stock object on Forge World.")
def _obj_not_stock():
    data = h.g3.data("holes")
    return h.export(data, h.objects_for(data))


@case("E_FOLDER_RANGE", "Object 'N' needs palette entry 144, but this map variant defines only 80 entries.")
def _folder_range():
    return h.export(w1(), with_new(w1(), h.new_object("N", type_name="Location Name", position=(1.0, 1.0, 1.0))), **h.GATE)


@case("E_OUT_OF_BOUNDS", "Object 'N' is at (1000.000, 0.000, 0.000), outside the map bounds (x -240.0 to 240.0, y -345.0 to 345.0, z -70.0 to 70.0). Move it inside; positions are never clamped.")
def _out_of_bounds():
    return h.export(w1(), with_new(w1(), block("N", position=(1000.0, 0.0, 0.0))), **h.GATE)


@case("E_QUOTA", "Palette entry 61 (Kill Boundary) would have 2 placed; the maximum on this map variant is 1.")
def _quota():
    kill = h.new_like_example(w1(), "Kill Boundary", "Second", position=(1.0, 1.0, 1.0))
    return h.export(w1(), with_new(w1(), kill), **h.GATE)


def quota_variant(row70):
    def edit(spec):
        spec["quotas"]["rows"]["70"] = list(row70)
    return spec_variant(edit)


@case("E_QUOTA_MIN", "Palette entry 70 (Block, 1x1) would drop to 1 placed; the minimum on this map variant is 2.")
def _quota_min():
    data = quota_variant((2, 16, 2))
    return h.export(data, h.without(h.objects_for(data), 1))


@case("E_QUOTA_RANGE", "Palette entry 70 (Block, 1x1) cannot hold more than 255 objects.")
def _quota_range():
    data = quota_variant((0, 255, 255))
    return h.export(data, with_new(data, block("N")), **h.GATE)


@case("E_CACHED_TYPE_UNKNOWN", "Cannot add a new 'Assault Rifle': its game object class is not known from this map variant. Place one in the game and import again, or duplicate an object of the same kind.")
def _cached_type_unknown():
    return h.export(w1(), with_new(w1(), h.new_object("N", type_name="Assault Rifle", position=(1.0, 1.0, 1.0))), **h.GATE)


@case("E_CACHED_TYPE_CHANGED", "Object '1 - Block, 1x1': the object class cannot be changed.")
def _cached_type_changed():
    objs = h.objects_for(w1())
    h.change(objs, 1, cached_type=5)
    return h.export(w1(), objs)


@case("E_RETARGET_CLASS", "Object '5 - Kill Boundary' cannot change from 'Kill Boundary' to 'Block, 1x1, Flat': they are different object classes.")
def _retarget_class():
    objs = h.objects_for(w1())
    h.change(objs, 5, type_name="Block, 1x1, Flat")
    return h.export(w1(), objs)


@case("E_TYPE19_UNDETERMINED", "Location-name objects cannot be created or edited yet: this map variant contains none, so how they are stored is undetermined.")
def _type19_undetermined():
    def edit(spec):
        spec["body"]["quota_count"] = 160
    data = spec_variant(edit)
    assert MapVariant.from_bytes(data).type19_status == "undetermined"
    return h.export(data, with_new(data, h.new_object("N", type_name="Location Name", position=(1.0, 1.0, 1.0), cached_type=19)), **h.GATE)


# ------------------------------------------------------------------------------------------------ orientation and flags
@case("E_ROTATION_GATED", "Object 'N' has a new or changed rotation. Writing rotation is unverified: tick Forge Scene > \"Allow unverified rotation export\" to write it.")
def _rotation_gated():
    return h.export(w1(), with_new(w1(), block("N")))


@case("E_TILT_UNSUPPORTED", "Object 'N' is tilted. Writing a tilted orientation is not supported; rotate it around Z only, or leave its rotation unchanged.")
def _tilt():
    return h.export(w1(), with_new(w1(), block("N", up=(0.0, 0.7071067811865476, 0.7071067811865476), forward=(1.0, 0.0, 0.0))), **h.GATE)


@case("E_TRANSFORM_INVALID", "Object 'N' has an invalid (non-finite or zero-length) position, forward or up vector and cannot be exported.")
def _transform_invalid():
    return h.export(w1(), with_new(w1(), block("N", position=(float("nan"), 0.0, 0.0))), **h.GATE)


@case("E_FLAG_UNVERIFIED", "Object '1 - Block, 1x1': symmetry cannot be changed yet; how it is stored is unverified.")
def _flag_unverified():
    objs = h.objects_for(w1())
    h.change(objs, 1, symmetry=2)
    return h.export(w1(), objs)


# ------------------------------------------------------------------------------------------------ plain field ranges
@case("E_COLOR_NEUTRAL", "Object 'N': the colour \"Neutral\" cannot be stored in a map variant (use colours 0 to 7 or \"Team\").")
def _color_neutral():
    return h.export(w1(), with_new(w1(), block("N", color=8)), **h.GATE)


@case("E_COLOR_RANGE", "Object 'N': the colour must be -1 (team colour) or 0 to 7 (got 9).")
def _color_range():
    return h.export(w1(), with_new(w1(), block("N", color=9)), **h.GATE)


@case("E_TEAM_RANGE", "Object 'N': team must be 0 to 8.")
def _team_range():
    return h.export(w1(), with_new(w1(), block("N", team=9)), **h.GATE)


@case("E_SHAPE_RANGE", "Object 'N': width must be between 0 and 200 (got 200.500).")
def _shape_range():
    return h.export(w1(), with_new(w1(), block("N", shape=3, width=200.5, length=1.0, top=1.0, bottom=1.0)), **h.GATE)


@case("E_SPAWN_RANGE", "Object 'N': spawn sequence must be -128 to 127 and spawn time 0 to 255.")
def _spawn_range():
    return h.export(w1(), with_new(w1(), block("N", spawn_sequence=128)), **h.GATE)


@case("E_LABEL_RANGE", "Object 'N': label 3 is not in this map variant's label table (3 labels).")
def _label_range():
    return h.export(w1(), with_new(w1(), block("N", label_index=3)), **h.GATE)


@case("E_PHYSICS_RANGE", "Object 'N': physics must be 0 (normal), 1 (fixed) or 3 (phased) (got 4).")
def _physics_range():
    return h.export(w1(), with_new(w1(), block("N", physics=4)), **h.GATE)


@case("E_OTHER_RANGE", "Object 'N': other_a must be 0 to 0.")
def _other_range():
    return h.export(w1(), with_new(w1(), block("N", other_a=3)), **h.GATE)


@case("E_CAPACITY", "The edited map variant needs 229438 bits; it can hold at most 229,376.")
def _capacity():
    data = h.g3.data("near_full")
    objs = h.objects_for(data)
    objs.append(h.new_like_example(data, "Block, 1x1", "N"))
    return h.export(data, objs, **h.GATE, keep_unrecognised_imported=True, raise_quota_max=True)


@case("E_OPTION_INVALID", "The export option hash_policy has the unknown value 'MD5'.")
def _option_invalid():
    return h.export(w1(), h.objects_for(w1()), hash_policy="MD5")


# ------------------------------------------------------------------------------------------------ warnings from the template
@case("W_HASH_UNKNOWN", "The template's SHA-1 matches no known recipe; the salted recipe was written. Whether MCC checks it is unknown.")
def _hash_unknown():
    data = bytearray(w1())
    data[h.HASH_AT] ^= 0x55
    objs = h.objects_for(bytes(data))
    pos = h.by_slot(objs, 1).position
    h.change(objs, 1, position=(pos[0] + 2.0, pos[1], pos[2]))
    return h.export(bytes(data), objs)


@case("W_GUID_VERSION_MISMATCH", "This map variant says it has version 32 but the 128-bit block that versions 32 and above carry is missing; it was read that way because only that reading fits.")
def _guid_mismatch():
    data = h.g3.data("guid_v32_absent")
    return h.export(data, h.objects_for(data), keep_unrecognised_imported=True)


def with_chunk_version(version):
    data = bytearray(w1())
    data[h.MVAR + 8:h.MVAR + 10] = version.to_bytes(2, "big")
    return bytes(data)


@case("W_VERSION_MISMATCH", "The map variant block has chunk version 32 but its body says version 31.")
def _version_mismatch():
    data = with_chunk_version(32)
    return h.export(data, h.objects_for(data))


@case("W_CHUNK_VERSION_UNEXPECTED", "The map variant block has chunk version 40; Halo: Reach uses 31 or 32. It was read anyway because the layout fits.")
def _chunk_version_unexpected():
    data = with_chunk_version(40)
    return h.export(data, h.objects_for(data))


@case("W_ZERO_RANGE_AXIS", "The map bounds have no extent on the z axis; positions on that axis cannot be changed.")
def _zero_range():
    data = h.g3.data("extremes")
    return h.export(data, h.objects_for(data), keep_unrecognised_imported=True)


@case("W_TRAILER_KEPT", "512 bytes after the end-of-file block were kept unchanged.")
def _trailer_kept():
    data = h.g3.data("trailer")
    return h.export(data, h.without(h.objects_for(data), 5))


@case("W_CMP_EXPANDED", "The map variant was stored compressed; the exported file stores it uncompressed (the game accepts both, per the available documentation).")
def _cmp_expanded():
    data = h.g3.data("cmp")
    return h.export(data, h.without(h.objects_for(data), 5))


@case("W_FSM_STALE", "The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, export again with fsm_policy = DROP.")
def _fsm_stale():
    data = h.g3.data("fsm")
    return h.export(data, h.without(h.objects_for(data), 5))


# ------------------------------------------------------------------------------------------------ warnings from the plan
@case("W_TOKEN_MISMATCH", "Object 'Copied' claims slot 2 but does not match the imported file (copied from another file?); it was treated as a new object.")
def _token_mismatch():
    objs = h.objects_for(w1())
    objs.append(h.export_object(h.g3.model(W1).objects()[0], name="Copied", slot=2))
    return h.export(w1(), objs, **h.GATE)


@case("W_DUPLICATE_SLOT", "Objects '1 - Block, 1x1' and 'Copy' both claim slot 1; kept '1 - Block, 1x1' and treated 'Copy' as new.")
def _duplicate_slot():
    objs = h.objects_for(w1())
    objs.append(h.export_object(h.g3.model(W1).objects()[0], name="Copy", name_matches_import=False))
    return h.export(w1(), objs, **h.GATE)


@case("W_SLOT_NOT_IMPORTED", "Slot 5 could not be imported earlier; it was left unchanged in the exported file.")
def _slot_not_imported():
    return h.export(w1(), h.without(h.objects_for(w1()), 5), imported_slots=[1, 650])


@case("W_PARENT_CLEARED", "Slot 650 lost its \"spawn relative to\" parent because slot 1 was deleted.")
def _parent_cleared():
    return h.export(w1(), h.without(h.objects_for(w1()), 1))


@case("W_ORIENTATION_UNVERIFIED", "1 object(s) had their rotation written with an unverified convention.")
def _orientation_unverified():
    return h.export(w1(), with_new(w1(), block("N")), **h.GATE)


@case("W_CACHED_TYPE_ASSUMED", "The object class of the new 'Bridge, Small' was assumed from its palette group, not learned from the map.")
def _cached_type_assumed():
    bridge = h.new_object("N", type_name="Bridge, Small", position=(1.0, 1.0, 1.0))
    return h.export(w1(), with_new(w1(), bridge), **h.GATE, raise_quota_max=True)


def tempest_template():
    """A Tempest (2004) map variant with a Respawn... no: a Cannon, Man (0x2800, class 0) so that the class of its folder is learned."""
    def edit(spec):
        spec["header"]["map_id"] = 2004
        spec["body"]["map_id_2"] = 2004
        spec["slots"][0].update({"folder": 40, "item": 0})
        spec["slots"][1].update({"folder": 58, "item": 0})
        spec["slots"][2].update({"folder": 67, "item": 0})
        spec["quotas"]["rows"] = {"58": [0, 1, 1], "40": [0, 5, 1], "67": [0, 16, 1]}
    return spec_variant(edit)


@case("W_DISPUTED_ID", "The id of 'Cannon, Man, Heavy' differs between the two source tables on Tempest; check it in the game.")
def _disputed_id():
    data = tempest_template()
    heavy = h.new_object("N", type_name="Cannon, Man, Heavy", position=(1.0, 1.0, 1.0))
    heavy.physics, heavy.symmetry = 3, 3
    return h.export(data, with_new(data, heavy), **h.GATE)


@case("W_UNKNOWN_TYPE_KEPT", "Object '4 - Unknown (0x0C04)' has an id (0x0C04) this tool does not know on Forge World; it was kept exactly as imported.")
def _unknown_type_kept():
    data = h.g3.data("holes")
    return h.export(data, h.objects_for(data), keep_unrecognised_imported=True)


@case("W_QUOTA_MAX_RAISED", "Quota maximum raised: unverified. Palette entry 61 (Kill Boundary) now has 2 placed; its maximum was raised from 1 to 2. Whether the game honours the file's maximum or rebuilds it from the scenario is unknown.")
def _quota_max_raised():
    kill = h.new_like_example(w1(), "Kill Boundary", "Second", position=(1.0, 1.0, 1.0))
    return h.export(w1(), with_new(w1(), kill), **h.GATE, raise_quota_max=True)


# ------------------------------------------------------------------------------------------------ the notes
@case("I_BUDGET", "Budget was not recalculated: item prices are not stored in the map variant, so the spent-budget value was copied unchanged. Open the map in Forge and check the budget meter before playing.")
def _i_budget():
    return h.export(w1(), h.objects_for(w1()))


@case("I_PALETTE", "Edits were written against the palette recorded in the file (CRC 0xDEADBEEF). If MCC rebuilds the variant from the scenario, changes may be lost (unverified).")
def _i_palette():
    return h.export(w1(), h.objects_for(w1()))


@case("I_UNVERIFIED", "This tool has never been checked against a real MCC load. Follow the test ladder in the documentation (NOTES.md) before relying on the output.")
def _i_unverified():
    return h.export(w1(), h.objects_for(w1()))


@case("I_HASH_ZERO", "The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for MCC-written game variants); none was written.")
def _i_hash_zero():
    data = h.g3.data("zero_hash")
    return h.export(data, h.without(h.objects_for(data), 5))


class TestEveryCode(unittest.TestCase):
    def test_each_code_is_raised_with_its_exact_message(self):
        for code, message, fn in CASES:
            with self.subTest(code):
                result = fn()
                found = [i for i in list(result.errors) + list(result.warnings) if i.code == code and i.message == message]
                self.assertTrue(found, "%s with that message was not reported; got %s" % (
                    code, [(i.code, i.message) for i in list(result.errors) + list(result.warnings) if i.code == code]
                    or [i.code for i in list(result.errors) + list(result.warnings)]))
                if code.startswith("E_"):
                    self.assertFalse(result.ok)
                    self.assertIsNone(result.data, "a refusal never returns bytes")
                    self.assertEqual(found[0].severity, "error")
                else:
                    self.assertEqual(found[0].severity, "warning" if code.startswith("W_") else "info")

    def test_the_cases_cover_every_library_code(self):
        covered = set(code for code, _m, _f in CASES)
        self.assertEqual(sorted(validate.LIBRARY_CODES - covered), [], "a library code has no scenario")
        self.assertEqual(sorted(covered - set(validate.MESSAGES)), [])

    def test_a_scenario_message_is_the_table_message(self):
        for code, message, _fn in CASES:
            severity, pattern = validate.MESSAGES[code]
            self.assertEqual(message.count("\n"), 0)
            regex = "^" + re.escape(pattern).replace("%s", ".*").replace("%d", "-?[0-9]+").replace("%r", ".*") \
                .replace("%\\.3f", "-?[0-9.]+").replace("%\\.1f", "-?[0-9.]+").replace("%X", "[0-9A-F]+").replace("%04X", "[0-9A-F]{4}") \
                .replace("%08X", "[0-9A-F]{8}") + "$"
            self.assertTrue(re.match(regex.replace("\\%", "%"), message), "%s: %r does not fit %r" % (code, message, pattern))


# =====================================================================================================
def spec_tables():
    """``{code: (severity, pattern)}`` read from the tables of SPEC 7.3 and 5.8."""
    with open(os.path.join(REPO, "docs", "mvar", "SPEC-mvar.md"), "r", encoding="utf-8") as fh:
        text = fh.read()
    out = {}
    for line in text.split("\n"):
        m = re.match(r"^\| `([EWI]_[A-Z0-9_]+)` \| (error|warning|info) \|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        pattern = cells[-1]
        if pattern.startswith("`") and pattern.endswith("`"):
            out[m.group(1)] = (m.group(2), pattern[1:-1])
        else:
            out[m.group(1)] = (m.group(2), None)                          # 'text in 5.8'
    notes = {}
    for m in re.finditer(r"^\| [^|]+ \| [^|]+ \| `((?:Budget was not|Edits were written|This tool has never)[^`]*)` \|$", text, re.M):
        notes[m.group(1)[:11]] = m.group(1)
    return out, notes


class TestMessagesAgainstTheSpec(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table, cls.notes = spec_tables()

    def test_every_code_of_the_table_has_the_spec_pattern(self):
        self.assertGreaterEqual(len(self.table), 55)
        for code, (severity, pattern) in self.table.items():
            with self.subTest(code):
                self.assertIn(code, validate.MESSAGES, "SPEC 7.3 lists %s but validate.MESSAGES does not" % code)
                self.assertEqual(validate.MESSAGES[code][0], severity)
                if pattern is not None:
                    self.assertEqual(validate.MESSAGES[code][1], pattern)

    def test_the_budget_palette_and_unverified_notes_are_the_texts_of_5_8(self):
        self.assertEqual(validate.MESSAGES["I_BUDGET"][1], self.notes["Budget was "])
        self.assertEqual(validate.MESSAGES["I_PALETTE"][1], self.notes["Edits were "])
        self.assertEqual(validate.MESSAGES["I_UNVERIFIED"][1], self.notes["This tool h"])
        for code in ("I_BUDGET", "I_PALETTE", "I_UNVERIFIED"):
            self.assertIsNone(self.table[code][1], "7.3 points to 5.8 for the text of " + code)

    def test_nothing_in_the_library_table_is_missing_from_the_spec(self):
        self.assertEqual(sorted(set(validate.MESSAGES) - set(self.table)), [])

    def test_the_shape_kind_sentence_is_in_the_spec(self):
        with open(os.path.join(REPO, "docs", "mvar", "SPEC-mvar.md"), "r", encoding="utf-8") as fh:
            self.assertIn(validate.SHAPE_KIND_PATTERN, fh.read())

    def test_every_pattern_formats_with_its_number_of_arguments(self):
        for code, (severity, pattern) in validate.MESSAGES.items():
            n = len(re.findall(r"%[-0-9.]*[sdrXf]", pattern))
            args = tuple(["x" if re.search(r"%[-0-9.]*[sr]", p) else 1 for p in re.findall(r"%[-0-9.]*[sdrXf]", pattern)])
            self.assertEqual(len(args), n)
            validate.make(code, *args)


class TestGlueCodes(unittest.TestCase):
    """The codes the Blender glue and io.py produce (7.3 'Source' glue / io): their texts must be the table's."""

    def string_constants(self):
        found = set()
        for rel in ("Addon/mjolnir.py", "Addon/io_ops.py", "Addon/state.py", "Addon/mvarlib/io.py"):
            with open(os.path.join(REPO, *rel.split("/")), "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    found.add(node.value)
        return found

    def test_the_glue_uses_the_table_texts(self):
        constants = self.string_constants()
        for code in sorted(validate.GLUE_CODES):
            with self.subTest(code):
                self.assertIn(validate.MESSAGES[code][1], constants, "no string in the glue equals the 7.3 pattern of %s" % code)

    def test_e_obj_no_type_is_raised_by_both(self):
        """The glue raises it for an object that never came from the file; the library for an imported one with no type at all."""
        constants = self.string_constants()
        self.assertIn(validate.MESSAGES["E_OBJ_NO_TYPE"][1], constants)
        result = h.export(w1(), h.objects_for(w1()) + [h.new_object("T", type_name="", position=(1.0, 1.0, 1.0))], **h.GATE)
        self.assertEqual(issue(result, "E_OBJ_NO_TYPE").message, validate.MESSAGES["E_OBJ_NO_TYPE"][1] % "T")


# =====================================================================================================
class TestDec74TwoTiers(unittest.TestCase):
    """DEC-7.4: an imported object whose id is not in the map's stock table is refused, unless the owner keeps those."""

    def test_default_refuses_every_unrecognised_imported_object(self):
        data = h.g3.data("holes")
        result = h.export(data, h.objects_for(data))
        refused = [e.object_name for e in result.errors if e.code == "E_OBJ_NOT_STOCK"]
        model = h.g3.model("holes")
        expected = ["%d - %s" % (r.slot, r.type_name) for r in model.objects() if not r.stock and r.type_id >= 0]
        self.assertEqual(sorted(refused), sorted(expected))
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)

    def test_keeping_them_exports_the_template_unchanged_with_one_warning_each(self):
        data = h.g3.data("holes")
        result = h.export(data, h.objects_for(data), keep_unrecognised_imported=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)
        kept = [w.object_name for w in result.warnings if w.code == "W_UNKNOWN_TYPE_KEPT"]
        self.assertEqual(len(kept), sum(1 for r in h.g3.model("holes").objects() if not r.stock))

    def test_an_unrecognised_object_that_is_deleted_is_not_checked(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        bad = [r.slot for r in model.objects() if not r.stock]
        objs = h.without(h.objects_for(model), *bad)
        result = h.export(data, objs)
        self.assertTrue(result.ok, [e.message for e in result.errors])

    def test_ids_that_are_in_the_table_are_kept_verbatim(self):
        """Tier 1: an imported stock object keeps its folder and item bits whatever its type name says (even a renamed collection that resolves to the same id)."""
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="")                                  # model-less: only the imported id
        self.assertEqual(h.export(w1(), objs).data, w1())

    def test_a_new_object_cannot_be_unrecognised_even_with_the_option(self):
        objs = with_new(w1(), h.new_object("N", type_name="", type_id_hint=0x0101, position=(1.0, 1.0, 1.0)))
        result = h.export(w1(), objs, **h.GATE, keep_unrecognised_imported=True)
        self.assertEqual(issue(result, "E_OBJ_NOT_STOCK").message, "Object 'N' (id 0x0101) is not a stock object on Forge World.")

    def test_a_retarget_to_an_unrecognised_id_is_refused(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, type_name="", type_id_hint=0x0101)
        result = h.export(w1(), objs, keep_unrecognised_imported=True)
        self.assertEqual(issue(result, "E_OBJ_NOT_STOCK").message, "Object '1 - Block, 1x1' (id 0x0101) is not a stock object on Forge World.")

    def test_an_imported_object_with_no_type_at_all(self):
        data = h.g3.data("extremes")
        result = h.export(data, h.objects_for(data))
        self.assertIn("Object '2 - Unknown (no type)' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object.",
                      [e.message for e in result.errors if e.code == "E_OBJ_NO_TYPE"])
        kept = h.export(data, h.objects_for(data), keep_unrecognised_imported=True)
        self.assertTrue(kept.ok)
        self.assertIn("Object '2 - Unknown (no type)' has an id (0xFFFF) this tool does not know on Forge World; it was kept exactly as imported.",
                      [w.message for w in kept.warnings if w.code == "W_UNKNOWN_TYPE_KEPT"])

    def test_a_non_stock_map_skips_the_type_checks_but_is_refused(self):
        data = h.g3.data("unknown_map")
        result = h.export(data, h.objects_for(data))
        self.assertEqual(sorted(set(h.codes(result.errors))), ["E_MAP_UNKNOWN"], "one root cause, no flood of per-object errors")


class TestObjectLimit(unittest.TestCase):
    def test_full650_exports_unchanged(self):
        data = h.g3.data("full650")
        result = h.export(data, h.objects_for(data))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)

    def test_full650_plus_one_object_is_refused(self):
        data = h.g3.data("full650")
        objs = h.objects_for(data)
        objs.append(h.new_like_example(data, "Block, 1x1", "Extra"))
        result = h.export(data, objs, **h.GATE)
        self.assertIsNone(result.data)
        self.assertEqual(issue(result, "E_TOO_MANY").message,
                         "651 objects would be written; the limit is 650. Remove 1 object(s). (A file that already holds more than 650 objects cannot be exported.)")

    def test_full650_replace_one_object_stays_at_650(self):
        data = h.g3.data("full650")
        model = h.g3.model("full650")
        victim = model.objects()[10].slot
        objs = h.without(h.objects_for(model), victim)
        objs.append(h.new_like_example(model, model.objects()[10].type_name, "Replacement"))
        result = h.export(data, objs, **h.GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.stats["occupied_after"], 650)

    def test_over650_is_refused_even_when_nothing_changes(self):
        data = h.g3.data("over650")
        result = h.export(data, h.objects_for(data))
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual([e.message for e in result.errors],
                         ["651 objects would be written; the limit is 650. Remove 1 object(s). (A file that already holds more than 650 objects cannot be exported.)"])

    def test_over650_with_a_raised_limit_is_passthrough(self):
        data = h.g3.data("over650")
        result = h.export(data, h.objects_for(data), max_objects=651)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)

    def test_deleting_one_object_of_over650_makes_it_exportable(self):
        data = h.g3.data("over650")
        result = h.export(data, h.without(h.objects_for(data), 0))
        self.assertTrue(result.ok, [e.message for e in result.errors])
        self.assertEqual(result.stats["occupied_after"], 650)

    def test_the_limit_counts_the_state_after_all_edits(self):
        objs = with_new(w1(), *[block("N%d" % i, (i, i, i)) for i in range(3)])
        self.assertTrue(h.export(w1(), objs, **h.GATE, max_objects=6).ok)
        refused = h.export(w1(), objs, **h.GATE, max_objects=5)
        self.assertEqual(issue(refused, "E_TOO_MANY").message,
                         "6 objects would be written; the limit is 5. Remove 1 object(s). (A file that already holds more than 5 objects cannot be exported.)")


class TestZeroRangeAxis(unittest.TestCase):
    """`extremes` has a zero-range z axis (min == max == 50): SPEC 3.3, 4.2, 7.3."""

    def setUp(self):
        self.data = h.g3.data("extremes")
        self.model = h.g3.model("extremes")

    def test_untouched_objects_keep_their_raw_cell_on_that_axis(self):
        result = h.export(self.data, h.objects_for(self.model), keep_unrecognised_imported=True)
        self.assertEqual(result.data, self.data)

    def test_moving_x_or_y_is_fine(self):
        objs = h.objects_for(self.model)
        pos = h.by_slot(objs, 0).position
        h.change(objs, 0, position=(pos[0] + 100.0, pos[1], pos[2]))
        result = h.export(self.data, objs, keep_unrecognised_imported=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])

    def test_moving_z_is_refused_with_the_bounds_message(self):
        objs = h.objects_for(self.model)
        pos = h.by_slot(objs, 0).position
        h.change(objs, 0, position=(pos[0], pos[1], pos[2] + 1.0))
        result = h.export(self.data, objs, keep_unrecognised_imported=True)
        self.assertEqual(issue(result, "E_OUT_OF_BOUNDS").message,
                         "Object '0 - Assault Rifle' is at (-2500.000, 0.000, 51.000), outside the map bounds (x -2500.0 to 2500.0, "
                         "y 0.0 to 10.0, z 50.0 to 50.0). Move it inside; positions are never clamped.")

    def test_a_new_object_is_refused_even_exactly_on_the_axis(self):
        new = h.new_object("N", type_name="Assault Rifle", position=(0.0, 5.0, 50.0))
        result = h.export(self.data, h.objects_for(self.model) + [new], **h.GATE, keep_unrecognised_imported=True)
        self.assertEqual(issue(result, "E_OUT_OF_BOUNDS").message,
                         "Object 'N' is at (0.000, 5.000, 50.000), outside the map bounds (x -2500.0 to 2500.0, y 0.0 to 10.0, z 50.0 to 50.0). "
                         "Move it inside; positions are never clamped.")


class TestTransformsAndRanges(unittest.TestCase):
    def test_non_finite_and_zero_length_vectors_are_invalid_before_any_codec_call(self):
        bad = [dict(position=(float("nan"), 0.0, 0.0)), dict(position=(0.0, float("inf"), 0.0)),
               dict(position=(0.0, 0.0, -float("inf"))), dict(forward=(0.0, 0.0, 0.0)), dict(forward=(float("nan"), 0.0, 0.0)),
               dict(up=(0.0, 0.0, 0.0)), dict(up=(0.0, 0.0, 1e-7)), dict(forward=(1e-7, 0.0, 0.0)), dict(up=(float("inf"), 0.0, 1.0))]
        for fields in bad:
            with self.subTest(fields):
                objs = h.objects_for(w1())
                h.change(objs, 1, **fields)
                result = h.export(w1(), objs, **h.GATE)
                self.assertEqual(h.codes(result.errors), ["E_TRANSFORM_INVALID"])
                self.assertIsNone(result.data)
                new = block("N", **fields)
                result = h.export(w1(), with_new(w1(), new), **h.GATE)
                self.assertEqual(h.codes(result.errors), ["E_TRANSFORM_INVALID"])

    def test_an_invalid_transform_does_not_delete_the_object(self):
        objs = h.objects_for(w1())
        h.change(objs, 1, position=(float("nan"), 0.0, 0.0))
        result = h.export(w1(), objs)
        self.assertNotIn("removed", [e.kind for e in result.diff])

    def test_all_range_errors_are_reported_together(self):
        objs = with_new(w1(), block("A", color=8, team=9, spawn_sequence=-129, spawn_time=256, label_index=7, physics=5,
                                    shape=3, width=-1.0, length=201.0, top=float("nan"), bottom=0.0))
        result = h.export(w1(), objs, **h.GATE)
        self.assertEqual(sorted(h.codes(result.errors)),
                         sorted(["E_COLOR_NEUTRAL", "E_TEAM_RANGE", "E_SPAWN_RANGE", "E_LABEL_RANGE", "E_PHYSICS_RANGE",
                                 "E_SHAPE_RANGE", "E_SHAPE_RANGE", "E_SHAPE_RANGE"]))
        shape = sorted(e.message for e in result.errors if e.code == "E_SHAPE_RANGE")
        self.assertEqual(shape, ["Object 'A': length must be between 0 and 200 (got 201.000).",
                                 "Object 'A': top must be between 0 and 200 (got nan).",
                                 "Object 'A': width must be between 0 and 200 (got -1.000)."])

    def test_the_shape_kind_has_its_own_sentence(self):
        result = h.export(w1(), with_new(w1(), block("A", shape=4)), **h.GATE)
        self.assertEqual([e.message for e in result.errors],
                         ["Object 'A': the shape must be 0 (none), 1 (radius only), 2 (cylinder) or 3 (box) (got 4)."])

    def test_unused_dimensions_are_not_checked(self):
        result = h.export(w1(), with_new(w1(), block("A", shape=1, width=5.0, length=999.0, top=-5.0, bottom=float("nan"))), **h.GATE)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        dims = h.decode(result.data)["slots"][0]["dims"]
        self.assertEqual(len(dims), 1)

    def test_dimension_limits_are_inclusive(self):
        for value, code in ((0.0, 0x000), (200.0, 0x7FF)):
            result = h.export(w1(), with_new(w1(), block("A", shape=1, width=value)), **h.GATE)
            self.assertTrue(result.ok)
            self.assertEqual(h.decode(result.data)["slots"][0]["dims"], [code])

    def test_boundary_values_of_the_integer_fields_are_accepted(self):
        for fields in (dict(spawn_sequence=-128), dict(spawn_sequence=127), dict(spawn_time=0), dict(spawn_time=255),
                       dict(team=0), dict(team=8), dict(color=0), dict(color=7), dict(label_index=0), dict(label_index=2)):
            with self.subTest(fields):
                result = h.export(w1(), with_new(w1(), block("A", **fields)), **h.GATE)
                self.assertTrue(result.ok, (fields, [e.message for e in result.errors]))
        for fields in (dict(spawn_sequence=-129), dict(spawn_time=-1), dict(team=-1), dict(label_index=-2), dict(color=-2)):
            with self.subTest(fields):
                result = h.export(w1(), with_new(w1(), block("A", **fields)), **h.GATE)
                self.assertFalse(result.ok, fields)

    def test_the_label_must_be_a_present_entry(self):
        """`extremes` has 256 labels of which 3, 100 and 254 are absent entries: an absent entry has no text, so it cannot be used."""
        data = h.g3.data("extremes")
        new = h.new_object("N", type_name="Assault Rifle", position=(0.0, 5.0, 50.0), label_index=3)
        result = h.export(data, h.objects_for(data) + [new], **h.GATE, keep_unrecognised_imported=True)
        self.assertIn("Object 'N': label 3 is not in this map variant's label table (256 labels).",
                      [e.message for e in result.errors if e.code == "E_LABEL_RANGE"])
        ok_label = h.new_object("M", type_name="Assault Rifle", position=(0.0, 5.0, 50.0), label_index=4)
        result = h.export(data, h.objects_for(data) + [ok_label], **h.GATE, keep_unrecognised_imported=True)
        self.assertNotIn("E_LABEL_RANGE", h.codes(result.errors))

    def test_nothing_is_written_for_any_refusal(self):
        result = h.export(w1(), with_new(w1(), block("A", color=8)), **h.GATE)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.stats["occupied_before"], 3)
        self.assertEqual(result.stats["capacity_bits"], 229376)

    def test_garbage_in_the_object_list_never_raises(self):
        junk = block("J", position=(float("nan"),) * 3, forward=(0.0, 0.0, 0.0), up=(float("inf"), 0.0, 0.0), shape=9,
                     width=float("nan"), team=99, color=99, spawn_sequence=10 ** 9, label_index=10 ** 9, physics=99)
        result = h.export(w1(), with_new(w1(), junk), **h.GATE)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)


class TestOtherFields(unittest.TestCase):
    def test_other_a_other_b_ranges_by_class_on_a_template_that_has_every_class(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        by_class = dict((r.cached_type, r.slot) for r in model.objects())
        opts = dict(keep_unrecognised_imported=True)
        # class 1: other_a 0..255, other_b must stay 0
        slot = by_class[1]
        objs = h.objects_for(model)
        h.change(objs, slot, other_a=7)
        self.assertTrue(h.export(data, objs, **opts).ok)
        h.change(objs, slot, other_a=256)
        self.assertEqual([e.message for e in h.export(data, objs, **opts).errors], ["Object '%d - Assault Rifle': other_a must be 0 to 255." % slot])
        h.change(objs, slot, other_a=7, other_b=1)
        self.assertEqual([e.message for e in h.export(data, objs, **opts).errors], ["Object '%d - Assault Rifle': other_b must be 0 to 0." % slot])
        # class 12: both 0..31
        slot = by_class[12]
        objs = h.objects_for(model)
        h.change(objs, slot, other_a=31, other_b=31)
        self.assertTrue(h.export(data, objs, **opts).ok)
        h.change(objs, slot, other_a=32)
        self.assertEqual(len(h.export(data, objs, **opts).errors), 1)
        # class 0 / 26: no extras
        slot = by_class[26]
        objs = h.objects_for(model)
        h.change(objs, slot, other_a=1)
        self.assertEqual(h.codes(h.export(data, objs, **opts).errors), ["E_OTHER_RANGE"])

    def test_clips_of_a_weapon_are_written_in_eight_bits(self):
        data = h.g3.data("holes")
        model = h.g3.model("holes")
        slot = [r.slot for r in model.objects() if r.cached_type == 1][0]
        objs = h.objects_for(model)
        h.change(objs, slot, other_a=255)
        result = h.export(data, objs, keep_unrecognised_imported=True)
        self.assertEqual(h.decode(result.data)["slots"][slot]["extra"], [255])


if __name__ == "__main__":
    unittest.main()
