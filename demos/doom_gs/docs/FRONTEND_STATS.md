# Front end statistics

Written by `python3 tools/v816/frontend.py --stats docs/FRONTEND_STATS.md`. Do not edit it:
`tests/test_frontend.py` compares this file with what the tool writes.

The input is upstream at the pinned commit (`tools/fetch_upstream.py`), built as upstream's Makefile
builds it by default: `-D TICSTEP=1` for the game, `-D MUSIC_MENU=1` for `m_menu65.s`, no flags for
`boot.s` and `loader.s`. `drawcol.s` and `loadfont.s` are made by upstream's `gendraw.py` and `loadfont.py`.

**Left out of all counts:** `cal_integer.s`. It is a copy of a Calypsi library file, and its licence does not
allow the port to keep anything derived from it. The front end parses it like the other files, and
section 1 says whether it has errors. `frontend.py --with-restricted` prints the counts with it, on the console only.

## 1. Result

|  | Count |
|---|---:|
| Sources (runs of the assembler) | 64 |
| of them in the game / boot / loader | 62 / 1 / 1 |
| Sources with errors | 0 |
| Errors | 0 |
| Unknown directives, mnemonics or macros | 0 |

An unknown directive or mnemonic is an error; the parser has no way to skip a line.

## 2. Files and lines

| Link unit | Sources | Files read | Lines of those files | Lines after the preprocessor |
|---|---:|---:|---:|---:|
| game | 61 | 75 | 87,142 | 141,940 |
| boot | 1 | 1 | 101 | 101 |
| loader | 1 | 3 | 1,452 | 1,450 |
| all | 63 | 78 | 88,684 | 143,491 |

"Files read" counts each file once, include files too; `memmap.inc` and other include files are read by the
boot and loader as well, so the rows do not add up to the last one. The lines after the preprocessor count an
include file each time it is read, and leave out the preprocessor lines and the groups that `#if` skips.

Upstream's `src/iigs` has 77 files `*.s` and `*.inc` with 81,293 lines (not counting the file that is left out).
Files of `src/iigs` that the default build does not read: `segclip.inc`.

Preprocessor lines in `src/iigs`: `#define` 126, `#elif` 6, `#else` 62, `#endif` 133, `#error` 1, `#if` 127, `#ifdef` 1, `#ifndef` 5, `#include` 151, `#undef` 93.

## 3. Macros

|  | Count |
|---|---:|
| `.macro` lines in `src/iigs` | 130 |
| Definitions that the default build reads | 126 |
| Definitions read, counted once for each source that reads them | 214 |
| Macro expansions | 1,358 |
| Macros that are used | 96 |
| Deepest nesting of expansions | 3 |

With the file that is left out, `src/iigs` has 131 `.macro` lines, the number that
`docs/ARCHITECTURE.md` (section 0) expects (`tests/test_frontend.py` checks it).

`.macro` lines that the default build does not read, because an `#if` skips them:

- `build/upstream/src/iigs/d_main65.s:57` PHASE
- `build/upstream/src/iigs/r_bsp65.s:89` PHASE
- `build/upstream/src/iigs/r_frame65.s:73` PHASE
- `build/upstream/src/iigs/r_wall65.s:324` PHASE

The macros with the most uses:

| Macro | Uses |
|---|---:|
| STATE | 314 |
| EMIT | 160 |
| KEYDEF | 128 |
| SLT32 | 59 |
| PUTWD | 54 |
| PUTWN | 50 |
| STEP8E | 35 |
| DW0 | 32 |
| DW8 | 32 |
| ARGAP | 28 |
| INFOINDEX | 21 |
| ENTER | 21 |
| LEAVE | 19 |
| INFOADDR | 17 |
| PHASE | 16 |
| PSUM | 16 |
| DW4 | 16 |
| MINFO | 14 |
| FSCUTE | 13 |
| VIS16 | 13 |

## 4. Instructions before and after macro expansion

| Link unit | Before | After | Difference |
|---|---:|---:|---:|
| game | 63,971 | 67,138 | 3,167 |
| boot | 56 | 56 | 0 |
| loader | 1,005 | 1,005 | 0 |
| all | 65,032 | 68,199 | 3,167 |

"Before" counts the instruction lines of the preprocessed text: a macro body counts once for each source that
reads its definition, and a use of a macro does not count. "After" counts the instructions of the IR, which is
what the encoder will see. Both include the generated `drawcol.s` and `loadfont.s`.

Instruction lines in the files of `src/iigs` as they are written (no preprocessor, each file once): 58,074.

## 5. Instructions by mnemonic

