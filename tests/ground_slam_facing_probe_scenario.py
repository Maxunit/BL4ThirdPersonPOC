"""Read-only facing capture through real loader/router and F10 cleanup."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import ground_slam_phase_probe_scenario as phase
from BL4ThirdPersonPOC import camera_height_capture as height,runtime_updates
from BL4ThirdPersonPOC.omni.common import KEY as OMNI_KEY
import unrealsdk.unreal as unreal

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_facing_capture.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_facing_capture'


class FacingTests(unittest.TestCase):
    tick=phase.ProbeTests.tick
    saved=phase.ProbeTests.saved
    def setUp(self):
        phase.ProbeTests.setUp(self)
        phase.mod.MOD_VERSION='0.3.9.38'
        sys.modules.pop(KEY,None)
        self.previous_omni=getattr(phase.mod,OMNI_KEY,None)
        self.world.pawn.slam=False
        self.actor=S(Pitch=0.,Yaw=180.,Roll=0.)
        self.root_yaw=180.;self.root_pitch=0.
        self.world.pawn.K2_GetActorRotation=lambda:self.actor
        self.world.camera.GetCameraRotation=lambda:S(Pitch=0.,Yaw=0.,Roll=0.)
        self.world.pc.GetControlRotation=lambda:S(Pitch=0.,Yaw=0.,Roll=0.)
        self.world.mesh.K2_GetComponentRotation=lambda:self.actor
        self.world.mesh.GetSocketRotation=lambda name:S(Pitch=self.root_pitch,Yaw=self.root_yaw,Roll=0.)
        self.anim.AimYaw=-180.;self.anim.AimPitch=25.
        fn=S(_get_address=lambda:20,_path_name=lambda:'/Script/OakGame.OakCharacter:IsPerformingGroundSlam',
             FunctionFlags=0x10000000,NumParams=1,_properties=lambda:iter((
             S(Class=S(Name='BoolProperty'),PropertyFlags=0x400),)))
        self.world.pawn.Class._find=lambda name:fn
        self.binding=patch.object(unreal,'BoundFunction',lambda fn,pawn:lambda:pawn.slam,create=True)
        self.binding.start()
        objects=(self.world.pc,self.world.pawn,self.world.camera,self.world.movement)
        self.child=S(active=True,refs=tuple(lambda o=o:o for o in objects),ground_slam_pose_native=True,
            native=S(control=[0]*10),idle_native=S(control=[0]*9),idle_update=S(control=[0]*9),
            aim_native=S(control=[0]*6,crouch_control=[0]*6),report={})
        setattr(phase.mod,OMNI_KEY,S(child=self.child))

    def tearDown(self):
        phase.ProbeTests.tearDown(self)
        self.binding.stop();sys.modules.pop(KEY,None)
        if self.previous_omni is None:delattr(phase.mod,OMNI_KEY)
        else:setattr(phase.mod,OMNI_KEY,self.previous_omni)

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def arm(self):
        capture=self.execute();capture.armed_at=0;self.tick()
        self.assertTrue(capture.active)
        return capture

    def test_actor_and_bone_turns_are_separately_logged_without_writes(self):
        capture=self.arm();self.tick()
        self.world.pawn.slam=True;self.world.movement.MovementMode=3
        self.actor.Yaw=0.;self.root_yaw=90.
        for _ in range(4):self.tick()
        row=next(r for r in reversed(capture.report['samples']) if 'bone_rotations' in r)
        self.assertEqual(row['actor_rotation']['Yaw'],0.)
        self.assertEqual(row['bone_rotations']['Root']['world_rotation']['Yaw'],90.)
        self.assertEqual(row['bone_rotations']['Root']['yaw_minus_actor'],90.)
        self.assertTrue(row['slam_active'])
        self.assertEqual(set(row['omni']['gates'].values()),{0})
        self.mode='GroundSlamExit';self.world.pawn.slam=False;self.tick()
        self.execute();report=self.saved(capture)
        self.assertFalse(report['errors'])
        self.assertEqual(report['native_reads'],0)
        self.assertEqual(report['native_patches_added'],0)
        self.assertEqual(report['events'][-1]['mode'],'GroundSlamExit')

    def test_model_can_rotate_while_actor_yaw_stays_fixed_and_vertical_yaw_is_marked(self):
        capture=self.arm();self.root_yaw=0.;self.root_pitch=90.
        self.tick();row=capture.report['samples'][-1]
        self.assertEqual(row['actor_rotation']['Yaw'],180.)
        self.assertEqual(row['bone_rotations']['Root']['world_rotation']['Yaw'],0.)
        self.assertFalse(row['bone_rotations']['Root']['yaw_well_projected'])

    def test_f10_stops_and_removes_owned_subscription(self):
        capture=self.arm();self.tick()
        self.assertTrue(height.trigger(phase.mod))
        self.assertEqual(self.saved(capture)['status'],'MANUAL_STOP')

    def test_animation_replacement_cancels_instead_of_reading_foreign_pose(self):
        capture=self.arm();self.world.mesh.AnimScriptInstance=S(_get_address=lambda:999)
        self.tick()
        report=self.saved(capture)
        self.assertEqual(report['status'],'READ_OR_START_FAILED')
        self.assertEqual(report['completed_updates'],0)

    def test_non_game_thread_and_open_console_do_not_start_reading(self):
        capture=self.execute();capture.armed_at=0
        with patch.object(runtime_updates,'is_game_thread',return_value=False):self.tick()
        self.assertTrue(capture.waiting)
        self.world.pc.bShowMouseCursor=True;self.tick();self.assertTrue(capture.waiting)
        self.world.pc.bShowMouseCursor=False;self.tick();self.assertTrue(capture.active)

    def test_output_failure_can_be_retried_after_safe_detach(self):
        capture=self.arm();self.tick()
        with patch.object(Path,'write_text',side_effect=OSError('full')):self.execute()
        self.assertFalse(capture.output_saved);self.assertFalse(self.producer.routes)
        self.execute();self.saved(capture)


if __name__=='__main__':unittest.main()
