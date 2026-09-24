; Doom for the Appletini -- definitions shared by the game's assembly
; (docs/DESIGN.md section 9).
;
; The game's C (p_local.h) is the reference; the assembly modules (a_*.s)
; implement the same functions for the 6502 with the same data. Struct
; offsets come from goffsets.inc (tools/gen_offsets.py asks cc65), the
; info tables' names from info.h (states, types) through the C symbols.
;
; Conventions:
;   - Entry points callable from C follow cc65's __fastcall__: the last
;     argument in A/X (sreg for the high word of a long), the others on
;     the C stack (sp), popped by the callee; results in A/X/sreg.
;   - Internal routines take their arguments in the game's zero page
;     (GZP) and in absolute variables, documented at each.
;   - The game's zero page is caller-saved: a routine that calls out (to
;     C, or to anything that may come back into assembly) keeps what it
;     needs on the 6502 stack or in its own variables. cc65's ptr1-ptr4,
;     tmp1-tmp4 and sreg are scratch as in C.
;   - 32-bit values are little endian, signed where fixed_t.

.setcpu "65C02"
.macpack longbranch
.include "zeropage.inc"
.include "goffsets.inc"
.include "doomdata.inc"

; --- the game's zero page (segment GZP, in the kernel's KZP area) ---------
.globalzp gmo, gth, gli, gpt

; --- constants of p_local.h -------------------------------------------------
FRACBITS        = 16
NO_INDEX        = $FFFF
ST_FOREVER      = 255
MAPBLOCKSHIFT   = 23
MAXRADIUS       = 32
THINK_REMOVED   = 1
SF_FREE         = $01
SF_AMBUSH       = $02
SF_DROPPED      = $04
SF_CORPSE       = $08
SF_GIBS         = $10
SF_DORMANT      = $20
SF_NOBLOCK      = $40
SF_LOOK1        = $80
ML_BLOCKING     = 1
ML_BLOCKMONSTERS = 2
ML_TWOSIDED     = 4
BOXTOP          = 0
BOXBOTTOM       = 1
BOXLEFT         = 2
BOXRIGHT        = 3
ST_HORIZONTAL   = 0
ST_VERTICAL     = 1
ST_POSITIVE     = 2
ST_NEGATIVE     = 3
PT_ADDLINES     = 1
PT_ADDTHINGS    = 2
PT_EARLYOUT     = 4
MAXINTERCEPTS   = 128
MAXSPECIALCROSS = 8
ANG90           = $4000
ANG180          = $8000
ANGLETOFINESHIFT = 3

