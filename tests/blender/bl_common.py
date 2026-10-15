"""Shared helpers of the headless Blender tests (SPEC 9.4). Runs inside Blender only; no test lives here.

Every test file ``bNN_name.py`` defines ``ID``, ``TITLE``, ``NEEDS_STUB`` and a ``run(env)`` and/or a ``run_real(env)``:

* ``run`` is the version for ``--provider stub`` (canned data of ``tests/stubs``); when ``NEEDS_STUB`` is false it is
  provider-agnostic and also runs under ``--provider real``;
* ``run_real`` is the version for ``--provider real`` (the library behind the add-on, fixtures of the independent
  builder and the one real map variant);
* ``REAL_ONLY = True`` marks a test that exists only for the real provider (it is not part of a stub run).

A file ends with::

    if __name__ == "__main__":
        bl_common.main_module(sys.modules[__name__])

so it runs alone (``blender -b --factory-startup --addons <id> --python tests/blender/bNN_name.py -- --provider real``)
or from ``run_all.py``. ``env`` (:class:`Env`) carries the add-on modules as the running Blender imported
them (the glue and the tests must share one ``provider`` module), the stub provider, a private temp folder
outside the repo and the stand-in object library (built once per process in a child Blender; the real
``Halo Reach.blend`` is only used with ``--real-library``, read-only).

The add-on is expected to be enabled at STARTUP (``--addons``): that is the condition under which
``bpy.data`` is restricted during ``register()``.
"""
import contextlib
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_ADDON = "bl_ext.user_default.mjolnir_forge"
ENV_ADDON = "MJOLNIR_ADDON_MODULE"
ENV_LIBRARY = "MJOLNIR_LIBRARY"
REAL_LIBRARY = os.path.join(REPO, "Addon", "Resources", "Halo Reach.blend")
NO_LIBRARY = os.path.join(tempfile.gettempdir(), "mjolnir-no-such-library", "Halo Reach.blend")


EXIT_SKIPPED = 3                  # exit status of a run that failed nothing but skipped something (run_all.py, main())


class Skip(Exception):
    """Raised by a test that cannot run in this configuration (reported as SKIP with the reason)."""


def check(cond, message="check failed"):
    if not cond:
        raise AssertionError(message)


def check_eq(actual, expected, message=""):
    if actual != expected:
        raise AssertionError("%s: expected %r, got %r" % (message or "values differ", expected, actual))


def _as_list(value):
    try:
        return list(value)                   # mathutils.Vector has no __iter__ but supports the sequence protocol
    except TypeError:
        return [value]


def check_close(actual, expected, tol=1e-4, message=""):
    a = _as_list(actual)
    e = _as_list(expected)
    if len(a) != len(e) or any(abs(x - y) > tol for x, y in zip(a, e)):
        raise AssertionError("%s: expected %r, got %r (tol %g)" % (message or "values differ", e, a, tol))


