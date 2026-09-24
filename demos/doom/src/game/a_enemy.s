; Doom for the Appletini -- the monsters' minds, 6502 (docs/DESIGN.md section 9).
;
; The assembly twin of p_enemy.c (the C is the reference, compiled on the
; host; read it for the why of each step): the sound flood (P_NoiseAlert),
; A_Look and P_LookForPlayers, A_Chase with P_Move, P_TryWalk and
; P_NewChaseDir, the range checks, A_FaceTarget, the attacks of the
; episode 1 monsters, the death actions and A_BossDeath. The actions are
; cc65 __fastcall__ (the actor in A/X), as P_SetMobjState calls them.
;
; Reentrancy is vanilla's. P_Move's P_TryMove, P_LineAttack, P_DamageMobj
; and P_SetMobjState may run other actions inside (a charging lost soul
; hurts a monster whose A_Chase runs at once, a monster's A_Chase that
; loses its target runs A_Look): a routine that needs something after
; such a call keeps it on the 6502 stack, as C keeps its locals
; (P_NewChaseDir's directions, A_SPosAttack's loop, the actor itself).
;
; The sound flood is vanilla's P_RecursiveSound as a queue (the result,
; which sectors get the sound target, is the same; recursion over the
; sectors would not fit the 6502's stack), with two savings that do not
; change it:
;   - each sector's two-sided neighbours (other sector, sound-blocking
;     bit) are gathered from its lines once per level, into a table in the
;     game's far bank (after the far tables and the set-up overlay), so a
;     flood reads one short far block per sector instead of its lines;
;   - an alert from a sector already flooded since the last height change
;     (P_SetSectorFloor/Ceiling count them: sec_changes) changes nothing
;     and is skipped: the flood is a function of the start and the
;     openings, and it only ever writes the same target (the player).
;
; For the py65 harness this code may sit in a code-only window (MCODE,
; gmacros.inc): its tables are in RODATA, it reads no inline data.

.include "gmacros.inc"
.include "gwork.inc"

