#!/usr/bin/env python3
"""Python 3.9 compatibility lint (SPEC 6.8, test U-19).

    python3 -I tests/py39_lint.py [PATH ...]      # default: Addon/mvarlib, tests, tools

``ast.parse(source, feature_version=(3, 9))`` rejects only syntax-level constructs (``match``,
``except*``, f-string quote reuse) and misses every runtime one: on 3.9.6 an ``int | None``
annotation raises ``TypeError`` at import, ``dataclass(slots=True)`` and ``zip(strict=True)``
raise ``TypeError``, ``.bit_count()`` and ``itertools.pairwise`` raise ``AttributeError``,
``int.from_bytes(b)`` raises ``TypeError``, yet the parse alone passes all of them. This lint adds
an AST pass for each forbidden construct of 6.8 that the parser accepts.

A finding on a line carrying the comment ``# py39: ok`` is suppressed (for the rare false
positive, for example a library ``to_bytes(flag)`` call that is not ``int.to_bytes``).
Exit status: 0 clean, 1 findings. Works on Python 3.9 to 3.13, standard library only.
"""
import ast
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATHS = [os.path.join(REPO, "Addon", "mvarlib"), os.path.join(REPO, "tests"), os.path.join(REPO, "tools")]
SUPPRESS = "py39: ok"

# (module, attribute) pairs that do not exist on 3.9
BANNED_MODULE_ATTRS = {
    ("itertools", "pairwise"): "itertools.pairwise needs 3.10",
    ("itertools", "batched"): "itertools.batched needs 3.12",
    ("datetime", "UTC"): "datetime.UTC needs 3.11",
    ("math", "cbrt"): "math.cbrt needs 3.11",
    ("math", "exp2"): "math.exp2 needs 3.11",
    ("math", "sumprod"): "math.sumprod needs 3.12",
    ("enum", "StrEnum"): "enum.StrEnum needs 3.11",
    ("sys", "stdlib_module_names"): "sys.stdlib_module_names needs 3.10",
}
for _name in ("Self", "TypeAlias", "ParamSpec", "TypeGuard", "Concatenate", "Never", "LiteralString",
              "assert_never", "assert_type", "reveal_type", "Required", "NotRequired", "TypeVarTuple",
              "Unpack", "dataclass_transform"):
    BANNED_MODULE_ATTRS[("typing", _name)] = "typing.%s needs 3.10 or later" % _name
BANNED_MODULES = {"tomllib": "tomllib needs 3.11"}
BUILTIN_TYPE_NAMES = {"int", "str", "float", "bool", "bytes", "bytearray", "complex", "list", "dict", "tuple",
                      "set", "frozenset", "object", "type"}
DATACLASS_BAD_KEYWORDS = {"slots", "kw_only", "match_args", "weakref_slot"}
BISECT_FUNCS = {"bisect", "bisect_left", "bisect_right", "insort", "insort_left", "insort_right"}


