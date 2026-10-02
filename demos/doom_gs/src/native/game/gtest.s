; game/gtest.s: the skeleton's own checks on hand-made data (milestone 10,
; docs/GAME.md 3.9, S5), in the skeleton's test image (make -f game.mk
; skel) only. GPL-2, the port's own. Each gt_t_* routine runs in the
; driver's routine mode (gdriver.s DM_ROUTINE) and appends what it finds to
; gt_res (gt_ri bytes), which tests/test_native_game_skeleton.py reads in
; the snapshot at drv_done:
;
;   gt_t_api     the object API: the mobj cache's LRU (slots 0-7 got, then
;                0-3 again, then 8 and 9: the four most recently got stay,
;                4 and 5 go); write-back (a dirty group reaches its bank on
;                eviction, an undirtied change does not); the counters; the
;                sector cache's two records; the line cache's two sectors
;                (LVS) and its record's write-back; the special cache's
;                store, eviction and its LRU (five lines: the four most
;                recently got hit again)
;   gt_t_spawn   a spawn into a slot whose cached line is dirty from a
;                removal (docs/GAME.md 3.9 S5, review 2): the spawned record
;                and its planes survive the later eviction
;   gt_t_fcall   FCALL in its own slot, slot 1 -> core -> slot 1, slot 1 ->
;                slot 2 -> slot 1 (review 1): each routine of the test
;                groups appends a marker and the group slot 1 holds
;   gt_t_planes  pl_get of slot 5, pl_put of slot 6 (the driver's planes in
;                and out around the call)
;   gt_t_free    the zone's free list (a full pool: zone slots, one freed
;                and taken again; a CS_PREV naming it becomes stale and
;                GT_ZPREV is raised) and a kind's special free list
;   gt_t_unb     an FCALL of a routine whose part is not built (GS_UNBUILT)
;   gt_t_dcall   DCALL of table dg_a's entry dg_x (1 ACTTAB .. 5 LSTAB):
;                the unbuilt stop GS_UNBUILTD
;   gt_tstub, gt_rstub
;                a stub G_Ticker and a stub continuation for the load
;                protocol (lockstep mode): the first tic starts the load of
;                action gt_act (G_LOADACT, gameaction), the continuation
;                does that action's tail (GAME.md 3.4: GA_LOADLEVEL,
;                GA_NEWGAME, GA_PLAYDEMO, GA_WORLDDONE), counts itself
;                (gt_cont) and re-enters the action loop (gt_reent); the
;                driver then raises gametic (the final integration: the
;                lockstep driver raises it after each tic, as upstream's
;                runTic; the stub raised it before)

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
        .include "ggame.inc"
        .include "gplace.inc"

        .export gt_t_api, gt_t_spawn, gt_t_fcall, gt_t_planes, gt_t_free
        .export gt_t_unb, gt_t_dcall, gt_tstub, gt_rstub
        .export gt_res, gt_ri, gt_act, gt_cont, gt_reent, gt_tphase
        .export gt_fa, gt_fa2, gt_fc, gt_fd, gt_fcore, gt_fb
        .import mo_get, mo_dirty, mo_tagged, sec_get, sec_dirty, ln_get
        .import ln_dirty, sp_get, sp_store, pl_get, pl_put, g_get
        .import gt_mosave, mo_free, gt_pooltake, gt_zfree, gt_spectake
        .import gt_spfree, fc_call, fc_unbuilt, dc_call
        .import ACTTAB, THTAB, ITTAB, TRVTAB, LSTAB
        .import Z_CheckHeap, ST_Start, HU_Start, I_GetTime, g_stop

PLR     = G_PLAYER

        .segment "LOADW"

; put: A appended to gt_res
put:    phx
        ldx gt_ri
        sta gt_res,x
        inc gt_ri
        plx
        rts

; far1: A = the byte of bank Y at GO_P (one far read, through gt_tmp)
far1:   sty FA_BANK
        lda GO_P
        sta FA_SRC
        lda GO_P+1
        sta FA_SRC+1
        lda #<gt_tmp
        ldx #>gt_tmp
        ldy #1
        jsr g_get
        lda gt_tmp
        rts

; moget: mo_get of slot A (below 256)
moget:  ldx #0
        jmp mo_get

; ===========================================================================
; gt_t_api
; ===========================================================================
gt_t_api:
        ; the LRU: 0-7, then 0-3 again, then 8 and 9
        ldy #0
:       phy
        tya
        jsr moget
        ply
        iny
        cpy #8
        bne :-
        ldy #0
:       phy
        tya
        jsr moget
        ply
        iny
        cpy #4
        bne :-
        lda #8
        jsr moget
        lda #9
        jsr moget
        ldy #0                  ; each of 0-9 cached: 1, else 0
