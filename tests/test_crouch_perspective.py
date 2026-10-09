import unittest
from types import SimpleNamespace as S
from unittest.mock import patch
from support import session
from BL4ThirdPersonPOC.omni.lifecycle import LifecycleSupervisor


class CrouchTests(unittest.TestCase):
    def test_idle_discovery_includes_other_receiver_and_refreshes_scalar_state(self):
        from support import prop
        o, _ = session()
        fields = [prop('BlendWeight', 'FloatProperty', 32), prop('bTurning', 'BoolProperty', 40)]
        layout = S(Name='GbxAnimNode_IdleTurns', _properties=lambda: fields)
        properties = [prop(o.IDLE_NODE_NAME, 'StructProperty', 100, Struct=layout),
                      prop('OtherIdle', 'StructProperty', 200, Struct=layout)]
        cls = S(_superfields=lambda: (), _properties=lambda: properties)
        anim = S(Class=cls, OtherIdle=S(BlendWeight=1., bTurning=True))
        setattr(anim, o.IDLE_NODE_NAME, S(BlendWeight=0., bTurning=False))
        pawn = S(Mesh=S(AnimScriptInstance=anim))
        o.head_anim = lambda: anim
        o.anim_address = 10000
        o.idle_native.table = 20000
        o.native.read = lambda address, count: (20000).to_bytes(8, 'little')
        o.bound = lambda: (None, pawn, None, None)
        rows = o.capture_idle_nodes()
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(row for row in rows if row['name']=='OtherIdle')['values']['BlendWeight'], 1.)
        anim.OtherIdle.BlendWeight = .25
        self.assertEqual(next(row for row in o.capture_idle_nodes() if row['name']=='OtherIdle')['values']['BlendWeight'], .25)
        pawn.Mesh.AnimScriptInstance = object()
        with self.assertRaisesRegex(RuntimeError, 'owner changed'):
            o.capture_idle_nodes()

    def setup_crouch(self):
        o, _ = session()
        o.active = True
        o.ready = True
        o.frames = 5
        o.native.base = 1000
        o.native.validate = lambda: None
        pc = S(bShowMouseCursor=False)
        rotation = S(Pitch=0., Yaw=0., Roll=0.)
        pawn = S(bIsCrouched=True, IsCharacterDashing=lambda: False,
                 K2_GetActorRotation=lambda: rotation)
        camera = S(GetActorCameraMode=lambda _: 'ThirdPerson')
        movement = S(MovementMode=1, CustomMovementMode=0)
        o.bound = lambda: (pc, pawn, camera, movement)
        o.mod._third_person_enabled = True
        o.mod._slide_active = False
        o.mod._vehicle_camera_active = False
        o.mod._shop_camera_active = False
        o.mod._ladder_active = False
        o.jump_down = lambda _: False
        o.air_dash_down = lambda _: True  # Held Crouch action must not block rotation.
        o.combat = {'active': False}
        row = dict(t=1., input_yaw=90., movement_input_active=True,
                   horizontal_speed=10., control_rotation={'Yaw': -90.})
        o.report['samples'] = [row]
        def rotate(_, value):
            rotation.Yaw = value['Yaw']
            return True
        o.set_rotation = rotate
        return o, pawn, row, rotation

    def test_held_crouch_selects_crouch_not_input_handoff(self):
        o, pawn, _, _ = self.setup_crouch()
        self.assertEqual(o.classify_handoff(*o.bound()), ('PAUSE', 'CROUCHED'))
        o.mod._slide_active = True
        self.assertEqual(o.classify_handoff(*o.bound()), ('PAUSE', 'SLIDE'))

    def test_slow_crouch_can_start_follow_and_preserves_native_dash_disabled(self):
        o, pawn, row, rotation = self.setup_crouch()
        o.crouch_frame()
        row['t'] += .05
        o.crouch_frame()
        self.assertAlmostEqual(rotation.Yaw, 27.)
        self.assertEqual(o.aim_native.crouch_control[0], 1)
        self.assertEqual(o.vector_trace.control[7], 0)
        self.assertEqual(o.dash_branch.control[7], 0)
        row['movement_input_active'] = False
        row['t'] += .05
        o.crouch_frame()
        self.assertAlmostEqual(rotation.Yaw, 27.)

    def test_combat_releases_pose_neutralization_and_aims_at_control(self):
        o, pawn, row, rotation = self.setup_crouch()
        o.crouch_frame()
        o.combat['active'] = True
        row['t'] += .05
        o.crouch_frame()
        self.assertAlmostEqual(rotation.Yaw, -54.)
        self.assertEqual(o.aim_native.crouch_control[0], 0)
        self.assertEqual(o.native.control[7], 0)

    def test_failed_rotation_readback_is_rejected(self):
        o, pawn, row, _ = self.setup_crouch()
        o.crouch_frame()
        row['t'] += .05
        o.set_rotation = lambda *args: True
        with self.assertRaisesRegex(RuntimeError, 'readback'):
            o.crouch_frame()


