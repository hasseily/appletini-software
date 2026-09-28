"""The instruction names of the 65816.

The front end needs the names only, to tell an instruction from a macro
and from a mistake. The opcode table belongs to the encoder.
"""

MNEMONICS = frozenset("""
    adc and asl bcc bcs beq bit bmi bne bpl bra brk brl bvc bvs clc cld
    cli clv cmp cop cpx cpy dec dex dey eor inc inx iny jml jmp jsl jsr
    lda ldx ldy lsr mvn mvp nop ora pea pei per pha phb phd phk php phx
    phy pla plb pld plp plx ply rep rol ror rti rtl rts sbc sec sed sei
    sep sta stp stx sty stz tax tay tcd tcs tdc trb tsb tsc tsx txa txs
    txy tya tyx wai wdm xba xce
""".split())

# Instructions that can work on the accumulator, written "asl a".
ACCUMULATOR = frozenset('asl dec inc lsr rol ror'.split())
