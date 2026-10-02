; gspawn.s: the game core's spawn (milestone 9, stage C; docs/LEVELS.md
; 2.1 steps 5 and 12, 2.4; milestone 10's skeleton: P_SpawnMobj in play,
; the object API, docs/GAME.md 3.1). A GPL-2 derivative of upstream's
; p_setup65.s (loadThings, loadBlockMap's globals, loadThings2),
; p_spawn65.s (P_SpawnMapThing, spawnPlayer, P_SpawnMobj, newMobj,
; clearMo), r_list65.s (addIfFunc) and g_game65.s (G_PlayerReborn).
;
;   gs_spawn    the load program's SPAWN step (only in nl_setup: GS_GAME):
;               the level's game globals from the header (the pool's size,
;               the blockmap's origin, size and place, the lumps' numbers,
;               LOGP; the places the tic phase needs: G_LTABAT, G_FLIDXAT,
;               G_FLENTAT, G_BLINKSAT, G_REJECTAT), LNMAP 0 (each line's
;               r_flags), the pool (gt_poolinit), the player without a
;               mobj, then each map thing in the lump's order (the lines'
;               sectors are LVS's: the GTABS step before it)
;   gs_mapthing P_SpawnMapThing of the map thing LW_MT: the player's start
;               spawns the player; a thing of the skill (the converter
;               precomputed P_FindDoomedNum's type) spawns with its tics
;               randomized, counted, turned, and ambushing when flagged
;   gs_player   spawnPlayer: G_PlayerReborn when reborn, the player's mobj,
;               its angle and health, the player's new status, the weapon
;               up (gw_setup)
;   gs_reborn   G_PlayerReborn: a new player but the cheats and the counts
;   gs_mobj     P_SpawnMobj(GC_X, GC_Y, GA_Z, type A) into LW_MOB (the
;               caller saves it: gt_mosave): the pool's slot (or the
;               zone's), mobjinfo's fields, one P_Random call, the spawn
;               state without its action, the position (gp_setpos), the
;               floor, ceiling and drop-off of its sector, z: ONFLOORZ the
;               floor, ONCEILINGZ the ceiling less the height, else GA_Z;
;               the thinker (a full one below MT_MISC0, a brainless one for
;               tics other than -1, else none: upstream's addIfFunc keeps a
;               mobj with no function off the thinker list), totallive;
;               its tics and function in LW_MOB's working MO_XTICS,
;               MO_XFUNC (the planes' at gt_mosave)
;   gs_spawnmobj  P_SpawnMobj in play: GA_X, GA_Y, GA_Z, GA_TYPE in; the
;               mobj made and saved; A:X = GC_MO = its slot

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gs_mobj, gs_reborn, gs_spawnmobj
.ifdef LOADIMG
        .export gs_spawn
.endif
        .import g_get, g_put, g_zero, g_random, gt_add, gt_poolinit
        .import gt_pooltake, gt_mosave, gp_setpos, gw_setup
        .import udiv16, mo_free, sec_get
.ifdef LOADIMG
        .import ld_block, ld_stop
.endif
        .include "ggame.inc"

; INC32 addr: the 32-bit game global at addr + 1
.macro  INC32 addr
        .local done
        inc addr
        bne done
        inc addr+1
        bne done
        inc addr+2
        bne done
        inc addr+3
done:
.endmacro

MO_A    = LW_MOB + MO_SIZE
MO_B    = LW_MOB + 2 * MO_SIZE
MO_C    = LW_MOB + 3 * MO_SIZE
PLR     = G_PLAYER

        .segment "LOADW"

; ---------------------------------------------------------------------------
; gs_spawn: the SPAWN step
; ---------------------------------------------------------------------------
.ifdef LOADIMG
gs_spawn:
        lda GS_GAME
        bne :+
        rts
:       ldx #2 * 4 - 1          ; the places of LVG1: LTAB, FLIDX, FLENT,
:       lda LW_HDR + LHV_LTAB,x ;   BLINKS (the header's order), REJECT's
        sta G_LTABAT,x
        dex
        bpl :-
        .assert G_FLIDXAT = G_LTABAT + 2 && G_FLENTAT = G_FLIDXAT + 2 &&  G_BLINKSAT = G_FLENTAT + 2 && G_REJECTAT = G_BLINKSAT + 2, error,  "the places' order"
        .assert LHV_FLIDX = LHV_LTAB + 2 && LHV_FLENT = LHV_FLIDX + 2 &&  LHV_BLINKS = LHV_FLENT + 2, error, "the header's order"
        lda LW_HDR + LH_REJECT
        sta G_REJECTAT
        lda LW_HDR + LH_REJECT + 1
        sta G_REJECTAT+1
        lda LW_HDR + LHC_THINGS ; the pool: one mobj a map thing
        sta G_POOLN
        lda LW_HDR + LHC_THINGS + 1
        sta G_POOLN+1
        lda LW_HDR + LHC_BLOCKS
        sta G_BLOCKS
        lda LW_HDR + LHC_BLOCKS + 1
        sta G_BLOCKS+1
        lda LW_HDR + LHC_LINETABLE
        sta G_LTABN
        lda LW_HDR + LHC_LINETABLE + 1
        sta G_LTABN+1
        lda LW_HDR + LH_BLOCKMAP + 5    ; P_InitBlockRows: below 256 columns
        ora LW_HDR + LH_BLOCKMAP + 7    ;   and rows
        beq :+
        lda #LS_BLOCKMAP
        jmp ld_stop
:       stz G_BMORGX            ; the origin (whole units), the size
        stz G_BMORGX+1
        stz G_BMORGY
        stz G_BMORGY+1
        ldx #3
:       lda LW_HDR + LH_BLOCKMAP,x
        sta G_BMORGX+2,x        ; (orgx, then orgy: G_BMORGY follows)
        dex
        bpl :-
        .assert G_BMORGY = G_BMORGX + 4, error, "the origin's two words"
        lda G_BMORGX+4
        sta G_BMORGY+2
        lda G_BMORGX+5
        sta G_BMORGY+3
        stz G_BMORGX+4
        stz G_BMORGX+5
        lda LW_HDR + LH_BLOCKMAP + 4
        sta G_BMW
        stz G_BMW+1
        lda LW_HDR + LH_BLOCKMAP + 6
        sta G_BMH
        stz G_BMH+1
        lda #<(BLOCKMAP_AT + 8) ; _g_blockmap: the offsets after 4 words
        sta G_BMAP
        lda #>(BLOCKMAP_AT + 8)
        sta G_BMAP+1
        ldx #LB_BLOCKMAP        ; the lumps' lengths and numbers
        jsr ld_block
        lda LP_N
        sta G_BMLEN
        lda LP_N+1
        sta G_BMLEN+1
        ldx #LB_REJECT
        jsr ld_block
        lda LP_N
        sta G_REJLEN
        lda LP_N+1
        sta G_REJLEN+1
        ldx #3
:       lda LW_HDR + LH_LUMPS,x
        sta G_BMLUMP,x
        dex
        bpl :-
        .assert G_REJLUMP = G_BMLUMP + 2, error, "the lumps' numbers"
        stz G_LOGP              ; LOGP: the sight logs' table
        stz G_LOGP+1
        ldx #0                  ; r_flags 0: LNMAP
:       stz LNMAP,x
        inx
        bne :-
        .assert LNMAP_END - LNMAP = 256, error, "LNMAP's 2,048 bits"
        jsr gt_poolinit
        lda #$FF                ; player.mo = NULL
        sta PLR + PL_MO
        sta PLR + PL_MO + 1
        stz GS_I                ; each map thing (loadThings2)
        stz GS_I+1
@thing: lda GS_I
        cmp G_POOLN
        lda GS_I+1
        sbc G_POOLN+1
        bcs @done
        ldx #LB_THINGS          ; its record: THINGS + 8 i
        jsr ld_block
        lda GS_I
        sta GC_T
        lda GS_I+1
        asl GC_T
        rol a
        asl GC_T
        rol a
        asl GC_T
        rol a
        tax
        clc
        lda GC_T
        adc FA_SRC
        sta FA_SRC
        txa
        adc FA_SRC+1
        sta FA_SRC+1
        lda #<LW_MT
        ldx #>LW_MT
        ldy #MTHING_SIZE
        jsr g_get
        jsr gs_mapthing
        inc GS_I
        bne @thing
        inc GS_I+1
        bra @thing
@done:  rts
.endif

; ---------------------------------------------------------------------------
; gs_mapthing: P_SpawnMapThing of LW_MT
; ---------------------------------------------------------------------------
gs_mapthing:
        lda LW_MT + MT_KIND
        cmp #MT_PLAYER_START
        jeq gs_player
        cmp #MT_NEVER
        bne :+
        rts
:       ldx G_GAMESKILL         ; the skill's flag: easy (baby, easy),
        lda #U_MTF_EASY         ;   normal (medium), hard (hard, nightmare)
        cpx #U_SK_EASY + 1
        bcc @flag
        lda #U_MTF_NORMAL
        cpx #U_SK_HARD
        bcc @flag
        lda #U_MTF_HARD
@flag:  and LW_MT + MT_OPTIONS
        bne :+
        rts
:       jsr mt_xy
        lda LW_MT + MT_KIND
        jsr gs_mobj
        lda LW_MOB + MO_XTICS + 1       ; tics > 0: 1 + P_Random() % tics
        bmi @counts
        ora LW_MOB + MO_XTICS
        beq @counts
        jsr g_random
        sta M_A
        stz M_A+1
        lda LW_MOB + MO_XTICS
        sta M_B
        lda LW_MOB + MO_XTICS + 1
        sta M_B+1
        jsr udiv16
        clc
        lda M_T
        adc #1
        sta LW_MOB + MO_XTICS
        lda M_T+1
        adc #0
        sta LW_MOB + MO_XTICS + 1
@counts:
        lda MO_B + MB_FLAGS + 2 ; kills, items
        and #U_MF_COUNTKILL_HI
        beq :+
        INC32 G_TOTALKILLS
:       lda MO_B + MB_FLAGS + 2
        and #U_MF_COUNTITEM_HI
        beq :+
        INC32 G_TOTALITEMS
:       jsr mt_angle
        lda LW_MT + MT_OPTIONS  ; an ambush
        and #U_MTF_AMBUSH
        beq :+
        lda MO_B + MB_FLAGS
        ora #U_MF_AMBUSH_LO
        sta MO_B + MB_FLAGS
:       jmp gt_mosave

; mt_xy: GC_X = mthing->x << 16, GC_Y = mthing->y << 16, GA_Z = ONFLOORZ
; (P_SpawnMapThing's and spawnPlayer's z)
mt_xy:  lda #<UC_ONFLOORZ_LO
        sta GA_Z
        lda #>UC_ONFLOORZ_LO
        sta GA_Z+1
        lda #<UC_ONFLOORZ_HI
        sta GA_Z+2
        lda #>UC_ONFLOORZ_HI
        sta GA_Z+3
        stz GC_X
        stz GC_X+1
        stz GC_Y
        stz GC_Y+1
        lda LW_MT + MT_X
        sta GC_X+2
        lda LW_MT + MT_X + 1
        sta GC_X+3
        lda LW_MT + MT_Y
        sta GC_Y+2
        lda LW_MT + MT_Y + 1
        sta GC_Y+3
        rts

; mt_angle: the mobj's angle = ANG45 * mthing->angle (its high word (angle
; & 7) << 13, its low word 0)
mt_angle:
        stz LW_MOB + TH_ANGLO
        stz LW_MOB + TH_ANGLO + 1
        stz LW_MOB + TH_ANG
        lda LW_MT + MT_ANGLE
        and #7
        asl a
        asl a
        asl a
        asl a
        asl a
        sta LW_MOB + TH_ANG + 1
        rts

; ---------------------------------------------------------------------------
; gs_player: spawnPlayer
; ---------------------------------------------------------------------------
gs_player:
        lda PLR + PL_PLAYERSTATE ; reborn: G_PlayerReborn
        cmp #U_PST_REBORN
        bne :+
        lda PLR + PL_PLAYERSTATE + 1
        bne :+
        jsr gs_reborn
:       jsr mt_xy
        lda #U_MT_PLAYER
        jsr gs_mobj
        lda GC_MO               ; p->mo
        sta PLR + PL_MO
        lda GC_MO+1
        sta PLR + PL_MO + 1
        jsr mt_angle
        lda PLR + PL_HEALTH      ; health = p->health
        sta MO_A + MA_HEALTH
        lda PLR + PL_HEALTH + 1
        sta MO_A + MA_HEALTH + 1
        jsr gt_mosave
        stz PLR + PL_PLAYERSTATE ; PST_LIVE, a new status
        stz PLR + PL_PLAYERSTATE + 1
        ldx #pl_zero_end - pl_zero - 1
:       ldy pl_zero,x
        lda #0
        sta PLR,y
        sta PLR+1,y
        dex
        bpl :-
        stz PLR + PL_MESSAGE + 4 ; (the message: a reference, 5 bytes)
        lda #U_VIEWHEIGHT_LO
        sta PLR + PL_VIEWHEIGHT
        lda #>U_VIEWHEIGHT_LO
        sta PLR + PL_VIEWHEIGHT + 1
        lda #U_VIEWHEIGHT_HI
        sta PLR + PL_VIEWHEIGHT + 2
        lda #>U_VIEWHEIGHT_HI
        sta PLR + PL_VIEWHEIGHT + 3
        jmp gw_setup
; the player's words spawnPlayer zeroes (the moms' two words each)
pl_zero:
        .byte PL_REFIRE, PL_MESSAGE, PL_MESSAGE + 2, PL_DAMAGECOUNT
        .byte PL_BONUSCOUNT, PL_EXTRALIGHT, PL_FIXEDCOLORMAP
        .byte PL_MOMX, PL_MOMX + 2, PL_MOMY, PL_MOMY + 2
