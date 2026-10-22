#!/usr/bin/env python3
"""Arrange a Standard MIDI File as a libtini pattern song.

An arrangement JSON names a bar range, the loop bar, the row resolution and
one entry per AY voice: a MIDI channel and a chord slot, 0 for the highest
note that starts at a row, 1 for the next lower and so on. Each voice plays
one note at a time; a later note cuts the earlier one. Drums and notes in
unused slots are left out, and the report counts them. The output is the
song JSON that tools/music.py compiles. The MIDI file itself is read only.
"""
import argparse
import json
from pathlib import Path
import struct

NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
TRACK_KEYS = {"name", "channel", "slot", "volume", "decay", "floor", "transpose"}


def variable(data, i, end):
    value = 0
    for _ in range(4):
        if i >= end:
            raise ValueError("truncated MIDI variable-length number")
        byte = data[i]
        i += 1
        value = (value << 7) | (byte & 127)
        if not byte & 128:
            return value, i
    raise ValueError("MIDI variable-length number longer than four bytes")


def read_midi(data):
    """Division, notes per channel (start, end, key) in ticks, tempos and meters."""
    if len(data) < 14 or data[:4] != b"MThd":
        raise ValueError("not a Standard MIDI File")
    length, _, count, division = struct.unpack(">IHHH", data[4:14])
    if length < 6 or division & 0x8000 or not division:
        raise ValueError("unsupported MIDI header or SMPTE timing")
    position = 8 + length
    notes, tempos, meters = {}, [], []
    for _ in range(count):
        if data[position:position + 4] != b"MTrk" or position + 8 > len(data):
            raise ValueError("missing MIDI track")
        size = struct.unpack(">I", data[position + 4:position + 8])[0]
        i, end = position + 8, position + 8 + size
        if end > len(data):
            raise ValueError("truncated MIDI track")
        position = end
        tick, status, sounding = 0, 0, {}
        while i < end:
            delta, i = variable(data, i, end)
            tick += delta
            if i >= end:
                raise ValueError("truncated MIDI event")
            byte = data[i]
            if byte == 0xFF:
                if i + 2 > end:
                    raise ValueError("truncated MIDI meta event")
                kind = data[i + 1]
                size, j = variable(data, i + 2, end)
                body = data[j:j + size]
                if kind == 0x2F:
                    break
                if kind == 0x51 and size == 3:
                    tempos.append((tick, int.from_bytes(body, "big")))
                if kind == 0x58 and size >= 2:
                    meters.append((tick, body[0], 2 ** body[1]))
                i = j + size
                continue
            if byte in (0xF0, 0xF7):
                size, j = variable(data, i + 1, end)
                i = j + size
                continue
            if byte & 128:
                status = byte
                i += 1
            if not status:
                raise ValueError("MIDI data byte without a status")
            kind, channel = status & 0xF0, status & 15
            width = 1 if kind in (0xC0, 0xD0) else 2
            if i + width > end:
                raise ValueError("truncated MIDI channel event")
            args = data[i:i + width]
            i += width
            if kind == 0x90 and args[1]:
                sounding.setdefault((channel, args[0]), []).append(tick)
            elif kind == 0x80 or kind == 0x90:
                starts = sounding.get((channel, args[0]))
                if starts:
                    notes.setdefault(channel + 1, []).append((starts.pop(0), tick, args[0]))
    return division, notes, sorted(tempos), sorted(meters)


