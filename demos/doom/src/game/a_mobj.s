; Doom for the Appletini -- things and thinkers, 6502 (docs/DESIGN.md
; section 9).
;
; The assembly twin of p_mobj.c and p_tick.c (the C is the reference,
; compiled on the host; read it for the why): the actor and static pools,
; statics seen as actors (P_StaticView, P_WakeStatic, P_Actor) and actors
; put back to sleep, P_SetMobjState, P_MobjThinker with the XY and Z
; movement, P_SpawnMobj, P_RemoveMobj, P_RunStatics, puffs and blood, the
; thinker list and its block pool, P_Ticker. The level-start spawner
; (P_SpawnMapThing, P_SpawnPlayer), the missile spawners and
; P_FindTeleportDest stay in C (p_spawn.c) on both targets.
;
; Actions and thinkers are called with the 6502's JSR through a pointer
; (call_ax); anything they may change is reloaded after: the zero page
; (gmo, gpt..), the W scratch slots. What this module keeps across such
; calls is on the 6502 stack or in variables no nested call writes:
; set_state keeps the thing and the next state on the stack; the XY move
; keeps its remaining move in W_M0/W_M1 (nothing it calls moves another
; thing by XY); the thinker and static loops keep their cursors in their
; own variables (neither runs nested).

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR


.import set_pos, unset_pos, is_static, info_ptr, ret_w, call_ax, cf_ptr
.import actor_cell, static_cell, find_link, line_get
.import _P_UnlinkStatic, _P_ArenaAlloc, _P_ArenaPool, _P_RejectVisible, _arena_bounds
.import try_move, thing_zh, _P_SlideMove, _ceilingline
.import w_mov, w_add, w_sub, w_neg, w_abs, w_zero, w_cmp, w_sign, w_ldi, w_fix
.import w_sext, w_ldo, w_sto, w_ldp, w_fixp, w_mul, w_tst, w_add3, w_sub3
.import aprox_dist
.import _P_Random, _P_SubRandom, _S_StartSound, _P_SectorCeilingPic
.import _P_PlayerThink, _P_UpdateSpecials, _kernel_crash
.import _mobjinfo, _st_tics, _st_action, _st_next, _mobj_actions
.import _player, _gameskill, _leveltime, _skyflatnum, _numsectors, _sec_soundtarget
.import _sec_floorh, _sec_ceilh
.import pushax, pusheax, addysp

.export _mobjs, _mobjs_end, _statics, _statics_end, _nummobjs, _numstatics
.export _mobjs_used, _statics_used, _sview, _sview_src, _thinkercap
.export _P_InitMobjs, _P_ExtendPool, _P_FreeActor, _P_AllocStatic, _P_StaticFlags, _P_ThingHeight
.export _P_StaticView, _P_WakeStatic, _P_Actor, _P_ForgetMobj, _P_SetMobjState
.export _P_ExplodeMissile, _P_MobjThinker, _P_SpawnMobj, _P_RemoveMobj, _P_RunStatics
.export _P_SpawnPuff, _P_SpawnBlood, _P_CheckMissileSpawn
.export _P_InitThinkers, _P_AllocThinker, _P_AddThinker, _P_RemoveThinker
.export _P_UnlinkThinker, _P_RunThinkers, _P_Ticker
.export set_state

.segment "BSS"
_mobjs:         .res 2
_mobjs_end:     .res 2
_statics:       .res 2
_statics_end:   .res 2
_nummobjs:      .res 2
_numstatics:    .res 2
_mobjs_used:    .res 2
_statics_used:  .res 2
mobj_free:      .res 2
static_hint:    .res 2
_sview:         .res MO_SIZE
_sview_src:     .res 2
_thinkercap:    .res TH_SIZE
tblocks:        .res 2
tblock_used:    .res THINKER_BLOCKS
sfl:            .res 4              ; static_flags' result
ss_st:          .res 2              ; set_state
ss_next:        .res 2
ws_s:           .res 2              ; the static being woken / put to sleep
ts_sf:          .res 1
rs_s:           .res 2              ; P_RunStatics' cursor
rs_st:          .res 2
rt_cur:         .res 2              ; P_RunThinkers' cursor
aa_must:        .res 1
sm_type:        .res 1
bl_dmg:         .res 2
im_n:           .res 2              ; P_InitMobjs

.segment "CODE"

ret_false:
        lda     #0
        tax
        rts

; ---- small helpers -------------------------------------------------------------------
; A = st_tics[A/X] / st_action[A/X]; A/X = st_next[A/X]
st_tics_of:
        clc
        adc     #<_st_tics
        sta     ptr1
        txa
        adc     #>_st_tics
        sta     ptr1+1
        lda     (ptr1)
        rts
st_action_of:
        clc
        adc     #<_st_action
        sta     ptr1
        txa
        adc     #>_st_action
        sta     ptr1+1
        lda     (ptr1)
        rts
st_next_of:
        asl     a
        sta     ptr1
        txa
        rol     a
        sta     ptr1+1
        clc
        lda     ptr1
        adc     #<_st_next
        sta     ptr1
        lda     ptr1+1
        adc     #>_st_next
        sta     ptr1+1
        ldy     #1
        lda     (ptr1),y
        tax
        lda     (ptr1)
        rts

; ptr1 = &mobjinfo[gmo->type]
mo_info:
        ldy     #MO_TYPE
        lda     (gmo),y
        jmp     info_ptr

; ptr2 = &sec_floorh[A/X], ptr3 = &sec_ceilh[A/X]
sec_ptrs:
        asl     a
        sta     tmp1
        txa
        rol     a
        sta     tmp2
        clc
        lda     _sec_floorh
        adc     tmp1
        sta     ptr2
        lda     _sec_floorh+1
        adc     tmp2
        sta     ptr2+1
        clc
        lda     _sec_ceilh
        adc     tmp1
        sta     ptr3
        lda     _sec_ceilh+1
        adc     tmp2
        sta     ptr3+1
        rts

; gmo's floorz, ceilingz = those of its sector
mo_floor_ceiling:
        ldy     #MO_SECTOR+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        jsr     sec_ptrs
        ldy     #1
        lda     (ptr2)
        pha
        lda     (ptr2),y
        ldy     #MO_FLOORZ+1
        sta     (gmo),y
        dey
        pla
        sta     (gmo),y
        ldy     #1
        lda     (ptr3)
        pha
        lda     (ptr3),y
        ldy     #MO_CEILINGZ+1
        sta     (gmo),y
        dey
        pla
        sta     (gmo),y
        rts

; Z set iff gmo is the player's mobj
gmo_is_player:
        lda     gmo
        cmp     _player+PL_MO
        bne     :+
        lda     gmo+1
        cmp     _player+PL_MO+1
:       rts

; the fixed_t at (gmo)+Y = 0
zero_field:
        lda     #0
        sta     (gmo),y
        iny
        sta     (gmo),y
        iny
        sta     (gmo),y
        iny
        sta     (gmo),y
        rts

; gmo->tics -= P_Random() & 3, at least 1 (as a signed byte)
tics_rand:
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     _P_Random
        and     #3
        sta     tmp1
        pla
        sta     gmo+1
        pla
        sta     gmo
        ldy     #MO_TICS
        lda     (gmo),y
        sec
        sbc     tmp1
        beq     :+
        bpl     :++
:       lda     #1
:       sta     (gmo),y
        rts

; W[X] = the int16 A/Y << (tmp4) as a fixed_t
w_shl:  jsr     w_sext
@loop:  asl     W,x
        rol     W+1,x
        rol     W+2,x
        rol     W+3,x
        dec     tmp4
        bne     @loop
        rts

; W[X] = P_SubRandom() << 10
subrandom10:
        phx
        jsr     _P_SubRandom
        stx     tmp3
        ldy     tmp3
        plx
        pha
        lda     #10
        sta     tmp4
        pla
        jmp     w_shl

; ---- the pools ---------------------------------------------------------------------------
; void P_InitMobjs(uint16_t nstatic)
_P_InitMobjs:
        sta     _numstatics
        stx     _numstatics+1
        stz     _statics_used
        stz     _statics_used+1
        ; statics = P_ArenaAlloc(n * 16), every slot free
        stx     tmp2
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        ldx     tmp2
        pha
        phx
        jsr     _P_ArenaAlloc
        sta     _statics
        sta     static_hint
        sta     ptr1
        stx     _statics+1
        stx     static_hint+1
        stx     ptr1+1
        ply                             ; the end: statics + size
        pla
        clc
        adc     _statics
        sta     _statics_end
        tya
        adc     _statics+1
        sta     _statics_end+1
@st:    lda     ptr1
        cmp     _statics_end
        bne     :+
        lda     ptr1+1
        cmp     _statics_end+1
        beq     @actors
:       ldy     #SO_SFLAGS
        lda     #SF_FREE
        sta     (ptr1),y
        clc
        lda     ptr1
        adc     #SO_SIZE
        sta     ptr1
        bcc     @st
        inc     ptr1+1
        bra     @st
