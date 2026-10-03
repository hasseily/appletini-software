#!/usr/bin/env python3
"""The placement of the tic phase's code (milestone 10, docs/GAME.md 4.3;
wave 1 of the speed plan, docs/SPEED.md 4 #1, docs/speed-parts/place.md):
each routine of the part table in the core or in a group of a slot.

Usage:  python3 tools/native/gplace.py [--write] [--placement FILE]
            [--no-search] [--page-us 63.8] [--call-us 5]
            [--restore auto|lazy|eager] [--train S,...] [--hold S,...]
            [--sweeps N] [--anneal N] [--seed N] [--core-reserve B]
            [--traces DIR] [--json FILE]
        python3 tools/native/gplace.py --heuristic [--write] [--sizes FILE]
            [--runs demo3,demo1,demo2] [--measure DIR/NAME]

The trained placement (the default when the scenes are recorded:
gplacerec.py): the machine's cost on recorded call traffic. Each scene
of TRAIN (the play build standing still, walking, demo3 in the title
loop; the lockstep build's demo3) is replayed by gsim, a model of gcall.s
that reproduces the loads the runs recorded exactly (gplacesim.py
--check), under a candidate placement; its cost is the pages copied at
--page-us (gr_load copies whole pages: 100.3 us a page before wave 1,
63.8 with part paging's far_gcopy, the default) plus --call-us a call
through fc_call (5 us), in ms a tic summed over the scenes, with gcall.s's
restore at a return (--restore lazy, part paging's SLOT_NEED of wave 1;
eager, the rule before it; auto, the default: the builds' own). The
search starts from
--placement FILE or the current placement.json and moves units (an
AFFINITY unit per source file: its calls across files are FCALLs; every
other routine alone) between the core, the groups and new groups, and
groups between the slots, while the cost falls and every rule holds:

  - sizes: each routine's measured bytes in the builds (the play link's
    tic image, the lockstep builds game and gprof), plus 3 B for each of
    its FCALL sites that the placement turns into fc_call (6 B instead of
    a jsr's 3) and less 3 B for each it turns back; a group at most its
    slot's 2,048 B less GROUP_MARGIN; the core's table routines and every
    build's fixed core code (the runtime, milestone 9's core, the play
    link's dl_hook.o: docs/play-requests.md P2, and since speed wave 2
    its s2t_hu.o, which play.mk's PLAY_TIC puts in the core with
    fx_chan's scratch block: docs/speed-parts/glue.md; the test builds'
    ghook and grec), with their own FCALL sites, at most the core's
    13,312 B less CORE_MARGIN (and --core-reserve); measured in the links
    as they are, so a play link older than those sources is named in the
    report (PLAY_GLUE_CORE); at most 43 groups (the play
    disk's CODE.2: a bank file of 49 segments holds W and the core, the
    glue's 5 groups and the game's), their pages packed in GCODE0 and
    GCODE1;
  - A_Chase's callees' groups never share A_Chase's slot, nor the groups
    of an APART pair one slot; a routine that reaches another without
    FCALL (a jsr, jmp or branch to its code, its address taken:
    hard_refs) has it in its group or in the core; the sources' own
    .assert on a placement (placement_asserts: sight.s keeps P_CheckSight
    in the core for its test entries) holds. PINNED and CORE_FIRST
    are the heuristic's: the trained search weighs the core by the
    traffic instead.

The scenes of HOLD are only evaluated (held-out checks). The report gives
each scene's loads and ms a tic before and after.

--heuristic: the placement of waves 1 to 6 (the heat, the survey's call
counts, the size estimates; see place()), its cost now in pages too.

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
# the machine's cost (docs/SPEED.md 2, measured on a2vm f121: gr_load copies
# whole pages, one far_get and one RAMRD window a page, 100.3 us; with part
# paging's far_gcopy, one window a group, 63.8 us a page; a call through
# fc_call, fc_go and fc_ret about 5 us)
PAGE_US_NOW = 100.3
PAGE_US = 63.8                  # the default: wave 1 has far_gcopy
CALL_US = 5.0
# gcall.s's restore at a return: 'eager' (the slot's group at the call, as
# before wave 1) or 'lazy' (the group the slot's innermost active call
# needs, SLOT_NEED: part paging's, wave 1); 'auto', the default: the
# builds' own (lazy when their ggame.inc has SLOT_NEED)
RESTORE = 'auto'
PAGE = 256
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
        # (gr_load copies the group's whole pages; the call's own cost
        # too, the fc_call path, CALL_US)
        return (gbytes[g] + PAGE - 1) // PAGE * PAGE_US + CALL_US

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


def run_heuristic(write: bool = False, sizes: Optional[Path] = None,
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



# ---------------------------------------------------------------------------
# The trained placement (docs/speed-parts/place.md)
# ---------------------------------------------------------------------------
TRAIN = ('still', 'walk', 'demo3', 'lock3a')
HOLD = ('fight', 'demo3b', 'lock3b')
FCALL_BYTES = 3                 # fc_call's 6 B against a jsr's 3
# the groups at most: the play disk's CODE.2 holds the tic image in one
# bank file of at most LL.BANKFILE_MAX_SEGS (49) segments, W and the core,
# the glue's 5 groups and the game's (playdisk.tic_segments: 43 game
# groups); gcall.s's MAXGRP 49 (GROUPS < 49 with the glue's after them)
MAX_GROUPS = 43
GROUP_ROOM = GL.SLOTS[1][1] - GL.SLOTS[1][0]
SWEEPS = 4
ANNEAL = 40000
SEED = 1
GLUE_BASE = 100                 # (the model's numbers of the glue groups)
CORE_RESERVE = 0                # bytes of the core kept free besides
#                                 CORE_MARGIN: growth the builds do not
#                                 have yet (--core-reserve)
BUILDS = (('play', None), ('game', 'game'), ('gprof', 'gprof'))
SRC = ROOT / 'src' / 'native'


class PlaceError(Exception):
    pass


def fcall_sites(src: Path = SRC) -> Dict[str, Dict[str, int]]:
    """caller -> {callee: FCALL sites}, from the sources: every FCALL of a
    ROUTINE's code (a macro's FCALLs counted at each use), keyed file:label
    (GL.native_names); code before a file's first ROUTINE is '@file:STEM'.
    (A placement changes an FCALL site's size: 6 B through fc_call, 3 B as
    a jsr.)"""
    import re
    inv = {v: k for k, v in GL.native_names().items()}
    files = sorted(src.glob('*.s')) + sorted(src.glob('game/*/*.s'))
    incs = sorted(src.glob('*.inc')) + sorted(src.glob('game/*/*.inc'))
    rx_r = re.compile(r'^\s*(?:[@\w]+:)?\s*ROUTINE\s+(\w+)', re.I)
    rx_f = re.compile(r'^\s*(?:[@\w]*:)?\s*FCALL\s+(\w+)', re.I)
    rx_m0 = re.compile(r'^\s*\.macro\s+(\w+)', re.I)
    rx_m1 = re.compile(r'^\s*\.endmacro', re.I)
    rx_w = re.compile(r'^\s*(?:[@\w]*:)?\s*(\w+)\b')
    rx_seg = re.compile(r'^\s*\.segment\s+"(\w+)"', re.I)
    builtin = ('FCALL', 'ROUTINE', 'DCALL')
    body: Dict[str, List[Tuple[str, str]]] = {}
    for f in files + incs:
        cur = None
        for line in f.read_text(errors='replace').splitlines():
            line = line.split(';', 1)[0]
            m = rx_m0.match(line)
            if m:
                cur = m.group(1)
                body.setdefault(cur, [])
                continue
            if rx_m1.match(line):
                cur = None
                continue
            if cur is None or cur in builtin:
                continue
            m = rx_f.match(line)
            if m:
                body[cur].append(('F', m.group(1)))
                continue
            m = rx_w.match(line)
            if m and m.group(1) in body:
                body[cur].append(('M', m.group(1)))

    def expand(name: str, depth: int = 0) -> Dict[str, int]:
        out: Dict[str, int] = {}
        if depth > 8:
            return out
        for kind, v in body.get(name, ()):
            if kind == 'F':
                out[v] = out.get(v, 0) + 1
            elif v not in builtin:
                for t, n in expand(v, depth + 1).items():
                    out[t] = out.get(t, 0) + n
        return out
    mac = {m: expand(m) for m in body if m not in builtin}
    mac = {m: c for m, c in mac.items() if c}
    out: Dict[str, Dict[str, int]] = {}
    for f in files:
        cur = '@file:' + f.stem
        inmac = False
        for line in f.read_text(errors='replace').splitlines():
            line = line.split(';', 1)[0]
            if rx_m0.match(line):
                inmac = True
                continue
            if rx_m1.match(line):
                inmac = False
                continue
            if inmac:
                continue
            m = rx_r.match(line)
            if m:
                cur = inv.get(m.group(1), '@file:' + f.stem)
                continue
            m = rx_seg.match(line)
            if m:
                # (code after a segment directive is no routine's: the
                # core's fixed code, or another image's: the driver's)
                cur = '@file:' + f.stem if m.group(1) in ('GCORE',
                                                         'LOADW') \
                    else '@seg:' + f.stem
                continue
            m = rx_f.match(line)
            calls: Dict[str, int] = {}
            if m:
                calls = {m.group(1): 1}
            else:
                m = rx_w.match(line)
                if m and m.group(1) in mac:
                    calls = mac[m.group(1)]
            for t, n in calls.items():
                key = inv.get(t)
                if key is None or cur.startswith('@seg:'):
                    continue
                d = out.setdefault(cur, {})
                d[key] = d.get(key, 0) + n
    return out


def hard_refs(src: Path = SRC) -> Set[Tuple[str, str]]:
    """(routine, routine) pairs of the sources that reference each other
    without FCALL or DCALL: a jsr, jmp or branch to a label of another
    ROUTINE's code in the same file (or to its global name), an address
    taken (#<, #>, .addr, .word). Such a pair needs the target in the
    core or in the referrer's group (a rule of the search; none crosses
    an AFFINITY unit on 2026-10-02)."""
    import re
    inv = {v: k for k, v in GL.native_names().items()}
    rx_r = re.compile(r'^\s*(?:[@\w]+:)?\s*ROUTINE\s+(\w+)', re.I)
    rx_lab = re.compile(r'^([A-Za-z_]\w*):')
    rx_ins = re.compile(r'^\s*(?:[@\w]*:)?\s*(?:jsr|jmp|bra|beq|bne|bcc|'
                        r'bcs|bmi|bpl|bvc|bvs|j[a-z]{2})\s+\(?([A-Za-z_]\w*)',
                        re.I)
    rx_ref = re.compile(r'(?:#<|#>|\.addr\s+|\.word\s+)\s*([A-Za-z_]\w*)')
    rx_m0 = re.compile(r'^\s*\.macro\b', re.I)
    rx_m1 = re.compile(r'^\s*\.endmacro\b', re.I)
    rx_seg = re.compile(r'^\s*\.segment\b', re.I)
    out: Set[Tuple[str, str]] = set()
    for f in sorted(src.glob('game/*/*.s')):
        lines = [x.split(';', 1)[0] for x in
                 f.read_text(errors='replace').splitlines()]
        owner: Dict[str, str] = {}
        cur = None
        inmac = False
        for line in lines:
            if rx_m0.match(line):
                inmac = True
            elif rx_m1.match(line):
                inmac = False
            elif not inmac:
                m = rx_r.match(line)
                if m:
                    cur = inv.get(m.group(1))
                    continue
                if rx_seg.match(line):
                    cur = None
                    continue
                m = rx_lab.match(line)
                if m and cur:
                    owner.setdefault(m.group(1), cur)
        cur = None
        inmac = False
        for line in lines:
            if rx_m0.match(line):
                inmac = True
                continue
            if rx_m1.match(line):
                inmac = False
                continue
            m = rx_r.match(line)
            if inmac or m:
                if m:
                    cur = inv.get(m.group(1))
                continue
            if rx_seg.match(line):
                cur = None
                continue
            if cur is None or re.search(r'\b(FCALL|DCALL)\b', line):
                continue
            m = rx_ins.match(line)
            toks = [m.group(1)] if m else rx_ref.findall(line)
            for t in toks:
                c = owner.get(t) or inv.get(t)
                if c and c != cur:
                    out.add((cur, c))
    return out


def placement_asserts(src: Path = SRC) -> List[Tuple[str, ...]]:
    """The sources' own rules on the placement (ca65 .assert on
    GP_name_G): ('core', key) for GP_x_G = 0 (sight.s: P_CheckSight in
    the core, for its test entries), ('one', a, b) for GP_a_G = GP_b_G."""
    import re
    inv = {v: k for k, v in GL.native_names().items()}
    rx = re.compile(r'^\s*\.assert\s+GP_(\w+)_G\s*=\s*(?:(0)\b|GP_(\w+)_G)')
    out: List[Tuple[str, ...]] = []
    for f in sorted(src.glob('*.s')) + sorted(src.glob('game/*/*.s')):
        for line in f.read_text(errors='replace').splitlines():
            m = rx.match(line.split(';', 1)[0])
            if not m or m.group(1) not in inv:
                continue
            if m.group(2) is not None:
                out.append(('core', inv[m.group(1)]))
            elif m.group(3) in inv:
                out.append(('one', inv[m.group(1)], inv[m.group(3)]))
    return sorted(set(out))


class Build(object):
    """A linked tic build's measures: each table routine's bytes and
    group, the core's other code (fixed: its modules' bytes), the FCALL
    sites the link made fc_call (exact: the bytes jsr fc_call, group,
    target)."""

    def __init__(self, label: str, b, glue: Optional[Dict[str, int]] = None):
        from native import grun as G, gplacerec as REC
        self.label = label
        self.b = b
        inc = b.obj / 'gen' / 'gplace.inc'
        if inc.stat().st_mtime > (b.obj / ('%s.map' % b.name)).stat(
                ).st_mtime:
            # (a link that failed after glayout.py wrote a new placement:
            # the map is the old one's)
            raise PlaceError('the %s build\'s gplace.inc is newer than its '
                             'map: link it again' % label)
        self.ranges = REC.unit_ranges(b, glue)
        # (grun.routine_sizes's sizes, but a routine's range ends at a
        # fixed label: the core's code after it is the core's)
        self.sizes: Dict[str, int] = {}
        for u, g, lo, hi in self.ranges:
            if not u.startswith('@'):
                self.sizes[u] = self.sizes.get(u, 0) + hi - lo
        core = sum(hi - lo for m, seg, lo, hi in G.contributions(b)
                   if seg in G.CODE_SEGMENTS)
        self.fixed = core - sum(hi - lo for u, g, lo, hi in self.ranges
                                if g == 0 and not u.startswith('@'))
        self.core_modules = {m for m, seg, lo, hi in G.contributions(b)
                             if seg in G.CODE_SEGMENTS}
        self.place = {u: g for u, g, *_ in self.ranges
                      if not u.startswith('@')}
        self.module_of = {}
        contrib = G.contributions(b)
        for u, g, lo, hi in self.ranges:
            if u.startswith('@'):
                continue
            for m, seg, clo, chi in contrib:
                sg = 0 if seg in G.CODE_SEGMENTS else (
                    int(seg[4:]) if seg.startswith('GGRP') else -1)
                if sg == g and clo <= lo < chi:
                    self.module_of[u] = m
                    break
        self.fc_sites = self._fc_sites()

    def _bytes(self, g: int, lo: int, hi: int) -> bytes:
        b = self.b
        if g == 0:
            core = (b.obj / ('%s.core' % b.name)).read_bytes()
            return core[lo - GL.WR['CORE'][0]:hi - GL.WR['CORE'][0]]
        data = (b.obj / ('%s.g%d' % (b.name, g))).read_bytes()
        base = b.segments['GGRP%d' % g][0]
        return data[lo - base:hi - base]

    def _fc_sites(self) -> Dict[Tuple[str, str], int]:
        fc = self.b.labels['fc_call']
        at: Dict[Tuple[int, int], str] = {}
        for u, g, lo, hi in self.ranges:
            for a in range(lo, hi):
                at[(g, a)] = u
        out: Dict[Tuple[str, str], int] = {}
        for u, g, lo, hi in self.ranges:
            if u.startswith('@'):
                continue
            data = self._bytes(g, lo, hi)
            for i in range(len(data) - 5):
                if data[i] == 0x20 and data[i + 1] == fc & 0xFF and \
                        data[i + 2] == fc >> 8:
                    t = data[i + 4] | data[i + 5] << 8
                    callee = at.get((data[i + 3], t))
                    if callee and not callee.startswith('@'):
                        out[(u, callee)] = out.get((u, callee), 0) + 1
        return out


# the sources of the play link's fixed core code beyond the lockstep
# builds' (dl_hook.s's core entries and fxc_scr, s2t_hu.s's module under
# play.mk's PLAY_TIC): a play link older than one of them measures the
# old bytes
PLAY_GLUE_CORE = ('src/native/dl_hook.s', 'src/native/s2t_hu.s',
                  'src/native/play.mk')


def play_stale(play: Optional[Path] = None) -> List[str]:
    """The sources of PLAY_GLUE_CORE newer than the play link's map ([]
    when none, or no play link)."""
    pdir = play or (BUILD / 'native' / 'play')
    lmap = pdir / 'tic' / 'tic.map'
    if not lmap.exists():
        return []
    t = lmap.stat().st_mtime
    return [s for s in PLAY_GLUE_CORE
            if (ROOT / s).exists() and (ROOT / s).stat().st_mtime > t]


def load_builds(play: Optional[Path] = None) -> List[Build]:
    """The builds that exist: the play link's tic image (with dl_hook.o in
    its core: docs/play-requests.md P2) and the lockstep builds."""
    from native import grun as G, gplacerec as REC
    out = []
    for label, name in BUILDS:
        try:
            if name is None:
                from native import playlink as PK
                pdir = play or (BUILD / 'native' / 'play')
                if not (pdir / 'tic' / 'tic.map').exists():
                    continue
                b = PK.tic_build(pdir)
                n = PK.gplace_groups(b.obj / 'gen' / 'gplace.inc')
                out.append(Build(label, b, REC.glue_groups(b, n)))
            else:
                if not (G.GAME / name / ('%s.map' % name)).exists():
                    continue
                out.append(Build(label, G.load_build(G.GAME / name, name)))
        except (OSError, KeyError, ValueError) as e:
            raise PlaceError('the %s build: %s' % (label, e))
    if not out:
        raise PlaceError('no tic build to measure (make -f game.mk game, '
                         'python3 tools/native/playdisk.py)')
    return out


def restore_of(builds: Sequence[Build]) -> str:
    """gcall.s's restore in the builds: 'lazy' when their layouts have
    SLOT_NEED (part paging's lazy restore), else 'eager'."""
    from native import gplacerec as REC
    kinds = set()
    for b in builds:
        sym = REC.inc_symbols([b.b.obj / 'gen'])
        kinds.add('lazy' if 'SLOT_NEED' in sym else 'eager')
    if len(kinds) != 1:
        raise PlaceError('the builds disagree on gcall.s\'s restore: '
                         'rebuild them')
    return kinds.pop()


class Sizer(object):
    """The bytes of a placement: each routine's measured size (the largest
    over the builds) with its FCALL sites' change, the groups', the core's
    in every build."""

    def __init__(self, builds: Sequence[Build],
                 sites: Dict[str, Dict[str, int]]):
        self.builds = list(builds)
        self.cur = dict(self.builds[0].place)
        keys = set()
        for b in self.builds:
            keys |= set(b.sizes)
        self.size = {k: max(b.sizes.get(k, 0) for b in self.builds)
                     for k in keys}
        # the sites a routine has: the sources' count, the links' where
        # they made fc_call (exact)
        self.sites: Dict[str, List[Tuple[str, int]]] = {}
        for caller, d in sites.items():
            if caller.startswith('@'):
                continue
            self.sites[caller] = [(c, n) for c, n in d.items()
                                  if c in self.size]
        for b in self.builds:
            for (u, c), n in b.fc_sites.items():
                lst = dict(self.sites.get(u, []))
                lst[c] = n
                self.sites[u] = sorted(lst.items())
        # the fixed core code's sites, by build: the files whose modules
        # are in that build's core
        self.fixed_sites: List[List[Tuple[str, int]]] = []
        for b in self.builds:
            d: Dict[str, int] = {}
            for caller, cs in sites.items():
                if caller.startswith('@file:') and \
                        caller[6:] in b.core_modules:
                    for c, n in cs.items():
                        if c in self.size:
                            d[c] = d.get(c, 0) + n
            self.fixed_sites.append(sorted(d.items()))
        # each routine's bytes with no site as fc_call: the largest over
        # the builds, each under its own link's placement (the builds may
        # follow different placements: one relinked, the others not yet)
        self.base = {}
        for k in self.size:
            self.base[k] = max(
                b.sizes[k] - FCALL_BYTES * sum(
                    n for c, n in self.sites.get(k, ())
                    if self._cross(b.place, b.place.get(k, 0), c))
                for b in self.builds if k in b.sizes)
        self.fixed_base = []
        for b, fs in zip(self.builds, self.fixed_sites):
            self.fixed_base.append(b.fixed - FCALL_BYTES * sum(
                n for c, n in fs if self._cross(b.place, 0, c)))

    @staticmethod
    def _cross(place: Dict[str, int], g: int, callee: str) -> bool:
        h = place.get(callee, 0)
        return h != 0 and h != g

    def routine(self, k: str, place: Dict[str, int]) -> int:
        g = place.get(k, 0)
        return self.base[k] + FCALL_BYTES * sum(
            n for c, n in self.sites.get(k, ()) if self._cross(place, g, c))

    def groups(self, place: Dict[str, int]) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for k in self.size:
            g = place.get(k, 0)
            if g:
                out[g] = out.get(g, 0) + self.routine(k, place)
        return out

    def core(self, place: Dict[str, int]) -> Tuple[int, List[int]]:
        """(the table routines' bytes in the core, each build's fixed core
        bytes)."""
        table = sum(self.routine(k, place) for k in self.size
                    if place.get(k, 0) == 0)
        fixed = [fb + FCALL_BYTES * sum(n for c, n in fs
                                        if self._cross(place, 0, c))
                 for fb, fs in zip(self.fixed_base, self.fixed_sites)]
        return table, fixed

    def core_room(self, place: Dict[str, int]) -> int:
        """The core's room for the table routines under this placement."""
        _, fixed = self.core(place)
        return GL.WR['CORE'][1] - GL.WR['CORE'][0] - CORE_MARGIN - max(fixed)


def pack_ok(pages: Sequence[int]) -> bool:
    """The groups' pages packed in GCODE0 (GROUP_FIRST to W's $6000) then
    GCODE1 (to LL.ROOM's end), in their order (playdisk.tic_segments,
    grun.py's images)."""
    from native import llayout as LL
    at = {0: 0x0200, 1: 0x0200}
    end = {0: 0x6000, 1: LL.ROOM[1]}
    for n in pages:
        bank = 0 if at[0] + (n << 8) <= end[0] else 1
        if at[bank] + (n << 8) > end[bank]:
            return False
        at[bank] += n << 8
    return True


def callees_of(key: str, graph, sites: Dict[str, Dict[str, int]]
               ) -> Set[str]:
    h = graph.heads.get(graph.head_of(key) or key) if graph else None
    out = set(h.calls if h else ())
    out |= set(sites.get(key, {}))
    return out


class Problem(object):
    """The search's state: units (tuples of keys) in groups (0 the core),
    the groups' slots, the rules and the sizes."""

    def __init__(self, sizer: Sizer, graph, sites, start: Dict[str, int],
                 start_slots: Dict[int, int], module_of: Dict[str, str],
                 refs: Optional[Set[Tuple[str, str]]] = None,
                 reserve: int = CORE_RESERVE,
                 asserts: Sequence[Tuple[str, ...]] = ()):
        self.sizer = sizer
        self.reserve = reserve
        keys = sorted(sizer.size)
        self.keys = keys
        unit_of: Dict[str, Tuple[str, ...]] = {}
        units: List[Tuple[str, ...]] = []
        for aff in AFFINITY:
            mem = [k for k in aff if k in sizer.size and k not in unit_of]
            by_mod: Dict[str, List[str]] = {}
            for k in mem:
                by_mod.setdefault(module_of.get(k, '?'), []).append(k)
            for sub in by_mod.values():
                u = tuple(sub)
                units.append(u)
                for k in u:
                    unit_of[k] = u
        for k in keys:
            if k not in unit_of:
                unit_of[k] = (k,)
                units.append((k,))
        self.units = units
        self.uidx = {u: i for i, u in enumerate(units)}
        self.unit_of = unit_of
        # a unit starts where its first routine is (a unit split across
        # groups in the start joins its first's)
        self.ug = [start.get(u[0], 0) for u in units]
        self.gslot = dict(start_slots)
        self.chase_callees = callees_of(CHASE, graph, sites) & set(keys)
        self.apart = [(a, b) for a, b in APART if a in sizer.size and
                      b in sizer.size]
        self.bound = sorted((a, b) for a, b in (refs or ())
                            if a in sizer.size and b in sizer.size and
                            unit_of[a] != unit_of[b])
        self.asserts = [r for r in (asserts or ())
                        if all(k in sizer.size for k in r[1:])]

    def place(self) -> Dict[str, int]:
        return {k: self.ug[self.uidx[self.unit_of[k]]] for k in self.keys}

    def problems(self, place: Optional[Dict[str, int]] = None) -> List[str]:
        place = place or self.place()
        out = []
        gb = self.sizer.groups(place)
        for g, n in sorted(gb.items()):
            if n > GROUP_ROOM - GROUP_MARGIN:
                out.append('group %d: %d B' % (g, n))
            if g not in self.gslot:
                out.append('group %d: no slot' % g)
        if len(gb) > MAX_GROUPS:
            out.append('%d groups' % len(gb))
        table, fixed = self.sizer.core(place)
        room = GL.WR['CORE'][1] - GL.WR['CORE'][0] - CORE_MARGIN - \
            self.reserve
        if table + max(fixed) > room:
            out.append('the core: %d + %d B' % (table, max(fixed)))
        if not pack_ok([(gb[g] + PAGE - 1) // PAGE for g in sorted(gb)]):
            out.append('the groups pass GCODE1')
        out += self.rule_problems(place)
        return out

    def rule_problems(self, place: Dict[str, int]) -> List[str]:
        out = []
        gc = place.get(CHASE, 0)
        if gc:
            for c in sorted(self.chase_callees):
                g = place.get(c, 0)
                if g and g != gc and self.gslot.get(g) == \
                        self.gslot.get(gc):
                    out.append('A_Chase\'s callee %s in its slot' % c)
        for a, b in self.apart:
            ga, gb_ = place.get(a, 0), place.get(b, 0)
            if ga and gb_ and ga != gb_ and self.gslot.get(ga) == \
                    self.gslot.get(gb_):
                out.append('APART %s, %s in one slot' % (a, b))
        for a, b in self.bound:
            if place.get(b, 0) not in (0, place.get(a, 0)):
                out.append('%s reaches %s without FCALL' % (a, b))
        for rule in self.asserts:
            if rule[0] == 'core' and place.get(rule[1], 0):
                out.append('%s not in the core (its source asserts it)' %
                           rule[1])
            if rule[0] == 'one' and place.get(rule[1], 0) != \
                    place.get(rule[2], 0):
                out.append('%s and %s apart (their source asserts one '
                           'group)' % rule[1:])
        return out


class Evaluator(object):
    """The cost of a placement on the model's scenes (gplacesim.Model)."""

    def __init__(self, model, policy: int, page_us: float, call_us: float,
                 weights: Optional[Sequence[float]] = None):
        self.model = model
        self.policy = policy
        self.page_us = page_us
        self.call_us = call_us
        self.weights = list(weights or [1.0] * len(model.scenes))

    def vectors(self, place: Dict[str, int], gslot: Dict[int, int],
                gbytes: Dict[int, int]):
        from native import gplacesim as S
        slot = [0] * S.NG
        pages = [0] * S.NG
        for g, s in gslot.items():
            if g in gbytes:
                slot[g] = s
                pages[g] = (gbytes[g] + PAGE - 1) // PAGE
        groups = [{'slot': slot[g] or 1} for g in range(1, GLUE_BASE)]
        return self.model.vectors(place, groups, pages[1:GLUE_BASE],
                                  glue_base=GLUE_BASE)

    def scenes(self, place, gslot, gbytes) -> List[Dict[str, float]]:
        from native import gplacesim as S
        rs = self.model.run(self.vectors(place, gslot, gbytes), self.policy)
        for r in rs:
            t = max(r['tics'], 1)
            r['loads_a_tic'] = r['loads'] / t
            r['pages_a_tic'] = r['pages'] / t
            r['cross_a_tic'] = r['cross'] / t
            r['ms_a_tic'] = S.cost_of(r, self.page_us, self.call_us) / 1000
        return rs

    def cost(self, place, gslot, gbytes) -> float:
        return sum(w * r['ms_a_tic'] for w, r in zip(
            self.weights, self.scenes(place, gslot, gbytes)))


def evaluate(model, placement: Dict[str, Any], policy: int, page_us: float,
             call_us: float) -> List[Dict[str, float]]:
    """A placement.json's figures on the model's scenes (its groups'
    bytes from the measured sizes when the builds are there, else its own
    'bytes')."""
    place = dict(placement['routines'])
    gslot = {i: int(g['slot']) for i, g in
             enumerate(placement['groups'], 1)}
    try:
        sizer = Sizer(load_builds(), fcall_sites())
        gbytes = sizer.groups(place)
    except PlaceError:
        gbytes = {i: int(g.get('bytes', GROUP_ROOM)) for i, g in
                  enumerate(placement['groups'], 1)}
    return Evaluator(model, policy, page_us, call_us).scenes(
        place, gslot, gbytes)


def unit_calls(model, prob: Problem) -> Dict[int, int]:
    """Each unit's recorded calls in the model's scenes (the hot units:
    the search moves those)."""
    import array
    out: Dict[int, int] = {}
    for scene, m in zip(model.scenes, model.meta):
        names = m['units']
        a = array.array('H')
        a.frombytes((model.out / ('%s.ev' % scene)).read_bytes())
        if sys.byteorder != 'little':
            a.byteswap()
        counts: Dict[int, int] = {}
        for i in range(0, len(a), 3):
            if a[i] == 0:
                counts[a[i + 2]] = counts.get(a[i + 2], 0) + 1
        for local, n in counts.items():
            k = names[local]
            if k in prob.unit_of:
                u = prob.uidx[prob.unit_of[k]]
                out[u] = out.get(u, 0) + n
    return out


def search(prob: Problem, ev: Evaluator, hot: Sequence[int],
           sweeps: int = SWEEPS, anneal: int = ANNEAL, seed: int = SEED,
           say=print, t0: float = None) -> float:
    """The search (deterministic: the units in order of their calls, the
    candidates in order, a seeded annealing): a repair of the start while
    it breaks a rule; sweeps of single moves (each hot unit to the core,
    another group or a new one in either slot; each group to the other
    slot; two hot units exchanged) while the cost falls; an annealing
    (random moves of every unit, the hot ones three times as often,
    exchanges, slot flips, accepted by Metropolis' rule at a temperature
    falling from t0 ms a tic to 0) that keeps its best; the sweeps
    again."""
    import math
    import random
    sizer = prob.sizer
    room_total = GL.WR['CORE'][1] - GL.WR['CORE'][0] - CORE_MARGIN - \
        prob.reserve
    every = list(range(len(prob.units)))

    def state():
        place = prob.place()
        return place, sizer.groups(place)

    def violation(place, gb) -> int:
        """0 when every rule holds; else the bytes over and a weight a
        broken rule."""
        v = 0
        if len(gb) > MAX_GROUPS:
            v += 10000 * (len(gb) - MAX_GROUPS)
        v += sum(max(0, n - (GROUP_ROOM - GROUP_MARGIN))
                 for n in gb.values())
        table, fixed = sizer.core(place)
        v += max(0, table + max(fixed) - room_total)
        if not pack_ok([(gb[g] + PAGE - 1) // PAGE for g in sorted(gb)]):
            v += 5000
        return v + 10000 * len(prob.rule_problems(place))

    def cost_now() -> Tuple[float, bool]:
        place, gb = state()
        if violation(place, gb):
            return float('inf'), False
        return ev.cost(place, prob.gslot, gb), True

    def free_id() -> Optional[int]:
        used = set(prob.ug)
        for g in range(1, MAX_GROUPS + 1):
            if g not in used:
                return g
        return None

    def tidy() -> None:
        for g in list(prob.gslot):
            if g not in prob.ug:
                del prob.gslot[g]

    def repair() -> None:
        """Units moved out of what breaks a rule (an overfull group or
        core, a rule of the slots) while the breach shrinks, the cheapest
        move first (the start: an earlier wave's placement, its sizes
        grown since, or another tool's)."""
        rank = {u: i for i, u in enumerate(hot)}
        while True:
            place, gb = state()
            v = violation(place, gb)
            if v == 0:
                return
            table, fixed = sizer.core(place)
            bad = {g for g, n in gb.items()
                   if n > GROUP_ROOM - GROUP_MARGIN}
            if table + max(fixed) > room_total:
                bad.add(0)
            named = set()
            for p in prob.rule_problems(place):
                named |= {k for k in prob.keys if k in p}
            movers = sorted((u for u in every if prob.ug[u] in bad),
                            key=lambda u: (u in rank, -rank.get(u, 0),
                                           prob.units[u]))[:24]
            movers += sorted({prob.uidx[prob.unit_of[k]] for k in named})
            trial = None
            if len(gb) > MAX_GROUPS:
                # (too many groups: a group's units all into another)
                for a_ in sorted(gb, key=lambda g: (gb[g], g)):
                    mem = [u for u in every if prob.ug[u] == a_]
                    for h in sorted(set(prob.ug) | {0}):
                        if h == a_:
                            continue
                        for u in mem:
                            prob.ug[u] = h
                        pl, g2 = state()
                        v2 = violation(pl, g2)
                        if v2 < v:
                            c = ev.cost(pl, prob.gslot, g2)
                            if trial is None or (v2, c) < trial[:2]:
                                trial = (v2, c, tuple(mem), h, None)
                        for u in mem:
                            prob.ug[u] = a_
            for u in (movers if trial is None else ()):
                g0 = prob.ug[u]
                nid = free_id()
                cands = [(h, None) for h in sorted(set(prob.ug) | {0})
                         if h != g0]
                if nid is not None:
                    cands += [(nid, 1), (nid, 2)]
                for h, sl in cands:
                    prob.ug[u] = h
                    if sl:
                        prob.gslot[h] = sl
                    pl, g2 = state()
                    v2 = violation(pl, g2)
                    if v2 < v:
                        c = ev.cost(pl, prob.gslot, g2)
                        if trial is None or (v2, c) < trial[:2]:
                            trial = (v2, c, (u,), h, sl)
                    if sl:
                        prob.gslot.pop(h, None)
                    prob.ug[u] = g0
            if trial is None:
                raise PlaceError('the start placement cannot be repaired: '
                                 '%s' % prob.problems()[:4])
            _, _, us, h, sl = trial
            for u in us:
                prob.ug[u] = h
            if sl:
                prob.gslot[h] = sl
            tidy()
            say('repair: %s to %s (%d left over)' % (
                ', '.join(prob.units[u][0] for u in us),
                'the core' if h == 0 else 'group %d' % h, trial[0]))

    def sweep(best: float) -> Tuple[float, bool]:
        improved = False
        for u in hot:
            g0 = prob.ug[u]
            trial = None
            for h in sorted(set(prob.ug) | {0}):
                if h == g0:
                    continue
                prob.ug[u] = h
                c, ok = cost_now()
                if ok and c + 1e-6 < best and (trial is None or
                                                c < trial[0]):
                    trial = (c, h, None)
            prob.ug[u] = g0
            nid = free_id()
            if nid is not None:
                for sl in (1, 2):
                    prob.ug[u] = nid
                    prob.gslot[nid] = sl
                    c, ok = cost_now()
                    if ok and c + 1e-6 < best and (trial is None or
                                                    c < trial[0]):
                        trial = (c, nid, sl)
                prob.gslot.pop(nid, None)
                prob.ug[u] = g0
            if trial is not None:
                best, h, sl = trial
                prob.ug[u] = h
                if sl is not None:
                    prob.gslot[h] = sl
                tidy()
                improved = True
        for g in sorted(set(prob.ug) - {0}):
            s0 = prob.gslot[g]
            prob.gslot[g] = 3 - s0
            c, ok = cost_now()
            if ok and c + 1e-6 < best:
                best = c
                improved = True
            else:
                prob.gslot[g] = s0
        top = list(hot[:40])
        for i, u in enumerate(top):
            for v in top[i + 1:]:
                gu, gv = prob.ug[u], prob.ug[v]
                if gu == gv:
                    continue
                prob.ug[u], prob.ug[v] = gv, gu
                c, ok = cost_now()
                if ok and c + 1e-6 < best:
                    best = c
                    improved = True
                else:
                    prob.ug[u], prob.ug[v] = gu, gv
        tidy()
        return best, improved

    def sweeps_to(best: float, label: str) -> float:
        for n in range(sweeps):
            best, improved = sweep(best)
            say('%s sweep %d: %.3f ms a tic' % (label, n + 1, best))
            if not improved:
                break
        return best

    def annealing(best: float) -> float:
        rng = random.Random(seed)
        pool = list(hot) * 3 + every
        cur = best
        snap = (list(prob.ug), dict(prob.gslot), best)
        temp0 = t0 if t0 is not None else 0.02 * best
        for it in range(anneal):
            temp = temp0 * (1 - it / anneal) + 1e-9
            r = rng.random()
            undo = None
            if r < 0.7:
                u = pool[rng.randrange(len(pool))]
                g0 = prob.ug[u]
                cands = sorted(set(prob.ug) | {0})
                k = rng.randrange(len(cands) + 1)
                if k == len(cands):
                    h = free_id()
                    if h is None:
                        continue
                    prob.gslot[h] = rng.choice((1, 2))
                else:
                    h = cands[k]
                if h == g0:
                    continue
                prob.ug[u] = h
                undo = ('m', u, g0, h)
            elif r < 0.9:
                u = pool[rng.randrange(len(pool))]
                v = pool[rng.randrange(len(pool))]
                if prob.ug[u] == prob.ug[v]:
                    continue
                prob.ug[u], prob.ug[v] = prob.ug[v], prob.ug[u]
                undo = ('s', u, v)
            else:
                gs = sorted(set(prob.ug) - {0})
                if not gs:
                    continue
                g = gs[rng.randrange(len(gs))]
                prob.gslot[g] = 3 - prob.gslot[g]
                undo = ('f', g)
            c, ok = cost_now()
            if ok and (c <= cur or rng.random() < math.exp(
                    -(c - cur) / temp)):
                cur = c
                tidy()
                if c + 1e-9 < snap[2]:
                    snap = (list(prob.ug), dict(prob.gslot), c)
            else:
                if undo[0] == 'm':
                    prob.ug[undo[1]] = undo[2]
                    if undo[3] not in prob.ug:
                        prob.gslot.pop(undo[3], None)
                elif undo[0] == 's':
                    u, v = undo[1], undo[2]
                    prob.ug[u], prob.ug[v] = prob.ug[v], prob.ug[u]
                else:
                    prob.gslot[undo[1]] = 3 - prob.gslot[undo[1]]
            if (it + 1) % 10000 == 0:
                say('annealing %d: %.3f ms a tic (best %.3f)' % (
                    it + 1, cur, snap[2]))
        prob.ug[:] = snap[0]
        prob.gslot.clear()
        prob.gslot.update(snap[1])
        return snap[2]

    say('%d units, %d of them called in the scenes' % (len(prob.units),
                                                       len(hot)))
    repair()
    best, ok = cost_now()
    if not ok:
        raise PlaceError('the start placement breaks a rule: %s' %
                         prob.problems()[:4])
    say('start: %.3f ms a tic (the training scenes summed)' % best)
    best = sweeps_to(best, 'first')
    if anneal and hot:
        best = annealing(best)
        say('annealing (%d steps, seed %d): %.3f ms a tic' % (anneal, seed,
                                                              best))
        best = sweeps_to(best, 'last')
    return best


def renumbered(prob: Problem) -> Tuple[Dict[str, int], List[int]]:
    """The groups numbered 1..n in their first routine's order (the keys'
    order): (each key's group, each group's slot)."""
    place = prob.place()
    order: List[int] = []
    for k in prob.keys:
        g = place[k]
        if g and g not in order:
            order.append(g)
    new = {g: i for i, g in enumerate(order, 1)}
    return ({k: new.get(g, 0) for k, g in place.items()},
            [prob.gslot[g] for g in order])


def start_placement(placement: Optional[Dict[str, Any]], sizer: Sizer
                    ) -> Tuple[Dict[str, int], Dict[int, int]]:
    if placement is None:
        placement = GL.placement_of()
    place = {k: int(g) for k, g in placement.get('routines', {}).items()}
    slots = {i: int(g['slot']) for i, g in
             enumerate(placement.get('groups', []), 1)}
    if not placement.get('groups'):
        place = dict(sizer.cur)
    return place, slots


def train(placement: Optional[Dict[str, Any]] = None,
          page_us: float = PAGE_US, call_us: float = CALL_US,
          restore: str = RESTORE, train_scenes: Sequence[str] = TRAIN,
          hold_scenes: Sequence[str] = HOLD, sweeps: int = SWEEPS,
          anneal: int = ANNEAL, seed: int = SEED, do_search: bool = True,
          out: Optional[Path] = None, say=print,
          core_reserve: int = CORE_RESERVE) -> Dict[str, Any]:
    """The trained placement (the module's header)."""
    from native import gcallgraph as CG, gplacesim as S, gplacerec as REC
    out = out or REC.OUT
    builds = load_builds()
    if restore == 'auto':
        restore = restore_of(builds)
    policy = S.POLICIES[restore]
    sites = fcall_sites()
    sizer = Sizer(builds, sites)
    graph = CG.load(write=False)
    place0, slots0 = start_placement(placement, sizer)
    module_of: Dict[str, str] = {}
    for b in builds:
        for k, m in b.module_of.items():
            module_of.setdefault(k, m)
    prob = Problem(sizer, graph, sites, place0, slots0, module_of,
                   hard_refs(), core_reserve, placement_asserts())
    have = [s for s in list(train_scenes) + list(hold_scenes)
            if (out / ('%s.ev' % s)).exists()]
    tr = [s for s in train_scenes if s in have]
    ho = [s for s in hold_scenes if s in have]
    if not tr:
        raise PlaceError('no training scene recorded (python3 tools/native/'
                         'gplacerec.py %s)' % ' '.join(train_scenes))
    with S.Model(tr + ho, out) as every:
        evall = Evaluator(every, policy, page_us, call_us)
        place = prob.place()
        before = evall.scenes(place, prob.gslot, sizer.groups(place))
        if do_search:
            with S.Model(tr, out) as model:
                ev = Evaluator(model, policy, page_us, call_us)
                calls = unit_calls(model, prob)
                hot = sorted((u for u in calls if calls[u] > 0),
                             key=lambda u: (-calls[u], prob.units[u]))
                search(prob, ev, hot, sweeps, anneal, seed, say)
        problems = prob.problems()
        if problems:
            raise PlaceError('the placement breaks: %s' % problems[:6])
        place = prob.place()
        gb = sizer.groups(place)
        after = evall.scenes(place, prob.gslot, gb)
        causes = every.causes(evall.vectors(place, prob.gslot, gb), policy)
    rules = prob.rule_problems(prob.place())
    final, slots = renumbered(prob)
    table, fixed = sizer.core(final)
    gbytes = sizer.groups(final)
    groups = []
    for i, sl in enumerate(slots, 1):
        groups.append({'slot': sl, 'bytes': gbytes.get(i, 0),
                       'routines': [k for k in prob.keys if final[k] == i]})
    core = [k for k in prob.keys if final[k] == 0]
    gc = final.get(CHASE, 0)
    res = {'format': 'game-placement 1', 'groups': groups,
           'routines': {k: g for k, g in final.items() if g},
           'core': core, 'core_bytes': table,
           'core_room': GL.WR['CORE'][1] - GL.WR['CORE'][0] - CORE_MARGIN -
           max(fixed),
           'core_reserve': core_reserve,
           'core_fixed': {b.label: f for b, f in zip(builds, fixed)},
           'play_stale': play_stale() if any(b.label == 'play'
                                             for b in builds) else [],
           'a_chase_rule': not any('A_Chase' in p for p in rules),
           'apart_rule': not any('APART' in p for p in rules),
           'a_chase_in_core': gc == 0,
           'model': {'page_us': page_us, 'call_us': call_us,
                     'restore': restore, 'train': tr, 'hold': ho,
                     'sweeps': sweeps, 'anneal': anneal, 'seed': seed,
                     'search': do_search,
                     'scenes': {s: {'before': _fig(b), 'after': _fig(a)}
                                for s, b, a in zip(tr + ho, before, after)},
                     'top_loads': _top_causes(causes, after, tr + ho)},
           'size_source': 'measured: %s' % ', '.join(b.label for b in
                                                      builds),
           'margins': {'group': GROUP_MARGIN, 'core': CORE_MARGIN}}
    return res


def _fig(r: Dict[str, float]) -> Dict[str, float]:
    return {'loads_a_tic': round(r['loads_a_tic'], 2),
            'pages_a_tic': round(r['pages_a_tic'], 2),
            'cross_a_tic': round(r['cross_a_tic'], 2),
            'ms_a_tic': round(r['ms_a_tic'], 3)}


def _top_causes(causes, after, scenes) -> Dict[str, List]:
    tics = {s: max(r['tics'], 1) for s, r in zip(scenes, after)}
    out: Dict[str, List] = {}
    for scene, kind, a, b, loads, pages in causes:
        out.setdefault(scene, []).append(
            [kind, a, b, round(loads / tics[scene], 2),
             round(pages / tics[scene], 2)])
    return {s: sorted(v, key=lambda x: -x[4])[:12] for s, v in out.items()}


def report(res: Dict[str, Any]) -> List[str]:
    lines = ['core: %d routines, %d of %d B%s (fixed core code: %s)' % (
        len(res['core']), res['core_bytes'], res['core_room'],
        ', %d B of them kept free' % res['core_reserve']
        if res.get('core_reserve') else '',
        ', '.join('%s %d B' % kv for kv in res.get('core_fixed', {})
                  .items()))]
    if res.get('play_stale'):
        lines.append('WARNING: the play link is older than %s: its fixed '
                     'core code is the old link\'s (python3 tools/native/'
                     'playdisk.py, then this again)'
                     % ', '.join(res['play_stale']))
    for i, g in enumerate(res['groups'], 1):
        lines.append('group %d: slot %d, %d routines, %d B' % (
            i, g['slot'], len(g['routines']), g['bytes']))
    m = res.get('model')
    if m:
        lines.append('cost: %.1f us a page, %.1f us a call through fc_call, '
                     'the %s restore' % (m['page_us'], m['call_us'],
                                        m['restore']))
        for s, v in m['scenes'].items():
            b, a = v['before'], v['after']
            lines.append('  %-7s %-5s loads a tic %7.2f -> %7.2f   pages a '
                         'tic %8.2f -> %8.2f   ms a tic %8.3f -> %8.3f' % (
                             s, 'train' if s in m['train'] else 'hold',
                             b['loads_a_tic'], a['loads_a_tic'],
                             b['pages_a_tic'], a['pages_a_tic'],
                             b['ms_a_tic'], a['ms_a_tic']))
    lines.append('A_Chase\'s rule %s; the APART pairs %s' % (
        'kept' if res['a_chase_rule'] else 'BROKEN',
        'apart' if res['apart_rule'] else 'BROKEN'))
    return lines


def run(write: bool = False, placement: Optional[Path] = None,
        **kw) -> Dict[str, Any]:
    start = json.loads(placement.read_text()) if placement else None
    res = train(start, **kw)
    if write:
        PLACEMENT.parent.mkdir(parents=True, exist_ok=True)
        PLACEMENT.write_text(json.dumps(res, indent=1) + '\n')
    return res


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--placement', type=Path,
                        help='the start (a placement.json); with '
                             '--no-search the placement itself')
    parser.add_argument('--no-search', action='store_true')
    parser.add_argument('--page-us', type=float, default=PAGE_US)
    parser.add_argument('--call-us', type=float, default=CALL_US)
    parser.add_argument('--restore', choices=('auto', 'eager', 'lazy'),
                        default=RESTORE)
    parser.add_argument('--train', default=','.join(TRAIN))
    parser.add_argument('--hold', default=','.join(HOLD))
    parser.add_argument('--sweeps', type=int, default=SWEEPS)
    parser.add_argument('--anneal', type=int, default=ANNEAL)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--core-reserve', type=int, default=CORE_RESERVE,
                        help='core bytes kept free for growth the builds '
                             'do not have yet')
    parser.add_argument('--json', type=Path,
                        help='also write the result here')
    parser.add_argument('--traces', type=Path,
                        help='the recorded scenes\' directory (default '
                             'build/native/game/gplace)')
    parser.add_argument('--heuristic', action='store_true',
                        help='waves 1-6\'s placement (heat and survey)')
    parser.add_argument('--sizes', type=Path)
    parser.add_argument('--heat', type=Path)
    parser.add_argument('--runs', default='demo3,demo1,demo2')
    parser.add_argument('--measure', default=None,
                        help='(--heuristic) DIR/NAME of a test build: the '
                             'built parts\' routines and the core\'s fixed '
                             'bytes measured there (grun.routine_sizes)')
    args = parser.parse_args(argv)
    if args.heuristic:
        return main_heuristic(args)
    try:
        res = run(args.write, args.placement, page_us=args.page_us,
                  call_us=args.call_us, restore=args.restore,
                  train_scenes=[s for s in args.train.split(',') if s],
                  hold_scenes=[s for s in args.hold.split(',') if s],
                  sweeps=args.sweeps, anneal=args.anneal, seed=args.seed,
                  do_search=not args.no_search,
                  core_reserve=args.core_reserve, out=args.traces)
    except PlaceError as e:
        print('gplace: %s' % e, file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(res, indent=1) + '\n')
    print('\n'.join(report(res)))
    return 0 if res['a_chase_rule'] and res['apart_rule'] else 1


def main_heuristic(args) -> int:
    measure = None
    if args.measure:
        mp = Path(args.measure)
        measure = (mp.parent, mp.name)
    res = run_heuristic(args.write, args.sizes, args.heat,
                        args.runs.split(','), measure)
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
