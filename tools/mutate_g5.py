#!/usr/bin/env python3
"""Mutation check of the G5 write path and its tests (proof that U-10 write, U-11, U-12, U-13 and T3-real write bite).

    python3 -I tools/mutate_g5.py [--python PATH] [--jobs N] [--list] [--check-patterns] [NAME_SUBSTRING ...]

Copies ``Addon/mvarlib``, the glue files the validation test reads, the tools, the fixture builder, the golden data, the spec
and the G3/G5 tests into a fresh temporary directory PER MUTANT (never inside the repository), applies ONE source mutation
(a changed tolerance, a dropped check, a swapped order, a wrong width, a lost warning ...), runs the tests that should notice it
with ``tools/run_tests.py --samples --only ...`` and reports whether the tests KILLED the mutant (a test failed) or it
SURVIVED. The real sources and the sample files (including the real map variant) are only read.

``--jobs N`` runs N mutants at the same time (each in its own sandbox). ``--check-patterns`` only verifies that every mutation
applies (its old text occurs exactly once) and runs nothing. Exit status: 0 when every mutant that is not listed in
``EQUIVALENT`` was killed, 1 otherwise, 2 when the unmutated baseline is not green.
"""
import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EDITS = ["test_edits_bitdiff", "test_identity", "test_validation", "test_container_write", "test_edit_rules"]
REAL = EDITS + ["test_real_mvar_write"]
CLI = ["test_reencode_cli"]
G5_TESTS = ("helpers_snapshot.py", "helpers_real.py", "helpers_fixtures.py", "helpers_g3.py", "helpers_g5.py",
            "test_edits_bitdiff.py", "test_identity.py", "test_validation.py", "test_container_write.py", "test_edit_rules.py",
            "test_real_mvar_write.py", "test_reencode_cli.py", "test_roundtrip_forced.py", "test_container_variants.py")
GLUE_FILES = ("mjolnir.py", "io_ops.py", "state.py")

# Mutants that cannot change any observable result (reason next to each).
EQUIVALENT = (
    # the callers only ask about values that already differ from the baseline, and a baseline is always inside its own field width
    "validate: other_a / other_b of an unchanged value are range checked too",
    # an up vector whose angle to +Z is EXACTLY 1e-4 rad cannot be built in floating point, so `>` against `>=` never differs
    "edit: the up vector tolerance is exclusive",
    # object names are unique per map (tests/unit/test_tables.py), so a name that differs from the slot's own never resolves to the slot's id
    "edit: a resolved id equal to the slot's still retargets",
    # verification guards: they state what the writer must never do, and an honest writer never trips them, so no correct input can show
    # the difference; the guards that CAN be reached by a faulty writer are proven by the fault-injection tests (TestVerificationBites)
    "edit: verification: layout hypothesis comparison removed",   # the re-parse is restricted to the planned hypothesis, so it cannot differ
    "edit: verification: end bit comparison removed",             # follows from the slots and quota rows, which are compared one by one
    "edit: verification: untouched slot guard removed",           # implied by the guard before it (every slot equals the plan)
)

