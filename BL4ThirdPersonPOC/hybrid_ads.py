"""Hybrid ADS Mode for omnidirectional movement.

Option ``omni_hybrid_ads`` (default off), active only while omni movement runs.

Hold ADS
    Every weapon category takes the TPS ADS route, sniper rifles included.
    Omni already pauses for ADS (combat signal): the body faces the view and
    side input strafes. The camera moves closer (offset +X, "dolly") in step
    with the ADS FOV progress, and the TPS zoom is capped to a mild
    magnification; precision is the scope's job.
Sprint while ADS is held
    Toggles the weapon's native first-person scope (FPS ADS route) and back.
    BL4 ignores Sprint while zoomed, so the configured Sprint key is only
    observed (by omni), never blocked.
Releasing ADS
    Always returns to omni third person, also from the scope.

Camera offset and FOV offset fade along the native camera-mode blend. That is
animation easing on the existing camera update, not a timer that synchronises
state: every state change is triggered by an input or an observed camera mode.
"""
from __future__ import annotations

from time import monotonic
from weakref import ref as weakref
import math
from typing import Any, Optional

from unrealsdk.unreal import WeakPointer

TAG = '[BL4ThirdPersonPOC] '
FPS_ROUTES = ('sniper_fps', 'fallback_fps')
SCOPE_BLEND_SECONDS = 0.2
DEFAULT_DOLLY = 35.0          # cm toward the character (camera_offset_x: + is closer)
MAX_DOLLY = 100.0
MAX_OFFSET_X = 110.0          # never move the camera into the character
DEFAULT_MAX_MAGNIFICATION = 1.35
MIN_FOV_DELTA = 0.5           # degrees; below this the dolly follows transition progress
# Failures a scope switch can raise from SDK calls or missing runtime objects.
SWITCH_ERRORS = (AttributeError, RuntimeError, TypeError, ValueError)

_state: dict[str, Any] = {}


def reset(mod: Any = None) -> None:
    """Forget scope/fade state (mod disable, tests). Tuning values persist.

    With ``mod`` a running FOV fade first writes its native end value.
    """
    if mod is not None and _state.get('fov_fade') is not None:
        finish_fov_fade(mod)
    if mod is not None:
        cancel_return_fov(mod)
    dolly = _state.get('dolly', DEFAULT_DOLLY)
    magnification = _state.get('max_magnification', DEFAULT_MAX_MAGNIFICATION)
    _state.clear()
    _state.update(scoped=False, scope_weapon=0, fade=None, fov_fade=None, omni_handoff=None,
                  tps_hold=None,
                  return_fov=None,
                  dolly=dolly, max_magnification=magnification,
                  scope_enters=0, scope_exits=0, scope_releases=0, scope_lost=0,
                  refusals={}, last_event=None, last_error=None)


reset()


# -- gates -------------------------------------------------------------------------
def option_enabled(mod: Any) -> bool:
    option = getattr(mod, 'omni_hybrid_ads', None)
    return option is not None and option.value is True


def gameplay_bound(mod: Any) -> bool:
    """The omni gameplay session (which reads the Sprint key) is bound."""
    from .omni.common import KEY
    supervisor = getattr(mod, KEY, None)
    return getattr(supervisor, 'child', None) is not None


def _gameplay_session(mod: Any) -> Any:
    from .omni.common import KEY
    return getattr(getattr(mod, KEY, None), 'child', None)


def request_scope(mod: Any, session: Any) -> str:
    """Queue one input edge for the camera stage, bound to its current owners."""
    if not active(mod) or _gameplay_session(mod) is not session or not session.active:
        return 'inactive'
    pc, pawn, camera = mod._get_runtime()
    if any(obj is None for obj in (pc, pawn, camera)):
        return 'refused:no_runtime'
    if bool(pc.bShowMouseCursor):
        return 'refused:ui'
    weapon = camera.CameraModeInputs.Weapon
    if weapon is None:
        return 'refused:no_weapon'
    if getattr(session, 'hybrid_scope_request', None) is not None:
        return 'already_queued'
    session.hybrid_scope_request = dict(
        owners=tuple(WeakPointer(obj) for obj in (pc, pawn, camera, weapon)),
        route=mod._ads_route)
    return 'queued'


