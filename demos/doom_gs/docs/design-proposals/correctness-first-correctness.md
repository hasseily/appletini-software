# Correctness review: virtual-65816 proposal for IIgs DOOM on the Appletini 65C02

The proposal's interpreter-first plan is sound, but the translator scheme as written has four blockers: code-address tokens, static residency for indexed operands, unit boundaries drawn at functions, and patchers the static detector cannot see. All evidence below is from `U/src/iigs/` (`U/` = `<upstream>/`). I read files only; nothing was created or modified.

## 1. Proposal claims checked

| Claim | Result |
|---|---|
| Frame discards at `p_path65.s:1089-1092`, `w_level65.s:1444-1447`, `m_menu65.s:2454-2457` | Confirmed. The third drops 19 bytes (16 of arguments plus the JSL frame). |
| Private tic stack at `p_think65.s:194-197` | Confirmed. There is a second site at `p_think65.s:293-301`. |
| D used as a shift register at `p_trace65.s:430-431, 502-504` | Confirmed. More sites at `:490`, `:697-699`, `:715-717`; D is restored at `:513-514`, `:726-727`. |
| Dynamic DBR in `P_RunThinkers`, compare at `p_tick65.s:250` | Confirmed (`p_tick65.s:109-117, 248-252, 303-311`). |
| No `sed` | Confirmed by grep: none in any `.s`/`.inc` or in `gendraw.py`. |
| "Byte for byte" rebuild at `U/Makefile:151-153` | The comment is at `Makefile:153-155`. |
| "Hand-assembled JML abs `$5C`, 28 sites, parsed as an instruction" | Wrong. Most are payload bytes in patch tables (`r_list65.s:3097-3209`, `r_seg65.s:4253`). They are data that is copied into code sites. |
| "Code images as `.byte`, `r_seg65.s:1063-1151, 3186-3278` … interpreted when executed" | Wrong. These are patch tables of site address, length, original bytes and replacement bytes (`r_seg65.s:1023-1024, 1060-1152`). They are never executed in place. |
| Census omits hand-assembled `JSR`/`JMP abs`/`JSL` | `.byte 0x20` (15), `.byte 0x4c` (53), `.byte 0x22` (1) exist, nearly all as patch payloads (`r_seg65.s:1064-1151, 3187-3275, 5268`). |

I did not verify the prototype's measured counts or the release-image hashes.

## 2. Findings

### B1. Tokens for code addresses break arithmetic, tables and the interpreter (blocker)

The proposal replaces code addresses with `$C0:id` tokens and pushes return tokens. Upstream treats code addresses as numbers.

| Evidence | What it does |
|---|---|
| `r_seg65.s:998-1004` | Loads `.word0 ss02Next4` etc. from `ssNexts`, adds a run-time offset (`adc dp:.tiny DC_FRAC`), stores the sum into a patch table that becomes a `JMP` operand. The target is label plus 2 or 3 bytes, not a label. |
| `r_seg65.s:1939` | `c17Return`: `.byte 0x60, 0, .byte1 (drawMid+7)`. One word store turns `RTS` into `JMP`; the three targets "share a high address byte". |
| `r_list65.s:874-902` (quoted in `R/iigs-renderer.md`) | Entry address is `flatBlocks + 4 * row`. |
| `p_sight65.s:317-318, 400-401, 519-520, 759` | 16-bit addresses of mid-function labels (`nodeDone`, `lineDone`) stored in a direct-page word, then `jmp (abs:SVEC)`. |
| `p_mobj65.s:341-342` | A function pointer pushed as two words, `.word2` then `.word0`. |

Further consequences:
- The interpreter runs original bytes and reads the same tables and struct fields. It will meet tokens written by translated code, and translated code will meet real addresses written by interpreted code.
- A 2-byte JSR token cannot be told apart from a real 16-bit return address pushed by the interpreter.
- Lockstep compares memory writes. Every call and every stored function pointer would differ from the reference.

