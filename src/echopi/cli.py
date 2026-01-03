from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import sounddevice as sd

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.tone import generate_sine
from echopi.gui.scope import run_scope
from echopi.gui.sonar import run_sonar_gui
from echopi.io import audio
from echopi.utils.latency import measure_latency
from echopi.utils.distance import measure_distance
from echopi import settings


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPi sonar utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="List audio devices")

    p_chirp = sub.add_parser("generate-chirp", help="Save chirp to wav file")
    p_chirp.add_argument("output", type=Path)
    p_chirp.add_argument("--sr", type=int, default=None)
    p_chirp.add_argument("--start", type=float, default=2000)
    p_chirp.add_argument("--end", type=float, default=20000)
    p_chirp.add_argument("--duration", type=float, default=0.05)
    p_chirp.add_argument("--amp", type=float, default=0.8)
    p_chirp.add_argument("--fade", type=float, default=0.0, help="Fade fraction (0=no window, 0.05=5%% Tukey)")

    p_play = sub.add_parser("play", help="Play wav file")
    p_play.add_argument("file", type=Path)
    _add_audio_flags(p_play, playback_only=True)

    p_tone = sub.add_parser("tone", help="Play test sine")
    p_tone.add_argument("--freq", type=float, default=1000.0)
    p_tone.add_argument("--seconds", type=float, default=1.0)
    p_tone.add_argument("--amp", type=float, default=0.8)
    _add_audio_flags(p_tone, playback_only=True)

    p_rec = sub.add_parser("record", help="Record to wav file")
    p_rec.add_argument("output", type=Path)
    p_rec.add_argument("--seconds", type=float, default=5.0)
    _add_audio_flags(p_rec, capture_only=True)

    p_mon = sub.add_parser("monitor", help="Show live mic RMS levels")
    _add_audio_flags(p_mon, capture_only=True)

    p_scope = sub.add_parser("scope", help="Live waveform+FFT via pyqtgraph")
    _add_audio_flags(p_scope, capture_only=True)
    p_scope.add_argument("--demo", action="store_true", help="Use demo mode with generated test signal")
    p_scope.add_argument("--fullscreen", action="store_true", help="Run in fullscreen mode")

    p_sonar = sub.add_parser("sonar", help="Interactive sonar GUI with parameter controls")
    _add_audio_flags(p_sonar)
    p_sonar.add_argument("--gui", action="store_true", help="Run interactive GUI mode (default is GUI)")
    p_sonar.add_argument("--fullscreen", action="store_true", help="Run in fullscreen mode")
    p_sonar.add_argument(
        "--max-distance",
        type=float,
        default=None,
        help="Initial max distance in meters (sets echo record window in GUI)",
    )

    p_check = sub.add_parser("check-device", help="Verify that input/output devices are available")
    _add_audio_flags(p_check)

    p_lat = sub.add_parser("latency", help="Measure play/rec latency via correlation")
    _add_audio_flags(p_lat)
    p_lat.add_argument("--start", type=float, default=1000)
    p_lat.add_argument("--end", type=float, default=10000)
    p_lat.add_argument("--duration", type=float, default=0.05)
    p_lat.add_argument("--amp", type=float, default=0.8)
    p_lat.add_argument("--fade", type=float, default=0.0)
    p_lat.add_argument("--repeats", type=int, default=7, help="Number of measurements to aggregate (median)")
    p_lat.add_argument("--discard", type=int, default=2, help="Discard first N runs (warmup)")
    p_lat.add_argument("--raw", action="store_true", help="Print per-run values (no median-focused output)")

    p_dist = sub.add_parser("distance", help="Measure distance to target via sonar")
    _add_audio_flags(p_dist)
    p_dist.add_argument("--start", type=float, default=None, help="Start frequency (Hz, default: from config)")
    p_dist.add_argument("--end", type=float, default=None, help="End frequency (Hz, default: from config)")
    p_dist.add_argument("--duration", type=float, default=0.05, help="Chirp duration (s)")
    p_dist.add_argument("--amp", type=float, default=None, help="Amplitude 0-1 (default: from config)")
    p_dist.add_argument("--fade", type=float, default=0.0, help="TX fade (0=max energy, not used)")
    p_dist.add_argument("--ref-fade", type=float, default=0.05, help="Reference fade for correlation (0.05=Tukey 5%%)")
    p_dist.add_argument("--medium", type=str, default="air", choices=["air", "water"], help="Propagation medium")
    p_dist.add_argument("--sys-latency", type=float, default=None, help="System latency in seconds (default: from config)")
    p_dist.add_argument(
        "--min-distance",
        type=float,
        default=None,
        help="Min distance in meters for search window (default: from config)",
    )
    p_dist.add_argument(
        "--max-distance",
        type=float,
        default=None,
        help="Max distance in meters used to size echo record window (separates echo window from chirp duration)",
    )
    p_dist.add_argument("--filter", type=int, default=3, help="Smoothing filter size (0=off, 1=raw, 3=moderate, 5+=heavy)")

    p_config = sub.add_parser("config", help="View or edit configuration")
    p_config.add_argument("--show", action="store_true", help="Show current configuration")
    p_config.add_argument("--set-latency", type=float, metavar="SECONDS", help="Set system latency in seconds")

    return parser.parse_args(argv)


