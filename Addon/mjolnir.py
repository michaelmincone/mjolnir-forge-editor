"""Mjolnir Forge Editor: the Blender side of the map variant port (SPEC section 8).

Rewritten from the maintained ``forge.py`` v0.9.9.2. The live-memory bridge is gone (no ``ctypes``, no
DLL, no process memory, no update checker, no ``sys.path`` edit). The scene is read and written through
two plain data conversions that talk to the library ONLY through ``provider``:

* :func:`apply_record`        ``ObjectRecord``  -> Blender object   (import; former ``FromForgeObject``)
* :func:`to_export_object`    Blender object   -> ``ExportObject``  (export; former ``ToForgeObject``)

Kept for the user: the property groups ``Object.forge`` / ``Collection.forge`` / ``Scene.forge`` (the
shaders of the object library read ``forge.colorIndex``), the panels, ``Add > Forge Object``, ``Convert
To Forge Object``, ``Setup Array``, ``Scale Forge Objects`` and the "N / 650" overlay. The fix list of
SPEC 8.7 is applied; each fix is marked ``8.7 #n`` where it lives.

``register()`` only registers classes, pointer properties and menu hooks (SPEC 8.2): it never touches
``bpy.data`` or ``bpy.context.scene``, calls no operator, starts no thread and reads no file.
"""
import math
import re
import textwrap

import blf
import bpy
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)
from bpy.types import Operator
from mathutils import Euler, Matrix, Vector

from . import palette, provider, state

VERSION = "1.1.0"
MAX_OBJECTS = 650
ANVIL_SCALING = True

# --- value tables (library ints <-> Blender enums) -------------------------------------------
TEAM_NAMES = ('RED', 'BLUE', 'GREEN', 'ORANGE', 'PURPLE', 'YELLOW', 'BROWN', 'PINK', 'NEUTRAL')   # 0..8
COLOR_NUMBER = dict((name, i) for i, name in enumerate(TEAM_NAMES))                               # for colorIndex
PHYSICS_TO_ENUM = {0: 'NORMAL', 1: 'FIXED', 2: 'NORMAL', 3: 'PHASED'}    # 2 is unused in the file (SPEC 3.9): shown as NORMAL
PHYSICS_FROM_ENUM = {'NORMAL': 0, 'FIXED': 1, 'PHASED': 3}
SYMMETRY_TO_ENUM = {0: 'NEITHER', 1: 'ASYMMETRIC', 2: 'SYMMETRIC', 3: 'BOTH'}                    # 3.9 file reading
SYMMETRY_FROM_ENUM = dict((v, k) for k, v in SYMMETRY_TO_ENUM.items())
SHAPE_TO_ENUM = {0: 'NONE', 1: 'SPHERE', 2: 'CYLINDER', 3: 'BOX'}
SHAPE_FROM_ENUM = dict((v, k) for k, v in SHAPE_TO_ENUM.items())
TELEPORTER_TYPES = (12, 13, 14)
ARRAY_PARENT_TYPES = ('FACES', 'VERTS')


def team_to_enum(team):
    """Library team (-1 none, 0..8) -> enum; "none" and 8 both show as NEUTRAL (the library treats 8 over none as unchanged)."""
    return TEAM_NAMES[team] if 0 <= team <= 7 else 'NEUTRAL'


def color_to_enum(color):
    """Library colour (-1 = team colour, 0..7) -> enum."""
    return TEAM_NAMES[color] if 0 <= color <= 7 else 'TEAM_COLOR'


def _clamp(value, low, high):
    return max(low, min(high, int(value)))


# --- scale conventions (port of forge.py; 8.7 #3 default is set on the property) ---------------
def recursive_330x(i, scale):
    for _ in range(max(0, i)):
        scale = scale + scale // 33 + scale // 228
    return scale


def spawnSeqToScale(spawnSequence, convention='47X', team='NONE'):
    one_percent_seq = -20 if convention == '330X' else -10
    if spawnSequence == one_percent_seq:
        return 0.01
    if convention == '1X':
        scale = 1
    elif convention == '33X':
        scale = 0.1 * spawnSequence
        if spawnSequence < -10:
            scale *= -2
            if spawnSequence > -81:
                scale += 8
            elif spawnSequence < -80:
                scale = 2 * scale - 8
        scale += 1
    elif convention == '71X':
        scale = 0.1 * spawnSequence
        if spawnSequence < -10:
            scale *= -4
            if spawnSequence > -81:
                scale += 6
            elif spawnSequence < -80:
                scale = 4 * scale - 90
        scale += 1
    elif convention == '47X':
        scale = spawnSequence
        lthn10 = spawnSequence < -10
        gthn71 = spawnSequence > -71
        gthn41 = spawnSequence > -41
        if lthn10:
            scale = 2 * (scale + 101)
            if gthn71:
                scale *= 3 if gthn41 else 2
        scale = 10 * scale + 100
        if lthn10:
            scale += 1000
            if gthn71:
                scale -= 1800 if gthn41 else 600
        scale *= 0.01                     # Halo Reach 100-based scale -> 1-based
    elif convention == '330X':
        scale = 100
        i = spawnSequence
        if spawnSequence < 0:
            i *= 5
            scale += i
            if spawnSequence <= -20:
                i = spawnSequence + 201
                if spawnSequence == -20:
                    scale = 1
        if spawnSequence < -20 or spawnSequence > 0:
            scale = recursive_330x(i, 32732 if team == 'RED' else 100)    # RED: cosmic scaling
        scale *= 0.01
    else:
        scale = 1
    return scale


# --- small helpers -----------------------------------------------------------------------------
def wrapText(text):
    lines = []
    for line in text.split('\n'):
        lines += textwrap.TextWrapper(width=60).wrap(text=line)
    return lines


def wrapTextPanel(self, text, scale=0.75):
    layout = self.layout.column(align=True)
    layout.scale_y = scale
    for wrapped in wrapText(text):
        layout.label(text=wrapped)


def lockObject(obj, scale=True, loc=False, rot=False):
    for i_ax in range(0, 3):
        obj.lock_scale[i_ax] = scale
        obj.lock_location[i_ax] = loc
        obj.lock_rotation[i_ax] = rot


_DUP_SUFFIX = re.compile(r'\.\d{3,}$')


def strip_duplicate_suffix(name):
    """``Block, 1x1.001`` -> ``Block, 1x1`` (Blender's duplicate suffix only)."""
    return _DUP_SUFFIX.sub('', name)


_suspended = [0]


class suspend_updates(object):
    """Context manager: the property ``update`` callbacks do nothing inside (bulk assignment on import)."""
    def __enter__(self):
        _suspended[0] += 1
        return self

    def __exit__(self, *exc):
        _suspended[0] -= 1
        return False


def _updates_suspended():
    return _suspended[0] > 0


def _scene_of(obj):
    scenes = obj.users_scene
    return scenes[0] if scenes else bpy.context.scene


# --- scale / colour / shape updates (all act on ``id_data``; 8.7 #2, #9) ------------------------
def is_scaled(obj, scene=None):
    scene = scene or _scene_of(obj)
    return ANVIL_SCALING and state.label_text(scene, obj.forge.gtLabel).upper() == 'SCALE'


def update_scale(obj, scene=None):
    """Set ``obj.scale`` from its spawn sequence when its label is SCALE, else 1. Acts on ``obj`` only (8.7 #2)."""
    scene = scene or _scene_of(obj)
    fp = obj.forge
    if is_scaled(obj, scene):
        s = spawnSeqToScale(fp.spawnSequence, scene.forge.scaleConvention, fp.team)
        obj.scale = (s, s, s)
    else:
        obj.scale = (1, 1, 1)


def apply_color_index(fp):
    col = fp.color
    if col == 'TEAM_COLOR':
        col = fp.team
    fp.colorIndex = COLOR_NUMBER[col]


