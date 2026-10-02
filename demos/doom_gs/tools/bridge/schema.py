"""The bridge's schema of upstream's game state.

Where each number comes from:

- Field offsets and record sizes: upstream's `src/iigs/offsets.inc`
  (`OFS_<S>_<FIELD>`, `SIZEOF_<S>`), read at run time by incfile.py; the
  structures that offsets.inc does not have (the lights, the floor mover,
  the scroller, wbstartstruct_t) from the `.equ` values of their own
  source files as build/linkmap.json has them (our assembler's values).
- Fixed addresses: `src/iigs/memmap.inc` (MM_*), and the labels of
  build/linkmap.json.
- Field types (fixed, int, pointer and to what, thinker function): this
  file, written from the C structs of Doom8088 that offsets.inc mirrors
  and from the code that uses each field. Types are this file's only
  hand-written facts; no offset or address is typed in here.

The schema has five parts: the structures (STRUCTS), the object kinds
(KINDS), the globals of the game's units (GLOBALS, UNIT_EXCLUSIONS), the
lists (LISTS) and the game-state regions with their exclusions (REGIONS,
EXCLUSIONS). tools/bridge/README.md explains each.
"""

from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

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


# ---- the zone and the WAD directory ---------------------------------------

class Zone(NamedTuple):
    """memblock_t of z_zone65.s (its .equ, from the link map)."""
    size: int
    tag: int
    user: int
    next: int
    prev: int
    header: int         # PARAGRAPH: the header, and the unit of sizes
    static: int
    level: int
    levspec: int
    cache: int
    no_user: int        # the user "0:2" of a block with no user pointer
                        # (z_zone65.s noUser: lda ##2); 0 is a free block


def zone(c: Constants) -> Zone:
    z = 'z_zone65.s'
    return Zone(c.local(z, 'MB_SIZE'), c.local(z, 'MB_TAG'),
                c.local(z, 'MB_USER'), c.local(z, 'MB_NEXT'),
                c.local(z, 'MB_PREV'), c.local(z, 'PARAGRAPH'),
                c.local(z, 'PU_STATIC'), c.local(z, 'PU_LEVEL'),
                c.local(z, 'PU_LEVSPEC'), c.local(z, 'PU_CACHE'), 2)


# filelump_t of w_wad65.s: FI_FILEPOS, FI_SIZE (.equ), 16 bytes an entry
# (its comment: "filelump_t, 16 bytes"; FI_NAME + 8 name bytes)
def wad_entry(c: Constants) -> Tuple[int, int, int]:
    w = 'w_wad65.s'
    return (c.local(w, 'FI_FILEPOS'), c.local(w, 'FI_SIZE'),
            c.local(w, 'FI_NAME') + 8)


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
        Field('kindcache', c['OFS_TH_FUNCTION'] + 3, U8, 'kindcache')],
        'offsets.inc thinker_t')
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
        structs[prefix] = Struct(prefix, c['SIZEOF_' + prefix], fields,
                                 'offsets.inc OFS_%s_*' % prefix)
    for name, (unit, items, size) in LOCAL_STRUCTS.items():
        fields = []
        for fname, offset, text in items:
            if isinstance(offset, str):
                offset = c.local(unit, offset)
            fields.append(make_field(fname, offset, text, structs, th))
        structs[name] = Struct(name, c.local(unit, size), fields,
                               '%s .equ' % unit)
    return structs


# ---- thinker functions ----------------------------------------------------

# The declared thinker functions: a function pointer must be one of these
# labels exactly (by its address in the link map), or 0. The kind of a
# thinker comes from its function.
THINKER_FUNCTIONS = {
    'p_tick65.s:P_MobjThinker': 'mobj',
    'p_tick65.s:P_MobjBrainlessThinker': 'mobj',
    'p_think65.s:P_RemoveThingDelayed': 'mobj',
    'p_think65.s:P_RemoveThinkerDelayed': 'removed',
    'p_plats65.s:T_PlatRaise': 'plat',
    'p_doors65.s:T_VerticalDoor': 'door',
    'p_floor65.s:T_MoveFloor': 'floor',
    'p_lights65.s:T_LightFlash': 'lightflash',
    'p_lights65.s:T_StrobeFlash': 'strobe',
    'p_lights65.s:T_Glow': 'glow',
    'p_spec65.s:T_Scroll': 'scroll',
}
SPECIAL_STRUCTS = {'plat': 'PLAT', 'door': 'DOOR', 'floor': 'FLOOR',
                   'lightflash': 'LIGHTFLASH', 'strobe': 'STROBE',
                   'glow': 'GLOW', 'scroll': 'SCROLL'}


