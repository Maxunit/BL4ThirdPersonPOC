"""0.3.9.12: FireBeam query origin at character depth (native stub executed on Linux x64)."""
import ctypes
import hashlib
import math
import mmap
import platform
import struct
import sys
import unittest
from types import SimpleNamespace as S

import support  # noqa: F401  (SDK stand-ins)

if not hasattr(sys.modules['unrealsdk'], 'find_all'):
    sys.modules['unrealsdk'].find_all = lambda *args: []
from BL4ThirdPersonPOC import native_beam_origin as beam  # noqa: E402

NATIVE = sys.platform.startswith('linux') and platform.machine() in ('x86_64', 'AMD64')

# SysV wrapper: rdi=receiver, rsi=results, rdx=stub. Presets rcx/rdx/r8-r11/rax and
# xmm0-2 (from results+0x100), calls the stub as the game would call 0xA640F0, then
# stores every argument/scratch register, xmm0-2 and the x87 environment.
WRAPPER = bytes.fromhex(
    '535541544155415641574989f44989d54889f948bad1d1d1d1d1d1d1d149b8888888888888888849b9'
    '999999999999999949ba101010101010101049bb0b0b0b0b0b0b0b0b48b8aaaaaaaaaaaaaaaaf3410f'
    '6f842400010000f3410f6f8c2410010000f3410f6f94242001000041ffd54989042449894c24084989'
    '5424104d894424184d894c24204d895424284d895c2430f3410f7f442440f3410f7f4c2450f3410f7f'
    '54246041d9b4248000000041d9a42480000000415f415e415d415c5d5bc3')
# Undo the replayed 0xA640F0 prologue (push r15,r14,rsi,rdi,rbx; sub rsp,0x190).
LANDING = bytes.fromhex('4881c4900100005b5f5e415e415fc3')

RECEIVER_TABLE = 0x7FF60B7931C0
ROTATION = 0x1928
PRESET = (0xAAAAAAAAAAAAAAAA, None, 0xD1D1D1D1D1D1D1D1, 0x8888888888888888,
          0x9999999999999999, 0x1010101010101010, 0x0B0B0B0B0B0B0B0B)


class Region:
    def __init__(self, size, prot):
        self.map = mmap.mmap(-1, size, prot=prot)
        self.address = ctypes.addressof(ctypes.c_char.from_buffer(self.map))

    def put(self, offset, data):
        self.map[offset:offset + len(data)] = data

    def get(self, offset, fmt):
        return struct.unpack_from(fmt, self.map, offset)


