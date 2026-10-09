"""Owned vehicle XYZ offsets; entry progress plus guarded hidden-driver post-reset offsets."""
import math
from unrealsdk import hooks, make_struct
from unrealsdk.unreal import WeakPointer
from .ffyl_entry_blend import NativeBlendReader
from . import runtime_updates
from .hidden_vehicle_camera import Owner as HiddenVehicleOwner

DEFAULTS = (0, 0, 0)
RANGES = ((-350, 350), (-200, 200), (-200, 200))
PRESETS = {'STANDARD': DEFAULTS, 'NEAR': (225, 0, -55), 'FAR': (-225, 0, -55)}
IDENTIFIER = 'bl4_third_person_poc.vehicle_offset'
_owner = None


def vector(value):
    result = tuple(float(getattr(value, key)) for key in ('X', 'Y', 'Z'))
    if not all(math.isfinite(v) for v in result):
        raise RuntimeError('Nonfinite vehicle offset')
    return result


def same(a, b):
    return all(abs(x-y) < .0001 for x,y in zip(a,b))


def values(mod):
    result = tuple(float(getattr(mod, 'vehicle_offset_'+axis).value) for axis in 'xyz')
    if any(not math.isfinite(v) or not lo <= v <= hi for v,(lo,hi) in zip(result,RANGES)):
        raise RuntimeError('Vehicle settings outside bounds')
    return result