# (name, file relative to Addon/mvarlib, old text (must occur exactly once), new text, --only substrings)
MUTANTS = [
    # --- validate.py -------------------------------------------------------------------------
    ("validate: angle tolerance 1e-3", "validate.py", "ANG_TOL = 1.0e-4 ", "ANG_TOL = 1.0e-3 ", EDITS),
    ("validate: angle tolerance 1e-5", "validate.py", "ANG_TOL = 1.0e-4 ", "ANG_TOL = 1.0e-5 ", EDITS),
    ("validate: shortest vector 1e-5", "validate.py", "MIN_VECTOR_LENGTH = 1.0e-6 ", "MIN_VECTOR_LENGTH = 1.0e-5 ", EDITS),
    ("validate: shortest vector 1e-7", "validate.py", "MIN_VECTOR_LENGTH = 1.0e-6 ", "MIN_VECTOR_LENGTH = 1.0e-7 ", EDITS),
    ("validate: the up vector length is not checked", "validate.py",
     "    return _length(obj.forward) >= MIN_VECTOR_LENGTH and _length(obj.up) >= MIN_VECTOR_LENGTH",
     "    return _length(obj.forward) >= MIN_VECTOR_LENGTH", EDITS),
    ("validate: the forward vector length is not checked", "validate.py",
     "    return _length(obj.forward) >= MIN_VECTOR_LENGTH and _length(obj.up) >= MIN_VECTOR_LENGTH",
     "    return _length(obj.up) >= MIN_VECTOR_LENGTH", EDITS),
    ("validate: the up vector is not tested for finiteness", "validate.py",
     "finite_vec(obj.position) and finite_vec(obj.forward) and finite_vec(obj.up)", "finite_vec(obj.position) and finite_vec(obj.forward)", EDITS),
    ("validate: the position is not tested for finiteness", "validate.py",
     "finite_vec(obj.position) and finite_vec(obj.forward) and finite_vec(obj.up)", "finite_vec(obj.forward) and finite_vec(obj.up)", EDITS),
    ("validate: a vertical forward still has a yaw", "validate.py",
     "    if math.hypot(forward[0], forward[1]) < MIN_VECTOR_LENGTH * _length(forward):\n        return None\n",
     "    if False:\n        return None\n", EDITS),
    ("validate: orientation unchanged needs only one vector", "validate.py",
     "angle_between(obj.forward, base_forward) <= ANG_TOL and angle_between(obj.up, base_up) <= ANG_TOL",
     "angle_between(obj.forward, base_forward) <= ANG_TOL or angle_between(obj.up, base_up) <= ANG_TOL", EDITS),
    ("validate: physics 2 is not normal", "validate.py", "    return 0 if value == 2 else value", "    return value", EDITS),
    ("validate: a shape kind is never out of range", "validate.py",
     "    if shape is None or shape not in DIM_NAMES and shape != 0:", "    if shape is None:", EDITS),
    ("validate: dimension 200 is refused", "validate.py", "0.0 <= value <= 200.0", "0.0 <= value < 200.0", EDITS),
    ("validate: dimension 0 is refused", "validate.py", "0.0 <= value <= 200.0", "0.0 < value <= 200.0", EDITS),
    ("validate: spawn sequence -128 is refused", "validate.py", "not (-128 <= seq <= 127)", "not (-128 < seq <= 127)", EDITS),
    ("validate: spawn time 255 is refused", "validate.py", "not (0 <= spawn <= 255)", "not (0 <= spawn < 255)", EDITS),
    ("validate: team 8 is refused", "validate.py", "if team is None or not 0 <= team <= 8:", "if team is None or not 0 <= team < 8:", EDITS),
    ("validate: colour 7 is neutral", "validate.py", "    if color == 8:", "    if color == 7:", EDITS),
    ("validate: team colour (-1) is refused", "validate.py", "elif color is None or not -1 <= color <= 7:", "elif color is None or not 0 <= color <= 7:", EDITS),
    ("validate: label -1 is refused", "validate.py", "if label is None or label < -1 or", "if label is None or label < 0 or", EDITS),
    ("validate: label equal to the count is accepted", "validate.py", "label >= label_count or not label_present[label]", "label > label_count or not label_present[label]", EDITS),
    ("validate: an absent label entry is accepted", "validate.py", "label >= label_count or not label_present[label]", "label >= label_count", EDITS),
    ("validate: physics 2 is refused", "validate.py", "physics not in (0, 1, 2, 3)", "physics not in (0, 1, 3)", EDITS),
    ("validate: weapon clips fit 7 bits", "validate.py", "        return 0, 255, 0\n    if 12 <= cached_type <= 14:", "        return 0, 127, 0\n    if 12 <= cached_type <= 14:", EDITS),
    ("validate: teleporter passability fits 4 bits", "validate.py", "        return 0, 31, 31", "        return 0, 31, 15", EDITS),
    ("validate: teleporter classes stop at 13", "validate.py", "    if 12 <= cached_type <= 14:\n        return 0, 31, 31", "    if 12 <= cached_type <= 13:\n        return 0, 31, 31", EDITS),
    ("validate: location index limits swapped", "validate.py", "return -1, (254 if type19_rule == \"plain8\" else 255), 0",
     "return -1, (255 if type19_rule == \"plain8\" else 254), 0", EDITS),
    ("validate: other_a / other_b of an unchanged value are range checked too", "validate.py",
     "        if only_if_changed is not None and v == only_if_changed[index]:\n            continue\n", "", EDITS),
    ("validate: quota ceiling 255 is refused", "validate.py", "    if new > 255:", "    if new >= 255:", EDITS),
    ("validate: a shrinking row above its maximum is refused", "validate.py", "    if new > maximum and new > old:", "    if new > maximum:", EDITS),
    ("validate: a row at its maximum is refused", "validate.py", "    if new > maximum and new > old:", "    if new >= maximum and new > old:", EDITS),
    ("validate: the option does not raise", "validate.py", "        if raise_max:\n            return None, new\n", "        if False:\n            return None, new\n", EDITS),
    ("validate: the option raises to the old maximum", "validate.py", "            return None, new\n", "            return None, maximum\n", EDITS),
    ("validate: a growing row below its minimum is refused", "validate.py", "    if new < minimum and new < old:", "    if new < minimum:", EDITS),
    ("validate: a row at its minimum is refused", "validate.py", "    if new < minimum and new < old:", "    if new <= minimum and new < old:", EDITS),
    ("validate: the palette name uses the item byte", "validate.py", "        if (type_id >> 8) == folder:", "        if (type_id & 0xFF) == folder:", EDITS),
    ("validate: the unknown palette name", "validate.py", "    return \"Unknown\"", "    return \"unknown\"", EDITS),
    ("validate: integral floats are not integers", "validate.py", "value == int(value)", "False", EDITS),
    ("validate: message of E_QUOTA", "validate.py", "would have %d placed; the maximum on this map variant is %d.", "would have %d placed; the maximum on this map is %d.", EDITS),
    ("validate: message of E_OUT_OF_BOUNDS", "validate.py", "Move it inside; positions are never clamped.", "Move it inside; positions are clamped.", EDITS),
    ("validate: message of W_QUOTA_MAX_RAISED", "validate.py", "Quota maximum raised: unverified.", "Quota maximum raised.", EDITS),
    ("validate: E_FLAG_UNVERIFIED names the glue source differently", "validate.py", "cannot be changed yet; how it is stored is unverified.", "cannot be changed.", EDITS),
    # --- edit.py: helpers --------------------------------------------------------------------
    ("edit: learned class ignores the exact type", "edit.py",
     "    same = set(s.cached_type for s in present if s.folder == folder and s.item == item)\n    if len(same) == 1:\n        return next(iter(same))\n    same = set(",
     "    same = set(s.cached_type for s in present if s.folder == folder and s.item == item)\n    if False:\n        return next(iter(same))\n    same = set(", EDITS),
    ("edit: learned class has no folder fallback", "edit.py",
     "    same = set(s.cached_type for s in present if s.folder == folder)\n    if len(same) == 1:\n        return next(iter(same))\n    return None",
     "    return None", EDITS),
    ("edit: learned class of the exact type takes any item", "edit.py",
     "    same = set(s.cached_type for s in present if s.folder == folder and s.item == item)\n    if len(same) == 1:",
     "    same = set(s.cached_type for s in present if s.folder == folder)\n    if len(same) == 1:", EDITS),
    ("edit: an ambiguous class is learned anyway", "edit.py",
     "    same = set(s.cached_type for s in present if s.folder == folder)\n    if len(same) == 1:\n        return next(iter(same))\n    return None",
     "    same = set(s.cached_type for s in present if s.folder == folder)\n    if same:\n        return min(same)\n    return None", EDITS),
    ("edit: learned example has no folder fallback", "edit.py",
     "    if not pool:\n        pool = [s for s in present if s.folder == folder]\n    if not pool:\n        return None\n",
     "    if not pool:\n        return None\n", EDITS),
    ("edit: learned example is the least common", "edit.py", "key=lambda key: (-counts[key], first[key]))[0]", "key=lambda key: (counts[key], first[key]))[0]", EDITS),
    ("edit: learned example breaks ties by the highest slot", "edit.py", "key=lambda key: (-counts[key], first[key]))[0]", "key=lambda key: (-counts[key], -first[key]))[0]", EDITS),
    ("edit: learned example ignores the colour", "edit.py", "        key = (s.placement, s.team_raw, s.color)", "        key = (s.placement, s.team_raw, None)", EDITS),
    ("edit: the end-bit estimate forgets the quota rows", "edit.py", "    return total + QUOTA_ROW_BITS * len(model.quotas)", "    return total", EDITS),
    ("edit: the end-bit estimate forgets the guid block", "edit.py", "    if model.guid is not None:\n        total += model.guid.nbits\n", "", EDITS),
    ("edit: the end-bit estimate forgets the label table", "edit.py", "model.header.raw.nbits + model.fixed.raw.nbits + model.labels.raw.nbits", "model.header.raw.nbits + model.fixed.raw.nbits", EDITS),
    ("edit: palette groups ignore the parent groups", "edit.py", "walk(group, path + [group.get(\"name\", \"\")])", "walk(group, [group.get(\"name\", \"\")])", EDITS),
    ("edit: a leaf needs only one assumed path", "edit.py", "return all(any(g in assumed for g in path) for path in paths)", "return any(any(g in assumed for g in path) for path in paths)", EDITS),
    ("edit: an unlisted leaf is assumed", "edit.py", "        if not paths:\n            return False\n", "        if not paths:\n            return True\n", EDITS),
    ("edit: header comparison ignores the whole header", "edit.py", "    return (a.to_int() & ~mask) == (b.to_int() & ~mask)", "    return True", EDITS),
    ("edit: header comparison ignores nothing", "edit.py", "    return (a.to_int() & ~mask) == (b.to_int() & ~mask)", "    return a.to_int() == b.to_int()", EDITS),
    # --- edit.py: identity and deletions -----------------------------------------------------
    ("edit: the token bit count is not compared", "edit.py", "bytes(obj.token_raw) == slot.raw.data and obj.token_bits == slot.raw.nbits", "bytes(obj.token_raw) == slot.raw.data", EDITS),
    ("edit: the token bytes are not compared", "edit.py", "bytes(obj.token_raw) == slot.raw.data and obj.token_bits == slot.raw.nbits", "obj.token_bits == slot.raw.nbits", EDITS),
    ("edit: a missing token matches", "edit.py", "        if obj.token_raw is None or obj.token_bits is None or slot.raw is None:\n            return False\n", "", EDITS),
    ("edit: an absent slot can be claimed", "edit.py", "0 <= index < SLOT_COUNT and m.slots[index].present\n", "0 <= index < SLOT_COUNT\n", EDITS),
    ("edit: duplicates ignore the name match", "edit.py", "            if len(matching) == 1:\n                keeper = matching[0]\n", "            if False:\n                keeper = matching[0]\n", EDITS),
    ("edit: several name matches are not narrowed", "edit.py", "pool = matching if len(matching) > 1 else claimants", "pool = claimants", EDITS),
    ("edit: the pose distance ignores the orientation", "edit.py", "        rot = V.angle_between(obj.forward, rec.forward) + V.angle_between(obj.up, rec.up)", "        rot = 0.0", EDITS),
    ("edit: the pose distance ignores the position", "edit.py", "        return (round(pos, 9), round(rot, 9))", "        return (0.0, round(rot, 9))", EDITS),
    ("edit: ties go to the largest name", "edit.py", "key=lambda o: self._pose_distance(o, m.slots[index]) + (o.name,))", "key=lambda o: self._pose_distance(o, m.slots[index]) + (tuple(-ord(c) for c in o.name),))", EDITS),
    ("edit: duplicate losers are not sorted", "edit.py", "            for obj in sorted(claimants, key=lambda o: o.name):\n                if obj is not keeper:", "            for obj in claimants:\n                if obj is not keeper:", EDITS),
    ("edit: not imported slots are deleted", "edit.py", "                if imported is None or s.index in imported:", "                if True:", EDITS),
    ("edit: nothing is ever deleted", "edit.py", "                if imported is None or s.index in imported:\n                    deleted.append(s.index)", "                if False:\n                    deleted.append(s.index)", EDITS),
    ("edit: a delete raises the quota row", "edit.py", "self.quota_delta[slot.folder] = self.quota_delta.get(slot.folder, 0) - 1", "self.quota_delta[slot.folder] = self.quota_delta.get(slot.folder, 0) + 1", EDITS),
    ("edit: a delete leaves the quota row alone", "edit.py", "            if slot.folder is not None:\n                self.quota_delta[slot.folder]", "            if False:\n                self.quota_delta[slot.folder]", EDITS),
    ("edit: the parent of slot 0 is not cleared", "edit.py", "s.present and s.parent_raw >= 1 and", "s.present and s.parent_raw >= 2 and", EDITS),
    ("edit: the parent link is off by one", "edit.py", "(s.parent_raw - 1) in gone:", "s.parent_raw in gone:", EDITS),
    ("edit: parent links are never cleared", "edit.py", "                    s.parent_raw = 0\n                    self.warnings.append(V.make(\"W_PARENT_CLEARED\"", "                    self.warnings.append(V.make(\"W_PARENT_CLEARED\"", EDITS),
    ("edit: a cleared parent is not reported", "edit.py", "                    self.warnings.append(V.make(\"W_PARENT_CLEARED\", s.index, parent, slot=s.index))", "                    pass", EDITS),
    # --- edit.py: positions, orientation, flags ----------------------------------------------
    ("edit: the position tolerance is exclusive", "edit.py", "abs(v - base_position[k]) <= codecs.pos_tolerance(axes[k], mn, mx)", "abs(v - base_position[k]) < codecs.pos_tolerance(axes[k], mn, mx)", REAL),
    ("edit: every moved axis is written", "edit.py", "            if base_position is not None and abs(v - base_position[k])", "            if base_position is not None and False and abs(v - base_position[k])", EDITS),
    ("edit: the upper bound is inclusive", "edit.py", "            if not (mn <= v < mx):\n                outside = True", "            if not (mn <= v <= mx):\n                outside = True", REAL),
    ("edit: the lower bound is exclusive", "edit.py", "            if not (mn <= v < mx):\n                outside = True", "            if not (mn < v < mx):\n                outside = True", REAL),
    ("edit: positions are clamped", "edit.py", "            if not (mn <= v < mx):\n                outside = True\n                continue\n", "            v = min(max(v, mn), mx - 1e-6)\n", EDITS),
    ("edit: the bounds message shows the wrong position", "edit.py", "pos[0], pos[1], pos[2], b[0], b[1], b[2], b[3], b[4], b[5]", "pos[1], pos[0], pos[2], b[0], b[1], b[2], b[3], b[4], b[5]", EDITS),
    ("edit: a tilted up vector is accepted", "edit.py", "if V.angle_between(obj.up, UP_Z) > V.ANG_TOL or V.yaw_of(obj.forward) is None:", "if V.yaw_of(obj.forward) is None:", EDITS),
    ("edit: a vertical forward is accepted", "edit.py", "if V.angle_between(obj.up, UP_Z) > V.ANG_TOL or V.yaw_of(obj.forward) is None:", "if V.angle_between(obj.up, UP_Z) > V.ANG_TOL:", EDITS),
    ("edit: the up vector tolerance is exclusive", "edit.py", "V.angle_between(obj.up, UP_Z) > V.ANG_TOL or", "V.angle_between(obj.up, UP_Z) >= V.ANG_TOL or", EDITS),
    ("edit: the rotation gate is ignored", "edit.py", "        if not self.options.allow_unverified_rotation:\n            self.err(self.errors_object, \"E_ROTATION_GATED\"", "        if False:\n            self.err(self.errors_object, \"E_ROTATION_GATED\"", EDITS),
    ("edit: the yaw is written with the wrong sign", "edit.py", "return codecs.angle_encode(V.yaw_of(obj.forward))", "return codecs.angle_encode(-V.yaw_of(obj.forward))", EDITS),
    ("edit: a changed orientation is never written", "edit.py", "                changes[\"up_global\"], changes[\"up_code\"], changes[\"angle\"] = 1, None, angle", "                pass", EDITS),
    ("edit: the up code is kept after a yaw", "edit.py", "changes[\"up_global\"], changes[\"up_code\"], changes[\"angle\"] = 1, None, angle", "changes[\"angle\"] = angle", EDITS),
    ("edit: symmetry changes are accepted", "edit.py", "        if V.to_int(obj.symmetry) != symmetry:\n", "        if False:\n", EDITS),
    ("edit: place-at-start changes are accepted", "edit.py", "        if bool(obj.place_at_start) != bool(place_at_start):\n", "        if False:\n", EDITS),
    ("edit: game-specific changes are accepted", "edit.py", "        if bool(obj.game_specific) != bool(game_specific):\n", "        if False:\n", EDITS),
    ("edit: neutral over none counts as a change", "edit.py", "        return not (new_team == base_team or (base_team == -1 and new_team == codecs.TEAM_NEUTRAL))", "        return not (new_team == base_team)", EDITS),
    ("edit: any team over none counts as unchanged", "edit.py", "(base_team == -1 and new_team == codecs.TEAM_NEUTRAL)", "(base_team == -1)", EDITS),
    ("edit: physics changes are ignored", "edit.py", "        if physics != V.physics_norm(rec.physics):\n            changes[\"placement\"]", "        if False:\n            changes[\"placement\"]", EDITS),
    ("edit: physics replaces the whole placement byte", "edit.py", "changes[\"placement\"] = codecs.placement_with_physics(slot.placement, physics)", "changes[\"placement\"] = physics << 6", EDITS),
    ("edit: a shape change is ignored when only the codes differ", "edit.py", "        if shape != slot.shape or codes != slot.dims:", "        if shape != slot.shape:", EDITS),
    ("edit: a label change is ignored", "edit.py", "        if (None if label == -1 else label) != slot.label:", "        if False:", EDITS),
    ("edit: a spawn sequence change is ignored", "edit.py", "        if seq != slot.spawn_seq:", "        if False:", EDITS),
    ("edit: a spawn time change is ignored", "edit.py", "        if spawn != slot.respawn:", "        if False:", EDITS),
    ("edit: a colour change is ignored", "edit.py", "        if color != rec.color:\n            changes[\"color\"]", "        if False:\n            changes[\"color\"]", EDITS),
    ("edit: a team change is ignored", "edit.py", "        if self._team_changed(team, rec.team):\n            changes[\"team_raw\"]", "        if False:\n            changes[\"team_raw\"]", EDITS),
    ("edit: the object class may change", "edit.py", "        if V.to_int(obj.cached_type) != slot.cached_type:\n", "        if False:\n", EDITS),
    ("edit: other_a / other_b changes are ignored", "edit.py", "        if (a, b) != (rec.other_a, rec.other_b):\n", "        if False:\n", EDITS),
    ("edit: other_a is written to the wrong list", "edit.py", "        if cached_type == 1:\n            return [a]", "        if cached_type == 1:\n            return [b]", EDITS),
    ("edit: the teleporter extras stop at 13", "edit.py", "        if 12 <= cached_type <= 14:\n            return [a, b]", "        if 12 <= cached_type <= 13:\n            return [a, b]", EDITS),
    ("edit: plain8 stores the index itself", "edit.py", "                return [a + 1]", "                return [a]", EDITS),
    ("edit: flag8 none is index 0", "edit.py", "            return [1, 0] if a == -1 else [0, a]", "            return [1, 0] if a == 0 else [0, a]", EDITS),
    ("edit: type 19 edits are allowed while undetermined", "edit.py", "        if self.m.type19_status == \"undetermined\":\n            self.err(self.errors_object, \"E_TYPE19_UNDETERMINED\"", "        if False:\n            self.err(self.errors_object, \"E_TYPE19_UNDETERMINED\"", EDITS),
    # --- edit.py: types and retargets --------------------------------------------------------
    ("edit: the assumed class is 1", "edit.py", "            return 0, True", "            return 1, True", REAL),
    ("edit: nothing is assumed", "edit.py", "        if self._assumed_group(type_name):\n            return 0, True", "        if False:\n            return 0, True", REAL),
    ("edit: assumed classes are reported for every object", "edit.py", "        if type_name not in self._assumed_warned:\n", "        if True:\n", REAL),
    ("edit: a name equal to the slot's keeps the type only by id", "edit.py", "            if text == rec.type_name:\n                return KEEP, None\n", "", EDITS),
    ("edit: a resolved id equal to the slot's still retargets", "edit.py", "return (KEEP, None) if resolved == rec.type_id else (RETARGET, resolved)", "return (RETARGET, resolved)", EDITS),
    ("edit: an id equal to the slot's still retargets", "edit.py", "        if hint == rec.type_id:\n            return KEEP, None\n        if hint == -1:", "        if hint == -1:", EDITS),
    ("edit: no type at all is accepted", "edit.py", "        if hint == -1:\n            self.err(self.errors_object, \"E_OBJ_NO_TYPE\", name, object_name=name)\n            return REFUSED, None\n", "", EDITS),
    ("edit: a retarget by id is not checked against the stock table", "edit.py", "        if known and not tables.is_stock_object(self.map_name, hint):\n            self.err(self.errors_object, \"E_OBJ_NOT_STOCK\", name, hint & 0xFFFF, self.map_name, object_name=name)\n            return REFUSED, None\n", "", EDITS),
    ("edit: unrecognised imported objects pass silently", "edit.py", "        if rec.stock or self.map_name is None:\n            return True\n", "        if True:\n            return True\n", EDITS),
    ("edit: the keep option does not keep", "edit.py", "        if self.options.keep_unrecognised_imported:\n            self.warnings.append(V.make(\"W_UNKNOWN_TYPE_KEPT\"", "        if False:\n            self.warnings.append(V.make(\"W_UNKNOWN_TYPE_KEPT\"", EDITS),
    ("edit: the kept-type warning shows the signed id", "edit.py", "obj.name, rec.type_id & 0xFFFF, self.map_name,\n                                        slot=index", "obj.name, rec.type_id, self.map_name,\n                                        slot=index", EDITS),
    ("edit: a retarget may change the class", "edit.py", "                if learned is None or learned != slot.cached_type:", "                if learned is None:", EDITS),
    ("edit: a retarget to an unknown class passes", "edit.py", "                if learned is None or learned != slot.cached_type:", "                if learned is not None and learned != slot.cached_type:", EDITS),
    ("edit: a retarget folder is not range checked", "edit.py", "            if folder >= m.fixed.quota_count:\n                self.err(self.errors_object, \"E_FOLDER_RANGE\", name, folder, m.fixed.quota_count, object_name=name)\n            else:\n                new_name", "            if False:\n                pass\n            else:\n                new_name", EDITS),
    ("edit: a retarget to a disputed id is silent", "edit.py", "                    if resolved in self._disputed():", "                    if False:", EDITS),
    ("edit: a retarget is not counted in the quota rows", "edit.py", "        if retarget is not None and retarget[0] != retarget[1]:", "        if False:", EDITS),
    ("edit: a retarget takes nothing out of the old row", "edit.py", "            if retarget[0] is not None:\n                self.quota_delta[retarget[0]]", "            if False:\n                self.quota_delta[retarget[0]]", EDITS),
    ("edit: a new object's name is not looked up", "edit.py", "            type_id = tables.object_id_for_name(self.map_name, text) if known else None\n            if type_id is None and known:", "            type_id = None\n            if type_id is None and known:", EDITS),
    ("edit: a new object by id needs no stock check", "edit.py", "            if known and tables.is_stock_object(self.map_name, hint):\n                type_id = hint", "            if known:\n                type_id = hint", EDITS),
    ("edit: an id of 0 is no type", "edit.py", "        elif hint >= 0:\n            if known and", "        elif hint > 0:\n            if known and", EDITS),
    ("edit: a new object's folder is not range checked", "edit.py", "            if folder >= m.fixed.quota_count:\n                self.err(self.errors_object, \"E_FOLDER_RANGE\", name, folder, m.fixed.quota_count, object_name=name)\n                folder = None", "            if folder > m.fixed.quota_count:\n                self.err(self.errors_object, \"E_FOLDER_RANGE\", name, folder, m.fixed.quota_count, object_name=name)\n                folder = None", EDITS),
    ("edit: location names are created without checking the rule", "edit.py", "                if V.to_int(obj.cached_type) == 19 and m.type19_status == \"undetermined\":", "                if False:", EDITS),
    ("edit: an unknown class is reported once per object", "edit.py", "                elif type_name not in self._unknown_class_reported:", "                elif True:", EDITS),
    ("edit: a new disputed id is silent", "edit.py", "            if type_id in self._disputed():", "            if False:", EDITS),
    ("edit: new objects do not write the orientation gate check", "edit.py", "        angle = self._yaw_angle(obj)\n        # --- the learned example", "        angle = codecs.angle_encode(V.yaw_of(obj.forward) or 0.0)\n        # --- the learned example", EDITS),
    ("edit: new objects skip the flag check", "edit.py", "        self._flag_problems(obj, base_view.symmetry, base_view.place_at_start, base_view.game_specific)\n        # --- extras", "        # --- extras", EDITS),
    ("edit: new objects are not range checked for their extras", "edit.py", "            problems = V.check_other(obj, cached, m.hypothesis.type19, None)\n            if problems:", "            problems = []\n            if problems:", EDITS),
    ("edit: flags2 of a new object", "edit.py", "NEW_FLAGS2 = 1 ", "NEW_FLAGS2 = 0 ", EDITS),
    ("edit: the default placement byte", "edit.py", "DEFAULT_PLACEMENT = 0x0C ", "DEFAULT_PLACEMENT = 0x1C ", EDITS),
    ("edit: the default team", "edit.py", "NEUTRAL_TEAM_RAW = 9 ", "NEUTRAL_TEAM_RAW = 0 ", EDITS),
    ("edit: a new object's parent", "edit.py", "        s.parent_raw = 0\n        shape = V.to_int(obj.shape)", "        s.parent_raw = 1\n        shape = V.to_int(obj.shape)", EDITS),
    ("edit: a new object is not in bounds", "edit.py", "        s.in_bounds = 1\n        s.pos = [cells[0]", "        s.in_bounds = 0\n        s.pos = [cells[0]", EDITS),
    ("edit: a new object's physics is not written", "edit.py", "        if physics != V.physics_norm(base_view.physics):\n            s.placement", "        if False:\n            s.placement", EDITS),
    ("edit: a new object ignores the team property", "edit.py", "s.team_raw = codecs.team_raw(team) if self._team_changed(team, codecs.team_view(base_team_raw)) else base_team_raw", "s.team_raw = base_team_raw", EDITS),
    ("edit: a new object ignores the colour property", "edit.py", "s.color = codecs.color_raw(color) if color != codecs.color_view(base_color) else base_color", "s.color = base_color", EDITS),
    ("edit: a new object ignores the label", "edit.py", "        s.label = None if label == -1 else label\n        physics", "        s.label = None\n        physics", EDITS),
    ("edit: a new object ignores the spawn sequence", "edit.py", "        s.spawn_seq = V.to_int(obj.spawn_sequence)\n        s.respawn", "        s.spawn_seq = 0\n        s.respawn", EDITS),
    ("edit: a new object ignores the shape", "edit.py", "        s.shape = shape\n        s.dims = self._dims_codes(obj, shape)", "        s.shape = 0\n        s.dims = []", EDITS),
    ("edit: new objects are not sorted", "edit.py", "        for obj in sorted(new_objects, key=lambda o: o.name):", "        for obj in new_objects:", EDITS),
    ("edit: new objects take the highest free slot", "edit.py", "            index = free.pop(0)", "            index = free.pop()", EDITS),
    ("edit: vacated slots are not free", "edit.py", "        occupied = set(s.index for s in m.slots if s.present and s.index not in gone)", "        occupied = set(s.index for s in m.slots if s.present)", EDITS),
    ("edit: a full file has no message", "edit.py", "            if not free:\n                self.err(self.errors_object, \"E_NO_FREE_SLOT\", obj.name, object_name=obj.name)\n                continue\n", "            if not free:\n                continue\n", EDITS),
    ("edit: a new object is not counted in its row", "edit.py", "            if folder is not None:\n                self.quota_delta[folder] = self.quota_delta.get(folder, 0) + 1", "            if False:\n                self.quota_delta[folder] = self.quota_delta.get(folder, 0) + 1", EDITS),
    ("edit: a rejected new object takes a slot", "edit.py", "            if slot is None:\n                continue\n            if not free:", "            if not free:", EDITS),
    # --- edit.py: quota, limits, capacity ----------------------------------------------------
    ("edit: the quota delta is not added", "edit.py", "            new = row.placed + delta", "            new = row.placed", EDITS),
    ("edit: the option is ignored", "edit.py", "        raise_max = bool(self.options.raise_quota_max)", "        raise_max = False", EDITS),
    ("edit: the option is always on", "edit.py", "        raise_max = bool(self.options.raise_quota_max)", "        raise_max = True", EDITS),
    ("edit: a raised maximum is not stored", "edit.py", "                    p.quotas[folder].maximum = new_max\n", "", EDITS),
    ("edit: a raised maximum is not reported", "edit.py", "                    self.warnings.append(V.make(\"W_QUOTA_MAX_RAISED\", folder, name, new, row.maximum, new_max))", "                    pass", EDITS),
    ("edit: the placed count is not stored", "edit.py", "                p.quotas[folder].placed = new\n", "                pass\n", EDITS),
    ("edit: the quota range error is lost", "edit.py", "            if problem == \"E_QUOTA_RANGE\":\n                self.err(self.errors_quota, \"E_QUOTA_RANGE\", folder, name)\n            elif", "            if False:\n                pass\n            elif", EDITS),
    ("edit: the minimum error is lost", "edit.py", "            elif problem == \"E_QUOTA_MIN\":\n                self.err(self.errors_quota, \"E_QUOTA_MIN\", folder, name, new, row.minimum)\n", "            elif problem == \"E_QUOTA_MIN\":\n                pass\n", EDITS),
    ("edit: quota changes list the wrong maximum", "edit.py", "\"maximum_before\": before.maximum, \"maximum_after\": after.maximum}", "\"maximum_before\": before.maximum, \"maximum_after\": before.maximum}", EDITS),
    ("edit: quota changes list unchanged rows", "edit.py", "            if before.as_tuple() != after.as_tuple():\n                out.append", "            if True:\n                out.append", EDITS),
    ("edit: the container shape is never refused", "edit.py", "        if self.m.shape == \"other\" and self._will_change():", "        if False:", EDITS),
    ("edit: the container shape is always refused", "edit.py", "        if self.m.shape == \"other\" and self._will_change():", "        if self.m.shape == \"other\":", EDITS),
    ("edit: a forced re-encode is no modification", "edit.py", "        return bool(self._content_dirty() or o.force_reencode or fsm_drop or self._rewrite_hash())", "        return bool(self._content_dirty() or fsm_drop or self._rewrite_hash())", EDITS),
    ("edit: a dropped _fsm is no modification", "edit.py", "        return bool(self._content_dirty() or o.force_reencode or fsm_drop or self._rewrite_hash())", "        return bool(self._content_dirty() or o.force_reencode or self._rewrite_hash())", EDITS),
    ("edit: a forced hash is no modification", "edit.py", "        return bool(self._content_dirty() or o.force_reencode or fsm_drop or self._rewrite_hash())", "        return bool(self._content_dirty() or o.force_reencode or fsm_drop)", EDITS),
    ("edit: the object limit is exclusive", "edit.py", "        if after > limit:", "        if after >= limit:", REAL),
    ("edit: the object limit ignores deletions", "edit.py", "        after = self.m.occupied - len(deleted) + len(new_objects)", "        after = self.m.occupied + len(new_objects)", REAL),
    ("edit: the object limit ignores additions", "edit.py", "        after = self.m.occupied - len(deleted) + len(new_objects)", "        after = self.m.occupied - len(deleted)", REAL),
    ("edit: the capacity is exclusive", "edit.py", "        if needed > STREAM_BITS:", "        if needed >= STREAM_BITS:", EDITS),
    ("edit: the capacity check is one bit late", "edit.py", "        if needed > STREAM_BITS:", "        if needed > STREAM_BITS + 1:", EDITS),
    ("edit: the capacity check is off", "edit.py", "        if needed > STREAM_BITS:", "        if False:", EDITS),
    ("edit: a pushed-out tail bit is allowed", "edit.py", "            if tail.nbits > room and tail.slice(room, tail.nbits).to_int() != 0:", "            if False:", EDITS),
    ("edit: a pushed-out zero tail is refused", "edit.py", "            if tail.nbits > room and tail.slice(room, tail.nbits).to_int() != 0:", "            if tail.nbits > room:", EDITS),
    # --- edit.py: results --------------------------------------------------------------------
    ("edit: the diff puts added before removed", "edit.py", "        return list(self.diff)\n\n    def _append_notes", "        return sorted(self.diff, key=lambda e: (e.kind != \"added\", e.slot if e.slot is not None else -1))\n\n    def _append_notes", EDITS),
    ("edit: a moved object is reported as edited", "edit.py", "        elif changed <= POS_FIELDS:", "        elif False:", EDITS),
    ("edit: a retarget is reported as edited", "edit.py", "        elif changed & TYPE_FIELDS:", "        elif False:", EDITS),
    ("edit: the hidden marker is lost", "edit.py", "        if obj.hidden:\n            detail += \" (hidden)\"\n        if obj.from_array:\n            detail += \" (array instance)\"\n        self.diff.append(DiffEntry(kind, index, name, detail))", "        self.diff.append(DiffEntry(kind, index, name, detail))", EDITS),
    ("edit: the notes are not reported on success", "edit.py", "        self._append_notes()\n        return ExportResult(True, data, diff, [], self.warnings, self.stats)", "        return ExportResult(True, data, diff, [], self.warnings, self.stats)", EDITS),
    ("edit: the palette note shows the wrong CRC", "edit.py", "V.make(\"I_PALETTE\", self.m.fixed.palette_crc)", "V.make(\"I_PALETTE\", self.m.fixed.checksum)", EDITS),
    ("edit: the rotation warning is lost", "edit.py", "        if self.rotation_written:\n            self.warnings.append(V.make(\"W_ORIENTATION_UNVERIFIED\", self.rotation_written))", "        pass", EDITS),
    ("edit: the rotation warning counts only the changed objects", "edit.py", "        self.rotation_written += 1\n        return s, type_id, folder", "        return s, type_id, folder", EDITS),
    ("edit: the template's warnings are not passed on", "edit.py", "                self.warnings.append(issue)\n\n    # --- step 3", "                pass\n\n    # --- step 3", EDITS),
    ("edit: fsm_policy DROP is ignored", "edit.py", "        if o.fsm_policy == \"DROP\":\n            p.drop_fsm()", "        if False:\n            p.drop_fsm()", EDITS),
    ("edit: a forced recipe is ignored", "edit.py", "        flavour = self._flavour_override()\n        force =", "        flavour = None\n        force =", EDITS),
    ("edit: the forced recipes are swapped", "edit.py", "\"salted_be32\" if policy == \"SALTED_BE32\" else \"plain_le32\"", "\"plain_le32\" if policy == \"SALTED_BE32\" else \"salted_be32\"", EDITS),
    ("edit: a forced recipe uses a big-endian length", "edit.py", "        endian = self.m.chunk.length_endian or \">\"\n        return hashing", "        endian = \">\"\n        return hashing", EDITS),
    ("edit: a clean template is never re-hashed", "edit.py", "force = bool(o.force_reencode) or (self._rewrite_hash() and not self._content_dirty())", "force = bool(o.force_reencode)", EDITS),
    ("edit: a clean template is always forced", "edit.py", "force = bool(o.force_reencode) or (self._rewrite_hash() and not self._content_dirty())", "force = True", EDITS),
    ("edit: a recipe equal to the template's still rewrites", "edit.py", "        return flavour is not None and flavour != self.m.flavour", "        return flavour is not None", EDITS),
    ("edit: the mode of a forced export is patched", "edit.py", "self.stats[\"mode\"] = \"forced\" if force else \"patched\"", "self.stats[\"mode\"] = \"patched\"", EDITS),
    ("edit: a passthrough reports the wrong end bit", "edit.py", "\"mode\": \"passthrough\", \"end_bit\": m.end_bit", "\"mode\": \"passthrough\", \"end_bit\": m.end_bit + 1", EDITS),
    ("edit: invalid fsm_policy values pass", "edit.py", "        if o.fsm_policy not in FSM_POLICIES:", "        if False:", EDITS),
    ("edit: invalid hash_policy values pass", "edit.py", "        if o.hash_policy not in HASH_POLICIES:", "        if False:", EDITS),
    ("edit: an unknown map is accepted", "edit.py", "        if self.map_name is None:\n            self.err(self.errors_global, \"E_MAP_UNKNOWN\"", "        if False:\n            self.err(self.errors_global, \"E_MAP_UNKNOWN\"", EDITS),
    ("edit: an unreadable template raises", "edit.py", "        except (MvarError, TypeError, ValueError) as exc:\n            self.errors_global.append", "        except ZeroDivisionError as exc:\n            self.errors_global.append", EDITS),
    ("edit: field errors do not stop an object", "edit.py", "                self.bad.add(id(obj))\n                continue\n            problems", "                continue\n            problems", EDITS),
    ("edit: a bad object loses its slot", "edit.py", "            self.diff.append(DiffEntry(\"kept\", index, name, \"not exported: the object has invalid values (see the errors)\"))\n            return", "            return", EDITS),
    # --- edit.py: the verification (fault injection) -----------------------------------------
    ("edit: verification: layout hypothesis comparison removed", "edit.py", "        if again.hypothesis != hyp:\n            fail(\"the layout hypothesis changed\")\n", "", EDITS),
    ("edit: verification: untouched header comparison removed", "edit.py", "        if not _same_except_file_length(m.header.raw, again.header.raw) or again.fixed.raw != m.fixed.raw \\\n                or again.labels.raw != m.labels.raw or again.guid != m.guid:\n            fail(", "        if False:\n            fail(", EDITS),
    ("edit: verification: label comparison removed", "edit.py", "or again.labels.raw != m.labels.raw or again.guid != m.guid:", "or again.guid != m.guid:", EDITS),
    ("edit: verification: quota comparison removed", "edit.py", "        if [q.as_tuple() for q in again.quotas] != [q.as_tuple() for q in p.quotas]:\n            fail(", "        if False:\n            fail(", EDITS),
    ("edit: verification: slot comparison removed", "edit.py", "            if again.slots[i].snapshot() != planned:\n                fail(", "            if False:\n                fail(", EDITS),
    ("edit: verification: untouched slot guard removed", "edit.py", "            if planned == m.slots[i].snapshot() and again.slots[i].snapshot() != m.slots[i].snapshot():\n                fail(", "            if False:\n                fail(", EDITS),
    ("edit: verification: end bit comparison removed", "edit.py", "        if again.end_bit != planned_end_bits(p):\n            fail(", "        if False:\n            fail(", EDITS),
    ("edit: verification: forced re-encode comparison removed", "edit.py", "            if self._template_is_canonical() and again.to_bytes(force=True) != data:\n                fail(", "            if False:\n                fail(", EDITS),
    ("edit: verification: every template is held to the forced re-encode", "edit.py", "            if self._template_is_canonical() and again.to_bytes(force=True) != data:", "            if again.to_bytes(force=True) != data:", EDITS),
    ("edit: verification: request check removed", "edit.py", "            if problem:\n                fail(", "            if False:\n                fail(", EDITS),
    ("edit: verification: position tolerance is huge", "edit.py", "codecs.pos_tolerance(axes[k], b[2 * k], b[2 * k + 1]) + 1e-9:", "codecs.pos_tolerance(axes[k], b[2 * k], b[2 * k + 1]) + 1e9:", EDITS),
    ("edit: verification: team check removed", "edit.py", "        if self._team_changed(obj.team, rec.team):\n            return", "        if False:\n            return", EDITS),
    ("edit: verification: yaw tolerance is huge", "edit.py", "delta > codecs.ANGLE_STEP + 1e-9", "delta > 10.0", EDITS),
    # --- model.py / blf.py: the write side ---------------------------------------------------
    ("model: capacity class length", "model.py", "        if self.length_class == \"capacity\":\n            return STREAM_BYTES", "        if self.length_class == \"capacity\":\n            return (end_bit + 7) // 8", EDITS),
    ("model: zero class length", "model.py", "        if self.length_class == \"zero\":\n            return 0", "        if self.length_class == \"zero\":\n            return (end_bit + 7) // 8", EDITS),
    ("model: the hash policy flavour is ignored", "model.py", "        return container.render(force=force, stream_length={\"mvar\": length}, flavour=flavour)", "        return container.render(force=force, stream_length={\"mvar\": length})", EDITS),
    ("model: dropping _fsm does nothing", "model.py", "        self.blf.drop_fsm()", "        pass", EDITS),
    ("blf: the unknown-hash fallback uses plain_le32", "blf.py", "used = hashing.HashFlavour(endian, spec.default_recipe or \"salted_be32\")", "used = hashing.HashFlavour(endian, spec.default_recipe or \"plain_le32\")", EDITS),
    ("blf: the unknown-hash warning is lost", "blf.py", "            issues.append(Issue(\"W_HASH_UNKNOWN\", \"warning\",", "            issues.append(Issue(\"W_HASH_UNKNOWN\", \"info\",", EDITS),
    ("blf: the zero-hash note is lost", "blf.py", "                issues.append(Issue(\"I_HASH_ZERO\", \"info\",", "                issues.append(Issue(\"I_HASH_ZERO_\", \"info\",", EDITS),
    ("blf: a modified file does not re-stamp the lengths", "blf.py", "        restamp = force or total != old_total", "        restamp = force", EDITS),
    ("blf: the trailer warning is lost", "blf.py", "            if modified:\n                issues.append(Issue(\"W_TRAILER_KEPT\"", "            if False:\n                issues.append(Issue(\"W_TRAILER_KEPT\"", EDITS),
    ("blf: the stale _fsm warning is lost", "blf.py", "        if modified and any(c.sig == \"_fsm\" for c in self.chunks):", "        if False:", EDITS),
    ("blf: a dropped _fsm stays", "blf.py", "        kept = [c for i, c in enumerate(self.chunks) if not (i > self.eof_index and c.sig == \"_fsm\")]", "        kept = list(self.chunks)", EDITS),
    ("blf: the cmp expansion is silent", "blf.py", "        if expanded:\n            issues.append(Issue(\"W_CMP_EXPANDED\"", "        if False:\n            issues.append(Issue(\"W_CMP_EXPANDED\"", EDITS),
    ("blf: the stored length is written in the wrong byte order", "blf.py", "        endian = flavour.length_endian if flavour is not None else analysis.length_endian", "        endian = \">\"", EDITS),
    # --- reencode_mvar.py (the command line tool; sources of tools/) --------------------------
    ("tool: corrupt hash flips nothing", "../../tools/reencode_mvar.py", "    out[offset] ^= 0xFF", "    out[offset] ^= 0x00", CLI),
    ("tool: the self-test is off", "../../tools/reencode_mvar.py", "        if out != data:\n            at = first_difference", "        if False:\n            at = first_difference", CLI),
    ("tool: two hash options are accepted", "../../tools/reencode_mvar.py", "    if sum(chosen) > 1:", "    if sum(chosen) > 5:", CLI),
    ("tool: the repository check is off", "../../tools/reencode_mvar.py", "    if inside_repo(args.output):", "    if False:", CLI),
    ("tool: the same-file check is off", "../../tools/reencode_mvar.py", "    issue = mio.check_output_path(args.output, [args.input])", "    issue = mio.check_output_path(args.output, [])", CLI),
    ("tool: a probe keeps the length byte order", "../../tools/reencode_mvar.py", "    endian = model.chunk.length_endian or \">\"\n    if args.corrupt_hash:", "    endian = \">\"\n    if args.corrupt_hash:", CLI),
    ("tool: a failed self-test exits 0", "../../tools/reencode_mvar.py", "            return EXIT_SELFTEST\n    try:\n        MapVariant.from_bytes(out)", "            return EXIT_OK\n    try:\n        MapVariant.from_bytes(out)", CLI),
]