def _add_audio_flags(parser: argparse.ArgumentParser, playback_only: bool = False, capture_only: bool = False):
    if not capture_only:
        parser.add_argument("--play-device", type=str, default=None, help="Playback device index or name")
    if not playback_only:
        parser.add_argument("--rec-device", type=str, default=None, help="Input device index or name")
    parser.add_argument("--sr", type=int, default=None, help="Sample rate (default from config file or 48000 for INMP441)")
    parser.add_argument("--frames", type=int, default=2048, help="Frames per buffer")


def _build_audio_cfg(args: argparse.Namespace) -> AudioDeviceConfig:
    # Start with config from file
    cfg = AudioDeviceConfig.from_file()
    
    # Override with command-line arguments if provided
    if hasattr(args, 'play_device') and args.play_device is not None:
        cfg.play_device = _parse_device(args.play_device)
    if hasattr(args, 'rec_device') and args.rec_device is not None:
        cfg.rec_device = _parse_device(args.rec_device)
    if hasattr(args, 'sr') and args.sr is not None:
        cfg.sample_rate = args.sr
    if hasattr(args, 'frames') and args.frames is not None:
        cfg.frames_per_buffer = args.frames
    
    return cfg


def _parse_device(value: str | None) -> int | str | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return value


def cmd_devices():
    devices = audio.list_devices()
    defaults = audio.default_devices()
    print("Default input/output:", defaults)
    for idx, dev in enumerate(devices):
        mark = []
        if defaults["default_input"] == idx:
            mark.append("IN")
        if defaults["default_output"] == idx:
            mark.append("OUT")
        marker = "*" if mark else " "
        print(f"{marker} [{idx:02d}] {dev['name']} :: in={dev['max_input_channels']} out={dev['max_output_channels']} sr={dev['default_samplerate']}")


def cmd_generate_chirp(args: argparse.Namespace):
    cfg = ChirpConfig(start_freq=args.start, end_freq=args.end, duration=args.duration, amplitude=args.amp, fade_fraction=args.fade)
    chirp = generate_chirp(cfg, sample_rate=args.sr)
    chirp = normalize(chirp, peak=cfg.amplitude)
    sf.write(args.output, chirp, args.sr)
    print(f"Saved {args.output} ({len(chirp)/args.sr:.3f}s)")