# ---- object kinds ---------------------------------------------------------

class Kind(NamedTuple):
    name: str
    struct: Optional[str]   # a structure of STRUCTS, or None
    stride: int             # 0: the structure's size
    identity: str           # how its objects are numbered
    where: str


KINDS = {
    'sector': Kind('sector', 'SEC', 0, 'index', '_g_sectors, _g_numsectors'),
    'line': Kind('line', 'LINE', 0, 'index', '_g_lines, _g_numlines'),
    'side': Kind('side', 'SIDE', 0, 'index', '_g_sides, numsides'),
    'subsector': Kind('subsector', 'SUB', 0, 'index',
                      '_g_subsectors, numsubsectors'),
    'seg': Kind('seg', 'SEG', 0, 'index', '_g_segs (the SEGS lump in '
                'place), count from the subsectors'),
    'node': Kind('node', 'NODE', 0, 'index', 'nodes, numnodes (the NODES '
                 'lump in place)'),
    'blocklink': Kind('blocklink', None, 4, 'index', '_g_blocklinks: the '
                      'head of the thing chain of each block'),
    'blockmap': Kind('blockmap', None, 1, 'single', '_g_blockmaplump (the '
                     'BLOCKMAP lump in place), words'),
    'reject': Kind('reject', None, 1, 'single', '_g_rejectmatrix (the '
                   'REJECT lump in place), bytes'),
    'linebuf': Kind('linebuf', None, 4, 'index', 'the line tables of the '
                    'sectors (sector.lines), a zone block of line pointers'),
    'mobj': Kind('mobj', 'MO', 0, 'pool slot', '_g_thingPool, '
                 '_g_thingPoolSize'),
    'zmobj': Kind('zmobj', 'MO', 0, 'rank', 'zone blocks (p_spawn65.s '
                  'newMobj when the pool is full)'),
    'secnode': Kind('secnode', 'SN', 0, 'reach', 'zone pools of 32 '
                    '(p_map65.s newSecnode)'),
    'plat': Kind('plat', 'PLAT', 0, 'thinker rank', 'zone, thinker list'),
    'door': Kind('door', 'DOOR', 0, 'thinker rank', 'zone, thinker list'),
    'floor': Kind('floor', 'FLOOR', 0, 'thinker rank', 'zone, thinker list'),
    'lightflash': Kind('lightflash', 'LIGHTFLASH', 0, 'thinker rank',
                       'zone, thinker list'),
    'strobe': Kind('strobe', 'STROBE', 0, 'thinker rank',
                   'zone, thinker list'),
    'glow': Kind('glow', 'GLOW', 0, 'thinker rank', 'zone, thinker list'),
    'scroll': Kind('scroll', 'SCROLL', 0, 'thinker rank',
                   'zone, thinker list'),
    'removed': Kind('removed', 'TH', 0, 'thinker rank', 'a special whose '
                    'function is P_RemoveThinkerDelayed'),
    'player': Kind('player', 'PL', 0, 'single', '_g_player'),
    'button': Kind('button', 'BTN', 0, 'index', '_g_buttonlist'),
    # constants that pointers name
    'state': Kind('state', None, 0, 'index', 'states (info65.s), '
                  'STATE_SIZE a record'),
    'lump': Kind('lump', None, 1, 'index', 'the resident WAD (fileinfo, '
                 'numlumps): lump number and byte offset'),
    'symbol': Kind('symbol', None, 1, 'label', 'a labelled constant of the '
                   'link map (rodata): unit:label'),
    'table': Kind('table', None, 1, 'memmap', 'a fixed table of memmap.inc: '
                  'its MM_ name'),
}
# Kinds whose references carry a byte offset instead of a field name.
BYTE_KINDS = ('lump', 'blockmap', 'reject', 'symbol', 'table')


# ---- globals --------------------------------------------------------------

# The game units: their data (bss and data sections) is game state. The
# other units (renderer, sound, menus, status bar, automap, platform) are
# not; their state is covered by later milestones (NATIVE.md section 13).
def is_game_unit(unit: str) -> bool:
    return unit.startswith('p_') or unit in ('g_game65.s', 'm_random65.s')


