# G4fix notes: clean-up of gate G4 (Blender glue) after the independent verification

Written for the orchestrator to merge into `NOTES.md`; `NOTES.md` and `docs/mvar/notes/G4.md` were not edited. Nothing was
committed (working tree only, git state untouched). Section numbers ("SPEC 8.5") refer to `docs/mvar/SPEC-mvar.md`.
Everything here runs against the stub provider; nothing proves anything about the real codec (G3/G5/G6).

## What was fixed (the verifier's findings, in its order)

### 1. Export report said "Result: ok" for a file that was never written
* `Addon/io_ops.py`, `EXPORT_OT_mjolnir_mvar.execute`: step 7 now writes the file FIRST (`P.write_atomic(...)`) and the report
  only afterwards. `build_report(..., status)` takes `STATUS_OK` / `STATUS_REFUSED` / `STATUS_FAILED`; the result line reads
  `Result: ok, file written`, `Result: REFUSED, nothing was written` or `Result: FAILED, nothing was written (the file could
  not be written)`.
* `PathPolicyError` and `OSError` from the writer give an `E_WRITE_FAILED` issue (new glue code, decision 1), the report with
  `Result: FAILED`, the ERROR `Export failed, nothing was written: <reason> See the text 'Mjolnir Export Report'.` and
  `CANCELLED`. Early refusals keep `REFUSED` (their tests are unchanged).
* Test: new `tests/blender/b22_export_write.py` (see 4).