@actors:
        ; the pool: its place and size from P_ArenaPool (p_setup.c)
        lda     #<im_n
        ldx     #>im_n
        jsr     _P_ArenaPool
        sta     _mobjs
        sta     _mobjs_end
        stx     _mobjs+1
        stx     _mobjs_end+1
        lda     im_n
        sta     _nummobjs
        stz     _nummobjs+1
        tax
        beq     @nopool
@size:  clc                             ; mobjs_end = mobjs + n * MO_SIZE
        lda     _mobjs_end
        adc     #MO_SIZE
        sta     _mobjs_end
        bcc     :+
        inc     _mobjs_end+1
:       dex
        bne     @size
@nopool:
        ; the free list in pool order: each slot's thinker.next is the next
        stz     mobj_free
        stz     mobj_free+1
        lda     _mobjs_end
        sta     ptr1
        lda     _mobjs_end+1
        sta     ptr1+1
@free:  lda     ptr1
        cmp     _mobjs
        bne     :+
        lda     ptr1+1
        cmp     _mobjs+1
        beq     @done
:       sec
        lda     ptr1
        sbc     #MO_SIZE
        sta     ptr1
        bcs     :+
        dec     ptr1+1
:       ldy     #TH_NEXT
        lda     mobj_free
        sta     (ptr1),y
        iny
        lda     mobj_free+1
        sta     (ptr1),y
        lda     ptr1
        sta     mobj_free
        lda     ptr1+1
        sta     mobj_free+1
        bra     @free
@done:  stz     _mobjs_used
        stz     _mobjs_used+1
        stz     _player+PL_MO
        stz     _player+PL_MO+1
        rts

; void P_ExtendPool(void): the set-up overlay's bytes (up to arena_bounds[4])
; become free actor slots, up to MAXACTORS in all
_P_ExtendPool:
        lda     _nummobjs
        cmp     #MAXACTORS
        bcs     @rts
        clc                             ; ptr2 = the slot's end: within the overlay?
        lda     _mobjs_end
        adc     #MO_SIZE
        sta     ptr2
        lda     _mobjs_end+1
        adc     #0
        sta     ptr2+1
        cmp     _arena_bounds+9
        bne     :+
        lda     ptr2
        cmp     _arena_bounds+8
:       beq     :+
        bcs     @rts
:       lda     _mobjs_end
        sta     ptr1
        lda     _mobjs_end+1
        sta     ptr1+1
        ldy     #TH_FUNCTION
        lda     #0
        sta     (ptr1),y
        iny
        sta     (ptr1),y
        ldy     #TH_NEXT
        lda     mobj_free
        sta     (ptr1),y
        iny
        lda     mobj_free+1
        sta     (ptr1),y
        lda     ptr1
        sta     mobj_free
        lda     ptr1+1
        sta     mobj_free+1
        lda     ptr2
        sta     _mobjs_end
        lda     ptr2+1
        sta     _mobjs_end+1
        inc     _nummobjs
        bra     _P_ExtendPool
@rts:   rts

; alloc_actor: an actor slot, zeroed -> A/X (0: none); C set: one must
; exist (else kernel_crash CRASH_MOBJS). When the free list is empty a
; puff, blood or fog is removed on the spot for it.
alloc_actor:
        lda     #0
        rol     a
        sta     aa_must
        lda     mobj_free
        ora     mobj_free+1
        bne     @have
        lda     _mobjs
        sta     ptr3
        lda     _mobjs+1
        sta     ptr3+1
@scan:  lda     ptr3
        cmp     _mobjs_end
        bne     :+
        lda     ptr3+1
        cmp     _mobjs_end+1
        beq     @none
:       ldy     #TH_FUNCTION+1
        lda     (ptr3),y
        dey
        ora     (ptr3),y
        beq     @next                   ; free
        lda     (ptr3),y
        cmp     #THINK_REMOVED
        bne     :+
        iny
        lda     (ptr3),y
        beq     @next                   ; removed
:       ldy     #MO_TYPE
        lda     (ptr3),y
        cmp     #MT_PUFF
        beq     @take
        cmp     #MT_BLOOD
        beq     @take
        cmp     #MT_TFOG
        beq     @take
        cmp     #MT_IFOG
        beq     @take
@next:  clc
        lda     ptr3
        adc     #MO_SIZE
        sta     ptr3
        bcc     @scan
        inc     ptr3+1
        bra     @scan
@take:  lda     ptr3
        ldx     ptr3+1
        pha
        phx
        jsr     _P_RemoveMobj
        plx
        pla
        pha
        phx
        jsr     _P_UnlinkThinker
        plx
        pla
        jsr     _P_FreeActor
        bra     @have
@none:  lda     aa_must
        beq     :+
        lda     #CRASH_MOBJS
        jmp     _kernel_crash
:       jmp     ret_false
@have:  lda     mobj_free
        sta     ptr1
        lda     mobj_free+1
        sta     ptr1+1
        ldy     #TH_NEXT
        lda     (ptr1),y
        sta     mobj_free
        iny
        lda     (ptr1),y
        sta     mobj_free+1
        lda     #0
        ldy     #MO_SIZE-1
:       sta     (ptr1),y
        dey
        bpl     :-
        inc     _mobjs_used
        bne     :+
        inc     _mobjs_used+1
:       lda     ptr1
        ldx     ptr1+1
        rts

; void P_FreeActor(mobj_t *mo)
_P_FreeActor:
        sta     ptr1
        stx     ptr1+1
        ldy     #TH_FUNCTION
        lda     #0
        sta     (ptr1),y
        iny
        sta     (ptr1),y
        ldy     #TH_NEXT
        lda     mobj_free
        sta     (ptr1),y
        iny
        lda     mobj_free+1
        sta     (ptr1),y
        lda     ptr1
        sta     mobj_free
        lda     ptr1+1
        sta     mobj_free+1
        lda     _mobjs_used
        bne     :+
        dec     _mobjs_used+1
:       dec     _mobjs_used
        rts

; sobj_t *P_AllocStatic(void): the next free slot from the hint on, 0 if none
_P_AllocStatic:
        lda     static_hint
        sta     ptr1
        lda     static_hint+1
        sta     ptr1+1
        lda     _numstatics
        sta     tmp1
        lda     _numstatics+1
        sta     tmp2
@loop:  lda     tmp1
        ora     tmp2
        beq     @none
        ldy     #SO_SFLAGS
        lda     (ptr1),y
        and     #SF_FREE
        bne     @found
        clc
        lda     ptr1
        adc     #SO_SIZE
        sta     ptr1
        bcc     :+
        inc     ptr1+1
:       cmp     _statics_end
        bne     :+
        lda     ptr1+1
        cmp     _statics_end+1
        bne     :+
        lda     _statics
        sta     ptr1
        lda     _statics+1
        sta     ptr1+1
:       lda     tmp1
        bne     :+
        dec     tmp2
:       dec     tmp1
        bra     @loop
@found: lda     #0
        sta     (ptr1),y
        lda     ptr1
        sta     static_hint
        lda     ptr1+1
        sta     static_hint+1
        inc     _statics_used
        bne     :+
        inc     _statics_used+1
:       lda     ptr1
        ldx     ptr1+1
        rts
@none:  jmp     ret_false

; the slot A/X free (its bnext is left: an iterator may stand on it)
free_static:
        sta     ptr1
        stx     ptr1+1
        ldy     #SO_SFLAGS
        lda     #SF_FREE
        sta     (ptr1),y
        lda     _statics_used
        bne     :+
        dec     _statics_used+1
:       dec     _statics_used
        rts

; ---- statics seen as actors -------------------------------------------------------------
; sfl = the flags of the static gpt (P_StaticFlags)
static_flags:
        ldy     #SO_TYPE
        lda     (gpt),y
        jsr     info_ptr
        ldy     #MI_FLAGS+3
        ldx     #3
:       lda     (ptr1),y
        sta     sfl,x
        dey
        dex
        bpl     :-
        ldy     #SO_SFLAGS
        lda     (gpt),y
        sta     tmp3
        and     #SF_CORPSE
        beq     @nc
        lda     sfl
        and     #<~(MF0_SHOOTABLE | MF0_SOLID)
        sta     sfl
        lda     sfl+1
        and     #<~MF1_FLOAT
        sta     sfl+1
        lda     sfl+3
        and     #<~MF3_SKULLFLY
        sta     sfl+3
        ldy     #SO_TYPE
        lda     (gpt),y
        cmp     #MT_SKULL
        beq     :+
        lda     sfl+1
        and     #<~MF1_NOGRAVITY
        sta     sfl+1
:       lda     sfl+2
        ora     #MF2_CORPSE
        sta     sfl+2
        lda     sfl+1
        ora     #MF1_DROPOFF
        sta     sfl+1
@nc:    lda     tmp3
        and     #SF_GIBS
        beq     :+
        lda     sfl
        and     #<~MF0_SOLID
        sta     sfl
:       lda     tmp3
        and     #SF_AMBUSH
        beq     :+
        lda     sfl
        ora     #MF0_AMBUSH
        sta     sfl
:       lda     tmp3
        and     #SF_DROPPED
        beq     :+
        lda     sfl+2
        ora     #MF2_DROPPED
        sta     sfl+2