# The canonical globals: unit -> {label: type}. A type is a spec
# (fields.spec), a structure name, 'object:KIND' (the label is an object
# of that kind: its fields are canonical there), 'table:KIND' (the base
# of a table), 'list:NAME' (the head of a list of LISTS), or
# 'cache:SPEC' (canonical, class cache).
GLOBALS = {
    'g_game65.s': {
        '_g_gameaction': 'u16', '_g_gamestate': 'u16',
        '_g_gameskill': 'u16', '_g_gamemap': 'u16',
        '_g_player': 'object:player', '_g_gametic': 'u32',
        '_g_basetic': 'u32', '_g_totalkills': 'u32',
        '_g_totallive': 'u32', '_g_totalitems': 'u32',
        '_g_totalsecret': 'u32', '_g_wminfo': 'WBSTART',
        '_g_respawnmonsters': 'u16', '_g_usergame': 'u16',
        '_g_timingdemo': 'u16', '_g_demoplayback': 'u16',
        '_g_singledemo': 'u16', 'demobuffer': 'ref:lump',
        'demolength': 'u16', 'demo_p': 'ref:lump', 'starttime': 'u32',
        'totalleveltimes': 'u32', 'd_skill': 'u16', 'savegameslot': 'u16',
        'secretexit': 'u16', 'defdemoname': 'ref:symbol',
        'cmds': 'CMDS', 'prevgamestate': 'u16'},
    'm_random65.s': {'prndindex': 'u16', 'rndindex': 'u16'},
    'p_think65.s': {'_g_leveltime': 'u32',
                    '_g_thinkerclasscap': 'list:thinkers'},
    'p_setup65.s': {
        '_g_segs': 'table:seg', '_g_numsectors': 'u16',
        '_g_sectors': 'table:sector', 'numsubsectors': 'u16',
        '_g_subsectors': 'table:subsector', '_g_numlines': 'u16',
        '_g_lines': 'table:line', 'numsides': 'u16',
        '_g_sides': 'table:side', '_g_bmapwidth': 'u16',
        '_g_bmapheight': 'u16', '_g_blockmap': 'ref:blockmap',
        '_g_blockmaplump': 'table:blockmap', '_g_bmaporgx': 'fixed',
        '_g_bmaporgy': 'fixed', '_g_blocklinks': 'table:blocklink',
        '_g_rejectmatrix': 'table:reject', '_g_thingPool': 'table:mobj',
        '_g_thingPoolSize': 'u16', 'numnodes': 'u16', 'nodes': 'table:node'},
    'p_map65.s': {
        'validcount': 'u16', '_g_ceilingline': 'ref:line',
        '_s_sector_list': 'list:sector_list', 'SN_FREE': 'list:sn_free',
        'MP_CLOB': 'u16',
        'LR_OK': 'cache:u16', 'LR_USE': 'cache:u16', 'LR_N': 'cache:u16',
        'LR_LINES': 'cache:u16*24'},
    'p_spawn65.s': {'TP_HW': 'cache:i16'},
    'p_switch65.s': {'_g_buttonlist': 'object:button',
                     'switchlist': 'u16*38', 'SW_IDX': 'u8*256'},
    'p_spec65.s': {'animated_texture_basepic': 'u16'},
    'p_sight65.s': {'LOGP': 'ref:table', 'CS_PREV1': 'cache:' + MOBJ_REF,
                    'CS_PREV2': 'cache:' + MOBJ_REF, 'CS_PREVR': 'cache:u16'},
    'p_path65.s': {'GW_TAG': 'cache:u16', 'G_ID': 'cache:u16'},
}

# Globals of other units that the tic reads as game state: canonical too
# (they are outside the game-state regions, which are the game units').
EXTERNAL_GLOBALS = {
    # the menu pauses the game: G_Ticker and P_Ticker read it
    # (g_game65.s:583-590, p_think65.s P_Ticker)
    'm_menu65.s': {'_g_menuactive': 'u16'},
}