; mobj flags: byte in the 32-bit word, mask (info.h's MF_x_B / MF_x_M)
MF0_SPECIAL     = $01
MF0_SOLID       = $02
MF0_SHOOTABLE   = $04
MF0_NOSECTOR    = $08
MF0_NOBLOCKMAP  = $10
MF0_AMBUSH      = $20
MF0_JUSTHIT     = $40
MF0_JUSTATTACKED = $80
MF1_SPAWNCEILING = $01
MF1_NOGRAVITY   = $02
MF1_DROPOFF     = $04
MF1_PICKUP      = $08
MF1_NOCLIP      = $10
MF1_SLIDE       = $20
MF1_FLOAT       = $40
MF1_TELEPORT    = $80
MF2_MISSILE     = $01
MF2_DROPPED     = $02
MF2_SHADOW      = $04
MF2_NOBLOOD     = $08
MF2_CORPSE      = $10
MF2_INFLOAT     = $20
MF2_COUNTKILL   = $40
MF2_COUNTITEM   = $80
MF3_SKULLFLY    = $01
MF3_NOTDMATCH   = $02

; The monsters part's code segment (a_sight.s, a_enemy.s, a_inter.s): CODE,
; or MCODE when the py65 harness runs it from a code-only window over the
; far tables' bytes (tests/host/gamesim.py, -D MCODE_WINDOW). Code in it
; keeps its tables in RODATA and reads no inline data (w_ldi) and no code
; bytes as data: the window's data reads see other memory.
.macro MONCODE
.ifdef MCODE_WINDOW
        .segment "MCODE"
.else
        .segment "CODE"
.endif
.endmacro

; ---------------------------------------------------------------------------
; 32-bit moves and arithmetic on absolute variables (a, b, dst may be the
; same); the Z/N flags after them are those of the top byte. The macros
; use only unnamed labels, so they do not end a scope of @ labels.

.macro mov32 dst, src
        lda     src
        sta     dst
        lda     src+1
        sta     dst+1
        lda     src+2
        sta     dst+2
        lda     src+3
        sta     dst+3
.endmacro

.macro ldi32 dst, value
        lda     #<(value)
        sta     dst
        lda     #>(value)
        sta     dst+1
        lda     #^(value)
        sta     dst+2
        lda     #<((value) >> 24)
        sta     dst+3
.endmacro

.macro add32 dst, a1, b1
        clc
        lda     a1
        adc     b1
        sta     dst
        lda     a1+1
        adc     b1+1
        sta     dst+1
        lda     a1+2
        adc     b1+2
        sta     dst+2
        lda     a1+3
        adc     b1+3
        sta     dst+3
.endmacro

.macro sub32 dst, a1, b1
        sec
        lda     a1
        sbc     b1
        sta     dst
        lda     a1+1
        sbc     b1+1
        sta     dst+1
        lda     a1+2
        sbc     b1+2
        sta     dst+2
        lda     a1+3
        sbc     b1+3
        sta     dst+3
.endmacro

; N set iff a1 < b1 (signed 32-bit)
.macro lt32 a1, b1
        sec
        lda     a1
        sbc     b1
        lda     a1+1
        sbc     b1+1
        lda     a1+2
        sbc     b1+2
        lda     a1+3
        sbc     b1+3
        bvc     :+
        eor     #$80
:
.endmacro

; Z set iff a1 == b1
.macro eq32 a1, b1
        lda     a1
        cmp     b1
        bne     :+
        lda     a1+1
        cmp     b1+1
        bne     :+
        lda     a1+2
        cmp     b1+2
        bne     :+
        lda     a1+3
        cmp     b1+3
:
.endmacro

; dst = -src
.macro neg32 dst, src
        sec
        lda     #0
        sbc     src
        sta     dst
        lda     #0
        sbc     src+1
        sta     dst+1
        lda     #0
        sbc     src+2
        sta     dst+2
        lda     #0
        sbc     src+3
        sta     dst+3
.endmacro

; dst = the int16 at src as fixed (src << 16)
.macro fix16 dst, src
        stz     dst
        stz     dst+1
        lda     src
        sta     dst+2
        lda     src+1
        sta     dst+3
.endmacro

; the field at (ptr),off <-> an absolute 32-bit variable
.macro ldf32 dst, ptr, off
        ldy     #off
        lda     (ptr),y
        sta     dst
        iny
        lda     (ptr),y
        sta     dst+1
        iny
        lda     (ptr),y
        sta     dst+2
        iny
        lda     (ptr),y
        sta     dst+3
.endmacro

.macro stf32 src, ptr, off
        ldy     #off
        lda     src
        sta     (ptr),y
        iny
        lda     src+1
        sta     (ptr),y
        iny
        lda     src+2
        sta     (ptr),y
        iny
        lda     src+3
        sta     (ptr),y
.endmacro

; A/X/sreg (a C long) <-> an absolute 32-bit variable
.macro ret32 src
        lda     src+3
        sta     sreg+1
        lda     src+2
        sta     sreg
        ldx     src+1
        lda     src
.endmacro

.macro get32 dst
        sta     dst
        stx     dst+1
        lda     sreg
        sta     dst+2
        lda     sreg+1
        sta     dst+3
.endmacro
