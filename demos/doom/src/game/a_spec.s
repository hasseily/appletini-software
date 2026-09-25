; Doom for the Appletini -- line and sector specials, lights, switches,
; 6502 (docs/DESIGN.md section 9).
;
; The assembly twin of the runtime half of p_spec.c, p_lights.c and
; p_switch.c (the C is the reference, compiled on the host; read it for
; the why of each step). a_movers.s has the doors, floors, stairs, plats,
; ceilings and teleporters; the level set-up and its undoing
; (P_SpawnSpecials, P_ResetLevelData) stay C, in the set-up overlay.
;
;   P_CrossSpecialLine, P_ShootSpecialLine, P_UseSpecialLine
;               spec_tab (as the C's): trigger, action, argument of every
;               vanilla line special; run_action dispatches to the EV_
;               routines with the line in ev_line, the argument in ev_arg,
;               the thing in ev_thing, the side in ev_side; they return
;               A = the count of sectors started (0 or 1)
;   P_PlayerInSpecialSector, P_UpdateSpecials (lights, buttons, scrolling
;               walls), P_SpawnSectorSpecial (the set-up's lights and
;               doors), P_ResetButtons
;   the tools of a_movers.s: the tagged-sector iterator (tag_first,
;               tag_next), a sector's lines (sl_start, sl_next), the other
;               side of a line (next_sector), the neighbour searches
;               (nb_find), the busy bits, the movers (new_mover,
;               remove_mover, find_mover), move_plane (T_MovePlane), the
;               journal (journal, clear_line_special), change_switch
;
; Reentrancy: what the movers call out to (P_ChangeSector, P_DamageMobj,
; P_TeleportMove, P_SpawnMobj) may run monster actions, and A_BossDeath
; starts floors (EV_DoFloorTag). So move_plane keeps its mover (mv) on
; the stack across P_ChangeSector, and the line entry points keep their
; line and trigger on the stack across the action; the EV_ routines' own
; variables are theirs alone (EV_ calls do not nest, but for that one).

.include "gmacros.inc"
.include "aspec.inc"
.ifdef BANKED_GAME
.include "banked.inc"
.endif

.ifdef DD_MAPDIR

.globalzp far_src, far_dst, far_ptr, far_len
.import kjt_far_read, kjt_far_write, kjt_far_copy
.import lev_addr, lev_idx, lev_far, far_rd, far_wr, line_get
.import _P_AllocThinker, _P_AddThinker, _P_RemoveThinker, _thinkercap
.import _P_SetSectorFloor, _P_SetSectorCeiling, _P_SetSectorSpecial, _P_SetSectorLight
.import _P_SetLineSpecial, _P_ChangeSector, _P_DamageMobj, _P_Random, _S_StartSound
.import _G_ExitLevel, _G_SecretExitLevel
.import _sec_floorh, _sec_ceilh, _sec_special, _leveltime, _player, _kbanks
.import _numsectors, _numlines, _totalsecret, _P_ArenaAlloc, _kernel_crash
.import pushax, pusha, popax, incsp2, incsp3, incsp4
; a_movers.s
.import ev_do_door, ev_locked_door, ev_vertical_door, ev_do_floor, ev_do_plat, ev_stop_plat
.import ev_do_ceiling, ev_crush_stop, ev_build_stairs, ev_donut, ev_teleport
.import door_close30, door_raise5

.export _P_CrossSpecialLine, _P_ShootSpecialLine, _P_UseSpecialLine
.export _P_PlayerInSpecialSector, _P_UpdateSpecials, _P_SpawnSectorSpecial, _P_ResetButtons
.export _P_SpawnSpecials, _P_ResetLevelData
.export _sec_busy, _tag_list, _tag_count, _scroll_list, _scroll_count, _jcount
.export _lights, _numlights, _maxlights
.export mv, ev_line, ev_tag, ev_arg, ev_thing, ev_side, ev_sec, pl_amount
.export tg_tag, tag_first, tag_next, ev_get_tag
.export sl_start, sl_next, next_sector, ns_sec
.export nb_find, nb_sec, nb_h, nb_ref
.export is_busy, set_busy, clr_busy, new_mover, remove_mover, find_mover, nm_func, fm_sec, fm_func
.export move_plane, mp_dest, mp_crush, mp_ceil, mp_dir
.export floor_of, ceil_of, special_of, sec_floorpic, set_floorpic, snd_null
.export journal, clear_line_special, change_switch, cs_line

MAXBUTTONS  = 16
BUTTONTIME  = 35
FASTDARK    = 15
SLOWDARK    = 35
STROBEBRIGHT = 5
GLOWSPEED   = 8

; the table's trigger byte (p_spec.c): kind in bits 0-2, then flags
TR_W        = 1
TR_S        = 2
TR_G        = 3
TR_D        = 4
TR_KIND     = 7
TR_REPEAT   = $08
TR_MONSTER  = $10
TR_ALWAYS   = $20
; actions (p_spec.c SA_*)
SA_NONE     = 0
SA_DOOR     = 1
SA_LOCKED   = 2
SA_VDOOR    = 3
SA_FLOOR    = 4
SA_PLAT     = 5
SA_STOPPLAT = 6
SA_CEIL     = 7
SA_CRUSHSTOP = 8
SA_STAIRS   = 9
SA_DONUT    = 10
SA_LIGHTON  = 11
SA_STROBE   = 12
SA_LIGHTSOFF = 13
SA_TELEPORT = 14
SA_EXIT     = 15
SA_CEILFLOOR = 16
CRASH_BANKS_SPEC = $23              ; p_local.h CRASH_BANKS
SPARE_LIGHTS = 8                    ; p_spec.h
MAXSCROLLERS = 32
PLAT24      = $10
PLAT32      = $20
NUMSPECIALS = 142

.segment "BSS"
; the state P_SpawnSpecials (C, set-up) makes (p_spec.h)
_sec_busy:  .res 2
_tag_list:  .res 2
_tag_count: .res 2
_scroll_list: .res 2
_scroll_count: .res 1
_jcount:    .res 2
_lights:    .res 2
_numlights: .res 1
_maxlights: .res 1
; the line entry points and the EV_ routines
ev_line:    .res 2
ev_tag:     .res 2
ev_arg:     .res 1
ev_thing:   .res 2
ev_side:    .res 1
ev_sec:     .res 2
pl_amount:  .res 1                  ; EV_DoPlat's amount (24, 32)
e_trig:     .res 1
e_act:      .res 1
e_arg:      .res 1
us_special: .res 1
; the tagged sectors
tg_pos:     .res 2
tg_tag:     .res 2
; a sector's lines (sl_count, sl_first: the SECTOR record's order)
sl_count:   .res 2
sl_first:   .res 2
sl_i:       .res 2
sl_line:    .res 2
ns_sec:     .res 2
; the neighbour searches
nb_kind:    .res 1
nb_sec:     .res 2
nb_h:       .res 2
nb_ref:     .res 2
nb_o:       .res 2
nb_v:       .res 2
; movers
mv:         .res 2
nm_func:    .res 2
fm_sec:     .res 2
fm_func:    .res 2
; move_plane
mp_sec:     .res 2
mp_last:    .res 2
mp_now:     .res 2
mp_dest:    .res 2
mp_crush:   .res 1
mp_ceil:    .res 1
mp_dir:     .res 1
mp_res:     .res 1
mp_step:    .res 1
; the player's sector
ps_sec:     .res 2
; lights
lt_ptr:     .res 2
lt_n:       .res 1
lt_new:     .res 2
lv:         .res 2
lamt:       .res 1
nl_kind:    .res 1
ss_dark:    .res 1
ss_sync:    .res 1
ss_spec:    .res 1
sl_s:       .res 2
sl_v:       .res 1
lo_bright:  .res 1
; buttons (structure of arrays)
bt_line_lo: .res MAXBUTTONS
bt_line_hi: .res MAXBUTTONS
bt_side_lo: .res MAXBUTTONS
bt_side_hi: .res MAXBUTTONS
bt_where:   .res MAXBUTTONS
bt_tex_lo:  .res MAXBUTTONS
bt_tex_hi:  .res MAXBUTTONS
bt_timer:   .res MAXBUTTONS
buttons_on: .res 1
rb_up:      .res 1
; switches
cs_line:    .res 2
cs_again:   .res 1
cs_side:    .res 2
cs_rec:     .res 3
cs_tex:     .res 6                  ; top, bottom, middle (the SIDEDEF order)
cs_other:   .res 2
cs_i:       .res 1
cs_where:   .res 1
; the journal
jn_e:       .res 6
cl_line:    .res 2
; scrolling walls
sc_i:       .res 1
sc_val:     .res 2
tmpb:       .res 1

.segment "RODATA"
bitmask:    .byte 1, 2, 4, 8, 16, 32, 64, 128
; switch_tex's order: top, middle, bottom (SIDEDEF_ offsets)
where_tab:  .byte SIDEDEF_TOPTEXTURE, SIDEDEF_MIDTEXTURE, SIDEDEF_BOTTOMTEXTURE
; the actions
sa_tab:     .word ac_none, ev_do_door, ev_locked_door, ac_vdoor, ev_do_floor, ac_plat
            .word ac_stopplat, ev_do_ceiling, ev_crush_stop, ev_build_stairs, ev_donut
            .word ac_lighton, ac_strobe, ac_lightsoff, ev_teleport, ac_exit, ac_ceilfloor

; vanilla's P_CrossSpecialLine, P_UseSpecialLine and P_ShootSpecialLine as
; data: special -> trigger, action, argument (p_spec.c spec_tab)
.macro W1 ac, ag
        .byte TR_W, ac, ag
.endmacro
.macro WR ac, ag
        .byte TR_W | TR_REPEAT, ac, ag
.endmacro
.macro S1 ac, ag
        .byte TR_S, ac, ag
.endmacro
.macro SR ac, ag
        .byte TR_S | TR_REPEAT, ac, ag
.endmacro
.macro DR ac, ag
        .byte TR_D | TR_REPEAT, ac, ag
.endmacro
.macro D1 ac, ag
        .byte TR_D, ac, ag