:       rts

; uint32_t P_StaticFlags(sobj_t *s)
_P_StaticFlags:
        sta     gpt
        stx     gpt+1
        jsr     static_flags
        lda     sfl+3
        sta     sreg+1
        lda     sfl+2
        sta     sreg
        ldx     sfl+1
        lda     sfl
        rts

; fixed_t P_ThingHeight(mobj_t *thing)
_P_ThingHeight:
        sta     gth
        stx     gth+1
        jsr     thing_zh
        ldx     #W_PDY                  ; a_map's W_THH
        jmp     ret_w

; the actor gmo takes the fields the static gpt defines (on a zeroed actor)
static_to_mobj:
        ldx     #W_T0
        ldy     #SO_X
        jsr     w_fixp
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_sto
        ldx     #W_T0
        ldy     #SO_Y
        jsr     w_fixp
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_sto
        ldx     #W_T0
        ldy     #SO_Z
        jsr     w_fixp
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_sto
        ldy     #SO_TYPE
        lda     (gpt),y
        ldy     #MO_TYPE
        sta     (gmo),y
        ldy     #SO_STATE
        lda     (gpt),y
        ldy     #MO_STATE
        sta     (gmo),y
        ldy     #SO_STATE+1
        lda     (gpt),y
        ldy     #MO_STATE+1
        sta     (gmo),y
        ldy     #SO_TICS
        lda     (gpt),y
        ldy     #MO_TICS
        sta     (gmo),y
        ldy     #SO_ANGLE
        lda     (gpt),y
        ldy     #MO_ANGLE+1
        sta     (gmo),y
        ldy     #SO_SECTOR
        lda     (gpt),y
        ldy     #MO_SECTOR
        sta     (gmo),y
        ldy     #SO_SECTOR+1
        lda     (gpt),y
        ldy     #MO_SECTOR+1
        sta     (gmo),y
        jsr     static_flags
        ldy     #MO_FLAGS+3
        ldx     #3
:       lda     sfl,x
        sta     (gmo),y
        dey
        dex
        bpl     :-
        lda     gpt
        sta     gth
        lda     gpt+1
        sta     gth+1
        jsr     thing_zh                ; (gpt = gth)
        ldx     #W_PDY                  ; the height (a_map's W_THH)
        ldy     #MO_HEIGHT
        jsr     w_sto
        ldy     #SO_TYPE
        lda     (gpt),y
        jsr     info_ptr
        ldy     #SO_SFLAGS
        lda     (gpt),y
        sta     tmp3
        and     #SF_GIBS
        beq     :+
        lda     #0                      ; gibs have no radius
        bra     :++
:       ldy     #MI_RADIUS
        lda     (ptr1),y
:       ldy     #MO_RADIUS
        sta     (gmo),y
        lda     tmp3
        and     #SF_CORPSE
        beq     :+
        lda     #0                      ; a corpse has no health
        tax
        bra     :++
:       ldy     #MI_SPAWNHEALTH+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
:       ldy     #MO_HEALTH
        sta     (gmo),y
        iny
        txa
        sta     (gmo),y
        lda     _gameskill
        cmp     #sk_nightmare
        beq     :+
        ldy     #MI_REACTIONTIME
        lda     (ptr1),y
        ldy     #MO_REACTIONTIME
        sta     (gmo),y
:       lda     tmp3                    ; lastlook: 1 if SF_LOOK1, else 0
        asl     a
        lda     #0
        rol     a
        ldy     #MO_LASTLOOK
        sta     (gmo),y
        jmp     mo_floor_ceiling

; mobj_t *P_StaticView(sobj_t *s): the scratch actor sview as s
_P_StaticView:
        sta     gpt
        stx     gpt+1
        sta     _sview_src
        stx     _sview_src+1
        lda     #0
        ldy     #MO_SIZE-1
:       sta     _sview,y
        dey
        bpl     :-
        lda     #<_sview
        sta     gmo
        lda     #>_sview
        sta     gmo+1
        jsr     static_to_mobj
        lda     #<_sview
        ldx     #>_sview
        rts

; mobj_t *P_WakeStatic(sobj_t *s): an actor in its place (NULL if no slot)
_P_WakeStatic:
        sta     ws_s
        stx     ws_s+1
        clc
        jsr     alloc_actor
        cpx     #0
        bne     :+
        cmp     #0
        bne     :+
        rts
:       sta     gmo
        stx     gmo+1
        lda     ws_s
        sta     gpt
        lda     ws_s+1
        sta     gpt+1
        jsr     static_to_mobj
        jsr     mobj_thinker_on
        ; the actor takes the static's place in its chain
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     ws_s
        sta     gmo
        sta     ptr4
        lda     ws_s+1
        sta     gmo+1
        sta     ptr4+1
        ldy     #SO_SFLAGS
        lda     (gmo),y
        and     #SF_NOBLOCK
        bne     @linked
        jsr     static_cell
        bcc     @linked
        jsr     find_link
        bcc     @linked
        pla
        sta     ptr3+1
        pla
        sta     ptr3
        pha
        lda     ptr3+1
        pha
        ldy     #SO_BNEXT
        lda     (ptr4),y
        ldy     #MO_BNEXT
        sta     (ptr3),y
        ldy     #SO_BNEXT+1
        lda     (ptr4),y
        ldy     #MO_BNEXT+1
        sta     (ptr3),y
        lda     ptr3
        sta     (ptr2)
        ldy     #1
        lda     ptr3+1
        sta     (ptr2),y
@linked:
        lda     _sview_src
        cmp     ws_s
        bne     :+
        lda     _sview_src+1
        cmp     ws_s+1
        bne     :+
        stz     _sview_src
        stz     _sview_src+1
:       lda     ws_s
        ldx     ws_s+1
        jsr     free_static
        pla
        tax
        pla
        rts

; the actor gmo thinks: P_MobjThinker, added to the list
mobj_thinker_on:
        ldy     #TH_FUNCTION
        lda     #<_P_MobjThinker
        sta     (gmo),y
        iny
        lda     #>_P_MobjThinker
        sta     (gmo),y
        lda     gmo
        ldx     gmo+1
        jmp     _P_AddThinker

; mobj_t *P_Actor(mobj_t *thing)
_P_Actor:
        jsr     is_static
        jcs     _P_WakeStatic
        cmp     #<_sview
        bne     @rts
        cpx     #>_sview
        bne     @rts
        lda     _sview_src
        ldx     _sview_src+1
        jne     _P_WakeStatic
        cmp     #0
        jne     _P_WakeStatic
@rts:   rts

; void P_ForgetMobj(mobj_t *gone)
_P_ForgetMobj:
        sta     tmp3
        stx     tmp4
        lda     _mobjs
        sta     ptr1
        lda     _mobjs+1
        sta     ptr1+1
@mo:    lda     ptr1
        cmp     _mobjs_end
        bne     :+
        lda     ptr1+1
        cmp     _mobjs_end+1
        beq     @player
:       ldy     #MO_TARGET
        jsr     @clear
        ldy     #MO_TRACER
        jsr     @clear
        clc
        lda     ptr1
        adc     #MO_SIZE
        sta     ptr1
        bcc     @mo
        inc     ptr1+1
        bra     @mo
@player:
        lda     #<(_player + PL_ATTACKER)
        sta     ptr1
        lda     #>(_player + PL_ATTACKER)
        sta     ptr1+1
        ldy     #0
        jsr     @clear
        lda     _sec_soundtarget
        sta     ptr1
        lda     _sec_soundtarget+1
        sta     ptr1+1
        lda     _numsectors
        sta     ptr2
        lda     _numsectors+1
        sta     ptr2+1
@sec:   lda     ptr2
        ora     ptr2+1
        beq     @rts
        ldy     #0
        jsr     @clear
        clc
        lda     ptr1
        adc     #2
        sta     ptr1
        bcc     :+
        inc     ptr1+1
:       lda     ptr2
        bne     :+
        dec     ptr2+1
:       dec     ptr2
        bra     @sec
@rts:   rts
; the pointer at (ptr1)+Y = 0 if it is gone (tmp3/tmp4)
@clear: lda     (ptr1),y
        cmp     tmp3
        bne     :+
        iny
        lda     (ptr1),y
        cmp     tmp4
        bne     :+
        lda     #0
        sta     (ptr1),y
        dey
        sta     (ptr1),y
:       rts

; the actor gmo, if it can live on as a static, does
try_sleep:
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_SHOOTABLE
        jne     @rts
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_MISSILE
        jne     @rts
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        jne     @rts
        jsr     gmo_is_player
        jeq     @rts
        ldy     #MO_MOMX
        lda     #0
:       ora     (gmo),y
        iny
        cpy     #MO_MOMZ+4
        bne     :-
        tax
        jne     @rts
        ; on its floor, or hanging
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_NOGRAVITY
        bne     @placed
        jsr     on_floor
        jne     @rts
@placed:
        ; in a quiet state (or one that lasts forever)
        ldy     #MO_TICS
        lda     (gmo),y
        cmp     #ST_FOREVER
        beq     @quiet
        ldy     #MO_STATE+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        jsr     st_action_of
        jpl     @rts
