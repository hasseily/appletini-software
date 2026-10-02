#!/usr/bin/env python3
"""Model of the 65C02 effect player (src/sound/fx.s): the specification
and the oracle of part fxplay (milestone 11; sound track S4), as
player.py is the music's.

Usage:  python3 tools/sound/fxplay.py [SFX.1] [--sound N] [--volume V]
                                      [--sep S] [--ntsc] [--log OUT]
    Plays one effect alone and prints (or writes) the AY writes of chip 3
    at every interrupt.

The design is tools/sound/README.md, "Effects (S4)", "The player"
(docs/SCREENS.md 0.1 F12, 2.3, 3, 4.4); docs/m11-parts/fxplay.md records
what this part decided where the design left a choice. The 65C02 player
keeps the state below, runs the steps below in their order with the same
integer arithmetic, and must write the same registers of chip 3, in the
same order, at every interrupt. Original code; nothing of upstream's.

State. Three voices, chip 3's channels A, B, C (VOICE_FIELDS of
tools/native/s2layout.py, card $E413-$E442):

    flags   ACTIVE ($80), ENDING ($40: level 0 at the next interrupt,
            then idle), STARVED ($02: no bytes in this interrupt), LAST
            ($01: the script ends when the current wait expires)
    head    the next script byte to copy (an address in bank SFX)
    left    the script's bytes not yet in the ring
    wpos    bytes put in the ring, mod 256 (the main loop's)
    rpos    bytes taken from it by the interrupt, mod 256
    run     ticks left of the current state (0: read the script)
    per     the tone period (0: tone off); att the step's attenuation
            (0-80, 80 silent); noise the noise period (0: off)
    chan    the channel whose sound it plays; vatt VATT[volume]; sound
    ring    128 bytes; (wpos - rpos) mod 256 of them unread

The player: FX_ON, FX_HOLD, FX_INVAL, the tempo fraction (16 bits);
want[0..10] and shadow[0..10], R0-R10 of chip 3; the write list. One
mailbox a channel (flags STOP 1, START 2, VOLUME 4; sound, volume,
separation).

Each interrupt (fx_step, then S2's snd_tick, then fx_burst):

  1. Nothing (no write, the tempo kept) unless FX_ON and a voice is
     active or ending.
  2. The tempo: the fraction += the music's (52,135 PAL, 22,043 NTSC);
     ticks = 2 + its carry. Every voice's STARVED is cleared.
  3. Each active voice, A then B then C, runs the ticks (Voice.tick): a
     tick that finds no bytes, or not all of a set's, marks the voice
     STARVED and holds it (no more ticks in this interrupt); a tick that
     ends the script (an end byte, a byte $50-$FE, or the wait of a LAST
     set expiring) makes it ENDING.
  4. Compose: an active voice that is not starved gives R2v, R2v+1 its
     period, R8+v = LEVEL[min(80, att + vatt)] (the music's table,
     tables.LEVEL), its tone bit on in R7 when its period is not 0, its
     noise bit on when its noise is; R6 = the noise period of the
     loudest voice with noise on (the lowest min(80, att + vatt); the
     first voice of a tie), unchanged when none. Any other voice: R8+v
     0, its bits off, its period kept; an ending one becomes idle. R7's
     bits 6-7 are 0.
  5. The write list: nothing while FX_HOLD; with FX_INVAL, R0-R10 all
     (then the shadow is valid); else each register that differs from
     the shadow. fx_burst writes it, R0 first, after the music's burst.

The frame (fx_service), main loop: each channel's mailbox in order: with
FX_ON 0 it is just emptied; a STOP or a START makes the channel's active
voice ENDING; a START then chooses a voice (Stereo, tables.FX_VOICES:
A left, B right, C centre; tables.fx_voice_order: separation below 96,
the first free of A, C, B; 96 to 128, of C, A, B; 129 to 160, of C, B,
A; above 160, of B, C, A; a voice is free when it is not active; none
free: no start) and starts it (its channel,
sound, VATT[volume & 127], tone 0, attenuation 80, noise 0, run 0, the
script with its 4-byte header at its directory's address and length, the
ring refilled from empty, then rpos 4: the header taken; ACTIVE last); a
VOLUME sets the channel's active voice's vatt; the mailbox is emptied.
Then every active voice's ring is refilled: twice, a piece of min(free,
to the ring's end, left) bytes, each published (wpos) after its bytes.

The mailboxes' writer (the channel logic, tools/sound/README.md "The game
side"): a start sets START, its sound, volume and separation; a stop sets
STOP and clears START and VOLUME; a volume sets VOLUME and the volume.
fx_isplaying(c): the channel's voice active, or START in its mailbox.
fx_song: FX_HOLD set; S2's snd_start; FX_INVAL set; FX_HOLD cleared.
fx_stopall: every active voice ENDING; every mailbox emptied. fx_init:
FX_ON = 1 for SND_MUSIC (else 0), FX_HOLD 0, FX_INVAL 1, the fraction
0, want all 0 but R7 $3F, every voice idle, every mailbox empty.

Standard library only.
"""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound import tables  # noqa: E402

