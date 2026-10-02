; gthink.s: the game core's thinker list, its pools and P_Random
; (milestone 9, stage C; docs/LEVELS.md 2.4, 3.1, 3.2; milestone 10's
; skeleton: the final layouts, docs/GAME.md 1.3, 1.4, 3.1). A GPL-2
; derivative of upstream's p_think65.s (P_InitThinkers, P_AddThinker),
; p_spawn65.s (poolInit, poolTake), p_map65.s (newSecnode's pool) and
; m_random65.s.
;
;   gt_init      the thinker list empty, the sector nodes' pools freed
;                (Z_FreeTags, P_SetSecnodeFirstpoolToNull), no specials
;                (each kind's free list empty), no zone mobjs (their free
;                list empty), the planes' high-water 0
;   gt_add       P_AddThinker: the thinker GC_H at the list's end; GC_PREV
;                = its previous one (the caller writes the new thinker's
;                links: prev GC_PREV, next none); the old last one's next
;                written: a mobj's in the planes, a special's in its record
;                (through the object API)
;   gt_poolinit  poolInit: the pool's G_POOLN slots free (the bitmap
;                G_TPBITS: bit i & 7 of byte i >> 3, 1 free) and each
;                slot's records a free mobj: type MT_NOTHING, the rest 0
;                or none (Z_CallocLevel's zeros: the native nulls are
;                $FFFF handles), its planes none
;   gt_pooltake  newMobj's slot: the pool's free slot with the highest
;                index (poolTake), else a zone slot (Z_MallocLevel): the
;                first of the zone's free list (G_ZMFREE, through the TNL
;                and TNH planes), else the next one after the pool's and
;                the zone's used ones (docs/LEVELS.md 3.1); GC_MO the slot,
;                GC_K 1 when pooled; G_MOHWM the highest slot + 1
;   gt_zfree     a zone mobj's slot GC_MO onto the zone's free list (its
;                kind FN_FREE: no object for the bridge); a slot that
;                CS_PREV1 or CS_PREV2 names becomes "stale" ($FFFE) and
;                GT_ZPREV is raised (docs/GAME.md 1.8)
;   gt_spectake  a special of kind X (llayout.SPEC_KINDS' order): the
;                first of its free list (G_SPFREE), else the next slot of
;                its range; GC_H its handle
;   gt_spfree    special GC_H onto its kind's free list (its function
;                none: no object for the bridge)
;   gt_nodetake  newSecnode's node: the first of the free list, a new pool
;                of SN_POOL linked nodes when the list is empty (so the free
;                list's length is upstream's); GC_N the node
;   gt_moaddr    GC_P = the records' address of the mobj slot A:X (RTHING
;                and the three game parts: RTHBASE + 24 slot)
;   gt_mosave    the mobj at LW_MOB (its RTHING and game parts A, B, C)
;                into slot GC_MO through the object API (mo_store), and its
;                planes: next none, kind LW_MOB + MO_XFUNC, tics the low
;                byte of LW_MOB + MO_XTICS
;   g_random     A = P_Random(): rndtable[++index] (main $03EE);
;                g_mrandom, g_mclearrandom (tic images): M_Random (main
;                $03EF), M_ClearRandom
;   g_get, g_put Y bytes (0: 256) of FA_BANK:FA_SRC into main A:X, of
;                main A:X to FA_BANK:FA_DST (far_get, far_put): the API's
;                lower layer, and the level's tables no cache holds (the
;                sector nodes, the block lists, the line tables, GTAB)
;
; A thinker handle is a mobj's slot (0-2,025) or SPEC_HANDLE + a special's
; slot; $FFFF is none (its high byte $FF names nothing else). The thinker
; links: a mobj's prev in group A, its next in the planes; a special's
; both in its record (SP_THPREV, SP_THNEXT).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gt_init, gt_add, gt_poolinit, gt_pooltake, gt_spectake
        .export gt_nodetake, gt_moaddr, gt_mosave, g_random, gt_zfree
        .export gt_spfree, g_get, g_put, g_put2, g_zero, rndtable
.ifndef LOADIMG
        .export g_mrandom, g_mclearrandom
