"""Only the measured TurnState writer is held; the .38 skeletal pose stays native."""
from types import SimpleNamespace as S
from unittest.mock import Mock, patch
import unittest
import test_slam_pose_handoff_0_3_9_38 as pose


def controls(session):
    return (session.native.control[0],session.native.control[7],
            session.idle_native.control[0],session.idle_update.control[0],
            session.aim_native.control[0],session.aim_native.crouch_control[0])


def fixture():
    session,pc,pawn,camera,movement=pose.fixture()
    session.mod._ads_active=False
    session.slam_heading_owned=False
    session.native.control[8]=session.native.base+0x56EF1AD # prior slide caller
    return session,pc,pawn,camera,movement


class HeadingTests(unittest.TestCase):
    def test_known_airborne_turn_caller_only_with_complete_native_pose(self):
        session,pc,pawn,camera,movement=fixture()
        movement.MovementMode=3;camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        for _ in range(50):
            session.release_native_slam_pose()
            session.paused_special_frame(None,None,None,None)
            session.publish_native_slam_heading()
            self.assertEqual(controls(session),(1,1,0,0,0,0))
            self.assertEqual(session.native.control[8],session.native.base+0x2E2E17)
        self.assertEqual(session.report['ground_slam_heading_hold']['eligible_updates'],50)
        # Validate once on acquisition; existing normal owner audits stay active.
        self.assertEqual(session.native.validate.call_count,1)
        pawn.K2_SetActorRotation.assert_not_called()
        for owner in (session.idle_native,session.idle_update,session.aim_native):
            self.assertFalse(any(i==0 and value for i,value in owner.control.writes))

    def test_heading_held_across_exit_and_own_return_blend(self):
        session,pc,pawn,camera,movement=fixture()
        for mode in ('GroundSlamExit','ThirdPerson'):
            camera.GetActorCameraMode=lambda pawn,mode=mode:mode
            camera.CameraModeState.bIsTransitioning=True
            session.release_native_slam_pose()
            session.paused_special_frame(None,None,None,None)
            session.publish_native_slam_heading()
            self.assertEqual(controls(session),(1,1,1,1,0,0))
            self.assertTrue(session.slam_heading_owned)
        pawn.K2_SetActorRotation.assert_not_called()

    def test_combat_ads_ui_and_other_special_contexts_release_heading(self):
        for blocked in ('combat','ads','cursor','vehicle','shop','ladder','slide','fps','mode','impulse'):
            with self.subTest(blocked=blocked):
                session,pc,pawn,camera,movement=fixture()
                session.publish_native_slam_heading()
                self.assertTrue(session.slam_heading_owned)
                if blocked=='combat':session.combat['active']=True
                elif blocked=='cursor':pc.bShowMouseCursor=True
                elif blocked=='fps':session.mod._third_person_enabled=False
                elif blocked=='mode':camera.GetActorCameraMode=lambda pawn:'Default'
                elif blocked=='impulse':session.impulse_index=None
                else:setattr(session.mod,{'ads':'_ads_active','vehicle':'_vehicle_camera_active',
                    'shop':'_shop_camera_active','ladder':'_ladder_active','slide':'_slide_active'}[blocked],True)
                session.publish_native_slam_heading()
                self.assertEqual(controls(session),(0,0,0,0,0,0))
                self.assertFalse(session.slam_heading_owned)

    def test_mixed_pose_is_rejected_before_heading_publication(self):
        session,*_=fixture();session.idle_update.control[0]=1
        with self.assertRaisesRegex(RuntimeError,'pose controls'):session.publish_native_slam_heading()
        self.assertEqual(session.native.control[0],0)
        self.assertEqual(session.native.control[7],0)

    def test_missing_owned_native_hook_is_rejected(self):
        session,*_=fixture();session.native.hook=None
        with self.assertRaisesRegex(RuntimeError,'installed owned'):session.publish_native_slam_heading()
        self.assertEqual(session.native.control[0],0)

    def test_ordinary_omni_controls_untouched_without_slam_ownership(self):
        session,*_=fixture();session.ground_slam_pose_native=False
        session.native.control[0]=session.native.control[7]=1
        session.native.control.writes.clear()
        session.publish_native_slam_heading()
        self.assertEqual(session.native.control.writes,[])

    def test_failed_native_validation_leaves_replacement_disabled(self):
        session,*_=fixture()
        session.native.validate.side_effect=RuntimeError('owner changed')
        with self.assertRaisesRegex(RuntimeError,'owner changed'):session.publish_native_slam_heading()
        self.assertEqual(controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_heading_owned)

    def test_existing_shutdown_closes_heading_before_native_cleanup(self):
        import support
        session,_=support.session()
        session.native.control[0]=session.native.control[7]=1
        session.slam_heading_owned=True
        session.report['ground_slam_heading_hold']=dict(enabled=True)
        session.finish('TEST_SLAM_STOP')
        self.assertEqual(session.native.control[0],0)
        self.assertEqual(session.native.control[7],0)
        self.assertFalse(session.slam_heading_owned)
        self.assertFalse(session.report['ground_slam_heading_hold']['enabled'])

    def test_real_frame_publishes_after_special_pause_and_disarms_before_resume(self):
        session,pc,pawn,camera,movement=fixture()
        session.lifecycle_managed=False
        session.inputs=S(begin_frame=lambda **kwargs:None,end_frame=lambda:None)
        session.disarm_ground_vector=Mock();session.ground_clip_originals=[]
        session.close_jump=Mock();session.finish=Mock()
        session.special_paused=False;session.special_signature=None
        session.enter_special=Mock(side_effect=lambda:setattr(session,'special_paused',True))
        session.controls_down=lambda pc:False;session.slide_exit_pending=lambda *args:False
        session.save_state_edge=Mock();session.resume_handoff=Mock()
        session.report['special_resume_count']=0
        pawn.IsCharacterDashing=Mock(return_value=False)
        pawn.IsPerformingGroundSlam.return_value=True
        movement.MovementMode=3
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson'
        def context(objects):
            return dict(third_person=True,camera_mode='ThirdPerson',movement_mode=int(movement.MovementMode),
                        custom_movement_mode=0,flags=dict(_vehicle_camera_active=False,
                        _slide_active=False,_shop_camera_active=False,_ladder_active=False))
        session.state_context=context
        session._ground_pose_frame=session._special_frame
        resumed=[]
        def normal(*args):
            resumed.append(controls(session))
            session.native.control[0]=session.native.control[7]=1
        session._slide_live_frame=normal
        with patch('BL4ThirdPersonPOC.omni.session.hybrid_ads.omni_pause_required',return_value=False):
            session.frame(None,None,None,None)
            self.assertEqual(controls(session),(1,1,0,0,0,0))
            self.assertFalse(resumed)
            self.assertTrue(session.slam_heading_owned)
            # Return blend retains heading; settled TPS releases before normal
            # pipeline re-publishes its controls, not after that publication.
            pawn.IsPerformingGroundSlam.return_value=False;movement.MovementMode=1
            camera.CameraModeState.bIsTransitioning=True
            session.frame(None,None,None,None)
            self.assertEqual(controls(session),(1,1,0,0,0,0))
            camera.CameraModeState.bIsTransitioning=False
            session.frame(None,None,None,None)
            self.assertEqual(resumed,[(0,0,0,0,0,0)])
            self.assertEqual(controls(session),(1,1,0,0,0,0))
            self.assertFalse(session.slam_heading_owned)
        session.finish.assert_not_called()
        pawn.K2_SetActorRotation.assert_not_called()
        self.assertFalse(session.report['errors'])


if __name__=='__main__':unittest.main()
