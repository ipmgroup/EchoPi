#!/usr/bin/env python3
"""Test script to diagnose distance measurement issues.

This script will:
1. Measure system latency
2. Perform 5 distance measurements
3. Display detailed results and diagnostics
4. Monitor memory usage

NOTE:
- Latency and distance require different physical setups.
    Use --latency and --distance in separate runs to avoid changing external
    conditions mid-test.
"""
import argparse
import sys
import traceback
import time
import tracemalloc

# Allow running this script directly from the repo without installing the package.  # noqa: E501
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from echopi.config import AudioDeviceConfig, ChirpConfig  # noqa: E402
from echopi.utils.distance import measure_distance  # noqa: E402
from echopi.utils.latency import measure_latency  # noqa: E402
from echopi import settings  # noqa: E402

import sounddevice as sd  # noqa: E402


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def measure_latency_test(cfg: AudioDeviceConfig):
    """Measure and save system latency."""
    print_section("STEP 1: System Latency Measurement")
    
    print("\n⚠️  IMPORTANT: Place speaker CLOSE to microphone (1-5 cm)")
    print("Press Enter when ready, or Ctrl+C to skip...")
    try:
        input()
    except KeyboardInterrupt:
        print("\nSkipped latency measurement")
        return None
    
    print("\nMeasuring latency...")
    
    chirp_cfg = ChirpConfig(
        start_freq=2000.0,
        end_freq=20000.0,
        duration=0.05,
        amplitude=0.8,
        fade_fraction=0.0
    )
    
    try:
        result = measure_latency(cfg, chirp_cfg, repeats=7, discard=2)
        latency_s = result['latency_seconds']
        
        print(
            f"\n✓ Latency measured: {latency_s:.6f} s ({latency_s*1000:.3f} ms)"
        )
        print(f"  Lag samples (median): {result['lag_samples']}")
        if 'latency_std_seconds' in result:
            print(f"  Stability (std): {result['latency_std_seconds']*1000:.3f} ms")
        
        # Save to config (sanity-check to avoid saving an echo/incorrect peak)
        if not (0.0005 <= latency_s <= 0.01):
            print("  ⚠️  Warning: latency looks unrealistic; not saving")
        else:
            if settings.set_system_latency(latency_s):
                print(f"  Saved to config: {settings.get_config_file_path()}")
        
        return latency_s
        
    except Exception as e:
        print(f"\n✗ Latency measurement failed: {e}")
        traceback.print_exc()
        return None


def measure_distance_test(cfg: AudioDeviceConfig, num_measurements: int = 5):
    """Perform multiple distance measurements."""
    print_section("STEP 2: Distance Measurements")
    
    # Load current latency
    latency = settings.get_system_latency(verbose=True)
    print(f"\nUsing system latency: {latency:.6f} s ({latency*1000:.3f} ms)")
    
    print("\n⚠️  IMPORTANT: Place object at known distance (0.5 - 2.0 m)")
    print("Press Enter when ready, or Ctrl+C to skip...")
    try:
        input()
    except KeyboardInterrupt:
        print("\nSkipped distance measurements")
        return
    
    # Chirp configuration
    chirp_cfg = ChirpConfig(
        start_freq=2000.0,
        end_freq=20000.0,
        duration=0.05,
        amplitude=0.8,
        fade_fraction=0.0
    )
    
    print(f"\nPerforming {num_measurements} measurements...")
    print("-" * 70)
    
    results = []
    
    for i in range(num_measurements):
        print(f"\n[{i+1}/{num_measurements}] Measuring...")
        
        try:
            result = measure_distance(
                cfg,
                chirp_cfg,
                medium="air",
                system_latency_s=latency,
                reference_fade=0.05
            )
            
            distance_m = result['distance_m']
            tof_s = result['time_of_flight_s']
            peak = result['refined_peak']
            sound_speed = result['sound_speed']
            
            results.append(result)
            
            # Display result
            print(f"  Distance:  {distance_m:.3f} m ({distance_m*100:.1f} cm)")
            print(f"  ToF:       {tof_s*1000:.3f} ms")
            print(f"  Peak:      {peak:.1f}")
            print(f"  Speed:     {sound_speed:.1f} m/s")
            
            # Warnings
            if distance_m < 0:
                print("  ⚠️  NEGATIVE distance! Latency too large!")
            elif distance_m < 0.01:
                print("  ⚠️  Distance near ZERO! Check connections/volume")
            if peak < 0.1:
                print("  ⚠️  WEAK signal! Increase amplitude or reduce noise")
            
            # Wait between measurements
            if i < num_measurements - 1:
                time.sleep(0.5)
                
        except Exception as e:
            print(f"  ✗ Measurement failed: {e}")
            traceback.print_exc()
    
    # Statistics
    if results:
        print_section("MEASUREMENT STATISTICS")
        
        distances = [r['distance_m'] for r in results]
        tofs = [r['time_of_flight_s'] * 1000 for r in results]
        peaks = [r['refined_peak'] for r in results]
        
        print("\nDistance (m):")
        print(f"  Mean:   {sum(distances)/len(distances):.3f}")
        print(f"  Min:    {min(distances):.3f}")
        print(f"  Max:    {max(distances):.3f}")
        print(f"  Range:  {max(distances)-min(distances):.3f}")
        
        print("\nTime of Flight (ms):")
        print(f"  Mean:   {sum(tofs)/len(tofs):.3f}")
        print(f"  Min:    {min(tofs):.3f}")
        print(f"  Max:    {max(tofs):.3f}")
        
        print("\nPeak:")
        print(f"  Mean:   {sum(peaks)/len(peaks):.1f}")
        print(f"  Min:    {min(peaks):.1f}")
        print(f"  Max:    {max(peaks):.1f}")


