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
from echopi.utils.distance import (
    compute_extra_record_seconds,
    measure_distance,
    clear_distance_smoothing,
    set_smoothing_buffer_size,
)
from echopi.utils.latency import measure_latency
from echopi.dsp.signal_optimization import optimize_chirp_duration
from echopi.io import audio_safe as audio
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
    
    def __init__(
        self,
        cfg: AudioDeviceConfig,
        fullscreen: bool = False,
        max_distance_m: float | None = None,
    ):
        super().__init__()
        self.cfg = cfg
        self.fullscreen = fullscreen
        self.running = False
        self.measurement_thread = None
        
        # Default parameters (load from init.json)
        gui_s = settings.get_gui_settings()
        self.start_freq = float(gui_s.get("start_freq_hz", 2000.0))
        self.end_freq = float(gui_s.get("end_freq_hz", 20000.0))
        self.duration = float(gui_s.get("chirp_duration_s", 0.05))
        self.amplitude = float(gui_s.get("amplitude", 0.8))
        self.medium = str(gui_s.get("medium", "air"))
        # Max distance controls echo record window (separate from chirp duration).
        # Default comes from init.json; CLI can override.
        if max_distance_m is None:
            self.max_distance_m = float(gui_s.get("max_distance_m", settings.get_max_distance()))
        else:
            self.max_distance_m = float(max_distance_m)
            # Persist CLI override so next GUI start keeps it.
            try:
                settings.set_max_distance(self.max_distance_m)
            except Exception as e:
                print(f"Warning: failed to persist max_distance_m: {e}")

        self.filter_size = int(gui_s.get("filter_size", 3))
        self.normalize_recorded = bool(gui_s.get("normalize_recorded", False))
        self.update_rate_hz = float(gui_s.get("update_rate_hz", 2.0))
        # Load system latency from config file (init.json if exists, otherwise default)
        self.system_latency = float(gui_s.get("system_latency_s", settings.get_system_latency()))
        # Load min_distance from config (used to filter out near reflections)
        self.min_distance_m = float(gui_s.get("min_distance_m", settings.get_min_distance()))
        
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
        self.start_freq_spin.valueChanged.connect(self._on_start_freq_changed)
        chirp_layout.addRow("Start Freq:", self.start_freq_spin)
        
        self.end_freq_spin = QtWidgets.QSpinBox()
        self.end_freq_spin.setRange(100, 24000)
        self.end_freq_spin.setValue(int(self.end_freq))
        self.end_freq_spin.setSuffix(" Hz")
        self.end_freq_spin.valueChanged.connect(self._on_end_freq_changed)
        chirp_layout.addRow("End Freq:", self.end_freq_spin)
        
        self.duration_spin = QtWidgets.QDoubleSpinBox()
        self.duration_spin.setRange(0.001, 1.0)
        self.duration_spin.setValue(self.duration)
        self.duration_spin.setSingleStep(0.001)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setDecimals(3)
        self.duration_spin.valueChanged.connect(self._on_duration_changed)
        chirp_layout.addRow("Duration:", self.duration_spin)
        
        # Optimize duration button
        self.optimize_duration_btn = QtWidgets.QPushButton("Optimize Duration")
        self.optimize_duration_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                padding: 6px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        self.optimize_duration_btn.clicked.connect(self._optimize_duration)
        chirp_layout.addRow("", self.optimize_duration_btn)
        
        self.amplitude_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.amplitude_slider.setRange(10, 100)
        self.amplitude_slider.setValue(int(self.amplitude * 100))
        self.amplitude_value_label = QtWidgets.QLabel(f"{self.amplitude:.2f}")
        amp_layout = QtWidgets.QHBoxLayout()
        amp_layout.addWidget(self.amplitude_slider)
        amp_layout.addWidget(self.amplitude_value_label)
        chirp_layout.addRow("Amplitude:", amp_layout)
        self.amplitude_slider.valueChanged.connect(self._on_amplitude_changed)
        
        control_layout.addWidget(chirp_group)
        
        # System settings
        system_group = QtWidgets.QGroupBox("System Settings")
        system_layout = QtWidgets.QFormLayout()
        system_group.setLayout(system_layout)
        
        self.medium_combo = QtWidgets.QComboBox()
        self.medium_combo.addItems(["air", "water"])
        self.medium_combo.setCurrentText(self.medium)
        self.medium_combo.currentTextChanged.connect(self._on_medium_changed)
        system_layout.addRow("Medium:", self.medium_combo)

        self.max_distance_spin = QtWidgets.QDoubleSpinBox()
        self.max_distance_spin.setRange(0.1, 200.0)
        self.max_distance_spin.setDecimals(1)
        self.max_distance_spin.setSingleStep(0.5)
        self.max_distance_spin.setSuffix(" m")
        self.max_distance_spin.setValue(self.max_distance_m)
        self.max_distance_spin.setToolTip("Defines echo record window based on round-trip time to this distance")
        self.max_distance_spin.valueChanged.connect(self._on_max_distance_changed)
        system_layout.addRow("Max Distance:", self.max_distance_spin)

        self.min_distance_spin = QtWidgets.QDoubleSpinBox()
        self.min_distance_spin.setRange(0.0, 50.0)
        self.min_distance_spin.setDecimals(1)
        self.min_distance_spin.setSingleStep(0.1)
        self.min_distance_spin.setSuffix(" m")
        self.min_distance_spin.setValue(self.min_distance_m)
        self.min_distance_spin.setToolTip("Minimum distance for search window - filters out close reflections")
        self.min_distance_spin.valueChanged.connect(self._on_min_distance_changed)
        system_layout.addRow("Min Distance:", self.min_distance_spin)

        self.echo_window_label = QtWidgets.QLabel("Echo Window: ---")
        self.echo_window_label.setStyleSheet("font-size: 11px; color: #666;")
        system_layout.addRow("", self.echo_window_label)
        
        self.latency_spin = QtWidgets.QDoubleSpinBox()
        self.latency_spin.setRange(0.0, 1.0)
        self.latency_spin.setDecimals(5)
        self.latency_spin.setSingleStep(0.0001)
        self.latency_spin.setSuffix(" s")
        self.latency_spin.setValue(self.system_latency)  # Now set value after decimals
        self.latency_spin.valueChanged.connect(self._on_latency_changed)
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
        self.update_rate_spin.setValue(self.update_rate_hz)
        self.update_rate_spin.setSingleStep(0.1)
        self.update_rate_spin.setDecimals(1)
        self.update_rate_spin.setSuffix(" Hz")
        self.update_rate_spin.valueChanged.connect(self._on_update_rate_changed)
        system_layout.addRow("Update Rate:", self.update_rate_spin)
        
        self.filter_spin = QtWidgets.QSpinBox()
        self.filter_spin.setRange(0, 10)
        self.filter_spin.setValue(self.filter_size)
        self.filter_spin.setSingleStep(1)
        self.filter_spin.setToolTip("0=Filter off, 1=No smoothing, 3=Moderate, 5+=Heavy")
        self.filter_spin.valueChanged.connect(self._on_filter_changed)
        system_layout.addRow("Filter Size:", self.filter_spin)
        
        self.normalize_checkbox = QtWidgets.QCheckBox("Normalize Recorded Signal")
        self.normalize_checkbox.setChecked(self.normalize_recorded)
        self.normalize_checkbox.setToolTip(
            "Normalize input signal before correlation.\n"
            "Helps with amplitude instability but hides SNR information.\n"
            "See NORMALIZATION_GUIDE.md for details."
        )
        self.normalize_checkbox.stateChanged.connect(self._on_normalize_changed)
        system_layout.addRow("", self.normalize_checkbox)
        
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

        # Initialize derived echo window label and validation
        self._refresh_echo_window()
        
        # Initialize global persistent audio stream early
        # This prevents false first measurements by warming up the audio hardware
        print("Initializing audio stream...")
        try:
            stream = audio.get_global_stream(self.cfg)
            # Агрессивный warmup: несколько dummy измерений для стабилизации voiceHAT
            # Это решает проблему плавающей амплитуды и прыгающих измерений по времени
            import time
            dummy_signal = np.zeros(int(self.cfg.sample_rate * 0.001), dtype=np.float32)
            print("  Warming up audio hardware (this may take a few seconds)...")
            for i in range(10):  # 10 warmup циклов для полной стабилизации
                stream.play_and_record(dummy_signal, extra_record_seconds=0.01, return_tx_index=False)
                time.sleep(0.05)  # 50ms пауза между warmup циклами
            print("✓ Audio stream initialized and stabilized")
        except Exception as e:
            print(f"Warning: Failed to initialize audio stream: {e}")
    
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

        # Reset persistent audio stream so first measurement starts clean.
        try:
            audio.close_global_stream()
        except Exception as e:
            print(f"Warning: failed to reset audio stream: {e}")
        
        self.running = True
        # Clear smoothing buffer when starting new session
        clear_distance_smoothing()
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
                loop_t0 = time.monotonic()

                # Read parameters from UI
                start_freq = float(self.start_freq_spin.value())
                end_freq = float(self.end_freq_spin.value())
                duration = float(self.duration_spin.value())
                amplitude = float(self.amplitude_slider.value()) / 100.0
                medium = str(self.medium_combo.currentText())
                max_distance_m = float(self.max_distance_spin.value())
                min_distance_m = float(self.min_distance_spin.value())
                system_latency = float(self.latency_spin.value())
                update_rate = float(self.update_rate_spin.value())
                filter_size = int(self.filter_spin.value())
                normalize_recorded = bool(self.normalize_checkbox.isChecked())
                
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
                    reference_fade=0.05,
                    min_distance_m=min_distance_m,
                    max_distance_m=max_distance_m,
                    filter_size=filter_size,
                    normalize_recorded=normalize_recorded
                )
                
                measurement_count += 1
                
                # Create a copy to avoid modifying Core echopi result dict
                result_copy = dict(result)
                result_copy['count'] = measurement_count
                
                # Send result via signal
                self.update_signal.emit(result_copy)

                # Wait before next measurement.
                # IMPORTANT: do not add artificial +100ms here.
                # The measurement itself already includes audio I/O time.
                # We only sleep the remaining time to match requested update_rate.
                interval = 1.0 / update_rate if update_rate > 0 else 1.0
                elapsed = time.monotonic() - loop_t0
                sleep_s = interval - elapsed
                if sleep_s > 0:
                    time.sleep(sleep_s)
                
            except ValueError as e:
                # Parameter validation error from core
                measurement_count += 1
                error_msg = f"Parameter validation failed: {str(e)}"
                print(f"❌ {error_msg}")
                self.update_signal.emit({
                    'error': error_msg,
                    'count': measurement_count,
                    'exception_type': 'ValueError'
                })
                # Stop on validation error - parameters need to be fixed
                self.running = False
                break
                
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
            
            # Get smoothed distance from core (distance.py handles smoothing)
            smoothed_distance = result.get('smoothed_distance_m', result['distance_m'])
            distance_m = result['distance_m']
            time_of_flight_s = result['time_of_flight_s']
            peak = result['refined_peak']
            sound_speed = result['sound_speed']
            count = result['count']
            
            # Show warning if distance is 0 or very small
            if smoothed_distance < 0.01:
                self.error_label.setText(
                    "⚠️ Distance is 0 or very small!\n"
                    "Check: 1) Speaker/mic connected? 2) Volume up? 3) Object in front?"
                )
            elif peak < 0.1:
                self.error_label.setText(
                    f"⚠️ Weak echo signal (peak: {peak:.3f})\n"
                    "Try: Increase amplitude, bring object closer, or reduce background noise"
                )
            
            # Update text labels (use smoothed distance for display)
            self.distance_label.setText(f"Distance: {smoothed_distance:.3f} m")
            self.distance_cm_label.setText(f"({smoothed_distance * 100:.1f} cm)")
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
            
            # Add to history (use smoothed distance)
            self.history_time.append(count)
            self.history_distance.append(smoothed_distance)
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
        # Clear smoothing buffer in core
        clear_distance_smoothing()
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
        result = QtWidgets.QMessageBox.question(
            self.win,
            "Latency Measurement",
            "Place speaker CLOSE to microphone\n\n"
            "For accurate system latency measurement:\n\n"
            "1. Position speaker near microphone (1-5 cm)\n"
            "2. Ensure there is no background noise\n"
            "3. Press OK to start measurement\n\n"
            "Measurement will take ~1 second",
            QtWidgets.QMessageBox.StandardButton.Ok | QtWidgets.QMessageBox.StandardButton.Cancel
        )
        
        if result != QtWidgets.QMessageBox.StandardButton.Ok:
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

            # Sanity-check: if speaker isn't close, correlation may lock on an echo.
            # Avoid overwriting good saved latency with an unrealistic value.
            if not (0.0 <= float(latency_s) <= 0.02):
                QtWidgets.QMessageBox.warning(
                    self.win,
                    "Latency Looks Wrong",
                    f"Measured latency looks unrealistic: {latency_s*1000:.1f} ms\n\n"
                    "Not saving this value.\n"
                    "Tip: place speaker 1–5 cm from microphone and remeasure."
                )
                return
            
            # Update value in UI
            self.latency_spin.setValue(latency_s)
            
            # Save to configuration file
            if settings.set_system_latency(latency_s):
                config_file = settings.get_config_file_path()
                print(f"System latency saved to {config_file}")
            
            # Show result
            QtWidgets.QMessageBox.information(
                self.win,
                "Latency Measured",
                f"System latency: {latency_s*1000:.3f} ms\n\n"
                f"Lag: {lag_samples} samples\n"
                f"Sample rate: {self.cfg.sample_rate} Hz\n\n"
                "Value automatically updated in settings."
            )
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.win,
                "Error",
                f"Failed to process result:\n{e}"
            )
    
    def _on_latency_changed(self, value: float):
        """Save latency value to config when manually changed."""
        if settings.set_system_latency(value):
            self.system_latency = value
            print(f"✓ System latency updated: {value:.5f} s")
            settings.set_gui_settings({"system_latency_s": float(value)})


    def _on_start_freq_changed(self, value: int):
        self.start_freq = float(value)
        settings.set_gui_settings({"start_freq_hz": float(value)})


    def _on_end_freq_changed(self, value: int):
        self.end_freq = float(value)
        settings.set_gui_settings({"end_freq_hz": float(value)})


    def _on_amplitude_changed(self, v: int):
        value = float(v) / 100.0
        self.amplitude_value_label.setText(f"{value:.2f}")
        self.amplitude = value
        settings.set_gui_settings({"amplitude": value})
    
    def _on_filter_changed(self, value: int):
        """Update filter size when changed."""
        self.filter_size = value
        settings.set_gui_settings({"filter_size": int(value)})
        if value > 1:
            set_smoothing_buffer_size(value)
            print(f"✓ Filter size changed: {value}")
        elif value == 1:
            print("✓ Filter: no smoothing (raw values)")
        else:
            print("✓ Filter: OFF")
    
    def _on_normalize_changed(self, state: int):
        """Handle normalize checkbox change."""
        self.normalize_recorded = (state == QtCore.Qt.CheckState.Checked.value)
        settings.set_gui_settings({"normalize_recorded": self.normalize_recorded})
        status = "enabled" if self.normalize_recorded else "disabled"
        print(f"✓ Normalize recorded signal: {status}")


    def _refresh_echo_window(self):
        """Update echo window label and re-validate update rate."""
        medium = str(self.medium_combo.currentText())
        max_distance_m = float(self.max_distance_spin.value())
        echo_s = compute_extra_record_seconds(medium=medium, max_distance_m=max_distance_m)
        self.echo_window_label.setText(f"Echo Window: {echo_s*1000:.1f} ms")
        # Trigger validation of update rate against current duration + echo window
        self._on_duration_changed(float(self.duration_spin.value()))


    def _on_medium_changed(self, _value: str):
        settings.set_gui_settings({"medium": str(self.medium_combo.currentText())})
        self._refresh_echo_window()


    def _on_max_distance_changed(self, _value: float):
        value = float(self.max_distance_spin.value())
        self.max_distance_m = value
        try:
            settings.set_max_distance(value)
        except Exception as e:
            print(f"Warning: failed to save max_distance_m: {e}")
        settings.set_gui_settings({"max_distance_m": value})
        self._refresh_echo_window()
    
    def _on_min_distance_changed(self, _value: float):
        value = float(self.min_distance_spin.value())
        self.min_distance_m = value
        try:
            settings.set_min_distance(value)
        except Exception as e:
            print(f"Warning: failed to save min_distance_m: {e}")
        settings.set_gui_settings({"min_distance_m": value})
    
    def _on_duration_changed(self, duration: float):
        """Validate duration vs update rate when duration changes.

        Rule: measurement period must be >= pulse duration + echo window.
        I.e. update_rate <= 1 / (duration + echo_window).
        """
        self.duration = duration
        settings.set_gui_settings({"chirp_duration_s": float(duration)})
        if duration <= 0:
            return

        medium = str(self.medium_combo.currentText())
        max_distance_m = float(self.max_distance_spin.value())
        echo_s = compute_extra_record_seconds(medium=medium, max_distance_m=max_distance_m)
        min_period = duration + echo_s
        max_update_rate = 1.0 / min_period
        current_update_rate = float(self.update_rate_spin.value())
        if current_update_rate > max_update_rate:
            safe_rate = min(self.update_rate_spin.maximum(), max_update_rate)
            safe_rate = round(safe_rate, 1)
            self.update_rate_spin.blockSignals(True)
            self.update_rate_spin.setValue(safe_rate)
            self.update_rate_spin.blockSignals(False)
            print(
                f"⚠ Update rate adjusted to {safe_rate:.1f} Hz "
                f"(min period {min_period:.3f}s = pulse {duration:.3f}s + echo {echo_s:.3f}s)"
            )

    def _optimize_duration(self):
        """Calculate optimal chirp duration based on distance and SNR requirements."""
        # Create dialog for input parameters
        dialog = QtWidgets.QDialog(self.win)
        dialog.setWindowTitle("Optimize Chirp Duration")
        dialog_layout = QtWidgets.QFormLayout()
        dialog.setLayout(dialog_layout)
        
        # Distance input
        distance_spin = QtWidgets.QDoubleSpinBox()
        distance_spin.setRange(0.1, 200.0)
        distance_spin.setDecimals(1)
        distance_spin.setSingleStep(0.5)
        distance_spin.setSuffix(" m")
        distance_spin.setValue(self.max_distance_m)
        dialog_layout.addRow("Target Distance:", distance_spin)
        
        # SNR input
        snr_spin = QtWidgets.QDoubleSpinBox()
        snr_spin.setRange(0.0, 60.0)
        snr_spin.setDecimals(1)
        snr_spin.setSingleStep(1.0)
        snr_spin.setSuffix(" dB")
        snr_spin.setValue(20.0)  # Default target SNR
        dialog_layout.addRow("Target SNR:", snr_spin)
        
        # Bandwidth info (read-only)
        bandwidth_hz = abs(self.end_freq - self.start_freq)
        bandwidth_label = QtWidgets.QLabel(f"{bandwidth_hz:.0f} Hz")
        dialog_layout.addRow("Bandwidth:", bandwidth_label)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | 
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        dialog_layout.addRow(button_box)
        
        # Show dialog
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        
        # Get parameters
        distance_m = distance_spin.value()
        target_snr_db = snr_spin.value()
        
        try:
            # Calculate optimal duration
            optimal_duration, estimated_snr, resolution_m = optimize_chirp_duration(
                distance_m=distance_m,
                target_snr_db=target_snr_db,
                bandwidth_hz=bandwidth_hz
            )
            
            # Show results and ask for confirmation
            result_msg = (
                f"Optimal chirp duration: {optimal_duration*1000:.1f} ms\n\n"
                f"Estimated SNR: {estimated_snr:.1f} dB\n"
                f"Distance resolution: {resolution_m*1000:.1f} mm\n\n"
                f"Apply this duration?"
            )
            
            reply = QtWidgets.QMessageBox.question(
                self.win,
                "Optimization Result",
                result_msg,
                QtWidgets.QMessageBox.StandardButton.Yes | 
                QtWidgets.QMessageBox.StandardButton.No
            )
            
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                # Update duration spinbox
                self.duration_spin.setValue(optimal_duration)
                print(f"✓ Optimal duration applied: {optimal_duration*1000:.1f} ms")
                
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self.win,
                "Optimization Error",
                f"Failed to calculate optimal duration:\n{e}"
            )
    
    def _on_update_rate_changed(self, update_rate: float):
        """Validate update rate vs duration when update rate changes.

        Rule: measurement period must be >= pulse duration + echo window.
        I.e. update_rate <= 1 / (duration + echo_window).
        """
        duration = float(self.duration_spin.value())
        if duration <= 0:
            return

        medium = str(self.medium_combo.currentText())
        max_distance_m = float(self.max_distance_spin.value())
        echo_s = compute_extra_record_seconds(medium=medium, max_distance_m=max_distance_m)
        min_period = duration + echo_s
        max_update_rate = 1.0 / min_period
        if update_rate > max_update_rate:
            safe_rate = min(self.update_rate_spin.maximum(), max_update_rate)
            safe_rate = round(safe_rate, 1)
            self.update_rate_spin.blockSignals(True)
            self.update_rate_spin.setValue(safe_rate)
            self.update_rate_spin.blockSignals(False)
            settings.set_gui_settings({"update_rate_hz": float(safe_rate)})
            print(
                f"⚠ Update rate too fast! Max {safe_rate:.1f} Hz "
                f"(min period {min_period:.3f}s = pulse {duration:.3f}s + echo {echo_s:.3f}s)"
            )
            QtWidgets.QMessageBox.warning(
                self.win,
                "Invalid Update Rate",
                f"Update rate cannot exceed {safe_rate:.1f} Hz\n"
                f"for pulse duration {duration:.3f}s\n"
                f"and echo window {echo_s:.3f}s\n\n"
                f"Rule: period >= pulse + echo\n"
                f"Min period = {min_period:.3f}s => max {max_update_rate:.1f} Hz"
            )
        else:
            settings.set_gui_settings({"update_rate_hz": float(update_rate)})
    
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


def run_sonar_gui(
    cfg: AudioDeviceConfig,
    fullscreen: bool = False,
    show_warning: bool = False,
    max_distance_m: float | None = None,
):
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
        msg.setIcon(QtWidgets.QMessageBox.Icon.Warning)
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
        msg.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        msg.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
        
        if msg.exec() != QtWidgets.QMessageBox.StandardButton.Yes:
            sys.exit(0)
    
    gui = SonarGUI(cfg, fullscreen=fullscreen, max_distance_m=max_distance_m)
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
