# S1prep notes: preparing the block star (NOTES.md D10 / D10a)

Path update (2026-10-21): existing checkout and tool references use the current `~/Documents/Halo_MCC/` layout. References to `real-mvar-samples/`, `maps/headstrong-star/` are historical artifacts absent from this checkout; examples requiring them are not ready to run. Recorded test results and literal historical default strings are unchanged.

Written for the orchestrator to merge into `NOTES.md`; `NOTES.md` itself was not edited. Nothing was committed (working tree
only, git state untouched). Section numbers ("SPEC 5.6") refer to `docs/mvar/SPEC-mvar.md`. The procedure for the real file is
`docs/mvar/STAR_BUILD.md`. Everything here was built and tested against the stub providers and the synthetic stand-in library;
**no star has been written by the real writer (G5 does not exist), nothing is verified in game.**

## What exists now

| file | content |
|---|---|
| `tools/star_layout.py` | pure geometry (stdlib, no `bpy`, no I/O): the true five-pointed star polygon (mirror-symmetric to the last bit), `star_cells(n, mode)` (filled / outline, reading order, deterministic), `fit_grid` (the largest of 17, 15, 13, 11, 9 that fits a number of free slots), `render_cells` (the shape as text), `tip_cells`, `Footprint`, `cell_positions` (neighbours exactly one footprint apart), `mesh_boxes`, `check_bounds` (library `[min, max)` rule plus a margin on the whole mesh box), `choose_centre`, `position_tolerance`, `match_positions` |
| `tools/build_star_mvar.py` | the Blender script (usage in its docstring and `--help`); pure parts importable without Blender (argument parsing, output path policy, block ranking, 650 pre-flight, container / hash checks, record verifier, report parser) |
| `tools/run_star_build.sh` | wrapper: isolated Blender profile in a scratch folder (outside the repo), `Addon/` linked in as `mjolnir_forge`, runs the script, passes its exit status on |
| `tools/run_star_tests.sh` | runs the Blender star test (package + isolated profile, or `--dev`) and with `--unit` the pure tests on 3.9 and 3.13 |
| `tests/unit/test_star_layout.py` | 62 tests (61 + the pin of the auto grids' connectivity): polygon, cell count 60..120 (80), exact symmetry for n = 5..39, five tips, 4- and 8-connectivity, outline, no duplicates, determinism, spacing = block size, touching without overlap, centring, offsets, bounds and margin, auto grid, tolerance, matching, purity (imports `math` only) |
| `tests/unit/test_star_build_tool.py` | 79 tests (59 + 20 after the verification: library resolution, case-insensitive paths, no bytecode, wrapper shape): command line, path policy, ranking (incl. the `Block, 1x4` regression), pre-flight, container and hash checks on synthetic files and (read-only, skipped loudly if absent) the real file, the record verifier (each mistake caught), report parser, the library-free file checks, the diff report, module shape |
| `tests/unit/test_star_roundtrip_stub.py` | 27 tests of the new test double |
| `tests/stubs/stub_roundtrip.py` | NEW test double: wraps `stub_mvarlib` and REMEMBERS what it writes (`ROUNDTRIP = True`); a few library-like refusals; templates chosen by their bytes (`map_template(id)`, `ODD_EXAMPLE_TEMPLATE`, `NO_BLOCKS_TEMPLATE`, `real_like_template(count)`); `CORRUPT` modes that write a deliberately wrong file; `QUOTA_MAX`. `stub_mvarlib.py` itself is untouched |
| `tests/blender/s1_star_stub.py` | the Blender test `s1` (see below) |
| `tests/blender/s1_make_odd_library.py` | NEW (round 2): child-Blender helper that builds the stand-in library with a `Block, 1x1` of 1.0182 x 1.0182 x 1.0 like the real one |
| `docs/mvar/STAR_BUILD.md` | the procedure for the real file, options, what is printed, refusals, caveats |

Not touched: `Addon/**`, `NOTES.md`, `tests/blender/run_all.py` and `tools/run_blender_tests.sh` (another agent was editing them
while this was written), `tests/stubs/stub_mvarlib.py`, `api.py`, `errors.py`, any original, any upstream binary.

## How to run

```
cd ~/Documents/Halo_MCC/mjolnir-forge-editor/source
/usr/bin/python3 -I tools/run_tests.py --only test_star_layout test_star_build_tool test_star_roundtrip_stub
/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13 -I tools/run_tests.py --only test_star_layout test_star_build_tool test_star_roundtrip_stub
tools/run_star_tests.sh --unit            # Blender test s1 (package + isolated profile) and the pure tests on both interpreters
tools/run_star_tests.sh --dev             # the same Blender test with the fast loop (Addon/ symlinked)
# or the plain command (add-on enabled at startup, stub provider, stand-in library built by the test):
$BL -b --factory-startup --python-exit-code 1 --addons <module> --python tests/blender/s1_star_stub.py -- --provider stub
# the star itself, stub rehearsal (keeps nothing), then the real one once G5 exists:
tools/run_star_build.sh --template T.mvar --out ~/Documents/Halo_MCC/mjolnir-forge-editor/forge-workspace/maps/headstrong-star/star.mvar --provider stub --real-library   # or MJOLNIR_LIBRARY=<stand-in> instead of --real-library
tools/run_star_build.sh --template ~/Documents/Halo_MCC/mjolnir-forge-editor/forge-workspace/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar --out ~/Documents/Halo_MCC/mjolnir-forge-editor/forge-workspace/maps/headstrong-star/breakneck_star.mvar --real-library [--dry-run]
```

## Results

All on 2026-10-10, Blender 5.2.1 LTS (Python 3.13.13) and system Python 3.9.6, after the last edit of any star file (round 2, after the
independent verification; the round-1 numbers were 147 / 809 tests).

| run | result |
|---|---|
| star pure tests (`--only test_star_layout test_star_build_tool test_star_roundtrip_stub`) | **168 passed, 0 failed, 0 skipped** on 3.9.6 and on 3.13.13 (62 + 79 + 27) |
| whole pure suite `tools/run_tests.py --samples` | **830 passed, 0 failed, 2 skipped** on each interpreter (113 s on 3.9, 79 s on 3.13). The two skips are not mine: `test_load_placeholder_raises_until_g3_replaces_it` (G3 has landed) and the optional research-table cross-check of G0. U-21: the 25 sample / protected files unchanged. Includes the 3.9 import scan of every `tools/*.py` and the py39 lint over `tools/` and `tests/` |
| Blender star test `tests/blender/s1_star_stub.py` | **PASS** with the add-on installed as an extension (`tools/run_star_tests.sh --unit`, 43 s with the pure tests) and with the dev loop (`--dev`, 30 s), provider stub, stand-in libraries (also in a copy of the repository WITHOUT `Addon/Resources`, so the test never needs the real game library) |
| `tools/run_blender_tests.sh` (not changed by this work, run to confirm) | ALL BLENDER RUNS PASSED, 18 passed, 0 failed, 0 skipped (b01 to b23) |
| `tools/check_no_game_assets.py` | ok (251 files checked) |
| originals | SHA-256, size and modification time of `real-mvar-samples/0aaaf8c7-...mvar` (`e514a53b...b254`, 59,392 bytes, mtime 1791603751) and of `Addon/Resources/Halo Reach.blend` (`a76e1d74...e6ad`, 57,276,220 bytes, mtime 1791572703) identical before and after the round-2 dry runs |
| dry run against the real files through the wrapper (read-only; real reader of G3, real library linked read-only, `--real-library`, relative `--out` from another directory) | the log names `library  : .../Addon/Resources/Halo Reach.blend (--real-library; linked read-only; sha256 a76e1d74d985975a)`; reaches `forge.add_object` x 34 and stops at `NotImplementedError("G5")`: "The real writer is not available yet", exit 1, nothing written. Without `--real-library` (and no `$MJOLNIR_LIBRARY`) the same command is refused before anything is linked: exit 2 |
| `--provider stub-roundtrip --real-library` on a synthetic Forge World template (round 1) | verification table all PASS (80 blocks, real `Block, 1x1` mesh box 1.0182 x 1.0182 x 1.0 measured from the real library), library hash unchanged |

## What the Blender test `s1` covers (`tests/blender/s1_star_stub.py`, stub + stand-in library only)

* **End to end against the plain stub**: the stub's `LAST_EXPORT` holds the five original objects (slots and tokens, handed back
  exactly as imported: `record_vs_export` finds no difference) and 80 new ones (`slot is None`, no token, type name `Block, 1x1`
  which is a stock object of the map with the id of the template's own block `0x4600`, physics Fixed, flags equal to the
  example's, forward (0, 1, 0), up +Z), the blocks form the star (rebuilt from the positions), positions equal the layout, the
  gate is ticked, `imported_slots` and `max_objects` are right; the file is kept only with `--allow-stub-output`.
* **Against the remembering double**: the whole verification passes; each of seven deliberately wrong files (block dropped,
  shifted, not Fixed, other type, extra block, original changed, hash recipe changed) is caught, renamed `*.REJECTED`, exit 1.
* **Refusals write no file** (and add nothing): 650 limit (the exact boundary from the canned 5 objects: grid n refused, n-1
  passes), non-stock name (nonsense, and a real name that is not stock on this map), centre outside the bounds on each axis,
  margin too large, the star's top exactly at the margin passes and half a unit further does not, bad grid / mode, missing
  template, output inside the repo / a sample folder / beside the template / equal to it / through a symlink / wrong extension /
  existing (untouched, replaced only with `--overwrite`), library refusals (not about the block: one attempt; `E_QUOTA`: the
  next block type is tried in auto mode, never for an explicit `--block`; flags: copied from the example or `E_FLAG_UNVERIFIED`;
  rotation gate), real library not implemented (`NotImplementedError` from the loader / the writer: a clear message), template
  the library refuses, no object library.
* **Real-file shape** (`real_like_template`: 610 objects, no block, bounds +-20000): auto grid 11 / 34 blocks; explicit 17 refused
  with "at most 40"; outline grid 15 = 40 blocks = exactly 650 passes; 640 objects leave no room for any star; a star away from every
  object is allowed with a warning; the position tolerance follows the 23-bit cell.
* **Footprint measurement**: scale, quarter turn, instance offset and a parent are all applied; no mesh gives no footprint.
* **Repeated runs in one Blender session** (found by the scratch-folder test, which reused one scene for several builds: a real bug): the star's collection used to stay the
  active one, so the next import put the template's objects into it and the next run deleted them (`ReferenceError`). Now the active
  collection is restored, blocks carry the custom property `mj_star` and only marked objects are ever deleted, wherever they are; three
  runs in a row, and an unmarked object of the user's in the star collection, are tested.
* **Scratch folders**: a stub or `--dry-run` export goes to a private folder under `$TMPDIR`; if `$TMPDIR` is inside the repository the run
  stops before creating anything (the wrappers check it too).
* **A child Blender** run the way the owner will (`--provider stub-roundtrip`): exit 0 and the report; `--cells 60` exits 2 with
  `E_TOO_MANY`; an output in the repo exits 2 and writes nothing; a bad command line exits 2; `--help` exits 0.

* **Round 2 scenarios**: `scenario_spacing_is_the_measured_mesh_box` (odd stand-in library: column step 1.0182, row step 1.0, footprint,
  bounds, library-untouched PASS); `scenario_library_resolution` (the preference overriding `--real-library` is refused and names both
  files; a preference without the flag is honoured, measured and named in the log; the real library is refused when `$MJOLNIR_LIBRARY` names
  it and, in the dev loop, when nothing is set and the add-on falls back to `Resources`; nothing is linked in any refusal);
  `scenario_wrapper_in_a_scratch_checkout` (`tools/run_star_build.sh` from a copy of the checkout without the game library: relative
  `--template` / `--out` from another directory, the output where the caller meant, no `__pycache__` in the copy, a relative `--out` from
  inside the copy refused, the no-library fallback refused with exit 2); the end-to-end scenario also asserts the `library  :` line and
  the "object library untouched" PASS; the path-policy scenario adds the mis-cased repository / template-folder spellings (skipped on a
  case-sensitive volume).

Mutation check (a throw-away copy of `tools/`, `tests/` and `Addon/` in a scratch folder, not kept; 39 mutants of `star_layout.py`,
`build_star_mvar.py` and the double, each run against the three pure test files and, when needed, `s1`): **38 killed, 1 equivalent**.
Killed include: wrong inner ratio, the footprint offset ignored, the z step using the width, the margin ignored, the upper bound
inclusive, a tiny tolerance, `fit_grid` off by one, many-to-one matching, an outline that keeps the interior; blocks not Fixed, flags not
copied, the gate never ticked, no 650 check, the repository / sample-folder / beside-the-template / existing-file checks removed, positions
never failing, originals not compared, header drift ignored, a bad file not renamed, the plan penalty dropped from the ranking (the
`Block, 1x4` regression), a retry on any refusal, the outside-bytes check, the trailer check, the hash-recipe comparison, the instance
offset ignored, the ground height ignored, `auto` always 17, the template fingerprint not compared, star blocks left in the scene for the
re-import, the active collection not restored, a removal that is not limited to marked blocks, a scratch folder allowed inside the repository,
a dry run that keeps its file, unstable block names, an explicit block that never warns. The first round let five survive;
each was a missing test (the upper-bound message, the library-free file checks `_file_checks`, the leftover star blocks, the warning for
an explicit block that is not in the template) and was added. The one equivalent mutant: removing `abs()` from the cell sampling (ray
casting is symmetric for this exactly mirrored polygon for every n from 5 to 64 and for 2000 random radii; `abs()` stays as a guarantee
by construction).

## Decisions (most reasonable choice made, work continued)

1. **`--cells` is the grid size N, default `auto`.** The task says "default N chosen so the star has roughly 60-120 cells":
   `star_layout.DEFAULT_GRID = 17` gives 80 filled cells. But the real file has 610 of 650 objects, so only 40 slots are free and
   80 blocks cannot be added. `auto` (the default) takes the largest of 17, 15, 13, 11, 9 that fits (here 11: 34 blocks); an
   explicit N is refused when it does not fit, never shrunk silently. Odd sizes only for auto (the apex sits on one column).
2. **The star lies in the XZ plane** (one layer deep along Y, apex +Z) and every block keeps the identity rotation that
   `forge.add_object` gives (forward +Y, up +Z): the only orientation written is pure yaw, as SPEC 5.6 / DEC-5.6 allow, with the
   gate ticked (loud NOTE). Cells are sampled with `abs(x)`, the polygon is built mirror-symmetric: symmetry is exact, not approximate.
3. **Block choice**: stock blocks of the Building Blocks group that are stock on the map, never `Invisible`; ranked by tiers (in
   the template and cube-like; in the template; cube-like; rest), inside a tier the better shape, then the smaller block, then more
   examples, then the name. "Cube-like" = square face in the star's plane AND as deep as wide. **A regression the first real dry run
   found**: ranking by the face alone chose `Block, 1x4` (a square face, four deep) over `Block, 1x1`; fixed and pinned
   (`test_a_long_block_is_never_preferred_to_the_one_by_one`, with the measured mesh boxes as numbers).
4. **Spacing is the measured mesh box** of the library model (`Block, 1x1`: 1.0182 x 1.0182 x 1.0 in the real library, 1 x 1 x 1 in
   the stand-in), with rotation, scale, parent chain and the collection's instance offset applied and the box centre relative to
   the object origin taken into account. It is not the game's collision box (unknown).
5. **Centre**: x, y = the middle of the bounds (the task text); z = the star's bottom edge on the median height of the template's
   own objects (shifted into the bounds, never clamped silently), `--center` overrides each part. The script prints where the
   template's own objects are and warns when the star lies outside that area (the real file's bounds are +-20000 although the map
   is 58 units across; here the middle is the middle of the map only because the map is centred on the origin).
