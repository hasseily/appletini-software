#!/usr/bin/env python3
"""The placement of the tic phase's code (milestone 10, docs/GAME.md 4.3):
each routine of the part table in the core or in a group of a slot, from
the heat, the call graph with its call counts and the sizes.

Usage:  python3 tools/native/gplace.py [--write] [--sizes FILE]
                                       [--runs demo3,demo1,demo2]

Inputs:
  heat      the instructions each routine runs: ref816's trace of demo3
            (build/a2vm/interp/demo.trace, PROFILE.md's: 40 frames), each
            executed address given to the head that holds it
            (gamecap.CallerMap); after wave 1 the gprof build's counts
            (--heat FILE: {"file:label": instructions})
  calls     the survey (gamecap.py, build/native/game/shared/survey/):
            each routine's calls a tic and its callers; the call graph's
            edges (gcallgraph.py) where the survey saw no call
  sizes     native bytes: --sizes FILE ({"file:label": bytes}, the parts'
            measured sizes, make -f game.mk sizes), else the estimate
            upstream's bytes x 1.3 (2.4's budgets)

The rules (4.3): the core takes the routines A_Chase, P_NewChaseDir, pMove
and P_TryWalk first, then the others by heat a byte until its room (the
core image's 13,312 B less the runtime and milestone 9's core as the
skeleton's image measures them) is full; the rest form groups (routines
connected by calls outside the core, cut in call order at slot 2's
2,048 B less GROUP_MARGIN so that either slot holds each (the core's room
less CORE_MARGIN: the planted bugs' copies link in the same placement); then merged by their calls and
packed, fewer than gcall.s's 64), each with a home slot; the homes are chosen to make the
counted cost of same-slot calls least (a load is the group's bytes at
0.246 us a byte plus 4 us a window; a call between two groups of one
slot costs both loads), and the groups of A_Chase's callees never share
A_Chase's slot (when A_Chase is not in the core), nor the groups of an
APART pair (path's traverseTo and the TRVTAB traversers) one slot. The report lists every
pair of groups of one slot with more than one call between them a tic at
the median.

--write puts the placement in build/native/game/shared/placement.json,
which glayout.py's gplace.inc and game.cfg follow (the integrator's step:
parts never write it).
"""

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from native import glayout as GL  # noqa: E402

ROOT = HERE.parent.parent
BUILD = ROOT / 'build'
TRACE = BUILD / 'a2vm' / 'interp' / 'demo.trace'
PLACEMENT = GL.SHARED / 'placement.json'
GROWTH = 1.3                    # native bytes a byte of upstream (2.4)
BYTE_US = 0.246                 # a byte loaded (NATIVE.md 4.3)
WINDOW_US = 4.0                 # a window (NATIVE.md 1.2: 3-5 us)
CHASE = 'p_enemy65.s:A_Chase'
EXHAUSTIVE = 22                 # at most this many moves: try every slot
# (wave 6 as integrated) room left in every group and in the core for the
# parts' planted bugs, whose copies link in the same placement: with the
# groups packed to 2,048 B and the core to 5 B of its end, a plant that adds
# bytes no longer linked (spawn's puff-z-random-after-tics +47 B in its
# group, sight's plants +8 B in the core)
GROUP_MARGIN = 64
CORE_MARGIN = 16
# (wave 5 as integrated: natively P_NewChaseDir and P_TryWalk are 7 B
# wrappers the release never calls; A_Chase calls newChaseDir, which
# calls doNewChaseDir, and tryWalk: chasemove.md R2)
CORE_FIRST = ('p_enemy65.s:A_Chase', 'p_enemy65.s:newChaseDir',
              'p_enemy65.s:doNewChaseDir', 'p_enemy65.s:pMove',
              'p_enemy65.s:tryWalk',
              # wave 2 as integrated: weaponinfo's two lookups, 19 B, called
              # by pspr's routines every tic (docs/game-parts/damage.md R7)
              'p_pspr65.s:wInfo', 'p_pspr65.s:wInfoOf')
SKELETON_ONLY = ('gtest', 'grec')   # the test image's own modules
# APART: pairs of routines whose groups never share a slot (as A_Chase's
# rule): path's traverseTo calls the trace's traverser (TRVTAB) for every
# intercept, a call the survey does not see (upstream's jml), so in one
# slot each intercept would reload both groups (wave 5 as integrated:
# attack.md R4)
APART = tuple(('p_path65.s:traverseTo', t)
              for t in GL.DISPATCH['TRVTAB']['targets']) + (
    # wave 6 as integrated: the door thinker and the planes' unit do not
    # fit one group (1,240 B and 1,228 B); in opposite slots a moving door
    # or plat loads each at most once besides the walk's reload (movers.md
    # request 2)
    ('p_doors65.s:T_VerticalDoor', 'p_floor65.s:T_MovePlaneCeiling'),)
