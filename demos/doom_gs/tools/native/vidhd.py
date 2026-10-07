"""The VidHD's records (docs/PLAY.md, docs/MEMORY_MAP.md): what
DOOM.SYSTEM writes when its boot finds a VidHD and nothing of the
Appletini's (pl_boot.s PLVIDHD, vh_boot).

A VidHD keeps its own copy of the SHR screen, fed by every write it sees
to aux $2000-$9FFF: it follows RAMWRT, 80STORE and PAGE2, not RamWorks'
$C073, so DOOM's data in aux $2000-$9FFF of banks 1-126 lands on its
picture. It always honours the IIgs SHADOW register $C035. With these
records the shadowing stays off ($18: bit 3, SHR; bit 4, the aux hi-res
pages, which the IIgs rules would shadow from aux $2000-$5FFF otherwise)
and comes on ($00) only while DOOM writes the screen with bank 0
selected. Each value is written twice in a row (a //e's speaker toggles
at any $C030-$C03F access: the second write puts it back within a few
cycles; the owner's fix), interrupts masked between the two.

The shadowing is turned on lazily, at the first screen window of a batch
(a window's STA RAMWRTON becomes JSR vh_wa), and off at the batch's end:

  the card     vh_go ($FFA7, the kernel's padding before KLISTS, 17 B):
               A the value wanted, compared with the last written (its
               own CMP's operand, $FFA8); a new one written twice to
               $C035 with interrupts masked (PHP, SEI ... PLP); A, X, Y
               kept. vh_kr ($E8F2, the channel block's unused tail, 8
               B): the kernel's K_CALL return, STA DL_RES then the
               shadowing off. vh_wa ($FE70, after the memory API's CPU
               version in AMEMCPUF's room, 9 B): a screen window's start,
               the shadowing on, then STA RAMWRTON (A 0 after it).
  the kernel   k_call's STA DL_RES (after each K_CALL) a JSR vh_kr: every
               step ends with the shadowing off, so the tic phase, the
               loads, the front end and the masked phase (far_put,
               far_vput, the record spills, the object API, the CPU
               copies) never write with it on
  main         vh_sc ($0868, after the benchmark's bt_ext in BT_EXT's
               room, 13 B): the replay's group: the shadowing off, its
               scatter (nb_scatter parks batches into RECW $8000-$BFFF),
               the shadowing on (the group's replays draw)
  the images   each screen window (s2_publish, s2_begin's three,
               s2_finish, AMAPW's pubents, OVLW's titleband, DLINIT's
               dli_screen) a JSR vh_wa; the replay's nb_frame (BKFAR, in
               MCODE and in OVLW's copy) its scatter through vh_sc; and
               the writes to aux $2000-$9FFF of other banks that come
               after a screen window inside one step, each preceded by the
               shadowing off from a few bytes in the image's slack (its
               last loaded page past its stored bytes): P2DW's HUD record
               (s2_hu.s record's far_put to SS_HUDTXT), MENUW's screen
               save (mv_open's call of mv_amem: aux 0 to S2VIEW
               $2000-$9FFF; MENUW stays in W through K_MENU, whose frames
               are not K_CALLs), AMAPW's list (am_frame's call of
               listsave: SS_AMOLD), OVLW after its title band (its records
               spill to RECSP); and DLINIT's dli_quit starts with $00
               written twice (the machine left as it was found), vh_go's
               last value left at $18 so that the kernel's hook writes
               nothing after it

A record as amcpu.py's: a length, a bank (0: main memory, or the main
card with its bank 1 at $D000), an address, the bytes; a length of 0 ends
the table (PATCH_SIZE bytes at pl_boot.s vh_patch). problems() checks
every place: the original bytes at each patched instruction, each room
free and zero (in LC.BIN, in the bank files, in no segment of the links
and no layout's region), the slack inside the image's K_LOAD runs.
"""

import struct
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import amcpu  # noqa: E402

PATCH_SIZE = 448                # pl_boot.s VHPATCH_SIZE
SHADOW = 0xC035
SH_ON, SH_OFF = 0x00, 0x18
RAMWRTON = bytes([0x8D, 0x05, 0xC0])
CARD = 0                        # a record's bank: main memory, the card

