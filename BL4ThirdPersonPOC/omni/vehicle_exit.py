"""Reviewed vehicle transition detours; owned by the Omni supervisor.

Native instruction templates retain their exact caller/object/vtable/thread
guards. Ring buffers are bounded scratch storage, reset only with gates closed.
No diagnostics subscription, physical key query, camera or velocity setter.
"""
import ctypes
from time import perf_counter_ns
import hashlib
import importlib
from itertools import islice
import math
import struct
import sys
from unrealsdk.unreal import WeakPointer
from ..build_gate import REVIEWED_BUILD as EXPECTED_BUILD
from . import hitch
TARGET_RVA, BODY_RVA, BODY_SIZE = 0x12D8432, 0x12D723A, 0x14DB
BODY_HASH = '682bc8073c49d612a1da0addfb87fb97ff07f0088fdfc0ecfd279520c0a755a2'
ORIGINAL = bytes.fromhex('488b831017000066440f288c2420020000')
CONTINUATION = bytes.fromhex('66440f168c2428020000')
PC_TABLE, VEHICLE_TABLE, CHARACTER_TABLE, MOVEMENT_TABLE = 0xB98A160, 0xB8D0A80, 0xB6F4080, 0xB709670
CAPACITY, RECORD_SIZE, MAX_SAMPLES = 64, 128, 2048
SENTINEL = b'\x11' * 8
PREFIX = bytes.fromhex('9c504152415349ba111111111111111149833a010f8578010000493b5a180f856e010000654c8b1c25480000004d3b5a100f855b010000498b42084c8b184d3b5a500f854a0100004c8b98a83900004939db0f853a0100004c8b98d00300004939db740a4d3b5a200f85240100004c8b1b4d3b5a580f85170100004c8b9b101700004d3b5a200f8506010000498b03493b42680f85f9000000498b8350680000493b42280f85e8000000493b83300400000f85db0000004c8b184d3b5a600f85ce0000004d8b5a404983fb400f83c000000049c1e3074d035a38498b420849894308498b421849894310498b422049894318498b422849894320488b84244002000049894328488b84244802000049894330488b84245002000049894338498b4230488984244802000049894340498b424849894348498b427049894350498b4208488b801004000049894358488b84242003000049894360488b84242803000049894368488b84243003000049894370498b4208488b80d00300004989437849c7030100000049ff424049c70200000000415b415a589d')
PREFIX_HASH = '77205102eaa3dbb638cc18b29b6f0f845335df61df79fa912ff4eeef99a93d81'
BODY_MOVE = bytes.fromhex('5657534881eca0000000660f29bc2490000000')
BODY_MOVE_PROLOGUE = bytes.fromhex('5657534881eca0000000660f29bc2490000000660f29b42480000000')
LAUNCH = bytes.fromhex('56574883ec2880b9881c0000007546')
GAP_RVA, GAP_REGION_RVA, GAP_REGION_SIZE = 0x2E2E03, 0x2E2800, 0x800
GAP_ORIGINAL = bytes.fromhex('488d5c24604889f14989d84531c9')
GAP_CONTINUATION = bytes.fromhex('ff90e80400004889d9e8dbc94d04')
GAP_PREFIX = bytes.fromhex('488d5c24604889f14989d84531c99c504152415349ba111111111111111149833a010f857a010000493b4a080f857001000065488b042548000000493b42100f855d010000498b4238488b40404d8b5a3049ffc34c39d80f8545010000498b42404c8b184d3b5a600f85340100004c8b98d00300004d3b5a480f8523010000498b42484c8b184d3b5a680f85120100004c8b98506800004939cb0f85020100004c8b98300400004939cb0f85f2000000488b01493b42500f85e500000080b991020000030f85d800000080b992020000000f85cb000000488b8110010000493b42180f85ba0000004c8b184d3b5a580f85ad0000004d8b5a284981fb000100000f839500000049c1e3074d035a20498b42404989430849894b10498b421849894318498b0049894320498b400849894328498b401049894330498b401849894338498b42184c8d8040020000498b0049894340498b400849894348498b401049894350498b401849894358488b0249894360488b420849894368488b421049894370498b4238488b40404989437849c7030100000049ff4228eb0749c70200000000415b415a589d')
GAP_PREFIX_HASH = 'f6d157e265f21be8c51eddc40d8d84292fd6a47713a520433ffd31e4555c873d'
GAP_PREFIX_SIZE = 424
GAP_CAPACITY = 256
GAP_REGION_HASH = '4ca0953788094c90601cd257ea4155c4a181b44b24b6b4d6049e5f0240192228'
CALL_GUARDS = {0x12D85D0: 'ff90e8040000', 0x12D870F: 'ff9088060000'}

