"""Native tilted poses, six cube faces, and exact preservation of imported bits."""
import math
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import helpers_g5 as h
from test_object_catalog import native_template
from mvarlib import codecs
from mvarlib.model import MapVariant


def angle(a, b):
    dot = sum(x*y for x, y in zip(a, b))
    return math.acos(max(-1, min(1, dot)))


class TestNativeOrientation(unittest.TestCase):
    def test_native_reference_axes_and_face_ties(self):
        self.assertEqual(codecs.native_tilt_reference((1, 0, 0)), (0, 0, -1))
        self.assertEqual(codecs.native_tilt_reference((0, 1, 0)), (0, 0, -1))
        self.assertEqual(codecs.native_tilt_reference((0, 0, 1)), (1, 0, 0))
        self.assertEqual(codecs.up_parts(codecs.up_encode_native((1, 1, 1)))[0], 2)
        self.assertEqual(codecs.up_parts(codecs.up_encode_native((-1, -1, -1)))[0], 5)

    def test_random_native_rotations_round_trip_all_cube_faces(self):
        randomizer = random.Random(348)
        faces = set()
        for _ in range(1600):
            up = [randomizer.uniform(-1, 1) for _ in range(3)]
            length = math.sqrt(sum(x*x for x in up))
            up = tuple(x/length for x in up)
            reference = codecs.native_tilt_reference(up)
            side = (up[1]*reference[2]-up[2]*reference[1], up[2]*reference[0]-up[0]*reference[2], up[0]*reference[1]-up[1]*reference[0])
            yaw = randomizer.uniform(-math.pi, math.pi)
            forward = tuple(reference[i]*math.cos(yaw)+side[i]*math.sin(yaw) for i in range(3))
            stored = codecs.orientation_encode_native(forward, up)
            got_forward, got_up = codecs.reconstruct_native_orientation(*stored)
            self.assertLess(angle(forward, got_forward), 0.006)
            self.assertLess(angle(up, got_up), 0.006)
            if stored[1] is not None:
                faces.add(codecs.up_parts(stored[1])[0])
        self.assertEqual(faces, set(range(6)))

    def test_native_tilt_export_is_gated_and_noop_is_exact(self):
        data = native_template()
        up = (0, -math.sin(0.7), math.cos(0.7))
        forward = (0, math.cos(0.7), math.sin(0.7))
        obj = h.new_object('Tilted block', position=(1, 2, 3), forward=forward, up=up)
        refused = h.export(data, h.objects_for(data) + [obj])
        self.assertIn('E_ROTATION_GATED', h.codes(refused.errors))
        result = h.export(data, h.objects_for(data) + [obj], allow_unverified_rotation=True)
        self.assertTrue(result.ok, [x.message for x in result.errors])
        model = MapVariant.from_bytes(result.data)
        tilted = next(o for o in model.objects() if o.slot == 0)
        self.assertEqual(tilted.orientation_kind, 'tilted')
        self.assertLess(angle(tilted.forward, forward), 0.006)
        self.assertLess(angle(tilted.up, up), 0.006)
        unchanged = h.export(result.data, h.objects_for(result.data))
        self.assertTrue(unchanged.ok)
        self.assertEqual(unchanged.data, result.data)


if __name__ == '__main__':
    unittest.main()
