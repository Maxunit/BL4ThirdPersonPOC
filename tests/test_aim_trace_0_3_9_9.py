"""0.3.9.9: TPS aim trace starts at character depth (stub executed natively on Linux x64)."""
import ctypes
import hashlib
import math
import mmap
import platform
import struct
import sys
import unittest
from types import SimpleNamespace as S

import support
from BL4ThirdPersonPOC import native_aim_origin as aim

NATIVE = sys.platform.startswith('linux') and platform.machine() in ('x86_64', 'AMD64')


WRAP_IN = bytes.fromhex(
    '5341544889f34881eca801000048c7c1090000004831d2488b84d740010000488984d44001000048ffc248ffc975e8'
    '48b85a5a5a5a5a5a5a5a49bb')  # + stub address, then 41ffe3 (jmp r11)
WRAP_OUT = bytes.fromhex(
    '488987f8010000488d8c24700100004929c84c8987e8010000488d8c24400100004929c94c898ff0010000'
    '48c7c1090000004831d2488b84d440010000488984d74001000048ffc248ffc975e84881c4a8010000415c5bc3')
MAGIC = 0x5A5A5A5A5A5A5A5A


class StubRunner:
    """Run the relocated stub inside a fake 0xC8D630 frame.

    SysV wrapper (rdi=frame image, rsi=controller): rbx=controller, frame bytes
    0x140..0x188 copied to [rsp+0x140] (End at +0x140, Start at +0x170),
    rax=MAGIC. The landing stores rax, r8-(rsp+0x170), r9-(rsp+0x140) and copies
    the frame back.
    """

    def __init__(self):
        self.memory = mmap.mmap(-1, 0x2000, prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
        self.view = (ctypes.c_char * 0x2000).from_buffer(self.memory)
        self.base = ctypes.addressof(self.view)
        self.control = ctypes.create_string_buffer(aim.CONTROL_SIZE)
        struct.pack_into('<d', self.control, aim.MIN_LENGTH, 1.0)
        code = aim.stub(ctypes.addressof(self.control), self.base + 0x900)
        self.memory[0:len(code)] = code
        wrapper = WRAP_IN + struct.pack('<Q', self.base) + bytes.fromhex('41ffe3')
        self.memory[0x800:0x800 + len(wrapper)] = wrapper
        self.memory[0x900:0x900 + len(WRAP_OUT)] = WRAP_OUT
        self.call = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(self.base + 0x800)

    def set(self, offset, fmt, *values):
        struct.pack_into(fmt, self.control, offset, *values)

    def get(self, offset, fmt):
        return struct.unpack_from(fmt, self.control, offset)

    def run(self, controller, start, end):
        frame = ctypes.create_string_buffer(0x200)
        struct.pack_into('<3d', frame, 0x140, *end)
        struct.pack_into('<3d', frame, 0x158, 11.0, 22.0, 33.0)   # rotation slot: untouched
        struct.pack_into('<3d', frame, 0x170, *start)
        self.call(ctypes.addressof(frame), controller)
        rax, r8, r9 = (struct.unpack_from('<Q', frame, o)[0] for o in (0x1F8, 0x1E8, 0x1F0))
        self.assertions = dict(rax=rax, r8=r8, r9=r9, rotation=struct.unpack_from('<3d', frame, 0x158),
                               end=struct.unpack_from('<3d', frame, 0x140))
        return struct.unpack_from('<3d', frame, 0x170)

    def close(self):
        del self.view
        self.memory.close()


@unittest.skipUnless(NATIVE, 'native stub execution needs Linux x86-64')
class StubExecutionTests(unittest.TestCase):
    PC = 0x1204CF0040
    END = (100000.0, 0.0, 0.0)   # camera looks along +X, trace range 1000 m

    def setUp(self):
        self.r = StubRunner()
        self.r.set(aim.CONTROLLER, '<Q', self.PC)
        self.r.set(aim.PAWN, '<3d', 250.0, -60.0, -20.0)   # 250 cm ahead, beside the ray
        self.r.set(aim.MARGIN, '<2d', 40.0, 1500.0)

    def tearDown(self):
        self.r.close()

    def check_frame_contract(self):
        a = self.r.assertions
        self.assertEqual(a['rax'], MAGIC, 'rax (world) preserved')
        self.assertEqual((a['r8'], a['r9']), (0, 0), 'r8=&Start, r9=&End replayed')
        self.assertEqual(a['rotation'], (11.0, 22.0, 33.0))
        self.assertEqual(a['end'], self.END)

    def test_disabled_only_replays_the_argument_loads(self):
        start = self.r.run(self.PC, (0.0, 0.0, 0.0), self.END)
        self.assertEqual(start, (0.0, 0.0, 0.0))
        self.assertEqual(self.r.get(aim.VISITS, '<Q'), (0,))
        self.check_frame_contract()

    def test_enabled_starts_the_trace_at_pawn_depth_plus_margin(self):
        self.r.set(aim.ENABLED, '<Q', 1)
        start = self.r.run(self.PC, (0.0, 0.0, 0.0), self.END)
        for got, want in zip(start, (290.0, 0.0, 0.0)):
            self.assertAlmostEqual(got, want)
        self.assertEqual(self.r.get(aim.APPLIED, '<Q'), (1,))
        self.assertAlmostEqual(self.r.get(aim.LAST_DEPTH, '<d')[0], 290.0)
        self.assertEqual(self.r.get(aim.LAST_START, '<3d'), (0.0, 0.0, 0.0))
        self.check_frame_contract()

    def test_oblique_ray_stays_on_the_ray(self):
        self.r.set(aim.ENABLED, '<Q', 1)
        origin = (100.0, 200.0, 50.0)
        p, y = math.radians(-10.0), math.radians(30.0)
        direction = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
        end = tuple(o + d * 50000.0 for o, d in zip(origin, direction))
        start = self.r.run(self.PC, origin, end)
        depth = sum((q - o) * d for q, o, d in zip((250.0, -60.0, -20.0), origin, direction)) + 40.0
        for got, o, d in zip(start, origin, direction):
            self.assertAlmostEqual(got, o + d * depth, places=6)

    def test_other_controllers_are_not_touched(self):
        self.r.set(aim.ENABLED, '<Q', 1)
        start = self.r.run(self.PC + 8, (0.0, 0.0, 0.0), self.END)
        self.assertEqual(start, (0.0, 0.0, 0.0))
        self.assertEqual(self.r.get(aim.MISMATCH, '<Q'), (1,))
        self.check_frame_contract()

    def test_camera_already_in_front_of_the_pawn_is_kept(self):
        self.r.set(aim.ENABLED, '<Q', 1)
        start = self.r.run(self.PC, (400.0, 0.0, 0.0), self.END)   # depth = -150 + 40 < 0
        self.assertEqual(start, (400.0, 0.0, 0.0))
        self.assertEqual(self.r.get(aim.SKIPPED, '<Q'), (1,))

    def test_depth_beyond_range_limit_or_nan_is_skipped(self):
        self.r.set(aim.ENABLED, '<Q', 1)
        self.assertEqual(self.r.run(self.PC, (-5000.0, 0.0, 0.0), self.END), (-5000.0, 0.0, 0.0))
        short_end = (100.0, 0.0, 0.0)                      # pawn depth beyond the trace end
        self.assertEqual(self.r.run(self.PC, (0.0, 0.0, 0.0), short_end), (0.0, 0.0, 0.0))
        self.assertEqual(self.r.run(self.PC, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)), (0.0, 0.0, 0.0))
        self.r.set(aim.PAWN, '<3d', float('nan'), 0.0, 0.0)
        self.assertEqual(self.r.run(self.PC, (0.0, 0.0, 0.0), self.END), (0.0, 0.0, 0.0))
        self.assertEqual(self.r.get(aim.SKIPPED, '<Q'), (4,))
        self.assertEqual(self.r.get(aim.APPLIED, '<Q'), (0,))


