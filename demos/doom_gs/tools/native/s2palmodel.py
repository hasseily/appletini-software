#!/usr/bin/env python3
"""The host model of upstream's palette rules (docs/SCREENS.md 1.3, 1.5.7,
1.5.8; part s2pal, docs/m11-parts/s2pal.md): the palette state of
src/iigs/i_viigs65.s (scb, palette, newpal, curtint, levelcopy,
palettecount, scbchanged, picturenum, viewpal, strippal), the screen's
SCBs and palettes, TINTPAL and NIBTAB, and the routines that change them:
I_SetPalette, I_ReloadPalette, I_FinishUpdate / D_Wipe without showDirty,
I_ApplyColors, newColors, pictureColors, I_ViewPalette, I_MessageStrip
(its palette part), stripEarly's, gammaColor, buildTints (tintRecords,
tintColors), buildNibtab, setRows, rowPalette, enterLevelMode, drawPicture
(its palette part), ST_doPaletteStuff [R i_viigs65.s:303-405, :500-787,
:1006-1200, :1226-1295; st_stuff65.s:1099-1171; d_main65.s:764-778].

Written from those routines' text, with upstream's 16-bit arithmetic:
the model is the specification the native code (src/native/s2_pal.s,
s2_nib.s, s2_palw.s) is compared with, and tools/native/s2pal.py checks
it against ref816's captures first.

Every screen store is logged in order (`Model.stores`: offset from aux 0
$2000, value), so the poisoned injection knows the bytes a frame writes.
"""

from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

# i_viigs65.s's constants [R i_viigs65.s:40-68]
VIEW_ROWS = 168
ST_HEIGHT = 32
STAT_PALS = 8
STAT_RECS = ST_HEIGHT
OVL_PAL = STAT_PALS + 1         # 9: MENU_PAL
MENU_PAL = OVL_PAL
MSG_PAL = OVL_PAL + 1           # 10
AMAP_PAL = OVL_PAL + 2          # 11
OVL_PALS = 3
LEVEL_PALS = OVL_PAL + OVL_PALS  # 12
TINTS = 14
TINT_ROW = LEVEL_PALS * 32      # 384
TINTPAL_SIZE = TINTS * TINT_ROW  # 5,376
STRIP_ROWS = 10
PALREC_PAIRS = 14 * 16 * 2      # 448: a record's pairs
PALREC_SIZE = 14 * 16 * 2 + 256  # 704
PICTURE_SCB = 32000
PICTURE_PALS = 32256
PICTURE_PAIRS = 32768
PICTURE_SIZE = 36864
NO_PALETTE_CHANGE = 100
NIBTAB_SIZE = 16 * 0x400
# st_stuff65.s [R :36-40]
STARTREDPALS, STARTBONUSPALS = 1, 9
NUMREDPALS, NUMBONUSPALS = 8, 4
RADIATIONPAL = 13
# the screen (aux 0), as offsets from $2000
SCB_OFS = 0x9D00 - 0x2000
PAL_OFS = 0x9E00 - 0x2000
SCREEN_PAL_LO = SCB_OFS        # $9D00-$9FFF: the bytes this part writes
SCREEN_PAL_SIZE = 0x300

# gammatab [R i_viigs65.s:178-182]: 5 levels of 16
GAMMATAB = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15),
    (0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 13, 14, 15),
    (0, 2, 4, 5, 6, 7, 8, 9, 10, 10, 11, 12, 13, 14, 14, 15),
    (0, 3, 4, 5, 7, 8, 8, 9, 10, 11, 12, 12, 13, 14, 14, 15),
    (0, 3, 5, 6, 7, 8, 9, 10, 11, 11, 12, 13, 13, 14, 14, 15),
)


def w16(v: int) -> int:
    return v & 0xFFFF


def neg16(v: int) -> bool:
    """The N flag of a 16-bit result."""
    return bool(v & 0x8000)


def asr16(v: int) -> int:
    """cmp ##$8000, ror a: a 16-bit arithmetic shift right."""
    v = w16(v)
    return (v >> 1) | (v & 0x8000)


def gamma_color(c: int, gamma: int) -> int:
    """gammaColor [R i_viigs65.s:565-610]: each 4-bit channel through the
    gamma table's row; bits 12-15 of the colour are dropped."""
    row = GAMMATAB[gamma]
    return (row[(c >> 8) & 15] << 8) | (row[(c >> 4) & 15] << 4) | \
        row[c & 15]


