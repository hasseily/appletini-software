"""The bridge's schema of upstream's structures.

Field offsets and record sizes come from upstream's `src/iigs/offsets.inc`
(`OFS_<S>_<FIELD>`, `SIZEOF_<S>`), read at run time by incfile.py; the
structures that offsets.inc does not have (the lights, the floor mover,
the scroller, wbstartstruct_t) from the `.equ` values of their own source
files as build/linkmap.json has them. Field types (fixed, int, pointer and
to what, thinker function) are this file's only hand-written facts,
written from the C structs of Doom8088 that offsets.inc mirrors.
"""

from pathlib import Path
from typing import Dict

from bridge import incfile
from bridge.linkmap import Symbols, UPSTREAM
from bridge.fields import Array, Field, Fn, Ref, Struct, Sub, spec, U8

# ---- the constants -------------------------------------------------------


class Constants:
    """offsets.inc, memmap.inc and info.inc, parsed; the link map for the
    `.equ` values of source files."""

    def __init__(self, symbols: Symbols, upstream: Path = UPSTREAM):
        memmap = incfile.parse(upstream / 'memmap.inc')
        self.memmap = incfile.as_dict(memmap)
        self.offsets_list = incfile.parse(upstream / 'offsets.inc')
        self.offsets = incfile.as_dict(self.offsets_list)
        self.info = incfile.as_dict(incfile.parse(upstream / 'info.inc'))
        self.symbols = symbols

    def local(self, unit: str, name: str) -> int:
        """An `.equ` of a source file, as the link map has it."""
        value = self.symbols.units[unit].get(name)
        if not isinstance(value, int):
            raise KeyError('%s has no .equ %s' % (unit, name))
        return value

    def __getitem__(self, name: str) -> int:
        for table in (self.offsets, self.memmap, self.info):
            if name in table:
                return table[name]
        raise KeyError(name)


# ---- structures ------------------------------------------------------------

MOBJ_REF = 'ref:mobj|zmobj'
SPECIAL_KINDS = ('plat', 'door', 'floor', 'lightflash', 'strobe', 'glow',
                 'scroll')
SPECIAL_REF = 'ref:' + '|'.join(SPECIAL_KINDS)

