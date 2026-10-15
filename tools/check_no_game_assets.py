#!/usr/bin/env python3
"""Guard: fail if the working tree gains anything that looks like a game file.

Rule from the task: "Don't add any Microsoft game files to the repo."

A file is acceptable if it already exists in upstream ``origin/master`` with identical content
(so the binaries upstream ships, and its Wiki screenshots, are tolerated and must stay
byte-identical). Any other file that has a binary/game-looking extension, starts with the Reach
``_blf`` container magic, or is larger than the size limit is reported.

When the base ref is not available (no ``origin/master``: a fresh export, a CI checkout, a temp
repository) the same allowlist is taken from ``UPSTREAM_SHA256`` below: the SHA-256 of every
upstream file with a suspect extension (the three pre-existing binaries and the Wiki images;
DEC-F.1). Untracked files are listed WITHOUT ``--exclude-standard`` (DEC-F.2): the port's own
``.gitignore`` hides ``*.mvar``, ``*.zip``, ``dist/``, ``build/`` and ``scratch/``, so a game file
placed there would otherwise pass. Entries under ``__pycache__/`` and ``*.pyc`` are dropped.

Usage:  python3 -I tools/check_no_game_assets.py [--base origin/master] [--max-kb 512] [--root DIR]
        python3 -I tools/check_no_game_assets.py --self-test
Exit status 0 = clean, 1 = violations found, 2 = could not run.
Compatible with Python 3.9+.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

SUSPECT_EXT = {
    '.blend', '.blend1', '.mvar', '.bin', '.dll', '.exe', '.png', '.jpg', '.jpeg', '.gif',
    '.tif', '.tiff', '.tga', '.dds', '.bmp', '.psd', '.zip', '.7z', '.rar', '.gz', '.map',
    '.pck', '.mglo', '.fbx', '.obj', '.gltf', '.glb', '.wav', '.ogg', '.mp3', '.mp4', '.mov',
    '.bitmap', '.model', '.scenario', '.dylib', '.so',
}
BLF_MAGIC = b'_blf'

# SHA-256 of every upstream (origin/master, 8a167f0) file whose extension is in SUSPECT_EXT.
# Fallback allowlist for when the base ref is not available. The first three are the pre-existing
# binaries named in SPEC 11 / G0 (DEC-F.1); the Wiki screenshots are upstream documentation.
UPSTREAM_SHA256 = {
    'Addon/Resources/ForgeBridge.dll':
        'e129652334f945b425f970db6ff4abbb4094167116b79970aef408fd9e7e2e48',
    'Addon/Resources/Halo Reach.blend':
        'a76e1d74d985975aae475de82484af8d6431e613f5fd9d1eed7ee5add211e6ad',
    'Blender (Download a Release, Not Me!)/forge.blend':
        '35cc9130e00cb3a6eaa0f8995a5f8e70174ec8d26cfff7a63891777766515ae8',
    'Wiki/0.9.8.1_objects.jpg':
        'cb95e327492ef9aee54c9023743512c6da8fa24f67adfa635b8081d06aa89876',
    'Wiki/4_7_props.jpg':
        '48779e8ea0b521bd772c5cb7daaa01f433448079343bae331b7dab3c5442bcf5',
    'Wiki/add_palette.gif':
        '6e5a77a0c50bd3902e07cca7cd75908b9a7871018f58bac537d5dd430143fa21',
    'Wiki/add_palette.jpg':
        'a8637e43bfff0d929166da8633128c3e0a2243455c6979e7bbec7ca0ba39ad99',
    'Wiki/add_search.gif':
        '8b60e359ec643a60c930a54b5e0b2460f833165451ba087640402f9285b243e3',
    'Wiki/array.gif':
        'cbb4db60a201ffa9d7e34c4fe2a821be085ce3f5e85f4c147d1876fafd2600eb',
    'Wiki/array_mod.jpg':
        'ba3f190f1ab7bc5ae3efc1fc4f5c343310545a290c626d6503180b29dc8928a5',
    'Wiki/assembly_home.jpg':
        'efca9c98d5c0ac1128594bb420d10f2ee7f67a97296dc8f78f6f7b916263e5e7',
    'Wiki/assembly_tag_scenario.jpg':
        'a561514f01b4b27b1f3609b951e23bfa9a57a65f0f6d0ce026a2ef19f04a5caf',
    'Wiki/auto_script.jpg':
        '63ab2f807640215971e96631ffbd4793c199d7b63e8e32759029300a101c863c',
    'Wiki/blender_forgeworld_battleshipblockade.jpg':
        '692ae329f3b70dbb0af63f05d20fe23c68858682e24690134e5661b8a02fd9b8',
    'Wiki/coll.gif':
        '481b2b0fbf997c273c6e2bd7a8e1b9f11fe5c78f20644c27fe82e41e7b246846',
    'Wiki/color2.gif':
        '93dd19b5eee5ebb4230c8063168c160a5687c81a807ae068374dfa447efedec0',
    'Wiki/cursor.gif':
        'dba926cc7badcb5a2a3a724bda6d9fb2cff0ecfe34f25fd1d8af01b4decce73b',
    'Wiki/curve.gif':
        'f860b11ecc2f152637901c28b4d642c8ee28da20104be687a399b6eabb43a0b7',
    'Wiki/curve_edit.gif':
        '4210b371ee11c3b1fd3c82bc689b2aa4f1e52b9bb479cbf3c1d5d8c41a9de9fc',
    'Wiki/dll_error.jpg':
        '96888324235bc71fa219b6c62beb3d6058c8a626e671dfbefcfbb3fa80ccd104',
    'Wiki/download.jpg':
        '9bb0500ca5d233dc10cfd5a156058cd889b2b68997414b47c4709ae87dfaf79f',
    'Wiki/download_source.jpg':
        '843f7ca34e045a7b3c3e35f9a32aded828ca1c921a4fe9cfb751a836d82a07f0',
    'Wiki/dupe.gif':
        '4c14559cf278410bbd7d00ea2aa2d9322a01ba0c8c7ab14f76874d1c80bc4f78',
    'Wiki/export.jpg':
        'd8cdc7ae9eeda3c2056b42283ffa7f44c9ddd1dd10c2c754febf02b95f796e14',
    'Wiki/export_confirm.jpg':
        '468fc0aae72c9ccd619105ca031586a5306256c832125b9fec53e156d0525c34',
    'Wiki/forge_props.jpg':
        'b4eade5aa65c143b3edb9bc8ac1e69560b9ec1e409aee05dad365b82f61fdfb4',
    'Wiki/foundation_tag_scenario.jpg':
        'e7f2b3ad5e00fc72ec5428b5a31fadd3b5ba8140e47983cd23f6fea0772e54af',
    'Wiki/foundation_tag_scenario_xml.jpg':
        'aa8375a9554c9e65abae0ed624335f81e9d182b5cab582e4f4c242ed71536f9e',
    'Wiki/gametypeLabels.png':
        '6ae5fadd9d68a604c927bb245acdce17969f079c919cc1902a184d5e657144ba',
    'Wiki/hidden.jpg':
        '3c8ec96246760c37a02804611dae41ddac285bb9241c53ce4d31819387caa0de',
    'Wiki/import-export.gif':
        '5107f7ae9bf32965339c21cac4e2b1c2ac8b73d449739572ed29fa65723a593f',
    'Wiki/import.jpg':
        '25952b416ac669d39f9ab9bb994a76557eb89f729793e60c2d3d5819a8166df9',
    'Wiki/invis.jpg':
        'ce6f58673df9539721259e032be3a78e045b390c5fe46597db030d24e4475193',
    'Wiki/mcc_creepforgeworld_battleshipblockade.jpg':
        '32ca4a71cafc05ea28ec3b691632420b36dc5344e2627672f11fef803692e4eb',
    'Wiki/mcc_creepforgeworld_errorshipblockade.jpg':
        'c0f8a3e41eb240c74c841d7e2e8796912dc4ee86278538a1bb5c2d70fa91f28d',
    'Wiki/mcc_creepforgeworldnight_battleshipblockade.jpg':
        '7b1284a56d0097254e38318d73a2a04031b7cd0da1bf06ed3c0c6d7c2295e057',
    'Wiki/rotate.gif':
        'c285d31bde018f7378f25b195c1fd9aec62eb3d29bcc41298c14b4882c5aab24',
    'Wiki/script_old.jpg':
        'aca038510b92d9a925ecb74277ed5358fe1ab62c55f7760f58dbe724397b0518',
    'Wiki/spiral.gif':
        '27239066e73f0e0700b94c7fe09e41e2c3b782e04b2a1256ef31a37293f71058',
    'Wiki/steam.jpg':
        '5e53c61d6191eef40cc7bbc597778235e546065621161c62f2d2b7db7729cd27',
    'Wiki/vstudio_build_succeeded.jpg':
        '392b9172385004a62abf80a0d9a4e84b9ef9bf1e46321e3ce3bbeedcb3ec0538',
    'Wiki/vstudio_forgebridge.jpg':
        '909d104e48ddff7b1080de06cf1e936a187ada5f6ab6cfb62755f2f217035e45',
    'Wiki/vstudio_itemparser_collapsed.jpg':
        '9f4b1230c1d663be53f6b84a800bc38f5ba38ce8c44044dc779e87691d0d5ae3',
    'Wiki/vstudio_itemparser_find_replace.jpg':
        '4076cff31afdb8e60c4694c4db2486a7622baf47a89ecccbe1700a0f6390af12',
    'Wiki/vstudio_itemparser_map_reference.jpg':
        'be3407cce97cb38febb8bb1e4dffea7b5752e6300605670907fda47a4676432c',
    'Wiki/vstudio_itemparser_menu_items.jpg':
        '40a88077ab7f046aa29a77129e37131d8e32e99be48ac953d8ff8228a5461ae0',
    'Wiki/vstudio_map.jpg':
        'f0ca2228b47e2e0d4a0720a0ad2d0abc01333e9d8fb1f7f0bd85e18752453166',
}


def git(args, root, env=None):
    return subprocess.run(['git'] + args, cwd=root, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True, env=env).stdout


def is_dropped(rel):
    """Untracked entries that are never reported: compiled Python bytecode only (DEC-F.2).

    Only ``*.pyc`` / ``*.pyo`` are dropped, so a game file hidden inside a ``__pycache__/``
    folder is still reported (lint finding from the G0 verification).
    """
    return rel.endswith(('.pyc', '.pyo'))


def _expand_dir_entry(root, rel):
    """``git ls-files --others`` reports a nested git repository as ``dir/``; walk it."""
    out = []
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, rel)):
        dirnames[:] = [d for d in dirnames if d != '.git']
        for name in filenames:
            full = os.path.join(dirpath, name)
            out.append(os.path.relpath(full, root).replace(os.sep, '/'))
    return out


def list_files(root):
    """Return ``(tracked, untracked)``; untracked INCLUDES gitignored files (DEC-F.2)."""
    tracked = git(['ls-files', '-z'], root).decode('utf-8', 'surrogateescape').split('\0')
    untracked = git(['ls-files', '-z', '--others'], root).decode('utf-8', 'surrogateescape').split('\0')
    expanded = []
    for p in untracked:
        if not p:
            continue
        if p.endswith('/'):
            expanded.extend(_expand_dir_entry(root, p))
        else:
            expanded.append(p)
    return [p for p in tracked if p], [p for p in expanded if not is_dropped(p)]


def load_base(root, base):
    """``{path: blob id}`` of the base ref, or ``None`` when the ref does not exist."""
    try:
        out = git(['ls-tree', '-r', '-z', base], root)
    except subprocess.CalledProcessError:
        return None
    blobs = {}
    for line in out.decode('utf-8', 'surrogateescape').split('\0'):
        if not line:
            continue
        meta, path = line.split('\t', 1)
        blobs[path] = meta.split()[2]
    return blobs


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def find_violations(root, tracked, untracked, base_blobs, max_kb=512, allow_sha=None):
    """Return a list of violation strings. ``base_blobs`` None means "use ``allow_sha``"."""
    allow_sha = UPSTREAM_SHA256 if allow_sha is None else allow_sha
    problems = []
    for rel in sorted(set(tracked + untracked)):
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            continue  # deleted in the working tree
        ext = os.path.splitext(rel)[1].lower()
        if base_blobs is not None and rel in base_blobs:
            # pre-existing upstream file: must be unchanged
            h = git(['hash-object', '--', rel], root).decode().strip()
            if h != base_blobs[rel] and ext in SUSPECT_EXT:
                problems.append('%s: upstream binary was modified' % rel)
            continue
        if base_blobs is None and rel in allow_sha:
            if sha256_file(full) == allow_sha[rel]:
                continue
            if ext in SUSPECT_EXT:
                problems.append('%s: upstream binary was modified' % rel)
            continue
        size = os.path.getsize(full)
        with open(full, 'rb') as fh:
            head = fh.read(4)
        if ext in SUSPECT_EXT:
            problems.append('%s: new file with binary/game-like extension (%s)' % (rel, ext))
        elif head == BLF_MAGIC:
            problems.append('%s: starts with the Reach _blf container magic' % rel)
        elif size > max_kb * 1024:
            problems.append('%s: new file larger than %d KB (%d bytes)' % (rel, max_kb, size))
    return problems


def run(root_arg, base, max_kb, allow_sha=None):
    """Return ``(exit status, output lines)``."""
    try:
        root = git(['rev-parse', '--show-toplevel'], root_arg).decode().strip()
        base_blobs = load_base(root, base)
        tracked, untracked = list_files(root)
    except (subprocess.CalledProcessError, OSError) as exc:
        return 2, ['check_no_game_assets: cannot inspect repository: %s' % exc]
    problems = find_violations(root, tracked, untracked, base_blobs, max_kb, allow_sha)
    where = base if base_blobs is not None else 'the built-in hash allowlist (%s not found)' % base
    if problems:
        return 1, ['check_no_game_assets: FAILED'] + ['  ' + p for p in problems]
    return 0, ['check_no_game_assets: ok (%d files checked against %s)' % (len(set(tracked + untracked)), where)]


# ---------------------------------------------------------------------------------------------
# --self-test: planted bad temp repositories must be refused, clean ones accepted
# ---------------------------------------------------------------------------------------------
def _git_env(home):
    env = dict(os.environ)
    env.update({'HOME': home, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_TERMINAL_PROMPT': '0'})
    return env


def _make_repo(parent, name, gitignore_text=None):
    root = os.path.join(parent, name)
    os.makedirs(root)
    git(['init', '-q'], root, _git_env(parent))
    if gitignore_text is not None:
        with open(os.path.join(root, '.gitignore'), 'w') as fh:
            fh.write(gitignore_text)
    return root


def _plant(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(data)


def self_test(repo_gitignore):
    """Run the guard against temp repositories; return 0 when every case behaves as required."""
    failures = []
    with open(repo_gitignore, 'r') as fh:
        real_ignore = fh.read()
    with tempfile.TemporaryDirectory(prefix='nogame-selftest-') as tmp:
        env = _git_env(tmp)

        def expect(label, root, want, must_mention=(), must_not_mention=(), allow_sha=None):
            status, lines = run(root, 'origin/master', 512, allow_sha)
            text = '\n'.join(lines)
            ok = status == want and all(m in text for m in must_mention) and not any(m in text for m in must_not_mention)
            print('  %-58s %s' % (label, 'ok' if ok else 'FAILED (exit %d, wanted %d)' % (status, want)))
            if not ok:
                failures.append(label)
                print(text)

        clean = _make_repo(tmp, 'clean', real_ignore)
        _plant(clean, 'a.py', b'print(1)\n')
        _plant(clean, 'notes.md', b'# hi\n')
        git(['add', '-A'], clean, env)
        expect('clean repo (real .gitignore) -> 0', clean, 0)

        bad_ext = _make_repo(tmp, 'bad_ext')
        _plant(bad_ext, 'maps/forge.mvar', b'not a real map\n')
        expect('planted .mvar -> 1', bad_ext, 1, ['maps/forge.mvar'])

        bad_magic = _make_repo(tmp, 'bad_magic')
        _plant(bad_magic, 'data/blob.dat', b'_blf' + b'\0' * 32)
        expect('file starting with _blf -> 1', bad_magic, 1, ['data/blob.dat'])

        big = _make_repo(tmp, 'big')
        _plant(big, 'big.txt', b'x' * (600 * 1024))
        expect('new file over 512 KB -> 1', big, 1, ['big.txt'])

        hidden = _make_repo(tmp, 'hidden', real_ignore)       # U-17b: everything planted is gitignored
        git(['add', '.gitignore'], hidden, env)
        git(['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false',
             'commit', '-q', '-m', 'ignore rules'], hidden, env)
        _plant(hidden, 'tests/p.mvar', b'x')
        _plant(hidden, 'dist/p.zip', b'PK')
        _plant(hidden, 'scratch/d.dat', b'_blf' + b'\0' * 32)
        status_text = git(['status', '--short'], hidden, env).decode()
        if status_text.strip():
            failures.append('hidden repo not hidden')
            print('  git status --short is not empty in the hidden repo: %r' % status_text)
        expect('gitignored p.mvar, p.zip, d.dat (U-17b) -> 1', hidden, 1,
               ['tests/p.mvar', 'dist/p.zip', 'scratch/d.dat'])

        cache = _make_repo(tmp, 'cache', real_ignore)
        _plant(cache, 'pkg/__pycache__/m.cpython-39.pyc', b'_blf' + b'\0' * 32)
        _plant(cache, 'm.pyc', b'_blf' + b'\0' * 32)
        expect('__pycache__ and *.pyc are ignored -> 0', cache, 0)
        _plant(cache, 'pkg/__pycache__/x.mvar', b'x')
        expect('a .mvar inside __pycache__/ is NOT dropped -> 1', cache, 1, ['pkg/__pycache__/x.mvar'])

        nested = _make_repo(tmp, 'nested', real_ignore)       # a nested git repository hides its files from the parent
        _plant(nested, 'tests/ok.py', b'print(1)\n')
        git(['init', '-q'], os.path.join(nested, 'tests'), env)
        _plant(nested, 'tests/inner/a.mvar', b'x')
        expect('a .mvar inside a nested git repository -> 1', nested, 1, ['tests/inner/a.mvar'])

        # hash allowlist fallback (no origin/master in these repos)
        allow = _make_repo(tmp, 'allow')
        payload = b'synthetic stand-in for an upstream binary\n'
        _plant(allow, 'bin_like/up.dll', payload)
        digest = hashlib.sha256(payload).hexdigest()
        expect('allowlisted hash, base missing -> 0', allow, 0, allow_sha={'bin_like/up.dll': digest})
        _plant(allow, 'bin_like/up.dll', payload + b'x')
        expect('allowlisted path with other content -> 1', allow, 1, ['upstream binary was modified'],
               allow_sha={'bin_like/up.dll': digest})
        expect('same file without allowlist -> 1', allow, 1, ['bin_like/up.dll'], allow_sha={})

        # base ref present: files identical to it are accepted, anything new is not
        based = _make_repo(tmp, 'based')
        _plant(based, 'bin_like/up.dll', payload)
        git(['add', '-A'], based, env)
        git(['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false',
             'commit', '-q', '-m', 'upstream'], based, env)
        git(['update-ref', 'refs/remotes/origin/master', 'HEAD'], based, env)
        expect('file identical to origin/master -> 0', based, 0, must_not_mention=['hash allowlist'])
        _plant(based, 'new.png', b'\x89PNG')
        expect('new .png next to an unchanged base file -> 1', based, 1, ['new.png'])
        os.remove(os.path.join(based, 'new.png'))
        _plant(based, 'bin_like/up.dll', payload + b'changed')
        expect('modified upstream binary -> 1', based, 1, ['upstream binary was modified'])
    print('check_no_game_assets --self-test: %s' % ('ok' if not failures else 'FAILED (%s)' % ', '.join(failures)))
    return 0 if not failures else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--base', default='origin/master', help='upstream ref used as the allowlist')
    ap.add_argument('--max-kb', type=int, default=512, help='size limit for files not in the base')
    ap.add_argument('--root', default=None,
                    help='directory inside the repository to check (default: the repository that holds this script)')
    ap.add_argument('--self-test', action='store_true', help='check the guard against planted temp repositories')
    args = ap.parse_args(argv)
    if args.self_test:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            return self_test(os.path.join(here, '.gitignore'))
        except (subprocess.CalledProcessError, OSError) as exc:
            print('check_no_game_assets: cannot run the self-test: %s' % exc, file=sys.stderr)
            return 2
    root_arg = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    status, lines = run(root_arg, args.base, args.max_kb)
    for line in lines:
        print(line, file=sys.stderr if status == 2 else sys.stdout)
    return status


if __name__ == '__main__':
    sys.exit(main())
