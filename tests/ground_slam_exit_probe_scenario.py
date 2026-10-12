""".39 Exit capture: repeated skeletal samples, native requests and untouched gates."""
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
import unittest
import ground_slam_rotation_probe_scenario as rotation

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_exit_capture.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_exit_capture'


class ExitTests(rotation.RotationTests):
    def setUp(self):
        self.source_patch=patch.multiple(rotation,SOURCE=SOURCE,KEY=KEY)
        self.source_patch.start()
        super().setUp()
        rotation.facing.phase.mod.MOD_VERSION='0.3.9.39'
        self.native.control[0]=self.native.control[7]=1
        self.native.control[8]=self.native.base+0x2e2e17
        self.child.report['ground_slam_heading_hold']=dict(enabled=True,update=1)
        self.child.ground_slam_pose_native=False
        self.anim.AimEnableAlpha=1.
        self.world.movement.CurrentRotateToState=S(CommandData=S(
            Duration=.2,InterpSpeed=1.,MaxYawRate=180.,MaxPitchRate=0.,
            TargetLocation=S(X=0.,Y=0.,Z=0.),TargetActor=None,TargetSocket='None',
            bFreezeRotation=False,bUseEasing=True,bUpdateCamera=False))

    def tearDown(self):
        try:super().tearDown()
        finally:self.source_patch.stop()

    def test_start_and_airborne_requests_are_copied_without_behavioral_writes(self):
        capture=self.arm()
        self.world.pawn.slam=True;self.child.ground_slam_pose_native=True
        self.record(caller=0x2eec48);self.record();self.tick()
        self.execute();r=self.saved(capture)
        self.assertEqual([x['caller_return_rva'] for x in r['rotation_requests']],['0x2eec48','0x2e2e17'])
        self.assertEqual([self.native.control[i] for i in (0,7)],[1,1])
        self.assertEqual(r['samples'][0]['omni']['turn_caller_return_rva'],'0x2e2e17')
        self.assertEqual(r['game_writes'],0);self.assertEqual(r['native_patches_added'],0)
        self.assertFalse(r['errors']);self.assertFalse(r['optional_errors'])

    def test_exit_samples_animated_root_changes_every_update_with_fixed_actor(self):
        c=self.arm();self.mode='GroundSlamExit';self.child.ground_slam_pose_native=True
        for yaw in (0.,90.,-90.,180.):
            self.root_yaw=yaw;self.native.control[9]+=1;self.tick()
        rows=c.report['samples']
        self.assertEqual([r['bone_rotations']['Root']['world_rotation']['Yaw'] for r in rows],[0.,90.,-90.,180.])
        self.assertEqual([r['actor_rotation']['Yaw'] for r in rows],[180.]*4)
        self.assertEqual([r['turn_replacements_since_previous'] for r in rows[1:]],[1]*3)
        self.assertTrue(all(r['omni']['heading_hold']['enabled'] for r in rows))
        self.assertTrue(all(not r['pose_controls_enabled'] for r in rows))
        self.execute();self.assertFalse(self.saved(c)['optional_errors'])

    def test_own_tps_return_keeps_dense_detail_then_ordinary_tps_is_throttled(self):
        c=self.arm();self.mode='ThirdPerson';self.child.ground_slam_pose_native=True
        for _ in range(3):self.tick()
        self.assertTrue(all('bone_rotations' in r for r in c.report['samples']))
        self.child.ground_slam_pose_native=False
        self.tick();self.assertNotIn('bone_rotations',c.report['samples'][-1])
        self.execute();self.saved(c)

    def test_unexpected_pose_control_is_logged_instead_of_changing_or_hiding_it(self):
        c=self.arm();self.child.aim_native.control[0]=1
        self.world.pawn.slam=True;self.child.ground_slam_pose_native=True
        self.tick()
        self.assertTrue(c.report['samples'][-1]['pose_controls_enabled'])
        self.assertEqual(self.child.aim_native.control[0],1)
        self.assertTrue(c.active)
        self.execute();self.saved(c)

    def test_40_expected_root_only_guard_is_distinguished_from_pose_suppression(self):
        rotation.facing.phase.mod.MOD_VERSION='0.3.9.40'
        c=self.arm();self.mode='GroundSlamExit';self.child.ground_slam_pose_native=True
        self.child.idle_native.control[0]=1
        self.child.report['ground_slam_heading_hold']['root_correction_skipped']=True
        self.tick();row=c.report['samples'][-1]
        self.assertTrue(row['pose_controls_enabled'])
        self.assertFalse(row['unexpected_slam_pose_controls'])
        self.assertEqual(self.child.idle_native.control[0],1)
        self.execute();self.saved(c)

    def test_41_expected_idle_fallback_is_reported_without_being_modified(self):
        rotation.facing.phase.mod.MOD_VERSION='0.3.9.41'
        c=self.arm();self.mode='GroundSlamExit';self.child.ground_slam_pose_native=True
        self.child.idle_native.control[0]=self.child.idle_update.control[0]=1
        self.child.report['ground_slam_heading_hold'].update(root_correction_skipped=True,idle_fallback_selected=True)
        self.tick();row=c.report['samples'][-1]
        self.assertFalse(row['unexpected_slam_pose_controls'])
        self.assertEqual(self.child.idle_update.control[0],1)
        self.execute();self.saved(c)

    def test_optional_sdk_command_failure_preserves_core_exit_data(self):
        c=self.arm();del self.world.movement.CurrentRotateToState
        self.mode='GroundSlamExit';self.tick();self.execute();r=self.saved(c)
        self.assertFalse(r['errors'])
        self.assertIn('rotate_command',r['optional_errors'])
        self.assertIn('bone_rotations',r['samples'][0])


if __name__=='__main__':unittest.main()
