# Correctness review: performance-first proposal for IIgs DOOM on the Appletini 65C02

Nothing was assembled or run, and no file was changed. Paths: `[U]` = `.../scratchpad/iigs-doom/src/iigs`, `[F]` = `.../scratchpad/appletini-one-main`. Counts are my greps over `[U]*.s` and `*.inc`; items marked **(A)** are assumptions.

## Verdict

The proposal would not produce a working game as written. It has three classes of fault:

- The translator assumes instruction sizes, the stack layout and the D register are incidental; upstream uses all three as data.
- The memory map over-commits the visible language card and has no single home for the near bank.
- Two code-generation inputs come from a profile run (index below 256, stack depth), which is unsound.

## Proposal claims checked against the source

| Claim | Result | Evidence |
|---|---|---|
| The per-tic private stack exists only for cache slots and can be dropped | True | `[U]p_think65.s:174-178`, `195-197`, `213-215` |
| Stack offsets across a `jsl` are "reduced by one", statically | False | `[U]p_path65.s:1089-1092`, `w_level65.s:1444-1448`, `m_menu65.s:2454-2457`, `p_map65.s:105` |
| Replacing SQL/SQH by an exact multiply gives identical results | False for `qmulh` | `[U]r_wall65.s:1781-1787` |
| D can be tracked as a page value through `tcd`/`phd`/`pld` | False | `[U]p_trace65.s:403-405`, `430-431`, `502-504`, `513-514` |
| Colormap page fills can use amem | False; the cache is in the aux language card | `[F]README_MEMORY_API.md:159-162` |
| `rep`/`sep` emit nothing or one load | False for 12 sites | 7 `rep #0x21`, 3 `sep #0x40`, 2 `sep #0x30` |
| `tdc` has 2 sites | True | `[U]p_trace65.s:697`, `715` |

## Blockers

### B1. Instruction bytes are copied, indexed and saved as data in translated-class code

- **Code templates.** `k3Tpl`/`k2Tpl` are assembled 65816 instructions, 6 bytes per case (`[U]r_thing65.s:1154-1171`). Six bytes are copied into `K3FIX` when the view angle changes, indexed by `6 * (GB.hi + 2)` (`r_thing65.s:1105-1121`, target `:757-762`).
- **Size change.** A translated 16-bit `sbc dp` is about 12 bytes, so both the index arithmetic and the 6-byte slot break.
- **Saved sites.** `hvSet` saves "the 17 bytes of the sites as assembled" and overwrites them with fragments from `hvT` (`r_thing65.s:1268`, `2121-2155`, `1324-1327`). The fragments are `jmp long:` and `jsl` at 4 bytes each.
- **Detection gap.** Patch sites are `.equ .` symbols, not labels (`r_thing65.s:714`, `757`). I count 36 such equates. The proposal detects "a store to a label in a text section".
- **Fix.** Catalogue every patch site by hand and fail the build on an uncatalogued store into text. Replace templates and site swaps with a variable plus an indirect jump, or a selector byte tested in line. Support only the full view until the view-size patchers are rewritten.

### B2. Computed opcodes stored into branches

- **Evidence.** `c12Signs` builds `$10` or `$30` (BPL or BMI) with `and #0x20 / ora #0x10` and stores it into four sites (`[U]r_thing65.s:1307-1319`).
- **Why it fails.** Lazy flags, fusion or branch relaxation can replace the one-byte branch opcode at that address. The proposal's "`lda #opcode` immediates, 35" list cannot see a computed opcode.
- **Fix.** Pin such sites: emit N from the true 16-bit result, keep a short branch at the label, and exclude the site from relaxation. Better, replace with a sign byte and `eor`.

### B3. Stack arithmetic hard-codes the 3-byte JSL frame

| Site | What it does |
|---|---|
| `[U]p_path65.s:1089-1092` | `tsc / adc ##3 / tcs` drops a JSL frame, then leaves by `jml` |
| `[U]w_level65.s:1444-1448` | `titleWipe` drops its own JSL return and returns to the caller's caller |
| `[U]m_menu65.s:2454-2457` | `adc ##19` = 16 argument bytes plus 3 |
| `[U]p_map65.s:105` | `TC_TT .equ (3 + FR_SIZE + 2 + 1)` mixes a JSL frame, a frame and a JSR frame in one constant |
| `[U]p_map65.s:1414-1417`, `1937-1942` | a frame is allocated in one routine and released in another, which then does `rtl` |

