"""Held scope return: real ADS setup/math/reconciliation, simulated SDK camera.

Assertions cover the requested TPS destination and absence of a second zoom-in.
They do not assume that the simulated view blend proves the native BL4 curve.
"""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
from BL4ThirdPersonPOC import ads_handoff, ads_control
import test_hybrid_omni_handoff_0_3_9_14 as handoff_tests
from BL4ThirdPersonPOC import ads_events, camera_math, hybrid_ads


class ZoomReturnTests(unittest.TestCase):
    assert_controls_off = handoff_tests.HandoffTests.assert_controls_off
    tick = handoff_tests.HandoffTests.tick
    enter = handoff_tests.HandoffTests.enter
    settle = handoff_tests.HandoffTests.settle

    def setUp(self):
        handoff_tests.HandoffTests.setUp(self)
        self.camera.CameraCachePrivate = S(POV=S(FOV=90.))
        mod = self.mod
        mod.ADS_MIN_SAFE_FOV = camera_math.ADS_MIN_SAFE_FOV
        mod.ADS_MAX_SAFE_FOV = camera_math.ADS_MAX_SAFE_FOV
        mod.ADS_MIN_DURATION = .05
        mod.ADS_MAX_DURATION = 2.
        self.sight = S(PuppetZoomFOVScale=.5, ZoomDuration=.15)
        mod._beam_active = lambda: False
        mod._find_active_ads_sight = lambda weapon: (self.sight, 0, 'MeasuredSight')
        mod._ads_attribute_float = camera_math._ads_attribute_float
        mod._derive_ads_target_fov = camera_math._derive_ads_target_fov
        mod._read_live_ads_fov = camera_math._read_live_ads_fov
        mod._find_ads_collector = lambda weapon: S(Name='Collector')
        mod._cleanup_ads_handoff = lambda reason: ads_handoff._cleanup_ads_handoff_impl(
            reason, owner_module=mod)
        mod._ads_debug = dict(tps_presses=0, category_counts={}, hold_writes=0)
        mod._set_hybrid_tps_fov = lambda value: ads_events._set_hybrid_tps_fov_impl(
            value, owner_module=mod)
        self.transitions = []
        def begin(kind, start, target):
            self.transitions.append((kind, start, target))
            ads_events._begin_hybrid_ads_transition_impl(kind, start, target, owner_module=mod)
        mod._begin_hybrid_ads_transition = begin
        mod._start_hybrid_tps_ads = lambda camera, category, source, evidence, **kw: (
            ads_events._start_hybrid_tps_ads_impl(camera, category, source, evidence,
                                                owner_module=mod, **kw))
        self.published = []
        mod._request_tps_reticle_publish = self.published.append
        mod._apply_camera_offset = lambda: None
        mod._clear_pending_ads_press = lambda reason: None
        mod._cancel_hybrid_ads = lambda reason: ads_events._cancel_hybrid_ads_impl(
            reason, owner_module=mod)
        self.ads_errors = []
        mod._ads_debug_error = lambda phase, exc: self.ads_errors.append((phase, str(exc)))
        self.target = camera_math._derive_ads_target_fov(90., .5)[0]
        mod._ads_tps_state.update(target_fov=self.target, last_fov=self.target,
                                  manager_address=mod._ads_object_address(self.camera))
        self.camera.CameraModeState.BaseFOVOffset = self.target - 90.

    def return_from_scope(self):
        self.enter()
        self.settle()
        self.camera.CameraCachePrivate.POV.FOV = 30.  # rendered native scope
        self.keys['sprint'] = False
        self.tick()
        self.keys['sprint'] = True
        self.tick()
        hybrid_ads.update(self.mod)
        self.assertEqual(self.mod._ads_route, 'sniper_fps')
        self.assertEqual(self.camera.mode, 'ThirdPerson')
        self.assertTrue(self.camera.CameraModeState.bIsTransitioning)

    def reconcile(self):
        ads_handoff._update_hybrid_ads_route_reconciliation_impl(owner_module=self.mod)

    def test_destination_is_held_tps_aim_during_blend_not_hip(self):
        self.return_from_scope()
        self.assertAlmostEqual(self.camera.CameraModeState.BaseFOVOffset, self.target - 90.)
        self.reconcile()
        self.assertIsNone(self.mod._ads_tps_state, 'Wait for the native camera blend to settle')
        self.assertEqual(self.transitions, [])
        for _ in range(5):
            hybrid_ads.update(self.mod)
            self.assertAlmostEqual(self.camera.CameraModeState.BaseFOVOffset, self.target - 90.)
            self.tick()
            self.assert_controls_off()

    def test_settled_resume_reuses_tps_calibration_without_second_zoom_in(self):
        self.return_from_scope()
        self.settle()
        self.camera.CameraCachePrivate.POV.FOV = 59.  # previous camera sample may still be blended
        self.reconcile()
        ads = self.mod._ads_tps_state
        self.assertEqual(self.ads_errors, [])
        self.assertEqual(ads['base_fov'], 90.)
        self.assertEqual(ads['original_offset'], 0.)
        self.assertAlmostEqual(ads['target_fov'], self.target)
        self.assertAlmostEqual(ads['last_fov'], self.target)
        self.assertIsNone(ads['transition'])
        self.assertEqual(self.transitions, [])
        self.assertEqual(self.published, ['hybrid_scope_exit'])
        self.assertTrue(self.mod._ads_handoff['native_tps_rearm']['same_weapon'])
        self.assertIsNone(hybrid_ads._state['return_fov'])
        self.keys['sprint'] = False
        self.tick()
        self.assertFalse(self.o.special_paused)

    def test_actual_fresh_ads_still_uses_normal_zoom_in(self):
        self.mod._ads_tps_state = None
        self.camera.CameraModeState.BaseFOVOffset = 0.
        self.mod._start_hybrid_tps_ads(self.camera, 'sniper_rifle', 's', 'e')
        self.assertEqual(self.transitions[0][0], 'zoom_in')
        self.assertEqual(self.mod._ads_tps_state['last_fov'], 90.)

    def test_return_uses_regular_offset_and_does_not_restart(self):
        self.return_from_scope()
        fade = hybrid_ads._state['fade']
        with patch.object(hybrid_ads, 'monotonic', return_value=fade['started'] + 1.):
            # Native mode is TPS, but route migration is not completed yet.
            self.assertEqual(hybrid_ads.compensate(self.mod, 0., 0., 0.), (0., 75., 10.))
            self.settle()
            self.reconcile()
            self.assertEqual(hybrid_ads.compensate(self.mod, 0., 75., 10.), (0., 75., 10.))

    def test_ads_release_during_return_restores_owned_offset(self):
        self.return_from_scope()
        self.mod._ads_active = False
        self.mod._ads_route = 'hip'
        hybrid_ads.release_transition(self.mod, .06)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 0.)
        hybrid_ads.update(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 0.)
        self.assertIsNone(hybrid_ads._state['return_fov'])

    def test_weapon_change_during_return_restores_old_overlay(self):
        self.return_from_scope()
        self.camera.CameraModeInputs.Weapon = S(Name='Other')
        hybrid_ads.update(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 0.)
        self.assertIsNone(hybrid_ads._state['return_fov'])

    def test_manager_replacement_never_writes_the_old_or_new_manager(self):
        self.return_from_scope()
        old_offset = self.camera.CameraModeState.BaseFOVOffset
        new = S(CameraModeState=S(BaseFOVOffset=123.), GetActorCameraMode=lambda pawn: 'ThirdPerson',
                CameraModeInputs=S(Weapon=self.weapon))
        self.runtime = (self.pc, self.pawn, new)
        hybrid_ads.update(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, old_offset)
        self.assertEqual(new.CameraModeState.BaseFOVOffset, 123.)
        self.assertIsNone(hybrid_ads._state['return_fov'])

    def test_other_offset_writer_is_not_overwritten_during_cleanup(self):
        self.return_from_scope()
        self.camera.CameraModeState.BaseFOVOffset = 4.
        hybrid_ads.cancel_return_fov(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 4.)

    def test_entry_fade_retired_by_manager_replacement_writes_neither_manager(self):
        self.enter()
        self.assertIsNotNone(hybrid_ads._state['fov_fade'])
        old_offset = self.camera.CameraModeState.BaseFOVOffset
        new = S(CameraModeState=S(BaseFOVOffset=123.))
        self.runtime = (self.pc, self.pawn, new)
        hybrid_ads.update(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, old_offset)
        self.assertEqual(new.CameraModeState.BaseFOVOffset, 123.)
        self.assertIsNone(hybrid_ads._state['fov_fade'])

    def test_cancel_and_mod_reset_restore_nonzero_original_offset(self):
        self.mod._ads_tps_state['original_offset'] = 5.
        self.return_from_scope()
        hybrid_ads.reset(self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 5.)

    def test_cancel_restore_false_discards_overlay_without_writing(self):
        self.return_from_scope()
        offset = self.camera.CameraModeState.BaseFOVOffset
        ads_events._cancel_hybrid_ads_impl('owner_changed', restore=False, owner_module=self.mod)
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, offset)
        self.assertIsNone(hybrid_ads._state['return_fov'])

    def test_ignored_return_does_not_put_tps_offset_into_fps(self):
        self.enter()
        self.settle()
        self.camera.CameraModeState.BaseFOVOffset = 0.
        hybrid_ads.finish_fov_fade(self.mod)
        self.camera.SetActorCameraMode = lambda *args: None
        hybrid_ads.toggle_scope(self.mod)
        self.assertEqual(self.camera.mode, 'Default')
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, 0.)
        self.assertEqual(hybrid_ads.compensate(self.mod, 0., 0., 0.), (0., 0., 0.))

    def test_current_camera_struct_is_used_and_cached_hold_is_only_scalars_and_weakrefs(self):
        self.return_from_scope()
        resume = self.mod._ads_handoff['route_pending']['hybrid_tps_resume']
        self.assertNotIn('mode_state', resume)
        old_struct = self.camera.CameraModeState
        self.camera.CameraModeState = S(BaseFOVOffset=0., bIsTransitioning=True)
        hybrid_ads.prepare_return_fov(self.mod)
        self.assertAlmostEqual(self.camera.CameraModeState.BaseFOVOffset, self.target - 90.)
        self.assertAlmostEqual(old_struct.BaseFOVOffset, self.target - 90.)

    def test_repeat_scope_round_trip_does_not_compound_zoom(self):
        self.return_from_scope()
        self.settle()
        self.reconcile()
        self.keys['sprint'] = False
        self.tick()
        for _ in range(3):
            self.assertEqual(hybrid_ads.enter_scope(self.mod), 'scope_on')
            self.settle()
            hybrid_ads.finish_fov_fade(self.mod)
            self.assertEqual(hybrid_ads.exit_scope(self.mod), 'scope_off')
            self.settle()
            self.reconcile()
            self.assertEqual(self.mod._ads_tps_state['base_fov'], 90.)
            self.assertAlmostEqual(self.mod._ads_tps_state['target_fov'], self.target)
            self.assertAlmostEqual(self.camera.CameraModeState.BaseFOVOffset, self.target - 90.)

    def test_fov_evidence_is_bounded_and_read_errors_are_nonfatal(self):
        self.return_from_scope()
        for _ in range(300):
            hybrid_ads.prepare_return_fov(self.mod)
        rows = self.o.report['hybrid_fov_events']
        self.assertEqual(len(rows), 256)
        self.assertEqual(rows[-1]['camera_fov'], 30.)
        del self.camera.CameraCachePrivate
        hybrid_ads.prepare_return_fov(self.mod)
        self.assertGreater(self.o.report['hybrid_fov_read_failures'], 0)
        self.assertTrue(self.o.active)
        self.assertEqual(self.o.report['errors'], [])


if __name__ == '__main__':
    unittest.main()