6. **Flags**: when the template holds a block of the chosen type, its symmetry, place-at-start, game-specific, team, colour and
   class are copied onto the new blocks (the most common combination among several examples, lowest slot on a tie), so SPEC 5.6's
   "a property that differs from the learned example is refused with `E_FLAG_UNVERIFIED`" cannot hit; spawn sequence, time, label
   and `other_*` stay at their defaults (an example may be a SCALE-labelled block). Colour is written only with `--color`.
7. **The exporter is the only validator and the only writer**: the script runs `export_scene.mjolnir_mvar` itself and reads its
   text report (`ERROR|WARNING <CODE>` lines), instead of building `ExportOptions` a second time. Block-dependent refusals
   (`E_QUOTA`, `E_FLAG_UNVERIFIED`, `E_CACHED_TYPE_UNKNOWN`, `E_OBJ_*`, `E_FOLDER_RANGE`, `E_TYPE19_UNDETERMINED`) make auto mode try the
   next block type (at most 6); anything else, or an explicit `--block`, stops. This is also how "pick a block whose quota maximum
   allows it" (D10a) is done: the quota rows are not visible through the frozen API.
8. **Independent verification of the output** (does not trust the writer): records via `load_map_variant` (originals equal, new objects
   counted / typed / positioned within tolerance / Fixed / vertical, header and body fields unchanged, occupied count), and without the
   library: the block list and all bytes outside the `mvar` hash, stored length and bit stream (including the 29,911 zero bytes after
   `_eof`) identical, the SHA-1 recomputed with the template's recipe and length byte order, the template and the object library
   unchanged on disk, and a re-import by the add-on itself. The position tolerance is twice the position cell (at most
   0.00052084, or range / 2^23 for a huge range) plus two float32 spacings at the largest coordinate: 0.0011 for a +-240 axis,
   0.0134 on the real file's 23-bit axes.
