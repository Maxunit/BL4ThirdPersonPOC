"""V3 preserves the strict native guard and bridges an unmatched target in TPS."""
from pathlib import Path
import struct
import sys
import unittest
import ground_slam_distance_v2_test_scenario as previous
from BL4ThirdPersonPOC import camera_height_capture as height

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_distance_test_v3.py'
SOURCE=compile(PROBE.read_text(),str(PROBE),'exec')
KEY='_bl4tps_ground_slam_distance_test_v3'


class DistanceV3Tests(previous.DistanceV2Tests):
    def setUp(self):
        super().setUp()
        sys.modules.pop(KEY,None)

    def tearDown(self):
        super().tearDown()
        sys.modules.pop(KEY,None)

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def test_target_without_a_proven_camera_contribution_is_rejected(self):
        capture=self.activate()
        self.native_exit(capture)
        struct.pack_into('<d',self.native.modify,160,-444.)
        before=self.native.modify.raw
        self.tick()
        self.assertTrue(capture.active)
        self.assertTrue(capture.exit_declined)
        self.assertEqual(self.native.modify.raw,before)
        self.assertEqual(capture.report['exit_diagnostics'][0]['native_target'][0],-444.)
        self.assertEqual(capture.report['exit_control_writes'],0)
        self.execute()
        self.saved(capture)

    def unmatched_exit(self,capture):
        self.native_exit(capture)
        struct.pack_into('<d',self.native.modify,160,-444.)
        for _ in range(10):self.tick()
        self.assertTrue(capture.handoff_pending)
        # Represent the stale direct SDK offset from the uploaded V1 report.
        self.world.camera.CameraModeState.CameraLocationOffset.X=50.-capture.extra

    def test_tps_fallback_preserves_first_offset_then_smoothly_releases_during_transition(self):
        capture=self.activate()
        self.unmatched_exit(capture)
        inherited=50.-capture.extra
        self.mode='ThirdPerson'
        self.world.camera.CameraModeState.bIsTransitioning=True
        self.tick()
        first=self.write()[0]
        self.assertEqual(first,inherited)
        values=[first]
        for _ in range(70):
            self.tick()
            values.append(self.write()[0])
        self.assertEqual(values[-1],50.)
        self.assertTrue(all(a<=b for a,b in zip(values,values[1:])))
        self.assertLess(max(b-a for a,b in zip(values,values[1:])),15.)
        self.assertFalse(capture.handoff_pending)
        self.assertEqual(capture.report['exit_control_writes'],0)
        self.execute()
        report=self.saved(capture)
        self.assertFalse(report['errors'])
        self.assertEqual(report['tps_handoff_fallbacks'],1)

    def test_fallback_never_applies_distance_to_ads_or_fps(self):
        capture=self.activate()
        self.unmatched_exit(capture)
        self.mode='ThirdPerson'
        previous.first.phase.mod._ads_active=True
        self.tick()
        self.assertEqual(self.write()[0],50.)
        self.assertFalse(capture.handoff_pending)
        self.mode='Default'
        self.assertEqual(self.write()[0],50.)

    def test_early_native_capture_can_match_beyond_old_64_write_window(self):
        capture=self.arm()
        self.tick()
        self.world.pawn.slam_active=True
        recorded=[]
        for _ in range(80):
            self.tick()
            recorded.append(self.write()[0])
            self.write()
        self.assertGreater(len(capture.offset_history),64)
        self.native_exit(capture)
        struct.pack_into('<d',self.native.modify,160,recorded[0])
        self.tick()
        self.assertIsNotNone(capture.exit_bridge)
        self.assertFalse(capture.exit_declined)
        self.assertTrue(capture.report['exit_diagnostics'][0]['matched'])
        self.execute()
        self.saved(capture)


if __name__=='__main__':unittest.main()
