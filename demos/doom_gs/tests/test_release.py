"""Tests of tools/v816/release.py: the programs of the release image."""

import unittest

import support
from v816 import release, scm

BLOCK = support.BLOCK


def disk():
    """A disk with two segments of the game, one of them with the
    interrupt code, a picture-less header and data that is not of the
    linker."""
    low = bytes([1]) * BLOCK + bytes([2]) * BLOCK + bytes([3]) * 300
    image = bytearray(support.make_disk([
        (0x00b800, 0, low),
        (0x030000, 0, b'code'),
        (0x100000, 0, b'resident data'),
        (0x400000, 0, b'store'),
    ]))
    image[0:4] = b'\x01boo'
    return bytes(image)


# The memories of the game: the code at $B800 and in bank 3 has bytes;
# bank $10 holds bss only, so the resident data there is not the
# linker's.
RULES = scm.parse('''
(define memories
  '((memory Low (address (#x00b800 . #x00b9ff)) (section low))
    (memory Irq (address (#x00dc00 . #x00deff)) (section irq))
    (memory Code (address (#x030000 . #x03ffff)) (section far zfar))
    (memory Far (address (#x100000 . #x10ffff)) (section zfar))
    ))
''')
INITIALISED = {'low', 'irq', 'far'}


class Targets(unittest.TestCase):
    def setUp(self):
        self.targets = release.targets(
            disk(), release.linked_memories(RULES, INITIALISED))

    def test_three_programs(self):
        self.assertEqual(
            [(target.name, target.rules_file) for target in self.targets],
            [('game', 'iigs.scm'), ('boot', 'boot.scm'),
             ('loader', 'loader.scm')])

    def test_boot_block(self):
        memory = self.targets[1].memory
        self.assertEqual(memory.extents(0), [(0x0800, 0x0a00)])
        self.assertEqual(memory.read(0x0800, 5), b'\x01boo\0')

    def test_loader(self):
        memory = self.targets[2].memory
        self.assertEqual(memory.extents(0), [(0x6000, 0x6000 + 700)])
        self.assertEqual(memory.read(0x6000, 2), b'\x60\x60')

    def test_game_has_the_segments_of_the_linker_only(self):
        memory = self.targets[0].memory
        self.assertEqual(memory.banks(), [0x00, 0x03])
        self.assertEqual(memory.read(0x030000, 5), b'code\0')
        self.assertEqual(memory.loaded_bytes(3), BLOCK)

    def test_interrupt_code_is_at_the_address_of_the_link(self):
        """The segment at $B800 has 3 blocks: $B800-$B9FF stays,
        $BA00-$BCFF runs at $DC00-$DEFF, and what follows stays. The
        bytes 3 are at $BC00-$BD2B on the disk."""
        memory = self.targets[0].memory
        self.assertEqual(memory.extents(0), [
            (0x00b800, 0x00ba00), (0x00bd00, 0x00be00),
            (0x00dc00, 0x00df00)])
        self.assertEqual(memory.read(0x00b9ff, 1), b'\x01')
        self.assertEqual(memory.read(0x00dc00, 1), b'\x02')
        self.assertEqual(memory.read(0x00ddff, 3), b'\x02\x03\x03')
        self.assertEqual(memory.read(0x00deff, 1), b'\x03')
        self.assertEqual(memory.read(0x00bd2b, 2), b'\x03\0')
        self.assertEqual(memory.loaded_bytes(0), 3 * BLOCK)

    def test_linked_memories(self):
        self.assertEqual(
            release.linked_memories(RULES, INITIALISED),
            [(0x00b800, 0x00b9ff), (0x00dc00, 0x00deff),
             (0x030000, 0x03ffff)])

    def test_segment_found_by_its_moved_part(self):
        """Only the interrupt code of the segment at $B800 lies in a
        memory of the link, at $DC00: the whole segment is the
        game's."""
        memories = release.linked_memories(RULES, {'irq'})
        memory = release.targets(disk(), memories)[0].memory
        self.assertEqual(memory.banks(), [0x00])
        self.assertEqual(memory.loaded_bytes(0), 3 * BLOCK)

    def test_nothing_linked(self):
        memory = release.targets(disk(), [])[0].memory
        self.assertEqual(memory.banks(), [])

    def test_disk_address(self):
        self.assertEqual(release.disk_address(0x00dc00), 0x00ba00)
        self.assertEqual(release.disk_address(0x00deff), 0x00bcff)
        self.assertEqual(release.disk_address(0x00df00), 0x00df00)
        self.assertEqual(release.disk_address(0x00dbff), 0x00dbff)
        self.assertEqual(release.disk_address(0x03dc00), 0x03dc00)


@support.needs_upstream
@support.needs_release
class ReleaseImage(unittest.TestCase):
    def test_sizes(self):
        targets = support.release_targets()
        sizes = {target.name: sum(target.memory.loaded_bytes(bank)
                                  for bank in target.memory.banks())
                 for target in targets}
        # 17,920 + 30,208 + 169,984: the code and near data segments
        # of docs/ARCHITECTURE.md, section 0
        self.assertEqual(sizes, {'game': 218112, 'boot': 512,
                                 'loader': 3072})
        self.assertEqual(targets[0].memory.banks(), [0, 2, 3, 4, 5])


if __name__ == '__main__':
    unittest.main()