# the shared code's places (docs/MEMORY_MAP.md)
GO = 0xFFA7                     # the kernel's padding before KLISTS
GO_END = 0xFFB8
KR = 0xE8F2                     # the channel block's tail (50 of 64 B used)
KR_END = 0xE900
WA = 0xFE70                     # AMEMCPUF's room after the CPU version
WA_END = 0xFE7B
SC = 0x0868                     # BT_EXT's room after bt_ext
SC_END = 0x0878

# the windows each image holds (its labels; the bytes after each window's
# STA RAMWRTON, which must not read A: vh_wa leaves A 0)
S2_WINDOWS = ('s2_publish', 's2_begin', 's2_finish')
WINDOW_FUNCS = {'P2DW': S2_WINDOWS, 'MENUW': S2_WINDOWS, 'WIW': S2_WINDOWS,
                'FINW': S2_WINDOWS, 'AMAPW': ('s2_publish', 'pubents'),
                'OVLW': ('titleband',), 'DLINIT': ('dli_screen',)}
WINDOW_COUNTS = {'P2DW': 5, 'MENUW': 5, 'WIW': 5, 'FINW': 5, 'AMAPW': 2,
                 'OVLW': 1, 'DLINIT': 1}
# the first byte after a window's STA RAMWRTON: LDX #, LDY #, LDY abs,X,
# LDA (zp), STA abs,X (titleband: A is 0, as vh_wa leaves it)
AFTER_OK = (0xA2, 0xA0, 0xBC, 0xB2, 0x9D)
# a guard: the shadowing off before a call (image, the function holding
# the JSR, the routine it calls)
GUARDS = (('P2DW', 'record', 'far_put'), ('MENUW', 'mv_open', 'mv_amem'),
          ('AMAPW', 'am_frame', 'listsave'))

Record = amcpu.Record


class Image(NamedTuple):
    name: str
    bank: int
    labels: Dict[str, int]
    lo: int                     # its stored bytes in the bank: [lo, end)
    end: int
    runs: Tuple[Tuple[int, int], ...]   # its K_LOAD runs (page, count)


def word(v: int) -> List[int]:
    return [v & 0xFF, v >> 8]


def go_code() -> bytes:
    """vh_go at GO: CMP #last, BEQ out, STA GO+1, PHP, SEI, STA $C035
    twice, PLP, RTS."""
    code = ([0xC9, SH_OFF, 0xF0, 0x0C, 0x8D] + word(GO + 1) +
            [0x08, 0x78, 0x8D] + word(SHADOW) + [0x8D] + word(SHADOW) +
            [0x28, 0x60])
    if len(code) != GO_END - GO:
        raise amcpu.PatchError('vh_go is %d B' % len(code))
    return bytes(code)


def off_then(target: int) -> bytes:
    """LDA #$18, JSR vh_go, JMP target: the shadowing off, then a routine
    whose registers (A aside) and flags are its caller's."""
    return bytes([0xA9, SH_OFF, 0x20] + word(GO) + [0x4C] + word(target))


def bank_images(files: Sequence[Tuple[str, bytes]]
                ) -> Tuple[Dict[int, bytearray], Dict[int, bytearray]]:
    """Each bank's bytes from the bank files (A2DM: a header of 256 B, 5
    bytes a segment from +8, then the segments), and a mask of the bytes
    some segment holds."""
    mem: Dict[int, bytearray] = {}
    held: Dict[int, bytearray] = {}
    for name, data in files:
        if data[:4] != b'A2DM':
            continue
        n, off = data[5], 256
        for k in range(n):
            bank, at, size = struct.unpack('<BHH', data[8 + 5 * k:13 + 5 * k])
            m = mem.setdefault(bank, bytearray(0x10000))
            h = held.setdefault(bank, bytearray(0x10000))
            m[at:at + size] = data[off:off + size]
            h[at:at + size] = b'\1' * size
            off += size
    return mem, held


