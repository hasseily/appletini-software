; Doom for the Appletini -- movement, collision, attacks, use, 6502
; (docs/DESIGN.md section 9).
;
; The assembly twin of p_map.c (the C is the reference, compiled on the
; host; read it for the why of each step): P_CheckPosition with its line
; and thing callbacks, P_TryMove, P_TeleportMove, P_ThingHeightClip,
; P_SlideMove, P_AimLineAttack, P_LineAttack, P_UseLines, P_RadiusAttack,
; P_ChangeSector, and the C globals of p_map (tmthing.., spechit,
; linetarget; tmbbox, tmx.. and the attack slopes are slots of W).
;
; Reentrancy is vanilla's: the tm* state is global and a callback that
; calls out (P_DamageMobj, P_TouchSpecialThing, P_CrossSpecialLine..) may
; run another P_TryMove inside (a woken monster's A_Chase), after which
; the outer one reads what the inner one left, as vanilla does. What must
; survive such a call is kept on the 6502 stack: the moving thing, the
; blockmap cell loop (iter_cells), the thing chain (things_iter).

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR


.import pols, bols, line_opening, set_pos, unset_pos, blockx, blocky
.import thing_xy, thing_radius, is_static, info_ptr, mul8, ret_w
.import lines_iter, things_iter, bl_func, bxl, bxh, byl, byh
.import path_traverse, pt_flags, pt_trav, aprox_dist, new_validcount
.import rpis, rp_x, rp_y, line_get, fx_sine, fx_cosine
.import w_mov, w_add, w_sub, w_neg, w_abs, w_zero, w_cmp, w_sign, w_ldi, w_fix
.import w_ldo, w_sto, w_ldp, w_fixl, w_mul, w_div, w_tst, w_add3, w_sub3
.import _P_Random, _P_SubRandom, _P_DamageMobj, _P_TouchSpecialThing, _P_StaticView
.import _P_Actor, _P_SetMobjState, _P_SpawnPuff, _P_SpawnBlood, _P_SpawnMobj
.import _P_RemoveMobj, _P_CrossSpecialLine, _P_ShootSpecialLine, _P_UseSpecialLine
.import _S_StartSound, _P_CheckSight, _P_SectorCeilingPic, _P_SectorBlockBox, _sec_bbox
.import _R_PointToAngle2, _P_StaticFlags
.import _skyflatnum, _leveltime, _player, _sec_floorh, _sec_ceilh, _mobjinfo, _st_tics
.import pushax, pusha, pusheax, incsp6, addysp

.export _P_CheckPosition, _P_TryMove, _P_TeleportMove, _P_ThingHeightClip
.export _P_SlideMove, _P_AimLineAttack, _P_LineAttack, _P_UseLines
.export _P_RadiusAttack, _P_ChangeSector
.export _tmthing, _tmflags, _floatok, _ceilingline, _spechit, _numspechit, _linetarget
.export try_move, check_pos, thing_flags0, thing_zh

.segment "BSS"
_tmthing:       .res 2
_tmflags:       .res 4
_floatok:       .res 1
_ceilingline:   .res 2
_spechit:       .res 2 * MAXSPECIALCROSS
_numspechit:    .res 1
_linetarget:    .res 2
shootthing:     .res 2
la_damage:      .res 2
slidemo:        .res 2
bestslideline:  .res 2
secondslideline: .res 2
hitcount:       .res 1
usething:       .res 2
bombsource:     .res 2
bombspot:       .res 2
bombdamage:     .res 2
crushchange:    .res 1
nofit:          .res 1
ct_f0:          .res 1              ; the callbacks' scratch (no call-out before use)
ct_type:        .res 1
ct_dmg:         .res 2
ct_in:          .res 2              ; the intercept of a traverser
ct_line:        .res 2
ct_side:        .res 1
hs_la:          .res 2              ; P_HitSlideLine's angles
hs_da:          .res 2
cs_box:         .res 4
os_x:           .res 2                  ; outside_sector
os_y:           .res 2
os_t:           .res 2
os_r:           .res 1
; iter_cells: the inputs, then the state it keeps on the stack around a cell
cp_xl:          .res 2
cp_xh:          .res 2
cp_yl:          .res 2
cp_yh:          .res 2
cp_state:
cp_o:           .res 2
cp_oh:          .res 2
cp_i:           .res 2
cp_il:          .res 2
cp_ih:          .res 2
cp_kind:        .res 1              ; bit 7: things (else lines), bit 6: y outer
cp_func:        .res 2
CP_SIZE         = * - cp_state

; W slots that p_map shares with pods (never live at the same time): a
; thing's z and height (thing_zh), the point of a puff
W_THZ   = W_PDX
W_THH   = W_PDY
W_HITX  = W_IDLX
W_HITY  = W_IDLY
W_HITZ  = W_IDLDX

CP_THINGS = $80
CP_YOUTER = $40

.segment "CODE"

; ---- small helpers ---------------------------------------------------------------
; A/X = 1 (true) / 0 (false)
ret_true:
        lda     #1
        ldx     #0
        rts
ret_false:
        lda     #0
        tax
        rts

; W[X] = FIX(A), A unsigned (a radius, a height)
fix_a:  ldy     #0
        jmp     w_fix

; C set iff W_T0 > 24 * FRACUNIT (signed)
t0_gt24:
        lda     W+W_T0+3
        bmi     @no
        bne     @yes
        lda     W+W_T0+2
        cmp     #24
        bcc     @no
        bne     @yes
        lda     W+W_T0+1
        ora     W+W_T0
        bne     @yes
@no:    clc
        rts
@yes:   sec
        rts

; A/X = the fine angle of the angle at (gmo)+MO_ANGLE (BAM16 >> 3)
mo_fine:
        ldy     #MO_ANGLE+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
; A/X >>= 3
shr3:   stx     tmp1
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        ldx     tmp1
        rts

; push W[X] on the C stack (a fixed_t argument)
push_w: jsr     ret_w
        jmp     pusheax

; ptr1 = &sec_floorh[A/X], ptr2 = &sec_ceilh[A/X]
sec_heights:
        asl     a
        sta     tmp1
        txa
        rol     a
        sta     tmp2
        clc
        lda     _sec_floorh
        adc     tmp1
        sta     ptr1
        lda     _sec_floorh+1
        adc     tmp2
        sta     ptr1+1
        clc
        lda     _sec_ceilh
        adc     tmp1
        sta     ptr2
        lda     _sec_ceilh+1
        adc     tmp2
        sta     ptr2+1
        rts

; W[X] = FIX(the int16 at (ptr1)) / (ptr2)
fix_p1: ldy     #1
        lda     (ptr1),y
        tay
        lda     (ptr1)
        jmp     w_fix
fix_p2: ldy     #1
        lda     (ptr2),y
        tay
        lda     (ptr2)
        jmp     w_fix

; Z set iff gmo is the player's mobj
gmo_is_player:
        lda     gmo
        cmp     _player+PL_MO
        bne     :+
        lda     gmo+1
        cmp     _player+PL_MO+1
:       rts

; ---- things as the callbacks see them ----------------------------------------------
; A = the low byte of the flags of the thing gth (MF_SPECIAL, MF_SOLID,
; MF_SHOOTABLE), a static's from its type less what death took
thing_flags0:
        lda     gth
        ldx     gth+1
        jsr     is_static
        bcs     @st
        ldy     #MO_FLAGS
        lda     (gth),y
        rts
@st:    ldy     #SO_TYPE
        lda     (gth),y
        jsr     info_ptr
        ldy     #MI_FLAGS
        lda     (ptr1),y
        sta     tmp1
        ldy     #SO_SFLAGS
        lda     (gth),y
        sta     tmp2
        and     #SF_CORPSE
        beq     :+
        lda     tmp1
        and     #<~(MF0_SOLID | MF0_SHOOTABLE)
        sta     tmp1
:       lda     tmp2
        and     #SF_GIBS
        beq     :+
        lda     tmp1
        and     #<~MF0_SOLID
        sta     tmp1
:       lda     tmp1
        rts

; A = the type of the thing gth
thing_type:
        lda     gth
        ldx     gth+1
        jsr     is_static
        ldy     #MO_TYPE
        bcc     :+
        ldy     #SO_TYPE
:       lda     (gth),y
        rts

; W_THZ, W_THH = the z and the height of the thing gth (P_ThingHeight)
thing_zh:
        lda     gth
        sta     gpt
        lda     gth+1
        sta     gpt+1
        ldx     gth+1
        lda     gth
        jsr     is_static
        bcs     @st
        ldx     #W_THZ
        ldy     #MO_Z
        jsr     w_ldp
        ldx     #W_THH
        ldy     #MO_HEIGHT
        jmp     w_ldp
@st:    ldy     #SO_Z
        lda     (gth),y
        pha
        iny
        lda     (gth),y
        tay
        pla
        ldx     #W_THZ
        jsr     w_fix
        ldy     #SO_TYPE
        lda     (gth),y
        jsr     info_ptr
        ldy     #MI_HEIGHT
        lda     (ptr1),y
        ldx     #W_THH
        jsr     fix_a
        ldy     #SO_SFLAGS
        lda     (gth),y
        and     #SF_GIBS
        beq     :+
        ldx     #W_THH
        jmp     w_zero
:       lda     (gth),y
        and     #SF_CORPSE
        beq     :+
        ldx     #2
@q:     lsr     W+W_THH+3
        ror     W+W_THH+2
        ror     W+W_THH+1
        ror     W+W_THH
        dex
        bne     @q
:       rts

; C set iff the thing gth is within blockdist = FIX(its radius) + W_TMRADIUS
; of (W_TMX, W_TMY) on both axes; W_THX, W_THY its position
within_blockdist:
        lda     gth
        ldx     gth+1
        jsr     thing_radius
        ldx     #W_T0
        jsr     fix_a
        ldx     #W_T0
        ldy     #W_TMRADIUS
        jsr     w_add
        jsr     thing_xy
        ldx     #W_T1
        ldy     #W_THX
        lda     #W_TMX
        jsr     w_sub3
        ldx     #W_T1
        jsr     w_abs
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_cmp
        bpl     @no
        ldx     #W_T1
        ldy     #W_THY
        lda     #W_TMY
        jsr     w_sub3
        ldx     #W_T1
        jsr     w_abs
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_cmp
        bpl     @no
        sec
        rts
@no:    clc
        rts

; Z set iff gth is the thing at A/X (compare)
gth_is:
        cmp     gth
        bne     :+
        cpx     gth+1
:       rts

; A/X = P_Actor(gth)
gth_actor:
        lda     gth
        ldx     gth+1
        jmp     _P_Actor

; ptr1 = &mobjinfo[tmthing->type]
tm_info:
        lda     _tmthing
        sta     ptr1
        lda     _tmthing+1
        sta     ptr1+1
        ldy     #MO_TYPE
        lda     (ptr1),y
        jmp     info_ptr

; ct_dmg = ((P_Random() % 8) + 1) * mobjinfo[tmthing->type].damage
missile_damage:
        jsr     _P_Random
        and     #7
        inc     a
        sta     ct_dmg
        jsr     tm_info
        ldy     #MI_DAMAGE
        lda     (ptr1),y
        ldx     ct_dmg
        jsr     mul8
        sta     ct_dmg
        stx     ct_dmg+1
        rts

; ---- the blockmap cell loop --------------------------------------------------------
; For each cell of cp_xl..cp_xh x cp_yl..cp_yh (int16 cell coordinates;
; x outer, or y outer with CP_YOUTER), lines_iter or things_iter
; (CP_THINGS) with the callback cp_func. A = 0 if a callback stopped it.
iter_cells:
        bit     cp_kind
        bvs     @yfirst
        ldx     #3
:       lda     cp_xl,x                 ; cp_o, cp_oh = cp_xl, cp_xh
        sta     cp_o,x
        lda     cp_yl,x                 ; cp_i (unused), cp_il, cp_ih
        sta     cp_il,x
        dex
        bpl     :-
        bra     @outer
@yfirst:
        ldx     #3
:       lda     cp_yl,x
        sta     cp_o,x
        lda     cp_xl,x
        sta     cp_il,x
        dex
        bpl     :-
@outer: sec
        lda     cp_oh
        sbc     cp_o
        lda     cp_oh+1
        sbc     cp_o+1
        bvc     :+
        eor     #$80
:       jmi     @done
        lda     cp_il
        sta     cp_i
        lda     cp_il+1
        sta     cp_i+1
@inner: sec
        lda     cp_ih
        sbc     cp_i
        lda     cp_ih+1
        sbc     cp_i+1
        bvc     :+
        eor     #$80
:       bmi     @nexto
        ldx     #cp_o - cp_state        ; outer -> bx (or by)
        ldy     #cp_i - cp_state
        bit     cp_kind
        bvc     :+
        ldx     #cp_i - cp_state
        ldy     #cp_o - cp_state
:       lda     cp_state,x
        sta     bxl
        lda     cp_state+1,x
        sta     bxh
        lda     cp_state,y
        sta     byl
        lda     cp_state+1,y
        sta     byh
        lda     cp_func
        sta     bl_func
        lda     cp_func+1
        sta     bl_func+1
        ldx     #CP_SIZE-1
:       lda     cp_state,x
        pha
        dex
        bpl     :-
        bit     cp_kind
        bmi     @th
        jsr     lines_iter
        bra     @back
@th:    jsr     things_iter
@back:  tay
        ldx     #0
:       pla
        sta     cp_state,x
        inx
        cpx     #CP_SIZE
        bne     :-
        tya
        beq     @stop
        inc     cp_i
        bne     @inner
        inc     cp_i+1
        bra     @inner
@nexto: inc     cp_o
        jne     @outer
        inc     cp_o+1
        jmp     @outer
@done:  lda     #1
        rts
@stop:  lda     #0
        rts

; cp_xl.. = the cells of the tm box grown by A map units
tm_cells:
        ldx     #W_T1
        jsr     fix_a
        ldx     #W_T0
        ldy     #W_TMLEFT
        lda     #W_T1
        jsr     w_sub3
        ldx     #W_T0
        jsr     blockx
        sta     cp_xl
        stx     cp_xl+1
        ldx     #W_T0
        ldy     #W_TMRIGHT
        lda     #W_T1
        jsr     w_add3
        ldx     #W_T0
        jsr     blockx
        sta     cp_xh
        stx     cp_xh+1
        ldx     #W_T0
        ldy     #W_TMBOTTOM
        lda     #W_T1
        jsr     w_sub3
        ldx     #W_T0
        jsr     blocky
        sta     cp_yl
        stx     cp_yl+1
        ldx     #W_T0
        ldy     #W_TMTOP
        lda     #W_T1
        jsr     w_add3
        ldx     #W_T0
        jsr     blocky
        sta     cp_yh
        stx     cp_yh+1
        rts

; ---- the tm state -------------------------------------------------------------------
; tmthing = gmo, tmflags, tmradius, the box around (W_TMX, W_TMY)
set_tm: lda     gmo
        sta     _tmthing
        lda     gmo+1
        sta     _tmthing+1
        ldy     #MO_FLAGS+3
:       lda     (gmo),y
        sta     _tmflags-MO_FLAGS,y
        dey
        cpy     #MO_FLAGS
        bcs     :-
        ldy     #MO_RADIUS
        lda     (gmo),y
        ldx     #W_TMRADIUS
        jsr     fix_a
tm_box: ldx     #W_TMTOP
        ldy     #W_TMY
        lda     #W_TMRADIUS
        jsr     w_add3
        ldx     #W_TMBOTTOM
        ldy     #W_TMY
        lda     #W_TMRADIUS
        jsr     w_sub3
        ldx     #W_TMRIGHT
        ldy     #W_TMX
        lda     #W_TMRADIUS
        jsr     w_add3
        ldx     #W_TMLEFT
        ldy     #W_TMX
        lda     #W_TMRADIUS
        jmp     w_sub3

; the sector under (W_TMX, W_TMY): tmfloorz = tmdropoffz, tmceilingz;
; no ceiling line
tm_sector:
        ldx     #7
:       lda     W+W_TMX,x               ; W_TMY follows W_TMX
        sta     rp_x,x                  ; rp_y follows rp_x
        dex
        bpl     :-
        jsr     rpis
        jsr     sec_heights
        lda     #$FF
        sta     _ceilingline
        sta     _ceilingline+1
        ldx     #W_TMFLOORZ
        jsr     fix_p1
        ldx     #W_TMDROPOFFZ
        jsr     fix_p1
        ldx     #W_TMCEILINGZ
        jmp     fix_p2
.assert W_TMY = W_TMX + 4, error, "tm_sector copies W_TMX and W_TMY at once"

; C args (mobj_t *thing, fixed_t x, fixed_t y) -> gmo, W_TMX, W_TMY
thing_xy_args:
        sta     W+W_TMY
        stx     W+W_TMY+1
        lda     sreg
        sta     W+W_TMY+2
        lda     sreg+1
        sta     W+W_TMY+3
        ldy     #3
:       lda     (sp),y
        sta     W+W_TMX,y
        dey
        bpl     :-
        ldy     #4
        lda     (sp),y
        sta     gmo
        iny
        lda     (sp),y
        sta     gmo+1
        jmp     incsp6

; ---- P_CheckPosition -----------------------------------------------------------------
; boolean P_CheckPosition(mobj_t *thing, fixed_t x, fixed_t y)
_P_CheckPosition:
        jsr     thing_xy_args
        jsr     set_tm
        jsr     check_pos
        ldx     #0
        rts

; check_pos: P_CheckPosition's work with the tm state set -> A (and Z)
check_pos:
        jsr     tm_sector
        jsr     new_validcount
        stz     _numspechit
        lda     _tmflags+1
        and     #MF1_NOCLIP
        bne     @true
        lda     #MAXRADIUS
        jsr     tm_cells
        lda     #CP_THINGS
        sta     cp_kind
        lda     #<pit_check_thing
        sta     cp_func
        lda     #>pit_check_thing
        sta     cp_func+1
        jsr     iter_cells
        beq     @rts
        lda     #0
        jsr     tm_cells
        stz     cp_kind
        lda     #<pit_check_line
        sta     cp_func
        lda     #>pit_check_line
        sta     cp_func+1
        jmp     iter_cells
@true:  lda     #1
@rts:   rts

pit_check_line:
        sta     gli
        stx     gli+1
        ldx     #W_T0
        ldy     #LI_BBOX + 2 * BOXLEFT
        jsr     w_fixl
        ldx     #W_TMRIGHT
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        jne     @true                   ; right <= line's left
        ldx     #W_T0
        ldy     #LI_BBOX + 2 * BOXRIGHT
        jsr     w_fixl
        ldx     #W_TMLEFT
        ldy     #W_T0
        jsr     w_cmp
        jpl     @true                   ; left >= line's right
        ldx     #W_T0
        ldy     #LI_BBOX + 2 * BOXBOTTOM
        jsr     w_fixl
        ldx     #W_TMTOP
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        jne     @true
        ldx     #W_T0
        ldy     #LI_BBOX + 2 * BOXTOP
        jsr     w_fixl
        ldx     #W_TMBOTTOM
        ldy     #W_T0
        jsr     w_cmp
        jpl     @true
        lda     #<(W + W_TMBBOX)
        sta     gpt
        lda     #>(W + W_TMBBOX)
        sta     gpt+1
        jsr     bols
        cmp     #$FF
        jne     @true
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        jeq     @false                  ; one sided
        lda     _tmflags+2
        and     #MF2_MISSILE
        bne     @open
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_BLOCKING
        bne     @false
        lda     _tmthing
        cmp     _player+PL_MO
        bne     @monster
        lda     _tmthing+1
        cmp     _player+PL_MO+1
        beq     @open
@monster:
        lda     (gli),y
        and     #ML_BLOCKMONSTERS
        bne     @false
@open:  jsr     line_opening
        ldx     #W_OPENTOP
        ldy     #W_TMCEILINGZ
        jsr     w_cmp
        bpl     :+
        ldx     #W_TMCEILINGZ
        ldy     #W_OPENTOP
        jsr     w_mov
        ldy     #LI_INDEX
        lda     (gli),y
        sta     _ceilingline
        iny
        lda     (gli),y
        sta     _ceilingline+1
:       ldx     #W_OPENBOTTOM
        ldy     #W_TMFLOORZ
        jsr     w_cmp
        cmp     #1
        bne     :+
        ldx     #W_TMFLOORZ
        ldy     #W_OPENBOTTOM
        jsr     w_mov
:       ldx     #W_LOWFLOOR
        ldy     #W_TMDROPOFFZ
        jsr     w_cmp
        bpl     :+
        ldx     #W_TMDROPOFFZ
        ldy     #W_LOWFLOOR
        jsr     w_mov
:       ldy     #LI_SPECIAL
        lda     (gli),y
        beq     @true
        lda     _numspechit
        cmp     #MAXSPECIALCROSS
        bcs     @true
        asl     a
        tax
        ldy     #LI_INDEX
        lda     (gli),y
        sta     _spechit,x
        iny
        lda     (gli),y
        sta     _spechit+1,x
        inc     _numspechit
@true:  jmp     ret_true
@false: jmp     ret_false

pit_check_thing:
        sta     gth
        stx     gth+1
        jsr     thing_flags0
        sta     ct_f0
        and     #MF0_SOLID | MF0_SPECIAL | MF0_SHOOTABLE
        jeq     @true
        jsr     within_blockdist
        jcc     @true
        lda     _tmthing
        ldx     _tmthing+1
        jsr     gth_is
        beq     @true
        jsr     thing_type
        sta     ct_type
        lda     _tmflags+3
        and     #MF3_SKULLFLY
        beq     @notskull
        ; a charging lost soul hits it and stops
        jsr     missile_damage
        jsr     gth_actor
        cpx     #0
        bne     :+
        cmp     #0
        beq     @stopskull
:       jsr     pushax
        lda     _tmthing
        ldx     _tmthing+1
        jsr     pushax
        jsr     pushax
        lda     ct_dmg
        ldx     ct_dmg+1
        jsr     _P_DamageMobj
@stopskull:
        lda     _tmthing
        sta     gmo
        lda     _tmthing+1
        sta     gmo+1
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #<~MF3_SKULLFLY
        sta     (gmo),y
        ldx     #W_T0
        jsr     w_zero
        ldx     #W_T0
        ldy     #MO_MOMX
        jsr     w_sto
        ldx     #W_T0
        ldy     #MO_MOMY
        jsr     w_sto
        ldx     #W_T0
        ldy     #MO_MOMZ
        jsr     w_sto
        jsr     tm_info
        lda     _tmthing
        ldx     _tmthing+1
        jsr     pushax
        ldy     #MI_SPAWNSTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     _P_SetMobjState
        jmp     ret_false
@true:  jmp     ret_true
@notskull:
        lda     _tmflags+2
        and     #MF2_MISSILE
        jeq     @notmissile
        ; a missile: over or under it passes
        jsr     thing_zh
        lda     _tmthing
        sta     gmo
        lda     _tmthing+1
        sta     gmo+1
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_THZ
        lda     #W_THH
        jsr     w_add3
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        cmp     #1
        beq     @true                   ; overhead
        ldx     #W_T1
        ldy     #MO_HEIGHT
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_add
        ldx     #W_T1
        ldy     #W_THZ
        jsr     w_cmp
        bmi     @true                   ; underneath
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     ptr1
        iny
        lda     (gmo),y
        sta     ptr1+1
        ora     ptr1
        beq     @hit
        ldy     #MO_TYPE
        lda     (ptr1),y
        cmp     ct_type
        bne     @hit
        lda     ptr1
        ldx     ptr1+1
        jsr     gth_is
        beq     @true                   ; its own shooter
        lda     ct_type
        cmp     #MT_PLAYER
        bne     @false                  ; no infighting within a species
@hit:   lda     ct_f0
        and     #MF0_SHOOTABLE
        bne     @damage
        lda     ct_f0
        and     #MF0_SOLID
        jeq     @true
@false: jmp     ret_false
@damage:
        jsr     missile_damage
        jsr     gth_actor
        cpx     #0
        bne     :+
        cmp     #0
        beq     @false
:       jsr     pushax
        lda     _tmthing
        ldx     _tmthing+1
        jsr     pushax
        sta     ptr1
        stx     ptr1+1
        ldy     #MO_TARGET+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     pushax
        lda     ct_dmg
        ldx     ct_dmg+1
        jsr     _P_DamageMobj
        jmp     ret_false
@notmissile:
        lda     ct_f0
        and     #MF0_SPECIAL
        beq     @solid
        lda     _tmflags+1
        and     #MF1_PICKUP
        beq     @solid
        lda     gth
        ldx     gth+1
        jsr     is_static
        bcc     :+
        jsr     _P_StaticView
:       jsr     pushax
        lda     _tmthing
        ldx     _tmthing+1
        jsr     _P_TouchSpecialThing
@solid: lda     ct_f0
        and     #MF0_SOLID
        bne     @false
        jmp     ret_true

; ---- P_TryMove --------------------------------------------------------------------------
; boolean P_TryMove(mobj_t *thing, fixed_t x, fixed_t y)
_P_TryMove:
        jsr     thing_xy_args
        jsr     try_move
        ldx     #0
        rts

; try_move: gmo to (W_TMX, W_TMY) -> A (and Z); keeps gmo
try_move:
        stz     _floatok
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     set_tm
        jsr     check_pos
        tay
        pla
        sta     gmo+1
        pla
        sta     gmo
        tya
        jeq     @false
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_NOCLIP
        bne     @move
        ; the gap must fit it
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        lda     #W_TMFLOORZ
        jsr     w_sub3
        ldx     #W_T1
        ldy     #MO_HEIGHT
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        jmi     @false
        lda     #1
        sta     _floatok
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_TELEPORT
        bne     @drop
        ldx     #W_T2
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        lda     #W_T2
        jsr     w_sub3
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        jmi     @false                  ; the top would hit the ceiling
        ldx     #W_T0
        ldy     #W_TMFLOORZ
        lda     #W_T2
        jsr     w_sub3
        jsr     t0_gt24
        jcs     @false                  ; too big a step up
@drop:  ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_DROPOFF | MF1_FLOAT
        bne     @move
        ldx     #W_T0
        ldy     #W_TMFLOORZ
        lda     #W_TMDROPOFFZ
        jsr     w_sub3
        jsr     t0_gt24
        jcs     @false                  ; don't stand over a dropoff
@move:  jsr     unset_pos
        ldx     #W_OLDX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_OLDY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     tm_floor_ceiling
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_sto
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_sto
        jsr     set_pos
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_TELEPORT | MF1_NOCLIP
        bne     @true
@spec:  lda     _numspechit
        beq     @true
        dec     _numspechit
        lda     _numspechit
        asl     a
        tax
        lda     _spechit,x
        sta     ct_line
        lda     _spechit+1,x
        sta     ct_line+1
        tax
        lda     ct_line
        jsr     line_get
        ldx     #W_PLX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_PLY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     pols
        sta     ct_side
        ldx     #W_PLX
        ldy     #W_OLDX
        jsr     w_mov
        ldx     #W_PLY
        ldy     #W_OLDY
        jsr     w_mov
        jsr     pols
        cmp     ct_side
        beq     @spec
        sta     ct_side                 ; the old side
        ldy     #LI_SPECIAL
        lda     (gli),y
        beq     @spec
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     ct_line
        ldx     ct_line+1
        jsr     pushax
        lda     ct_side
        jsr     pusha
        lda     gmo
        ldx     gmo+1
        jsr     _P_CrossSpecialLine
        pla
        sta     gmo+1
        pla
        sta     gmo
        bra     @spec
@true:  lda     #1
        rts
@false: lda     #0
        rts

; gmo's floorz, ceilingz = the tm ones (map units)
tm_floor_ceiling:
        ldy     #MO_FLOORZ
        lda     W+W_TMFLOORZ+2
        sta     (gmo),y
        iny
        lda     W+W_TMFLOORZ+3
        sta     (gmo),y
        ldy     #MO_CEILINGZ
        lda     W+W_TMCEILINGZ+2
        sta     (gmo),y
        iny
        lda     W+W_TMCEILINGZ+3
        sta     (gmo),y
        rts

; ---- P_TeleportMove ----------------------------------------------------------------------
; boolean P_TeleportMove(mobj_t *thing, fixed_t x, fixed_t y)
_P_TeleportMove:
        jsr     thing_xy_args
        jsr     set_tm
        jsr     tm_sector
        jsr     new_validcount
        stz     _numspechit
        lda     #MAXRADIUS
        jsr     tm_cells
        lda     #CP_THINGS
        sta     cp_kind
        lda     #<pit_stomp
        sta     cp_func
        lda     #>pit_stomp
        sta     cp_func+1
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     iter_cells
        tay
        pla
        sta     gmo+1
        pla
        sta     gmo
        tya
        bne     :+
        jmp     ret_false
:       jsr     unset_pos
        jsr     tm_floor_ceiling
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_sto
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_sto
        jsr     set_pos
        jmp     ret_true

pit_stomp:
        sta     gth
        stx     gth+1
        jsr     thing_flags0
        and     #MF0_SHOOTABLE
        beq     @true
        jsr     within_blockdist
        bcc     @true
        lda     _tmthing
        ldx     _tmthing+1
        jsr     gth_is
        beq     @true
        ; only the player telefrags (gamemap 30 is not in episode 1)
        lda     _tmthing
        cmp     _player+PL_MO
        bne     @false
        lda     _tmthing+1
        cmp     _player+PL_MO+1
        bne     @false
        jsr     gth_actor
        cpx     #0
        bne     :+
        cmp     #0
        beq     @true
:       jsr     pushax
        lda     _tmthing
        ldx     _tmthing+1
        jsr     pushax
        jsr     pushax
        lda     #<10000
        ldx     #>10000
        jsr     _P_DamageMobj
@true:  jmp     ret_true
@false: jmp     ret_false

; ---- height clipping ------------------------------------------------------------------------
; boolean P_ThingHeightClip(mobj_t *thing)
_P_ThingHeightClip:
        sta     gmo
        stx     gmo+1
height_clip:
        ; on its floor: z == FIX(floorz)
        ldy     #MO_Z
        lda     (gmo),y
        iny
        ora     (gmo),y
        bne     @off
        iny
        lda     (gmo),y
        ldy     #MO_FLOORZ
        cmp     (gmo),y
        bne     @off
        ldy     #MO_Z+3
        lda     (gmo),y
        ldy     #MO_FLOORZ+1
        cmp     (gmo),y
        bne     @off
        lda     #1
        bra     :+
@off:   lda     #0
:       pha                             ; onfloor
        lda     gmo
        pha
        lda     gmo+1
        pha
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     set_tm
        jsr     check_pos
        pla
        sta     gmo+1
        pla
        sta     gmo
        jsr     tm_floor_ceiling
        ldx     #W_T1
        ldy     #MO_HEIGHT
        jsr     w_ldo
        pla
        beq     @notfloor
        ldx     #W_TMFLOORZ
        ldy     #MO_Z
        jsr     w_sto
        bra     @fit
@notfloor:
        ; z + height > tmceilingz: z = tmceilingz - height
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_add
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        jsr     w_cmp
        cmp     #1
        bne     @fit
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        lda     #W_T1
        jsr     w_sub3
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_sto
@fit:   ; tmceilingz - tmfloorz >= height
fits_t1:
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        lda     #W_TMFLOORZ
        jsr     w_sub3
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        bmi     :+
        jmp     ret_true
:       jmp     ret_false

; the same for the static gth: on its floor unless it hangs (NOGRAVITY);
; keeps gth
static_height_clip:
        lda     gth
        pha
        lda     gth+1
        pha
        sta     _tmthing+1
        lda     gth
        sta     _tmthing
        ldx     gth+1
        jsr     _P_StaticFlags
        sta     _tmflags
        stx     _tmflags+1
        lda     sreg
        sta     _tmflags+2
        lda     sreg+1
        sta     _tmflags+3
        pla
        sta     gth+1
        pla
        sta     gth
        lda     gth
        ldx     gth+1
        jsr     thing_radius
        ldx     #W_TMRADIUS
        jsr     fix_a
        jsr     thing_xy
        ldx     #W_TMX
        ldy     #W_THX
        jsr     w_mov
        ldx     #W_TMY
        ldy     #W_THY
        jsr     w_mov
        jsr     tm_box
        lda     _tmflags+1
        pha                             ; NOGRAVITY is in byte 1
        lda     gth
        pha
        lda     gth+1
        pha
        jsr     check_pos
        pla
        sta     gth+1
        pla
        sta     gth
        jsr     thing_zh
        ldx     #W_T1
        ldy     #W_THH
        jsr     w_mov
        pla
        and     #MF1_NOGRAVITY
        bne     @hangs
        ldy     #SO_Z
        lda     W+W_TMFLOORZ+2
        sta     (gth),y
        iny
        lda     W+W_TMFLOORZ+3
        sta     (gth),y
        jmp     fits_t1
@hangs: ldx     #W_T0
        ldy     #W_THZ
        lda     #W_T1
        jsr     w_add3
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        jsr     w_cmp
        cmp     #1
        jne     fits_t1
        ldx     #W_T0
        ldy     #W_TMCEILINGZ
        lda     #W_T1
        jsr     w_sub3
        ldy     #SO_Z
        lda     W+W_T0+2
        sta     (gth),y
        iny
        lda     W+W_T0+3
        sta     (gth),y
        jmp     fits_t1

; ---- sliding ---------------------------------------------------------------------------------
; void P_SlideMove(mobj_t *mo)
_P_SlideMove:
        sta     slidemo
        stx     slidemo+1
        stz     hitcount
@retry: inc     hitcount
        lda     hitcount
        cmp     #3
        jeq     @stairstep
        jsr     gmo_slide
        ldy     #MO_RADIUS
        lda     (gmo),y
        ldx     #W_T0
        jsr     fix_a
        ; the leading and trailing corners
        ldx     #W_T1
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_T2
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T1
        jsr     w_sign
        cmp     #1
        bne     @xneg
        ldx     #W_LEADX
        ldy     #W_T2
        lda     #W_T0
        jsr     w_add3
        ldx     #W_TRAILX
        ldy     #W_T2
        lda     #W_T0
        jsr     w_sub3
        bra     @y
@xneg:  ldx     #W_LEADX
        ldy     #W_T2
        lda     #W_T0
        jsr     w_sub3
        ldx     #W_TRAILX
        ldy     #W_T2
        lda     #W_T0
        jsr     w_add3
@y:     ldx     #W_T1
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_T2
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T1
        jsr     w_sign
        cmp     #1
        bne     @yneg
        ldx     #W_LEADY
        ldy     #W_T2
        lda     #W_T0
        jsr     w_add3
        ldx     #W_TRAILY
        ldy     #W_T2
        lda     #W_T0
        jsr     w_sub3
        bra     @trace
@yneg:  ldx     #W_LEADY
        ldy     #W_T2
        lda     #W_T0
        jsr     w_sub3
        ldx     #W_TRAILY
        ldy     #W_T2
        lda     #W_T0
        jsr     w_add3
@trace: ldx     #W_BESTSLIDE
        jsr     w_ldi
        .dword  $10001
        ldx     #W_LEADX
        ldy     #W_LEADY
        jsr     slide_trace
        ldx     #W_TRAILX
        ldy     #W_LEADY
        jsr     slide_trace
        ldx     #W_LEADX
        ldy     #W_TRAILY
        jsr     slide_trace
        lda     W+W_BESTSLIDE+3
        bne     @found
        lda     W+W_BESTSLIDE+2
        cmp     #1
        bne     @found
        lda     W+W_BESTSLIDE+1
        bne     @found
        lda     W+W_BESTSLIDE
        cmp     #1
        jeq     @stairstep              ; nothing hit: FRACUNIT + 1
@found: ; move up to the wall
        ldx     #W_T0
        jsr     w_ldi
        .dword  $800
        ldx     #W_BESTSLIDE
        ldy     #W_T0
        jsr     w_sub
        ldx     #W_BESTSLIDE
        jsr     w_sign
        cmp     #1
        bne     @along
        jsr     gmo_slide
        ldx     #W_T1
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_BESTSLIDE
        jsr     w_mul
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMX
        ldy     #W_FR
        jsr     w_add
        ldx     #W_T1
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_BESTSLIDE
        jsr     w_mul
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #W_FR
        jsr     w_add
        jsr     try_move
        jeq     @stairstep
@along: ; the rest of the move along the wall
        ldx     #W_T0
        jsr     w_ldi
        .dword  $800
        ldx     #W_BESTSLIDE
        ldy     #W_T0
        jsr     w_add
        ldx     #W_T0
        jsr     w_ldi
        .dword  $10000
        ldx     #W_T0
        ldy     #W_BESTSLIDE
        jsr     w_sub
        ldx     #W_BESTSLIDE
        ldy     #W_T0
        jsr     w_mov
        lda     W+W_BESTSLIDE+3
        jmi     @rts
        bne     @clamp
        lda     W+W_BESTSLIDE+2
        cmp     #1
        bcc     @low
        bne     @clamp
        lda     W+W_BESTSLIDE+1
        ora     W+W_BESTSLIDE
        beq     @low
@clamp: ldx     #W_BESTSLIDE
        jsr     w_ldi
        .dword  $10000
@low:   ldx     #W_BESTSLIDE
        jsr     w_tst
        beq     @rts
        jsr     gmo_slide
        ldx     #W_T1
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_BESTSLIDE
        jsr     w_mul
        ldx     #W_TMXMOVE
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T1
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_BESTSLIDE
        jsr     w_mul
        ldx     #W_TMYMOVE
        ldy     #W_FR
        jsr     w_mov
        lda     bestslideline
        ldx     bestslideline+1
        jsr     line_get
        jsr     hit_slide_line
        jsr     gmo_slide
        ldx     #W_TMXMOVE
        ldy     #MO_MOMX
        jsr     w_sto
        ldx     #W_TMYMOVE
        ldy     #MO_MOMY
        jsr     w_sto
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMX
        ldy     #W_TMXMOVE
        jsr     w_add
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #W_TMYMOVE
        jsr     w_add
        jsr     try_move
        jeq     @retry
@rts:   rts
@stairstep:
        ; (x, y + momy), else (x + momx, y)
        jsr     gmo_slide
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #W_T0
        jsr     w_add
        jsr     try_move
        bne     @rts
        jsr     gmo_slide
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_TMX
        ldy     #W_T0
        jsr     w_add
        jmp     try_move

gmo_slide:
        lda     slidemo
        sta     gmo
        lda     slidemo+1
        sta     gmo+1
        rts

; P_PathTraverse(W[X], W[Y], W[X] + momx, W[Y] + momy, PT_ADDLINES, ptr_slide)
slide_trace:
        phy
        ldy     #W_PTX1
        jsr     w_movr
        ply
        ldx     #W_PTY1
        jsr     w_mov
        jsr     gmo_slide
        ldx     #W_PTX2
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_PTX2
        ldy     #W_PTX1
        jsr     w_add
        ldx     #W_PTY2
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_PTY2
        ldy     #W_PTY1
        jsr     w_add
        lda     #PT_ADDLINES
        sta     pt_flags
        lda     #<ptr_slide
        sta     pt_trav
        lda     #>ptr_slide
        sta     pt_trav+1
        jmp     path_traverse

; W[Y] = W[X] (w_mov the other way round)
w_movr: phx
        phy
        plx
        ply
        jmp     w_mov

; ct_in = the intercept A/X; W_T4 = its frac
get_in: sta     ct_in
        stx     ct_in+1
        sta     gpt
        stx     gpt+1
        ldx     #W_T4
        ldy     #IN_FRAC
        jmp     w_ldp

; A/X = the line of the intercept gpt, fetched (gli); ct_line = its index
in_line:
        ldy     #IN_LINE
        lda     (gpt),y
        sta     ct_line
        iny
        lda     (gpt),y
        sta     ct_line+1
        tax
        lda     ct_line
        jmp     line_get

ptr_slide:
        jsr     get_in
        ldy     #IN_ISALINE
        lda     (gpt),y
        beq     @true
        jsr     in_line
        jsr     gmo_slide
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        bne     @two
        ldx     #W_PLX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_PLY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     pols
        bne     @true                   ; don't hit the back side
        bra     @block
@two:   jsr     line_opening
        ldx     #W_T0
        ldy     #MO_HEIGHT
        jsr     w_ldo
        ldx     #W_OPENRANGE
        ldy     #W_T0
        jsr     w_cmp
        bmi     @block                  ; doesn't fit
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T2
        ldy     #W_OPENTOP
        lda     #W_T1
        jsr     w_sub3
        ldx     #W_T2
        ldy     #W_T0
        jsr     w_cmp
        bmi     @block                  ; the top is too low
        ldx     #W_T0
        ldy     #W_OPENBOTTOM
        lda     #W_T1
        jsr     w_sub3
        jsr     t0_gt24
        bcs     @block                  ; too big a step up
@true:  jmp     ret_true
@block: ldx     #W_T4
        ldy     #W_BESTSLIDE
        jsr     w_cmp
        bpl     :+
        ldx     #W_SECONDSLIDE
        ldy     #W_BESTSLIDE
        jsr     w_mov
        lda     bestslideline
        sta     secondslideline
        lda     bestslideline+1
        sta     secondslideline+1
        ldx     #W_BESTSLIDE
        ldy     #W_T4
        jsr     w_mov
        lda     ct_line
        sta     bestslideline
        lda     ct_line+1
        sta     bestslideline+1
:       jmp     ret_false

; A/X = R_PointToAngle2(0, 0, W[X], W[Y])
angle_of:
        phy
        phx
        lda     #0
        tax
        stz     sreg
        stz     sreg+1
        jsr     pusheax
        jsr     pusheax
        plx
        jsr     push_w
        plx
        jsr     ret_w
        jmp     _R_PointToAngle2

; the move W_TMXMOVE/W_TMYMOVE along the line gli
hit_slide_line:
        ldy     #LI_SLOPETYPE
        lda     (gli),y
        bne     :+
        ldx     #W_TMYMOVE
        jmp     w_zero
:       cmp     #ST_VERTICAL
        bne     :+
        ldx     #W_TMXMOVE
        jmp     w_zero
:       jsr     gmo_slide
        ldx     #W_PLX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_PLY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     pols
        sta     ct_side
        ldx     #W_T0
        ldy     #LI_DX
        jsr     w_fixl
        ldx     #W_T1
        ldy     #LI_DY
        jsr     w_fixl
        ldx     #W_T0
        ldy     #W_T1
        jsr     angle_of
        sta     hs_la
        lda     ct_side
        beq     :+
        txa
        eor     #>ANG180
        tax
:       stx     hs_la+1
        ldx     #W_TMXMOVE
        ldy     #W_TMYMOVE
        jsr     angle_of
        ; deltaangle = moveangle - lineangle, + ANG180 if > ANG180
        sec
        sbc     hs_la
        sta     hs_da
        txa
        sbc     hs_la+1
        sta     hs_da+1
        cmp     #>ANG180
        bcc     @small
        bne     @big
        lda     hs_da
        beq     @small
@big:   lda     hs_da+1
        eor     #>ANG180
        sta     hs_da+1
@small: ; movelen = P_AproxDistance(tmxmove, tmymove)
        ldx     #W_T0
        ldy     #W_TMXMOVE
        jsr     w_mov
        ldx     #W_T1
        ldy     #W_TMYMOVE
        jsr     w_mov
        jsr     aprox_dist
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mov
        ; newlen = FixedMul(movelen, cos(delta))
        lda     hs_da
        ldx     hs_da+1
        jsr     shr3
        jsr     fx_cosine
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mov
        lda     hs_la
        ldx     hs_la+1
        jsr     shr3
        jsr     fx_cosine
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_TMXMOVE
        ldy     #W_FR
        jsr     w_mov
        lda     hs_la
        ldx     hs_la+1
        jsr     shr3
        jsr     fx_sine
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_TMYMOVE
        ldy     #W_FR
        jmp     w_mov

; ---- aiming and shooting -----------------------------------------------------------------------
; the trace of an attack from gmo: shootthing, W_SHOOTZ, W_ATTACKRANGE
; (from W_T3), W_PTX1.. to distance along the fine angle A/X
attack_setup:
        sta     fine_lo
        stx     fine_hi
        lda     gmo
        sta     shootthing
        lda     gmo+1
        sta     shootthing+1
        ldx     #W_ATTACKRANGE
        ldy     #W_T3
        jsr     w_mov
        ; x2 = x + (distance >> FRACBITS) * cos: FixedMul of the whole part
        stz     W+W_T3
        stz     W+W_T3+1
        lda     fine_lo
        ldx     fine_hi
        jsr     fx_cosine
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_PTX1
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_PTX2
        ldy     #W_PTX1
        lda     #W_FR
        jsr     w_add3
        lda     fine_lo
        ldx     fine_hi
        jsr     fx_sine
        ldx     #W_T3
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_PTY1
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_PTY2
        ldy     #W_PTY1
        lda     #W_FR
        jsr     w_add3
        ; shootz = z + (height >> 1) + 8 * FRACUNIT
        ldx     #W_SHOOTZ
        ldy     #MO_HEIGHT
        jsr     w_ldo
        lda     W+W_SHOOTZ+3
        cmp     #$80
        ror     W+W_SHOOTZ+3
        ror     W+W_SHOOTZ+2
        ror     W+W_SHOOTZ+1
        ror     W+W_SHOOTZ
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_SHOOTZ
        ldy     #W_T0
        jsr     w_add
        clc
        lda     W+W_SHOOTZ+2
        adc     #8
        sta     W+W_SHOOTZ+2
        bcc     :+
        inc     W+W_SHOOTZ+3
:       lda     #PT_ADDLINES | PT_ADDTHINGS
        sta     pt_flags
        rts

.segment "BSS"
fine_lo:    .res 1
fine_hi:    .res 1
.segment "CODE"

; C args (mobj_t *t1, angle_t angle, ...): gmo, A/X = the fine angle
; Y = the offset of angle on the C stack
angle_arg:
        lda     (sp),y
        pha
        iny
        lda     (sp),y
        tax
        iny
        lda     (sp),y
        sta     gmo
        iny
        lda     (sp),y
        sta     gmo+1
        pla
        jmp     shr3

; fixed_t P_AimLineAttack(mobj_t *t1, angle_t angle, fixed_t distance)
_P_AimLineAttack:
        sta     W+W_T3
        stx     W+W_T3+1
        lda     sreg
        sta     W+W_T3+2
        lda     sreg+1
        sta     W+W_T3+3
        ldy     #0
        jsr     angle_arg
        pha
        phx
        ldy     #4
        jsr     addysp
        plx
        pla
        jsr     attack_setup
        ldx     #W_TOPSLOPE
        jsr     w_ldi
        .dword  100 * $10000 / 160
        ldx     #W_BOTTOMSLOPE
        jsr     w_ldi
        .dword  $FFFF6000               ; -100 * FRACUNIT / 160
        stz     _linetarget
        stz     _linetarget+1
        lda     #<ptr_aim
        sta     pt_trav
        lda     #>ptr_aim
        sta     pt_trav+1
        jsr     path_traverse
        lda     _linetarget
        ldx     _linetarget+1
        bne     :+
        cmp     #0
        bne     :+
        ldx     #W_T0
        jsr     w_zero
        jmp     ret_w
:       jsr     is_static
        bcc     :+
        jsr     _P_StaticView           ; a static target is given as its view
        sta     _linetarget
        stx     _linetarget+1
:       ldx     #W_AIMSLOPE
        jmp     ret_w

; T3 = dist = FixedMul(attackrange, in->frac)
in_dist:
        ldx     #W_ATTACKRANGE
        ldy     #W_T4
        jsr     w_mul
        ldx     #W_T3
        ldy     #W_FR
        jmp     w_mov

; W_FR = FixedDiv(W[X] - shootz, dist)
slope_to:
        ldy     #W_SHOOTZ
        jsr     w_sub
        ldy     #W_T3
        jmp     w_div

; the flags of a line gli: is the floor (A = 0) / ceiling (A = 2) of both
; its sectors the same? Z set if so (never for a one-sided line)
same_heights:
        tax
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        beq     @differ
        phx
        ldy     #LI_FRONTSECTOR+1
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        jsr     sec_heights
        lda     ptr1
        sta     ptr3
        lda     ptr1+1
        sta     ptr3+1
        lda     ptr2
        sta     ptr4
        lda     ptr2+1
        sta     ptr4+1
        ldy     #LI_BACKSECTOR+1
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        jsr     sec_heights
        pla
        beq     :+
        lda     ptr2                    ; the ceilings
        sta     ptr1
        lda     ptr2+1
        sta     ptr1+1
        lda     ptr4
        sta     ptr3
        lda     ptr4+1
        sta     ptr3+1
:       lda     (ptr1)
        cmp     (ptr3)
        bne     @rts
        ldy     #1
        lda     (ptr1),y
        cmp     (ptr3),y
@rts:   rts
@differ:
        lda     #1                      ; Z clear
        rts

ptr_aim:
        jsr     get_in
        ldy     #IN_ISALINE
        lda     (gpt),y
        jeq     @thing
        jsr     in_line
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @false
        jsr     line_opening
        ldx     #W_OPENBOTTOM
        ldy     #W_OPENTOP
        jsr     w_cmp
        bpl     @false
        jsr     in_dist
        lda     #0
        jsr     same_heights
        beq     :+
        ldx     #W_T0
        ldy     #W_OPENBOTTOM
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        cmp     #1
        bne     :+
        ldx     #W_BOTTOMSLOPE
        ldy     #W_FR
        jsr     w_mov
:       lda     #2
        jsr     same_heights
        beq     :+
        ldx     #W_T0
        ldy     #W_OPENTOP
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_TOPSLOPE
        jsr     w_cmp
        bpl     :+
        ldx     #W_TOPSLOPE
        ldy     #W_FR
        jsr     w_mov
:       ldx     #W_TOPSLOPE
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        cmp     #1
        bne     @false
@true:  jmp     ret_true
@false: jmp     ret_false
@thing: jsr     in_thing
        bcc     @true
        ; thingtopslope -> T1
        ldx     #W_T0
        ldy     #W_THZ
        lda     #W_THH
        jsr     w_add3
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_T1
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T1
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        bmi     @true                   ; shot over the thing
        ldx     #W_T0
        ldy     #W_THZ
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_T2
        ldy     #W_FR
        jsr     w_mov
        ldx     #W_T2
        ldy     #W_TOPSLOPE
        jsr     w_cmp
        cmp     #1
        beq     @true                   ; shot under the thing
        ; the part of the thing in view: aimslope its middle
        ldx     #W_T1
        ldy     #W_TOPSLOPE
        jsr     w_cmp
        cmp     #1
        bne     :+
        ldx     #W_T1
        ldy     #W_TOPSLOPE
        jsr     w_mov
:       ldx     #W_T2
        ldy     #W_BOTTOMSLOPE
        jsr     w_cmp
        bpl     :+
        ldx     #W_T2
        ldy     #W_BOTTOMSLOPE
        jsr     w_mov
:       ldx     #W_AIMSLOPE
        ldy     #W_T1
        lda     #W_T2
        jsr     w_add3
        ; / 2, rounding towards zero as C does
        lda     W+W_AIMSLOPE+3
        bpl     :+
        inc     W+W_AIMSLOPE
        bne     :+
        inc     W+W_AIMSLOPE+1
        bne     :+
        inc     W+W_AIMSLOPE+2
        bne     :+
        inc     W+W_AIMSLOPE+3
:       lda     W+W_AIMSLOPE+3
        cmp     #$80
        ror     W+W_AIMSLOPE+3
        ror     W+W_AIMSLOPE+2
        ror     W+W_AIMSLOPE+1
        ror     W+W_AIMSLOPE
        lda     gth
        sta     _linetarget
        lda     gth+1
        sta     _linetarget+1
        jmp     ret_false

; the thing of the intercept gpt -> gth; C clear if it is not a target
; (the shooter, not shootable); else T3 = dist, W_THZ, W_THH
in_thing:
        ldy     #IN_THING
        lda     (gpt),y
        sta     gth
        iny
        lda     (gpt),y
        sta     gth+1
        tax
        lda     gth
        cmp     shootthing
        bne     :+
        cpx     shootthing+1
        beq     @no
:       jsr     thing_flags0
        and     #MF0_SHOOTABLE
        beq     @no
        jsr     in_dist
        jsr     thing_zh
        sec
        rts
@no:    clc
        rts

; the point frac = in->frac - FixedDiv(A * FRACUNIT, attackrange) along
; the trace -> W_HITX, W_HITY, W_HITZ
hit_point:
        ldx     #W_T0
        jsr     fix_a
        ldx     #W_T0
        ldy     #W_ATTACKRANGE
        jsr     w_div
        ldx     #W_T4
        ldy     #W_FR
        jsr     w_sub                   ; T4 = frac
        ldx     #W_TRDX
        ldy     #W_T4
        jsr     w_mul
        ldx     #W_HITX
        ldy     #W_TRX
        lda     #W_FR
        jsr     w_add3
        ldx     #W_TRDY
        ldy     #W_T4
        jsr     w_mul
        ldx     #W_HITY
        ldy     #W_TRY
        lda     #W_FR
        jsr     w_add3
        ldx     #W_T4
        ldy     #W_ATTACKRANGE
        jsr     w_mul
        ldx     #W_AIMSLOPE             ; FixedMul(aimslope, that)
        ldy     #W_FR
        jsr     w_mul
        ldx     #W_HITZ
        ldy     #W_SHOOTZ
        lda     #W_FR
        jmp     w_add3

; P_SpawnPuff(hit point)
spawn_puff:
        ldx     #W_HITX
        jsr     push_w
        ldx     #W_HITY
        jsr     push_w
        ldx     #W_HITZ
        jsr     ret_w
        jmp     _P_SpawnPuff

; Z set iff the sector at (gli)+Y has the sky as its ceiling
sky_ceiling:
        lda     (gli),y
        pha
        iny
        lda     (gli),y
        tax
        pla
        jsr     _P_SectorCeilingPic
        cmp     _skyflatnum
        bne     :+
        cpx     _skyflatnum+1
:       rts

ptr_shoot:
        jsr     get_in
        ldy     #IN_ISALINE
        lda     (gpt),y
        jeq     @thing
        jsr     in_line
        ldy     #LI_SPECIAL
        lda     (gli),y
        beq     :+
        lda     shootthing
        ldx     shootthing+1
        jsr     pushax
        lda     ct_line
        ldx     ct_line+1
        jsr     _P_ShootSpecialLine
        lda     ct_line
        ldx     ct_line+1
        jsr     line_get
:       ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @hitline
        jsr     line_opening
        jsr     in_dist
        lda     #0
        jsr     same_heights
        beq     :+
        ldx     #W_T0
        ldy     #W_OPENBOTTOM
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_AIMSLOPE
        jsr     w_cmp
        cmp     #1
        beq     @hitline
:       lda     #2
        jsr     same_heights
        beq     @through
        ldx     #W_T0
        ldy     #W_OPENTOP
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_AIMSLOPE
        jsr     w_cmp
        bmi     @hitline
@through:
        jmp     ret_true
@hitline:
        lda     #4
        jsr     hit_point
        ; don't shoot the sky
        ldy     #LI_FRONTSECTOR
        jsr     sky_ceiling
        bne     @puff
        ldy     #LI_FRONTSECTOR+1
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        jsr     sec_heights
        ldx     #W_T0
        jsr     fix_p2
        ldx     #W_HITZ
        ldy     #W_T0
        jsr     w_cmp
        cmp     #1
        beq     @false
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        beq     @puff
        ldy     #LI_BACKSECTOR
        jsr     sky_ceiling
        beq     @false
@puff:  jsr     spawn_puff
@false: jmp     ret_false
@thing: jsr     in_thing
        bcs     :+
        jmp     ret_true
:       ; thingtopslope < aimslope: over it
        ldx     #W_T0
        ldy     #W_THZ
        lda     #W_THH
        jsr     w_add3
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_AIMSLOPE
        jsr     w_cmp
        bpl     :+
        jmp     ret_true
:       ldx     #W_T0
        ldy     #W_THZ
        jsr     w_mov
        ldx     #W_T0
        jsr     slope_to
        ldx     #W_FR
        ldy     #W_AIMSLOPE
        jsr     w_cmp
        cmp     #1
        bne     :+
        jmp     ret_true                ; under it
:       lda     #10
        jsr     hit_point
        jsr     gth_actor
        sta     gth
        stx     gth+1
        ora     gth+1
        beq     @false
        lda     gth
        pha
        lda     gth+1
        pha
        ldy     #MO_FLAGS+2
        lda     (gth),y
        and     #MF2_NOBLOOD
        beq     @blood
        jsr     spawn_puff
        bra     @damage
@blood: ldx     #W_HITX
        jsr     push_w
        ldx     #W_HITY
        jsr     push_w
        ldx     #W_HITZ
        jsr     push_w
        lda     la_damage
        ldx     la_damage+1
        jsr     _P_SpawnBlood
@damage:
        plx
        pla
        ldy     la_damage
        bne     :+
        ldy     la_damage+1
        jeq     @false
:       jsr     pushax
        lda     shootthing
        ldx     shootthing+1
        jsr     pushax
        jsr     pushax
        lda     la_damage
        ldx     la_damage+1
        jsr     _P_DamageMobj
        jmp     ret_false

; void P_LineAttack(mobj_t *t1, angle_t angle, fixed_t distance, fixed_t slope,
;                   int16_t damage)
; C stack: +0 slope, +4 distance, +8 angle, +10 t1
_P_LineAttack:
        sta     la_damage
        stx     la_damage+1
        ldy     #3
:       lda     (sp),y
        sta     W+W_AIMSLOPE,y
        dey
        bpl     :-
        ldy     #7
        ldx     #3
:       lda     (sp),y
        sta     W+W_T3,x
        dey
        dex
        bpl     :-
        ldy     #8
        jsr     angle_arg
        pha
        phx
        ldy     #12
        jsr     addysp
        plx
        pla
        jsr     attack_setup
        lda     #<ptr_shoot
        sta     pt_trav
        lda     #>ptr_shoot
        sta     pt_trav+1
        jmp     path_traverse

; ---- use --------------------------------------------------------------------------------------------
; void P_UseLines(player_t *player)
_P_UseLines:
        sta     ptr1
        stx     ptr1+1
        ldy     #PL_MO
        lda     (ptr1),y
        sta     gmo
        sta     usething
        iny
        lda     (ptr1),y
        sta     gmo+1
        sta     usething+1
        ; to USERANGE (64 units) along the angle
        ldx     #W_T3
        jsr     w_ldi
        .dword  64 * $10000
        jsr     mo_fine
        jsr     attack_setup            ; (shootthing, shootz, attackrange unused)
        lda     #PT_ADDLINES
        sta     pt_flags
        lda     #<ptr_use
        sta     pt_trav
        lda     #>ptr_use
        sta     pt_trav+1
        jmp     path_traverse

ptr_use:
        jsr     get_in
        jsr     in_line
        ldy     #LI_SPECIAL
        lda     (gli),y
        bne     @special
        jsr     line_opening
        ldx     #W_OPENRANGE
        jsr     w_sign
        cmp     #1
        beq     @true
        lda     usething
        ldx     usething+1
        jsr     pushax
        lda     #sfx_noway
        jsr     _S_StartSound
        jmp     ret_false               ; can't use through a wall
@true:  jmp     ret_true
@special:
        lda     usething
        sta     gmo
        lda     usething+1
        sta     gmo+1
        ldx     #W_PLX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_PLY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     pols
        sta     ct_side
        lda     usething
        ldx     usething+1
        jsr     pushax
        lda     ct_line
        ldx     ct_line+1
        jsr     pushax
        lda     ct_side
        jsr     _P_UseSpecialLine
        jmp     ret_false

; ---- radius attack ------------------------------------------------------------------------------------
; void P_RadiusAttack(mobj_t *spot, mobj_t *source, int16_t damage)
_P_RadiusAttack:
        sta     bombdamage
        stx     bombdamage+1
        ldy     #0
        lda     (sp),y
        sta     bombsource
        iny
        lda     (sp),y
        sta     bombsource+1
        iny
        lda     (sp),y
        sta     bombspot
        sta     gmo
        iny
        lda     (sp),y
        sta     bombspot+1
        sta     gmo+1
        ldy     #4
        jsr     addysp
        ; the cells within damage + MAXRADIUS of the spot, y outer
        clc
        lda     bombdamage
        adc     #MAXRADIUS
        tax
        lda     bombdamage+1
        adc     #0
        tay
        txa
        ldx     #W_TMRADIUS
        jsr     w_fix
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     tm_box
        lda     #0
        jsr     tm_cells
        lda     #CP_THINGS | CP_YOUTER
        sta     cp_kind
        lda     #<pit_radius
        sta     cp_func
        lda     #>pit_radius
        sta     cp_func+1
        jmp     iter_cells

pit_radius:
        sta     gth
        stx     gth+1
        jsr     thing_flags0
        and     #MF0_SHOOTABLE
        jeq     @true
        ; dist = max(|dx|, |dy|) - radius, in map units, at least 0
        jsr     thing_xy
        lda     bombspot
        sta     gmo
        lda     bombspot+1
        sta     gmo+1
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_THX
        lda     #W_T0
        jsr     w_sub3
        ldx     #W_T1
        jsr     w_abs
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T2
        ldy     #W_THY
        lda     #W_T0
        jsr     w_sub3
        ldx     #W_T2
        jsr     w_abs
        ldx     #W_T1
        ldy     #W_T2
        jsr     w_cmp
        cmp     #1
        beq     :+
        ldx     #W_T1
        ldy     #W_T2
        jsr     w_mov
:       lda     gth
        ldx     gth+1
        jsr     thing_radius
        ldx     #W_T0
        jsr     fix_a
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_sub
        lda     W+W_T1+3
        bpl     :+
        stz     W+W_T1+2
        stz     W+W_T1+3
:       ; dist >= bombdamage: out of reach
        lda     W+W_T1+2
        cmp     bombdamage
        lda     W+W_T1+3
        sbc     bombdamage+1
        bvc     :+
        eor     #$80
:       bpl     @true
        sec
        lda     bombdamage
        sbc     W+W_T1+2
        sta     ct_dmg
        lda     bombdamage+1
        sbc     W+W_T1+3
        sta     ct_dmg+1
        jsr     gth_actor
        sta     gth
        stx     gth+1
        ora     gth+1
        beq     @true
        lda     ct_dmg+1
        pha
        lda     ct_dmg
        pha
        lda     gth
        ldx     gth+1
        jsr     pushax
        lda     bombspot
        ldx     bombspot+1
        jsr     _P_CheckSight
        tay
        beq     @nosight
        lda     gth
        ldx     gth+1
        jsr     pushax
        lda     bombspot
        ldx     bombspot+1
        jsr     pushax
        lda     bombsource
        ldx     bombsource+1
        jsr     pushax
        pla
        plx
        jsr     _P_DamageMobj
        jmp     ret_true
@nosight:
        pla
        pla
@true:  jmp     ret_true

; ---- sector height change -----------------------------------------------------------------------------
; C set iff the thing gth's box (map units, the position's floor) is
; strictly outside sec_bbox (top, bottom, left, right)
outside_sector:
        lda     gth
        ldx     gth+1
        jsr     thing_radius
        sta     os_r
        lda     gth
        ldx     gth+1
        jsr     is_static
        ldy     #SO_X
        lda     #SO_Y
        bcs     :+
        ldy     #MO_X+2
        lda     #MO_Y+2