def absolute_jump(target):
    return b'\xff\x25\0\0\0\0' + struct.pack('<Q', target)

def stub(control, trampoline):
    if (len(PREFIX) != 408 or PREFIX.count(SENTINEL) != 1
            or hashlib.sha256(PREFIX).hexdigest() != PREFIX_HASH):
        raise RuntimeError('Reviewed native body-yaw template differs')
    return PREFIX.replace(SENTINEL, struct.pack('<Q', control)) + absolute_jump(trampoline)

def live(obj):
    obj = None if obj is None else WeakPointer(obj)()
    if obj is None or obj.Class is None: raise RuntimeError('SDK object expired')
    address = int(obj._get_address())
    if not 0x10000 <= address < (1 << 47): raise RuntimeError('SDK object address outside user range')
    return obj, address

def properties(schema):
    parents = list(islice(schema._superfields(), 25))
    if len(parents) > 24: raise RuntimeError('Reflection inheritance bound exceeded')
    found = {}
    for parent in (schema, *parents):
        props = list(islice(parent._properties(), 4097))
        if len(props) > 4096: raise RuntimeError('Reflection field bound exceeded')
        for prop in props: found.setdefault(str(prop.Name), prop)
    return found

def field(schema, name, kind, offset, size):
    prop = properties(schema).get(name)
    if (prop is None or str(prop.Class.Name) != kind or int(prop.Offset_Internal) != offset
            or int(prop.ElementSize) != size or int(prop.ArrayDim) != 1):
        raise RuntimeError('Measured field layout differs: ' + name)
    return prop

def controller_layout(pc):
    field(pc.Class, 'Pawn', 'ObjectProperty', 0x3D0, 8)
    rotation = field(pc.Class, 'ControlRotation', 'StructProperty', 0x408, 24)
    if str(rotation.Struct._path_name()) != '/Script/CoreUObject.Rotator':
        raise RuntimeError('Measured controller Rotator differs')
    members = {name.lower(): prop for name, prop in properties(rotation.Struct).items()}
    for name, offset in (('pitch', 0), ('yaw', 8), ('roll', 16)):
        prop = members.get(name)
        if (prop is None or str(prop.Class.Name) != 'DoubleProperty'
                or int(prop.Offset_Internal) != offset or int(prop.ElementSize) != 8
                or int(prop.ArrayDim) != 1): raise RuntimeError('Measured rotation member differs')
    personal = field(pc.Class, 'PersonalVehicleState', 'StructProperty', 0x3920, 544)
    if str(personal.Struct._path_name()) != '/Script/OakGame.PersonalVehicleState':
        raise RuntimeError('Measured personal vehicle state differs')
    field(personal.Struct, 'Vehicle', 'ObjectProperty', 0x88, 8)

def components(value, names):
    values = {name: float(getattr(value, name)) for name in names}
    if not all(math.isfinite(v) for v in values.values()): raise RuntimeError('Nonfinite SDK value')
    return values

def yaw_bits(value):
    value = float(value)
    if not math.isfinite(value): raise RuntimeError('Nonfinite facing yaw')
    return struct.unpack('<Q', struct.pack('<d', (value + 180.0) % 360.0 - 180.0))[0]

