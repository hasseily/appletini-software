; game/planes/planes.s: part planes of milestone 10 (docs/GAME.md 2.4,
; wave 4): the plane movers, the check of the things in a moving sector and
; the floor thinker. A GPL-2 derivative of upstream's p_floor65.s
; (T_MovePlaneFloor, T_MovePlaneCeiling with toDest, crushStep and
; restore; checkSector = P_CheckSector; changeSector = PIT_ChangeSector;
; heightClip = P_ThingHeightClip; T_MoveFloor). Upstream's helpers
; planeArgs, minusSpeed, plusSpeed, saveLast, setPlaneT, secArg, loadNode,
; nodeArg, thingArg, floorArg, floorSector, floorSpeed and sectorSound load
; its direct page's pointers: natively the handles are kept in the scratch
; block, and each helper is done in place (a macro, or a local subroutine
; of the routine that uses it); restore is a local subroutine of the
; movers.
;
; The native interfaces (docs/game-parts/planes.md, "Interfaces"):
;
;   T_MovePlaneFloor, T_MovePlaneCeiling
;                   GA_0 = the sector, GA_2-5 = speed, GA_6-9 = dest
;                   (fixed_t), GA_10 = the direction ($FF down, 1 up, else
;                   nothing moves) (upstream's _Dp[0-3], X:C, _Dp[4-7] and
;                   4,s) -> A = UC_OK, UC_CRUSHED or UC_PASTDEST
;   checkSector     A = a sector -> A = nofit (1: a shootable thing did not
;                   fit), also in SB_NOFIT (upstream's MP_SEC, C, NOFIT)
;   changeSector    A:X = a thing (a mobj slot): sets SB_NOFIT to 1 when it
;                   is shootable and does not fit (upstream's _Dp[0-3],
;                   NOFIT); a corpse that does not fit becomes gibs, a
;                   dropped item is removed
;   heightClip      A:X = a thing -> A = 1 when it fits, else 0; its
;                   floorz, ceilingz, dropoffz from P_CheckPosition at its
;                   place, z on the floor (or under the ceiling)
;   THTAB's T_MoveFloor
;                   GA_0-1 = the floor thinker's handle (upstream's
;                   _Dp[0-3])
;
; Upstream's move has no crush damage: PIT_ChangeSector only gibs a corpse,
; removes a dropped item or sets nofit (p_floor65.s:390-437, Doom8088's
; p_floor.c without the crunch's P_DamageMobj), and the movers take no
; crush argument (p_floor65.s:80-86).
;
; A sector's floor and ceiling heights are its render record's SEC_FLOOR,
; SEC_CEIL (4 bytes each); its touching-thing list is the game record's
; SG_TOUCH (a sector node, $FFFF none), each node's next in the sector
; SN_SNEXT, its thing SN_THING (a slot), its visited word SN_VISITED (0 or
; 1, as upstream's 16-bit int). Signed 32-bit compares are upstream's
; SLT32: a - b on the four bytes, the sign with the overflow folded in.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export T_MovePlaneFloor, T_MovePlaneCeiling, checkSector
        .export changeSector, heightClip, T_MoveFloor
        .import sec_get, sec_dirty, sn_get, sn_putw, mo_get, mo_dirty
        .import sp_get, pl_get, pl_put, S_StartSound2
        .import fc_call, fc_unbuilt

        .assert SEC_FLOOR = 0 && SEC_CEIL = 4, error, "the sector's heights"
        .assert UC_OK = 0 && UC_CRUSHED = 1 && UC_PASTDEST = 2, error, "result_e"
        .assert >UC_S_GIBS = 1, error, "S_GIBS's high byte"
        .assert UC_MF_NOBLOCKMAP_HI = 0 && >UC_MF_NOBLOCKMAP_LO = 0, error, "MF_NOBLOCKMAP's byte (0)"
        .assert UC_MF_SOLID_HI = 0 && >UC_MF_SOLID_LO = 0, error, "MF_SOLID's byte (0)"
        .assert UC_MF_SHOOTABLE_HI = 0 && >UC_MF_SHOOTABLE_LO = 0, error, "MF_SHOOTABLE's byte (0)"
        .assert UC_MF_DROPPED_LO = 0 && >UC_MF_DROPPED_HI = 0, error, "MF_DROPPED's byte (2)"
        .assert SPFL_DIRECTION = SPFL_TYPE + 2, error, "the floor's fields"
        ; the movers share their helpers (one group: planes.md request 2)
        .assert GP_T_MovePlaneFloor_G = GP_T_MovePlaneCeiling_G, error, "T_MovePlaneFloor and T_MovePlaneCeiling in one group"

; ---------------------------------------------------------------------------
; The scratch block (SB_PLANES: what a routine keeps across a call). The
; movers' bytes (MP_*) live across checkSector, which never runs a mover;
; changeSector's and heightClip's are their own
; ---------------------------------------------------------------------------
SB_SEC   = SB_PLANES            ; the sector                 MP_SEC
SB_SPD   = SB_PLANES + 1        ; the speed (4)              MP_SPEED
SB_DST   = SB_PLANES + 5        ; the destination (4)        MP_DEST
SB_LST   = SB_PLANES + 9        ; lastpos (4)                MP_LAST
SB_T     = SB_PLANES + 13       ; the new height (4)         MP_T
SB_OFS   = SB_PLANES + 17       ; the plane: SEC_FLOOR or SEC_CEIL (Y)
SB_NOFIT = SB_PLANES + 18       ; nofit                      NOFIT
SB_NODE  = SB_PLANES + 19       ; checkSector's node (2)     CS_NODE
SB_TH    = SB_PLANES + 21       ; changeSector's thing (2)
SB_HT    = SB_PLANES + 23       ; heightClip's thing (2)
SB_ONF   = SB_PLANES + 25       ; onfloor                    TH_ONFLOOR
SB_FL    = SB_PLANES + 26       ; T_MoveFloor's thinker (2)  TM_FLOOR
SB_RES   = SB_PLANES + 28       ; its T_MovePlaneFloor result
SB_END   = SB_PLANES + 29
        .assert SB_END <= SB_PLANES + SB_PLANES_SIZE, error, "scratch"

; a mobj cache line's groups (LW_MOB's layout) and their dirty bits
ML_A    = MO_SIZE
ML_B    = 2 * MO_SIZE
D_RTH   = 1
D_B     = 4

; ---------------------------------------------------------------------------
; Helpers done in place
; ---------------------------------------------------------------------------

; SECTOR: GC_SP = the sector SB_SEC (secArg)
.macro SECTOR
        lda SB_SEC
        jsr sec_get
.endmacro

; SECSOUND sfx: S_StartSound2(the sound origin of sector SB_SEC, sfx)
; (sectorSound)
.macro SECSOUND sfx
        ldx SB_SEC
        ldy #$80
        lda #sfx
        jsr S_StartSound2
.endmacro

; ===========================================================================
; T_MovePlaneFloor, T_MovePlaneCeiling: the plane one step towards dest, the
; things in the sector checked; held by a thing that does not fit: back to
; lastpos (crushed, or still pastdest)
; ===========================================================================
        ROUTINE T_MovePlaneFloor
        jsr plane_args          ; (planeArgs) A = the direction
        cmp #$FF
        beq @down
        cmp #1
        jne mp_okay
        ; the floor up: destheight = min(dest, ceilingheight)
        SECTOR
        ldy #SEC_CEIL
        jsr dst_lt              ; dest < ceilingheight: dest stays
        bmi :+
        ldy #SEC_CEIL
        jsr dst_set
:       lda #SEC_FLOOR
        jsr plus_speed          ; floorheight + speed > destheight
        jsr dst_lt_t
        jmi mp_todest
        jmp mp_crush
@down:  lda #SEC_FLOOR          ; the floor down: past dest, or a step
        jsr minus_speed         ; floorheight - speed < dest
        jsr t_lt_dst
        jmi mp_todest
        jmp mp_step

        ROUTINE T_MovePlaneCeiling
        jsr plane_args
        cmp #$FF
        beq @down
        cmp #1
        jne mp_okay
        lda #SEC_CEIL           ; the ceiling up: past dest, or a step
        jsr plus_speed          ; ceilingheight + speed > dest
        jsr dst_lt_t
        jmi mp_todest
        jmp mp_step
@down:  SECTOR                  ; the ceiling down: destheight =
        ldy #SEC_FLOOR          ;   max(dest, floorheight)
        jsr dst_lt              ; dest < floorheight: dest = floorheight
        bpl :+
        ldy #SEC_FLOOR
        jsr dst_set
:       lda #SEC_CEIL
        jsr minus_speed         ; ceilingheight - speed < destheight
        jsr t_lt_dst
        jmi mp_todest
        ; fall into mp_crush

; mp_crush: the plane = SB_T (one step); a thing that does not fit holds
; it: back to lastpos, crushed (crushStep)
mp_crush:
        jsr mp_set
        beq mp_okay
        jsr mp_restore
        lda #UC_CRUSHED
        rts

; mp_todest: the plane = dest, pastdest; back to lastpos if a thing does
; not fit (toDest)
mp_todest:
        ldx #3
:       lda SB_DST,x
        sta SB_T,x
        dex
        bpl :-
        jsr mp_set
        beq :+
        jsr mp_restore
:       lda #UC_PASTDEST
        rts

; mp_step: the plane = SB_T and the check, whatever it finds
mp_step:
        jsr mp_set
mp_okay:
        lda #UC_OK
        rts

; mp_restore: the plane = lastpos, and the check again (restore)
mp_restore:
        ldx #3
:       lda SB_LST,x
        sta SB_T,x
        dex
        bpl :-
        jsr set_plane
        lda SB_SEC
        FCALL checkSector
        rts

; mp_set: lastpos = the plane (saveLast), the plane = SB_T (setPlaneT),
; checkSector -> A = nofit, Z from it
mp_set:
        SECTOR
        ldy SB_OFS
        ldx #0
:       lda (GC_SP),y
        sta SB_LST,x
        iny
        inx
        cpx #4
        bne :-
        jsr set_plane
        lda SB_SEC
        FCALL checkSector
        cmp #0
        rts

; set_plane: the plane SB_OFS of SB_SEC = SB_T (setPlaneT)
set_plane:
        SECTOR
        ldy SB_OFS
        ldx #0
:       lda SB_T,x
        sta (GC_SP),y
        iny
        inx
        cpx #4
        bne :-
        lda #1
        jmp sec_dirty

; plane_args: SB_SEC, SB_SPD, SB_DST from GA_0-9 -> A = the direction
; (planeArgs)
plane_args:
        lda GA_0
        sta SB_SEC
        ldx #3
:       lda GA_2,x
        sta SB_SPD,x
        lda GA_6,x
        sta SB_DST,x
        dex
        bpl :-
        lda GA_10
        rts

; minus_speed, plus_speed: SB_OFS = A; SB_T = the plane -/+ the speed
; (minusSpeed, plusSpeed)
minus_speed:
        jsr plane_at
        sec
:       lda (GC_SP),y
        sbc SB_SPD,x
        sta SB_T,x
        iny
        inx
        txa
        eor #4
        bne :-                  ; (eor leaves the carry)
        rts
plus_speed:
        jsr plane_at
        clc
:       lda (GC_SP),y
        adc SB_SPD,x
        sta SB_T,x
        iny
        inx
        txa
        eor #4
        bne :-
        rts
plane_at:
        sta SB_OFS
        SECTOR
        ldy SB_OFS
        ldx #0
        rts

; dst_lt: N = (dest < the sector's 4 bytes at Y), signed (GC_SP the sector)
dst_lt:
        sec
        lda SB_DST
        sbc (GC_SP),y
        iny
        lda SB_DST + 1
        sbc (GC_SP),y
        iny
        lda SB_DST + 2
        sbc (GC_SP),y
        iny
        lda SB_DST + 3
        sbc (GC_SP),y
        bvc :+
        eor #$80
:       rts

; dst_set: dest = the sector's 4 bytes at Y
dst_set:
        ldx #0
:       lda (GC_SP),y
        sta SB_DST,x
        iny
        inx
        cpx #4
        bne :-
        rts

; dst_lt_t: N = (dest < SB_T); t_lt_dst: N = (SB_T < dest), signed
dst_lt_t:
        sec
        lda SB_DST
        sbc SB_T
        lda SB_DST + 1
        sbc SB_T + 1
        lda SB_DST + 2
        sbc SB_T + 2
        lda SB_DST + 3
        sbc SB_T + 3
        bvc :+
        eor #$80
:       rts
t_lt_dst:
        sec
        lda SB_T
        sbc SB_DST
        lda SB_T + 1
        sbc SB_DST + 1
        lda SB_T + 2
        sbc SB_DST + 2
        lda SB_T + 3
        sbc SB_DST + 3
        bvc :+
        eor #$80
:       rts

; ===========================================================================
; checkSector: P_CheckSector: every node of the sector's touching-thing
; list unvisited; then, from the list's head each time (the list can change
; on the way), the first unvisited node is visited and its thing, unless
; MF_NOBLOCKMAP, goes to PIT_ChangeSector. A = nofit
; ===========================================================================
        ROUTINE checkSector
        sta SB_SEC
        stz SB_NOFIT
        jsr cs_head
        stz API_W               ; visited = 0 on every node
        stz API_W+1
@clear: lda SB_NODE+1
        cmp #$FF
        beq @again
        ldy #SN_VISITED
        lda SB_NODE
        ldx SB_NODE+1
        jsr sn_putw
        jsr cs_next
        bra @clear
@again: jsr cs_head             ; do: the first unvisited node
@scan:  lda SB_NODE+1
        cmp #$FF
        beq @done
        lda SB_NODE
        ldx SB_NODE+1
        jsr sn_get
        lda SN_BUF + SN_VISITED
        ora SN_BUF + SN_VISITED + 1
        beq @visit
        lda SN_BUF + SN_SNEXT
        sta SB_NODE
        lda SN_BUF + SN_SNEXT + 1
        sta SB_NODE+1
        bra @scan
@visit: lda SN_BUF + SN_THING   ; the thing (before sn_putw)
        sta SB_TH
        lda SN_BUF + SN_THING + 1
        sta SB_TH+1
        lda #1                  ; visited = 1
        sta API_W
        stz API_W+1
        ldy #SN_VISITED
        lda SB_NODE
        ldx SB_NODE+1
        jsr sn_putw
        lda SB_TH               ; not MF_NOBLOCKMAP: PIT_ChangeSector
        ldx SB_TH+1
        jsr mo_get
        ldy #ML_B + MB_FLAGS
        lda (GC_MP),y
        and #<UC_MF_NOBLOCKMAP_LO
        bne @again
        lda SB_TH
        ldx SB_TH+1
        FCALL changeSector
        bra @again
@done:  lda SB_NOFIT
        rts

; cs_head: SB_NODE = the sector's first node (loadNode)
cs_head:
        SECTOR
        ldy #SEC_SIZE + SG_TOUCH
        lda (GC_SP),y
        sta SB_NODE
        iny
        lda (GC_SP),y
        sta SB_NODE+1
        rts

; cs_next: SB_NODE = its next in the sector (m_snext)
cs_next:
        lda SB_NODE
        ldx SB_NODE+1
        jsr sn_get
        lda SN_BUF + SN_SNEXT
        sta SB_NODE
        lda SN_BUF + SN_SNEXT + 1
        sta SB_NODE+1
        rts

; ===========================================================================
; changeSector: PIT_ChangeSector: a thing that does not fit is crushed to
; gibs (a corpse: health <= 0; not solid, no height, no radius), removed
; (a dropped item), or sets nofit (shootable)
; ===========================================================================
        ROUTINE changeSector
        sta SB_TH
        stx SB_TH+1
        FCALL heightClip
        cmp #0
        bne @done
        jsr ch_get
        ldy #ML_A + MA_HEALTH + 1 ; dead (health <= 0): gibs
        lda (GC_MP),y
        bmi @gibs
        dey
        ora (GC_MP),y
        bne @alive
@gibs:  lda SB_TH
        sta GA_0
        lda SB_TH+1
        sta GA_1
        lda #<UC_S_GIBS
        ldx #>UC_S_GIBS
        FCALL P_SetMobjState
        jsr ch_get
        ldy #ML_B + MB_FLAGS    ; not solid
        lda (GC_MP),y
        and #<~UC_MF_SOLID_LO
        sta (GC_MP),y
        lda #0                  ; height 0, radius 0
        ldy #ML_B + MB_HEIGHT
        jsr ch_zero
        ldy #ML_B + MB_RADIUS
        jsr ch_zero
        lda #D_B
        jmp mo_dirty
@alive: ldy #ML_B + MB_FLAGS + 2 ; a dropped item: removed
        lda (GC_MP),y
        and #<UC_MF_DROPPED_HI
        beq @shoot
        lda SB_TH
        ldx SB_TH+1
        FCALL P_RemoveMobj
        rts
@shoot: ldy #ML_B + MB_FLAGS    ; shootable: nofit
        lda (GC_MP),y
        and #<UC_MF_SHOOTABLE_LO
        beq @done
        lda #1
        sta SB_NOFIT
@done:  rts

ch_get: lda SB_TH
        ldx SB_TH+1
        jmp mo_get

; ch_zero: the line's 4 bytes at Y = A (0)
ch_zero:
        ldx #4
:       sta (GC_MP),y
        iny
        dex
        bne :-
        rts


; ===========================================================================
; heightClip: P_ThingHeightClip: onfloor = z == floorz; P_CheckPosition at
; its place gives floorz, ceilingz, dropoffz; z = floorz when it was on
; the floor, else z = ceilingz - height when z + height > ceilingz; A = 1
; when !(ceilingz - floorz < height), signed
; ===========================================================================
        .assert MB_CEILZ = MB_FLOORZ + 4 && MB_DROPZ = MB_FLOORZ + 8, error, "floorz, ceilingz, dropoffz"
        .assert GM_TMCEILZ = GM_TMFLOORZ + 4 && GM_TMDROPZ = GM_TMFLOORZ + 8, error, "tmfloorz, tmceilingz, tmdropoffz"
        .assert TH_Y = TH_X + 4, error, "x, y"
HZ      = GA_10                 ; (4) z, then z + height, ceilingz - height
HD      = GA_14                 ; (4) ceilingz - floorz

        ROUTINE heightClip
        sta SB_HT
        stx SB_HT+1
        jsr hc_get
        jsr hc_z                ; onfloor = z == floorz
        stz SB_ONF
        ldy #ML_B + MB_FLOORZ
        ldx #0
:       lda (GC_MP),y
        cmp HZ,x
        bne @args
        iny
        inx
        cpx #4
        bne :-
        inc SB_ONF
@args:  lda SB_HT               ; P_CheckPosition(thing, x, y)
        sta GA_0
        lda SB_HT+1
        sta GA_1
        ldy #TH_X
        ldx #0
:       lda (GC_MP),y
        sta GA_2,x
        iny
        inx
        cpx #8
        bne :-
        FCALL P_CheckPosition
        lda SB_HT               ; (upstream's CLEARCLEAN)
        ldx SB_HT+1
        jsr pl_get
        lda PL_K
        and #$FF ^ KIND_CLEAN
        sta PL_K
        lda SB_HT
        ldx SB_HT+1
        jsr pl_put
        jsr hc_get              ; floorz, ceilingz, dropoffz
        ldy #ML_B + MB_FLOORZ
        ldx #0
:       lda GM_TMFLOORZ,x
        sta (GC_MP),y
        iny
        inx
        cpx #12
        bne :-
        lda #D_B
        jsr mo_dirty
        lda SB_ONF
        beq @under
        ldx #0                  ; on the floor: z = floorz
:       lda GM_TMFLOORZ,x
        sta HZ,x
        inx
        cpx #4
        bne :-
        bra @zset
@under: jsr hc_z                ; z + height
        ldy #ML_B + MB_HEIGHT
        ldx #0
        clc
:       lda HZ,x
        adc (GC_MP),y
        sta HZ,x
        iny
        inx
        txa
        eor #4
        bne :-                  ; (eor leaves the carry)
        lda GM_TMCEILZ          ; ceilingz < z + height: below it
        cmp HZ
        lda GM_TMCEILZ+1
        sbc HZ+1
        lda GM_TMCEILZ+2
        sbc HZ+2
        lda GM_TMCEILZ+3
        sbc HZ+3
        bvc :+
        eor #$80
:       bpl @fits
        ldy #ML_B + MB_HEIGHT   ; z = ceilingz - height
        ldx #0
        sec
:       lda GM_TMCEILZ,x
        sbc (GC_MP),y
        sta HZ,x
        iny
        inx
        txa
        eor #4
        bne :-
@zset:  ldy #TH_Z
        ldx #0
:       lda HZ,x
        sta (GC_MP),y
        iny
        inx
        cpx #4
        bne :-
        lda #D_RTH
        jsr mo_dirty
@fits:  ldx #0                  ; ceilingz - floorz
        sec
:       lda GM_TMCEILZ,x
        sbc GM_TMFLOORZ,x
        sta HD,x
        inx
        txa
        eor #4
        bne :-
        ldy #ML_B + MB_HEIGHT   ; < height: no fit
        lda HD
        cmp (GC_MP),y
        iny
        lda HD+1
        sbc (GC_MP),y
        iny
        lda HD+2
        sbc (GC_MP),y
        iny
        lda HD+3
        sbc (GC_MP),y
        bvc :+
        eor #$80
:       bmi @no
        lda #1
        rts
@no:    lda #0
        rts

hc_get: lda SB_HT
        ldx SB_HT+1
        jmp mo_get

; hc_z: HZ = the thing's z
hc_z:   ldy #TH_Z
        ldx #0
:       lda (GC_MP),y
        sta HZ,x
        iny
        inx
        cpx #4
        bne :-
        rts

; ===========================================================================
; T_MoveFloor: the floor thinker: T_MovePlaneFloor(its sector, speed,
; dest, direction); the stone sound when (leveltime & 7) == 0; at the
; destination a donut's pool (up, DONUTRAISE) takes its new floor pic and
; loses its special, the sector's floordata is none, the thinker is
; removed (P_RemoveThinker: late, as upstream's), and the stop sound
; ===========================================================================
        .assert SPFL_SPEED = SPFL_DEST + 4, error, "dest, speed"

        ROUTINE T_MoveFloor
        lda GA_0
        sta SB_FL
        lda GA_1
        sta SB_FL+1
        jsr fl_get
        ldy #SPFL_DIRECTION
        lda (GC_XP),y
        sta GA_10
        ldy #SP_SECTOR
        lda (GC_XP),y
        sta GA_0
        sta SB_SEC
        ldy #SPFL_DEST          ; dest, then speed
        ldx #0
:       lda (GC_XP),y
        sta GA_6,x
        iny
        inx
        cpx #4
        bne :-
        ldx #0
:       lda (GC_XP),y
        sta GA_2,x
        iny
        inx
        cpx #4
        bne :-
        FCALL T_MovePlaneFloor
        sta SB_RES
        lda G_LEVELTIME         ; the stone sound when (leveltime & 7) == 0
        and #7
        bne :+
        SECSOUND UC_SFX_STNMOV
:       lda SB_RES
        cmp #UC_PASTDEST
        beq @end
        rts
@end:   jsr fl_get              ; up, a donut: the new floor of the pool
        ldy #SPFL_DIRECTION
        lda (GC_XP),y
        cmp #1
        bne @data
        ldy #SPFL_TYPE + 1
        lda (GC_XP),y
        bne @data
        dey
        lda (GC_XP),y
        cmp #UC_DONUTRAISE
        bne @data
        ldy #SPFL_TEXTURE
        lda (GC_XP),y
        pha
        SECTOR
        pla
        ldy #SEC_FPIC
        sta (GC_SP),y
        lda #0
        ldy #SEC_SIZE + SG_SPECIAL
        sta (GC_SP),y
        lda #3
        jsr sec_dirty
@data:  SECTOR                  ; sector->floordata = none
        lda #$FF
        ldy #SEC_SIZE + SG_FLOORD
        sta (GC_SP),y
        iny
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        lda SB_FL               ; P_RemoveThinker(&floor->thinker)
        ldx SB_FL+1
        FCALL P_RemoveThinker
        SECSOUND UC_SFX_PSTOP   ; the stop sound
        rts

fl_get: lda SB_FL
        ldx SB_FL+1
        jmp sp_get