:       pha
        lda     (gth),y
        sta     os_x
        iny
        lda     (gth),y
        sta     os_x+1
        ply
        lda     (gth),y
        sta     os_y
        iny
        lda     (gth),y
        sta     os_y+1
        ; x + r < left
        clc
        lda     os_x
        adc     os_r
        sta     os_t
        lda     os_x+1
        adc     #0
        sta     os_t+1
        lda     os_t
        cmp     _sec_bbox + 2 * BOXLEFT
        lda     os_t+1
        sbc     _sec_bbox + 2 * BOXLEFT + 1
        bvc     :+
        eor     #$80
:       bmi     @out
        ; right < x - r
        sec
        lda     os_x
        sbc     os_r
        sta     os_t
        lda     os_x+1
        sbc     #0
        sta     os_t+1
        lda     _sec_bbox + 2 * BOXRIGHT
        cmp     os_t
        lda     _sec_bbox + 2 * BOXRIGHT + 1
        sbc     os_t+1
        bvc     :+
        eor     #$80
:       bmi     @out
        ; y + r < bottom
        clc
        lda     os_y
        adc     os_r
        sta     os_t
        lda     os_y+1
        adc     #0
        sta     os_t+1
        lda     os_t
        cmp     _sec_bbox + 2 * BOXBOTTOM
        lda     os_t+1
        sbc     _sec_bbox + 2 * BOXBOTTOM + 1
        bvc     :+
        eor     #$80
