#!/usr/bin/env python3
"""GUI for audio signal generation with frequency and amplitude control."""

import sys
import time
import threading
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QSpinBox, QDoubleSpinBox, QPushButton, QGroupBox, QRadioButton
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from echopi.config import AudioDeviceConfig
from echopi.io.audio import PersistentAudioStream
import sounddevice as sd


class SignalGenerator(QMainWindow):
    """GUI application for audio signal generation."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Signal Generator")
        self.setGeometry(100, 100, 600, 400)
        
        # Generator parameters
        self.frequency = 1000  # Hz
        self.amplitude = 0.3  # 0.0 - 1.0
        self.is_playing = False
        self.phase = 0.0
        self.mode = "continuous"  # "continuous" or "pulsed"
        
        # Audio configuration from echopi
        self.audio_cfg = AudioDeviceConfig.from_file()
        self.audio_cfg.frames_per_buffer = 4096  # Large buffer for stability
        self.audio_cfg.latency = "high"  # High latency for stability
        self.sample_rate = self.audio_cfg.sample_rate
        
        # Generation streams
        self.audio_stream = None
        self.sd_stream = None  # For continuous mode
        self.generator_thread = None
        self.stop_event = threading.Event()
        
        # Initialize UI
        self.init_ui()
        
    def init_ui(self):
        """Create user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        central_widget.setLayout(main_layout)
        
        # Title
        title_label = QLabel("Audio Signal Generator")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Frequency control group
        freq_group = QGroupBox("Frequency")
        freq_layout = QVBoxLayout()
        freq_group.setLayout(freq_layout)
        
        freq_info_layout = QHBoxLayout()
        self.freq_label = QLabel(f"Frequency: {self.frequency} Hz")
        freq_info_layout.addWidget(self.freq_label)
        freq_layout.addLayout(freq_info_layout)
        
        freq_slider_layout = QHBoxLayout()
        self.freq_slider = QSlider(Qt.Horizontal)
        self.freq_slider.setMinimum(20)
        self.freq_slider.setMaximum(20000)
        self.freq_slider.setValue(self.frequency)
        self.freq_slider.valueChanged.connect(self.on_frequency_changed)
        freq_slider_layout.addWidget(QLabel("20 Hz"))
        freq_slider_layout.addWidget(self.freq_slider)
        freq_slider_layout.addWidget(QLabel("20 kHz"))
        freq_layout.addLayout(freq_slider_layout)
        
        freq_input_layout = QHBoxLayout()
        freq_input_layout.addWidget(QLabel("Exact value:"))
        self.freq_spinbox = QSpinBox()
        self.freq_spinbox.setMinimum(20)
        self.freq_spinbox.setMaximum(20000)
        self.freq_spinbox.setValue(self.frequency)
        self.freq_spinbox.setSuffix(" Hz")
        self.freq_spinbox.valueChanged.connect(self.on_frequency_spinbox_changed)
        freq_input_layout.addWidget(self.freq_spinbox)
        freq_input_layout.addStretch()
        freq_layout.addLayout(freq_input_layout)
        
        main_layout.addWidget(freq_group)
        
        # Amplitude control group
        amp_group = QGroupBox("Amplitude")
        amp_layout = QVBoxLayout()
        amp_group.setLayout(amp_layout)
        
        amp_info_layout = QHBoxLayout()
        self.amp_label = QLabel(f"Amplitude: {self.amplitude:.2f}")
        amp_info_layout.addWidget(self.amp_label)
        amp_layout.addLayout(amp_info_layout)
        
        amp_slider_layout = QHBoxLayout()
        self.amp_slider = QSlider(Qt.Horizontal)
        self.amp_slider.setMinimum(0)
        self.amp_slider.setMaximum(100)
        self.amp_slider.setValue(int(self.amplitude * 100))
        self.amp_slider.valueChanged.connect(self.on_amplitude_changed)
        amp_slider_layout.addWidget(QLabel("0%"))
        amp_slider_layout.addWidget(self.amp_slider)
        amp_slider_layout.addWidget(QLabel("100%"))
        amp_layout.addLayout(amp_slider_layout)
        
        amp_input_layout = QHBoxLayout()
        amp_input_layout.addWidget(QLabel("Exact value:"))
        self.amp_spinbox = QDoubleSpinBox()
        self.amp_spinbox.setMinimum(0.0)
        self.amp_spinbox.setMaximum(1.0)
        self.amp_spinbox.setSingleStep(0.01)
        self.amp_spinbox.setValue(self.amplitude)
        self.amp_spinbox.valueChanged.connect(self.on_amplitude_spinbox_changed)
        amp_input_layout.addWidget(self.amp_spinbox)
        amp_input_layout.addStretch()
        amp_layout.addLayout(amp_input_layout)
        
        main_layout.addWidget(amp_group)
        
        # Mode selection group
        mode_group = QGroupBox("Generation Mode")
        mode_layout = QHBoxLayout()
        mode_group.setLayout(mode_layout)
        
        self.continuous_radio = QRadioButton("Continuous")
        self.continuous_radio.setChecked(True)
        self.continuous_radio.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.continuous_radio)
        
        self.pulsed_radio = QRadioButton("Pulsed (100 ms)")
        self.pulsed_radio.toggled.connect(self.on_mode_changed)
        mode_layout.addWidget(self.pulsed_radio)
        
        main_layout.addWidget(mode_group)
        
        # Control buttons
        control_layout = QHBoxLayout()
        control_layout.addStretch()
        
        self.start_button = QPushButton("Start")
        self.start_button.setMinimumSize(120, 50)
        self.start_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-size: 14pt; font-weight: bold; }")
        self.start_button.clicked.connect(self.start_signal)
        control_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.setMinimumSize(120, 50)
        self.stop_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; font-size: 14pt; font-weight: bold; }")
        self.stop_button.clicked.connect(self.stop_signal)
        self.stop_button.setEnabled(False)
        control_layout.addWidget(self.stop_button)
        
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        # Status indicator
        self.status_label = QLabel("Status: Stopped")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont()
        status_font.setPointSize(12)
        self.status_label.setFont(status_font)
        main_layout.addWidget(self.status_label)
        
        main_layout.addStretch()
        
    def on_frequency_changed(self, value):
        """Handler for frequency change via slider."""
        self.frequency = value
        self.freq_label.setText(f"Frequency: {self.frequency} Hz")
        self.freq_spinbox.blockSignals(True)
        self.freq_spinbox.setValue(value)
        self.freq_spinbox.blockSignals(False)
        
    def on_frequency_spinbox_changed(self, value):
        """Handler for frequency change via spinbox."""
        self.frequency = value
        self.freq_label.setText(f"Frequency: {self.frequency} Hz")
        self.freq_slider.blockSignals(True)
        self.freq_slider.setValue(value)
        self.freq_slider.blockSignals(False)
        
    def on_amplitude_changed(self, value):
        """Handler for amplitude change via slider."""
        self.amplitude = value / 100.0
        self.amp_label.setText(f"Amplitude: {self.amplitude:.2f}")
        self.amp_spinbox.blockSignals(True)
        self.amp_spinbox.setValue(self.amplitude)
        self.amp_spinbox.blockSignals(False)
        
    def on_amplitude_spinbox_changed(self, value):
        """Handler for amplitude change via spinbox."""
        self.amplitude = value
        self.amp_label.setText(f"Amplitude: {self.amplitude:.2f}")
        self.amp_slider.blockSignals(True)
        self.amp_slider.setValue(int(value * 100))
        self.amp_slider.blockSignals(False)
        
    def on_mode_changed(self):
        """Handler for mode change."""
        if self.continuous_radio.isChecked():
            self.mode = "continuous"
        else:
            self.mode = "pulsed"
        
        # If playing, restart with new mode
        if self.is_playing:
            self.stop_signal()
            time.sleep(0.1)
            self.start_signal()
        
    def continuous_callback(self, outdata, frames, time_info, status):
        """Callback for continuous signal generation."""
        if status:
            print(f"⚠️  Status: {status}")
        
        try:
            # Generate sine wave with continuous phase
            t = (np.arange(frames, dtype=np.float64) + self.phase) / self.sample_rate
            signal = (self.amplitude * np.sin(2 * np.pi * self.frequency * t)).astype(np.float32)
            
            # Update phase for continuity
            self.phase = (self.phase + frames) % self.sample_rate
            
            # Write to output buffer
            outdata[:, 0] = signal
            
        except Exception as e:
            print(f"❌ Callback error: {e}")
            outdata.fill(0)
    
    def generate_signal_loop(self):
        """Thread for pulsed signal generation."""
        try:
            # Create audio stream via echopi
            self.audio_stream = PersistentAudioStream(self.audio_cfg)
            print(f"✓ Audio stream created (fs={self.sample_rate}, buffer={self.audio_cfg.frames_per_buffer})")
            
            # Generate and play in chunks
            chunk_duration = 0.1  # 100 ms per chunk
            chunk_frames = int(self.sample_rate * chunk_duration)
            
            while not self.stop_event.is_set():
                # Generate sine wave chunk
                t = (np.arange(chunk_frames, dtype=np.float64) + self.phase) / self.sample_rate
                signal = (self.amplitude * np.sin(2 * np.pi * self.frequency * t)).astype(np.float32)
                
                # Update phase for continuity
                self.phase = (self.phase + chunk_frames) % self.sample_rate
                
                # Play via echopi stream (with empty record buffer)
                try:
                    self.audio_stream.play_and_record(signal, extra_record_seconds=0.0)
                except Exception as e:
                    if not self.stop_event.is_set():
                        print(f"⚠️  Playback error: {e}")
                        
        except Exception as e:
            print(f"❌ Generation thread error: {e}")
        finally:
            if self.audio_stream is not None:
                self.audio_stream.close()
                self.audio_stream = None
        
    def start_signal(self):
        """Start signal generation."""
        if not self.is_playing:
            self.is_playing = True
            self.phase = 0.0
            self.stop_event.clear()
            
            try:
                if self.mode == "continuous":
                    # Continuous mode - use sounddevice directly
                    time.sleep(0.05)
                    self.sd_stream = sd.OutputStream(
                        samplerate=self.sample_rate,
                        channels=1,
                        callback=self.continuous_callback,
                        blocksize=self.audio_cfg.frames_per_buffer,
                        latency='high',
                        dtype=np.float32
                    )
                    self.sd_stream.start()
                    time.sleep(0.05)
                    print(f"✓ Continuous mode: {self.frequency} Hz, amplitude {self.amplitude:.2f}")
                    mode_text = "Continuous"
                else:
                    # Pulsed mode - use echopi
                    self.generator_thread = threading.Thread(target=self.generate_signal_loop, daemon=True)
                    self.generator_thread.start()
                    print(f"✓ Pulsed mode: {self.frequency} Hz, amplitude {self.amplitude:.2f}")
                    mode_text = "Pulsed"
                
                self.start_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                self.continuous_radio.setEnabled(False)
                self.pulsed_radio.setEnabled(False)
                self.status_label.setText(f"Status: {mode_text} ({self.frequency} Hz, amplitude {self.amplitude:.2f})")
                self.status_label.setStyleSheet("color: green;")
                
            except Exception as e:
                self.is_playing = False
                self.status_label.setText(f"Error: {str(e)}")
                self.status_label.setStyleSheet("color: red;")
                print(f"❌ Start error: {e}")
                
    def stop_signal(self):
        """Stop signal generation."""
        if self.is_playing:
            self.is_playing = False
            
            # Stop continuous stream
            if self.sd_stream is not None:
                try:
                    self.sd_stream.stop()
                    self.sd_stream.close()
                except Exception as e:
                    print(f"⚠️  Stop error: {e}")
                finally:
                    self.sd_stream = None
            
            # Stop pulsed stream
            self.stop_event.set()
            
            if self.generator_thread is not None and self.generator_thread.is_alive():
                self.generator_thread.join(timeout=2.0)
                self.generator_thread = None
                
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.continuous_radio.setEnabled(True)
            self.pulsed_radio.setEnabled(True)
            self.status_label.setText("Status: Stopped")
            self.status_label.setStyleSheet("color: black;")
            print("✓ Generator stopped")
            
    def closeEvent(self, event):
        """Handle window close event."""
        self.stop_signal()
        event.accept()


def main():
    """Launch application."""
    app = QApplication(sys.argv)
    window = SignalGenerator()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
