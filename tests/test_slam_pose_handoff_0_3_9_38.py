"""Actual legacy Exit pipeline: pose gates, transient writes and native handoff."""
from types import SimpleNamespace as S
import unittest
from unittest.mock import Mock
import support
from BL4ThirdPersonPOC.omni.session import GameplaySession
from BL4ThirdPersonPOC.omni.free_look import publish


class Controls(list):
    def __init__(self,n):
        super().__init__([0]*n)
        self.writes=[]
    def __setitem__(self,index,value):
        self.writes.append((index,value))
        super().__setitem__(index,value)


def fixture():
    session=GameplaySession.__new__(GameplaySession)
    session.active=True;session.busy=False;session.frames=10
    session.updates=S(is_game_thread=lambda:True)
    session.mod=S(_third_person_enabled=True)
    session.native=S(control=Controls(10),slide_control=Controls(7),hook={},base=0x140000000,validate=Mock())
    session.vector_trace=S(control=Controls(13))
    session.idle_native=S(control=Controls(9),hook={},validate=Mock())
    session.idle_update=S(control=Controls(9),hook={},validate=Mock())
    session.aim_native=S(control=Controls(6),crouch_control=Controls(6),hook={},validate=Mock())
    session.slam_cycle=None;session.slam_sequence=0
    session.slam_override_owned=session.slam_pose_owned=session.slam_trace_window=False
    session.jump_idle_owned=False;session.jump_cycle=None
    session.impulse_index=1;session.combat=dict(active=False)
    session.free_look_context=False;session.ground_slam_pose_native=True
    session.cycle_start=None;session.ground_circle_previous_dash=False
    session.collect_pose_diagnostics=True
    session.consume_slam_records=Mock();session.capture_rotate_state=lambda:{}
    session.audit_owners=Mock();session.discard_special_input=Mock();session.read_combat=Mock()
    session.trim_diagnostics=Mock()
    def clear():
        session.native.control[0]=session.native.control[7]=0
        session.idle_native.control[0]=session.idle_update.control[0]=0
        session.aim_native.control[0]=session.aim_native.crouch_control[0]=0
    session.disable_special_controls=clear
    def sample(*args):
        session.frames+=1
        session.report['samples'].append(dict(update_index=session.frames,normal_tps_sample=False,
            combat=dict(active=False),actor_rotation=dict(Yaw=180.),camera_rotation=dict(Yaw=0.)))
    session._sample_frame=sample
    session.report={name:[] for name in ('samples','errors','ground_slam_native_cycles',
        'ground_slam_rotate_state_samples','ground_slam_native_ab_rows','ground_slam_pose_ab_rows')}
    session.report['special_pause_updates']=0
    pc=S(bShowMouseCursor=False,GetControlRotation=lambda:S(Yaw=0.))
    pawn=S(K2_GetActorRotation=lambda:S(Yaw=180.),K2_SetActorRotation=Mock(),
           IsPerformingGroundSlam=Mock(return_value=False))
    camera=S(GetActorCameraMode=lambda pawn:'GroundSlamExit',CameraModeState=S(bIsTransitioning=False))
    movement=S(MovementMode=1,CustomMovementMode=0)
    session.bound=lambda:(pc,pawn,camera,movement)
    session.combat_refs=(lambda:None,lambda:S(AimYaw=-180.,AimPitch=25.))
    return session,pc,pawn,camera,movement


