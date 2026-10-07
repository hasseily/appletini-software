"""PHS1: bounded deltas and sparse register writes, with strict round-trip decoding."""

from __future__ import annotations

import struct

HEADER = struct.Struct("<4sHHII")
RECORD = struct.Struct("<HB")


def valid_write(target, reg, value):
    return (type(target) is int and type(reg) is int and type(value) is int
            and 0 <= value <= 255 and
            ((0 <= target <= 3 and 0 <= reg <= 13) or (4 <= target <= 5 and 0 <= reg <= 4)))


def encode(events, tick_hz: int, duration_ticks: int) -> bytes:
    if type(tick_hz) is not int or not 25 <= tick_hz <= 400:
        raise ValueError("tick_hz must be 25..400")
    if type(duration_ticks) is not int or not 1 <= duration_ticks <= 0xFFFFFFFF:
        raise ValueError("duration_ticks must be 1..4294967295")
    groups = []
    last = 0
    writes_this_tick = 0
    for tick, target, reg, value in events:
        if type(tick) is not int or not last <= tick <= duration_ticks:
            raise ValueError("event ticks must be sorted within duration")
        if not valid_write(target, reg, value):
            raise ValueError("invalid target, register or byte")
        writes_this_tick = writes_this_tick + 1 if tick == last else 1
        if writes_this_tick > 255:
            raise ValueError("more than 255 register writes on one tick")
        if not groups or tick != groups[-1][0] or len(groups[-1][1]) == 255:
            groups.append((tick, []))
        groups[-1][1].append(((target << 4) | reg, value))
        last = tick
    # A trailing wait makes the declared duration unambiguous even for silence.
    if not groups or groups[-1][0] < duration_ticks:
        groups.append((duration_ticks, []))
    body = bytearray()
    count = 0
    previous = 0
    for tick, writes in groups:
        delta = tick - previous
        while delta > 65535:
            body.extend(RECORD.pack(65535, 0))
            delta -= 65535
            count += 1
        body.extend(RECORD.pack(delta, len(writes)))
        for opcode, value in writes:
            body.extend((opcode, value))
        previous = tick
        count += 1
    return HEADER.pack(b"PHS1", tick_hz, 0, duration_ticks, count) + body


def decode(data: bytes) -> tuple[list, dict]:
    if len(data) < HEADER.size:
        raise ValueError("truncated PHS1 header")
    magic, tick_hz, flags, duration, records = HEADER.unpack_from(data)
    if magic != b"PHS1" or flags != 0 or not 25 <= tick_hz <= 400 or not duration or not records:
        raise ValueError("invalid PHS1 header")
    if records > (len(data) - HEADER.size) // RECORD.size:
        raise ValueError("truncated PHS1 record table")
    pos = HEADER.size
    tick = 0
    events = []
    same_tick_records = 0
    writes_this_tick = 0
    for _ in range(records):
        if pos + RECORD.size > len(data):
            raise ValueError("truncated PHS1 record")
        delta, count = RECORD.unpack_from(data, pos)
        same_tick_records = 1 if delta else same_tick_records + 1
        if same_tick_records > 64:
            raise ValueError("more than 64 records on one tick")
        writes_this_tick = writes_this_tick + count if not delta else count
        if writes_this_tick > 255:
            raise ValueError("more than 255 register writes on one tick")
        pos += RECORD.size
        tick += delta
        if tick > duration or pos + count * 2 > len(data):
            raise ValueError("invalid or truncated PHS1 event")
        for _ in range(count):
            opcode, value = data[pos:pos + 2]
            target, reg = opcode >> 4, opcode & 15
            if not valid_write(target, reg, value):
                raise ValueError("invalid PHS1 register opcode")
            events.append((tick, target, reg, value))
            pos += 2
    if pos != len(data) or tick != duration:
        raise ValueError("PHS1 trailing bytes or missing terminal duration")
    return events, {"tick_hz": tick_hz, "duration_ticks": duration, "record_count": records, "bytes": len(data)}