9. **A file that fails verification is renamed `<out>.REJECTED`** (not deleted); a refusal writes nothing; the report is
   `<out>.report.txt` beside a written file only. Exit status 0 / 1 / 2 (verified to survive `sys.exit` in Blender 5.2.1).
10. **Stub semantics**: `--provider stub` is a rehearsal: the export goes to a private scratch folder (outside the repo, removed at
    the end) unless `--allow-stub-output` is given, because the plain stub's output is a copy of the template and must never be
    mistaken for a deliverable; its read-back checks are SKIPped (it cannot remember). `--provider stub-roundtrip` is the new double.
    `--dry-run` does the same for any provider. The default provider is `real`; when G5 lands nothing else changes.
11. **Output path policy** (more than `P.check_output_path`, which the exporter still applies): `.mvar` only; not inside the repo;
    not in a sample folder (a mirror of `mvarlib.io.DEFAULT_PROTECTED` incl. `real-mvar-samples`, plus `$MJOLNIR_SAMPLES` and
    `$MJOLNIR_PROTECTED`); not in the template's folder ("never beside the originals"); not the template, also through a symlink or a
    hard link; not an existing file without `--overwrite`. Checked before Blender is touched; nothing is created by the check.
12. **No change to `Addon/**`, `run_all.py`, `run_blender_tests.sh`** (others were editing them): the star test is its own command
    (`tools/run_star_tests.sh`) and is not part of `run_all`. With `--provider real` the test would SKIP (needs the stub), as
    every stub-data test does.
