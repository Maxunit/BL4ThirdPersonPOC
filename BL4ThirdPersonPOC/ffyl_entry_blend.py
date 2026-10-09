"""First-entry native blend compensation; no hook or clock-based smoothing.
Build, layout, serial lifetimes and current stack membership guard every read.
Read failures stop compensation; native camera ownership remains with production.
"""
import math
import struct
from .build_gate import REVIEWED_BUILD

EXPECTED_BUILD = REVIEWED_BUILD
# Measured runtime layout/callsite evidence. These are read-only code checks.
LAYOUT_ANCHORS = {
    0x1449892: '4989c70f57ff0f29384889781048895818488d48400f2978200f297830e812c1',
    0x1449F72: '488b86483a00000f57d24885c07417488b40104885c0740e0f2ed67606f6401c',
    0x14498DA: 'e8cd56a1ff498b4710486348304885c9',
}


class NativeBlendReader:
    """Observe fresh active runtime only; retain serial references, never runtime pointers.

    Snapshot equality detects changes, but is not a cross-thread lock. Failed
    reads are diagnostic only and never block the original camera callback.
    The archived +0xa78 byte is raw evidence, NOT an interpreted active flag.
    """
    def __init__(self, mod, state, weak_pointer):
        self.mod, self.state = mod, state
        self.disabled = False
        objects = mod._get_runtime()
        if any(obj is None for obj in objects):
            raise RuntimeError('Loaded local gameplay tuple required')
        self.addresses = tuple(int(obj._get_address()) for obj in objects)
        self.references = tuple(weak_pointer(obj) for obj in objects)
        self.validate_lifetimes()
        base = int(mod._kernel32.GetModuleHandleW(None) or 0)
        dos = self.read(base, 64)
        if dos[:2] != b'MZ':
            raise RuntimeError('Main module DOS header mismatch')
        offset = struct.unpack_from('<I', dos, 60)[0]
        if not 64 <= offset <= 0x100000:
            raise RuntimeError('Main module PE offset outside bounds')
        pe = self.read(base+offset, 0x60)
        if pe[:4] != b'PE\0\0' or struct.unpack_from('<H', pe, 24)[0] != 0x20B:
            raise RuntimeError('Main module PE32+ header mismatch')
        build = (struct.unpack_from('<I', pe, 8)[0],
                 struct.unpack_from('<I', pe, 80)[0],
                 struct.unpack_from('<H', pe, 4)[0])
        if build != EXPECTED_BUILD:
            raise RuntimeError('Native FFYL reader build mismatch')
        for rva, hx in LAYOUT_ANCHORS.items():
            expected = bytes.fromhex(hx)
            if self.read(base+rva, len(expected)) != expected:
                raise RuntimeError('Native camera layout code changed at '+hex(rva))
        state['native_reader_validation'] = {
            'build': [hex(v) for v in build], 'layout_anchors_verified': True,
            'source': 'reviewed native runtime observer',
            'duration_offset': '0xa70', 'remaining_offset': '0xa74',
            'raw_byte_offset': '0xa78', 'serial_lifetimes_bound': True,
            'time_fraction_is_not_engine_eased_alpha': True}

    def read(self, address, size):
        if not 0x10000 <= address < 0x0000800000000000 or not 0 < size <= 0x10000 or address+size > 0x0000800000000000:
            raise RuntimeError('Native diagnostic read outside bounds')
        self.state['native_accesses_added'] += 1
        data = self.mod._native_read(address, size)
        if len(data) != size:
            raise RuntimeError('Incomplete native diagnostic read')
        return data

    def validate_lifetimes(self):
        objects = tuple(ref() for ref in self.references)
        current = self.mod._get_runtime()
        if (any(obj is None for obj in objects+current)
                or tuple(int(obj._get_address()) for obj in objects) != self.addresses
                or tuple(int(obj._get_address()) for obj in current) != self.addresses):
            raise RuntimeError('Native reader gameplay lifetime changed')

    def snapshot(self):
        if self.disabled:
            return {'status': 'disabled_after_lifetime_change'}
        try:
            self.validate_lifetimes()
        except Exception:
            self.disabled = True
            raise
        address = self.addresses[2]+0x39A8
        manager = self.read(address, 0xB0)
        array, count, capacity = struct.unpack_from('<Qii', manager, 0x18)
        if not 0 <= count <= capacity <= 256 or count > 64:
            raise RuntimeError('Native camera stack outside bounds')
        if not count:
            return {'status': 'empty_stack'}
        stack = self.read(array, count*40)
        pair = manager[0xA0:0xB0]
        fname = manager[0x88:0x90]
        matches = [stack[i:i+40] for i in range(0, len(stack), 40)
                   if stack[i+24:i+40] == pair and stack[i:i+8] == fname]
        if len(matches) != 1:
            raise RuntimeError('Active runtime lacks unique live stack membership')
        runtime, control = struct.unpack('<QQ', pair)
        header = self.read(runtime, 32)
        if struct.unpack_from('<QQ', header) != (runtime, control):
            raise RuntimeError('Active native runtime self/control differs')
        duration, remaining, raw_byte = struct.unpack('<ffB', self.read(runtime+0xA70, 9))
        if (not all(math.isfinite(v) for v in (duration, remaining))
                or not 0 <= duration <= 10 or not -0.1 <= remaining <= duration+0.1):
            raise RuntimeError('Native blend values outside diagnostic bounds')
        coherent = (self.read(address, 0xB0) == manager
                    and self.read(array, len(stack)) == stack
                    and self.read(runtime, 32) == header)
        self.validate_lifetimes()
        if not coherent:
            return {'status': 'incoherent_snapshot'}
        return {'status': 'ok', 'runtime': hex(runtime), 'control': hex(control),
                'definition': hex(struct.unpack_from('<Q', header, 16)[0]),
                'mode_fname_hex': fname.hex(), 'stack_count': count,
                'blend_duration': duration, 'blend_remaining': remaining,
                'raw_byte_a78': raw_byte,
                'linear_time_fraction': max(0.0, min(1.0, 1.0-remaining/duration)) if duration > 0 else None}



