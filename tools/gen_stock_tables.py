#!/usr/bin/env python3
"""Generate the stock-map and stock-object tables of ``mvarlib`` (SPEC 6.7, 7.1, DEC-7.1).

    python3 -I tools/gen_stock_tables.py             # (re)write the two data files
    python3 -I tools/gen_stock_tables.py --check     # exit 1 if the committed files differ
    python3 -I tools/gen_stock_tables.py --cross-check RESEARCH_TABLES_DIR [--rvt-source page_map_perms.cpp]

Outputs (Addon/mvarlib/data/):
  maps.json           the 20 stock Halo: Reach maps: id, name, source
  stock_objects.json  per map: [type_id, internal_type, display_name]; plus "disputed" ids

Inputs, all inside the repository so the run is reproducible without the research folder:
  * ``Addon/objects.py`` (``map_object_types`` + ``type_to_name``), parsed with ``ast`` and never
    executed (it imports a sibling module by a bare name and prints on import);
  * the literal map list below, copied from ReachVariantTool ``page_map_perms.cpp:15-58``;
  * the literal ``DISPUTED`` table (the 8 ids on which ``ItemParser.cs`` and ``objects.py``
    genuinely disagree, SPEC 7.1 / X18).

``--cross-check DIR`` additionally proves that the output is equal in content to the research
tables ``stock_objects_per_map_with_model_flag.json`` and ``objects_py_tables.json`` (and that the
disputed ids appear in ``itemparser_cs_vs_objects_py.json``); ``--rvt-source`` proves the embedded
map list against the C++ file. The files contain names, ids and flags only: no mesh, texture or
any other game asset.

Deterministic: fixed key order, one entry per line, ASCII-escaped JSON, LF line endings,
byte-identical on every run and on Python 3.9 to 3.13. Writes go through ``mvarlib.io.write_atomic``.
Exit codes: 0 ok, 1 differs / cross-check failed, 2 cannot run.
"""
import argparse
import ast
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "Addon"))

OBJECTS_PY = os.path.join(REPO, "Addon", "objects.py")
DATA_DIR = os.path.join(REPO, "Addon", "mvarlib", "data")

MAPS_SOURCE = "ReachVariantTool native/src/ReachVariantTool/ui/script_editor/page_map_perms.cpp:15-58"
MAP_ENTRY_SOURCE = "RVT page_map_perms.cpp:15-58"
OBJECTS_SOURCE = "Addon/objects.py (map_object_types + type_to_name), parsed with ast"

# The 20 stock maps: (id, name), ascending by id. Copied from page_map_perms.cpp:15-58 (SPEC 7.1).
STOCK_MAPS = [
    (1000, "Sword Base"), (1020, "Countdown"), (1035, "Boardwalk"), (1040, "Zealot"),
    (1055, "Powerhouse"), (1080, "Boneyard"), (1150, "Reflection"), (1200, "Spire"),
    (1500, "Condemned"), (1510, "Highlands"), (2001, "Anchor 9"), (2002, "Breakpoint"),
    (2004, "Tempest"), (3006, "Forge World"), (10010, "Penance"), (10020, "Battle Canyon"),
    (10030, "Ridgeline"), (10050, "Breakneck"), (10060, "High Noon"), (10070, "Solitary"),
]

# Ids RVT lists that are NOT stock for this tool (SPEC 7.1): placeholders and unused DLC slots.
NOT_STOCK_IDS = [
    (1, "Unknown 1 (RVT placeholder)"),
    (1001, "Unused (DLC Sword Base)"),
    (1056, "Unused (DLC Powerhouse)"),
]

# Ids on which ItemParser.cs and objects.py disagree about WHICH object the id is (SPEC 7.1, X18):
# Tempest 0x2800-0x2802 vs 0x6100-0x6102 (Forerunner and plain Man Cannons swapped) and
# Breakneck 0x2203/0x2204 (Man Cannon and Vehicle Cannon swapped). The 36 other differences between
# the two upstream tables are spelling and are not disputed.
DISPUTED = {
    "Breakneck": [0x2203, 0x2204],
    "Tempest": [0x2800, 0x2801, 0x2802, 0x6100, 0x6101, 0x6102],
}


