"""B-20 (SPEC 9.4, 8.10, gate G6): the INSTALLED extension works: relative imports, data files, no ``sys.path`` hack.

Independently of how the suite itself was started (dev loop or installed), this test

1. builds the DEFAULT package (no game asset inside) with ``tools/build_package.py --allow-placeholders`` into a scratch
   folder outside the repository, inspects the zip (manifest and ``__init__.py`` at the root, the data files, no ``.blend``,
   ``.dll``, ``.mvar``, ``.bin``, ``parse_palette.py`` or bytecode),
2. installs it with ``blender --command extension install-file -r user_default`` into a BRAND NEW isolated profile,
3. starts a child Blender on that profile with the add-on enabled at startup and runs, with the real provider,
   * the real-provider variants of B-02 and B-18 through ``run_all.py --only b02 b18`` (import W1, the golden edits
     E1/E2/E2b/E3 byte for byte), with ``$MJOLNIR_LIBRARY`` removed from the environment, and
   * this file's own ``--child`` checks: the module lives in the profile's ``extensions/user_default`` folder, no ``Addon``
     folder of the repository is on ``sys.path``, the active provider is the extension's own ``mvarlib.api``, the data
     files (stock tables, palette tree) are read from the installed copy, the package holds no ``Halo Reach.blend`` and no
     ``ForgeBridge.dll``, and the object library is found through the ADD-ON PREFERENCE ``Library path`` (set after
     ``addon_utils.enable(..., default_set=True, persistent=True)``, because an add-on enabled by ``--addons`` has no
     entry in ``bpy.context.preferences.addons``): the stand-in is linked in place from the preference path.
"""
import json
import os
import subprocess
import sys
import zipfile

import bpy

sys.dont_write_bytecode = True                 # keep __pycache__ out of the work tree
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bl_common  # noqa: E402
import real_data as rd  # noqa: E402
from bl_common import check, check_eq  # noqa: E402

ID = "b20"
TITLE = "the installed extension (default package, library through the preference) runs B-02 and B-18"
NEEDS_STUB = False
REAL_ONLY = True

PY39 = "/usr/bin/python3"
EXTENSION_ID = "bl_ext.user_default.mjolnir_forge"
FORBIDDEN_SUFFIXES = (".blend", ".dll", ".mvar", ".bin", ".pyc", ".mglo")
FORBIDDEN_NAMES = ("parse_palette.py", "ForgeBridge.dll", "Halo Reach.blend")


def run_logged(cmd, env, label, tmp):
    log = os.path.join(tmp, label + ".log")
    proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                          env=env)
    with open(log, "w") as fh:
        fh.write(proc.stdout)
    return proc.returncode, proc.stdout


def inspect_zip(path):
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    check("blender_manifest.toml" in names and "__init__.py" in names, "manifest and __init__.py at the root: %s" % names[:8])
    for needed in ("mjolnir.py", "io_ops.py", "palette.py", "state.py", "provider.py", "mvarlib/api.py", "mvarlib/entry.py",
                   "mvarlib/data/stock_objects.json", "mvarlib/data/maps.json", "mvarlib/data/palette_tree.json"):
        check(needed in names, "%s is in the package" % needed)
    for name in names:
        base = os.path.basename(name)
        check(not name.lower().endswith(FORBIDDEN_SUFFIXES), "no game asset or bytecode in the package: %s" % name)
        check(base not in FORBIDDEN_NAMES and "__pycache__" not in name, "not packaged: %s" % name)
    return names


def run_real(env):
    py39 = PY39 if os.path.exists(PY39) else None
    if py39 is None:
        raise bl_common.Skip("%s is missing: the package cannot be built" % PY39)
    scratch = os.path.join(env.tmp, "b20")
    dist = os.path.join(scratch, "dist")
    profile = os.path.join(scratch, "user_res")
    os.makedirs(dist)
    os.makedirs(profile)
    base_env = dict(os.environ)
    for key in ("MJOLNIR_LIBRARY", bl_common.ENV_ADDON, "BLENDER_USER_RESOURCES", "PYTHONPATH"):
        base_env.pop(key, None)
    base_env["PYTHONUNBUFFERED"] = "1"

    # 1. build the default package outside the repository
    code, out = run_logged([py39, "-I", os.path.join(bl_common.REPO, "tools", "build_package.py"), "--out", dist,
                            "--allow-placeholders", "--blender", bpy.app.binary_path], base_env, "build", scratch)
    check_eq(code, 0, "build_package.py exit status; output:\n" + out[-3000:])
    zips = [n for n in os.listdir(dist) if n.endswith(".zip")]
    check_eq(len(zips), 1, "one zip was built: %s" % zips)
    zip_path = os.path.join(dist, zips[0])
    names = inspect_zip(zip_path)

    # 2. install it into a fresh profile
    profile_env = dict(base_env)
    profile_env["BLENDER_USER_RESOURCES"] = profile
    code, out = run_logged([bpy.app.binary_path, "--command", "extension", "install-file", "-r", "user_default", zip_path], profile_env,
                           "install", scratch)
    check_eq(code, 0, "extension install-file exit status; output:\n" + out[-3000:])
    installed = os.path.join(profile, "extensions", "user_default", "mjolnir_forge")
    check(os.path.isfile(os.path.join(installed, "__init__.py")), "installed at %s" % installed)
    check(not os.path.exists(os.path.join(installed, "Resources", "Halo Reach.blend")), "the installed package carries no object library")
    check(not os.path.exists(os.path.join(installed, "Resources", "ForgeBridge.dll")), "and no DLL")

    # 3a. B-02 and B-18 in the installed extension (no library variable: the tests set what they need themselves)
    code, out = run_logged([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--addons", EXTENSION_ID,
                            "--python", os.path.join(bl_common.HERE, "run_all.py"), "--", "--provider", "real", "--only", "b02", "b18"],
                           profile_env, "run_all", scratch)
    check_eq(code, 0, "B-02 and B-18 in the installed extension; output:\n" + out[-6000:])
    check("PASS b02" in out and "PASS b18" in out and "run_all: RESULT: PASSED" in out, out[-3000:])

    # 3b. the layout and preference checks
    result_json = os.path.join(scratch, "child.json")
    standin_dir = os.path.dirname(env.standin_library())
    code, out = run_logged([bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--addons", EXTENSION_ID,
                            "--python", os.path.abspath(__file__), "--", "--child", result_json, profile, standin_dir, scratch],
                           profile_env, "child", scratch)
    check_eq(code, 0, "child checks in the installed extension; output:\n" + out[-6000:])
    with open(result_json) as fh:
        report = json.load(fh)
    check_eq(report["problems"], [], "child problems")
    print("B-20 the default package (%d files, no game asset) installed into a fresh profile; B-02 and B-18 passed there; library through the "
          "preference: %s" % (len(names), report["library"]))


