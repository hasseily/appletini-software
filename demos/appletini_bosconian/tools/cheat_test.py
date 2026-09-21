#!/usr/bin/env python3
"""Scripted play that reaches base destruction, round clear and game over.

Usage: python3 tools/cheat_test.py OUT_DIR [SECONDS]  (env: GSSQUARED_ROOT, DISK)

It boots dist/Appletini-Bosconian.hdv in GSSquared, starts a game, then
cheats through the debug protocol: every base but one is marked dead, the
ship is moved to the east of the last base, and the driver backs off and
approaches on the core's row, firing only while the open-core sprite
(id 34) is in the display list. Symbol addresses come from build/BOSCO.lbl.
It prints every state change and event and writes SHR screenshots to
OUT_DIR. Expected events: 5 (base destroyed), 7 (round clear), 1 (round 2
blast off) and, after the lives run out, 8 (game over).
"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
GAME = Path(__file__).resolve().parents[1]
GS2 = Path(os.environ.get('GSSQUARED_ROOT', GAME.parents[2] / 'gssquared')).resolve()
sys.path.insert(0, str(GAME/'tools')); sys.path.insert(0, str(GS2/'clients/python/src'))
import shr2png, gs2debug as gs2
OUT = Path(sys.argv[1]); SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 200; OUT.mkdir(parents=True, exist_ok=True)
DISK = os.environ.get('DISK', str(GAME / 'dist/Appletini-Bosconian.hdv'))
LBL = {}
for line in open(GAME/'build/BOSCO.lbl'):
    p = line.split()
    if len(p) == 3 and p[0] == 'al': LBL[p[2].lstrip('.')] = int(p[1], 16)
L = lambda n: LBL['_'+n]
KEY = {0:12, 2:15, 4:14, 6:13}   # i l k j
ST = {0:'BOOT',1:'TITLE',2:'PLAY',3:'DYING',4:'GAME_OVER',5:'ROUND_CLEAR',6:'PAUSED'}
def word(m,o): return m[o] | (m[o+1]<<8)
def wrap(d):
    d %= 1536
    return d-1536 if d >= 768 else d
sock = Path(tempfile.gettempdir())/f'gs2-core-{os.getpid()}.sock'
cmd = ['xvfb-run','-a',str(GS2/'build/GSSquared'),str(GAME/'appletini-bosconian.gs2'),f'-ds7d1={DISK}','--debug',str(sock),'--no-quit-confirm']
p = subprocess.Popen(cmd, cwd=GS2, env=dict(os.environ, SDL_AUDIODRIVER='dummy'), stdout=open(OUT/'emu.log','w'), stderr=subprocess.STDOUT)
c = gs2.Client(); t0 = time.monotonic()
while True:
    if sock.exists():
        try: c.connect(str(sock)); c.hello(); break
        except Exception: c.close()
    if time.monotonic()-t0 > 60: raise SystemExit('no socket')
    time.sleep(0.2)
def mb(): return c.read_mem(gs2.MEM_MAIN, 0x300, 41)
def shot(name):
    shr2png.convert(c.read_mem(gs2.MEM_MAIN_RAW, 0x12000, 0x8000), OUT/f'{name}.png', scale=2)
def rd16(a): m = c.read_mem(gs2.MEM_MAIN, a, 2); return m[0] | (m[1]<<8)
def wr16(a, v): c.write_mem(gs2.MEM_MAIN, a, bytes([v & 255, v >> 8]))
def core_open():
    n = c.read_mem(gs2.MEM_MAIN, L('dl_count'), 1)[0]
    items = c.read_mem(gs2.MEM_MAIN, L('dl_items'), 6*n) if n else b''
    return any(items[i*6] == 34 for i in range(n))
t0 = time.monotonic()
while mb()[:4] != b'A13B':
    if time.monotonic()-t0 > 60: raise SystemExit('no mailbox')
    time.sleep(0.2)
time.sleep(1.0); c.tap_key(40, hold_s=0.05)
t0 = time.monotonic()
while mb()[4] != 2:
    if time.monotonic()-t0 > 10: raise SystemExit('never reached PLAY')
    time.sleep(0.1)
last_state = None; seen = set(); t_start = time.monotonic(); placed = False; heading = None; fire = False; last_shot = 0
def set_heading(h):
    global heading
    if h != heading:
        c.key_up(44); c.tap_key(KEY[h], hold_s=0.05); heading = h
        if fire: c.key_down(44)
def set_fire(on):
    global fire
    if on != fire:
        fire = on
        if on: c.key_down(44)
        else: c.key_up(44)
while time.monotonic()-t_start < SECONDS:
    m = mb(); st = m[4]; frame = word(m,5)
    ev = m[35]
    if ev not in seen:
        seen.add(ev); print(f'frame {frame}: event {ev} state {ST.get(st)} score {int.from_bytes(m[7:11],"little")} bases_left {m[19]} round {m[11]}')
        if ev in (2,3,5,7): shot(f'event_{ev}_{frame:05d}')
    if st != last_state:
        print(f'frame {frame}: state {ST.get(st,st)} score {int.from_bytes(m[7:11],"little")} lives {m[12]} bases {m[19]} round {m[11]} writes {word(m,22)} max {word(m,24)} ev {ev}')
        shot(f'state_{frame:05d}_{ST.get(st,st)}'); last_state = st
        if st == 2: placed = False; heading = None
    if st == 2:
        n = c.read_mem(gs2.MEM_MAIN, L('base_count'), 1)[0]
        states = list(c.read_mem(gs2.MEM_MAIN, L('base_state'), 8))
        alive = [i for i in range(n) if states[i] == 1]
        if len(alive) > 1:
            c.write_mem(gs2.MEM_MAIN, L('base_state')+1, bytes([0]*(n-1))); print('cheat: only base 0 alive'); alive = [0]
        if not alive: time.sleep(0.1); continue
        b = alive[0]
        bx, by = rd16(L('base_x')+2*b), rd16(L('base_y')+2*b)
        if not placed:
            wr16(L('player_x'), (bx + 160) % 1536); wr16(L('player_y'), by)
            c.write_mem(gs2.MEM_MAIN, L('player_h'), bytes([6])); placed = True; heading = 6
            print(f'cheat: ship teleported east of base {b} at ({bx},{by})'); time.sleep(0.2); continue
        px, py = rd16(L('player_x')), rd16(L('player_y'))
        dx, dy = wrap(px - bx), wrap(py - by)        # ship relative to the core
        opened = core_open()
        # Closed core: hold 150..170 px east, where the near pods are off
        # screen and do not fire. Open core: run in firing (shot range 120),
        # then back out before touching the pods.
        if opened:
            if dx < 60: set_heading(2)
            elif dx > 126 or heading != 2: set_heading(6)
        else:
            if dx < 150: set_heading(2)
            elif dx > 170: set_heading(6)
        set_fire(opened and heading == 6 and dx <= 130)
        if opened and frame - last_shot > 120: shot(f'core_open_{frame:05d}'); last_shot = frame
    time.sleep(0.08)
m = mb(); print('final:', ST.get(m[4]), 'score', int.from_bytes(m[7:11],'little'), 'round', m[11], 'bases_left', m[19], 'events', sorted(seen), 'max writes', word(m,24))
shot('final'); c.quit(); c.close(); p.wait(timeout=10); print('done', OUT)
