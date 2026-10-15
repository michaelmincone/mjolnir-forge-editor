"""Halo: Mjolnir Forge Editor: import and export Halo: Reach map variants (.mvar) in Blender.

Package layout (SPEC 8.1): ``mjolnir`` (property groups, objects, panels, Add menu, overlay), ``palette``
(object library link, static Add-menu tree, relink), ``io_ops`` (File > Import / Export), ``state`` (what is
kept in the .blend), ``provider`` (the only door to ``mvarlib``) and ``mvarlib`` (the pure-Python library).
Relative imports only: no ``sys.path`` edit, nothing is registered at import.

``register()`` follows SPEC 8.2: classes, pointer properties, menu hooks and handlers only. It touches no
``bpy.data`` and no ``bpy.context.scene``, calls no operator, starts no thread, uses no network and links no
library, because during enable at startup ``bpy.data`` is restricted.
"""

# ``bl_info`` serves the legacy development loop (``Addon/`` symlinked into scripts/addons); the extension
# metadata is ``blender_manifest.toml``.
bl_info = {
    "name": "Halo: Mjolnir Forge Editor",
    "author": "Waffle1434",
    "description": "Import and export Halo: Reach map variants (.mvar).",
    "blender": (5, 2, 0),
    "version": (1, 0, 0),
    "location": "File > Import / Export, Add > Forge Object",
    "warning": "",
    "category": "Import-Export",
    "doc_url": "https://github.com/Waffle1434/Mjolnir-Forge-Editor",
}

from . import state, palette, mjolnir, io_ops    # noqa: E402  (relative imports; bpy is available when Blender loads this)


def register():
    mjolnir.register()
    palette.register()
    io_ops.register()


def unregister():
    io_ops.unregister()
    palette.unregister()
    mjolnir.unregister()
