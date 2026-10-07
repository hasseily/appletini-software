; dl_kern.s: the main loop's resident kernel (docs/PLAY.md), the
; playable game's: in the main card at $FF00, pl_ready's place (DOOM.SYSTEM
; ends with jmp pl_ready, which the second half replaces with the title
; loop: docs/SCREENS.md; the play build's link puts this code there in
; pl_ready's stead), and its menu loop in main $0880-$08FF and $0B94-$0BFF
; (read-only code: DLINIT's PRIVATE copy puts it there with the static
; tables, in docs/MEMORY_MAP.md's free bytes of $0800-$0BFF). GPL-2, the port's own.
;
; W ($6000-$BFFF) holds one image at a time, so the main loop's logic is
; the brain's (src/native/dl_brain.s and its groups, in the tic image):
; at every frame the brain writes the frame's step list into DLBUF ($FE80,
; one page of the card), and this kernel runs it. A step:
;
;   K_END            the list's end: the next frame (K_TIC E_FRAME)
;   K_LOAD b, runs   bank b's page runs (first page, count; a first page
;                    0 ends them) into main at the same addresses: one
;                    memory-API PRIVATE request, a descriptor a run
;                    (gcall.s's am_runs in the card; docs/SPEED.md). The
;                    render front end's window and the masked phase's image
;                    come this way too (the brain's img_wload, img_mload:
;                    far_wloadt's and far_mload's runs)
;   K_CALL a, A, X   jsr a with A and X (Y 0); its A into DL_RES
;   K_WLOAD, K_MLOAD (not used since the copy engine: a stop)
;   K_TIC code       the tic image's core (and its W unless the list
;                    ended with P2DW, which left the same bytes there) from
;                    GCODE0 and the walk's planes (each plane's pages below
;                    G_MOHWM) from MOBJP into W, a request each (am_runs),
;                    the slots empty (the frame
;                    slots too: the brain restored their colormap bytes at
;                    the last tic phase's end, gcall.s's fs_restore), then the
;                    brain (dl_brain, its group through gcall.s's fc_go)
;                    with DL_CODE = code; the brain writes the next list
;                    and, at its end, the two load lists k_core and k_planes
;                    (dl_disp.s kc_from, planes_out: at KLISTS, a fixed
;                    place, as the tic image is linked before this card)
;   K_MENU           the menu's paused frames, with MENUW in W: each queued event to m_responder (a key the menu
;                    does not eat goes to gamekeydown, G_Responder's keys),
;                    m_ticker for each new tic (at most MAXTICS), m_frame;
;                    until the menu closes or makes a request
;   K_HALT           interrupts off, the end (the quit)
;
;   far_gcopy        a group's copy in one RAMRD window, at KERN_GCOPY:
;                    gr_load's until the copy engine took it (docs/SPEED.md);
;                    no code calls it now
;   bt_mark          the benchmark's phase timing (docs/PLAY.md): a
;                    phase boundary (a K_CALL of the list, or bt_replay's),
;                    at BT_MARK and BT_MARK2 in the menu loop's free main
;                    bytes, its middle part the brain's at BT_EXT
;   bt_replay        nat_replay's entry while the benchmark is timed (the
;                    card, BT_REPLAY): the replay of a batch timed apart
;
; k_sdfail (main KMAIN, its fixed place) is m_savedone with C set (a save
; failed: none in this version), for a K_CALL. The kernel keeps nothing in zero page between steps (every
; image uses it): its bytes are KV_* in the card and DL_* in main's DLM.

        .setcpu "65C02"
        .include "rlayout.inc"
        .include "s2.inc"
        .include "play.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "playsym.inc"
        .include "playk.inc"

        .import pl_time
        .export dl_kernel, dl_run, dl_halt, dl_mwait, k_sdfail, k_menu

        .segment "DLKERN"

; ---------------------------------------------------------------------------
; dl_kernel: from the boot's jmp pl_ready
; ---------------------------------------------------------------------------
dl_kernel:
        ldx #$FF
        txs
        lda #E_BOOT
k_tic:  sta DL_CODE
        lda #$FF                ; the slots hold nothing (W was another's;
        ldx #SLOT_CLR - 1       ;   the frame slots were restored at the
:       sta SLOT_GRP,x          ;   tic phase's end), no active frame needs
        dex                     ;   one (gcall.s's lazy restore), no frame
        bpl :-                  ;   slot to restore: SLOT_GRP, SLOT_NEED,
                                ;   FS_DIRTY
        .assert FS_DIRTY + 1 - SLOT_GRP = SLOT_CLR, error, "SLOT_GRP .. FS_DIRTY"
        lda #<k_core
        ldx #>k_core
        ldy #GCODE0
k_tcore:                        ; (the loads' labels: here, k_tplan and
        jsr XS_am_runs          ;   k_tbrain)
        lda #<k_planes
        ldx #>k_planes
        ldy #MOBJP
k_tplan:
        jsr XS_am_runs
k_tbrain:
        lda #XS_DLG_BRAIN
        sta FC_GRP
        lda #<XS_dl_brain
        sta FC_T
        lda #>XS_dl_brain
        sta FC_T+1
        jsr k_go
dl_run: ldy #0
run:    lda DLBUF,y
        iny
        asl a
        tax
        jmp (k_ops,x)
k_go:   jmp XS_fc_go            ; (the caller's return on the stack)

k_ops:  .addr k_end, k_load, k_call, dl_halt, dl_halt, k_tic1, k_menu
        .addr dl_halt

k_end:  lda #E_FRAME
        bra k_tic
k_tic1: lda DLBUF,y
        bra k_tic

k_load: lda DLBUF,y             ; the bank
        sta KV_BANK
        iny
        sty KV_PTR
        tya                     ; the runs at DLBUF + y: $FE80 | y
        ora #<DLBUF
        ldx #>DLBUF
        ldy KV_BANK
k_lrun: jsr XS_am_runs          ; (the step: the bank in Y)
        ldy KV_PTR
:       lda DLBUF,y             ; past the runs
        beq :+
        iny
        iny
        bra :-
:       iny
        bra run

k_call: lda DLBUF,y
        sta k_jsr+1
        lda DLBUF+1,y
        sta k_jsr+2
        ldx DLBUF+3,y
        lda DLBUF+2,y
        iny
        iny
        iny
        iny
        sty KV_PTR
        ldy #0
k_jsr:  jsr k_go                ; (the step's address)
        sta DL_RES
k_ret:  ldy KV_PTR
        bra run

dl_halt:
        sei
:       bra :-

; the page runs of the tic image's W and core (GCODE0) and of the walk's
; four planes (MOBJP): am_runs' lists (in the card: K_TIC replaces W), at
; KLISTS (BT_REPLAY - 12), where the tic image's dl_disp.s rewrites them
; at each list's end: k_core from $66 after P2DW (kc_from; playdisk.py
; asserts the shared bytes), each plane's count the pages below G_MOHWM
; (planes_out, 1-3). These are the boot's: everything.
KLISTS = BT_REPLAY - 12
        .res KLISTS - KERNEL - (* - dl_kernel)
k_core:   .byte $60, XS_CORE_PAGES, 0
k_planes: .byte >PL_TNL, PLANE_SLOTS >> 8, >PL_TNH, PLANE_SLOTS >> 8
          .byte >PL_KIND, PLANE_SLOTS >> 8, >PL_TICS, PLANE_SLOTS >> 8, 0
        .assert k_core = KLISTS && k_planes = KLISTS + 3, lderror, "the kernel's lists are not at KLISTS"
        .assert PL_TNH = PL_TNL + PLANE_SLOTS && PL_TICS + PLANE_SLOTS = $C000, error, "the planes"

; ---------------------------------------------------------------------------
; bt_replay: nat_replay's entry while the benchmark is timed (docs/PLAY.md):
; the brain's bt_start writes jmp bt_replay over nat_replay's first
; instruction (sta gcol), which it keeps in BT_J with jmp nat_replay + 3
; after it. A batch's replay is the phase PH_DRAW, then PH_MASK again (the
; bucket pass's next batch). A, X: nat_replay's (Y it does not read).
; ---------------------------------------------------------------------------
        .assert * = BT_REPLAY, lderror, "bt_replay is not at BT_REPLAY"
bt_replay:
        pha
        phx
        lda #PH_DRAW
        jsr bt_mark
        plx
        pla
        jsr BT_J                ; (nat_replay)
bt_rback:
        lda #PH_MASK
        jmp bt_mark

; ---------------------------------------------------------------------------
; far_gcopy: FA_N pages (1-255) of RamWorks bank FA_BANK from FA_SRC to
; main FA_DST, both with the same low byte, but the first Y bytes (Y even:
; the first page from byte Y), in one RAMRD window (gcall.s's gr_load's
; copy of a group to the frame slots, before the copy engine: since
; then a memory-API request makes it, docs/SPEED.md; no code calls this
; copy now). In the card: with RAMRD on,
; the fetches of $0200-$BFFF come from the bank. Its window, as
; far_pload's, writes $C073 at its start and 0 at its end. Changes A, Y,
; FA_SRC, FA_DST (their high bytes on by FA_N), FA_N.
; ---------------------------------------------------------------------------
GC_RAMRDOFF = $C002
GC_RAMRDON  = $C003
GC_RWBANK   = $C073
        .res KERN_GCOPY - KERNEL - (* - dl_kernel)  ; (its fixed place,
                                ;   the tic image's jsr: DLKERN from
                                ;   KERNEL, playlink.py's check)
far_gcopy:
        lda FA_BANK
        sta GC_RWBANK
        sta GC_RAMRDON
@page:  lda (FA_SRC),y          ; read from the bank (RAMRD), written to
        sta (FA_DST),y          ;   main
        iny
        lda (FA_SRC),y
        sta (FA_DST),y
        iny
        bne @page
        inc FA_SRC+1
        inc FA_DST+1
        dec FA_N
        bne @page
        sta GC_RAMRDOFF
        stz GC_RWBANK
        rts
        .assert far_gcopy = KERN_GCOPY, lderror, "far_gcopy is not at KERN_GCOPY"
        .assert * <= KERNEL + $FA, lderror, "far_gcopy passes the vectors"

; ---------------------------------------------------------------------------
; K_MENU: the paused frames (d_main65.s's tryRunTics with a menu up: only
; M_Ticker for the new tics, no tic command kept; uiDisplay). In main
; $0880-$08FF and $0B94-$0BFF: read-only code, nothing stores into it
; ---------------------------------------------------------------------------
        .segment "DLKMAIN"

; k_sdfail at KMAIN, the list's fixed address (the tic image is linked
; before this card)
k_sdfail:
        sec
        jmp XS_m_savedone
        .assert k_sdfail = KMAIN, lderror, "k_sdfail is not at KMAIN"

k_menu: sty KV_PTR
km_ev:  ldx PL_QHEAD            ; the events, in order
        cpx PL_QTAIL
        bne :+
        jmp km_tic
:       stx KV_N                ; (the head)
        lda PL_QUEUE+1,x        ; m_responder: A the type, X data1
        pha
        lda PL_QUEUE,x
        plx
        jsr XS_m_responder
        ldx KV_N
        cmp #0
        bne km_pop
        lda PL_QUEUE+2,x        ; not the menu's: G_Responder's keys
        bne km_pop              ;   (gamekeydown of a Doom key, down 1,
        ldy PL_QUEUE+1,x        ;   up 0)
        cpy #NUMKEYS
        bcs km_pop
        lda PL_QUEUE,x
        eor #1
        sta DL_KEYS,y
km_pop: txa
        clc
        adc #PL_EVENT_SIZE
        cmp #PL_EVENTS * PL_EVENT_SIZE
        bcc :+
        lda #0
:       sta PL_QHEAD
        bra km_ev

; ---------------------------------------------------------------------------
; bt_mark: a phase boundary of the benchmark's timing (docs/PLAY.md), a
; K_CALL of the frame's list or bt_replay's call. A = the phase that starts
; (PH_*). VIA-A's timer 1 (the Phasor's, free-running, counting the Apple
; bus cycles down: pl_detect's, which nothing else uses after the boot) is
; read low then high, both again when the low byte was near its borrow
; (the high byte is read 5 cycles after the low: 4, and the extra tick a
; native-mode low read makes); the cycles since the last boundary (mod
; 65,536) are added to the phase that ran (BT_PH, none when 0), then A is
; the phase. Its middle part, at BT_EXT (main $0844-$0877, free), is the
; brain's (dl_brain.s bt_ext, which bt_start copies there): vbl_count's low
; byte kept with the reading (the brain's bt_close times the tic phase
; from them, that phase being longer than the timer's turn), and the phase
; of an interval of 3 VBLs or more (it may pass the turn) kept for
; bt_close, which adds the turns the short phases lost to it. A, X, Y
; changed. In main $08CA-$08F3 and $0BE1-$0BFF (the menu loop's free
; bytes) and $0844-$0867.
; ---------------------------------------------------------------------------
VIA_T1CL = $C414                ; the Phasor's VIA-A, timer 1 (both modes:
VIA_T1CH = $C415                ;   pl_irq.s's pl_detect)
        .assert * = BT_MARK, lderror, "bt_mark is not at BT_MARK"
bt_mark:
        pha
        ldx VIA_T1CL            ; the timer: low, then high
        ldy VIA_T1CH
        cpx #8                  ; (the high may have borrowed: read again,
        bcs :+                  ;   past the borrow)
        ldx VIA_T1CL
        ldy VIA_T1CH
:       sec                     ; the cycles since the last boundary: the
        lda BT_T                ;   last reading - this one (a counter
        stx BT_T                ;   down), into Y:X; this one kept
        sbc BT_T
        tax
        lda BT_T+1
        sty BT_T+1
        sbc BT_T+1
        tay
        jmp BT_EXT              ; (then BT_MARK2, A = X, X = BT_PH)

        .segment "DLKMAIN2"     ; (main $0B94-$0BFF: read-only code)
km_tic: jsr pl_time             ; the new tics: M_Ticker each, at most
        sta KV_T                ;   MAXTICS (lastmadetic takes them all)
        stx KV_T+1
        sec
        sbc DL_LASTM
        beq km_fr
        ldx KV_T
        stx DL_LASTM
        ldx KV_T+1
        stx DL_LASTM+1
        cmp #MAXTICS + 1
        bcc :+
        lda #MAXTICS
:       sta KV_N
:       jsr XS_m_ticker
        dec KV_N
        bne :-
km_fr:  jsr XS_m_frame
        lda M_REQ               ; a request: the brain's
        bne km_out
        lda G_MENUACTIVE        ; the menu closed, no message: the game's
        ora M_MSGPRINT          ;   frames again
        beq km_out
dl_mwait:
        jsr pl_time             ; the next tic (a2vm's idle loop)
        cmp DL_LASTM
        beq dl_mwait
        jmp km_ev
km_out: ldy KV_PTR
        jmp run

; bt_mark's last part: Y:X (A its low byte) into the phase X's 4 bytes
        .assert * = BT_MARK2, lderror, "bt_mark2 is not at BT_MARK2"
bt_mark2:
        beq @out
        clc
        adc BT_S-4,x
        sta BT_S-4,x
        tya
        adc BT_S-3,x
        sta BT_S-3,x
        bcc @out
        inc BT_S-2,x
        bne @out
        inc BT_S-1,x
@out:   pla
        sta BT_PH
        rts