def find_shape_helper(obj):
    """The ``<name> Shape`` child of ``obj`` (found through the parent link, so rename and duplicate are safe; 8.7 #9)."""
    fp = obj.forge
    name = fp.shapeObject
    helper = bpy.data.objects.get(name) if name else None
    if helper is not None and helper.parent == obj:
        return helper
    for child in obj.children:
        if child.get('mj_helper') == 'shape':
            return child
    return None


def _primary_collection(obj):
    colls = obj.users_collection
    return colls[0] if colls else bpy.context.scene.collection


def update_shape(obj):
    """(Re)build the shape helper child of ``obj`` from ``forge.shape`` and the dimensions (8.7 #6, #18)."""
    fp = obj.forge
    helper = find_shape_helper(obj)
    shape = fp.shape
    if shape == 'NONE':
        if helper is not None:
            bpy.data.objects.remove(helper, do_unlink=True)
            fp.shapeObject = ""
        return
    if helper is None:
        helper = bpy.data.objects.new("%s Shape" % obj.name, None)
        helper['mj_helper'] = 'shape'
        _primary_collection(obj).objects.link(helper)
        fp.shapeObject = helper.name
        helper.rotation_euler = Euler((0, 0, math.radians(90)))
        helper.show_instancer_for_viewport = helper.show_instancer_for_render = False
        helper.parent = obj
        lockObject(helper, True, True, True)
    coll = None
    if shape == 'BOX':
        coll = _shape_collection('Shape Box')
        helper.scale = (fp.width, fp.length, fp.top + fp.bottom)
    elif shape == 'CYLINDER':
        coll = _shape_collection('Shape Cylinder')
        d = fp.width * 2
        helper.scale = (d, d, fp.top + fp.bottom)
    if coll is not None:
        helper.empty_display_type = 'PLAIN_AXES'
        helper.empty_display_size = 1.0
        helper.instance_type = 'COLLECTION'
        if helper.instance_collection != coll:
            helper.instance_collection = coll
    else:                                 # sphere, or no shape model available: a plain empty drawn as the volume
        helper.instance_type = 'NONE'
        helper.instance_collection = None
        if shape == 'SPHERE':
            helper.empty_display_type = 'SPHERE'
            helper.empty_display_size = max(fp.width, 1e-4)      # radius = width
            helper.scale = (1, 1, 1)
        else:
            helper.empty_display_type = 'CUBE'
            helper.empty_display_size = 0.5                      # a unit cube, scaled to the volume above
    helper.location = (0, 0, 0 if shape == 'SPHERE' else (fp.top - fp.bottom) / 2)


def _shape_collection(name):
    coll = palette.find_collection(name)
    if coll is None:
        palette.ensure_palette()
        coll = palette.find_collection(name)
    return coll


def _upd_scale(self, context):
    if not _updates_suspended():
        update_scale(self.id_data)


def _upd_color(self, context):
    if _updates_suspended():
        return
    apply_color_index(self)
    obj = self.id_data
    if is_scaled(obj):                    # the 330X cosmic scale depends on the team
        update_scale(obj)


def _upd_shape(self, context):
    if not _updates_suspended():
        update_shape(self.id_data)


def _upd_other_info(self, context):
    if not _updates_suspended() and self.cachedType != 19 and self.otherInfoA < 0:
        self.otherInfoA = 0


# --- the gametype label enum (8.7 #8) -----------------------------------------------------------
_label_cache = {"key": None, "items": [(state.NO_LABEL, "No Label", "Default", 'NONE', 0)]}


def _label_items(self, context):
    """Enum items: ``NO_LABEL`` and ``L<i>`` per present label entry, text in original case.

    The returned list lives in a module global (Blender keeps references to the strings, B3). Item numbers
    are ``i + 1`` so a stored value stays valid when other entries come and go.
    """
    try:
        scene = context.scene
    except Exception:
        scene = None
    entries = state.label_entries(scene) if scene is not None else []
    key = tuple(entries)
    if _label_cache["key"] != key:
        items = [(state.NO_LABEL, "No Label", "Default", 'NONE', 0)]
        for index, text in entries:
            items.append((state.label_enum_id(index), text if text else "Label %d" % index,
                          "Gametype label %d" % index, 'NONE', index + 1))
        _label_cache["key"] = key
        _label_cache["items"] = items
    return _label_cache["items"]


# --- property groups -----------------------------------------------------------------------------
class ForgeObjectProps(bpy.types.PropertyGroup):
    __slots__ = ()                                      # silences register_class under --debug-python; adds no attribute
    teamEnum = [
        ('RED', "Red", ""),
        ('BLUE', "Blue", ""),
        ('GREEN', "Green", ""),
        ('ORANGE', "Orange", ""),
        ('PURPLE', "Purple", ""),
        ('YELLOW', "Yellow", ""),
        ('BROWN', "Brown", ""),
        ('PINK', "Pink", ""),
        ('NEUTRAL', "Neutral", ""),
    ]
    colorEnum = teamEnum + [('TEAM_COLOR', "Team", "")]

    shapeObject: StringProperty()                       # name hint of the shape child (find_shape_helper verifies the parent)
    objectType: IntProperty(default=-1)                 # imported type id; -1 = none (8.7 #12)
    cachedType: IntProperty(min=0, max=31)
    gtLabel: EnumProperty(name="Game Type Label", description="How the gametype interprets this object",
                          items=_label_items, default=0, update=_upd_scale)
    otherInfoA: IntProperty(min=-1, max=255, update=_upd_other_info)
    otherInfoB: IntProperty(min=0, max=255)

    physics: EnumProperty(name="Physics", description="Physics mode", default='PHASED', items=[
        ('NORMAL', "Normal", "Affected by gravity and movable", 'NONE', 0),
        ('FIXED', "Fixed", "Unaffected by gravity", 'NONE', 1),
        ('PHASED', "Phased", "Unaffected by gravity and collisionless", 'NONE', 2),
    ])
    team: EnumProperty(name="Team", description="Object team", items=teamEnum, default='NEUTRAL', update=_upd_color)
    color: EnumProperty(name="Color", description="Object color", items=colorEnum, default='TEAM_COLOR',
                        update=_upd_color)
    colorIndex: IntProperty(default=8)                  # read by the shaders of the object library: keep the name
    spawnSequence: IntProperty(name="Spawn Sequence", description="Gamemode phase at which the object will spawn",
                               min=-128, max=127, soft_min=-100, soft_max=100, update=_upd_scale)
    spawnTime: IntProperty(name="Spawn Time", description="Time in seconds before the object spawns or respawns "
                           "(0 is never)", min=0, soft_max=180, max=255)
    gameSpecific: BoolProperty(name="Game Specific", description="Should object exclusively spawn for current "
                               "gamemode. Changing this is refused at export until the placement flags are verified")
    placeAtStart: BoolProperty(name="Place At Start", description="Should object spawn at start. Changing this is "
                               "refused at export until the placement flags are verified", default=True)
    symmetry: EnumProperty(name="Symmetry", description="Gamemode symmetry. Changing this is refused at export "
                           "until the placement flags are verified", default='BOTH', items=[
        ('BOTH', "Both", "Present in symmetric and asymmetric gamemodes (default)", 'NONE', 0),
        ('SYMMETRIC', "Symmetric", "Present only in symmetric gamemodes", 'NONE', 1),
        ('ASYMMETRIC', "Asymmetric", "Present only in asymmetric gamemodes", 'NONE', 2),
        ('NEITHER', "Neither", "Present in neither kind of gamemode", 'NONE', 3),
    ])

    # The numbers are what a .blend stores. forge.py v0.9.9.2 numbered NONE 0, CYLINDER 1, BOX 2 by position, so those
    # three keep their numbers (a .blend saved by the old add-on must read the same shape); SPHERE is new and takes 3.
    # They are NOT the file's shape codes (0 none, 1 sphere, 2 cylinder, 3 box): SHAPE_TO_ENUM / SHAPE_FROM_ENUM map by
    # identifier. Physics (NORMAL 0, FIXED 1, PHASED 2) and symmetry (BOTH 0, SYMMETRIC 1, ASYMMETRIC 2, NEITHER 3 new)
    # keep the old position numbers too.
    shape: EnumProperty(name="Shape", description="Area shape", default='NONE', update=_upd_shape, items=[
        ('NONE', "None", "", 'NONE', 0),
        ('CYLINDER', "Cylinder", "", 'NONE', 1),
        ('BOX', "Box", "", 'NONE', 2),
        ('SPHERE', "Sphere", "Radius only (the radius is the width)", 'NONE', 3),
    ])
    width: FloatProperty(name="Width", description="", unit='LENGTH', min=0, soft_max=100.9, max=200, update=_upd_shape)
    length: FloatProperty(name="Length", description="", unit='LENGTH', min=0, soft_max=100.9, max=200,
                          update=_upd_shape)
    top: FloatProperty(name="Top", description="Distance to top from center", unit='LENGTH', min=0, soft_max=100.9,
                       max=200, update=_upd_shape)
    bottom: FloatProperty(name="Bottom", description="Distance to bottom from center", unit='LENGTH', min=0,
                          soft_max=100.9, max=200, update=_upd_shape)


