"""TPS aim trace starts at the character depth for every weapon (0.3.9.9).

Measured with bl4tps_weapon_probe / bl4tps_native_dump (steam-2026-09-14):

- Fire slot 0x2C0 asks the weapon holder (OakCharacter interface +0x3A30,
  slot +0x38) for the shot ORIGIN. In TPS that is already at the character
  (0.3.9.8 measured only ~3 cm depth to the pawn), so moving it changed nothing.
- The fire ROTATION comes from holder +0x48 -> controller vfunc 0x7A0
  (0xC8D630). In first person (controller vfunc 0x788 = camera definition flag)
  it returns the view rotation. In TPS it calls GetPlayerViewPoint (controller
  vfunc 0x718), builds End = ViewLocation + Forward * Range and runs
  LineTraceSingleByChannel(World, Hit, Start=&ViewLocation, End, channel 4)
  at 0xC8DA19. The rotation then points from the origin to Hit.Location (or End).
- The trace therefore starts at the CAMERA. Anything on the crosshair ray
  between camera and character (an enemy behind the character, a wall edge
  next to the camera) becomes the aim point and the shot flies at it.

Correction (ray depth along the camera direction): before the trace, move
its start along the trace direction to the character's depth plus a margin:

    dir    = normalize(End - Start)
    depth  = dot(P - Start, dir) + margin            (P = pawn location)
    Start += dir * depth   when 0 < depth < min(max_depth, |End - Start|)

Everything closer to the camera than the character is no longer traced;
obstacles in front of the weapon remain real hits. P comes from Python every
frame, so the configurable camera X/Y/Z offsets need no special case.

Native shape: one detour replaces the two argument loads before the trace call
(lea r8,[rsp+0x170]; lea r9,[rsp+0x140] at 0xC8DA03, 16 bytes, no branch
targets inside). The stub adjusts the start vector in the caller's frame when
the control block is enabled and the receiver is the local controller, replays
both loads and returns to 0xC8DA13. It only uses r10, r11, xmm0-xmm5 and flags
(rax holds the world; xmm6-xmm8 hold the end point) and never calls out.
The verified function hash, the exact original bytes and the reviewed build
are required before any write. Code and control stay pinned after restore.
"""
import ctypes
import hashlib
import math
import struct
import sys
import types

from .build_gate import REVIEWED_BUILD, parse_pe_identity

TAG = '[BL4ThirdPersonPOC.AimTrace]'
KEY = '_bl4_tps_aim_origin_owner'
RETIRED = '_bl4_tps_aim_origin_retired'
ROUTE = 'bl4tps.aim_origin.frame'

FUNCTION_RVA = 0xC8D630
FUNCTION_SIZE = 0x576
FUNCTION_SHA256 = '8955a925fc4620dd73885a3dc7f4766af70980b2abd4ce4ed3c6bddae1c90800'
RVA = 0xC8DA03
ORIGINAL = bytes.fromhex('4c8d8424700100004c8d8c2440010000')  # lea r8,[rsp+0x170]; lea r9,[rsp+0x140]
RETURN_RVA = RVA + len(ORIGINAL)
RETURN_BYTES = bytes.fromhex('4889c14c89f2')  # mov rcx,rax; mov rdx,r14 (then call trace)
MANAGER_RUNTIME = 0x3A48     # camera runtime -> definition +0x10 -> flags +0x1C
FIRST_PERSON_FLAG = 0x02     # same test as manager vfunc 0x878 (0x4904A5C)

