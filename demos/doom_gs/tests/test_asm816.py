"""Tests of tools/v816/asm816.py and opcodes.py: every opcode, the
choice of the operand size, holes and branches.

OPCODE_MAP is the opcode map of the 65816 in the order of the opcodes,
as the data sheet prints it. It is written apart from the table of
tools/v816/opcodes.py, which is in the order of the mnemonics, so that
a mistake in one of them shows.
"""

import unittest

import support
from v816 import asm816, linear, opcodes

# Two lines for each high nibble of the opcode, 8 opcodes each:
# mnemonic and mode.
OPCODE_MAP = '''
brk:imm ora:(dp,x) cop:imm ora:sr,s tsb:dp ora:dp asl:dp ora:[dp]
php:imp ora:imm asl:acc phd:imp tsb:abs ora:abs asl:abs ora:long
bpl:rel8 ora:(dp),y ora:(dp) ora:(sr,s),y trb:dp ora:dp,x asl:dp,x ora:[dp],y
clc:imp ora:abs,y inc:acc tcs:imp trb:abs ora:abs,x asl:abs,x ora:long,x
jsr:abs and:(dp,x) jsl:long and:sr,s bit:dp and:dp rol:dp and:[dp]
plp:imp and:imm rol:acc pld:imp bit:abs and:abs rol:abs and:long
bmi:rel8 and:(dp),y and:(dp) and:(sr,s),y bit:dp,x and:dp,x rol:dp,x and:[dp],y
sec:imp and:abs,y dec:acc tsc:imp bit:abs,x and:abs,x rol:abs,x and:long,x
rti:imp eor:(dp,x) wdm:imm eor:sr,s mvp:move eor:dp lsr:dp eor:[dp]
pha:imp eor:imm lsr:acc phk:imp jmp:abs eor:abs lsr:abs eor:long
bvc:rel8 eor:(dp),y eor:(dp) eor:(sr,s),y mvn:move eor:dp,x lsr:dp,x eor:[dp],y
cli:imp eor:abs,y phy:imp tcd:imp jml:long eor:abs,x lsr:abs,x eor:long,x
rts:imp adc:(dp,x) per:rel16 adc:sr,s stz:dp adc:dp ror:dp adc:[dp]
pla:imp adc:imm ror:acc rtl:imp jmp:(abs) adc:abs ror:abs adc:long
bvs:rel8 adc:(dp),y adc:(dp) adc:(sr,s),y stz:dp,x adc:dp,x ror:dp,x adc:[dp],y
sei:imp adc:abs,y ply:imp tdc:imp jmp:(abs,x) adc:abs,x ror:abs,x adc:long,x
bra:rel8 sta:(dp,x) brl:rel16 sta:sr,s sty:dp sta:dp stx:dp sta:[dp]
dey:imp bit:imm txa:imp phb:imp sty:abs sta:abs stx:abs sta:long
bcc:rel8 sta:(dp),y sta:(dp) sta:(sr,s),y sty:dp,x sta:dp,x stx:dp,y sta:[dp],y
tya:imp sta:abs,y txs:imp txy:imp stz:abs sta:abs,x stz:abs,x sta:long,x
ldy:imm lda:(dp,x) ldx:imm lda:sr,s ldy:dp lda:dp ldx:dp lda:[dp]
tay:imp lda:imm tax:imp plb:imp ldy:abs lda:abs ldx:abs lda:long
bcs:rel8 lda:(dp),y lda:(dp) lda:(sr,s),y ldy:dp,x lda:dp,x ldx:dp,y lda:[dp],y
clv:imp lda:abs,y tsx:imp tyx:imp ldy:abs,x lda:abs,x ldx:abs,y lda:long,x
cpy:imm cmp:(dp,x) rep:imm cmp:sr,s cpy:dp cmp:dp dec:dp cmp:[dp]
iny:imp cmp:imm dex:imp wai:imp cpy:abs cmp:abs dec:abs cmp:long
bne:rel8 cmp:(dp),y cmp:(dp) cmp:(sr,s),y pei:(dp) cmp:dp,x dec:dp,x cmp:[dp],y
cld:imp cmp:abs,y phx:imp stp:imp jml:[abs] cmp:abs,x dec:abs,x cmp:long,x
cpx:imm sbc:(dp,x) sep:imm sbc:sr,s cpx:dp sbc:dp inc:dp sbc:[dp]
inx:imp sbc:imm nop:imp xba:imp cpx:abs sbc:abs inc:abs sbc:long
beq:rel8 sbc:(dp),y sbc:(dp) sbc:(sr,s),y pea:imm sbc:dp,x inc:dp,x sbc:[dp],y
sed:imp sbc:abs,y plx:imp xce:imp jsr:(abs,x) sbc:abs,x inc:abs,x sbc:long,x
'''

