; gdriver.s: the a2vm test driver of the tic phase (milestone 10, docs/GAME.md
; 3.4, 3.6). Not part of the game: it lives in the card's $E000 part,
; which the game gives the sound and the IRQ (test builds only, as
; ldriver.s). GPL-2, the port's own.
;
; The harness's image (tools/native/grun.py) is the machine with the
; store's banks, the card (the math's tables and code, the far layer, the
; phase loader, this driver), the tic image in GCODE0 (W's MATHW, AUXW and
; the core at their addresses; the groups anywhere in GCODE0-1, the group
; directory in the core's grp_bank, grp_src, grp_pages), the load image in
; LCODE, the planes in MOBJP, the game state (the bridge's port writer
; through native-game-1), GTEST (the schedule, the stream, the I_GetTime
; values, the re-key records), the descriptor DESC below, and every other
; byte poisoned. drv_game starts it:
;
;   the mouse card's VBL interrupt on (a stub that counts it); the core
;   image into W (far_pload, dg_core's runs from GCODE0); the API's caches
;   empty (go_reset), the slots empty, the logs empty; the planes into W
;   (dg_planes' runs from MOBJP); then by dg_mode:
;
;   DM_ROUTINE       the routine dg_entry (group dg_grp: through fc_call's
;                    path, so a group routine runs in its slot) with A, X,
;                    Y, P = dg_a, dg_x, dg_y, dg_p (the zero page and the
;                    arguments are the image's); its A, X, Y, P into dg_ra
;                    .. dg_rp; go_flush, the planes out; drv_done (the
;                    snapshot point); the halt
;   DM_ROUTINE_LOAD  the same, and while the routine (or the continuation)
;                    returns GT_LOAD: the load protocol, then the
;                    continuation (dg_resume); drv_done
;   DM_LOCKSTEP      the tic loop: at each G_Ticker entry go_flush, the
;                    planes out, drv_tic (the snapshot point: a snapshot
;                    event a tic), the sound and hit logs emptied; the end
;                    when D_AdvanceDemo has run (GT_FLAGS bit 0) or gametic
;                    reaches dg_stop; the tic (dg_ticker: G_Ticker), and
;                    while it returns GT_LOAD the load protocol and the
;                    continuation (dg_resume: g_resume); then the
;                    schedule's frame when its gametic is reached (FRONT,
;                    FULL: go_flush, the planes out, the render inputs
;                    (ri_make), the render window and dg_frame, then the
;                    tic image and the planes again)
;   DM_LOADTEST      the load protocol once (S5's check on hand-made data)
;
; The load protocol (GAME.md 3.4, review 3): G_Ticker returned GT_LOAD with
; G_LOADACT, the action that started the load; the caches flushed and
; emptied, the planes out; the load image (dg_lcode's runs from LCODE) and
; nl_setup (dg_nlsetup) of G_GAMEMAP; drv_loaded (a snapshot point); in
; test builds the setup's re-key record (GTEST GT_REKEYS, record
; dg_rekey): CS_PREV1, CS_PREV2 and the sight hint by pool slot (HINTL,
; HINTH); the tic image and the planes again.
;
; A BRK (a stop: GS_STATUS or LV_STATUS) goes to drv_crash, where a2vm
; stops.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .import far_pload, far_wload, far_get, far_put, go_flush, go_reset
        .import fc_go, fc_call, fc_unbuilt, state_at, g_stop
        .export drv_game, drv_done, drv_tic, drv_loaded, drv_frame
        .export drv_halt, drv_crash, drv_irq, drv_end, planes_out
        .export dg_mode, dg_entry, dg_grp, dg_a, dg_x, dg_y, dg_p
        .export dg_ra, dg_rx, dg_ry, dg_rp, dg_ticker, dg_resume
        .export dg_nlsetup, dg_frame, dg_stop, dg_rekey, dg_sched
        .export dg_core, dg_planes, dg_lcode, dg_tcount, dg_loads
        .export far_gcopy
.ifdef TICLEVEL
        .export dg_fwl, dg_fml, dg_fmm, dg_fbl, dg_fnb, dg_fkind, dg_strm
        .export dg_scnt, dg_nosnap, dg_wipe
        .export drv_fmend, drv_fend
.endif
        .exportzp IRQCNT

MOUSE_MODE = $C0AE
MOUSE_ACK  = $C0AF
MODE_VBL   = $08
INTCXROMOFF = $C006
IRQCNT  = $D8
PH_EXIT = 18                    ; GPROF (docs/GAME.md 5.4): the tic phase's
                                ;   entry and exit (the images, the
                                ;   planes, the flush);
PH_TIC  = 30                    ;   the tic (a2vm --cost-pcmap-when: the
                                ;   PC map gives its subsystems, 19-30);
PH_LOAD = 31                    ;   a level's load

        .segment "DRIVER"

drv_game:
        lda #<drv_irq
        sta $FFFE
        lda #>drv_irq
        sta $FFFF
        stz IRQCNT
        stz IRQCNT+1
        sta INTCXROMOFF
        lda #MODE_VBL
        sta MOUSE_MODE
        cli
        jsr core_in
        jsr go_reset
        lda #$FF
        sta SLOT_GRP
        sta SLOT_GRP+1
        sta SLOT_GRP+2
        sta SLOT_NEED           ; (no active frame needs a slot)
        sta SLOT_NEED+1
        ldx #0
        stx GO_HITS             ; the API's and the paging's counters
        stx GO_HITS+1
        stx GO_MISS
        stx GO_MISS+1
        stx GO_WBACK
        stx GO_WBACK+1
        stx FC_LOADS
        stx FC_LOADS+1
        stx GT_FLAGS
        stx GT_SNDLOG
        stx GT_SNDLOG+1
        stx GT_HITLOG
        stx GT_HITLOG+1
        stx GT_TIMEP
        stx GT_TIMEP+1
        stx GT_DIV0
        stx GT_DIV0+1
        stx dg_loads
        stx dg_sched
        stx dg_sched+1
        jsr planes_in
        lda dg_mode
        cmp #DM_LOCKSTEP
        jeq lockstep
        cmp #DM_LOADTEST
        bne :+
        jsr load
        bra done
:       cmp #DM_ROUTINE
        beq :+
        cmp #DM_ROUTINE_LOAD
        beq :+
        lda #GS_DRIVER
        jmp g_stop
:       lda dg_p                ; the routine, with its registers
        pha
        lda dg_a
        ldx dg_x
        ldy dg_y
        plp
        jsr call_entry
        php
        sta dg_ra
        stx dg_rx
        sty dg_ry
        pla
        sta dg_rp
        lda dg_mode
        cmp #DM_ROUTINE_LOAD
        bne done
:       lda dg_ra               ; a load: the protocol and the continuation
        cmp #GT_LOAD
        bne done
        jsr load
        jsr call_resume
        sta dg_ra
        bra :-
done:   jsr go_flush
        jsr planes_out
drv_done:                       ; (the snapshot point: after the flush)
        nop
drv_end:
        sei
        stz MOUSE_MODE
        lda #3
        sta MOUSE_ACK
drv_halt:
        bra drv_halt
drv_crash:
        bra drv_crash

; call_entry: dg_entry in group dg_grp (0: the core), A, X, Y kept
call_entry:
        sta FC_A
        stx FC_X
        sty FC_Y
        lda dg_entry
        sta FC_T
        lda dg_entry+1
        sta FC_T+1
        lda dg_grp
        sta FC_GRP
        bne :+
        lda FC_A
        jmp (FC_T)
:       jmp fc_go               ; (the return: this caller)

call_ticker:
        lda dg_ticker
        sta FC_T
        lda dg_ticker+1
        sta FC_T+1
        jmp (FC_T)
call_resume:
        lda dg_resume
        sta FC_T
        lda dg_resume+1
        sta FC_T+1
        jmp (FC_T)

; ---------------------------------------------------------------------------
; Lockstep-schedule mode
; ---------------------------------------------------------------------------
lockstep:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_EXIT        ; the driver's own work (the timing report)
        sta PHASE
.endif
.endif
.ifdef TICLEVEL
        jsr stream              ; the tic's command and events (dg_strm)
        lda dg_nosnap           ; (a run with no snapshot a tic: the
        bne drv_tic             ;   timing's, the flush before frames only)
.endif
        jsr go_flush
        jsr planes_out
drv_tic:                        ; (a snapshot event a tic: the harness's)
        nop
        stz GT_SNDLOG           ; the logs, emptied after the snapshot
        stz GT_SNDLOG+1
        stz GT_HITLOG
        stz GT_HITLOG+1
        lda GT_FLAGS            ; the demo has ended
        and #1
        jne drv_end
        lda G_GAMETIC           ; gametic >= dg_stop: the end
        cmp dg_stop
        lda G_GAMETIC+1
        sbc dg_stop+1
        lda G_GAMETIC+2
        sbc dg_stop+2
        lda G_GAMETIC+3
        sbc dg_stop+3
        jcs drv_end
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_TIC
        sta PHASE
.endif
.endif
        jsr call_ticker
:       cmp #GT_LOAD
        bne :+
        jsr load
        jsr call_resume
        bra :-
:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_EXIT
        sta PHASE
.endif
.endif
        inc G_GAMETIC           ; gametic + 1 (upstream's runTic after
        bne :+                  ;   G_Ticker, d_main65.s:248-251; found at
        inc G_GAMETIC+1         ;   the final integration: the driver
        bne :+                  ;   never raised it)
        inc G_GAMETIC+2
        bne :+
        inc G_GAMETIC+3
:
.ifdef TICLEVEL
        jsr wi_disp
.endif
        jsr frame
        bra lockstep

.ifdef TICLEVEL
; wi_disp: the display's one write to the game state in the intermission:
; upstream's WI_Drawer sets snl_pointeron in NoState (wi_stuff65.s:589-
; 591), at every display while the 10 tics of NoState last; the lockstep
; runs no display (milestone 11's), so after a tic that leaves the
; intermission in NoState it is set as a display would (the final
; integration: the tour's E1M2 start differed in it)
wi_disp:
        lda G_GAMESTATE
        cmp #UC_GS_INTERMISSION
        bne :+
        lda G_GAMESTATE+1
        bne :+
        lda WI_STATE+1          ; NoState: -1
        bpl :+
        lda #1
        sta WI_SNLPTR
        stz WI_SNLPTR+1
:       rts
.endif

; frame: the schedule's frames whose gametic is G_GAMETIC, each in turn
; (GTEST GT_SCHEDULE: 3 bytes a frame, the gametic's low word and the
; kind: FRAME_FRONT, FRAME_FULL, or FRAME_FULL + 1, a full frame with the
; snapshot points drv_fmend and drv_fend; a kind 0 ends the list)
frame:  jsr frame_one
        bcs frame
        rts
; frame_one: the next frame of the schedule if its gametic is G_GAMETIC
; (C set: one ran)
frame_one:
        lda dg_sched            ; FA_SRC = GT_SCHEDULE + 3 k
        sta GO_T
        lda dg_sched+1
        sta GO_T+1
        asl GO_T
        rol GO_T+1
        clc
        lda GO_T
        adc dg_sched
        sta FA_SRC
        lda GO_T+1
        adc dg_sched+1
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<GT_SCHEDULE
        sta FA_SRC
        lda FA_SRC+1
        adc #>GT_SCHEDULE
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        lda #<dg_fr
        sta FA_DST
        lda #>dg_fr
        sta FA_DST+1
        lda #3
        sta FA_N
        jsr far_get
        lda dg_fr+2
        beq frame_none          ; (no more frames)
        lda dg_fr
        cmp G_GAMETIC
        bne frame_none
        lda dg_fr+1
        cmp G_GAMETIC+1
        bne frame_none
        inc dg_sched
        bne :+
        inc dg_sched+1
:
.ifdef TICLEVEL
        lda dg_fr+2             ; the kind, and the display's view top:
        and #FRAME_KIND         ;   the message strip's rows or none (a
        sta dg_fkind            ;   render input of the display, milestone
        lda #$FF                ;   11's, from the reference's frame)
        bit dg_fr+2
        bpl :+
        lda #VIEW_STRIPTOP
:       sta VIEWTOP
.endif
        jsr go_flush
        jsr planes_out
        jsr ri_make
.ifdef TICLEVEL
        lda W_FSG               ; the display's (milestone 11's D_Display,
        sta W_FSW               ;   d_main65.s:377-381): the old fill
        stz W_FSG               ;   spans need the view shown
.endif
        jsr call_frame
.ifdef TICLEVEL
        lda dg_wipe             ; the screen shows this view, but the
        bne :+                  ;   first frame after a load (a wipe:
        lda #1                  ;   d_main65.s:521-523, g_game65.s:645)
        sta W_FSG
:       stz dg_wipe
.endif
drv_frame:                      ; (the frame's end: a snapshot point)
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_EXIT        ; (the renderer marked its own phases)
        sta PHASE
.endif
.endif
        jsr core_in
        jsr go_reset            ; the caches' tags (main $1980) were the
        jsr planes_in           ;   renderer's DSX1, DSX2 (found at the
        sec                     ;   final integration: milestone 11's
        rts                     ;   K_TIC does the same, dl_brain.s)
frame_none:
        clc
        rts

; call_frame: the frame of kind dg_fkind through the renderer's entries
; in the descriptor (dg_frame 0: none linked, a stop): the front end's
; window (dg_fwl: far_wload) and nr_frame (dg_frame); for a full frame
; the masked phase's image (dg_fml: far_mload), nm_masked (dg_fmm),
; nm_bkload (dg_fbl) and the replay nb_frame (dg_fnb). Kind FRAME_FULL + 1
; passes the snapshot points drv_fmend (the masked phase's end: its
; records) and drv_fend (after the replay: the screen)
call_frame:
        lda dg_frame
        ora dg_frame+1
        bne :+
        lda #GS_DRIVER          ; (a frame and no renderer linked)
        jmp g_stop
.ifdef TICLEVEL
:       ldx #dg_fwl - dg_fwl
        jsr call_desc
        ldx #dg_frame - dg_fwl
        jsr call_desc
        lda dg_fkind
        cmp #FRAME_FULL
        bcc @rts
        ldx #dg_fml - dg_fwl
        jsr call_desc
        ldx #dg_fmm - dg_fwl
        jsr call_desc
        lda dg_fkind
        cmp #FRAME_FULL + 1
        bne :+
        jsr drv_fmend
:       ldx #dg_fbl - dg_fwl
        jsr call_desc
        ldx #dg_fnb - dg_fwl
        jsr call_desc
        lda dg_fkind
        cmp #FRAME_FULL + 1
        bne @rts
        jsr drv_fend
@rts:   rts
drv_fmend:                      ; (snapshot points: the harness's events)
        rts
drv_fend:
        rts
; call_desc: the entry at dg_fwl + X (A, X, Y 0)
call_desc:
        lda dg_fwl,x
        sta FC_T
        lda dg_fwl+1,x
        sta FC_T+1
        lda #0
        tax
        tay
        jmp (FC_T)
.else
:       lda dg_frame
        sta FC_T
        lda dg_frame+1
        sta FC_T+1
        jmp (FC_T)
.endif

; ri_make: the render inputs from the game state (as tools/native/
; framestate.py injects them from upstream's, RENDER-MASKED.md 2.3): the
; player's mobj's x, y and angle; viewz, extralight, fixedcolormap; each
; psprite's sprite and frame (its state's; none: $FF, $FFFF), sx, sy and
; PSPF; the player's sector light; the invisibility power
ri_make:
        lda G_PLAYER + PL_MO
        ldx G_PLAYER + PL_MO + 1
        jsr rth_get             ; LW_MOB's RTHING part: x, y, angle
        ldx #3
:       lda LW_MOB + TH_X,x
        sta PL_X,x
        lda LW_MOB + TH_Y,x
        sta PL_Y,x
        lda G_PLAYER + PL_VIEWZ_G,x
        sta PL_VIEWZ,x
        dex
        bpl :-
        lda LW_MOB + TH_ANGLO
        sta PL_ANGLE
        lda LW_MOB + TH_ANGLO + 1
        sta PL_ANGLE+1
        lda LW_MOB + TH_ANG
        sta PL_ANGLE+2
        lda LW_MOB + TH_ANG + 1
        sta PL_ANGLE+3
        ldx #1
:       lda G_PLAYER + PL_EXTRALIGHT,x
        sta PL_XLIGHT,x
        lda G_PLAYER + PL_FIXEDCOLORMAP,x
        sta PL_FIXCM,x
        lda G_PLAYER + PL_POWERS_0 + 2 * UC_PW_INVISIBILITY,x
        sta PL_INVIS,x
        dex
        bpl :-
        stz PSPF
        ldx #0                  ; psprite 0, then 1
        jsr ri_psp
        ldx #PL_PSPRITES_1_STATE - PL_PSPRITES_0_STATE
        jsr ri_psp
        ; the player's sector light: its subsector's sector (LVMAP)
        lda G_PLAYER + PL_MO
        ldx G_PLAYER + PL_MO + 1
        jsr rth_get
        lda LW_MOB + MO_SIZE + MA_SUBSEC
        sta FA_SRC
        lda LW_MOB + MO_SIZE + MA_SUBSEC + 1
        asl FA_SRC
        rol a
        asl FA_SRC
        rol a
        sta FA_SRC+1
        clc
        lda FA_SRC
        adc #<(SUBBASE + SUB_SECTOR)
        sta FA_SRC
        lda FA_SRC+1
        adc #>(SUBBASE + SUB_SECTOR)
        sta FA_SRC+1
        lda #LVMAP
        sta FA_BANK
        lda #<dg_fr
        sta FA_DST
        lda #>dg_fr
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        lda dg_fr               ; SECBASE + 16 s + SEC_LIGHT
        stz FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        asl a
        rol FA_SRC+1
        clc
        adc #<(SECBASE + SEC_LIGHT)
        sta FA_SRC
        lda FA_SRC+1
        adc #>(SECBASE + SEC_LIGHT)
        sta FA_SRC+1
        lda #<PL_SECLIGHT
        sta FA_DST
        lda #>PL_SECLIGHT
        sta FA_DST+1
        jmp far_get

; ri_psp: psprite X (its offset in the player: 0 or 10): PSPn_*, PSPF
ri_psp: stx GO_J
        lda G_PLAYER + PL_PSPRITES_0_STATE,x
        sta GO_T
        lda G_PLAYER + PL_PSPRITES_0_STATE + 1,x
        sta GO_T+1
        and GO_T
        cmp #$FF
        bne @state
        lda #$FF                ; none
        sta dg_spr
        sta dg_frm
        sta dg_frm+1
        bra @put
@state: lda GO_T
        ldx GO_T+1
        jsr state_at            ; LW_STATE
        lda LW_STATE + U_ST_SPRITE
        sta dg_spr
        lda LW_STATE + U_ST_FRAME
        sta dg_frm
        lda LW_STATE + U_ST_FRAME + 1
        sta dg_frm+1
        lda GO_J                ; PSPF: bit 0 psprite 0, bit 1 psprite 1
        beq :+
        lda #2
        bra @bit
:       lda #1
@bit:   ora PSPF
        sta PSPF
@put:   ldx GO_J
        ldy #0
        cpx #0
        beq :+
        ldy #PSP1_SPR - PSP0_SPR
:       lda dg_spr
        sta PSP0_SPR,y
        lda dg_frm
        sta PSP0_FRAME,y
        lda dg_frm+1
        sta PSP0_FRAME+1,y
        lda G_PLAYER + PL_PSPRITES_0_SX,x
        sta PSP0_SX,y
        lda G_PLAYER + PL_PSPRITES_0_SX + 1,x
        sta PSP0_SX+1,y
        lda G_PLAYER + PL_PSPRITES_0_SY,x
        sta PSP0_SY,y
        lda G_PLAYER + PL_PSPRITES_0_SY + 1,x
        sta PSP0_SY+1,y
        lda G_PLAYER + PL_PSPRITES_0_SY + 2,x
        sta PSP0_SY+2,y
        lda G_PLAYER + PL_PSPRITES_0_SY + 3,x
        sta PSP0_SY+3,y
        rts
        .assert PSP1_SPR - PSP0_SPR = PSP1_SY - PSP0_SY, error, "the psprite inputs"

; rth_get: LW_MOB's RTHING and group A = slot A:X's (RTH, MOBJA), far
rth_get:
        sta GO_P
        stx GO_P+1
        asl GO_P                ; 24 s
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        lda GO_P
        sta GO_T
        lda GO_P+1
        sta GO_T+1
        asl GO_P
        rol GO_P+1
        clc
        lda GO_P
        adc GO_T
        sta GO_P
        lda GO_P+1
        adc GO_T+1
        sta GO_P+1
        clc
        lda GO_P
        adc #<RTHBASE
        sta FA_SRC
        lda GO_P+1
        adc #>RTHBASE
        sta FA_SRC+1
        lda #RTH
        sta FA_BANK
        lda #<LW_MOB
        sta FA_DST
        lda #>LW_MOB
        sta FA_DST+1
        lda #MO_SIZE
        sta FA_N
        jsr far_get
        lda #MOBJA
        sta FA_BANK
        lda #<(LW_MOB + MO_SIZE)
        sta FA_DST
        lda #>(LW_MOB + MO_SIZE)
        sta FA_DST+1
        jmp far_get

; ---------------------------------------------------------------------------
; The load protocol
; ---------------------------------------------------------------------------
load:
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_LOAD        ; the load (its own image in W: no PC map)
        sta PHASE
.endif
.endif
        jsr go_flush
        jsr planes_out
        lda #<dg_lcode
        ldx #>dg_lcode
        ldy #LCODE
        jsr far_pload
        lda dg_nlsetup
        sta FC_T
        lda dg_nlsetup+1
        sta FC_T+1
        lda G_GAMEMAP
        jsr load_setup
drv_loaded:                     ; (a snapshot point after nl_setup)
        inc dg_loads
.ifdef TICLEVEL
        lda #1                  ; (the next frame is a wipe's)
        sta dg_wipe
.endif
.ifdef TESTBUILD
        jsr rekey
.endif
.ifdef TICLEVEL
        jsr levfields
.endif
        jsr core_in
.ifdef TESTBUILD                ; (a test build's harness: the timing)
.ifdef GPROF
        lda #2 * PH_TIC
        sta PHASE
.endif
.endif
        jmp planes_in
load_setup:
        jmp (FC_T)

.ifdef TESTBUILD
; rekey: the setup's re-key record (GTEST GT_REKEYS + dg_rekey records):
; its map (a check), CS_PREV1, CS_PREV2, then the hint's low and high
; planes by pool slot (POOL_MAX each) into MOBJP's HINTL, HINTH
rekey:  lda dg_rekey            ; FA_SRC = GT_REKEYS + REKEY_RECORD k
        sta GO_I
        lda #<GT_REKEYS
        sta FA_SRC
        lda #>GT_REKEYS
        sta FA_SRC+1
:       lda GO_I
        beq :+
        clc
        lda FA_SRC
        adc #<REKEY_RECORD
        sta FA_SRC
        lda FA_SRC+1
        adc #>REKEY_RECORD
        sta FA_SRC+1
        dec GO_I
        bra :-
:       inc dg_rekey
        lda #GTEST
        sta FA_BANK
        lda #<dg_fr
        sta FA_DST
        lda #>dg_fr
        sta FA_DST+1
        lda #6
        sta FA_N
        jsr far_get
        lda dg_fr               ; the map: 0 means no record (nothing)
        bne :+
        rts
:       cmp G_GAMEMAP
        beq :+
        lda #GS_STREAM          ; (a record of another map)
        jmp g_stop
:       ldx #3
:       lda dg_fr+1,x
        sta CS_PREV1,x
        dex
        bpl :-
        .assert CS_PREV2 = CS_PREV1 + 2, error, "CS_PREV1, CS_PREV2"
        ; the hint planes: 2 x POOL_MAX bytes, through BL_BUF a page at a
        ; time
        clc
        lda FA_SRC
        adc #6
        sta GO_T
        lda FA_SRC+1
        adc #0
        sta GO_T+1
        lda #<PL_HINTL
        sta GO_P
        lda #>PL_HINTL
        sta GO_P+1
        ldy #0                  ; the pages: 2 a plane
@page:  phy
        lda #GTEST
        sta FA_BANK
        lda GO_T
        sta FA_SRC
        lda GO_T+1
        sta FA_SRC+1
        lda #<BL_BUF
        sta FA_DST
        lda #>BL_BUF
        sta FA_DST+1
        stz FA_N
        jsr far_get
        lda #MOBJP
        sta FA_BANK
        lda #<BL_BUF
        sta FA_SRC
        lda #>BL_BUF
        sta FA_SRC+1
        lda GO_P
        sta FA_DST
        lda GO_P+1
        sta FA_DST+1
        jsr far_put
        inc GO_T+1
        inc GO_P+1
        ply
        iny
        cpy #2
        bne :+
        lda #>PL_HINTH          ; the high plane
        sta GO_P+1
:       cpy #4
        bne @page
        rts
        .assert POOL_MAX = 512, error, "two pages of hints a plane"
        .assert <PL_HINTL = 0 && <PL_HINTH = 0, error, "hint pages"

.ifdef TICLEVEL
; levfields: in a run with frames (dg_frame not 0), the frame block's level
; fields of the map just loaded (GTEST GT_LEVELS, GT_LEVEL_RECORD bytes a
; map from E1M1: NUMNODES, NVERT, SKYBANK/SKYLO/SKYHI, the map's header in
; the store, which the harness reads there as milestone 11's s_level does)
levfields:
        lda dg_frame
        ora dg_frame+1
        bne :+
        rts
:       lda G_GAMEMAP           ; FA_SRC = GT_LEVELS + 7 (map - 1)
        dec a
        sta GO_T
        asl a
        asl a
        asl a
        sec
        sbc GO_T
        clc
        adc #<GT_LEVELS
        sta FA_SRC
        lda #>GT_LEVELS
        adc #0
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        lda #<dg_fr
        sta FA_DST
        lda #>dg_fr
        sta FA_DST+1
        lda #GT_LEVEL_RECORD
        sta FA_N
        jsr far_get
        lda dg_fr
        sta NUMNODES
        lda dg_fr+1
        sta NUMNODES+1
        lda dg_fr+2
        sta NVERT
        lda dg_fr+3
        sta NVERT+1
        ldx #2
:       lda dg_fr+4,x
        sta SKYBANK,x
        dex
        bpl :-
        rts
        .assert GT_LEVEL_RECORD = 7, error, "the level fields' record"

; stream: in a run on a stream of commands (dg_strm, the next record's
; place in GTEST: 0, none, a demo's), the record of this tic (src/native/
; game/README.md, "The tic level"): its gametic's low word (a check), its
; command into the ring's entry of gametic (G_CMDS + 8 (gametic & 7), as
; upstream's buildNewTiccmds left it for G_Ticker), then its events in
; turn: a cheat (EV_CHEAT: C_Responder of its number), a poke of main
; (EV_POKE: address, size, value), the menu's state (EV_MENU), the menu's
; new game (EV_INITNEW: G_DeferedInitNew of its skill), each before the
; tic as upstream's D_ProcessEvents makes them before G_Ticker
EV_CHEAT   = 1
EV_POKE    = 2
EV_MENU    = 3
EV_INITNEW = 4
STREAM_HEAD = 11                ; tic 2, command 8, events' count 1
FC_HERE .set 0
stream: lda dg_scnt             ; (none, or none left: no command)
        ora dg_scnt+1
        bne :+
        rts
:       lda dg_scnt
        bne :+
        dec dg_scnt+1
:       dec dg_scnt
        lda #<dg_sbuf
        ldx #STREAM_HEAD
        jsr st_get
        lda dg_sbuf             ; the record of this tic
        cmp G_GAMETIC
        jne st_bad
        lda dg_sbuf+1
        cmp G_GAMETIC+1
        jne st_bad
        lda G_GAMETIC           ; its command into the ring
        and #7
        asl a
        asl a
        asl a
        tax
        ldy #0
:       lda dg_sbuf+2,y
        sta G_CMDS,x
        inx
        iny
        cpy #8
        bne :-
        lda #STREAM_HEAD
        jsr st_skip
        lda dg_sbuf+10
        sta dg_sev
@ev:    lda dg_sev
        bne :+
        rts
:       dec dg_sev
        lda #<dg_ebuf           ; kind, length, up to 8 bytes
        ldx #10
        jsr st_get
        lda dg_ebuf+1
        cmp #9
        jcs st_bad
        clc
        adc #2
        jsr st_skip
        lda dg_ebuf
        cmp #EV_CHEAT
        bne :+
        lda dg_ebuf+2
        FCALL C_Responder
        bra @ev
:       cmp #EV_POKE
        bne @menu
        lda dg_ebuf+2           ; the address, the size, the value
        sta GO_P
        lda dg_ebuf+3
        sta GO_P+1
        ldy #0
:       lda dg_ebuf+5,y
        sta (GO_P),y
        iny
        cpy dg_ebuf+4
        bne :-
        bra @ev
@menu:  cmp #EV_MENU
        bne :+
        lda dg_ebuf+2
        sta G_MENUACTIVE
        stz G_MENUACTIVE+1
        lda dg_ebuf+3
        sta G_SHOWMSG
        stz G_SHOWMSG+1
        bra @ev
:       cmp #EV_INITNEW
        bne st_bad
        lda dg_ebuf+2
        ldx #0
        FCALL G_DeferedInitNew
        bra @ev
st_bad: lda #GS_STREAM
        jmp g_stop
; st_get: X bytes of the stream at dg_strm into the card's A (low byte of
; a DESC address)
st_get: sta FA_DST
        lda #>dg_sbuf
        sta FA_DST+1
        stx FA_N
        lda dg_strm
        sta FA_SRC
        lda dg_strm+1
        sta FA_SRC+1
        lda #GTEST
        sta FA_BANK
        jmp far_get
        .assert >dg_sbuf = >dg_ebuf, error, "the stream's buffers"
; st_skip: dg_strm + A
st_skip:
        clc
        adc dg_strm
        sta dg_strm
        bcc :+
        inc dg_strm+1
:       rts
.endif
.endif

; ---------------------------------------------------------------------------
; The images and the planes
; ---------------------------------------------------------------------------
; core_in: the tic image back into W. W was another image's (the load
; image's, the renderer's), which wrote the slots: they hold no group, as
; milestone 11's kernel says at its tic (dl_kern.s); found at wave 6's
; integration: after a load G_Ticker's action loop (g_tresume, fc_call)
; ran the load image's bytes in slot 2 when SLOT_GRP still named its group.
; SLOT_NEED too (gcall.s's lazy restore): no FCALL frame is active here, and
; the renderer's scratch overlays the runtime's state
core_in:
        lda #$FF
        sta SLOT_GRP
        sta SLOT_GRP+1
        sta SLOT_GRP+2
        sta SLOT_NEED
        sta SLOT_NEED+1
        lda #<dg_core
        ldx #>dg_core
        ldy #GCODE0
        jmp far_pload
planes_in:
        lda #<dg_planes
        ldx #>dg_planes
        ldy #MOBJP
        jmp far_pload
; far_gcopy: gr_load's copy of a group (gcall.s) in the test builds: FA_N
; pages (1-255) of bank FA_BANK from FA_SRC + Y to main FA_DST + Y, both
; pointers with the same low byte, the first page from byte Y (Y even; as
; the play kernel's), through far_get a page at a time, the pages counted
; in FC_PS (as gr_load's own loop was: the parts' write checks allow
; far_get's stores into the slots). It overrides game.cfg's weak
; far_gcopy, the play kernel's one read window (dl_kern.s), which a test
; image does not link (part ticloads' request 3, speed wave 2 as
; integrated). Changes A, Y, FA_SRC, FA_DST, FA_N, FC_PS.
far_gcopy:
        lda FA_N
        sta FC_PS
        tya
        beq @whole
        jsr gc_add              ; both pointers on by Y
        tya
        eor #$FF
        inc a
        sta FA_N                ; the first page's 256 - Y bytes
        jsr far_get
        lda FA_N
        jsr gc_add              ; on past them
        dec FC_PS
        beq @done
@whole: stz FA_N                ; (256)
:       jsr far_get
        inc FA_SRC+1
        inc FA_DST+1
        dec FC_PS
        bne :-
@done:  rts
gc_add: pha                     ; FA_SRC and FA_DST on by A
        clc
        adc FA_SRC
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       pla
        clc
        adc FA_DST
        sta FA_DST
        bcc :+
        inc FA_DST+1
:       rts
; planes_out: W's planes back to MOBJP (a page at a time, far_put)
planes_out:
        lda #MOBJP
        sta FA_BANK
        stz FA_SRC
        stz FA_DST
        stz FA_N
        lda #>PL_TNL
:       sta FA_SRC+1
        sta FA_DST+1
        jsr far_put
        lda FA_SRC+1
        inc a
        cmp #>(PL_TICS + PLANE_SLOTS)
        bne :-
        rts

; drv_irq: the mouse card's VBL, acknowledged and counted; a BRK (the B
; bit of the pushed P) goes to drv_crash
drv_irq:
        pha
        phx
        tsx
        lda $0103,x
        and #$10
        bne @brk
        lda #3
        sta MOUSE_ACK
        inc IRQCNT
        bne :+
        inc IRQCNT+1
:       plx
        pla
        rti
@brk:   jmp drv_crash

        .segment "DESC"
; the page runs (far_pload's lists: near in the window, in the card; a
; list must not cross a page, as far_pload steps its low byte only: first
; in the descriptor, and asserted, since speed wave 2's integration grew
; the driver and put dg_planes at $EAFF in part xymove's image)
dg_core:   .res 8               ; the tic image from GCODE0
dg_planes: .res 4               ; the planes from MOBJP
dg_lcode:  .res 8               ; the load image from LCODE
        .assert >dg_core = >(dg_core + 7) && >dg_planes = >(dg_planes + 3) && >dg_lcode = >(dg_lcode + 7), lderror, "a far_pload list crosses a page"
dg_mode:   .res 1               ; DM_*
dg_entry:  .res 2               ; the routine (DM_ROUTINE*)
dg_grp:    .res 1               ; its group (0: the core)
dg_a:      .res 1               ; its registers
dg_x:      .res 1
dg_y:      .res 1
dg_p:      .res 1
dg_ra:     .res 1               ; at its return
dg_rx:     .res 1
dg_ry:     .res 1
dg_rp:     .res 1
dg_ticker: .res 2               ; G_Ticker's entry (lockstep)
dg_resume: .res 2               ; g_resume's entry (the load protocol)
dg_nlsetup: .res 2              ; the load image's nl_setup
.ifdef TICLEVEL
; the renderer's entries (the harness's, from the render build it links:
; call_frame), in this order
dg_fwl:    .res 2               ; far_wload: the front end's window
dg_frame:  .res 2               ; nr_frame (0: no renderer linked)
dg_fml:    .res 2               ; far_mload: the masked phase's image
dg_fmm:    .res 2               ; nm_masked
dg_fbl:    .res 2               ; nm_bkload
dg_fnb:    .res 2               ; nb_frame: the bucket pass and the replay
dg_fkind:  .res 1               ; the frame's kind (FRAME_*)
dg_wipe:   .res 1               ; a load since the last frame (a wipe)
dg_nosnap: .res 1               ; no flush and snapshot a tic (timing)
dg_strm:   .res 2               ; the stream's next record
dg_scnt:   .res 2               ; its records left (0: none, a demo's)
dg_sev:    .res 1               ; its events left
dg_sbuf:   .res 11              ; a record's head
dg_ebuf:   .res 10              ; an event
.else
dg_frame:  .res 2               ; the frame's entry (0: none linked)
.endif
dg_stop:   .res 4               ; the gametic that ends a lockstep run
dg_rekey:  .res 1               ; the next re-key record
dg_sched:  .res 2               ; the next frame of the schedule
dg_tcount: .res 2               ; I_GetTime's values in GTEST
dg_loads:  .res 1               ; the loads made
dg_fr:     .res 8               ; a frame's record, a re-key's head
dg_spr:    .res 1
dg_frm:    .res 2
