"""Scene state of the Blender glue (SPEC 8.3): the only code that touches ``scene['mjolnir*']``.

What lives in the ``.blend`` (so a saved file keeps working in a fresh Blender process, with no
dependence on a path or on ``bpy.app.driver_namespace``)::

    scene['mjolnir_template']   bytes, top level: the imported file verbatim
    scene['mjolnir']            dict: template_sha256, source_name, source_path, map_id_hex, map_name,
                                labels (original case, index = file entry index), label_present,
                                bounds, quota_count, version, occupied_at_import, imported_slots,
                                failed_slots, failed_nonstock, hash_flavour, hypothesis, addon_version,
                                mvarlib_version

Blender integer custom properties are 32 bit, so no u32 value is stored as an int (the map id is the
string ``map_id_hex``; the palette CRC and budget words stay inside the template bytes). A list that
mixes ``str`` and ``int`` raises ``TypeError``, so nothing mixed is stored (``_clean`` turns such data
into strings). Nothing here talks to ``mvarlib``: the callers pass the load result in.
"""
import hashlib

KEY = "mjolnir"
TEMPLATE_KEY = "mjolnir_template"

NO_LABEL = "NO_LABEL"
LABEL_PREFIX = "L"

_INT_MIN = -(2 ** 31)
_INT_MAX = 2 ** 31 - 1


