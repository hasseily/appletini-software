# CALIB.hdv: the card's per-operation costs

Written by `tools/native/calibdisk.py --doc` (docs/SPEED.md 5: the card's TIC row fell 9.6 ms where a2vm predicted 24.1 after speed wave 2, so a2vm's costs of the tic phase's RamWorks work are checked against the card before wave 3).

**The card** (the owner's photo, 2026-10-03, PAL //e, WIN 32, the disk of SHA-1 `e692b6e4`, whose A2VM column held the model before the correction): CPU 66.690 MHz, TIME 8.417 s. Its figures are the Card columns below. They corrected a2vm's cost model the same day (**The fit**, below): a2vm f121 now comes within 0.6% of the card on every line it measured (MO GET the farthest), 44 of the 44 within 1%; before, up to 39.0% (REG). The memory API's PRIVATE lines (45-52, page 2) came after that photo: they have no card figures yet.

**The disk:** `build/native/CALIB.hdv`, 143360 bytes, SHA-1 `ceb663d6a9aacc6bd35304d70d1b64375c2d9c9f`, with the corrected model's figures in its A2VM column. Boot it on the Appletini (PAL //e, TURBO, the Phasor in slot 4 and RamWorks on, as for DOOM.hdv); it shows "CALIB: MEASURING", runs the 52 lines once, then shows the first 44 (text page 1); SPACE shows the memory API's 8 (text page 2) and SPACE again page 1; R runs them all again, CTRL-RESET reboots (the program overwrites ProDOS's card). The run takes 9.891 s on a2vm f121 with the DOOM profile's window of 32 and 11.854 s with the default window of 512 (TIME in the header, measured by the program itself; the card took 8.417 s for the 44 lines of the earlier disk). A photo of each page gives the card's columns.

**The screen** (80 columns): row 0 `CALIB PAL 20280  WIN 32  CPU 66.690 MHZ  TIME 9.891 S  RUN 1  SPACE: MORE` (the video standard and its frame in bus cycles, the slot-4 window, REG's nominal 65C02 cycles a second, the run's time, the runs since the boot, the key to page 2); row 1 the heads; rows 2-23 the first 44 lines, 22 a side: the name, the card's us an operation, its us a byte (where an operation moves bytes), a2vm f121's us an operation. Page 2 (SPACE): row 0 `CALIB PAGE 2: THE MEMORY API  SPACE: PAGE 1  R: RUN AGAIN`, row 1 the heads, rows 2-5 the PRIVATE lines (PR2 left, PR6 right), rows 7-10 a legend, row 12 `NO MEMORY API IN SLOT 7 (APPLETINI F1.1.4 OR LATER, VTW ON): NOT MEASURED` when the program found no memory API in slot 7. ERR in place of the figures: the two timers disagreed or D was not positive, or (a PRIVATE line) there is no memory API or a request was refused or got no reply.

## How it measures

- **The clock.** Timer 1 of the Phasor's VIA-B, free-running with the latch `$FFFE` (a period of exactly 65,536 bus cycles: 1,015,625 a second on PAL, 1,020,484 on NTSC, told apart by one frame between two blankings of `$C019`, the figure after PAL in the header). It is read at the start and the end of each measurement only: the low byte, the high byte, the low byte again (a read whose low bytes wrapped is taken again). VIA-A's timer 1 runs beside it with the latch `$FEFE` (65,280 cycles): the difference of the two elapsed counts, 256 a VIA-B wrap, gives the wraps, so a measurement may run 16 s; a difference off a multiple of 256 by more than 24 marks it ERR.
- **The reads cancel.** Each line is measured with n and with 2n repetitions of its unit in the same loop (`measure` in the card); the figure is (E(2n) - E(n)) / n, so the timer reads and the slot-4 window they open (512 CPU cycles at 1 MHz by default, 32 with the DOOM profile) cancel exactly. n is chosen so that E(n) is about 55,000 bus cycles on a2vm f121: the reads' window is under 1% of each measurement even before it cancels. Interrupts are masked.
- **The game's code.** far_get, far_put and far_pload are the bytes of the card's far area (`$DC00-$DFFF` of bank 1) and far_gcopy the kernel's (`$FFD5`), as the play build puts them in DOOM.hdv's LC.BIN; the object API's window is gobj.s's `pw_go`, copied from the tic image into page 1 as go_reset does. They run at the game's addresses: far_gcopy, far_pload and the window are called from main code as the game calls them (gr_load's FA_* and Y for far_gcopy); far_get and far_put are the units themselves, called by the driver's `jsr` in the card (the game calls them from main code). `calibdisk.py` checks the bytes against DOOM.hdv and against the card and page 1 after the run.
- **The units.** A line's unit is called by the driver's loop (`jsr`, a 16-bit count: 26 cycles with the call); the figure is per operation: per byte for the memory loops, per call for the routines, with "us/byte" the call over its bytes. The driver's loop and the loops that read or write another bank run in the card, as far.s's do; the setups (FA_*, the descriptors) run before the timing.
- **The header.** WIN: the slot-4 window from SPIN and WIN (the T test of the music disk, with the timers instead of frame counts), W = (t_WIN - t_SPIN - 1) / (1 - t_SPIN / 837) CPU cycles (the read's own bus cycle aside, the window's W cycles at 1 MHz less the time TURBO would have taken them), shown as 512 (480-540), 32 (24-44), NONE (below 5) or the whole cycles; CPU: REG's nominal 65C02 cycles a second (1313 a unit, checked on a2vm's core; TURBO shows tens of MHz, a //e at 1 MHz about 1).
- **The memory API.** The PRIVATE lines time what the frame slots will do (docs/MEMORY_MAP.md rule 3: CPU stores into main `$2000-$5FFF` are video writes, so a group of code is put there by one memory-API request): each unit sends one request (eight for 8X2K) of one descriptor, COPY with the PRIVATE flag from RamWorks bank 17 to main, through slot 7's raw FIFO as appletini-one's README_MEMORY_API.md section 7 specifies and as lload.s's am_send sends one: `$CFFF` and `$C700` read, the request's 36 bytes (the CONTROL command, its nine parameter bytes, the list's length, its header, the descriptor) written to `$CFF0`, `$02` to `$CFF1`, `$CFF1` polled, the result read from `$CFF0` and popped at `$CFF2`, `$CFFF` read; the requests are built before the timing (the game's are built once too). The units and the transport run in the card. Main `$2000-$9FFF` holds the program itself, so each setup first copies main's 16 KB at the destination into bank 17 (one untimed request): the timed copies rewrite main with the bytes it holds, and `calibdisk.py` checks after the run that main still holds the program and bank 17 the same bytes, and that a2vm's memory API ran every request the list sends (4043 in a run). At the start a STATUS request finds the API (as pl_boot.s does); without it the PRIVATE lines show ERR and page 2 says why.
- **Noise and steps.** A timer read whose low bytes wrapped is retaken about 15 bus cycles later, which moves that E by as much (0.03%); a2vm's run shows its E equal to its own clock between the reads that held. A unit bound to the bus (a soft switch, a slot-4 read, a far window) takes a whole number of bus cycles or alternates between two, so its figure moves by up to a bus cycle (0.985 us) with where its code falls against the bus: compare the card and a2vm line by line, not the SW lines among themselves below a bus cycle.

## The lines

a2vm: `f121+phasor+window32` (`f121`, the game's profile in `playdisk.py`: the DOOM profile's window of 32; "before": `f121+phasor+window32+precal`, the model before the card corrected it) and `fastpath+phasor+window32`, `--via-timers`, the exact core, `--cost-timed`. Header on a2vm f121: PAL, frame 20280 bus cycles, WIN 32 (32.7 cycles), CPU 66.69 MHz; with the default window of 512 (`f121+phasor`) WIN 512 (512.0) and the WIN line 510.031 us; the other lines' D move by 16 bus cycles at most (0.027%: a timer read retaken, or where the code falls against the bus), which changes the third decimal of 10 of them.

| # | Line | What it measures | n | Card us/op | Card us/byte | a2vm f121 us/op | against the card | before 2026-10-03 us/op | against the card | fastpath us/op |
| --: | --- | --- | --: | --: | --: | --: | --: | --: | --: | --: |
| 1 | `REG` | a register-only loop: one `dey / bne` turn (5 cycles), in the card | 4540 | 0.077 |  | 0.077 | +0.0% | 0.047 | -39.0% | 0.077 |
| 2 | `MAIN RD` | `lda abs,y / iny / bne` over 16 pages of main memory ($A000-$AFFF): one byte | 119 | 0.141 |  | 0.141 | +0.0% | 0.111 | -21.3% | 0.141 |
| 3 | `MAIN WR` | `sta abs,y / iny / bne` over the same pages: one byte | 126 | 0.150 |  | 0.150 | +0.0% | 0.105 | -30.0% | 0.150 |
| 4 | `AUX RD` | MAIN RD in aux bank 0 (RAMRD on, `$C073` = 0, the loop in the card) | 119 | 0.141 |  | 0.141 | +0.0% | 0.111 | -21.3% | 0.141 |
| 5 | `AUX WR` | MAIN WR in aux bank 0 (RAMWRT on) | 126 | 0.150 |  | 0.150 | +0.0% | 0.105 | -30.0% | 0.150 |
| 6 | `RW HIT` | MAIN RD's loop shape on RamWorks bank 16 (RAMRD on), but `lda abs,x` with X = 0: every read the same byte, the line cache's hit | 103 | 0.158 |  | 0.158 | +0.0% | 0.128 | -19.0% | 0.158 |
| 7 | `RW SEQ` | MAIN RD in bank 16: in order, one line miss every 8 bytes | 72 | 0.246 |  | 0.246 | +0.0% | 0.185 | -24.8% | 0.186 |
| 8 | `RW UHIT` | 64 unrolled `lda abs` of one byte of bank 16 (hits): the base of the next two | 8580 | 0.100 |  | 0.100 | +0.0% | 0.099 | -1.0% | 0.100 |
| 9 | `RW S64` | 64 unrolled `lda abs` of bank 16 at a stride of 64 bytes: every read a miss | 859 | 0.985 |  | 0.985 | +0.0% | 0.985 | +0.0% | 0.325 |
| 10 | `RW S256` | the same at a stride of 256 bytes (64 pages) | 859 | 0.985 |  | 0.985 | +0.0% | 0.985 | +0.0% | 0.325 |
| 11 | `RW WHIT` | RW HIT's loop with `sta abs,x` (RAMWRT on): every write the same byte | 103 | 0.173 |  | 0.173 | +0.0% | 0.128 | -26.0% | 0.173 |
| 12 | `RW WSEQ` | MAIN WR in bank 16: in order, a dirty line every 8 bytes | 53 | 0.369 |  | 0.369 | +0.0% | 0.248 | -32.8% | 0.223 |
| 13 | `RW WS64` | 64 unrolled `sta abs` at a stride of 64 bytes: every write a miss with a dirty victim | 430 | 1.969 |  | 1.969 | +0.0% | 1.969 | +0.0% | 0.505 |
| 14 | `GC RW 1` | far_gcopy (the kernel's, `$FFD5`) of 1 page from bank 16 to main, called as gr_load calls it | 776 | 85.339 | 0.333 | 85.660 | +0.4% | 70.392 | -17.5% | 70.159 |
| 15 | `GC RW 4` | far_gcopy of 4 pages from bank 16 | 210 | 321.688 | 0.314 | 321.969 | +0.1% | 259.760 | -19.3% | 276.878 |
| 16 | `GC RW 8` | far_gcopy of 8 pages from bank 16 | 106 | 636.442 | 0.311 | 637.046 | +0.1% | 510.495 | -19.8% | 552.378 |
| 17 | `GC AX 1` | far_gcopy of 1 page from aux bank 0 | 1019 | 64.000 | 0.250 | 64.000 | +0.0% | 53.173 | -16.9% | 59.062 |
| 18 | `GC AX 4` | far_gcopy of 4 pages from aux bank 0 | 274 | 237.271 | 0.232 | 237.292 | +0.0% | 197.911 | -16.6% | 232.200 |
| 19 | `GC AX 8` | far_gcopy of 8 pages from aux bank 0 | 139 | 468.422 | 0.229 | 467.692 | -0.2% | 389.915 | -16.8% | 462.833 |
| 20 | `PLOAD 4` | far_pload (far.s) of a list of one run of 4 pages from bank 16 to the same main pages | 208 | 322.480 | 0.315 | 322.958 | +0.1% | 260.265 | -19.3% | 277.056 |
| 21 | `SPIN` | a main read then 160 turns of `dey / bne` (837 cycles with the driver) | 7033 | 12.595 |  | 12.593 | -0.0% | 7.712 | -38.8% | 12.593 |
| 22 | `WIN` | SPIN with a read of VIA-A's DDRA (`$C413`) in place of the main read: the slot-4 window it opens (the header's WIN) | 1341 | 45.292 |  | 45.292 | +0.0% | 40.347 | -10.9% | 45.292 |
| 23 | `GET RW 4` | far_get (far.s) of 4 bytes from bank 16 to main | 7857 | 6.892 | 1.723 | 6.894 | +0.0% | 6.892 | +0.0% | 2.153 |
| 24 | `GET RW24` | far_get of 24 bytes from bank 16 | 3929 | 13.785 | 0.574 | 13.785 | +0.0% | 13.785 | +0.0% | 8.303 |
| 25 | `GET RW96` | far_get of 96 bytes from bank 16 | 1341 | 40.369 | 0.421 | 40.369 | +0.0% | 40.369 | +0.0% | 30.442 |
| 26 | `GET AX 4` | far_get of 4 bytes from aux bank 0 | 7857 | 6.890 | 1.722 | 6.892 | +0.0% | 6.892 | +0.0% | 2.078 |
| 27 | `GET AX24` | far_get of 24 bytes from aux bank 0 | 4587 | 12.800 | 0.533 | 12.800 | +0.0% | 11.815 | -7.7% | 8.183 |
| 28 | `GET AX96` | far_get of 96 bytes from aux bank 0 | 1833 | 33.477 | 0.349 | 33.477 | +0.0% | 29.538 | -11.8% | 29.063 |
| 29 | `PUT RW 4` | far_put (far.s) of 4 bytes from main to bank 16 | 7051 | 8.828 | 2.207 | 8.862 | +0.4% | 7.682 | -13.0% | 4.925 |
| 30 | `PUT RW24` | far_put of 24 bytes to bank 16 | 3102 | 18.667 | 0.778 | 18.708 | +0.2% | 17.455 | -6.5% | 10.831 |
| 31 | `PUT RW96` | far_put of 96 bytes to bank 16 | 1008 | 54.152 | 0.564 | 54.154 | +0.0% | 53.746 | -0.7% | 33.477 |
| 32 | `PUT AX 4` | far_put of 4 bytes to aux bank 0 | 7757 | 7.860 | 1.965 | 7.877 | +0.2% | 6.983 | -11.2% | 4.923 |
| 33 | `PUT AX24` | far_put of 24 bytes to aux bank 0 | 4231 | 13.711 | 0.571 | 13.785 | +0.5% | 12.800 | -6.6% | 10.831 |
| 34 | `PUT AX96` | far_put of 96 bytes to aux bank 0 | 1794 | 34.462 | 0.359 | 34.462 | +0.0% | 30.172 | -12.4% | 31.508 |
| 35 | `MO GET` | gobj.s's page-1 window (`pw_go`) with mo_fetch's four descriptors: a mobj's RTHING, A, B and C groups (4 x 24 bytes, four banks) into a cache line; the descriptors' setup excluded | 1462 | 45.038 | 0.469 | 45.292 | +0.6% | 37.028 | -17.8% | 25.992 |
| 36 | `MO PUT` | the same window as mo_wback writes it: the four groups back (RAMWRT) | 1108 | 54.155 | 0.564 | 54.155 | +0.0% | 48.874 | -9.8% | 31.508 |
| 37 | `LN GET` | the window with ln_miss's three descriptors: a line's record (32 bytes, LVG0) and its two sector bytes (LVS) | 2587 | 23.579 | 0.694 | 23.630 | +0.2% | 20.951 | -11.1% | 10.852 |
| 38 | `SW NONE` | `jsr` to 16 `lda abs,x` in main and back: the base of the switches | 20393 | 1.429 |  | 1.429 | +0.0% | 1.328 | -7.1% | 1.429 |
| 39 | `SW RAMRD` | `sta $C003 / sta $C002` (from the card) then SW NONE's main code | 6342 | 4.923 |  | 4.923 | +0.0% | 4.267 | -13.3% | 1.564 |
| 40 | `SW RAMWR` | `sta $C005 / sta $C004` then the main code | 6347 | 4.922 |  | 4.923 | +0.0% | 4.267 | -13.3% | 3.938 |
| 41 | `SW C073` | `stz $C073` then the main code | 9190 | 2.954 |  | 2.954 | +0.0% | 2.954 | +0.0% | 1.496 |
| 42 | `SW ALTZP` | `sta $C009 / sta $C008` then the main code | 6346 | 4.923 |  | 4.923 | +0.0% | 4.267 | -13.3% | 1.556 |
| 43 | `SHR SEQ` | RAMWRT on, 256 contiguous bytes to aux `$2000` (SHR), RAMWRT off, `lda $C000`: the burst and its drain | 209 | 259.152 | 1.012 | 259.199 | +0.0% | 259.194 | +0.0% | 259.213 |
| 44 | `SHR COL` | the same with a column: 96 bytes 160 apart | 227 | 238.771 | 2.487 | 238.797 | +0.0% | 238.797 | +0.0% | 238.776 |
| 45 | `PR2 256` | the memory API (slot 7): one request of one PRIVATE COPY of 256 bytes from RamWorks bank 17 to main `$2000` (the colormaps' place in the game), sent through the `$CFF0-$CFF2` FIFO as lload.s's am_send sends one: the request's 36 bytes pushed, executed, its result popped | 505 |  |  | 107.323 |  | 106.309 |  | 83.692 |
| 46 | `PR2 2K` | the same, 2 KB | 76 |  |  | 708.923 |  | 707.938 |  | 517.713 |
| 47 | `PR2 16K` | the same, 16 KB (`$2000-$5FFF`) | 10 |  |  | 5504.982 |  | 5503.998 |  | 3981.291 |
| 48 | `PR2 8X2K` | the same 16 KB as eight requests of 2 KB, one after the other (us/op: a request) | 10 |  |  | 708.061 |  | 706.892 |  | 517.415 |
| 49 | `PR6 256` | PR2 256 to main `$6000` | 505 |  |  | 107.323 |  | 106.368 |  | 83.663 |
| 50 | `PR6 2K` | PR2 2K to main `$6000` | 76 |  |  | 708.923 |  | 707.938 |  | 517.907 |
| 51 | `PR6 16K` | PR2 16K to main `$6000-$9FFF` | 10 |  |  | 5506.459 |  | 5505.475 |  | 3979.814 |
| 52 | `PR6 8X2K` | PR2 8X2K to main `$6000-$9FFF` | 10 |  |  | 708.061 |  | 707.077 |  | 517.415 |

The card's us/byte is its us/op over the bytes (the screen's quotient). The screen shows the card's us/op, us/byte and a2vm f121's us/op side by side; on a2vm f121 it reads:

```
CALIB PAL 20280  WIN 32  CPU 66.690 MHZ  TIME 9.891 S  RUN 1  SPACE: MORE
OP          US/OP   US/B A2VM F121      OP          US/OP   US/B A2VM F121
REG         0.077            0.077      GET RW 4    6.894  1.724     6.894
MAIN RD     0.141            0.141      GET RW24   13.785  0.574    13.785
MAIN WR     0.150            0.150      GET RW96   40.369  0.421    40.369
AUX RD      0.141            0.141      GET AX 4    6.892  1.723     6.892
AUX WR      0.150            0.150      GET AX24   12.800  0.533    12.800
RW HIT      0.158            0.158      GET AX96   33.477  0.349    33.477
RW SEQ      0.246            0.246      PUT RW 4    8.862  2.215     8.862
RW UHIT     0.100            0.100      PUT RW24   18.708  0.780    18.708
RW S64      0.985            0.985      PUT RW96   54.154  0.564    54.154
RW S256     0.985            0.985      PUT AX 4    7.877  1.969     7.877
RW WHIT     0.173            0.173      PUT AX24   13.785  0.574    13.785
RW WSEQ     0.369            0.369      PUT AX96   34.462  0.359    34.462
RW WS64     1.969            1.969      MO GET     45.292  0.472    45.292
GC RW 1    85.660  0.335    85.660      MO PUT     54.155  0.564    54.155
GC RW 4   321.969  0.314   321.969      LN GET     23.630  0.695    23.630
GC RW 8   637.046  0.311   637.046      SW NONE     1.429            1.429
GC AX 1    64.000  0.250    64.000      SW RAMRD    4.923            4.923
GC AX 4   237.292  0.232   237.292      SW RAMWR    4.923            4.923
GC AX 8   467.692  0.228   467.692      SW C073     2.954            2.954
PLOAD 4   322.958  0.315   322.958      SW ALTZP    4.923            4.923
SPIN       12.593           12.593      SHR SEQ   259.199  1.012   259.199
WIN        45.292           45.292      SHR COL   238.797  2.487   238.797
```

## The memory API's PRIVATE copy (page 2)

Lines 45-52 time the frame slots' load before they are built: the tic phase's code paging cost about 138 ms of the card's 332 ms benchmark frame, and putting pinned groups in main `$2000-$5FFF` (colormaps A and B, which only the replay reads) with one PRIVATE request at a group's first call in a frame, the colormaps' pages restored after the tic phase, was simulated at about 28 ms. That estimate rests on a2vm's model of a request, which no card figure has checked yet; these lines are that check. On a2vm f121:

| Line | Requests a unit | Bytes a request | n | a2vm f121 us a request | us a byte | fastpath us a request |
| --- | --: | --: | --: | --: | --: | --: |
| `PR2 256` | 1 | 256 | 505 | 107.323 | 0.419 | 83.692 |
| `PR2 2K` | 1 | 2048 | 76 | 708.923 | 0.346 | 517.713 |
| `PR2 16K` | 1 | 16384 | 10 | 5504.982 | 0.336 | 3981.291 |
| `PR2 8X2K` | 8 | 2048 | 10 | 708.061 | 0.346 | 517.415 |
| `PR6 256` | 1 | 256 | 505 | 107.323 | 0.419 | 83.663 |
| `PR6 2K` | 1 | 2048 | 76 | 708.923 | 0.346 | 517.907 |
| `PR6 16K` | 1 | 16384 | 10 | 5506.459 | 0.336 | 3979.814 |
| `PR6 8X2K` | 8 | 2048 | 10 | 708.061 | 0.346 | 517.415 |

a2vm's model of a request (`a2vm_cost_amem` in `tools/a2vm/cost.c`, the parameters `amem_*` and `axi_us` of `costs/appletini.json`): the request's bytes popped by the ARM, the hold (the mirror and the caches flushed), the copy in chunks of 504 bytes (a DMA read of the RamWorks bank, then AXI writes of main's shadow word by word), the release; the FIFO's own writes are served inside the fabric. From the 2K and 16K lines a request costs 23.8 us plus 0.3345 us a byte into `$2000` (23.6 plus 0.3346 into `$6000`: a2vm charges main alike everywhere), so 16 KB is 5.505 ms in one request and 5.664 ms in eight (+2.9%). Read the card's photo of page 2 against these: its 2K and 16K give its own fixed cost and cost a byte, and the frame slots' estimate scales with them.

Page 2 on a2vm f121:

```
CALIB PAGE 2: THE MEMORY API  SPACE: PAGE 1  R: RUN AGAIN
OP          US/OP   US/B A2VM F121      OP          US/OP   US/B A2VM F121
PR2 256   107.323  0.419   107.323      PR6 256   107.323  0.419   107.323
PR2 2K    708.923  0.346   708.923      PR6 2K    708.923  0.346   708.923
PR2 16K  5504.982  0.336  5504.982      PR6 16K  5506.459  0.336  5506.459
PR2 8X2K  708.061  0.346   708.061      PR6 8X2K  708.061  0.346   708.061

PR2: ONE PRIVATE COPY FROM RAMWORKS BANK 17 TO MAIN $2000 (THE COLORMAPS)
PR6: THE SAME TO MAIN $6000. EACH LINE A MEMORY-API REQUEST, FIFO INCLUDED
256, 2K, 16K: ONE REQUEST OF THAT SIZE; 8X2K: EIGHT REQUESTS OF 2K IN A ROW
US/OP: A REQUEST; US/B: A BYTE; A2VM F121: THE MODEL'S US/OP
```

## The fit (2026-10-03)

Before the card's figures, every line that runs code between its memory accesses was 7-39% faster on a2vm than on the card (REG -39%, MAIN WR -30%, RW WSEQ -33%, GC -17 to -20%), and the lines bound to the bus matched exactly (RW S64, RW WS64, GET RW, SW C073, SHR), except four families: the RAMRD, RAMWRT and ALTZP switches (-13%), far_put's short calls (PUT RW 4 -13%, PUT AX 4 -11%) and the object API's mobj fetch (MO GET -18%, of which -8% remained once the CPU was right). One new parameter and four corrected readings of the RTL account for all of it (a fifth, `slow_done`, follows from the same registers; no line can tell it); each parameter's source in `tools/a2vm/costs/appletini.json` names the lines and the card's figures. The variant `precal` keeps the model before them ("before" above; `playtime.py --profile f121-precal`).

| Parameter | Before | Now | Why (the RTL; the card) | Lines it moves |
| --- | --: | --: | --- | --- |
| `d2_replay` (new) | 0 | 1 | The virtual Disk II in slot 6 is active on the card (`disk2.slot6.enabled` on; the firmware's default is off) and replays, one a clock, the 65C02 cycles each TURBO step stands for; until it has, `d2_time_ready` holds the core's next step (`disk2_card.sv:374-412`, `apple_top.sv:2065-2068`, `vtw_core_top.sv:1524`, `:1907`). A step that omitted k dummy reads delays the next one k + 1 clocks: the TURBO core's free dummy reads cost 2 clocks each (1 for the second of a pair, as in `rts`). REG's `dey / bne`, 3 accesses and 2 such steps: 10.3 clocks on the card, 6.3 before | every line with dummy reads: REG, MAIN, AUX, RW HIT, RW SEQ, RW WHIT, RW WSEQ, GC, PLOAD, SPIN, WIN, GET AX, PUT, MO, LN, SW NONE |
| `bus_drive_tap` | 8 | 9 | drive_en is `addr_pipe[8]` registered (`apple_bus_wrapper.sv:622`): the engine launches a sync cycle at tap 9 (`vtw_bus_engine.sv:810`, `:848-858`) | SW RAMRD, SW RAMWR, SW ALTZP, PUT RW 4, PUT RW24, PUT AX 4 |
| `bus_done` | 2 | 4 | data_en is registered from the data snap (`apple_bus_wrapper.sv:657-659`), resp_valid_q from data_en (`vtw_bus_engine.sv:726`, `:764-767`), then X_BUS and X_BUS_DONE (`vtw_core_top.sv:2125-2159`). With `bus_drive_tap` 9 a switch write right after another's response misses the next Apple cycle: the switch lines take 5.0 Apple cycles on the card, 4.33 before; one write (SW C073) had slack and was already right | as above |
| `admit_offset` | 6 | 30 | addr_en is `TAP_ADDR_SNAP` 25 (`apple_bus_wrapper.sv:101`, `:625-639`), not tap 3; the PSRAM's background window opens three edges later (`psram_simple.sv:313-325`) | GC RW 1 (+1.5% with 6, +0.4% with 30) |
| `admit_window` | 40 | 37 | `ADMIT_WINDOW_TAPS` 40 counts from addr_en, not from the arming (`psram_simple.sv:239`, `:318-328`): the last admission is at tap 66 | MO GET: the third line miss of each descriptor comes 43 clocks into the window and waits a cycle (41.353 us with 40, 45.292 with 37, the card 45.038) |
| `slow_done` | 1 | 3 | A cycle paced at 1 MHz ends on the third clock after the data snap: data_en and `pace_tick_pending_q` are registered (`apple_bus_wrapper.sv:657-659`, `vtw_core_top.sv:1850-1856`, `:1514`), as for `bus_done` | WIN by 0.011 us; the slot-4 window's tests (`test_sound_player65`) |

The other families followed from these, with no parameter of their own: main and aux writes (`sta abs,y` has a dummy read, and so `iny` and the taken `bne`: 3 a byte); RamWorks sequential reads and writes, whose line misses fall one admission window later once the loop takes its real time (RW SEQ 2 Apple cycles a line, RW WSEQ 3, as on the card, with every PSRAM parameter unchanged); far_gcopy and far_pload (their loops' dummy reads, and the same windows). The SHR drain lines were right and stay right (the coalescer's scan, modelled from the RTL on 2026-09-30).

The benchmark checks the fit on the game: on the corrected model the menu's BENCHMARK of both waves' DOOM.hdv comes within 0.4% of the card's FPS and each of its five rows within 1.6% (docs/SPEED.md 5). With the virtual Disk II inactive (the variant `nod2`: `disk2.slot6.enabled=off`, or `vtw.disk2.acceleration.disabled=on`, in the DOOM profile), a2vm predicts wave 2's benchmark at 3.609 FPS against 3.004 as the card is set (+20%; docs/SPEED.md 5); the card, set so, gave 3.610.

## The card on F1.2.2 (2026-10-03)

Firmware F1.2.2 (appletini-one `3101934`) admits PSRAM requests as soon as the service can while vTW owns the bus, and runs the memory API's copies on an FPGA engine. The owner ran this disk (SHA-1 `ceb663d6`) on it, PAL, with the Disk II's acceleration off (`vtw.disk2.acceleration.disabled=on`): CPU 110.100 MHz, TIME 7.045 s. a2vm's profile `f122` (`tools/a2vm/README.md`, "F1.2.2: the profile `f122`") follows the RTL for page 1 with no fitted value, and fits one, `ps_dispatch_us` 25.9 us (the ARM's dispatch of a request), to page 2. Run as the card was, `f122+nod2` (`playtime.py --profile f122-nod2`):

| # | line | card F1.2.2 (D2 off) | f122+nod2 | err | f122 (D2 on) | f121+nod2 |
|--:|---|--:|--:|--:|--:|--:|
| 1 | REG | 0.047 | 0.047 | +0.0% | 0.077 | 0.047 |
| 2 | MAIN RD | 0.111 | 0.111 | +0.0% | 0.141 | 0.111 |
| 3 | MAIN WR | 0.105 | 0.105 | +0.0% | 0.150 | 0.105 |
| 4 | AUX RD | 0.111 | 0.111 | +0.0% | 0.141 | 0.111 |
| 5 | AUX WR | 0.105 | 0.105 | +0.0% | 0.150 | 0.105 |
| 6 | RW HIT | 0.128 | 0.128 | +0.0% | 0.158 | 0.128 |
| 7 | RW SEQ | 0.156 | 0.156 | +0.0% | 0.186 | 0.185 |
| 8 | RW UHIT | 0.099 | 0.099 | +0.0% | 0.100 | 0.099 |
| 9 | RW S64 | 0.324 | 0.324 | +0.0% | 0.325 | 0.985 |
| 10 | RW S256 | 0.323 | 0.323 | +0.0% | 0.325 | 0.985 |
| 11 | RW WHIT | 0.128 | 0.128 | +0.0% | 0.173 | 0.128 |
| 12 | RW WSEQ | 0.178 | 0.178 | +0.0% | 0.223 | 0.251 |
| 13 | RW WS64 | 0.504 | 0.504 | +0.0% | 0.506 | 1.969 |
| 14 | GC RW 1 | 66.906 | 66.954 | +0.1% | 76.781 | 70.891 |
| 15 | GC RW 4 | 244.367 | 244.185 | -0.1% | 283.569 | 259.938 |
| 16 | GC RW 8 | 480.195 | 480.492 | +0.1% | 559.261 | 511.015 |
| 17 | GC AX 1 | 53.734 | 53.491 | -0.5% | 64.000 | 53.488 |
| 18 | GC AX 4 | 198.249 | 198.770 | +0.3% | 237.292 | 198.784 |
| 19 | GC AX 8 | 389.915 | 389.915 | +0.0% | 467.692 | 389.915 |
| 20 | PLOAD 4 | 245.131 | 245.169 | +0.0% | 283.503 | 260.923 |
| 21 | SPIN | 7.710 | 7.710 | +0.0% | 12.591 | 7.710 |
| 22 | WIN | 40.369 | 40.347 | -0.1% | 45.292 | 40.369 |
| 23 | GET RW 4 | 6.892 | 6.892 | +0.0% | 6.890 | 6.892 |
| 24 | GET RW24 | 12.796 | 12.796 | +0.0% | 13.785 | 13.785 |
| 25 | GET RW96 | 33.477 | 33.477 | +0.0% | 37.415 | 40.369 |
| 26 | GET AX 4 | 6.857 | 6.892 | +0.5% | 6.892 | 6.892 |
| 27 | GET AX24 | 11.815 | 11.812 | -0.0% | 12.800 | 11.815 |
| 28 | GET AX96 | 29.538 | 29.538 | +0.0% | 33.469 | 29.538 |
| 29 | PUT RW 4 | 8.827 | 8.862 | +0.4% | 8.859 | 8.862 |
| 30 | PUT RW24 | 15.567 | 15.754 | +1.2% | 16.739 | 18.708 |
| 31 | PUT RW96 | 38.401 | 38.400 | -0.0% | 42.338 | 54.154 |
| 32 | PUT AX 4 | 7.837 | 7.877 | +0.5% | 7.877 | 7.877 |
| 33 | PUT AX24 | 12.803 | 12.800 | -0.0% | 13.785 | 12.800 |
| 34 | PUT AX96 | 30.477 | 30.523 | +0.2% | 34.462 | 30.523 |
| 35 | MO GET | 37.332 | 37.425 | +0.2% | 41.354 | 40.369 |
| 36 | MO PUT | 38.396 | 38.400 | +0.0% | 43.324 | 52.185 |
| 37 | LN GET | 20.645 | 20.677 | +0.2% | 22.646 | 21.661 |
| 38 | SW NONE | 1.328 | 1.328 | +0.0% | 1.429 | 1.328 |
| 39 | SW RAMRD | 4.414 | 4.431 | +0.4% | 4.922 | 4.431 |
| 40 | SW RAMWR | 4.414 | 4.431 | +0.4% | 4.923 | 4.431 |
| 41 | SW C073 | 2.909 | 2.954 | +1.5% | 2.955 | 2.954 |
| 42 | SW ALTZP | 4.413 | 4.431 | +0.4% | 4.923 | 4.431 |
| 43 | SHR SEQ | 259.194 | 259.170 | -0.0% | 259.194 | 259.194 |
| 44 | SHR COL | 238.732 | 238.828 | +0.0% | 238.797 | 238.802 |
| 45 | PR2 256 | 62.241 | 56.123 | -9.8% | 57.108 | 106.338 |
| 46 | PR2 2K | 119.929 | 125.046 | +4.3% | 126.031 | 708.133 |
| 47 | PR2 16K | 786.117 | 676.431 | -14.0% | 677.415 | 5503.998 |
| 48 | PR2 8X2K | 124.400 | 124.431 | +0.0% | 125.415 | 707.077 |
| 49 | PR6 256 | 57.010 | 56.123 | -1.6% | 57.108 | 106.338 |
| 50 | PR6 2K | 128.738 | 125.240 | -2.7% | 126.031 | 707.938 |
| 51 | PR6 16K | 1135.360 | 676.431 | -40.4% | 677.415 | 5503.998 |
| 52 | PR6 8X2K | 120.234 | 124.431 | +3.5% | 125.415 | 707.077 |

- Page 1: 42 of 44 lines within 0.5%. SW C073 (+1.5%) and PUT RW24 (+1.2%) are whole-Apple-cycle phase effects that `f121+nod2` shows alike; no parameter the RTL leaves open moves them without throwing the other switch lines off.
- F1.2.2's change is all in the RamWorks lines: a scattered read is 0.324 us (35 fabric clocks, against one Apple cycle before), a scattered write 0.504 (the dirty victim first), a page copy by the CPU 0.234 us a byte (0.311 on F1.2.1).
- Page 2: a request costs about 46 us plus 0.038 us a byte (the engine moves 8 bytes in 41 clocks, `vtw_copy_engine.sv:126-236`). The PRIVATE copy beats the CPU's copy above about 220 bytes: 2 KB in 120-129 us against 480 us. Identical requests differ by up to 44% on the card (PR2 16K against PR6 16K): nothing in the RTL or the ARM code depends on `$2000` or `$6000`, but the 16K lines' span (n = 10, under 12 ms) is short enough for the ARM's other main-loop work (the compositor, USB, storage), deferred while it polls the engine, to land in one measurement and not the other. The lines with 76 to 505 requests agree within 4-9 us.
- The benchmark checks the profile on the game: wave 2's DOOM.hdv gives 3.829 FPS on `f122+nod2`, the card 3.830, each row within 0.1 ms (docs/SPEED.md 5).

## Reading the card against a2vm

- REG, MAIN RD and MAIN WR set the CPU's speed in fast memory; AUX RD and AUX WR the same through RAMRD and RAMWRT.
- RW HIT and RW UHIT are the line cache's hits; RW SEQ against RW HIT gives a sequential miss (one every 8 bytes: 8 x the difference); RW S64 and RW S256 against RW UHIT give a random miss, and their difference any PSRAM row effect; RW WSEQ and RW WS64 the same for writes with dirty victims.
- GC (far_gcopy) per page against RW SEQ gives the copy's cost beyond its reads; GET and PUT at 4, 24 and 96 bytes split into a fixed cost a call (the window: two switches, two `$C073` writes and the cache refills) and a cost a byte.
- MO GET, MO PUT and LN GET are the object API's misses as the tic phase runs them; SW lines less SW NONE are each switch's cost with the refill of the main code after it.
- SHR SEQ against the known card figure (0.985 us a byte, one Apple cycle) checks the drain of contiguous bytes; SHR COL the coalescer's page scan on a column (about 4 Apple cycles a byte).
- PR2 and PR6 (page 2): the card's us/op is one request's whole cost as the game will pay it (the FIFO, the ARM's hold, the copy, the CPU's caches refilled after it). 2K and 16K give the fixed cost of a request and the cost of a byte (**The memory API's PRIVATE copy**, above); 256 checks the fixed cost; 8X2K against 2K checks that requests in a row cost no more than one alone, and 8X2K against 16K what splitting 16 KB into eight requests costs. PR2 against PR6: whether the colormap area costs more than other main memory (a2vm charges them alike).

## Commands

```
python3 tools/native/calibdisk.py --doc     # gen, make, a2vm, the disk, this page
python3 -m unittest test_calib              # from tests/: about 20 s
```
