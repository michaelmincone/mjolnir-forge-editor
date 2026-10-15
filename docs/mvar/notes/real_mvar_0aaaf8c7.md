# Decode summary of the real map variant `0aaaf8c7-5ae6-43ba-bb4d-37c987f5e8b8.mvar`

Gate G3 (docs/mvar/SPEC-mvar.md, tier T3-real). **Numbers and names only**: no bytes, no bit stream, no mesh or tag data of the game is
reproduced here (object names are the names of the repository's own stock table, `Addon/mvarlib/data/stock_objects.json`, and the label strings
are the file's own 21 short Forge labels). Produced by `python3 -I tools/verify_mvar.py` plus read-only analysis scripts on the unmodified
original at `~/Local_Documents/Halo-MCC/forge/real-mvar-samples/` (sha256 `e514a53b...79bb254`, checked unchanged after every run). Nothing here was typed from
memory: every figure is reproduced by `tests/unit/test_real_mvar.py` (it skips loudly when the file is absent).

## 1. Verdict

* **The whole body decodes on the first attempt under the spec's own default layout and no constant had to be changed.** The walk consumes the
  header, the fixed body, the label table, all 651 slot records and the 82 quota rows and ends at **bit 106,487**; `ceil(106,487 / 8) = 13,311`,
  exactly the file's own stored length `L` (big-endian `00 00 33 FF`). Hypothesis chosen: type-19 rule `flag8` (preference order; the file has no
  type-19 object, so the rule is `undetermined`), axis bits **23/23/23** (all three rounding variants of SPEC 4.1 agree), **no** 128-bit GUID block
  (body version 31). The two GUID-block hypotheses are rejected (out-of-bounds record at slot 24).
* Header and `chdr` agree: content type 5 (map variant), fileLength 29,481, map id **10050** = Breakneck, title **"Headstrong"**, description
  **"A heavier Headlong."** (the extended comparison of all `chdr` fields, authors and timestamps included, has no difference).
* **Independent semantic cross-checks that the walk's end bit does not need** (all hold): (1) the `placed` byte of **all 82 quota rows equals the
  number of present slots whose folder is that row** (610 objects in total); (2) **all 610 (folder, item) pairs resolve** in the Breakneck stock table
  (`id = (folder << 8) | item`, SPEC 3.6/7.1 confirmed on a real file); (3) the 21 label strings are gametype labels and they sit exactly on the object
  kinds they belong to (`race_spawn` on spawn points, `ctf_flag_return` / `as_bomb` / `race_flag` on flag stands, `koth_hill` / `inf_haven` on
  hill markers, ...); (4) the cached type is a function of the object type (weapons 1, grenades 2, vehicles 7 / 8 / 9, spawn points 15, respawn
  zones 16, kill boundaries 26, loadout cameras 27, teleporter nodes 13 / 14; Structure and Scenery objects 0); (5) shape and dimension fields are
  sane for their kinds (cylinders on flag stands and hill markers, boxes on kill boundaries and respawn zones; largest dimension code 1,033 of
  2,047); (6) respawn times are 15 s multiples (15 ... 180) on all but 5 objects (2, 3 and 7 s); (7) the 14-bit angle code of a vertical object is most often **8,192** (angle 0,
  92 objects) and **4,096** (-90 degrees, 29 objects); (8) Cobb's JavaScript prototype, run read-only on the same file with `node`, decodes
  the same 610 objects, positions, labels and header (test `TestJsOracleOnTheRealFile`).
* Everything is **stock**: no object id is unknown to the Breakneck table, no soft check fires (suspicion count 0), tail and pad bits are zero.
* **There is no `Block` object in this map variant (none of the folders 63 and 70-80), and the quota row of every Block folder is (0, 0, 0).**
  See section 8: this matters for the final star deliverable.

## 2. Container