def check_raises(exc_type, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError("expected %s from %s" % (exc_type.__name__, getattr(fn, "__name__", fn)))


def parse_args(argv=None):
    """``{"provider", "only", "real_library", "addon"}`` from the arguments after ``--``."""
    argv = list(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []) if argv is None else list(argv)
    out = {"provider": "stub", "only": [], "real_library": False, "addon": os.environ.get(ENV_ADDON, DEFAULT_ADDON)}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--provider":
            out["provider"] = argv[i + 1]
            i += 1
        elif arg == "--real-library":
            out["real_library"] = True
        elif arg == "--addon-module":
            out["addon"] = argv[i + 1]
            i += 1
        elif arg == "--only":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                out["only"].append(argv[i])
                i += 1
            continue
        i += 1
    if out["provider"] not in ("stub", "real"):
        raise SystemExit("--provider must be stub or real")
    return out


def _import_stub():
    addon_dir = os.path.join(REPO, "Addon")
    stubs_dir = os.path.join(REPO, "tests", "stubs")
    if addon_dir not in sys.path:
        sys.path.append(addon_dir)           # the stub imports the repository copy of mvarlib as ``mvarlib``
    if stubs_dir not in sys.path:
        sys.path.append(stubs_dir)
    return importlib.import_module("stub_mvarlib")


class Env(object):
    """What a test needs. Created once per process."""

    def __init__(self, args):
        self.args = args
        self.provider_kind = args["provider"]
        self.real_library_requested = args["real_library"]
        self.addon_name = args["addon"]
        self.addon = importlib.import_module(self.addon_name)
        self.mjolnir = importlib.import_module(self.addon_name + ".mjolnir")
        self.io_ops = importlib.import_module(self.addon_name + ".io_ops")
        self.palette = importlib.import_module(self.addon_name + ".palette")
        self.state = importlib.import_module(self.addon_name + ".state")
        self.provider = importlib.import_module(self.addon_name + ".provider")
        self.stub = _import_stub()
        self.tmp = tempfile.mkdtemp(prefix="mjolnir-btest-")
        if os.path.realpath(self.tmp).startswith(os.path.realpath(REPO) + os.sep):
            raise SystemExit("temp folder inside the repository: %s" % self.tmp)
        self._standin = None
        self.reset()

    # --- providers and library ------------------------------------------------------------------
    @property
    def is_stub(self):
        return self.provider_kind == "stub"

    def require_stub(self):
        if not self.is_stub:
            raise Skip("needs the stub provider (canned data); run with --provider stub")

    def standin_library(self):
        """Path of the stand-in ``Halo Reach.blend`` (built once per process in a child Blender)."""
        if self._standin is None:
            out_dir = os.path.join(self.tmp, "standin")
            subprocess.run(
                [bpy.app.binary_path, "-b", "--factory-startup", "--python-exit-code", "1", "--python",
                 os.path.join(HERE, "make_standin_library.py"), "--", out_dir],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
            self._standin = os.path.join(out_dir, "Halo Reach.blend")
        return self._standin

    def library_path(self):
        return REAL_LIBRARY if self.real_library_requested else self.standin_library()

    def use_library(self, path=None):
        """Point ``$MJOLNIR_LIBRARY`` at the stand-in (or ``path``); returns the path."""
        path = path or self.library_path()
        os.environ[ENV_LIBRARY] = path
        return path

    def no_library(self):
        """Make the library unavailable (objects import as arrow empties)."""
        os.environ[ENV_LIBRARY] = NO_LIBRARY

    # --- scene hygiene ---------------------------------------------------------------------------
    def reset(self):
        """Empty scene, no library, default scene props, stub controls cleared, provider chosen, library unavailable."""
        scene = bpy.context.scene
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        for coll in list(scene.collection.children):
            scene.collection.children.unlink(coll)
        for coll in list(bpy.data.collections):
            if coll.library is None:
                bpy.data.collections.remove(coll)
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)
        for datablocks in (bpy.data.cameras, bpy.data.meshes, bpy.data.curves, bpy.data.texts):
            for block in list(datablocks):
                datablocks.remove(block)
        for other in list(bpy.data.scenes):
            if other is not scene:
                bpy.data.scenes.remove(other)
        self.state.clear(scene)
        for name in ("scaleConvention", "allowUnverifiedRotation", "keepUnrecognisedObjects"):
            scene.forge.property_unset(name)
        scene.cursor.location = (0.0, 0.0, 0.0)
        self.stub.reset()
        self.provider.set_provider(self.stub if self.is_stub else None)
        if not self.is_stub:                            # --provider real must mean the library behind the add-on, nothing else
            active = self.provider.get_provider()
            if getattr(active, "IS_STUB", False) or not str(getattr(active, "__name__", "")).endswith("mvarlib.api"):
                raise RuntimeError("--provider real is not running the add-on's own mvarlib.api: %r" % (active,))
        self.palette._cache.update(provider=None, tree=None)       # forget the cached tree of the previous provider
        self.mjolnir._overlay.update(dirty=True, count=0)
        self.no_library()

    def write_template(self, name="template.mvar", payload=b"STUB-TEMPLATE-BYTES\x00\x01\x02"):
        """A file the stub provider accepts as a map variant (it only looks at the SHA-256)."""
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(payload)
        return path

    def import_stub(self, load=None, path=None, **kwargs):
        """Import through the operator; ``load`` is a LoadResult the stub returns instead of ``CANNED``."""
        if load is not None:
            self.stub.NEXT_LOAD = load
        path = path or self.write_template()
        return bpy.ops.import_scene.mjolnir_mvar(filepath=path, **kwargs), path

    def import_file(self, path, **kwargs):
        """Import ``path`` through File > Import (works with either provider); returns the operator result set."""
        return bpy.ops.import_scene.mjolnir_mvar(filepath=path, **kwargs)

    def import_bytes(self, data, name="fixture.mvar", **kwargs):
        """Write ``data`` below the private temp folder and import it; returns ``(result set, path)``."""
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return self.import_file(path, **kwargs), path

    def require_real_provider(self):
        if self.is_stub:
            raise Skip("needs the real provider; run with --provider real")

    def export_to(self, name="out.mvar", **kwargs):
        """Run the export operator; returns ``(result_set_or_exception, output_path)``."""
        path = os.path.join(self.tmp, name)
        if os.path.exists(path):
            os.remove(path)
        try:
            result = bpy.ops.export_scene.mjolnir_mvar(filepath=path, **kwargs)
        except RuntimeError as exc:                 # report({'ERROR'}) surfaces as RuntimeError to Python callers
            result = exc
        return result, path

    # --- registration safety net -------------------------------------------------------------------
    def addon_registered(self):
        """True when the add-on's pointer properties and operators exist (what every test other than B-01 needs)."""
        return (hasattr(bpy.types.Scene, "forge") and hasattr(bpy.types.Object, "forge")
                and getattr(bpy.types, "IMPORT_SCENE_OT_mjolnir_mvar", None) is not None
                and getattr(bpy.types, "EXPORT_SCENE_OT_mjolnir_mvar", None) is not None)

    def ensure_registered(self):
        """Register the add-on again when a test left it unregistered; True when that was necessary.

        Without this a failing B-01 (which unregisters and registers on purpose) would make every later test fail
        with an unrelated ``AttributeError`` on ``scene.forge``.
        """
        if self.addon_registered():
            return False
        try:
            self.addon.unregister()
        except Exception:
            traceback.print_exc()
        self.addon.register()
        return True

    def forge_objects(self):
        return sorted((o for o in bpy.context.scene.objects if o.get("isForgeObject")), key=lambda o: o.name)

    def report_text(self):
        text = bpy.data.texts.get(self.io_ops.REPORT_NAME)
        return text.as_string() if text is not None else ""

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


@contextlib.contextmanager
def fresh_scene(name="Fresh"):
    """A new, empty scene made the context scene for the block (operators see ``context.scene`` = the new scene)."""
    scene = bpy.data.scenes.new(name)
    try:
        with bpy.context.temp_override(scene=scene):
            yield scene
    finally:
        try:
            bpy.data.scenes.remove(scene)
        except Exception:
            pass


@contextlib.contextmanager
def capture_output(stderr=False):
    """Capture everything written to file descriptor 1 (operator ``report`` lines go there in background mode), and with
    ``stderr=True`` file descriptor 2 as well (tracebacks printed by ``traceback.print_exc``).

    Yields a list that receives the captured text (one string) when the block ends.
    """
    sink = []
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1)
    saved_err = os.dup(2) if stderr else None
    tmp = tempfile.TemporaryFile(mode="w+b")
    try:
        os.dup2(tmp.fileno(), 1)
        if stderr:
            os.dup2(tmp.fileno(), 2)
        try:
            yield sink
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved, 1)
            if stderr:
                os.dup2(saved_err, 2)
            tmp.seek(0)
            sink.append(tmp.read().decode("utf-8", "replace"))
    finally:
        os.close(saved)
        if saved_err is not None:
            os.close(saved_err)
        tmp.close()