class _Visitor(ast.NodeVisitor):
    def __init__(self, future_annotations):
        self.findings = []
        self.future_annotations = future_annotations
        self.func_depth = 0
        self.aliases = {}                       # local name -> module name ("import itertools as it")

    def add(self, node, message):
        self.findings.append((getattr(node, "lineno", 0), message))

    # --- imports ---------------------------------------------------------------------------
    def visit_Import(self, node):
        for alias in node.names:
            root = alias.name.split(".")[0]
            self.aliases[alias.asname or root] = alias.name if alias.asname else root
            if alias.name in BANNED_MODULES:
                self.add(node, BANNED_MODULES[alias.name])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ""
        if module in BANNED_MODULES:
            self.add(node, BANNED_MODULES[module])
        for alias in node.names:
            reason = BANNED_MODULE_ATTRS.get((module, alias.name))
            if reason:
                self.add(node, reason)
        self.generic_visit(node)

    # --- attributes ------------------------------------------------------------------------
    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            module = self.aliases.get(node.value.id, node.value.id)
            reason = BANNED_MODULE_ATTRS.get((module, node.attr))
            if reason:
                self.add(node, reason)
        self.generic_visit(node)

    # --- calls -----------------------------------------------------------------------------
    @staticmethod
    def _callee(node):
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None

    def visit_Call(self, node):
        name = self._callee(node)
        keywords = set(k.arg for k in node.keywords if k.arg)
        positional = len(node.args)
        if name == "dataclass" and keywords & DATACLASS_BAD_KEYWORDS:
            self.add(node, "dataclass(%s=...) needs 3.10 or later" % sorted(keywords & DATACLASS_BAD_KEYWORDS)[0])
        elif name == "field" and "kw_only" in keywords:
            self.add(node, "dataclasses.field(kw_only=...) needs 3.10")
        elif isinstance(node.func, ast.Name) and name == "zip" and "strict" in keywords:
            self.add(node, "zip(strict=...) needs 3.10")
        elif isinstance(node.func, ast.Attribute) and name == "bit_count":
            self.add(node, "int.bit_count() needs 3.10 (use bin(x).count('1'))")
        elif isinstance(node.func, ast.Attribute) and name == "from_bytes":
            # the library's own classmethod ``MapVariant.from_bytes(data)`` is not ``int.from_bytes`` (G3)
            library_class = isinstance(node.func.value, ast.Name) and node.func.value.id == "MapVariant"
            if positional < 2 and "byteorder" not in keywords and not library_class:
                self.add(node, "int.from_bytes() needs the byteorder argument before 3.11")
        elif isinstance(node.func, ast.Attribute) and name == "to_bytes":
            first_is_bool = (positional >= 1 and isinstance(node.args[0], ast.Constant)
                             and isinstance(node.args[0].value, bool))
            if "byteorder" not in keywords and not first_is_bool and (
                    positional == 1 or (positional == 0 and "length" in keywords)):
                self.add(node, "int.to_bytes() needs length and byteorder before 3.11 "
                               "(a library to_bytes must be called with keywords, or add '# py39: ok')")
        elif isinstance(node.func, ast.Name) and name in ("isinstance", "issubclass") and len(node.args) == 2:
            second = node.args[1]
            if isinstance(second, ast.BinOp) and isinstance(second.op, ast.BitOr):
                self.add(node, "%s(x, A | B) needs 3.10 (use a tuple)" % name)
        elif name in BISECT_FUNCS and "key" in keywords:
            self.add(node, "%s(key=...) needs 3.10" % name)
        elif isinstance(node.func, ast.Name) and name in ("aiter", "anext"):
            self.add(node, "%s() needs 3.10" % name)
        self.generic_visit(node)

    # --- type unions -----------------------------------------------------------------------
    def visit_BinOp(self, node):
        if isinstance(node.op, ast.BitOr):
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and side.value is None:
                    self.add(node, "'X | None' type union is evaluated at runtime and needs 3.10")
                    break
                if isinstance(side, ast.Name) and side.id in BUILTIN_TYPE_NAMES:
                    self.add(node, "'%s | ...' type union is evaluated at runtime and needs 3.10" % side.id)
                    break
        self.generic_visit(node)

    def _check_annotation(self, annotation):
        """Annotations are evaluated at definition time unless ``from __future__ import annotations``."""
        if annotation is None or self.future_annotations:
            return
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                self.add(sub, "type union 'A | B' in an annotation needs 3.10 (add "
                              "'from __future__ import annotations' or use Optional/Union)")
                return
        self.visit(annotation)                   # an evaluated annotation may use a banned name (typing.Self)

    def _visit_function(self, node):
        args = node.args
        every = list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs)
        if args.vararg:
            every.append(args.vararg)
        if args.kwarg:
            every.append(args.kwarg)
        for arg in every:
            self._check_annotation(arg.annotation)
        self._check_annotation(node.returns)
        # Annotation subtrees are not walked further: they are either checked above or, under
        # "from __future__ import annotations", never evaluated.
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            self.visit(default)
        self.func_depth += 1
        for statement in node.body:
            self.visit(statement)
        self.func_depth -= 1

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_AnnAssign(self, node):
        if self.func_depth == 0:                 # annotations of locals are not evaluated
            self._check_annotation(node.annotation)
        self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    # --- syntax newer than 3.9 that an old parser may have accepted ------------------------
    def visit_Match(self, node):
        self.add(node, "match statement needs 3.10")
        self.generic_visit(node)

    def visit_TryStar(self, node):
        self.add(node, "except* needs 3.11")
        self.generic_visit(node)