; (only with the converted data: the stand-in data set builds the
; platform's GAME skeleton, src/game/game.c)
.ifdef DD_MAPDIR

.globalzp far_src, far_dst, far_ptr, far_len
.import kjt_far_read, kjt_far_write
.import lev_addr, lev_idx, lev_far, far_rd, line_get
.import check_sight, sg_t1, sg_t2, sight_reset
.import set_state, try_move, aprox_dist, info_ptr, mul8
.import fx_mul, fx_div, fx_sine, fx_cosine, fxa, fxb, fxr
.import w_ldo, w_sto, w_mov, w_cmp, w_sub3, w_abs, w_add, ret_w
.import _P_Random, _P_SubRandom, _S_StartSound, _R_PointToAngle2, _P_AproxDistance
.import _P_AimLineAttack, _P_LineAttack, _P_SpawnMissile, _P_DamageMobj, _P_RadiusAttack
.import _P_UseSpecialLine, _EV_DoFloorTag, _P_ArenaAlloc, _kernel_crash
.import _P_MobjThinker, _mobjinfo, _player, _gameskill, _gamemap, _game_far_bank
.import _mobjs, _mobjs_end, _statics, _statics_end
.import _numsectors, _sec_soundtarget, _sec_floorh, _sec_ceilh, _sec_changes
.import _floatok, _numspechit, _spechit
.import __GFAR_SIZE__, __GOVL_SIZE__, _levarr
.import pushax, pusha, pusheax, popax

.export _P_NoiseAlert, _P_MonstersSetupLevel
.export _A_Look, _A_Chase, _A_FaceTarget, _A_PosAttack, _A_SPosAttack, _A_TroopAttack
.export _A_SargAttack, _A_HeadAttack, _A_BruisAttack, _A_SkullAttack
.export _A_Scream, _A_XScream, _A_Pain, _A_Fall, _A_Explode, _A_BossDeath, _A_PlayerScream
.export mo_sound, mo_info, push_field, angle_to_target, angle_to, random_mod

PL          = _player
; vanilla's directions (p_local.h: DI_NODIR comes from goffsets.inc)
DI_EAST     = 0
DI_NORTH    = 2
DI_WEST     = 4
DI_SOUTH    = 6
DI_SOUTHEAST = 7
.assert DI_NODIR = 8, error, "the directions of p_local.h"
MELEE_HI    = 64                    ; MELEERANGE >> 16
SND_QUEUE   = 64                    ; the flood's ring of (sector, level)
SND_PIECE   = 32                    ; neighbour entries read or written at a time
ML_SOUNDBLOCK = 64
; the neighbour table in the game's far bank: after the far tables and the
; set-up overlay that game_farinit copied there from $0200 (fixed.s)
SND_TABLE   = ($0200 + __GFAR_SIZE__ + __GOVL_SIZE__ + 1) & $FFFE

.segment "BSS"
; per level (the arena)
snd_trav:   .res 2                  ; numsectors bytes: 0 unreached, else level + 1, bit 7 pending
snd_built:  .res 2                  ; bitset: the sector's neighbours are in the table
snd_from:   .res 2                  ; bitset: flooded from here since snd_gen
snd_bytes:  .res 2                  ; (numsectors + 7) >> 3
snd_gen:    .res 1                  ; sec_changes when snd_from was cleared
snd_target: .res 2                  ; the target of the floods in snd_from
; one flood
nz_target:  .res 2
q_sec_lo:   .res SND_QUEUE
q_sec_hi:   .res SND_QUEUE
q_lvl:      .res SND_QUEUE
q_head:     .res 1
q_tail:     .res 1
q_over:     .res 1                  ; the queue overflowed: pending sectors to find
ex_sec:     .res 2                  ; the sector being expanded
ex_lvl:     .res 1
ex_rec:                             ; its SECTOR record's linecount, firstline
ex_count:   .res 2
ex_first:   .res 2
ex_n:       .res 1                  ; entries in ex_buf
ex_buf:     .res SND_PIECE * 2
ex_floor:   .res 2
ex_ceil:    .res 2
rc_sec:     .res 2                  ; reach's sector and level
rc_lvl:     .res 1
bt_i:       .res 2                  ; building: the SECLINES index
bt_line:    .res 2
; the actions (each is used before any call that may come back here, or
; kept on the 6502 stack across it)
ac:         .res 2                  ; the actor
ac_ang:     .res 2
ac_slope:   .res 4
ac_dmg:     .res 2
ac_sound:   .res 1
nc_old:     .res 1                  ; P_NewChaseDir (kept across P_TryWalk)
nc_turn:    .res 1
nc_d1:      .res 1
nc_d2:      .res 1
nc_tdir:    .res 1
nc_ygtx:    .res 1                  ; bit 7: |deltay| > |deltax|
NC_SIZE     = 6
cm_dist:    .res 2                  ; P_CheckMissileRange
mv_good:    .res 1                  ; P_Move
mv_try:     .res 8                  ; tryx, tryy

.segment "RODATA"
; vanilla's opposite[] and diags[]
opposite:   .byte 4, 5, 6, 7, 0, 1, 2, 3, 8
diags:      .byte 3, 1, 5, 7
; vanilla's xspeed/yspeed per direction as a code: 0 none, 1 +FRACUNIT,
; 2 +47000, $81 -FRACUNIT, $82 -47000
xcode:      .byte 1, 2, 0, $82, $81, $82, 0, 2
ycode:      .byte 0, 2, 1, 2, 0, $82, $81, $82
bitmask:    .byte 1, 2, 4, 8, 16, 32, 64, 128

MONCODE

; ---- helpers ---------------------------------------------------------------------------
; ptr1 = &mobjinfo[gmo->type]
mo_info:
        ldy     #MO_TYPE
        lda     (gmo),y
        jmp     info_ptr

; S_StartSound(gmo, A)
mo_sound:
        pha
        lda     gmo
        ldx     gmo+1
        jsr     pushax
        pla
        jmp     _S_StartSound

; the fixed_t at (gmo)+Y onto the C stack
push_field:
        ldx     #W_T0
        jsr     w_ldo
        ldx     #W_T0
        jsr     ret_w
        jmp     pusheax

; A/X = R_PointToAngle2(gmo->x, gmo->y, gmo->target->x, gmo->target->y)
; (angle_to: to the mobj at gpt); gmo is kept
angle_to_target:
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
angle_to:
        lda     gpt
        pha
        lda     gpt+1
        pha
        ldy     #MO_X
        jsr     push_field
        ldy     #MO_Y
        jsr     push_field
        pla
        sta     gpt+1
        pla
        sta     gpt
        ldx     #3
        ldy     #MO_X+3
:       lda     (gpt),y                 ; its x onto the C stack
        pha
        dey
        dex
        bpl     :-
        lda     sp
        sec
        sbc     #4
        sta     sp
        bcs     :+
        dec     sp+1
:       ldy     #0
:       pla
        sta     (sp),y
        iny
        cpy     #4
        bne     :-
        ldy     #MO_Y+3                 ; its y in A/X/sreg
        lda     (gpt),y
        sta     sreg+1
        dey
        lda     (gpt),y
        sta     sreg
        dey
        lda     (gpt),y
        tax
        dey
        lda     (gpt),y
        jmp     _R_PointToAngle2

; gmo = gmo->target
gmo_target:
        ldy     #MO_TARGET+1
        lda     (gmo),y
        tax
        dey
        lda     (gmo),y
        sta     gmo
        stx     gmo+1
        rts

; A = P_Random() % A (A > 0), by subtraction
random_mod:
        sta     tmp4
        jsr     _P_Random
:       cmp     tmp4
        bcc     :+
        sbc     tmp4
        bra     :-
:       rts

; gmo = ac
gmo_ac: lda     ac
        sta     gmo
        lda     ac+1
        sta     gmo+1
        rts

; the action's argument: ac = gmo = A/X
action: sta     ac
        sta     gmo
        stx     ac+1
        stx     gmo+1
        rts

; Z set iff gmo->target is NULL
no_target:
        ldy     #MO_TARGET
        lda     (gmo),y
        iny
        ora     (gmo),y
        rts

; ptr1 = &sec_X[A/X] for the 2-byte arrays: ptr1 the floors, ptr2 the ceilings
sec_hptrs:
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

; ---- P_MonstersSetupLevel ------------------------------------------------------------------
_P_MonstersSetupLevel:
        jsr     sight_reset
        ; the flood's arrays: trav (numsectors), built and from (bitsets)
        lda     _numsectors
        ldx     _numsectors+1
        jsr     _P_ArenaAlloc
        sta     snd_trav
        stx     snd_trav+1
        clc
        lda     _numsectors
        adc     #7
        sta     snd_bytes
        lda     _numsectors+1
        adc     #0
        lsr     a
        ror     snd_bytes
        lsr     a
        ror     snd_bytes
        lsr     a
        ror     snd_bytes
        sta     snd_bytes+1
        ldx     snd_bytes+1
        lda     snd_bytes
        jsr     _P_ArenaAlloc
        sta     snd_built
        stx     snd_built+1
        ldx     snd_bytes+1
        lda     snd_bytes
        jsr     _P_ArenaAlloc
        sta     snd_from
        stx     snd_from+1
        lda     _sec_changes
        sta     snd_gen
        stz     snd_target
        stz     snd_target+1
        ; the table must fit the far bank: 2 bytes per SECLINES entry
        lda     _levarr+LA_SIZE*MAPARR_SECLINES+LA_COUNT
        sta     tmp1
        lda     _levarr+LA_SIZE*MAPARR_SECLINES+LA_COUNT+1
        asl     tmp1
        rol     a
        bcs     @big
        tax
        clc
        lda     tmp1
        adc     #<SND_TABLE
        txa
        adc     #>SND_TABLE
        bcs     @big
        cmp     #$C0
        bcs     @big
        rts
@big:   lda     #CRASH_ARENA
        jmp     _kernel_crash

; ---- the sound flood (vanilla P_NoiseAlert, P_RecursiveSound) --------------------------------
; void P_NoiseAlert(mobj_t *target, mobj_t *emitter)
_P_NoiseAlert:
        sta     gmo
        stx     gmo+1
        jsr     popax
        sta     nz_target
        stx     nz_target+1
        ; a new target or a height change since: every flood may differ
        lda     nz_target
        cmp     snd_target
        bne     @forget
        lda     nz_target+1
        cmp     snd_target+1
        bne     @forget
        lda     _sec_changes
        cmp     snd_gen
        beq     @known
@forget:
        lda     nz_target
        sta     snd_target
        lda     nz_target+1
        sta     snd_target+1
        lda     _sec_changes
        sta     snd_gen
        lda     snd_from
        ldx     snd_from+1
        jsr     clear_bits
@known: ; flooded from the emitter's sector already: nothing would change
        ldy     #MO_SECTOR
        lda     (gmo),y
        sta     rc_sec
        iny
        lda     (gmo),y
        sta     rc_sec+1
        lda     snd_from
        ldx     snd_from+1
        jsr     bit_of                  ; rc_sec -> ptr1, A = mask
        and     (ptr1)
        beq     :+
        rts
:       lda     tmp3
        ora     (ptr1)
        sta     (ptr1)
        ; a new flood: nothing traversed
        lda     snd_trav
        sta     ptr1
        lda     snd_trav+1
        sta     ptr1+1
        lda     _numsectors
        ldx     _numsectors+1
        jsr     clear_mem
        stz     q_head
        stz     q_tail
        stz     q_over
        stz     rc_lvl
        jsr     reach
@next:  ; the queue, then (after an overflow) the sectors left pending
        ldx     q_head
        cpx     q_tail
        beq     @empty
        lda     q_sec_lo,x
        sta     ex_sec
        lda     q_sec_hi,x
        sta     ex_sec+1
        lda     q_lvl,x
        sta     ex_lvl
        inx
        txa
        and     #SND_QUEUE - 1
        sta     q_head
        ; (reached again at a lower level since: that expansion counts)
        jsr     trav_ptr
        lda     (ptr1)
        and     #$7F
        sec
        sbc     #1
        cmp     ex_lvl
        bne     @next
        jsr     expand
        bra     @next
@empty: lda     q_over
        beq     @done
        stz     q_over
        jsr     pending
        bra     @next
@done:  rts

; the pending sectors (bit 7 of trav) back into the queue, as far as it goes
pending:
        stz     ex_sec
        stz     ex_sec+1
@loop:  lda     ex_sec
        cmp     _numsectors
        lda     ex_sec+1
        sbc     _numsectors+1
        bcs     @rts
        jsr     trav_ptr
        lda     (ptr1)
        bpl     @skip
        and     #$7F
        dec     a
        tax                             ; the level
        lda     q_tail                  ; full: stays pending for the next round
        inc     a
        and     #SND_QUEUE - 1
        cmp     q_head
        bne     :+
        inc     q_over
        bra     @rts
:       lda     (ptr1)
        and     #$7F
        sta     (ptr1)
        ldy     q_tail
        lda     ex_sec
        sta     q_sec_lo,y
        lda     ex_sec+1
        sta     q_sec_hi,y
        txa
        sta     q_lvl,y
        iny
        tya
        and     #SND_QUEUE - 1
        sta     q_tail
@skip:  inc     ex_sec
        bne     @loop
        inc     ex_sec+1
        bra     @loop
@rts:   rts

; ptr1 = &snd_trav[ex_sec]
trav_ptr:
        clc
        lda     snd_trav
        adc     ex_sec
        sta     ptr1
        lda     snd_trav+1
        adc     ex_sec+1
        sta     ptr1+1
        rts

; vanilla's entry test of P_RecursiveSound for (rc_sec, rc_lvl): if not
; flooded at this level or lower, the sound target is set and the sector
; queued for expansion
reach:  clc
        lda     snd_trav
        adc     rc_sec
        sta     ptr1
        lda     snd_trav+1
        adc     rc_sec+1
        sta     ptr1+1
        lda     (ptr1)
        and     #$7F
        beq     @new
        sec                             ; traversed <= level + 1: already flooded
        sbc     #1
        cmp     rc_lvl
        bcc     @rts
        beq     @rts
@new:   ldx     rc_lvl
        inx
        txa
        sta     (ptr1)
        ; the sector's sound target
        lda     rc_sec
        asl     a
        sta     tmp1
        lda     rc_sec+1
        rol     a
        sta     tmp2
        clc
        lda     _sec_soundtarget
        adc     tmp1
        sta     ptr2
        lda     _sec_soundtarget+1
        adc     tmp2
        sta     ptr2+1
        lda     nz_target
        sta     (ptr2)
        ldy     #1
        lda     nz_target+1
        sta     (ptr2),y
        ; queued (or pending if the queue is full)
        lda     q_tail
        inc     a
        and     #SND_QUEUE - 1
        cmp     q_head
        bne     :+
        lda     (ptr1)
        ora     #$80
        sta     (ptr1)
        inc     q_over
        rts
:       ldy     q_tail
        sta     q_tail
        lda     rc_sec
        sta     q_sec_lo,y
        lda     rc_sec+1
        sta     q_sec_hi,y
        lda     rc_lvl
        sta     q_lvl,y
@rts:   rts

; flood on from ex_sec at level ex_lvl through its open two-sided lines
expand: jsr     neighbours_ready
        ; its heights
        lda     ex_sec
        ldx     ex_sec+1
        jsr     sec_hptrs
        lda     (ptr1)
        sta     ex_floor
        ldy     #1
        lda     (ptr1),y
        sta     ex_floor+1
        lda     (ptr2)
        sta     ex_ceil
        lda     (ptr2),y
        sta     ex_ceil+1
@piece: lda     ex_count
        ora     ex_count+1
        bne     :+
        rts
:       jsr     read_piece              ; ex_buf, ex_n entries; ex_first, ex_count advanced
        ldx     #0
@entry: cpx     ex_n
        beq     @piece
        phx
        txa
        asl     a
        tax
        lda     ex_buf+1,x
        cmp     #$FF
        bne     :+
        lda     ex_buf,x
        cmp     #$FF
        beq     @skip                   ; not two-sided
:       lda     ex_buf,x
        sta     rc_sec
        lda     ex_buf+1,x
        and     #$7F
        sta     rc_sec+1
        ; openrange <= 0 (a closed door): the lower ceiling not above the
        ; higher floor
        lda     rc_sec
        ldx     rc_sec+1
        jsr     sec_hptrs
        jsr     opening
        bcc     @skip
        plx
        phx
        txa
        asl     a
        tax
        lda     ex_buf+1,x
        bpl     @plain
        lda     ex_lvl                  ; sound-blocking: only from level 0, to 1
        bne     @skip
        lda     #1
        sta     rc_lvl
        jsr     reach
        bra     @skip
@plain: lda     ex_lvl
        sta     rc_lvl
        jsr     reach
@skip:  plx
        inx
        bra     @entry

; C set iff min(ceilings) > max(floors) of ex_sec and the sector at
; ptr1/ptr2 (their floor and ceiling)
opening:
        ; tmp1/tmp2 = the lower ceiling
        ldy     #1
        lda     (ptr2)
        cmp     ex_ceil
        lda     (ptr2),y
        sbc     ex_ceil+1
        bvc     :+
        eor     #$80
:       bmi     @oc
        lda     ex_ceil
        sta     tmp1
        lda     ex_ceil+1
        sta     tmp2
        bra     @fl
@oc:    lda     (ptr2)
        sta     tmp1
        lda     (ptr2),y
        sta     tmp2
@fl:    ; tmp3/tmp4 = the higher floor
        lda     (ptr1)
        cmp     ex_floor
        lda     (ptr1),y
        sbc     ex_floor+1
        bvc     :+
        eor     #$80
:       bpl     @of
        lda     ex_floor
        sta     tmp3
        lda     ex_floor+1
        sta     tmp4
        bra     @cmp
@of:    lda     (ptr1)
        sta     tmp3
        lda     (ptr1),y
        sta     tmp4
@cmp:   ; floor < ceiling (signed): C set
        lda     tmp3
        cmp     tmp1
        lda     tmp4
        sbc     tmp2
        bvc     :+
        eor     #$80
:       asl     a                       ; C = the sign: set iff floor < ceiling
        rts

; ex_count, ex_first = ex_sec's line list (its SECTOR record); its
; neighbour entries built into the table if this is its first flood
neighbours_ready:
        lda     ex_sec
        sta     lev_idx
        lda     ex_sec+1
        sta     lev_idx+1
        lda     #MAPARR_SECTORS
        jsr     lev_addr
        clc
        lda     lev_far
        adc     #SECTOR_LINECOUNT
        sta     lev_far
        bcc     :+
        inc     lev_far+1
:       lda     #<ex_rec
        sta     far_ptr
        lda     #>ex_rec
        sta     far_ptr+1
        lda     #4
        sta     far_len
        stz     far_len+1
        jsr     far_rd
.assert SECTOR_FIRSTLINE = SECTOR_LINECOUNT + 2, error, "linecount, firstline"
        lda     ex_sec
        sta     rc_sec
        lda     ex_sec+1
        sta     rc_sec+1
        lda     snd_built
        ldx     snd_built+1
        jsr     bit_of
        and     (ptr1)
        beq     :+
        rts
:       lda     tmp3
        ora     (ptr1)
        sta     (ptr1)
        ; build: one entry per line of its list, written a piece at a time
        lda     ex_first
        sta     bt_i
        lda     ex_first+1
        sta     bt_i+1
        lda     ex_count
        pha
        lda     ex_count+1
        pha
@piece: stz     ex_n
@line:  lda     ex_count
        ora     ex_count+1
        jeq     @flush
        lda     ex_n
        cmp     #SND_PIECE
        jeq     @flush
        ; SECLINES[bt_i]
        lda     bt_i
        clc
        adc     ex_n
        sta     lev_idx
        lda     bt_i+1
        adc     #0
        sta     lev_idx+1
        lda     #MAPARR_SECLINES
        jsr     lev_addr
        lda     #<bt_line
        sta     far_ptr
        lda     #>bt_line
        sta     far_ptr+1
        lda     #2
        sta     far_len
        stz     far_len+1
        jsr     far_rd
        lda     bt_line
        ldx     bt_line+1
        jsr     line_get
        ; two-sided with a back sector: the other sector, bit 15 if
        ; sound-blocking; else $FFFF
        lda     ex_n
        asl     a
        tax
        lda     #$FF
        sta     ex_buf,x
        sta     ex_buf+1,x
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_TWOSIDED
        beq     @next
        ldy     #LI_BACKSECTOR+1
        lda     (gli),y
        dey
        and     (gli),y
        cmp     #$FF
        beq     @next
        ; the other sector: the back one if the front is ex_sec, else the front
        ldy     #LI_FRONTSECTOR
        lda     (gli),y
        cmp     ex_sec
        bne     @isfront
        iny
        lda     (gli),y
        cmp     ex_sec+1
        bne     @isfront
        ldy     #LI_BACKSECTOR
        bra     @take
@isfront:
        ldy     #LI_FRONTSECTOR
@take:  lda     (gli),y
        sta     ex_buf,x
        iny
        lda     (gli),y
        sta     ex_buf+1,x
        ldy     #LI_FLAGS
        lda     (gli),y
        and     #ML_SOUNDBLOCK
        beq     @next
        lda     ex_buf+1,x
        ora     #$80
        sta     ex_buf+1,x
@next:  inc     ex_n
        lda     ex_count
        bne     :+
        dec     ex_count+1
:       dec     ex_count
        jmp     @line
@flush: lda     ex_n
        beq     @built
        ; far_write(ex_buf, table + 2 * bt_i, 2 * ex_n)
        lda     bt_i
        asl     a
        sta     far_dst
        lda     bt_i+1
        rol     a
        sta     far_dst+1
        clc
        lda     far_dst
        adc     #<SND_TABLE
        sta     far_dst
        lda     far_dst+1
        adc     #>SND_TABLE
        sta     far_dst+1
        lda     _game_far_bank
        sta     far_dst+2
        lda     #<ex_buf
        sta     far_ptr
        lda     #>ex_buf
        sta     far_ptr+1
        lda     ex_n
        asl     a
        sta     far_len
        stz     far_len+1
        jsr     kjt_far_write
        clc
        lda     bt_i
        adc     ex_n
        sta     bt_i
        bcc     :+
        inc     bt_i+1
:       jmp     @piece
@built: pla
        sta     ex_count+1
        pla
        sta     ex_count
        rts

; up to SND_PIECE entries of ex_first.. from the table into ex_buf (ex_n);
; ex_first, ex_count advanced
read_piece:
        lda     ex_count+1
        bne     :+
        lda     ex_count
        cmp     #SND_PIECE
        bcc     :++
:       lda     #SND_PIECE
:       sta     ex_n
        lda     ex_first
        asl     a
        sta     far_src
        lda     ex_first+1
        rol     a
        sta     far_src+1
        clc
        lda     far_src
        adc     #<SND_TABLE
        sta     far_src
        lda     far_src+1
        adc     #>SND_TABLE
        sta     far_src+1
        lda     _game_far_bank
        sta     far_src+2
        lda     #<ex_buf
        sta     far_ptr
        lda     #>ex_buf
        sta     far_ptr+1
        lda     ex_n
        asl     a
        sta     far_len
        stz     far_len+1
        jsr     kjt_far_read
        clc
        lda     ex_first
        adc     ex_n
        sta     ex_first
        bcc     :+
        inc     ex_first+1
:       sec
        lda     ex_count
        sbc     ex_n
        sta     ex_count
        bcs     :+
        dec     ex_count+1
:       rts

; the bit of rc_sec in the bitset A/X: ptr1 = its byte, A = tmp3 = its mask
bit_of: sta     ptr1
        stx     ptr1+1
        lda     rc_sec+1
        sta     tmp1
        lda     rc_sec
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        lsr     tmp1
        ror     a
        clc
        adc     ptr1
        sta     ptr1
        lda     tmp1
        adc     ptr1+1
        sta     ptr1+1
        lda     rc_sec
        and     #7
        tax
        lda     bitmask,x
        sta     tmp3
        rts

; clear the snd_bytes bytes of the bitset A/X
clear_bits:
        sta     ptr1
        stx     ptr1+1
        lda     snd_bytes
        ldx     snd_bytes+1
; clear A/X bytes at ptr1
clear_mem:
        sta     tmp1
        stx     tmp2
        lda     #0
        ldx     tmp2
        beq     @part
        ldy     #0
@page:  sta     (ptr1),y
        iny
        bne     @page
        inc     ptr1+1
        dex
        bne     @page
@part:  ldy     tmp1
        beq     @rts
@b:     dey
        sta     (ptr1),y
        cpy     #0
        bne     @b
@rts:   rts

; ---- range checks ------------------------------------------------------------------------------
; C set iff gmo's target is within melee range and in sight (vanilla
; P_CheckMeleeRange); gmo kept
check_melee:
        jsr     no_target
        bne     :+
        clc
        rts
