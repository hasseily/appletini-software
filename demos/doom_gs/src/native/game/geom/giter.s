; game/geom/giter.s: the block iterators of part geom (docs/GAME.md: the
; dispatch tables, the parts). A GPL-2 derivative of upstream's
; p_map65.s (P_BlockLinesIterator with callLN, P_BlockThingsIterator with
; callLN2). The callbacks go through the dispatch table ITTAB (DCALL): its
; mechanism is this part's, its entries the parts' that own the callbacks
; (tracel's PIT_AddLineIntercepts, chasemove's PIT_AvoidDropoff, look's
; PIT_RadiusAttack, teleport's stompThing).
;
;   P_BlockLinesIterator   A = 1 when every line of block (GA_0..GA_1,
;                          GA_2..GA_3) (signed words) was given to callback
;                          GA_4 (its ITTAB number) or none needed it, 0 when
;                          the callback said stop; also 1 for a block off the
;                          map. The block's list (LVG2's blockmap through
;                          bl_get: the word at 4 + block is the list's place,
;                          docs/LEVELS.md) from its second entry (the first is
;                          the list's 0) to $FFFF; a line whose stamp is
;                          validcount is skipped, any other is stamped with
;                          validcount and given to the callback
;   P_BlockThingsIterator  the same for the things of the block (LVG1's
;                          blocklinks, then each mobj's bnext, read after
;                          the callback returns)
;
; The callback's convention (ITTAB): GA_0..GA_1 the line or mobj handle;
; C set on return to go on, clear to stop. A callback may run any game
; logic, this iterator included, so the state of a walk is on the stack
; across it (as upstream keeps LS, LN and the list position there), and the
; block list's window in BL_BUF is fetched again after it.
;
; Every callback goes through DCALL; a block's first thing comes from the
; object API (bk_get).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/geom/geom.inc"

        .export P_BlockLinesIterator, P_BlockThingsIterator
        .import ln_get, ln_dirty, mo_get, bl_get, bk_get, mul8
        .import dc_call, fc_call, fc_unbuilt, ITTAB

; ITCALL: callback A (an ITTAB number), GA_0..1 its handle; C its answer
.macro ITCALL
        DCALL ITTAB
.endmacro

; INRANGE: GT_0..1 = the block of (GA_0..1, GA_2..3), or to `out` when it
; is off the map (each word signed; 0 <= x < width, 0 <= y < height)
.macro INRANGE out
        lda GA_1                        ; x
        jmi out
        lda GA_0
        cmp G_BMW
        lda GA_1
        sbc G_BMW+1
        jcs out
        lda GA_3                        ; y
        jmi out
        lda GA_2
        cmp G_BMH
        lda GA_3
        sbc G_BMH+1
        jcs out
        lda GA_2                        ; y width + x (both below 256)
        ldy G_BMW
        jsr mul8
        clc
        lda M_R
        adc GA_0
        sta GT_0
        lda M_R+1
        adc #0
        sta GT_1
.endmacro

; ===========================================================================
; P_BlockLinesIterator
; ===========================================================================
        ROUTINE P_BlockLinesIterator
        INRANGE @true
        lda GA_4                        ; the callback
        sta GT_2
        clc                             ; the list's place: the word at 4 +
        lda GT_0                        ;   block
        adc #4
        pha
        lda GT_1
        adc #0
        tax
        pla
        jsr bl_get
        clc                             ; its first line: the word after
        lda BL_BUF                      ;   the list's 0
        adc #1
        sta GT_0
        lda BL_BUF+1
        adc #0
        sta GT_1
        stz GT_5                        ; no window
@entry: lda GT_5                        ; position GT_0..1 in the window
        beq @fetch                      ;   (GT_3..4 its first, 128
        sec                             ;   words)?
        lda GT_0
        sbc GT_3
        tax
        lda GT_1
        sbc GT_4
        bne @fetch
        cpx #128
        bcs @fetch
        txa
        asl a
        tay
        bra @read
@fetch: lda GT_0
        sta GT_3
        ldx GT_1
        stx GT_4
        jsr bl_get
        lda #1
        sta GT_5
        ldy #0
@read:  lda BL_BUF+1,y                  ; $FFFF: the list's end
        tax
        lda BL_BUF,y
        cmp #$FF
        bne @line
        cpx #$FF
        beq @true
@line:  sta GA_0                        ; the line: stamped already: skip
        stx GA_1
        jsr ln_get
        ldy #LN_VALID
        lda (GC_LP),y
        cmp G_VALID
        bne @stamp
        iny
        lda (GC_LP),y
        cmp G_VALID+1
        beq @next
@stamp: ldy #LN_VALID                   ; its stamp
        lda G_VALID
        sta (GC_LP),y
        iny
        lda G_VALID+1
        sta (GC_LP),y
        jsr ln_dirty
        lda GT_0                        ; the walk's state across the
        pha                             ;   callback
        lda GT_1
        pha
        lda GT_2
        pha
        ITCALL
        pla                             ; (C kept)
        sta GT_2
        pla
        sta GT_1
        pla
        sta GT_0
        stz GT_5                        ; the window: fetched again
        bcc @false
@next:  inc GT_0
        jne @entry
        inc GT_1
        jmp @entry
@true:  lda #1
        rts
@false: lda #0
        rts

; ===========================================================================
; P_BlockThingsIterator
; ===========================================================================
        ROUTINE P_BlockThingsIterator
        INRANGE @true
        lda GA_4
        sta GT_2
        lda GT_0                        ; the block's first thing
        ldx GT_1
        jsr bk_get
        sta GT_0
        stx GT_1
@thing: lda GT_1                        ; none: the end
        cmp #$FF
        beq @true
        lda GT_0
        sta GA_0
        lda GT_1
        sta GA_1
        lda GT_0
        pha
        lda GT_1
        pha
        lda GT_2
        pha
        ITCALL
        pla
        sta GT_2
        pla
        sta GT_1
        pla
        sta GT_0
        bcc @false
        lda GT_0                        ; its bnext, read now
        ldx GT_1
        jsr mo_get
        ldy #MO_SIZE + MA_BNEXT
        lda (GC_MP),y
        sta GT_0
        iny
        lda (GC_MP),y
        sta GT_1
        bra @thing
@true:  lda #1
        rts
@false: lda #0
        rts
