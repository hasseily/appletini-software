; Doom for the Appletini -- the tic command, the sound hook and the render
; packet, 6502 (docs/DESIGN.md sections 9, 10).
;
; The assembly twin of G_BuildTiccmd, S_StartSound and R_BuildView of
; g_game.c (the C is the reference, compiled on the host; its header says
; what the packet holds and how the things are chosen). The level flow and
; the entry points stay in g_game.c on both targets.

.include "gmacros.inc"
.include "gwork.inc"
.include "rview.inc"
.ifdef BANKED_GAME
.include "banked.inc"
.globalzp far_dst, far_ptr, far_len
.import kjt_far_write
.import _mi_viewflags
.endif

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR


.import is_static, info_ptr, fx_sine, fx_cosine, mul8
.import w_mov, w_fix, w_mul, w_cmp, w_ldo
.import _player, _rview, _kin, _leveltime, _snd_last, _snd_count
.import _mobjs, _mobjs_end, _statics, _statics_end, _mobjinfo, _st_sprite, _st_frame
.import _P_MobjThinker
.import popax, incsp2

.export _G_BuildTiccmd, _S_StartSound, _R_BuildView

PL      = _player
NBANDS  = 32
MAXCAND = 255
SLOWTURNTICS = 6
RV_NOCOLORMAP = $FF

; kin (kernel.h): +0 mouse_dx, +2 buttons, +3 move, +6 weapon
KIN_MOUSE   = 0
KIN_BUTTONS = 2
KIN_MOVE    = 3
KIN_WEAPON  = 6
KB_FIRE     = $01
KB_USE      = $02
KB_RUN      = $80
KM_FORWARD  = $01
KM_BACK     = $02
KM_LEFT     = $04
KM_RIGHT    = $08
KM_STRAFEL  = $10
KM_STRAFER  = $20

.segment "RODATA"
fwdmove:    .byte   $19, $32
sidemv:     .byte   $18, $28
turnlo:     .byte   <640, <1280, <320
turnhi:     .byte   >640, >1280, >320

.segment "BSS"
turnheld:   .res 1
tc_speed:   .res 1
tc_fwd:     .res 1
tc_side:    .res 1
; View construction runs after all thinkers and never traverses paths.
; Reuse the path-intercept scratch while producing the render packet.
.ifdef BANKED_GAME
.import _intercepts
view_work_offset .set 0
.macro VIEW_WORK name, count
name = _intercepts + view_work_offset
view_work_offset .set view_work_offset + count
.endmacro
.else
.macro VIEW_WORK name, count
name: .res count
.endmacro
.endif
VIEW_WORK band_head, NBANDS
VIEW_WORK band_hist, NBANDS
VIEW_WORK band_count, 1
VIEW_WORK band_limit, 1
VIEW_WORK band_full, 1
VIEW_WORK cand_lo, MAXCAND
VIEW_WORK cand_hi, MAXCAND
VIEW_WORK cand_next, MAXCAND
VIEW_WORK bv_px, 2
VIEW_WORK bv_py, 2
VIEW_WORK bv_n, 1
VIEW_WORK bv_cull, 1
VIEW_WORK bv_b, 1
VIEW_WORK bv_state, 2
VIEW_WORK bv_dx, 2
VIEW_WORK bv_dy, 2
VIEW_WORK bv_dot, 4
VIEW_WORK mv, 2
VIEW_WORK mc, 2
VIEW_WORK mr, 4
VIEW_WORK msign, 1
.ifdef BANKED_GAME
.assert view_work_offset <= MAXINTERCEPTS * 9, error, "view scratch exceeds intercept buffer"
.endif
.delmacro VIEW_WORK

.segment "CODE"

; ---- the tic command -------------------------------------------------------------------
; void G_BuildTiccmd(ticcmd_t *cmd)
_G_BuildTiccmd:
        sta     ptr2
        stx     ptr2+1
        lda     #0
        ldy     #TC_SIZE-1
:       sta     (ptr2),y
        dey
        bpl     :-
        sta     tc_fwd
        sta     tc_side
        sta     tc_speed
        bit     _kin+KIN_BUTTONS
        bpl     :+
        inc     tc_speed
:       lda     _kin+KIN_MOVE
        and     #KM_LEFT | KM_RIGHT
        beq     @noturn
        lda     turnheld
        cmp     #255
        beq     :+
        inc     turnheld
        bra     :+
