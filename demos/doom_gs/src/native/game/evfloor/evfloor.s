; game/evfloor/evfloor.s: part evfloor of the game (docs/GAME.md, the
; parts; wave 4): the floors, the stairs and the donut a line starts. A GPL-2
; derivative of upstream's p_floor65.s (EV_DoFloor, EV_BuildStairs,
; EV_DoDonut, newFloor; the helpers floorUp (with floorDown), setDest,
; stairStep, nextStep and halfSpeed as routines, the others done in place)
; and p_switch65.s (lnFloor, lnStairs, lnDonut: LSTAB's floor entries).
;
; The native interfaces:
;
;   EV_DoFloor      A:X = the line, Y = the floor type (upstream's _Dp[0-3]
;                   and C) -> A = 1 when a floor started, else 0
;   EV_BuildStairs  A:X = the line -> A = 1 when a stair started, else 0
;   EV_DoDonut      A:X = the line -> A = 1 when a donut started, else 0
;   newFloor        A = the sector, Y = the type (upstream's FL_SEC and C)
;                   -> A:X = the new floor's handle (upstream's FL_FLOOR):
;                   a floor thinker at the list's end, function
;                   T_MoveFloor, the type, its sector none (upstream sets
;                   it in floorUp, floorDown), the rest 0; the sector's
;                   floordata = it
;   floorUp         A = the direction (1 up: upstream's floorUp; $FF down:
;                   its floorDown) for the floor SB_FL: its sector SB_SEC,
;                   speed FLOORSPEED
;   setDest         GA_0-3 -> the floordestheight of the floor SB_FL
;   halfSpeed       the speed of the floor SB_FL = FLOORSPEED / 2
;   stairStep       a buildStair floor for the step SB_SEC: up to SB_H at
;                   FLOORSPEED / 4 (SB_FL = it)
;   nextStep        the next step from SB_SEC (texture SB_TX): A = 1 when
;                   there is one (its floor made, SB_SEC = it, SB_H + 8),
;                   else 0
;   LSTAB's lnFloor GA_0-1 = the line, GA_2 = the entry's argument (the
;                   type) -> A = EV_DoFloor's result
;   lnStairs, lnDonut  GA_0-1 = the line -> A = the routine's result
;
; Upstream's 16-bit fields are native bytes here: a line's tag and special,
; its flags' low byte (ML_TWOSIDED), a sector's number (0-254; $FF: none),
; its floorpic (the floor's texture keeps a high byte 0 from the record's
; clear), a floor's type (every type below 256). A sector's floordata is a
; special's handle, $FFFF none (upstream's NULL): "a moving floor" is a
; high byte other than $FF. A line's two sectors are the bytes after its
; record (llayout's LVS: the front and the back; upstream's lineSector of
; sidenum[0] and sidenum[1]), so upstream's lineSector and sectorNum
; (IIGS_MulLo16, _Div16 of a sector's address) are the sector's number,
; with no arithmetic.
;
; EV_BuildStairs: upstream's minssec stays -1 (p_floor65.s:1059-1067), so
; its test `ssec <= minssec` never holds and has no code here; the outer
; tag search's index (upstream's FL_SECNUM, pushed around a stair) is
; SB_SN, which nextStep leaves alone: its step is SB_SEC.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export EV_DoFloor, EV_BuildStairs, EV_DoDonut, newFloor
        .export floorUp, setDest, halfSpeed, stairStep, nextStep
        .export lnFloor, lnStairs, lnDonut
        .import sec_get, sec_dirty, ln_get, lt_get, sp_get, sp_dirty
        .import sp_store, gt_spectake, gt_add
        .import fc_call, fc_unbuilt

        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the sector's heights"
        .assert NO_SECTOR = $FF, error, "a sector a byte"
        .assert ML_TWOSIDED < $100, error, "the flags' low byte"
        .assert UC_LOWERFLOOR = 0, error, "the floor types"

FLOORSPEED_HI = 1               ; FRACUNIT (p_floor65.s:46)
STAIRSIZE_HI  = 8               ; 8 * FRACUNIT (p_floor65.s:1075, :1170)