def child():
    """Runs inside the Blender that has the INSTALLED extension enabled at startup."""
    argv = sys.argv[sys.argv.index("--") + 1:]
    result_json, profile, standin_dir, scratch = argv[1], argv[2], argv[3], argv[4]
    problems = []

    def expect(cond, message="a check failed"):
        if not cond:
            problems.append(message)

    import addon_utils
    import importlib
    # nothing of the repository is on sys.path yet (this runs before anything of bl_common's Env is created)
    expect(not any(os.path.normpath(p).endswith(os.path.join("Mjolnir-Forge-Editor", "Addon")) for p in sys.path),
           "the repository's Addon folder is on sys.path")
    mod = importlib.import_module(EXTENSION_ID)
    package_dir = os.path.dirname(os.path.abspath(mod.__file__))
    expect(os.path.realpath(package_dir).startswith(os.path.realpath(profile)), "the add-on is not loaded from the profile: %s" % package_dir)
    expect(os.path.isfile(os.path.join(package_dir, "mvarlib", "data", "stock_objects.json")), "data files are in the package")
    expect(not os.path.exists(os.path.join(package_dir, "Resources", "Halo Reach.blend")), "no library in the package")
    provider = importlib.import_module(EXTENSION_ID + ".provider")
    P = provider.get_provider()
    expect(P.__name__ == EXTENSION_ID + ".mvarlib.api", "the provider is not the extension's own api: %r" % P.__name__)
    expect(len(P.stock_object_names("Forge World")) == 348, "stock table read from the installed data files")
    expect(len(P.stock_object_names("Breakneck")) == 218, "the Breakneck stock table")
    expect(P.map_name_for_id(10050) == "Breakneck", "the map table")
    palette = importlib.import_module(EXTENSION_ID + ".palette")
    expect(os.environ.get("MJOLNIR_LIBRARY") is None, "the environment variable must be absent in this child")
    expect(not os.path.isfile(palette.library_path()), "without a preference the library is not found: %s" % palette.library_path())

    # the preference: enable (default_set, persistent) first, then set the library path
    addon_utils.enable(EXTENSION_ID, default_set=True, persistent=True)
    entry = bpy.context.preferences.addons.get(EXTENSION_ID)
    expect(entry is not None, "the add-on has no preferences entry after addon_utils.enable")
    library_report = ""
    if entry is not None:
        entry.preferences.library_path = standin_dir
        expect(palette.library_path() == os.path.join(standin_dir, "Halo Reach.blend"), "preference: %r" % palette.library_path())
        w1 = rd.fixture("w1_minimal")
        source = os.path.join(scratch, "child_w1.mvar")
        with open(source, "wb") as fh:
            fh.write(w1)
        try:
            result = bpy.ops.import_scene.mjolnir_mvar(filepath=source)
            expect(result == {'FINISHED'}, "import: %r" % (result,))
            objs = sorted((o for o in bpy.context.scene.objects if o.get("isForgeObject")), key=lambda o: o["mj_slot"])
            expect([o["mj_slot"] for o in objs] == [1, 5, 650], "objects: %r" % [o.name for o in objs])
            block = objs[0]
            lib = block.instance_collection.library if block.instance_collection is not None else None
            expect(lib is not None, "the block is not the linked model: the preference path was not used")
            if lib is not None:
                linked = os.path.realpath(bpy.path.abspath(lib.filepath))
                expect(linked == os.path.realpath(os.path.join(standin_dir, "Halo Reach.blend")), "linked from %s" % linked)
                library_report = linked
            block.location.x += 1.0
            bpy.context.view_layer.update()
            target = os.path.join(scratch, "child_e1.mvar")
            result = bpy.ops.export_scene.mjolnir_mvar(filepath=target)
            expect(result == {'FINISHED'}, "export: %r" % (result,))
            expect(rd.read_bytes(target) == rd.fixture("w1_E1"), "the installed extension exported W1 + E1 differently from the golden file")
        except Exception as exc:                       # reported, never a traceback that hides the other findings
            problems.append("%s: %s" % (type(exc).__name__, exc))
    with open(result_json, "w") as fh:
        json.dump({"problems": problems, "library": library_report}, fh)


if __name__ == "__main__":
    if "--child" in sys.argv:
        child()
    else:
        bl_common.main_module(sys.modules[__name__])
