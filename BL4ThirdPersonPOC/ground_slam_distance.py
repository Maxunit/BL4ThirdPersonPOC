"""Ground-driven Slam distance on the owned widget PRE and camera setter.

V4's validated entry/ground envelope and composed Exit handoff, without a
probe wrapper, diagnostic sampling, new producer, timer or native patch.
One subscription uses the V4-proven widget source; animation events only apply
the current distance through their already existing scoped camera setter.
"""
import ctypes
import hashlib
from itertools import islice
import math
import struct
import sys
from time import perf_counter_ns
from unrealsdk import hooks
from unrealsdk import find_object, make_struct
from unrealsdk.unreal import WeakPointer
from . import runtime_updates, ground_slam_camera

RETURN_HEIGHT = 1200.
CONTACT_MARGIN = 100.
TRACE_LENGTH = 20000.
EXIT_HASH = '1f9f3cc3a0aaaacf18ff4f612d7c37a93b97ea7af867f94df5b2106f1cdabffb'


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Nonfinite Slam distance value')
    return value


def approach(old, target, dt, response):
    value = old + (target - old) * (-math.expm1(-max(0., min(.1, dt)) / response))
    return target if abs(value - target) < .02 else value


def ground_envelope(clearance, velocity_z, dt):
    predicted = max(0., clearance + min(0., velocity_z) * max(0., min(.1, dt)))
    t = max(0., min(1., (predicted - CONTACT_MARGIN) / (RETURN_HEIGHT - CONTACT_MARGIN)))
    return t * t * (3. - 2. * t)


def configured(mod):
    option = getattr(mod, 'ground_slam_distance_cm', None)
    return max(0., min(250., finite(option.value))) if option is not None else 0.


def character_movement(pawn):
    # The locally possessed pawn can be OakVehicle. Missing character movement
    # is an expected perspective/possession handoff, not a Slam-distance fault.
    return None if pawn is None else getattr(pawn, 'OakCharacterMovement', None)


def permitted(mod, pc):
    from . import ffyl_strategy_runtime
    return (mod._third_person_enabled and mod._third_person_pushed
            and mod.tps_ground_slam_beta.value is True and not bool(pc.bShowMouseCursor)
            and not any(bool(getattr(mod, k, False)) for k in (
                '_ads_active', '_slide_active', '_ladder_active', '_vehicle_camera_active',
                '_shop_camera_active', '_ffyl_native_resume_pending'))
            and not mod._camera_lifecycle.get('pending')
            and not mod._camera_lifecycle.get('suppress_offsets')
            and not mod._mantle_camera_state.get('active')
            and not mod._mantle_camera_state.get('releasing')
            and not ffyl_strategy_runtime.controls_transition(mod))


