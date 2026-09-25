#!/usr/bin/env python3
"""Check linked images, banking metadata, preload bytes, and memory budgets.

Run by the Makefile after ld65 (src/doom.cfg). Checks what the loader and
the kernel rely on:

  DOOM.SYSTEM  starts with code at $2000 and ends below $4000 (the LC.BIN
               stage at $6000 and the loader's buffers are above it)
  RENDER.BIN   $0200 up, ends below VIEWBUF ($8B80)
  LC.BIN       exactly 16,384 bytes; the jump table at $E000 (offset
               $1000) starts with JMP; the IRQ vector (offset $2FFE)
               points into the card
  GAME.BIN     $0200 up, ends below reserved intercept scratch ($B380)
               in banked builds; legacy builds end below the C stack ($B800)

For builds with banked.json, use doom-banked.cfg and the final map/labels
to validate every code bank, its vectors and public entry descriptors,
and the exact preload package installed by the loader. Include BSS and
address gaps in the main-arena budget. The conservative arena gate is
for the current converted nine-map Freedoom set and 160 actors.

Print the bytes used and free in each area. --json writes the same report
for tests and build diagnostics. Legacy stand-in builds retain their
original configuration and reporting format.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

AREAS = {   # name: (start, size, what) -- src/doom.cfg
    "KZP": (0x0002, 0x00DE, "zero page, kernel and renderer"),
    "CZP": (0x00E0, 0x0020, "zero page, cc65"),
    "LOADER": (0x2000, 0x2000, "DOOM.SYSTEM"),
    "RLOW": (0x0200, 0x0200, "RENDER $0200-$03FF"),
    "RTEXT": (0x0400, 0x0800, "RENDER $0400-$0BFF (read-only)"),
    "RMAIN": (0x0C00, 0x7F80, "RENDER $0C00-$8B7F"),
    "LC2": (0xD000, 0x1000, "LC bank 2 $D000-$DFFF"),
    "LCHI": (0xE000, 0x1FFA, "LC $E000-$FFF9"),
    "LCVEC": (0xFFFA, 0x0006, "LC vectors"),
    "LC1": (0xD000, 0x1000, "LC bank 1 $D000-$DFFF"),
    "GAME": (0x0200, 0xB600, "GAME bank 1 $0200-$B7FF"),
}

# Conservative bound for the converted nine-map Freedoom asset set: the
# largest level after moving block heads far, plus 160 64-byte actors.
BANKED_ARENA_REQUIRED = 30_604
BANKED_PACKET_BYTES = 2_600
BANKED_INTERCEPT_BYTES = 1_152
BANKED_INTERCEPT_START = 0xB380


def config_records(cfg: str, section: str) -> dict[str, dict[str, str]]:
    """The generated ld65 configuration uses literal, named properties."""
    cfg = re.sub(r"#[^\n]*", "", cfg)
    match = re.search(r"\b" + section + r"\s*\{([^}]*)\}", cfg, re.S)
    if match is None:
        raise ValueError(f"configuration has no {section} block")
    result = {}
    for name, body in re.findall(r"(\w+)\s*:\s*([^;]+);", match[1]):
        result[name] = dict(re.findall(r'(\w+)\s*=\s*("[^"]*"|[^,]+)', body))
        result[name] = {k: v.strip().strip('"') for k, v in result[name].items()}
    return result


def number(value: str) -> int:
    return int(value[1:], 16) if value.startswith("$") else int(value, 10)


def map_segments(text: str) -> dict[str, dict[str, int]]:
    if "Segment list:" not in text:
        raise ValueError("map file has no segment list")
    body = text.split("Segment list:", 1)[1].split("Exports list", 1)[0]
    result = {}
    for name, start, end, size in re.findall(
            r"^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+([0-9A-F]{6})", body, re.M):
        result[name] = {"start": int(start, 16), "end": int(end, 16) + 1,
                        "size": int(size, 16)}
    return result


def read_labels(path: Path) -> dict[str, int]:
    return {name: int(value, 16) for value, name in
            re.findall(r"^al\s+([0-9A-Fa-f]+)\s+\.([^\s]+)", path.read_text(), re.M)}


def banked_report(build: Path) -> tuple[dict, list[str]]:
    """Check the actual integrated link and the exact bytes the loader uses.

    Areas with equal CPU addresses are deliberately distinct physical
    memories. Check overlap within each configured area, never between a
    game's LC bank and another LC bank or the renderer's phase image.
    """
    errors: list[str] = []
    metadata = json.loads((build / "banked.json").read_text())
    inventory = json.loads((build / "banks/banks.json").read_text())
    cfg = (build / "doom-banked.cfg").read_text()
    areas = config_records(cfg, "MEMORY")
    assignments = config_records(cfg, "SEGMENTS")
    segments = map_segments((build / "doom.map").read_text())
    labels = read_labels(build / "doom.lbl")
    overlay_names = ("AMEMCOPY", "AMEMPROBE", "AMEMFILL")
    if metadata.get("memory_api_optional"):
        for name in overlay_names:
            area = areas.get(name + "RUN", {})
            if number(area.get("start", "0")) != labels.get("kbuf"):
                errors.append(f"{name}: overlay must run in the existing kbuf")
    if metadata.get("format") != 1 or inventory.get("format") != 1:
        errors.append("unsupported banked build metadata format")
    runtime_banks = metadata.get("banks", {})
    banks = list(runtime_banks.values())
    if (not banks or len(set(banks)) != len(banks) or
            any(not (96 <= bank < 122 or group == "control" and bank == 0)
                for group, bank in runtime_banks.items())):
        errors.append("code banks must be distinct RamWorks banks 96..121, "
                      "with only control optionally resident in base auxiliary bank 0")
    if metadata.get("banks") != inventory.get("banks"):
        errors.append("banked.json and banks/banks.json disagree: stale bank inventory")
    staging = metadata.get("code_staging", {})
    if not isinstance(staging, dict):
        staging = {}
    if set(staging) != {str(bank) for bank in banks}:
        errors.append("code_staging must name exactly every runtime code bank")
    if metadata.get("code_staging") != inventory.get("code_staging"):
        errors.append("banked.json and banks/banks.json disagree: stale code staging")
    stages = list(staging.values())
    stages_valid = bool(stages) and all(type(bank) is int and 96 <= bank < 122 for bank in stages)
    if not stages_valid or len(set(stages)) != len(stages):
        errors.append("code staging banks must be distinct RamWorks banks 96..121")
    if stages_valid and sorted(stages) != list(range(min(stages), max(stages) + 1)):
        errors.append("code staging banks must form a contiguous range")
    if any(bank != 0 and staging.get(str(bank)) != bank for bank in banks):
        errors.append("nonzero runtime code banks must retain the same staging bank")
    expected_platform = {"game_home": 125, "render_home": 122, "packet_bank": 124,
                         "packet_address": 0x0200, "tables_bank": 127, "info_bank": 1}
    for key, expected in expected_platform.items():
        if metadata.get(key) != expected:
            errors.append(f"banked.json {key} disagrees with the platform mapping ({expected})")
    expected_bank_areas = {f"GB{b}" for b in banks} | {f"GBV{b}" for b in banks}
    actual_bank_areas = {name for name in areas if re.fullmatch(r"GBV?\d+", name)}
    if actual_bank_areas != expected_bank_areas:
        errors.append("configured code-bank areas disagree with banked.json")
    for name, start, size in (("GAME", 0x0200, 0xB180), ("GZPMEM", 0x0040, 8),
                              ("ISCRATCH", BANKED_INTERCEPT_START, BANKED_INTERCEPT_BYTES),
                              ("INFO", 0x6000, 0x1000)):
        area = areas.get(name, {})
        if (number(area.get("start", "0")), number(area.get("size", "0"))) != (start, size):
            errors.append(f"{name}: configured address window disagrees with banked runtime")
    if number(areas.get("TABLES", {}).get("start", "0")) != 0x0200:
        errors.append("TABLES must be linked at its far-load address $0200")
    scratch_area = areas.get("ISCRATCH", {})
    if (scratch_area.get("file") != "" or scratch_area.get("type") != "rw" or
            scratch_area.get("define") != "yes"):
        errors.append("ISCRATCH must be defined writable RAM with no initialized output file")
    report = {}
    file_sizes: dict[str, int] = {}
    members = {name: [] for name in areas}
    for name, segment in segments.items():
        assignment = assignments.get(name)
        if assignment is None or assignment.get("load") not in areas:
            errors.append(f"{name}: mapped segment has no configured memory area")
            continue
        load, run = assignment["load"], assignment.get("run", assignment["load"])
        if run != load:
            if not metadata.get("memory_api_optional") or name not in overlay_names or run not in areas:
                errors.append(f"{name}: unsupported distinct load/run mapping")
                continue
            address = labels.get(f"__{name}_LOAD__", 0)
            loaded = {"start": address, "end": address + segment["size"], "size": segment["size"]}
            members[load].append((name, loaded, assignment))
            members[run].append((name, segment, assignment))
        else:
            members[load].append((name, segment, assignment))
    for name, area in areas.items():
        start, size = number(area["start"]), number(area["size"])
        end = start + size
        high = start
        occupied_end = start
        file_end = start
        used = 0
        for segment_name, segment, assignment in sorted(members[name], key=lambda v: v[1]["start"]):
            lo, hi, count = segment["start"], segment["end"], segment["size"]
            if not count:
                continue
            if hi - lo != count:
                errors.append(f"{segment_name}: inconsistent map extent/size")
            if lo < start or hi > end:
                errors.append(f"{segment_name}: ${lo:04X}-${hi-1:04X} exceeds {name} "
                              f"${start:04X}-${end-1:04X}")
            if lo < occupied_end:
                errors.append(f"{segment_name}: overlaps an earlier segment in {name}")
            occupied_end = max(occupied_end, hi)
            high = max(high, hi)
            used += count
            if assignment.get("type") != "bss":
                file_end = max(file_end, hi)
        report[name] = {"start": start, "size": size, "used": used,
                        "occupied": high - start, "free": end - high,
                        "what": area.get("file", "") or "zero page / reserved RAM"}
        filename = area.get("file", "")
        if filename:
            filename = filename.removeprefix("%O")
            if Path(filename).name != filename:
                raise ValueError(f"unsupported output path in configuration: {filename}")
            span = size if area.get("fill") == "yes" else file_end - start
            file_sizes[filename] = file_sizes.get(filename, 0) + span

    # rview is mutable auxiliary LC RAM, omitted from initialized segment
    # bytes. Its whole extent must nevertheless fit beside the control code.
    control_bank = metadata.get("banks", {}).get("control")
    expected_packet = {"bank": control_bank, "segment": "GVIEW", "bytes": BANKED_PACKET_BYTES}
    if control_bank is None or inventory.get("lc_packet") != expected_packet:
        errors.append("LC packet inventory must describe a 2600-byte GVIEW in the control bank")
    view = segments.get("GVIEW", {})
    view_assignment = assignments.get("GVIEW", {})
    control_area = f"GB{control_bank}"
    if (view_assignment.get("load") != control_area or
            view_assignment.get("run", control_area) != control_area or
            view_assignment.get("type") != "bss"):
        errors.append("GVIEW must be mutable BSS in the control LC bank")
    if view.get("size") != BANKED_PACKET_BYTES:
        errors.append("GVIEW must reserve the complete 2600-byte render packet")
    if view:
        code_end = segments.get(control_area, {}).get("end", 0x10000)
        if not 0xD000 <= code_end <= view["start"] < view["end"] <= 0xFFFA:
            errors.append("GVIEW must fit after control code and before LC vectors at $FFFA")
        if labels.get("_rview") != view["start"]:
            errors.append("_rview does not point to the start of GVIEW: stale labels or placement")
        if (labels.get("__GVIEW_RUN__"), labels.get("__GVIEW_SIZE__")) != (view["start"], view["size"]):
            errors.append("GVIEW map and label values disagree: stale map/labels")
        report["lc_packet"] = {"bank": control_bank, "start": view["start"],
                                "end": view["end"], "bytes": view["size"]}

    # Intercepts are cleared and reused frequently. Keep the entire buffer
    # above the Apple display windows and outside both malloc and the C stack.
    scratch = segments.get("GINTERCEPTS", {})
    scratch_assignment = assignments.get("GINTERCEPTS", {})
    if (scratch_assignment.get("load") != "ISCRATCH" or
            scratch_assignment.get("run", "ISCRATCH") != "ISCRATCH" or
            scratch_assignment.get("type") != "bss" or
            scratch_assignment.get("define") != "yes"):
        errors.append("GINTERCEPTS must be defined BSS in the dedicated ISCRATCH area")
    if scratch.get("size") != BANKED_INTERCEPT_BYTES:
        errors.append("GINTERCEPTS must reserve the complete 1152-byte intercept buffer")
    if scratch:
        if not 0x6000 <= scratch["start"] < scratch["end"] == 0xB800:
            errors.append("GINTERCEPTS must stay above display RAM and end at the $B800 stack boundary")
        if scratch["start"] != BANKED_INTERCEPT_START:
            errors.append("GINTERCEPTS must start at the reserved $B380 intercept address")
        if labels.get("_intercepts") != scratch["start"]:
            errors.append("_intercepts does not point to the start of GINTERCEPTS")
        if (labels.get("__GINTERCEPTS_RUN__"), labels.get("__GINTERCEPTS_SIZE__")) != (
                scratch["start"], scratch["size"]):
            errors.append("GINTERCEPTS map and label values disagree: stale map/labels")
    if (labels.get("__ISCRATCH_START__"), labels.get("__ISCRATCH_SIZE__")) != (
            number(scratch_area.get("start", "0")), number(scratch_area.get("size", "0"))):
        errors.append("ISCRATCH configuration and label values disagree: stale config/labels")

    images = {}
    for filename, expected in file_sizes.items():
        path = build / filename
        if not path.is_file():
            errors.append(f"{filename}: missing linked image")
            continue
        blob = path.read_bytes()
        images[filename] = blob
        if len(blob) != expected:
            errors.append(f"{filename}: {len(blob)} bytes; map/config require {expected} "
                          "(truncated, stale, or mixed build)")
    stale = {p.name for p in build.glob("GBANK*.BIN")} - {f"GBANK{b}.BIN" for b in banks}
    if stale:
        errors.append("unlisted stale code-bank images: " + ", ".join(sorted(stale)))
    system = images.get("DOOM.SYSTEM", b"")
    if not system or system[0] not in (0xD8, 0x78, 0xA2, 0x4C):
        errors.append("DOOM.SYSTEM does not start with loader code")
    count = labels.get("CODE_BANK_COUNT")
    if count != len(banks):
        errors.append("loader CODE_BANK_COUNT does not match the runtime bank inventory")
    install_tables = {}
    for name in ("lc_install_sources", "lc_install_targets"):
        offset = labels.get(name, 0) - 0x2000
        if count is None or offset < 0 or offset + len(banks) > len(system):
            errors.append(f"DOOM.SYSTEM {name} table is missing or outside the loader image")
        else:
            install_tables[name] = system[offset:offset + len(banks)]
    if len(install_tables) == 2:
        pairs = list(zip(install_tables["lc_install_sources"], install_tables["lc_install_targets"]))
        expected_pairs = {(staging.get(str(bank)), bank) for bank in banks}
        if len(set(pairs)) != len(banks) or set(pairs) != expected_pairs:
            errors.append("DOOM.SYSTEM LC installation tables disagree with code_staging/runtime banks")
    lc = images.get("LC.BIN", b"")
    if len(lc) != 0x4000 or lc[0x1000] != 0x4C:
        errors.append("LC.BIN must be 16384 bytes with the kernel jump table at $E000")
    elif int.from_bytes(lc[0x2FFE:0x3000], "little") < 0xD000:
        errors.append("LC.BIN IRQ vector does not point into main LC")
    game = images.get("GAME.BIN", b"")
    for bank in banks:
        code_area, vectors = areas.get(f"GB{bank}", {}), areas.get(f"GBV{bank}", {})
        if tuple(number(v) for v in (code_area.get("start", "0"), code_area.get("size", "0"),
                 vectors.get("start", "0"), vectors.get("size", "0"))) != (0xD000, 0x2FFA, 0xFFFA, 6):
            errors.append(f"bank {bank}: expected $D000-$FFF9 code and $FFFA-$FFFF vectors")
        blob = images.get(f"GBANK{bank}.BIN", b"")
        expected_vectors = struct.pack("<HHH", labels["gb_nmi"], 0, labels["gb_irq"])
        if len(blob) != 0x3000 or blob[-6:] != expected_vectors:
            errors.append(f"GBANK{bank}.BIN: wrong size or stale NMI/reset/IRQ vectors")
    for symbol in ("gb_call", "gb_irq", "gb_nmi"):
        if not 0x0200 <= labels[symbol] < 0x0200 + len(game):
            errors.append(f"{symbol}: gateway is not resident in the initialized main GAME image")
    entries = inventory.get("entries", [])
    if len(entries) * 6 != segments.get("GBSTUBS", {}).get("size"):
        errors.append("entry inventory does not match the linked GBSTUBS segment")
    if len({entry["public"] for entry in entries}) != len(entries):
        errors.append("bank entry inventory contains duplicate public symbols")
    for entry in entries:
        public, private, group = entry["public"], entry["private"], entry["group"]
        if public not in labels or private not in labels or group not in metadata["banks"]:
            errors.append(f"{public}: bank inventory entry missing from final link")
            continue
        bank = metadata["banks"][group]
        address, target = labels[public], labels[private]
        code = segments[f"GB{bank}"]
        if not code["start"] <= target < code["end"]:
            errors.append(f"{public}: private target is outside its linked bank {bank}")
        stub = bytes([0x20]) + struct.pack("<H", labels["gb_call"]) + bytes([bank]) + struct.pack("<H", target)
        offset = address - 0x0200
        if offset < 0 or game[offset:offset + 6] != stub:
            errors.append(f"{public}: stale or invalid bank-call descriptor in GAME.BIN")

    preload_name = metadata.get("preload_file", "")
    if Path(preload_name).name != preload_name or not preload_name:
        raise ValueError("invalid preload filename in banked.json")
    package = (build / preload_name).read_bytes()
    expected_payloads = {(staging.get(str(b)), 0x0200): images.get(f"GBANK{b}.BIN", b"") for b in banks}
    expected_payloads[(127, 0x0200)] = images.get("GAME.TABLES", b"")
    expected_payloads[(1, 0x6000)] = images.get("GAME.INFO", b"")
    if metadata.get("memory_api_optional"):
        expected_payloads[(122, 0xB800)] = images.get("AMEM.BIN", b"")
        if len(expected_payloads[(122, 0xB800)]) != 768:
            errors.append("AMEM.BIN must contain three complete 256-byte overlays")
        for i, name in enumerate(overlay_names):
            segment = segments.get(name, {})
            if (segment.get("start"), segment.get("size"), labels.get(f"__{name}_LOAD__")) != (
                    labels.get("kbuf"), 256, 0xB800 + 256*i):
                errors.append(f"{name}: overlay extent or immutable backing address changed")
        if not (labels.get("__KBSS_RUN__", 0) <= labels.get("kbuf", 0)
                and labels.get("kbuf", 0) + 256 <= labels.get("__KBSS_RUN__", 0) + labels.get("__KBSS_SIZE__", 0)):
            errors.append("AMEM overlays must fit in the existing resident 256-byte kbuf")
    preload_errors = check_preload(package, expected_payloads)
    errors.extend(f"{preload_name}: {error}" for error in preload_errors)
    bss = segments["BSS"]
    stack_start, stack_size = labels["__STACKSTART__"], labels["__STACKSIZE__"]
    stack_bottom = stack_start - stack_size
    if (stack_start, stack_size) != (0xC000, 0x0800):
        errors.append("banked GAME must retain the $B800-$BFFF 2048-byte software stack")
    if labels["__BSS_RUN__"] != bss["start"] or labels["__BSS_SIZE__"] != bss["size"]:
        errors.append("BSS map and label values disagree: stale map/labels")
    arena_end = number(scratch_area.get("start", "0"))
    if not bss["end"] <= arena_end < stack_bottom:
        errors.append("main arena overlaps intercept scratch or the software stack")
    if scratch and (scratch["start"] != arena_end or scratch["end"] != stack_bottom):
        errors.append("intercept scratch must fill the gap between the main arena and software stack")
    if "_arena_bounds" in labels:
        offset = labels["_arena_bounds"] - 0x0200
        expected_bounds = struct.pack("<HHHHH", bss["end"], arena_end, 0, 0, 0)
        if offset < 0 or game[offset:offset + 10] != expected_bounds:
            errors.append("GAME.BIN arena bounds do not match the permanent-code-bank layout")
    else:
        errors.append("GAME.BIN arena bounds label is missing")
    arena = arena_end - bss["end"]
    if arena < BANKED_ARENA_REQUIRED:
        errors.append(f"main arena has {arena} bytes; conservative nine-map/160-actor "
                      f"budget requires {BANKED_ARENA_REQUIRED}")
    report["main_arena"] = {"start": bss["end"], "end": arena_end, "bytes": arena,
                            "stack_bytes": stack_size, "actor_pool_bytes": 10_240,
                            "conservative_required_bytes": BANKED_ARENA_REQUIRED,
                            "conservative_margin_bytes": arena - BANKED_ARENA_REQUIRED}
    report["files"] = {name: len(blob) for name, blob in images.items()}
    report["files"][preload_name] = len(package)
    report["banked"] = metadata
    return report, errors


def check_preload(package: bytes, expected: dict[tuple[int, int], bytes]) -> list[str]:
    """Reject truncated, duplicated, stale, or incorrectly placed payloads."""
    if len(package) < 256 or package[:5] != b"A2DM\x01":
        return ["missing A2DM version-1 preload header"]
    count = package[5]
    if 8 + count * 5 > 256:
        return ["segment descriptors exceed the 256-byte header"]
    errors, seen = [], set()
    pos = 256
    for n in range(count):
        bank, address, size = struct.unpack_from("<BHH", package, 8 + 5 * n)
        key = bank, address
        if key in seen:
            errors.append(f"duplicate segment {bank}:${address:04X}")
        seen.add(key)
        if not size or address < 0x0200 or address + size > 0xC000:
            errors.append(f"invalid lower-RAM segment {bank}:${address:04X}/{size}")
        payload = package[pos:pos + size]
        if key not in expected:
            errors.append(f"unexpected segment {bank}:${address:04X}")
        elif payload != expected[key]:
            errors.append(f"segment {bank}:${address:04X} differs from its linked image (stale preload)")
        pos += size
    if seen != set(expected):
        errors.append("preload segment inventory does not match the linked code/tables/info")
    if pos != len(package):
        errors.append("preload payload is truncated or has trailing bytes")
    return errors


def area_usage(map_text: str) -> dict:
    """{memory area: bytes used}, from the map's segment list and the cfg's
    segment-to-area assignment."""
    cfg = (Path(__file__).resolve().parents[1] / "src/doom.cfg").read_text()
    seg_area = dict(re.findall(r"^\s*(\w+):\s*load\s*=\s*(\w+)", cfg, re.M))
    used = {name: 0 for name in AREAS}
    part = map_text.split("Segment list:")[1].split("Exports list")[0]
    for line in part.splitlines():
        m = re.match(r"^(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+([0-9A-F]{6})", line)
        if m and m.group(1) in seg_area:
            used[seg_area[m.group(1)]] += int(m.group(4), 16)
    return used


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", type=Path, default=Path("build"))
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    b = args.build
    if (b / "banked.json").is_file():
        try:
            report, errors = banked_report(b)
        except (OSError, ValueError, KeyError, TypeError, struct.error) as exc:
            print(f"check_link: incomplete or inconsistent banked build: {exc}", file=sys.stderr)
            return 1
        if args.json:
            args.json.write_text(json.dumps(report, indent=1) + "\n")
        if not args.quiet:
            for name, item in report.items():
                if name not in ("files", "banked", "main_arena", "lc_packet"):
                    print(f"  {name:8s} {item['used']:6d} used {item['free']:6d} free")
            arena = report["main_arena"]
            print(f"  Main arena ${arena['start']:04X}-${arena['end']-1:04X}: "
                  f"{arena['bytes']} bytes; conservative nine-map/160-actor margin "
                  f"{arena['conservative_margin_bytes']} bytes; "
                  f"software stack {arena['stack_bytes']} bytes")
        for error in errors:
            print("check_link: " + error, file=sys.stderr)
        return 1 if errors else 0
    errors = []
    system = (b / "DOOM.SYSTEM").read_bytes()
    render = (b / "RENDER.BIN").read_bytes()
    lc = (b / "LC.BIN").read_bytes()
    game = (b / "GAME.BIN").read_bytes()
    if system[0] not in (0xD8, 0x78, 0xA2, 0x4C):
        errors.append(f"DOOM.SYSTEM starts with ${system[0]:02X}, not code")
    if 0x2000 + len(system) > 0x4000:
        errors.append(f"DOOM.SYSTEM is {len(system)} bytes: past $3FFF")
    if 0x0200 + len(render) > 0x8B80:
        errors.append(f"RENDER.BIN is {len(render)} bytes: reaches the view buffer")
    if len(lc) != 0x4000:
        errors.append(f"LC.BIN is {len(lc)} bytes, not 16384")
    elif lc[0x1000] != 0x4C:
        errors.append("LC.BIN: no JMP at $E000")
    else:
        irq = lc[0x2FFE] | (lc[0x2FFF] << 8)
        if irq < 0xD000:
            errors.append(f"LC.BIN: the IRQ vector is ${irq:04X}")
    if 0x0200 + len(game) > 0xB800:
        errors.append(f"GAME.BIN is {len(game)} bytes: reaches the C stack")
    used = area_usage((b / "doom.map").read_text())
    report = {name: dict(start=start, size=size, used=used[name], free=size - used[name],
                         what=what) for name, (start, size, what) in AREAS.items()}
    report["files"] = {"DOOM.SYSTEM": len(system), "RENDER.BIN": len(render),
                       "LC.BIN": len(lc), "GAME.BIN": len(game)}
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n")
    if not args.quiet:
        for name, (start, size, what) in AREAS.items():
            print(f"  {name:7s} {what:34s} {used[name]:6d} used {size - used[name]:6d} free")
    for error in errors:
        print("check_link: " + error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
