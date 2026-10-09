"""0.3.9.5: read-only weapon fire-path probe (synthetic image, no game)."""
import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S

import support
from BL4ThirdPersonPOC import native_weapon_probe as probe

BASE = 0x140000000
SIZE = 0x31B8C000
TEXT = (0x1000, 0x10000000)
RDATA = 0x20000000


class Memory:
    """Zero-filled main image plus explicit heap objects; records image reads."""

    def __init__(self, stamp=0x6AA81051):
        self.image = {}
        self.heap = {}
        self.text_reads = 0
        self.header(stamp)

    def put(self, address, data):
        target = self.image if BASE <= address < BASE + SIZE else self.heap
        for i, byte in enumerate(data):
            target[address + i] = byte

    def header(self, stamp):
        dos = bytearray(64)
        dos[:2] = b'MZ'
        struct.pack_into('<I', dos, 60, 0x80)
        self.put(BASE, dos)
        pe = bytearray(24)
        pe[:4] = b'PE\0\0'
        struct.pack_into('<HHI', pe, 4, 0x8664, 2, stamp)
        struct.pack_into('<H', pe, 20, 0xF0)
        self.put(BASE + 0x80, pe)
        optional = bytearray(0xF0)
        struct.pack_into('<H', optional, 0, 0x20B)
        struct.pack_into('<I', optional, 56, SIZE)
        self.put(BASE + 0x80 + 24, optional)
        sections = bytearray(80)
        struct.pack_into('<III', sections, 8, TEXT[1], TEXT[0], 0)
        struct.pack_into('<I', sections, 36, 0x60000020)
        struct.pack_into('<III', sections, 48, 0x100000, RDATA, 0)
        struct.pack_into('<I', sections, 76, 0x40000040)
        self.put(BASE + 0x80 + 24 + 0xF0, sections)

    def read(self, address, size):
        if BASE <= address < BASE + SIZE:
            if TEXT[0] <= address - BASE < TEXT[0] + TEXT[1]:
                self.text_reads += 1
            return bytes(self.image.get(address + i, 0) for i in range(size))
        if all(address + i in self.heap for i in range(size)):
            return bytes(self.heap[address + i] for i in range(size))
        raise RuntimeError(f'unmapped read {address:#x}')

    def qword(self, address, value):
        self.put(address, struct.pack('<Q', value))


def code_call(at, target):
    return b'\xe8' + struct.pack('<i', target - (at + 5))


