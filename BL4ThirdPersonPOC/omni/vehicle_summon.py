"""Reviewed vehicle transition detours; owned by the Omni supervisor.

Native instruction templates retain their exact caller/object/vtable/thread
guards. Ring buffers are bounded scratch storage, reset only with gates closed.
No diagnostics subscription, physical key query, camera or velocity setter.
"""
import ctypes
import hashlib
import importlib
from itertools import islice
import math
import struct
import sys
from unrealsdk.unreal import WeakPointer
from ..build_gate import REVIEWED_BUILD as EXPECTED_BUILD
from . import hitch
GETTER_RVA, CALL_RVA, RETURN_RVA = 0x48EC174, 0xA9ACD9, 0xA9ACDF
SETTER_RVA, POSSESSION_RVA, POSSESSION_RETURN_RVA = 0x210A52, 0x5956AAA, 0x5956D16
TABLE_RVA, VEHICLE_TABLE_RVA = 0xB98A160, 0xB8D0A80
GETTER = bytes.fromhex('4889d0488b9118040000488950100f1081080400000f1100c3')
ORIGINAL = GETTER[:14]
CALL = bytes.fromhex('ff9080060000')
SETTER = bytes.fromhex('5657534883ec204489c34889d64889cf')
CONTINUATION = bytes.fromhex('e84b000000')
POSSESSION_SIZE = 0x461
POSSESSION_HASH = '8b0502fd7b7b0f66c8b07a826d37dd383255a511909e4c584039a5d79acd650c'
CAPACITY, RECORD_SIZE, POSSESSION_RECORD_SIZE, MAX_SAMPLES = 64, 64, 128, 2048
BOOT_RETURN_RVA, BOOT_GUARD_RVA, MOVEMENT_TABLE_RVA = 0xBDA5B5, 0xBDA57D, 0xB8F37E0
BOOT_GUARD = bytes.fromhex('ff74544883be8009000000744a488b074889f9ff908010000084c00f857d0b0000488b07488d9c24800000004889f94889daff90800600000f57c0f20f5a4308f30f1186981900000f57c0f20f5a03f30f11869c1900008a86a119000034014108c5750d80be081d0000010f840e0b00')
BOOT_CAPACITY = 512
SENTINEL = b'\x11' * 8
TEMPLATE = bytes.fromhex(
    '4889d0488b9118040000488950100f1081080400000f11009c415241535249ba111111111111111149837a48010f8559'
    '010000493b4a080f854f010000654c8b1c25480000004d3b5a100f853c0100004c8b5c24204d3b5a18752549833a010f'
    '85270100004d8b5a284983fb400f831901000049c1e3064d035a30e9a60000004d3b9a900000000f85ff0000004983ba'
    '80000000010f85f10000004d8b9a880000004d85db0f84e10000004c3b99a83900000f85d40000004c3b99d00300000f'
    '85c7000000498b13493b52580f85ba000000493bb3001700000f85ad0000004885f60f84a4000000488b16493b92b800'
    '00000f85940000004d8b9a980000004981fb000200000f838000000049c1e3064d039aa000000049897330498b928800'
    '000049895338488b500849895308488b542420493b5218750d498b5220498992b0000000eb07498b92b0000000488950'
    '0849895310498b52384989531849894b20488b5424204989532849c70301000000493b5218750e49c742400100000049'
    'ff4228eb0749ff82980000005a415b415a9dc3'
)
TEMPLATE_HASH = '637ee2982805b008d3350b9c5161bf10c967305d6c3b0797584f632bc3ba279b'
POSSESSION_TEMPLATE = bytes.fromhex(
    '9c504152415349ba111111111111111149837a48010f853301000049837a40010f8528010000493b4a080f851e010000'
    '654c8b1c25480000004d3b5a100f850b0100004c8b5c24204d3b5a500f85fc00000049c742400000000049ff427849c7'
    '4260010000004180f8010f85de00000049c74260020000004885ff0f84cd00000049c7426003000000483bb9a8390000'
    '0f85b800000049c74260040000004c8b1f4d3b5a580f85a300000049c74260050000004d8b5a684983fb400f838d0000'
    '0049c742600000000049c1e3074d035a70488b0249894308488b420849894310488b421049894318488b810804000048'
    '890249894320488b81100400004889420849894328488b8118040000488942104989433049897b38488b442420498943'
    '40498b4238498943484d89435049894b584989ba8800000049c782800000000100000049c7030100000049ff4268415b'
    '415a589d'
)
POSSESSION_TEMPLATE_HASH = 'a7af33f3523de9cd60d838d2b5fdffad5cf9ed0eae1d7b8002f98274df6aac53'

