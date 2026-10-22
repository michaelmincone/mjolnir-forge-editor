# SPEC: Halo: Reach map variant (`.mvar`) import/export for Mjolnir Forge Editor on macOS

Path update (2026-10-21): existing checkout and tool references use the current `~/Documents/Halo_MCC/` layout. References to `test-samples/` are historical artifacts absent from this checkout; examples requiring them are not ready to run. Recorded test results and literal historical default strings are unchanged.

Status: decision-ready implementation spec, v1.1 (2026-10-09), revised in place after two adversarial lint passes (format and codec; plan, Blender and done-criteria). Every applied, partly applied and rejected lint item is listed in Appendix F (change log) and Appendix E (rejected lint items). Audience: the engineers who build gates G0 to G7 (section 11) without re-reading the research reports.
Repo: `~/Documents/Halo_MCC/mjolnir-forge-editor/source`, branch `macos-mvar`. Target: Blender 5.2.1 LTS (Python 3.13.13) on macOS arm64; the pure-Python library must also run on system Python 3.9.6.

This spec was written after reading, in full: the six research reports, `critique-format-correctness.md`, `critique-plan-feasibility.md`, `map_variant_mvar.js` (Cobb), the RVT C++ sources named in the task, `forge.py` v0.9.9.2, `ForgeObject.cs`, `Map.cs`, the repo state, and the prototypes; plus 24 independent spot-checks (Appendix A) and 20 further checks made during the revision (Appendix A.2). Where the reports conflict, the conflict is listed in section 1.5 with the decision and the reason.

## Table of contents