VOICES = 3
RING = 128
NREGS = 11
CHIP = 3
ACTIVE, ENDING, STARVED, LAST = 0x80, 0x40, 0x02, 0x01
MX_STOP, MX_START, MX_VOLUME = 0x01, 0x02, 0x04
BANK_BASE = 0x0200              # SFX.1 is loaded at $0200 of bank SFX
DIRECTORY = 0x0200
VATT_AT = 0x02D0
SOUNDS = 52
ATT_SILENT = tables.ATT_MAX     # 80
TONE_BITS = (0x01, 0x02, 0x04)
NOISE_BITS = (0x08, 0x10, 0x20)
SND_MUSIC, SND_NO_MUSIC = 0, 1
HEADER = 4
NUM_CHANNELS = 3

# the bytes of a set $4k, from its field bits
SET_LENGTH = tuple(1 + 2 * (k & 1) + (k >> 1 & 1) + (k >> 2 & 1) +
                   (k >> 3 & 1) for k in range(16))


class Bank:
    """Bank SFX: SFX.1's bytes at $0200 (tools/sound/fxconv.py)."""

    def __init__(self, data):
        self.data = bytes(data)

    def byte(self, address):
        return self.data[address - BANK_BASE]

    def entry(self, sound):
        """(address, length) of sound 1-52's script with its header."""
        at = DIRECTORY + 4 * (sound - 1)
        return (self.byte(at) | self.byte(at + 1) << 8,
                self.byte(at + 2) | self.byte(at + 3) << 8)

    def vatt(self, volume):
        return self.byte(VATT_AT + (volume & 0x7F))


class Voice:
    def __init__(self):
        self.flags = 0
        self.head = self.left = 0
        self.wpos = self.rpos = 0
        self.run = 0
        self.per = 0
        self.att = ATT_SILENT
        self.noise = 0
        self.chan = 0
        self.vatt = 0
        self.sound = 0
        self.ring = bytearray(RING)

    @property
    def unread(self):
        return (self.wpos - self.rpos) & 0xFF

    def take(self):
        b = self.ring[self.rpos & (RING - 1)]
        self.rpos = (self.rpos + 1) & 0xFF
        return b

    def tick(self):
        """One tick; False when the voice takes no more ticks in this
        interrupt (starved, or ended)."""
        if self.run:
            self.run -= 1
            if self.run:
                return True
            if self.flags & LAST:
                self.flags = ENDING
                return False
        while True:
            avail = self.unread
            if avail == 0:
                self.flags |= STARVED
                return False
            op = self.ring[self.rpos & (RING - 1)]
            if op < 0x40:
                self.take()
                self.run = (op & 0x3F) + 1
                return True
            if op >= 0x50:
                self.flags = ENDING
                return False
            if SET_LENGTH[op & 0x0F] > avail:
                self.flags |= STARVED
                return False
            self.take()
            if op & 1:
                lo = self.take()
                self.per = lo | self.take() << 8
            if op & 2:
                self.att = self.take()
            if op & 4:
                self.noise = self.take()
            if op & 8:
                self.flags |= LAST
                self.run = (self.take() & 0x3F) + 1
                return True


class Mailbox:
    def __init__(self):
        self.flags = self.sound = self.vol = self.sep = 0