@noturn:
        stz     turnheld
:       ldx     tc_speed
        lda     turnheld
        cmp     #SLOWTURNTICS
        bcs     :+
        ldx     #2                      ; the slow start of a turn
:       lda     _kin+KIN_MOVE
        and     #KM_RIGHT
        beq     :+
        sec
        ldy     #TC_ANGLETURN
        lda     (ptr2),y
        sbc     turnlo,x
        sta     (ptr2),y
        iny
        lda     (ptr2),y
        sbc     turnhi,x
        sta     (ptr2),y
:       lda     _kin+KIN_MOVE
        and     #KM_LEFT
        beq     :+
        clc
        ldy     #TC_ANGLETURN
        lda     (ptr2),y
        adc     turnlo,x
        sta     (ptr2),y
        iny
        lda     (ptr2),y
        adc     turnhi,x
        sta     (ptr2),y
:       ldx     tc_speed
        lda     _kin+KIN_MOVE
        and     #KM_FORWARD
        beq     :+
        clc
        lda     tc_fwd
        adc     fwdmove,x
        sta     tc_fwd
:       lda     _kin+KIN_MOVE
        and     #KM_BACK
        beq     :+
        sec
        lda     tc_fwd
        sbc     fwdmove,x
        sta     tc_fwd
:       lda     _kin+KIN_MOVE
        and     #KM_STRAFER
        beq     :+
        clc
        lda     tc_side
        adc     sidemv,x
        sta     tc_side
:       lda     _kin+KIN_MOVE
        and     #KM_STRAFEL
        beq     :+
        sec
        lda     tc_side
        sbc     sidemv,x
        sta     tc_side
:       ; the mouse turns: angleturn -= mouse_dx * 8
        lda     _kin+KIN_MOUSE
        sta     tmp1
        lda     _kin+KIN_MOUSE+1
        asl     tmp1
        rol     a
        asl     tmp1
        rol     a
        asl     tmp1
        rol     a
        sta     tmp2
        sec
        ldy     #TC_ANGLETURN
        lda     (ptr2),y
        sbc     tmp1
        sta     (ptr2),y
        iny
        lda     (ptr2),y
        sbc     tmp2
        sta     (ptr2),y
        ; (forward and side stay within +-MAXPLMOVE: 0x32 at most either way)
        lda     tc_fwd
        ldy     #TC_FORWARDMOVE
        sta     (ptr2),y
        lda     tc_side
        ldy     #TC_SIDEMOVE
        sta     (ptr2),y
        ldx     #0
        lda     _kin+KIN_BUTTONS
        and     #KB_FIRE
        beq     :+
        ldx     #BT_ATTACK
:       lda     _kin+KIN_BUTTONS
        and     #KB_USE
        beq     :+
        txa
        ora     #BT_USE
        tax
:       lda     _kin+KIN_WEAPON
        beq     :+
        cmp     #8
        bcs     :+
        dec     a
        asl     a
        asl     a
        asl     a
        ora     #BT_CHANGE
        stx     tmp1
        ora     tmp1
        tax
:       txa
        ldy     #TC_BUTTONS
        sta     (ptr2),y
        rts

; ---- the sound hook ---------------------------------------------------------------------
; void S_StartSound(mobj_t *origin, uint8_t sfx)
_S_StartSound:
        pha
        lda     _snd_count
        and     #7
        tax
        pla
        sta     _snd_last,x
        inc     _snd_count
        jmp     incsp2

; ---- the render packet -------------------------------------------------------------------
; file the thing A/X under its distance band from (bv_px, bv_py) by its
; map-unit position tmp3/tmp4 (x), ptr3 (y)
add_candidate:
        pha
        phx
        ; ax = |x - px| -> ptr1, ay = |y - py| -> ptr2
        sec
        lda     tmp3
        sbc     bv_px
        sta     ptr1
        lda     tmp4
        sbc     bv_px+1
        sta     ptr1+1
        bpl     :+
        sec
        lda     #0
        sbc     ptr1
        sta     ptr1
        lda     #0
        sbc     ptr1+1
        sta     ptr1+1
:       sec
        lda     ptr3
        sbc     bv_py
        sta     ptr2
        lda     ptr3+1
        sbc     bv_py+1
        sta     ptr2+1
        bpl     :+
        sec
        lda     #0
        sbc     ptr2
        sta     ptr2
        lda     #0
        sbc     ptr2+1
        sta     ptr2+1