- **Why it fails.** The adjustment is not per operand. It lives in immediates and equates, and frames cross routine boundaries, so a separate software frame stack would also desynchronise.
- **Fix.** Keep frames on one stack. Give the translator a symbolic "return address size" term and require every `tsc`/`tcs` site and every stack equate to be annotated.

### B4. Overlay gates change stack-relative offsets

- **Evidence.** Arguments and function pointers are passed on the stack (`[U]p_mobj65.s:341-343`). `callFn` is reached by `jsl` and leaves by `jml [FN_P]`, so the callee sees exactly one return frame (`p_tick65.s:61-63`, `530-531`).
- **Why it fails.** A gate that pushes its own return data shifts every `n,s` in the callee. The same callee can be reached directly or through a gate.
- **Fix.** Keep gate bookkeeping on a private gate stack and swap the return address in place, so the hardware frame size never changes. The gate must preserve P: 250 call sites branch on flags straight after `jsr`/`jsl` (78 `bcs`, 63 `bcc`, 32 `beq`, among others).

### B5. The near bank has no single home

- **Size.** Near data is at least 24 KB initialised plus 16 KB of BSS by literal sums, before drawsegs, openings and vissprites. My estimate is 55 KB or more **(A)**. The map gives it 8 KB in main plus PSRAM banks 7-8.
- **Near pointers.** 16-bit near pointers are stored and dereferenced, for example `mobj->state` (`[U]p_tick65.s:523-526`) and `SM_INFO` (`p_spawn65.s:51`). A 16-bit value cannot say which of three regions it points to.
- **One near bank is assumed.** `NEARDBR` uses `.byte2 _g_thinkerclasscap` as the bank of all near data (`p_tick65.s:66-70`). The walk compares bank bytes against it (`p_tick65.s:145-155`).
- **Fix.** Put all address-taken near objects in one contiguous 16-bit region. Give "main RAM" its own non-zero bank id, distinct from `$C073` value 0. Count the resulting far accesses again.

### B6. The aux language card is over-committed

- **Evidence.** The map puts 8 KB of row blocks and 8 KB of colormap cache there. Only 12 KB (`$D000-$FFFF`) is visible at once, and `$FFFA-$FFFF` holds vectors.
- **Also there.** The compiled HUD text code is 10 bytes per screen byte with two 16 KB slots upstream (`[U]patch65.s:279-283`, `memmap.inc:109`).
- **Why it fails.** Switching `$D000` banks is a `$C08x` access, which the design forbids inside a batch. The cache also cannot be filled by amem.
- **Fix.** Budget 12 KB. Keep row blocks and replay in `$D000-$EFFF`, colormap pages below `$FF00`, and fill them with a CPU copy. Move text code to aux `$0200-$1FFF` behind a trampoline, or drop the text cache.

## Major

