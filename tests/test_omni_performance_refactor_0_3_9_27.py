"""Coherent intent boundaries and preserved guards; SDK stubs are not FPS proof."""
from types import SimpleNamespace as S
from unittest.mock import Mock, patch
import unittest

import support
from BL4ThirdPersonPOC.input_bindings import NativeBindings
from BL4ThirdPersonPOC.omni.session import GameplaySession
from BL4ThirdPersonPOC.omni.visual_guard import validate_visual


class CountedMappings(list):
    reads = 0

    def __len__(self):
        self.reads += 1
        return super().__len__()


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.pc = support.controller()
        self.rows = CountedMappings(self.pc.PlayerInput.EnhancedActionMappings)
        self.pc.PlayerInput.EnhancedActionMappings = self.rows
        self.reader = NativeBindings(self.pc)
        self.reader.refresh(require_complete=True)
        self.rows.reads = 0

    def test_one_mapping_check_and_key_read_for_twelve_consumers(self):
        original = self.pc.IsInputKeyDown
        self.pc.IsInputKeyDown = Mock(side_effect=original)
        self.reader.begin_frame(coherent=True)
        for _ in range(12):
            self.reader.snapshot(self.pc)
        self.assertEqual(self.rows.reads, 1)
        self.assertEqual(self.pc.IsInputKeyDown.call_count, 6)
        self.reader.end_frame()
        self.assertIsNone(self.reader.frame_snapshot)
        self.assertFalse(self.reader.frame_cache_enabled)
        self.assertFalse(self.reader.coherent_callback)

    def test_shared_reader_default_keeps_immediate_mapping_count_checks(self):
        self.reader.begin_frame()
        for _ in range(12):
            self.reader.snapshot(self.pc)
        self.assertEqual(self.rows.reads, 12)
        self.rows.append(support.mapping('Action_Carry_Throw', 'UserCarry'))
        self.pc.pressed.add('UserCarry')
        self.assertTrue(self.reader.snapshot(self.pc)['carry_throw'])

    def test_count_change_and_new_key_are_admitted_next_callback(self):
        self.reader.begin_frame(coherent=True)
        self.assertFalse(self.reader.snapshot(self.pc)['carry_throw'])
        self.rows.append(support.mapping('Action_Carry_Throw', 'UserCarry'))
        self.pc.pressed.add('UserCarry')
        self.assertFalse(self.reader.snapshot(self.pc)['carry_throw'])
        self.reader.end_frame()
        self.reader.begin_frame(coherent=True)
        self.assertTrue(self.reader.snapshot(self.pc)['carry_throw'])

    def test_explicit_refresh_invalidates_intent_even_inside_callback(self):
        self.reader.begin_frame(coherent=True)
        self.assertFalse(self.reader.snapshot(self.pc)['fire'])
        self.rows[4].Key.KeyName = 'RemappedFire'
        self.pc.pressed.add('RemappedFire')
        self.reader.refresh(require_complete=True)
        self.assertTrue(self.reader.snapshot(self.pc)['fire'])

    def test_expired_or_replaced_owner_rejected_before_cached_intent(self):
        for changed in ('input', 'weak_input', 'weak_controller', 'controller'):
            with self.subTest(changed=changed):
                self.setUp()
                self.reader.begin_frame(coherent=True)
                self.reader.snapshot(self.pc)
                supplied = self.pc
                if changed == 'input':
                    self.pc.PlayerInput = S()
                elif changed == 'weak_input':
                    self.reader.player_input_ref = lambda: None
                elif changed == 'weak_controller':
                    self.reader.controller_ref = lambda: None
                else:
                    supplied = support.controller()
                with self.assertRaisesRegex(RuntimeError, 'snapshot owner changed'):
                    self.reader.snapshot(supplied)

    def test_consumers_cannot_mutate_snapshot_for_other_consumers(self):
        self.reader.begin_frame(coherent=True)
        first = self.reader.snapshot(self.pc)
        first['fire'] = True
        self.assertFalse(self.reader.snapshot(self.pc)['fire'])

    def test_gameplay_failure_closes_scope_and_does_not_reuse_next_intent(self):
        session = GameplaySession.__new__(GameplaySession)
        session.active, session.busy, session.lifecycle_managed = True, False, False
        session.mod = S(_third_person_enabled=True)
        session.updates = S(is_game_thread=lambda: True)
        session.inputs = self.reader
        pawn = S(IsCharacterDashing=lambda: False)
        session.bound = lambda: (self.pc, pawn, S(), S())
        session.disarm_ground_vector = lambda: None
        session.ground_clip_originals = []
        session.report = dict(errors=[])
        session.finish = Mock()
        def leaf(*args):
            self.reader.snapshot(self.pc)
            raise RuntimeError('state changed')
        session._ground_pose_frame = leaf
        session.frame(None, None, None, None)
        session.finish.assert_called_once_with('COMBINED_GROUND_FAILED')
        self.assertIsNone(self.reader.frame_snapshot)
        self.assertFalse(self.reader.coherent_callback)
        self.pc.pressed.add('UserBinding_4')
        self.assertTrue(self.reader.snapshot(self.pc)['fire'])