# Field types by structure and field name (offsets.inc's names). A name
# not listed here is an alias of a listed field at the same offset
# (ALIASES); every offset must have one listed name.
THINKER = 'thinker'
LIST = 'list'
TYPES = {
    'MO': {
        'THINKER': THINKER, 'X': 'fixed', 'Y': 'fixed', 'Z': 'fixed',
        'SNEXT': LIST, 'SPREV': LIST, 'ANGLE': 'angle', 'SPRITE': 'i16',
        'FRAME': 'i16', 'BNEXT': LIST, 'BPREV': LIST,
        'SUBSECTOR': 'ref:subsector', 'FLOORZ': 'fixed',
        'CEILINGZ': 'fixed', 'DROPOFFZ': 'fixed', 'RADIUS': 'fixed',
        'HEIGHT': 'fixed', 'MOMX': 'fixed', 'MOMY': 'fixed',
        'MOMZ': 'fixed', 'HEALTH': 'i16', 'TYPE': 'i16', 'TICS': 'i16',
        'STATE': 'ref:state', 'FLAGS': 'u32', 'TARGET': MOBJ_REF,
        'MOVEDIR': 'u8', 'THRESHOLD': 'u8', 'PURSUECOUNT': 'i16',
        'MOVECOUNT': 'i16', 'REACTIONTIME': 'i16', 'LASTENEMY': MOBJ_REF,
        'TOUCHING_SECTORLIST': LIST,
        # the line of the last sight check of the mobj: a cache that
        # upstream says never changes an answer (p_sight65.s:88-93)
        'SIGHTLINE': 'cache:u16'},
    'SEC': {
        'FLOORHEIGHT': 'fixed', 'CEILINGHEIGHT': 'fixed',
        'SOUNDTARGET': MOBJ_REF, 'SOUNDORG': 'fixed*2',
        'VALIDCOUNT': 'u16', 'THINGLIST': LIST, 'FLOORDATA': SPECIAL_REF,
        'CEILINGDATA': SPECIAL_REF, 'TOUCHING_THINGLIST': LIST,
        'LINES': 'ref:linebuf', 'LINECOUNT': 'i16', 'FLOORPIC': 'i16',
        'CEILINGPIC': 'i16', 'LIGHTLEVEL': 'i16', 'SPECIAL': 'i16',
        'OLDSPECIAL': 'i16', 'TAG': 'i16', 'SOUNDTRAVERSED': 'i16'},
    'LINE': {
        'V1': 'i16*2', 'V2': 'i16*2', 'DX': 'i16', 'DY': 'i16',
        'SIDENUM': 'i16*2', 'BBOX': 'i16*4', 'TAG': 'i16', 'FLAGS': 'u8',
        'SLOPETYPE': 'u8', 'VALIDCOUNT': 'u16', 'R_VALIDCOUNT': 'u16',
        'R_FLAGS': 'u16', 'SPECIAL': 'i16'},
    'SIDE': {
        'SECTOR': 'ref:sector', 'TEXTUREOFFSET': 'i16', 'ROWOFFSET': 'i16',
        'TOPTEXTURE': 'i16', 'BOTTOMTEXTURE': 'i16', 'MIDTEXTURE': 'i16'},
    'SUB': {'SECTOR': 'ref:sector', 'NUMLINES': 'i16', 'FIRSTLINE': 'u16'},
    'SEG': {
        'V1': 'i16*2', 'V2': 'i16*2', 'OFFSET': 'i16', 'ANGLE': 'u16',
        'SIDENUM': 'i16', 'LINENUM': 'i16', 'FRONTSECTORNUM': 'u8',
        'BACKSECTORNUM': 'u8'},
    'NODE': {'X': 'i16', 'Y': 'i16', 'DX': 'i16', 'DY': 'i16',
             'BBOX': 'i16*8', 'CHILDREN': 'u16*2'},
    'SN': {'M_SECTOR': 'ref:sector', 'M_THING': MOBJ_REF, 'M_TPREV': LIST,
           'M_TNEXT': LIST, 'M_SPREV': LIST, 'M_SNEXT': LIST,
           'VISITED': 'i16'},
    'TC': {'FORWARDMOVE': 'i8', 'SIDEMOVE': 'i8', 'ANGLETURN': 'i16',
           'BUTTONS': 'u8'},
    'PSP': {'STATE': 'ref:state', 'TICS': 'i16', 'SX': 'i16', 'SY': 'fixed'},
    'PL': {
        'MO': MOBJ_REF, 'PLAYERSTATE': 'i16', 'CMD': 'TC', 'VIEWZ': 'fixed',
        'VIEWHEIGHT': 'fixed', 'DELTAVIEWHEIGHT': 'fixed', 'BOB': 'fixed',
        'MOMX': 'fixed', 'MOMY': 'fixed', 'HEALTH': 'i16',
        'ARMORPOINTS': 'i16', 'ARMORTYPE': 'i16', 'POWERS': 'i16*6',
        'CARDS': 'i16*3', 'BACKPACK': 'i16', 'READYWEAPON': 'i16',
        'PENDINGWEAPON': 'i16', 'WEAPONOWNED': 'i16*9', 'AMMO': 'i16*4',
        'MAXAMMO': 'i16*4', 'ATTACKDOWN': 'i16', 'USEDOWN': 'i16',
        'CHEATS': 'i16', 'REFIRE': 'i16', 'KILLCOUNT': 'i16',
        'ITEMCOUNT': 'i16', 'SECRETCOUNT': 'i16', 'MESSAGE': 'ref:symbol',
        'DAMAGECOUNT': 'i16', 'BONUSCOUNT': 'i16', 'ATTACKER': MOBJ_REF,
        'EXTRALIGHT': 'i16', 'FIXEDCOLORMAP': 'i16', 'PSPRITES': 'PSP*2',
        'DIDSECRET': 'i16'},
    'PLAT': {'THINKER': THINKER, 'SECTOR': 'ref:sector', 'SPEED': 'fixed',
             'LOW': 'fixed', 'HIGH': 'fixed', 'WAIT': 'i16', 'COUNT': 'i16',
             'STATUS': 'i16', 'TAG': 'i16', 'TYPE': 'i16',
             # p_plats65.s:1-6: upstream keeps no list of active plats,
             # so the field stays NULL (Z_CallocLevSpec)
             'LIST': 'ref:'},
    'DOOR': {'THINKER': THINKER, 'TYPE': 'i16', 'SECTOR': 'ref:sector',
             'TOPHEIGHT': 'fixed', 'SPEED': 'fixed', 'DIRECTION': 'i8',
             'TOPCOUNTDOWN': 'i16', 'LINE': 'ref:line', 'LIGHTTAG': 'i16'},
    'BTN': {'LINE': 'ref:line', 'WHERE': 'i16', 'BTEXTURE': 'i16',
            'BTIMER': 'i16', 'SOUNDORG': 'ref:sector'},
}
ALIASES = {('MO', 'TOUCHING'): 'TOUCHING_SECTORLIST',
           ('SN', 'SECTOR'): 'M_SECTOR', ('SN', 'THING'): 'M_THING',
           ('SN', 'TNEXT'): 'M_TNEXT'}

