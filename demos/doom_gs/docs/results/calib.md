# CALIB.hdv: the card's per-operation costs

Written by `tools/native/calibdisk.py --doc` (docs/SPEED.md 5: the card's TIC row fell 9.6 ms where a2vm predicted 24.1 after speed wave 2, so a2vm's costs of the tic phase's RamWorks work are checked against the card before wave 3).

**The disk:** `build/native/CALIB.hdv`, 143360 bytes, SHA-1 `e692b6e441367274cec3c4513bc4bfd2a9b7c4bb`. Boot it on the Appletini (PAL //e, TURBO, the Phasor in slot 4 and RamWorks on, as for DOOM.hdv); it shows "CALIB: MEASURING", runs the 44 lines once, then shows them; R runs them again, CTRL-RESET reboots (the program overwrites ProDOS's card). The run takes 7.187 s on a2vm f121 with the DOOM profile's window of 32 and 9.152 s with the default window of 512 (TIME in the header, measured by the program itself): on the card about 10 s, more where the card is slower than a2vm. A photo of the screen gives the card's columns.

**The screen** (80 columns): row 0 `CALIB PAL 20280  WIN 32  CPU 110.100 MHZ  TIME 7.187 S  RUN 1  R: RUN AGAIN` (the video standard and its frame in bus cycles, the slot-4 window, REG's nominal 65C02 cycles a second, the run's time, the runs since the boot); row 1 the heads; rows 2-23 the 44 lines, 22 a side: the name, the card's us an operation, its us a byte (where an operation moves bytes), a2vm f121's us an operation. ERR in place of the figures: the two timers disagreed or D was not positive.

## How it measures

- **The clock.** Timer 1 of the Phasor's VIA-B, free-running with the latch `$FFFE` (a period of exactly 65,536 bus cycles: 1,015,625 a second on PAL, 1,020,484 on NTSC, told apart by one frame between two blankings of `$C019`, the figure after PAL in the header). It is read at the start and the end of each measurement only: the low byte, the high byte, the low byte again (a read whose low bytes wrapped is taken again). VIA-A's timer 1 runs beside it with the latch `$FEFE` (65,280 cycles): the difference of the two elapsed counts, 256 a VIA-B wrap, gives the wraps, so a measurement may run 16 s; a difference off a multiple of 256 by more than 24 marks it ERR.
- **The reads cancel.** Each line is measured with n and with 2n repetitions of its unit in the same loop (`measure` in the card); the figure is (E(2n) - E(n)) / n, so the timer reads and the slot-4 window they open (512 CPU cycles at 1 MHz by default, 32 with the DOOM profile) cancel exactly. n is chosen so that E(n) is about 55,000 bus cycles on a2vm f121: the reads' window is under 1% of each measurement even before it cancels. Interrupts are masked.
- **The game's code.** far_get, far_put and far_pload are the bytes of the card's far area (`$DC00-$DFFF` of bank 1) and far_gcopy the kernel's (`$FFD5`), as the play build puts them in DOOM.hdv's LC.BIN; the object API's window is gobj.s's `pw_go`, copied from the tic image into page 1 as go_reset does. They run at the game's addresses: far_gcopy, far_pload and the window are called from main code as the game calls them (gr_load's FA_* and Y for far_gcopy); far_get and far_put are the units themselves, called by the driver's `jsr` in the card (the game calls them from main code). `calibdisk.py` checks the bytes against DOOM.hdv and against the card and page 1 after the run.
- **The units.** A line's unit is called by the driver's loop (`jsr`, a 16-bit count: 26 cycles with the call); the figure is per operation: per byte for the memory loops, per call for the routines, with "us/byte" the call over its bytes. The driver's loop and the loops that read or write another bank run in the card, as far.s's do; the setups (FA_*, the descriptors) run before the timing.
- **The header.** WIN: the slot-4 window from SPIN and WIN (the T test of the music disk, with the timers instead of frame counts), W = (t_WIN - t_SPIN - 1) / (1 - t_SPIN / 837) CPU cycles (the read's own bus cycle aside, the window's W cycles at 1 MHz less the time TURBO would have taken them), shown as 512 (480-540), 32 (24-44), NONE (below 5) or the whole cycles; CPU: REG's nominal 65C02 cycles a second (1313 a unit, checked on a2vm's core; TURBO shows tens of MHz, a //e at 1 MHz about 1).
- **Noise and steps.** A timer read whose low bytes wrapped is retaken about 15 bus cycles later, which moves that E by as much (0.03%); a2vm's run shows its E equal to its own clock between the reads that held. A unit bound to the bus (a soft switch, a slot-4 read, a far window) takes a whole number of bus cycles or alternates between two, so its figure moves by up to a bus cycle (0.985 us) with where its code falls against the bus: compare the card and a2vm line by line, not the SW lines among themselves below a bus cycle.

## The lines

a2vm: `f121+phasor+window32` (`f121`, the game's profile in `playdisk.py`: the DOOM profile's window of 32) and `fastpath+phasor+window32`, `--via-timers`, the exact core, `--cost-timed`. Header on a2vm f121: PAL, frame 20280 bus cycles, WIN 32 (32.5 cycles), CPU 110.10 MHz; with the default window of 512 (`f121+phasor`) WIN 512 (513.0) and the WIN line 509.046 us; the other lines' D move by 18 bus cycles at most (0.033%: a timer read retaken, or where the code falls against the bus), which changes the third decimal of 19 of them.

| # | Line | What it measures | n | a2vm f121 us/op | us/byte | fastpath us/op | Card us/op | Card us/byte |
| --: | --- | --- | --: | --: | --: | --: | --: | --: |
| 1 | `REG` | a register-only loop: one `dey / bne` turn (5 cycles), in the card | 4540 | 0.047 |  | 0.047 | | |
| 2 | `MAIN RD` | `lda abs,y / iny / bne` over 16 pages of main memory ($A000-$AFFF): one byte | 119 | 0.111 |  | 0.111 | | |
| 3 | `MAIN WR` | `sta abs,y / iny / bne` over the same pages: one byte | 126 | 0.105 |  | 0.105 | | |
| 4 | `AUX RD` | MAIN RD in aux bank 0 (RAMRD on, `$C073` = 0, the loop in the card) | 119 | 0.111 |  | 0.111 | | |
| 5 | `AUX WR` | MAIN WR in aux bank 0 (RAMWRT on) | 126 | 0.105 |  | 0.105 | | |
| 6 | `RW HIT` | MAIN RD's loop shape on RamWorks bank 16 (RAMRD on), but `lda abs,x` with X = 0: every read the same byte, the line cache's hit | 103 | 0.128 |  | 0.128 | | |
| 7 | `RW SEQ` | MAIN RD in bank 16: in order, one line miss every 8 bytes | 72 | 0.185 |  | 0.156 | | |
| 8 | `RW UHIT` | 64 unrolled `lda abs` of one byte of bank 16 (hits): the base of the next two | 8580 | 0.099 |  | 0.099 | | |
| 9 | `RW S64` | 64 unrolled `lda abs` of bank 16 at a stride of 64 bytes: every read a miss | 859 | 0.985 |  | 0.324 | | |
| 10 | `RW S256` | the same at a stride of 256 bytes (64 pages) | 859 | 0.985 |  | 0.323 | | |
| 11 | `RW WHIT` | RW HIT's loop with `sta abs,x` (RAMWRT on): every write the same byte | 103 | 0.128 |  | 0.128 | | |
| 12 | `RW WSEQ` | MAIN WR in bank 16: in order, a dirty line every 8 bytes | 53 | 0.248 |  | 0.178 | | |
| 13 | `RW WS64` | 64 unrolled `sta abs` at a stride of 64 bytes: every write a miss with a dirty victim | 430 | 1.969 |  | 0.504 | | |
| 14 | `GC RW 1` | far_gcopy (the kernel's, `$FFD5`) of 1 page from bank 16 to main, called as gr_load calls it | 776 | 70.394 | 0.275 | 60.417 | | |
| 15 | `GC RW 4` | far_gcopy of 4 pages from bank 16 | 210 | 259.756 | 0.254 | 238.202 | | |
| 16 | `GC RW 8` | far_gcopy of 8 pages from bank 16 | 106 | 510.495 | 0.249 | 475.142 | | |
| 17 | `GC AX 1` | far_gcopy of 1 page from aux bank 0 | 1019 | 53.173 | 0.208 | 49.321 | | |
| 18 | `GC AX 4` | far_gcopy of 4 pages from aux bank 0 | 274 | 197.911 | 0.193 | 193.470 | | |
| 19 | `GC AX 8` | far_gcopy of 8 pages from aux bank 0 | 139 | 389.915 | 0.190 | 385.587 | | |
| 20 | `PLOAD 4` | far_pload (far.s) of a list of one run of 4 pages from bank 16 to the same main pages | 208 | 260.260 | 0.254 | 238.395 | | |
| 21 | `SPIN` | a main read then 160 turns of `dey / bne` (837 cycles with the driver) | 7033 | 7.710 |  | 7.710 | | |
| 22 | `WIN` | SPIN with a read of VIA-A's DDRA (`$C413`) in place of the main read: the slot-4 window it opens (the header's WIN) | 1341 | 40.369 |  | 40.369 | | |
| 23 | `GET RW 4` | far_get (far.s) of 4 bytes from bank 16 to main | 7857 | 6.894 | 1.724 | 1.892 | | |
| 24 | `GET RW24` | far_get of 24 bytes from bank 16 | 3929 | 13.785 | 0.574 | 7.140 | | |
| 25 | `GET RW96` | far_get of 96 bytes from bank 16 | 1341 | 40.369 | 0.421 | 26.039 | | |
| 26 | `GET AX 4` | far_get of 4 bytes from aux bank 0 | 7857 | 6.892 | 1.723 | 1.815 | | |
| 27 | `GET AX24` | far_get of 24 bytes from aux bank 0 | 4587 | 11.819 | 0.492 | 7.020 | | |
| 28 | `GET AX96` | far_get of 96 bytes from aux bank 0 | 1833 | 29.538 | 0.308 | 24.660 | | |
| 29 | `PUT RW 4` | far_put (far.s) of 4 bytes from main to bank 16 | 7051 | 7.679 | 1.920 | 4.923 | | |
| 30 | `PUT RW24` | far_put of 24 bytes to bank 16 | 3102 | 17.455 | 0.727 | 9.846 | | |
| 31 | `PUT RW96` | far_put of 96 bytes to bank 16 | 1008 | 53.762 | 0.560 | 28.554 | | |
| 32 | `PUT AX 4` | far_put of 4 bytes to aux bank 0 | 7757 | 6.982 | 1.745 | 3.940 | | |
| 33 | `PUT AX24` | far_put of 24 bytes to aux bank 0 | 4231 | 12.800 | 0.533 | 9.846 | | |
| 34 | `PUT AX96` | far_put of 96 bytes to aux bank 0 | 1794 | 30.171 | 0.314 | 26.585 | | |
| 35 | `MO GET` | gobj.s's page-1 window (`pw_go`) with mo_fetch's four descriptors: a mobj's RTHING, A, B and C groups (4 x 24 bytes, four banks) into a cache line; the descriptors' setup excluded | 1462 | 37.038 | 0.386 | 21.519 | | |
| 36 | `MO PUT` | the same window as mo_wback writes it: the four groups back (RAMWRT) | 1108 | 48.889 | 0.509 | 26.585 | | |
| 37 | `LN GET` | the window with ln_miss's three descriptors: a line's record (32 bytes, LVG0) and its two sector bytes (LVS) | 2587 | 20.944 | 0.616 | 9.194 | | |
| 38 | `SW NONE` | `jsr` to 16 `lda abs,x` in main and back: the base of the switches | 20393 | 1.328 |  | 1.328 | | |
| 39 | `SW RAMRD` | `sta $C003 / sta $C002` (from the card) then SW NONE's main code | 6342 | 4.267 |  | 1.463 | | |
| 40 | `SW RAMWR` | `sta $C005 / sta $C004` then the main code | 6347 | 4.267 |  | 3.938 | | |
| 41 | `SW C073` | `stz $C073` then the main code | 9190 | 2.955 |  | 1.394 | | |
| 42 | `SW ALTZP` | `sta $C009 / sta $C008` then the main code | 6346 | 4.267 |  | 1.454 | | |
| 43 | `SHR SEQ` | RAMWRT on, 256 contiguous bytes to aux `$2000` (SHR), RAMWRT off, `lda $C000`: the burst and its drain | 209 | 259.194 | 1.012 | 259.279 | | |
| 44 | `SHR COL` | the same with a column: 96 bytes 160 apart | 227 | 238.763 | 2.487 | 238.871 | | |

The card's columns are empty until the owner's photo fills them. The screen shows the card's us/op, us/byte and a2vm f121's us/op side by side; on a2vm f121 it reads:

```
CALIB PAL 20280  WIN 32  CPU 110.100 MHZ  TIME 7.187 S  RUN 1  R: RUN AGAIN
OP          US/OP   US/B A2VM F121      OP          US/OP   US/B A2VM F121
REG         0.047            0.047      GET RW 4    6.894  1.724     6.894
MAIN RD     0.111            0.111      GET RW24   13.785  0.574    13.785
MAIN WR     0.105            0.105      GET RW96   40.369  0.421    40.369
AUX RD      0.111            0.111      GET AX 4    6.892  1.723     6.892
AUX WR      0.105            0.105      GET AX24   11.819  0.492    11.819
RW HIT      0.128            0.128      GET AX96   29.538  0.308    29.538
RW SEQ      0.185            0.185      PUT RW 4    7.679  1.920     7.679
RW UHIT     0.099            0.099      PUT RW24   17.455  0.727    17.455
RW S64      0.985            0.985      PUT RW96   53.762  0.560    53.762
RW S256     0.985            0.985      PUT AX 4    6.982  1.745     6.982
RW WHIT     0.128            0.128      PUT AX24   12.800  0.533    12.800
RW WSEQ     0.248            0.248      PUT AX96   30.171  0.314    30.171
RW WS64     1.969            1.969      MO GET     37.038  0.386    37.038
GC RW 1    70.394  0.275    70.394      MO PUT     48.889  0.509    48.889
GC RW 4   259.756  0.254   259.756      LN GET     20.944  0.616    20.944
GC RW 8   510.495  0.249   510.495      SW NONE     1.328            1.328
GC AX 1    53.173  0.208    53.173      SW RAMRD    4.267            4.267
GC AX 4   197.911  0.193   197.911      SW RAMWR    4.267            4.267
GC AX 8   389.915  0.190   389.915      SW C073     2.955            2.955
PLOAD 4   260.260  0.254   260.260      SW ALTZP    4.267            4.267
SPIN        7.710            7.710      SHR SEQ   259.194  1.012   259.194
WIN        40.369           40.369      SHR COL   238.763  2.487   238.763
```

## Reading the card against a2vm

- REG, MAIN RD and MAIN WR set the CPU's speed in fast memory; AUX RD and AUX WR the same through RAMRD and RAMWRT.
- RW HIT and RW UHIT are the line cache's hits; RW SEQ against RW HIT gives a sequential miss (one every 8 bytes: 8 x the difference); RW S64 and RW S256 against RW UHIT give a random miss, and their difference any PSRAM row effect; RW WSEQ and RW WS64 the same for writes with dirty victims.
- GC (far_gcopy) per page against RW SEQ gives the copy's cost beyond its reads; GET and PUT at 4, 24 and 96 bytes split into a fixed cost a call (the window: two switches, two `$C073` writes and the cache refills) and a cost a byte.
- MO GET, MO PUT and LN GET are the object API's misses as the tic phase runs them; SW lines less SW NONE are each switch's cost with the refill of the main code after it.
- SHR SEQ against the known card figure (0.985 us a byte, one Apple cycle) checks the drain of contiguous bytes; SHR COL the coalescer's page scan on a column (about 4 Apple cycles a byte).

## Commands

```
python3 tools/native/calibdisk.py --doc     # gen, make, a2vm, the disk, this page
python3 -m unittest test_calib              # from tests/: about 20 s
```