| item | value |
|---|---|
| file size | 59,392 bytes = 29,481 (plain 4-block file) + **29,911 zero bytes after `_eof`** (kept verbatim; shape `plain4`, trailer in `BlfFile.trailer`) |
| blocks | `_blf` 0x30 v1.2 at 0x0, `chdr` 0x2C0 v10.2 at 0x30, `mvar` 0x7028 **v31.1** at 0x2F0, `_eof` 0x11 v1.1 at 0x7318 (value 0x7318, big-endian) |
| stored length L | 13,311 = `00 00 33 FF`, **big-endian** |
| stored SHA-1 | `b41f6cb0fabe27fc9b22a607c0a9c9ca51c344e3`; reproduced by `SHA1(LE32(13311) || stream[0:13311])`, no salt = **`plain_le32`** (flavour `('>', 'plain_le32')`); the other five candidates do not match |
| passthrough | `to_bytes() == input` (all 59,392 bytes) |
| forced re-encode | `to_bytes(force=True) == input` (all 59,392 bytes, no writer issue) |

## 3. Header (bit form, 1,327 bits)

content type 5; fileLength 29,481 (equals the real length through `_eof`); activity 4 (decoded 3 -> no hopper id); game mode 3 (matchmaking);
engine 0; engine category 255; map id 10050 (0x2742); created by "343 Industries" (timestamp 1,284,422,400, online-id flag 1, xuid 0);
modified by [redacted third-party gamertag, 13 chars] (timestamp 1,329,462,626, xuid [redacted], online-id flag 1); title "Headstrong"; description "A heavier Headlong."
(the same authors, title and description are in `chdr`). No campaign or firefight tail.

## 4. Fixed body and label table

| field | value |
|---|---|
| section bit offsets | header 0-1,327; fixed body 1,327-1,698 (371 bits); labels 1,698-3,167 (1,469 bits); slot 0 starts at 3,167; slot 650 ends at 104,519; quota rows 104,519-106,487 (82 x 24 bits); tail 106,487-229,376 (122,889 bits, all zero); pad bits after the end: 1, zero |
| body version | 31 (the chunk version is 31 as well: no `W_VERSION_MISMATCH`) |
| checksum | 0xFFFFFFFF |
| palette CRC | 0xE1DE4A26 |
| quota_count | **82** |
| map id copy | 10050 |
| built_in / built_from_xml | 0 / 0 |
| bounds (x, y, z) | -20000 .. 20000 on each axis (range 40,000 -> **23/23/23** bits under all three rounding variants and both range computations; one axis triple) |
| budget words | max 0x00002710 = 10,000; spent 0x00000F2D = 3,885 (small integers, not floats) |
| label table | 21 entries, all present; dataLength 225; **compressed**, 145 bytes stored (4-byte size prefix + zlib stream, 13-bit size field); inflates to 225 bytes (= dataLength); recompression with zlib level 9 reproduces the stored block bit for bit |
| GUID block | none |

### Labels (21 entries, one per Forge label; offsets into the 225-byte buffer)

| index | offset | text |
|---|---|---|
| 0 | 0 | `race_spawn` |
| 1 | 11 | `ctf_res_zone` |
| 2 | 24 | `ctf_res_zone_away` |
| 3 | 42 | `team_only` |
| 4 | 52 | `assault` |
| 5 | 60 | `inf_spawn` |
| 6 | 70 | `stockpile` |
| 7 | 80 | `ffa_only` |
| 8 | 89 | `ctf_flag_return` |
| 9 | 105 | `terr_object` |
| 10 | 117 | `oddball_ball` |
| 11 | 130 | `stp_goal` |
| 12 | 139 | `stp_flag` |
| 13 | 148 | `hh_drop_point` |
| 14 | 162 | `koth_hill` |
| 15 | 172 | `as_bomb` |
| 16 | 180 | `as_goal` |
| 17 | 188 | `inf_haven` |
| 18 | 198 | `race_flag` |
| 19 | 208 | `rally_flag` |
| 20 | 219 | `rally` |

### Objects per quota row / folder