def images(play: Path) -> Dict[str, Image]:
    """The images the records patch, their banks, labels, stored bytes and
    load runs (playlink.loads)."""
    from native import lrun, playlink as PK, playlayout as PL, \
        render_check as RC, rlayout as R, s2layout as S, s2run
    runs = {ld.name: ld.runs for ld in PK.loads(play)}
    out = {}
    b = PK.p2dw_build(play)
    lo, end = s2run.stored_extent(b)
    out['P2DW'] = Image('P2DW', S.image_banks()['P2DW'], b.labels, lo, end,
                        runs['p2dw'])
    for name in ('MENUW', 'AMAPW', 'WIW', 'FINW'):
        b = PK.m11_build(name)
        lo, end = s2run.stored_extent(b)
        out[name] = Image(name, S.image_banks()[name], b.labels, lo, end,
                          runs[name.lower()])
    ov = S.IMAGE['OVLW'].stored[0]
    out['OVLW'] = Image('OVLW', S.OVLW_BANK,
                        lrun.load_build(PK.M11 / PK.OVLW_BUILD[0],
                                        PK.OVLW_BUILD[1]).labels,
                        ov, ov + len(PK.ovlw_bytes()), runs['ovlw'])
    rc = RC.load_build(RC.OBJ, 'rcard')
    out['MCODE'] = Image('MCODE', R.MCODE_BANK, rc.labels, 0, 0,
                         runs['mload'])
    ib = PK.init_build(play)
    out['DLINIT'] = Image('DLINIT', PL.DLBANK, ib.labels, PL.DLINIT_LO,
                          PL.DLINIT_LO + len(PK.init_bytes(play)),
                          runs['dlinit'])
    return out


def in_runs(img: Image, lo: int, hi: int) -> bool:
    return any(p << 8 <= lo and hi <= (p + n) << 8 for p, n in img.runs)


class Patcher:
    """The records, each checked against the bank files as it is made."""

    def __init__(self, mem: Dict[int, bytearray],
                 held: Dict[int, bytearray]):
        self.mem, self.held = mem, held
        self.records: List[Record] = []
        self.slack: Dict[str, int] = {}

    def site(self, img: Image, at: int, old: bytes, new: bytes) -> None:
        """An instruction of the image replaced, the same length."""
        have = bytes(self.mem[img.bank][at:at + len(old)])
        if have != old or len(new) != len(old):
            raise amcpu.PatchError('%s $%04X holds %s, not %s' % (
                img.name, at, have.hex(), old.hex()))
        if not all(self.held[img.bank][at:at + len(old)]):
            raise amcpu.PatchError('%s $%04X is in no segment' % (img.name,
                                                                    at))
        self.records.append((img.bank, at, new))

    def room(self, img: Image, code: bytes) -> int:
        """Code in the image's slack: its last loaded page past its
        stored bytes, zero and in no segment of the bank files."""
        at = self.slack.get(img.name, img.end)
        hi = at + len(code)
        page_end = (img.end + 0xFF) & ~0xFF
        if hi > page_end or not in_runs(img, img.lo, hi):
            raise amcpu.PatchError('%s: no slack for %d B at $%04X' % (
                img.name, len(code), at))
        if any(self.mem[img.bank][at:hi]) or any(self.held[img.bank][at:hi]):
            raise amcpu.PatchError('%s $%04X-$%04X is not free' % (
                img.name, at, hi - 1))
        for name, a in img.labels.items():
            if at <= a < hi and not name.startswith('__'):
                raise amcpu.PatchError('%s\'s %s $%04X is in its slack' % (
                    img.name, name, a))
        self.slack[img.name] = hi
        self.records.append((img.bank, at, code))
        return at


def function_range(labels: Dict[str, int], name: str) -> Tuple[int, int]:
    """[start, end) of a function: its label to the next label of the link
    that is not a cheap local."""
    lo = labels[name]
    later = [a for n, a in labels.items()
             if a > lo and not n.startswith('@') and not n.startswith('__')]
    return lo, min(later) if later else lo + 0x400


def find(mem: bytearray, lo: int, hi: int, pattern: bytes) -> List[int]:
    return [k for k in range(lo, hi - len(pattern) + 1)
            if mem[k:k + len(pattern)] == pattern]