def name_of(key):
    return NAMES[key % 12] + str(key // 12 - 1)


def playable(key):
    """Fold a note into the octaves whose AY periods fit 1..2047."""
    while round(1_000_000 / (16 * 440 * 2 ** ((key - 69) / 12))) > 2047:
        key += 12
    while round(1_000_000 / (16 * 440 * 2 ** ((key - 69) / 12))) < 16:
        key -= 12
    return key


def arrange(data, plan):
    division, notes, tempos, meters = read_midi(data)
    first, last = plan["bars"]
    loop_bar, per_beat = plan.get("loop_bar", first), plan["rows_per_beat"]
    if type(per_beat) is not int or not 1 <= per_beat <= 16:
        raise ValueError("rows_per_beat must be 1..16")
    if not (type(first) is int and type(last) is int and 0 <= first <= last and first <= loop_bar <= last):
        raise ValueError("bars must be [first, last] with the loop bar inside")
    numerator, denominator = 4, 4
    for tick, top, bottom in meters:
        if tick <= 0:
            numerator, denominator = top, bottom
        else:
            raise ValueError("meter changes are not supported")
    bar_ticks = division * 4 * numerator // denominator
    rows_per_bar = per_beat * 4 * numerator // denominator
    start, end = first * bar_ticks, (last + 1) * bar_ticks
    tempo = 500000
    for tick, value in tempos:
        if tick <= start:
            tempo = value
        elif tick < end:
            raise ValueError(f"tempo changes inside the bar range, at bar {tick / bar_ticks:.2f}")
    bars = last - first + 1
    total = bars * rows_per_bar

    def row(tick):
        return round((tick - start) * per_beat / division)

    tracks, patterns, bodies = [], {}, {}
    report = {"tracks": [], "unassigned": {}}
    slots = {}
    for entry in plan["tracks"]:
        if not isinstance(entry, dict) or not set(entry) <= TRACK_KEYS or "channel" not in entry:
            raise ValueError("each arranged track needs a channel and only known keys")
        slots.setdefault(entry["channel"], set()).add(entry.get("slot", 0))
    for channel, used in slots.items():
        groups = {}
        for on, off, key in notes.get(channel, []):
            if on < end and off > start:
                groups.setdefault(max(row(on), 0), set()).add(key)
        report["unassigned"][str(channel)] = sum(len(keys) - len(used & set(range(len(keys))))
                                                 for keys in groups.values())
    for entry in plan["tracks"]:
        channel, slot = entry["channel"], entry.get("slot", 0)
        transpose = entry.get("transpose", 0)
        groups = {}
        for on, off, key in notes.get(channel, []):
            if on >= end or off <= start:
                continue
            begin = max(row(on), 0)
            groups.setdefault(begin, {})
            groups[begin][key] = max(groups[begin].get(key, 0), min(max(row(off), begin + 1), total))
        line = []
        for begin in sorted(groups):
            keys = sorted(groups[begin], reverse=True)
            if slot < len(keys):
                line.append([begin, groups[begin][keys[slot]], playable(keys[slot] + transpose)])
        for this, following in zip(line, line[1:]):
            this[1] = min(this[1], following[0])
        # Rows per bar: (symbol, rows), with rests in the gaps and holds
        # where a note crosses a bar line.
        cells = [[] for _ in range(bars)]
        cursor = 0

        def emit(symbol, begin, finish):
            while begin < finish:
                bar = begin // rows_per_bar
                stop = min(finish, (bar + 1) * rows_per_bar)
                cells[bar].append((symbol, stop - begin))
                symbol = "^" if symbol != "-" else "-"
                begin = stop

        for begin, finish, key in line:
            emit("-", cursor, begin)
            emit(name_of(key), begin, finish)
            cursor = finish
        emit("-", cursor, total)
        order, made = [], 0
        name = entry.get("name", "track" + str(len(tracks)))
        for cell in cells:
            merged = []
            for symbol, rows in cell:
                if merged and symbol in ("-", "^") and merged[-1][0] == symbol:
                    merged[-1] = (symbol, merged[-1][1] + rows)
                else:
                    merged.append((symbol, rows))
            text = " ".join(f"{symbol}:{rows}" for symbol, rows in merged)
            if text not in bodies:
                bodies[text] = f"{name}_{made}"
                patterns[bodies[text]] = text
                made += 1
            order.append(bodies[text])
        tracks.append({"name": name, "volume": entry.get("volume", 12), "decay": entry.get("decay", 0),
                       "floor": entry.get("floor", 0), "order": order})
        report["tracks"].append({"name": name, "channel": channel, "slot": slot, "notes": len(line),
                                 "patterns": len(set(order))})
    song = {"bpm": round(60_000_000 / tempo, 3), "rows_per_beat": per_beat,
            "loop": loop_bar - first, "tracks": tracks, "patterns": patterns}
    return song, report


def song_text(document):
    """JSON with one line per track and per pattern."""
    song = document["song"]
    tracks = [json.dumps(track) for track in song["tracks"]]
    patterns = [json.dumps(name) + ": " + json.dumps(text) for name, text in song["patterns"].items()]
    return "\n".join([
        "{", ' "credit": ' + json.dumps(document["credit"]) + ",",
        ' "source": ' + json.dumps(document["source"]) + ",",
        ' "song": {', '  "bpm": ' + json.dumps(song["bpm"]) + ', "rows_per_beat": ' +
        str(song["rows_per_beat"]) + ', "loop": ' + str(song["loop"]) + ",",
        '  "tracks": [', ",\n".join("   " + line for line in tracks), "  ],",
        '  "patterns": {', ",\n".join("   " + line for line in patterns), "  }", " }", "}"]) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midi", type=Path)
    parser.add_argument("arrangement", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.arrangement.read_text(encoding="utf-8"))
    try:
        song, report = arrange(args.midi.read_bytes(), plan)
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error)) from None
    document = {"credit": plan.get("credit", ""), "source": plan.get("source", args.midi.name), "song": song}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(song_text(document), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
