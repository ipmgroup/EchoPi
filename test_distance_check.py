#!/usr/bin/env python3
"""Test script to diagnose distance measurement issues.

This script will:
1. Measure system latency
2. Perform 5 distance measurements
3. Display detailed results and diagnostics
4. Monitor memory usage
"""
import sys
import time
import tracemalloc
from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.utils.distance import measure_distance
from echopi.utils.latency import measure_latency
from echopi import settings


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
        result = measure_latency(cfg, chirp_cfg)
        latency_s = result['latency_seconds']
        
        print(f"\n✓ Latency measured: {latency_s:.6f} s ({latency_s*1000:.3f} ms)")
        print(f"  Lag samples: {result['lag_samples']}")
        
        # Save to config
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
    
    print(f"\n⚠️  IMPORTANT: Place object at known distance (0.5 - 2.0 m)")
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
                print(f"  ⚠️  NEGATIVE distance! Latency too large!")
            elif distance_m < 0.01:
                print(f"  ⚠️  Distance near ZERO! Check connections/volume")
            if peak < 0.1:
                print(f"  ⚠️  WEAK signal! Increase amplitude or reduce noise")
            
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
        
        print(f"\nDistance (m):")
        print(f"  Mean:   {sum(distances)/len(distances):.3f}")
        print(f"  Min:    {min(distances):.3f}")
        print(f"  Max:    {max(distances):.3f}")
        print(f"  Range:  {max(distances)-min(distances):.3f}")
        
        print(f"\nTime of Flight (ms):")
        print(f"  Mean:   {sum(tofs)/len(tofs):.3f}")
        print(f"  Min:    {min(tofs):.3f}")
        print(f"  Max:    {max(tofs):.3f}")
        
        print(f"\nPeak:")
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
    print("=" * 70)
    print("  EchoPi Distance Measurement Diagnostic")
    print("=" * 70)
    
    # Create audio config
    cfg = AudioDeviceConfig()
    print(f"\nAudio Configuration:")
    print(f"  Sample Rate:  {cfg.sample_rate} Hz")
    print(f"  Device:       {cfg.device_name or 'Default'}")
    
    try:
        # Step 1: Measure latency
        latency = measure_latency_test(cfg)
        
        # Step 2: Measure distance
        measure_distance_test(cfg, num_measurements=5)
        
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