def prepare(sandbox):
    os.makedirs(os.path.join(sandbox, "tests", "unit"))
    os.makedirs(os.path.join(sandbox, "tools"))
    os.makedirs(os.path.join(sandbox, "docs", "mvar"))
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(os.path.join(REPO, "Addon", "mvarlib"), os.path.join(sandbox, "Addon", "mvarlib"), ignore=ignore)
    for name in GLUE_FILES:
        shutil.copy(os.path.join(REPO, "Addon", name), os.path.join(sandbox, "Addon", name))
    shutil.copytree(os.path.join(REPO, "tests", "fixturebuilder"), os.path.join(sandbox, "tests", "fixturebuilder"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "tests", "golden"), os.path.join(sandbox, "tests", "golden"), ignore=ignore)
    shutil.copytree(os.path.join(REPO, "docs", "mvar", "reference"), os.path.join(sandbox, "docs", "mvar", "reference"), ignore=ignore)
    shutil.copy(os.path.join(REPO, "docs", "mvar", "SPEC-mvar.md"), os.path.join(sandbox, "docs", "mvar", "SPEC-mvar.md"))
    for name in G5_TESTS:
        shutil.copy(os.path.join(REPO, "tests", "unit", name), os.path.join(sandbox, "tests", "unit", name))
    for name in ("run_tests.py", "verify_mvar.py", "dump_mvar.py", "reencode_mvar.py"):
        shutil.copy(os.path.join(REPO, "tools", name), os.path.join(sandbox, "tools", name))


