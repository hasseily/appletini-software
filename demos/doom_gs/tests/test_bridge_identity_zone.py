"""The identity rules for the zone mobjs' sector nodes (tools/bridge/
identity.py; milestone 10's final integration, docs/GAME.md "Acceptance":
generated stream G1). The sector nodes are numbered in the order the
things' node lists reach them, the zone mobjs in their identity's order
(the thinker list's), whatever the present identities: the port reader's
are its slots, whose order can differ from the thinker list's. Hand-made
states, no build needed."""

import unittest

import support  # noqa: F401  (puts tools/ on the path)

from bridge import identity
from bridge.fields import R

THINKERS = 'p_think65.s:_g_thinkerclasscap'


def state(zone_ids, nodes_of, thinkers):
    """A canonical state with zone mobjs (present identities zone_ids),
    each with its node list, on the thinker list in `thinkers`' order."""
    return {'format': 'bridge-canonical 1',
            'globals': {THINKERS: [R('zmobj', z, None) for z in thinkers]},
            'objects': {
                'zmobj': {z: {'touching_sectorlist': [
                    R('secnode', n, None) for n in nodes_of[z]]}
                    for z in zone_ids},
                'secnode': {n: {'m_thing': R('zmobj', z, None)}
                            for z in zone_ids for n in nodes_of[z]}}}


class ZoneNodes(unittest.TestCase):
    def test_the_same_whatever_the_slots(self):
        # upstream's reader: ranks already (thinker order 0, 1)
        up = identity.renumber(state([0, 1], {0: [10, 11], 1: [12]},
                                     [0, 1]))
        # the port's: slots 801 (second on the thinker list) and 800
        port = identity.renumber(state([800, 801], {801: [5, 6], 800: [7]},
                                       [801, 800]))
        self.assertEqual(up['objects'], port['objects'])
        z0 = port['objects']['zmobj'][0]['touching_sectorlist']
        self.assertEqual([r.id for r in z0], [0, 1])

    def test_the_mobjs_first(self):
        s = state([3], {3: [9]}, [3])
        s['objects']['mobj'] = {0: {'touching_sectorlist': [
            R('secnode', 4, None)]}}
        s['objects']['secnode'][4] = {'m_thing': R('mobj', 0, None)}
        out = identity.renumber(s)
        self.assertEqual(out['objects']['mobj'][0]['touching_sectorlist'][0]
                         .id, 0)
        self.assertEqual(out['objects']['zmobj'][0]['touching_sectorlist']
                         [0].id, 1)


if __name__ == '__main__':
    unittest.main()