pl_zero_end:

; ---------------------------------------------------------------------------
; gs_reborn: G_PlayerReborn: the player all 0 (its references none) but
; its counts and cheats; usedown, attackdown; live; health; the pistol and
; the fist; the clip's bullets; the ammunition's maxima
; ---------------------------------------------------------------------------
gs_reborn:
        ldx #3                  ; kills, items, secrets; cheats
:       lda PLR + PL_KILLCOUNT,x
        pha
        dex
        bpl :-
        .assert PL_ITEMCOUNT = PL_KILLCOUNT + 2 && PL_SECRETCOUNT =  PL_ITEMCOUNT + 2, error, "the player's counts"
        lda PLR + PL_SECRETCOUNT
        pha
        lda PLR + PL_SECRETCOUNT + 1
        pha
        lda PLR + PL_CHEATS
        pha
        lda PLR + PL_CHEATS + 1
        pha
        lda #<PLR
        ldx #>PLR
        ldy #PL_SIZE
        jsr g_zero
        lda #$FF                ; the references: none
        sta PLR + PL_MO
        sta PLR + PL_MO + 1
        sta PLR + PL_ATTACKER
        sta PLR + PL_ATTACKER + 1
        sta PLR + PL_PSPRITES_0_STATE
        sta PLR + PL_PSPRITES_0_STATE + 1
        sta PLR + PL_PSPRITES_1_STATE
        sta PLR + PL_PSPRITES_1_STATE + 1
        pla
        sta PLR + PL_CHEATS + 1
        pla
        sta PLR + PL_CHEATS
        pla
        sta PLR + PL_SECRETCOUNT + 1
        pla
        sta PLR + PL_SECRETCOUNT
        ldx #0