13. `tools/` is not packaged (`build_package.py` stages `Addon/` only); the star tools never import the Blender add-on at module
    level so `tests/unit/test_py39_syntax.py`'s import scan of `tools/*.py` passes on 3.9.

## Findings about the real file (data points for the orchestrator; read-only, reader of gate G3 as it was at 01:30 on 2026-10-10)

* `Breakneck` (10050), "Headstrong", version 31, `plain4`, hash `plain_le32` with big-endian L (re-derived here WITHOUT the library
  by `build_star_mvar.hash_flavour`: `('>', 'plain_le32', 13311)`, confirming D9), axis bits 23, 23, 23 (bounds +-20000 on every axis),
  quota count 82, budget 3885 of 10000 (raw words).
* **610 objects** (248 Respawn Point, 108 Initial Spawn, 47 Flag Stand, 25 Hill Marker, 23 Respawn Zone, 20 Frag Grenade, 48 types in
  all), **no block of any kind**, all 610 ids in the stock table, 403 vertical and 207 tilted, extents x -28.8..29.0, y -29.0..29.6,
  z 2.1..21.7 (median 5.4). Consequences: 40 free slots (the default 80-block star cannot be added), the object class of a new block
  cannot be learned (SPEC 7.4 assumed-class rule with `W_CACHED_TYPE_ASSUMED`, unverified), and no `--keep-unrecognised` is needed.
