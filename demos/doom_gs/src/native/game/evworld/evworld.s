; game/evworld/evworld.s: part evworld of milestone 10 (docs/GAME.md 2.4,
; wave 3): the doors and the plats a line starts. A GPL-2 derivative of
; upstream's p_doors65.s (EV_DoDoor, newDoor, EV_VerticalDoor with the
; locked doors and the reopening of a moving door; the helpers doorArg,
; setDir, topLowest, setTop, edLine, edSec, edSound and sectorArg done in
; place), p_plats65.s (EV_DoPlat; platArg, sectorArg, platSound, setHigh,
; setLow and plSec done in place) and p_switch65.s (lnDoor, lnPlat,
; lnVDoor: LSTAB's door and plat entries).
;
; The native interfaces (docs/game-parts/evworld.md, "Interfaces"):
;
;   EV_DoDoor        A:X = the line, Y = the door type (upstream's _Dp[0-3]
;                    and C) -> A = 1 when a door started, else 0
;   EV_VerticalDoor  GA_0-1 = the line, GA_2-3 = the thing (a mobj handle:
;                    upstream's _Dp[0-3], _Dp[4-7]); no result
;   newDoor          A = the sector, GA_0-1 = the line (upstream's ED_SEC,
;                    ED_LINE) -> A:X = the new door's handle (upstream's
;                    DR_DOOR): a door thinker at the list's end, function
;                    T_VerticalDoor, its sector, speed VDOORSPEED, its line,
;                    the rest 0; the sector's ceilingdata = it
;   EV_DoPlat        A:X = the line, Y = the plat type -> A = 1 when a plat
;                    started, else 0
;   LSTAB's lnDoor, lnPlat
;                    GA_0-1 = the line, GA_2 = the entry's argument (the
;                    type) -> A = EV_DoDoor's, EV_DoPlat's result
;   LSTAB's lnVDoor  GA_0-1 = the line, GA_4-5 = the thing -> A = 1
;
; Upstream's 16-bit fields are native bytes here: a line's special and tag
; (LN_SPECIAL, LN_TAG: the tag sign-extended where a word is stored, as
; P_FindSectorFromLineTag compares it), a sector's number (0-254; $FF: no
; more), a door's and a plat's type (every E1 type below 256: the high
; byte stays 0 from the record's clear). A sector's floordata and
; ceilingdata are special handles, $FFFF none (upstream's NULL), so "a
; moving floor" is a high byte other than $FF.
;
; The plat's list field (SPPL_LIST) is always none: upstream keeps no list
; of active plats (p_plats65.s:3-6), so its OFS_PLAT_LIST stays NULL from
; Z_CallocLevSpec (docs/GAME.md 1.4, review 8); its tag stays 0 (upstream
; never writes it).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export EV_DoDoor, EV_VerticalDoor, newDoor, EV_DoPlat
        .export lnDoor, lnPlat, lnVDoor
        .import sec_get, sec_dirty, ln_get, ln_dirty, sp_get, sp_dirty
        .import sp_store, gt_spectake, gt_add, S_StartSound, S_StartSound2
        .import fc_call, fc_unbuilt

        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the sector's heights"
        .assert SG_OLDSPECIAL = SG_SPECIAL + 1, error, "the specials"
        .assert PL_CARDS_1 = PL_CARDS_0 + 2 && PL_CARDS_2 = PL_CARDS_0 + 4, error, "the cards"
        .assert UC_IT_BLUECARD = 0 && UC_IT_YELLOWCARD = 1 && UC_IT_REDCARD = 2, error, "the keys"
        .assert NO_SECTOR = $FF, error, "a sector a byte"

VDOORSPEED_HI = 2               ; FRACUNIT * 2 (p_doors65.s:22)
PLATWAIT      = 3               ; p_plats65.s:21

; ---------------------------------------------------------------------------
; The scratch block (SB_EVWORLD: what a routine keeps across a call). The
; three EV_ routines never run inside one another; newDoor (called by the
; two doors' routines) has bytes of its own
; ---------------------------------------------------------------------------
SB_LN   = SB_EVWORLD            ; the line (2)                 ED_LINE, PL_LINE
SB_TY   = SB_EVWORLD + 2        ; the type                     ED_TYPE, PL_TYPE
SB_SN   = SB_EVWORLD + 3        ; the tag search's sector      ED_SECNUM, PL_SECNUM
SB_RT   = SB_EVWORLD + 4        ; the result                   ED_RTN, PL_RTN
SB_SEC  = SB_EVWORLD + 5        ; the sector                   ED_SEC, PL_SEC
SB_DR   = SB_EVWORLD + 6        ; the door or the plat (2)     DR_DOOR, PL_PLAT
SB_T    = SB_EVWORLD + 8        ; the door's top (4)           DR_T
SB_VP   = SB_EVWORLD + 12       ; 1: the thing is the player   VD_PLAYER
SB_TH   = SB_EVWORLD + 13       ; the thing (2)
SB_LT   = SB_EVWORLD + 15       ; the new door's lighttag (2)
SB_NS   = SB_EVWORLD + 17       ; newDoor: the sector,
SB_NL   = SB_EVWORLD + 18       ;   the line (2),
SB_ND   = SB_EVWORLD + 20       ;   the door (2)
SB_END  = SB_EVWORLD + 22
        .assert SB_END <= SB_EVWORLD + SB_EVWORLD_SIZE, error, "scratch"

; ---------------------------------------------------------------------------
; The helpers, done in place
; ---------------------------------------------------------------------------

; DOOR: GC_XP = the door SB_DR (upstream's doorArg)
.macro DOOR
        lda SB_DR
        ldx SB_DR+1
        jsr sp_get
.endmacro

; SETDIR v: the door's direction = v (setDir)
.macro SETDIR v
        DOOR
        lda #v
        ldy #SPDO_DIRECTION
        sta (GC_XP),y
        jsr sp_dirty
.endmacro

; SETTOP: the door's topheight = SB_T (setTop)
.macro SETTOP
        DOOR
        ldy #SPDO_TOPHEIGHT + 3
        ldx #3
:       lda SB_T,x
        sta (GC_XP),y
        dey
        dex
        bpl :-
        jsr sp_dirty
.endmacro

; TOPLOWEST: SB_T = P_FindLowestCeilingSurrounding(SB_SEC) - 4 FRACUNIT,
; the door's topheight = it (topLowest)
.macro TOPLOWEST
        lda SB_SEC
        FCALL P_FindLowestCeilingSurrounding
        lda GA_0
        sta SB_T
        lda GA_1
        sta SB_T+1
        sec
        lda GA_2
        sbc #4
        sta SB_T+2
        lda GA_3
        sbc #0
        sta SB_T+3
        SETTOP
.endmacro

; SECSOUND sfx: S_StartSound2(the sound origin of sector SB_SEC, sfx)
; (edSound, platSound)
.macro SECSOUND sfx
        ldx SB_SEC
        ldy #$80
        lda #sfx
        jsr S_StartSound2
.endmacro

; OOF: S_StartSound(player->mo, sfx_oof) (p_doors65.s's oof)
.macro OOF
        ldx G_PLAYER + PL_MO
        ldy G_PLAYER + PL_MO + 1
        lda #UC_SFX_OOF
        jsr S_StartSound
.endmacro

; ===========================================================================
; EV_DoDoor: a door for each sector with the line's tag that has no moving
; ceiling: close30ThenOpen goes down from where it is (the close sound);
; normal and open go up to the lowest ceiling next to it - 4 (the open
; sound unless the ceiling is there already); A = 1 when one started
; ===========================================================================
        ROUTINE EV_DoDoor
        sta SB_LN
        stx SB_LN+1
        sty SB_TY
        lda #$FF                ; secnum = -1
        sta SB_SN
        stz SB_RT
@loop:  lda SB_LN               ; secnum = P_FindSectorFromLineTag(line,
        ldx SB_LN+1             ;   secnum)
        ldy SB_SN
        FCALL P_FindSectorFromLineTag
        cmp #$FF
        bne @sec
        lda SB_RT
        rts
@sec:   sta SB_SN
        sta SB_SEC
        jsr sec_get             ; a moving ceiling: no
        ldy #SEC_SIZE + SG_CEILD + 1
        lda (GC_SP),y
        cmp #$FF
        bne @loop
        lda #1
        sta SB_RT
        lda SB_LN
        sta GA_0
        lda SB_LN+1
        sta GA_1
        lda SB_SEC
        FCALL newDoor
        sta SB_DR
        stx SB_DR+1
        jsr sp_get              ; its type (lighttag stays 0)
        lda SB_TY
        ldy #SPDO_TYPE
        sta (GC_XP),y
        jsr sp_dirty
        lda SB_TY
        cmp #UC_CLOSE30THENOPEN
        bne @open
        lda SB_SEC              ; topheight = ceilingheight, down
        jsr sec_get
        ldy #SEC_CEIL + 3
        ldx #3
:       lda (GC_SP),y
        sta SB_T,x
        dey
        dex
        bpl :-
        SETTOP
        SETDIR $FF
        SECSOUND UC_SFX_DORCLS
        jmp @loop
@open:  cmp #UC_NORMAL          ; normal, open: up to the lowest ceiling
        beq :+                  ;   next to it - 4
        cmp #UC_DOPEN
        jne @loop
:       SETDIR 1
        TOPLOWEST
        lda SB_SEC              ; not already there: the open sound
        jsr sec_get
        ldy #SEC_CEIL
        ldx #0
:       lda (GC_SP),y
        cmp SB_T,x
        bne @snd
        iny
        inx
        cpx #4
        bne :-
        jmp @loop
@snd:   SECSOUND UC_SFX_DOROPN
        jmp @loop

; ===========================================================================
; newDoor: a door thinker for sector A (the line GA_0-1) at the thinker
; list's end: function T_VerticalDoor, the sector, speed VDOORSPEED, the
; line, the rest 0; sec->ceilingdata = it; A:X = its handle
; ===========================================================================
        ROUTINE newDoor
        sta SB_NS
        lda GA_0
        sta SB_NL
        lda GA_1
        sta SB_NL+1
        ldx #SPK_DOOR           ; Z_CallocLevSpec
        jsr gt_spectake
        lda GC_H
        sta SB_ND
        lda GC_H+1
        sta SB_ND+1
        jsr gt_add              ; P_AddThinker: GC_PREV
        ldx #SPEC_SIZE - 1
:       stz LW_SPEC,x
        dex
        bpl :-
        lda #FN_DOOR
        sta LW_SPEC + SP_FUNC
        lda SB_NS
        sta LW_SPEC + SP_SECTOR
        lda GC_PREV
        sta LW_SPEC + SP_THPREV
        lda GC_PREV+1
        sta LW_SPEC + SP_THPREV + 1
        lda #$FF
        sta LW_SPEC + SP_THNEXT
        sta LW_SPEC + SP_THNEXT + 1
        lda #VDOORSPEED_HI
        sta LW_SPEC + SPDO_SPEED + 2
        lda SB_NL
        sta LW_SPEC + SPDO_LINE
        lda SB_NL+1
        sta LW_SPEC + SPDO_LINE + 1
        lda SB_ND
        sta GC_H
        lda SB_ND+1
        sta GC_H+1
        jsr sp_store
        lda SB_NS               ; sec->ceilingdata = the door
        jsr sec_get
        ldy #SEC_SIZE + SG_CEILD
        lda SB_ND
        sta (GC_SP),y
        iny
        lda SB_ND+1
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        lda SB_ND
        ldx SB_ND+1
        rts

; ===========================================================================
; EV_VerticalDoor: a manual door. The locked lines want their key (a
; monster: nothing; the player without it: the message and oof); the
; sector on the line's back side opens; a door that moves already turns
; around on the repeatable lines (1, 26-28): going down it goes up, else
; the player sends it down; on the others a new door starts. 31-34 open
; and stay, and the line is used up.
; ===========================================================================
        ROUTINE EV_VerticalDoor
        lda GA_0
        sta SB_LN
        lda GA_1
        sta SB_LN+1
        lda GA_2
        sta SB_TH
        lda GA_3
        sta SB_TH+1
        stz SB_VP               ; the thing is the player?
        lda G_PLAYER + PL_MO
        cmp SB_TH
        bne :+
        lda G_PLAYER + PL_MO + 1
        cmp SB_TH+1
        bne :+
        inc SB_VP
:       lda SB_LN               ; the locks
        ldx SB_LN+1
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        ldx #2 * UC_IT_BLUECARD
        cmp #26
        beq @lock
        cmp #32
        beq @lock
        ldx #2 * UC_IT_YELLOWCARD
        cmp #27
        beq @lock
        cmp #34
        beq @lock
        ldx #2 * UC_IT_REDCARD
        cmp #28
        beq @lock
        cmp #33
        bne @open
@lock:  lda SB_VP               ; a monster: no
        bne :+
        rts
:       lda G_PLAYER + PL_CARDS_0,x
        ora G_PLAYER + PL_CARDS_0 + 1,x
        bne @open
        txa                     ; no key: the message, then oof
        lsr a
        tax
        lda #1                  ; (a symbol: tag 1, its number, offset 0)
        sta G_PLAYER + PL_MESSAGE
        lda vd_msglo,x
        sta G_PLAYER + PL_MESSAGE + 1
        lda vd_msghi,x
        sta G_PLAYER + PL_MESSAGE + 2
        stz G_PLAYER + PL_MESSAGE + 3
        stz G_PLAYER + PL_MESSAGE + 4
        bra @oof
@open:  lda SB_LN               ; no back side: oof (a monster: nothing)
        ldx SB_LN+1
        jsr ln_get
        ldy #LN_SIDE1
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        bne @two
        lda SB_VP
        bne @oof
        rts
@oof:   OOF
        rts
@two:   ldy #LINE_SIZE + 1      ; sec = the back sector
        lda (GC_LP),y
        sta SB_SEC
        jsr sec_get             ; door = sec->ceilingdata
        ldy #SEC_SIZE + SG_CEILD
        lda (GC_SP),y
        sta SB_DR
        iny
        lda (GC_SP),y
        sta SB_DR+1
        cmp #$FF
        beq @new
        lda SB_LN               ; a repeatable line (1, 26-28)
        ldx SB_LN+1
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        cmp #1
        beq @turn
        cmp #26
        bcc @new
        cmp #29
        bcs @new
@turn:  DOOR                    ; only doors set ceilingdata: going down it
        ldy #SPDO_DIRECTION     ;   goes up, else the player sends it down
        lda (GC_XP),y
        cmp #$FF
        bne :+
        lda #1
        sta (GC_XP),y
        jmp sp_dirty
:       lda SB_VP
        beq :+
        lda #$FF
        sta (GC_XP),y
        jmp sp_dirty
:       rts
@new:   SECSOUND UC_SFX_DOROPN  ; the open sound, a new door going up
        lda SB_LN
        sta GA_0
        lda SB_LN+1
        sta GA_1
        lda SB_SEC
        FCALL newDoor
        sta SB_DR
        stx SB_DR+1
        SETDIR 1
        lda SB_LN               ; lighttag = line->tag; the type
        ldx SB_LN+1
        jsr ln_get
        ldy #LN_TAG
        lda (GC_LP),y
        sta SB_LT
        ldx #0
        cmp #$80
        bcc :+
        dex
:       stx SB_LT+1
        ldy #LN_SPECIAL
        lda (GC_LP),y
        ldx #UC_NORMAL
        cmp #1
        beq @type
        cmp #26
        bcc @notag
        cmp #29
        bcc @type
        cmp #31
        bcc @notag
        cmp #35
        bcs @notag
        lda #0                  ; 31-34: open, the line is used up
        sta (GC_LP),y
        jsr ln_dirty
        ldx #UC_DOPEN
        bra @type
@notag: stz SB_LT               ; the other lines: no light
        stz SB_LT+1
@type:  stx SB_TY
        DOOR
        ldy #SPDO_LIGHTTAG
        lda SB_LT
        sta (GC_XP),y
        iny
        lda SB_LT+1
        sta (GC_XP),y
        ldy #SPDO_TYPE
        lda SB_TY
        sta (GC_XP),y
        jsr sp_dirty
        TOPLOWEST
        rts

; the locked doors' messages by key (PD_BLUEK, PD_YELLOWK, PD_REDK)
vd_msglo:
        .byte <SYM_p_doors_msgBlue, <SYM_p_doors_msgYellow, <SYM_p_doors_msgRed
vd_msghi:
        .byte >SYM_p_doors_msgBlue, >SYM_p_doors_msgYellow, >SYM_p_doors_msgRed

; ===========================================================================
; EV_DoPlat: a plat for each sector with the line's tag that has no moving
; floor. raiseToNearestAndChange takes the floor texture of the line's
; front sector and rises to the next floor up (the special cleared, the
; moving sound); downWaitUpStay goes down to the lowest floor next to it,
; waits and comes back (the start sound); any other type gets a plat with
; its low, type and sector only; A = 1 when one started
; ===========================================================================
        ROUTINE EV_DoPlat
        sta SB_LN
        stx SB_LN+1
        sty SB_TY
        lda #$FF                ; secnum = -1
        sta SB_SN
        stz SB_RT
@loop:  lda SB_LN               ; secnum = P_FindSectorFromLineTag(line,
        ldx SB_LN+1             ;   secnum)
        ldy SB_SN
        FCALL P_FindSectorFromLineTag
        cmp #$FF
        bne @sec
        lda SB_RT
        rts
@sec:   sta SB_SN
        sta SB_SEC
        jsr sec_get             ; a moving floor: no
        ldy #SEC_SIZE + SG_FLOORD + 1
        lda (GC_SP),y
        cmp #$FF
        bne @loop
        lda #1
        sta SB_RT
        ldx #SPK_PLAT           ; the plat thinker (Z_CallocLevSpec)
        jsr gt_spectake
        lda GC_H
        sta SB_DR
        lda GC_H+1
        sta SB_DR+1
        jsr gt_add              ; P_AddThinker: GC_PREV
        ldx #SPEC_SIZE - 1
:       stz LW_SPEC,x
        dex
        bpl :-
        lda #FN_PLAT
        sta LW_SPEC + SP_FUNC
        lda SB_SEC
        sta LW_SPEC + SP_SECTOR
        lda GC_PREV
        sta LW_SPEC + SP_THPREV
        lda GC_PREV+1
        sta LW_SPEC + SP_THPREV + 1
        lda #$FF
        sta LW_SPEC + SP_THNEXT
        sta LW_SPEC + SP_THNEXT + 1
        sta LW_SPEC + SPPL_LIST         ; (none, always)
        lda SB_TY
        sta LW_SPEC + SPPL_TYPE
        lda SB_SEC              ; sec->floordata = the plat; low =
        jsr sec_get             ;   sec->floorheight
        ldy #SEC_SIZE + SG_FLOORD
        lda SB_DR
        sta (GC_SP),y
        iny
        lda SB_DR+1
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        sta LW_SPEC + SPPL_LOW,x
        dey
        dex
        bpl :-
        lda SB_TY
        cmp #UC_RAISETONEARESTANDCHANGE
        beq @raise
        cmp #UC_DOWNWAITUPSTAY
        beq @lower
        jsr @store
        jmp @loop

        ; raiseToNearestAndChange (wait and status stay 0: up)
@raise: lda #$80                ; speed = PLATSPEED / 2
        sta LW_SPEC + SPPL_SPEED + 1
        jsr @store
        lda SB_LN               ; the floor texture of the front sector
        ldx SB_LN+1
        jsr ln_get
        ldy #LINE_SIZE
        lda (GC_LP),y
        jsr sec_get
        ldy #SEC_FPIC
        lda (GC_SP),y
        pha
        lda SB_SEC
        jsr sec_get
        pla
        ldy #SEC_FPIC
        sta (GC_SP),y
        lda #1
        jsr sec_dirty
        lda SB_SEC              ; high = the next floor up
        FCALL P_FindNextHighestFloor
        ldy #SPPL_HIGH
        jsr @field
        lda SB_SEC              ; special = oldspecial = 0
        jsr sec_get
        lda #0
        ldy #SEC_SIZE + SG_SPECIAL
        sta (GC_SP),y
        iny
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        SECSOUND UC_SFX_STNMOV
        jmp @loop

        ; downWaitUpStay
@lower: lda #4                  ; speed = PLATSPEED * 4
        sta LW_SPEC + SPPL_SPEED + 2
        lda #UC_TICRATE * PLATWAIT
        sta LW_SPEC + SPPL_WAIT
        lda #UC_DOWN
        sta LW_SPEC + SPPL_STATUS
        ldx #3                  ; high = sec->floorheight (the low so far)
:       lda LW_SPEC + SPPL_LOW,x
        sta LW_SPEC + SPPL_HIGH,x
        dex
        bpl :-
        jsr @store
        lda SB_SEC              ; low = the lowest floor next to it (never
        FCALL P_FindLowestFloorSurrounding     ; above the sector's floor)
        ldy #SPPL_LOW
        jsr @field
        SECSOUND UC_SFX_PSTART
        jmp @loop

; @store: LW_SPEC into the plat SB_DR
@store: lda SB_DR
        sta GC_H
        lda SB_DR+1
        sta GC_H+1
        jmp sp_store

; @field: the plat's fixed_t at offset Y = GA_0-3 (setHigh, setLow)
@field: phy
        lda SB_DR
        ldx SB_DR+1
        jsr sp_get
        ply
        ldx #0
:       lda GA_0,x
        sta (GC_XP),y
        iny
        inx
        cpx #4
        bne :-
        jmp sp_dirty
        .assert UC_TICRATE * PLATWAIT < 256, error, "the plat's wait"

; ===========================================================================
; p_switch65.s: LSTAB's door and plat entries
; ===========================================================================

; lnDoor: GA_0-1 = the line, GA_2 = the type: EV_DoDoor's result
        ROUTINE lnDoor
        lda GA_0
        ldx GA_1
        ldy GA_2
        FCALL EV_DoDoor
        rts

; lnPlat: GA_0-1 = the line, GA_2 = the type: EV_DoPlat's result
        ROUTINE lnPlat
        lda GA_0
        ldx GA_1
        ldy GA_2
        FCALL EV_DoPlat
        rts

; lnVDoor: GA_0-1 = the line, GA_4-5 = the thing: EV_VerticalDoor, A = 1
        ROUTINE lnVDoor
        lda GA_4
        sta GA_2
        lda GA_5
        sta GA_3
        FCALL EV_VerticalDoor
        lda #1
        rts
