#!/usr/bin/env python3
"""Generate the game's info tables (states, mobj types) and its far tables.

    python3 tools/gen_info.py            # writes src/game/info.h, info.c, gtables.s
    python3 tools/gen_info.py --check    # exit 1 if the checked-in files differ

Doom's play simulation is driven by two tables, `states[]` (sprite, frame,
tics, action, next state) and `mobjinfo[]` (one record per thing type).
Vanilla Doom has 967 states and 137 types; the Appletini port keeps only
what episode 1 can show (DESIGN.md sections 1 and 9): the player and his
weapons (fist, chainsaw, pistol, shotgun, chaingun, rocket launcher,
plasma rifle; no BFG, no super shotgun), the E1 monsters (zombieman,
shotgun guy, imp, demon, spectre, lost soul, cacodemon, baron) with their
projectiles, the barrel, puffs, blood, fogs, the teleport destination,
every pickup, and the decorations whose sprites the converter kept
(tools/wad2a2.py). Raise states (the arch-vile) are dropped.

The source below is written in the same terms as vanilla's info.c (names,
order, values) so that the vanilla sources can be read next to the port;
tests/test_game_info.py compares it field by field with a vanilla info.c
when one is at hand (chocolate-doom's src/doom/info.c, GPL) and with
ZDoom's DECORATE sequences.

STATES lines:   NAME  SPRITE FRAME[*] TICS ACTION NEXT
    FRAME is the frame letter, * = full bright (Doom's FF_FULLBRIGHT);
    TICS -1 = forever; ACTION '-' = none. The order is vanilla's.
MOBJS lines:    MT_NAME key=value ...
    Only the fields that differ from DEFAULTS are given. Radius, height and
    speed are in map units (Doom's radius 20*FRACUNIT is radius=20; a
    missile's speed 10*FRACUNIT is speed=10: the C side knows that
    MF_MISSILE types scale theirs); sounds are sfx_ names without the
    prefix; flags are MF_ names without the prefix.

Generated C (src/game/info.h, info.c; cc65 and host gcc):
  - enums statenum_t (S_*), mobjtype_t (MT_*), sfx (sfx_*, vanilla's full
    order so the sound part can map them), action numbers (AC_*);
  - the states as five byte planes (cc65 indexes a byte array with one
    instruction, a struct array with a multiply): st_sprite (SPR_ numbers
    of doomdata.h), st_frame (letter index, bit 7 full bright, as the
    render packet wants it), st_tics (255 = -1), st_action (AC_*; bit 7
    "quiet": neither the state nor any state after it has an action, so
    a thing in it can live on as a static, p_mobj.c), st_next (u16);
  - mobjinfo[] as a 34-byte struct, doomednums in a
    separate table used only by the map spawner;
  - the action tables: mobj actions (void f(mobj_t*)) and weapon actions
    (void f(player_t*, pspdef_t*)), indexed by AC_ number.

The far tables are also written as C arrays for the host build of the
game (tests/host/gtables_host.h).

Generated assembly (src/game/gtables.s): segment GFAR, the game's far
tables, copied at boot into the game's own RamWorks bank (DESIGN.md 9):
finesine for the first quarter turn (2,048 x u16 = vanilla finesine[0..2047],
the rest by symmetry, which vanilla's table keeps to +-1/65536 at 26 of
8,192 angles), tantoangle (2,049 x u16: vanilla's angle >> 16). The random
table (vanilla's rndtable) goes to RODATA (it is read every P_Random).
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
OUT_H = PROJECT / "src/game/info.h"
OUT_C = PROJECT / "src/game/info.c"
OUT_S = PROJECT / "src/game/gtables.s"
OUT_HOST = PROJECT / "tests/host/gtables_host.h"

FLAGS = dict(SPECIAL=0x1, SOLID=0x2, SHOOTABLE=0x4, NOSECTOR=0x8, NOBLOCKMAP=0x10,
             AMBUSH=0x20, JUSTHIT=0x40, JUSTATTACKED=0x80, SPAWNCEILING=0x100,
             NOGRAVITY=0x200, DROPOFF=0x400, PICKUP=0x800, NOCLIP=0x1000, SLIDE=0x2000,
             FLOAT=0x4000, TELEPORT=0x8000, MISSILE=0x10000, DROPPED=0x20000,
             SHADOW=0x40000, NOBLOOD=0x80000, CORPSE=0x100000, INFLOAT=0x200000,
             COUNTKILL=0x400000, COUNTITEM=0x800000, SKULLFLY=0x1000000,
             NOTDMATCH=0x2000000)

# vanilla's sfxenum_t, in order (sounds.h)
SFX = """None pistol shotgn sgcock dshtgn dbopn dbcls dbload plasma bfg sawup sawidl
sawful sawhit rlaunc rxplod firsht firxpl pstart pstop doropn dorcls stnmov swtchn
swtchx plpain dmpain popain vipain mnpain pepain slop itemup wpnup oof telept posit1
posit2 posit3 bgsit1 bgsit2 sgtsit cacsit brssit cybsit spisit bspsit kntsit vilsit
mansit pesit sklatk sgtatk skepch vilatk claw skeswg pldeth pdiehi podth1 podth2
podth3 bgdth1 bgdth2 sgtdth cacdth skldth brsdth cybdth spidth bspdth vildth kntdth
pedth skedth posact bgact dmact bspact bspwlk vilact noway barexp punch hoof metal
chgun tink bdopn bdcls itmbk flame flamst getpow bospit boscub bossit bospn bosdth
manatk mandth sssit ssdth keenpn keendt skeact skesit skeatk radio""".split()

# actions taking a mobj (p_enemy.c and friends: the MONSTERS part) and
# actions taking a player and a psprite (p_pspr.c: the core)
MOBJ_ACTIONS = """A_Look A_Chase A_FaceTarget A_PosAttack A_SPosAttack A_TroopAttack
A_SargAttack A_HeadAttack A_BruisAttack A_SkullAttack A_Scream A_XScream A_Pain
A_Fall A_Explode A_BossDeath A_PlayerScream""".split()
WEAPON_ACTIONS = """A_Light0 A_WeaponReady A_Lower A_Raise A_Punch A_ReFire A_FirePistol
A_Light1 A_FireShotgun A_Light2 A_FireCGun A_GunFlash A_FireMissile A_Saw
A_FirePlasma""".split()

DEFAULTS = dict(doomednum="-1", spawnstate="S_NULL", spawnhealth="1000", seestate="S_NULL",
                seesound="None", reactiontime="8", attacksound="None", painstate="S_NULL",
                painchance="0", painsound="None", meleestate="S_NULL", missilestate="S_NULL",
                deathstate="S_NULL", xdeathstate="S_NULL", deathsound="None", speed="0",
                radius="20", height="16", mass="100", damage="0", activesound="None", flags="0")
STATE_FIELDS = ("spawnstate", "seestate", "painstate", "meleestate", "missilestate",
                "deathstate", "xdeathstate")
SOUND_FIELDS = ("seesound", "attacksound", "painsound", "deathsound", "activesound")

# --- the compact source ------------------------------------------------------------

STATES = """
S_NULL             TROO A   -1 -               S_NULL
S_LIGHTDONE        SHTG E    0 A_Light0        S_NULL
S_PUNCH            PUNG A    1 A_WeaponReady   S_PUNCH
S_PUNCHDOWN        PUNG A    1 A_Lower         S_PUNCHDOWN
S_PUNCHUP          PUNG A    1 A_Raise         S_PUNCHUP
S_PUNCH1           PUNG B    4 -               S_PUNCH2
S_PUNCH2           PUNG C    4 A_Punch         S_PUNCH3
S_PUNCH3           PUNG D    5 -               S_PUNCH4
S_PUNCH4           PUNG C    4 -               S_PUNCH5
S_PUNCH5           PUNG B    5 A_ReFire        S_PUNCH
S_PISTOL           PISG A    1 A_WeaponReady   S_PISTOL
S_PISTOLDOWN       PISG A    1 A_Lower         S_PISTOLDOWN
S_PISTOLUP         PISG A    1 A_Raise         S_PISTOLUP
S_PISTOL1          PISG A    4 -               S_PISTOL2
S_PISTOL2          PISG B    6 A_FirePistol    S_PISTOL3
S_PISTOL3          PISG C    4 -               S_PISTOL4
S_PISTOL4          PISG B    5 A_ReFire        S_PISTOL
S_PISTOLFLASH      PISF A*   7 A_Light1        S_LIGHTDONE
S_SGUN             SHTG A    1 A_WeaponReady   S_SGUN
S_SGUNDOWN         SHTG A    1 A_Lower         S_SGUNDOWN
S_SGUNUP           SHTG A    1 A_Raise         S_SGUNUP
S_SGUN1            SHTG A    3 -               S_SGUN2
S_SGUN2            SHTG A    7 A_FireShotgun   S_SGUN3
S_SGUN3            SHTG B    5 -               S_SGUN4
S_SGUN4            SHTG C    5 -               S_SGUN5
S_SGUN5            SHTG D    4 -               S_SGUN6
S_SGUN6            SHTG C    5 -               S_SGUN7
S_SGUN7            SHTG B    5 -               S_SGUN8
S_SGUN8            SHTG A    3 -               S_SGUN9
S_SGUN9            SHTG A    7 A_ReFire        S_SGUN
S_SGUNFLASH1       SHTF A*   4 A_Light1        S_SGUNFLASH2
S_SGUNFLASH2       SHTF B*   3 A_Light2        S_LIGHTDONE
S_CHAIN            CHGG A    1 A_WeaponReady   S_CHAIN
S_CHAINDOWN        CHGG A    1 A_Lower         S_CHAINDOWN
S_CHAINUP          CHGG A    1 A_Raise         S_CHAINUP
S_CHAIN1           CHGG A    4 A_FireCGun      S_CHAIN2
S_CHAIN2           CHGG B    4 A_FireCGun      S_CHAIN3
S_CHAIN3           CHGG B    0 A_ReFire        S_CHAIN
S_CHAINFLASH1      CHGF A*   5 A_Light1        S_LIGHTDONE
S_CHAINFLASH2      CHGF B*   5 A_Light2        S_LIGHTDONE
S_MISSILE          MISG A    1 A_WeaponReady   S_MISSILE
S_MISSILEDOWN      MISG A    1 A_Lower         S_MISSILEDOWN
S_MISSILEUP        MISG A    1 A_Raise         S_MISSILEUP
S_MISSILE1         MISG B    8 A_GunFlash      S_MISSILE2
S_MISSILE2         MISG B   12 A_FireMissile   S_MISSILE3
S_MISSILE3         MISG B    0 A_ReFire        S_MISSILE
S_MISSILEFLASH1    MISF A*   3 A_Light1        S_MISSILEFLASH2
S_MISSILEFLASH2    MISF B*   4 -               S_MISSILEFLASH3
S_MISSILEFLASH3    MISF C*   4 A_Light2        S_MISSILEFLASH4
S_MISSILEFLASH4    MISF D*   4 A_Light2        S_LIGHTDONE
S_SAW              SAWG C    4 A_WeaponReady   S_SAWB
S_SAWB             SAWG D    4 A_WeaponReady   S_SAW
S_SAWDOWN          SAWG C    1 A_Lower         S_SAWDOWN
S_SAWUP            SAWG C    1 A_Raise         S_SAWUP
S_SAW1             SAWG A    4 A_Saw           S_SAW2
S_SAW2             SAWG B    4 A_Saw           S_SAW3
S_SAW3             SAWG B    0 A_ReFire        S_SAW
S_PLASMA           PLSG A    1 A_WeaponReady   S_PLASMA
S_PLASMADOWN       PLSG A    1 A_Lower         S_PLASMADOWN
S_PLASMAUP         PLSG A    1 A_Raise         S_PLASMAUP
S_PLASMA1          PLSG A    3 A_FirePlasma    S_PLASMA2
S_PLASMA2          PLSG B   20 A_ReFire        S_PLASMA
S_PLASMAFLASH1     PLSF A*   4 A_Light1        S_LIGHTDONE
S_PLASMAFLASH2     PLSF B*   4 A_Light1        S_LIGHTDONE
S_BLOOD1           BLUD C    8 -               S_BLOOD2
S_BLOOD2           BLUD B    8 -               S_BLOOD3
S_BLOOD3           BLUD A    8 -               S_NULL
S_PUFF1            PUFF A*   4 -               S_PUFF2
S_PUFF2            PUFF B    4 -               S_PUFF3
S_PUFF3            PUFF C    4 -               S_PUFF4
S_PUFF4            PUFF D    4 -               S_NULL
S_TBALL1           BAL1 A*   4 -               S_TBALL2
S_TBALL2           BAL1 B*   4 -               S_TBALL1
S_TBALLX1          BAL1 C*   6 -               S_TBALLX2
S_TBALLX2          BAL1 D*   6 -               S_TBALLX3
S_TBALLX3          BAL1 E*   6 -               S_NULL
S_RBALL1           BAL2 A*   4 -               S_RBALL2
S_RBALL2           BAL2 B*   4 -               S_RBALL1
S_RBALLX1          BAL2 C*   6 -               S_RBALLX2
S_RBALLX2          BAL2 D*   6 -               S_RBALLX3
S_RBALLX3          BAL2 E*   6 -               S_NULL
S_PLASBALL         PLSS A*   6 -               S_PLASBALL2
S_PLASBALL2        PLSS B*   6 -               S_PLASBALL
S_PLASEXP          PLSE A*   4 -               S_PLASEXP2
S_PLASEXP2         PLSE B*   4 -               S_PLASEXP3
S_PLASEXP3         PLSE C*   4 -               S_PLASEXP4
S_PLASEXP4         PLSE D*   4 -               S_PLASEXP5
S_PLASEXP5         PLSE E*   4 -               S_NULL
S_ROCKET           MISL A*   1 -               S_ROCKET
S_EXPLODE1         MISL B*   8 A_Explode       S_EXPLODE2
S_EXPLODE2         MISL C*   6 -               S_EXPLODE3
S_EXPLODE3         MISL D*   4 -               S_NULL
S_TFOG             TFOG A*   6 -               S_TFOG01
S_TFOG01           TFOG B*   6 -               S_TFOG02
S_TFOG02           TFOG A*   6 -               S_TFOG2
S_TFOG2            TFOG B*   6 -               S_TFOG3
S_TFOG3            TFOG C*   6 -               S_TFOG4
S_TFOG4            TFOG D*   6 -               S_TFOG5
S_TFOG5            TFOG E*   6 -               S_TFOG6
S_TFOG6            TFOG F*   6 -               S_TFOG7
S_TFOG7            TFOG G*   6 -               S_TFOG8
S_TFOG8            TFOG H*   6 -               S_TFOG9
S_TFOG9            TFOG I*   6 -               S_TFOG10
S_TFOG10           TFOG J*   6 -               S_NULL
S_IFOG             IFOG A*   6 -               S_IFOG01
S_IFOG01           IFOG B*   6 -               S_IFOG02
S_IFOG02           IFOG A*   6 -               S_IFOG2
S_IFOG2            IFOG B*   6 -               S_IFOG3
S_IFOG3            IFOG C*   6 -               S_IFOG4
S_IFOG4            IFOG D*   6 -               S_IFOG5
S_IFOG5            IFOG E*   6 -               S_NULL
S_PLAY             PLAY A   -1 -               S_NULL
S_PLAY_RUN1        PLAY A    4 -               S_PLAY_RUN2
S_PLAY_RUN2        PLAY B    4 -               S_PLAY_RUN3
S_PLAY_RUN3        PLAY C    4 -               S_PLAY_RUN4
S_PLAY_RUN4        PLAY D    4 -               S_PLAY_RUN1
S_PLAY_ATK1        PLAY E   12 -               S_PLAY
S_PLAY_ATK2        PLAY F*   6 -               S_PLAY_ATK1
S_PLAY_PAIN        PLAY G    4 -               S_PLAY_PAIN2
S_PLAY_PAIN2       PLAY G    4 A_Pain          S_PLAY
S_PLAY_DIE1        PLAY H   10 -               S_PLAY_DIE2
S_PLAY_DIE2        PLAY I   10 A_PlayerScream  S_PLAY_DIE3
S_PLAY_DIE3        PLAY J   10 A_Fall          S_PLAY_DIE4
S_PLAY_DIE4        PLAY K   10 -               S_PLAY_DIE5
S_PLAY_DIE5        PLAY L   10 -               S_PLAY_DIE6
S_PLAY_DIE6        PLAY M   10 -               S_PLAY_DIE7
S_PLAY_DIE7        PLAY N   -1 -               S_NULL
S_PLAY_XDIE1       PLAY O    5 -               S_PLAY_XDIE2
S_PLAY_XDIE2       PLAY P    5 A_XScream       S_PLAY_XDIE3
S_PLAY_XDIE3       PLAY Q    5 A_Fall          S_PLAY_XDIE4
S_PLAY_XDIE4       PLAY R    5 -               S_PLAY_XDIE5
S_PLAY_XDIE5       PLAY S    5 -               S_PLAY_XDIE6
S_PLAY_XDIE6       PLAY T    5 -               S_PLAY_XDIE7
S_PLAY_XDIE7       PLAY U    5 -               S_PLAY_XDIE8
S_PLAY_XDIE8       PLAY V    5 -               S_PLAY_XDIE9
S_PLAY_XDIE9       PLAY W   -1 -               S_NULL
S_POSS_STND        POSS A   10 A_Look          S_POSS_STND2
S_POSS_STND2       POSS B   10 A_Look          S_POSS_STND
S_POSS_RUN1        POSS A    4 A_Chase         S_POSS_RUN2
S_POSS_RUN2        POSS A    4 A_Chase         S_POSS_RUN3
S_POSS_RUN3        POSS B    4 A_Chase         S_POSS_RUN4
S_POSS_RUN4        POSS B    4 A_Chase         S_POSS_RUN5
S_POSS_RUN5        POSS C    4 A_Chase         S_POSS_RUN6
S_POSS_RUN6        POSS C    4 A_Chase         S_POSS_RUN7
S_POSS_RUN7        POSS D    4 A_Chase         S_POSS_RUN8
S_POSS_RUN8        POSS D    4 A_Chase         S_POSS_RUN1
S_POSS_ATK1        POSS E   10 A_FaceTarget    S_POSS_ATK2
S_POSS_ATK2        POSS F    8 A_PosAttack     S_POSS_ATK3
S_POSS_ATK3        POSS E    8 -               S_POSS_RUN1
S_POSS_PAIN        POSS G    3 -               S_POSS_PAIN2
S_POSS_PAIN2       POSS G    3 A_Pain          S_POSS_RUN1
S_POSS_DIE1        POSS H    5 -               S_POSS_DIE2
S_POSS_DIE2        POSS I    5 A_Scream        S_POSS_DIE3
S_POSS_DIE3        POSS J    5 A_Fall          S_POSS_DIE4
S_POSS_DIE4        POSS K    5 -               S_POSS_DIE5
S_POSS_DIE5        POSS L   -1 -               S_NULL
S_POSS_XDIE1       POSS M    5 -               S_POSS_XDIE2
S_POSS_XDIE2       POSS N    5 A_XScream       S_POSS_XDIE3
S_POSS_XDIE3       POSS O    5 A_Fall          S_POSS_XDIE4
S_POSS_XDIE4       POSS P    5 -               S_POSS_XDIE5
S_POSS_XDIE5       POSS Q    5 -               S_POSS_XDIE6
S_POSS_XDIE6       POSS R    5 -               S_POSS_XDIE7
S_POSS_XDIE7       POSS S    5 -               S_POSS_XDIE8
S_POSS_XDIE8       POSS T    5 -               S_POSS_XDIE9
S_POSS_XDIE9       POSS U   -1 -               S_NULL
S_SPOS_STND        SPOS A   10 A_Look          S_SPOS_STND2
S_SPOS_STND2       SPOS B   10 A_Look          S_SPOS_STND
S_SPOS_RUN1        SPOS A    3 A_Chase         S_SPOS_RUN2
S_SPOS_RUN2        SPOS A    3 A_Chase         S_SPOS_RUN3
S_SPOS_RUN3        SPOS B    3 A_Chase         S_SPOS_RUN4
S_SPOS_RUN4        SPOS B    3 A_Chase         S_SPOS_RUN5
S_SPOS_RUN5        SPOS C    3 A_Chase         S_SPOS_RUN6
S_SPOS_RUN6        SPOS C    3 A_Chase         S_SPOS_RUN7
S_SPOS_RUN7        SPOS D    3 A_Chase         S_SPOS_RUN8
S_SPOS_RUN8        SPOS D    3 A_Chase         S_SPOS_RUN1
S_SPOS_ATK1        SPOS E   10 A_FaceTarget    S_SPOS_ATK2
S_SPOS_ATK2        SPOS F*  10 A_SPosAttack    S_SPOS_ATK3
S_SPOS_ATK3        SPOS E   10 -               S_SPOS_RUN1
S_SPOS_PAIN        SPOS G    3 -               S_SPOS_PAIN2
S_SPOS_PAIN2       SPOS G    3 A_Pain          S_SPOS_RUN1
S_SPOS_DIE1        SPOS H    5 -               S_SPOS_DIE2
S_SPOS_DIE2        SPOS I    5 A_Scream        S_SPOS_DIE3
S_SPOS_DIE3        SPOS J    5 A_Fall          S_SPOS_DIE4
S_SPOS_DIE4        SPOS K    5 -               S_SPOS_DIE5
S_SPOS_DIE5        SPOS L   -1 -               S_NULL
S_SPOS_XDIE1       SPOS M    5 -               S_SPOS_XDIE2
S_SPOS_XDIE2       SPOS N    5 A_XScream       S_SPOS_XDIE3
S_SPOS_XDIE3       SPOS O    5 A_Fall          S_SPOS_XDIE4
S_SPOS_XDIE4       SPOS P    5 -               S_SPOS_XDIE5
S_SPOS_XDIE5       SPOS Q    5 -               S_SPOS_XDIE6
S_SPOS_XDIE6       SPOS R    5 -               S_SPOS_XDIE7
S_SPOS_XDIE7       SPOS S    5 -               S_SPOS_XDIE8
S_SPOS_XDIE8       SPOS T    5 -               S_SPOS_XDIE9
S_SPOS_XDIE9       SPOS U   -1 -               S_NULL
S_TROO_STND        TROO A   10 A_Look          S_TROO_STND2
S_TROO_STND2       TROO B   10 A_Look          S_TROO_STND
S_TROO_RUN1        TROO A    3 A_Chase         S_TROO_RUN2
S_TROO_RUN2        TROO A    3 A_Chase         S_TROO_RUN3
S_TROO_RUN3        TROO B    3 A_Chase         S_TROO_RUN4
S_TROO_RUN4        TROO B    3 A_Chase         S_TROO_RUN5
S_TROO_RUN5        TROO C    3 A_Chase         S_TROO_RUN6
S_TROO_RUN6        TROO C    3 A_Chase         S_TROO_RUN7
S_TROO_RUN7        TROO D    3 A_Chase         S_TROO_RUN8
S_TROO_RUN8        TROO D    3 A_Chase         S_TROO_RUN1
S_TROO_ATK1        TROO E    8 A_FaceTarget    S_TROO_ATK2
S_TROO_ATK2        TROO F    8 A_FaceTarget    S_TROO_ATK3
S_TROO_ATK3        TROO G    6 A_TroopAttack   S_TROO_RUN1
S_TROO_PAIN        TROO H    2 -               S_TROO_PAIN2
S_TROO_PAIN2       TROO H    2 A_Pain          S_TROO_RUN1
S_TROO_DIE1        TROO I    8 -               S_TROO_DIE2
S_TROO_DIE2        TROO J    8 A_Scream        S_TROO_DIE3
S_TROO_DIE3        TROO K    6 -               S_TROO_DIE4
S_TROO_DIE4        TROO L    6 A_Fall          S_TROO_DIE5
S_TROO_DIE5        TROO M   -1 -               S_NULL
S_TROO_XDIE1       TROO N    5 -               S_TROO_XDIE2
S_TROO_XDIE2       TROO O    5 A_XScream       S_TROO_XDIE3
S_TROO_XDIE3       TROO P    5 -               S_TROO_XDIE4
S_TROO_XDIE4       TROO Q    5 A_Fall          S_TROO_XDIE5
S_TROO_XDIE5       TROO R    5 -               S_TROO_XDIE6
S_TROO_XDIE6       TROO S    5 -               S_TROO_XDIE7
S_TROO_XDIE7       TROO T    5 -               S_TROO_XDIE8
S_TROO_XDIE8       TROO U   -1 -               S_NULL
S_SARG_STND        SARG A   10 A_Look          S_SARG_STND2
S_SARG_STND2       SARG B   10 A_Look          S_SARG_STND
S_SARG_RUN1        SARG A    2 A_Chase         S_SARG_RUN2
S_SARG_RUN2        SARG A    2 A_Chase         S_SARG_RUN3
S_SARG_RUN3        SARG B    2 A_Chase         S_SARG_RUN4
S_SARG_RUN4        SARG B    2 A_Chase         S_SARG_RUN5
S_SARG_RUN5        SARG C    2 A_Chase         S_SARG_RUN6
S_SARG_RUN6        SARG C    2 A_Chase         S_SARG_RUN7
S_SARG_RUN7        SARG D    2 A_Chase         S_SARG_RUN8
S_SARG_RUN8        SARG D    2 A_Chase         S_SARG_RUN1
S_SARG_ATK1        SARG E    8 A_FaceTarget    S_SARG_ATK2
S_SARG_ATK2        SARG F    8 A_FaceTarget    S_SARG_ATK3
S_SARG_ATK3        SARG G    8 A_SargAttack    S_SARG_RUN1
S_SARG_PAIN        SARG H    2 -               S_SARG_PAIN2
S_SARG_PAIN2       SARG H    2 A_Pain          S_SARG_RUN1
S_SARG_DIE1        SARG I    8 -               S_SARG_DIE2
S_SARG_DIE2        SARG J    8 A_Scream        S_SARG_DIE3
S_SARG_DIE3        SARG K    4 -               S_SARG_DIE4
S_SARG_DIE4        SARG L    4 A_Fall          S_SARG_DIE5
S_SARG_DIE5        SARG M    4 -               S_SARG_DIE6
S_SARG_DIE6        SARG N   -1 -               S_NULL
S_HEAD_STND        HEAD A   10 A_Look          S_HEAD_STND
S_HEAD_RUN1        HEAD A    3 A_Chase         S_HEAD_RUN1
S_HEAD_ATK1        HEAD B    5 A_FaceTarget    S_HEAD_ATK2
S_HEAD_ATK2        HEAD C    5 A_FaceTarget    S_HEAD_ATK3
S_HEAD_ATK3        HEAD D*   5 A_HeadAttack    S_HEAD_RUN1
S_HEAD_PAIN        HEAD E    3 -               S_HEAD_PAIN2
S_HEAD_PAIN2       HEAD E    3 A_Pain          S_HEAD_PAIN3
S_HEAD_PAIN3       HEAD F    6 -               S_HEAD_RUN1
S_HEAD_DIE1        HEAD G    8 -               S_HEAD_DIE2
S_HEAD_DIE2        HEAD H    8 A_Scream        S_HEAD_DIE3
S_HEAD_DIE3        HEAD I    8 -               S_HEAD_DIE4
S_HEAD_DIE4        HEAD J    8 -               S_HEAD_DIE5
S_HEAD_DIE5        HEAD K    8 A_Fall          S_HEAD_DIE6
S_HEAD_DIE6        HEAD L   -1 -               S_NULL
S_BRBALL1          BAL7 A*   4 -               S_BRBALL2
S_BRBALL2          BAL7 B*   4 -               S_BRBALL1
S_BRBALLX1         BAL7 C*   6 -               S_BRBALLX2
S_BRBALLX2         BAL7 D*   6 -               S_BRBALLX3
S_BRBALLX3         BAL7 E*   6 -               S_NULL
S_BOSS_STND        BOSS A   10 A_Look          S_BOSS_STND2
S_BOSS_STND2       BOSS B   10 A_Look          S_BOSS_STND
S_BOSS_RUN1        BOSS A    3 A_Chase         S_BOSS_RUN2
S_BOSS_RUN2        BOSS A    3 A_Chase         S_BOSS_RUN3
S_BOSS_RUN3        BOSS B    3 A_Chase         S_BOSS_RUN4
S_BOSS_RUN4        BOSS B    3 A_Chase         S_BOSS_RUN5
S_BOSS_RUN5        BOSS C    3 A_Chase         S_BOSS_RUN6
S_BOSS_RUN6        BOSS C    3 A_Chase         S_BOSS_RUN7
S_BOSS_RUN7        BOSS D    3 A_Chase         S_BOSS_RUN8
S_BOSS_RUN8        BOSS D    3 A_Chase         S_BOSS_RUN1
S_BOSS_ATK1        BOSS E    8 A_FaceTarget    S_BOSS_ATK2
S_BOSS_ATK2        BOSS F    8 A_FaceTarget    S_BOSS_ATK3
S_BOSS_ATK3        BOSS G    8 A_BruisAttack   S_BOSS_RUN1
S_BOSS_PAIN        BOSS H    2 -               S_BOSS_PAIN2
S_BOSS_PAIN2       BOSS H    2 A_Pain          S_BOSS_RUN1
S_BOSS_DIE1        BOSS I    8 -               S_BOSS_DIE2
S_BOSS_DIE2        BOSS J    8 A_Scream        S_BOSS_DIE3
S_BOSS_DIE3        BOSS K    8 -               S_BOSS_DIE4
S_BOSS_DIE4        BOSS L    8 A_Fall          S_BOSS_DIE5
S_BOSS_DIE5        BOSS M    8 -               S_BOSS_DIE6
S_BOSS_DIE6        BOSS N    8 -               S_BOSS_DIE7
S_BOSS_DIE7        BOSS O   -1 A_BossDeath     S_NULL
S_SKULL_STND       SKUL A*  10 A_Look          S_SKULL_STND2
S_SKULL_STND2      SKUL B*  10 A_Look          S_SKULL_STND
S_SKULL_RUN1       SKUL A*   6 A_Chase         S_SKULL_RUN2
S_SKULL_RUN2       SKUL B*   6 A_Chase         S_SKULL_RUN1
S_SKULL_ATK1       SKUL C*  10 A_FaceTarget    S_SKULL_ATK2
S_SKULL_ATK2       SKUL D*   4 A_SkullAttack   S_SKULL_ATK3
S_SKULL_ATK3       SKUL C*   4 -               S_SKULL_ATK4
S_SKULL_ATK4       SKUL D*   4 -               S_SKULL_ATK3
S_SKULL_PAIN       SKUL E*   3 -               S_SKULL_PAIN2
S_SKULL_PAIN2      SKUL E*   3 A_Pain          S_SKULL_RUN1
S_SKULL_DIE1       SKUL F*   6 -               S_SKULL_DIE2
S_SKULL_DIE2       SKUL G*   6 A_Scream        S_SKULL_DIE3
S_SKULL_DIE3       SKUL H*   6 -               S_SKULL_DIE4
S_SKULL_DIE4       SKUL I*   6 A_Fall          S_SKULL_DIE5
S_SKULL_DIE5       SKUL J    6 -               S_SKULL_DIE6
S_SKULL_DIE6       SKUL K    6 -               S_NULL
S_ARM1             ARM1 A    6 -               S_ARM1A
S_ARM1A            ARM1 B*   7 -               S_ARM1
S_ARM2             ARM2 A    6 -               S_ARM2A
S_ARM2A            ARM2 B*   6 -               S_ARM2
S_BAR1             BAR1 A    6 -               S_BAR2
S_BAR2             BAR1 B    6 -               S_BAR1
S_BEXP             BEXP A*   5 -               S_BEXP2
S_BEXP2            BEXP B*   5 A_Scream        S_BEXP3
S_BEXP3            BEXP C*   5 -               S_BEXP4
S_BEXP4            BEXP D*  10 A_Explode       S_BEXP5
S_BEXP5            BEXP E*  10 -               S_NULL
S_BON1             BON1 A    6 -               S_BON1A
S_BON1A            BON1 B    6 -               S_BON1B
S_BON1B            BON1 C    6 -               S_BON1C
S_BON1C            BON1 D    6 -               S_BON1D
S_BON1D            BON1 C    6 -               S_BON1E
S_BON1E            BON1 B    6 -               S_BON1
S_BON2             BON2 A    6 -               S_BON2A
S_BON2A            BON2 B    6 -               S_BON2B
S_BON2B            BON2 C    6 -               S_BON2C
S_BON2C            BON2 D    6 -               S_BON2D
S_BON2D            BON2 C    6 -               S_BON2E
S_BON2E            BON2 B    6 -               S_BON2
S_BKEY             BKEY A   10 -               S_BKEY2
S_BKEY2            BKEY B*  10 -               S_BKEY
S_RKEY             RKEY A   10 -               S_RKEY2
S_RKEY2            RKEY B*  10 -               S_RKEY
S_YKEY             YKEY A   10 -               S_YKEY2
S_YKEY2            YKEY B*  10 -               S_YKEY
S_BSKULL           BSKU A   10 -               S_BSKULL2
S_BSKULL2          BSKU B*  10 -               S_BSKULL
S_RSKULL           RSKU A   10 -               S_RSKULL2
S_RSKULL2          RSKU B*  10 -               S_RSKULL
S_YSKULL           YSKU A   10 -               S_YSKULL2
S_YSKULL2          YSKU B*  10 -               S_YSKULL
S_STIM             STIM A   -1 -               S_NULL
S_MEDI             MEDI A   -1 -               S_NULL
S_SOUL             SOUL A*   6 -               S_SOUL2
S_SOUL2            SOUL B*   6 -               S_SOUL3
S_SOUL3            SOUL C*   6 -               S_SOUL4
S_SOUL4            SOUL D*   6 -               S_SOUL5
S_SOUL5            SOUL C*   6 -               S_SOUL6
S_SOUL6            SOUL B*   6 -               S_SOUL
S_PINV             PINV A*   6 -               S_PINV2
S_PINV2            PINV B*   6 -               S_PINV3
S_PINV3            PINV C*   6 -               S_PINV4
S_PINV4            PINV D*   6 -               S_PINV
S_PSTR             PSTR A*  -1 -               S_NULL
S_PINS             PINS A*   6 -               S_PINS2
S_PINS2            PINS B*   6 -               S_PINS3
S_PINS3            PINS C*   6 -               S_PINS4
S_PINS4            PINS D*   6 -               S_PINS
S_SUIT             SUIT A*  -1 -               S_NULL
S_PMAP             PMAP A*   6 -               S_PMAP2
S_PMAP2            PMAP B*   6 -               S_PMAP3
S_PMAP3            PMAP C*   6 -               S_PMAP4
S_PMAP4            PMAP D*   6 -               S_PMAP5
S_PMAP5            PMAP C*   6 -               S_PMAP6
S_PMAP6            PMAP B*   6 -               S_PMAP
S_PVIS             PVIS A*   6 -               S_PVIS2
S_PVIS2            PVIS B    6 -               S_PVIS
S_CLIP             CLIP A   -1 -               S_NULL
S_AMMO             AMMO A   -1 -               S_NULL
S_ROCK             ROCK A   -1 -               S_NULL
S_BROK             BROK A   -1 -               S_NULL
S_CELL             CELL A   -1 -               S_NULL
S_CELP             CELP A   -1 -               S_NULL
S_SHEL             SHEL A   -1 -               S_NULL
S_SBOX             SBOX A   -1 -               S_NULL
S_BPAK             BPAK A   -1 -               S_NULL
S_MGUN             MGUN A   -1 -               S_NULL
S_CSAW             CSAW A   -1 -               S_NULL
S_LAUN             LAUN A   -1 -               S_NULL
S_PLAS             PLAS A   -1 -               S_NULL
S_SHOT             SHOT A   -1 -               S_NULL
S_COLU             COLU A*  -1 -               S_NULL
S_BLOODYTWITCH     GOR1 A   10 -               S_BLOODYTWITCH2
S_BLOODYTWITCH2    GOR1 B   15 -               S_BLOODYTWITCH3
S_BLOODYTWITCH3    GOR1 C    8 -               S_BLOODYTWITCH4
S_BLOODYTWITCH4    GOR1 B    6 -               S_BLOODYTWITCH
S_GIBS             POL5 A   -1 -               S_NULL
S_LIVESTICK        POL6 A    6 -               S_LIVESTICK2
S_LIVESTICK2       POL6 B    8 -               S_LIVESTICK
S_MEAT2            GOR2 A   -1 -               S_NULL
S_MEAT4            GOR4 A   -1 -               S_NULL
S_MEAT5            GOR5 A   -1 -               S_NULL
S_STALAGTITE       SMIT A   -1 -               S_NULL
S_TALLGRNCOL       COL1 A   -1 -               S_NULL
S_SHRTGRNCOL       COL2 A   -1 -               S_NULL
S_TALLREDCOL       COL3 A   -1 -               S_NULL
S_CANDLESTIK       CAND A*  -1 -               S_NULL
S_CANDELABRA       CBRA A*  -1 -               S_NULL
S_TORCHTREE        TRE1 A   -1 -               S_NULL
S_BIGTREE          TRE2 A   -1 -               S_NULL
S_TECHPILLAR       ELEC A   -1 -               S_NULL
S_FLOATSKULL       FSKU A*   6 -               S_FLOATSKULL2
S_FLOATSKULL2      FSKU B*   6 -               S_FLOATSKULL3
S_FLOATSKULL3      FSKU C*   6 -               S_FLOATSKULL
S_HEARTCOL         COL5 A   14 -               S_HEARTCOL2
S_HEARTCOL2        COL5 B   14 -               S_HEARTCOL
S_BLUETORCH        TBLU A*   4 -               S_BLUETORCH2
S_BLUETORCH2       TBLU B*   4 -               S_BLUETORCH3
S_BLUETORCH3       TBLU C*   4 -               S_BLUETORCH4
S_BLUETORCH4       TBLU D*   4 -               S_BLUETORCH
S_GREENTORCH       TGRN A*   4 -               S_GREENTORCH2
S_GREENTORCH2      TGRN B*   4 -               S_GREENTORCH3
S_GREENTORCH3      TGRN C*   4 -               S_GREENTORCH4
S_GREENTORCH4      TGRN D*   4 -               S_GREENTORCH
S_REDTORCH         TRED A*   4 -               S_REDTORCH2
S_REDTORCH2        TRED B*   4 -               S_REDTORCH3
S_REDTORCH3        TRED C*   4 -               S_REDTORCH4
S_REDTORCH4        TRED D*   4 -               S_REDTORCH
S_BTORCHSHRT       SMBT A*   4 -               S_BTORCHSHRT2
S_BTORCHSHRT2      SMBT B*   4 -               S_BTORCHSHRT3
S_BTORCHSHRT3      SMBT C*   4 -               S_BTORCHSHRT4
S_BTORCHSHRT4      SMBT D*   4 -               S_BTORCHSHRT
S_GTORCHSHRT       SMGT A*   4 -               S_GTORCHSHRT2
S_GTORCHSHRT2      SMGT B*   4 -               S_GTORCHSHRT3
S_GTORCHSHRT3      SMGT C*   4 -               S_GTORCHSHRT4
S_GTORCHSHRT4      SMGT D*   4 -               S_GTORCHSHRT
S_RTORCHSHRT       SMRT A*   4 -               S_RTORCHSHRT2
S_RTORCHSHRT2      SMRT B*   4 -               S_RTORCHSHRT3
S_RTORCHSHRT3      SMRT C*   4 -               S_RTORCHSHRT4
S_RTORCHSHRT4      SMRT D*   4 -               S_RTORCHSHRT
"""
MOBJS = """
MT_PLAYER      spawnstate=S_PLAY spawnhealth=100 seestate=S_PLAY_RUN1 reactiontime=0 painstate=S_PLAY_PAIN painchance=255 painsound=plpain missilestate=S_PLAY_ATK1 deathstate=S_PLAY_DIE1 xdeathstate=S_PLAY_XDIE1 deathsound=pldeth radius=16 height=56 flags=SOLID|SHOOTABLE|DROPOFF|PICKUP|NOTDMATCH
MT_POSSESSED   doomednum=3004 spawnstate=S_POSS_STND spawnhealth=20 seestate=S_POSS_RUN1 seesound=posit1 attacksound=pistol painstate=S_POSS_PAIN painchance=200 painsound=popain missilestate=S_POSS_ATK1 deathstate=S_POSS_DIE1 xdeathstate=S_POSS_XDIE1 deathsound=podth1 speed=8 height=56 activesound=posact flags=SOLID|SHOOTABLE|COUNTKILL
MT_SHOTGUY     doomednum=9 spawnstate=S_SPOS_STND spawnhealth=30 seestate=S_SPOS_RUN1 seesound=posit2 painstate=S_SPOS_PAIN painchance=170 painsound=popain missilestate=S_SPOS_ATK1 deathstate=S_SPOS_DIE1 xdeathstate=S_SPOS_XDIE1 deathsound=podth2 speed=8 height=56 activesound=posact flags=SOLID|SHOOTABLE|COUNTKILL
MT_TROOP       doomednum=3001 spawnstate=S_TROO_STND spawnhealth=60 seestate=S_TROO_RUN1 seesound=bgsit1 painstate=S_TROO_PAIN painchance=200 painsound=popain meleestate=S_TROO_ATK1 missilestate=S_TROO_ATK1 deathstate=S_TROO_DIE1 xdeathstate=S_TROO_XDIE1 deathsound=bgdth1 speed=8 height=56 activesound=bgact flags=SOLID|SHOOTABLE|COUNTKILL
MT_SERGEANT    doomednum=3002 spawnstate=S_SARG_STND spawnhealth=150 seestate=S_SARG_RUN1 seesound=sgtsit attacksound=sgtatk painstate=S_SARG_PAIN painchance=180 painsound=dmpain meleestate=S_SARG_ATK1 deathstate=S_SARG_DIE1 deathsound=sgtdth speed=10 radius=30 height=56 mass=400 activesound=dmact flags=SOLID|SHOOTABLE|COUNTKILL
MT_SHADOWS     doomednum=58 spawnstate=S_SARG_STND spawnhealth=150 seestate=S_SARG_RUN1 seesound=sgtsit attacksound=sgtatk painstate=S_SARG_PAIN painchance=180 painsound=dmpain meleestate=S_SARG_ATK1 deathstate=S_SARG_DIE1 deathsound=sgtdth speed=10 radius=30 height=56 mass=400 activesound=dmact flags=SOLID|SHOOTABLE|SHADOW|COUNTKILL
MT_HEAD        doomednum=3005 spawnstate=S_HEAD_STND spawnhealth=400 seestate=S_HEAD_RUN1 seesound=cacsit painstate=S_HEAD_PAIN painchance=128 painsound=dmpain missilestate=S_HEAD_ATK1 deathstate=S_HEAD_DIE1 deathsound=cacdth speed=8 radius=31 height=56 mass=400 activesound=dmact flags=SOLID|SHOOTABLE|FLOAT|NOGRAVITY|COUNTKILL
MT_BRUISER     doomednum=3003 spawnstate=S_BOSS_STND seestate=S_BOSS_RUN1 seesound=brssit painstate=S_BOSS_PAIN painchance=50 painsound=dmpain meleestate=S_BOSS_ATK1 missilestate=S_BOSS_ATK1 deathstate=S_BOSS_DIE1 deathsound=brsdth speed=8 radius=24 height=64 mass=1000 activesound=dmact flags=SOLID|SHOOTABLE|COUNTKILL
MT_BRUISERSHOT spawnstate=S_BRBALL1 seesound=firsht deathstate=S_BRBALLX1 deathsound=firxpl speed=15 radius=6 height=8 damage=8 flags=NOBLOCKMAP|MISSILE|DROPOFF|NOGRAVITY
MT_SKULL       doomednum=3006 spawnstate=S_SKULL_STND spawnhealth=100 seestate=S_SKULL_RUN1 attacksound=sklatk painstate=S_SKULL_PAIN painchance=256 painsound=dmpain missilestate=S_SKULL_ATK1 deathstate=S_SKULL_DIE1 deathsound=firxpl speed=8 radius=16 height=56 mass=50 damage=3 activesound=dmact flags=SOLID|SHOOTABLE|FLOAT|NOGRAVITY
MT_BARREL      doomednum=2035 spawnstate=S_BAR1 spawnhealth=20 deathstate=S_BEXP deathsound=barexp radius=10 height=42 flags=SOLID|SHOOTABLE|NOBLOOD
MT_TROOPSHOT   spawnstate=S_TBALL1 seesound=firsht deathstate=S_TBALLX1 deathsound=firxpl speed=10 radius=6 height=8 damage=3 flags=NOBLOCKMAP|MISSILE|DROPOFF|NOGRAVITY
MT_HEADSHOT    spawnstate=S_RBALL1 seesound=firsht deathstate=S_RBALLX1 deathsound=firxpl speed=10 radius=6 height=8 damage=5 flags=NOBLOCKMAP|MISSILE|DROPOFF|NOGRAVITY
MT_ROCKET      spawnstate=S_ROCKET seesound=rlaunc deathstate=S_EXPLODE1 deathsound=barexp speed=20 radius=11 height=8 damage=20 flags=NOBLOCKMAP|MISSILE|DROPOFF|NOGRAVITY
MT_PLASMA      spawnstate=S_PLASBALL seesound=plasma deathstate=S_PLASEXP deathsound=firxpl speed=25 radius=13 height=8 damage=5 flags=NOBLOCKMAP|MISSILE|DROPOFF|NOGRAVITY
MT_PUFF        spawnstate=S_PUFF1 flags=NOBLOCKMAP|NOGRAVITY
MT_BLOOD       spawnstate=S_BLOOD1 flags=NOBLOCKMAP
MT_TFOG        spawnstate=S_TFOG flags=NOBLOCKMAP|NOGRAVITY
MT_IFOG        spawnstate=S_IFOG flags=NOBLOCKMAP|NOGRAVITY
MT_TELEPORTMAN doomednum=14 flags=NOBLOCKMAP|NOSECTOR
MT_MISC0       doomednum=2018 spawnstate=S_ARM1 flags=SPECIAL
MT_MISC1       doomednum=2019 spawnstate=S_ARM2 flags=SPECIAL
MT_MISC2       doomednum=2014 spawnstate=S_BON1 flags=SPECIAL|COUNTITEM
MT_MISC3       doomednum=2015 spawnstate=S_BON2 flags=SPECIAL|COUNTITEM
MT_MISC4       doomednum=5 spawnstate=S_BKEY flags=SPECIAL|NOTDMATCH
MT_MISC5       doomednum=13 spawnstate=S_RKEY flags=SPECIAL|NOTDMATCH
MT_MISC6       doomednum=6 spawnstate=S_YKEY flags=SPECIAL|NOTDMATCH
MT_MISC7       doomednum=39 spawnstate=S_YSKULL flags=SPECIAL|NOTDMATCH
MT_MISC8       doomednum=38 spawnstate=S_RSKULL flags=SPECIAL|NOTDMATCH
MT_MISC9       doomednum=40 spawnstate=S_BSKULL flags=SPECIAL|NOTDMATCH
MT_MISC10      doomednum=2011 spawnstate=S_STIM flags=SPECIAL
MT_MISC11      doomednum=2012 spawnstate=S_MEDI flags=SPECIAL
MT_MISC12      doomednum=2013 spawnstate=S_SOUL flags=SPECIAL|COUNTITEM
MT_INV         doomednum=2022 spawnstate=S_PINV flags=SPECIAL|COUNTITEM
MT_MISC13      doomednum=2023 spawnstate=S_PSTR flags=SPECIAL|COUNTITEM
MT_INS         doomednum=2024 spawnstate=S_PINS flags=SPECIAL|COUNTITEM
MT_MISC14      doomednum=2025 spawnstate=S_SUIT flags=SPECIAL
MT_MISC15      doomednum=2026 spawnstate=S_PMAP flags=SPECIAL|COUNTITEM
MT_MISC16      doomednum=2045 spawnstate=S_PVIS flags=SPECIAL|COUNTITEM
MT_CLIP        doomednum=2007 spawnstate=S_CLIP flags=SPECIAL
MT_MISC17      doomednum=2048 spawnstate=S_AMMO flags=SPECIAL
MT_MISC18      doomednum=2010 spawnstate=S_ROCK flags=SPECIAL
MT_MISC19      doomednum=2046 spawnstate=S_BROK flags=SPECIAL
MT_MISC20      doomednum=2047 spawnstate=S_CELL flags=SPECIAL
MT_MISC21      doomednum=17 spawnstate=S_CELP flags=SPECIAL
MT_MISC22      doomednum=2008 spawnstate=S_SHEL flags=SPECIAL
MT_MISC23      doomednum=2049 spawnstate=S_SBOX flags=SPECIAL
MT_MISC24      doomednum=8 spawnstate=S_BPAK flags=SPECIAL
MT_CHAINGUN    doomednum=2002 spawnstate=S_MGUN flags=SPECIAL
MT_MISC26      doomednum=2005 spawnstate=S_CSAW flags=SPECIAL
MT_MISC27      doomednum=2003 spawnstate=S_LAUN flags=SPECIAL
MT_MISC28      doomednum=2004 spawnstate=S_PLAS flags=SPECIAL
MT_SHOTGUN     doomednum=2001 spawnstate=S_SHOT flags=SPECIAL
MT_MISC31      doomednum=2028 spawnstate=S_COLU radius=16 flags=SOLID
MT_MISC32      doomednum=30 spawnstate=S_TALLGRNCOL radius=16 flags=SOLID
MT_MISC33      doomednum=31 spawnstate=S_SHRTGRNCOL radius=16 flags=SOLID
MT_MISC34      doomednum=32 spawnstate=S_TALLREDCOL radius=16 flags=SOLID
MT_MISC37      doomednum=36 spawnstate=S_HEARTCOL radius=16 flags=SOLID
MT_MISC39      doomednum=42 spawnstate=S_FLOATSKULL radius=16 flags=SOLID
MT_MISC40      doomednum=43 spawnstate=S_TORCHTREE radius=16 flags=SOLID
MT_MISC41      doomednum=44 spawnstate=S_BLUETORCH radius=16 flags=SOLID
MT_MISC42      doomednum=45 spawnstate=S_GREENTORCH radius=16 flags=SOLID
MT_MISC43      doomednum=46 spawnstate=S_REDTORCH radius=16 flags=SOLID
MT_MISC44      doomednum=55 spawnstate=S_BTORCHSHRT radius=16 flags=SOLID
MT_MISC45      doomednum=56 spawnstate=S_GTORCHSHRT radius=16 flags=SOLID
MT_MISC46      doomednum=57 spawnstate=S_RTORCHSHRT radius=16 flags=SOLID
MT_MISC47      doomednum=47 spawnstate=S_STALAGTITE radius=16 flags=SOLID
MT_MISC48      doomednum=48 spawnstate=S_TECHPILLAR radius=16 flags=SOLID
MT_MISC49      doomednum=34 spawnstate=S_CANDLESTIK
MT_MISC50      doomednum=35 spawnstate=S_CANDELABRA radius=16 flags=SOLID
MT_MISC51      doomednum=49 spawnstate=S_BLOODYTWITCH radius=16 height=68 flags=SOLID|SPAWNCEILING|NOGRAVITY
MT_MISC52      doomednum=50 spawnstate=S_MEAT2 radius=16 height=84 flags=SOLID|SPAWNCEILING|NOGRAVITY
MT_MISC54      doomednum=52 spawnstate=S_MEAT4 radius=16 height=68 flags=SOLID|SPAWNCEILING|NOGRAVITY
MT_MISC55      doomednum=53 spawnstate=S_MEAT5 radius=16 height=52 flags=SOLID|SPAWNCEILING|NOGRAVITY
MT_MISC56      doomednum=59 spawnstate=S_MEAT2 height=84 flags=SPAWNCEILING|NOGRAVITY
MT_MISC57      doomednum=60 spawnstate=S_MEAT4 height=68 flags=SPAWNCEILING|NOGRAVITY
MT_MISC59      doomednum=62 spawnstate=S_MEAT5 height=52 flags=SPAWNCEILING|NOGRAVITY
MT_MISC60      doomednum=63 spawnstate=S_BLOODYTWITCH height=68 flags=SPAWNCEILING|NOGRAVITY
MT_MISC61      doomednum=22 spawnstate=S_HEAD_DIE6
MT_MISC62      doomednum=15 spawnstate=S_PLAY_DIE7
MT_MISC63      doomednum=18 spawnstate=S_POSS_DIE5
MT_MISC64      doomednum=21 spawnstate=S_SARG_DIE6
MT_MISC65      doomednum=23 spawnstate=S_SKULL_DIE6
MT_MISC66      doomednum=20 spawnstate=S_TROO_DIE5
MT_MISC67      doomednum=19 spawnstate=S_SPOS_DIE5
MT_MISC68      doomednum=10 spawnstate=S_PLAY_XDIE9
MT_MISC69      doomednum=12 spawnstate=S_PLAY_XDIE9
MT_MISC71      doomednum=24 spawnstate=S_GIBS
MT_MISC75      doomednum=26 spawnstate=S_LIVESTICK radius=16 flags=SOLID
MT_MISC76      doomednum=54 spawnstate=S_BIGTREE radius=32 flags=SOLID
"""

# vanilla's rndtable (m_random.c)
RNDTABLE = [
    0, 8, 109, 220, 222, 241, 149, 107, 75, 248, 254, 140, 16, 66, 74, 21, 211, 47, 80,
    242, 154, 27, 205, 128, 161, 89, 77, 36, 95, 110, 85, 48, 212, 140, 211, 249, 22, 79,
    200, 50, 28, 188, 52, 140, 202, 120, 68, 145, 62, 70, 184, 190, 91, 197, 152, 224, 149,
    104, 25, 178, 252, 182, 202, 182, 141, 197, 4, 81, 181, 242, 145, 42, 39, 227, 156, 198,
    225, 193, 219, 93, 122, 175, 249, 0, 175, 143, 70, 239, 46, 246, 163, 53, 163, 109, 168,
    135, 2, 235, 25, 92, 20, 145, 138, 77, 69, 166, 78, 176, 173, 212, 166, 113, 94, 161, 41,
    50, 239, 49, 111, 164, 70, 60, 2, 37, 171, 75, 136, 156, 11, 56, 42, 146, 138, 229, 73,
    146, 77, 61, 98, 196, 135, 106, 63, 197, 195, 86, 96, 203, 113, 101, 170, 247, 181, 113,
    80, 250, 108, 7, 255, 237, 129, 226, 79, 107, 112, 166, 103, 241, 24, 223, 239, 120, 198,
    58, 60, 82, 128, 3, 184, 66, 143, 224, 145, 224, 81, 206, 163, 45, 63, 90, 168, 114, 59,
    33, 159, 95, 28, 139, 123, 98, 125, 196, 15, 70, 194, 253, 54, 14, 109, 226, 71, 17, 161,
    93, 186, 87, 244, 138, 20, 52, 123, 251, 26, 36, 17, 46, 52, 231, 232, 76, 31, 221, 84,
    37, 216, 165, 212, 106, 197, 242, 98, 43, 39, 175, 254, 145, 190, 84, 118, 222, 187, 136,
    120, 163, 236, 249]
assert len(RNDTABLE) == 256


def finesine_quarter():
    """vanilla finesine[0..2047]: 65536 sin((i + 0.5) 2pi / 8192) truncated,
    except two entries where vanilla's table (computed with other floats)
    is one higher."""
    q = [int(65536 * math.sin((i + 0.5) * 2 * math.pi / 8192)) for i in range(2048)]
    q[455] += 1
    q[1080] += 1
    return q


def tantoangle16():
    """vanilla tantoangle[i] >> 16 (BAM16): the angle whose tangent is i/2048."""
    return [int(math.atan(i / 2048) / (2 * math.pi) * 4294967296) >> 16 for i in range(2049)]


# --- parsing -------------------------------------------------------------------------

class State:
    def __init__(self, name, sprite, frame, bright, tics, action, nxt):
        self.name, self.sprite, self.frame, self.bright = name, sprite, frame, bright
        self.tics, self.action, self.next = tics, action, nxt


def parse_states(text=STATES):
    out = []
    for line in text.strip().splitlines():
        name, sprite, frame, tics, action, nxt = line.split()
        bright = frame.endswith("*")
        out.append(State(name, sprite, ord(frame[0]) - ord("A"), bright, int(tics),
                         None if action == "-" else action, nxt))
    return out


def parse_mobjs(text=MOBJS):
    out = []
    for line in text.strip().splitlines():
        name, *pairs = line.split()
        fields = dict(DEFAULTS)
        for pair in pairs:
            key, _, value = pair.partition("=")
            if key not in DEFAULTS:
                raise ValueError(f"{name}: unknown field {key}")
            fields[key] = value
        out.append((name, fields))
    return out


def flag_value(text):
    if text == "0":
        return 0
    return sum(FLAGS[f] for f in text.split("|"))


def sprite_numbers(doomdata_h: Path):
    return {m.group(1): int(m.group(2)) for m in
            re.finditer(r"#define SPR_(\w+)\s+(\d+)", doomdata_h.read_text())}


# --- output ----------------------------------------------------------------------------

HEADER = "/* Generated by tools/gen_info.py -- do not edit. */\n"


def c_array(ctype, name, values, per_line=12):
    lines = [f"const {ctype} {name}[{len(values)}] = {{"]
    for i in range(0, len(values), per_line):
        lines.append("    " + ", ".join(str(v) for v in values[i:i + per_line]) + ",")
    lines.append("};")
    return "\n".join(lines)


def generate(sprites: dict[str, int] | None = None):
    states = parse_states()
    mobjs = parse_mobjs()
    index = {s.name: i for i, s in enumerate(states)}
    if len(index) != len(states):
        raise ValueError("duplicate state name")
    actions = ["AC_NONE"] + ["AC_" + a[2:] for a in MOBJ_ACTIONS + WEAPON_ACTIONS]
    act_index = {a: i + 1 for i, a in enumerate(MOBJ_ACTIONS + WEAPON_ACTIONS)}
    for s in states:
        if s.next not in index:
            raise ValueError(f"{s.name}: next state {s.next} not kept")
        if s.action and s.action not in act_index:
            raise ValueError(f"{s.name}: unknown action {s.action}")
        if not -1 <= s.tics <= 254:
            raise ValueError(f"{s.name}: tics {s.tics}")
    for name, f in mobjs:
        for k in STATE_FIELDS:
            if f[k] not in index:
                raise ValueError(f"{name}: {k} {f[k]} not kept")
        for k in SOUND_FIELDS:
            if f[k] not in SFX:
                raise ValueError(f"{name}: unknown sound {f[k]}")

    # --- info.h
    h = [HEADER, "/* Doom's states and thing types for episode 1 (tools/gen_info.py,",
         " * DESIGN.md section 9). Vanilla names and order; see info.c. */",
         "#ifndef INFO_H", "#define INFO_H", "", "#include <stdint.h>", ""]
    h.append(f"#define NUMSTATES {len(states)}")
    h.append("enum {")
    h += [f"    {s.name}," for s in states]
    h.append("};")
    h.append("")
    h.append(f"#define NUMMOBJTYPES {len(mobjs)}")
    h.append("enum {")
    h += [f"    {name}," for name, _ in mobjs]
    h.append("};")
    h.append("")
    h.append(f"#define NUMSFX {len(SFX)}")
    h.append("enum {")
    h += [f"    sfx_{s}," for s in SFX]
    h.append("};")
    h.append("")
    h.append(f"#define NUMACTIONS {len(actions)}")
    h.append(f"#define AC_FIRST_WEAPON {1 + len(MOBJ_ACTIONS)}  /* AC_ numbers from here are weapon actions */")
    h.append("enum {")
    h += [f"    {a}," for a in actions]
    h.append("};")
    h.append("")
    h.append("/* mobj flags (vanilla's MF_ values); MF_x_B is the byte of the flag")
    h.append(" * word that holds it and MF_x_M its mask in that byte, for FLAG() */")
    for k, v in FLAGS.items():
        byte = (v.bit_length() - 1) // 8
        h.append(f"#define MF_{k:14s} 0x{v:08X}UL")
        h.append(f"#define MF_{k}_B {byte}")
        h.append(f"#define MF_{k}_M 0x{v >> (8 * byte):02X}")
    h.append("")
    h.append("""/* One thing type, 32 bytes (vanilla's mobjinfo_t without doomednum and
 * raisestate). radius, height and speed are map units; a missile's speed
 * is (fixed_t)speed << FRACBITS. painchance is 16 bits: the lost soul's
 * 256 means always. */