class TemplateTests(unittest.TestCase):
    def test_documented_assembly_source_produces_the_shipped_stub(self):
        try:
            import keystone
        except ImportError:
            self.skipTest('keystone-engine not installed')
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1] / 'docs' / 'aim_trace_stub_source.py').read_text()
        asm = source.split('ASM = """', 1)[1].split('"""', 1)[0]
        encoded, _ = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64).asm(asm, 0)
        built = bytes(encoded) + b'\xff\x25\x00\x00\x00\x00' + struct.pack('<Q', aim.RETURN_SENTINEL)
        self.assertEqual(built, aim.STUB)

    def test_stub_replays_the_exact_replaced_bytes_before_returning(self):
        self.assertEqual(aim.STUB[-14 - 16:-14], aim.ORIGINAL)
        self.assertEqual(hashlib.sha256(aim.STUB).hexdigest(), aim.STUB_SHA256)
        self.assertEqual((aim.RVA, aim.RETURN_RVA), (0xC8DA03, 0xC8DA13))

    def test_stub_touches_only_scratch_registers(self):
        try:
            import capstone
        except ImportError:
            self.skipTest('capstone not installed')
        md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        md.detail = True
        allowed = {'r10', 'r11', 'r8', 'r9', 'rflags', 'rip'} | {f'xmm{i}' for i in range(6)}
        for ins in md.disasm(aim.STUB[:-8], 0):
            written = {ins.reg_name(r) for r in ins.regs_access()[1]}
            self.assertLessEqual(written, allowed, (hex(ins.address), ins.mnemonic, ins.op_str))
            self.assertNotEqual(ins.mnemonic, 'call')

    def test_relocation_and_patch_shape(self):
        code = aim.stub(0x1000, 0x2000)
        self.assertEqual(code.count(struct.pack('<Q', 0x1000)), 1)
        self.assertEqual(code[-8:], struct.pack('<Q', 0x2000))
        patch = aim.patch_bytes(0xABCDEF)
        self.assertEqual(len(patch), len(aim.ORIGINAL))
        self.assertEqual(patch[:6], b'\xff\x25\x00\x00\x00\x00')