def tint_colors(tintpal: bytearray, pal: int, record: bytes,
                gamma: int) -> None:
    """tintColors [R :672-704]: palette `pal` of TINTPAL in each of the 14
    tints, from the record's 14 x 16 colours, with gamma."""
    for t in range(TINTS):
        for c in range(16):
            v = record[t * 32 + 2 * c] | record[t * 32 + 2 * c + 1] << 8
            g = gamma_color(v, gamma)
            at = t * TINT_ROW + pal * 32 + 2 * c
            tintpal[at:at + 2] = g.to_bytes(2, 'little')


def build_tints(tintpal: bytearray, view: bytes, stat: bytes, ovl: bytes,
                gamma: int) -> None:
    """buildTints [R :611-641]: palette 0 from the view's record, 1-8 from
    GSSTAT's records (after its row map), 9-11 from GSOVL's."""
    tint_colors(tintpal, 0, view, gamma)
    for k in range(STAT_PALS):
        at = STAT_RECS + k * PALREC_SIZE
        tint_colors(tintpal, 1 + k, stat[at:at + PALREC_SIZE], gamma)
    for k in range(OVL_PALS):
        at = k * PALREC_SIZE
        tint_colors(tintpal, OVL_PAL + k, ovl[at:at + PALREC_SIZE], gamma)


def build_nibtab(pairs: bytes) -> bytes:
    """buildNibtab [R :705-736]: a palette's 1 KB nibble table from its
    256 pair bytes: the left pixel even row, odd row, the right pixel even
    row, odd row."""
    p = pairs[:256]
    return bytes(b & 0xF0 for b in p) + bytes((b << 4) & 0xFF for b in p) + \
        bytes(b & 0x0F for b in p) + bytes(b >> 4 for b in p)


class PalState(NamedTuple):
    """The palette state as upstream's words (scb and palette as bytes)."""
    scb: bytes                  # 200
    palette: bytes              # 512
    newpal: int
    curtint: int
    levelcopy: int
    palettecount: int
    scbchanged: int
    picturenum: int
    viewpal: int
    strippal: int


FLAGS = ('newpal', 'curtint', 'levelcopy', 'palettecount', 'scbchanged',
         'picturenum', 'viewpal', 'strippal')


