"""Validated motion controls; percent values are converted only by camera math."""

from __future__ import annotations
import json
import math
from .settings_validation import bounded_number

# key, caption, description, default, minimum, maximum
GROUPS = (
    (
        "MOVEMENT",
        (
            (
                "still_gain",
                "Idle Strength (%)",
                "Vertical motion while standing or crouched.",
                16,
                0,
                200,
            ),
            (
                "walk_gain",
                "Walking Strength (%)",
                "Motion above the walking speed threshold.",
                42,
                0,
                200,
            ),
            (
                "fast_gain",
                "Fast Movement Strength (%)",
                "Motion above the fast movement threshold.",
                90,
                0,
                200,
            ),
        ),
    ),
    (
        "ACTIONS",
        (
            (
                "air_gain",
                "Airborne Strength (%)",
                "Motion during jumps and falls.",
                30,
                0,
                200,
            ),
            (
                "landing_gain",
                "Landing Strength (%)",
                "Motion on the first grounded frame.",
                45,
                0,
                200,
            ),
            (
                "crouch_gain",
                "Crouch Transition (%)",
                "Motion while crouching down or rising.",
                40,
                0,
                200,
            ),
        ),
    ),
    (
        "RESPONSE",
        (
            (
                "filter",
                "Motion Response (%)",
                "Higher = faster response; lower = softer motion.",
                20,
                1,
                100,
            ),
            (
                "baseline",
                "Pose Adaptation (%)",
                "Higher = faster return toward your current pose.",
                3.5,
                0.5,
                20,
            ),
            (
                "idle_horizontal",
                "Idle Horizontal (%)",
                "Forward and sideways strength while standing still.",
                6,
                0,
                200,
            ),
        ),
    ),
    (
        "AXIS STRENGTH",
        (
            (
                "axis_x",
                "Forward / Back (%)",
                "Scale forward / backward motion. Zero disables this axis.",
                100,
                0,
                200,
            ),
            (
                "axis_y",
                "Sideways (%)",
                "Scale lateral motion. Zero disables this axis.",
                100,
                0,
                200,
            ),
            (
                "axis_z",
                "Vertical (%)",
                "Scale up and down motion. Zero disables this axis.",
                100,
                0,
                200,
            ),
        ),
    ),
    (
        "MOVEMENT LIMITS",
        (
            (
                "limit_x",
                "Forward / Back Limit",
                "Maximum added offset on the forward axis (game units).",
                6,
                0,
                20,
            ),
            (
                "limit_y",
                "Sideways Limit",
                "Maximum added sideways offset (game units).",
                6,
                0,
                20,
            ),
            (
                "limit_z",
                "Vertical Limit",
                "Maximum added vertical offset (game units).",
                6,
                0,
                20,
            ),
        ),
    ),
    (
        "SPEED DETECTION",
        (
            (
                "walk_speed",
                "Walking Threshold",
                "Minimum speed for walking motion (game units / second).",
                25,
                1,
                300,
            ),
            (
                "fast_speed",
                "Fast Movement Threshold",
                "Minimum speed for fast motion (game units / second).",
                650,
                301,
                1200,
            ),
            (
                "unknown_gain",
                "Unknown Speed Strength (%)",
                "Fallback when the game cannot report movement speed.",
                16,
                0,
                200,
            ),
        ),
    ),
)
SPECS = tuple(spec for _, group in GROUPS for spec in group)
DEFAULTS = {key: default for key, _, _, default, _, _ in SPECS}


def sanitize(values):
    """Return known bounded motion parameters; reject unsupported/nonfinite values."""
    result = dict(DEFAULTS)
    if not isinstance(values, dict):
        return result
    for key, _, _, default, lo, hi in SPECS:
        step = 0.5 if key == "baseline" else 1
        result[key] = bounded_number(values.get(key, default), default, lo, hi, step)
    return result


def read_parameters(path):
    """Load validated parameters only from a file with a strict boolean enabled field."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
            return dict(DEFAULTS)
        return sanitize(data.get("parameters"))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


class MotionOption:
    def __init__(self, parameters, key):
        self.parameters, self.key = parameters, key

    @property
    def value(self):
        return self.parameters[self.key]

    @value.setter
    def value(self, value):
        self.parameters[self.key] = sanitize({self.key: value})[self.key]
