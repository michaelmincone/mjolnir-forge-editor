# Building the block star on the real Breakneck map variant

Status: **built (gate S1, 2026-10-10).** The script was prepared and tested against the stub providers (S1prep); with the real
writer of gate G5 it has now produced the star on the real Breakneck file: `Headstrong_Star.mvar`, 39 blocks, in
`~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/` (outside the repository). What was decided and measured for that run (block, design,
place, clearances, every warning) is in `docs/mvar/notes/S1.md` and in `STAR_REPORT.md` beside the file; the commands that
made it are under "The exact commands" below. The sections that follow keep the original description of the tool.

Whatever the script produces is **UNVERIFIED IN GAME**. Adding objects is the least verified edit of the whole port
(SPEC 5.6, 10; NOTES.md D10). Nobody has loaded such a file in MCC, and nobody knows how an `.mvar` reaches an Xbox
(NOTES.md D10a).

## What it is

`tools/build_star_mvar.py` is a Blender script. It uses the add-on's own operators (`import_scene.mjolnir_mvar`,
`forge.add_object`, `export_scene.mjolnir_mvar`), so every check the add-on and the library make is made, and nothing is
bypassed. It builds an upright five-pointed pixel-art star (apex up, symmetric about the vertical axis) out of Forge blocks
in a vertical plane, centred in the map, with physics set to Fixed (the only placement bits that may be edited, SPEC 3.9).

`tools/star_layout.py` is the pure geometry (no Blender): the true star polygon sampled at the centre of every cell of an
N x N grid, the conversion of cells to positions from the block's measured mesh box (neighbouring blocks touch and never
overlap), the bounds checks and the read-back tolerance. `tools/run_star_build.sh` runs the script in an isolated Blender
profile so that your own Blender settings are not touched.

## What the real file looks like (read with the real reader, read-only)

Facts about `~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar` that decide how the star is built
(measured on the day this was written, with the reader of gate G3 as it was then; re-run the dry run to see current values):

| fact | value | consequence |
|---|---|---|
| map | Breakneck (10050), title "Headstrong" | a stock map: allowed |
| objects | **610** of the 650 allowed | only **40 free object slots**: the default 80-block star does not fit |
| blocks in the file | **none** | no learned example: the library must assume the object class of a block (SPEC 7.4, warning `W_CACHED_TYPE_ASSUMED`, unverified) |
| bounds | x, y, z all -20000 to 20000 | a position cell is 40000 / 2^23 = 0.0048 units; "the middle of the bounds" is (0, 0, 0) |
| the file's own objects | x -28.8 to 29.0, y -29.0 to 29.6, z 2.1 to 21.7 (median z 5.4) | the map is about 58 units across and centred on the origin, so the middle of the bounds is the middle of the map here |
| hash | `plain_le32`, length stored big-endian | the writer must reproduce exactly that (SPEC 2.7); the script re-checks it on the output without the library |
| ids | all 610 are in the stock table | no `--keep-unrecognised` needed (it exists if a later file needs it) |

So with `--cells auto` (the default) the star is the **largest of grid 17, 15, 13, 11, 9 that fits the free slots**: grid 11,
**34 blocks**, 9.2 units wide and 10 tall (`--outline` gives grid 15 with exactly 40 blocks, which uses every free slot).
`Block, 1x1` is chosen (see "Choosing the block"). The shape (one `#` per block, top is up; the run prints it too):

```
....#....
....#....
....#....
...###...
#########
..#####..
..#####..
..#####..
..#...#..
.#.....#.
```

It is a recognisable five-pointed star, apex up, exactly mirror-symmetric, in one piece when a corner counts as touching
(8-connected). **The two feet touch the legs at a corner only**, not along a face: of the grids `auto` can choose, 11 is the one
whose filled star is not face-to-face connected (17, 15, 13 and 9 are), and every outline is corner-connected by nature. The
blocks are Fixed, so nothing falls; it only means the feet look a little detached up close. This is pinned by a test
(`test_the_grids_auto_can_choose_are_pinned_to_one_piece_under_8_connectivity`); a face-attached foot would need a different
cell rule and a different block count (36 instead of 34).

**S1 replaced that default for the real deliverable with a fixed design, `--shape pixel39`** (39 blocks, 9 x 9, every block
touches a neighbour along a face, mirror symmetric, 39 of the 40 free slots, so 649 of 650 objects):

```
....#....
....#....
...###...
#########
.#######.
..#####..
..#####..
..##.##..
.##...##.
```