def visual_session():
    session = GameplaySession.__new__(GameplaySession)
    session.active, session.busy = True, False
    session.updates = S(is_game_thread=lambda: True)
    node = S(RotationChannelName=S(TagName='RotationChannel.Aim'),
             BlendSpaceKey=S(TagName='AnimSet.Player.3rd.AimO_3rd'), ALPHA=1., BlendWeight=1.)
    anim = S(_get_address=lambda: 0x4000,
             **{name: 0. for name in session.INPUT_NAMES})
    setattr(anim, session.NODE_NAME, node)
    mesh = S(AnimScriptInstance=anim)
    movement = S(MovementMode=1, CustomMovementMode=0)
    pawn = S(Mesh=mesh, OakCharacterMovement=movement)
    pc = S(bShowMouseCursor=False)
    camera = S(GetActorCameraMode=lambda pawn: 'ThirdPerson')
    runtime = [pc, pawn, camera]
    session.mod = S(_get_runtime=lambda: tuple(runtime), _third_person_enabled=True)
    session.refs = tuple(lambda obj=obj: obj for obj in (*runtime, movement))
    session.mesh_ref, session.anim_ref = lambda: mesh, lambda: anim
    session.anim_address = 0x4000
    session.collect_pose_diagnostics = False
    session.frames, session.started = 0, 0.
    session.report = dict(errors=[], visual_samples=[], special_state_edges=[])
    session.finish = Mock()
    session._body_frame = Mock()
    return session, S(node=node, anim=anim, mesh=mesh, pawn=pawn, runtime=runtime)


