"""Flat-field and dark-frame correction pipeline for microscopy images."""

import logging
from pathlib import Path

import cv2
import numpy as np
import typer

logger = logging.getLogger(__name__)

FLAT_BLUR_KERNEL = 51
EPS = 1e-6
EDGE_CROP_PX = 200

app = typer.Typer(help="Flat-field correction for microscopy images.")


def load_image(path: Path) -> np.ndarray:
    """Load an image as float32, raising if the file cannot be read."""
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    return img.astype(np.float32)


def crop_sensor_edges(image: np.ndarray, px: int = EDGE_CROP_PX) -> np.ndarray:
    """Remove the outer border that falls outside the optical circle.

    Sensor corners receive little to no light, producing near-zero flat-field
    values that corrupt the correction ratio.

    Args:
        image: Input image (HxWxC or HxW).
        px: Number of pixels to remove from each edge.

    Returns:
        Cropped image with shape (H-2*px, W-2*px, ...).
    """
    return image[px:-px, px:-px]


def build_flat_field(flat_paths: list[Path]) -> np.ndarray:
    """Average multiple flat-field frames and apply Gaussian smoothing.

    Args:
        flat_paths: One or more paths to flat-field images.

    Returns:
        Smoothed, averaged flat-field as float32.
    """
    frames = [load_image(p) for p in flat_paths]
    averaged = np.mean(frames, axis=0).astype(np.float32)
    return cv2.GaussianBlur(averaged, (FLAT_BLUR_KERNEL, FLAT_BLUR_KERNEL), 0)


def correct(raw: np.ndarray, flat: np.ndarray, dark: np.ndarray) -> np.ndarray:
    """Apply dark-frame subtraction and flat-field correction.

    Implements: corrected = (raw - dark) / (flat - dark), then normalises
    to mid-grey via per-channel median.

    Assumes all inputs have already been cropped via crop_sensor_edges.

    Args:
        raw: Raw image (float32, HxWxC).
        flat: Smoothed flat-field (float32, HxWxC).
        dark: Dark frame (float32, HxWxC).

    Returns:
        Corrected image as float32 at mid-grey scale (~128).
    """
    raw_corrected = np.maximum(raw - dark, 0.0)
    flat_corrected = np.maximum(flat - dark, EPS)

    ratio = raw_corrected / flat_corrected
    channel_median = np.median(ratio, axis=(0, 1), keepdims=True) + EPS
    return ratio / channel_median * 128.0


def stretch_contrast(image: np.ndarray) -> np.ndarray:
    """Stretch per-channel contrast to [0, 255] by clipping the 2nd–98th percentile."""
    lo, hi = np.percentile(image, [2, 98], axis=(0, 1))
    stretched = (image - lo) / (hi - lo + EPS) * 255.0
    return np.clip(stretched, 0, 255).astype(np.uint8)


@app.command()
def run(
    flat_field: list[Path] = typer.Option(
        ...,
        "--flat",
        "-f",
        help="Path to flat-field image(s). Pass multiple times to average frames.",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    dark_frame: Path = typer.Option(
        ...,
        "--dark",
        "-d",
        help="Path to the dark-frame image.",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    raw_images: list[Path] = typer.Option(
        ...,
        "--raw",
        "-r",
        help="Path to raw image(s) to correct. Pass multiple times.",
        exists=True,
        file_okay=True,
        dir_okay=False,
    ),
    output_dir: Path = typer.Option(
        Path("data/output"),
        "--output",
        "-o",
        help="Directory to write corrected images.",
    ),
) -> None:
    """Correct raw microscopy images using flat-field and dark-frame calibration."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading dark frame: %s", dark_frame)
    dark = crop_sensor_edges(load_image(dark_frame))

    logger.info("Building flat field from %d frame(s)", len(flat_field))
    flat = crop_sensor_edges(build_flat_field(flat_field))

    for raw_path in raw_images:
        logger.info("Correcting %s", raw_path)
        raw = crop_sensor_edges(load_image(raw_path))
        corrected = correct(raw, flat, dark)
        result = stretch_contrast(corrected)

        out_path = output_dir / f"{raw_path.stem}_corrected{raw_path.suffix}"
        cv2.imwrite(str(out_path), result)
        logger.info("Saved %s", out_path)

    logger.info("Done. %d image(s) written to %s", len(raw_images), output_dir)


if __name__ == "__main__":
    app()
