"""Appletini F1.2.4 and physical SSI-263 register and pitch contracts.

The Appletini profile uses the firmware's 20 kHz glottal counter. Its rounded
period differs from the original chip's XCK pitch equation; each profile uses
its own control law so vocals and AY accompaniment stay in tune.
"""

from __future__ import annotations

from bisect import bisect_left
import hashlib
import math
from pathlib import Path
import re
import subprocess


TARGET_FIRMWARE = "F1.2.4"
SLOT = 4
NATIVE_MODE_ADDRESS = 0xC0CD
VIA_BASES = (0xC410, 0xC480)
SSI_BASES = (0xC420, 0xC440)  # secondary/left, primary/right
SSI_BROADCAST_BASE = 0xC460
AY_SELECT_BASES = (0x0C, 0x14)  # primary/secondary: reset high, BDIR/BC low
# Average bus clocks shared with music/doom/src/aytime.s and tables.inc.
# The firmware top-level Q3 comment (~2.046 MHz) is a rounded nominal value.
NTSC_CPU_HZ = 1_020_484
PAL_CPU_HZ = 1_015_625
AY_NATIVE_CLOCK_HZ = 2 * NTSC_CPU_HZ
SSI_RAW_XCK_HZ = 2 * NTSC_CPU_HZ  # Q3; duration core divides by two
SSI_FILTER_NEUTRAL = 128
SSI_CONTROL_HZ = 20_000
SSI_MIN_HZ = SSI_CONTROL_HZ / 640
SSI_MAX_HZ = float(SSI_CONTROL_HZ)

# SSI-263 labels (not SC-01 phone numbers). Extended entries can also be
# supplied as integer codes in a score.
SSI_PHONEMES = {
    label: code
    for code, label in enumerate(
        "PA E E1 Y YI AY IE I A AI EH EH1 AE AE1 AH AH1 "
        "AW O OU OO IU IU1 U U1 UH UH1 UH2 UH3 ER R R1 R2 "
        "L L1 LF W B D KV P T K HV HVC HF HFC HN Z "
        "S J SCH V F THV TH M N NG".split()
    )
}

FIRMWARE_SOURCE_FILES = (
    "ps_sources/image_versions.h",
    "hdl/apple/mockingboard.sv",
    "hdl/apple/YM2149.sv",
    "hdl/apple/ssi263_bus_wrapper.sv",
    "hdl/apple/ssi263_voice.sv",
    "hdl/apple/ssi263_xck_ce.sv",
    "hdl/apple/sc01a_digital_core.sv",
    "hdl/apple/ssi263_formant_backend.sv",
    "hdl/apple/ssi263_formant_pkg.sv",
    "hdl/apple/ssi263_sc02_rom.mem",
)

# Verified F1.2.4 contract from codex/turbo-paging-dma. Source changes require
# a new review of pitch, live-control and rendering behavior.
TARGET_SOURCE_SHA256: dict[str, str] = {
    'ps_sources/image_versions.h': '29aa22d9b05bb690f61bb1e0b7fb6af22c1f9127db0de493ed49cfdaff53d3db',
    'hdl/apple/mockingboard.sv': '9073f8e72c5f8d8ce7c1342c5796cf439f3d99d0485762c6ad513f80f1060f65',
    'hdl/apple/YM2149.sv': '79267211c20dfc0f4715b57db19cd5221d654870eede621db53c383e6e7999cf',
    'hdl/apple/ssi263_bus_wrapper.sv': '87e264f5873d195af22c04863ea65a384f721eb71ff8e11c9a73b1b85b82b82e',
    'hdl/apple/ssi263_voice.sv': 'd1c6488a263b2b27efd483add301f36dcb1f9cdcd23d38f870f80333280f01b3',
    'hdl/apple/ssi263_xck_ce.sv': 'eb4f0cef7f718433322795c36b99a70cd4cb2c0a01cfe772d927060306bb2199',
    'hdl/apple/sc01a_digital_core.sv': 'b9f7fcbc4aeb8c200649923b41753c81859717bf86ba1bd623fbc004baaad63f',
    'hdl/apple/ssi263_formant_backend.sv': '520505cfcff3c4820fe0deaf30c9ff335b8ace42659e9b421fc5aba5a5265716',
    'hdl/apple/ssi263_formant_pkg.sv': '44c8f3f3588462d589717047349282801766b8e5da2dcedcd10cf0c1829f8e25',
    'hdl/apple/ssi263_sc02_rom.mem': 'e853e4b19425ab6b719b71a97f952bf900dc15eca5c2dc184663db752665c8a0',
}
TARGET_SOURCE_COMMIT = "96fd466076abfbac52d62d47446f67946913e58f"


