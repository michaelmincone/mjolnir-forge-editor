"""mvarlib: pure-Python reader and writer for Halo: Reach map variant (.mvar) files.

No ``bpy``, standard library only, Python 3.9 to 3.13, relative imports only (it is importable as
``mvarlib`` from the tools and as ``<extension>.mvarlib`` inside Blender). The public surface is
the frozen interface of :mod:`mvarlib.api` (SPEC 6.4, "interface freeze v1"); this package module
re-exports it together with the exception classes.

``import mvarlib`` is cheap: the heavy modules (``entry`` and everything behind it) are imported
lazily by the functions of ``api.py``.
"""
from .api import *                         # noqa: F401,F403  (the frozen names; see api.__all__)
from .api import __all__ as _api_all
from . import errors                       # noqa: F401

__version__ = "1.0.0"
__all__ = list(_api_all) + ["errors", "__version__"]