def _consume_scope_request(mod: Any) -> None:
    session = _gameplay_session(mod)
    request = getattr(session, 'hybrid_scope_request', None)
    if request is None:
        return
    # Consume before any SDK operation. A refusal or failure must not replay
    # this key press in a later camera frame.
    session.hybrid_scope_request = None
    result = 'refused:request_context_changed'
    if session.active and active(mod) and mod._ads_active:
        pc, pawn, camera = mod._get_runtime()
        live = (pc, pawn, camera, None if camera is None else camera.CameraModeInputs.Weapon)
        expected = tuple(owner() for owner in request['owners'])
        same = all(a is not None and b is not None and a == b for a, b in zip(expected, live))
        if (same and not bool(pc.bShowMouseCursor)
                and request['route'] == mod._ads_route and mod._ads_handoff.get('held')):
            result = toggle_scope(mod)
    session.report['hybrid_scope_last'] = result


def _pause_omni_before_scope(mod: Any, pc: Any, pawn: Any, camera: Any) -> None:
    """Release behavioral controls before the SDK can expose the FPS camera."""
    session = _gameplay_session(mod)
    if session is None or not session.active:
        return
    if session.bound()[:3] != (pc, pawn, camera):
        raise RuntimeError('Hybrid scope gameplay owner changed')
    session.enter_special()
    _state['omni_handoff'] = dict(session=weakref(session),
                                owners=tuple(WeakPointer(o) for o in (pc, pawn, camera)))


def omni_pause_required(session: Any) -> bool:
    """Keep this exact session paused through scope and observed TPS return.

    The completion condition is camera state, never an elapsed deadline. If a
    return call is ignored, the native view keeps ownership safely.
    """
    handoff = _state['omni_handoff']
    if handoff is None or handoff['session']() is not session:
        return False
    pc, pawn, camera, _movement = session.bound()
    expected = tuple(owner() for owner in handoff['owners'])
    if any(a is None or a != b for a, b in zip(expected, (pc, pawn, camera))):
        raise RuntimeError('Hybrid scope handoff owner changed')
    mode = str(camera.GetActorCameraMode(pawn))
    if mode not in ('ThirdPerson', 'Default'):
        _state['omni_handoff'] = None
        return False  # Existing special-state handling owns FFYL/ladder/etc.
    fps_ads = bool(session.mod._ads_active) and session.mod._ads_route in FPS_ROUTES
    if (mode == 'Default' or _state['scoped'] or fps_ads
            or bool(camera.CameraModeState.bIsTransitioning)):
        return True
    _state['omni_handoff'] = None
    return False


def active(mod: Any) -> bool:
    """Hybrid rules apply: option on, omni running and its gameplay session bound.

    Without the bound session the Sprint toggle could not work, so ADS keeps
    the normal routes (e.g. right after a vehicle exit, before omni re-arms).
    """
    if not option_enabled(mod):
        return False
    try:
        from . import omni
        return bool(omni.is_running(mod)) and gameplay_bound(mod)
    except (ImportError, AttributeError, RuntimeError):
        return False


def sniper_uses_tps(mod: Any) -> bool:
    """Route decision shared by every sniper check of the hybrid ADS code."""
    return mod.sniper_tps_ads.value is True or active(mod)


def cap_target_fov(mod: Any, base_fov: float, target_fov: float) -> float:
    """Mild TPS zoom while holding ADS in hybrid mode (FOV larger = less zoom)."""
    if not active(mod):
        return target_fov
    magnification = max(1.0, float(_state['max_magnification']))
    return max(float(target_fov), float(base_fov) / magnification)


def _capture_tps_hold(pc: Any, pawn: Any, camera: Any, weapon: Any, ads: dict) -> dict:
    """Keep scalar TPS calibration, never its borrowed CameraModeState struct."""
    values = {name: float(ads[name]) for name in ('base_fov', 'target_fov', 'original_offset')}
    if not all(math.isfinite(value) for value in values.values()):
        raise RuntimeError('Hybrid TPS hold calibration is nonfinite')
    return dict(values, owners=tuple(WeakPointer(o) for o in (pc, pawn, camera, weapon)),
                category=str(ads.get('category') or ''))