# Structures of source files' own .equ: (unit, [(field, offset .equ or
# a number, type)], size .equ). The thinker header is bytes 0-11.
LOCAL_STRUCTS = {
    'FLOOR': ('p_floor65.s', [('THINKER', 0, THINKER),
                              ('SECTOR', 'FM_SECTOR', 'ref:sector'),
                              ('TYPE', 'FM_TYPE', 'i16'),
                              ('DIRECTION', 'FM_DIRECTION', 'i8'),
                              ('TEXTURE', 'FM_TEXTURE', 'i16'),
                              ('DEST', 'FM_DEST', 'fixed'),
                              ('SPEED', 'FM_SPEED', 'fixed')], 'FM_SIZE'),
    'LIGHTFLASH': ('p_lights65.s', [('THINKER', 0, THINKER),
                                    ('SECTOR', 'LT_SECTOR', 'ref:sector'),
                                    ('COUNT', 'LF_COUNT', 'i16'),
                                    ('MAXLIGHT', 'LF_MAXLIGHT', 'i16'),
                                    ('MINLIGHT', 'LF_MINLIGHT', 'i16')],
                   'LF_SIZE'),
    'STROBE': ('p_lights65.s', [('THINKER', 0, THINKER),
                                ('SECTOR', 'LT_SECTOR', 'ref:sector'),
                                ('COUNT', 'SF_COUNT', 'i16'),
                                ('MINLIGHT', 'SF_MINLIGHT', 'i16'),
                                ('MAXLIGHT', 'SF_MAXLIGHT', 'i16'),
                                ('DARKTIME', 'SF_DARKTIME', 'i16')],
               'SF_SIZE'),
    'GLOW': ('p_lights65.s', [('THINKER', 0, THINKER),
                              ('SECTOR', 'LT_SECTOR', 'ref:sector'),
                              ('MINLIGHT', 'GL_MINLIGHT', 'i16'),
                              ('MAXLIGHT', 'GL_MAXLIGHT', 'i16'),
                              ('DIRECTION', 'GL_DIRECTION', 'i8')],
             'GL_SIZE'),
    # scroll_t: s->textureoffset = &sides[affectee].textureoffset
    # (p_spec65.s addScroller)
    'SCROLL': ('p_spec65.s', [('THINKER', 0, THINKER),
                              ('TEXTUREOFFSET', 'SC_TEXOFS', 'ref:side')],
               'SC_SIZE'),
    'WBSTART': ('g_game65.s', [('DIDSECRET', 'WM_DIDSECRET', 'u16'),
                               ('LAST', 'WM_LAST', 'u16'),
                               ('NEXT', 'WM_NEXT', 'u16'),
                               ('MAXKILLS', 'WM_MAXKILLS', 'u32'),
                               ('MAXITEMS', 'WM_MAXITEMS', 'u32'),
                               ('MAXSECRET', 'WM_MAXSECRET', 'u32'),
                               ('PARTIME', 'WM_PARTIME', 'u16'),
                               ('SKILLS', 'WM_SKILLS', 'u32'),
                               ('SITEMS', 'WM_SITEMS', 'u32'),
                               ('SSECRET', 'WM_SSECRET', 'u32'),
                               ('STIME', 'WM_STIME', 'u32'),
                               ('TOTALTIMES', 'WM_TOTALTIMES', 'u32')],
                'WM_SIZE'),
}