.endmacro
spec_tab:
    .byte 0, 0, 0                                       ; 0
    .byte TR_D | TR_REPEAT | TR_MONSTER, SA_VDOOR, 0    ; 1
    W1    SA_DOOR, vld_open                               ; 2
    W1    SA_DOOR, vld_close                              ; 3
    .byte TR_W | TR_MONSTER, SA_DOOR, vld_normal        ; 4
    W1    SA_FLOOR, raiseFloor                            ; 5
    W1    SA_CEIL, fastCrushAndRaise                      ; 6
    S1    SA_STAIRS, build8                               ; 7
    W1    SA_STAIRS, build8                               ; 8
    S1    SA_DONUT, 0                                     ; 9
    .byte TR_W | TR_MONSTER, SA_PLAT, downWaitUpStay    ; 10
    .byte TR_S | TR_ALWAYS, SA_EXIT, 0                  ; 11
    W1    SA_LIGHTON, 0                                   ; 12
    W1    SA_LIGHTON, 255                                 ; 13
    S1    SA_PLAT, raiseAndChange | PLAT32                ; 14
    S1    SA_PLAT, raiseAndChange | PLAT24                ; 15
    W1    SA_DOOR, vld_close30ThenOpen                    ; 16
    W1    SA_STROBE, 0                                    ; 17
    S1    SA_FLOOR, raiseFloorToNearest                   ; 18
    W1    SA_FLOOR, lowerFloor                            ; 19
    S1    SA_PLAT, raiseToNearestAndChange                ; 20
    S1    SA_PLAT, downWaitUpStay                         ; 21
    W1    SA_PLAT, raiseToNearestAndChange                ; 22
    S1    SA_FLOOR, lowerFloorToLowest                    ; 23
    .byte TR_G | TR_ALWAYS, SA_FLOOR, raiseFloor        ; 24
    W1    SA_CEIL, crushAndRaise                          ; 25
    .byte TR_D | TR_REPEAT, SA_VDOOR, 0                 ; 26
    .byte TR_D | TR_REPEAT, SA_VDOOR, 0                 ; 27
    .byte TR_D | TR_REPEAT, SA_VDOOR, 0                 ; 28
    S1    SA_DOOR, vld_normal                             ; 29
    W1    SA_FLOOR, raiseToTexture                        ; 30
    D1    SA_VDOOR, 0                                     ; 31
    .byte TR_D | TR_MONSTER, SA_VDOOR, 0                ; 32
    .byte TR_D | TR_MONSTER, SA_VDOOR, 0                ; 33
    .byte TR_D | TR_MONSTER, SA_VDOOR, 0                ; 34
    W1    SA_LIGHTON, 35                                  ; 35
    W1    SA_FLOOR, turboLower                            ; 36
    W1    SA_FLOOR, lowerAndChange                        ; 37
    W1    SA_FLOOR, lowerFloorToLowest                    ; 38
    .byte TR_W | TR_MONSTER, SA_TELEPORT, 0             ; 39
    W1    SA_CEILFLOOR, 0                                 ; 40
    S1    SA_CEIL, lowerToFloor                           ; 41
    SR    SA_DOOR, vld_close                              ; 42
    SR    SA_CEIL, lowerToFloor                           ; 43
    W1    SA_CEIL, lowerAndCrush                          ; 44
    SR    SA_FLOOR, lowerFloor                            ; 45
    .byte TR_G | TR_REPEAT | TR_ALWAYS | TR_MONSTER, SA_DOOR, vld_open ; 46
    .byte TR_G | TR_ALWAYS, SA_PLAT, raiseToNearestAndChange ; 47
    .byte 0, 0, 0                                       ; 48 (scrolling: P_UpdateSpecials)
    S1    SA_CEIL, crushAndRaise                          ; 49
    S1    SA_DOOR, vld_close                              ; 50
    .byte TR_S | TR_ALWAYS, SA_EXIT, 1                  ; 51
    WR    SA_EXIT, 0                                      ; 52
    W1    SA_PLAT, perpetualRaise                         ; 53
    W1    SA_STOPPLAT, 0                                  ; 54
    S1    SA_FLOOR, raiseFloorCrush                       ; 55
    W1    SA_FLOOR, raiseFloorCrush                       ; 56
    W1    SA_CRUSHSTOP, 0                                 ; 57
    W1    SA_FLOOR, raiseFloor24                          ; 58
    W1    SA_FLOOR, raiseFloor24AndChange                 ; 59
    SR    SA_FLOOR, lowerFloorToLowest                    ; 60
    SR    SA_DOOR, vld_open                               ; 61
    SR    SA_PLAT, downWaitUpStay                         ; 62
    SR    SA_DOOR, vld_normal                             ; 63
    SR    SA_FLOOR, raiseFloor                            ; 64
    SR    SA_FLOOR, raiseFloorCrush                       ; 65
    SR    SA_PLAT, raiseAndChange | PLAT24                ; 66
    SR    SA_PLAT, raiseAndChange | PLAT32                ; 67
    SR    SA_PLAT, raiseToNearestAndChange                ; 68
    SR    SA_FLOOR, raiseFloorToNearest                   ; 69
    SR    SA_FLOOR, turboLower                            ; 70
    S1    SA_FLOOR, turboLower                            ; 71
    WR    SA_CEIL, lowerAndCrush                          ; 72
    WR    SA_CEIL, crushAndRaise                          ; 73
    WR    SA_CRUSHSTOP, 0                                 ; 74
    WR    SA_DOOR, vld_close                              ; 75
    WR    SA_DOOR, vld_close30ThenOpen                    ; 76
    WR    SA_CEIL, fastCrushAndRaise                      ; 77
    .byte 0, 0, 0                                       ; 78
    WR    SA_LIGHTON, 35                                  ; 79
    WR    SA_LIGHTON, 0                                   ; 80
    WR    SA_LIGHTON, 255                                 ; 81
    WR    SA_FLOOR, lowerFloorToLowest                    ; 82
    WR    SA_FLOOR, lowerFloor                            ; 83
    WR    SA_FLOOR, lowerAndChange                        ; 84
    .byte 0, 0, 0                                       ; 85
    WR    SA_DOOR, vld_open                               ; 86
    WR    SA_PLAT, perpetualRaise                         ; 87
    .byte TR_W | TR_REPEAT | TR_MONSTER, SA_PLAT, downWaitUpStay ; 88
    WR    SA_STOPPLAT, 0                                  ; 89
    WR    SA_DOOR, vld_normal                             ; 90
    WR    SA_FLOOR, raiseFloor                            ; 91
    WR    SA_FLOOR, raiseFloor24                          ; 92
    WR    SA_FLOOR, raiseFloor24AndChange                 ; 93
    WR    SA_FLOOR, raiseFloorCrush                       ; 94
    WR    SA_PLAT, raiseToNearestAndChange                ; 95
    WR    SA_FLOOR, raiseToTexture                        ; 96
    .byte TR_W | TR_REPEAT | TR_MONSTER, SA_TELEPORT, 0 ; 97
    WR    SA_FLOOR, turboLower                            ; 98
    SR    SA_LOCKED, vld_blazeOpen                        ; 99
    W1    SA_STAIRS, turbo16                              ; 100
    S1    SA_FLOOR, raiseFloor                            ; 101
    S1    SA_FLOOR, lowerFloor                            ; 102
    S1    SA_DOOR, vld_open                               ; 103
    W1    SA_LIGHTSOFF, 0                                 ; 104
    WR    SA_DOOR, vld_blazeRaise                         ; 105
    WR    SA_DOOR, vld_blazeOpen                          ; 106
    WR    SA_DOOR, vld_blazeClose                         ; 107
    W1    SA_DOOR, vld_blazeRaise                         ; 108
    W1    SA_DOOR, vld_blazeOpen                          ; 109
    W1    SA_DOOR, vld_blazeClose                         ; 110
    S1    SA_DOOR, vld_blazeRaise                         ; 111
    S1    SA_DOOR, vld_blazeOpen                          ; 112
    S1    SA_DOOR, vld_blazeClose                         ; 113
    SR    SA_DOOR, vld_blazeRaise                         ; 114
    SR    SA_DOOR, vld_blazeOpen                          ; 115
    SR    SA_DOOR, vld_blazeClose                         ; 116
    DR    SA_VDOOR, 0                                     ; 117
    D1    SA_VDOOR, 0                                     ; 118
    W1    SA_FLOOR, raiseFloorToNearest                   ; 119
    WR    SA_PLAT, blazeDWUS                              ; 120
    W1    SA_PLAT, blazeDWUS                              ; 121
    S1    SA_PLAT, blazeDWUS                              ; 122
    SR    SA_PLAT, blazeDWUS                              ; 123
    WR    SA_EXIT, 1                                      ; 124
    .byte TR_W | TR_MONSTER, SA_TELEPORT, 1             ; 125
    .byte TR_W | TR_REPEAT | TR_MONSTER, SA_TELEPORT, 1 ; 126
    S1    SA_STAIRS, turbo16                              ; 127
    WR    SA_FLOOR, raiseFloorToNearest                   ; 128
    WR    SA_FLOOR, raiseFloorTurbo                       ; 129
    W1    SA_FLOOR, raiseFloorTurbo                       ; 130
    S1    SA_FLOOR, raiseFloorTurbo                       ; 131
    SR    SA_FLOOR, raiseFloorTurbo                       ; 132
    S1    SA_LOCKED, vld_blazeOpen                        ; 133
    SR    SA_LOCKED, vld_blazeOpen                        ; 134
    S1    SA_LOCKED, vld_blazeOpen                        ; 135
    SR    SA_LOCKED, vld_blazeOpen                        ; 136
    S1    SA_LOCKED, vld_blazeOpen                        ; 137
    .byte TR_S | TR_REPEAT | TR_ALWAYS, SA_LIGHTON, 255 ; 138
    .byte TR_S | TR_REPEAT | TR_ALWAYS, SA_LIGHTON, 35  ; 139
    S1    SA_FLOOR, raiseFloor512                         ; 140
    W1    SA_CEIL, silentCrushAndRaise                    ; 141
spec_tab_end:
.assert spec_tab_end - spec_tab = 3 * NUMSPECIALS, error, "one entry per special"

SPECCODE

