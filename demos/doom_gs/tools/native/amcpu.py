"""The memory API made optional (docs/PLAY.md): the patch table that
DOOM.SYSTEM writes when its probe finds no memory API in slot 7.

With the API nothing here runs: the card's transport (gcall.s AMEMLC) and
the W images' own transports send every request to it, as before. Without
it, DOOM.SYSTEM (pl_boot.s am_patch) writes this table's records after
the install, and every request is done by the CPU, byte for byte, at the
same point:

  the card     gcall.s's AMEMCPU over AMEMLC (am_req's 20-byte head, then
               am_begin to the bank's end: the template's descriptor stays),
               AMEMCPUD and AMEMCPUF into glayout.AMEM_CPU's free ranges:
               am_begin rts, am_push the template's descriptor done by
               cx_exec, am_runs far_pload, am_fin plp/rts (the entries are
               AMEMLC's own, so gr_load, fs_restore, planes_out and the
               kernel are unchanged)
  the W images a walker (walker()) over each one's transport, which in CPU
               mode no code reaches: lload.s am_send (LCODE), dl_init.s
               dli_send (DLINIT, then on to dli_screen), s2_mvid.s mv_amem
               (MENUW), s2_fin.s sgsave (FINW). It keeps the far layer's
               zero page ($00-$05), copies each descriptor of its request
               into the card's cq and calls cx_exec, and returns A = 0 as
               the API's success does.

A record: its length (1-255), its bank (0: the main card, bank 1 at
$D000; else a RamWorks bank), its address, its bytes; a length of 0 ends
the table (PATCH_SIZE bytes in DOOM.SYSTEM at bt_patch).
"""

import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import glayout as GL, llayout as LL  # noqa: E402

PATCH_SIZE = 512                # pl_boot.s PATCH_SIZE
CARD = 0                        # a record's bank: the main card
WALKER_SIZE = 53
ENTRIES = (('cq', 'am_req'), ('c_begin', 'am_begin'), ('c_push', 'am_push'),
           ('c_runs', 'am_runs'), ('c_fin', 'am_fin'))

Record = Tuple[int, int, bytes]     # (bank, address, bytes)


class PatchError(Exception):
    pass


def card_patches(b) -> List[Record]:
    """The card's records from a tic build (its obj/<name>.amemcpu,
    .amemcpud, .amemcpuf: gcall.s's segments at glayout.AMEM_CPU): the
    CPU version's entries at AMEMLC's, am_req's template descriptor left
    out (its callers' working memory, the same bytes)."""
    lab = b.labels
    for mine, theirs in ENTRIES:
        if mine not in lab or lab[mine] != lab.get(theirs):
            raise PatchError('%s is not at %s' % (mine, theirs))
    out = []
    for seg, (lo, hi) in sorted(GL.AMEM_CPU.items()):
        if seg not in b.segments:
            raise PatchError('the tic build has no %s' % seg)
        s_lo, s_hi = b.segments[seg]
        data = (b.obj / ('%s.%s' % (b.name, seg.lower()))).read_bytes()
        if s_lo != lo or s_hi >= hi or len(data) != s_hi + 1 - s_lo:
            raise PatchError('%s at $%04X-$%04X, not in $%04X-$%04X' % (
                seg, s_lo, s_hi, lo, hi - 1))
        if seg == 'AMEMCPU':
            head = GL.AM_REQ[0] + 20 - lo         # the request's head
            tail = GL.AM_REQ[1] - lo              # after the template
            out.append((CARD, lo, data[:head]))
            out.append((CARD, lo + tail, data[tail:]))
        else:
            out.append((CARD, lo, data))
    return out


def word(v: int) -> List[int]:
    return [v & 0xFF, v >> 8]