STUB = bytes.fromhex(
    '49ba017766554433221149833a010f85a1010000f049ff4208493b5a100f8586010000f20f10842440010000'
    'f20f5c842470010000f20f108c2448010000f20f5c8c2478010000f20f10942450010000f20f5c9424800100'
    '00660f28d8f20f59db660f28e1f20f59e4f20f58dc660f28e2f20f59e4f20f58dcf20f51db66410f2e9aa800'
    '00000f8a240100000f861e010000f20f5ec3f20f5ecbf20f5ed3f2410f106220f20f5ca42470010000f20f59'
    'e0f2410f106a28f20f5cac2478010000f20f59e9f20f58e5f2410f106a30f20f5cac2480010000f20f59eaf2'
    '0f58e5f2410f586250f2410f11a2a0000000660f57ed660f2ee50f8ab40000000f86ae00000066410f2e6258'
    '0f8aa20000000f839c000000660f2ee30f83920000004c8b9c24700100004d895a704c8b9c24780100004d89'
    '5a784c8b9c24800100004d899a80000000f20f59c4f20f58842470010000f20f11842470010000f2410f1182'
    '88000000f20f59ccf20f588c2478010000f20f118c2478010000f2410f118a90000000f20f59d4f20f589424'
    '80010000f20f11942480010000f2410f119298000000f049ff4218eb0cf049ff4268eb05f049ff42604c8d84'
    '24700100004c8d8c2440010000ff25000000000277665544332211')
STUB_SHA256 = '482f64f964c96da2fecfdf5fcbada7b700de972567c05d9075a876b6df87ba5c'
CONTROL_SENTINEL = 0x1122334455667701
RETURN_SENTINEL = 0x1122334455667702

# Control block layout (owned by Python, read by the stub).
ENABLED, VISITS, CONTROLLER, APPLIED = 0x00, 0x08, 0x10, 0x18
PAWN, MARGIN, MAX_DEPTH = 0x20, 0x50, 0x58
SKIPPED, MISMATCH, LAST_START, LAST_SHIFTED, LAST_DEPTH, MIN_LENGTH = 0x60, 0x68, 0x70, 0x88, 0xA0, 0xA8
CONTROL_SIZE = 0x1000
CODE_SIZE = 0x1000

# Read only by the FireBeam origin stub: its query is a radius-20 sweep that
# also decides the hits, so the beam keeps its own margin (`beam_margin`).
BEAM_MARGIN = 0xB0
DEFAULT_MARGIN = 70.0        # cm in front of the capsule centre
DEFAULT_MAX_DEPTH = 1500.0   # cm; larger depths mean an unexpected origin
# Beam: geometry closer than this on the crosshair ray is not queried. Smaller
# values keep cover right in front of the gun; larger ones clear wall edges.
DEFAULT_BEAM_MARGIN = 70.0


def stub(control, return_address):
    """Relocate the verified stub template."""
    replay = STUB[-14 - len(ORIGINAL):-14]
    if hashlib.sha256(STUB).hexdigest() != STUB_SHA256 or replay != ORIGINAL:
        raise RuntimeError('Aim-trace stub fingerprint changed')
    code = STUB
    for sentinel, value in ((CONTROL_SENTINEL, control), (RETURN_SENTINEL, return_address)):
        needle = struct.pack('<Q', sentinel)
        if code.count(needle) != 1:
            raise RuntimeError('Aim-origin stub relocation mismatch')
        code = code.replace(needle, struct.pack('<Q', value))
    return code


def absolute_jump(target):
    return b'\xff\x25\x00\x00\x00\x00' + struct.pack('<Q', target)


def patch_bytes(code_address):
    jump = absolute_jump(code_address)
    return jump + b'\x90' * (len(ORIGINAL) - len(jump))


def finite(values):
    return all(isinstance(v, float) and math.isfinite(v) for v in values)


