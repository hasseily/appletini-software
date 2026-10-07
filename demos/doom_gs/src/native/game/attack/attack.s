; game/attack/attack.s: part attack of the game (docs/GAME.md: TRVTAB,
; the parts): the hitscan
; attacks. GPL-2: rewritten from upstream's p_attack65.s (P_LineAttack:78,
; traceSetup:95, endPoint:148, traceRun:179, PTR_ShootTraverse:227,
; loadIntercept:372, opening:391, rangeDist:399, rangeMul:418,
; lineSectors:460, sideAddr:485, sideSectors:498, sectorsDiffer:515,
; shootable:535, rawSlope:555, thingHead:565, thingFoot:579, thingPtr:594,
; mul3:603, P_AimLineAttack:639, PTR_AimTraverse:668, thingTop:785,
; thingTopRaw:788, shootSpecial:936, ceilBelowZ:963, thingBottom:971,
; thingBottomRaw:974, slopeTo:985, slopeOf:996, puffPos:1019, traceAt:1066,
; puffArgs:1087, spawnPuff:1100), Doom8088: Apple IIgs Edition. Nothing
; here comes from upstream's cal_integer.s: the products, the reciprocal
; and the divide are math.s's (mul32 for _Mul32, fixmul for
; FixedMul, recip for FixedReciprocal, approxdiv for FixedApproxDiv,
; finesine, finecosine).
;
; Mobjs are handles (slots; $FFFF none), lines 16-bit numbers, sectors
; bytes; every record comes through the object API. The places are
; attack.inc's.
;
;   P_LineAttack     GA_0-1 t1, GA_2-5 the angle, GA_6-9 the distance,
;                    GA_10-13 the slope, GA_14-15 the damage (upstream's
;                    _Dp[0-3], X:C, _Dp[4-7] and the stack's slope and
;                    damage): aimslope and la_damage, the setup, then
;                    P_PathTraverse(t1's x, y, x2, y2, PT_ADDLINES |
;                    PT_ADDTHINGS, PTR_ShootTraverse). Out: nothing
;   P_AimLineAttack  GA_0-1 t1, GA_2-5 the angle, GA_6-9 the distance:
;                    the setup, topslope 40960, bottomslope -40960,
;                    linetarget none, P_PathTraverse(..., PTR_AimTraverse).
;                    Out: GA_0-3 = aimslope when a target was found, else
;                    0; AK_LTGT = GM_LINETARGET the target (the shared
;                    field)
;   setup            (traceSetup, endPoint) shootthing = t1, attackrange
;                    (GM_ATRANGE) = distance, x2 = t1.x + the low 32 bits
;                    of (distance >> 16) finecosine(angle >> 19), y2 the
;                    same with t1.y and finesine, shootz = t1.z +
;                    (t1.height >> 1) + 8 FRACUNIT; P_PathTraverse's
;                    GA_0-15 (x1 = t1.x, y1 = t1.y, x2, y2)
;   run              (traceRun) P_PathTraverse with the traverser A
;   PTR_AimTraverse  TRVTAB's: GA_0 the intercept. A line: not two-sided,
;                    or its opening closed (openbottom >= opentop): stop;
;                    else, with dist = FixedMul(attackrange, frac), where
;                    the floors differ bottomslope = max(it, the slope to
;                    openbottom), where the ceilings differ topslope =
;                    min(it, the slope to opentop) (a slope: (h - shootz)
;                    / dist by FixedApproxDiv, INT32_MAX for dist 0); stop
;                    when topslope <= bottomslope. A thing: the shooter or
;                    not shootable: go on; over (its top's slope <
;                    bottomslope) or under (its bottom's > topslope): go
;                    on; else aimslope = the two clamped to the window,
;                    halved toward 0 (upstream's + 1 for a negative sum),
;                    linetarget = it, stop. Out: C set (A = 1) to go on,
;                    C clear (A = 0) to stop
;   PTR_ShootTraverse  TRVTAB's: GA_0 the intercept. A line: its special
;                    (shootSpecial) when it has one; a two-sided line that
;                    the shot passes (t = shootz + FixedMul3(aimslope,
;                    frac, attackrange) not below openbottom where the
;                    floors differ, not above opentop where the ceilings
;                    differ) lets it go on; else the puff 4 units early
;                    (puffPos), none when the front ceiling is the sky and
;                    below the puff, or the back one is, then stop. A
;                    thing: the shooter or not shootable, over or under
;                    the aim (the raw slopes, no test of dist): go on;
;                    else the puff (MF_NOBLOOD) or blood 10 units early,
;                    then P_DamageMobj(it, shootthing, shootthing,
;                    la_damage) when la_damage is not 0, stop
;   shootSpecial     (P_ShootSpecialLine) the line AK_LI: special 46 with
;                    a tag (P_CheckTag): EV_DoDoor(line, dopen),
;                    P_ChangeSwitchTexture(line, 1)
;   puffPos          A = 4 or 10, GT_0-3 = the intercept's frac: frac -=
;                    A x FixedReciprocal(attackrange) (the low 32 bits);
;                    GA_X = trace.x + FixedMul(trace.dx, frac), GA_Y the
;                    same in y, GA_Z = shootz + mul3(frac)
;   mul3             (FixedMul3) M_R = aimslope ? FixedMul(rangeMul(M_B),
;                    aimslope) : 0
;   rangeMul         M_R = FixedMul(attackrange, M_B): M_B << 11 for
;                    attackrange 1 << 27 (MISSILERANGE), << 10 for 1 << 26
;                    (the low 32 bits, as FixedMul), else fixmul
;
; Upstream's helpers with no code of their own here (inlined):
; traceSetup, endPoint (setup, endpt), traceRun (run), loadIntercept
; (loadic), opening, rangeDist, lineSectors, sideAddr and sideSectors
; (the line's sectors come from ln_get: LVS's LNSECF, LNSECB), thingPtr,
; thingTop, thingBottom, thingTopRaw, thingBottomRaw (the four in their
; callers' code), rawSlope, slopeOf, slopeTo, sectorsDiffer, shootable,
; thingHead, thingFoot, ceilBelowZ, traceAt, puffArgs (the puff's place is
; made in GA_X-GA_Z), spawnPuff. The routines that share local helpers are
; asserted to be in one group (the placement's unit).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"
        .include "game/attack/attack.inc"

        .export P_LineAttack, P_AimLineAttack, PTR_AimTraverse
        .export PTR_ShootTraverse, shootSpecial, puffPos, mul3, rangeMul
        ; the places, for the callers
        .export AK_SHOOT, AK_Z, AK_DMG, AK_TOP, AK_BOT, AK_AIM, AK_LTGT
        .import mo_get, ln_get, sec_get
        .import mul32, fixmul, recip, approxdiv, finesine, finecosine
        .import fc_call, fc_unbuilt

; ===========================================================================
; P_LineAttack, P_AimLineAttack (one group: setup and run are theirs)
; ===========================================================================
        ROUTINE P_LineAttack
        ldx #3                  ; aimslope = slope
:       lda GA_10,x
        sta AK_AIM,x
        dex
        bpl :-
        lda GA_14               ; la_damage = damage
        sta AK_DMG
        lda GA_15
        sta AK_DMG+1
        jsr setup
        lda #TRVTAB_PTR_ShootTraverse
        jmp run

        ROUTINE P_AimLineAttack
        .assert GP_P_AimLineAttack_G = GP_P_LineAttack_G, error, "P_AimLineAttack and P_LineAttack in one group"
        jsr setup
        lda #<AK_TOPSLOPE       ; topslope = 40960, bottomslope = -40960
        sta AK_TOP
        lda #>AK_TOPSLOPE
        sta AK_TOP+1
        stz AK_TOP+2
        stz AK_TOP+3
        lda #<(-AK_TOPSLOPE)
        sta AK_BOT
        lda #>(-AK_TOPSLOPE)
        sta AK_BOT+1
        lda #$FF
        sta AK_BOT+2
        sta AK_BOT+3
        sta AK_LTGT             ; linetarget = none
        sta AK_LTGT+1
        lda #TRVTAB_PTR_AimTraverse
        jsr run
        lda AK_LTGT             ; linetarget ? aimslope : 0
        and AK_LTGT+1
        cmp #$FF
        beq @none
        ldx #3
:       lda AK_AIM,x
        sta GA_0,x
        dex
        bpl :-
        rts
@none:  stz GA_0
        stz GA_1
        stz GA_2
        stz GA_3
        rts

; setup: (traceSetup) from GA_0-1 t1, GA_2-5 the angle, GA_6-9 the
; distance: shootthing, attackrange, x2 (GA_8-11), y2 (GA_12-15), shootz;
; then GA_0-3 = t1.x, GA_4-7 = t1.y
setup:  lda GA_0                ; shootthing = t1
        sta AK_SHOOT
        lda GA_1
        sta AK_SHOOT+1
        ldx #3                  ; attackrange = distance
:       lda GA_6,x
        sta AK_RANGE,x
        dex
        bpl :-
        lda GA_5                ; the fine angle: angle >> 19 (AK_T)
        sta AK_T+1
        lda GA_4
        lsr AK_T+1
        ror a
        lsr AK_T+1
        ror a
        lsr AK_T+1
        ror a
        sta AK_T
        jsr angle               ; x2 = t1.x + (distance >> 16) cos
        jsr finecosine
        ldx #TH_X
        jsr endpt
        jsr angle               ; y2 = t1.y + (distance >> 16) sin
        jsr finesine
        ldx #TH_Y
        jsr endpt
        lda AK_SHOOT            ; shootz = z + (height >> 1) + 8 FRACUNIT
        ldx AK_SHOOT+1
        jsr mo_get
        ldy #AK_LNB + MB_HEIGHT + 3     ; height >> 1, arithmetic (M_A)
        lda (GC_MP),y
        cmp #$80
        ror a
        sta M_A+3
        dey
        lda (GC_MP),y
        ror a
        sta M_A+2
        dey
        lda (GC_MP),y
        ror a
        sta M_A+1
        dey
        lda (GC_MP),y
        ror a
        sta M_A
        clc
        ldy #TH_Z
        lda (GC_MP),y
        adc M_A
        sta AK_Z
        iny
        lda (GC_MP),y
        adc M_A+1
        sta AK_Z+1
        iny
        lda (GC_MP),y
        adc M_A+2
        sta AK_Z+2
        iny
        lda (GC_MP),y
        adc M_A+3
        sta AK_Z+3
        clc
        lda AK_Z+2
        adc #8
        sta AK_Z+2
        lda AK_Z+3
        adc #0
        sta AK_Z+3
        ldy #7                  ; x1, y1 = t1's x, y
:       lda (GC_MP),y
        sta GA_0,y
        dey
        bpl :-
        rts

; angle: M_A = the fine angle (AK_T)
angle:  lda AK_T
        sta M_A
        lda AK_T+1
        sta M_A+1
        rts

; endpt: (endPoint) GA_8 + X = t1's coordinate at X (TH_X, TH_Y) + the
; low 32 bits of (attackrange >> 16, sign extended) M_R
endpt:  stx GT_6
        ldx #3
:       lda M_R,x
        sta M_A,x
        dex
        bpl :-
        lda AK_RANGE+2
        sta M_B
        lda AK_RANGE+3
        sta M_B+1
        and #$80
        beq :+
        lda #$FF
:       sta M_B+2
        sta M_B+3
        jsr mul32
        lda AK_SHOOT
        ldx AK_SHOOT+1
        jsr mo_get
        ldy GT_6
        ldx #0
        lda #4
        sta GT_5
        clc
:       lda M_R,x
        adc (GC_MP),y
        sta GA_8,y
        inx
        iny
        dec GT_5
        bne :-
        rts

; run: (traceRun) P_PathTraverse(GA_0-15, PT_ADDLINES | PT_ADDTHINGS,
; the traverser A)
run:    sta GA_17
        lda #UC_PT_ADDLINES | UC_PT_ADDTHINGS
        sta GA_16
        FCALL P_PathTraverse
        rts

; ===========================================================================
; PTR_AimTraverse, PTR_ShootTraverse, shootSpecial (one group: the local
; helpers below are theirs)
; ===========================================================================
        ROUTINE PTR_AimTraverse
        jsr loadic
        jmi aimThing
        lda AK_LI               ; a one-sided line: stop
        ldx AK_LI+1
        jsr ln_get
        ldy #LN_FLAGS
        lda (GC_LP),y
        and #UC_ML_TWOSIDED
        jeq stop
        jsr opening             ; openbottom >= opentop: stop
        SLT32 GM_OPENBOT, GM_OPENTOP
        jpl stop
        jsr rangeDist           ; dist = FixedMul(attackrange, frac)
        jsr lineSectors
        ldy #SEC_FLOOR          ; the floors differ: the bottom slope
        jsr sectorsDiffer
        beq @ceil
        ldx #GM_OPENBOT - GM_OPENTOP
        jsr slopeTo
        SLT32 AK_BOT, M_R       ; slope > bottomslope: bottomslope = it
        bpl @ceil
        AKCOPY M_R, AK_BOT
@ceil:  ldy #SEC_CEIL           ; the ceilings differ: the top slope
        jsr sectorsDiffer
        beq @test
        ldx #0
        jsr slopeTo
        SLT32 M_R, AK_TOP       ; slope < topslope: topslope = it
        bpl @test
        AKCOPY M_R, AK_TOP
@test:  SLT32 AK_BOT, AK_TOP    ; topslope <= bottomslope: stop
        jpl stop
go:     lda #1
        sec
        rts

; a thing: not the shooter, shootable, in the window
aimThing:
        jsr shootable
        bcs go
        jsr rangeDist
        jsr thingHead           ; its top's slope (AK_T)
        jsr slopeOf
        AKCOPY M_R, AK_T
        SLT32 AK_T, AK_BOT      ; under the window's bottom: over it
        bmi go
        jsr thingFoot           ; its bottom's slope (M_R)
        jsr slopeOf
        SLT32 AK_TOP, M_R       ; above the window's top: under it
        bmi go
        AKCOPY M_R, GT_0        ; (dist is done: the bottom's slope)
        SLT32 AK_TOP, AK_T      ; thingtopslope = min(it, topslope)
        bpl :+
        AKCOPY AK_TOP, AK_T
:       SLT32 GT_0, AK_BOT      ; thingbottomslope = max(it, bottomslope)
        bpl :+
        AKCOPY AK_BOT, GT_0
:       clc                     ; aimslope = (top + bottom) / 2 toward 0:
        lda AK_T                ;   a negative sum + 1 first, then >> 1
        adc GT_0                ;   arithmetic (the sum's 32 bits)
        sta M_R
        lda AK_T+1
        adc GT_1
        sta M_R+1
        lda AK_T+2
        adc GT_2
        sta M_R+2
        lda AK_T+3
        adc GT_3
        sta M_R+3
        bpl @half
        inc M_R
        bne @half
        inc M_R+1
        bne @half
        inc M_R+2
        bne @half
        inc M_R+3
@half:  lda M_R+3
        cmp #$80
        ror a
        sta AK_AIM+3
        lda M_R+2
        ror a
        sta AK_AIM+2
        lda M_R+1
        ror a
        sta AK_AIM+1
        lda M_R
        ror a
        sta AK_AIM
        lda AK_LI               ; linetarget = it
        sta AK_LTGT
        lda AK_LI+1
        sta AK_LTGT+1
stop:   lda #0
        clc
        rts

        ROUTINE PTR_ShootTraverse
        .assert GP_PTR_ShootTraverse_G = GP_PTR_AimTraverse_G, error, "PTR_ShootTraverse and PTR_AimTraverse in one group"
        jsr loadic
        jmi shThing
        lda AK_LI               ; a special line: its action
        ldx AK_LI+1
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        beq @flags
        FCALL shootSpecial
        lda AK_LI               ; (the line again)
        ldx AK_LI+1
        jsr ln_get
@flags: ldy #LN_FLAGS           ; a two-sided line: through the opening?
        lda (GC_LP),y
        and #UC_ML_TWOSIDED
        jeq @hit
        jsr opening
        jsr icfrac              ; t = FixedMul3(aimslope, frac, range) +
        FCALL mul3              ;   shootz
        clc
        lda M_R
        adc AK_Z
        sta AK_T
        lda M_R+1
        adc AK_Z+1
        sta AK_T+1
        lda M_R+2
        adc AK_Z+2
        sta AK_T+2
        lda M_R+3
        adc AK_Z+3
        sta AK_T+3
        jsr lineSectors
        ldy #SEC_FLOOR          ; the floors differ and t < openbottom: hit
        jsr sectorsDiffer
        beq @ceil
        SLT32 AK_T, GM_OPENBOT
        jmi @hit
@ceil:  ldy #SEC_CEIL           ; the ceilings differ and opentop < t: hit
        jsr sectorsDiffer
        jeq go
        SLT32 GM_OPENTOP, AK_T
        jpl go
@hit:   jsr icfrac              ; the line is hit: the puff 4 units early
        AKCOPY M_B, GT_0
        lda #4
        FCALL puffPos
        jsr lineSectors
        lda GT_4                ; the front ceiling is the sky
        jsr sec_get
        ldy #SEC_CPIC
        lda (GC_SP),y
        cmp #AK_SKYPIC
        bne @puff
        ldy #SEC_CEIL           ; below the puff: into the sky, no puff
        jsr ceilBelowZ
        jmi stop
        lda GT_5                ; a sky hack wall: the back ceiling
        cmp #$FF
        beq @puff
        jsr sec_get
        ldy #SEC_CPIC
        lda (GC_SP),y
        cmp #AK_SKYPIC
        bne @puff
        ldy #SEC_CEIL           ; below the puff: no puff
        jsr ceilBelowZ
        jmi stop
@puff:  FCALL P_SpawnPuff
        jmp stop

; a thing: not the shooter, shootable, the aim between its slopes
shThing:
        jsr shootable
        jcs go
        jsr rangeDist
        jsr thingHead           ; thingtopslope < aimslope: over it
        jsr rawSlope
        SLT32 M_R, AK_AIM
        jmi go
        jsr thingFoot           ; thingbottomslope > aimslope: under it
        jsr rawSlope
        SLT32 AK_AIM, M_R
        jmi go
        jsr icfrac              ; the puff or the blood 10 units early
        AKCOPY M_B, GT_0
        lda #10
        FCALL puffPos
        lda AK_LI               ; MF_NOBLOOD: a puff, else blood
        ldx AK_LI+1
        jsr mo_get
        ldy #AK_LNB + MB_FLAGS + 2
        lda (GC_MP),y
        and #UC_MF_NOBLOOD_HI
        beq @blood
        FCALL P_SpawnPuff
        bra @dmg
@blood: lda AK_DMG              ; P_SpawnBlood(x, y, z, la_damage)
        sta GA_12
        lda AK_DMG+1
        sta GA_13
        FCALL P_SpawnBlood
@dmg:   lda AK_DMG              ; P_DamageMobj(th, shootthing, shootthing,
        ora AK_DMG+1            ;   la_damage) when la_damage is not 0
        jeq stop
        lda AK_LI
        sta GA_0
        lda AK_LI+1
        sta GA_1
        lda AK_SHOOT
        sta GA_2
        sta GA_4
        lda AK_SHOOT+1
        sta GA_3
        sta GA_5
        lda AK_DMG
        sta GA_6
        lda AK_DMG+1
        sta GA_7
        FCALL P_DamageMobj
        jmp stop

        ROUTINE shootSpecial
        .assert GP_shootSpecial_G = GP_PTR_ShootTraverse_G, error, "shootSpecial and PTR_ShootTraverse in one group"
        lda AK_LI               ; special 46 only (P_ShootSpecialLine)
        ldx AK_LI+1
        jsr ln_get
        ldy #LN_SPECIAL
        lda (GC_LP),y
        cmp #AK_GUNDOOR
        bne @r
        lda AK_LI               ; a tag is needed
        ldx AK_LI+1
        FCALL P_CheckTag
        cmp #0
        beq @r
        lda AK_LI               ; EV_DoDoor(line, dopen)
        ldx AK_LI+1
        ldy #UC_DOPEN
        FCALL EV_DoDoor
        lda AK_LI               ; P_ChangeSwitchTexture(line, true)
        ldx AK_LI+1
        ldy #1
        FCALL P_ChangeSwitchTexture
@r:     rts

; loadic: (loadIntercept) AK_IN = GA_0, AK_LI = its line or its thing; N
; set for a thing
loadic: lda GA_0
        sta AK_IN
        jsr icp
        ldy #4
        lda (GT_5),y
        sta AK_LI
        iny
        lda (GT_5),y
        tax
        and #$7F
        sta AK_LI+1
        txa
        rts

; icp: GT_5-6 = ICPT + 6 AK_IN (the entry: frac 4, what 2)
icp:    lda AK_IN
        asl a                   ; (AK_IN < 64: no carry)
        adc AK_IN
        asl a                   ; 6 AK_IN: C its bit 8
        tax
        lda #0
        rol a
        sta GT_6
        txa
        clc
        adc #<ICPT
        sta GT_5
        lda GT_6
        adc #>ICPT
        sta GT_6
        rts

; icfrac: M_B = the intercept's frac
icfrac: jsr icp
        ldy #3
:       lda (GT_5),y
        sta M_B,y
        dey
        bpl :-
        rts

; opening: P_LineOpening(the line AK_LI)
opening:
        lda AK_LI
        ldx AK_LI+1
        FCALL P_LineOpening
        rts

; rangeDist: GT_0-3 = dist = FixedMul(attackrange, the intercept's frac)
rangeDist:
        jsr icfrac
        FCALL rangeMul
        AKCOPY M_R, GT_0
        rts

; lineSectors: GT_4 = the front sector of the line AK_LI, GT_5 the back
; one, $FF when it has no side 1 (upstream's NULL)
lineSectors:
        lda AK_LI
        ldx AK_LI+1
        jsr ln_get
        ldy #LINE_SIZE          ; LNSECF
        lda (GC_LP),y
        sta GT_4
        ldy #LN_SIDE1
        lda (GC_LP),y
        iny
        and (GC_LP),y
        cmp #$FF
        beq :+
        ldy #LINE_SIZE + 1      ; LNSECB
        lda (GC_LP),y
:       sta GT_5
        rts

; sectorsDiffer: A = 0 (Z set) when the fixed_t at offset Y of the front
; and back sectors (GT_4, GT_5) are equal; else A = 1
sectorsDiffer:
        sty GT_6
        lda GT_4
        jsr sec_get
        ldy GT_6
        ldx #0
:       lda (GC_SP),y
        sta M_A,x
        iny
        inx
        cpx #4
        bne :-
        lda GT_5
        jsr sec_get
        ldy GT_6
        ldx #0
:       lda (GC_SP),y
        cmp M_A,x
        bne @ne
        iny
        inx
        cpx #4
        bne :-
        lda #0
        rts
@ne:    lda #1
        rts

; shootable: C set when the thing AK_LI is the shooter or not
; MF_SHOOTABLE (the trace goes on)
shootable:
        lda AK_LI
        cmp AK_SHOOT
        bne :+
        lda AK_LI+1
        cmp AK_SHOOT+1
        beq @on
:       lda AK_LI
        ldx AK_LI+1
        jsr mo_get
        ldy #AK_LNB + MB_FLAGS
        lda (GC_MP),y
        and #UC_MF_SHOOTABLE_LO
        beq @on
        clc
        rts
@on:    sec
        rts

; thingHead: M_A = th.z + th.height - shootz; thingFoot: th.z - shootz
thingHead:
        lda AK_LI
        ldx AK_LI+1
        jsr mo_get
        clc
        ldy #TH_Z
        lda (GC_MP),y
        ldy #AK_LNB + MB_HEIGHT
        adc (GC_MP),y
        sta M_A
        ldy #TH_Z + 1
        lda (GC_MP),y
        ldy #AK_LNB + MB_HEIGHT + 1
        adc (GC_MP),y
        sta M_A+1
        ldy #TH_Z + 2
        lda (GC_MP),y
        ldy #AK_LNB + MB_HEIGHT + 2
        adc (GC_MP),y
        sta M_A+2
        ldy #TH_Z + 3
        lda (GC_MP),y
        ldy #AK_LNB + MB_HEIGHT + 3
        adc (GC_MP),y
        sta M_A+3
        bra minusZ
thingFoot:
        lda AK_LI
        ldx AK_LI+1
        jsr mo_get
        ldy #TH_Z + 3
:       lda (GC_MP),y
        sta M_A - TH_Z,y
        dey
        cpy #TH_Z
        bpl :-
minusZ: sec
        lda M_A
        sbc AK_Z
        sta M_A
        lda M_A+1
        sbc AK_Z+1
        sta M_A+1
        lda M_A+2
        sbc AK_Z+2
        sta M_A+2
        lda M_A+3
        sbc AK_Z+3
        sta M_A+3
        rts

; slopeTo: M_A = (GM_OPENTOP + X: opentop, or openbottom) - shootz, then
; slopeOf
slopeTo:
        sec
        lda GM_OPENTOP,x
        sbc AK_Z
        sta M_A
        lda GM_OPENTOP+1,x
        sbc AK_Z+1
        sta M_A+1
        lda GM_OPENTOP+2,x
        sbc AK_Z+2
        sta M_A+2
        lda GM_OPENTOP+3,x
        sbc AK_Z+3
        sta M_A+3
        ; fall into slopeOf

; slopeOf: M_R = dist (GT_0-3) ? FixedApproxDiv(M_A, dist) : INT32_MAX;
; rawSlope: without the test of dist
slopeOf:
        lda GT_0
        ora GT_1
        ora GT_2
        ora GT_3
        bne rawSlope
        lda #$FF
        sta M_R
        sta M_R+1
        sta M_R+2
        lda #$7F
        sta M_R+3
        rts
rawSlope:
        AKCOPY GT_0, M_B
        jmp approxdiv

; ceilBelowZ: N set when the fixed_t at offset Y of the sector at GC_SP
; is below the puff's z (GA_Z), signed
ceilBelowZ:
        lda (GC_SP),y
        cmp GA_Z
        iny
        lda (GC_SP),y
        sbc GA_Z+1
        iny
        lda (GC_SP),y
        sbc GA_Z+2
        iny
        lda (GC_SP),y
        sbc GA_Z+3
        bvc :+
        eor #$80
:       rts

; ===========================================================================
; puffPos, mul3 (one group: puffPos calls mul3)
; ===========================================================================
        ROUTINE puffPos
        pha                     ; frac -= A x FixedReciprocal(attackrange)
        AKCOPY AK_RANGE, M_A
        jsr recip
        AKCOPY M_R, M_A
        pla
        sta M_B
        stz M_B+1
        stz M_B+2
        stz M_B+3
        jsr mul32
        sec
        lda GT_0
        sbc M_R
        sta GT_0
        lda GT_1
        sbc M_R+1
        sta GT_1
        lda GT_2
        sbc M_R+2
        sta GT_2
        lda GT_3
        sbc M_R+3
        sta GT_3
        ldx #0                  ; x = trace.x + FixedMul(trace.dx, frac)
        jsr traceAt
        ldx #4                  ; y = trace.y + FixedMul(trace.dy, frac)
        jsr traceAt
        AKCOPY GT_0, M_B        ; z = shootz + FixedMul3(aimslope, frac,
        FCALL mul3              ;   attackrange)
        clc
        lda M_R
        adc AK_Z
        sta GA_Z
        lda M_R+1
        adc AK_Z+1
        sta GA_Z+1
        lda M_R+2
        adc AK_Z+2
        sta GA_Z+2
        lda M_R+3
        adc AK_Z+3
        sta GA_Z+3
        rts

; traceAt: GA_X + X = trace's coordinate X (0 x, 4 y) + FixedMul(its delta,
; frac GT_0-3)
traceAt:
        stx GT_4
        ldy #0
:       lda AK_TRACE+8,x
        sta M_A,y
        lda GT_0,y
        sta M_B,y
        inx
        iny
        cpy #4
        bne :-
        jsr fixmul
        ldx GT_4
        ldy #0
        lda #4
        sta GT_5
        clc
:       lda M_R,y
        adc AK_TRACE,x
        sta GA_X,x
        inx
        iny
        dec GT_5
        bne :-
        rts

        ROUTINE mul3
        lda AK_AIM              ; aimslope 0: 0
        ora AK_AIM+1
        ora AK_AIM+2
        ora AK_AIM+3
        bne :+
        stz M_R
        stz M_R+1
        stz M_R+2
        stz M_R+3
        rts
:       FCALL rangeMul          ; FixedMul(FixedMul(range, frac), aimslope)
        AKCOPY M_R, M_A
        AKCOPY AK_AIM, M_B
        jmp fixmul

; ===========================================================================
; rangeMul
; ===========================================================================
        ROUTINE rangeMul
        lda AK_RANGE            ; 1 << 27 or 1 << 26: a shift
        ora AK_RANGE+1
        ora AK_RANGE+2
        bne @mul
        ldy #3
        lda AK_RANGE+3
        cmp #>(UC_MISSILERANGE_HI)
        beq @shift
        dey
        cmp #>(UC_MISSILERANGE_HI / 2)
        bne @mul
@shift: stz M_R                 ; << 8, then one bit at a time
        lda M_B
        sta M_R+1
        lda M_B+1
        sta M_R+2
        lda M_B+2
        sta M_R+3
:       asl M_R
        rol M_R+1
        rol M_R+2
        rol M_R+3
        dey
        bne :-
        rts
@mul:   AKCOPY AK_RANGE, M_A    ; else FixedMul(attackrange, v)
        jmp fixmul
        .assert UC_MISSILERANGE_HI = $0800 && UC_MISSILERANGE_LO = 0, error, "MISSILERANGE 1 << 27"