@unittest.skipUnless(NATIVE, 'native stub execution needs Linux x86-64')
class BeamStubExecutionTests(unittest.TestCase):
    RECEIVER, WEAPON, PAWN, CONTROLLER = 0x0000, 0x1000, 0x2000, 0x3000
    MANAGER, RUNTIME, DEFINITION, CONTROL = 0x6000, 0xA000, 0xB000, 0xC000
    BUFFER, RESULTS = 0x10000, 0x20000

    def setUp(self):
        self.data = Region(0x30000, mmap.PROT_READ | mmap.PROT_WRITE)
        self.code = Region(0x2000, mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
        a = self.addr
        q = lambda off, value: self.data.put(off, struct.pack('<Q', value))
        q(self.RECEIVER, RECEIVER_TABLE)
        q(self.RECEIVER + 0xC8, a(self.WEAPON))
        self.data.put(self.RECEIVER + 0x2EA, struct.pack('<H', 5))
        q(self.WEAPON + 0x1B0, a(self.PAWN))
        q(self.PAWN + 0x3C0, a(self.CONTROLLER))
        q(self.CONTROLLER + 0x2500, a(self.MANAGER))
        q(self.MANAGER + 0x3A48, a(self.RUNTIME))
        q(self.RUNTIME + 0x10, a(self.DEFINITION))
        self.camera(100.0, 200.0, 300.0, pitch=0.0, yaw=0.0)
        self.control(enabled=1, pawn=(350.0, 260.0, 280.0), margin=70.0, max_depth=1500.0)
        self.landing = self.code.address + 0x800
        self.code.put(0x800, LANDING)
        self.code.put(0xA00, WRAPPER)
        self.install(a(self.CONTROL))
        self.call = ctypes.CFUNCTYPE(None, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64)(
            self.code.address + 0xA00)
        for i, value in enumerate((1.25, -2.5, 3.75)):
            self.data.put(self.RESULTS + 0x100 + i * 16, struct.pack('<dd', value, -value))

    def tearDown(self):
        del self.call
        self.code.map.close()
        self.data.map.close()

    def addr(self, offset):
        return self.data.address + offset

    def install(self, control):
        blob = beam.recorder(self.addr(self.BUFFER), self.addr(self.WEAPON), RECEIVER_TABLE,
                             self.landing, control, ROTATION)
        self.code.put(0, blob)

    def camera(self, x, y, z, pitch, yaw, roll=0.0):
        self.data.put(self.MANAGER + 0x1910, struct.pack('<3d', x, y, z))
        self.data.put(self.MANAGER + ROTATION, struct.pack('<3d', pitch, yaw, roll))

    def control(self, enabled, pawn, margin, max_depth, aim_margin=999.0):
        """Shared block: +0x50 is the bullets' margin, +0xB0 the beam's own."""
        self.data.put(self.CONTROL, struct.pack('<Q', enabled))
        self.data.put(self.CONTROL + 0x20, struct.pack('<3d', *pawn))
        self.data.put(self.CONTROL + 0x50, struct.pack('<2d', aim_margin, max_depth))
        self.data.put(self.CONTROL + 0xB0, struct.pack('<d', margin))

    def run_stub(self):
        self.call(self.addr(self.RECEIVER), self.addr(self.RESULTS), self.code.address)
        regs = self.data.get(self.RESULTS, '<7Q')
        for value, expected in zip(regs, PRESET):
            if expected is not None:
                self.assertEqual(value, expected)
        self.assertEqual(regs[1], self.addr(self.RECEIVER), 'rcx (receiver) preserved')
        for i in range(3):
            self.assertEqual(self.data.get(self.RESULTS + 0x40 + i * 16, '<2Q'),
                             self.data.get(self.RESULTS + 0x100 + i * 16, '<2Q'), 'xmm%d' % i)
        tag = self.data.get(self.RESULTS + 0x80 + 8, '<H')[0]
        self.assertEqual(tag, 0xFFFF, 'x87 stack empty after the stub')
        return self.data.get(self.RECEIVER + 0x388, '<3d')

    def counters(self):
        return self.data.get(self.BUFFER + beam.DEPTH_COUNTERS, '<3Q')

    def test_straight_view_moves_the_origin_to_character_depth(self):
        origin = self.run_stub()
        self.assertEqual(origin, (420.0, 200.0, 300.0))  # (350-100) + 70 along +X
        self.assertEqual(self.counters(), (0, 1, 0))
        record = self.BUFFER + 0x20
        self.assertEqual(self.data.get(record + 0x48, '<3d'), (420.0, 200.0, 300.0))
        self.assertEqual(self.data.get(record + 0xA8, '<3d'), (100.0, 200.0, 300.0))
        self.assertEqual(self.data.get(record + 0xC0, '<d'), (320.0,))
        self.assertEqual(self.data.get(record + 0xC8, '<Q'), (1,))
        self.assertEqual(self.data.get(self.BUFFER, '<Q'), (1,))

    def test_beam_margin_is_independent_of_the_bullet_margin(self):
        self.control(1, (350.0, 260.0, 280.0), margin=20.0, max_depth=1500.0, aim_margin=70.0)
        self.assertEqual(self.run_stub(), (370.0, 200.0, 300.0))

    def test_oblique_view_stays_on_the_crosshair_ray(self):
        pitch, yaw = -20.0, 135.0
        self.camera(-5000.0, 1200.0, 40.0, pitch=pitch, yaw=yaw)
        p, y = math.radians(pitch), math.radians(yaw)
        d = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
        camera = (-5000.0, 1200.0, 40.0)
        pawn = tuple(c + 260.0 * k + o for c, k, o in zip(camera, d, (30.0, -10.0, 5.0)))
        self.control(1, pawn, 70.0, 1500.0)
        depth = sum((pv - cv) * k for pv, cv, k in zip(pawn, camera, d)) + 70.0
        origin = self.run_stub()
        for got, c, k in zip(origin, camera, d):
            self.assertAlmostEqual(got, c + k * depth, places=6)
        self.assertAlmostEqual(self.data.get(self.BUFFER + beam.DEPTH_LAST, '<d')[0], depth, places=6)

    def test_disabled_or_out_of_range_writes_the_camera_position(self):
        cases = (
            ('disabled', dict(enabled=0, pawn=(350.0, 260.0, 280.0), margin=70.0, max_depth=1500.0), 0),
            ('behind camera', dict(enabled=1, pawn=(-500.0, 200.0, 300.0), margin=70.0, max_depth=1500.0), 2),
            ('beyond max', dict(enabled=1, pawn=(5000.0, 200.0, 300.0), margin=70.0, max_depth=1500.0), 2),
        )
        for name, control, status in cases:
            with self.subTest(name):
                self.control(**control)
                self.data.put(self.RECEIVER + 0x388, bytes(24))
                before = self.counters()
                self.assertEqual(self.run_stub(), (100.0, 200.0, 300.0))
                after = self.counters()
                self.assertEqual(after[status] - before[status], 1)

    def test_nonfinite_rotation_never_shifts(self):
        self.camera(100.0, 200.0, 300.0, pitch=float('nan'), yaw=0.0)
        self.assertEqual(self.run_stub(), (100.0, 200.0, 300.0))
        self.assertEqual(self.counters(), (0, 0, 1))

    def test_missing_shared_control_uses_the_zero_qword(self):
        self.install(self.addr(self.BUFFER + beam.DISABLED_CONTROL))
        self.assertEqual(self.run_stub(), (100.0, 200.0, 300.0))
        self.assertEqual(self.counters(), (1, 0, 0))

    def test_ineligible_calls_write_nothing(self):
        cases = (
            ('other receiver class', self.RECEIVER, struct.pack('<Q', RECEIVER_TABLE + 8)),
            ('other mode', self.RECEIVER + 0x2EA, struct.pack('<H', 4)),
            ('first-person definition', self.DEFINITION + 0x1C, b'\x02'),
        )
        for name, offset, data in cases:
            with self.subTest(name):
                saved = bytes(self.data.map[offset:offset + len(data)])
                self.data.put(offset, data)
                self.data.put(self.RECEIVER + 0x388, struct.pack('<3d', 7.0, 8.0, 9.0))
                self.assertEqual(self.run_stub(), (7.0, 8.0, 9.0))
                self.data.put(offset, saved)
        self.assertEqual(self.counters(), (0, 0, 0))

    def test_after_the_record_limit_the_origin_is_still_written(self):
        self.data.put(self.BUFFER, struct.pack('<Q', beam.LIMIT))
        self.assertEqual(self.run_stub(), (420.0, 200.0, 300.0))
        self.assertEqual(self.data.get(self.BUFFER, '<Q'), (beam.LIMIT + 1,))


class TemplateTests(unittest.TestCase):
    def test_documented_source_produces_the_shipped_template(self):
        try:
            import keystone  # noqa: F401
        except ImportError:
            self.skipTest('keystone-engine not installed')
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'docs'))
        try:
            import beam_origin_stub_source as source
        finally:
            sys.path.pop(0)
        self.assertEqual(source.assemble(), beam.TEMPLATE)

    def test_template_hash_relocation_and_replayed_entry(self):
        self.assertEqual(hashlib.sha256(beam.TEMPLATE).hexdigest(), beam.TEMPLATE_SHA256)
        code = beam.recorder(0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x1928)
        for sentinel, _, _ in beam.SENTINELS:
            self.assertNotIn(struct.pack('<Q', sentinel), code)
        self.assertEqual(code[-14 - len(beam.ORIGINAL):-14], beam.ORIGINAL)
        self.assertEqual(code[-8:], struct.pack('<Q', 0x4000))

    def test_stub_restores_every_register_it_uses(self):
        try:
            import capstone
        except ImportError:
            self.skipTest('capstone not installed')
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        code = beam.recorder(0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x1928)
        body = code[:-14 - len(beam.ORIGINAL)]
        allowed = {'rax', 'r10', 'r11', 'rsp', 'rflags', 'rip', 'xmm0', 'xmm1', 'eax',
                   'fpsw', 'fpcw', 'fpsr'} | {'st(%d)' % i for i in range(8)} | {
                   'st%d' % i for i in range(8)}
        for ins in md.disasm(body, 0):
            written = {ins.reg_name(r) for r in ins.regs_access()[1]}
            self.assertLessEqual(written, allowed, (hex(ins.address), ins.mnemonic, ins.op_str))
            self.assertNotEqual(ins.mnemonic, 'call')