It was derived once with an area-coverage rule (a cell is a block when at least half of it lies inside the true star) that the
unit test re-derives, so it is not a free-hand drawing; `star_layout.NAMED_SHAPES` holds it. `--shape` cannot be combined with
`--cells` or `--outline`; without it nothing changed.

## The exact commands

The command that produced the S1 deliverable (the place came from `tools/star_placement.py search`, see below; the block was
chosen by measuring the real library, see `docs/mvar/notes/S1.md`):

```bash
cd ~/Local_Documents/Halo-MCC/forge/Mjolnir-Forge-Editor
mkdir -p ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star
T=~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar
tools/run_star_build.sh --template $T --out ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/Headstrong_Star.mvar --real-library \
    --block "Block, 1x1" --shape pixel39 --center 13.25,-15.75,17.0 --raise-quota-max          # add --dry-run first to rehearse
python3 -I tools/star_placement.py search  $T                                                   # where the star has the most room
python3 -I tools/star_placement.py measure $T ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/Headstrong_Star.mvar   # clearances of the built file
python3 -I tools/verify_star_output.py $T ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/Headstrong_Star.mvar \
    --shape pixel39 --center 13.25,-15.75,17.0 --preview                                       # independent check, exit 0 = all passed
python3 -I tools/verify_mvar.py ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/Headstrong_Star.mvar          # the T3 decode report, exit 0
```

The generic procedure (sampled grid, auto block) follows.

```bash
cd ~/Local_Documents/Halo-MCC/forge/Mjolnir-Forge-Editor
mkdir -p ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star

# 1. Rehearsal: everything, including the export and the verification, but nothing is kept.
tools/run_star_build.sh \
    --template ~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar \
    --out ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/breakneck_star.mvar \
    --real-library --dry-run

# 2. The real run (same command without --dry-run). Exit status 0 only if every check passed.
tools/run_star_build.sh \
    --template ~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar \
    --out ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/breakneck_star.mvar \
    --real-library
```

`--provider real` is the default; nothing else has to change when G5 lands. The wrapper creates an isolated profile in a
scratch folder (printed first), links `Addon/` into it as the add-on `mjolnir_forge`, and runs this Blender command, which
you can also run yourself when the add-on is already enabled in the profile you use. **Relative `--template` / `--out` paths
mean the directory you run the wrapper from** (it does not change directory); absolute paths and `~` work as usual. Run from
inside the repository, `--out star.mvar` is the repository and is refused.

```bash
PYTHONDONTWRITEBYTECODE=1 /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python-use-system-env \
    --python-exit-code 1 --addons mjolnir_forge --python tools/build_star_mvar.py -- \
    --template ~/Local_Documents/Halo-MCC/forge/real-mvar-samples/0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar \
    --out ~/Local_Documents/Halo-MCC/forge/maps/headstrong-star/breakneck_star.mvar --real-library
```

`--addons` takes the add-on's module name: `mjolnir_forge` for the working-tree loop above, `bl_ext.user_default.mjolnir_forge`
for an installed extension (`tools/build_package.py`). `PYTHONDONTWRITEBYTECODE=1` together with `--python-use-system-env`
keeps Python from writing `__pycache__` into a working tree whose `Addon/` is the enabled add-on (Blender's embedded Python
ignores the variable without that option; the script itself never writes bytecode for its own helper). The wrapper does both.

