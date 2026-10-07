; game/path/path.inc: part path's places (docs/GAME.md: the trace, the
; parts' places). GPL-2, the port's own.
; Included after ggame.inc.
;
; The walk's state of P_PathTraverse: upstream's near scratch of
; p_path65.s (PT_*, TI_*: p_path65.s:37-94), which lives across the calls
; of the block steps (traceLines, traceThings, P_BlockLinesIterator) and of
; the traverser (any game logic), so it is in the part's scratch block.
; The trace itself (x1, y1 moved off a block line, dx, dy) is the shared
; GM_TRACE (part tracel's); the ends and the starts from the block map's
; origin are made from it and G_BMORGX, G_BMORGY when needed, so no copy
; of x1 .. y2 is kept.
;
; 44 bytes: the default block is 32; glayout.SCRATCH_REQUESTS['path']
; gives the part 44.
;
;   PT_FLAGS  the flags (UC_PT_ADDLINES, UC_PT_ADDTHINGS)
;   PT_TRAV   the traverser: its TRVTAB number
;   PT_XT1 .. PT_YT2   the blocks of the ends (words, signed: xt1, yt1,
;             xt2, yt2; x then y, so that an axis X = 0, 4 is X / 2 here)
;   PT_XSTEP, PT_YSTEP  xstep, ystep (fixed_t; + 4 the y one)
;   PT_XI, PT_YI        xintercept, yintercept (fixed_t; + 4 the y one)
;   PT_MX, PT_MY        mapx, mapy (words, signed)
;   PT_MXS, PT_MYS      mapxstep, mapystep (words: 1, -1, 0)
;   PT_COUNT  the steps so far (0-64)
;   PT_K      128 FRACUNIT / L for the early traversal, 0 none (a word)
;   PT_RAN    not 0 when the traverser ran in this step (upstream's
;             PT_TRV against PT_TR0)
;   PT_IP0    the intercepts before this block's things (upstream's PT_IP0,
;             an index here)
;   PT_LIM    TI_LIM: traverseTo's limit (fixed_t, signed)
;   PT_IN     TI_IN: the intercept the traverser has (its index)

PT        = SB_PATH
PT_FLAGS  = PT + 0
PT_TRAV   = PT + 1
PT_XT1    = PT + 2
PT_YT1    = PT + 4
PT_XT2    = PT + 6
PT_YT2    = PT + 8
PT_XSTEP  = PT + 10
PT_YSTEP  = PT + 14
PT_XI     = PT + 18
PT_YI     = PT + 22
PT_MX     = PT + 26
PT_MY     = PT + 28
PT_MXS    = PT + 30
PT_MYS    = PT + 32
PT_COUNT  = PT + 34
PT_K      = PT + 35
PT_RAN    = PT + 37
PT_IP0    = PT + 38
PT_LIM    = PT + 39
PT_IN     = PT + 43
PT_NEED   = 44
        .assert SB_PATH_SIZE >= PT_NEED, error, "path's scratch block"

; The trace (GM_TRACE): x, y, dx, dy
PT_TRX    = GM_TRACE + 0
PT_TRY    = GM_TRACE + 4
PT_TRDX   = GM_TRACE + 8
PT_TRDY   = GM_TRACE + 12

MAXSTEPS  = 64                  ; for (count = 0; count < 64; count++)
IC_HEAD   = MAXINTERCEPTS       ; the by-frac chain's head: ICHAIN + 64
