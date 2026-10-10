"""Real Python ADS migration/rearm/zoom paths with SDK/native leaves substituted.

The callbacks run before or after migration; no callback counts are fabricated
by the fix. Windows native execution and gameplay visuals require in-game QA.
"""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
import test_hybrid_fov_return_0_3_9_15 as return_tests
from BL4ThirdPersonPOC import ads_events, ads_zoom_modifiers, ads_zoom_settings, camera_math, hybrid_ads, native_lifecycle


class HybridFixTests(unittest.TestCase):
    assert_controls_off = return_tests.ZoomReturnTests.assert_controls_off
    tick = return_tests.ZoomReturnTests.tick
    enter = return_tests.ZoomReturnTests.enter
    settle = return_tests.ZoomReturnTests.settle

    def setUp(self):
        return_tests.ZoomReturnTests.setUp(self)
        self.addCleanup(hybrid_ads.reset)
        m = self.mod
        self.collector = S(Name='Collector')
        self.incoming = S(Name='Incoming', CurrentState='Active')
        self.addresses = {id(self.pc): 0x10, id(self.pawn): 0x20, id(self.camera): 0x30,
                          id(self.weapon): 0xAA, id(self.incoming): 0xCC, id(self.collector): 0x55}
        m._object_address = m._ads_object_address = lambda obj: self.addresses.get(id(obj), 0)
        self.pawn.ZoomState = S(State=2, Level=0, bWantsToZoom=True, bPendingZoom=False, bTickingZoom=False)
        self.camera.CameraModeState.bIsColliding = False
        self.camera.CameraModeState.bShowViewModel = False
        self.native_active = False
        self.native_starts = []
        m._native_active = lambda: self.native_active
        m._native_start = self.start_native
        m._native_stop = lambda reason: setattr(self, 'native_active', False) or True
        m._looks_like_first_person_fallback = lambda: False
        m._ffyl_camera_stack_has_single_tps = lambda camera: True
        m._ads_press_intent = {}
        for flag in ('_native_ffyl_pending', '_native_npc_pending', '_native_ladder_handoff_pending',
                     '_native_slide_handoff_pending', '_native_fault'):
            setattr(m, flag, False)
        m._find_ads_collector = lambda weapon: self.collector
        m._ffyl_camera_active = lambda pawn, camera: False
        m._update_hybrid_ads_weapon_handoff = lambda pawn, camera, state: (
            ads_events._update_hybrid_ads_weapon_handoff_impl(pawn, camera, state, owner_module=m))
        m._ads_smoothstep = lambda alpha: alpha * alpha * (3 - 2 * alpha)
        ads_events._reset_ads_handoff_debug_impl(owner_module=m)
        m._ads_handoff.update(held=True, route_weapon=0xAA)
        m._ads_tps_state.update(weapon_address=0xAA, manager_address=0x30)
        m._ads_write_zoom_latches = lambda pawn, **kw: ads_events._ads_write_zoom_latches_impl(
            pawn, owner_module=m, **kw)
        m._start_ads_handoff_latch_mask = lambda pawn, reason: ads_events._start_ads_handoff_latch_mask_impl(
            pawn, reason, owner_module=m)
        m._release_ads_handoff_latches = lambda pawn, reason: ads_events._release_ads_handoff_latches_impl(
            pawn, reason, owner_module=m)
        m._arm_late_tps_ads_equip_handoff = lambda obj, args: ads_events._arm_late_tps_ads_equip_handoff_impl(
            obj, args, owner_module=m)
        m._commit_ads_handoff_pose = lambda pawn, reason: ads_events._commit_ads_handoff_pose_impl(
            pawn, reason, owner_module=m)
        m._camera_feature_options = dict(global_=None, categories={})
        m._camera_feature_options['global'] = S(value=1.)

    def start_native(self, **kwargs):
        self.native_starts.append(kwargs)
        self.native_active = True

    def equip_callbacks(self):
        args = S(EventWeapon=self.incoming)
        for _ in range(2):
            ads_events._hybrid_ads_weapon_equipped_pre_hook_impl(self.collector, args, None, None, owner_module=self.mod)
            ads_events._hybrid_ads_weapon_equipped_post_hook_impl(self.collector, args, None, None, owner_module=self.mod)

    def migrate(self, callbacks='before'):
        m = self.mod
        self.assertEqual(hybrid_ads.enter_scope(m), 'scope_on')
        self.settle()
        self.camera.CameraModeInputs.Weapon = self.incoming
        self.incoming.CurrentState = 'Equipping'
        if callbacks == 'before':
            self.equip_callbacks()  # FPS route has no incoming TPS handoff yet.
        ads_events._update_hybrid_ads_route_reconciliation_impl(owner_module=m)
        self.settle()
        self.camera.CameraCachePrivate.POV.FOV = 90.
        ads_events._update_hybrid_ads_route_reconciliation_impl(owner_module=m)
        self.assertEqual(m._ads_route, 'tps')
        if callbacks == 'after':
            with patch.object(ads_zoom_modifiers, 'update'):
                self.equip_callbacks()
        self.incoming.CurrentState = 'Active'
        self.finish_ads_blend()

    def finish_ads_blend(self):
        state = self.mod._ads_tps_state
        transition = state.get('transition')
        if transition:
            with patch.object(ads_events.time, 'perf_counter', return_value=transition['started'] + transition['duration'] + .01):
                ads_events._update_hybrid_tps_ads_impl(owner_module=self.mod)
        self.assertIsNone(state['transition'])

    def rearm(self):
        native_lifecycle._rearm_held_ads_if_ready(self.camera, self.pawn, owner_module=self.mod)

    def test_callbacks_before_migration_no_longer_leave_toggle_stuck(self):
        self.migrate('before')
        m = self.mod
        self.assertEqual(m._ads_handoff['equip_ordinal'], 0)
        self.assertTrue(m._ads_handoff['reticle_rebind_active'])
        self.assertEqual(hybrid_ads.enter_scope(m), 'refused:weapon_handoff')
        with patch.object(ads_zoom_modifiers, 'update') as modifiers:
            self.rearm()
        modifiers.assert_called_once_with(m)
        self.assertFalse(m._ads_handoff['reticle_rebind_active'])
        self.assertEqual(m._ads_handoff['equip_ordinal'], 0)
        self.assertNotIn('native_tps_rearm', m._ads_handoff)
        self.assertEqual(self.native_starts, [dict(allow_tps_ads=True)])
        self.assertEqual(hybrid_ads.enter_scope(m), 'scope_on')

    def test_callbacks_after_migration_keep_the_existing_pair_path(self):
        self.migrate('after')
        self.assertEqual(self.mod._ads_handoff['equip_ordinal'], 2)
        self.assertFalse(self.mod._ads_handoff['reticle_rebind_active'])
        with patch.object(ads_zoom_modifiers, 'update'):
            self.rearm()
        self.assertTrue(self.native_active)
        self.assertEqual(hybrid_ads.enter_scope(self.mod), 'scope_on')

    def test_repeated_scope_swap_cycles_with_ads_held(self):
        for cycle in range(3):
            self.migrate('before')
            with patch.object(ads_zoom_modifiers, 'update'):
                self.rearm()
            self.assertFalse(self.mod._ads_handoff['reticle_rebind_active'])
            self.assertEqual(self.mod._ads_handoff['equip_ordinal'], 0)
            # New identity; the next request never inherits the old completion.
            self.weapon = self.incoming
            self.incoming = S(Name='Next', CurrentState='Active')
            self.addresses[id(self.incoming)] = 0xDD + cycle
        self.assertEqual(len(self.native_starts), 3)

    def test_unsettled_runtime_and_special_states_keep_guard_closed(self):
        self.migrate()
        m = self.mod
        cases = (
            (self.incoming, 'CurrentState', 'Equipping'),
            (self.incoming, 'CurrentState', 'PuttingDown'),
            (self.camera.CameraModeState, 'bIsTransitioning', True),
            (self.camera.CameraModeState, 'bIsColliding', True),
            (self.pawn.ZoomState, 'State', 0),
            (m, '_slide_active', True), (m, '_native_fault', True),
            (m, '_ads_active', False), (m.omni_hybrid_ads, 'value', False),
            (m, '_ads_collector_address', 0x99),
        )
        for obj, name, value in cases:
            before = getattr(obj, name)
            with self.subTest(field=name, value=value):
                setattr(obj, name, value)
                self.rearm()
                self.assertTrue(m._ads_handoff['reticle_rebind_active'])
                self.assertEqual(self.native_starts, [])
                setattr(obj, name, before)
        for key in ('latch_active', 'in_gap'):
            m._ads_handoff[key] = True
            self.rearm()
            self.assertEqual(self.native_starts, [])
            m._ads_handoff[key] = False
        m._ads_tps_state['transition'] = dict(kind='zoom_in')
        self.rearm()
        self.assertEqual(self.native_starts, [])

    def test_changed_weapon_or_manager_cannot_inherit_request(self):
        for kind in ('weapon', 'manager'):
            with self.subTest(kind=kind):
                self.setUp()
                self.migrate()
                if kind == 'weapon':
                    self.camera.CameraModeInputs.Weapon = self.weapon
                else:
                    self.mod._get_runtime = lambda: (self.pc, self.pawn, S())
                self.rearm()
                self.assertEqual(self.native_starts, [])
                self.assertTrue(self.mod._ads_handoff['reticle_rebind_active'])
                self.assertNotIn('native_tps_rearm', self.mod._ads_handoff)

    def test_native_failure_does_not_unlock_or_retry_every_frame(self):
        self.migrate()
        self.mod._native_start = lambda **kw: (_ for _ in ()).throw(RuntimeError('guard refused'))
        self.rearm()
        self.assertTrue(self.mod._ads_handoff['reticle_rebind_active'])
        self.assertTrue(self.mod._ads_handoff['native_tps_rearm']['attempted'])
        self.mod._native_start = self.start_native
        self.rearm()
        self.assertEqual(self.native_starts, [])
        self.assertEqual(hybrid_ads.enter_scope(self.mod), 'refused:weapon_handoff')

    def test_native_start_without_owner_does_not_unlock(self):
        self.migrate()
        self.mod._native_start = lambda **kw: None
        self.rearm()
        self.assertTrue(self.mod._ads_handoff['reticle_rebind_active'])
        self.assertNotIn('hybrid_settled_equip', self.mod._ads_tps_state)

    def test_release_and_cleanup_cancel_the_pending_request(self):
        self.migrate()
        ads_events._cleanup_ads_handoff_impl('ads_release', clear_held=True, owner_module=self.mod)
        self.rearm()
        self.assertEqual(self.native_starts, [])
        self.assertNotIn('native_tps_rearm', self.mod._ads_handoff)

    def test_superseded_request_is_not_cleared_after_native_start(self):
        self.migrate()
        replacement = dict(identity=(1, 2, 3, 4))
        def start(**kw):
            self.native_active = True
            self.mod._ads_handoff['native_tps_rearm'] = replacement
        self.mod._native_start = start
        self.rearm()
        self.assertIs(self.mod._ads_handoff['native_tps_rearm'], replacement)
        self.assertTrue(self.mod._ads_handoff['reticle_rebind_active'])

    def test_hybrid_off_retains_the_original_callback_requirement(self):
        self.migrate()
        request = self.mod._ads_handoff['native_tps_rearm']
        request.pop('hybrid_settled_equip')
        self.rearm()
        self.assertEqual(self.native_starts, [])
        self.assertTrue(self.mod._ads_handoff['reticle_rebind_active'])

    def test_native_category_global_and_custom_zoom_are_not_flattened(self):
        m = self.mod
        for category, scale, global_factor, custom_factor in (
            ('pistol', .8, 1., None), ('sniper_rifle', .3, 1., None),
            ('shotgun', .5, 1.8, None), ('shotgun', .5, 1.8, 2.5),
        ):
            with self.subTest(category=category, factor=custom_factor or global_factor):
                self.sight.PuppetZoomFOVScale = scale
                self.camera.CameraModeState.BaseFOVOffset = 0.
                m._camera_feature_options['global'].value = global_factor
                m._camera_feature_options['categories'] = {category: (S(value=custom_factor is not None), S(value=custom_factor or 1.))}
                m._start_hybrid_tps_ads(self.camera, category, 'test', 'test')
                expected = ads_zoom_settings.adjust(m, category, 90., camera_math._derive_ads_target_fov(90., scale))[0]
                self.assertAlmostEqual(m._ads_tps_state['target_fov'], expected)
                self.assertAlmostEqual(m._ads_tps_state['zoom_multiplier'], custom_factor or global_factor)

    def test_settings_changed_during_ads_retarget_without_a_cap(self):
        m = self.mod
        m._start_hybrid_tps_ads(self.camera, 'shotgun', 'test', 'test')
        initial = m._ads_tps_state['target_fov']
        m._camera_feature_options['global'].value = 2.
        ads_events._update_hybrid_tps_ads_impl(owner_module=m)
        self.assertLess(m._ads_tps_state['target_fov'], initial)
        self.assertEqual(m._ads_tps_state['transition']['kind'], 'settings_retarget')
        expected = ads_zoom_settings.adjust(m, 'shotgun', 90., camera_math._derive_ads_target_fov(90., .5))[0]
        self.assertAlmostEqual(m._ads_tps_state['target_fov'], expected)

    def test_settled_modifier_admission_preserves_native_byte_guard(self):
        self.migrate()
        with patch.object(ads_zoom_modifiers, 'update'):
            self.rearm()
        # Admission reaches the unchanged initializer; a failing byte/build
        # guard is handled there without any native call or unsafe memory read.
        with patch.object(ads_zoom_modifiers, '_initialize', side_effect=RuntimeError('byte guard')) as init:
            ads_zoom_modifiers.update(self.mod)
        init.assert_called_once_with(self.mod)
        self.assertEqual(self.mod._ads_tps_state['zoom_modifier_result'], 'refused')
        self.assertTrue(any('byte guard' in message for _, message in support.LOG))

    def test_changed_collector_rejects_settled_modifier_proof(self):
        self.migrate()
        with patch.object(ads_zoom_modifiers, 'update'):
            self.rearm()
        self.mod._ads_collector_address = 0x99
        with patch.object(ads_zoom_modifiers, '_initialize') as init:
            ads_zoom_modifiers.update(self.mod)
        init.assert_not_called()


if __name__ == '__main__':
    unittest.main()