def build_world(stamp=0x6AA81051):
    m = Memory(stamp)
    default = [BASE + 0x1000 + i * 0x10 for i in range(probe.VTABLE_SLOTS)]
    fire_vt, sight_vt, receiver_vt = BASE + RDATA, BASE + RDATA + 0x1000, BASE + RDATA + 0x2000
    for table, overrides in ((fire_vt, {130: BASE + 0x500000, 5: BASE + 0x510000}),
                             (sight_vt, {130: BASE + 0x520000})):
        for i, value in enumerate(default):
            m.qword(table + i * 8, overrides.get(i, value))
    # Fire slot 0x410: call 0x600000, camera-cache read, call [rip] -> Beam helper.
    code = bytearray(code_call(0x500000, 0x600000))
    code += bytes.fromhex('488b8110190000')
    ptr_slot = RDATA + 0x3000
    m.qword(BASE + ptr_slot, BASE + 0x38F90E)
    at = 0x500000 + len(code)
    code += b'\xff\x15' + struct.pack('<i', ptr_slot - (at + 6))
    m.put(BASE + 0x500000, code)
    m.put(BASE + 0x600000, code_call(0x600000, 0x700000))
    weapon, data, fire, sight, receiver = 0x5000000, 0x5100000, 0x5200000, 0x5210000, 0x5300000
    m.put(weapon, bytes(0x1000))
    m.qword(weapon + probe.USE_MODE_TABLE, data)
    m.put(weapon + probe.USE_MODE_TABLE + 8, struct.pack('<ii', 2, 4))
    m.put(weapon + probe.USE_MODE_INDEX, b'\x01')
    m.put(data, bytes(2 * probe.USE_MODE_STRIDE))
    m.qword(data + 8, sight)
    m.qword(data + probe.USE_MODE_STRIDE + 8, fire)
    for obj, table in ((fire, fire_vt), (sight, sight_vt), (receiver, receiver_vt)):
        m.put(obj, bytes(probe.OBJECT_WINDOW))
        m.qword(obj, table)
    m.qword(receiver_vt + 0x368, BASE + 0x800000)
    m.qword(fire + 0x30, weapon)
    m.qword(fire + 0x40, receiver)
    pawn = 0x5500000
    m.put(pawn, bytes(0x100))
    m.qword(pawn, BASE + RDATA + 0x5000)
    m.qword(pawn + 0x40, BASE + RDATA + 0x4000)  # interface subobject vtable
    for i in range(probe.HOLDER_SLOTS):
        m.qword(BASE + RDATA + 0x4000 + i * 8, BASE + 0x1000 + i * 0x10)
    m.qword(BASE + RDATA + 0x4000 + 0x38, BASE + 0x900000)
    m.qword(BASE + RDATA + 0x4000 + 0x48, BASE + 0x910000)
    m.put(BASE + 0x900000, bytes.fromhex('f20f108128190000') + code_call(0x900008, 0x920000))
    m.qword(weapon + probe.HOLDER_OBJECT, pawn)
    m.qword(weapon + probe.HOLDER_INTERFACE, pawn + 0x40)
    manager = 0x5400000
    m.put(manager, bytes(0x2000))
    manager_vt = BASE + RDATA + 0x6000
    m.qword(manager, manager_vt)
    for i in range(probe.PROVIDER_SLOTS):
        m.qword(manager_vt + i * 8, BASE + 0x1000 + i * 0x10)
    m.qword(manager_vt + probe.AIM_VALID_SLOT, BASE + probe.MEASURED_MANAGER_AIM_VALID)
    m.qword(manager_vt + probe.AIM_TARGET_SLOT, BASE + 0xA00000)
    m.put(BASE + 0xA00000, code_call(0xA00000, 0xA10000))
    m.qword(BASE + RDATA + 0x5000 + probe.PAWN_AIM_FALLBACK_SLOT, BASE + 0xB00000)
    controller = 0x5600000
    m.put(controller, bytes(0x1000))
    m.qword(controller + probe.AIM_PROVIDER, manager)
    m.put(manager + probe.CAMERA_CACHE_LOCATION, struct.pack('<3d', 1.0, 2.0, 3.0))

    def behavior(name, cls, address):
        return S(Name=name, Class=S(Name=cls), _path_name=lambda: '/Game/W.' + name,
                 _get_address=lambda: address)

    weapon_obj = S(Name='Weapon', Class=S(Name='OakWeapon'), _path_name=lambda: '/Game/W',
                   _get_address=lambda: weapon,
                   behaviors=[behavior('UM0_Sight', 'WeaponBehavior_Sight', sight),
                              behavior('UM1_Fire', 'WeaponBehavior_FireProjectile', fire)])
    return m, weapon_obj, S(_get_address=lambda: manager)


class ProbeTests(unittest.TestCase):
    def test_projectile_fire_path_is_collected(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager)
        fire = report['fire']
        self.assertEqual(fire['cls'], 'WeaponBehavior_FireProjectile')
        self.assertFalse(fire['is_measured_firebeam'])
        self.assertEqual(fire['slot_0x410'], hex(0x500000))
        self.assertEqual({o['slot'] for o in fire['override_slots']}, {hex(0x410), hex(0x28)})
        self.assertEqual(fire['object_pointers'][0]['offset'], hex(0x40))
        self.assertEqual(report['use_modes']['current'], 1)
        functions = report['functions']
        for rva in (0x500000, 0x510000, 0x600000, 0x700000, 0x38F90E):
            self.assertIn(hex(rva), functions)
        self.assertEqual(functions[hex(0x700000)]['depth'], 2)
        self.assertEqual(functions[hex(0x38F90E)]['known'], 'beam_query_helper')
        self.assertEqual(report['summary']['camera_cache_readers'], [hex(0x500000)])
        self.assertEqual(report['summary']['beam_helper_callers'], [hex(0x500000)])
        self.assertEqual(report['camera_cache_location'], [1.0, 2.0, 3.0])
        self.assertTrue(next(b for b in report['behaviors'] if b['cls'].endswith('Projectile'))['in_current_use_mode'])
        json.dumps(report)

    def test_foreign_build_is_refused_before_any_code_read(self):
        m, weapon, manager = build_world(stamp=0x12345678)
        with self.assertRaises(RuntimeError):
            probe.probe(m.read, BASE, weapon, manager)
        self.assertEqual(m.text_reads, 0)

    def test_harvest_is_bounded(self):
        m, weapon, manager = build_world()
        original = probe.MAX_FUNCTIONS
        probe.MAX_FUNCTIONS = 3
        try:
            report = probe.probe(m.read, BASE, weapon, manager)
        finally:
            probe.MAX_FUNCTIONS = original
        self.assertLessEqual(len(report['functions']), 3)

    def test_local_branches_are_not_followed(self):
        m, weapon, manager = build_world()
        m.put(BASE + 0x510000, b'\xe9' + struct.pack('<i', 0x40 - 5))  # jmp inside the window
        report = probe.probe(m.read, BASE, weapon, manager)
        self.assertNotIn(hex(0x510040), report['functions'])

    def test_report_file_is_named_by_class_and_pruned(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager)
        with tempfile.TemporaryDirectory() as root:
            for _ in range(probe.MAX_REPORTS + 3):
                path = probe.write(root, report)
            files = list((Path(root) / probe.REPORT_DIRECTORY_NAME).glob(probe.REPORT_PREFIX + '*.json'))
            self.assertLessEqual(len(files), probe.MAX_REPORTS)
            self.assertIn('WeaponBehavior_FireProjectile', path.name)
            self.assertEqual(json.loads(path.read_text())['version'], probe.VERSION)

    def test_probe_module_never_writes_game_memory(self):
        source = (support.PACKAGE_DIR / 'native_weapon_probe.py').read_text()
        for forbidden in ('WriteProcessMemory', 'VirtualProtect', 'VirtualAlloc', 'add_hook', 'setattr('):
            self.assertNotIn(forbidden, source)