; ---------------------------------------------------------------------------
; The scratch block (SB_EVFLOOR: what a routine keeps across a call). The
; three EV_ routines never run inside one another; newFloor (called by all
; three) has bytes of its own
; ---------------------------------------------------------------------------
SB_LN   = SB_EVFLOOR            ; the line (2)                 FL_LINE
SB_TY   = SB_EVFLOOR + 2        ; the floor type               FL_TYPE
SB_SN   = SB_EVFLOOR + 3        ; the tag search's sector      FL_SECNUM
SB_RT   = SB_EVFLOOR + 4        ; the result                   FL_RTN
SB_SEC  = SB_EVFLOOR + 5        ; the sector (a step)          FL_SEC
SB_FL   = SB_EVFLOOR + 6        ; the new floor (2)            FL_FLOOR
SB_H    = SB_EVFLOOR + 8        ; the stair's height (4)       FL_HEIGHT
SB_TX   = SB_EVFLOOR + 12       ; the steps' texture           FL_TEXTURE
SB_I    = SB_EVFLOOR + 13       ; a line's index (2)           FL_I
SB_S1   = SB_EVFLOOR + 15       ; the donut: the pillar,       FL_S1
SB_S2   = SB_EVFLOOR + 16       ;   the pool,                  FL_S2
SB_S3   = SB_EVFLOOR + 17       ;   the model                  FL_S3
SB_T    = SB_EVFLOOR + 18       ; nextStep: the next step      MP_T
SB_NS   = SB_EVFLOOR + 19       ; newFloor: the sector,
SB_NT   = SB_EVFLOOR + 20       ;   the type,
SB_ND   = SB_EVFLOOR + 21       ;   the floor (2)
SB_END  = SB_EVFLOOR + 23
        .assert SB_END <= SB_EVFLOOR + SB_EVFLOOR_SIZE, error, "scratch"

; ---------------------------------------------------------------------------
; The helpers done in place
; ---------------------------------------------------------------------------

