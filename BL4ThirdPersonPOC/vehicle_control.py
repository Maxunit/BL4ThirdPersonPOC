"""Optional camera-relative vehicle driving; validated runtime binding and native scalar-store boundary."""
from .omni.vehicle_handoff import allow_early_drive
from time import monotonic, perf_counter_ns
import math
import ctypes
import struct
import hashlib
import importlib
from collections import deque
from unrealsdk import hooks, make_struct, find_object
from unrealsdk.unreal import WeakPointer
from . import runtime_updates
KEY = 'bl4tps.vehicle_control'
TAG = '[BL4ThirdPersonPOC.VehicleControl]'
STICK_DEADZONE = 0.15
ANALOG_KEYS = {'left_x': 'Gamepad_LeftX', 'left_y': 'Gamepad_LeftY'}

def number(value):
    value = float(value)
    if not math.isfinite(value):
        raise RuntimeError('Nonfinite control value')
    return value

def components(value, names):
    result = {}
    for name in names:
        for spelling in (name, name.lower(), name.upper()):
            try:
                result[name] = number(getattr(value, spelling))
                break
            except AttributeError:
                continue
        else:
            raise RuntimeError('Missing component ' + name)
    return result

def identity(obj):
    obj = WeakPointer(obj)()
    if obj is None:
        raise RuntimeError('Expired SDK object')
    return {'address': hex(int(obj._get_address())), 'path': str(obj._path_name()), 'class': str(obj.Class._path_name())}

class Observer:

    def __init__(self, mod):
        self.mod = mod
        self.started = monotonic()
        self.next_sample = 0.0
        self.active = False
        self.registered = False
        self.errors = []
        self.error_count = 0
        self.finish_reason = None
        self.previous = None
        self.key_values = {}
        self.analog_keys = {}
        self.boost_key = None
        self.getter_metadata = {}
        self.spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, KEY + '.frame')

    def install(self):
        key_struct = find_object('ScriptStruct', '/Script/InputCore.Key')
        if key_struct is None or 'KeyName' not in {str(p.Name) for p in key_struct._properties()}:
            raise RuntimeError('InputCore.Key.KeyName unavailable; no observation hook installed')
        self.key_values = {name: make_struct('/Script/InputCore.Key', KeyName=name) for name in ('W', 'A', 'S', 'D')}
        analog_function = find_object('Function', '/Script/Engine.PlayerController.GetInputAnalogKeyState')
        if analog_function is None:
            raise RuntimeError('SDK analog getter unavailable; no hook installed')
        fields = {str(prop.Name): str(prop.Class.Name) for prop in analog_function._properties()}
        if fields.get('Key') != 'StructProperty' or fields.get('ReturnValue') != 'FloatProperty':
            raise RuntimeError('Analog getter parameter layout differs; no hook installed')
        self.getter_metadata = {'path': str(analog_function._path_name()), 'fields': fields}
        pc, _, _ = self.mod._get_runtime()
        if pc is None or not callable(getattr(pc, 'GetInputAnalogKeyState', None)):
            raise RuntimeError('Local analog getter unavailable; no hook installed')
        self.analog_keys = {label: make_struct('/Script/InputCore.Key', KeyName=name) for label, name in ANALOG_KEYS.items()}
        for key in self.analog_keys.values():
            number(pc.GetInputAnalogKeyState(key))
        self.boost_key = make_struct('/Script/InputCore.Key', KeyName='Gamepad_LeftShoulder')
        if runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Direction observation hook already owned')
        self.registered = True
        runtime_updates.add_hook(*self.spec, self.frame)
        if not runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Direction observation registration unverified')
        self.active = True

    def frame(self, obj, args, ret, func):
        return

    def stop(self):
        self.active = False
        if self.finish_reason is None:
            self.finish_reason = 'user_stop'
        if self.registered:
            if runtime_updates.has_hook(*self.spec):
                runtime_updates.remove_hook(*self.spec)
            if runtime_updates.has_hook(*self.spec):
                raise RuntimeError('Hook removal unverified; rerun to retry')
            self.registered = False
