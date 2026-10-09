"""Native input capture at the already fingerprinted dash-vector helper.

Phase 1/2/3 retain the original worker. Phase 4 extends its rejected-phase
branch with validated Pawn input sources. Generated assembly is in docs/.
"""
import ctypes
import math
import struct
from typing import Any
from unrealsdk.unreal import WeakPointer
from .common import parts, reflected_fields
from .native_movement import VectorEntryTrace


class LiveAirInputTrace(VectorEntryTrace):
    template = bytes.fromhex("9c50515241504151415241534c8b15d401000049833a010f85b8010000493b4a080f85ae01000065488b042548000000493b42100f859b01000049837a38010f8590010000488b442440483b05a60100000f857e0100004d8b4a184981f9000400000f83650100004d89c849c1e0074d03422049c700000000004d894808498b422849894010488b4424404989401849895020488b0249894028488b420849894030488b42104989403849c740580000000049837a40000f85c300000049837a6001742149837a6003741a49837a60020f852901000080b900110000030f859d000000eb0d80b900110000010f858e000000f68158440000010f84810000000fb6814844000083f80377754c8b99304400004d3b5a7075684d85db746349837a6001751a493b42687556418b848390000000413b427875484d8d5a48eb204989c149c1e1054f8d8c0a80000000418b848390000000413b0175264d8d5908498b03488902498b430848894208498b43104889421049ff424049c74058010000000fb68148440000498940680fb6810011000049894070488b813044000049894078488b0249894040488b420849894048488b421049894050498b42604989406049c7000100000049ff4218eb0849c7423001000000415b415a415941585a59589dff250800000011111111111111112222222222222222333333333333333349837a60040f8576ffffff80b900110000030f8569fffffff68158440000010f845cffffff0fb6814844000083f8030f874cffffff4c8b99304400004d3b5a700f853bffffff4d85db0f8432ffffff4989c149c1e1054f8d8c0a40010000418b848390000000413b010f8512ffffff4883ec60f30f7f0424f30f7f4c2410f30f7f542420f30f7f5c2430f30f7f642440f30f7f6c24504d8b9a0001000049c78238010000010000004981fb000001000f8224010000498b0348d1e049b900000000000060804c39c80f870b010000498b430848d1e04c39c80f87fb000000f2410f1003f2410f104b08660f28d0f20f59d0660f28d9f20f59d9f20f58d366410f2e92100100000f86ac000000f20f51d2f20f5ec2f20f5ecaf2410f118218010000f2410f118a2001000049c78228010000000000000fb681484400004989823001000048c1e0054d8d8c0240010000f2410f105108f2410f105910660f28e0f20f59e2660f28e9f20f59ebf20f58e5f20f59caf20f59c3f20f5cc8f20f1122f20f114a0848c7421000000000f30f6f0424f30f6f4c2410f30f6f542420f30f6f5c2430f30f6f642440f30f6f6c24504883c460e9bdfdffff4983ba3801000001751749c78238010000020000004d8b9a08010000e9cffefffff30f6f0424f30f6f4c2410f30f6f542420f30f6f5c2430f30f6f642440f30f6f6c24504883c460e97cfdffff")
    template_hash = "3aa2728cc470ab740f21c53f38f09fbdb55ce6147b7f30dd8f1999358dfc41a8"

    def __init__(self, capture: Any, spec: Any) -> None:
        super().__init__(capture, spec)
        self.control = (ctypes.c_uint64 * 64)()
        self.input_pawn_ref = None
        self.input_offsets = None
        self.control[34] = struct.unpack('<Q', struct.pack('<d', 0.04))[0]

    def install(self) -> None:
        self.bind_input_sources()
        super().install()

    def bind_input_sources(self) -> None:
        pawn = self.capture.bound()[1]
        fields = reflected_fields(pawn.Class)
        offsets = []
        for name in ('ControlInputVector', 'LastControlInputVector'):
            prop = fields.get(name)
            if (prop is None or str(prop.Class.Name) != 'StructProperty'
                    or str(prop.Struct._path_name()) != '/Script/CoreUObject.Vector'):
                raise RuntimeError('Native air input field schema differs: ' + name)
            layout = reflected_fields(prop.Struct)
            for axis, offset in (('X', 0), ('Y', 8), ('Z', 16)):
                field = layout.get(axis)
                if (field is None or str(field.Class.Name) != 'DoubleProperty'
                        or int(field.Offset_Internal) != offset):
                    raise RuntimeError('Native air input vector layout differs')
            offset = int(prop.Offset_Internal)
            if not 0 < offset < 65536:
                raise RuntimeError('Native air input field offset outside bound')
            offsets.append(offset)
        for name in ('GetPendingMovementInputVector', 'GetLastMovementInputVector'):
            if not callable(getattr(pawn, name, None)):
                raise RuntimeError('Native air input SDK getter unavailable: ' + name)
        self.input_pawn_ref = WeakPointer(pawn)
        self.input_offsets = tuple(offsets)
        self.validate_input_sources()
        self.capture.report['air_input_source'] = {
            'fields': dict(zip(('ControlInputVector', 'LastControlInputVector'), offsets)),
            'layout': 'SDK-reflected FVector / 3 finite doubles; native vs SDK readback',
            'capture': 'pending input at exact native vector helper; last-input fallback',
            'no_input': 'native vector retained; no extra direction forced',
        }

    def validate_input_sources(self) -> None:
        _, pawn, _, movement = self.capture.bound()
        if (self.input_pawn_ref is None or self.input_pawn_ref() != pawn
                or pawn.OakCharacterMovement != movement):
            self.control[32] = self.control[33] = 0
            raise RuntimeError('Native air input Pawn/Movement owner changed')
        address = int(pawn._get_address())
        methods = ('GetPendingMovementInputVector', 'GetLastMovementInputVector')
        for slot, offset, method in zip((32, 33), self.input_offsets, methods):
            source = address + offset
            if not 65536 <= source < 0x800000000000 - 24:
                raise RuntimeError('Native air input source outside pointer bounds')
            info = self.mod._native_query(source)
            start = int(info.BaseAddress or 0)
            protection = int(info.Protect)
            if (int(info.State) != 0x1000 or protection & 0x100
                    or protection & 0xff not in (2, 4, 8, 32, 64, 128)
                    or not start <= source < source + 24 <= start + int(info.RegionSize)):
                raise RuntimeError('Native air input source page unavailable')
            raw = struct.unpack('<3d', self.read(source, 24))
            sdk = parts(getattr(pawn, method)(), ('X', 'Y', 'Z'))
            if (not all(math.isfinite(v) and abs(v) <= 16 for v in raw)
                    or any(abs(v - sdk[k]) > 1e-7 for v, k in zip(raw, ('X', 'Y', 'Z')))):
                raise RuntimeError('Native air input source/readback differs: ' + method)
            self.control[slot] = source

    def consume(self) -> None:
        begin = self.consumed
        start = len(self.capture.report['vector_entry_records'])
        super().consume()
        for index, row in zip(range(begin, self.consumed),
                              self.capture.report['vector_entry_records'][start:]):
            phase = struct.unpack_from('<Q', self.buffer, index * 128 + 96)[0]
            if phase != 4:
                continue
            row['phase'] = 'AIR_LIVE_INPUT_VECTOR'
            if row['overridden']:
                desired = [struct.unpack('<d', struct.pack('<Q', self.control[n]))[0]
                           for n in (35, 36, 37)]
                if (not all(math.isfinite(v) for v in desired)
                        or abs(math.hypot(*desired[:2]) - 1) > 1e-7 or desired[2] != 0
                        or int(self.control[8]) != 1):
                    raise RuntimeError('Native air input one-shot latch differs')
                row['desired_input_vector'] = desired
                row['input_source'] = 'pending' if self.control[39] == 1 else 'last'

    def stop(self) -> None:
        self.control[32] = self.control[33] = 0
        super().stop()
        self.input_pawn_ref = None