# For each mode, an operand in the syntax of the assembler and the
# bytes that it must give. The constants choose the size of the
# address by their value.
OPERANDS = {
    'imp': ('', ''), 'acc': ('a', ''),
    'dp': ('0x12', '12'), 'dp,x': ('0x12,x', '12'),
    'dp,y': ('0x12,y', '12'),
    '(dp)': ('(0x12)', '12'), '(dp,x)': ('(0x12,x)', '12'),
    '(dp),y': ('(0x12),y', '12'),
    '[dp]': ('[0x12]', '12'), '[dp],y': ('[0x12],y', '12'),
    'sr,s': ('0x12,s', '12'), '(sr,s),y': ('(0x12,s),y', '12'),
    'abs': ('0x1234', '3412'), 'abs,x': ('0x1234,x', '3412'),
    'abs,y': ('0x1234,y', '3412'),
    '(abs)': ('(0x1234)', '3412'), '(abs,x)': ('(0x1234,x)', '3412'),
    '[abs]': ('[0x1234]', '3412'),
    'long': ('0x123456', '563412'), 'long,x': ('0x123456,x', '563412'),
    'rel8': ('.+0x14', '12'), 'rel16': ('.+0x1237', '3412'),
}
ONE_BYTE_IMMEDIATE = ('brk', 'cop', 'wdm', 'rep', 'sep')


def opcode_map():
    """(opcode, mnemonic, mode) for the 256 opcodes."""
    entries = OPCODE_MAP.split()
    return [(opcode,) + tuple(entry.split(':'))
            for opcode, entry in enumerate(entries)]


def code(text):
    """The bytes of the first fragment of the source `text`, in
    hexadecimal."""
    return support.assemble_clean(text).fragments[0].data.hex()


def errors(text):
    return [error.message for error in support.assemble_text(text).errors]


def holes(text):
    fragment = support.assemble_clean(text).fragments[0]
    return [(hole.offset, hole.width, hole.kind, hole.value.reloc)
            for hole in fragment.holes]


class OpcodeTable(unittest.TestCase):
    def test_the_map_has_256_opcodes(self):
        self.assertEqual(len(opcode_map()), 256)

    def test_table_and_map_agree(self):
        from_map = {}
        for opcode, mnemonic, mode in opcode_map():
            from_map.setdefault(mnemonic, {})[mode] = opcode
        from_map['jmp']['long'] = from_map['jml']['long']
        from_map['jmp']['[abs]'] = from_map['jml']['[abs]']
        self.assertEqual(opcodes.OPCODES, from_map)

    def test_every_mode_has_a_size(self):
        for modes in opcodes.OPCODES.values():
            for mode in modes:
                if mode != 'imm':
                    self.assertIn(mode, opcodes.OPERAND_SIZES)


class EveryOpcode(unittest.TestCase):
    def check(self, opcode, source, operand):
        self.assertEqual(code(' %s\n' % source), '%02x%s' % (opcode, operand),
                         source)

    def test_every_opcode(self):
        for opcode, mnemonic, mode in opcode_map():
            if mode in ('imm', 'move'):
                continue
            text, operand = OPERANDS[mode]
            self.check(opcode, '%s %s' % (mnemonic, text), operand)

    def test_immediates_of_8_bits(self):
        for opcode, mnemonic, mode in opcode_map():
            if mode == 'imm' and mnemonic != 'pea':
                self.check(opcode, '%s #0x12' % mnemonic, '12')

    def test_immediates_of_16_bits(self):
        for opcode, mnemonic, mode in opcode_map():
            if mode == 'imm' and mnemonic not in ONE_BYTE_IMMEDIATE:
                self.check(opcode, '%s ##0x1234' % mnemonic, '3412')

    def test_one_size_with_either_mark(self):
        self.assertEqual(code(' pea #0x1234\n'), 'f43412')
        self.assertEqual(code(' rep ##0x30\n'), 'c230')

    def test_jmp_has_the_long_forms_of_jml(self):
        self.assertEqual(code(' jmp long:0x1234\n'), '5c341200')
        self.assertEqual(code(' jmp [0x1234]\n'), 'dc3412')

    def test_pei_without_brackets(self):
        self.assertEqual(code(' pei 0x12\n'), 'd412')
        self.assertEqual(code(' pei dp:0x12\n'), 'd412')

    def test_block_moves_are_refused(self):
        for mnemonic in ('mvn', 'mvp'):
            found = errors(' %s 1\n' % mnemonic)
            self.assertEqual(len(found), 1)
            self.assertIn('block moves', found[0])

    def test_mnemonic_in_upper_case(self):
        self.assertEqual(code(' LDA #1\n'), 'a901')