typedef struct {
    uint16_t spawnstate, seestate, painstate, meleestate;
    uint16_t missilestate, deathstate, xdeathstate;
    int16_t  spawnhealth;
    uint16_t painchance;
    uint16_t mass;
    uint32_t flags;
    uint8_t  seesound, attacksound, painsound, deathsound, activesound;
    uint8_t  reactiontime, speed, radius, height, damage;
} mobjinfo_t;

extern const mobjinfo_t mobjinfo[NUMMOBJTYPES];
extern const int16_t mi_doomednum[NUMMOBJTYPES];   /* -1: not placed in maps */

/* the states, one byte plane per field */
extern const uint8_t  st_sprite[NUMSTATES];   /* SPR_ number (doomdata.h) */
extern const uint8_t  st_frame[NUMSTATES];    /* frame letter index, bit 7 full bright */
extern const uint8_t  st_tics[NUMSTATES];     /* 255 = forever (vanilla -1) */
extern const uint8_t  st_action[NUMSTATES];   /* AC_*, bit 7: quiet from here on */
extern const uint16_t st_next[NUMSTATES];
#define ST_FOREVER 255

/* vanilla's rndtable (m_random.c) */
extern const uint8_t rndtable[256];

/* the action tables (info.c): AC_ numbers below AC_FIRST_WEAPON call
 * mobj_actions[n](mobj), the others weapon_actions[n - AC_FIRST_WEAPON]
 * (player, psp) */
