"""Exercise actual C bus decoding, card state and deterministic input timing."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "demos/doom_gs/tools/a2vm"
HARNESS = r'''
#include "a2vm.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "line %d: %s\n", __LINE__, #x); return 1; } } while (0)

static a2vm *machine(void) {
    a2vm_config c; a2vm_default_config(&c);
    c.core = A2VM_CORE_W65C02S; c.turbo = 0; c.speed = 13; c.io_cycles = 0;
    char error[256]; a2vm *m = a2vm_new(&c, error, sizeof error);
    if (!m) { fprintf(stderr, "%s\n", error); exit(2); }
    return m;
}

static int fourplay(void) {
    a2vm *m = machine();
    CHECK(a2vm_set_slot2(m, A2VM_SLOT2_FOUR_PLAY));
    for (int addr=0xc0a0; addr<=0xc0af; addr++) CHECK(a2vm_read(m, addr)==0x20);
    const unsigned masks[4] = {A2VM_PAD_B|A2VM_PAD_UP, A2VM_PAD_A|A2VM_PAD_DOWN,
                              A2VM_PAD_Y|A2VM_PAD_LEFT, A2VM_PAD_RIGHT};
    const unsigned expected[4] = {0xa1, 0x62, 0x34, 0x28};
    for (unsigned p=0; p<4; p++) CHECK(a2vm_set_pad(m,p,masks[p]));
    for (unsigned a=0; a<16; a++) {
        CHECK(a2vm_read(m,0xc0a0+a)==expected[a&3]);
        a2vm_write(m,0xc0a0+a,0xff);
        CHECK(a2vm_read(m,0xc0a0+a)==expected[a&3]);
    }
    const unsigned mapping[12] = {0x80,0x10,0,0,1,2,4,8,0x40,0,0,0};
    for (unsigned bit=0; bit<12; bit++) {
        CHECK(a2vm_set_pad(m,0,1u<<bit));
        CHECK(a2vm_read(m,0xc0a0)==(0x20|mapping[bit]));
    }
    CHECK(a2vm_set_pad(m,0,-1)); CHECK(a2vm_read(m,0xc0a0)==0x20);
    CHECK(a2vm_read(m,0xc090)==0);
    a2vm_free(m); return 0;
}

static int snes(void) {
    a2vm *m=machine(); CHECK(a2vm_set_slot2(m,A2VM_SLOT2_SNES_MAX));
    CHECK(a2vm_read(m,0xc0a0)==0xc0); /* no captured presence before latch */
    CHECK(a2vm_set_pad(m,0,0x555)); CHECK(a2vm_set_pad(m,1,0xaaa));
    a2vm_write(m,0xc0ae,0); /* an even alias latches */
    CHECK(a2vm_set_pad(m,0,-1)); CHECK(a2vm_set_pad(m,1,0));
    for (unsigned bit=0; bit<12; bit++) {
        unsigned expect=(bit&1)?0x80:0x40;
        for (unsigned a=0; a<16; a++) CHECK(a2vm_read(m,0xc0a0+a)==expect);
        a2vm_write(m,0xc0a1+2*(bit%8),0xff);
    }
    for (unsigned bit=12; bit<16; bit++) {
        CHECK(a2vm_read(m,0xc0a0)==0xc0); a2vm_write(m,0xc0af,0);
    }
    for (int i=0;i<20;i++) {
        CHECK(a2vm_read(m,0xc0a8)==0); a2vm_write(m,0xc0a3,0);
    }
    /* Latch now captures player 1 absent, player 2 connected and released. */
    a2vm_write(m,0xc0a4,0);
    for (int i=0;i<16;i++) { CHECK(a2vm_read(m,0xc0a0)==0xc0); a2vm_write(m,0xc0a1,0); }
    CHECK(a2vm_read(m,0xc0af)==0x80);
    /* One hot masks ensure the complete documented 12-bit serial order. */
    for (unsigned pressed=0;pressed<12;pressed++) {
        CHECK(a2vm_set_pad(m,0,1u<<pressed)); a2vm_write(m,0xc0a0,0);
        for (unsigned bit=0;bit<12;bit++) {
            CHECK(a2vm_read(m,0xc0a0)==(bit==pressed?0x40:0xc0));
            a2vm_write(m,0xc0a1,0);
        }
    }
    /* Re-selecting the current card does not destroy an in-flight latch. */
    a2vm_write(m,0xc0a0,0); a2vm_write(m,0xc0a1,0);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_SNES_MAX)); CHECK(m->snes_bit==1);
    a2vm_free(m); return 0;
}

static int mouse_modes(void) {
    a2vm *m=machine(); CHECK(m->slot2_mode==A2VM_SLOT2_MOUSE);
    CHECK(a2vm_read(m,0xc205)==0x38); CHECK(a2vm_read(m,0xc2fb)==0xd6);
    a2vm_write(m,0xc0ae,0x0f); /* enabled with move/button/VBL interrupts */
    a2vm_mouse_move(m,300,400); a2vm_mouse_buttons(m,1,0);
    CHECK(m->mouse.irq); CHECK(a2vm_read(m,0xc0a1)==(300&255));
    cpu65c02_set_irq(&m->cpu,1,1); cpu65c02_set_irq(&m->cpu,2,1);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_FOUR_PLAY));
    CHECK(!m->mouse_on && !m->mouse.irq && !m->mouse.mode);
    CHECK(m->cpu.irq_sources==2); /* another card's IRQ is not cleared */
    CHECK(a2vm_read(m,0xc205)==0); CHECK(a2vm_read(m,0xc0a0)==0x20);
    a2vm_write(m,0xc0ae,0xff); CHECK(!m->mouse.mode);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_OFF)); CHECK(a2vm_read(m,0xc0a0)==0);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_MOUSE));
    CHECK(m->mouse_on && !m->mouse.irq && !m->mouse.mode);
    CHECK(a2vm_read(m,0xc205)==0x38);
    a2vm_write(m,0xc0ae,1); a2vm_mouse_delta(m,9,11);
    CHECK(a2vm_read(m,0xc0a1)==9 && a2vm_read(m,0xc0a3)==11);
    a2vm_free(m);
    /* Existing plain/AppleMouse configurations retain their ROM flavor. */
    a2vm_config c; a2vm_default_config(&c); c.mouse=0; c.mouse_apple=1; c.io_cycles=0;
    char err[200]; m=a2vm_new(&c,err,sizeof err); CHECK(m);
    CHECK(a2vm_read(m,0xc200)==0x2c);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_SNES_MAX));
    CHECK(!m->mouse_apple && a2vm_read(m,0xc205)==0);
    CHECK(a2vm_set_slot2(m,A2VM_SLOT2_MOUSE));
    CHECK(m->mouse_apple && a2vm_read(m,0xc200)==0x2c);
    a2vm_free(m); return 0;
}

static int paddles(void) {
    a2vm *m=machine();
    for (unsigned p=0;p<4;p++) CHECK(m->paddle_values[p]==128 && m->paddles[p]==1412);
    const unsigned values[4]={0,1,128,255};
    for (unsigned p=0;p<4;p++) CHECK(a2vm_set_paddle(m,p,values[p]));
    a2vm_read(m,0xc070); CHECK(m->paddle_trigger==0);
    CHECK(a2vm_set_paddle(m,0,255)); /* existing timer retains its snapshot */
    for (unsigned p=0;p<4;p++) {
        unsigned delay=4+11*values[p];
        *m->clock=(delay-1)*13; CHECK(a2vm_read(m,0xc064+p)==0x80);
        CHECK(a2vm_read(m,0xc06c+p)==0x80);
        *m->clock=delay*13; CHECK(a2vm_read(m,0xc064+p)==0);
        CHECK(a2vm_read(m,0xc06c+p)==0);
    }
    for (unsigned a=0x70;a<=0x7f;a++) {
        uint64_t bus=10000+(a-0x70)*100;
        *m->clock=bus*13; a2vm_read(m,0xc000+a);
        CHECK(m->paddle_trigger==(int64_t)bus && m->paddles[0]==2809);
        *m->clock=(bus+1)*13; a2vm_write(m,0xc000+a,7);
        CHECK(m->paddle_trigger==(int64_t)(bus+1));
        if (a==0x71 || a==0x73) CHECK(m->bank==7);
    }
    a2vm_free(m); return 0;
}

static int buttons(void) {
    a2vm *m=machine(); m->buttons[1]=0x80;
    CHECK(a2vm_set_pad(m,2,A2VM_PAD_B|A2VM_PAD_Y));
    for (unsigned i=0;i<3;i++) {
        CHECK(a2vm_read(m,0xc061+i)==0x80); CHECK(a2vm_read(m,0xc069+i)==0x80);
    }
    CHECK(a2vm_set_pad(m,0,0)); /* lower connected index owns PBs */
    CHECK(a2vm_read(m,0xc061)==0 && a2vm_read(m,0xc062)==0x80 && a2vm_read(m,0xc063)==0);
    CHECK(a2vm_set_pad(m,0,-1)); CHECK(a2vm_read(m,0xc061)==0x80);
    CHECK(a2vm_set_pad(m,2,-1)); CHECK(a2vm_read(m,0xc061)==0);
    CHECK(a2vm_read(m,0xc062)==0x80); /* physical Apple key survives disconnect */
    a2vm_free(m); return 0;
}

static int keyboard(void) {
    a2vm *m=machine();
    for (unsigned i=0;i<1024;i++) {
        unsigned key=32+(i%64); a2vm_press(m,key,a2vm_now(m));
        CHECK(a2vm_read(m,0xc000)==(key|0x80));
        CHECK(a2vm_read(m,0xc000)==(key|0x80));
        a2vm_write(m,0xc010,0); CHECK(!m->key_count && !m->halt[0]);
    }
    a2vm_hold(m,'A'); CHECK(a2vm_read(m,0xc010)&0x80);
    CHECK(a2vm_read(m,0xc000)=='A'); a2vm_release(m); CHECK(!(a2vm_read(m,0xc010)&0x80));
    a2vm_press(m,'B',100); a2vm_press(m,'C',200);
    *m->clock=99; CHECK(!(a2vm_read(m,0xc000)&0x80));
    *m->clock=100; CHECK(a2vm_read(m,0xc000)==('B'|0x80)); a2vm_write(m,0xc010,0);
    *m->clock=199; CHECK(!(a2vm_read(m,0xc000)&0x80));
    *m->clock=200; CHECK(a2vm_read(m,0xc000)==('C'|0x80));
    a2vm_free(m); return 0;
}

static int invalid(void) {
    a2vm *m=machine();
    CHECK(!a2vm_set_slot2(NULL,0) && !a2vm_set_pad(NULL,0,0) && !a2vm_set_paddle(NULL,0,0));
    CHECK(!a2vm_set_slot2(m,-1) && !a2vm_set_slot2(m,4));
    CHECK(!a2vm_set_pad(m,4,0) && !a2vm_set_pad(m,0,-2) && !a2vm_set_pad(m,0,0x1000));
    CHECK(!a2vm_set_paddle(m,4,0) && !a2vm_set_paddle(m,0,256));
    CHECK(m->slot2_mode==A2VM_SLOT2_MOUSE && m->pad_present==0 && m->paddle_values[0]==128);
    m->vidhd.slot=2; CHECK(!a2vm_set_slot2(m,A2VM_SLOT2_FOUR_PLAY)); m->vidhd.slot=0;
    a2vm_free(m); return 0;
}

static int device_read(a2vm *m,uint16_t addr) { (void)m; return addr==0xc0f0 || addr==0xc700 ? 0xa5 : -1; }
static int device_write(a2vm *m,uint16_t addr,uint8_t value) {
    if (addr!=0xc0f0 && addr!=0xc700) return 0;
    *(unsigned *)m->device_context=value; return 1;
}
static int hooks_irq(void) {
    a2vm *m=machine(); unsigned value=0;
    m->device_context=&value; m->device_read=device_read; m->device_write=device_write;
    m->io_cycles=7; uint64_t c=a2vm_now(m),io=m->io_accesses;
    CHECK(a2vm_read(m,0xc0f0)==0xa5); CHECK(a2vm_now(m)==c+7 && m->io_accesses==io+1);
    a2vm_write(m,0xc700,42); CHECK(value==42 && a2vm_now(m)==c+14 && m->io_accesses==io+1);
    CHECK(a2vm_read(m,0xc700)==0xa5); CHECK(a2vm_now(m)==c+21);
    CHECK(a2vm_read(m,0xc205)==0x38); CHECK(a2vm_now(m)==c+28);
    CHECK(a2vm_read(m,0xc000)==0); CHECK(a2vm_now(m)==c+35 && m->io_accesses==io+2);
    m->io_cycles=0; m->cpu.pc=0x2000; m->cpu.p=0x20; m->main[0x2000]=0xea;
    m->rom[0x3ffe]=0; m->rom[0x3fff]=0x30; cpu65c02_set_irq(&m->cpu,2,1);
    a2vm_step(m); CHECK(m->irqs==1 && m->cpu.pc==0x3000 && (m->cpu.p&CPU65C02_I));
    a2vm_free(m); return 0;
}

static int service_events(void) {
    a2vm *m=machine();
    a2vm_write(m,0xc0ae,9); /* enable mouse VBL IRQ */
    m->cpu.pc=0x2000; m->cpu.p=0x20; m->rom[0x3ffe]=0; m->rom[0x3fff]=0x30;
    uint64_t due=m->next_vbl; *m->clock=due;
    a2vm_service_events(m);
    CHECK(m->mouse.vbl_pending && m->mouse.irq && (m->cpu.irq_sources&1));
    CHECK(m->instructions==0 && m->irqs==0 && a2vm_now(m)==due);
    CHECK(m->next_vbl==due+m->frame_cycles);
    a2vm_service_events(m);
    CHECK(m->instructions==0 && m->irqs==0 && m->next_vbl==due+m->frame_cycles);
    a2vm_step(m);
    CHECK(m->instructions==1 && m->irqs==1 && m->cpu.pc==0x3000);
    CHECK(m->next_vbl==due+m->frame_cycles);
    /* Large explicit clock jumps catch up once, rather than delivering
       another overdue frame on each repeated call at the same boundary. */
    *m->clock=due+3*m->frame_cycles;
    a2vm_service_events(m); uint64_t next=m->next_vbl;
    CHECK(next==due+4*m->frame_cycles);
    a2vm_service_events(m); CHECK(m->next_vbl==next && m->instructions==1);
    a2vm_free(m);

    m=machine(); m->via_timers=1;
    a2vm_write(m,0xc40e,0xc0); /* T1 interrupt enable */
    a2vm_write(m,0xc404,2); a2vm_write(m,0xc405,0);
    CHECK(m->phasor.t1_clock==4*13);
    *m->clock=m->phasor.t1_clock;
    cpu65c02_set_irq(&m->cpu,2,1); /* external source survives service */
    a2vm_service_events(m);
    CHECK((m->phasor.t1[0].ifr&0x40) && m->cpu.irq_sources==3);
    CHECK(m->instructions==0 && m->irqs==0);
    a2vm_read(m,0xc404); /* clear T1's flag */
    a2vm_service_events(m); CHECK(m->cpu.irq_sources==2);
    a2vm_free(m); return 0;
}

int main(int argc,char **argv) {
    if (argc!=2) return 2;
    if (!strcmp(argv[1],"fourplay")) return fourplay();
    if (!strcmp(argv[1],"snes")) return snes();
    if (!strcmp(argv[1],"mouse")) return mouse_modes();
    if (!strcmp(argv[1],"paddles")) return paddles();
    if (!strcmp(argv[1],"buttons")) return buttons();
    if (!strcmp(argv[1],"keyboard")) return keyboard();
    if (!strcmp(argv[1],"invalid")) return invalid();
    if (!strcmp(argv[1],"hooks")) return hooks_irq();
    if (!strcmp(argv[1],"events")) return service_events();
    return 2;
}
'''


class AppletiniInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("cc")
        if not compiler:
            raise unittest.SkipTest("C compiler required for actual machine tests")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        source = Path(cls.temp.name) / "inputs.c"
        source.write_text(HARNESS)
        cls.binary = Path(cls.temp.name) / "inputs"
        subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic",
                        "-I", str(CORE), str(source),
                        *[str(CORE / name) for name in ("a2vm.c", "cost.c", "prodos.c", "cpu65c02.c")],
                        "-o", str(cls.binary)], check=True, capture_output=True, text=True)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fourplay_all_players_aliases_and_buttons(self): self.run_case("fourplay")
    def test_snes_latch_serial_order_presence_and_aliases(self): self.run_case("snes")
    def test_exclusive_card_selection_and_mouse_regression(self): self.run_case("mouse")
    def test_paddle_snapshot_timing_and_bank_switch_aliases(self): self.run_case("paddles")
    def test_gamepad_pushbuttons_and_physical_apple_keys(self): self.run_case("buttons")
    def test_keyboard_more_than_256_taps_and_scheduled_input(self): self.run_case("keyboard")
    def test_invalid_inputs_do_not_mutate_state(self): self.run_case("invalid")
    def test_external_device_hooks_accounting_and_irq(self): self.run_case("hooks")
    def test_events_precede_traps_without_advancing_or_double_delivery(self): self.run_case("events")


if __name__ == "__main__":
    unittest.main()