:       ; d = ax + ay - min(ax, ay) / 2
        lda     ptr1
        cmp     ptr2
        lda     ptr1+1
        sbc     ptr2+1
        bcc     :+                      ; ax < ay: the smaller is ax
        lda     ptr2+1                  ; the smaller is ay
        lsr     a
        sta     tmp2
        lda     ptr2
        ror     a
        bra     :++
:       lda     ptr1+1
        lsr     a
        sta     tmp2
        lda     ptr1
        ror     a
:       sta     tmp1                    ; tmp2:tmp1 = min / 2
        clc
        lda     ptr1
        adc     ptr2
        sta     ptr1
        lda     ptr1+1
        adc     ptr2+1
        sta     ptr1+1
        sec
        lda     ptr1
        sbc     tmp1
        sta     ptr1
        lda     ptr1+1
        sbc     tmp2                    ; A = d >> 8
        ; band = d >= 4096 ? 31 : d >> 7
        cmp     #$10
        bcc     :+
        lda     #NBANDS-1
        bra     :++
:       asl     ptr1
        rol     a
:       tay
        tax
        lda     band_hist,x
        cmp     #255
        beq     :+
        inc     band_hist,x
:       plx
        pla
        cpy     band_limit
        beq     :+
        bcs     @rts                    ; past the limit: counted only
:       phx
        ldx     band_count
        cpx     #MAXCAND
        bne     :+
        plx
        lda     #1
        sta     band_full
@rts:   rts
:       sta     cand_lo,x
        pla
        sta     cand_hi,x
        lda     band_head,y
        sta     cand_next,x
        txa
        sta     band_head,y
        inc     band_count
        rts

; every actor and static with a sprite, but the player's mobj, into the bands
gather: ldx     #NBANDS-1
:       lda     #$FF
        sta     band_head,x
        stz     band_hist,x
        dex
        bpl     :-
        stz     band_count
        stz     band_full
        lda     _mobjs
        sta     gth
        lda     _mobjs+1
        sta     gth+1
@actor: lda     gth
        cmp     _mobjs_end
        bne     :+
        lda     gth+1
        cmp     _mobjs_end+1
        beq     @statics
:       ldy     #TH_FUNCTION
        lda     (gth),y
        cmp     #<_P_MobjThinker
        bne     @anext
        iny
        lda     (gth),y
        cmp     #>_P_MobjThinker
        bne     @anext
        lda     gth
        cmp     PL+PL_MO
        bne     :+
        lda     gth+1
        cmp     PL+PL_MO+1
        beq     @anext
:       ldy     #MO_FLAGS
        lda     (gth),y
        and     #MF0_NOSECTOR
        bne     @anext
        ldy     #MO_STATE
        lda     (gth),y
        iny
        ora     (gth),y
        beq     @anext
        ldy     #MO_X+2
        lda     (gth),y
        sta     tmp3
        iny
        lda     (gth),y
        sta     tmp4
        ldy     #MO_Y+2
        lda     (gth),y
        sta     ptr3
        iny
        lda     (gth),y
        sta     ptr3+1
        lda     gth
        ldx     gth+1
        jsr     add_candidate
@anext: clc
        lda     gth
        adc     #MO_SIZE
        sta     gth
        bcc     @actor
        inc     gth+1
        bra     @actor
@statics:
        lda     _statics
        sta     gth
        lda     _statics+1
        sta     gth+1
@static:
        lda     gth
        cmp     _statics_end
        bne     :+
        lda     gth+1
        cmp     _statics_end+1
        bne     :+
        rts
:       ldy     #SO_SFLAGS
        lda     (gth),y
        and     #SF_FREE
        bne     @snext
        ldy     #SO_TYPE
        lda     (gth),y
.ifdef BANKED_GAME
        ; Immutable per-type bits are in this bank: avoid a full metadata
        ; read and kernel-bank round trip for each static candidate.
        tax
        lda     _mi_viewflags,x
.else
        jsr     info_ptr
        ldy     #MI_FLAGS
        lda     (ptr1),y
.endif
        and     #MF0_NOSECTOR
        bne     @snext
        ldy     #SO_X
        lda     (gth),y
        sta     tmp3
        iny
        lda     (gth),y
        sta     tmp4
        ldy     #SO_Y
        lda     (gth),y
        sta     ptr3
        iny
        lda     (gth),y
        sta     ptr3+1
        lda     gth
        ldx     gth+1
        jsr     add_candidate