| Mnemonic | Lines in `src/iigs` | Instructions in the IR |
|---|---:|---:|
| lda | 11,232 | 13,350 |
| sta | 7,971 | 10,196 |
| adc | 1,889 | 3,121 |
| jsr | 2,239 | 2,269 |
| ldy | 2,077 | 2,085 |
| cmp | 1,959 | 2,070 |
| asl | 1,696 | 1,771 |
| xba | 619 | 1,731 |
| clc | 1,359 | 1,647 |
| and | 1,083 | 1,559 |
| beq | 1,435 | 1,455 |
| ldx | 1,394 | 1,429 |
| bne | 1,360 | 1,369 |
| tay | 582 | 1,301 |
| sbc | 1,134 | 1,272 |
| rts | 1,167 | 1,159 |
| jsl | 1,120 | 1,118 |
| iny | 1,039 | 1,112 |
| tax | 1,010 | 1,104 |
| sec | 989 | 1,059 |
| bra | 897 | 977 |
| tya | 443 | 927 |
| bcc | 716 | 801 |
| bcs | 691 | 796 |
| rtl | 694 | 705 |
| pla | 597 | 634 |
| txa | 596 | 625 |
| lsr | 583 | 623 |
| stz | 595 | 592 |
| rep | 577 | 588 |
| inc | 542 | 585 |
| eor | 469 | 560 |
| brl | 535 | 556 |
| pha | 547 | 546 |
| inx | 503 | 539 |
| sep | 527 | 534 |
| jmp | 509 | 522 |
| stx | 504 | 504 |
| bpl | 465 | 464 |
| bmi | 401 | 429 |
| ora | 381 | 385 |
| cpx | 287 | 301 |
| dex | 281 | 282 |
| dec | 240 | 248 |
| bvc | 167 | 240 |
| plb | 205 | 220 |
| pei | 140 | 188 |
| dey | 164 | 161 |
| rol | 121 | 123 |
| cpy | 121 | 121 |
| plx | 115 | 114 |
| phx | 113 | 113 |
| sty | 100 | 105 |
| ply | 92 | 92 |
| ror | 88 | 91 |
| bit | 82 | 82 |
| tyx | 74 | 77 |
| phb | 70 | 71 |
| plp | 71 | 71 |
| php | 64 | 64 |
| nop | 49 | 51 |
| phy | 49 | 49 |
| txy | 47 | 47 |
| pea | 29 | 29 |
| bvs | 21 | 27 |
| tcd | 23 | 25 |
| tsc | 25 | 25 |
| sei | 24 | 24 |
| pld | 19 | 21 |
| tcs | 19 | 18 |
| phd | 15 | 17 |
| xce | 12 | 12 |
| phk | 8 | 8 |
| clv | 3 | 3 |
| rti | 3 | 3 |
| tdc | 3 | 3 |
| cld | 2 | 2 |
| cli | 1 | 1 |
| txs | 1 | 1 |
| **total** | 58,074 | 68,199 |

79 different mnemonics are used.

## 6. Instructions by addressing-mode syntax

The syntax as written, in the IR (after expansion). `e` stands for an expression.

| Syntax | Instructions |
|---|---:|
| `e` | 30,528 |
| no operand | 14,664 |
| `##e` | 8,330 |
| `e,x` | 4,157 |
| `[e],y` | 3,087 |
| `a` | 3,022 |
| `#e` | 2,704 |
| `[e]` | 694 |
| `e,y` | 689 |
| `e,s` | 227 |
| `(e),y` | 35 |
| `(e,x)` | 32 |
| `(e)` | 30 |

How the operands say their size: the prefix, and the relocation operator at the top of the expression.
Immediate operands are in the row "nothing" unless they have an operator.

| Written | Operands |
|---|---:|
| nothing | 17,541 |
| `.near` | 8,927 |
| `dp: .tiny` | 7,139 |
| `long:` | 5,080 |
| `.tiny` | 3,749 |
| `abs:` | 2,562 |
| `.kbank` | 2,376 |
| `dp:` | 2,094 |
| `.word0` | 351 |
| `abs: .near` | 253 |
| `.word2` | 231 |
| `abs: .word0` | 131 |
| `.byte2` | 47 |
| `.byte0` | 16 |
| `.byte1` | 16 |