* A dry run of the whole script with `--real-library` (real reader, real library read-only, hash of the library and the template
  unchanged) reaches `forge.add_object` x 34 and stops at the export with `NotImplementedError("G5")`, reported as "The real writer is
  not available yet", exit status 1, nothing written.

## Deviations from the task text

* `--cells` also accepts `auto` and defaults to it (decision 1); the task's "default N" is `star_layout.DEFAULT_GRID = 17`.
* `--provider` has a third value `stub-roundtrip` (a test double, decision 10) and the script has extra options (`--outline`,
  `--center`, `--margin`, `--color`, `--keep-unrecognised`, `--no-rotation-gate`, `--overwrite`, `--dry-run`, `--allow-stub-output`,
  `--addon-module`, `--grid`).
* The Blender test is `tests/blender/s1_star_stub.py` run by `tools/run_star_tests.sh`, not by `tools/run_blender_tests.sh`
  (decision 12).
* "type ids" in the test: new objects carry a type NAME (their `type_id_hint` is -1 by design of the glue); the test checks the
  name is a stock name of the map and that its id (from the stock table) equals the id of the template's own block.
* The task asked for the check "through the same validation the exporter uses"; the exporter is the validator (decision 7), so
  there is no separate dry-run call: `--dry-run` exports to a scratch file.

