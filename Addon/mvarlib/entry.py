"""Real bodies behind ``api.load_map_variant`` and ``api.export_map_variant`` (SPEC 6.1, 6.4).

Created at G0 with placeholder bodies so that ``api.py`` can be frozen complete:

* G3 (this file's ``load_map_variant``): the body read path; see the contract notes of 6.4.
* G5 (``export_map_variant``, the ordered algorithm of 5.10, in ``edit.py`` and ``validate.py``).

Nothing else may change here without re-reading the contract notes of SPEC 6.4. The parameter
names below mirror ``api.py`` exactly (covered by test ``test_api_surface.py``). There are no
annotations, because ``api.py`` imports this module lazily and the types would only be documentation.
"""


def load_map_variant(data, name="", options=None):
    """Parse a map variant (bytes) into an ``api.LoadResult``.

    Raises the errors of SPEC 6.2 / 7.2 (all are ``MvarError``): ``BlfFormatError``,
    ``UnsupportedVariantError``, ``FormatError``, ``DesyncError``, ``AmbiguousLayoutError``,
    ``OutOfBoundsPositionError``. ``options`` is an ``api.ReadOptions`` (or ``None``). Nothing is written
    anywhere; the result holds the occupied slots as ``ObjectRecord`` objects and the ``MapInfo``.
    """
    from .api import LoadResult
    from .model import MapVariant
    model = MapVariant.from_bytes(data, options, name)
    info = model.info()
    return LoadResult(info=info, objects=model.objects(), warnings=list(info.warnings))


def export_map_variant(template, objects, options):
    """Patch ``template`` with ``objects`` and return an ``api.ExportResult`` (SPEC 5.10; implemented in G5).

    The ordered algorithm lives in ``edit.py`` (planning, identity matching, quota, serialisation, verification) and
    the texts and field rules in ``validate.py``. Stateless: the template is parsed strictly on every call and
    nothing touches the file system; a refusal returns ``ok = False`` with ``data = None`` and every problem.
    """
    from .edit import export_map_variant as _export
    return _export(template, objects, options)