class LocalMemoryReader:
    """Private read-only Win64 API bindings; no GIL handoff per tiny syscall.

    PyDLL retains the GIL. On Windows x64 the exported API uses the unified
    x64 ABI, so these fully typed calls are compatible. Never use on Win32.
    This owns its function objects and changes no production ctypes binding.
    Accessibility is checked afresh for every read; no memory/page cache.
    """
    def __init__(self, mod):
        if sys.platform != 'win32' or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError('Private reader requires Windows x64')
        self.info_type = mod._MEMORY_BASIC_INFORMATION
        if ctypes.sizeof(self.info_type) != 48:
            raise RuntimeError('Reviewed Win64 memory information layout differs')
        from BL4ThirdPersonPOC.native_memory import _native_require_readable
        self.require_readable = _native_require_readable
        self.api = ctypes.PyDLL('kernel32', handle=mod._kernel32._handle, use_last_error=True)
        self.api.GetCurrentProcess.argtypes = ()
        self.api.GetCurrentProcess.restype = ctypes.c_void_p
        self.api.VirtualQuery.argtypes = (ctypes.c_void_p, ctypes.POINTER(self.info_type), ctypes.c_size_t)
        self.api.VirtualQuery.restype = ctypes.c_size_t
        self.api.ReadProcessMemory.argtypes = (ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t))
        self.api.ReadProcessMemory.restype = ctypes.c_int32
        self.process = self.api.GetCurrentProcess()
        if not self.process: raise RuntimeError('Private current-process handle unavailable')
        self.stats = dict(backend='private_Win64_PyDLL', queries=0, reads=0,
            read_total_ns=0, read_max_ns=0)

    def query(self, address):
        info = self.info_type()
        returned = self.api.VirtualQuery(ctypes.c_void_p(address), ctypes.byref(info), ctypes.sizeof(info))
        self.stats['queries'] += 1
        if int(returned) != ctypes.sizeof(info):
            raise RuntimeError('Private VirtualQuery failed or incomplete')
        return info

    def read(self, address, size):
        if not 0x10000 <= address < address + size < (1 << 47) or not 1 <= size <= 0x20000:
            raise RuntimeError('Diagnostic read outside bounds')
        started = perf_counter_ns()
        try:
            self.require_readable(address, size, 'vehicle exit body yaw', self.query)
            buffer = ctypes.create_string_buffer(size)
            count = ctypes.c_size_t()
            success = self.api.ReadProcessMemory(self.process, ctypes.c_void_p(address),
                buffer, size, ctypes.byref(count))
            self.stats['reads'] += 1
            if not success or int(count.value) != size:
                raise RuntimeError('Private ReadProcessMemory failed or incomplete')
            return bytes(buffer.raw)
        finally:
            elapsed = perf_counter_ns() - started
            self.stats['read_total_ns'] += elapsed
            self.stats['read_max_ns'] = max(self.stats['read_max_ns'], elapsed)