class GenError(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# Reading Addon/objects.py without executing it
# ---------------------------------------------------------------------------------------------
def _twoway_literal(node, what):
    """``TwoWayDict({...})`` -> dict, rejecting duplicate keys (a repeated key would silently win)."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "TwoWayDict" and len(node.args) == 1 and not node.keywords):
        raise GenError("%s: expected TwoWayDict({...})" % what)
    arg = node.args[0]
    if not isinstance(arg, ast.Dict):
        raise GenError("%s: TwoWayDict argument is not a dict literal" % what)
    keys = [ast.literal_eval(k) for k in arg.keys]
    if len(set(keys)) != len(keys):
        dup = sorted(set(k for k in keys if keys.count(k) > 1), key=str)
        raise GenError("%s: duplicate keys %r" % (what, dup))
    return dict(zip(keys, (ast.literal_eval(v) for v in arg.values))), keys


def parse_objects_py(path=OBJECTS_PY):
    """Return ``(map_object_types, type_to_name)`` as plain dicts, preserving the file order.

    ``map_object_types``: {map name: [(type_id, internal_type), ...]} in file order.
    """
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("map_object_types", "type_to_name")):
            found[node.targets[0].id] = node.value
    if set(found) != {"map_object_types", "type_to_name"}:
        raise GenError("%s: map_object_types / type_to_name assignments not found" % path)
    top = found["map_object_types"]
    if not isinstance(top, ast.Dict):
        raise GenError("map_object_types is not a dict literal")
    map_names = [ast.literal_eval(k) for k in top.keys]
    if len(set(map_names)) != len(map_names):
        raise GenError("map_object_types: duplicate map names")
    maps = {}
    for name, value in zip(map_names, top.values):
        table, order = _twoway_literal(value, "map_object_types[%r]" % name)
        maps[name] = [(k, table[k]) for k in order]
    names, _ = _twoway_literal(found["type_to_name"], "type_to_name")
    return maps, names


# ---------------------------------------------------------------------------------------------
# Building the outputs
# ---------------------------------------------------------------------------------------------
def _j(value):
    return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))


def build_tables(objects_py=OBJECTS_PY):
    """Validate and return ``(maps, objects)``.

    maps:    [{"id", "name", "source"}] ascending by id
    objects: {map name: [(type_id, internal_type, display_name)]} ascending by id, in objects.py map order
    """
    raw_maps, type_to_name = parse_objects_py(objects_py)
    stock_names = [n for _, n in STOCK_MAPS]
    if sorted(stock_names) != sorted(raw_maps):
        raise GenError("map names differ: RVT list %r vs objects.py %r"
                       % (sorted(set(stock_names) ^ set(raw_maps)), sorted(raw_maps)))
    if len(set(i for i, _ in STOCK_MAPS)) != len(STOCK_MAPS):
        raise GenError("duplicate stock map id")

    objects = {}
    for map_name in raw_maps:
        rows = []
        for type_id, internal in sorted(raw_maps[map_name]):
            if not (isinstance(type_id, int) and 0 <= type_id <= 0xFFFF):
                raise GenError("%s: bad type id %r" % (map_name, type_id))
            # folder is 8 bits, item is 5 bits (SPEC 0.3 / 3.6)
            if (type_id & 0xFF) > 31:
                raise GenError("%s: id 0x%04X has item %d, which does not fit 5 bits" % (map_name, type_id, type_id & 0xFF))
            display = type_to_name.get(internal)
            if display is None:
                sys.stderr.write("gen_stock_tables: %s id 0x%04X (%s) has no display name; using the internal name\n"
                                 % (map_name, type_id, internal))
                display = internal
            rows.append((type_id, internal, display))
        dups = sorted(set(d for _, _, d in rows if [r[2] for r in rows].count(d) > 1))
        if dups:
            raise GenError("%s: display names are not unique on this map: %r" % (map_name, dups))
        objects[map_name] = rows

    for map_name, ids in DISPUTED.items():
        have = set(r[0] for r in objects.get(map_name, []))
        missing = [i for i in ids if i not in have]
        if missing:
            raise GenError("disputed ids %r are not in the %s table" % (["0x%04X" % i for i in missing], map_name))

    maps = [{"id": i, "name": n, "source": MAP_ENTRY_SOURCE} for i, n in sorted(STOCK_MAPS)]
    return maps, objects


def render_maps(maps):
    lines = ["{",
             ' "schema": "mvarlib.maps/1",',
             ' "source": %s,' % _j(MAPS_SOURCE + "; names must equal the map keys of Addon/objects.py"),
             ' "maps": [']
    for i, m in enumerate(maps):
        lines.append("  %s%s" % (_j(m), "," if i + 1 < len(maps) else ""))
    lines.append(" ],")
    lines.append(' "not_stock_ids": [')
    for i, (map_id, note) in enumerate(NOT_STOCK_IDS):
        lines.append("  %s%s" % (_j({"id": map_id, "note": note}), "," if i + 1 < len(NOT_STOCK_IDS) else ""))
    lines.append(" ]")
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def render_objects(objects):
    lines = ["{",
             ' "schema": "mvarlib.stock_objects/1",',
             ' "source": %s,' % _j(OBJECTS_SOURCE),
             ' "entry": ["type_id", "internal_type", "display_name"],',
             ' "maps": {']
    names = list(objects)
    for mi, map_name in enumerate(names):
        rows = objects[map_name]
        lines.append("  %s: [" % _j(map_name))
        for ri, row in enumerate(rows):
            lines.append("   %s%s" % (_j(list(row)), "," if ri + 1 < len(rows) else ""))
        lines.append("  ]%s" % ("," if mi + 1 < len(names) else ""))
    lines.append(" },")
    lines.append(' "disputed": {')
    keys = sorted(DISPUTED)
    for ki, key in enumerate(keys):
        lines.append("  %s: %s%s" % (_j(key), _j(sorted(DISPUTED[key])), "," if ki + 1 < len(keys) else ""))
    lines.append(" }")
    lines.append("}")
    return ("\n".join(lines) + "\n").encode("ascii")


def build_outputs(objects_py=OBJECTS_PY):
    """Return ``{file name: bytes}`` for the two data files (pure; used by the sync test U-15)."""
    maps, objects = build_tables(objects_py)
    return {"maps.json": render_maps(maps), "stock_objects.json": render_objects(objects)}


# ---------------------------------------------------------------------------------------------
# Cross-checks against the research tables and the RVT source
# ---------------------------------------------------------------------------------------------
def cross_check_research(tables_dir, objects_py=OBJECTS_PY):
    """Return a list of mismatch descriptions (empty = equal in content)."""
    problems = []
    _, objects = build_tables(objects_py)

    def load(name):
        with open(os.path.join(tables_dir, name), "r", encoding="utf-8") as fh:
            return json.load(fh)

    per_map = load("stock_objects_per_map_with_model_flag.json")
    if list(per_map) != list(objects):
        problems.append("map list/order differs: %r vs %r" % (list(per_map), list(objects)))
    for map_name, rows in objects.items():
        theirs = [(r["id"], r["internal_type"], r["display_name"]) for r in per_map.get(map_name, [])]
        if theirs != rows:
            problems.append("%s: stock_objects_per_map_with_model_flag.json differs (%d vs %d rows)"
                            % (map_name, len(theirs), len(rows)))
    py_tables = load("objects_py_tables.json")
    for map_name, rows in objects.items():
        theirs = py_tables["map_object_types"].get(map_name, {})
        mine = dict((str(t), i) for t, i, _ in rows)
        if theirs != mine:
            problems.append("%s: objects_py_tables.json map_object_types differs" % map_name)
        for _, internal, display in rows:
            if py_tables["type_to_name"].get(internal, internal) != display:
                problems.append("%s: display name of %s differs from objects_py_tables.json" % (map_name, internal))
    cs = load("itemparser_cs_vs_objects_py.json")
    for map_name, ids in DISPUTED.items():
        listed = set(r[0] for r in cs.get(map_name, {}).get("different_name_at_same_id", []))
        for i in ids:
            if i not in listed:
                problems.append("%s: disputed id 0x%04X is not a difference in itemparser_cs_vs_objects_py.json" % (map_name, i))
    return problems


def parse_rvt_maps(cpp_path):
    """Stock map ids and names from page_map_perms.cpp (commented-out blocks removed)."""
    with open(cpp_path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    found = []
    for m in re.finditer(r'_MapID\((\d+),\s*QObject::tr\("([^"]+)"', text):
        found.append((int(m.group(1)), m.group(2)))
    return found


def cross_check_rvt(cpp_path):
    problems = []
    found = parse_rvt_maps(cpp_path)
    stock = sorted((i, n) for i, n in found if not n.startswith("Unused"))
    if stock != sorted(STOCK_MAPS):
        problems.append("embedded STOCK_MAPS differs from %s" % cpp_path)
    unused = sorted(i for i, n in found if n.startswith("Unused"))
    if unused != sorted(i for i, _ in NOT_STOCK_IDS if i != 1):
        problems.append("embedded NOT_STOCK_IDS differs from the 'Unused' entries of %s" % cpp_path)
    return problems


# ---------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if the committed files differ")
    ap.add_argument("--objects-py", default=OBJECTS_PY)
    ap.add_argument("--out-dir", default=DATA_DIR)
    ap.add_argument("--cross-check", metavar="TABLES_DIR", help="research/tables directory to compare against")
    ap.add_argument("--rvt-source", metavar="CPP", help="page_map_perms.cpp to compare the embedded map list against")
    args = ap.parse_args(argv)
    try:
        outputs = build_outputs(args.objects_py)
    except (GenError, OSError, SyntaxError, ValueError) as exc:
        print("gen_stock_tables: cannot generate: %s" % exc, file=sys.stderr)
        return 2

    status = 0
    if args.cross_check or args.rvt_source:
        problems = []
        try:
            if args.cross_check:
                problems += cross_check_research(args.cross_check, args.objects_py)
            if args.rvt_source:
                problems += cross_check_rvt(args.rvt_source)
        except (OSError, ValueError, KeyError) as exc:
            print("gen_stock_tables: cannot cross-check: %s" % exc, file=sys.stderr)
            return 2
        for p in problems:
            print("CROSS-CHECK MISMATCH: " + p)
        if problems:
            return 1
        print("gen_stock_tables: cross-check ok (output is equal in content to the given sources)")

    if args.check:
        for name, data in sorted(outputs.items()):
            path = os.path.join(args.out_dir, name)
            try:
                with open(path, "rb") as fh:
                    current = fh.read()
            except OSError:
                current = None
            if current != data:
                print("gen_stock_tables: %s differs from the generated output" % path)
                status = 1
        if status == 0:
            print("gen_stock_tables: committed tables are up to date")
        return status

    import mvarlib.io as mio
    for name, data in sorted(outputs.items()):
        path = os.path.join(args.out_dir, name)
        mio.write_atomic(path, data, source_paths=[args.objects_py])
        print("gen_stock_tables: wrote %s (%d bytes)" % (path, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
