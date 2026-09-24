; Pinball Construction Set for the Appletini -- the upstream's fixed RAM
; tables, relocated.
;
; The original put these at fixed addresses inside the text pages, the
; hires page area and the overlay region ($200-$7FF, $4000-$6FFF,
; $8F00-$9AFF). The converted modules import them by name; here they get
; addresses outside the ranges the virtual TransWarp mirrors.
;
; DIV7/MOD7: the original converted a pixel x into (byte column, bit) with
; these tables. The port's bitmap records carry the pixel x directly, so
; DIV7 is the identity and MOD7 is all zeros: every upstream line that does
; `LDA DIV7,X / STA rec+3 / LDA MOD7,X / STA rec+4` produces (x, 0), which
; is exactly the port's (x lo, x hi) record layout.

.setcpu "65C02"
.include "pcs.inc"

.export PBTBLO, PBTBHI, VLO, VHI, VECTLO, VECTHI, RCN, RUNCHN, TIME
.export NVRTX, NDXCOEFF, NDXFRACT, NDXCODE, DXBUFR
.export P1STATE, P2STATE, P3STATE, P4STATE
.export SLEEPCODE, SLEEPLO, SLEEPHI, SLEEPERS
.export LOGIC, WSET, PBDATA
.export BITMAPS: absolute
.export DIV7, MOD7
.import PBBASE


; the object database (pcs.cfg places PBBASE and PBDX)
LOGIC   = PBBASE                ; 6 gates x 4 bytes
WSET    = PBBASE+24             ; gravity, speed, kick, elasticity
PBDATA  = PBBASE+$1C            ; count, sizes, records, then the span buffer
BITMAPS = 0                     ; the upstream anchor of its bitmap block, unused

.segment "BSS"

PBTBLO:     .res 192            ; per row: address of the row's span records
PBTBHI:     .res 192
VLO:        .res 128            ; per object: L-record address (0 = polygon)
VLO_END:
VHI:        .res 128
RCN:        .res 128            ; run chain: indices of the library objects
TIME:       .res 128            ; per object: TIME mask during play
VECTLO = VLO                    ; RUN2's names for the same tables
VECTHI = VHI
RUNCHN = RCN
NVRTX:      .res 64             ; scan converter: per vertex edge tables
NDXCOEFF:   .res 64
NDXFRACT:   .res 64
NDXCODE:    .res 64
DXBUFR:     .res 32             ; slope codes of the current row's crossings
P1STATE:    .res 512            ; RUN2: per player saved object state
P2STATE:    .res 512
P3STATE:    .res 512
P4STATE:    .res 512
SLEEPCODE:  .res SLEEP_MAX      ; RUN2: sleeping (captured) balls
SLEEPLO:    .res SLEEP_MAX
SLEEPHI:    .res SLEEP_MAX
SLEEPERS:   .res SLEEP_MAX*23

.segment "RODATA"

DIV7:
.repeat 256, i
        .byte   i
.endrepeat
MOD7:
.repeat 256
        .byte   0
.endrepeat