## Spec defects and gaps found (section numbers)

1. **6.4 `MapInfo`**: the quota rows (minimum, maximum, placed) are not exposed, so D10a's "choose block types whose quota
   maximum allows the count" cannot be checked before exporting; the script relies on `E_QUOTA` and the next-type retry.
2. **8.5 / 8.4**: the export operator reports problems only as a text datablock and console lines; a Python caller has no
   structured result. The script parses `ERROR|WARNING <CODE>` lines (stable because 8.5 step 5 and G4's report builder fix the format); a
   module-level `io_ops.LAST_EXPORT_ISSUES` (or an operator property) would remove the parsing. There is also no validate-only mode, so
   a dry run needs a scratch output.
3. **D10 vs the real file**: "default N chosen so the star has roughly 60-120 cells" assumes room that the real file does not have
   (610 of 650 objects). The auto grid is the answer; D10 / D10a should say the star is about 34 blocks.
4. **3.3 / 4.1 / 4.2**: the real file's bounds are +-20000 on every axis (23-bit axes, cell 0.0048). SPEC 4.2's statement that the
   change tolerance "is a flat 1.0e-3 for all plausible boxes" does not hold here: `max(1e-3, 0.5 cell, 2 ulp32(20000))` = 0.0039. "Centred in the map bounds"
   (D10) is the origin; it is the middle of the map only because Breakneck is centred on the origin.
5. **7.4 / 5.6**: when the template holds no block (the real file), the new block's class and placement rest on the assumed-zero-group
   rule and the default placement byte; nothing in the spec says which `placement` byte a new block gets besides `0x0C` with the physics
   bits replaced, so the in-game default of Forge World blocks is unknown (ladder rung 3 tests exactly this).
6. **SPEC 9.5 rung 3** ("add one `Block, 1x1`") has no tool that produces that single-block file; `--cells 9 --outline` (20 blocks) is the
   smallest star, the Blender GUI the only way to place one block.
7. **2.13 / DEC-2.13**: the default protected list did not contain `real-mvar-samples` when this work started; G3 added it meanwhile (seen
   in `io.py` and `helpers_snapshot.py`); the star tool carries its own mirror of the list and a test pins it.

## Notes for G5 / G6 / G7

* What the star hands the exporter (per block): `name` "Star NNN", `slot None`, `token None`, `type_name` a stock display name (here
  `Block, 1x1`), `type_id_hint -1`, position (Blender float32), forward (0, 1, 0), up (0, 0, 1) (a yaw of pi/2 in SPEC 4.7: raw 12288),
  `shape 0`, dims 0, `spawn_sequence 0`, `spawn_time 0`, `cached_type 0` (copied from an example if any), `label_index -1`,
  `physics 1`, `symmetry 3`, `place_at_start True`, `game_specific False`, `team 8`, `color -1`, `other_a/b 0`; options:
  `allow_unverified_rotation True`, `imported_slots` = every imported slot, `max_objects 650`, `hash_policy REPRODUCE`, `fsm_policy KEEP`.
* What the script checks of the output, so G5 knows what a real writer must satisfy for the star to be accepted: originals' records
  equal (so no re-encoding of untouched slots), header / body fields and budget words unchanged, `hash_flavour` unchanged, the bytes
  outside the stream, the hash and the stored length unchanged (the 29,911-byte trailer included), the SHA-1 of the output equal to
  the recipe of the template, `occupied == before + blocks`, new objects Fixed and vertical.
* G6 can reuse `tests/stubs/stub_roundtrip.py` (`ROUNDTRIP`, `CORRUPT`, `QUOTA_MAX`, templates by bytes) for glue tests that need
  an export that comes back.
* G7: the doc to link is `docs/mvar/STAR_BUILD.md`; the owner-facing caveats are printed by the script on every run.

## Fixes after the independent verification (round 2)

Six defects were reported (1 major, 5 minor). All are fixed within S1prep's own files; nothing outside them (no `Addon/**`, no frozen
file, no `NOTES.md`) was touched.