BASE = 0x140000000
def _function():
    body = bytearray(bytes(range(256)) * 2 + bytes(aim.FUNCTION_SIZE - 512))
    at = aim.RVA - aim.FUNCTION_RVA
    body[at:at + 16] = aim.ORIGINAL
    body[at + 16:at + 22] = aim.RETURN_BYTES
    return bytes(body)


FUNCTION = _function()


class FakeNative:
    def __init__(self, stamp=0x6AA81051, original=aim.ORIGINAL):
        self.base = BASE
        self.mem = {}
        self.code_writes = []
        self.next = 0x70000000
        self.put(BASE, b'MZ' + bytes(58) + struct.pack('<I', 0x80))
        pe = bytearray(0x108)
        pe[:4] = b'PE\0\0'
        struct.pack_into('<HHI', pe, 4, 0x8664, 1, stamp)
        struct.pack_into('<H', pe, 24, 0x20B)
        struct.pack_into('<I', pe, 80, 0x31B8C000)
        self.put(BASE + 0x80, bytes(pe))
        self.put(BASE + aim.FUNCTION_RVA, FUNCTION)
        self.put(BASE + aim.RVA, original)

    def put(self, address, data):
        for i, b in enumerate(data):
            self.mem[address + i] = b

    def read(self, address, count):
        return bytes(self.mem.get(address + i, 0) for i in range(count))

    def write_code(self, address, data):
        self.code_writes.append((address, bytes(data)))
        self.put(address, data)

    def allocate(self, size):
        address, self.next = self.next, self.next + 0x10000
        return address

    def publish_code(self, address, code):
        self.put(address, code)

    def store(self, address, data):
        self.put(address, data)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.saved_hash = aim.FUNCTION_SHA256
        aim.FUNCTION_SHA256 = hashlib.sha256(FUNCTION).hexdigest()
        sys.modules.pop(aim.KEY, None)
        sys.modules.pop(aim.SHARED_CONTROL, None)

    def tearDown(self):
        aim.FUNCTION_SHA256 = self.saved_hash
        sys.modules.pop(aim.KEY, None)
        sys.modules.pop(aim.SHARED_CONTROL, None)

    def test_install_writes_the_detour_and_restore_puts_bytes_back(self):
        native = FakeNative()
        state = aim.install(native)
        self.assertEqual(native.read(BASE + aim.RVA, 16), state.patch)
        self.assertEqual(native.read(state.code + len(aim.STUB) - 30, 16), aim.ORIGINAL)
        self.assertIs(aim.install(native), state, 'second install reuses the owner')
        self.assertTrue(aim.restore(native))
        self.assertEqual(native.read(BASE + aim.RVA, 16), aim.ORIGINAL)
        self.assertNotIn(aim.KEY, sys.modules)
        self.assertTrue(aim.restore(native), 'nothing left to restore')

    def test_refusals_write_nothing(self):
        cases = [FakeNative(stamp=0x1), FakeNative(original=bytes(16))]
        for native in cases:
            with self.assertRaises(RuntimeError):
                aim.install(native)
            self.assertEqual(native.code_writes, [])
        aim.FUNCTION_SHA256 = '0' * 64
        native = FakeNative()
        with self.assertRaises(RuntimeError):
            aim.install(native)
        self.assertEqual(native.code_writes, [])

    def test_foreign_bytes_block_restore(self):
        native = FakeNative()
        aim.install(native)
        native.put(BASE + aim.RVA, b'\xcc' * 16)
        with self.assertRaises(RuntimeError):
            aim.restore(native)