class Owner:
    def __init__(self, mod):
        self.mod = mod
        self.binding = None
        self.ready_frames = 0
        self.last_written = None
        self.reader = None
        self.native_identity = None
        self.last_fraction = None
        self.reported_values = None
        self.done = False
        self.faulted = False
        self.busy = False
        self.registered = False
        self.hidden = None
        self.hidden_registered = False
        self.reader_state = {'native_accesses_added': 0}

    def runtime(self):
        pc,pawn,manager = self.mod._get_runtime()
        if any(o is None for o in (pc,pawn,manager)):
            return None
        state,inputs = manager.CameraModeState,manager.CameraModeInputs
        if state is None or inputs is None:
            return None
        objects = (pc,pawn,manager,state)
        refs = tuple(WeakPointer(o) for o in objects)
        live = tuple(ref() for ref in refs)
        identity = tuple(int(o._get_address()) for o in objects)
        if any(o is None for o in live) or tuple(int(o._get_address()) for o in live) != identity:
            return None
        target = inputs.ViewTarget
        vehicle = (str(pawn.Class.Name) == 'OakVehicle' and bool(self.mod._vehicle_camera_active)
                   and target is not None and int(target._get_address()) == identity[1])
        return objects,identity,refs,vehicle

    def matches(self, runtime):
        if self.binding is None or runtime is None or runtime[1] != self.binding[0]:
            return False
        live = tuple(ref() for ref in self.binding[1])
        return all(o is not None for o in live) and tuple(int(o._get_address()) for o in live) == runtime[1]

    def retire(self):
        self.binding = None
        self.ready_frames = 0
        self.last_written = None
        self.reader = None
        self.native_identity = None
        self.last_fraction = None
        self.reported_values = None
        self.done = False

    def restore(self, runtime):
        if not self.matches(runtime) or not runtime[3]:
            self.retire()
            return True
        if self.last_written is None:
            return True
        state = runtime[0][3]
        current = vector(state.CameraLocationOffset)
        if not same(current, DEFAULTS) and not same(current, self.last_written):
            return False
        if not same(current, DEFAULTS):
            state.CameraLocationOffset = make_struct('Vector', X=0.,Y=0.,Z=0.)
            if not same(vector(state.CameraLocationOffset), DEFAULTS):
                return False
        self.last_written = None
        return True

    def alpha(self, state):
        if self.done or not bool(state.bIsTransitioning):
            # First configuration may happen long after the entry blend ended.
            # Settled vehicle offsets need no native entry-progress reader.
            self.done = True
            self.reader = None
            return 1.
        if self.reader is None:
            self.reader = NativeBlendReader(self.mod,self.reader_state,WeakPointer)
        sample = self.reader.snapshot()
        if sample.get('status') != 'ok':
            raise RuntimeError('Native vehicle progress unavailable')
        identity = tuple(sample.get(k) for k in ('runtime','control','definition'))
        if any(v is None for v in identity) or (self.native_identity is not None and identity != self.native_identity):
            raise RuntimeError('Native vehicle entry runtime changed')
        self.native_identity = identity
        fraction = sample.get('linear_time_fraction')
        if fraction is None:
            if bool(state.bIsTransitioning):
                raise RuntimeError('Vehicle entry duration unavailable')
            fraction = 1.
        if not math.isfinite(fraction) or not 0 <= fraction <= 1 or (self.last_fraction is not None and fraction+.0001 < self.last_fraction):
            raise RuntimeError('Invalid vehicle entry progress')
        self.last_fraction = fraction
        self.done = fraction >= 1
        if self.done:
            self.reader = None  # No native progress polling during settled driving.
        return fraction*fraction*(3-2*fraction)

    def pre(self, obj, args, ret, func):
        if self.hidden is not None and not runtime_updates.is_game_thread():
            return
        if self.busy:
            return
        self.busy = True
        try:
            runtime = self.runtime()
            if self.faulted:
                self.restore(runtime)
                return
            requested = values(self.mod)
            if requested == DEFAULTS:
                if not self.restore(runtime):
                    raise RuntimeError('Foreign vehicle offset preserved')
                self.retire()
                return
            if not self.matches(runtime):
                self.retire()
            if runtime is None or not runtime[3]:
                self.retire()
                return
            objects,identity,refs,vehicle = runtime
            state = objects[3]
            if self.binding is None:
                self.binding = (identity,refs)
            current = vector(state.CameraLocationOffset)
            if same(current,DEFAULTS):
                self.ready_frames += 1
            elif self.last_written is not None and same(current,self.last_written):
                pass
            elif self.last_written is not None:
                raise RuntimeError('Foreign vehicle offset writer preserved')
            else:
                self.ready_frames = 0
            if self.ready_frames < 3:
                return
            alpha = self.alpha(state)
            injected = tuple(v*alpha for v in requested)
            self.last_written = injected
            state.CameraLocationOffset = make_struct('Vector',X=injected[0],Y=injected[1],Z=injected[2])
            if not same(vector(state.CameraLocationOffset),injected):
                raise RuntimeError('Vehicle offset readback differs')
            if self.done and self.reported_values != requested:
                self.reported_values = requested
                self.mod.logging.info(
                    '[BL4ThirdPersonPOC.VehicleCamera] OFFSET_APPLIED values='
                    + repr(requested) + ' settled=True'
                )
        except Exception as exc:
            if not self.faulted:
                self.mod.logging.error('[BL4ThirdPersonPOC.VehicleCamera] FAULT '+repr(exc))
            self.faulted = True
        finally:
            self.busy = False

    def hidden_frame(self, obj, args, ret, func):
        if self.hidden is not None:
            self.hidden.update()

    def install(self):
        self.hidden = HiddenVehicleOwner(self.mod)
        spec_hidden = (self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, IDENTIFIER + '.hidden')
        self.hidden_registered = True
        runtime_updates.add_hook(*spec_hidden, self.hidden_frame)
        if not runtime_updates.has_hook(*spec_hidden):
            raise RuntimeError('Hidden vehicle updater registration unverified')
        spec = (self.mod.FIRST_PERSON_ANIM_HOOK,hooks.Type.PRE,IDENTIFIER)
        if hooks.has_hook(*spec):
            raise RuntimeError('Vehicle hook already owned')
        self.registered = True
        hooks.add_hook(*spec,self.pre)
        if not hooks.has_hook(*spec):
            raise RuntimeError('Vehicle hook registration unverified')

    def close(self):
        if self.hidden is not None and not self.hidden.close():
            return False
        if self.hidden_registered:
            spec_hidden = (self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, IDENTIFIER + '.hidden')
            if runtime_updates.has_hook(*spec_hidden):
                runtime_updates.remove_hook(*spec_hidden)
            if runtime_updates.has_hook(*spec_hidden):
                return False
            self.hidden_registered = False
        if not self.restore(self.runtime()):
            return False
        spec = (self.mod.FIRST_PERSON_ANIM_HOOK,hooks.Type.PRE,IDENTIFIER)
        if self.registered:
            if hooks.has_hook(*spec):hooks.remove_hook(*spec)
            if hooks.has_hook(*spec):return False
            self.registered = False
        self.retire()
        return True


def start(mod):
    global _owner
    if not shutdown():
        raise RuntimeError('Vehicle owner restoration incomplete')
    _owner = Owner(mod)
    try:
        _owner.install()
    except Exception:
        shutdown()
        raise


def shutdown():
    global _owner
    if _owner is None:
        return True
    if not _owner.close():
        return False
    _owner = None
    return True
