; game/tic/tic.inc: part tic's places (milestone 10, docs/GAME.md 2.4, 4.4;
; docs/game-parts/tic.md). GPL-2, the port's own.
;
; The part has no zero page of its own: its temporaries are GT_0-GT_6
; (GT_7 on is the object API's: PL_N, PL_K, PL_T among them), its
; arguments GA_*. The walk's thinker and its next are the runtime's (main
; RT_TH, RT_NEXT: GAME.md 4.4); what a routine keeps across a call is in
; the scratch block SB_TIC (32 bytes). G_Ticker is active under every
; other routine of the tic, so no other part's block shares these bytes
; (glayout.py's overlays).

TK      = SB_TIC
        .assert SB_TIC_SIZE >= 32, error, "tic's scratch block"
TK_MO   = TK + 0                ; (2) P_MobjThinker's mobj (upstream's MO_P)
TK_ACT  = TK + 2                ; (1) G_Ticker's action being run (the
                                ;   load's G_LOADACT)
TK_KIND = TK + 3                ; (1) the walk's: the visited mobj's kind
                                ;   (FN number, CLEAN off)
TK_NEED = 4                     ; (the block's bytes used)
        .assert TK_NEED <= SB_TIC_SIZE, error, "tic's scratch block"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits, as
; part mobjstate's ms.inc names them
TK_LN_A = MO_SIZE
TK_LN_B = 2 * MO_SIZE
TK_LN_C = 3 * MO_SIZE
TK_D_C  = 8

; upstream's ring of tic commands (g_game65.s cmds: CMDS slots of 8
; bytes, MAXTICS 4: 8 slots); the native G_CMDS holds it as the bridge
; writes it
TK_CMDS = 8
        .assert G_PREVSTATE - G_CMDS = 8 * TK_CMDS, error, "the command ring"
        .assert PL_CMD_SIDEMOVE = PL_CMD_FORWARDMOVE + 1 && PL_CMD_ANGLETURN = PL_CMD_FORWARDMOVE + 2 && PL_CMD_BUTTONS = PL_CMD_FORWARDMOVE + 4, error, "the player's command (ticcmd_t: 5 bytes)"

; P_MobjThinker's nightmare respawn: movecount from 12 seconds
TK_RESPAWN_TICS = 12 * 35

; the momentum and the heights in the mobj's line
        .assert MC_MOMY = MC_MOMX + 4 && MC_MOMZ = MC_MOMY + 4, error, "the momentum"
        .assert KIND_CLEAN = $80, error, "CLEAN is the kind's bit 7"
        .assert FN_NONE = 0, error, "FN_NONE"
        .assert UC_GS_LEVEL = 0, error, "GS_LEVEL"