# Milestone 10 (docs/GAME.md 1.11): the external globals of the tic
# comparison, decoded only by a reader in tic mode (upstream.Reader(...,
# tic=True)), so that every existing manifest and state stays as it was:
# wi_stuff65.s's game-side counters (they decide the tic of the next
# load, wi_stuff65.s:71-83), nukage (P_UpdateAnimatedFlat writes it,
# r_data65.s:681-688; the renderer draws it), whether HU_Ticker clears
# player.message (hu_stuff65.s:249-251: showMessages, the menu's, and
# _g_message_dontfuckwithme). texturetranslation is TIC_TEXTURES: its
# entries through the pointer, one a texture (P_UpdateSpecials writes
# them, p_spec65.s:328-336).
TIC_GLOBALS = {
    'wi_stuff65.s': {'_g_acceleratestage': 'i16', 'state': 'i16',
                     'cnt': 'i16', 'bcnt': 'i16', 'cnt_time': 'i32',
                     'cnt_total_time': 'i32', 'cnt_par': 'i16',
                     'cnt_pause': 'i16', 'sp_state': 'i16',
                     'cnt_kills': 'i16', 'cnt_items': 'i16',
                     'cnt_secret': 'i16', 'snl_pointeron': 'i16'},
    'r_data65.s': {'nukage': 'u16'},
    'hu_stuff65.s': {'_g_message_dontfuckwithme': 'u16'},
    'm_menu65.s': {'showMessages': 'u16'},
}
TIC_TEXTURES = 'r_data65.s:texturetranslation'
# P_CheckSight's last pair: a pointer that names no object (upstream's
# pool moved at a load, or a zone mobj freed) is the canonical "stale"
# (docs/GAME.md 1.8), never a raw pointer
STALE_GLOBALS = ('p_sight65.s:CS_PREV1', 'p_sight65.s:CS_PREV2')
STALE = 'stale'

# The rest of each game unit's data: working variables. Each call of the
# unit's routines writes them before it reads them, so no value lives
# from one tic to the next; the bridge checks this on every dump with a
# footprint (no byte of them read before written in the tic).
SCRATCH = ('working variables of the unit\'s routines: each call writes '
           'them before reading them, so nothing lives from one tic to '
           'the next (checked on each dump: never read before written '
           'in the tic)')
UNIT_EXCLUSIONS = {
    'g_game65.s': {
        'input': ('gamekeydown', 'netcmd', 'turnframes', 'iigs_newframe',
                  'fudgecount', 'GB_SPEED', 'GB_TURN', 'GB_FORWARD',
                  'GB_SIDE'),
    },
    'p_path65.s': {'code patch': ('PT_FLP',)},
}

# Bytes of scratch that a tic reads before it writes them, but only as the
# high byte of a 16-bit load whose value the code drops: the liveness check
# (checks.py) accepts these reads. (unit, label): (offset, where and why).
OVERREADS = {
    ('p_sight65.s', 'IF_P'): (4, 'shr8V reads IF_P+3 as a word and keeps '
                              'its low byte (and ##0x00ff)'),
    ('p_sight65.s', 'IF_QS'): (0, 'interceptFrac reads IF_E+3 as a word '
                               'and keeps bits 4-7 of its low byte (and '
                               '##0x00f0); IF_QS follows IF_E'),
    ('p_sight65.s', 'SL_N'): (0, 'the sight walk reads a seg\'s '
                              'backsectornum (byte 17) as a word and keeps '
                              'the low byte (and ##0x00ff); for FAKESEG, '
                              'SL_N follows it'),
}

# The exclusions that say a byte is dead: the liveness check fails when a
# tic reads one of them before writing it. The others (caches, the zone's
# own layout, renderer data, constant tables) may be read.
DEAD_EXCLUSIONS = ('scratch', 'input', 'layout pad', 'dead link',
                   'dead secnode', 'removed thinker', 'zone slack',
                   'zone free', 'no line', 'no sector', 'flood room',
                   'tp unused', 'trace scratch')

# Working areas inside the level tables' bank: (unit, first .equ, last
# .equ); each ends with the last one's word.
BANK21_SCRATCH = (('p_trace65.s', 'IC_NEXT', 'IC_LAST'),
                  ('p_trace65.s', 'VT_P1', 'IV_ON'))


def bank21_scratch(c: 'Constants') -> List[Tuple[int, int]]:
    return [(c.local(unit, first), c.local(unit, last) + 2)
            for unit, first, last in BANK21_SCRATCH]
