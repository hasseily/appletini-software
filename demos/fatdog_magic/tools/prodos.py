"""Independent ProDOS directory/payload reader and allocation verifier.

Layout: https://prodos8.com/docs/techref/file-organization/
Only seedling/sapling files are needed by FATDOG MAGIC's image payloads.
"""
from pathlib import Path
import re
import struct


def word(data, offset):
    return int.from_bytes(data[offset:offset + 2], "little")


def entries(disk, key=2):
    visited = set()
    block, previous = key, 0
    while block:
        assert 0 < block < len(disk) // 512 and block not in visited, "Directory loop/range"
        visited.add(block)
        base = block * 512
        assert word(disk, base) == previous, "Directory previous link"
        for slot in range(1 if block == key else 0, 13):
            offset = base + 4 + slot * 39
            if disk[offset] >> 4:
                yield offset, disk[offset:offset + 39]
        previous, block = block, word(disk, base + 2)


def entry_name(entry):
    return entry[1:1 + (entry[0] & 15)].decode("ascii")


def raw_files(path: Path) -> dict[str, bytes]:
    disk = path.read_bytes()
    result = {}
    visited = set()

    def walk(key, prefix):
        assert key not in visited, "Shared/recursive directory"
        visited.add(key)
        for _, e in entries(disk, key):
            name = prefix + entry_name(e)
            storage, child = e[0] >> 4, word(e, 17)
            eof = int.from_bytes(e[21:24], "little")
            if storage == 13:
                walk(child, name + "/")
                continue
            if storage == 1:
                payload = disk[child * 512:(child + 1) * 512]
            elif storage == 2:
                index = disk[child * 512:(child + 1) * 512]
                payload = bytearray()
                for i in range((eof + 511) // 512):
                    block = index[i] | index[i + 256] << 8
                    payload.extend(disk[block * 512:(block + 1) * 512] if block else bytes(512))
            else:
                raise ValueError(f"Unexpected storage type {storage}: {name}")
            assert name not in result, f"Duplicate path: {name}"
            result[name] = bytes(payload[:eof])

    walk(2, "")
    return result


def verify_allocation(path: Path) -> None:
    disk = path.read_bytes()
    total, bitmap = word(disk, 0x429), word(disk, 0x427)
    assert total * 512 == len(disk) or (total == 65535 and len(disk) == 32 * 1024 * 1024)
    assert not any(disk[total * 512:]), "Nonzero padding outside ProDOS volume"
    used = {0, 1, *range(bitmap, bitmap + (total + 4095) // 4096)}

    def claim(block):
        assert 0 < block < total and block not in used, f"Invalid/shared block: {block}"
        used.add(block)

    def walk(key, parent=None):
        header = disk[key * 512 + 4:key * 512 + 43]
        assert header[0] >> 4 == (15 if parent is None else 14)
        assert header[31:33] == bytes((39, 13))
        if parent is not None:
            offset, entry = parent
            assert entry_name(header) == entry_name(entry)
            assert word(header, 35) == offset // 512
            assert header[37] == ((offset % 512) - 4) // 39 + 1
            assert header[38] == 39
        block, directory_blocks = key, 0
        while block:
            claim(block)
            directory_blocks += 1
            block = word(disk, block * 512 + 2)
        count, names = 0, set()
        for offset, e in entries(disk, key):
            count += 1
            name = entry_name(e)
            assert name not in names
            names.add(name)
            assert word(e, 37) == key, f"Wrong parent header: {name}"
            child, storage = word(e, 17), e[0] >> 4
            eof = int.from_bytes(e[21:24], "little")
            if storage == 13:
                assert e[16] == 15
                blocks_used = walk(child, (offset, e))
                assert eof == blocks_used * 512
            else:
                claim(child)
                blocks_used = 1
                if storage == 2:
                    assert eof <= 131072
                    index = disk[child * 512:(child + 1) * 512]
                    for i in range((eof + 511) // 512):
                        block = index[i] | index[i + 256] << 8
                        if block:
                            claim(block)
                            blocks_used += 1
                else:
                    assert storage == 1 and eof <= 512
            assert blocks_used == word(e, 19), name
        assert count == word(header, 33), "Directory file count"
        return directory_blocks

    walk(2)
    for block in range(total):
        free = bool(disk[bitmap * 512 + block // 8] & (0x80 >> (block & 7)))
        assert free == (block not in used), f"Bitmap mismatch: {block}"
    for block in range(total, ((total + 4095) // 4096) * 4096):
        assert not disk[bitmap * 512 + block // 8] & (0x80 >> (block & 7)), "Free bit outside volume"


def expand_empty_volume(path: Path) -> None:
    """Expand ac's empty volume to a 32 MiB image / 65535-block ProDOS volume."""
    original = path.read_bytes()
    assert not list(entries(original)), "Expansion must precede file creation"
    assert word(original, 0x427) == 6 and word(original, 0x429) == 1600
    disk = bytearray(32 * 1024 * 1024)
    disk[:6 * 512] = original[:6 * 512]
    struct.pack_into("<H", disk, 0x429, 65535)
    # Blocks 0-1 boot, 2-5 root, 6-21 bitmap. The last physical block is padding.
    for block in range(22, 65535):
        disk[6 * 512 + block // 8] |= 0x80 >> (block & 7)
    path.write_bytes(disk)
    verify_allocation(path)


def create_folder(path: Path, name: str) -> None:
    """Create an empty root folder; ac's legacy CLI has no mkdir command.

    Preserve mixed case with GS/OS case bits; actual ProDOS names are uppercase.
    The gallery renders periods as spaces, without altering lookup names.
    """
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9.]{0,14}", name), name
    disk = bytearray(path.read_bytes())
    assert name.upper() not in [entry_name(e) for _, e in entries(disk)]
    block, offset = 2, None
    while block and offset is None:
        for slot in range(1 if block == 2 else 0, 13):
            candidate = block * 512 + 4 + slot * 39
            if disk[candidate] == 0:
                offset = candidate
                break
        block = word(disk, block * 512 + 2)
    assert offset is not None, "Root directory full"
    bitmap, total = word(disk, 0x427), word(disk, 0x429)
    child = next(b for b in range(total)
                 if disk[bitmap * 512 + b // 8] & (0x80 >> (b & 7)))
    disk[bitmap * 512 + child // 8] &= ~(0x80 >> (child & 7))
    name_bytes = name.upper().encode("ascii")
    case = 0x8000 | sum(1 << (14 - i) for i, c in enumerate(name) if c.islower())
    e = bytearray(39)
    e[0] = 0xD0 | len(name)
    e[1:1 + len(name)] = name_bytes
    e[16] = 15
    struct.pack_into("<HH", e, 17, child, 1)
    e[21:24] = (512).to_bytes(3, "little")
    struct.pack_into("<H", e, 28, case)
    e[30] = 0xE3
    struct.pack_into("<H", e, 37, 2)
    disk[offset:offset + 39] = e
    h = bytearray(512)
    h[4] = 0xE0 | len(name)
    h[5:5 + len(name)] = name_bytes
    h[0x14:0x1C] = bytes.fromhex("75 23 00 00 C3 27 0D 00")
    struct.pack_into("<H", h, 0x20, case)
    h[0x22:0x25] = bytes((0xE3, 39, 13))
    struct.pack_into("<HBB", h, 0x27, offset // 512, ((offset % 512) - 4) // 39 + 1, 39)
    disk[child * 512:(child + 1) * 512] = h
    struct.pack_into("<H", disk, 0x425, word(disk, 0x425) + 1)
    path.write_bytes(disk)
