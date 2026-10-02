; game/geom/geom.inc: part geom's results (milestone 10, docs/GAME.md
; 2.4 row geom, 4.4). GPL-2, the port's own. Included after ggame.inc.
;
; The names hold the results upstream leaves in its near scratch of
; p_map65.s and its callers read after the return (GAME.md 2.4 "Inputs and
; outputs"); they live until the next call that writes them, as upstream's
; near globals do:
;
;   GEO_OPENTOP, GEO_OPENBOT, GEO_OPENRANGE
;                   P_LineOpening's and P_LineOpeningXY's opentop,
;                   openbottom, openrange (_g_opentop ...; fixed_t each)
;   GEO_TMFLOORZ, GEO_TMCEILZ, GEO_TMDROPZ
;                   sectorFloor's tmfloorz, tmceilingz, tmdropoffz
;                   (_g_tmfloorz ...): the floor and ceiling of the point's
;                   sector, which P_CheckPosition goes on lowering and
;                   raising (part checkpos)
;   GEO_SS, GEO_SEC pointSector's MV_SS (the subsector, a word) and MV_SEC
;                   (its sector, a byte), which P_TryMove reads after
;                   checkPos's walks (p_map65.s:475-512)
;   GEO_NSPEC       baseLite's numspechit (a byte: 0 there)
;   GEO_BXL .. GEO_BYH
;                   blockRange's MP_XL, MP_XH, MP_YL, MP_YH (bytes: when it
;                   returns C clear, the only case its caller reads them,
;                   each is a block number below 256)
;
; Wave 1 as integrated (request R3 of docs/game-parts/geom.md): these are
; upstream's near scratch of p_map65.s, read by later parts (checkpos,
; trymove, attack, xymove, player, pspr, teleport): the shared tic scratch
; GM_* of ggame.inc (GW, never overlaid). SB_GEOM is no longer used.

GEO_OPENTOP     = GM_OPENTOP
GEO_OPENBOT     = GM_OPENBOT
GEO_OPENRANGE   = GM_OPENRANGE
GEO_TMFLOORZ    = GM_TMFLOORZ
GEO_TMCEILZ     = GM_TMCEILZ
GEO_TMDROPZ     = GM_TMDROPZ
GEO_SS          = GM_SS
GEO_SEC         = GM_SEC
GEO_NSPEC       = GM_NSPEC
GEO_BXL         = GM_BXL
GEO_BXH         = GM_BXH
GEO_BYL         = GM_BYL
GEO_BYH         = GM_BYH

; the box of P_BoxOnLineSide and blockRange in GA_0..GA_15, upstream's
; order (offsets.inc CONST_BOX*): top, bottom, left, right
GEO_TOP         = GA_0 + 4 * UC_BOXTOP
GEO_BOTTOM      = GA_0 + 4 * UC_BOXBOTTOM
GEO_LEFT        = GA_0 + 4 * UC_BOXLEFT
GEO_RIGHT       = GA_0 + 4 * UC_BOXRIGHT
