; game/movers/movers.s: part movers of the game (docs/GAME.md, the
; parts; wave 6): the door and the plat thinkers. A GPL-2 derivative of
; upstream's p_doors65.s (T_VerticalDoor: waiting, down, up, done; partLight
; with lightPartway, EV_LightTurnOnPartway; the helpers doorSound, moveCeiling
; and dlSec done in place, mulExt a routine of its own) and p_plats65.s
; (T_PlatRaise: waiting, up, down, remove; the helpers movePlat, stopWait,
; waitStatus and setStatus done in place). Upstream's doorArg, sectorArg,
; setDir, platArg, platSound are part evworld's helpers, which have no code
; (glayout.INLINED['evworld']): their work is done here in place too.
;
; The native interfaces:
;
;   THTAB's T_VerticalDoor, T_PlatRaise
;                   GA_0-1 = the thinker's handle (upstream's _Dp[0-3])
;   partLight       A:X = the door's handle (upstream's DR_DOOR): when the
;                   door has a light tag and a height, the sectors with its
;                   line's tag get the light between the lowest and the
;                   brightest next to each, at the door's open fraction
;   mulExt          M_A = a 32-bit value, A:X = a word (A low, sign
;                   extended) -> M_R = their product's low 32 bits
;                   (upstream's X:C = _Dp[0-3] * C); changes what mul32
;                   changes
;
; A door's fields (llayout's SP_KIND door): SPDO_TYPE (2), SPDO_TOPHEIGHT
; (4), SPDO_SPEED (4), SPDO_DIRECTION (1: 0 waiting, 1 up, $FF down),
; SPDO_TOPCOUNTDOWN (2), SPDO_LINE (a line, 2), SPDO_LIGHTTAG (2). A
; plat's: SPPL_SPEED, SPPL_LOW, SPPL_HIGH (4 each), SPPL_WAIT, SPPL_COUNT,
; SPPL_STATUS, SPPL_TYPE (2 each). The 16-bit fields are compared as
; upstream's words. A sector's floordata and ceilingdata are special
; handles, $FFFF none (upstream's NULL). Light levels are the sectors'
; render bytes (0-255): upstream's 16-bit signed compares of two lights
; are unsigned byte compares, and its 16-bit light result (the high word of
; level * bright + (FRACUNIT - level) * min, level clamped to 0..FRACUNIT)
; is at most 255.
;
; The sound events (S_StartSound2 on the sector's sound origin: the hook's
; X = the sector, Y = $80) come in upstream's order: a door's open or
; close sound after its direction is set; a plat's stone sound before its
; destination's status and sound.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export T_VerticalDoor, partLight, T_PlatRaise, mulExt
        .import sec_get, sec_dirty, sp_get, sp_dirty, S_StartSound2
        .import mul32, approxdiv
        .import fc_call, fc_unbuilt

        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the sector's heights"
        .assert UC_OK = 0 && UC_CRUSHED = 1 && UC_PASTDEST = 2, error, "result_e"
        .assert UC_NORMAL = 0 && UC_CLOSE30THENOPEN = 1 && UC_DOPEN = 2, error, "vldoor_e"
        .assert UC_UP = 0 && UC_DOWN = 1 && UC_WAITING = 2, error, "plat_e"
        .assert UC_RAISETONEARESTANDCHANGE = 1, error, "plattype_e"
        .assert NO_SECTOR = $FF, error, "a sector a byte"

VDOORWAIT = 150                 ; p_doors65.s:23
CLOSE30   = UC_TICRATE * 30     ; close30ThenOpen's wait (p_doors65.s:129)

; ---------------------------------------------------------------------------
; The scratch block (SB_MOVERS: what a routine keeps across a call). The
; two thinkers never run inside each other; partLight runs inside
; T_VerticalDoor and keeps SB_TH (the same door) and SB_RES
; ---------------------------------------------------------------------------
SB_TH    = SB_MOVERS            ; the thinker (2)              DR_DOOR, PL_PLAT
SB_SEC   = SB_MOVERS + 2        ; its sector
SB_RES   = SB_MOVERS + 3        ; the plane move's result      DR_RES, PL_RES
SB_LINE  = SB_MOVERS + 4        ; partLight: the line (2)      DL_LINE
SB_LVL   = SB_MOVERS + 6        ;   the level (4)              DL_LEVEL
SB_I     = SB_MOVERS + 10       ;   the tagged sector          DL_I, DL_SEC
SB_J     = SB_MOVERS + 11       ;   its line (2)               DL_J
SB_BRT   = SB_MOVERS + 13       ;   the brightest              DL_BRIGHT
SB_MIN   = SB_MOVERS + 14       ;   the lowest                 DL_MIN
SB_T     = SB_MOVERS + 15       ;   level * bright (4)         DR_T
SB_END   = SB_MOVERS + 19
        .assert SB_END <= SB_MOVERS + SB_MOVERS_SIZE, error, "scratch"

; ---------------------------------------------------------------------------
; Helpers done in place
; ---------------------------------------------------------------------------

; THINKER: GC_XP = the thinker SB_TH (doorArg, platArg)
.macro THINKER
        lda SB_TH
        ldx SB_TH+1
        jsr sp_get
.endmacro

; SECSOUND sfx: S_StartSound2(the sound origin of sector SB_SEC, sfx)
; (doorSound, platSound)
.macro SECSOUND sfx
        ldx SB_SEC
        ldy #$80
        lda #sfx
        jsr S_StartSound2
.endmacro

; TYPE16 ofs: A = the word at ofs of GC_XP when its high byte is 0, else
; $FF (no type of upstream's compares has a high byte); Z from A
.macro TYPE16 ofs
        ldy #ofs + 1
        lda (GC_XP),y
        beq :+
        lda #$FF
        bra :++
:       dey
        lda (GC_XP),y
:
.endmacro

; ARGS4 ofs, ga: GA (4 bytes) = the 4 bytes at ofs of GC_XP
.macro ARGS4 ofs, ga
        ldy #ofs + 3
        ldx #3
:       lda (GC_XP),y
        sta ga,x
        dey
        dex
        bpl :-
.endmacro

; ===========================================================================
; T_VerticalDoor (THTAB): the door waits, goes down or goes up
; ===========================================================================
        ROUTINE T_VerticalDoor
        lda GA_0
        sta SB_TH
        ldx GA_1
        stx SB_TH+1
        jsr sp_get
        ldy #SP_SECTOR
        lda (GC_XP),y
        sta SB_SEC
        ldy #SPDO_DIRECTION
        lda (GC_XP),y
        beq @wait
        cmp #1
        jeq @up
        cmp #$FF
        beq @down
        rts

        ; waiting: when the countdown ends, down (normal) or up
        ; (close30ThenOpen)
@wait:  ldy #SPDO_TOPCOUNTDOWN  ; --topcountdown (a word)
        lda (GC_XP),y
        sec
        sbc #1
        sta (GC_XP),y
        sta GT_0
        iny
        lda (GC_XP),y
        sbc #0
        sta (GC_XP),y
        ora GT_0
        php
        jsr sp_dirty
        plp
        bne @rts
        TYPE16 SPDO_TYPE
        cmp #UC_NORMAL
        bne :+
        lda #$FF                ; direction = -1, the close sound
        jsr dr_setdir
        SECSOUND UC_SFX_DORCLS
        rts
:       cmp #UC_CLOSE30THENOPEN
        bne @rts
        lda #1                  ; direction = 1, the open sound
        jsr dr_setdir
        SECSOUND UC_SFX_DOROPN
@rts:   rts

        ; down to the floor
@down:  lda SB_SEC              ; dest = sector->floorheight
        jsr sec_get
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        sta GA_6,x
        dey
        dex
        bpl :-
        jsr dr_move             ; (moveCeiling, then partLight)
        lda SB_RES
        cmp #UC_PASTDEST
        bne @crushd
        THINKER                 ; at the bottom
        TYPE16 SPDO_TYPE
        cmp #UC_NORMAL          ; normal: done
        jeq dr_done
        cmp #UC_CLOSE30THENOPEN ; close30ThenOpen: waits 30 s
        bne @rts
        lda #0
        jsr dr_setdir
        ldy #SPDO_TOPCOUNTDOWN
        lda #<CLOSE30
        sta (GC_XP),y
        iny
        lda #>CLOSE30
        sta (GC_XP),y
        jmp sp_dirty
@crushd:
        cmp #UC_CRUSHED         ; something under it: up again
        bne @rts
        lda #1
        jsr dr_setdir
        SECSOUND UC_SFX_DOROPN
        rts

        ; up to the top
@up:    ARGS4 SPDO_TOPHEIGHT, GA_6 ; dest = topheight
        jsr dr_move
        lda SB_RES
        cmp #UC_PASTDEST
        bne @rts
        THINKER                 ; at the top
        TYPE16 SPDO_TYPE
        cmp #UC_NORMAL          ; normal: waits
        bne :+
        lda #0
        jsr dr_setdir
        ldy #SPDO_TOPCOUNTDOWN
        lda #<VDOORWAIT
        sta (GC_XP),y
        iny
        lda #>VDOORWAIT
        sta (GC_XP),y
        jmp sp_dirty
:       cmp #UC_CLOSE30THENOPEN ; close30ThenOpen, open: done
        beq dr_done
        cmp #UC_DOPEN
        beq dr_done
        rts

; dr_done: sector->ceilingdata = none, the thinker removed
dr_done:
        lda SB_SEC
        jsr sec_get
        lda #$FF
        ldy #SEC_SIZE + SG_CEILD
        sta (GC_SP),y
        iny
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        lda SB_TH
        ldx SB_TH+1
        FCALL P_RemoveThinker
        rts

; dr_setdir: the door's direction = A (setDir); GC_XP the door after it
dr_setdir:
        pha
        THINKER
        pla
        ldy #SPDO_DIRECTION
        sta (GC_XP),y
        jmp sp_dirty

; dr_move: SB_RES = T_MovePlaneCeiling(the sector, door->speed, GA_6-9,
; door->direction) (moveCeiling), then partLight
dr_move:
        THINKER
        ARGS4 SPDO_SPEED, GA_2
        ldy #SPDO_DIRECTION
        lda (GC_XP),y
        sta GA_10
        lda SB_SEC
        sta GA_0
        FCALL T_MovePlaneCeiling
        sta SB_RES
        lda SB_TH
        ldx SB_TH+1
        FCALL partLight
        rts

; ===========================================================================
; partLight: if (door->lighttag && topheight != floorheight)
; EV_LightTurnOnPartway(door->line, FixedApproxDiv(ceilingheight -
; floorheight, topheight - floorheight))
; ===========================================================================
        ROUTINE partLight
        sta SB_TH
        stx SB_TH+1
        jsr sp_get
        ldy #SPDO_LIGHTTAG      ; no light tag: nothing
        lda (GC_XP),y
        iny
        ora (GC_XP),y
        bne :+
        rts
:       ldy #SPDO_LINE          ; the line
        lda (GC_XP),y
        sta SB_LINE
        iny
        lda (GC_XP),y
        sta SB_LINE+1
        ARGS4 SPDO_TOPHEIGHT, M_B ; topheight
        ldy #SP_SECTOR
        lda (GC_XP),y
        jsr sec_get
        sec                     ; M_B = topheight - floorheight
        ldx #0
        ldy #SEC_FLOOR
:       lda M_B,x
        sbc (GC_SP),y
        sta M_B,x
        iny
        inx
        txa
        eor #4
        bne :-
        lda M_B
        ora M_B+1
        ora M_B+2
        ora M_B+3
        bne :+
        rts                     ; no height: nothing
:       ldy #SEC_CEIL + 3       ; M_A = ceilingheight - floorheight
        ldx #3
:       lda (GC_SP),y
        sta M_A,x
        dey
        dex
        bpl :-
        sec
        ldx #0
        ldy #SEC_FLOOR
:       lda M_A,x
        sbc (GC_SP),y
        sta M_A,x
        iny
        inx
        txa
        eor #4
        bne :-
        jsr approxdiv           ; the level
        ldx #3
:       lda M_R,x
        sta SB_LVL,x
        dex
        bpl :-

        ; lightPartway: the level clamped to 0..FRACUNIT
        lda SB_LVL+3            ; level < 0: 0
        bpl @pos
        stz SB_LVL
        stz SB_LVL+1
        stz SB_LVL+2
        stz SB_LVL+3
        bra @tags
@pos:   ora SB_LVL+2            ; the high word 0: kept
        beq @tags
        lda SB_LVL+3            ; FRACUNIT: kept
        bne @unit
        lda SB_LVL+2
        cmp #1
        bne @unit
        lda SB_LVL
        ora SB_LVL+1
        beq @tags
@unit:  stz SB_LVL              ; above FRACUNIT: FRACUNIT
        stz SB_LVL+1
        lda #1
        sta SB_LVL+2
        stz SB_LVL+3

        ; each sector with the line's tag
@tags:  lda #$FF                ; i = -1
        sta SB_I
@next:  lda SB_LINE             ; i = P_FindSectorFromLineTag(line, i)
        ldx SB_LINE+1
        ldy SB_I
        FCALL P_FindSectorFromLineTag
        sta SB_I
        cmp #NO_SECTOR
        bne :+
        rts
:       jsr sec_get             ; bright = 0, min = lightlevel
        ldy #SEC_LIGHT
        lda (GC_SP),y
        sta SB_MIN
        stz SB_BRT
        stz SB_J                ; for (j = 0; j < linecount; j++)
        stz SB_J+1
@line:  lda SB_I                ; the sector next to it across lines[j]
        ldx SB_J
        ldy SB_J+1
        FCALL nextSector
        cpx #0
        bne @level              ; past its lines
        cmp #NO_SECTOR
        beq @nx
        jsr sec_get
        ldy #SEC_LIGHT
        lda (GC_SP),y
        cmp SB_BRT              ; > bright: bright
        beq :+
        bcc :+
        sta SB_BRT
:       cmp SB_MIN              ; < min: min
        bcs @nx
        sta SB_MIN
@nx:    inc SB_J
        bne @line
        inc SB_J+1
        bra @line

        ; lightlevel = (level * bright + (FRACUNIT - level) * min) >> 16
@level: ldx #3
:       lda SB_LVL,x
        sta M_A,x
        dex
        bpl :-
        lda SB_BRT
        ldx #0
        FCALL mulExt
        ldx #3
:       lda M_R,x
        sta SB_T,x
        dex
        bpl :-
        sec                     ; FRACUNIT - level
        lda #0
        sbc SB_LVL
        sta M_A
        lda #0
        sbc SB_LVL+1
        sta M_A+1
        lda #1
        sbc SB_LVL+2
        sta M_A+2
        lda #0
        sbc SB_LVL+3
        sta M_A+3
        lda SB_MIN
        ldx #0
        FCALL mulExt
        clc                     ; the sum's high word (its low byte: at
        lda M_R                 ;   most 255)
        adc SB_T
        lda M_R+1
        adc SB_T+1
        lda M_R+2
        adc SB_T+2
        pha
        lda SB_I
        jsr sec_get
        pla
        ldy #SEC_LIGHT
        sta (GC_SP),y
        lda #1
        jsr sec_dirty
        jmp @next

; ===========================================================================
; mulExt: M_R = M_A * A:X (the word sign extended), the low 32 bits
; ===========================================================================
        ROUTINE mulExt
        sta M_B
        stx M_B+1
        txa
        asl a                   ; C = the sign
        lda #0
        bcc :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        jmp mul32

; ===========================================================================
; T_PlatRaise (THTAB): the plat goes up, goes down or waits
; ===========================================================================
        ROUTINE T_PlatRaise
        lda GA_0
        sta SB_TH
        ldx GA_1
        stx SB_TH+1
        jsr sp_get
        ldy #SP_SECTOR
        lda (GC_XP),y
        sta SB_SEC
        TYPE16 SPPL_STATUS
        jeq @up
        cmp #UC_DOWN
        jeq @down
        cmp #UC_WAITING
        beq @wait
        rts

        ; waiting: at the end of the count, up from the bottom, else down
@wait:  ldy #SPPL_COUNT         ; --count (a word)
        lda (GC_XP),y
        sec
        sbc #1
        sta (GC_XP),y
        sta GT_0
        iny
        lda (GC_XP),y
        sbc #0
        sta (GC_XP),y
        ora GT_0
        php
        jsr sp_dirty
        plp
        bne @rts
        ARGS4 SPPL_LOW, GT_0    ; floorheight == low: up, else down
        lda SB_SEC
        jsr sec_get
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        cmp GT_0,x
        bne :+
        dey
        dex
        bpl :-
        lda #UC_UP
        bra :++
:       lda #UC_DOWN
:       jsr pl_status           ; (setStatus)
        SECSOUND UC_SFX_PSTART
@rts:   rts

        ; up to high: the stone sound for the raise type; held: down
@up:    lda #1
        ldx #SPPL_HIGH
        jsr pl_move
        THINKER
        TYPE16 SPPL_TYPE
        cmp #UC_RAISETONEARESTANDCHANGE
        bne :+
        lda G_LEVELTIME
        and #7
        bne :+
        SECSOUND UC_SFX_STNMOV
:       lda SB_RES
        cmp #UC_CRUSHED
        bne :+
        lda #UC_DOWN            ; (waitStatus)
        jsr pl_wait
        SECSOUND UC_SFX_PSTART
        rts
:       cmp #UC_PASTDEST        ; at the top: both types are done
        bne @rts
        jsr pl_stop
        THINKER
        TYPE16 SPPL_TYPE
        cmp #UC_RAISETONEARESTANDCHANGE + 1
        bcc pl_remove
        rts

        ; down to low
@down:  lda #$FF
        ldx #SPPL_LOW
        jsr pl_move
        lda SB_RES
        cmp #UC_PASTDEST
        bne @rts
        jsr pl_stop
        THINKER                 ; at the bottom: the raise type is done
        TYPE16 SPPL_TYPE
        cmp #UC_RAISETONEARESTANDCHANGE
        beq pl_remove
        rts

; pl_remove: sector->floordata = none, the thinker removed
pl_remove:
        lda SB_SEC
        jsr sec_get
        lda #$FF
        ldy #SEC_SIZE + SG_FLOORD
        sta (GC_SP),y
        iny
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        lda SB_TH
        ldx SB_TH+1
        FCALL P_RemoveThinker
        rts

; pl_move: SB_RES = T_MovePlaneFloor(the sector, plat->speed, the fixed_t
; at offset X of the plat, A = the direction) (movePlat)
pl_move:
        sta GA_10
        phx
        THINKER
        ply
        ldx #0
:       lda (GC_XP),y
        sta GA_6,x
        iny
        inx
        cpx #4
        bne :-
        ARGS4 SPPL_SPEED, GA_2
        lda SB_SEC
        sta GA_0
        FCALL T_MovePlaneFloor
        sta SB_RES
        rts

; pl_stop: count = wait, status = waiting, the stop sound (stopWait)
pl_stop:
        lda #UC_WAITING
        jsr pl_wait
        SECSOUND UC_SFX_PSTOP
        rts

; pl_wait: count = wait, status = A (waitStatus); pl_status: status = A
; (setStatus)
pl_wait:
        pha
        THINKER
        ldy #SPPL_WAIT
        lda (GC_XP),y
        ldy #SPPL_COUNT
        sta (GC_XP),y
        ldy #SPPL_WAIT + 1
        lda (GC_XP),y
        ldy #SPPL_COUNT + 1
        sta (GC_XP),y
        bra :+
pl_status:
        pha
        THINKER
:       pla
        ldy #SPPL_STATUS
        sta (GC_XP),y
        lda #0
        iny
        sta (GC_XP),y
        jmp sp_dirty