- [0. Conventions used in this document](#0-conventions-used-in-this-document)
  - [0.1 Evidence tags (every format claim carries one)](#01-evidence-tags-every-format-claim-carries-one)
  - [0.2 Clean-room rule](#02-clean-room-rule)
  - [0.3 Terms](#03-terms)
- [1. Executive summary and honest confidence statement](#1-executive-summary-and-honest-confidence-statement)
  - [1.1 What is being built](#11-what-is-being-built)
  - [1.2 Confidence, layer by layer](#12-confidence-layer-by-layer)
  - [1.3 Design principles (these decide the rest of the document)](#13-design-principles-these-decide-the-rest-of-the-document)
  - [1.4 Binding decisions A to G: adoption](#14-binding-decisions-a-to-g-adoption)
  - [1.5 Conflict register: where sources disagree, what this spec decides and why](#15-conflict-register-where-sources-disagree-what-this-spec-decides-and-why)
- [2. Container specification: _blf, chdr, mvar, _eof, _cmp, _fsm](#2-container-specification-_blf-chdr-mvar-_eof-_cmp-_fsm)
  - [2.1 Block header (all blocks, 12 bytes, big-endian)](#21-block-header-all-blocks-12-bytes-big-endian)
  - [2.2 Layout of a plain map variant (the case this tool writes)](#22-layout-of-a-plain-map-variant-the-case-this-tool-writes)
  - [2.3 _blf (0x30 bytes) V](#23-_blf-0x30-bytes-v)
  - [2.4 chdr (0x2C0 bytes): byte-aligned, **little-endian** numbers, UTF-16LE strings V](#24-chdr-0x2c0-bytes-byte-aligned-little-endian-numbers-utf-16le-strings-v)
  - [2.5 The mvar block (0x7028 bytes)](#25-the-mvar-block-0x7028-bytes)
  - [2.6 _eof (0x11 bytes)](#26-_eof-0x11-bytes)
  - [2.7 Stored length, hash and the flavour pair](#27-stored-length-hash-and-the-flavour-pair)
  - [2.8 _cmp (zlib-wrapped block)](#28-_cmp-zlib-wrapped-block)
  - [2.9 _fsm and unknown blocks](#29-_fsm-and-unknown-blocks)
  - [2.10 Supported shapes and what may be modified](#210-supported-shapes-and-what-may-be-modified)
  - [2.11 Generic block file: parse and rebuild rules (the code path T1 exercises on mpvr files)](#211-generic-block-file-parse-and-rebuild-rules-the-code-path-t1-exercises-on-mpvr-files)
  - [2.12 Stored length semantics for a parsed mvar](#212-stored-length-semantics-for-a-parsed-mvar)
  - [2.13 Path and write policy for output files (library, mvarlib.io)](#213-path-and-write-policy-for-output-files-library-mvarlibio)
- [3. The bit stream: UGC header, body, slots (in stream order)](#3-the-bit-stream-ugc-header-body-slots-in-stream-order)
  - [3.1 Conventions V](#31-conventions-v)
  - [3.2 UGC header (the same structure as the mpvr game-variant header)](#32-ugc-header-the-same-structure-as-the-mpvr-game-variant-header)
  - [3.3 Body, fixed fields](#33-body-fixed-fields)
  - [3.4 Forge label table (single language)](#34-forge-label-table-single-language)
  - [3.5 Version 32: 128 extra bits](#35-version-32-128-extra-bits)
  - [3.6 Slots: 651 records, each starting with a presence bit](#36-slots-651-records-each-starting-with-a-presence-bit)
  - [3.7 Quota table and tail](#37-quota-table-and-tail)
  - [3.8 Extras by cached type, and the disputed points](#38-extras-by-cached-type-and-the-disputed-points)
  - [3.9 The placement byte (slot field 22): the two readings conflict](#39-the-placement-byte-slot-field-22-the-two-readings-conflict)
  - [3.10 Walk acceptance, hypotheses and plausibility](#310-walk-acceptance-hypotheses-and-plausibility)
  - [3.11 Mapping from a slot to Mjolnir's ForgeObject fields](#311-mapping-from-a-slot-to-mjolnirs-forgeobject-fields)
  - [3.12 Worked example](#312-worked-example)
- [4. Exact codecs and golden test vectors](#4-exact-codecs-and-golden-test-vectors)
  - [4.1 Axis bit counts (how many bits each position coordinate takes)](#41-axis-bit-counts-how-many-bits-each-position-coordinate-takes)
  - [4.2 Position codec](#42-position-codec)
  - [4.3 Shape dimension codec (11 bits, range 0 to 200)](#43-shape-dimension-codec-11-bits-range-0-to-200)
  - [4.4 Angle codec (14 bits)](#44-angle-codec-14-bits)
  - [4.5 Up axis: 20-bit cube-face code (decode only in v1)](#45-up-axis-20-bit-cube-face-code-decode-only-in-v1)
  - [4.6 Orientation reconstruction: UNVERIFIED (display only)](#46-orientation-reconstruction-unverified-display-only)
  - [4.7 Yaw encode (the only orientation write, gated)](#47-yaw-encode-the-only-orientation-write-gated)
  - [4.8 Decisions on orientation](#48-decisions-on-orientation)
  - [4.9 Change detection summary (tolerances)](#49-change-detection-summary-tolerances)
  - [4.10 Golden vector index (all pure functions; stored in tests/golden/codec_vectors.json)](#410-golden-vector-index-all-pure-functions-stored-in-testsgoldencodec_vectorsjson)
- [5. The lossless round-trip design](#5-the-lossless-round-trip-design)
  - [5.1 Data model (Python 3.9, no slots=True, no match, no X | Y at runtime)](#51-data-model-python-39-no-slotstrue-no-match-no-x--y-at-runtime)
  - [5.2 Three output modes](#52-three-output-modes)
  - [5.3 Supported edits](#53-supported-edits)
  - [5.4 What each edit must update, in order](#54-what-each-edit-must-update-in-order)
  - [5.5 Slot identity and the identity token](#55-slot-identity-and-the-identity-token)
  - [5.6 Adding an object](#56-adding-an-object)
  - [5.7 Deleting an object](#57-deleting-an-object)
  - [5.8 What is NOT safely updatable, and the messages shown](#58-what-is-not-safely-updatable-and-the-messages-shown)
  - [5.9 Dirty tracking and the bit-diff contract (used by the tests)](#59-dirty-tracking-and-the-bit-diff-contract-used-by-the-tests)
  - [5.10 export_map_variant() as one ordered algorithm (G5)](#510-export_map_variant-as-one-ordered-algorithm-g5)
- [6. Library API: mvarlib](#6-library-api-mvarlib)
  - [6.1 Module layout](#61-module-layout)
  - [6.2 Exception hierarchy](#62-exception-hierarchy)
  - [6.3 Lower-level contracts (the parts G1 and G3 must build)](#63-lower-level-contracts-the-parts-g1-and-g3-must-build)
  - [6.4 The frozen interface (Addon/mvarlib/api.py): the contract between G3/G5 and G4](#64-the-frozen-interface-addonmvarlibapipy-the-contract-between-g3g5-and-g4)
  - [6.5 Tool-facing helper API (not frozen, used by tools/)](#65-tool-facing-helper-api-not-frozen-used-by-tools)
  - [6.6 Plain-dict / JSON form (to_plain / from_plain)](#66-plain-dict--json-form-to_plain--from_plain)
  - [6.7 Command-line tools](#67-command-line-tools)
  - [6.8 Python compatibility rules (3.9 to 3.13)](#68-python-compatibility-rules-39-to-313)
- [7. Validation rules for import and export](#7-validation-rules-for-import-and-export)
  - [7.1 Data sources](#71-data-sources)
  - [7.2 Read-time refusals (exceptions)](#72-read-time-refusals-exceptions)
  - [7.3 Export refusals and warnings (Issue.code)](#73-export-refusals-and-warnings-issuecode)
  - [7.4 Two-tier object type rule and cached types](#74-two-tier-object-type-rule-and-cached-types)
  - [7.5 Quota rules](#75-quota-rules)
  - [7.6 What is validated where](#76-what-is-validated-where)
- [8. Blender integration plan, file by file](#8-blender-integration-plan-file-by-file)
  - [8.1 Files](#81-files)
  - [8.2 Registration contract (Addon/__init__.py)](#82-registration-contract-addon__init__py)
  - [8.3 State kept in the .blend](#83-state-kept-in-the-blend)
  - [8.4 Import operator (import_scene.mjolnir_mvar)](#84-import-operator-import_scenemjolnir_mvar)
  - [8.5 Export operator (export_scene.mjolnir_mvar)](#85-export-operator-export_scenemjolnir_mvar)
  - [8.6 Palette: lazy link, static menu, relink](#86-palette-lazy-link-static-menu-relink)
  - [8.7 Property-group and behaviour changes (the fix list)](#87-property-group-and-behaviour-changes-the-fix-list)
  - [8.8 UI that must be preserved](#88-ui-that-must-be-preserved)
  - [8.9 Mapping of the scene to the library (summary)](#89-mapping-of-the-scene-to-the-library-summary)
  - [8.10 Packaging](#810-packaging)
  - [8.11 Background-mode guards (headless tests and CLI use)](#811-background-mode-guards-headless-tests-and-cli-use)
  - [8.12 FileHandler](#812-filehandler)
  - [8.13 What is removed](#813-what-is-removed)
- [9. Test plan by tier, with exact commands](#9-test-plan-by-tier-with-exact-commands)
  - [9.1 The four tiers (binding decision A) and what each proves](#91-the-four-tiers-binding-decision-a-and-what-each-proves)
  - [9.2 Environment and drivers](#92-environment-and-drivers)
  - [9.3 Pure-Python test catalogue (tests/unit/)](#93-pure-python-test-catalogue-testsunit)
  - [9.4 Headless Blender tests (tests/blender/)](#94-headless-blender-tests-testsblender)
  - [9.5 T4: the ladder the user runs in MCC (also written into NOTES.md by G7)](#95-t4-the-ladder-the-user-runs-in-mcc-also-written-into-notesmd-by-g7)
  - [9.6 Manual GUI checklist (10 lines; headless runs cannot see these)](#96-manual-gui-checklist-10-lines-headless-runs-cannot-see-these)
  - [9.7 What a green run proves](#97-what-a-green-run-proves)
  - [9.8 Done-criteria traceability (the acceptance sheet)](#98-done-criteria-traceability-the-acceptance-sheet)
- [10. Risks (ordered) and what cannot be confirmed without a real .mvar or MCC](#10-risks-ordered-and-what-cannot-be-confirmed-without-a-real-mvar-or-mcc)
  - [10.1 Risks, most dangerous first](#101-risks-most-dangerous-first)
  - [10.2 Things that CANNOT be confirmed without a real .mvar (T3) or MCC (T4)](#102-things-that-cannot-be-confirmed-without-a-real-mvar-t3-or-mcc-t4)
- [11. Gate-by-gate work breakdown G0 to G7](#11-gate-by-gate-work-breakdown-g0-to-g7)
  - [Cross-gate contract: the stub provider (what lets G3 and G4 proceed in parallel)](#cross-gate-contract-the-stub-provider-what-lets-g3-and-g4-proceed-in-parallel)
  - [G0. Spec acceptance, repo guards, interface freeze](#g0-spec-acceptance-repo-guards-interface-freeze)
  - [G1. Container, bit I/O, hashing, shared header (T1)](#g1-container-bit-io-hashing-shared-header-t1)
  - [G2. Independent fixture builder and golden vectors](#g2-independent-fixture-builder-and-golden-vectors)
  - [G3. Body read path and verify_mvar (T3 tool)](#g3-body-read-path-and-verify_mvar-t3-tool)
  - [G4. Blender glue refactor against the stub provider (parallel with G1 to G3 and G5)](#g4-blender-glue-refactor-against-the-stub-provider-parallel-with-g1-to-g3-and-g5)
  - [G5. Write path and validation](#g5-write-path-and-validation)
  - [G6. End-to-end headless Blender suite](#g6-end-to-end-headless-blender-suite)
  - [G7. Packaging, docs, NOTES](#g7-packaging-docs-notes)
- [Appendix A. Spot-check log (what the author of this spec re-ran or re-read, not just trusted)](#appendix-a-spot-check-log-what-the-author-of-this-spec-re-ran-or-re-read-not-just-trusted)
  - [A.2 Checks made during the revision pass (after the two lint reports)](#a2-checks-made-during-the-revision-pass-after-the-two-lint-reports)
- [Appendix B. Index of decisions made by judgement in this spec](#appendix-b-index-of-decisions-made-by-judgement-in-this-spec)
- [Appendix C. Reference fixture W1 and golden edits](#appendix-c-reference-fixture-w1-and-golden-edits)
  - [C.1 Parameters](#c1-parameters)
  - [C.2 Golden numbers (salted_be32 flavour unless stated; stored length big-endian)](#c2-golden-numbers-salted_be32-flavour-unless-stated-stored-length-big-endian)
  - [C.3 Golden edits (all on the salted_be32 W1)](#c3-golden-edits-all-on-the-salted_be32-w1)
  - [C.4 Header-variant goldens (salted_be32; body and slots as W1, only the UGC header differs)](#c4-header-variant-goldens-salted_be32-body-and-slots-as-w1-only-the-ugc-header-differs)
- [Appendix D. Source index (where each cited fact lives)](#appendix-d-source-index-where-each-cited-fact-lives)
- [Appendix E. Rejected lint items](#appendix-e-rejected-lint-items)
- [Appendix F. Change log vs first draft](#appendix-f-change-log-vs-first-draft)

---------------------------------------------------------------------------------------------------

## 0. Conventions used in this document

### 0.1 Evidence tags (every format claim carries one)

| Tag | Meaning |
|---|---|
| `V` | VERIFIED-ON-REAL-FILES. Reproduced by a script on the real Reach **game-variant** files (`_blf/chdr/mpvr/_eof`; 8 paths, 5 distinct contents). Valid for the container, the bit-stream conventions, the shared UGC header and the `mpvr` hash. It is **never** evidence for an `mvar`-body claim. |
| `P:file:line` | PRIMARY-SOURCE. A named local file and line. Abbreviations: `JS` = `~/Documents/Halo_MCC/halo-reach-variant-tool/html/src/raw/map_variant_mvar.js` (Cobb 2020; comment at line 835: "everything above confirmed accurate via memory inspection of haloreach.dll"); `RVT` = `~/Documents/Halo_MCC/halo-reach-variant-tool/native/src/ReachVariantTool/`; `MJ` = this repo. |
| `W:HMS` | WEB. Sopitive/HaloMapStudio `crates/hms-app/src/mvar.rs` and `h4/mvar.rs` (PolyForm Noncommercial; **facts only, no code copied**). The only source that documents MCC load behaviour. Single source unless another tag is next to it. |
| `W:BLF` | WEB. Blam-Network/blf `scenario_map_variant.rs` (no licence; **facts only**). A 360-era (TU1 build 12065) independent implementation. |
| `W:URL` | other WEB page, URL given. |
| `I` | INFERRED. Reasoning, not evidence. |
| `U` | UNKNOWN. Nobody on this machine can say. |
| `S` | Spot-checked by the author of this spec in this session (re-ran or re-read). Written as a suffix, for example `P:JS:831 S`. Appendix A is the log. |
| **DECISION** `DEC-n.m` | A judgement made in this spec. Every one is indexed in Appendix B. |

**V caveat (provenance of the samples).** The 8 sample paths (5 distinct contents) share creator metadata: content id `0x4A6994BF5D589B43` in all five, timestamp 1,284,422,400 (2010-09-14) and author byte `0xA6` (re-checked `S` in the revision pass), and four of them sit beside `.lua` source files, so they are RVT-built test fixtures. `P:RVT game_variants/base.cpp:243-278` shows that RVT's writer emits exactly the salted-BE32 recipe with a little-endian stored length for multiplayer content, and its string tables are compressed with the same zlib call. `V` therefore establishes the container grammar, the bit conventions and what RVT's writer emits; it does **not** establish what the game itself writes (hash recipe, stored-length byte order, `chdr` build fields, compressor settings). Wherever a `V` below concerns one of those four things, read it with this caveat.

Rules: a statement without a tag is a design statement, not a format claim. An `I` or `U` item is never presented as fact; wherever the code depends on one, the spec says what the code does when the assumption is wrong.

### 0.2 Clean-room rule

HaloMapStudio (PolyForm Noncommercial) and Blam-Network/blf (no licence) inform **facts** in this spec only. No code from them is to be copied or transliterated. Cobb's JS is GPLv3: the spec states facts (field order, widths, constants), the implementation is written independently from this document. Nobody adds Microsoft/343 assets (meshes, textures, tags, map files, `.mvar`/`.bin` samples) to the repo, to a test fixture, or to any package, archive or copy anywhere. The only game asset in play is the upstream-tracked `Addon/Resources/Halo Reach.blend`, which is read in place (linked, never copied, re-saved or re-packaged by default; DEC-8.10).

### 0.3 Terms

- **slot**: one of the 651 object records of the map variant (index 0..650).
- **folder / item**: the 8-bit and 5-bit object-definition fields of a slot. Mjolnir calls them `itemCategory` and `itemVariant`; `type_id = (folder << 8) | item` (the object id used by `Addon/objects.py`). HMS/BLF call them `variant_quota_index` and `variant_index`.
- **L**: the stored stream length, a u32 at `mvar` chunk offset +32.
- **raw int model**: every parsed field keeps its raw integer (section 5). Floats are derived views.
- **template**: the `.mvar` file that was imported; export always patches a template, never synthesises a file from nothing.
- **bit offset** in tables: counted from bit 0 of the `mvar` bit stream (stream byte 0, most significant bit first) unless stated otherwise.

---------------------------------------------------------------------------------------------------

## 1. Executive summary and honest confidence statement

### 1.1 What is being built

A pure-Python library `mvarlib` (no `bpy`, Python 3.9 to 3.13) that reads and writes Halo: Reach map variant files (BLF container with chunks `_blf`, `chdr`, `mvar`, `_eof`), plus a thin Blender add-on layer that exposes File > Import / File > Export operators, keeps the existing Mjolnir UI, and replaces the Windows-only live-memory bridge (`ForgeBridge.dll`, ctypes, MCC process memory). The user edits a Forge map in Blender and writes a new `.mvar` that MCC can load.

The design is built around one fact: **no real `.mvar` exists on this machine.** Everything about the `mvar` body is reconstructed from Cobb's 2020 JS prototype (reverse-engineered from `haloreach.dll`) and two independent web sources. Therefore the library is (a) lossless by construction, (b) self-validating on read (it tries the documented alternative interpretations of the disputed points and accepts only a walk that ends exactly where the file says it ends), (c) loud and early in refusing, and (d) shipped with a one-command verifier the user runs on a real file (`tools/verify_mvar.py`).

### 1.2 Confidence, layer by layer

"Confidence" is the author's probability that the statement holds for a real MCC Reach `.mvar`. It is a judgement, informed by the format critique's estimate, not a measurement.

| Layer | What it rests on | Status | Confidence |
|---|---|---|---|
| BLF block header, chunk tiling, `_blf`, `chdr`, `_eof` layout | `V` (5 distinct real game variants) + `W:HMS`/`W:BLF` for map variants | verified for game variants | 0.93 |
| `mvar` chunk framing: size 0x7028, SHA-1 at +12, L at +32, bit stream at +36, 0x7000 bytes, 4 zero bytes | `P:JS:691-704` + `W:HMS` + `W:BLF` (three agree) | not verified on a real file | 0.88 |
| Stored length L is **big-endian** | `W:HMS`, `W:BLF` only (JS reads 4 raw bytes); the verified `mpvr` files store it little-endian but were RVT-written (0.1 V caveat) | | 0.75 (reader accepts both) |
| Hash recipe of an `mvar` chunk | salted-BE32 is `V` for `mpvr` only (RVT-written files, 0.1 V caveat); plain-LE32 is `W:HMS` only; an all-zero hash marks MCC-written *game variants* (`W:URL` KSoft.Blam) | unknown which; **detected per file** (`salted_be32`, `plain_le32`, `zero`, diagnostics) | by design |
| MCC enforces the SHA-1 | `W:HMS` (disassembly note: a never-set flag guards the check) | | 0.7 that it does **not** |
| UGC header in bit form (content type, file length, ids, activity, game mode, engine, map id, authors, title, description, conditional tails) | `V` (header decodes and re-encodes bit-identically on 5/5 files, re-checked `S`) + `P:RVT ugc_header.cpp:15-53` | | 0.95 |
| Body fixed fields (version, checksum, palette CRC, quota count, map id copy, 2 bits, 6 bounds floats, 2 budget words) | `P:JS:745-769` + `W:HMS` + `W:BLF` | | 0.9 |
| Forge label table (single language; 9/12/13-bit widths; optional zlib) | `P:JS:771-827`, `P:RVT localized_string_table.h:131-137`, `W:HMS`, `W:BLF` | | 0.9 |
| 651 slots, 1-bit presence, no terminator | `P:JS:831 S` + `W:HMS` + `W:BLF` | | 0.93 |
| Slot record fixed part | `P:JS:615-642` + `W:HMS` + `W:BLF` | | 0.9 |
| Cached-type-19 extra bits | **DISPUTED** (JS and BLF: 8 bits, stored value minus 1; HMS: 1 flag bit then 8 bits) | both rules implemented; chosen by the walk | 0.5 / 0.5 |
| Out-of-bounds position record | JS/Mjolnir read nothing extra; HMS reads an escape; BLF says widths come from BSP data | **abort** | n/a |
| Body version 32 adds 128 bits after the label table | `W:HMS` only | handled as a hypothesis (`guid_present`, 3.10), flagged `I` | 0.6 |
| Quota table `count x (min, max, placed)` u8 each | `P:JS:837-845` (names `unk00/01/02`) + `W:HMS` + `W:BLF` (names) | | 0.85 |
| Axis bit counts from the bounds (21-bit baseline formula) | `P:JS:79-150 S` + `W:HMS` | three rounding variants computed (4.1) | 0.9 |
| `_cmp` zlib wrapper layout | `P:RVT block.cpp:152-184` (layout) + `W:HMS` (that mvar files use it) | | 0.7 that real files use it |
| `_fsm` trailing chunk | `W:BLF`, `W:HMS` (carried verbatim) | | structure 0.6, validation behaviour <0.3 |
| `id = (folder << 8) \| item` equals the Mjolnir object id | `P:JS:571-596` comment (Tempest Coliseum Wall = subcat 71, subtype 8) and `Addon/objects.py` (`0x4708 wall_coliseum`) agree `S`; field widths 8 and 5 fit the id ranges (max category 144, max variant 25) | two independent sources | 0.85 |
| Position codec `(q + 0.5) * (range / 2^bits) + min` | `P:JS:289-330`, `P:RVT compressed_float.h` | | 0.9 |
| Shape dimension codec (11 bits, 0 to 0, 0x7FF to 200) | `P:JS:157-285 S`, RVT exact-bounds float, BLF | | 0.92 |
| Up-axis 20-bit cube-face **decode** | `P:JS:331-454` (constants table row for 20 bits matches the closed form `S`) | | 0.8 |
| **Orientation reconstruction (forward vector from up code + 14-bit angle)** | JS port is marked wrong by its author; reference vector function unknown | **UNVERIFIED** | vertical objects 0.6, tilted objects ~0.3 |
| Placement-flag bit meanings | **CONFLICT** between `W:HMS` and Mjolnir's in-memory struct (section 3.9) | edits refused | `U` |
| Which objects the game accepts on which map | `Addon/objects.py` tables (20 maps) | | 0.8 for the table; acceptance by MCC `U` |
| **MCC loads a file this tool exports** | nothing local can establish it | tiered ladder T4 | `U` |

Aggregate, taking the format critique's estimates and this spec's mitigations:

- A naive implementation of the reports' most consistent reading would decode a real MCC `.mvar` without desynchronising with probability about 0.55.
- The self-validating loader specified here "decodes correctly or refuses loudly" with probability about 0.95 and "decodes correctly" about 0.8. The residual risks are the single-source items (v32 GUID, `_cmp`, type 19, out-of-bounds records) and the fact that nobody on this machine has ever walked a real `.mvar`.
- Because an unmodified model is written back as the original bytes (section 5.2), a no-op export cannot corrupt a file. Probability that the **first real edit** (rung 2 of the ladder in 9.5) loads in MCC, given T3 passes: judgement 0.7. Adding an object: 0.5. Deleting: 0.6. These are guesses with no measurement behind them; they are given only so the owner can plan.

### 1.3 Design principles (these decide the rest of the document)

1. **Raw integers, not floats, are the source of truth** (binding decision B). Re-packing a slot from its raw integer fields is exact by construction; floats are views used for Blender and for change detection. A field is re-encoded only when its Blender value moved beyond a tolerance.
2. **Passthrough first.** An unmodified model returns the original bytes verbatim (also for `_cmp`, `_fsm`, unknown chunks and the unknown tail). A *forced* full re-encode path exists and is tested separately so that the codec itself is exercised even when no edit is made.
3. **Hypotheses, not guesses.** Where sources disagree (type 19, axis rounding, v32 GUID presence, hash flavour including an all-zero hash, length endianness) the reader tries the alternatives and accepts only a walk that consumes every slot and the quota table, ends where `L` says, and passes plausibility checks. If none passes, or two give different answers, it refuses and prints both.
4. **Stateless export from an embedded template.** The imported file is stored inside the `.blend` (bytes custom property plus SHA-256). Export re-parses the template; nothing depends on a file path, `bpy.app.driver_namespace`, or a DLL.
5. **Identity is explicit.** Every imported object carries its slot number and an identity token; deletion is defined only for slots that were successfully imported.
6. **Refuse before writing any byte**, report a diff (kept/moved/added/removed with names and slots), write to a temporary file, verify by re-parsing, then `os.replace`.
7. **Never claim more than is known.** UI and report texts say "unverified" where the format says so; unverified edits (rotation, placement flags) are opt-in or refused.

### 1.4 Binding decisions A to G: adoption

All seven binding decisions from the orchestrator are adopted. Refinements are marked; two of them (A for `_cmp` shapes, E tier 1) go beyond the literal wording and are explained in their rows; none contradicts primary-source evidence.

| Id | Binding decision | Adopted | Refinement or note |
|---|---|---|---|
| A | Tiered acceptance T1 to T4 | yes, sections 9.1 to 9.5 | The T4 rung "no-op re-save" returns the original bytes (passthrough), so it is a pipeline control, not a codec test; an optional rung H (hash-enforcement probe: a file with a corrupted or differently-hashed SHA-1) and a diagnosis column are added (DEC-9.1). For `_cmp` shapes the forced re-encode is *defined* as the expanded plain form, because no rule can promise that a regenerated zlib stream equals the original compressor output (and RVT's own saves write the plain form, `W:HMS` for the claim that the game accepts both); T2 therefore asserts passthrough == input and forced == the builder's golden expanded file for those shapes (2.11, DEC-2.6) |
| B | Never trust decode, float, encode; raw ints; tolerance; unknown bits kept raw; passthrough + forced path | yes, section 5 | |
| C | Stream facts (offset 36, 0x7028, 651 slots, parent = slot + 1, version branch, type 19 disputed, OOB abort, axis threshold caveat, label offsets, quota table) | yes, sections 2 to 4 | Stored-length endianness and hash-length endianness are two *independent* dimensions (the verified `mpvr` has LE stored length with a BE32 hash input); the detection covers both (section 2.7) |
| D | Hash flavour detection; salted fallback with warning | yes, section 2.7 | Flavour is a pair (stored-length endianness, recipe); an all-zero stored hash is a further recipe class `zero`, reproduced as zeros (DEC-2.3). The salted fallback for a non-zero hash that matches no candidate is kept exactly as decided; the lint proposal to switch it to plain_le32 was declined (Appendix E, M5) and `ExportOptions.hash_policy` lets the owner override it |
| E | Blender policy (slot props, bytes IDProperty, embedded template, lazy link, static palette JSON, relink handler, scene.objects + depsgraph for arrays, refuse-first, overwrite policy, two-tier stock rule, cachedType, rotation gate, refusals) | yes, section 8 | The rotation gate is narrowed to yaw about +Z (tilt writes are refused outright, DEC-4.8); placement-flag edits are refused (DEC-3.9); new objects need the gate (DEC-5.6); the cachedType rule is "learned from the template", plus the small hand table the plan critique allowed (class 0 for Structure and Scenery blocks only, with a warning), otherwise an explicit refusal (7.4). **Deviation from the literal wording of E, tier 1 (DEC-7.4):** an imported object whose id is not in the map's stock table is refused by default (`NOTES.md` D4, "stock objects only") and is kept verbatim only if the owner ticks "Keep objects this tool does not recognise"; ids that are in the table are kept verbatim as E says |
| F | Repo hygiene | yes, sections 8.10, 11 (G0) | `.gitignore`, `.gitattributes` and `tools/check_no_game_assets.py` **already exist as uncommitted working-tree changes**; G0 verifies them, adds a hash allowlist fallback, and commits (DEC-F.1). The guard also scans gitignored files (DEC-F.2), and the default package contains no game asset (DEC-8.10) |
| G | Gates G0 to G7 | yes, section 11 | interface freeze (`api.py` complete, with `errors.py`) added to G0 so G3 and G4 can run in parallel; the tables and path-policy modules move to G0 for the same reason |

### 1.5 Conflict register: where sources disagree, what this spec decides and why

| # | Topic | Sources in conflict | Decision |
|---|---|---|---|
| X1 | Where the `mvar` bit stream starts | `container-and-bit-conventions.md` section 7 (+0x28 vs +0x24, open) and `blf_container.py` default `prefix=0x28`; vs JS/HMS/BLF (+36) | **+36 (0x24)**, big-endian length at +32. JS reads hash (0x14 bytes) then 4 bytes then the header bits `P:JS:699-704 S`; HMS and BLF agree. The `mpvr` layout (+0x28, LE length at +0x24) is a different chunk type. `blf_container.py` is promoted with `mvar` and `mpvr` as separate payload specs |
| X2 | File size of a plain map variant | `container-and-bit-conventions.md` says 0x9329; `web-mvar-format.md` says 29,481 | **29,481 = 0x7329** (0x30 + 0x2C0 + 0x7028 + 0x11 `S`); `_eof` offset 0x7318. The 0x9329 text is an arithmetic slip |
| X3 | Terminator vs 651 slots | `upstream-mvar-branch.md` 9.1 keeps H-T open | **651 slots, presence bit each, no terminator, never stop at the first absent slot** `P:JS:831 S` |
| X4 | Parent link storage | `upstream-mvar-branch.md` "raw, none = 0x3FF" | **stored = parent slot + 1, 0 = none** `P:JS:641 S` |
| X5 | Type-19 extra bits | JS and BLF vs HMS | **DISPUTED**; both rules are hypotheses; the walk decides; type-19 objects cannot be *created* unless the rule is determined by the template (section 3.8) |
| X6 | Out-of-bounds position records | JS/Mjolnir (nothing extra) vs HMS (escape) vs BLF (BSP data not in file) | **abort with a clear error** (binding C) |
| X7 | Version | JS "must be 0x1F" vs HMS "31 and 32" | accept 31 and 32; v32 adds 128 bits after the label table `I`; whether they are present is a hypothesis, the version only orders the two values (3.10); anything else refused |
| X8 | Hash recipe | HMS plain-LE32 (MCC) vs salted-BE32 (`V` for `mpvr`, RVT-written files) vs all-zero (KSoft.Blam: MCC-written game variants) | detect per file; reproduce (zeros included); non-zero and unmatched => salted + loud warning (binding D) |
| X9 | Length field endianness | HMS/BLF BE for mvar vs `V` LE for mpvr | accept either (value must be <= 0x7000), preserve; write BE when the template gives no evidence |
| X10 | Axis-bit rounding | JS `ceil` (double, constant 0.00833333333) vs HMS `+0.9999` truncate (f32) vs the engine's own f32 constant `0x3C088889` with `ceil` | compute all three; they differ only in slivers around exact cell-count thresholds; every distinct triple is a hypothesis |
| X11 | Position decode formula | BLF implies exact endpoints; JS/HMS/RVT cell centre | cell centre; and never recompute raw ints from floats for untouched axes |
| X12 | Label table language count | `upstream-mvar-branch.md` 6 worried about 12 languages | **single language** (JS, HMS, BLF all agree; widths 9/12/13 follow from 256 strings, 4096-byte buffer) |
| X13 | "Shape codec cannot be re-encoded naively (148 of 2048 codes)" | `upstream-mvar-branch.md` 7 | not reproducible: 0 failures `S`; harmless because raw codes are kept |
| X14 | Up-axis codes re-encode identically | implied by "decode then encode" | false for 4,998 of 1,043,334 valid codes (outer ring) and there is no code for exact +Z; raw codes and the 1-bit `up_global` are kept; no tilted-up encoder in v1 |
| X15 | Placement-flag byte meaning | Mjolnir `ForgeObject.cs` (0x02 HideAtStart, 0x04 Symmetric, 0x08 Asymmetric) vs HMS (0x10 not-at-start, 0x08 symmetric, 0x04 asymmetric, 0x02 shortcut, 0x01 hide-unless-required) | **DISPUTED**; display uses the HMS (file) reading, edits other than physics are refused (section 3.9) |
| X16 | Team/colour names | JS calls the 4-bit field "color" and the 3-bit field "team"; HMS/BLF the reverse | order and widths are identical; this spec uses HMS/BLF names (team 4 bits, colour 1+3 bits) |
| X17 | Slot count vs "650 limit" | file has 651 slots; community says 650 | export cap = **650 occupied slots** (conservative, `U` whether 651 works) |
| X18 | Stock id tables | `ItemParser.cs` vs `Addon/objects.py` (36 ids disagree) | `objects.py` is canonical (newer, derived from a tag export); the 8 genuinely conflicting ids (Tempest and Breakneck cannons) are flagged `disputed` in the data file, the other differences are spelling |
| X19 | Palette linking | `blender-5-2.md` A6 "link in register()" | **impossible** (`bpy.data` is `_RestrictData` during startup register, re-verified `S`); link lazily inside operators |
| X20 | Overwrite policy | `addon-architecture.md` 6.2 "write a new name and keep a .bak" | no `.bak`; never write onto the source path or a protected folder; temp file + `os.replace` |
| X21 | Mjolnir `ConvertForge` | exports type 0 = Assault Rifle | refuse objects with no resolvable type |
| X22 | `maps*.json` | task text mentions `tables/maps*.json` | **does not exist** in `research/tables/`; the map table is built from RVT `page_map_perms.cpp:15-58` `S` and `Addon/objects.py` map names (G0 deliverable) |
| X23 | JS gameMode check | JS line 734 tests `this.gameMode`, which is undefined (typo for `o.gameMode`) `S` | JS never reads the campaign/firefight header tails; RVT C++ does `P:RVT ugc_header.cpp:39-51`; this spec follows the C++ |
| X24 | Nested bytes in IDProperties | only top-level bytes and a nested dict without bytes were tested | store the template as a **top-level** scene key (DEC-8.3) |
| X25 | Stored hash all zero | KSoft.Blam: an all-zero hash marks an MCC-written *game variant* (length byte-swapped); nothing documents map variants | candidate recipe `zero`: detected and reproduced; `I` for `mvar` (2.7) |
| X26 | Chunk version of the `mvar` block | `web-mvar-format.md` section 6 (from HMS `h4/mvar.rs`): Halo 4 map variants share the 0x7028 chunk size with chunk versions 50/51; Halo 3 uses 12 to 14 | known non-Reach versions refused, other unexpected versions warn (2.2, 7.2); not re-verified against the HMS source |

---------------------------------------------------------------------------------------------------

## 2. Container specification: `_blf`, `chdr`, `mvar`, `_eof`, `_cmp`, `_fsm`

### 2.1 Block header (all blocks, 12 bytes, big-endian)

| Offset | Size | Field | Notes | Tag |
|---|---|---|---|---|
| 0 | 4 | signature | ASCII, for example `_blf`, `chdr`, `mvar`, `_eof` | `V`, `P:RVT block.cpp:24-51` |
| 4 | 4 | size, u32 BE | whole block **including** this header; `size < 12` is a bad block | `V`, `P:RVT block.cpp:148` |
| 8 | 2 | version, u16 BE | | `V` |
| 10 | 2 | flags, u16 BE | 1 = "initialized" (payload blocks, `_eof`), 2 = "is header" (`_blf`, `chdr`) | `V`, `P:ReachVariantTool/html/src/raw/game_variant_blam.js` |

Blocks tile the file up to and including `_eof` (`V`, 5 distinct files: the sum of the sizes equals the file length). Bytes after `_eof` are parsed as further blocks while they form valid blocks (`_fsm`); any remainder is kept as an opaque `trailer` (shape `other`, verbatim passthrough; a modified save keeps it verbatim and warns `W_TRAILER_KEPT`), because RVT itself stops at padding after `_eof` (`P:RVT game_variants/base.cpp:373`: "some files have a TON of empty padding space at their ends", re-read `S`). A parser must reject: first block not `_blf`; a block that runs past the end of the file before `_eof`; no `_eof`; more than 256 blocks.

### 2.2 Layout of a plain map variant (the case this tool writes)

| # | Block | Version.flags | Size | File offset | Evidence |
|---|---|---|---|---|---|
| 1 | `_blf` | 1.2 | 0x30 | 0x0000 | `V` (game variant), `W:HMS` |
| 2 | `chdr` | 10.2 | 0x2C0 | 0x0030 | `V` (game variant), `W:HMS` (map variant) |
| 3 | `mvar` | 31.1 expected | 0x7028 (28,712) | 0x02F0 | `P:JS:691-694 S` (size), `W:BLF` ("31.1"), `W:HMS` ("A v31 mvar chunk is 28712 bytes") |
| 4 | `_eof` | 1.1 | 0x11 | 0x7318 | `V` (game variant), `W:BLF` |

Total = 0x30 + 0x2C0 + 0x7028 + 0x11 = 48 + 704 + 28,712 + 17 = **29,481 bytes = 0x7329** `S`. The `_eof` body value is 0x7318 = 29,464. (An earlier report wrote 0x9329; that is wrong, X2.) The `mvar` bit stream starts at file offset 0x2F0 + 36 = **0x314**.

The reader never *requires* flags 1 for the `mvar` block (it preserves whatever it finds) and records version and flags. It *requires* the `mvar` size to be exactly 0x7028 (`P:JS:691-694`: the JS prototype throws otherwise). **Chunk version policy (X26):** the chunk versions 12, 13, 14 (Halo 3) and 50, 51 (Halo 4) are refused with `UnsupportedVariantError` (they share the chunk size, so a Halo 4 file would otherwise pass every container check and be caught only by the walk's roughly 4 % false-pass rate, `W:HMS` via `web-mvar-format.md` section 6, not re-verified); any other value outside {31, 32} is accepted with warning `W_CHUNK_VERSION_UNEXPECTED` and left to the walk. The chunk version and the body version byte (3.3) should be equal; a mismatch is warning `W_VERSION_MISMATCH` and the body byte orders the GUID hypothesis.

### 2.3 `_blf` (0x30 bytes) `V`

| Offset | Size | Value in real game variants |
|---|---|---|
| 0x00 | 12 | header `_blf`, 0x30, 1, 2 |
| 0x0C | 2 | `FF FE` (byte-order mark) |
| 0x0E | 0x20 | zero |
| 0x2E | 2 | zero |

The library keeps all 0x30 bytes verbatim.

### 2.4 `chdr` (0x2C0 bytes): byte-aligned, **little-endian** numbers, UTF-16LE strings `V`

Layout from `P:RVT ugc_header.cpp:54-86` and `V` on game variants. It is assumed identical for map variants (`W:HMS`; `I`). The library keeps all 0x2C0 bytes verbatim and interprets only the starred fields.

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 12 | header | `chdr`, 0x2C0, 10, 2 |
| 0x0C | 2 | build major u16 | 0 in real files |
| 0x0E | 2 | build minor u16 | 0xFFFF in real files |
| 0x10 | 1 | **contentType** i8 (*) | 5 = map variant, 6 = game variant (`V` for 6; `P:RVT ugc_header.h:13-22` enum for 5) |
| 0x11 | 3 | pad | |
| 0x14 | 4 | **fileLength** u32 LE (*) | total file length through `_eof` (21,289 in the game-variant samples `V`) |
| 0x18, 0x20, 0x28, 0x30 | 4 x 8 | unk08, unk10, unk18, unk20 u64 | content ids; meaning unknown |
| 0x38 | 1 | activity i8 | |
| 0x39 | 1 | gameMode u8 | |
| 0x3A | 1 | engine u8 | |
| 0x3B | 1 | pad | |
| 0x3C | 4 | **mapID** u32 (*) | 0xFFFFFFFF in game variants; the base map for map variants (`P:RVT ugc_header.h:51`) |
| 0x40 | 4 | engineCategory u32 | |
| 0x44 | 4 | pad | |
| 0x48 | 0x24 | createdBy | u64 timestamp (Unix s), u64 xuid, char[16] name, u8 isOnlineID, 3 pad |
| 0x6C | 0x24 | modifiedBy | same |
| 0x90 | 0x100 | **title** (*) UTF-16LE x 128, NUL padded | |
| 0x190 | 0x100 | **description** (*) | |
| 0x290 | 4 | engineIcon u32 | |
| 0x294 | 0x1C | unk | zero |
| 0x2B0 | 8 | campaign: id u8, difficulty u8, metagameScoring u8, rallyPoint u8, unk u32 | |
| 0x2B8 | 8 | unk | zero |

`verify_mvar` cross-checks the starred fields against the bit-form header (title, description, map id, content type, file length) and reports mismatches as warnings (RVT calls the `chdr` block "non-essential", always generated by the game as an easy-to-read metadata view: `P:RVT game_variants/base.cpp:383 S`; whether MCC reads it for map variants is `U`).

### 2.5 The `mvar` block (0x7028 bytes)

| Offset in block | Size | Field | Evidence |
|---|---|---|---|
| +0x00 | 12 | block header `mvar`, 0x7028, version, flags | `P:JS:687-697` |
| +0x0C | 20 | SHA-1 | `P:JS:699` (`readBytes(0x14)`) |
| +0x20 (32) | 4 | **L**, stored stream length, u32 | `P:JS:700` reads 4 raw bytes; **big-endian** per `W:HMS` ("BE u32 at +32") and `W:BLF`; the reader accepts either order (2.7) |
| +0x24 (36) | 0x7000 | **bit stream**, MSB-first, zero padded to capacity | `P:JS:700-704`, `W:HMS`, `W:BLF` |
| +0x7024 | 4 | zero pad | `W:HMS`, `W:BLF`; arithmetic: 12 + 20 + 4 + 0x7000 + 4 = 0x7028 `S` |

**This differs from `mpvr` (game variant)** `V`: `mpvr` has the hash at +12, **4 unused bytes at +32**, a **little-endian** length at +36 and the stream at **+40** (size 0x5028, capacity 0x5000). A reader or writer built from the `mpvr` layout is off by 32 bits on the first field of an `mvar` (X1). The generic block code therefore takes a `PayloadSpec` per signature (section 6.3).

Stream capacity: 0x7000 bytes = 229,376 bits. The writer refuses anything that needs more (DEC-2.1: stricter than HMS, which allows spill into the 4 pad bytes, 229,408 bits).

### 2.6 `_eof` (0x11 bytes)

Header `_eof`, 0x11, 1, 1; body: u32 **big-endian** = file offset of the `_eof` block itself (21,272 in the 21,289-byte game variants; **not** the file length) `V`; then one byte 0 (authentication type 0 = none, `W:BLF`). In a plain map variant the value is 0x7318. RVT reads it little-endian by default but never uses it, and its writer comment says "in some files this is little-endian, without the block having a different version or flags" (`P:RVT game_variants/base.cpp:32-46 S`); all real files here are big-endian `V`. **DECISION DEC-2.2b:** the reader accepts either byte order (the valid reading is the one equal to the block's own offset), records it, and a forced rebuild reproduces the template's order (BE if neither reading matches).
A longer `_eof` (size 0x105, auth type 3, 256-byte RSA signature, `W:BLF`) is treated as an unknown variant: passthrough only, modified saves refused (DEC-2.2).

### 2.7 Stored length, hash and the flavour pair

Two independent facts differ per file; both are detected:

1. **Stored-length byte order** of the 4 bytes at +32: BE (`W:HMS`, `W:BLF`) or LE (the verified `mpvr` convention `V`). Rule: interpret the 4 bytes both ways; the valid reading is the one whose value is in `1..0x7000` (they cannot both be valid unless the value is 0). If the raw value is 0, effective L is tried as both 0 and 0x7000 (`W:BLF`: "if stored length is 0 use min(0x7000, available)"). If neither reading is valid, `FormatError: stored stream length`.
2. **Hash recipe**. Candidates, all over `stream[0:L]` (the bytes of the stream, including the embedded fileLength field as stored):

| Name | Digest input | Origin | Tag |
|---|---|---|---|
| `plain_le32` | `LE32(L) \|\| data` | "PlainLe", said to be MCC's own (`H4HashKind::PlainLe`, tried first by `detect_hash_kind`) | `W:HMS` |
| `salted_be32` | `SALT34 \|\| BE32(L) \|\| data` | Xbox 360 recipe ("SaltedBe360") | `V` for `mpvr` (re-run `S`: 5/5 match, plain-LE does not); `W:HMS`, `W:BLF` for `mvar` |
| `salted_le32` | `SALT34 \|\| LE32(L) \|\| data` | diagnostic only | `I` |
| `plain_be32` | `BE32(L) \|\| data` | diagnostic only | `I` |
| `data_only` | `data` | diagnostic only | `I` |
| `zero` | no digest: the 20 hash bytes are all `0x00` | MCC-written game variants per KSoft.Blam `GameEngineVariantBlob.cs` (`W:URL` https://raw.githubusercontent.com/KornnerStudios/KSoft.Blam/main/KSoft.Blam/Blob/Presentation/GameEngineVariantBlob.cs, MIT, facts only): the flag "probably from MCC" starts true and becomes false if any hash byte is non-zero; read in the revision pass `S`. Game variants only; nothing documents map variants | `W:URL`; `I` for `mvar` |

`SALT34` = `ED D4 30 09 66 6D 5C 4A 5C 36 57 FA B4 0E 02 2F 53 5A C6 C9 EE 47 1F 01 F1 A4 47 56 B7 71 4F 1C 36 EC` (`P:RVT formats/sha1.h:4-14 S`, 34 bytes). It is a published constant in the GPL source and is a *public algorithm constant*, not game data.

Test vector (synthetic, `S`): `data = 00 01 02 03 04 05 06 07 08 09`, `L = 10`:
- `salted_be32` = `6f0d524ee1491d003958ab5065fa74db67f4cc7e`
- `plain_le32` = `908ea657bfe5b911f8752827b0c8e5ad9fef06b3`
- `salted_le32` = `134da971af17127d0854f27a1a4dd49b2aa9a671`
- `plain_be32` = `6df6c8eef85b2a16452be2f9adf695fa478b61c2`
- `data_only` = `494179714a6cd627239dfededf2de9ef994caf03`

**Flavour** = `(length_endian, recipe)`; detected once at parse time and stored in the model. `recipe` is one of the five digest names above or `zero`; a stored hash of 20 zero bytes is classed `zero` before any digest is tried (a real digest of 20 zero bytes is not a practical concern).

**DECISION DEC-2.3 (writer):** the writer reproduces the template's flavour `(length byte order, recipe)`.
1. The stored hash matches a digest candidate: write that recipe.
2. The stored hash is 20 zero bytes (`zero`): write 20 zero bytes and report info `I_HASH_ZERO`.
3. The stored hash is non-zero and matches no candidate: write `salted_be32` with the template's valid length byte order (BE when the field was ambiguous) and emit the loud warning `W_HASH_UNKNOWN` (text in 7.3: the salted recipe was written; whether MCC checks it is unknown).
Rationale for 3: binding decision D, and `salted_be32` is the only recipe verified on real files (for `mpvr`; RVT-written, 0.1 V caveat). The lint review proposed `plain_le32` for case 3 because HMS calls it MCC's recipe; that rests on one WEB source, contradicts binding decision D and is not adopted as the default (Appendix E, M5). Instead `ExportOptions.hash_policy` (default `REPRODUCE`; also `SALTED_BE32` and `PLAIN_LE32`) forces a recipe regardless of the template, so the owner can switch once T3/T4 evidence exists; `tools/reencode_mvar.py --hash-recipe NAME`, `--zero-hash` and `--corrupt-hash` write the probe files of ladder rung H (9.5). The T3 report prints which candidate matched, so the first real file settles the question.

MCC enforcement of the hash: `W:HMS` says the loader recomputes the hash but rejects a mismatch only when a never-written global flag is set ("A stale hash still loads"). Single source, disassembly-based; treat as `I`. The tool always writes a correct hash anyway.

### 2.8 `_cmp` (zlib-wrapped block)

Layout (`P:RVT block.cpp:152-184` for the layout; `W:HMS` for "some shipped map variants use it, for example Empire.mvar"):

| Offset | Size | Field |
|---|---|---|
| +0 | 12 | header `_cmp`, size = whole wrapper, version, flags |
| +12 | 1 | compression type; **0 = zlib** (HMS handles only 0; RVT calls it `unk00`) |
| +13 | 4 | uncompressed size, u32 BE |
| +17 | rest | zlib stream (`78 xx` header) that inflates to **a complete block** including its own 12-byte header |

Rules: on parse, a `_cmp` block is inflated (`zlib.decompress`), the result must be exactly the declared size and a self-consistent block, and it takes the place of the wrapper in the logical block list while the wrapper bytes are remembered. Compression type other than 0, a failed inflate, or a size mismatch is a `FormatError`.
- Unmodified save: the **original wrapper bytes** are emitted (passthrough, also in `force=False` after edits to other blocks).
- Modified save: the plain inflated block is written (the game accepts both forms, `W:HMS`; its own saves write the plain form), `_eof` and both fileLength fields are re-stamped for the new total length, and warning `W_CMP_EXPANDED` is issued. Whether the fileLength inside such a file counts the compressed or the expanded size is `U`; the writer sets the expanded plain length.
- Forced re-encode: `to_bytes(force=True)` of a `_cmp` shape returns the same expanded plain form, never the original wrapper and never a regenerated zlib stream (DEC-2.6, 2.11).
- A `_cmp` that wraps something other than `mvar`/`mpvr` is kept as an unknown block.

### 2.9 `_fsm` and unknown blocks

`_fsm` ("file-share metadata", MCC): version 1.1, fixed fields of 0x1C4 bytes including a 256-byte RSA-SHA512 attestation (`W:BLF`). It follows `_eof` and is **not** counted in the file length fields (`W:HMS`). What it signs is `U`.
- Unmodified save: verbatim.
- **DECISION DEC-2.4:** a modified save **keeps** `_fsm` verbatim by default (this is what HMS does, and HMS reports that its saved files load in MCC) and issues warning `W_FSM_STALE: the file-share signature block was kept; if MCC refuses the file, export again with fsm_policy=DROP`. The export option `fsm_policy` is `KEEP` (default) or `DROP`. `fsm_policy = DROP` on a template that carries `_fsm` counts as a modification: the result is the shape without `_fsm`, never the template bytes (5.10 step 10).
- Any other block after `_eof` is kept verbatim. Any unknown block *before* `_eof` is kept verbatim in place; a modified save is refused if the block list is not one of the supported shapes in 2.10.

### 2.10 Supported shapes and what may be modified

| Shape id | Block list | Read | Unmodified save | Modified save |
|---|---|---|---|---|
| `plain4` | `_blf`, `chdr`, `mvar`, `_eof` | yes | verbatim | yes |
| `plain4+fsm` | plain4 then `_fsm` | yes | verbatim | yes (DEC-2.4) |
| `cmp4` | `_blf`, `chdr`, `_cmp(mvar)`, `_eof` | yes | verbatim | yes, expands (2.8) |
| `cmp4+fsm` | cmp4 then `_fsm` | yes | verbatim | yes, expands |
| `other` | anything else that tiles (extra or reordered blocks, long `_eof`) or carries a non-block trailer after `_eof` (2.1) | readable if an `mvar` block is found | verbatim | **refused** (`E_CONTAINER_SHAPE`) |

For the two `cmp4` shapes `to_bytes(force=True)` returns the expanded form of 2.8, not the input (DEC-2.6).

### 2.11 Generic block file: parse and rebuild rules (the code path T1 exercises on `mpvr` files)

`BlfFile` knows nothing about slots. It parses any tiling block list; for blocks whose signature has a registered `PayloadSpec` it can also *finalise* them.

Parse: read blocks, expand `_cmp`, keep `raw` bytes for every block, record shape id and any flavour detection results.

`to_bytes(force=False)`:
1. If nothing is dirty and `force` is false: return the original bytes (verbatim).
2. Otherwise emit each block: clean blocks as their `raw` bytes (or wrapper), dirty blocks rendered.

`to_bytes(force=True)` ("forced rebuild": recompute everything derivable) performs, in this order:
1. block sizes from the rendered bodies (`_blf` 0x30, `chdr` 0x2C0, payload spec size, `_eof` 0x11);
2. `F` = sum of the sizes of the blocks up to and including `_eof`;
3. patch the payload's embedded fileLength field (32 bits, MSB-first, at bit 72 of the `mpvr` stream and at **bit 4** of the `mvar` stream, `P:RVT ugc_header.cpp:18-19`) to `F`;
4. L: for a payload whose body is parsed (`mvar`) from the walk (2.12); for an opaque payload (`mpvr`) keep the stored L (it equals "last non-zero byte + 1" in 5/5 real files `V`);
5. SHA-1 by the detected flavour (`salted_be32` default for `mpvr`; `zero` writes 20 zero bytes; 2.7); the 4 pad bytes after the stream are copied from the template (zero for synthesised files);
6. `_eof` body := offset of the `_eof` block;
7. `chdr` fileLength (+0x14, LE) := `F`;
8. trailing blocks and the opaque trailer verbatim.

For the 8 real game-variant files (5 distinct) forced rebuild must reproduce the input byte for byte (this is what `blf_container.py --selftest` shows `V`; re-run in the revision pass: all 5 distinct files rebuilt byte-exactly). For synthetic map variants of shape `plain4` and `plain4+fsm` (T2) it must also reproduce the input.

**DECISION DEC-2.6:** for the shapes `cmp4` and `cmp4+fsm`, `to_bytes(force=True)` is *defined* to return the expanded form (no `_cmp`; `_eof` and both fileLength fields re-stamped; warning `W_CMP_EXPANDED`), because no rule can promise that a regenerated zlib stream equals the original compressor output (5.2 already says label recompression depends on the zlib implementation). Tests assert for those shapes: (1) `to_bytes()` (passthrough) equals the input; (2) `to_bytes(force=True)` equals the builder's golden `<name>_expanded` file; (3) `parse(to_bytes(force=True))` has slots, labels and quotas equal to the input's. Identity `force=True == input` is asserted only for the shapes `plain4`, `plain4+fsm` and the 8 real game variants.

### 2.12 Stored length semantics for a parsed `mvar`

Let `end` be the bit position after the quota table (section 3.7). The reader classifies the template:
- `ceil_end`: `L == ceil(end / 8)` (expected; `W:HMS`: "length when writing: ceil(end_bit/8)");
- `capacity`: `L == 0x7000`;
- `zero`: the stored bytes are `00 00 00 00` (effective length 0x7000 for reading, `W:BLF`; written back as `00 00 00 00`);
- `other`: anything else.

**DECISION DEC-2.5:** a walk is *accepted* only if the class is `ceil_end`, `capacity` or `zero` (3.10). The writer keeps the class: `ceil_end` -> recompute `ceil(end / 8)` after edits; `capacity` -> keep 0x7000; `zero` -> keep `00 00 00 00`. `other` never occurs in an accepted walk. Bytes in `[L, 0x7000)` are not hashed (`W:HMS`: the engine reads the whole stream regardless of L).

### 2.13 Path and write policy for output files (library, `mvarlib.io`)

- `write_atomic(target, data, source_paths=(), protected=None)` (every tool that writes a file goes through it, the command-line tools included, not only the add-on): refuse (`PathPolicyError`) if `target` resolves (`os.path.realpath`) to the same file as any source path given, or lies under a protected directory (historical default strings: `~/Local_Documents/rvt-test-samples`, `~/Local_Documents/ReachVariantTool-core-library`; configurable in add-on preferences). Otherwise write `<target>.tmp-<pid>` in the same directory with `O_EXCL`, `fsync`, then `os.replace`. Never create a `.bak`. Never rename an existing file.
- `check_output_path(target, source_paths=(), protected=None)` runs the same two checks without writing and returns the `Issue` (`E_PATH_SAME_AS_SOURCE` or `E_PATH_PROTECTED`) or `None`; the export operator calls it before collecting any object.
- Default output name: `<source stem>_mjolnir.mvar` in the source file's directory. If that directory is, or lies inside, a protected folder, the operator proposes `~/Documents/Mjolnir Exports/<stem>_mjolnir.mvar` instead (the folder is created on export), so the proposed default is never a refused path.
- After writing the temp file and **before** `os.replace`, re-read it and run `verify_roundtrip` (parse with the same options, same hypotheses, expected set of changed slots). A failure deletes the temp file and refuses.

---------------------------------------------------------------------------------------------------

## 3. The bit stream: UGC header, body, slots (in stream order)

### 3.1 Conventions `V`

- Bit 0 of the stream is the most significant bit of stream byte 0. A field of n bits is the next n bits; its first bit is the most significant bit of the value, so every multi-bit field is big-endian even when unaligned (`V`: the embedded header decodes to the independent little-endian `chdr` values; negative control with LSB-first fails).
- Reads past the end of the 0x7000-byte stream are an error in this library (RVT returns zero bits and counts an overflow; we treat overrun inside a walk as a desync).
- `float` = 32 raw bits, big-endian IEEE-754. Strings: 8-bit chars or 16-bit units read MSB-first (so UTF-16BE), each **stops after the first NUL** or at the maximum length (`V`: authors 16 chars; title and description 128 units; `P:RVT helpers/bitreader.cpp:32-45`). Signed fields are two's complement. "Stored +1" fields hold `value + 1` (so "none" is stored as 0).
- Optional fields: some have a presence bit with **1 = present** (slot, label-offset entries); others an *absent* bit with **1 = none** (folder, item, label, colour). The polarity is not uniform; the tables say which.
- The reader must support field widths 0 to 64 (a 0-bit read returns 0 and consumes nothing); position axes use 0 to 26 (upstream's `ReadBits` only supported 17 to 24 for positions, an upstream bug: `upstream-mvar-branch.md` section 2, `critique-format-correctness.md` D15).

### 3.2 UGC header (the same structure as the `mpvr` game-variant header)

Evidence: `P:RVT formats/ugc_header.cpp:15-53` (read) and `:87-121` (write) `S`; `P:JS:702-737`; `V` (this exact sequence decodes the 5 real game variants and re-encodes bit-identically, re-run `S`: header lengths 1,535 / 1,183 / 2,287 / 2,271 / 2,575 bits). Map variants start the stream with it; game variants put a 68-bit prefix (4-bit engine type, u32 encodingVersion, u32 engineVersion) before it.

| Bit offset | Width | Field | Stored form | Notes | Tag |
|---|---|---|---|---|---|
| 0 | 4 | contentType | value + 1 | map variant 5 -> stored **6**; game variant 6 -> 7 `V`. `UnsupportedVariantError` if not a map variant | `V`; `P:RVT ugc_header.cpp:18`, `P:JS:704` |
| 4 | 32 | fileLength | u32 | total file length through `_eof` (29,481 for plain4); inside the hashed region | `V`; `P:RVT:19`, `P:JS:708` |
| 36 | 64 | unk08 | u64 | content ids; opaque | `V`; `P:RVT:20`, `P:JS:709` |
| 100 | 64 | unk10 | u64 | | `V`; `P:RVT:21` |
| 164 | 64 | unk18 | u64 | | `V`; `P:RVT:22` |
| 228 | 64 | unk20 | u64 | | `V`; `P:RVT:23` |
| 292 | 3 | activity | value + 1 | `hopperID` below is present iff the DECODED value (stored - 1) equals 2, i.e. stored 3: `P:RVT ugc_header.cpp:37` tests the decoded bitnumber and the JS tests `readBits(3) - 1` (`P:JS:713,730`, re-read `S`). No primary source says what value 2 means | `V` (stored 4, decoded 3, in every real sample); `P:RVT:24,37`, `P:JS:713` |
| 295 | 3 | gameMode | u3 | 1 campaign, 2 firefight, 3 matchmaking, 4 forge, 5 theater (`P:RVT ugc_header.h:24-31`) | `V`; `P:RVT:25`, `P:JS:716` |
| 298 | 3 | engine | u3 | | `V`; `P:RVT:26`, `P:JS:717` |
| 301 | 32 | mapID | u32 | the stock-map id (section 7.1) | `V` (0xFFFFFFFF in game variants); `P:RVT:27`, `P:JS:719` |
| 333 | 8 | engineCategory | u8 | | `V`; `P:RVT:28`, `P:JS:721` |
| 341 | A | createdBy | author record | below | `V`; `P:RVT:29`, `P:JS:722-723` |
| 341 + A | A' | modifiedBy | author record | | `V`; `P:RVT:30`, `P:JS:724-725` |
| ... | 16 t | title | UTF-16BE units, NUL-terminated, t <= 128 | t counts the NUL if present | `V`; `P:RVT:31-32`, `P:JS:728` |
| ... | 16 d | description | same | | `V`; `P:RVT:33-34`, `P:JS:729` |
| ... | 8 | engineIcon | u8 | **only if contentType is game variant**; absent for map variants | `V` for game variants; `P:RVT:35-36` |
| ... | 16 | hopperID | u16 | only if the decoded activity == 2 (stored 3) | `P:RVT:37-38`, `P:JS:730-731`; not exercised by any real file (`I` for the width); fixture `hdr_hopper` (G2) pins it |
| ... | 52 | campaign tail | id u8, difficulty u2, metagameScoring u2, rallyPoint u8, unk u32 | only if gameMode == 1 | `P:RVT:40-46`; the JS tests `this.gameMode` (typo, X23); no real file has gameMode 1 (`I` for the width); fixture `hdr_campaign` pins it |
| ... | 34 | firefight tail | difficulty u2, unk u32 | only if gameMode == 2 | `P:RVT:47-50`; no real file has gameMode 2 (`I` for the width); fixture `hdr_firefight` pins it |

Author record (`P:RVT content_author.cpp:11-16`): `u64 timestamp`, `u64 xuid`, name as 8-bit chars stopping after the first NUL, at most 16 chars read (so `n` in 1..16), `u1 isOnlineID`. Bits = 129 + 8 n.

Header end `E_h = 341 + (129 + 8 n_c) + (129 + 8 n_m) + 16 t + 16 d + (16 if the decoded activity == 2) + (52 if gameMode == 1) + (34 if gameMode == 2)`. Any fixed skip such as Mjolnir's 298, 516 or 110 x 8 + 7 is wrong in general (the author names are variable length).

The conditional tails (hopper, campaign, firefight) and the variable-length text are exercised by no real file and by no primary source for a map variant (X23), and a wrong width here would shift the whole body (`I`). The synthetic fixtures `hdr_hopper`, `hdr_campaign`, `hdr_firefight`, `hdr_long_text` and `hdr_min_text` (G2, Appendix C.4) pin the widths the spec states; they check the code against this document, not against the game.

Library behaviour: the header is parsed into fields **and** its raw bit range `[0, E_h)` is kept. Header fields are not editable in v1 (DEC-3.1); the raw range is re-emitted, with only the 32-bit fileLength re-stamped in a rebuild (2.11).

Consistency checks at parse (warnings unless noted): contentType stored 6 (error otherwise); fileLength equals the real length; map id equals `chdr` map id; title/description equal the `chdr` strings; `E_h` < 0x7000 x 8.

### 3.3 Body, fixed fields

Offsets relative to `E_h`. Evidence: `P:JS:745-769` (names `unk02B0` etc.), `W:HMS`, `W:BLF`; Mjolnir's skip constants 115 and 64 (`upstream-mvar-branch.md` 4.3) equal the sums below.

| Offset | Width | Field | JS name | Notes | Tag |
|---|---|---|---|---|---|
| +0 | 8 | version | unk02B0 | 31 (0x1F). JS: "Reach would abort" if not 0x1F. HMS: 31 and 32 exist. Accept {31, 32} (**DEC-3.4**); else `UnsupportedVariantError`. Should equal the `mvar` chunk version (2.2): a mismatch is warning `W_VERSION_MISMATCH`. This byte orders the GUID hypothesis (3.10) | `P:JS:745-747`; `W:HMS` for 32 (`I`) |
| +8 | 32 | checksum | unk02DC | named "original map RSA signature hash" (BLF) / "map-variant-checksum" (HMS); 0xFFFFFFFF on every shipped file (HMS). Opaque | `P:JS:748`; `W:BLF`, `W:HMS` |
| +40 | 32 | scenario palette CRC | unk02E0 | HMS: if it differs from the loaded scenario's CRC, the game rebuilds the variant from the scenario (`U` against the real game). Opaque; never changed | `P:JS:749`; `W:HMS` |
| +72 | 9 | quota_count | unk02B2 | **> 256 is an error** (JS:828-829: Reach aborts) | `P:JS:750,828-829`; `W:BLF` |
| +81 | 32 | map id (second copy) | unk02B4 | warn if it differs from the header map id | `P:JS:752` |
| +113 | 1 | built_in | unk02D9 | opaque | `P:JS:754` |
| +114 | 1 | built_from_xml | unk02DA | opaque | `P:JS:755` |
| +115 | 6 x 32 | bounds | boundingBox | float32 BE in the order xmin, xmax, ymin, ymax, zmin, zmax (same order in HMS and BLF) | `P:JS:762-767`; `W:HMS`, `W:BLF` |
| +307 | 32 | max budget | unk02D0 | integer or float: `U`; opaque raw word | `P:JS:768` |
| +339 | 32 | spent budget | unk02D4 | opaque raw word | `P:JS:769` |
| +371 | var | forge label table | forgeLabels | 3.4 | `P:JS:771-827` |

`E_b = E_h + 371` is where the label table begins.

Bounds are the immutable coordinate frame of every position field (3.6, 4.2). Validation at parse: all six bounds finite and `min <= max` per axis. `min > max` or a non-finite value is `FormatError`. `min == max` is accepted with warning `W_ZERO_RANGE_AXIS` (DEC-3.6): that axis reads 0 bits (`P:JS:129-145`: a zero range gives a cell count of 0 and 0 bits, re-read `S`), every slot has raw cell 0 on it and decodes to `min`; `pos_encode` is undefined there, so a new object or a moved axis on it is refused with `E_OUT_OF_BOUNDS`, and untouched objects keep their raw cell.

### 3.4 Forge label table (single language)

Evidence: `P:JS:771-827`; widths `P:RVT localized_string_table.h:131-137` (`offset_bitlength = bitcount(max_buffer - 1)`, `buffer_size_bitlength = bitcount(max_buffer)`, `count_bitlength = bitcount(max_count)`) for (max_count 256, max_buffer 4096) -> 12, 13, 9 bits, which are the widths the JS uses; `W:BLF` `c_single_language_string_table<256,4096,12,13,9>`; `W:HMS`.

| Order | Width | Field | Notes | Tag |
|---|---|---|---|---|
| 1 | 9 | count N | 0..511 in the field, >256 is an error | `P:JS:778`; `W:BLF` (256 strings) |
| 2 | N x (1 + 12) | for each label i: presence bit (1 = present), then a 12-bit byte offset if present | one entry per label (not 12 languages, X12) | `P:JS:779-785`; `P:RVT localized_string_table.h:131-137` |
| 3 (only if N > 0) | 13 | dataLength | uncompressed byte count of the string buffer | `P:JS:787` |
| 4 (only if N > 0) | 1 | isCompressed | | `P:JS:789` |
| 5a (if compressed) | 13 | compSize | **includes** the 4-byte prefix | `P:JS:794`; `P:RVT localized_string_table.cpp:408-452` |
| 5b (if compressed) | 8 x compSize | bytes: u32 BE uncompressed size, then a zlib stream (`78 DA`: zlib header, best compression) | inflated length should equal dataLength; a mismatch is only a warning (JS also only warns; the stream position does not depend on it, because exactly compSize bytes are consumed), a failed inflate is an error | `P:JS:795-806`, `V` for the zlib form on game-variant string tables |
| 5c (if not compressed) | 8 x dataLength | raw buffer bytes | | `P:JS:810-811` |

Bytes are read 8 bits at a time at any bit alignment. If N == 0 nothing follows the 9-bit count (no size field, `P:JS:786`).

String lookup: label i's text is `buffer[offset_i : first NUL at or after offset_i]`; an entry with presence 0 has **no text** (it is not "empty string"). Mjolnir's `text.split('\0')` is wrong whenever an entry is absent or offsets are shared or non-monotonic. The label index stored in an object slot (8 bits) is the **entry index i**. Encoding of the text bytes is `U` (JS uses `String.fromCharCode`, RVT `std::string`); the library decodes UTF-8 with a Latin-1 fallback for display and keeps the raw bytes.

Writer (needed only for `from_plain`, tests, and a future label editor): RVT compresses when the buffer is >= 0x80 bytes with zlib `Z_BEST_COMPRESSION`, writes `compSize + 4` in the size field, then the BE uncompressed size, then the zlib bytes (`P:RVT formats/localized_string_table.cpp:408-452 S` (reader: `:249-282`)); recompressing the 4 compressed string tables found in the 5 distinct real game variants (the fifth has none: its buffer is under the 0x80-byte threshold) with Python's zlib at levels 7 to 9 reproduces the original bytes on zlib 1.2.12 (Python 3.9.6), 1.3.1 (Blender's Python 3.13.13) and 1.2.12 (Homebrew Python 3.14.7) (`V` for what RVT's compressor emits, 0.1 V caveat; `crit_plan/p1_zlib_recompress.py` re-run in the revision pass on Python 3.9.6: 4 of 4 identical at levels 7, 8 and 9, `S`; the other two interpreters are the plan lint's measurement). HMS always writes uncompressed (`W:HMS`, "engine reads both"). **DECISION DEC-3.2:** v1 never edits the label table; it is always emitted as its original bit range. `encode_label_table` exists for `from_plain` and uses uncompressed below 0x80 bytes, zlib level 9 above.

### 3.5 Version 32: 128 extra bits

If `version >= 32`, 128 bits (HMS parses them as a signed 32-bit value, then 16, 16 and 64 bits and keeps them as `mcc_map_id`, a 16-byte map GUID) follow the label table, before slot 0. Evidence `W:HMS` only; BLF has no version branch; the JS prototype only knows 31. Tag `I`. The library keeps the 128 bits raw. Whether they are present is a hypothesis dimension (`guid_present`, 3.10): the value implied by the version is tried first, the other value is tried too, and the end-of-walk check confirms or refutes it.

### 3.6 Slots: 651 records, each starting with a presence bit

`for i in 0..650` (`P:JS:831 S`: `for(i < 0x28B)`), each record begins with a 1-bit **presence** flag (1 = present). An absent slot is exactly that one bit. There is **no terminator** and the loop **never stops at the first absent slot** (`P:JS:615-617`: the constructor returns after the presence bit; `W:HMS`, `W:BLF`). Slot indices are meaningful: the parent link refers to them and the user's Blender objects will be tied to them.

Present-slot record (`P:JS:615-642` and `:235-285`; names in the last column are the JS field names; HMS/BLF agree on order and widths):

| # | Field | Width | Condition | Stored form | JS name | Tag |
|---|---|---|---|---|---|---|
| 1 | present | 1 | always | 1 = present | `presence` | `P:JS:615-617` |
| 2 | flags2 | 2 | | raw; bit 0 is set on every real object, "occupied/used" (`W:HMS`); new objects use 1 | `unk00` | `P:JS:619`; meaning `W:HMS` |
| 3 | folder_absent | 1 | | **1 = none** | | `P:JS:620` |
| 4 | folder | 8 | folder_absent == 0 | u8 | `objectSubcat` | `P:JS:621` |
| 5 | item_absent | 1 | | **1 = none** | | `P:JS:622` |
| 6 | item | 5 | item_absent == 0 | u5 | `objectType` | `P:JS:624` |
| 7 | in_bounds | 1 | | must be 1; **0 aborts** (3.8) | `a` ("can't understand how this is used", JS:293) | `P:JS:293`; OOB `W:HMS` |
| 8 | pos_x | bx | | u(bx) | `position.x` | `P:JS:317` |
| 9 | pos_y | by | | u(by) | | `P:JS:318` |
| 10 | pos_z | bz | | u(bz) | | `P:JS:319` |
| 11 | up_global | 1 | | 1 = up is exactly +Z, no up code | | `P:JS:628` |
| 12 | up_code | 20 | up_global == 0 | u20 cube-face code | `axisAngleAxis` | `P:JS:637`, `:365` |
| 13 | angle | 14 | | u14 | `rawAxisAngleAngle` | `P:JS:639` |
| 14 | parent | 10 | | **stored = parent slot index + 1; 0 = none** (JS: `readBits(10) - 1`; HMS/BLF agree) | `unk2C` | `P:JS:641 S` |
| 15 | shape | 2 | | 0 none, 1 radius only (sphere), 2 cylinder, 3 box | `unk10` | `P:JS:154` |
| 16 | dims | 11 each | shape 1: 1 value (radius); shape 2: 3 values (radius, top, bottom); shape 3: 4 values (width, length, top, bottom) | u11 each | `unk00,04,08,0C` | `P:JS:157-233` |
| 17 | spawn_seq | 8 | | two's complement (HMS `bits_signed(8)`; JS "TODO: make sure signed") | `spawnSequence` | `P:JS:254-257`; signedness `W:HMS` |
| 18 | respawn | 8 | | u8 seconds, 0 = default | `respawnTime` | `P:JS:259` |
| 19 | cached_type | 5 | | u5; selects the extras in 3.8 | `unk13` | `P:JS:260` |
| 20 | label_absent | 1 | | **1 = none** | | `P:JS:261` |
| 21 | label | 8 | label_absent == 0 | entry index into the label table | `forgeLabelIndex` | `P:JS:264` |
| 22 | placement | 8 | | raw byte; see 3.9 | `unk16` | `P:JS:266`; meaning DISPUTED (3.9) |
| 23 | team | 4 | | stored +1: raw 0 = none, raw 1..9 = team 0..8 (8 = neutral) | JS `unk17` ("color?") | `P:JS:267`; meaning `W:HMS`, `W:BLF` |
| 24 | color_absent | 1 | | **1 = none (use team colour)** | | `P:JS:268` |
| 25 | color | 3 | color_absent == 0 | u3 colour 0..7 | JS `team` | `P:JS:269` |
| 26 | extras | see 3.8 | by cached_type | | `unk18`, `unk19` | `P:JS:274-284` (type 19 DISPUTED) |

Axis widths `bx, by, bz` come from the bounds (4.1). The position fields are cell indices in the file's immutable bounds.

Size of a present slot (re-derived `S` from the table above): minimum 128 bits with axes 20/21/19 and folder, item and every other optional field absent; 141 for a typical block (axes 20/21/19, folder and item present, as W1 slot 1 in Appendix C; 144 with axes 21/21/21; 150 with 23/23/23); at most 235 with three 23-bit axes, folder, item, an explicit up code, a box shape, a label, a colour and a 5+5 extra (224 without the label and the colour). 651 x 235 + 256 x 24 = 159,129 bits, so with positions bounded by 23 bits the 229,376-bit capacity can only be exceeded by an unusually large label table; the capacity check is still mandatory.

### 3.7 Quota table and tail

Immediately after slot 650: `quota_count` rows of 24 bits: `minimum_count` u8, `maximum_count` u8, `placed_on_map` u8 (`P:JS:837-845` reads three bytes per row for `i < unk2B2` and names them `unk00..02`; the order min, max, placed is from `W:HMS` and `W:BLF`, confidence 0.85). Row i belongs to the palette entry whose index is i; an object's `folder` **is** the row index (HMS: "matches the quota-table index"). Price, tag id and design-time maximum are not stored for Reach (`W:BLF` comments them out).

`end` = bit position after the last quota row. The remainder of the 0x7000-byte stream is the **tail**: zero in normal files (`W:HMS`: carried verbatim; `I`: probably zero). The library keeps the tail as a raw bit range from `end` to capacity and re-appends it after any edit (shifted with the quota table); if a non-zero tail bit would be pushed past the capacity the export is refused (`E_CAPACITY`).

### 3.8 Extras by cached type, and the disputed points

`cached_type` (5 bits) selects trailing fields (`P:JS:274-284`):

| cached_type | Extra bits | Meaning | Mjolnir view | Evidence |
|---|---|---|---|---|
| 1 | 8 | spare clips (weapons) | `otherInfoA` = value | `P:JS:274-276`, `W:HMS`, `W:BLF` |
| 12, 13, 14 | 5 + 5 | teleporter channel, passability flags | `otherInfoA` = channel, `otherInfoB` = flags (`NoPlayers 1, LandVehicles 2, HeavyVehicles 4, FlyingVehicles 8, Projectiles 16`, `P:ForgeLib/ForgeObject.cs:97-103`) | `P:JS:279-281` |
| **19** | **DISPUTED**, see below | location name index | `otherInfoA` = index | |
| anything else | 0 | | `otherInfoA = otherInfoB = 0` | |

(JS: `unk13 == 1` -> 8 bits; `unk13 <= 0xB` -> nothing; `<= 0xE` -> 5 + 5; `== 0x13` -> 8 bits minus 1; otherwise nothing.)

**Type 19 is DISPUTED (X5).** Two rules, both implemented as hypotheses `type19=plain8` and `type19=flag8`:

| Rule | Bits | Value | Sources |
|---|---|---|---|
| `plain8` | 8, always | stored value minus 1 (stored 0 = none) | `P:JS:282-283`, `W:BLF` (`read_unnamed_index::<255>(8)`, re-read `S`) |
| `flag8` | 1 flag (1 = none), then 8 bits only if the flag is 0 | the index | `W:HMS` (re-read `S`: "1 bool + (8 bits only when the flag is CLEAR)", a set flag leaves the name at 0xFFFF; HMS comment says a bare 8 bits "would desync" every following object) |

Consequences: (a) the reader decides by the walk (3.10); (b) if the template contains no type-19 object both rules decode identically and the result is `type19=undetermined`; (c) **creating or retargeting an object to cached type 19 is refused unless the rule is determined** by a type-19 object in the template (`E_TYPE19_UNDETERMINED`); (d) unchanged type-19 slots are re-emitted from raw ints, which hold the exact bits of whichever rule applies.

Other disputed or conditional points:

- **Out-of-bounds position (`in_bounds == 0`).** JS/Mjolnir read the same three axis widths and nothing extra; HMS reads one more flag bit and, if clear, a 2-bit BSP index; BLF says the widths for such a point come from per-BSP data that is not in the file. **DECISION DEC-3.3:** `in_bounds == 0` aborts the import (when it is the failure of every hypothesis, 3.10 rule 1) with `OutOfBoundsPositionError: slot N has a position outside the map bounds (in-bounds flag = 0); such records need BSP data that is not in the file and cannot be decoded`. HMS says the game clamps objects into the box on its own saves, so these should be rare (`W:HMS`).
- **Axis-bit rounding** at exact cell-count thresholds (4.1): hypotheses (three variants).
- **v32 GUID** (3.5): a hypothesis dimension `guid_present`; the version number only decides which value is tried first (3.10).

### 3.9 The placement byte (slot field 22): the two readings conflict

| Bit | Mask | `W:HMS` (file reading; `PLACE_*` constants, re-read `S`) | Mjolnir in-memory `ForgeObject.Flags` (`P:ForgeLib/ForgeObject.cs:75-84`, `P:forge.py:57-66`) |
|---|---|---|---|
| 0 | 0x01 | hide unless a script requires this type | undefined |
| 1 | 0x02 | shortcut (navigation) | **HideAtStart** |
| 2 | 0x04 | **ASYMMETRIC** | **Symmetric** |
| 3 | 0x08 | **SYMMETRIC** | **Asymmetric** |
| 4 | 0x10 | **NOT placed at start** (inverted: clear = placed at match start) | undefined |
| 5 | 0x20 | unique spawn | GameSpecific |
| 6-7 | 0xC0 | physics: 0 normal, 1 fixed, 3 phased (2 unused) | Normal 0x00, Fixed 0x40, Phased 0xC0 |
| default | | 0x0C ("most common retail value", both symmetries, placed at start, normal physics) | Mjolnir's old export wrote 0xCC for phased objects |

The sources disagree on which bit is "symmetric", which bit means "not placed at start", and the meaning of bit 1. The in-memory struct (live process memory) need not equal the file byte. This conflict was **not** noted in any of the reports; it was found by re-reading HMS's constants against `ForgeObject.cs`.

**DECISION DEC-3.9:**
1. The library exposes the byte raw (`placement`) and a decoded view using the **file reading (HMS)**: `physics` (bits 6-7), `symmetry` (bits 2-3: 0 neither, 1 asymmetric-only, 2 symmetric-only, 3 both), `place_at_start` (bit 4 clear), `game_specific` (bit 5). The Blender UI shows these.
2. Export may change **only the physics bits** (the two readings agree on 6-7). Any change to `symmetry`, `place_at_start` or `game_specific` relative to the baseline view is refused with `E_FLAG_UNVERIFIED`: "Symmetry / Place At Start / Game Specific cannot be changed yet: the placement-flag bit meanings disagree between sources and have not been checked on a real file".
3. A new object's placement byte is `learned example (same folder and item) or 0x0C`, with the physics bits replaced from the Blender property. Both readings treat bits 1 and 4 as 0 = "placed at start", so the default is safe under either. For a new object the baseline view of `symmetry`, `place_at_start` and `game_specific` is that of the learned example (else BOTH, placed at start, not game specific); a Blender value that differs from that baseline is refused with `E_FLAG_UNVERIFIED`, never silently ignored (5.6).
4. `verify_mvar` prints a histogram of placement bytes so that a real file settles the question (for example "0xCC x 412, 0x0C x 100, 0x1C x 3": which of 0x04/0x08/0x10 occur).

### 3.10 Walk acceptance, hypotheses and plausibility

A **hypothesis** is a tuple `(type19_rule, axis_bits_triple, guid_present)`. `guid_present` takes both values; the value implied by the body version (`version >= 32`) is tried first. If only the other value yields an accepted walk it is used, the decode is flagged `guid=contradicts_version` and warning `W_GUID_VERSION_MISMATCH` is issued. The set of hypotheses is built as: `type19_rule` in {`flag8`, `plain8`} x the distinct axis-bit triples produced by the rounding variants of 4.1 (one triple in almost every file) x `guid_present` in {version-implied, other}.

For each hypothesis the **walk** reads: header (3.2), fixed body (3.3), label table (3.4), [GUID], 651 slots, `quota_count` quota rows, and records `end`. A walk is **accepted** iff all of the following hold:

1. **No overrun, no out-of-bounds record:** every read is inside `0x7000 x 8` bits and no present slot has `in_bounds == 0`. (A wrong hypothesis desynchronises the walk and then meets `in_bounds == 0` by chance about half the time, so under one hypothesis an `in_bounds == 0` only *rejects that hypothesis*, with the reason "out of bounds at slot N". If **every** hypothesis is rejected for that reason at the same slot, the library raises `OutOfBoundsPositionError` for that slot; otherwise `DesyncError`.)
2. **Length agreement:** `ceil(end / 8) == L` (class `ceil_end`), or `L == 0x7000` (class `capacity`), or the stored bytes are `00 00 00 00` (class `zero`); for the last two classes rule 3 carries the weight. Anything else rejects the hypothesis.
3. **Hard plausibility checks (any violation rejects the hypothesis):** (a) `quota_count <= 256`; (b) `label_count <= 256`, every present slot's label index is `< label_count` and refers to a present label entry, and a compressed label buffer inflates; (c) every present slot's `folder < quota_count`; (d) `parent_raw <= 651`; (e) every present up code has `face <= 5` (code `< 1,048,572`); (f) all six bounds are finite and `min <= max` on each axis (`min == max` passes, 3.3). The "refers to a present label entry" part of (b) and the whole of (c) have no primary source (`I`; HMS only says the folder "matches the quota-table index"): if they are wrong they would refuse a correct decode of a valid file. They are therefore reported by name as the first-failure reason in `DesyncError.diagnostics`, a hypothesis rejected *only* by one of them is flagged as such, and `verify_mvar --lenient` shows the walk with just those two checks disabled.
4. **Soft checks (warnings; they never reject, they only raise the "suspicion" count printed by `verify_mvar` and used to order otherwise identical candidates):** non-zero bits in the tail or in the pad bits between `end` and `8 x ceil(end/8)`; `u` above 416 in an up code (dead zone; `v = rem % 417` cannot exceed 416); team raw above 9; the inflated label buffer length differing from `dataLength`; quota `placed` differing from the number of present slots per folder (expected equal: HMS recomputes `placed` from the saved slots and round-trips shipped files unchanged, `W:HMS`, indirect, `I`); `minimum > maximum`; a zero-range axis; label text not decodable; folder/item pairs not in the stock table; position cells at the extremes of their range. Rationale: a hard check that is stricter than the real format would make a correct hypothesis fail and block the import, so only checks that the game itself enforces (or that are structurally impossible to violate in a well-formed file) are hard.

**DECISION DEC-3.10 (selection rule):** the rule below is applied to the accepted hypotheses of one `guid_present` value at a time. If the version-implied value has any accepted hypothesis, the other value is ignored (no ambiguity is reported between the two GUID values, because the wrong one passes the end test with the 3.8 % false-pass probability of the critique); only when the version-implied value has none is the other value tried, with `W_GUID_VERSION_MISMATCH`.

- exactly one accepted hypothesis -> use it;
- several accepted and all decode **identically** (same slot tuples, same `end`) -> use the first in preference order `flag8` then `plain8`, and record the undetermined parts (`type19=undetermined`);
- several accepted with **different** decodes -> `AmbiguousLayoutError` listing each hypothesis' `end` and first differing slot (the format critique measured a 3.8 % false-pass rate for the end-of-walk test alone, so this is rare but possible);
- none accepted -> `DesyncError` carrying, per hypothesis, the first failing check and the slot index/bit position where the walk went wrong, and `verify_mvar` prints that table.

`ReadOptions.strict = False` (used only by `verify_mvar --lenient`) lets a walk that fails rule 2 or 3 be *reported* without being used; **no export is ever built from a lenient parse.**

### 3.11 Mapping from a slot to Mjolnir's `ForgeObject` fields

`ForgeObject` is the 76-byte struct of `forge.py:30-56` / `ForgeObject.cs:44-72`. `ObjectRecord` (section 6.4) carries these values to the Blender glue; the glue's `FromForgeObject`/`ToForgeObject` keep their shape but read/write `ObjectRecord`/`ExportObject`.

| ForgeObject field (offset, type) | `ObjectRecord` / `ExportObject` field | Source in the slot | Import conversion | Export rule |
|---|---|---|---|---|
| `show` (0, u16) | present | slot present | 1 | slot present = at least one Blender object claims the slot |
| `itemCategory` (2, u16) | `folder` | folder (8 bits) | absent -> -1 (and `type_id` undefined) | changed only by retarget (two-tier rule 7.4) |
| `itemVariant` (46, u8) | `item` | item (5 bits) | absent -> -1 | same |
| `idExt` (4, u32), `pad1`, `pad2` | none | not in the file | | |
| `position` (8, 3 x f32) | `position` | pos_x, pos_y, pos_z | `(q + 0.5) * (range / 2^bits) + min` per axis | per axis: keep the old cell unless the Blender value moved beyond tolerance (4.2), then `floor((v - min) / cell)`; never clamp |
| `forward` (20, 3 x f32), `up` (32, 3 x f32) | `forward`, `up` | up_global/up_code + angle | **UNVERIFIED** reconstruction (4.6) | unchanged -> raw bits kept; yaw-only on a vertical object -> angle re-encoded (gate); anything else refused (DEC-4.8) |
| `spawnRelativeToMapIndex` (44, u16) | `parent_slot` | parent | `raw - 1`, 0 -> -1 (0xFFFF in the struct) | preserved; cleared if the parent slot is deleted |
| `shape` (64, u8) | `shape` | shape | 0 none, 1 radius-only, 2 cylinder, 3 box (**1 is no longer flattened to 0**) | changed -> dims re-encoded |
| `width` (48), `length` (52), `top` (56), `bottom` (60) f32 | `width`, `length`, `top`, `bottom` | dims | `0 -> 0`, `0x7FF -> 200`, else `(v - 1) * 0.0977517142892 + 0.0488758571446`; unused dims = 0.0 | keep the old code when `dim_encode(value)` equals it (4.3) |
| `spawnSequence` (65, i8) | `spawn_sequence` | spawn_seq | signed 8-bit | changed -> re-encode (range -128..127) |
| `spawnTime` (66, u8) | `spawn_time` | respawn | u8 | changed -> re-encode |
| `cachedType` (67, u8) | `cached_type` | cached_type | u5 | **cannot be changed** on an existing object (`E_CACHED_TYPE_CHANGED`); new objects: learned (7.4) |
| `gtLabelIndex` (68, u16) | `label_index` | label_absent/label | absent -> -1 (0xFFFF in the struct) | must be < label count; not addable (DEC-3.2) |
| `flags` (70, u8) | `placement` + `physics`, `symmetry`, `place_at_start`, `game_specific` | placement byte | decoded with the **file** reading (3.9) | physics only (DEC-3.9) |
| `team` (71, u8) | `team` | team | raw - 1: -1 none, 0..8 | changed -> raw = team + 1 (none cannot be written; `NONE` displays as `NEUTRAL` and an unchanged `NEUTRAL` over a `none` baseline counts as unchanged) |
| `otherInfoA` (72, u8) | `other_a` | extras | clips / channel / location index (type 19: `plain8` -> value - 1, `flag8` -> index or -1) | changed -> re-encode in the field width (8 / 5 bits) |
| `otherInfoB` (73, u8) | `other_b` | extras | passability flags (5 bits) | same |
| `color` (74, u8) | `color` | color_absent/color | absent -> -1 (255 = team colour); 0..7 | `NEUTRAL (8)` cannot be stored in 3 bits -> `E_COLOR_NEUTRAL` |
| (not in the struct) | `flags2` | flags2 | raw | preserved; new = 1 |
| (not in the struct) | `raw`, `raw_bits`, `slot` | the slot's original bit range | identity token (5.5) | |

### 3.12 Worked example

Appendix C defines reference fixture **W1** (3 present objects, 3 labels, tilted object, kill-boundary box, parent link, quota rows) with every section's bit offset, the stored length, both hash flavours and three golden edits. It was built and parsed by two independent scripts written for this spec (`docs/mvar/reference/w1_build.py` and `w1_parse.py` once G0 has committed them), and rebuilt a third time by the format lint pass from the text of this document alone, which reproduced every Appendix C number; G2's builder must reproduce W1 byte for byte.

---------------------------------------------------------------------------------------------------

## 4. Exact codecs and golden test vectors

All code in this section is illustrative Python 3.9 written for this spec (not copied from any source). Constants are facts from the cited sources.

### 4.1 Axis bit counts (how many bits each position coordinate takes)

Evidence: `P:JS:79-150` (`_sub4DC8E0`) re-implemented `S`; baseline `bitcount = 21` is hard-coded at `P:JS:290`; `W:HMS` `compute_axis_bits(21, ...)` is the same algorithm in float32 with a different rounding step. The float32 constants are `0x3C088889 = 0.008333333767950535` and `0x38D1B717 = 9.999999747378752e-05` `S`.

```python
import math, struct
def f32(x): return struct.unpack(">f", struct.pack(">f", x))[0]
MIN_UNIT_16 = 0.00833333333          # JS; the engine constant is f32 0x3C088889
STEP_FLOOR  = 0.0001                 # f32 0x38D1B717

def bits_from_cells(n):              # ceil(log2(n)); 0 for n <= 1.  Equals the JS highest-bit-plus-remainder test (checked `S` for every n in 0..0x800000)
    return 0 if n <= 1 else (n - 1).bit_length()

def axis_bits_ceil(rng, base=21):    # variant "ceil" (JS), double precision
    step = MIN_UNIT_16 / (1 << (base - 16))          # base 21 -> 0.00026041666...
    if step < STEP_FLOOR: return 26                  # never taken with base 21
    step *= 2                                        # 0.000520833...
    n = min(0x800000, math.ceil(rng / step))
    return min(26, bits_from_cells(n))

def axis_bits_trunc(rng, base=21):   # variant "trunc9999" (HMS), float32 arithmetic and +0.9999 then truncate
    step = f32(f32(f32(MIN_UNIT_16) / f32(1 << (base - 16))) * 2.0)
    q = f32(f32(f32(rng) / step) + f32(0.9999))
    return min(26, bits_from_cells(int(min(8388608.0, q))))

ENGINE_UNIT_16 = 0.008333333767950535  # f32 0x3C088889 exactly; relative difference 5.3e-8 from the JS constant

def axis_bits_ceil_f32(rng, base=21):  # variant "ceil_f32": the engine's own float32 constant, float32 arithmetic, then ceil
    step = f32(f32(f32(ENGINE_UNIT_16) / f32(1 << (base - 16))) * 2.0)
    n = min(0x800000, math.ceil(f32(f32(rng) / step)))
    return min(26, bits_from_cells(n))
```

Hypotheses: the range of an axis is computed in two ways (the double difference of the two f32-decoded bounds, and `f32(max - min)`); each is passed to the three variants (`ceil` with the JS double constant, `trunc9999` in float32, and `ceil_f32`, the engine's own float32 constant with `ceil`); the distinct triples are the axis hypotheses. `ceil` and `trunc9999` differ **only** when `range` falls within about 1e-7 (relative) of an exact cell-count power of two of the JS step, `range = 2^k x 0.000520833333` (k = 15 gives 17.0667, k = 20 gives 546.1333): there `ceil` gives k bits and `trunc9999` gives k+1 (`S`: k = 15..22 all show this; k = 23 is capped at 23 for both; 300,000 random extents and 4,077 integer or half-integer ranges produced **0** disagreements). `ceil_f32` differs from `ceil` only within about 5e-8 (relative) of the thresholds of the float32 step, `range = f32(2^k x 0.0005208333604969084)`: there `ceil` and `trunc9999` give k+1 and `ceil_f32` gives k (`S`, revision pass: k = 15..22; k = 23 is 23 for all); 208,999 integer, half-integer and random ranges produced 0 disagreements between any two variants, and at the JS thresholds `ceil_f32` agrees with `ceil`. Which variant the engine uses is `U`; none of this matters unless a bounding box lands on a threshold. With baseline 21 the result is never above 23 bits.

Golden vectors (id `G-AX`):

| Id | Input ranges (x, y, z) | Output bits |
|---|---|---|
| G-AX-1 | 1024, 1024, 1024 | 21, 21, 21 (`W:HMS` worked example; `S`) |
| G-AX-2 | 480, 690, 140 (Forge World box, "about 480 x 690 x 140", `W:HMS`) | 20, 21, 19 (`S`) |
| G-AX-3 | `2^k x (0.00833333333 / 32 x 2)` for k = 15..22 | `ceil`: k; `trunc9999`: k + 1; `ceil_f32`: k |
| G-AX-4 | 34.0 / 34.2 / 0.0 | 16 / 17 / 0 (zero-range axis reads 0 bits; the walker must support it) |
| G-AX-5 | 4369.07 and larger | 23 (cell count capped at 0x800000) |
| G-AX-6 | `f32(2^k x 0.0005208333604969084)` for k = 15..22 (thresholds of the float32 step) | `ceil`: k + 1; `trunc9999`: k + 1; `ceil_f32`: k (`S`) |

### 4.2 Position codec

```python
def pos_cell(bits, mn, mx):          # cell size in world units
    return (mx - mn) / float(1 << bits)

def pos_decode(q, bits, mn, mx):     # cell centre (P:JS:323-329, P:RVT compressed_float.h unsigned, !exact)
    return (q + 0.5) * pos_cell(bits, mn, mx) + mn

def pos_encode(v, bits, mn, mx):     # containing cell; refuse (never clamp) outside [mn, mx)
    if not (mn <= v < mx): raise OutOfBounds(...)
    return min((1 << bits) - 1, int(math.floor((v - mn) / pos_cell(bits, mn, mx))))
```
`bits` may be 0 (a zero-range axis, `mn == mx`, 3.3): then `q = 0`, the decoded value is `mn`, the walker still reads 0 bits, `pos_cell` is 0 and `pos_encode` is undefined (it would raise): a new object or a moved axis on such an axis is refused with `E_OUT_OF_BOUNDS`, and an untouched axis keeps its raw cell.

Why cell-centre decode and floor encode: decode returns the middle of cell q, so `floor` of any value in the cell returns q. The format critique measured that `decode -> float32 -> encode` is **not** the identity when float32 spacing approaches the cell size (for example bounds minimum 3000, range 4000: 16.7 % of cells), which is why raw cells of untouched axes are never recomputed (principle 1).

**Change tolerance (DEC-4.1).** An axis is "unchanged" iff `abs(v_blender - pos_decode(q_old)) <= tol` with
`tol = max(1.0e-3, 0.5 * cell, 2 * ulp32(M))`, `M = max(abs(mn), abs(mx))`, `ulp32(M) = 2^(floor(log2(M)) - 23)`.
For all plausible Reach boxes (range below about 4,400, |coordinate| below 8,192) this is a flat 1.0e-3 world units (about 2 to 4 cells; the cells of the 20/21/19-bit W1 axes are 0.00046, 0.00033 and 0.00027). Blender's `Object.location` is float32 (readback `400.0001220703125` `S` from the critique's X1 run), error about 3e-5 at 500. A moved axis is re-encoded alone: the other two axes keep their raw cells.

Golden vectors (id `G-POS`):

| Id | Bounds, bits | q | Value |
|---|---|---|---|
| G-POS-1 | 0..1024, 21 | 0 / 1 / 2,097,151 | 0.000244140625 / 0.000732421875 / 1023.999755859375 (`S`) |
| G-POS-2 | -240..240, 20 (W1 x axis) | 524,288 | 0.0002288818359375 (cell 0.000457763671875) |
| G-POS-3 | same | encode of 1.0002288818359375 | 526,473 (decodes to 1.0004425048828125) |
| G-POS-4 | same | encode of 240.0 | refused (v == max) |
| G-POS-5 | same | blender value `pos_decode(524288) + 0.0004` | unchanged (inside the 1e-3 tolerance) -> keep 524,288 (a plain `pos_encode` would give 524,289) |

### 4.3 Shape dimension codec (11 bits, range 0 to 200)

`P:JS:157-285` `S`; equals RVT's `decode_compressed_float(raw, 11, 0, 200, unsigned, guarantee_exact_bounds = true)` `P:RVT formats/compressed_float.h:11-33`.

```python
def dim_decode(v):                   # v in 0..2047
    if v == 0: return 0.0
    if v == 0x7FF: return 200.0
    return (v - 1) * 0.0977517142892 + 0.0488758571446     # == (v - 0.5) * 200/2046

def dim_encode(x):                   # refuse x < 0 or x > 200
    if x == 0.0: return 0
    if x == 200.0: return 0x7FF
    return max(1, min(2046, int(math.floor(x * 2046.0 / 200.0 + 1.0))))   # RVT: trunc((x - min)/interval + 1), interval 200/2046
```
`dim_encode(f32(dim_decode(v))) == v` for all 2048 codes (checked `S`; this also refutes the earlier claim that a naive re-encoder fails on 148 codes, X13). Because the interval of values mapping to code v is centred on `dim_decode(v)`, the glue compares `dim_encode(value)` with the old code: equal -> unchanged; no separate tolerance is needed.

Golden vectors (id `G-SH`): `dim_decode(0) = 0.0`; `dim_decode(1) = 0.0488758571446`; `dim_decode(2) = 0.1466275714338`; `dim_decode(1024) = 100.04887957499619`; `dim_decode(2046) = 199.9511315785586`; `dim_decode(0x7FF) = 200.0`. Encode: `0.0 -> 0`; `0.04 -> 1`; `10.0 -> 103`; `100.0 -> 1024`; `199.97 -> 2046`; `200.0 -> 0x7FF`; `200.01` and `-0.01` refused.

Dimension roles: shape 1 -> `width` = radius; shape 2 -> `width` = radius, `top`, `bottom` (`length` unused); shape 3 -> `width`, `length`, `top`, `bottom`. Unused dims are reported as 0.0 and ignored on export.

### 4.4 Angle codec (14 bits)

```python
ANGLE_STEP = 2 * math.pi / 16384                   # 0.00038349519697141
def angle_decode(raw):  return (raw + 0.5) * ANGLE_STEP - math.pi
# JS form: raw * 0.0003834952 - 3.1415927 + 0.0001917476  (P:JS:459); max difference 4.64e-8 rad (S)
def angle_encode(theta):                           # theta normalised to [-pi, pi]
    return max(0, min(16383, int(math.floor((theta + math.pi) / ANGLE_STEP))))
```
Golden (id `G-ANG`; compare with tolerance 1e-6 because the two forms differ by up to 4.6e-8): exact form `angle_decode(0) = -3.1414009059913073`, `angle_decode(8192) = 0.00019174759848583633`, `angle_decode(16383) = 3.1414009059913077`; JS-constant form `-3.1414009523999997`, `0.00019172599999998916`, `3.1414009091999997`; `angle_encode(0.0) = 8192`; `angle_encode(pi/2) = 12288`; `angle_encode(-pi/2) = 4096`; `angle_encode(pi) = 16383`; `angle_encode(-pi) = 0`. Raw 0 and raw 16383 are about 2 pi apart minus one step: compare angles as vectors, never as raw numbers, when deciding "unchanged" (4.9).

### 4.5 Up axis: 20-bit cube-face code (decode only in v1)

Evidence: `P:JS:331-454` (`loadAxisAngleAxis`); the constants-table row for 20 bits is `[0x2AAAA, 0x1A1]` (line 357), equal to the closed form `STRIDE = floor(2^bits / 6) = 174762` and `N = isqrt(STRIDE) - 1 = 417`; this holds for every JS table row of 6 to 22 bits (17 of 17 rows, re-checked `S`), whereas `N^2 <= STRIDE` alone would allow 418 and is NOT the rule. Rows for 23 to 28 bits in the JS table look corrupt (`upstream-mvar-branch.md` 8) but only the 20-bit row is used.

```python
STRIDE, N = 174762, 417
def up_decode(code):                               # code in 0 .. 2^20-1
    face = code // STRIDE
    if face > 5: raise DecodeError("up code %d: face %d" % (code, face))   # codes 1,048,572 .. 1,048,575
    rem = code - face * STRIDE
    u, v = rem // N, rem % N                       # rem < 174,762 allows u up to 419 (dead zone: u above 416; v = rem % 417 cannot exceed 416)
    cu, cv = (2*u + 1) / 416.0 - 1.0, (2*v + 1) / 416.0 - 1.0
    vec = {0:(1,cu,cv), 1:(cu,1,cv), 2:(cu,cv,1), 3:(-1,cu,cv), 4:(cu,-1,cv), 5:(cu,cv,-1)}[face]
    return normalise(vec)
```
(The JS has a special case `if 2u == 415: c = 0` that can never fire because `2u` is even.)

Properties checked `S` (critique `upaxis.py`, re-run): no code decodes to exactly +Z; u or v equal to 416 give a coordinate of magnitude 1.0024 (4,998 codes, 0.479 %), which re-encode (by the dominant-axis inverse) to a **different face**; 5,238 dead codes lie in valid faces; codes 1,048,572 to 1,048,575 are invalid. Hence the raw code and the separate 1-bit `up_global` flag are the stored truth (principle 1) and **there is no up-vector encoder in v1** (DEC-4.8).

Golden (id `G-UP`; vectors rounded to 7 places, tolerance 1e-6):

| Code | face, u, v | Vector |
|---|---|---|
| 0 | 0, 0, 0 | (0.5782766, -0.5768865, -0.5768865) |
| 416 | 0, 0, 416 | (0.5773492, -0.5759613, 0.5787370) |
| 173888 | 0, 416, 416 | (0.5764261, 0.5778118, 0.5778118) |
| 174762 | 1, 0, 0 | (-0.5768865, 0.5782766, -0.5768865) |
| 436468 | 2, 208, 208 | (0.0024038, 0.0024038, 0.9999942) |
| 436050 | 2, 207, 207 | (-0.0024038, -0.0024038, 0.9999942) |
| 1047698 | 5, 416, 416 | (0.5778118, 0.5778118, -0.5764261) |
| 1048571 | 5, 419, 38 | (0.6190499, -0.4961180, -0.6088056) (dead zone: warning) |
| 1048572 | | `DecodeError` |

### 4.6 Orientation reconstruction: UNVERIFIED (display only)

What is known: a slot stores either "up is +Z" (1 bit) or a 20-bit up code, plus a 14-bit angle. `P:JS:456-565` (`loadAxisAngleAngle`) turns them into a forward vector by (i) computing a reference vector perpendicular to up (a helper `_sub10A8A0`, present twice in the file in two slightly different forms, lines 40-77 and 466-501), (ii) rotating it about up by the decoded angle with Rodrigues' formula. The author marks the port "wrong digits and sign" (JS comments). Checked `S` by transcribing the inline helper of lines 466-501: its result is **not** perpendicular to up for 19,853 of 20,000 random unit vectors (largest |up . ref| = 0.706; for up = +Z it returns (1, 0, 0), for +X (0, 0, -1), for +Y (0, 0, 1)); the Rodrigues routine below it (lines 535-563) has an operator-precedence slip (`(a.x*b.y) - (b.x*a.y) * cy`) and uses `b.z` where the `k (k . v)(1 - cos)` term is expected; and the caller copies only `x` and `z` of the helper's result (lines 503-504). Mjolnir's Python port adds further aliasing errors (`upstream-mvar-branch.md` 8). So **the true reference-vector function is unknown.**

What the library does (DEC-4.6):

- Vertical (`up_global = 1`): `up = (0, 0, 1)`, `forward = (cos t, sin t, 0)` with `t = angle_decode(raw)`. Derived by hand from the JS helper for up = +Z (it yields reference (1, 0, 0), `S`) and consistent with `W:HMS` ("Z-up, forward +X, no axis remap") and the upstream tip. Counter-clockwise sense is `I`. Tag: `I`.
- Tilted (explicit up code): `up = up_decode(code)`; `ref = normalise(X - (X . up) up)` (Gram-Schmidt of +X against up; if `abs(up.x) > 0.99999` use +Y), `forward = ref cos t + (up x ref) sin t`. This is continuous with the vertical case and is **display-only**; it is a guess (tag `U`).
- The Blender glue builds `matrix_world` with columns `(right = forward x up, forward, up, position)` exactly as `forge.py:888-915` does. Whether the models in `Halo Reach.blend` are authored with the game's forward on local +Y is a property of the existing add-on and is unchanged.

Consequence: an imported tilted object may look wrongly rotated in Blender if the guess is wrong. It cannot be *exported* wrongly, because an object whose orientation did not change keeps its raw bits.

### 4.7 Yaw encode (the only orientation write, gated)

Given Blender `forward`, `up` of an object whose `up` equals +Z within 1e-4 rad: `t = atan2(forward.y, forward.x)`, `raw = angle_encode(t)`, `up_global = 1`. Everything depends on the `I` convention of 4.6; hence the opt-in gate (DEC-4.8, 5.6). Golden: W1 slot 1 has `up_global = 1, raw = 8192` -> `t = 0.00019174759848583633` rad, forward = (cos t, sin t, 0) = (1.0, 0.000192, 0). An unrotated Blender object has forward (0, 1, 0) (local +Y, 8.4), hence `t = pi/2` and raw 12288; raw 8192 needs forward +X, i.e. `rotation_euler.z = -pi/2` (`S`, revision pass; Appendix C.3 E2).

### 4.8 Decisions on orientation

**DEC-4.8:** (1) An existing object whose Blender forward and up are within `ANG_TOL = 1.0e-4` rad of the baseline view keeps its raw `up_global`, `up_code` and `angle`. (2) A changed or new orientation is written only if `up` is +Z within 1e-4 rad (pure yaw), and only if `ForgeSceneProps.allowUnverifiedRotation` is true; otherwise `E_ROTATION_GATED`. (3) A changed or new orientation with a tilted `up` is refused always (`E_TILT_UNSUPPORTED`): v1 has no verified reference-vector function and no up-vector encoder. (4) Mirrored transforms (negative determinant of the 3x3) are refused (`E_MIRRORED`). (5) Scale on the Blender object is ignored (vectors are normalised). (6) A position, forward or up that is non-finite, or a forward or up of length below 1e-6, is refused with `E_TRANSFORM_INVALID` before any codec call (`angle_encode(nan)` raises `ValueError` and `angle_encode(inf)` `OverflowError`, `S`).

### 4.9 Change detection summary (tolerances)

| Quantity | Unchanged iff | Constant |
|---|---|---|
| position axis | `abs(v - decode(q_old)) <= tol` (4.2) | `POS_TOL = max(1e-3, 0.5 cell, 2 ulp32)` |
| forward, up | angle between each new vector and its baseline `<= ANG_TOL` | `ANG_TOL = 1.0e-4` rad (below half an angle step 1.9e-4 and the up-code cell 4.8e-3) |
| shape dim | `dim_encode(value) == old code` | none |
| spawn sequence / spawn time / other_a / other_b | integer equality | exact |
| team | `team == baseline` or (`baseline == -1` and `team == 8`) | |
| color | `color == baseline` (`-1` baseline equals Blender `TEAM_COLOR`) | |
| label | index equality | |
| physics | equality of the decoded 2-bit value (2 counts as `normal` for the UI) | |

### 4.10 Golden vector index (all pure functions; stored in `tests/golden/codec_vectors.json`)

`G-AX-1..6`, `G-POS-1..5`, `G-SH` (6 decode + 6 encode + 2 refusals), `G-ANG` (3 decode + 5 encode), `G-UP` (8 decode + 1 error), `G-ID-1`: Tempest `0x4708` = folder 71 (0x47), item 8, internal `wall_coliseum`, display "Wall, Coliseum" (`P:JS:571-596` comment and `Addon/objects.py` agree `S`); `G-ID-2`: `Block, 1x1` = `0x4600` on Forge World, `0x4300` on Tempest, `0x3900` on Battle Canyon (`S` from `stock_objects_per_map_with_model_flag.json`); `G-ID-3`: Forge World `0x3D00` = Kill Boundary, `0x3C00` = Safe Boundary, `0x9000` = Location Name; `G-SZ`: plain file 29,481 = 0x7329, `_eof` offset 0x7318, `mvar` chunk 0x7028, stream at file offset 0x314, capacity 229,376 bits; `G-HASH`: the five digests of 2.7; `G-REAL`: the five distinct real game variants (all 21,289 bytes; header lengths 1,535 / 1,183 / 2,287 / 2,271 / 2,575 bits starting at payload bit 68; `L` = 4,648 / 3,779 / 7,288 / 2,006 / 3,467; stored SHA-1 `eda354ab...`, `dde9b021...`, `85e9acf0...`, `1af297bf...`, `d7d035eb...`; `salted_be32` matches and `plain_le32` does not `S`); `W1`: Appendix C.

---------------------------------------------------------------------------------------------------

## 5. The lossless round-trip design

### 5.1 Data model (Python 3.9, no `slots=True`, no `match`, no `X | Y` at runtime)

(`Chunk` in the code sketches is the "block" of the prose.)

```python
class BitString:                         # immutable bit range, MSB-first, last byte zero padded
    data: bytes ; nbits: int
    def get(self, start, n) -> int ; def slice(self, start, end) -> "BitString" ; def __eq__ ...

class Chunk:                             # a container block
    sig: str ; version: int ; flags: int
    raw: bytes                           # the exact original bytes of the block (for _cmp: the logical, inflated block)
    cmp: Optional[CmpWrapper]            # (type, usize, wrapper_bytes) when the block came from a _cmp wrapper
    dirty: bool

class BlfFile:                           # generic: any tiling block list (mpvr, mvar, unknown)
    original: bytes ; chunks: List[Chunk] ; shape: str          # 'plain4', 'plain4+fsm', 'cmp4', ...
    flavour: Optional[HashFlavour]       # detected per payload block
    eof_endian: str ; trailer: List[Chunk]

class UgcHeader:  raw: BitString (bits [0, E_h)) ; fields: parsed view (ints, strings) ; end_bit: int
class BodyFixed:  version, checksum, palette_crc, quota_count, map_id2, built_in, built_from_xml : int
                  bounds_raw: Tuple[int, ...] (6 x u32) ; max_budget, spent_budget : int ; raw: BitString
class LabelTable: count ; entries: List[Optional[int]] (offset or None) ; data_length ; compressed ; raw: BitString ; buffer: bytes ; comp_bytes: Optional[bytes]
class Quota:      minimum: int ; maximum: int ; placed: int

class Slot:                              # one of 651
    index: int ; present: bool
    # raw integer fields; None means "absent bit set"
    flags2:int ; folder:Optional[int] ; item:Optional[int] ; in_bounds:int
    pos: List[int]                       # 3 raw cells
    up_global: int ; up_code: Optional[int] ; angle: int ; parent_raw: int
    shape: int ; dims: List[int] ; spawn_seq: int ; respawn: int ; cached_type: int
    label: Optional[int] ; placement: int ; team_raw: int ; color: Optional[int]
    extra: List[int]                     # fields by cached type; for type 19 under flag8: [flag, index_or_0]
    raw: Optional[BitString]             # original bit range of this slot (None for slots created in memory)
    baseline: Optional[tuple]            # frozen copy of all raw ints at parse time
    dirty: set                           # names of fields changed since parse
    def bit_length(self, rule, axes) -> int ; def pack(self, writer, rule, axes) -> None

class MapVariant:
    blf: BlfFile ; header: UgcHeader ; fixed: BodyFixed ; labels: LabelTable ; guid: Optional[BitString]
    slots: List[Slot] (651) ; quotas: List[Quota] ; tail: BitString
    hypothesis: Hypothesis ; length_class: str ; end_bit: int ; flavour: HashFlavour
```

Invariant I1: for every slot, `Slot.pack()` of the parsed (unchanged) raw ints produces exactly `Slot.raw`. The reader asserts this for all 651 slots at parse time (a mismatch is a library bug, `InternalError`); `verify_mvar` reports "slot repack identity: 651/651". Invariant I2: after any patched or forced serialisation, parsing the produced bytes with the same hypothesis yields the planned model (5.4 step 9); a violation is also an `InternalError`, raised before anything is written.

### 5.2 Three output modes

| Mode | Trigger | Result | Test |
|---|---|---|---|
| **Passthrough** | model clean (no dirty slot, quota, or block) and `force=False` | the original bytes, including `_cmp` wrapper bytes, `_fsm`, unknown blocks and the unknown tail | T1 (real files), T2: `to_bytes() == input` |
| **Patched** | at least one dirty part | stream rebuilt from the model (clean slots from `Slot.raw`, dirty slots repacked, header/fixed/labels/GUID/tail from their raw bit ranges), then L, hash by the template's flavour; all other blocks verbatim (plain4); `_cmp` expanded (W_CMP_EXPANDED) | T2 single-edit bit-diff tests, G5 |
| **Forced re-encode** | `force=True` (diagnostic; also the export option "Force full re-encode") | every part rendered from the model: block sizes, embedded fileLength, L, hash, `_eof`, chdr fileLength recomputed (2.11); slots repacked from raw ints even if clean | T1: `BlfFile` forced rebuild == input for the 8 real files; T2: `MapVariant.to_bytes(force=True) == input` for every fixture of shape `plain4` / `plain4+fsm`; for the `cmp4` shapes the expanded golden file (2.11, DEC-2.6) |

For a clean model `Patched` is never entered. A forced re-encode of an unedited model equals the input for a well-formed file; if it does not, the reader reports exactly which part differs (`verify_mvar` rung "forced re-encode identical").

The label table is a special case: it is emitted from its raw bit range in all modes (DEC-3.2). Whether `encode_label_table(decode(raw))` reproduces the raw bits is **reported** (`label re-encode identical: yes/no`) because it depends on the zlib implementation and Bungie's compressor settings; `from_plain` stores `comp_hex` so a JSON round trip is exact regardless.

### 5.3 Supported edits

Every edit operates on raw integer fields. "Gate" refers to the scene option `allowUnverifiedRotation` (DEC-4.8).

| Edit | Supported | How | Length effect | Gate |
|---|---|---|---|---|
| Translate an object | yes | re-encode only the axes that moved beyond `POS_TOL` (4.2); all other fields untouched | none | no |
| Yaw of a vertical object | yes | `up_global = 1`, `angle = angle_encode(t)` (4.7) | none | **yes** |
| Tilted object made vertical | yes | sets `up_global = 1`, drops the 20-bit code, re-encodes the angle | -20 bits | **yes** |
| Any tilted result | **refused** | `E_TILT_UNSUPPORTED` | | n/a |
| Change type (palette retarget) | yes, restricted | new folder/item must satisfy 7.4; the new type's learned `cached_type` must equal the old one (else `E_RETARGET_CLASS`); quota rows adjusted | none | no |
| Change label | yes | index of an existing label (< count, entry present); `none` <-> index | +/- 8 bits | no |
| Change team / colour | yes | team: raw = team + 1; colour: `none` <-> 0..7 (8 refused) | colour: +/- 3 bits | no |
| Shape kind or dimensions | yes | shape code, dims re-encoded only if `dim_encode` differs | +/- 11 bits per dim | no |
| Spawn sequence, spawn time | yes | 8 bits each | none | no |
| Physics (bits 6-7 of the placement byte) | yes | | none | no |
| Symmetry, place-at-start, game-specific | **refused** unless unchanged | `E_FLAG_UNVERIFIED` (3.9) | | n/a |
| `other_a` / `other_b` (clips, channel, passability, location) | yes | field widths by cached type; type 19 only if the rule is determined | none | no |
| `cached_type` of an existing object | **refused** | `E_CACHED_TYPE_CHANGED` | | n/a |
| Add an object | yes | 5.6 | + slot size - 1 bit | **yes** (orientation is written) |
| Delete an object | yes | slot becomes absent (1 bit), quota `placed - 1`, children's parent link cleared | - (slot size - 1) | no |
| Edit the parent link | **not exposed**; only cleared by deleting the parent | | | |
| Add or edit labels | no (DEC-3.2) | | | |
| Header text, authors, timestamps, `chdr` | no (DEC-3.1) | the raw header range is re-emitted | | |
| Bounds, palette CRC, quota min/max, budget words, checksum, flags2 of existing objects | **never written** | | | |

### 5.4 What each edit must update, in order

1. **Slot fields** of the edited slots (raw ints), marking `dirty`.
2. **Parent links:** for each deleted slot `d`, every present slot with `parent_raw - 1 == d` gets `parent_raw = 0` (dirty; warning `W_PARENT_CLEARED`).
3. **Quota rows (delta, not recompute; DEC-5.4):** for each folder `f`: `placed[f] = old_placed[f] + added_f - removed_f + retarget_in_f - retarget_out_f`. Rules: result must be in 0..255; if the change moves `placed` above `maximum` it is refused (`E_QUOTA`); if it moves `placed` below `minimum` it is refused (`E_QUOTA_MIN`); a pre-existing violation is not made worse and is not an error. `minimum` and `maximum` are never rewritten, with one opt-in exception: `ExportOptions.raise_quota_max` (D11, 7.5) raises `maximum` to the new `placed` instead of refusing. Rationale: whether scenario-default objects are counted in `placed` is unknown (`U`), so an absolute recount could be wrong where a delta cannot. (`W:HMS` recomputes `placed` from the saved slots and claims its gates re-encode shipped files unchanged; that is indirect evidence, `I`, that `placed` equals the number of present slots of the folder, and the delta rule is kept anyway as the conservative choice.) `verify_mvar` prints the per-folder comparison between `placed` and the number of present slots so a real file shows which holds.
4. **Serialise the stream:** header raw bits, fixed raw bits, label raw bits, [GUID raw bits], 651 slots (`present = 0` -> the single bit 0), quota rows (24 bits each), tail raw bits. Total bits `T`.
5. **Capacity:** `end = bits through the last quota row`; require `end <= 229,376` and `T <= 229,376` else `E_CAPACITY` ("needs N bits, capacity 229,376").
6. **L:** class `ceil_end` -> `L = ceil(end / 8)`; class `capacity` -> keep 0x7000; class `zero` -> keep `00 00 00 00`. Written in the template's byte order.
7. **Embedded fileLength:** recompute only if the total file length changed (never for plain4/plain4+fsm; yes after `_cmp` expansion).
8. **Hash:** by the template's flavour over `stream[0:L]` (2.7).
9. **Verify:** re-parse the produced bytes with the same hypothesis; the decoded views of every untouched slot must equal the template's, edited slots must decode to what was requested (within quantisation), quota rows must equal the plan.

### 5.5 Slot identity and the identity token

A slot is identified by its index (0..650), which never changes for an object in v1 (objects keep their slots; new objects take free slots). Each imported Blender object stores:

- `mj_slot` (int): the slot index;
- `mj_raw` (bytes) and `mj_raw_bits` (int): the **identity token**, the slot's original bit range. `ObjectRecord.raw/raw_bits` carry it;
- `mj_parent_slot` (int, -1 none): the original parent link (informational; the library holds the truth);
- `mj_name` (str): the Blender object name at import.

Export matching (performed by the library, section 6.4):

1. A claimant is **valid** iff its slot is present in the template and its token equals the template slot's bit range. Invalid claimants (token mismatch: copied from another file or a re-imported map; slot absent in the template) are **new objects** and produce `W_TOKEN_MISMATCH`.
2. If several valid claimants share a slot (a Blender duplicate inherits the custom properties), keep the one with `name == mj_name`; if none or several, the one closest to the baseline pose; if still tied, the smallest name. The others are new. The diff report says which was kept.
3. A slot present in the template, listed in `imported_slots`, and claimed by nobody is **deleted**.
4. A slot present in the template but **not** in `imported_slots` (its import failed) is kept untouched and reported (`W_SLOT_NOT_IMPORTED`). Deletion is only defined for slots that were successfully imported.

### 5.6 Adding an object

Order of new objects: sorted by Blender name (deterministic output). Each takes the **lowest absent slot index**; if there is none, or the occupied count would exceed 650, `E_TOO_MANY`/`E_NO_FREE_SLOT`. Field defaults for a new slot:

| Field | Value |
|---|---|
| `flags2` | 1 (`W:HMS`: new objects use 1) |
| `folder`, `item` | from the resolved type (7.4); both present |
| `in_bounds` | 1 (position outside the bounds is refused) |
| position | encoded per axis (4.2) |
| orientation | pure yaw only: `up_global = 1`, angle from 4.7. **Needs the gate** (DEC-5.6): any orientation that is *written* is unverified, so adding objects requires `allowUnverifiedRotation`; moving existing objects does not |
| `parent_raw` | 0 |
| shape, dims | from the Blender properties (default none) |
| `spawn_seq`, `respawn` | from the properties (defaults 0) |
| `cached_type` | learned (7.4) or the assumed-0 group rule, else `E_CACHED_TYPE_UNKNOWN` |
| `label` | from the property if set, else absent |
| `placement` | learned example for the same (folder, item) -> else `0x0C`; then the physics bits replaced by the property |
| `team_raw` | learned example's -> else `9` (neutral) |
| `color` | learned example's -> else absent (team colour) |
| extras | from `other_a/other_b` by cached type; type 19 only if the rule is determined |

**New-object property precedence.** For a new object the *baseline view* is the learned example's (else the defaults: symmetry BOTH, place at start, not game specific, team NEUTRAL, colour Team). `team`, `color` and `physics` from the Blender properties are written when they differ from that baseline; `symmetry`, `place_at_start` and `game_specific` that differ from it are refused with `E_FLAG_UNVERIFIED` (3.9), never silently dropped or overridden by the learned example. An unchanged property yields exactly the learned bytes.

**DEC-5.6:** requiring the gate for new objects is deliberate: the unverified-orientation caveat applies to every orientation the tool writes from scratch. The ladder rung "add one block" (9.5) tells the user to tick it.

### 5.7 Deleting an object

The slot's record is replaced by the single bit 0. The stream shortens by `slot_bits - 1`; every later bit shifts; `end`, L, hash change; the quota row of the deleted object's folder loses 1 (7.5 minimum rule). `raw` of the deleted slot is kept only for the diff report.

### 5.8 What is NOT safely updatable, and the messages shown

| Item | Why | Message (exact text printed in the export report) |
|---|---|---|
| Spent budget and maximum budget words | prices live in the scenario tag, not in the file; `W:HMS` claims the game restores the budget and recomputes spent on load (`I`) | `Budget was not recalculated: item prices are not stored in the map variant, so the spent-budget value was copied unchanged. Open the map in Forge and check the budget meter before playing.` |
| Palette CRC, quota min/max | owned by the scenario | `Edits were written against the palette recorded in the file (CRC 0x%08X). If MCC rebuilds the variant from the scenario, changes may be lost (unverified).` |
| Scenario-default objects | how they occupy slots is `U` (`critique-format-correctness.md` D14) | `Objects that came with the map are treated like any other object; deleting them is unverified.` |
| Header and `chdr` metadata | not edited in v1 | none |
| `_fsm` | stale-signature risk | `W_FSM_STALE` text in 2.9 |
| MCC acceptance | untestable here | `This tool has never been checked against a real MCC load. Follow the test ladder in the documentation (NOTES.md) before relying on the output.` |

### 5.9 Dirty tracking and the bit-diff contract (used by the tests)

`MapVariant.spans()` returns an ordered list of `(name, start_bit, end_bit)` for: header, each fixed field, label table, GUID, each slot (and, via `Slot.field_spans()`, each field of a present slot), each quota row, tail. For two streams `A` (input) and `B` (output) the helper `bitdiff(A, B, spans_A, spans_B)` must satisfy:

- **Same-length edit (translate, yaw, spawn fields, team, physics, ...):** the XOR of `A` and `B` is non-zero only inside the spans of the edited fields of the edited slots, the changed quota rows (if any), the 4 L bytes (never, if L is unchanged), and the 20 hash bytes.
- **Length-changing edit (add, delete, shape, label, colour):** bits before the first edited slot are identical; from the end of the edit, `B` equals `A` shifted by the length delta, except the changed quota rows; the final bits equal `A`'s tail shifted.
- In all cases: the 12-byte `mvar` header, `_blf`, `chdr`, `_eof`, and the 4 pad bytes are unchanged (plain4).

W1's golden edits (Appendix C) fix concrete expected results: E1 changes only the 20 x-bits of slot 1 plus the hash (end bit and L unchanged); E2 adds 140 bits (end 4,970 -> 5,110, L 622 -> 639) and changes quota row 70; E3 removes 192 bits (end 4,778, L 598) and changes quota row 61.

### 5.10 `export_map_variant()` as one ordered algorithm (G5)

1. **Parse** `template` strictly into a model `M` (hypothesis walk, 3.10). Failure -> `ok = False` with `E_TEMPLATE_UNREADABLE`.
2. **Global checks:** `map_id` in the stock table (`E_MAP_UNKNOWN`); container shape supported for modification (`E_CONTAINER_SHAPE`, only checked if something will change).
3. **Field validation** of every `ExportObject`: first non-finite or zero-length position, forward and up (`E_TRANSFORM_INVALID`, before any codec call); then ranges and enums (`E_SHAPE_RANGE`, `E_SPAWN_RANGE`, `E_TEAM_RANGE`, `E_COLOR_NEUTRAL`, `E_LABEL_RANGE`, `E_OTHER_RANGE`).
4. **Identity matching** (5.5): valid claimants per slot; duplicates and token mismatches become new objects.
5. **Deletions:** slots in `imported_slots` (all present slots when `None`) with no valid claimant; slots not in `imported_slots` stay untouched (`W_SLOT_NOT_IMPORTED`).
6. **Per claimed slot:** compute the baseline views from `M`, compare each field with its tolerance (4.9); build the edit set; apply the type rule (7.4), the orientation rules (4.8), the flag rule (3.9), `cached_type` immutability, position bounds (`E_OUT_OF_BOUNDS`).
7. **New objects:** sorted by name, lowest free slots, defaults (5.6), tier-2 type rule, learned cached type, orientation gate, position bounds; `E_NO_FREE_SLOT`. Then the occupied count after all edits is compared with `max_objects`: above it is `E_TOO_MANY`, which also refuses an unchanged template that already exceeds the limit (6.4, 7.3).
8. **Quota deltas** (5.4) and their checks (7.5); parent clearing for deleted slots; then compute the encoded bit length of the planned stream without writing it and add `E_CAPACITY` to the error list if it exceeds 229,376, so that a capacity problem is reported together with every other error.
9. **Stop here if any error was collected:** return `ok = False`, `data = None`, the full issue list and a best-effort diff.
10. **Apply** the edit set to a copy of `M` (slots become dirty); if nothing is dirty and `force_reencode` is false, the result is the template bytes (passthrough, diff all `kept`). `fsm_policy = DROP` on a template that carries `_fsm` counts as a modification: the result is the shape without `_fsm`, not the template bytes.
11. **Serialise** (5.4 steps 4 to 8; the capacity check was already made in step 8); `_cmp` expansion and `_fsm` policy (2.8, 2.9).
12. **Verify (I2):** parse the produced bytes with the same hypothesis; every untouched slot's views equal the template's, edited slots decode to the requested values within quantisation, quota rows equal the plan. A failure raises `InternalError` (a bug, never a user error) and nothing is returned for writing.
13. **Report:** `DiffEntry` list (`kept`, `moved` when only position axes changed, `edited`, `retargeted`, `added`, `removed`, `not_imported`), warnings, `I_` notes of 5.8, `stats`.

---------------------------------------------------------------------------------------------------

## 6. Library API: `mvarlib`

Location: `~/Documents/Halo_MCC/mjolnir-forge-editor/source/Addon/mvarlib/`. Pure Python, standard library only (`struct`, `zlib`, `hashlib`, `math`, `json`, `os`, `io`, `dataclasses`, `typing`), **no `bpy`**, no absolute imports of its own package (relative imports only, so it works as `mvarlib` from the tools and as `mjolnir_forge.mvarlib` inside Blender).

### 6.1 Module layout

```
Addon/mvarlib/
  __init__.py        re-exports the frozen API of api.py, errors, __version__ = "1.0.0"
  api.py             FROZEN AT G0 and COMPLETE: dataclasses (MapInfo, ObjectRecord, ExportObject, ...), options, the error classes re-exported from errors.py, the two entry points as lazy delegations to entry.py, five data/path helpers delegating to tables.py and io.py
  errors.py          exception hierarchy (6.2); frozen with api.py; imports nothing from the package
  entry.py           the real bodies behind api.py: load_map_variant() (G3), export_map_variant() (G5); created in G0 with bodies that raise NotImplementedError("G3") / ("G5")
  bitio.py           BitReader, BitWriter, BitString (promoted from docs/mvar/reference/bitio_prototype.py; the RVT-port oracles move to tests)
  hashing.py         SALT34, recipes, HashFlavour, detect_flavour(), compute()
  blf.py             PayloadSpec registry, Chunk, BlfFile, parse(), to_bytes(force)  (promoted from docs/mvar/reference/blf_container.py)
  ugc_header.py      UgcHeader decode/encode (bit form), chdr parse/build (byte form)
  codecs.py          axis bits, position, shape dimension, angle, up-axis decode, orientation view, team/colour/placement views
  labels.py          LabelTable decode/encode, label_text()
  slot.py            Slot (raw ints, views, repack), read_slot(), per-field spans
  walk.py            body walk, hypotheses, acceptance and plausibility checks (3.10)
  model.py           MapVariant: from_bytes(), to_bytes(force), info(), objects(), spans()
  edit.py            export planning: identity matching, edit plan, application, quota delta, new-object defaults
  validate.py        validation rules and issue codes (section 7)
  tables.py          maps, stock objects, palette groups, cached-type hints (reads data/*.json); delivered in G0 (needs no format knowledge)
  plain.py           to_plain(model) / from_plain(dict)
  report.py          decode report used by tools/verify_mvar.py
  io.py              read_file(), check_output_path(), write_atomic() with the path policy (2.13); delivered in G0
  data/maps.json             stock maps: id, name, source
  data/stock_objects.json    per map: [type_id, internal_type, display_name]; plus "disputed" ids
  data/palette_tree.json     palette group tree: names only (no meshes), used by the Add menu and by the assumed-cached-type rule; G0 commits a valid empty tree {"groups": []}, G4 generates the content
  data/cached_type_hints.json  {"assumed_zero_groups": ["Structure", "Scenery"], "known_classes": {...}}
```

### 6.2 Exception hierarchy

```
MvarError(Exception)
 +-- FormatError                  the input is not a supported map variant
 |    +-- BlfFormatError          container: not blf, bad tiling, truncated, bad _cmp, bad stored length
 |    +-- UnsupportedVariantError not a map variant, mvar size != 0x7028, body version not in {31, 32}, known non-Reach chunk version, content type
 |    +-- DesyncError             no hypothesis accepted; .diagnostics = per-hypothesis first failure
 |    +-- AmbiguousLayoutError    several hypotheses accepted with different decodes; .candidates
 |    +-- OutOfBoundsPositionError in_bounds == 0 at slot N (.slot)
 +-- DecodeError                  a field value is invalid (up-code face > 5, ...)
 +-- EncodeError                  a value cannot be represented (dimension > 200, position outside the bounds, ...)
 +-- CapacityError                the stream would exceed 0x7000 bytes
 +-- HashError                    internal hash/flavour failure
 +-- ValidationError              export refused; .issues = List[Issue] (all problems, not just the first)
 +-- PathPolicyError              output path forbidden (2.13)
 +-- InternalError                invariant I1/I2 violated: a library bug, never a user error
```
Every message is a complete sentence a user can act on; none contains a traceback. `errors.py` imports nothing from the package, so `api.py` can re-export every class without an import cycle (`ValidationError.issues` is a plain list of `api.Issue`).

### 6.3 Lower-level contracts (the parts G1 and G3 must build)

```python
# bitio.py
class BitReader:
    def __init__(self, data: bytes, bit_length: Optional[int] = None) -> None
    pos: int                                   # bit position
    def read(self, n: int) -> int              # n in 0..64 (and larger for blobs); raises BitOverrun past bit_length
    def read_signed(self, n: int) -> int
    def read_cstring(self, maxlen: int) -> bytes      # 8-bit units, stops after (and includes) the NUL, max maxlen units
    def read_u16string(self, maxlen: int) -> List[int]# 16-bit units, same rule
    def set_bitpos(self, p: int) -> None ; def remaining(self) -> int
class BitWriter:
    def write(self, value: int, n: int) -> None       # raises EncodeError unless 0 <= value < 2**n (a masked write would hide encoder bugs); MSB-first; never disturbs neighbouring bits
    def write_signed(self, value: int, n: int) -> None  # two's complement; raises EncodeError outside -2**(n-1) .. 2**(n-1) - 1
    def write_masked(self, value: int, n: int) -> None  # masks to n bits; used only by the RVT-port oracle in the tests
    def write_bitstring(self, bs: "BitString") -> None
    pos: int ; def getvalue(self, total_bytes: Optional[int] = None) -> bytes   # zero padded, never truncated
class BitString: data: bytes; nbits: int       # immutable; slice(start, end); get(start, n)

# hashing.py
@dataclass(frozen=True)
class HashFlavour: length_endian: str; recipe: str          # '>' | '<' ; one of the five names in 2.7, or 'zero'
def candidates(chunk: bytes, spec: PayloadSpec) -> List[Tuple[str, str, int, bool]]   # (endian, recipe, L, matches)
def detect_flavour(chunk: bytes, spec: PayloadSpec) -> Optional[HashFlavour]
def compute(flavour: HashFlavour, data: bytes, L: int) -> bytes

# blf.py
@dataclass(frozen=True)
class PayloadSpec:
    sig: str ; chunk_size: int ; hash_off: int ; length_off: int ; length_endian: str
    stream_off: int ; stream_capacity: int ; embedded_filelen_bit: int ; default_recipe: Optional[str]
PAYLOAD_SPECS = {
  "mpvr": PayloadSpec("mpvr", 0x5028, 12, 0x24, "<", 0x28, 0x5000, 72, "salted_be32"),
  "mvar": PayloadSpec("mvar", 0x7028, 12, 32,   ">", 36,   0x7000, 4,  None),   # None: detect, else salted_be32 + warning
}
def parse(data: bytes) -> BlfFile
class BlfFile:
    def to_bytes(self, force: bool = False, stream_length: Optional[Mapping[str, int]] = None) -> bytes
    def find(self, sig: str) -> Optional[Chunk]

# ugc_header.py
def read_header(r: BitReader) -> UgcHeader ; def write_header(w: BitWriter, h: UgcHeader) -> None
def parse_chdr(block: bytes) -> dict ; def build_chdr(d: dict) -> bytes      # byte-exact on real files (V)

# codecs.py   (all pure; signatures as in section 4)
axis_bits_ceil(rng), axis_bits_trunc(rng), axis_bits_ceil_f32(rng), axis_bit_hypotheses(bounds) -> List[Tuple[int,int,int]]
pos_decode(q, bits, mn, mx), pos_encode(v, bits, mn, mx), pos_tolerance(bits, mn, mx)
dim_decode(v), dim_encode(x), angle_decode(raw), angle_encode(t), up_decode(code), reconstruct_orientation(up_global, up_code, angle_raw) -> (forward, up)
team_view(raw) -> int, team_raw(view) -> int, placement_view(byte) -> PlacementView

# walk.py
@dataclass(frozen=True)
class Hypothesis: type19: str ; axis_bits: Tuple[int,int,int] ; guid: bool       # guid = guid_present (3.10)
def walk_stream(stream: bytes, L: int, hyp: Hypothesis, spec) -> WalkResult   # header .. quota; raises on overrun/OOB
def choose(stream: bytes, L: int, version_hint: Optional[int]) -> Tuple[Hypothesis, WalkResult, List[HypothesisReport]]

# model.py
class MapVariant:
    @classmethod
    def from_bytes(cls, data: bytes, options: Optional[ReadOptions] = None) -> "MapVariant"
    def to_bytes(self, force: bool = False, flavour: Optional[HashFlavour] = None) -> bytes   # flavour forces a recipe: ExportOptions.hash_policy and the probe files of tools/reencode_mvar.py (HashFlavour('>', 'zero') writes 20 zero bytes)
    def info(self) -> MapInfo ; def objects(self) -> List[ObjectRecord] ; def spans(self) -> List[Tuple[str,int,int]]
    def copy(self) -> "MapVariant"                  # deep copy, for planning
```

### 6.4 The frozen interface (`Addon/mvarlib/api.py`): the contract between G3/G5 and G4

This file is written at G0, is COMPLETE at G0 (DEC-6.4) (the two entry points are lazy delegations that never change) and is not changed without both teams agreeing. G3/G5 implement `entry.py`; G4 builds the Blender glue against `tests/stubs/stub_mvarlib.py`, which implements the same names with canned data (section 11, G0 and G4).

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from .errors import (MvarError, FormatError, BlfFormatError, UnsupportedVariantError, DesyncError,
                     AmbiguousLayoutError, OutOfBoundsPositionError, DecodeError, EncodeError, CapacityError,
                     HashError, ValidationError, PathPolicyError, InternalError)    # re-exported: the glue catches P.MvarError

Vec3 = Tuple[float, float, float]
Bounds = Tuple[float, float, float, float, float, float]       # xmin, xmax, ymin, ymax, zmin, zmax

@dataclass(frozen=True)
class Issue:
    code: str                          # 'E_...' (refusal), 'W_...' (warning), 'I_...' (info); table in section 7
    severity: str                      # 'error' | 'warning' | 'info'
    message: str                       # complete sentence, user-facing
    slot: Optional[int] = None
    object_name: Optional[str] = None

@dataclass(frozen=True)
class MapInfo:
    map_id: int ; map_name: Optional[str] ; is_stock_map: bool ; bounds: Bounds
    quota_count: int ; version: int ; title: str ; description: str
    labels: List[str]                  # index -> text; '' where the entry is absent (see label_present)
    label_present: List[bool]
    occupied: int ; shape: str         # container shape id, e.g. 'plain4'
    template_sha256: str ; hash_flavour: str            # e.g. 'salted_be32/>' or 'unknown'
    palette_crc: int ; max_budget_raw: int ; spent_budget_raw: int
    hypothesis: Dict[str, object]      # {'type19': 'flag8'|'plain8'|'undetermined', 'axis_bits': [..], 'guid': bool, 'length_class': 'ceil_end'}
    warnings: List[Issue] = field(default_factory=list)

@dataclass(frozen=True)
class ObjectRecord:                    # one occupied slot, "ForgeObject-like" (3.11)
    slot: int
    folder: int ; item: int            # -1 where the file has the absent bit
    type_id: int                       # (folder << 8) | item, or -1
    type_name: str                     # display name on this map, or "Unknown (0x%04X)"
    stock: bool                        # (map, type_id) is in the stock table
    position: Vec3 ; forward: Vec3 ; up: Vec3
    orientation_kind: str              # 'vertical' | 'tilted'
    parent_slot: int                   # -1 none
    shape: int ; width: float ; length: float ; top: float ; bottom: float
    spawn_sequence: int ; spawn_time: int ; cached_type: int ; label_index: int   # -1 none
    placement: int ; physics: int ; symmetry: int ; place_at_start: bool ; game_specific: bool   # 3.9, file reading
    team: int                          # -1 none, 0..8
    color: int                         # -1 none (team colour), 0..7
    other_a: int ; other_b: int ; flags2: int
    raw: bytes ; raw_bits: int         # identity token

@dataclass(frozen=True)
class LoadResult:
    info: MapInfo ; objects: List[ObjectRecord] ; warnings: List[Issue]

@dataclass
class ExportObject:                    # one Blender object (or one array instance) handed to export
    name: str
    slot: Optional[int]                # None = no slot claimed (new object)
    token_raw: Optional[bytes] ; token_bits: Optional[int]
    name_matches_import: bool = False
    type_name: str = ""                # display name of the instanced palette collection (suffix .NNN stripped), or the imported type name
    type_id_hint: int = -1             # the imported type id (forge.objectType), -1 if none
    position: Vec3 = (0.0, 0.0, 0.0) ; forward: Vec3 = (0.0, 1.0, 0.0) ; up: Vec3 = (0.0, 0.0, 1.0)
    shape: int = 0 ; width: float = 0.0 ; length: float = 0.0 ; top: float = 0.0 ; bottom: float = 0.0
    spawn_sequence: int = 0 ; spawn_time: int = 0 ; cached_type: int = 0 ; label_index: int = -1
    physics: int = 3 ; symmetry: int = 3 ; place_at_start: bool = True ; game_specific: bool = False
    team: int = 8 ; color: int = -1 ; other_a: int = 0 ; other_b: int = 0
    hidden: bool = False ; from_array: bool = False          # informational, used in the diff

@dataclass
class ExportOptions:
    allow_unverified_rotation: bool = False
    force_reencode: bool = False
    fsm_policy: str = "KEEP"           # 'KEEP' | 'DROP'
    hash_policy: str = "REPRODUCE"     # 'REPRODUCE' (template's flavour, DEC-2.3) | 'SALTED_BE32' | 'PLAIN_LE32' (force a recipe)
    keep_unrecognised_imported: bool = False             # DEC-7.4: keep imported objects whose id is not in the map's stock table (warning instead of E_OBJ_NOT_STOCK)
    imported_slots: Optional[Sequence[int]] = None      # slots that were successfully imported; None = all present slots
    max_objects: int = 650
    raise_quota_max: bool = False      # D11: opt-in; when a quota row new placed would exceed its maximum, raise maximum to the new placed (never lowers anything, never touches minimum); warning W_QUOTA_MAX_RAISED

@dataclass(frozen=True)
class DiffEntry:
    kind: str                          # 'kept' | 'moved' | 'edited' | 'retargeted' | 'added' | 'removed' | 'not_imported'
    slot: Optional[int] ; name: str ; detail: str

@dataclass(frozen=True)
class ExportResult:
    ok: bool
    data: Optional[bytes]              # None when ok is False; nothing may be written
    diff: List[DiffEntry]
    errors: List[Issue] ; warnings: List[Issue]
    stats: Dict[str, object]           # occupied_before/after, end_bit, capacity_bits, L, hash_flavour, quota_changes, mode ('passthrough'|'patched'|'forced')

@dataclass(frozen=True)
class ReadOptions:
    strict: bool = True                # False only for verify_mvar --lenient; export refuses non-strict parses
    hypothesis_filter: Optional[Dict[str, object]] = None   # diagnostics/tests only

def load_map_variant(data: bytes, name: str = "", options: Optional[ReadOptions] = None) -> LoadResult:
    from . import entry                       # lazy; entry.load_map_variant raises NotImplementedError("G3") until G3; the stub returns canned data
    return entry.load_map_variant(data, name, options)

def export_map_variant(template: bytes, objects: Sequence[ExportObject], options: ExportOptions) -> ExportResult:
    from . import entry                       # lazy; entry.export_map_variant raises NotImplementedError("G5") until G5; the stub records its arguments
    return entry.export_map_variant(template, objects, options)

# Data and path helpers: implemented in G0 (they need only the JSON tables and `os`, no format knowledge), so G4 can use them
def map_name_for_id(map_id: int) -> Optional[str]:
    from . import tables
    return tables.map_name_for_id(map_id)                            # data/maps.json
def stock_object_names(map_name: str) -> List[str]:
    from . import tables
    return tables.stock_object_names(map_name)                       # data/stock_objects.json: display names valid on that map
def palette_tree() -> Dict[str, object]:
    from . import tables
    return tables.palette_tree()                                     # data/palette_tree.json
def check_output_path(target: str, source_paths: Sequence[str] = (), protected: Optional[Sequence[str]] = None) -> Optional[Issue]:
    from . import io as mio
    return mio.check_output_path(target, source_paths, protected)    # E_PATH_SAME_AS_SOURCE / E_PATH_PROTECTED (2.13), else None
def write_atomic(target: str, data: bytes, source_paths: Sequence[str] = (), protected: Optional[Sequence[str]] = None) -> None:
    from . import io as mio
    mio.write_atomic(target, data, source_paths, protected)          # raises PathPolicyError (2.13)

__all__ = ["Vec3", "Bounds", "Issue", "MapInfo", "ObjectRecord", "LoadResult", "ExportObject", "ExportOptions",
           "DiffEntry", "ExportResult", "ReadOptions", "load_map_variant", "export_map_variant",
           "map_name_for_id", "stock_object_names", "palette_tree", "check_output_path", "write_atomic",
           "MvarError", "FormatError", "BlfFormatError", "UnsupportedVariantError", "DesyncError",
           "AmbiguousLayoutError", "OutOfBoundsPositionError", "DecodeError", "EncodeError", "CapacityError",
           "HashError", "ValidationError", "PathPolicyError", "InternalError"]
```
(The block above is valid Python 3.9 as written; it was checked with an import plus instantiation smoke test on 3.9.6 and 3.13.13 inside a stub package carrying `errors.py`, `entry.py`, `tables.py` and `io.py` (revision pass, `S`). G0 commits it as `Addon/mvarlib/api.py` COMPLETE, adding only the module docstring: the two entry points are lazy delegations that never change later, and the five helpers delegate to modules that G0 also delivers. `Addon/mvarlib/entry.py` is created in G0 with bodies that `raise NotImplementedError("G3")` / `("G5")`; G3 and G5 edit `entry.py` only. **Interface freeze v1** = the SHA-256 of `api.py` and `errors.py`, recorded in `NOTES.md` and in `tests/golden/interface_sha256.json`; test U-22 `test_interface_frozen.py` fails when either file differs from the record.)

Contract notes:
- `export_map_variant` is **stateless**: it re-parses `template` (strict). It never touches the file system. It returns all problems at once (`errors` is the full list). `ok = False` implies `data is None`.
- If steps 1 to 9 of 5.10 collect no error (container, map, per-object rules, the 650-object limit, quotas, capacity), no object changed, `force_reencode` is false and `fsm_policy` does not drop a block, `ok` is true and `data == template` (passthrough). A template that already holds more than `max_objects` occupied slots is therefore refused even when nothing changed (`E_TOO_MANY`, binding decision E; 10.2 item 11).
- `ExportObject.team = 8` with a `none` baseline, and `color = -1` with a `none` baseline, count as unchanged (4.9). `color = 8` is `E_COLOR_NEUTRAL`.
- `ObjectRecord` lists occupied slots in slot order. Unknown types still appear (`stock = False`, `type_name = "Unknown (0x....)"`).
- The glue never interprets bits; it maps UI enums to these integers (`symmetry` 0..3, `physics` 0/1/3).
- The error classes of `errors.py` are re-exported by `api.py`: the glue catches `P.MvarError` (`P = get_provider()`) and never imports `errors` itself.
- `ExportOptions.raise_quota_max` (interface freeze v2, DECISION D11; default `False`, appended last so every v1 call stays valid): off, a quota row whose new `placed` would exceed its `maximum` is `E_QUOTA`; on, its `maximum` is raised to the new `placed` (never lowered, `minimum` never touched), `W_QUOTA_MAX_RAISED` names each raised row, and `ExportResult.stats['quota_changes']` lists every changed row (`folder`, `name`, `minimum`, `placed_before`, `placed_after`, `maximum_before`, `maximum_after`).

### 6.5 Tool-facing helper API (not frozen, used by `tools/`)

`mvarlib.report.build_report(data, options) -> Report` and `format_report(report) -> str` (section 6.7); `mvarlib.plain.to_plain(model)`; `mvarlib.plain.from_plain(d)`; `mvarlib.io.write_atomic(...)`.

### 6.6 Plain-dict / JSON form (`to_plain` / `from_plain`)

Purpose: load a map variant into plain data and write it back; golden fixtures; diffing; debugging. JSON-safe: 64-bit values and byte strings are hex strings.

```json
{
 "schema": "mvarlib.plain/1",
 "container": {"shape": "plain4", "chunks": [{"sig": "_blf", "version": 1, "flags": 2, "body_hex": "..."}, {"sig": "chdr", "version": 10, "flags": 2, "body_hex": "..."}, {"sig": "mvar", "version": 31, "flags": 1}, {"sig": "_eof", "version": 1, "flags": 1}],
                "cmp": null, "trailer_hex": null, "eof_endian": ">", "hash": {"length_endian": ">", "recipe": "salted_be32"}, "length_class": "ceil_end"},
 "header": {"content_type_raw": 6, "file_length": 29481, "ids": ["0x0123456789ABCDEF", "...", "...", "0x0"], "activity_raw": 1, "game_mode": 4, "engine": 1, "map_id": 3006, "category": 0,
            "created_by": {"timestamp": 1700000000, "xuid": "0x0", "name_hex": "4100", "online": 0}, "modified_by": {"...": "..."}, "title": "W1 minimal", "description": "...",
            "hopper_id": null, "campaign_hex": null, "firefight_hex": null, "raw_hex": "..."},
 "body": {"version": 31, "checksum": "0xFFFFFFFF", "palette_crc": "0xDEADBEEF", "quota_count": 80, "map_id_2": 3006, "built_in": 0, "built_from_xml": 0,
          "bounds_hex": ["c3700000", "..."], "max_budget": 30000, "spent_budget": 123, "guid_hex": null},
 "labels": {"entries": [0, 6, 20], "data_length": 26, "compressed": false, "buffer_hex": "...", "comp_hex": null},
 "layout": {"type19": "flag8", "axis_bits": [20, 21, 19], "guid": false},
 "slots": [{"index": 1, "flags2": 1, "folder": 70, "item": 0, "in_bounds": 1, "pos": [524288, 1048576, 262144], "up_global": 1, "up_code": null, "angle": 8192,
            "parent_raw": 0, "shape": 0, "dims": [], "spawn_seq": 0, "respawn": 0, "cached_type": 0, "label": null, "placement": 204, "team_raw": 9, "color": null, "extra": []}],
 "quotas": [[0, 0, 0], "..."],
 "tail_hex": "",
 "views": {"note": "derived floats for humans; ignored by from_plain"}
}
```
Only present slots are listed (absent slots are implicit). `from_plain(to_plain(m)).to_bytes(force=True) == original` for every fixture of shape `plain4` / `plain4+fsm` (for the `cmp` shapes: the golden expanded file); `header.raw_hex` is the exact bit range padded to bytes plus `header.raw_bits`.

### 6.7 Command-line tools

Tools directory: `~/Documents/Halo_MCC/mjolnir-forge-editor/source/tools/`.

All tools run as `python3 -I tools/<tool>.py`. Because `-I` removes the script directory from `sys.path`, each tool begins with `sys.path.insert(0, <repo>/Addon)` computed from `__file__` and `import mvarlib`.

| Tool | Purpose | Notes |
|---|---|---|
| `verify_mvar.py FILE...` | **T3.** Decode report for a real `.mvar` (and container report for any BLF file), no game data written | below |
| `dump_mvar.py FILE [--plain OUT.json] [--slots] [--spans]` | print or save the plain form | writes only through `mvarlib.io.write_atomic`; refuses any output path that resolves inside the repo working tree (no exception) or inside a protected folder (DEC-6.1: derived map data must not be committed) |
| `reencode_mvar.py IN OUT [--force] [--hash-recipe NAME] [--zero-hash] [--corrupt-hash]` | write the passthrough copy, the forced re-encode (equal to the input for plain shapes; a self-test), or a **probe** file whose SHA-1 is recomputed with another recipe, set to 20 zero bytes, or deliberately corrupted (ladder rung H, section 9.5) | writes only through `mvarlib.io.write_atomic` (the realpath/symlink same-file check and the protected-folder check of 2.13 apply); refuses OUT == IN and any OUT inside the repo working tree |
| `check_no_game_assets.py` | repo guard (exists in the working tree; G0 extends it); scans gitignored files too (DEC-F.2) | exit 0 clean, 1 violation, 2 cannot run |
| `run_tests.py` / `run_tests.sh` | the test driver (section 9); `run_tests.py` also snapshots the sample folders before and after the run (U-21) | `.sh` is `#!/bin/bash` with `set -o pipefail`, requires `/usr/bin/python3` to report 3.9.x, and runs Python 3.9 and 3.13 |
| `run_blender_tests.sh [--provider stub\|real] [--only ID...] [--real-library]` | builds the default package (with `--allow-placeholders`) into a fresh `mktemp -d`, installs it into an isolated profile, runs the 9.4 commands and prints `BLENDER_EXIT=n` | outside the repo |
| `accept.sh` | runs rows 1, 1b, 2, 3, 4, 5, 6 and 7 of the acceptance sheet 9.8 and prints PASS or FAIL per row | |
| `accept_real_mvar.sh FILE.mvar` | optional: copies FILE to a temp dir, runs `verify_mvar` and the B-15 steps on the copy (9.8 row 2R) | never touches FILE |
| `build_package.py --out DIR [--with-library --i-accept-that-this-copies-game-assets] [--allow-placeholders]` | stage and build the Blender extension zip; the default zip contains no game asset (8.10) | `DIR` must be outside the repo working tree |
| `gen_stock_tables.py` | generate `data/maps.json` and `data/stock_objects.json` from `Addon/objects.py` and RVT's map list | deterministic; the sync test fails if the committed JSON differs |
| `gen_palette_tree.py` | headless Blender: write `data/palette_tree.json` (names only) from `Halo Reach.blend` | opens the blend read-only; writes no game data |

`verify_mvar.py` output sections (all printed; `--json OUT` writes the same facts; `--no-strings` omits titles, authors, label text):
1. container: blocks (signature, offset, size, version, flags), tiling, shape id, `_cmp`/`_fsm`, `_eof` value and byte order, file size;
2. hash: every candidate `(length byte order, recipe)` with L and match yes/no, including `zero` (stored hash all zero: yes/no); chosen flavour; "enforcement unknown";
3. header: content type, fileLength vs real, ids, activity, game mode, engine, map id and resolved name, category, authors (names, timestamps), title, description, header end bit, `chdr` agreement;
4. body: version, checksum, palette CRC, quota count, map id copy, flags, bounds and ranges, axis bit triples for the three rounding variants (and whether ambiguous), budget words, label table (count, buffer size, compression, texts), GUID;
5. walk: table of hypotheses (type19 rule x axis triple x guid_present): accepted yes/no, `end`, `ceil(end/8)` vs L, plausibility violations, first failure; selected hypothesis or the failure report; `length_class`;
6. slots: occupied count, free slots, per-folder histogram, unresolved (folder, item) pairs for the map, cached-type histogram per folder (and "same folder, several cached types" count), placement-byte histogram, team/colour/shape/label histograms, parent links (valid / dangling), type-19 count and the rule determined, out-of-bounds count, position cells at the range extremes, `forward . up` orthogonality of the reconstructed orientations;
7. quotas: rows, per folder `placed` vs the number of present slots, min > max rows;
8. tail and padding: tail zero?, pad bits zero?;
9. self-checks: slot repack identity `651/651`; label re-encode identical yes/no; unmodified `to_bytes() == input`; `to_bytes(force=True) == input` (else the first differing section and bit); plain round trip identical.

Exit codes: 0 all good; 1 desync/ambiguous/out-of-bounds/format error; 2 usage, I/O, or the file is not a map variant (a game variant gets the container report and exit 2); 3 decode succeeded but a self-check failed. Every non-zero exit prints one line `VERIFY FAILED: <reason>` last.

### 6.8 Python compatibility rules (3.9 to 3.13)

Forbidden because they break on 3.9.6: `match`/`case`; `int | None` annotations or `isinstance(x, int | str)` without `from __future__ import annotations`; `@dataclass(slots=True)`, `kw_only=True`, `match_args=`; `zip(strict=True)`; `int.bit_count()`; `itertools.pairwise` and `itertools.batched`; `str | None` in `typing` aliases evaluated at runtime; `except*`; `datetime.UTC`; `import tomllib`; `int.from_bytes(b)` / `.to_bytes(n)` without a byteorder argument; `math.cbrt`, `math.exp2`, `math.sumprod`; `enum.StrEnum`; `typing.Self`, `TypeAlias`, `ParamSpec`, `TypeGuard`; quote reuse inside an f-string expression (3.12 only). (Parenthesised multi-item `with` was in the first draft's list; it runs on 3.9.6, re-tested `S`, and is allowed.) Allowed: `from __future__ import annotations`, f-strings, walrus, `math.isqrt`, `dict | dict`, built-in generics in annotations (`list[int]`).

Enforcement. `ast.parse(source, feature_version=(3, 9))` catches only syntax-level constructs (`match`, `except*`, f-string quote reuse; re-tested on 3.13.13 `S`) and misses every runtime one: on 3.9.6 `int | None` annotations raise `TypeError` at import, `dataclass(slots=True)` and `zip(strict=True)` raise `TypeError`, `.bit_count()` and `itertools.pairwise` raise `AttributeError`, `int.from_bytes(b)` raises `TypeError`, yet the scan passes all of them (`S`). U-19 therefore (a) imports every module of `Addon/mvarlib` and `tools` under `/usr/bin/python3` (3.9.x), and (b) runs the AST lint `tests/py39_lint.py` (G0, about 60 lines) on every file of `Addon/mvarlib`, `tests` and `tools`; the lint flags each forbidden construct above that the parser accepts. The whole suite runs under both interpreters.

---------------------------------------------------------------------------------------------------

## 7. Validation rules for import and export

Principle: **everything is checked before a single byte is written, all problems are collected and reported together** (a user fixing one at a time is a bad experience), and a refusal never leaves a partial file. Read-time problems are exceptions (6.2); export-time problems are `Issue`s in `ExportResult.errors` (6.4). Issue codes are stable identifiers used by the tests.

### 7.1 Data sources

| Rule input | Source | Notes |
|---|---|---|
| Stock maps: id <-> name | `Addon/mvarlib/data/maps.json`, generated by `tools/gen_stock_tables.py` from `P:RVT ui/script_editor/page_map_perms.cpp:15-58 S` and the 20 map names of `Addon/objects.py`. (`research/tables/maps*.json` named in the task **does not exist**, X22.) | table below |
| Stock objects per map | `Addon/mvarlib/data/stock_objects.json`, generated from `Addon/objects.py` (`map_object_types` + `type_to_name`), equal in content to `research/tables/stock_objects_per_map_with_model_flag.json` | id = `(folder << 8) + item`; display names unique **per map** (the global duplicate "Sprint" is two ids on different maps and resolves per map) |
| Quota count, bounds, label count, version | the template | |
| Object limit | 650 occupied slots (X17) | `ExportOptions.max_objects` |
| Capacity | 0x7000 x 8 = 229,376 bits | |
| Learned cached types, defaults | the template's occupied slots | 7.4 |

Stock maps (20), ids from `P:RVT page_map_perms.cpp:15-58 S`: Sword Base 1000, Countdown 1020, Boardwalk 1035, Zealot 1040, Powerhouse 1055, Boneyard 1080, Reflection 1150, Spire 1200, Condemned 1500, Highlands 1510, Anchor 9 2001, Breakpoint 2002, Tempest 2004, Forge World 3006, Penance 10010, Battle Canyon 10020, Ridgeline 10030, Breakneck 10050, High Noon 10060, Solitary 10070. RVT's list also contains an "Unknown 1" placeholder (id 1) and 1001 and 1056 ("Unused (DLC ...)"), which are **not** stock for this purpose; its campaign (5005..5080) and firefight (7000..7500, 10080) ids are commented out there. Creep's Forge World and its Night variant (modded, `Map.cs`) have no id table. That the map-variant header's `mapID` carries the same ids as game-variant map permissions is `I`.

Objects per map (`stock_objects.json`): Forge World 348, Boardwalk 121, Boneyard 96, Countdown 121, Powerhouse 123, Reflection 117, Spire 100, Sword Base 116, Zealot 109, Anchor 9 102, Breakpoint 119, Tempest 347, Condemned 125, Highlands 116, Battle Canyon 161, Penance 112, Ridgeline 232, Solitary 197, High Noon 209, Breakneck 218 (`S`). The two id tables upstream (`ItemParser.cs`, `objects.py`) disagree on 36 entries, mostly spelling; the real id conflicts are Tempest `0x2800-0x2802` vs `0x6100-0x6102` (Forerunner and plain Man Cannons swapped) and Breakneck `0x2203/0x2204` (Man Cannon vs Vehicle Cannon swapped). `objects.py` is canonical (DEC-7.1); the 8 ids are listed under `"disputed"` and produce `W_DISPUTED_ID` when a *new* object uses them. Because the tables were never checked against a real file, they are plain data: one real `.mvar` can correct them without code changes.

### 7.2 Read-time refusals (exceptions)

| Exception | Condition | Message pattern |
|---|---|---|
| `BlfFormatError` | first block is not `_blf` | `This file is not a Halo BLF file (first block is '%s', expected '_blf').` |
| `BlfFormatError` | blocks do not tile | `The file is damaged: block '%s' at offset 0x%X claims %d bytes but only %d remain.` |
| `BlfFormatError` | bad `_cmp` | `The compressed (_cmp) block could not be expanded: %s.` |
| `BlfFormatError` | stored length invalid in both byte orders | `The stored stream length bytes %s are not a valid length (maximum 0x7000).` |
| `UnsupportedVariantError` | `mpvr` present, no `mvar` | `This is a game variant (block 'mpvr'), not a map variant. Use File > Import for map variants only.` |
| `UnsupportedVariantError` | no `mvar` | `No map variant block ('mvar') was found; blocks present: %s.` |
| `UnsupportedVariantError` | mvar size | `The map variant block has size 0x%X; only 0x7028 is supported.` |
| `UnsupportedVariantError` | version | `The map variant body version is %d; supported versions are 31 and 32.` |
| `UnsupportedVariantError` | `mvar` chunk version in {12, 13, 14, 50, 51} (2.2, X26) | `The map variant block has chunk version %d; Halo: Reach uses 31 or 32 (50 and 51 are Halo 4, 12 to 14 are Halo 3).` |
| `FormatError` | a bounds value is not finite, or `min > max` on an axis (3.3) | `The map bounds are not valid (axis %s: min %g, max %g).` |
| `UnsupportedVariantError` | content type | `The content type is %d (%s); a map variant is 5.` |
| `DesyncError` | no hypothesis accepted | `Could not read this map variant: none of the %d known layouts fits. Best candidate (%s) fails at slot %d, bit %d: %s. Run tools/verify_mvar.py on the file for the full report.` |
| `AmbiguousLayoutError` | several accepted, different | `This map variant can be read %d different ways that all look valid (they first differ at slot %d). Run tools/verify_mvar.py for details.` |
| `OutOfBoundsPositionError` | `in_bounds == 0` | `Slot %d has a position outside the map bounds (in-bounds flag is 0). Such records need map data that is not in the file and cannot be read.` |

Import itself is permissive about *content*: unknown maps and unknown object ids import (as "Unknown (0x....)" arrow empties); only export refuses them.

### 7.3 Export refusals and warnings (`Issue.code`)

"Source" names where the rule's data comes from. All messages are complete sentences; `%s` object names are Blender object names.

| Code | Sev | Condition | Source | Message pattern |
|---|---|---|---|---|
| `E_NO_TEMPLATE` | error | the scene has no embedded template (glue) | scene key | `This scene has no imported map variant. Import a .mvar first: export patches the imported file.` |
| `E_TEMPLATE_CORRUPT` | error | embedded bytes do not match the stored SHA-256 (glue) | scene keys | `The map variant stored in this scene is damaged (checksum mismatch). Import the original file again.` |
| `E_TEMPLATE_UNREADABLE` | error | the embedded template fails the strict parse (library) | blf, walk | `The imported map variant could not be read again: %s` |
| `E_MAP_UNKNOWN` | error | `map_id` not in `maps.json` | header | `Map id %d (0x%X) is not one of the 20 stock Halo: Reach maps this tool supports. Export is limited to stock maps.` |
| `E_CONTAINER_SHAPE` | error | shape `other` and the model is dirty | blf | `This file's block layout (%s) cannot be modified safely.` |
| `E_TOO_MANY` | error | occupied after edits > `max_objects` (an unchanged template that already exceeds the limit is refused too: binding decision E; the contract note in 6.4 says so) | options | `%d objects would be written; the limit is %d. Remove %d object(s). (A file that already holds more than %d objects cannot be exported.)` |
| `E_NO_FREE_SLOT` | error | no absent slot for a new object | slots | `No free object slot is left for '%s'.` |
| `E_OBJ_NO_TYPE` | error | object has neither a resolvable name nor a baseline id | glue | `Object '%s' has no Forge object type. Add it with Add > Forge Object, or duplicate an imported object.` |
| `E_OBJ_NAME_UNKNOWN` | error | new/retargeted: `type_name` not in `stock_objects[map]` display names | stock table | `Object '%s' uses '%s', which is not a stock object on %s.` |
| `E_OBJ_NOT_STOCK` | error | new, retargeted or imported: resolved id not in the map's table (for an imported object only while `keep_unrecognised_imported` is off, DEC-7.4) | stock table | `Object '%s' (id 0x%04X) is not a stock object on %s.` |
| `E_FOLDER_RANGE` | error | new/retargeted: `folder >= quota_count` | body | `Object '%s' needs palette entry %d, but this map variant defines only %d entries.` |
| `E_OUT_OF_BOUNDS` | error | any position axis outside `[min, max)` (on a zero-range axis the interval is empty: every new or moved position on it is refused) | bounds | `Object '%s' is at (%.3f, %.3f, %.3f), outside the map bounds (x %.1f to %.1f, y %.1f to %.1f, z %.1f to %.1f). Move it inside; positions are never clamped.` |
| `E_QUOTA` | error | `placed` would exceed `maximum` (7.5) | quota rows | `Palette entry %d (%s) would have %d placed; the maximum on this map variant is %d.` |
| `E_QUOTA_MIN` | error | `placed` would fall below `minimum` (7.5) | quota rows | `Palette entry %d (%s) would drop to %d placed; the minimum on this map variant is %d.` |
| `E_QUOTA_RANGE` | error | `placed` > 255 | | `Palette entry %d (%s) cannot hold more than 255 objects.` |
| `E_CACHED_TYPE_UNKNOWN` | error | new object, class not learnable and not in an assumed group (7.4) | slots, hints | `Cannot add a new '%s': its game object class is not known from this map variant. Place one in the game and import again, or duplicate an object of the same kind.` |
| `E_CACHED_TYPE_CHANGED` | error | existing object's Blender `cached_type` differs from the baseline | slot | `Object '%s': the object class cannot be changed.` |
| `E_RETARGET_CLASS` | error | retarget to a type whose learned class differs | slots | `Object '%s' cannot change from '%s' to '%s': they are different object classes.` |
| `E_TYPE19_UNDETERMINED` | error | creating/changing a cached-type-19 object while the rule is undetermined | hypothesis | `Location-name objects cannot be created or edited yet: this map variant contains none, so how they are stored is undetermined.` |
| `E_ROTATION_GATED` | error | new or changed orientation and the gate is off (4.8) | options | `Object '%s' has a new or changed rotation. Writing rotation is unverified: tick Forge Scene > "Allow unverified rotation export" to write it.` |
| `E_TILT_UNSUPPORTED` | error | new or changed orientation with `up` not +Z | options | `Object '%s' is tilted. Writing a tilted orientation is not supported; rotate it around Z only, or leave its rotation unchanged.` |
| `E_MIRRORED` | error | negative determinant | glue | `Object '%s' has a mirrored (negative scale) transform, which cannot be exported.` |
| `E_TRANSFORM_INVALID` | error | position, forward or up non-finite, or forward or up of length < 1e-6 (5.10 step 3, before any codec call) | fields | `Object '%s' has an invalid (non-finite or zero-length) position, forward or up vector and cannot be exported.` |
| `E_ARRAY_NOT_EVALUATED` | error | an array source (parent with `instance_type` FACES or VERTS) has no evaluated instance because its parent is hidden, excluded or empty (8.5) | glue | `Array '%s' is hidden, excluded or empty, so its instances cannot be read. Unhide it, include its collection or apply the array, then export again.` |
| `E_FLAG_UNVERIFIED` | error | symmetry, place-at-start or game-specific differ from baseline (3.9; for a new object the baseline is the learned example's, 5.6) | slot | `Object '%s': %s cannot be changed yet; how it is stored is unverified.` |
| `E_COLOR_NEUTRAL` | error | colour 8 | fields | `Object '%s': the colour "Neutral" cannot be stored in a map variant (use colours 0 to 7 or "Team").` |
| `E_TEAM_RANGE` | error | team not in 0..8 | fields | `Object '%s': team must be 0 to 8.` |
| `E_SHAPE_RANGE` | error | dimension < 0 or > 200, shape not 0..3 | fields | `Object '%s': %s must be between 0 and 200 (got %.3f).` |
| `E_SPAWN_RANGE` | error | spawn sequence not in -128..127 or spawn time not in 0..255 | fields | `Object '%s': spawn sequence must be -128 to 127 and spawn time 0 to 255.` |
| `E_LABEL_RANGE` | error | label index not in `[-1, label_count)` or entry absent | labels | `Object '%s': label %d is not in this map variant's label table (%d labels).` |
| `E_OTHER_RANGE` | error | `other_a/other_b` outside the field width for the cached type | fields | `Object '%s': %s must be 0 to %d.` |
| `E_COLOR_RANGE` | error | colour not in -1..7 and not 8 (added by gate G5; no enum can produce it, 7.3 only had `E_COLOR_NEUTRAL`) | fields | `Object '%s': the colour must be -1 (team colour) or 0 to 7 (got %d).` |
| `E_PHYSICS_RANGE` | error | physics not in 0..3 (added by gate G5) | fields | `Object '%s': physics must be 0 (normal), 1 (fixed) or 3 (phased) (got %d).` |
| `E_OPTION_INVALID` | error | `fsm_policy` or `hash_policy` has an unknown value (added by gate G5) | options | `The export option %s has the unknown value %r.` |
| `E_CAPACITY` | error | encoded bits > 229,376 | stream | `The edited map variant needs %d bits; it can hold at most 229,376.` |
| `E_PATH_SAME_AS_SOURCE` | error | target resolves to the imported file (glue/io) | io | `Refusing to overwrite the file this map was imported from (%s). Choose a different name.` |
| `E_PATH_PROTECTED` | error | target in a protected folder (glue/io) | preferences | `Refusing to write into the protected folder %s.` |
| `W_HASH_UNKNOWN` | warning | no hash candidate matched the template | hashing | `The template's SHA-1 matches no known recipe; the salted recipe was written. Whether MCC checks it is unknown.` |
| `W_GUID_VERSION_MISMATCH` | warning | only the `guid_present` value that contradicts the body version gave an accepted walk (3.10) | walk | `This map variant says it has version %d but the 128-bit block that versions 32 and above carry is %s; it was read that way because only that reading fits.` |
| `W_VERSION_MISMATCH` | warning | the `mvar` chunk version differs from the body version byte (2.2, 3.3) | body | `The map variant block has chunk version %d but its body says version %d.` |
| `W_CHUNK_VERSION_UNEXPECTED` | warning | chunk version outside {31, 32} and not a refused Halo 3/4 value (2.2) | blf | `The map variant block has chunk version %d; Halo: Reach uses 31 or 32. It was read anyway because the layout fits.` |
| `W_ZERO_RANGE_AXIS` | warning | a bounds axis has `min == max` (3.3) | body | `The map bounds have no extent on the %s axis; positions on that axis cannot be changed.` |
| `W_TRAILER_KEPT` | warning | a trailer after `_eof` was kept (2.1) | blf | `%d bytes after the end-of-file block were kept unchanged.` |
| `W_CMP_EXPANDED` | warning | `_cmp` template and modified save | blf | `The map variant was stored compressed; the exported file stores it uncompressed (the game accepts both, per the available documentation).` |
| `W_FSM_STALE` | warning | `_fsm` kept after modification | blf | `The file-share signature block (_fsm) was kept unchanged. If MCC refuses the file, export again with fsm_policy = DROP.` |
| `W_TOKEN_MISMATCH` | warning | claimant's token does not match the template slot | slots | `Object '%s' claims slot %d but does not match the imported file (copied from another file?); it was treated as a new object.` |
| `W_DUPLICATE_SLOT` | warning | several valid claimants | slots | `Objects '%s' and '%s' both claim slot %d; kept '%s' and treated '%s' as new.` |
| `W_SLOT_NOT_IMPORTED` | warning | present template slot not in `imported_slots` | options | `Slot %d could not be imported earlier; it was left unchanged in the exported file.` |
| `W_PARENT_CLEARED` | warning | a deleted slot was some slot's parent | slots | `Slot %d lost its "spawn relative to" parent because slot %d was deleted.` |
| `W_HIDDEN_EXPORTED` | warning | hidden objects were included (glue) | glue | `%d hidden object(s) were exported. Hidden objects are not skipped; delete them to remove them from the map.` |
| `W_ORIENTATION_UNVERIFIED` | warning | any rotation written | gate | `%d object(s) had their rotation written with an unverified convention.` |
| `W_CACHED_TYPE_ASSUMED` | warning | assumed-group cached type used | hints | `The object class of the new '%s' was assumed from its palette group, not learned from the map.` |
| `W_DISPUTED_ID` | warning | new object whose id is in `disputed` | stock table | `The id of '%s' differs between the two source tables on %s; check it in the game.` |
| `W_UNKNOWN_TYPE_KEPT` | warning | imported object with an id not in the map table, unchanged, only when `keep_unrecognised_imported` is set (otherwise `E_OBJ_NOT_STOCK`, DEC-7.4) | stock table | `Object '%s' has an id (0x%04X) this tool does not know on %s; it was kept exactly as imported.` |
| `W_QUOTA_MAX_RAISED` | warning | `ExportOptions.raise_quota_max` is on and a quota row's new `placed` would exceed its `maximum` (one warning per raised row; D11, interface freeze v2) | quota rows | `Quota maximum raised: unverified. Palette entry %d (%s) now has %d placed; its maximum was raised from %d to %d. Whether the game honours the file's maximum or rebuilds it from the scenario is unknown.` |
| `I_BUDGET` | info | always | 5.8 | text in 5.8 |
| `I_PALETTE` | info | always | 5.8 | text in 5.8 |
| `I_UNVERIFIED` | info | always | 5.8 | text in 5.8 |
| `I_HASH_ZERO` | info | the template's SHA-1 field is 20 zero bytes, so 20 zero bytes were written (2.7) | hashing | `The template carries no SHA-1 (20 zero bytes, which KSoft.Blam documents for MCC-written game variants); none was written.` |

`E_SHAPE_RANGE` has two conditions and one pattern (for a dimension). A shape kind outside 0..3 uses the sentence `Object '%s': the shape must be 0 (none), 1 (radius only), 2 (cylinder) or 3 (box) (got %d).` The dimensions named in the pattern are `radius` (shapes 1 and 2), `width`, `length`, `top` and `bottom`, and only the dimensions the shape uses are checked.

The first block of problems (`E_NO_TEMPLATE`, `E_TEMPLATE_CORRUPT`, `E_TEMPLATE_UNREADABLE`, `E_MAP_UNKNOWN`, `E_CONTAINER_SHAPE`, `E_TOO_MANY`) is reported even if per-object checks also fail.

### 7.4 Two-tier object type rule and cached types

**Tier 1 (imported objects keep their type verbatim).** An object's type is given by `type_name` (the instanced palette collection's name) or, when `type_name` is empty (model-less imported objects), by `type_id_hint` (the id stored at import). A valid claimant of slot `s` whose `type_name` equals the display name of the template slot's type (or equals the template's `"Unknown (0x....)"` string), or whose `type_name` is empty and `type_id_hint` equals the template slot's id, keeps the slot's `folder` and `item` bits verbatim: they are not re-derived from the name, so objects whose names the tables cannot round-trip (same-name entries, the two disputed table regions) still export unchanged.

**DECISION DEC-7.4:** tier 1 does not exempt an imported object from the stock rule. An imported object whose id is not in `stock_objects[map]` is refused with `E_OBJ_NOT_STOCK` (`NOTES.md` D4: "stock objects only (every object id must exist in the stock palette for that map)", re-read in the revision pass). If the owner ticks "Keep objects this tool does not recognise" (`ExportOptions.keep_unrecognised_imported`, scene property `keepUnrecognisedObjects`, default off), the error becomes the warning `W_UNKNOWN_TYPE_KEPT` and the object is exported unchanged. Rationale: the id tables were never checked against a real file (R5), so the refusal can be a false alarm; `verify_mvar` lists unresolved ids so that the owner can correct `data/*.json` or tick the box knowingly. This narrows the literal wording of binding decision E ("ids that came from the imported file are kept verbatim") in the unrecognised-id case only: ids that are in the table are still kept verbatim.

**Tier 2 (new and retargeted objects).** `type_name` is looked up in the map's display-name table (unique per map) to get `(folder, item)`; the id must be in `stock_objects[map]`; `folder < quota_count`; for a retarget the learned class equals the old class (`E_RETARGET_CLASS`). Failure gives `E_OBJ_NAME_UNKNOWN`, `E_OBJ_NOT_STOCK` or `E_FOLDER_RANGE`. The Blender Add menu offers only the names available on the template's map (8.6) so that the common failure never occurs.

**Learned cached type (new objects).** `learn(folder, item)` = the unique `cached_type` among template slots with the same `(folder, item)`; else the unique one among slots with the same `folder`; else none. If none: if the palette group of the display name (`palette_tree.json`) is in `cached_type_hints.assumed_zero_groups` (`Structure`, `Scenery`) the class is **0 with `W_CACHED_TYPE_ASSUMED`** (`I`, from the `ForgeObject.cs` comment "0: props ... everything"; unverified); otherwise `E_CACHED_TYPE_UNKNOWN`. Learned placement byte, team and colour for the new object use the same lookup (5.6).

### 7.5 Quota rules

For each folder the library computes `new = old + delta` (5.4). Refused: `new > maximum` (and `new > old`), `new < minimum` (and `new < old`), `new > 255`. **Option `raise_quota_max` (D11, default off):** when it is on, the `new > maximum` case is not refused: the row's `maximum` is raised to `new` (never lowered; `minimum` is never touched) and `W_QUOTA_MAX_RAISED` names the row, the old and the new maximum; `new > 255` is still `E_QUOTA_RANGE` and `new < minimum` is still `E_QUOTA_MIN`. The raised rows appear in `stats['quota_changes']`. A template row that already violates its own range is not an error until an edit makes it worse. Deleting objects of a folder whose `minimum` is above the new count is refused (this is conservative and `U` against the game).

### 7.6 What is validated where

| Check | Library (`export_map_variant`) | Glue | Tools |
|---|---|---|---|
| container, version, walk, hypotheses | yes | maps exceptions to reports | `verify_mvar` |
| stock map, object rules, quota, bounds, capacity, ranges, orientation gate, flags | yes | passes inputs | |
| identity matching, imported slots, deletions | yes | supplies `imported_slots`, tokens | |
| hidden objects, array instances and unevaluated array parents, mirrored transform, scene template presence/checksum | | yes | |
| target path policy | `io.write_atomic` | calls it | `reencode_mvar` |
| repo has no game files | | | `check_no_game_assets` |

---------------------------------------------------------------------------------------------------

## 8. Blender integration plan, file by file

Target: Blender 5.2.1 LTS, Python 3.13.13, macOS arm64. Baseline code: `Blender (Download a Release, Not Me!)/forge.py` v0.9.9.2 (maintained, runs on 5.2.1 `blender-5-2.md` section 1), moved into the `Addon/` package layout. `Addon/mjolnir.py` v1.0.0 (2024) is older, cannot be enabled on macOS (its `cdll.LoadLibrary` runs at import) and is replaced, not merged from. The earlier regression scripts in the session scratchpad (`blender_tests/`: `t07_mock_roundtrip.py`, `t13_ui_draw_mock.py`, `t16_650.py`, `run_suite.sh`) are reference material only: the B-xx tests of 9.4 supersede them, they are not copied into the repo and belong to no gate.

### 8.1 Files

| Path | Status | Content |
|---|---|---|
| `Addon/__init__.py` | rewrite | `bl_info` (legacy dev loop only), relative imports, `register()`/`unregister()` that call the module functions below. No `sys.path` edit, no `import mjolnir` side effects |
| `Addon/blender_manifest.toml` | new | extension manifest (8.10) |
| `Addon/mjolnir.py` | rewrite from `forge.py` | property groups `ForgeObjectProps`, `ForgeCollectionProps`, `ForgeSceneProps`; object creation; `apply_record()` / `to_export_object()` (the former `FromForgeObject`/`ToForgeObject`); panels; Add menu classes; `ConvertForge`, `SetupArray`, `ScaleObjects`, `ErrorMessage`; overlay; `spawnSeqToScale`; menu hooks. Removed: everything in 8.13 |
| `Addon/provider.py` | new | `get_provider()` / `set_provider()`; the provider is a module-like namespace with the names of `mvarlib.api` (`load_map_variant`, `export_map_variant`, `ExportObject`, `ExportOptions`, `ReadOptions`, the error classes re-exported from `errors.py` such as `MvarError`, and the helpers `map_name_for_id`, `stock_object_names`, `palette_tree`, `check_output_path`, `write_atomic`). The default returns the add-on's own `mvarlib.api`; tests inject the stub. **The glue builds `ExportObject`/`ExportOptions` through the provider (`P = get_provider(); P.ExportObject(...)`) and never imports the api types itself, and never uses `isinstance` on them**, so a stub carrying its own copy of the dataclasses works (6.4) |
| `Addon/state.py` | new | scene state helpers: `get(scene)`, `set_from_load(scene, data, load_result, source_path)`, `clear(scene)`, `template_bytes(scene)`; the only code that touches `scene['mjolnir*']` |
| `Addon/palette.py` | new | lazy library link, `find_collection(name)`, static palette tree menu, per-map filtering, the `load_post` relink handler (8.6) |
| `Addon/io_ops.py` | new | `IMPORT_OT_mjolnir_mvar` (`import_scene.mjolnir_mvar`), `EXPORT_OT_mjolnir_mvar` (`export_scene.mjolnir_mvar`), `MJOLNIR_FH_mvar` (`FileHandler`), the File menu hooks, `collect_export_objects()` |
| `Addon/objects.py`, `Addon/TwoWayDict.py` | keep | `objects.py` switches to `from .TwoWayDict import TwoWayDict`; after G0 it is used only by `tools/gen_stock_tables.py` and the sync test (the glue resolves names through the provider helpers `stock_object_names` and `map_name_for_id`) |
| `Addon/parse_palette.py` | excluded from the package | dev tool with a hard-coded Windows path |
| `Addon/Resources/ForgeBridge.dll` | stays in the repo (upstream file, untouched), **excluded from the package** | |
| `Addon/Resources/Halo Reach.blend` | unchanged, tracked upstream file | Microsoft/343 models and textures inside (385 meshes, 205 packed images); never copied, re-saved or re-exported by any tool, and not part of the default package (8.10) |
| `Addon/mvarlib/**` | new | section 6 |
| `tests/blender/*.py`, `tests/stubs/stub_mvarlib.py` | new | section 9 |

### 8.2 Registration contract (`Addon/__init__.py`)

`register()` order: `mjolnir.register()` (classes, `Object/Collection/Scene.forge` pointers, menu hooks, overlay handler unless `bpy.app.background`), `palette.register()` (`load_post` handler), `io_ops.register()` (two operators, the `FileHandler`, `TOPBAR_MT_file_import/export` hooks). `unregister()` reverses it and removes every handler, hook, pointer property and class; calling `register()`/`unregister()` three times leaves exactly one File > Import entry and one Export entry and no residue (the existing t14 test pattern).

**register() must not**: touch `bpy.data` or `bpy.context.scene` (during enable at startup `bpy.data` is `_RestrictData`: re-verified `S` with a probe extension enabled by `--addons bl_ext.user_default.<id>`, `libraries` and `context.scene` both raise `AttributeError`); call any `bpy.ops` operator; start a thread; use the network or `webbrowser`; link a library; read big files. The only I/O allowed is reading small static JSON lazily on first use.

### 8.3 State kept in the `.blend`

No `bpy.app.driver_namespace` (wiped on every file load, `blender-5-2.md` A3), no module state that matters beyond rebuildable caches.

**Scene keys (DEC-8.3):**

| Key | Type | Content |
|---|---|---|
| `scene['mjolnir_template']` | **bytes**, top level | the imported file, verbatim (29,481 bytes for plain4). Top level because bytes inside a nested dict were not tested; a top-level 29,481-byte value survives `save_as_mainfile` + `open_mainfile` in 5.2.1 (`crit_plan/x1_idprops.py`, reproduced by the critique) |
| `scene['mjolnir']` | dict | `template_sha256` (str), `source_name` (basename), `source_path` (str), `map_id_hex` (str, `'0x%08X'`), `map_name` (str, '' if unknown), `labels` (list of str, **original case**, index = file entry index), `label_present` (list of 0/1), `bounds` (6 floats), `quota_count`, `version`, `occupied_at_import`, `imported_slots` (list of ints), `failed_slots` (list of ints), `hash_flavour` (str), `hypothesis` (dict of str/int/bool/list), `addon_version`, `mvarlib_version` |

Blender integer custom properties are **32-bit**: `2**31` raises `OverflowError` (`x1_idprops.log`; re-probed on 5.2.1 in the revision pass: `0xFFFFFFFF` raises, `10070` works, `S`). The header `mapID` is a u32 and import is permissive about unknown maps, so **no u32 value is stored as an int**: the map id is stored as `map_id_hex`, and the palette CRC and the budget words stay inside the template bytes; nothing 64-bit is stored as an int (header ids stay inside the template bytes). Everything left in the dict fits in 32 bits. A list that mixes `str` and `int` items raises `TypeError` (probed): such data is stored as a dict or a JSON string.

**Object custom properties** (plain custom props, not a registered group): `isForgeObject` (bool, existing marker), `mj_slot` (int), `mj_raw` (**bytes**), `mj_raw_bits` (int), `mj_parent_slot` (int, -1 none), `mj_name` (str). A bytes custom property of 19 bytes with an embedded NUL round-trips (`x1`); a slot is at most 235 bits = 30 bytes.

### 8.4 Import operator (`import_scene.mjolnir_mvar`)

`class IMPORT_OT_mjolnir_mvar(Operator, ImportHelper)`: `bl_label = "Halo Reach Map Variant (.mvar)"`, `bl_options = {'REGISTER', 'UNDO'}`, `filename_ext = ".mvar"`, `filter_glob: StringProperty(default="*.mvar", options={'HIDDEN'})`, `replace_existing: BoolProperty(default=True)` (**DEC-8.4**: replacing is the default because one scene holds exactly one template), plus `directory`/`files` for drag and drop (5.2.1 API in `blender-5-2.md` section 7). `invoke()` opens the file browser, or `execute()` directly when `filepath` is already set (drag and drop). When `state.get(scene)` exists and `replace_existing` is true, `invoke()` first calls `context.window_manager.invoke_confirm(self, event, message="Replace the map variant already in this scene? Imported objects, including edits, are deleted. Undo is available.")`; headless tests call `execute()` with `filepath=` and are not affected.

`execute()`:
1. Read the file; refuse above 1 MiB (`This does not look like a map variant (file too large).`).
2. `P = get_provider(); P.load_map_variant(data, name)`; `except P.MvarError as e` -> `self.report({'ERROR'}, str(e))`, `CANCELLED` (nothing was created). Any other exception: report `Unexpected error: ...`, print the traceback, `CANCELLED`.
3. If the scene already holds a map variant: with `replace_existing` delete the previously imported objects (those with `mj_slot`) together with their helper children (the `Shape` child named in `forge.shapeObject`, the loadout-camera child) and replace the state; without it, `CANCELLED` ("This scene already contains a map variant; tick Replace Existing or use a new scene"). User-made forge objects (no `mj_slot`) are never deleted.
4. `palette.ensure_palette()`; failure is a WARNING and objects import as arrow empties.
5. `state.set_from_load(...)` (template bytes + SHA-256 + info) **before** creating objects (labels are needed by the enum).
6. For each `ObjectRecord`: `try: create_object(rec) except Exception as e: failed.append((rec.slot, str(e)))`. `create_object` = port of `createForgeObject` + `apply_record`: Empty named `"%d - %s" % (slot, type_name)` in the active collection; `isForgeObject`; `mj_*` props; palette instance if `palette.find_collection(type_name)` else arrow empty; `matrix_world` columns `(forward x up, forward, up, position)`; then the property values with `obj.scale` set directly for objects whose label text upper-cased is `SCALE`; the loadout-camera child for "Initial Loadout Camera".
7. `imported_slots` = successes, `failed_slots` = failures (kept in state; a failed slot is never treated as deleted at export, 5.5).
8. Report: `INFO Imported %d objects from %s (%s, %d of 650 slots used)`; if any failed, `WARNING %d objects could not be imported (see console); they will be left unchanged on export`; library warnings summarised.

A failed import of an *individual* object (the former KeyError/TypeError cases) can no longer abort the whole import: the former crash sites are removed by 8.7 and wrapped by the per-object `try`.

### 8.5 Export operator (`export_scene.mjolnir_mvar`)

`class EXPORT_OT_mjolnir_mvar(Operator, ExportHelper)`: `filename_ext = ".mvar"`, `check_extension = True`, `check_existing = True`, `force_reencode: BoolProperty(default=False)` ("Diagnostic: rewrite the whole stream"), `fsm_policy: EnumProperty(KEEP, DROP)`, `hash_policy: EnumProperty(REPRODUCE, SALTED_BE32, PLAIN_LE32; default REPRODUCE, labelled Advanced)`. `draw()` shows the three options, `context.scene.forge.allowUnverifiedRotation`, `context.scene.forge.keepUnrecognisedObjects`, and a one-line note about what is checked. `invoke()` proposes `<source dir>/<source stem>_mjolnir.mvar`, or the fallback folder of 2.13 when the source directory is a protected folder.

`execute()` (the operator changes no scene object):
1. `st = state.get(scene)`; none -> `E_NO_TEMPLATE`. SHA-256 of `scene['mjolnir_template']` must equal `st['template_sha256']` else `E_TEMPLATE_CORRUPT`.
2. Path policy pre-check (2.13) through `P.check_output_path(target, [st['source_path']])`: same file as `st['source_path']` -> `E_PATH_SAME_AS_SOURCE`; protected folder -> `E_PATH_PROTECTED`.
3. `objs = collect_export_objects(scene)`:
   - **Pass B (array instances) runs first:** `depsgraph.object_instances` where `inst.is_instance` and the source `inst.object.original` has `isForgeObject` and is an array source (a forge object whose parent has `instance_type` `FACES` or `VERTS`). Instances of one source are numbered in iteration order; instance 0 carries the source's `mj_slot`/token, the others are new objects (`slot = None`, `from_array = True`). Works for model-less arrow empties too (the former `is_instancer` test made them vanish, `addon-architecture.md` defect 6). The set `seen_sources` collects every array source that has at least one instance.
   - **Pass A (plain objects):** `for ob in scene.objects` (this includes eye-hidden, `hide_viewport` and excluded-collection objects; it does not depend on the evaluated depsgraph) where `ob.get('isForgeObject')` and `ob` is not in `seen_sources`. An array source that is **not** in `seen_sources` is not exported as a plain object: the export is refused with `E_ARRAY_NOT_EVALUATED` and nothing is written. Reason, probed on Blender 5.2.1 (`S`): the depsgraph yields 3 of 3 instances for a visible FACES array but none when the array parent is eye-hidden, `hide_viewport` or in an excluded collection, although all those sources remain in `scene.objects`; without this rule pass A would skip the source, pass B would never see it, its slot would have no claimant and rule 3 of 5.5 would silently delete the imported object. Transform from `ob.matrix_world`; forward = column 1 normalised, up = column 2 normalised; negative determinant of the 3x3 -> `E_MIRRORED`. Hidden = `ob.hide_get() or ob.hide_viewport`.
   - Fill `ExportObject` from the properties: `type_name` = `instance_collection.name` with a trailing `.NNN` removed (always `.name`, never `.name_full`), or `''` with `type_id_hint = forge.objectType`; `physics` from the enum (NORMAL 0, FIXED 1, PHASED 3); `symmetry` (BOTH 3, SYMMETRIC 2, ASYMMETRIC 1, NEITHER 0); `team` enum -> 0..8; `color` TEAM_COLOR -> -1, RED..PINK -> 0..7, NEUTRAL -> 8 (refused by the library); `label_index` from the label enum (`'NO_LABEL'` -> -1, `'L<i>'` -> i); dims and the rest straight from the properties; `token_raw/token_bits` from `mj_raw/mj_raw_bits`; `name_matches_import = (ob.name == ob['mj_name'])`.
4. `P = get_provider(); result = P.export_map_variant(template, objs, P.ExportOptions(allow_unverified_rotation=scene.forge.allowUnverifiedRotation, keep_unrecognised_imported=scene.forge.keepUnrecognisedObjects, force_reencode=self.force_reencode, fsm_policy=self.fsm_policy, hash_policy=self.hash_policy, imported_slots=list(st['imported_slots'])))`.
5. Write the **report** (always; **DEC-8.5**: a text datablock because the Info area shows only one line): a text datablock `Mjolnir Export Report` (replaced each time) and the console: one line per `DiffEntry` (`KEPT/MOVED/EDITED/RETARGETED/ADDED/REMOVED/NOT IMPORTED slot N "name" detail`), all errors and warnings with their codes, the budget/palette/unverified notes of 5.8, hashing and stats (occupied before/after, bits used of 229,376, L, flavour).
6. `not result.ok` -> `self.report({'ERROR'}, "Export refused: %d problem(s); first: <message>. See the text 'Mjolnir Export Report'.")`, `CANCELLED`, nothing written.
7. `P.write_atomic(...)` (2.13) with the verify step; `self.report({'INFO'}, "Exported %s: %d kept, %d moved, %d added, %d removed.")`; warnings as `WARNING` lines.

Silent truncation is gone: more than 650 occupied slots is `E_TOO_MANY` (the former behaviour dropped the extras and said "Exported 650").

### 8.6 Palette: lazy link, static menu, relink

**Never link in `register()`** and never link in `load_post` (it would tie every `.blend` the user opens to a 57 MB library). Linking happens inside operators: Import, `AddForgeObject.invoke/execute`, and `ensure_palette()` called by `SetupArray`/shape creation when a collection is needed.

```python
WANTED = ("Forge World Palette", "Shape Models")
def ensure_palette() -> bool:
    if _already_linked(): return True
    path = library_path()              # preference library_path -> $MJOLNIR_LIBRARY -> <package>/Resources/Halo Reach.blend (dev loop / --with-library only)
    if not os.path.isfile(path): return False
    with bpy.data.libraries.load(path, link=True, relative=False) as (df, dt):
        dt.collections = [n for n in WANTED if n in df.collections]    # collections only, not scenes
    return True
```
With no library found (`os.path.isfile` false), `ensure_palette()` returns False and Import reports the WARNING "Palette library not found. Set Preferences > Add-ons > Halo: Mjolnir Forge Editor > Library path. Objects were imported as arrow empties." The default package does not carry the library (8.10), so on a normal install the preference or `$MJOLNIR_LIBRARY` is how it is found; it is linked in place and never copied.

Verified behaviour (`crit_plan/x3`, a synthetic stand-in library): only the requested collections arrive (no scene, so no 234-object Forge World backdrop, which the old `TryLinkBlendData` dragged into every user file); a second call creates no duplicates; the linked collection's `.name` is `Block, 1x1` while `.name_full` is `Block, 1x1 [Halo Reach.blend]` (use `.name`); after `save_as_mainfile` the library path is stored relative; if the library moves, `is_missing` is true and `instance_collection.objects` is empty, and `lib.filepath = new; lib.reload()` repairs it. The measured cost of linking the real library is 0.5 to 0.7 s once (`blender-5-2.md` section 6).

- `find_collection(name)`: among `bpy.data.collections` prefer one whose `library` is set and whose library file basename is `Halo Reach.blend`; fall back to a local collection of that name (a user who appended). Never `bpy.data.collections[name]`.
- **Static tree:** `mvarlib/data/palette_tree.json` (names only, generated by `tools/gen_palette_tree.py`) drives the Add menu and the search popup. `AddForgeObjectMenu.draw()` and `addForgeObjectMenuItem()` read only that JSON (and the scene state for filtering), so drawing never touches `bpy.data` and the former `KeyError` before the first import cannot occur. Icons come from a hand-written name -> icon map validated against the 5.2.1 icon enum (the stored numeric `forge.icon` indices drift across Blender versions and resolve to wrong icons today, `blender-5-2.md` B2; GUI-verification of the icons is manual, 9.6).
- **Per-map filter:** when the scene has a map variant, a leaf is shown iff its display name is in `stock_objects[map_name]`; otherwise (no template) the whole tree is shown with the label "Import a map variant to filter by map". The 194 modelled leaves are the only Add-menu entries; stock objects without a model (weapons, vehicles, spawn camera, boundaries, zones) are added by duplicating an imported object.
- **Relink handler:** `@persistent def _on_load(_)` appended to `bpy.app.handlers.load_post` in `register()`, removed in `unregister()`: for each `bpy.data.libraries` entry whose basename is `Halo Reach.blend` and whose resolved path does not exist, set `filepath` to `library_path()` and `reload()`; all wrapped in `try/except`. It never links anything new. Required because for an extension the library path contains the per-Blender-version profile directory, which an upgrade strands.

### 8.7 Property-group and behaviour changes (the fix list)

Everything below was found by running the existing code on 5.2.1 (`addon-architecture.md` sections 3 and 7). Each row is a G4 deliverable with a test id in section 9. **DEC-8.7:** two enum items are added to existing properties so that real data is representable instead of crashing or being flattened: `SPHERE` in `shape` and `NEITHER` in `symmetry`.

| # | Defect in the current add-on | Fix | Test |
|---|---|---|---|
| 1 | `ToForgeObject` uses `coll.name_full`; a linked palette makes every export raise `KeyError` | type resolution uses `.name` and the library's per-map table; `GetObjectTypeId` and the global `type_to_name.BtoA` ("Sprint" collision) are gone from the glue | B-07 |
| 2 | `UpdateSpawnSeq` rescales `context.selected_objects`, so import ignores scale when anything is selected | `UpdateSpawnSeq`/`UpdateScale` act on `self.id_data`; import sets `obj.scale` directly | B-06 |
| 3 | `scaleConvention` default is index 2 = `71X` although `47X*` is documented | `default='47X'` (identifier) | B-06 |
| 4 | `team == 255` -> `TypeError`; unknown/odd flags -> `KeyError`; one bad object aborts the whole import | library views give `team` -1..8, `color` -1..7, `physics`, `symmetry` 0..3 (new enum item `NEITHER`); per-object `try/except` with a failed-slot list | B-05 |
| 5 | width/length/top/bottom clamp at 100.9 while the file allows 200; spawn sequence -100..100 vs a signed byte | hard range 0..200 and -128..127 (soft limits 100.9 and -100..100 keep the old slider feel) | B-05 |
| 6 | shape code 1 flattened to NONE | new enum item `SPHERE` (radius = `width`; shape child is an Empty with `empty_display_type = 'SPHERE'`, no model) | B-05 |
| 7 | flags bits 0/4 and `spawnRelativeToMapIndex` dropped; export rebuilds the byte from scratch | the library keeps the raw placement byte and the parent link; only physics is editable (3.9) | B-08 |
| 8 | Gametype labels are upper-cased, stored as a positional dynamic-enum value, session-global | labels live in `scene['mjolnir']['labels']` in original case; enum items `'NO_LABEL'` and `'L<i>'` with the label text as display name; `SCALE` detection is `text.upper() == 'SCALE'`; items callback returns a module-level list (string lifetime, `blender-5-2.md` B3) | B-05 |
| 9 | `forge.object` stores the object's own name; breaks on duplicate and rename | `self.id_data` everywhere | B-09 |
| 10 | hidden objects are silently not exported; array copies of model-less empties vanish; >650 silently truncated | pass B (array instances) first, pass A over `scene.objects` for everything else, unevaluated array parents refused with `E_ARRAY_NOT_EVALUATED`, `E_TOO_MANY` | B-10, B-11 |
| 11 | `AddForgeObject` offers all 194 leaves on every map; Add menu raises `KeyError` before the palette exists | static tree + per-map filter | B-04 |
| 12 | `Convert To Forge Object` exports type 0 = Assault Rifle | export refuses an object with no resolvable type (`E_OBJ_NO_TYPE`) | B-12 |
| 13 | `ForgeObjectFlags` has trailing commas (1-tuples), `PhysicsMask` aliases `PhysicsPhased` | removed; the glue uses the library's `physics`/`symmetry` ints | B-05 |
| 14 | `ErrorMessage` operator invoked from `register()`; `rl=` typo | removed; `ErrorMessage` kept for runtime errors only | B-01 |
| 15 | `ForgeCollectionPanel` edits `collection.forge.icon` on linked (read-only) data | panel disabled when `collection.library` is set | B-13 |
| 16 | the "N / 650" overlay iterates the depsgraph every redraw and calls `blf.draw`, which segfaults 5.2.1 in background mode | handler not added and callback returns immediately when `bpy.app.background`; count cached and refreshed on `depsgraph_update_post`; whole callback in `try/except`; removed safely in `unregister()` (no `KeyError`) | B-01, B-13 |
| 17 | additive import leaves unflagged helper children | `replace_existing` deletes helpers via `forge.shapeObject` and the camera child | B-14 |
| 18 | `ForgeObjectProps.UpdateShape` looks the palette up as `bpy.data.collections['Shape Box']` | `palette.find_collection('Shape Box')` after `ensure_palette()` | B-05 |

### 8.8 UI that must be preserved

| Item | Id | Status |
|---|---|---|
| Add > Forge Object (search popup + category submenus) | operator `forge.add_object`, menu `VIEW3D_MT_add_forge_object`, hook on `VIEW3D_MT_add` | kept; data source changes (8.6) |
| Convert To (Blender / Forge) Object | `object.convert_forge`, hook on `VIEW3D_MT_object_context_menu` | kept |
| Setup Array | `object.setup_array` (REGISTER, UNDO; type CONST/OBJECT/CURVE, count 1..650, offset, rotation, size) | kept |
| Scale Forge Objects | `forge.scale_objects` | kept |
| Properties editor > Object > Forge Properties | `SCENE_PT_forge_object` | kept (labels dropdown now label text) |
| 3D View sidebar tab "Forge" | `SCENE_PT_forge_object_sidebar` | kept |
| Properties > Collection > Forge Collection | `SCENE_PT_forge_collection` | kept (read-only for linked) |
| Properties > Scene > Forge Scene | `SCENE_PT_forge_scene` | kept; **adds** the map-variant box (map, source, occupied/650, hypothesis, hash flavour), the `allowUnverifiedRotation` checkbox and the `keepUnrecognisedObjects` checkbox ("Keep objects this tool does not recognise", default off, DEC-7.4) |
| Property names `Object.forge`, `Collection.forge`, `Scene.forge` and `forge.colorIndex` | | **must not be renamed**: the shaders in `Halo Reach.blend` read `forge.colorIndex` from the instancer `blender-5-2.md`/`addon-architecture.md` section 2 |
| File > Import / Export | **was** `forge.import`, `forge.export` (live MCC memory) | **replaced** by `import_scene.mjolnir_mvar`, `export_scene.mjolnir_mvar` with the text "Halo Reach Map Variant (.mvar)" and the existing icon |
| Overlay counter "N / 650" | draw handler | kept (colours orange above 500, red above 650) |
| `forge.error` | `ErrorMessage` | kept, never invoked from `register()` |

### 8.9 Mapping of the scene to the library (summary)

```
Blender scene                                   mvarlib
-------------                                   -------
File > Import .mvar  --bytes-->  load_map_variant()  --> LoadResult(info, [ObjectRecord])
   creates Empties, mj_* props, scene['mjolnir*'] (template bytes, labels, bounds, imported_slots)
Edit in Blender (move / duplicate / delete / add / retarget ...)
File > Export .mvar  --[ExportObject]--> export_map_variant(template, objects, options)
   <-- ExportResult(ok, data, diff, errors, warnings, stats) ;  write_atomic(data) only if ok
```

### 8.10 Packaging

- **Extension (distribution):** `Addon/blender_manifest.toml`:
```toml
schema_version = "1.0.0"
id = "mjolnir_forge"
version = "1.0.0"
name = "Halo: Mjolnir Forge Editor"
tagline = "Import and export Halo: Reach map variants"
maintainer = "OWNER NAME <owner@example.com>"      # to be filled by the owner; build_package.py refuses to build while it holds a placeholder
type = "add-on"
blender_version_min = "5.2.0"                      # only 5.2.1 is tested
license = ["SPDX:GPL-3.0-or-later"]                # PLACEHOLDER: the upstream repo declares no licence; the owner must confirm (DEC-8.10)

[permissions]
files = "Read and write map variant files chosen by the user"

[build]
paths_exclude_pattern = ["__pycache__/", "*.pyc", "Resources/ForgeBridge.dll", "parse_palette.py"]
```
Verified `S`: `blender --command extension build --source-dir <dir> --output-dir <existing dir> < /dev/null` honours `paths_exclude_pattern` (the DLL, `parse_palette.py` and `__pycache__` were dropped, `Resources/Halo Reach.blend` was kept in that experiment, the default build excludes it, DEC-8.10); the output directory must already exist; stdin must be closed. The zip has the manifest at its root and the add-on files next to it (`__init__.py` at the root: a legacy `addon_install` rejects this layout, `extension install-file` accepts it). Installed id: `bl_ext.user_default.mjolnir_forge`.
- **Build script** `tools/build_package.py --out DIR [--with-library --i-accept-that-this-copies-game-assets] [--allow-placeholders]` (**DEC-8.10**): refuses a `DIR` inside the repo working tree (checks the git top level); stages a copy of `Addon/` in a temp dir outside the tree; runs `blender --command extension validate <stage>` then `extension build`; prints size and SHA-256. **Default: the zip does NOT contain `Resources/Halo Reach.blend`** (about 100 KB), so no Microsoft/343 asset is copied anywhere (hard rule, 0.2). The add-on finds the library, read in place and never copied, through the add-on preference `library_path` (an `AddonPreferences` class, `bl_idname = __package__`), `$MJOLNIR_LIBRARY`, or `<package>/Resources/Halo Reach.blend` (present only in the dev loop, where `Addon/` is symlinked into the profile, and in a `--with-library` build). `--with-library` exists only for the owner's own machine, additionally requires `--i-accept-that-this-copies-game-assets`, prints that the output must never be shared, committed or uploaded, and is used by no test, no gate acceptance and no T4 instruction. With no library found, `ensure_palette()` returns False and Import reports the WARNING of 8.6. The build fails while the manifest contains `example.com` or `OWNER` ("fill maintainer and licence first"); `--allow-placeholders` exists for the tests and the headless suite (`extension validate` itself accepts the placeholders, verified `S`).
- **Where the 57 MB blend lives:** `Addon/Resources/Halo Reach.blend`, already tracked upstream (sha256 `a76e1d74...e6ad`); `forge.blend` is not part of the package. `.gitignore` already excludes `dist/`, `build/`, `*.zip`, `*.mvar`; `tools/check_no_game_assets.py` fails on anything new of that kind and scans gitignored files too (DEC-F.2).
- **Legacy dev loop:** `bl_info` stays in `__init__.py` so `Addon/` can be symlinked into `$BLENDER_USER_RESOURCES/scripts/addons/mjolnir_forge`; `extension validate` and `extension build` accept a manifest next to `bl_info` (verified `S` in the revision pass), so nothing is stripped from the staged copy.
- **Offline:** no network permission; the update checker is gone.

### 8.11 Background-mode guards (headless tests and CLI use)

`blf.draw` segfaults 5.2.1 in `-b` (exit 139, `blender-5-2.md` section 2): never call it, never add the handler, when `bpy.app.background`. `INVOKE_DEFAULT` in `-b` falls through to `execute` with an empty `filepath`: tests always pass `filepath=`. `ImportHelper.invoke` in 5.2.1 always opens the browser even when `filepath` is preset: override `invoke` as in the `FileHandler` example. `blender.crash.txt` may be written to the system temp directory by a crash; ignore it.

### 8.12 `FileHandler`

`class MJOLNIR_FH_mvar(bpy.types.FileHandler)`: `bl_idname = "MJOLNIR_FH_mvar"`, `bl_label = "Halo Reach Map Variant"`, `bl_import_operator = "import_scene.mjolnir_mvar"`, `bl_export_operator = "export_scene.mjolnir_mvar"`, `bl_file_extensions = ".mvar"`, `poll_drop(cls, context)` true in the 3D viewport. Registers and unregisters cleanly (`blender-5-2.md` section 7); actual drag and drop needs a GUI (9.6).

### 8.13 What is removed

The ctypes `float3`/`ForgeObject` structures and `from ctypes import *`; `dllPath`, `cdll.LoadLibrary`, every `forge.*` call (`TrySetConnect`, `ReadMemory`, `GetMapName`, `GetObjectPtr`, `AddObject`, `WriteMemory`, ...), `GetDllVersion`; the update-check thread, `urllib.request`, `webbrowser`, `githubURL`, `check_update`, `vMjolnir` network comparison; `bpy.ops.forge.error(...)` calls inside `register()`; `bpy.app.driver_namespace` (`persist_vars`, `gtIndexToLabel` globals, `forge_show_warning`, the draw-handler key); the `sys.path.append(cur_dir)` hack and `import mjolnir` side effect in `__init__.py`; the module-level `try: unregister() ... register()` tail; the confirmation dialog about "MCC's RAM"; unguarded `blf.draw`; `ConvertForge`'s silent type-0 export; the old `forge.import`/`forge.export` operators. The repo directories `ForgeLib/`, `ForgeConsole/` and `Mjolnir.sln` stay untouched (Windows tooling) and are simply not packaged.

---------------------------------------------------------------------------------------------------

## 9. Test plan by tier, with exact commands

### 9.1 The four tiers (binding decision A) and what each proves

| Tier | Input | Must hold | Proves | Does **not** prove |
|---|---|---|---|---|
| **T1** | the 8 real game-variant `.bin` files (5 distinct contents; `rvt-test-samples/` and `ReachVariantTool-core-library/macos/Fixtures/`) | through the **same generic `BlfFile` code path** an `.mvar` uses: parse -> unmodified `to_bytes()` equals the input; **forced** rebuild (sizes, embedded fileLength, hash, `_eof`, chdr fileLength recomputed) equals the input; the shared UGC header decodes and re-encodes identically at bit offset 68 (as in `mpvr`) **and** at offset 0 (as in `mvar`); the recomputed hash equals the stored one; string-table recompression equals the original (the 4 compressed tables among the 5 distinct contents) | container, hash, header codec, bit I/O, zlib determinism | any `mvar` field |
| **T2** | synthetic `.mvar` fixtures produced by the **independent fixture builder** (separate module, table-driven, shares no helper with the codec; includes holes in the 651 slots, extreme values, a 0-label table, compressed and uncompressed label tables, v31 and v32, `_cmp` and `_fsm` wrappers, both type-19 rules, both hash flavours plus the all-zero hash, both length byte orders, the header conditionals and text extremes, a zero-range axis, 650- and 651-object files, an unknown map id, a GUID/version mismatch) | unmodified save == input; forced re-encode == input (for `_cmp` shapes the golden expanded file, DEC-2.6); a single edit changes only the expected bits (the bit-diff contract of 5.9); W1 golden edits reproduced byte for byte | internal consistency of the body codec against an independently written description of the same spec | agreement with MCC; correctness of the spec's single-source facts |
| **T3** | a real `.mvar` that **the user** supplies, `python3 -I tools/verify_mvar.py FILE` | prints the decode report of 6.7, writes no game data, **exits non-zero on desync** | the first and only real-format check of framing, widths, hypotheses, hash flavour, id resolution | edit semantics |
| **T4** | a manual ladder the user runs in MCC (9.5) | no-op re-save loads; one object moved; one added; one deleted | game acceptance | n/a |

**Non-circularity rule (DEC-9.2).** The T2 fixture builder (`tests/fixturebuilder/`) must not import `mvarlib`, must carry its own bit writer (a different technique: big-integer accumulation versus the library's masked-byte writer), and must take its widths, orders and constants from a literal table copied from sections 3 and 4 of this document. A unit test scans `tests/fixturebuilder/*.py` for `import mvarlib` and for `from ..Addon` and fails on a hit. The builder ships a second, separate *self-check walker* so a typo in the builder is caught before it can mask a codec bug. The reference fixture **W1** (Appendix C) was built and parsed this way during the writing of this spec and fixes concrete byte values: the G2 builder must reproduce them. An optional third oracle, U-23, runs Cobb's own JS parser (via `node`, when installed) on W1 and compares header fields, bounds, labels, slot folder/item/cells and quota rows; it catches implementation slips only, never the spec's single-source claims, and nothing from the GPL file is copied or vendored.

**Honest limit of T2:** if this spec is wrong about the file format, the builder and the library are wrong in the same way and T2 stays green. Only T3 on a real file can detect that.

### 9.2 Environment and drivers

```bash
REPO=~/Documents/Halo_MCC/mjolnir-forge-editor/source
BL=/Applications/Blender.app/Contents/MacOS/Blender               # Blender 5.2.1 LTS
PY39=/usr/bin/python3                                              # must report 3.9.x; run_tests.sh aborts otherwise (PATH order is not trusted: /opt/homebrew/bin/python3 is 3.14.7 here)
PY313=/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13   # 3.13.13, zlib 1.3.1 (verified to run with -I)
```
`python3 -I` removes the script directory and the working directory from `sys.path` (isolated mode), so every driver inserts the repo paths itself.

```bash
cd $REPO
$PY39  -I tools/run_tests.py --samples          # T1 + T2 + CLI + guards, system Python 3.9
$PY313 -I tools/run_tests.py --samples          # same suite on Python 3.13
tools/run_tests.sh                              # both interpreters + check_no_game_assets + the 3.9 import and lint scan
```
`tools/run_tests.py` options (**DEC-9.3**: the sample files are found at their two known folders, or in `$MJOLNIR_SAMPLES` if set, and are never copied): `--samples` (T1 needs the real sample files: without the flag a missing sample directory SKIPS T1 with a loud notice; with the flag it is a failure), `--only SUBSTR`, `-v`, `--fixtures-dir DIR` (where the generated fixtures are written; default a fresh temp dir). It uses `unittest` only (no pytest dependency on the system Python). Fixtures are generated into a temp directory at test time and never written inside the repo (`.gitignore` ignores `*.mvar` anyway, and `check_no_game_assets.py` would fail the build). Golden data that *is* committed is JSON and hashes only: `tests/golden/*.json`.

`tools/run_tests.sh` also runs `$PY39 -I tools/check_no_game_assets.py`, the Python 3.9 import and lint scan of 6.8 (U-19), and fails if either interpreter run fails; `tools/run_tests.py` wraps the whole run in the sample-untouched check U-21. The Blender suite is driven by `tools/run_blender_tests.sh`, and `tools/accept.sh` runs the acceptance sheet of 9.8. All `tools/*.sh` start with `#!/bin/bash` and `set -o pipefail`. Directory names `bin/`, `out/`, `log/`, `build/`, `dist/` must not be used inside the repo: the existing `.gitignore` ignores `[Bb]in/`, `[Oo]ut/`, `[Ll]og/` (`git check-ignore` confirms `tests/bin/x`, `tests/out/y`, `Log/z` are ignored `S`) and the port adds `build/`, `dist/`.

### 9.3 Pure-Python test catalogue (`tests/unit/`)

`tests/` is not a package and is never on `sys.path`; each test inserts `Addon/` itself. (A package named `tests/mvarlib/` would shadow `Addon/mvarlib` whenever a runner puts `tests/` first on the path, as `unittest discover -t tests` does: reproduced `S`.)

| Id | File | Tier | Content |
|---|---|---|---|
| U-01 | `test_bitio.py` | T1 | 608-check port of `bitio_prototype.py` (random width schedules over real payloads, misaligned starts, non-multiple-of-8 totals), **masked writes never disturb neighbouring bits** (the RVT `write_to_bitpos` clobber hazard, `container-and-bit-conventions.md` 11), signed fields, strings that stop after the NUL, overrun raises, widths 0..64 (a 0-bit read consumes nothing), `write` raises `EncodeError` on a value that does not fit; the RVT-port reader/writer classes live in the test as oracles |
| U-02 | `test_blf_real.py` | T1 | the 8 files, printing `PASS <file> <sha256[:16]>` per path (9.8 row 1): chunk walk and tiling; `to_bytes() == input`; `to_bytes(force=True) == input`; flavour detection returns `('<', 'salted_be32')`, `plain_le32` does **not** match; hash recompute equals stored; a 1-bit flip in the stream breaks every candidate and restoring it matches again; `_eof` value and byte order |
| U-03 | `test_header_real.py` | T1 | decode the UGC header at payload bit 68; re-encode from fields at 68 and at 0, identical bits (lengths 1,535 / 1,183 / 2,287 / 2,271 / 2,575); a longer title shifts the remainder consistently; `chdr` parse/build byte-exact |
| U-04 | `test_labels_zlib_real.py` | T1 | locate the compressed string table of each real file that has one (scan for `78 DA` preceded by a plausible size field; a file without such a stream is skipped: `test_user_funcs_and_recursion.bin` has none, so 4 of the 5 distinct contents), recompress at zlib levels 7 to 9 and compare (expected identical on 3.9.6/zlib 1.2.12 and 3.13.13/zlib 1.3.1); the test asserts that at least 4 streams were found |
| U-05 | `test_codecs_golden.py` | pure | all of 4.10: `G-AX` (G-AX-4 zero-range axis, G-AX-6 float32-step thresholds, all three variants), `G-POS`, `G-SH`, `G-ANG`, `G-UP`, `G-ID`; property tests: `dim_encode(f32(dim_decode(v))) == v` for 0..2047; angle encode/decode; `pos_encode(pos_decode(q)) == q` whenever float32 spacing is below half a cell; up-code invalid faces |
| U-06 | `test_hashing.py` | pure | the five test vectors of 2.7; detection on W1 salted and plain; both stored-length byte orders; L = 0 handling; the `zero` flavour (detection, write-back as zeros, `hash_policy` forcing) |
| U-07 | `test_fixtures_read.py` | T2 | every fixture spec (`tests/golden/fixture_specs/*.json`): build with the independent builder, read with `mvarlib`, compare each declared field; includes the header fixtures `hdr_hopper`, `hdr_campaign`, `hdr_firefight`, `hdr_long_text`, `hdr_min_text` (golden header ends, end bits, L and SHA-1 of Appendix C.4) and `extremes` with its zero-range axis (read with `W_ZERO_RANGE_AXIS`) |
| U-08 | `test_roundtrip_forced.py` | T2 | `to_bytes() == input` for every fixture; `to_bytes(force=True) == input` for every fixture of shape `plain4` / `plain4+fsm`; for `cmp4` / `cmp4+fsm` fixtures `force=True` equals the builder's golden `<name>_expanded` file and re-parses to the same slots, labels and quotas (DEC-2.6); slot repack identity I1; plain-dict round trip; label re-encode report. Owned by G3, re-run by G5 |
| U-09 | `test_hypotheses.py` | T2 | type-19 `flag8` and `plain8` fixtures decode to the right slots under their own rule and are refused or flagged under the wrong one; a file with no type-19 object reports `undetermined`; the axis-threshold fixture (range = 2^20 x 0.000520833) yields two axis hypotheses and the end-of-walk check selects the right one; `AmbiguousLayoutError`; `DesyncError` carries per-hypothesis diagnostics; out-of-bounds (rejected under every hypothesis at the same slot -> `OutOfBoundsPositionError`; under one wrong hypothesis only -> not an error), wrong version, wrong size, content type, truncated stream, invalid L; GUID hypothesis: a v32 file without the 128 bits and a v31 file with them are both read, with `W_GUID_VERSION_MISMATCH`, and an accepted version-implied value wins over the other (no ambiguity between GUID values) |
| U-10 | `test_container_variants.py` | T2 | `_cmp` (unmodified save emits the wrapper bytes; modified save expands and re-stamps), `_fsm` kept/dropped, v32 (+128 bits), `plain_le32`, LE stored length, LE `_eof`, `plain4+fsm`, shape `other` refused on modification, trailer after `_eof` kept (`W_TRAILER_KEPT`), chunk versions 12/13/14/50/51 refused and other unexpected ones warned, `fsm_policy = DROP` on a clean `plain4+fsm` template yields the shape without `_fsm`, the all-zero hash flavour reproduced |
| U-11 | `test_edits_bitdiff.py` | T2 | W1 golden edits E1/E2/E3 equal the builder's files byte for byte; per-edit-kind bit-diff contract (5.9) for translate, yaw, tilt-to-vertical, spawn fields, team, colour, label, shape change, physics, add, delete; quota deltas; parent clearing; capacity refusal on a near-full fixture; hash and L recomputation |
| U-12 | `test_identity.py` | T2 | token match/mismatch, duplicate claimants, not-imported slots, deleted slots, new-object ordering and slot assignment determinism |
| U-13 | `test_validation.py` | T2 | every library-side `E_`/`W_` code of 7.3 triggered once, with the exact message text (codes marked glue in 7.3 are covered by the B-xx tests); both DEC-7.4 cases (an imported unrecognised id is refused with `E_OBJ_NOT_STOCK` by default and kept with `W_UNKNOWN_TYPE_KEPT` when `keep_unrecognised_imported` is set); `E_TRANSFORM_INVALID`; a moved or new object on a zero-range axis; `E_TOO_MANY` for `full650` plus one object and for `over650` unchanged |
| U-14 | `test_plain.py` | T2 | JSON round trip for all fixtures; hex fields; `from_plain` of a hand-written minimal dict builds a readable file |
| U-15 | `test_tables_sync.py` | pure | `data/stock_objects.json` equals the tables parsed (with `ast`, without executing) from `Addon/objects.py`; 20 maps; map ids; palette tree names resolve in the Forge World table |
| U-16 | `test_cli.py` | T2/T3 | `verify_mvar` exit codes: 0 on W1, 1 on a desynchronised fixture, 2 on a game variant (container report printed) and on garbage, 3 when a self-check is forced to fail; `dump_mvar`/`reencode_mvar` refuse output paths inside the repo (no exception, `scratch/` included), protected folders, symlinks to the input and `OUT == IN`, because they write through `write_atomic` |
| U-17 | `test_repo_guards.py` | pure | the independence scan of 9.1; no `.mvar/.bin/.blend/.dll` under `tests/` or `Addon/mvarlib/`; `check_no_game_assets.py` returns 1 in a temp git repo that contains a planted `.mvar` or a file starting with `_blf`, and 0 on the clean tree. **U-17b:** a second temp repo that carries a copy of the real `.gitignore` plants `tests/p.mvar`, `dist/p.zip` and `scratch/d.dat` (first bytes `_blf`), all gitignored: `git status --short` shows nothing and the guard must still exit 1 (reproduced `S`: with `--exclude-standard` the first draft's guard reported nothing) |
| U-18 | `test_io_policy.py` | pure | `write_atomic`: refuses same file (also through a symlink), protected folder, creates no `.bak`, uses temp + `os.replace`, leaves nothing behind on a failed verify |
| U-19 | `test_py39_syntax.py` | pure | (a) imports every module of `Addon/mvarlib` and `tools` under `/usr/bin/python3` (3.9.x; skipped with a notice on another interpreter); (b) runs `tests/py39_lint.py` (6.8) on every file of `Addon/mvarlib`, `tests`, `tools`, including the `ast.parse(feature_version=(3, 9))` scan; the lint's own tests feed it one bad line per forbidden construct |
| U-20 | `test_fixturebuilder_selfcheck.py` | pure | the builder's own walker agrees with the builder for every fixture spec and with W1's golden numbers (section C) |
| U-21 | `test_samples_untouched.py` | pure | also run by `tools/run_tests.py` itself around the whole run: before the first test record `(path, size, mtime_ns, sha256)` of every `*.bin` in both sample folders and of every file in the protected folders (2.13); after the last test record again; any difference fails the run and names the file. Samples are opened `rb` only, through `helpers_real.open_sample()` |
| U-22 | `test_interface_frozen.py` | pure | the SHA-256 of `Addon/mvarlib/api.py` and `errors.py` equal `tests/golden/interface_sha256.json` (the interface freeze of 6.4) |
| U-23 | `test_oracle_js.py` | T2 (optional) | skipped when `node` or Cobb's `map_variant_mvar.js` is absent or cannot be loaded; otherwise runs the JS parser on W1 and compares header fields, bounds, label strings, slot folder/item/cells and quota rows with the library |

### 9.4 Headless Blender tests (`tests/blender/`)

All Blender runs use an isolated profile so nothing touches `~/Library/Application Support/Blender`:

```bash
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/mjolnir-run.XXXXXX"); export SCRATCH   # a fresh private directory outside the repo; nothing is deleted
mkdir -p "$SCRATCH/dist"
export BLENDER_USER_RESOURCES="$SCRATCH/user_res"      # PLURAL; the singular name is silently ignored
export PYTHONUNBUFFERED=1
$PY39 -I tools/build_package.py --out "$SCRATCH/dist" --allow-placeholders   # default package: no game asset inside (8.10)
$BL --command extension install-file -r user_default "$SCRATCH/dist/mjolnir_forge-1.0.0.zip" < /dev/null
ADD=bl_ext.user_default.mjolnir_forge

# B-01: enable at STARTUP (this is the condition that exposes _RestrictData in register()); must exit 0
$BL -b --factory-startup --python-exit-code 1 --addons $ADD --python tests/blender/b01_startup.py

# fast suite against the stub provider (G4)
$BL -b --factory-startup --python-exit-code 1 --addons $ADD --python tests/blender/run_all.py -- --provider stub

# full suite against the real library (G6); add --real-library to link the real Halo Reach.blend (local, read-only) instead of the synthetic stand-in
$BL -b --factory-startup --python-exit-code 1 --addons $ADD --python tests/blender/run_all.py -- --provider real [--real-library]
echo "BLENDER_EXIT=$?"                                  # 0 ok, 1 uncaught exception in a script. Do not pipe the Blender command: the default macOS shell is zsh, where ${PIPESTATUS[0]} is empty (reproduced S); redirect to a log file and read $?
```
`run_all.py` options: `--provider stub|real`, `--only ID...` (for example `--only b15 b18`), `--real-library`.

Verified `S` on this Mac with a probe extension: `--addons bl_ext.user_default.<id>` runs the add-on's `register()` at startup with `bpy.data` restricted, `extension build` needs an existing `--output-dir`, and `extension install-file -r user_default` works offline with stdin closed. `--python-exit-code 1` turns an uncaught exception into exit status 1 (without it Blender exits 0 even when the script raises).

Rules: never call `blf.draw` unstubbed; never run `INVOKE_DEFAULT` expecting a dialog (pass `filepath=`); the synthetic stand-in library (`tests/blender/make_standin_library.py`) has the same collection layout as `Halo Reach.blend` (a cube per leaf, names only) and is the default so CI on another machine needs no game asset; the real library is linked only with `--real-library` and only read.

| Id | File | Content |
|---|---|---|
| B-01 | `b01_startup.py` | enabled at startup without `AttributeError`; classes registered; `register`/`unregister` x3 leaves exactly one File > Import and one Export entry and then none; handlers removed; no `bpy.ops` call and no thread started during `register()`; `ErrorMessage` not invoked; overlay handler absent in `-b` |
| B-02 | `b02_import.py` | import W1 (generated by the fixture builder): 3 objects, names `"%d - %s"`, matrices, `mj_*` props, scene keys, labels original case, `imported_slots`; import fixture `unknown_map` (map id 0xFFFFFFFF): no exception, `map_name` '' and `map_id_hex` '0xFFFFFFFF' |
| B-03 | `b03_persist.py` | import, `save_as_mainfile`, **open in a fresh Blender process**, export succeeds from the embedded template (no path dependency; `bpy.app.driver_namespace` holds no key starting with `mjolnir`, `gtIndexToLabel` or `persist_vars`: a fresh Blender already holds about 74 unrelated entries, `S`). Runs against the stub in G4; `b03r_persist_real.py` repeats it with `--provider real` in G6 |
| B-04 | `b04_addmenu.py` | Add menu draw with a recording layout before any import and with `bpy.data.collections` empty (no `KeyError`); per-map filtering (Forge World vs Boneyard sets differ); search popup items |
| B-05 | `b05_props_extremes.py` | the "extremes" fixture (shape 1, width 200, spawn seq +/-128, team none, flags 0xFF, label none, parent set) imports without exception and re-exports with a zero diff; every property range and enum round trip; per-object failure isolation |
| B-06 | `b06_scale.py` | `SCALE` label scale applied with a selection present (the old bug); default convention is 47X |
| B-07 | `b07_linked_export.py` | export with a **linked** palette (`name_full` has the library suffix) works; "Sprint" resolves per map |
| B-08 | `b08_flags.py` | raw placement byte preserved; physics edit allowed; symmetry / place-at-start / game-specific edit refused with `E_FLAG_UNVERIFIED` |
| B-09 | `b09_duplicate_rename.py` | duplicate (`Shift+D` equivalent) with the same `mj_slot`; rename; `forge.object` replaced by `id_data`; unlinking and relinking an object, and moving it to another collection, leave the exported bytes unchanged |
| B-10 | `b10_hidden.py` | hidden (`hide_set`, `hide_viewport`) and excluded-collection plain objects are exported (and `W_HIDDEN_EXPORTED` appears); three array cases (array parent eye-hidden, `hide_viewport`, in an excluded collection) each produce `E_ARRAY_NOT_EVALUATED` and write no file |
| B-11 | `b11_arrays_limit.py` | array of a model-backed and of a model-less object (N instances -> N objects); fixture `full650` (650 occupied slots, roomy quotas) exports; `full650` plus one added object and fixture `over650` (651 occupied) give `E_TOO_MANY` and write nothing (assert membership of the code in the error list, not equality: other errors may be collected) |
| B-12 | `b12_convert.py` | `Convert To Forge Object` on a plain Blender object -> `E_OBJ_NO_TYPE` |
| B-13 | `b13_ui.py` | panels draw with a recording fake `UILayout` in all states; linked collection panel disabled; overlay callback returns immediately in `-b` |
| B-14 | `b14_replace.py` | `replace_existing` removes imported objects and their shape/camera helpers, keeps user-made objects |
| B-15 | `b15_move_roundtrip.py` | import -> move one object -> export -> re-import: the moved object within one cell (`tol`), every other object's slot **bit-identical** in the file; prints `moved slot S dx=.. other slots bit-identical N/N` (9.8 row 2) |
| B-16 | `b16_refusals.py` | each refusal through the operator, nothing written: no template, tampered template, unknown map id (fixture `unknown_map`, 0xFFFFFFFF), non-stock object (new, and imported-unrecognised), >650 (`full650` plus one, and `over650`), unevaluated array parent, out-of-bounds, quota, no free slot, unknown cached type, label out of range, rotation gate, tilt, mirrored, same-path overwrite, protected folder |
| B-17 | `b17_relink.py` | move the (stand-in) library after saving a file that links it; `load_post` repairs `filepath`; export still works |
| B-18 | `b18_golden_edits.py` | **the end-to-end anchor:** build W1, import in Blender, (E1) move slot 1 by +1.0 in x, (E2) add `Block, 1x1` at the cell-centre of (1, 2, 3) with the gate on, rotated so that its forward (local +Y) points along world +X (`rotation_euler.z = -pi/2`; an unrotated Add has forward (0, 1, 0) and yields raw angle 12288, the different golden E2b of Appendix C.3), (E3) delete slot 5; export; the output bytes **equal the independent builder's `w1_*_E1/E2/E3` files** |
| B-19 | `b19_filehandler.py` | `FileHandler` registers/unregisters; `import_scene.mjolnir_mvar` accepts `directory` + `files` |
| B-20 | `b20_installed_package.py` | run B-02 and B-18 against the installed extension (relative imports, data files, no `sys.path` hack) built with the default (no-library) package and with the stand-in library path in the preference |
| B-21 | `b21_symmetry_import.py` | files with every placement-byte value in 0x00..0xFF import without exception (display decoding total) |

### 9.5 T4: the ladder the user runs in MCC (also written into `NOTES.md` by G7)

Prerequisites: T3 passed on the user's own file (exit 0). Work on **copies** with new names; never overwrite the original. Each rung is one MCC load of the exported file in Forge on the same map.

**DECISION DEC-9.1:** the binding ladder (no-op, moved, added, deleted) is kept, but rung 1 yields the *original bytes* by design (principle 2) and a forced re-encode must equal the input too, so neither tests the codec against MCC; the first rung that does is the move. The extra rung H probes whether MCC enforces the SHA-1 at all, which decides how much the hash-flavour uncertainty matters.

| Rung | Action | What a pass means | If it fails, in this order |
|---|---|---|---|
| 1 | import the `.mvar` in Blender and export it unchanged (`_mjolnir.mvar`) | the pipeline works; the output **equals the input byte for byte** (`cmp in out`), so MCC sees nothing new. A control for file naming/location | check paths and file name; run `verify_mvar` on the output |
| H (optional) | `python3 -I tools/reencode_mvar.py in.mvar probe.mvar --corrupt-hash`, then `--zero-hash`, then `--hash-recipe plain_le32` / `salted_be32` | probe.mvar with a corrupted SHA-1 loads -> MCC does not enforce the hash (then flavour is irrelevant); loads with 20 zero bytes -> MCC needs no digest; loads only with one recipe -> that recipe is required | record the result in `NOTES.md` |
| 2 | move **one** object by +1 world unit in x | first real test: the position codec, the bounds, the hash/length rewrite (only 20 bits of one slot, L unchanged, new SHA-1) | verify output with `verify_mvar` (round trip OK?); if rung H showed the hash matters, the flavour is wrong; else the position codec or bounds are wrong |
| 3 | tick "Allow unverified rotation export", **add** one `Block, 1x1` at a free spot | slot insertion: stream grows, quota row `placed + 1`, assumed class 0, default placement byte, yaw convention | classes or orientation conventions wrong: compare with an in-game-placed block via `verify_mvar` placement/cached-type histograms |
| 4 | **delete** one object | stream shrinks (bit shifts), quota `placed - 1` | |
| 5 (optional) | rotate one vertical object by 90 degrees about Z (gate on) | the yaw convention (which way "forward" points) | flip the convention in `codecs.py` and record it |

Pass/fail is what the user sees in Forge (map loads, object present, where it is, budget meter, no crash). Each result is recorded in `NOTES.md` under "T4 results".

### 9.6 Manual GUI checklist (10 lines; headless runs cannot see these)

1. File > Import and File > Export list "Halo Reach Map Variant (.mvar)". 2. Drag a `.mvar` onto the 3D viewport imports it. 3. The imported objects appear at the right places with the palette models; arrow empties for model-less ones. 4. Add > Forge Object shows only entries valid for the map; icons look sensible (the numeric `forge.icon` indices drift; the static icon map must be eyeballed). 5. Sidebar tab "Forge" and Properties > Object > Forge Properties show sensible values and a label dropdown with the map's labels. 6. Properties > Scene > Forge Scene shows map name, slots used and the rotation checkbox. 7. The overlay counter "N / 650" is drawn bottom-left and turns orange above 500, red above 650. 8. Export dialog shows the options and the refusal text for a deliberately bad case; the text datablock "Mjolnir Export Report" opens. 9. Undo after import removes the objects. 10. Opening a `.blend` saved with objects but without the library shows no errors and, after the library is available, the models relink.

### 9.7 What a green run proves

All of U-xx and B-xx green on both interpreters and the real-library run: the code agrees with this document and with an independently built copy of it; the Blender glue behaves on 5.2.1 headless; the 8 real game-variant files pass through the generic container path; no game asset entered the repo. It does **not** prove that MCC loads an exported map, that the `mvar` body layout is right, or that the GUI looks right. Those are T3, T4 and 9.6. Section 9.8 maps each done-criterion to one command and one pass condition.

### 9.8 Done-criteria traceability (the acceptance sheet)

"Sample" means the 8 game-variant `.bin` paths (5 distinct contents). No real `.mvar` exists on this Mac (`NOTES.md` D1), so the "sample map" of Phase 2 is the synthetic map W1 (and the other T2 fixtures) from the independent builder. A green Phase 2 therefore proves self-consistency on Blender 5.2.1, not MCC acceptance (9.7). If the owner supplies a real `.mvar`, row 2R runs the same steps on a copy of it. `PY39=/usr/bin/python3` in every command; commands run from `$REPO`.

| # | Done-criterion | Command | Pass condition |
|---|---|---|---|
| 1 | Phase 1: every sample file loads, saves with no change, byte-identical | `$PY39 -I tools/run_tests.py --samples --only blf_real -v`, and the same with `$PY313` | U-02 prints `PASS <file> <sha256[:16]>` for all 8 paths: parse ok, `to_bytes() == input`, `to_bytes(force=True) == input` |
| 1b | the same for synthetic map variants | `$PY39 -I tools/run_tests.py --only roundtrip_forced -v` | U-08 green for every fixture (for `_cmp` shapes: the DEC-2.6 assertions) |
| 2 | Phase 2: Blender 5.2.1: import a map, move one object, export, re-import, the change is intact | `tools/run_blender_tests.sh --provider real --only b15 b18` | exit 0; B-15 prints `moved slot S dx=.. other slots bit-identical N/N` |
| 2R | Phase 2 on a real map (optional; needs a real `.mvar`) | `tools/accept_real_mvar.sh FILE.mvar` (copies FILE to a temp dir, runs `verify_mvar`, then the B-15 steps on the copy) | exit 0 |
| 3 | refuse a non-stock map | U-13 `E_MAP_UNKNOWN`; B-16 case `unknown_map` (map id 0xFFFFFFFF) | refusal, nothing written |
| 4 | refuse non-stock objects | U-13 `E_OBJ_NAME_UNKNOWN` and `E_OBJ_NOT_STOCK` (also for imported ids missing from the table, DEC-7.4) | refusal, nothing written |
| 5 | refuse more than 650 objects | fixtures `full650` and `over650` in U-13 and B-11/B-16 | `full650` exports; `full650` plus one object and `over650` (even unchanged) give `E_TOO_MANY`; nothing written on a refusal |
| 6 | never modify the originals | U-21, U-18 and the B-16 same-path and protected-folder cases | snapshots equal before and after; the refusals fire |
| 7 | no Microsoft game files in the repo | `$PY39 -I tools/check_no_game_assets.py` (scans ignored files too, DEC-F.2) and `git status --ignored --short` | exit 0; ignored entries only `__pycache__/`, `dist/`, `build/` |

`tools/accept.sh` runs rows 1, 1b, 2, 3, 4, 5, 6 and 7 and prints PASS or FAIL per row; G7 accepts on eight PASS lines. (DEC-9.4)

---------------------------------------------------------------------------------------------------

## 10. Risks (ordered) and what cannot be confirmed without a real `.mvar` or MCC

### 10.1 Risks, most dangerous first

Rank = likelihood x impact, the author's judgement. "Mitigation" is what the spec already does.

| # | Risk | Likelihood | Impact | Mitigation in this design |
|---|---|---|---|---|
| R1 | **No real `.mvar` has ever been walked.** Framing (+36, L at +32, pad), header widths, a field order or width in the body table may be wrong | 0.2 to 0.4 that at least one table entry needs a fix | import refuses (best case) or a wrong decode is caught by the end-of-walk check (3.10) | all layouts are data tables; hypotheses for the disputed points; acceptance by length + plausibility; `verify_mvar` (T3) is shipped at the end of G3, **before** the write path is built, so the owner can run it early; exit code non-zero on desync |
| R2 | Single-source features are wrong: v32 GUID (0.6), `_cmp` in the wild (0.7), stored-length byte order (0.75), type-19 rule (0.5/0.5), OOB escape | 0.3 each | refusal or mis-walk | each is a hypothesis or a refusal, never an assumption; the failing walk prints which one |
| R3 | **Hash flavour and MCC enforcement** unknown (including whether MCC-saved map variants carry an all-zero hash); `_fsm` semantics unknown | 0.3 | MCC rejects every exported file, or accepts any | flavour detected per file and reproduced (`zero` included); `hash_policy` override; rung H of the ladder measures enforcement; `fsm_policy` KEEP/DROP |
| R4 | **Orientation**: reconstruction of forward from (up code, angle) is a guess for tilted objects and the zero direction/sign of yaw is inferred | 0.4 that something is off | wrong picture in Blender; badly oriented *new* objects | raw bits kept for untouched objects; only pure-yaw writes; opt-in gate; tilt writes refused; rung 5 of the ladder |
| R5 | **Object-id tables**: `(folder << 8) + item` per map might not equal MCC's palette (8 ids genuinely conflict between the two upstream tables, 36 differ in total; MCC updates; palette CRC) | 0.2 | wrong object placed; or the game rebuilds the variant from the scenario and drops edits | tier-1 keeps imported ids verbatim (an id missing from the table is refused unless the owner opts in, DEC-7.4); tables are data (one real file corrects them); `W_DISPUTED_ID`; `I_PALETTE` note; verify prints unresolved ids |
| R6 | **Placement-flag semantics conflict** (HMS vs Mjolnir) and unknown `flags2` bits | certain that one reading is wrong | wrong symmetry/place-at-start if edited | edits other than physics refused; display uses the file reading; verify prints the histogram |
| R7 | **New-object bookkeeping**: cached type for new objects, default team/colour/placement, quota meaning for scenario-default objects, budget, 650 vs 651, whether deleted default objects free slots | 0.5 that one of these is off | added/deleted objects behave oddly or the game "repairs" the file | learned-from-template defaults; assumed class 0 only for Structure/Scenery with a warning; quota delta updates with refusal; rungs 3 and 4 |
| R8 | **Out-of-bounds records** exist in a real map | 0.1 | that map cannot be imported at all (abort) | clear message; HMS says the game clamps on its own saves; documented limitation |
| R9 | Blender GUI behaviour not seen: icons, drag and drop, overlay, undo, relink after Blender upgrades, 57 MB library link time | 0.5 that something cosmetic is off | UX only | 9.6 checklist; relink handler; static icon map; lazy link |
| R10 | **Legal/licence**: the repo tracks upstream's Microsoft/343 library `Halo Reach.blend` (read in place); the optional `--with-library` zip would contain it; upstream repo declares no licence; sources have GPLv3 (Cobb), PolyForm-NC (HMS), no licence (BLF) | certain to need an owner decision | release/distribution risk | clean-room rule (0.2); the default package contains no game asset (DEC-8.10); package built outside the tree; `*.zip` ignored; `check_no_game_assets` (scans ignored files too, DEC-F.2); the build refuses a placeholder manifest licence (DEC-8.10) |
| R11 | Independence of T2 collapses (same person writes builder and codec; shared misreading of this spec) | 0.3 | false confidence | different authors for G2 and G3 when possible; import scan; W1 produced by a third implementation; the optional JS oracle U-23; 9.1 "honest limit" statement |
| R12 | Library/zlib differences between Python 3.9 (zlib 1.2.12) and 3.13 (1.3.1) | 0.1 | label re-encode differs | label table is emitted from raw bits; the recompress test covers both (U-04); re-encode identity is reported, not required |
| R13 | Data loss by user error (overwrite, wrong file) | 0.2 | a lost map | path policy (2.13), `_mjolnir` default name, atomic write, no `.bak` surprises, originals never opened for writing by any tool (proved by U-21) |
| R14 | Performance of pure Python | 0.05 | slow import | decode of 651 slots x up to 8 hypotheses is a few hundred thousand bit reads (well under a second); Blender mock import of 650 objects measured 0.2 s plus 0.6 s for the one-time library link |

### 10.2 Things that CANNOT be confirmed without a real `.mvar` (T3) or MCC (T4)

1. The mvar chunk framing: bit stream at +36, stored length at +32 and its byte order, the 4 pad bytes, chunk version/flags (31/1) on a real MCC file.
2. Which hash recipe MCC writes (and whether MCC-saved map variants carry an all-zero hash, as KSoft.Blam documents for game variants); whether MCC checks the SHA-1; what `_fsm` signs and whether a stale one matters.
3. Whether real files are plain, `_cmp`, or carry `_fsm`; whether the body version is 31 or 32; the meaning of the 128 bits.
4. The type-19 rule; whether real maps contain out-of-bounds records.
5. The axis-bit rounding variant at exact thresholds (only matters if a box lands on one).
6. That `id = (folder << 8) + item` and the per-map tables match what MCC uses; behaviour on a palette-CRC mismatch.
7. Orientation: the reference-vector function for tilted objects, the sign and zero direction of the 14-bit angle, whether Blender's identity corresponds to the game's.
8. The meaning of the placement byte (symmetry, not-at-start, shortcut), of `flags2` bit 1 and `in_bounds`, and of the signed `spawn_seq`.
9. The semantics of quota `placed` (are scenario-default objects counted?), whether MCC enforces `minimum/maximum` on load, whether the budget words are integers or floats and whether MCC recomputes them.
10. The set of valid cached types and the rule that blocks are class 0; the exact encoding of team (raw 9 = neutral) and colour (3 bits).
11. The 650-versus-651 limit and whether deleting a default object frees its slot. (Consequence of the conservative limit: a real map that occupies 651 slots is refused by export even when unchanged, `E_TOO_MANY`; ladder rung 1 cannot be run on such a file until the owner raises `max_objects`, which v1 does not expose.)
12. That MCC accepts a header and `chdr` that are not re-stamped with a new "modified by".
13. The text encoding of label strings and acceptance of a different compressor.
14. **That MCC loads any file this tool writes.**
15. GUI look and feel (9.6).

---------------------------------------------------------------------------------------------------

## 11. Gate-by-gate work breakdown G0 to G7

Dependency graph (an arrow means "must be finished before the accepting step"):

```
G0 --> G1 --+
 |          +--> G3 --> G5 --+
 +--> G2 ---+                +--> G6 --> G7
 |                           |
 +--> G4 --------------------+
```
G1 and G2 run in parallel; G3 needs G1 and G2; **G4 needs only G0 and runs in parallel with G1/G2/G3/G5**; G5 needs G3; G6 needs G4 and G5; G7 last. **Interfaces that cross gates are frozen in G0:** `Addon/mvarlib/api.py` and `errors.py` (complete at G0, SHA-256 recorded, test U-22), the stub, `provider.py` (6.4). `tables.py` and `io.py` are delivered in G0 as well, because the glue (G4) needs the stock-name tables and the path policy before G3 and G5 exist.

### Cross-gate contract: the stub provider (what lets G3 and G4 proceed in parallel)

`tests/stubs/stub_mvarlib.py` is written in G0 and exposes **exactly** the names of `Addon/mvarlib/api.py`: the dataclasses are imported from `api.py` (not redefined), plus the two functions and a few test controls:

```python
# tests/stubs/stub_mvarlib.py (illustrative)
from mvarlib.api import *                  # dataclasses, Issue, MapInfo, ObjectRecord, ExportObject, ExportOptions, ExportResult, ReadOptions, the error classes and the five real G0 helpers
LAST_EXPORT = None                         # (template, objects, options) of the last export_map_variant() call
NEXT_EXPORT = None                         # if set, an ExportResult returned (and cleared) by the next call: lets tests inject refusals
NEXT_LOAD_ERROR = None                     # if set, an MvarError raised by the next load_map_variant()
NEXT_LOAD = None                           # if set, a LoadResult returned (and cleared) by the next load_map_variant(): CANNED_EXTREMES etc.
def reset() -> None
def load_map_variant(data, name="", options=None) -> LoadResult      # ignores the bytes except for the SHA-256; returns CANNED
def export_map_variant(template, objects, options) -> ExportResult    # records LAST_EXPORT; default: ok=True, data=template, naive diff
```
`CANNED` = a Forge World map (id 3006, bounds -240..240, -345..345, -70..70, quota_count 80, version 31, hypothesis `{'type19': 'undetermined', 'axis_bits': [20, 21, 19], 'guid': False, 'length_class': 'ceil_end'}`, labels `SCALE`, `Kill Boundary`, `Spawn`) with five objects: slot 1 `Block, 1x1` (vertical, yaw 0), slot 2 `Assault Rifle` (no model, folder 0, item 0, cached type 1, other_a 3), slot 5 `Kill Boundary` (shape 3, label 1, cached type 26), slot 9 `Block, 1x1` (tilted), slot 11 `Initial Loadout Camera` (so the camera-child path runs); every record carries a distinct `raw/raw_bits` token. The stub also carries `CANNED_BY_MAP = {3006: <Forge World>, 1080: <Boneyard>}` (so the per-map Add-menu filter can be tested), `CANNED_EXTREMES` (shape 1, width 200, spawn sequence -128 and 127, team none, flags 0xFF, label none, parent set) and `CANNED_PLACEMENT_ALL` (256 objects, one per placement byte); `map_name_for_id`, `stock_object_names`, `palette_tree`, `check_output_path` and `write_atomic` are the real G0 functions re-exported, so G4 reads everything through the provider `P` and needs nothing outside G0. The glue reaches the library **only** through `Addon/provider.py` (`get_provider()` / `set_provider()`) and builds every api object through it (`P.ExportObject(...)`), so tests call `provider.set_provider(stub_mvarlib)` and the production default returns the add-on's `mvarlib.api` module itself. (Inside Blender the real library is `bl_ext.user_default.mjolnir_forge.mvarlib` while the stub imports the repo copy as `mvarlib`: two module identities, which is why the glue must not use `isinstance` or import api types directly.) G3/G5 must make `mvarlib.api.load_map_variant` and `export_map_variant` behave as the contract notes of 6.4 say; G4 asserts on `LAST_EXPORT` (the ExportObjects the glue built) and on the reports it shows for injected results.

### G0. Spec acceptance, repo guards, interface freeze

Deliverables (paths relative to `~/Documents/Halo_MCC/mjolnir-forge-editor/source`):
- This spec accepted by the owner and committed with its reference material (all synthetic, no game data): `docs/mvar/SPEC-mvar.md` and `docs/mvar/reference/{bitio_prototype.py, blf_container.py, w1_build.py, w1_parse.py}` (DEC-G0.1). The `research/` paths named in G1, G2 and Appendix C then mean `docs/mvar/...`; the research reports themselves stay outside the repo.
- **Repo hygiene (binding F; DEC-F.1: the three pieces already exist uncommitted, so G0 reviews and completes rather than creates).** `.gitignore` and `.gitattributes` already carry the port's additions as *uncommitted working-tree changes* (`dist/`, `build/`, `*.zip`, `*.mvar`, `*.mglo`, `__pycache__/`, `scratch/` ...; `*.mvar binary`, `*.bin binary`, `*.mglo binary` `S`): review the diff and commit. `tools/check_no_game_assets.py` already exists (uncommitted): it allowlists files identical to `origin/master` and rejects new binary-looking files, files starting with `_blf`, and anything over 512 KB. G0 **adds** the hash allowlist fallback (the three pre-existing binaries: `Addon/Resources/ForgeBridge.dll` sha256 `e1296523...2e48`, `Addon/Resources/Halo Reach.blend` `a76e1d74...e6ad`, `Blender (Download a Release, Not Me!)/forge.blend` `35cc9130...5ae8`) for when `origin/master` is not available, a `--self-test`, the test U-17 (with U-17b), and the ignored-files scan (**DEC-F.2**): replace the untracked listing `git ls-files -z --others --exclude-standard` by `git ls-files -z --others` (no `--exclude-standard`) and drop entries under `__pycache__/` and `*.pyc`, because the port's own `.gitignore` hides `*.mvar`, `*.zip`, `dist/`, `build/` and `scratch/`, so a game file placed there would otherwise pass (reproduced `S` in a temp repo with the real `.gitignore`: `git status --short` and the first draft's guard both showed nothing). Package zips are built outside the tree (`tools/build_package.py`, G4) and contain no game asset by default (DEC-8.10).
- `Addon/mvarlib/{__init__,api,errors,entry,tables,io}.py`: `api.py` and `errors.py` exactly as 6.2 and 6.4 including the re-export line and the five helpers; `entry.py` with bodies that raise `NotImplementedError("G3")` / `("G5")`; `tables.py` and `io.py` complete; `Addon/provider.py`; `tests/stubs/stub_mvarlib.py` (canned Forge World map: 5 objects incl. one model-less, one kill-boundary box, one tilted object, plus the extra canned data of the cross-gate contract above; `export_map_variant` records its arguments in `LAST_EXPORT`, returns `ok = True` with `data = template`, a naive diff, and can be told to return preset `Issue`s so UI tests can exercise refusals).
- `tools/gen_stock_tables.py`, `Addon/mvarlib/data/maps.json`, `Addon/mvarlib/data/stock_objects.json`, `data/cached_type_hints.json`, `data/palette_tree.json` as the valid empty tree (+ `U-15`).
- `tools/run_tests.py`, `tools/run_tests.sh` (skeleton running whatever tests exist), `tests/py39_lint.py`, and the tests U-18, U-19, U-21, U-22 (their subjects `io.py`, the lint and the freeze exist from G0).
- `NOTES.md`: add a pointer to this spec and record the SHA-256 of `api.py` and `errors.py` as "interface freeze v1" (also in `tests/golden/interface_sha256.json`).

Acceptance: `$PY39 -I tools/check_no_game_assets.py` exits 0 on the tree and 1 on a temp repo with a planted `.mvar` (U-17) and on one that plants gitignored files (U-17b); `$PY39 -I tools/run_tests.py` and `$PY313 -I tools/run_tests.py` green (U-15, U-17, U-18, U-19, U-21, U-22); `api.py` imports on 3.9 and 3.13; `git status --ignored --short` lists no entry other than `__pycache__/`, `dist/`, `build/`.

### G1. Container, bit I/O, hashing, shared header (T1)

Deliverables: `Addon/mvarlib/{bitio,hashing,blf,ugc_header}.py` (promoted from `docs/mvar/reference/bitio_prototype.py` and `docs/mvar/reference/blf_container.py`, which are references; note `blf_container.py` defaults to the `mpvr` layout and a LE length, wrong for `mvar`: the new `PayloadSpec` registry fixes that); `tests/unit/{helpers_real,test_bitio,test_blf_real,test_header_real,test_labels_zlib_real,test_hashing}.py`.
Consumes: G0. Produces: `BlfFile`, `HashFlavour`, `BitReader/BitWriter/BitString`, header codec for G3 and G5.
Acceptance: `$PY39 -I tools/run_tests.py --samples` and `$PY313 ...` green for U-01 to U-04 and U-06; the 8 real files satisfy every T1 clause in 9.1 (parse, passthrough, forced rebuild, flavour `('<', 'salted_be32')`, header at 68 and 0, zlib recompress); masked-write test proves the RVT clobber hazard cannot occur; no `import` outside the standard library.

### G2. Independent fixture builder and golden vectors

Deliverables: `tests/fixturebuilder/{__init__,bits,consts,build,selfcheck}.py` (own big-integer bit writer, literal tables from sections 3 and 4, own walker); `tests/golden/{codec_vectors.json,w1_reference.json,fixture_specs/*.json,fixture_sha256.json}`; `tests/unit/test_fixturebuilder_selfcheck.py` (U-20) and the independence scan inside U-17. Fixture specs: `w1_minimal` (Appendix C), `holes`, `extremes` (shape 3 with 0 and 0x7FF, spawn seq -128/127, team raw 0 and 9, colour absent and 7, parent raw 0 and 651, label 255 with a 256-entry table, folder 255, item 31, cached type 31, angle 0 and 16383, positions 0 and 2^bits - 1, bits 15 to 23 including a zero-range axis), `zero_labels`, `labels_uncompressed`, `labels_compressed`, `v32`, `cmp`, `fsm`, `cmp_fsm`, `plain_le32`, `le_length`, `eof_le`, `type19_flag8`, `type19_plain8`, `axis_threshold`, `near_full` (capacity), `full650` (650 occupied slots over folders 70 to 73, each quota `(0, 255, n)`), `over650` (651 occupied), `unknown_map` (map id 0xFFFFFFFF), `zero_hash` (stored hash 20 zero bytes), `guid_v32_absent` (version 32 without the 128 bits), `guid_v31_present` (version 31 with them), `trailer` (padding after `_eof`), the header fixtures `hdr_hopper` (decoded activity 2, stored 3, hopper id 0x1234), `hdr_campaign` (gameMode 1; id 5, difficulty 2, metagame 1, rally 7, unk 0x01020304), `hdr_firefight` (gameMode 2; difficulty 3, unk 0xA0B0C0D0), `hdr_long_text` (both author names 16 chars with no NUL, title and description 128 units with no NUL) and `hdr_min_text` (author names `00`, empty title and description) with the goldens of Appendix C.4, a golden `<name>_expanded` file for each `cmp` shape (DEC-2.6), and the negative ones `bad_version`, `bad_size`, `oob`, `desync_length`, `truncated`, `bad_content_type`, `chunk_version_50`, `chunk_version_13`, `bounds_inverted`.
Staffing: a different engineer from G3 where possible, working from this spec, not from G3's code.
Acceptance: the builder reproduces **W1 exactly** (SHA-256 of both flavours, hash, L, end bit, section starts, E1/E2/E3 and E2b files and the header goldens: Appendix C); U-20 green; fixture generation is deterministic (a second run gives identical SHA-256s, recorded in `fixture_sha256.json`); no fixture file is written inside the repo; the builder imports nothing from `Addon`.
Runs in parallel with G1.

### G3. Body read path and `verify_mvar` (T3 tool)

Deliverables: `Addon/mvarlib/{codecs,labels,slot,walk,model,plain,report}.py` (G3 owns `Slot.pack`, the read side of `model.py` and `to_bytes()` / `to_bytes(force=True)` of unmodified models; `tables.py` is G0's and `palette_tree.json` is G4's), `tools/{verify_mvar,dump_mvar}.py`, `entry.load_map_variant` (the `api.py` delegation already exists); tests U-05, U-07, U-08 (owned here, re-run by G5), U-09, U-10 (read parts), U-14, U-16, and U-23 if `node` is available.
Consumes: G1, G2, G0. Produces: `LoadResult` with correct `ObjectRecord`s; the T3 tool.
Acceptance: every positive fixture parses and its fields equal the builder's declared values; unmodified `to_bytes() == input` and, for the plain shapes, `to_bytes(force=True) == input` (for `cmp` shapes the golden expanded file, DEC-2.6); hypothesis tests (U-09) including `undetermined`, `Ambiguous`, `Desync`; `verify_mvar.py` exit codes 0/1/2/3 as specified on W1, a desynchronised fixture, a game variant and a forced self-check failure; **milestone: deliver `tools/verify_mvar.py` to the owner to run on a real `.mvar` now**, without waiting for G5/G6 (R1).
Needs G1 and G2.

### G4. Blender glue refactor against the stub provider (parallel with G1 to G3 and G5)

Deliverables: `Addon/{__init__,mjolnir,provider,state,palette,io_ops}.py`, `Addon/blender_manifest.toml`, `tools/{gen_palette_tree,build_package}.py`, `Addon/mvarlib/data/palette_tree.json` (generated), `tests/blender/{run_all,make_standin_library,b01_startup,b02_import,b03_persist,b04_addmenu,b05_props_extremes,b06_scale,b08_flags,b09_duplicate_rename,b10_hidden,b11_arrays_limit,b12_convert,b13_ui,b14_replace,b17_relink,b19_filehandler,b21_symmetry_import}.py` and `tools/run_blender_tests.sh`, driven by `tests/stubs/stub_mvarlib.py` through `provider.set_provider()`.
Consumes: G0 only (`api.py`, `errors.py`, `tables.py`, `io.py`, the data JSON, the stub, `provider.py`). The glue must import the library **only** through `provider`.
Implements: 8.1 to 8.13, including every row of the 8.7 fix list that does not depend on the real codec.
Acceptance: `B-01 .. B-06, B-08 (display + refusal passthrough), B-09 .. B-14, B-17, B-19, B-21` green with `--provider stub` under the startup-enable condition (9.4); no `bpy.data` access, `bpy.ops` call or thread in `register()`; File > Import/Export entries correct after 3 enable/disable cycles; `ForgeBridge.dll` not packaged; the default (no-library) extension builds outside the tree with `--allow-placeholders` and installs into an isolated profile.

### G5. Write path and validation

Deliverables: `Addon/mvarlib/{edit,validate}.py` (`io.py` is G0's), the write side of `model.py` (patched mode, forced mode for edited models, hash flavours including `zero`, `hash_policy`, `_cmp` expansion, `_fsm` policy), `entry.export_map_variant`, `tools/reencode_mvar.py`; tests U-10 (write parts), U-11, U-12, U-13; U-08 is re-run.
Consumes: G3. Produces: the real provider behind `api.py`.
Acceptance: W1 E1/E2/E3 byte-equal to the builder's files; the bit-diff contract (5.9) for every edit kind; every `E_`/`W_` code of 7.3 has a test with its exact message; capacity refusal; hash flavour reproduction for both flavours, `zero` and the `unknown` fallback, and `hash_policy` forcing; `export_map_variant(template, unchanged objects)` returns the template bytes (unless a global limit such as `E_TOO_MANY` refuses it, 6.4); refusals leave `data = None`.

### G6. End-to-end headless Blender suite

Deliverables: `tests/blender/{b03r_persist_real,b07_linked_export,b15_move_roundtrip,b16_refusals,b18_golden_edits,b20_installed_package}.py` (`b03r_persist_real` is B-03 with `--provider real`) completing the catalogue of 9.4, and the final `tools/run_blender_tests.sh`; the whole catalogue is run with `--provider real`, the stand-in library and once with `--real-library`.
Consumes: G4 + G5.
Acceptance: the whole 9.4 suite green with exit code 0 under `--factory-startup --addons bl_ext.user_default.mjolnir_forge`; **B-18 output bytes equal the independent W1 E1/E2/E3 files**; save/reopen between import and export (fresh process) works; every refusal path leaves no file; moved-library relink works; also green on the real `Halo Reach.blend` (read-only, local run).

### G7. Packaging, docs, NOTES

Deliverables: final `tools/build_package.py`; `Addon/blender_manifest.toml` completed by the owner (maintainer, licence); `NOTES.md` updated (confidence table of 1.2, limitations of 10.2, the T4 ladder of 9.5 with a results table, how to run T3, how to install the extension and set the Library path preference (the default zip contains no game asset; a `--with-library` zip must never be shared), the results of the 10 GUI items of 9.6 each recorded as PASS, FAIL or NOT RUN); `readme.md` section for macOS; `tools/run_tests.sh` and `tools/accept.sh` final.
Acceptance: the manifest is completed (the build refuses `example.com` and `OWNER` without `--allow-placeholders`); `python3 -I tools/build_package.py --out <dir outside the tree>` (default: no library inside) produces a zip that `blender --command extension validate` accepts; installed into a clean isolated profile it passes B-01 and B-20; `tools/accept.sh` prints PASS for rows 1, 1b, 2, 3, 4, 5, 6 and 7 of 9.8; `git status --ignored --short` lists no entry other than `__pycache__/`, `dist/`, `build/`; the owner has run the 10 items of 9.6 and recorded each in `NOTES.md`; the T4 instructions have been dry-run by the owner on a copy of a map (results may still be pending MCC).

---------------------------------------------------------------------------------------------------

## Appendix A. Spot-check log (what the author of this spec re-ran or re-read, not just trusted)

Scripts and outputs: `/private/tmp/claude-501/-Users-michaelmincone-Local-Documents/6d5fba7a-3008-4537-951e-dacfdc34a893/scratchpad/spec_checks/` and `.../research/spec_w1/`. Every check below was run in this session on this Mac (Python 3.9.6, Blender 5.2.1 LTS).

| # | Claim checked | How | Result |
|---|---|---|---|
| 1 | 8 sample paths = 5 distinct contents; blocks `_blf 0x30 / chdr 0x2C0 / mpvr 0x5028 / _eof 0x11` tile 21,289 bytes; `_eof` value 21,272 BE | own script over both sample folders | confirmed |
| 2 | `mpvr` hash = SHA-1(salt34 + BE32(L) + stream[:L]) with L read **little-endian** at +0x24; plain-LE and salted-LE do not match; L equals "last non-zero byte + 1" | own script | confirmed for 5/5 (L = 4,648 / 3,779 / 7,288 / 2,006 / 3,467) |
| 3 | plain map variant = 29,481 = 0x7329 bytes; `mvar` chunk 12 + 20 + 4 + 0x7000 + 4 = 0x7028; `_eof` at 0x7318; capacity 229,376 bits | arithmetic | confirmed; the 0x9329 figure in `container-and-bit-conventions.md` is wrong |
| 4 | JS: 651 slots (`for i < 0x28B`, line 831), presence bit then return (615-617), parent `readBits(10) - 1` (641), size 0x7028 (691-694), stream after 0x14 hash bytes + 4 bytes (699-704), version byte 0x1F (745-747), quota loop (837-845), `this.gameMode` typo (734) | read all 846 lines | confirmed; typo noted (X23) |
| 5 | JS shape layout and codec (153-285): shape 1 = 1 value, 2 = 3 values, 3 = 4 values; 11-bit values; 0 -> 0, 0x7FF -> 200 | read; re-implemented | `dim_encode(f32(dim_decode(v))) == v` for all 2,048 codes |
| 6 | axis-bit formula: 1024^3 -> 21/21/21, 480x690x140 -> 20/21/19; JS highest-bit form equals `(n-1).bit_length()` for n in 1..65535; float32 constants `0x3C088889`, `0x38D1B717` | own implementation | confirmed |
| 7 | up-axis: JS constants-table row for 20 bits is `[0x2AAAA, 0x1A1]` = `[floor(2^20/6), 417]`; 4,998 of 1,043,334 valid codes re-encode to another face; 4 invalid face codes | re-read table; re-ran `crit_format/upaxis.py` | confirmed |
| 8 | UGC header: field order from `ugc_header.cpp:15-53`; decode and re-encode the 5 real headers independently, at the real offset (68) and from bit 0 | own decoder/encoder | identical bits for 5/5 (1,535 / 1,183 / 2,287 / 2,271 / 2,575 bits); titles decode |
| 9 | HMS (`mvar.rs`, `h4/mvar.rs`) facts: type 19 = 1 flag bit + 8; OOB = flag + 2-bit BSP escape; v32 adds 128 bits (signed 32 + 16 + 16 + 64) after the labels; L at +32 big-endian, `ceil(end/8)` on write; quota order min/max/placed; 651 slots; `_cmp` layout; `H4HashKind::PlainLe` (tried first) and `SaltedBe360`; non-enforcement comment | WebFetch of the raw source (facts only) | confirmed as the reports say |
| 10 | BLF (`scenario_map_variant.rs`): type 19 = `read_unnamed_index::<255>(8)` with no flag; slot order and widths; 651 slots; quota fields; **no version branch** | WebFetch (facts only) | confirmed; agrees with JS, disagrees with HMS (X5) |
| 11 | RVT `_cmp` layout: 12 header, 1 byte, u32 BE size, zlib, inflates to a complete block (`block.cpp:152-184`) | read | agrees with HMS |
| 12 | RVT string-table widths: `offset_bitlength = bitcount(max_buffer - 1)`, `buffer_size_bitlength = bitcount(max_buffer)`, `count_bitlength = bitcount(max_count)`; writer compresses at >= 0x80 bytes, size field = compressed + 4 (`localized_string_table.h:131-137`, `.cpp:408-452`) | read | consistent with (256, 4096) -> 9 / 12 / 13 |
| 13 | Map ids (`page_map_perms.cpp:15-58`): the 20 stock ids; **no `tables/maps*.json` exists** | read; listed `research/tables/` | confirmed (X22) |
| 14 | `0x4708` on Tempest = folder 71, item 8, `wall_coliseum`, "Wall, Coliseum"; JS comment says subcat 71 / subtype 8; max category 144, max variant 25 over all maps | JSON + JS comment | two independent sources agree |
| 15 | `forge.py`: `ToForgeObject` uses `coll.name_full`; `UpdateSpawnSeq` rescales `context.selected_objects`; `scaleConvention` has 5 items and `default=2` (= `71X`); `UpdateShape` looks up `bpy.data.collections['Shape Box']` globally; `forge.object` back-reference by name | read lines 480-1436 | confirmed |
| 16 | **Placement-flag bit meanings** differ between HMS (`PLACE_ASYMMETRIC 0x04`, `PLACE_SYMMETRIC 0x08`, `PLACE_NOT_AT_START 0x10`, shortcut `0x02`) and `ForgeObject.cs` / `forge.py` (`Symmetric 0x04`, `Asymmetric 0x08`, `HideAtStart 0x02`) | WebFetch of HMS constants vs local code | **new conflict, not in any report** (X15, 3.9) |
| 17 | `.gitignore` already ignores `[Bb]in/`, `[Oo]ut/`, `[Ll]og/` (plus `*.mvar` etc. from the port); `.gitattributes`/`.gitignore` modified and `tools/check_no_game_assets.py` present but uncommitted; the 3 binaries' SHA-256 | `git status`, `git diff`, `git check-ignore -v`, `shasum -a 256` | confirmed |
| 18 | Blender 5.2.1: an extension enabled with `--addons bl_ext.user_default.<id>` has `register()` called with `bpy.data` restricted (`libraries`, `context.scene` raise `AttributeError`); `extension build` needs an existing `--output-dir`, honours `paths_exclude_pattern`; `install-file -r user_default` works with stdin closed | built and ran probe extensions in an isolated `BLENDER_USER_RESOURCES` | confirmed |
| 19 | `python3 -I` = 3.9.6 and does not add the script directory to `sys.path`; Blender's bundled interpreter `/Applications/Blender.app/Contents/Resources/5.2/python/bin/python3.13` runs with `-I` (zlib 1.3.1) | ran both | confirmed |
| 20 | W1 reference fixture (Appendix C): built by one script, walked by a second script with a different bit reader; edits E1/E2/E3 also built and walked | `research/spec_w1/w1_build.py`, `w1_parse.py` | self-consistent: all offsets, `ceil(end/8) == L`, quota rows |
| 21 | Hash test vectors of 2.7 and golden codec values of section 4 | computed | recorded in the spec |
| 22 | every Python snippet of section 4 and the `api.py` block of 6.4, executed as written | extracted from this document and run on 3.9.6 (and the `api.py` block also on 3.13.13) | all golden vectors reproduced (G-AX including both rounding variants at k = 15..22, G-POS, G-SH incl. all 2,048 shape codes, G-ANG, G-UP); `api.py` compiles with `feature_version=(3, 9)`, imports and instantiates |
| 23 | the W1 numbers quoted in Appendix C | compared the 10 hashes and the offsets printed by `w1_build.py` with the text of this document | 10 of 10 present, offsets equal |
| 24 | the JS reference-vector helper (lines 466-501) | transcribed and run on 20,000 random unit vectors | not perpendicular to up in 19,853 cases (max abs dot 0.706); returns (1, 0, 0) for up = +Z |

Not re-fetched, taken from `web-mvar-format.md` and attributed to the source it names there: the `_fsm` field layout (0x1C4 bytes, RSA-SHA512 attestation), the remark that some shipped map variants are `_cmp`-wrapped (Empire.mvar), the `mvar` chunk version "31.1", the long `_eof` (size 0x105, auth type 3), HMS's statement that its saved files load in MCC, and the documented MCC budget figures. The critique's synthetic experiments (`crit_format/walker.py`, `lencheck.py`, `poscodec.py`, `crit_plan/x1`..`x3`, `p1_zlib_recompress.py`) were read and, where marked `S` above, re-run; the others are cited as the critique's results.

### A.2 Checks made during the revision pass (after the two lint reports)

Scripts and outputs: `.../scratchpad/fix_checks/` and `.../scratchpad/spec_patches/`. Python 3.9.6 (`/usr/bin/python3`), Blender 5.2.1 LTS, `node` v26.0.0 present.

| # | Claim checked | How | Result |
|---|---|---|---|
| R1 | the JS returns 0 bits for a zero range (`P:JS:129-145`); the JS bit-count logic equals `(n-1).bit_length()` for every n in 0..0x800000 | read; ported and looped | confirmed, 0 mismatches |
| R2 | UGC header conditionals: `activity` is tested decoded (`ugc_header.cpp:37`); widths hopper 16, campaign 8+2+2+8+32, firefight 2+32; `base.cpp:373` stops at padding after `_eof` | read `ugc_header.{h,cpp}`, `content_author.cpp`, `base.cpp` | confirmed |
| R3 | header goldens (hopper, campaign, firefight; long and minimal text) | the spec author's builder `w1_build.py` with only the header changed, compared with the format lint's independent builder | identical for hopper, campaign, firefight; header ends 4951 and 647 also agree |
| R4 | E2 yaw: `angle_encode(atan2(1, 0)) = 12288`; `rotation_euler.z = -pi/2` gives forward +X and raw 8192; the E2b golden | script | confirmed; E2b SHA-1 `0ebb78f1...2c77` |
| R5 | present-slot sizes 128 / 141 / 144 / 150 / 235 / 224 and 159,129 bits | script from the 3.6 table | confirmed |
| R6 | `N = isqrt(STRIDE) - 1` for the JS up-axis rows of 6 to 22 bits; `N^2 <= STRIDE` alone allows 418 | parsed the JS table | 17 of 17 rows match |
| R7 | compressed label tables: 4 of the 5 distinct real files, recompress identical at zlib levels 7 to 9 | `crit_plan/p1_zlib_recompress.py` on 3.9.6 | confirmed (`test_user_funcs_and_recursion.bin` has none) |
| R8 | sample provenance: content id `0x4A6994BF5D589B43`, timestamp 1,284,422,400, author byte `0xA6` in all five; `.lua` siblings beside four | script over the headers | confirmed |
| R9 | axis-bit variants: third variant `ceil_f32`; thresholds G-AX-3 and G-AX-6; 208,999 ranges | scripts | no disagreement on ordinary ranges; table in 4.1 |
| R10 | KSoft.Blam all-zero-hash rule (game variants only) | WebFetch of the raw file, facts only | confirmed |
| R11 | hidden or excluded array parents yield no depsgraph instances (Blender 5.2.1, `-b --factory-startup`) | probe script | 3 instances for the visible array, 0 for each of the three hidden variants; sources stay in `scene.objects` |
| R12 | `scene['k'] = 0xFFFFFFFF` raises `OverflowError`, `10070` works; a mixed str/int list raises `TypeError` | probe script | confirmed |
| R13 | `bpy.app.driver_namespace` after a fresh load | probe | 74 entries |
| R14 | `feature_version=(3, 9)` misses the runtime constructs; parenthesised `with` runs on 3.9.6 | 9 cases on 3.9.6 and 3.13.13 | confirmed (f-string quote reuse is caught by the scan) |
| R15 | zsh leaves `${PIPESTATUS[0]}` empty (`pipestatus` is the zsh name), bash fills it | tested | confirmed |
| R16 | the first draft's guard cannot see gitignored files | temp repo with the real `.gitignore` | `git status --short` and the guard listing both empty |
| R17 | `extension validate` and `extension build` accept placeholder maintainer text and `bl_info` next to the manifest | probe extension | confirmed |
| R18 | a package `tests/mvarlib/` shadows `Addon/mvarlib` when `tests/` is first on `sys.path` | probe | confirmed |
| R19 | `NOTES.md` D4 wording; `blf_container.py --selftest` | read; ran | confirmed; `ALL 5 FILES REBUILT BYTE-EXACTLY` |
| R20 | the revised `api.py` block of 6.4 | extracted and imported inside a stub package on 3.9.6 and 3.13.13, instantiated, `__all__` checked, `feature_version=(3, 9)` parse | all names resolve; star-import exports the error classes |

---------------------------------------------------------------------------------------------------

## Appendix B. Index of decisions made by judgement in this spec

Everything not listed here follows directly from a cited source or from the binding decisions A to G.

| Id | Where | Decision | Why |
|---|---|---|---|
| DEC-F.1 | 1.4, 11 G0 | the working-tree `.gitignore`, `.gitattributes`, `tools/check_no_game_assets.py` are reviewed and completed (hash allowlist fallback) rather than recreated | they already exist, uncommitted |
| DEC-2.1 | 2.5 | capacity is 229,376 bits; no spill into the 4 pad bytes (HMS allows 229,408) | stricter, never wrong |
| DEC-2.2 | 2.6 | a long `_eof` (size 0x105, signature) is passthrough-only; modified saves refused | we cannot re-sign it |
| DEC-2.2b | 2.6 | `_eof` byte order accepted either way, template's order reproduced | RVT comments that some files are LE |
| DEC-2.3 | 2.7 | writer reproduces the template's `(length byte order, recipe)`, an all-zero hash as zeros; non-zero no match -> salted_be32 + `W_HASH_UNKNOWN`; `hash_policy` override | binding D; only recipe verified locally; the plain_le32 fallback proposed by the lint was declined (Appendix E) |
| DEC-2.4 | 2.9 | `_fsm` kept verbatim on modified saves, warning, option `fsm_policy = DROP` | what HMS does; its saves are reported to load |
| DEC-2.5 | 2.12 | a walk is accepted only if L is `ceil(end/8)`, 0x7000 or the stored bytes `00 00 00 00` (class `zero`, written back unchanged) | WEB:HMS writer rule; capacity read rule; a forced rebuild must reproduce a zero field |
| DEC-3.1 | 3.2 | header (bit form and `chdr`) not editable in v1; raw range re-emitted | keeps both copies consistent for free |
| DEC-3.2 | 3.4 | label table never edited; emitted from raw bits; encoder only for `from_plain` | label editing is out of scope |
| DEC-3.3 | 3.8 | `in_bounds == 0` aborts the import | binding C |
| DEC-3.4 | 3.3 | body versions 31 and 32 accepted | JS knows 31, HMS 31 and 32 |
| DEC-3.9 | 3.9 | placement byte displayed with the HMS file reading; only physics bits editable; other flag edits refused | the two readings conflict |
| DEC-3.10 | 3.10 | hypothesis selection and preference order `flag8` then `plain8`; `guid_present` is a hypothesis dimension, the version-implied value is tried first and wins when accepted | binding C; a single-source rule must not be a hard assumption |
| DEC-4.1 | 4.2 | position change tolerance `max(1e-3, 0.5 cell, 2 ulp32)` per axis | float32 spacing can reach a cell |
| DEC-4.6 | 4.6 | orientation: vertical `forward = (cos t, sin t, 0)`; tilted display-only Gram-Schmidt of +X | JS port is unusable; continuity with the vertical case |
| DEC-4.8 | 4.8 | orientation writes: unchanged keeps raw; changed/new only pure yaw and only with the opt-in; tilt refused; mirrored refused | orientation is the largest unknown |
| DEC-5.4 | 5.4 | quota rows updated by delta; refuse above max or below min | whether default objects count in `placed` is unknown |
| DEC-5.6 | 5.6 | adding objects needs the rotation opt-in | every written orientation is unverified |
| DEC-6.1 | 6.7 | tools that write derived map data write through `write_atomic` and refuse any target inside the repo working tree (no exception) or a protected folder | no game-derived data in the repo; the guard cannot be escaped through `scratch/` |
| DEC-7.1 | 7.1 | `Addon/objects.py` is the canonical id table; 8 disputed ids flagged | newer, derived from a tag export |
| DEC-8.3 | 8.3 | the template is stored as a top-level bytes key | only that form was tested |
| DEC-8.4 | 8.4 | import replaces the previous import in the scene by default | one scene, one template |
| DEC-8.5 | 8.5 | export report goes to a text datablock plus console | Info area shows one line |
| DEC-8.7 | 8.7 | enum items `SPHERE` (shape) and `NEITHER` (symmetry) added | represent real data without flattening |
| DEC-8.10 | 8.10 | extension-only distribution, id `mjolnir_forge`, min Blender 5.2.0, licence field is a placeholder for the owner; the default zip contains no game asset (`--with-library` is an explicit opt-in that prints a do-not-share warning); the build refuses a placeholder manifest | only 5.2.1 tested; upstream declares no licence; hard rule: no Microsoft/343 asset is copied anywhere |
| DEC-9.1 | 9.5 | T4 rung 1 is a pipeline control; rung H probes hash enforcement; diagnosis column added | passthrough makes rung 1 byte-identical |
| DEC-9.2 | 9.1 | the fixture builder must not import `mvarlib`; scanned by a test | non-circularity |
| DEC-9.3 | 9.2 | samples found at the two known folders or `$MJOLNIR_SAMPLES`, never copied | repo stays free of game data |
| (also) | 5.7, 7.4 | new-object defaults learned from the template; class 0 assumed only for the `Structure` and `Scenery` palette groups, with a warning | `ForgeObject.cs` comment; unverified |
| (also) | 3.8 | type-19 objects cannot be created while the rule is undetermined | cannot encode what is unknown |
| (also) | 1.5 X20 | no `.bak` files; overwrite only through temp + `os.replace`; never onto the source | "never modify originals" |
| DEC-F.2 | 11 G0 | `check_no_game_assets.py` scans gitignored files (no `--exclude-standard`) | the port's `.gitignore` hides `*.mvar`, `*.zip`, `dist/`, `build/`, `scratch/` |
| DEC-2.6 | 2.11 | forced re-encode of a `_cmp` shape returns the expanded form; tests use a golden expanded file | a regenerated zlib stream cannot be promised identical |
| DEC-3.6 | 3.3 | a zero-range axis (`min == max`) is accepted with `W_ZERO_RANGE_AXIS`; moving or adding on it is refused | the JS reads 0 bits there and the spec's own golden vector requires it |
| DEC-6.4 | 6.4, 11 | `api.py` is complete at G0 (lazy delegation to `entry.py`); freeze = SHA-256 of `api.py` and `errors.py`; `tables.py`, `io.py` move to G0 | the freeze hash must not cover a file two gates edit; G4 needs the helpers |
| DEC-7.4 | 7.4 | an imported object whose id is not in the map's stock table is refused by default; owner opt-in keeps it | `NOTES.md` D4; narrows the literal wording of binding E in that case only |
| DEC-9.4 | 9.8 | acceptance sheet: each done-criterion has one command and one pass condition; U-21 proves the originals untouched | traceability |
| DEC-G0.1 | 11 G0 | the spec and its synthetic reference scripts are committed under `docs/mvar/` | the session scratchpad does not outlive the session |
| (also) | 2.2 | known non-Reach chunk versions (12, 13, 14, 50, 51) refused; other unexpected versions warn | catches Halo 4 files before the roughly 4 % false-pass walk; source not re-verified |
| (also) | 2.1 | bytes after `_eof` that are not blocks are kept as an opaque trailer | RVT itself stops at padding after `_eof` |

---------------------------------------------------------------------------------------------------

## Appendix C. Reference fixture W1 and golden edits

W1 is a synthetic plain 4-block map variant built to this specification. It is **not game data**. It exists so that two independent implementations (G2's builder and the library) can be compared byte for byte, and so that the Blender end-to-end test (B-18) can compare against bytes that were not produced by the library. Regenerate and verify with:

```
python3 -I docs/mvar/reference/w1_build.py [OUTDIR]
python3 -I docs/mvar/reference/w1_parse.py FILE [--type19 flag8|plain8]
```
(`w1_build.py` writes the files only when `OUTDIR` is given.) Those two scripts are references (G0 copies them from the session scratchpad, `research/spec_w1/`, into `docs/mvar/reference/`); the G2 builder must be written from this appendix and sections 2 to 4, not by copying them.

### C.1 Parameters

Container: `_blf` 0x30 (1.2, BOM `FF FE`, zeros); `chdr` 0x2C0 (10.2): build 0 / 0xFFFF, contentType 5, fileLength 0x7329, ids `0x0123456789ABCDEF`, `0x0F1E2D3C4B5A6978`, `0x1122334455667788`, `0`, activity 0, gameMode 4, engine 1, mapID 3006, engineCategory 0, createdBy {timestamp 1,700,000,000, xuid 0, name `A`, online 0}, modifiedBy {timestamp 1,700,000,001, same}, title "W1 minimal", description "synthetic reference fixture" (UTF-16LE, NUL padded to 128 units), engineIcon 0, everything else zero; `mvar` 0x7028 version 31 flags 1; `_eof` 0x11 (1.1), value 0x7318 BE.

Stream header (bits): contentType stored 6; fileLength 0x7329; the four ids; activity stored 1; gameMode 4; engine 1; mapID 3006; category 0; two author records (name bytes `41 00`); title and description in UTF-16BE with NUL. Header end = **1255**.
Body: version 31; checksum 0xFFFFFFFF; palette CRC 0xDEADBEEF; quota_count 80; map id copy 3006; built_in 0; built_from_xml 0; bounds (-240, 240, -345, 345, -70, 70) as float32 BE; max budget 30,000; spent budget 123. Axis bits (20, 21, 19) (G-AX-2).
Labels: 3 entries, offsets 0 / 6 / 20, buffer `SCALE\0Kill Boundary\0Spawn\0` (26 bytes), uncompressed.
Quota rows: 80 rows `(0, 0, 0)` except row 61 = `(0, 1, 1)` and row 70 = `(0, 16, 2)`. Tail zero.

| Slot | folder | item | pos cells (x, y, z) | up | angle | parent_raw | shape, dims | spawn_seq | respawn | cached | label | placement | team_raw | color |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 70 (`Block, 1x1`, 0x4600) | 0 | 524288, 1048576, 262144 | global | 8192 | 0 | none | 0 | 0 | 0 | none | 0xCC | 9 | none |
| 5 | 61 (`Kill Boundary`, 0x3D00) | 0 | 123456, 654321, 98765 | global | 8192 | 0 | 3 (box): 0x7FF, 1024, 0, 2046 | -5 (0xFB) | 0 | 26 | 1 | 0x0C | 0 | none |
| 650 | 70 | 0 | 0, 0, 0 | code 436468 | 16383 | 2 (parent slot 1) | none | 0 | 0 | 0 | 2 | 0xCC | 9 | 7 |

All other slots are absent. `flags2 = 1`, `in_bounds = 1` everywhere.

### C.2 Golden numbers (salted_be32 flavour unless stated; stored length big-endian)

| Item | Value |
|---|---|
| file length | 29,481 bytes |
| section start bits | header 0; body fixed 1,255; labels 1,626; slots 1,896; quota table 3,050; end 4,970 |
| slot bit ranges | slot 0 [1896, 1897); slot 1 [1897, 2038) = 141 bits; slots 2 to 4 one bit each; slot 5 [2041, 2234) = 193 bits; slots 6 to 649 one bit each (644 bits); slot 650 [2878, 3050) = 172 bits; quota table [3050, 4970) = 80 x 24 |
| L | ceil(4970 / 8) = **622** |
| stored SHA-1 (salted_be32) | `a6183d5f5872d38b6dda0d476ea7d8c8c40641ad` |
| file SHA-256 (salted_be32) | `902d952fdce8b5830e53e96e0ad45926554e1a9e617f753f39bb58a5fd2344e4` |
| stored SHA-1 (plain_le32, stored length still BE) | `cb6d51c253b9d53b82b4faf653c3adc8e1a7afda` |
| file SHA-256 (plain_le32) | `9e11095033b8356e7f772a2f615ceb77ba7e49b18c047f3826ac1da7a62ddbc5` |

### C.3 Golden edits (all on the salted_be32 W1)

| Edit | Description | End bit | L | Stored SHA-1 | File SHA-256 |
|---|---|---|---|---|---|
| E1 | move slot 1 by +1.0 world unit in x: x cell 524,288 -> **526,473**; nothing else | 4,970 | 622 | `770d7849af8a19d13deb739ea8fd97d77da956d7` | `32296dac74f00aea41f16859052f27a5230c29a556ddcc3b3edcefb19b64cf32` |
| E2 | add a `Block, 1x1` into the lowest free slot (0) at cells (1, 2, 3), forward along world +X (yaw 0, angle 8192, up_global), placement 0xCC, team_raw 9, no label/colour/shape; quota row 70 `placed` 2 -> **3** | 5,110 (+140) | 639 | `2749d9b60e6da739d296d18aeec31a0490e9a36a` | `9055a41eb6690c26d53b701a208c4531a7c239c474b7911147399a460b78a08d` |
| E3 | delete slot 5 (the kill boundary): the 193-bit record becomes one 0 bit; quota row 61 `placed` 1 -> **0** | 4,778 (-192) | 598 | `89a171193839cb0b9ec718db061295c9cb176819` | `6e3f948488c5a9ed4d0c0febdcb859738d8d28571860566ab4d0d2081ae4058f` |

Interpretation in Blender terms (B-18): E1 = move the object named `1 - Block, 1x1` by (+1, 0, 0) (its position decodes to x = 0.0002288818359375, so the new x 1.0002288818359375 falls in cell 526,473); E2 = add `Block, 1x1` at the cell-centre coordinates of cells (1, 2, 3), the rotation gate on, default properties (physics PHASED -> 0xCC, team NEUTRAL -> raw 9, colour Team), and rotated so that its forward (local +Y) points along world +X (`rotation_euler.z = -pi/2`); E3 = delete `5 - Kill Boundary`. An unrotated Add has forward (0, 1, 0), yaw +pi/2 and raw angle 12288 (`S`); that is the different golden **E2b**: same end bit 5,110 and L 639, stored SHA-1 `0ebb78f125fd9f1dc8ec2cea072433f3b6082c77`, file SHA-256 `851d42b8dc49182db799d0ee573dc30531be7992944e8406d6f6fc2adabb3fdd`. B-18 asserts E2 (the rotated add); a variant may assert E2b for the unrotated one.

Reading the file as a game would: with the type-19 rule irrelevant (no type-19 object) both type-19 hypotheses accept W1, so `type19 = undetermined`; with axis bits (20, 21, 19) there is one axis hypothesis; the selected hypothesis is `flag8` (preference order) with `undetermined` noted.

### C.4 Header-variant goldens (salted_be32; body and slots as W1, only the UGC header differs)

| Fixture | Header change | Header end | End bit | L | Stored SHA-1 |
|---|---|---|---|---|---|
| `hdr_hopper` | decoded activity 2 (stored 3), hopper id 0x1234 | 1,271 | 4,986 | 624 | `9c8723519aebc42e54a16d5c59fa26b2af1e3615` |
| `hdr_campaign` | gameMode 1; id 5, difficulty 2, metagame 1, rally 7, unk 0x01020304 | 1,307 | 5,022 | 628 | `e7495f21fa80a3d6f763a7ded50a1535edfce855` |
| `hdr_firefight` | gameMode 2; difficulty 3, unk 0xA0B0C0D0 | 1,289 | 5,004 | 626 | `2db181cdbab88900a4812b2a30d6e53083b84a24` |
| `hdr_long_text` | both author names 16 chars with no NUL; title and description 128 units with no NUL | 4,951 | 8,666 | 1,084 | `34925a9213e04d13caf9187778b3f76a4233f343` |
| `hdr_min_text` | author names `00` (only the NUL); empty title and description | 647 | 4,362 | 546 | `1a45c8a3b33c8e1c444409ce2e7371ebafa15b4c` |

The first three rows were computed by the format lint's independent builder and reproduced by the spec author's builder in the revision pass (`S`); the last two come from the spec author's builder only (their header ends 4,951 and 647 also follow from the formula of 3.2). The `chdr` block is set to match (activity byte, campaign fields) and does not enter the stream SHA-1, so no file SHA-256 is listed. These fixtures pin the widths this document states; they cannot show that the game uses the same widths (`I`, 3.2).

---------------------------------------------------------------------------------------------------

## Appendix D. Source index (where each cited fact lives)

| Short name | Path |
|---|---|
| JS | `~/Documents/Halo_MCC/halo-reach-variant-tool/html/src/raw/map_variant_mvar.js` (846 lines): axis bits 79-150; shape 152-286; position 289-330; up axis 331-455; angle 456-565; slot 566-643; header 702-744; body 745-769; labels 771-827; slots 831-833; quota 837-845 |
| RVT | `~/Documents/Halo_MCC/halo-reach-variant-tool/native/src/ReachVariantTool/`: `formats/ugc_header.cpp` (15-53 read, 87-121 write), `ugc_header.h` (13-31 enums, 51), `content_author.cpp`, `compressed_float.h`, `localized_string_table.{h,cpp}`, `sha1.h` (salt), `block.cpp` (24-51 header, 152-184 `_cmp`), `game_variants/base.cpp` (30-46 `_eof`, 144-165 and 243-278 hash, 383 chdr note), `helpers/bitreader.cpp`, `ui/script_editor/page_map_perms.cpp` (15-58) |
| Mjolnir | `~/Documents/Halo_MCC/mjolnir-forge-editor/source/`: `Blender (Download a Release, Not Me!)/forge.py` v0.9.9.2 (1436 lines), `Addon/{mjolnir,objects,TwoWayDict,__init__,parse_palette}.py`, `ForgeLib/{ForgeObject,Map,ItemParser,ForgeBridge}.cs`, `NOTES.md`, `tools/check_no_game_assets.py` |
| Real samples | `~/Documents/Halo_MCC/halo-reach-variant-tool/test-samples/*.bin` (3), `~/Documents/Halo_MCC/halo-reach-variant-tool/macos/Fixtures/*.bin` (5) |
| Research (session scratchpad, outside the repo; G0 copies the synthetic reference scripts into `docs/mvar/reference/`) | `/private/tmp/claude-501/-Users-michaelmincone-Local-Documents/6d5fba7a-3008-4537-951e-dacfdc34a893/scratchpad/research/`: `lint-format.md`, `lint-plan.md`, `addon-architecture.md`, `blender-5-2.md`, `container-and-bit-conventions.md`, `object-library-inventory.md`, `upstream-mvar-branch.md`, `web-mvar-format.md`, `critique-format-correctness.md`, `critique-plan-feasibility.md`, `blf_container.py`, `bitio_prototype.py`, `tables/`, `crit_format/`, `crit_plan/`, `spec_w1/` |
| Blender tests (reference) | `.../scratchpad/blender_tests/` (`t07_mock_roundtrip.py`, `t13_ui_draw_mock.py`, `t16_650.py`, `run_suite.sh`, `proto_src/mjolnir_forge/`) |
| Web (facts only) | HMS: `https://raw.githubusercontent.com/Sopitive/HaloMapStudio/HEAD/crates/hms-app/src/mvar.rs` and `.../h4/mvar.rs` (PolyForm Noncommercial); BLF: `https://raw.githubusercontent.com/Blam-Network/blf/HEAD/blf_lib/src/blam/haloreach/v12065_11_08_24_1738_tu1actual/saved_games/scenario_map_variant.rs` (no licence); KSoft.Blam: `https://raw.githubusercontent.com/KornnerStudios/KSoft.Blam/main/KSoft.Blam/Blob/Presentation/GameEngineVariantBlob.cs` (MIT); `https://developer.blender.org/docs/release_notes/5.0/python_api/` |

---------------------------------------------------------------------------------------------------

## Appendix E. Rejected lint items

Two adversarial lint reports (`lint-format.md`: 7 majors and 18 minors on sections 2 to 5 and 7; `lint-plan.md`: 5 blockers, 7 majors and 10 minors on sections 1, 6, 8, 9, 10 and 11) raised 47 defects. Each was checked against the primary source, or reproduced by a script, before it was applied (Appendix A.2). No defect was wrong as a whole; the items below are those where the lint's own remedy, or a sub-claim, was not adopted as written.

| # | Item | What the lint asked | What this spec does, and why |
|---|---|---|---|
| E.1 | M5 (declined part) | when the stored hash is non-zero and matches no candidate, write `plain_le32` instead of `salted_be32` | **Declined.** Binding decision D fixes the salted fallback with a loud warning, and nothing primary contradicts it: the only support for `plain_le32` as "what MCC writes" is one WEB source (HMS), while `salted_be32` is the only recipe reproduced on real files (RVT-written, 0.1 V caveat). Applied from M5: the `zero` flavour (detected, reproduced as zeros, `I_HASH_ZERO`), `ExportOptions.hash_policy` (the owner can choose `PLAIN_LE32`), `--zero-hash` and rung H (2.7, DEC-2.3, 6.4, 9.5). The KSoft.Blam claim itself was re-read and holds for game variants only |
| E.2 | m10 (declined part) | `E_TOO_MANY` only when the count is above the limit and above the template's own count, so an unchanged oversize template passes | **Declined.** Binding decision E says export refuses more than 650 occupied slots, and the 650-object done-criterion has no exception. The contradiction the lint found with the contract note is resolved by correcting the note (6.4: passthrough applies only when steps 1 to 9 of 5.10 collect no error) and by recording the cost in 10.2 item 11: a real map that occupies 651 slots cannot be exported even unchanged. Applied from m10 and P-18: fixtures `full650` and `over650`, B-11 and U-13 cases |
| E.3 | m3 (modified) | refuse every `mvar` chunk version outside {31, 32} | **Modified.** The chunk version of a real MCC Reach map variant has never been seen on this machine (`U`), so refusing unknown values could reject a valid file. The known non-Reach versions (12, 13, 14 for Halo 3; 50, 51 for Halo 4, from `web-mvar-format.md` section 6, not re-fetched) are refused; any other value warns (`W_CHUNK_VERSION_UNEXPECTED`) and the walk decides; a chunk/body mismatch warns (`W_VERSION_MISMATCH`) (2.2, 7.2) |
| E.4 | P-08 (applied, deviation recorded) | imported objects whose id is not in the stock table are refused by default, with an owner opt-in | **Applied.** It narrows the literal wording of binding decision E ("ids that came from the imported file are kept verbatim") in the unrecognised-id case only, because `NOTES.md` D4 ("stock objects only (every object id must exist in the stock palette for that map)", re-read) is the owner's own export limit. Recorded in 1.4 row E and DEC-7.4; flipping the default of `keep_unrecognised_imported` reverts it. A consequence the owner should know: until the id tables are checked against a real file, an unrecognised id blocks even an unchanged export unless the box is ticked |
| E.5 | P-11 (sub-claim corrected) | `ast.parse(feature_version=(3, 9))` does not catch 3.12 f-string quote reuse | **Corrected.** On Blender's Python 3.13.13 the scan does reject it (`SyntaxError`); the finding stands for the seven runtime constructs (`int \| None` annotations, `dataclass(slots=True)`, `zip(strict=True)`, `.bit_count()`, `itertools.pairwise`, `datetime.UTC`, `int.from_bytes(b)`), which the scan cannot see (6.8) |
| E.6 | not re-verifiable here | m3 (Halo 3/4 chunk versions), M5 (HMS: "PlainLe is what MCC writes"), m17 (HMS recomputes `placed`) | Applied as stated and tagged `W:HMS` or `I`; they rest on `web-mvar-format.md` summaries of the HMS source, which this revision did not re-fetch. P-19's optional JS oracle (U-23) was specified, not run: `node` v26.0.0 exists, but loading Cobb's script (it depends on helper scripts in the same folder) was not tried |

---------------------------------------------------------------------------------------------------

## Appendix F. Change log vs first draft

First draft: v1.0, 2,056 lines (kept as `.../scratchpad/spec_backup/SPEC.first-draft.md`). This revision: v1.1. Of the 47 lint defects, **42 were applied as written, 3 applied with a modification (m3, P-08, P-11) and 2 applied in part with the contested remedy declined (M5, m10)**; none was dropped without a trace (Appendix E). Section structure is unchanged except for the new 9.8 and Appendices A.2, E and F.

| Lint id | Sev. | Where changed | Change |
|---|---|---|---|
| M1 | major | 3.3, 3.10 rule 3(f), 4.2, 7.2, 7.3, Appendix B | a zero-range axis (`min == max`) is accepted (`W_ZERO_RANGE_AXIS`, DEC-3.6); only `min > max` or non-finite is `FormatError`; moving or adding on that axis gives `E_OUT_OF_BOUNDS`; this makes the `extremes` fixture and G-AX-4 consistent |
| M2 | major | 1.4 row A, 2.8, 2.10, 2.11, 5.2, 6.6, 9.1, U-08, G2, G3 | forced re-encode of a `_cmp` shape is the expanded form (DEC-2.6); T2 asserts passthrough, golden `<name>_expanded` and re-parse equality for those shapes |
| M3 | major | 4.7, B-18, Appendix C.3 | golden E2 needs the added object rotated (`rotation_euler.z = -pi/2`); the unrotated add is the new golden E2b (raw 12288, SHA-1 `0ebb78f1...`) |
| M4 | major | 3.5, 3.8, 3.10, 6.7, 7.3, U-09, G2 | `guid_present` is a third hypothesis dimension, version-implied value first and winning when accepted; `W_GUID_VERSION_MISMATCH`; fixtures `guid_v32_absent`, `guid_v31_present` |
| M5 | major | 0.1/1.2/1.5 (X8, X25), 2.7, 2.12, 6.3, 6.4, 6.7, 7.3, 9.3, 9.5, Appendix B | new `zero` hash recipe and length class, DEC-2.3 rewritten, `ExportOptions.hash_policy`, `I_HASH_ZERO`, `--zero-hash` probe; plain_le32 fallback declined (E.1) |
| M6 | major | 0.1, 1.2 (hash and length rows), 3.4 | V caveat added: the 8 samples are RVT-written fixtures, V does not show what the game writes |
| M7 | major | 3.2, G2, U-07, Appendix C.4 | fixtures and goldens for hopper, campaign, firefight, long and minimal text; cross-checked with a second builder |
| m1 | minor | 3.2 | `hopperID` is tested on the decoded activity (stored 3); "matchmaking" removed |
| m2 | minor | 2.1, 2.10, 7.3 | bytes after `_eof` parsed as blocks or kept as an opaque trailer (`W_TRAILER_KEPT`) |
| m3 | minor | 2.2, 3.3, 7.2, 7.3, 1.5 X26 | chunk-version policy (modified, E.3) |
| m4 | minor | 3.6, 4.2 | slot sizes 128 / 141 / 144 / 150 / 235 (224) and "2 to 4 cells" |
| m5 | minor | 3.1 | reader widths 0 to 64 |
| m6 | minor | 4.5 | `N = isqrt(STRIDE) - 1` (17 of 17 JS rows), not `N^2 <= STRIDE` |
| m7 | minor | 4.7 | forward spelled out as (1.0, 0.000192, 0) |
| m8 | minor | 3.10 rule 4, 4.5 | only `u` can exceed 416 |
| m9 | minor | 3.4, 9.1, U-04 | 4 of 5 distinct files have a compressed table; "Blender 3.13.13" corrected |
| m10 | minor | 6.4 contract note, 7.3 `E_TOO_MANY`, 10.2 item 11 | limit stays unconditional; the contract note corrected (E.2) |
| m11 | minor | 4.8 (6), 5.10 step 3, 7.3 | `E_TRANSFORM_INVALID` for non-finite or zero-length vectors |
| m12 | minor | 8.3 | `map_id_hex`; no u32 stored as a Blender int |
| m13 | minor | 6.3, U-01 | `BitWriter.write` raises on a value that does not fit; `write_signed`, `write_masked` |
| m14 | minor | 3.10 rule 3 | label-entry and `folder < quota_count` checks tagged `I`, named in diagnostics, `--lenient` disables them |
| m15 | minor | 2.9, 5.10 steps 8, 10, 11 | `E_CAPACITY` found in step 8; `fsm_policy = DROP` counts as a modification |
| m16 | minor | 2.11, 2.12, 5.4 | class `zero` for a stored length of 00 00 00 00; pad bytes copied from the template |
| m17 | minor | 3.10 rule 4, 5.4 step 3 | HMS's recompute of `placed` noted as indirect evidence; delta rule kept |
| m18 | minor | 4.1, 6.3, G-AX-3, G-AX-6 | third axis-bit variant `ceil_f32` with its own threshold vectors |
| P-01 | blocker | new 9.8, U-21, 6.7, 9.2, G7 | done-criteria acceptance sheet, `tools/accept.sh`, `run_blender_tests.sh`, "originals untouched" test |
| P-02 | blocker | G0, G7, 6.7, 8.10, U-17b, DEC-6.1, DEC-F.2 | guard scans gitignored files; tools may not write anywhere in the repo; acceptance uses `git status --ignored --short` |
| P-03 | blocker | 6.1, 6.4, G0, G3, G5, U-22 | `api.py` complete at G0 with lazy delegation to `entry.py`; freeze = SHA-256 of `api.py` and `errors.py` (DEC-6.4) |
| P-04 | blocker | 6.4, 8.1, 8.4, 8.5 | error classes re-exported from `api.py`; the glue calls `P.load_map_variant`, `P.export_map_variant`, catches `P.MvarError` |
| P-05 | blocker | 0.2, 6.7, 8.1, 8.10, 9.4, R10, G7, DEC-8.10 | default zip contains no game asset; `--with-library` needs an explicit flag; library found by preference, `$MJOLNIR_LIBRARY` or in place |
| P-06 | major | 6.1, 6.4, cross-gate stub, G0, G3, G4, G5 | five helpers in `api.py`; `tables.py`, `io.py` move to G0; stub gains `CANNED_BY_MAP`, `NEXT_LOAD`, `CANNED_EXTREMES`, `CANNED_PLACEMENT_ALL`; ownership overlaps removed |
| P-07 | major | 8 intro, G4, G6, G7 | B-21 in G4; B-03 split into B-03 (G4) and `b03r_persist_real` (G6); legacy scripts dropped; GUI checklist recorded in G7 |
| P-08 | major | 1.4 row E, 7.3, 7.4, 8.5, 8.8, 6.4, U-13, DEC-7.4 | imported unrecognised ids refused by default, owner opt-in (applied with a recorded deviation, E.4) |
| P-09 | major | 8.5, 8.7, 7.3, B-10, B-16 | pass B first; unevaluated array parents refused with `E_ARRAY_NOT_EVALUATED` |
| P-10 | major | 8.3, B-02, B-16, G2 | `map_id_hex`; fixture `unknown_map` |
| P-11 | major | 6.8, 9.2, U-19 | import-under-3.9.6 plus an AST lint; `PY39=/usr/bin/python3`; forbidden list corrected (E.5) |
| P-12 | major | G0, G1, Appendix C and D | spec and synthetic reference scripts committed under `docs/mvar/` |
| P-13 | minor | B-03 | the driver-namespace assertion names the keys it forbids |
| P-14 | minor | 2.13, 8.5 | default export path falls back to `~/Documents/Mjolnir Exports/` |
| P-15 | minor | 9.3, G1, G2 | `tests/unit/` instead of `tests/mvarlib/` |
| P-16 | minor | 6.7, DEC-6.1, U-16 | all tools write through `write_atomic` |
| P-17 | minor | 9.4, 9.2, 6.7 | `mktemp -d`, no `rm -rf`, bash with `pipefail`, no piping of the Blender command |
| P-18 | minor | G2, 6.4, B-09, B-11, B-16 | fixtures `full650`, `over650`, `unknown_map`; contract note reworded |
| P-19 | minor | 9.1, U-23, R11 | optional JS oracle test |
| P-20 | minor | 8.4 | confirmation before replacing the map variant already in the scene |
| P-21 | minor | 8.10, G7 | build refuses placeholder maintainer text without `--allow-placeholders`; `bl_info` is not stripped |
| P-22 | minor | 3.9, 5.6 | new-object property precedence against the learned baseline; mismatches refused, never dropped |

**New in v1.1** (everything above that did not exist before): section 9.8; Appendices A.2, E, F and C.4; tests U-21, U-22, U-23 and U-17b; tools `accept.sh`, `accept_real_mvar.sh`, `run_blender_tests.sh`, `tests/py39_lint.py`; modules `entry.py` (and `tables.py`, `io.py` moved to G0); issue codes `E_TRANSFORM_INVALID`, `E_ARRAY_NOT_EVALUATED`, `W_GUID_VERSION_MISMATCH`, `W_VERSION_MISMATCH`, `W_CHUNK_VERSION_UNEXPECTED`, `W_ZERO_RANGE_AXIS`, `W_TRAILER_KEPT`, `I_HASH_ZERO`; options `hash_policy` and `keep_unrecognised_imported`; decisions DEC-2.6, DEC-3.6, DEC-6.4, DEC-7.4, DEC-9.4, DEC-G0.1, DEC-F.2 (and changed DEC-2.3, DEC-2.5, DEC-3.10, DEC-6.1, DEC-8.10); conflicts X25 and X26; golden vectors G-AX-6, E2b and the five header variants; fixtures `full650`, `over650`, `unknown_map`, `zero_hash`, `guid_v32_absent`, `guid_v31_present`, `trailer`, `hdr_*`, `chunk_version_50`, `chunk_version_13`, `bounds_inverted`.

**Unchanged:** the binding decisions A to G (with the two recorded refinements of A for `_cmp` shapes and of E tier 1), the tier structure T1 to T4, the evidence tags, the codec formulas and golden vectors of section 4 apart from the additions above, the W1 numbers E1, E3 and the base fixture, and the gate order G0 to G7.

