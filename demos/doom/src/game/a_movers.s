; Doom for the Appletini -- doors, floors, stairs, plats, ceilings,
; teleporters, 6502 (docs/DESIGN.md section 9).
;
; The assembly twin of p_doors.c, p_floor.c, p_plats.c, p_ceilng.c,
; p_telept.c and p_spec.c's EV_DoDonut (the C is the reference, compiled
; on the host; read it for the why of each step). The tools are a_spec.s's
; (aspec.inc has the records).
;
; The thinkers (T_VerticalDoor, T_MoveFloor, T_PlatRaise, T_MoveCeiling)
; are called by P_RunThinkers with A/X = the mover, as cc65 __fastcall__.
; The EV_ routines take the line in ev_line (EV_DoFloorTag, from C, the
; tag), the argument (the type) in ev_arg, the thing in ev_thing, the
; side in ev_side, and return A = the count of sectors started (0 or 1).
; They walk the tagged sectors with tag_first/tag_next (the sector in
; ev_sec) and make movers with new_mover (the mover in mv and gpt; gpt is
; reloaded from mv after every call out).

.include "gmacros.inc"
.include "aspec.inc"

.ifdef DD_MAPDIR

.globalzp far_src, far_ptr, far_len
.import kjt_far_read
.import lev_addr, lev_idx, lev_far, far_rd, line_get
.import mv, ev_line, ev_tag, ev_arg, ev_thing, ev_side, ev_sec, pl_amount
.import tg_tag, tag_first, tag_next, ev_get_tag
.import sl_start, sl_next, next_sector, ns_sec
.import nb_find, nb_sec, nb_h, nb_ref
.import is_busy, new_mover, remove_mover, find_mover, nm_func, fm_sec, fm_func
.import move_plane, mp_dest, mp_crush, mp_ceil, mp_dir
.import floor_of, ceil_of, special_of, sec_floorpic, set_floorpic, snd_null
.import clear_line_special
.import _P_SetSectorSpecial, _P_Random, _S_StartSound, _P_FindTeleportDest, _P_TeleportMove
.import _P_SpawnMobj, _fine_sine, _fine_cosine, _thinkercap, _leveltime, _player
.import pushax, pusheax, popax

.export ev_do_door, ev_locked_door, ev_vertical_door, ev_do_floor, ev_do_plat, ev_stop_plat
.export ev_do_ceiling, ev_crush_stop, ev_build_stairs, ev_donut, ev_teleport
.export door_close30, door_raise5, _EV_DoFloorTag
.export T_VerticalDoor, T_MoveFloor, T_PlatRaise, T_MoveCeiling

.segment "BSS"
ev_rtn:     .res 1
hk_card:    .res 1
hk_msg:     .res 1
vd_special: .res 1
tf_res:     .res 1
tf_sec:     .res 2
fl_front:   .res 2
fl_h:       .res 2
fl_min:     .res 2
fl_tex:     .res 2
bh_tex:     .res 2
st_speed:   .res 1
st_size:    .res 1
st_height:  .res 2
st_tex:     .res 2
st_cur:     .res 2
st_next:    .res 2
dn_s1:      .res 2
dn_s2:      .res 2
dn_s3:      .res 2
pf_front:   .res 2
pf_h:       .res 2
bt_tag:     .res 2
bt_stop:    .res 1
tp_x:       .res 4
tp_y:       .res 4
tp_ox:      .res 4
tp_oy:      .res 4
tp_oz:      .res 4
tp_z:       .res 4
tp_ang:     .res 2
tp_fog:     .res 2
tp_t:       .res 4
tx_line:    .res 2                  ; raiseToTexture's line

SPECCODE

; ---- helpers ----------------------------------------------------------------------------
; a 16-bit field Y of the mover mv = A/X
put16:  pha
        phx
        ldmv
        plx
        pla
        sta     (gpt),y
        iny
        txa
        sta     (gpt),y
        rts

; a byte field Y of the mover mv = A
put8:   pha
        ldmv
        pla
        sta     (gpt),y
        rts

; A/X = the mover mv's 16-bit field Y
get16:  ldmv
        iny
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        rts

; the neighbour searches of ev_sec -> A/X
lowest_ceiling:
        lda     #$FF
        sta     nb_h
        lda     #$7F
        sta     nb_h+1
        lda     #NB_LOWCEIL
        bra     nb_ev
highest_ceiling:
        stz     nb_h
        stz     nb_h+1
        lda     #NB_HIGHCEIL
        bra     nb_ev
highest_floor:
        lda     #<-500
        sta     nb_h
        lda     #>-500
        sta     nb_h+1
        lda     #NB_HIGHFLOOR
        bra     nb_ev
lowest_floor:
        lda     ev_sec
        ldx     ev_sec+1
        jsr     floor_of
        sta     nb_h
        stx     nb_h+1
        lda     #NB_LOWFLOOR
        bra     nb_ev
next_floor:                             ; the next floor above ev_sec's
        lda     ev_sec
        ldx     ev_sec+1
        jsr     floor_of
        sta     nb_h
        stx     nb_h+1
        sta     nb_ref
        stx     nb_ref+1
        lda     #NB_NEXTFLOOR
nb_ev:  pha
        lda     ev_sec
        sta     nb_sec
        lda     ev_sec+1
        sta     nb_sec+1
        pla
        jmp     nb_find

; A/X = ev_sec's floor (ceiling)
ev_floor:
        lda     ev_sec
        ldx     ev_sec+1
        jmp     floor_of
ev_ceil:
        lda     ev_sec
        ldx     ev_sec+1
        jmp     ceil_of

