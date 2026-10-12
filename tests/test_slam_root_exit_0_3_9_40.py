"""Measured Exit Root conflict: extra correction guard without IdleUpdate/Aim suppression."""
from types import SimpleNamespace as S
from unittest.mock import Mock, patch
import unittest
import support
import test_slam_heading_0_3_9_39 as heading


def fixture():
    session,pc,pawn,camera,movement=heading.fixture()
    session.slam_exit_root_owned=False
    return session,pc,pawn,camera,movement


class RootExitTests(unittest.TestCase):
    def test_exit_skips_only_extra_root_rotation_and_retains_native_pose_update(self):
        session,pc,pawn,camera,movement=fixture()
        for _ in range(83):
            session.release_native_slam_pose()
            session.paused_special_frame(None,None,None,None)
            session.publish_native_slam_heading()
            self.assertEqual(heading.controls(session),(1,1,1,0,0,0))
            self.assertTrue(session.slam_exit_root_owned)
            self.assertTrue(session.report['ground_slam_heading_hold']['root_correction_skipped'])
        self.assertEqual(session.idle_native.validate.call_count,1)
        self.assertFalse(any(i==0 and value for i,value in session.idle_update.control.writes))
        self.assertFalse(any(i==0 and value for i,value in session.aim_native.control.writes))
        pawn.K2_SetActorRotation.assert_not_called()

    def test_airborne_slam_has_no_root_override_even_after_previous_exit(self):
        session,pc,pawn,camera,movement=fixture()
        session.publish_native_slam_heading()
        self.assertTrue(session.slam_exit_root_owned)
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson';movement.MovementMode=3
        pawn.IsPerformingGroundSlam.return_value=True
        session.release_native_slam_pose();session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(1,1,0,0,0,0))
        self.assertFalse(session.slam_exit_root_owned)
        self.assertFalse(session.report['ground_slam_heading_hold']['root_correction_skipped'])

    def test_air_return_without_seen_exit_does_not_enable_root(self):
        session,pc,pawn,camera,movement=fixture()
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        camera.CameraModeState.bIsTransitioning=True
        session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(1,1,0,0,0,0))
        self.assertFalse(session.slam_exit_root_owned)

    def test_own_exit_return_keeps_root_until_disarmed_before_normal_publish(self):
        session,pc,pawn,camera,movement=fixture()
        session.publish_native_slam_heading()
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        camera.CameraModeState.bIsTransitioning=True
        for _ in range(35):
            session.release_native_slam_pose();session.publish_native_slam_heading()
            self.assertEqual(heading.controls(session),(1,1,1,0,0,0))
        session.ground_slam_pose_native=False;session.disarm_slam_heading()
        self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_exit_root_owned)

    def test_repeated_publication_accepts_its_own_root_guard(self):
        session,*_=fixture()
        session.publish_native_slam_heading();session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(1,1,1,0,0,0))
        self.assertEqual(session.idle_native.validate.call_count,1)

    def test_unavailable_or_changed_root_guard_fails_before_heading_publication(self):
        for broken in ('missing','changed'):
            with self.subTest(broken=broken):
                session,*_=fixture()
                if broken=='missing':session.idle_native.hook=None
                else:session.idle_native.validate.side_effect=RuntimeError('Root owner changed')
                with self.assertRaises(RuntimeError):session.publish_native_slam_heading()
                self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
                self.assertFalse(session.slam_exit_root_owned)

    def test_special_priority_releases_root_as_well_as_heading(self):
        for key in ('_ads_active','_vehicle_camera_active','_shop_camera_active','_ladder_active','_slide_active'):
            with self.subTest(key=key):
                session,*_=fixture();session.publish_native_slam_heading()
                setattr(session.mod,key,True);session.publish_native_slam_heading()
                self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
                self.assertFalse(session.slam_exit_root_owned)

    def test_shutdown_closes_owned_root_and_report(self):
        session,_=support.session()
        session.native.control[0]=session.native.control[7]=session.idle_native.control[0]=1
        session.slam_heading_owned=session.slam_exit_root_owned=True
        session.report['ground_slam_heading_hold']=dict(enabled=True,root_correction_skipped=True)
        session.finish('TEST_SLAM_ROOT_STOP')
        self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_exit_root_owned)
        self.assertFalse(session.report['ground_slam_heading_hold']['root_correction_skipped'])

    def test_real_frame_air_exit_return_and_normal_resume_preserve_ownership_order(self):
        session,pc,pawn,camera,movement=fixture()
        mode='ThirdPerson';movement.MovementMode=3
        pawn.IsPerformingGroundSlam.return_value=True
        pawn.IsCharacterDashing=Mock(return_value=False)
        camera.GetActorCameraMode=lambda pawn:mode
        session.lifecycle_managed=False
        session.inputs=S(begin_frame=lambda **kwargs:None,end_frame=lambda:None)
        session.disarm_ground_vector=Mock();session.ground_clip_originals=[]
        session.close_jump=Mock();session.finish=Mock()
        session.special_paused=False;session.special_signature=None
        session.enter_special=Mock(side_effect=lambda:setattr(session,'special_paused',True))
        session.controls_down=lambda pc:False;session.slide_exit_pending=lambda *args:False
        session.save_state_edge=Mock();session.resume_handoff=Mock()
        session.report['special_resume_count']=0
        session.state_context=lambda objects:dict(third_person=True,camera_mode=mode,
            movement_mode=int(movement.MovementMode),custom_movement_mode=0,
            flags=dict(_vehicle_camera_active=False,_slide_active=False,
                       _shop_camera_active=False,_ladder_active=False))
        session._ground_pose_frame=session._special_frame
        resumed=[]
        def normal(*args):
            resumed.append(heading.controls(session))
            session.native.control[0]=session.native.control[7]=1
            session.idle_native.control[0]=session.idle_update.control[0]=1
        session._slide_live_frame=normal
        with patch('BL4ThirdPersonPOC.omni.session.hybrid_ads.omni_pause_required',return_value=False):
            session.frame(None,None,None,None)
            self.assertEqual(heading.controls(session),(1,1,0,0,0,0))
            mode='GroundSlamExit';movement.MovementMode=1
            pawn.IsPerformingGroundSlam.return_value=False
            session.frame(None,None,None,None)
            self.assertEqual(heading.controls(session),(1,1,1,0,0,0))
            mode='ThirdPerson';camera.CameraModeState.bIsTransitioning=True
            session.frame(None,None,None,None)
            self.assertEqual(heading.controls(session),(1,1,1,0,0,0))
            camera.CameraModeState.bIsTransitioning=False
            session.frame(None,None,None,None)
            self.assertEqual(resumed,[(0,0,0,0,0,0)])
            self.assertEqual(heading.controls(session),(1,1,1,1,0,0))
            self.assertFalse(session.slam_heading_owned or session.slam_exit_root_owned)
        session.finish.assert_not_called()
        pawn.K2_SetActorRotation.assert_not_called()
        self.assertFalse(session.report['errors'])


if __name__=='__main__':unittest.main()
