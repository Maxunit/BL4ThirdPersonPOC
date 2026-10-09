"""Validated post-reset BaseLocationOffset for the settled hidden-driver vehicle.
Native code and layout guards match the successful combined V3 test. No runtime
object is kept alive by the helper; gates close before pawn replacement.
"""
import ctypes
import struct
import hashlib
from unrealsdk import hooks
from unrealsdk.unreal import WeakPointer
from . import camera_hook_chain
from .ffyl_entry_blend import NativeBlendReader

RESET_RVA = 4558088
TAIL_RVA = 4558464
BODY_SIZE = 400
BODY_SHA256 = '76c9a82429e40bdf481fca6bd7c2bb6fc63fc438142c851084353eba698f16be'
ORIGINAL = bytes.fromhex('c786c80100000000000080a64c010000bf')
TRACE_CODE = bytes.fromhex('9c504152415349ba222222222222222249837a10010f85c90000004939320f85c000000049837a1801752a498b822000100048898688000000498b822800100048898690000000498b82300010004889869800000049c7c301000000f04d0fc15a084981fb0020000073794c89d848c1e0074d8d54022049897208488b868800000049894210488b869000000049894218488b869800000049894220488b86c000000049894228488b86c800000049894230488b86d000000049894238488b44245849894240488b463049894248488b463849894250488b46404989425849ffc34d891a415b415a589d')
TRACE_SHA256 = '72b3189745d093e5caec669d80ba7eb378b63189dffc1925d80ac73a295ff6ba'
CAP = 8192
STRIDE = 128
HEADER = 32

KEY = 'bl4tps.hidden_vehicle_camera'
TAG = '[BL4ThirdPersonPOC.HiddenVehicleCamera]'