@quiet: ; the static flags it would have
        stz     ts_sf
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_CORPSE
        beq     :+
        lda     #SF_CORPSE
        tsb     ts_sf
:       ldy     #MO_RADIUS
        lda     (gmo),y
        bne     :+
        lda     #SF_GIBS
        tsb     ts_sf
:       ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_DROPPED
        beq     :+
        lda     #SF_DROPPED
        tsb     ts_sf
:       ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_AMBUSH
        beq     :+
        lda     #SF_AMBUSH
        tsb     ts_sf
:       lda     (gmo),y
        and     #MF0_NOBLOCKMAP
        beq     :+
        lda     #SF_NOBLOCK
        tsb     ts_sf
:       jsr     _P_AllocStatic
        sta     ws_s
        stx     ws_s+1
        sta     gpt
        stx     gpt+1
        ora     ws_s+1
        beq     @rts
        ldy     #SO_SFLAGS
        lda     ts_sf
        sta     (gpt),y
        ldy     #MO_TYPE
        lda     (gmo),y
        ldy     #SO_TYPE
        sta     (gpt),y
        ; it must look the same as a static: flags (less the transient
        ; ones) and height
        jsr     static_flags
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #<~(MF0_JUSTHIT | MF0_JUSTATTACKED)
        cmp     sfl
        bne     @undo
        iny
        lda     (gmo),y
        cmp     sfl+1
        bne     @undo
        iny
        lda     (gmo),y
        and     #<~MF2_INFLOAT
        cmp     sfl+2
        bne     @undo
        iny
        lda     (gmo),y
        cmp     sfl+3
        bne     @undo
        lda     gpt
        sta     gth
        lda     gpt+1
        sta     gth+1
        jsr     thing_zh
        ldy     #MO_HEIGHT
        ldx     #0
:       lda     (gmo),y
        cmp     W+W_PDY,x               ; a_map's W_THH
        bne     @undo
        iny
        inx
        cpx     #4
        bne     :-
        bra     @sleep
@undo:  lda     ws_s
        ldx     ws_s+1
        jmp     free_static
@rts:   rts
@sleep: lda     ws_s
        sta     gpt
        lda     ws_s+1
        sta     gpt+1
        ldy     #MO_X+2
        lda     (gmo),y
        ldy     #SO_X
        sta     (gpt),y
        ldy     #MO_X+3
        lda     (gmo),y
        ldy     #SO_X+1
        sta     (gpt),y
        ldy     #MO_Y+2
        lda     (gmo),y
        ldy     #SO_Y
        sta     (gpt),y
        ldy     #MO_Y+3
        lda     (gmo),y
        ldy     #SO_Y+1
        sta     (gpt),y
        ldy     #MO_Z+2
        lda     (gmo),y
        ldy     #SO_Z
        sta     (gpt),y
        ldy     #MO_Z+3
        lda     (gmo),y
        ldy     #SO_Z+1
        sta     (gpt),y
        ldy     #MO_ANGLE+1
        lda     (gmo),y
        ldy     #SO_ANGLE
        sta     (gpt),y
        ldy     #MO_STATE
        lda     (gmo),y
        ldy     #SO_STATE
        sta     (gpt),y
        ldy     #MO_STATE+1
        lda     (gmo),y
        ldy     #SO_STATE+1
        sta     (gpt),y
        ldy     #MO_TICS
        lda     (gmo),y
        ldy     #SO_TICS
        sta     (gpt),y
        ldy     #MO_SECTOR
        lda     (gmo),y
        ldy     #SO_SECTOR
        sta     (gpt),y
        ldy     #MO_SECTOR+1
        lda     (gmo),y
        ldy     #SO_SECTOR+1
        sta     (gpt),y
        ldy     #SO_BNEXT
        lda     #0
        sta     (gpt),y
        iny
        sta     (gpt),y
        ; the static takes the actor's place in its chain
        lda     ts_sf
        and     #SF_NOBLOCK
        bne     @gone
        jsr     actor_cell
        bcc     @gone
        jsr     find_link
        bcc     @gone
        lda     ws_s
        sta     gpt
        lda     ws_s+1
        sta     gpt+1
        ldy     #MO_BNEXT
        lda     (gmo),y
        ldy     #SO_BNEXT
        sta     (gpt),y
        ldy     #MO_BNEXT+1
        lda     (gmo),y
        ldy     #SO_BNEXT+1
        sta     (gpt),y
        lda     ws_s
        sta     (ptr2)
        ldy     #1
        lda     ws_s+1
        sta     (ptr2),y
@gone:  lda     gmo
        ldx     gmo+1
        pha
        phx
        jsr     _P_ForgetMobj
        plx
        pla
        jmp     _P_RemoveThinker

; Z set iff gmo's z == FIX(its floorz)
on_floor:
        ldy     #MO_Z
        lda     (gmo),y
        iny
        ora     (gmo),y
        bne     @rts
        iny
        lda     (gmo),y
        ldy     #MO_FLOORZ
        cmp     (gmo),y
        bne     @rts
        ldy     #MO_Z+3
        lda     (gmo),y
        ldy     #MO_FLOORZ+1
        cmp     (gmo),y
@rts:   rts

; ---- states -----------------------------------------------------------------------------
; boolean P_SetMobjState(mobj_t *mobj, uint16_t state)
_P_SetMobjState:
        pha
        phx
        ldy     #1
        lda     (sp),y
        sta     gmo+1
        lda     (sp)
        sta     gmo
        ldy     #2
        jsr     addysp
        plx
        pla
        jsr     set_state
        ldx     #0
        rts

; set_state: gmo to the state A/X, and on through the zero-tic states,
; running their actions -> A = 0 if it was removed (S_NULL)
set_state:
        sta     ss_st
        stx     ss_st+1
@loop:  lda     ss_st
        ora     ss_st+1
        bne     @live
        ldy     #MO_STATE
        sta     (gmo),y
        iny
        sta     (gmo),y
        lda     gmo
        ldx     gmo+1
        jsr     _P_RemoveMobj
        lda     #0
        rts
@live:  ldy     #MO_STATE
        lda     ss_st
        sta     (gmo),y
        iny
        lda     ss_st+1
        sta     (gmo),y
        ldx     ss_st+1
        lda     ss_st
        jsr     st_tics_of
        ldy     #MO_TICS
        sta     (gmo),y
        lda     ss_st
        ldx     ss_st+1
        jsr     st_next_of
        sta     ss_next
        stx     ss_next+1
        lda     ss_st
        ldx     ss_st+1
        jsr     st_action_of
        and     #$7F
        beq     @quiet
        asl     a
        tay
        lda     _mobj_actions,y
        sta     cf_ptr
        lda     _mobj_actions+1,y
        sta     cf_ptr+1
        lda     ss_next+1
        pha
        lda     ss_next
        pha
        lda     gmo+1
        pha
        lda     gmo
        pha
        ldx     gmo+1
        jsr     call_ax
        pla
        sta     gmo
        pla
        sta     gmo+1
        pla
        sta     ss_next
        pla
        sta     ss_next+1
@quiet: ldy     #MO_TICS
        lda     (gmo),y
        bne     @done
        lda     ss_next
        sta     ss_st
        lda     ss_next+1
        sta     ss_st+1
        jmp     @loop
@done:  lda     #1
        rts

; void P_ExplodeMissile(mobj_t *mo)
_P_ExplodeMissile:
        sta     gmo
        stx     gmo+1
explode:
        ldy     #MO_MOMX
        jsr     zero_field
        ldy     #MO_MOMY
        jsr     zero_field
        ldy     #MO_MOMZ
        jsr     zero_field
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     mo_info
        ldy     #MI_DEATHSTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     set_state
        pla
        sta     gmo+1
        pla
        sta     gmo
        jsr     tics_rand
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #<~MF2_MISSILE
        sta     (gmo),y
        jsr     mo_info
        ldy     #MI_DEATHSOUND
        lda     (ptr1),y
        beq     :+
        pha
        lda     gmo
        ldx     gmo+1
        jsr     pushax
        pla
        jmp     _S_StartSound
:       rts

; ---- movement ---------------------------------------------------------------------------
; W[X] clamped to +-MAXMOVE (30 units)
clamp_move:
        lda     W+3,x
        bmi     @neg
        bne     @hi
        lda     W+2,x
        cmp     #30
        bcc     @rts
        bne     @hi
        lda     W+1,x
        ora     W,x
        beq     @rts
@hi:    stz     W,x
        stz     W+1,x
        lda     #30
        sta     W+2,x
        stz     W+3,x
@rts:   rts
@neg:   cmp     #$FF
        bne     @lo
        lda     W+2,x
        cmp     #<-30
        bcs     @rts                    ; >= -30.0
@lo:    stz     W,x
        stz     W+1,x
        lda     #<-30
        sta     W+2,x
        lda     #$FF
        sta     W+3,x
        rts