:       ; P_AproxDistance(pl->x - x, pl->y - y) >= MELEERANGE - 20 + pl's radius: no
        jsr     target_delta            ; W_T0, W_T1 = target - gmo; gpt = target
        jsr     aprox_dist              ; W_FR
        ldy     #MO_TYPE
        lda     (gpt),y
        jsr     info_ptr
        ldy     #MI_RADIUS
        lda     (ptr1),y
        clc
        adc     #MELEE_HI - 20
        sta     tmp1
        lda     #0
        adc     #0
        sta     tmp2                    ; the range, whole units
        ; (the range is whole: dist >= range iff dist >> 16 >= range)
        lda     W+W_FR+3
        cmp     tmp2
        bcc     @in
        bne     @out
        lda     W+W_FR+2
        cmp     tmp1
        bcc     @in
@out:   clc
        rts
@in:    jsr     sight_target
        beq     @out
        sec
        rts

; A = P_CheckSight(gmo, gmo->target) (and Z); gmo kept
sight_target:
        lda     gmo
        sta     sg_t1
        pha
        lda     gmo+1
        sta     sg_t1+1
        pha
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     sg_t2
        iny
        lda     (gmo),y
        sta     sg_t2+1
        jsr     check_sight
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        rts

; W_T0 = target->x - gmo->x, W_T1 = target->y - gmo->y; gpt = the target
target_delta:
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
; W_T0, W_T1 = gpt's x, y - gmo's
delta_gpt:
        ldx     #0
        ldy     #MO_X
        sec