| folder | stock names seen | present slots |
|---|---|---|
| 1 | DMR | 3 |
| 2 | Grenade Launcher | 3 |
| 3 | Magnum | 2 |
| 4 | Rocket Launcher | 2 |
| 5 | Shotgun | 3 |
| 6 | Sniper Rifle | 2 |
| 7 | Spartan Laser | 1 |
| 8 | Frag Grenade | 20 |
| 9 | Mounted Machinegun | 2 |
| 10 | Concussion Rifle | 2 |
| 12 | Fuel Rod Gun | 1 |
| 13 | Gravity Hammer | 1 |
| 14 | Focus Rifle | 1 |
| 15 | Needle Rifle | 1 |
| 16 | Needler | 5 |
| 17 | Plasma Launcher | 2 |
| 18 | Plasma Pistol | 6 |
| 20 | Plasma Rifle | 3 |
| 22 | Plasma Grenade | 12 |
| 31 | Fusion Coil | 1 |
| 32 | Health Station | 6 |
| 34 | Cannon, Vehicle | 1 |
| 36 | Receiver Node; Sender Node | 2 |
| 39 | Initial Spawn | 108 |
| 40 | Respawn Point | 248 |
| 41 | Initial Loadout Camera | 3 |
| 42 | Respawn Zone | 23 |
| 43 | Respawn Zone, Weak | 2 |
| 46 | Kill Boundary; Soft Kill Boundary | 17 |
| 47 | Flag Stand | 47 |
| 48 | Capture Plate | 5 |
| 49 | Hill Marker | 25 |
| 51 | Crate, Heavy, Small | 1 |
| 53 | Street Cone | 4 |
| 55 | Banshee | 2 |
| 56 | Ghost | 2 |
| 58 | Revenant | 1 |
| 59 | Warthog, Default; Warthog, Gauss; Warthog, Rocket | 7 |
| 60 | Wraith | 1 |
| 61 | Falcon | 2 |
| 66 | Cover, Large; I-Beam | 7 |
| 67 | Door, Human; Wall | 23 |

### Histogram of (folder, item, stock name, cached type, placement byte, flags2, team raw, colour)