class DepthSourceTests(unittest.TestCase):
    """Reflection layout and live cross-check decide whether the shift is armed."""

    def prop(self, name, kind, offset, **kw):
        return S(Name=name, Class=S(Name=kind), Offset_Internal=offset, **kw)

    def struct_type(self, name, props):
        return S(Name=name, _superfields=lambda: (), _properties=lambda: props)

    def setUp(self):
        rotator = self.struct_type('Rotator', [self.prop('Pitch', 'DoubleProperty', 0),
                                               self.prop('Yaw', 'DoubleProperty', 8),
                                               self.prop('Roll', 'DoubleProperty', 16)])
        vector = self.struct_type('Vector', [])
        view = self.struct_type('MinimalViewInfo', [
            self.prop('Location', 'StructProperty', 0, Struct=vector),
            self.prop('Rotation', 'StructProperty', 0x18, Struct=rotator)])
        entry = self.struct_type('CameraCacheEntry', [self.prop('POV', 'StructProperty', 0x10, Struct=view)])
        self.cls = self.struct_type('OakPlayerCameraManager', [
            self.prop('CameraCachePrivate', 'StructProperty', 0x1900, Struct=entry)])
        self.pov = S(Location=S(X=1.0, Y=2.0, Z=3.0), Rotation=S(Pitch=-10.0, Yaw=45.0, Roll=0.0))
        self.camera = S(Class=self.cls, CameraCachePrivate=S(POV=self.pov))
        self.memory = {0x1910: struct.pack('<3d', 1.0, 2.0, 3.0), 0x1928: struct.pack('<3d', -10.0, 45.0, 0.0)}

    def read(self, address, count):
        return self.memory[address][:count]

    def test_reflected_layout_and_live_values_arm_the_shift(self):
        self.assertEqual(beam.camera_cache_layout(self.cls), (0x1910, 0x1928))
        result = beam.depth_source(self.camera, 0, self.read, 0xC0FFEE)
        self.assertEqual((result['enabled'], result['control'], result['rotation_offset']),
                         (True, 0xC0FFEE, 0x1928))

    def test_mismatches_keep_the_camera_origin(self):
        self.memory[0x1928] = struct.pack('<3d', -10.0, 46.0, 0.0)
        self.assertFalse(beam.depth_source(self.camera, 0, self.read, 0xC0FFEE)['enabled'])
        self.memory[0x1928] = struct.pack('<3d', -10.0, 45.0, 0.0)
        self.assertFalse(beam.depth_source(self.camera, 0, self.read, 0)['enabled'])
        self.cls._properties()[0].Offset_Internal = 0x1908
        result = beam.depth_source(self.camera, 0, self.read, 0xC0FFEE)
        self.assertFalse(result['enabled'])
        self.assertIn('0x1910', result['reason'])

    def test_float_rotator_layout_is_refused(self):
        rotator = self.cls._properties()[0].Struct._properties()[0].Struct._properties()[1].Struct
        rotator._properties()[1].Class.Name = 'FloatProperty'
        self.assertFalse(beam.depth_source(self.camera, 0, self.read, 0xC0FFEE)['enabled'])



