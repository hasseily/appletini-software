; gthink.s: the game core's thinker list, its pools and P_Random
; (milestone 9, stage C; docs/LEVELS.md 2.4, 3.1, 3.2). A GPL-2 derivative
; of upstream's p_think65.s (P_InitThinkers, P_AddThinker), p_spawn65.s
; (poolInit, poolTake), p_map65.s (newSecnode's pool) and m_random65.s.
;
;   gt_init      the thinker list empty, the sector nodes' pools freed
;                (Z_FreeTags, P_SetSecnodeFirstpoolToNull), no specials,
;                no zone mobjs
;   gt_add       P_AddThinker: the thinker GC_H at the list's end; GC_PREV
;                = its previous one (the caller writes the new record's
;                links: prev GC_PREV, next none); the old last one's next
;                written in its record
;   gt_poolinit  poolInit: the pool's G_POOLN slots free (the bitmap
;                G_TPBITS: bit i & 7 of byte i >> 3, 1 free) and each
;                slot's records a free mobj: type MT_NOTHING, the rest 0
;                or none (Z_CallocLevel's zeros: the native nulls are
;                $FFFF handles)
;   gt_pooltake  newMobj's slot: the pool's free slot with the highest
;                index (poolTake), else the next zone slot (Z_MallocLevel:
;                docs/LEVELS.md 3.1); GC_MO the slot, GC_K 1 when pooled
;   gt_spectake  a special of kind X (llayout.SPEC_KINDS' order): the next
;                slot of its range; GC_H its handle, GC_P its record's
;                address in ZONE0
;   gt_nodetake  newSecnode's node: the first of the free list, a new pool
;                of SN_POOL linked nodes when the list is empty (so the free
;                list's length is upstream's); GC_N the node
;   gt_moaddr    GC_P = the records' address of the mobj slot A:X (RTHING
;                and the three game parts: RTHBASE + 24 slot)
;   gt_mosave    the mobj LW_MOB (its RTHING and game parts A, B, C) into
;                slot GC_MO
;   g_random     A = P_Random(): rndtable[++index] (main $03EE)
;   g_get, g_put Y bytes (0: 256) of FA_BANK:FA_SRC into main A:X, of
;                main A:X to FA_BANK:FA_DST (far_get, far_put)
;
; A thinker handle is a mobj's slot (0-2,025) or SPEC_HANDLE + a special's
; slot; $FFFF is none (its high byte $FF names nothing else). The thinker
; links are at the same offsets in a mobj's game part A and in a special's
; record (MA_THPREV = SP_THPREV, MA_THNEXT = SP_THNEXT).

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"

        .export gt_init, gt_add, gt_poolinit, gt_pooltake, gt_spectake
        .export gt_nodetake, gt_moaddr, gt_mosave, gt_threc, g_random
        .export g_get, g_put, g_put2, g_zero, rndtable
        .import far_get, far_put, ld_stop

        .assert MA_THPREV = SP_THPREV && MA_THNEXT = SP_THNEXT, error,  "the thinker links' offsets"
        .assert >SPEC_HANDLE > >(MOBJ_CAP - 1), error, "thinker handles"

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
        rts
        .assert G_SPN = G_SNHWM + 2 && G_ZMN = G_SPN + 14, error,  "the counts' order"

; ---------------------------------------------------------------------------
; gt_threc: FA_BANK and GC_P = the record of thinker A:X (a mobj's game
; part A, a special's record). Changes A, X.
; ---------------------------------------------------------------------------
gt_threc:
        cpx #>SPEC_HANDLE
        bcs @spec
        jsr gt_moaddr
        lda #MOBJA
        sta FA_BANK
        rts
@spec:  sec                     ; GC_P = SPEC_BASE + 32 (h - SPEC_HANDLE)
        sbc #<SPEC_HANDLE
        sta GC_P
        txa
        sbc #>SPEC_HANDLE
        ldx #5
:       asl GC_P
        rol a
        dex
        bne :-
        sta GC_P+1
        clc
        lda GC_P
        adc #<SPEC_BASE
        sta GC_P
        lda GC_P+1
        adc #>SPEC_BASE
        sta GC_P+1
        lda #ZONE0
        sta FA_BANK
        rts

; ---------------------------------------------------------------------------
; gt_add: P_AddThinker(GC_H): GC_PREV = the list's last thinker; its next
; = GC_H (in its record), or the list's first when it was empty; the last
; = GC_H. Changes A, X, Y, GC_P, FA_*.
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
@link:  jsr gt_threc                ; the old last's next = GC_H
        clc
        lda GC_P
        adc #MA_THNEXT
        sta FA_DST
        lda GC_P+1
        adc #0
        sta FA_DST+1
        lda #<GC_H
        ldx #>GC_H
        jsr g_put2
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
; each) into its slot GC_MO. Changes A, X, Y, GC_P, FA_*.
; ---------------------------------------------------------------------------
gt_mosave:
        lda GC_MO
        ldx GC_MO+1
        jsr gt_moaddr
        ldx #3
@part:  lda mo_banks,x
        sta FA_BANK
        lda GC_P
        sta FA_DST
        lda GC_P+1
        sta FA_DST+1
        phx
        lda mo_parts,x
        ldx #>LW_MOB
        ldy #MO_SIZE
        jsr g_put
        plx
        dex
        bpl @part
        rts
mo_banks:
        .byte RTH, MOBJA, MOBJB, MOBJC
mo_parts:
        .byte <LW_MOB, <(LW_MOB + MO_SIZE), <(LW_MOB + 2 * MO_SIZE)
        .byte <(LW_MOB + 3 * MO_SIZE)
        .assert >LW_MOB = >(LW_MOB + 4 * MO_SIZE - 1), error,  "LW_MOB in one page"

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
@tmpl:  jsr mo_free             ; the template
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
        ldx #4 * MO_SIZE - 1
:       stz LW_MOB,x
        dex
        bpl :-
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
        .byte MO_SIZE + MA_THPREV, MO_SIZE + MA_THNEXT, MO_SIZE + MA_SPREV
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
        clc                     ; the zone: G_POOLN + G_ZMN
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
        inc G_ZMN
        bne :+
        inc G_ZMN+1
:       stz GC_K
        rts
@full:  lda #LS_ZONE
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
        rts
bitmask:
        .byte $01, $02, $04, $08, $10, $20, $40, $80

; ---------------------------------------------------------------------------
; gt_spectake: a special of kind X: the next slot of its range (LS_SPECIALS
; when the range is full): GC_H = SPEC_HANDLE + the slot, GC_P = its
; record's address, FA_BANK = ZONE0. Changes A, X, Y.
; ---------------------------------------------------------------------------
gt_spectake:
        txa
        asl a
        tay                     ; Y = 2 kind: its count in G_SPN
        lda G_SPN,y
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
        tay
        lda GC_H+1
        adc #>SPEC_HANDLE
        sta GC_H+1
        tax
        tya
        jmp gt_threc
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
