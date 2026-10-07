; game/pspr/pspr.inc: part pspr's places (docs/GAME.md). GPL-2, the port's
; own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6 (GT_7
; on is the object API's), its arguments GA_*. What its routines keep
; across a call is in the scratch block SB_PSPR (32 bytes) or, where a
; routine may be entered again by an action it runs (A_WeaponReady's
; psprite), on the stack, as upstream keeps it.
;
; Conventions of the part's entries (each routine's comment has the rest):
;   - a psprite is its number: 0 the weapon (upstream's ps_weapon, PSPW),
;     1 the flash (ps_flash, PSPF); a weapon action takes it in GS_PSP
;     (gweap.s's gw_setpsprite), tickPsprite in A
;   - a state is its number, "none" $FFFF in a psprite (gw_setpsprite)
;   - a mobj is its handle, a sector its number (a byte)

PS      = SB_PSPR
        .assert SB_PSPR_SIZE >= 32, error, "pspr's scratch block"
PS_TGT  = PS + 0                ; (2) the flood's sound target (upstream's
                                ;   RS_TGT: the player's mobj)
PS_SP   = PS + 2                ; (2) the work stack's depth (entries)
PS_SEC  = PS + 4                ; (1) the flood's sector (upstream's 5,s)
PS_POS  = PS + 5                ; (2) its entry (upstream's X, 1,s)
PS_V    = PS + 7                ; (1) FL_V: v, the sound blocks its entries
                                ;   pass on (upstream's 3,s); FL_B: the
                                ;   part with ML_SOUNDBLOCK
PS_END  = PS + 8                ; (2) the end of its part (upstream's 1,s)
PS_OTH  = PS + 10               ; (1) the entry's other sector
PS_FLI  = PS + 11               ; (2) (pflood.s's header): the flood
PS_FLE  = PS + 13               ; (2)   index's and entries' places as
                                ;   lt_get entries, (at - G_LTABAT) / 2
PS_T    = PS + 15               ; (2) the bob: hi16 of its first product
PS_ANG  = PS + 17               ; (2) the bob: its fine angle
PS_COS  = PS + 19               ; (4) the bob: finecosine(angle)
PS_CNT  = PS + 23               ; (1) checkAmmo: the count
PS_ST   = PS + 24               ; (1) the flood's first sector
        .assert PS_ST + 1 <= PS + 32, error, "pspr's scratch block"

; the flood's work stack (LEVELS.md: 512 entries, the bound of every
; E1 map; in recursiveSound's group, after its code: two planes of FL_DEPTH
; bytes, the entry's low byte, its second byte; a level's sector is the
; entry of the level below it, LEVELS.md's third byte not kept)
FL_DEPTH = 512
FL_ENTRY = 2
FL_BYTES = FL_DEPTH * FL_ENTRY
FL_V     = $80                  ; an entry's second byte, and PS_V: bit 7 v,
FL_B     = $40                  ;   bit 6 the part with ML_SOUNDBLOCK, bits
                                ;   0-5 the entry's high byte

; the flood's stop code (GS_FLOOD in glayout.GS)
PS_GS_FLOOD = GS_FLOOD

; the player and its psprites (llayout.player_layout: upstream's player_t)
PLR     = G_PLAYER
PSP_SIZE = PL_PSPRITES_1_STATE - PL_PSPRITES_0_STATE
        .assert PSP_SIZE = 10, error, "a psprite: state, tics, sx, sy"
PSTATE  = PLR + PL_PSPRITES_0_STATE     ; psprite k's fields at + 10 k
PTICS   = PLR + PL_PSPRITES_0_TICS
PSX     = PLR + PL_PSPRITES_0_SX        ; (2: upstream's sx is a word)
PSY     = PLR + PL_PSPRITES_0_SY        ; (4)
        .assert PL_PSPRITES_0_SY - PL_PSPRITES_0_SX = 2, error, "sx a word"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
LN_A    = MO_SIZE
D_A     = 2

; a sector cache line: the render record, then the game record
SEC_G   = SEC_SIZE
