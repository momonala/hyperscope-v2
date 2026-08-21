"""Camera control utilities for gPhoto2-based timelapse capture."""

import logging
import subprocess
import sys
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path

import gphoto2 as gp
from rich.logging import RichHandler

from camera_settings import CaptureMode
from camera_settings import CaptureTarget
from camera_settings import FocusMode

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger(__name__)


SHOOT_INTERVAL_SECONDS = 0.1
MEDIA_DIR = Path(__file__).parent.parent / "media"


def kill_macos_camera_drivers() -> None:
    """Kill macOS PTP camera drivers to release exclusive camera access."""
    for process in ("PTPCamera", "imagecaptured"):
        result = subprocess.run(["pkill", "-f", process], capture_output=True)
        if result.returncode == 0:
            logger.info("Killed process: %s", process)
    time.sleep(1)


def initialize_camera() -> gp.Camera:
    """Initialize and return a connected gPhoto2 camera."""
    camera = gp.Camera()
    try:
        camera.init()
    except gp.GPhoto2Error as exc:
        if exc.code == -105:
            logger.error("Camera not found. Check physical connection.")
            sys.exit(1)
        raise exc
    logger.info("Camera connected")
    return camera


def configure_camera(camera: gp.Camera) -> None:
    """Configure camera for timelapse: manual focus, quiet shutter, RAM capture target."""
    config = camera.get_config()
    config.get_child_by_name("focusmode").set_value(FocusMode.MANUAL)
    config.get_child_by_name("autofocusdrive").set_value(0)
    config.get_child_by_name("capturemode").set_value(CaptureMode.QUIET)
    config.get_child_by_name("capturetarget").set_value(CaptureTarget.RAM)
    camera.set_config(config)
    time.sleep(1)  # allow camera to apply config before first capture

    configured = {
        name: config.get_child_by_name(name).get_value()
        for name in ("focusmode", "autofocusdrive", "capturemode", "capturetarget")
    }
    logger.info("Camera configured: %s", configured)


def capture_and_save_image(camera: gp.Camera, save_dir: Path, shot_number: int) -> Path:
    """Capture a single image and save it to disk.

    Args:
        camera: Initialized gPhoto2 camera.
        save_dir: Directory to write the image file.
        shot_number: Sequential counter embedded in the filename.

    Returns:
        Path to the saved image file.

    Raises:
        gp.GPhoto2Error: On capture or file transfer failure.
    """
    file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
    camera_file = camera.file_get(file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL)

    now = datetime.now(timezone.utc).astimezone()
    filename = save_dir / f"{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}_{shot_number:04d}.jpg"
    camera_file.save(str(filename))

    logger.info("[shot %d] Saved: %s", shot_number, filename)
    return filename


def _wait_for_camera_idle(camera: gp.Camera, timeout_ms: int = 1000) -> None:
    """Drain camera events until idle, so the next capture doesn't race internal processing."""
    while True:
        event_type, _ = camera.wait_for_event(timeout_ms)
        if event_type == gp.GP_EVENT_TIMEOUT:
            break


def run_timelapse(interval_seconds: int = SHOOT_INTERVAL_SECONDS, save_dir: Path | None = None) -> None:
    """Run a continuous timelapse, capturing images at a fixed interval until interrupted.

    Args:
        interval_seconds: Delay between shots in seconds.
        save_dir: Directory to save images. Defaults to MEDIA_DIR/<date>.
    """
    if save_dir is None:
        date_str = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d")
        save_dir = MEDIA_DIR / date_str
    save_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Saving to: %s", save_dir)
    logger.info("Shooting every %ds — Ctrl+C to stop", interval_seconds)

    kill_macos_camera_drivers()
    camera = initialize_camera()
    configure_camera(camera)

    shot = 1
    try:
        while True:
            try:
                capture_and_save_image(camera, save_dir, shot)
                shot += 1
                _wait_for_camera_idle(camera)
            except gp.GPhoto2Error as exc:
                logger.warning("Capture error (%d): %s — retrying...", exc.code, exc)
                time.sleep(3)
                continue
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Stopped. %d images saved to %s", shot - 1, save_dir)
    finally:
        camera.exit()


if __name__ == "__main__":
    run_timelapse()
