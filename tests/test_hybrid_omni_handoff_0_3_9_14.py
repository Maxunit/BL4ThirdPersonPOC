"""Hybrid camera stage plus real GameplaySession.frame/special/combat/sampling.

SDK objects and executable native workers are substituted. The tested Python
guards and special pause/resume path are real. Unrelated Slide/Dash installation
is bypassed at its boundary; this is not an in-game scope/HUD validation.
"""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
from support import controller, session
from test_hybrid_ads_0_3_9_13 import fake_mod
from BL4ThirdPersonPOC import hybrid_ads
from BL4ThirdPersonPOC.omni.animation import observe_hybrid_scope
from BL4ThirdPersonPOC.omni.common import KEY


def sdk_object(obj, name):
    obj.Class = S(Name=name, _path_name=lambda: '/Script/Test.' + name)
    obj._path_name = lambda: '/Test/' + name
    return obj


class HandoffTests(unittest.TestCase):
    def setUp(self):
        hybrid_ads.reset()
        self.running = patch('BL4ThirdPersonPOC.omni.is_running', return_value=True)
        self.running.start()
        self.addCleanup(self.running.stop)
        self.addCleanup(hybrid_ads.reset)
        self.o, _ = session()
        self.mod, self.camera, self.weapon = fake_mod()
        self.o.mod = self.mod
        self.pc = sdk_object(controller(), 'Controller')
        self.pc.bShowMouseCursor = False
        rotation = S(Pitch=0., Yaw=90., Roll=0.)
        zero = S(X=0., Y=0., Z=0.)
        self.pc.GetControlRotation = lambda: rotation
        self.anim = S(bIsFiring=False, bIsReloading=False)
        self.mesh = S(AnimScriptInstance=self.anim, RelativeRotation=rotation)
        self.pawn = sdk_object(S(Mesh=self.mesh, bIsCrouched=False,
                                bUseControllerRotationYaw=False,
                                K2_GetActorRotation=lambda: rotation,
                                GetLastMovementInputVector=lambda: zero,
                                IsCharacterDashing=lambda: False), 'OakCharacter')
        self.movement = S(MovementMode=1, CustomMovementMode=0, Velocity=zero,
                          Acceleration=zero, bIsSprinting=False, bWantsToSprint=False,
                          bWantsToStartSprinting=False, bWantsToDash=False,
                          bOrientRotationToMovement=False, bUseControllerDesiredRotation=False)
        self.pawn.OakCharacterMovement = self.movement
        sdk_object(self.camera, 'Camera')
        self.camera.GetCameraRotation = lambda: rotation
        self.weapon.CurrentState = 'Active'
        self.runtime = (self.pc, self.pawn, self.camera)
        self.mod._get_runtime = lambda: self.runtime
        self.o.refs = tuple(lambda obj=obj: obj for obj in (*self.runtime, self.movement))
        self.o.combat_refs = tuple(lambda obj=obj: obj for obj in (self.mesh, self.anim, self.weapon))
        self.o.active = self.o.ready = True
        self.o.report['optional_field_errors'] = {}
        self.o.collect_pose_diagnostics = False
        self.keys = dict(sprint=False, dash=False, crouch=False, jump=False,
                         fire=False, zoom=True, gadget=False)
        self.o.inputs = S(begin_frame=lambda: None, snapshot=lambda pc: dict(self.keys),
                          revision=1, metadata=lambda: dict(revision=1), present_roles=set(self.keys))
        self.supervisor = S(child=self.o)
        setattr(self.mod, KEY, self.supervisor)
        self.stops = []
        def finish(reason):
            self.stops.append(reason)
            self.o.active = False
        self.o.finish = finish
        self.o.native.validate = lambda: None
        self.o.native.consume = lambda: None
        self.o.native.consume_slide = lambda: None
        # Enter the real camera guard via the real ground handoff. No native
        # Slide/Dash code can run in this Linux harness.
        self.o._slide_live_frame = self.o._handoff_frame
        def ground_leaf(*args):
            self.o._combat_frame(*args)
            self.o._root_frame(*args)
        self.o._dash_vector_frame = ground_leaf
        self.o._visual_frame = lambda *args: None
        self.mode_calls = []
        original_switch = self.camera.SetActorCameraMode
        def switch(pawn, mode, *args):
            if mode == 'Default':
                self.assert_controls_off()
            self.mode_calls.append(mode)
            original_switch(pawn, mode, *args)
            self.camera.CameraModeState.bIsTransitioning = True
        self.camera.SetActorCameraMode = switch

    def assert_controls_off(self):
        for owner in self.o.owners():
            control = getattr(owner, 'control', None)
            if control is not None:
                self.assertFalse(control[0])
        self.assertFalse(self.o.native.control[7])
        self.assertFalse(self.o.native.slide_control[0])
        self.assertFalse(self.o.aim_native.crouch_control[0])
        self.assertFalse(self.o.vector_trace.control[7])
        self.assertFalse(self.o.vector_trace.control[12])
        for _action, _rva, owner, _trace in self.o.entries:
            self.assertFalse(owner.control[0])
            self.assertFalse(owner.control[16])

    def tick(self):
        self.o.frame(None, None, None, None)
        self.assertEqual(self.stops, [], self.o.report['errors'])
        self.assertEqual(self.o.report['errors'], [])
        self.assertTrue(self.o.active)

    def enter(self):
        # Equip -> held TPS ADS -> configured Sprint press. The sampling
        # callback must still see TPS. Only the camera stage switches modes.
        self.weapon.CurrentState = 'Equipping'
        self.tick()
        self.weapon.CurrentState = 'Active'
        self.keys['sprint'] = True
        self.tick()
        self.assertEqual(self.o.report['hybrid_scope_last'], 'queued')
        self.assertTrue(self.o.report['samples'][-1]['normal_tps_sample'])
        self.assertEqual(self.mode_calls, [])
        hybrid_ads.update(self.mod)
        self.assertEqual(self.mode_calls, ['Default'])
        self.assertEqual(self.o.report['hybrid_scope_last'], 'scope_on')
        self.tick()
        self.assertEqual(self.o.report['samples'][-1]['handoff_state'], 'HYBRID_SCOPE_NATIVE_PAUSE')
        self.assert_controls_off()

    def settle(self):
        self.camera.CameraModeState.bIsTransitioning = False

    def test_reported_failure_reproduces_with_inline_camera_switch(self):
        self.keys['sprint'] = True
        with patch.object(hybrid_ads, 'request_scope', lambda mod, obj: hybrid_ads.toggle_scope(mod)):
            self.o.frame(None, None, None, None)
        self.assertEqual(self.stops, ['LEFT_NORMAL_TPS'])

    def test_scope_stays_paused_and_one_press_switches_once(self):
        self.enter()
        self.settle()
        for _ in range(8):
            self.tick()
            hybrid_ads.update(self.mod)
            self.assert_controls_off()
        self.assertEqual(self.mode_calls, ['Default'])
        self.assertEqual(self.o.report['hybrid_scope_presses'], 1)

    def test_toggle_back_waits_for_blend_and_sprint_release_with_ads_held(self):
        self.enter()
        self.settle()
        self.keys['sprint'] = False
        self.tick()
        self.keys['sprint'] = True
        self.tick()
        hybrid_ads.update(self.mod)
        self.assertEqual(self.mode_calls, ['Default', 'ThirdPerson'])
        self.tick()
        self.assert_controls_off()
        self.assertTrue(self.o.special_paused)
        self.settle()
        # Route reconciliation has completed its same-weapon TPS rearm.
        self.mod._ads_route = 'tps'
        self.mod._ads_handoff['route_pending'] = None
        self.tick()
        self.assertTrue(self.o.special_paused, 'Sprint must be released before resuming')
        self.assert_controls_off()
        self.keys['sprint'] = False
        self.tick()
        self.assertFalse(self.o.special_paused)
        self.assertTrue(self.o.report['samples'][-1]['combat']['ads_active'])
        self.assertEqual(self.o.report['special_resume_count'], 1)
        self.assertTrue(self.o.report['samples'][-1]['normal_tps_sample'])

    def test_settled_camera_waits_for_tps_ads_route_reconciliation(self):
        self.enter()
        self.settle()
        self.keys['sprint'] = False
        self.tick()
        self.keys['sprint'] = True
        self.tick()
        hybrid_ads.update(self.mod)
        self.keys['sprint'] = False
        self.settle()
        self.tick()
        self.assertTrue(self.o.special_paused, 'FPS ADS route still awaits TPS reconciliation')
        self.assert_controls_off()
        self.mod._ads_route = 'tps'
        self.mod._ads_handoff['route_pending'] = None
        self.tick()
        self.assertFalse(self.o.special_paused)

    def test_ads_release_returns_only_after_observed_blend_end(self):
        self.enter()
        self.mod._ads_active = False
        self.mod._ads_route = 'hip'
        self.keys.update(zoom=False, sprint=False)
        hybrid_ads.release_transition(self.mod, .06)
        self.camera.SetActorCameraMode(self.pawn, 'ThirdPerson', '', .2, False, True)
        self.tick()
        self.assert_controls_off()
        self.settle()
        self.tick()
        self.assertFalse(self.o.special_paused)

    def test_ignored_return_never_reenables_omni_in_default_camera(self):
        self.enter()
        self.settle()
        self.keys['sprint'] = False
        self.tick()
        self.keys['sprint'] = True
        self.tick()
        self.camera.SetActorCameraMode = lambda *args: None
        hybrid_ads.update(self.mod)
        self.keys['sprint'] = False
        for _ in range(12):
            self.tick()
            self.assert_controls_off()
        self.assertEqual(self.camera.mode, 'Default')

    def test_queued_press_is_cancelled_on_release_disable_or_weapon_change(self):
        for change in ('release', 'disable', 'weapon', 'route', 'retired', 'ui'):
            with self.subTest(change=change):
                self.setUp_context_for_request()
                self.assertEqual(hybrid_ads.request_scope(self.mod, self.o), 'queued')
                if change == 'release': self.mod._ads_active = False
                if change == 'disable': self.mod.omni_hybrid_ads.value = False
                if change == 'weapon': self.camera.CameraModeInputs.Weapon = S(Name='Other')
                if change == 'route': self.mod._ads_route = 'hip'
                if change == 'retired': self.o.active = False
                if change == 'ui': self.pc.bShowMouseCursor = True
                hybrid_ads.update(self.mod)
                self.assertEqual(self.mode_calls, [])
                self.assertIsNone(self.o.hybrid_scope_request)

    def setUp_context_for_request(self):
        self.mod._ads_active = True
        self.mod.omni_hybrid_ads.value = True
        self.mod._ads_route = 'tps'
        self.mod._ads_handoff['held'] = True
        self.camera.CameraModeInputs.Weapon = self.weapon
        self.o.active = True
        self.pc.bShowMouseCursor = False

    def test_queued_request_does_not_move_to_a_new_gameplay_session(self):
        hybrid_ads.request_scope(self.mod, self.o)
        replacement, _ = session()
        self.supervisor.child = replacement
        hybrid_ads.update(self.mod)
        self.assertEqual(self.mode_calls, [])

    def test_runtime_change_between_input_and_camera_stage_refuses_request(self):
        hybrid_ads.request_scope(self.mod, self.o)
        self.runtime = (self.pc, self.pawn, S(CameraModeInputs=S(Weapon=self.weapon)))
        hybrid_ads.update(self.mod)
        self.assertEqual(self.mode_calls, [])

    def test_ffyl_and_ui_keep_existing_special_handoff(self):
        self.enter()
        self.settle()
        self.camera.mode = 'FFYL'
        self.tick()
        self.assert_controls_off()
        self.assertEqual(self.o.report['samples'][-1]['handoff_state'], 'SPECIAL_NATIVE_PAUSE')
        self.camera.mode = 'ThirdPerson'
        hybrid_ads._state['scoped'] = False
        self.pc.bShowMouseCursor = True
        self.tick()
        self.assert_controls_off()

    def test_camera_failure_does_not_replay_or_change_ads_route(self):
        self.keys['sprint'] = True
        self.tick()
        self.camera.fail = RuntimeError('SDK switch refused')
        hybrid_ads.update(self.mod)
        self.assertEqual(self.o.report['hybrid_scope_last'], 'error')
        self.assertEqual(self.mod._ads_route, 'tps')
        self.assertIsNone(self.o.hybrid_scope_request)
        self.keys['sprint'] = False
        self.tick()
        self.assertFalse(self.o.special_paused)

    def test_native_validation_failure_during_scope_still_stops_session(self):
        self.enter()
        self.o.native.hook = object()
        self.o.native.validate = lambda: (_ for _ in ()).throw(RuntimeError('patch changed'))
        self.o.frame(None, None, None, None)
        self.assertEqual(self.stops, ['SPECIAL_HANDOFF_FAILED'])
        self.assertFalse(self.o.active)
        self.assert_controls_off()


if __name__ == '__main__':
    unittest.main()