class PerspectiveTests(unittest.TestCase):
    def test_retired_pose_evidence_preserves_crouch_and_standing_transition_bounded(self):
        rows = [dict(update_index=i, is_crouched=i<300, ignored='unused') for i in range(400)]
        source = dict(crouch_idle_layouts=[['ActualIdle', 123]], crouch_follow_updates=300,
                      crouch_pose_pairs=list(range(200)), head_pose_samples=list(range(200)), samples=rows)
        kept = LifecycleSupervisor.retained_pose_diagnostics(source)
        self.assertEqual(len(kept['crouch_pose_pairs']), 128)
        self.assertEqual(len(kept['head_pose_samples']), 128)
        self.assertEqual(len(kept['transition_samples']), 256)
        self.assertEqual(kept['crouch_idle_layouts'], source['crouch_idle_layouts'])
        self.assertTrue(kept['transition_samples'][0]['is_crouched'])
        self.assertFalse(kept['transition_samples'][-1]['is_crouched'])
        self.assertNotIn('ignored', kept['transition_samples'][0])

    def test_pre_fps_retires_before_bound_and_keeps_supervisor(self):
        o, _ = session()
        state = LifecycleSupervisor(o.mod, o.updates)
        state.active = True
        state.child = o
        o.mod._third_person_enabled = False
        o.bound = lambda: self.fail('FPS retirement must precede bound sampling')
        retired = []
        def retire(reason):
            retired.append(reason)
            state.child = None
        state.retire = retire
        state.frame(None, None, None, None)
        state.frame(None, None, None, None)
        self.assertEqual(retired, ['PERSPECTIVE_NATIVE_HANDOFF'])
        self.assertTrue(state.active)
        self.assertFalse(state.report['errors'])
        self.assertEqual(state.phase, 'WAITING_TPS_ENABLED')

    def test_post_fps_uses_same_retirement_before_gameplay_reads(self):
        o, _ = session()
        o.active = True
        o.mod._third_person_enabled = False
        called = []
        o.lifecycle_supervisor = S(pause_perspective=lambda: called.append('pause'))
        o.bound = lambda: self.fail('No gameplay reads after FPS transition')
        o.frame(None, None, None, None)
        self.assertEqual(called, ['pause'])

    def test_return_to_tps_reuses_stable_binding_gate(self):
        o, _ = session()
        state = LifecycleSupervisor(o.mod, o.updates)
        state.active = True
        o.mod._third_person_enabled = True
        objects = [object() for _ in range(4)]
        refs = tuple(lambda obj=obj: obj for obj in objects)
        state.eligible = lambda: (((1, 2, 3, 4), refs), 'ON_FOOT_READY')
        child = S(report={}, install=lambda: None)
        with patch('BL4ThirdPersonPOC.omni.lifecycle.GameplaySession', return_value=child):
            state.frame(None, None, None, None)
            self.assertIsNone(state.child)
            state.frame(None, None, None, None)
        self.assertIs(state.child, child)
        self.assertEqual(state.report['rebind_count'], 1)

    def test_cleanup_failure_on_perspective_switch_still_fails_closed(self):
        o, _ = session()
        state = LifecycleSupervisor(o.mod, o.updates)
        state.active = True
        state.child = o
        o.mod._third_person_enabled = False
        state.retire = lambda _: (_ for _ in ()).throw(RuntimeError('cleanup conflict'))
        caught = []
        state.fail = lambda where, exc: caught.append((where, str(exc)))
        state.frame(None, None, None, None)
        self.assertEqual(caught, [('widget_pre', 'cleanup conflict')])