EXCLUSIONS = {
    'scratch': SCRATCH,
    'input': 'the input side of G_BuildTiccmd, which runs in the main '
             'loop between tics: keys held, the command it makes, the '
             'turn and frame counts; tic tests feed commands through cmds '
             'or the demo (native-verification.md section 6.2)',
    'layout pad': 'bytes a source file reserves to keep later data at its '
                  'offsets (the comment next to the .space says so)',
    'kindcache': 'byte 11 of a mobj, the high byte of its thinker '
                 'function: upstream\'s kind cache, set and cleared by '
                 'P_RunThinkers and CLEARCLEAN (p_tick65.s, p_map65.s); '
                 'never read as game state (native-verification.md 4.4)',
    'dead link': 'a list link of an object that is not on that list (a '
                 'free pool slot, a mobj waiting for its removal, a mobj '
                 'with MF_NOSECTOR or MF_NOBLOCKMAP, a thinker not on the '
                 'thinker list, a free sector node): '
                 'the code that puts the object on the list writes the link '
                 'before any read',
    'dead secnode': 'a field of a free sector node (on SN_FREE) other than '
                    'its m_tnext: newSecnode and its caller write each '
                    'field before use (p_map65.s)',
    'removed thinker': 'the body of a special whose function is '
                       'P_RemoveThinkerDelayed: it is freed at its next '
                       'turn and nothing reads it (sectors drop their '
                       'pointers before the removal)',
    'zone header': 'the 16-byte header of a zone block and the free and '
                   'static blocks that close each bank (z_zone65.s): the '
                   'allocator\'s layout, not game state; the port has no '
                   'zone for these objects',
    'zone slack': 'the bytes of a zone block after its object: the block '
                  'rounds up to 16 bytes, and takes a whole free block when '
                  'the rest would be MINFRAGMENT or less',
    'zone free': 'a free zone block: stale bytes of freed objects',
    'zone static': 'a PU_STATIC block, allocated at start-up by R_Init '
                   'and the level loader (the only Z_MallocStatic callers '
                   'are r_data65.s and w_level65.s): textures, their '
                   'heights and translation, sprites, hash chains, the song '
                   'cache: renderer and loader data. In the dumps the tic '
                   'reads none of it before writing it, and writes only '
                   'texturetranslation (P_UpdateSpecials\' texture '
                   'animation, for the renderer)',
    'zone textures': 'a PU_LEVEL block with a user pointer: the level\'s '
                     'composite textures (r_data65.s, the only '
                     'Z_MallocLevel caller with a user): renderer data',
    'zone cache': 'a PU_CACHE block: a purgable lump (hu_stuff65.s, '
                  'r_frame65.s, st_stuff65.s): not game state',
    'sight hints': 'SIGHTHINT (memmap.inc MM_SIGHTHINT, p_sight65.s): a '
                   'line number for each mobj at (its address >> 2) & '
                   '0x7ffe, which the sight walk tries first; keyed by '
                   'address, and by upstream\'s claim (p_sight65.s) it '
                   'never changes an answer: routine tests of P_CheckSight '
                   'check the claim',
    'guard counts': 'GW_TAB (p_path65.s): line counts of P_PathTraverse\'s '
                    'guard, cached per block and tagged per level (GW_TAG, '
                    'canonical): values recomputed from the level on a '
                    'miss; routine tests of P_PathTraverse check them',
    'level tables': 'bank $21 (memmap.inc MM_B3F) but its trace scratch: '
                    'the sight, move and line tables that P_InitSightTables, '
                    'P_InitSightLogs, '
                    'P_InitBlockRows and P_InitFlood derive from the level '
                    'at its load (p_sight65.s, p_map65.s); constant during '
                    'a level (the bridge checks that two dumps of one level '
                    'load agree); milestone 9 compares them per load',
    'respawn copy': 'RL_* of p_setup65.s at MM_BRL + $C000: the results of '
                    'groupLines kept for a new life on the same map, '
                    'written at a level load only; compared per load',
    'no line': 'GSTAMP words past the level\'s last line: stale from an '
               'earlier level, never read (the guard stamps lines only)',
    'no sector': 'FL_IDX bytes that are not the 8 bytes at a sector '
                 'address of this level (bank $0C is indexed by the low '
                 'word of a sector address, memmap.inc MM_FL_IDX)',
    'flood room': 'FL_ENT words that are not in a sector\'s flood list: '
                  'the room between its two parts, and past the last list '
                  '(P_InitFlood gives each sector linecount entries)',
    'tp unused': 'TP_BITS words past the pool\'s last mobj: 0 by poolInit '
                 'and never read (TP_HW stays below them)',
    'trace scratch': 'working areas of P_PathTraverse in bank $21 '
                     '(p_trace65.s): IC_NEXT to IC_LAST, the intercepts '
                     'sorted by frac, and VT_P1 to IV_ON, the constants of '
                     'the trace (sideSetup, ivSetup); written for each '
                     'trace before use (checked on each dump: never read '
                     'before written in the tic)',
    'code patch': 'PT_FLP (p_path65.s): the flags that ptPatch last patched '
                  'into the branches of P_PathTraverse\'s code (sideSetup, '
                  'p_trace65.s); it describes the code, and code is never '
                  'compared (native-verification.md 4.4)',
    'overread': 'the byte after an object whose last field is a byte '
                '(glow_t.direction): upstream reads that field as a word and '
                'keeps the low byte (T_Glow: and ##0x00ff), so the byte '
                'after it is read and dropped',
}


