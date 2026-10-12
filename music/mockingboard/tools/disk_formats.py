#!/usr/bin/env python3
"""Small, deterministic DOS 3.3/Applesoft/ProDOS conversion helpers.

The DOS reader preserves full 30-character names and removes only the file
format's length/address header. ``DosFile.raw`` retains the complete allocated
sector payload for provenance. The ProDOS writer emits a native filesystem,
not merely a DOS disk with its sectors reordered.

ProDOS filesystem reading and final allocation validation use the repository's
independent reader in tools/appletini/disk.py. No Java tools are required.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
from typing import Iterable


REPO = Path(__file__).resolve().parents[3]
DEFAULT_MASTER = REPO / "demos/fatdog_magic/assets/ProDOS_2_4_3.po"
BLOCK = 512
TYPE_BIN, TYPE_BAS, TYPE_SYS = 0x06, 0xFC, 0xFF


def word(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


@dataclass(frozen=True)
class DosFile:
    name: str
    type: int
    locked: bool
    sectors: int
    data: bytes
    load_address: int | None
    raw: bytes
    catalog_track: int
    catalog_sector: int
    catalog_index: int

    @property
    def type_name(self) -> str:
        return {0: "TXT", 1: "INT", 2: "BAS", 4: "BIN", 8: "S", 16: "REL",
                32: "A", 64: "B"}.get(self.type, f"${self.type:02X}")


def read_dos_disk(path: str | Path) -> list[DosFile]:
    """Extract live files from a 35-track DOS-order DOS 3.3 disk image.

    BAS/INT .data excludes the two-byte length. BIN .data excludes its
    four-byte load-address/length header; .load_address holds its address.
    Unstructured files retain their allocation padding in .data.
    """
    image = Path(path).read_bytes()
    if len(image) != 35 * 16 * 256:
        raise ValueError("expected a 143360-byte, 35-track DOS-order image")

    def sector(track: int, number: int) -> bytes:
        if not 0 <= track < 35 or not 0 <= number < 16:
            raise ValueError(f"DOS sector outside image: {track}/{number}")
        offset = (track * 16 + number) * 256
        return image[offset:offset + 256]

    vtoc = sector(17, 0)
    if vtoc[0x34:0x38] != bytes((35, 16, 0, 1)):
        raise ValueError("VTOC does not identify a 35-track/16-sector DOS volume")
    catalog_track, catalog_sector = vtoc[1:3]
    catalog_seen: set[tuple[int, int]] = set()
    names: set[str] = set()
    result: list[DosFile] = []
    while catalog_track:
        key = (catalog_track, catalog_sector)
        if key in catalog_seen:
            raise ValueError(f"DOS catalog cycle at {key}")
        catalog_seen.add(key)
        catalog = sector(*key)
        for index in range(7):
            entry = catalog[11 + 35 * index:46 + 35 * index]
            if entry[0] in (0, 255):
                continue
            name = bytes(c & 127 for c in entry[3:33]).decode("ascii").rstrip(" ")
            if not name or name in names:
                raise ValueError(f"invalid or duplicate DOS name: {name!r}")
            names.add(name)
            track, number = entry[:2]
            lists_seen: set[tuple[int, int]] = set()
            chunks: dict[int, bytes] = {}
            allocated: set[tuple[int, int]] = set()
            while track:
                position = (track, number)
                if position in lists_seen:
                    raise ValueError(f"{name}: track/sector-list cycle")
                lists_seen.add(position)
                block = sector(*position)
                first = word(block, 5)
                for slot in range(122):
                    data_track, data_sector = block[12 + 2 * slot:14 + 2 * slot]
                    if not data_track and not data_sector:
                        continue
                    logical = first + slot
                    address = (data_track, data_sector)
                    if logical in chunks or address in allocated:
                        raise ValueError(f"{name}: duplicate data-sector pointer")
                    allocated.add(address)
                    chunks[logical] = sector(*address)
                track, number = block[1:3]
            raw = b"".join(chunks.get(i, bytes(256))
                           for i in range(max(chunks, default=-1) + 1))
            file_type = entry[2] & 127
            header = 4 if file_type == 4 else 2 if file_type in (1, 2) else 0
            load = word(raw, 0) if file_type == 4 else 0x0801 if file_type == 2 else None
            if header:
                length = word(raw, header - 2)
                if len(raw) < header or header + length > len(raw):
                    raise ValueError(f"{name}: declared length exceeds its data sectors")
                data = raw[header:header + length]
            else:
                data = raw
            result.append(DosFile(name, file_type, bool(entry[2] & 128),
                                  word(entry, 33), data, load, raw,
                                  catalog_track, catalog_sector, index))
        catalog_track, catalog_sector = catalog[1:3]
    return result


# Applesoft ROM token table, $80 through $EA, in byte order.
TOKENS = (
    "END", "FOR", "NEXT", "DATA", "INPUT", "DEL", "DIM", "READ", "GR", "TEXT",
    "PR#", "IN#", "CALL", "PLOT", "HLIN", "VLIN", "HGR2", "HGR", "HCOLOR=",
    "HPLOT", "DRAW", "XDRAW", "HTAB", "HOME", "ROT=", "SCALE=", "SHLOAD",
    "TRACE", "NOTRACE", "NORMAL", "INVERSE", "FLASH", "COLOR=", "POP", "VTAB",
    "HIMEM:", "LOMEM:", "ONERR", "RESUME", "RECALL", "STORE", "SPEED=", "LET",
    "GOTO", "RUN", "IF", "RESTORE", "&", "GOSUB", "RETURN", "REM", "STOP",
    "ON", "WAIT", "LOAD", "SAVE", "DEF", "POKE", "PRINT", "CONT", "LIST",
    "CLEAR", "GET", "NEW", "TAB(", "TO", "FN", "SPC(", "THEN", "AT", "NOT",
    "STEP", "+", "-", "*", "/", "^", "AND", "OR", ">", "=", "<", "SGN", "INT",
    "ABS", "USR", "FRE", "SCRN(", "PDL", "POS", "SQR", "RND", "LOG", "EXP",
    "COS", "SIN", "TAN", "ATN", "PEEK", "LEN", "STR$", "VAL", "ASC", "CHR$",
    "LEFT$", "RIGHT$", "MID$",
)
TOKEN_BYTES = {text: number + 128 for number, text in enumerate(TOKENS)}
_TOKEN_MATCH = sorted(TOKEN_BYTES, key=len, reverse=True)


def parse_basic(data: bytes, base: int = 0x0801) -> list[tuple[int, bytes]]:
    """Return line numbers and exact tokenized bodies (without DOS header).

    DOS SAVE commonly includes one stale byte after the two-zero program end
    marker. It is deliberately ignored here; DosFile.data/raw retain it.
    """
    result = []
    offset = 0
    while True:
        if offset + 2 > len(data):
            raise ValueError("truncated Applesoft end marker")
        following = word(data, offset)
        if not following:
            return result
        if offset + 4 >= len(data):
            raise ValueError("truncated Applesoft line")
        end = data.find(b"\x00", offset + 4)
        if end < 0 or following != base + end + 1:
            raise ValueError(f"invalid Applesoft line link at ${base + offset:04X}")
        number = word(data, offset + 2)
        if result and number <= result[-1][0]:
            raise ValueError("Applesoft line numbers are not strictly increasing")
        result.append((number, data[offset + 4:end]))
        offset = end + 1


def pack_basic(lines: Iterable[tuple[int, bytes | str]], base: int = 0x0801) -> bytes:
    """Rebuild line links; strings are tokenized, bytes are preserved exactly."""
    result = bytearray()
    previous = -1
    for number, body in lines:
        if not previous < number <= 63999:
            raise ValueError("Applesoft lines must ascend in the range 0..63999")
        previous = number
        body = tokenize_body(body) if isinstance(body, str) else bytes(body)
        if 0 in body:
            raise ValueError("Applesoft line body contains an embedded zero")
        following = base + len(result) + len(body) + 5
        if following > 65533:
            raise ValueError("Applesoft program extends beyond memory")
        result.extend(following.to_bytes(2, "little"))
        result.extend(number.to_bytes(2, "little"))
        result.extend(body)
        result.append(0)
    return bytes(result) + b"\x00\x00"


def tokenize_body(text: str) -> bytes:
    """Tokenize one Applesoft statement body, retaining literal/REM/DATA text.

    Use parse_basic()/pack_basic() with byte bodies when unchanged original
    token streams must remain byte-for-byte identical.
    """
    result = bytearray()
    index, quoted, data = 0, False, False
    while index < len(text):
        char = text[index]
        if char == '"':
            quoted = not quoted
            result.append(34)
            index += 1
            continue
        if quoted or data:
            if char == ":" and not quoted:
                data = False
            result.extend(char.encode("ascii"))
            index += 1
            continue
        if char in " \t":
            index += 1
            continue
        if char == "?":
            result.append(TOKEN_BYTES["PRINT"])
            index += 1
            continue
        remaining = text[index:].upper()
        matched = next((token for token in _TOKEN_MATCH if remaining.startswith(token)), None)
        if matched is not None:
            result.append(TOKEN_BYTES[matched])
            index += len(matched)
            if matched == "REM":
                result.extend(text[index:].encode("ascii"))
                break
            if matched == "DATA":
                data = True
        else:
            result.extend(char.upper().encode("ascii"))
            index += 1
    return bytes(result)


def detokenize_body(body: bytes) -> str:
    result: list[str] = []
    quoted, raw, data = False, False, False
    for byte in body:
        if byte == 34 and not raw:
            quoted = not quoted
        if raw or quoted or data or byte < 128:
            result.append(chr(byte))
            if byte == 58 and data and not quoted:
                data = False
        else:
            if byte - 128 >= len(TOKENS):
                raise ValueError(f"unknown Applesoft token ${byte:02X}")
            token = TOKENS[byte - 128]
            result.append(f" {token} ")
            raw = token == "REM"
            data = token == "DATA"
    return "".join(result)


def basic_source(data: bytes) -> str:
    return "\n".join(f"{number} {detokenize_body(body)}"
                     for number, body in parse_basic(data)) + "\n"


def read_prodos_disk(path: str | Path) -> tuple[str, list[dict]]:
    """Read and validate root files with the repository's independent reader."""
    module_path = REPO / "tools/appletini/disk.py"
    spec = importlib.util.spec_from_file_location("mockingboard_prodos_reader", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load ProDOS reader: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.read_disk(path)


def runtime_files(master_path: str | Path = DEFAULT_MASTER) -> list[tuple[str, int, int, bytes]]:
    """Return original PRODOS then BASIC.SYSTEM, suitable for the writer."""
    _, entries = read_prodos_disk(master_path)
    by_name = {entry["name"]: entry for entry in entries}
    return [(name, by_name[name]["type"], by_name[name]["aux"], by_name[name]["data"])
            for name in ("PRODOS", "BASIC.SYSTEM")]


def build_prodos_image(path: str | Path, files: Iterable[tuple[str, int, int, bytes]],
                       *, volume: str = "MOCKINGBOARD", total_blocks: int = 280,
                       master_path: str | Path = DEFAULT_MASTER) -> int:
    """Write a bootable native .po and verify its files and allocation bitmap.

    ``files`` contains (name, ProDOS type, auxiliary type, data), including
    PRODOS and BASIC.SYSTEM supplied by runtime_files() if desired. This
    preserves caller-controlled .SYSTEM startup order. Returns used blocks.
    280 blocks makes a 140KB Disk II image; 1600 makes an 800KB SmartPort image.
    """
    files = [(name, kind, aux, bytes(data)) for name, kind, aux, data in files]
    valid_name = re.compile(r"[A-Z][A-Z0-9.]{0,14}\Z")
    if not valid_name.fullmatch(volume):
        raise ValueError(f"invalid ProDOS volume name: {volume!r}")
    if not 8 <= total_blocks <= 65535:
        raise ValueError("ProDOS volume must have 8..65535 blocks")
    if len(files) > 51:
        raise ValueError("root directory has capacity for 51 files")
    names: set[str] = set()
    for name, kind, aux, data in files:
        if not valid_name.fullmatch(name) or name in names:
            raise ValueError(f"invalid or duplicate ProDOS name: {name!r}")
        if not 0 <= kind <= 255 or not 0 <= aux <= 65535 or len(data) > 0xFFFFFF:
            raise ValueError(f"invalid ProDOS metadata/size: {name}")
        names.add(name)
    master = Path(master_path).read_bytes()
    read_prodos_disk(master_path)  # Reject malformed/non-ProDOS master inputs.
    image = bytearray(total_blocks * BLOCK)
    image[:2 * BLOCK] = master[:2 * BLOCK]
    bitmap_blocks = (total_blocks + 4095) // 4096
    next_free = 6 + bitmap_blocks

    def allocate() -> int:
        nonlocal next_free
        if next_free >= total_blocks:
            raise ValueError("ProDOS volume is full")
        result = next_free
        next_free += 1
        return result

    def put(number: int, data: bytes) -> None:
        if len(data) > BLOCK:
            raise ValueError("oversized ProDOS block write")
        image[number * BLOCK:number * BLOCK + len(data)] = data

    def pointers(numbers: list[int]) -> bytes:
        if len(numbers) > 256:
            raise ValueError("too many ProDOS index pointers")
        block = bytearray(BLOCK)
        for index, number in enumerate(numbers):
            block[index], block[index + 256] = number & 255, number >> 8
        return bytes(block)

    entries = []
    for name, kind, aux, data in files:
        before = next_free
        count = max(1, (len(data) + BLOCK - 1) // BLOCK)
        key = allocate()
        if count == 1:
            storage, numbers = 1, [key]
        elif count <= 256:
            storage = 2
            numbers = [allocate() for _ in range(count)]
            put(key, pointers(numbers))
        else:
            storage, numbers, branches = 3, [], []
            for start in range(0, count, 256):
                branch = allocate()
                branches.append(branch)
                part = [allocate() for _ in range(min(256, count - start))]
                put(branch, pointers(part))
                numbers.extend(part)
            put(key, pointers(branches))
        for index, number in enumerate(numbers):
            put(number, data[index * BLOCK:(index + 1) * BLOCK])
        entry = bytearray(39)
        entry[0] = storage << 4 | len(name)
        entry[1:1 + len(name)] = name.encode("ascii")
        entry[16] = kind
        entry[17:19] = key.to_bytes(2, "little")
        entry[19:21] = (next_free - before).to_bytes(2, "little")
        entry[21:24] = len(data).to_bytes(3, "little")
        entry[30] = 0xC3
        entry[31:33] = aux.to_bytes(2, "little")
        entry[37:39] = (2).to_bytes(2, "little")
        entries.append(entry)
    for number in range(2, 6):
        block = bytearray(BLOCK)
        block[:2] = (number - 1 if number > 2 else 0).to_bytes(2, "little")
        block[2:4] = (number + 1 if number < 5 else 0).to_bytes(2, "little")
        put(number, block)
    header = bytearray(39)
    header[0] = 0xF0 | len(volume)
    header[1:1 + len(volume)] = volume.encode("ascii")
    header[30:33] = bytes((0xC3, 39, 13))
    header[33:35] = len(entries).to_bytes(2, "little")
    header[35:37] = (6).to_bytes(2, "little")
    header[37:39] = total_blocks.to_bytes(2, "little")
    for position, entry in enumerate([header] + entries):
        offset = (2 + position // 13) * BLOCK + 4 + position % 13 * 39
        image[offset:offset + 39] = entry
    for number in range(next_free, total_blocks):
        image[6 * BLOCK + number // 8] |= 0x80 >> (number % 8)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image)
    read_volume, read_files = read_prodos_disk(destination)
    recovered = [(entry["name"], entry["type"], entry["aux"], entry["data"])
                 for entry in read_files]
    if read_volume != volume or recovered != files:
        raise ValueError("ProDOS write/read comparison failed")
    # Allocation is contiguous by construction; the independent reader above
    # also checks file pointers, sizes, ownership and blocks-used counts.
    for number in range(bitmap_blocks * 4096):
        free = bool(image[6 * BLOCK + number // 8] & (0x80 >> (number % 8)))
        if free != (next_free <= number < total_blocks):
            raise ValueError(f"ProDOS allocation bitmap mismatch at block {number}")
    return next_free
