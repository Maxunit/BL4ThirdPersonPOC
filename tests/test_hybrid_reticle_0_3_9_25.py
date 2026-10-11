"""Execute the actual reticle reader/writer over simulated process memory.

WinAPI and immutable native hashes are substituted. Native HUD rendering and
scope-overlay behavior still require gameplay QA.
"""
import ctypes
import struct
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
import test_hybrid_ads_0_3_9_13 as scope_tests
import test_hybrid_fov_return_0_3_9_15 as return_tests
from BL4ThirdPersonPOC import _reticle_publish, hybrid_ads


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


class Memory:
    def __init__(self):
        self.data = {}
        self.writes = []
        self.fail_once = None
        self.on_read = None

    def put(self, address, data):
        self.data.update((address + i, value) for i, value in enumerate(data))

    def pack(self, address, fmt, *values):
        self.put(address, struct.pack(fmt, *values))

    def read(self, process, address, buffer, size, got):
        if self.on_read is not None:
            self.on_read(address, size)
        try:
            data = bytes(self.data[address + i] for i in range(size))
        except KeyError:
            return 0
        ctypes.memmove(buffer, data, size)
        ctypes.cast(got, ctypes.POINTER(ctypes.c_size_t))[0] = size
        return 1

    def write(self, process, address, buffer, size, got):
        if self.fail_once == address:
            self.fail_once = None
            return 0
        data = ctypes.string_at(buffer, size)
        self.put(address, data)
        self.writes.append((address, data))
        ctypes.cast(got, ctypes.POINTER(ctypes.c_size_t))[0] = size
        return 1


class NativeReticleTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope_tests.HybridBase()
        self.scope.setUp()
        self.addCleanup(self.scope.tearDown)
        self.mod, self.camera, self.weapon = scope_tests.fake_mod()
        self.pc, self.pawn = S(), S(ZoomState=S(State=2))
        addresses = (0x200000, 0x210000, 0x220000, 0x230000)
        for obj, address in zip((self.pc, self.pawn, self.camera, self.weapon), addresses):
            obj._get_address = lambda address=address: address
        self.identity = addresses
        self.mod._get_runtime = lambda: (self.pc, self.pawn, self.camera)
        self.mod._ads_object_address = lambda obj: obj._get_address() if obj is not None else 0
        self.mod._ads_handoff['route_weapon'] = addresses[3]
        self.mod._ads_tps_state.update(weapon_address=addresses[3], manager_address=addresses[2])
        self.mod._reticle_gate_last_fail = ''
        self.memory = Memory()
        self.base, cls, owner = 0x140000000, 0x240000, 0x250000
        self.model, data, container, text = 0x260000, 0x270000, 0x280000, 0x290000
        mem = self.memory
        for address in (addresses[0], owner):
            mem.pack(address + 0x10, '<Q', cls)
        mem.pack(cls + 0x38, '<i', 0)
        mem.pack(cls + 0x30, '<Q', 0x2A0000)
        mem.pack(0x2A0000, '<Q', cls + 0x30)
        mem.pack(self.base + 0xCBA5CD0, '<Q', cls)
        mem.pack(self.base + 0xCAE1528, '<Q', cls)
        mem.pack(addresses[0] + 0x430, '<Q', owner)
        key = (owner >> 4) & 0xFFFFFFFF
        key = ((key ^ (key >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        key = ((key ^ (key >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        key ^= key >> 16
        header = bytearray(0x50)
        struct.pack_into('<Qii', header, 0, data, 1, 1)
        struct.pack_into('<i', header, 0x48, 1)
        mem.put(self.base + 0xCBCD518, header)
        entry = bytearray(32)
        struct.pack_into('<I', entry, 0, key)
        struct.pack_into('<Q', entry, 8, container)
        struct.pack_into('<i', entry, 24, -1)
        mem.put(data, entry)
        mem.pack(container + 0xA0, '<Q', self.model)
        self.raw = bytearray(0x30)
        self.raw[0] = 1
        struct.pack_into('<I', self.raw, 4, 7)
        name = 'crosshair_ar\x00'.encode('utf-16-le')
        struct.pack_into('<QiiI', self.raw, 0x18, text, len(name) // 2, len(name) // 2, 1)
        mem.put(self.model + 0x88, self.raw)
        mem.put(text, name)
        mem.pack(addresses[3] + 0x1B0, '<Q', addresses[1])
        ready = bytearray(0x3E)
        ready[0] = 1
        struct.pack_into('<Q', ready, 0x36, 0x777)
        mem.put(addresses[3] + 0xD2A, ready)
        mem.pack(self.base + 0xCB8CD70, '<QQ', 0x111, 0x222)
        anchors = (
            (3862014, 401, '3e29d76de88924ffae8010ec3a2dd1cc1e8936dd17ab78d7ff10e4015b3fb0b8'),
            (9899534, 371, '6425b949e8760423f4e163b1f836937c00b3f32524786a98d52427db48a58c3b'),
            (76318096, 2132, 'a463ef265980420cd0b05f55e9184bf8e2356188729b4def80df7c377648effd'),
        )
        self.digests = {}
        for rva, size, digest in anchors:
            mem.put(self.base + rva, bytes(size))
            self.digests[size] = digest
        mem.put(self.base + 0xFC0656, bytes.fromhex('41 88 87 88 00 00 00 ff c1 41 89 8f 8c 00 00 00'))
        api = S(GetModuleHandleW=Function(lambda name: self.base),
                GetCurrentProcess=Function(lambda: 1),
                ReadProcessMemory=Function(mem.read), WriteProcessMemory=Function(mem.write))
        self.addCleanup(patch.stopall)
        patch.object(ctypes, 'WinDLL', return_value=api, create=True).start()
        patch('hashlib.sha256', side_effect=lambda raw: S(hexdigest=lambda: self.digests[len(raw)])).start()
        self.publisher = _reticle_publish.create_publisher(self.mod)
        self.mod._hide_hybrid_tps_reticle = self.publisher.hide_for_scope

    def enter(self):
        self.assertEqual(hybrid_ads.enter_scope(self.mod), 'scope_on')

    def visible(self):
        return self.memory.data[self.model + 0x88]

    def test_hold_and_toggle_hide_only_visibility_and_notification_counter(self):
        for held in (True, False):
            with self.subTest(physical_button_held=held):
                hybrid_ads.reset()
                self.mod._ads_route = 'tps'
                self.mod._ads_handoff.update(held=held, route_weapon=self.identity[3])
                self.mod._ads_tps_state = dict(phase='ads', weapon_address=self.identity[3],
                    category='assault_rifle', base_fov=90., target_fov=70., original_offset=0.,
                    mode_state=self.camera.CameraModeState, offset_overridden=False)
                self.memory.put(self.model + 0x88, self.raw)
                self.memory.writes.clear()
                self.enter()
                self.assertEqual(self.visible(), 0)
                self.assertEqual(self.memory.writes, [(self.model + 0x88, b'\x00'),
                                                       (self.model + 0x8C, struct.pack('<I', 8))])
                self.assertEqual(self.pawn.ZoomState.State, 2)

    def test_repeated_handover_of_hidden_model_does_not_write(self):
        self.enter()
        self.memory.writes.clear()
        self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'already_hidden')
        self.assertEqual(self.memory.writes, [])

    def test_native_camera_blend_can_report_outgoing_mode_at_scope_event(self):
        self.enter()
        self.camera.mode = 'ThirdPerson'
        self.camera.CameraModeState.bIsTransitioning = True
        self.memory.put(self.model + 0x88, self.raw)
        self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'hidden')
        self.assertEqual(self.visible(), 0)

    def test_changed_weapon_manager_zoom_or_special_context_cannot_hide(self):
        self.enter()
        cases = ((self.mod, '_ads_route', 'tps'), (self.mod, '_ads_active', False),
                 (self.mod, '_vehicle_camera_active', True), (self.mod, '_ladder_active', True),
                 (self.mod, '_shop_camera_active', True), (self.mod, '_slide_active', True),
                 (self.pawn.ZoomState, 'State', 0), (self.camera, 'mode', 'ThirdPerson'),
                 (self.mod.omni_hybrid_ads, 'value', False))
        for obj, field, value in cases:
            old = getattr(obj, field)
            with self.subTest(field=field):
                self.memory.put(self.model + 0x88, self.raw)
                self.memory.writes.clear()
                setattr(obj, field, value)
                self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'gate_skipped')
                self.assertEqual(self.memory.writes, [])
                setattr(obj, field, old)
        for changed in ((1, *self.identity[1:]), (*self.identity[:2], 1, self.identity[3]),
                        (*self.identity[:3], 1)):
            self.assertEqual(self.publisher.hide_for_scope(changed)['status'], 'gate_skipped')
            self.assertEqual(self.memory.writes, [])

    def test_fps_route_alone_without_hybrid_scope_cannot_hide(self):
        self.mod._ads_route = 'fallback_fps'
        self.camera.mode = 'Default'
        self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'gate_skipped')
        self.assertEqual(self.memory.writes, [])

    def test_unrelated_model_and_scope_model_flag_are_not_written(self):
        self.enter()
        for text, flag in (('unrelated_ui', 0), ('crosshair_ar', 1)):
            raw = bytearray(self.raw)
            raw[8] = flag
            name = (text + '\x00').encode('utf-16-le')
            struct.pack_into('<ii', raw, 0x20, len(name) // 2, len(name) // 2)
            self.memory.put(0x290000, name)
            self.memory.put(self.model + 0x88, raw)
            self.memory.writes.clear()
            self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'model_mismatch')
            self.assertEqual(self.memory.writes, [])

    def test_identity_change_between_snapshot_and_write_is_refused(self):
        self.enter()
        self.memory.put(self.model + 0x88, self.raw)
        self.memory.writes.clear()
        def change(address, size):
            if address == self.model + 0x88:
                self.mod._ads_handoff['route_weapon'] = 1
        self.memory.on_read = change
        self.assertEqual(self.publisher.hide_for_scope(self.identity)['status'], 'unstable_snapshot')
        self.assertEqual(self.memory.writes, [])

    def test_failed_counter_write_repairs_visibility_while_identity_matches(self):
        self.memory.fail_once = self.model + 0x8C
        with self.assertRaisesRegex(RuntimeError, 'write failed'):
            hybrid_ads.enter_scope(self.mod)
        self.assertEqual(self.visible(), 1)
        self.assertEqual(self.camera.mode, 'Default')

    def test_native_code_mismatch_refuses_initialization(self):
        self.memory.put(self.base + 0xFC0656, bytes(17))
        with self.assertRaisesRegex(RuntimeError, 'assignment code mismatch'):
            _reticle_publish.create_publisher(self.mod)
        self.assertEqual(self.memory.writes, [])

    def test_return_tps_publication_uses_same_model_with_fresh_guards(self):
        self.enter()
        hybrid_ads.reset()
        self.mod._ads_route = 'tps'
        self.mod._ads_collector_address = 0x55
        self.mod._ads_tps_state = dict(phase='ads', weapon_address=self.identity[3],
                                      manager_address=self.identity[2], category='assault_rifle')
        self.mod._ads_handoff['route_weapon'] = self.identity[3]
        self.camera.mode = 'ThirdPerson'
        self.assertEqual(self.publisher()['status'], 'published')
        self.assertEqual(self.visible(), 1)
        self.mod._ads_route = 'fallback_fps'
        self.assertEqual(self.publisher()['status'], 'gate_skipped')


class ScopeEventTests(unittest.TestCase):
    def setUp(self):
        self.scope = scope_tests.HybridBase()
        self.scope.setUp()
        self.addCleanup(self.scope.tearDown)

    def test_camera_failure_and_refusal_do_not_hide_tps_model(self):
        for fail in (False, True):
            mod, camera, _ = scope_tests.fake_mod()
            if fail:
                camera.fail = RuntimeError('camera failed')
                expected = 'error'
            else:
                camera.CameraModeState.bIsTransitioning = True
                expected = 'refused:camera_transitioning'
            self.assertEqual(hybrid_ads.toggle_scope(mod), expected)
            self.assertEqual(mod.reticle_hides, [])
            self.assertEqual(mod._ads_route, 'tps')

    def test_return_event_republishes_once_after_camera_settles(self):
        fixture = return_tests.ZoomReturnTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.return_from_scope()
        fixture.reconcile()
        self.assertEqual(fixture.published, [])
        fixture.settle()
        fixture.reconcile()
        self.assertEqual(fixture.published, ['hybrid_scope_exit'])
        self.assertEqual(fixture.mod._ads_route, 'tps')
        fixture.reconcile()
        self.assertEqual(fixture.published, ['hybrid_scope_exit'])


if __name__ == '__main__':
    unittest.main()