class ManualExamples(unittest.TestCase):
    """The list files of sections 21.3 to 21.3.2 of the manual."""

    def test_operand_that_the_assembler_cannot_solve(self):
        source = ' .extern foo\n lda foo\n lda 10\n lda dp:foo\n'
        self.assertEqual(code(source), 'ad0000' 'a50a' 'a500')
        self.assertEqual(holes(source), [(1, 2, 'abs', None),
                                         (6, 1, 'dp', None)])

    def test_word_operators(self):
        source = (' .extern foo, bar\n lda ##.word0 foo\n sta dp:bar\n'
                  ' lda ##.word2 foo\n sta dp:bar+2\n')
        self.assertEqual(code(source), 'a90000' '8500' 'a90000' '8500')
        self.assertEqual(holes(source), [
            (1, 2, 'imm', 'word0'), (4, 1, 'dp', None),
            (6, 2, 'imm', 'word2'), (9, 1, 'dp', None)])

    def test_immediate_size(self):
        self.assertEqual(code(' ldx ##0x1234\n lda #0xAB\n'),
                         'a23412' 'a9ab')

    def test_addressing_mode_range(self):
        self.assertEqual(
            code(' lda dp:10,x\n lda abs:10,x\n lda long:10,x\n'
                 ' lda 10,x\n lda 0x1000,x\n lda 0x331000,x\n'),
            'b50a' 'bd0a00' 'bf0a0000' 'b50a' 'bd0010' 'bf001033')

    def test_tiny_near_and_kbank(self):
        source = (' .extern foo\n lda dp: .tiny (foo+2)\n'
                  ' lda abs: .near (foo+2)\n here: jmp .kbank here\n')
        self.assertEqual(code(source), 'a500' 'ad0000' '4c0000')
        self.assertEqual(holes(source), [
            (1, 1, 'dp', 'tiny'), (3, 2, 'abs', 'near'),
            (6, 2, 'abs', 'kbank')])


