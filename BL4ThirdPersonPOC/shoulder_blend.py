"""Short shoulder interpolation on existing camera updates; weak context ownership."""
import math
from time import monotonic
from unrealsdk.unreal import WeakPointer

_blend = None
_scope = None


def reset():
    global _blend, _scope
    _blend = None
    _scope = None


def context(owner):
    if (not owner._third_person_enabled or not owner._third_person_pushed
            or owner._vehicle_camera_active or owner._shop_camera_active
            or owner._ladder_active or owner._slide_active
            or owner._camera_lifecycle.get('suppress_offsets', False)
            or owner._camera_lifecycle.get('phase') == 'repairing'
            or (owner._ads_active and owner._ads_route != 'tps')):
        return None
    pc, pawn, manager = owner._get_runtime()
    if any(o is None for o in (pc, pawn, manager)):
        return None
    if (owner._ffyl_camera_active(pawn, manager)
            or str(manager.GetActorCameraMode(pawn)) != 'ThirdPerson'
            or owner._looks_like_first_person_fallback()):
        return None
    return tuple(WeakPointer(o) for o in (pc, pawn, manager))



def safe_context(owner):
    try:
        return context(owner)
    except Exception as exc:
        owner.logging.warning(
            '[BL4ThirdPersonPOC] SHOULDER_BLEND_CONTEXT_UNAVAILABLE '
            +type(exc).__name__+': '+str(exc)
        )
        return None


def matches(a, b):
    if a is None or b is None:
        return False
    aa, bb = tuple(r() for r in a), tuple(r() for r in b)
    return all(o is not None for o in aa+bb) and all(x == y for x, y in zip(aa, bb))


def value(now):
    b = _blend
    alpha = min(1.0, max(0.0, (now-b['started'])/b['duration']))
    eased = alpha*alpha*(3.0-2.0*alpha)
    return b['start']+(b['target']-b['start'])*eased


def swap(owner):
    global _blend
    old = float(owner.camera_offset_y.value)
    target = -old
    settings = getattr(owner, '_camera_feature_options', None)
    duration = float(settings['shoulder'].value) if settings is not None else 0.0
    refs = None
    if math.isfinite(duration) and duration > 0.0:
        refs = safe_context(owner)
    if refs is not None:
        now = monotonic()
        start = (value(now) if _blend is not None
                 and matches(_blend['refs'], refs) and old == _blend['target'] else old)
        _blend = {'start': start, 'target': target, 'started': now,
                  'duration': min(1.0, duration), 'refs': refs}
    else:
        _blend = None
    owner.camera_offset_y.value = target
    owner._apply_camera_offset()


def begin(owner):
    global _blend, _scope
    previous = _scope
    _scope = None
    if _blend is not None:
        b = _blend
        if (float(owner.camera_offset_y.value) != b['target']
                or not matches(b['refs'], safe_context(owner))):
            _blend = None
        else:
            now = monotonic()
            _scope = value(now)-b['target']
            if now-b['started'] >= b['duration']:
                _blend = None
    return previous


def end(previous):
    global _scope
    _scope = previous


def compensate(x, y, z):
    return x, y if _scope is None else float(y)+_scope, z
