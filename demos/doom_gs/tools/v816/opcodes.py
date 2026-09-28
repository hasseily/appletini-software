"""The opcode table of the 65816.

OPCODES maps a mnemonic to a dictionary from addressing mode to opcode.
The modes name the form of the instruction, with the size of the
operand decided:

    imp                     no operand
    acc                     the accumulator ("asl a")
    imm                     immediate; "#" and "##" give its size, see
                            IMMEDIATE_SIZES
    dp  dp,x  dp,y          direct page, 8 bits
    abs abs,x abs,y         absolute, 16 bits
    long long,x             absolute long, 24 bits
    (dp) (dp,x) (dp),y      indirect through the direct page
    [dp] [dp],y             the same with a 24-bit pointer
    sr,s (sr,s),y           stack relative
    (abs) (abs,x) [abs]     indirect jumps
    rel8 rel16              branches
    move                    mvn and mvp: two bank bytes

The table is written by instruction group, as the data sheet of the
processor has it, so that a wrong entry shows as a break in a pattern.
"""

# ora and eor adc sta lda cmp sbc: the opcode is the base of the
# mnemonic plus the number of the mode.
_GROUP_ONE = {'ora': 0x00, 'and': 0x20, 'eor': 0x40, 'adc': 0x60,
              'sta': 0x80, 'lda': 0xa0, 'cmp': 0xc0, 'sbc': 0xe0}
_GROUP_ONE_MODES = {
    '(dp,x)': 0x01, 'sr,s': 0x03, 'dp': 0x05, '[dp]': 0x07, 'imm': 0x09,
    'abs': 0x0d, 'long': 0x0f, '(dp),y': 0x11, '(dp)': 0x12,
    '(sr,s),y': 0x13, 'dp,x': 0x15, '[dp],y': 0x17, 'abs,y': 0x19,
    'abs,x': 0x1d, 'long,x': 0x1f}

# asl rol lsr ror: the same five modes each.
_SHIFTS = {'asl': 0x00, 'rol': 0x20, 'lsr': 0x40, 'ror': 0x60}
_SHIFT_MODES = {'dp': 0x06, 'acc': 0x0a, 'abs': 0x0e, 'dp,x': 0x16,
                'abs,x': 0x1e}

_OTHERS = {
    'inc': {'acc': 0x1a, 'dp': 0xe6, 'abs': 0xee, 'dp,x': 0xf6,
            'abs,x': 0xfe},
    'dec': {'acc': 0x3a, 'dp': 0xc6, 'abs': 0xce, 'dp,x': 0xd6,
            'abs,x': 0xde},
    'bit': {'dp': 0x24, 'abs': 0x2c, 'dp,x': 0x34, 'abs,x': 0x3c,
            'imm': 0x89},
    'tsb': {'dp': 0x04, 'abs': 0x0c},
    'trb': {'dp': 0x14, 'abs': 0x1c},
    'stz': {'dp': 0x64, 'dp,x': 0x74, 'abs': 0x9c, 'abs,x': 0x9e},
    'stx': {'dp': 0x86, 'abs': 0x8e, 'dp,y': 0x96},
    'sty': {'dp': 0x84, 'abs': 0x8c, 'dp,x': 0x94},
    'ldx': {'imm': 0xa2, 'dp': 0xa6, 'abs': 0xae, 'dp,y': 0xb6,
            'abs,y': 0xbe},
    'ldy': {'imm': 0xa0, 'dp': 0xa4, 'abs': 0xac, 'dp,x': 0xb4,
            'abs,x': 0xbc},
    'cpx': {'imm': 0xe0, 'dp': 0xe4, 'abs': 0xec},
    'cpy': {'imm': 0xc0, 'dp': 0xc4, 'abs': 0xcc},
    'jmp': {'abs': 0x4c, 'long': 0x5c, '(abs)': 0x6c, '(abs,x)': 0x7c,
            '[abs]': 0xdc},
    'jml': {'long': 0x5c, '[abs]': 0xdc},
    'jsr': {'abs': 0x20, '(abs,x)': 0xfc},
    'jsl': {'long': 0x22},
    'pea': {'imm': 0xf4},
    'pei': {'(dp)': 0xd4},
    'per': {'rel16': 0x62},
    'brl': {'rel16': 0x82},
    'rep': {'imm': 0xc2},
    'sep': {'imm': 0xe2},
    'brk': {'imm': 0x00},
    'cop': {'imm': 0x02},
    'wdm': {'imm': 0x42},
    'mvp': {'move': 0x44},
    'mvn': {'move': 0x54},
}

