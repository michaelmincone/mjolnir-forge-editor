"""Helper of the Blender test ``s1``: a synthetic stand-in library whose ``Block, 1x1`` is NOT a unit cube.

The plain stand-in library (``make_standin_library.py``) gives every palette entry the same 1 x 1 x 1 cube, so a star tool that
ignored the measured mesh box and spaced its blocks by 1.0 would still pass every test. The REAL library's ``Block, 1x1`` is
1.0182 x 1.0182 x 1.0 (measured read-only); this helper builds the stand-in with that box (origin at the bottom centre, like
the other stand-in objects) so the spacing requirement is pinned end to end. Names and boxes only, no game data.

    blender -b --factory-startup --python tests/blender/s1_make_odd_library.py -- OUT_DIR

writes ``OUT_DIR/Halo Reach.blend`` (OUT_DIR must be outside the repository) and prints ``ODD_LIBRARY <path>``.
"""
import os
import sys

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_standin_library  # noqa: E402

ODD_SIZE = (1.0182, 1.0182, 1.0)                # width (X), depth (Y), height (Z) of "Block, 1x1" in the real library
BLOCK = "Block, 1x1"


def build(out_dir):
    path = make_standin_library.build(out_dir)
    collection = bpy.data.collections[BLOCK]
    objects = list(collection.objects)
    if len(objects) != 1:
        raise SystemExit("s1_make_odd_library: expected one object in %r, found %d" % (BLOCK, len(objects)))
    width, depth, height = ODD_SIZE
    mesh = bpy.data.meshes.new("standin_odd_block")
    verts = [(x * width / 2.0, y * depth / 2.0, z * height) for x in (-1, 1) for y in (-1, 1) for z in (0, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    objects[0].data = mesh                       # the other entries keep the shared unit cube
    bpy.ops.wm.save_as_mainfile(filepath=path, compress=False, check_existing=False)
    return path


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(argv) != 1:
        raise SystemExit("usage: blender -b --factory-startup --python s1_make_odd_library.py -- OUT_DIR")
    print("ODD_LIBRARY %s" % build(argv[0]))