def _clean(value):
    """Make ``value`` storable as an ID property: 32-bit ints, homogeneous lists, str keys."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if _INT_MIN <= value <= _INT_MAX else "0x%X" % value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return dict((str(k), _clean(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        items = [_clean(v) for v in value]
        kinds = set(type(v) for v in items if not isinstance(v, (dict, list)))
        if len(kinds) > 1 and not kinds <= set([int, float, bool]):
            items = [v if isinstance(v, str) else str(v) for v in items]
        if any(isinstance(v, (list, dict)) for v in items):
            items = [str(v) for v in items]
        return items
    if value is None:
        return ""
    return str(value)


def get(scene):
    """The state dict of ``scene`` as a plain ``dict`` (a copy), or ``None`` when no map variant was imported."""
    raw = scene.get(KEY) if scene is not None else None
    if raw is None:
        return None
    return raw.to_dict() if hasattr(raw, "to_dict") else dict(raw)


def has_map(scene):
    """True when a map variant was imported into ``scene`` (cheap: no copy, unlike :func:`get`)."""
    return scene is not None and scene.get(KEY) is not None


def template_bytes(scene):
    """The embedded template (bytes) or ``None``."""
    raw = scene.get(TEMPLATE_KEY) if scene is not None else None
    if raw is None:
        return None
    return bytes(raw)


def verify_template(scene):
    """``(ok, reason)``: the embedded bytes exist and match the stored SHA-256 (E_NO_TEMPLATE / E_TEMPLATE_CORRUPT)."""
    st = get(scene)
    data = template_bytes(scene)
    if st is None or data is None:
        return False, "E_NO_TEMPLATE"
    if hashlib.sha256(data).hexdigest() != st.get("template_sha256", ""):
        return False, "E_TEMPLATE_CORRUPT"
    return True, ""


def set_from_load(scene, data, load_result, source_path, addon_version="", library_version=""):
    """Store the template bytes and the info of ``load_result`` (call BEFORE objects are created)."""
    info = load_result.info
    labels = [str(t) for t in info.labels]
    present = [1 if p else 0 for p in info.label_present]
    present = (present + [0] * len(labels))[:len(labels)]
    map_id = int(info.map_id)
    st = {
        "template_sha256": hashlib.sha256(bytes(data)).hexdigest(),
        "source_name": _basename(source_path),
        "source_path": str(source_path or ""),
        "map_id_hex": "0x%08X" % (map_id & 0xFFFFFFFF),
        "map_name": info.map_name or "",
        "labels": labels,
        "label_present": present,
        "bounds": [float(v) for v in info.bounds],
        "quota_count": int(info.quota_count),
        "version": int(info.version),
        "occupied_at_import": int(info.occupied),
        "imported_slots": [],
        "failed_slots": [],
        "failed_nonstock": {},
        "hash_flavour": str(info.hash_flavour or ""),
        "hypothesis": _clean(dict(info.hypothesis or {})),
        "addon_version": str(addon_version),
        "mvarlib_version": str(library_version),
    }
    # Blender 5.2.1 bug (probed): assigning a bytes value to a key that ALREADY holds bytes stores an EMPTY value. The key is
    # deleted first so that a leftover template (a hand-deleted ``mjolnir`` key, an older state) can never swallow the file.
    for key in (TEMPLATE_KEY, KEY):
        if key in scene:
            del scene[key]
    scene[TEMPLATE_KEY] = bytes(data)
    scene[KEY] = st


def set_import_results(scene, imported, failed, failed_nonstock=None):
    """Record which slots were imported and which failed (a failed slot is never treated as deleted at export).

    ``failed_nonstock`` is ``{slot: type name}`` for the failed slots whose object is not a stock object of the map:
    the library keeps a slot it was not told about exactly as it is and does not run the stock check on it, so the
    export (``io_ops``) must say so (refuse, or warn when the user keeps unrecognised objects).
    """
    st = scene[KEY]
    st["imported_slots"] = [int(s) for s in imported]
    st["failed_slots"] = [int(s) for s in failed]
    st["failed_nonstock"] = dict((str(int(slot)), str(name)) for slot, name in dict(failed_nonstock or {}).items())


def failed_nonstock(scene):
    """``{slot: type name}`` of the failed-import slots whose object is not stock (empty for older state)."""
    st = scene.get(KEY) if scene is not None else None
    raw = st.get("failed_nonstock") if st is not None else None
    if not raw:
        return {}
    out = {}
    for key in raw.keys():
        try:
            out[int(key)] = str(raw[key])
        except (TypeError, ValueError):
            continue
    return out


def clear(scene):
    for key in (KEY, TEMPLATE_KEY):
        if key in scene:
            del scene[key]


def _basename(path):
    path = str(path or "")
    return path.replace("\\", "/").rsplit("/", 1)[-1]


# --- labels ---------------------------------------------------------------------------------
def label_entries(scene):
    """``[(index, text)]`` of the label entries that are present in the file, in file order."""
    raw = scene.get(KEY) if scene is not None else None
    if raw is None:
        return []
    labels = [str(t) for t in raw.get("labels", [])]
    present = list(raw.get("label_present", []))
    out = []
    for i, text in enumerate(labels):
        if i >= len(present) or present[i]:
            out.append((i, text))
    return out


def label_enum_id(index):
    """Enum identifier for a file label index: ``-1`` -> ``NO_LABEL``, ``i`` -> ``L<i>``."""
    return NO_LABEL if index is None or index < 0 else "%s%d" % (LABEL_PREFIX, index)


def label_index_from_enum(identifier):
    """File label index for an enum identifier (``NO_LABEL`` / ``L<i>`` / empty -> -1)."""
    if identifier and identifier.startswith(LABEL_PREFIX) and identifier[1:].isdigit():
        return int(identifier[1:])
    return -1


def label_text(scene, identifier):
    """Label text (original case) for an enum identifier, '' for no label or an unknown index."""
    index = label_index_from_enum(identifier)
    if index < 0:
        return ""
    for i, text in label_entries(scene):
        if i == index:
            return text
    return ""


def enum_id_for_text(scene, text):
    """Enum identifier of the first present label whose text upper-cased equals ``text`` upper-cased, else ``None``."""
    wanted = text.upper()
    for i, label in label_entries(scene):
        if label.upper() == wanted:
            return label_enum_id(i)
    return None


def quota_count(scene):
    """Number of palette entries (quota rows) the imported file defines; 0 when no map variant or unknown."""
    st = scene.get(KEY) if scene is not None else None
    if st is None:
        return 0
    try:
        return int(st.get("quota_count", 0))
    except (TypeError, ValueError):
        return 0


def map_name(scene):
    st = scene.get(KEY) if scene is not None else None
    return str(st.get("map_name", "")) if st is not None else ""