def windows(p: Patcher, img: Image) -> None:
    """The image's screen windows: each STA RAMWRTON in its window
    functions a JSR vh_wa."""
    mem = p.mem[img.bank]
    found = []
    for name in WINDOW_FUNCS[img.name]:
        if name not in img.labels:
            raise amcpu.PatchError('%s has no %s' % (img.name, name))
        lo, hi = function_range(img.labels, name)
        if name == 's2_begin':      # its three windows, up to s2_finish
            hi = img.labels['s2_finish']
        found += find(mem, lo, hi, RAMWRTON)
    if len(found) != WINDOW_COUNTS[img.name]:
        raise amcpu.PatchError('%s has %d screen windows, not %d' % (
            img.name, len(found), WINDOW_COUNTS[img.name]))
    for at in found:
        if mem[at + 3] not in AFTER_OK:
            raise amcpu.PatchError('%s $%04X: the window\'s next byte $%02X'
                                   ' may read A' % (img.name, at,
                                                    mem[at + 3]))
        p.site(img, at, RAMWRTON, bytes([0x20] + word(WA)))


def call_in(p: Patcher, img: Image, func: str, target: int) -> int:
    """The one JSR target inside func."""
    lo, hi = function_range(img.labels, func)
    at = find(p.mem[img.bank], lo, hi, bytes([0x20] + word(target)))
    if len(at) != 1:
        raise amcpu.PatchError('%s\'s %s calls $%04X %d times' % (
            img.name, func, target, len(at)))
    return at[0]


def guard(p: Patcher, img: Image, func: str, routine: str) -> None:
    """The JSR to routine in func preceded by the shadowing off."""
    labels = img.labels
    target = labels[routine]
    at = call_in(p, img, func, target)
    tramp = p.room(img, off_then(target))
    p.site(img, at, bytes([0x20] + word(target)), bytes([0x20] + word(tramp)))


def replay(p: Patcher, img: Image, bkfar_load: int) -> None:
    """nb_frame's JSR nb_scatter (BKFAR, run at $0C00, stored at
    bkfar_load in the image's bank) a JSR vh_sc."""
    lab = img.labels
    run = lab['__BKFAR_RUN__']
    f_lo, f_hi = function_range(lab, 'nb_frame')
    lo = bkfar_load + f_lo - run
    hi = bkfar_load + f_hi - run
    at = find(p.mem[img.bank], lo, hi, bytes([0x20] + word(lab['nb_scatter'])))
    if len(at) != 1:
        raise amcpu.PatchError('%s\'s nb_frame calls nb_scatter %d times' % (
            img.name, len(at)))
    p.site(img, at[0], bytes([0x20] + word(lab['nb_scatter'])),
           bytes([0x20] + word(SC)))


def card_problems(boot, main_card: bytes, tic) -> List[str]:
    """The card's and main's rooms (boot: pldisk.Boot of the play card
    link; main_card: LC.BIN's main half as playdisk.card_main makes it;
    tic: the tic image's build)."""
    from native import glayout as GL, pldisk, playlayout as PL, \
        s2layout as S
    out = []

    def card(lo: int, hi: int) -> bytes:
        at = pldisk.card_offset(lo, False)
        return bytes(main_card[at:at + hi - lo])

    lab = boot.labels
    if lab.get('k_core') != GO_END:
        out.append('k_core is not at $%04X (vh_go\'s end)' % GO_END)
    inside = [n for n, a in lab.items() if GO <= a < GO_END]
    if inside or any(card(GO, GO_END)):
        out.append('vh_go\'s $%04X-$%04X is not the kernel\'s padding (%s)'
                   % (GO, GO_END - 1, ', '.join(inside) or 'not zero'))
    cb = S.BUILDS['release']
    if KR < cb.sc_base + S.sc_size(cb.channels) or \
            KR_END > cb.sc_base + 64 or any(card(KR, KR_END)):
        out.append('vh_kr\'s $%04X-$%04X is not the channel block\'s free '
                   'tail' % (KR, KR_END - 1))
    lo, hi = GL.AMEM_CPU['AMEMCPUF']
    seg = tic.segments.get('AMEMCPUF')
    if seg is None or not (lo <= seg[1] < WA and WA_END <= hi) or \
            any(card(WA, WA_END)):
        out.append('vh_wa\'s $%04X-$%04X is not AMEMCPUF\'s free room'
                   % (WA, WA_END - 1))
    for r in PL.regions():
        if r.space == 'card' and r.start < WA_END and WA < r.end:
            out.append('vh_wa meets %s' % r.what)
        if r.space == 'main' and r.start < SC_END and SC < r.end:
            out.append('vh_sc meets %s' % r.what)
    size = tic.labels['bt_ext_end'] - tic.labels['bt_ext']
    if not (PL.BT_EXT[0] + size <= SC and SC_END <= PL.BT_EXT[1]):
        out.append('vh_sc\'s $%04X-$%04X is not BT_EXT\'s free room'
                   % (SC, SC_END - 1))
    for lo, hi in PL.STATIC_MAIN + (PL.KMAIN, PL.KMAIN2):
        if lo < SC_END and SC < hi:
            out.append('vh_sc meets DLINIT\'s copy $%04X-$%04X' % (lo, hi))
    return out