# The integrator's decisions from the parts' measurements (docs/GAME.md
# "Wave 1 as integrated"):
# PINNED: in the core before anything else. P_CheckSight's walk pages its
# own routines up to 21 times a call when they are apart (docs/game-parts/
# sight.md R5: 5 group loads at the median of a call that sees, 203,071
# cycles against 52,473 with none), and sight is 40% of the game's
# instructions (GAME.md 0.3 fact 7)
PINNED = ('p_sight65.s:P_CheckSight', 'p_sight65.s:zSetup',
          'p_sight65.s:sightSlope', 'p_sight65.s:interceptFrac',
          'p_sight65.s:opening', 'p_sight65.s:smul48')
# AFFINITY: routines kept in one group (or all in the core), callers and
# callees whose calls would reload a slot twice when apart (geom.md R8,
# mobjstate.md R8, secfind.md request 10; wave 2's below)
AFFINITY = (
    ('p_map65.s:P_LineOpening', 'p_map65.s:P_LineOpeningXY'),
    ('p_map65.s:sectorFloor', 'p_map65.s:pointSector', 'p_map65.s:baseLite',
     'p_map65.s:baseFloor', 'p_map65.s:baseFloorL'),
    ('p_map65.s:P_PointOnLineSide', 'p_map65.s:posMul'),
    ('p_map65.s:unlist', 'p_map65.s:link', 'p_map65.s:blockOf',
     'p_map65.s:mvSector', 'p_map65.s:mvBlock',
     'p_map65.s:P_UnsetThingPosition', 'p_map65.s:P_DelSeclist',
     'p_map65.s:P_DelSecnode', 'p_spawn65.s:P_RemoveMobj',
     'r_list65.s:linkRemove', 'p_think65.s:P_RemoveThing'),
    ('p_think65.s:P_RemoveThingDelayed', 'p_think65.s:P_RemoveThinkerDelayed',
     'p_think65.s:unlink', 'p_spawn65.s:poolFree'),
    ('p_tick65.s:P_SetMobjState', 'p_tick65.s:rocketCheat',
     'p_mobj65.s:explode'),
    ('p_lights65.s:nextSector', 'p_spec65.s:around',
     'p_spec65.s:P_FindLowestFloorSurrounding',
     'p_spec65.s:P_FindHighestFloorSurrounding',
     'p_spec65.s:P_FindLowestCeilingSurrounding',
     'p_floor65.s:P_FindNextHighestFloor', 'p_lights65.s:EV_LightTurnOn',
     'p_spec65.s:P_FindSectorFromLineTag'),
    # wave 2 as integrated (docs/GAME.md): a crossed line's intercept
    # (tracel.md R2: 1,721 B; the long trace's vertex sides apart, so that
    # either fits slot 2), SIDE1's setup helpers with tracet's sideSetup to
    # come
    ('p_trace65.s:PIT_AddLineIntercepts', 'p_trace65.s:lineCross',
     'p_trace65.s:ivAxis', 'p_trace65.s:interceptVector3',
     'p_trace65.s:ivTest', 'p_trace65.s:ivProd', 'p_trace65.s:addIntercept',
     'p_trace65.s:icInsert'),
    ('p_trace65.s:vtxSlow', 'p_trace65.s:divlineSide',
     'p_trace65.s:vtxSlowR'),
    ('p_trace65.s:ivSetup', 'p_trace65.s:gOf', 'p_trace65.s:smul',
     'p_trace65.s:vsC', 'p_trace65.s:sideSetup', 'p_trace65.s:longTrace'),
    # the damage (damage.md R7)
    ('p_inter65.s:P_DamageMobj', 'p_inter65.s:thrust',
     'p_inter65.s:playerDamage', 'p_inter65.s:setState',
     'p_inter65.s:lastEnemy', 'p_inter65.s:killMobj'),
    # the pickups and the cheats (pickup.md P3)
    ('p_inter65.s:P_TouchSpecialThing', 'p_inter65.s:pkArmor',
     'p_inter65.s:pkHealthBonus', 'p_inter65.s:pkSoul',
     'p_inter65.s:pkArmorBonus', 'p_inter65.s:pkCard',
     'p_inter65.s:pkBody', 'p_inter65.s:pkPower', 'p_inter65.s:pkClip',
     'p_inter65.s:pkAmmo', 'p_inter65.s:pkBackpack',
     'p_inter65.s:pkWeapon', 'p_inter65.s:giveBody',
     'p_inter65.s:giveAmmo', 'p_inter65.s:giveWeapon',
     'p_inter65.s:givePower', 'p_inter65.s:P_GivePower'),
    ('m_cheat65.s:C_Responder', 'm_cheat65.s:power',
     'm_cheat65.s:giveAmmo'),
    # the special lines (lines.md request 4)
    ('p_switch65.s:findSpecial', 'p_spec65.s:P_CheckTag',
     'p_switch65.s:P_UseSpecialLine', 'p_switch65.s:P_CrossSpecialLine'),
    # the height move and the puffs (spawn.md request 2)
    ('p_mobj65.s:P_ZMovement', 'p_mobj65.s:missileHit', 'p_mobj65.s:shr3',
     'p_mobj65.s:isPlayer'),
    ('p_spawn65.s:P_SpawnPuff', 'p_spawn65.s:P_SpawnBlood',
     'p_spawn65.s:zNoise', 'p_spawn65.s:spawnXYZ',
     'p_spawn65.s:ticsNoise', 'p_attack65.s:P_IsAttackRangeMeleeRange'),
    # wave 3 as integrated (docs/GAME.md): the block steps' every line and
    # thing with SIDE1's copy (tracet.md R2; sideSetup and longTrace join
    # ivSetup's unit above)
    ('p_trace65.s:traceLines', 'p_trace65.s:traceThings',
     'p_trace65.s:thFast', 'p_trace65.s:thSide'),
    # the position check but PIT_CheckThing (cold) (checkpos.md R2: the
    # seven pass slot 2's 2,048 B)
    ('p_map65.s:P_CheckPosition', 'p_map65.s:checkPos', 'p_map65.s:cpCopy',
     'p_map65.s:setBox', 'p_map65.s:walkRange', 'p_map65.s:lineBlocks'),
    # the weapon's routines of every tic (pspr.md R6)
    ('p_pspr65.s:P_MovePsprites', 'p_pspr65.s:tickPsprite',
     'p_pspr65.s:A_WeaponReady', 'p_pspr65.s:signExt4',
     'p_pspr65.s:signExt0', 'p_pspr65.s:setMoState',
     'p_pspr65.s:startSound', 'p_pspr65.s:A_ReFire', 'p_pspr65.s:A_Lower',
     'p_pspr65.s:A_GunFlash', 'p_pspr65.s:fireSomething',
     'p_pspr65.s:A_Light0', 'p_pspr65.s:A_Light1', 'p_pspr65.s:A_Light2',
     'p_pspr65.s:fireWeapon', 'p_pspr65.s:checkAmmo',
     'p_pspr65.s:P_CheckAmmo'),
    # the doors and plats a line starts (evworld.md request 2): each
    # handler with the routine it calls, newDoor with its two callers
    ('p_switch65.s:lnDoor', 'p_doors65.s:EV_DoDoor', 'p_doors65.s:newDoor',
     'p_switch65.s:lnVDoor', 'p_doors65.s:EV_VerticalDoor',
     'p_switch65.s:lnPlat', 'p_plats65.s:EV_DoPlat'),
    # the look, its ranges and the face (look.md request 3); the sounds
    # and the fall; the radius attack
    ('p_enemy65.s:A_Look', 'p_enemy65.s:lookForPlayers',
     'p_enemy65.s:behindFast', 'p_enemy65.s:angleToAT',
     'p_enemy65.s:distanceAT', 'p_enemy65.s:loadTarget',
     'p_enemy65.s:checkMeleeRange', 'p_enemy65.s:checkMissileRange',
     'p_enemy65.s:P_CheckMeleeRange', 'p_enemy65.s:P_CheckMissileRange',
     'p_enemy65.s:faceTarget', 'p_enemy65.s:A_FaceTarget'),
    ('p_enemy65.s:A_Scream', 'p_enemy65.s:A_XScream', 'p_enemy65.s:A_Pain',
     'p_enemy65.s:A_Fall', 'p_enemy65.s:A_PlayerScream',
     'p_enemy65.s:randMod', 'p_enemy65.s:startSound'),
    ('p_attack65.s:P_RadiusAttack', 'p_attack65.s:PIT_RadiusAttack'),
    # wave 4 as integrated (docs/GAME.md): the walk of a trace, whose block
    # loop calls early and early traverseTo at every block step (path.md
    # R4: 1,357 B)
    ('p_path65.s:P_PathTraverse', 'p_path65.s:ptBody',
     'p_path65.s:early', 'p_path65.s:traverseTo', 'p_path65.s:offLine',
     'p_path65.s:axisStep', 'p_path65.s:fromOrigin', 'p_path65.s:a1Shr7',
     'p_path65.s:ptStuck'),
    # the move with its caller of every tic (trymove.md R3: P_XYMovement
    # calls P_TryMove 2.9 times a tic at the median; part xymove's wave
    # may revise it with its measured sizes)
    # (wave 5: with the slide's own move, xymove.md R1)
    ('p_mobj65.s:P_XYMovement', 'p_map65.s:P_TryMove',
     'p_mobj65.s:slideMove'),
    # the plane movers with the sector check and the floor thinker
    # (planes.md request 2): T_MovePlaneFloor and T_MovePlaneCeiling share
    # their local code (planes.s asserts one group)
    ('p_floor65.s:T_MoveFloor', 'p_floor65.s:T_MovePlaneFloor',
     'p_floor65.s:T_MovePlaneCeiling', 'p_floor65.s:checkSector',
     'p_floor65.s:changeSector', 'p_floor65.s:heightClip'),
    # the floors, stairs and donut a line starts (evfloor.md request 2):
    # each handler with its routine, the helper routines with them
    ('p_switch65.s:lnFloor', 'p_floor65.s:EV_DoFloor',
     'p_floor65.s:newFloor', 'p_floor65.s:floorUp', 'p_floor65.s:setDest',
     'p_floor65.s:halfSpeed', 'p_switch65.s:lnStairs',
     'p_floor65.s:EV_BuildStairs', 'p_floor65.s:stairStep',
     'p_floor65.s:nextStep', 'p_switch65.s:lnDonut',
     'p_floor65.s:EV_DoDonut'),
    # the teleport (teleport.md R2: cold, one group)
    ('p_switch65.s:lnTele', 'p_telept65.s:EV_Teleport',
     'p_telept65.s:fogSound', 'p_telept65.s:times20',
     'p_telept65.s:destination', 'p_map65.s:P_TeleportMove',
     'p_map65.s:stompThing', 'p_map65.s:farFrom'),
    # wave 5 as integrated (docs/GAME.md): the shot's and the aim's
    # traversers with their helper routines, in the slot other than path's
    # walk, and the two entries (attack.md R4: 1,806 B and 358 B)
    ('p_attack65.s:PTR_AimTraverse', 'p_attack65.s:PTR_ShootTraverse',
     'p_attack65.s:shootSpecial', 'p_attack65.s:puffPos',
     'p_attack65.s:mul3', 'p_attack65.s:rangeMul'),
    ('p_attack65.s:P_LineAttack', 'p_attack65.s:P_AimLineAttack'),
    # the player's think of every tic, the use, the special floors
    # (player.md R3: 1,957 B, 600 B, 207 B)
    ('p_user65.s:P_PlayerThink', 'p_user65.s:movePlayer',
     'p_user65.s:calcHeight', 'p_user65.s:fixedSquare',
     'p_user65.s:onGround', 'p_user65.s:thrustMul',
     'p_user65.s:angleToAttacker'),
    ('p_use65.s:P_UseLines', 'p_use65.s:PTR_UseTraverse',
     'p_use65.s:PTR_NoWayTraverse', 'p_use65.s:times64'),
    ('p_user65.s:specialSector', 'p_user65.s:hurt32'),
    # the move's helpers, one group apart from P_XYMovement's; the
    # player's slide: its traces and clip with their traverser (xymove.md
    # R1: 445 B, 1,023 B)
    ('p_mobj65.s:clampMove', 'p_mobj65.s:slow', 'p_mobj65.s:frictionAP',
     'p_mobj65.s:frictionNear', 'p_mobj65.s:friction',
     'p_mobj65.s:quarterOut', 'p_mobj65.s:skyHit'),
    ('p_mobj65.s:slideTrace', 'p_mobj65.s:bobClip', 'p_mobj65.s:bestMul',
     'p_mobj65.s:labs', 'p_mobj65.s:PTR_SlideTraverse',
     'p_mobj65.s:hitSlideLine'),
    # the missiles' spawners and the helpers they share (missile.md R2:
    # 714 B without wfire's P_SpawnPlayerMissile)
    ('p_spawn65.s:P_SpawnMissile', 'p_spawn65.s:srcAbove',
     'p_spawn65.s:seeTarget', 'p_spawn65.s:thSpeed',
     'p_spawn65.s:angleMom', 'p_spawn65.s:halfMom',
     'p_spawn65.s:P_SpawnPlayerMissile',
     # wave 6: the rocket launcher's action with its spawner (wfire.md R2)
     'p_pspr65.s:A_FireMissile'),
    # the chase's move and direction; the drop-off with its callback
    # (chasemove.md R2: 1,467 B, 822 B)
    ('p_enemy65.s:pMove', 'p_enemy65.s:tryWalk', 'p_enemy65.s:newChaseDir',
     'p_enemy65.s:doNewChaseDir', 'p_enemy65.s:P_NewChaseDir',
     'p_enemy65.s:P_TryWalk'),
    ('p_enemy65.s:avoidDropoff', 'p_enemy65.s:PIT_AvoidDropoff'),
    # wave 6 as integrated (docs/GAME.md): the door and plat thinkers with
    # the door's light, which runs at every door move (movers.md request
    # 2: 1,240 B)
    ('p_doors65.s:T_VerticalDoor', 'p_doors65.s:partLight',
     'p_doors65.s:mulExt', 'p_plats65.s:T_PlatRaise'),
    # the player's weapons: a pistol shot pages A_FirePistol, useAmmo,
    # bulletSlope, gunShot, randMod and spread, a shotgun shot gunShot
    # seven times (wfire.md R2: 1,096 B)
    ('p_pspr65.s:A_FirePistol', 'p_pspr65.s:A_FireShotgun',
     'p_pspr65.s:A_FireCGun', 'p_pspr65.s:bulletSlope',
     'p_pspr65.s:gunShot', 'p_pspr65.s:spread', 'p_pspr65.s:randMod',
     'p_pspr65.s:useAmmo', 'p_pspr65.s:A_Punch', 'p_pspr65.s:A_Saw',
     'p_pspr65.s:meleeAngle', 'p_pspr65.s:meleeAttack',
     'p_pspr65.s:angleToTarget'),
    # the thinkers' walk with P_MobjThinker, which it calls for every mobj
    # that is not clean by upstream's jml (callFn), a call the survey does
    # not see (tic.md R4: 601 B); and, the integrator's, the thinkers of
    # every tic it reaches the same way, the lights, the scroll and the
    # brainless mobjs' (418 B): in another group of the walk's slot each
    # would load its group and the walk's again, every tic (an APART rule
    # of the walk and THTAB instead made the model's cost 9.4 ms a tic: a
    # light packed with P_PlayerThink)
    ('p_tick65.s:P_RunThinkers', 'p_tick65.s:P_MobjThinker',
     'p_lights65.s:T_Glow', 'p_lights65.s:T_LightFlash',
     'p_lights65.s:T_StrobeFlash', 'p_spec65.s:T_Scroll',
     'p_tick65.s:P_MobjBrainlessThinker'),
    # the monsters' attacks and their helpers (chase.md R2: 811 B)
    ('p_enemy65.s:A_PosAttack', 'p_enemy65.s:A_SPosAttack',
     'p_enemy65.s:A_TroopAttack', 'p_enemy65.s:A_SargAttack',
     'p_enemy65.s:A_CyberAttack', 'p_enemy65.s:A_BruisAttack',
     'p_enemy65.s:lineAttack', 'p_enemy65.s:aimLine',
     'p_enemy65.s:spreadAngle', 'p_enemy65.s:damageTarget',
     'p_enemy65.s:spawnMissile'),
)