:       lda     (gpt),y
        sbc     (gmo),y
        sta     W+W_T0,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        ldx     #0
        ldy     #MO_Y
        sec
:       lda     (gpt),y
        sbc     (gmo),y
        sta     W+W_T1,x
        iny
        inx
        txa                             ; (keeps the carry)
        eor     #4
        bne     :-
        rts

; C set iff vanilla P_CheckMissileRange(gmo); gmo kept
check_missile:
        jsr     sight_target
        bne     :+
        clc
        rts
:       ldy     #MO_FLAGS
        lda     (gmo),y
        bit     #MF0_JUSTHIT
        beq     :+
        and     #<~MF0_JUSTHIT          ; the target just hit the enemy: fight back!
        sta     (gmo),y
        sec
        rts
:       ldy     #MO_REACTIONTIME
        lda     (gmo),y
        beq     :+
        clc                             ; do not attack yet
        rts
:       ; dist = (P_AproxDistance(x - tx, y - ty) >> 16) - 64, - 128 more
        ; without a melee attack (whole units subtract exactly), halved for
        ; the lost soul, at most 200; P_Random() < dist: not now
        jsr     target_delta
        jsr     aprox_dist
        lda     W+W_FR+2
        sec
        sbc     #64
        sta     cm_dist
        lda     W+W_FR+3
        sbc     #0
        sta     cm_dist+1
        jsr     mo_info
        ldy     #MI_MELEESTATE
        lda     (ptr1),y
        iny
        ora     (ptr1),y
        bne     :+
        sec
        lda     cm_dist
        sbc     #128
        sta     cm_dist
        bcs     :+
        dec     cm_dist+1
:       ldy     #MO_TYPE
        lda     (gmo),y
        cmp     #MT_SKULL
        bne     :+
        lda     cm_dist+1
        cmp     #$80
        ror     cm_dist+1
        ror     cm_dist
:       lda     cm_dist+1
        bpl     :+
        stz     cm_dist                    ; dist < 0: P_Random() < dist never
        bra     @rnd
:       bne     @cap
        lda     cm_dist
        cmp     #201
        bcc     @rnd
@cap:   lda     #200
        sta     cm_dist
@rnd:   jsr     _P_Random
        cmp     cm_dist
        bcc     @no
        sec
        rts
@no:    clc
        rts

; ---- A_Look -----------------------------------------------------------------------------------
_A_Look:
        jsr     action
        ldy     #MO_THRESHOLD
        lda     #0
        sta     (gmo),y                 ; any shot will wake up
        ; the sound target of its sector, if it can still be shot
        ldy     #MO_SECTOR
        lda     (gmo),y
        asl     a
        sta     tmp1
        iny
        lda     (gmo),y
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
        sta     gpt+1
        lda     (ptr1)
        sta     gpt
        ora     gpt+1
        beq     @look
        ldy     #MO_FLAGS
        lda     (gpt),y
        and     #MF0_SHOOTABLE
        beq     @look
        ldy     #MO_TARGET
        lda     gpt
        sta     (gmo),y
        iny
        lda     gpt+1
        sta     (gmo),y
        ; an ambusher only if it also sees it
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #MF0_AMBUSH
        beq     @seeyou
        jsr     sight_target
        bne     @seeyou
@look:  clc                             ; only 180 degrees in front
        jsr     look_for_players
        bcs     @seeyou
        rts
@seeyou:
        ; go into its chase state, with its sight sound
        jsr     mo_info
        ldy     #MI_SEESOUND
        lda     (ptr1),y
        beq     @chase
        cmp     #sfx_posit1
        bcc     @sound
        cmp     #sfx_posit3 + 1
        bcs     :+
        lda     #3
        jsr     random_mod
        adc     #sfx_posit1             ; (C clear: random_mod ends below its divisor)
        bra     @sound
:       cmp     #sfx_bgsit1
        bcc     @sound
        cmp     #sfx_bgsit2 + 1
        bcs     @sound
        lda     #2
        jsr     random_mod
        adc     #sfx_bgsit1
@sound: jsr     mo_sound
@chase: jsr     mo_info
        ldy     #MI_SEESTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jmp     set_state

