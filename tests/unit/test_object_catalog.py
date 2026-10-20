"""Full palette coverage and native defaults without coupling support to meshes."""
import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import helpers_g5 as h
from mvarlib import api, catalog, tables
from mvarlib.model import MapVariant


def native_template(palette_crc=0x20E1C0E1):
    build, _ = h.build_modules()
    spec = copy.deepcopy(build.load_spec('w1_minimal'))
    spec['body']['palette_crc'] = palette_crc
    spec['body']['quota_count'] = 89
    return build.build(spec).data


class TestFullCatalog(unittest.TestCase):
    def test_every_stock_type_is_discoverable_once_without_adding_fake_models(self):
        seen = []

        def walk(node):
            seen.extend(node.get('leaves', []))
            for child in node.get('groups', []):
                walk(child)

        tree = catalog.browser_tree()
        walk(tree)
        expected = tables.stock_object_names('Forge World')
        self.assertEqual(len(seen), 348)
        self.assertCountEqual(seen, expected)
        self.assertEqual(len(set(seen)), len(seen))
        # The original asset tree remains useful for deciding whether a real model exists.
        modeled = []

        def model_walk(node):
            modeled.extend(node.get('leaves', []))
            for child in node.get('groups', []):
                model_walk(child)

        model_walk(tables.palette_tree())
        self.assertEqual(len(modeled), 194)
        self.assertIn('Assault Rifle', seen)
        self.assertNotIn('Assault Rifle', modeled)

    def test_native_classes_and_shapes_include_previously_unmodeled_objects(self):
        expected = {'Assault Rifle': 1, 'Frag Grenade': 2, 'Jet Pack': 5,
                    'Warthog, Default': 7, 'Pelican, Hovering': 9,
                    'Hill Marker': 0, 'Location Name': 19}
        for name, cached in expected.items():
            row = catalog.definition('Forge World', name)
            self.assertEqual(row['cached_type'], cached, name)
        location = catalog.definition('Forge World', 'Location Name')
        self.assertEqual(location['shape'], 2)
        self.assertEqual(location['width'], 3.0)
        self.assertTrue(location['editor_only'])

    def test_definitions_cannot_leak_across_maps_or_be_modified_by_callers(self):
        self.assertIsNone(catalog.definition('Breakneck', 'Assault Rifle'))
        self.assertIsNone(catalog.definition('Forge World', 'Not a Forge object'))
        row = catalog.definition('Forge World', 'Assault Rifle')
        row['cached_type'] = 31
        row['category'].append('Changed')
        self.assertEqual(catalog.definition('Forge World', 'Assault Rifle')['cached_type'], 1)
        self.assertEqual(catalog.definition('Forge World', 'Assault Rifle')['category'], ['Weapons, Human'])

    def test_new_defaults_preserve_the_named_location_none_sentinel(self):
        defaults = catalog.new_object_defaults('Forge World', 'Location Name')
        self.assertEqual(defaults['other_a'], -1)
        self.assertEqual(defaults['shape'], 2)
        self.assertEqual(catalog.new_object_defaults('Forge World', 'Assault Rifle')['respawn'], 30)