:       pla
        sta PLR + PL_KILLCOUNT,x
        inx
        cpx #4
        bne :-
        lda #1                  ; usedown = attackdown = true
        sta PLR + PL_USEDOWN
        sta PLR + PL_ATTACKDOWN
        lda #U_INITIAL_HEALTH
        sta PLR + PL_HEALTH
        lda #U_WP_PISTOL
        sta PLR + PL_READYWEAPON
        sta PLR + PL_PENDINGWEAPON
        lda #1
        sta PLR + PL_WEAPONOWNED_0 + 2 * U_WP_FIST
        sta PLR + PL_WEAPONOWNED_0 + 2 * U_WP_PISTOL
        lda #U_INITIAL_BULLETS
        sta PLR + PL_AMMO_0 + 2 * U_AM_CLIP
        ldx #2 * U_NUMAMMO - 1
:       lda maxammo,x
        sta PLR + PL_MAXAMMO_0,x
        dex
        bpl :-
        rts
        .assert >U_INITIAL_HEALTH = 0 && >U_INITIAL_BULLETS = 0, error,  "the reborn player's numbers"
        .assert PL_WEAPONOWNED_1 = PL_WEAPONOWNED_0 + 2, error, "words"
maxammo:
        .word U_MAXAMMO_0, U_MAXAMMO_1, U_MAXAMMO_2, U_MAXAMMO_3
        .assert U_NUMAMMO = 4, error, "four kinds of ammunition"