def walker(req: int, cq: int, cx_exec: int) -> bytes:
    """A transport's CPU walker (53 bytes, position independent): the
    request at req (the API's layout: the SmartPort head, the list's length
    at +10, its count at +17, the descriptors from +20) done descriptor by
    descriptor by the card's cx_exec. Uses the request's length word as
    its count (no CPU-mode code reads it).

        ldx #5          ; the far layer's zero page kept
    @s: lda $00,x
        pha
        dex
        bpl @s
        lda req+17      ; the descriptors left
        sta req+10
        ldx #0
    @d: ldy #0          ; a descriptor into cq
    @c: lda req+20,x
        sta cq,y
        inx
        iny
        cpy #16
        bne @c
        phx
        jsr cx_exec
        plx
        dec req+10
        bne @d
        ldx #0
    @r: pla
        sta $00,x
        inx
        cpx #6
        bne @r
        lda #0          ; (the API's success)
        rts
    """
    code = ([0xA2, 0x05, 0xB5, 0x00, 0x48, 0xCA, 0x10, 0xFA,
             0xAD] + word(req + 17) + [0x8D] + word(req + 10) +
            [0xA2, 0x00, 0xA0, 0x00, 0xBD] + word(req + 20) + [0x99] +
            word(cq) + [0xE8, 0xC8, 0xC0, 0x10, 0xD0, 0xF4,
                        0xDA, 0x20] + word(cx_exec) + [0xFA, 0xCE] +
            word(req + 10) + [0xD0, 0xE8,
                              0xA2, 0x00, 0x68, 0x95, 0x00, 0xE8, 0xE0, 0x06,
                              0xD0, 0xF8, 0xA9, 0x00, 0x60])
    if len(code) != WALKER_SIZE:
        raise PatchError('the walker is %d B' % len(code))
    return bytes(code)


def transport_room(labels: Dict[str, int], entry: str,
                   end: Optional[str] = None) -> Tuple[int, int]:
    """[start, end) of a W image's transport: its entry to the next label
    of the link that is not a cheap local (@name), or to `end`."""
    lo = labels[entry]
    if end is not None:
        hi = labels[end]
    else:
        later = [a for n, a in labels.items()
                 if a > lo and not n.startswith('@')]
        if not later:
            raise PatchError('no label after %s' % entry)
        hi = min(later)
    inside = sorted(n for n, a in labels.items()
                    if lo < a < hi and not n.startswith('@'))
    if inside:
        raise PatchError('%s\'s transport holds %s' % (entry,
                                                      ', '.join(inside)))
    return lo, hi


def image_patch(bank: int, labels: Dict[str, int], entry: str, req: int,
                tic: Dict[str, int], then: Optional[str] = None,
                end: Optional[str] = None) -> Record:
    """A W image's record: the walker over its transport at `entry` (then,
    for an inline transport, jsr to the walker and jmp `then`)."""
    lo, hi = transport_room(labels, entry, end)
    w = walker(req, tic['cq'], tic['cx_exec'])
    if then is not None:
        w = bytes([0x20] + word(lo + 6) + [0x4C] + word(labels[then])) + w
    if len(w) > hi - lo:
        raise PatchError('%s: the walker\'s %d B over a transport of %d' % (
            entry, len(w), hi - lo))
    return (bank, lo, w)


def lcode_patch(level, tic: Dict[str, int]) -> Record:
    """The load image's (LCODE, lload.s am_send: the request at LW_REQ)."""
    return image_patch(LL.LCODE, level.labels, 'am_send', LL.LW_REQ, tic,
                       end='ld_stop')


def play_patches(play: Path) -> List[Record]:
    """Every record of the play disk: the card's (the play link's tic
    image), LCODE's, DLINIT's, MENUW's, FINW's."""
    from native import lrun, playlayout as PL, playlink as PK, pldisk, \
        s2run
    tb = PK.tic_build(play)
    tic = tb.labels
    out = card_patches(tb)
    out.append(lcode_patch(lrun.load_build(pldisk.LCARD, 'lcard'), tic))
    ib = PK.init_build(play)
    out.append(image_patch(PL.DLBANK, ib.labels, 'dli_send',
                           PL.DLINIT_HI - 0x0200 + 2, tic, then='dli_screen',
                           end='dli_screen'))
    for image, entry in (('MENUW', 'mv_amem'), ('FINW', 'sgsave')):
        b = PK.m11_build(image)
        out.append(image_patch(s2run.image_bank(b), b.labels, entry,
                               b.labels['am_copy'], tic))
    return out


def table(records: Sequence[Record], size: int = PATCH_SIZE) -> bytes:
    """pl_boot.s's bt_patch: the records (a record's bytes cut at 255),
    a 0 length, zeros to `size`."""
    out = bytearray()
    for bank, address, data in records:
        if not 0 <= bank <= 126 or address + len(data) > 0x10000:
            raise PatchError('a record at %d $%04X' % (bank, address))
        for k in range(0, len(data), 255):
            part = data[k:k + 255]
            out += bytes([len(part), bank]) + struct.pack('<H',
                                                           address + k)
            out += part
    out.append(0)
    if len(out) > size:
        raise PatchError('the patch table is %d B of %d' % (len(out), size))
    return bytes(out) + bytes(size - len(out))