class ForgeCollectionProps(bpy.types.PropertyGroup):
    __slots__ = ()

    def iconsEnum(self, context):
        return _icon_items()

    icon: EnumProperty(name="Icon", description="Icon used in menus (the Add menu uses a fixed icon table)",
                       items=iconsEnum, default=0)


_icon_cache = []


def _icon_items():
    """All icon identifiers as enum items, built once (strings must outlive the call, B3)."""
    if not _icon_cache:
        icons = bpy.types.UILayout.bl_rna.functions['prop'].parameters['icon'].enum_items.keys()
        for i, ico in enumerate(icons):
            _icon_cache.append((ico, "", ico, ico, i))
    return _icon_cache


def _upd_scale_convention(self, context):
    scene = self.id_data
    for obj in scene.objects:
        if obj.get('isForgeObject'):
            update_scale(obj, scene)


class ForgeSceneProps(bpy.types.PropertyGroup):
    __slots__ = ()
    scaleConvention: EnumProperty(
        name="Scale Convention",
        description="Gametype object scaling convention, or how to interpret the spawn sequence number.",
        # The numbers are what a .blend stores. They are forge.py v0.9.9.2's (the shipped add-on numbered the items by
        # position: 1X 0, 33X 1, 71X 2, 47X 3, 330X 4), pinned here so that a reordering can never shift them. The older
        # Addon/mjolnir.py of the repository (33X 0, 71X 1, 47X 2, 330X 3, no 1X) never shipped in a release of its own and
        # is the minority; files saved by forge.py before 0.9.9.0 (which had no 1X either) stored the same shifted numbers
        # and read one item up, a change the maintainer's own 4eddf40 made and that no reader can repair. docs/mvar/notes/G6.md.
        items=(('1X', "1X", "Disable scaling", 'NONE', 0),
               ('33X', "33X", "Trusty's Old", 'NONE', 1),
               ('71X', "71X", "Rabid MidgetMan's", 'NONE', 2),
               ('47X', "47X*", "Anvil Editor Default (Trusty's New)", 'NONE', 3),
               ('330X', "330X", "Tx Titan Scale. Max scale of 327.34", 'NONE', 4)),
        default='47X', update=_upd_scale_convention)                      # 8.7 #3: the documented default
    allowUnverifiedRotation: BoolProperty(
        name="Allow unverified rotation export",
        description="Write rotations and new objects. The orientation convention has never been checked against "
                    "a real map variant (SPEC 4.8); leave off to refuse any rotation change",
        default=False)
    keepUnrecognisedObjects: BoolProperty(
        name="Keep objects this tool does not recognise",
        description="Export imported objects whose id is not in the stock table of the map unchanged instead of "
                    "refusing the export",
        default=False)


# --- import: object creation and record application -----------------------------------------------
def create_forge_object(context, item_name, slot=None, coll_index=None):
    """An Empty for one Forge object: the palette model instanced when the library has one, else an arrow."""
    name = item_name if slot is None else "%d - %s" % (slot, item_name)
    blobj = bpy.data.objects.new(name, None)
    (context.collection or context.scene.collection).objects.link(blobj)
    blobj['isForgeObject'] = True
    lockObject(blobj)
    coll = coll_index.get(item_name) if coll_index is not None else palette.find_collection(item_name)
    if coll is not None:
        blobj.instance_collection = coll
        blobj.instance_type = 'COLLECTION'
        blobj.empty_display_size = 0.0001
    else:
        blobj.empty_display_type = 'ARROWS'
        blobj.empty_display_size = 0.5
        if slot is None:                   # added without a model: remember the chosen type for export
            blobj['mj_type_name'] = item_name
    if slot is None:
        scene = context.scene
        defaults = provider.new_object_defaults(state.map_name(scene) or 'Forge World', item_name,
                                                state.template_bytes(scene))
        if defaults:
            blobj['mj_type_name'] = item_name
            fp = blobj.forge
            with suspend_updates():
                fp.objectType = defaults['id']
                fp.cachedType = defaults['cached_type']
                fp.spawnTime = defaults['respawn']
                fp.physics = PHYSICS_TO_ENUM[defaults['physics']]
                fp.symmetry = SYMMETRY_TO_ENUM[defaults['symmetry']]
                fp.placeAtStart = defaults['place_at_start']
                fp.gameSpecific = defaults['game_specific']
                fp.shape = SHAPE_TO_ENUM[defaults['shape']]
                fp.width, fp.length = defaults['width'], defaults['length']
                fp.top, fp.bottom = defaults['top'], defaults['bottom']
                fp.otherInfoA, fp.otherInfoB = defaults['other_a'], defaults['other_b']
            if defaults['shape']:
                update_shape(blobj)
    return blobj


def orthonormal_axes(forward, up):
    """``(right, forward, up)``: an orthonormal frame from a record's ``forward`` / ``up``.

    ``up`` is the stored axis (SPEC 4.6: the file keeps the up code, forward is derived from it), so it is only
    normalised; ``forward`` is made perpendicular to it. A ``forward`` that is zero or parallel to ``up`` gets any
    perpendicular direction; a zero ``up`` becomes +Z. ``right = forward x up`` (the convention of forge.py).
    """
    u = Vector(up)
    if u.length < 1e-9:
        u = Vector((0.0, 0.0, 1.0))
    u.normalize()
    f = Vector(forward)
    f = f - u * f.dot(u)
    if f.length < 1e-6:
        f = u.cross(Vector((1.0, 0.0, 0.0)))
        if f.length < 1e-6:
            f = u.cross(Vector((0.0, 1.0, 0.0)))
    f.normalize()
    return f.cross(u), f, u


def basis_matrix(forward, up, position):
    """World matrix with the columns ``(right, forward, up, position)`` (rotation re-orthonormalised)."""
    right, fwd, upv = orthonormal_axes(forward, up)
    pos = Vector(position)
    return Matrix(((right.x, fwd.x, upv.x, pos.x),
                   (right.y, fwd.y, upv.y, pos.y),
                   (right.z, fwd.z, upv.z, pos.z),
                   (0, 0, 0, 1)))


