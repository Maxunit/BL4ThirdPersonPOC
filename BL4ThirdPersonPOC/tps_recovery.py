"""Re-arm the existing camera repair when TPS is wanted but BL4 settled in Default.

Death/respawn and save -> main menu -> load can leave BL4 in its native Default
(first-person) camera while the loader still wants third person and no
ClientRestart repair was armed (0.3.9.0 test: no CAMERA_LIFECYCLE_ARMED line).
The owned TPS entry is gone, so F5 first "disabled" an invisible TPS.

This owner adds no hooks and no native writes. It only arms the existing
camera lifecycle (reason 'tps_desync'), whose settle check and
_repair_third_person() retire/pop stale ownership and push again.

Gates: TPS wanted, no pending lifecycle or FFYL transition, no ADS/slide/ladder/
vehicle/shop/menu route, local on-foot OakCharacter, Default mode settled for
SETTLE_SECONDS. Bounded: COOLDOWN_SECONDS between attempts and MAX_ATTEMPTS per
desync episode; an episode ends once settled ThirdPerson is observed again.

Respawn is different: the intended result is the existing respawn handoff
(respawn_camera.py), which pushes TPS with the remaining native blend so the
respawn camera flight ends at the TPS camera position. That handoff only runs
inside a 'client_restart' lifecycle. When BL4 shows RespawnCamera and no
lifecycle was armed (missing ClientRestart reconciliation), this module arms
exactly that lifecycle while RespawnCamera is still active, once per respawn.
The settled-Default fallback stays the last resort for every other path.
"""
from time import perf_counter

SETTLE_SECONDS = 0.75
COOLDOWN_SECONDS = 3.0
MAX_ATTEMPTS = 3
ATTR = '_tps_recovery_state'
TAG = '[BL4ThirdPersonPOC.TPSRecovery]'


def state(mod):
    current = getattr(mod, ATTR, None)
    if not isinstance(current, dict):
        current = dict(since=None, attempts=0, last_attempt=None, gave_up=False,
                       repairs_armed=0, last_block=None, respawn_armed=False,
                       respawn_handoffs_armed=0)
        setattr(mod, ATTR, current)
    return current


def reset(mod):
    setattr(mod, ATTR, None)


def blocked_by_route(mod):
    """Return the name of an intentional non-TPS route, or None."""
    if not mod._third_person_enabled:
        return 'tps_disabled'
    if mod._camera_lifecycle.get('pending'):
        return 'lifecycle_pending'
    for flag in ('_ads_active', '_vehicle_camera_active', '_shop_camera_active',
                 '_ladder_active', '_slide_active', '_slide_camera_recovery_pending'):
        if bool(getattr(mod, flag, False)):
            return flag
    if getattr(mod, '_ads_route', 'hip') != 'hip':
        return 'ads_route'
    if getattr(mod, '_ladder_pending_third_person_enabled', None) is not None:
        return 'ladder_pending'
    if (getattr(mod, '_ads_press_intent', None) or {}).get('pending'):
        return 'ads_press_pending'
    if mod._camera_stack_owner.get('pending_pop'):
        return 'pending_pop'
    if mod._native_fault and mod._native_active():
        return 'native_fault'
    respawn = getattr(mod, '_respawn_camera_state', None)
    if isinstance(respawn, dict) and respawn.get('active') and not (
            respawn.get('handoff_aborted') or respawn.get('handoff_finished')):
        return 'respawn_handoff'
    from . import ffyl_strategy_runtime
    if ffyl_strategy_runtime.controls_transition(mod):
        return 'ffyl_transition'
    return None


def resolve_own_repair(mod):
    """Close a 'tps_desync' lifecycle that another path already settled.

    Non-client_restart lifecycles wait for Default; if TPS came back another
    way (vehicle exit, slide recovery, F5) the request must not stay pending,
    because a pending lifecycle also blocks slide recovery and FFYL arming.
    Returns True while this module's request is still pending.
    """
    lifecycle = mod._camera_lifecycle
    if not (lifecycle.get('pending') and lifecycle.get('reason') == 'tps_desync'):
        return False
    if (not mod._third_person_enabled or mod._vehicle_camera_active
            or mod._shop_camera_active or mod._ladder_active):
        mod._discard_camera_lifecycle('tps_desync_superseded')
        return False
    pc, pawn, manager = mod._get_runtime()
    if pawn is None or manager is None:
        return True
    if (str(manager.GetActorCameraMode(pawn)) == 'ThirdPerson'
            and not bool(manager.CameraModeState.bIsTransitioning)):
        lifecycle.update(pending=False, repair_done=True, suppress_offsets=False,
                         settled_since=None, phase='tps_desync_resolved')
        mod.logging.info(TAG + ' RESOLVED third person active again')
        return False
    return True