struct mobj_s;
struct player_s;
struct pspdef_s;
typedef void (*mobjaction_t)(struct mobj_s *);
typedef void (*weaponaction_t)(struct player_s *, struct pspdef_s *);
extern const mobjaction_t mobj_actions[AC_FIRST_WEAPON];
extern const weaponaction_t weapon_actions[NUMACTIONS - AC_FIRST_WEAPON];
""")
    for a in MOBJ_ACTIONS:
        h.append(f"void {a}(struct mobj_s *actor);")
    for a in WEAPON_ACTIONS:
        h.append(f"void {a}(struct player_s *player, struct pspdef_s *psp);")
    h += ["", "#endif", ""]

    # --- info.c
    def spr(name):
        return f"SPR_{name}"

    c = [HEADER, "/* Doom's states and thing types for episode 1, from the compact source",
         " * in tools/gen_info.py (vanilla names, order and values). */",
         '#include "doomdata.h"', '#include "info.h"', "", "#ifdef DD_MAPDIR", ""]
    c.append(c_array("uint8_t", "st_sprite", [spr(s.sprite) for s in states], 8))
    c.append(c_array("uint8_t", "st_frame",
                     [s.frame | (0x80 if s.bright else 0) for s in states], 16))
    c.append(c_array("uint8_t", "st_tics", [255 if s.tics < 0 else s.tics for s in states], 16))
    acts = [act_index.get(s.action, 0) for s in states]

    def quiet(i):
        seen = set()
        while i not in seen:
            if acts[i]:
                return False
            seen.add(i)
            i = index[states[i].next]
        return True
    c.append(c_array("uint8_t", "st_action",
                     ["0x%02X" % (a | (0x80 if quiet(i) else 0)) for i, a in enumerate(acts)], 12))
    c.append(c_array("uint16_t", "st_next", [index[s.next] for s in states], 12))
    c.append("")
    c.append("const mobjinfo_t mobjinfo[NUMMOBJTYPES] = {")
    for name, f in mobjs:
        speed = int(f["speed"])
        vals = [f[k] for k in ("spawnstate", "seestate", "painstate", "meleestate",
                               "missilestate", "deathstate", "xdeathstate")]
        vals += [f["spawnhealth"], f["painchance"], f["mass"], "0x%08lXUL" % flag_value(f["flags"])]
        vals += ["sfx_" + f[k] for k in ("seesound", "attacksound", "painsound", "deathsound",
                                         "activesound")]
        vals += [f["reactiontime"], str(speed), f["radius"], f["height"], f["damage"]]
        c.append(f"    {{ {', '.join(vals)} }},  /* {name} */")
    c.append("};")
    c.append("")
    c.append(c_array("int16_t", "mi_doomednum", [int(f["doomednum"]) for _, f in mobjs], 12))
    c.append("")
    c.append(c_array("uint8_t", "rndtable", RNDTABLE, 16))
    c.append("")
    c.append("const mobjaction_t mobj_actions[AC_FIRST_WEAPON] = {\n    0,")
    c += [f"    {a}," for a in MOBJ_ACTIONS]
    c.append("};")
    c.append("const weaponaction_t weapon_actions[NUMACTIONS - AC_FIRST_WEAPON] = {")
    c += [f"    {a}," for a in WEAPON_ACTIONS]
    c.append("};")
    c += ["", "#endif", ""]

    # --- gtables.s
    q = finesine_quarter()
    t = tantoangle16()
    s = [HEADER.replace("/*", ";").replace(" */", ""),
         "; The game's far tables (DESIGN.md section 9): assembled into GAME.BIN in",
         "; segment GFAR, copied at boot into the game's own RamWorks bank by",
         "; game_farinit (fixed.s); after that the bytes in bank 1 are free memory.",
         "; Offsets from the start of the segment (GT_* in fixed.s):",
         ";   +0      finesine[0..2047], u16 (vanilla finesine, first quarter)",
         ";   +4096   tantoangle[0..2048], u16 (vanilla tantoangle >> 16)",
         ";   (only with the converted data: the stand-in data set builds the",
         ";   platform's GAME skeleton, src/game/game.c)",
         "", '.include "doomdata.inc"', ".ifdef DD_MAPDIR", "",
         ".export gtables_start, gtables_end", "", '.segment "GFAR"', "gtables_start:"]
    for i in range(0, 2048, 16):
        s.append("        .word   " + ",".join(str(v) for v in q[i:i + 16]))
    for i in range(0, 2049, 16):
        s.append("        .word   " + ",".join(str(v) for v in t[i:i + 16]))
    s.append("gtables_end:")
    s += ["", ".endif ; DD_MAPDIR", ""]

    # --- the same tables for the host build (tests/host/host.c)
    g = [HEADER, "/* The far tables of src/game/gtables.s for the host build. */",
         c_array("uint16_t", "host_finesine_q", q, 16), c_array("uint16_t", "host_tantoangle", t, 16), ""]
    return "\n".join(h), "\n".join(c), "\n".join(s), "\n".join(g)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="compare with the checked-in files")
    args = ap.parse_args(argv)
    outs = dict(zip((OUT_H, OUT_C, OUT_S, OUT_HOST), generate()))
    if args.check:
        stale = [str(p) for p, text in outs.items() if not p.is_file() or p.read_text() != text]
        if stale:
            print("stale: " + ", ".join(stale))
            return 1
        return 0
    for path, text in outs.items():
        path.write_text(text)
        print(f"wrote {path.relative_to(PROJECT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