class SharedControlTests(unittest.TestCase):
    """Beam stub and aim-trace installs share one process-lifetime control block."""

    def setUp(self):
        import hashlib as _hashlib
        import test_aim_trace_0_3_9_9 as aimtests
        from BL4ThirdPersonPOC import native_aim_origin as aim
        self.aim, self.aimtests = aim, aimtests
        self.saved = aim.FUNCTION_SHA256
        aim.FUNCTION_SHA256 = _hashlib.sha256(aimtests.FUNCTION).hexdigest()
        for key in (aim.KEY, aim.SHARED_CONTROL):
            sys.modules.pop(key, None)

    def tearDown(self):
        self.aim.FUNCTION_SHA256 = self.saved
        for key in (self.aim.KEY, self.aim.SHARED_CONTROL):
            sys.modules.pop(key, None)

    def test_beam_first_then_aim_install_restore_install(self):
        native = self.aimtests.FakeNative()
        control = self.aim.shared_control(native)  # beam armed before the aim trace
        state = self.aim.install(native)
        self.assertEqual(state.control, control)
        native.store(control, struct.pack('<Q', 1))
        self.assertTrue(self.aim.restore(native))
        self.assertEqual(native.read(control, 8), bytes(8), 'restore disables the beam shift too')
        self.assertEqual(self.aim.install(native).control, control)
        self.assertEqual(struct.unpack('<d', native.read(control + self.aim.MIN_LENGTH, 8)), (1.0,))


if __name__ == '__main__':
    unittest.main()
