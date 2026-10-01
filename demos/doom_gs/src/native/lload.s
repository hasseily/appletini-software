; lload.s: the level load's program runner (milestone 9, stage B;
; docs/LEVELS.md 2.1, 2.2, 4.1): nl_load runs a map's load program from
; the level store in RamWorks, as tools/native/lstore.py's HostMachine
; defines it:
;
;   the store's directory at STORE_DIR_BANK:STORE_DIR (llayout.py) names
;   each map's header (its counts and blocks); the header's PROGRAM block
;   holds the steps and the memory-API requests:
;
;     VARIANTS m   the undo requests of the map LV_VARMAP names (none for
;                  0), then map m's apply requests, then LV_VARMAP = m
;                  (docs/LEVELS.md 1.4)
;     COPYREQ n,   the program's request n: its descriptors (COPY, FILL;
;     PRIVREQ n    PRIVATE for main and aux 0) fetched from the store into
;                  W and handed to the memory API's transport
;     LINES, GROUP, FLOOD, CMAPS
;                  the static steps (lgeom.s)
;     SPAWN, SPECIALS
;                  stage C's game core (gspawn.s, gspec.s): run only when
;                  the load is nl_setup's (nl_game: GS_GAME); nl_load alone
;                  loads the level's data and skips them
;     END          the end
;
; The code runs in W (the load phase's mode window, MEMORY_MAP.md 3.5),
; loaded with the phase loader (far_pload) from bank LCODE; every read of
; the store and every write to a RamWorks bank goes through the far
; layer's far_get and far_put (the card's, docs/MEMORY_MAP.md 4.2: inside
; a RAMRD or RAMWRT window only zero page, the stack and the card are
; near). The memory API's transport is here too (MEMORY_MAP.md 4.1,
; fallback 3): a request is built in W at LW_REQ and sent through slot
; 7's FIFO with interrupts masked.
;
; A stop (a store without the map, a codec other than raw, a malformed
; program, a request the API refuses, a limit of the load's scratch)
; stores its code in LV_STATUS (llayout.py LS) and executes BRK, as the
; renderer's stops do.
;
; The profiling build (-D LPROF) marks the cost phases (PHASE, 2 x n): 2
; the variants, 3 the copies, 4 LINES, 5 GROUP, 6 FLOOD, 7 CMAPS, 8 the
; PRIVATE copies, 9 SPAWN, 10 SPECIALS; the driver marks 1, the image's
; load, and 11 nl_setup's own steps.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
        .include "math.inc"
        .include "llayout.inc"

        .export nl_load, nl_game, ld_stop, ld_find, ld_block, am_send
        .import far_get, far_put
        .import lg_lines, lg_group, lg_flood, lg_cmaps
        .import gs_spawn, gx_specials
        .include "lgame.inc"

SP_DATA         = $CFF0         ; the memory API's raw FIFO transport in
SP_CTRL         = $CFF1         ;   slot 7 (appletini-one
SP_POP          = $CFF2         ;   README_MEMORY_API.md section 7)
SP_RELEASE      = $CFFF
SP_ROM          = $C700
AMEM_TIMEOUT    = $6F           ; (ours: no reply came)

.macro  MARK n
.ifdef LPROF
        lda #2 * (n)
        sta PHASE
.endif
.endmacro

        .segment "LOADW"

; ---------------------------------------------------------------------------
; nl_load: the load of map A (1-9) by its program, the level's data only
; (the game's steps skipped). nl_game: the same with the game's steps
; (nl_setup's, GS_GAME set). Change everything but the persistent state.
; ---------------------------------------------------------------------------
nl_load:
        stz GS_GAME
        bra ld_map
nl_game:
        tax
        lda #1
        sta GS_GAME
        txa
ld_map: sta LP_MAP
        jsr ld_find             ; FA_BANK:FA_SRC = the map's header
        lda #<LW_HDR
        sta FA_DST
        lda #>LW_HDR
        sta FA_DST+1
        lda #LH_SIZE
        sta FA_N
        jsr far_get
        lda LW_HDR              ; "LH", the map
        cmp #'L'
        jne @bad
        lda LW_HDR+1
        cmp #'H'
        jne @bad
        lda LW_HDR+2
        cmp LP_MAP
        jne @bad
        ldx #LB_PROGRAM         ; the program's head
        jsr ld_block
        lda FA_BANK
        sta LP_PB
        lda FA_SRC
        sta LP_P
        lda FA_SRC+1
        sta LP_P+1
        lda #<LW_STEPS
        sta FA_DST
        lda #>LW_STEPS
        sta FA_DST+1
        lda #LP_HEAD
        sta FA_N
        jsr far_get
        lda LW_STEPS            ; "LP", the map, the steps, the requests
        cmp #'L'
        jne @bad
        lda LW_STEPS+1
        cmp #'P'
        jne @bad
        lda LW_STEPS+2
        cmp LP_MAP
        jne @bad
        lda LW_STEPS+3
        sta LP_NSTEP
        jeq @bad
        cmp #LSTEP_MAX + 1
        jcs @steps
        lda LW_STEPS+4
        sta LP_NREQ
        cmp #LREQ_MAX + 1
        jcs @reqs
        lda LP_NSTEP            ; the steps: 3 bytes each, after the head
        asl a
        adc LP_NSTEP            ; (C clear: at most 180)
        sta FA_N
        clc
        lda LP_P
        adc #LP_HEAD
        sta FA_SRC
        lda LP_P+1
        adc #0
        sta FA_SRC+1
        lda #<(LW_STEPS + LP_HEAD)
        sta FA_DST
        lda #>(LW_STEPS + LP_HEAD)
        sta FA_DST+1
        jsr far_get
        clc                     ; LP_P = the first request
        lda FA_SRC
        adc FA_N
        sta LP_P
        lda FA_SRC+1
        adc #0
        sta LP_P+1
        ldx #0                  ; each request's place: its descriptor
@req:   cpx LP_NREQ             ;   count, then 16 bytes a descriptor
        beq @placed
        lda LP_P
        sta LW_REQLO,x
        sta FA_SRC
        lda LP_P+1
        sta LW_REQHI,x
        sta FA_SRC+1
        jsr get1                ; A = its count
        jsr skip_req
        inx
        bra @req
@placed:
        sec                     ; the requests end the block: LP_P less
        lda LP_P                ;   its start is its length
        sbc LW_HDR + LH_BLOCKS + LH_BLOCK * LB_PROGRAM + 2
        tay
        lda LP_P+1
        sbc LW_HDR + LH_BLOCKS + LH_BLOCK * LB_PROGRAM + 3
        cmp LW_HDR + LH_BLOCKS + LH_BLOCK * LB_PROGRAM + 5
        jne @bad
        cpy LW_HDR + LH_BLOCKS + LH_BLOCK * LB_PROGRAM + 4
        jne @bad
        stz LP_STEP
@step:  lda LP_STEP             ; the steps in order
        cmp LP_NSTEP
        jcs @bad                ; (no END)
        asl a
        adc LP_STEP
        tay
        lda LW_STEPS + LP_HEAD + 1,y    ; the argument (a byte is enough)
        sta LP_ARG
        lda LW_STEPS + LP_HEAD + 2,y
        jne @bad
        lda LW_STEPS + LP_HEAD,y
        beq @end                ; END
        cmp #LST_SPECIALS + 1
        jcs @bad
        asl a
        tax
        jsr @go
        inc LP_STEP
        bra @step
@end:   MARK 0
        stz GS_GAME
        rts
@go:    jmp (steps,x)
@bad:   lda #LS_PROGRAM
        jmp ld_stop
@steps: lda #LS_STEPS
        jmp ld_stop
@reqs:  lda #LS_REQUESTS
        jmp ld_stop

steps:  .word 0                 ; END (above)
        .word st_copy           ; COPYREQ
        .word st_variants       ; VARIANTS
        .word st_lines
        .word st_group
        .word st_flood
        .word st_cmaps
        .word st_priv           ; PRIVREQ
        .word st_spawn          ; SPAWN (stage C)
        .word st_specials       ; SPECIALS (stage C)

st_spawn:
        MARK 9
        jmp gs_spawn
st_specials:
        MARK 10
        jmp gx_specials

st_lines:
        MARK 4
        jmp lg_lines
st_group:
        MARK 5
        jmp lg_group
st_flood:
        MARK 6
        jmp lg_flood
st_cmaps:
        MARK 7
        jmp lg_cmaps

; COPYREQ n, PRIVREQ n: the program's request n
st_priv:
        MARK 8
        bra st_req
st_copy:
        MARK 3
st_req: ldx LP_ARG
        cpx LP_NREQ
        bcs @bad
        lda LW_REQLO,x
        sta FA_SRC
        lda LW_REQHI,x
        sta FA_SRC+1
        lda LP_PB
        sta FA_BANK
        jmp run_req
@bad:   lda #LS_PROGRAM
        jmp ld_stop

; VARIANTS m: the undo list of the map LV_VARMAP names, m's apply list,
; LV_VARMAP = m (docs/LEVELS.md 1.4)
st_variants:
        MARK 2
        lda LV_VARMAP
        beq @apply
        jsr ld_find             ; that map's header
        ldx #LB_UNDOREQ
        jsr ld_entry
        jsr run_list
@apply: lda LP_ARG
        jsr ld_find
        ldx #LB_APPLYREQ
        jsr ld_entry
        jsr run_list
        lda LP_ARG
        sta LV_VARMAP
        rts

; ---------------------------------------------------------------------------
; ld_find: FA_BANK:FA_SRC = the header of map A, from the store's
; directory (STORE_DIR_BANK:STORE_DIR). Stops when the directory is not
; the store's or names no such map. Changes A, X, Y.
; ---------------------------------------------------------------------------
ld_find:
        pha
        lda #STORE_DIR_BANK
        sta FA_BANK
        lda #<STORE_DIR
        sta FA_SRC
        lda #>STORE_DIR
        sta FA_SRC+1
        lda #<LW_DIR
        sta FA_DST
        lda #>LW_DIR
        sta FA_DST+1
        lda #STORE_DIR_HEAD + 4 * STORE_DIR_MAPS
        sta FA_N
        jsr far_get
        ldx #3                  ; "LVST", version 1, at most 12 maps
:       lda LW_DIR,x
        cmp dir_magic,x
        bne @dir
        dex
        bpl :-
        lda LW_DIR+4
        cmp #1
        bne @dir
        lda LW_DIR+5
        cmp #STORE_DIR_MAPS + 1
        bcs @dir
        tax
        pla
        ldy #STORE_DIR_HEAD
@next:  dex
        bmi @map
        cmp LW_DIR,y
        beq @found
        iny
        iny
        iny
        iny
        bra @next
@found: lda LW_DIR+1,y
        sta FA_BANK
        lda LW_DIR+2,y
        sta FA_SRC
        lda LW_DIR+3,y
        sta FA_SRC+1
        rts
@dir:   pla
        lda #LS_DIR
        jmp ld_stop
@map:   lda #LS_MAP
        jmp ld_stop
dir_magic:
        .byte "LVST"

; ---------------------------------------------------------------------------
; ld_block: FA_BANK:FA_SRC = block X of the header in LW_HDR, LP_N its
; length; stops on a codec other than raw. Changes A, Y.
; ld_entry: the same from the header at FA_BANK:FA_SRC (in the store): its
; entry fetched into LW_BE first. Changes A, Y, FA_DST, FA_N.
; ---------------------------------------------------------------------------
ld_block:
        txa                     ; Y = 6 X
        asl a
        sta LP_N
        txa
        asl a
        asl a
        clc
        adc LP_N
        tay
        lda LW_HDR + LH_BLOCKS,y
        sta FA_BANK
        lda LW_HDR + LH_BLOCKS + 1,y
        bne codec
        lda LW_HDR + LH_BLOCKS + 2,y
        sta FA_SRC
        lda LW_HDR + LH_BLOCKS + 3,y
        sta FA_SRC+1
        lda LW_HDR + LH_BLOCKS + 4,y
        sta LP_N
        lda LW_HDR + LH_BLOCKS + 5,y
        sta LP_N+1
        rts
codec:  lda #LS_CODEC
        jmp ld_stop

ld_entry:
        txa                     ; FA_SRC += LH_BLOCKS + 6 X
        asl a
        sta LP_N
        txa
        asl a
        asl a
        clc
        adc LP_N
        adc #LH_BLOCKS
        clc
        adc FA_SRC
        sta FA_SRC
        bcc :+
        inc FA_SRC+1
:       lda #<LW_BE
        sta FA_DST
        lda #>LW_BE
        sta FA_DST+1
        lda #LH_BLOCK
        sta FA_N
        jsr far_get
        lda LW_BE
        sta FA_BANK
        lda LW_BE+1
        bne codec
        lda LW_BE+2
        sta FA_SRC
        lda LW_BE+3
        sta FA_SRC+1
        lda LW_BE+4
        sta LP_N
        lda LW_BE+5
        sta LP_N+1
        rts

; ---------------------------------------------------------------------------
; run_list: the request list at FA_BANK:FA_SRC (its count, then each
; request: a descriptor count and the descriptors), every request run.
; run_req: the request at FA_BANK:FA_SRC run. Both change everything but
; FA_BANK.
; ---------------------------------------------------------------------------
run_list:
        jsr get1                ; the count
        inc FA_SRC
        bne :+
        inc FA_SRC+1
:       sta LP_N
@next:  lda LP_N
        beq @done
        jsr run_req
        dec LP_N
        bra @next
@done:  rts

run_req:
        jsr get1                ; the descriptor count, 1-16
        beq @bad
        cmp #AMEM_MAX + 1
        bcs @bad
        sta LW_REQ + REQ_HEAD - 3       ; "AMEM", 1, the count, 0, 0
        asl a
        asl a
        asl a
        asl a
        sta FA_N                ; 16 n (0: 256)
        clc
        adc #8
        sta LW_REQ + 10         ; the payload: 8 + 16 n
        lda #0
        adc #0
        ldy FA_N
        bne :+
        lda #1                  ; (n = 16: 264)
:       sta LW_REQ + 11
        ldx #9                  ; CONTROL, unit 0, selector $80
:       lda rq_head,x
        sta LW_REQ,x
        dex
        bpl :-
        ldx #4
:       lda rq_amem,x
        sta LW_REQ + 12,x
        dex
        bpl :-
        stz LW_REQ + REQ_HEAD - 2
        stz LW_REQ + REQ_HEAD - 1
        inc FA_SRC              ; the descriptors
        bne :+
        inc FA_SRC+1
:       lda #<(LW_REQ + REQ_HEAD)
        sta FA_DST
        lda #>(LW_REQ + REQ_HEAD)
        sta FA_DST+1
        jsr far_get
        clc                     ; the next request
        lda FA_SRC
        adc FA_N
        sta FA_SRC
        lda FA_SRC+1
        adc #0
        ldy FA_N
        bne :+
        inc a                   ; (256 bytes)
:       sta FA_SRC+1
        clc                     ; the bytes: 20 + 16 n
        lda LW_REQ + 10
        adc #12
        sta AM_N
        lda LW_REQ + 11
        adc #0
        sta AM_N+1
        jmp am_send
@bad:   lda #LS_PROGRAM
        jmp ld_stop
rq_head:
        .byte 4, 3, 0, 0, 0, $80, 0, 0, 0, 0
rq_amem:
        .byte "AMEM", 1

; get1: A = the byte at FA_BANK:FA_SRC (into LW_BE+6). Changes A, Y,
; FA_DST, FA_N.
get1:   lda #<(LW_BE + 6)
        sta FA_DST
        lda #>(LW_BE + 6)
        sta FA_DST+1
        lda #1
        sta FA_N
        jsr far_get
        lda LW_BE + 6
        rts

; skip_req: LP_P past a request of A descriptors (LP_P at its count).
; Changes A, LP_N+1.
skip_req:
        stz LP_N+1              ; 1 + 16 A
        asl a
        rol LP_N+1
        asl a
        rol LP_N+1
        asl a
        rol LP_N+1
        asl a
        rol LP_N+1
        sec
        adc LP_P
        sta LP_P
        lda LP_N+1
        adc LP_P+1
        sta LP_P+1
        rts

; ---------------------------------------------------------------------------
; am_send: the request at LW_REQ, AM_N bytes, through the FIFO; executed,
; its reply's first byte popped: 0, else a stop with the result in
; LV_AMEM. Interrupts masked meanwhile. Changes A, X, Y, AM_P, AM_N, AM_W.
; ---------------------------------------------------------------------------
am_send:
        php
        sei
        bit SP_RELEASE
        bit SP_ROM
        lda #<LW_REQ
        sta AM_P
        lda #>LW_REQ
        sta AM_P+1
        ldy #0
@byte:  lda (AM_P),y
        sta SP_DATA
        iny
        bne :+
        inc AM_P+1
:       lda AM_N
        bne :+
        dec AM_N+1
:       dec AM_N
        lda AM_N
        ora AM_N+1
        bne @byte
        lda #2                  ; execute
        sta SP_CTRL
        ldx #0
        ldy #0
        stz AM_W
@wait:  lda SP_CTRL
        bmi @ready
        dex
        bne @wait
        dey
        bne @wait
        dec AM_W
        bne @wait
        lda #AMEM_TIMEOUT
        bra @done
@ready: lda SP_DATA
        sta SP_POP
@done:  bit SP_RELEASE
        plp
        cmp #0
        bne :+
        rts
:       sta LV_AMEM
        lda #LS_AMEM
        ; (on to ld_stop)

; ld_stop: the load's stop: LV_STATUS = A, BRK
ld_stop:
        sta LV_STATUS
        brk
        .byte 0