def routines() -> List[str]:
    """The part table's routines that have code (the inlined helpers have
    none: GL.INLINED)."""
    return [k for p in GL.PARTS for k in p['routines'] + p['helpers']
            if not GL.inlined(k)]


def measured(image: Path, name: str) -> Tuple[Dict[str, int], int]:
    """(each built routine's bytes, the core's bytes no table routine
    holds) of a test build (grun.routine_sizes): the parts' measured sizes
    and the core's fixed part (the runtime, milestone 9's core, the parts'
    code outside the table)."""
    from native import grun as G
    b = G.load_build(image, name)
    sizes, rest = G.routine_sizes(b)
    return sizes, sum(rest.values())


def core_room() -> Tuple[int, int]:
    """(room, used): the core image's bytes and what the runtime and
    milestone 9's core take in the skeleton's image (its test modules
    left out); the estimate 2,000 + 5,860 B (4.7) without a build."""
    room = GL.WR['CORE'][1] - GL.WR['CORE'][0]
    try:
        from native import grun as G
        b = G.load_build(G.GAME / 'skel', 'skel')
        ms = G.module_sizes(b)
        used = sum(v for k, v in ms.items() if k not in SKELETON_ONLY)
    except Exception:           # no build: the design's estimate
        used = 2000 + 5860
    return room, used