:       bmi     @out
        ; top < y - r
        sec
        lda     os_y
        sbc     os_r
        sta     os_t
        lda     os_y+1
        sbc     #0
        sta     os_t+1
        lda     _sec_bbox + 2 * BOXTOP
        cmp     os_t
        lda     _sec_bbox + 2 * BOXTOP + 1
        sbc     os_t+1
        bvc     :+
        eor     #$80
:       bmi     @out
        clc
        rts
@out:   sec
        rts

; boolean P_ChangeSector(uint16_t sector, boolean crunch)
_P_ChangeSector:
        sta     crushchange
        stz     nofit
        ; the sector argument, still on the C stack, is P_SectorBlockBox's
        lda     #<cs_box
        ldx     #>cs_box
        jsr     _P_SectorBlockBox
        lda     cs_box + BOXLEFT
        sta     cp_xl
        lda     cs_box + BOXRIGHT
        sta     cp_xh
        lda     cs_box + BOXBOTTOM
        sta     cp_yl
        lda     cs_box + BOXTOP
        sta     cp_yh
        stz     cp_xl+1
        stz     cp_xh+1
        stz     cp_yl+1
        stz     cp_yh+1
        lda     #CP_THINGS
        sta     cp_kind
        lda     #<pit_change
        sta     cp_func
        lda     #>pit_change
        sta     cp_func+1
        jsr     iter_cells
        lda     nofit
        ldx     #0
        rts