@snext: clc
        lda     gth
        adc     #SO_SIZE
        sta     gth
        bcc     @static
        inc     gth+1
        bra     @static

; the 4 bytes at (ptr4)+Y = W[X] >> 12 (arithmetic)
sar12_to:
        lda     W+3,x
        cmp     #$80
        lda     #0
        bcc     :+
        lda     #$FF
:       sta     tmp1                    ; the sign byte
        lda     W+1,x
        sta     tmp2
        lda     W+2,x
        sta     tmp3
        lda     W+3,x
        sta     tmp4
        phy
        ldy     #4
:       lda     tmp1
        cmp     #$80
        ror     tmp4
        ror     tmp3
        ror     tmp2
        dey
        bne     :-
        ply
        lda     tmp2
        sta     (ptr4),y
        iny
        lda     tmp3
        sta     (ptr4),y
        iny
        lda     tmp4
        sta     (ptr4),y
        iny
        lda     tmp1
        sta     (ptr4),y
        rts

; the 4 bytes at (ptr4)+Y = the int16 A/X << 4
shl4_to:
        sta     tmp2
        stx     tmp3
        txa
        cmp     #$80
        lda     #0
        bcc     :+
        lda     #$FF
:       sta     tmp4
        phy
        ldy     #4
:       asl     tmp2
        rol     tmp3
        rol     tmp4
        dey
        bne     :-
        ply
        lda     tmp2
        sta     (ptr4),y
        iny
        lda     tmp3
        sta     (ptr4),y
        iny
        lda     tmp4
        sta     (ptr4),y
        iny
        lda     tmp4
        cmp     #$80
        lda     #0
        bcc     :+
        lda     #$FF
:       sta     (ptr4),y
        rts

; ptr1 = the state bv_state's sprite / frame -> A (st_sprite / st_frame)
state_sprite:
        clc
        lda     bv_state
        adc     #<_st_sprite
        sta     ptr1
        lda     bv_state+1
        adc     #>_st_sprite
        sta     ptr1+1
        lda     (ptr1)
        rts
state_frame:
        clc
        lda     bv_state
        adc     #<_st_frame
        sta     ptr1
        lda     bv_state+1
        adc     #>_st_frame
        sta     ptr1+1
        lda     (ptr1)
        rts

; C set iff the thing at the map-unit offset (bv_dx, bv_dy) from the eye
; is not more than 64 units behind it: dx * cos + dy * sin >= -64 * 256,
; the cos and sin (>> 8: -256..256) in W_M2, W_M3 (their low words)
in_front:
        lda     bv_dx
        ldx     bv_dx+1
        ldy     #W_M2
        jsr     mul16s9
        ldx     #3
:       lda     mr,x
        sta     bv_dot,x
        dex
        bpl     :-
        lda     bv_dy
        ldx     bv_dy+1
        ldy     #W_M3
        jsr     mul16s9
        clc
        lda     bv_dot
        adc     mr
        lda     bv_dot+1
        adc     mr+1
        sta     tmp1
        lda     bv_dot+2
        adc     mr+2
        sta     tmp2
        lda     bv_dot+3
        adc     mr+3
        ; >= -16384 ($FFFFC000): the top bytes $FF, byte 1 >= $C0; or >= 0
        bpl     @yes
        cmp     #$FF
        bne     @no
        lda     tmp2
        cmp     #$FF
        bne     @no
        lda     tmp1
        cmp     #$C0
        bcs     @yes
@no:    clc
        rts
@yes:   sec
        rts

; mr = the int16 A/X * the int16 at W+Y (-256..256), 32 bits
mul16s9:
        sta     mv
        stx     mv+1
        txa
        eor     W+1,y
        sta     msign
        lda     W,y
        sta     mc
        lda     W+1,y
        sta     mc+1
        bpl     :+
        sec                             ; |c|
        lda     #0
        sbc     mc
        sta     mc
        lda     #0
        sbc     mc+1
        sta     mc+1
:       bit     mv+1
        bpl     :+
        sec                             ; |v|
        lda     #0
        sbc     mv
        sta     mv
        lda     #0
        sbc     mv+1
        sta     mv+1
:       stz     mr+3
        lda     mc+1
        beq     @byte
        stz     mr                      ; |c| = 256: |v| << 8
        lda     mv
        sta     mr+1
        lda     mv+1
        sta     mr+2
        bra     @sign