class Native:
    """Windows memory access; replaced by fakes in tests."""

    def __init__(self):
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        ptr, size = ctypes.c_void_p, ctypes.c_size_t
        for name, args, result in (
                ('GetModuleHandleW', [ctypes.c_wchar_p], ptr),
                ('GetCurrentProcess', [], ptr),
                ('ReadProcessMemory', [ptr, ptr, ptr, size, ctypes.POINTER(size)], ctypes.c_int),
                ('WriteProcessMemory', [ptr, ptr, ptr, size, ctypes.POINTER(size)], ctypes.c_int),
                ('VirtualProtect', [ptr, size, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)], ctypes.c_int),
                ('FlushInstructionCache', [ptr, ptr, size], ctypes.c_int),
                ('VirtualAlloc', [ptr, size, ctypes.c_ulong, ctypes.c_ulong], ptr)):
            fn = getattr(k, name)
            fn.argtypes, fn.restype = args, result
        self.k = k
        self.handle = k.GetCurrentProcess()
        self.base = int(k.GetModuleHandleW(None) or 0)

    def read(self, address, count):
        if address < 0x10000 or not 0 < count <= 0x10000:
            raise RuntimeError('Read outside bounds')
        buf, got = ctypes.create_string_buffer(count), ctypes.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, address, buf, count, ctypes.byref(got)) \
                or got.value != count:
            raise OSError('ReadProcessMemory failed')
        return buf.raw

    def write_code(self, address, data):
        old = ctypes.c_ulong()
        if not self.k.VirtualProtect(address, len(data), 0x40, ctypes.byref(old)):
            raise OSError('VirtualProtect failed')
        try:
            buf, done = ctypes.create_string_buffer(data), ctypes.c_size_t()
            if not self.k.WriteProcessMemory(self.handle, address, buf, len(data), ctypes.byref(done)) \
                    or done.value != len(data):
                raise OSError('WriteProcessMemory failed')
            if not self.k.FlushInstructionCache(self.handle, address, len(data)):
                raise OSError('FlushInstructionCache failed')
        finally:
            unused = ctypes.c_ulong()
            if not self.k.VirtualProtect(address, len(data), old.value, ctypes.byref(unused)):
                raise OSError('Page protection restore failed; restart game')

    def allocate(self, size):
        address = int(self.k.VirtualAlloc(None, size, 0x3000, 0x04) or 0)
        if not address:
            raise OSError('VirtualAlloc failed; no game code changed')
        return address

    def publish_code(self, address, code):
        ctypes.memmove(address, code, len(code))
        old = ctypes.c_ulong()
        if not self.k.VirtualProtect(address, CODE_SIZE, 0x20, ctypes.byref(old)):
            raise OSError('Stub executable protection failed')
        if not self.k.FlushInstructionCache(self.handle, address, len(code)):
            raise OSError('Stub instruction-cache flush failed')

    def store(self, address, data):
        ctypes.memmove(address, data, len(data))


# Process-lifetime control block. Every aim-trace install and the FireBeam
# origin stub (0.3.9.12) read the same block, so `bl4tps_aim off`, the margin
# and the published pawn position govern both. Never freed: a retired stub may
# still be executing when a new one installs.
SHARED_CONTROL = '_bl4_tps_aim_control'


def shared_control(native):
    """Address of the shared control block, allocated once per game module."""
    holder = sys.modules.get(SHARED_CONTROL)
    if holder is not None and holder.base == native.base:
        return holder.address
    address = native.allocate(CONTROL_SIZE)
    native.store(address, bytes(MIN_LENGTH))
    native.store(address + MIN_LENGTH, struct.pack('<d', 1.0))
    holder = types.ModuleType(SHARED_CONTROL)
    holder.base = native.base
    holder.address = address
    sys.modules[SHARED_CONTROL] = holder
    return address


def install(native):
    """Verify build, function hash and bytes; write the detour. Returns the state."""
    state = sys.modules.get(KEY)
    if state is not None:
        return state
    base, read = native.base, native.read
    if not base or parse_pe_identity(read, base) != REVIEWED_BUILD:
        raise RuntimeError('Build differs from the reviewed build; no patch attempted')
    if hashlib.sha256(read(base + FUNCTION_RVA, FUNCTION_SIZE)).hexdigest() != FUNCTION_SHA256:
        raise RuntimeError('Aim-trace function fingerprint changed')
    if read(base + RVA, len(ORIGINAL)) != ORIGINAL:
        raise RuntimeError('Aim-trace capture site differs from original bytes')
    if read(base + RETURN_RVA, len(RETURN_BYTES)) != RETURN_BYTES:
        raise RuntimeError('Aim-trace return site differs')
    state = types.ModuleType(KEY)
    state.base = base
    state.control = shared_control(native)
    state.code = native.allocate(CODE_SIZE)
    # Disabled with fresh counters until the next published frame.
    native.store(state.control, bytes(MIN_LENGTH))
    native.store(state.control + MIN_LENGTH, struct.pack('<d', 1.0))
    native.publish_code(state.code, stub(state.control, base + RETURN_RVA))
    state.patch = patch_bytes(state.code)
    sys.modules[KEY] = state  # recovery metadata precedes the code write
    try:
        native.write_code(base + RVA, state.patch)
        if read(base + RVA, len(state.patch)) != state.patch:
            raise RuntimeError('Aim-trace patch readback mismatch')
    except Exception:
        current = read(base + RVA, len(ORIGINAL))
        if current == state.patch:
            native.write_code(base + RVA, ORIGINAL)
        if read(base + RVA, len(ORIGINAL)) == ORIGINAL:
            del sys.modules[KEY]
        raise
    return state


