"""Shared names and finite SDK value conversions; no physical input defaults."""
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path
from unrealsdk import logging as _sdk_logging
from . import settings as _settings

REPORT_DIRECTORY_NAME = 'BL4ThirdPersonPOC_reports'
REPORT_PREFIX = 'player_omnidirectional_'
MAX_REPORT_FILES = 40


class _FeatureLog:
    """State messages are console warnings only while diagnostics are enabled.

    Production routes them to developer logging so normal play does not print
    every phase change. Errors always use the normal error channel.
    """

    @staticmethod
    def warning(message):
        if _settings.diagnostics_enabled():
            _sdk_logging.warning(message)
            return
        developer = getattr(_sdk_logging, 'dev_warning', None)
        if developer is not None:
            developer(message)

    @staticmethod
    def info(message):
        _sdk_logging.info(message)

    @staticmethod
    def error(message):
        _sdk_logging.error(message)


log = _FeatureLog()


def report_path(mod, stem):
    """Return a writable report path below SETTINGS_DIR, never inside a .sdkmod.

    A .sdkmod is a zip on sys.path, so paths relative to __file__ are not
    writable there. Returns None when the loader exposes no settings directory.
    """
    settings_dir = getattr(mod, 'SETTINGS_DIR', None)
    if settings_dir is None:
        return None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    return Path(settings_dir) / REPORT_DIRECTORY_NAME / (stem + '_' + stamp + '.json')


def write_report(path, report):
    """Write one bounded JSON report and keep only the newest feature reports."""
    if path is None:
        raise RuntimeError('No writable report directory')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    try:
        reports = sorted(path.parent.glob(REPORT_PREFIX + '*.json'), key=lambda p: p.stat().st_mtime)
        for old in reports[:-MAX_REPORT_FILES]:
            if old != path:
                old.unlink()
    except OSError:
        pass
    return path


def movement_input_state(vector):
    strength = math.hypot(vector['X'], vector['Y'])
    if not math.isfinite(strength):
        raise RuntimeError('Nonfinite native movement input')
    return dict(movement_input_active=strength > 0.2, movement_input_strength=min(1.0, strength), movement_input_source='native_movement' if strength > 0.2 else 'none')
KEY = '_player_omnidirectional_gameplay'
TAG = '[OmnidirectionalGameplay]'
MAX_SAMPLES = 512
FRAME_STRIDE = 1

def parts(value, names):
    result = {name: float(getattr(value, name)) for name in names}
    if not all((math.isfinite(v) for v in result.values())):
        raise RuntimeError('Nonfinite SDK value')
    return result

def angle(a, b):
    return (a - b + 180.0) % 360.0 - 180.0

def direction(v):
    return math.degrees(math.atan2(v['Y'], v['X'])) if math.hypot(v['X'], v['Y']) > 0.01 else None

def describe(obj):
    return {'path': str(obj._path_name()), 'class': str(obj.Class._path_name())}

def quat(raw):
    values = struct.unpack('<4d', raw)
    norm = sum((v * v for v in values))
    if not all((math.isfinite(v) for v in values)) or abs(norm - 1) > 0.02:
        return {'bytes': raw.hex(), 'status': 'INVALID_UNIT_QUAT_RAW_ONLY'}
    x, y, z, w = values
    return {'xyzw': list(values), 'yaw': math.degrees(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))}

def reflected_fields(typ):
    result = {}
    for owner in (typ, *tuple(typ._superfields())):
        for prop in owner._properties():
            result.setdefault(str(prop.Name), prop)
    return result