| folder | item | id | stock name | cached | placement | flags2 | team raw | colour | count |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 0x0100 | DMR | 1 | 0x0C | 1 | 9 | -1 | 3 |
| 2 | 0 | 0x0200 | Grenade Launcher | 1 | 0x0C | 1 | 9 | -1 | 3 |
| 3 | 0 | 0x0300 | Magnum | 1 | 0x0C | 1 | 9 | -1 | 2 |
| 4 | 0 | 0x0400 | Rocket Launcher | 1 | 0x0C | 1 | 9 | -1 | 2 |
| 5 | 0 | 0x0500 | Shotgun | 1 | 0x0C | 1 | 9 | -1 | 3 |
| 6 | 0 | 0x0600 | Sniper Rifle | 1 | 0x0C | 1 | 9 | -1 | 2 |
| 7 | 0 | 0x0700 | Spartan Laser | 1 | 0x08 | 1 | 9 | -1 | 1 |
| 8 | 0 | 0x0800 | Frag Grenade | 2 | 0x0C | 1 | 9 | -1 | 20 |
| 9 | 0 | 0x0900 | Mounted Machinegun | 7 | 0x0C | 1 | 9 | -1 | 2 |
| 10 | 0 | 0x0A00 | Concussion Rifle | 1 | 0x0C | 1 | 9 | -1 | 2 |
| 12 | 0 | 0x0C00 | Fuel Rod Gun | 1 | 0x04 | 1 | 9 | -1 | 1 |
| 13 | 0 | 0x0D00 | Gravity Hammer | 1 | 0x0C | 1 | 9 | -1 | 1 |
| 14 | 0 | 0x0E00 | Focus Rifle | 1 | 0x0C | 1 | 9 | -1 | 1 |
| 15 | 0 | 0x0F00 | Needle Rifle | 1 | 0x0C | 1 | 9 | -1 | 1 |
| 16 | 0 | 0x1000 | Needler | 1 | 0x0C | 1 | 9 | -1 | 5 |
| 17 | 0 | 0x1100 | Plasma Launcher | 1 | 0x0C | 1 | 9 | -1 | 2 |
| 18 | 0 | 0x1200 | Plasma Pistol | 1 | 0x0C | 1 | 9 | -1 | 6 |
| 20 | 0 | 0x1400 | Plasma Rifle | 1 | 0x0C | 1 | 9 | -1 | 3 |
| 22 | 0 | 0x1600 | Plasma Grenade | 2 | 0x0C | 1 | 9 | -1 | 12 |
| 31 | 0 | 0x1F00 | Fusion Coil | 0 | 0x4E | 1 | 9 | -1 | 1 |
| 32 | 0 | 0x2000 | Health Station | 0 | 0xCC | 1 | 9 | -1 | 6 |
| 34 | 3 | 0x2203 | Cannon, Vehicle | 0 | 0xCE | 1 | 9 | -1 | 1 |
| 36 | 0 | 0x2400 | Receiver Node | 14 | 0x0C | 1 | 9 | -1 | 1 |
| 36 | 1 | 0x2401 | Sender Node | 13 | 0xCC | 1 | 9 | -1 | 1 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 1 | -1 | 24 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 2 | -1 | 13 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 3 | -1 | 2 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 4 | -1 | 1 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 5 | -1 | 9 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 6 | -1 | 9 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 7 | -1 | 9 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 8 | -1 | 9 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x2C | 1 | 9 | -1 | 31 |
| 39 | 0 | 0x2700 | Initial Spawn | 15 | 0x6C | 1 | 4 | -1 | 1 |
| 40 | 0 | 0x2800 | Respawn Point | 15 | 0x0C | 1 | 9 | -1 | 224 |
| 40 | 0 | 0x2800 | Respawn Point | 15 | 0x2C | 1 | 9 | -1 | 22 |
| 40 | 0 | 0x2800 | Respawn Point | 15 | 0xCC | 1 | 9 | -1 | 2 |
| 41 | 0 | 0x2900 | Initial Loadout Camera | 27 | 0xCC | 1 | 1 | -1 | 1 |
| 41 | 0 | 0x2900 | Initial Loadout Camera | 27 | 0xCC | 1 | 2 | -1 | 1 |
| 41 | 0 | 0x2900 | Initial Loadout Camera | 27 | 0xCC | 1 | 9 | -1 | 1 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xCC | 1 | 1 | -1 | 1 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xCC | 1 | 2 | -1 | 1 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xCC | 1 | 9 | -1 | 1 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xEC | 1 | 1 | -1 | 3 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xEC | 1 | 2 | -1 | 3 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xEC | 1 | 3 | -1 | 4 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xEC | 1 | 4 | -1 | 5 |
| 42 | 0 | 0x2A00 | Respawn Zone | 16 | 0xEC | 1 | 9 | -1 | 5 |
| 43 | 0 | 0x2B00 | Respawn Zone, Weak | 16 | 0xCC | 1 | 1 | -1 | 1 |
| 43 | 0 | 0x2B00 | Respawn Zone, Weak | 16 | 0xCC | 1 | 2 | -1 | 1 |
| 46 | 0 | 0x2E00 | Kill Boundary | 26 | 0xCC | 1 | 9 | -1 | 4 |
| 46 | 1 | 0x2E01 | Soft Kill Boundary | 26 | 0xCC | 1 | 9 | -1 | 13 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0x2C | 1 | 1 | -1 | 2 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0x2C | 1 | 2 | -1 | 2 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0x2C | 1 | 9 | -1 | 3 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0xEC | 1 | 3 | -1 | 2 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0xEC | 1 | 4 | -1 | 2 |
| 47 | 0 | 0x2F00 | Flag Stand | 0 | 0xEC | 1 | 9 | -1 | 36 |
| 48 | 0 | 0x3000 | Capture Plate | 0 | 0x2C | 1 | 2 | -1 | 1 |
| 48 | 0 | 0x3000 | Capture Plate | 0 | 0x2C | 1 | 9 | -1 | 1 |
| 48 | 0 | 0x3000 | Capture Plate | 0 | 0xEC | 1 | 1 | -1 | 1 |
| 48 | 0 | 0x3000 | Capture Plate | 0 | 0xEC | 1 | 3 | -1 | 1 |
| 48 | 0 | 0x3000 | Capture Plate | 0 | 0xEC | 1 | 4 | -1 | 1 |
| 49 | 0 | 0x3100 | Hill Marker | 0 | 0x2C | 1 | 3 | -1 | 1 |
| 49 | 0 | 0x3100 | Hill Marker | 0 | 0xEC | 1 | 1 | -1 | 1 |
| 49 | 0 | 0x3100 | Hill Marker | 0 | 0xEC | 1 | 2 | -1 | 1 |
| 49 | 0 | 0x3100 | Hill Marker | 0 | 0xEC | 1 | 4 | -1 | 1 |
| 49 | 0 | 0x3100 | Hill Marker | 0 | 0xEC | 1 | 9 | -1 | 21 |
| 51 | 4 | 0x3304 | Crate, Heavy, Small | 0 | 0x4C | 1 | 9 | -1 | 1 |
| 53 | 0 | 0x3500 | Street Cone | 0 | 0x0C | 1 | 9 | -1 | 4 |
| 55 | 0 | 0x3700 | Banshee | 9 | 0x0C | 1 | 9 | -1 | 2 |
| 56 | 0 | 0x3800 | Ghost | 7 | 0x0C | 1 | 9 | -1 | 2 |
| 58 | 0 | 0x3A00 | Revenant | 7 | 0x08 | 1 | 9 | -1 | 1 |
| 59 | 0 | 0x3B00 | Warthog, Default | 7 | 0x0C | 1 | 9 | -1 | 4 |
| 59 | 1 | 0x3B01 | Warthog, Gauss | 7 | 0x0C | 1 | 9 | -1 | 2 |
| 59 | 2 | 0x3B02 | Warthog, Rocket | 7 | 0x0C | 1 | 9 | -1 | 1 |
| 60 | 0 | 0x3C00 | Wraith | 8 | 0x0C | 1 | 9 | -1 | 1 |
| 61 | 0 | 0x3D00 | Falcon | 9 | 0x04 | 1 | 9 | -1 | 1 |
| 61 | 0 | 0x3D00 | Falcon | 9 | 0x0C | 1 | 9 | -1 | 1 |
| 66 | 7 | 0x4207 | Cover, Large | 0 | 0xCC | 1 | 9 | -1 | 4 |
| 66 | 8 | 0x4208 | I-Beam | 0 | 0xCC | 1 | 9 | -1 | 3 |
| 67 | 0 | 0x4300 | Wall | 0 | 0xCC | 1 | 9 | -1 | 8 |
| 67 | 4 | 0x4304 | Door, Human | 0 | 0x0C | 1 | 9 | -1 | 3 |
| 67 | 4 | 0x4304 | Door, Human | 0 | 0xCC | 1 | 9 | -1 | 9 |
| 67 | 4 | 0x4304 | Door, Human | 0 | 0xCE | 1 | 9 | -1 | 3 |