; FLOOR: GC_XP = the floor SB_FL (upstream's floorArgFL)
.macro FLOOR
        lda SB_FL
        ldx SB_FL+1
        jsr sp_get
.endmacro

; NEXTTAGGED: A = SB_SN = P_FindSectorFromLineTag(SB_LN, SB_SN); $FF none
; (lineStart's start, nextTagged; secOf is the number itself)
.macro NEXTTAGGED
        lda SB_LN
        ldx SB_LN+1
        ldy SB_SN
        FCALL P_FindSectorFromLineTag
        sta SB_SN
.endmacro

; BUSY: Z clear when the sector at GC_SP has a moving floor (floordata)
.macro BUSY
        ldy #SEC_SIZE + SG_FLOORD + 1
        lda (GC_SP),y
        cmp #$FF
.endmacro

; LINEOF: GC_LP = line SB_I of the sector at GC_SP; C set past its lines
; (i >= linecount, unsigned)
.macro LINEOF
        ldy #SEC_SIZE + SG_LCOUNT
        lda SB_I
        cmp (GC_SP),y
        iny
        lda SB_I+1
        sbc (GC_SP),y
        bcs :+
        ldy #SEC_SIZE + SG_LFIRST       ; sec->lines[i]
        clc
        lda (GC_SP),y
        adc SB_I
        pha
        iny
        lda (GC_SP),y
        adc SB_I+1
        tax
        pla
        jsr lt_get
        jsr ln_get
        clc
:
.endmacro

; NEXTI: SB_I + 1
.macro NEXTI
        inc SB_I
        bne :+
        inc SB_I+1
:
.endmacro

; ONESIDED: Z set when the line at GC_LP has no back side (sidenum[1] -1)
.macro ONESIDED
        ldy #LN_SIDE1
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
.endmacro

; S3FLOOR: GA_0-3 = the floor height of the donut's model SB_S3 (s3Floor)
.macro S3FLOOR
        lda SB_S3
        jsr sec_get
        ldy #SEC_FLOOR + 3
:       lda (GC_SP),y
        sta GA_0,y
        dey
        bpl :-
.endmacro

; NEWFLOOR ty: SB_FL = newFloor(SB_SEC, ty)
.macro NEWFLOOR ty
        lda SB_SEC
        ldy ty
        FCALL newFloor
        sta SB_FL
        stx SB_FL+1
.endmacro

; ===========================================================================
; EV_DoFloor: a floor for each sector with the line's tag that has no
; moving floor: lowerFloor down to the highest floor next to it,
; lowerFloorToLowest to the lowest, turboLower at four times the speed to
; the highest (+ 8 when not its own floor), raiseFloor up to the lowest
; ceiling next to it (at most its own ceiling), raiseFloorToNearest to the
; next floor up; any other type gets a floor with its type only. A = 1 when
; one started
; ===========================================================================
        ROUTINE EV_DoFloor
        sta SB_LN
        stx SB_LN+1
        sty SB_TY
        lda #$FF                ; secnum = -1
        sta SB_SN
        stz SB_RT
@loop:  NEXTTAGGED
        cmp #$FF
        bne @sec
        lda SB_RT
        rts
@sec:   sta SB_SEC
        jsr sec_get             ; a moving floor already: no
        BUSY
        bne @loop
        lda #1
        sta SB_RT
        NEWFLOOR SB_TY
        lda SB_TY               ; lowerFloor (0)
        bne @2
        lda #$FF
        FCALL floorUp
        lda SB_SEC
        FCALL P_FindHighestFloorSurrounding
        jmp @dest
@2:     cmp #UC_LOWERFLOORTOLOWEST
        bne @3
        lda #$FF
        FCALL floorUp
        lda SB_SEC
        FCALL P_FindLowestFloorSurrounding
        jmp @dest
@3:     cmp #UC_TURBOLOWER
        bne @4
        lda #$FF
        FCALL floorUp
        FLOOR                   ; speed = FLOORSPEED * 4
        lda #4 * FLOORSPEED_HI
        ldy #SPFL_SPEED + 2
        sta (GC_XP),y
        jsr sp_dirty
        lda SB_SEC
        FCALL P_FindHighestFloorSurrounding
        lda SB_SEC              ; not the sector's own floor: + 8 FRACUNIT
        jsr sec_get             ;   (sameAsFloor)
        ldy #SEC_FLOOR + 3
:       lda (GC_SP),y
        cmp GA_0,y
        bne @plus8
        dey
        bpl :-
        bra @dest
@plus8: clc
        lda GA_2
        adc #8
        sta GA_2
        lda GA_3
        adc #0
        sta GA_3
        bra @dest
@4:     cmp #UC_RAISEFLOOR
        bne @5
        lda #1
        FCALL floorUp
        lda SB_SEC
        FCALL P_FindLowestCeilingSurrounding
        lda SB_SEC              ; at most the ceiling (underCeiling): the
        jsr sec_get             ;   ceiling when ceilingheight < dest
        ldy #SEC_CEIL           ;   (signed)
        lda (GC_SP),y
        cmp GA_0
        iny
        lda (GC_SP),y
        sbc GA_1
        iny
        lda (GC_SP),y
        sbc GA_2
        iny
        lda (GC_SP),y
        sbc GA_3
        bvc :+
        eor #$80
:       bpl @dest
        ldy #SEC_CEIL + 3
        ldx #3
:       lda (GC_SP),y
        sta GA_0,x
        dey
        dex
        bpl :-
        bra @dest
@5:     cmp #UC_RAISEFLOORTONEAREST
        jne @loop               ; (the other types: nothing more)
        lda #1
        FCALL floorUp
        lda SB_SEC
        FCALL P_FindNextHighestFloor
@dest:  FCALL setDest
        jmp @loop

; ===========================================================================
; newFloor: a floor thinker of type Y for sector A at the thinker list's
; end: function T_MoveFloor, the type, the sector none, the rest 0;
; sec->floordata = it; A:X = its handle
; ===========================================================================
        ROUTINE newFloor
        sta SB_NS
        sty SB_NT
        ldx #SPK_FLOOR          ; Z_CallocLevSpec
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
        lda #FN_FLOOR
        sta LW_SPEC + SP_FUNC
        lda GC_PREV
        sta LW_SPEC + SP_THPREV
        lda GC_PREV+1
        sta LW_SPEC + SP_THPREV + 1
        lda #$FF
        sta LW_SPEC + SP_THNEXT
        sta LW_SPEC + SP_THNEXT + 1
        sta LW_SPEC + SP_SECTOR ; (NULL until floorUp)
        lda SB_NT
        sta LW_SPEC + SPFL_TYPE
        lda SB_ND
        sta GC_H
        lda SB_ND+1
        sta GC_H+1
        jsr sp_store
        lda SB_NS               ; sec->floordata = the floor
        jsr sec_get
        ldy #SEC_SIZE + SG_FLOORD
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
; floorUp: the floor SB_FL goes in direction A (1 up, $FF down: upstream's
; floorUp and floorDown), its sector SB_SEC, speed FLOORSPEED (the record
; is 0 from newFloor: the speed's high word's low byte only)
; ===========================================================================
        ROUTINE floorUp
        pha
        FLOOR
        pla
        ldy #SPFL_DIRECTION
        sta (GC_XP),y
        lda SB_SEC
        ldy #SP_SECTOR
        sta (GC_XP),y
        lda #FLOORSPEED_HI
        ldy #SPFL_SPEED + 2
        sta (GC_XP),y
        jmp sp_dirty

; ===========================================================================
; setDest: the floordestheight of the floor SB_FL = GA_0-3
; ===========================================================================
        ROUTINE setDest
        FLOOR
        ldy #SPFL_DEST
        ldx #0
:       lda GA_0,x
        sta (GC_XP),y
        iny
        inx
        cpx #4
        bne :-
        jmp sp_dirty

; ===========================================================================
; halfSpeed: the speed of the floor SB_FL = FLOORSPEED / 2 ($8000)
; ===========================================================================
        ROUTINE halfSpeed
        FLOOR
        ldy #SPFL_SPEED + 1
        lda #$80
        sta (GC_XP),y
        iny
        lda #0
        sta (GC_XP),y
        jmp sp_dirty

; ===========================================================================
; EV_BuildStairs: a stair from each sector with the line's tag: each step
; rises 8 above the one before; the next step is the back sector of the
; first two-sided line whose front sector is the step, with the same floor
; texture and no moving floor. A = 1 when one started
; ===========================================================================
        ROUTINE EV_BuildStairs
        sta SB_LN
        stx SB_LN+1
        lda #$FF                ; ssec = -1
        sta SB_SN
        stz SB_RT
@loop:  NEXTTAGGED
        cmp #$FF
        bne @sec
        lda SB_RT
        rts
@sec:   sta SB_SEC
        jsr sec_get             ; the first step moves already: none
        BUSY
        bne @loop
        lda #1
        sta SB_RT
        ldy #SEC_FLOOR + 3      ; height = floorheight + stairsize
:       lda (GC_SP),y
        sta SB_H,y
        dey
        bpl :-
        clc
        lda SB_H+2
        adc #STAIRSIZE_HI
        sta SB_H+2
        lda SB_H+3
        adc #0
        sta SB_H+3
        ldy #SEC_FPIC           ; texture = sec->floorpic
        lda (GC_SP),y
        sta SB_TX
        FCALL stairStep         ; the first step
@next:  FCALL nextStep          ; the next ones
        cmp #0
        bne @next
        jmp @loop

; ===========================================================================
; stairStep: a buildStair floor for the step SB_SEC: up to SB_H at
; FLOORSPEED / 4
; ===========================================================================
        ROUTINE stairStep
        NEWFLOOR #UC_BUILDSTAIR
        lda #1
        FCALL floorUp
        FLOOR                   ; speed = FLOORSPEED / 4 ($4000)
        ldy #SPFL_SPEED + 1
        lda #$40
        sta (GC_XP),y
        iny
        lda #0
        sta (GC_XP),y
        jsr sp_dirty
        ldx #3                  ; dest = the height
:       lda SB_H,x
        sta GA_0,x
        dex
        bpl :-
        FCALL setDest
        rts

; ===========================================================================
; nextStep: the next step from SB_SEC: the back sector of its first
; two-sided line whose front sector is SB_SEC, if that one has the floor
; texture SB_TX and no moving floor; then height + 8, SB_SEC = it, its
; floor (stairStep), A = 1. A = 0: none
; ===========================================================================
        ROUTINE nextStep
        stz SB_I
        stz SB_I+1
@line:  lda SB_SEC              ; for (i = 0; i < linecount; i++)
        jsr sec_get
        LINEOF
        bcc @in
        lda #0
        rts
@in:    ldy #LN_FLAGS           ; two-sided
        lda (GC_LP),y
        and #ML_TWOSIDED
        beq @skip
        ldy #LINE_SIZE          ; the front sector is this step
        lda (GC_LP),y
        cmp SB_SEC
        bne @skip
        ONESIDED                ; the back sector (none: the next line)
        beq @skip
        ldy #LINE_SIZE + 1
        lda (GC_LP),y
        sta SB_T
        jsr sec_get
        ldy #SEC_FPIC           ; the same floor texture
        lda (GC_SP),y
        cmp SB_TX
        bne @skip
        BUSY                    ; and no moving floor
        bne @skip
        clc                     ; height += stairsize
        lda SB_H+2
        adc #STAIRSIZE_HI
        sta SB_H+2
        lda SB_H+3
        adc #0
        sta SB_H+3
        lda SB_T                ; sec = tsec
        sta SB_SEC
        FCALL stairStep
        lda #1
        rts
@skip:  NEXTI
        jmp @line

; ===========================================================================
; EV_DoDonut: for each sector with the line's tag (the pillar, s1) with no
; moving floor: the pool s2 is the other sector of its first line; a line
; of the pool with a back side whose back sector is not the pillar gives
; the model s3; the pool rises and the pillar lowers, both at FLOORSPEED / 2
; to the model's floor, and the pool gets the model's floor texture. A = 1
; when one started
; ===========================================================================
        ROUTINE EV_DoDonut
        sta SB_LN
        stx SB_LN+1
        lda #$FF
        sta SB_SN
        stz SB_RT
@loop:  NEXTTAGGED              ; s1: the pillar
        cmp #$FF
        bne @sec
        lda SB_RT
        rts
@sec:   sta SB_S1
        jsr sec_get             ; moving already: no
        BUSY
        bne @loop
        ldy #SEC_SIZE + SG_LFIRST       ; s2 = getNextSector(s1->lines[0],
        lda (GC_SP),y                   ;   s1)
        pha
        iny
        lda (GC_SP),y
        tax
        pla
        jsr lt_get
        ldy SB_S1
        FCALL getNextSector
        cmp #NO_SECTOR
        beq @loop
        sta SB_S2
        jsr sec_get             ; the pool moves already: no
        BUSY
        jne @loop
        stz SB_I                ; a line of the pool with a back side whose
        stz SB_I+1              ;   back sector is not the pillar
@line:  lda SB_S2
        jsr sec_get
        LINEOF
        jcs @loop
        ONESIDED
        beq @skip
        ldy #LINE_SIZE + 1
        lda (GC_LP),y
        cmp SB_S1
        bne @s3
@skip:  NEXTI
        bra @line
@s3:    sta SB_S3               ; s3: the model
        lda #1
        sta SB_RT
        lda SB_S2               ; the rising pool
        sta SB_SEC
        NEWFLOOR #UC_DONUTRAISE
        lda #1
        FCALL floorUp
        FCALL halfSpeed
        lda SB_S3               ; texture = s3->floorpic
        jsr sec_get
        ldy #SEC_FPIC
        lda (GC_SP),y
        pha
        FLOOR
        pla
        ldy #SPFL_TEXTURE
        sta (GC_XP),y
        jsr sp_dirty
        S3FLOOR                 ; dest = s3->floorheight
        FCALL setDest
        lda SB_S1               ; the lowering pillar
        sta SB_SEC
        NEWFLOOR #UC_LOWERFLOOR
        lda #$FF
        FCALL floorUp
        FCALL halfSpeed
        S3FLOOR
        FCALL setDest
        jmp @loop

; ===========================================================================
; p_switch65.s: LSTAB's floor entries
; ===========================================================================

; lnFloor: GA_0-1 = the line, GA_2 = the type: EV_DoFloor's result
        ROUTINE lnFloor
        lda GA_0
        ldx GA_1
        ldy GA_2
        FCALL EV_DoFloor
        rts

; lnStairs: GA_0-1 = the line: EV_BuildStairs' result
        ROUTINE lnStairs
        lda GA_0
        ldx GA_1
        FCALL EV_BuildStairs
        rts

; lnDonut: GA_0-1 = the line: EV_DoDonut's result
        ROUTINE lnDonut
        lda GA_0
        ldx GA_1
        FCALL EV_DoDonut
        rts
