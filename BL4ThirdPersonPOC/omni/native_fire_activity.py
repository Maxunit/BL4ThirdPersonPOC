"""Read-only equivalent of measured sprint-request and firearm activity paths.

No hooks, native calls, writes or timer-based release. Unknown activity getters
are reported as unsupported; no raw-state interpretation is guessed for them.
"""
import struct

from unrealsdk.unreal import WeakPointer
from ..build_gate import REVIEWED_BUILD, parse_pe_identity
from ..native_weapon_probe import Image

GUARDS = {
    0x107A06E: bytes.fromhex('80b9c000000001770c4883b900010000000f95c0c3b001c3'),
    0xF5DEB4: bytes.fromhex('4881c1e8600000e848010000'),
    0xE2EA8F: bytes.fromhex('4c69f870010000438a5c3e68'),
    0xE2EB24: bytes.fromhex('49c7042400000000'),
    0x6F35FA: bytes.fromhex('f681d002000003750f488b89b00000004885c9750731c0c3b001ebfb488b0148ffa0b8020000'),
    0xB81C65: bytes.fromhex('ff9038030000'),
}


class NativeFireActivity:
    def __init__(self, mod):
        self.read = mod._native_read
        self.base = int(mod._kernel32.GetModuleHandleW(None) or 0)
        if not self.base or parse_pe_identity(self.read, self.base) != REVIEWED_BUILD:
            raise RuntimeError('Sprint-fire activity requires reviewed game build')
        for rva, expected in GUARDS.items():
            if self.read(self.base + rva, len(expected)) != expected:
                raise RuntimeError(f'Sprint-fire measured code differs at {rva:#x}')
        self.image = Image(self.read, self.base)

    def pointer(self, value):
        if not 0x10000 <= value < (1 << 47):
            raise RuntimeError('Sprint-fire pointer outside user range')
        return value

    def qword(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def slot(self, behavior, offset):
        table = self.qword(self.pointer(behavior))
        if not self.image.in_image(table) or not self.image.in_image(table + offset + 7):
            raise RuntimeError('Sprint-fire vtable outside reviewed image')
        return self.image.code_rva(self.qword(table + offset))

    def sample(self, pawn, weapon):
        if str(pawn.Class.Name) != 'OakCharacter':
            raise RuntimeError('Sprint-fire requires bound on-foot character')
        ref = WeakPointer(weapon)
        if ref() is None:
            raise RuntimeError('Sprint-fire weapon expired')
        wa = self.pointer(int(weapon._get_address()))
        data, count, capacity = struct.unpack('<Qii', self.read(wa + 0xBE8, 16))
        mode = self.read(wa + 0xBD8, 1)[0]
        if not 0 <= mode < count <= capacity <= 32:
            raise RuntimeError('Sprint-fire use-mode bounds differ')
        self.pointer(data)
        fire = self.qword(data + mode * 0x88 + 8)
        if not fire or self.slot(fire, 0x2B8) != 0x6F35FA or self.slot(fire, 0x398) != 0xB81A94:
            return dict(supported=False, pending=False, active=False, reason='UNREVIEWED_FIRE_BEHAVIOR')
        auxiliary = self.qword(fire + 0xB0)
        if auxiliary and self.slot(auxiliary, 0x2B8) != 0x107A06E:
            return dict(supported=False, pending=False, active=False, reason='UNREVIEWED_AUXILIARY_BEHAVIOR')
        flags = self.read(fire + 0x2D0, 1)[0]
        auxiliary_active = False
        if auxiliary:
            # Exact native getter: state > 1 OR own timer-handle value != 0.
            # Handle is data only; never dereference it.
            auxiliary_active = (self.read(auxiliary + 0xC0, 1)[0] > 1
                                or self.qword(auxiliary + 0x100) != 0)
        pa = self.pointer(int(pawn._get_address()))
        user = pa + 0x60E8
        if self.qword(user + 0x150) != pa:
            raise RuntimeError('Sprint-fire Weapon-User owner differs')
        entries, size, allocated = struct.unpack('<Qii', self.read(user + 0xA0, 16))
        if not 0 < size <= allocated <= 32:
            raise RuntimeError('Sprint-fire Weapon-User bounds differ')
        self.pointer(entries)
        matches = [entries + i * 0x170 for i in range(size)
                   if self.qword(entries + i * 0x170 + 0x20) == wa]
        if len(matches) != 1:
            raise RuntimeError('Sprint-fire weapon must match exactly one user entry')
        entry = matches[0]
        pending = bool(self.qword(entry + 0x58) or self.read(entry + 0x68, 1)[0] & 2)
        if (self.read(user + 0xA0, 16) != struct.pack('<Qii', entries, size, allocated)
                or self.qword(user + 0x150) != pa or self.qword(entry + 0x20) != wa
                or self.read(wa + 0xBE8, 16) != struct.pack('<Qii', data, count, capacity)
                or self.read(wa + 0xBD8, 1)[0] != mode
                or self.qword(data + mode * 0x88 + 8) != fire
                or self.qword(fire + 0xB0) != auxiliary or ref() != weapon):
            raise RuntimeError('Sprint-fire native binding changed during capture')
        return dict(supported=True, pending=pending,
                    active=bool(flags & 3 or auxiliary_active),
                    auxiliary_present=bool(auxiliary), auxiliary_active=auxiliary_active)