# --- pose bookkeeping: "did the user move or turn this object?" (SPEC 4.8 / 4.9, glue half) ----------------------
# The library compares what it is handed with the pose it decoded (position within POS_TOL, forward and up within
# ANG_TOL = 1e-4 rad) and keeps the original raw bits when nothing changed. Blender cannot always reproduce a
# decoded pose exactly: ``matrix_world`` is recomposed from location / rotation / scale on the next depsgraph
# update, which re-orthonormalises the rotation (a forward / up pair that is not perpendicular drifts by far more
# than 1e-4 rad) and rounds to float32. So the glue never asks "is the object where the library put it?" but
# "is it where Blender had it right after import?": two values read through the SAME code path
# (:func:`pose_from_matrix` on :func:`world_matrix`, after a view-layer update). Unchanged parts are then
# handed back as the record's own numbers (``mj_pose``), so the library sees no difference at all.
POSE_KEY = 'mj_pose'                # the record's position, forward, up (9 floats, doubles: exact)
BASE_KEY = 'mj_base'                # the same pose as read back from Blender after import (9 floats)
POSE_POS_TOL = 5e-4                 # Blender-side "not moved" (below the library's own POS_TOL >= 1e-3)
POSE_ANG_TOL = 5e-5                 # Blender-side "not turned" (half the library's ANG_TOL = 1e-4 rad)


AXIS_SNAP = 1e-6                    # a direction component this small is float32 noise, not an angle (1e-6 rad = 0.00006 deg)


def snap_axis(vector):
    """``vector`` as three floats with float32 noise removed and renormalised.

    A rotation by exactly -90 degrees about Z leaves the stored forward at ``(1, -4.4e-8, 0)`` (``cos`` of the float32
    ``-pi/2``), a yaw of ``-4.4e-8`` rad: the quantiser FLOORS the angle, so that noise sends it to the cell below
    (raw 8191) instead of the cell that starts at yaw 0 (raw 8192, SPEC 4.4 / 4.7). Every quarter turn is a cell edge
    (16384 cells), so every axis-aligned rotation a user types would otherwise be written one cell off. Components
    below ``AXIS_SNAP`` are set to zero (this is far below a cell, 3.8e-4 rad, and below the 5e-5 rad change tolerance)
    and the vector is normalised again, so ``(1, -4.4e-8, 0)`` becomes exactly ``(1, 0, 0)``.
    """
    x, y, z = (0.0 if abs(float(c)) < AXIS_SNAP else float(c) for c in vector)
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 0.0:
        return (float(vector[0]), float(vector[1]), float(vector[2]))
    return (x / length, y / length, z / length)


def pose_from_matrix(matrix):
    """``(position, forward, up)`` as three 3-tuples of floats; forward and up are normalised (scale is ignored) and
    free of float32 noise (:func:`snap_axis`)."""
    position = matrix.col[3].xyz
    return ((float(position.x), float(position.y), float(position.z)),
            snap_axis(matrix.col[1].xyz.normalized()),
            snap_axis(matrix.col[2].xyz.normalized()))


def _flat(pose):
    return [float(c) for part in pose for c in part]


def _pose_prop(obj, key):
    """The three 3-tuples stored in custom property ``key`` of ``obj``, or ``None`` (absent or malformed)."""
    raw = obj.get(key)
    if raw is None:
        return None
    try:
        values = [float(v) for v in raw]
    except (TypeError, ValueError):
        return None
    if len(values) != 9:
        return None
    return (tuple(values[0:3]), tuple(values[3:6]), tuple(values[6:9]))


def _distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _angle_between(a, b):
    """Angle in radians between two 3-vectors (``atan2`` form: exact for tiny angles); 0 for a zero vector."""
    cross = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.atan2(math.sqrt(sum(c * c for c in cross)), sum(x * y for x, y in zip(a, b)))


def legacy_native_rotation(obj, current):
    """Resolve untouched rotations from an older .blend without exporting its display-only guess."""
    if obj.get('mj_orientation_basis') == 'native':
        return None
    scene = _scene_of(obj)
    stored = state.get(scene)
    if stored is None or stored.get('hypothesis', {}).get('orientation_basis') == 'native':
        return None
    base = _pose_prop(obj, BASE_KEY)
    if base is None or _pose_prop(obj, POSE_KEY) is None:
        return None
    if _angle_between(current[1], base[1]) > POSE_ANG_TOL or _angle_between(current[2], base[2]) > POSE_ANG_TOL:
        return None
    return provider.imported_native_orientation(state.template_bytes(scene), obj.get('mj_slot'),
                                                obj.get('mj_raw'), obj.get('mj_raw_bits'))


def exported_pose(obj, current):
    """``(position, forward, up)`` to hand to the library for ``obj``, whose Blender-side pose is ``current``.

    Position and orientation are judged separately against the baseline captured at import: a part that did not
    change is replaced by the record's own numbers, a part that did change is handed over as it is now. Orientation
    is one quantity (forward and up together). Without a baseline (an object not made by the importer) the current
    pose is returned.
    """
    base = _pose_prop(obj, BASE_KEY)
    original = _pose_prop(obj, POSE_KEY)
    if base is None or original is None:
        return current
    position = original[0] if _distance(current[0], base[0]) <= POSE_POS_TOL else current[0]
    turned = (_angle_between(current[1], base[1]) > POSE_ANG_TOL or _angle_between(current[2], base[2]) > POSE_ANG_TOL)
    forward, up = (current[1], current[2]) if turned else (original[1], original[2])
    if not turned:
        native = legacy_native_rotation(obj, current)
        if native is not None:
            forward, up = native
    return position, forward, up


def capture_pose_baselines(context, objs):
    """Store ``mj_base`` on every object of ``objs`` (call once after the import created them all).

    The view layer is updated first so that ``matrix_world`` holds what the depsgraph makes of the object (not the
    matrix that was assigned), and the pose is read through :func:`world_matrix` exactly as the export reads it.
    """
    view_layer = context.view_layer
    view_layer.update()
    excluded = _excluded_collection_names(view_layer)
    for obj in objs:
        obj[BASE_KEY] = _flat(pose_from_matrix(world_matrix(obj, excluded)))


def apply_record(obj, rec, scene):
    """Set transform, ``forge`` properties and identity props of ``obj`` from an ``ObjectRecord`` (8.7 #2, #4, #6, #7, #8)."""
    obj.matrix_world = basis_matrix(rec.forward, rec.up, rec.position)
    obj[POSE_KEY] = _flat((rec.position, rec.forward, rec.up))
    fp = obj.forge
    with suspend_updates():
        fp.objectType = rec.type_id if rec.type_id >= 0 else -1
        fp.cachedType = _clamp(rec.cached_type, 0, 31)
        fp.gtLabel = state.label_enum_id(rec.label_index)
        fp.otherInfoA = _clamp(rec.other_a, -1 if rec.cached_type == 19 else 0, 255)
        fp.otherInfoB = _clamp(rec.other_b, 0, 255)
        fp.physics = PHYSICS_TO_ENUM.get(rec.physics, 'NORMAL')
        fp.team = team_to_enum(rec.team)
        fp.color = color_to_enum(rec.color)
        fp.symmetry = SYMMETRY_TO_ENUM.get(rec.symmetry, 'BOTH')
        fp.spawnSequence = _clamp(rec.spawn_sequence, -128, 127)
        fp.spawnTime = _clamp(rec.spawn_time, 0, 255)
        fp.placeAtStart = bool(rec.place_at_start)
        fp.gameSpecific = bool(rec.game_specific)
        fp.shape = SHAPE_TO_ENUM.get(rec.shape, 'NONE')
        fp.width = rec.width
        fp.length = rec.length
        fp.top = rec.top
        fp.bottom = rec.bottom
    apply_color_index(fp)
    update_shape(obj)
    if is_scaled(obj, scene):
        update_scale(obj, scene)           # obj.scale set directly, whatever is selected (8.7 #2)
    obj['mj_slot'] = int(rec.slot)
    obj['mj_raw'] = bytes(rec.raw)
    obj['mj_raw_bits'] = int(rec.raw_bits)
    obj['mj_parent_slot'] = int(rec.parent_slot)
    obj['mj_physics'] = int(rec.physics)    # raw 2-bit value: the enum cannot show the unused value 2 (8.7 #7)
    obj['mj_name'] = obj.name


