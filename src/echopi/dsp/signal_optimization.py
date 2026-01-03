"""Signal optimization module for chirp parameter calculation.

This module provides functions to optimize chirp parameters (duration, bandwidth)
based on physical propagation models and target requirements (distance, SNR, resolution).

Formulas are based on:
- Matched filter theory
- Physical sound propagation model
- Rayleigh criterion for resolution
"""

from __future__ import annotations

import numpy as np


def optimize_chirp_duration(
    distance_m: float,
    target_snr_db: float,
    bandwidth_hz: float,
    speed_of_sound: float = 343.0,
    absorption_coeff: float = 0.1,
    ambient_noise_db: float = -60.0
) -> tuple[float, float, float]:
    """Optimize chirp duration for given distance and target SNR.
    
    Physical model accounts for:
    1. Propagation losses (spherical spreading)
    2. Air absorption
    3. Processing gain from matched filtering
    
    FORMULAS:
    ========
    
    1. Signal losses (round trip):
       Loss_spreading = 40 * log10(2 * distance)  [dB]
       Loss_absorption = α * 2 * distance          [dB]
       Loss_total = Loss_spreading + Loss_absorption
    
    2. Required processing gain to achieve target SNR:
       PG_required = SNR_target + Loss_total
    
    3. Processing gain from matched filtering:
       PG = 10 * log10(T_chirp * BW)  [dB]
       where T_chirp - chirp duration [s]
             BW - frequency bandwidth [Hz]
    
    4. Solution for chirp duration:
       T_chirp = 10^(PG_required/10) / BW  [s]
    
    5. Distance resolution (Rayleigh criterion):
       Δr = c / (2 * BW)  [m]
       factor 2 accounts for round trip
    
    Args:
        distance_m: Distance to target in meters (one way)
        target_snr_db: Target SNR in dB
        bandwidth_hz: Chirp frequency bandwidth in Hz (f_max - f_min)
        speed_of_sound: Speed of sound in m/s (default: 343 m/s for air at 20°C)
        absorption_coeff: Absorption coefficient in dB/m (default: 0.1 for 10 kHz)
        ambient_noise_db: Ambient noise level in dBFS
    
    Returns:
        Tuple (T_chirp, estimated_snr, distance_resolution):
        - T_chirp: Optimal chirp duration in seconds
        - estimated_snr: Estimated SNR at given distance in dB
        - distance_resolution: Distance resolution in meters
    
    Example:
        >>> T_chirp, snr, resolution = optimize_chirp_duration(
        ...     distance_m=2.0,
        ...     target_snr_db=15.0,
        ...     bandwidth_hz=9000.0
        ... )
        >>> print(f"Chirp duration: {T_chirp*1000:.2f} ms")
        >>> print(f"Expected SNR: {snr:.1f} dB")
        >>> print(f"Resolution: {resolution*1000:.1f} mm")
    """
    # Round trip distance for echo signal
    round_trip_distance = 2.0 * distance_m
    
    # FORMULA 1: Propagation losses (spherical spreading)
    # For one direction: L = 20*log10(r)
    # For round trip: L = 40*log10(r)
    # Normalized to 1 meter
    spreading_loss_db = 40.0 * np.log10(round_trip_distance / 1.0)
    
    # FORMULA 2: Atmospheric absorption
    # L_abs = α * d, where α - absorption coefficient [dB/m]
    # Typical values at ~10 kHz: 0.1 dB/m
    absorption_loss_db = absorption_coeff * round_trip_distance
    
    # FORMULA 3: Total losses
    total_loss_db = spreading_loss_db + absorption_loss_db
    
    # FORMULA 4: Required processing gain
    # SNR_out = SNR_in + PG
    # PG_required = SNR_target - SNR_in
    # Assume transmission power = 0 dBFS
    received_signal_db = 0 - total_loss_db
    snr_in_db = received_signal_db - ambient_noise_db
    required_gain_db = target_snr_db - snr_in_db
    
    # FORMULA 5: Matched filter processing gain
    # PG = 10 * log10(TBP), where TBP = T * BW
    # Therefore: T = 10^(PG/10) / BW
    required_tbp = 10 ** (required_gain_db / 10.0)
    T_chirp = required_tbp / bandwidth_hz
    
    # Practical limits
    min_duration_s = 0.001  # 1 ms minimum (hardware limitations)
    max_duration_s = 0.200  # 200 ms maximum (real-time constraint)
    T_chirp = np.clip(T_chirp, min_duration_s, max_duration_s)
    
    # FORMULA 6: Actual SNR with optimal duration
    actual_tbp = T_chirp * bandwidth_hz
    actual_processing_gain_db = 10 * np.log10(actual_tbp)
    estimated_snr = snr_in_db + actual_processing_gain_db
    
    # FORMULA 7: Distance resolution (Rayleigh criterion)
    # Δr = c / (2 * BW)
    # Factor 2 accounts for round trip
    time_resolution_s = 1.0 / bandwidth_hz
    distance_resolution = (time_resolution_s * speed_of_sound) / 2.0
    
    return T_chirp, estimated_snr, distance_resolution