1. **Library choice (major). Fixed as proposed (rules a, b, c), plus the log source and a clean FAIL for a vanished library.** `stage_environment` now asks the add-on what it resolved
   (`palette.library_path()`: preference, then `$MJOLNIR_LIBRARY`, then `<Addon>/Resources`), through the pure helpers
   `repo_library_path`, `same_file`, `library_problem`, `library_source`:
   * no `--real-library` and the resolved file is this checkout's real `Halo Reach.blend` (nothing named, or the environment names it, or
     it is reached through a link or another spelling) -> **refused, exit 2**, before anything is linked (only `stat` calls are made on the file): "pass --real-library, or set $MJOLNIR_LIBRARY to a stand-in";
   * `--real-library` and the resolved file is another one (the preference overrides the flag) -> **refused, exit 2**, naming both files;
   * the resolved file is fingerprinted and the "object library untouched" check runs whenever it is a file, whichever way it was chosen
     (`run.library_path`, no longer `$MJOLNIR_LIBRARY`); the `library  :` log line names the resolved file and where it came from
     (`--real-library`, `$MJOLNIR_LIBRARY`, the add-on's Resources folder, the add-on preference); a library that does not exist says
     `NOT FOUND` (stage 3 still stops with its own message); a library that vanished or became unreadable is a FAIL, not a traceback.
   * `STAR_BUILD.md` (option table, the sentence under the commands, a new refusals table) and the `--real-library` help text now state the
     real order and the fallback. The header of `tools/run_star_build.sh` too.
   * Tests: 11 pure tests (`TestLibraryResolution`, with `stage_environment` driven by a fake `palette.library_path()` and `bs.REPO` pointed
     at a scratch folder holding a fake "real library", so the pure tests never see the game file) and the Blender scenario
     `scenario_library_resolution` (the REAL `library_path()` precedence; the preference is stood in by replacing
     `palette._addon_preferences`, because `--addons` in a background Blender does not list the add-on in `preferences.addons` and the
     preference is therefore never visible there; this is a property of the test setup, the real preference path is the same function).
2. **Case-insensitive output guard (minor). Fixed.** `_inside` is now the library's `_inside` (commonpath test, then a `samefile` walk up the
   path while the folder exists), starting at the path itself. The same class of hole in the "beside the template" test (string equality of
   the two folders) is closed with `_same_folder`. Tests skip loudly where the volume is case-sensitive; here (APFS) they run:
   `swapcase()` / `lower()` / `upper()` of the repository path, of a mixed-case sample folder, of the default sample folders and of the
   template's folder are all refused; a folder next to the repository is not.
