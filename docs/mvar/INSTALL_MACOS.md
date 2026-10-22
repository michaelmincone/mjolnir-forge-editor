# Mjolnir Forge Editor on macOS: editing Halo: Reach map variant files

This port replaces the Windows-only live-memory bridge (`ForgeBridge.dll`) with **File > Import** and **File > Export** for
Halo: Reach map variant files (`.mvar`). No game needs to run. Only Blender 5.2.1 LTS on macOS has been tested.

**Read first:** nothing produced by this tool has ever been loaded in Halo: The Master Chief Collection. See "What is not verified"
below and `NOTES.md` (D9 to D11) before relying on an export.

## Install

Run source-tree commands from `~/Documents/Halo_MCC/mjolnir-forge-editor/source`. The current map-workflow
paths and offline rules are in [../../../forge-workspace/AGENTS.md](../../../forge-workspace/AGENTS.md).

1. Build the extension (it is built outside the repo and contains **no game assets**):
   `python3 tools/build_package.py --out ~/Documents/Halo_MCC/mjolnir-forge-editor/packages --allow-placeholders`
   (the manifest still holds placeholder maintainer and licence text; the licence line is a placeholder because upstream declares none).
2. Blender: Edit > Preferences > Get Extensions > (top-right menu) Install from Disk... > choose `~/Documents/Halo_MCC/mjolnir-forge-editor/packages/mjolnir_forge-1.1.0.zip`, then enable it.
3. In the add-on's preferences set **Library path** to the full library `~/Documents/Halo_MCC/mjolnir-forge-editor/forge-workspace/object-support/assets/full-v04/Halo Reach.blend`
   (a folder is accepted too; it is linked read-only and never saved). The package deliberately does not include it.
   `$MJOLNIR_LIBRARY` works as an alternative. Without the library, import still works (objects appear as empties).

## Use

* **File > Import > Halo Reach Map Variant (.mvar)**: the map's objects appear as Blender objects. The file is embedded in the
  `.blend`, so you can save, reopen and export later without the original.
* Move or delete objects; add objects from **Add > Forge Object** (only objects in that map's own stock palette are offered).
* **File > Export > Halo Reach Map Variant (.mvar)**: writes `<name>_mjolnir.mvar`. It never overwrites the file you imported and refuses
  folders holding sample or original files. Every refusal writes no file at all and says why.

## Rules the exporter enforces

Stock map only; stock objects only (from that map's own palette); at most **650 objects** (a map that already holds 610 has room for 40
more); positions inside the map bounds (never clamped); per-type counts inside the map's own quota table. Adding more of a type than
the file's quota maximum allows is refused unless you tick **Raise quota maximum (unverified)**, which raises that maximum to the count
you placed (never lowers anything). It is off by default and is not remembered between exports.
Rotation edits are off by default (**Allow unverified rotation export**); moving, deleting and adding objects are the supported edits.

## What is not verified

* That MCC (or an Xbox, via Halo Waypoint) accepts an edited file. Nobody has tried. The owner has no Windows PC.
* Orientation decoding (the angle of tilted objects) and the meaning of some placement-flag bits.
* Raising a quota maximum, the object class assumed for new blocks, and the Forge budget (not recomputable offline).
* Only **one** real map variant (Breakneck) was ever available for testing the file format; type-19 objects, parent links,
  v32 files and compressed (`_cmp`) files are untested on real data.

## Command-line tools (Python 3.9+, no Blender needed)

`tools/verify_mvar.py <file.mvar>` decodes a map variant and prints a full report (exit 0 = decoded and self-checked);
`tools/dump_mvar.py`, `tools/reencode_mvar.py`; `tools/run_tests.sh` runs everything; `tools/run_blender_tests.sh` runs the headless
Blender suite. The star example is `docs/mvar/STAR_BUILD.md`.