.endif
        .import far_get, far_put, ld_stop, mo_store, pl_get, pl_put
        .import pl_setn, sp_get, sp_dirty
        .include "ggame.inc"

        .assert >SPEC_HANDLE > >(MOBJ_CAP - 1), error, "thinker handles"
        .assert >SPEC_HANDLE >= >PLANE_SLOTS, error, "thinker handles"

        .segment "LOADW"

; ---------------------------------------------------------------------------
; g_get, g_put: Y bytes (0: 256) between FA_BANK (FA_SRC, FA_DST) and main
; A:X (A the low byte). g_put2: the word at main A:X to FA_BANK:FA_DST.
; g_zero: Y bytes (1-255) of main at A:X set to 0. Change A, Y (g_zero X).
; ---------------------------------------------------------------------------
g_get:  sta FA_DST
        stx FA_DST+1
        sty FA_N
        jmp far_get
g_put2: ldy #2
g_put:  sta FA_SRC
        stx FA_SRC+1
        sty FA_N
        jmp far_put
g_zero: sta GC_P
        stx GC_P+1
        lda #0
:       dey
        sta (GC_P),y
        bne :-
        rts

; ---------------------------------------------------------------------------
; g_random: A = P_Random(), the index a byte (m_random65.s). Changes X.
; ---------------------------------------------------------------------------
g_random:
        inc PRND
        ldx PRND
        lda rndtable,x
        rts
.ifndef LOADIMG
; g_mrandom: A = M_Random(): rndtable[++rndindex], its own index (main
; $03EF, m_random65.s); g_mclearrandom: M_ClearRandom, both indexes 0
; (wave 1 as integrated: the tic images' math is the render build's, which
; has neither; docs/game-parts/flow.md request 4). Change X.
g_mrandom:
        inc MT_MRND
        ldx MT_MRND
        lda rndtable,x
        rts
g_mclearrandom:
        stz MT_PRND
        stz MT_MRND
        rts
.endif

; ---------------------------------------------------------------------------
; gt_init: an empty thinker list, no sector nodes, specials or zone mobjs
; ---------------------------------------------------------------------------
gt_init:
        lda #$FF
        sta G_THFIRST
        sta G_THFIRST+1
        sta G_THLAST
        sta G_THLAST+1
        sta G_SNFREE
        sta G_SNFREE+1
        sta G_SECLIST
        sta G_SECLIST+1
        ldx #G_ZMN + 2 - G_SNHWM - 1    ; G_SNHWM, G_SPN, G_ZMN: 0
:       stz G_SNHWM,x
        dex
        bpl :-
        ldx #G_MOHWM + 2 - G_SPFREE - 1 ; the free lists none, the planes'
:       lda #$FF                        ;   high-water 0
        sta G_SPFREE,x
        dex
        bpl :-
        stz G_MOHWM
        stz G_MOHWM+1
        rts
        .assert G_SPN = G_SNHWM + 2 && G_ZMN = G_SPN + 14, error,  "the counts' order"
        .assert G_ZMFREE = G_SPFREE + 14 && G_MOHWM = G_ZMFREE + 2, error,  "the free lists' order"

; ---------------------------------------------------------------------------
; gt_add: P_AddThinker(GC_H): GC_PREV = the list's last thinker; its next
; = GC_H (a mobj's in the planes, a special's in its record), or the
; list's first when it was empty; the last = GC_H. Changes A, X, Y, the
; API's temporaries, FA_*.
; ---------------------------------------------------------------------------
gt_add:
        lda G_THLAST
        sta GC_PREV
        ldx G_THLAST+1
        stx GC_PREV+1
        cpx #$FF
        bne @link
        lda GC_H
        sta G_THFIRST
        lda GC_H+1
        sta G_THFIRST+1
        bra @last
@link:  cpx #>SPEC_HANDLE
        bcs @spec
        lda GC_H                ; a mobj: its next plane
        sta PL_N
        lda GC_H+1
        sta PL_N+1
        lda GC_PREV
        jsr pl_setn
        bra @last
@spec:  lda GC_PREV             ; a special: its record's next
        jsr sp_get
        ldy #SP_THNEXT
        lda GC_H
        sta (GC_XP),y
        iny
        lda GC_H+1
        sta (GC_XP),y
        jsr sp_dirty
@last:  lda GC_H
        sta G_THLAST
        lda GC_H+1
        sta G_THLAST+1
        rts