# --- recording stand-in for UILayout -------------------------------------------------------------------
_ICONS = None


def icon_names():
    global _ICONS
    if _ICONS is None:
        _ICONS = set(bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys())
    return _ICONS


class FakeOperatorProps(object):
    def __init__(self, idname):
        self.__dict__["idname"] = idname


class FakeUI(object):
    """Records every call; validates property names and icons the way the real layout would resolve them."""

    def __init__(self, log=None, depth=0):
        object.__setattr__(self, "log", log if log is not None else [])
        object.__setattr__(self, "depth", depth)
        object.__setattr__(self, "sets", {})

    def __setattr__(self, name, value):
        self.sets[name] = value
        self.log.append(("set", name, value))

    def _icon(self, icon):
        if icon not in (None, "NONE", ""):
            if isinstance(icon, str) and icon not in icon_names():
                raise AssertionError("unknown icon %r" % icon)

    def _child(self, kind):
        self.log.append((kind,))
        return FakeUI(self.log, self.depth + 1)

    def row(self, **kw):
        return self._child("row")

    def column(self, **kw):
        return self._child("column")

    def box(self, **kw):
        return self._child("box")

    def split(self, **kw):
        return self._child("split")

    def column_flow(self, **kw):
        return self._child("column_flow")

    def grid_flow(self, **kw):
        return self._child("grid_flow")

    def separator(self, **kw):
        self.log.append(("separator",))

    def label(self, text="", icon="NONE", **kw):
        self._icon(icon)
        self.log.append(("label", text))

    def prop(self, data, prop, text=None, icon="NONE", **kw):
        self._icon(icon)
        props = getattr(getattr(data, "bl_rna", None), "properties", None)
        if props is not None and hasattr(data, "bl_rna"):
            if prop not in props.keys():
                raise AssertionError("%r has no property %r" % (data, prop))
        elif not hasattr(data, prop):
            raise AssertionError("%r has no attribute %r" % (data, prop))
        self.log.append(("prop", prop, text, self.sets.get("enabled", True)))

    def operator(self, idname, text="", icon="NONE", **kw):
        self._icon(icon)
        self.log.append(("operator", idname, text, icon))
        return FakeOperatorProps(idname)

    def menu(self, idname, text="", icon="NONE", **kw):
        self._icon(icon)
        if getattr(bpy.types, idname, None) is None:
            raise AssertionError("menu %r is not registered" % idname)
        self.log.append(("menu", idname, text, icon))

    def context_pointer_set(self, *a, **kw):
        self.log.append(("context_pointer_set",))

    def prop_menu_enum(self, *a, **kw):
        self.log.append(("prop_menu_enum",))

    def texts(self):
        return [entry[1] for entry in self.log if entry[0] == "label"]

    def props(self):
        return [entry[1] for entry in self.log if entry[0] == "prop"]

    def operators(self):
        return [entry for entry in self.log if entry[0] == "operator"]

    def menus(self):
        return [entry for entry in self.log if entry[0] == "menu"]