def absolute_jump(target): return b'\xff\x25\0\0\0\0' + struct.pack('<Q', target)

def stub(control, trampoline=None):
    template, digest, length = ((TEMPLATE, TEMPLATE_HASH, 403) if trampoline is None else
                              (POSSESSION_TEMPLATE, POSSESSION_TEMPLATE_HASH, 340))
    if (len(template) != length or template.count(SENTINEL) != 1
            or hashlib.sha256(template).hexdigest() != digest
            or (trampoline is None and template[:24] != GETTER[:-1])):
        raise RuntimeError('Reviewed native template differs')
    code = template.replace(SENTINEL, struct.pack('<Q', control))
    return code if trampoline is None else code + absolute_jump(trampoline)

def live(obj):
    value = None if obj is None else WeakPointer(obj)()
    if value is None or value.Class is None:
        raise RuntimeError('Local SDK object expired')
    address = int(value._get_address())
    if not 0x10000 <= address < (1 << 47):
        raise RuntimeError('SDK object address outside user range')
    return value, address

def vector_yaw(vector):
    x, y, z = (float(getattr(vector, key)) for key in ('X', 'Y', 'Z'))
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise RuntimeError('Nonfinite native movement vector')
    # Match the existing Omni movement-input threshold, without physical keys.
    return math.degrees(math.atan2(y, x)) if math.hypot(x, y) > 0.2 else None

def rot_yaw(obj):
    value = float(obj.K2_GetActorRotation().Yaw)
    if not math.isfinite(value): raise RuntimeError('Nonfinite actor yaw')
    return (value + 180.0) % 360.0 - 180.0

def control_layout(pc):
    parents = list(islice(pc.Class._superfields(), 25))
    if len(parents) > 24: raise RuntimeError('Controller inheritance bound exceeded')
    for schema in (pc.Class, *parents):
        fields = list(islice(schema._properties(), 4097))
        if len(fields) > 4096: raise RuntimeError('Controller field bound exceeded')
        for prop in fields:
            if str(prop.Name) == 'ControlRotation':
                if (str(prop.Class.Name) != 'StructProperty' or int(prop.Offset_Internal) != 0x408
                        or int(prop.ElementSize) != 24 or int(prop.ArrayDim) != 1
                        or str(prop.Struct._path_name()) != '/Script/CoreUObject.Rotator'):
                    raise RuntimeError('Measured ControlRotation layout differs')
                members = {str(p.Name).lower(): p for p in prop.Struct._properties()}
                for name, offset in (('pitch', 0), ('yaw', 8), ('roll', 16)):
                    p = members.get(name)
                    if (p is None or str(p.Class.Name) != 'DoubleProperty'
                            or int(p.Offset_Internal) != offset or int(p.ElementSize) != 8
                            or int(p.ArrayDim) != 1):
                        raise RuntimeError('Measured Rotator layout differs')
                return
    raise RuntimeError('ControlRotation reflection unavailable')

def vehicle_layout(pc):
    parents = list(islice(pc.Class._superfields(), 25))
    if len(parents) > 24: raise RuntimeError('Controller inheritance bound exceeded')
    props = {}
    for schema in (pc.Class, *parents):
        fields = list(islice(schema._properties(), 4097))
        if len(fields) > 4096: raise RuntimeError('Controller field bound exceeded')
        for prop in fields: props.setdefault(str(prop.Name), prop)
    prop = props.get('PersonalVehicleState')
    if (prop is None or str(prop.Class.Name) != 'StructProperty'
            or int(prop.Offset_Internal) != 0x3920 or int(prop.ElementSize) != 544
            or int(prop.ArrayDim) != 1
            or str(prop.Struct._path_name()) != '/Script/OakGame.PersonalVehicleState'):
        raise RuntimeError('Measured personal vehicle state layout differs')
    fields = list(islice(prop.Struct._properties(), 4097))
    if len(fields) > 4096: raise RuntimeError('Vehicle field bound exceeded')
    prop = next((p for p in fields if str(p.Name) == 'Vehicle'), None)
    if (prop is None or str(prop.Class.Name) != 'ObjectProperty'
            or int(prop.Offset_Internal) != 0x88 or int(prop.ElementSize) != 8
            or int(prop.ArrayDim) != 1):
        raise RuntimeError('Measured owned vehicle link layout differs')