### Quota rows with a non-zero minimum, maximum or placed (42 of 82; the other 40 rows are (0, 0, 0))

| row = folder | first stock object of the folder | minimum | maximum | placed | present slots |
|---|---|---|---|---|---|
| 1 | DMR | 0 | 3 | 3 | 3 |
| 2 | Grenade Launcher | 0 | 3 | 3 | 3 |
| 3 | Magnum | 0 | 2 | 2 | 2 |
| 4 | Rocket Launcher | 0 | 3 | 2 | 2 |
| 5 | Shotgun | 0 | 3 | 3 | 3 |
| 6 | Sniper Rifle | 0 | 3 | 2 | 2 |
| 7 | Spartan Laser | 0 | 2 | 1 | 1 |
| 8 | Frag Grenade | 0 | 20 | 20 | 20 |
| 9 | Mounted Machinegun | 0 | 2 | 2 | 2 |
| 10 | Concussion Rifle | 0 | 2 | 2 | 2 |
| 12 | Fuel Rod Gun | 0 | 1 | 1 | 1 |
| 13 | Gravity Hammer | 0 | 1 | 1 | 1 |
| 14 | Focus Rifle | 0 | 1 | 1 | 1 |
| 15 | Needle Rifle | 0 | 1 | 1 | 1 |
| 16 | Needler | 0 | 5 | 5 | 5 |
| 17 | Plasma Launcher | 0 | 2 | 2 | 2 |
| 18 | Plasma Pistol | 0 | 6 | 6 | 6 |
| 20 | Plasma Rifle | 0 | 3 | 3 | 3 |
| 22 | Plasma Grenade | 0 | 12 | 12 | 12 |
| 31 | Fusion Coil | 0 | 1 | 1 | 1 |
| 32 | Health Station | 0 | 6 | 6 | 6 |
| 34 | Cannon, Man | 0 | 1 | 1 | 1 |
| 36 | Receiver Node | 0 | 2 | 2 | 2 |
| 39 | Initial Spawn | 0 | 108 | 108 | 108 |
| 40 | Respawn Point | 0 | 248 | 248 | 248 |
| 41 | Initial Loadout Camera | 0 | 3 | 3 | 3 |
| 42 | Respawn Zone | 0 | 23 | 23 | 23 |
| 43 | Respawn Zone, Weak | 0 | 2 | 2 | 2 |
| 46 | Kill Boundary | 0 | 17 | 17 | 17 |
| 47 | Flag Stand | 0 | 47 | 47 | 47 |
| 48 | Capture Plate | 0 | 5 | 5 | 5 |
| 49 | Hill Marker | 0 | 25 | 25 | 25 |
| 51 | Covenant Crate | 0 | 1 | 1 | 1 |
| 53 | Street Cone | 0 | 4 | 4 | 4 |
| 55 | Banshee | 0 | 2 | 2 | 2 |
| 56 | Ghost | 0 | 2 | 2 | 2 |
| 58 | Revenant | 0 | 1 | 1 | 1 |
| 59 | Warthog, Default | 0 | 7 | 7 | 7 |
| 60 | Wraith | 0 | 1 | 1 | 1 |
| 61 | Falcon | 0 | 2 | 2 | 2 |
| 66 | Antenna, Small | 0 | 7 | 7 | 7 |
| 67 | Door, Human | 0 | 23 | 23 | 23 |

