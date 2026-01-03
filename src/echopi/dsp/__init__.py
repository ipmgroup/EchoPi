"""DSP helpers and signal optimization functions."""

from echopi.dsp.signal_optimization import (
    optimize_chirp_duration,
    calculate_correlation_threshold,
    calculate_optimal_bandwidth,
    calculate_max_unambiguous_distance,
    calculate_processing_gain,
)

__all__ = [
    "optimize_chirp_duration",
    "calculate_correlation_threshold",
    "calculate_optimal_bandwidth",
    "calculate_max_unambiguous_distance",
    "calculate_processing_gain",
]