_BRANCHES = {'bpl': 0x10, 'bmi': 0x30, 'bvc': 0x50, 'bvs': 0x70,
             'bra': 0x80, 'bcc': 0x90, 'bcs': 0xb0, 'bne': 0xd0,
             'beq': 0xf0}

_IMPLIED = {
    'php': 0x08, 'phd': 0x0b, 'clc': 0x18, 'tcs': 0x1b, 'plp': 0x28,
    'pld': 0x2b, 'sec': 0x38, 'tsc': 0x3b, 'rti': 0x40, 'pha': 0x48,
    'phk': 0x4b, 'cli': 0x58, 'phy': 0x5a, 'tcd': 0x5b, 'rts': 0x60,
    'pla': 0x68, 'rtl': 0x6b, 'sei': 0x78, 'ply': 0x7a, 'tdc': 0x7b,
    'dey': 0x88, 'txa': 0x8a, 'phb': 0x8b, 'tya': 0x98, 'txs': 0x9a,
    'txy': 0x9b, 'tay': 0xa8, 'tax': 0xaa, 'plb': 0xab, 'clv': 0xb8,
    'tsx': 0xba, 'tyx': 0xbb, 'iny': 0xc8, 'dex': 0xca, 'wai': 0xcb,
    'cld': 0xd8, 'phx': 0xda, 'stp': 0xdb, 'inx': 0xe8, 'nop': 0xea,
    'xba': 0xeb, 'sed': 0xf8, 'plx': 0xfa, 'xce': 0xfb}


def _table():
    table = {}
    for mnemonic, base in _GROUP_ONE.items():
        table[mnemonic] = {mode: base + number
                           for mode, number in _GROUP_ONE_MODES.items()
                           if (mnemonic, mode) != ('sta', 'imm')}
    for mnemonic, base in _SHIFTS.items():
        table[mnemonic] = {mode: base + number
                           for mode, number in _SHIFT_MODES.items()}
    for mnemonic, modes in _OTHERS.items():
        table[mnemonic] = dict(modes)
    for mnemonic, opcode in _BRANCHES.items():
        table[mnemonic] = {'rel8': opcode}
    for mnemonic, opcode in _IMPLIED.items():
        table[mnemonic] = {'imp': opcode}
    return table


OPCODES = _table()

# Bytes of the operand, by mode; "imm" is in IMMEDIATE_SIZES.
OPERAND_SIZES = {
    'imp': 0, 'acc': 0,
    'dp': 1, 'dp,x': 1, 'dp,y': 1, '(dp)': 1, '(dp,x)': 1, '(dp),y': 1,
    '[dp]': 1, '[dp],y': 1, 'sr,s': 1, '(sr,s),y': 1, 'rel8': 1,
    'abs': 2, 'abs,x': 2, 'abs,y': 2, '(abs)': 2, '(abs,x)': 2,
    '[abs]': 2, 'rel16': 2, 'move': 2,
    'long': 3, 'long,x': 3}

# The sizes that the immediate operand of a mnemonic can have. The size
# of the others depends on the M or X flag when the instruction runs;
# the source says which with "#" (8 bits) or "##" (16 bits).
IMMEDIATE_SIZES = {
    'rep': (1,), 'sep': (1,), 'brk': (1,), 'cop': (1,), 'wdm': (1,),
    'pea': (2,)}
MODE_DEPENDENT_IMMEDIATE = (1, 2)


def immediate_sizes(mnemonic):
    """The sizes in bytes that the immediate operand of `mnemonic` can
    have."""
    return IMMEDIATE_SIZES.get(mnemonic, MODE_DEPENDENT_IMMEDIATE)
