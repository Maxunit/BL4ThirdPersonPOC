"""Grounded Root height compensation inside the existing TPS offset scope.

No producer, timer, native access or actor/animation writes. The .34 captures
show Root at mesh origin minus FloorDist on ordinary ground, and about 44 units
below that on a railing. Use that live reference even when starting on a perch.
Motion uses the same raw Root translation, separately from the filtered camera
translation, so landing compression is retained without following Root twice.
"""
import math
from unrealsdk.unreal import WeakPointer

RESPONSE = 0.20
MAX_DROP = 80.0
DEADBAND = 2.0


def reset(owner):
    owner._root_height_state = dict(refs=None, available=None, raw_z=0.0,
        target_z=0.0, filtered_z=0.0, status='idle', last_error='')


def matches(refs, objects):
    if refs is None or len(refs) != len(objects):
        return False
    resolved = tuple(ref() for ref in refs)
    return all(saved is not None and live is not None and saved == live
               for saved, live in zip(resolved, objects))


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite Root height input')
    return number


def rotation_value(rotation, name):
    try:
        value = getattr(rotation, name)
    except AttributeError:
        value = getattr(rotation, name.lower())
    return finite(value)


def vertical_local(height, pitch, roll):
    """Inverse camera rotation of a world-Z displacement; no division at ±90°."""
    height, pitch, roll = map(finite, (height, pitch, roll))
    p, r = math.radians(pitch), math.radians(roll)
    return (height * math.sin(p), -height * math.cos(p) * math.sin(r),
            height * math.cos(p) * math.cos(r))


def prepare(owner, pc, pawn, manager):
    frame = getattr(owner, '_camera_frame', None)
    if frame is None or owner.root_height_enabled.value is not True:
        reset(owner)
        return
    frame['height_visited'] = True
    state = owner._root_height_state
    frame['height_local'] = (0.0, 0.0, 0.0)
    frame['motion_root_z'] = None
    if (owner._ads_active or owner._slide_active or owner._ladder_active
            or owner._camera_lifecycle.get('pending')
            or owner._mantle_camera_state.get('active')
            or owner._mantle_camera_state.get('releasing')):
        reset(owner)
        return
    try:
        if pc is None or pawn is None or manager is None:
            reset(owner)
            return
        if (bool(pc.bShowMouseCursor) or owner._ffyl_camera_active(pawn, manager)
                or bool(manager.CameraModeState.bIsTransitioning)):
            reset(owner)
            return
        mesh = pawn.Mesh
        movement = pawn.OakCharacterMovement
        if mesh is None or movement is None:
            reset(owner)
            return
        objects = (pc, pawn, manager, mesh)
        if not matches(state['refs'], objects):
            reset(owner)
            state = owner._root_height_state
            state['refs'] = tuple(WeakPointer(obj) for obj in objects)
            state['available'] = bool(mesh.DoesSocketExist('Root'))
        if not state['available']:
            state['status'] = 'missing_root'
            return
        mode = int(movement.MovementMode)
        crouched = bool(pawn.bIsCrouched)
        # Only observed ordinary walking/falling modes can feed this route.
        if mode not in (1, 3) or int(movement.CustomMovementMode) != 0:
            reset(owner)
            return
        raw = 0.0
        if not crouched:
            if frame.get('sample_pawn') != int(pawn._get_address()):
                raise ValueError('Current mantle sample unavailable')
            if frame.get('sample_mesh') != int(mesh._get_address()):
                raise ValueError('Current mesh sample changed')
            root_z = finite(mesh.GetSocketLocation('Root').Z)
            mesh_z = finite(frame['mesh'][2])
            floor_dist = 0.0
            if mode == 1:
                floor = movement.CurrentFloor
                if not (bool(floor.bBlockingHit) and bool(floor.bWalkableFloor)):
                    raise ValueError('Walkable blocking floor required')
                floor_dist = finite(floor.FloorDist)
                if not 0.0 <= floor_dist <= 8.0:
                    raise ValueError('Floor distance outside height reference bounds')
            raw = root_z - mesh_z + floor_dist
            if not -MAX_DROP <= raw <= 8.0:
                raise ValueError('Root displacement outside QA bounds')
            frame['motion_root_z'] = raw
        # SDK calls may reenter gameplay. Never publish a partially rebound frame.
        runtime = tuple(owner._get_runtime())
        if not matches(state['refs'][:3], runtime):
            frame['owner_changed'] = True
            reset(owner)
            return
        live_pawn = state['refs'][1]()
        if (not matches(state['refs'], (*runtime, live_pawn.Mesh))
                or movement != live_pawn.OakCharacterMovement):
            frame['owner_changed'] = True
            reset(owner)
            return
        target = raw if mode == 1 and not crouched and raw < -DEADBAND else 0.0
        filtered = state['filtered_z'] + RESPONSE * (target - state['filtered_z'])
        if abs(filtered) < 0.02:
            filtered = 0.0
        if filtered:
            rotation = manager.CameraModeState.POV.Rotation
            pitch = rotation_value(rotation, 'Pitch')
            roll = rotation_value(rotation, 'Roll')
            if not -180.0 <= pitch <= 180.0 or not -180.0 <= roll <= 180.0:
                raise ValueError('Camera rotation outside QA bounds')
            frame['height_refs'] = state['refs']
            frame['height_local'] = vertical_local(filtered, pitch, roll)
        state.update(raw_z=raw, target_z=target, filtered_z=filtered,
                     status='tracking' if target else 'release' if filtered else 'neutral',
                     last_error='')
    except Exception as exc:
        message = type(exc).__name__ + ': ' + str(exc)
        if state.get('last_error') != message:
            owner.logging.warning('[BL4ThirdPersonPOC.RootHeight] DECLINED '+message)
        state.update(raw_z=0.0, target_z=0.0, filtered_z=0.0,
                     status='declined', last_error=message)
        frame['height_local'] = (0.0, 0.0, 0.0)
        frame['motion_root_z'] = None


def compensate(owner, pc, pawn, manager, values):
    frame = getattr(owner, '_camera_frame', None)
    if (not frame or not frame.get('height_refs')
            or owner.root_height_enabled.value is not True):
        return values
    if not matches(frame['height_refs'][:3], (pc, pawn, manager)):
        return values
    if frame['height_refs'][3]() != pawn.Mesh:
        return values
    return tuple(v + delta for v, delta in zip(values, frame['height_local']))


def snapshot(owner):
    state = getattr(owner, '_root_height_state', {})
    return dict(enabled=bool(getattr(owner, 'root_height_enabled', None)
                             and owner.root_height_enabled.value is True),
                **{key: state.get(key) for key in (
                    'available', 'raw_z', 'target_z', 'filtered_z', 'status', 'last_error')})