class HolderTests(unittest.TestCase):
    def test_holder_interface_is_resolved_and_harvested_deeper(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, dict(pawn=0x5500000, controller=0x1))
        holder = report['holder']
        self.assertEqual(holder['matches'], ['pawn'])
        self.assertEqual(holder['interface_offset'], hex(0x40))
        self.assertEqual(holder['slots'][0x38 // 8], hex(0x900000))
        functions = report['holder_functions']
        self.assertIn(hex(0x900000), functions)
        self.assertIn(hex(0x920000), functions)
        self.assertEqual(len(bytes.fromhex(functions[hex(0x900000)]['hex'])), probe.HOLDER_WINDOW)
        self.assertEqual(report['summary']['holder_camera_cache_readers'], [hex(0x900000)])
        self.assertEqual(report['runtime']['pawn'], hex(0x5500000))

    def test_fire_pipeline_windows_are_full_length(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager)
        window = report['fire']['windows'][hex(0x410)]
        self.assertEqual(window['rva'], hex(0x500000))
        self.assertEqual(len(bytes.fromhex(window['hex'])), 0x2400)
        self.assertEqual(window['calls'][0]['target'], hex(0x600000))

    def test_missing_holder_is_reported_not_fatal(self):
        m, weapon, manager = build_world()
        m.qword(0x5000000 + probe.HOLDER_OBJECT, 0)
        report = probe.probe(m.read, BASE, weapon, manager)
        self.assertTrue(report['holder']['missing'])
        self.assertEqual(report['holder_functions'], {})


class RunTests(unittest.TestCase):
    def test_run_writes_report_with_console_summary_fields(self):
        m, weapon, manager = build_world()
        pawn = S(_get_address=lambda: 0x5500000)
        pc = S(_get_address=lambda: 0x5600000)  # controller with the aim provider at +0x448
        manager.CameraModeInputs = S(Weapon=weapon)
        with tempfile.TemporaryDirectory() as root:
            owner = S(_get_runtime=lambda: (pc, pawn, manager), _native_read=m.read, SETTINGS_DIR=root,
                      _kernel32=S(GetModuleHandleW=lambda name: BASE))
            report, path = probe.run(owner)
            self.assertTrue(path.exists())
        summary = report['summary']
        for key in ('functions', 'override_slots', 'camera_cache_readers', 'holder_functions',
                    'holder_camera_cache_readers'):
            self.assertIn(key, summary)
        self.assertEqual(report['holder']['matches'], ['pawn'])
        self.assertIn('is_measured_firebeam', report['fire'])
        source = (support.PACKAGE_DIR / '__init__.py').read_text()
        body = source.split('def weapon_probe_console', 1)[1].split('\n\n\n', 1)[0]
        for key in ("summary['holder_functions']", "summary['holder_camera_cache_readers']",
                    "report['holder'].get('matches')"):
            self.assertIn(key, body)


RUNTIME = dict(pawn=0x5500000, controller=0x5600000, manager=0x5400000)


class AimProviderTests(unittest.TestCase):
    def test_provider_is_resolved_as_the_measured_camera_manager(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, RUNTIME)
        provider = report['aim_provider']
        self.assertEqual(provider['matches'], ['manager'])
        self.assertTrue(provider['aim_valid_matches_beam_measurement'])
        self.assertEqual(provider['aim_target'], hex(0xA00000))
        self.assertEqual(provider['pawn_aim_fallback'], hex(0xB00000))
        functions = report['aim_provider_functions']
        for rva in (0xA00000, 0xA10000, probe.MEASURED_MANAGER_AIM_VALID, 0xB00000):
            self.assertIn(hex(rva), functions)

    def test_provider_failure_does_not_abort_the_probe(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, dict(RUNTIME, controller=0x1))
        self.assertIn('error', report['aim_provider'])
        self.assertEqual(report['aim_provider_functions'], {})

    def test_live_aim_relates_target_to_camera_and_pawn(self):
        import struct as st
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, RUNTIME)
        m.put(0x5400000 + probe.CAMERA_CACHE_LOCATION, st.pack('<6d', 0, 0, 0, 0, 0, 0))
        calls = []

        def call(rva, *args):
            calls.append((rva, args))
            return True if rva == probe.MEASURED_MANAGER_AIM_VALID else st.pack('<3d', 50.0, 0.0, 0.0)
        pawn = S(K2_GetActorLocation=lambda: S(X=200.0, Y=-60.0, Z=0.0))
        aim = probe.live_aim(m.read, BASE, report, 0x5400000, pawn, call)
        self.assertEqual([c[0] for c in calls], [probe.MEASURED_MANAGER_AIM_VALID, 0xA00000])
        self.assertTrue(aim['valid'])
        self.assertAlmostEqual(aim['target_depth'], 50.0)
        self.assertAlmostEqual(aim['pawn_depth'], 200.0)
        self.assertFalse(aim['target_in_front_of_pawn'])

    def test_live_aim_does_not_ask_for_a_target_when_aim_is_invalid(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, RUNTIME)
        calls = []
        aim = probe.live_aim(m.read, BASE, report, 0x5400000, None,
                             lambda rva, *a: calls.append(rva) or False)
        self.assertEqual(aim, dict(valid=False))
        self.assertEqual(calls, [probe.MEASURED_MANAGER_AIM_VALID])

    def test_live_aim_is_skipped_unless_provider_is_the_measured_manager(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager, RUNTIME)
        report['aim_provider']['aim_valid_matches_beam_measurement'] = False
        self.assertIn('skipped', probe.live_aim(m.read, BASE, report, 0x5400000, None, lambda *a: None))


class ReceiverAndDumpTests(unittest.TestCase):
    def test_receiver_slots_are_listed_and_harvested(self):
        m, weapon, manager = build_world()
        report = probe.probe(m.read, BASE, weapon, manager)
        receiver = report['fire']['object_pointers'][0]
        self.assertEqual(receiver['slots'][0x368 // 8], hex(0x800000))
        self.assertFalse(receiver['is_measured_beam_receiver'])
        self.assertIn(hex(0x800000), report['functions'])

    def test_dump_reads_only_executable_windows_of_the_reviewed_build(self):
        m, _, _ = build_world()
        report = probe.dump(m.read, BASE, [0x500000, RDATA + 0x10], 0x40)
        self.assertEqual(len(bytes.fromhex(report['windows'][hex(0x500000)]['hex'])), 0x40)
        self.assertIn('error', report['windows'][hex(RDATA + 0x10)])
        self.assertEqual(report['windows'][hex(0x500000)]['calls'][0]['target'], hex(0x600000))
        for bad in (([0x500000], 0), ([0x500000], probe.MAX_DUMP + 1), ([], 0x40), (list(range(33)), 0x40)):
            with self.assertRaises(RuntimeError):
                probe.dump(m.read, BASE, *bad)
        foreign, _, _ = build_world(stamp=0x1)
        with self.assertRaises(RuntimeError):
            probe.dump(foreign.read, BASE, [0x500000], 0x40)
        self.assertEqual(foreign.text_reads, 0)


class CommandWiringTests(unittest.TestCase):
    def test_console_command_is_registered(self):
        source = (support.PACKAGE_DIR / '__init__.py').read_text()
        self.assertIn('"bl4tps_weapon_probe"', source)
        commands = source.split('_MOD_COMMANDS = (', 1)[1].split(')', 1)[0]
        self.assertIn('weapon_probe_console', commands)
        self.assertIn('native_dump_console', commands)
        self.assertIn('"bl4tps_native_dump"', source)


if __name__ == '__main__':
    unittest.main()
