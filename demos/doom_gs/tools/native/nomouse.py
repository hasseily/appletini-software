"""The mouse card made optional (docs/PLAY.md): the records DOOM.SYSTEM
writes when slot 2 is not the Appletini's mouse card.

With the Appletini's mouse card nothing here runs: its VBL interrupt is
the clock and pl_poll reads its X and buttons, as before. Without it
(an emulator's AppleMouse II, or no card) the clock is the Phasor's VIA-B
timer 1 (pl_boot.s bt_detect) and DOOM.SYSTEM (bt_init, am_records)
writes:

  mo_recs     its own records (pl_boot.s, from the card link's symbols):
              pl_vbody's head on VIA-B's timer 1 flag, pl_crash's
              interrupt off on VIA-B, pl_init's BRA over the mouse card's
              window
  bt_mpatch   this table: in each frame image that links pl_input.s's
              pl_poll (P2DW, MENUW, WIW, FINW, in their code banks at W's
              addresses), the buttons' read of $C0A5 made LDA #0 (no
              button down; a missing card's floating bus would press
              them) and pl_mouse an RTS (no X read, no re-centring write)

card_problems() checks that the bytes mo_recs replaces are still the ones
it was written for. Records as amcpu.py's: a length, a bank, an address,
the bytes; a length of 0 ends the table (MPATCH_SIZE bytes at bt_mpatch).

With an AppleMouse II in slot 2 (docs/PLAY.md, 2026-10-04) DOOM.SYSTEM
writes the records above, then pl_boot.s's ap_recs (the handler on the
mouse's VBL through its firmware, ap_irq) and this module's second table,
ap_mpatch (APATCH_SIZE bytes, apple_patches()): in each of the same frame
images, pl_poll's reads of the card's buttons ($C0A5), sequence ($C0A6)
and X ($C0A1, $C0A2) become reads of the zero page ap_irq keeps (AP_SB,
AP_X: the button in AP_SB's bit 0, its count of updates in bits 2-7, so
that the poll's two reads of the sequence still see an update between
them), pl_mouse's first byte back to LDY #2 (bt_mpatch made it an RTS),
and pl_centre's writes of the card's X writes of AP_X.
"""

import sys
from pathlib import Path
from typing import List, Optional, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import amcpu  # noqa: E402

MPATCH_SIZE = 52                # pl_boot.s MPATCH_SIZE
IMAGES = ('P2DW', 'MENUW', 'WIW', 'FINW')   # the images that link pl_poll
BUTTONS_READ = bytes([0xAD, 0xA5, 0xC0])    # lda MOUSE_BTN
NO_BUTTONS = bytes([0xA9, 0x00, 0xEA])      # lda #0, nop
MOUSE_HEAD = bytes([0xA0, 0x02])            # pl_mouse: ldy #2
RTS = bytes([0x60])

# what mo_recs replaces (pl_irq.s, pl_keys.s): pl_vbody's 13 bytes (the
# branch's offset aside), pl_crash's 8 after its SEI, pl_init's window
VBODY_HEAD = bytes([0xAE, 0xA0, 0xC0, 0xA9, 0x03, 0x8D, 0xAF, 0xC0, 0x8A,
                    0x29, 0x08, 0xF0])
CRASH_BODY = bytes([0x9C, 0xAE, 0xC0, 0xA9, 0x03, 0x8D, 0xAF, 0xC0])
IWIN_HEAD = bytes([0x9C, 0xA7, 0xC0])

# with an AppleMouse II (pl_boot.s PLMOUSE)
APATCH_SIZE = 176               # pl_boot.s APATCH_SIZE
AP_X, AP_SB = 0x00FD, 0x00FF    # pl_boot.s AP_X (2), AP_SB: ZP_SPARE
MOUSE_REGS = {0xC0A1: AP_X, 0xC0A2: AP_X + 1, 0xC0A5: AP_SB,
              0xC0A6: AP_SB}    # the card's X, buttons, sequence
MOUSE_SPAN = 18                 # pl_mouse: ldy #2 .. cpx MOUSE_SEQ
CENTRE_SPAN = 8                 # pl_centre: stz XLO, lda #$80, sta XHI

Record = amcpu.Record


def image_bytes(b, address: int, n: int) -> bytes:
    """n bytes of image b at its W address, from its stored records."""
    from native import s2run
    for _, _, lo, data in s2run.image_records(b):
        if lo <= address and address + n <= lo + len(data):
            return data[address - lo:address - lo + n]
    raise amcpu.PatchError('%s has no bytes at $%04X' % (b.image, address))


def poll_patches(b) -> List[Record]:
    """Image b's two records: its buttons' read, its pl_mouse."""
    from native import s2run
    lab = b.labels
    for name in ('pl_poll', 'pl_mouse'):
        if name not in lab:
            raise amcpu.PatchError('%s has no %s' % (b.image, name))
    lo, hi = lab['pl_poll'], lab['pl_mouse']
    code = image_bytes(b, lo, hi - lo)
    at = [k for k in range(len(code) - 2)
          if code[k:k + 3] == BUTTONS_READ]
    if len(at) != 1:
        raise amcpu.PatchError('%s\'s pl_poll reads $C0A5 %d times' % (
            b.image, len(at)))
    if image_bytes(b, hi, 2) != MOUSE_HEAD:
        raise amcpu.PatchError('%s\'s pl_mouse is not LDY #2' % b.image)
    bank = s2run.image_bank(b)
    return [(bank, lo + at[0], NO_BUTTONS), (bank, hi, RTS)]