pit_change:
        sta     gth
        stx     gth+1
        ; outside the box of the sector's lines (sec_bbox, P_SectorBlockBox):
        ; its heights do not depend on this sector (p_map.c)
        jsr     outside_sector
        bcc     :+
        jmp     ret_true
:       lda     gth
        ldx     gth+1
        jsr     is_static
        jcc     @actor
        jsr     static_height_clip
        tay
        bne     @true
        ldy     #SO_SFLAGS
        lda     (gth),y
        and     #SF_CORPSE
        beq     @notcorpse
        ; crushed to gibs: not solid, radius and height 0
        ldy     #SO_STATE
        lda     #<S_GIBS
        sta     (gth),y
        iny
        lda     #>S_GIBS
        sta     (gth),y
        lda     _st_tics + S_GIBS
        ldy     #SO_TICS
        sta     (gth),y
        ldy     #SO_SFLAGS
        lda     (gth),y
        ora     #SF_GIBS
        sta     (gth),y
@true:  jmp     ret_true
@notcorpse:
        lda     (gth),y
        and     #SF_DROPPED
        bne     @remove
        jsr     thing_flags0
        and     #MF0_SHOOTABLE
        beq     @true
        lda     #1
        sta     nofit
        jsr     crush_tic
        bne     @true
        jsr     gth_actor
        sta     gth
        stx     gth+1
        ora     gth+1
        beq     @true
        bra     @crush