; ---------------------------------------------------------------------------
; gt_moaddr: GC_P = RTHBASE + 24 * A:X (a mobj slot, below 2,731). Changes
; A, X.
; ---------------------------------------------------------------------------
gt_moaddr:
        sta GC_P
        stx GC_P+1
        asl GC_P                ; 2 s
        rol GC_P+1
        clc                     ; 3 s
        adc GC_P
        sta GC_P
        txa
        adc GC_P+1
        sta GC_P+1
        ldx #3                  ; 24 s
:       asl GC_P
        rol GC_P+1
        dex
        bne :-
        clc
        lda GC_P
        adc #<RTHBASE
        sta GC_P
        lda GC_P+1
        adc #>RTHBASE
        sta GC_P+1
        rts

; ---------------------------------------------------------------------------
; gt_mosave: the mobj at LW_MOB (RTHING, game parts A, B, C, 24 bytes
; each: a mobj cache line's form) into its slot GC_MO through the object
; API, and its planes: next none, kind MO_XFUNC, tics MO_XTICS's low byte
; (-1: $FF). Changes A, X, Y, the API's temporaries, FA_*.
; ---------------------------------------------------------------------------
gt_mosave:
        jsr mo_store
        lda #$FF
        sta PL_N
        sta PL_N+1
        lda LW_MOB + MO_XFUNC
        sta PL_K
        lda LW_MOB + MO_XTICS
        sta PL_T
        lda GC_MO
        ldx GC_MO+1
        jmp pl_put

; ---------------------------------------------------------------------------
; gt_poolinit: poolInit for G_POOLN mobjs (at most POOL_MAX: LS_THINGS
; otherwise): every slot free in G_TPBITS, the others' bits 0; each
; slot's records those of a free mobj (LW_MOB as the template). Changes
; A, X, Y, GC_MO, GC_P, FA_*.
; ---------------------------------------------------------------------------
gt_poolinit:
        lda G_POOLN+1
        cmp #>POOL_MAX
        bcc @fits
        bne @many
        lda G_POOLN
        beq @fits               ; (exactly POOL_MAX)
@many:  lda #LS_THINGS
        jmp ld_stop
@fits:  ldx #POOL_MAX / 8 - 1   ; the bitmap: 0, then bits 0 .. n - 1
:       stz G_TPBITS,x
        dex
        bpl :-
        lda G_POOLN             ; full bytes: n >> 3
        sta GC_T
        lda G_POOLN+1
        lsr a
        ror GC_T
        lsr a
        ror GC_T
        lsr a
        ror GC_T
        ldx #0
@full:  cpx GC_T
        beq @part
        lda #$FF
        sta G_TPBITS,x
        inx
        bra @full
@part:  lda G_POOLN             ; then (1 << (n & 7)) - 1
        and #7
        tay
        lda #0
:       dey
        bmi :+
        sec
        rol a
        bra :-
:       cpx #POOL_MAX / 8
        bcs @tmpl
        sta G_TPBITS,x
@tmpl:  lda G_POOLN              ; the planes' high-water: the pool
        sta G_MOHWM
        lda G_POOLN+1
        sta G_MOHWM+1
        jsr mo_free             ; the template
        stz GC_MO
        stz GC_MO+1
@slot:  lda GC_MO
        cmp G_POOLN
        lda GC_MO+1
        sbc G_POOLN+1
        bcs @done
        jsr gt_mosave
        inc GC_MO
        bne @slot
        inc GC_MO+1
        bra @slot
@done:  rts

; mo_free: LW_MOB = a free mobj: every byte 0 but the handles (none) and
; the type (MT_NOTHING)
mo_free:
        ldx #4 * MO_SIZE + 3 - 1        ; (the spawn's MO_XTICS, MO_XFUNC: 0)
:       stz LW_MOB,x
        dex
        bpl :-
        .assert MO_XTICS = 4 * MO_SIZE && MO_XFUNC = MO_XTICS + 2, error,  "the spawn's working fields"
        ldx #mo_none_end - mo_none - 1
:       ldy mo_none,x
        lda #$FF
        sta LW_MOB,y
        sta LW_MOB+1,y
        dex
        bpl :-
        lda #U_MT_NOTHING
        sta LW_MOB + MO_SIZE + MA_TYPE
        rts
; the handles of a mobj's records (their offsets in LW_MOB)
mo_none:
        .byte TH_SNEXT
        .byte MO_SIZE + MA_THPREV, MO_SIZE + MA_SPREV
        .byte MO_SIZE + MA_BNEXT, MO_SIZE + MA_BPREV, MO_SIZE + MA_SUBSEC
        .byte MO_SIZE + MA_TOUCH, MO_SIZE + MA_STATE, MO_SIZE + MA_TARGET
        .byte 3 * MO_SIZE + MC_LASTEN
mo_none_end:
        .export mo_free

; ---------------------------------------------------------------------------
; gt_pooltake: GC_MO = the pool's free slot with the highest index (its
; bit cleared), GC_K = 1; else (none free) the next zone slot, GC_K = 0
; (LS_ZONE past MOBJ_CAP). Changes A, X, Y.
; ---------------------------------------------------------------------------
gt_pooltake:
        ldx #POOL_MAX / 8 - 1
