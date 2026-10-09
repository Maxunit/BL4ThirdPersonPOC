"""Measured mapping/state handback, real input reader and body-follow path.

SDK objects/native workers are simulated. The live report replay proves the
recognition/state decisions, not BL4's native animation timing or visual result.
"""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
import test_fixes_0_3_9_12 as old_tests
import test_hybrid_omni_handoff_0_3_9_14 as handoff_tests
from BL4ThirdPersonPOC.input_bindings import NativeBindings
from BL4ThirdPersonPOC.omni.carry_throw_handoff import CarryThrowHandoff


class CarryStateTests(unittest.TestCase):
    def setUp(self):
        self.handoff = CarryThrowHandoff()

    def step(self, intent=False, context=True, carrying=True, eligible=True, now=1.):
        return self.handoff.observe(intent=intent, context=context, carrying=carrying,
                                    eligible=eligible, now=now)

    def test_reported_sequence_holds_after_key_release_until_context_removal(self):
        self.assertFalse(self.step())  # picked up, still free facing
        self.assertTrue(self.step(intent=True, carrying=False))
        self.assertEqual(self.handoff.phase, 'OBJECT_RELEASED')
        for _ in range(100):
            self.assertTrue(self.step(carrying=False, now=9999.))
        self.assertFalse(self.step(context=False, carrying=False))
        self.assertEqual(self.handoff.episodes[-1]['end_reason'], 'CARRY_CONTEXT_ENDED')
        self.assertTrue(self.handoff.episodes[-1]['object_release_observed'])
        self.assertFalse(self.handoff.episodes[-1]['timer_based_release'])

    def test_repeated_reads_do_not_end_or_rearm_a_hold(self):
        self.step()
        self.step(intent=True, carrying=False)
        for _ in range(8): self.assertTrue(self.step(intent=True, carrying=False))
        for _ in range(8): self.assertTrue(self.step(carrying=False))
        self.assertEqual(self.handoff.started, 1)

    def test_released_key_without_object_release_never_latches(self):
        self.step()
        self.assertTrue(self.step(intent=True))
        self.assertFalse(self.step())
        self.assertEqual(self.handoff.episodes[-1]['end_reason'], 'RELEASED_WITHOUT_OBJECT_RELEASE')

    def test_unknown_carry_state_supports_held_intent_only(self):
        for _ in range(3): self.assertTrue(self.step(intent=True, carrying=None))
        self.assertFalse(self.step(carrying=None))
        self.assertEqual(self.handoff.episodes[-1]['end_reason'], 'CARRY_STATE_UNAVAILABLE')

    def test_state_read_lost_after_release_does_not_leave_context_latched(self):
        self.step(); self.step(intent=True, carrying=False)
        self.assertFalse(self.step(carrying=None))

    def test_object_drop_without_throw_press_does_not_turn_body(self):
        self.step()
        self.assertFalse(self.step(carrying=False))
        self.assertEqual(self.handoff.started, 0)

    def test_new_object_or_special_context_ends_hold_without_replaying_held_key(self):
        for exit_args, reason in [({'carrying': True}, 'NEW_CARRIED_OBJECT'),
                                  ({'carrying': False, 'eligible': False}, 'INELIGIBLE')]:
            self.handoff = CarryThrowHandoff()
            self.step(); self.step(intent=True, carrying=False)
            self.assertFalse(self.step(intent=True, **exit_args))
            self.assertEqual(self.handoff.episodes[-1]['end_reason'], reason)
            self.assertFalse(self.step(intent=True))


class CarryInputTests(unittest.TestCase):
    def reader(self):
        self.pc = support.controller()
        self.reader = NativeBindings(self.pc)
        self.reader.refresh(require_complete=True)
        self.pc.PlayerInput.EnhancedActionMappings.pop()  # native carry removes zoom
        self.pc.PlayerInput.EnhancedActionMappings.extend([
            support.mapping('Action_Carry_Throw', 'PlayerThrow'),
            support.mapping('Action_Carry_Throw', 'Gamepad_LeftTrigger')])
        self.reader.maybe_refresh(require_complete=True)
        return self.reader

    def test_remapped_keyboard_and_controller_throw_are_not_ads_or_fire(self):
        reader = self.reader()
        for key in ('PlayerThrow', 'Gamepad_LeftTrigger'):
            self.pc.pressed = {key}
            snapshot = reader.snapshot(self.pc)
            self.assertTrue(snapshot['carry_throw'])
            self.assertFalse(snapshot['zoom'] or snapshot['fire'])
        self.assertTrue(reader.complete)

    def test_count_change_restores_zoom_and_removes_throw_binding_while_key_stays_held(self):
        reader = self.reader()
        self.pc.pressed = {'Gamepad_LeftTrigger'}
        rows = self.pc.PlayerInput.EnhancedActionMappings
        rows[:] = [r for r in rows if 'Action_Carry_Throw' not in r.Action._path_name()]
        rows.append(support.mapping('Action_Zoom', 'Gamepad_LeftTrigger'))
        reader.begin_frame(); reader.maybe_refresh(require_complete=True)
        self.assertTrue(reader.snapshot(self.pc)['zoom'])
        self.assertFalse(reader.snapshot(self.pc)['carry_throw'])
        self.assertNotIn('carry_throw', reader.present_roles)

    def test_ignored_and_complex_carry_rows_never_create_throw_intent(self):
        reader = self.reader()
        for row in self.pc.PlayerInput.EnhancedActionMappings:
            if 'Action_Carry_Throw' in row.Action._path_name(): row.bShouldBeIgnored = True
        reader.refresh(require_complete=True)
        self.pc.pressed = {'PlayerThrow', 'Gamepad_LeftTrigger'}
        self.assertFalse(reader.snapshot(self.pc)['carry_throw'])
        chord = S(Class=S(Name='InputTriggerChordAction'))
        self.pc.PlayerInput.EnhancedActionMappings.append(
            support.mapping('Action_Carry_Throw', 'PlayerThrow', triggers=(chord,)))
        reader.refresh(require_complete=True)
        self.assertFalse(reader.snapshot(self.pc)['carry_throw'])
        self.assertEqual(reader.skipped_optional, 1)


