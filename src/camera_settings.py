"""Enums for gPhoto2 camera configuration values.

Widget names and valid choices vary by camera model. These enums reflect
common Nikon DSLR values — verify against your camera with:
    gphoto2 --get-config /main/capturesettings/<widget>
"""

from enum import StrEnum


class FocusMode(StrEnum):
    MANUAL = "Manual"
    AF_SINGLE = "AF-S"
    AF_CONTINUOUS = "AF-C"
    AF_AUTO = "AF-A"


class CaptureMode(StrEnum):
    SINGLE = "Single"
    QUIET = "Quiet"
    CONTINUOUS_LOW = "Continuous low speed"
    CONTINUOUS_HIGH = "Continuous high speed"
    SELF_TIMER_2S = "Self-timer 2s"
    SELF_TIMER_10S = "Self-timer 10s"


class CaptureTarget(StrEnum):
    RAM = "Internal RAM"
    MEMORY_CARD = "Memory card"