; A/X -= 4 (a door's top below the lowest neighbouring ceiling)
minus4: sec
        sbc     #4
        bcs     :+
        dex
:       rts

; A/X = the sidedef of line A/X, side Y (LINEDEF_SIDE0 or _SIDE1)
line_side:
        sta     lev_idx
        stx     lev_idx+1
        phy
        lda     #MAPARR_LINEDEFS
        jsr     lev_addr
        pla
        clc
        adc     lev_far
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<bh_tex
        sta     far_ptr
        lda     #>bh_tex
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        lda     bh_tex
        ldx     bh_tex+1
        rts

; is ev_thing the player's mobj? Z set if so
ev_is_player:
        lda     ev_thing
        cmp     _player+PL_MO
        bne     :+
        lda     ev_thing+1
        cmp     _player+PL_MO+1
:       rts

; the key A (it_bluecard ...) or its skull, else the message X and "oof":
; C clear if the player has it
has_key:
        sta     hk_card
        stx     hk_msg
        jsr     ev_is_player
        bne     @no                     ; (not the player: no key, no message)
        ldx     hk_card
        lda     _player+PL_CARDS,x
        ora     _player+PL_CARDS+3,x
        bne     @yes
        lda     hk_msg
        sta     _player+PL_MESSAGE
        lda     #sfx_oof
        jsr     snd_null
@no:    sec
        rts
@yes:   clc
        rts

; ---- doors (p_doors.c) ---------------------------------------------------------------------------
T_VerticalDoor:
        sta     mv
        stx     mv+1
        ldmv
        ldy     #MV_DIR
        lda     (gpt),y
        jeq     @wait
        cmp     #2
        jeq     @initial
        cmp     #1
        jeq     @up
        ; down
        jsr     ev_mover_floor
        sta     mp_dest
        stx     mp_dest+1
        stz     mp_crush
        lda     #1
        sta     mp_ceil
        lda     #$FF
        sta     mp_dir
        jsr     move_plane
        cmp     #RES_PASTDEST
        beq     @dpast
        cmp     #RES_CRUSHED
        bne     @out
        ldmv                            ; a thing in the way: back up
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #vld_blazeClose
        beq     @out
        cmp     #vld_close
        beq     @out
        lda     #1
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_doropn
        jmp     snd_null
@out:   rts
@dpast: ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #vld_blazeRaise
        beq     @rmblaze
        cmp     #vld_blazeClose
        beq     @rmblaze
        cmp     #vld_normal
        beq     @rm
        cmp     #vld_close
        beq     @rm
        cmp     #vld_close30ThenOpen
        bne     @out
        lda     #0
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #<(35 * 30)
        ldx     #>(35 * 30)
        ldy     #DR_COUNT
        jmp     put16
@rmblaze:
        jsr     remove_mover
        lda     #sfx_bdcls
        jmp     snd_null
@rm:    jmp     remove_mover
@wait:  jsr     count_down              ; waiting at the top
        bne     @out
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #vld_blazeRaise
        beq     @goblaze
        cmp     #vld_normal
        beq     @godown
        cmp     #vld_close30ThenOpen
        bne     @out
        lda     #1
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_doropn
        jmp     snd_null
@goblaze:
        lda     #$FF
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_bdcls
        jmp     snd_null
@godown:
        lda     #$FF
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_dorcls
        jmp     snd_null
@initial:                               ; raiseIn5Mins' first wait
        jsr     count_down
        bne     @out
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #vld_raiseIn5Mins
        bne     @out
        lda     #vld_normal
        sta     (gpt),y
        lda     #1
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_doropn
        jmp     snd_null
@up:    ldy     #DR_TOP
        jsr     get16
        sta     mp_dest
        stx     mp_dest+1
        stz     mp_crush
        lda     #1
        sta     mp_ceil
        sta     mp_dir
        jsr     move_plane
        cmp     #RES_PASTDEST
        jne     @out
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #vld_blazeRaise
        beq     @top
        cmp     #vld_normal
        beq     @top
        cmp     #vld_close30ThenOpen
        jeq     @rm
        cmp     #vld_blazeOpen
        jeq     @rm
        cmp     #vld_open
        jeq     @rm
        rts
@top:   lda     #0                      ; wait at the top
        ldy     #MV_DIR
        sta     (gpt),y
        ldy     #DR_WAIT
        jsr     get16
        ldy     #DR_COUNT
        jmp     put16

; --topcountdown of the door mv: Z set when it reaches 0 (gpt = mv)
count_down:
        ldmv
        ldy     #DR_COUNT
        lda     (gpt),y
        sec
        sbc     #1
        sta     (gpt),y
        iny
        lda     (gpt),y
        sbc     #0
        sta     (gpt),y
        dey
        ora     (gpt),y
        rts

; A/X = the floor of the mover mv's sector
ev_mover_floor:
        ldy     #MV_SECTOR
        jsr     get16
        jmp     floor_of

; a new door of type A on ev_sec (vanilla's speed and wait) -> mv, gpt
new_door:
        pha
        lda     #<T_VerticalDoor
        sta     nm_func
        lda     #>T_VerticalDoor
        sta     nm_func+1
        jsr     new_mover
        pla
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     #VDOORSPEED
        ldy     #MV_SPEED
        sta     (gpt),y
        lda     #<VDOORWAIT
        ldy     #DR_WAIT
        sta     (gpt),y
        iny
        lda     #>VDOORWAIT
        sta     (gpt),y
        rts

; the door mv's top = 4 below ev_sec's lowest neighbouring ceiling -> A/X
door_top:
        jsr     lowest_ceiling
        jsr     minus4
        ldy     #DR_TOP
        jmp     put16

; the door's top differs from ev_sec's ceiling: Z clear
top_moves:
        ldy     #DR_TOP
        jsr     get16
        sta     tmp3
        stx     tmp4
        jsr     ev_ceil
        cmp     tmp3
        bne     :+
        cpx     tmp4
:       rts

; vanilla EV_DoDoor(ev_line, ev_arg)
ev_do_door:
        jsr     ev_get_tag
        stz     ev_rtn
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        lda     ev_arg
        jsr     new_door
        lda     ev_arg
        cmp     #vld_blazeClose
        beq     @blclose
        cmp     #vld_close
        beq     @close
        cmp     #vld_close30ThenOpen
        beq     @c30
        cmp     #vld_blazeRaise
        beq     @blopen
        cmp     #vld_blazeOpen
        beq     @blopen
        cmp     #vld_normal
        beq     @open
        cmp     #vld_open
        beq     @open
        bra     @next
@blclose:
        jsr     door_top
        lda     #$FF
        ldy     #MV_DIR
        jsr     put8
        lda     #VDOORSPEED * 4
        ldy     #MV_SPEED
        jsr     put8
        lda     #sfx_bdcls
        jsr     snd_null
        bra     @next
@close: jsr     door_top
        lda     #$FF
        ldy     #MV_DIR
        jsr     put8
        lda     #sfx_dorcls
        jsr     snd_null
        bra     @next
@c30:   jsr     ev_ceil
        ldy     #DR_TOP
        jsr     put16
        lda     #$FF
        ldy     #MV_DIR
        jsr     put8
        lda     #sfx_dorcls
        jsr     snd_null
        bra     @next
@blopen:
        lda     #1
        ldy     #MV_DIR
        jsr     put8
        jsr     door_top
        lda     #VDOORSPEED * 4
        ldy     #MV_SPEED
        jsr     put8
        jsr     top_moves
        beq     @next
        lda     #sfx_bdopn
        jsr     snd_null
        bra     @next
@open:  lda     #1
        ldy     #MV_DIR
        jsr     put8
        jsr     door_top
        jsr     top_moves
        beq     @next
        lda     #sfx_doropn
        jsr     snd_null
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; vanilla EV_DoLockedDoor(ev_line, ev_arg, ev_thing): "you need a ... key
; to activate this object"
ev_locked_door:
        lda     ev_line
        ldx     ev_line+1
        jsr     line_get
        ldy     #LI_SPECIAL
        lda     (gli),y
        cmp     #99
        beq     @blue
        cmp     #133
        beq     @blue
        cmp     #134
        beq     @red
        cmp     #135
        beq     @red
        cmp     #136
        beq     @yellow
        cmp     #137
        beq     @yellow
        jmp     ev_do_door
@blue:  lda     #it_bluecard
        ldx     #MSG_PD_BLUEO
        bra     @key
@red:   lda     #it_redcard
        ldx     #MSG_PD_REDO
        bra     @key
@yellow:
        lda     #it_yellowcard
        ldx     #MSG_PD_YELLOWO
@key:   jsr     has_key
        bcs     :+
        jmp     ev_do_door
:       lda     #0
        rts

; vanilla EV_VerticalDoor(ev_line, ev_thing): the manual doors
ev_vertical_door:
        lda     ev_line
        ldx     ev_line+1
        jsr     line_get
        ldy     #LI_SPECIAL
        lda     (gli),y
        sta     vd_special
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        sta     ev_sec
        iny
        lda     (gli),y
        sta     ev_sec+1
        lda     vd_special
        cmp     #26
        beq     @blue
        cmp     #32
        beq     @blue
        cmp     #27
        beq     @yellow
        cmp     #34
        beq     @yellow
        cmp     #28
        beq     @red
        cmp     #33
        beq     @red
        bra     @keyok
@blue:  lda     #it_bluecard
        ldx     #MSG_PD_BLUEK
        bra     @key
@yellow:
        lda     #it_yellowcard
        ldx     #MSG_PD_YELLOWK
        bra     @key
@red:   lda     #it_redcard
        ldx     #MSG_PD_REDK
@key:   jsr     has_key
        bcc     @keyok
@out:   rts
@keyok: lda     ev_sec+1                ; a one-sided door line (vanilla would crash)
        and     ev_sec
        cmp     #$FF
        beq     @out
        lda     ev_sec
        ldx     ev_sec+1
        jsr     is_busy
        beq     @new
        ; the sector moves: a raise door turns around
        lda     ev_sec
        sta     fm_sec
        lda     ev_sec+1
        sta     fm_sec+1
        lda     #<T_VerticalDoor
        sta     fm_func
        lda     #>T_VerticalDoor
        sta     fm_func+1
        jsr     find_mover
        bcs     @out                    ; not a door: nothing
        sta     mv
        stx     mv+1
        lda     vd_special
        cmp     #1
        beq     @turn
        cmp     #117
        beq     @turn
        cmp     #26
        bcc     @new
        cmp     #29
        bcs     @new
@turn:  ldmv
        ldy     #MV_DIR
        lda     (gpt),y
        cmp     #$FF
        bne     @close
        lda     #1                      ; closing: back up
        sta     (gpt),y
        rts
@close: jsr     ev_is_player            ; monsters never close doors
        bne     @out
        lda     #$FF
        ldy     #MV_DIR
        sta     (gpt),y
        rts
@new:   lda     #sfx_doropn
        ldx     vd_special
        cpx     #117
        beq     :+
        cpx     #118
        bne     :++
:       lda     #sfx_bdopn
:       jsr     snd_null
        lda     #vld_normal
        jsr     new_door
        lda     #1
        ldy     #MV_DIR
        sta     (gpt),y
        lda     vd_special
        cmp     #117
        beq     @blraise
        cmp     #118
        beq     @blopen
        cmp     #31
        bcc     @top
        cmp     #35
        bcs     @top
        lda     #vld_open               ; 31-34: stays open, used up
        ldy     #MV_TYPE
        sta     (gpt),y
        bra     @used
@blraise:
        lda     #vld_blazeRaise
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     #VDOORSPEED * 4
        ldy     #MV_SPEED
        sta     (gpt),y
        bra     @top
@blopen:
        lda     #vld_blazeOpen
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     #VDOORSPEED * 4
        ldy     #MV_SPEED
        sta     (gpt),y
@used:  lda     ev_line
        ldx     ev_line+1
        jsr     clear_line_special
@top:   jmp     door_top

; sector special 10: closes 30 seconds into the level (ev_sec)
door_close30:
        lda     #vld_normal
        jsr     new_door
        jsr     special_off
        lda     #0
        ldy     #MV_DIR
        jsr     put8
        lda     #<(30 * 35)
        ldx     #>(30 * 35)
        ldy     #DR_COUNT
        jmp     put16

; sector special 14: opens 5 minutes into the level (ev_sec)
door_raise5:
        lda     #vld_raiseIn5Mins
        jsr     new_door
        jsr     special_off
        lda     #2
        ldy     #MV_DIR
        jsr     put8
        jsr     door_top
        lda     #<(5 * 60 * 35)
        ldx     #>(5 * 60 * 35)
        ldy     #DR_COUNT
        jmp     put16

; ev_sec's special = 0
special_off:
        lda     ev_sec
        ldx     ev_sec+1
        jsr     pushax
        lda     #0
        jmp     _P_SetSectorSpecial

; ---- floors (p_floor.c) ---------------------------------------------------------------------------
T_MoveFloor:
        sta     mv
        stx     mv+1
        ldmv
        ldy     #FM_DEST
        lda     (gpt),y
        sta     mp_dest
        iny
        lda     (gpt),y
        sta     mp_dest+1
        ldy     #FM_CRUSH
        lda     (gpt),y
        sta     mp_crush
        stz     mp_ceil
        ldy     #MV_DIR
        lda     (gpt),y
        sta     mp_dir
        jsr     move_plane
        sta     tf_res
        lda     _leveltime
        and     #7
        bne     :+
        lda     #sfx_stnmov
        jsr     snd_null
:       lda     tf_res
        cmp     #RES_PASTDEST
        bne     @out
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        tax
        ldy     #MV_DIR
        lda     (gpt),y
        cmp     #1
        bne     @down
        cpx     #donutRaise
        beq     @change
        bra     @rm
@down:  cpx     #lowerAndChange
        bne     @rm
@change:                                ; the new special and flat
        ldy     #MV_SECTOR
        jsr     get16
        sta     tf_sec
        stx     tf_sec+1
        jsr     pushax
        ldy     #FM_NEWSPEC
        lda     (gpt),y
        jsr     _P_SetSectorSpecial
        lda     tf_sec
        sta     ev_sec
        lda     tf_sec+1
        sta     ev_sec+1
        ldy     #FM_TEX
        jsr     get16
        jsr     set_floorpic
@rm:    jsr     remove_mover
        lda     #sfx_pstop
        jmp     snd_null
@out:   rts

; a new floor mover (T_MoveFloor) on ev_sec: type ev_arg, speed A,
; direction X -> mv, gpt
new_floor:
        pha
        phx
        lda     #<T_MoveFloor
        sta     nm_func
        lda     #>T_MoveFloor
        sta     nm_func+1
        jsr     new_mover
        pla
        ldy     #MV_DIR
        sta     (gpt),y
        pla
        ldy     #MV_SPEED
        sta     (gpt),y
        lda     ev_arg
        ldy     #MV_TYPE
        sta     (gpt),y
        rts

; the floor's destination = A/X
set_dest:
        ldy     #FM_DEST
        jmp     put16

; ---- int16_t EV_DoFloorTag(uint16_t tag, uint8_t floortype) -------------------------------------
_EV_DoFloorTag:
        sta     ev_arg
        jsr     popax
        sta     tg_tag
        stx     tg_tag+1
        jsr     floor_tag
        ldx     #0
        rts

; vanilla EV_DoFloor(ev_line, ev_arg)
ev_do_floor:
        jsr     ev_get_tag
        lda     ev_arg
        cmp     #raiseFloor24AndChange
        bne     floor_tag
        ; the tagged sectors take the flat and special of the line's front
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        sta     fl_front
        iny
        lda     (gli),y
        sta     fl_front+1
        jsr     tag_first
@loop:  bcs     @done
        jsr     is_busy
        bne     @next
        lda     fl_front
        ldx     fl_front+1
        jsr     sec_floorpic
        jsr     set_floorpic
        lda     ev_sec
        ldx     ev_sec+1
        jsr     pushax
        lda     fl_front
        ldx     fl_front+1
        jsr     special_of
        jsr     _P_SetSectorSpecial
@next:  jsr     tag_next
        bra     @loop
@done:  lda     #raiseFloor24
        sta     ev_arg
        ; fall through
; vanilla EV_DoFloor's work, the tag in tg_tag -> A
floor_tag:
        stz     ev_rtn
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        lda     #FLOORSPEED
        ldx     #1
        jsr     new_floor
        lda     ev_arg
        cmp     #lowerFloor
        beq     @lower
        cmp     #lowerFloorToLowest
        beq     @lowest
        cmp     #turboLower
        beq     @turbo
        cmp     #raiseFloorCrush
        jeq     @raise
        cmp     #raiseFloor
        beq     @raise
        cmp     #raiseFloorTurbo
        jeq     @rturbo
        cmp     #raiseFloorToNearest
        jeq     @nearest
        cmp     #raiseFloor24
        jeq     @r24
        cmp     #raiseFloor512
        jeq     @r512
        cmp     #raiseToTexture
        jeq     @texture
        cmp     #lowerAndChange
        jeq     @change
        jmp     @next
@lower: jsr     dir_down
        jsr     highest_floor
        jsr     set_dest
        jmp     @next
@lowest:
        jsr     dir_down
        jsr     lowest_floor
        jsr     set_dest
        jmp     @next
@turbo: jsr     dir_down
        lda     #FLOORSPEED * 4
        ldy     #MV_SPEED
        jsr     put8
        jsr     highest_floor
        sta     fl_h
        stx     fl_h+1
        jsr     ev_floor
        cmp     fl_h
        bne     :+
        cpx     fl_h+1
        beq     @tset
:       clc
        lda     fl_h
        adc     #8
        sta     fl_h
        bcc     @tset
        inc     fl_h+1
@tset:  lda     fl_h
        ldx     fl_h+1
        jsr     set_dest
        jmp     @next
@raise: jsr     lowest_ceiling          ; h = min(lowest neighbouring ceiling, own)
        sta     fl_h
        stx     fl_h+1
        jsr     ev_ceil
        sta     tmp3
        stx     tmp4
        slt16   tmp3, fl_h
        bpl     :+
        lda     tmp3
        sta     fl_h
        lda     tmp4
        sta     fl_h+1
:       lda     ev_arg
        cmp     #raiseFloorCrush
        bne     @tset
        lda     #1
        ldy     #FM_CRUSH
        jsr     put8
        lda     fl_h                    ; the crusher stops 8 below
        sec
        sbc     #8
        sta     fl_h
        bcs     @tset
        dec     fl_h+1
        bra     @tset
@rturbo:
        lda     #FLOORSPEED * 4
        ldy     #MV_SPEED
        jsr     put8
@nearest:
        jsr     next_floor
        jsr     set_dest
        jmp     @next
@r24:   lda     #24
        bra     @plus
@r512:  lda     #<512
        ldx     #>512
        bra     @plus2
@plus:  ldx     #0
@plus2: sta     fl_h
        stx     fl_h+1
        jsr     ev_floor
        clc
        adc     fl_h
        sta     fl_h
        txa
        adc     fl_h+1
        tax
        lda     fl_h
        jsr     set_dest
        jmp     @next
@texture:                               ; up by the lowest lower texture around
        lda     #$FF
        sta     fl_min
        lda     #$7F
        sta     fl_min+1
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sl_start
@tloop: jsr     sl_next
        bcs     @tend
        sta     tx_line
        stx     tx_line+1
        jsr     line_get
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @tloop
        ldy     #LINEDEF_SIDE0
        jsr     bottom_height
        ldy     #LINEDEF_SIDE1
        jsr     bottom_height
        bra     @tloop
@tend:  jsr     ev_floor
        clc
        adc     fl_min
        sta     fl_h
        txa
        adc     fl_min+1
        sta     fl_h+1
        bvc     :+
        lda     #$FF                    ; (past 32767: 32767)
        sta     fl_h
        lda     #$7F
        sta     fl_h+1
:       jmp     @tset
@change:                                ; down to the lowest neighbour; its flat and special
        jsr     dir_down
        jsr     lowest_floor
        sta     fl_h
        stx     fl_h+1
        jsr     set_dest
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sec_floorpic
        ldy     #FM_TEX
        jsr     put16
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sl_start
@cloop: jsr     sl_next
        bcs     @next
        jsr     line_get
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @cloop
        ldy     #LI_FRONTSECTOR         ; the other sector
        lda     (gli),y
        cmp     ev_sec
        bne     @front
        iny
        lda     (gli),y
        dey
        cmp     ev_sec+1
        bne     @front
        ldy     #LI_BACKSECTOR
@front: lda     (gli),y                 ; (Y at the other's low byte)
        sta     fl_front
        iny
        lda     (gli),y
        sta     fl_front+1
        tax
        lda     fl_front
        jsr     floor_of
        cmp     fl_h
        bne     @cloop
        cpx     fl_h+1
        bne     @cloop
        lda     fl_front
        ldx     fl_front+1
        jsr     sec_floorpic
        ldy     #FM_TEX
        jsr     put16
        lda     fl_front
        ldx     fl_front+1
        jsr     special_of
        ldy     #FM_NEWSPEC
        jsr     put8
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; the mover's direction down
dir_down:
        lda     #$FF
        ldy     #MV_DIR
        jmp     put8

; fl_min = min(fl_min, the Doom height of the lower texture of line
; tx_line's side Y); a missing side or texture counts not
bottom_height:
        lda     tx_line
        ldx     tx_line+1
        jsr     line_side
        cpx     #$FF
        bne     :+
        cmp     #$FF
        beq     @out
:       sta     lev_idx
        stx     lev_idx+1
        lda     #MAPARR_SIDEDEFS
        jsr     lev_addr
        clc
        lda     lev_far
        adc     #SIDEDEF_BOTTOMTEXTURE
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<bh_tex
        sta     far_ptr
        lda     #>bh_tex
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        lda     bh_tex
        ora     bh_tex+1
        beq     @out
        ldx     #4                      ; the TEX record's height: 16 * texture
:       asl     bh_tex
        rol     bh_tex+1
        dex
        bne     :-
        clc
        lda     bh_tex
        adc     #<(DD_TEXDIR + TEX_HEIGHT)
        sta     far_src
        lda     bh_tex+1
        adc     #>(DD_TEXDIR + TEX_HEIGHT)
        sta     far_src+1
        lda     #DD_DIR_BANK
        sta     far_src+2
        lda     #<bh_tex
        sta     far_ptr
        lda     #>bh_tex
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     kjt_far_read
        slt16   bh_tex, fl_min
        bpl     @out
        lda     bh_tex
        sta     fl_min
        lda     bh_tex+1
        sta     fl_min+1
@out:   rts

; vanilla EV_BuildStairs(ev_line, ev_arg)
ev_build_stairs:
        jsr     ev_get_tag
        stz     ev_rtn
        lda     #FLOORSPEED / 4
        ldx     #8
        ldy     ev_arg
        cpy     #build8
        beq     :+
        lda     #FLOORSPEED * 4
        ldx     #16
:       sta     st_speed
        stx     st_size
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        jsr     ev_floor
        clc
        adc     st_size
        sta     st_height
        bcc     :+
        inx
:       stx     st_height+1
        lda     ev_sec
        ldx     ev_sec+1
        jsr     sec_floorpic
        sta     st_tex
        stx     st_tex+1
@step:  lda     st_speed                ; this step's mover (type 0, as C's zeroed one)
        ldx     #1
        jsr     new_floor
        lda     #0
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     st_height
        ldx     st_height+1
        jsr     set_dest
        ; the next step: a two-sided line with this one in front, whose
        ; back sector has the same flat
        lda     ev_sec
        sta     st_cur
        ldx     ev_sec+1
        stx     st_cur+1
        jsr     sl_start
@lines: jsr     sl_next
        bcs     @next
        jsr     line_get
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @lines
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        cmp     st_cur
        bne     @lines
        iny
        lda     (gli),y
        cmp     st_cur+1
        bne     @lines
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        sta     st_next
        iny
        lda     (gli),y
        sta     st_next+1
        tax
        lda     st_next
        jsr     sec_floorpic
        cmp     st_tex
        bne     @lines
        cpx     st_tex+1
        bne     @lines
        clc
        lda     st_height
        adc     st_size
        sta     st_height
        bcc     :+
        inc     st_height+1
:       lda     st_next
        ldx     st_next+1
        jsr     is_busy
        bne     @lines
        lda     st_next
        sta     ev_sec
        lda     st_next+1
        sta     ev_sec+1
        jmp     @step
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; vanilla EV_DoDonut(ev_line)
ev_donut:
        jsr     ev_get_tag
        stz     ev_rtn
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        lda     ev_sec
        sta     dn_s1
        sta     ns_sec
        ldx     ev_sec+1
        stx     dn_s1+1
        stx     ns_sec+1
        jsr     sl_start                ; s2: beyond s1's first line
        jsr     sl_next
        jcs     @next
        jsr     next_sector
        cpx     #$FF
        jeq     @next                   ; (vanilla would crash)
        sta     dn_s2
        stx     dn_s2+1
        jsr     sl_start
@lines: jsr     sl_next
        jcs     @next
        jsr     line_get
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        sta     dn_s3
        iny
        lda     (gli),y
        sta     dn_s3+1
        cmp     #$FF                    ; (one-sided)
        bne     :+
        lda     dn_s3
        cmp     #$FF
        beq     @lines
:       lda     dn_s3                   ; vanilla's ML_TWOSIDED test is always
        cmp     dn_s1                   ; false: only the line back to s1 is skipped
        bne     @slime
        lda     dn_s3+1
        cmp     dn_s1+1
        beq     @lines
@slime: lda     dn_s2                   ; the rising slime
        sta     ev_sec
        lda     dn_s2+1
        sta     ev_sec+1
        lda     #donutRaise
        sta     ev_arg
        lda     #FLOORSPEED / 2
        ldx     #1
        jsr     new_floor
        lda     dn_s3
        ldx     dn_s3+1
        jsr     sec_floorpic
        ldy     #FM_TEX
        jsr     put16
        lda     dn_s3
        ldx     dn_s3+1
        jsr     floor_of
        ldy     #FM_DEST
        jsr     put16
        lda     dn_s1                   ; the lowering donut hole
        sta     ev_sec
        lda     dn_s1+1
        sta     ev_sec+1
        lda     #lowerFloor
        sta     ev_arg
        lda     #FLOORSPEED / 2
        ldx     #$FF
        jsr     new_floor
        lda     dn_s3
        ldx     dn_s3+1
        jsr     floor_of
        ldy     #FM_DEST
        jsr     put16
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; ---- plats (p_plats.c) ---------------------------------------------------------------------------
T_PlatRaise:
        sta     mv
        stx     mv+1
        ldmv
        ldy     #MV_DIR
        lda     (gpt),y
        beq     @up
        cmp     #PLAT_DOWN
        jeq     @down
        cmp     #PLAT_WAITING
        jeq     @waiting
        rts                             ; in stasis
@up:    ldy     #PT_HIGH
        jsr     get16
        sta     mp_dest
        stx     mp_dest+1
        ldy     #PT_CRUSH
        lda     (gpt),y
        sta     mp_crush
        stz     mp_ceil
        lda     #1
        sta     mp_dir
        jsr     move_plane
        sta     tf_res
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #raiseAndChange
        beq     :+
        cmp     #raiseToNearestAndChange
        bne     :++
:       lda     _leveltime
        and     #7
        bne     :+
        lda     #sfx_stnmov
        jsr     snd_null
:       ldmv
        lda     tf_res
        cmp     #RES_CRUSHED
        bne     @past
        ldy     #PT_CRUSH
        lda     (gpt),y
        bne     @past
        jsr     wait_again              ; blocked: back down
        lda     #PLAT_DOWN
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_pstart
        jmp     snd_null
@past:  lda     tf_res
        cmp     #RES_PASTDEST
        bne     @out
        jsr     wait_again
        lda     #PLAT_WAITING
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_pstop
        jsr     snd_null
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #perpetualRaise
        beq     @out
        jmp     remove_mover
@out:   rts
@down:  ldy     #PT_LOW
        jsr     get16
        sta     mp_dest
        stx     mp_dest+1
        stz     mp_crush
        stz     mp_ceil
        lda     #$FF
        sta     mp_dir
        jsr     move_plane
        cmp     #RES_PASTDEST
        bne     @out
        ldmv
        jsr     wait_again
        lda     #PLAT_WAITING
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_pstop
        jmp     snd_null
@waiting:
        ldy     #PT_COUNT
        lda     (gpt),y
        dec     a
        sta     (gpt),y
        bne     @out
        ldy     #MV_SECTOR              ; up if at the bottom, else down
        jsr     get16
        jsr     floor_of
        sta     tmp3
        stx     tmp4
        ldmv
        ldx     #PLAT_UP
        ldy     #PT_LOW
        lda     (gpt),y
        cmp     tmp3
        bne     :+
        iny
        lda     (gpt),y
        cmp     tmp4
        beq     :++
:       ldx     #PLAT_DOWN
:       txa
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #sfx_pstart
        jmp     snd_null

; count = wait (gpt = the plat)
wait_again:
        ldy     #PT_WAIT
        lda     (gpt),y
        iny
        sta     (gpt),y
        rts
.assert PT_COUNT = PT_WAIT + 1, error, "wait_again"

; the plats (bt_stop 0: restart those in stasis; else stop the moving
; ones) of tag bt_tag: vanilla P_ActivateInStasis, EV_StopPlat
plats_by_tag:
        lda     _thinkercap+TH_NEXT
        ldx     _thinkercap+TH_NEXT+1
@loop:  sta     gpt
        stx     gpt+1
        cmp     #<_thinkercap
        bne     :+
        cpx     #>_thinkercap
        beq     @out
:       ldy     #TH_FUNCTION
        lda     (gpt),y
        cmp     #<T_PlatRaise
        bne     @nx
        iny
        lda     (gpt),y
        cmp     #>T_PlatRaise
        bne     @nx
        ldy     #PT_TAG
        lda     (gpt),y
        cmp     bt_tag
        bne     @nx
        iny
        lda     (gpt),y
        cmp     bt_tag+1
        bne     @nx
        ldy     #MV_DIR
        lda     (gpt),y
        ldx     bt_stop
        beq     @start
        cmp     #PLAT_STASIS
        beq     @nx
        ldy     #PT_OLD
        sta     (gpt),y
        lda     #PLAT_STASIS
        ldy     #MV_DIR
        sta     (gpt),y
        bra     @nx
@start: cmp     #PLAT_STASIS
        bne     @nx
        ldy     #PT_OLD
        lda     (gpt),y
        ldy     #MV_DIR
        sta     (gpt),y
@nx:    ldy     #TH_NEXT+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        bra     @loop
@out:   rts

ev_stop_plat:
        jsr     ev_get_tag
        lda     tg_tag
        sta     bt_tag
        lda     tg_tag+1
        sta     bt_tag+1
        lda     #1
        sta     bt_stop
        jmp     plats_by_tag

; vanilla EV_DoPlat(ev_line, ev_arg, pl_amount)
ev_do_plat:
        jsr     ev_get_tag
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        sta     pf_front
        iny
        lda     (gli),y
        sta     pf_front+1
        lda     ev_arg
        cmp     #perpetualRaise
        bne     :+
        lda     tg_tag
        sta     bt_tag
        lda     tg_tag+1
        sta     bt_tag+1
        stz     bt_stop
        jsr     plats_by_tag
:       stz     ev_rtn
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        lda     #<T_PlatRaise
        sta     nm_func
        lda     #>T_PlatRaise
        sta     nm_func+1
        jsr     new_mover
        lda     ev_arg
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     tg_tag
        ldx     tg_tag+1
        ldy     #PT_TAG
        jsr     put16
        jsr     ev_floor
        sta     pf_h
        stx     pf_h+1
        lda     ev_arg
        cmp     #raiseToNearestAndChange
        beq     @change
        cmp     #raiseAndChange
        beq     @change
        cmp     #downWaitUpStay
        beq     @dwus
        cmp     #blazeDWUS
        beq     @dwus
        cmp     #perpetualRaise
        jeq     @perp
        jmp     @next
@change:
        lda     #PLATSPEED / 2
        ldy     #MV_SPEED
        jsr     put8
        lda     pf_front
        ldx     pf_front+1
        jsr     sec_floorpic
        jsr     set_floorpic
        lda     ev_arg
        cmp     #raiseToNearestAndChange
        bne     @amount
        jsr     next_floor
        ldy     #PT_HIGH
        jsr     put16
        jsr     special_off             ; no more damage
        bra     @cup
@amount:
        clc
        lda     pf_h
        adc     pl_amount
        ldx     pf_h+1
        bcc     :+
        inx
:       ldy     #PT_HIGH
        jsr     put16
@cup:   lda     #PLAT_UP
        ldy     #MV_DIR
        jsr     put8
        lda     #sfx_stnmov
        jsr     snd_null
        bra     @next
@dwus:  lda     #PLATSPEED * 4
        ldx     ev_arg
        cpx     #blazeDWUS
        bne     :+
        lda     #PLATSPEED * 8
:       ldy     #MV_SPEED
        jsr     put8
        jsr     low_limit
        lda     pf_h
        ldx     pf_h+1
        ldy     #PT_HIGH
        jsr     put16
        lda     #35 * PLATWAIT
        ldy     #PT_WAIT
        jsr     put8
        lda     #PLAT_DOWN
        ldy     #MV_DIR
        jsr     put8
        lda     #sfx_pstart
        jsr     snd_null
        bra     @next
@perp:  lda     #PLATSPEED
        ldy     #MV_SPEED
        jsr     put8
        jsr     low_limit
        jsr     highest_floor           ; high = max(highest neighbour, own)
        sta     tmp3
        stx     tmp4
        slt16   tmp3, pf_h
        bpl     :+
        lda     pf_h
        sta     tmp3
        lda     pf_h+1
        sta     tmp4
:       lda     tmp3
        ldx     tmp4
        ldy     #PT_HIGH
        jsr     put16
        lda     #35 * PLATWAIT
        ldy     #PT_WAIT
        jsr     put8
        jsr     _P_Random
        and     #1
        ldy     #MV_DIR
        jsr     put8
        lda     #sfx_pstart
        jsr     snd_null
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; the plat's low = min(lowest neighbouring floor, own floor pf_h)
low_limit:
        jsr     lowest_floor
        sta     tmp3
        stx     tmp4
        slt16   pf_h, tmp3
        bpl     :+
        lda     pf_h
        sta     tmp3
        lda     pf_h+1
        sta     tmp4
:       lda     tmp3
        ldx     tmp4
        ldy     #PT_LOW
        jmp     put16

; ---- ceilings (p_ceilng.c) ----------------------------------------------------------------------
T_MoveCeiling:
        sta     mv
        stx     mv+1
        ldmv
        ldy     #MV_DIR
        lda     (gpt),y
        bne     :+
        rts                             ; in stasis
:       sta     mp_dir
        lda     #1
        sta     mp_ceil
        lda     mp_dir
        bmi     @godown
        ldy     #CE_TOP
        jsr     get16
        stz     mp_crush
        bra     @move
@godown:
        ldy     #CE_CRUSH
        lda     (gpt),y
        sta     mp_crush
        ldy     #CE_BOTTOM
        jsr     get16
@move:  sta     mp_dest
        stx     mp_dest+1
        jsr     move_plane
        sta     tf_res
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        cmp     #silentCrushAndRaise
        beq     :+
        lda     _leveltime
        and     #7
        bne     :+
        lda     #sfx_stnmov
        jsr     snd_null
:       ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        tax
        ldy     #MV_DIR
        lda     (gpt),y
        bmi     @down
        lda     tf_res                  ; up
        cmp     #RES_PASTDEST
        bne     @out
        cpx     #raiseToHighest
        beq     @rm
        cpx     #silentCrushAndRaise
        bne     :+
        lda     #sfx_pstop
        jsr     snd_null
        bra     @todown
:       cpx     #fastCrushAndRaise
        beq     @todown
        cpx     #crushAndRaise
        bne     @out
@todown:
        lda     #$FF
        ldy     #MV_DIR
        jmp     put8
@rm:    jmp     remove_mover
@out:   rts
@down:  lda     tf_res
        cmp     #RES_PASTDEST
        bne     @crushed
        cpx     #lowerAndCrush
        beq     @rm
        cpx     #lowerToFloor
        beq     @rm
        cpx     #silentCrushAndRaise
        bne     :+
        lda     #sfx_pstop
        jsr     snd_null
        ldmv
        ldy     #MV_TYPE
        lda     (gpt),y
        tax
:       cpx     #fastCrushAndRaise
        beq     @toup
        cpx     #crushAndRaise
        beq     @normal
        cpx     #silentCrushAndRaise
        bne     @out
@normal:
        lda     #CEILSPEED
        ldy     #MV_SPEED
        jsr     put8
@toup:  lda     #1
        ldy     #MV_DIR
        jmp     put8
@crushed:
        cmp     #RES_CRUSHED
        bne     @out
        cpx     #silentCrushAndRaise
        beq     @slow
        cpx     #crushAndRaise
        beq     @slow
        cpx     #lowerAndCrush
        bne     @out
@slow:  lda     #CEILSPEED / 8          ; a thing under it: an eighth of the speed
        ldy     #MV_SPEED
        jmp     put8

; the ceilings of tag bt_tag (bt_stop 0: restart those in stasis; else
; stop the moving ones, A = 1 if any): vanilla P_ActivateInStasisCeiling,
; EV_CeilingCrushStop
ceilings_by_tag:
        stz     ev_rtn
        lda     _thinkercap+TH_NEXT
        ldx     _thinkercap+TH_NEXT+1
@loop:  sta     gpt
        stx     gpt+1
        cmp     #<_thinkercap
        bne     :+
        cpx     #>_thinkercap
        beq     @out
:       ldy     #TH_FUNCTION
        lda     (gpt),y
        cmp     #<T_MoveCeiling
        bne     @nx
        iny
        lda     (gpt),y
        cmp     #>T_MoveCeiling
        bne     @nx
        ldy     #CE_TAG
        lda     (gpt),y
        cmp     bt_tag
        bne     @nx
        iny
        lda     (gpt),y
        cmp     bt_tag+1
        bne     @nx
        ldy     #MV_DIR
        lda     (gpt),y
        ldx     bt_stop
        beq     @start
        tax
        beq     @nx
        ldy     #CE_OLD
        sta     (gpt),y
        lda     #0
        ldy     #MV_DIR
        sta     (gpt),y
        lda     #1
        sta     ev_rtn
        bra     @nx
@start: tax
        bne     @nx
        ldy     #CE_OLD
        lda     (gpt),y
        ldy     #MV_DIR
        sta     (gpt),y
@nx:    ldy     #TH_NEXT+1
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        bra     @loop
@out:   lda     ev_rtn
        rts

ev_crush_stop:
        jsr     ev_get_tag
        lda     tg_tag
        sta     bt_tag
        lda     tg_tag+1
        sta     bt_tag+1
        lda     #1
        sta     bt_stop
        jmp     ceilings_by_tag

; vanilla EV_DoCeiling(ev_line, ev_arg)
ev_do_ceiling:
        jsr     ev_get_tag
        lda     ev_arg
        cmp     #fastCrushAndRaise
        beq     :+
        cmp     #silentCrushAndRaise
        beq     :+
        cmp     #crushAndRaise
        bne     :++
:       lda     tg_tag
        sta     bt_tag
        lda     tg_tag+1
        sta     bt_tag+1
        stz     bt_stop
        jsr     ceilings_by_tag
:       stz     ev_rtn
        jsr     tag_first
@loop:  jcs     @done
        jsr     is_busy
        jne     @next
        lda     #1
        sta     ev_rtn
        lda     #<T_MoveCeiling
        sta     nm_func
        lda     #>T_MoveCeiling
        sta     nm_func+1
        jsr     new_mover
        lda     ev_arg
        ldy     #MV_TYPE
        sta     (gpt),y
        lda     #CEILSPEED
        ldy     #MV_SPEED
        sta     (gpt),y
        lda     #$FF
        ldy     #MV_DIR
        sta     (gpt),y
        lda     tg_tag
        ldx     tg_tag+1
        ldy     #CE_TAG
        jsr     put16
        lda     ev_arg
        cmp     #fastCrushAndRaise
        beq     @fast
        cmp     #silentCrushAndRaise
        beq     @crush
        cmp     #crushAndRaise
        beq     @crush
        cmp     #lowerAndCrush
        beq     @lower
        cmp     #lowerToFloor
        beq     @lower
        cmp     #raiseToHighest
        beq     @raise
        bra     @next
@fast:  lda     #1
        ldy     #CE_CRUSH
        jsr     put8
        jsr     ev_ceil
        ldy     #CE_TOP
        jsr     put16
        jsr     ev_floor
        clc
        adc     #8
        bcc     :+
        inx
:       ldy     #CE_BOTTOM
        jsr     put16
        lda     #CEILSPEED * 2
        ldy     #MV_SPEED
        jsr     put8
        bra     @next
@crush: lda     #1
        ldy     #CE_CRUSH
        jsr     put8
        jsr     ev_ceil
        ldy     #CE_TOP
        jsr     put16
@lower: jsr     ev_floor
        ldy     ev_arg
        cpy     #lowerToFloor
        beq     :+
        clc
        adc     #8
        bcc     :+
        inx
:       ldy     #CE_BOTTOM
        jsr     put16
        bra     @next
@raise: jsr     highest_ceiling
        ldy     #CE_TOP
        jsr     put16
        lda     #1
        ldy     #MV_DIR
        jsr     put8
@next:  jsr     tag_next
        jmp     @loop
@done:  lda     ev_rtn
        rts

; ---- teleporters (p_telept.c) -------------------------------------------------------------------
; vanilla EV_Teleport(ev_line, ev_side, ev_thing)
ev_teleport:
        lda     ev_thing
        sta     gpt
        lda     ev_thing+1
        sta     gpt+1
        ldy     #MO_FLAGS+2             ; no missiles
        lda     (gpt),y
        and     #MF2_MISSILE
        jne     @no
        lda     ev_side                 ; the back side lets you out
        jne     @no
        jsr     ev_get_tag
        jsr     tag_first
@loop:  jcs     @no
        lda     ev_sec
        ldx     ev_sec+1
        jsr     _P_FindTeleportDest
        sta     gpt
        stx     gpt+1
        ora     gpt+1
        bne     @found
        jsr     tag_next
        bra     @loop
@found: ldy     #MO_X+3                 ; (a static's view: read it now)
        ldx     #3
:       lda     (gpt),y
        sta     tp_x,x
        dey
        dex
        bpl     :-
        ldy     #MO_Y+3
        ldx     #3
:       lda     (gpt),y
        sta     tp_y,x
        dey
        dex
        bpl     :-
        ldy     #MO_ANGLE
        lda     (gpt),y
        sta     tp_ang
        iny
        lda     (gpt),y
        sta     tp_ang+1
        jsr     thing_ptr               ; the old place
        ldy     #MO_X+3
        ldx     #3
:       lda     (gpt),y
        sta     tp_ox,x
        dey
        dex
        bpl     :-
        ldy     #MO_Y+3
        ldx     #3
:       lda     (gpt),y
        sta     tp_oy,x
        dey
        dex
        bpl     :-
        ldy     #MO_Z+3
        ldx     #3
:       lda     (gpt),y
        sta     tp_oz,x
        dey
        dex
        bpl     :-
        ; P_TeleportMove(thing, x, y)
        lda     ev_thing
        ldx     ev_thing+1
        jsr     pushax
        ldx     #tp_x - tp_x
        jsr     push32
        ldx     #tp_y - tp_x
        jsr     ld32
        jsr     _P_TeleportMove
        tax
        jeq     @no
        ; z = floorz; the player's view
        jsr     thing_ptr
        stz     tp_z
        stz     tp_z+1
        ldy     #MO_FLOORZ
        lda     (gpt),y
        sta     tp_z+2
        iny
        lda     (gpt),y
        sta     tp_z+3
        ldy     #MO_Z
        ldx     #0
:       lda     tp_z,x
        sta     (gpt),y
        iny
        inx
        cpx     #4
        bne     :-
        jsr     ev_is_player
        bne     :++
        clc                             ; viewz = z + viewheight
        ldx     #0
:       lda     tp_z,x
        adc     _player+PL_VIEWHEIGHT,x
        sta     _player+PL_VIEWZ,x
        inx
        txa
        eor     #4                      ; (keeps C)
        bne     :-
:       ; fog where it was
        ldx     #tp_ox - tp_x
        jsr     push32
        ldx     #tp_oy - tp_x
        jsr     push32
        ldx     #tp_oz - tp_x
        jsr     ld32
        jsr     spawn_fog
        ; fog 20 units in front of the destination
        lda     tp_ang+1                ; fa = angle >> 3
        sta     tmp4
        lda     tp_ang
        lsr     tmp4
        ror     a
        lsr     tmp4
        ror     a
        lsr     tmp4
        ror     a
        ldx     tmp4
        pha
        phx
        jsr     _fine_cosine
        jsr     times20                 ; tp_t = 20 * cos
        ldx     #0
        clc
:       lda     tp_x,x
        adc     tp_t,x
        sta     tp_ox,x                 ; (tp_ox: the fog's x)
        inx
        txa
        eor     #4
        bne     :-
        plx
        pla
        jsr     _fine_sine
        jsr     times20
        ldx     #0
        clc
:       lda     tp_y,x
        adc     tp_t,x
        sta     tp_oy,x
        inx
        txa
        eor     #4
        bne     :-
        ldx     #tp_ox - tp_x
        jsr     push32
        ldx     #tp_oy - tp_x
        jsr     push32
        ldx     #tp_z - tp_x
        jsr     ld32
        jsr     spawn_fog
        ; don't move for a bit; the destination's angle; still
        jsr     thing_ptr
        jsr     ev_is_player
        bne     :+
        lda     #18
        ldy     #MO_REACTIONTIME
        sta     (gpt),y
:       ldy     #MO_ANGLE
        lda     tp_ang
        sta     (gpt),y
        iny
        lda     tp_ang+1
        sta     (gpt),y
        lda     #0
        ldy     #MO_MOMX
:       sta     (gpt),y
        iny
        cpy     #MO_MOMZ+4
        bne     :-
        lda     #1
        rts
@no:    lda     #0
        rts
.assert MO_MOMY = MO_MOMX + 4 && MO_MOMZ = MO_MOMY + 4, error, "momentum fields"

thing_ptr:
        lda     ev_thing
        sta     gpt
        lda     ev_thing+1
        sta     gpt+1
        rts

; push the 32-bit tp_x + X on the C stack
push32: jsr     ld32
        jmp     pusheax

; A/X/sreg = the 32-bit tp_x + X
ld32:   lda     tp_x+3,x
        sta     sreg+1
        lda     tp_x+2,x
        sta     sreg
        lda     tp_x,x
        pha
        lda     tp_x+1,x
        tax
        pla
        rts

; tp_t = 20 * A/X/sreg (a fine sine: |v| <= 65536)
times20:
        sta     tp_t
        stx     tp_t+1
        lda     sreg
        sta     tp_t+2
        lda     sreg+1
        sta     tp_t+3
        asl     tp_t                    ; 4v
        rol     tp_t+1
        rol     tp_t+2
        rol     tp_t+3
        asl     tp_t
        rol     tp_t+1
        rol     tp_t+2
        rol     tp_t+3
        lda     tp_t                    ; + 16v
        sta     tmp1
        lda     tp_t+1
        sta     tmp2
        lda     tp_t+2
        sta     tmp3
        lda     tp_t+3
        sta     tmp4
        ldx     #2
:       asl     tmp1
        rol     tmp2
        rol     tmp3
        rol     tmp4
        dex
        bne     :-
        clc
        lda     tp_t
        adc     tmp1
        sta     tp_t
        lda     tp_t+1
        adc     tmp2
        sta     tp_t+1
        lda     tp_t+2
        adc     tmp3
        sta     tp_t+2
        lda     tp_t+3
        adc     tmp4
        sta     tp_t+3
        rts

; P_SpawnMobj(the two pushed, A/X/sreg, MT_TFOG) and its sound
spawn_fog:
        jsr     pusheax
        lda     #MT_TFOG
        jsr     _P_SpawnMobj
        jsr     pushax
        lda     #sfx_telept
        jmp     _S_StartSound

.endif ; DD_MAPDIR