def create_import_object(context, rec, scene, coll_index=None):
    """One imported slot -> one Empty named ``"<slot> - <type name>"`` (plus the loadout-camera child)."""
    obj = create_forge_object(context, rec.type_name, rec.slot, coll_index)
    try:
        apply_record(obj, rec, scene)
        if rec.type_name == "Initial Loadout Camera":
            camera_data = bpy.data.cameras.new("Initial Loadout Camera")
            cam = bpy.data.objects.new("Initial Loadout Camera", camera_data)
            (context.collection or context.scene.collection).objects.link(cam)
            cam['mj_helper'] = 'camera'
            cam.parent = obj
            cam.rotation_euler = Euler((math.radians(90), 0, 0))
            lockObject(cam, True, True, True)
    except Exception:
        remove_with_helpers(obj)             # a failed slot leaves no half-built object behind (it would export as new)
        raise
    return obj


def imported_objects(scene):
    """Objects of ``scene`` that carry a slot (imported, or duplicates of imported objects)."""
    return [o for o in scene.objects if 'mj_slot' in o]


def remove_with_helpers(obj):
    """Delete ``obj`` and its shape / loadout-camera helper children (8.7 #17)."""
    for child in list(obj.children):
        if child.get('mj_helper') in ('shape', 'camera'):
            data = child.data
            bpy.data.objects.remove(child, do_unlink=True)
            if data is not None and getattr(data, 'users', 1) == 0 and isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
    helper = find_shape_helper(obj)
    if helper is not None:
        bpy.data.objects.remove(helper, do_unlink=True)
    bpy.data.objects.remove(obj, do_unlink=True)


# --- export: scene -> ExportObject -------------------------------------------------------------------
def forge_type_name(obj):
    """Display name of the instanced palette collection (``.name``, suffix ``.NNN`` stripped; 8.7 #1), else ''."""
    coll = obj.instance_collection
    if coll is not None:
        return strip_duplicate_suffix(coll.name)
    return str(obj.get('mj_type_name', ''))


def is_array_source(obj):
    parent = obj.parent
    return parent is not None and parent.instance_type in ARRAY_PARENT_TYPES


def _excluded_collection_names(view_layer):
    """``name_full`` of every collection excluded in the view layer, children of excluded ones included."""
    out = set()

    def walk(layer_coll, excluded):
        excluded = excluded or layer_coll.exclude
        if excluded:
            out.add(layer_coll.collection.name_full)
        for child in layer_coll.children:
            walk(child, excluded)

    walk(view_layer.layer_collection, False)
    return out


def _unevaluated(obj, excluded):
    """True when the depsgraph does not evaluate ``obj`` (``hide_viewport`` or only in excluded collections)."""
    if obj.hide_viewport:
        return True
    colls = obj.users_collection
    return bool(colls) and all(c.name_full in excluded for c in colls)


def _manual_world(obj):
    """World matrix from the local transforms (for objects the depsgraph does not evaluate; constraints ignored)."""
    parent = obj.parent
    if parent is None:
        return obj.matrix_basis.copy()
    if obj.parent_type != 'OBJECT':
        return obj.matrix_world.copy()
    return _manual_world(parent) @ obj.matrix_parent_inverse @ obj.matrix_basis


def world_matrix(obj, excluded):
    """``matrix_world`` where it is trustworthy, else the matrix rebuilt from the local transforms."""
    node = obj
    while node is not None:
        if _unevaluated(node, excluded):
            return _manual_world(obj)
        node = node.parent
    return obj.matrix_world.copy()


def is_hidden(obj, excluded):
    try:
        eye = obj.hide_get()
    except RuntimeError:
        eye = False
    return bool(eye or obj.hide_viewport or _unevaluated(obj, excluded))


class ForgeItems(object):
    """What the scene holds for export: array instances, plain objects, unevaluated array sources."""
    def __init__(self):
        self.array_sources = []          # [(source object, [instance matrix, ...])] in first-seen order
        self.plain = []                  # [object]
        self.unevaluated = []            # [array source object with no evaluated instance]
        self.excluded = set()

    def count(self):
        return len(self.plain) + sum(len(m) for _s, m in self.array_sources)


def collect_forge_items(scene, depsgraph, view_layer=None):
    """Pass B (array instances from the depsgraph) then pass A (``scene.objects``, hidden ones included), SPEC 8.5."""
    items = ForgeItems()
    view_layer = view_layer or bpy.context.view_layer
    items.excluded = _excluded_collection_names(view_layer)
    seen = {}
    order = []
    for inst in depsgraph.object_instances:                       # pass B
        if not inst.is_instance:
            continue
        evaluated = inst.object
        if not evaluated.get('isForgeObject'):
            continue
        source = evaluated.original
        if not is_array_source(source):
            continue
        key = source.name_full
        if key not in seen:
            seen[key] = (source, [])
            order.append(key)
        seen[key][1].append(inst.matrix_world.copy())
    items.array_sources = [seen[k] for k in order]
    for obj in scene.objects:                                      # pass A
        if not obj.get('isForgeObject') or obj.name_full in seen:
            continue
        if is_array_source(obj):
            items.unevaluated.append(obj)
        else:
            items.plain.append(obj)
    return items


def count_forge_objects(scene, depsgraph, view_layer=None):
    return collect_forge_items(scene, depsgraph, view_layer).count()


def _issue(P, code, severity, message, obj=None, slot=None):
    return P.Issue(code, severity, message, slot, obj.name if obj is not None else None)


def to_export_object(P, obj, matrix, name=None, claim_slot=True, hidden=False, from_array=False):
    """Blender object -> ``ExportObject`` built through the provider (never an api import, never ``isinstance``).

    Returns ``(export_object, problems)``; ``problems`` are glue-level ``Issue`` objects (``E_MIRRORED``,
    ``E_OBJ_NO_TYPE``). Scale is not exported (columns are normalised); the property values are read as they are.
    An object that claims a slot and has an import baseline hands back the record's own position / forward / up for
    every part the user did not change (:func:`exported_pose`), so the library never sees Blender-side drift.
    """
    fp = obj.forge
    problems = []
    m3 = matrix.to_3x3()
    pose = pose_from_matrix(matrix)
    if claim_slot:
        pose = exported_pose(obj, pose)           # unchanged parts keep the record's own numbers (see POSE_KEY)
    position, forward, up = pose
    if m3.determinant() < 0:
        problems.append(_issue(P, "E_MIRRORED", "error", "Object '%s' has a mirrored (negative scale) transform, "
                               "which cannot be exported." % obj.name, obj))
    type_name = forge_type_name(obj)
    hint = fp.objectType if fp.objectType >= 0 else -1
    if not type_name and hint < 0 and 'mj_slot' not in obj:
        # an object that came from the file keeps whatever the file says (the library decides); one that did not
        # (Convert To Forge Object on a plain Blender object) has no type: the old export wrote type 0 (8.7 #12)
        problems.append(_issue(P, "E_OBJ_NO_TYPE", "error", "Object '%s' has no Forge object type. Add it with "
                               "Add > Forge Object, or duplicate an imported object." % obj.name, obj))
    slot = obj.get('mj_slot') if claim_slot else None
    raw = obj.get('mj_raw') if claim_slot else None
    bits = obj.get('mj_raw_bits') if claim_slot else None
    physics = PHYSICS_FROM_ENUM.get(fp.physics, 3)
    raw_physics = obj.get('mj_physics')
    if raw_physics is not None and PHYSICS_TO_ENUM.get(raw_physics, 'NORMAL') == fp.physics:
        physics = int(raw_physics)         # unchanged: hand back the file's own value (even the unused 2)
    eo = P.ExportObject(
        name=name or obj.name,
        slot=int(slot) if slot is not None else None,
        token_raw=bytes(raw) if raw is not None else None,
        token_bits=int(bits) if bits is not None else None,
        name_matches_import=bool(claim_slot and obj.name == obj.get('mj_name')),
        type_name=type_name,
        type_id_hint=int(hint),
        position=position, forward=forward, up=up,
        shape=SHAPE_FROM_ENUM.get(fp.shape, 0),
        width=float(fp.width), length=float(fp.length), top=float(fp.top), bottom=float(fp.bottom),
        spawn_sequence=int(fp.spawnSequence), spawn_time=int(fp.spawnTime),
        cached_type=int(fp.cachedType),
        label_index=state.label_index_from_enum(fp.gtLabel),
        physics=physics,
        symmetry=SYMMETRY_FROM_ENUM.get(fp.symmetry, 3),
        place_at_start=bool(fp.placeAtStart),
        game_specific=bool(fp.gameSpecific),
        team=COLOR_NUMBER.get(fp.team, 8),
        color=-1 if fp.color == 'TEAM_COLOR' else COLOR_NUMBER.get(fp.color, -1),
        other_a=int(fp.otherInfoA), other_b=int(fp.otherInfoB),
        hidden=bool(hidden), from_array=bool(from_array),
    )
    return eo, problems


