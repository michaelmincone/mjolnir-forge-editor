"""File input and the output path policy of ``mvarlib`` (SPEC 2.13, DEC-6.1). Delivered complete in G0.

Every tool that writes a file goes through :func:`write_atomic`, the command-line tools included,
not only the add-on. The rules (2.13):

* refuse (``PathPolicyError``) when the target resolves (``os.path.realpath``, so symlinks and
  hard links are followed) to the same file as any source path, or lies under a protected folder
  (defaults: ``~/Local_Documents/Halo-MCC/variant-tool/test-samples``, ``~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library``
  and, since G3, ``~/Local_Documents/Halo-MCC/forge/real-mvar-samples`` (the one real map variant); configurable in the
  add-on preferences);
* otherwise write ``<target>.tmp-<pid>`` in the same directory with ``O_EXCL``, ``fsync`` it,
  re-read it, run the optional ``verify`` callback, then ``os.replace`` it onto the target;
* never create a ``.bak``; never rename an existing file; a failed verify deletes the temporary
  file and nothing is left behind.

Source files are only ever opened ``rb`` (:func:`read_file`). Python 3.9 to 3.13, standard library only.
"""
import errno
import os

from .api import Issue
from .errors import FormatError, InternalError, PathPolicyError

DEFAULT_PROTECTED = (
    "~/Local_Documents/Halo-MCC/variant-tool/test-samples",
    "~/Local_Documents/Halo-MCC/variant-tool/ReachVariantTool-core-library",
    "~/Local_Documents/Halo-MCC/forge/real-mvar-samples",
)

SUFFIX = "_mjolnir.mvar"
FALLBACK_EXPORT_DIR = "~/Documents/Mjolnir Exports"


def default_protected_dirs():
    """The built-in protected folders with ``~`` expanded."""
    return [os.path.expanduser(p) for p in DEFAULT_PROTECTED]


def _real(path):
    return os.path.realpath(os.path.expanduser(os.fspath(path)))


def _same_file(a_real, b_real):
    if os.path.normcase(a_real) == os.path.normcase(b_real):
        return True
    try:
        return os.path.samefile(a_real, b_real)   # hard links, case-insensitive volumes
    except OSError:
        return False


def _inside(target_real, folder_real):
    """True when ``target_real`` is the folder itself or lies anywhere below it."""
    try:
        if os.path.commonpath([target_real, folder_real]) == folder_real:
            return True
    except ValueError:                       # different drives (Windows) or mixed absolute/relative
        pass
    if os.path.isdir(folder_real):           # case-insensitive volumes, bind-mount aliases
        cur = os.path.dirname(target_real)
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


def check_output_path(target, source_paths=(), protected=None):
    """Run the two path checks of 2.13 without writing; return the ``Issue`` or ``None``.

    ``protected=None`` means the built-in defaults; an explicit empty sequence protects nothing.
    Codes: ``E_PATH_SAME_AS_SOURCE`` (7.3, checked first) and ``E_PATH_PROTECTED``.
    """
    target_real = _real(target)
    for src in source_paths or ():
        if not src:
            continue
        if _same_file(target_real, _real(src)):
            return Issue(
                "E_PATH_SAME_AS_SOURCE", "error",
                "Refusing to overwrite the file this map was imported from (%s). Choose a different name."
                % os.fspath(src))
    folders = default_protected_dirs() if protected is None else list(protected)
    for folder in folders:
        if not folder:
            continue
        if _inside(target_real, _real(folder)):
            return Issue("E_PATH_PROTECTED", "error",
                         "Refusing to write into the protected folder %s." % os.fspath(folder))
    return None


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def write_atomic(target, data, source_paths=(), protected=None, verify=None, make_dirs=True):
    """Write ``data`` to ``target`` under the path policy; raises ``PathPolicyError`` when refused.

    ``verify`` (optional) is called with the bytes re-read from the temporary file, after the
    byte-for-byte comparison with ``data`` and before ``os.replace``. If it raises, the exception
    propagates unchanged; if it returns ``False`` an ``InternalError`` is raised. In both cases the
    temporary file is deleted and the target is untouched. ``make_dirs`` creates missing parent
    folders after the policy check (the default export folder ``~/Documents/Mjolnir Exports`` is
    created on first export, 2.13). Not part of the frozen ``api.write_atomic`` signature: the api
    helper calls this function with its four positional arguments.
    """
    issue = check_output_path(target, source_paths, protected)
    if issue is not None:
        raise PathPolicyError(issue.message)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("write_atomic: data must be bytes, got %s" % type(data).__name__)
    payload = bytes(data)
    base = os.path.abspath(os.path.expanduser(os.fspath(target)))   # stay in the target's own directory
    if os.path.isdir(base):
        raise PathPolicyError("Refusing to write: %s is a folder, not a file." % base)
    directory = os.path.dirname(base)
    if make_dirs and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)

    tmp = None
    fd = None
    for n in range(100):
        cand = "%s.tmp-%d" % (base, os.getpid()) + ("" if n == 0 else "-%d" % n)
        try:
            fd = os.open(cand, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        tmp = cand
        break
    if tmp is None:
        raise OSError(errno.EEXIST, "could not create a unique temporary file next to the target", base)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        with open(tmp, "rb") as fh:
            written = fh.read()
        if written != payload:
            raise OSError(errno.EIO, "the temporary file does not match the data that was written", tmp)
        if verify is not None and verify(written) is False:
            raise InternalError("The written file failed verification; nothing was saved.")
        os.replace(tmp, base)
    except BaseException:
        _remove_quietly(tmp)
        raise
    try:                                      # best effort: make the rename durable
        dfd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def read_file(path, max_bytes=None):
    """Read a source file (opened ``rb`` only). ``max_bytes`` refuses larger files."""
    with open(os.fspath(path), "rb") as fh:
        if max_bytes is None:
            return fh.read()
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FormatError("This does not look like a map variant (file too large).")
    return data


def default_output_path(source_path, protected=None, fallback_dir=None):
    """Default export name: ``<source stem>_mjolnir.mvar`` next to the source (2.13).

    When that directory is, or lies inside, a protected folder the name is proposed in
    ``~/Documents/Mjolnir Exports`` instead (``fallback_dir`` overrides it), so the proposed
    default is never a refused path. The folder is created by :func:`write_atomic` on export.
    """
    source_path = os.fspath(source_path)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    name = stem + SUFFIX
    candidate = os.path.join(os.path.dirname(os.path.abspath(source_path)), name)
    issue = check_output_path(candidate, [source_path], protected)
    if issue is None:
        return candidate
    return os.path.join(os.path.expanduser(fallback_dir or FALLBACK_EXPORT_DIR), name)
