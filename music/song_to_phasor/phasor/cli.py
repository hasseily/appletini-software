"""Command-line workflow; heavy analysis and RTL tools are imported only on use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

from .compiler import AY_CLOCKS, DEFAULT_PROFILE, PROFILES, compile_score
from .hardware import TARGET_SOURCE_COMMIT, firmware_info
from .score import validate_score
from .stream import decode, encode


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def checked_firmware(path):
    info = firmware_info(path)
    if not info["verified"]:
        raise ValueError(f"Firmware does not match the F1.2.4 profile: {info['version']}; "
                         f"changed files: {', '.join(info['mismatches'])}")
    return info


def compile_files(score, out, clock, center=True, firmware=None, *,
                  profile=DEFAULT_PROFILE, ssi_effective_clock_hz=None):
    events, report = compile_score(score, clock=clock, center_voice=center,
                                   profile=profile, ssi_effective_clock_hz=ssi_effective_clock_hz)
    if profile == "appletini-f1.2.4":
        report["firmware"] = checked_firmware(firmware) if firmware else {
            "profile_commit": TARGET_SOURCE_COMMIT, "checkout_checked": False}
    data = encode(events, score["tick_hz"], score["duration_ticks"])
    _, stream_info = decode(data)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    save_json(out / "score.json", score)
    (out / "song.phs").write_bytes(data)
    save_json(out / "events.json", {"tick_hz": score["tick_hz"], "duration_ticks": score["duration_ticks"],
                                    "event_fields": ["tick", "target", "register", "value"], "events": events})
    report.update(stream_info)
    report["stream_sha256"] = hashlib.sha256(data).hexdigest()
    save_json(out / "report.json", report)
    return events, report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert songs into vocal-first Phasor streams")
    sub = parser.add_subparsers(dest="command", required=True)
    default_firmware = Path(__file__).resolve().parents[4] / "appletini-one"

    def output(p):
        p.add_argument("--out", type=Path, required=True, help="output directory")

    def model(p):
        p.add_argument("--firmware-root", type=Path, default=default_firmware)
        p.add_argument("--cache", type=Path, default=Path(".cache"))

    def compile_options(p):
        p.add_argument("--clock", choices=("ntsc", "pal"), default="ntsc")
        p.add_argument("--no-center", action="store_true", help="keep a single vocal on its chosen SSI socket")
        p.add_argument("--profile", choices=PROFILES, default=DEFAULT_PROFILE,
                       help="SSI register equations: physical-ssi263 (datasheet; real Phasor, Appletini F1.2.5+) "
                            "or appletini-f1.2.4 (obsolete F1.2.4 model, needed for RTL fit/listen)")
        p.add_argument("--ssi-effective-clock-hz", type=float,
                       help="physical-ssi263 only: effective XCK after clock division; default regional AY clock / 2")

    def fit_options(p):
        p.add_argument("--filters", type=int, nargs="+", default=[96, 128, 160], help="FF values to compare in the model bank")
        p.add_argument("--bank-pitch-hz", type=float, help="fixed reference-bank pitch for cache reuse; default: rounded source median")
        p.add_argument("--lock-phonemes", action="store_true", help="preserve aligned phonemes; fit their tract settings only")

    for name in ("analyze", "convert"):
        p = sub.add_parser(name, help="analyze song/stems" if name == "analyze" else "analyze and compile a song")
        p.add_argument("song", type=Path)
        p.add_argument("--vocals", type=Path, help="isolated vocal stem, starting at the song's time zero")
        p.add_argument("--accompaniment", type=Path, help="backing stem, starting at the song's time zero")
        p.add_argument("--annotations", type=Path, help="timed SSI phoneme JSON; annotation gaps are silent")
        p.add_argument("--tick-hz", type=int, default=100)
        p.add_argument("--transpose", type=int, default=0, help="semitones, applied to both vocals and backing")
        output(p)
        if name == "convert":
            compile_options(p)
            model(p)
            fit_options(p)
            p.add_argument("--fit", action="store_true", help="refine phoneme/tract choices against the cached RTL bank")
            p.add_argument("--listen", action="store_true", help="render actual SSI RTL and compare the vocal with the source")
    p = sub.add_parser("compile", help="compile an editable score without audio dependencies")
    p.add_argument("score", type=Path)
    output(p)
    compile_options(p)
    p.add_argument("--firmware-root", type=Path)
    p = sub.add_parser("check-firmware")
    p.add_argument("firmware_root", type=Path, nargs="?", default=default_firmware)
    p = sub.add_parser("inspect")
    p.add_argument("stream", type=Path)
    p = sub.add_parser("render", help="render the two SSI sockets from a PHS1 stream, using actual firmware RTL")
    p.add_argument("stream", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--clock", choices=("ntsc", "pal"), default="ntsc", help="must match the compilation report")
    p.add_argument("--full", action="store_true", help="include all four AY chips and the native Phasor stereo mix")
    p.add_argument("--vocal-output", type=Path, help="with --full, also save the isolated SSI stem")
    p.add_argument("--backing-output", type=Path, help="with --full, also save the isolated AY stem")
    model(p)
    p = sub.add_parser("compare", help="measure pitch, voicing, timing, level and spectrum; not lyric intelligibility")
    p.add_argument("reference", type=Path)
    p.add_argument("candidate", type=Path)
    p.add_argument("--output", type=Path)
    p = sub.add_parser("fit", help="refine a score's vocal against an RTL reference bank")
    p.add_argument("score", type=Path)
    p.add_argument("vocals", type=Path)
    output(p)
    model(p)
    fit_options(p)
    compile_options(p)
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        if hasattr(args, "profile"):
            compile_kwargs = {"profile": args.profile,
                              "ssi_effective_clock_hz": args.ssi_effective_clock_hz}
            if args.profile == "physical-ssi263" and (
                    args.command == "fit" or getattr(args, "fit", False) or getattr(args, "listen", False)):
                raise ValueError("physical-ssi263 cannot use RTL fit/listen: the pinned RTL is the F1.2.4 speech model; "
                                 "pass --profile appletini-f1.2.4 for those tools")
        if args.command == "check-firmware":
            info = checked_firmware(args.firmware_root)
            print(json.dumps(info, indent=2))
        elif args.command == "inspect":
            events, info = decode(args.stream.read_bytes())
            info["register_writes"] = len(events)
            print(json.dumps(info, indent=2))
        elif args.command == "compile":
            _, report = compile_files(read_json(args.score), args.out, args.clock, not args.no_center,
                                      args.firmware_root, **compile_kwargs)
            print(json.dumps(report, indent=2))
        elif args.command == "render":
            # PHS1 bytes do not identify their compiler profile. Preserve the
            # adjacent report when sharing streams; a bare stream cannot be
            # distinguished safely from Appletini register data.
            report_path = args.stream.parent / "report.json"
            if report_path.exists():
                report = read_json(report_path)
                if not isinstance(report, dict):
                    raise ValueError(f"Invalid compilation report: {report_path}")
                if report.get("profile") == "physical-ssi263":
                    raise ValueError("Cannot render physical-ssi263 registers with the Appletini RTL; use a physical recording")
            events, info = decode(args.stream.read_bytes())
            if args.full:
                from .full_render import render_full
                print("Rendering the complete Phasor through the pinned firmware RTL...", file=sys.stderr, flush=True)
                metadata = render_full(events, info["tick_hz"], info["duration_ticks"], args.firmware_root,
                                       args.output, args.cache, xck_hz=AY_CLOCKS[args.clock],
                                       ay_clock_hz=AY_CLOCKS[args.clock], vocal_output=args.vocal_output,
                                       backing_output=args.backing_output)
            else:
                if args.vocal_output or args.backing_output:
                    raise ValueError("--vocal-output and --backing-output require --full")
                from .rtl import render
                print("Rendering SSI vocals through the pinned firmware RTL...", file=sys.stderr, flush=True)
                metadata = render(events, info["tick_hz"], info["duration_ticks"], args.firmware_root, args.output, args.cache,
                                  xck_hz=AY_CLOCKS[args.clock])
            save_json(args.output.with_suffix(".render.json"), metadata)
            print(f"Rendered {'Phasor mix' if args.full else 'SSI vocals'}: {args.output}")
        elif args.command == "compare":
            from .compare import compare_audio
            metrics = compare_audio(args.reference, args.candidate)
            if args.output:
                save_json(args.output, metrics)
            print(json.dumps(metrics, indent=2))
        elif args.command == "fit":
            from .fit import fit_score
            checked_firmware(args.firmware_root)
            print("Loading or building the cached RTL voice bank, then fitting...", file=sys.stderr, flush=True)
            score, fit_report = fit_score(read_json(args.score), args.vocals, args.firmware_root, args.cache,
                                          locked_phonemes=args.lock_phonemes, filters=tuple(args.filters),
                                          bank_pitch_hz=args.bank_pitch_hz)
            compile_files(score, args.out, args.clock, not args.no_center, args.firmware_root, **compile_kwargs)
            save_json(args.out / "fit.json", fit_report)
            print(f"Fitted score and stream: {args.out}")
        else:
            from .audio import analyze_audio
            print("Analyzing vocal and accompaniment audio...", file=sys.stderr, flush=True)
            score = analyze_audio(args.song, vocals=args.vocals, accompaniment=args.accompaniment,
                                  annotations=args.annotations, tick_hz=args.tick_hz, transpose=args.transpose)
            validate_score(score)
            save_json(args.out / "analysis.score.json", score)
            if args.command == "analyze":
                print(f"Editable score: {args.out / 'analysis.score.json'}")
            else:
                original = score
                reference = args.vocals or args.song
                if args.fit or args.listen:
                    checked_firmware(args.firmware_root)
                if args.fit:
                    from .fit import fit_score
                    print("Loading or building the cached RTL voice bank, then fitting...", file=sys.stderr, flush=True)
                    score, fit_report = fit_score(score, reference, args.firmware_root, args.cache,
                        locked_phonemes=args.lock_phonemes or args.annotations is not None,
                        filters=tuple(args.filters), bank_pitch_hz=args.bank_pitch_hz)
                    save_json(args.out / "fit.json", fit_report)
                    save_json(args.out / "candidate.score.json", score)
                events, report = compile_files(score, args.out, args.clock, not args.no_center,
                                               args.firmware_root if args.fit or args.listen else None, **compile_kwargs)
                if args.listen:
                    from .rtl import render
                    from .compare import compare_audio, select_fit
                    print("Rendering the candidate SSI vocal and measuring it against the source...", file=sys.stderr, flush=True)
                    candidate_path = args.out / ("candidate.rtl.wav" if args.fit else "vocals.rtl.wav")
                    metadata = render(events, score["tick_hz"], score["duration_ticks"], args.firmware_root,
                                      candidate_path, args.cache, xck_hz=AY_CLOCKS[args.clock])
                    metrics = {"candidate": compare_audio(reference, candidate_path)}
                    if args.fit:
                        print("Rendering the baseline SSI vocal for the before/after comparison...", file=sys.stderr, flush=True)
                        baseline, _ = compile_score(original, args.clock, not args.no_center, **compile_kwargs)
                        baseline_metadata = render(baseline, score["tick_hz"], score["duration_ticks"], args.firmware_root,
                                                   args.out / "baseline.rtl.wav", args.cache, xck_hz=AY_CLOCKS[args.clock])
                        metrics["baseline"] = compare_audio(reference, args.out / "baseline.rtl.wav")
                        metrics["selection"] = select_fit(metrics["baseline"], metrics["candidate"])
                        if metrics["selection"]["selected"] == "baseline":
                            score = original
                            events, report = compile_files(score, args.out, args.clock, not args.no_center,
                                                           args.firmware_root, **compile_kwargs)
                            metadata = baseline_metadata
                            shutil.copyfile(args.out / "baseline.rtl.wav", args.out / "vocals.rtl.wav")
                        else:
                            shutil.copyfile(candidate_path, args.out / "vocals.rtl.wav")
                        report["fit_selection"] = metrics["selection"]
                        metadata["selected_output"] = str(args.out / "vocals.rtl.wav")
                        print(f"Selected {metrics['selection']['selected']} from the rendered comparison.", file=sys.stderr, flush=True)
                    metrics["reference_is_mix"] = args.vocals is None
                    metrics["transposition_semitones"] = args.transpose
                    if args.transpose:
                        metrics["note"] = "Pitch error includes intentional transposition relative to the original recording."
                    save_json(args.out / "comparison.json", metrics)
                    save_json(args.out / "render.json", metadata)
                report["conversion_seconds"] = time.perf_counter() - started
                save_json(args.out / "report.json", report)
                print(f"Score, Phasor stream and reports: {args.out}")
    except (ValueError, OSError, RuntimeError, KeyError, ImportError) as exc:
        parser.exit(2, f"song-to-phasor: {exc}\n")
    return 0