@byte:  lda G_TPBITS,x
        bne @found
        dex
        bpl @byte
        lda G_ZMFREE+1          ; the zone: its free list's first
        cmp #$FF
        beq @new
        lda G_ZMFREE
        sta GC_MO
        ldx G_ZMFREE+1
        stx GC_MO+1
        jsr pl_get              ; the list: its next
        lda PL_N
        sta G_ZMFREE
        lda PL_N+1
        sta G_ZMFREE+1
        stz GC_K
        rts
@new:   clc                     ; else the one after: G_POOLN + G_ZMN
        lda G_POOLN
        adc G_ZMN
        sta GC_MO
        lda G_POOLN+1
        adc G_ZMN+1
        sta GC_MO+1
        lda GC_MO
        cmp #<MOBJ_CAP
        lda GC_MO+1
        sbc #>MOBJ_CAP
        bcs @full
        lda GC_MO               ; the planes hold it (a stop past them)
        cmp #<PLANE_SLOTS
        lda GC_MO+1
        sbc #>PLANE_SLOTS
        bcs @planes
        inc G_ZMN
        bne :+
        inc G_ZMN+1
:       stz GC_K
        jmp hwm
@full:  lda #LS_ZONE
        jmp ld_stop
@planes:
        lda #LS_PLANES
        jmp ld_stop
@found: ldy #7                  ; its highest bit
:       asl a
        bcs :+
        dey
        bra :-
:       lda bitmask,y           ; cleared
        eor #$FF
        and G_TPBITS,x
        sta G_TPBITS,x
        stz GC_MO+1             ; the slot: 8 x + y
        txa
        asl a
        rol GC_MO+1
        asl a
        rol GC_MO+1
        asl a
        rol GC_MO+1
        sta GC_MO
        tya
        ora GC_MO
        sta GC_MO
        lda #1
        sta GC_K
        ; (on into hwm)
; hwm: G_MOHWM = GC_MO + 1 when that is more
hwm:    clc
        lda GC_MO
        adc #1
        sta GO_T
        lda GC_MO+1
        adc #0
        sta GO_T+1
        lda G_MOHWM
        cmp GO_T
        lda G_MOHWM+1
        sbc GO_T+1
        bcs :+
        lda GO_T
        sta G_MOHWM
        lda GO_T+1
        sta G_MOHWM+1
:       rts
bitmask:
        .byte $01, $02, $04, $08, $10, $20, $40, $80

; ---------------------------------------------------------------------------
; gt_zfree: zone slot GC_MO onto the zone's free list: its kind FN_FREE, its
; next the old first; CS_PREV1, CS_PREV2 naming it become STALE and raise
; GT_ZPREV (docs/GAME.md 1.8). Changes A, X, Y, the API's temporaries.
; ---------------------------------------------------------------------------
gt_zfree:
        ldx #2                  ; CS_PREV2, then CS_PREV1
@prev:  lda CS_PREV1,x
        cmp GC_MO
        bne :+
        lda CS_PREV1+1,x
        cmp GC_MO+1
        bne :+
        lda #<STALE
        sta CS_PREV1,x
        lda #>STALE
        sta CS_PREV1+1,x
        lda #1
        sta GT_ZPREV
