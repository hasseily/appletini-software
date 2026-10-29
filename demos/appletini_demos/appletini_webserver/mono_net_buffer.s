.setcpu "6502"
.export _mono_http_reply
.segment "NETBSS"
; Fresh descriptor/body scratch, never retained across a NET invocation.
_mono_http_reply: .res 512