**Which object library is linked.** Whatever the add-on resolves (`palette.library_path()`), in this order: the add-on
preference "Library path", then `$MJOLNIR_LIBRARY`, then `Addon/Resources/Halo Reach.blend`, which in a working tree is the
REAL game library. The script asks the add-on, prints the file it resolved on the line `library  :` (with where it came from),
fingerprints that file (size, time, SHA-256) and checks it again at the end, whichever way it was chosen. The real library is
used **only with `--real-library`** (it sets `$MJOLNIR_LIBRARY` to this checkout's file, read-only):

* without `--real-library`, a run that would end on the real library (nothing named, or `$MJOLNIR_LIBRARY` naming it) is
  **refused** (exit 2) before anything is linked: pass `--real-library`, or point `$MJOLNIR_LIBRARY` at a stand-in;
* with `--real-library`, a run in which the preference "Library path" names another file is **refused** (exit 2): the
  preference is checked before the environment variable and would override the flag, so the log would name the wrong file.

### Options

| option | default | meaning |
|---|---|---|
| `--template FILE` | required | the map variant to start from; only ever opened for reading |
| `--out FILE` | required | the new file (a relative path is relative to where you run the wrapper). Refused: inside this repository, in a sample folder (`rvt-test-samples`, `ReachVariantTool-core-library`, `real-mvar-samples`, `$MJOLNIR_SAMPLES`, `$MJOLNIR_PROTECTED`), in the template's folder, equal to the template (also through a link), not ending in `.mvar`, or already existing |
| `--block auto\|NAME` | `auto` | `auto` = see below; or the display name of a stock block of the map (`Block, 1x1`; case-insensitive) |
| `--cells N\|auto` | `auto` | the star is drawn on an N x N grid (the grid size, not the block count; 5 to 64). `auto`: the largest of 17, 15, 13, 11, 9 that fits. An explicit N is **refused** when it does not fit (`E_TOO_MANY`), never shrunk |
| `--outline` | off | only the outline (grid 17: 44 blocks instead of 80; grid 15: 40) |
| `--shape NAME` | none | use a fixed, reviewed design (`pixel39`: 39 blocks, face-connected) instead of the sampled grid; not with `--cells` or `--outline` |
| `--provider real\|stub` | `real` | `stub` = the canned test stub: a rehearsal, nothing is kept (also `stub-roundtrip`, a test double that remembers what it writes) |
| `--real-library` | off | link the real `Halo Reach.blend` of this checkout read-only (its hash is checked before and after). Without it that file is never used: a run that would fall back to it is refused, and a run where the add-on preference "Library path" overrides the flag is refused too. Whatever library the add-on resolves is fingerprinted and named on the `library  :` line |
| `--center X,Y,Z` | `auto,auto,auto` | centre of the star's mesh box; each part a number or `auto`. Auto x, y = the middle of the bounds; auto z = the star's bottom edge on the median height of the file's own objects |
| `--margin M` | 1.0 | world units kept free between the star and every bound |
| `--color NAME` | `KEEP` | `KEEP` writes nothing extra (the template's own block colour if there is an example); a colour writes one more field (unverified) |
| `--keep-unrecognised` | off | tick "Keep objects this tool does not recognise" (DEC-7.4), only if the export is refused with `E_OBJ_NOT_STOCK` for objects that were already in the file |
| `--raise-quota-max` | off | tick "Raise quota maximum (unverified)" on the export (decision D11): a palette entry whose maximum in the template is smaller than the new count (the real file's Block rows are `(0, 0, 0)`) gets its maximum raised to the new count instead of the export being refused with `E_QUOTA`; nothing is lowered, no minimum is touched, and the report carries `W_QUOTA_MAX_RAISED`. UNVERIFIED in game: the game may rebuild quotas from the scenario or refuse the file |
| `--no-rotation-gate` | off | leave "Allow unverified rotation export" unticked; the export is then refused (`E_ROTATION_GATED`). For testing |
| `--overwrite` | off | allow `--out` to replace an existing file |
| `--dry-run` | off | do everything but keep nothing |
| `--allow-stub-output` | off | with `--provider stub`: keep the stub's bytes (a copy of the template, NOT a star) |

Exit status: **0** built and verified; **1** it ran and something failed (a refusal by the library, a failed check, the
real writer missing); **2** refused before anything was written (bad request, over the limit, bad path, bad command line).

### Choosing the block

`auto` takes the block types of the map's Building Blocks group that are stock objects of the map, never the `Invisible`
ones, and ranks them: first a type **already in the template** (the library can then learn its object class and flags from a
real object, SPEC 5.6 / 7.4, and the script copies that example's symmetry, place-at-start, game-specific, team, colour and
class onto the new blocks so that no flag differs from it), then a stock block with a loud warning. Inside a group the best shape
wins: square face in the star's plane and as deep as wide, so `Block, 1x1` beats `Block, 1x4` (which is as wide as it is
tall but four deep) and a slab such as `Block, 2x2`; then the smaller block; then more examples in the template. The spacing
is the measured mesh box of the chosen block in the library (`Block, 1x1` is 1.0182 x 1.0182 x 1.0), not a guess.

If the library refuses because of the block type (`E_QUOTA`, `E_FLAG_UNVERIFIED`, `E_CACHED_TYPE_UNKNOWN`, ...), auto mode
removes the blocks and tries the next type (at most 6); an explicit `--block` is never replaced. The quota maximum of a block
type is not visible through the API, so this is how "pick a block whose quota allows it" is done.

## What it prints

Six sections, then a result and the caveats; the same text is written to `<out>.report.txt` beside a kept file.

1. **Request**: template and output paths, size and SHA-256 of the template (checked again at the end), the object library the
   add-on really resolved (the line `library  : <file> (<where it came from>; linked read-only; sha256 ...)`; a library that does
   not exist says `NOT FOUND`), the provider.
2. **Template**: map, title, object count and room left, bounds, hash recipe and layout, where the file's own objects are,
   the grid chosen.
3. **Block**: which block types the template holds, the candidates with their measured mesh boxes and aspect, and warnings
   (no block in the template; a block that would look stretched; a block that is not square in plan).
4. **Layout and export**, one block per attempt: star box and centre, spacing, the shape drawn in text (one `#` per block, top
   is up), existing objects inside the star's box, the flags copied, `added N x 'Block, 1x1' with forge.add_object, physics Fixed`, and, if the exporter refuses, the exporter's
   own messages with hints.
5. **Export verdict**: the add-on's report (errors, warnings with their codes, counts of kept / added changes, objects before and
   after, bits used of 229,376, stored length L, hash recipe) and the budget and "never checked against MCC" notes.
6. **Verification**: the output is read back and checked, one line each, `[PASS]`, `[FAIL]`, `[SKIP]` or `[INFO]`:

   | check | how |
   |---|---|
   | original objects unchanged | every record that was in the template is equal to its record in the output (identity token and every decoded field) |
   | map header and body fields unchanged | map id, bounds, quota count, version, title, description, labels, palette CRC, budget words, hash recipe |
   | star block count / type / positions / Fixed / vertical | as many new objects as blocks, all the chosen type, each position within the quantisation tolerance (two cells plus the float32 spacing; 0.0134 on this file) of where Blender had it, physics 1, up = +Z |
   | occupied count | template + blocks, never above 650 |
   | bytes outside the bit stream identical | `_blf`, `chdr`, `_eof`, the block list, the 4 pad bytes and the 29,911 zero bytes after `_eof` are byte-identical (checked without the library) |
   | hash recipe reproduced | the output's SHA-1 matches the same recipe and length byte order as the template's (`plain_le32`, big-endian L), recomputed without the library |
   | output differs from the template | |
   | template untouched / object library untouched | size, modification time and SHA-256 equal before and after; the library is the file the add-on resolved (named on the `library  :` line), whether or not `--real-library` was given |
   | re-import with the add-on | the add-on imports the output: as many objects as the file holds, none failed |

After the table comes the **diff report** (objects added, removed, changed and unchanged compared with the template, by type
and slot, for example `added 34 x 'Block, 1x1' in slot(s) 12, 13, ...`), the block, the centre and size of the star, the time and,
for a kept file, `DELIVERABLE: <path> (<bytes>, sha256 ...) UNVERIFIED IN GAME`.

A written file that fails any check is renamed `<out>.REJECTED` and the script exits 1: the file name you asked for never
holds an unverified file. A refusal writes nothing at all. In Blender the blocks are objects named `Star NNN` marked with the custom
property `mj_star` in the collection `Forge Star`; only objects with that mark are ever deleted by the script (between attempts and
before the re-import), never the template's objects.

Sample (the stub round-trip double, `--real-library`, a synthetic Forge World template; NOT the real file):

```
== 6. Verification (re-reading the output) ==
[PASS] original objects unchanged: 5 of 5 slots identical (identity token and every decoded field)
[PASS] map header and body fields unchanged: map_id, bounds, quota_count, version, title, labels, hash_flavour; budget words copied unchanged
[PASS] star block count: 80 new objects, expected 80
[PASS] star block type: all 80 are 'Block, 1x1' (id 0x4600)
[PASS] star block positions: all 80 within the quantisation tolerance (largest error 0.00025, 0.00025, 0.00025; allowed 0.00107, 0.00110, 0.00106)
[PASS] star blocks Fixed: physics = Fixed on all 80
...
RESULT: OK
```

The real dry run today, up to the missing writer (`--real-library`, real reader, no G5):

```
== 2. Template ==
map      : Breakneck 0x00002742
objects  : 610 in the template, room for 40 more (limit 650 objects)
star     : grid auto -> 11: 34 blocks (filled), the largest of 17, 15, 13, 11, 9 that fits the 40 free slots
== 3. Block ==
*** WARNING: the template contains no building block. ... falls back to the palette group rule ... UNVERIFIED. ***
== 4. Layout and export, attempt 1: Block, 1x1 ==
star box : 9.164 x 1.018 x 10.000 centred at (0.0000, 0.0000, 10.4002) ...
added    : 34 x 'Block, 1x1' with forge.add_object, physics Fixed
FAILED: The real writer is not available yet (gate G5 is not finished): ...
```

## If it refuses or fails

| message | meaning / what to do |
|---|---|
| "The object library would be the real ... pass --real-library" | nothing named a library and the add-on fell back to its own `Resources` folder (the real game library in a working tree), or `$MJOLNIR_LIBRARY` names it, and `--real-library` was not given. Refused (exit 2) before anything was linked: pass `--real-library`, or set `$MJOLNIR_LIBRARY` to a stand-in |
| "--real-library asks for ... but the add-on resolves the object library to ..." | the add-on preference "Library path" is checked before `$MJOLNIR_LIBRARY` and overrides the flag. Refused (exit 2). Clear the preference, or leave out `--real-library` |
| `E_TOO_MANY ... at most 40` | the explicit `--cells` has more blocks than free slots; use `--cells auto`, a smaller N, or `--outline` |
| `E_OBJ_NAME_UNKNOWN` | not a stock block of this map; the message lists the stock blocks |
| `E_OUT_OF_BOUNDS` | the star or the margin does not fit the bounds; use `--center`, `--margin 0`, a smaller grid |
| `E_QUOTA` | the map's quota maximum for that block type is reached (auto mode tries the next type); `--raise-quota-max` raises the maximum instead (unverified) |
| `E_CACHED_TYPE_UNKNOWN` | the library cannot assume the object class (no block of that kind in the file). Use a block the file contains, or place one block in the game and use that file as the template |
| `E_ROTATION_GATED` | the rotation gate was left off; never pass `--no-rotation-gate` for a real build |
| `E_OBJ_NOT_STOCK` (an object already in the file) | the stock table does not know that id; if you accept that, `--keep-unrecognised` keeps those objects exactly as they were |
| "The real writer is not available yet" | gate G5 is not finished; nothing was written |
| "FAILED: N verification check(s) failed" | the file was renamed `*.REJECTED`; do not use it, and read the failing lines |
| a warning "N existing object(s) lie inside the star's box" | the star's plane (one block deep) passes through objects of the map; move it with `--center` |

## Caveats (also printed at the end of every run)

* **Unverified in game.** Nothing has been loaded in MCC. The least verified parts are exactly the ones this file uses:
  slot insertion, the assumed object class when the file has no block, the placement byte of a new object and the yaw
  convention (SPEC 4.6 to 4.8). Follow the test ladder of SPEC 9.5 / NOTES.md (rung 3 "add one `Block, 1x1`" is the
  smallest probe; `--cells 9` is the nearest star to it).
* **Xbox / Halo Waypoint route unverified.** Believed: MCC on a PC loads the file, the user saves or shares it to Waypoint,
  the Xbox downloads it. The owner has no Windows PC; whether Microsoft's service or the console checks the SHA-1 or a signature
  (`_fsm`; the real file has none) is unknown. Only native content (a stock map and objects of its own stock palette) is
  produced, which is what an Xbox can run (D10a).
* **Budget cannot be recomputed offline.** Item prices live in game data, not in the file; the spent-budget word is copied
  unchanged (3885 of 10000 in the real file). Open the map in Forge and read the budget meter.
* **Orientation.** Blocks are written as pure yaw 0 (up = +Z) with the gate ticked. `Block, 1x1` is square in plan, so a quarter
  turn from a wrong convention would not change the star; a long block would.
* **Quota rows** (the maximum number of a block type) are checked by the library, not by this script.
* **Spacing** is the mesh box of the library model (1.0182 for `Block, 1x1`): blocks touch in the model; the game's own
  collision box may differ by a hair.

## What was and was not run

Everything in `tests/blender/s1_star_stub.py` and the three pure test files runs against the stub providers and the stand-in
library (names only, no game data); see `docs/mvar/notes/S1prep.md`. The real library, the real reader and the real file were
used read-only for the dry runs quoted above. The dry run quoted above ("the real dry run today") is from before the writer
existed; since G5 the real writer has run and S1 produced the star (`docs/mvar/notes/S1.md`).

Run the star tests:

```bash
tools/run_star_tests.sh --unit          # package + isolated profile (add --dev for the fast loop); Blender test and the pure tests
/usr/bin/python3 -I tools/run_tests.py --only test_star_layout test_star_build_tool test_star_roundtrip_stub
```