def to_zero_page(code: bytes, want: Sequence[int]) -> bytes:
    """code with each absolute operand at the offsets `want` (the opcode's
    offset) moved from the mouse card's register to ap_irq's zero page
    (MOUSE_REGS), as absolute operands still: the lengths, so every
    branch, stay. Every other byte is kept."""
    out = bytearray(code)
    for at in want:
        operand = code[at + 1] | code[at + 2] << 8
        if operand not in MOUSE_REGS:
            raise amcpu.PatchError('$%04X is not a mouse register' % operand)
        out[at + 1:at + 3] = bytes([MOUSE_REGS[operand] & 0xFF,
                                    MOUSE_REGS[operand] >> 8])
    return bytes(out)


# the poll's code with the mouse card's registers (pl_input.s): the
# opcodes, None for a byte that is not checked (a zero-page operand)
MOUSE_CODE = (0xA0, 0x02, 0xAE, 0xA6, 0xC0, 0xAD, 0xA1, 0xC0, 0x85, None,
              0xAD, 0xA2, 0xC0, 0x85, None, 0xEC, 0xA6, 0xC0)
CENTRE_CODE = (0x9C, 0xA1, 0xC0, 0xA9, 0x80, 0x8D, 0xA2, 0xC0)


def matches(code: bytes, pattern: Sequence[Optional[int]]) -> bool:
    return len(code) == len(pattern) and all(
        p is None or p == c for c, p in zip(code, pattern))


def apple_poll_patches(b) -> List[Record]:
    """Image b's three records with an AppleMouse II: its buttons' read,
    pl_mouse's reads (from its first byte), pl_centre's writes."""
    from native import s2run
    lab = b.labels
    for name in ('pl_poll', 'pl_mouse', 'pl_centre'):
        if name not in lab:
            raise amcpu.PatchError('%s has no %s' % (b.image, name))
    lo, hi = lab['pl_poll'], lab['pl_mouse']
    code = image_bytes(b, lo, hi - lo)
    at = [k for k in range(len(code) - 2)
          if code[k:k + 3] == BUTTONS_READ]
    if len(at) != 1:
        raise amcpu.PatchError('%s\'s pl_poll reads $C0A5 %d times' % (
            b.image, len(at)))
    mouse = image_bytes(b, hi, MOUSE_SPAN)
    if not matches(mouse, MOUSE_CODE):
        raise amcpu.PatchError('%s\'s pl_mouse is not the card\'s reads' %
                               b.image)
    centre = image_bytes(b, lab['pl_centre'], CENTRE_SPAN)
    if not matches(centre, CENTRE_CODE):
        raise amcpu.PatchError('%s\'s pl_centre is not the card\'s writes' %
                               b.image)
    bank = s2run.image_bank(b)
    return [(bank, lo + at[0], to_zero_page(BUTTONS_READ, (0,))),
            (bank, hi, to_zero_page(mouse, (2, 5, 10, 15))),
            (bank, lab['pl_centre'], to_zero_page(centre, (0, 5)))]


def apple_patches(play: Path) -> List[Record]:
    """Every record of ap_mpatch on the play disk."""
    from native import playlink as PK
    out = []
    for image in IMAGES:
        b = PK.p2dw_build(play) if image == 'P2DW' else PK.m11_build(image)
        out += apple_poll_patches(b)
    return out


def play_patches(play: Path) -> List[Record]:
    """Every record of bt_mpatch on the play disk."""
    from native import playlink as PK
    out = []
    for image in IMAGES:
        b = PK.p2dw_build(play) if image == 'P2DW' else PK.m11_build(image)
        out += poll_patches(b)
    return out


def card_problems(boot, system: bytes, main_card: bytes) -> List[str]:
    """The bytes mo_recs replaces, in the card link (boot: pldisk.Boot;
    system: DOOM.SYSTEM's bytes from $2000; main_card: LC.BIN's main
    half, pldisk.card_images' layout)."""
    from native import pldisk
    lab = boot.labels

    def card(address: int, n: int) -> bytes:
        at = address - 0xE000 + 0x2000
        return bytes(main_card[at:at + n])

    out = []
    if card(lab['pl_vbody'], 12) != VBODY_HEAD:
        out.append('pl_vbody\'s head is not the mouse card\'s')
    elif card(lab['pl_vbody'] + 12, 1)[0] + lab['pl_vbody'] + 13 != \
            lab['pl_vnone']:
        out.append('pl_vbody\'s branch is not to pl_vnone')
    if card(lab['pl_crash'], 1 + len(CRASH_BODY)) != \
            bytes([0x78]) + CRASH_BODY:
        out.append('pl_crash is not SEI and the mouse card\'s mode off')
    at = lab['pl_iwin'] - pldisk.BOOT_LO
    if bytes(system[at:at + 3]) != IWIN_HEAD:
        out.append('pl_iwin is not the window\'s STZ $C0A7')
    return out
