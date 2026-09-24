; Doom for the Appletini -- definitions shared by the SPECIALS part's
; assembly (a_spec.s, a_movers.s; docs/DESIGN.md section 9).
;
; The C reference (p_spec.c and the other p_*.c of the part, compiled on
; the host) has the same records; their layouts here are the 6502's own
; (only this part reads them), in the C structs' order.

; ---- the movers: a thinker block (THINKER_BLOCK bytes) ---------------------
; every mover (p_spec.h mover_t)
MV_SECTOR   = TH_SIZE               ; u16
MV_TYPE     = TH_SIZE + 2           ; u8
MV_SPEED    = TH_SIZE + 3           ; u8, eighths of a map unit per tic
MV_ACC      = TH_SIZE + 4           ; u8, eighths owed
MV_DIR      = TH_SIZE + 5           ; s8: door/floor/ceiling direction, plat status
; vldoor_t
DR_TOP      = TH_SIZE + 6           ; s16 topheight
DR_WAIT     = TH_SIZE + 8           ; u16 topwait
DR_COUNT    = TH_SIZE + 10          ; u16 topcountdown
; floormove_t
FM_CRUSH    = TH_SIZE + 6           ; u8
FM_NEWSPEC  = TH_SIZE + 7           ; u8
FM_TEX      = TH_SIZE + 8           ; u16 texture (flat)
FM_DEST     = TH_SIZE + 10          ; s16 floordestheight
; plat_t (MV_DIR is the status)
PT_LOW      = TH_SIZE + 6           ; s16
PT_HIGH     = TH_SIZE + 8           ; s16
PT_WAIT     = TH_SIZE + 10          ; u8
PT_COUNT    = TH_SIZE + 11          ; u8
PT_OLD      = TH_SIZE + 12          ; u8 oldstatus
PT_CRUSH    = TH_SIZE + 13          ; u8
PT_TAG      = TH_SIZE + 14          ; u16
; ceiling_t
CE_BOTTOM   = TH_SIZE + 6           ; s16
CE_TOP      = TH_SIZE + 8           ; s16
CE_CRUSH    = TH_SIZE + 10          ; u8
CE_OLD      = TH_SIZE + 11          ; s8 olddirection
CE_TAG      = TH_SIZE + 12          ; u16
MOVER_SIZE  = TH_SIZE + 14
.assert MOVER_SIZE <= THINKER_BLOCK, error, "a mover fits a thinker block"

PLAT_UP     = 0
PLAT_DOWN   = 1
PLAT_WAITING = 2
PLAT_STASIS = 3

; T_MovePlane's results
RES_OK      = 0
RES_CRUSHED = 1
RES_PASTDEST = 2

; speeds in eighths of a unit per tic (p_spec.h SPEED)
VDOORSPEED  = 16
VDOORWAIT   = 150
FLOORSPEED  = 8
CEILSPEED   = 8
PLATSPEED   = 8
PLATWAIT    = 3

; ---- lights (p_spec.h light_t, 8 bytes) --------------------------------------
LT_SECTOR   = 0
LT_KIND     = 2
LT_COUNT    = 3
LT_MIN      = 4
LT_MAX      = 5
LT_CUR      = 6
LT_AUX      = 7
LT_SIZE     = 8
LT_FLASH    = 0
LT_STROBE   = 1
LT_GLOW     = 2
LT_FIRE     = 3

; ---- the specials' bank (kbanks - 2) -------------------------------------------
JOURNAL_BASE = $0200
JOURNAL_MAX = 341

; ---- the neighbour searches (a_spec.s nb_find, the kind in A) --------------------
NB_LOWFLOOR = 0
NB_HIGHFLOOR = 1
NB_NEXTFLOOR = 2
NB_LOWCEIL  = 3
NB_HIGHCEIL = 4
NB_MINLIGHT = 5
NB_MAXLIGHT = 6

; the specials part's code segment: CODE, or MCODE2 when the py65 harness
; runs it from a code-only window (tests/host/gamesim.py, -D MCODE_WINDOW;
; the window holds the C code too). Tables are in RODATA; nothing reads
; code bytes as data.
.macro SPECCODE
.ifdef MCODE_WINDOW
        .segment "MCODE2"
.else
        .segment "CODE"
.endif
.endmacro

; the mover pointer mv into gpt (after any call that may have used gpt)
.macro ldmv
        lda     mv
        sta     gpt
        lda     mv+1
        sta     gpt+1
.endmacro

; N set iff the signed 16-bit a1 < b1 (absolute operands)
.macro slt16 a1, b1
        lda     a1
        cmp     b1
        lda     a1+1
        sbc     b1+1
        bvc     :+
        eor     #$80
:
.endmacro

; dst = src (16 bits, absolute)
.macro mov16 dst, src
        lda     src
        sta     dst
        lda     src+1
        sta     dst+1
.endmacro
