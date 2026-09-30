# The state bridge (v1)

Upstream's game state and the port's in one canonical model: milestone 6,
item 2 of [`docs/NATIVE.md`](../../docs/NATIVE.md) (section 11, "State
bridge"), designed in
[`docs/research/native-verification.md`](../../docs/research/native-verification.md)
sections 1-4. Standard-library Python, 3.9 to 3.14.

A ref816 memory image of the reference becomes a canonical state: objects
with identities, fields with values, pointers as references to identities,
lists as sequences. A canonical state goes back into upstream's layout
byte for byte, and into the port's layout by a layout manifest, and back.
Every byte of the game-state regions is claimed by a schema field or by a
named exclusion with its reason.

| File | What it is |
| --- | --- |
| `bridge.py` | The command line (below) |
| `dumps.py` | Dumps of the reference at `G_Ticker` entries, from the coverage scripts and demo3, with each tic's footprint; `--sweep` keeps footprints only |
| `incfile.py` | Our own parser of upstream's `.inc` files (`NAME .equ EXPR`) |
| `linkmap.py` | Symbols of `build/linkmap.json`: exact lookups only, never the nearest label |
| `fields.py` | Field types, structures (fields must tile the record), references `R` |
| `schema.py` | The schema: structures, kinds, globals, exclusions, lists, regions |
| `upstream.py` | Upstream's layout: `Reader` (image to canonical), `Writer` (canonical to image), `Coverage` |
| `canonical.py` | The canonical model's JSON form, `diff`, `counts`, `dangling` |
| `identity.py` | The identity rules, applied to a canonical state (`renumber`) |
| `layout.py` | The port's layout manifest format, and `native_v1`, the first native layout |
| `port.py` | The port's layout: `PortWriter`, `PortReader`, and `through_a2vm` |
| `checks.py` | The acceptance checks |
| `synthetic.py` | States made from a dump the way upstream would make them (zone mobjs, a removed special), for the tests |
| `memory.py` | Upstream's memory (ref816 images, `--dump-ram` files) and the port's (a2vm images and snapshots) |

Tests: `tests/test_bridge.py` (the parts on hand-made data, and the schema
against upstream's includes and the link map) and
`tests/test_bridge_dumps.py` (the acceptance on every dump, the synthetic
cases, and that broken states fail). Both skip, saying what to run, when
`build/` or the dumps are missing.

## Commands

From `demos/doom_gs`, after `tools/fetch_upstream.py`,
`tools/v816/imgmatch.py` and `make -C tools/ref816` (milestones 1 and 2):

    python3 tools/bridge/dumps.py                 # 35 dumps, about 15 s
    python3 tools/bridge/dumps.py --sweep 80      # 400 footprints, about 25 s
    python3 tools/bridge/bridge.py check          # the acceptance, about 20 s
    python3 tools/bridge/bridge.py check --a2vm --json build/bridge/report.json
    python3 tools/bridge/bridge.py decode build/bridge/dumps/demo-06 -o s.json
    python3 tools/bridge/bridge.py upstream s.json --base build/bridge/dumps/demo-06 -o s.img
    python3 tools/bridge/bridge.py layout         # build/bridge/native-v1.json
    python3 tools/bridge/bridge.py port s.json -o s.a2vmimg
    python3 tools/bridge/bridge.py from-port SNAPSHOT.ram -o s2.json
    python3 -m unittest discover -s tests -p 'test_bridge*.py'

`dumps.py` runs ref816 under `nice -n 10`, two runs at a time (`--jobs`);
`check --a2vm` runs a2vm under `nice -n 10` too, one run at a time.
It uses only ref816's existing options, as `tools/ref816/capture.py` does:
a first run logs every `G_Ticker` entry (`--mark`), a second captures the
chosen calls (`--capture`, `--capture-hit`) and must end with the same RAM
and the same log. `--dump-at` was not needed. `check --a2vm` needs
`build/a2vm/a2vm` and appletini-one's `docs/Apple2e_Enhanced.rom`
(`APPLETINI_ROOT` to move it).

## The dumps

A dump is the state at a `G_Ticker` entry (`g_game65.s:563`): one tic done,
the next not begun (verification section 6.1). `build/bridge/dumps/SET-NN/`
holds `entry.img` (all RAM, a ref816 image), `reads.img` and `writes.img`
(the tic's footprint: bytes read before written, bytes written),
`call.json` and `dump.json` (set, script, hit, note, gametic, gamemap,
gamestate, leveltime).

| Set | Script | Dumps |
| --- | --- | --- |
| `title` | `coverage/title.script` | 3 tics from "demo" to "demo-25s" |
| `demo` | title.script run on until demo3 ends (made in `dumps.py`) | 12 tics over all of demo3, leveltime 1 to 2,134 (its last tic) |
| `newgame` | `coverage/newgame.script` | 8 tics from "still" to the end (a door opens) |
| `viewsize` | `coverage/viewsize.script` | 3 tics after the first full-size shot |
| `tour` | `coverage/tour.script` | the first tic after each map's shot: E1M1-E1M9 |

The sweep (`build/bridge/sweep/SET-sNNN/`) keeps the footprints of 80 tics
spread over each whole run (menus, loads and intermissions included), 400
in all: evidence for the liveness check on many more tics.

## The canonical model

    {"format": "bridge-canonical 1",
     "globals": {"unit:label": value, ...},
     "objects": {kind: {identity: {field: value, ...}}}}

Values are integers, strings (a thinker function as `"unit:label"`, raw
bytes in hexadecimal), lists (arrays), dicts (a structure inside a
structure), `null` (a null pointer), and references `R(kind, id, field)`,
in JSON `{"ref": [kind, id, field]}`. A field of a reference names a field
inside the object when upstream points there (`button.soundorg` points at
`R("sector", 12, "soundorg")`); for byte kinds (lumps, BLOCKMAP) it is a
byte offset (`demo_p` is `R("lump", 3, 313)`, DEMO3 at byte 313).

**Lists are sequences**, held in their head: the thinker list in the global
`p_think65.s:_g_thinkerclasscap`, a sector's things in `sector.thinglist`,
a block's chain in `blocklink.things`, a thing's sector nodes in
`mobj.touching_sectorlist`, a sector's nodes in `sector.touching_thinglist`,
`_s_sector_list` and the free nodes `SN_FREE` in their globals. Their links
(`snext`, `sprev`, `bnext`, `bprev`, `m_tnext` and the rest, the thinkers'
`prev` and `next`) are not fields: the writers make them from the
sequences. Order is state: `canonical.diff` compares lists as sequences.

**Identities** (`schema.KINDS`, `identity.py`):

| Kind | Identity |
| --- | --- |
| `sector`, `line`, `side`, `subsector`, `seg`, `node`, `blocklink`, `linebuf`, `button` | index |
| `mobj` | the **pool slot** (`_g_thingPool`), free slots included (field `free` from `TP_BITS`) |
| `zmobj` (a mobj in the zone, when the pool is full) | first those on the thinker list, in its order; then those **with no thinker** in the order the sectors' thing lists reach them (sector by sector), then the blocks' chains; any left (unreachable) in address order, counted in the report |
| `plat`, `door`, `floor`, `lightflash`, `strobe`, `glow`, `scroll` | rank among the thinkers of the kind |
| `removed` (a special whose function is `P_RemoveThinkerDelayed`) | rank among them |
| `secnode` | order of first reach: things' node lists (pool slots, then zone mobjs), sectors' node lists, `_s_sector_list`, the free list |
| `player`, `blockmap`, `reject` | 0 |
| `state` | its number (`states` of `info65.s`, `STATE_SIZE` a record) |
| `lump` | its number in the WAD directory (`fileinfo`) |
| `symbol` | `unit:label` of a labelled constant (message strings, the demo name) |
| `table` | the `MM_` name of a fixed table of `memmap.inc` (`LOGP` is `R("table", "MM_LOGTAB", 0)`) |

The reader numbers this way; the port reader numbers by its slots and then
`identity.renumber`s, so a port that keeps objects in other slots reads
back to the same state (tested).

**Thinker functions** come from a declared list (`schema.THINKER_FUNCTIONS`:
`P_MobjThinker`, `P_MobjBrainlessThinker`, `P_RemoveThingDelayed`,
`P_RemoveThinkerDelayed`, `T_PlatRaise`, `T_VerticalDoor`, `T_MoveFloor`,
`T_LightFlash`, `T_StrobeFlash`, `T_Glow`, `T_Scroll`), matched to their
exact address in the link map. Any other address is a problem, never the
nearest label (tested with a function one byte off). The function also
gives a thinker's kind.

**Field classes.** `state` fields are compared. `cache` fields are
canonical and round-tripped but a comparison may skip them: upstream caches
whose claim of not changing results routine tests check (`mobj.sightline`,
`CS_PREV1`, `CS_PREV2`, `CS_PREVR`, `LR_*`, `TP_HW`, `GW_TAG`, `G_ID`,
`line.gstamp`). `schema.compare_skips(structs, mode)` gives the skip lists:
`exact` none, `lockstep` the caches, `free` (free-running mode) also
`validcount` and the stamps and the renderer's `line.r_validcount` and
`r_flags` (verification section 4.4, NATIVE.md 15.1 row 4).

## The schema

Where each number comes from (`schema.py`):

- Offsets and record sizes: `offsets.inc` (`OFS_<S>_<FIELD>`, `SIZEOF_<S>`),
  parsed by `incfile.py` at run time. Every `OFS_` of the fourteen
  structures must have a type or be a declared alias (`ALIASES`), and the
  fields must tile the record: a new or moved field in upstream stops the
  bridge. The structures offsets.inc lacks (lightflash, strobe, glow,
  floor mover, scroller, wbstartstruct_t) come from their source files'
  `.equ` as the link map has them (our assembler's values). A test checks
  every value of `offsets.inc`, `memmap.inc` and `info.inc` read by our
  parser against the link map.
- Addresses: labels of `build/linkmap.json`, `MM_` of `memmap.inc`.
- Field types are the schema's only hand-written facts (`TYPES`,
  `LOCAL_STRUCTS`, `GLOBALS`), from Doom8088's C structs and the code that
  uses each field. No offset or address is typed in.

**Globals.** The game units are `p_*.s`, `g_game65.s` and `m_random65.s`.
`GLOBALS` types their canonical labels (73): the game's globals, the level
counts and table bases, `validcount`, the random indexes, the tic command
ring, the buttons, the switch tables, the list heads, and the caches. Every
other label of their data is excluded: `scratch` by default, `input` for
`G_BuildTiccmd`'s side (`gamekeydown`, `netcmd`, ...), `code patch` for
`PT_FLP`. `EXTERNAL_GLOBALS` adds `m_menu65.s:_g_menuactive`, which pauses
the tic. The player (`_g_player`) and the buttons are objects.

**The game-state regions** (`schema.regions`, plus the level's lumps per
dump):

| Region | Extent | Source |
| --- | --- | --- |
| Game units' data | every bss and data fragment of the game units (banks `$00`, `$02`, `$0D`) | link map |
| Zone | `$06:0000-$09:FFFF` | `MM_ZONE_FIRST`, `MM_ZONE_LAST` |
| Pool map | `$0A:8000-$0A:805F`: `TP_BITS` (64 B), `TP_MASK` (32 B) | `MM_TP_MAP`, `p_spawn65.s` |
| GSTAMP | `$22:8000-$22:8FFF` | `MM_GSTAMP` to `MM_VIEWSAVE` |
| Flood index | all of bank `$0C` | `MM_FL_IDX` ("all of it") |
| Flood entries | `$24:8000-$24:9FFF` | `MM_FL_ENT` to `MM_VIEWSAVE2` |
| Guard counts | `$0B:0000-$0B:7FF7` | `MM_GW_TAB`, `GW_MAXB` x 10 |
| Sight hints | `$0A:0000-$0A:7FFF` | `MM_SIGHTHINT`, 32 KB |
| Level tables | all of bank `$21` | `MM_B3F` |
| Respawn copy | `$0B:C000-$0B:FE09` | `RL_SECS` to `RL_TOTAL` of `p_setup65.s` |
| SEGS, NODES, BLOCKMAP, REJECT lumps | their extent in the level window | the WAD directory |

Each byte is claimed once (`Coverage`): by a field (`field:KIND`), a list
link (`list:NAME`), a table derived from the objects (`derived:TP_BITS`,
`TP_MASK`, `flood index`, `flood entries`), or an exclusion (`excl:NAME`).
The 24 exclusions and their reasons are `schema.EXCLUSIONS`; in short:

| Exclusion | What |
| --- | --- |
| `scratch`, `input`, `layout pad` | globals of the game units that are not state (above) |
| `trace scratch` | `IC_NEXT`-`IC_LAST` and `VT_P1`-`IV_ON` in bank `$21` (`p_trace65.s`) |
| `kindcache` | byte 11 of a mobj, upstream's kind cache |
| `dead link` | links of objects off that list (free slots, mobjs waiting for removal, `MF_NOSECTOR`, `MF_NOBLOCKMAP`, thinkerless) |
| `dead secnode` | fields of free nodes but `m_tnext` |
| `removed thinker` | the body of a special waiting for removal |
| `overread` | the byte after a glow (its last field, a byte, is read as a word and masked) |
| `zone header`, `zone slack`, `zone free` | the allocator's layout |
| `zone static`, `zone textures`, `zone cache` | renderer and loader blocks (by tag and user; the allocation sites are listed) |
| `sight hints`, `guard counts` | address- or block-keyed caches (routine tests of `P_CheckSight` and `P_PathTraverse` check them) |
| `level tables`, `respawn copy` | tables derived at a level load |
| `no line`, `no sector`, `flood room`, `tp unused` | parts of GSTAMP, FL_IDX, FL_ENT, TP_BITS the level does not use |

The "dead" exclusions (`schema.DEAD_EXCLUSIONS`) claim that no value lives
from one tic to the next; `checks.liveness` holds each dump's tic to it
(no byte of them read before written), and the sweep does the same for the
game units' data over 400 tics. Three reads are declared overreads
(`schema.OVERREADS`: `IF_P+4`, `IF_QS`, `SL_N`, each the high byte of a
16-bit load that the code masks off, with the instruction named).

## Upstream's layout (`upstream.py`)

**Reading** finds every object before decoding any:

1. The level tables from their globals (`_g_sectors` and `_g_numsectors`,
   ...), the segs' count from the subsectors, the pool, the blockmap
   chains, the buttons, the player; the resident lumps from the WAD
   directory (a lump whose start other lumps share is upstream's
   placeholder for a lump not in RAM and names nothing).
2. The zone: the blocks from the sentinel (`z_zone65.s`), checked to tile
   banks `$06-$09` with sound back links.
3. The thinker list from its head, a ring checked both ways; each
   thinker's kind from its function, a mobj's slot from its address.
4. Zone mobjs with no thinker: `PU_LEVEL` blocks with no user that no
   table starts and that look like a mobj; ranked as above.
5. Sector nodes by reach; each must sit in a pool block of `SN_POOL`
   nodes, and every node of a pool must be on a list.
6. Each zone block gets an owner (a table, a thinker, a node pool) or an
   exclusion by its tag and user; a block with neither is a problem.

Then an index of the objects' extents classifies each pointer: an object
(`R(kind, id)` or a field inside it), a state, a memmap table, a labelled
constant, a resident lump. A pointer that names nothing, names a kind the
field does not allow, points inside a field or has a pad byte other than 0
is reported (`raw_pointers`, `problems`) and never passes through as a
value. The lists are walked from their heads with their back links checked
(`cell` style for the sector and block chains: `sprev` holds the address of
the link that points here; `node` style for the node lists).

The flood lists (`P_InitFlood`, `p_pspr65.s`) are read per sector from
`FL_IDX` + the low word of its address: two sequences of sectors, `flood`
and `flood_sb` (lines with `ML_SOUNDBLOCK`). GSTAMP is `line.gstamp`.
`TP_BITS` is `mobj.free`; `TP_MASK` must be `1 << k`.

**Writing** (`Writer`) puts a canonical state at the reader's `Placement`
(the objects' addresses, the tables' bases, the flood lists' rooms) over a
base memory that keeps the excluded bytes. The round trip poisons every
claimed byte first, so a byte the writer does not produce shows. Limit of
v1: the state must have the objects the placement has (see open problems).
Before writing anything, `Writer.check` refuses (`Problem`) a state it
cannot hold: a global, an object or a field missing or not in the
placement and the schema, or a value out of its type (an integer out of
range, an array of another length, an undeclared thinker function, a
reference to nothing). `bridge.py upstream` prints the refusal and exits
1; without the check, a missing field would have kept the base's bytes
unnoticed.

## The port's layout (`layout.py`, `port.py`)

The manifest format, `bridge-port-layout 1` (JSON, `layout.py`'s docstring
is the reference):

    {"format": "bridge-port-layout 1", "name": "native-v1", "note": "...",
     "symbols": ["unit:label", ...], "tables": ["MM_...", ...],
     "lists": {"sector_things": {"elements": ["mobj", "zmobj"], "prev": true}},
     "pools": {"flood": {"capacity": 8192, "codes": [["sector", null]],
               "count": [...], "planes": [...]}},
     "kinds": {"mobj": {"capacity": 512, "why": "TP_MAX (p_spawn65.s)",
               "count": ["aux:48:B20A", "aux:48:B20B"], "leaves": [
       {"path": ["x"], "enc": {"enc": "int", "bytes": 4, "signed": true},
        "planes": ["aux:48:B40C", "aux:48:B60C", "aux:48:B80C", "aux:48:BA0C"]},
       {"path": ["subsector"], "enc": {"enc": "ref", "codes": [["subsector", null]],
        "offset": false}, "planes": ["aux:49:2000", "aux:49:2200", "aux:49:2400"]},
       {"path": ["touching_sectorlist"], "enc": {"enc": "list", "list": "thing_nodes",
        "codes": [["secnode", null]]}, "planes": [...], "when": ["free", 0]},
       {"path": ["@sector_things.next"], "enc": {"enc": "ref", "codes":
        [["mobj", null], ["zmobj", null]], "offset": false}, "planes": [...]},
       ...]}},
     "globals": {"leaves": [{"path": ["g_game65.s:_g_gameaction"], "enc":
       {"enc": "int", "bytes": 2, "signed": false}, "planes": ["main:1A80", "main:1A81"]}, ...]}}

A leaf is one value: its path into the canonical object, its encoding, the
addresses of its byte planes (byte k of object i at `planes[k] + i`), and
optionally `when` (it exists only when a field has a value). Encodings:
`int`, `ref` (tag, id low, id high, and offset planes when the targets
carry offsets; tag 0 is null, tag i the leaf's `codes[i - 1]`), `enum` (a
thinker function), `raw`, `list` (the head: a ref to the first element;
each element's `@LIST.next` and `@LIST.prev` leaves link the rest), `seq`
(start and length into a pool), `table` (a table base: no planes), `blob`
(a lump's bytes). Addresses are `main:XXXX` or `aux:BB:XXXX` (RamWorks bank
`BB` as `$C073` names it). The port reader and writer follow the manifest
and know nothing else, so a change of the port's layout is a change of its
manifest. The writer refuses (`PortError`) what the layout cannot hold:
a field, a global or a kind no leaf holds (checked before writing, so no
value is dropped), more objects than a capacity, identities that are not 0 to n - 1, a
reference its leaf cannot name, a value too wide.

**native-v1** (`layout.native_v1`, written by `bridge.py layout`): the
port has no game-state layout yet, so this is a first one, the structure of
arrays of verification section 4.3. Every field of every kind is byte
planes of `capacity` bytes, packed into RamWorks banks `$40-$4B`, pages
`$0200-$BFFF` (the RAMRD/RAMWRT window); the globals go to main
`$1A80-$1FFF` (MEMORY_MAP.md section 3.3, "hot game globals"). The lists
are linked through `@LIST.next`/`@LIST.prev` planes, the flood lists are a
pool of 8,192 entries. Capacities keep upstream's limits where it has one
(`TP_MAX` 512 mobjs, `SEC_MAX` 256 sectors, `SS_MAX` and `NODE_MAX` 2,048,
`MM_SEGVTX_MAX` 8,192 segs, 2,048 lines as GSTAMP has words for, 4
buttons); the rest are choices above E1's largest level (measured on the
dumps: 805 sides, 2,912 blocks, 1,719 line-table entries, 448 sector
nodes; 64 of each special, 64 zone mobjs, 1,024 sector nodes). It is a stand-in for the
manifest the port's build will write; the milestone 9 level store will size
its tables per level.

`port.through_a2vm` writes the port memory as an a2vm `--image`, has a2vm
load it and dump its RAM with a bus script (`dump FILE`), and reads the
snapshot back: the manifest's addresses checked against a2vm's own memory
map.

## Acceptance (NATIVE.md section 13, milestone 6 (2))

`python3 tools/bridge/bridge.py check --a2vm`, 2026-09-30, on the 35 dumps
and the 400-tic sweep:

| Check | Result |
| --- | --- |
| Dumps | 35: title 3, demo3 12 (to its last tic, leveltime 2,134), newgame 8, viewsize 3, tour 9 (E1M1-E1M9) |
| Raw pointers | **0** in every dump |
| Problems (unowned zone blocks, broken links, wrong pad bytes, undeclared functions, ...) | **0** |
| Bytes of the game-state regions | 513,751 to 559,191 a dump, **every one** a field (60-202 KB), a list link (8-25 KB), a derived table (1.3-3.6 KB) or a named exclusion (328-437 KB); 0 unclaimed, 0 claimed twice |
| Pool map, GSTAMP, flood tables | all claimed: `derived:TP_BITS`/`TP_MASK`, `line.gstamp`, `derived:flood index`/`entries`, and `tp unused`, `no line`, `no sector`, `flood room` |
| Liveness | 0 bytes of a dead exclusion read before written, in 35 tics and in the 400 of the sweep (3 declared overreads) |
| Writes outside the regions | all code (self-modified), the stack, direct pages, or data of units that are not game logic |
| Upstream -> canonical (JSON) -> upstream | **0 differing bytes**, 0 bytes changed outside the regions, every dump, all kinds and globals |
| Upstream -> canonical -> port (native-v1) -> canonical | **equal**, every dump; also through a2vm's memory |
| Identities | the reader's numbering is identity.py's (renumber changes nothing) |
| Level tables | equal across the dumps of one level load (22 pairs) |
| Kinds met | sector, line, side, subsector, seg, node, blocklink, blockmap, reject, linebuf, mobj, secnode, player, button, plat, door, floor, lightflash, strobe, glow, scroll; thinker functions all but `P_RemoveThinkerDelayed` |

No dump has a zone mobj (the pool never filled) or a special waiting for
its removal. `tests/test_bridge_dumps.py` makes them from a dump
(`synthetic.py`): a zone mobj on the thinker list, two with no thinker on
two sectors' lists (ranked by sector), one unreachable, a glow set to
`P_RemoveThinkerDelayed`. Each reads with no problem, round-trips byte-exact
and through the port. The tests also break states and expect the checks to
fail: a thinker function one byte off, a pointer into free zone memory, a
special unlinked from the list (its block then has no owner), a broken
`sprev`, a dead byte in a footprint.

**The prototype's weak points** (NATIVE.md section 11), fixed: mobj
identity is the pool slot; no raw pointer passes (a pointer that names
nothing is an error, not a value); zone mobjs with no thinker are found
from the zone blocks and ranked through the sector and block lists; thinker
functions come from the declared list by exact address.

## What the bridge found in upstream

- Bank `$21` is not only level tables: `p_trace65.s` keeps two working
  areas there (`IC_NEXT`-`IC_LAST`, the intercepts sorted by frac;
  `VT_P1`-`IV_ON`, the trace constants). The constancy check found them.
- Byte 11 of a mobj (the kind cache) is written in 21 of 35 tics, the sight
  hints in 26: both are caches the port need not keep.
- The tic reads, before writing, data of units that are not game logic:
  `_g_menuactive` (the pause, now canonical), `automapmode`, `pagetic`,
  the status bar's and HUD's counters, `texturetranslation` (which
  `P_UpdateSpecials` also writes), `R_PointInSubsector`'s grid (`sgrid*`)
  and its last-point cache (`PI_PREV*`), the sound channels (`CH_ORIGIN`
  holds mobj pointers), the intermission's `wi_stuff65.s` state. The
  renderer's direct page (`drawcol.s` `SF`, `SI`, `TI`) is read first too,
  by `STWC` of `p_map65.s`, which compares a byte before storing it: the
  result does not depend on it.
- Three scratch bytes are read first only as the high byte of a masked
  16-bit load (`schema.OVERREADS`), and the byte after a glow the same way
  (`overread`).

## Open problems

1. **Injection needs an allocator.** `Writer` puts a state at the base
   dump's placement; a state with objects the base lacks (a new special, a
   zone mobj, more node pools) or without some it has raises `Problem`.
   Injecting a port state into the reference (bisection, verification
   section 6.4) needs zone allocation as `z_zone65.s` does it; the pool
   mobjs need none (their slots are fixed). The flood lists keep upstream's
   rooms: a state whose lists changed length is refused.
2. **Scope of "game state".** The regions are the game units' data and the
   game's tables. State of other units that the tic reads (list above:
   automap, demo sequence, intermission, status bar, sound channels,
   `PI_PREV*`, `texturetranslation`) is outside the canonical model but
   `_g_menuactive`; milestones 10, 11 and S4 need parts of it (the
   intermission's state for tic sync across an intermission, the sound
   channels for `S_StartSound` events).
3. **Level inputs not decoded.** The subsector grid (`SGRIDn`, pointed to by
   `r_iigs65.s:sgrid`) and the level tables of bank `$21` are claimed as
   level data, not decoded; milestone 9 compares them per load.
4. **Unreachable zone mobjs** (no thinker, no sector, no block) take their
   rank from their addresses, which the port does not share. None occurred;
   the report counts them.
5. **Liveness is evidence, not proof.** The scratch claims hold on 435 tics
   of all four scripts and demo3; a rarer routine could read a scratch
   byte first. Every new dump or sweep re-checks them.
6. **Canonical `line.gstamp` and the guard.** GSTAMP is a cache keyed by
   `G_ID`; comparing it is only meaningful in lockstep. `GW_TAB` (the guard
   counts) is excluded as a cache keyed by block; the routine tests of
   `P_PathTraverse` (milestone 10) must confirm both.
7. **native-v1 is not the port's layout.** It checks the manifest machinery
   (and a2vm's map); the port's build must write its own manifest, and its
   tables will be sized per level (about 12 banks at these capacities).