class Distance:
    def __init__(self, mod, objects):
        self.mod = mod
        self.refs = tuple(WeakPointer(o) for o in objects)
        self.amount = self.entry = 0.
        self.active = self.had_slam = self.releasing = False
        self.mode = None
        self.channel = self.capsule_ref = self.library_ref = None
        self.gap = 0.
        self.last_raw = None
        self.shift = self.shift_candidate = None
        self.shift_count = 0
        self.history = []
        self.bridge = None
        self.wait = 0
        self.fallback = self.fault = False
        self.status = 'waiting_for_ground'

    def matches(self, objects):
        live = tuple(ref() for ref in self.refs)
        return (len(live) == len(objects) and all(a is not None and a == b
                for a, b in zip(live, objects)))

    def current(self):
        pc, pawn, camera = self.mod._get_runtime()
        objects = (pc, pawn, camera, character_movement(pawn))
        if not self.matches(objects):
            raise RuntimeError('Slam distance owner changed')
        return objects

    def calibrate(self, objects):
        pc, pawn, camera, movement = objects
        floor = movement.CurrentFloor
        if int(movement.MovementMode) != 1 or not (floor.bBlockingHit and floor.bWalkableFloor):
            return
        fn = pawn.Class._find('IsPerformingGroundSlam')
        props = list(islice(fn._properties(), 3))
        if (str(fn._path_name()) != '/Script/OakGame.OakCharacter:IsPerformingGroundSlam'
                or not int(fn.FunctionFlags) & 0x10000000 or int(fn.NumParams) != 1
                or len(props) != 1 or str(props[0].Class.Name) != 'BoolProperty'
                or not int(props[0].PropertyFlags) & 0x400):
            raise RuntimeError('Reviewed pure Ground Slam getter differs')
        capsule = pawn.CapsuleComponent
        library = find_object('KismetSystemLibrary', '/Script/Engine.Default__KismetSystemLibrary')
        if capsule is None or library is None:
            raise RuntimeError('Ground sensor unavailable')
        fn = library.Class._find('LineTraceSingle')
        props = list(islice(fn._properties(), 15))
        names = ('WorldContextObject', 'Start', 'End', 'TraceChannel', 'bTraceComplex',
                 'ActorsToIgnore', 'DrawDebugType', 'OutHit', 'bIgnoreSelf', 'TraceColor',
                 'TraceHitColor', 'DrawTime', 'ReturnValue')
        if (int(fn.NumParams) != 13 or tuple(str(p.Name) for p in props) != names
                or str(props[-1].Class.Name) != 'BoolProperty'
                or str(props[7].Struct._path_name()) != '/Script/Engine.HitResult'):
            raise RuntimeError('Reviewed ground trace differs')
        self.capsule_ref, self.library_ref = WeakPointer(capsule), WeakPointer(library)
        reference = finite(floor.FloorDist)
        matches = []
        for channel in (0, 1):
            gap = self.trace(channel)
            if gap is not None and abs(gap - reference) <= 12.:
                matches.append((abs(gap - reference), channel, gap))
        if not matches:
            raise RuntimeError('Ground trace does not agree with standing floor')
        _, self.channel, self.gap = min(matches)
        self.status = 'ready'

    def trace(self, channel):
        pc, pawn, camera, movement = self.current()
        capsule, library = self.capsule_ref(), self.library_ref()
        if capsule is None or pawn.CapsuleComponent != capsule or library is None:
            raise RuntimeError('Ground sensor weak owner changed')
        center = capsule.K2_GetComponentLocation()
        xyz = tuple(finite(getattr(center, a)) for a in 'XYZ')
        half = finite(capsule.GetScaledCapsuleHalfHeight())
        if not 1. < half < 500.:
            raise ValueError('Ground sensor capsule outside bounds')
        end = make_struct('Vector', X=xyz[0], Y=xyz[1], Z=xyz[2] - TRACE_LENGTH)
        result = library.LineTraceSingle(pc, center, end, channel, True, [pawn], 0,
            make_struct('HitResult'), True, make_struct('LinearColor', R=0., G=0., B=0., A=0.),
            make_struct('LinearColor', R=0., G=0., B=0., A=0.), 0.)
        self.current()
        if self.capsule_ref() != pawn.CapsuleComponent:
            raise RuntimeError('Ground sensor changed during trace')
        if not bool(result[0]):
            return None
        hit = result[-1]
        impact_z, normal_z = finite(hit.ImpactPoint.Z), finite(hit.ImpactNormal.Z)
        gap = xyz[2] - half - impact_z
        if (hit.bBlockingHit and not hit.bStartPenetrating and normal_z >= .4
                and -15. <= gap <= TRACE_LENGTH and impact_z <= xyz[2]):
            return gap
        return None

    def observe_composition(self, camera):
        if self.last_raw is None:
            return
        shift = finite(camera.CameraModeState.CameraLocationOffset.X) - self.last_raw[1]
        if abs(shift) > 512.:
            raise ValueError('Slam offset composition outside bounds')
        if self.shift_candidate is None or abs(self.shift_candidate - shift) > 1e-6:
            self.shift_candidate, self.shift_count = shift, 1
        else:
            self.shift_count += 1
        if self.shift_count >= 3:
            self.shift = shift

    def owns_exit(self, state):
        if (not getattr(state, 'active', False) or getattr(state, 'mod', None) is not self.mod
                or getattr(state, 'owner_invalidated', False)):
            return False
        current = self.current()
        if not ground_slam_camera.owner_matches(state, current[:3]):
            return False
        if ctypes.sizeof(state.modify) != 256 or ctypes.addressof(state.modify) % 8:
            raise RuntimeError('Exit control layout differs')
        return (struct.unpack_from('<I', state.modify.raw, 8)[0] == 1
                and struct.unpack_from('<I', state.modify.raw, 184)[0] == 1)

    def release_exit(self, dt):
        if self.fallback:
            return
        if self.bridge is None:
            state = sys.modules.get(ground_slam_camera.KEY)
            if (state is None or not self.owns_exit(state)
                    or not struct.unpack_from('<Q', state.modify.raw, 40)[0]):
                self.wait += 1
                if self.wait > 12:
                    self.fallback = True
                    self.status = 'tps_fallback'
                return
            if (ground_slam_camera.OFFSET_PREFIX_SHA256 != EXIT_HASH
                    or hashlib.sha256(ground_slam_camera.OFFSET_PREFIX).hexdigest() != EXIT_HASH):
                raise RuntimeError('Exit consumer fingerprint differs')
            target = struct.unpack_from('<3d', state.modify.raw, 160)
            if not all(math.isfinite(v) and abs(v) <= 512. for v in target):
                raise ValueError('Exit target outside bounds')
            record = next((r for r in reversed(self.history) if self.shift is not None
                           and abs(r[1] + self.shift - target[0]) < 1e-6), None)
            if record is None:
                self.fallback = True
                self.status = 'tps_fallback'
                self.mod.logging.warning('[BL4ThirdPersonPOC.SlamDistance] Unmatched Exit target; smooth TPS fallback')
                return
            contribution = record[0] - record[1]
            base = target[0] + contribution
            if not 0. <= contribution <= 250.000001 or abs(base) > 512.:
                raise ValueError('Exit distance contribution outside bounds')
            self.amount = min(self.amount, contribution)
            self.bridge = dict(state=state, base=base, last=target[0])
        self.write_exit(approach(self.amount, 0., dt, .1))
        self.status = 'exit_release' if self.amount else 'exit_neutral'

    def write_exit(self, amount):
        bridge = self.bridge
        state = bridge['state']
        if not self.owns_exit(state):
            raise RuntimeError('Exit distance owner changed')
        current = struct.unpack_from('<d', state.modify.raw, 160)[0]
        if not math.isfinite(current) or abs(current - bridge['last']) > 1e-6:
            raise RuntimeError('Exit distance has another writer')
        saved = struct.unpack_from('<Q', state.modify.raw, 40)[0]
        if not saved and amount > .02:
            raise RuntimeError('Native TPS handoff preceded distance release')
        target = bridge['base'] - amount
        if abs(target) > 512. or not math.isfinite(target):
            raise ValueError('Exit release outside bounds')
        if current != target:
            struct.pack_into('<d', state.modify, 160, target)
        bridge['last'], self.amount = target, amount

    def restore_bridge(self):
        if self.bridge is None:
            return
        # An expired/replaced weak owner has no remaining write authority.
        live = tuple(ref() for ref in self.refs)
        current = tuple(self.mod._get_runtime())
        if (any(o is None for o in live) or live[:3] != current
                or character_movement(current[1]) != live[3]):
            self.bridge = None
            return
        if self.owns_exit(self.bridge['state']):
            self.write_exit(0.)
        self.bridge = None

    def tick(self, objects, mode, dt):
        if self.fault:
            return
        pc, pawn, camera, movement = objects
        allowed = permitted(self.mod, pc)
        if not allowed:
            self.restore_bridge()
            self.amount = self.entry = 0.
            self.active = self.had_slam = self.fallback = False
            self.last_raw = None
            self.status = 'suspended'
            return
        if mode == 'ThirdPerson' and not camera.CameraModeState.bIsTransitioning:
            self.observe_composition(camera)
            if self.channel is None and int(movement.MovementMode) == 1:
                self.calibrate(objects)
        active = (mode == 'ThirdPerson' and int(movement.MovementMode) == 3
                  and int(movement.CustomMovementMode) == 0 and self.channel is not None
                  and bool(pawn.IsPerformingGroundSlam()))
        if mode != 'GroundSlamExit':
            self.restore_bridge()
        if mode == 'GroundSlamExit' and self.had_slam:
            self.release_exit(dt)
        elif mode != 'ThirdPerson':
            self.amount = self.entry = 0.
            self.had_slam = False
            self.status = 'suspended'
        elif active:
            if not self.active:
                self.entry = 0.
                self.releasing = self.fallback = False
                self.wait = 0
                self.history.clear()
            self.had_slam = True
            limit = configured(self.mod)
            self.entry = approach(self.entry, limit, dt, .08)
            gap = self.trace(self.channel)
            envelope = 1. if gap is None else ground_envelope(max(0., gap - self.gap),
                                                              finite(movement.Velocity.Z), dt)
            desired = min(self.entry, limit * envelope)
            continuing = self.releasing
            self.releasing |= envelope < 1.
            self.amount = min(self.amount, desired) if continuing else desired
            if self.amount < .02:
                self.amount = 0.
            self.status = 'ground_release' if self.releasing else 'slam'
        else:
            # Preserve an unmatched native snapshot's first ordinary TPS write;
            # then use V3's tested transition-safe fallback.
            if not (self.fallback and self.mode == 'GroundSlamExit'):
                self.amount = approach(self.amount, 0., dt, .1 if self.fallback else .06)
            if not self.amount:
                self.had_slam = self.fallback = False
            self.status = 'tps_release' if self.amount else 'ready'
        self.active, self.mode = active, mode


