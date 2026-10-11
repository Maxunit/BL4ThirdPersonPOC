"""Ground-driven release before contact, composed native handoff, real router."""
import ctypes
from pathlib import Path
import struct
import sys
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import ground_slam_distance_test_scenario as first
from BL4ThirdPersonPOC import ground_slam_camera as exit_runtime
from BL4ThirdPersonPOC import camera_height_capture as height
import unrealsdk
import unrealsdk.unreal as unreal

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_distance_test_v4.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_distance_test_v4'


class DistanceV4Tests(unittest.TestCase):
    arm=first.DistanceTests.arm
    tick=first.DistanceTests.tick
    write=first.DistanceTests.write
    saved=first.DistanceTests.saved

    def setUp(self):
        first.DistanceTests.setUp(self)
        sys.modules.pop(KEY,None)
        self.previous_native_owner=sys.modules.pop(exit_runtime.KEY,None)
        self.ground_z=0.
        self.failed_channels=set()
        self.trace_calls=[]
        names=('WorldContextObject','Start','End','TraceChannel','bTraceComplex',
               'ActorsToIgnore','DrawDebugType','OutHit','bIgnoreSelf','TraceColor',
               'TraceHitColor','DrawTime','ReturnValue')
        params=[S(Name=n,Class=S(Name='OtherProperty')) for n in names]
        params[7].Struct=S(_path_name=lambda:'/Script/Engine.HitResult')
        params[-1].Class.Name='BoolProperty'
        self.trace_fn=S(NumParams=13,_properties=lambda:iter(params),
                       _path_name=lambda:'/Script/Engine.KismetSystemLibrary:LineTraceSingle')
        self.library=S(Class=S(_find=lambda name:self.trace_fn),
                       LineTraceSingle=self.trace,_get_address=lambda:18)
        self.lookup=patch.object(unrealsdk,'find_object',return_value=self.library)
        self.lookup.start()

    def tearDown(self):
        first.DistanceTests.tearDown(self)
        self.lookup.stop()
        sys.modules.pop(KEY,None)
        sys.modules.pop(exit_runtime.KEY,None)
        if self.previous_native_owner is not None:
            sys.modules[exit_runtime.KEY]=self.previous_native_owner

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def trace(self,*args):
        self.trace_calls.append(args)
        self.assertIs(args[0],self.world.pc)
        self.assertEqual(args[5],[self.world.pawn])
        self.assertEqual(args[6],0)  # No debug drawing or persistent trace.
        self.assertIs(args[8],True)
        self.assertEqual(args[-1],0.)
        self.assertEqual(args[1].Z-args[2].Z,20000.)
        hit=S(ImpactPoint=S(X=0.,Y=0.,Z=self.ground_z),
              ImpactNormal=S(X=0.,Y=0.,Z=1.),bBlockingHit=True,bStartPenetrating=False)
        return (args[3] not in self.failed_channels,hit)

    def composed_write(self):
        raw=self.write()
        self.world.camera.CameraModeState.CameraLocationOffset.X-=256.
        return (raw[0]-256.,raw[1],raw[2])

    def calibrate(self):
        capture=self.arm()
        for _ in range(4):
            self.composed_write()
            self.tick()
        self.assertEqual(capture.composition_shift,-256.)
        return capture

    def air(self,clearance=3000.,velocity=-5000.):
        self.world.position.Z=self.ground_z+100.+clearance
        self.world.movement.Velocity.Z=velocity
        self.world.movement.MovementMode=3
        self.world.pawn.slam_active=True

    def activate(self):
        capture=self.calibrate()
        self.air()
        for _ in range(48):
            self.tick()
            self.composed_write()
        self.assertEqual(capture.extra,250.)
        return capture

    def native_exit(self,capture,target=None):
        if target is None:
            v=self.world.camera.CameraModeState.CameraLocationOffset
            target=(v.X,v.Y+.3,v.Z-.4)
        self.target=target
        buffer=ctypes.create_string_buffer(256)
        struct.pack_into('<I',buffer,8,1)
        struct.pack_into('<Q',buffer,40,1234)
        struct.pack_into('<I',buffer,184,1)
        struct.pack_into('<3d',buffer,160,*target)
        self.native=S(active=True,mod=first.phase.mod,owner_invalidated=False,modify=buffer,
            owner_identity=(1,2,3),owner_refs=tuple(unreal.WeakPointer(o) for o in
                (self.world.pc,self.world.pawn,self.world.camera)))
        sys.modules[exit_runtime.KEY]=self.native
        self.world.pawn.slam_active=False
        self.mode='GroundSlamExit'
        self.publish_native()

    def publish_native(self):
        x,y,z=struct.unpack_from('<3d',self.native.modify.raw,160)
        self.world.camera.CameraModeState.CameraLocationOffset=S(X=x,Y=y,Z=z)

    def land(self,capture):
        values=[]
        for clearance in (1800.,1300.,1000.,800.,600.,400.,250.,180.):
            self.air(clearance)
            self.tick()
            values.append(capture.extra)
            self.composed_write()
        self.assertEqual(values[-1],0.)
        self.assertTrue(all(a>=b for a,b in zip(values,values[1:])))
        self.assertTrue(self.world.pawn.slam_active)
        self.assertEqual(self.mode,'ThirdPerson')
        return values

    def test_long_slam_holds_then_releases_before_contact_without_exit_jump(self):
        capture=self.activate()
        count=len(self.trace_calls)
        self.land(capture)
        self.assertEqual(len(self.trace_calls)-count,8)
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,-206.)
        self.native_exit(capture)
        before=self.native.modify.raw
        self.tick()
        self.assertIsNotNone(capture.exit_bridge)
        self.assertEqual(capture.report['exit_bridge']['captured_extra'],0.)
        self.assertEqual(self.native.modify.raw,before)
        self.assertEqual(capture.phase,'exit_settled')
        self.assertEqual(capture.extra,0.)
        self.mode='ThirdPerson'
        self.tick()
        self.assertEqual(self.composed_write()[0],-206.)
        self.execute()
        report=self.saved(capture)
        self.assertFalse(report['errors'])
        self.assertEqual(report['tps_handoff_fallbacks'],0)
        self.assertEqual(report['extra_distance'],250.)

    def test_earlier_composed_snapshot_never_reexpands_released_distance(self):
        capture=self.activate()
        early=self.world.camera.CameraModeState.CameraLocationOffset
        target=(early.X,early.Y+.3,early.Z-.4)
        self.land(capture)
        self.native_exit(capture,target)
        self.tick()
        self.assertEqual(capture.extra,0.)
        self.assertEqual(capture.report['exit_bridge']['captured_extra'],250.)
        self.assertEqual(struct.unpack_from('<d',self.native.modify.raw,160)[0],-206.)
        self.assertEqual(struct.unpack_from('<2d',self.native.modify.raw,168),target[1:])
        self.assertEqual(capture.report['exit_control_writes'],1)
        self.execute()
        self.saved(capture)

    def test_short_slam_limits_zoom_and_neutralizes_before_impact(self):
        capture=self.calibrate()
        values=[]
        for clearance in (700.,600.,500.,400.,300.,180.):
            self.air(clearance)
            self.tick();self.composed_write()
            values.append(capture.extra)
        self.assertLess(max(values),125.)
        self.assertEqual(values[-1],0.)
        self.assertTrue(self.world.pawn.slam_active)

    def test_trace_loss_or_a_lower_ledge_cannot_rezoom_during_release(self):
        capture=self.activate()
        self.air(600.)
        self.tick();self.composed_write()
        before=capture.extra
        self.failed_channels.add(capture.trace_channel)
        self.air(2000.)
        self.tick();self.composed_write()
        self.assertLessEqual(capture.extra,before)
        self.failed_channels.clear()
        self.tick();self.composed_write()
        self.assertLessEqual(capture.extra,before)

    def test_ordinary_jump_uses_no_repeated_traces_or_camera_changes(self):
        capture=self.calibrate()
        self.world.movement.MovementMode=3
        for _ in range(30):
            self.tick()
            self.assertEqual(self.composed_write(),(-206.,66.,-34.))
        self.assertEqual(capture.report['ground_trace_calls'],2)
        self.assertEqual(capture.report['game_writes'],0)
        self.execute();self.saved(capture)

    def test_calibration_selects_only_a_matching_channel(self):
        self.failed_channels.add(0)
        capture=self.arm()
        self.assertEqual(capture.trace_channel,1)
        self.assertEqual(capture.contact_gap,0.)
        self.assertEqual(len(capture.report['ground_calibration']),2)

    def test_bad_calibration_or_signature_declines_before_writing(self):
        for fault in ('channel','height','signature','not_grounded'):
            self.failed_channels.clear();self.ground_z=0.;self.trace_fn.NumParams=13
            self.world.movement.CurrentFloor.bWalkableFloor=True
            if fault=='channel':self.failed_channels.update((0,1))
            elif fault=='height':self.ground_z=-100.
            elif fault=='signature':self.trace_fn.NumParams=12
            else:self.world.movement.CurrentFloor.bWalkableFloor=False
            capture=self.execute();capture.armed_at=0;self.tick()
            report=self.saved(capture)
            self.assertEqual(report['status'],'READ_OR_START_FAILED')
            self.assertEqual(report['game_writes'],0)

    def test_second_slam_starts_a_fresh_entry(self):
        capture=self.activate()
        self.land(capture)
        self.native_exit(capture);self.tick()
        self.mode='ThirdPerson';self.tick();self.composed_write()
        self.air()
        self.tick();self.composed_write()
        self.assertGreater(capture.extra,0.)
        self.assertLess(capture.extra,60.)
        self.assertFalse(capture.ground_releasing)
        for _ in range(48):self.tick();self.composed_write()
        self.assertEqual(capture.extra,250.)

    def test_native_owner_or_unmatched_target_never_receives_our_control_writes(self):
        for fault in ('owner','target','fingerprint'):
            capture=self.activate()
            self.native_exit(capture)
            if fault=='owner':self.native.owner_identity=(1,2,999)
            if fault=='target':struct.pack_into('<d',self.native.modify,160,-444.)
            before=self.native.modify.raw
            if fault=='fingerprint':
                with patch.object(exit_runtime,'OFFSET_PREFIX_SHA256','changed'):self.tick()
            else:self.tick()
            self.assertEqual(self.native.modify.raw,before)
            if height._capture is capture:self.execute()
            self.saved(capture)
            self.mode='ThirdPerson';self.world.pawn.slam_active=False
            self.world.position.Z=100.;self.world.movement.Velocity.Z=0.

    def test_repeated_writes_and_root_height_stay_intact(self):
        capture=self.activate()
        value=self.write()
        for _ in range(5):self.assertEqual(self.write(),value)
        self.assertEqual(value,(-200.,66.,-34.))
        self.assertEqual(first.phase.mod._root_height_state['filtered_z'],-44.)
        self.assertEqual(tuple(getattr(first.phase.mod,'camera_offset_'+a).value for a in 'xyz'),(45.,55.,10.))
        self.execute();self.saved(capture)
        self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,50.)

    def test_ads_fps_and_vehicle_do_not_get_extra(self):
        capture=self.activate()
        for gate in ('ads','fps','vehicle'):
            first.phase.mod._ads_active=gate=='ads'
            first.phase.mod._vehicle_camera_active=gate=='vehicle'
            self.mode='Default' if gate=='fps' else 'ThirdPerson'
            self.assertEqual(self.write(),(50.,66.,-34.))
        self.execute();self.saved(capture)

    def test_f10_and_shutdown_restore_wrapper_and_last_raw_write(self):
        capture=self.activate();self.write()
        self.assertTrue(height.trigger(first.phase.mod));self.saved(capture)
        self.world.position.Z=100.;self.world.pawn.slam_active=False
        capture=self.arm();self.air()
        self.tick();self.write()
        self.assertTrue(height.shutdown(first.phase.mod));self.saved(capture)

    def test_real_production_setter_preserves_root_compensation(self):
        capture=self.activate()
        capture.original_setter=self.saved_setter
        self.original=self.saved_setter
        first.phase.mod.root_height_enabled.value=True
        first.phase.mod._camera_frame=dict(height_refs=tuple(unreal.WeakPointer(o) for o in
            (self.world.pc,self.world.pawn,self.world.camera,self.world.mesh)),height_local=(5.,11.,-44.))
        try:
            self.assertEqual(self.write(),(-200.,66.,-34.))
            self.execute();self.saved(capture)
            self.assertEqual(self.world.camera.CameraModeState.CameraLocationOffset.X,50.)
        finally:first.phase.mod._camera_frame=None

    def test_spatial_curve_is_continuous_and_uses_one_update_lookahead(self):
        ns={}
        exec(compile(PROBE.read_text().rsplit('\ntoggle()',1)[0],str(PROBE),'exec'),ns)
        curve=ns['ground_envelope']
        self.assertEqual(curve(3000.,-5000.,1/60)[0],1.)
        self.assertEqual(curve(180.,-5000.,1/60)[0],0.)
        self.assertAlmostEqual(curve(650.,0.,1/60)[0],.5)
        samples=[curve(float(h),0.,1/60)[0] for h in range(100,1201)]
        self.assertTrue(all(a<=b for a,b in zip(samples,samples[1:])))
        self.assertLess(max(b-a for a,b in zip(samples,samples[1:])),.0014)


if __name__=='__main__':unittest.main()