def valid_tps_resume(mod: Any, camera: Any, weapon: Any, resume: Any) -> bool:
    if not isinstance(resume, dict) or not _fade_context_ok(mod):
        return False
    pc, pawn, live_camera = mod._get_runtime()
    expected = tuple(owner() for owner in resume['owners'])
    live = (pc, pawn, live_camera, weapon)
    return (camera == live_camera and len(expected) == len(live)
            and all(a is not None and b is not None and a == b for a, b in zip(expected, live)))


def _return_resume(mod: Any, camera: Any) -> Optional[dict]:
    pending = mod._ads_handoff.get('route_pending')
    if not isinstance(pending, dict) or not pending.get('hybrid_same_weapon'):
        return None
    resume = pending.get('hybrid_tps_resume')
    weapon = camera.CameraModeInputs.Weapon
    if (not mod._ads_active or not mod._ads_handoff.get('held')
            or not valid_tps_resume(mod, camera, weapon, resume)):
        return None
    return resume


def _record_fov(mod: Any, camera: Any, event: str) -> None:
    """Small bounded evidence around scope handoffs; diagnostics never gate play."""
    session = _gameplay_session(mod)
    if session is None:
        return
    try:
        _pc, pawn, live = mod._get_runtime()
        if camera != live or pawn is None:
            return
        ads = getattr(mod, '_ads_tps_state', None) or {}
        row = dict(event=event, t=monotonic() - session.started,
                   update_index=session.frames, route=mod._ads_route,
                   mode=str(camera.GetActorCameraMode(pawn)),
                   transitioning=bool(camera.CameraModeState.bIsTransitioning),
                   fov_offset=float(camera.CameraModeState.BaseFOVOffset),
                   base_fov=ads.get('base_fov'), target_fov=ads.get('target_fov'),
                   ads_transition=(ads.get('transition') or {}).get('kind'))
        # This is the SDK POV field used by the existing TPS FOV reader.
        row['camera_fov'] = float(camera.CameraCachePrivate.POV.FOV)
        if not math.isfinite(row['camera_fov']) or not math.isfinite(row['fov_offset']):
            raise ValueError('Nonfinite handoff FOV evidence')
        rows = session.report.setdefault('hybrid_fov_events', [])
        rows.append(row)
        del rows[:-256]
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        session.report['hybrid_fov_read_failures'] = session.report.get('hybrid_fov_read_failures', 0) + 1
        session.report['hybrid_fov_last_error'] = type(exc).__name__ + ': ' + str(exc)[:160]