@remove:
        lda     gth
        ldx     gth+1
        jsr     _P_RemoveMobj
        jmp     ret_true
@actor: lda     gth
        sta     gmo
        lda     gth+1
        sta     gmo+1
        jsr     height_clip
        tay
        bne     @true
        ldy     #MO_HEALTH+1
        lda     (gth),y
        bmi     @gibs
        dey
        ora     (gth),y
        bne     @alive
@gibs:  lda     gth
        ldx     gth+1
        pha
        phx
        jsr     pushax
        lda     #<S_GIBS
        ldx     #>S_GIBS
        jsr     _P_SetMobjState
        pla
        sta     gth+1
        pla
        sta     gth
        ldy     #MO_FLAGS
        lda     (gth),y
        and     #<~MF0_SOLID
        sta     (gth),y
        lda     #0
        ldy     #MO_HEIGHT
        sta     (gth),y
        iny
        sta     (gth),y
        iny
        sta     (gth),y
        iny
        sta     (gth),y
        ldy     #MO_RADIUS
        sta     (gth),y
        jmp     ret_true
@alive: ldy     #MO_FLAGS+2
        lda     (gth),y
        and     #MF2_DROPPED
        bne     @remove
        ldy     #MO_FLAGS
        lda     (gth),y
        and     #MF0_SHOOTABLE
        jeq     @true2
        lda     #1
        sta     nofit
        jsr     crush_tic
        bne     @true2
