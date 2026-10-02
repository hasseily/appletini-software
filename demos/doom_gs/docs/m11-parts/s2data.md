# Milestone 11, part `s2data`: the 2D store

Part `s2data` of wave 3 ([`docs/SCREENS.md`](../SCREENS.md) 7.3): the
lumps the 2D screens draw, from `DOOM1.WAD` by our own code where the WAD
holds them and from the release image where only the release does,
placed in RamWorks banks with a handles table, written as the bank file
`GFX.1`. 2026-10-01. Follows SCREENS.md 0.1 F5, 4.5, 9 risks 3-4. Labels
as in `NATIVE.md`: [M] measured, [R file:line] read, [A] assumed.

## 1. What was built

| File | What |
| --- | --- |
| `tools/native/s2data.py` | The store: the lump set, each lump from its source (Doom patches parsed and written again by our own code, `STBAR` drawn into upstream's raw form, `FLOOR4_8`; the pictures, the palette records and the upstream-only patches from the release through `umodel.Release`, read only); the places; the handles table; the bank file `GFX.n`, the include, the manifest, the listing; the checks (sources, places, read-back, include). Its docstring is the reference |
| `src/native/m11/s2data.mk` | `make -f m11.mk part P=s2data` (or `make -f src/native/m11/s2data.mk`): builds and checks into `build/native/m11/s2data/`; `s2data-check`, `s2data-clean`. Adds `s2data` to `PARTS` and `M11_HOST`, so a plain `make -f m11.mk` builds the store too. Since the review of 2026-10-02 it also names `s2data.inc` and `s2data.json` as made by the store's run (and writes into `$(M11)/s2data` when `M11` is set), so `make -f m11.mk all` from an empty `build/native/m11` builds the store before the parts that read it (`tests/wip_test_m11_build.py`) |
| `tests/wip_test_m11_s2data.py` | 17 tests (below); the hand-made ones run without `build/` |

Build output (`build/native/m11/s2data/`, 368 KB): `GFX.1` (296,921 B: a
256-byte header and 10 segments), `s2data.inc`, `s2data.json`,
`s2data.lst`, `s2data.log`. The tool runs in about 0.15 s.

### 1.1 The lumps and their sources

The 2D lumps are every lump of the release's directory named `ST*`,
`M_*` or `WI*` outside the sprite and patch markers (`S_START`-`S_END`,
`P_START`-`P_END`: this leaves out the sprite `STIMA0` and the wall
patches `STEP*`), and `TITLEPIC`, `HELP2`, `FLOOR4_8`, `GSSTAT`, `GSOVL`:
**216 lumps, 295,585 B** [M]. The release's directory numbers them 148-354
(`HELP2` to `WIENTER`), 977 (`FLOOR4_8`), 997-1004 (`GSOVL`, `GSSTAT`,
the six upstream menu patches).

| Kind | Source | Lumps | Bytes [M] | How |
| --- | --- | ---: | ---: | --- |
| Doom patch | `DOOM1.WAD` | 202 | 156,088 | parsed (header, the 32-bit column offsets, each post's top, pad bytes and pixels) and written again (columns in order, a zero pad to 4 bytes, as the WAD lays every 2D patch out [M]); equal to the release's lump |
| Doom patch | release | 7 | 6,793 | `M_ARUN`, `M_GAMMA`, `M_MOUSE`, `M_MSPEED`, `M_MMOVE`, `M_CTRLS`: not in `DOOM1.WAD` (upstream's own menu patches [R `m_menu65.s:194-210`]); `WIURH0`: **upstream recoloured it** (the release's lump has `DOOM1.WAD`'s header and posts, but 290 of its 1,080 bytes, all pixels, differ [M]). Declared in `RELEASE_PATCHES` with the reason; the check verifies the WAD's form still differs and the posts are the same |
| raw | `DOOM1.WAD` | 1 | 10,240 | `STBAR`: the WAD's 320 x 32 patch drawn row by row (every pixel covered), equal to the release's raw lump (`V_DrawRaw`'s [R `st_stuff65.s:749-755`]) |
| flat | `DOOM1.WAD` | 1 | 4,096 | `FLOOR4_8`, equal to the release's |
| picture | release | 3 | 110,592 | `TITLEPIC` (title set), `HELP2`, `WIMAP0` (intermission set): 36,864 B each, read as their parts (pixels 0-31,999, SCBs 32,000-32,199, a 56-byte pad, the 16 palettes 32,256-32,767, the pair tables 32,768-36,863 [R `i_viigs65.s:60-64`]) and checked part by part |
| palette record | release | 2 | 7,776 | `GSSTAT` (5,664 B), `GSOVL` (2,112 B), resident |

The release's lumps are read through `umodel.Release`: a resident lump
from its memory (`resident_bytes`), any other from the first set whose
entries place it, the set's units decoded into its window banks (keyed by
the entry's bank byte, the key its lump entries use; no 2D lump crosses
a window bank [M]). This reading is checked against `DOOM1.WAD` where
both hold a lump: 31 of the 32 intermission patches of set 11 and
`FLOOR4_8` read from the units equal the WAD's; `WIURH0` alone differs
(above).

### 1.2 The interface

**Handles.** A lump's handle is its rank among the 2D lumps in the
release's directory (0-215), so the runs upstream indexes by lump number
plus a digit stay consecutive (`STTNUM0`-`9`, `WINUM0`-`9`, `WILV00`-`08`,
`STKEYS0`-`2` are tested). `s2data.handles_of(rel)` maps upstream's lump
numbers to handles, for the injection (request S2DATA-4).

**The handles table `GFXDIR`** at `GFX0` (bank 109) `$0200`, 1,080 B:
five arrays of `GFX_NH` (216) bytes, indexed by the handle (one index
register): `GFXDIR_BK` the bank, `GFXDIR_LO`/`GFXDIR_HI` the address,
`GFXDIR_SZLO`/`GFXDIR_SZHI` the length.

**`s2data.inc`** (ca65): `GFX_NH`, `GFXDIR_BANK`, `GFXDIR`, the five
arrays' addresses, `GFX_FETCH` (1,024: the largest fetch buffer the
contracts use), `PIC_SIZE`, `PIC_SCB`, `PIC_PALS`, `PIC_PAIRS`, and for
every lump `H_name` (its handle), `HBANK_name`, `HADDR_name` (its place),
so a drawer with a fixed lump (`STBAR`, `GSSTAT`, a picture) needs no
table lookup. No name of the include meets a symbol of `src/native` or
`s2.inc` [M: grep].

**`s2data.json`**: every lump's handle, lump number, kind, source, bank,
address, size and SHA-256; the table's place; the fetch size.

### 1.3 The places

In order (`s2data.bins()`, from `s2layout`'s constants where it has them):
`GFX0`-`GFX3` whole (`$0200-$BFFF`), then the free parts of banks 103-108
(SCREENS.md 4.5): `S2SFX` past `SFX.1`'s room, `S2CODE0` and `S2CODE1`
below `MATHW` (4.5's "2D data below `$6000`"), `S2VIEW` around the menu's
saved screen (4.5's "2D data around it"), `S2CODE0` and `S2CODE1` above
their image's room, `S2STATE` past its blocks; bank 125 only when those
do not hold the store (reported as over the budget). `S2PAL` (106) is
part `s2pal`'s and gets nothing. The table goes first, then the pictures
(each whole in one of `GFX0`-`GFX3`), then every other lump from the
largest, each at the first place it fits, packed from the place's start
(no gaps). Every place is checked against what else uses its bank
(`SFX.1`, the saved screen, `MATHW` and the image's room, the state
blocks, `S2PAL`).

The contracts (`docs/m11-parts/s2draw.md` 1.1, SCREENS.md 4.5), each
checked on every build: every lump inside its bank's `$0200-$BFFF`; a
patch's every column at most 256 bytes (the longest are 65 B) and every
column starting at least `GFX_FETCH` (1,024) before `$C000`, which the
placement also enforces; a raw lump whole rows of 320 bytes and inside a
bank (`STBAR` 32 rows; no full-screen raw lump exists); a picture
36,864 B.

## 2. Checkpoint

Commands, from `demos/doom_gs`:

```
make -C src/native -f m11.mk part P=s2data           # no warning
make -f src/native/m11/s2data.mk s2data-check        # the files again
python3 tools/native/s2data.py --check --report
python3 tools/testpar.py tests/wip_test_m11_s2data.py
```

Results [M, 2026-10-01]: the build and `--check` print `sources OK`,
`places OK`, `read-back OK`, `include OK` and "budget ... met";
`wip_test_m11_s2data` 17 tests OK in 0.6 s, also on Python 3.9.6 with
`-W error::ResourceWarning`; `make -C src/native -f m11.mk all` builds
with no warning. `tests/test_sound_*` unchanged and green (7 modules, 152
tests), `wip_test_m11_s2lay` green (25), run together at 2 jobs.

| Check | Result |
| --- | --- |
| Every lump equal to the release's or taken from it | 216 of 216: the 204 made from `DOOM1.WAD` equal the release's lumps byte for byte; the 12 taken from the release equal it (the pictures part by part); the set is the release's 2D lumps in directory order |
| The store fits its banks | Yes, without bank 125: the table below |
| Read-back | `GFX.1` parsed (`lstore.read_bank_file`), its 10 segments copied into banks, the handles table read from `GFX0` `$0200`, every lump read at the table's bank, address and length: 216 of 216 equal to the release's lump |
| The include | every `H_`, `HBANK_`, `HADDR_` equal to the table read back; ca65 assembles it with no message |
| The contracts | 0 problems (above) |

### 2.1 The tests (`tests/wip_test_m11_s2data.py`)

Without `build/`: a hand-made patch written again equals its bytes (the
offsets low byte first); a gap or a tail refused; a raw from a patch, a
pixel not covered refused; the places of four hand-made lumps in two
small bins, exactly, the last to bank 125; the handles table's arrays; a
bank file read back; `check_places` naming a lump across a bank's end
and `bank_files` refusing it; the fetch contract one byte either side;
the bins against the other users of their banks. With `build/`: the tool
in a temporary directory (bounded run) passes its four checks and meets
the budget; the checkpoint on its files; the lump set, kinds and
sources, the handles' runs; the budget (no bank 125, no `S2PAL`, the
pictures in `GFX0`-`GFX3`, the bytes used equal the lumps and the table,
at most 49 segments); `SFX.1` and `SFXAUTO.1` (part `fxconv`'s, when
built) within `SFX.1`'s room; the include assembled; the tree's build
passing; the planted bugs.

## 3. Planted bugs (each in a scratch copy of `s2data.py`, built with the copy, checked by the tree's checks)

| Bug | Caught by | The first failure |
| --- | --- | --- |
| A patch's column offsets byte-swapped (`'>I'` for `'<I'` in `encode_patch`) | sources (and read-back) | "STGNUM0 (patch): 68 bytes, the release's 68; the first difference at byte 8" |
| A lump placed across a bank end (`fits` testing the start, not the end) | places (and the bank file writer) | "TITLEPIC at bank 109 $9638-$12637: outside $0200-$BFFF (across the bank's end)" |
| A picture's palettes from the wrong record (`HELP2`'s from `WIMAP0`'s parts, `TITLEPIC`'s from `HELP2`'s) | sources (and read-back) | "HELP2: the palettes ($7E00-$7FFF) differ from the release's" |

## 4. Sizes against the budget

Budget: the store in `GFX0`-`GFX3` and the free parts of 103-108, bank
125 next if it does not fit. **Met; bank 125 not used.** [M:
`s2data.lst`]

| Bank | Place | Room | Used | Free |
| ---: | --- | --- | ---: | ---: |
| 109 | `GFX0` (the table, `HELP2`, `STBAR`, patches) | `$0200-$BFFF` | 48,184 | 456 |
| 110 | `GFX1` (`TITLEPIC`, `FLOOR4_8`, patches) | `$0200-$BFFF` | 47,732 | 908 |
| 114 | `GFX2` (`WIMAP0`, `GSSTAT`, patches) | `$0200-$BFFF` | 47,588 | 1,052 |
| 115 | `GFX3` (patches) | `$0200-$BFFF` | 47,592 | 1,048 |
| 103 | `S2SFX` past `SFX.1`'s room | `$4000-$BFFF` | 31,740 | 1,028 |
| 107 | `S2CODE0` below `MATHW` | `$0200-$5FFF` | 24,062 | 2 |
| 108 | `S2CODE1` below `MATHW` | `$0200-$5FFF` | 24,060 | 4 |
| 105 | `S2VIEW` below the saved screen | `$0200-$1FFF` | 7,680 | 0 |
| 105 | `S2VIEW` above the saved screen | `$A000-$BFFF` | 7,175 | 1,017 |
| 107 | `S2CODE0` above `P2DW`'s room | `$8300-$BFFF` | 10,852 | 4,764 |
| 108 | `S2CODE1` above `MENUW`'s room | `$A800-$BFFF` | 0 | 6,144 |
| 104 | `S2STATE` past its blocks | `$6200-$BFFF` | 0 | 24,064 |
| | **Total** | | **296,665** (295,585 + the 1,080 B table) | 40,487 |

Against SCREENS.md 4.5's estimate ("about 300 KB [M] in about 10 banks
... the free parts of 103-108 (about 100 KB [A]) take the rest"): 296,665
B; `GFX0`-`GFX3` take 191,096 B (the table included), the free parts of
103, 105 and 107-108 105,569 B; 30,208 B of the free parts stay free (all of 104's and 108's
top). The pictures are the constraint: a picture is 36,864 B whole, so
three of `GFX0`-`GFX3` hold one each and the patches fill around them.

Time: the part took about 1.5 hours.

## 5. Requests (for the integrator; the stand-ins are marked `STAND-IN`)

### S2DATA-1. `tools/native/s2layout.py`: the store's neighbours as constants

**Evidence.** `s2data.bins()` takes every place from `s2layout` (the
`GFX` banks, `MATHW_LO`, each image's room through `image_banks()`, the
`S2STATE` fields) but two, which `s2layout` does not hold: `SFX.1`'s room
in bank 103 and the menu's saved screen in `S2VIEW` (105). **Stand-in.**
`s2data.py`'s `SFX_ROOM = (0x0200, 0x4000)` (`SFX.1` 11,385 B [M:
`fxconv.md`], its budget "about 15 KB, one bank") and `MENU_SAVE =
(0x2000, 0xA000)` (SCREENS.md 4.5, 1.5.3), marked `STAND-IN (request
S2DATA-1)`. **What.** Add to `s2layout.py` after `S2CODE3_5`:

```python
# bank 103: SFX.1 at $0200 (part fxconv: 11,385 B; its room about 15 KB);
# the 2D store takes the rest (part s2data)
SFX_ROOM = (0x0200, 0x4000)
# bank 105: the menu's saved screen (SCREENS.md 1.5.3); the 2D store
# takes $0200-$1FFF and $A000-$BFFF around it (part s2data)
S2VIEW_SAVE = (0x2000, 0xA000)
# the 2D store's handles table (part s2data)
GFXDIR_PLACE = (GFX[0], 0x0200)
```

then `s2data.py` uses `L.SFX_ROOM`, `L.S2VIEW_SAVE` (its two constants
go), and `fxconv`'s test may check `SFX.1` against `L.SFX_ROOM` too.

### S2DATA-2. `docs/SCREENS.md` 4.5, 0.1 F5 and risks 3-4: the store as built

1. 4.5's table, row 103: after "`SFX.1`: 11,385 B [M: ...]" add "; the
   2D store at `$4000-$BFFF` (31,740 B [M: `docs/m11-parts/s2data.md`])".
2. Row 105: replace "2D data around it" with "the 2D store at
   `$0200-$1FFF` and `$A000-$BFFF` (14,855 B [M: `s2data.md`])".
3. Row 106: replace "`TINTPAL`, the 16 nibble tables `S2NIB`, `GRAYMAP`,
   `GSSTAT`, `GSOVL`" with "`TINTPAL`, the 16 nibble tables `S2NIB`,
   `GRAYMAP` (`GSSTAT`, `GSOVL` are in the 2D store, by handle: request
   S2DATA-3)".
4. Row 107, 108: replace "2D data below `$6000`" with "the 2D store at
   `$0200-$5FFF` and, in 107, above `P2DW`'s room at `$8300-$BFFF`
   (58,974 B [M: `s2data.md`])".
5. Row 109-115: replace "(about 300 KB with the pictures [M: this design,
   0.1 F5])" with "(216 lumps, 295,585 B and the handles table, 1,080 B,
   at `GFX0` `$0200` [M: `docs/m11-parts/s2data.md`]; 191,096 B with the
   table in these four banks, three of them holding one picture each)" and the label `A` with `M`.