:       dex
        dex
        bpl @prev
        .assert CS_PREV2 = CS_PREV1 + 2, error, "CS_PREV1, CS_PREV2"
        lda G_ZMFREE
        sta PL_N
        lda G_ZMFREE+1
        sta PL_N+1
        lda #FN_FREE
        sta PL_K
        stz PL_T
        lda GC_MO
        sta G_ZMFREE
        ldx GC_MO+1
        stx G_ZMFREE+1
        jmp pl_put

; ---------------------------------------------------------------------------
; gt_spectake: a special of kind X: the first of its free list (G_SPFREE,
; through its record's next), else the next slot of its range (LS_SPECIALS
; when the range is full): GC_H = SPEC_HANDLE + the slot. Its record is the
; caller's to write (sp_store). Changes A, X, Y, the API's temporaries.
; ---------------------------------------------------------------------------
gt_spectake:
        txa
        asl a
        tay                     ; Y = 2 kind
        lda G_SPFREE+1,y
        cmp #$FF
        beq @new
        lda G_SPFREE,y          ; the free list's first; the list its next
        sta GC_H
        ldx G_SPFREE+1,y
        stx GC_H+1
        phy
        jsr sp_get
        ply
        lda #SP_THNEXT
        sta GO_I
        phy
        ldy GO_I
        lda (GC_XP),y
        tax
        iny
        lda (GC_XP),y
        ply
        sta G_SPFREE+1,y
        txa
        sta G_SPFREE,y
        rts
@new:   lda G_SPN,y             ; (X: the kind)
        cmp spec_n,x
        lda G_SPN+1,y
        sbc spec_nh,x
        bcs @full
        clc                     ; GC_H = SPEC_HANDLE + lo + count
        lda G_SPN,y
        adc spec_lo,x
        sta GC_H
        lda G_SPN+1,y
        adc spec_loh,x
        sta GC_H+1
        lda G_SPN,y             ; count + 1
        clc
        adc #1
        sta G_SPN,y
        bcc :+
        lda G_SPN+1,y
        inc a
        sta G_SPN+1,y
:       clc
        lda GC_H
        adc #<SPEC_HANDLE
        sta GC_H
        lda GC_H+1
        adc #>SPEC_HANDLE
        sta GC_H+1
        rts
@full:  lda #LS_SPECIALS
        jmp ld_stop
spec_lo:
        .byte <SPK_PLAT_LO, <SPK_DOOR_LO, <SPK_FLOOR_LO
        .byte <SPK_LIGHTFLASH_LO, <SPK_STROBE_LO, <SPK_GLOW_LO
        .byte <SPK_SCROLL_LO
spec_loh:
        .byte >SPK_PLAT_LO, >SPK_DOOR_LO, >SPK_FLOOR_LO
        .byte >SPK_LIGHTFLASH_LO, >SPK_STROBE_LO, >SPK_GLOW_LO
        .byte >SPK_SCROLL_LO
spec_n:
        .byte <SPK_PLAT_N, <SPK_DOOR_N, <SPK_FLOOR_N
        .byte <SPK_LIGHTFLASH_N, <SPK_STROBE_N, <SPK_GLOW_N
        .byte <SPK_SCROLL_N
spec_nh:
        .byte >SPK_PLAT_N, >SPK_DOOR_N, >SPK_FLOOR_N
        .byte >SPK_LIGHTFLASH_N, >SPK_STROBE_N, >SPK_GLOW_N
        .byte >SPK_SCROLL_N
        .assert SPK_PLAT = 0 && SPK_DOOR = 1 && SPK_FLOOR = 2 &&  SPK_LIGHTFLASH = 3 && SPK_STROBE = 4 && SPK_GLOW = 5 &&  SPK_SCROLL = 6, error, "the specials' kinds"

; ---------------------------------------------------------------------------
; gt_spfree: special GC_H onto its kind's free list (the kind from its
; slot's range): its function none, its next the old first. Changes A, X,
; Y, the API's temporaries.
; ---------------------------------------------------------------------------
gt_spfree:
        sec                     ; the slot: GC_H - SPEC_HANDLE
        lda GC_H
        sbc #<SPEC_HANDLE
        sta GO_T
        lda GC_H+1
        sbc #>SPEC_HANDLE
        sta GO_T+1
        ldx #SPK_SCROLL         ; the kind: the last range that starts at
