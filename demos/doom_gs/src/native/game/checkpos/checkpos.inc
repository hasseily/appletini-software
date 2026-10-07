; game/checkpos/checkpos.inc: part checkpos's places (docs/GAME.md,
; the parts; zero page and scratch). GPL-2, the port's own. Included
; after ggame.inc.
;
; p_map65.s's near scratch that this part writes and later parts read
; (trymove: tmthing, tmx, tmy, spechit, MP_TRY; teleport: tmthing, tmx,
; tmy, setBox's box; chasemove: the box and spechit) is GW's shared
; GM_TMTHING, GM_TMX, GM_TMY, GM_TMBBOX, GM_SPECHIT, GM_MPTRY
; (glayout.TIC_GW_FIELDS); the part's names for them:
;
;   CP_TMTHING  tmthing (a mobj handle)
;   CP_TMX      tmx (fixed_t)
;   CP_TMY      tmy (fixed_t)
;   CP_TMBBOX   _g_tmbbox: top, bottom, left, right (fixed_t each, in
;               upstream's order UC_BOX*)
;   CP_SPECHIT  _g_spechit: 4 line numbers (16 bits each); their count is
;               GM_NSPEC (numspechit, geom's)
;   CP_TRY      MP_TRY: 1 when P_TryMove calls checkPos (the point's floor
;               after the things), 0 from P_CheckPosition

CP_TMTHING      = GM_TMTHING
CP_TMX          = GM_TMX
CP_TMY          = GM_TMY
CP_TMBBOX       = GM_TMBBOX
CP_SPECHIT      = GM_SPECHIT
CP_TRY          = GM_MPTRY

BOXT            = CP_TMBBOX + 4 * UC_BOXTOP
BOXB            = CP_TMBBOX + 4 * UC_BOXBOTTOM
BOXL            = CP_TMBBOX + 4 * UC_BOXLEFT
BOXR            = CP_TMBBOX + 4 * UC_BOXRIGHT

; The scratch block SB_CHECKPOS (32 B). Upstream's near scratch that only
; this part reads (MP_TMF, MP_RAD: setBox's, read by the things' walk; a
; nested check overwrites them as it overwrites upstream's), the walks'
; blocks, and each walk's own state. The two walks share bytes: the lines'
; walk starts after the things' walk has ended, and the things' walk keeps
; its state on the stack across PIT_CheckThing's game logic (which can run
; another check), as upstream keeps its walk frame there.
CP              = SB_CHECKPOS
CP_TMF          = CP + 0        ; bit 7: tmthing is a missile; bit 2: it
                                ;   picks up (upstream's MP_TMF high byte's
                                ;   bit 7 and low byte's bit 2)
CP_RAD          = CP + 1        ; tmthing's radius (whole units: MP_RAD+2)
; the walk's blocks (walkRange's results and the walk's place): kept on
; the stack across PIT_CheckThing (CP_BX .. CP_TH + 1, CP_WALK bytes)
CP_BX           = CP + 2        ; the block's x (walkRange: xl)
CP_BY           = CP + 3        ; its y
CP_XH           = CP + 4        ; the last x
CP_YL           = CP + 5        ; the first y
CP_YH           = CP + 6        ; the last y
CP_IDX          = CP + 7        ; 2: the block's index (y width + x)
CP_ROW          = CP + 9        ; 2: yl width
CP_TH           = CP + 11       ; 2: the things' walk: the thing
CP_WALK         = CP_TH + 2 - CP_BX
CP_RS           = CP + 13       ; 2: the sum of the radii
CP_RS2          = CP + 15       ; 2: twice the sum
CP_PR           = CP + 17       ; the last radius ($FF: none)
; the lines' walk (over the things' walk's bytes from CP_TH on)
CP_MISS         = CP + 11       ; MP_MISSILE: tmthing is a missile
CP_PLAY         = CP + 12       ; MP_PLAYER: tmthing is the player's
CP_BH           = CP + 13       ; 2: bottom >> 16 ($7FFF: an edge of -32768.0)
CP_TF           = CP + 15       ; 2: (top >> 16) - (its low word == 0)
CP_RF           = CP + 17       ; 2: (right >> 16) - (its low word == 0)
CP_LH           = CP + 19       ; 2: left >> 16
CP_POS          = CP + 21       ; 2: the list's entry (a blockmap word)
CP_LN           = CP + 23       ; 2: the line
CP_WIN          = CP + 25       ; 1: BL_BUF holds the window CP_WB
CP_WB           = CP + 26       ; 2: the window's first word
CP_SEC          = CP + 28       ; the line's sector being taken
CP_SEC2         = CP + 29       ; its back sector
CP_END          = CP + 30
        .assert CP_END <= SB_CHECKPOS + SB_CHECKPOS_SIZE, error, "checkpos's scratch block"

; the mobj line's groups (mo_get's GC_MP: RTHING, then A, B, C)
LN_A            = MO_SIZE
LN_B            = 2 * MO_SIZE
LR_MAX          = 24            ; the line record's lines (p_map65.s:174)

        .assert UC_MF_MISSILE_HI = 1, error, "MF_MISSILE: bit 0 of the flags' byte 2"
        .assert >UC_MF_PICKUP_LO = $08 && <UC_MF_PICKUP_LO = 0, error, "MF_PICKUP: bit 3 of byte 1"
        .assert <UC_MF_NOCLIP_LO = 0, error, "MF_NOCLIP: byte 1"
        .assert >UC_MF_SOLID_LO = 0 && >UC_MF_SPECIAL_LO = 0 && >UC_MF_SHOOTABLE_LO = 0, error, "byte 0's flags"
        .assert >UC_ML_BLOCKING = 0 && >UC_ML_BLOCKMONSTERS = 0, error, "the line flags' low byte"
