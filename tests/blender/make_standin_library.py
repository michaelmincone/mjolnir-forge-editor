"""Synthetic stand-in for the object library ``Halo Reach.blend`` (SPEC 9.4, 8.6).

The real library contains Microsoft/343 models and textures and is never copied, re-saved or used by the
default test run. The stand-in has the same collection layout (a ``Props`` scene holding ``Forge World
Palette`` with its groups and one leaf collection per palette entry, and ``Shape Models`` with ``Shape Box``
and ``Shape Cylinder``) but each leaf holds one object that shares a single cube mesh: names only, no game
data. The layout is read from ``Addon/mvarlib/data/palette_tree.json`` (names only, itself generated from
the real library by ``tools/gen_palette_tree.py``).

Two ways to use it:

    blender -b --factory-startup --python tests/blender/make_standin_library.py -- OUT_DIR [TREE_JSON]
        writes OUT_DIR/Halo Reach.blend (OUT_DIR is created; it must be outside the repository)

    from make_standin_library import build            # inside a Blender session
    path = build(out_dir)

Running ``tools/gen_palette_tree.py --library <that file> --out <elsewhere>`` reproduces the tree it was
built from (checked by ``b04_addmenu.py``).
"""
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_TREE = os.path.join(REPO, "Addon", "mvarlib", "data", "palette_tree.json")
LIBRARY_NAME = "Halo Reach.blend"


def _cube_mesh():
    mesh = bpy.data.meshes.new("standin_cube")
    verts = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (0.0, 1.0)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


def _is_inside_repo(path):
    real = os.path.realpath(path)
    root = os.path.realpath(REPO)
    return real == root or real.startswith(root + os.sep)


def build(out_dir, tree_json=DEFAULT_TREE):
    """Write ``out_dir/Halo Reach.blend`` from the tree; returns the path. Refuses a folder inside the repo."""
    if _is_inside_repo(out_dir):
        raise SystemExit("make_standin_library: refusing to write inside the repository: %s" % out_dir)
    with open(tree_json, "r", encoding="utf-8") as fh:
        tree = json.load(fh)
    os.makedirs(out_dir, exist_ok=True)
    # an empty file: no default cube, light or camera
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    scene.name = "Props"
    shared = _cube_mesh()

    def leaf_collection(name, parent):
        coll = bpy.data.collections.new(name)
        parent.children.link(coll)
        obj = bpy.data.objects.new(name, shared)
        coll.objects.link(obj)

    def walk(node, parent):
        for group in node.get("groups", []):
            coll = bpy.data.collections.new(group["name"])
            parent.children.link(coll)
            walk(group, coll)
        for leaf in node.get("leaves", []):
            leaf_collection(leaf["name"] if isinstance(leaf, dict) else leaf, parent)

    palette = bpy.data.collections.new("Forge World Palette")
    scene.collection.children.link(palette)
    walk(tree, palette)
    shapes = bpy.data.collections.new("Shape Models")
    scene.collection.children.link(shapes)
    for name in ("Shape Box", "Shape Cylinder"):
        leaf_collection(name, shapes)
    path = os.path.join(out_dir, LIBRARY_NAME)
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=False, check_existing=False)
    return path


def count_leaves(tree):
    def walk(node):
        return len(node.get("leaves", [])) + sum(walk(g) for g in node.get("groups", []))
    return walk(tree)


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("usage: blender -b --factory-startup --python make_standin_library.py -- OUT_DIR [TREE_JSON]")
    result = build(argv[0], argv[1] if len(argv) > 1 else DEFAULT_TREE)
    print("STANDIN_LIBRARY %s" % result)