; vanilla P_LookForPlayers(gmo, allaround = C) for one player -> C set if
; the player is its new target; gmo kept
look_for_players:
        php
        ldy     #MO_LASTLOOK
        lda     (gmo),y
        tax
        lda     #0
        sta     (gmo),y
        cpx     #1
        jeq     @no                     ; vanilla stops at player 0 before looking
        lda     PL+PL_HEALTH+1
        jmi     @no
        ora     PL+PL_HEALTH
        jeq     @no                     ; dead
        plp
        php
        bcs     @look                   ; all around
        ; behind its back (more than 90 degrees off its angle) and not real
        ; close: no (vanilla asks after the sight walk: the same answer)
        lda     PL+PL_MO
        sta     gpt
        lda     PL+PL_MO+1
        sta     gpt+1
        jsr     angle_to
        sec
        ldy     #MO_ANGLE
        sbc     (gmo),y
        sta     tmp1
        txa
        iny
        sbc     (gmo),y                 ; an = angle - actor's angle
        cmp     #$40                    ; ANG90 < an < ANG270: behind
        bcc     @look
        bne     :+
        ldx     tmp1
        beq     @look                   ; exactly ANG90
:       cmp     #$C0
        bcs     @look
        lda     PL+PL_MO
        sta     gpt
        lda     PL+PL_MO+1
        sta     gpt+1
        jsr     delta_gpt
        jsr     aprox_dist              ; > MELEERANGE: behind its back
        lda     W+W_FR+3
        bne     @no
        lda     W+W_FR+2
        cmp     #MELEE_HI
        bcc     @look
        bne     @no
        lda     W+W_FR+1
        ora     W+W_FR
        bne     @no
@look:  lda     gmo
        sta     sg_t1
        pha
        lda     gmo+1
        sta     sg_t1+1
        pha
        lda     PL+PL_MO
        sta     sg_t2
        lda     PL+PL_MO+1
        sta     sg_t2+1
        jsr     check_sight
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        beq     @no                     ; out of sight
@yes:   plp
        ldy     #MO_TARGET
        lda     PL+PL_MO
        sta     (gmo),y
        iny
        lda     PL+PL_MO+1
        sta     (gmo),y
        sec
        rts
@no:    plp
        clc
        rts

; ---- A_Chase --------------------------------------------------------------------------------
_A_Chase:
        jsr     action
        ; reactiontime counts down
        ldy     #MO_REACTIONTIME
        lda     (gmo),y
        beq     :+
        dec     a
        sta     (gmo),y
:       ; the target threshold: forget it with the target, else count down
        ldy     #MO_THRESHOLD
        lda     (gmo),y
        beq     @turn
        jsr     no_target
        beq     @thr0
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
        ldy     #MO_HEALTH+1
        lda     (gpt),y
        bmi     @thr0
        dey
        ora     (gpt),y
        beq     @thr0
        ldy     #MO_THRESHOLD
        lda     (gmo),y
        dec     a
        sta     (gmo),y
        bra     @turn
@thr0:  ldy     #MO_THRESHOLD
        lda     #0
        sta     (gmo),y
@turn:  ; turn towards the movement direction if not there yet
        ldy     #MO_MOVEDIR
        lda     (gmo),y
        cmp     #8
        bcs     @target
        asl     a                       ; movedir << 5: the high byte of << 13
        asl     a
        asl     a
        asl     a
        asl     a
        sta     tmp1
        ldy     #MO_ANGLE
        lda     #0
        sta     (gmo),y                 ; angle &= 7 << 13
        iny
        lda     (gmo),y
        and     #$E0
        tax
        sec
        sbc     tmp1                    ; the delta's high byte (its low byte is 0)
        beq     @keep
        bmi     @plus
        txa
        sec
        sbc     #$20                    ; delta > 0: - ANG90 / 2
        bra     @set
@plus:  txa
        clc
        adc     #$20                    ; delta < 0: + ANG90 / 2
@set:   tax
@keep:  txa
        sta     (gmo),y
@target:
        ; no target, or not shootable: look for a new one, else back to spawn
        jsr     no_target
        beq     @lost
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
        ldy     #MO_FLAGS
        lda     (gpt),y
        and     #MF0_SHOOTABLE
        bne     @hunt
@lost:  sec
        jsr     look_for_players
        bcc     :+
        rts                             ; got a new target
:       jsr     mo_info
        ldy     #MI_SPAWNSTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jmp     set_state
@hunt:  ; do not attack twice in a row
        ldy     #MO_FLAGS
        lda     (gmo),y
        bpl     @melee                  ; (MF0_JUSTATTACKED is bit 7)
        and     #<~MF0_JUSTATTACKED
        sta     (gmo),y
        lda     _gameskill
        cmp     #sk_nightmare
        beq     :+
        jmp     new_chase_dir
:       rts
@melee: ; a melee attack in range
        jsr     mo_info
        ldy     #MI_MELEESTATE
        lda     (ptr1),y
        iny
        ora     (ptr1),y
        beq     @missile
        jsr     check_melee
        bcc     @missile
        jsr     mo_info
        ldy     #MI_ATTACKSOUND
        lda     (ptr1),y
        beq     :+
        jsr     mo_sound
        jsr     mo_info
:       ldy     #MI_MELEESTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jmp     set_state
@missile:
        ; a missile attack (below nightmare, not while it has steps to go)
        jsr     mo_info
        ldy     #MI_MISSILESTATE
        lda     (ptr1),y
        iny
        ora     (ptr1),y
        beq     @chase
        lda     _gameskill
        cmp     #sk_nightmare
        bcs     :+
        ldy     #MO_MOVECOUNT
        lda     (gmo),y
        bne     @chase
:       jsr     check_missile
        bcc     @chase
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     mo_info
        ldy     #MI_MISSILESTATE+1
        lda     (ptr1),y
        tax
        dey
        lda     (ptr1),y
        jsr     set_state
        pla
        sta     gmo+1
        pla
        sta     gmo
        ldy     #MO_FLAGS
        lda     (gmo),y
        ora     #MF0_JUSTATTACKED
        sta     (gmo),y
        rts