class ExitFacing:
    def validate_gap_component(self):
        movement = self.movement_ref()
        if movement is None: raise RuntimeError('Gap movement expired')
        self.review_field(movement.Class, 'UpdatedComponent', 'ObjectProperty', 0x110, 8)
        self.review_field(movement.Class, 'MovementMode', 'ByteProperty', 0x291, 1)
        self.review_field(movement.Class, 'CustomMovementMode', 'ByteProperty', 0x292, 1)
        component, pointer = live(movement.UpdatedComponent)
        if (self.u64(self.movement_address + 0x110) != pointer
                or self.u64(pointer) != self.base + 0xA824FC0
                or self.u64(self.base + 0xA824FC0 + 0x510) != self.base + 0x28BA36):
            raise RuntimeError('Reviewed gap UpdatedComponent/dispatch differs')
        rotation = struct.unpack('<4d', self.read(pointer + 0x240, 32))
        if not all(math.isfinite(v) for v in rotation) or not 0.99 < sum(v*v for v in rotation) < 1.01:
            raise RuntimeError('Gap root quaternion invalid')
        return component, pointer

    def review_field(self, schema, name, kind, offset, size):
        """Keep immutable type-layout review outside the repeated frame work.

        The live UClass identity is the cache key, never a class name or a heap
        object's numeric address. A different/expired class needs fresh review.
        Native owner/component identities and links are checked separately on
        every frame. No runtime object pointer or mutable state is cached here.
        """
        signature = (name, kind, offset, size)
        self.layout_cache[:] = [(ref, fields) for ref, fields in self.layout_cache if ref() is not None]
        for ref, fields in self.layout_cache:
            if ref() == schema:
                if signature not in fields:
                    field(schema, name, kind, offset, size)
                    fields.add(signature)
                    self.performance['layout_reviews'] += 1
                return
        ref = WeakPointer(schema)
        if ref() != schema: raise RuntimeError('Reviewed field class expired')
        field(schema, name, kind, offset, size)
        self.layout_cache.append((ref, {signature}))
        self.performance['layout_reviews'] += 1

    def validate_gap_initial(self):
        if self.image.code_rva(self.base + GAP_RVA) != GAP_RVA:
            raise RuntimeError('Gap caller outside executable image')
        if hashlib.sha256(self.read(self.base + GAP_REGION_RVA, GAP_REGION_SIZE)).hexdigest() != GAP_REGION_HASH:
            raise RuntimeError('Reviewed TurnState context differs or is patched')
        if self.read(self.base + GAP_RVA, len(GAP_ORIGINAL) + len(GAP_CONTINUATION)) != GAP_ORIGINAL + GAP_CONTINUATION:
            raise RuntimeError('Reviewed TurnState call setup differs')
        if (len(GAP_PREFIX) != GAP_PREFIX_SIZE or GAP_PREFIX.count(SENTINEL) != 1
                or not GAP_PREFIX.startswith(GAP_ORIGINAL)
                or hashlib.sha256(GAP_PREFIX).hexdigest() != GAP_PREFIX_HASH):
            raise RuntimeError('Reviewed gap instruction template differs')
        component, self.component_address = self.validate_gap_component()
        self.component_ref = WeakPointer(component)
        self.report['scope'].update(gap_target_rva=hex(GAP_RVA),
            gap_context_sha256=GAP_REGION_HASH, component=hex(self.component_address))

    def verify_gap(self):
        if self.gap_hook is None: raise RuntimeError('Owned gap patch missing')
        if self.read(self.base + GAP_RVA, len(GAP_ORIGINAL) + len(GAP_CONTINUATION)) != self.gap_hook['patch'] + GAP_CONTINUATION:
            raise RuntimeError('Owned gap patch/call continuation changed')
        component, pointer = self.validate_gap_component()
        if component != self.component_ref() or pointer != self.component_address:
            raise RuntimeError('Gap UpdatedComponent changed')

    def gap_publish(self, pc, pawn, camera, movement):
        air = self.gap_air_owner()
        normal = (air is not None and not pc.bShowMouseCursor and self.mod._third_person_enabled
            and self.mod._third_person_pushed and not any(bool(getattr(self.mod, name, False))
                for name in ('_ads_active', '_shop_camera_active', '_ladder_active', '_slide_active')))
        if str(pawn.Class.Name) == 'OakVehicle':
            if not self.gap_seat_open:
                self.gap_control[6] = int(self.control[8])
            self.gap_seat_open = True
            self.gap_control[0] = int(normal and bool(self.control[0]))
            self.gap_phase = 'WAITING_OWN_EXIT' if self.gap_control[0] else 'INACTIVE'
            return
        ticket = air.ticket if air is not None else None
        eligible = (self.gap_seat_open and normal and pawn == self.pawn_ref()
            and self.consumed == int(self.gap_control[6]) + 1
            and isinstance(ticket, dict) and ticket.get('confirmed') is True
            and ticket['character']() == pawn and ticket['vehicle']() == self.vehicle_ref()
            and pc.Pawn == pawn and int(movement.MovementMode) == 3
            and int(movement.CustomMovementMode) == 0 and not pawn.IsCharacterDashing()
            and not movement.bWantsToDash and not camera.CameraModeState.bIsTransitioning
            and not any(bool(getattr(movement, name)) for name in (
                'bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting'))
            and camera.CameraModeInputs.ViewTarget == pawn
            and str(camera.GetActorCameraMode(pawn)) == 'ThirdPerson'
            and not self.mod._vehicle_camera_active)
        self.gap_control[0] = int(eligible)
        self.gap_phase = 'PRESERVING_EXIT_FACING' if eligible else 'HANDED_OFF_OR_CANCELLED'
        if not eligible: self.gap_seat_open = False

    def read(self, address, size):
        return self.memory_reader.read(address, size)

    def u64(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def validate_character(self, pawn):
        if live(pawn)[1] != self.pawn_address: raise RuntimeError('Character identity changed')
        for name, offset in (('OakCharacterMovement', 0x6850), ('CharacterMovement', 0x430)):
            self.review_field(pawn.Class, name, 'ObjectProperty', offset, 8)
        movement, pointer = live(pawn.OakCharacterMovement)
        if pawn.CharacterMovement != movement or str(movement.Class.Name) != 'OakCharacterMovementComponent':
            raise RuntimeError('Measured character movement links differ')
        if (self.u64(self.pawn_address) != self.base + CHARACTER_TABLE
                or self.u64(self.pawn_address + 0x6850) != pointer
                or self.u64(self.pawn_address + 0x430) != pointer
                or self.u64(pointer) != self.base + MOVEMENT_TABLE):
            raise RuntimeError('Native/SDK character movement differs')
        return movement, pointer

    def body_move_original(self):
        """Accept original bytes or the current gameplay child's owned .18 hook.

        This does not follow a trampoline or authorize overwriting the movement
        hook. The late-exit and TurnState call-setup patches are separately owned.
        """
        target = self.base + 0x493D8EA
        raw = self.read(target, len(BODY_MOVE_PROLOGUE))
        if raw == BODY_MOVE_PROLOGUE:
            self.body_move_entry_state = 'ORIGINAL'
            return BODY_MOVE_PROLOGUE
        from BL4ThirdPersonPOC.omni import native_rotation
        child = self.supervisor.child
        native = getattr(child, 'native', None)
        if (getattr(self.mod, '_player_omnidirectional_gameplay', None) is not self.supervisor
                or not self.supervisor.active or child is None or not child.active
                or type(native) is not native_rotation.NativeTrace or native.capture is not child
                or native.mod is not self.mod or child.mod is not self.mod
                or child.updates is not self.updates):
            raise RuntimeError('Body-move entry changed without current Omni ownership')
        if (native_rotation.TARGET_RVA != 0x493D8EA
                or native_rotation.PROLOGUE != BODY_MOVE_PROLOGUE
                or len(native_rotation.TRACE_PREFIX) != 93
                or hashlib.sha256(native_rotation.TRACE_PREFIX).hexdigest()
                    != '79cd2c76a368f08b8000004670068127de8eb8c7fd0bdb6b978925dc1d3fc293'
                or len(native_rotation.SLIDE_RECORD_PREFIX) != 245
                or hashlib.sha256(native_rotation.SLIDE_RECORD_PREFIX).hexdigest()
                    != '9739330907f06c1ec57ad178d71b65b0f776c88520137cd3dd41005cff7ff374'):
            raise RuntimeError('Reviewed Omni movement templates differ')
        hook = native.hook
        if (not isinstance(hook, dict) or hook.get('target') != target
                or hook.get('original') != BODY_MOVE_PROLOGUE or not hook.get('patch_attempted')
                or hook.get('restored') or not hook.get('stub')):
            raise RuntimeError('Omni movement hook metadata differs')
        expected_patch = absolute_jump(int(hook['stub'])) + b'\x90' * (len(BODY_MOVE_PROLOGUE) - 14)
        if hook.get('patch') != expected_patch or raw != expected_patch:
            raise RuntimeError('Owned Omni movement patch readback differs')
        if (native.base != self.base or native.movement != self.movement_address
                or native.vtable != self.base + MOVEMENT_TABLE
                or int(native.control[1]) != self.movement_address
                or int(native.control[2]) != int(self.producer.thread)
                or int(native.control[3]) != native.component
                or self.u64(self.movement_address + 0x110) != native.component):
            raise RuntimeError('Omni movement hook binding differs')
        bound = child.bound()
        if (len(bound) != 4 or bound[0] != self.pc_ref() or bound[1] != self.pawn_ref()
                or bound[2] != self.camera_ref() or bound[3] != self.movement_ref()):
            raise RuntimeError('Omni movement hook belongs to another runtime binding')
        # Repeat NativeTrace.validate's live address/table/component predicates
        # through this probe's private reader. Do not call/replace its WinDLL
        # read method and do not mutate its controls or diagnostic counters.
        if (live(bound[3])[1] != native.movement
                or self.u64(native.movement) != native.vtable
                or self.u64(native.movement + 0x110) != native.component):
            raise RuntimeError('Bound native movement/component changed')
        self.body_move_entry_state = 'OWNED_OMNI_NATIVE_TRACE'
        return BODY_MOVE_PROLOGUE

    def validate_dispatches(self):
        if self.body_move_original()[:len(BODY_MOVE)] != BODY_MOVE:
            raise RuntimeError('Reviewed body-move original differs')
        if self.read(self.base + 0x3CDDF24, len(LAUNCH)) != LAUNCH:
            raise RuntimeError('Reviewed launch entry differs at 0x3cddf24')
        if self.u64(self.base + MOVEMENT_TABLE + 0x4E8) != self.base + 0x493D8EA:
            raise RuntimeError('Reviewed body-move vtable slot differs')
        if self.u64(self.base + MOVEMENT_TABLE + 0x688) != self.base + 0x3CDDF24:
            raise RuntimeError('Reviewed launch vtable slot differs')

    def validate_initial(self, pc, pawn):
        from BL4ThirdPersonPOC.build_gate import REVIEWED_BUILD, parse_pe_identity
        from BL4ThirdPersonPOC.native_weapon_probe import Image
        if REVIEWED_BUILD != EXPECTED_BUILD: raise RuntimeError('Reviewed build table differs')
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        if parse_pe_identity(self.read, self.base) != EXPECTED_BUILD:
            raise RuntimeError('Reviewed executable required')
        self.image = Image(self.read, self.base)
        for rva, size in ((BODY_RVA, BODY_SIZE), (0x493D8EA, len(BODY_MOVE)), (0x3CDDF24, len(LAUNCH))):
            if self.image.code_rva(self.base + rva) != rva:
                raise RuntimeError('Measured native code outside executable image')
            for page in range((self.base + rva) & ~0xFFF, self.base + rva + size, 0x1000):
                self.mod._native_require_executable(page, 'vehicle exit body yaw')
        if hashlib.sha256(self.read(self.base + BODY_RVA, BODY_SIZE)).hexdigest() != BODY_HASH:
            raise RuntimeError('Reviewed exit calculation/body code differs or is patched')
        controller_layout(pc)
        if self.u64(self.pc_address) != self.base + PC_TABLE or pc.Pawn != pawn:
            raise RuntimeError('Measured local controller possession differs')
        if self.u64(self.pc_address + 0x3D0) != self.pawn_address:
            raise RuntimeError('Native/SDK Pawn differs')
        native = struct.unpack('<3d', self.read(self.pc_address + 0x408, 24))
        sdk = tuple(components(pc.ControlRotation, ('Pitch', 'Yaw', 'Roll')).values())
        if native != sdk: raise RuntimeError('Native/SDK ControlRotation differs')
        movement, self.movement_address = self.validate_character(pawn)
        self.movement_ref = WeakPointer(movement)
        self.validate_dispatches()
        self.report['scope'] = dict(build=[hex(x) for x in EXPECTED_BUILD], target_rva=hex(TARGET_RVA),
            controller=hex(self.pc_address), character=hex(self.pawn_address),
            movement=hex(self.movement_address), thread_id=int(self.producer.thread),
            body_sha256=BODY_HASH, body_size=BODY_SIZE,
            body_move_entry_at_arm=self.body_move_entry_state)

    def verify_patch(self):
        if self.hook is None: raise RuntimeError('Owned native patch missing')
        expected = self.hook['patch'] + CONTINUATION
        if self.read(self.base + TARGET_RVA, len(expected)) != expected:
            raise RuntimeError('Owned exit body patch changed')
        for rva, value in CALL_GUARDS.items():
            raw = bytes.fromhex(value)
            if self.read(self.base + rva, len(raw)) != raw:
                raise RuntimeError('Final body/launch callsite changed')
        self.validate_dispatches()
        self.verify_gap()

    def publish_vehicle(self, pc, pawn, camera):
        # Native identity/field proofs were checked at this seat transition.
        # The native body stub rechecks PC/PV/driver/vtables/movement on every
        # actual exit. SDK ownership is still checked on each publication.
        if pc.PersonalVehicleState.Vehicle != pawn or pc.Pawn != pawn or pawn.DriverPawn != self.pawn_ref():
            raise RuntimeError('Own vehicle possession/driver changed')
        seat_start = not self.seated or self.vehicle_ref() != pawn
        if seat_start:
            self.sequence += 1
            self.vehicle_ref = WeakPointer(pawn)
        velocity = components(pawn.GetVelocity(), ('X', 'Y', 'Z'))
        speed = math.hypot(velocity['X'], velocity['Y'])
        # Exit facing follows the vehicle's current body, including after a
        # short turn, strafe, drift or reverse. Velocity is diagnostic only.
        self.last_yaw = float(components(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))['Yaw'])
        self.source = 'vehicle_body_orientation'
        self.last_speed = speed
        if seat_start:
            summon = getattr(self.owner, 'summon', None)
            hitch.note('[OmniVehicle]', 'seated vehicle_yaw=' + hitch.value(lambda: self.last_yaw)
                       + ' camera_yaw=' + hitch.value(lambda: pc.GetControlRotation().Yaw)
                       + ' summon_target_yaw=' + ('-' if summon is None else hitch.value(lambda: summon.last_yaw)))
        self.seated = True
        self.control[3], self.control[6] = live(pawn)[1], yaw_bits(self.last_yaw)
        self.control[9], self.control[14] = self.frames, self.sequence
        eligible = (not pc.bShowMouseCursor and not self.mod._ads_active
                    and not camera.CameraModeState.bIsTransitioning
                    and camera.CameraModeInputs.ViewTarget == pawn)
        self.control[0] = int(eligible)
        return velocity

    def transition_validate(self, vehicle=None):
        """Full native proof at admission/exit transitions, never idle polling."""
        self.verify_patch()
        movement, pointer = self.validate_character(self.pawn_ref())
        if movement != self.movement_ref() or pointer != self.movement_address:
            raise RuntimeError('Character movement binding changed')
        if vehicle is not None:
            self.review_field(vehicle.Class, 'DriverPawn', 'ObjectProperty', 0x1710, 8)
            pointer = live(vehicle)[1]
            if (self.u64(self.pc_address + 0x39A8) != pointer
                    or self.u64(self.pc_address + 0x3D0) != pointer
                    or self.u64(pointer) != self.base + VEHICLE_TABLE
                    or self.u64(pointer + 0x1710) != self.pawn_address):
                raise RuntimeError('Own vehicle native admission differs')
        self.performance['transition_validations'] += 1

    def __init__(self, owner):
        self.owner, self.mod, self.updates, self.supervisor = owner, owner.mod, owner.updates, owner.sup
        self.producer = self.updates._owner
        pc, pawn, camera = self.mod._get_runtime()
        self.pc_ref, self.pawn_ref, self.camera_ref = map(WeakPointer, (pc, pawn, camera))
        self.pc_address, self.pawn_address = live(pc)[1], live(pawn)[1]
        self.layout_cache = []
        self.performance = dict(layout_reviews=0, transition_validations=0)
        self.report = dict(scope={})
        self.control = (ctypes.c_uint64 * 16)()
        self.gap_control = (ctypes.c_uint64 * 16)()
        self.buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        self.gap_buffer = (ctypes.c_ubyte * (GAP_CAPACITY * RECORD_SIZE))()
        self.hook = self.gap_hook = None
        self.publication_attempted = self.gap_publication_attempted = False
        self.active = self.seated = self.gap_seat_open = False
        self.vehicle_ref = None
        self.frames = self.sequence = self.consumed = 0
        self.memory_reader = LocalMemoryReader(self.mod)
        self.validate_initial(pc, pawn)
        self.control[1:6] = [self.pc_address, int(self.producer.thread), 0,
                             self.pawn_address, self.movement_address]
        self.control[7] = ctypes.addressof(self.buffer)
        self.control[10:14] = [self.base+PC_TABLE, self.base+VEHICLE_TABLE,
                             self.base+MOVEMENT_TABLE, self.base+CHARACTER_TABLE]
        self.validate_gap_initial()
        self.gap_control[1:5] = [self.movement_address, int(self.producer.thread),
                               self.component_address, ctypes.addressof(self.gap_buffer)]
        self.gap_control[7:14] = [ctypes.addressof(self.control), self.pc_address,
            self.pawn_address, self.base+MOVEMENT_TABLE, self.base+0xA824FC0,
            self.base+PC_TABLE, self.base+CHARACTER_TABLE]

    def gap_air_owner(self):
        return self.owner.air if self.owner.active and self.owner.air.active else None

    def install(self):
        def gap_builder(code, trampoline):
            if (not self.updates.is_game_thread()
                    or hashlib.sha256(self.read(self.base+GAP_REGION_RVA, GAP_REGION_SIZE)).hexdigest() != GAP_REGION_HASH):
                raise RuntimeError('TurnState changed before publication')
            self.validate_gap_component()
            code = GAP_PREFIX.replace(SENTINEL, struct.pack('<Q', ctypes.addressof(self.gap_control)))
            return (self.gap_buffer, self.control), self.gap_control, code + absolute_jump(self.base+GAP_RVA+len(GAP_ORIGINAL))
        self.gap_publication_attempted = True
        self.gap_hook = self.mod._native_allocate_hook(self.base+GAP_RVA, GAP_ORIGINAL,
            len(GAP_ORIGINAL), gap_builder, 'Omni vehicle exit facing gap')
        def builder(code, trampoline):
            if (not self.updates.is_game_thread()
                    or hashlib.sha256(self.read(self.base+BODY_RVA, BODY_SIZE)).hexdigest() != BODY_HASH):
                raise RuntimeError('Exit body changed before publication')
            return self.buffer, self.control, stub(ctypes.addressof(self.control), trampoline)
        self.publication_attempted = True
        self.hook = self.mod._native_allocate_hook(self.base+TARGET_RVA, ORIGINAL,
            len(ORIGINAL), builder, 'Omni vehicle exit body yaw')
        self.verify_patch()
        self.active = True

    def disarm(self):
        self.control[0] = self.gap_control[0] = 0

    def exit_snapshot(self, count):
        """Decode the existing native scratch record, without changing its stub.

        PREFIX records 16 qwords: flag, PC/vehicle/character/movement, original
        rotation, applied yaw, publication update/sequence, camera yaw and tail.
        This is report-only; unavailable diagnostics never affect handoff.
        """
        try:
            if not 1 <= count <= CAPACITY:
                raise ValueError('Exit record count outside scratch capacity')
            row = struct.unpack_from('<16Q', self.buffer, (count - 1) * RECORD_SIZE)
            if (row[0] != 1 or row[1] != self.pc_address or row[2] != int(self.control[3])
                    or row[3] != self.pawn_address or row[4] != self.movement_address):
                raise ValueError('Exit record ownership differs')
            def yaw(bits):
                value = struct.unpack('<d', struct.pack('<Q', bits))[0]
                if not math.isfinite(value):
                    raise ValueError('Nonfinite exit record yaw')
                return value
            return dict(applied_yaw=yaw(row[8]), native_original_yaw=yaw(row[6]),
                        native_camera_yaw=yaw(row[11]), publication_update=row[9],
                        publication_sequence=row[10],
                        publication_age_updates=self.frames - row[9])
        except Exception as exc:
            return dict(applied_yaw='?', native_record_error=repr(exc)[:160])

    def frame(self, pc, pawn, camera):
        previous_gap = bool(self.gap_control[0])
        self.disarm()
        self.frames += 1
        movement = self.movement_ref()
        character = self.pawn_ref()
        if (pc != self.pc_ref() or camera != self.camera_ref() or character is None
                or movement is None or character.OakCharacterMovement != movement
                or character.CharacterMovement != movement or movement.UpdatedComponent != self.component_ref()):
            raise RuntimeError('Vehicle exit live bindings changed')
        count = int(self.control[8])
        if not self.consumed <= count <= CAPACITY: raise RuntimeError('Exit scratch count differs')
        if count != self.consumed:
            self.transition_validate()
            self.consumed = count
            self.owner.report['exit_rotations'] += 1
            row = dict(**self.exit_snapshot(count),
                       published_yaw=hitch.value(lambda: self.last_yaw),
                       source=getattr(self, 'source', None),
                       vehicle_speed=hitch.value(lambda: self.last_speed),
                       character_yaw=hitch.value(lambda: character.K2_GetActorRotation().Yaw),
                       camera_yaw=hitch.value(lambda: pc.GetControlRotation().Yaw))
            exits = self.owner.report.setdefault('exit_facings', [])
            exits.append(row)
            del exits[:-16]
            hitch.note('[OmniVehicle]', 'exit ' + ' '.join(k + '=' + str(v) for k, v in row.items()))
        if pawn == character:
            self.seated = False
            if self.gap_seat_open or previous_gap:
                self.gap_publish(pc, pawn, camera, movement)
            if not self.gap_seat_open and not self.gap_control[0]:
                # Seat epoch is over; neither stub can use its scratch records.
                self.control[8] = self.gap_control[5] = self.gap_control[6] = self.consumed = 0
            elif self.gap_control[5] >= GAP_CAPACITY:
                self.gap_control[5] = 0
        elif str(pawn.Class.Name) == 'OakVehicle':
            if pc.PersonalVehicleState.Vehicle != pawn or pawn.DriverPawn != character:
                self.seated = self.gap_seat_open = False
                return
            if not self.seated or self.vehicle_ref() != pawn:
                self.transition_validate(pawn)
            self.publish_vehicle(pc, pawn, camera)
            self.gap_publish(pc, pawn, camera, movement)
        else:
            self.seated = self.gap_seat_open = False

    def stop(self):
        self.disarm()
        self.active = False
        for attr, attempted, rva, original, continuation, region, size, digest in (
            ('gap_hook', self.gap_publication_attempted, GAP_RVA, GAP_ORIGINAL, GAP_CONTINUATION, GAP_REGION_RVA, GAP_REGION_SIZE, GAP_REGION_HASH),
            ('hook', self.publication_attempted, TARGET_RVA, ORIGINAL, CONTINUATION, BODY_RVA, BODY_SIZE, BODY_HASH)):
            hook = getattr(self, attr)
            if hook is not None:
                self.mod._native_restore_hook(hook)
                if self.read(self.base+rva, len(original)+len(continuation)) != original+continuation:
                    raise RuntimeError('Vehicle exit restoration differs')
                self.mod._native_release_hook(hook)
                setattr(self, attr, None)
            elif attempted and hashlib.sha256(self.read(self.base+region, size)).hexdigest() != digest:
                raise RuntimeError('Vehicle exit publication cleanup unverified')