# --- panels ---------------------------------------------------------------------------------------------
def region_width(region_type):
    try:
        for region in bpy.context.area.regions:
            if region.type == region_type:
                return region.width
    except AttributeError:                 # no area (background mode)
        pass
    return 500


def drawForgeObjectProperties(self, context, region):
    layout = self.layout
    width = region_width(region)
    wide = width > 200
    layout.use_property_split = wide
    obj = context.selected_objects[0]
    fprops = obj.forge

    locRotLay = layout if wide else layout.column(align=True)
    locRotLay.prop(obj, 'location')
    locRotLay.prop(obj, 'rotation_euler', text="Rotation")

    if wide:
        layout.prop(obj, 'instance_collection', text="Object Type")
    else:
        col = layout.column(align=True)
        col.label(text="Object Type:")
        col.prop(obj, 'instance_collection', text="")
    if 'mj_slot' in obj:
        layout.label(text="Map slot: %d" % obj['mj_slot'])
    if fprops.cachedType == 0:
        defaults = provider.new_object_defaults(state.map_name(context.scene) or 'Forge World',
                                                forge_type_name(obj), state.template_bytes(context.scene))
        if defaults and defaults['native_verified'] and defaults['cached_type'] == 1:
            layout.operator('forge.enable_native_settings', text='Enable Weapon Settings')

    col = layout.column(align=True)
    col.use_property_split = width > 160
    col.prop(fprops, 'physics')
    col.prop(fprops, 'team')
    col.prop(fprops, 'color')
    col.prop(fprops, 'symmetry')

    if fprops.cachedType == 1:
        col = layout.column(align=True)
        col.label(text="Weapon")
        col.prop(fprops, 'otherInfoA', text="Spare Clips")
    elif fprops.cachedType in TELEPORTER_TYPES:
        col = layout.column(align=True)
        col.label(text="Teleporter")
        col.prop(fprops, 'otherInfoA', text="Channel")
        col.prop(fprops, 'otherInfoB', text="Flags")
    elif fprops.cachedType == 19:
        col = layout.column(align=True)
        col.label(text="Location Name")
        col.prop(fprops, 'otherInfoA', text="Name Index (-1 = None)")

    col = layout.column(align=True)
    if wide:
        col.prop(fprops, 'spawnSequence')
        col.prop(fprops, 'spawnTime')
    else:
        col.label(text="Spawn")
        col.prop(fprops, 'spawnSequence', text="Sequence")
        col.prop(fprops, 'spawnTime', text="Time")

    col = layout.column(align=True)
    col.prop(fprops, 'placeAtStart')
    col.prop(fprops, 'gameSpecific')

    shape = fprops.shape
    col = layout.column(align=True)
    col.prop(fprops, 'shape')
    col2 = col.column(align=True)
    col2.enabled = shape != 'NONE'
    col2.prop(fprops, 'width', text=('Width' if shape == 'BOX' else 'Radius'))
    if shape == 'BOX':
        col2.prop(fprops, 'length')
    if shape != 'SPHERE':
        col2.prop(fprops, 'top')
        col2.prop(fprops, 'bottom')

    col = layout.column(align=True)
    col.prop(fprops, 'gtLabel')
    if is_scaled(obj, context.scene):
        col.prop(context.scene.forge, 'scaleConvention')


def pollForgePanel(self, context):
    objs = context.selected_objects
    if objs:
        return objs[0].get('isForgeObject', False)
    return False


class ForgeObjectPanel(bpy.types.Panel):
    bl_label = "Forge Properties"
    bl_idname = 'SCENE_PT_forge_object'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'

    @classmethod
    def poll(cls, context):
        return pollForgePanel(cls, context)

    def draw(self, context):
        drawForgeObjectProperties(self, context, 'WINDOW')


class ForgeObjectPanel_Sidebar(bpy.types.Panel):
    bl_label = "Forge Properties"
    bl_idname = 'SCENE_PT_forge_object_sidebar'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Forge'
    bl_context = 'objectmode'

    @classmethod
    def poll(cls, context):
        return pollForgePanel(cls, context)

    def draw(self, context):
        drawForgeObjectProperties(self, context, 'UI')


class ForgeCollectionPanel(bpy.types.Panel):
    bl_label = "Forge Collection"
    bl_idname = 'SCENE_PT_forge_collection'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        collection = context.collection
        if collection is None:
            layout.label(text="No active collection")
            return
        if collection.library is not None:                           # 8.7 #15: linked data is read-only
            layout.label(text="Linked collection: read-only", icon='LIBRARY_DATA_DIRECT')
            layout.enabled = False
        layout.prop(collection.forge, 'icon')


class ForgeScenePanel(bpy.types.Panel):
    bl_label = "Forge Scene"
    bl_idname = 'SCENE_PT_forge_scene'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'scene'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        scene = context.scene
        sceneProps = scene.forge
        layout.prop(sceneProps, 'scaleConvention')
        box = layout.box()
        st = state.get(scene)
        if st is None:
            box.label(text="No map variant imported (File > Import)")
        else:
            box.label(text="Map: %s (%s)" % (st.get("map_name") or "unknown map", st.get("map_id_hex", "")))
            box.label(text="Source: %s" % st.get("source_name", ""))
            box.label(text="Slots at import: %d / %d" % (st.get("occupied_at_import", 0), MAX_OBJECTS))
            hyp = st.get("hypothesis")
            if hyp is not None:
                parts = ["%s=%s" % (k, hyp[k]) for k in ("type19", "guid", "length_class") if k in hyp]
                box.label(text="Layout: %s" % (", ".join(parts) or "n/a"))
            box.label(text="Hash: %s" % st.get("hash_flavour", ""))
            failed = list(st.get("failed_slots", []))
            if failed:
                box.label(text="Not imported (left unchanged on export): slots %s" % ", ".join(str(s) for s in failed[:12])
                          + (" ..." if len(failed) > 12 else ""), icon='ERROR')
                nonstock = state.failed_nonstock(scene)
                if nonstock:
                    box.label(text="Not stock objects: slots %s. Export is refused unless \"Keep objects this tool does not "
                                   "recognise\" is ticked" % ", ".join(str(n) for n in sorted(nonstock)[:12]), icon='ERROR')
        layout.prop(sceneProps, 'allowUnverifiedRotation')
        layout.prop(sceneProps, 'keepUnrecognisedObjects')


# --- operators --------------------------------------------------------------------------------------------
class ConvertForge(Operator):
    """Set if object is exported to the map variant"""
    bl_idname = 'object.convert_forge'
    bl_label = "Convert Forge Object"

    isForgeObject: BoolProperty()

    def execute(self, context):
        for obj in context.selected_objects:
            obj['isForgeObject'] = self.isForgeObject
        return {'FINISHED'}


def convertForgeMenuItem(self, context):
    active = context.active_object
    if active is None:
        return
    isForge = active.get('isForgeObject', False)
    if isForge:
        op = self.layout.operator(ConvertForge.bl_idname, icon='REMOVE', text="Convert To Blender Object")
    else:
        op = self.layout.operator(ConvertForge.bl_idname, icon='ADD', text="Convert To Forge Object")
    op.isForgeObject = not isForge


