"""Build a block star on a Halo: Reach map variant with the Blender add-on, headless (S1 preparation, NOTES.md D10 / D10a).

Run it inside Blender with the add-on enabled at startup (``tools/run_star_build.sh`` does the set-up for you)::

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python-exit-code 1 \\
        --addons <add-on module> --python tools/build_star_mvar.py -- \\
        --template <the map variant to start from> --out <the new map variant> \\
        [--block auto|<display name>] [--cells N|auto] [--provider stub|real] [--real-library] [--dry-run] [--help for the rest]

What it does, in this order, using only the add-on's OWN operators and checks (nothing is bypassed):

1. refuses an output path inside this repository, inside a sample folder, beside the template, equal to the template,
   or already in use;
2. imports the template with ``import_scene.mjolnir_mvar``;
3. picks the block type: one that the template already contains (so the library can learn its object class and flags
   from a real object, SPEC 5.6 / 7.4), else a stock block of the map with a loud warning; measures the block's
   mesh box in the object library to get the spacing;
4. lays out an upright five-pointed pixel-art star (``tools/star_layout.py``) centred in the map bounds, on the largest
   grid that fits the free object slots of the template (``--cells auto``, the default);
5. checks the 650-object limit, the stock rule and the bounds, then adds the blocks with ``forge.add_object``, sets
   their physics to Fixed (the only placement bit that may be edited, SPEC 3.9) and exports with
   ``export_scene.mjolnir_mvar``: the library's own validation (stock objects, quota maximum, bounds, capacity,
   rotation gate) decides, and a refusal writes no file;
6. re-reads the output and verifies it independently (the star's block count, every position within the
   quantisation tolerance, every original object bit-identical, the bytes outside the bit stream, the hash recipe);
7. prints a report and exits non-zero on any failure (0 built and verified, 1 failed, 2 refused before anything was
   written). A file that fails verification is renamed ``*.REJECTED``. ``--dry-run`` does all of it and keeps nothing.

It never writes inside the repository (not even bytecode) or beside the template, never changes the template or the
object library, and never saves a ``.blend``. The object library is whatever the add-on resolves (``palette.library_path()``:
the add-on preference 'Library path', else ``$MJOLNIR_LIBRARY``, else ``<add-on>/Resources``); the real
``Halo Reach.blend`` of this checkout is linked only with ``--real-library`` and the script refuses when the add-on would
use another library than the options promise. The result is UNVERIFIED IN GAME: nobody has loaded it in MCC (see
``docs/mvar/STAR_BUILD.md``).

The pure parts (argument parsing, path policy, block ranking, container and hash checks, record verification) import
no ``bpy`` and are unit-tested on Python 3.9 and 3.13 (``tests/unit/test_star_build_tool.py``); the Blender part is
tested by ``tests/blender/s1_star_stub.py``.
"""
import argparse
import hashlib
import importlib
import math
import os
import re
import struct
import sys
import tempfile
import time

sys.dont_write_bytecode = True     # "never writes inside the repository": no __pycache__ for star_layout (the wrapper scripts
                                   # export PYTHONDONTWRITEBYTECODE=1 for the add-on, which is imported before this script runs)
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import star_layout as sl  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1                    # ran, but something went wrong or a check failed
EXIT_REFUSED = 2                   # refused before anything was written (bad request, over the limits, bad path)

MAX_OBJECTS = 650
MAX_TEMPLATE_BYTES = 1 << 20       # the import operator's own limit
BLOCK_GROUP = "Building Blocks"
COLLECTION_NAME = "Forge Star"
BLOCK_PREFIX = "Star "
MAX_ATTEMPTS = 6                   # block types tried in auto mode before giving up
ASPECT_OK = 0.15                   # |ln(width / height)| of a block that makes a good-looking star
PROVIDERS = ("real", "stub", "stub-roundtrip")
COLOR_CHOICES = ("KEEP", "TEAM_COLOR", "RED", "BLUE", "GREEN", "ORANGE", "PURPLE", "YELLOW", "BROWN", "PINK")
LIBRARY_RELATIVE = os.path.join("Addon", "Resources", "Halo Reach.blend")
SAMPLE_FOLDERS = (                 # mirrors mvarlib.io.DEFAULT_PROTECTED plus the real map variant folder
    "~/Local_Documents/Halo-MCC/variant-tool/test-samples",
    "~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library",
    "~/Local_Documents/Halo-MCC/forge/real-mvar-samples",
)
# refusals of the library that depend on WHICH block type was chosen: another type may pass (auto mode tries the next)
TYPE_SPECIFIC_CODES = frozenset(["E_QUOTA", "E_QUOTA_MIN", "E_QUOTA_RANGE", "E_FLAG_UNVERIFIED", "E_CACHED_TYPE_UNKNOWN",
                                 "E_OBJ_NAME_UNKNOWN", "E_OBJ_NOT_STOCK", "E_FOLDER_RANGE", "E_TYPE19_UNDETERMINED"])
HINTS = {
    "E_ROTATION_GATED": "Adding objects writes a rotation, which is gated (SPEC 5.6). Do not pass --no-rotation-gate.",
    "E_OBJ_NOT_STOCK": "An object that is already in the template is not in this tool's stock table for the map. If you "
                       "accept that (the table was never checked against a real file), run again with --keep-unrecognised: "
                       "those objects are then kept exactly as they were.",
    "E_QUOTA": "The map allows only so many of that block type. Pick another one with --block, or use a smaller --cells.",
    "E_FLAG_UNVERIFIED": "The block's flags differ from the example in the template. Pick another block type with --block.",
    "E_CACHED_TYPE_UNKNOWN": "The object class of this block type cannot be learned from the template, and its palette group "
                             "is not one the library may assume (SPEC 7.4). Use a block type the template already contains "
                             "(--block; the list above says which), or place one block of the kind you want on the map in the "
                             "game, save it, and use that file as the template.",
    "E_TOO_MANY": "Use a smaller --cells or --outline.",
    "E_NO_FREE_SLOT": "Use a smaller --cells or --outline.",
    "E_CAPACITY": "The file would be too big. Use a smaller --cells or --outline.",
    "E_OUT_OF_BOUNDS": "Choose a --center inside the map bounds, or a smaller --cells.",
    "E_PATH_SAME_AS_SOURCE": "Choose a different --out.",
    "E_PATH_PROTECTED": "Choose a different --out.",
}
CAVEATS = (
    "UNVERIFIED IN GAME: adding objects is the least verified edit of the whole port (SPEC 5.6, 10); nobody has loaded this "
    "file in MCC. Treat it as a candidate and follow the test ladder in NOTES.md / docs/mvar/STAR_BUILD.md.",
    "Xbox / Halo Waypoint route UNVERIFIED: how an .mvar reaches an Xbox (believed: MCC on a PC, then save or share it to "
    "Waypoint, then download on the console) has not been tested; whether the service or the console checks the SHA-1 or a "
    "signature (_fsm) is unknown.",
    "Budget NOT recomputable offline: item prices are not in the file, so the spent-budget word was copied unchanged. Open "
    "the map in Forge and read the budget meter before relying on it.",
    "Orientation convention UNVERIFIED (SPEC 4.6 to 4.8): blocks are written as pure yaw 0; a block that is not square in "
    "plan could end up turned by a quarter turn if the convention is wrong.",
)


class StarBuildError(Exception):
    """A planned stop. ``kind`` is ``'refused'`` (nothing was written, the request cannot be met) or ``'failed'``."""

    def __init__(self, message, kind="refused"):
        super().__init__(message)
        self.kind = kind


# --- options -----------------------------------------------------------------------------------------
class Options(object):
    """Everything the script takes (also what the tests pass in-process)."""

    def __init__(self, **kwargs):
        self.template = None
        self.out = None
        self.block = "auto"
        self.cells = None                      # grid size N (the star is drawn on N x N cells); None = auto
        self.shape = None                      # name of a fixed design of star_layout.NAMED_SHAPES (instead of --cells)
        self.mode = "filled"
        self.provider = "real"                 # 'real' | 'stub' | 'stub-roundtrip' | a provider module
        self.real_library = False
        self.center = (None, None, None)
        self.margin = sl.DEFAULT_MARGIN
        self.color = "KEEP"
        self.keep_unrecognised = False
        self.raise_quota_max = False           # decision D11: tick "Raise quota maximum (unverified)" on the export
        self.unverified_rotation = True        # tick "Allow unverified rotation export": adding objects needs it (DEC-5.6)
        self.overwrite = False
        self.dry_run = False                   # export to a scratch file, verify, keep nothing
        self.allow_stub_output = False
        self.addon_module = None
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise TypeError("unknown option %r" % key)
            setattr(self, key, value)


def parse_center(text):
    """``'x,y,z'`` where each part is a number or ``auto`` -> a 3-tuple with ``None`` for auto."""
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 3:
        raise ValueError("--center needs three comma-separated values (numbers or 'auto'), for example 0,0,auto")
    out = []
    for part in parts:
        if part.lower() == "auto":
            out.append(None)
            continue
        try:
            value = float(part)
        except ValueError:
            raise ValueError("--center: %r is not a number or 'auto'" % part)
        if not math.isfinite(value):
            raise ValueError("--center: %r is not finite" % part)
        out.append(value)
    return tuple(out)