class TestNativeClassExport(unittest.TestCase):
    def test_explicit_native_weapon_settings_preserve_legacy_positions_and_other_slots(self):
        build, _ = h.build_modules()
        spec = copy.deepcopy(build.load_spec('w1_minimal'))
        spec['body']['palette_crc'] = 0x20E1C0E1
        spec['body']['quota_count'] = 89
        spec['slots'].insert(0, dict(index=0, folder=0, item=0, pos=[1, 1, 1], cached_type=0))
        spec['quotas']['rows']['0'] = [0, 16, 1]
        data = build.build(spec).data
        original = MapVariant.from_bytes(data)
        objects = h.objects_for(data)
        h.change(objects, 0, cached_type=1, other_a=4)
        result = h.export(data, objects)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        changed = MapVariant.from_bytes(result.data)
        rifle = changed.record_for(changed.slots[0])
        self.assertEqual((rifle.cached_type, rifle.other_a), (1, 4))
        self.assertEqual(changed.slots[0].pos, original.slots[0].pos)
        self.assertEqual(changed.slots[0].angle, original.slots[0].angle)
        for slot in (1, 5, 650):
            self.assertEqual(changed.slots[slot].raw, original.slots[slot].raw)
        self.assertIn('0 - Assault Rifle', result.stats['native_property_upgrades'])

    def test_new_native_weapon_requests_its_full_controls_on_a_legacy_template(self):
        build, _ = h.build_modules()
        spec = copy.deepcopy(build.load_spec('w1_minimal'))
        spec['body']['palette_crc'] = 0x20E1C0E1
        spec['body']['quota_count'] = 89
        spec['slots'].insert(0, dict(index=0, folder=0, item=0, pos=[1, 1, 1], cached_type=0))
        spec['quotas']['rows']['0'] = [0, 16, 1]
        data = build.build(spec).data
        defaults = catalog.new_object_defaults('Forge World', 'Assault Rifle', data)
        self.assertEqual(defaults['cached_type'], 1)
        new = h.new_object('Native rifle', 'Assault Rifle', cached_type=1, other_a=6)
        result = h.export(data, h.objects_for(data) + [new], allow_unverified_rotation=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        rifles = [o for o in MapVariant.from_bytes(result.data).objects() if o.type_name == 'Assault Rifle']
        self.assertEqual([(o.cached_type, o.other_a) for o in rifles], [(0, 0), (1, 6)])

    def test_named_location_extends_legacy_palette_and_uses_native_index_codec(self):
        source = native_template()
        new = h.new_object('Named volume', 'Location Name', position=(1.0, 1.0, 1.0),
                           shape=2, width=3.0, top=3.0, bottom=3.0, other_a=7)
        result = h.export(source, h.objects_for(source) + [new], allow_unverified_rotation=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        decoded = MapVariant.from_bytes(result.data)
        self.assertEqual(decoded.fixed.quota_count, 145)
        self.assertEqual(decoded.fixed.palette_crc, 0x8B33E8AC)
        self.assertEqual(decoded.hypothesis.type19, 'plain8')
        location = next(o for o in decoded.objects() if o.type_name == 'Location Name')
        self.assertEqual((location.cached_type, location.other_a), (19, 7))
        self.assertEqual(decoded.slots[location.slot].extra, [8])
        self.assertEqual(decoded.quotas[144].as_tuple(), (0, 64, 1))
        clean = h.export(result.data, h.objects_for(result.data))
        self.assertTrue(clean.ok, [e.message for e in clean.errors])
        self.assertEqual(clean.data, result.data)
        for old in MapVariant.from_bytes(source).present_slots():
            self.assertEqual(decoded.slots[old.index].raw, old.raw)

    def test_native_location_index_limits_and_none_round_trip(self):
        for index in (-1, 0, 254, 255):
            source = native_template()
            new = h.new_object('Named volume', 'Location Name', position=(1.0, 1.0, 1.0), other_a=index)
            result = h.export(source, h.objects_for(source) + [new], allow_unverified_rotation=True)
            if index == 255:
                self.assertFalse(result.ok)
                self.assertIn('E_OTHER_RANGE', h.codes(result.errors))
            else:
                self.assertTrue(result.ok, [e.message for e in result.errors])
                location = next(o for o in MapVariant.from_bytes(result.data).objects() if o.type_name == 'Location Name')
                self.assertEqual(location.other_a, index)

    def test_unknown_palette_revision_cannot_extend_its_definition_table(self):
        source = native_template(0x12345678)
        new = h.new_object('Named volume', 'Location Name', position=(1.0, 1.0, 1.0), other_a=-1)
        result = h.export(source, h.objects_for(source) + [new], allow_unverified_rotation=True)
        self.assertFalse(result.ok)
        self.assertIn('E_FOLDER_RANGE', h.codes(result.errors))
        self.assertNotIn('native_palette_extension', result.stats)

    def test_weapon_without_template_example_gets_native_class_and_clip_field(self):
        data = native_template()
        new = h.new_object('New rifle', 'Assault Rifle', position=(1.0, 1.0, 1.0), other_a=5)
        result = h.export(data, h.objects_for(data) + [new], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        parsed = MapVariant.from_bytes(result.data)
        rifle = next(row for row in parsed.objects() if row.type_name == 'Assault Rifle')
        self.assertEqual((rifle.cached_type, rifle.other_a), (1, 5))
        # Untouched imported slots retain their exact field bits.
        original = MapVariant.from_bytes(data)
        for old in original.present_slots():
            self.assertEqual(parsed.slots[old.index].raw, old.raw)
        self.assertIn('Assault Rifle', result.stats['native_object_definitions'])
        self.assertEqual(parsed.fixed.spent_budget, 30)
        self.assertEqual(result.stats['native_budget'], dict(spent=30, maximum=30000))

    def test_unchanged_native_template_keeps_its_original_budget_word_and_bytes(self):
        data = native_template()
        result = h.export(data, h.objects_for(data))
        self.assertTrue(result.ok)
        self.assertEqual(result.data, data)
        self.assertNotIn('native_budget', result.stats)

    def test_unknown_palette_revision_does_not_assume_native_class(self):
        data = native_template(0x12345678)
        new = h.new_object('New rifle', 'Assault Rifle', position=(1.0, 1.0, 1.0))
        result = h.export(data, h.objects_for(data) + [new], allow_unverified_rotation=True, raise_quota_max=True)
        self.assertFalse(result.ok)
        self.assertIn('E_CACHED_TYPE_UNKNOWN', h.codes(result.errors))

    def test_valid_observed_class_keeps_precedence_over_a_native_default(self):
        build, _ = h.build_modules()
        spec = copy.deepcopy(build.load_spec('w1_minimal'))
        spec['body']['palette_crc'] = 0x20E1C0E1
        spec['body']['quota_count'] = 89
        spec['slots'].insert(0, dict(index=0, folder=0, item=0, pos=[1, 1, 1], cached_type=0))
        spec['quotas']['rows']['0'] = [0, 16, 1]
        data = build.build(spec).data
        new = h.new_object('New rifle', 'Assault Rifle', position=(1.0, 1.0, 1.0))
        result = h.export(data, h.objects_for(data) + [new], allow_unverified_rotation=True)
        self.assertTrue(result.ok, [e.message for e in result.errors])
        rifles = [o for o in MapVariant.from_bytes(result.data).objects() if o.type_name == 'Assault Rifle']
        self.assertEqual([o.cached_type for o in rifles], [0, 0])


if __name__ == '__main__':
    unittest.main()