; ---- the table ------------------------------------------------------------------------
; the line ev_line's entry -> e_trig, e_act, e_arg (0s past the table)
spec_entry:
        lda     ev_line
        ldx     ev_line+1
        jsr     line_get
        ldy     #LI_SPECIAL
        lda     (gli),y
        sta     us_special
        stz     e_trig
        stz     e_act
        stz     e_arg
        cmp     #NUMSPECIALS
        bcs     @out
        sta     tmp1                    ; 3 * special
        asl     a
        tax
        lda     #0
        rol     a
        sta     tmp2
        txa
        clc
        adc     tmp1
        sta     ptr1
        lda     tmp2
        adc     #0
        sta     ptr1+1
        clc
        lda     ptr1
        adc     #<spec_tab
        sta     ptr1
        lda     ptr1+1
        adc     #>spec_tab
        sta     ptr1+1
        lda     (ptr1)
        sta     e_trig
        ldy     #1
        lda     (ptr1),y
        sta     e_act
        iny
        lda     (ptr1),y
        sta     e_arg
@out:   rts

; the action e_act with e_arg; A = its count (the switch changes if not 0)
run_action:
        lda     e_arg
        sta     ev_arg
        lda     e_act
        asl     a
        tax
        jmp     (sa_tab,x)

ac_none:
        lda     #0
        rts

ac_vdoor:
        jsr     ev_vertical_door
        lda     #1
        rts

ac_plat:
        lda     ev_arg
        ldx     #24
        bit     #PLAT24
        bne     :+
        ldx     #32
        bit     #PLAT32
        bne     :+
        ldx     #0
:       stx     pl_amount
        and     #15
        sta     ev_arg
        jmp     ev_do_plat

ac_stopplat:
        jsr     ev_stop_plat
        lda     #1
        rts

ac_lighton:
        lda     ev_arg
        jsr     ev_light_on
        lda     #1
        rts

ac_strobe:
        jsr     ev_start_strobing
        lda     #1
        rts

ac_lightsoff:
        jsr     ev_lights_off
        lda     #1
        rts

ac_exit:
        lda     ev_arg
        beq     :+
        jsr     _G_SecretExitLevel
        lda     #1
        rts
:       jsr     _G_ExitLevel
        lda     #1
        rts

ac_ceilfloor:
        lda     #raiseToHighest
        sta     ev_arg
        jsr     ev_do_ceiling
        lda     #lowerFloorToLowest
        sta     ev_arg
        jsr     ev_do_floor
        lda     #1
        rts

; is ev_thing the player's mobj? Z set if so
is_player:
        lda     ev_thing
        cmp     _player+PL_MO
        bne     :+
        lda     ev_thing+1
        cmp     _player+PL_MO+1
:       rts