TRACE_HEADER = 160
SITES = ({'index': 0, 'writer_rva': 12428733, 'component_register': 'rsi', 'source_description': 'virtual getter receiver in RDI', 'original': 'f30f1186981900000f57c0f20f5a03', 'guard_rva': 12428669, 'guard': 'ff74544883be8009000000744a488b074889f9ff908010000084c00f857d0b0000488b07488d9c24800000004889f94889daff90800600000f57c0f20f5a4308f30f1186981900000f57c0f20f5a03f30f11869c1900008a86a119000034014108c5750d80be081d0000010f840e0b00', 'trace': '9c5052415049b822222222222222224983781001755bf049ff402049393075514983784001754af3410f104048f049ff4028c7868c03000000000000c786a403000000000000418b4068418b5058891406418b4070891406418b4078c7040600000000418b8080000000c704060000000041585a589d', 'trace_sha256': 'd5167f98f1be5f50612f5622ec1d3ba553e60b1bcd7e029f7173765d1dc4a738'},)
DRIVE_FIELDS = ('RawThrottleInput', 'ThrottleInput', 'RawBrakeInput', 'BrakeInput')
DRIVE_OFFSET_HEADER = dict(zip(DRIVE_FIELDS, (104, 112, 120, 128)))

def direction_command(keys, camera_yaw, actor_yaw, left_x=0.0, left_y=0.0):
    keys = {name: bool(keys.get(name, False)) for name in ('W', 'A', 'S', 'D')}
    x, y = (number(left_x), number(left_y))
    magnitude = math.hypot(x, y)
    if not math.isfinite(magnitude):
        raise RuntimeError('Nonfinite stick magnitude')
    any_keys = any(keys.values())
    if any_keys:
        right = float(keys['D']) - float(keys['A'])
        forward = float(keys['W']) - float(keys['S'])
        throttle = float(bool(right or forward))
        source = 'keyboard'
    elif magnitude > STICK_DEADZONE:
        right, forward = (x / magnitude, y / magnitude)
        throttle = min(1.0, (magnitude - STICK_DEADZONE) / (1.0 - STICK_DEADZONE))
        source = 'gamepad'
    else:
        right = forward = throttle = 0.0
        source = 'idle'
    any_input = source != 'idle'
    reference = number(camera_yaw) % 360.0 if any_input else None
    actor_yaw = number(actor_yaw) % 360.0
    target = (reference + math.degrees(math.atan2(right, forward))) % 360.0 if right or forward else actor_yaw
    return {'reference_yaw': reference, 'any_keys': any_keys, 'any_input': any_input, 'input_source': source, 'left_x': x, 'left_y': y, 'stick_magnitude_raw': magnitude, 'stick_magnitude_clamped': min(1.0, magnitude), 'right': right, 'forward': forward, 'target_yaw': target, 'throttle': throttle, 'key_mask': sum((int(keys[name]) << index for index, name in enumerate(('W', 'A', 'S', 'D'))))}