| # | Problem | Evidence | Fix |
|---|---|---|---|
| M1 | D is used as a data register in `fixedDiv` | `[U]p_trace65.s:430-431`, `502-504` | Recognise the idiom; map D to a zero-page word there |
| M2 | `php`/`plp` save and restore widths and flags; not modelled | 23 `php`, 57 `plp`; `[U]r_list65.s:551-556`, `p_enemy65.s:1250-1259` | Push and pop the width state in the data-flow; keep N live across `plp / bmi` |
| M3 | `rep #0x21` clears carry; `sep #0x40` sets V as a result flag | `[U]r_seg65.s:1034`, `p_sight65.s:711`, `p_floor65.s:789` | Emit `clc`, or set V with `bit` on a `$40` byte |
| M4 | `qmulh` returns the high word "or 1 more"; an exact multiply differs | `[U]r_wall65.s:1781-1787`; 14 references | Add the missing borrow: high(P) + carry of (low(sq(d)) + low(P)) |
| M5 | Inline four-way table selects are about 90 hand-expanded sequences, not calls | `[U]m_fixed65.s:56-93`, `r_seg65.s:191-238`; SQL/SQH references in 6 files | Match whole sequences; reproduce register and carry outputs |
| M6 | "Index proven below 256" and stack depth come from a profile | proposal sections 2 and 7 | Use static proof, or a guarded fast path with a slow fallback |
| M7 | The gather cannot read records while RAMRD is on | records in main `$9000`; texels in PSRAM | Build a worklist in zero page or main LC first; budget the space |
| M8 | Grouping records by bank can break paint order | covered ranges depend on list order, `[U]lists.inc:108-117` | Cut batches as contiguous runs in replay order |
| M9 | With RAMWRT on, replay writes to main variables land in aux | the replay empties lists as it goes, `[U]r_list65.s:601-610` | Keep replay state in zero page or LC; defer list resets |
| M10 | No overlay window exists while rendering; W holds records and stage | proposal section 3 map | Reserve a code window, or make all render-phase code resident |
| M11 | Overlapping MVN is a required semantic | `[U]w_level65.s:1355-1361`; amem rejects overlap, `[F]README_MEMORY_API.md:164-166` | Forward byte loop on the CPU for the decoder; set X, Y, A and DBR as MVN does |
| M12 | Code after MVN reuses X and Y | `[U]s_sound65.s:2078-2088` | Same helper contract as M11 |
| M13 | WPAGE is reached as `dp:` and as `long:`; 125 long or absolute sites | `[U]d_main65.s:378-381`, `r_wall65.s:1722` | Map by symbol, never by addressing form |
| M14 | Short branches will go out of range after 2-3x expansion | not addressed in the proposal | Add a relaxation pass; exempt patched branches (B2) |
| M15 | Reads past `$BFFF` hit I/O; upstream relies on over-read | `[U]w_level65.s:1451-1455`; `tools/levelimg.py:70` | Keep 128 bytes of slack before `$C000` in every texel bank |

## Minor

- **`sep #0x10`.** It must zero the high bytes of X and Y (11 sites). "Emit nothing" is wrong.
- **16-bit compares.** `cmp`, `cpx` and `cpy` need a sequence that keeps V and, in 8-bit-A windows, real A. Carry from `cpx` is consumed by a later `sbc` (`[U]p_trace65.s:494-496`).
- **16-bit `dex / bpl`.** N must come from the high byte.
- **`[dp],y` with Y above 255.** The far stub must add the high byte of Y. The cost table assumes 8-bit Y.
- **Fuzz and overlay records.** They read the screen (`[U]r_list65.s:523-526`), so they need RAMRD on with bank 0 and break the "no `$Cxxx` in a batch" rule.
- **Pictures.** Upstream blacks the palette, copies, then sets colours (`[U]i_viigs65.s:306-345`). Drawing straight to SHR shows the picture in the old palette, so black the palette before drawing.
- **Nibble tables.** Upstream uses palettes 0-11; 8 KB holds 8.

## Interrupts and helper re-entrancy

- **Bank shadow.** `$C073` is write-only. Stubs must update `curbank` before the hardware write, or the handler restores a stale bank.
- **Shared temporaries.** The handler must not use the virtual registers, far-pointer slots or multiply temporaries.
- **Two stacks.** With ALTZP on, the IRQ pushes onto the aux stack. Both stacks need headroom and both language cards need the handler.
- **Torn reads.** A 16-bit read of a tick counter becomes two loads. Read it under `sei`, or read twice.

## The three most important changes

1. **Treat code bytes and stack layout as catalogued data.** Hand-list every patch site, template, saved site and stack-pointer adjustment; fail the build on anything unlisted; keep gate bookkeeping off the hardware stack. This covers B1-B4.
2. **Redo the memory model.** Give the near bank one 16-bit home and a distinct bank id for main RAM; budget the aux language card at 12 KB; add a render-phase code window and a gather worklist. This covers B5, B6, M7, M9 and M10.
3. **Make code generation sound and bit-exact.** Remove profile-derived facts from emitted code; model `php`/`plp`, flag bits in `rep`/`sep` and D as data; reproduce `qmulh` exactly. This covers M1-M6.