def cmd_play(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    data, sr = sf.read(args.file, dtype="float32")
    if data.ndim > 1:
        data = data[:, 0]
    if sr != cfg_audio.sample_rate:
        print(f"Warning: file SR {sr} != requested {cfg_audio.sample_rate}, playing as-is")
    audio.play_blocking(data, cfg_audio)


def cmd_tone(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    tone = generate_sine(freq=args.freq, duration=args.seconds, amplitude=args.amp, sample_rate=cfg_audio.sample_rate)
    audio.play_blocking(tone, cfg_audio)


def cmd_record(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    samples = audio.record_blocking(args.seconds, cfg_audio)
    sf.write(args.output, samples, cfg_audio.sample_rate)
    print(f"Recorded {args.output} ({len(samples)/cfg_audio.sample_rate:.2f}s)")


def cmd_monitor(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    print("Press Ctrl+C to stop")

    def on_audio(samples, status):
        if status:
            print(f"Audio status: {status}")
            return
        level = audio.rms_level(samples)
        print(f"RMS: {level:.5f}", end="\r", flush=True)

    try:
        audio.monitor_microphone(cfg_audio, on_audio)
    except KeyboardInterrupt:
        print("\nStopped")


def cmd_scope(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    demo_mode = getattr(args, "demo", False)
    fullscreen = getattr(args, "fullscreen", False)
    # When launched via CLI, show_warning=False (running through proper Core echopi)
    run_scope(cfg_audio, demo_mode=demo_mode, update_interval_ms=500, fullscreen=fullscreen, show_warning=False)


def cmd_check_device(args: argparse.Namespace):
    ok = True

    def check(dev, kind: str) -> bool:
        if dev is None:
            return True
        try:
            info = sd.query_devices(dev, kind=kind)
            idx = sd.default.device[0] if kind == "input" else sd.default.device[1]
            print(f"{kind}: ok -> name='{info['name']}' index={info['index']} max_in={info['max_input_channels']} max_out={info['max_output_channels']} default_index={idx}")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"{kind}: ERROR for {dev}: {exc}")
            return False

    ok &= check(args.rec_device, "input")
    ok &= check(args.play_device, "output")
    defaults = audio.default_devices()
    print(f"System defaults: input={defaults['default_input']} output={defaults['default_output']}")
    if not ok:
        raise SystemExit(1)


def cmd_latency(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    cfg_chirp = ChirpConfig(start_freq=args.start, end_freq=args.end, duration=args.duration, amplitude=args.amp, fade_fraction=args.fade)
    result = measure_latency(cfg_audio, cfg_chirp, repeats=args.repeats, discard=args.discard)
    
    latency_s = result['latency_seconds']
    std_s = result.get('latency_std_seconds', 0.0)

    if getattr(args, "raw", False) and 'latencies_seconds' in result:
        vals_s = result['latencies_seconds']
        vals_ms = [v * 1000 for v in vals_s]
        vals_samples = [int(round(v * cfg_audio.sample_rate)) for v in vals_s]
        print(f"Runs: {len(vals_ms)} (repeats={result.get('repeats')}, discard={result.get('discard')})")
        for i, (ms, samp) in enumerate(zip(vals_ms, vals_samples), start=1):
            print(f"  [{i:02d}] {ms:8.3f} ms  ({samp:5d} samples)")
        print(f"Summary: median={latency_s*1000:.3f} ms, std={std_s*1000:.3f} ms")
    else:
        print(f"Lag samples (median): {result['lag_samples']}")
        print(f"Latency (median): {latency_s*1000:.3f} ms")
        print(f"Stability (std): {std_s*1000:.3f} ms")
        if 'latencies_seconds' in result:
            raw_vals = [f"{v*1000:.3f}" for v in result['latencies_seconds']]
            used_list = result.get('latencies_used_seconds', result['latencies_seconds'])
            used_vals = [f"{v*1000:.3f}" for v in used_list]
            print(
                f"Runs used: {len(used_vals)}/{len(raw_vals)} "
                f"(repeats={result.get('repeats')}, discard={result.get('discard')})"
            )
            print("Per-run used ms:", ", ".join(used_vals))
            if len(raw_vals) != len(used_vals):
                print("Per-run raw ms:", ", ".join(raw_vals))
        print(f"Correlation length: {result['correlation_length']}")
    print()
    
    # Save to config file (sanity-check to avoid saving echo/incorrect peak)
    if not (0.0005 <= latency_s <= 0.01):
        print("⚠ Warning: Measured latency looks unrealistic; not saving.")
        print("  Tip: place speaker 1–5 cm from microphone and re-run.")
        print("  If you really want to save it, use: echopi config --set-latency <seconds>")
        return

    if settings.set_system_latency(latency_s):
        config_file = settings.get_config_file_path()
        print(f"✓ System latency saved to {config_file}")
        print(f"  Use 'echopi distance' or 'echopi sonar' to use this latency")
    else:
        print("⚠ Warning: Failed to save latency to config file")


def cmd_distance(args: argparse.Namespace):
    cfg_audio = _build_audio_cfg(args)
    
    # Get parameters from config if not specified
    start_freq = args.start if args.start is not None else settings.get_start_freq()
    end_freq = args.end if args.end is not None else settings.get_end_freq()
    amplitude = args.amp if args.amp is not None else settings.get_amplitude()
    
    cfg_chirp = ChirpConfig(start_freq=start_freq, end_freq=end_freq, duration=args.duration, amplitude=amplitude, fade_fraction=args.fade)
    
    # Use system latency from config if not specified
    sys_latency = args.sys_latency
    if sys_latency is None:
        sys_latency = settings.get_system_latency()
        config_file = settings.get_config_file_path()
        print(f"Using system latency from {config_file}: {sys_latency*1000:.3f} ms")
        print()
    
    # Use min_distance from config if not specified
    min_dist = args.min_distance
    if min_dist is None:
        min_dist = settings.get_min_distance()
    
    result = measure_distance(
        cfg_audio, 
        cfg_chirp, 
        medium=args.medium, 
        system_latency_s=sys_latency, 
        reference_fade=args.ref_fade,
        min_distance_m=min_dist,
        max_distance_m=args.max_distance,
        filter_size=args.filter
    )
    
    print(f"Medium: {result['medium']}")
    print(f"Sound speed: {result['sound_speed']:.1f} m/s")
    print(f"Total time: {result['total_time_s']*1000:.3f} ms")
    print(f"System latency: {result['system_latency_s']*1000:.3f} ms")
    if result.get('extra_record_seconds') is not None:
        print(f"Echo window: {result['extra_record_seconds']*1000:.1f} ms")
    print(f"Time of flight: {result['time_of_flight_s']*1000:.3f} ms")
    print(f"Lag samples: {result['lag_samples']} (refined: {result['refined_lag']:.2f})")
    print(f"Peak: {result['peak']:.1f} (refined: {result['refined_peak']:.1f})")
    print()
    print("="*60)
    distance = result.get('smoothed_distance_m', result['distance_m'])
    print(f"Distance to obstacle: {distance:.2f} m ({distance*100:.0f} cm)")
    if 'smoothed_distance_m' in result and args.filter > 1:
        print(f"(raw: {result['distance_m']:.2f} m, filter: {args.filter})")
    print("="*60)


def cmd_sonar(args: argparse.Namespace):
    cfg = _build_audio_cfg(args)
    # Note: --gui flag is always True by default behavior, not explicitly checked
    # When launched via CLI, show_warning=False (running through proper Core echopi)
    run_sonar_gui(
        cfg=cfg,
        fullscreen=args.fullscreen,
        show_warning=False,
        max_distance_m=args.max_distance,
    )


def cmd_config(args: argparse.Namespace):
    """Show or edit configuration."""
    config_file = settings.get_config_file_path()
    
    # Set latency if requested
    if args.set_latency is not None:
        if settings.set_system_latency(args.set_latency):
            print(f"✓ System latency set to {args.set_latency*1000:.3f} ms")
            print(f"  Saved to {config_file}")
        else:
            print(f"✗ Failed to save latency to {config_file}")
            return
    
    # Show configuration (default or after setting)
    if args.show or args.set_latency is not None:
        config_settings = settings.load_settings()
        print()
        print("=" * 60)
        print(f"EchoPi Configuration ({config_file})")
        print("=" * 60)
        for key, value in config_settings.items():
            if key == "system_latency_s":
                print(f"  {key:20s}: {value:.6f} s ({value*1000:.3f} ms)")
            else:
                print(f"  {key:20s}: {value}")
        print("=" * 60)


def main(argv: list[str] | None = None):
    args = _parse_args(argv or sys.argv[1:])
    if args.command == "devices":
        cmd_devices()
    elif args.command == "generate-chirp":
        cmd_generate_chirp(args)
    elif args.command == "play":
        cmd_play(args)
    elif args.command == "tone":
        cmd_tone(args)
    elif args.command == "record":
        cmd_record(args)
    elif args.command == "monitor":
        cmd_monitor(args)
    elif args.command == "scope":
        cmd_scope(args)
    elif args.command == "sonar":
        cmd_sonar(args)
    elif args.command == "check-device":
        cmd_check_device(args)
    elif args.command == "latency":
        cmd_latency(args)
    elif args.command == "distance":
        cmd_distance(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        raise SystemExit(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()
