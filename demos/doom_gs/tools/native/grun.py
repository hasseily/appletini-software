"""The tic image's group directory (gcall.s's grp_bank, grp_src,
grp_pages, grp_tail): group_entry, each group's entry as
tools/native/playdisk.py writes it into the core."""

from typing import List, Tuple


class RunError(Exception):
    pass


# a group's last page: copied as a whole page when the bytes it uses are
# more than this (once the threshold for a second far_gcopy window;
# gr_load has made one window a group since the tic image was integrated, where the few bytes past it save little either way;
# since the copy engine (docs/SPEED.md), one request a group, where a
# byte costs 0.038 us: the rule stays, at most 10 us a load)
TAIL_MAX = 224


def group_entry(bank: int, page: int, size: int) -> List[Tuple[str, int]]:
    """A group's entry of gcall.s's directory: its bank, its first page, its
    whole pages and the bytes gr_load copies of the page after them: its
    byte length rounded up to an even count (far_gcopy copied two bytes a
    turn; gr_load's request copies grp_pages pages and grp_tail bytes), or
    the page whole when it uses more than TAIL_MAX bytes or the
    group is under a page (gr_load reads a grp_pages of 0 as a group the
    image does not hold)."""
    if not 0 < size <= 0x800:
        raise RunError('a group of %d B' % size)
    pages, tail = size >> 8, size & 0xFF
    tail += tail & 1
    if tail > TAIL_MAX or (tail and not pages):
        pages, tail = pages + 1, 0
    return [('grp_bank', bank), ('grp_src', page), ('grp_pages', pages),
            ('grp_tail', tail)]
