.setcpu "65C02"
; A timed-out C8 command leaves an unknown reply in the shared FIFO.
; Both clients must stop until the program exits.
.export _ti_private_poisoned, _ti_net_poisoned
.segment "NEARBSS"
_ti_private_poisoned:
_ti_net_poisoned: .res 1