def restore(native):
    """Put the original bytes back; keep code/control pinned. True when clean."""
    state = sys.modules.get(KEY)
    if state is None:
        return True
    if state.base != native.base:
        raise RuntimeError('Saved aim-trace patch belongs to another module base')
    native.store(state.control, struct.pack('<Q', 0))  # disable first
    address = state.base + RVA
    current = native.read(address, len(ORIGINAL))
    if current == state.patch:
        native.write_code(address, ORIGINAL)
    elif current != ORIGINAL:
        raise RuntimeError('Aim-trace restore refused: bytes changed by another writer')
    if native.read(address, len(ORIGINAL)) != ORIGINAL:
        return False
    retired = sys.modules.get(RETIRED)
    if retired is None:
        retired = types.ModuleType(RETIRED)
        retired.allocations = []
        sys.modules[RETIRED] = retired
    retired.allocations.append(state)
    del sys.modules[KEY]
    return True


def counters(native, state):
    raw = native.read(state.control, 0xA8)
    q = lambda off: struct.unpack_from('<Q', raw, off)[0]
    d = lambda off, n=3: list(struct.unpack_from('<%dd' % n, raw, off))
    return dict(enabled=q(ENABLED), visits=q(VISITS), applied=q(APPLIED), skipped=q(SKIPPED),
                mismatch=q(MISMATCH), last_start=d(LAST_START), last_shifted=d(LAST_SHIFTED),
                last_depth=d(LAST_DEPTH, 1)[0])


