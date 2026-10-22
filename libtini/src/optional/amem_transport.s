; C8 ownership guard for the optional, baseline-identified raw FIFO module.
; IRQs cannot select another slot during submission/response consumption.
.setcpu "65C02"
.export _ti_amem_lock, _ti_amem_unlock
.import _ti_amem_saved_p, _ti_amem_saved_cx
.segment "CODE"
_ti_amem_lock:
        php
        pla
        sta _ti_amem_saved_p
        sei
        cld
        lda $C015
        sta _ti_amem_saved_cx
        sta $C006
        bit $CFFF
        bit $C700
        rts
_ti_amem_unlock:
        bit $CFFF
        lda _ti_amem_saved_cx
        bpl mainrom
        sta $C007
mainrom:
        lda _ti_amem_saved_p
        pha
        plp
        rts
