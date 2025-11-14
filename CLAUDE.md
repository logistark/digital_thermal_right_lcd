# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Linux driver for Thermalright CPU cooler LCD screens. It controls an 84-LED HID USB device (Vendor: 0x0416, Product: 0x8001) to display CPU/GPU metrics and time on 7-segment displays.

## Development Setup

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run controller directly
python3 src/controller.py config.json

# Run with test mode (cycles through digits 0-9)
python3 src/controller.py config.json --test

# Launch UI to modify configuration
python3 src/led_display_ui.py config.json

# Build as executable
pyinstaller --onefile src/controller.py
```

## Hardware Architecture

### LED Layout
- **84 total LEDs** divided into CPU (0-41) and GPU (42-83) sections
- Each section has:
  - 2 device indicator LEDs
  - 21 temperature LEDs (3 digits × 7 segments)
  - 16 usage LEDs (2 LEDs for "1" + 2 digits × 7 segments)
  - 1 unit LED (°C or °F)
  - 1 percent LED

### Critical: GPU LED Reversal
**GPU LEDs are physically wired in REVERSE ORDER within each 7-segment digit**:
- CPU temp: LEDs 2→22 (ascending)
- GPU temp: LEDs 81→61 (descending)

When displaying numbers on GPU, reverse each digit's 7 segments individually using:
```python
leds = leds.reshape(-1, 7)[:, ::-1].flatten()
```

Do NOT reverse the entire array or you'll get incorrect digits.

### 7-Segment Layout
Each digit uses 7 LEDs in this order:
```
[top, top-right, bottom-right, bottom, bottom-left, top-left, middle]
```

## Software Architecture

### Core Components

**src/controller.py** - Main controller with display logic
- `MatrixController`: Low-level LED control, USB communication
- `Controller`: High-level display modes, metric formatting
- Display modes: metrics, time, alternate_time, debug_ui
- Uses HID protocol with 512-byte packets (4 × 128-byte chunks)

**src/metrics.py** - Cross-platform hardware metrics
- Tries multiple methods to find working temperature/usage sources
- Supports: psutil, Linux sysfs, Windows WMI, NVIDIA (nvml/smi), AMD (pyamdgpuinfo)
- Caches metrics based on `update_interval`

**src/config.py** - LED mappings and configuration constants
- `leds_indexes`: Maps logical names to physical LED positions
- `display_modes`: Available display modes
- `default_config`: Default configuration structure

**src/utils.py** - Color utilities
- `interpolate_color()`: Linear RGB interpolation
- `get_random_color()`: Random hex color generation

### Configuration System

The `config.json` contains:
- `display_mode`: Current display mode
- `metrics.colors`: Array of 84 hex colors (one per LED)
- `time.colors`: Time mode colors
- Color format: `"RRGGBB"` or `"START-END-metric"` for gradients
  - Example: `"0000ff-ff0000-cpu_temp"` (blue→red based on CPU temp)
  - Special: `"random"` for random colors
- Temperature ranges: `{device}_min_temp`, `{device}_max_temp`
- Update intervals: `update_interval` (display), `metrics_update_interval` (sensors)
- `layout_mode`: "big" (84 LEDs) or "small" (31 LEDs) hardware

### Number Display Logic

**Temperature (3 digits with padding):**
```python
digit_array = get_number_array(temperature, array_length=3, fill_value=10)  # 10 = blank
# Example: 50 → [10, 5, 0] displays as " 50"
```

**Usage (2 digits + overflow):**
```python
digit_array = get_number_array(usage, array_length=2, fill_value=10)
leds = np.concatenate(([int(usage>=100)]*2, digit_leds))  # 2 LEDs for "1" in "100%"
```

## Common Tasks

### Testing Display Changes
Use test mode to verify digit rendering:
```bash
python3 src/controller.py config.json --test
```
This cycles through 0-9 on all matrices every 2 seconds.

### Debugging USB Issues
If device not found:
```bash
# Run as root temporarily
sudo python3 src/controller.py config.json

# Permanent fix: Create udev rule
sudo nano /etc/udev/rules.d/99-hid-device.rules
# Add: SUBSYSTEM=="usb", ATTRS{idVendor}=="0416", ATTRS{idProduct}=="8001", MODE="0666"
sudo udevadm control --reload-rules
```

### Adding New Display Modes
1. Add mode name to `display_modes` in `src/config.py`
2. Implement display method in `Controller` class (e.g., `display_custom()`)
3. Add conditional in `Controller.display()` main loop
4. Update `config.json` with mode-specific color arrays if needed

### Systemd Service Setup
```bash
# Create service file
sudo nano /etc/systemd/system/digital_lcd_controller.service

# Enable and start
sudo systemctl enable digital_lcd_controller.service
sudo systemctl start digital_lcd_controller.service
```

## Important Notes

- **Never reverse entire GPU LED array** - only reverse segments within each digit
- Temperature values use 3-digit arrays with padding (10 = blank) to ensure correct alignment
- Usage percentages ≥100 use 2 extra LEDs to display the "1" digit
- HID packets must be exactly 512 bytes (prepended with '00', then 4 × 128-byte chunks)
- Metrics system auto-detects working methods on initialization - don't assume specific libraries
- Color interpolation happens in Controller.calculate_colors() based on metric values and ranges