class Owner:
    """Per-frame control publisher on the owned game-thread widget tick."""

    def __init__(self, mod, native_factory=Native):
        self.mod = mod
        self.native_factory = native_factory
        self.native = None
        self.wanted = True
        self.margin = DEFAULT_MARGIN
        self.beam_margin = DEFAULT_BEAM_MARGIN
        self.max_depth = DEFAULT_MAX_DEPTH
        self.registered = False
        self.active = False
        self.busy = False
        self.install_error = None
        self.last_error = None
        self.enabled = False
        self.reason = 'starting'

    # -- lifecycle -------------------------------------------------------------
    def start(self, updates):
        from unrealsdk import hooks

        self.updates = updates
        spec = (self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, ROUTE)
        if updates.has_hook(*spec):
            raise RuntimeError('Aim-origin route already registered')
        self.spec = spec
        self.registered = True
        updates.add_hook(*spec, self.frame)
        if not updates.has_hook(*spec):
            raise RuntimeError('Aim-origin route registration unverified')
        self.active = True

    def close(self):
        self.active = False
        clean = True
        if self.native is not None or sys.modules.get(KEY) is not None:
            native = self.native or self.native_factory()
            clean = restore(native)
        if self.registered:
            if self.updates.has_hook(*self.spec):
                self.updates.remove_hook(*self.spec)
            if self.updates.has_hook(*self.spec):
                return False
            self.registered = False
        return clean

    # -- per frame ---------------------------------------------------------------
    def disable(self, reason):
        self.reason = reason
        state = sys.modules.get(KEY)
        if state is not None and self.native is not None:
            self.native.store(state.control + ENABLED, struct.pack('<Q', 0))
        self.enabled = False

    def eligible(self, pc, pawn, manager):
        mod = self.mod
        if not self.wanted:
            return 'off'
        if pc is None or pawn is None or manager is None:
            return 'no_runtime'
        if not (mod._third_person_enabled and mod._third_person_pushed):
            return 'not_tps'
        if getattr(mod, '_vehicle_camera_active', False):
            return 'vehicle'
        if str(pawn.Class.Name) != 'OakCharacter':
            return 'not_character'
        runtime = struct.unpack('<Q', mod._native_read(int(manager._get_address()) + MANAGER_RUNTIME, 8))[0]
        definition = struct.unpack('<Q', mod._native_read(runtime + 0x10, 8))[0] if runtime else 0
        if not definition or mod._native_read(definition + 0x1C, 1)[0] & FIRST_PERSON_FLAG:
            return 'first_person_view'
        return None

    def frame(self, obj, args, ret, func):
        if not self.active or self.busy or not self.updates.is_game_thread():
            return
        if _owner is not self:
            return  # orphaned by a module reload; the current owner publishes
        self.busy = True
        try:
            self.update()
        except Exception as exc:
            text = repr(exc)[:300]
            self.disable('error')
            if text != self.last_error:
                self.last_error = text
                self.mod.logging.error(TAG + ' UPDATE_FAILED correction paused: ' + text)
        finally:
            self.busy = False

    def update(self):
        pc, pawn, manager = self.mod._get_runtime()
        reason = self.eligible(pc, pawn, manager)
        if reason is not None:
            self.disable(reason)
            return
        if self.install_error is not None:
            # Also covers a refused install whose rollback kept the state.
            self.disable('install_failed')
            return
        state = sys.modules.get(KEY)
        if state is None:
            try:
                self.native = self.native or self.native_factory()
                state = install(self.native)
                self.mod.logging.info(TAG + ' ARMED rva=0xC8DA03 native_patches=1')
                if not self.active:
                    # Closed while installing (disable off the game thread).
                    restore(self.native)
                    return
            except Exception as exc:
                self.install_error = repr(exc)[:300]
                self.mod.logging.error(TAG + ' INSTALL_REFUSED ' + self.install_error)
                self.disable('install_failed')
                return
        location = pawn.K2_GetActorLocation()
        pawn_location = (float(location.X), float(location.Y), float(location.Z))
        if not finite(pawn_location):
            self.disable('nonfinite')
            return
        self.native.store(state.control + CONTROLLER, struct.pack('<Q', int(pc._get_address())))
        self.native.store(state.control + PAWN, struct.pack('<3d', *pawn_location))
        self.native.store(state.control + MARGIN, struct.pack('<2d', self.margin, self.max_depth))
        self.native.store(state.control + BEAM_MARGIN, struct.pack('<d', self.beam_margin))
        # Every frame after the data: a re-installed control block (new state)
        # must never stay disabled because of a stale Python flag.
        self.native.store(state.control + ENABLED, struct.pack('<Q', 1))
        self.enabled = True
        self.reason = 'active'

    def status(self):
        state = sys.modules.get(KEY)
        result = dict(wanted=self.wanted, enabled=self.enabled, reason=self.reason, margin=self.margin,
                      beam_margin=self.beam_margin,
                      installed=state is not None, install_error=self.install_error,
                      last_error=self.last_error)
        if state is not None and self.native is not None:
            result.update(counters(self.native, state))
        if self.native is not None:
            try:
                from . import native_beam_origin
                beam = native_beam_origin.depth_counters(self.native.read)
            except (ImportError, RuntimeError, OSError) as exc:
                beam = dict(error=repr(exc)[:160])
            if beam is not None:
                result['beam'] = beam
        return result


_owner = None


def start(mod, updates):
    global _owner
    if not shutdown():
        raise RuntimeError('Aim-origin cleanup incomplete')
    _owner = Owner(mod)
    try:
        _owner.start(updates)
    except Exception:
        shutdown()
        raise


def shutdown():
    global _owner
    if _owner is None:
        state = sys.modules.get(KEY)
        return True if state is None else restore(Native())
    if not _owner.close():
        return False
    _owner = None
    return True


def owner():
    return _owner