def heat_of(graph, path: Path = TRACE) -> Dict[str, int]:
    """Instructions a head runs in the trace (every phase: the game
    units' heads only run in the tic and setup phases)."""
    from ref816 import tracefile
    from native import gamecap as GC
    if not path.exists():
        return {}
    t = tracefile.read(path)
    cm = GC.CallerMap(graph)
    out: Dict[str, int] = {}
    for f in t.frames:
        for (phase, address), (count, _) in f.heat.items():
            k = cm.head(address)
            if k:
                out[k] = out.get(k, 0) + count
    return out


def sizes_of(graph, given: Optional[Dict[str, int]] = None
             ) -> Dict[str, int]:
    out = {}
    for k in routines():
        if given and k in given:
            out[k] = int(given[k])
            continue
        h = graph.heads.get(graph.head_of(k) or k)
        out[k] = max(8, int(round((h.size if h else 0) * GROWTH)))
    return out


def per_tic_edges(runs: Sequence[str]) -> Dict[Tuple[str, str],
                                                  List[float]]:
    """(caller, callee): the callee's calls a tic from that caller, a
    list over the runs' active tics (the callee's tics, split among its
    callers by their shares)."""
    from native import gamecap as GC
    out: Dict[Tuple[str, str], List[float]] = {}
    for run in runs:
        sv = GC.survey_of(run)
        if sv is None:
            continue
        tics: Set[int] = set()
        per: Dict[str, Dict[int, int]] = {}
        for k, r in sv['routines'].items():
            d: Dict[int, int] = {}
            for t in r['tic']:
                if t >= 0:
                    d[t] = d.get(t, 0) + 1
                    tics.add(t)
            per[k] = d
        active = sorted(tics)
        for k, r in sv['routines'].items():
            total = sum(r['parents'].values())
            if not total:
                continue
            for caller, n in r['parents'].items():
                share = n / total
                lst = out.setdefault((caller, k), [])
                lst += [per[k].get(t, 0) * share for t in active]
    return out