class Model:
    """Upstream's palette routines on one machine's state: the palette
    state, the screen's $9D00-$9FFF, TINTPAL, NIBTAB, the gamma, the text
    cache's invalidation, the stores in order."""

    def __init__(self, st: PalState, screen: bytes, tintpal: bytes,
                 gamma: int, nibtab: Optional[bytes] = None):
        self.scb = bytearray(st.scb)
        self.palette = bytearray(st.palette)
        for f in FLAGS:
            setattr(self, f, getattr(st, f))
        self.screen = bytearray(screen)         # $9D00-$9FFF
        self.tintpal = bytearray(tintpal)
        self.gamma = gamma
        self.nibtab = bytearray(nibtab) if nibtab is not None else None
        self.stores: List[Tuple[int, int]] = []  # (offset from $2000, value)
        self.invalidated = 0                    # textInvalidate's calls
        self.strip_clears = 0                   # I_MessageStrip's clears
        self.paths: Dict[str, int] = {}         # each branch taken

    def took(self, path: str) -> None:
        self.paths[path] = self.paths.get(path, 0) + 1

    def state(self) -> PalState:
        return PalState(bytes(self.scb), bytes(self.palette),
                        *(getattr(self, f) for f in FLAGS))

    def store(self, offset: int, value: int) -> None:
        self.screen[offset - SCREEN_PAL_LO] = value
        self.stores.append((offset, value))

    # -- the routines
    def set_palette(self, pal: int) -> None:
        """I_SetPalette [R :315-317]."""
        self.newpal = pal & 0xFF

    def text_invalidate(self) -> None:
        self.invalidated += 1

    def row_palette(self, row: int, pal: int) -> None:
        """rowPalette [R :766-787]: the row's SCB (its nibble pages are
        derived from it natively)."""
        self.scb[row] = pal & 0xFF

    def set_rows(self, first: int, count: int, pal: int) -> None:
        """setRows [R :738-753]."""
        self.text_invalidate()
        for x in range(first, first + count):
            self.row_palette(x, pal)
        self.scbchanged = 1

    def view_palette(self, pal: int) -> None:
        """I_ViewPalette [R :509-518]."""
        if pal == self.viewpal:
            self.took('I_ViewPalette: the same')
            return
        self.took('I_ViewPalette: new, %s' % ('the automap\'s'
                                             if pal == AMAP_PAL else
                                             'the view\'s'))
        self.viewpal = self.strippal = pal
        self.set_rows(0, VIEW_ROWS, pal)

    def message_strip(self, on: int, clear: int) -> None:
        """I_MessageStrip [R :519-555], its palette part; a clear of the
        strip's rows (s2hud's) is counted."""
        if on:
            if not (self.strippal == MSG_PAL and clear == 0):
                self.strip_clears += 1
                self.took('I_MessageStrip: on, a clear')
            else:
                self.took('I_MessageStrip: on, kept')
            a = MSG_PAL
        else:
            self.took('I_MessageStrip: off')
            a = self.viewpal
        if a != self.strippal:
            self.took('I_MessageStrip: the rows set')
            self.strippal = a
            self.set_rows(0, STRIP_ROWS, a)

    def strip_early(self, paused: int, message_on: int, message_new: int,
                    menuactive: int) -> int:
        """stripEarly's palette [R d_main65.s:764-778]; the new
        message_new."""
        if paused:
            self.took('stripEarly: paused')
            return message_new
        x = message_new
        new = 1 if menuactive else 0
        if menuactive:
            self.took('stripEarly: a menu')
        self.message_strip(message_on, x)
        return new

    def st_do_palette_stuff(self, damage: int, strength: int, bonus: int,
                            ironfeet: int, menuactive: int,
                            st_palette: int) -> int:
        """ST_doPaletteStuff [R st_stuff65.s:1103-1171]: the new
        st_palette (I_SetPalette when it changes)."""
        cnt = w16(damage)
        if w16(strength):
            bzc = w16(12 - (w16(strength) >> 6))
            if bzc != cnt and not neg16(bzc - cnt):
                cnt = bzc
        if cnt:
            a = asr16(asr16(asr16(cnt + 7)))
            if not neg16(a - NUMREDPALS):
                a = NUMREDPALS - 1
            if menuactive:
                a = asr16(a)
            a = w16(a + STARTREDPALS)
        elif w16(bonus):
            a = asr16(asr16(asr16(w16(bonus) + 7)))
            if not neg16(a - NUMBONUSPALS):
                a = NUMBONUSPALS - 1
            a = w16(a + STARTBONUSPALS)
        else:
            p = w16(ironfeet)
            if not neg16(p - (4 * 32 + 1)) or p & 8:
                a = RADIATIONPAL
            else:
                a = 0
        if a != w16(st_palette):
            st_palette = a
            self.set_palette(a)
            self.took('ST_doPaletteStuff: a new tint')
        else:
            self.took('ST_doPaletteStuff: the same')
        return st_palette

    def level_palettes(self) -> None:
        self.levelcopy = 1

    def new_colors(self) -> None:
        """newColors [R :354-391]."""
        if self.newpal != NO_PALETTE_CHANGE:
            self.curtint = self.newpal
            if self.picturenum & 0x8000:
                self.level_palettes()
                self.took('newColors: a new tint, a level')
            else:
                self.took('newColors: a new tint, a picture')
            self.newpal = NO_PALETTE_CHANGE
        if self.scbchanged:
            self.took('newColors: the SCBs')
            for x in range(200):
                self.store(SCB_OFS + x, self.scb[x])
            self.scbchanged = 0
        if self.levelcopy:
            self.took('newColors: a TINTPAL row')
            self.levelcopy = 0
            at = w16(self.curtint * TINT_ROW)
            row = self.tintpal[at:at + TINT_ROW]
            if len(row) != TINT_ROW:
                raise ValueError('the tint row %d passes TINTPAL'
                                 % self.curtint)
            for k in range(TINT_ROW):
                self.store(PAL_OFS + k, row[k])

    def picture_colors(self) -> None:
        """pictureColors [R :392-405]: palettecount words, from the top."""
        if not self.palettecount:
            return
        self.took('pictureColors')
        n = 2 * self.palettecount
        for k in range(n - 1, -1, -1):
            self.store(PAL_OFS + k, self.palette[k])
        self.palettecount = 0

    def black(self) -> None:
        for k in range(511, -1, -1):
            self.store(PAL_OFS + k, 0)

    def apply_colors(self) -> None:
        """I_ApplyColors [R :347-350]."""
        self.new_colors()
        self.picture_colors()

    def finish_update(self, title: bool = False) -> Optional[int]:
        """I_FinishUpdate and D_Wipe [R :329-345] without showDirty; the
        index in `stores` where the marked bytes would go (the wipe's PW
        point is after them), None without a picture. `title`: titleWipe's
        path (no black: X3)."""
        if self.palettecount:
            if title:
                self.took('the finish: titleWipe (X3)')
                self.apply_colors()
                return None
            self.took('the finish: the black step')
            self.black()
            self.new_colors()
            mid = len(self.stores)
            self.picture_colors()
            return mid
        self.new_colors()
        return None

    def reload_palette(self, view: Optional[Sequence[bytes]]) -> bool:
        """I_ReloadPalette [R :318-328]; view: (the view record, GSSTAT,
        GSOVL) when a level's tints are rebuilt. True: the level's
        branch."""
        if not (self.picturenum & 0x8000):
            self.took('I_ReloadPalette: a picture')
            self.picturenum = 0xFFFF
            return False
        self.took('I_ReloadPalette: a level')
        if view is not None:
            build_tints(self.tintpal, view[0], view[1], view[2], self.gamma)
            self.level_palettes()
        return True

    def set_nibtab(self, pal: int, pairs: bytes) -> None:
        """buildNibtab: textInvalidate, then the table."""
        self.text_invalidate()
        if self.nibtab is not None:
            self.nibtab[pal * 0x400:(pal + 1) * 0x400] = build_nibtab(pairs)

    def enter_level_mode(self, view: bytes, stat: bytes,
                         ovl: bytes) -> None:
        """enterLevelMode [R :788-875]: the nibble tables of palettes 0-11,
        the view's rows (palette 0), the status bar's rows (GSSTAT's row
        map + 1), no picture, the level's colours."""
        self.set_nibtab(0, view[PALREC_PAIRS:PALREC_PAIRS + 256])
        for n in range(1, STAT_PALS + 1):
            at = STAT_RECS + (n - 1) * PALREC_SIZE + PALREC_PAIRS
            self.set_nibtab(n, stat[at:at + 256])
        for n in range(OVL_PAL, LEVEL_PALS):
            at = (n - OVL_PAL) * PALREC_SIZE + PALREC_PAIRS
            self.set_nibtab(n, ovl[at:at + 256])
        self.viewpal = self.strippal = 0
        self.set_rows(0, VIEW_ROWS, 0)
        for y in range(ST_HEIGHT):
            self.row_palette(VIEW_ROWS + y, w16(stat[y] + 1))
        self.scbchanged = 1
        self.picturenum = 0xFFFF
        self.level_palettes()

    def set_level_palette(self, view: bytes, stat: bytes, ovl: bytes
                          ) -> None:
        """I_SetLevelPalette's palette part [R :1015-1200]: the tints with
        gamma (always rebuilt: the same bytes as upstream's cache of its
        record and gamma), enterLevelMode."""
        build_tints(self.tintpal, view, stat, ovl, self.gamma)
        self.enter_level_mode(view, stat, ovl)

    def draw_picture(self, num: int, pic: bytes) -> bool:
        """drawPicture's palette part [R :1226-1295]: when the picture is
        new, its rows, its 16 palettes with gamma, palettecount 256, its
        16 nibble tables. True when it was new."""
        if self.picturenum == num:
            self.took('drawPicture: the same')
            return False
        self.took('drawPicture: new')
        self.text_invalidate()
        for x in range(200):
            self.row_palette(x, pic[PICTURE_SCB + x])
        self.scbchanged = 1
        for k in range(0, 512, 2):
            v = pic[PICTURE_PALS + k] | pic[PICTURE_PALS + k + 1] << 8
            g = gamma_color(v, self.gamma)
            self.palette[k:k + 2] = g.to_bytes(2, 'little')
        self.palettecount = 256
        for i in range(16):
            at = PICTURE_PAIRS + i * 256
            self.set_nibtab(i, pic[at:at + 256])
        self.picturenum = num
        return True


def stores_written(stores: Sequence[Tuple[int, int]]) -> Dict[int, int]:
    """The final value of each written byte."""
    out: Dict[int, int] = {}
    for o, v in stores:
        out[o] = v
    return out