def check_memory():
    """Check memory usage."""
    print_section("STEP 3: Memory Check")
    
    tracemalloc.start()
    
    # Get snapshot
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')
    
    print("\nTop 5 memory allocations:")
    for stat in top_stats[:5]:
        print(f"  {stat}")
    
    current, peak = tracemalloc.get_traced_memory()
    print(f"\nCurrent memory: {current / 1024 / 1024:.1f} MB")
    print(f"Peak memory:    {peak / 1024 / 1024:.1f} MB")
    
    tracemalloc.stop()


def main():
    """Main test function."""
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--latency",
        action="store_true",
        help="Measure (and optionally save) system latency only",
    )
    parser.add_argument(
        "--distance",
        action="store_true",
        help="Run distance measurements only (uses saved latency)",
    )
    parser.add_argument(
        "--no-save-latency",
        action="store_true",
        help="Do not save measured latency to init.json",
    )
    args = parser.parse_args()

    run_latency = bool(args.latency)
    run_distance = bool(args.distance)
    # Backward-compatible default: run both when no mode flags were provided.
    if not run_latency and not run_distance:
        run_latency = True
        run_distance = True

    print("=" * 70)
    print("  EchoPi Distance Measurement Diagnostic")
    print("=" * 70)
    
    # Create audio config
    cfg = AudioDeviceConfig.from_file()

    # Prefer sample rate from init.json when the selected devices support it.
    preferred_sr = int(settings.load_settings().get("sample_rate", cfg.sample_rate))
    try:
        sd.check_input_settings(device=cfg.rec_device, samplerate=preferred_sr, channels=cfg.channels_rec)
        sd.check_output_settings(device=cfg.play_device, samplerate=preferred_sr, channels=cfg.channels_play)
        cfg.sample_rate = preferred_sr
    except Exception:
        # Keep cfg.sample_rate from audio_config.json / defaults.
        pass
    print("\nAudio Configuration:")
    print(f"  Sample Rate:  {cfg.sample_rate} Hz")
    play_dev = getattr(cfg, "play_device", None)
    rec_dev = getattr(cfg, "rec_device", None)
    print(f"  Play Device:  {play_dev if play_dev is not None else 'Default'}")
    print(f"  Rec Device:   {rec_dev if rec_dev is not None else 'Default'}")
    
    try:
        if run_latency:
            # Step 1: Measure latency
            if args.no_save_latency:
                # Temporarily disable saving by monkey-patching the setter.
                orig_set = settings.set_system_latency

                def _no_save(_: float) -> bool:
                    return False

                settings.set_system_latency = _no_save  # type: ignore[assignment]
                try:
                    _ = measure_latency_test(cfg)
                finally:
                    settings.set_system_latency = orig_set  # type: ignore[assignment]
            else:
                _ = measure_latency_test(cfg)

        if run_distance:
            # Step 2: Measure distance
            measure_distance_test(cfg, num_measurements=5)  # noqa: E501

        # Step 3: Check memory
        check_memory()
        
        print_section("DIAGNOSTIC COMPLETE")
        print("\nRecommendations:")
        print("1. If distances are negative → latency is too large, remeasure it")
        print("2. If distances are zero → check speaker/mic connections and volume")
        print("3. If distances vary a lot → improve environmental conditions (reduce noise)")
        print("4. If memory usage is high → check for memory leaks in GUI")
        print("\n✓ Test completed successfully")
        
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\n✗ Test failed with error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