def arrayModifier(context, type, count=3, offset=(1, 0, 0), rotation=(0, 0, 0), curveLen=5):
    srcObj = context.active_object
    loc = srcObj.location
    size = 1

    coll = srcObj.instance_collection
    if coll is not None:
        name = coll.name
        for inst_o in coll.objects:
            s = inst_o.dimensions.y
            if s > size:
                size = s
    else:
        name = srcObj.name

    bpy.ops.mesh.primitive_plane_add(enter_editmode=False, align='WORLD', location=loc, size=1)
    arrObj = masterParent = context.object
    arrObj.name = "%s Array" % name
    arrObj.instance_type = 'FACES'
    arrObj.show_instancer_for_viewport = arrObj.show_instancer_for_render = False
    arrObj.select_set(True)

    bpy.ops.object.modifier_add(type='ARRAY')
    mod = arrObj.modifiers["Array"]
    mod.show_on_cage = True
    mod.use_relative_offset = False

    if type != 'CONST':
        parentObj = masterParent = bpy.data.objects.new("%s Array Holder" % name, None)
        context.collection.objects.link(parentObj)
        parentObj.location = loc
        parentObj.empty_display_size = 2
        arrObj.parent = parentObj
        arrObj.location = (0, 0, 0)
    if type == 'OBJECT':
        offsetObj = bpy.data.objects.new("%s Array Offset" % name, None)
        context.collection.objects.link(offsetObj)
        offsetObj.empty_display_size = size
        offsetObj.location = offset
        offsetObj.rotation_euler = rotation
        lockObject(offsetObj)
        offsetObj.parent = parentObj
        offsetObj.select_set(True)

        mod.use_constant_offset = False
        mod.use_object_offset = True
        mod.offset_object = offsetObj
    else:
        mod.use_constant_offset = True
        mod.constant_offset_displace = offset
    if type == 'CURVE':
        bpy.ops.object.modifier_add(type='CURVE')
        cMod = arrObj.modifiers["Curve"]
        cMod.show_on_cage = cMod.show_in_editmode = True

        bpy.ops.curve.primitive_bezier_curve_add(enter_editmode=False, align='WORLD', location=(0, 0, 0),
                                                 radius=curveLen)
        curve = bpy.context.object
        curve.name = "%s Curve" % name
        curve.parent = parentObj
        curve.select_set(True)
        lockObject(curve)
        curveData = curve.data
        curveData.twist_mode = 'Z_UP'
        curveData.use_deform_bounds = curve.show_in_front = True

        mod.fit_type = 'FIT_CURVE'
        mod.curve = curve
        cMod.object = curve

        arrObj.select_set(True)
    else:
        mod.count = count

    masterParent.rotation_euler = srcObj.rotation_euler

    srcObj.parent = arrObj
    srcObj.location = (0, 0, 0)
    srcObj.rotation_euler = (0, 0, 0)
    srcObj.display_type = 'BOUNDS'
    srcObj.select_set(True)
    if type != 'CONST':
        parentObj.select_set(True)


class SetupArray(Operator):
    """Setup array (repeated object duplication) for forge object"""
    bl_idname = 'object.setup_array'
    bl_label = "Setup Array"
    bl_options = {'REGISTER', 'UNDO'}

    type: EnumProperty(name="Type", description="Array modifier mode", default='CONST', items=[
        ('CONST', "Linear", "Simple XYZ offset from the modifier panel", 'MOD_ARRAY', 0),
        ('OBJECT', "Object", "Advanced XYZ offset and rotation from an object", 'MOD_TINT', 1),
        ('CURVE', "Curve", "Place objects along curve", 'MOD_CURVE', 2),
    ])
    count: IntProperty(name="Count", description="Number of duplicated objects", default=3, min=1, max=MAX_OBJECTS)
    offset: FloatVectorProperty(name="Offset", default=(1, 0, 0))
    rotation: FloatVectorProperty(name="Rotation", default=(0, 0, 0))
    size: FloatProperty(name="Size", description="Size of curve", default=5, min=0)

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        rot = self.rotation
        arrayModifier(context, self.type, self.count, self.offset,
                      (math.radians(rot[0]), math.radians(rot[1]), math.radians(rot[2])), self.size)
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, 'type')
        if self.type != 'CURVE':
            layout.prop(self, 'count')
        layout.prop(self, 'offset')
        if self.type == 'OBJECT':
            layout.prop(self, 'rotation')
        if self.type == 'CURVE':
            layout.prop(self, 'size')


def setupArrayMenuItem(self, context):
    self.layout.operator(SetupArray.bl_idname, icon='MOD_ARRAY')


class ErrorMessage(Operator):
    """Error message (runtime errors only; never called from register())"""
    bl_idname = 'forge.error'
    bl_label = "Error"

    message: bpy.props.StringProperty()
    url: bpy.props.StringProperty()

    def invoke(self, context, event):
        print("Error: " + self.message + "\n")
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        wrapTextPanel(self, self.message)
        if self.url != "":
            layout = self.layout.column(align=True)
            layout.operator_context = 'INVOKE_DEFAULT'
            op = layout.operator('wm.url_open', text="Open Webpage")
            op.url = self.url

    def execute(self, context):
        return {'CANCELLED'}


class ScaleObjects(Operator):
    """Scale multiple objects as one"""
    bl_idname = 'forge.scale_objects'
    bl_label = "Scale Forge Objects"
    bl_options = {'REGISTER', 'UNDO'}

    seq: IntProperty(name="Spawn Sequence (Scale)", default=0, min=-128, max=127, soft_min=-100, soft_max=100)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects) and state.enum_id_for_text(context.scene, 'SCALE') is not None

    def execute(self, context):
        scene = context.scene
        label_id = state.enum_id_for_text(scene, 'SCALE')
        scale = spawnSeqToScale(self.seq, scene.forge.scaleConvention)
        for blobj in context.selected_objects:
            if not blobj.get('isForgeObject'):
                continue
            fobj = blobj.forge
            fobj.gtLabel = label_id            # the update callbacks act on this object only (8.7 #2)
            fobj.spawnSequence = self.seq
            update_scale(blobj, scene)
        try:
            bpy.ops.transform.resize(value=(scale, scale, scale))
        except RuntimeError as exc:
            self.report({'WARNING'}, "Positions were not scaled: %s" % exc)
        return {'FINISHED'}


# --- Add > Forge Object (static tree, per-map filter) ------------------------------------------------------
def genObjectTypesEnum(self, context):
    try:
        scene = context.scene
    except Exception:
        scene = None
    return palette.search_items(scene)


class AddForgeObject(Operator):
    """Add forge object"""
    bl_idname = 'forge.add_object'
    bl_label = "Forge Object..."
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'objectType'

    objectType: EnumProperty(name="Object Type", items=genObjectTypesEnum)

    def invoke(self, context, event):
        palette.ensure_palette()
        context.window_manager.invoke_search_popup(self)
        return {'FINISHED'}

    def execute(self, context):
        if self.objectType == 'NONE':
            self.report({'ERROR'}, "No object type is available (the palette tree is empty).")
            return {'CANCELLED'}
        palette.ensure_palette()
        blobj = create_forge_object(context, self.objectType)
        blobj.location = context.scene.cursor.location
        for obj in context.selected_objects:
            obj.select_set(False)
        blobj.select_set(True)
        context.view_layer.objects.active = blobj
        return {'FINISHED'}


MENU_POOL_IDNAMES = ["VIEW3D_MT_add_forge_object_%02d" % k for k in range(palette.MENU_POOL_SIZE)]


