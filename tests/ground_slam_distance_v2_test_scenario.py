"""Reproduce a captured Exit offset whose Y/Z changed after the last TPS write."""
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
import unrealsdk.unreal as unreal

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_distance_test_v2.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_distance_test_v2'


class DistanceV2Tests(first.DistanceTests):
    def setUp(self):
        super().setUp()
        sys.modules.pop(KEY,None)
        self.previous_native_owner=sys.modules.pop(exit_runtime.KEY,None)

    def tearDown(self):
        super().tearDown()
        sys.modules.pop(KEY,None)
        sys.modules.pop(exit_runtime.KEY,None)
        if self.previous_native_owner is not None:
            sys.modules[exit_runtime.KEY]=self.previous_native_owner

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def native_exit(self,capture):
        self.write()
        buffer=ctypes.create_string_buffer(256)
        struct.pack_into('<I',buffer,8,1)
        struct.pack_into('<Q',buffer,40,1234)
        struct.pack_into('<I',buffer,184,1)
        want=capture.last_write['wanted']
        # Native .35 freezes the TPS X; Y/Z differ from our last direct write,
        # exactly the situation that defeated the v1 all-axis restore guard.
        self.target=(want['X'],want['Y']+0.3,want['Z']-0.4)
        struct.pack_into('<3d',buffer,160,*self.target)
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

    def test_ground_slam_exit_removes_only_extra_and_keeps_newer_native_owner(self):
        capture=self.activate()
        self.native_exit(capture)
        self.tick()
        first_x=struct.unpack_from('<d',self.native.modify.raw,160)[0]
        self.assertGreater(first_x,self.target[0])
        self.assertLess(first_x,50.)
        self.assertEqual(struct.unpack_from('<2d',self.native.modify.raw,168),self.target[1:])
        for _ in range(70):
            self.publish_native()
            self.tick()
        self.publish_native()
        self.assertEqual(capture.extra,0.)
        self.assertEqual(struct.unpack_from('<d',self.native.modify.raw,160)[0],50.)
        self.assertEqual(struct.unpack_from('<2d',self.native.modify.raw,168),self.target[1:])
        self.mode='ThirdPerson'
        self.tick()
        self.assertIsNone(capture.exit_bridge)
        self.assertEqual(self.write()[0],50.)
        self.execute()
        report=self.saved(capture)
        self.assertGreater(report['exit_control_writes'],0)
        self.assertTrue(report['exit_control_restored'])

    def test_stop_during_exit_restores_control_x_and_preserves_live_yz(self):
        capture=self.activate()
        self.native_exit(capture)
        for _ in range(4):
            self.tick()
            self.publish_native()
        self.execute()
        self.saved(capture)
        self.assertEqual(struct.unpack_from('<d',self.native.modify.raw,160)[0],50.)
        v=self.world.camera.CameraModeState.CameraLocationOffset
        self.assertEqual((v.X,v.Y,v.Z),(50.,*self.target[1:]))

    def test_foreign_or_retired_native_owner_never_gets_control_write(self):
        capture=self.activate()
        self.native_exit(capture)
        self.native.owner_identity=(1,2,999)
        before=self.native.modify.raw
        self.tick()
        self.assertEqual(self.native.modify.raw,before)
        if height._capture is capture:self.execute()
        self.saved(capture)

    def test_consumer_fingerprint_mismatch_fails_before_control_write(self):
        capture=self.activate()
        self.native_exit(capture)
        before=self.native.modify.raw
        with patch.object(exit_runtime,'OFFSET_PREFIX_SHA256','different'):
            self.tick()
        report=self.saved(capture)
        self.assertEqual(report['exit_control_writes'],0)
        self.assertEqual(self.native.modify.raw,before)

    def test_target_without_a_proven_camera_contribution_is_rejected(self):
        capture=self.activate()
        self.native_exit(capture)
        struct.pack_into('<d',self.native.modify,160,-444.)
        before=self.native.modify.raw
        self.tick()
        self.saved(capture)
        self.assertEqual(self.native.modify.raw,before)

    def test_cleanup_preserves_a_retired_owner(self):
        capture=self.activate()
        self.native_exit(capture)
        self.tick()
        self.native.active=False
        before=self.native.modify.raw
        self.execute()
        self.saved(capture)
        self.assertEqual(self.native.modify.raw,before)


if __name__=='__main__':unittest.main()