def pre_frame(mod, args):
    if not runtime_updates.is_game_thread():
        return
    state = getattr(mod, '_ground_slam_distance_state', None)
    if state is not None:
        pc = state.refs[0]()
        if pc is None or configured(mod) == 0. or not permitted(mod, pc):
            shutdown_state(mod)
    mod._slam_distance_pending = True
    tick = perf_counter_ns()
    previous = getattr(mod, '_slam_distance_tick', None)
    mod._slam_distance_tick = tick
    delta = getattr(args, 'InDeltaTime', None) if args is not None else None
    if delta is None:
        delta = (tick - previous) / 1e9 if previous is not None else 0.
        mod._slam_distance_delta_source = 'owned_callback_elapsed'
    else:
        mod._slam_distance_delta_source = 'widget_InDeltaTime'
    mod._slam_distance_delta = max(0., min(.1, finite(delta)))


def step(mod, args):
    """One PRE of the serial/thread-filtered owned widget, as validated in V4."""
    if getattr(mod, '_slam_distance_stopping', False) or not runtime_updates.is_game_thread():
        return
    pre_frame(mod, args)
    try:
        pc, pawn, camera = mod._get_runtime()
        if any(o is None for o in (pc, pawn, camera)):
            shutdown_state(mod)
            return
        mode = str(camera.GetActorCameraMode(pawn))
        if mode == 'ThirdPerson' and mod._looks_like_first_person_fallback():
            mode = 'Default'
        update(mod, pc, pawn, camera, mode)
    finally:
        mod._slam_distance_pending = False