:       phy
        tya
        ldx #0
        jsr mo_tagged
        lda #0
        rol a
        jsr put
        ply
        iny
        cpy #10
        bne :-
        ; write-back: slot 20's type dirty, slot 30's health not
        lda #20
        jsr moget
        ldy #MO_SIZE + MA_TYPE
        lda #$42
        sta (GC_MP),y
        lda #2
        jsr mo_dirty
        lda #30
        jsr moget
        ldy #MO_SIZE + MA_HEALTH
        lda #$99
        sta (GC_MP),y
        ldy #40                 ; eight others: both evicted
:       phy
        tya
        jsr moget
        ply
        iny
        cpy #48
        bne :-
        lda #20                 ; MOBJA: slot 20's type, slot 30's health
        jsr mo_far
        clc
        lda GO_P
        adc #MA_TYPE
        sta GO_P
        bcc :+
        inc GO_P+1
:       ldy #MOBJA
        jsr far1
        jsr put
        lda #30
        jsr mo_far
        clc
        lda GO_P
        adc #MA_HEALTH
        sta GO_P
        bcc :+
        inc GO_P+1
:       ldy #MOBJA
        jsr far1
        jsr put
        lda GO_HITS             ; the counters
        jsr put
        lda GO_MISS
        jsr put
        lda GO_WBACK
        jsr put
        ; the sectors: 3's light (render), 4's tag (game), evicted
        lda #3
        jsr sec_get
        ldy #SEC_LIGHT
        lda #$C3
        sta (GC_SP),y
        lda #1
        jsr sec_dirty
        lda #4
        jsr sec_get
        ldy #SEC_SIZE + SG_TAG
        lda #$D4
        sta (GC_SP),y
        lda #2
        jsr sec_dirty
        ldy #10
:       phy
        tya
        jsr sec_get
        ply
        iny
        cpy #18
        bne :-
        lda #<(SECBASE + 3 * SEC_SIZE + SEC_LIGHT)
        sta GO_P
        lda #>(SECBASE + 3 * SEC_SIZE + SEC_LIGHT)
        sta GO_P+1
        ldy #LVMAP
        jsr far1
        jsr put
        lda #<(SECG_BASE + 4 * SECG_SIZE + SG_TAG)
        sta GO_P
        lda #>(SECG_BASE + 4 * SECG_SIZE + SG_TAG)
        sta GO_P+1
        ldy #LVG1
        jsr far1
        jsr put
        ; the lines: 5's two sectors, its stamp written back
        lda #5
        ldx #0
        jsr ln_get
        ldy #LINE_SIZE
        lda (GC_LP),y
        jsr put
        iny
        lda (GC_LP),y
        jsr put
        ldy #LN_VALID
        lda #$34
        sta (GC_LP),y
        iny
        lda #$12
        sta (GC_LP),y
        jsr ln_dirty
        ldy #100
:       phy
        tya
        ldx #0
        jsr ln_get
        ply
        iny
        cpy #108
        bne :-
        lda #<(LINE_BASE + 5 * LINE_SIZE + LN_VALID)
        sta GO_P
        lda #>(LINE_BASE + 5 * LINE_SIZE + LN_VALID)
        sta GO_P+1
        ldy #LVG0
        jsr far1
        jsr put
        inc GO_P
        ldy #LVG0
        jsr far1
        jsr put
        ; the specials: special 3 stored, five others got (it is
        ; evicted), its byte 7 back in ZONE0
        ldy #SPEC_SIZE - 1
:       tya
        ora #$80
        sta LW_SPEC,y
        dey
        bpl :-
        lda #<(SPEC_HANDLE + 3)
        sta GC_H
        lda #>(SPEC_HANDLE + 3)
        sta GC_H+1
        jsr sp_store
        ldy #10
:       phy
        tya
        ldx #>SPEC_HANDLE
        jsr sp_get
        ply
        iny
        cpy #15
        bne :-
        lda #<(SPEC_BASE + 3 * SPEC_SIZE + 7)
        sta GO_P
        lda #>(SPEC_BASE + 3 * SPEC_SIZE + 7)
        sta GO_P+1
        ldy #ZONE0
        jsr far1
        jsr put
        ; the special cache's LRU: 10-14 cached; 10-13 again; 15; then
        ; 10-13 are hits (4 more) and 14 a miss
        ldy #10
:       phy
        tya
        ldx #>SPEC_HANDLE
        jsr sp_get
        ply
        iny
        cpy #14
        bne :-
        lda #15
        ldx #>SPEC_HANDLE
        jsr sp_get
        lda GO_HITS
        sta gt_tmp
        lda GO_MISS
        sta gt_tmp+1
        ldy #10
