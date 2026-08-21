# hyperscope

[![CI](https://github.com/momonala/hyperscope/actions/workflows/ci.yml/badge.svg)](https://github.com/momonala/hyperscope/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/momonala/hyperscope/branch/main/graph/badge.svg)](https://codecov.io/gh/momonala/hyperscope)

Camera control and image-processing tools for microscope/telescope photography: a gPhoto2-driven DSLR timelapse capture script, and a flat-field/dark-frame correction CLI for calibrating the resulting raw images.

## Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) for dependency management
- `gphoto2` system library (macOS: `brew install gphoto2`) for camera control
- A gPhoto2-compatible camera (developed against Nikon DSLRs) connected via USB, for the capture script only

## Installation

```bash
git clone https://github.com/momonala/hyperscope.git
cd hyperscope
uv sync
```

## Running

**Timelapse capture** (`src/camera_control.py`) — connects to the camera, configures it for unattended shooting (manual focus, quiet shutter, RAM capture target), and shoots continuously until interrupted:
```bash
uv run python src/camera_control.py
```
Images save to `media/<YYYYMMDD>/` as `<date>_<time>_<shot>.jpg`. `SHOOT_INTERVAL_SECONDS` (in `camera_control.py`) sets the delay between shots. Camera widget names/values (focus mode, capture mode, etc.) are Nikon-specific — verify against your camera with `gphoto2 --get-config /main/capturesettings/<widget>` before relying on `src/camera_settings.py`'s enums.

**Flat-field correction** (`src/flat_field_correction.py`) — corrects raw images using dark-frame subtraction and flat-field normalization:
```bash
uv run python src/flat_field_correction.py \
  --flat calibration/2x/flat_00.JPG \
  --dark calibration/dark.JPG \
  --raw media/20260403/some_shot.jpg \
  --output output/
```
`--flat` and `--raw` accept multiple `-f`/`-r` flags to average several frames or batch-process several raws.

## Project Structure

```
hyperscope/
├── src/
│   ├── camera_control.py         # gPhoto2 timelapse capture loop
│   ├── camera_settings.py        # StrEnums for gPhoto2 config values (Nikon-specific)
│   ├── flat_field_correction.py  # Typer CLI: dark/flat calibration pipeline
│   └── config.py                 # Exposes [tool.config] via `uv run config`
├── calibration/                  # Flat-field and dark-frame reference images
├── media/                        # Captured timelapse frames (gitignored)
├── output/                       # Corrected images from flat_field_correction.py
├── tests/
└── pyproject.toml
```

## Key Concepts

| Concept | Description |
|---------|-------------|
| Flat-field correction | `corrected = (raw - dark) / (flat - dark)`, then normalized to mid-grey (~128) per channel via median — removes vignetting and sensor non-uniformity |
| Edge cropping | Outer 200px of each frame is cropped before correction; sensor corners fall outside the optical circle and produce near-zero flat values that would corrupt the ratio |
| Dark frame | A reference shot with no light exposure, used to subtract fixed-pattern sensor noise |
| Capture target: RAM | Images are captured to the camera's internal RAM, not its memory card, for faster continuous shooting |