class SlamPoseTests(unittest.TestCase):
    def test_opposite_camera_body_exit_cannot_reopen_rotation_idle_or_aim(self):
        session,pc,pawn,camera,movement=fixture()
        for _ in range(90):
            session.paused_special_frame(None,None,None,None)
            publish(session)
            values=(session.native.control[0],session.native.control[7],
                    session.idle_native.control[0],session.idle_update.control[0],
                    session.aim_native.control[0],session.aim_native.crouch_control[0])
            self.assertEqual(values,(0,0,0,0,0,0))
        # Recording is read-only; neither pose nor rotation replacement is enabled.
        self.assertEqual(session.native.slide_control[0],1)
        for owner in (session.idle_native,session.idle_update,session.aim_native):
            self.assertFalse(any(i==0 and value for i,value in owner.control.writes))
        self.assertFalse(any(i in (0,7) and value for i,value in session.native.control.writes))
        pawn.K2_SetActorRotation.assert_not_called()
        self.assertTrue(all(not row['pose_enabled'] for row in session.report['ground_slam_pose_ab_rows']))

    def test_native_context_covers_air_exit_and_only_its_own_tps_blend(self):
        session,pc,pawn,camera,movement=fixture()
        mode='ThirdPerson'
        camera.GetActorCameraMode=lambda pawn:mode
        session.ground_slam_pose_native=False
        movement.MovementMode=3
        pawn.IsPerformingGroundSlam.return_value=False
        self.assertFalse(session.native_slam_pose_context(pawn,camera,movement))
        pawn.IsPerformingGroundSlam.return_value=True
        self.assertTrue(session.native_slam_pose_context(pawn,camera,movement))
        pawn.IsPerformingGroundSlam.return_value=False
        movement.MovementMode=1;mode='GroundSlamExit'
        self.assertTrue(session.native_slam_pose_context(pawn,camera,movement))
        session.ground_slam_pose_native=True;mode='ThirdPerson'
        camera.CameraModeState.bIsTransitioning=True
        self.assertTrue(session.native_slam_pose_context(pawn,camera,movement))
        camera.CameraModeState.bIsTransitioning=False
        self.assertFalse(session.native_slam_pose_context(pawn,camera,movement))
        camera.CameraModeState.bIsTransitioning=True
        session.ground_slam_pose_native=False
        self.assertFalse(session.native_slam_pose_context(pawn,camera,movement))
        session.ground_slam_pose_native=True;mode='Default'
        self.assertFalse(session.native_slam_pose_context(pawn,camera,movement))

    def test_early_release_closes_previous_free_look_and_jump_gates(self):
        session,pc,pawn,camera,movement=fixture()
        session.native.control[0]=session.native.control[7]=1
        session.idle_native.control[0]=session.idle_update.control[0]=1
        session.aim_native.control[0]=session.aim_native.crouch_control[0]=2
        session.slam_override_owned=session.slam_pose_owned=session.jump_idle_owned=True
        session.release_native_slam_pose()
        self.assertEqual((session.native.control[0],session.native.control[7],
            session.idle_native.control[0],session.idle_update.control[0],
            session.aim_native.control[0],session.aim_native.crouch_control[0]),(0,0,0,0,0,0))
        self.assertFalse(session.slam_override_owned or session.slam_pose_owned or session.jump_idle_owned)

    def test_real_special_pipeline_routes_active_slam_to_native_pause_not_air_facing(self):
        session,pc,pawn,camera,movement=fixture()
        session.lifecycle_managed=False
        session.mod._third_person_enabled=True
        session.state_context=lambda objects:dict(third_person=True,camera_mode='ThirdPerson',
            movement_mode=3,custom_movement_mode=0,flags=dict(_vehicle_camera_active=False,
            _slide_active=False,_shop_camera_active=False,_ladder_active=False))
        session.report['last_lifecycle_context']={}
        session.special_paused=False;session.special_signature=None
        session.enter_special=Mock(side_effect=lambda:setattr(session,'special_paused',True))
        session.save_state_edge=Mock();session.slide_exit_pending=lambda *args:False
        session.controls_down=lambda pc:False
        session._slide_live_frame=Mock()
        session.ground_slam_pose_native=True
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        movement.MovementMode=3
        pawn.IsPerformingGroundSlam.return_value=True
        with unittest.mock.patch('BL4ThirdPersonPOC.omni.session.hybrid_ads.omni_pause_required',return_value=False):
            session._special_frame(None,None,None,None)
        session.enter_special.assert_called_once()
        session._slide_live_frame.assert_not_called()
        pawn.K2_SetActorRotation.assert_not_called()
        self.assertEqual(session.report['special_pause_updates'],1)
        self.assertFalse(session.report['errors'])

    def test_settled_tps_resumes_existing_pipeline_after_native_pose(self):
        session,pc,pawn,camera,movement=fixture()
        session.lifecycle_managed=False;session.ground_slam_pose_native=False
        session.state_context=lambda objects:dict(third_person=True,camera_mode='ThirdPerson',
            movement_mode=1,custom_movement_mode=0,flags=dict(_vehicle_camera_active=False,
            _slide_active=False,_shop_camera_active=False,_ladder_active=False))
        session.special_paused=True;session.special_signature='slam'
        session.report['special_resume_count']=0
        session.slide_exit_pending=lambda *args:False;session.controls_down=lambda pc:False
        session.resume_handoff=Mock();session._slide_live_frame=Mock();session.save_state_edge=Mock()
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        with unittest.mock.patch('BL4ThirdPersonPOC.omni.session.hybrid_ads.omni_pause_required',return_value=False):
            session._special_frame(None,None,None,None)
        session.resume_handoff.assert_called_once()
        session._slide_live_frame.assert_called_once()
        self.assertFalse(session.special_paused)
        self.assertEqual(session.report['special_resume_count'],1)
        self.assertFalse(session.report['errors'])


if __name__=='__main__':unittest.main()