; the action, keeping the line and the trigger across it (it may come back
; here through a monster's action)
run_kept:
        lda     ev_line
        pha
        lda     ev_line+1
        pha
        lda     e_trig
        pha
        jsr     run_action
        sta     tmp1
        pla
        sta     e_trig
        pla
        sta     ev_line+1
        pla
        sta     ev_line
        lda     tmp1
        rts

; ---- void P_CrossSpecialLine(uint16_t linenum, uint8_t side, mobj_t *thing) ------------
; C stack: +0 side, +1 linenum
_P_CrossSpecialLine:
        sta     ev_thing
        stx     ev_thing+1
        lda     (sp)
        sta     ev_side
        ldy     #1
        lda     (sp),y
        sta     ev_line
        iny
        lda     (sp),y
        sta     ev_line+1
        jsr     incsp3
        jsr     spec_entry
        lda     e_trig
        and     #TR_KIND
        cmp     #TR_W
        bne     @out
        jsr     is_player
        beq     @player
        ; a monster: not projectiles (vanilla's list: all of E1's MF_MISSILE)
        lda     ev_thing
        sta     ptr1
        lda     ev_thing+1
        sta     ptr1+1
        ldy     #MO_FLAGS+2
        lda     (ptr1),y
        and     #MF2_MISSILE
        bne     @out
        lda     e_trig
        and     #TR_MONSTER
        beq     @out
        bra     @run
@player:
        lda     e_act                   ; 125, 126: monsters only
        cmp     #SA_TELEPORT
        bne     @run
        lda     e_arg
        bne     @out
@run:   jsr     run_kept
        lda     e_trig
        and     #TR_REPEAT
        bne     @out
        lda     ev_line
        ldx     ev_line+1
        jmp     clear_line_special
@out:   rts

; ---- void P_ShootSpecialLine(mobj_t *thing, uint16_t linenum) ----------------------------
_P_ShootSpecialLine:
        sta     ev_line
        stx     ev_line+1
        jsr     popax
        sta     ev_thing
        stx     ev_thing+1
        stz     ev_side
        jsr     spec_entry
        lda     e_trig
        and     #TR_KIND
        cmp     #TR_G
        bne     @out
        jsr     is_player
        beq     @run
        lda     e_trig
        and     #TR_MONSTER
        beq     @out
@run:   jsr     run_kept
        lda     ev_line
        sta     cs_line
        lda     ev_line+1
        sta     cs_line+1
        lda     e_trig
        and     #TR_REPEAT
        jmp     change_switch
@out:   rts

; ---- boolean P_UseSpecialLine(mobj_t *thing, uint16_t linenum, uint8_t side) --------------
; C stack: +0 linenum, +2 thing
_P_UseSpecialLine:
        sta     ev_side
        ldy     #3
        lda     (sp),y
        sta     ev_thing+1
        dey
        lda     (sp),y
        sta     ev_thing
        dey
        lda     (sp),y
        sta     ev_line+1
        lda     (sp)
        sta     ev_line
        jsr     incsp4
        lda     ev_side
        bne     @false                  ; only the front side
        jsr     spec_entry
        jsr     is_player
        beq     @use
        ; monsters open the manual doors that are not secret
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_SECRET
        bne     @false
        lda     us_special
        cmp     #1
        beq     @use
        cmp     #32
        bcc     @false
        cmp     #35
        bcs     @false
@use:   lda     e_trig
        and     #TR_KIND
        cmp     #TR_D
        bne     @switch
        jsr     ev_vertical_door
        bra     @true
@switch:
        cmp     #TR_S
        bne     @true
        jsr     run_kept
        tax
        bne     @change
        lda     e_trig
        and     #TR_ALWAYS
        beq     @true
@change:
        lda     ev_line
        sta     cs_line
        lda     ev_line+1
        sta     cs_line+1
        lda     e_trig
        and     #TR_REPEAT
        jsr     change_switch
@true:  lda     #1
        ldx     #0
        rts
@false: lda     #0
        tax
        rts

ML_SECRET   = 32

; ---- sectors -------------------------------------------------------------------------------
; A/X = sector -> ptr1 = 2 * sector
twice:  asl     a
        sta     ptr1
        txa
        rol     a
        sta     ptr1+1
        rts

; A/X = sector -> A/X = its floor (ceiling) height
floor_of:
        jsr     twice
        clc
        lda     ptr1
        adc     _sec_floorh
        sta     ptr1
        lda     ptr1+1
        adc     _sec_floorh+1
        bra     rd16
ceil_of:
        jsr     twice
        clc
        lda     ptr1
        adc     _sec_ceilh
        sta     ptr1
        lda     ptr1+1
        adc     _sec_ceilh+1
rd16:   sta     ptr1+1
        ldy     #1
        lda     (ptr1),y
        tax
        lda     (ptr1)
        rts

; A/X = sector -> A = its special
special_of:
        clc
        adc     _sec_special
        sta     ptr1
        txa
        adc     _sec_special+1
        sta     ptr1+1
        lda     (ptr1)
        rts

; A = array, lev_idx = index, Y = field offset -> lev_far
lev_field:
        phy
        jsr     lev_addr
        pla
        clc
        adc     lev_far
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       rts

; far_ptr = A/X, far_len = Y
far_to: sta     far_ptr
        stx     far_ptr+1
        sty     far_len
        stz     far_len+1
        rts

; A/X = sector -> lev_far = its record's field Y
sec_field:
        sta     lev_idx
        stx     lev_idx+1
        lda     #MAPARR_SECTORS
        bra     lev_field

; A/X = sector -> A = its light (far record)
sec_light:
        ldy     #SECTOR_LIGHTLEVEL
        jsr     sec_field
        lda     #<tmpb
        ldx     #>tmpb
        ldy     #1
        jsr     far_to
        jsr     far_rd
        lda     tmpb
        rts

; A/X = sector -> A/X = its floor flat (far record)
sec_floorpic:
        ldy     #SECTOR_FLOORPIC
        jsr     sec_field
        lda     #<sc_val
        ldx     #>sc_val
        ldy     #2
        jsr     far_to
        jsr     far_rd
        lda     sc_val
        ldx     sc_val+1
        rts

; the floor flat of sector ev_sec = A/X
set_floorpic:
        sta     sc_val
        stx     sc_val+1
        lda     ev_sec
        ldx     ev_sec+1
        ldy     #SECTOR_FLOORPIC
        jsr     sec_field
        lda     #<sc_val
        ldx     #>sc_val
        ldy     #2
        jsr     far_to
        jmp     far_wr

; S_StartSound(NULL, A): the sectors' sounds have no origin
snd_null:
        pha
        lda     #0
        tax
        jsr     pushax
        pla
        jmp     _S_StartSound

; ---- the busy bits (vanilla sector->specialdata) ------------------------------------------
; A/X = sector -> ptr1 = its byte, tmp1 = its bit
busy_addr:
        pha
        and     #7
        tay
        lda     bitmask,y
        sta     tmp1
        stx     tmp2
        pla
        lsr     tmp2
        ror     a
        lsr     tmp2
        ror     a
        lsr     tmp2
        ror     a
        clc
        adc     _sec_busy
        sta     ptr1
        lda     tmp2
        adc     _sec_busy+1
        sta     ptr1+1
        rts

; Z clear iff busy
is_busy:
        jsr     busy_addr
        lda     (ptr1)
        and     tmp1
        rts

set_busy:
        jsr     busy_addr
        lda     (ptr1)
        ora     tmp1
        sta     (ptr1)
        rts

clr_busy:
        jsr     busy_addr
        lda     tmp1
        eor     #$FF
        and     (ptr1)
        sta     (ptr1)
        rts

; ---- the tagged sectors (vanilla P_FindSectorFromLineTag) -----------------------------------
; tg_tag = ev_line's tag
ev_get_tag:
        lda     ev_line
        ldx     ev_line+1
        jsr     line_get
        ldy     #LI_TAG
        lda     (gli),y
        sta     tg_tag
        sta     ev_tag
        iny
        lda     (gli),y
        sta     tg_tag+1
        sta     ev_tag+1
        rts

tag_first:
        stz     tg_pos
        stz     tg_pos+1
        ; fall through
; the next sector with tg_tag: C clear, ev_sec = A/X = it; C set when done
tag_next:
        lda     tg_pos
        cmp     _tag_count
        lda     tg_pos+1
        sbc     _tag_count+1
        bcs     @done
        lda     tg_pos                  ; ptr1 = tag_list + 4 * pos
        asl     a
        sta     ptr1
        lda     tg_pos+1
        rol     a
        sta     ptr1+1
        asl     ptr1
        rol     ptr1+1
        clc
        lda     ptr1
        adc     _tag_list
        sta     ptr1
        lda     ptr1+1
        adc     _tag_list+1
        sta     ptr1+1
        inc     tg_pos
        bne     :+
        inc     tg_pos+1
:       ldy     #2
        lda     (ptr1),y
        cmp     tg_tag
        bne     tag_next
        iny
        lda     (ptr1),y
        cmp     tg_tag+1
        bne     tag_next
        lda     (ptr1)
        sta     ev_sec
        ldy     #1
        lda     (ptr1),y
        sta     ev_sec+1
        tax
        lda     ev_sec
        clc
        rts
@done:  sec
        rts

; ---- a sector's lines -------------------------------------------------------------------------
; A/X = sector: sl_count, sl_first from its record; the iteration from 0
sl_start:
        ldy     #SECTOR_LINECOUNT
        jsr     sec_field
        lda     #<sl_count
        ldx     #>sl_count
        ldy     #4
        jsr     far_to
        jsr     far_rd
        stz     sl_i
        stz     sl_i+1
        rts

; the next line: C clear, A/X = sl_line = it; C set when done
sl_next:
        lda     sl_i
        cmp     sl_count
        lda     sl_i+1
        sbc     sl_count+1
        bcs     @done
        clc
        lda     sl_first
        adc     sl_i
        sta     lev_idx
        lda     sl_first+1
        adc     sl_i+1
        sta     lev_idx+1
        inc     sl_i
        bne     :+
        inc     sl_i+1
:       lda     #MAPARR_SECLINES
        jsr     lev_addr
        lda     #<sl_line
        ldx     #>sl_line
        ldy     #2
        jsr     far_to
        jsr     far_rd
        lda     sl_line
        ldx     sl_line+1
        clc
        rts
@done:  sec
        rts

; vanilla getNextSector: A/X = line, ns_sec = sector -> A/X = the other
; side's sector, X = $FF if none (one-sided)
next_sector:
        jsr     line_get
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @none
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        cmp     ns_sec
        bne     @front
        iny
        lda     (gli),y
        cmp     ns_sec+1
        bne     @front
        ldy     #LI_BACKSECTOR+1
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        rts
@front: ldy     #LI_FRONTSECTOR+1
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        rts
@none:  lda     #$FF
        tax
        rts

; ---- the neighbour searches (vanilla P_Find*Surrounding, P_FindNextHighestFloor,
; P_FindMinSurroundingLight, EV_LightTurnOn's search) ----------------------------------------
; A = NB_ kind, nb_sec = sector, nb_h = the start (a light: its low byte,
; high byte 0), nb_ref = the height NB_NEXTFLOOR looks above -> A/X = nb_h
nb_find:
        sta     nb_kind
        lda     nb_sec
        sta     ns_sec
        ldx     nb_sec+1
        stx     ns_sec+1
        jsr     sl_start
@loop:  jsr     sl_next
        jcs     @done
        jsr     next_sector
        cpx     #$FF
        beq     @loop
        sta     nb_o
        stx     nb_o+1
        lda     nb_kind
        cmp     #NB_MINLIGHT
        jcs     @light
        cmp     #NB_LOWCEIL
        lda     nb_o
        ldx     nb_o+1
        bcs     @ceil
        jsr     floor_of
        bra     @have
@ceil:  jsr     ceil_of
@have:  sta     nb_v
        stx     nb_v+1
        lda     nb_kind
        beq     @low
        cmp     #NB_LOWCEIL
        beq     @low
        cmp     #NB_NEXTFLOOR
        beq     @next
        slt16   nb_h, nb_v              ; highest: h < v -> h = v
        bpl     @loop
@set:   lda     nb_v
        sta     nb_h
        lda     nb_v+1
        sta     nb_h+1
        jmp     @loop
@low:   slt16   nb_v, nb_h              ; lowest: v < h -> h = v
        bpl     @loop
        jmp     @set
@next:  slt16   nb_ref, nb_v            ; above the height: ref < v
        jpl     @loop
        lda     nb_h                    ; none yet (h == ref), or lower than h
        cmp     nb_ref
        bne     @nx2
        lda     nb_h+1
        cmp     nb_ref+1
        beq     @set
@nx2:   slt16   nb_v, nb_h
        jpl     @loop
        jmp     @set
@light: lda     nb_o
        ldx     nb_o+1
        jsr     sec_light
        ldx     nb_kind
        cpx     #NB_MINLIGHT
        bne     @max
        cmp     nb_h
        jcs     @loop
        sta     nb_h
        jmp     @loop
@max:   cmp     nb_h
        jcc     @loop
        jeq     @loop
        sta     nb_h
        jmp     @loop
@done:  lda     nb_h
        ldx     nb_h+1
        rts

; vanilla P_FindMinSurroundingLight(ev_sec, A)
min_light:
        sta     nb_h
        stz     nb_h+1
        lda     ev_sec
        sta     nb_sec
        lda     ev_sec+1
        sta     nb_sec+1
        lda     #NB_MINLIGHT
        jmp     nb_find

; ---- movers -----------------------------------------------------------------------------------
; a zeroed thinker block, in the list, with the function nm_func, for the
; sector ev_sec (made busy) -> mv, gpt
new_mover:
        lda     #THINKER_BLOCK
        jsr     _P_AllocThinker
        sta     mv
        stx     mv+1
        jsr     _P_AddThinker
        ldmv
        ldy     #TH_FUNCTION
        lda     nm_func
        sta     (gpt),y
        iny
        lda     nm_func+1
        sta     (gpt),y
        ldy     #MV_SECTOR
        lda     ev_sec
        sta     (gpt),y
        iny
        lda     ev_sec+1
        sta     (gpt),y
        lda     ev_sec
        ldx     ev_sec+1
        jsr     set_busy
        ldmv
        rts

; the mover mv: its sector free, its thinker removed (freed at the next run)
remove_mover:
        ldmv
        ldy     #MV_SECTOR+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        jsr     clr_busy
        lda     mv
        ldx     mv+1
        jmp     _P_RemoveThinker

; the thinker with function fm_func on sector fm_sec: C clear, A/X = gpt =
; it; C set if none
find_mover:
        lda     _thinkercap+TH_NEXT
        ldx     _thinkercap+TH_NEXT+1
@loop:  sta     gpt
        stx     gpt+1
        cmp     #<_thinkercap
        bne     @chk
        cpx     #>_thinkercap
        beq     @none
@chk:   ldy     #TH_FUNCTION
        lda     (gpt),y
        cmp     fm_func
        bne     @nx
        iny
        lda     (gpt),y
        cmp     fm_func+1
        bne     @nx
        ldy     #MV_SECTOR
        lda     (gpt),y
        cmp     fm_sec
        bne     @nx
        iny
        lda     (gpt),y
        cmp     fm_sec+1
        bne     @nx
        lda     gpt
        ldx     gpt+1
        clc
        rts
@nx:    ldy     #TH_NEXT+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        bra     @loop
@none:  sec
        rts

; ---- T_MovePlane --------------------------------------------------------------------------------
; The mover mv's floor (mp_ceil 0) or ceiling (1) one tic toward mp_dest,
; direction mp_dir (1 up, $FF down), crushing if mp_crush -> A = RES_*.
; The speed is in eighths: the plane moves by the whole units owed (acc
; keeps the rest); on a tic that owes none it does not move, and only a
; crusher asks P_ChangeSector. mv is kept across P_ChangeSector.
move_plane:
        lda     mv
        pha
        lda     mv+1
        pha
        jsr     mp_body
        tax
        pla
        sta     mv+1
        pla
        sta     mv
        txa
        rts

mp_body:
        ldmv
        ldy     #MV_SECTOR
        lda     (gpt),y
        sta     mp_sec
        iny
        lda     (gpt),y
        sta     mp_sec+1
        ldy     #MV_ACC                 ; step = acc + speed, in eighths
        lda     (gpt),y
        ldy     #MV_SPEED
        clc
        adc     (gpt),y
        pha
        and     #7
        ldy     #MV_ACC
        sta     (gpt),y
        pla
        lsr     a
        lsr     a
        lsr     a
        sta     mp_step
        lda     mp_sec
        ldx     mp_sec+1
        ldy     mp_ceil
        bne     :+
        jsr     floor_of
        bra     :++
:       jsr     ceil_of
:       sta     mp_last
        stx     mp_last+1
        cmp     mp_dest                 ; there already: past it
        bne     :+
        cpx     mp_dest+1
        beq     @past
:       lda     mp_dir
        bmi     @down
        clc
        lda     mp_last
        adc     mp_step
        sta     mp_now
        lda     mp_last+1
        adc     #0
        sta     mp_now+1
        slt16   mp_dest, mp_now         ; last + step > dest
        bmi     @past
        bra     @step
@down:  sec
        lda     mp_last
        sbc     mp_step
        sta     mp_now
        lda     mp_last+1
        sbc     #0
        sta     mp_now+1
        slt16   mp_now, mp_dest         ; last - step < dest
        bmi     @past
@step:  lda     mp_step
        bne     @move
        lda     mp_crush
        beq     :+
        jsr     mp_change               ; a crusher: its things still feel it
:       lda     #RES_OK
        rts
@move:  lda     #RES_OK
        bra     @set
@past:  lda     mp_dest
        sta     mp_now
        lda     mp_dest+1
        sta     mp_now+1
        lda     #RES_PASTDEST
@set:   sta     mp_res
        jsr     mp_setnow
        jsr     mp_change
        bne     @nofit
        lda     mp_res
        rts
@nofit: lda     mp_res
        bne     @back                   ; past: back, and pastdest
        ; on the way: a rising ceiling goes on; a crusher crushes on
        ; (floor up, ceiling down); the rest go back
        lda     mp_ceil
        beq     @floor
        lda     mp_dir
        bpl     @ok
        lda     mp_crush
        bne     @crushed
        bra     @back1
@floor: lda     mp_dir
        bmi     @back1
        lda     mp_crush
        bne     @crushed
@back1: lda     #RES_CRUSHED
        sta     mp_res
@back:  lda     mp_last
        sta     mp_now
        lda     mp_last+1
        sta     mp_now+1
        jsr     mp_setnow
        jsr     mp_change
        lda     mp_res
        rts
@crushed:
        lda     #RES_CRUSHED
        rts
@ok:    lda     #RES_OK
        rts

; the plane's height = mp_now (P_SetSectorFloor/Ceiling: near and far)
mp_setnow:
        lda     mp_sec
        ldx     mp_sec+1
        jsr     pushax
        lda     mp_now
        ldx     mp_now+1
        ldy     mp_ceil
        bne     :+
        jmp     _P_SetSectorFloor
:       jmp     _P_SetSectorCeiling

; P_ChangeSector(mp_sec, mp_crush) -> A, Z set iff everything fits
mp_change:
        lda     mp_sec
        ldx     mp_sec+1
        jsr     pushax
        lda     mp_crush
        jsr     _P_ChangeSector
        cmp     #0
        rts

; ---- the player on a special sector (vanilla P_PlayerInSpecialSector) --------------------------
_P_PlayerInSpecialSector:
        lda     _player+PL_MO
        sta     gpt
        lda     _player+PL_MO+1
        sta     gpt+1
        ldy     #MO_SECTOR
        lda     (gpt),y
        sta     ps_sec
        iny
        lda     (gpt),y
        sta     ps_sec+1
        tax
        lda     ps_sec
        jsr     floor_of
        sta     tmp3
        stx     tmp4
        ldy     #MO_Z                   ; on the floor: z == FIX(floor)
        lda     (gpt),y
        iny
        ora     (gpt),y
        bne     @out
        iny
        lda     (gpt),y
        cmp     tmp3
        bne     @out
        iny
        lda     (gpt),y
        cmp     tmp4
        bne     @out
        lda     ps_sec
        ldx     ps_sec+1
        jsr     special_of
        cmp     #5
        beq     @slime
        cmp     #7
        beq     @nukage
        cmp     #16
        beq     @super
        cmp     #4
        beq     @super
        cmp     #9
        beq     @secret
        cmp     #11
        beq     @exit
@out:   rts
@slime: lda     #10
        bra     @suit
@nukage:
        lda     #5
@suit:  tax
        lda     _player+PL_POWERS+2*pw_ironfeet
        ora     _player+PL_POWERS+2*pw_ironfeet+1
        bne     @out
        txa
        bra     @hurt
@super: lda     _player+PL_POWERS+2*pw_ironfeet
        ora     _player+PL_POWERS+2*pw_ironfeet+1
        beq     @s20
        jsr     _P_Random               ; with the suit: 5 in 256
        cmp     #5
        bcs     @out
@s20:   lda     #20
@hurt:  tax
        lda     _leveltime
        and     #$1F
        bne     @out
        txa
        jmp     damage_player
@secret:
        inc     _player+PL_SECRETCOUNT
        bne     :+
        inc     _player+PL_SECRETCOUNT+1
:       lda     ps_sec
        ldx     ps_sec+1
        jsr     pushax
        lda     #0
        jmp     _P_SetSectorSpecial
@exit:  lda     _player+PL_CHEATS       ; E1M8's end: no god mode, 20 a hit, out at 10
        and     #<~CF_GODMODE
        sta     _player+PL_CHEATS
        lda     _leveltime
        and     #$1F
        bne     :+
        lda     #20
        jsr     damage_player
:       lda     _player+PL_HEALTH       ; health <= 10: health < 11
        cmp     #11
        lda     _player+PL_HEALTH+1
        sbc     #0
        bvc     :+
        eor     #$80
:       bpl     @out
        jmp     _G_ExitLevel

; P_DamageMobj(player.mo, NULL, NULL, A)
damage_player:
        pha
        lda     _player+PL_MO
        ldx     _player+PL_MO+1
        jsr     pushax
        lda     #0
        tax
        jsr     pushax
        jsr     pushax
        pla
        ldx     #0
        jmp     _P_DamageMobj

; ---- the tic: P_UpdateSpecials ----------------------------------------------------------------------
_P_UpdateSpecials:
        jsr     run_lights
        jsr     run_buttons
        ; scrolling walls: one unit a tic, from the offset they started at
        stz     sc_i
@loop:  lda     sc_i
        cmp     _scroll_count
        bcs     @out
        asl     a                       ; ptr1 = scroll_list + 4 * i
        asl     a
        clc
        adc     _scroll_list
        sta     ptr1
        lda     _scroll_list+1
        adc     #0
        sta     ptr1+1
        ldy     #2                      ; x = start + leveltime + 1
        lda     (ptr1),y
        sec
        adc     _leveltime
        sta     sc_val
        iny
        lda     (ptr1),y
        adc     _leveltime+1
        sta     sc_val+1
        lda     (ptr1)
        sta     lev_idx
        ldy     #1
        lda     (ptr1),y
        sta     lev_idx+1
        lda     #MAPARR_SIDEDEFS
        ldy     #SIDEDEF_XOFFSET
        jsr     lev_field
        lda     #<sc_val
        ldx     #>sc_val
        ldy     #2
        jsr     far_to
        jsr     far_wr
        inc     sc_i
        bra     @loop
@out:   rts

; ---- lights (p_lights.c) --------------------------------------------------------------------------
lt_reload:
        lda     lt_ptr
        sta     gpt
        lda     lt_ptr+1
        sta     gpt+1
        rts

run_lights:
        lda     _lights
        sta     lt_ptr
        lda     _lights+1
        sta     lt_ptr+1
        lda     _numlights
        sta     lt_n
        bne     @loop
        rts
@loop:  jsr     lt_reload
        ldy     #LT_KIND
        lda     (gpt),y
        cmp     #LT_GLOW
        bne     @counted
        ldy     #LT_CUR                 ; glow: 8 a tic between min and max
        lda     (gpt),y
        sta     lv
        stz     lv+1
        ldy     #LT_AUX
        lda     (gpt),y
        beq     @gdown
        clc                             ; up: v += 8; at max, back and turn
        lda     lv
        adc     #GLOWSPEED
        sta     lv
        bcs     @gturn                  ; (>= 256 > max)
        ldy     #LT_MAX
        cmp     (gpt),y
        jcc     @apply
@gturn: lda     lv
        sec
        sbc     #GLOWSPEED
        sta     lv
        lda     #0
        ldy     #LT_AUX
        sta     (gpt),y
        jmp     @apply
@gdown: sec                             ; down: v -= 8; at min, back and turn
        lda     lv
        sbc     #GLOWSPEED
        sta     lv
        bcc     @gdturn                 ; (< 0 <= min)
        ldy     #LT_MIN
        lda     (gpt),y
        cmp     lv
        jcc     @apply                  ; min < v
@gdturn:
        clc
        lda     lv
        adc     #GLOWSPEED
        sta     lv
        lda     #1
        ldy     #LT_AUX
        sta     (gpt),y
        jmp     @apply
@counted:
        ldy     #LT_COUNT
        lda     (gpt),y
        dec     a
        sta     (gpt),y
        jne     @next
        ldy     #LT_KIND
        lda     (gpt),y
        cmp     #LT_FLASH
        beq     @flash
        cmp     #LT_STROBE
        beq     @strobe
        ; fire flicker: amount 0-48; cur - amount < min: min, else max - amount
        jsr     _P_Random
        and     #3
        asl     a
        asl     a
        asl     a
        asl     a
        sta     lamt
        jsr     lt_reload
        ldy     #LT_CUR
        lda     (gpt),y
        sec
        sbc     lamt
        bcc     @fmin
        ldy     #LT_MIN
        cmp     (gpt),y
        bcc     @fmin
        ldy     #LT_MAX
        lda     (gpt),y
        sec
        sbc     lamt
        bra     @fset
@fmin:  ldy     #LT_MIN
        lda     (gpt),y
@fset:  sta     lv
        lda     #4
        ldy     #LT_COUNT
        sta     (gpt),y
        jmp     @apply
@flash: ldy     #LT_CUR                 ; flash: dark 1-8 tics, bright 1 or 65
        lda     (gpt),y
        ldy     #LT_MAX
        cmp     (gpt),y
        bne     @flup
        ldy     #LT_MIN
        lda     (gpt),y
        sta     lv
        jsr     _P_Random
        and     #7
        bra     @flcnt
@flup:  lda     (gpt),y
        sta     lv
        jsr     _P_Random
        and     #64
@flcnt: inc     a
        pha
        jsr     lt_reload
        pla
        ldy     #LT_COUNT
        sta     (gpt),y
        jmp     @apply
@strobe:
        ldy     #LT_CUR
        lda     (gpt),y
        ldy     #LT_MIN
        cmp     (gpt),y
        bne     @stdn
        ldy     #LT_MAX
        lda     (gpt),y
        sta     lv
        lda     #STROBEBRIGHT
        bra     @stcnt
@stdn:  lda     (gpt),y                 ; (Y = LT_MIN)
        sta     lv
        ldy     #LT_AUX
        lda     (gpt),y
@stcnt: ldy     #LT_COUNT
        sta     (gpt),y
@apply: ldy     #LT_CUR                 ; a new level: the record and the far sector
        lda     lv
        cmp     (gpt),y
        beq     @next
        sta     (gpt),y
        ldy     #LT_SECTOR+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        jsr     pushax
        lda     lv
        jsr     _P_SetSectorLight
@next:  clc
        lda     lt_ptr
        adc     #LT_SIZE
        sta     lt_ptr
        bcc     :+
        inc     lt_ptr+1
:       dec     lt_n
        jne     @loop
        rts

; a new light of kind A for sector ev_sec: C clear, gpt = lt_new = it
; (cur, max = its light, min = its darkest neighbour's, its special off);
; C set if the list is full
new_light:
        sta     nl_kind
        lda     _numlights
        cmp     _maxlights
        bcs     @full
        stz     tmp2                    ; lt_new = lights + 8 * numlights
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        clc
        adc     _lights
        sta     lt_new
        lda     tmp2
        adc     _lights+1
        sta     lt_new+1
        inc     _numlights
        jsr     nl_reload
        ldy     #LT_SECTOR
        lda     ev_sec
        sta     (gpt),y
        iny
        lda     ev_sec+1
        sta     (gpt),y
        ldy     #LT_KIND
        lda     nl_kind
        sta     (gpt),y
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sec_light
        pha
        jsr     nl_reload
        pla
        ldy     #LT_CUR
        sta     (gpt),y
        ldy     #LT_MAX
        sta     (gpt),y
        jsr     min_light
        pha
        jsr     nl_reload
        pla
        ldy     #LT_MIN
        sta     (gpt),y
        lda     ev_sec
        ldx     ev_sec+1
        jsr     pushax
        lda     #0
        jsr     _P_SetSectorSpecial
        jsr     nl_reload
        clc
        rts
@full:  sec
        rts

nl_reload:
        lda     lt_new
        sta     gpt
        lda     lt_new+1
        sta     gpt+1
        rts

; vanilla P_SpawnStrobeFlash(ev_sec, A = darktime, X = in sync)
spawn_strobe:
        sta     ss_dark
        stx     ss_sync
        lda     #LT_STROBE
        jsr     new_light
        bcs     @out
        ldy     #LT_AUX
        lda     ss_dark
        sta     (gpt),y
        ldy     #LT_MIN
        lda     (gpt),y
        ldy     #LT_MAX
        cmp     (gpt),y
        bne     :+
        lda     #0
        ldy     #LT_MIN
        sta     (gpt),y
:       lda     #1
        ldx     ss_sync
        bne     :+
        jsr     _P_Random
        and     #7
        inc     a
:       pha
        jsr     nl_reload
        pla
        ldy     #LT_COUNT
        sta     (gpt),y
@out:   rts

; ---- void P_SpawnSectorSpecial(uint16_t sector, uint8_t special) -----------------------------
; the level set-up's lights, and the doors of sector specials 10 and 14
_P_SpawnSectorSpecial:
        sta     ss_spec
        jsr     popax
        sta     ev_sec
        stx     ev_sec+1
        lda     ss_spec
        cmp     #10
        bne     :+
        jmp     door_close30
:       cmp     #14
        bne     :+
        jmp     door_raise5
:       cmp     #1
        beq     @flash
        cmp     #2
        beq     @fast
        cmp     #3
        beq     @slow
        cmp     #4
        beq     @hurt
        cmp     #8
        beq     @glow
        cmp     #12
        beq     @slowsync
        cmp     #13
        beq     @fastsync
        cmp     #17
        beq     @fire
        rts
@flash: lda     #LT_FLASH
        jsr     new_light
        bcs     @out
        jsr     _P_Random
        and     #64
        inc     a
        pha
        jsr     nl_reload
        pla
        ldy     #LT_COUNT
        sta     (gpt),y
@out:   rts
@fast:  lda     #FASTDARK
        ldx     #0
        jmp     spawn_strobe
@slow:  lda     #SLOWDARK
        ldx     #0
        jmp     spawn_strobe
@hurt:  lda     #FASTDARK               ; a strobe, and the floor hurts
        ldx     #0
        jsr     spawn_strobe
        lda     ev_sec
        ldx     ev_sec+1
        jsr     pushax
        lda     #4
        jmp     _P_SetSectorSpecial
@glow:  lda     #LT_GLOW
        jmp     new_light
@slowsync:
        lda     #SLOWDARK
        ldx     #1
        jmp     spawn_strobe
@fastsync:
        lda     #FASTDARK
        ldx     #1
        jmp     spawn_strobe
@fire:  lda     #LT_FIRE
        jsr     new_light
        bcs     @out
        ldy     #LT_MIN
        lda     (gpt),y
        clc
        adc     #16
        sta     (gpt),y
        ldy     #LT_COUNT
        lda     #4
        sta     (gpt),y
        rts

; the light of sector sl_s = A: the far record, and the list's copies
set_light:
        sta     sl_v
        lda     sl_s
        ldx     sl_s+1
        jsr     pushax
        lda     sl_v
        jsr     _P_SetSectorLight
        lda     _lights
        sta     gpt
        lda     _lights+1
        sta     gpt+1
        ldx     _numlights
        beq     @out
@loop:  lda     (gpt)
        cmp     sl_s
        bne     @nx
        ldy     #1
        lda     (gpt),y
        cmp     sl_s+1
        bne     @nx
        ldy     #LT_CUR
        lda     sl_v
        sta     (gpt),y
@nx:    clc
        lda     gpt
        adc     #LT_SIZE
        sta     gpt
        bcc     :+
        inc     gpt+1
:       dex
        bne     @loop
@out:   rts

; vanilla EV_StartLightStrobing: the tagged sectors not moving strobe slowly
ev_start_strobing:
        jsr     ev_get_tag
        jsr     tag_first
@loop:  bcs     @out
        jsr     is_busy
        bne     :+
        lda     #SLOWDARK
        ldx     #0
        jsr     spawn_strobe
:       jsr     tag_next
        bra     @loop
@out:   rts

; vanilla EV_TurnTagLightsOff: each tagged sector to its darkest neighbour's
ev_lights_off:
        jsr     ev_get_tag
        jsr     tag_first
@loop:  bcs     @out
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sec_light
        jsr     min_light
        pha
        lda     ev_sec
        sta     sl_s
        lda     ev_sec+1
        sta     sl_s+1
        pla
        jsr     set_light
        jsr     tag_next
        bra     @loop
@out:   rts

; vanilla EV_LightTurnOn(A = bright): 0 is the brightest neighbour's, and
; the level found for the first sector is kept for the others (vanilla's)
ev_light_on:
        sta     lo_bright
        jsr     ev_get_tag
        jsr     tag_first
@loop:  bcs     @out
        lda     lo_bright
        bne     @set
        stz     nb_h
        stz     nb_h+1
        lda     ev_sec
        sta     nb_sec
        lda     ev_sec+1
        sta     nb_sec+1
        lda     #NB_MAXLIGHT
        jsr     nb_find
        sta     lo_bright
@set:   lda     ev_sec
        sta     sl_s
        lda     ev_sec+1
        sta     sl_s+1
        lda     lo_bright
        jsr     set_light
        jsr     tag_next
        bra     @loop
@out:   rts

; ---- switches (p_switch.c) ---------------------------------------------------------------------------
; vanilla P_ChangeSwitchTexture(cs_line, A = useAgain)
change_switch:
        sta     cs_again
        bne     :+
        lda     cs_line
        ldx     cs_line+1
        jsr     clear_line_special
:       lda     cs_line                 ; the front sidedef
        sta     lev_idx
        lda     cs_line+1
        sta     lev_idx+1
        lda     #MAPARR_LINEDEFS
        ldy     #LINEDEF_SIDE0
        jsr     lev_field
        lda     #<cs_side
        ldx     #>cs_side
        ldy     #2
        jsr     far_to
        jsr     far_rd
        lda     cs_side                 ; its record, its textures
        sta     lev_idx
        lda     cs_side+1
        sta     lev_idx+1
        lda     #MAPARR_SIDEDEFS
        ldy     #0
        jsr     lev_field
        lda     lev_far
        sta     cs_rec
        lda     lev_far+1
        sta     cs_rec+1
        lda     lev_far+2
        sta     cs_rec+2
        lda     #SIDEDEF_TOPTEXTURE
        jsr     cs_at
        lda     #<cs_tex
        ldx     #>cs_tex
        ldy     #6
        jsr     far_to
        jsr     far_rd
        stz     cs_i
@loop:  ldx     cs_i                    ; top, middle, bottom
        lda     where_tab,x
        sta     cs_where
        sec
        sbc     #SIDEDEF_TOPTEXTURE
        tax
        lda     cs_tex,x
        sta     cs_other
        ora     cs_tex+1,x
        beq     @next
        lda     cs_tex+1,x
        sta     cs_other+1
        ; its partner: TEX record + TEX_SWITCHTEX (16 * texture)
        ldx     #4
:       asl     cs_other
        rol     cs_other+1
        dex
        bne     :-
        clc
        lda     cs_other
        adc     #<(DD_TEXDIR + TEX_SWITCHTEX)
        sta     far_src
        lda     cs_other+1
        adc     #>(DD_TEXDIR + TEX_SWITCHTEX)
        sta     far_src+1
        lda     #DD_DIR_BANK
        sta     far_src+2
        lda     #<cs_other
        ldx     #>cs_other
        ldy     #2
        jsr     far_to
        jsr     kjt_far_read
        lda     cs_other
        ora     cs_other+1
        bne     @found
@next:  inc     cs_i
        lda     cs_i
        cmp     #3
        bne     @loop
        rts
@found: lda     #sfx_swtchn             ; (vanilla's exit sound never plays)
        jsr     snd_null
        lda     cs_where
        jsr     cs_at
        lda     cs_again
        beq     @once
        jsr     start_button
        bra     @write
@once:  lda     #2
        jsr     journal
@write: lda     cs_where
        jsr     cs_at
        lda     #<cs_other
        ldx     #>cs_other
        ldy     #2
        jsr     far_to
        jmp     far_wr

; lev_far = the sidedef record + A
cs_at:  clc
        adc     cs_rec
        sta     lev_far
        lda     cs_rec+1
        adc     #0
        sta     lev_far+1
        lda     cs_rec+2
        sta     lev_far+2
        rts

; vanilla P_StartButton: cs_line's button at cs_where, the texture it had
start_button:
        ldx     #0
@same:  lda     bt_timer,x              ; already pressed?
        beq     :+
        lda     bt_line_lo,x
        cmp     cs_line
        bne     :+
        lda     bt_line_hi,x
        cmp     cs_line+1
        beq     @out
:       inx
        cpx     #MAXBUTTONS
        bne     @same
        ldx     #0
@free:  lda     bt_timer,x
        beq     @take
        inx
        cpx     #MAXBUTTONS
        bne     @free
@out:   rts                             ; (vanilla: I_Error, no slot left)
@take:  lda     cs_line
        sta     bt_line_lo,x
        lda     cs_line+1
        sta     bt_line_hi,x
        lda     cs_side
        sta     bt_side_lo,x
        lda     cs_side+1
        sta     bt_side_hi,x
        lda     cs_where
        sta     bt_where,x
        ldy     cs_where
        lda     cs_tex-SIDEDEF_TOPTEXTURE,y
        sta     bt_tex_lo,x
        lda     cs_tex-SIDEDEF_TOPTEXTURE+1,y
        sta     bt_tex_hi,x
        lda     #BUTTONTIME
        sta     bt_timer,x
        inc     buttons_on
        rts

; button X's texture back in its sidedef
bt_restore:
        lda     bt_side_lo,x
        sta     lev_idx
        lda     bt_side_hi,x
        sta     lev_idx+1
        lda     bt_tex_lo,x
        sta     sc_val
        lda     bt_tex_hi,x
        sta     sc_val+1
        ldy     bt_where,x
        lda     #MAPARR_SIDEDEFS
        jsr     lev_field
        lda     #<sc_val
        ldx     #>sc_val
        ldy     #2
        jsr     far_to
        jmp     far_wr

run_buttons:
        lda     buttons_on
        beq     @out
        ldx     #0
@loop:  lda     bt_timer,x
        beq     @next
        dec     a
        sta     bt_timer,x
        bne     @next
        phx
        jsr     bt_restore
        lda     #sfx_swtchn
        jsr     snd_null
        dec     buttons_on
        plx
@next:  inx
        cpx     #MAXBUTTONS
        bne     @loop
@out:   rts

; ---- void P_ResetButtons(boolean up) ---------------------------------------------------------------
_P_ResetButtons:
        sta     rb_up
        ldx     #0
@loop:  lda     bt_timer,x
        beq     @next
        lda     rb_up
        beq     @free
        phx
        jsr     bt_restore
        plx
@free:  stz     bt_timer,x
@next:  inx
        cpx     #MAXBUTTONS
        bne     @loop
        stz     buttons_on
        rts

; ---- the journal (p_spec.c P_JournalBytes, P_ClearLineSpecial) ----------------------------------------
; before a lasting change of A (1 or 2) bytes at lev_far: an entry (the
; address, the length, the bytes) at JOURNAL_BASE + 6 * jcount in the
; specials' bank (kbanks - 2). lev_far is kept.
journal:
        sta     jn_e+3
        lda     _jcount
        cmp     #<JOURNAL_MAX
        lda     _jcount+1
        sbc     #>JOURNAL_MAX
        bcs     @out                    ; full: the change stays after a restart
        lda     lev_far
        sta     jn_e
        lda     lev_far+1
        sta     jn_e+1
        lda     lev_far+2
        sta     jn_e+2
        lda     #<(jn_e+4)
        ldx     #>(jn_e+4)
        ldy     jn_e+3
        jsr     far_to
        jsr     far_rd
        lda     _jcount                 ; far_dst = JOURNAL_BASE + 6 * jcount
        asl     a
        sta     tmp1
        lda     _jcount+1
        rol     a
        sta     tmp2                    ; 2j
        lda     tmp1
        asl     a
        sta     far_dst
        lda     tmp2
        rol     a
        sta     far_dst+1               ; 4j
        clc
        lda     far_dst
        adc     tmp1
        sta     far_dst
        lda     far_dst+1
        adc     tmp2
        sta     far_dst+1               ; 6j
        clc
        lda     far_dst
        adc     #<JOURNAL_BASE
        sta     far_dst
        lda     far_dst+1
        adc     #>JOURNAL_BASE
        sta     far_dst+1
        lda     _kbanks
        sec
        sbc     #2
        sta     far_dst+2
        lda     #<jn_e
        ldx     #>jn_e
        ldy     #6
        jsr     far_to
        jsr     kjt_far_write
        inc     _jcount
        bne     @out
        inc     _jcount+1
@out:   rts

; a W1/S1/G1 line (A/X) is used up: its special journalled, then 0
clear_line_special:
        sta     cl_line
        stx     cl_line+1
        sta     lev_idx
        stx     lev_idx+1
        lda     #MAPARR_LINEDEFS
        ldy     #LINEDEF_SPECIAL
        jsr     lev_field
        lda     #1
        jsr     journal
        lda     cl_line
        ldx     cl_line+1
        jsr     pushax
        lda     #0
        jmp     _P_SetLineSpecial

; ==== the level set-up and its undoing (p_spec.c's last part) ===================================
; In the set-up overlay (GOVL, p_setup.c) on the Apple: called only while
; a level loads, its bytes are actor slots afterwards. The py65 harness
; runs it from its code window instead (it has no room to grow GOVL).
.segment "BSS"
; the snapshots: where each map's SECTORS array is kept (bank 0: not yet)
SNAP_MAPS   = 9
SNAP_BASE   = $0A00
SNAP_END    = $C000
snap_bank:  .res SNAP_MAPS
snap_lo:    .res SNAP_MAPS
snap_hi:    .res SNAP_MAPS
snap_nextbank: .res 1
snap_next:  .res 2
su_n:       .res 2
su_count:   .res 1
su_tag:     .res 2
su_bank:    .res 1
su_desc:    .res DESC_SIZE
su_per:     .res 2
su_chunk:   .res 1
su_addr:    .res 2
su_len:     .res 2
su_to:      .res 1
su_map:     .res 1
su_dst:     .res 2

.ifdef MCODE_WINDOW
        .segment "MCODE2"
.else
        .segment "GOVL"
.endif

; A/X = P_ArenaAlloc(A/X)
arena:  jmp     _P_ArenaAlloc

; su_tag = the tag of sector su_n (its far record)
su_sector_tag:
        lda     su_n
        ldx     su_n+1
        ldy     #SECTOR_TAG
        jsr     sec_field
        lda     #<su_tag
        ldx     #>su_tag
        ldy     #2
        jsr     far_to
        jmp     far_rd

; su_n++, C set when it reaches numsectors (numlines: su_lim)
su_next_sector:
        inc     su_n
        bne     :+
        inc     su_n+1
:       lda     su_n
        cmp     _numsectors
        lda     su_n+1
        sbc     _numsectors+1
        rts

; ---- void P_SpawnSpecials(void) ----------------------------------------------------------------
_P_SpawnSpecials:
        ; the busy bits
        lda     _numsectors
        ldx     _numsectors+1
        clc
        adc     #7
        bcc     :+
        inx
:       stx     tmp1
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        ldx     tmp1
        jsr     arena
        sta     _sec_busy
        stx     _sec_busy+1
        ; count the tagged sectors and the lights
        stz     _tag_count
        stz     _tag_count+1
        stz     su_count
        stz     su_n
        stz     su_n+1
        lda     _numsectors
        ora     _numsectors+1
        beq     @alloc
@count: jsr     su_sector_tag
        lda     su_tag
        ora     su_tag+1
        beq     :+
        inc     _tag_count
        bne     :+
        inc     _tag_count+1
:       lda     su_n
        ldx     su_n+1
        jsr     special_of
        jsr     is_light
        bcc     :+
        inc     su_count
:       jsr     su_next_sector
        bcc     @count
@alloc: lda     _tag_count              ; tag_list: 4 bytes a sector
        ldx     _tag_count+1
        stx     tmp1
        asl     a
        rol     tmp1
        asl     a
        rol     tmp1
        ldx     tmp1
        jsr     arena
        sta     _tag_list
        stx     _tag_list+1
        lda     su_count                ; the lights, and the spare ones
        clc
        adc     #SPARE_LIGHTS
        sta     _maxlights
        stz     tmp1
        asl     a
        rol     tmp1
        asl     a
        rol     tmp1
        asl     a
        rol     tmp1
        ldx     tmp1
        jsr     arena
        sta     _lights
        stx     _lights+1
        stz     _numlights
        ; the tag list, the secrets, the lights and doors
        stz     _tag_count
        stz     _tag_count+1
        stz     su_n
        stz     su_n+1
        lda     _numsectors
        ora     _numsectors+1
        jeq     @scroll
@fill:  jsr     su_sector_tag
        lda     su_tag
        ora     su_tag+1
        beq     @special
        lda     _tag_count              ; ptr1 = tag_list + 4 * tag_count
        asl     a
        sta     ptr1
        lda     _tag_count+1
        rol     a
        sta     ptr1+1
        asl     ptr1
        rol     ptr1+1
        clc
        lda     ptr1
        adc     _tag_list
        sta     ptr1
        lda     ptr1+1
        adc     _tag_list+1
        sta     ptr1+1
        lda     su_n
        sta     (ptr1)
        ldy     #1
        lda     su_n+1
        sta     (ptr1),y
        iny
        lda     su_tag
        sta     (ptr1),y
        iny
        lda     su_tag+1
        sta     (ptr1),y
        inc     _tag_count
        bne     @special
        inc     _tag_count+1
@special:
        lda     su_n
        ldx     su_n+1
        jsr     special_of
        beq     @nextsec
        cmp     #9
        bne     @spawn
        inc     _totalsecret
        bne     @nextsec
        inc     _totalsecret+1
        bra     @nextsec
@spawn: pha
        lda     su_n
        ldx     su_n+1
        jsr     pushax
        pla
        jsr     _P_SpawnSectorSpecial
@nextsec:
        jsr     su_next_sector
        jcc     @fill
        ; the scrolling walls: lines of special 48 (one far byte a line)
@scroll:
        lda     #<(MAXSCROLLERS * 4)
        ldx     #>(MAXSCROLLERS * 4)
        jsr     arena
        sta     _scroll_list
        stx     _scroll_list+1
        stz     _scroll_count
        stz     su_n
        stz     su_n+1
@lines: lda     su_n
        cmp     _numlines
        lda     su_n+1
        sbc     _numlines+1
        jcs     @done
        lda     su_n
        sta     lev_idx
        lda     su_n+1
        sta     lev_idx+1
        lda     #MAPARR_LINEDEFS
        ldy     #LINEDEF_SPECIAL
        jsr     lev_field
        lda     #<tmpb
        ldx     #>tmpb
        ldy     #1
        jsr     far_to
        jsr     far_rd
        lda     tmpb
        cmp     #48
        bne     @nextline
        lda     _scroll_count
        cmp     #MAXSCROLLERS
        bcs     @nextline
        asl     a                       ; su_dst = scroll_list + 4 * count
        asl     a
        clc
        adc     _scroll_list
        sta     su_dst
        lda     _scroll_list+1
        adc     #0
        sta     su_dst+1
        lda     su_n                    ; its front sidedef
        sta     lev_idx
        lda     su_n+1
        sta     lev_idx+1
        lda     #MAPARR_LINEDEFS
        ldy     #LINEDEF_SIDE0
        jsr     lev_field
        lda     su_dst
        ldx     su_dst+1
        ldy     #2
        jsr     far_to
        jsr     far_rd
        lda     su_dst                  ; and its offset now
        sta     ptr1
        lda     su_dst+1
        sta     ptr1+1
        lda     (ptr1)
        sta     lev_idx
        ldy     #1
        lda     (ptr1),y
        sta     lev_idx+1
        lda     #MAPARR_SIDEDEFS
        ldy     #SIDEDEF_XOFFSET
        jsr     lev_field
        clc
        lda     su_dst
        adc     #2
        pha
        lda     su_dst+1
        adc     #0
        tax
        pla
        ldy     #2
        jsr     far_to
        jsr     far_rd
        inc     _scroll_count
@nextline:
        inc     su_n
        jne     @lines
        inc     su_n+1
        jmp     @lines
@done:  lda     #0
        jmp     _P_ResetButtons

; C set iff the sector special A spawns a light (1-4, 8, 12, 13, 17)
is_light:
        cmp     #1
        bcc     @no
        cmp     #5
        bcc     @yes
        cmp     #8
        beq     @yes
        cmp     #12
        beq     @yes
        cmp     #13
        beq     @yes
        cmp     #17
        beq     @yes
@no:    clc
        rts
@yes:   sec
        rts

; ---- void P_ResetLevelData(uint8_t map) ----------------------------------------------------------
_P_ResetLevelData:
        sta     su_map
        lda     _kbanks
        sec
        sbc     #2
        sta     su_bank
        cmp     #DD_LAST_BANK + 2
        bcs     :+
        lda     #CRASH_BANKS_SPEC
        jmp     _kernel_crash
        ; the level being left: buttons up, walls unscrolled, the journal back
:       lda     #1
        jsr     _P_ResetButtons
        stz     su_count
@unscroll:
        lda     su_count
        cmp     _scroll_count
        bcs     @journal
        asl     a
        asl     a
        clc
        adc     _scroll_list
        sta     ptr1
        lda     _scroll_list+1
        adc     #0
        sta     ptr1+1
        lda     (ptr1)
        sta     lev_idx
        ldy     #1
        lda     (ptr1),y
        sta     lev_idx+1
        iny
        lda     (ptr1),y
        sta     sc_val
        iny
        lda     (ptr1),y
        sta     sc_val+1
        lda     #MAPARR_SIDEDEFS
        ldy     #SIDEDEF_XOFFSET
        jsr     lev_field
        lda     #<sc_val
        ldx     #>sc_val
        ldy     #2
        jsr     far_to
        jsr     far_wr
        inc     su_count
        bra     @unscroll
@journal:
        stz     _scroll_count
@back:  lda     _jcount
        ora     _jcount+1
        beq     @snap
        lda     _jcount
        bne     :+
        dec     _jcount+1
:       dec     _jcount
        lda     _jcount                 ; far_src = JOURNAL_BASE + 6 * jcount
        asl     a
        sta     tmp1
        lda     _jcount+1
        rol     a
        sta     tmp2
        lda     tmp1
        asl     a
        sta     far_src
        lda     tmp2
        rol     a
        sta     far_src+1
        clc
        lda     far_src
        adc     tmp1
        sta     far_src
        lda     far_src+1
        adc     tmp2
        sta     far_src+1
        clc
        lda     far_src
        adc     #<JOURNAL_BASE
        sta     far_src
        lda     far_src+1
        adc     #>JOURNAL_BASE
        sta     far_src+1
        lda     su_bank
        sta     far_src+2
        lda     #<jn_e
        ldx     #>jn_e
        ldy     #6
        jsr     far_to
        jsr     kjt_far_read
        lda     jn_e                    ; the old bytes back where they were
        sta     lev_far
        lda     jn_e+1
        sta     lev_far+1
        lda     jn_e+2
        sta     lev_far+2
        lda     #<(jn_e+4)
        ldx     #>(jn_e+4)
        ldy     jn_e+3
        jsr     far_to
        jsr     far_wr
        bra     @back
        ; the level to load: its sectors from the snapshot, or a snapshot
@snap:  lda     su_map
        beq     @out
        cmp     #SNAP_MAPS + 1
        bcs     @out
        dec     a                       ; far_src = the map's SECTORS descriptor
        lsr     a
        sta     far_src+1
        lda     #0
        ror     a                       ; 128 * (map - 1)
        clc
        adc     #<(DD_MAPDIR + MAP_ARRAYS + DESC_SIZE * MAPARR_SECTORS)
        sta     far_src
        lda     far_src+1
        adc     #>(DD_MAPDIR + MAP_ARRAYS + DESC_SIZE * MAPARR_SECTORS)
        sta     far_src+1
        lda     #DD_DIR_BANK
        sta     far_src+2
        lda     #<su_desc
        ldx     #>su_desc
        ldy     #DESC_SIZE
        jsr     far_to
        jsr     kjt_far_read
        ldx     su_map
        dex
        lda     snap_bank,x
        beq     @make
        sta     su_bank
        lda     snap_lo,x
        sta     su_addr
        lda     snap_hi,x
        sta     su_addr+1
        stz     su_to
        jmp     snapshot
@out:   rts
@make:  lda     snap_nextbank           ; the first: this bank, after the journal
        bne     :+
        lda     su_bank
        sta     snap_nextbank
        lda     #<SNAP_BASE
        sta     snap_next
        lda     #>SNAP_BASE
        sta     snap_next+1
:       lda     su_desc + DESC_COUNT    ; su_len = count * 16
        sta     su_len
        lda     su_desc + DESC_COUNT + 1
        ldx     #4
:       asl     su_len
        rol     a
        dex
        bne     :-
        sta     su_len+1
        clc                             ; past SNAP_END: the bank below, from $0200
        lda     snap_next
        adc     su_len
        sta     tmp1
        lda     snap_next+1
        adc     su_len+1
        bcs     @below
        tax                             ; the end <= SNAP_END?
        lda     tmp1
        cmp     #<(SNAP_END + 1)
        txa
        sbc     #>(SNAP_END + 1)
        bcc     @place
@below: dec     snap_nextbank
        lda     snap_nextbank
.ifdef BANKED_GAME
        ; These lower-RAM banks hold the phase images and render packet.
        ; Auxiliary LC code banks may still supply their independent RAM.
        cmp     #GAME_HOME_BANK
        beq     @below
        cmp     #PACKET_BANK
        beq     @below
        cmp     #RENDER_HOME_BANK
        beq     @below
.endif
        cmp     #DD_LAST_BANK + 2
        bcs     :+
        lda     #CRASH_BANKS_SPEC
        jmp     _kernel_crash
:       lda     #<JOURNAL_BASE
        sta     snap_next
        lda     #>JOURNAL_BASE
        sta     snap_next+1
@place: ldx     su_map
        dex
        lda     snap_nextbank
        sta     snap_bank,x
        sta     su_bank
        lda     snap_next
        sta     snap_lo,x
        sta     su_addr
        lda     snap_next+1
        sta     snap_hi,x
        sta     su_addr+1
        clc
        lda     snap_next
        adc     su_len
        sta     snap_next
        lda     snap_next+1
        adc     su_len+1
        sta     snap_next+1
        lda     #1
        sta     su_to
        ; fall through
; the SECTORS array (su_desc) between its chunks and the snapshot at
; su_bank:su_addr, into the snapshot if su_to
snapshot:
        lda     su_desc + DESC_LOG2     ; elements per chunk (log2 >= 16: all)
        ldx     #$FF
        stx     su_per
        stx     su_per+1
        cmp     #16
        bcs     :++
        tax
        lda     #1
        sta     su_per
        stz     su_per+1
        cpx     #0
        beq     :++
:       asl     su_per
        rol     su_per+1
        dex
        bne     :-
:       lda     su_desc + DESC_BANK
        sta     su_chunk
@chunk: lda     su_desc + DESC_COUNT
        ora     su_desc + DESC_COUNT + 1
        jeq     @done
        ; n = min(count, per) -> su_len = 16 n
        lda     su_desc + DESC_COUNT
        cmp     su_per
        lda     su_desc + DESC_COUNT + 1
        sbc     su_per+1
        lda     su_desc + DESC_COUNT
        ldx     su_desc + DESC_COUNT + 1
        bcc     :+
        lda     su_per
        ldx     su_per+1
:       sta     su_len
        stx     su_len+1
        sec                             ; count -= n
        lda     su_desc + DESC_COUNT
        sbc     su_len
        sta     su_desc + DESC_COUNT
        lda     su_desc + DESC_COUNT + 1
        sbc     su_len+1
        sta     su_desc + DESC_COUNT + 1
        ldx     #4
:       asl     su_len
        rol     su_len+1
        dex
        bne     :-
        ; live chunk: su_chunk:DESC_ADDR; snapshot: su_bank:su_addr
        lda     su_to
        beq     @from
        lda     su_desc + DESC_ADDR
        sta     far_src
        lda     su_desc + DESC_ADDR + 1
        sta     far_src+1
        lda     su_chunk
        sta     far_src+2
        lda     su_addr
        sta     far_dst
        lda     su_addr+1
        sta     far_dst+1
        lda     su_bank
        sta     far_dst+2
        bra     @copy
@from:  lda     su_addr
        sta     far_src
        lda     su_addr+1
        sta     far_src+1
        lda     su_bank
        sta     far_src+2
        lda     su_desc + DESC_ADDR
        sta     far_dst
        lda     su_desc + DESC_ADDR + 1
        sta     far_dst+1
        lda     su_chunk
        sta     far_dst+2
@copy:  lda     su_len
        sta     far_len
        lda     su_len+1
        sta     far_len+1
        jsr     kjt_far_copy
        clc
        lda     su_addr
        adc     su_len
        sta     su_addr
        lda     su_addr+1
        adc     su_len+1
        sta     su_addr+1
        inc     su_chunk
        jmp     @chunk
@done:  rts

.endif ; DD_MAPDIR