## 5. Slots

* 651 slot records, **610 present (slots 0-609 without a single hole) and 41 absent (slots 610-650)**. Present records are 150-222 bits (mean
  166.1), 101,311 bits in all. Every present record has in-bounds flag 1 and flags2 = 1.
* Parent links: **none** (`parent` is 0 in all 610 slots), so the parent encoding (stored = slot + 1) is still unverified on real data.
* Type-19 objects: **none**, so the type-19 rule stays `undetermined`. No out-of-bounds record.
* Positions (decoded cell centres, world units): x -28.7938 .. 28.9512, y -29.0084 .. 29.6330, z 2.1005 .. 21.6985 (raw cells x 4,188,265 ..
  4,200,375, y 4,188,220 .. 4,200,518, z 4,194,744 .. 4,198,854): a small area in the middle of the +-20,000 box. No cell is at a range extreme.
* Shapes: none 517, cylinder (2) 51, box (3) 42, radius-only (1) 0. Spawn sequence 0-10 (569 zeros), respawn time 0 (513), 15 (10), 30 (14), 45 (42), 60 (1),
  90 (10), 120 (14), 180 (1), and 2 (1), 3 (1), 7 (3). Team raw: 9 (neutral) 496; teams 1..8: 34, 23, 10, 11, 9, 9, 9, 9. Colour: absent in all 610.
* Extras: cached type 1 (weapons) carries 8 bits: spare clips 2 (33 objects), 5 (2), 1 (2), 0 (1); cached types 13 and 14 carry (channel 0, flags 0).
* **Orientation**: vertical (`up_global`) 403, tilted (explicit up code) 207. Raw angle codes of vertical objects: 8,192 x92, 4,096 x29, 12,277 x8,
  16,142 x8, 6,416 x8, 12,288 x5 ... The up codes of tilted objects use cube faces 0 (35), 1 (17), 2 (108), 3 (17), 4 (30), none on faces 5; their tilt from +Z
  (reconstructed with the UNVERIFIED rule of SPEC 4.6): 88 objects within 5 degrees (70 within 1 degree, nearly all of them the codes 436,467 / 436,050 / 436,051 / 436,468 next to
  the centre of face 2, i.e. "almost +Z" codes), 52 around 85-95 degrees, 19 around 110 degrees, the rest spread. No dead-zone code (u above 416) occurs.
  Orthogonality of the reconstructed `forward` and `up`: maximum |forward . up| = 6.8e-15 over all 610 objects, none above 1e-6 (this holds by construction of the
  reconstruction; it is not evidence for the convention).
* Objects that are **not** fully "both symmetries, placed at start": see the placement discussion in section 7.



## 6. Which Block objects exist