def merge(groups: List[List[str]], size: Dict[str, int],
          edges: Dict[Tuple[str, str], List[float]], slot1: int,
          slot2: int) -> List[List[str]]:
    """Fewer groups (gcall.s takes at most 63): the two groups with the
    most calls between them a tic merged while they fit slot 1, then the
    small ones packed together (first fit, largest first) into slot 2's
    size."""
    groups = [list(g) for g in groups]
    calls: Dict[Tuple[str, str], float] = {
        k: (sum(v) / len(v) if v else 0.0) for k, v in edges.items()}

    def between(a: List[str], b: List[str]) -> float:
        sa, sb = set(a), set(b)
        return sum(m for (x, y), m in calls.items()
                   if (x in sa and y in sb) or (x in sb and y in sa))

    def nbytes(g: List[str]) -> int:
        return sum(size[x] for x in g)

    while True:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if nbytes(groups[i]) + nbytes(groups[j]) > slot2:
                    continue
                c = between(groups[i], groups[j])
                if c > 0 and (best is None or c > best[0]):
                    best = (c, i, j)
        if best is None:
            break
        _, i, j = best
        groups[i] += groups[j]
        del groups[j]
    big = [g for g in groups if nbytes(g) > slot2]
    small = sorted((g for g in groups if nbytes(g) <= slot2),
                   key=lambda g: -nbytes(g))
    bins: List[List[str]] = []
    for g in small:
        for b in bins:
            if nbytes(b) + nbytes(g) <= slot2:
                b += g
                break
        else:
            bins.append(list(g))
    return big + bins