@chase: ; chase towards the player: movecount (a signed byte that stops at
        ; -128: vanilla's int keeps its sign) down; a new direction when it
        ; is spent or the move is blocked
        ldy     #MO_MOVECOUNT
        lda     (gmo),y
        cmp     #$80
        beq     :+
        dec     a
        sta     (gmo),y
:       lda     gmo
        pha
        lda     gmo+1
        pha
        ldy     #MO_MOVECOUNT
        lda     (gmo),y
        bmi     @newdir
        jsr     p_move
        bne     @moved
@newdir:
        jsr     new_chase_dir           ; (gmo is still the actor)
@moved: pla
        sta     gmo+1
        sta     ac+1
        pla
        sta     gmo
        sta     ac
        ; the active sound, now and then
        jsr     mo_info
        ldy     #MI_ACTIVESOUND
        lda     (ptr1),y
        beq     @rts
        pha
        jsr     _P_Random
        tax
        pla
        cpx     #3
        bcs     @rts
        jmp     mo_sound
@rts:   rts

; ---- P_Move: gmo in its direction -> A = 1 moved (or floated, or a door
; opened), 0 blocked (and Z); gmo kept ------------------------------------------------------------
p_move:
        ldy     #MO_MOVEDIR
        lda     (gmo),y
        cmp     #8
        bcc     :+
        lda     #0
        rts
:       pha
        ; tryx, tryy = x, y + speed * xspeed[dir], yspeed[dir]
        jsr     mo_info
        ldy     #MI_SPEED
        lda     (ptr1),y
        sta     tmp3
        plx
        phx
        lda     xcode,x
        ldy     #MO_X
        ldx     #0
        jsr     try_axis
        plx
        lda     ycode,x
        ldy     #MO_Y
        ldx     #4
        jsr     try_axis
        ldx     #3
:       lda     mv_try,x
        sta     W+W_TMX,x
        lda     mv_try+4,x
        sta     W+W_TMY,x
        dex
        bpl     :-
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     try_move
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        beq     @blocked
        ; moved: not floating any more; walkers stand on the floor
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        and     #<~MF2_INFLOAT
        sta     (gmo),y
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_FLOAT
        bne     @true
        ldy     #MO_Z
        lda     #0
        sta     (gmo),y
        iny
        sta     (gmo),y
        ldy     #MO_FLOORZ
        lda     (gmo),y
        ldy     #MO_Z+2
        sta     (gmo),y
        ldy     #MO_FLOORZ+1
        lda     (gmo),y
        ldy     #MO_Z+3
        sta     (gmo),y
@true:  lda     #1
        rts
@blocked:
        ; a floater that fits the opening adjusts its height
        ldy     #MO_FLAGS+1
        lda     (gmo),y
        and     #MF1_FLOAT
        beq     @specials
        lda     _floatok
        beq     @specials
        ldx     #W_T0
        ldy     #MO_Z
        jsr     w_ldo
        ldx     #W_T0
        ldy     #W_TMFLOORZ
        jsr     w_cmp                   ; z < tmfloorz: up, else down
        ldy     #MO_Z+2
        bmi     @up
        clc
        lda     (gmo),y
        sbc     #4 - 1                  ; (C clear: 4 less)
        sta     (gmo),y
        iny
        lda     (gmo),y
        sbc     #0
        sta     (gmo),y
        bra     @infloat
@up:    clc
        lda     (gmo),y
        adc     #4
        sta     (gmo),y
        iny
        lda     (gmo),y
        adc     #0
        sta     (gmo),y
@infloat:
        ldy     #MO_FLAGS+2
        lda     (gmo),y
        ora     #MF2_INFLOAT
        sta     (gmo),y
        lda     #1
        rts
@specials:
        ; the special lines it touched (the doors a monster opens)
        lda     _numspechit
        bne     :+
        rts                             ; A = 0
:       ldy     #MO_MOVEDIR
        lda     #DI_NODIR
        sta     (gmo),y
        lda     #0
        pha                             ; good
@use:   ldx     _numspechit             ; while (numspechit--)
        dec     _numspechit
        txa
        beq     @end
        lda     gmo
        pha
        lda     gmo+1
        pha
        tax
        lda     gmo
        jsr     pushax
        lda     _numspechit
        asl     a
        tay
        lda     _spechit,y
        ldx     _spechit+1,y
        jsr     pushax
        lda     #0
        jsr     _P_UseSpecialLine
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        beq     @use
        pla
        lda     #1
        pha
        bra     @use
@end:   pla
        rts

; mv_try+X = the fixed at (gmo)+Y plus the speed (tmp3) times the speed
; code A (0, 1 = FRACUNIT, 2 = 47000; bit 7: negative)
try_axis:
        pha
        phx
        lda     (gmo),y
        sta     mv_try,x
        iny
        lda     (gmo),y
        sta     mv_try+1,x
        iny
        lda     (gmo),y
        sta     mv_try+2,x
        iny
        lda     (gmo),y
        sta     mv_try+3,x
        plx
        pla
        beq     @rts
        sta     tmp4
        and     #$7F
        cmp     #1
        bne     @47000
        stz     W+W_T0                  ; speed << 16
        stz     W+W_T0+1
        lda     tmp3
        sta     W+W_T0+2
        stz     W+W_T0+3
        bra     @add
@47000: ; speed * 47000 ($B798): speed * $98 + (speed * $B7 << 8)
        phx
        lda     tmp3
        ldx     #$98
        jsr     mul8
        sta     W+W_T0
        stx     W+W_T0+1
        lda     tmp3
        ldx     #$B7
        jsr     mul8
        clc
        adc     W+W_T0+1
        sta     W+W_T0+1
        txa
        adc     #0
        sta     W+W_T0+2
        stz     W+W_T0+3
        plx
@add:   bit     tmp4
        bmi     @sub
        clc
        lda     mv_try,x
        adc     W+W_T0
        sta     mv_try,x
        lda     mv_try+1,x
        adc     W+W_T0+1
        sta     mv_try+1,x
        lda     mv_try+2,x
        adc     W+W_T0+2
        sta     mv_try+2,x
        lda     mv_try+3,x
        adc     #0
        sta     mv_try+3,x
@rts:   rts
@sub:   sec
        lda     mv_try,x
        sbc     W+W_T0
        sta     mv_try,x
        lda     mv_try+1,x
        sbc     W+W_T0+1
        sta     mv_try+1,x
        lda     mv_try+2,x
        sbc     W+W_T0+2
        sta     mv_try+2,x
        lda     mv_try+3,x
        sbc     #0
        sta     mv_try+3,x
        rts

; ---- P_TryWalk: movedir = A, then P_Move; moved: a new movecount
; (P_Random() & 15) -> C set; gmo kept. P_NewChaseDir's directions are
; kept across P_Move (it may run another monster's P_NewChaseDir) ------------------
try_walk:
        ldy     #MO_MOVEDIR
        sta     (gmo),y
        ldx     #NC_SIZE - 1
:       lda     nc_old,x
        pha
        dex
        bpl     :-
        lda     gmo
        pha
        lda     gmo+1
        pha
        jsr     p_move
        beq     @no
        jsr     _P_Random
        and     #15
        tax
        pla
        sta     gmo+1
        pla
        sta     gmo
        txa
        ldy     #MO_MOVECOUNT
        sta     (gmo),y
        sec
        bra     @back
@no:    pla
        sta     gmo+1
        pla
        sta     gmo
        clc
@back:  php
        pla
        tay                             ; (the carry, while the directions come back)
        ldx     #0
:       pla
        sta     nc_old,x
        inx
        cpx     #NC_SIZE
        bne     :-
        tya
        pha
        plp
        rts

; ---- P_NewChaseDir(gmo) ------------------------------------------------------------------------
new_chase_dir:
        ldy     #MO_MOVEDIR
        lda     (gmo),y
        sta     nc_old
        tax
        lda     opposite,x
        sta     nc_turn
        jsr     target_delta            ; W_T0 = deltax, W_T1 = deltay
        ; d1: east if deltax > 10 units, west if < -10, else none
        ldx     #W_T0
        jsr     ten_units
        tax
        lda     #DI_EAST
        dex
        beq     :+
        lda     #DI_WEST
        inx
        inx
        beq     :+
        lda     #DI_NODIR
:       sta     nc_d1
        ; d2: south if deltay < -10, north if > 10, else none
        ldx     #W_T1
        jsr     ten_units
        tax
        lda     #DI_NORTH
        dex
        beq     :+
        lda     #DI_SOUTH
        inx
        inx
        beq     :+
        lda     #DI_NODIR
:       sta     nc_d2
        ; (|deltay| > |deltax|, for later: nothing moves the two meanwhile)
        ldx     #W_T2
        ldy     #W_T0
        jsr     w_mov
        ldx     #W_T2
        jsr     w_abs
        ldx     #W_T3
        ldy     #W_T1
        jsr     w_mov
        ldx     #W_T3
        jsr     w_abs
        ldx     #W_T2
        ldy     #W_T3
        jsr     w_cmp                   ; |dx| - |dy| < 0: |dy| > |dx|
        and     #$80
        sta     nc_ygtx
        ; try the direct route
        lda     nc_d1
        cmp     #DI_NODIR
        beq     @other
        lda     nc_d2
        cmp     #DI_NODIR
        beq     @other
        ; movedir = diags[((deltay < 0) << 1) + (deltax > 0)]
        lda     W+W_T1+3
        asl     a                       ; C = deltay < 0
        lda     #0
        rol     a
        asl     a
        sta     tmp1
        ldx     #W_T0
        jsr     w_pos                   ; (C clear)
        adc     tmp1
        tax
        lda     diags,x
        ldy     #MO_MOVEDIR
        sta     (gmo),y
        cmp     nc_turn
        beq     @other
        jsr     try_walk
        bcc     @other
        rts
@other: ; try the other directions: d1 and d2 swapped if P_Random() > 200
        ; or |deltay| > |deltax| (the random number first, always)
        jsr     _P_Random
        cmp     #201
        bcs     @swap
        bit     nc_ygtx
        bpl     @noswap
@swap:  lda     nc_d1
        ldx     nc_d2
        sta     nc_d2
        stx     nc_d1
@noswap:
        lda     nc_d1
        cmp     nc_turn
        bne     :+
        lda     #DI_NODIR
        sta     nc_d1
:       lda     nc_d2
        cmp     nc_turn
        bne     :+
        lda     #DI_NODIR
        sta     nc_d2
:       lda     nc_d1
        cmp     #DI_NODIR
        beq     :+
        jsr     try_walk
        bcc     :+
        rts                             ; either moved forward or attacked
:       lda     nc_d2
        cmp     #DI_NODIR
        beq     :+
        jsr     try_walk
        bcc     :+
        rts
:       ; no direct path to the player: the old direction
        lda     nc_old
        cmp     #DI_NODIR
        beq     :+
        jsr     try_walk
        bcc     :+
        rts
:       ; then every direction, in a random sense of rotation
        jsr     _P_Random
        lsr     a
        bcc     @down
        stz     nc_tdir                 ; east .. southeast
@up:    lda     nc_tdir
        cmp     nc_turn
        beq     :+
        jsr     try_walk
        bcc     :+
        rts
:       inc     nc_tdir
        lda     nc_tdir
        cmp     #DI_SOUTHEAST + 1
        bne     @up
        bra     @turn
@down:  lda     #DI_SOUTHEAST           ; southeast .. east
        sta     nc_tdir
@dn:    lda     nc_tdir
        cmp     nc_turn
        beq     :+
        jsr     try_walk
        bcc     :+
        rts
:       dec     nc_tdir
        bpl     @dn
@turn:  lda     nc_turn
        cmp     #DI_NODIR
        beq     :+
        jsr     try_walk
        bcc     :+
        rts
:       ldy     #MO_MOVEDIR             ; can not move
        lda     #DI_NODIR
        sta     (gmo),y
        rts

; A = 1 if W[X] > 10 << 16, $FF if W[X] < -10 << 16, else 0
ten_units:
        lda     W+3,x
        bmi     @neg
        bne     @gt
        lda     W+2,x
        cmp     #10
        bcc     @none
        bne     @gt
        lda     W+1,x
        ora     W,x
        beq     @none
@gt:    lda     #1
        rts
@neg:   cmp     #$FF
        bne     @lt
        lda     W+2,x
        cmp     #<-10                   ; below $FFF6xxxx: less
        bcs     @none
@lt:    lda     #$FF
        rts
@none:  lda     #0
        rts

; A = 1 if W[X] > 0, else 0; C clear
w_pos:  lda     W+3,x
        bmi     @no
        ora     W+2,x
        ora     W+1,x
        ora     W,x
        beq     @no
        lda     #1
        clc
        rts
@no:    lda     #0
        clc
        rts

; ---- A_FaceTarget ---------------------------------------------------------------------------------
_A_FaceTarget:
        jsr     action
; gmo turns to its target (if any); gmo kept
face_target:
        jsr     no_target
        bne     :+
        rts
:       ldy     #MO_FLAGS
        lda     (gmo),y
        and     #<~MF0_AMBUSH
        sta     (gmo),y
        jsr     angle_to_target
        ldy     #MO_ANGLE
        sta     (gmo),y
        iny
        txa
        sta     (gmo),y
        ; a shadow target: angle += P_SubRandom() << 5 (vanilla << 21)
        ldy     #MO_TARGET
        lda     (gmo),y
        sta     gpt
        iny
        lda     (gmo),y
        sta     gpt+1
        ldy     #MO_FLAGS+2
        lda     (gpt),y
        and     #MF2_SHADOW
        beq     @rts
        ldx     #5
        jsr     subrandom_shl
        ldy     #MO_ANGLE
        clc
        adc     (gmo),y
        sta     (gmo),y
        iny
        lda     tmp2
        adc     (gmo),y
        sta     (gmo),y
@rts:   rts

; A (low), tmp2 (high) = P_SubRandom() << X
subrandom_shl:
        phx
        jsr     _P_SubRandom
        stx     tmp2
        plx
:       asl     a
        rol     tmp2
        dex
        bne     :-
        rts

; ---- the attacks -----------------------------------------------------------------------------------
; ac_slope = P_AimLineAttack(ac, ac_ang, MISSILERANGE)
aim_missilerange:
        lda     ac
        ldx     ac+1
        jsr     pushax
        lda     ac_ang
        ldx     ac_ang+1
        jsr     pushax
        lda     #<(32 * 64)             ; MISSILERANGE >> 16
        sta     sreg
        lda     #>(32 * 64)
        sta     sreg+1
        lda     #0
        tax
        jsr     _P_AimLineAttack
        sta     ac_slope
        stx     ac_slope+1
        lda     sreg
        sta     ac_slope+2
        lda     sreg+1
        sta     ac_slope+3
        rts

; P_LineAttack(ac, A/X, MISSILERANGE, ac_slope, ac_dmg)
line_attack:
        pha
        phx
        lda     ac
        ldx     ac+1
        jsr     pushax
        plx
        pla
        jsr     pushax
        lda     #<(32 * 64)
        sta     sreg
        lda     #>(32 * 64)
        sta     sreg+1
        lda     #0
        tax
        jsr     pusheax
        lda     ac_slope+2
        sta     sreg
        lda     ac_slope+3
        sta     sreg+1
        lda     ac_slope
        ldx     ac_slope+1
        jsr     pusheax
        lda     ac_dmg
        ldx     ac_dmg+1
        jmp     _P_LineAttack

; ac_dmg = ((P_Random() % 5) + 1) * 3
bullet_damage:
        lda     #5
        jsr     random_mod
        inc     a
        sta     tmp1
        asl     a
        adc     tmp1
        sta     ac_dmg
        stz     ac_dmg+1
        rts

; A/X = ac_ang + (P_SubRandom() << 4) (vanilla << 20)
spread:
        ldx     #4
        jsr     subrandom_shl
        clc
        adc     ac_ang
        pha
        lda     tmp2
        adc     ac_ang+1
        tax
        pla
        rts

; ac_ang = gmo's angle
take_angle:
        ldy     #MO_ANGLE
        lda     (gmo),y
        sta     ac_ang
        iny
        lda     (gmo),y
        sta     ac_ang+1
        rts

; the zombieman
_A_PosAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        jsr     face_target
        jsr     take_angle
        jsr     aim_missilerange
        jsr     gmo_ac
        lda     #sfx_pistol
        jsr     mo_sound
        jsr     spread
        pha
        phx
        jsr     bullet_damage
        plx
        pla
        jmp     line_attack
@rts:   rts

; the shotgun guy: three pellets after one aim
_A_SPosAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        lda     #sfx_shotgn
        jsr     mo_sound
        jsr     face_target
        jsr     take_angle
        jsr     aim_missilerange
        lda     #3
@pellet:
        ; (the loop's state survives P_LineAttack on the 6502 stack)
        pha
        lda     ac
        pha
        lda     ac+1
        pha
        lda     ac_ang
        pha
        lda     ac_ang+1
        pha
        ldx     #3
:       lda     ac_slope,x
        pha
        dex
        bpl     :-
        jsr     spread
        pha
        phx
        jsr     bullet_damage
        plx
        pla
        jsr     line_attack
        ldx     #0
:       pla
        sta     ac_slope,x
        inx
        cpx     #4
        bne     :-
        pla
        sta     ac_ang+1
        pla
        sta     ac_ang
        pla
        sta     ac+1
        pla
        sta     ac
        pla
        dec     a
        bne     @pellet
@rts:   rts

; P_DamageMobj(ac->target, ac, ac, ac_dmg)
melee_hit:
        jsr     gmo_ac
        ldy     #MO_TARGET
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tax
        pla
        jsr     pushax
        lda     ac
        ldx     ac+1
        jsr     pushax
        lda     ac
        ldx     ac+1
        jsr     pushax
        lda     ac_dmg
        ldx     ac_dmg+1
        jmp     _P_DamageMobj

; P_SpawnMissile(ac, ac->target, A)
missile:
        pha
        jsr     gmo_ac
        lda     ac
        ldx     ac+1
        jsr     pushax
        ldy     #MO_TARGET
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tax
        pla
        jsr     pushax
        pla
        jmp     _P_SpawnMissile

; ac_dmg = (P_Random() % A + 1) * X
melee_damage:
        phx
        jsr     random_mod
        inc     a
        plx
        jsr     mul8
        sta     ac_dmg
        stx     ac_dmg+1
        rts

; the imp: claw at melee range, else a fireball
_A_TroopAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        jsr     face_target
        jsr     check_melee
        bcc     @far
        lda     #sfx_claw
        jsr     mo_sound
        lda     #8
        ldx     #3
        jsr     melee_damage
        jmp     melee_hit
@far:   lda     #MT_TROOPSHOT
        jmp     missile
@rts:   rts

; the demon and the spectre (Doom 1.5 and later: only in range)
_A_SargAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        jsr     face_target
        jsr     check_melee
        bcc     @rts
        lda     #10
        ldx     #4
        jsr     melee_damage
        jmp     melee_hit
@rts:   rts

; the cacodemon: a bite at melee range, else a ball
_A_HeadAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        jsr     face_target
        jsr     check_melee
        bcc     @far
        lda     #6
        ldx     #10
        jsr     melee_damage
        jmp     melee_hit
@far:   lda     #MT_HEADSHOT
        jmp     missile
@rts:   rts

; the baron (its attack states face the target themselves)
_A_BruisAttack:
        jsr     action
        jsr     no_target
        beq     @rts
        jsr     check_melee
        bcc     @far
        lda     #sfx_claw
        jsr     mo_sound
        lda     #8
        ldx     #10
        jsr     melee_damage
        jmp     melee_hit
@far:   lda     #MT_BRUISERSHOT
        jmp     missile
@rts:   rts

; the lost soul flies at its target like a missile (SKULLSPEED 20 units)
_A_SkullAttack:
        jsr     action
        jsr     no_target
        bne     :+
        rts
:       ldy     #MO_FLAGS+3
        lda     (gmo),y
        ora     #MF3_SKULLFLY
        sta     (gmo),y
        jsr     mo_info
        ldy     #MI_ATTACKSOUND
        lda     (ptr1),y
        jsr     mo_sound
        jsr     face_target
        ; momx, momy = 20 * cosine, sine of angle >> 3
        ldy     #MO_ANGLE
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
        sta     tmp2
        pha
        lda     tmp1
        pha
        ldx     tmp2
        jsr     fx_cosine
        ldy     #MO_MOMX
        jsr     skull_speed
        pla
        plx
        jsr     fx_sine
        ldy     #MO_MOMY
        jsr     skull_speed
        ; dist = (P_AproxDistance(dest - actor) >> 16) / 20, at least 1
        jsr     target_delta
        jsr     aprox_dist
        lda     W+W_FR+2
        ldx     W+W_FR+3
        jsr     div20
        cmp     #0
        bne     :+
        cpx     #0
        bne     :+
        lda     #1
:       sta     fxb+2
        stx     fxb+3
        stz     fxb
        stz     fxb+1
        ; momz = (dest->z + (dest->height >> 1) - z) / dist
        ; (FixedDiv by dist << 16 is that division, truncated)
        ldx     #W_T0
        ldy     #MO_HEIGHT
        lda     gmo
        pha
        lda     gmo+1
        pha
        lda     gpt
        sta     gmo
        lda     gpt+1
        sta     gmo+1
        jsr     w_ldo
        lda     W+W_T0+3
        cmp     #$80
        ror     W+W_T0+3
        ror     W+W_T0+2
        ror     W+W_T0+1
        ror     W+W_T0
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_ldo
        pla
        sta     gmo+1
        pla
        sta     gmo
        ldx     #W_T0
        ldy     #W_T1
        jsr     w_add
        ldx     #W_T1
        ldy     #MO_Z
        jsr     w_ldo
        sub32   fxa, W+W_T0, W+W_T1
        jsr     fx_div
        ldx     #W_FR
        ldy     #MO_MOMZ
        jmp     w_sto

; (gmo)+Y = FixedMul(SKULLSPEED, fxr)
skull_speed:
        phy
        mov32   fxb, fxr
        ldi32   fxa, 20 << 16
        jsr     fx_mul
        ply
        ldx     #W_FR
        jmp     w_sto

; A/X = A/X / 20 (unsigned 16-bit)
div20:  sta     tmp1
        stx     tmp2
        lda     #0                      ; the remainder
        ldx     #16
:       asl     tmp1
        rol     tmp2
        rol     a
        cmp     #20
        bcc     :+
        sbc     #20
        inc     tmp1
:       dex
        bne     :--
        lda     tmp1
        ldx     tmp2
        rts

; ---- the death actions ------------------------------------------------------------------------------
_A_Scream:
        jsr     action
        jsr     mo_info
        ldy     #MI_DEATHSOUND
        lda     (ptr1),y
        beq     @rts
        cmp     #sfx_podth1
        bcc     @sound
        cmp     #sfx_podth3 + 1
        bcs     :+
        lda     #3
        jsr     random_mod
        adc     #sfx_podth1
        bra     @sound
:       cmp     #sfx_bgdth1
        bcc     @sound
        cmp     #sfx_bgdth2 + 1
        bcs     @sound
        lda     #2
        jsr     random_mod
        adc     #sfx_bgdth1
@sound: jmp     mo_sound
@rts:   rts

_A_XScream:
        jsr     action
        lda     #sfx_slop
        jmp     mo_sound

_A_Pain:
        jsr     action
        jsr     mo_info
        ldy     #MI_PAINSOUND
        lda     (ptr1),y
        beq     :+
        jmp     mo_sound
:       rts

_A_Fall:
        sta     gmo
        stx     gmo+1
        ldy     #MO_FLAGS
        lda     (gmo),y
        and     #<~MF0_SOLID            ; it can be walked over
        sta     (gmo),y
        rts

_A_Explode:
        jsr     action
        jsr     pushax                  ; P_RadiusAttack(actor, actor->target, 128)
        ldy     #MO_TARGET
        lda     (gmo),y
        pha
        iny
        lda     (gmo),y
        tax
        pla
        jsr     pushax
        lda     #128
        ldx     #0
        jmp     _P_RadiusAttack

_A_PlayerScream:
        jsr     action
        lda     #sfx_pldeth
        jmp     mo_sound

; E1M8: the floors tagged 666 lower when the last baron dies
_A_BossDeath:
        jsr     action
        lda     _gamemap
        cmp     #8
        jne     @rts
        ldy     #MO_TYPE
        lda     (gmo),y
        cmp     #MT_BRUISER
        jne     @rts
        sta     tmp3
        lda     PL+PL_HEALTH+1
        jmi     @rts
        ora     PL+PL_HEALTH
        jeq     @rts                    ; no one left alive
        ; another baron alive: an actor with health, or a live static
        lda     _mobjs
        sta     gpt
        lda     _mobjs+1
        sta     gpt+1
@actor: lda     gpt
        cmp     _mobjs_end
        lda     gpt+1
        sbc     _mobjs_end+1
        bcs     @statics
        lda     gpt
        cmp     gmo
        bne     :+
        lda     gpt+1
        cmp     gmo+1
        beq     @nexta
:       ldy     #TH_FUNCTION
        lda     (gpt),y
        cmp     #<_P_MobjThinker
        bne     @nexta
        iny
        lda     (gpt),y
        cmp     #>_P_MobjThinker
        bne     @nexta
        ldy     #MO_TYPE
        lda     (gpt),y
        cmp     tmp3
        bne     @nexta
        ldy     #MO_HEALTH+1
        lda     (gpt),y
        bmi     @nexta
        dey
        ora     (gpt),y
        bne     @rts                    ; other boss not dead
@nexta: clc
        lda     gpt
        adc     #MO_SIZE
        sta     gpt
        bcc     @actor
        inc     gpt+1
        bra     @actor
@statics:
        lda     _statics
        sta     gpt
        lda     _statics+1
        sta     gpt+1
@static:
        lda     gpt
        cmp     _statics_end
        lda     gpt+1
        sbc     _statics_end+1
        bcs     @victory
        ldy     #SO_SFLAGS
        lda     (gpt),y
        and     #SF_FREE | SF_CORPSE
        bne     @nexts
        ldy     #SO_TYPE
        lda     (gpt),y
        cmp     tmp3
        beq     @rts                    ; a dormant one
@nexts: clc
        lda     gpt
        adc     #SO_SIZE
        sta     gpt
        bcc     @static
        inc     gpt+1
        bra     @static
@victory:
        lda     #<666
        ldx     #>666
        jsr     pushax
        lda     #lowerFloorToLowest
        jmp     _EV_DoFloorTag
@rts:   rts

.endif
