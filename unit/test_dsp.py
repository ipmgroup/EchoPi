import unittest
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Headless backend
import matplotlib.pyplot as plt
from pathlib import Path
from echopi.dsp.correlation import cross_correlation, find_peaks, parabolic_interpolate
from echopi.dsp.chirp import generate_chirp, normalize
from echopi.dsp.tone import generate_sine
from echopi.dsp.signal_optimization import (
    calculate_correlation_threshold, 
    calculate_processing_gain,
    calculate_optimal_bandwidth
)
from echopi.config import ChirpConfig

# Output directory for test plots
OUTPUT_DIR = Path("unit/test_output")
OUTPUT_DIR.mkdir(exist_ok=True)

class TestDSP(unittest.TestCase):
    def test_cross_correlation(self):
        ref = np.sin(np.linspace(0, 10 * np.pi, 100))
        shift = 20
        sig = np.zeros(200)
        sig[shift:shift+100] = ref
        
        peak_idx, peak, corr = cross_correlation(ref, sig)
        
        self.assertEqual(peak_idx, shift)
        self.assertGreater(peak, 0.9)
        
        # Save plot
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))
        ax1.plot(ref)
        ax1.set_title('Reference Signal')
        ax1.set_xlabel('Sample')
        ax1.grid(True)
        
        ax2.plot(sig)
        ax2.set_title(f'Signal (shifted by {shift} samples)')
        ax2.set_xlabel('Sample')
        ax2.grid(True)
        
        ax3.plot(corr)
        ax3.axvline(peak_idx, color='r', linestyle='--', label=f'Peak at {peak_idx}')
        ax3.set_title(f'Cross-correlation (peak={peak:.3f})')
        ax3.set_xlabel('Lag (samples)')
        ax3.legend()
        ax3.grid(True)
        
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_cross_correlation.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_cross_correlation.png'}")

    def test_find_peaks(self):
        corr = np.array([0, 1, 0, 0, 0.5, 0, 0, 0.8, 0])
        peaks = find_peaks(corr, num_peaks=3, min_distance=1)
        
        self.assertEqual(len(peaks), 3)
        self.assertEqual(peaks[0], (1, 1.0))
        self.assertEqual(peaks[1], (7, 0.8))
        self.assertEqual(peaks[2], (4, 0.5))
        
        # Save plot
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(corr, 'b-o', label='Correlation')
        for i, (idx, val) in enumerate(peaks):
            ax.plot(idx, val, 'r*', markersize=15, label=f'Peak {i+1}' if i < 3 else '')
        ax.set_title('Peak Detection')
        ax.set_xlabel('Index')
        ax.set_ylabel('Value')
        ax.legend()
        ax.grid(True)
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_find_peaks.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_find_peaks.png'}")

    def test_parabolic_interpolate(self):
        corr = np.array([0, 9, 10, 9, 0])
        idx, val = parabolic_interpolate(corr, 2)
        self.assertEqual(idx, 2.0)
        self.assertEqual(val, 10.0)
        
        corr = np.array([0, 2, 2, 0])
        idx, val = parabolic_interpolate(corr, 1)
        self.assertEqual(idx, 1.5)
        self.assertGreater(val, 2.0)

    def test_generate_chirp(self):
        cfg = ChirpConfig(start_freq=1000, end_freq=2000, duration=0.1, amplitude=0.5)
        chirp = generate_chirp(cfg, sample_rate=10000)
        
        self.assertEqual(len(chirp), 1000)
        self.assertLessEqual(np.max(np.abs(chirp)), 0.51)
        self.assertEqual(chirp.dtype, np.float32)
        
        # Save plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        time_axis = np.arange(len(chirp)) / 10000
        
        ax1.plot(time_axis * 1000, chirp)
        ax1.set_title(f'Chirp Signal ({cfg.start_freq}-{cfg.end_freq} Hz, {cfg.duration}s)')
        ax1.set_xlabel('Time (ms)')
        ax1.set_ylabel('Amplitude')
        ax1.grid(True)
        
        # Spectrogram
        from scipy import signal
        f, t, Sxx = signal.spectrogram(chirp, fs=10000, nperseg=256)
        ax2.pcolormesh(t * 1000, f, 10 * np.log10(Sxx + 1e-10), shading='gouraud')
        ax2.set_title('Spectrogram')
        ax2.set_ylabel('Frequency (Hz)')
        ax2.set_xlabel('Time (ms)')
        
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_generate_chirp.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_generate_chirp.png'}")

    def test_generate_sine(self):
        sine = generate_sine(freq=1000, duration=0.1, amplitude=0.8, sample_rate=10000)
        self.assertEqual(len(sine), 1000)
        self.assertLessEqual(np.max(np.abs(sine)), 0.81)
        self.assertEqual(sine.dtype, np.float32)
        
        # Save plot
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        time_axis = np.arange(len(sine)) / 10000
        
        # Time domain
        ax1.plot(time_axis[:100] * 1000, sine[:100])
        ax1.set_title('Sine Wave (1000 Hz, first 10ms)')
        ax1.set_xlabel('Time (ms)')
        ax1.set_ylabel('Amplitude')
        ax1.grid(True)
        
        # FFT
        fft = np.fft.rfft(sine)
        freqs = np.fft.rfftfreq(len(sine), 1/10000)
        ax2.plot(freqs, np.abs(fft))
        ax2.set_title('Frequency Spectrum')
        ax2.set_xlabel('Frequency (Hz)')
        ax2.set_ylabel('Magnitude')
        ax2.set_xlim(0, 2000)
        ax2.grid(True)
        
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_generate_sine.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_generate_sine.png'}")

    def test_normalize(self):
        sig = np.array([1, 2, 3, 4, 5], dtype=np.float32)
        norm = normalize(sig, peak=1.0)
        self.assertAlmostEqual(np.max(np.abs(norm)), 1.0)
        self.assertAlmostEqual(norm[4], 1.0)
        self.assertAlmostEqual(norm[0], 0.2)
        
        # Save plot
        fig, ax = plt.subplots(figsize=(10, 5))
        x = np.arange(len(sig))
        ax.bar(x - 0.2, sig, width=0.4, label='Original', alpha=0.7)
        ax.bar(x + 0.2, norm, width=0.4, label='Normalized (peak=1.0)', alpha=0.7)
        ax.set_title('Signal Normalization')
        ax.set_xlabel('Sample')
        ax.set_ylabel('Amplitude')
        ax.legend()
        ax.grid(True, axis='y')
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_normalize.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_normalize.png'}")

    def test_signal_optimization(self):
        # Test processing gain
        duration = 0.05
        bandwidth = 10000.0
        tbp, pg_db = calculate_processing_gain(duration, bandwidth)
        self.assertEqual(tbp, 500.0)
        self.assertAlmostEqual(pg_db, 10 * np.log10(500.0))
        
        # Test optimal bandwidth
        bw = calculate_optimal_bandwidth(target_resolution_m=0.01, speed_of_sound=340.0)
        # bw = c / (2 * dr) = 340 / (2 * 0.01) = 340 / 0.02 = 17000
        self.assertEqual(bw, 17000.0)
        
        # Test correlation threshold
        threshold, width, gain = calculate_correlation_threshold(
            chirp_duration_s=0.05,
            bandwidth_hz=10000.0,
            sample_rate=48000.0
        )
        self.assertGreater(threshold, 0)
        self.assertGreater(width, 0)
        self.assertGreater(gain, 0)

    def test_chirp_windowing(self):
        """Test windowing function for reference chirp in matched filter."""
        # Generate chirp without window (TX chirp)
        cfg_no_window = ChirpConfig(
            start_freq=2000, 
            end_freq=20000, 
            duration=0.05, 
            amplitude=0.8,
            fade_fraction=0.0
        )
        chirp_tx = generate_chirp(cfg_no_window, sample_rate=48000)
        
        # Generate chirp with window (reference for correlation)
        cfg_windowed = ChirpConfig(
            start_freq=2000, 
            end_freq=20000, 
            duration=0.05, 
            amplitude=0.8,
            fade_fraction=0.05
        )
        chirp_ref = generate_chirp(cfg_windowed, sample_rate=48000)
        
        # Verify window is applied
        # Window should taper at edges
        self.assertLess(np.abs(chirp_ref[0]), np.abs(chirp_tx[10]))
        self.assertLess(np.abs(chirp_ref[-1]), np.abs(chirp_tx[-10]))
        
        # Test correlation with and without window
        # Симулируем реальный сонар с matched filter
        echo_delay_samples = 500  # Задержка эха после TX
        
        # Записанный сигнал: TX chirp (без окна) + эхо
        signal_len = echo_delay_samples + len(chirp_tx) + 500
        recorded = np.zeros(signal_len, dtype=np.float32)
        
        # Эхо - отражение TX chirp (который был без окна)
        recorded[echo_delay_samples:echo_delay_samples+len(chirp_tx)] = chirp_tx * 0.5
        
        # Matched filter корреляция с реверсированным эталоном (КАК В СОНАРЕ!)
        # Вариант 1: Windowed reference (better sidelobe suppression)
        chirp_ref_reversed = chirp_ref[::-1]
        peak_idx_windowed, peak_windowed, corr_windowed = cross_correlation(
            chirp_ref_reversed, recorded
        )
        
        # Вариант 2: Non-windowed reference (higher sidelobes)
        chirp_tx_reversed = chirp_tx[::-1]
        peak_idx_no_window, peak_no_window, corr_no_window = cross_correlation(
            chirp_tx_reversed, recorded
        )
        
        # Вычисляем задержку как в distance.py
        ref_offset_windowed = len(chirp_ref) - 1
        ref_offset_no_window = len(chirp_tx) - 1
        
        lag_windowed = peak_idx_windowed - ref_offset_windowed
        lag_no_window = peak_idx_no_window - ref_offset_no_window
        
        # Оба должны детектировать эхо
        self.assertGreater(peak_windowed, 0.5)
        self.assertGreater(peak_no_window, 0.5)
        
        # Non-windowed должен найти близко к истине (может быть небольшой offset)
        self.assertAlmostEqual(lag_no_window, echo_delay_samples, delta=150)
        
        # Windowed может иметь больший сдвиг из-за mismatch (TX без окна, ref с окном)
        # Но все равно должен детектировать в разумных пределах
        self.assertGreater(lag_windowed, echo_delay_samples - 350)
        self.assertLess(lag_windowed, echo_delay_samples + 50)
        
        # Save comprehensive plot
        fig = plt.figure(figsize=(14, 10))
        
        # 1. Chirp signals comparison
        ax1 = plt.subplot(3, 2, 1)
        time_ms = np.arange(len(chirp_tx)) / 48000 * 1000
        ax1.plot(time_ms, chirp_tx, label='TX (no window)', alpha=0.7)
        ax1.plot(time_ms, chirp_ref, label='Reference (windowed)', alpha=0.7)
        ax1.set_title('Chirp Signals: TX vs Reference')
        ax1.set_xlabel('Time (ms)')
        ax1.set_ylabel('Amplitude')
        ax1.legend()
        ax1.grid(True)
        
        # 2. Zoom on start (window effect)
        ax2 = plt.subplot(3, 2, 2)
        zoom_samples = 200
        ax2.plot(time_ms[:zoom_samples], chirp_tx[:zoom_samples], 
                label='TX (no window)', linewidth=2)
        ax2.plot(time_ms[:zoom_samples], chirp_ref[:zoom_samples], 
                label='Reference (windowed)', linewidth=2)
        ax2.set_title('Window Effect at Start')
        ax2.set_xlabel('Time (ms)')
        ax2.set_ylabel('Amplitude')
        ax2.legend()
        ax2.grid(True)
        
        # 3. Spectrograms comparison
        from scipy import signal as scipy_signal
        ax3 = plt.subplot(3, 2, 3)
        f, t, Sxx = scipy_signal.spectrogram(chirp_tx, fs=48000, nperseg=256)
        ax3.pcolormesh(t * 1000, f/1000, 10 * np.log10(Sxx + 1e-10), 
                      shading='gouraud', cmap='viridis')
        ax3.set_title('TX Chirp Spectrogram (No Window)')
        ax3.set_ylabel('Frequency (kHz)')
        ax3.set_xlabel('Time (ms)')
        
        ax4 = plt.subplot(3, 2, 4)
        f, t, Sxx = scipy_signal.spectrogram(chirp_ref, fs=48000, nperseg=256)
        ax4.pcolormesh(t * 1000, f/1000, 10 * np.log10(Sxx + 1e-10), 
                      shading='gouraud', cmap='viridis')
        ax4.set_title('Reference Chirp Spectrogram (Windowed)')
        ax4.set_ylabel('Frequency (kHz)')
        ax4.set_xlabel('Time (ms)')
        
        # 5. Correlation comparison (sidelobe suppression)
        ax5 = plt.subplot(3, 1, 3)
        corr_time = np.arange(len(corr_windowed)) / 48000 * 1000
        
        # Normalize for comparison
        corr_windowed_norm = corr_windowed / np.max(np.abs(corr_windowed))
        corr_no_window_norm = corr_no_window / np.max(np.abs(corr_no_window))
        
        ax5.plot(corr_time, corr_no_window_norm, 
                label='No window (higher sidelobes)', alpha=0.7, linewidth=1)
        ax5.plot(corr_time, corr_windowed_norm, 
                label='Windowed (suppressed sidelobes)', alpha=0.7, linewidth=1)
        ax5.axvline(peak_idx_windowed / 48000 * 1000, color='r', 
                   linestyle='--', label=f'Peak at {peak_idx_windowed} samples', linewidth=2)
        ax5.set_title('Correlation Comparison: Windowing Effect on Sidelobes')
        ax5.set_xlabel('Time (ms)')
        ax5.set_ylabel('Normalized Correlation')
        ax5.legend()
        ax5.grid(True)
        ax5.set_ylim(-0.3, 1.1)
        
        plt.tight_layout()
        plt.savefig(OUTPUT_DIR / 'test_chirp_windowing.png', dpi=150)
        plt.close()
        print(f"✓ Saved: {OUTPUT_DIR / 'test_chirp_windowing.png'}")

if __name__ == '__main__':
    unittest.main()