def native_ease(fraction):
    # Empirical inference: this exact quadratic ease-in/out reproduces all 31
    # lateral samples in the stationary 20261004_024719 baseline to <0.000006
    # units, after subtracting the previous callback's applied SDK Y offset.
    # This is a measured curve candidate, not a decoded engine alpha field.
    t = max(0.0, min(1.0, fraction))
    return 2.0*t*t if t < 0.5 else 1.0-2.0*(1.0-t)**2



class EntryBlend:
    def __init__(self, mod, weak_pointer):
        self.reader = NativeBlendReader(mod, {'native_accesses_added': 0}, weak_pointer)
        self.runtime = None
        self.context = None
        self.done = False

    def apply(self, owner, values):
        mod = owner._mod
        if self.done or values == (0.0, 0.0, 0.0):
            return values
        if (owner.closed or owner.faulted or mod._ads_active
                or mod._vehicle_camera_active or mod._shop_camera_active
                or mod._ladder_active or mod._slide_active or not mod._third_person_enabled):
            self.done = True
            return values
        # Pop clears ownership and writes zero before Push. Pending preparation
        # must not be cancelled by this deliberate transaction.
        if not mod._third_person_pushed or mod._camera_lifecycle.get('pending'):
            if self.runtime is not None:
                self.done = True
            return values
        pc, pawn, camera = owner.current_runtime()
        if owner.context is None or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
            return values
        if self.context is not None and self.context is not owner.context:
            self.done = True
            return values
        sample = self.reader.snapshot()
        if sample['status'] != 'ok':
            self.done = True
            return values
        if self.runtime is not None and sample['runtime'] != self.runtime:
            self.done = True
            return values
        self.context = owner.context
        self.runtime = sample['runtime']
        fraction = sample['linear_time_fraction']
        if fraction is None or fraction >= 1.0:
            self.done = True
            return values
        alpha = native_ease(fraction)
        return tuple(v * alpha for v in values)