class Owner:
    def __init__(self, mod):
        self.mod = mod
        self.thread = None
        self.buffer = None
        self.chain = camera_hook_chain
        self.native_hook = None
        self.native_clean = True
        self.reader = None
        self.native_validation = {'native_accesses_added': 0}
        self.binding = None
        self.camera_gate_reason = 'not_bound'
        self.last_command = None
        self.bind_count = self.retire_count = 0
        self.restart_spec = (mod.CLIENT_RESTART_FUNCTION, hooks.Type.PRE, KEY + '.restart')
        self.restart_registered = False
        self.faulted = False

    def event(self, name, **fields):
        self.mod.logging.info(TAG + ' ' + name + ' ' + repr(fields))

    def error(self, where, exc):
        self.mod.logging.error(TAG + ' ' + where + ' ' + repr(exc))

    def install(self):
        # Lazy installation is dispatched from the validated owned widget Tick.
        self.thread = int(self.mod._kernel32.GetCurrentThreadId())
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        self.reader = NativeBlendReader(self.mod, self.native_validation, WeakPointer)
        body = self.chain.original_read(self.mod, self.base + RESET_RVA, BODY_SIZE)
        if hashlib.sha256(body).hexdigest() != BODY_SHA256:
            raise RuntimeError('Reviewed camera reset method changed')
        if self.chain.original_read(self.mod, self.base + TAIL_RVA, len(ORIGINAL)) != ORIGINAL:
            raise RuntimeError('Reviewed reset tail changed')
        if hashlib.sha256(TRACE_CODE).hexdigest() != TRACE_SHA256 or TRACE_CODE.count(b'"'*8) != 1:
            raise RuntimeError('Audited native camera code changed')
        self.buffer = ctypes.create_string_buffer(HEADER + CAP*STRIDE + 24)
        struct.pack_into('<QQQQ', self.buffer, 0, 0, 0, 0, 1)
        def builder(stub, trampoline):
            code = TRACE_CODE.replace(b'"'*8, struct.pack('<Q', ctypes.addressof(self.buffer)))
            return self.buffer, self.buffer, code + self.mod._native_absolute_jump(trampoline)
        self.native_clean = False
        self.native_hook = self.chain.allocate(self.mod, self.base + TAIL_RVA, ORIGINAL,
            len(ORIGINAL), builder, 'Hidden-driver vehicle camera')
        self.chain.verify(self.mod, self.native_hook)
        if hooks.has_hook(*self.restart_spec):
            raise RuntimeError('Hidden vehicle restart observer already owned')
        hooks.add_hook(*self.restart_spec, self.restart_pre)
        self.restart_registered = hooks.has_hook(*self.restart_spec)
        if not self.restart_registered:
            raise RuntimeError('Hidden vehicle restart observer unverified')

    def update(self):
        if self.faulted:
            self.gate_off('faulted', True)
            return
        try:
            if self.buffer is None:
                pc, pawn, manager = self.mod._get_runtime()
                if any(o is None for o in (pc, pawn, manager)):
                    return
                character = getattr(pc, 'OakPlayerCharacter', None)
                if (str(pawn.Class.Name) != 'OakVehicle' or character is None
                        or not bool(character.bHidden) or not self.mod._vehicle_camera_active
                        or manager.CameraModeState.bIsTransitioning):
                    return
                self.install()
            self.update_native_camera()
        except Exception as exc:
            self.gate_off('camera_update_error', True)
            self.faulted = True
            self.error('FAULT', exc)

    def close(self):
        self.gate_off('mod_disable', True)
        try:
            if self.native_hook is not None and not self.native_clean:
                self.chain.restore(self.mod, self.native_hook)
                self.chain.retire(self.mod, self.native_hook)
            self.native_clean = True
            if self.restart_registered:
                if hooks.has_hook(*self.restart_spec):
                    hooks.remove_hook(*self.restart_spec)
                if hooks.has_hook(*self.restart_spec):
                    return False
                self.restart_registered = False
            return True
        except Exception as exc:
            self.error('CLEANUP_FAILED', exc)
            return False

    def gate_off(self, reason, retire=False):
        self.camera_gate_reason = reason
        if self.buffer is not None:
            struct.pack_into('<Q', self.buffer, 16, 0)
        if retire and self.binding is not None:
            self.event('CAMERA_CONTEXT_RETIRED', reason=reason, identity=[hex(x) for x in self.binding[0]])
            self.retire_count += 1
            self.binding = None
            self.reader = None
            self.last_command = None

    def restart_pre(self, obj, args, ret, func):
        if self.thread is not None and int(self.mod._kernel32.GetCurrentThreadId()) != self.thread:
            return
        try:
            pc, _, _ = self.mod._get_runtime()
            if pc is not None and int(obj._get_address()) != int(pc._get_address()):
                return
            self.gate_off('CLIENT_RESTART', True)
        except Exception as exc:
            self.gate_off('restart_read_error', True)
            self.error('restart', exc)

    def update_native_camera(self):
        from .vehicle_camera import values
        if self.buffer is None:
            return
        pc, pawn, manager = self.mod._get_runtime()
        if any((o is None for o in (pc, pawn, manager))):
            self.gate_off('runtime_unavailable', True)
            return
        state = manager.CameraModeState
        inputs = manager.CameraModeInputs
        character = getattr(pc, 'OakPlayerCharacter', None)
        target = None if inputs is None else inputs.ViewTarget
        hidden = character is not None and bool(character.bHidden)
        eligible = state is not None and str(pawn.Class.Name) == 'OakVehicle' and hidden and bool(self.mod._vehicle_camera_active) and (target is not None) and (int(target._get_address()) == int(pawn._get_address()))
        if not eligible:
            self.gate_off('not_hidden_driver_vehicle', True)
            return
        if bool(state.bIsTransitioning):
            self.gate_off('entry_transition', True)
            return
        objects = (pc, pawn, manager, state)
        addresses = tuple((int(o._get_address()) for o in objects))
        live = None if self.binding is None else tuple((ref() for ref in self.binding[1]))
        valid = self.binding is not None and self.binding[0] == addresses and all((x is not None for x in live)) and (tuple((int(x._get_address()) for x in live)) == addresses)
        if not valid:
            self.gate_off('runtime_identity_changed', True)
            reader = NativeBlendReader(self.mod, self.native_validation, WeakPointer)
            props = {}
            for cls in (state.Class, *tuple(state.Class._superfields())):
                for prop in cls._properties():
                    props.setdefault(str(prop.Name), int(prop.Offset_Internal))
            for name, offset in [('BaseLocationOffset', 136), ('CameraLocationOffset', 192), ('POV', 48)]:
                if props.get(name) != offset:
                    raise RuntimeError('Reviewed camera layout changed: ' + name)
            vtable = struct.unpack('<Q', reader.read(addresses[3], 8))[0]
            if not self.base <= vtable < self.base + 834191360 - 680:
                raise RuntimeError('State vtable outside reviewed image')
            if struct.unpack('<Q', reader.read(vtable + 672, 8))[0] != self.base + RESET_RVA:
                raise RuntimeError('Camera reset method changed')
            refs = tuple((WeakPointer(o) for o in objects))
            if any((ref() is None for ref in refs)):
                raise RuntimeError('Vehicle weak identities expired')
            self.binding = (addresses, refs)
            self.reader = reader
            self.bind_count += 1
            self.event('CAMERA_RESUMED', bind_index=self.bind_count, identity=[hex(x) for x in addresses])
        self.reader.validate_lifetimes()
        delta = values(self.mod)
        command = (addresses[3], delta)
        if command != self.last_command:
            self.gate_off('command_update')
            struct.pack_into('<ddd', self.buffer, HEADER + CAP * STRIDE, *delta)
            struct.pack_into('<Q', self.buffer, 0, addresses[3])
            struct.pack_into('<Q', self.buffer, 24, 1)
            self.last_command = command
            self.event('CAMERA_VALUES', delta=delta)
        enabled = any((abs(x) > 0.0001 for x in delta))
        struct.pack_into('<Q', self.buffer, 16, int(enabled))
        self.camera_gate_reason = 'active' if enabled else 'default_values'