class FxPlayer:
    """The effect player (fx.s) with bank `bank` (SFX.1's bytes) and the
    clock's standard (ntsc: CLK_STD's bit 7)."""

    def __init__(self, bank, ntsc=False, channels=NUM_CHANNELS):
        self.bank = bank if isinstance(bank, Bank) else Bank(bank)
        self.ntsc = ntsc
        self.voices = [Voice() for _ in range(VOICES)]
        self.mail = [Mailbox() for _ in range(channels)]
        self.on = 0
        self.hold = 0
        self.inval = 1
        self.frac = 0
        self.want = [0] * NREGS
        self.shadow = [0] * NREGS
        self.writes = []
        self.init(SND_MUSIC)

    # -- the main loop -----------------------------------------------------

    def init(self, answer):
        """fx_init: A = snd_probe's answer."""
        self.on = 1 if answer == SND_MUSIC else 0
        self.hold = 0
        self.inval = 1
        self.frac = 0
        self.writes = []
        self.want = [0] * NREGS
        self.want[7] = 0x3F
        for v in self.voices:
            v.flags = 0
        for m in self.mail:
            m.flags = 0

    def mail_start(self, c, sound, volume, sep):
        m = self.mail[c]
        m.flags |= MX_START
        m.sound, m.vol, m.sep = sound, volume, sep

    def mail_stop(self, c):
        m = self.mail[c]
        m.flags = (m.flags | MX_STOP) & ~(MX_START | MX_VOLUME) & 0xFF

    def mail_volume(self, c, volume):
        m = self.mail[c]
        m.flags |= MX_VOLUME
        m.vol = volume

    def isplaying(self, c):
        if self.mail[c].flags & MX_START:
            return True
        return any(v.flags & ACTIVE and v.chan == c for v in self.voices)

    def stopall(self):
        for v in self.voices:
            if v.flags & ACTIVE:
                v.flags = ENDING
        for m in self.mail:
            m.flags = 0

    def song_begin(self):
        """fx_song before snd_start."""
        self.hold = 1

    def song_end(self):
        """fx_song after snd_start."""
        self.inval = 1
        self.hold = 0

    def chan_voice(self, c):
        for v in self.voices:
            if v.flags & ACTIVE and v.chan == c:
                return v
        return None

    def choose(self, sep):
        for k in tables.fx_voice_order(sep):
            if not self.voices[k].flags & ACTIVE:
                return self.voices[k]
        return None

    def service(self):
        """fx_service."""
        for c, m in enumerate(self.mail):
            f = m.flags
            if f and self.on:
                if f & (MX_STOP | MX_START):
                    v = self.chan_voice(c)
                    if v is not None:
                        v.flags = ENDING
                if f & MX_START:
                    v = self.choose(m.sep)
                    if v is not None:
                        self.start(v, c, m)
                if f & MX_VOLUME:
                    v = self.chan_voice(c)
                    if v is not None:
                        v.vatt = self.bank.vatt(m.vol)
            m.flags = 0
        for v in self.voices:
            if v.flags & ACTIVE:
                self.refill(v)

    def start(self, v, c, m):
        v.chan = c
        v.sound = m.sound
        v.head, v.left = self.bank.entry(m.sound)
        v.wpos = v.rpos = 0
        v.run = 0
        v.per = 0
        v.noise = 0
        v.att = ATT_SILENT
        v.vatt = self.bank.vatt(m.vol)
        self.refill(v)
        v.rpos = HEADER                 # the header, taken
        v.flags = ACTIVE

    def refill(self, v):
        for _ in range(2):
            n = RING - v.unread
            if n == 0:
                return
            w = v.wpos & (RING - 1)
            n = min(n, RING - w)
            if v.left < 256:
                if v.left == 0:
                    return
                n = min(n, v.left)
            for k in range(n):
                v.ring[w + k] = self.bank.byte(v.head + k)
            v.head = (v.head + n) & 0xFFFF
            v.left -= n
            v.wpos = (v.wpos + n) & 0xFF

    # -- the interrupt -----------------------------------------------------

    def step(self):
        """fx_step: the write list of this interrupt (fx_burst's)."""
        self.writes = []
        if not self.on or not any(v.flags & (ACTIVE | ENDING)
                                  for v in self.voices):
            return self.writes
        whole, frac = tables.tempo(tables.NTSC_NATIVE if self.ntsc
                                   else tables.PAL_NATIVE)
        self.frac += frac
        ticks = whole + (self.frac >> 16)
        self.frac &= 0xFFFF
        for v in self.voices:
            v.flags &= ~STARVED & 0xFF
            if v.flags & ACTIVE:
                for _ in range(ticks):
                    if not v.tick():
                        break
        self.compose()
        if self.hold:
            return self.writes
        regs = range(NREGS)
        if not self.inval:
            regs = [r for r in regs if self.want[r] != self.shadow[r]]
        self.inval = 0
        for r in regs:
            self.shadow[r] = self.want[r]
            self.writes.append((CHIP, r, self.want[r]))
        return self.writes

    def compose(self):
        mix = 0x3F
        best = None
        for k, v in enumerate(self.voices):
            if v.flags & (ACTIVE | STARVED) == ACTIVE:
                a = min(ATT_SILENT, v.att + v.vatt)
                self.want[8 + k] = tables.LEVEL[a]
                if v.noise:
                    mix &= ~NOISE_BITS[k]
                    if best is None or a < best:
                        best = a
                        self.want[6] = v.noise
                if v.per:
                    mix &= ~TONE_BITS[k]
                self.want[2 * k] = v.per & 0xFF
                self.want[2 * k + 1] = v.per >> 8
            else:
                self.want[8 + k] = 0
                if not v.flags & ACTIVE:
                    v.flags = 0
        self.want[7] = mix

    def interrupt(self):
        """fx_step and fx_burst together (no music between them)."""
        return list(self.step())


# ---------------------------------------------------------------------------

def default_bank():
    return Path(__file__).resolve().parents[2] / 'build' / 'native' / \
        'm11' / 'fxconv' / 'SFX.1'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('bank', nargs='?', default=str(default_bank()))
    parser.add_argument('--sound', type=int, default=1)
    parser.add_argument('--volume', type=int, default=127)
    parser.add_argument('--sep', type=int, default=128)
    parser.add_argument('--ntsc', action='store_true')
    parser.add_argument('--interrupts', type=int, default=120)
    parser.add_argument('--log')
    args = parser.parse_args(argv)
    fx = FxPlayer(Path(args.bank).read_bytes(), ntsc=args.ntsc)
    fx.mail_start(0, args.sound, args.volume, args.sep)
    fx.service()
    lines = []
    for k in range(1, args.interrupts + 1):
        w = fx.interrupt()
        fx.service()
        if w:
            lines.append('%d %s' % (k, ' '.join('R%d=%d' % (r, x)
                                                 for _, r, x in w)))
    text = '\n'.join(lines) + '\n'
    if args.log:
        Path(args.log).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
