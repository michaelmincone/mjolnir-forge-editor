"""Complete stock browser and evidence-backed defaults, independent of preview meshes.

The source is numeric/name metadata read from the installed Forge World cache.
It does not contain meshes, textures, executable bytes or map variants. Native
defaults are admitted only for the observed Forge World palette revisions;
imported records always retain their own serialized class and extra fields.
"""
import copy
from functools import lru_cache

from . import tables


@lru_cache(maxsize=1)
def _document():
    data = tables._load_json('object_support.json', 'mvarlib.object_support/1')
    expected = tables.stock_objects(data['map_name'])
    actual = [(row['id'], row['internal'], row['name']) for row in data['objects']]
    if actual != expected or len(actual) != 348:
        raise ValueError('Native object definitions do not match the stock Forge World table')
    return data


def definition(map_name, name_or_id):
    """A fresh native definition, or None; other maps never inherit Forge World IDs."""
    data = _document()
    if map_name != data['map_name']:
        return None
    for row in data['objects']:
        if name_or_id == row['name'] or name_or_id == row['id']:
            return copy.deepcopy(row)
    return None


def compatible(model):
    """Whether this stock model names a palette revision corroborated by the cache audit."""
    data = _document()
    return (model.map_id == data['map_id']
            and any(model.fixed.palette_crc == row['crc'] and model.fixed.quota_count == row['entries']
                    for row in data['palette_revisions']))


def native_palette(model):
    """Complete native palette parameters for a corroborated template, else None."""
    if not compatible(model):
        return None
    data = _document()
    maxima = {}
    for row in data['objects']:
        maxima[row['id'] >> 8] = min(255, row['ordinary_maximum']) if row['ordinary_maximum'] > 0 else 255
    return dict(count=data['palette_entries'], crc=data['native_palette_crc'], budget=data['native_budget'],
                type19=data['native_type19_rule'], maxima=maxima)


def available_palette_count(template):
    model = _template(bytes(template))
    data = native_palette(model)
    return data['count'] if data else model.fixed.quota_count


def read_layout(map_id, palette_crc, quota_count):
    """Known native layout for the complete, source-derived modern palette only.

    Legacy files retain hypothesis discovery. The complete palette's native
    reader/writer establish plain8 even when its sentinel can fit two bit walks.
    """
    data = _document()
    if (map_id == data['map_id'] and palette_crc == data['native_palette_crc']
            and quota_count == data['palette_entries']):
        return data['native_type19_rule']
    return None


def native_class(model, folder, item):
    if not compatible(model):
        return None
    row = definition(model.map_name, (folder << 8) | item)
    return row['cached_type'] if row else None


def browser_tree(model_tree=None):
    """Preserve modeled groups and add every missing stock name in its native category.

    The original palette_tree document continues to describe the asset library.
    This separate browser document describes all recognized object definitions.
    """
    tree = copy.deepcopy(model_tree if model_tree is not None else tables.palette_tree())
    seen = set()

    def collect(node):
        for leaf in node.get('leaves', []):
            seen.add(leaf if isinstance(leaf, str) else leaf['name'])
        for child in node.get('groups', []):
            collect(child)

    collect(tree)
    for row in _document()['objects']:
        if row['name'] in seen:
            continue
        node = tree
        for part in row['category']:
            children = node.setdefault('groups', [])
            match = next((child for child in children if child['name'] == part), None)
            if match is None:
                match = {'name': part}
                children.append(match)
            node = match
        node.setdefault('leaves', []).append(row['name'])
        seen.add(row['name'])
    tree['source'] = 'Complete stock browser; modeled groups plus native scenario categories'
    return tree


@lru_cache(maxsize=4)
def _template(data):
    from .model import MapVariant
    return MapVariant.from_bytes(data)


def imported_native_orientation(template, slot_index, raw, raw_bits):
    if template is None or raw is None or raw_bits is None:
        return None
    model = _template(bytes(template))
    if not compatible(model) or not isinstance(slot_index, int) or not 0 <= slot_index < len(model.slots):
        return None
    slot = model.slots[slot_index]
    if not slot.present:
        return None
    record = model.record_for(slot)
    if record.raw != bytes(raw) or record.raw_bits != int(raw_bits):
        return None
    return record.forward, record.up


def new_object_defaults(map_name, name, template=None):
    """Native creation properties plus template-specific learned class/placement flags."""
    row = definition(map_name, name)
    if row is None:
        return None
    row.update(physics=3 if row['phased'] else 0, symmetry=3, native_verified=False,
               place_at_start=True, game_specific=False, other_a=0, other_b=0)
    if row['cached_type'] == 19:
        row['other_a'] = -1
    if template is not None:
        from . import codecs
        from .edit import learn_class, learn_example
        model = _template(bytes(template))
        if model.map_name == map_name:
            row['native_verified'] = compatible(model)
            learned = learn_class(model, row['id'] >> 8, row['id'] & 255)
            if learned is not None and not row['native_verified']:
                row['cached_type'] = learned
            example = learn_example(model, row['id'] >> 8, row['id'] & 255)
            if example:
                placement = codecs.placement_view(example[0][0])
                row.update(symmetry=placement.symmetry, place_at_start=placement.place_at_start,
                           game_specific=placement.game_specific)
    return row