@byte:  lda     mv
        ldx     mc
        jsr     mul8
        sta     mr
        stx     mr+1
        lda     mv+1
        ldx     mc
        jsr     mul8
        clc
        adc     mr+1
        sta     mr+1
        txa
        adc     #0
        sta     mr+2
@sign:  bit     msign
        bpl     @rts
        sec
        lda     #0
        sbc     mr
        sta     mr
        lda     #0
        sbc     mr+1
        sta     mr+1
        lda     #0
        sbc     mr+2
        sta     mr+2
        lda     #0
        sbc     mr+3
        sta     mr+3
@rts:   rts

; bv_dx = A/X - bv_px / bv_dy = A/X - bv_py (map units)
dx_t0:  sec
        sbc     bv_px
        sta     bv_dx
        txa
        sbc     bv_px+1
        sta     bv_dx+1
        rts
dy_t1:  sec
        sbc     bv_py
        sta     bv_dy
        txa
        sbc     bv_py+1
        sta     bv_dy+1
        rts

; void R_BuildView(void)
_R_BuildView:
        lda     PL+PL_MO
        sta     gmo
        lda     PL+PL_MO+1
        sta     gmo+1
        ora     gmo
        bne     :+
        rts
:       lda     #<_rview
        sta     ptr4
        lda     #>_rview
        sta     ptr4+1
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T0
        ldy     #RV_X
        jsr     sar12_to
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        ldy     #RV_Y
        jsr     sar12_to
        ldx     #3
:       lda     PL+PL_VIEWZ,x
        sta     W+W_T0,x
        dex
        bpl     :-
        ldx     #W_T0
        ldy     #RV_Z
        jsr     sar12_to
        ldy     #MO_ANGLE
        lda     (gmo),y
        sta     _rview+RV_ANGLE
        iny
        lda     (gmo),y
        sta     _rview+RV_ANGLE+1
        lda     PL+PL_EXTRALIGHT
        sta     _rview+RV_EXTRALIGHT
        ; Doom's colormap c is the stored c >> 1; 0 and 32 (invulnerability): none
        lda     PL+PL_FIXEDCOLORMAP
        beq     :+
        cmp     #32
        beq     :+
        lsr     a
        bra     :++
:       lda     #RV_NOCOLORMAP
:       sta     _rview+RV_FIXEDCMAP
        lda     _leveltime
        sta     _rview+RV_TIC
        lda     _leveltime+1
        sta     _rview+RV_TIC+1
        ; the weapon layers
        stz     bv_n
        ldx     #0
        jsr     @layer
        ldx     #PS_SIZE
        jsr     @layer
        lda     bv_n
        sta     _rview+RV_NPSPRITES
        cmp     #2
        beq     @things
        lda     #$FF
        sta     _rview+RV_PSPRITES+RP_SIZE+RP_SPRITE
        lda     bv_n
        bne     @things
        lda     #$FF
        sta     _rview+RV_PSPRITES+RP_SPRITE
@things:
        ldy     #MO_X+2
        lda     (gmo),y
        sta     bv_px
        iny
        lda     (gmo),y
        sta     bv_px+1
        ldy     #MO_Y+2
        lda     (gmo),y
        sta     bv_py
        iny
        lda     (gmo),y
        sta     bv_py+1
        lda     #NBANDS-1
        sta     band_limit
        jsr     gather
        lda     band_full
        beq     @gathered
        ; too many: keep the bands that hold the nearest MAXCAND
        stz     tmp1
        stz     tmp2
        ldx     #0
:       clc
        lda     tmp1
        adc     band_hist,x
        sta     tmp1
        bcc     :+
        inc     tmp2
:       lda     tmp2                    ; the sum > MAXCAND (255)
        bne     :+
        inx
        cpx     #NBANDS
        bne     :--
:       txa
        beq     :+
        dec     a
:       sta     band_limit
        jsr     gather
@gathered:
        stz     bv_cull
        lda     band_count
        cmp     #RV_MAXTHINGS+1
        bcc     @nocull
        inc     bv_cull
        lda     PL+PL_MO
        sta     gmo
        lda     PL+PL_MO+1
        sta     gmo+1
        ldy     #MO_ANGLE               ; the fine angle: angle >> 3
        lda     (gmo),y
        sta     tmp1
        iny
        lda     (gmo),y
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        lsr     a
        ror     tmp1
        tax
        lda     tmp1
        pha
        phx
        jsr     fx_cosine
        ldx     #W_M2
        jsr     fr_sar8
        plx
        pla
        jsr     fx_sine
        ldx     #W_M3
        jsr     fr_sar8
