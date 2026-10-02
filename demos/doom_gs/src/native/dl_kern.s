; dl_kern.s: the main loop's resident kernel (docs/PLAY.md 2, 3), the
; playable game's: in the main card at $FF00, pl_ready's place (DOOM.SYSTEM
; ends with jmp pl_ready, which the second half replaces with the title
; loop: docs/SCREENS.md 2.5; the play build's link puts this code there in
; pl_ready's stead), and its menu loop in main $0880-$08FF and $0B94-$0BFF
; (read-only code: DLINIT's PRIVATE copy puts it there with the static
; tables, in MEMORY_MAP.md 3.2's free bytes of $0800-$0BFF). GPL-2, the port's own.
;
; W ($6000-$BFFF) holds one image at a time, so the main loop's logic is
; the brain's (src/native/dl_brain.s and its groups, in the tic image):
; at every frame the brain writes the frame's step list into DLBUF ($FE80,
; one page of the card), and this kernel runs it. A step:
;
;   K_END            the list's end: the next frame (K_TIC E_FRAME)
;   K_LOAD b, runs   far_pload of bank b's page runs (first page, count;
;                    a first page 0 ends them: in the card, near in the
;                    phase loader's RAMRD window)
;   K_CALL a, A, X   jsr a with A and X (Y 0); its A into DL_RES
;   K_WLOAD          far_wload (the render front end's window)
;   K_MLOAD          far_mload (the masked phase's image)
;   K_TIC code       the tic image's W and core from GCODE0 and the walk's
;                    planes from MOBJP into W, the slots empty, then the
;                    brain (dl_brain, its group through gcall.s's fc_go)
;                    with DL_CODE = code; the brain writes the next list
;   K_MENU           the menu's paused frames, with MENUW in W (R7 item
;                    9): each queued event to m_responder (a key the menu
;                    does not eat goes to gamekeydown, G_Responder's keys),
;                    m_ticker for each new tic (at most MAXTICS), m_frame;
;                    until the menu closes or makes a request
;   K_HALT           interrupts off, the end (the quit)
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
        lda #$FF                ; the slots hold nothing (W was another's)
        sta SLOT_GRP
        sta SLOT_GRP+1
        sta SLOT_GRP+2
        lda #<k_core
        ldx #>k_core
        ldy #GCODE0
        jsr XS_far_pload
        lda #<k_planes
        ldx #>k_planes
        ldy #MOBJP
        jsr XS_far_pload
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

k_ops:  .addr k_end, k_load, k_call, k_wload, k_mload, k_tic1, k_menu
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
        jsr XS_far_pload
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

k_wload:
        sty KV_PTR
        jsr XS_far_wload
        bra k_ret
k_mload:
        sty KV_PTR
        jsr XS_far_mload
        bra k_ret

dl_halt:
        sei
:       bra :-

; the page runs of the tic image's W and core (GCODE0) and of the walk's
; planes (MOBJP): far_pload's lists, near in its RAMRD window
k_core:   .byte $60, XS_CORE_PAGES, 0
k_planes: .byte >PL_TNL, (PL_TICS + PLANE_SLOTS - PL_TNL) >> 8, 0

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
