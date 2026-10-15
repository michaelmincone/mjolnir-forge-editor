#!/usr/bin/env python3
"""Build the Blender extension zip of the add-on OUTSIDE the work tree (SPEC 8.10, DEC-8.10).

    /usr/bin/python3 -I tools/build_package.py --out DIR [--allow-placeholders] [--blender BIN]
        [--with-library --i-accept-that-this-copies-game-assets] [--keep-stage]

* ``DIR`` must not be inside the repository (the git top level and the repo folder are both checked); it is
  created when missing. Nothing is ever written into the work tree.
* The add-on is staged (a copy of ``Addon/``) in a temporary folder outside the tree, then
  ``blender --command extension validate`` and ``extension build`` run on the stage (stdin closed; a private
  ``BLENDER_USER_RESOURCES`` so no real profile is touched).
* The DEFAULT package contains NO game asset: ``Resources/Halo Reach.blend`` (Microsoft/343 models) is not
  staged, ``Resources/ForgeBridge.dll`` and ``parse_palette.py`` are never staged, no ``__pycache__``. The
  add-on finds the library, read in place and never copied, through the add-on preference ``Library path``,
  ``$MJOLNIR_LIBRARY`` or (dev loop only) ``<package>/Resources/Halo Reach.blend``.
* ``--with-library`` exists only for the owner's own machine: it also needs
  ``--i-accept-that-this-copies-game-assets``, prints that the output must never be shared, committed or
  uploaded, and is used by no test.
* The build refuses while the manifest still holds ``example.com`` or ``OWNER`` (maintainer / licence not
  filled in) unless ``--allow-placeholders`` is given (tests and the headless suite).
* After the build the zip is inspected: manifest and ``__init__.py`` at the root, no ``.dll``, no
  ``ForgeBridge``, no ``.blend`` (unless ``--with-library``), no ``__pycache__``. Size and SHA-256 are printed.

Exit status: 0 built and verified, 1 refused or failed, 2 usage error.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(REPO, "Addon")
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
NEVER_STAGED = ("Resources/ForgeBridge.dll", "parse_palette.py")
LIBRARY_REL = "Resources/Halo Reach.blend"
PLACEHOLDER_MARKERS = ("example.com", "OWNER")


class BuildError(Exception):
    """The build is refused or failed (exit status 1)."""


def _real(path):
    return os.path.realpath(os.path.expanduser(path))


def git_top_level(start):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
    except OSError:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def is_inside_tree(path):
    """True when ``path`` is inside the repository folder or inside the git top level of the repository."""
    target = _real(path)
    roots = [_real(REPO)]
    top = git_top_level(REPO)
    if top:
        roots.append(_real(top))
    for root in roots:
        if target == root or target.startswith(root + os.sep):
            return True
    return False


def manifest_text(addon_dir):
    with open(os.path.join(addon_dir, "blender_manifest.toml"), "r", encoding="utf-8") as fh:
        return fh.read()


def strip_comments(text):
    lines = []
    for line in text.splitlines():
        lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def placeholders_in(text):
    """Markers of an unfinished manifest found outside comments."""
    code = strip_comments(text)
    return [m for m in PLACEHOLDER_MARKERS if m in code]


def _ignore_factory(with_library):
    def ignore(directory, names):
        rel_dir = os.path.relpath(directory, ADDON_DIR).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        skipped = []
        for name in names:
            rel = rel_dir + name
            if name == "__pycache__" or name.endswith(".pyc") or name == ".DS_Store":
                skipped.append(name)
            elif rel in NEVER_STAGED:
                skipped.append(name)
            elif rel == LIBRARY_REL and not with_library:
                skipped.append(name)
        return skipped
    return ignore


def stage(dest, with_library=False):
    """Copy ``Addon/`` to ``dest`` (which must not exist) without the excluded files."""
    shutil.copytree(ADDON_DIR, dest, ignore=_ignore_factory(with_library))


def run_blender(blender, args, user_resources):
    env = dict(os.environ)
    env["BLENDER_USER_RESOURCES"] = user_resources
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.run([blender, "--command", "extension"] + args, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, universal_newlines=True)
    return proc.returncode, proc.stdout


def inspect_zip(path, with_library):
    """Problems found in the built zip (empty list = clean)."""
    problems = []
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    for required in ("blender_manifest.toml", "__init__.py"):
        if required not in names:
            problems.append("%s is not at the root of the zip" % required)
    for name in names:
        low = name.lower()
        if "__pycache__" in low or low.endswith(".pyc"):
            problems.append("bytecode in the package: %s" % name)
        if low.endswith(".dll") or "forgebridge" in low:
            problems.append("ForgeBridge/DLL in the package: %s" % name)
        if low.endswith(".blend") and not with_library:
            problems.append("game asset (.blend) in the default package: %s" % name)
        if low.endswith((".mvar", ".bin")):
            problems.append("map/game file in the package: %s" % name)
        if low.endswith("parse_palette.py"):
            problems.append("dev tool in the package: %s" % name)
    return problems


def build(out_dir, blender=DEFAULT_BLENDER, allow_placeholders=False, with_library=False, keep_stage=False,
          log=print):
    """Build the extension zip into ``out_dir``; returns the zip path. Raises :class:`BuildError`."""
    if is_inside_tree(out_dir):
        raise BuildError("refusing --out %s: it is inside the repository working tree" % out_dir)
    if not os.path.isfile(blender) or not os.access(blender, os.X_OK):
        raise BuildError("Blender not found: %s (use --blender)" % blender)
    found = placeholders_in(manifest_text(ADDON_DIR))
    if found and not allow_placeholders:
        raise BuildError("the manifest still holds a placeholder (%s): fill maintainer and licence first "
                         "(or pass --allow-placeholders for tests)" % ", ".join(found))
    if found:
        log("build_package: WARNING: placeholders in the manifest (%s), allowed by --allow-placeholders" % ", ".join(found))
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="mjolnir-package-")
    if is_inside_tree(work):
        raise BuildError("the temporary folder %s is inside the repository" % work)
    try:
        stage_dir = os.path.join(work, "stage")
        stage(stage_dir, with_library)
        profile = os.path.join(work, "user_res")
        before = set(os.listdir(out_dir))
        code, text = run_blender(blender, ["validate", stage_dir], profile)
        if code != 0:
            raise BuildError("extension validate failed (exit %d):\n%s" % (code, text[-2000:]))
        code, text = run_blender(blender, ["build", "--source-dir", stage_dir, "--output-dir", out_dir], profile)
        if code != 0:
            raise BuildError("extension build failed (exit %d):\n%s" % (code, text[-2000:]))
        new = sorted(n for n in set(os.listdir(out_dir)) - before if n.endswith(".zip"))
        if not new:                                   # an identical name was overwritten: take the newest zip
            new = sorted((n for n in os.listdir(out_dir) if n.endswith(".zip")),
                         key=lambda n: os.path.getmtime(os.path.join(out_dir, n)))[-1:]
        if not new:
            raise BuildError("the build produced no zip in %s" % out_dir)
        zip_path = os.path.join(out_dir, new[-1])
        problems = inspect_zip(zip_path, with_library)
        if problems:
            raise BuildError("the package is not clean:\n  " + "\n  ".join(problems))
        with open(zip_path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        log("build_package: %s (%d bytes) sha256 %s" % (zip_path, os.path.getsize(zip_path), digest))
        if with_library:
            log("build_package: WARNING: this zip contains Halo Reach.blend (Microsoft/343 assets). Never share, "
                "commit or upload it.")
        return zip_path
    finally:
        if keep_stage:
            log("build_package: stage kept in %s" % work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, metavar="DIR", help="output folder (outside the repository; created if missing)")
    ap.add_argument("--blender", default=os.environ.get("BLENDER", DEFAULT_BLENDER))
    ap.add_argument("--allow-placeholders", action="store_true", help="build although the manifest holds placeholders")
    ap.add_argument("--with-library", action="store_true", help="owner's own machine only: include Halo Reach.blend")
    ap.add_argument("--i-accept-that-this-copies-game-assets", action="store_true", dest="accept_assets")
    ap.add_argument("--keep-stage", action="store_true")
    args = ap.parse_args(argv)
    if args.with_library and not args.accept_assets:
        print("build_package: --with-library also needs --i-accept-that-this-copies-game-assets", file=sys.stderr)
        return 2
    try:
        build(args.out, args.blender, args.allow_placeholders, args.with_library, args.keep_stage)
    except BuildError as exc:
        print("build_package: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
