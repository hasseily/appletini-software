; game/attack/attack.inc: part attack's places (docs/GAME.md, the parts;
; zero page and scratch). GPL-2, the port's own.
; Included after ggame.inc.
;
; The part has no zero page of its own. What lives from P_LineAttack's or
; P_AimLineAttack's setup to the traverser's calls (upstream's near
; scratch of p_attack65.s: AT_SHOOT, AT_Z, AT_DAMAGE, AT_TOP, AT_BOT,
; AT_AIM) and what a traverser keeps across its own calls (the intercept
; and its line or thing, the shot's height t) is in the scratch block
; SB_ATTACK (32 bytes, 27 used). attackrange is the shared GM_ATRANGE
; (P_IsAttackRangeMeleeRange reads it); the trace is
; the shared GM_TRACE (x, y, dx, dy: path's P_PathTraverse writes it).
;
; A traverser's temporaries between calls that change no GT_0-GT_6 (the
; object API, the math, the part's own rangeMul and mul3, fc_call): GT_0-3
; the distance (upstream's AT_DIST), then the bottom slope of a thing or
; the puff's frac; GT_4 the front sector, GT_5 the back one ($FF none);
; GT_5-6 the intercept's pointer while it is read; the math block M_A,
; M_B, M_R between math calls. The puff's x, y, z are made in place in
; GA_X, GA_Y, GA_Z, P_SpawnPuff's and P_SpawnBlood's arguments (upstream's
; AT_PX, AT_PY, AT_PZ).

AK        = SB_ATTACK
AK_SHOOT  = AK + 0              ; (2) shootthing (AT_SHOOT, AT_T1)
AK_Z      = AK + 2              ; (4) shootz (AT_Z)
AK_DMG    = AK + 6              ; (2) la_damage (AT_DAMAGE)
AK_TOP    = AK + 8              ; (4) topslope (AT_TOP)
AK_BOT    = AK + 12             ; (4) bottomslope (AT_BOT)
AK_AIM    = AK + 16             ; (4) aimslope (AT_AIM)
AK_IN     = AK + 20             ; (1) the traverser's intercept (AT_IN)
AK_LI     = AK + 21             ; (2) its line, or its thing (AT_LI)
AK_T      = AK + 23             ; (4) the shot's height t, a thing's top
                                ;   slope; the fine angle in the setup
AK_NEED   = 27
        .assert SB_ATTACK_SIZE >= AK_NEED, error, "attack's scratch block"

AK_RANGE  = GM_ATRANGE          ; attackrange (AT_RANGE)
AK_LTGT   = GM_LINETARGET       ; (2) linetarget, $FFFF none (the shared
                                ;   GM_LINETARGET)
AK_TRACE  = GM_TRACE            ; _g_trace: x, y, dx, dy

; a mobj cache line's groups (LW_MOB's layout)
AK_LNB    = 2 * MO_SIZE

; the sky's ceiling pic: upstream's skyflatnum, the word $FFFE
; (r_data65.s:62), is the native byte pic SKY_PIC of ggame.inc
; (levelconv.py's SKY_PIC)
AK_SKYPIC = SKY_PIC
; the one gun special: open a door on impact (p_attack65.s:942)
AK_GUNDOOR = 46
; the view's slopes (p_attack65.s:21: 100 * FRACUNIT / 160)
AK_TOPSLOPE = 40960

        .assert TH_X = 0 && TH_Y = 4, error, "RTHING's x, y first"
        .assert GM_OPENBOT = GM_OPENTOP + 4, error, "opentop, openbottom"
        .assert UC_MF_SHOOTABLE_HI = 0 && UC_MF_SHOOTABLE_LO < 256, error, "MF_SHOOTABLE in the flags' byte 0"
        .assert UC_MF_NOBLOOD_LO = 0 && UC_MF_NOBLOOD_HI < 256, error, "MF_NOBLOOD in the flags' byte 2"
        .assert UC_ML_TWOSIDED < 256, error, "ML_TWOSIDED in the flags' byte"
        .assert SEC_CAP <= $FF, error, "sector $FF is none"
        .assert GA_Y = GA_X + 4 && GA_Z = GA_X + 8, error, "GA_X, GA_Y, GA_Z"

; SLT32 lhs, rhs: N set when the 32-bit lhs < rhs, signed (upstream's SLT32);
; changes A
.macro SLT32 lhs, rhs
        lda lhs
        cmp rhs
        lda lhs+1
        sbc rhs+1
        lda lhs+2
        sbc rhs+2
        lda lhs+3
        sbc rhs+3
        bvc :+
        eor #$80
:
.endmacro

; AKCOPY src, dst: 4 bytes; changes A
.macro AKCOPY src, dst
        lda src
        sta dst
        lda src+1
        sta dst+1
        lda src+2
        sta dst+2
        lda src+3
        sta dst+3
.endmacro