def _grid_argument(text):
    if str(text).lower() == "auto":
        return None
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid int value or 'auto': %r" % text)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="build_star_mvar.py",
        description="Build a pixel-art block star on a Halo: Reach map variant with the Mjolnir Forge add-on (headless "
                    "Blender). The output is UNVERIFIED IN GAME.")
    ap.add_argument("--template", required=True, help="the map variant (.mvar) to start from; only ever read")
    ap.add_argument("--out", required=True, help="the new .mvar; outside the repository, not beside the template, not "
                                                 "in a sample folder, must not exist (unless --overwrite)")
    ap.add_argument("--block", default="auto", help="'auto' (default) or the display name of a stock block of the map, "
                                                    "for example 'Block, 1x1'")
    ap.add_argument("--cells", "--grid", dest="cells", type=_grid_argument, default=None, metavar="N|auto",
                    help="the star is drawn on an N x N grid of blocks; this is the grid size, not the block count. "
                         "'auto' (default) takes the largest of %s that still fits the free object slots of the template "
                         "(%d is about 80 blocks); an explicit N is refused when it does not fit" % (
                             ", ".join(str(n) for n in sl.AUTO_GRIDS), sl.DEFAULT_GRID))
    ap.add_argument("--outline", action="store_true", help="only the outline of the star (about half the blocks)")
    ap.add_argument("--shape", choices=sl.shape_names(), default=None, metavar="NAME",
                    help="use a fixed, reviewed star design instead of the sampled grid (%s). 'pixel39' is 39 blocks, 9 x 9, "
                         "one piece under 4-connectivity (every block touches a neighbour along a face), mirror symmetric; "
                         "it cannot be combined with --cells or --outline" % ", ".join(sl.shape_names()))
    ap.add_argument("--provider", choices=PROVIDERS, default="real",
                    help="real = the add-on's library (default); stub = the canned test stub (a dry run: nothing is kept "
                         "unless --allow-stub-output); stub-roundtrip = the remembering test double")
    ap.add_argument("--real-library", action="store_true",
                    help="link the real Halo Reach.blend of this repository (read-only) for the block models. Without it "
                         "the library must come from $MJOLNIR_LIBRARY or the add-on preference 'Library path'; the run is "
                         "refused when the add-on would fall back to the real one, or when the preference overrides "
                         "--real-library")
    ap.add_argument("--center", default="auto,auto,auto", metavar="X,Y,Z",
                    help="centre of the star, each part a number or 'auto' (default: the middle of the map bounds; "
                         "height: the star stands on the typical height of the existing objects)")
    ap.add_argument("--margin", type=float, default=sl.DEFAULT_MARGIN,
                    help="world units kept free between the star and the map bounds (default %g)" % sl.DEFAULT_MARGIN)
    ap.add_argument("--color", choices=COLOR_CHOICES, default="KEEP",
                    help="block colour; KEEP (default) leaves what the template's example block has (writes nothing extra)")
    ap.add_argument("--keep-unrecognised", action="store_true",
                    help="tick 'Keep objects this tool does not recognise' (DEC-7.4): objects of the template whose id is "
                         "not in the stock table are kept exactly as they are instead of refusing the export")
    ap.add_argument("--raise-quota-max", action="store_true",
                    help="tick 'Raise quota maximum (unverified)' on the export (decision D11): when a palette entry would "
                         "hold more objects than the template's maximum (a finished matchmaking map allows exactly what it "
                         "holds, so a Block row is (0, 0, 0)), raise that maximum instead of refusing. Never lowers a value; "
                         "UNVERIFIED in game")
    ap.add_argument("--no-rotation-gate", action="store_true",
                    help="do NOT tick 'Allow unverified rotation export' (the export is then refused; for testing)")
    ap.add_argument("--overwrite", action="store_true", help="allow --out to replace an existing file")
    ap.add_argument("--dry-run", action="store_true",
                    help="do everything, including the export and the verification, but into a scratch file that is "
                         "deleted afterwards: nothing is kept at --out")
    ap.add_argument("--allow-stub-output", action="store_true",
                    help="with --provider stub: write the stub's bytes (a copy of the template) to --out")
    ap.add_argument("--addon-module", default=None, help="module name of the enabled add-on (found automatically)")
    return ap


def parse_args(argv):
    """``argv`` (the part after ``--``) -> :class:`Options`. A bad command line exits with status 2 and a usage message."""
    ap = build_parser()
    args = ap.parse_args(list(argv))
    try:
        center = parse_center(args.center)
    except ValueError as exc:
        ap.error(str(exc))
    if args.cells is not None and (args.cells < sl.MIN_GRID or args.cells > sl.MAX_GRID):
        ap.error("--cells must be 'auto' or between %d and %d" % (sl.MIN_GRID, sl.MAX_GRID))
    if args.shape and (args.cells is not None or args.outline):
        ap.error("--shape is a fixed design: it cannot be combined with --cells or --outline")
    if not math.isfinite(args.margin) or args.margin < 0:
        ap.error("--margin must be zero or a positive number")
    return Options(template=args.template, out=args.out, block=args.block, cells=args.cells, shape=args.shape,
                   mode="outline" if args.outline else "filled", provider=args.provider,
                   real_library=args.real_library, center=center, margin=args.margin, color=args.color,
                   keep_unrecognised=args.keep_unrecognised, raise_quota_max=args.raise_quota_max,
                   unverified_rotation=not args.no_rotation_gate,
                   overwrite=args.overwrite, dry_run=args.dry_run, allow_stub_output=args.allow_stub_output,
                   addon_module=args.addon_module)


def script_arguments(argv=None):
    """The arguments after ``--`` (Blender's convention); ``[]`` when there is none."""
    argv = list(sys.argv if argv is None else argv)
    return argv[argv.index("--") + 1:] if "--" in argv else []


# --- path policy -------------------------------------------------------------------------------------
def _real(path):
    return os.path.realpath(os.path.expanduser(os.fspath(path)))


def _inside(path_real, folder_real):
    """True when ``path_real`` is the folder itself or lies anywhere below it (mirrors ``mvarlib.io._inside``).

    The text test alone is not enough on a case-insensitive volume (the macOS default): ``.../local_documents/...`` is the
    same folder as ``.../Local_Documents/...``. So, when the folder exists, the path and each of its ancestors are
    compared with the folder by identity (``samefile``).
    """
    try:
        if os.path.commonpath([path_real, folder_real]) == folder_real:
            return True
    except ValueError:                       # different drives (Windows) or mixed absolute/relative
        pass
    if os.path.isdir(folder_real):           # case-insensitive volumes, bind-mount aliases
        cur = path_real
        while True:
            try:
                if os.path.exists(cur) and os.path.samefile(cur, folder_real):
                    return True
            except OSError:
                pass
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    return False


def _same_folder(a_real, b_real):
    """True when two folder paths (already resolved) are the same folder, also when they differ only in case."""
    if a_real == b_real:
        return True
    try:
        return os.path.isdir(a_real) and os.path.isdir(b_real) and os.path.samefile(a_real, b_real)
    except OSError:
        return False


def protected_folders(environ=None):
    """Sample folders and their configured extras (``$MJOLNIR_SAMPLES``, ``$MJOLNIR_PROTECTED``), ``~`` expanded."""
    environ = os.environ if environ is None else environ
    folders = [os.path.expanduser(p) for p in SAMPLE_FOLDERS]
    for var in ("MJOLNIR_SAMPLES", "MJOLNIR_PROTECTED"):
        folders += [os.path.expanduser(p) for p in environ.get(var, "").split(os.pathsep) if p]
    return folders


def path_problems(out, template, repo=REPO, protected=None, overwrite=False):
    """Why ``out`` may not be written (complete sentences); empty when it may."""
    problems = []
    if not out:
        return ["No output file was given (--out)."]
    out_real = _real(out)
    template_real = _real(template) if template else None
    if not out_real.lower().endswith(".mvar"):
        problems.append("The output file name must end in .mvar (got %s)." % out)
    if _inside(out_real, _real(repo)):
        problems.append("Refusing to write inside the repository (%s): the repository must never hold a map variant. "
                        "Choose a folder outside it, for example ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/." % _real(repo))
    for folder in (protected_folders() if protected is None else protected):
        if folder and _inside(out_real, _real(folder)):
            problems.append("Refusing to write into the protected sample folder %s." % folder)
    if template_real is not None:
        same = out_real == template_real
        if not same and os.path.exists(out_real) and os.path.exists(template_real):
            try:
                same = os.path.samefile(out_real, template_real)
            except OSError:
                same = False
        if same:
            problems.append("Refusing to overwrite the template (%s). Choose a different --out." % template)
        elif _same_folder(os.path.dirname(out_real), os.path.dirname(template_real)):
            problems.append("Refusing to write beside the template (%s): originals are never written next to. Choose "
                            "another folder." % os.path.dirname(template_real))
    if os.path.exists(out_real) and not overwrite:
        problems.append("The output file already exists (%s). Choose another name or pass --overwrite." % out)
    if os.path.isdir(out_real):
        problems.append("The output path is a folder (%s)." % out)
    return problems


