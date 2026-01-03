# EchoPi

EchoPi is a sonar prototyping toolkit for Raspberry Pi, designed for acoustic ranging in air and water environments using chirp signals and correlation processing.

## Features

- **Chirp Signal Generation**: Linear frequency-modulated (LFM) chirp signals with configurable parameters
- **Distance Measurement**: Accurate distance measurement using matched filter correlation
- **Real-time GUI**: Interactive sonar visualization with live distance history
- **Audio Scope**: Waveform and spectrum analyzer for signal monitoring
- **Stable Measurements**: Chirp caching and signal normalization for consistent results
- **Multiple Media**: Support for air and water environments with different sound speeds

## Hardware Requirements

- **Platform**: Raspberry Pi 4/5 or CM4/CM5
- **Audio Interface**: I2S devices
  - **TX**: MAX98357 (DAC with amplifier)
  - **RX**: INMP441 (I2S microphone)
- **Sample Rate**: Up to 50 kHz with INMP441 (default: 48 kHz)

## Installation

### 1. System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y libportaudio2 libsndfile1 python3-venv python3-pip
```

For GUI support:
```bash
sudo apt-get install -y xserver-xorg xinit openbox
```

### 2. Python Package

```bash
# Clone repository
cd /home/pi/src/EchoPi5

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install package
pip install -e .
```

## Quick Start

### 1. List Audio Devices

```bash
echopi devices
```

### 2. Measure System Latency

Place speaker close to microphone (1-5 cm) and measure:

```bash
echopi latency --rec-device 0 --play-device 0 --sr 48000
```

### 3. Measure Distance

```bash
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121 \
  --medium air
```

### 4. Launch GUI

```bash
DISPLAY=:0 echopi sonar --gui
```

## CLI Commands

### Audio Device Management

```bash
# List devices
echopi devices

# Check device availability
echopi check-device --rec-device 0 --play-device 0 --sr 48000

# Play test tone
echopi tone --freq 1000 --seconds 2 --play-device 0 --sr 48000

# Record audio
echopi record test.wav --seconds 3 --rec-device 0 --sr 48000

# Play audio file
echopi play test.wav --play-device 0 --sr 48000
```

### Signal Generation

```bash
# Generate chirp signal
echopi generate-chirp chirp.wav \
  --sr 48000 \
  --start 2000 \
  --end 20000 \
  --duration 0.05 \
  --amp 0.8
```

### Distance Measurement

```bash
# Basic measurement (air)
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121

# With custom parameters
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121 \
  --max-distance 10 \
  --start 2000 \
  --end 20000 \
  --duration 0.05 \
  --amp 0.8 \
  --medium air

# Water environment
echopi distance \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000 \
  --sys-latency 0.00121 \
  --medium water
```

### Latency Measurement

```bash
echopi latency \
  --rec-device 0 \
  --play-device 0 \
  --sr 48000
```

### GUI Applications

```bash
# Oscilloscope (waveform + spectrum)
DISPLAY=:0 echopi scope --rec-device 0 --sr 48000

# Sonar GUI (interactive distance measurement)
DISPLAY=:0 echopi sonar --gui
```

## Configuration

Settings are stored in `~/.config/echopi/init.json`:

```json
{
  "system_latency_s": 0.00121,
  "min_distance_m": 0.0,
  "max_distance_m": 17.0,
  "start_freq_hz": 2000.0,
  "end_freq_hz": 20000.0,
  "chirp_duration_s": 0.05,
  "amplitude": 0.8,
  "medium": "air",
  "update_rate_hz": 2.0,
  "filter_size": 3,
  "sample_rate": 48000
}
```

## Project Structure

```
EchoPi5/
├── src/echopi/
│   ├── cli.py              # Command-line interface
│   ├── config.py           # Configuration classes
│   ├── settings.py         # Settings management
│   ├── dsp/                # Digital signal processing
│   │   ├── chirp.py        # Chirp generation
│   │   ├── correlation.py  # Correlation algorithms
│   │   └── tone.py         # Tone generation
│   ├── gui/                # GUI applications
│   │   ├── sonar.py        # Sonar GUI
│   │   └── scope.py        # Oscilloscope
│   ├── io/                 # Audio I/O
│   │   ├── audio.py        # Audio stream management
│   │   └── audio_safe.py   # Safe audio operations
│   └── utils/              # Utilities
│       ├── distance.py     # Distance measurement
│       └── latency.py      # Latency measurement
├── docs/                   # Documentation
├── pyproject.toml          # Project configuration
└── README.md              # This file
```

## Key Features

### Chirp Caching
Chirp signals are cached to ensure stable emission amplitude and prevent volume jumps between measurements.

### Signal Normalization
Optional normalization of recorded signals before correlation for improved stability when amplitude varies.

### Matched Filter
Uses reversed chirp reference for optimal correlation, improving SNR and detection reliability.

### Peak Selection
Intelligent peak selection algorithm filters weak peaks and handles multiple reflections.

## Troubleshooting

### Distance Measurements Unstable

1. **Measure system latency** with speaker close to microphone
2. **Adjust min/max distance** to exclude unwanted reflections
3. **Enable signal normalization** in GUI if amplitude is unstable
4. **Check power supply** (27W for RPi5)

### Volume Jumps

1. **Chirp caching is automatic** - should prevent most issues
2. **Check amplifier status**: `sudo dmesg | grep voicehat`
3. **Verify power supply**: `vcgencmd get_throttled`

### GUI Not Starting

1. **Check X11 display**: `echo $DISPLAY`
2. **Start X server**: `sudo xinit /usr/bin/openbox-session -- :0 vt1 &`
3. **Set DISPLAY**: `export DISPLAY=:0`

## Documentation

- `docs/COMMANDS.md` - Detailed command reference
- `docs/DIAGNOSTIC.md` - Troubleshooting guide
- `docs/SONAR_GUI.md` - GUI usage guide

## License

This project is for research and prototyping purposes.

## Roadmap

### Planned Features

- **System Service (daemon)**: Run EchoPi as a background service for continuous operation
- **ArduPilot Integration**: MAVLink support for integration with ArduPilot autopilot
  - Distance sensor data transmission (DISTANCE_SENSOR message)
  - Command/control interface for start/stop operations
  - Mode switching support
  - Real-time distance data streaming

## Version

Current version: 0.0.1