def calculate_correlation_threshold(
    chirp_duration_s: float,
    bandwidth_hz: float,
    sample_rate: float,
    window_alpha: float = 0.25
) -> tuple[float, float, float]:
    """Calculate adaptive correlation threshold based on signal properties.
    
    Complex formula accounts for:
    - Chirp duration (longer = better SNR, wider mainlobe)
    - Frequency bandwidth (wider = narrower mainlobe, better resolution)
    - Window type (via alpha parameter, affects sidelobe suppression)
    - Sample rate (affects discrete time resolution)
    
    FORMULAS:
    ========
    
    1. Time resolution from matched filter theory:
       Δt ≈ 1 / BW  [s]
    
    2. Mainlobe width with window function:
       W_mainlobe = Δt * (1 + α/2)  [s]
       where α - Tukey window parameter (fade fraction)
    
    3. Processing gain (time-bandwidth product):
       TBP = T_chirp * BW  [dimensionless]
       PG = 10 * log10(TBP)  [dB]
    
    4. Noise level estimate for matched filter:
       σ_noise = 1 / sqrt(TBP)  [normalized]
    
    5. Detection threshold (6 dB margin above noise):
       threshold = σ_noise * 10^(6/20) = 2 * σ_noise
       (gives ~99.7% detection probability, equivalent to 3-σ)
    
    Args:
        chirp_duration_s: Chirp duration in seconds
        bandwidth_hz: Chirp frequency bandwidth in Hz
        sample_rate: Sample rate in Hz
        window_alpha: Tukey window α parameter (fade fraction, 0 to 1)
    
    Returns:
        Tuple (threshold, mainlobe_width_samples, processing_gain_db):
        - threshold: Normalized correlation threshold (0 to 1)
        - mainlobe_width_samples: Expected mainlobe width in samples
        - processing_gain_db: Processing gain in dB
    
    Example:
        >>> threshold, width, gain = calculate_correlation_threshold(
        ...     chirp_duration_s=0.05,
        ...     bandwidth_hz=9000.0,
        ...     sample_rate=48000.0,
        ...     window_alpha=0.25
        ... )
        >>> print(f"Threshold: {threshold:.4f}")
        >>> print(f"Mainlobe width: {width:.1f} samples")
        >>> print(f"Processing gain: {gain:.1f} dB")
    """
    # FORMULA 1: Theoretical time resolution
    time_resolution_s = 1.0 / bandwidth_hz
    
    # FORMULA 2: Mainlobe width accounting for window
    # Tukey window broadens mainlobe: coefficient = 1 + α/2
    # For α=0.25: coefficient ≈ 1.125
    window_broadening = 1.0 + window_alpha * 0.5
    mainlobe_width_s = time_resolution_s * window_broadening
    mainlobe_width_samples = mainlobe_width_s * sample_rate
    
    # FORMULA 3: Processing gain from time-bandwidth product
    # TBP = T_chirp * BW (dimensionless)
    # Processing Gain = 10*log10(TBP) [dB]
    time_bandwidth_product = chirp_duration_s * bandwidth_hz
    processing_gain_db = 10.0 * np.log10(time_bandwidth_product)
    
    # FORMULA 4: Peak/sidelobe ratio from window
    # Tukey window with α=0.25: sidelobe level ≈ -40 dB
    sidelobe_suppression_db = 40.0 * window_alpha / 0.25
    
    # FORMULA 5: Noise level estimate for matched filter
    # For white noise, matched filter SNR improvement = TBP
    # Noise standard deviation: σ = 1/sqrt(TBP)
    noise_floor = 1.0 / np.sqrt(time_bandwidth_product)
    
    # FORMULA 6: Detection threshold with margin
    # Use 6 dB (coefficient 2) above noise level
    # This gives ~99.7% detection probability (equivalent to 3-σ)
    detection_margin_db = 6.0
    detection_margin_linear = 10 ** (detection_margin_db / 20.0)
    
    # Final threshold (normalized to correlation peak = 1.0)
    threshold = noise_floor * detection_margin_linear
    
    return threshold, mainlobe_width_samples, processing_gain_db