def target_path(sandbox, rel):
    if rel.startswith("../../"):
        return os.path.join(sandbox, rel[6:])
    return os.path.join(sandbox, "Addon", "mvarlib", rel)


def run(python, sandbox, only):
    cmd = [python, "-I", os.path.join(sandbox, "tools", "run_tests.py"), "--samples", "--only"] + list(only)
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, cwd=sandbox)
    return proc.returncode, proc.stdout


def one(python, mutant):
    name, rel, old, new, only = mutant
    sandbox = tempfile.mkdtemp(prefix="mjolnir-mutate-g5-")
    try:
        prepare(sandbox)
        path = target_path(sandbox, rel)
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        if source.count(old) != 1:
            return name, "PATTERN", "%d occurrences of the old text in %s" % (source.count(old), rel)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source.replace(old, new))
        code, out = run(python, sandbox, only)
        if code != 0:
            first = [line for line in out.splitlines() if line.startswith(("FAIL:", "ERROR:"))][:1]
            return name, "killed", first[0] if first else "run failed"
        return name, "SURVIVED", ""
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check-patterns", action="store_true")
    ap.add_argument("names", nargs="*")
    args = ap.parse_args(argv)
    chosen = [m for m in MUTANTS if not args.names or any(n in m[0] for n in args.names)]
    if args.list:
        for m in chosen:
            print(m[0])
        return 0
    if args.check_patterns:
        bad = 0
        sandbox = tempfile.mkdtemp(prefix="mjolnir-mutate-g5-")
        try:
            prepare(sandbox)
            for name, rel, old, new, only in chosen:
                with open(target_path(sandbox, rel), "r", encoding="utf-8") as fh:
                    count = fh.read().count(old)
                if count != 1:
                    bad += 1
                    print("PATTERN  %-70s %d occurrences in %s" % (name, count, rel))
            print("%d mutants, %d patterns do not apply" % (len(chosen), bad))
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        return 1 if bad else 0
    baseline = tempfile.mkdtemp(prefix="mjolnir-mutate-g5-base-")
    try:
        prepare(baseline)
        code, out = run(args.python, baseline, EDITS + REAL[-1:] + CLI)
        if code != 0:
            print("baseline is not green:\n" + out[-3000:])
            return 2
    finally:
        shutil.rmtree(baseline, ignore_errors=True)
    survivors = []
    killed = 0
    equivalent = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for name, state, detail in pool.map(lambda m: one(args.python, m), chosen):
            if state == "killed":
                killed += 1
                print("killed   %s    [%s]" % (name, detail[:110]))
            elif state == "SURVIVED" and name in EQUIVALENT:
                equivalent += 1
                print("equiv    %s" % name)
            else:
                print("%-8s %s %s" % (state, name, detail))
                survivors.append(name)
            sys.stdout.flush()
    print("")
    print("%d mutants: %d killed, %d equivalent, %d survivors" % (len(chosen), killed, equivalent, len(survivors)))
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
