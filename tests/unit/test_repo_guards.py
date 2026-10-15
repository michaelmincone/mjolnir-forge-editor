"""U-17 and U-17b (SPEC 9.3): the repo guards.

* no ``.mvar`` / ``.bin`` / ``.blend`` / ``.dll`` under ``tests/`` or ``Addon/mvarlib/``;
* the independence scan of 9.1 (the G2 fixture builder must not import ``mvarlib`` or ``Addon``;
  the scanner is tested here, the real ``tests/fixturebuilder`` is scanned once G2 delivers it);
* ``tools/check_no_game_assets.py`` returns 0 on the real tree, 1 in a temp git repo that contains
  a planted ``.mvar`` or a file starting with ``_blf``, and (U-17b) 1 in a temp repo that carries a
  copy of the real ``.gitignore`` and plants ``tests/p.mvar``, ``dist/p.zip`` and ``scratch/d.dat``
  (first bytes ``_blf``), all gitignored, where ``git status --short`` shows nothing;
* ``git status --ignored --short`` of the real tree lists no ignored entry other than
  ``__pycache__/``, ``dist/`` and ``build/`` (plus Finder's ``.DS_Store``, which this repo's
  ``.gitignore`` also hides and which no tool here creates).
"""
import ast
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
GUARD = os.path.join(REPO, "tools", "check_no_game_assets.py")
FORBIDDEN_EXT = (".mvar", ".bin", ".blend", ".dll")
BLF = b"_blf" + b"\x00" * 44


def run_guard(cwd, *extra):
    # --root is explicit: the guard's default is the repository that holds the script, not the cwd
    args = list(extra)
    if "--root" not in args:
        args = ["--root", cwd] + args
    return subprocess.run([sys.executable, "-I", GUARD] + args, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, universal_newlines=True)


