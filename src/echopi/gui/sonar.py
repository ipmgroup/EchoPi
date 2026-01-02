"""Sonar GUI for EchoPi.

IMPORTANT: This GUI is a frontend only and should NOT be run independently.
It depends on Core echopi for all sonar computations:
- Signal processing must be done in echopi.dsp modules
- Distance calculations must use echopi.utils.distance
- Latency measurements must use echopi.utils.latency

This GUI only provides visualization and user controls. All actual sonar
logic and calculations MUST remain in the Core echopi modules.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import tracemalloc
import psutil

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

from echopi.config import AudioDeviceConfig, ChirpConfig
from echopi.utils.distance import measure_distance
from echopi.utils.latency import measure_latency
from echopi import settings


def _check_x11_display() -> bool:
    """Checks if an X11 display is available."""
    display = os.environ.get("DISPLAY")
    if not display:
        return False
    
    if display.startswith(":"):
        x11_socket = f"/tmp/.X11-unix/X{display[1:]}"
        return os.path.exists(x11_socket)
    
    return True


class SonarGUI(QtCore.QObject):
    """Interactive GUI for sonar visualization.
    
    WARNING: This is a frontend-only component. Do NOT implement sonar
    computation logic here. All signal processing, distance calculations,
    and measurement algorithms MUST be implemented in Core echopi modules:
    - echopi.dsp.* for signal processing
    - echopi.utils.distance for distance measurements
    - echopi.utils.latency for latency compensation
    
    This class should only:
    - Display results from Core echopi
    - Provide user interface controls
    - Handle UI updates and user interactions
    """
    
    # Signals for thread-safe UI updates
    update_signal = QtCore.pyqtSignal(dict)
    latency_signal = QtCore.pyqtSignal(dict)
    
    def __init__(self, cfg: AudioDeviceConfig, fullscreen: bool = False):
        super().__init__()
        self.cfg = cfg
        self.fullscreen = fullscreen
        self.running = False
        self.measurement_thread = None
        
        # Default parameters
        self.start_freq = 2000.0
        self.end_freq = 20000.0
        self.duration = 0.05
        self.amplitude = 0.8
        self.medium = "air"
        # Load system latency from config file (init.json if exists, otherwise default)
        self.system_latency = settings.get_system_latency(verbose=True)
        
        # Measurement history
        self.history_time = []
        self.history_distance = []
        self.max_history = 100
        
        # Memory monitoring
        self.process = psutil.Process()
        self.initial_memory_mb = self.process.memory_info().rss / 1024 / 1024
        tracemalloc.start()
        
        # Connect signals
        self.update_signal.connect(self._update_display)
        self.latency_signal.connect(self._latency_measured)
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Create user interface."""
        pg.setConfigOptions(antialias=False)
        self.app = pg.mkQApp("EchoPi Sonar")
        
        # Main window
        self.win = QtWidgets.QWidget()
        self.win.setWindowTitle("EchoPi Sonar - Interactive")
        
        if self.fullscreen:
            self.win.showFullScreen()
        else:
            self.win.resize(1400, 900)
        
        # Main layout
        main_layout = QtWidgets.QHBoxLayout()
        self.win.setLayout(main_layout)
        
        # Left panel - graphs
        graph_widget = pg.GraphicsLayoutWidget()
        main_layout.addWidget(graph_widget, stretch=3)
        
        # Distance history plot
        self.distance_plot = graph_widget.addPlot(title="Distance History", row=0, col=0)
        self.distance_plot.setLabel("left", "Distance", units="m")
        self.distance_plot.setLabel("bottom", "Measurement", units="#")
        self.distance_plot.showGrid(x=True, y=True, alpha=0.3)
        self.distance_curve = self.distance_plot.plot(pen=pg.mkPen("g", width=2))
        
        # Time of flight history plot
        self.tof_plot = graph_widget.addPlot(title="Time of Flight History", row=1, col=0)
        self.tof_plot.setLabel("left", "ToF", units="ms")
        self.tof_plot.setLabel("bottom", "Measurement", units="#")
        self.tof_plot.showGrid(x=True, y=True, alpha=0.3)
        self.tof_curve = self.tof_plot.plot(pen=pg.mkPen("c", width=2))
        self.history_tof = []
        
        # Right panel - controls
        control_panel = QtWidgets.QWidget()
        control_layout = QtWidgets.QVBoxLayout()
        control_panel.setLayout(control_layout)
        main_layout.addWidget(control_panel, stretch=1)
        
        # Title
        title = QtWidgets.QLabel("SONAR CONTROL")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 10px;")
        control_layout.addWidget(title)
        
        # Start/Stop button
        self.start_btn = QtWidgets.QPushButton("START SONAR")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 15px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.start_btn.clicked.connect(self._toggle_sonar)
        control_layout.addWidget(self.start_btn)
        
        # Measurement results
        results_group = QtWidgets.QGroupBox("Measurement Results")
        results_layout = QtWidgets.QVBoxLayout()
        results_group.setLayout(results_layout)
        
        self.distance_label = QtWidgets.QLabel("Distance: --- m")
        self.distance_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #4CAF50;")
        results_layout.addWidget(self.distance_label)
        
        self.distance_cm_label = QtWidgets.QLabel("(--- cm)")
        self.distance_cm_label.setStyleSheet("font-size: 16px; color: #666;")
        results_layout.addWidget(self.distance_cm_label)
        
        self.tof_label = QtWidgets.QLabel("Time of Flight: --- ms")
        self.tof_label.setStyleSheet("font-size: 14px;")
        results_layout.addWidget(self.tof_label)
        
        self.peak_label = QtWidgets.QLabel("Peak: ---")
        self.peak_label.setStyleSheet("font-size: 14px;")
        results_layout.addWidget(self.peak_label)
        
        self.speed_label = QtWidgets.QLabel("Sound Speed: 343.0 m/s")
        self.speed_label.setStyleSheet("font-size: 14px;")
        results_layout.addWidget(self.speed_label)
        
        self.count_label = QtWidgets.QLabel("Measurements: 0")
        self.count_label.setStyleSheet("font-size: 12px; color: #888;")
        results_layout.addWidget(self.count_label)
        
        self.memory_label = QtWidgets.QLabel("Memory: --- MB")
        self.memory_label.setStyleSheet("font-size: 11px; color: #888;")
        results_layout.addWidget(self.memory_label)
        
        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("font-size: 11px; color: #f44336; word-wrap: break-word;")
        self.error_label.setWordWrap(True)
        results_layout.addWidget(self.error_label)
        
        control_layout.addWidget(results_group)
        
        # Chirp parameters
        chirp_group = QtWidgets.QGroupBox("Chirp Parameters")
        chirp_layout = QtWidgets.QFormLayout()
        chirp_group.setLayout(chirp_layout)
        
        self.start_freq_spin = QtWidgets.QSpinBox()
        self.start_freq_spin.setRange(100, 24000)
        self.start_freq_spin.setValue(int(self.start_freq))
        self.start_freq_spin.setSuffix(" Hz")
        chirp_layout.addRow("Start Freq:", self.start_freq_spin)
        
        self.end_freq_spin = QtWidgets.QSpinBox()
        self.end_freq_spin.setRange(100, 24000)
        self.end_freq_spin.setValue(int(self.end_freq))
        self.end_freq_spin.setSuffix(" Hz")
        chirp_layout.addRow("End Freq:", self.end_freq_spin)
        
        self.duration_spin = QtWidgets.QDoubleSpinBox()
        self.duration_spin.setRange(0.01, 1.0)
        self.duration_spin.setValue(self.duration)
        self.duration_spin.setSingleStep(0.01)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setDecimals(3)
        chirp_layout.addRow("Duration:", self.duration_spin)
        
        self.amplitude_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.amplitude_slider.setRange(10, 100)
        self.amplitude_slider.setValue(int(self.amplitude * 100))
        self.amplitude_value_label = QtWidgets.QLabel(f"{self.amplitude:.2f}")
        amp_layout = QtWidgets.QHBoxLayout()
        amp_layout.addWidget(self.amplitude_slider)
        amp_layout.addWidget(self.amplitude_value_label)
        chirp_layout.addRow("Amplitude:", amp_layout)
        self.amplitude_slider.valueChanged.connect(
            lambda v: self.amplitude_value_label.setText(f"{v/100:.2f}")
        )
        
        control_layout.addWidget(chirp_group)
        
        # System settings
        system_group = QtWidgets.QGroupBox("System Settings")
        system_layout = QtWidgets.QFormLayout()
        system_group.setLayout(system_layout)
        
        self.medium_combo = QtWidgets.QComboBox()
        self.medium_combo.addItems(["air", "water"])
        self.medium_combo.setCurrentText(self.medium)
        system_layout.addRow("Medium:", self.medium_combo)
        
        self.latency_spin = QtWidgets.QDoubleSpinBox()
        self.latency_spin.setRange(0.0, 0.1)
        self.latency_spin.setValue(self.system_latency)
        self.latency_spin.setSingleStep(0.0001)
        self.latency_spin.setDecimals(6)
        self.latency_spin.setSuffix(" s")
        system_layout.addRow("Sys Latency:", self.latency_spin)
        
        # Latency measurement button
        self.measure_latency_btn = QtWidgets.QPushButton("Measure Latency")
        self.measure_latency_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 8px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        self.measure_latency_btn.clicked.connect(self._measure_latency)
        system_layout.addRow("", self.measure_latency_btn)
        
        # Latency measurement instruction
        latency_info = QtWidgets.QLabel("⚠️ Place speaker\nclose to microphone")
        latency_info.setStyleSheet("font-size: 11px; color: #FF9800; margin-top: 5px;")
        latency_info.setWordWrap(True)
        system_layout.addRow("", latency_info)
        
        self.update_rate_spin = QtWidgets.QDoubleSpinBox()
        self.update_rate_spin.setRange(0.1, 10.0)
        self.update_rate_spin.setValue(2.0)
        self.update_rate_spin.setSingleStep(0.1)
        self.update_rate_spin.setDecimals(1)
        self.update_rate_spin.setSuffix(" Hz")
        system_layout.addRow("Update Rate:", self.update_rate_spin)
        
        control_layout.addWidget(system_group)
        
        # Control buttons
        btn_layout = QtWidgets.QHBoxLayout()
        
        clear_btn = QtWidgets.QPushButton("Clear History")
        clear_btn.clicked.connect(self._clear_history)
        btn_layout.addWidget(clear_btn)
        
        control_layout.addLayout(btn_layout)
        control_layout.addStretch()
        
        # Show window
        self.win.show()
    
    def _toggle_sonar(self):
        """Enable/disable sonar."""
        if not self.running:
            self._start_sonar()
        else:
            self._stop_sonar()
    
    def _start_sonar(self):
        """Start sonar."""
        # Clear screen on start
        self._clear_history()
        
        self.running = True
        self.start_btn.setText("STOP SONAR")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 15px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        
        # Start measurement thread
        self.measurement_thread = threading.Thread(target=self._measurement_loop, daemon=True)
        self.measurement_thread.start()
    
    def _stop_sonar(self):
        """Stop sonar."""
        self.running = False
        if self.measurement_thread and self.measurement_thread.is_alive():
            self.measurement_thread.join(timeout=3.0)
            # Force cleanup if thread didn't stop
            if self.measurement_thread.is_alive():
                print("Warning: Measurement thread did not stop cleanly")
            self.measurement_thread = None
        
        self.start_btn.setText("START SONAR")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 16px;
                font-weight: bold;
                padding: 15px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
    
    def _measurement_loop(self):
        """Measurement loop in separate thread.
        
        NOTE: All sonar computations are delegated to Core echopi:
        - measure_distance() from echopi.utils.distance
        This GUI only reads parameters and displays results.
        """
        measurement_count = 0
        
        while self.running:
            try:
                # Read parameters from UI
                start_freq = float(self.start_freq_spin.value())
                end_freq = float(self.end_freq_spin.value())
                duration = float(self.duration_spin.value())
                amplitude = float(self.amplitude_slider.value()) / 100.0
                medium = str(self.medium_combo.currentText())
                system_latency = float(self.latency_spin.value())
                update_rate = float(self.update_rate_spin.value())
                
                # Create chirp configuration
                chirp_cfg = ChirpConfig(
                    start_freq=start_freq,
                    end_freq=end_freq,
                    duration=duration,
                    amplitude=amplitude,
                    fade_fraction=0.0
                )
                
                # Perform measurement (Core echopi)
                result = measure_distance(
                    self.cfg,
                    chirp_cfg,
                    medium=medium,
                    system_latency_s=system_latency,
                    reference_fade=0.05
                )
                
                measurement_count += 1
                
                # Create a copy to avoid modifying Core echopi result dict
                result_copy = dict(result)
                result_copy['count'] = measurement_count
                
                # Send result via signal
                self.update_signal.emit(result_copy)
                
                # Wait before next measurement
                if update_rate > 0:
                    time.sleep(1.0 / update_rate)
                else:
                    time.sleep(1.0)
                
            except Exception as e:
                measurement_count += 1
                error_msg = f"Measurement #{measurement_count} failed: {str(e)[:100]}"
                print(error_msg)
                print("=" * 70)
                import traceback
                traceback.print_exc()
                print("=" * 70)
                # Send error to GUI
                self.update_signal.emit({
                    'error': error_msg, 
                    'count': measurement_count,
                    'exception_type': type(e).__name__
                })
                # Longer sleep on error to prevent rapid memory allocation
                time.sleep(2.0)
        
        print(f"Measurement loop stopped after {measurement_count} measurements")
    
    @QtCore.pyqtSlot(dict)
    def _update_display(self, result: dict):
        """Update display of results (in main thread)."""
        try:
            # Check for error message
            if 'error' in result:
                error_text = f"⚠️ {result['error']}"
                if 'exception_type' in result:
                    error_text += f"\nType: {result['exception_type']}"
                self.error_label.setText(error_text)
                if 'count' in result:
                    self.count_label.setText(f"Measurements: {result['count']}")
                # Update memory even on error
                current_memory_mb = self.process.memory_info().rss / 1024 / 1024
                memory_delta = current_memory_mb - self.initial_memory_mb
                self.memory_label.setText(f"Memory: {current_memory_mb:.1f} MB (+{memory_delta:.1f})")
                return
            
            # Clear error label on successful measurement
            self.error_label.setText("")
            
            distance_m = result['distance_m']
            time_of_flight_s = result['time_of_flight_s']
            peak = result['refined_peak']
            sound_speed = result['sound_speed']
            count = result['count']
            
            # Show warning if distance is 0 or very small
            if distance_m < 0.01:
                self.error_label.setText(
                    "⚠️ Distance is 0 or very small!\n"
                    "Check: 1) Speaker/mic connected? 2) Volume up? 3) Object in front?"
                )
            elif peak < 0.1:
                self.error_label.setText(
                    f"⚠️ Weak echo signal (peak: {peak:.3f})\n"
                    "Try: Increase amplitude, bring object closer, or reduce background noise"
                )
            
            # Update text labels
            self.distance_label.setText(f"Distance: {distance_m:.3f} m")
            self.distance_cm_label.setText(f"({distance_m * 100:.1f} cm)")
            self.tof_label.setText(f"Time of Flight: {time_of_flight_s * 1000:.3f} ms")
            self.peak_label.setText(f"Peak: {peak:.1f}")
            self.speed_label.setText(f"Sound Speed: {sound_speed:.1f} m/s")
            self.count_label.setText(f"Measurements: {count}")
            
            # Update memory usage
            current_memory_mb = self.process.memory_info().rss / 1024 / 1024
            memory_delta = current_memory_mb - self.initial_memory_mb
            self.memory_label.setText(f"Memory: {current_memory_mb:.1f} MB (+{memory_delta:.1f})")
            
            # Warning for memory leak
            if memory_delta > 100:
                self.error_label.setText(
                    f"⚠️ Memory leak detected! {memory_delta:.0f} MB increase.\n"
                    "Consider restarting the application."
                )
            
            # Add to history
            self.history_time.append(count)
            self.history_distance.append(distance_m)
            self.history_tof.append(time_of_flight_s * 1000)
            
            # Limit history size - use slicing to prevent memory fragmentation
            if len(self.history_time) > self.max_history:
                self.history_time = self.history_time[-self.max_history:]
                self.history_distance = self.history_distance[-self.max_history:]
                self.history_tof = self.history_tof[-self.max_history:]
            
            # Update plots
            if len(self.history_time) > 0:
                # Use list() to create new list copies to prevent reference issues
                self.distance_curve.setData(list(self.history_time), list(self.history_distance))
                self.tof_curve.setData(list(self.history_time), list(self.history_tof))
                
                # Auto-scale
                self.distance_plot.enableAutoRange()
                self.tof_plot.enableAutoRange()
                
        except Exception as e:
            print(f"Display update error: {e}")
    
    def _clear_history(self):
        """Clear measurement history."""
        # Clear lists completely by reassigning to free memory
        self.history_time = []
        self.history_distance = []
        self.history_tof = []
        # Clear plot curves
        self.distance_curve.setData([], [])
        self.tof_curve.setData([], [])
    
    def _measure_latency(self):
        """Start latency measurement in separate thread.
        
        NOTE: Actual measurement is done by Core echopi:
        - measure_latency() from echopi.utils.latency
        """
        if self.running:
            QtWidgets.QMessageBox.warning(
                self.win,
                "Sonar Active",
                "Stop sonar before measuring latency"
            )
            return
        
        # Show instruction dialog
        msg = QtWidgets.QMessageBox(self.win)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setWindowTitle("Latency Measurement")
        msg.setText("Place speaker CLOSE to microphone")
        msg.setInformativeText(
            "For accurate system latency measurement:\n\n"
            "1. Position speaker near microphone (1-5 cm)\n"
            "2. Ensure there is no background noise\n"
            "3. Press OK to start measurement\n\n"
            "Measurement will take ~1 second"
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        
        if msg.exec() != QtWidgets.QMessageBox.Ok:
            return
        
        # Disable button and show progress
        self.measure_latency_btn.setEnabled(False)
        self.measure_latency_btn.setText("Measuring...")
        
        # Start measurement in separate thread
        thread = threading.Thread(target=self._latency_measurement_thread, daemon=True)
        thread.start()
    
    def _latency_measurement_thread(self):
        """Latency measurement thread.
        
        NOTE: Actual computation is done by Core echopi:
        - measure_latency() from echopi.utils.latency
        """
        try:
            # Create chirp configuration for measurement
            chirp_cfg = ChirpConfig(
                start_freq=2000.0,
                end_freq=20000.0,
                duration=0.05,
                amplitude=0.8,
                fade_fraction=0.0
            )
            
            # Perform measurement (Core echopi)
            result = measure_latency(self.cfg, chirp_cfg)
            
            # Send result via signal
            self.latency_signal.emit(result)
            
        except Exception as e:
            print(f"Latency measurement error: {e}")
            # Send empty result to reset button
            self.latency_signal.emit({'error': str(e)})
    
    @QtCore.pyqtSlot(dict)
    def _latency_measured(self, result: dict):
        """Process latency measurement result (in main thread)."""
        # Re-enable button
        self.measure_latency_btn.setEnabled(True)
        self.measure_latency_btn.setText("Measure Latency")
        
        if 'error' in result:
            QtWidgets.QMessageBox.critical(
                self.win,
                "Measurement Error",
                f"Failed to measure latency:\n{result['error']}"
            )
            return
        
        try:
            latency_s = result['latency_seconds']
            lag_samples = result['lag_samples']
            
            # Update value in UI
            self.latency_spin.setValue(latency_s)
            
            # Save to configuration file
            if settings.set_system_latency(latency_s):
                config_file = settings.get_config_file_path()
                print(f"System latency saved to {config_file}")
            
            # Show result
            msg = QtWidgets.QMessageBox(self.win)
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setWindowTitle("Latency Measured")
            msg.setText(f"System latency: {latency_s*1000:.3f} ms")
            msg.setInformativeText(
                f"Lag: {lag_samples} samples\n"
                f"Sample rate: {self.cfg.sample_rate} Hz\n\n"
                "Value automatically updated in settings."
            )
            msg.exec()
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.win,
                "Error",
                f"Failed to process result:\n{e}"
            )
    
    def run(self):
        """Run the application."""
        try:
            self.app.exec()
        finally:
            # Ensure clean shutdown
            self.running = False
            if self.measurement_thread and self.measurement_thread.is_alive():
                self.measurement_thread.join(timeout=3.0)
            # Clear all data to free memory
            self._clear_history()
            # Disconnect signals to prevent memory leaks
            try:
                self.update_signal.disconnect()
                self.latency_signal.disconnect()
            except:
                pass


