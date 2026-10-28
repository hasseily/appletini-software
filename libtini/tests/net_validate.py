"""Run the actual cc65 API and RAM copy loop against a guarded controller."""
import argparse
import json
from storage_validate import ROOT, build_target, CpuRun, read_labels
from amem_validate import Controller as BaseController

class Controller(BaseController):
    def __init__(self, mode):
        super().__init__(1 if mode == 1 else 0)
        self.net_mode = mode
        self.generation = 17
        self.vbl_reads = 0
        self.sticky_ready = True  # a completed boot-ROM response leaves READY set

    def __getitem__(self, address):
        if address == 0xCFF1:
            self.guard()
            return 0x80 if self.sticky_ready else 0
        return super().__getitem__(address)

    def _read_io(self, address):
        if address == 0xC019:
            self.vbl_reads += 1
            return (self.vbl_reads // 64 & 1) * 128
        return super()._read_io(address)

    def submit(self, data):
        assert data[1:5] == bytes((3,0,0,0)), data
        self.at = 0
        self.sticky_ready = True
        selector = data[5]
        if data[0] == 4:
            assert selector == 0x82
            size = int.from_bytes(data[10:12], 'little')
            assert len(data) == 12 + size
            p = data[12:]
            assert p[0] == 1 and p[10:12] == bytes(2)
            if p[1] == 1:
                assert p[2:4] == bytes((1,4))
                m,u,h,b = p[3],int.from_bytes(p[4:6],'little'),int.from_bytes(p[6:8],'little'),int.from_bytes(p[8:10],'little')
                assert p[12:12+m] == b'POST'
                assert p[12+m:12+m+u] == b'https://example.test/a'
                assert p[12+m+u:12+m+u+h] == b'Content-Type: application/json\r\n'
                assert p[12+m+u+h:] == bytes(range(8)) and b == 8
                self.generation += 1
            elif p[1] == 3:
                assert p[12:] == b'/scores/0/name'
            else:
                assert p[1] == 2 and len(p) == 12
            self.controls.append(data)
            self.response = [0]
            return
        assert data[0] == 0 and len(data) == 10
        if self.net_mode == 4:
            self.sticky_ready = False
            self.response = []
            return
        if selector == 0x82:
            p = bytearray(64)
            p[:7] = b'ATNH' + bytes((1,64,15))
            if self.net_mode == 2: p[4] = 99
            p[7] = self.generation + (self.net_mode == 5 and bool(self.controls))
            p[8] = 3; p[9] = 1; p[12:14] = (200).to_bytes(2,'little')
            if self.net_mode == 6:
                p[8] = 4; p[10:12] = (-111).to_bytes(2,'little',signed=True); p[12:14] = bytes(2)
            p[16:20] = (32768).to_bytes(4,'little')
            p[28:30] = (22).to_bytes(2,'little')
            p[44:48] = (1017812).to_bytes(4,'little')
            self.response = [0,0xFF,0xFF] if self.net_mode == 3 else [0,len(p),0,*p]
        else:
            assert selector in (0x83,0x84)
            offset = int.from_bytes(data[6:8],'little')
            cap = int.from_bytes(data[8:10],'little')
            assert 9 <= cap <= 512
            payload = b'ACE' if selector == 0x84 else bytes((offset+i)&255 for i in range(cap-8))
            p = bytes((self.generation,2 if selector == 0x84 else 1)) + offset.to_bytes(4,'little') + len(payload).to_bytes(2,'little') + payload
            self.response = [0,len(p)&255,len(p)>>8,*p]

class Run(CpuRun):
    def observe(self):
        if self.started:
            if not getattr(self,"dirty_scratch",False):
                for at in range(self.labels["_ti_net_parameters"],self.labels["_ti_net_rx"]+2):self.memory.main[at]=0xA5
                self.dirty_scratch=True
            self.memory.main[self.labels['_net_mode']] = self.mode

def main():
    p = argparse.ArgumentParser(); p.add_argument('--cc65-home',required=True); a = p.parse_args()
    out, program, labels = build_target('net',a.cc65_home,
        ['src/memory.c','src/memory_copy.c','src/timing.c','src/timing_gap.c','src/net.c','tests/net_target.c'],
        ['src/target/memory.s','src/target/hardware.s','src/target/private_state.s','src/target/net.s'])
    symbols=read_labels(labels)
    # Persistent flags must live in the startup-cleared near segment.
    near=symbols["__NEARBSS_RUN__"];end=near+symbols["__NEARBSS_SIZE__"]
    assert all(near<=symbols[n]<end for n in ("_ti_net_poisoned","_ti_net_ready"))
    results=[]
    for mode in range(7):
        model=Controller(mode); run=Run(program,labels,model);run.mode=mode
        # Real boot RAM is not zero. Startup must clear the resident flags.
        for at in range(near,end):run.memory.main[at]=0xA5
        run.run(30_000_000)
        assert run.quit and not run.value('_net_failed'), (mode,run.value('_net_failed'))
        assert model.intcxrom and model.selected is None
        assert not model.cpu.p&4, 'IRQ mask leaked'
        if mode == 0: assert len(model.controls) == 3
        elif mode == 6: assert len(model.controls) == 1
        elif mode != 5: assert not model.controls
        results.append(dict(mode=mode,checks=run.value('_net_checks'),instructions=run.steps,controls=len(model.controls)))
        print('PASS NET',results[-1],flush=True)
    (out/'validation.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__ == '__main__': main()