def calculate_optimal_bandwidth(
    target_resolution_m: float,
    speed_of_sound: float = 343.0
) -> float:
    """Calculate optimal frequency bandwidth for desired distance resolution.
    
    FORMULA:
    ========
    From Rayleigh criterion for distance resolution:
    
    Δr = c / (2 * BW)
    
    Therefore:
    BW = c / (2 * Δr)  [Hz]
    
    where:
    - Δr - distance resolution [m]
    - c - speed of sound [m/s]
    - BW - frequency bandwidth [Hz]
    - factor 2 accounts for round trip
    
    Args:
        target_resolution_m: Desired distance resolution in meters
        speed_of_sound: Speed of sound in m/s
    
    Returns:
        Required frequency bandwidth in Hz
    
    Example:
        >>> bw = calculate_optimal_bandwidth(
        ...     target_resolution_m=0.02  # 2 cm resolution
        ... )
        >>> print(f"Required bandwidth: {bw/1000:.1f} kHz")
    """
    # FORMULA: BW = c / (2 * Δr)
    bandwidth_hz = speed_of_sound / (2.0 * target_resolution_m)
    return bandwidth_hz


def calculate_max_unambiguous_distance(
    chirp_duration_s: float,
    speed_of_sound: float = 343.0
) -> float:
    """Calculate maximum unambiguous measurement distance.
    
    FORMULA:
    ========
    Maximum unambiguous distance is determined by time between pulses:
    
    d_max = (c * T_chirp) / 2  [m]
    
    where:
    - c - speed of sound [m/s]
    - T_chirp - chirp duration (pulse repetition period) [s]
    - factor 2 accounts for round trip
    
    Alternative form via PRF (pulse repetition frequency):
    PRF = 1 / T_chirp  [Hz]
    d_max = c / (2 * PRF)  [m]
    
    Args:
        chirp_duration_s: Chirp duration in seconds
        speed_of_sound: Speed of sound in m/s
    
    Returns:
        Maximum unambiguous distance in meters
    
    Example:
        >>> # For 50 ms chirp
        >>> d_max = calculate_max_unambiguous_distance(0.05)
        >>> print(f"Max distance: {d_max:.1f} m")
    """
    # FORMULA: d_max = (c * T) / 2
    max_distance_m = (speed_of_sound * chirp_duration_s) / 2.0
    return max_distance_m


def calculate_processing_gain(
    chirp_duration_s: float,
    bandwidth_hz: float
) -> tuple[float, float]:
    """Calculate matched filter processing gain.
    
    FORMULAS:
    ========
    
    1. Time-Bandwidth Product:
       TBP = T_chirp * BW  [dimensionless]
    
    2. Processing gain in dB:
       PG = 10 * log10(TBP)  [dB]
    
    3. Processing gain in linear scale:
       PG_linear = TBP  [dimensionless]
    
    Physical meaning:
    - TBP shows how many times SNR improves after matched filtering
    - Larger TBP = better detection of weak signals in noise
    
    Args:
        chirp_duration_s: Chirp duration in seconds
        bandwidth_hz: Frequency bandwidth in Hz
    
    Returns:
        Tuple (tbp, processing_gain_db):
        - tbp: Time-bandwidth product (dimensionless)
        - processing_gain_db: Processing gain in dB
    
    Example:
        >>> tbp, pg_db = calculate_processing_gain(0.05, 9000.0)
        >>> print(f"TBP: {tbp:.0f}")
        >>> print(f"Processing gain: {pg_db:.1f} dB")
    """
    # FORMULA 1: TBP = T * BW
    time_bandwidth_product = chirp_duration_s * bandwidth_hz
    
    # FORMULA 2: PG = 10 * log10(TBP)
    processing_gain_db = 10.0 * np.log10(time_bandwidth_product)
    
    return time_bandwidth_product, processing_gain_db
