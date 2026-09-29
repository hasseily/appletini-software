"""Run a list of bus operations on a2sim.py's Machine, for the tests of
tests/test_a2vm_machine.py that compare a2vm with it.

Run with the Python of build/venv (py65): it reads a JSON spec on stdin
and prints a JSON result. The spec:

  rom        the 16 KB ROM image
  speed      "turbo" or a number (a2sim.Machine's speed)
  amem       attach a2sim.FakeSmartPortMemory (with `amem_options`)
  files      null, or [name, type, aux, hex bytes] for a FakeProDOS
  loads      [kind, bank, address, hex bytes]: kind 0 main, 1 aux bank,
             2 the main language card (address $C000-$FFFF), 3 its bank 1
  switches   {name: value}: a2sim's sw names, lc_read, lc_write,
             lc_prewrite, lc_bank2, bank, newvideo
  registers  {pc, a, x, y, s, p}
  ops        in order: ["r", addr], ["w", addr, value], ["run", steps],
             ["hold", key], ["release"], ["press", key, cycle],
             ["mouse", dx, dy], ["mouse-to", x, y], ["buttons", l, r],
             ["button", n, value], ["clock", cycles]
  ram        where to write the RAM, in a2vm's snapshot layout

The result: {"reads": [the values of the "r" operations], "state": the
fields of a2vm's state (compare_a2sim.a2sim_state)}.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools' / 'a2vm'))
import compare_a2sim  # noqa: E402
import doom  # noqa: E402

sys.path.insert(0, str(doom.DOOM / 'tools'))
import a2sim  # noqa: E402


def main():
    spec = json.load(sys.stdin)
    prodos = None
    if spec.get('files') is not None:
        prodos = a2sim.FakeProDOS(volume='DOOM', launched='DOOM.SYSTEM')
        for name, file_type, aux, data in spec['files']:
            prodos.add(name, (file_type, aux, bytes.fromhex(data)))
    speed = spec.get('speed', 'turbo')
    if speed != 'turbo':
        speed = int(speed)
    m = a2sim.Machine(spec['rom'], speed=speed, prodos=prodos)
    if spec.get('amem'):
        m.smartport = a2sim.FakeSmartPortMemory(**spec.get('amem_options', {}))
    for kind, bank, address, data in spec.get('loads', []):
        data = bytes.fromhex(data)
        if kind == 0:
            m.main[address:address + len(data)] = data
        elif kind == 1:
            m.bank_memory(bank)[address:address + len(data)] = data
        elif kind == 2:
            m.lc[False][address - 0xc000:address - 0xc000 + len(data)] = data
        else:
            m.lc_bank1[False][address - 0xd000:address - 0xd000 + len(data)] = \
                data
    for name, value in spec.get('switches', {}).items():
        if name == 'bank':
            m.select_bank(value)
        elif name == 'newvideo':
            m.newvideo = value
        elif name in m.sw:
            m.sw[name] = bool(value)
        else:
            setattr(m, name, bool(value))
    mpu = m.mpu
    for name, value in spec.get('registers', {}).items():
        setattr(mpu, {'s': 'sp'}.get(name, name), value)
    reads = []
    for op in spec.get('ops', []):
        verb = op[0]
        if verb == 'r':
            reads.append(m[op[1]])
        elif verb == 'w':
            m[op[1]] = op[2]
        elif verb == 'run':
            for _ in range(op[1]):
                m.step()
        elif verb == 'hold':
            m.hold(op[1])
        elif verb == 'release':
            m.release()
        elif verb == 'press':
            m.press(chr(op[1] & 0x7f), at_cycle=op[2])
        elif verb == 'mouse':
            m.mouse_delta(op[1], op[2])
        elif verb == 'mouse-to':
            m.mouse_move(op[1], op[2])
        elif verb == 'buttons':
            m.mouse_buttons(bool(op[1]), bool(op[2]))
        elif verb == 'button':
            m.buttons[op[1]] = op[2]
        elif verb == 'clock':
            mpu.processorCycles = op[1]
        else:
            raise SystemExit('unknown operation %r' % (op,))
    Path(spec['ram']).write_bytes(b''.join(
        data for _, data in compare_a2sim.a2sim_ram(m)))
    json.dump(dict(reads=reads, state=compare_a2sim.a2sim_state(m)),
              sys.stdout)


if __name__ == '__main__':
    main()