def git_env(home):
    env = dict(os.environ)
    env.update({"HOME": home, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
    return env


def git(args, cwd, env):
    return subprocess.run(["git"] + args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, universal_newlines=True).stdout


def plant(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def scan_independence(directory):
    """Hits for the T2 non-circularity rule (DEC-9.2): any import of ``mvarlib`` or ``Addon``."""
    hits = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(directory, name)
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [("." * node.level) + (node.module or "")]
                if node.level and any(a.name in ("Addon", "mvarlib") for a in node.names):
                    hits.append("%s:%d: from %s import %s" % (name, node.lineno, modules[0], node.names[0].name))
            for module in modules:
                root = module.lstrip(".").split(".")[0]
                if root in ("mvarlib", "Addon", "provider") or module.lstrip(".").startswith("Addon"):
                    hits.append("%s:%d: import %s" % (name, node.lineno, module))
        for lineno, line in enumerate(source.splitlines(), 1):         # dynamic imports and path hacks
            if re.search(r"(import_module|__import__)\s*\(\s*['\"](mvarlib|Addon)", line) or re.search(r"\.\.\s*/\s*Addon", line):
                hits.append("%s:%d: dynamic import of the library" % (name, lineno))
    return sorted(set(hits))


class TestNoGameFilesInTestsAndLibrary(unittest.TestCase):
    def test_no_forbidden_extensions(self):
        for top in (os.path.join(REPO, "tests"), os.path.join(REPO, "Addon", "mvarlib")):
            for root, dirs, files in os.walk(top):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for name in files:
                    self.assertFalse(name.lower().endswith(FORBIDDEN_EXT), os.path.join(root, name))
                    with open(os.path.join(root, name), "rb") as fh:
                        self.assertNotEqual(fh.read(4), b"_blf", os.path.join(root, name))


class TestIndependenceScan(unittest.TestCase):
    def test_scanner_finds_each_forbidden_form(self):
        bad = {
            "a.py": "import mvarlib\n",
            "b.py": "from mvarlib import codecs\n",
            "c.py": "from mvarlib.bitio import BitWriter\n",
            "d.py": "from ..Addon import mvarlib\n",
            "e.py": "import Addon.mvarlib.api\n",
            "f.py": "from Addon.mvarlib import api\n",
            "g.py": "import importlib\nm = importlib.import_module('mvarlib.api')\n",
            "h.py": "import provider\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in bad.items():
                with open(os.path.join(tmp, name), "w") as fh:
                    fh.write(text)
            hits = scan_independence(tmp)
            for name in bad:
                self.assertTrue(any(h.startswith(name + ":") for h in hits), (name, hits))

    def test_scanner_accepts_independent_code(self):
        good = "import struct\nimport hashlib\nfrom tests_helpers import x\nvalue = 'mvarlib is only a word here'\n"
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ok.py"), "w") as fh:
                fh.write(good)
            self.assertEqual(scan_independence(tmp), [])

    def test_real_fixture_builder_is_independent(self):
        builder = os.path.join(REPO, "tests", "fixturebuilder")
        if not os.path.isdir(builder):
            self.skipTest("tests/fixturebuilder does not exist yet (delivered by G2)")
        self.assertEqual(scan_independence(builder), [])


class TestGuardOnTheRealTree(unittest.TestCase):
    def test_exit_0_on_the_clean_tree(self):
        result = run_guard(REPO)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("check_no_game_assets: ok", result.stdout)

    def test_the_hash_allowlist_alone_also_passes(self):
        result = run_guard(REPO, "--base", "refs/does/not/exist")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("hash allowlist", result.stdout)

    def test_self_test(self):
        result = run_guard(REPO, "--self-test")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("--self-test: ok", result.stdout)

    def test_cannot_run_outside_a_repository_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_cwd = tmp
            result = subprocess.run([sys.executable, "-I", GUARD, "--root", env_cwd], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, universal_newlines=True,
                                    env=dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(tmp)))
            self.assertEqual(result.returncode, 2, result.stdout)

    def test_ignored_entries_are_only_the_allowed_kinds(self):
        try:
            out = git(["status", "--ignored", "--short"], REPO, dict(os.environ))
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        for line in out.splitlines():
            if not line.startswith("!! "):
                continue
            path = line[3:]
            last = path.rstrip("/").split("/")[-1]
            self.assertIn(last, ("__pycache__", "dist", "build", ".DS_Store"), "unexpected ignored entry: " + path)


class TestPlantedTempRepos(unittest.TestCase):
    """U-17: the guard refuses planted files in a temp git repository."""

    def make_repo(self, tmp, name):
        root = os.path.join(tmp, name)
        os.makedirs(root)
        git(["init", "-q"], root, git_env(tmp))
        return root

    def test_clean_temp_repo_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_repo(tmp, "clean")
            plant(root, "a.py", b"print(1)\n")
            git(["add", "-A"], root, git_env(tmp))
            result = run_guard(root)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_planted_mvar_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_repo(tmp, "mvar")
            plant(root, "maps/forge.mvar", b"x")
            result = run_guard(root)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("maps/forge.mvar", result.stdout)

    def test_planted_blf_magic_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_repo(tmp, "blf")
            plant(root, "notes.txt", BLF)
            result = run_guard(root)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("notes.txt", result.stdout)
            self.assertIn("_blf", result.stdout)

    def test_planted_game_like_extensions_exit_1(self):
        for ext in (".bin", ".blend", ".dll", ".png"):
            with tempfile.TemporaryDirectory() as tmp:
                root = self.make_repo(tmp, "ext")
                plant(root, "x" + ext, b"\x00\x01")
                self.assertEqual(run_guard(root).returncode, 1, ext)


class TestGitignoredPlants(unittest.TestCase):
    """U-17b: files hidden by the repo's own .gitignore must still be found."""

    def test_ignored_plants_are_found_although_git_status_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = git_env(tmp)
            root = os.path.join(tmp, "hidden")
            os.makedirs(root)
            git(["init", "-q"], root, env)
            with open(os.path.join(REPO, ".gitignore"), "rb") as src, open(os.path.join(root, ".gitignore"), "wb") as dst:
                dst.write(src.read())
            git(["add", ".gitignore"], root, env)
            git(["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                 "commit", "-q", "-m", "ignore rules"], root, env)
            plant(root, "tests/p.mvar", b"x")
            plant(root, "dist/p.zip", b"PK")
            plant(root, "scratch/d.dat", BLF)
            self.assertEqual(git(["status", "--short"], root, env).strip(), "", "the plants must be invisible to git status")
            result = run_guard(root)
            self.assertEqual(result.returncode, 1, result.stdout)
            for rel in ("tests/p.mvar", "dist/p.zip", "scratch/d.dat"):
                self.assertIn(rel, result.stdout)

    def test_pycache_is_not_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = git_env(tmp)
            root = os.path.join(tmp, "cache")
            os.makedirs(root)
            git(["init", "-q"], root, env)
            plant(root, "pkg/__pycache__/m.cpython-39.pyc", BLF)
            plant(root, "n.pyc", BLF)
            self.assertEqual(run_guard(root).returncode, 0)


if __name__ == "__main__":
    unittest.main()