**Fix.** Drop tokens. Use the original 24-bit address as the only representation of a code pointer and of a return address (push original PC-1, as the 65816 does). `vm_ret` and `vm_dispatch` map original address to host entry through a hash or a per-page table, and fall back to the interpreter on a miss. `RTS` and `jmp (abs,x)` use the static original program bank of the site.

### B2. "Resident" cannot be decided statically for indexed operands (blocker)

The proposal emits `static physical base + X` for about 4,773 indexed sites, over a page-granular map. X and Y are 16-bit, so the base says nothing about the page reached.

| Evidence | Pattern |
|---|---|
| `wi_stuff65.s:471-473` | `lda abs:0,y` with Y a near pointer. |
| `p_map65.s:343-346` | `tsc / tax / lda long:TT,x`: the stack frame read as bank-0 memory. |
| `r_list65.s:308-320` | `lda dp:0,x` over the 44 drawer inputs. |
| `p_tick65.s:304-310`, `r_list65.s:280-283` | `abs:OFS,x` with X a full pointer and DBR dynamic. |
| `r_seg65.s:1933, 1940` | `long:FSTEP_TABLE,x` with X up to `$FFFE`. |

Bank `$02` is split in the proposal between `$0C00-$1FFF`, `$6000-$BFFF` and RamWorks. An array spanning pages that are not physically adjacent is read wrongly with no error.

**Fix.** Give each of bank `$00` `$0900-$3FFF` and bank `$02` one linear mapping (physical = virtual + constant), fully resident or fully not. For every other indexed operand, translate the effective address at run time. Allow the static form only where range analysis proves the object stays inside one linear region, and assert it in checked builds.

### B3. Translation units are not functions (blocker)

Control moves between routines by branch, and patches enter code at computed offsets.

- `r_list65.s:566-570`: `drawAll` does `php / rep / brl pairBegin`, and control returns by `brl` to `pairBeginDone` in the middle of `drawAll`. `pairBegin` installs the borrowed exit vectors, so it sits in a self-modifying region.
- `r_list65.s:1612-1615` with `:6390-6395`: `brl spEndH` and back to `spEndDoneH`, which does `plp / rts` on a P pushed elsewhere.
- `p_tick65.s:315-319`: the call falls through into `resume`.
- B1's label-plus-offset targets.

With "any function holding a patched label is interpreted", the interpreter must hand control to translated code at arbitrary labels and back. The proposal has no such mechanism. Flag elision is also unsafe at those entries.

**Fix.** Make the unit a basic-block region. Every label reachable from another unit, from a table or from a patch payload becomes a registered entry with full flag state materialised and a recorded M/X/D/DBR. The interpreter checks the entry table on every taken branch, jump, call and return. On entry from the interpreter, compare dynamic M and X with the entry's static values and stay interpreted on mismatch.

### B4. Patchers that write through pointers are invisible to static detection (blocker)

The static detector looks for stores whose operand resolves to a text label. Three patchers write through pointers loaded from tables:

- `ssPatch`, `r_seg65.s:1035-1052`: site address from `ssSites`, bytes stored with `sta [.tiny (_Dp+4)],y`.
- The one-view patcher, `r_list65.s:3030-3051`: `sta [.tiny DC_ENTRY],y`, targets such as `OF_CMP+1`, `pixHalf`, and the data table `VWTAB+8` (`r_list65.s:3060-3100`).
- `hvPatch`, `r_thing65.s:1248-1303`: 17 plus 6 saved bytes at six sites.

They run only on a view-size change (`r_seg65.s:954`). The benchmark hook rewrites the first instruction of `vwFrame` only when the menu benchmark starts (`m_menu65.s:2213-2220, 2240-2243`). The proposal's coverage list names neither. If the reference run never triggers them, the target functions are translated, and on hardware a view-size change patches the image while the translated code stays as it was.

