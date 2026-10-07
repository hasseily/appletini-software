# Speed: where the frame's time goes and how it is kept short

Nothing here changes what the game shows or does. Every technique below
changes only time: where code lives, how bytes are copied, and which pages
are loaded again. The frame's steps are [`PLAY.md`](PLAY.md)'s; the
places are [`MEMORY_MAP.md`](MEMORY_MAP.md)'s; code paging itself is
[`GAME.md`](GAME.md)'s.

## 1. The figures

The menu's OPTIONS, BENCHMARK plays demo3 (E1M7) at the normal tic rate
and shows FPS = 35000 × frames drawn / realtics, then five rows: each
phase's mean time a frame in ms (section 2). Upstream's rule caps a frame
at `MAXTICS` (4) tics, so a frame longer than 114 ms slows the game below
35 tics a second.

**On the card** (firmware F1.2.2, PAL, the Disk II's acceleration off,
the memory API present; the disk's images are the shipped disk's):

| FPS | TIC | 3D | MASK | DRAW | REST | N |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **6.343** | 93.1 | 18.1 | 11.7 | 31.3 | 3.5 | 547 |

**On a2vm** (`tools/a2vm`, profile `f122-nod2`: F1.2.2 with the Disk II
inactive, the card's setting), the same images:

| Scene | Frame | FPS |
| --- | ---: | ---: |
| The BENCHMARK (`TIC 89.4  3D 18.0  MASK 11.6  DRAW 31.3  REST 3.3`, N 551) | 153.6 ms | 6.519 |
| E1M1's start, standing still | 58.9 ms (median 58.2, max 78.0) | 16.97 |
| demo3, gametics 1052-1796 | 143.7 ms (median 149.4, max 259.4) | 6.96 |
| The BENCHMARK without the memory API (`TIC 136.8  3D 22.0  MASK 13.8  DRAW 31.4  REST 5.0`) | 208.9 ms | 4.794 |

Standing still runs at real time (35 tics a second). demo3's fights run
4 tics a frame, about 25 tics a second.

The model and the card: a2vm's `f122-nod2` cost model was fitted to the
card's own timings of the basic operations, and it gave earlier disks'
benchmarks within 0.03 FPS of the card. On this disk the card is 2.7%
slower, nearly all in TIC (+3.7 ms). The gap grows with the memory-API
requests (52 a frame here). Fitted through two disks, a request costs the
card about 27 µs and 0.022 µs a byte more than the model's 46 µs and
0.038 µs a byte. That is a fit through two points, not a measurement.

**The machine's setting matters.** With the card's virtual Disk II
active, the Disk II replays the 65C02 cycles each TURBO step stands for,
so every dummy read the TURBO core omits still costs time: code runs at
about 67 MHz of 65C02 cycles instead of 110. The benchmark is about 20%
slower that way (on F1.2.1: 3.015 FPS with it, 3.610 without). Set
`vtw.disk2.acceleration.disabled=on` in the Doom profile
([`PLAY.md`](PLAY.md), the machine).

## 2. Where the time goes

The benchmark page's rows (how they are measured: [`PLAY.md`](PLAY.md),
the benchmark's rows):

| Row | What runs | Card, ms | Share |
| --- | --- | ---: | ---: |
| TIC | `K_TIC`: the tic image and the walk's planes back into W, the brain, the frame's tics (game code, its group loads, the object API's far windows), the next step list | 93.1 | 59% |
| 3D | the front end's load and `nr_frame` (BSP walk, walls, planes, records) | 18.1 | 11% |
| MASK | the masked image's load, `nm_masked`, `nm_bkload`, `nb_frame`'s bucket pass | 11.7 | 7% |
| DRAW | `nb_frame`'s replays, the SHR drain included | 31.3 | 20% |
| REST | `PALW` at a level's first frame, `P2DW`'s load, `s2_frame` | 3.5 | 2% |

- **TIC** is mostly RamWorks work: group loads into W, the object API's
  far windows (`far_get`, `far_put`), and soft-switch windows. Game logic
  itself is a small part.
- **DRAW** is bound by the SHR drain: about one Apple cycle a screen
  byte. Only writing fewer screen bytes makes it shorter.
- **3D** and **MASK** are the CPU in W and the card.

## 3. Code paging

The tic phase's code does not fit in W. The tic image holds W
`$6000-$65FF` (the math), a core `$6600-$99FF` (13,312 B), two 2 KB slots
(`$9E00-$A5FF`, `$A600-$ADFF`), and the walk's planes `$B400-$BFFF`. The
rest of the game code is in groups of at most 2,048 B in RamWorks
(`GCODE0`, `GCODE1`, banks 72-73). `gcall.s`'s `FCALL` (`fc_call`)
loads a callee's group into its slot when the slot holds another, and
restores the caller's on return.

- **Lazy restore.** `fc_go` pushes the slot's innermost needed group;
  `fc_ret` reloads only that, so a return reloads a group only when an
  active caller needs it (`SLOT_NEED`).
- **Exact lengths.** The group directory holds each group's whole pages
  and the bytes of its last page (`grp_tail`); a load copies only those.
- **Resident glue.** The HUD's ticker (`s2t_hu.s`) is in the core
  (`play.mk` assembles the tic image with `PLAY_TIC`), so no tic loads
  `DLG_H` for it.
- **Fewer pages at `K_TIC`.** After `P2DW` the tic image's W pages are
  already in place (the same `MATHW` bytes): the core loads from page
  `$66`. The walk's planes come in and go out only below the highest mobj
  slot used (`G_MOHWM`). `playdisk.py` checks the shared bytes
  (`shared_w_problems`).

## 4. The frame slots

Main `$2000-$5FFF` holds colormaps A and B of light levels 0-31, which
only the replay reads. During the tic phase it holds code instead: the
**frame slots**. Each pinned group has a place of its own there: one
group a slot, at most 15 slots (the restore's one request takes 15
descriptors; the runtime's state has room for 16), 64 pages, packed
largest first, none across `$4000`. Its first call in a frame loads it by one memory-API
PRIVATE request (a CPU store there would be a video write). At the
brain's end (`dl_brain.s`, before the list runs) `fs_restore` copies each
loaded slot's colormap bytes back from the level's copy in `LVC`, in one
request with a descriptor a slot. Every path from the tic phase to a
replay passes there.

- `SLOT_GRP` holds 19 slots (0-2 and 16 frame slots), `SLOT_NEED` 18,
  then `FS_DIRTY`; `K_TIC` resets them.
- A routine the tic code stores into may not be pinned (rule 3 of
  [`MEMORY_MAP.md`](MEMORY_MAP.md)). `playdisk.py` checks that the tic
  link has no absolute store into `$2000-$5FFF` and that each pinned
  group stays in its slot (`frame_slot_problems`). Indirect stores are
  not checked statically: `recursiveSound`, which writes its work stack
  through a pointer, is kept out by the placement.
- The frame slots are full: 11 groups in 64 of 64 pages.
- Every loaded slot is restored whole, so a pinned group pays its pages
  twice a frame. Pinning pays only for a group a frame would otherwise
  load about twice or more.

## 5. The memory API's copies

On F1.2.2 the memory API's copies run on the FPGA's copy engine: about 46
µs a request and 0.038 µs a byte, where the CPU's copy from RamWorks into
main costs about 7.8 µs and 0.231 µs a byte. A request wins above about
220 B. Every bulk copy of a frame goes that way:

| Copy | Source → destination | How |
| --- | --- | --- |
| a group into a W slot or a frame slot (`gr_load`) | `GCODE0-1` → `$9E00-$ADFF` or `$2000-$5FFF` | one request (`am_one`), the group's length |
| the frame slots' colormaps (`fs_restore`) | `LVC` → `$2000-$5FFF` | one request, a descriptor a loaded slot (at most 15: `glayout.AM_MAX`) |
| `K_TIC`: the core, the planes | `GCODE0`, `MOBJP` → W | one request each (`am_runs`), a descriptor a page run |
| the planes back (`planes_out`) | W → `MOBJP` | one request, 4 descriptors |
| every `K_LOAD`: the front end (`img_wload`, 74 pages), the masked image (`img_mload`, 41), `P2DW` (31), the menu, the automap, the intermission, the finale, `PALW`, `OVLW`, the load image, `DLINIT` | their banks → W | one request each, a descriptor a run |

The transport is in the main card (`gcall.s` segment `AMEMLC`, bank 1
`$DB5C-$DBFF`, 164 of 164 B), because a load that replaces W or the core
must not overwrite the code waiting for it. Each request masks interrupts
from its build to its end; the longest (the front end's 18.9 KB, about
0.8 ms) is far under a VBL.

Requests a frame on a2vm `f122-nod2` (requests, descriptors, pages, ms):

| Kind | Benchmark | Still | demo3 |
| --- | --- | --- | --- |
| W slot | 38.39, 38.39, 212.6, 3.91 | 9.13, 9.13, 56.8, 0.99 | 30.75, 30.75, 171.3, 3.14 |
| frame slot | 6.95, 6.95, 42.7, 0.75 | 2.00, 2.00, 14.2, 0.23 | 7.03, 7.03, 42.8, 0.77 |
| restore | 1, 6.95, 42.7, 0.52 | 1, 2.00, 14.2, 0.20 | 1, 7.03, 42.8, 0.52 |
| planes out | 1, 4, 8.0, 0.14 | 1, 4, 4.0, 0.11 | 1, 4, 8.0, 0.14 |
| `K_TIC` core | 1, 1, 52.0, 0.57 | 1, 1, 52.0, 0.56 | 1, 1, 52.0, 0.57 |
| `K_TIC` planes | 1, 4, 8.0, 0.15 | 1, 4, 4.0, 0.11 | 1, 4, 8.0, 0.15 |
| `K_LOAD` (front end, masked image, `P2DW`) | 3, 5, 146.0, 1.61 | 3, 5, 146.0, 1.60 | 3, 5, 146.0, 1.61 |
| **All** | **52.34, 66.30, 512.1, 7.65** | 18.13, 27.13, 291.1, 3.80 | 44.78, 58.80, 471.0, 6.90 |

A W slot's request costs about 102 µs (5.5 pages on average). The CPU
still makes the copies under a request's break-even and those that write
the screen (rule 4 of [`MEMORY_MAP.md`](MEMORY_MAP.md)): the replay's
drain and texel gather, `s2_frame`'s status bar and HUD, the bucket
pass's chunks, the object API's `far_get` and `far_put`. `nm_bkload`
(0.21 ms) and the bucket pass's `park` and `back` (0.11 ms) also stay CPU
copies: they are the render build's code, which has no transport.

Without the memory API, `DOOM.SYSTEM` patches the transport with a CPU
version that makes the same copies at the same points
([`PLAY.md`](PLAY.md), the machine variants). They cost about 60 ms a
frame on the benchmark against 7.65: the groups into W 17.3 ms, the frame
slots' loads and restores 29.4 ms (every CPU store into `$2000-$5FFF` is
a video write), `K_TIC`'s loads 3.6 ms, the images 8.8 ms.

## 6. The placement

`tools/native/gplace-f122.json` says which routine goes into which group,
which group into which slot, and what stays in the core. `build.sh` copies
it to `build/native/game/shared/placement.json`, which the tic link
(`play.mk`, `glayout.py`'s generated `gplace.inc`) follows. It is fixed
data: the search that made it is not part of this tree.

- 42 groups; 11 in frame slots (64 of 64 pages); the core holds 3,776 of
  its 3,793 B of placed routines beside its fixed code (play build 9,318
  B).
- A group stays within 2,048 B less a 96 B margin; the core keeps a 16 B
  margin.
- Its cost model is F1.2.2's: 9.84 µs a page, 46.3 µs a request, 3.5 µs
  a further descriptor, 5 µs a cross-group call, the lazy restore. It was
  trained on recorded call traces of standing still, walking, demo3 and a
  lockstep demo3 run, and checked on fight, demo3b and a second lockstep
  run that it was not trained on. The model's cost a tic: still 0.64 ms,
  demo3 1.51 ms.
- Moving every frame slot's group back into W slots would make demo3's
  model cost 10.9 ms a tic against 1.5.

## 7. The renderer's and the object API's techniques

- **The object API** (`gobj.s`): a cache miss copies its records in one
  window run from page 1 (`pw_go`, `$0100-$014F`): a mobj's record
  groups, a line with its sectors, a sector's two records, a block list.
  Line lookups start from the line used last. The caches are 8 mobjs, 8
  sectors, 8 lines and 5 specials.
- **The bucket pass**: each column's byte count comes from the record
  producers (`rec_room`, `FCNT`, `MCNT`), so no walk counts them; the
  chunk copy is a 10-byte loop written into zero page each frame.
- **The replay**: a texture span that wraps past texel 127 copies its two
  used runs, not all 128 texels.
- **The front end**: the BSP walk keeps each node's box corner angles
  while the view stands still (`CCANG` in `RENDB`). In a run of frames
  that skip the weapon rows with the same weapon vissprite, the weapon's
  clip pass takes the first frame's result (`WCLIP`) instead of running
  again.

## 8. Limits and open problems

- `MAXTICS` stays 4: changing it would change which gametics are drawn.
- `K_TIC` makes two requests (the core from `GCODE0`, the planes from
  `MOBJP`); one with both banks' runs would save about 46 µs a frame, but
  `am_runs` takes one bank a list and `AMEMLC` has no byte left.
- `nm_bkload` and the bucket pass's `park` and `back` stay CPU copies
  (about 0.3 ms a frame). Converting them needs the transport at a fixed
  place the render images can import.
- The group directory rounds a tail to an even byte count and loads a
  tail over `TAIL_MAX` bytes as a whole page (`grun.group_entry`): at
  most about 10 µs a load with a request.
- The frame slots are full; more pinned code needs smaller groups or
  more room.
- The kernel's `far_gcopy` (35 B at `KERN_GCOPY`, `$FFD5`) is called by
  no game code.
- The rest of the frame is soft-switch windows, RamWorks line misses and
  the SHR drain, which the firmware sets.