; C set iff W[X] > MAXMOVE / 2 (15 units)
over15: lda     W+3,x
        bmi     @no
        bne     @yes
        lda     W+2,x
        cmp     #15
        bcc     @no
        bne     @yes
        lda     W+1,x
        ora     W,x
        bne     @yes
@no:    clc
        rts
@yes:   sec
        rts

; W[X] = W[Y] / 2 (C's division: towards zero)
w_half: jsr     w_mov
        lda     W+3,x
        bpl     :+
        inc     W,x
        bne     :+
        inc     W+1,x
        bne     :+
        inc     W+2,x
        bne     :+
        inc     W+3,x
:       ; (fall into w_sar1)
; W[X] >>= 1 (arithmetic)
w_sar1: lda     W+3,x
        cmp     #$80
        ror     W+3,x
        ror     W+2,x
        ror     W+1,x
        ror     W,x
        rts

; C set iff -bound < W[X] < bound, the bound $0000hhll in A (hi) / Y (lo)
; ... used as: |W[X]| < STOPSPEED ($1000), |W[X]| <= FRACUNIT / 4
; (W[X] + $0FFF) unsigned < $1FFF
below_stop:
        clc
        lda     W,x
        adc     #$FF
        sta     tmp1
        lda     W+1,x
        adc     #$0F
        sta     tmp2
        lda     W+2,x
        adc     #0
        bne     @no
        lda     W+3,x
        adc     #0
        bne     @no
        lda     tmp2
        cmp     #$1F
        bcc     @yes
        bne     @no
        lda     tmp1
        cmp     #$FF
        bcc     @yes
@no:    clc
        rts
@yes:   sec
        rts

; C set iff -FRACUNIT/4 <= W[X] <= FRACUNIT/4: (W[X] + $4000) unsigned <= $8000
within_quarter:
        clc
        lda     W+1,x
        adc     #$40
        sta     tmp2
        lda     W+2,x
        adc     #0
        bne     @no
        lda     W+3,x
        adc     #0
        bne     @no
        lda     tmp2
        cmp     #$80
        bcc     @yes
        bne     @no
        lda     W,x
        bne     @no
@yes:   sec
        rts
@no:    clc
        rts

; P_XYMovement of gmo (kept)
xy_movement:
        ldx     #W_M0
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_M1
        ldy     #MO_MOMY
        jsr     w_ldo
        ldx     #W_M0
        jsr     w_tst
        bne     @moving
        ldx     #W_M1
        jsr     w_tst
        bne     @moving
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        beq     @rts
        ; a lost soul that stopped
        lda     (gmo),y
        and     #<~MF3_SKULLFLY
        sta     (gmo),y
        ldy     #MO_MOMZ
        jsr     zero_field
        jsr     mo_info
        ldy     #MI_SPAWNSTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jmp     set_state
@rts:   rts
@moving:
        ldx     #W_M0
        jsr     clamp_move
        ldx     #W_M1
        jsr     clamp_move
        ldx     #W_M0
        ldy     #MO_MOMX
        jsr     w_sto
        ldx     #W_M1
        ldy     #MO_MOMY
        jsr     w_sto
@step:  ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_M0
        jsr     over15
        bcs     @half
        ldx     #W_M1
        jsr     over15
        bcs     @half
        ldx     #W_TMX
        ldy     #W_M0
        jsr     w_add
        ldx     #W_TMY
        ldy     #W_M1
        jsr     w_add
        ldx     #W_M0
        jsr     w_zero
        ldx     #W_M1
        jsr     w_zero
        bra     @try
@half:  ldx     #W_T0
        ldy     #W_M0
        jsr     w_half
        ldx     #W_TMX
        ldy     #W_T0
        jsr     w_add
        ldx     #W_T0
        ldy     #W_M1
        jsr     w_half
        ldx     #W_TMY
        ldy     #W_T0
        jsr     w_add
        ldx     #W_M0
        jsr     w_sar1
        ldx     #W_M1
        jsr     w_sar1
@try:   jsr     try_move
        jne     @next
        jsr     gmo_is_player
        bne     @notplayer
        lda     gmo
        pha
        lda     gmo+1
        pha
        tax
        lda     gmo
        jsr     _P_SlideMove
        pla
        sta     gmo+1
        pla
        sta     gmo
        bra     @next
@notplayer:
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_MISSILE
        beq     @stop
        ; vanilla's hack: missiles vanish against a sky ceiling
        lda     _ceilingline
        and     _ceilingline+1
        cmp     #$FF
        beq     @explode
        lda     _ceilingline
        ldx     _ceilingline+1
        jsr     line_get
        ldy     #LI_BACKSECTOR
        lda     (gli),y
        iny
        and     (gli),y
        cmp     #$FF
        beq     @explode
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     (gli),y
        tax
        dey
        lda     (gli),y
        jsr     _P_SectorCeilingPic
        sta     tmp1
        pla
        sta     gmo+1
        pla
        sta     gmo
        lda     tmp1
        cmp     _skyflatnum
        bne     @explode
        cpx     _skyflatnum+1
        bne     @explode
        lda     gmo
        ldx     gmo+1
        jmp     _P_RemoveMobj
@explode:
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     explode
        pla
        sta     gmo+1
        pla
        sta     gmo
        bra     @next
@stop:  ldy     #MO_MOMX
        jsr     zero_field
        ldy     #MO_MOMY
        jsr     zero_field
@next:  ldx     #W_M0
        jsr     w_tst
        jne     @step
        ldx     #W_M1
        jsr     w_tst
        jne     @step
        ; friction
        jsr     gmo_is_player
        bne     @notcheat
        lda     _player+PL_CHEATS
        and     #CF_NOMOMENTUM
        beq     @notcheat
        ldy     #MO_MOMX
        jsr     zero_field
        ldy     #MO_MOMY
        jmp     zero_field
@notcheat:
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_MISSILE
        jne     @rts2
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        jne     @rts2
        ; in the air: no friction
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldy     #MO_FLOORZ
        lda     (gmo),y
        pha
        ldy     #MO_FLOORZ+1
        lda     (gmo),y
        tay
        pla
        ldx     #W_T1
        jsr     w_fix
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        cmp     #1
        jeq     @rts2
        ldx     #W_M2
        ldy     #MO_MOMX
        jsr     w_ldo
        ldx     #W_M3
        ldy     #MO_MOMY
        jsr     w_ldo
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_CORPSE
        beq     @stopped
        ; a sliding corpse keeps sliding off a step
        ldx     #W_M2
        jsr     within_quarter
        bcc     @sliding
        ldx     #W_M3
        jsr     within_quarter
        bcs     @stopped
@sliding:
        ldy     #MO_SECTOR+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        jsr     sec_ptrs
        ldy     #MO_FLOORZ
        lda     (gmo),y
        cmp     (ptr2)
        bne     @rts2
        ldy     #MO_FLOORZ+1
        lda     (gmo),y
        ldy     #1
        cmp     (ptr2),y
        bne     @rts2
@stopped:
        ldx     #W_M2
        jsr     below_stop
        bcc     @friction
        ldx     #W_M3
        jsr     below_stop
        bcc     @friction
        jsr     gmo_is_player
        bne     @halt
        lda     _player+PL_CMD+TC_FORWARDMOVE
        ora     _player+PL_CMD+TC_SIDEMOVE
        bne     @friction
        ; the player stops running
        ldy     #MO_STATE
        lda     (gmo),y
        sec
        sbc     #<S_PLAY_RUN1
        tax
        iny
        lda     (gmo),y
        sbc     #>S_PLAY_RUN1
        bne     @halt
        cpx     #4
        bcs     @halt
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     #<S_PLAY
        ldx     #>S_PLAY
        jsr     set_state
        pla
        sta     gmo+1
        pla
        sta     gmo
@halt:  ldy     #MO_MOMX
        jsr     zero_field
        ldy     #MO_MOMY
        jmp     zero_field
@rts2:  rts
@friction:
        ldx     #W_T0
        jsr     w_ldi
        .dword  $E800
        ldx     #W_M2
        ldy     #W_T0
        jsr     w_mul
        ldx     #W_FR
        ldy     #MO_MOMX
        jsr     w_sto
        ldx     #W_M3
        ldy     #W_T0
        jsr     w_mul
        ldx     #W_FR
        ldy     #MO_MOMY
        jmp     w_sto

; P_ZMovement of gmo (kept)
z_movement:
        ldy     #MO_FLOORZ+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        phx
        ply
        ldx     #W_M2                   ; M2 = floorz (fixed)
        jsr     w_fix
        ldx     #W_M3
        ldy     #MO_Z
        jsr     w_ldo
        ; the player's view drops with a step down
        jsr     gmo_is_player
        bne     @notpl
        ldx     #W_M3
        ldy     #W_M2
        jsr     w_cmp
        bpl     @notpl
        ldx     #W_T0
        ldy     #W_M2
        lda     #W_M3
        jsr     w_sub3
        lda     #<(_player + PL_VIEWHEIGHT)
        sta     gpt
        lda     #>(_player + PL_VIEWHEIGHT)
        sta     gpt+1
        ldx     #W_T1
        ldy     #0
        jsr     w_ldp
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_sub
        ldx     #W_T1
        ldy     #0
        jsr     w_stp_gpt
        ldx     #W_T0
        jsr     w_ldi
        .dword  41 * $10000
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_sub
        jsr     t0_sar3
        ldx     #W_T0
        ldy     #PL_DELTAVIEWHEIGHT - PL_VIEWHEIGHT
        jsr     w_stp_gpt
@notpl: ; z += momz
        ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_ldo
        ldx     #W_M3
        ldy     #W_T4
        jsr     w_add
        ; a floating monster rises or sinks towards its target
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_FLOAT
        jeq     @nofloat
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
        ora     gpt
        jeq     @nofloat
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        jne     @nofloat
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_INFLOAT
        jne     @nofloat
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T2
        ldy     #MO_X
        jsr     w_ldp
        ldx     #W_T0
        ldy     #W_T2
        jsr     w_sub
        ldx     #W_T1
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T2
        ldy     #MO_Y
        jsr     w_ldp
        ldx     #W_T1
        ldy     #W_T2
        jsr     w_sub
        jsr     aprox_dist
        ldx     #W_T3                   ; dist
        ldy     #W_FR
        jsr     w_mov
        ; delta = target->z + (height >> 1) - z
        ldx     #W_T0
        ldy     #MO_HEIGHT
        jsr     w_ldo
        ldx     #W_T0
        jsr     w_sar1
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_ldp
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_add
        ldx     #W_T0
        ldy     #W_M3
        jsr     w_sub                   ; T0 = delta
        ldx     #W_T1                   ; T1 = delta * 3
        ldy     #W_T0
        jsr     w_mov
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_add
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_add
        ldx     #W_T0
        jsr     w_sign
        beq     @nofloat
        bpl     @up
        ldx     #W_T1
        jsr     w_neg                   ; -(delta * 3)
        ldx     #W_T3
        ldy     #W_T1
        jsr     w_cmp
        bpl     @nofloat
        sec
        lda     W+W_M3+2
        sbc     #4
        sta     W+W_M3+2
        bcs     @nofloat
        dec     W+W_M3+3
        bra     @nofloat
@up:    ldx     #W_T3
        ldy     #W_T1
        jsr     w_cmp
        bpl     @nofloat
        clc
        lda     W+W_M3+2
        adc     #4
        sta     W+W_M3+2
        bcc     @nofloat
        inc     W+W_M3+3
@nofloat:
        ldx     #W_M3
        ldy     #MO_Z
        jsr     w_sto
        ; on the floor?
        ldx     #W_M3
        ldy     #W_M2
        jsr     w_cmp
        cmp     #1
        jeq     @air
        ; Ultimate Doom's lost soul bounce
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        beq     :+
        ldx     #W_T4
        jsr     w_neg
        ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_sto
:       lda     W+W_T4+3
        bpl     @landed
        jsr     gmo_is_player
        bne     @nooof
        ; a hard landing: the view squats, oof
        lda     W+W_T4+3
        cmp     #$FF
        bne     @oof
        lda     W+W_T4+2
        cmp     #<-8
        bcs     @nooof                  ; momz >= -8.0
@oof:   ldx     #W_T0
        ldy     #W_T4
        jsr     w_mov
        jsr     t0_sar3
        lda     #<(_player + PL_DELTAVIEWHEIGHT)
        sta     gpt
        lda     #>(_player + PL_DELTAVIEWHEIGHT)
        sta     gpt+1
        ldx     #W_T0
        ldy     #0
        jsr     w_stp_gpt
        lda     gmo
        pha
        lda     gmo+1
        pha
        tax
        lda     gmo
        jsr     pushax
        lda     #sfx_oof
        jsr     _S_StartSound
        pla
        sta     gmo+1
        pla
        sta     gmo
@nooof: ldy     #MO_MOMZ
        jsr     zero_field
@landed:
        ldx     #W_M2
        ldy     #MO_Z
        jsr     w_sto
        jsr     missile_hits
        bcc     @ceiling
        jmp     explode
@air:   ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_NOGRAVITY
        bne     @ceiling
        ldx     #W_T4
        jsr     w_tst
        bne     :+
        ldx     #W_T4
        jsr     w_ldi
        .dword  $FFFE0000               ; -GRAVITY * 2
        bra     @fall
:       lda     W+W_T4+2
        bne     :+
        dec     W+W_T4+3
:       dec     W+W_T4+2
@fall:  ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_sto
@ceiling:
        ; the top against the ceiling
        ldy     #MO_CEILINGZ
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tay
        pla
        ldx     #W_T1
        jsr     w_fix                   ; T1 = FIX(ceilingz)
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T2
        ldy     #MO_HEIGHT
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_T2
        jsr     w_add
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_cmp
        cmp     #1
        bne     @rts
        ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_ldo
        ldx     #W_T4
        jsr     w_sign
        cmp     #1
        bne     :+
        ldy     #MO_MOMZ
        jsr     zero_field
:       ldx     #W_T1
        ldy     #W_T2
        jsr     w_sub
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_sto
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        beq     :+
        ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_ldo
        ldx     #W_T4
        jsr     w_neg
        ldx     #W_T4
        ldy     #MO_MOMZ
        jsr     w_sto
:       jsr     missile_hits
        bcc     @rts
        jmp     explode
@rts:   rts

; C set iff gmo is a missile that explodes on what it hit (not NOCLIP)
missile_hits:
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #MF2_MISSILE
        beq     @no
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_NOCLIP
        bne     @no
        sec
        rts
@no:    clc
        rts

; W_T0 >>= 3 (arithmetic)
t0_sar3:
        ldx     #W_T0
        jsr     w_sar1
        jsr     w_sar1
        jmp     w_sar1

; the 4 bytes at (gpt)+Y = W[X]
w_stp_gpt:
        lda     W,x
        sta     (gpt),y
        iny
        lda     W+1,x
        sta     (gpt),y
        iny
        lda     W+2,x
        sta     (gpt),y
        iny
        lda     W+3,x
        sta     (gpt),y
        rts

; Z set iff gmo's thinker was removed
removed:
        ldy     #TH_FUNCTION+1
        lda     (gmo),y
        bne     :+
        dey
        lda     (gmo),y
        cmp     #THINK_REMOVED
:       rts

; void P_MobjThinker(mobj_t *mobj)
_P_MobjThinker:
        sta     gmo
        stx     gmo+1
        ldy     #MO_MOMX
        lda     #0
:       ora     (gmo),y
        iny
        cpy     #MO_MOMY+4
        bne     :-
        tax
        bne     @xy
        ldy     #MO_FLAGS+3
        lda     (gmo),y
        and     #MF3_SKULLFLY
        beq     @z
@xy:    jsr     xy_movement
        jsr     removed
        beq     @rts
@z:     jsr     on_floor
        bne     @zm
        ldy     #MO_MOMZ
        lda     #0
:       ora     (gmo),y
        iny
        cpy     #MO_MOMZ+4
        bne     :-
        tax
        beq     @tics
@zm:    jsr     z_movement
        jsr     removed
        beq     @rts
@tics:  ldy     #MO_TICS
        lda     (gmo),y
        cmp     #ST_FOREVER
        beq     @sleep
        dec     a
        sta     (gmo),y
        bne     @sleep
        ldy     #MO_STATE+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        jsr     st_next_of
        ldy     gmo
        phy
        ldy     gmo+1
        phy
        jsr     set_state
        ply
        sty     gmo+1
        ply
        sty     gmo
        tax
        beq     @rts
@sleep: jmp     try_sleep
@rts:   rts

; ---- spawning and removal -------------------------------------------------------------------
; mobj_t *P_SpawnMobj(fixed_t x, fixed_t y, fixed_t z, uint8_t type)
; C stack: +0 z, +4 y, +8 x (left there until the end)
_P_SpawnMobj:
        sta     sm_type
        sec
        jsr     alloc_actor
        sta     gmo
        stx     gmo+1
        lda     sm_type
        ldy     #MO_TYPE
        sta     (gmo),y
        ldx     #3
        ldy     #11
:       lda     (sp),y                  ; x
        pha
        dey
        dex
        bpl     :-
        ldy     #MO_X
        ldx     #4
:       pla
        sta     (gmo),y
        iny
        dex
        bne     :-
        ldx     #3
        ldy     #7
:       lda     (sp),y                  ; y
        pha
        dey
        dex
        bpl     :-
        ldy     #MO_Y
        ldx     #4
:       pla
        sta     (gmo),y
        iny
        dex
        bne     :-
        jsr     mo_info
        ldy     #MI_RADIUS
        lda     (ptr1),y
        ldy     #MO_RADIUS
        sta     (gmo),y
        ldy     #MI_HEIGHT
        lda     (ptr1),y
        ldy     #MO_HEIGHT+2
        sta     (gmo),y
        ldy     #MI_FLAGS
        lda     (ptr1),y
        ldy     #MO_FLAGS
        sta     (gmo),y
        ldy     #MI_FLAGS+1
        lda     (ptr1),y
        ldy     #MO_FLAGS+1
        sta     (gmo),y
        ldy     #MI_FLAGS+2
        lda     (ptr1),y
        ldy     #MO_FLAGS+2
        sta     (gmo),y
        ldy     #MI_FLAGS+3
        lda     (ptr1),y
        ldy     #MO_FLAGS+3
        sta     (gmo),y
        ldy     #MI_SPAWNHEALTH
        lda     (ptr1),y
        ldy     #MO_HEALTH
        sta     (gmo),y
        ldy     #MI_SPAWNHEALTH+1
        lda     (ptr1),y
        ldy     #MO_HEALTH+1
        sta     (gmo),y
        lda     _gameskill
        cmp     #sk_nightmare
        beq     :+
        ldy     #MI_REACTIONTIME
        lda     (ptr1),y
        ldy     #MO_REACTIONTIME
        sta     (gmo),y
:       lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     _P_Random               ; vanilla's lastlook: P_Random() % MAXPLAYERS
        and     #3
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        ldy     #MO_LASTLOOK
        sta     (gmo),y
        jsr     mo_info
        ldy     #MI_SPAWNSTATE
        lda     (ptr1),y
        ldy     #MO_STATE
        sta     (gmo),y
        pha
        ldy     #MI_SPAWNSTATE+1
        lda     (ptr1),y
        ldy     #MO_STATE+1
        sta     (gmo),y
        tax
        pla
        jsr     st_tics_of
        ldy     #MO_TICS
        sta     (gmo),y
        jsr     set_pos
        jsr     mo_floor_ceiling
        ; z: ONFLOORZ (MININT), ONCEILINGZ (MAXINT) or as given
        ldy     #3
        lda     (sp),y
        cmp     #$80
        bne     @notfloor
        dey
        lda     (sp),y
        dey
        ora     (sp),y
        dey
        ora     (sp),y
        bne     @given
        ldy     #MO_FLOORZ
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tay
        pla
        ldx     #W_T0
        jsr     w_fix
        bra     @setz
@notfloor:
        cmp     #$7F
        bne     @given
        dey
        lda     (sp),y
        dey
        and     (sp),y
        dey
        and     (sp),y
        cmp     #$FF
        bne     @given
        ldy     #MO_CEILINGZ
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tay
        pla
        ldx     #W_T0
        jsr     w_fix
        jsr     mo_info
        ldy     #MI_HEIGHT
        lda     (ptr1),y
        sta     tmp1
        sec
        lda     W+W_T0+2
        sbc     tmp1
        sta     W+W_T0+2
        bcs     @setz
        dec     W+W_T0+3
        bra     @setz
@given: ldy     #3
:       lda     (sp),y
        sta     W+W_T0,y
        dey
        bpl     :-
@setz:  ldx     #W_T0
        ldy     #MO_Z
        jsr     w_sto
        jsr     mobj_thinker_on
        ldy     #12
        jsr     addysp
        lda     gmo
        ldx     gmo+1
        rts

; void P_RemoveMobj(mobj_t *mobj)
_P_RemoveMobj:
        cmp     #<_sview
        bne     @notview
        cpx     #>_sview
        bne     @notview
        lda     _sview_src
        ldx     _sview_src+1
        bne     :+
        cmp     #0
        beq     @rts
:       stz     _sview_src
        stz     _sview_src+1
        bra     @static
@notview:
        jsr     is_static
        bcc     @actor
@static:
        sta     ptr1
        stx     ptr1+1
        pha
        phx
        ldy     #SO_SFLAGS
        lda     (ptr1),y
        and     #SF_NOBLOCK
        bne     :+
        plx
        pla
        pha
        phx
        jsr     _P_UnlinkStatic
:       plx
        pla
        jmp     free_static
@actor: sta     gmo
        stx     gmo+1
        jsr     unset_pos
        jsr     mo_info
        ldy     #MI_FLAGS
        lda     (ptr1),y
        and     #MF0_SHOOTABLE
        beq     :+
        lda     gmo
        ldx     gmo+1
        jsr     _P_ForgetMobj
:       lda     gmo
        ldx     gmo+1
        jmp     _P_RemoveThinker
@rts:   rts

; ---- the statics' tic ----------------------------------------------------------------------------
; void P_RunStatics(void)
_P_RunStatics:
        lda     _statics
        sta     rs_s
        lda     _statics+1
        sta     rs_s+1
@loop:  lda     rs_s
        cmp     _statics_end
        bne     :+
        lda     rs_s+1
        cmp     _statics_end+1
        bne     :+
        rts
:       jsr     rs_gpt
        ldy     #SO_SFLAGS
        lda     (gpt),y
        and     #SF_FREE
        jne     @next
        ldy     #SO_TICS
        lda     (gpt),y
        cmp     #ST_FOREVER
        jeq     @next
        dec     a
        sta     (gpt),y
        jne     @next
        ldy     #SO_STATE
        lda     (gpt),y
        sta     rs_st
        iny
        lda     (gpt),y
        sta     rs_st+1
@state: lda     rs_st
        ldx     rs_st+1
        jsr     st_next_of
        sta     rs_st
        stx     rs_st+1
        ora     rs_st+1
        bne     @live
        ; the end of its states: gone
        jsr     rs_gpt
        ldy     #SO_SFLAGS
        lda     (gpt),y
        and     #SF_NOBLOCK
        bne     :+
        lda     rs_s
        ldx     rs_s+1
        jsr     _P_UnlinkStatic
:       lda     rs_s
        ldx     rs_s+1
        jsr     free_static
        bra     @next
@live:  lda     rs_st
        ldx     rs_st+1
        jsr     st_action_of
        and     #$7F
        beq     @quiet
        cmp     #AC_Look
        bne     @wake
        jsr     rs_gpt
        ldy     #SO_SFLAGS
        lda     (gpt),y
        and     #SF_DORMANT
        beq     @wake
        jsr     may_wake
        beq     @quiet
@wake:  lda     rs_s
        ldx     rs_s+1
        jsr     _P_WakeStatic
        cpx     #0
        bne     :+
        cmp     #0
        beq     @quiet                  ; no actor slot: no action
:       sta     gmo
        stx     gmo+1
        lda     rs_st
        ldx     rs_st+1
        jsr     set_state
        bra     @next
@quiet: jsr     rs_gpt
        ldy     #SO_STATE
        lda     rs_st
        sta     (gpt),y
        iny
        lda     rs_st+1
        sta     (gpt),y
        ldx     rs_st+1
        lda     rs_st
        jsr     st_tics_of
        ldy     #SO_TICS
        sta     (gpt),y
        cmp     #0
        jeq     @state
@next:  clc
        lda     rs_s
        adc     #SO_SIZE
        sta     rs_s
        jcc     @loop
        inc     rs_s+1
        jmp     @loop

rs_gpt: lda     rs_s
        sta     gpt
        lda     rs_s+1
        sta     gpt+1
        rts

; Z clear iff the dormant static gpt's A_Look may succeed: its sector heard
; a noise, or REJECT lets it see the living player's sector
may_wake:
        ldy     #SO_SECTOR
        lda     (gpt),y
        asl     a
        sta     tmp1
        iny
        lda     (gpt),y
        rol     a
        sta     tmp2
        clc
        lda     _sec_soundtarget
        adc     tmp1
        sta     ptr1
        lda     _sec_soundtarget+1
        adc     tmp2
        sta     ptr1+1
        ldy     #1
        lda     (ptr1),y
        ora     (ptr1)
        bne     @rts
        lda     _player+PL_MO
        sta     ptr1
        ora     _player+PL_MO+1
        beq     @rts
        lda     _player+PL_MO+1
        sta     ptr1+1
        lda     _player+PL_HEALTH+1
        bmi     @no
        ora     _player+PL_HEALTH
        beq     @rts
        ldy     #SO_SECTOR
        lda     (gpt),y
        tax
        iny
        lda     (gpt),y
        phx
        tax
        pla
        jsr     pushax
        ldy     #MO_SECTOR+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     _P_RejectVisible
        cmp     #0
@rts:   rts
@no:    lda     #0
        rts

; ---- puffs, blood, missiles ---------------------------------------------------------------------
; void P_SpawnPuff(fixed_t x, fixed_t y, fixed_t z)
_P_SpawnPuff:
        jsr     get_z_t4
        ldx     #W_T4
        jsr     push_t4
        lda     #MT_PUFF
        jsr     _P_SpawnMobj
        sta     gmo
        stx     gmo+1
        ldy     #MO_MOMZ+2
        lda     #1
        sta     (gmo),y
        jsr     tics_rand
        ; a punch's puff starts small
        lda     W+W_ATTACKRANGE
        ora     W+W_ATTACKRANGE+1
        ora     W+W_ATTACKRANGE+3
        bne     @rts
        lda     W+W_ATTACKRANGE+2
        cmp     #64
        bne     @rts
        lda     #<S_PUFF3
        ldx     #>S_PUFF3
        jmp     set_state
@rts:   rts

; W_T4 = the z in A/X/sreg + P_SubRandom() << 10
get_z_t4:
        sta     W+W_T4
        stx     W+W_T4+1
        lda     sreg
        sta     W+W_T4+2
        lda     sreg+1
        sta     W+W_T4+3
        ldx     #W_T3
        jsr     subrandom10
        ldx     #W_T4
        ldy     #W_T3
        jmp     w_add

push_t4:
        jsr     ret_w
        jmp     pusheax

; void P_SpawnBlood(fixed_t x, fixed_t y, fixed_t z, int16_t damage)
_P_SpawnBlood:
        sta     bl_dmg
        stx     bl_dmg+1
        ; z (on the C stack) += P_SubRandom() << 10
        ldx     #W_T3
        jsr     subrandom10
        clc                             ; (X counts $FC..$FF: inx keeps the carry)
        ldy     #0
        ldx     #<-4
:       lda     (sp),y
        adc     W+W_T3+4-256,x
        sta     (sp),y
        iny
        inx
        bne     :-
        lda     #MT_BLOOD
        jsr     _P_SpawnMobj
        sta     gmo
        stx     gmo+1
        ldy     #MO_MOMZ+2
        lda     #2
        sta     (gmo),y
        jsr     tics_rand
        ; damage 9..12: S_BLOOD2, below 9: S_BLOOD3
        lda     bl_dmg+1
        bmi     @small
        bne     @rts
        lda     bl_dmg
        cmp     #13
        bcs     @rts
        cmp     #9
        bcc     @small
        lda     #<S_BLOOD2
        ldx     #>S_BLOOD2
        jmp     set_state
@small: lda     #<S_BLOOD3
        ldx     #>S_BLOOD3
        jmp     set_state
@rts:   rts

; void P_CheckMissileSpawn(mobj_t *th)
_P_CheckMissileSpawn:
        sta     gmo
        stx     gmo+1
        jsr     tics_rand
        ; move it half a step out of its shooter
        ldy     #MO_MOMX
        ldx     #MO_X
        jsr     @half
        ldy     #MO_MOMY
        ldx     #MO_Y
        jsr     @half
        ldy     #MO_MOMZ
        ldx     #MO_Z
        jsr     @half
        ldx     #W_TMX
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_TMY
        ldy     #MO_Y
        jsr     w_ldo
        jsr     try_move
        bne     :+
        jmp     explode
:       rts
; the field at X += the field at Y >> 1
@half:  phx
        ldx     #W_T0
        jsr     w_ldo
        ldx     #W_T0
        jsr     w_sar1
        ply
        phy
        ldx     #W_T1
        jsr     w_ldo
        ldx     #W_T1
        ldy     #W_T0
        jsr     w_add
        ply
        ldx     #W_T1
        jmp     w_sto

; ---- thinkers ------------------------------------------------------------------------------------
; void P_InitThinkers(void)
_P_InitThinkers:
        lda     #<_thinkercap
        sta     _thinkercap+TH_PREV
        sta     _thinkercap+TH_NEXT
        lda     #>_thinkercap
        sta     _thinkercap+TH_PREV+1
        sta     _thinkercap+TH_NEXT+1
        lda     #<(THINKER_BLOCKS * THINKER_BLOCK)
        ldx     #>(THINKER_BLOCKS * THINKER_BLOCK)
        jsr     _P_ArenaAlloc
        sta     tblocks
        stx     tblocks+1
        ldx     #THINKER_BLOCKS-1
:       stz     tblock_used,x
        dex
        bpl     :-
        rts

; thinker_t *P_AllocThinker(uint8_t size): a zeroed block
_P_AllocThinker:
        cmp     #THINKER_BLOCK+1
        bcs     @full
        ldx     #0
@find:  lda     tblock_used,x
        beq     @found
        inx
        cpx     #THINKER_BLOCKS
        bne     @find
@full:  lda     #CRASH_ARENA
        jmp     _kernel_crash
@found: inc     tblock_used,x
        ; tblocks + X * 32
        stz     tmp2
        txa
        asl     a
        asl     a
        asl     a
        asl     a
        rol     tmp2
        asl     a
        rol     tmp2
        clc
        adc     tblocks
        sta     ptr1
        lda     tmp2
        adc     tblocks+1
        sta     ptr1+1
        lda     #0
        ldy     #THINKER_BLOCK-1
:       sta     (ptr1),y
        dey
        bpl     :-
        lda     ptr1
        ldx     ptr1+1
        rts
.assert THINKER_BLOCK = 32, error, "P_AllocThinker multiplies by 32"

; void P_AddThinker(thinker_t *thinker)
_P_AddThinker:
        sta     ptr1
        stx     ptr1+1
        lda     _thinkercap+TH_PREV
        sta     ptr2
        lda     _thinkercap+TH_PREV+1
        sta     ptr2+1
        ldy     #TH_NEXT                ; thinkercap.prev->next = thinker
        lda     ptr1
        sta     (ptr2),y
        iny
        lda     ptr1+1
        sta     (ptr2),y
        ldy     #TH_NEXT                ; thinker->next = &thinkercap
        lda     #<_thinkercap
        sta     (ptr1),y
        iny
        lda     #>_thinkercap
        sta     (ptr1),y
        ldy     #TH_PREV                ; thinker->prev = thinkercap.prev
        lda     ptr2
        sta     (ptr1),y
        iny
        lda     ptr2+1
        sta     (ptr1),y
        lda     ptr1                    ; thinkercap.prev = thinker
        sta     _thinkercap+TH_PREV
        lda     ptr1+1
        sta     _thinkercap+TH_PREV+1
        rts

; void P_RemoveThinker(thinker_t *thinker)
_P_RemoveThinker:
        sta     ptr1
        stx     ptr1+1
        ldy     #TH_FUNCTION
        lda     #THINK_REMOVED
        sta     (ptr1),y
        iny
        lda     #0
        sta     (ptr1),y
        rts

; void P_UnlinkThinker(thinker_t *thinker)
_P_UnlinkThinker:
        sta     ptr1
        stx     ptr1+1
        ldy     #TH_NEXT
        lda     (ptr1),y
        sta     ptr2
        iny
        lda     (ptr1),y
        sta     ptr2+1
        ldy     #TH_PREV
        lda     (ptr1),y
        sta     ptr3
        iny
        lda     (ptr1),y
        sta     ptr3+1
        ldy     #TH_PREV                ; next->prev = prev
        lda     ptr3
        sta     (ptr2),y
        iny
        lda     ptr3+1
        sta     (ptr2),y
        ldy     #TH_NEXT                ; prev->next = next
        lda     ptr2
        sta     (ptr3),y
        iny
        lda     ptr2+1
        sta     (ptr3),y
        rts

; void P_RunThinkers(void)
_P_RunThinkers:
        lda     _thinkercap+TH_NEXT
        sta     rt_cur
        lda     _thinkercap+TH_NEXT+1
        sta     rt_cur+1
@loop:  lda     rt_cur
        cmp     #<_thinkercap
        bne     :+
        lda     rt_cur+1
        cmp     #>_thinkercap
        bne     :+
        rts
:       lda     rt_cur
        sta     ptr1
        lda     rt_cur+1
        sta     ptr1+1
        ldy     #TH_FUNCTION+1
        lda     (ptr1),y
        sta     cf_ptr+1
        dey
        lda     (ptr1),y
        sta     cf_ptr
        ora     cf_ptr+1
        beq     @next
        lda     cf_ptr+1
        bne     @run
        lda     cf_ptr
        cmp     #THINK_REMOVED
        bne     @run
        ; removed: out of the list, its memory back
        ldy     #TH_NEXT
        lda     (ptr1),y
        pha
        iny
        lda     (ptr1),y
        pha
        lda     rt_cur
        ldx     rt_cur+1
        jsr     _P_UnlinkThinker
        lda     rt_cur
        ldx     rt_cur+1
        jsr     free_thinker
        pla
        sta     rt_cur+1
        pla
        sta     rt_cur
        bra     @loop
@run:   lda     rt_cur
        ldx     rt_cur+1
        jsr     call_ax
@next:  lda     rt_cur
        sta     ptr1
        lda     rt_cur+1
        sta     ptr1+1
        ldy     #TH_NEXT
        lda     (ptr1),y
        sta     rt_cur
        iny
        lda     (ptr1),y
        sta     rt_cur+1
        bra     @loop

; the thinker A/X goes back to its pool
free_thinker:
        cpx     _mobjs+1
        bne     :+
        cmp     _mobjs
:       bcc     @block
        cpx     _mobjs_end+1
        bne     :+
        cmp     _mobjs_end
:       bcs     @block
        jmp     _P_FreeActor
@block: sec                             ; (A/X - tblocks) / 32
        sbc     tblocks
        sta     tmp1
        txa
        sbc     tblocks+1
        ldx     #5
:       lsr     a
        ror     tmp1
        dex
        bne     :-
        ldx     tmp1
        stz     tblock_used,x
        rts

; void P_Ticker(void)
_P_Ticker:
        lda     #<_player
        ldx     #>_player
        jsr     _P_PlayerThink
        jsr     _P_RunThinkers
        jsr     _P_RunStatics
        jsr     _P_UpdateSpecials
        inc     _leveltime
        bne     :+
        inc     _leveltime+1
:       rts

.endif ; DD_MAPDIR