def cancel_return_fov(mod: Any, *, restore: bool = True) -> None:
    """Restore only this still-owned TPS offset; never write another manager."""
    overlay = _state.get('return_fov')
    _state['return_fov'] = None
    if overlay is None or not restore:
        return
    _pc, pawn, camera = mod._get_runtime()
    expected = tuple(owner() for owner in overlay['resume']['owners'][:3])
    if (any(a is None or a != b for a, b in zip(expected, (_pc, pawn, camera)))
            or camera is None or pawn is None
            or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson'):
        return
    # A completed TPS start owns this offset now and its normal cancel/release
    # path restores it. Avoid competing with that new owner.
    ads = getattr(mod, '_ads_tps_state', None)
    if isinstance(ads, dict) and mod._ads_route == 'tps':
        return
    state = camera.CameraModeState
    if abs(float(state.BaseFOVOffset) - overlay['requested']) <= .001:
        state.BaseFOVOffset = overlay['resume']['original_offset']
        _record_fov(mod, camera, 'RETURN_CANCELLED')


def complete_tps_resume(mod: Any, camera: Any) -> None:
    _state['return_fov'] = None
    _state['tps_hold'] = None
    _record_fov(mod, camera, 'TPS_HOLD_RESUMED')


def prepare_return_fov(mod: Any) -> None:
    """Set the observed TPS destination to held aim while its native view blends.

    The outgoing rendered FOV remains owned by the camera's existing blend.
    An ignored mode switch must never receive this TPS offset in FPS mode.
    """
    pending = mod._ads_handoff.get('route_pending')
    if not isinstance(pending, dict) or pending.get('hybrid_tps_resume') is None:
        cancel_return_fov(mod)
        return
    _pc, pawn, camera = mod._get_runtime()
    if pawn is None or camera is None or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
        cancel_return_fov(mod)
        return
    resume = _return_resume(mod, camera)
    if resume is None:
        cancel_return_fov(mod)
        return
    finish_fov_fade(mod)
    requested = resume['original_offset'] + resume['target_fov'] - resume['base_fov']
    _state['return_fov'] = dict(resume=resume, requested=requested)
    camera.CameraModeState.BaseFOVOffset = requested
    if abs(float(camera.CameraModeState.BaseFOVOffset) - requested) > .001:
        raise RuntimeError('Hybrid return FOV offset readback differs')
    _record_fov(mod, camera, 'RETURN_TARGET')


# -- camera offset -----------------------------------------------------------------
def _smoothstep(alpha: float) -> float:
    alpha = min(1.0, max(0.0, alpha))
    return alpha * alpha * (3.0 - 2.0 * alpha)


def dolly_blend(mod: Any) -> float:
    """0..1 share of the dolly: follows the TPS ADS FOV between base and target."""
    state = getattr(mod, '_ads_tps_state', None)
    if not isinstance(state, dict):
        return 0.0
    base, target = float(state['base_fov']), float(state['target_fov'])
    if base - target >= MIN_FOV_DELTA:
        current = float(state.get('last_fov', base))
        return min(1.0, max(0.0, (base - current) / (base - target)))
    transition = state.get('transition')
    if not isinstance(transition, dict):
        return 1.0 if state.get('phase') == 'ads' else 0.0
    duration = max(float(getattr(mod, 'ADS_MIN_DURATION', 0.05)), float(transition['duration']))
    eased = _smoothstep((mod.time.perf_counter() - float(transition['started'])) / duration)
    kind = str(transition.get('kind', ''))
    if kind.startswith('zoom_in'):
        return eased
    if kind == 'zoom_out':
        return 1.0 - eased
    return 1.0


def _fade_context_ok(mod: Any) -> bool:
    lifecycle = getattr(mod, '_camera_lifecycle', {}) or {}
    return bool(mod._third_person_enabled and mod._third_person_pushed
                and not mod._vehicle_camera_active and not mod._shop_camera_active
                and not mod._ladder_active
                and not lifecycle.get('suppress_offsets', False)
                and lifecycle.get('phase') != 'repairing')


def _progress(fade: dict, now: float) -> tuple[float, float]:
    alpha = (now - fade['started']) / max(1e-3, fade['duration'])
    return alpha, _smoothstep(alpha)


def _with_dolly(mod: Any, x: float, y: float, z: float) -> tuple[float, float, float]:
    if (x, y, z) == (0.0, 0.0, 0.0) or not active(mod):
        return x, y, z
    if not (getattr(mod, '_ads_route', None) == 'tps' and isinstance(getattr(mod, '_ads_tps_state', None), dict)):
        return x, y, z
    shifted = x + float(_state['dolly']) * dolly_blend(mod)
    return max(x, min(shifted, MAX_OFFSET_X)), y, z


def _camera_transitioning(mod: Any) -> bool:
    try:
        _pc, _pawn, camera = mod._get_runtime()
        return camera is not None and bool(camera.CameraModeState.bIsTransitioning)
    except (AttributeError, RuntimeError):
        return False


def compensate(mod: Any, x: float, y: float, z: float) -> tuple[float, float, float]:
    """Applied inside _set_camera_offset: hold dolly and scope fades.

    A fade blends from the offset that was live when it started toward the
    live offset of each frame. "out" (into the scope) ends at the blend end.
    "in" (back to third person) targets held shoulder aim, or hip on release,
    while callers still write zero for first-person reasons. It ends once the observed state
    lets the third-person offset through (route left FPS, blend settled).
    """
    live = _with_dolly(mod, x, y, z)
    fade = _state['fade']
    if fade is None:
        return live
    if not _fade_context_ok(mod):
        _state['fade'] = None
        return live
    alpha, eased = _progress(fade, monotonic())
    zero = live == (0.0, 0.0, 0.0)
    if fade['kind'] == 'out':
        target = live
        if alpha >= 1.0:
            _state['fade'] = None
            return live
    else:
        target = _hip_offset(mod) if zero else live
        if zero:
            _pc, pawn, camera = mod._get_runtime()
            # A held return ends at shoulder aim, including its dolly. Keep
            # unknown/ignored FPS mode at the caller's zero offset.
            if camera is not None and pawn is not None:
                mode = str(camera.GetActorCameraMode(pawn))
                if mode != 'ThirdPerson':
                    _state['fade'] = None
                    return live
                if _return_resume(mod, camera) is not None and active(mod):
                    x0, y0, z0 = target
                    target = (max(x0, min(x0 + float(_state['dolly']), MAX_OFFSET_X)), y0, z0)
        if alpha >= 1.0:
            waiting = zero and (getattr(mod, '_ads_route', None) in FPS_ROUTES or _camera_transitioning(mod))
            if not waiting:
                _state['fade'] = None
                return live
            return target
    start = fade['start']
    return tuple(a + (b - a) * eased for a, b in zip(start, target))


def _hip_offset(mod: Any) -> tuple[float, float, float]:
    from .settings_validation import position_values
    return tuple(position_values((mod.camera_offset_x, mod.camera_offset_y, mod.camera_offset_z)))


def _live_offset(camera: Any) -> tuple[float, float, float]:
    current = camera.CameraModeState.CameraLocationOffset
    return float(current.X), float(current.Y), float(current.Z)


def _start_fade(kind: str, start: tuple[float, float, float]) -> None:
    _state['fade'] = dict(kind=kind, start=tuple(float(v) for v in start),
                          started=monotonic(), duration=SCOPE_BLEND_SECONDS)


def start_return_fade(mod: Any) -> None:
    """Blend the camera offset back in after leaving a first-person view."""
    _pc, _pawn, camera = mod._get_runtime()
    start = _live_offset(camera) if camera is not None else (0.0, 0.0, 0.0)
    _start_fade('in', start)


def return_transition(mod: Any, default: float) -> float:
    """Camera blend time back to third person for hybrid weapon swaps in the scope."""
    if not active(mod):
        return default
    start_return_fade(mod)
    return SCOPE_BLEND_SECONDS


def finish_fov_fade(mod: Any) -> None:
    """Stop a running fade; restore its end value only on the current manager."""
    fov = _state['fov_fade']
    _state['fov_fade'] = None
    if fov is None:
        return
    camera = fov['camera']()
    _pc, _pawn, live = mod._get_runtime()
    if camera is not None and camera == live:
        camera.CameraModeState.BaseFOVOffset = fov['to']


# -- per frame ---------------------------------------------------------------------
def update(mod: Any) -> None:
    """Camera-update stage: FOV offset fade and scope bookkeeping."""
    _consume_scope_request(mod)
    prepare_return_fov(mod)
    fov = _state['fov_fade']
    if fov is not None:
        camera = fov['camera']()
        _pc, _pawn, live = mod._get_runtime()
        alpha, eased = _progress(fov, monotonic())
        if (camera is None or live is None or camera != live or alpha >= 1.0
                or not _fade_context_ok(mod)):
            finish_fov_fade(mod)
        else:
            camera.CameraModeState.BaseFOVOffset = fov['from'] + (fov['to'] - fov['from']) * eased
    if _state['scoped']:
        pending = (getattr(mod, '_ads_handoff', {}) or {}).get('route_pending')
        if not mod._ads_active or (mod._ads_route not in FPS_ROUTES and not pending):
            _state['scoped'] = False
            _state['scope_lost'] += 1
            _state['last_event'] = 'SCOPE_LOST route=' + str(mod._ads_route)


# -- scope switch ------------------------------------------------------------------
def _refuse(mod: Any, reason: str) -> str:
    refusals = _state['refusals']
    refusals[reason] = refusals.get(reason, 0) + 1
    _state['last_event'] = 'REFUSED ' + reason
    if refusals[reason] <= 3:
        mod.logging.info(TAG + 'HYBRID_SCOPE_REFUSED reason=' + reason)
    return 'refused:' + reason


def _blocked_by_state(mod: Any) -> Optional[str]:
    if mod._slide_active or mod._ladder_active:
        return 'slide_or_ladder'
    if mod._vehicle_camera_active or mod._shop_camera_active:
        return 'vehicle_or_shop'
    if (getattr(mod, '_camera_lifecycle', {}) or {}).get('pending'):
        return 'camera_lifecycle'
    return None


def toggle_scope(mod: Any) -> str:
    """Execute the queued scope switch in the camera stage."""
    if not active(mod):
        return 'inactive'
    try:
        return exit_scope(mod) if _state['scoped'] else enter_scope(mod)
    except SWITCH_ERRORS as exc:
        _state['last_error'] = type(exc).__name__ + ': ' + str(exc)[:200]
        _state['last_event'] = 'ERROR'
        mod.logging.error(TAG + 'HYBRID_SCOPE_FAILED ' + _state['last_error'])
        return 'error'


def enter_scope(mod: Any) -> str:
    """Held TPS ADS -> native first-person scope of the same weapon."""
    pc, pawn, camera = mod._get_runtime()
    if pawn is None or camera is None:
        return _refuse(mod, 'no_runtime')
    handoff, ads = mod._ads_handoff, mod._ads_tps_state
    if not (mod._ads_active and mod._ads_route == 'tps' and handoff.get('held')
            and isinstance(ads, dict) and ads.get('phase') == 'ads'):
        return _refuse(mod, 'not_holding_tps_ads')
    if handoff.get('latch_active') or handoff.get('reticle_rebind_active') or handoff.get('in_gap'):
        return _refuse(mod, 'weapon_handoff')
    blocked = _blocked_by_state(mod)
    if blocked:
        return _refuse(mod, blocked)
    if bool(camera.CameraModeState.bIsTransitioning):
        return _refuse(mod, 'camera_transitioning')
    weapon = camera.CameraModeInputs.Weapon
    weapon_address = mod._ads_object_address(weapon)
    if not weapon_address or weapon_address != int(ads.get('weapon_address', 0)):
        return _refuse(mod, 'weapon_changed')
    category = str(ads.get('category') or '')
    # FPS ADS switches the camera definition: release the TPS Look owner first,
    # exactly like the existing TPS -> sniper migration.
    if ((mod._native_active() or mod._active_native_state.get('ladder_default'))
            and not mod._native_stop('hybrid_scope_enter')):
        raise RuntimeError('Recoil restore failed before the hybrid scope')
    start_offset = _live_offset(camera)
    mode_state = ads['mode_state']
    fov_from, fov_to = float(mode_state.BaseFOVOffset), float(ads['original_offset'])
    tps_hold = _capture_tps_hold(pc, pawn, camera, weapon, ads)
    _pause_omni_before_scope(mod, pc, pawn, camera)
    # Commit the ADS route only after the SDK call. Omni is already paused;
    # a refused switch resumes through its normal release/owner guards.
    camera.SetActorCameraMode(pawn, 'Default', '', SCOPE_BLEND_SECONDS, False, True)
    if ads.get('offset_overridden'):
        _state['fov_fade'] = {'camera': WeakPointer(camera), 'started': monotonic(),
                              'duration': SCOPE_BLEND_SECONDS, 'from': fov_from, 'to': fov_to}
    mod._reticle_publish_pending = False
    mod._ads_tps_state = None
    mod._ads_collector_address = 0
    mod._cleanup_ads_handoff('hybrid_scope_enter')
    handoff['held'] = True
    handoff['route_weapon'] = weapon_address
    mod._ads_active = True
    mod._ads_route = 'sniper_fps' if category == 'sniper_rifle' else 'fallback_fps'
    _state.update(scoped=True, scope_weapon=weapon_address, last_event='SCOPE_ON')
    _state['tps_hold'] = tps_hold
    _record_fov(mod, camera, 'SCOPE_ON')
    _start_fade('out', start_offset)
    _state['scope_enters'] += 1
    mod.logging.info(
        TAG + 'HYBRID_SCOPE_ON route=' + repr(mod._ads_route) + ' category=' + repr(category)
        + ' weapon=0x%016X blend=%.2f ' % (weapon_address, SCOPE_BLEND_SECONDS)
        + str(mod._ads_zoom_fields(pawn)))
    return 'scope_on'


def exit_scope(mod: Any) -> str:
    """Native scope -> held TPS ADS of the same weapon (ADS still held)."""
    _pc, pawn, camera = mod._get_runtime()
    if pawn is None or camera is None:
        return _refuse(mod, 'no_runtime')
    handoff = mod._ads_handoff
    if not (mod._ads_active and mod._ads_route in FPS_ROUTES and handoff.get('held')):
        _state['scoped'] = False
        return _refuse(mod, 'not_scoped')
    if handoff.get('route_pending'):
        return _refuse(mod, 'migration_pending')
    blocked = _blocked_by_state(mod)
    if blocked:
        return _refuse(mod, blocked)
    if bool(camera.CameraModeState.bIsTransitioning):
        return _refuse(mod, 'camera_transitioning')
    weapon = camera.CameraModeInputs.Weapon
    weapon_address = mod._ads_object_address(weapon)
    if not weapon_address or weapon_address != int(handoff.get('route_weapon', 0)):
        return _refuse(mod, 'weapon_changed')
    category, source, evidence = mod._classify_ads_weapon(weapon)
    start_offset = _live_offset(camera)
    camera.SetActorCameraMode(pawn, 'ThirdPerson', '', SCOPE_BLEND_SECONDS, False, True)
    handoff['route_pending'] = dict(from_route=mod._ads_route, weapon_address=weapon_address,
                                    category=category, source=source, evidence=evidence,
                                    hybrid_same_weapon=True, hybrid_tps_resume=_state['tps_hold'])
    _state.update(scoped=False, last_event='SCOPE_OFF')
    _start_fade('in', start_offset)
    prepare_return_fov(mod)
    _state['scope_exits'] += 1
    mod.logging.info(TAG + 'HYBRID_SCOPE_OFF weapon=0x%016X blend=%.2f; TPS ADS resumes '
                     'after the camera blend' % (weapon_address, SCOPE_BLEND_SECONDS))
    return 'scope_off'


def release_transition(mod: Any, default: float) -> float:
    """ADS released while scoped: blend back to omni TPS like the scope exit."""
    cancel_return_fov(mod)
    _state['tps_hold'] = None
    if not _state['scoped']:
        return default
    _state.update(scoped=False, last_event='SCOPE_RELEASED')
    _state['scope_releases'] += 1
    start_return_fade(mod)
    return SCOPE_BLEND_SECONDS


def set_dolly(value: float) -> None:
    value = float(value)
    if not 0.0 <= value <= MAX_DOLLY:
        raise ValueError('dolly must be 0..%d cm' % MAX_DOLLY)
    _state['dolly'] = value


def set_max_magnification(value: float) -> None:
    value = float(value)
    if not 1.0 <= value <= 4.0:
        raise ValueError('zoom must be 1.0..4.0')
    _state['max_magnification'] = value


def status(mod: Any) -> dict:
    return dict(option=option_enabled(mod), active=active(mod), scoped=_state['scoped'],
                dolly=_state['dolly'], max_magnification=_state['max_magnification'],
                scope_enters=_state['scope_enters'], scope_exits=_state['scope_exits'],
                scope_releases=_state['scope_releases'], scope_lost=_state['scope_lost'],
                refusals=dict(_state['refusals']), last_event=_state['last_event'],
                last_error=_state['last_error'])