def place(graph, heat: Dict[str, int], size: Dict[str, int],
          edges: Dict[Tuple[str, str], List[float]],
          room: int) -> Dict[str, Any]:
    keys = routines()
    rank = {k: i for i, k in enumerate(keys)}
    core: List[str] = []
    used = 0
    for k in PINNED:
        if k not in size:
            continue
        if used + size[k] > room:
            raise ValueError('the pinned routines pass the core\'s room '
                             '(%d B)' % room)
        core.append(k)
        used += size[k]
    for k in CORE_FIRST:
        if k in size and k not in core and used + size[k] <= room:
            core.append(k)
            used += size[k]
    rest = sorted((k for k in keys if k not in core),
                  key=lambda k: (-heat.get(graph.head_of(k) or k, 0) /
                                 max(1, size[k]), rank[k]))
    unit_of: Dict[str, Tuple[str, ...]] = {}
    for a in AFFINITY:
        for k in a:
            unit_of[k] = a
    for k in rest:
        if heat.get(graph.head_of(k) or k, 0) <= 0 or k in core:
            continue
        unit = [x for x in unit_of.get(k, (k,)) if x in size and
                x not in core]
        n = sum(size[x] for x in unit)
        if used + n <= room:
            core += unit
            used += n
    cset = set(core)
    # the groups: components of the calls outside the core
    adj: Dict[str, Set[str]] = {k: set() for k in keys if k not in cset}
    for k in adj:
        h = graph.heads.get(graph.head_of(k) or k)
        for c in (h.calls if h else ()):
            if c in adj and c != k:
                adj[k].add(c)
                adj[c].add(k)
    for (a, b), _ in edges.items():
        if a in adj and b in adj and a != b:
            adj[a].add(b)
            adj[b].add(a)
    for unit in AFFINITY:
        inside = [k for k in unit if k in adj]
        for a, b in zip(inside, inside[1:]):
            adj[a].add(b)
            adj[b].add(a)
    seen: Set[str] = set()
    groups: List[List[str]] = []
    full1 = GL.SLOTS[1][1] - GL.SLOTS[1][0]
    full2 = GL.SLOTS[2][1] - GL.SLOTS[2][0]
    # (a group is packed to the slot less GROUP_MARGIN; an affinity unit
    # larger than that is a group of its own)
    slot1 = GL.SLOTS[1][1] - GL.SLOTS[1][0] - GROUP_MARGIN
    slot2 = full2 - GROUP_MARGIN
    for k in sorted(adj, key=lambda x: rank[x]):
        if k in seen:
            continue
        comp: List[str] = []
        todo = [k]
        while todo:
            x = todo.pop(0)
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            todo += sorted(adj[x] - seen, key=lambda y: rank[y])
        # cut in call order, an affinity unit never split (its members
        # together where its first comes)
        order: List[str] = []
        for x in comp:
            if x in order:
                continue
            order += [y for y in unit_of.get(x, (x,)) if y in comp and
                      y not in order] if x in unit_of else [x]
        cur: List[str] = []
        n = 0
        i = 0
        while i < len(order):
            x = order[i]
            unit = [y for y in unit_of.get(x, (x,)) if y in order[i:]] \
                if x in unit_of else [x]
            m = sum(size[y] for y in unit)
            if m > full2:
                raise ValueError('an affinity unit passes a slot: %s' %
                                 unit)
            if cur and n + m > slot2:
                groups.append(cur)
                cur, n = [], 0
            cur += unit
            n += m
            i += len(unit)
        if cur:
            groups.append(cur)
    groups = merge(groups, size, edges, slot1, slot2)
    group_of = {x: i for i, g in enumerate(groups) for x in g}
    gbytes = [sum(size[x] for x in g) for g in groups]
    # calls a tic between groups (the median over the tics)
    pair_calls: Dict[Tuple[int, int], List[float]] = {}
    for (a, b), lst in edges.items():
        ga, gb = group_of.get(a), group_of.get(b)
        if ga is None or gb is None or ga == gb:
            continue
        key = (min(ga, gb), max(ga, gb))
        cur = pair_calls.setdefault(key, [0.0] * len(lst))
        if len(cur) < len(lst):
            cur += [0.0] * (len(lst) - len(cur))
        for i, v in enumerate(lst):
            cur[i] += v
    mean_calls = {p: (sum(v) / len(v) if v else 0.0)
                  for p, v in pair_calls.items()}
    median_calls = {p: (statistics.median(v) if v else 0.0)
                    for p, v in pair_calls.items()}

    def load_us(g: int) -> float:
        return gbytes[g] * BYTE_US + WINDOW_US

    # A_Chase's slot and its callees' groups
    forbid: Set[Tuple[int, int]] = set()
    if CHASE in group_of:
        h = graph.heads.get(graph.head_of(CHASE) or CHASE)
        for c in (h.calls if h else ()):
            if c in group_of and group_of[c] != group_of[CHASE]:
                forbid.add((group_of[CHASE], group_of[c]))
    chase_forbid = set(forbid)
    # the APART pairs
    for a, b in APART:
        if a in group_of and b in group_of and group_of[a] != group_of[b]:
            forbid.add((group_of[a], group_of[b]))
    slot = [1 if gbytes[i] > full2 else 2 for i in range(len(groups))]

    def cost() -> float:
        total = 0.0
        for (a, b), m in mean_calls.items():
            if slot[a] == slot[b]:
                total += m * (load_us(a) + load_us(b))
        return total

    def legal() -> bool:
        return all(slot[a] != slot[b] for a, b in forbid) and all(
            gbytes[i] <= (full1 if slot[i] == 1 else full2)
            for i in range(len(groups)))

    # the forbidden pairs' components, each two-coloured (two slots: a
    # component has exactly two legal colourings), then flipped whole;
    # every other group alone
    near: Dict[int, Set[int]] = {}
    for a, b in forbid:
        near.setdefault(a, set()).add(b)
        near.setdefault(b, set()).add(a)
    moves: List[List[int]] = []
    done: Set[int] = set()
    for i in range(len(groups)):
        if i in done:
            continue
        comp = [i]
        done.add(i)
        if i in near:
            slot[i] = 2
            todo = [i]
            while todo:
                x = todo.pop(0)
                for y in sorted(near[x]):
                    if y in done:
                        if slot[y] == slot[x]:
                            raise ValueError('the slot rules cannot all '
                                             'hold: groups %d and %d' %
                                             (x + 1, y + 1))
                        continue
                    slot[y] = 3 - slot[x]
                    done.add(y)
                    comp.append(y)
                    todo.append(y)
        moves.append(comp)
    # the search: every colouring of the moves when they are few (a Gray
    # code walk, the cost kept by its change), else one move and two
    # together until none helps (wave 5 as integrated: the greedy walk
    # alone stopped at 4.1 ms where 1.6 was legal)
    weight = {pq: m * (load_us(pq[0]) + load_us(pq[1]))
              for pq, m in mean_calls.items()}
    touching: Dict[int, List[Tuple[int, int]]] = {}
    for pq in weight:
        for g in pq:
            touching.setdefault(g, []).append(pq)

    def flip(*comps: List[int]) -> None:
        for comp in comps:
            for i in comp:
                slot[i] = 3 - slot[i]

    def oversize(i: int) -> bool:
        return gbytes[i] > (full1 if slot[i] == 1 else full2)

    best = cost() if legal() else float('inf')
    if len(moves) <= EXHAUSTIVE:
        cur = cost()
        over = sum(1 for i in range(len(groups)) if oversize(i))
        best_slot = list(slot) if over == 0 else None
        best = cur if over == 0 else float('inf')
        for k in range(1, 1 << len(moves)):
            comp = moves[(k & -k).bit_length() - 1]
            pqs = {pq for g in comp for pq in touching.get(g, ())}
            cur -= sum(weight[pq] for pq in pqs if slot[pq[0]] == slot[pq[1]])
            over -= sum(1 for i in comp if oversize(i))
            flip(comp)
            cur += sum(weight[pq] for pq in pqs if slot[pq[0]] == slot[pq[1]])
            over += sum(1 for i in comp if oversize(i))
            if over == 0 and cur + 1e-6 < best:
                best = cur
                best_slot = list(slot)
        if best_slot is None:
            raise ValueError('no legal slot for every group')
        slot[:] = best_slot
        best = cost()
    improved = True
    rounds = 0
    while improved and rounds < 50:
        improved = False
        rounds += 1
        tries = [(m,) for m in moves] + [
            (m, n) for i, m in enumerate(moves) for n in moves[i + 1:]]
        for t in tries:
            flip(*t)
            c = cost() if legal() else float('inf')
            if c + 1e-9 < best:
                best = c
                improved = True
            else:
                flip(*t)
    report_pairs = []
    for (a, b), med in sorted(median_calls.items()):
        if slot[a] == slot[b] and med > 1:
            report_pairs.append({'groups': [a + 1, b + 1], 'slot': slot[a],
                                 'median_calls_a_tic': med})
    chase_ok = all(slot[a] != slot[b] for a, b in chase_forbid)
    apart_ok = all(slot[a] != slot[b] for a, b in forbid)
    return {'format': 'game-placement 1',
            'groups': [{'slot': slot[i], 'routines': g, 'bytes': gbytes[i]}
                       for i, g in enumerate(groups)],
            'routines': {x: group_of[x] + 1 for x in group_of},
            'core': core, 'core_bytes': used, 'core_room': room,
            'cost_us_a_tic': round(best, 1) if best != float('inf')
            else None,
            'same_slot_pairs_over_1': report_pairs,
            'a_chase_rule': chase_ok, 'apart_rule': apart_ok}


