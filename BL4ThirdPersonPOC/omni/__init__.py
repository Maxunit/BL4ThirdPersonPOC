"""Integrated omnidirectional movement (experimental feature, default off).

The loader owns the option, menu row, console command and shutdown stage; this
package owns the lifecycle supervisor and its gameplay sessions. The owner
module is injected explicitly - nothing here looks the loader up by name.

Contract with the loader (``owner``): ``_get_runtime``, ``_kernel32``, the
native read/write/restore/release helpers, ``FIRST_PERSON_ANIM_HOOK``,
``CLIENT_RESTART_FUNCTION``, ``SETTINGS_DIR`` and the camera/state flags
(``_third_person_enabled``, ``_third_person_pushed``, ``_vehicle_camera_active``,
``_shop_camera_active``, ``_ladder_active``, ``_slide_active``, ``_ads_active``).
The shared game-thread producer is ``BL4ThirdPersonPOC.runtime_updates``.
"""
from .common import KEY, TAG, log
from . import settings

# Set by start() after a failed arm or a fail-closed stop, cleared by shutdown().
_last_failure = {'reason': None}


def _updates():
    from .. import runtime_updates
    return runtime_updates


def is_running(owner):
    state = getattr(owner, KEY, None)
    return state is not None and state.active


def record_failure(where: str, exc: Exception) -> None:
    _last_failure['reason'] = where + ': ' + repr(exc)[:300]


def last_failure():
    return _last_failure['reason']


def start(owner):
    """Arm the lifecycle supervisor. Returns True when running afterwards."""
    if is_running(owner):
        return True
    if getattr(owner, KEY, None) is not None:
        log.error(TAG + ' FAILED cleanup pending; run bl4tps_omni off first')
        return False
    # Reject any simultaneously active lab probe state from older builds.
    for name, value in vars(owner).copy().items():
        if (name.startswith('_player_') and name != KEY and value is not None
                and hasattr(value, 'finish') and hasattr(value, 'report')):
            log.error(TAG + ' FAILED stop previous probe first: ' + name)
            _last_failure['reason'] = 'previous probe active: ' + name
            return False
    from .. import build_gate
    gate = build_gate.status(owner)
    if not gate['reviewed']:
        log.error(TAG + ' FAILED unreviewed game build; feature stays off. ' + build_gate.summary(gate))
        _last_failure['reason'] = 'unreviewed game build'
        return False
    updates = _updates()
    owner_state = getattr(updates, '_owner', None)
    if owner_state is None or not getattr(owner_state, 'active', False):
        log.error(TAG + ' FAILED existing runtime_updates producer required')
        _last_failure['reason'] = 'runtime updates not started'
        return False
    from .lifecycle import LifecycleSupervisor
    state = LifecycleSupervisor(owner, updates)
    setattr(owner, KEY, state)
    try:
        state.install()
    except Exception as exc:
        _last_failure['reason'] = 'arm: ' + repr(exc)[:200]
        state.fail('arm', exc)
        return is_running(owner) and state.active
    _last_failure['reason'] = None
    log.info(TAG + ' ARMED diagnostics=' + str(settings.diagnostics_enabled())
             + '; waits for normal on-foot TPS; current game mappings; native charges retained')
    return True


def shutdown(owner, reason='FEATURE_DISABLED'):
    """Stop and restore. Returns True only when no feature state remains."""
    state = getattr(owner, KEY, None)
    if state is None:
        _last_failure['reason'] = None
        return True
    try:
        state.finish(reason)
    except Exception as exc:
        log.error(TAG + ' STOP_FAILED state retained; retry with bl4tps_omni off: ' + repr(exc)[:300])
        previous = _last_failure['reason']
        _last_failure['reason'] = (previous + '; ' if previous else '') + 'cleanup incomplete'
        return False
    if getattr(owner, KEY, None) is not None:
        return False
    _last_failure['reason'] = None
    return True


def stopped_after_failure(owner):
    """True when the supervisor removed itself fail-closed while the option stayed on."""
    state = getattr(owner, KEY, None)
    if state is not None:
        return not state.active
    return _last_failure['reason'] is not None


def status(owner):
    state = getattr(owner, KEY, None)
    if state is None:
        return dict(running=False, cleanup_pending=False, diagnostics=settings.diagnostics_enabled(),
                    last_failure=_last_failure['reason'])
    child = state.child
    return dict(running=state.active, cleanup_pending=not state.active, diagnostics=state.diagnostics, phase=state.phase,
                sessions=state.sequence, rebinds=state.report.get('rebind_count', 0),
                errors=len(state.report.get('errors', [])),
                gameplay_bound=child is not None,
                native_patches=0 if child is None else child.report.get('native_patches', 0),
                last_failure=_last_failure['reason'])


def save_report(owner, reason='MANUAL_REPORT'):
    state = getattr(owner, KEY, None)
    if state is None:
        raise RuntimeError('Feature is not running')
    return state.save_report(reason)


def restart(owner, reason='SETTINGS_CHANGED'):
    """Stop and arm again, e.g. after the diagnostics switch changed."""
    if not shutdown(owner, reason):
        return False
    return start(owner)


