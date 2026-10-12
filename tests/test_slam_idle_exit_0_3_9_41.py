"""Stable Exit input zero without reopening Aim or leaking ownership to normal Omni."""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock
import unittest
import support
import test_slam_root_exit_0_3_9_40 as root
import test_slam_heading_0_3_9_39 as heading


class IdleExitTests(unittest.TestCase):
    def test_exit_selects_idle_with_no_transient_aim_override(self):
        session,pc,pawn,camera,movement=root.fixture()
        for _ in range(81):
            session.release_native_slam_pose()
            session.paused_special_frame(None,None,None,None)
            session.publish_native_slam_heading()
            self.assertEqual(heading.controls(session),(1,1,1,1,0,0))
        self.assertTrue(session.slam_exit_idle_owned)
        self.assertTrue(session.report['ground_slam_heading_hold']['idle_fallback_selected'])
        self.assertEqual(session.idle_update.validate.call_count,1)
        self.assertFalse(any(i==0 and v for i,v in session.aim_native.control.writes))
        self.assertFalse(any(i==0 and v for i,v in session.aim_native.crouch_control.writes))
        pawn.K2_SetActorRotation.assert_not_called()

    def test_airborne_slam_releases_idle_fallback_from_previous_exit(self):
        session,pc,pawn,camera,movement=root.fixture()
        session.publish_native_slam_heading()
        camera.GetActorCameraMode=lambda pawn:'ThirdPerson';movement.MovementMode=3
        pawn.IsPerformingGroundSlam.return_value=True
        session.release_native_slam_pose();session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(1,1,0,0,0,0))
        self.assertFalse(session.slam_exit_idle_owned)

    def test_repeat_publication_and_normal_resume_close_own_idle_only(self):
        session,*_=root.fixture()
        session.publish_native_slam_heading();session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(1,1,1,1,0,0))
        session.ground_slam_pose_native=False;session.disarm_slam_heading()
        self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_exit_idle_owned)
        # Normal Omni can re-open its own input gate; no later Slam close leaks.
        session.idle_update.control[0]=1;session.publish_native_slam_heading()
        self.assertEqual(session.idle_update.control[0],1)

    def test_missing_or_changed_idle_worker_cannot_publish_partial_exit_controls(self):
        for missing in (True,False):
            session,*_=root.fixture()
            if missing:session.idle_update.hook=None
            else:session.idle_update.validate.side_effect=RuntimeError('idle owner changed')
            with self.assertRaises(RuntimeError):session.publish_native_slam_heading()
            self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
            self.assertFalse(session.slam_exit_idle_owned)

    def test_combat_releases_all_three_owned_overrides(self):
        session,*_=root.fixture();session.publish_native_slam_heading()
        session.combat['active']=True;session.publish_native_slam_heading()
        self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_heading_owned or session.slam_exit_root_owned or session.slam_exit_idle_owned)

    def test_shutdown_closes_idle_and_ownership_report(self):
        session,_=support.session()
        session.native.control[0]=session.native.control[7]=1
        session.idle_native.control[0]=session.idle_update.control[0]=1
        session.slam_heading_owned=session.slam_exit_root_owned=session.slam_exit_idle_owned=True
        session.report['ground_slam_heading_hold']=dict(enabled=True,root_correction_skipped=True,idle_fallback_selected=True)
        session.finish('TEST_SLAM_IDLE_STOP')
        self.assertEqual(heading.controls(session),(0,0,0,0,0,0))
        self.assertFalse(session.slam_exit_idle_owned)
        self.assertFalse(session.report['ground_slam_heading_hold']['idle_fallback_selected'])

    def test_captured_native_update_keeps_generic_update_while_selecting_idle(self):
        source=Path(__file__).with_name('slam_idle_native_replay_scenario.py')
        result=subprocess.run([sys.executable,str(source)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        if 'skipped' in report:self.skipTest(report['skipped'])
        self.assertEqual([x['input'] for x in report['cases']],[2,1,0,0,2,1])
        self.assertTrue(all(x['generic_updates']==1 for x in report['cases']))
        self.assertEqual(report['owned_bypasses'],2)
        self.assertTrue(report['inactive_idle'])


if __name__=='__main__':unittest.main()
