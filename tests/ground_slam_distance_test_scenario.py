"""Exercise the mutating distance probe with the real loader/router and SDK stubs."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import ground_slam_phase_probe_scenario as phase
from BL4ThirdPersonPOC import camera_height_capture as height,runtime_updates
import unrealsdk.unreal as unreal

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_distance_test.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_distance_test'


class DistanceTests(unittest.TestCase):
    def setUp(self):
        phase.ProbeTests.setUp(self)
        sys.modules.pop(KEY,None)
        self.saved_setter=phase.mod._set_camera_offset
        self.saved_fallback=phase.mod._looks_like_first_person_fallback
        phase.mod._looks_like_first_person_fallback=lambda:False
        phase.mod._third_person_pushed=True
        phase.mod._ads_active=False
        phase.mod._slide_active=phase.mod._ladder_active=False
        phase.mod._shop_camera_active=False
        phase.mod._camera_lifecycle={}
        phase.mod._mantle_camera_state={}
        phase.mod._root_height_state=dict(filtered_z=-44.,status='tracking')
        for axis,value in zip('xyz',(45.,55.,10.)):
            getattr(phase.mod,'camera_offset_'+axis).value=value
        self.world.pawn.slam_active=False
        self.getter=S(_path_name=lambda:'/Script/OakGame.OakCharacter:IsPerformingGroundSlam',
            FunctionFlags=0x10000000,NumParams=1,_get_address=lambda:17,
            _properties=lambda:iter((S(Class=S(Name='BoolProperty'),PropertyFlags=0x480),)))
        self.world.pawn.Class._find=lambda name:self.getter
        def original(x,y,z):
            # Represent live .35 Root/Motion/shoulder output on every write.
            self.world.camera.CameraModeState.CameraLocationOffset=S(X=x+5.,Y=y+11.,Z=z-44.)
            return True
        self.original=original
        phase.mod._set_camera_offset=original
        self.binding=patch.object(unreal,'BoundFunction',lambda fn,pawn:lambda:pawn.slam_active,create=True)
        self.binding.start()

    def tearDown(self):
        phase.ProbeTests.tearDown(self)
        phase.mod._set_camera_offset=self.saved_setter
        phase.mod._looks_like_first_person_fallback=self.saved_fallback
        self.binding.stop()
        sys.modules.pop(KEY,None)

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def arm(self):
        capture=self.execute()
        capture.armed_at=0
        self.tick()
        self.assertTrue(capture.active)
        return capture

    def tick(self):
        self.now+=16_666_667
        for callback in list(self.producer.routes.values()):
            callback(self.widget,S(InDeltaTime=1/60),None,None)

    def write(self,coords=(45.,55.,10.)):
        phase.mod._set_camera_offset(*coords)
        v=self.world.camera.CameraModeState.CameraLocationOffset
        return (v.X,v.Y,v.Z)

    def saved(self,capture):
        report=json.loads(capture.path.read_text())
        self.assertTrue(report['cleanup_complete'])
        self.assertEqual(report['sdk_hooks'],0)
        self.assertEqual(report['settings_writes'],0)
        self.assertEqual(report['character_writes'],0)
        self.assertEqual(report['animation_writes'],0)
        self.assertFalse(self.producer.routes)
        self.assertIsNone(height._capture)
        self.assertTrue(report['python_setter_wrapper_restored'])
        self.assertIs(phase.mod._set_camera_offset,self.original)
        return report

    def activate(self):
        capture=self.arm()
        self.tick()
        self.world.pawn.slam_active=True
        self.world.movement.MovementMode=3
        for _ in range(30):self.tick()
        self.assertGreater(capture.extra,79.)
        return capture

    def test_normal_jump_unchanged_and_slam_preserves_height_motion_settings(self):
        capture=self.arm()
        self.world.movement.MovementMode=3
        for _ in range(90):
            self.tick()
            self.assertEqual(self.write(),(50.,66.,-34.))
        self.assertEqual(capture.report['game_writes'],0)
        self.world.pawn.slam_active=True
        for _ in range(30):self.tick()
        offset=self.write()
        self.assertAlmostEqual(offset[0],50.-capture.extra)
        self.assertEqual(offset[1:],(66.,-34.))
        self.assertEqual(tuple(getattr(phase.mod,'camera_offset_'+a).value for a in 'xyz'),(45.,55.,10.))
        self.assertEqual(phase.mod._root_height_state['filtered_z'],-44.)
        self.execute()
        self.assertEqual(self.saved(capture)['status'],'MANUAL_STOP')
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,50.)

    def test_repeated_motion_writes_never_accumulate_distance(self):
        capture=self.activate()
        first=self.write((45.,55.,10.))
        for _ in range(5):self.assertEqual(self.write((45.,55.,10.)),first)
        moved=self.write((47.,57.,12.))
        self.assertAlmostEqual(moved[0],52.-capture.extra)
        self.assertEqual(moved[1:],(68.,-32.))
        self.execute()
        self.saved(capture)
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.Z,-32.)

    def test_ground_slam_exit_removes_only_extra_and_keeps_newer_native_owner(self):
        capture=self.activate()
        self.write()
        self.world.pawn.slam_active=False
        self.mode='GroundSlamExit'
        native=S(X=900.,Y=111.,Z=222.)
        self.world.camera.CameraModeState.CameraLocationOffset=native
        self.tick()
        self.assertEqual(capture.extra,0.)
        self.assertIs(self.world.camera.CameraModeState.CameraLocationOffset,native)
        self.assertEqual(self.write(),(50.,66.,-34.))
        self.execute()
        self.saved(capture)

    def test_f10_mid_slam_restores_exact_completed_baseline(self):
        capture=self.activate()
        self.write((48.,59.,16.))
        self.assertTrue(height.trigger(phase.mod))
        self.saved(capture)
        v=self.world.camera.CameraModeState.CameraLocationOffset
        self.assertEqual((v.X,v.Y,v.Z),(53.,70.,-28.))

    def test_ads_fps_menu_or_runtime_changes_cannot_receive_extra(self):
        for gate in ('ads','fps','menu','vehicle','lifecycle'):
            capture=self.activate()
            if gate=='ads':phase.mod._ads_active=True
            elif gate=='fps':self.mode='Default'
            elif gate=='menu':self.world.pc.bShowMouseCursor=True
            elif gate=='vehicle':phase.mod._vehicle_camera_active=True
            else:phase.mod._camera_lifecycle['pending']=True
            self.assertEqual(self.write(),(50.,66.,-34.))
            self.execute()
            self.saved(capture)
            phase.mod._ads_active=False
            phase.mod._vehicle_camera_active=False
            phase.mod._camera_lifecycle={}
            self.mode='ThirdPerson'
            self.world.pc.bShowMouseCursor=False
            self.now=0
        capture=self.activate()
        self.write()
        self.world.objects[1]=S(_get_address=lambda:200)
        self.world.camera.CameraModeState.CameraLocationOffset=S(X=123.,Y=456.,Z=789.)
        self.tick()
        self.saved(capture)
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,123.)

    def test_shutdown_and_limits_restore_wrapper(self):
        capture=self.activate()
        self.write()
        self.assertTrue(height.shutdown(phase.mod))
        self.saved(capture)
        capture=self.arm()
        self.now=180_000_000_000
        self.tick()
        self.assertEqual(self.saved(capture)['status'],'TIME_LIMIT')

    def test_non_game_thread_stop_is_queued_and_restored_on_owned_update(self):
        capture=self.activate()
        self.write()
        with patch.object(runtime_updates,'is_game_thread',return_value=False):
            self.execute()
            self.assertTrue(capture.registered)
        self.tick()
        self.saved(capture)
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,50.)

    def test_reflected_getter_mismatch_declines_before_modification(self):
        self.getter.FunctionFlags=0
        capture=self.execute()
        capture.armed_at=0
        self.tick()
        self.assertEqual(self.saved(capture)['status'],'READ_OR_START_FAILED')
        self.assertEqual(capture.report['game_writes'],0)

    def test_cleanup_detach_failure_keeps_retry_owner(self):
        capture=self.activate()
        self.write()
        with patch.object(runtime_updates,'remove_hook',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'removal unverified'):self.execute()
        self.assertIs(height._capture,capture)
        self.execute()
        self.saved(capture)

    def test_output_failure_detaches_and_preserves_report_for_retry(self):
        capture=self.activate()
        self.write()
        with patch.object(Path,'write_text',side_effect=OSError('disk full')):self.execute()
        self.assertFalse(capture.output_saved)
        self.assertFalse(self.producer.routes)
        self.assertIs(phase.mod._set_camera_offset,self.original)
        self.execute()
        self.saved(capture)

    def test_entry_interpolation_depends_on_elapsed_updates_not_frame_count(self):
        ns={}
        # Load helper without running its PyExec entry point.
        exec(compile(PROBE.read_text().rsplit('\ntoggle()',1)[0],str(PROBE),'exec'),ns)
        values=[]
        for fps in (30,60,120):
            v=0.
            for _ in range(fps//2):v=ns['approach'](v,80.,1/fps,.08)
            values.append(v)
        self.assertLess(max(values)-min(values),1e-8)
        self.assertLessEqual(max(values),80.)

    def test_real_production_setter_root_compensation_is_preserved(self):
        capture=self.activate()
        capture.original_setter=self.saved_setter
        self.original=self.saved_setter
        phase.mod.root_height_enabled.value=True
        phase.mod._camera_frame=dict(height_refs=tuple(unreal.WeakPointer(o) for o in
            (self.world.pc,self.world.pawn,self.world.camera,self.world.mesh)),height_local=(5.,11.,-44.))
        try:
            value=self.write()
            self.assertAlmostEqual(value[0],50.-capture.extra)
            self.assertEqual(value[1:],(66.,-34.))
            self.execute()
            self.saved(capture)
            v=self.world.camera.CameraModeState.CameraLocationOffset
            self.assertEqual((v.X,v.Y,v.Z),(50.,66.,-34.))
        finally:
            phase.mod._camera_frame=None


if __name__=='__main__':unittest.main()