def start(mod):
    if not shutdown(mod):
        raise RuntimeError('Slam distance subscription cleanup incomplete')
    mod._slam_distance_stopping = False
    spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.PRE, 'bl4tps.ground_slam_distance')
    mod._slam_distance_spec = spec
    try:
        runtime_updates.add_hook(*spec, lambda obj, args, ret, func: step(mod, args))
        if not runtime_updates.has_hook(*spec):
            raise RuntimeError('Slam distance widget subscription unverified')
    except Exception:
        shutdown(mod)
        raise


def update(mod, pc, pawn, camera, mode):
    if not getattr(mod, '_slam_distance_pending', False) or not runtime_updates.is_game_thread():
        return
    mod._slam_distance_pending = False
    state = getattr(mod, '_ground_slam_distance_state', None)
    if configured(mod) == 0. or mod.tps_ground_slam_beta.value is not True:
        shutdown_state(mod)
        return
    try:
        if (any(o is None for o in (pc, pawn, camera))
                or bool(getattr(mod, '_vehicle_camera_active', False))):
            shutdown_state(mod)
            return
        movement = character_movement(pawn)
        if movement is None:
            shutdown_state(mod)
            return
        objects = (pc, pawn, camera, movement)
        if state is None or not state.matches(objects):
            if state is not None:
                state.restore_bridge()
            state = Distance(mod, objects)
            mod._ground_slam_distance_state = state
        state.tick(objects, mode, mod._slam_distance_delta)
    except Exception as exc:
        if state is not None:
            state.fault = True
            state.status = 'fault'
            state.amount = 0.
            state.restore_bridge()
        mod.logging.warning('[BL4ThirdPersonPOC.SlamDistance] DECLINED ' + str(exc))