**Fix.**
- Parse the patch tables at build time and mark every target site and payload target as patched.
- Add view-size, detail and benchmark scripts to the reference runs.
- In release builds, make the far-write helper check writes into text ranges against a bitmap of translated code, and demote the function to interpreted (or stop) on a hit.

### M1. Promoting direct-page cells to host zero page breaks aliasing (major)

The direct page is also reached by other modes:
- `jmp (abs:SVEC)` with `SVEC .equ DC_TI` (`p_sight65.s:47, 759`) reads the vector by absolute address in bank 0.
- `flush` copies offsets 0 to `$2A` with `lda dp:0,x` (`r_list65.s:308-320`).
- `long:(WPAGE+W_FSW)` and similar reach WPAGE by long address from another D (`r_list65.s:157-183`).
- The row-block exit borrows `$0565`/`$0765` in bank 0 (`R/iigs-renderer.md`, section 2.9).

**Fix.** Do not promote single cells. Keep both direct pages as whole linear pages, addressed the same way by every mode.

### M2. D is not a per-function constant (major)

- `newPage` is documented "Any direct page" (`r_list65.s:272-276`). It is called under WPAGE (`r_seg65.s:1647, 1687, 3023`) and under `$0900` (`r_frame65.s:1561, 1836, 1970`, `am_map65.s:1503`).
- `R_WallLight`, `c26LightSetup`, `c17Setup`, `fillBytes` and `texCol` are called while D is WPAGE (`r_seg65.s:347-349, 358, 413, 440, 497, 582`).
- `dp:.tiny DC_*` under WPAGE means the WPAGE copy of offsets `$00-$2B` (`wpage.inc:7-8`, `r_seg65.s:3423-3437`).

Strict unification will report conflicts or pick one value.

**Fix.** Give D the same lattice as M/X with an explicit "either" state that is legal only in code with no dp operand. Clone functions that have dp operands and are reached under two D values. Indirect entries carry D in the entry record.

### M3. Register-transfer rule is wrong for TSC, TCS, TCD, TDC (major)

The proposal says "transfers use the destination width". These four always move 16 bits. `p_map65.s:342-344` runs `sep #0x20 / tsc / tax`; with the stated rule only the low byte of A is written, and `tax` then copies a stale B into X. TDC behaves likewise in `p_trace65.s:502-504`.

**Fix.** Make these four templates 16-bit regardless of M, with 16-bit N and Z.

### M4. V and C must survive helpers, returns and CMP (major)

- V is a return value: `sep #0x40 / rts` and `clv / rts` (`p_floor65.s:789-792`).
- V is set, kept across loads, shifts and branches, pushed by `php`, and tested after `plp` much later (`p_sight65.s:709-725, 756-757`).
- C is a return value across `rtl` (`m_config65.s:476-482`, `p_map65.s:1941-1942`).
- 32-bit compares feed C from `cmp` into `sbc`, with a far operand and `iny` in between (`p_floor65.s:798-803`, `wi_stuff65.s:471-477`).
- The `cmp ##k` template is "`sec / sbc` chain", which changes host V; 65816 CMP does not.

**Fix.**
- State as a contract that `vm_ret`, `vm_dispatch`, the far helpers, push/pull, MVN and the overlay loader preserve host C and V and the N/Z cells.
- Treat all flags as live at every `rts`/`rtl` and every registered entry unless all callers are known.
- Build CMP from `cmp` (low) and `sbc` (high) and save V around it when V is live.
- `sep #0x40` needs a template (`bit` on a constant `$40` byte).
- `php` must build a full P byte from host flags, cells and static M/X; `plp` must restore all of it.

### M5. Interrupt safety of the far layer and of 16-bit state (major)

- The IRQ handler may arrive while RAMRD or RAMWRT is on, while `$C073` selects another bank, and while `T0` holds a half-built address. `$C073` is write-only (`R/appletini-hardware.md`, section 2), so the shadow copy and the register are updated by two instructions.
- The proposal keeps `s_sound65.s` logic and the 32-byte key ring. Upstream protects state shared with the interrupt by `php / sei … plp` (`s_sound65.s:1539-1549, 2104-2150`, `iigs_asm.s:353-377`). A virtual I flag that is only a cell removes that protection.
- Upstream 16-bit loads and stores are atomic against interrupts; translated ones are two host instructions. This affects any word the host handler shares with translated code.

