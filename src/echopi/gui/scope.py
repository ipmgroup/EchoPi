from __future__ import annotations

import os
import sys
import threading

import numpy as np
import pyqtgraph as pg
import sounddevice as sd
from pyqtgraph.Qt import QtCore, QtWidgets

from echopi.config import AudioDeviceConfig


def _check_x11_display() -> bool:
    """Checks if an X11 display is available."""
    display = os.environ.get("DISPLAY")
    if not display:
        return False
    
    # Check availability of local X11 server
    if display.startswith(":"):
        # Local display (:0, :1, etc.)
        x11_socket = f"/tmp/.X11-unix/X{display[1:]}"
        return os.path.exists(x11_socket)
    
    # X11 forwarding (localhost:10.0, etc.)
    return True


def run_scope(cfg: AudioDeviceConfig, update_interval_ms: int = 500, demo_mode: bool = False, fullscreen: bool = False, show_warning: bool = False):
    """Live waveform + spectrum viewer using pyqtgraph.
    
    Args:
        cfg: Audio device configuration
        update_interval_ms: GUI update interval in milliseconds (default 500ms = 2 FPS)
        demo_mode: Use generated test signal instead of microphone
        fullscreen: Run in fullscreen mode
        show_warning: Show warning dialog if running without Core echopi
    """
    
    # Check if X11 display is available
    if not _check_x11_display():
        print("ERROR: No X11 display available!", file=sys.stderr)
        print("\nNo X11 server is running on this device.", file=sys.stderr)
        print("To launch the GUI, do one of the following:", file=sys.stderr)
        print("  1. Start X11 server locally: startx", file=sys.stderr)
        print("  2. Set DISPLAY: DISPLAY=:0 echopi scope", file=sys.stderr)
        print("  3. Use SSH with X11 forwarding: ssh -X user@host", file=sys.stderr)
        sys.exit(1)

    pg.setConfigOptions(antialias=False)  # Disable antialiasing for performance
    app = pg.mkQApp("EchoPi Scope")
    
    # Show warning if running directly (not via Core echopi CLI)
    if show_warning:
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setWindowTitle("⚠️ Scope GUI Running Without Core echopi")
        msg.setText("This GUI is running in STANDALONE mode")
        msg.setInformativeText(
            "WARNING: This is a FRONTEND ONLY component!\n\n"
            "This GUI should be launched via Core echopi CLI:\n"
            "  echopi scope            - Launch via CLI\n"
            "  echopi scope --demo     - Demo mode\n\n"
            "Direct execution is for TESTING ONLY.\n"
            "Continue anyway?"
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msg.setDefaultButton(QtWidgets.QMessageBox.No)
        
        if msg.exec() != QtWidgets.QMessageBox.Yes:
            sys.exit(0)

    win = pg.GraphicsLayoutWidget(show=True, title="EchoPi Live Scope")
    
    if fullscreen:
        win.showFullScreen()
    else:
        win.resize(1200, 800)

    waveform_plot = win.addPlot(title="Waveform")
    waveform_plot.showGrid(x=True, y=True, alpha=0.3)
    waveform_plot.setLabel("bottom", "Time", units="s")
    waveform_curve = waveform_plot.plot(pen=pg.mkPen("c", width=1.5))

    win.nextRow()
    spectrum_plot = win.addPlot(title="Spectrum")
    spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
    spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
    spectrum_plot.setLabel("left", "Magnitude", units="dBFS")
    spectrum_curve = spectrum_plot.plot(pen=pg.mkPen("y", width=1.5))

    # Thread-safe buffer: using double buffering with lock
    buffer_size = 8192
    audio_buffer_a = np.zeros(buffer_size, dtype=np.float32)
    audio_buffer_b = np.zeros(buffer_size, dtype=np.float32)
    current_buffer = [0]  # 0 = write to A, read B; 1 = write to B, read A
    buffer_lock = threading.Lock()
    write_pos = [0]
    
    # For demo mode
    demo_phase = [0.0]

    def audio_callback(indata, frames, time_info, status):  # noqa: ANN001, ANN202
        # Fast callback - minimal operations
        if status:
            return
            
        try:
            with buffer_lock:
                # Select buffer for writing
                buf = audio_buffer_a if current_buffer[0] == 0 else audio_buffer_b
                
                if demo_mode:
                    # Generate test data
                    t = np.arange(frames, dtype=np.float32) / cfg.sample_rate
                    signal = (0.3 * np.sin(2 * np.pi * 440 * (t + demo_phase[0]))
                            + 0.05 * np.sin(2 * np.pi * 880 * (t + demo_phase[0])))
                    demo_phase[0] = (demo_phase[0] + frames / cfg.sample_rate) % 1.0
                    data = signal
                else:
                    # Get data from microphone
                    data = indata[:, 0] if indata.ndim == 2 else indata
                
                # Simple ring buffer write
                n = min(len(data), buffer_size)
                pos = write_pos[0]
                
                if pos + n <= buffer_size:
                    buf[pos:pos+n] = data[:n]
                    write_pos[0] = (pos + n) % buffer_size
                else:
                    first = buffer_size - pos
                    buf[pos:] = data[:first]
                    buf[:n-first] = data[first:n]
                    write_pos[0] = n - first
        except:
            pass  # Ignore errors in callback

    # Create stream
    if demo_mode:
        # Виртуальный поток для демо
        class DemoStream:
            def __init__(self):
                self.timer = QtCore.QTimer()
                self.timer.timeout.connect(lambda: audio_callback(None, 512, None, None))
                
            def start(self):
                self.timer.start(100)  # Every 100 ms
                
            def stop(self):
                self.timer.stop()
                
            def close(self):
                pass
        
        stream = DemoStream()
    else:
        stream = sd.InputStream(
            channels=cfg.channels_rec,
            samplerate=cfg.sample_rate,
            blocksize=cfg.frames_per_buffer,
            device=cfg.rec_device,
            dtype="float32",
            callback=audio_callback,
        )

    def update_gui():
        """GUI update - called by timer in main thread"""
        try:
            # Switch buffers
            with buffer_lock:
                current_buffer[0] = 1 - current_buffer[0]
                # Читаем из другого буфера
                data = (audio_buffer_b if current_buffer[0] == 0 else audio_buffer_a).copy()
            
            # Update waveform
            t = np.arange(len(data), dtype=np.float32) / cfg.sample_rate
            waveform_curve.setData(t, data)
            
            # Calculate spectrum
            windowed = data * np.hanning(len(data))
            fft = np.fft.rfft(windowed)
            magnitude = np.abs(fft)
            
            # Convert to dB
            magnitude_db = 20 * np.log10(magnitude + 1e-10)
            magnitude_db = magnitude_db - np.max(magnitude_db)
            
            freqs = np.fft.rfftfreq(len(data), 1.0 / cfg.sample_rate)
            spectrum_curve.setData(freqs, magnitude_db)
            spectrum_plot.setYRange(-80, 0)
            spectrum_plot.setXRange(0, min(cfg.sample_rate / 2, 24000))
        except:
            pass  # Ignore update errors

    # Timer for GUI updates
    gui_timer = QtCore.QTimer()
    gui_timer.timeout.connect(update_gui)
    gui_timer.start(update_interval_ms)

    # Start audio stream
    stream.start()
    
    try:
        app.exec()
    finally:
        gui_timer.stop()
        stream.stop()
        stream.close()


if __name__ == "__main__":
    # Console warning
    print("=" * 70)
    print("WARNING: Running Scope GUI directly (standalone mode)")
    print("=" * 70)
    print()
    print("This GUI is a FRONTEND ONLY component for live visualization.")
    print()
    print("Recommended usage:")
    print("  echopi scope            - Launch via CLI (recommended)")
    print("  echopi scope --demo     - Demo mode without audio device")
    print()
    print("Direct execution is for testing purposes only.")
    print("=" * 70)
    print()
    
    cfg = AudioDeviceConfig()
    run_scope(cfg, update_interval_ms=500, demo_mode=True, show_warning=True)
