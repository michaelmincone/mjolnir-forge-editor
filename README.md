# Mjolnir Forge Editor for Mac

A Blender add-on for building Halo: Reach Forge maps on a Mac. It opens a Forge map file (`.mvar`) in Blender, lets you move, delete and add Forge objects there, and saves the result as a new `.mvar` that you can upload to your File Share and play on Xbox. The game never needs to run on the Mac.

This is a Mac port of [Mjolnir Forge Editor](https://github.com/Waffle1434/Mjolnir-Forge-Editor) by Waffle1434. The original edits a running copy of Halo: Reach on a Windows PC through a DLL; this version reads and writes map files instead.

## What it does

- **File > Import > Halo Reach Map Variant (.mvar)** brings every object on the map into Blender.
- Move or delete objects, or add new ones from **Add > Forge Object** (only the objects that map's own Forge palette offers).
- **File > Export > Halo Reach Map Variant (.mvar)** writes `<name>_mjolnir.mvar`. It never overwrites the file you opened.
- The exporter keeps maps unmodded and Xbox friendly: stock maps and stock objects only, at most 650 objects, everything inside the map's bounds, and each object type within its Forge limit. If a map breaks a rule, it refuses and says why instead of writing a file.

An edited map exported with it has been uploaded with [MCC Forge Publisher](https://github.com/michaelmincone/mcc-forge-publisher) and downloaded in MCC on Xbox. Tilted objects are still unverified in the game, so rotation export is off unless you turn it on.

## What you need

- A Mac (tested on Apple Silicon)
- [Blender 5.2.1](https://www.blender.org/download/) in `/Applications`
- The Command Line Tools for Python 3 (`xcode-select --install`)
- A Halo: Reach map variant (`.mvar`) to start from. Map files come from the game, so none are included here.

## Set it up with AI

Open [Claude Code](https://claude.com/claude-code), or another AI assistant that can run commands on your Mac, and paste this:

```text
Set up the Mjolnir Forge Editor Blender add-on on my Mac from
https://github.com/michaelmincone/mjolnir-forge-editor.
Clone it, read README.md and docs/mvar/INSTALL_MACOS.md, and check that Blender 5.2.1 is installed.
Build the add-on zip into a folder outside the repo, run tools/run_tests.sh and tell me whether everything passed.
Then walk me through installing the zip in Blender and pointing the add-on at Addon/Resources/Halo Reach.blend.
Never edit or overwrite any .mvar file I give you; work on copies.
```

## Set it up by hand

```bash
git clone https://github.com/michaelmincone/mjolnir-forge-editor.git
cd mjolnir-forge-editor
python3 tools/build_package.py --out ~/Desktop/mjolnir-addon --allow-placeholders
```

1. In Blender, open **Edit > Preferences > Get Extensions**, choose **Install from Disk...** from the menu at the top right, pick `~/Desktop/mjolnir-addon/mjolnir_forge-1.0.0.zip`, and enable it.
2. In the add-on's preferences, set **Library path** to `Addon/Resources/Halo Reach.blend` in this repo. That file holds the object models; without it, objects import as empties.
3. Use **File > Import** and **File > Export** as described above.

`tools/run_tests.sh` runs the full test suite (it needs `/usr/bin/python3` and Blender's own Python). `tools/verify_mvar.py <file.mvar>` checks any map file without Blender. [docs/mvar/INSTALL_MACOS.md](docs/mvar/INSTALL_MACOS.md) has the details, and [NOTES.md](NOTES.md) records every design decision and what is still unverified.

## Related tools

- [MCC Forge Publisher](https://github.com/michaelmincone/mcc-forge-publisher) uploads the exported map to your MCC File Share from the Mac.
- [ReachVariantTool for Mac](https://github.com/michaelmincone/halo-reach-variant-tool) edits Halo: Reach game types.

## Credits and license

- **Mjolnir Forge Editor** is by Waffle1434 and Jason Deacutis, with contributions from John Woodruff, Michael White, Connor J Thompson, Tobin Cavanaugh and Lookenpeepers: <https://github.com/Waffle1434/Mjolnir-Forge-Editor>. The add-on, the object library and the original Windows version are their work. Their original readme is kept in [UPSTREAM_README.md](UPSTREAM_README.md).
- It was based on [Halo Reach Forge Assistant](https://github.com/Lookenpeepers/Halo-Reach-Forge-Assistant) by Lookenpeepers.
- Reading and writing `.mvar` files follows David J. Cobb's map variant research in [ReachVariantTool](https://github.com/DavidJCobb/ReachVariantEditor).
- The Mac port (the `.mvar` import and export, `Addon/mvarlib`, the tests and tools) was written by [michaelmincone](https://github.com/michaelmincone) with Claude Code.

The original project has no license file, so its code stays under its authors' copyright. Keep this repository private unless Waffle1434 agrees to it being shared publicly.

*Halo: The Master Chief Collection © Microsoft Corporation. Mjolnir Forge Editor was created under Microsoft's [Game Content Usage Rules](https://www.xbox.com/en-US/developers/rules) using assets from Halo: Reach, and it is not endorsed by or affiliated with Microsoft.*