def fingerprint(path):
    """``(size, mtime_ns, sha256)`` of a file, read-only."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    st = os.stat(path)
    return (st.st_size, st.st_mtime_ns, digest.hexdigest())


# --- which object library the add-on will use (pure) -------------------------------------------------------
def repo_library_path(repo=None):
    """The real ``Halo Reach.blend`` of this checkout (the upstream binary; only ever linked read-only)."""
    return os.path.join(REPO if repo is None else repo, LIBRARY_RELATIVE)


def same_file(a, b):
    """True when two paths name the same file: same resolved text, or (both exist) the same file on disk."""
    if not a or not b:
        return False
    a_real, b_real = _real(a), _real(b)
    if a_real == b_real:
        return True
    try:
        return os.path.exists(a_real) and os.path.exists(b_real) and os.path.samefile(a_real, b_real)
    except OSError:
        return False


def library_problem(resolved, real_library, repo_library=None):
    """Why the object library the add-on resolved is not the one the options promise (a sentence), else ``None``.

    ``resolved`` is what ``palette.library_path()`` returns. The add-on checks the preference 'Library path' first, then
    ``$MJOLNIR_LIBRARY``, then its own ``Resources`` folder (which is the real library in a working-tree checkout). So
    ``--real-library`` (it only sets ``$MJOLNIR_LIBRARY``) can be overridden by the preference, and a run without it can
    still end up on the real library through the fallback. The real game asset is used only when asked for.
    """
    repo_library = repo_library or repo_library_path()
    is_real = same_file(resolved, repo_library)
    if real_library and not is_real:
        return ("--real-library asks for %s, but the add-on resolves the object library to %s: the add-on preference 'Library "
                "path' is checked before $MJOLNIR_LIBRARY and overrides it. Clear that preference, or leave out "
                "--real-library to use the library the add-on resolved." % (repo_library, resolved))
    if not real_library and is_real:
        return ("The object library would be the real %s (the add-on falls back to its own Resources folder when neither the "
                "preference 'Library path' nor $MJOLNIR_LIBRARY names a library). That game asset is only linked on request: "
                "pass --real-library, or set $MJOLNIR_LIBRARY to a stand-in library." % repo_library)
    return None


def library_source(resolved, environ=None, repo_library=None):
    """Where ``palette.library_path()`` got ``resolved`` from, for the log (the add-on's order: preference, env, Resources)."""
    environ = os.environ if environ is None else environ
    repo_library = repo_library or repo_library_path()
    env = environ.get("MJOLNIR_LIBRARY")
    if env:
        env = os.path.expanduser(env)
        if os.path.isdir(env):
            env = os.path.join(env, os.path.basename(repo_library))
        if same_file(resolved, env):
            return "$MJOLNIR_LIBRARY"
    if same_file(resolved, repo_library):
        return "the add-on's Resources folder"
    return "the add-on preference 'Library path'"


# --- choosing the block ------------------------------------------------------------------------------
def leaves_of_group(tree, group_name):
    """Leaf names of every group called ``group_name`` in a palette tree document (``[]`` when there is none)."""
    out = []

    def walk(node):
        for child in node.get("groups", []):
            if child.get("name") == group_name:
                out.extend(leaf["name"] if isinstance(leaf, dict) else leaf for leaf in child.get("leaves", []))
            walk(child)

    walk(tree)
    return out


def candidate_names(stock_names, group_leaves, allow_invisible=False):
    """Block names to consider, in the map's stock order: stock AND in the Building Blocks group, never ``Invisible``.

    When the tree has no such group the names starting with ``Block,`` are used instead.
    """
    stock = list(stock_names)
    members = set(group_leaves)
    if members:
        chosen = [n for n in stock if n in members]
    else:
        chosen = [n for n in stock if n.startswith("Block,")]
    if not allow_invisible:
        chosen = [n for n in chosen if "invisible" not in n.lower()]
    return chosen


_OBJECT_NAME = re.compile(r"^\d+ - (.+?)(?:\.\d{3,})?$")


def type_name_from_object_name(name):
    """``'12 - Block, 1x1.001'`` -> ``'Block, 1x1'`` (the importer names objects ``"<slot> - <type>"``); else ``''``."""
    match = _OBJECT_NAME.match(name or "")
    return match.group(1) if match else ""


def aspect_penalty(footprint):
    """``|ln(width / height)|``: 0 for a block that is as wide as it is tall (the star keeps its proportions)."""
    return abs(math.log(footprint.width / footprint.height))


def plan_penalty(footprint):
    """``|ln(width / depth)|``: 0 for a block that is as deep as it is wide (a one-layer star, immune to a quarter turn)."""
    return abs(math.log(footprint.width / footprint.depth))


def yaw_symmetric(footprint, tol=0.05):
    """True when width and depth agree within ``tol`` (a quarter turn about Z does not change the block's plan)."""
    return plan_penalty(footprint) <= tol


def good_for_a_star(footprint):
    """A block whose face in the star's plane is square and whose depth equals its width (a cube, give or take)."""
    return aspect_penalty(footprint) <= ASPECT_OK and plan_penalty(footprint) <= ASPECT_OK


def rank_candidates(entries):
    """Sort ``[(name, present_count, footprint_or_None)]`` best first; blocks without a footprint are dropped.

    Tier 0: in the template and cube-like (:func:`good_for_a_star`); 1: in the template; 2: not in the template but
    cube-like; 3: the rest. Inside a tier: the better shape (penalty in steps of 0.05), then the smaller block (less
    budget, a finer star), then more examples in the template, then the name. A long block such as ``Block, 1x4`` (as
    wide as it is tall, but four deep) is therefore never preferred to ``Block, 1x1``.
    """
    ranked = []
    for name, present, footprint in entries:
        if footprint is None:
            continue
        good = good_for_a_star(footprint)
        tier = (0 if good else 1) if present else (2 if good else 3)
        bucket = int((aspect_penalty(footprint) + plan_penalty(footprint)) / 0.05)
        size = round(max(footprint.width, footprint.depth, footprint.height), 3)
        ranked.append(((tier, bucket, size, -present, name), name, present, footprint))
    ranked.sort(key=lambda item: item[0])
    return [(name, present, footprint) for _key, name, present, footprint in ranked]


def resolve_block_name(requested, stock_names):
    """The canonical stock display name for ``requested`` (case-insensitive), or ``None`` when it is not a stock name."""
    for name in stock_names:
        if name == requested:
            return name
    lowered = [n for n in stock_names if n.lower() == str(requested).lower()]
    return lowered[0] if len(lowered) == 1 else None


# --- pre-flight (pure) ----------------------------------------------------------------------------------
def preflight_problems(map_name, stock_names, block_name, occupied, block_count, max_objects=MAX_OBJECTS):
    """Reasons the request cannot be met, before anything is added. Complete sentences, codes of SPEC 7.3 named."""
    problems = []
    if not map_name:
        problems.append("E_MAP_UNKNOWN: this map variant is not one of the 20 stock Halo: Reach maps this tool supports; "
                        "export is limited to stock maps.")
    if block_name is not None and map_name and block_name not in stock_names:
        problems.append("E_OBJ_NAME_UNKNOWN: '%s' is not a stock object on %s." % (block_name, map_name))
    if occupied + block_count > max_objects:
        problems.append("E_TOO_MANY: the template already holds %d objects and the star needs %d more, %d in all; the limit "
                        "is %d. Use a smaller --cells (or --outline) to add at most %d." % (
                            occupied, block_count, occupied + block_count, max_objects, max(0, max_objects - occupied)))
    return problems


# --- container and hash checks, independent of the library (SPEC 2.1, 2.5, 2.7) -----------------------------
SALT34 = bytes.fromhex("EDD43009666D5C4A5C3657FAB40E022F535AC6C9EE471F01F1A44756B7714F1C36EC")
MVAR_SIZE = 0x7028
MVAR_CAPACITY = 0x7000
RECIPES = ("plain_le32", "salted_be32", "salted_le32", "plain_be32", "data_only")


def split_blocks(data):
    """``([(sig, offset, size, version, flags)], end)``: the blocks up to and including ``_eof``; ``end`` starts the trailer."""
    blocks = []
    pos = 0
    while pos + 12 <= len(data) and len(blocks) < 256:
        sig = bytes(data[pos:pos + 4])
        size, version, flags = struct.unpack(">IHH", data[pos + 4:pos + 12])
        if size < 12 or pos + size > len(data):
            break
        blocks.append((sig, pos, size, version, flags))
        pos += size
        if sig == b"_eof":
            break
    return blocks, pos


def _recipe_input(recipe, stream, length):
    data = stream[:length]
    if recipe == "plain_le32":
        return struct.pack("<I", length) + data
    if recipe == "salted_be32":
        return SALT34 + struct.pack(">I", length) + data
    if recipe == "salted_le32":
        return SALT34 + struct.pack("<I", length) + data
    if recipe == "plain_be32":
        return struct.pack(">I", length) + data
    return data


def hash_flavour(data):
    """``(length_endian, recipe, L)`` of the ``mvar`` block of a plain file, found without the library.

    ``recipe`` is one of :data:`RECIPES`, ``'zero'`` (twenty zero bytes) or ``'unknown'``. ``None`` when the file has no
    plain 0x7028-byte ``mvar`` block.
    """
    blocks, _end = split_blocks(data)
    for sig, off, size, _version, _flags in blocks:
        if sig != b"mvar":
            continue
        if size != MVAR_SIZE:
            return None
        stored = bytes(data[off + 12:off + 32])
        raw = bytes(data[off + 32:off + 36])
        stream = bytes(data[off + 36:off + 36 + MVAR_CAPACITY])
        readings = [(e, struct.unpack(e + "I", raw)[0]) for e in (">", "<")]
        readings = [(e, n) for e, n in readings if 1 <= n <= MVAR_CAPACITY]
        if stored == bytes(20):
            return (readings[0][0] if readings else "?", "zero", readings[0][1] if readings else 0)
        for endian, length in readings:
            for recipe in RECIPES:
                if hashlib.sha1(_recipe_input(recipe, stream, length)).digest() == stored:
                    return (endian, recipe, length)
        return (readings[0][0] if readings else "?", "unknown", readings[0][1] if readings else 0)
    return None


def outside_payload_identical(template, output):
    """``(status, detail)``: everything except the ``mvar`` block's hash, stored length and bit stream is identical.

    ``status`` is ``'PASS'``, ``'FAIL'`` or ``'SKIP'`` (no plain ``mvar`` block, so nothing to compare). Block list
    (signatures, offsets, sizes, versions, flags), every other block, the 4 pad bytes of ``mvar``, the block header of
    ``mvar`` and any trailer after ``_eof`` must be byte-identical, and the file length must not change.
    """
    blocks_a, end_a = split_blocks(template)
    blocks_b, end_b = split_blocks(output)
    if not any(b[0] == b"mvar" and b[2] == MVAR_SIZE for b in blocks_a):
        return "SKIP", "the template has no plain 0x7028-byte mvar block"
    if blocks_a != blocks_b:
        return "FAIL", "the block list changed: %s -> %s" % (
            [(b[0].decode("latin-1"), b[2]) for b in blocks_a], [(b[0].decode("latin-1"), b[2]) for b in blocks_b])
    if template[end_a:] != output[end_b:]:
        return "FAIL", "the bytes after _eof (%d in the template, %d in the output) are not identical" % (
            len(template) - end_a, len(output) - end_b)
    for sig, off, size, _version, _flags in blocks_a:
        a, b = template[off:off + size], output[off:off + size]
        if sig == b"mvar":
            if a[:12] != b[:12]:
                return "FAIL", "the mvar block header changed"
            if a[36 + MVAR_CAPACITY:] != b[36 + MVAR_CAPACITY:]:
                return "FAIL", "the 4 pad bytes after the mvar bit stream changed"
        elif a != b:
            return "FAIL", "block %r (%d bytes at offset 0x%X) changed" % (sig.decode("latin-1"), size, off)
    return "PASS", "%d blocks and %d trailer byte(s) identical; only the hash, the stored length and the bit stream of mvar differ" % (
        len(blocks_a), len(template) - end_a)


# --- record verification (pure) ---------------------------------------------------------------------------
class Check(object):
    """One line of the verification table. ``status`` is PASS, FAIL, SKIP or INFO."""

    def __init__(self, name, status, detail=""):
        self.name = name
        self.status = status
        self.detail = detail

    @property
    def failed(self):
        return self.status == "FAIL"

    def line(self):
        return "[%s] %s%s" % (self.status, self.name, (": " + self.detail) if self.detail else "")

    def __repr__(self):
        return "Check(%r, %r, %r)" % (self.name, self.status, self.detail)


_INFO_FIELDS = ("map_id", "map_name", "is_stock_map", "bounds", "quota_count", "version", "title", "description",
                "labels", "label_present", "palette_crc", "max_budget_raw", "spent_budget_raw", "shape", "hash_flavour")


def _listing(items, limit=6):
    items = list(items)
    text = ", ".join(str(i) for i in items[:limit])
    return text + (" ... (%d in all)" % len(items) if len(items) > limit else "")


def verify_records(before, after, expected_positions, block_name, tolerance, can_store=True, vertical_tol=1.0e-3):
    """Compare two ``LoadResult`` objects (the template and the output); returns a list of :class:`Check`.

    ``expected_positions`` are the star's block positions as Blender handed them to the exporter. When ``can_store`` is
    false (the canned stub cannot remember what it wrote) the checks that need the new objects are SKIPped.
    """
    checks = []
    n = len(expected_positions)
    b_by = dict((r.slot, r) for r in before.objects)
    a_by = dict((r.slot, r) for r in after.objects)
    if len(a_by) != len(after.objects):
        checks.append(Check("slots are unique", "FAIL", "two objects of the output share a slot"))

    gone = sorted(s for s in b_by if s not in a_by)
    changed = sorted(s for s in b_by if s in a_by and a_by[s] != b_by[s])
    if gone or changed:
        checks.append(Check("original objects unchanged", "FAIL", "%d removed (%s), %d changed (%s) of %d" % (
            len(gone), _listing(gone), len(changed), _listing(changed), len(b_by))))
    else:
        checks.append(Check("original objects unchanged", "PASS", "%d of %d slots identical (identity token and every "
                            "decoded field)" % (len(b_by), len(b_by))))

    drift = [f for f in _INFO_FIELDS if getattr(before.info, f, None) != getattr(after.info, f, None)]
    if drift:
        checks.append(Check("map header and body fields unchanged", "FAIL", "changed: %s" % ", ".join(drift)))
    else:
        checks.append(Check("map header and body fields unchanged", "PASS", "%s; budget words copied unchanged" % (
            ", ".join(f for f in ("map_id", "bounds", "quota_count", "version", "title", "labels", "hash_flavour")))))

    if not can_store:
        for name in ("star block count", "star block type", "star block positions", "star blocks Fixed",
                     "star blocks vertical", "occupied count"):
            checks.append(Check(name, "SKIP", "the stub provider cannot remember what it wrote"))
        return checks

    new = [a_by[s] for s in sorted(a_by) if s not in b_by]
    ok = len(new) == n
    checks.append(Check("star block count", "PASS" if ok else "FAIL", "%d new objects, expected %d" % (len(new), n)))
    wrong_type = [r.slot for r in new if r.type_name != block_name]
    checks.append(Check("star block type", "FAIL" if wrong_type else "PASS",
                        ("slots %s are not '%s'" % (_listing(wrong_type), block_name)) if wrong_type
                        else "all %d are '%s' (id 0x%04X)" % (len(new), block_name, new[0].type_id) if new else "none"))
    match = sl.match_positions(expected_positions, [r.position for r in new], tolerance)
    if match.ok and new:
        checks.append(Check("star block positions", "PASS", "all %d within the quantisation tolerance (largest error %.5f, "
                            "%.5f, %.5f; allowed %.5f, %.5f, %.5f)" % ((len(new),) + tuple(match.worst) + tuple(tolerance))))
    else:
        checks.append(Check("star block positions", "FAIL", "%d expected positions missing, %d unexpected objects, "
                            "tolerance %.5f" % (len(match.missing), len(match.extra), tolerance[0])))
    loose = [r.slot for r in new if r.physics != 1]
    checks.append(Check("star blocks Fixed", "FAIL" if loose else "PASS",
                        ("slots %s are not Fixed (physics %s)" % (_listing(loose), _listing(r.physics for r in new if r.physics != 1)))
                        if loose else "physics = Fixed on all %d" % len(new)))
    tilted = [r.slot for r in new if abs(r.up[2] - 1.0) > vertical_tol]
    checks.append(Check("star blocks vertical", "FAIL" if tilted else "PASS",
                        ("slots %s are tilted" % _listing(tilted)) if tilted else "up = +Z on all %d" % len(new)))
    want = before.info.occupied + n
    checks.append(Check("occupied count", "PASS" if after.info.occupied == want else "FAIL",
                        "%d slots used (template %d + %d), limit %d" % (after.info.occupied, before.info.occupied, n, MAX_OBJECTS)))
    if after.info.occupied > MAX_OBJECTS:
        checks.append(Check("650-object limit", "FAIL", "%d objects" % after.info.occupied))
    return checks


def diff_lines(before, after, limit=8):
    """The diff report between two ``LoadResult`` objects: what was added, removed or changed, by object type."""
    b_by = dict((r.slot, r) for r in before.objects)
    a_by = dict((r.slot, r) for r in after.objects)
    added = sorted(s for s in a_by if s not in b_by)
    removed = sorted(s for s in b_by if s not in a_by)
    changed = sorted(s for s in b_by if s in a_by and a_by[s] != b_by[s])
    lines = ["diff     : %d object(s) added, %d removed, %d changed, %d unchanged (of %d in the template)" % (
        len(added), len(removed), len(changed), len(b_by) - len(removed) - len(changed), len(b_by))]
    for title, slots, table in (("added", added, a_by), ("removed", removed, b_by), ("changed", changed, a_by)):
        kinds = {}
        for slot in slots:
            kinds.setdefault(table[slot].type_name, []).append(slot)
        for name in sorted(kinds):
            shown = ", ".join(str(n) for n in kinds[name][:limit])
            lines.append("           %s %d x '%s' in slot(s) %s%s" % (
                title, len(kinds[name]), name, shown, " ..." if len(kinds[name]) > limit else ""))
    return lines


# --- the export report (the add-on's text datablock), parsed -----------------------------------------------
_ISSUE_LINE = re.compile(r"^\s+(ERROR|WARNING|INFO)\s+([EWI]_[A-Z0-9_]+)\b(.*)$")
_CHANGE_LINE = re.compile(r"^\s+(KEPT|MOVED|EDITED|RETARGETED|ADDED|REMOVED|NOT IMPORTED)\s+slot\b")


def parse_report(text):
    """``(issues, changes)`` of an export report: ``[(severity, code, line)]`` and ``{kind: count}``."""
    issues, changes = [], {}
    for line in text.splitlines():
        m = _ISSUE_LINE.match(line)
        if m:
            issues.append((m.group(1), m.group(2), line.strip()))
            continue
        m = _CHANGE_LINE.match(line)
        if m:
            changes[m.group(1)] = changes.get(m.group(1), 0) + 1
    return issues, changes


# --- the Blender part ---------------------------------------------------------------------------------
class Log(object):
    """Prints and remembers every line (the report file gets the same text)."""

    def __init__(self, echo=True):
        self.lines = []
        self.echo = echo

    def say(self, text=""):
        for line in str(text).split("\n"):
            self.lines.append(line)
            if self.echo:
                print(line)
                sys.stdout.flush()

    def head(self, text):
        self.say("")
        self.say("== %s ==" % text)


class Mods(object):
    """The add-on's modules as the running Blender imported them, plus ``bpy``."""
    pass


class BuildResult(object):
    """What :func:`build` returns (the tests read it)."""

    def __init__(self):
        self.status = "failed"             # 'ok' | 'refused' | 'failed'
        self.message = ""
        self.exit_code = EXIT_FAILED
        self.out_path = None               # the file that was written (and kept), else None
        self.block_name = None
        self.footprint = None
        self.centre = None
        self.positions = []
        self.cells = []
        self.grid = None                   # the grid size N that was used
        self.checks = []
        self.attempts = []                 # [(block name, 'ok' | 'refused: CODE ...' | ...)]
        self.warnings = []
        self.report_lines = []
        self.rejected_path = None
        self.scratch = None                # a private temp folder of a stub dry run (removed by build())

    @property
    def ok(self):
        return self.status == "ok"


def find_addon_module(preferred=None):
    """Name of the enabled add-on package (the one whose ``io_ops`` and ``mjolnir`` modules are loaded)."""
    names = []
    for name in (preferred, os.environ.get("MJOLNIR_ADDON_MODULE"), "bl_ext.user_default.mjolnir_forge", "mjolnir_forge"):
        if name and name not in names:
            names.append(name)
    for name in sorted(sys.modules):
        if name.endswith(".io_ops") and name[:-len(".io_ops")] + ".mjolnir" in sys.modules:
            package = name[:-len(".io_ops")]
            if package not in names:
                names.append(package)
    for name in names:
        if name + ".io_ops" in sys.modules and name + ".mjolnir" in sys.modules:
            return name
    for name in names:
        try:
            importlib.import_module(name + ".io_ops")
            importlib.import_module(name + ".mjolnir")
            return name
        except Exception:
            continue
    raise StarBuildError("The Mjolnir Forge add-on is not enabled in this Blender. Start Blender with --addons <module> "
                         "(see docs/mvar/STAR_BUILD.md; tools/run_star_build.sh does it for you).", "failed")


def load_modules(preferred=None):
    import bpy                                                        # only inside Blender
    mods = Mods()
    mods.bpy = bpy
    mods.name = find_addon_module(preferred)
    for short in ("io_ops", "mjolnir", "palette", "state", "provider"):
        setattr(mods, short, importlib.import_module("%s.%s" % (mods.name, short)))
    for namespace, op in (("import_scene", "mjolnir_mvar"), ("export_scene", "mjolnir_mvar"), ("forge", "add_object")):
        if not hasattr(getattr(bpy.ops, namespace), op):
            raise StarBuildError("The operator %s.%s is not registered: the add-on %s is not enabled." % (
                namespace, op, mods.name), "failed")
    return mods


def install_provider(choice, mods):
    """Make the add-on talk to ``choice``; returns ``(provider, label, can_read_back)``."""
    if choice == "real":
        mods.provider.set_provider(None)
        return mods.provider.get_provider(), "real library (%s)" % getattr(mods.provider.get_provider(), "__name__", "?"), True
    if isinstance(choice, str):
        for path in (os.path.join(REPO, "Addon"), os.path.join(REPO, "tests", "stubs")):
            if path not in sys.path:
                sys.path.append(path)                                 # the stub imports the repository's mvarlib
        module = importlib.import_module("stub_roundtrip" if choice == "stub-roundtrip" else "stub_mvarlib")
    else:
        module = choice
    mods.provider.set_provider(module)
    can_store = bool(getattr(module, "ROUNDTRIP", False)) or not getattr(module, "IS_STUB", False)
    label = "%s (test double%s)" % (getattr(module, "__name__", "stub"), "" if can_store else ", cannot remember what it writes")
    return module, label, can_store


def _collection_matrix(obj):
    if obj.parent is None:
        return obj.matrix_basis.copy()
    return _collection_matrix(obj.parent) @ obj.matrix_parent_inverse @ obj.matrix_basis


def measure_collection(collection):
    """The mesh box of a palette collection as a :class:`star_layout.Footprint`, relative to the instance origin; ``None`` without a mesh."""
    from mathutils import Vector
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    found = 0
    for obj in collection.all_objects:
        if obj.type != "MESH" or obj.data is None or len(obj.data.vertices) == 0:
            continue
        found += 1
        matrix = _collection_matrix(obj)
        for corner in obj.bound_box:
            point = matrix @ Vector(corner)
            for axis in range(3):
                lo[axis] = min(lo[axis], point[axis])
                hi[axis] = max(hi[axis], point[axis])
    if not found:
        return None
    shift = collection.instance_offset                                 # the instance origin is the collection's offset
    lo = [lo[a] - shift[a] for a in range(3)]
    hi = [hi[a] - shift[a] for a in range(3)]
    size = [hi[a] - lo[a] for a in range(3)]
    if any(s <= 1e-6 for s in size):
        return None
    centre = tuple(round((lo[a] + hi[a]) / 2.0, 6) for a in range(3))
    return sl.Footprint(round(size[0], 6), round(size[1], 6), round(size[2], 6), centre)


def imported_by_type(mods, scene):
    """``{type name: [objects by slot]}`` for the objects the template created."""
    out = {}
    for obj in sorted((o for o in scene.objects if "mj_slot" in o), key=lambda o: o["mj_slot"]):
        name = mods.mjolnir.forge_type_name(obj) or type_name_from_object_name(obj.name)
        if name:
            out.setdefault(name, []).append(obj)
    return out


FLAG_PROPERTIES = ("symmetry", "placeAtStart", "gameSpecific", "team", "color", "cachedType")


def example_flags(examples):
    """``(dict of property values, slot)`` of the most common flag combination among the template's examples (ties: lowest slot)."""
    counts = {}
    order = []
    for obj in examples:
        values = tuple(getattr(obj.forge, p) for p in FLAG_PROPERTIES)
        if values not in counts:
            counts[values] = [0, obj["mj_slot"]]
            order.append(values)
        counts[values][0] += 1
    best = max(order, key=lambda v: (counts[v][0], -counts[v][1]))
    return dict(zip(FLAG_PROPERTIES, best)), counts[best][1], len(counts)


def run_export(mods, out_path, raise_quota_max=False):
    """Run the add-on's export operator; returns ``(finished, message, report_text)``. Never raises for a refusal.

    ``raise_quota_max`` ticks the operator's "Raise quota maximum (unverified)" option (decision D11); it is passed
    only when set, so a provider or add-on without the option is not disturbed.
    """
    bpy = mods.bpy
    kwargs = {"raise_quota_max": True} if raise_quota_max else {}
    try:
        result = bpy.ops.export_scene.mjolnir_mvar(filepath=out_path, **kwargs)
        finished = result == {"FINISHED"}
        message = "" if finished else "the export operator returned %s" % (sorted(result),)
    except RuntimeError as exc:                     # report({'ERROR'}) reaches Python as a RuntimeError
        finished, message = False, str(exc).strip()
    text = bpy.data.texts.get(mods.io_ops.REPORT_NAME)
    return finished, message, (text.as_string() if text is not None else "")


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0


STAR_MARK = "mj_star"                       # custom property of every block this script adds (and nothing else carries it)


def _set_active_collection(bpy, collection):
    layer = bpy.context.view_layer.layer_collection.children.get(collection.name)
    if layer is not None:
        bpy.context.view_layer.active_layer_collection = layer


def _remove_star_blocks(bpy):
    """Delete the blocks this script added (found by their mark, wherever they are); the template's objects are never touched."""
    for obj in [o for o in bpy.data.objects if o.get(STAR_MARK)]:
        bpy.data.objects.remove(obj, do_unlink=True)


def add_star_blocks(mods, block_name, positions, flags, color, collection):
    """Add one block per position with ``forge.add_object`` (the Add > Forge Object path); returns the objects."""
    bpy = mods.bpy
    scene = bpy.context.scene
    created = []
    cursor = tuple(scene.cursor.location)
    previous_layer = bpy.context.view_layer.active_layer_collection      # restored below: later imports must not land in the star's collection
    _set_active_collection(bpy, collection)
    try:
        for index, position in enumerate(positions):
            scene.cursor.location = position
            try:
                result = bpy.ops.forge.add_object(objectType=block_name)
            except (RuntimeError, TypeError) as exc:
                raise StarBuildError("The add-on refused to add '%s': %s" % (block_name, exc), "failed")
            if result != {"FINISHED"}:
                raise StarBuildError("forge.add_object did not finish for '%s' (%s)." % (block_name, sorted(result)), "failed")
            obj = bpy.context.view_layer.objects.active
            obj.name = "%s%03d" % (BLOCK_PREFIX, index)
            obj[STAR_MARK] = True
            obj.location = position
            fp = obj.forge
            for prop, value in flags.items():
                setattr(fp, prop, value)
            if color != "KEEP":
                fp.color = color
            fp.physics = "FIXED"
            created.append(obj)
    finally:
        scene.cursor.location = cursor
        bpy.context.view_layer.active_layer_collection = previous_layer
    return created


def _fmt_vec(v):
    return "(%s)" % ", ".join("%.4f" % c for c in v)


class Run(object):
    """State shared by the stages of one :func:`build` (everything a later stage needs from an earlier one)."""

    def __init__(self, options, log, result):
        self.options = options
        self.log = log
        self.result = result
        self.t0 = time.time()
        self.template = os.path.abspath(os.path.expanduser(options.template or ""))
        self.out = os.path.abspath(os.path.expanduser(options.out or ""))
        self.cells = []
        self.grid = None
        self.extent_lo = self.extent_hi = None     # bounding box of the template's own objects
        self.template_bytes = b""
        self.template_before = None
        self.library_before = None
        self.library_path = None           # what the add-on resolved (palette.library_path()), fingerprinted when it is a file
        self.mods = None
        self.bpy = None
        self.P = None
        self.can_store = False
        self.keep_output = True
        self.before = None                 # LoadResult of the template, read by the library itself
        self.map_name = ""
        self.bounds = None
        self.occupied = 0
        self.stock = []
        self.group = []
        self.present = {}
        self.explicit = False
        self.ranked = []
        self.ground_z = None
        self.collection = None


class Exported(object):
    """One successful export attempt."""

    def __init__(self, name, count, footprint, centre, positions, target, report, issues, changes):
        self.name, self.count, self.footprint, self.centre = name, count, footprint, centre
        self.positions, self.target, self.report, self.issues, self.changes = positions, target, report, issues, changes


def build(options, log=None):
    """The whole pipeline. Returns a :class:`BuildResult`; a refusal or failure is reported in it, never raised."""
    log = log or Log()
    result = BuildResult()
    try:
        run = Run(options, log, result)
        stage_request(run)
        stage_environment(run)
        stage_template(run)
        stage_block(run)
        exported = stage_export(run)
        stage_verify(run, exported)
    except StarBuildError as exc:
        result.status = exc.kind
        result.message = str(exc)
        result.exit_code = EXIT_REFUSED if exc.kind == "refused" else EXIT_FAILED
        log.say("")
        log.say("%s: %s" % ("REFUSED (nothing was written)" if exc.kind == "refused" else "FAILED", exc))
    except Exception as exc:                        # a bug in this script: say so plainly
        import traceback
        traceback.print_exc()
        result.status, result.exit_code = "failed", EXIT_FAILED
        result.message = "Unexpected error: %s: %s" % (type(exc).__name__, exc)
        log.say("")
        log.say("FAILED: %s" % result.message)
    finally:
        if result.scratch:
            for name in os.listdir(result.scratch):
                try:
                    os.remove(os.path.join(result.scratch, name))
                except OSError:
                    pass
            try:
                os.rmdir(result.scratch)
            except OSError:
                pass
    log.say("")
    log.say("RESULT: %s" % ("OK" if result.ok else result.status.upper()))
    if result.ok or result.status == "failed":
        log.say("")
        log.say("CAVEATS")
        for text in CAVEATS:
            log.say(" * " + text)
    result.report_lines = list(log.lines)
    if result.out_path or result.rejected_path:                 # a file was written: keep the report beside it
        try:
            with open(os.path.abspath(os.path.expanduser(options.out)) + ".report.txt", "w") as fh:
                fh.write("\n".join(log.lines) + "\n")
        except OSError as exc:
            print("Could not write the report file: %s" % exc)
    return result


# --- stage 1: the request, before Blender is touched ----------------------------------------------------------
def stage_request(run):
    options, log = run.options, run.log
    if options.shape:
        log.say("Mjolnir block star: design %s, block %s" % (options.shape, options.block))
    else:
        log.say("Mjolnir block star: %s star, grid %s, block %s" % (
            options.mode, "auto" if options.cells is None else "%dx%d" % (options.cells, options.cells), options.block))
    log.head("1. Request")
    if not os.path.isfile(run.template):
        raise StarBuildError("The template does not exist or is not a file: %s" % run.template)
    if os.path.getsize(run.template) > MAX_TEMPLATE_BYTES:
        raise StarBuildError("The template is larger than 1 MiB; this does not look like a map variant: %s" % run.template)
    problems = path_problems(run.out, run.template, overwrite=options.overwrite)
    if problems:
        raise StarBuildError(" ".join(problems))
    if options.mode not in sl.MODES:
        raise StarBuildError("The star mode must be one of %s (got %r)." % (", ".join(sl.MODES), options.mode))
    if options.shape:
        if options.cells is not None or options.mode != "filled":
            raise StarBuildError("A fixed star design (shape %r) cannot be combined with a grid size or the outline mode." % options.shape)
        try:
            run.cells = sl.named_shape(options.shape)
        except sl.LayoutError as exc:
            raise StarBuildError(str(exc))
        run.grid = max(c[0] for c in run.cells) + 1
    elif options.cells is not None:
        try:
            run.cells, run.grid = sl.star_cells(options.cells, options.mode), options.cells
        except sl.LayoutError as exc:
            raise StarBuildError(str(exc))
    log.say("template : %s" % run.template)
    log.say("output   : %s" % run.out)
    if run.cells and options.shape:
        log.say("star     : %d blocks (fixed design %r, %d columns)" % (len(run.cells), options.shape, run.grid))
    elif run.cells:
        log.say("star     : %d blocks (%s, grid %d)" % (len(run.cells), options.mode, run.grid))
    run.template_before = fingerprint(run.template)
    log.say("template : %d bytes, sha256 %s" % (run.template_before[0], run.template_before[2]))
    log.say("            (opened read-only; size, time and hash are checked again at the end)")
    with open(run.template, "rb") as fh:
        run.template_bytes = fh.read()


# --- stage 2: Blender, the add-on, the provider and the object library -----------------------------------------
def stage_environment(run):
    options, log = run.options, run.log
    repo_library = repo_library_path()
    if options.real_library:
        if not os.path.isfile(repo_library):
            raise StarBuildError("--real-library: %s was not found." % repo_library, "failed")
        os.environ["MJOLNIR_LIBRARY"] = repo_library
    run.mods = load_modules(options.addon_module)
    run.bpy = run.mods.bpy
    resolved = run.mods.palette.library_path()          # what the add-on will really link, whatever the options say
    problem = library_problem(resolved, options.real_library, repo_library)
    if problem:
        raise StarBuildError(problem)
    run.library_path = resolved
    source = "--real-library" if options.real_library else library_source(resolved, os.environ, repo_library)
    if os.path.isfile(resolved):
        run.library_before = fingerprint(resolved)
        log.say("library  : %s (%s; linked read-only; sha256 %s)" % (resolved, source, run.library_before[2][:16]))
    else:
        log.say("library  : %s (%s; NOT FOUND)" % (resolved, source))
    run.P, label, run.can_store = install_provider(options.provider, run.mods)
    is_stub = bool(getattr(run.P, "IS_STUB", False))
    log.say("provider : %s" % label)
    if is_stub:
        log.say("*** STUB PROVIDER: a test double, not the codec. %s ***" % (
            "The output is a stand-in payload, not a map variant." if run.can_store
            else "The output is a stand-in, not a map variant with a star."))
    run.keep_output = not ((is_stub and not options.allow_stub_output) or options.dry_run)
    if options.dry_run:
        log.say("*** dry run (--dry-run): the export goes to a scratch file that is verified and deleted; nothing is kept ***")
    elif not run.keep_output:
        log.say("*** stub dry run: the export goes to a scratch file that is deleted; use --allow-stub-output to keep it ***")


# --- stage 3: read the template with the library and import it with the add-on ----------------------------------
def stage_template(run):
    log, P, mods, bpy = run.log, run.P, run.mods, run.bpy
    log.head("2. Template")
    try:
        run.before = P.load_map_variant(run.template_bytes, os.path.basename(run.template))
    except NotImplementedError as exc:
        raise StarBuildError("The real library cannot read map variants yet (%s: %s): gates G3 and G5 are not finished. Use "
                             "--provider stub for a dry run." % (type(exc).__name__, exc), "failed")
    except P.MvarError as exc:
        raise StarBuildError("The template could not be read: %s" % exc)
    scene = bpy.context.scene
    try:
        finished = bpy.ops.import_scene.mjolnir_mvar(filepath=run.template)
    except RuntimeError as exc:
        raise StarBuildError("The add-on could not import the template: %s" % exc, "failed")
    st = mods.state.get(scene)
    if finished != {"FINISHED"} or st is None:
        raise StarBuildError("The add-on did not import the template.", "failed")
    run.map_name = st.get("map_name", "")
    run.bounds = tuple(float(v) for v in st["bounds"])
    run.occupied = int(st.get("occupied_at_import", 0))
    failed_slots = list(st.get("failed_slots", []))
    log.say("map      : %s %s" % (run.map_name or "NOT A STOCK MAP", st.get("map_id_hex", "")))
    log.say("title    : %s" % run.before.info.title)
    log.say("objects  : %d in the template, room for %d more (limit %d objects)" % (
        run.occupied, max(0, MAX_OBJECTS - run.occupied), MAX_OBJECTS))
    log.say("bounds   : x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f" % run.bounds)
    log.say("file     : %s, layout %s" % (st.get("hash_flavour", "?"), run.before.info.hypothesis))
    if failed_slots:
        run.result.warnings.append("%d slot(s) could not be imported and stay untouched: %s" % (len(failed_slots), failed_slots))
        log.say("WARNING: %s" % run.result.warnings[-1])
    run.stock = list(P.stock_object_names(run.map_name)) if run.map_name else []
    if run.map_name:
        _report_extent(run, scene)
    if _wants_auto_grid(run):
        _choose_grid(run)
    early = preflight_problems(run.map_name, run.stock, None, run.occupied, len(run.cells))
    if early:
        raise StarBuildError(" ".join(early))


def _wants_auto_grid(run):
    return run.options.cells is None and not run.options.shape


def _choose_grid(run):
    """``--cells auto``: the largest star that fits the free slots of the template."""
    room = max(0, MAX_OBJECTS - run.occupied)
    grid = sl.fit_grid(room, run.options.mode)
    if grid is None:
        smallest = min(sl.AUTO_GRIDS)
        raise StarBuildError("E_TOO_MANY: the template already holds %d objects, so only %d more fit under the limit of %d, "
                             "and the smallest star (grid %d) needs %d blocks (%d as an outline). Delete objects in the "
                             "template first, or ask for a smaller grid with --cells N." % (
                                 run.occupied, room, MAX_OBJECTS, smallest, len(sl.star_cells(smallest, "filled")),
                                 len(sl.star_cells(smallest, "outline"))))
    run.grid, run.cells = grid, sl.star_cells(grid, run.options.mode)
    run.log.say("star     : grid auto -> %d: %d blocks (%s), the largest of %s that fits the %d free slots" % (
        grid, len(run.cells), run.options.mode, ", ".join(str(n) for n in sl.AUTO_GRIDS), room))


def _report_extent(run, scene):
    """Print where the template's own objects are (the bounds of a map variant can be far larger than the map)."""
    run.bpy.context.view_layer.update()
    points = [o.matrix_world.translation for o in scene.objects if "mj_slot" in o]
    if not points:
        return
    run.extent_lo = tuple(min(p[a] for p in points) for a in range(3))
    run.extent_hi = tuple(max(p[a] for p in points) for a in range(3))
    run.log.say("objects  : the template's own objects span x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f" % (
        run.extent_lo[0], run.extent_hi[0], run.extent_lo[1], run.extent_hi[1], run.extent_lo[2], run.extent_hi[2]))


# --- stage 4: which block, and how big it is ----------------------------------------------------------------------
def stage_block(run):
    options, log, mods, P = run.options, run.log, run.mods, run.P
    scene = run.bpy.context.scene
    log.head("3. Block")
    if not mods.palette.find_collection("Forge World Palette"):
        raise StarBuildError("The object library was not found, so the block cannot be measured. Pass --real-library, set "
                             "$MJOLNIR_LIBRARY or the add-on preference 'Library path'.", "failed")
    run.present = imported_by_type(mods, scene)
    run.group = leaves_of_group(P.palette_tree(), BLOCK_GROUP)
    if (options.block or "auto").lower() == "auto":
        names = candidate_names(run.stock, run.group)
        run.explicit = False
    else:
        canonical = resolve_block_name(options.block, run.stock)
        if canonical is None:
            raise StarBuildError("%s Stock blocks on %s: %s." % (
                preflight_problems(run.map_name, run.stock, options.block, run.occupied, len(run.cells))[0], run.map_name,
                ", ".join(candidate_names(run.stock, run.group, allow_invisible=True)) or "none"))
        names = [canonical]
        run.explicit = True
        if canonical not in run.group:
            log.say("WARNING: '%s' is not in the Building Blocks group; the star may not look like blocks." % canonical)
        if "invisible" in canonical.lower():
            log.say("WARNING: '%s' is an invisible block: the star will not be visible in game." % canonical)
    if not names:
        raise StarBuildError("%s has no visible stock building block. Pass --block with the display name of a stock object." % (
            run.map_name or "This map"))
    log.say("blocks in the template: %s" % (
        ", ".join("%s x%d" % (n, len(o)) for n, o in sorted(run.present.items()) if n in names) or "none"))
    entries = []
    for name in names:
        collection = mods.palette.find_collection(name)
        footprint = measure_collection(collection) if collection is not None else None
        if footprint is None:
            log.say("  %-28s no model in the library, skipped" % name)
        entries.append((name, len(run.present.get(name, [])), footprint))
    run.ranked = rank_candidates(entries)
    if not run.ranked:
        raise StarBuildError("None of the candidate blocks has a model in the object library, so none can be measured.", "failed")
    if not any(present for _n, present, _f in run.ranked):
        what = ("'%s'" % run.ranked[0][0]) if run.explicit else "building block"
        log.say("*** WARNING: the template contains no %s. The library cannot learn the object class of a block from the "
                "map, so it falls back to the palette group rule (SPEC 7.4: Structure is class 0, with the warning "
                "W_CACHED_TYPE_ASSUMED). This is UNVERIFIED. ***" % what)
        run.result.warnings.append("no block type of the template was usable; a stock block was chosen" if not run.explicit
                                   else "the block asked for is not in the template; its class is assumed")
    for name, count, footprint in run.ranked[:8]:
        log.say("  %-28s %s  mesh %.4f x %.4f x %.4f  aspect %.3f" % (
            name, ("in template x%d" % count) if count else "NOT in template", footprint.width, footprint.depth,
            footprint.height, footprint.width / footprint.height))


# --- stage 5: lay out, add, export (next block type only for refusals that depend on the type) ------------------
def stage_export(run):
    options, log, mods, bpy, result = run.options, run.log, run.mods, run.bpy, run.result
    scene = bpy.context.scene
    run.collection = bpy.data.collections.get(COLLECTION_NAME) or bpy.data.collections.new(COLLECTION_NAME)
    if run.collection.name not in scene.collection.children:
        scene.collection.children.link(run.collection)
    _remove_star_blocks(bpy)
    scene.forge.allowUnverifiedRotation = bool(options.unverified_rotation)
    scene.forge.keepUnrecognisedObjects = bool(options.keep_unrecognised)
    if options.unverified_rotation:
        log.say("")
        log.say("NOTE: 'Allow unverified rotation export' is ticked, as adding objects requires (DEC-5.6): the yaw written for "
                "new objects uses a convention nobody has checked against the game.")
    if options.keep_unrecognised:
        log.say("NOTE: 'Keep objects this tool does not recognise' is ticked (--keep-unrecognised).")
    if options.raise_quota_max:
        log.say("NOTE: 'Raise quota maximum (unverified)' is ticked (--raise-quota-max, decision D11): a palette entry whose "
                "maximum in the template is too small gets its maximum raised to the new count (nothing is lowered, no "
                "minimum is touched). Whether the game honours the file's maximum or rebuilds it is unknown.")
    bpy.context.view_layer.update()
    heights = [o.matrix_world.translation.z for objs in run.present.values() for o in objs]
    run.ground_z = _median(heights) if heights else None
    attempts = run.ranked[:1] if run.explicit else run.ranked[:MAX_ATTEMPTS]
    for tries, (name, count, footprint) in enumerate(attempts, 1):
        log.head("4. Layout and export, attempt %d: %s" % (tries, name))
        positions, centre = _layout(run, name, footprint)
        flags = _announce_and_copy_flags(run, name, count, footprint, positions, centre)
        blocks = add_star_blocks(mods, name, positions, flags, options.color, run.collection)
        log.say("added    : %d x '%s' with forge.add_object, physics Fixed%s" % (
            len(blocks), name, "" if options.color == "KEEP" else ", colour " + options.color))
        if run.keep_output:
            target = run.out
        else:
            if _inside(_real(tempfile.gettempdir()), _real(REPO)):
                raise StarBuildError("The temporary folder %s is inside the repository (check $TMPDIR); nothing may be written "
                                     "there." % tempfile.gettempdir(), "failed")
            scratch = tempfile.mkdtemp(prefix="mjolnir-star-scratch-")
            result.scratch = scratch
            target = os.path.join(scratch, os.path.basename(run.out))
        finished, message, report = run_export(mods, target, options.raise_quota_max)
        issues, changes = parse_report(report)
        codes = [code for sev, code, _line in issues if sev == "ERROR"]
        if finished:
            result.attempts.append((name, "ok"))
            return Exported(name, count, footprint, centre, positions, target, report, issues, changes)
        result.attempts.append((name, "refused: " + ", ".join(codes or [message[:80]])))
        log.say("REFUSED by the exporter (nothing was written):")
        for severity, _code, line in issues:
            if severity == "ERROR":
                log.say("  " + line)
        if not issues:
            log.say("  " + message)
        for code in dict.fromkeys(codes):
            if code in HINTS:
                log.say("  hint: %s" % HINTS[code])
        if "NotImplementedError" in report or "NotImplementedError" in message:
            raise StarBuildError("The real writer is not available yet (gate G5 is not finished): %s" % (
                message or "NotImplementedError"), "failed")
        _remove_star_blocks(bpy)
        retry = (not run.explicit and codes and all(c in TYPE_SPECIFIC_CODES for c in codes) and tries < len(attempts))
        if not retry:
            raise StarBuildError("The export was refused%s. First problem: %s" % (
                " (" + ", ".join(dict.fromkeys(codes)) + ")" if codes else "", issues[0][2] if issues else message), "failed")
        log.say("-> trying the next block type (the refusal depends on the block type)")
    raise StarBuildError("No block type could be exported.", "failed")          # unreachable: the loop returns or raises


def _layout(run, name, footprint):
    """Centre and positions of the star for this block, with every limit checked; raises a refusal."""
    options, log = run.options, run.log
    size = sl.extent(run.cells, footprint)
    try:
        centre = sl.choose_centre(run.bounds, size, options.margin, run.ground_z, options.center)
    except sl.LayoutError as exc:
        raise StarBuildError(str(exc))
    positions = sl.cell_positions(run.cells, footprint, centre)
    problems = sl.check_bounds(positions, footprint, run.bounds, options.margin)
    if problems:
        raise StarBuildError("E_OUT_OF_BOUNDS: " + " ".join(problems))
    problems = preflight_problems(run.map_name, run.stock, name, run.occupied, len(run.cells))
    if problems:
        raise StarBuildError(" ".join(problems))
    standing = run.ground_z is not None and options.center[2] is None
    if run.extent_lo is not None:
        box_lo = tuple(min(p[a] - footprint.width / 2.0 for p in positions) for a in range(2))
        box_hi = tuple(max(p[a] + footprint.width / 2.0 for p in positions) for a in range(2))
        if any(box_hi[a] < run.extent_lo[a] or box_lo[a] > run.extent_hi[a] for a in range(2)):
            run.result.warnings.append("the star lies outside the area covered by the template's own objects")
            log.say("WARNING: %s: the bounds of this map variant (x %.0f to %.0f) can be much larger than the map, so the "
                    "middle of the bounds may not be the middle of the map. Choose a place with --center X,Y,Z." % (
                        run.result.warnings[-1], run.bounds[0], run.bounds[1]))
    log.say("star box : %.3f x %.3f x %.3f centred at %s (x, y: the middle of the bounds unless --center; z: %s)" % (
        size + (_fmt_vec(centre), "bottom on the typical object height %.2f" % run.ground_z if standing else "as chosen")))
    log.say("spacing  : %.4f along x, %.4f along z (the mesh box of '%s'); blocks touch, none overlap" % (
        footprint.width, footprint.height, name))
    log.say("shape    : %d blocks, one '#' each (top is up, left is -X)" % len(run.cells))
    for row in sl.render_cells(run.cells):
        log.say("            " + row)
    return positions, centre


def _announce_and_copy_flags(run, name, count, footprint, positions, centre):
    """Warnings about this block and the flags of the template's own example (``{}`` when it has none)."""
    log = run.log
    if aspect_penalty(footprint) > ASPECT_OK:
        log.say("WARNING: '%s' is %.2f times as wide as it is tall, so the star will look stretched." % (
            name, footprint.width / footprint.height))
    if not yaw_symmetric(footprint):
        log.say("WARNING: '%s' is not square in plan (%.3f x %.3f): if the unverified yaw convention is wrong by a quarter "
                "turn, neighbouring blocks would overlap." % (name, footprint.width, footprint.depth))
    boxes = sl.mesh_boxes(positions, footprint)
    box_lo = tuple(min(b[0][a] for b in boxes) for a in range(3))
    box_hi = tuple(max(b[1][a] for b in boxes) for a in range(3))
    inside = [o for objs in run.present.values() for o in objs
              if all(box_lo[a] <= o.matrix_world.translation[a] <= box_hi[a] for a in range(3))]
    if inside:
        run.result.warnings.append("%d existing object(s) lie inside the star's box" % len(inside))
        log.say("WARNING: %s (they may clip into the blocks): %s" % (run.result.warnings[-1], ", ".join(o.name for o in inside[:5])))
    if not count:
        return {}
    flags, slot, variants = example_flags(run.present[name])
    log.say("flags    : copied from the template's own '%s' (slot %d%s): %s" % (
        name, slot, "; the %d examples differ, the most common set was used" % variants if variants > 1 else "",
        ", ".join("%s=%s" % (k, v) for k, v in sorted(flags.items()))))
    return flags


# --- stage 6: verify the written file independently --------------------------------------------------------------
def stage_verify(run, exported):
    options, log, mods, bpy, result, P = run.options, run.log, run.mods, run.bpy, run.result, run.P
    name, footprint = exported.name, exported.footprint
    result.block_name, result.footprint, result.centre = name, footprint, exported.centre
    result.positions, result.cells, result.grid = exported.positions, run.cells, run.grid
    log.head("5. Export verdict (the add-on's own report)")
    for _severity, _code, line in exported.issues:
        log.say("  " + line)
    log.say("changes  : %s" % (", ".join("%d %s" % (n, k.lower()) for k, n in sorted(exported.changes.items())) or "none reported"))
    for line in exported.report.splitlines():
        if line.startswith(("  Objects:", "  Bits used", "  Stored stream", "  Hash:", "Budget was not", "This tool has never")):
            log.say(line)
    with open(exported.target, "rb") as fh:
        written = fh.read()
    log.say("file     : %s, %d bytes, sha256 %s" % (exported.target, len(written), hashlib.sha256(written).hexdigest()))

    log.head("6. Verification (re-reading the output)")
    try:
        after = P.load_map_variant(written, os.path.basename(run.out))
    except Exception as exc:
        raise _reject(run, exported.target, "The output could not be read back: %s: %s" % (type(exc).__name__, exc))
    checks = list(verify_records(run.before, after, exported.positions, name, sl.position_tolerance(run.bounds), run.can_store))
    checks.extend(_file_checks(run, written))
    checks.extend(_reimport_check(mods, bpy, exported.target, after))
    for check in checks:
        log.say(check.line())
    for line in diff_lines(run.before, after):
        log.say(line)
    result.checks = checks
    failed = [c for c in checks if c.failed]
    log.say("")
    log.say("block    : '%s' x %d, Fixed, from the template: %s" % (name, len(exported.positions), "yes" if exported.count else "NO (assumed class)"))
    log.say("centre   : %s, size %.3f x %.3f x %.3f" % ((_fmt_vec(exported.centre),) + tuple(sl.extent(run.cells, footprint))))
    log.say("time     : %.1f s" % (time.time() - run.t0))
    if failed:
        raise _reject(run, exported.target, "%d verification check(s) failed: %s" % (len(failed), "; ".join(c.name for c in failed)))
    if run.keep_output:
        result.out_path = run.out
        log.say("report   : %s.report.txt" % run.out)
        log.say("")
        log.say("DELIVERABLE: %s  (%d bytes, sha256 %s)  UNVERIFIED IN GAME" % (run.out, len(written), hashlib.sha256(written).hexdigest()))
    result.status, result.exit_code, result.message = "ok", EXIT_OK, ""
    if not run.keep_output:
        log.say("dry run complete: no file was kept%s." % ("" if options.dry_run else " (the stub does not write a map variant)"))


def _file_checks(run, written):
    """Checks on the bytes alone, made without the library: outside the bit stream, the hash recipe, the inputs untouched."""
    checks = []
    status, detail = outside_payload_identical(run.template_bytes, written)
    checks.append(Check("bytes outside the bit stream identical", status, detail))
    t_flavour, o_flavour = hash_flavour(run.template_bytes), hash_flavour(written)
    if t_flavour is None or o_flavour is None:
        checks.append(Check("hash recipe reproduced", "SKIP", "no plain mvar block to examine"))
    elif t_flavour[1] == "unknown":
        checks.append(Check("hash recipe reproduced", "INFO", "the template's hash matches no known recipe (%s); output: %s" % (
            t_flavour[:2], o_flavour[:2])))
    else:
        same = t_flavour[:2] == o_flavour[:2]
        checks.append(Check("hash recipe reproduced", "PASS" if same else "FAIL", "template %s/%s (L=%d), output %s/%s (L=%d)" % (
            t_flavour[1], t_flavour[0], t_flavour[2], o_flavour[1], o_flavour[0], o_flavour[2])))
    if run.can_store:
        checks.append(Check("output differs from the template", "PASS" if written != run.template_bytes else "FAIL",
                            "%d bytes against %d" % (len(written), len(run.template_bytes))))
    else:
        checks.append(Check("output differs from the template", "SKIP", "the stub returns the template unchanged"))
    unchanged = _unchanged(run.template, run.template_before)
    checks.append(Check("template untouched", "PASS" if unchanged else "FAIL",
                        "size, mtime and sha256 unchanged" if unchanged else "the template CHANGED on disk"))
    if run.library_before is not None:                  # whatever library the add-on resolved, not only --real-library
        unchanged = _unchanged(run.library_path, run.library_before)
        checks.append(Check("object library untouched", "PASS" if unchanged else "FAIL",
                            ("size, mtime and sha256 unchanged (%s)" % run.library_path) if unchanged
                            else "the library CHANGED on disk (%s)" % run.library_path))
    return checks


def _unchanged(path, before):
    """True when ``path`` still has the fingerprint ``before`` (a file that vanished or cannot be read has changed)."""
    try:
        return fingerprint(path) == before
    except OSError:
        return False


def _reject(run, target, message):
    """A written file failed verification: move it out of the way (``*.REJECTED``) and return the error to raise."""
    if run.keep_output and os.path.exists(target):
        rejected = run.out + ".REJECTED"
        try:
            os.replace(target, rejected)
            run.result.rejected_path = rejected
            run.log.say("The written file failed verification and was renamed to %s. DO NOT USE IT." % rejected)
        except OSError as exc:
            run.log.say("The written file failed verification (and could not be renamed: %s). DO NOT USE IT: %s" % (exc, target))
    return StarBuildError(message, "failed")


def _reimport_check(mods, bpy, target, after):
    """Import the output with the add-on itself (replacing the scene's objects) and compare the object counts."""
    _remove_star_blocks(bpy)                         # the file holds the blocks now; the scene's own copies would double them
    try:
        done = bpy.ops.import_scene.mjolnir_mvar(filepath=target)
    except RuntimeError as exc:
        return [Check("re-import with the add-on", "FAIL", str(exc))]
    st = mods.state.get(bpy.context.scene)
    count = len([o for o in bpy.context.scene.objects if "mj_slot" in o])
    failed = len(st.get("failed_slots", [])) if st else -1
    ok = done == {"FINISHED"} and st is not None and count == len(after.objects) and failed == 0
    return [Check("re-import with the add-on", "PASS" if ok else "FAIL",
                  "%d objects imported (the file holds %d), %d failed" % (count, len(after.objects), failed))]


def main(argv=None):
    """Entry point: ``argv`` defaults to the arguments after ``--``. Returns the exit status."""
    options = parse_args(script_arguments() if argv is None else argv)
    return build(options).exit_code


if __name__ == "__main__":
    sys.exit(main())