def play_patches(play: Path) -> List[Record]:
    """Every record of vh_patch on the play disk."""
    from native import pldisk, playdisk as PD, playlink as PK, \
        playlayout as PL
    boot = pldisk.load_boot(play / 'card')
    lab = boot.labels
    tic = PK.tic_build(play)
    bad = card_problems(boot, PD.card_main(boot, play)[1], tic)
    if bad:
        raise amcpu.PatchError('; '.join(bad))
    mem, held = bank_images(PD.bank_files(play))
    p = Patcher(mem, held)
    kr_at = lab['k_jsr'] + 3
    sym = PD.symbols(play)
    dl_res = sym['DL_RES']
    # the card's and main's code, the kernel's hook
    p.records.append((CARD, GO, go_code()))
    p.records.append((CARD, KR, bytes([0x8D] + word(dl_res) +
                                      [0xA9, SH_OFF, 0x4C] + word(GO))))
    p.records.append((CARD, WA, bytes([0xA9, SH_ON, 0x20] + word(GO) +
                                      list(RAMWRTON) + [0x60])))
    imgs = images(play)
    mc = imgs['MCODE']
    scatter = mc.labels['nb_scatter']
    if imgs['OVLW'].labels['nb_scatter'] != scatter:
        raise amcpu.PatchError('OVLW\'s BKFAR is not MCODE\'s')
    p.records.append((CARD, SC, bytes([0xA9, SH_OFF, 0x20] + word(GO) +
                                      [0x20] + word(scatter) +
                                      [0xA9, SH_ON, 0x4C] + word(GO))))
    card_at = pldisk.card_offset(kr_at, False)
    main_card = PD.card_main(boot, play)[1]
    if main_card[card_at:card_at + 3] != bytes([0x8D] + word(dl_res)):
        raise amcpu.PatchError('k_call\'s STA DL_RES is not at $%04X' %
                               kr_at)
    p.records.append((CARD, kr_at, bytes([0x20] + word(KR))))
    # the images
    for name in ('P2DW', 'MENUW', 'AMAPW', 'WIW', 'FINW', 'OVLW', 'DLINIT'):
        windows(p, imgs[name])
    for name, func, routine in GUARDS:
        guard(p, imgs[name], func, routine)
    ov = imgs['OVLW']
    tb = ov.labels['titleband']
    at = call_in(p, ov, 'am_ovl', tb) if 'am_ovl' in ov.labels else None
    if at is None:
        raise amcpu.PatchError('OVLW has no am_ovl')
    tramp = p.room(ov, bytes([0x20] + word(tb) + [0xA9, SH_OFF, 0x4C] +
                              word(GO)))
    p.site(ov, at, bytes([0x20] + word(tb)), bytes([0x20] + word(tramp)))
    replay(p, mc, mc.labels['__BKFAR_LOAD__'])
    replay(p, ov, ov.labels['__BKFAR_LOAD__'])
    # the quit: $00 twice, vh_go's last value left at $18
    dl = imgs['DLINIT']
    stop = sym.get('XS_snd_stop', lab.get('snd_stop'))
    quit_at = dl.labels['dli_quit']
    tramp = p.room(dl, bytes([0x08, 0x78, 0x9C] + word(SHADOW) + [0x9C] +
                             word(SHADOW) + [0x28, 0x4C] + word(stop)))
    p.site(dl, quit_at, bytes([0x20] + word(stop)),
           bytes([0x20] + word(tramp)))
    if PL.DLBANK != dl.bank:
        raise amcpu.PatchError('DLINIT is not in DLBANK')
    return p.records
