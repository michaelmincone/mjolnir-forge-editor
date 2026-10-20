#!/usr/bin/env python3
"""Generate names and numeric object defaults from a bounded read-only cache audit.

No mesh, bitmap, map variant or executable bytes are copied into the add-on.
Usage: python3 tools/gen_object_support.py --audit ../object-support/research/native_palette_audit.json
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {
    'ff_weapons_human': ['Weapons, Human'],
    'ff_weapons_covenant': ['Weapons, Covenant'],
    'ff_armor_abilities': ['Armor Abilities'],
    'ff_vehicles': ['Vehicles'],
    'ff_gadgets': ['Gadgets'],
    'ff_spawning': ['Spawning'],
    'ff_objectives': ['Objectives'],
    'ff_scenery': ['Scenery'],
    'ff_structure': ['Structure'],
    'structure_blocks': ['Hidden', 'Invisible'],
    'ff_thorage_vehicles': ['Vehicles', 'MCC Additions'],
    'ff_thorage_gadgets': ['Gadgets', 'MCC Additions'],
    'ff_thorage_scenery': ['Scenery', 'MCC Additions'],
    'ff_thorage_structure': ['Structure', 'MCC Additions'],
    'ff_thorage_hidden': ['Hidden'],
    'ff_thorage_more': ['More'],
}


def generate(audit):
    rows = []
    for record in audit['objects']:
        native = record['native']
        props = native['multiplayer_properties']
        if len(props) != 1 or record['native_multiplayer_classes'] != [props[0]['type']]:
            raise ValueError('Expected one unambiguous native property class: ' + record['name'])
        values = {field['name']: field['value'] for field in props[0]['fields']}
        row = dict(id=record['id'], name=record['name'], internal=record['internal'],
                   category=CATEGORIES[native['category']], cached_type=props[0]['type'],
                   class_name=props[0]['type_name'], editor_only=bool(values['Flags'] & 1),
                   respawn=max(0, min(255, values['Default Spawn Time'])),
                   phased=bool(values['Flags'] & 2), shape=values['Boundary Shape'],
                   width=values['Boundary Width/Radius'], length=values['Boundary Box Length'],
                   top=values['Boundary +Height'], bottom=values['Boundary -Height'],
                   bounding_radius=native['bounding_radius'], bounding_offset=native['bounding_offset'],
                   object_tag=native['object']['name'], object_group=native['object']['group'],
                   model_tag=(native.get('render_model') or {}).get('name'),
                   model_variant=native['model_variant_name'],
                   price=native['price'], ordinary_maximum=native['ordinary_maximum'])
        rows.append(row)
    stock = json.loads((ROOT / 'Addon/mvarlib/data/stock_objects.json').read_text())['maps']['Forge World']
    if [(r['id'], r['internal'], r['name']) for r in rows] != [tuple(r) for r in stock]:
        raise ValueError('Native audit and stock table disagree')
    if len(rows) != 348 or audit['native_entry_count'] != 145 or audit['native_variant_count'] != 348:
        raise ValueError('The complete Forge World audit is required')
    if not audit['templates'] or any('palette_crc' not in t for t in audit['templates'].values()):
        raise ValueError('Re-run the audit to include template palette CRCs')
    return dict(schema='mvarlib.object_support/1', map_id=3006, map_name='Forge World',
                source=dict(cache_sha256=audit['cache']['sha256'], cache_build=audit['cache']['build'],
                            binary_sha256=audit['binary']['sha256'],
                            schemas={Path(p).name: digest for p, digest in audit['schemas'].items()},
                            method='Read-only scenario palette and referenced object multiplayer properties; native source facts, runtime not verified'),
                palette_entries=145, native_palette_crc=audit['native_palette_crc'], native_budget=int(audit['native_budget']),
                native_type19_rule='plain8',
                native_codec_evidence='ev_537fb1f10b74f207b94e680ed04855491a4c64368f7f7c2130e80dbbd5ec0483',
                native_palette_crc_evidence=audit['palette_crc_evidence'],
                palette_revisions=sorted(
                    [dict(crc=crc, entries=entries) for crc, entries in
                     {(t['palette_crc'], t['quota_count']) for t in audit['templates'].values()}]
                    + [dict(crc=audit['native_palette_crc'], entries=145)], key=lambda row: row['entries']),
                template_palette_crcs=sorted({t['palette_crc'] for t in audit['templates'].values()} | {audit['native_palette_crc']}),
                objects=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', required=True, type=Path)
    parser.add_argument('--out', type=Path, default=ROOT / 'Addon/mvarlib/data/object_support.json')
    args = parser.parse_args()
    data = generate(json.loads(args.audit.read_text()))
    args.out.write_text(json.dumps(data, indent=1, ensure_ascii=True) + '\n')
    print('Generated', len(data['objects']), 'native definitions;', len(data['template_palette_crcs']), 'observed template palette CRCs')


if __name__ == '__main__':
    main()