; ---------------------------------------------------------------------------
; gs_mobj: P_SpawnMobj(GC_X, GC_Y, ONFLOORZ, A) into LW_MOB, slot GC_MO
; ---------------------------------------------------------------------------
gs_mobj:
        sta GS_SB               ; (the type)
        jsr gt_pooltake         ; newMobj: GC_MO, GC_K pooled
        jsr mo_free             ; clearMo (the handles none)
        lda GS_SB
        sta MO_A + MA_TYPE
        lda GC_K                ; MF_POOLED
        beq :+
        lda #>U_MF_POOLED_HI
        sta MO_B + MB_FLAGS + 3
:       lda GS_SB               ; mobjinfo[type]: GT_MOBJINFO + 64 type
        stz FA_SRC
        lsr a
        ror FA_SRC
        lsr a
        ror FA_SRC
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<GT_MOBJINFO
        sta FA_SRC
        lda FA_SRC+1
        adc #>GT_MOBJINFO
        sta FA_SRC+1
        lda #GTAB
        sta FA_BANK
        lda #<LW_MINFO
        ldx #>LW_MINFO
        ldy #INFO_SIZE
        jsr g_get
        .assert INFO_SIZE = 64, error, "a mobjinfo record"
        ldx #3                  ; x, y; radius, height; flags |= info's