class FakeSelf(object):
    """Stands in for ``self`` of a Panel / Menu / Operator draw method."""

    def __init__(self, **attrs):
        self.layout = FakeUI()
        self.__dict__.update(attrs)


class FakeContext(object):
    def __init__(self, scene=None, selected_objects=(), collection=None, area=None, **extra):
        self.scene = scene or bpy.context.scene
        self.selected_objects = list(selected_objects)
        self.collection = collection
        self.area = area
        self.active_object = self.selected_objects[0] if self.selected_objects else None
        self.__dict__.update(extra)


def draw_with_fake(draw_function, context=None, **self_attrs):
    """Call a bare ``draw(self, context)`` with a recording layout; returns the :class:`FakeUI`."""
    fake = FakeSelf(**self_attrs)
    draw_function(fake, context or FakeContext())
    return fake.layout


def record_vs_export(rec, eo, tol_pos=1e-4, tol_dir=1e-5, tol_dim=1e-5):
    """Differences between an imported ``ObjectRecord`` and the ``ExportObject`` the glue builds back from the scene.

    The glue-side meaning of "re-exports with a zero diff": every field the library compares is handed back
    unchanged. Documented equivalences: team none (-1) is handed back as 8 (NEUTRAL; the library treats 8 over a
    ``none`` baseline as unchanged, SPEC 6.4); an imported type id comes back as ``type_id_hint``.
    """
    diffs = []

    def same(name, a, b):
        if a != b:
            diffs.append((name, a, b))

    def close(name, a, b, tol):
        if any(abs(x - y) > tol for x, y in zip(a, b)):
            diffs.append((name, tuple(a), tuple(b)))

    same("slot", rec.slot, eo.slot)
    same("token_raw", rec.raw, eo.token_raw)
    same("token_bits", rec.raw_bits, eo.token_bits)
    same("type_id_hint", rec.type_id, eo.type_id_hint)
    close("position", rec.position, eo.position, tol_pos)
    close("forward", rec.forward, eo.forward, tol_dir)
    close("up", rec.up, eo.up, tol_dir)
    same("shape", rec.shape, eo.shape)
    close("dims", (rec.width, rec.length, rec.top, rec.bottom), (eo.width, eo.length, eo.top, eo.bottom), tol_dim)
    same("spawn_sequence", rec.spawn_sequence, eo.spawn_sequence)
    same("spawn_time", rec.spawn_time, eo.spawn_time)
    same("cached_type", rec.cached_type, eo.cached_type)
    same("label_index", rec.label_index, eo.label_index)
    same("physics", rec.physics, eo.physics)
    same("symmetry", rec.symmetry, eo.symmetry)
    same("place_at_start", rec.place_at_start, eo.place_at_start)
    same("game_specific", rec.game_specific, eo.game_specific)
    same("team", 8 if rec.team in (-1, 8) else rec.team, eo.team)
    same("color", rec.color, eo.color)
    same("other_a", rec.other_a, eo.other_a)
    same("other_b", rec.other_b, eo.other_b)
    return diffs