# ---- lists ----------------------------------------------------------------

class ListDecl(NamedTuple):
    name: str
    elements: Tuple[str, ...]       # kinds on the list
    next: Tuple[str, str]           # (struct, field) of the next link
    prev: Optional[Tuple[str, str]]  # of the prev link, or None
    prev_style: str                 # 'node': the previous object (NULL
                                    # first), 'cell': the address of the
                                    # link that points here, 'ring': a
                                    # ring through the head, '' none
    heads: str                      # where its heads are


LISTS = {
    'thinkers': ListDecl('thinkers', ('mobj', 'zmobj') + SPECIAL_KINDS +
                         ('removed',), ('TH', 'next'), ('TH', 'prev'),
                         'ring', 'p_think65.s:_g_thinkerclasscap'),
    'sector_things': ListDecl('sector_things', ('mobj', 'zmobj'),
                              ('MO', 'snext'), ('MO', 'sprev'), 'cell',
                              'sector.thinglist'),
    'block_things': ListDecl('block_things', ('mobj', 'zmobj'),
                             ('MO', 'bnext'), ('MO', 'bprev'), 'cell',
                             'blocklink'),
    'thing_nodes': ListDecl('thing_nodes', ('secnode',), ('SN', 'm_tnext'),
                            ('SN', 'm_tprev'), 'node',
                            'mobj.touching_sectorlist'),
    'sector_nodes': ListDecl('sector_nodes', ('secnode',),
                             ('SN', 'm_snext'), ('SN', 'm_sprev'), 'node',
                             'sector.touching_thinglist'),
    'sector_list': ListDecl('sector_list', ('secnode',), ('SN', 'm_tnext'),
                            ('SN', 'm_tprev'), 'node',
                            'p_map65.s:_s_sector_list'),
    'sn_free': ListDecl('sn_free', ('secnode',), ('SN', 'm_tnext'), None,
                        '', 'p_map65.s:SN_FREE'),
}


# ---- regions --------------------------------------------------------------

class Region(NamedTuple):
    name: str
    start: int
    end: int
    source: str