class VisualGuardTests(unittest.TestCase):
    def test_normal_gameplay_validates_without_pose_or_rotation_reporting(self):
        session, _ = visual_session()
        session.visual = Mock(side_effect=AssertionError('full diagnostic capture'))
        session._visual_frame(None, None, None, None)
        session._body_frame.assert_called_once()
        session.finish.assert_not_called()
        self.assertEqual(session.report['visual_samples'], [])
        self.assertEqual(session.report['errors'], [])

    def test_diagnostics_path_still_captures_visual_rows_and_runs_gameplay(self):
        session, _ = visual_session()
        session.collect_pose_diagnostics = True
        row = dict(update_index=1)
        session.visual = Mock(return_value=row)
        session._visual_frame(None, None, None, None)
        self.assertEqual(session.report['visual_samples'], [row])
        session._body_frame.assert_called_once()

    def test_each_animation_input_nonfinite_stops_before_body_writes(self):
        for name in GameplaySession.INPUT_NAMES:
            with self.subTest(name=name):
                session, objects = visual_session()
                setattr(objects.anim, name, float('nan'))
                session._visual_frame(None, None, None, None)
                session.finish.assert_called_once_with('VISUAL_CAPTURE_FAILED')
                session._body_frame.assert_not_called()

    def test_boolean_animation_inputs_remain_supported(self):
        session, objects = visual_session()
        objects.anim.bIsMoving2D = False
        values, _ = validate_visual(session, capture=True)
        self.assertIs(values['bIsMoving2D'], False)

    def test_actual_visual_capture_keeps_animation_and_aim_fields(self):
        session, objects = visual_session()
        rotation = S(Pitch=0., Yaw=30., Roll=0.)
        session.bones, session.restore_pending = [], False
        objects.pawn.K2_GetActorRotation = lambda: rotation
        objects.runtime[2].GetCameraRotation = lambda: rotation
        objects.mesh.K2_GetComponentRotation = lambda: rotation
        objects.mesh.RelativeRotation = rotation
        objects.pawn.OakCharacterMovement.Velocity = S(X=10., Y=0., Z=0.)
        objects.anim.Class = S(Name='Animation', _path_name=lambda: '/Script/Test.Animation')
        objects.anim._path_name = lambda: '/Test/Animation'
        objects.node.BlendSpace = None
        objects.node.YawAxis, objects.node.PitchAxis = 0, 1
        row = session._aim_binding_visual()
        self.assertEqual(set(row['animation_inputs']), set(session.INPUT_NAMES))
        self.assertEqual(row['normal_aim_offset'], dict(channel='RotationChannel.Aim',
            blend_space_key='AnimSet.Player.3rd.AimO_3rd', ALPHA=1., BlendWeight=1.,
            BlendSpace=None, YawAxis=0, PitchAxis=1))
        self.assertIn('velocity_relative_actor', row)

    def test_aim_schema_and_values_guards_preserved(self):
        for changed in ('channel', 'key', 'alpha', 'weight'):
            with self.subTest(changed=changed):
                session, objects = visual_session()
                if changed == 'channel':
                    objects.node.RotationChannelName.TagName = 'Other'
                elif changed == 'key':
                    objects.node.BlendSpaceKey.TagName = 'Other'
                elif changed == 'alpha':
                    objects.node.ALPHA = float('inf')
                else:
                    objects.node.BlendWeight = float('nan')
                with self.assertRaises(RuntimeError):
                    validate_visual(session)

    def test_weak_lifetime_runtime_and_component_changes_fail_closed(self):
        for changed in ('mesh_expired', 'anim_expired', 'mesh_owner', 'anim_owner',
                        'anim_address', 'runtime', 'movement', 'pawn_expired'):
            with self.subTest(changed=changed):
                session, objects = visual_session()
                if changed == 'mesh_expired': session.mesh_ref = lambda: None
                elif changed == 'anim_expired': session.anim_ref = lambda: None
                elif changed == 'mesh_owner': objects.pawn.Mesh = S()
                elif changed == 'anim_owner': objects.mesh.AnimScriptInstance = S()
                elif changed == 'anim_address': objects.anim._get_address = lambda: 0x5000
                elif changed == 'runtime': objects.runtime[0] = S()
                elif changed == 'movement': objects.pawn.OakCharacterMovement = S()
                else: session.refs = (session.refs[0], lambda: None, *session.refs[2:])
                with self.assertRaises(RuntimeError): validate_visual(session)

    def test_compact_state_still_drives_handoffs_without_object_descriptions(self):
        session, _ = visual_session()
        with patch('BL4ThirdPersonPOC.omni.diagnostics.describe', side_effect=AssertionError('description')):
            row = session.state_context()
        self.assertEqual(row['bound_identity_matches'], [True, True, True])
        self.assertTrue(row['movement_identity_matches'])
        self.assertEqual(row['camera_mode'], 'ThirdPerson')
        self.assertNotIn('current_objects', row)

    def test_state_edge_descriptions_built_once_at_edge(self):
        session, _ = visual_session()
        row = session.state_context()
        with patch('BL4ThirdPersonPOC.omni.diagnostics.describe', return_value={'name': 'live'}) as describe:
            session.save_state_edge(row, 'SPECIAL_PAUSED')
        self.assertEqual(describe.call_count, 3)
        self.assertNotIn('current_objects', row)
        self.assertEqual(len(session.report['special_state_edges'][0]['current_objects']), 3)

    def test_state_stage_resolves_once_and_next_stage_rechecks_runtime(self):
        session, objects = visual_session()
        runtime = session.mod._get_runtime
        session.mod._get_runtime = Mock(side_effect=runtime)
        row = session.state_context(session.bound())
        self.assertEqual(session.mod._get_runtime.call_count, 1)
        self.assertTrue(row['movement_identity_matches'])
        objects.runtime[0] = S()
        with self.assertRaisesRegex(RuntimeError, 'Local player or camera changed'):
            session.bound()


if __name__ == '__main__':
    unittest.main()