### 2. Shape enum renumbered
* `forge.py` v0.9.9.2 numbered the items by position: NONE 0, CYLINDER 1, BOX 2. `mjolnir.py` `ForgeObjectProps.shape` now stores
  NONE 0, CYLINDER 1, BOX 2, SPHERE 3 (dropdown order None / Cylinder / Box / Sphere). `SHAPE_TO_ENUM` / `SHAPE_FROM_ENUM`
  map the file's shape codes (0 none, 1 sphere, 2 cylinder, 3 box) by identifier, so nothing else depended on the numbers.
  Checked the neighbours too: `physics` (NORMAL 0, FIXED 1, PHASED 2) and `symmetry` (BOTH 0, SYMMETRIC 1, ASYMMETRIC 2,
  NEITHER 3 new) already kept the old position numbers. `gtLabel` cannot be compatible (the old items were positional and
  dynamic; that is SPEC 8.7 #8 and unchanged).
* Tests: `b05` asserts the stored numbers of all three enums and reads raw stored values (`obj.forge['shape'] = 1` must be
  CYLINDER, 2 BOX, 3 SPHERE) the way a `.blend` saved by the old add-on holds them; the unit test
  `test_g4_glue_static.test_the_enum_numbers_a_blend_stores_are_the_old_add_ons` pins the literal items.

### 3. Matrix not re-orthonormalised; an untouched tilted object could look moved or rotated
Probed on 5.2.1 (throw-away script, not kept): right after `obj.matrix_world = M` the matrix reads back exactly as assigned;
after the next depsgraph update it is recomposed from location / rotation / scale and a forward/up pair 0.2 degrees off
perpendicular comes back 1.8e-3 rad (forward) and 2.5e-3 rad (up) away, far above the library's `ANG_TOL` of 1e-4. Even a
perpendicular control returns forward `(1, 7.5e-8, 0)`. Two layers now exist:
* **Import** (`mjolnir.orthonormal_axes`, `basis_matrix`, `apply_record`): `up` is the stored axis (SPEC 4.6), so it is only
  normalised; `forward` is projected perpendicular to it (zero or parallel forward gets any perpendicular direction; zero up
  becomes +Z). The skew no longer leaks into `obj.scale`.
* **Export** (`mjolnir.exported_pose`, `capture_pose_baselines`, `pose_from_matrix`): `apply_record` keeps the record's own
  numbers in `obj['mj_pose']` (9 floats, doubles: exact). After the whole import has created its objects the import operator
  calls `capture_pose_baselines`, which does `view_layer.update()` and stores `obj['mj_base']`: the same 9 numbers read back
  from Blender through `pose_from_matrix(world_matrix(obj, excluded))`, i.e. exactly the code path the export uses. At export,
  `to_export_object` reads the current pose the same way and compares it with `mj_base`:
  position within `POSE_POS_TOL` = 5e-4, orientation (forward AND up together) within `POSE_ANG_TOL` = 5e-5 rad (half of
  the library's `ANG_TOL`; the angle uses `atan2(|a x b|, a . b)`). A part that did not change is handed over as the record's
  own `mj_pose` numbers (bit-identical), a part that did change as Blender has it now, so the library sees no difference for
  untouched parts and keeps the original raw bits; a move does not report a rotation and the other way round.
  No baseline (an object not made by the importer, an older import, a malformed property) means the current pose, as before.
  Array instance 0 uses the same rule (compared with the baseline of the source); other array instances and new objects never
  have one.
* Test: new `tests/blender/b23_pose_baseline.py` with a canned non-orthonormal set built from the stub's `make_record`
  (perpendicular control, a pair 0.2 degrees off, a tilted skewed pair, forward parallel to up). It proves the premise (Blender's
  own reading of the skewed pair WOULD be reported as rotated by a library applying SPEC 4.9), the import (proper rotation, scale
  1, `up` kept), the no-op export (every pose equals the record's exactly and `library_sees_change` is `(False, False)`), moved
  without turned and turned without moved, tolerances (1e-5 ignored, 2e-3 and 1e-3 rad real), hidden / `hide_viewport` /
  excluded-collection objects, duplicates (unmoved and moved), missing and malformed baselines, new objects, and save + reopen
  (also across a process in `b03`).
* Mutation checks (throw-away copies of `Addon/`, not kept): export ignoring the baseline, position always the record's,
  orientation judged per vector, baseline captured without the view-layer update, import without the re-orthonormalisation:
  each is caught by b23.

### 4. Test and harness findings
| finding | fix |
|---|---|
| `b12_convert.py` cannot run alone; two unclosed files | the `__main__` block is at the end of the file; `sha256_of()` uses `with open`. Every `bNN` file now also runs alone (checked in a loop) |
| B-06 "changing the convention rescales" asserts nothing | 33X, 47X and 71X all give 6.0 at sequence 50. The test now uses -30 (47X 35.6, 71X 19, 33X 15, 330X 240.88), checks each step against `spawnSeqToScale`, that the scale really changed, and that a non-forge object and an object without the SCALE label are untouched. Mutation (convention callback does nothing) is caught |
| B-14 vacuous `or True` | the second import comes from a file with different bytes: stored `template_sha256` differs and equals the SHA-256 of the new bytes, `template_bytes` are the new bytes, `source_name` changed, `verify_template` ok. Mutation (fixed hash) is caught |
| B-09 does not discriminate `find_shape_helper`'s parent check | a copy of the shaped object is made while `forge.shapeObject` still names the original's live helper (the copy's hint resolves to an object that exists but is not its child). Asserted: `find_shape_helper(copy)` is `None`, editing / removing the copy's shape never touches the original's helper. Mutation (parent check removed) is caught |
| `ExportOptions` from the UI beyond defaults | `b22`: eight combinations of the two scene checkboxes and `force_reencode` / `fsm_policy` / `hash_policy` (each one alone, then all together, then back to defaults); `imported_slots`, `max_objects` and the template are asserted too. Mutation (the two checkboxes swapped) is caught |
| `.NNN` duplicate-suffix strip | `b17`: three collections called "Block, 1x1" (Blender names them `.001`, `.002`), each as `instance_collection` of an exported object -> `type_name` is the bare name; boundary cases of `strip_duplicate_suffix` (`.1234` stripped, `.01` / `.5` / a suffix in the middle kept, only the last of `.001.002`); the `mj_type_name` fallback. Mutation (no strip) is caught |
| array sources parented by `instance_type = VERTS` | `b11`: a four-vertex mesh as VERTS parent gives four objects at the vertices (one claims the slot, three new), the overlay counts them, and a hidden VERTS parent is refused with `E_ARRAY_NOT_EVALUATED`. Mutation (`ARRAY_PARENT_TYPES` without VERTS) is caught |
| export goes through `P.write_atomic` | `b22`: `stub.write_atomic` is wrapped to record `(target, bytes, [source], None)`, and `builtins.open`, `io.open` and `os.open` fail any write below the test folder outside that call (the guard itself is proven first: a plain `open(path, 'wb')` raises). Mutations (plain `open().write()` instead of the provider; report written before the write) are caught |
| `scene['mjolnir']` read outside `state.py` | `ForgeScenePanel.draw` uses `state.get(scene)`; `palette.visible_names` uses the new `state.has_map(scene)`. Static unit test `test_the_scene_state_is_touched_only_inside_state_py` (no `['mjolnir*']` subscript or `.get('mjolnir*')`, no `state.KEY` / `state.TEMPLATE_KEY` outside `state.py`); `b13` sets `failed_slots` through `state.set_import_results`. Tests that tamper with `scene['mjolnir_template']` on purpose (b12) keep doing so |
| stats keys printed twice; whole report echoed | the report writes every stats key exactly once (a key already said by `Objects:`, `Bits used:`, `Stored stream length L:` or `Hash:` is not repeated; unknown keys and a lone `end_bit` are kept). The console gets `export OK|REFUSED|FAILED: <file> (n error(s), m warning(s), k change(s))`, every problem (at most `MAX_CONSOLE_PROBLEMS` = 12, then `... and N more problem(s)`) and `full report: text 'Mjolnir Export Report' in the Text Editor` (2 lines for a clean export instead of about 60). Asserted in `b22` (including 30 problems) |
| B-01 fails between `unregister()` and `register()` -> misleading `AttributeError`s later | `b01.run` wraps its checks: on any failure the add-on is unregistered and registered again before the exception goes on. Plus a harness net in `bl_common.run_test`: after every test `Env.ensure_registered()` registers a left-unregistered add-on again and the test that left it is reported as FAILED with that reason. Proven with an injected failure after B-01's final unregister (b02, b05, b22 still pass) and with a throw-away test that unregisters |
| `run_blender_tests.sh --provider real` exits 0 with skips | `run_all.py` exits 0 only when nothing was skipped, 1 on a failure, 3 on skips (last line `run_all: RESULT: PASSED\|FAILED\|SKIPPED`); a stand-alone test file that SKIPs exits 3 too (`bl_common.EXIT_SKIPPED`). `run_blender_tests.sh` passes status 3 through: it prints `SKIPPED: no test failed, but tests were skipped ... this is not a pass` and exits 3 (a failure always wins: exit 1). Unit test `TestRunBlenderTestsScript` drives the script with a fake Blender (no Blender started). Result of `--provider real` now: B-01 passes, 17 SKIP, exit 3 |

### 5. `register_class` warnings under `--debug-python`
`register_class(...): warning, ForgeObjectProps: is expected to contain a "__slots__" member` (also the Collection and Scene props).
One safe line each: `__slots__ = ()` in the three `PropertyGroup` classes. Verified: the warnings are gone, annotations / class
attributes / the update callbacks work, and `obj.forge.anything = 1` now raises `AttributeError` (which is what the warning wants;
nothing in the glue or the tests assigned an arbitrary attribute). Pinned by `test_property_groups_declare_slots`.

## Decisions (most reasonable choice made, work continued)
1. **New glue issue code `E_WRITE_FAILED`** for `PathPolicyError` / `OSError` raised by the writer after all checks passed (same
   family as `E_NO_TARGET` and `E_INTERNAL` of G4 decision 6). Its message is the exception text (`Could not write <target>: ...`).
2. **Console summary instead of the whole report** (deviation from SPEC 8.5 step 5, "the console: one line per DiffEntry ..."): a
   650-object export would print 650+ lines every time. The text datablock still holds everything.
3. **Position and orientation are judged separately**, orientation as one quantity; tolerances 5e-4 and 5e-5 rad are strictly
   inside the library's (`POS_TOL >= 1e-3`, `ANG_TOL = 1e-4`) so "Blender-side unchanged" can never be "changed" for the library.
4. **`up` wins in the re-orthonormalisation**: the file stores the up code (SPEC 4.6) and derives forward from it.
5. Custom property names `mj_pose` and `mj_base` (next to `mj_slot` / `mj_raw` ...); 9 doubles each, they survive save + reopen
   (b23, and across a process in b03).
6. `Env.ensure_registered()` and `bl_common.EXIT_SKIPPED` are harness additions in `tests/blender/bl_common.py`.

## Spec gaps and defects found (section numbers)
1. **SPEC 8.5 step 5**: echoing the whole report to the console does not scale (decision 2).
2. **SPEC 7.3**: no code for a write that fails after validation (`E_WRITE_FAILED`), none for "no output file" (`E_NO_TARGET`, G4)
   or an unexpected library exception (`E_INTERNAL`, G4).
3. **SPEC 4.6 (last bullet) / 8.4 step 6**: "columns `(forward x up, forward, up, position)`" is only right for a perpendicular
   pair, and `matrix_world` is recomposed on the next depsgraph update. For G5/G6: the glue now hands the library the record's
   own numbers for every unchanged part, so a library comparison against its decoded pose (4.9) cannot be thrown off by Blender;
   for a changed part the library still receives Blender's normalised vectors. A real-codec test with a tilted object
   (G6, `b15`/`b18` style) should cover a no-op export of slots whose forward/up are perpendicular only to float32.
4. **SPEC 8.7 DEC-8.7** adds `SPHERE` and `NEITHER` to existing enums without saying which numbers they take; the numbers are what a
   `.blend` stores (this is how fix 2 came about). The numbers now in force are in the code comment of `ForgeObjectProps` and pinned by tests.
5. **SPEC 9.4** does not say what a run with skipped tests returns (exit 3 / `SKIPPED` here).

## Files changed
Add-on: `Addon/mjolnir.py` (shape numbers, `__slots__`, `orthonormal_axes` / `basis_matrix` / pose bookkeeping, state routing),
`Addon/io_ops.py` (report order and status, console summary, stats once, baseline capture after import), `Addon/state.py`
(`has_map`), `Addon/palette.py` (`visible_names` through `state.has_map`).
Tests: `tests/blender/{bl_common,run_all,b01_startup,b03_persist,b05_props_extremes,b06_scale,b09_duplicate_rename,b11_arrays_limit,
b12_convert,b13_ui,b14_replace,b17_relink}.py` edited; new `b22_export_write.py` and `b23_pose_baseline.py` (extras, not in the SPEC 9.4
catalogue; G6's file list does not collide). `tests/unit/{test_g4_state,test_g4_glue_static,test_g4_tools}.py` extended (G4 unit tests: 35 -> 42).
Tools: `tools/run_blender_tests.sh`. Not touched: `build_package.py`, `gen_palette_tree.py` (no finding concerned them), `provider.py`,
`__init__.py`, the stub, `api.py`, `errors.py`, `Addon/Resources/*`.

## How to run / results (Blender 5.2.1 LTS, Python 3.13.13; system Python 3.9.6)
```
cd ~/Local_Documents/Halo-MCC/forge/Mjolnir-Forge-Editor
tools/run_blender_tests.sh                       # package + isolated profile + B-01 alone + run_all (stub)   -> exit 0
tools/run_blender_tests.sh --real-library        # same, real Halo Reach.blend linked read-only                  -> exit 0
tools/run_blender_tests.sh --provider real       # B-01 passes, 17 tests SKIP                                     -> exit 3 "SKIPPED"
tools/run_blender_tests.sh --dev --only b22 b23  # fast loop, subset
/usr/bin/python3 -I tools/run_tests.py --only g4           # the G4 unit tests (42); same with the Blender python3.13
```
* Blender suite, installed extension, stub provider: **18 passed, 0 failed, 0 skipped** (the 16 of G4 plus b22 and b23); the same with
  `--real-library`: 18 passed; `--dev`: 18 passed; every `bNN` file also passes when run alone.
* `--debug-python` startup: no `register_class` warning.
* Unit suite with `--samples`, both interpreters, 585 tests: **2 failures, both in `test_py39_syntax` (the 3.9 lint)**, caused by files of
  the parallel G3 work that were being written while this ran (`Addon/mvarlib/plain.py:330`, `tests/unit/helpers_g3.py`,
  `tests/unit/test_roundtrip_forced.py`: `.from_bytes()` calls without the keyword the lint demands). They are not G4 files and were
  not edited here; the lint is clean on every file I touched (`tests/py39_lint.py` on `Addon/*.py`, `tests/blender`,
  `tests/unit/test_g4_*.py`, `tools`: 0 findings). Everything else is green and U-21 (samples untouched) holds. An earlier run
  showed the same two failures against a different in-flight line, so re-run once the G3 files settle.
* `tools/check_no_game_assets.py`: ok. `Addon/Resources/ForgeBridge.dll` (`e1296523...2e48`) and `Halo Reach.blend` (`a76e1d74...e6ad`)
  SHA-256 and mtime are identical before and after all runs (including `--real-library`).

## Denied actions
None. No tool call was denied by the permission classifier.

## Notes for the orchestrator
* Other agents were editing `Addon/mvarlib/*` and `tests/unit/helpers_*` / `test_roundtrip_forced.py` in the same working tree while this
  ran (the tool reported `Addon/mvarlib/io.py` and others changing on disk); none of those files were touched.
* `tools/__pycache__/*.cpython-313.pyc` appear after the 3.13 unit run (the tool tests import the tools by path); they are git-ignored and were already there.
