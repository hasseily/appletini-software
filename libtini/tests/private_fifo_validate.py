"""A failed NET or AMEM reply must block the other client on the shared FIFO."""
import argparse,json
from storage_validate import build_target,CpuRun,read_labels
from net_validate import Controller as NetController
from amem_validate import Controller as AmemController
class Run(CpuRun):
    def observe(self):
        if self.started:self.memory.main[self.labels['_fifo_mode']]=self.mode
def main():
    p=argparse.ArgumentParser();p.add_argument('--cc65-home',required=True);a=p.parse_args()
    out,program,labels=build_target('private_fifo',a.cc65_home,
      ['src/memory.c','src/memory_copy.c','src/timing.c','src/timing_gap.c','src/net.c','src/amem.c','tests/private_fifo_target.c'],
      ['src/target/memory.s','src/target/hardware.s','src/target/net.s','src/target/private_state.s','src/optional/amem_transport.s'],True)
    syms=read_labels(labels);assert syms['_ti_net_poisoned']==syms['_ti_private_poisoned']
    rows=[]
    for mode,model in enumerate((NetController(3),AmemController(9))):
        run=Run(program,labels,model);run.mode=mode;run.run()
        assert run.quit and not run.value('_fifo_failed',1)
        assert len(model.requests)==1 and model.intcxrom and model.selected is None
        rows.append({'first_client':'NET' if mode==0 else 'AMEM','commands':1,'other_client_blocked':True})
    (out/'validation.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('PASS failed NET blocks AMEM; failed AMEM blocks NET; no second FIFO command')
if __name__=='__main__':main()