def _draw_node(layout, context, node):
    names, _note = palette.visible_names(context.scene)
    for child in node.get("groups", []):
        if palette.count_visible(child, names) == 0:
            continue
        number = palette.group_number(child)
        icon = palette.groups()[number][1] if number is not None else palette.DEFAULT_ICON
        if number is not None and number < len(MENU_POOL_IDNAMES):
            layout.menu(MENU_POOL_IDNAMES[number], text=child.get("name", ""), icon=icon)
        else:                              # more groups than pooled menu classes: draw inline
            layout.separator()
            layout.label(text=child.get("name", ""), icon=icon)
            _draw_node(layout, context, child)
    layout.operator_context = 'EXEC_DEFAULT'
    for leaf in node.get("leaves", []):
        name = leaf["name"] if isinstance(leaf, dict) else leaf
        if names is not None and name not in names:
            continue
        op = layout.operator(AddForgeObject.bl_idname, text=name, icon=palette.leaf_icon(name))
        op.objectType = name


class AddForgeObjectMenu(bpy.types.Menu):
    bl_label = "Forge Object"
    bl_idname = 'VIEW3D_MT_add_forge_object'

    def draw(self, context):
        _names, note = palette.visible_names(context.scene)
        if note:
            self.layout.label(text=note)
        _draw_node(self.layout, context, palette.tree())


def _make_pool_menu(number):
    def draw(self, context):
        entries = palette.groups()
        if number < len(entries):
            _draw_node(self.layout, context, entries[number][0])

    return type(MENU_POOL_IDNAMES[number], (bpy.types.Menu,),
                {"bl_idname": MENU_POOL_IDNAMES[number], "bl_label": "Forge Object", "draw": draw})


MENU_POOL = [_make_pool_menu(k) for k in range(palette.MENU_POOL_SIZE)]


def addForgeObjectMenuItem(self, context):
    layout = self.layout
    layout.operator_context = 'INVOKE_DEFAULT'
    layout.operator(AddForgeObject.bl_idname, icon='ADD')
    layout.menu(AddForgeObjectMenu.bl_idname)


# --- the "N / 650" overlay (8.7 #16) ------------------------------------------------------------------------
_overlay = {"handle": None, "dirty": True, "count": 0}


def _is_background():
    return bpy.app.background


def draw_forgeObjectOverlay():
    """Draw "N / 650" bottom-left of the 3D view. Returns at once in background mode: ``blf.draw`` segfaults there."""
    if _is_background():
        return
    try:
        ctx = bpy.context
        space = ctx.space_data
        if space is not None and space.type == 'VIEW3D' and not space.overlay.show_overlays:
            return
        if _overlay["dirty"]:
            _overlay["count"] = count_forge_objects(ctx.scene, ctx.evaluated_depsgraph_get())
            _overlay["dirty"] = False
        count = _overlay["count"]
        font_id = 0
        blf.position(font_id, 15, 15, 0)
        blf.size(font_id, 11)
        if count > MAX_OBJECTS:
            blf.color(font_id, 1, 0, 0, 1)
        elif count > 500:
            blf.color(font_id, 1, 0.5, 0, 1)
        else:
            blf.color(font_id, 1, 1, 1, 1)
        blf.draw(font_id, "%d / %d" % (count, MAX_OBJECTS))
    except Exception:
        pass


@persistent
def _on_depsgraph_update(scene, depsgraph=None):
    _overlay["dirty"] = True


# --- registration ---------------------------------------------------------------------------------------------
class EnableNativeSettings(Operator):
    """Enable a legacy object's verified stock settings while keeping its placement"""
    bl_idname = 'forge.enable_native_settings'
    bl_label = 'Enable Native Object Settings'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects and context.selected_objects[0].get('isForgeObject'))

    def execute(self, context):
        obj = context.selected_objects[0]
        defaults = provider.new_object_defaults(state.map_name(context.scene) or 'Forge World',
                                                forge_type_name(obj), state.template_bytes(context.scene))
        if not defaults or not defaults['native_verified'] or obj.forge.cachedType != 0:
            self.report({'ERROR'}, 'Verified stock settings are unavailable for this object and template')
            return {'CANCELLED'}
        obj.forge.cachedType = defaults['cached_type']
        obj.forge.otherInfoA = defaults['other_a']
        obj.forge.otherInfoB = defaults['other_b']
        self.report({'INFO'}, 'Enabled stock object settings; placement was kept')
        return {'FINISHED'}


class RefreshForgePreviews(Operator):
    """Reload preview models from the selected library without changing Forge properties or poses"""
    bl_idname = 'forge.refresh_previews'
    bl_label = 'Refresh Forge Object Previews'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None

    def execute(self, context):
        if not palette.ensure_palette():
            self.report({'ERROR'}, palette.palette_missing_warning())
            return {'CANCELLED'}
        models = palette.collection_index()
        refreshed = 0
        for obj in context.scene.objects:
            if obj.type != 'EMPTY' or not obj.get('isForgeObject'):
                continue
            collection = models.get(forge_type_name(obj))
            if collection is None:
                continue
            pose = obj.matrix_world.copy()
            native = legacy_native_rotation(obj, pose_from_matrix(pose))
            if native is not None:
                forward, up = native
                corrected = basis_matrix(forward, up, pose.col[3].xyz)
                for axis in range(3):
                    corrected.col[axis].xyz *= pose.col[axis].xyz.length
                pose = corrected
                original = _pose_prop(obj, POSE_KEY)
                base = _pose_prop(obj, BASE_KEY)
                obj[POSE_KEY] = _flat((original[0], forward, up))
                new_view = pose_from_matrix(pose)
                obj[BASE_KEY] = _flat((base[0], new_view[1], new_view[2]))
                obj['mj_orientation_basis'] = 'native'
            obj.instance_type = 'COLLECTION'
            obj.instance_collection = collection
            obj.empty_display_size = 0.0001
            obj.matrix_world = pose
            apply_color_index(obj.forge)
            refreshed += 1
        self.report({'INFO'}, 'Refreshed %d Forge object previews; placements and properties were kept' % refreshed)
        return {'FINISHED'}


CLASSES = [
    ForgeObjectProps, ForgeCollectionProps, ForgeSceneProps,
    AddForgeObject, ConvertForge, SetupArray, ErrorMessage, ScaleObjects, RefreshForgePreviews, EnableNativeSettings,
    ForgeObjectPanel, ForgeObjectPanel_Sidebar, AddForgeObjectMenu, ForgeCollectionPanel, ForgeScenePanel,
] + MENU_POOL

# (menu type name, draw function): hooks appended on register and removed on unregister
MENU_HOOKS = [
    ('VIEW3D_MT_object_context_menu', convertForgeMenuItem),
    ('VIEW3D_MT_object_context_menu', setupArrayMenuItem),
    ('VIEW3D_MT_add', addForgeObjectMenuItem),
]

_registered = False


def register():
    global _registered
    if _registered:
        unregister()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Object.forge = PointerProperty(type=ForgeObjectProps)
    bpy.types.Collection.forge = PointerProperty(type=ForgeCollectionProps)
    bpy.types.Scene.forge = PointerProperty(type=ForgeSceneProps)
    for menu_name, fn in MENU_HOOKS:
        menu = getattr(bpy.types, menu_name)
        menu.remove(fn)                                       # never twice (remove of an absent hook is silent)
        menu.append(fn)
    if not bpy.app.background:                                # blf.draw crashes -b; nothing to draw there (8.11)
        _overlay["handle"] = bpy.types.SpaceView3D.draw_handler_add(draw_forgeObjectOverlay, (), 'WINDOW',
                                                                    'POST_PIXEL')
        bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)
    _registered = True


def unregister():
    global _registered
    if _overlay["handle"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_overlay["handle"], 'WINDOW')
        except Exception:
            pass
        _overlay["handle"] = None
    while _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)
    for menu_name, fn in MENU_HOOKS:
        try:
            getattr(bpy.types, menu_name).remove(fn)
        except Exception:
            pass
    for owner in (bpy.types.Object, bpy.types.Collection, bpy.types.Scene):
        try:
            del owner.forge
        except Exception:
            pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
    _registered = False