@crush: ; hurt it and spray blood
        lda     gth
        pha
        lda     gth+1
        pha
        tax
        lda     gth
        jsr     pushax
        lda     #0
        tax
        jsr     pushax
        jsr     pushax
        lda     #10
        ldx     #0
        jsr     _P_DamageMobj
        pla
        sta     gmo+1
        pla
        sta     gmo
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T0
        jsr     push_w
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        jsr     push_w
        ldx     #W_T0
        ldy     #MO_HEIGHT
        jsr     w_ldo
        lda     W+W_T0+3                ; height / 2 (>= 0)
        cmp     #$80
        ror     W+W_T0+3
        ror     W+W_T0+2
        ror     W+W_T0+1
        ror     W+W_T0
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_add
        ldx     #W_T0
        jsr     push_w
        lda     #MT_BLOOD
        jsr     _P_SpawnMobj
        sta     gmo
        stx     gmo+1
        ldy     #MO_MOMX
        jsr     sub_random12
        ldy     #MO_MOMY
        jsr     sub_random12
@true2: jmp     ret_true

; Z set iff crushchange && !(leveltime & 3) (the crush hurts this tic)
crush_tic:
        lda     crushchange
        beq     @no
        lda     _leveltime
        and     #3
        rts
@no:    lda     #1
        rts

; the fixed_t at (gmo)+Y = P_SubRandom() << 12
sub_random12:
        phy
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     _P_SubRandom
        sta     tmp1
        stx     tmp2
        pla
        sta     gmo+1
        pla
        sta     gmo
        ply
        ; (int16 << 12) as fixed_t: bytes 0, lo << 4, (hi:lo) >> 4, sign
        lda     tmp1
        asl     a
        asl     a
        asl     a
        asl     a
        pha
        lda     #0
        sta     (gmo),y
        pla
        iny
        sta     (gmo),y
        ; bits 4..11: (tmp2 << 4 | tmp1 >> 4) & $FF
        lda     tmp1
        lsr     a
        lsr     a
        lsr     a
        lsr     a
        sta     tmp3
        lda     tmp2
        asl     a
        asl     a
        asl     a
        asl     a
        ora     tmp3
        iny
        sta     (gmo),y
        lda     tmp2
        cmp     #$80
        ror     a
        cmp     #$80
        ror     a
        cmp     #$80
        ror     a
        cmp     #$80
        ror     a
        iny
        sta     (gmo),y
        rts

.endif ; DD_MAPDIR
