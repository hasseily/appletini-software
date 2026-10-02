; gvalid.s: validcount (milestone 9, stage C; docs/LEVELS.md 3.4;
; NATIVE.md 15.1 row 4; milestone 10's skeleton: one count, docs/GAME.md
; 1.7).
;
;   gv_inc      validcount++. Upstream has one validcount, which the game's
;               walks and the renderer's frame setup both raise: natively
;               it is the frame block's VALIDCOUNT, G_VALID its name in the
;               game core, and the renderer's nr_setup calls gv_inc too
;               (this file is linked into the render images, -D GV_RENDER).
;               The release build fixes upstream's wrap: when the count
;               wraps to 0 the line and sector caches are flushed and
;               emptied (go_flush: no cached record keeps an old stamp),
;               every stamp is cleared (each sector's in its LVMAP record,
;               each line's validcount and r_validcount in LVG0) and the
;               count becomes 1, so no stamp of an earlier walk can equal a
;               new count. Built with -D VCWRAP_UPSTREAM (every lockstep and
;               test build) it only adds 1, as upstream does.
;
; The render images assemble it with -D GV_RENDER -D VCWRAP_UPSTREAM (their
; test builds); the release frame's clear is milestone 11's (docs/LEVELS.md
; "Stage C as built"): a frame starts with the caches empty, so its clear
; needs no flush.

        .setcpu "65C02"
        .macpack longbranch
        .include "rlayout.inc"
.ifndef GV_RENDER
        .include "math.inc"
        .include "llayout.inc"
        .include "lgame.inc"
.else
G_VALID = VALIDCOUNT
.endif

        .export gv_inc
.ifndef VCWRAP_UPSTREAM
        .export gv_clear
        .import go_stamps0
.endif

.ifdef GV_RENDER
        .segment "RENDERW"
.else
        .segment "LOADW"
.endif

; ---------------------------------------------------------------------------
; gv_inc: validcount++. Changes A (and, at a wrap in the release build, X,
; Y, GC_T, GC_P, the API's temporaries, FA_*).
; ---------------------------------------------------------------------------
gv_inc:
        inc G_VALID
        bne @done
        inc G_VALID+1
.ifndef VCWRAP_UPSTREAM
        bne @done
        jsr gv_clear
        lda #1
        sta G_VALID
.endif
@done:  rts

.ifndef VCWRAP_UPSTREAM
; gv_clear: the caches flushed and emptied, then every sector's stamp
; (LVMAP) and every line's two stamps (LVG0) 0 (the object API's
; go_stamps0: no far access of a cached kind outside gobj.s)
gv_clear:
        jmp go_stamps0
.endif