def regions(c: Constants, symbols: Symbols) -> List[Region]:
    """The game-state regions: every byte of each must be a schema field
    or a named exclusion. Their extents come from memmap.inc and the link
    map (the level lumps are added per dump, from the WAD directory)."""
    mm = c.memmap
    out = []
    for f in symbols.data_fragments():
        if is_game_unit(f.unit):
            out.append(Region('data %s %s' % (f.unit, f.section), f.address,
                              f.address + f.size, 'build/linkmap.json'))
    out.append(Region('zone', mm['MM_ZONE_FIRST'] << 16,
                      (mm['MM_ZONE_LAST'] + 1) << 16,
                      'memmap.inc MM_ZONE_FIRST..MM_ZONE_LAST'))
    tp_max = c.local('p_spawn65.s', 'TP_MAX')
    tp_mask = c.local('p_spawn65.s', 'TP_MASK')
    out.append(Region('pool map', mm['MM_TP_MAP'], tp_mask + 32,
                      'memmap.inc MM_TP_MAP: TP_BITS (TP_MAX / 8 = %d bytes) '
                      'and TP_MASK (16 words) of p_spawn65.s' % (tp_max // 8)))
    out.append(Region('GSTAMP', mm['MM_GSTAMP'], mm['MM_VIEWSAVE'],
                      'memmap.inc MM_GSTAMP up to MM_VIEWSAVE'))
    out.append(Region('flood index', mm['MM_FL_IDX'] & 0xff0000,
                      (mm['MM_FL_IDX'] & 0xff0000) + 0x10000,
                      'memmap.inc MM_FL_IDX: all of bank $0C'))
    out.append(Region('flood entries', mm['MM_FL_ENT'],
                      mm['MM_VIEWSAVE2'],
                      'memmap.inc MM_FL_ENT up to MM_VIEWSAVE2'))
    gw = mm['MM_GW_TAB']
    out.append(Region('guard counts', gw, gw + 10 * c.local(
        'p_path65.s', 'GW_MAXB'), 'memmap.inc MM_GW_TAB, GW_MAXB x 10 '
        'bytes (p_path65.s)'))
    out.append(Region('sight hints', mm['MM_SIGHTHINT'],
                      mm['MM_SIGHTHINT'] + 0x8000,
                      'memmap.inc MM_SIGHTHINT, 32 KB (p_sight65.s)'))
    b3f = mm['MM_B3F'] & 0xff0000
    out.append(Region('level tables', b3f, b3f + 0x10000,
                      'memmap.inc MM_B3F: its bank (tables up to $F421)'))
    brl = mm['MM_BRL']
    rl_secs = c.local('p_setup65.s', 'RL_SECS')
    rl_total = c.local('p_setup65.s', 'RL_TOTAL')
    out.append(Region('respawn copy', rl_secs, rl_total + 2,
                      'p_setup65.s RL_SECS to RL_TOTAL (MM_BRL $%06X + '
                      '$C000)' % brl))
    return out


# ---- what a comparison leaves out ------------------------------------------

def cache_fields(structs) -> List[str]:
    """Canonical fields of class cache, as canonical.diff's skip names."""
    out = []
    for kind, k in KINDS.items():
        if k.struct:
            out += ['%s.%s' % (kind, f.name) for f in structs[k.struct].fields
                    if f.cls == 'cache']
    for unit, labels in GLOBALS.items():
        out += ['%s:%s' % (unit, n) for n, text in labels.items()
                if text.startswith('cache:')]
    return out + EXTRA_CACHES


# validcount and its stamps: the renderer also counts and stamps
# (native-verification.md 4.4, NATIVE.md 3.2); compared in
# lockstep-schedule mode only.
STAMPS = ['p_map65.s:validcount', 'line.validcount', 'sector.validcount']
# GSTAMP: the guard's stamps of the lines, numbered by G_ID (a cache)
EXTRA_CACHES = ['line.gstamp']
# Written by the renderer (r_wall65.s): frame level only.
RENDER_FIELDS = ['line.r_validcount', 'line.r_flags']


# Milestone 10 (docs/GAME.md 3.5, 3.6): what the routine and tic modes
# leave out of the canonical state. P_CheckSight's pair (CS_PREV*),
# mobj.sightline and the line record of lineBlocks (LR_*) are compared:
# upstream's shortcuts make them state (GAME.md 0.3 facts 2-4). Out: the
# dead guard's state (R4: line.gstamp, GW_TAG, G_ID: written only by the
# guard, which the release never calls) and poolTake's scan start (R5:
# TP_HW, a cache that changes no result); in tic mode also the renderer's
# line.r_validcount (T1; and line.r_flags in a FRONT run, gcanon.py) and
# the tic command ring (T4: the entry G_Ticker reads is compared as
# player.cmd after the tic).
ROUTINE_SKIPS = ['line.gstamp', 'p_path65.s:GW_TAG', 'p_path65.s:G_ID',
                 'p_spawn65.s:TP_HW']
TIC_SKIPS = ROUTINE_SKIPS + ['line.r_validcount', 'g_game65.s:cmds']


def compare_skips(structs, mode: str) -> List[str]:
    """The fields a tic comparison skips: "exact" none, "lockstep" the
    caches, "free" (free-running mode) also the stamps and the render
    fields; milestone 10's "routine" and "tic" (above)."""
    if mode == 'exact':
        return []
    if mode == 'lockstep':
        return cache_fields(structs)
    if mode == 'free':
        return cache_fields(structs) + STAMPS + RENDER_FIELDS
    if mode == 'routine':
        return list(ROUTINE_SKIPS)
    if mode == 'tic':
        return list(TIC_SKIPS)
    raise ValueError(mode)