class SummonFacing:
    def read(self, address, size):
        if not 0x10000 <= address < address + size < (1 << 47) or not 1 <= size <= 0x20000:
            raise RuntimeError('Native diagnostic read outside bounds')
        self.mod._native_require_readable(address, size, 'vehicle summon A/B')
        raw = self.mod._native_read(address, size)
        if not isinstance(raw, bytes) or len(raw) != size: raise RuntimeError('Incomplete native read')
        return raw

    def u64(self, address): return struct.unpack('<Q', self.read(address, 8))[0]

    def validate_initial(self, pc, pawn):
        from BL4ThirdPersonPOC.build_gate import REVIEWED_BUILD, parse_pe_identity
        from BL4ThirdPersonPOC.native_weapon_probe import Image
        if REVIEWED_BUILD != EXPECTED_BUILD: raise RuntimeError('Reviewed build table differs')
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        if parse_pe_identity(self.read, self.base) != EXPECTED_BUILD:
            raise RuntimeError('Reviewed executable required')
        image = Image(self.read, self.base)
        for rva in (GETTER_RVA, CALL_RVA, SETTER_RVA, POSSESSION_RVA,
                    POSSESSION_RVA + POSSESSION_SIZE - 1, BOOT_GUARD_RVA, BOOT_RETURN_RVA):
            if image.code_rva(self.base + rva) != rva:
                raise RuntimeError('Measured code outside executable image')
            self.mod._native_require_executable(self.base + rva, 'vehicle summon A/B v3')
        control_layout(pc)
        vehicle_layout(pc)
        if self.u64(self.pc_address + 0xF48) != self.pawn_address:
            raise RuntimeError('Measured local character link differs')
        owned = pc.PersonalVehicleState.Vehicle
        owned_address = 0 if owned is None else live(owned)[1]
        if self.u64(self.pc_address + 0x39A8) != owned_address:
            raise RuntimeError('Native/SDK owned vehicle link differs')
        if owned is not None and (str(owned.Class.Name) != 'OakVehicle'
                or self.u64(owned_address) != self.base + VEHICLE_TABLE_RVA):
            raise RuntimeError('Measured own vehicle type/vtable differs')
        # Require the reviewed image-owned vehicle table to be readable even
        # when no vehicle exists at arm time. No table slot is called here.
        self.read(self.base + VEHICLE_TABLE_RVA, 8)
        self.validate_static()
        values = struct.unpack('<3d', self.read(self.pc_address + 0x408, 24))
        sdk_values = tuple(float(getattr(pc.ControlRotation, k)) for k in ('Pitch', 'Yaw', 'Roll'))
        if not all(math.isfinite(x) and x == y for x, y in zip(values, sdk_values)):
            raise RuntimeError('Native/SDK controller rotation differs')
        self.report['build'] = [hex(v) for v in EXPECTED_BUILD]
        self.report['scope'] = dict(getter_rva=hex(GETTER_RVA), caller_return_rva=hex(RETURN_RVA),
            setter_rva=hex(SETTER_RVA), possession_return_rva=hex(POSSESSION_RETURN_RVA),
            possession_body_sha256=POSSESSION_HASH, owned_vehicle_offset='0x39a8',
            vehicle_vtable_rva=hex(VEHICLE_TABLE_RVA), movement_vtable_rva=hex(MOVEMENT_TABLE_RVA),
            boot_caller_return_rva=hex(BOOT_RETURN_RVA), boot_guard_sha256=hashlib.sha256(BOOT_GUARD).hexdigest(),
            controller=hex(self.pc_address), thread_id=int(self.producer.thread))

    def target(self, name):
        return ((GETTER_RVA, ORIGINAL, GETTER) if name == 'getter' else
                (SETTER_RVA, SETTER, SETTER + CONTINUATION))

    def validate_static(self):
        for name in ('getter', 'possession'):
            rva, original, full = self.target(name)
            hook = self.native_hooks.get(name)
            expected = full if hook is None else hook['patch'] + full[len(original):]
            if self.read(self.base + rva, len(full)) != expected:
                raise RuntimeError('Owned native ' + name + ' entry differs')
        if (getattr(self.drive_module, '_owner', None) is not self.drive_owner or not self.drive_owner.active
                or not bool(self.mod.vehicle_camera_relative_drive.value)):
            raise RuntimeError('Camera-relative vehicle control ownership changed/stopped')
        self.read(self.base + BOOT_GUARD_RVA, len(BOOT_GUARD))
        if self.chain.original_read(self.mod, self.base + BOOT_GUARD_RVA, len(BOOT_GUARD)) != BOOT_GUARD:
            raise RuntimeError('Reviewed vehicle DesiredYaw reader changed')
        if self.read(self.base + CALL_RVA, len(CALL)) != CALL:
            raise RuntimeError('Measured summon caller differs')
        # Guards the caller register, temporary rotator lifetime and subsequent
        # SetPawn handoff, including out-of-line root-cache branches.
        if hashlib.sha256(self.read(self.base + POSSESSION_RVA, POSSESSION_SIZE)).hexdigest() != POSSESSION_HASH:
            raise RuntimeError('Reviewed possession body differs')
        if (self.u64(self.pc_address) != self.base + TABLE_RVA
                or any(self.u64(self.base + TABLE_RVA + slot) != self.base + rva for slot, rva in
                       ((0x680, GETTER_RVA), (0x688, SETTER_RVA), (0x6E8, POSSESSION_RVA)))):
            raise RuntimeError('Measured local controller dispatch differs')

    def _review_field(self, schema, name, kind, offset, size):
        parents = list(islice(schema._superfields(), 25))
        if len(parents) > 24: raise RuntimeError('Vehicle inheritance bound exceeded')
        for owner in (schema, *parents):
            fields = list(islice(owner._properties(), 4097))
            if len(fields) > 4096: raise RuntimeError('Vehicle field bound exceeded')
            for prop in fields:
                if str(prop.Name) == name:
                    if (str(prop.Class.Name) != kind or int(prop.Offset_Internal) != offset
                            or int(prop.ElementSize) != size or int(prop.ArrayDim) != 1):
                        raise RuntimeError('Measured vehicle field differs: ' + name)
                    return
        raise RuntimeError('Measured vehicle field unavailable: ' + name)

    def field(self, schema, name, kind, offset, size):
        signature = (name, kind, offset, size)
        self.layout_cache[:] = [(ref, fields) for ref, fields in self.layout_cache if ref() is not None]
        for ref, fields in self.layout_cache:
            if ref() == schema:
                if signature not in fields:
                    self._review_field(schema, *signature)
                    fields.add(signature)
                return
        self._review_field(schema, *signature)
        self.layout_cache.append((WeakPointer(schema), {signature}))

    def transition_handoff(self, pc, pawn, camera):
        if not self.control[16]: return dict(boot_hold=False)
        vehicle = pc.PersonalVehicleState.Vehicle
        if vehicle is None or live(vehicle)[1] != self.control[17] or pawn != vehicle:
            self.control[16] = 0
            self.record_handoff(dict(update=self.frames, outcome='CONTEXT_LEFT',
                                                boot_calls=self.boot_consumed))
            return dict(boot_hold=False, handoff='CONTEXT_LEFT')
        self.field(vehicle.Class, 'OakVehicleMovement', 'ObjectProperty', 0x1700, 8)
        if self.u64(live(vehicle)[1]) != self.base + VEHICLE_TABLE_RVA:
            raise RuntimeError('Measured own vehicle vtable changed')
        movement = vehicle.OakVehicleMovement
        movement, address = live(movement)
        if (str(movement.Class._path_name()) != '/Script/OakGame.OakWheeledVehicleMovementComponent'
                or self.u64(address) != self.base + MOVEMENT_TABLE_RVA):
            raise RuntimeError('A/B v3 requires the measured wheeled vehicle movement')
        for name, offset in (('DesiredYaw', 0x1998), ('DesiredPitch', 0x199C)):
            self.field(movement.Class, name, 'FloatProperty', offset, 4)
        desired = float(movement.DesiredYaw)
        if not math.isfinite(desired): raise RuntimeError('Nonfinite vehicle DesiredYaw')
        child = self.drive_owner.child
        buffer = getattr(child, 'buffer', None)
        bound = bool(child is not None and child.active and getattr(child, 'phase', None) == 'ACTIVE'
                     and isinstance(buffer, ctypes.Array) and ctypes.sizeof(buffer) == 160)
        target = None
        if bound:
            raw = bytes(buffer)
            receiver = struct.unpack_from('<Q', raw, 0)[0]
            binding_gate = struct.unpack_from('<Q', raw, 16)[0]
            direction_gate = struct.unpack_from('<Q', raw, 64)[0]
            target = struct.unpack_from('<f', raw, 72)[0]
            publication = struct.unpack_from('<Q', raw, 80)[0]
            bound = (receiver == address and binding_gate == direction_gate == 1
                     and publication > 0 and math.isfinite(target)
                     and tuple(getattr(child, 'bindings', ())) ==
                     (self.pc_address, live(vehicle)[1], live(camera)[1], address)
                     and not camera.CameraModeState.bIsTransitioning)
        if bound:
            if (len(child.native_hooks) != 1
                    or child.native_hooks[0]['target'] != self.base + 0xBDA5BD
                    or child.native_hooks[0].get('restored', False)
                    or child.native_hooks[0].get('_probe_retired', False)):
                raise RuntimeError('Published vehicle control hook ownership differs')
            for item in child.native_hooks: self.chain.verify(self.mod, item)
            self.control[16] = 0
            self.record_handoff(dict(update=self.frames, outcome='DRIVE_BOUND',
                vehicle_address=hex(live(vehicle)[1]), movement_address=hex(address),
                native_desired_yaw=desired, published_target_yaw=target,
                publication=publication, boot_calls=self.boot_consumed))
        return dict(boot_hold=bool(self.control[16]), native_desired_yaw=desired,
                    drive_phase=str(getattr(child, 'phase', None)), drive_bound=bool(bound),
                    drive_target_yaw=target, movement_address=hex(address))

    def __init__(self, owner):
        self.owner, self.mod, self.updates = owner, owner.mod, owner.updates
        self.producer = self.updates._owner
        pc, pawn, camera = self.mod._get_runtime()
        self.pc_ref, self.pawn_ref = WeakPointer(pc), WeakPointer(pawn)
        self.pc_address, self.pawn_address = live(pc)[1], live(pawn)[1]
        self.control = (ctypes.c_uint64 * 24)()
        self.buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        self.possession_buffer = (ctypes.c_ubyte * (CAPACITY * POSSESSION_RECORD_SIZE))()
        self.boot_buffer = (ctypes.c_ubyte * (BOOT_CAPACITY * RECORD_SIZE))()
        self.native_hooks, self.attempted = {}, set()
        self.frames, self.boot_consumed = 0, 0
        self.last_yaw, self.source = rot_yaw(pawn), 'current_character_body'
        self.report = dict(handoffs=[], scope={})
        self.drive_module = importlib.import_module('BL4ThirdPersonPOC.vehicle_control')
        self.drive_owner = getattr(self.drive_module, '_owner', None)
        self.chain = importlib.import_module('BL4ThirdPersonPOC.camera_hook_chain')
        self.active = False
        self.seat_vehicle = None
        self.seat = None
        self.layout_cache = []
        self.validate_initial(pc, pawn)
        self.control[1:4] = [self.pc_address, int(self.producer.thread), self.base + RETURN_RVA]
        self.control[6] = ctypes.addressof(self.buffer)
        self.control[10:12] = [self.base + POSSESSION_RETURN_RVA, self.base + VEHICLE_TABLE_RVA]
        self.control[14] = ctypes.addressof(self.possession_buffer)
        self.control[18] = self.base + BOOT_RETURN_RVA
        self.control[20] = ctypes.addressof(self.boot_buffer)
        self.control[23] = self.base + MOVEMENT_TABLE_RVA

    def record_handoff(self, row):
        self.report['handoffs'].append(row)
        del self.report['handoffs'][:-16]

    def install(self):
        for name in ('possession', 'getter'):
            rva, original, full = self.target(name)
            def builder(code, trampoline, name=name):
                if not self.updates.is_game_thread(): raise RuntimeError('Owned GameThread required')
                self.validate_static()
                code = stub(ctypes.addressof(self.control), trampoline if name == 'possession' else None)
                return (self.buffer, self.possession_buffer, self.boot_buffer), self.control, code
            self.attempted.add(name)
            self.native_hooks[name] = self.mod._native_allocate_hook(self.base+rva, original,
                len(original), builder, 'Omni vehicle summon ' + name)
            self.validate_static()
        self.active, self.control[9] = True, 1

    def disarm(self):
        self.control[0] = self.control[8] = self.control[16] = 0

    def frame(self, pc, pawn, camera):
        self.control[0] = 0
        self.frames += 1
        if pc != self.pc_ref() or self.pawn_ref() is None:
            raise RuntimeError('Summon local owner expired')
        in_vehicle = str(pawn.Class.Name) == 'OakVehicle'
        if in_vehicle:
            if self.seat_vehicle is None or self.seat_vehicle() != pawn:
                self.validate_static()
                self.seat_vehicle = WeakPointer(pawn)
        elif self.seat_vehicle is not None:
            self.validate_static()
            self.seat_vehicle = None
        on_foot = pawn == self.pawn_ref()
        self.seat_frame(pc, pawn, on_foot)
        # Native per-call proofs remain. Full image/patch proofs are transition work.
        if self.control[16]:
            self.transition_handoff(pc, pawn, camera)
        child = self.owner.sup.child
        allowed = (on_foot and self.owner.normal(pc) and self.mod._third_person_pushed
            and child is not None and child.active and not getattr(child, 'special_paused', False)
            and int(pawn.OakCharacterMovement.MovementMode) == 1
            and not camera.CameraModeState.bIsTransitioning
            and camera.CameraModeInputs.ViewTarget == pawn
            and str(camera.GetActorCameraMode(pawn)) == 'ThirdPerson')
        if allowed:
            # Input is a requested direction, not the actual body orientation.
            # Refresh even while idle or after an exit changed the actor yaw.
            self.last_yaw = rot_yaw(pawn)
            self.source = 'current_character_body'
            # Previous seat tickets have ended. Reset bounded records with both
            # the summon gate and boot gate closed; the native GameThread is ours.
            if not self.control[16] and not self.control[8]:
                self.control[5] = self.control[13] = self.control[19] = 0
                self.boot_consumed = 0
        self.control[4] = struct.unpack('<Q', struct.pack('<d', self.last_yaw))[0]
        self.control[7] = self.frames
        self.control[0] = int(allowed)
        if self.control[19] >= BOOT_CAPACITY:
            # Bounded scratch can wrap only between native calls on this thread.
            self.control[19] = 0
            self.boot_consumed = 0

    def seat_frame(self, pc, pawn, on_foot):
        """Bounded summon-seat window (QA timeline, hidden-character camera alignment).

        Opens for any non-character pawn that is the owned vehicle or follows a
        recent summon ticket, independent of the vehicle class name. Runs before
        the summon gate is republished. Never raises: a failing read closes the
        window. On foot without an open window it costs nothing.
        """
        seat = getattr(self, 'seat', None)
        if seat is None and on_foot:
            return
        character = self.pawn_ref()
        try:
            if on_foot:
                vehicle = None
            elif seat is not None and seat.ref() == pawn:
                vehicle = pawn
            else:
                from .summon_seat import summon_ticket
                owned = pc.PersonalVehicleState.Vehicle == pawn
                vehicle = pawn if owned or summon_ticket(self) is not None else None
            if seat is not None and (vehicle is None or seat.ref() != vehicle):
                seat.finish('left_vehicle' if vehicle is None else 'other_vehicle')
                self.seat = seat = None
            if vehicle is None:
                return
            if seat is None:
                from .summon_seat import SummonSeat
                self.seat = seat = SummonSeat(self, vehicle)
                seat.row['owned'] = hitch.text(lambda: int(pc.PersonalVehicleState.Vehicle == vehicle))
            if not seat.done:
                seat.step(pc, vehicle, character)
        except Exception as exc:
            if seat is not None:
                seat.row['error'] = hitch.text(lambda: repr(exc), 160)
                seat.finish('error')

    def stop(self):
        seat = getattr(self, 'seat', None)
        if seat is not None:
            seat.finish('stopped')
            self.seat = None
        self.disarm()
        self.control[9], self.active = 0, False
        for name in ('getter', 'possession'):
            rva, original, full = self.target(name)
            hook = self.native_hooks.get(name)
            if hook is not None:
                self.mod._native_restore_hook(hook)
                if self.read(self.base+rva, len(full)) != full:
                    raise RuntimeError('Summon restoration differs: ' + name)
                self.mod._native_release_hook(hook)
                del self.native_hooks[name]
            elif name in self.attempted and self.read(self.base+rva, len(full)) != full:
                raise RuntimeError('Summon publication cleanup unverified')