:       phy
        tya
        ldx #>SPEC_HANDLE
        jsr sp_get
        ply
        iny
        cpy #15
        bne :-
        sec
        lda GO_HITS
        sbc gt_tmp
        jsr put                 ; (4)
        sec
        lda GO_MISS
        sbc gt_tmp+1
        jmp put                 ; (1)
        .assert <(SPEC_HANDLE + 15) = 15, error, "the specials' handles"

; mo_far: GO_P = slot A's record address (RTHBASE + 24 A)
mo_far: sta GO_P
        stz GO_P+1
        asl GO_P                ; 8 slot
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        asl GO_P
        rol GO_P+1
        lda GO_P
        sta gt_tmp
        lda GO_P+1
        sta gt_tmp+1
        asl GO_P                ; + 16 slot
        rol GO_P+1
        clc
        lda GO_P
        adc gt_tmp
        sta GO_P
        lda GO_P+1
        adc gt_tmp+1
        sta GO_P+1
        clc
        lda GO_P
        adc #<RTHBASE
        sta GO_P
        lda GO_P+1
        adc #>RTHBASE
        sta GO_P+1
        rts

; ===========================================================================
; gt_t_spawn: slot 7's line dirty (a removal), then a spawn into slot 7
; ===========================================================================
gt_t_spawn:
        lda #7
        jsr moget
        ldy #MO_SIZE + MA_TYPE
        lda #$33
        sta (GC_MP),y
        lda #$0F
        jsr mo_dirty
        jsr mo_free             ; the spawned mobj: type $55, FN_MOBJ, tics 5
        lda #$55
        sta LW_MOB + MO_SIZE + MA_TYPE
        lda #FN_MOBJ
        sta LW_MOB + MO_XFUNC
        lda #5
        sta LW_MOB + MO_XTICS
        lda #7
        sta GC_MO
        stz GC_MO+1
        jsr gt_mosave
        ldy #40                 ; eight others: slot 7 evicted
:       phy
        tya
        jsr moget
        ply
        iny
        cpy #48
        bne :-
        lda #7
        jsr mo_far
        clc
        lda GO_P
        adc #MA_TYPE
        sta GO_P
        bcc :+
        inc GO_P+1
:       ldy #MOBJA
        jsr far1
        jsr put                 ; ($55)
        lda #7
        ldx #0
        jsr pl_get
        lda PL_K
        jsr put
        lda PL_T
        jsr put
        lda PL_N
        jsr put
        lda PL_N+1
        jmp put