@kind:  lda GO_T                ;   or before it
        cmp spec_lo,x
        lda GO_T+1
        sbc spec_loh,x
        bcs :+
        dex
        bpl @kind
:       txa
        asl a
        pha
        lda GC_H
        ldx GC_H+1
        jsr sp_get
        ply
        lda #FN_NONE            ; no function
        phy
        ldy #SP_FUNC
        sta (GC_XP),y
        ply
        lda G_SPFREE,y          ; its next: the list's first
        phy
        ldy #SP_THNEXT
        sta (GC_XP),y
        ply
        lda G_SPFREE+1,y
        phy
        ldy #SP_THNEXT + 1
        sta (GC_XP),y
        ply
        lda GC_H
        sta G_SPFREE,y
        lda GC_H+1
        sta G_SPFREE+1,y
        jmp sp_dirty

; ---------------------------------------------------------------------------
; gt_nodetake: GC_N = a free sector node, taken off the free list (a new
; pool of SN_POOL nodes first when it is empty: LS_NODES past SN_CAP).
; Its record is the caller's to write. Changes A, X, Y, GC_P, GC_T, FA_*.
; ---------------------------------------------------------------------------
gt_nodetake:
        lda G_SNFREE+1
        cmp #$FF
        jne @take
        clc                     ; a new pool: G_SNHWM + 32 <= SN_CAP
        lda G_SNHWM
        adc #SN_POOL
        sta GC_T
        lda G_SNHWM+1
        adc #0
        sta GC_T+1
        lda #<SN_CAP
        cmp GC_T
        lda #>SN_CAP
        sbc GC_T+1
        bcs :+
        lda #LS_NODES
        jmp ld_stop
:       ldx #SN_SIZE - 1        ; the free node's record: sector none,
:       stz LW_SN,x             ;   free, links none, visited 0
        dex
        bpl :-
        lda #$FF
        ldx #SN_SNEXT + 1 - SN_THING
:       sta LW_SN + SN_THING,x
        dex
        bpl :-
        sta LW_SN + SN_SECTOR
        lda #1
        sta LW_SN + SN_FREE
        lda G_SNHWM             ; the free list: the pool's first
        sta G_SNFREE
        lda G_SNHWM+1
        sta G_SNFREE+1
        ldy #SN_POOL
@new:   phy
        lda G_SNHWM             ; its next: the one after, or none
        ldx G_SNHWM+1
        clc
        adc #1
        bcc :+
        inx
:       sta LW_SN + SN_TNEXT
        stx LW_SN + SN_TNEXT + 1
        ply
        cpy #1
        bne :+
        lda #$FF
        sta LW_SN + SN_TNEXT
        sta LW_SN + SN_TNEXT + 1
:       phy
        lda G_SNHWM
        ldx G_SNHWM+1
        jsr sn_addr
        lda #ZONE1
        sta FA_BANK
        lda GC_P
        sta FA_DST
        lda GC_P+1
        sta FA_DST+1
        lda #<LW_SN
        ldx #>LW_SN
        ldy #SN_SIZE
        jsr g_put
        inc G_SNHWM
        bne :+
        inc G_SNHWM+1
:       ply
        dey
        bne @new
@take:  lda G_SNFREE            ; the first free node; the list its next
        sta GC_N
        ldx G_SNFREE+1
        stx GC_N+1
        jsr sn_addr
        lda #ZONE1
        sta FA_BANK
        clc
        lda GC_P
        adc #SN_TNEXT
        sta FA_SRC
        lda GC_P+1
        adc #0
        sta FA_SRC+1
        lda #<G_SNFREE
        ldx #>G_SNFREE
        ldy #2
        jmp g_get

; sn_addr: GC_P = SN_BASE + 16 * A:X. Changes A, X.
sn_addr:
        sta GC_P
        txa
        ldx #4
:       asl GC_P
        rol a
        dex
        bne :-
        sta GC_P+1
        clc
        lda GC_P
        adc #<SN_BASE
        sta GC_P
        lda GC_P+1
        adc #>SN_BASE
        sta GC_P+1
        rts
        .export sn_addr

; P_Random's table (Doom's: math.s's, from the reference's RAM)
rndtable:
        .incbin "rndtable.bin"