def compensate(mod, pc, pawn, camera, values):
    state = getattr(mod, '_ground_slam_distance_state', None)
    frame = getattr(mod, '_camera_frame', None)
    if (state is None or state.fault or not runtime_updates.is_game_thread()
            or frame is None or frame.get('slam_distance_mode') != 'ThirdPerson'
            or not permitted(mod, pc) or state.mode != 'ThirdPerson'
            or (camera.CameraModeState.bIsTransitioning and not state.fallback)
            or not state.matches((pc, pawn, camera, character_movement(pawn)))):
        return values
    # A fresh mode proof in this setter scope also covers Root height off.
    baseline = values[0]
    wanted = baseline - state.amount
    state.last_raw = (baseline, wanted)
    if state.had_slam:
        state.history.append(state.last_raw)
        del state.history[:-1024]
    return wanted, values[1], values[2]


def shutdown_state(mod):
    state = getattr(mod, '_ground_slam_distance_state', None)
    if state is not None:
        if state.bridge is not None and not runtime_updates.is_game_thread():
            return False
        state.restore_bridge()
        state.amount = state.entry = 0.
        state.active = state.had_slam = False
        state.status = 'stopped'
    mod._ground_slam_distance_state = None
    mod._slam_distance_pending = False
    return True


def shutdown(mod):
    mod._slam_distance_stopping = True
    if not shutdown_state(mod):
        return False
    spec = getattr(mod, '_slam_distance_spec', None)
    if spec is not None:
        runtime_updates.remove_hook(*spec)
        if runtime_updates.has_hook(*spec):
            return False
        mod._slam_distance_spec = None
    mod._slam_distance_tick = None
    return True


def snapshot(mod):
    state = getattr(mod, '_ground_slam_distance_state', None)
    return dict(configured_cm=configured(mod), subscribed=getattr(mod, '_slam_distance_spec', None) is not None,
                delta_seconds=getattr(mod, '_slam_distance_delta', None),
                delta_source=getattr(mod, '_slam_distance_delta_source', None),
                status=state.status if state else 'waiting_for_runtime',
                extra_cm=state.amount if state else 0.,
                slam_active=state.active if state else False,
                ground_channel=state.channel if state else None)
