; game/secfind/secfind.s: part secfind of the game's tic code
; (docs/GAME.md): the sector finders, the tag search, the animated textures and
; flats, the switch timers, the scrolling walls and the light thinkers.
; A GPL-2 derivative of upstream's p_spec65.s (getNextSector, the
; P_Find*Surrounding finders and their `around`, P_FindSectorFromLineTag,
; P_CheckTag, P_UpdateSpecials with buttonDone and mod3, T_Scroll),
; p_floor65.s (P_FindNextHighestFloor), p_lights65.s (T_LightFlash,
; T_StrobeFlash, T_Glow, EV_LightTurnOn), r_data65.s (P_UpdateAnimatedFlat)
; and p_switch65.s (lnLight, LSTAB's light entry).
;
; The native interfaces:
;
;   getNextSector   A:X = a line, Y = a sector -> A = the line's other
;                   sector, NO_SECTOR ($FF) when there is none (a one-sided
;                   line, or both sides the sector)
;   nextSector      A = a sector, X:Y = i (X low) -> X = 1 when i is not
;                   below its line count; else X = 0, A = getNextSector(its
;                   line i, the sector)
;   P_FindLowestFloorSurrounding, P_FindHighestFloorSurrounding,
;   P_FindLowestCeilingSurrounding, P_FindNextHighestFloor
;                   A = a sector -> GA_0-3 = the height (fixed_t)
;   around          (the finders' loop) SB_SEC, SB_MODE (the render
;                   record's offset, bit 7 the highest), SB_BEST
;   P_FindSectorFromLineTag
;                   A:X = a line, Y = start ($FF: -1) -> A = the next
;                   sector after start with the line's tag, $FF none
;   P_CheckTag      A:X = a line -> A = 1 (a tag, or a special that needs
;                   none) or 0, Z from A
;   P_UpdateSpecials, P_UpdateAnimatedFlat
;                   no arguments: NUKAGE, TEXTRANS, the switch timers
;   mod3            A:X = a word (A low) -> A = it % 3 (unsigned)
;   buttonDone      A = a button's offset in G_BUTTONS
;   EV_LightTurnOn  A:X = a line, Y = the light level (0: the brightest of
;                   the sectors next to each)
;   THTAB's T_LightFlash, T_StrobeFlash, T_Glow, T_Scroll
;                   GA_0-1 = the thinker's handle (upstream's _Dp[0-3])
;   LSTAB's lnLight GA_0-1 = the line, GA_2 = the argument (35) -> A = 1
;
; Light levels are the sectors' render records' bytes (0-255): upstream's
; 16-bit signed compares of a light with another light are unsigned byte
; compares; with a special's word (min, max) they stay 16-bit signed.
;
; As integrated: a
; side's record and a sector's line table through the object API (sd_get,
; sd_put, lt_get); GTAB's animated_texture_basepic at ggame.inc's
; GT_BASEPIC, read with g_get (GTAB: no cache holds it); p_lights65.s's
; equates GLOWSPEED, STROBEBRIGHT as ggame.inc's UGLOWSPEED,
; USTROBEBRIGHT.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export getNextSector, nextSector, around
        .export P_FindLowestFloorSurrounding, P_FindHighestFloorSurrounding
        .export P_FindLowestCeilingSurrounding, P_FindNextHighestFloor
        .export P_FindSectorFromLineTag, P_CheckTag, P_UpdateSpecials
        .export P_UpdateAnimatedFlat, mod3, buttonDone, T_Scroll
        .export T_LightFlash, T_StrobeFlash, T_Glow, EV_LightTurnOn, lnLight
        .import ln_get, sec_get, sec_dirty, sp_get, sp_dirty
        .import g_get, g_random, S_StartSound2, sd_get, sd_put, lt_get
        .import fc_call, fc_unbuilt

        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the sector's heights"
        .assert SIDE_SIZE = 8 && SIDE_TEXOFS = 0, error, "the side record"
        .assert BT_SIZE = 9 && U_MAXBUTTONS = 4, error, "the buttons"
        .assert NO_SECTOR = $FF && SEC_CAP <= $FF, error, "a sector a byte"

; ---------------------------------------------------------------------------
; Temporaries (GT_0-6: no API call or fc_call changes them) and the
; scratch block (SB_SECFIND: what a routine keeps across an FCALL)
; ---------------------------------------------------------------------------
Q0      = GT_0
Q1      = GT_1
Q2      = GT_2
Q3      = GT_3
Q4      = GT_4
Q5      = GT_5
Q6      = GT_6

SB_SEC   = SB_SECFIND           ; the finders, EV_LightTurnOn: the sector
SB_I     = SB_SECFIND + 1       ;   a line's index in it (2)
SB_BEST  = SB_SECFIND + 3       ;   the height so far (4)
SB_MODE  = SB_SECFIND + 7       ;   around: the field, bit 7 the highest
SB_CUR   = SB_SECFIND + 8       ; P_FindNextHighestFloor: its floor (4)
SB_FOUND = SB_SECFIND + 12      ;   a floor above it seen
SB_LINE  = SB_SECFIND + 13      ; EV_LightTurnOn: the line (2)
SB_BRT   = SB_SECFIND + 15      ;   bright
SB_TB    = SB_SECFIND + 16      ;   tbright
SB_BTN   = SB_SECFIND + 17      ; P_UpdateSpecials: a button's offset
SB_BD    = SB_SECFIND + 18      ; buttonDone: its button's offset
SB_END   = SB_SECFIND + 19
        .assert SB_END <= SB_SECFIND + SB_SECFIND_SIZE, error, "scratch"
SB_SD    = SD_BUF               ; the object API's side record (sd_get)

; around is upstream's label of P_FindLowestCeilingSurrounding's head
; (p_spec65.s:around): the part table names it, so its group
; is the placement's

; GNS: A = getNextSector(the line at GC_LP, sector Q0)
.macro GNS
        ldy #LINE_SIZE          ; its front sector: not sec, the front one
        lda (GC_LP),y
        cmp Q0
        bne :+
        iny                     ; sec: the back one (the front again for a
        lda (GC_LP),y           ;   one-sided line), if not sec
        cmp Q0
        bne :+
        lda #NO_SECTOR
:
.endmacro

; LT_COUNT: GA_0-1 = a light thinker: sp_get; its count (the word at
; offset `ofs`) - 1 stored and the special dirty; Z set when it is 0
.macro LT_COUNT ofs
        lda GA_0
        ldx GA_1
        jsr sp_get
        ldy #ofs
        lda (GC_XP),y
        sec
        sbc #1
        sta (GC_XP),y
        sta Q0
        iny
        lda (GC_XP),y
        sbc #0
        sta (GC_XP),y
        ora Q0
        php
        jsr sp_dirty
        plp
.endmacro

; LT_SEC: GC_SP = the sector of the light thinker at GC_XP, A its light
.macro LT_SEC
        ldy #SP_SECTOR
        lda (GC_XP),y
        jsr sec_get
        ldy #SEC_LIGHT
        lda (GC_SP),y
.endmacro

; ===========================================================================
; p_spec65.s: the sector finders
; ===========================================================================

; getNextSector: A:X = a line, Y = a sector -> A = the other sector or $FF
        ROUTINE getNextSector
        sty Q0
        jsr ln_get
        GNS
        rts

; nextSector: A = a sector, X:Y = i -> X = 1 (and C set) past its lines;
; else X = 0 (C clear), A = the other sector of its line i ($FF none). The
; callers test X: fc_call does not keep P when it restores a group on the
; return (gcall.s)
        ROUTINE nextSector
        sta Q0
        stx Q1
        sty Q2
        jsr sec_get
        ldy #SEC_SIZE + SG_LCOUNT       ; i < linecount (unsigned)
        lda Q1
        cmp (GC_SP),y
        iny
        lda Q2
        sbc (GC_SP),y
        bcc :+
        ldx #1                          ; (C set)
        rts
:       ldy #SEC_SIZE + SG_LFIRST       ; its lines[i]
        clc
        lda (GC_SP),y
        adc Q1
        pha
        iny
        lda (GC_SP),y
        adc Q2
        tax
        pla
        jsr lt_get
        jsr ln_get
        GNS
        ldx #0
        clc
        rts

; P_FindLowestFloorSurrounding: A = a sector -> GA_0-3 = the lowest floor
; of it and the sectors next to it
        ROUTINE P_FindLowestFloorSurrounding
        sta SB_SEC
        jsr sec_get
        ldy #SEC_FLOOR + 3      ; its floor
:       lda (GC_SP),y
        sta SB_BEST,y
        dey
        bpl :-
        lda #SEC_FLOOR          ; the lower
        sta SB_MODE
        FCALL around
        rts

; P_FindHighestFloorSurrounding: A = a sector -> GA_0-3 = the highest floor
; of the sectors next to it, -32000 * FRACUNIT at least
        ROUTINE P_FindHighestFloorSurrounding
        sta SB_SEC
        stz SB_BEST
        stz SB_BEST+1
        stz SB_BEST+2
        lda #>(-32000 & $FFFF)
        sta SB_BEST+3
        lda #SEC_FLOOR | $80    ; the higher
        sta SB_MODE
        FCALL around
        rts

; P_FindLowestCeilingSurrounding: A = a sector -> GA_0-3 = the lowest
; ceiling of the sectors next to it, 32000 * FRACUNIT at most
        ROUTINE P_FindLowestCeilingSurrounding
        sta SB_SEC
        stz SB_BEST
        stz SB_BEST+1
        stz SB_BEST+2
        lda #>32000
        sta SB_BEST+3
        lda #SEC_CEIL           ; the lower
        sta SB_MODE
        FCALL around
        rts
        .assert <32000 = 0 && <(-32000 & $FFFF) = 0, error, "32000"

; around: SB_BEST = the lowest (SB_MODE bit 7 clear) or the highest (set)
; of SB_BEST and the field at SB_MODE & $7F of the sectors next to SB_SEC;
; GA_0-3 = SB_BEST
        ROUTINE around
        stz SB_I
        stz SB_I+1
@line:  lda SB_SEC
        ldx SB_I
        ldy SB_I+1
        FCALL nextSector
        cpx #0
        bne @done
        cmp #NO_SECTOR
        beq @next
        jsr sec_get
        lda SB_MODE
        and #$7F
        tay
        bit SB_MODE
        bmi @higher
        sec                     ; the lower: it < SB_BEST
        lda (GC_SP),y
        sbc SB_BEST
        iny
        lda (GC_SP),y
        sbc SB_BEST+1
        iny
        lda (GC_SP),y
        sbc SB_BEST+2
        iny
        lda (GC_SP),y
        sbc SB_BEST+3
        bra @sign
@higher:
        sec                     ; the higher: SB_BEST < it
        lda SB_BEST
        sbc (GC_SP),y
        iny
        lda SB_BEST+1
        sbc (GC_SP),y
        iny
        lda SB_BEST+2
        sbc (GC_SP),y
        iny
        lda SB_BEST+3
        sbc (GC_SP),y
@sign:  bvc :+
        eor #$80
:       bpl @next
        dey                     ; SB_BEST = it
        dey
        dey
        ldx #0
:       lda (GC_SP),y
        sta SB_BEST,x
        iny
        inx
        cpx #4
        bne :-
@next:  inc SB_I
        bne @line
        inc SB_I+1
        bra @line
@done:  ldx #3
:       lda SB_BEST,x
        sta GA_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; p_floor65.s: P_FindNextHighestFloor
; ===========================================================================

; P_FindNextHighestFloor: A = a sector -> GA_0-3 = the lowest floor next to
; it that is above its floor, else its floor
        ROUTINE P_FindNextHighestFloor
        sta SB_SEC
        jsr sec_get
        ldy #SEC_FLOOR + 3      ; currentheight
:       lda (GC_SP),y
        sta SB_CUR,y
        dey
        bpl :-
        stz SB_FOUND
        stz SB_I
        stz SB_I+1
@line:  lda SB_SEC
        ldx SB_I
        ldy SB_I+1
        FCALL nextSector
        cpx #0
        bne @done
        cmp #NO_SECTOR
        beq @next
        jsr sec_get
        sec                     ; above: currentheight < its floor
        ldy #SEC_FLOOR
        lda SB_CUR
        sbc (GC_SP),y
        iny
        lda SB_CUR+1
        sbc (GC_SP),y
        iny
        lda SB_CUR+2
        sbc (GC_SP),y
        iny
        lda SB_CUR+3
        sbc (GC_SP),y
        bvc :+
        eor #$80
:       bpl @next
        lda SB_FOUND            ; the first one above: it
        beq @take
        sec                     ; the rest: it < height
        ldy #SEC_FLOOR
        lda (GC_SP),y
        sbc SB_BEST
        iny
        lda (GC_SP),y
        sbc SB_BEST+1
        iny
        lda (GC_SP),y
        sbc SB_BEST+2
        iny
        lda (GC_SP),y
        sbc SB_BEST+3
        bvc :+
        eor #$80
:       bpl @next
@take:  ldy #SEC_FLOOR + 3
:       lda (GC_SP),y
        sta SB_BEST,y
        dey
        bpl :-
        lda #1
        sta SB_FOUND
@next:  inc SB_I
        bne @line
        inc SB_I+1
        bra @line
@done:  ldx #3                  ; height, or currentheight with none above
        lda SB_FOUND
        bne @best
:       lda SB_CUR,x
        sta GA_0,x
        dex
        bpl :-
        rts
@best:
:       lda SB_BEST,x
        sta GA_0,x
        dex
        bpl :-
        rts

; ===========================================================================
; p_spec65.s: the tags
; ===========================================================================

; P_FindSectorFromLineTag: A:X = a line, Y = start ($FF: -1) -> A = the
; first sector after start with the line's tag (the sector's word against
; the line's sign-extended byte), $FF none
        ROUTINE P_FindSectorFromLineTag
        sty Q0
        jsr ln_get
        ldy #LN_TAG
        lda (GC_LP),y
        sta Q1
        ldx #0                  ; (sign-extended)
        cmp #$80
        bcc :+
        dex
:       stx Q2
        ldx Q0
@sec:   inx                     ; i = start + 1, the next (-1: 0; 255 is
        stx Q0                  ;   past every sector)
        lda LVCOUNT+1           ; i < numsectors
        bne :+
        cpx LVCOUNT
        bcs @none
:       txa
        jsr sec_get
        ldy #SEC_SIZE + SG_TAG
        lda (GC_SP),y
        cmp Q1
        bne :+
        iny
        lda (GC_SP),y
        cmp Q2
        beq @found
:       ldx Q0
        bra @sec
@found: lda Q0
        rts
@none:  lda #$FF
        rts

; P_CheckTag: A:X = a line -> A = 1 when it has a tag or a special that
; needs none, else 0
        ROUTINE P_CheckTag
        jsr ln_get
        ldy #LN_TAG
        lda (GC_LP),y
        bne @yes
        ldy #LN_SPECIAL
        lda (GC_LP),y
        ldx #NOTAGS - 1
:       cmp notags,x
        beq @yes
        dex
        bpl :-
        lda #0
        rts
@yes:   lda #1
        rts
; the specials that need no tag: manual doors, lights, thing teleporters,
; exits, scrolling walls (upstream's notags)
notags: .byte 1, 26, 27, 28, 31, 32, 33, 34, 35, 97, 11, 51, 48
NOTAGS = * - notags

; ===========================================================================
; p_spec65.s: P_UpdateSpecials; r_data65.s: P_UpdateAnimatedFlat
; ===========================================================================

; P_UpdateSpecials: the nukage flat, the slime textures (basepic +
; ((leveltime >> 3) % 3) into TEXTRANS[basepic .. basepic + 2]), the switch
; timers
        ROUTINE P_UpdateSpecials
        FCALL P_UpdateAnimatedFlat
        ldx #3                  ; leveltime >> 3, 32 bits, arithmetic
:       lda G_LEVELTIME,x
        sta Q0,x
        dex
        bpl :-
        ldx #3
:       lda Q3
        cmp #$80
        ror Q3
        ror Q2
        ror Q1
        ror Q0
        dex
        bne :-
        clc                     ; % 3: 65536 is 1 mod 3, so the halves add
        lda Q0                  ;   (a carry: + 65536, that is + 1)
        adc Q2
        sta Q0
        lda Q1
        adc Q3
        tax
        lda Q0
        bcc :+
        inc a
        bne :+
        inx
:       FCALL mod3
        sta Q4
        lda #<GT_BASEPIC        ; basepic from GTAB (ggame.inc)
        sta FA_SRC
        lda #>GT_BASEPIC
        sta FA_SRC+1
        lda #GTAB
        sta FA_BANK
        lda #<Q2
        ldx #>Q2
        ldy #2
        jsr g_get
        clc                     ; pic = basepic + it
        lda Q2
        adc Q4
        sta Q4
        clc                     ; TEXTRANS[basepic .. basepic + 2] = pic
        lda Q2
        adc #<TEXTRANS
        sta Q0
        lda Q3
        adc #>TEXTRANS
        sta Q1
        lda Q4
        ldy #0
        sta (Q0),y
        iny
        sta (Q0),y
        iny
        sta (Q0),y
        stz SB_BTN              ; the switch timers
@btn:   ldx SB_BTN
        lda G_BUTTONS + BT_BTIMER,x
        ora G_BUTTONS + BT_BTIMER + 1,x
        beq @nb
        lda G_BUTTONS + BT_BTIMER,x     ; --btimer
        bne :+
        dec G_BUTTONS + BT_BTIMER + 1,x
:       dec G_BUTTONS + BT_BTIMER,x
        lda G_BUTTONS + BT_BTIMER,x
        ora G_BUTTONS + BT_BTIMER + 1,x
        bne @nb
        txa                     ; 0: the switch changes back
        FCALL buttonDone
@nb:    clc
        lda SB_BTN
        adc #BT_SIZE
        sta SB_BTN
        cmp #U_MAXBUTTONS * BT_SIZE
        bcc @btn
        rts

; P_UpdateAnimatedFlat: NUKAGE = ((leveltime & $FFFF) >> 3) % 3, the shift
; unsigned (a signed one went negative after 32,768 tics)
        ROUTINE P_UpdateAnimatedFlat
        lda G_LEVELTIME+1
        sta Q0
        lda G_LEVELTIME
        lsr Q0
        ror a
        lsr Q0
        ror a
        lsr Q0
        ror a
        ldx Q0
        FCALL mod3
        sta NUKAGE
        rts

; mod3: A:X (A low) -> A = it % 3. 256 is 1 mod 3: the bytes add, the
; carry adds 1; then 16 is 1 mod 3: the nibbles add. Changes X.
        ROUTINE mod3
        stx Q6
        clc
        adc Q6
        adc #0
        adc #0                  ; (A = 0 and C: 256)
        tax
        and #$0F
        sta Q6
        txa
        lsr a
        lsr a
        lsr a
        lsr a
        clc
        adc Q6                  ; 0-30
:       cmp #3
        bcc :+
        sbc #3
        bra :-
:       rts

; buttonDone: A = a button's offset: its texture back on its side of the
; line's side 0, the switch sound from its sound origin, the button cleared
        ROUTINE buttonDone
        sta SB_BD
        tax
        lda G_BUTTONS + BT_LINE + 1,x
        tay
        lda G_BUTTONS + BT_LINE,x
        phy
        plx
        jsr ln_get
        ldx SB_BD
        lda G_BUTTONS + BT_WHERE + 1,x
        bne @sound
        lda G_BUTTONS + BT_WHERE,x      ; top, middle or bottom
        ldy #SIDE_TOP
        cmp #UC_TOP
        beq @tex
        ldy #SIDE_MID
        cmp #UC_MIDDLE
        beq @tex
        ldy #SIDE_BOTTOM
        cmp #UC_BOTTOM
        bne @sound
@tex:   sty Q2                  ; the texture's place in the side's record
        ldy #LN_SIDE0           ; sidenum[0]'s record
        lda (GC_LP),y
        pha
        iny
        lda (GC_LP),y
        tax
        pla
        jsr sd_get
        ldx SB_BD               ; its texture there
        ldy Q2
        lda G_BUTTONS + BT_BTEXTURE,x
        sta SB_SD,y
        jsr sd_put
@sound: ldx SB_BD               ; S_StartSound2(soundorg, sfx_swtchn)
        lda G_BUTTONS + BT_SOUNDORG,x
        tax
        ldy #$80
        lda #UC_SFX_SWTCHN
        jsr S_StartSound2
        ldx SB_BD               ; the button cleared: line and sound origin
        ldy #BT_SIZE            ;   none, the words 0
:       stz G_BUTTONS,x
        inx
        dey
        bne :-
        ldx SB_BD
        lda #$FF
        sta G_BUTTONS + BT_LINE,x
        sta G_BUTTONS + BT_LINE + 1,x
        sta G_BUTTONS + BT_SOUNDORG,x
        rts

; ===========================================================================
; p_spec65.s: T_Scroll
; ===========================================================================

; T_Scroll: GA_0-1 = a scroller: its side's texture offset + 1
        ROUTINE T_Scroll
        lda GA_0
        ldx GA_1
        jsr sp_get
        ldy #SPSC_SIDE+1        ; its side
        lda (GC_XP),y
        tax
        dey
        lda (GC_XP),y
        jsr sd_get
        inc SB_SD + SIDE_TEXOFS
        bne :+
        inc SB_SD + SIDE_TEXOFS + 1
:       jsr sd_put
        rts

; ===========================================================================
; p_lights65.s: the light thinkers
; ===========================================================================

; T_LightFlash: GA_0-1 = a flash: at the end of its count its sector goes
; from maxlight to minlight (count (P_Random() & 7) + 1) or else to
; maxlight (count (P_Random() & 64) + 1)
        ROUTINE T_LightFlash
        LT_COUNT SPLI_COUNT
        beq :+
        rts
:       LT_SEC
        ldy #SPLI_MAXLIGHT      ; at maxlight (the word)
        cmp (GC_XP),y
        bne @max
        iny
        lda (GC_XP),y
        bne @max
        ldy #SPLI_MINLIGHT      ; to minlight
        lda (GC_XP),y
        ldy #SEC_LIGHT
        sta (GC_SP),y
        jsr g_random
        and #7
        bra @count
@max:   ldy #SPLI_MAXLIGHT      ; to maxlight
        lda (GC_XP),y
        ldy #SEC_LIGHT
        sta (GC_SP),y
        jsr g_random
        and #64
@count: inc a
        ldy #SPLI_COUNT
        sta (GC_XP),y
        iny
        lda #0
        sta (GC_XP),y
        lda #1
        jmp sec_dirty

; T_StrobeFlash: GA_0-1 = a strobe: at the end of its count its sector goes
; from minlight to maxlight (count STROBEBRIGHT) or else to minlight (count
; darktime)
        ROUTINE T_StrobeFlash
        LT_COUNT SPST_COUNT
        beq :+
        rts
:       LT_SEC
        ldy #SPST_MINLIGHT      ; at minlight (the word)
        cmp (GC_XP),y
        bne @min
        iny
        lda (GC_XP),y
        bne @min
        ldy #SPST_MAXLIGHT      ; to maxlight
        lda (GC_XP),y
        ldy #SEC_LIGHT
        sta (GC_SP),y
        lda #USTROBEBRIGHT
        ldx #0
        bra @count
@min:   ldy #SPST_MINLIGHT      ; to minlight
        lda (GC_XP),y
        ldy #SEC_LIGHT
        sta (GC_SP),y
        ldy #SPST_DARKTIME + 1
        lda (GC_XP),y
        tax
        dey
        lda (GC_XP),y
@count: ldy #SPST_COUNT
        sta (GC_XP),y
        iny
        txa
        sta (GC_XP),y
        lda #1
        jmp sec_dirty

; T_Glow: GA_0-1 = a glow: direction -1 dims by GLOWSPEED down to minlight
; (then back up, direction 1), 1 brightens up to maxlight (then back,
; direction -1), else nothing. The light's 16-bit signed compares with the
; special's words as upstream's
        ROUTINE T_Glow
        lda GA_0
        ldx GA_1
        jsr sp_get
        LT_SEC
        ldy #SPGL_DIRECTION
        tax
        lda (GC_XP),y
        cmp #$FF
        beq @down
        cmp #1
        beq @up
        rts
@down:  txa                     ; Q0:Q1 = lightlevel - GLOWSPEED
        sec
        sbc #UGLOWSPEED
        sta Q0
        lda #0
        sbc #0
        sta Q1
        ldy #SPGL_MINLIGHT      ; <= minlight: back, and up
        sec
        lda Q0
        sbc (GC_XP),y
        sta Q2
        iny
        lda Q1
        sbc (GC_XP),y
        sta Q3
        ora Q2                  ; (V kept)
        beq @turnup
        lda Q3
        bvc :+
        eor #$80
:       bmi @turnup
        lda Q0                  ; no: the light dimmed
        bra @light
@turnup:
        lda #1                  ; (the light as it was)
        bra @dir
@up:    txa                     ; Q0:Q1 = lightlevel + GLOWSPEED
        clc
        adc #UGLOWSPEED
        sta Q0
        lda #0
        adc #0
        sta Q1
        ldy #SPGL_MAXLIGHT      ; >= maxlight: back, and down
        sec
        lda Q0
        sbc (GC_XP),y
        iny
        lda Q1
        sbc (GC_XP),y
        bvc :+
        eor #$80
:       bpl @turndown
        lda Q0                  ; no: the light brightened
@light: ldy #SEC_LIGHT
        sta (GC_SP),y
        lda #1
        jmp sec_dirty
@turndown:
        lda #$FF
@dir:   ldy #SPGL_DIRECTION
        sta (GC_XP),y
        jmp sp_dirty

; EV_LightTurnOn: A:X = a line, Y = bright: each sector with the line's tag
; gets light level bright, or for 0 the highest light level next to it
        ROUTINE EV_LightTurnOn
        sta SB_LINE
        stx SB_LINE+1
        sty SB_BRT
        lda #$FF                ; i = -1
        sta SB_SEC
@sec:   lda SB_LINE             ; i = P_FindSectorFromLineTag(line, i)
        ldx SB_LINE+1
        ldy SB_SEC
        FCALL P_FindSectorFromLineTag
        cmp #$FF
        bne :+
        rts
:       sta SB_SEC
        lda SB_BRT              ; tbright = bright
        sta SB_TB
        bne @set
        stz SB_I                ; 0: the highest light next to it
        stz SB_I+1
@line:  lda SB_SEC
        ldx SB_I
        ldy SB_I+1
        FCALL nextSector
        cpx #0
        bne @set
        cmp #NO_SECTOR
        beq @next
        jsr sec_get
        ldy #SEC_LIGHT          ; its light > tbright
        lda (GC_SP),y
        cmp SB_TB
        beq @next
        bcc @next
        sta SB_TB
@next:  inc SB_I
        bne @line
        inc SB_I+1
        bra @line
@set:   lda SB_SEC              ; the sector's light level = tbright
        jsr sec_get
        lda SB_TB
        ldy #SEC_LIGHT
        sta (GC_SP),y
        lda #1
        jsr sec_dirty
        bra @sec

; ===========================================================================
; p_switch65.s: lnLight, LSTAB's light entry
; ===========================================================================

; lnLight: GA_0-1 = the line, GA_2 = the argument: EV_LightTurnOn; A = 1
        ROUTINE lnLight
        lda GA_0
        ldx GA_1
        ldy GA_2
        FCALL EV_LightTurnOn
        lda #1
        rts