**None.** No present slot has folder 63 (Block, 1x1 ... 2x2, Tall) or folders 70-80 (the invisible blocks). The structure objects that do exist are
`Wall` (8), `Door, Human` (15), `Cover, Large` (4), `I-Beam` (3) (folders 66 and 67) and the scenery `Street Cone` (4) and `Crate, Heavy, Small` (1).
The quota rows of the Block folders of Breakneck are all **(0, 0, 0)**: 63 Block 1x1 and 70-80 the eleven invisible blocks. The only rows with room
(maximum above placed) are 4 Rocket Launcher (max 3, placed 2), 6 Sniper Rifle (max 3, placed 2) and 7 Spartan Laser (max 2, placed 1).

## 7. Placement byte, as seen in the file (relevant to the disputed SPEC 3.9)

Histogram over the 610 objects: 0x0C x315, 0x2C x139, 0xEC x87, 0xCC x58, 0xCE x4, 0x04 x2, 0x08 x2, 0x6C x1, 0x4C x1, 0x4E x1. Bit 4 (0x10) never occurs.
Bits that occur: 0x02 on 5 objects (3 `Door, Human`, `Cannon, Vehicle`, `Fusion Coil`), 0x04 alone on `Fuel Rod Gun` and `Falcon`, 0x08 alone on `Spartan Laser`
and `Revenant`, 0x20 on the spawn and objective kinds (all 108 `Initial Spawn`, all 47 `Flag Stand`, all 25 `Hill Marker`, all 5 `Capture Plate`, 20 of 23 `Respawn Zone`, and the 22
`Respawn Point` that carry the label `race_spawn`), 0x40 (fixed physics) on three objects (a crate, a `Fusion Coil`, one `Initial Spawn`), 0xC0 (phased) on the boundaries,
zones, walls, doors and health stations. The data fit both readings (bit 5 = game specific in both); they do **not**
settle which of 0x04 / 0x08 is "symmetric" or what bit 1 means. Nothing in the file contradicts the physics reading of bits 6-7 (0xC0 phased on structure and
boundary objects, 0x40 fixed on one crate, 0x00 normal on weapons, grenades and vehicles).

## 8. What this means for the planned block star (NOTES.md D10 / D10a)

1. There is **no Block in the template to copy field values from**. What the file does give: Structure and Scenery objects have cached type 0 (confirming the
   `assumed_zero_groups` hint of SPEC 7.4, now on real data: `Wall`, `Door, Human`, `Cover, Large`, `I-Beam`, `Street Cone`, `Crate, Heavy, Small`, also `Health Station`, `Fusion Coil`),
   placement 0xCC on walls, covers and beams, team raw 9 (neutral), colour absent, flags2 1, respawn time 0, spawn sequence 0, no label, shape none.
2. **The quota rows forbid adding any Block**: `maximum` is 0 for every Block folder, and SPEC 5.4 / 7.5 refuse `placed` above `maximum`, while SPEC 5.3 says
   `maximum` is "never written". As the template stands, no star of Blocks can be exported under the spec's rules and decision D10a (stock content only, respect quota
   maxima). The same is true for every object kind that is not already placed: the template is a *finished* matchmaking map variant whose maxima equal what it holds
   (all 39 used rows have maximum == placed except rows 4, 6, 7). The orchestrator has to choose, outside this gate: (a) refuse (spec as written); (b) add an explicit,
   loudly flagged, unverified option that raises `maximum` of the affected row to the new `placed` (never lowers a value, never touches `minimum`); (c) use another template.
   Whether MCC/Xbox honours the file's `maximum` or re-derives it from the scenario is unknown (SPEC 10.2), so (b) is a guess that can only be tested in the game.
3. Free slots: 610-650 (41 slots), so a star of up to 41 new objects fits the slot table; the stream has room (122,889 free bits; a new block record is about 150 bits).

## 9. Cross-checks that were run

`tools/verify_mvar.py` (exit 0, full output in G3.md), `tools/dump_mvar.py --plain` to a temp file and `from_plain` back (identical to the input including the trailer), the
independent hash check with `hashlib` in the test, the JavaScript prototype via `node` (objects, labels, header, bounds, budget identical), patched-mode edits in memory (move one
object: only its x cells and the hash change; delete one: L and hash follow; add one: slot, quota row, L and hash follow), and a forced rebuild of each edited copy.