:       lda GC_X,x
        sta LW_MOB + TH_X,x
        lda GC_Y,x
        sta LW_MOB + TH_Y,x
        lda LW_MINFO + U_MI_RADIUS,x
        sta MO_B + MB_RADIUS,x
        lda LW_MINFO + U_MI_HEIGHT,x
        sta MO_B + MB_HEIGHT,x
        lda LW_MINFO + U_MI_FLAGS,x
        ora MO_B + MB_FLAGS,x
        sta MO_B + MB_FLAGS,x
        dex
        bpl :-
        lda LW_MINFO + U_MI_SPAWNHEALTH
        sta MO_A + MA_HEALTH
        lda LW_MINFO + U_MI_SPAWNHEALTH + 1
        sta MO_A + MA_HEALTH + 1
        lda G_GAMESKILL         ; reactiontime, but in nightmare
        cmp #U_SK_NIGHTMARE
        bne :+
        lda G_GAMESKILL+1
        beq @random
:       lda LW_MINFO + U_MI_REACTIONTIME
        sta MO_C + MC_REACT
        lda LW_MINFO + U_MI_REACTIONTIME + 1
        sta MO_C + MC_REACT + 1
@random:
        jsr g_random            ; (only for compatibility)
        lda LW_MINFO + U_MI_SPAWNSTATE  ; the spawn state, its action not run
        sta MO_A + MA_STATE
        lda LW_MINFO + U_MI_SPAWNSTATE + 1
        sta MO_A + MA_STATE + 1
        jsr state_get
        lda LW_STATE + U_ST_TICS
        sta LW_MOB + MO_XTICS
        lda LW_STATE + U_ST_TICS + 1
        sta LW_MOB + MO_XTICS + 1
        lda LW_STATE + U_ST_SPRITE
        sta LW_MOB + TH_SPR
        lda LW_STATE + U_ST_FRAME
        sta LW_MOB + TH_FRAME
        lda LW_STATE + U_ST_FRAME + 1
        sta LW_MOB + TH_FRAME + 1
        jsr gp_setpos           ; the blocks and the sector (GC_SEC)
        lda GC_SEC              ; floorz = dropoffz = the floor, ceilingz
        jsr sec_get
        ldy #SEC_FLOOR + 3
        ldx #3
:       lda (GC_SP),y
        sta MO_B + MB_FLOORZ,x
        sta MO_B + MB_DROPZ,x
        dey
        dex
        bpl :-
        ldy #SEC_CEIL + 3
        ldx #3
:       lda (GC_SP),y
        sta MO_B + MB_CEILZ,x
        dey
        dex
        bpl :-
        lda GA_Z+3              ; z: ONFLOORZ the floor, ONCEILINGZ the
        cmp #>UC_ONFLOORZ_HI    ;   ceiling less the height, else GA_Z
        bne @ceil
        lda GA_Z+2
        cmp #<UC_ONFLOORZ_HI
        bne @given
        lda GA_Z+1
        cmp #>UC_ONFLOORZ_LO
        bne @given
        lda GA_Z
        cmp #<UC_ONFLOORZ_LO
        bne @given
        ldx #3