**Fix.**
- The IRQ handler saves and restores RAMRD, RAMWRT, the bank shadow and register, and the helper temporaries, or owns a separate set of temporaries and never calls the far layer.
- Order the bank update as "write shadow, then register" and have the handler restore from the shadow.
- Map virtual `sei`/`cli` and the I bit of `plp` to the host I flag.
- Keep interrupt-shared variables to single bytes, or read them with a double read.

### M6. 16-bit far reads that straddle a mapping boundary (major)

With `address = $4000 + (offset & $7FFF)`, a word at offset `$7FFF` has its low byte at `$BFFF` of one physical bank and its high byte at `$4000` of the next. A word at `$FFFF` continues in the next virtual bank for long and `[dp],y` modes. Lumps never cross a 64 KB bank (`R/iigs-platform.md`, section 3), but nothing keeps words off offset `$7FFF`. The cost table (2 to 3 `$Cxxx` accesses) shows the split case was not planned.

**Fix.** Give `rd16`/`wr16` a slow path when the low address byte is `$FF`, and cover it in template tests.

### M7. `jmp (abs)` and `jmp (abs,x)` read from different banks (major)

`jmp (abs)` reads its vector from bank 0. `jmp (abs,x)` and `jsr (abs,x)` read from the program bank. Neither uses DBR. The proposal says only "load the token". The 14 or more `jmp (abs:SVEC)` sites in `p_sight65.s:662-895` depend on the bank-0 read reaching the direct page.

**Fix.** Two dispatch templates, each with the static original program bank of the site.

### Minor findings

| # | Problem | Evidence | Fix |
|---|---|---|---|
| m1 | The map puts "virtual stack pages in use" in fast memory. S-relative code needs one linear region for both stacks. | Stacks at `$3FFF` down and `$1B6F` down (`iigs.scm:6-7`, `p_think65.s:182`) | Map `$0B00-$3FFF` whole, or add a depth guard |
| m2 | Release builds keep no M/X byte, but the interpreter needs M and X at every hand-over | Proposal section 2, register table | Each transition stub loads them from the entry record |
| m3 | Resident code window is 16 KB (`$2000-$5FFF`), overlays are "40 KB or less"; the load address of an overlay is not stated | Proposal section 3 | State the map; calls between overlays need stubs |
| m4 | Direct 2D drawing passes the frame-end check but may flicker where the view and 2D overlap (assumption, not verified) | `am_map65.s:1105-1109` draws with shadowing off so each byte "must change on screen once" | Keep a private buffer for overlay paths |
| m5 | Key-up inferred from the any-key flag gives one key at a time; Doom needs held combinations | Upstream reads raw ADB make/break codes (`iigs_asm.s:96-133`) | State the limit or use another input source |

## 3. Idioms that the virtual model handles correctly

- TSC/ADC/TCS frames and discards, given a fully virtual stack with original-size return frames.
- D as data, given a real virtual D.
- DBR changes by `pea / plb / plb` and `phb`/`plb` (`r_seg65.s:500`, `p_tick65.s:64-68`).
- Decimal mode: never set.

## 4. The three most important changes

1. **Use original addresses, not tokens, for every code pointer and return address**, with one address-to-entry table shared by `vm_ret`, `vm_dispatch` and the interpreter (B1). This also makes lockstep memory comparison exact.
2. **Make the unit of translation a region with registered entries, and find patched code from the patch tables and a write guard**, not from static stores and function boundaries (B3, B4).
3. **Replace page-granular static residency with linear regions for bank 0 `$0900-$3FFF` and bank `$02`, with run-time address translation for all other indexed operands, and drop zero-page promotion of direct-page cells** (B2, M1, M2).