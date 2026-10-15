"""U-19 (SPEC 6.8, 9.3): the library must run on Python 3.9.6 as well as 3.13.

(a) every module of ``Addon/mvarlib`` and ``tools`` (plus ``Addon/provider.py`` and the stub) is imported
    under ``/usr/bin/python3`` when that is a 3.9.x interpreter. On 3.9 the import runs in this
    process; on another interpreter it runs in a child process of ``/usr/bin/python3 -I`` when one
    exists (the spec only asks to skip with a notice there; running the child is stricter), else the
    test is skipped with a notice.
(b) ``tests/py39_lint.py`` runs on every file of ``Addon/mvarlib``, ``tests`` and ``tools``, including
    the ``ast.parse(feature_version=(3, 9))`` scan; the lint's own tests feed it one bad line per
    forbidden construct of 6.8 and a set of good lines that must stay quiet.
"""
import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PY39 = "/usr/bin/python3"
sys.path.insert(0, os.path.join(REPO, "Addon"))


def load_lint():
    spec = importlib.util.spec_from_file_location("py39_lint_under_test", os.path.join(REPO, "tests", "py39_lint.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = load_lint()

IMPORT_SCRIPT = r'''
import importlib.util, os, sys
repo = sys.argv[1]
sys.path.insert(0, os.path.join(repo, "Addon"))
sys.path.insert(0, os.path.join(repo, "tests", "stubs"))
failed = []
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
pkg = os.path.join(repo, "Addon", "mvarlib")
for fn in sorted(os.listdir(pkg)):
    if fn.endswith(".py"):
        name = "mvarlib" if fn == "__init__.py" else "mvarlib." + fn[:-3]
        try:
            __import__(name)
        except Exception as exc:
            failed.append("%s: %s: %s" % (name, type(exc).__name__, exc))
for fn in sorted(os.listdir(os.path.join(repo, "tools"))):
    if fn.endswith(".py"):
        try:
            load(os.path.join(repo, "tools", fn), "tools_" + fn[:-3])
        except Exception as exc:
            failed.append("tools/%s: %s: %s" % (fn, type(exc).__name__, exc))
for rel, name in (("Addon/provider.py", "provider"), ("tests/stubs/stub_mvarlib.py", "stub_mvarlib")):
    try:
        load(os.path.join(repo, rel), name)
    except Exception as exc:
        failed.append("%s: %s: %s" % (rel, type(exc).__name__, exc))
print("python %d.%d.%d" % sys.version_info[:3])
for line in failed:
    print("IMPORT FAILED " + line)
sys.exit(1 if failed else 0)
'''


def python39_available():
    if sys.version_info[:2] == (3, 9):
        return True
    try:
        out = subprocess.run([PY39, "-I", "-c", "import sys; print(sys.version_info[:2] == (3, 9))"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True).stdout
    except OSError:
        return False
    return out.strip() == "True"


class TestImportsUnderPython39(unittest.TestCase):
    def test_every_library_and_tool_module_imports_on_3_9(self):
        if not python39_available():
            self.skipTest("NOTICE: no /usr/bin/python3 reporting 3.9.x here; the 3.9 import scan did not run")
        if sys.version_info[:2] == (3, 9):
            namespace = {"__name__": "__u19__"}
            old_argv = sys.argv
            sys.argv = ["u19", REPO]
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    with self.assertRaises(SystemExit) as cm:
                        exec(compile(IMPORT_SCRIPT, "<u19-import-scan>", "exec"), namespace)
            finally:
                sys.argv = old_argv
            self.assertEqual(cm.exception.code, 0, "module(s) failed to import on Python 3.9:\n" + captured.getvalue())
        else:
            result = subprocess.run([PY39, "-I", "-c", IMPORT_SCRIPT, REPO], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("python 3.9", result.stdout)


class TestTreeIsLintClean(unittest.TestCase):
    def test_addon_mvarlib_tests_and_tools_have_no_findings(self):
        paths = [os.path.join(REPO, "Addon", "mvarlib"), os.path.join(REPO, "tests"), os.path.join(REPO, "tools")]
        count, findings = lint.lint_paths(paths)
        self.assertGreater(count, 15)
        self.assertEqual(findings, [], "\n".join(findings))

    def test_lint_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tests", "py39_lint.py"),
                             os.path.join(REPO, "Addon", "mvarlib")], stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("0 finding(s)", ok.stdout)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.py")
            with open(bad, "w") as fh:
                fh.write("def f(a: int | None):\n    return a\n")
            result = subprocess.run([sys.executable, "-I", os.path.join(REPO, "tests", "py39_lint.py"), bad],
                                    stdout=subprocess.PIPE, universal_newlines=True)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("bad.py:1:", result.stdout)


# One bad line (or two) per forbidden construct of SPEC 6.8 that the parser accepts, plus the syntax ones.
BAD = {
    "match statement": "match x:\n    case 1:\n        pass\n",
    "except*": "try:\n    pass\nexcept* ValueError:\n    pass\n",
    "f-string quote reuse": "x = {'a': 1}\ny = f\"{x[\"a\"]}\"\n",
    "f-string backslash": "y = f\"{'\\n'.join(['a'])}\"\n",
    "int | None annotation (parameter)": "def f(a: int | None):\n    pass\n",
    "int | None annotation (return)": "def f() -> str | None:\n    pass\n",
    "class attribute annotation union": "class A:\n    x: int | None = None\n",
    "runtime union alias": "X = int | None\n",
    "isinstance with a union": "isinstance(1, int | str)\n",
    "dataclass(slots=True)": "from dataclasses import dataclass\n@dataclass(slots=True)\nclass A:\n    x: int\n",
    "dataclass(kw_only=True)": "import dataclasses\n@dataclasses.dataclass(kw_only=True)\nclass A:\n    x: int\n",
    "dataclass(match_args=False)": "from dataclasses import dataclass\n@dataclass(match_args=False)\nclass A:\n    x: int\n",
    "zip(strict=True)": "zip([1], [2], strict=True)\n",
    "int.bit_count()": "(5).bit_count()\n",
    "itertools.pairwise": "import itertools\nitertools.pairwise([1, 2])\n",
    "from itertools import pairwise": "from itertools import pairwise\n",
    "itertools.batched": "import itertools\nitertools.batched([1], 2)\n",
    "datetime.UTC": "import datetime\ndatetime.UTC\n",
    "import tomllib": "import tomllib\n",
    "int.from_bytes(b)": "int.from_bytes(b'ab')\n",
    ".to_bytes(n)": "x = 5\nx.to_bytes(4)\n",
    "math.cbrt": "import math\nmath.cbrt(8)\n",
    "math.exp2": "import math\nmath.exp2(3)\n",
    "math.sumprod": "from math import sumprod\n",
    "enum.StrEnum": "import enum\nclass A(enum.StrEnum):\n    pass\n",
    "typing.Self": "from typing import Self\n",
    "typing.TypeAlias": "from typing import TypeAlias\n",
    "typing.ParamSpec": "import typing\nP = typing.ParamSpec('P')\n",
    "typing.TypeGuard": "from typing import TypeGuard\n",
}
GOOD = {
    "future annotations allow unions": "from __future__ import annotations\ndef f(a: int | None) -> str | None:\n    pass\nclass A:\n    x: int | None = None\n",
    "builtin generics in annotations": "def f(a: list[int]) -> dict[str, tuple[int, ...]]:\n    pass\n",
    "to_bytes with byteorder": "x = 5\nx.to_bytes(4, 'big')\nx.to_bytes(4, byteorder='big')\nx.to_bytes(length=4, byteorder='little')\n",
    "library to_bytes with keywords": "m.to_bytes()\nm.to_bytes(force=True)\nm.to_bytes(True)\nm.to_bytes(stream_length=3)\n",
    "from_bytes with byteorder": "int.from_bytes(b'ab', 'big')\nint.from_bytes(b'ab', byteorder='little')\n",
    "library classmethod MapVariant.from_bytes": "m = MapVariant.from_bytes(data)\n",
    "integer bit-or": "a = 1 | 2\nb = x | y\nflags = FLAG_A | FLAG_B\n",
    "parenthesised with": "with (open('a') as f, open('b') as g):\n    pass\n",
    "walrus and dict union": "if (n := 3) > 2:\n    d = {1: 2} | {3: 4}\n",
    "math.isqrt and typing generics": "import math\nfrom typing import Dict, List, Optional\nmath.isqrt(9)\n",
    "match as an identifier": "import re\nmatch = re.match('a', 'a')\n",
    "local variable annotation": "def f():\n    x: int | None = None\n",
    "string annotation": "def f(a: 'int | None') -> 'str | None':\n    pass\n",
    "safe dataclass": "from dataclasses import dataclass, field\n@dataclass(frozen=True)\nclass A:\n    x: int = field(default=1)\n",
    "zip without strict": "zip([1], [2])\n",
    "suppression comment": "x.to_bytes(force)  # py39: ok\n",
    "f-string with different quotes": "x = {'a': 1}\ny = f\"{x['a']}\"\nz = f\"\"\"{x['a']}\"\"\"\n",
}


class TestLintItself(unittest.TestCase):
    def test_every_forbidden_construct_is_found(self):
        for name, source in sorted(BAD.items()):
            findings = lint.lint_source(source, name)
            self.assertTrue(findings, "the lint missed: " + name)

    def test_good_code_stays_quiet(self):
        for name, source in sorted(GOOD.items()):
            self.assertEqual(lint.lint_source(source, name), [], name)

    def test_findings_carry_file_and_line(self):
        findings = lint.lint_source("import os\nx = 5\nx.bit_count()\n", "demo.py")
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0].startswith("demo.py:3: "), findings)

    def test_syntax_error_is_reported_not_raised(self):
        findings = lint.lint_source("def broken(:\n", "broken.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("broken.py", findings[0])


if __name__ == "__main__":
    unittest.main()