class DriveCapture(Observer):

    def __init__(self, mod):
        super().__init__(mod)
        self.buffer = None
        self.native_hooks = []
        self.chain = None
        self.reader = None
        self.native_state = {'native_accesses_added': 0}
        self.native_clean = True
        self.bindings = None
        self.references = None
        self.movement_layout = []
        self.disabled_reason = None
        self.native_records = []
        self.reserved = 0
        self.site_counts = [0]
        self.native_overrides = 0
        self.reference = None
        self.command = direction_command({}, None, 0.0)
        self.update_index = 0
        self.sessions = []
        self.drive_offsets = {}
        self.drive_validation = {}
        self.target = None
        self.source_metadata = {}
        self.original_disable = mod._on_disable_impl
        self.disable_wrapped = False

        def disable(*args, **kwargs):
            self.stop()
            return self.original_disable(*args, **kwargs)
        self.disable_wrapper = disable

    def current_bound(self):
        objects = self.mod._get_runtime()
        live = tuple((reference() for reference in self.references))
        if any((o is None for o in objects + live)):
            raise RuntimeError('Bound local vehicle lifetime expired')
        pc, pawn, manager = objects
        if bool(pc.bShowMouseCursor):
            return (None, 'WAITING_UI')
        if str(pawn.Class.Name) != 'OakVehicle':
            raise RuntimeError('Local pawn left the bound vehicle')
        movement = pawn.OakVehicleMovement
        current = objects + (movement,)
        if movement is None or tuple((int(o._get_address()) for o in current)) != self.bindings:
            raise RuntimeError('Bound local vehicle identity changed')
        if tuple((int(o._get_address()) for o in live)) != self.bindings:
            raise RuntimeError('Bound weak identity changed')
        return current

    def gate_off(self, reason):
        if self.buffer is not None:
            struct.pack_into('<Q', self.buffer, 64, 0)
            struct.pack_into('<Q', self.buffer, 16, 0)
        self.disabled_reason = reason

    def publish_command(self):
        struct.pack_into('<f', self.buffer, 72, self.command['target_yaw'])
        struct.pack_into('<Q', self.buffer, 80, self.update_index)
        struct.pack_into('<f', self.buffer, 88, self.command['throttle'])
        struct.pack_into('<f', self.buffer, 96, self.command['reference_yaw'] or 0.0)
        struct.pack_into('<ffII', self.buffer, 136, self.command['right'], self.command['forward'], self.command['key_mask'], int(self.command['any_input']))

    def frame(self, obj, args, ret, func):
        if self.active and self.buffer is not None:
            try:
                pc, pawn, manager, movement = self.current_bound()
                if (manager.CameraModeState.bIsTransitioning) and not allow_early_drive(self, pc, pawn, manager):
                    raise RuntimeError('Vehicle camera transition started')
                keys = {name: bool(pc.IsInputKeyDown(key)) for name, key in self.key_values.items()}
                analog = {name: number(pc.GetInputAnalogKeyState(key)) for name, key in self.analog_keys.items()}
                input_active = any(keys.values()) or math.hypot(analog['left_x'], analog['left_y']) > STICK_DEADZONE
                camera_yaw = components(pc.GetControlRotation(), ('Yaw',))['Yaw'] if input_active else None
                actor_yaw = components(pawn.K2_GetActorRotation(), ('Yaw',))['Yaw']
                previous_reference = self.reference
                self.command = direction_command(keys, camera_yaw, actor_yaw, analog['left_x'], analog['left_y'])
                self.reference = self.command['reference_yaw']
                self.target = self.command['target_yaw']
                self.update_index += 1
                self.publish_command()
                if (previous_reference is None) != (self.reference is None):
                    event = {'t': monotonic() - self.started, 'event': 'direction_input_started' if self.reference is not None else 'all_direction_input_released', 'reference_yaw': self.reference, 'native_reserved': struct.unpack_from('<Q', self.buffer, 8)[0]}
                    if len(self.sessions) < 512:
                        self.sessions.append(event)
            except Exception as exc:
                self.error_count += 1
                if len(self.errors) < 32:
                    self.errors.append({'t': monotonic() - self.started, 'where': 'direction/lifetime', 'error': repr(exc)})
                self.gate_off(repr(exc))
                self.active = False
                self.finish_reason = 'direction_or_context_error'
                self.mod.logging.error(TAG + ' INPUT_FAILED; original native control resumed; toggle OFF before retry')
                return
        super().frame(obj, args, ret, func)
        if not self.active:
            self.gate_off(self.disabled_reason or self.finish_reason or 'inactive')

    def validate_context(self, require_stopped=True):
        pc, pawn, manager = self.mod._get_runtime()
        if any((o is None for o in (pc, pawn, manager))) or str(pawn.Class.Name) != 'OakVehicle':
            raise RuntimeError('Run seated in a standing vehicle')
        if (manager.CameraModeState.bIsTransitioning) and not allow_early_drive(self, pc, pawn, manager):
            raise RuntimeError('Wait for vehicle entry to finish')
        movement = pawn.OakVehicleMovement
        if movement is None or (require_stopped and abs(number(movement.GetForwardSpeed())) > 30):
            raise RuntimeError('Stop vehicle before arming')
        self.movement_layout = []
        self.drive_offsets = {}
        self.drive_validation = {}
        self.source_metadata = {}
        objects = (pc, pawn, manager, movement)
        self.bindings = tuple((int(o._get_address()) for o in objects))
        self.references = tuple((WeakPointer(o) for o in objects))
        for cls in (movement.Class, *tuple(movement.Class._superfields())):
            for prop in cls._properties():
                offset = int(prop.Offset_Internal)
                name = str(prop.Name)
                if 6528 <= offset <= 6576 or name in ('RawSteeringInput', 'SteeringInput', *DRIVE_FIELDS):
                    field = {'name': name, 'offset': offset, 'type': str(prop.Class.Name)}
                    if field not in self.movement_layout:
                        self.movement_layout.append(field)
        expected = {'DesiredYaw': (6552, 'FloatProperty'), 'RawSteeringInput': (908, 'FloatProperty'), 'SteeringInput': (932, 'FloatProperty'), 'RawThrottleInput': (912, 'FloatProperty'), 'OakVehicleOwner': (6544, 'ObjectProperty')}
        for name, (offset, kind) in expected.items():
            matches = [f for f in self.movement_layout if f['name'] == name]
            if len(matches) != 1 or matches[0]['offset'] != offset or matches[0]['type'] != kind:
                raise RuntimeError('Reviewed native movement layout changed: ' + name)
        self.reader = importlib.import_module(self.mod.__name__ + '.ffyl_entry_blend').NativeBlendReader(self.mod, self.native_state, WeakPointer)
        self.chain = importlib.import_module(self.mod.__name__ + '.camera_hook_chain')
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        address = self.bindings[3]
        raw = self.reader.read(address + 6552, 4)
        if abs(struct.unpack('<f', raw)[0] - float(movement.DesiredYaw)) > 0.001:
            raise RuntimeError('Native/SDK DesiredYaw mismatch')
        for site in SITES:
            original = bytes.fromhex(site['original'])
            guard = bytes.fromhex(site['guard'])
            if original != bytes.fromhex('f30f1186981900000f57c0f20f5a03') or len(original) != 15:
                raise RuntimeError('Vehicle detour must end at reviewed instruction boundary')
            if guard[64:79] != original or guard[79:87] != bytes.fromhex('f30f11869c190000'):
                raise RuntimeError('Vehicle scalar pitch-store continuation changed')
            trace = bytes.fromhex(site['trace'])
            if self.chain.original_read(self.mod, self.base + site['guard_rva'], len(guard)) != guard:
                raise RuntimeError('Reviewed rotation-copy code changed at ' + hex(site['writer_rva']))
            if self.chain.original_read(self.mod, self.base + site['writer_rva'], len(original)) != original:
                raise RuntimeError('Reviewed write block changed at ' + hex(site['writer_rva']))
            if hashlib.sha256(trace).hexdigest() != site['trace_sha256'] or trace.count(b'"' * 8) != 1:
                raise RuntimeError('Audited native recorder changed')
        occupied = {908, 932}
        for name in DRIVE_FIELDS:
            matches = [f for f in self.movement_layout if f['name'] == name]
            if len(matches) != 1 or matches[0]['type'] != 'FloatProperty':
                raise RuntimeError('Unique reflected float drive field unavailable: ' + name)
            offset = matches[0]['offset']
            if not 768 <= offset < 2048 or offset % 4 or offset in occupied:
                raise RuntimeError('Invalid/overlapping reflected drive field: ' + name)
            occupied.add(offset)
            sdk_value = number(getattr(movement, name))
            native_value = number(struct.unpack('<f', self.reader.read(address + offset, 4))[0])
            if abs(native_value - sdk_value) > 0.001:
                raise RuntimeError('Native/SDK drive field mismatch: ' + name)
            self.drive_offsets[name] = offset
            self.drive_validation[name] = {'offset': offset, 'type': 'FloatProperty', 'native_value': native_value, 'sdk_value': sdk_value}
        self.current_bound()
        driver = getattr(pawn, 'DriverPawn', None)
        for name, obj in (('controller', pc), ('vehicle', pawn), ('driver', driver)):
            if obj is None:
                continue
            fields = []
            for cls in (obj.Class, *tuple(obj.Class._superfields())):
                for prop in cls._properties():
                    if int(prop.Offset_Internal) in (960, 5888):
                        field = {'name': str(prop.Name), 'offset': int(prop.Offset_Internal), 'type': str(prop.Class.Name)}
                        if field not in fields:
                            fields.append(field)
            self.source_metadata[name] = {'identity': identity(obj), 'fields': fields}

    def install(self):
        self.validate_context(require_stopped=False)
        pc, pawn, manager, movement = self.current_bound()
        address = self.bindings[3]
        super().install()
        self.buffer = ctypes.create_string_buffer(TRACE_HEADER)
        struct.pack_into('<QQQQ', self.buffer, 0, address, 0, 0, 0)
        self.target = components(pawn.K2_GetActorRotation(), ('Yaw',))['Yaw'] % 360.0
        self.command = direction_command({}, None, self.target)
        for name, header_offset in DRIVE_OFFSET_HEADER.items():
            struct.pack_into('<I', self.buffer, header_offset, self.drive_offsets[name])
        self.publish_command()
        struct.pack_into('<Q', self.buffer, 64, 1)
        self.native_clean = False
        for site in SITES:
            original = bytes.fromhex(site['original'])
            trace = bytes.fromhex(site['trace'])

            def builder(stub, trampoline, trace=trace):
                code = trace.replace(b'"' * 8, struct.pack('<Q', ctypes.addressof(self.buffer)))
                return (self.buffer, self.buffer, code + self.mod._native_absolute_jump(trampoline))
            item = self.chain.allocate(self.mod, self.base + site['writer_rva'], original, len(original), builder, 'vehicle yaw writer ' + hex(site['writer_rva']))
            self.native_hooks.append(item)
            self.chain.verify(self.mod, item)
        self.current_bound()
        struct.pack_into('<Q', self.buffer, 16, 1)

    def stop(self):
        self.active = False
        self.gate_off(self.disabled_reason or 'user_stop')
        for item in reversed(self.native_hooks):
            if item.get('_probe_retired'):
                continue
            self.chain.restore(self.mod, item)
            self.chain.retire(self.mod, item)
            item['_probe_retired'] = True
        self.native_clean = True
        super().stop()
        if self.disable_wrapped:
            current = self.mod._on_disable_impl
            if current is self.disable_wrapper:
                self.mod._on_disable_impl = self.original_disable
            elif current is not self.original_disable:
                raise RuntimeError('Disable wrapper ownership changed; cleanup incomplete')
            self.disable_wrapped = False

