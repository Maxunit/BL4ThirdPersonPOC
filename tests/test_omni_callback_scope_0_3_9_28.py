"""0.3.9.28: per-callback identity scope, round-robin native audits, one read per key.

The cost budget runs the real Omni pipeline in a counting fake world. Counts are
exact for that world; they are not timings or FPS. In-game proof is the F10
profiler (Total-Messung) in the same spot as the .26/.27 captures.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import Mock

import support
import BL4ThirdPersonPOC.input_bindings as input_bindings
from BL4ThirdPersonPOC.input_bindings import NativeBindings
from BL4ThirdPersonPOC.omni.session import GameplaySession
from test_omni_performance_refactor_0_3_9_27 import visual_session

# Per idle update (lifecycle PRE + gameplay POST) in the counting fake world.
# 0.3.9.27 measured: stand 30 runtime / 392 props / 48 UFunctions / 28 reads,
# crouch 23 / 300 / 49 / 28, and 20 full mapping scans per 600 updates.
# 0.3.9.29 adds running scenarios and the grenade class check (path strings
# become cheap identity comparisons, hence the higher uobj_eq limit).
BUDGETS = {
    'stand': dict(get_runtime=2, prop_get=160, ufunc=28, rpm=6, uobj_eq=60, weak_deref=50, path_name=1),
    'crouch': dict(get_runtime=2, prop_get=125, ufunc=32, rpm=8, uobj_eq=50, weak_deref=40, path_name=1),
    'move': dict(get_runtime=2, prop_get=180, ufunc=29, rpm=10, uobj_eq=65, weak_deref=55, path_name=1),
    'turn': dict(get_runtime=2, prop_get=180, ufunc=32, rpm=10, uobj_eq=65, weak_deref=55, path_name=1),
}


def run_cost(scenario):
    script = Path(__file__).with_name('omni_idle_cost_scenario.py')
    result = subprocess.run([sys.executable, str(script), scenario], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class CostBudgetTests(unittest.TestCase):
    def test_idle_updates_stay_within_sdk_budget(self):
        for scenario, budget in BUDGETS.items():
            with self.subTest(scenario=scenario):
                report = run_cost(scenario)
                for category, limit in budget.items():
                    self.assertLessEqual(report['per_update'][category], limit, (scenario, category))
                # Full mapping scans stay a rare fallback (count/menu edges are immediate).
                self.assertLessEqual(report['mapping_scans'], 2)


class CallbackScopeTests(unittest.TestCase):
    def setUp(self):
        self.session, self.objects = visual_session()
        self.calls = Mock(side_effect=self.session.mod._get_runtime)
        self.session.mod._get_runtime = self.calls

    def test_outside_a_callback_every_bound_resolves_the_runtime(self):
        self.session.bound()
        self.session.bound()
        self.assertEqual(self.calls.call_count, 2)

    def test_inside_a_callback_identity_is_validated_once(self):
        self.session.open_callback_scope()
        first = self.session.bound()
        for _ in range(20):
            self.assertIs(self.session.bound(), first)
        self.assertEqual(self.calls.call_count, 1)
        self.session.close_callback_scope()
        self.session.bound()
        self.assertEqual(self.calls.call_count, 2)

    def test_changed_local_player_is_seen_by_the_next_callback(self):
        self.session.open_callback_scope()
        self.session.bound()
        self.session.close_callback_scope()
        self.objects.runtime[0] = S()
        self.session.open_callback_scope()
        with self.assertRaisesRegex(RuntimeError, 'Local player or camera changed'):
            self.session.bound()

    def test_failed_callback_drops_objects_and_values(self):
        session = GameplaySession.__new__(GameplaySession)
        session.active, session.busy, session.lifecycle_managed = True, False, False
        session.mod = S(_third_person_enabled=True)
        session.updates = S(is_game_thread=lambda: True)
        session.inputs = S(begin_frame=lambda **kw: None, end_frame=lambda: None)
        pawn = S(IsCharacterDashing=Mock(return_value=False))
        objects = (S(), pawn, S(GetActorCameraMode=lambda pawn: 'ThirdPerson'),
                   S(MovementMode=1, CustomMovementMode=0))
        session.refs = tuple(lambda o=o: o for o in objects)
        session.mod._get_runtime = lambda: objects[:3]
        pawn.OakCharacterMovement = objects[3]
        session.disarm_ground_vector = lambda: None
        session.ground_clip_originals = []
        session.report = dict(errors=[])
        session.finish = Mock()

        def leaf(*args):
            self.assertFalse(session.is_dashing(pawn))
            self.assertFalse(session.is_dashing(pawn))
            raise RuntimeError('state changed')
        session._ground_pose_frame = leaf
        session.frame(None, None, None, None)
        session.finish.assert_called_once_with('COMBINED_GROUND_FAILED')
        self.assertIsNone(session._callback_objects)
        self.assertIsNone(session._callback_values)
        self.assertFalse(session._callback_scope)
        # frame() and leaf share one native dash read.
        self.assertEqual(pawn.IsCharacterDashing.call_count, 1)

    def test_game_write_invalidates_memoized_getters(self):
        session = self.session
        reads = iter([False, True])
        pawn = S(IsCharacterDashing=lambda: next(reads), K2_SetActorRotation=lambda *a: True)
        session.report['game_writes'] = 0
        session.open_callback_scope()
        self.assertFalse(session.is_dashing(pawn))
        self.assertFalse(session.is_dashing(pawn))
        session.set_rotation(pawn, dict(Pitch=0., Yaw=1., Roll=0.))
        self.assertTrue(session.is_dashing(pawn))
        session.close_callback_scope()

    def test_finish_inside_a_callback_closes_the_scope(self):
        session, _ = support.session()
        session.open_callback_scope()
        session._callback_objects = ('validated earlier in this callback',)
        session.finish('TEST_STOP')
        self.assertIsNone(session._callback_objects)
        self.assertFalse(session._callback_scope)


class NativeAuditTests(unittest.TestCase):
    SLOTS = range(11)

    def due(self, session):
        return {slot for slot in self.SLOTS if session.native_audit_due(slot)}

    def test_first_update_and_resume_audit_every_slot(self):
        session = GameplaySession.__new__(GameplaySession)
        self.assertEqual(self.due(session), set(self.SLOTS))
        session._audit_full, session._audit_tick = False, 3
        self.assertLess(len(self.due(session)), len(self.SLOTS))
        session.control = [0] * 9
        session.route_ready = session.ready = session.vector_ready = False
        session.follow_previous_t = session.started = 0.
        session.transition_event = lambda reason: None
        session._handoff_resume_handoff()
        self.assertEqual(self.due(session), set(self.SLOTS))

    def test_every_slot_within_one_period_at_most_two_per_update(self):
        session = GameplaySession.__new__(GameplaySession)
        session._audit_full = False
        seen = set()
        for tick in range(session.NATIVE_AUDIT_PERIOD):
            session._audit_tick = tick
            due = self.due(session)
            self.assertLessEqual(len(due), 2)
            seen |= due
        self.assertEqual(seen, set(self.SLOTS))


class KeyKindTests(unittest.TestCase):
    def setUp(self):
        self.pc = support.controller()
        self.digital, self.analog = [], []
        original_down, original_analog = self.pc.IsInputKeyDown, self.pc.GetInputAnalogKeyState
        self.pc.IsInputKeyDown = lambda key: (self.digital.append(str(key.KeyName)), original_down(key))[1]
        self.pc.GetInputAnalogKeyState = lambda key: (self.analog.append(str(key.KeyName)), original_analog(key))[1]
        self.original_find = getattr(input_bindings.unrealsdk, 'find_class', None)

    def tearDown(self):
        if self.original_find is None:
            if hasattr(input_bindings.unrealsdk, 'find_class'):
                del input_bindings.unrealsdk.find_class
        else:
            input_bindings.unrealsdk.find_class = self.original_find

    def library(self, analog=(), button_axis=(), fail=False):
        def is_analog(key):
            if fail:
                raise RuntimeError('no function')
            return str(key.KeyName) in analog

        def is_button_axis(key):
            return str(key.KeyName) in button_axis
        cdo = S(Key_IsAnalog=is_analog, Key_IsButtonAxis=is_button_axis)
        input_bindings.unrealsdk.find_class = lambda name: S(ClassDefaultObject=cdo)

    def reader(self):
        reader = NativeBindings(self.pc)
        reader.refresh(require_complete=True)
        self.digital.clear()
        self.analog.clear()
        return reader

    def test_unavailable_classifier_keeps_both_reads(self):
        if hasattr(input_bindings.unrealsdk, 'find_class'):
            del input_bindings.unrealsdk.find_class
        reader = self.reader()
        reader.snapshot(self.pc)
        self.assertEqual(len(self.digital), 6)
        self.assertEqual(len(self.analog), 6)

    def test_classifier_error_keeps_both_reads(self):
        self.library(fail=True)
        reader = self.reader()
        reader.snapshot(self.pc)
        self.assertEqual((len(self.digital), len(self.analog)), (6, 6))

    def test_one_read_per_plain_button_or_axis(self):
        self.library(analog={'UserBinding_5'}, button_axis={'UserBinding_4'})
        reader = self.reader()
        reader.snapshot(self.pc)
        self.assertNotIn('UserBinding_5', self.digital)
        self.assertEqual(self.analog, ['UserBinding_4', 'UserBinding_5'])
        self.assertEqual(len(self.digital), 5)

    def test_intent_unchanged_for_pressed_button_and_moved_axis(self):
        self.library(analog={'UserBinding_5'})
        reader = self.reader()
        self.pc.pressed.add('UserBinding_0')
        self.pc.analog['UserBinding_5'] = 0.3
        snapshot = reader.snapshot(self.pc)
        self.assertTrue(snapshot['sprint'])
        self.assertTrue(snapshot['zoom'])
        self.assertFalse(snapshot['fire'])
        self.pc.analog['UserBinding_5'] = float('nan')
        with self.assertRaisesRegex(RuntimeError, 'Nonfinite'):
            reader.snapshot(self.pc)


class GroundPreparationTests(unittest.TestCase):
    def test_standing_still_skips_handler_validation_and_native_read(self):
        session = GameplaySession.__new__(GameplaySession)
        owner = S(control=[0] * 24)
        session.entries = [('Action_Crouch', 0, owner, None)]
        session.vector_trace = S(read=Mock(side_effect=AssertionError('native read')))
        session.validate_handler = Mock(side_effect=AssertionError('handler'))
        session.ground_prepared = None
        session._ground_vector_prepare_ground(dict(velocity=dict(X=3., Y=4., Z=0.)))
        self.assertIsNone(session.ground_prepared)
        self.assertEqual(owner.control[16], 0)


if __name__ == '__main__':
    unittest.main()