class CarryCombatTests(old_tests.CombatHarness, unittest.TestCase):
    def setUp(self):
        self.build()
        self.keys.update(gadget=False, carry_throw=False)
        self.obj.inputs.present_roles = {'fire', 'carry_throw'}
        self.anim.bIsCarrying = True
        self.movement.bIsSprinting = self.movement.bWantsToSprint = False

    def test_real_combat_holds_without_any_montage_api_and_clears_on_native_context_end(self):
        self.assertFalse(self.read()['active'])
        self.keys['carry_throw'] = True
        self.anim.bIsCarrying = False
        self.assertTrue(self.read()['active'])
        self.keys['carry_throw'] = False
        for _ in range(4):
            combat = self.read()
            self.assertTrue(combat['carry_throw_hold'] and combat['throw_hold'] and combat['active'])
        self.obj.inputs.present_roles.remove('carry_throw')
        self.assertFalse(self.read()['active'])
        self.assertNotIn('throw_montage_error', self.obj.report)
        self.assertEqual(self.obj.report['carry_throw_episodes'][-1]['end_reason'], 'CARRY_CONTEXT_ENDED')

    def test_menu_and_slide_block_carry_alignment(self):
        for flag in ('menu', 'slide'):
            self.setUp()
            self.read()
            self.keys['carry_throw'] = True
            self.anim.bIsCarrying = False
            if flag == 'menu': self.pc.bShowMouseCursor = True
            else: self.obj.mod._slide_active = True
            self.assertFalse(self.read()['carry_throw_hold'])

    def test_missing_carry_state_is_input_only_and_does_not_stop_combat_reader(self):
        del self.anim.bIsCarrying
        self.keys['carry_throw'] = True
        self.assertTrue(self.read()['carry_throw_hold'])
        self.keys['carry_throw'] = False
        self.assertFalse(self.read()['active'])
        self.assertIn('AttributeError', self.obj.report['carry_throw_state_error'])


class CarryBodyTests(unittest.TestCase):
    tick = handoff_tests.HandoffTests.tick

    def setUp(self):
        handoff_tests.HandoffTests.setUp(self)
        self.mod._ads_active = False
        self.keys.update(zoom=False, carry_throw=False)
        self.mod._slide_active = False
        self.o.inputs.present_roles = {'fire', 'carry_throw'}
        self.anim.bIsCarrying = True
        self.actor = S(Pitch=0., Yaw=-90., Roll=0.)
        self.pawn.K2_GetActorRotation = lambda: self.actor
        def set_actor(value, teleport):
            self.actor = value
            return True
        self.pawn.K2_SetActorRotation = set_actor
        self.o.impulse_index = 1
        self.o.follow_started_t = 0.
        self.o.follow_previous_t = 0.
        self.o.started = 0.
        self.movement.Velocity = S(X=0., Y=-200., Z=0.)
        self.movement.Acceleration = self.movement.Velocity
        self.pawn.GetLastMovementInputVector = lambda: S(X=0., Y=-1., Z=0.)
        def ground_leaf(*args):
            self.o._combat_frame(*args)
            self.o._body_frame(*args)
        self.o._dash_vector_frame = ground_leaf

    def test_actual_session_body_follows_camera_during_throw_then_returns_to_movement(self):
        with patch('BL4ThirdPersonPOC.omni.sampling.monotonic', return_value=1.): self.tick()
        self.assertEqual(self.actor.Yaw, -90.)
        self.keys['carry_throw'] = True
        self.anim.bIsCarrying = False
        for i in range(1, 5):
            with patch('BL4ThirdPersonPOC.omni.sampling.monotonic', return_value=1.+i*.05): self.tick()
        self.assertAlmostEqual(self.actor.Yaw, 90.)
        self.assertEqual(self.o.report['samples'][-1]['follow_mode'], 'COMBAT_AIM')
        self.keys['carry_throw'] = False
        with patch('BL4ThirdPersonPOC.omni.sampling.monotonic', return_value=1.3): self.tick()
        self.assertEqual(self.actor.Yaw, 90.)
        self.o.inputs.present_roles.remove('carry_throw')
        with patch('BL4ThirdPersonPOC.omni.sampling.monotonic', return_value=1.35): self.tick()
        self.assertEqual(self.o.report['samples'][-1]['follow_mode'], 'MOVEMENT_FOLLOW')
        self.assertNotEqual(self.actor.Yaw, 90.)