class Vector(S):
    pass


def fake_mod(first_person=False, **overrides):
    memory = {}
    manager_address, runtime, definition = 0x9000, 0xA000, 0xB000
    memory[manager_address + aim.MANAGER_RUNTIME] = struct.pack('<Q', runtime)
    memory[runtime + 0x10] = struct.pack('<Q', definition)
    memory[definition + 0x1C] = bytes([aim.FIRST_PERSON_FLAG if first_person else 0])
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x5FCE00000,
             K2_GetActorLocation=lambda: S(X=250.0, Y=-60.0, Z=-20.0))
    manager = S(_get_address=lambda: manager_address)
    pc = S(_get_address=lambda: 0x1204CF0040)
    mod = S(_third_person_enabled=True, _third_person_pushed=True, _vehicle_camera_active=False,
            _get_runtime=lambda: (pc, pawn, manager), _native_read=lambda a, n: memory[a][:n],
            logging=S(info=lambda m: support.LOG.append(('info', m)),
                      error=lambda m: support.LOG.append(('error', m))),
            FIRST_PERSON_ANIM_HOOK='widget')
    for key, value in overrides.items():
        setattr(mod, key, value)
    return mod


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.saved_hash = aim.FUNCTION_SHA256
        aim.FUNCTION_SHA256 = hashlib.sha256(FUNCTION).hexdigest()
        sys.modules.pop(aim.KEY, None)
        sys.modules.pop(aim.SHARED_CONTROL, None)
        self.native = FakeNative()

    def tearDown(self):
        aim.FUNCTION_SHA256 = self.saved_hash
        sys.modules.pop(aim.KEY, None)
        sys.modules.pop(aim.SHARED_CONTROL, None)
        aim._owner = None

    def owner(self, mod):
        owner = aim.Owner(mod, native_factory=lambda: self.native)
        owner.active = True
        owner.updates = S(is_game_thread=lambda: True)
        aim._owner = owner
        return owner

    def control(self, offset, fmt):
        state = sys.modules[aim.KEY]
        return struct.unpack(fmt, self.native.read(state.control + offset, struct.calcsize(fmt)))

    def test_tps_frame_installs_once_and_publishes_controller_pawn_and_margin(self):
        owner = self.owner(fake_mod())
        owner.frame(None, None, None, None)
        self.assertEqual(owner.reason, 'active')
        self.assertEqual(self.control(aim.ENABLED, '<Q'), (1,))
        self.assertEqual(self.control(aim.CONTROLLER, '<Q'), (0x1204CF0040,))
        self.assertEqual(self.control(aim.PAWN, '<3d'), (250.0, -60.0, -20.0))
        self.assertEqual(self.control(aim.MARGIN, '<2d'), (aim.DEFAULT_MARGIN, aim.DEFAULT_MAX_DEPTH))
        self.assertEqual(self.control(aim.MIN_LENGTH, '<d'), (1.0,))
        writes = len(self.native.code_writes)
        owner.frame(None, None, None, None)
        self.assertEqual(len(self.native.code_writes), writes, 'installed once')

    def test_gates_disable_the_correction(self):
        cases = {
            'first_person_view': fake_mod(first_person=True),
            'not_tps': fake_mod(_third_person_enabled=False),
            'vehicle': fake_mod(_vehicle_camera_active=True),
        }
        for reason, mod in cases.items():
            with self.subTest(reason=reason):
                sys.modules.pop(aim.KEY, None)
                sys.modules.pop(aim.SHARED_CONTROL, None)
                self.native = FakeNative()
                owner = self.owner(fake_mod())
                owner.frame(None, None, None, None)
                self.assertEqual(self.control(aim.ENABLED, '<Q'), (1,))
                owner.mod = mod
                owner.frame(None, None, None, None)
                self.assertEqual(owner.reason, reason)
                self.assertEqual(self.control(aim.ENABLED, '<Q'), (0,))

    def test_console_off_and_install_failure(self):
        owner = self.owner(fake_mod())
        owner.wanted = False
        owner.frame(None, None, None, None)
        self.assertEqual(owner.reason, 'off')
        self.assertNotIn(aim.KEY, sys.modules, 'nothing installed while off')
        aim.FUNCTION_SHA256 = '0' * 64
        owner.wanted = True
        support.LOG.clear()
        owner.frame(None, None, None, None)
        owner.frame(None, None, None, None)
        self.assertEqual(owner.reason, 'install_failed')
        self.assertEqual(sum('INSTALL_REFUSED' in m for _, m in support.LOG), 1)

    def test_reinstalled_patch_is_enabled_again_and_orphans_stay_silent(self):
        owner = self.owner(fake_mod())
        aim._owner, saved = owner, aim._owner
        try:
            owner.frame(None, None, None, None)
            self.assertTrue(aim.restore(self.native))      # e.g. reload restored the site
            owner.frame(None, None, None, None)            # reinstalls with a fresh control block
            self.assertEqual(self.control(aim.ENABLED, '<Q'), (1,))
            orphan = aim.Owner(fake_mod(), native_factory=lambda: self.native)
            orphan.active = True
            orphan.updates = S(is_game_thread=lambda: True)
            orphan.frame(None, None, None, None)
            self.assertEqual(orphan.reason, 'starting', 'orphaned owner does nothing')
        finally:
            aim._owner = saved

    def test_install_error_wins_over_a_retained_state(self):
        owner = self.owner(fake_mod())
        aim._owner, saved = owner, aim._owner
        try:
            owner.install_error = 'simulated torn rollback'
            sys.modules[aim.KEY] = S(control=0x70000000, base=BASE, patch=b'')
            owner.frame(None, None, None, None)
            self.assertEqual(owner.reason, 'install_failed')
        finally:
            aim._owner = saved

    def test_status_reports_native_counters(self):
        owner = self.owner(fake_mod())
        owner.frame(None, None, None, None)
        status = owner.status()
        self.assertTrue(status['installed'])
        for key in ('visits', 'applied', 'skipped', 'mismatch', 'last_start', 'last_shifted', 'last_depth'):
            self.assertIn(key, status)