6. The paragraph after the table: replace "The 2D store needs about 300
   KB [M] in about 10 banks of 48,640 B; the free parts of 103-108 (about
   100 KB [A]) take the rest." with "The 2D store is 296,665 B [M:
   `s2data.md`]: `GFX0`-`GFX3` take 191,096 B, the free parts of 103, 105,
   107 and 108 105,569 B; 104's free part and 108's top stay free (30,208
   B)." and "part `s2data` measures, and if the store does not fit, bank
   125 is next (risk 3)" with "part `s2data` measured it: bank 125 is not
   needed (risk 3)".
7. 0.1 F5, column "Fact", after "the rest are Doom patches and the
   `STBAR` raw lump": add "(but `WIURH0`, which upstream recoloured: 290
   pixel bytes differ from `DOOM1.WAD`'s [M: `s2data.md`], and the menu
   patches `M_ARUN`, `M_GAMMA`, `M_MOUSE`, `M_MSPEED`, `M_MMOVE`, `M_CTRLS`,
   upstream's own)"; column "Consequence": after "the pictures and the
   `GS*` records from the release image" add "with those seven patches".
8. Risk 3, column "What the builders do": replace "`s2data` measures in
   wave 3; the store can drop ..." with "Measured in wave 3: 296,665 B,
   no bank 125, 30,208 B of the free parts left (`s2data.md` 4); the
   store can drop ..." Risk 4: append "; `s2data.py` names each lump's
   source (`s2data.json`), and `RELEASE_PATCHES` the patches the release
   changed".

### S2DATA-3. `GSSTAT`, `GSOVL` in the 2D store (with part `s2pal`)

**Evidence.** SCREENS.md 4.5 lists them in `S2PAL` (106), but the part's
files give them to the store, and `S2PAL`'s layout is part `s2pal`'s,
built in this wave at the same time. **What.** They are in the store:
`GSSTAT` at bank 114 `$9200` (`H_GSSTAT` 209), `GSOVL` at bank 103
`$A590` (`H_GSOVL` 208); `PALW` (`s2pal`) reads them there by
`HBANK_GSSTAT`/`HADDR_GSSTAT` (`s2data.inc`), or copies them into `S2PAL`
if it wants them beside `TINTPAL`. If `s2pal` built on 4.5's text with
them in `S2PAL`, the integrator chooses one place; the store drops the
two from `RECORDS` (7,776 B) with no other change if `S2PAL` keeps them.

### S2DATA-4. The injection of upstream's lump numbers (part `s2cap`'s `s2state.py`, `s2layout`'s field map)

**Evidence.** The field map copies `wi_stuff65.s:lumps` (`W_LUMPS`, 66
B, 33 words), `f_finale65.s:help2num` and `backgroundnum` (`F_HELP2`,
`F_BACKGROUND`, words) as upstream's lump numbers; upstream's code uses
them as lump numbers [R `wi_stuff65.s:84`, `:178-187`; `f_finale65.s:31-32`,
`:157-159`], natively they are 2D handles (SCREENS.md 6.2: "a patch
pointer as a 2D store handle"). **What.** An encoding `gfx` (a lump
number to its handle, one byte; `$FFFF` stays `$FF`) by
`s2data.handles_of(umodel.Release())`, for those three fields
(`W_LUMPS` 33 bytes); the native screens index `GFXDIR` with them.

### S2DATA-5. `docs/MEMORY_MAP.md` (the final integration, SCREENS.md 8.4)

In the RamWorks bank list: banks 109, 110, 114, 115 `GFX0`-`GFX3`, the 2D
store (`GFX.1`; the handles table at 109 `$0200`); and the store's parts
of 103 (`$4000-$BFFF`), 105 (`$0200-$1FFF`, `$A000-$BFFF`), 107
(`$0200-$5FFF`, `$8300-$BFFF`) and 108 (`$0200-$5FFF`).

### S2DATA-6. The boot disk (part `plboot`)

`GFX.1` goes on `DOOM.hdv` with the other bank files and into
`CRCLIST` (SCREENS.md 2.5 step 2 already names `GFX.n`); it is
`build/native/m11/s2data/GFX.1`, made by `make -f m11.mk` (`M11_HOST`).
Its segments meet `SFX.1` and the code banks' files in no byte (the
check against `reserved()`), so the load order of the files does not
matter.

