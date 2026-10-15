#!/usr/bin/env python3
"""Generate ``Addon/mvarlib/data/palette_tree.json``: the static palette tree of the Add menu (SPEC 8.6, 8.1).

    /usr/bin/python3 -I tools/gen_palette_tree.py [--library PATH] [--out PATH] [--blender BIN] [--check]
    /usr/bin/python3 -I tools/gen_palette_tree.py --from-raw RAW.json [--out PATH]

The tree holds NAMES ONLY (group names and the display names of the leaves). It is read from the
``Forge World Palette`` collection of an object library (``Halo Reach.blend`` by default) by a
headless Blender, which links that one collection tree READ-ONLY into an empty session and never
saves anything. The library file is only ever opened for reading; the tool hashes it before and
after the Blender run and aborts when the digest differs. Nothing but names reaches the output, so
no game asset is copied (SPEC 0.2). The tree is also what the synthetic stand-in library of the
Blender tests is built from (``tests/blender/make_standin_library.py``), so running this tool on the
stand-in must reproduce the committed file (checked by ``tests/blender/b04_addmenu.py``).

Node format (``tables.py`` documents the part fixed in G0): the top level is
``{"schema", "source", "groups": [node, ...]}``; a node is ``{"name", "groups": [...], "leaves": [...]}``
with empty ``groups`` / ``leaves`` omitted. A leaf is a collection that directly holds objects (one
Forge object type, named like its display name); a group is any other collection with children.
The relative order of groups and leaves inside a node is not kept (the menu draws groups first).

Every leaf name must be a Forge World object (``tables.stock_object_names("Forge World")``): the
tool refuses to write a tree with an unknown name. ``--check`` compares the generated tree with the
committed file and exits 1 when they differ (needs the library, so it is a local check). The output
is ASCII, LF, newline-terminated and deterministic.

Exit status: 0 ok, 1 ``--check`` found a difference, 2 cannot run (missing library or Blender,
Blender failed, unknown leaf name, library changed while it was read).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LIBRARY = os.path.join(REPO, "Addon", "Resources", "Halo Reach.blend")
DEFAULT_OUT = os.path.join(REPO, "Addon", "mvarlib", "data", "palette_tree.json")
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
ROOT_COLLECTION = "Forge World Palette"
SCHEMA = "mvarlib.palette_tree/1"
SOURCE = ("names only; the 'Forge World Palette' collection tree of Halo Reach.blend "
          "(tools/gen_palette_tree.py); leaves are collections that directly hold objects")

# Runs inside Blender (-b --factory-startup --python SCRIPT -- LIBRARY OUT ROOT). Links one collection
# tree read-only into the empty startup session, walks it and writes the raw tree as JSON. It saves
# nothing and touches no other file.
BLENDER_SCRIPT = r'''
import json
import sys

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
library, out, root = args[0], args[1], args[2]
with bpy.data.libraries.load(library, link=True, relative=False) as (data_from, data_to):
    if root not in data_from.collections:
        raise SystemExit("collection %r not found in %s" % (root, library))
    data_to.collections = [root]
top = bpy.data.collections[root]


def walk(coll):
    node = {"name": coll.name, "groups": [], "leaves": []}
    for child in coll.children:
        if len(child.objects) > 0:
            node["leaves"].append(child.name)
        elif len(child.children) > 0:
            node["groups"].append(walk(child))
    return node


with open(out, "w", encoding="utf-8") as fh:
    json.dump(walk(top), fh)
'''


class GenError(Exception):
    """Cannot generate (exit status 2)."""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _node(raw):
    node = {"name": raw["name"]}
    groups = [_node(g) for g in raw.get("groups", [])]
    leaves = list(raw.get("leaves", []))
    if groups:
        node["groups"] = groups
    if leaves:
        node["leaves"] = leaves
    return node


def finalize(raw, known_names):
    """Raw ``{"name", "groups", "leaves"}`` root -> the committed document; refuses unknown leaf names."""
    unknown = []

    def check(node):
        for leaf in node.get("leaves", []):
            if leaf not in known_names:
                unknown.append(leaf)
        for child in node.get("groups", []):
            check(child)

    check(raw)
    if unknown:
        raise GenError("leaf names that are not Forge World objects: %s" % ", ".join(sorted(set(unknown))))
    groups = [_node(g) for g in raw.get("groups", [])]
    if raw.get("leaves"):
        raise GenError("the root collection holds objects directly; expected only groups")
    return {"schema": SCHEMA, "source": SOURCE, "groups": groups}


def render(document):
    """Deterministic ASCII/LF text of the document."""
    return json.dumps(document, indent=1, ensure_ascii=True) + "\n"


def count_leaves(document):
    def walk(node):
        return len(node.get("leaves", [])) + sum(walk(g) for g in node.get("groups", []))
    return sum(walk(g) for g in document["groups"])


def extract_raw(library, blender):
    """Run Blender on ``library`` (read-only) and return the raw tree."""
    if not os.path.isfile(library):
        raise GenError("library not found: %s" % library)
    if not os.path.isfile(blender) or not os.access(blender, os.X_OK):
        raise GenError("Blender not found: %s (set --blender or $BLENDER)" % blender)
    before = sha256_of(library)
    with tempfile.TemporaryDirectory(prefix="mjolnir-palette-") as tmp:
        script = os.path.join(tmp, "dump_tree.py")
        out = os.path.join(tmp, "raw.json")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(BLENDER_SCRIPT)
        env = dict(os.environ)
        env["BLENDER_USER_RESOURCES"] = os.path.join(tmp, "user_res")     # keep the real profile out of it
        proc = subprocess.run(
            [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", script,
             "--", library, out, ROOT_COLLECTION],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
            universal_newlines=True)
        if proc.returncode != 0 or not os.path.isfile(out):
            raise GenError("Blender failed (exit %d):\n%s" % (proc.returncode, proc.stdout[-2000:]))
        with open(out, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    after = sha256_of(library)
    if before != after:
        raise GenError("the library changed while it was read (%s -> %s): refusing" % (before, after))
    return raw


def forge_world_names():
    sys.path.insert(0, os.path.join(REPO, "Addon"))
    try:
        from mvarlib import tables
    finally:
        sys.path.pop(0)
    return set(tables.stock_object_names("Forge World"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--library", default=DEFAULT_LIBRARY, help="object library (read-only); default Halo Reach.blend")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output JSON (default Addon/mvarlib/data/palette_tree.json)")
    ap.add_argument("--blender", default=os.environ.get("BLENDER", DEFAULT_BLENDER))
    ap.add_argument("--from-raw", metavar="RAW.json", help="build from a raw tree dump instead of running Blender")
    ap.add_argument("--check", action="store_true", help="compare with the committed file, write nothing")
    args = ap.parse_args(argv)
    try:
        if args.from_raw:
            with open(args.from_raw, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        else:
            raw = extract_raw(args.library, args.blender)
        document = finalize(raw, forge_world_names())
    except (GenError, OSError, ValueError) as exc:
        print("gen_palette_tree: %s" % exc, file=sys.stderr)
        return 2
    text = render(document)
    if args.check:
        try:
            with open(args.out, "r", encoding="utf-8") as fh:
                current = fh.read()
        except OSError as exc:
            print("gen_palette_tree: cannot read %s: %s" % (args.out, exc), file=sys.stderr)
            return 2
        if current != text:
            print("gen_palette_tree: %s differs from the generated tree" % args.out, file=sys.stderr)
            return 1
        print("gen_palette_tree: %s is up to date (%d leaves)" % (args.out, count_leaves(document)))
        return 0
    with open(args.out, "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)
    print("gen_palette_tree: wrote %s (%d groups at the top, %d leaves)" % (args.out, len(document["groups"]),
                                                                          count_leaves(document)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