def _fstring_findings(source):
    """Quote reuse, backslashes and comments inside f-string expressions are valid only from 3.12.

    ``ast.parse(feature_version=(3, 9))`` on 3.12/3.13 accepts them (re-tested on 3.13.13), so they
    are found with the tokenizer; on 3.9 to 3.11 the parser itself rejects them.
    """
    import io
    import tokenize
    start_type = getattr(tokenize, "FSTRING_START", None)
    if start_type is None:
        return []
    found = []
    stack = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == start_type:
                delim = tok.string.lstrip("rRfFbBuU")
                if any(delim.startswith(e) for e in stack):
                    found.append((tok.start[0], "f-string nested with the same quotes as its enclosing f-string needs 3.12"))
                stack.append(delim)
            elif tok.type == tokenize.FSTRING_END:
                if stack:
                    stack.pop()
            elif stack and tok.type == tokenize.STRING:
                body = tok.string.lstrip("rRfFbBuU")
                delim = body[:3] if body[:3] in ('"""', "'''") else body[:1]
                if any(delim.startswith(e) for e in stack):
                    found.append((tok.start[0], "quote reuse inside an f-string expression needs 3.12"))
                if "\\" in tok.string:
                    found.append((tok.start[0], "backslash inside an f-string expression needs 3.12"))
            elif stack and tok.type == tokenize.COMMENT:
                found.append((tok.start[0], "comment inside an f-string expression needs 3.12"))
    except (tokenize.TokenError, SyntaxError):
        pass
    return found


def _uses_future_annotations(tree):
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(a.name == "annotations" for a in node.names):
                return True
    return False


def lint_source(source, filename="<string>"):
    """Return a list of ``"file:line: message"`` findings for one source text."""
    try:
        tree = ast.parse(source, filename=filename, feature_version=(3, 9))
    except SyntaxError as exc:
        return ["%s:%s: not valid Python 3.9 syntax: %s" % (filename, exc.lineno or 0, exc.msg)]
    visitor = _Visitor(_uses_future_annotations(tree))
    visitor.visit(tree)
    lines = source.splitlines()
    out = []
    for lineno, message in sorted(set(visitor.findings + _fstring_findings(source))):
        if 1 <= lineno <= len(lines) and SUPPRESS in lines[lineno - 1]:
            continue
        out.append("%s:%d: %s" % (filename, lineno, message))
    return out


def iter_python_files(path):
    if os.path.isfile(path):
        yield path
        return
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(root, name)


def lint_paths(paths):
    findings = []
    count = 0
    for path in paths:
        for filename in iter_python_files(path):
            count += 1
            with open(filename, "r", encoding="utf-8") as fh:
                findings += lint_source(fh.read(), filename)
    return count, findings


def main(argv=None):
    paths = list(sys.argv[1:] if argv is None else argv) or DEFAULT_PATHS
    try:
        count, findings = lint_paths(paths)
    except OSError as exc:
        print("py39_lint: cannot read: %s" % exc, file=sys.stderr)
        return 2
    for line in findings:
        print(line)
    print("py39_lint: %d file(s) checked, %d finding(s)" % (count, len(findings)))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
