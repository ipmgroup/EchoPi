#!/usr/bin/env python3
"""Debug script to test sonar measurements and diagnose issues."""

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.utils.distance import measure_distance
import sounddevice as sd

print("=" * 70)
print("SONAR DEBUG TEST")
print("=" * 70)
print()

# Show audio devices
print("Available audio devices:")
print(sd.query_devices())
print()

# Create configuration
cfg = AudioDeviceConfig()
print(f"Using sample rate: {cfg.sample_rate} Hz")
print(f"Playback device: {cfg.play_device}")
print(f"Recording device: {cfg.rec_device}")
print()

# Create chirp configuration
chirp_cfg = ChirpConfig(
    start_freq=2000.0,
    end_freq=20000.0,
    duration=0.05,
    amplitude=0.8,
    fade_fraction=0.0
)

print("Chirp parameters:")
print(f"  Start freq: {chirp_cfg.start_freq} Hz")
print(f"  End freq: {chirp_cfg.end_freq} Hz")
print(f"  Duration: {chirp_cfg.duration} s")
print(f"  Amplitude: {chirp_cfg.amplitude}")
print()

print("Running measurement...")
print("IMPORTANT: Make sure:")
print("  1. Speaker is connected and volume is UP")
print("  2. Microphone is connected and not muted")
print("  3. There is an object 0.5-2m in front of the speaker")
print()

try:
    result = measure_distance(
        cfg,
        chirp_cfg,
        medium="air",
        system_latency_s=0.00121,
        reference_fade=0.05
    )
    
    print("Measurement result:")
    print(f"  Distance: {result['distance_m']:.3f} m ({result['distance_m']*100:.1f} cm)")
    print(f"  Time of flight: {result['time_of_flight_s']*1000:.3f} ms")
    print(f"  Peak value: {result['peak']:.3f}")
    print(f"  Refined peak: {result['refined_peak']:.3f}")
    print(f"  Sound speed: {result['sound_speed']:.1f} m/s")
    print()
    
    if result['distance_m'] < 0.01:
        print("⚠️  WARNING: Distance is essentially 0!")
        print()
        print("Possible issues:")
        print("  1. No echo received - check speaker output")
        print("  2. Microphone not recording - check input")
        print("  3. No object in front of speaker")
        print("  4. Volume too low")
        print("  5. System latency might be wrong")
        
    elif result['refined_peak'] < 0.1:
        print("⚠️  WARNING: Very weak echo signal!")
        print()
        print("Suggestions:")
        print("  1. Increase amplitude (currently {})".format(chirp_cfg.amplitude))
        print("  2. Bring object closer")
        print("  3. Reduce background noise")
        print("  4. Use a better reflecting surface")
        
    else:
        print("✓ Measurement looks good!")
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