def field_type(text, structs: Dict[str, Struct]):
    base, star, count = text.partition('*')
    if base in structs:
        t = Sub(structs[base])
        return Array(t, int(count)) if star else t
    return spec(text)


def make_field(name: str, offset: int, text: str,
               structs: Dict[str, Struct], th: Struct) -> Field:
    if text.startswith('cache:'):
        return Field(name.lower(), offset, field_type(text[6:], structs),
                     'cache')
    if text == THINKER:
        return Field(name.lower(), offset, Sub(th), 'thinker')
    if text == LIST:
        return Field(name.lower(), offset, Ref(('list',)), 'list')
    return Field(name.lower(), offset, field_type(text, structs))


def build_structs(c: Constants) -> Dict[str, Struct]:
    structs: Dict[str, Struct] = {}
    th = Struct('TH', c['SIZEOF_TH'], [
        Field('prev', c['OFS_TH_PREV'], Ref(('list',)), 'list'),
        Field('next', c['OFS_TH_NEXT'], Ref(('list',)), 'list'),
        Field('function', c['OFS_TH_FUNCTION'], Fn()),
        # byte 11: the high byte of the function pointer; for a mobj,
        # upstream's kind cache (p_tick65.s P_RunThinkers)
        Field('kindcache', c['OFS_TH_FUNCTION'] + 3, U8, 'kindcache')])
    structs['TH'] = th
    order = ['TC', 'PSP', 'MO', 'SEC', 'LINE', 'SIDE', 'SUB', 'SEG', 'NODE',
             'SN', 'PL', 'PLAT', 'DOOR', 'BTN']
    for prefix in order:
        types = TYPES[prefix]
        found: Dict[int, str] = {}
        for k in c.offsets_list:
            if not k.name.startswith('OFS_%s_' % prefix):
                continue
            name = k.name[len('OFS_%s_' % prefix):]
            if name in types:
                if k.value in found:
                    raise ValueError('%s: %s and %s at %d' % (
                        prefix, found[k.value], name, k.value))
                found[k.value] = name
            elif (prefix, name) not in ALIASES:
                raise ValueError('offsets.inc OFS_%s_%s has no type in '
                                 'the schema' % (prefix, name))
        missing = set(types) - set(found.values())
        if missing:
            raise ValueError('%s: no offset for %s' % (prefix,
                                                       sorted(missing)))
        fields = [make_field(found[o], o, types[found[o]], structs, th)
                  for o in sorted(found)]
        structs[prefix] = Struct(prefix, c['SIZEOF_' + prefix], fields)
    for name, (unit, items, size) in LOCAL_STRUCTS.items():
        fields = []
        for fname, offset, text in items:
            if isinstance(offset, str):
                offset = c.local(unit, offset)
            fields.append(make_field(fname, offset, text, structs, th))
        structs[name] = Struct(name, c.local(unit, size), fields)
    return structs


# Kinds whose references carry a byte offset instead of a field name.
BYTE_KINDS = ('lump', 'blockmap', 'reject', 'symbol', 'table')