:       lda MO_B + MB_FLOORZ,x
        sta LW_MOB + TH_Z,x
        dex
        bpl :-
        bra @thinker
@ceil:  cmp #>UC_ONCEILINGZ_HI
        bne @given
        lda GA_Z+2
        cmp #<UC_ONCEILINGZ_HI
        bne @given
        lda GA_Z+1
        cmp #>UC_ONCEILINGZ_LO
        bne @given
        lda GA_Z
        cmp #<UC_ONCEILINGZ_LO
        bne @given
        sec
        ldx #0
        ldy #4
:       lda MO_B + MB_CEILZ,x
        sbc MO_B + MB_HEIGHT,x
        sta LW_MOB + TH_Z,x
        inx
        dey
        bne :-
        bra @thinker
@given: ldx #3
:       lda GA_Z,x
        sta LW_MOB + TH_Z,x
        dex
        bpl :-
@thinker:
        ldx #FN_MOBJ            ; the thinker: full below MT_MISC0, the
        lda MO_A + MA_TYPE      ;   states only with tics other than -1,
        cmp #U_MT_MISC0         ;   else none
        bcc @fn
        ldx #FN_BRAINLESS
        lda LW_MOB + MO_XTICS
        and LW_MOB + MO_XTICS + 1
        cmp #$FF
        bne @fn
        ldx #FN_NONE
@fn:    stx LW_MOB + MO_XFUNC
        cpx #FN_NONE
        beq @live
        lda GC_MO
        sta GC_H
        lda GC_MO+1
        sta GC_H+1
        jsr gt_add
        lda GC_PREV
        sta MO_A + MA_THPREV
        lda GC_PREV+1
        sta MO_A + MA_THPREV + 1
@live:  lda MO_B + MB_FLAGS + 2 ; a monster to kill: totallive++
        and #U_MF_COUNTKILL_HI
        beq :+
        INC32 G_TOTALLIVE
:       lda MO_B + MB_FLAGS + 2 ; the renderer's MF_SHADOW
        and #U_MF_SHADOW_HI
        beq :+
        lda #1
:       sta LW_MOB + TH_FLAGS
        rts
        .assert >U_MF_COUNTKILL_HI = 0 && >U_MF_COUNTITEM_HI = 0 &&  >U_MF_SHADOW_HI = 0 && <U_MF_POOLED_HI = 0 &&  >U_MF_AMBUSH_LO = 0 && >U_MF_NOSECTOR = 0 &&  >U_MF_NOBLOCKMAP = 0, error, "the flags' bytes"

; ---------------------------------------------------------------------------
; gs_spawnmobj: P_SpawnMobj in play: GA_X, GA_Y, GA_Z, GA_TYPE in; the mobj
; made and saved (gt_mosave: the object API and the planes); A:X = GC_MO
; ---------------------------------------------------------------------------
; (the parts' name for it: FCALL P_SpawnMobj, glayout.CORE_ENTRIES)
P_SpawnMobj := gs_spawnmobj
        .export P_SpawnMobj
gs_spawnmobj:
        ldx #3
:       lda GA_X,x
        sta GC_X,x
        lda GA_Y,x
        sta GC_Y,x
        dex
        bpl :-
        lda GA_TYPE
        jsr gs_mobj
        jsr gt_mosave
        lda GC_MO
        ldx GC_MO+1
        rts

; state_get: LW_STATE = the state MO_A's MA_STATE (GT_STATES + 16 n)
state_get:
        lda MO_A + MA_STATE
        ldx MO_A + MA_STATE + 1
        .export state_at
; state_at: LW_STATE = state A:X
state_at:
        sta FA_SRC
        txa
        ldx #4
:       asl FA_SRC
        rol a
        dex
        bne :-
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<GT_STATES
        sta FA_SRC
        lda FA_SRC+1
        adc #>GT_STATES
        sta FA_SRC+1
        lda #GTAB
        sta FA_BANK
        lda #<LW_STATE
        ldx #>LW_STATE
        ldy #STATE_SIZE
        jmp g_get
        .assert STATE_SIZE = 16, error, "a state record"