Relocation operators below the top of an expression, which the manual does not allow ("they must appear at
the top level"): 2. They have the form `.word0 NAME + 2`, which is `(.word0 NAME) + 2` by the precedence of the
manual. The image match will show what the assembler makes of them.

## 7. Section fragments by section name

Each `.section` directive starts a fragment, and each source starts in a fragment of the section `code`
(manual, 21.4). The kind is as written; "(none)" means that no directive gave one. "With content" leaves
out the fragments that hold nothing but equates, which the linker has nothing to place for: the fragment at
the start of most sources is one.

| Section | Kind | Fragments | With content |
|---|---|---:|---:|
| znear | bss | 65 | 65 |
| code | (none), text | 64 | 4 |
| coldcode | text | 52 | 51 |
| farcode | text | 37 | 36 |
| logiccode | text | 30 | 30 |
| cfar | rodata | 26 | 26 |
| bspcode | text | 16 | 16 |
| cnear | rodata | 13 | 13 |
| hotmul | text | 8 | 8 |
| near | data | 8 | 8 |
| ztiny | bss | 8 | 8 |
| zfar | bss | 7 | 7 |
| coldfar | bss | 6 | 6 |
| detailimg | text | 5 | 5 |
| vwcode | text | 5 | 5 |
| onecold | text | 4 | 4 |
| core5cold | text | 3 | 3 |
| lvlcode | text | 3 | 3 |
| onelist | text | 3 | 3 |
| segcode | text | 3 | 3 |
| startup | text | 3 | 3 |
| fourlist | text | 2 | 2 |
| halflist | rodata, text | 2 | 2 |
| hotlist | text | 2 | 2 |
| irqcode | text | 2 | 1 |
| loader | text | 2 | 2 |
| logicfar | text | 2 | 2 |
| uicode | text | 2 | 2 |
| vw3code | text | 2 | 2 |
| amcode | text | 1 | 1 |
| boot | text | 1 | 1 |
| cmaps | bss | 1 | 1 |
| core14 | text | 1 | 1 |
| core16head | text | 1 | 1 |
| core16rows | text | 1 | 1 |
| core19save | bss | 1 | 1 |
| data_init_table | (none) | 1 | 0 |
| diskcode | text | 1 | 1 |
| fourimg | text | 1 | 1 |
| fourui | text | 1 | 1 |
| guardcode | text | 1 | 1 |
| hotdraw | text | 1 | 1 |
| irqcold | text | 1 | 1 |
| irqstate | text | 1 | 1 |
| levelsetup | text | 1 | 1 |
| listfuzz | text | 1 | 1 |
| listovl | text | 1 | 1 |
| maskcode | text | 1 | 1 |
| muscode | text | 1 | 1 |
| paircode | text | 1 | 1 |
| qstride | text | 1 | 1 |
| registers | (none) | 1 | 1 |
| segmore | text | 1 | 1 |
| segthird | text | 1 | 1 |
| segwalls | text | 1 | 1 |
| stack | (none) | 1 | 0 |
| thirdimg | text | 1 | 1 |
| thirdlist | text | 1 | 1 |
| **total** |  | 414 | 349 |

58 section names.

## 8. Other items of the IR

| Item | Count |
|---|---:|
| Labels | 4,651 |
| Local labels (`N$`) | 4,364 |
| Local label scopes | 6,072 |
| References to a local label across an equate | 28 |
| Equates | 47,856 |
| of them code positions (the value uses `.`) | 51 |
| `.ascii` | 201 |
| `.asciz` | 299 |
| `.byte` | 2,117 |
| `.long` | 1,263 |
| `.space` | 1,856 |
| `.word` | 3,501 |
| `.extern` names | 1,547 |
| `.public` names | 841 |

Equates are counted for each source that reads them; most are in include files.

**Local labels and equates.** The manual says that a local label is visible between two labels that are not
local. It does not say whether the name of an equate is such a label. The sources decide it: the references
counted above have an equate between the reference and its label, in the same scope, so an equate cannot end
a scope. With that rule every reference finds its label, and no scope defines a label twice.

## 9. Comparison with the research notes

`docs/research/iigs-platform.md` (section 6) counted source lines with awk and grep: no preprocessor, a macro
body once, no generated file, and with the file that this report leaves out. "Lines" below is the same kind
of count by `tools/v816/stats.py`; "IR" is the count after the preprocessor and macro expansion, with the
generated files.

| Construct | Research | Lines | Difference | IR |
|---|---:|---:|---:|---:|
| rep/sep | 1,107 | 1,104 | -3 | 1,122 |
| jsl | 1,120 | 1,120 | 0 | 1,118 |
| jsr | 2,243 | 2,239 | -4 | 2,269 |
| long: | 4,678 | 4,681 | 3 | 5,080 |
| [dp] | 2,872 | 2,811 | -61 | 3,781 |
| ,s | 316 | 240 | -76 | 227 |
| ## immediate | 8,151 | 8,091 | -60 | 8,330 |
| .near | 9,106 | 9,106 | 0 | 9,180 |
| phb/plb | 275 | 275 | 0 | 291 |
| xba | 620 | 619 | -1 | 1,731 |
| mvn | 33 | 32 | -1 | 40 |
| pei | 151 | 140 | -11 | 188 |
| pea | 29 | 29 | 0 | 29 |
| phd/pld | 34 | 34 | 0 | 38 |
| tcd | 23 | 23 | 0 | 25 |
| tsc/tcs | 54 | 44 | -10 | 43 |
| txy/tyx | 122 | 121 | -1 | 124 |
| brl | 534 | 535 | 1 | 556 |
| jmp long: | 189 | 189 | 0 | 192 |
| stz | 606 | 595 | -11 | 592 |
| bra | 905 | 897 | -8 | 977 |
| phx/phy/plx/ply | 387 | 369 | -18 | 368 |

|  | Research | Here |
|---|---:|---:|
| Lines of `src/iigs` | 82,470 | 81,293 |
| Instruction lines | 58,691 | 58,074 |
| `.macro` lines | 131 | 130 |
| Instructions after expansion, game only | 67,235 | 67,138 |
| `#include` lines | 152 | 151 |
| `#if` lines | 127 | 127 |
| `#define` lines | 126 | 126 |
| `#undef` lines | 93 | 93 |

Why the numbers differ:

1. **The file that is left out.** Every "Lines" number above is without `cal_integer.s`; the research counted
   it. With it, the counts of this tool equal the research for all constructs of the table except the four of
   points 2 and 3, and the `.macro` lines are 131 and the `#include` lines 152. `tests/test_frontend.py` checks
   these equalities in memory, so that no number of the file is written here.
2. **Labels made by the preprocessor.** `segvar.inc` and `segclip.inc` have instructions after labels of the
   form `L(name):`. The research did not count those lines; this tool does. They hold 3 `rep`, 3 `long:` and
   1 `brl`, which are the differences of +3, +3 and +1 that remain for `rep/sep`, `long:` and `brl` when the
   file of point 1 is counted.
3. **MVN.** The research counted the 33 `.byte` lines that start with `0x54`. One of them is a table
   (`r_list65.s:3816`, 16 values). This tool counts a line as MVN when it has the opcode alone or the opcode
   and two bank bytes: 32 lines.
4. **Lines.** The research total of 82,470 includes the three linker scripts (`iigs.scm`, `boot.scm`,
   `loader.scm`: 239 lines). Without them it is 82,231, which is the number of this tool with the file of
   point 1.
5. **Instruction lines.** With the file of point 1 this tool counts 17 instruction lines fewer than
   the research, although it counts the 27 instruction lines of point 2 that the research did not. The
   research script is not in the repository, so the 44 lines that it counted and this tool does not are not
   identified; uses of macros with names in lower case, which look like mnemonics, may be among them. The
   difference is 0.07 percent, and the counts of all single mnemonics of the table agree.
6. **Macro count.** 131 is the number of `.macro` lines. The 105 of the research notes is not reproduced by
   any count of this tool; the notes do not say how it was made.
7. **Instructions after expansion.** `docs/ARCHITECTURE.md` (section 2.2) reports 67,235 from a prototype
   that is not in the repository. The number here is without `cal_integer.s`; what the prototype counted is
   not known, so the difference is not explained.
8. **IR against lines.** The IR has more of most constructs because macro uses are expanded, `segvar.inc` is
   read for each wall variant, and `drawcol.s` is generated code (`xba` and `[dp]` grow most). It has
   fewer where an `#if` of the default build skips code.

## 10. Preprocessor cross-check

`python3 tools/v816/cppcheck.py` compares the output of `tools/v816/cpp.py` with that of
`clang -E -P -x assembler-with-cpp` for every source, with the same `-I` and `-D`. The outputs must be equal
line by line after runs of white space are made one blank and empty lines are dropped.
`tests/test_cppcheck.py` runs the comparison where clang is installed: all 64 sources are equal.

clang is not part of the build. The release image, not clang, decides whether the preprocessor of the Calypsi
assembler behaves the same; the known risks are:

- a `#define` body keeps its `;` comment (C knows no such comment), so the comment arrives where the macro is
  used. The sources use such macros at the end of a line only: the IR is the same when the comments are
  dropped from the bodies (`tests/test_frontend.py`);
- the text after `#else` and `#endif` is ignored (`segvar.inc:245` has a `;` comment there);
- a number like `0x1e+NAME` is one preprocessing token in C, so `NAME` would not be expanded. The sources
  have no such text (`tests/test_frontend.py`).