@nocull:
        ; nearest bands first
        lda     #<(_rview + RV_THINGS)
        sta     ptr4
        lda     #>(_rview + RV_THINGS)
        sta     ptr4+1
        stz     bv_n
        stz     bv_b
@band:  ldx     bv_b
        cpx     #NBANDS
        jeq     @done
        lda     band_head,x
@cand:  cmp     #$FF
        jeq     @nextband
        ldx     bv_n
        cpx     #RV_MAXTHINGS
        jeq     @done
        tax
        phx
        lda     cand_lo,x
        sta     gth
        lda     cand_hi,x
        sta     gth+1
        tax
        lda     gth
        jsr     is_static
        jcc     @actor
        ; a static
        lda     bv_cull
        beq     :+
        ldy     #SO_X
        lda     (gth),y
        pha
        iny
        lda     (gth),y
        tax
        pla
        jsr     dx_t0
        ldy     #SO_Y
        lda     (gth),y
        pha
        iny
        lda     (gth),y
        tax
        pla
        jsr     dy_t1
        jsr     in_front
        jcc     @skip
:       ldy     #SO_X
        jsr     @s16
        ldy     #RT_X
        jsr     shl4_to
        ldy     #SO_Y
        jsr     @s16
        ldy     #RT_Y
        jsr     shl4_to
        ldy     #SO_Z
        jsr     @s16
        ldy     #RT_Z
        jsr     shl4_to
        ldy     #RT_ANGLE
        lda     #0
        sta     (ptr4),y
        ldy     #SO_ANGLE
        lda     (gth),y
        ldy     #RT_ANGLE+1
        sta     (ptr4),y
        ldy     #SO_STATE
        lda     (gth),y
        sta     bv_state
        iny
        lda     (gth),y
        sta     bv_state+1
        ldy     #SO_TYPE
        lda     (gth),y
.ifdef BANKED_GAME
        tax
        lda     _mi_viewflags,x
.else
        jsr     info_ptr
        ldy     #MI_FLAGS+2
        lda     (ptr1),y
.endif
        ldx     #SO_SECTOR
        bra     @common
@actor: lda     bv_cull
        beq     :+
        ldy     #MO_X+2
        jsr     @s16
        jsr     dx_t0
        ldy     #MO_Y+2
        jsr     @s16
        jsr     dy_t1
        jsr     in_front
        jcc     @skip
:       lda     gth
        sta     gmo
        lda     gth+1
        sta     gmo+1
        ldx     #W_T0
        ldy     #MO_X
        jsr     w_ldo
        ldx     #W_T0
        ldy     #RT_X
        jsr     sar12_to
        ldx     #W_T0
        ldy     #MO_Y
        jsr     w_ldo
        ldx     #W_T0
        ldy     #RT_Y
        jsr     sar12_to
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T0
        ldy     #RT_Z
        jsr     sar12_to
        ldy     #MO_ANGLE
        lda     (gth),y
        ldy     #RT_ANGLE
        sta     (ptr4),y
        ldy     #MO_ANGLE+1
        lda     (gth),y
        ldy     #RT_ANGLE+1
        sta     (ptr4),y
        ldy     #MO_STATE
        lda     (gth),y
        sta     bv_state
        iny
        lda     (gth),y
        sta     bv_state+1
        ldy     #MO_FLAGS+2
        lda     (gth),y
        ldx     #MO_SECTOR
@common:
        ; A = the flags' byte 2 (MF2_SHADOW), X = the offset of its sector
        and     #MF2_SHADOW
        beq     :+
        lda     #RT_SHADOW
:       ldy     #RT_FLAGS
        sta     (ptr4),y
        txa
        tay
        lda     (gth),y
        pha
        iny
        lda     (gth),y
        ldy     #RT_SECTOR+1
        sta     (ptr4),y
        dey
        pla
        sta     (ptr4),y
        jsr     state_sprite
        ldy     #RT_SPRITE
        sta     (ptr4),y
        jsr     state_frame
        ldy     #RT_FRAME
        sta     (ptr4),y
        ldy     #RT_FLAGS+1             ; the pad byte
        lda     #0
        sta     (ptr4),y
        clc
        lda     ptr4
        adc     #RT_SIZE
        sta     ptr4
        bcc     :+
        inc     ptr4+1
