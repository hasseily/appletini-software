#!/usr/bin/env python3
"""Scripted play that reaches base destruction, round clear and game over.

Usage: python3 tools/cheat_test.py OUT_DIR [SECONDS]  (env: GSSQUARED_ROOT, DISK)

It boots dist/Appletini-Bosconian.hdv in GSSquared, starts a game, then
cheats through the debug protocol: every base but one is marked dead, the
ship is moved onto the last base's axis (east of a horizontal base, south
of a vertical one), and the driver runs in firing along the axis, where the
core's tube is open, then backs off before touching the cannons. Symbol
addresses come from build/BOSCO.lbl.
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
KEY = {0:12, 2:15, 4:14, 6:13, 1:18, 3:54, 5:16, 7:24}   # i l k j, diagonals o , m u
ST = {0:'BOOT',1:'TITLE',2:'PLAY',3:'DYING',4:'GAME_OVER',5:'ROUND_CLEAR',6:'PAUSED'}
def word(m,o): return m[o] | (m[o+1]<<8)
def wrap(d, size):
    d %= size
    return d-size if d >= size//2 else d
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
def shot_closing_in():
    n = c.read_mem(gs2.MEM_MAIN, L('dl_count'), 1)[0]
    items = c.read_mem(gs2.MEM_MAIN, L('dl_items'), 6*n) if n else b''
    for i in range(n):
        it = items[i*6:i*6+6]
        if it[0] != 80: continue
        x = it[1] | it[2]<<8; y = it[3] | it[4]<<8
        x = x-0x10000 if x >= 0x8000 else x; y = y-0x10000 if y >= 0x8000 else y
        if abs(x+2-128) <= 56 and abs(y+2-100) <= 56: return True
    return False
def wr16(a, v): c.write_mem(gs2.MEM_MAIN, a, bytes([v & 255, v >> 8]))
t0 = time.monotonic()
while mb()[:4] != b'A13B':
    if time.monotonic()-t0 > 60: raise SystemExit('no mailbox')
    time.sleep(0.2)
time.sleep(1.0); c.tap_key(40, hold_s=0.05)
t0 = time.monotonic()
while mb()[4] != 2:
    if time.monotonic()-t0 > 10: raise SystemExit('never reached PLAY')
    time.sleep(0.1)
last_state = None; seen = set(); t_start = time.monotonic(); placed = False; heading = None; fire = False; last_shot = 0; dodge = []
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
        hz = c.read_mem(gs2.MEM_MAIN, L('base_hz')+b, 1)[0]
        # along the base's axis: east of a horizontal base (heading 6 = W
        # attacks, 2 = E retreats), south of a vertical one (0 = N, 4 = S)
        toward, away = (6, 2) if hz else (0, 4)
        if not placed:
            if hz: wr16(L('player_x'), (bx + 160) % 1024); wr16(L('player_y'), by)
            else: wr16(L('player_x'), bx); wr16(L('player_y'), (by + 160) % 1792)
            c.write_mem(gs2.MEM_MAIN, L('player_h'), bytes([toward])); placed = True; heading = toward
            print(f'cheat: ship teleported {"east" if hz else "south"} of base {b} at ({bx},{by})'); time.sleep(0.2); continue
        px, py = rd16(L('player_x')), rd16(L('player_y'))
        d = wrap(px - bx, 1024) if hz else wrap(py - by, 1792)   # ship along the axis from the core
        # run in firing (shot range 120; the axis cannon goes first, then the
        # core), then back out before touching the cannons; a cannon shot
        # that comes close is dodged with a diagonal sidestep of 10 frames
        # (15 px), held for 10 frames while the shot passes, then 10 frames
        # back onto the axis (timed by the game's frame counter, so the
        # host's emulation speed does not matter)
        while dodge and frame >= dodge[0][1]: dodge.pop(0)
        if dodge: set_heading(dodge[0][0])
        elif d < 60: set_heading(away)
        elif shot_closing_in() and heading == toward:
            dodge = [((toward+1) & 7, frame+10), (toward, frame+20), ((toward-1) & 7, frame+30)]; set_heading(dodge[0][0])
        elif d > 126 or heading != toward: set_heading(toward)
        set_fire(heading == toward and d <= 130 and not dodge)
        if frame - last_shot > 120: shot(f'attack_{frame:05d}'); last_shot = frame
    time.sleep(0.08)
m = mb(); print('final:', ST.get(m[4]), 'score', int.from_bytes(m[7:11],'little'), 'round', m[11], 'bases_left', m[19], 'events', sorted(seen), 'max writes', word(m,24))
shot('final'); c.quit(); c.close(); p.wait(timeout=10); print('done', OUT)