## 6. Open problems

- The places leave little room: `GFX0`-`GFX3` have 456-1,052 B free,
  107 below `MATHW` 2 B. A lump added (or a bank part taken) moves the
  packing; the checks fail at once on any overlap with `s2layout`'s
  places, and 30,208 B remain in 104 and 108's top before bank 125.
- `P2DW`'s room growing (risk 12) would meet the store's 10,852 B above
  it in bank 107; `s2data`'s places follow `s2layout`'s rooms at every
  build (the next build moves the lumps to 104), so nothing silent.
- The two stand-ins of S2DATA-1 and the `GSSTAT`/`GSOVL` place
  (S2DATA-3) wait for the integrator.
- Not compared with a ref816 run: the store is data, checked against the
  release's own lumps; the drawers that read it are compared with ref816
  by their parts.

## 7. The wave 3 integration (2026-10-01)

What the integrator did with each request (`docs/SCREENS.md` 8.7, "Wave
3 as integrated"):

| Request | Outcome |
| --- | --- |
| S2DATA-1 | Applied: `s2layout.py` `SFX_ROOM`, `S2VIEW_SAVE`, `GFXDIR_PLACE` (checked in `$0200-$BFFF`); `s2data.py`'s `SFX_ROOM` and `MENU_SAVE` are now `L.SFX_ROOM` and `L.S2VIEW_SAVE` (the same values) |
| S2DATA-3 | **Decided for `S2PAL`** (SCREENS.md 4.5 and part `s2pal`'s `PALW`, built at the same time, both read them there; S2PAL-1 asks the store to put them there): `GSSTAT` and `GSOVL` stay lumps of the store with their handles (208, 209), but `place()` puts them at `s2layout.S2PAL_AT['S2P_GSSTAT']` (`$5800`) and `['S2P_GSOVL']` (`$6E20`) in bank 106 (`FIXED`, `fixed_bins()`), outside the packing; `reserved()` keeps the rest of `S2PAL` for part `s2pal`; `check_places` fails a record not at its place. `wip_test_m11_s2data`: `test_the_bins_avoid_the_other_users` checks the two places against the other users, `test_the_budget` that only these two lumps are in `S2PAL`, at their places. The packing changed (GFX2 1,016 B and GFX3 1,036 B free, 107's top 12,560 B free) |
| S2DATA-2 | Applied with S2DATA-3's numbers: SCREENS.md 4.5 (rows 103, 105, 106, 107-108, 109-115 and the paragraph), 0.1 F5, risks 3 and 4 |
| S2DATA-4 | Applied: the field map's `wi_stuff65.s:lumps` (`W_LUMPS`, now 33 B), `help2num` and `backgroundnum` (`F_HELP2`, `F_BACKGROUND`, 1 B each) take the encoding `gfx` (`s2state.gfx_handles()`: `handles_of(umodel.Release())`, `$FFFF` as `$FF`; a lump number that is no 2D lump is unfit). Before applying it every case of the eleven runs was scanned: every value of the three fields is a 2D lump [M], so no case becomes unfit |
| S2DATA-5 | Recorded in `design.md` R2 item 4 for the final integrator (with bank 106's two records) |
| S2DATA-6 | Nothing to apply; kept for `plboot`: `GFX.1` now also writes bank 106 (`$5800-$765F`), which `PALW`'s TINTPAL and `S2NIB` places do not meet |

Results after the integration [M]: `python3 tools/native/s2data.py
--check --report`: sources, places, read-back, include OK; the budget met
without bank 125.

| Bank | Place | Used | Free |
| ---: | --- | ---: | ---: |
| 109 | `GFX0` | 48,184 | 456 |
| 110 | `GFX1` | 47,732 | 908 |
| 114 | `GFX2` | 47,624 | 1,016 |
| 115 | `GFX3` | 47,604 | 1,036 |
| 103 | `S2SFX` past `SFX.1` | 31,748 | 1,020 |
| 107 | `S2CODE0` below `MATHW` | 24,062 | 2 |
| 108 | `S2CODE1` below `MATHW` | 24,040 | 24 |
| 105 | `S2VIEW` below the saved screen | 7,679 | 1 |
| 105 | `S2VIEW` above the saved screen | 7,160 | 1,032 |
| 107 | `S2CODE0` above `P2DW`'s room | 3,056 | 12,560 |
| 108 | `S2CODE1` above `MENUW`'s room | 0 | 6,144 |
| 104 | `S2STATE` past its blocks | 0 | 24,064 |
| 106 | `GSSTAT`, `GSOVL` at `S2PAL`'s places | 7,776 | 0 |
| | **Total** | **296,665** | 48,263 |