def _positive_finite(value: float, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite and positive")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite and positive") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be finite and positive")
    return value


def _integer_in(value: int, low: int, high: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer in {low}..{high}")
    return value


def _pitch_table() -> tuple[tuple[float, ...], tuple[int, ...]]:
    # Retain the lowest register word for each physical period. Many of the
    # 4096 words produce the same pitch after the firmware's integer division.
    periods: dict[int, int] = {}
    for inflection in range(4096):
        period = max(1, ((4096 - inflection) * 5) // 32)
        periods.setdefault(period, inflection)
    rows = sorted((SSI_CONTROL_HZ / period, inflection)
                  for period, inflection in periods.items())
    return tuple(row[0] for row in rows), tuple(row[1] for row in rows)


_SSI_FREQUENCIES, _SSI_INFLECTIONS = _pitch_table()


def ssi_pitch(hz: float) -> tuple[int, float]:
    """Return (12-bit inflection, achieved Hz), nearest in musical cents.

    Requests outside the firmware's range clamp to its endpoints. The actual
    frequency lets the caller report both clipping and quantization error.
    This range describes the counter, not intelligible singing: the source
    pulse truncates above about 278 Hz and very high notes lose useful timbre.
    """
    hz = _positive_finite(hz, "pitch")
    position = bisect_left(_SSI_FREQUENCIES, hz)
    candidates = {max(0, position - 1), min(position, len(_SSI_FREQUENCIES) - 1)}
    # Subtract logs rather than divide frequencies: a positive subnormal
    # request must clamp cleanly without overflowing the ratio.
    log_hz = math.log2(hz)
    best = min(candidates, key=lambda index: (
        abs(math.log2(_SSI_FREQUENCIES[index]) - log_hz), index))
    return _SSI_INFLECTIONS[best], _SSI_FREQUENCIES[best]


def physical_ssi_pitch(hz: float, effective_clock_hz: float) -> tuple[int, float]:
    """Nearest physical-chip inflection in cents, using the datasheet equation.

    XCK is the effective clock after any external/divide-by-two selection.
    f0 = XCK / (8 * (4096 - I)); no Appletini excitation model is assumed.
    """
    hz = _positive_finite(hz, "pitch")
    clock = _positive_finite(effective_clock_hz, "effective SSI clock")
    if hz <= clock / (8 * 4096):
        return 0, clock / (8 * 4096)
    if hz >= clock / 8:
        return 4095, clock / 8
    ideal = clock / (8 * hz)
    candidates = {max(1, min(4096, math.floor(ideal))),
                  max(1, min(4096, math.ceil(ideal)))}
    period = min(candidates, key=lambda value: (
        abs(math.log2(clock / (8 * value)) - math.log2(hz)), -value))
    return 4096 - period, clock / (8 * period)


def physical_ssi_filter(authored_filter: int, effective_clock_hz: float) -> tuple[int, float]:
    """Map the score's normalized tract setting to a physical filter clock.

    Authored f requests 20,000 * (128 + f) / 256 Hz. Choose the nearest
    achievable XCK / (2 * (256 - FF)) in Hz. This preserves the intended
    relative brightness; it is not a calibrated match of the two spectra.
    """
    authored_filter = _integer_in(authored_filter, 0, 255, "authored filter")
    clock = _positive_finite(effective_clock_hz, "effective SSI clock")
    desired = SSI_CONTROL_HZ * (128 + authored_filter) / 256
    if desired <= clock / (2 * 256):
        return 0, clock / (2 * 256)
    if desired >= clock / 2:
        return 255, clock / 2
    ideal = clock / (2 * desired)
    candidates = {max(1, min(256, math.floor(ideal))),
                  max(1, min(256, math.ceil(ideal)))}
    period = min(candidates, key=lambda value: (abs(clock / (2 * value) - desired), -value))
    return 256 - period, clock / (2 * period)


def pack_pitch(inflection: int, rate: int = 0) -> tuple[int, int]:
    """Return SSI INFLECT/RATEINF bytes without mixing rate into pitch."""
    inflection = _integer_in(inflection, 0, 4095, "inflection")
    rate = _integer_in(rate, 0, 15, "rate")
    return ((inflection >> 3) & 0xFF,
            (rate << 4) | ((inflection >> 8) & 0x08) | (inflection & 0x07))


def ay_period(hz: float, clock_hz: int) -> tuple[int, float]:
    """Return a 1..4095 tone period and achieved Hz, nearest in cents."""
    hz = _positive_finite(hz, "pitch")
    clock = _positive_finite(clock_hz, "AY clock")
    # Bound before division so finite subnormal inputs remain valid.
    if hz <= clock / (16 * 4095):
        return 4095, clock / (16 * 4095)
    if hz >= clock / 16:
        return 1, clock / 16
    ideal = clock / (16 * hz)
    candidates = {max(1, min(4095, math.floor(ideal))),
                  max(1, min(4095, math.ceil(ideal)))}
    period = min(candidates, key=lambda value: (
        abs(math.log2(clock / (16 * value)) - math.log2(hz)), value))
    return period, clock / (16 * period)


def fit_duration(seconds: float, clock_hz: int = NTSC_CPU_HZ) -> tuple[int, int, float]:
    """Return (D, RATE, seconds) nearest one native SSI phoneme interval.

    ``clock_hz`` is the effective XCK rate after DIV2, normally the bus clock.
    The host still owns phoneme boundaries: an interval repeats indefinitely.
    Choose D/R at a phone onset; changing D requires a reg0 phone restart.
    Ties prefer lower D, then lower RATE. Existing explicit controls should
    remain authoritative, especially when a vowel deliberately spans repeats.
    """
    seconds = _positive_finite(seconds, "duration")
    clock = _positive_finite(clock_hz, "effective SSI clock")
    candidates = (
        (duration, rate, 4096 * (4 - duration) * (16 - rate) / clock)
        for duration in range(4) for rate in range(16)
    )
    return min(candidates, key=lambda item: (abs(item[2] - seconds), item[0], item[1]))


def ssi_initialize(chip: int, *, filter_byte: int = SSI_FILTER_NEUTRAL) -> list[tuple[int, int, int]]:
    """Set immediate inflection, then mask speech IRQs, ending muted/CTL low.

    Stream targets 4 and 5 are the left and right SSI sockets. Run this short
    setup while CPU IRQs are masked. A CTL falling edge samples DR as the mode;
    DR=00 masks IRQs but keeps mode 2. Later reg0 writes start phones without
    changing that mode, and live reg1/reg2/reg3 writes preserve the phone.
    """
    chip = _integer_in(chip, 0, 1, "SSI chip")
    filter_byte = _integer_in(filter_byte, 0, 255, "SSI filter register")
    writes = (
        (3, 0x80),  # power down and mute before any mode setup
        (0, 0x80),  # mode 2: phoneme timing, immediate inflection, pause phone
        (1, 0x00),
        (2, 0x00),
        (4, filter_byte),  # profile's neutral tract rate; power-on FF=0 is darker
        (3, 0x00),  # latch mode 2, start muted pause
        (3, 0x80),
        (0, 0x00),  # retain mode 2, disable its external IRQ
        (3, 0x00),  # CTL low: future phone and envelope writes can play
    )
    return [(4 + chip, register, value) for register, value in writes]


def firmware_info(root: Path) -> dict:
    """Inspect a local firmware checkout and compare its pinned contract.

    A matching version label alone is not verification. ``verified`` also
    requires the pinned contract-file SHA-256 values. Git identity and dirty
    state record provenance; unrelated dirty files do not change the contract.
    No fetch, checkout, build or firmware upload occurs here.
    """
    root = Path(root).resolve()
    try:
        version_header = (root / FIRMWARE_SOURCE_FILES[0]).read_text()
    except OSError as exc:
        raise ValueError(f"Cannot read Appletini firmware at {root}") from exc
    match = re.search(r'^\s*#define\s+APPLETINI_FIRMWARE_IMAGE_VERSION_SHORT\s+"([^"]+)"',
                      version_header, re.MULTILINE)
    if not match:
        raise ValueError("Firmware version macro is missing")
    version = match.group(1)
    sources: dict[str, str | None] = {}
    for relative in FIRMWARE_SOURCE_FILES:
        try:
            sources[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        except OSError:
            sources[relative] = None

    def git(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *arguments], capture_output=True,
                text=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip()

    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=normal")
    mismatches = [name for name in FIRMWARE_SOURCE_FILES
                  if sources[name] != TARGET_SOURCE_SHA256.get(name) or sources[name] is None]
    profile_matches = bool(TARGET_SOURCE_SHA256) and not mismatches
    return {
        "version": version,
        "target_version": TARGET_FIRMWARE,
        "version_matches": version == TARGET_FIRMWARE,
        "head": head,
        "dirty": None if status is None else bool(status),
        "sources": sources,
        "profile_commit": TARGET_SOURCE_COMMIT,
        "profile_matches": profile_matches,
        "mismatches": mismatches,
        "verified": version == TARGET_FIRMWARE and profile_matches,
    }