class WiringTests(unittest.TestCase):
    def test_enable_shutdown_and_console_are_wired(self):
        root = support.PACKAGE_DIR
        enable = (root / 'game_hooks.py').read_text().split('def _on_enable_impl', 1)[1]
        self.assertTrue('native_aim_origin.start(owner_module, runtime_updates)' in enable)
        self.assertTrue('native_aim_origin.shutdown()' in enable)
        shutdown = (root / 'mod_shutdown.py').read_text()
        self.assertIn('"aim_origin", native_aim_origin.shutdown', shutdown)
        self.assertLess(shutdown.index('"aim_origin"'), shutdown.index('"runtime_updates", runtime_updates.shutdown'))
        init = (root / '__init__.py').read_text()
        self.assertIn('"bl4tps_aim"', init)
        commands = init.split('_MOD_COMMANDS = (', 1)[1].split(')', 1)[0]
        self.assertIn('aim_origin_console', commands)



class LoaderWiringTests(unittest.TestCase):
    def test_enable_registers_route_console_tunes_and_disable_cleans_up(self):
        import json
        import subprocess
        from pathlib import Path
        script = Path(__file__).with_name('loader_scenarios.py')
        completed = subprocess.run([sys.executable, str(script), 'aim_origin_wiring'], capture_output=True,
                                   text=True, timeout=120, cwd=str(script.parent))
        data = json.loads(completed.stdout.split('RESULT_JSON=')[1])
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        self.assertTrue(result['owner'])
        self.assertTrue(result['registered'])
        self.assertEqual((result['margin'], result['wanted']), (55.0, False))
        self.assertEqual(result['beam_margin'], 30.0)  # 500 refused, value kept
        self.assertTrue(all('AIM_TRACE' in m for m in result['console']))
        self.assertTrue(any('AIM_TRACE_FAILED' in m and 'beam_margin' in m for m in result['console']))
        self.assertFalse(result['owner_after'])
        self.assertEqual([m for m in result['errors'] if 'beam_margin must be' not in m], [])


if __name__ == '__main__':
    unittest.main()