class Capture(DriveCapture):

    def __init__(self, mod):
        super().__init__(mod)
        self.lifecycle_events = deque(maxlen=1024)
        self.binding_history = deque(maxlen=128)
        self.phase = None
        self.candidate = None
        self.candidate_refs = None
        self.ready_frames = 0
        self.bind_count = 0
        self.retire_count = 0
        self.extra_hooks = []
        self.busy = False

    def event(self, name, **fields):
        row = {'t': monotonic() - self.started, 'event': name, **fields}
        self.lifecycle_events.append(row)
        self.mod.logging.warning(TAG + ' ' + name + ' ' + repr(fields))

    def eligible(self):
        objects = self.mod._get_runtime()
        if any((o is None for o in objects)):
            return (None, 'PAUSED_LOADING')
        pc, pawn, manager = objects
        if bool(pc.bShowMouseCursor):
            return (None, 'WAITING_UI')
        if str(pawn.Class.Name) != 'OakVehicle':
            return (None, 'ON_FOOT')
        if (bool(manager.CameraModeState.bIsTransitioning)) and not allow_early_drive(self, pc, pawn, manager):
            return (None, 'WAITING_TRANSITION')
        movement = pawn.OakVehicleMovement
        if movement is None:
            return (None, 'WAITING_MOVEMENT')
        if (not bool(self.mod._vehicle_camera_active)) and not allow_early_drive(self, pc, pawn, manager):
            return (None, 'WAITING_VEHICLE_CAMERA')
        target = manager.CameraModeInputs.ViewTarget
        if (target is None or int(target._get_address()) != int(pawn._get_address())) and not allow_early_drive(self, pc, pawn, manager):
            return (None, 'WAITING_VIEW_TARGET')
        objects = objects + (movement,)
        refs = tuple((WeakPointer(o) for o in objects))
        live = tuple((ref() for ref in refs))
        if any((o is None for o in live)):
            return (None, 'WAITING_LIFETIMES')
        addresses = tuple((int(o._get_address()) for o in objects))
        if tuple((int(o._get_address()) for o in live)) != addresses:
            return (None, 'WAITING_LIFETIMES')
        return ((addresses, refs), 'VEHICLE_READY')

    def pause(self, reason):
        self.gate_off(reason)
        if self.bindings is not None:
            self.event('CONTEXT_RETIRED', reason=reason, bindings=[hex(a) for a in self.bindings], native_overrides=struct.unpack_from('<Q', self.buffer, 40)[0], stale_writes=0)
            self.retire_count += 1
        self.bindings = None
        self.references = None
        self.reader = None
        self.reference = None
        self.previous = None
        self.candidate = self.candidate_refs = None
        self.ready_frames = 0
        if self.phase != reason:
            self.phase = reason
            self.event(reason)

    def fail(self, where, exc):
        self.gate_off(repr(exc))
        self.active = False
        self.finish_reason = 'lifecycle_error'
        self.error_count += 1
        if len(self.errors) < 32:
            self.errors.append({'t': monotonic() - self.started, 'where': where, 'error': repr(exc)})
        self.event('FAILED', where=where, error=repr(exc))

    def pre(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            candidate, reason = self.eligible()
            if candidate is None:
                self.pause(reason)
            elif self.bindings is not None:
                try:
                    self.current_bound()
                except RuntimeError:
                    self.pause('CONTEXT_CHANGED')
        except Exception as exc:
            self.fail('pre', exc)

    def restart_pre(self, obj, args, ret, func):
        if not self.active:
            return
        try:
            pc, _, _ = self.mod._get_runtime()
            if pc is not None and int(obj._get_address()) == int(pc._get_address()):
                self.pause('CLIENT_RESTART')
        except Exception as exc:
            self.fail('restart_pre', exc)

    def rebind(self):
        self.gate_off('validating_new_vehicle')
        self.validate_context(require_stopped=False)
        for key in self.analog_keys.values():
            number(self.mod._get_runtime()[0].GetInputAnalogKeyState(key))
        self.current_bound()
        for item in self.native_hooks:
            self.chain.verify(self.mod, item)
        struct.pack_into('<Q', self.buffer, 0, self.bindings[3])
        for name, header_offset in DRIVE_OFFSET_HEADER.items():
            struct.pack_into('<I', self.buffer, header_offset, self.drive_offsets[name])
        self.target = components(self.mod._get_runtime()[1].K2_GetActorRotation(), ('Yaw',))['Yaw'] % 360.0
        self.command = direction_command({}, None, self.target)
        self.publish_command()
        struct.pack_into('<Q', self.buffer, 64, 1)
        self.disabled_reason = None
        self.bind_count += 1
        self.binding_history.append({'t': monotonic() - self.started, 'bindings': [hex(a) for a in self.bindings], 'drive_field_validation': dict(self.drive_validation), 'native_validation': dict(self.native_state.get('native_reader_validation', {}))})
        self.phase = 'ACTIVE'
        self.event('RESUMED', bind_index=self.bind_count, bindings=[hex(a) for a in self.bindings])

    def frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        self.busy = True
        try:
            candidate, reason = self.eligible()
            if candidate is None:
                self.pause(reason)
                Observer.frame(self, obj, args, ret, func)
                return
            if self.bindings is not None:
                try:
                    self.current_bound()
                except RuntimeError:
                    self.pause('CONTEXT_CHANGED')
            if self.bindings is None:
                addresses, refs = candidate
                old_live = tuple((ref() for ref in self.candidate_refs or ()))
                same = self.candidate == addresses and len(old_live) == 4 and all((o is not None for o in old_live)) and (tuple((int(o._get_address()) for o in old_live)) == addresses)
                if same:
                    self.ready_frames += 1
                else:
                    self.candidate, self.candidate_refs = (addresses, refs)
                    self.ready_frames = 1
                if self.ready_frames < 2:
                    Observer.frame(self, obj, args, ret, func)
                    return
                self.rebind()
            super().frame(obj, args, ret, func)
            if self.active:
                self.current_bound()
                struct.pack_into('<Q', self.buffer, 16, 1)
        except Exception as exc:
            self.fail('frame/rebind', exc)
        finally:
            self.busy = False

    def install(self):
        super().install()
        plans = ((self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.PRE, KEY + '.lifecycle_pre', self.pre), (self.mod.CLIENT_RESTART_FUNCTION, hooks.Type.PRE, KEY + '.restart_pre', self.restart_pre))
        for path, kind, name, callback in plans:
            if runtime_updates.has_hook(path, kind, name):
                raise RuntimeError('Lifecycle hook already owned: ' + name)
            self.extra_hooks.append((path, kind, name))
            runtime_updates.add_hook(path, kind, name, callback)
            if not runtime_updates.has_hook(path, kind, name):
                raise RuntimeError('Lifecycle hook registration unverified: ' + name)
        self.bind_count = 1
        self.phase = 'ACTIVE'
        self.binding_history.append({'t': monotonic() - self.started, 'bindings': [hex(a) for a in self.bindings], 'drive_field_validation': dict(self.drive_validation), 'native_validation': dict(self.native_state.get('native_reader_validation', {}))})
        self.event('RESUMED', bind_index=1, bindings=[hex(a) for a in self.bindings])

    def stop(self):
        self.gate_off('user_stop')
        self.active = False
        for spec in list(self.extra_hooks):
            if runtime_updates.has_hook(*spec):
                runtime_updates.remove_hook(*spec)
            if runtime_updates.has_hook(*spec):
                raise RuntimeError('Lifecycle hook removal unverified; rerun to retry')
            self.extra_hooks.remove(spec)
        super().stop()


_owner = None

class RuntimeOwner:
    def __init__(self, mod):
        self.mod = mod
        self.child = None
        self.active = True
        self.spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, KEY+'.start')

    def install(self):
        if runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Vehicle control startup hook already owned')
        runtime_updates.add_hook(*self.spec, self.frame)
        if not runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Vehicle control startup hook unverified')

    def frame(self, obj, args, ret, func):
        if not self.active or self.child is not None:
            return
        try:
            pc, pawn, manager = self.mod._get_runtime()
            if (pc is None or pawn is None or manager is None or pc.bShowMouseCursor
                    or str(pawn.Class.Name) != 'OakVehicle'
                    or ((not self.mod._vehicle_camera_active or manager.CameraModeState.bIsTransitioning)
                        and not self.early_start(pc, pawn, manager))):
                return
            self.child = Capture(self.mod)
            self._starting = True
            try:
                self.child.install()
            finally:
                self._starting = False
        except Exception as exc:
            self.active = False
            if self.child is not None:
                self.child.gate_off(repr(exc))
                try:
                    self.child.stop()
                except Exception as cleanup_error:
                    self.mod.logging.error(TAG+' CLEANUP_FAILED '+repr(cleanup_error))
            self.mod.logging.error(TAG+' START_FAILED original control retained '+repr(exc))

    def early_start(self, pc, pawn, manager):
        sup = getattr(self.mod, '_player_omnidirectional_gameplay', None)
        worker = getattr(sup, 'vehicle', None)
        summon = getattr(worker, 'summon', None)
        return (worker is not None and worker.active and summon is not None and summon.active
                and summon.control[16] == 1 and summon.control[13] > 0
                and pc == summon.pc_ref() and pc.PersonalVehicleState.Vehicle == pawn
                and int(pawn._get_address()) == summon.control[17]
                and runtime_updates.is_game_thread())

    def stop(self):
        self.active = False
        if self.child is not None:
            self.child.stop()
        if runtime_updates.has_hook(*self.spec):
            runtime_updates.remove_hook(*self.spec)
        if runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Vehicle startup hook removal unverified')

def start(mod):
    global _owner
    if _owner is not None:
        if _owner.active:
            return
        if not shutdown():
            raise RuntimeError('Previous vehicle control ownership retained')
    _owner = RuntimeOwner(mod)
    try:
        _owner.install()
    except Exception:
        shutdown()
        raise

def shutdown():
    global _owner
    if _owner is None:
        return True
    try:
        _owner.stop()
    except Exception as exc:
        _owner.mod.logging.error(TAG+' STOP_FAILED '+repr(exc))
        return False
    _owner = None
    return True