class OperandSize(unittest.TestCase):
    def test_constant_takes_the_shortest_size_that_exists(self):
        self.assertEqual(code(' jmp 0x12\n'), '4c1200')
        self.assertEqual(code(' lda 0x12,y\n'), 'b91200')
        self.assertEqual(code(' jsl 0x12\n'), '22120000')
        self.assertEqual(code(' stx 0x12,y\n'), '9612')

    def test_constant_from_equates_and_label_distances(self):
        self.assertEqual(
            code('N .equ M + 1\nM .equ 0xff\n lda N\n lda M\n'),
            'ad0001' 'a5ff')
        self.assertEqual(code('a1: nop\na2: lda a2 - a1\n'), 'ea' 'a501')

    def test_constant_that_is_too_large(self):
        self.assertEqual(len(errors(' stz 0x123456\n')), 1)
        self.assertEqual(len(errors(' lda dp:0x1234\n')), 1)
        self.assertEqual(len(errors(' lda #0x1234\n')), 1)

    def test_negative_immediate(self):
        self.assertEqual(code(' lda #-1\n lda ##-2\n'), 'a9ff' 'a9feff')

    def test_placement_dependent_operand_takes_16_bits(self):
        source = 'here: lda here\n lda here,x\n jmp here\n jmp (here)\n'
        self.assertEqual(code(source),
                         'ad0000' 'bd0000' '4c0000' '6c0000')

    def test_placement_dependent_operand_with_one_size(self):
        source = (' .extern p\n lda [p],y\n lda (p),y\n jsl p\n'
                  ' lda p,s\n')
        self.assertEqual(code(source), 'b700' 'b100' '22000000' 'a300')
        self.assertEqual([hole[:3] for hole in holes(source)], [
            (1, 1, 'dp'), (3, 1, 'dp'), (5, 3, 'long'), (9, 1, 'dp')])

    def test_operators_without_prefix(self):
        source = (' .extern p\n lda .near p\n jsr .kbank p\n'
                  ' lda .tiny p\n lda [.tiny p],y\n')
        self.assertEqual(code(source), 'ad0000' '200000' 'a500' 'b700')

    def test_byte_and_word_operators_need_a_prefix(self):
        self.assertEqual(len(errors(' .extern p\n lda .word0 p\n')), 1)
        self.assertEqual(code(' .extern p\n lda abs:.word0 p\n'), 'ad0000')

    def test_prefix_that_the_instruction_does_not_have(self):
        self.assertEqual(len(errors(' jsr long:0x1234\n')), 1)
        self.assertEqual(len(errors(' lda [abs:0x12],y\n')), 1)

    def test_operator_on_a_constant_is_a_constant(self):
        self.assertEqual(
            code('V .equ 0x123456\n lda #.byte0 V\n lda #.byte1 V\n'
                 ' lda #.byte2 V\n lda ##.word0 V\n lda ##.word2 V\n'),
            'a956' 'a934' 'a912' 'a95634' 'a91200')

    def test_operator_before_a_sum(self):
        """".word0 NAME + 2" is "(.word0 NAME) + 2", which the sources
        use for the low word of NAME + 2."""
        source = ' .extern p\n lda ##.word0 p + 2\n'
        fragment = support.assemble_clean(source).fragments[0]
        hole = fragment.holes[0]
        self.assertEqual(hole.value.reloc, 'word0')
        self.assertEqual(hole.value.linear,
                         linear.Linear.atom(('symbol', 'p'), 2))

    def test_wrong_operands(self):
        self.assertEqual(len(errors(' nop 1\n')), 1)
        self.assertEqual(len(errors(' lda\n')), 1)
        self.assertEqual(len(errors(' sta #1\n')), 1)
        self.assertEqual(len(errors(' stz 1,y\n')), 1)
        self.assertEqual(len(errors(' jsr [0x1234]\n')), 1)


class Branches(unittest.TestCase):
    def test_inside_the_fragment(self):
        self.assertEqual(
            code('back: nop\n bne back\n beq ahead\n nop\nahead: rts\n'),
            'ea' 'd0fd' 'f001' 'ea' '60')
        self.assertEqual(code('1$: brl 1$\n'), '82fdff')
        self.assertEqual(code(' bpl .+3\n dex\n'), '1001' 'ca')

    def test_to_a_position_equate(self):
        self.assertEqual(code(' bra there\n nop\nthere .equ .\n rts\n'),
                         '8001' 'ea' '60')

    def test_too_far(self):
        source = 'a1: .space 200\n bne a1\n'
        found = errors(source)
        self.assertEqual(len(found), 1)
        self.assertIn('bytes away', found[0])
        self.assertEqual(code('a1: .space 200\n brl a1\n')[-6:], '8235ff')

    def test_to_another_fragment_is_a_hole(self):
        source = (' .section one\n bra there\n brl there\n'
                  ' .section two\nthere: rts\n')
        unit = support.assemble_clean(source)
        first, second = unit.fragments
        self.assertEqual(first.data.hex(), '8000' '820000')
        self.assertEqual(
            [(hole.offset, hole.width, hole.kind) for hole in first.holes],
            [(1, 1, 'rel'), (3, 2, 'rel')])
        distance = first.holes[1].value.linear
        self.assertEqual(distance.constant, -5)
        self.assertEqual(distance.coefficient(second.atom), 1)
        self.assertEqual(distance.coefficient(first.atom), -1)

    def test_branch_needs_a_plain_target(self):
        self.assertEqual(len(errors('x: bne dp:x\n')), 1)
        self.assertEqual(len(errors('x: bne (x)\n')), 1)


class Helpers(unittest.TestCase):
    def test_little_endian(self):
        self.assertEqual(asm816.little_endian(0x1234, 2), b'\x34\x12')
        self.assertEqual(asm816.little_endian(-2, 2), b'\xfe\xff')
        self.assertEqual(asm816.little_endian(0x12345678, 3),
                         b'\x78\x56\x34')

    def test_fits(self):
        self.assertTrue(asm816.fits(255, 1))
        self.assertTrue(asm816.fits(-128, 1))
        self.assertFalse(asm816.fits(256, 1))
        self.assertFalse(asm816.fits(-129, 1))
        self.assertFalse(asm816.fits(-1, 1, signed_too=False))


if __name__ == '__main__':
    unittest.main()