# --- running -----------------------------------------------------------------------------------------------
@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


def select_run(module_or_run, env):
    """The function a test runs for the active provider, or raises :class:`Skip` with the reason.

    A bare function (``main`` of an old-style file) runs as it is. A module runs ``run`` under the stub, ``run_real``
    under the real provider (falling back to a provider-agnostic ``run`` when ``NEEDS_STUB`` is false), and a stub-data
    test without a real variant is skipped with a reason that names the gap.
    """
    if callable(module_or_run):
        return module_or_run
    needs_stub = getattr(module_or_run, "NEEDS_STUB", True)
    run = getattr(module_or_run, "run", None)
    run_real = getattr(module_or_run, "run_real", None)
    if env.is_stub:
        if run is None:
            raise Skip("exists for the real provider only; run with --provider real")
        return run
    if run_real is not None:
        return run_real
    if needs_stub or run is None:
        raise Skip("needs the stub provider (canned data) and has no real-provider variant")
    return run


def run_test(module_or_run, test_id, env):
    """Run one test with a clean scene; returns ``("PASS"|"FAIL"|"SKIP", detail)``.

    Whatever the outcome, the add-on is registered again afterwards if the test left it unregistered, and a test
    that passed while doing so is reported as a failure of its own (not of the tests that follow).
    """
    try:
        run = select_run(module_or_run, env)
        env.reset()
        run(env)
        status, detail = "PASS", ""
    except Skip as exc:
        status, detail = "SKIP", str(exc)
    except Exception:
        status, detail = "FAIL", traceback.format_exc()
    try:
        restored = env.ensure_registered()
    except Exception:
        return "FAIL", detail + "\nthe add-on could not be registered again:\n" + traceback.format_exc()
    if restored:
        note = "the test left the add-on unregistered (the harness registered it again for the next test)"
        return "FAIL", (detail + "\n" + note) if detail else note
    return status, detail


def _finish(env, test_id, status, detail):
    print("%s %s %s" % (status, test_id, detail if status != "PASS" else ""))
    env.cleanup()
    if status == "FAIL":
        sys.exit(1)
    if status == "SKIP":
        sys.exit(EXIT_SKIPPED)                   # a skipped test proves nothing: never exit 0 for it


def main_module(module):
    """Entry point of a stand-alone test file (``bl_common.main_module(sys.modules[__name__])``)."""
    args = parse_args()
    env = Env(args)
    if args["real_library"] and not os.path.isfile(REAL_LIBRARY):
        raise SystemExit("--real-library: %s not found" % REAL_LIBRARY)
    status, detail = run_test(module, getattr(module, "ID", "?"), env)
    _finish(env, getattr(module, "ID", "?"), status, detail)


def main(run, test_id, needs_stub=True):
    """Entry point of an old-style stand-alone file that only has ``run`` (kept for the stub-only files)."""
    args = parse_args()
    env = Env(args)
    if args["real_library"] and not os.path.isfile(REAL_LIBRARY):
        raise SystemExit("--real-library: %s not found" % REAL_LIBRARY)

    class _Holder(object):
        pass

    holder = _Holder()
    holder.run = run
    holder.NEEDS_STUB = needs_stub
    status, detail = run_test(holder, test_id, env)
    _finish(env, test_id, status, detail)
