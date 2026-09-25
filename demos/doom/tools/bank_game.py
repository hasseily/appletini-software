#!/usr/bin/env python3
"""Build GAME with real, permanently loaded auxiliary language-card banks.

Generated assembly keeps ordinary data and the shared runtime in main RAM.
Each public banked routine has a stable six-byte main-RAM entry, including
routines whose addresses appear in thinker/action tables. Direct calls inside
one bank bypass that entry. This is a source transformation, not an emulator
instruction window: every output bank really links at $D000-$FFF9.

The output directory contains transformed sources, objects, a linker fragment,
the public-entry table, and a machine-readable inventory. The encompassing
platform build supplies gamebanks.s and the kernel/renderer segments.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
GROUPS = {
    "collision": ("a_map", "a_maputl"),
    "actors": ("a_mobj",),
    "ai": ("a_enemy", "a_sight"),
    "specials": ("a_spec", "a_movers"),
    "control": ("g_game", "a_view", "a_inter"),
    "setup": ("p_setup", "p_spawn"),
    "weapons": ("a_user", "a_debug"),
}
MODULE_GROUP = {m: g for g, modules in GROUPS.items() for m in modules}
STATE_ARRAYS = ("_st_sprite", "_st_frame", "_st_tics", "_st_action", "_st_next",
                "_mi_viewflags")
STATE_USERS = {
    "collision": ("_st_tics",),
    "actors": ("_st_tics", "_st_action", "_st_next"),
    "control": ("_st_sprite", "_st_frame", "_mi_viewflags"),
    "setup": ("_st_tics",),
    "weapons": ("_st_tics", "_st_action", "_st_next"),
}
# These tables are private to code in one bank. In particular a_spec's
# setup tail never reads its runtime switch/action tables directly.
PRIVATE_RODATA = {"a_spec", "a_inter", "a_enemy", "a_view", "a_debug", "g_game"}
IDENT = r"[A-Za-z_][A-Za-z_0-9]*"
LABEL = re.compile(r"^\s*(" + IDENT + r")\s*:")
PROC = re.compile(r"^\s*\.proc\s+(" + IDENT + r")\b")
SEGMENT = re.compile(r'^\s*\.segment\s+"([^\"]+)"')
EXPORT = re.compile(r"^\s*\.export\s+(.+)")
TRANSFER = re.compile(r"^(\s*(?:(?:" + IDENT + r"|@\w+)?\s*:\s*)?"
                      r"(?:jsr|jmp|bra|bcc|bcs|beq|bne|bmi|bpl|bvc|bvs|"
                      r"jcc|jcs|jeq|jne|jmi|jpl|jvc|jvs)\s+)(" + IDENT + r")\b", re.I)


@dataclass
class Line:
    text: str
    segment: str
    group: str | None
    # Physical placement may differ from the required execution context.
    # Main-resident actor code still needs bank 97's ZP, stack and helpers.
    physical_segment: str | None = None


@dataclass
class Entry:
    module: str
    symbol: str
    public: str
    private: str
    group: str


def replace_symbol(text: str, old: str, new: str) -> str:
    return re.sub(r"(?<![A-Za-z_0-9@])" + re.escape(old) + r"(?![A-Za-z_0-9])", new, text)


def segments(module: str, source: str) -> list[Line]:
    """Annotate segment ownership, extracting the measured shared helpers."""
    out = []
    segment = "CODE"
    helper = False
    sector_change = False
    static_main = False
    for raw in source.splitlines():
        text = raw.split(";", 1)[0]
        m = SEGMENT.match(text)
        if m:
            segment = m[1]
        elif re.match(r"^\s*(MONCODE|SPECCODE)\s*$", text):
            segment = "CODE"
            raw = '.segment "CODE"'
        lab = LABEL.match(text) or PROC.match(text)
        # LABEL also matches the instruction in "bne :+"; anonymous branch
        # operands do not introduce a named scope boundary.
        if module == "a_mobj" and lab and text[lab.end():lab.end() + 1] not in ("+", "-"):
            if lab[1] == "_P_RunStatics":
                static_main = True
            elif static_main:
                if lab[1] != "may_wake":
                    raise ValueError("unexpected label inside main-resident P_RunStatics")
                static_main = False
        if module == "a_map" and lab and lab[1] == "outside_sector":
            sector_change = True
        if module == "a_maputl" and lab:
            if lab[1] in ("call_ax", "_P_NewValidcount"):
                helper = True
            elif lab[1] in ("_P_PointOnLineSide", "pit_add_line"):
                helper = False
        group = MODULE_GROUP.get(module)
        if sector_change:
            group = "setup"
        if segment == "GOVL" and module != "fixed":
            group = "setup"
        bankable = segment in ("CODE", "MCODE", "MCODE2", "GOVL")
        bankable |= segment == "RODATA" and module in PRIVATE_RODATA
        if not bankable or helper:
            group = None
        if static_main and (segment != "CODE" or group != "actors"):
            raise ValueError("main-resident P_RunStatics must keep its actors context")
        out.append(Line(raw, segment, group, "CODE" if static_main else None))
    if static_main:
        raise ValueError("main-resident P_RunStatics is missing its may_wake boundary")
    return out


def exports(source: str) -> set[str]:
    names = set()
    for raw in source.splitlines():
        m = EXPORT.match(raw.split(";", 1)[0])
        if m:
            names.update(re.findall(IDENT, m[1].split(":", 1)[0]))
    return names


def entries(module: str, lines: list[Line], public: set[str]) -> dict[str, Entry]:
    """Public routines and private callbacks both need invariant addresses."""
    definitions = {}
    in_proc = False
    for line in lines:
        proc = PROC.match(line.text)
        m = proc or (None if in_proc else LABEL.match(line.text))
        if proc:
            in_proc = True
        elif re.match(r"\s*\.endproc\b", line.text):
            in_proc = False
        if m and line.group is not None and line.segment in ("CODE", "MCODE", "MCODE2", "GOVL"):
            definitions[m[1]] = line.group
    taken = set()
    for line in lines:
        text = line.text.split(";", 1)[0]
        text = LABEL.sub("", text)
        # Function pointers passed in A/X or emitted into an address table.
        if re.search(r"#\s*[<>^]|\.(?:word|addr)\b", text):
            taken.update(re.findall(IDENT, text))
        transfer = TRANSFER.match(text)
        if transfer and transfer[2] in definitions and definitions[transfer[2]] != line.group:
            taken.add(transfer[2])
    result = {}
    for name, group in definitions.items():
        if name in public or name in taken:
            result[name] = Entry(module, name,
                                 name if name in public else f"gbptr_{module}_{name}",
                                 f"gbbody_{module}_{name}", group)
    return result


def extract_states(source: str) -> tuple[str, dict[str, str]]:
    """Remove shared lookup arrays; emit copies only in banks that read them."""
    lines = source.splitlines()
    array = None
    bodies: dict[str, list[str]] = {s: [] for s in STATE_ARRAYS}
    kept = []
    for line in lines:
        m = LABEL.match(line)
        if m:
            array = m[1] if m[1] in STATE_ARRAYS else None
        elif SEGMENT.match(line):
            array = None
        if array is not None:
            bodies[array].append(line)
        else:
            m = EXPORT.match(line)
            if not (m and m[1].strip() in STATE_ARRAYS):
                kept.append(line)
    if any(not lines for lines in bodies.values()):
        raise ValueError("info.s does not define the expected bank-local lookup arrays")
    return "\n".join(kept) + "\n", {s: "\n".join(v) + "\n" for s, v in bodies.items()}


def transform(module: str, lines: list[Line], own: dict[str, Entry],
              global_entries: dict[str, Entry], banks: dict[str, int],
              variants: dict[str, dict[str, Entry]]) -> str:
    result = ["; Generated by tools/bank_game.py; edit the original game sources."]
    extra_imports = set()
    extra_exports = set()
    current = None
    default_group = MODULE_GROUP.get(module)
    lookup = dict(global_entries)
    lookup.update(own)
    for line in lines:
        text = line.text
        label = LABEL.match(text.split(";", 1)[0]) or PROC.match(text.split(";", 1)[0])
        placed_entry = own.get(label[1]) if label and line.physical_segment else None
        placed_name = None
        if placed_entry:
            # Keep the public descriptor's target in its original code bank.
            # This tiny wrapper preserves the actor context and existing gate
            # validation; the hot body and its cheap-local branches stay main.
            wrapper_segment = f"GB{banks[placed_entry.group]}"
            if current != wrapper_segment:
                result.append(f'.segment "{wrapper_segment}"')
            placed_name = f"gbmain_{module}_{placed_entry.symbol}"
            result += [f"{placed_entry.private}:", f"    jmp {placed_name}"]
            current = wrapper_segment
        actual = line.physical_segment or (f"GB{banks[line.group]}" if line.group else line.segment)
        if actual in ("MCODE", "MCODE2"):
            actual = "CODE"
        if current != actual:
            suffix = ": zeropage" if actual in ("KZP", "GZP", "ZEROPAGE") else ""
            result.append(f'.segment "{actual}"{suffix}')
            current = actual
        # Original switches have already been represented above.
        if SEGMENT.match(text):
            continue
        code, sep, comment = text.partition(";")
        m = LABEL.match(code) or PROC.match(code)
        definition = m[1] if m else None
        export = EXPORT.match(code)
        if re.match(r"\s*\.dbg\s+func\b", code):
            for name, entry in own.items():
                code = code.replace('"' + name + '"', '"' + entry.private + '"')
        elif export:
            for name, entry in own.items():
                if name in exports(code):
                    code = replace_symbol(code, name, entry.private)
                    extra_imports.add(entry.public)
        elif not code.lstrip().startswith((".import", ".dbg", ".export")):
            transfer = TRANSFER.match(code)
            # Replace every reference to a thunked local label. Direct calls
            # inside its bank bind the body; all address values name the stub.
            for name, entry in own.items():
                replacement = entry.public
                if definition == name or (transfer and transfer[2] == name
                                          and line.group == entry.group):
                    replacement = placed_name if definition == name and placed_name else entry.private
                    extra_exports.add(entry.private)
                if re.search(r"(?<![A-Za-z_0-9@])" + re.escape(name) + r"(?![A-Za-z_0-9])", code):
                    code = replace_symbol(code, name, replacement)
                    if replacement == entry.public:
                        extra_imports.add(entry.public)
            if transfer and transfer[2] not in own:
                entry = variants.get(transfer[2], {}).get(line.group)
                if entry is None:
                    entry = global_entries.get(transfer[2])
                if entry and line.group == entry.group:
                    code = replace_symbol(code, entry.symbol, entry.private)
                    extra_imports.add(entry.private)
        # State data is addressed only while its owning bank is selected.
        for state in STATE_ARRAYS:
            if re.search(r"\b" + state + r"\b", code):
                # A module may have a cold tail assigned to a different bank.
                state_group = line.group or default_group
                if code.lstrip().startswith(".import"):
                    # Emit an import for each bank that this module's code uses.
                    imports = {f"gb{banks[l.group]}{state}" for l in lines
                               if l.group and re.search(r"\b" + state + r"\b", l.text)
                               and not l.text.lstrip().startswith((".import", ".dbg"))}
                    if imports:
                        code = replace_symbol(code, state, ", ".join(sorted(imports)))
                        continue
                if state_group not in STATE_USERS or state not in STATE_USERS[state_group]:
                    raise ValueError(f"{module}: unassigned state-array reference {state}")
                code = replace_symbol(code, state, f"gb{banks[state_group]}{state}")
        result.append(code + (sep + comment if sep else ""))
    defined = {e.private for e in own.values()}
    # Explicit imports are harmless when the original module already imports
    # that name; ca65 permits repeated declarations of the same import.
    header = []
    if extra_imports - defined:
        header.append(".import " + ", ".join(sorted(extra_imports - defined)))
    if extra_exports:
        header.append(".export " + ", ".join(sorted(extra_exports)))
    return "\n".join(header + result) + "\n"


def clone_level_accessors(sources: dict[str, str], banks: dict[str, int]) -> set[str]:
    """Duplicate accessor CODE; all caches and scratch variables stay shared.

    The module's header contains its conditional constants. Its two BSS
    blocks have no nesting directives; preserve every conditional delimiter
    in both views so DD_MAPDIR remains balanced.
    """
    original = sources["a_levdata"]
    lines = segments("a_levdata", original)
    first = next(i for i, line in enumerate(lines) if SEGMENT.match(line.text))
    header = lines[:first]
    body = lines[first:]
    data_names = {m[1] for line in body if line.segment == "BSS"
                  if (m := LABEL.match(line.text))}
    exported = exports(original)
    # Private cache names become external only so the code copies can share
    # them. Namespace those new exports: the renderer has its own nodebuf,
    # linebuf, and other unrelated scratch symbols in the encompassing link.
    for name in sorted(data_names - exported, key=len, reverse=True):
        original = replace_symbol(original, name, f"gbshared_levdata_{name}")
    lines = segments("a_levdata", original)
    first = next(i for i, line in enumerate(lines) if SEGMENT.match(line.text))
    header, body = lines[:first], lines[first:]
    data_names = {m[1] for line in body if line.segment == "BSS"
                  if (m := LABEL.match(line.text))}
    data_exports = exported & data_names
    code_exports = exported - data_exports

    def view(code: bool) -> str:
        out = []
        allowed = code_exports if code else data_names
        for line in header:
            m = EXPORT.match(line.text)
            if m:
                names = sorted(exports(line.text) & allowed)
                if names:
                    out.append(".export " + ", ".join(names))
            else:
                out.append(line.text)
        out.append((".import " if code else ".export ") + ", ".join(sorted(data_names)))
        for line in body:
            conditional = re.match(r"\s*\.(?:if\w*|else|endif)\b", line.text)
            if conditional or (line.segment == "CODE") == code:
                out.append(line.text)
        return "\n".join(out) + "\n"

    sources["a_levdata"] = view(False)
    clones = set()
    for group, bank in banks.items():
        name = f"a_levdata_g{bank}"
        sources[name] = view(True)
        MODULE_GROUP[name] = group
        clones.add(name)
    return clones


def actual_references(source: str) -> set[str]:
    """References that can require a symbol, excluding import/debug metadata."""
    references = set()
    for line in source.splitlines():
        text = line.split(";", 1)[0]
        if re.match(r"\s*\.(?:import\w*|export\w*|dbg)\b", text):
            continue
        references.update(re.findall(IDENT, text))
    return references


def prune_imports(source: str) -> str:
    used = actual_references(source)
    out = []
    for line in source.splitlines():
        if re.match(r"\s*\.dbg\s+sym\b", line):
            # cc65 records even unused imported C declarations here. After
            # binding direct calls to private bank bodies those old imports
            # need not exist; retain line/function debug information instead.
            continue
        match = re.match(r"\s*\.import\s+(.+)", line)
        if match:
            names = [name.strip() for name in match[1].split(",") if name.strip() in used]
            if names:
                out.append(".import " + ", ".join(names))
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def prepare(args) -> dict:
    video_hz = getattr(args, "video_hz", 60)
    if video_hz not in (50, 60):
        raise ValueError("video_hz must be 50 or 60")
    src, data, out = args.source.resolve(), args.data.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    gen = out / "generated"
    gen.mkdir(exist_ok=True)
    staging = {g: args.first_bank + i for i, g in enumerate(GROUPS)}
    banks = dict(staging)
    # Base auxiliary LC has fast code, zero page and hardware stack. Stage
    # its image in extended RAM until ProDOS and the renderer load are done.
    control = getattr(args, "control_bank", 0)
    if control not in (0, staging["control"]):
        raise ValueError("control bank must be 0 or its ordinary extended-bank ID")
    banks["control"] = control
    constants = (data / "doomdata.inc").read_text()
    last = int(re.search(r"DD_LAST_BANK\s*=\s*(\d+)", constants)[1])
    if args.first_bank <= last or max(staging.values()) >= 122:
        raise ValueError(f"code staging banks {min(staging.values())}..{max(staging.values())} "
                         f"overlap data (through {last}) or platform banks (122..127)")
    sources = {}
    for path in sorted(src.glob("*.c")):
        dest = gen / (path.stem + ".raw.s")
        subprocess.run([args.cc65, "-t", "none", "--cpu", "65c02", "--standard", "c99",
                        "-Oirs", "-g", "-D", "BANKED_GAME", "-I", str(src), "-I", str(data),
                        "-o", str(dest), str(path)], check=True)
        sources[path.stem] = dest.read_text()
    for path in sorted(src.glob("*.s")):
        if path.stem in sources:
            raise ValueError(f"duplicate C/assembly module {path.stem}")
        sources[path.stem] = path.read_text()
    sources["info"], state_bodies = extract_states(sources["info"])
    clones = clone_level_accessors(sources, banks)
    annotated = {m: segments(m, text) for m, text in sources.items()}
    per_module = {m: entries(m, annotated[m], exports(text)) for m, text in sources.items()}
    public_entries = {}
    variants: dict[str, dict[str, Entry]] = {}
    for module, candidates in per_module.items():
        for name, entry in candidates.items():
            if name not in exports(sources[module]):
                continue
            if module in clones:
                variants.setdefault(name, {})[entry.group] = entry
                if name in public_entries:
                    entry.public = f"gbalias_{module}_{name}"
                else:
                    public_entries[name] = entry
            else:
                public_entries[name] = entry
    all_entries = [e for es in per_module.values() for e in es.values()]
    generated = {module: prune_imports(transform(module, lines, per_module[module],
                                                 public_entries, banks, variants))
                 for module, lines in annotated.items()}
    referenced = {"_game_init", "_game_tic", "_game_frame", "_debug_readout"}
    for source in generated.values():
        referenced.update(actual_references(source))
    all_entries = [entry for entry in all_entries if entry.public in referenced]
    objects = []
    for module, source in generated.items():
        path = gen / (module + ".s")
        path.write_text(source)
        obj = out / (module + ".o")
        subprocess.run([args.ca65, "--cpu", "65c02", "-g", "-D", "BANKED_GAME",
                        "-D", f"VIDEO_HZ={video_hz}",
                        "-I", str(src), "-I", str(PROJECT / "src/kernel"),
                        "-I", str(data), "-o", str(obj), str(path)], check=True)
        objects.append(str(obj))
    stubs = ['.setcpu "65C02"', '.import gb_call', '.segment "GBSTUBS"']
    for entry in sorted(all_entries, key=lambda e: e.public):
        stubs += [f".import {entry.private}", f".export {entry.public}", f"{entry.public}:",
                  "    jsr gb_call", f"    .byte {banks[entry.group]}",
                  f"    .word {entry.private}"]
    for group, names in STATE_USERS.items():
        stubs.append(f'.segment "GB{banks[group]}"')
        for name in names:
            symbol = f"gb{banks[group]}{name}"
            stubs += [f".export {symbol}", replace_symbol(state_bodies[name], name, symbol)]
    stubs += [".import gb_irq, gb_nmi"]
    for bank in banks.values():
        stubs += [f'.segment "GBV{bank}"', "    .word gb_nmi, 0, gb_irq"]
    path = gen / "bank_entries.s"
    path.write_text("\n".join(stubs) + "\n")
    obj = out / "bank_entries.o"
    subprocess.run([args.ca65, "--cpu", "65c02", "-g", "-D", f"VIDEO_HZ={video_hz}",
                    "-o", str(obj), str(path)], check=True)
    objects.append(str(obj))
    inventory = {"format": 1, "banks": banks, "first_bank": args.first_bank,
                 "default_video_hz": video_hz,
                 "code_staging": {str(banks[g]): staging[g] for g in GROUPS},
                 "code_start": 0xD000, "code_capacity": 0x2FFA,
                 "objects": objects, "entries": [vars(e) for e in all_entries],
                 "state_arrays": STATE_USERS,
                 "lc_packet": {"bank": banks["control"], "segment": "GVIEW", "bytes": 2600}}
    (out / "banks.json").write_text(json.dumps(inventory, indent=2) + "\n")
    (out / "objects.txt").write_text("\n".join(objects) + "\n")
    memory = []
    bank_segments = []
    for bank in banks.values():
        memory += [f'    GB{bank}: file = "%OGBANK{bank}.BIN", start = $D000, '
                   'size = $2FFA, fill = yes, type = rw;',
                   f'    GBV{bank}: file = "%OGBANK{bank}.BIN", start = $FFFA, '
                   'size = $0006, fill = yes, type = rw;']
        bank_segments += [f'    GB{bank}: load = GB{bank}, type = rw, define = yes;',
                          f'    GBV{bank}: load = GBV{bank}, type = ro;']
    bank_segments.append(f'    GVIEW: load = GB{banks["control"]}, type = bss, define = yes;')
    (out / "banks-memory.cfg").write_text("\n".join(memory) + "\n")
    (out / "banks-segments.cfg").write_text("\n".join(bank_segments) + "\n")
    print(f"Prepared {len(objects)} objects, {len(all_entries)} bank entry stubs, "
          f"banks {','.join(map(str, banks.values()))}")
    return inventory


def standalone(args, inventory):
    """Real-memory game link with trap kernel entries for execution tests."""
    out = args.out.resolve()
    kernel = (PROJECT / "tests/host/flatkern.s").read_text()
    for old, new in (("KBSS", "GINPUT"), ("KJT", "CODE"), ("KCODE", "CODE")):
        kernel = kernel.replace(f'.segment "{old}"', f'.segment "{new}"')
    kernel += '\n.export gb_irq_service\ngb_irq_service: rts\n'
    path = out / "generated/bank_test_kernel.s"
    path.write_text(kernel)
    objects = list(inventory["objects"])
    for source in (path, PROJECT / "src/kernel/gamebanks.s"):
        obj = out / (source.stem + ".o")
        subprocess.run([args.ca65, "--cpu", "65c02", "-g", "-D", "BANKED_GAME",
                        "-D", f"VIDEO_HZ={getattr(args, 'video_hz', 60)}",
                        "-I", str(PROJECT / "src/kernel"), "-I", str(args.data.resolve()),
                        "-o", str(obj), str(source)], check=True)
        objects.append(str(obj))
    memory = (out / "banks-memory.cfg").read_text()
    bank_segments = (out / "banks-segments.cfg").read_text()
    config = '''# Generated standalone banked-GAME test link: genuine Apple II addresses.
SYMBOLS {
    __STACKSIZE__: type = weak, value = $0800;
    __STACKSTART__: type = weak, value = $C000;
}
MEMORY {
    KZP: file = "", start = $0002, size = $003E, type = rw;
    GZP: file = "", start = $0040, size = $0008, type = rw;
    CZP: file = "", start = $00E0, size = $0020, type = rw;
    GAME: file = "%OGAME.BIN", start = $0200, size = $B180, type = rw, define = yes;
    ISCRATCH: file = "", start = $B380, size = $0480, type = rw, define = yes;
    TABLES: file = "%OGAME.TABLES", start = $0200, size = $BDF0, type = rw;
    INFO: file = "%OGAME.INFO", start = $6000, size = $1000, type = ro;
''' + memory + '''}
SEGMENTS {
    KZP: load = KZP, type = zp;
    GZP: load = GZP, type = zp;
    ZEROPAGE: load = CZP, type = zp;
    STARTUP: load = GAME, type = ro;
    LOWCODE: load = GAME, type = ro, optional = yes;
    ONCE: load = GAME, type = ro, optional = yes;
    CODE: load = GAME, type = rw;
    GBSTUBS: load = GAME, type = ro;
    GBANKCODE: load = GAME, type = rw;
    RODATA: load = GAME, type = ro;
    DATA: load = GAME, type = rw, define = yes;
    GINPUT: load = GAME, type = bss;
    GBANKBSS: load = GAME, type = bss, define = yes;
    GINTERCEPTS: load = ISCRATCH, type = bss, define = yes;
    INIT: load = GAME, type = bss, optional = yes;
    BSS: load = GAME, type = bss, define = yes;
    GFAR: load = TABLES, type = ro, define = yes;
    GOVL: load = TABLES, type = ro, define = yes, optional = yes;
    GINFO: load = INFO, type = ro, optional = yes;
''' + bank_segments + '''}
FEATURES {
    CONDES: type = constructor, label = __CONSTRUCTOR_TABLE__, count = __CONSTRUCTOR_COUNT__, segment = ONCE;
    CONDES: type = destructor, label = __DESTRUCTOR_TABLE__, count = __DESTRUCTOR_COUNT__, segment = RODATA;
    CONDES: type = interruptor, label = __INTERRUPTOR_TABLE__, count = __INTERRUPTOR_COUNT__, segment = RODATA, import = __CALLIRQ__;
}
'''
    cfg = out / "banked.cfg"
    cfg.write_text(config)
    subprocess.run([args.ld65, "-C", str(cfg), "-m", str(out / "game.map"),
                    "-Ln", str(out / "game.lbl"), "--dbgfile", str(out / "game.dbg"),
                    "-o", str(out) + "/", *objects, "none.lib"], check=True)
    report = budget(out)
    (out / "budget.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def budget(out: Path) -> dict:
    table = {}
    body = (out / "game.map").read_text().split("Segment list:\n", 1)[1]
    for line in body.splitlines()[3:]:
        match = re.match(r"(\w+)\s+([0-9A-F]{6})\s+([0-9A-F]{6})\s+([0-9A-F]{6})", line)
        if match:
            name, start, end, size = match.groups()
            table[name] = {"start": int(start, 16), "end": int(end, 16) + 1,
                           "bytes": int(size, 16)}
    near_end = table["BSS"]["end"]
    if table.get("GVIEW", {}).get("bytes") != 2600:
        raise ValueError("the control LC bank must contain the full 2600-byte render packet")
    scratch = table.get("GINTERCEPTS", {})
    if scratch != {"start": 0xB380, "end": 0xB800, "bytes": 1152}:
        raise ValueError("intercept/view scratch must occupy main $B380-$B7FF")
    return {"segments": table, "main_used_bytes": near_end - 0x200 + scratch["bytes"],
            "main_arena_bytes": scratch["start"] - near_end, "software_stack_bytes": 2048,
            "main_scratch_bytes": scratch["bytes"],
            "lc_packet_bytes": table["GVIEW"]["bytes"],
            "actor_pool_bytes": 160 * 64,
            "level_bytes_after_160_actors": scratch["start"] - near_end - 160 * 64}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT / "src/game")
    parser.add_argument("--data", type=Path, default=PROJECT / "build/data")
    parser.add_argument("--out", type=Path, default=PROJECT / "build/banked-game")
    parser.add_argument("--first-bank", type=int, default=96)
    parser.add_argument("--video-hz", type=int, choices=(50, 60), default=60,
                        help="initial video rate for the tic scheduler and debug readout")
    parser.add_argument("--control-bank", type=int, default=0,
                        help="control LC bank: 0 (base auxiliary) or first-bank+4 for comparison")
    parser.add_argument("--cc65", default="cc65")
    parser.add_argument("--ca65", default="ca65")
    parser.add_argument("--ld65", default="ld65")
    parser.add_argument("--standalone", action="store_true",
                        help="link GAME and all LC banks with the test trap kernel")
    args = parser.parse_args()
    inventory = prepare(args)
    if args.standalone:
        standalone(args, inventory)


if __name__ == "__main__":
    main()