; ===========================================================================
; gt_t_fcall: the test groups (glayout.TEST_GROUPS: gt_fa, gt_fa2 in group
; 1 and gt_fd in group 4, slot 1; gt_fc in group 2, slot 2; gt_fcore and
; gt_fb in the core)
; ===========================================================================
gt_t_fcall:
        FCALL gt_fa
        lda #'E'
        jmp put

        ROUTINE gt_fa
        lda #'A'
        jsr mark
        FCALL gt_fa2            ; the same group: a jsr
        lda #'a'
        jsr mark
        FCALL gt_fcore          ; slot 1 -> the core -> slot 1
        lda #'b'
        jsr mark
        FCALL gt_fc             ; slot 1 -> slot 2 -> slot 1
        lda #'c'
        jmp mark

        ROUTINE gt_fa2
        lda #'2'
        jmp mark

        ROUTINE gt_fc
        lda #'C'
        jsr mark
        FCALL gt_fd             ; (its return restores slot 1's group: the
        lda #'k'                ;   carry it set comes back, 'k'; lost, 'x':
        bcs :+                  ;   wave 1 as integrated, secfind.md
        lda #'x'                ;   request 11)
:       jmp mark

        ROUTINE gt_fd
        lda #'D'
        jsr mark
        sec                     ; (a carry result)
        rts

        ROUTINE gt_fcore
        lda #'K'
        jsr mark
        FCALL gt_fd
        FCALL gt_fb
        lda #'k'
        jmp mark

        ROUTINE gt_fb
        lda #'B'
        jmp mark

        .segment "LOADW"
; mark: A and the group slot 1 holds appended (the core's: no paging)
mark:   jsr put
        lda SLOT_GRP+1
        jmp put

; ===========================================================================
; gt_t_planes
; ===========================================================================
gt_t_planes:
        lda #5
        ldx #0
        jsr pl_get
        lda PL_N
        jsr put
        lda PL_N+1
        jsr put
        lda PL_K
        jsr put
        lda PL_T
        jsr put
        lda #$23
        sta PL_N
        lda #$01
        sta PL_N+1
        lda #$0A
        sta PL_K
        lda #$07
        sta PL_T
        lda #6
        ldx #0
        jmp pl_put

; ===========================================================================
; gt_t_free: the pool full (the image's G_POOLN, G_TPBITS 0), G_ZMN 0
; ===========================================================================
gt_t_free:
        jsr gt_pooltake         ; the zone: G_POOLN, then G_POOLN + 1
        lda GC_MO
        jsr put
        lda GC_K
        jsr put
        jsr gt_pooltake
        lda GC_MO
        jsr put
        lda GC_MO               ; CS_PREV1 names it
        sta CS_PREV1
        lda GC_MO+1
        sta CS_PREV1+1
        jsr gt_zfree            ; freed: CS_PREV1 stale, GT_ZPREV
        lda CS_PREV1
        jsr put
        lda CS_PREV1+1
        jsr put
        lda GT_ZPREV
        jsr put
        lda GC_MO
        ldx GC_MO+1
        jsr pl_get
        lda PL_K
        jsr put                 ; (FN_FREE)
        jsr gt_pooltake         ; the freed one again
        lda GC_MO
        jsr put
        lda G_ZMN
        jsr put
        lda G_MOHWM
        jsr put
        ldx #SPK_DOOR           ; a door, freed, taken again
        jsr gt_spectake
        lda GC_H
        jsr put
        lda GC_H+1
        jsr put
        jsr gt_spfree
        lda G_SPFREE + 2 * SPK_DOOR
        jsr put
        ldx #SPK_DOOR
        jsr gt_spectake
        lda GC_H
        jsr put
        lda G_SPFREE + 2 * SPK_DOOR + 1
        jsr put
        lda G_SPN + 2 * SPK_DOOR
        jmp put

; ===========================================================================
; The stops
; ===========================================================================
gt_t_unb:
        FCALL P_DelSecnode      ; (mobjstate's: not built in the skeleton)
        rts

gt_t_dcall:
        txa                     ; the entry
        ldy dg_t
        cpy #1
        bne :+
        DCALL ACTTAB
        rts
:       cpy #2
        bne :+
        DCALL THTAB
        rts
:       cpy #3
        bne :+
        DCALL ITTAB
        rts
:       cpy #4
        bne :+
        DCALL TRVTAB
        rts
:       DCALL LSTAB
        rts

; ===========================================================================
; The load protocol's stubs (lockstep mode)
; ===========================================================================
gt_tstub:
        lda gt_tphase
        bne @tic
        inc gt_tphase
        lda gt_act              ; the action that starts the load
        sta G_GAMEACTION
        stz G_GAMEACTION+1
        sta G_LOADACT
        lda #GT_LOAD
        rts
@tic:   jmp gt_loop

; gt_rstub: the continuation of G_LOADACT, then the action loop again
gt_rstub:
        ; doLoadLevel's tail: gameaction 0, Z_CheckHeap, the keys up (the
        ; input's: milestone 11), ST_Start, HU_Start
        stz G_GAMEACTION
        stz G_GAMEACTION+1
        jsr Z_CheckHeap
        jsr ST_Start
        jsr HU_Start
        lda G_LOADACT
        cmp #UGA_NEWGAME
        bne :+
        stz G_GAMEACTION        ; doNewGame: gameaction 0, ST_Start
        stz G_GAMEACTION+1
        jsr ST_Start
        bra @count
:       cmp #UGA_PLAYDEMO
        bne :+
        stz PLR + PL_CHEATS     ; readDemoHeader: cheats 0; doPlayDemo:
        stz PLR + PL_CHEATS + 1 ;   gameaction 0, usergame 0,
        stz G_GAMEACTION        ;   demoplayback 1, starttime =
        stz G_GAMEACTION+1      ;   I_GetTime
        stz G_USERGAME
        stz G_USERGAME+1
        lda #1
        sta G_DEMOPLAY
        stz G_DEMOPLAY+1
        jsr I_GetTime
        ldx #3
@time:  lda GA_0,x
        sta G_STARTTIME,x
        dex
        bpl @time
        bra @count
:       cmp #UGA_WORLDDONE
        bne @count
        stz G_GAMEACTION        ; doWorldDone: gameaction 0
        stz G_GAMEACTION+1
@count: ldx G_LOADACT
        inc gt_cont,x
        inc gt_reent            ; the action loop, entered again
; gt_loop: the stub's action loop: an action left is a stop; else the
; tic (the driver raises gametic after it)
gt_loop:
        lda G_GAMEACTION
        ora G_GAMEACTION+1
        beq :+
        lda #GS_DRIVER
        jmp g_stop
:       lda #0
        rts

gt_res:   .res 96
gt_ri:    .res 1
gt_tmp:   .res 2
gt_act:   .res 1
gt_cont:  .res 9
gt_reent: .res 1
gt_tphase: .res 1
dg_t:     .res 1
        .export dg_t
