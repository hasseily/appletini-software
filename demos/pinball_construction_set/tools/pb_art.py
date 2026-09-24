"""Decode the HGR picture saved after an original Apple II PCS table.

DISK.S COMPRESS emits zero runs as ``1, length`` (zero means 256),
literal runs as ``length, bytes`` (again zero means 256), and ends with
``1, 1``. The picture is HGR page 1, $2000-$3FFF. Only the left 154
pixels belong to the playfield in the Appletini port; those pixels become
its transparent 16-colour overlay layer.

Earlier BudgeCo demo files use a simpler stream: nonzero bytes are literal,
``$80, length`` emits zeroes, and ``$80, 1`` ends the picture. Both variants
are present in archived Apple II releases.
"""

HGR_SIZE = 0x2000
HGR_WIDTH = 280
TABLE_WIDTH = 154
TABLE_HEIGHT = 192


def decode_hgr_artwork(stream: bytes) -> bytes:
    """Return the original 8192-byte HGR page, rejecting malformed runs.

    DISK.S tests the destination's high byte *after* emitting a run. Its
    forced $FF sentinels at $3FFF/$4000 can therefore make the final run
    cross the page boundary by a few bytes. Saved EA tables also sometimes
    contain a repeated 1/1 terminator. Neither affects the HGR picture.
    """
    if stream.endswith(b"\x80\x01"):
        return _decode_budgeco_artwork(stream)
    out = bytearray()
    pos = 0
    while pos < len(stream):
        length = stream[pos]
        pos += 1
        if length == 1:
            if pos >= len(stream):
                raise ValueError("truncated zero run")
            amount = stream[pos]
            pos += 1
            if amount == 1:
                if not HGR_SIZE <= len(out) < HGR_SIZE + 256:
                    raise ValueError(f"HGR picture has {len(out)} bytes, expected 8192..8447")
                if stream[pos:] not in (b"", b"\x01\x01"):
                    raise ValueError("unexpected bytes after HGR picture terminator")
                return bytes(out[:HGR_SIZE])
            out.extend(bytes(amount or 256))
        else:
            amount = length or 256
            if pos + amount > len(stream):
                raise ValueError("truncated literal run")
            out.extend(stream[pos:pos + amount])
            pos += amount
        if len(out) >= HGR_SIZE + 256:
            raise ValueError("HGR picture exceeds 8447 bytes")
    raise ValueError("missing HGR picture terminator")


def _decode_budgeco_artwork(stream: bytes) -> bytes:
    """Decode the older zero-run escape stream found in BudgeCo DEMOs."""
    out = bytearray()
    pos = 0
    while pos < len(stream):
        value = stream[pos]
        pos += 1
        if value == 0x80:
            if pos >= len(stream):
                raise ValueError("truncated BudgeCo zero run")
            amount = stream[pos]
            pos += 1
            if amount == 1:
                if pos != len(stream) or len(out) != HGR_SIZE:
                    raise ValueError(f"BudgeCo HGR picture has {len(out)} bytes, expected 8192")
                return bytes(out)
            out.extend(bytes(amount or 256))
        else:
            out.append(value)
        if len(out) > HGR_SIZE:
            raise ValueError("BudgeCo HGR picture exceeds 8192 bytes")
    raise ValueError("missing BudgeCo HGR picture terminator")


def hgr_row_offset(y: int) -> int:
    """Byte offset of HGR page 1's scanline y (without its $2000 base)."""
    if not 0 <= y < TABLE_HEIGHT:
        raise ValueError("HGR scanline outside 0..191")
    return ((y & 7) << 10) | (((y >> 3) & 7) << 7) | ((y >> 6) * 40)


def hgr_to_overlay_pixels(hgr: bytes) -> list[list[int]]:
    """Map the playfield's HGR dots to Appletini palette indexes.

    Two adjacent lit dots read as white on the Apple II. An isolated dot
    uses the byte's colour-set bit and its even/odd column: violet/green
    or blue/orange. Zero is transparent so polygons below the artwork
    still show through the port's overlay.
    """
    if len(hgr) != HGR_SIZE:
        raise ValueError("HGR page must be exactly 8192 bytes")
    pixels = []
    for y in range(TABLE_HEIGHT):
        start = hgr_row_offset(y)
        dots = [False] * HGR_WIDTH
        phases = [False] * HGR_WIDTH
        for column in range(40):
            value = hgr[start + column]
            phase = bool(value & 0x80)
            for bit in range(7):
                x = 7 * column + bit
                dots[x] = bool(value & (1 << bit))
                phases[x] = phase
        row = []
        for x in range(TABLE_WIDTH):
            if not dots[x]:
                row.append(0)
            elif (x > 0 and dots[x - 1]) or dots[x + 1]:
                row.append(4)        # white
            elif phases[x]:
                row.append(12 if x % 2 == 0 else 7)  # blue / orange
            else:
                row.append(14 if x % 2 == 0 else 10)  # violet / green
        pixels.append(row)
    return pixels