:
        inc     bv_n
@skip:  plx
        lda     cand_next,x
        jmp     @cand
@nextband:
        inc     bv_b
        jmp     @band
@done:  lda     bv_n
        sta     _rview+RV_NTHINGS
.ifdef BANKED_GAME
        jsr     packet_flush
.endif
        rts
; A/X = the int16 at (gth)+Y
@s16:   lda     (gth),y
        pha
        iny
        lda     (gth),y
        tax
        pla
        rts
; the weapon layer at psprites + X, if on, into the packet
@layer: lda     PL+PL_PSPRITES+PS_STATE,x
        sta     bv_state
        lda     PL+PL_PSPRITES+PS_STATE+1,x
        sta     bv_state+1
        ora     bv_state
        beq     @off
        phx
        lda     bv_n
        ldy     #RP_SIZE
        cmp     #0
        beq     :+
        ldy     #RP_SIZE*2
:       tya
        sec
        sbc     #RP_SIZE                ; the packet's layer: bv_n * RP_SIZE
        tay
        jsr     state_sprite
        sta     _rview+RV_PSPRITES+RP_SPRITE,y
        jsr     state_frame
        sta     _rview+RV_PSPRITES+RP_FRAME,y
        plx
        lda     #8
        sta     tmp1
:       lda     PL+PL_PSPRITES+PS_SX,x
        sta     _rview+RV_PSPRITES+RP_SX,y
        inx
        iny
        dec     tmp1
        bne     :-
        inc     bv_n
@off:   rts
.assert RP_SY = RP_SX + 4, error, "sx and sy copied at once"

.ifdef BANKED_GAME
; The packet lives in this code bank's spare LC RAM. The main-LC kernel
; cannot read that RAM after the gateway turns ALTZP off, so first copy
; each chunk through the now-dead candidate/path scratch in main memory.
; All pointers are initialized afresh for each chunk; no flush state lives
; in _intercepts, which is overwritten by the first copy.
RV_PACKET_SIZE = RV_HEADER + RV_MAXTHINGS * RT_SIZE
PACKET_CHUNK_SIZE = 1024
.assert RV_PACKET_SIZE = 2600, error, "packet flush layout changed"
.assert PACKET_CHUNK_SIZE <= MAXINTERCEPTS * 9, error, "packet chunk exceeds scratch"
.macro PACKET_CHUNK offset, length
        .local page, tail
        lda     #<(_rview + offset)
        sta     ptr1
        lda     #>(_rview + offset)
        sta     ptr1+1
        lda     #<_intercepts
        sta     ptr2
        lda     #>_intercepts
        sta     ptr2+1
        ldy     #0
        ldx     #>(length)
page:   lda     (ptr1),y
        sta     (ptr2),y
        iny
        bne     page
        inc     ptr1+1
        inc     ptr2+1
        dex
        bne     page
.if <(length)
        ldx     #<(length)
tail:   lda     (ptr1),y
        sta     (ptr2),y
        iny
        dex
        bne     tail
.endif
        lda     #<(PACKET_BASE + offset)
        sta     far_dst
        lda     #>(PACKET_BASE + offset)
        sta     far_dst+1
        lda     #PACKET_BANK
        sta     far_dst+2
        lda     #<_intercepts
        sta     far_ptr
        lda     #>_intercepts
        sta     far_ptr+1
        lda     #<(length)
        sta     far_len
        lda     #>(length)
        sta     far_len+1
        jsr     kjt_far_write
.endmacro

packet_flush:
        PACKET_CHUNK PACKET_CHUNK_SIZE, PACKET_CHUNK_SIZE
        PACKET_CHUNK PACKET_CHUNK_SIZE * 2, RV_PACKET_SIZE - PACKET_CHUNK_SIZE * 2
        ; Publish the header last, after every record it describes is ready.
        PACKET_CHUNK 0, PACKET_CHUNK_SIZE
        rts
.delmacro PACKET_CHUNK
.endif

; W[X] = W_FR >> 8 (arithmetic)
fr_sar8:
        lda     W+W_FR+1
        sta     W,x
        lda     W+W_FR+2
        sta     W+1,x
        lda     W+W_FR+3
        sta     W+2,x
        cmp     #$80
        lda     #0
        bcc     :+
        lda     #$FF
:       sta     W+3,x
        rts

.endif ; DD_MAPDIR
