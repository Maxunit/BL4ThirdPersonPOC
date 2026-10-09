"""Pure numeric validation for file-backed settings and engine-bound offsets."""

import math


def bounded_number(raw, default, lo, hi, step=None):
    """Clamp a finite numeric value and optionally round half away from zero.

    Reject booleans and other types. Compare large integers before float
    conversion so malformed file values do not overflow during validation.
    """
    if type(raw) not in (int, float):
        return default
    # Compare arbitrary-size integers before converting them to float.
    if type(raw) is float and not math.isfinite(raw):
        return default
    if raw <= lo:
        return lo
    if raw >= hi:
        return hi
    value = float(raw)
    if step is not None:
        value = math.copysign(math.floor(abs(value) / step + 0.5), value) * step
    return max(lo, min(hi, value))


POSITION_DEFAULTS = (0, 75, 10)
POSITION_RANGES = ((-75, 75), (-150, 150), (-65, 85))


def position_values(options, *, ads=False):
    return tuple(
        bounded_number(option.value, default, 0 if ads and i == 1 else lo, hi)
        for i, (option, default, (lo, hi)) in enumerate(
            zip(options, POSITION_DEFAULTS, POSITION_RANGES)
        )
    )


def sanitize_positions(owner):
    """Sanitize saved offsets and strict boolean feature flags before engine use."""
    options = tuple(getattr(owner, "camera_offset_" + axis) for axis in "xyz")
    for option, value in zip(options, position_values(options)):
        option.value = value
    # Older option-free test fixtures and old configs keep their character defaults.
    for axis, (lo, hi) in zip('xyz', ((-350,350),(-200,200),(-200,200))):
        option = getattr(owner, 'vehicle_offset_'+axis, None)
        if option is not None:
            option.value = bounded_number(option.value, 0, lo, hi)
    if type(owner.tps_ffyl_beta.value) is not bool:
        owner.tps_ffyl_beta.value = False
    if type(owner.sniper_tps_ads.value) is not bool:
        owner.sniper_tps_ads.value = False
    hybrid = getattr(owner, "omni_hybrid_ads", None)
    if hybrid is not None and type(hybrid.value) is not bool:
        hybrid.value = False
    if type(owner.dynamic_motion_camera_enabled.value) is not bool:
        owner.dynamic_motion_camera_enabled.value = False