def run_sonar_gui(cfg: AudioDeviceConfig, fullscreen: bool = False, show_warning: bool = False):
    """Launch interactive sonar GUI.
    
    WARNING: This is a frontend only. All sonar computations must be
    done in Core echopi modules (echopi.dsp.*, echopi.utils.*).
    Do NOT implement signal processing or calculations in this GUI.
    
    Args:
        cfg: Audio device configuration
        fullscreen: Run in fullscreen mode
        show_warning: Show warning dialog if running without Core echopi
    """
    
    if not _check_x11_display():
        print("ERROR: No X11 display available!", file=sys.stderr)
        print("\nNo X11 server is running on this device.", file=sys.stderr)
        sys.exit(1)
    
    # Show warning if running directly (not via Core echopi CLI)
    if show_warning:
        app = pg.mkQApp("EchoPi Sonar")
        msg = QtWidgets.QMessageBox()
        msg.setIcon(QtWidgets.QMessageBox.Warning)
        msg.setWindowTitle("⚠️ Sonar GUI Running Without Core echopi")
        msg.setText("This GUI is running in STANDALONE mode")
        msg.setInformativeText(
            "WARNING: This is a FRONTEND ONLY component!\n\n"
            "All sonar computations are performed by Core echopi:\n"
            "  • echopi.dsp.*           - Signal processing\n"
            "  • echopi.utils.distance  - Distance measurements\n"
            "  • echopi.utils.latency   - Latency compensation\n\n"
            "This GUI should be launched via Core echopi CLI:\n"
            "  echopi sonar            - Launch via CLI\n"
            "  echopi sonar --gui      - Interactive GUI mode\n\n"
            "Direct execution is for TESTING ONLY.\n"
            "Continue anyway?"
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        msg.setDefaultButton(QtWidgets.QMessageBox.No)
        
        if msg.exec() != QtWidgets.QMessageBox.Yes:
            sys.exit(0)
    
    gui = SonarGUI(cfg, fullscreen=fullscreen)
    gui.run()


if __name__ == "__main__":
    # Console warning
    print("=" * 70)
    print("WARNING: Running Sonar GUI directly (standalone mode)")
    print("=" * 70)
    print()
    print("This GUI is a FRONTEND ONLY component that depends on Core echopi.")
    print()
    print("All sonar computations are performed by Core echopi modules:")
    print("  • echopi.dsp.*           - Signal processing")
    print("  • echopi.utils.distance  - Distance measurements")
    print("  • echopi.utils.latency   - Latency compensation")
    print()
    print("Recommended usage:")
    print("  echopi sonar            - Launch via CLI (recommended)")
    print("  echopi sonar --gui      - Interactive GUI mode")
    print()
    print("Direct execution is for testing purposes only.")
    print("=" * 70)
    print()
    
    cfg = AudioDeviceConfig()
    run_sonar_gui(cfg, fullscreen=False, show_warning=True)