def run(write: bool = False, sizes: Optional[Path] = None,
        heat_file: Optional[Path] = None,
        runs: Sequence[str] = ('demo3', 'demo1', 'demo2'),
        measure: Optional[Tuple[Path, str]] = None) -> Dict[str, Any]:
    from native import gcallgraph as CG
    graph = CG.load(write=False)
    room, used = core_room()
    heat = json.loads(heat_file.read_text()) if heat_file else \
        heat_of(graph)
    given = json.loads(sizes.read_text()) if sizes else None
    if measure is not None:
        given, used = measured(*measure)
    size = sizes_of(graph, given)
    edges = per_tic_edges(runs)
    res = place(graph, heat, size, edges, room - used - CORE_MARGIN)
    res['skeleton_core_bytes'] = used
    res['heat_source'] = str(heat_file or TRACE)
    res['size_source'] = (('measured: %s/%s.map, the rest upstream x %.1f'
                           % (measure[0], measure[1], GROWTH)) if measure
                          else str(sizes) if sizes else
                          'upstream x %.1f' % GROWTH)
    res['pinned'] = [k for k in PINNED if k in res['core']]
    res['runs'] = list(runs)
    if write:
        PLACEMENT.parent.mkdir(parents=True, exist_ok=True)
        PLACEMENT.write_text(json.dumps(res, indent=1) + '\n')
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--sizes', type=Path)
    parser.add_argument('--heat', type=Path)
    parser.add_argument('--runs', default='demo3,demo1,demo2')
    parser.add_argument('--measure', default=None,
                        help='DIR/NAME of a test build: the built parts\' '
                             'routines and the core\'s fixed bytes measured '
                             'there (grun.routine_sizes), e.g. '
                             'build/native/game/wave1/wtest')
    args = parser.parse_args(argv)
    measure = None
    if args.measure:
        mp = Path(args.measure)
        measure = (mp.parent, mp.name)
    res = run(args.write, args.sizes, args.heat, args.runs.split(','),
              measure)
    print('core: %d routines, %d of %d B (the skeleton\'s own %d B)' % (
        len(res['core']), res['core_bytes'], res['core_room'],
        res['skeleton_core_bytes']))
    for i, g in enumerate(res['groups'], 1):
        print('group %d: slot %d, %d routines, %d B' % (
            i, g['slot'], len(g['routines']), g['bytes']))
    print('same-slot calls: %s us a tic (mean); A_Chase\'s rule %s; the '
          'APART pairs %s' % (
              res['cost_us_a_tic'],
              'kept' if res['a_chase_rule'] else 'BROKEN',
              'apart' if res['apart_rule'] else 'BROKEN'))
    for p in res['same_slot_pairs_over_1']:
        print('  groups %s in slot %d: %.1f calls a tic at the median' % (
            p['groups'], p['slot'], p['median_calls_a_tic']))
    if not res['same_slot_pairs_over_1']:
        print('  no pair of one slot with more than one call a tic at the '
              'median')
    return 0 if res['a_chase_rule'] and res['apart_rule'] else 1


if __name__ == '__main__':
    sys.exit(main())