3. **Bytecode (minor). Fixed, but the proposed fix was not enough.** Measured on Blender 5.2.1: its embedded Python runs with
   `sys.flags.ignore_environment == 1`, so `export PYTHONDONTWRITEBYTECODE=1` alone does nothing (the report's evidence of "zero new files"
   was bytecode that already existed and was fresh). It takes **`--python-use-system-env`** next to `--factory-startup`; with it the variable
   works (checked: no `__pycache__` appears in an empty profile). Both wrappers now `export PYTHONDONTWRITEBYTECODE=1`, pass
   `--python-use-system-env`, and first `unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE` and set `PYTHONNOUSERSITE=1` (so the new
   option does not let the caller's environment change the interpreter). `build_star_mvar.py` sets `sys.dont_write_bytecode = True` before
   `import star_layout`. `run_star_tests.sh` also starts its Python with `-B`. A Blender `--startup` script in the profile was tried as an
   alternative and does not run before the add-on is imported, so it is not used. The test (`TestNoBytecodeAndWrappers`) runs the script's
   code in a subprocess without `-I`/`-E` (Apple's 3.9 turns bytecode off by itself for those and keeps all bytecode in
   `~/Library/Caches/com.apple.python`, `sys.pycache_prefix`, so the file check is made only on an interpreter that would write beside the
   source, i.e. Blender's 3.13; the flag check runs on both) with a control that removes the line and must see the flag / the file. The Blender
   scenario `scenario_wrapper_in_a_scratch_checkout` runs the wrapper from a scratch copy of the checkout and asserts no `__pycache__`.
   The plain Blender command in `STAR_BUILD.md` now carries the variable and the option.
4. **Grid 11 feet (minor). Accepted and pinned, not repaired.** `test_the_grids_auto_can_choose_are_pinned_to_one_piece_under_8_connectivity`:
   every auto grid, filled and outline, is one piece under 8-connectivity; the filled star is face-connected on 17, 15, 13 and 9; on 11 exactly
   two cells (the mirrored feet) have no face neighbour and each touches the leg at one corner; the count stays 34. `STAR_BUILD.md` shows the
   shape and says so. A repair (adding a cell beside each foot: 36 blocks, still inside the 40 free slots) would change the pinned counts in
   three test files, two documents and the owner's expectation of "34 blocks"; the report offered either way, and the corner-attached
   foot is the usual look of an 11 x 11 pixel star. If the owner prefers face-attached feet it is a one-rule change in `star_layout.star_cells`.
5. **Test gap on the spacing (minor). Fixed.** `tests/blender/s1_make_odd_library.py` builds a stand-in whose `Block, 1x1` is 1.0182 x 1.0182 x
   1.0; `scenario_spacing_is_the_measured_mesh_box` asserts every column step 1.0182 and every row step 1.0 (each +-0.002) and the footprint.
   The mutant "spacing hard-coded to 1.0" (`cell_positions(..., Footprint(1.0, 1.0, 1.0, offset), ...)`) is now killed.
6. **Relative paths in the wrapper (minor). Fixed by removing the `cd`**, not by documenting absolute paths: the wrapper runs Blender with the
   absolute script path and the caller's working directory, so relative `--template` / `--out` (and abbreviations of those options) mean what
   the caller expects. Run from inside the repository, `--out star.mvar` is the repository and is refused (tested). Documented in the header and
   in `STAR_BUILD.md`. The Blender scenario runs the wrapper with relative paths from another directory.

Mutation check of round 2 (a throw-away copy of the repository without `Addon/Resources`, not kept): 17 mutants, **17 killed** (library
refusal (a) and (b) off, fingerprint only with the flag, the check following the environment variable, `_inside` and `_same_folder` text-only,
no `dont_write_bytecode`, `library_source` constant, wrapper `cd` back / without `--python-use-system-env` / without the export / test wrapper
without `-B`, a changed inner ratio, spacing hard-coded to 1.0, the library check removed from the stage). The first round of the Blender
mutants all "died" for the wrong reason (the scratch copy has no real library, so the `--real-library` scenario failed on the missing
file); the scenario was changed to use a placeholder file in a fake checkout, and the four Blender mutants were re-run and die in the
intended scenario (checked by the assertion text).

Behaviour changes the owner will notice: a rehearsal such as `--provider stub` now needs `--real-library` or `MJOLNIR_LIBRARY=<stand-in>`
(before, it silently linked the real library); relative paths now mean the caller's directory.

## Spec / pipeline notes from round 2 (for the orchestrator)

* `palette.library_path()` consults the add-on preference BEFORE `$MJOLNIR_LIBRARY` (the order is in its docstring). Anything that sets the
  environment variable to pick a library (this tool's `--real-library`, `tests/blender/bl_common.Env.use_library`) is silently overridden by a
  preference that is set in the user's profile. The star tool now refuses in that case; `bl_common` does not (it runs with `--factory-startup`,
  where the preference is empty). Not changed (Addon/** is not S1prep's).
* In a background `blender --addons X`, `bpy.context.preferences.addons` has no entry for X, so `palette._addon_preferences()` is `None` there and
  the Library path preference cannot be exercised headlessly except by replacing that function (as `s1` does).
* Blender's embedded Python ignores every `PYTHON*` variable unless started with `--python-use-system-env`. `tools/run_blender_tests.sh`
  (not mine) does not export `PYTHONDONTWRITEBYTECODE` and does not pass the option; with the dev loop (`Addon/` symlinked) it can write
  `Addon/__pycache__`. The `__pycache__` folders of the repository are git-ignored.
* Apple's `/usr/bin/python3` (CLT 3.9.6) behaves differently from CPython in two ways that matter for tests: `-I`/`-E` set `dont_write_bytecode`,
  and `sys.pycache_prefix` is `~/Library/Caches/com.apple.python`, so it never writes `__pycache__` beside the source.

## Denied actions

One, in round 2: a single `rm -rf` of the scratch folders this work created (the `mjolnir-star.*`, `mjolnir-startest.*` and
`mjolnir-run.3mfooo` folders under `$TMPDIR`, the throw-away mutation copy `.../scratchpad/mut` and a few small probes in the scratchpad)
was DENIED by the safety classifier ("dangerous rm operation": the target was a shell-variable expansion). I did not retry or route
around it. Nothing depends on those folders; they are outside the repository, hold no original and no game asset except the
mutation copy (which was built WITHOUT `Addon/Resources`), and can be deleted by hand:
`$TMPDIR/mjolnir-star.*`, `$TMPDIR/mjolnir-startest.*`, `$TMPDIR/mjolnir-run.*`, `$TMPDIR/mjolnir-btest-*`, and the scratchpad's `mut/`, `bc/`, `prof/`.
(Round 1: no denial.)
