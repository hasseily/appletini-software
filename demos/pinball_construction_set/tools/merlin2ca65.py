#!/usr/bin/env python3
"""Convert the upstream Merlin sources of Pinball Construction Set to ca65.

Two layouts:

* `--layout baseline`: every module becomes a standalone file assembled at
  its original ORG with the original hard-coded EQU chains, so the output
  is byte for byte the original program (tests/test_convert.py checks the
  sizes and checksums). Used to validate the converter, and by the port
  layout to learn the value of every symbol.

* `--layout port`: the modules are linked together with the port's own
  code. An EQU whose value is the address of a label in another module
  (`SETMODE EQU HI+$10F`, `PLAYSTART EQU $8854`, ...) becomes an `.import`
  of `MODULE_LABEL`; the fixed RAM tables (`PBTBLO EQU $400`, `LOGIC EQU
  $4000`, ...) become imports of symbols the port defines; label ranges
  listed in drops.json are removed (the port re-implements them) and lines
  listed in patches.json are rewritten. Labels of dropped ranges that the
  remaining code still uses are imported by their plain name from the
  port. Every module exports what the others import, plus exports.json.

Merlin facts this relies on (all verified against the sources): `DA <X`
and `DA >X` emit one byte; `#<X+1` applies to the whole expression (so it
is parenthesised); `LDA 0,Y` assembles as absolute,Y; the only directives
are LST, ORG, OBJ, EQU, HEX, DA, DS.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

MODULES = {
    'CDRAW': 'source_disc1/CDRAW.S', 'EDIT': 'source_disc1/EDIT.S',
    'PPAK': 'source_disc1/PPAK.S', 'RUN2': 'source_disc1/RUN2.S',
    'BOOT2': 'source_disc2/BOOT2.S', 'DISK': 'source_disc2/DISK.S',
    'RUN': 'source_disc2/RUN.S', 'SWAP': 'source_disc2/SWAP.S',
    'WIRE': 'source_disc2/WIRE.S',
}
ORG_FIX = {'CDRAW': 0x1780}     # `ORG HI+$C0`: HI = $16C0

# Names a module uses for another module's labels.
ALIAS = {
    'D7': 'DIV7', 'M7': 'MOD7', 'DRAWB': 'DRAWBITS', 'FRAMER': 'FRAMERECT',
    'DRAWR': 'DRAWRECT', 'INR': 'INRECT', 'GETB': 'GETBUTNS', 'GETBUTN': 'GETBUTNS',
    'INITC': 'INITCRSR', 'XDRAWC': 'XDRAWCRSR', 'UPDATEC': 'UPDATECRSR',
    'DOCX': 'DOCRSRX', 'GETCX': 'GETCURSORX', 'DOCY': 'DOCRSRY', 'CINR': 'CRSRINRECT',
    'CHAR': 'CHARBITS', 'GETNOBJ': 'GETNEXTOBJ', 'PLAYSTART': 'PLAY',
    'LFLIP2': 'LFLIPPER2', 'RFLIP2': 'RFLIPPER2', 'SPIN': 'SPIN1', 'MGNT': 'MAG1',
    'INITBALL': 'INITB2', 'GAMESTART': 'MAIN', 'PLAYGAME': 'DISKPLAY',
}
# RAM tables and buffers at fixed addresses in the original; the port
# defines them (BSS) and the modules import them by name.
PORT_DATA = {
    'COLORBAR', 'NVRTX', 'NDXCOEFF', 'NDXFRACT', 'NDXCODE', 'DXBUFR',
    'PBTBLO', 'PBTBHI', 'VLO', 'VHI', 'RCN', 'TIME', 'VECTLO', 'VECTHI', 'RUNCHN',
    'LOGIC', 'WSET', 'PBDATA', 'PBDX', 'PBBASE', 'BITMAPS',
    'P1STATE', 'P2STATE', 'P3STATE', 'P4STATE', 'SLEEPCODE', 'SLEEPLO', 'SLEEPHI', 'SLEEPERS',
    'CHARBUF', 'LINELEN', 'VALIDBUF',
    'SHFRSLT', 'SHFOUT', 'DIV7', 'MOD7', 'LO', 'HI',
}
# In the port layout these imports go to the port's wrapper instead of the
# provider module (the wrapper marks rectangles dirty, then jumps on).
REDIRECT = {'DRAWOBJ': 'PORT_DRAWOBJ', 'REMOVEPOLY': 'PORT_REMOVEPOLY',
            'DRAWDISPLAY': 'PORT_DRAWDISPLAY',
    'PLAY': 'PORT_PLAY',            # EDIT's PLAYSTART: play_begin/RUN_PLAY/play_end
}
MNEMONICS = set('''ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV CMP CPX CPY
DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA PHA PHP PLA PLP ROL ROR RTI RTS SBC
SEC SED SEI STA STX STY TAX TAY TSX TXA TXS TYA STZ PHX PHY PLX PLY BRA TRB TSB'''.split())
IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def split_fields(line):
    """Merlin line -> (label, op, operand, comment)."""
    comment = ''
    if ';' in line:
        line, comment = line.split(';', 1)
        comment = comment.rstrip()
    if line[:1] in (' ', '\t'):
        label = ''
        rest = line.strip()
    else:
        parts = line.split(None, 1)
        label = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ''
    if not rest:
        return label, '', '', comment
    parts = rest.split(None, 1)
    return label, parts[0].upper(), (parts[1].strip() if len(parts) > 1 else ''), comment


def fix_expr(op):
    if op.startswith('#<') or op.startswith('#>'):
        return op[:2] + '(' + op[2:] + ')'
    if op and op[0] in '<>':
        return op[0] + '(' + op[1:] + ')'
    return op


def identifiers(operand):
    """Symbol names in an operand (registers after a comma excluded)."""
    text = re.sub(r',\s*[XY]\b', '', operand)
    text = re.sub(r'\$[0-9A-F]+', '', text)
    return set(IDENT.findall(text))


def apply_drops(lines, drops):
    """Yield (lineno, line) for the lines outside dropped label ranges."""
    dropping = None
    for lineno, line in enumerate(lines, 1):
        if line and line[0] not in '* \t':
            label = split_fields(line)[0]
            if dropping:
                if label == dropping:
                    dropping = None
                else:
                    continue
            if label in drops:
                dropping = drops[label] if drops[label] != '__END__' else '\0'
                yield lineno, None
                continue
        elif dropping:
            continue
        yield lineno, line


def defined_labels(lines, drops=None):
    """Labels a module defines with an address: plain labels and `EQU *...`."""
    out = set()
    for _, line in apply_drops(lines, drops or {}):
        if not line or line[0] in '* \t':
            continue
        label, op, operand, _ = split_fields(line)
        if op != 'EQU' or operand.startswith('*'):
            out.add(label)
    return out


def convert_lines(module, src, layout, drops, patches):
    """First pass: emit ca65 text items.

    Returns (org, items, used, local) where items are strings or
    (text, label, operand) tuples for EQUs, `used` the identifiers referenced
    by code and data, `local` the labels defined by code and data.
    """
    items = []
    used = set()
    local = set()
    org = None
    skip_until = 0
    for lineno, line in apply_drops(src, drops):
        if line is None:
            items.append('; %s:%d dropped, replaced by the port' % (MODULES[module], lineno))
            continue
        if lineno <= skip_until:
            continue
        if lineno in patches:
            end, repl = patches[lineno]
            skip_until = end
            lines = repl if isinstance(repl, list) else [repl]
        else:
            lines = [line]
        for line in lines:
            if line == '':
                continue
            if line[0] == '*':
                items.append(';' + line[1:])
                continue
            label, op, operand, comment = split_fields(line)
            cmt = ('  ;' + comment) if comment else ''
            if op in ('LST', 'OBJ'):
                continue
            if op == 'ORG':
                org = ORG_FIX.get(module, int(operand.replace('$', ''), 16) if operand.startswith('$') else None)
                if layout == 'baseline':
                    items.append('.org $%04X' % org)
                continue
            if op == 'EQU':
                items.append(('%s = %s%s' % (label, fix_expr(operand), cmt), label, operand))
                continue
            lab = (label + ':') if label else ''
            if label:
                local.add(label)
            if op == 'HEX':
                h = operand.replace(',', '')
                items.append('%s .byte %s%s' % (lab, ','.join('$' + h[i:i + 2] for i in range(0, len(h), 2)), cmt))
            elif op == 'DA':
                if operand[:1] in '<>':
                    items.append('%s .byte %s%s' % (lab, fix_expr(operand), cmt))
                else:
                    items.append('%s .word %s%s' % (lab, operand, cmt))
                used |= identifiers(operand)
            elif op == 'DS':
                items.append('%s .res %s%s' % (lab, operand, cmt))
            elif op == '':
                items.append('%s%s' % (lab, cmt))
            elif op in MNEMONICS:
                items.append('%s %s %s%s' % (lab, op.lower(), fix_expr(operand), cmt))
                used |= identifiers(operand)
            elif op.startswith('.'):
                items.append('%s %s %s%s' % (lab, op.lower(), operand, cmt))
                used |= identifiers(operand)
            else:
                raise ValueError('%s:%d unknown op %s' % (module, lineno, op))
    return org, items, used, local


def baseline_symbols(upstream, workdir):
    """Assemble the baseline and return {module: (org, end, {label: value})}."""
    tools = {t: os.environ.get(t.upper(), t) for t in ('ca65', 'ld65')}
    out = {}
    for module, path in MODULES.items():
        src = (Path(upstream) / path).read_text().splitlines()
        org, items, _, local = convert_lines(module, src, 'baseline', {}, {})
        names = sorted(local | {i[1] for i in items if isinstance(i, tuple)})
        text = '\n'.join(['.setcpu "65C02"'] + [i[0] if isinstance(i, tuple) else i for i in items]
                         + ['.export %s' % n for n in names]) + '\n'
        s = Path(workdir) / (module + '.s')
        s.write_text(text)
        o = s.with_suffix('.o')
        cfg = s.with_suffix('.cfg')
        cfg.write_text('MEMORY { M: start=$%04X, size=$%04X, file=%%O; }\nSEGMENTS { CODE: load=M, type=rw; }\n'
                       % (org, 0x10000 - org))
        binf = s.with_suffix('.bin')
        lbl = s.with_suffix('.lbl')
        subprocess.run([tools['ca65'], '-g', '-o', str(o), str(s)], check=True)
        subprocess.run([tools['ld65'], '-C', str(cfg), '-Ln', str(lbl), '-o', str(binf), str(o)], check=True)
        labels = {}
        for line in lbl.read_text().splitlines():
            p = line.split()
            if len(p) == 3 and p[0] == 'al':
                labels[p[2].lstrip('.')] = int(p[1], 16)
        out[module] = (org, org + binf.stat().st_size, labels)
    return out


class Converter:
    def __init__(self, upstream, layout, drops=None, patches=None, exports=None, symbols=None):
        self.upstream = Path(upstream)
        self.layout = layout
        self.drops = drops or {}          # (module, first) -> end
        self.patches = patches or {}      # (module, line no) -> (end line, [lines])
        self.exports = exports or {}      # module -> [labels]
        self.sources = {m: (self.upstream / p).read_text().splitlines() for m, p in MODULES.items()}
        self.labels = {}
        for m, src in self.sources.items():
            self.labels[m] = defined_labels(src, self.module_drops(m))
        self.symbols = symbols            # baseline: module -> (org, end, {label: value})
        self.imports_needed = {}          # provider module -> {label}

    def module_drops(self, module):
        return {first: end for (m, first), end in self.drops.items() if m == module}

    def module_patches(self, module):
        return {ln: repl for (m, ln), repl in self.patches.items() if m == module}

    def find_provider(self, module, name, value):
        """(provider, label) for an address in another module, or None.

        RUN and RUN2 overlap in memory (RUN2 overlays RUN's tail), so a
        label of the expected name wins over any label with the value, and
        RUN is searched before RUN2.
        """
        target = ALIAS.get(name, name)
        order = ['CDRAW', 'PPAK', 'RUN', 'RUN2', 'EDIT', 'WIRE', 'SWAP', 'DISK', 'BOOT2']
        inside = []
        for m in order:
            if m == module or m not in self.symbols:
                continue
            org, end, labels = self.symbols[m]
            if not org <= value < end:
                continue
            inside.append(m)
            if target in labels and labels[target] == value and target in self.labels[m]:
                return m, target
        for m in inside:
            labels = self.symbols[m][2]
            for label, v in labels.items():
                if v == value and label in self.labels[m]:
                    return m, label
        if inside:
            return inside[0], None      # inside a module but no surviving label
        return None

    def convert(self, module):
        src = self.sources[module]
        drops = self.module_drops(module)
        patches = self.module_patches(module)
        org, items, used, local = convert_lines(module, src, self.layout, drops, patches)
        out = ['; Generated by tools/merlin2ca65.py from %s. Do not edit.' % MODULES[module],
               '.setcpu "65C02"', '']
        if self.layout == 'baseline':
            out.extend(i[0] if isinstance(i, tuple) else i for i in items)
            return org, '\n'.join(out) + '\n', local

        out.append('.segment "CODE"')
        values = self.symbols[module][2]
        equs = {i[1]: i for i in items if isinstance(i, tuple)}
        imports = {}
        kept = set()                    # EQUs kept as local definitions

        def resolve(label):
            """Decide how an EQU label used by the code is provided."""
            operand = equs[label][2]
            if operand.startswith('*'):
                kept.add(label)
                return []
            target = ALIAS.get(label, label)
            if target in PORT_DATA or label in PORT_DATA:
                imports[label] = target
                return []
            if target in REDIRECT:
                imports[label] = REDIRECT[target]
                return []
            found = self.find_provider(module, label, values[label]) if label in values else None
            if found and found[1] is not None:
                provider, target = found
                imports[label] = '%s_%s' % (provider, target)
                self.imports_needed.setdefault(provider, set()).add(target)
                return []
            if found and found[1] is None:
                # inside another module with no surviving label: a dropped
                # routine the port provides under this name
                imports[label] = target
                return []
            kept.add(label)             # constants, ZP, I/O, local chains
            return identifiers(operand)

        pending, seen = set(used), set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            if name in equs:
                pending |= set(resolve(name))
        used = seen
        emitted = []
        for item in items:
            if not isinstance(item, tuple):
                emitted.append(item)
                continue
            text, label, operand = item
            if label in kept or (operand.startswith('*') and label in used):
                emitted.append(text)
                local.add(label)
        for name in sorted(used):
            if name in local or name in imports:
                continue
            if name in self.labels[module]:
                continue                    # defined later by code or data
            imports[name] = name            # dropped here, provided by the port
        for name in sorted(imports):
            sym = imports[name]
            if sym == name:
                out.append('.import %s' % name)
            else:
                out.append('.import %s' % sym)
                out.append('%s = %s' % (name, sym))
        out.append('.macpack longbranch')
        out.append('')
        # a branch to a routine that is now in another module cannot reach:
        # use the long-branch macro (jsr/jmp pairs stay as they are)
        branch = re.compile(r'^(\S*\s+)(b(?:cc|cs|eq|ne|mi|pl|vc|vs)) (\w+)(.*)$')
        for item in emitted:
            m = branch.match(item)
            if m and m.group(3) in imports and m.group(3) not in local:
                item = '%sj%s %s%s' % (m.group(1), m.group(2)[1:], m.group(3), m.group(4))
            out.append(item)
        return org, '\n'.join(out) + '\n', local

    def run(self, outdir, modules):
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        results = {}
        if self.layout == 'baseline':
            for m in modules:
                org, text, _ = self.convert(m)
                (outdir / (m + '.s')).write_text(text)
                results[m] = org
            return results
        converted = {m: self.convert(m) for m in modules}
        for m in modules:
            _, text, local = converted[m]
            names = set(self.imports_needed.get(m, set())) | set(self.exports.get(m, []))
            exports = []
            for name in sorted(names):
                if name not in local:
                    raise ValueError('%s does not define %s to export' % (m, name))
                exports.append('.export %s_%s = %s' % (m, name, name))
            if exports:
                text = text.replace('\n\n', '\n' + '\n'.join(exports) + '\n\n', 1)
            (outdir / (m + '.s')).write_text(text)
            results[m] = sorted(names)
        return results


def load_json(path, key):
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    if key == 'drops':
        return {(m, first): end for m, first, end in data}
    if key == 'patches':
        return {(p['module'], p['line']): (p.get('end', p['line']), p['replace']) for p in data}
    return data


def check_patches(upstream, paths):
    """Every patch must name the line it expects (guards against drift)."""
    for path in paths:
        for p in json.loads(Path(path).read_text()):
            lines = (Path(upstream) / MODULES[p['module']]).read_text().splitlines()
            actual = lines[p['line'] - 1]
            if actual.rstrip() != p['expect'].rstrip():
                raise ValueError('%s:%d expected %r, found %r' % (p['module'], p['line'], p['expect'], actual))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('upstream')
    ap.add_argument('--layout', choices=('baseline', 'port'), default='port')
    ap.add_argument('--drops')
    ap.add_argument('--patches', action='append', default=[])
    ap.add_argument('--exports')
    ap.add_argument('--modules', default='CDRAW,EDIT,PPAK,RUN,RUN2,WIRE')
    ap.add_argument('--output', required=True, help='output directory')
    args = ap.parse_args()
    check_patches(args.upstream, args.patches)
    patches = {}
    for path in args.patches:
        patches.update(load_json(path, 'patches'))
    symbols = None
    if args.layout == 'port':
        with tempfile.TemporaryDirectory() as tmp:
            symbols = baseline_symbols(args.upstream, tmp)
    conv = Converter(args.upstream, args.layout, drops=load_json(args.drops, 'drops'),
                     patches=patches, exports=load_json(args.exports, 'exports'), symbols=symbols)
    modules = args.modules.split(',') if args.layout == 'port' else list(MODULES)
    results = conv.run(args.output, modules)
    for m in modules:
        print('%-6s %s' % (m, results[m] if isinstance(results[m], list) else '$%04X' % results[m]))


if __name__ == '__main__':
    main()
