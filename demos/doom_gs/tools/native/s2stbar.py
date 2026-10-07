#!/usr/bin/env python3
"""Part s2stbar: the generated include of the status bar
and the face (src/native/s2_st.s, s2t_st.s), the places they need beyond
s2.inc and s2data.inc.

Usage:  python3 tools/native/s2stbar.py --inc OUT/s2stbar.inc
"""

import argparse
import struct
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import s2stmodel as M  # noqa: E402

WAMMO_ENTRIES = 11


def weapon_ammo() -> Tuple[int, ...]:
    """weaponinfo[w].ammo of the release, and the 2 entries after its 9
    that readyNum reads for a ready weapon out of range (wp_nochange 10:
    the release's bytes past the table, as upstream reads them)."""
    from native import umodel as U
    wi = U.Release().table('p_pspr65.s:weaponinfo', 12 * WAMMO_ENTRIES)
    return tuple(struct.unpack_from('<H', wi, 12 * w)[0]
                 for w in range(WAMMO_ENTRIES))


# ---------------------------------------------------------------------------
# The generated include: the places s2_st.s and s2t_st.s need beyond
# s2.inc and s2data.inc
# ---------------------------------------------------------------------------

PLAYER_FIELDS = (('PO_MO', ('mo',)), ('PO_HEALTH', ('health',)),
                 ('PO_ARMOR', ('armorpoints',)), ('PO_POWERS', ('powers', 0)),
                 ('PO_CARDS', ('cards', 0)), ('PO_READYW', ('readyweapon',)),
                 ('PO_OWNED', ('weaponowned', 0)), ('PO_AMMO', ('ammo', 0)),
                 ('PO_ATTACKDOWN', ('attackdown',)),
                 ('PO_CHEATS', ('cheats',)),
                 ('PO_DAMAGE', ('damagecount',)),
                 ('PO_BONUS', ('bonuscount',)),
                 ('PO_ATTACKER', ('attacker',)))
# the stand-ins this part still uses (its other places are s2layout.py's,
# in s2.inc)
STANDINS = (
    ('GT_POS', '$%02X' % 0x5C, 's2t_pos\'s answer, GT_0-GT_11 '
     '(x, y, angle: 4 bytes each), the game\'s GT_*'),
)


def inc_values() -> List[Tuple[str, int]]:
    from native import llayout as LL
    at = {tuple(path): a for path, enc, a in LL.player_layout()}
    out = [('G_PLAYER', LL.G['G_PLAYER']),
           ('G_MENUACTIVE', LL.G['G_MENUACTIVE'])]
    out += [(name, at[path]) for name, path in PLAYER_FIELDS]
    out += [('AM_NOAMMO', M.AM_NOAMMO), ('CF_GODMODE', M.CF_GODMODE),
            ('NO_HANDLE', LL.NO_HANDLE)]
    out += [('ST_WAMMO%d' % w, v) for w, v in enumerate(weapon_ammo())]
    return out


def inc_text() -> str:
    lines = ['; s2stbar.inc: part s2stbar\'s places beyond s2.inc and '
             's2data.inc (generated', '; by tools/native/s2stbar.py --inc; '
             'docs/SCREENS.md). Do not edit.', '']
    for name, value in inc_values():
        lines.append('%-16s= $%04X' % (name, value))
    lines += ['', '; STANDIN: places the part still stands in for']
    for name, expr, why in STANDINS:
        lines.append('%-16s= %-16s; STANDIN %s' % (name, expr, why))
    return '\n'.join(lines) + '\n'


def write_inc(path: Path) -> None:
    from native import s2layout as S
    S.write_if_changed(path, inc_text())


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--inc', metavar='OUT', required=True)
    args = parser.parse_args(argv)
    write_inc(Path(args.inc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