def retire_if_stack_empty(mod, manager, pawn_address, manager_address):
    """Forget an owned entry the game already removed, instead of popping blind."""
    owner = mod._camera_stack_owner
    if not owner.get('owned'):
        return False
    if (int(owner.get('pawn_address', 0)) != pawn_address
            or int(owner.get('manager_address', 0)) != manager_address):
        return False  # _pop_third_person retires a replaced owner itself.
    try:
        empty = bool(mod._ffyl_camera_stack_empty(manager))
    except Exception as exc:
        mod.logging.warning(TAG + ' STACK_UNVERIFIED ' + type(exc).__name__ + ': ' + str(exc))
        return False
    if empty:
        mod._retire_camera_stack_owner('tps_desync_empty_stack')
    return empty


def arm_respawn_handoff(mod, current):
    """Arm the existing respawn handoff while BL4 still shows RespawnCamera.

    Returns 'respawn_armed' when the 'client_restart' lifecycle was armed here.
    """
    if not mod._third_person_enabled:
        current['respawn_armed'] = False
        return None
    pc, pawn, manager = mod._get_runtime()
    if pawn is None or manager is None:
        return None
    if str(manager.GetActorCameraMode(pawn)) != 'RespawnCamera':
        current['respawn_armed'] = False
        return None
    if current['respawn_armed'] or mod._camera_lifecycle.get('pending'):
        return None  # Already armed (here or by ClientRestart) for this respawn.
    if (mod._vehicle_camera_active or mod._is_vehicle_camera_view()
            or (mod._native_fault and mod._native_active())):
        return None
    from . import ffyl_strategy_runtime
    if ffyl_strategy_runtime.controls_transition(mod):
        return None
    current['respawn_armed'] = True
    current['respawn_handoffs_armed'] += 1
    mod.logging.info(TAG + ' RESPAWN_CAMERA_SEEN no ClientRestart reconciliation pending; '
                     'arming respawn TPS handoff')
    mod._arm_camera_lifecycle('client_restart', expected_pawn=mod._object_address(pawn))
    return 'respawn_armed'


def update(mod, now=None):
    current = state(mod)
    if resolve_own_repair(mod):
        current['since'] = None
        return None
    if arm_respawn_handoff(mod, current) is not None:
        current['since'] = None
        return 'respawn_armed'
    block = blocked_by_route(mod)
    if block is not None:
        current['since'] = None
        current['last_block'] = block
        if block == 'tps_disabled':
            current.update(attempts=0, gave_up=False)
        return None
    pc, pawn, manager = mod._get_runtime()
    if pc is None or pawn is None or manager is None:
        current['since'] = None
        return None
    if bool(pc.bShowMouseCursor) or str(pawn.Class.Name) != 'OakCharacter':
        current['since'] = None
        return None
    if mod._is_vehicle_camera_view():
        current['since'] = None
        return None
    mode = str(manager.GetActorCameraMode(pawn))
    transitioning = bool(manager.CameraModeState.bIsTransitioning)
    if mode != 'Default' or transitioning:
        current['since'] = None
        if mode == 'ThirdPerson' and not transitioning:
            # Healthy TPS ends the episode.
            current.update(attempts=0, gave_up=False)
        return None
    now = perf_counter() if now is None else now
    if current['since'] is None:
        current['since'] = now
        return None
    if now - current['since'] < SETTLE_SECONDS:
        return None
    if current['attempts'] >= MAX_ATTEMPTS:
        if not current['gave_up']:
            current['gave_up'] = True
            mod.logging.error(TAG + ' GAVE_UP attempts=' + str(current['attempts'])
                              + '; camera stays first-person, press F5 to retry')
        return None
    if current['last_attempt'] is not None and now - current['last_attempt'] < COOLDOWN_SECONDS:
        return None
    current['attempts'] += 1
    current['last_attempt'] = now
    current['since'] = None
    current['repairs_armed'] += 1
    owner = mod._camera_stack_owner
    pawn_address = mod._object_address(pawn)
    manager_address = mod._object_address(manager)
    stale = bool(owner.get('owned')) and (
        int(owner.get('pawn_address', 0)) != pawn_address
        or int(owner.get('manager_address', 0)) != manager_address)
    retired = retire_if_stack_empty(mod, manager, pawn_address, manager_address)
    mod.logging.warning(
        TAG + ' DEFAULT_WHILE_TPS_WANTED attempt=' + str(current['attempts'])
        + ' owned=' + str(bool(owner.get('owned'))) + ' stale_owner=' + str(stale)
        + ' retired_empty_stack=' + str(retired) + '; arming camera repair')
    mod._arm_camera_lifecycle('tps_desync', expected_pawn=pawn_address)
    return 'armed'


def visibly_first_person(mod):
    """True when TPS is wanted but BL4 shows a settled Default camera (F5 helper)."""
    if blocked_by_route(mod) is not None:
        return False
    pc, pawn, manager = mod._get_runtime()
    if pc is None or pawn is None or manager is None or bool(pc.bShowMouseCursor):
        return False
    if str(pawn.Class.Name) != 'OakCharacter' or mod._is_vehicle_camera_view():
        return False
    return (str(manager.GetActorCameraMode(pawn)) == 'Default'
            and not bool(manager.CameraModeState.bIsTransitioning))
