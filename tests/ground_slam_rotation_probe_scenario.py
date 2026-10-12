"""Native-buffer capture guards through the real loader/router; SDK/native stubs."""
import ctypes
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import ground_slam_facing_probe_scenario as facing
from BL4ThirdPersonPOC.omni.native_rotation import NativeTrace, CAPACITY, RECORD_SIZE
from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates

PROBE=Path(__file__).resolve().parents[1]/'probes/ground_slam_rotation_capture.py'
SOURCE=compile(PROBE.read_text(), str(PROBE), 'exec')
KEY='_bl4tps_ground_slam_rotation_capture'

class RotationTests(unittest.TestCase):
    saved=facing.FacingTests.saved
    def setUp(self):
        facing.FacingTests.setUp(self)
        sys.modules.pop(KEY,None)
        child=self.child
        child.mod=facing.phase.mod;child.frames=0;child.slam_trace_window=False
        native=NativeTrace(child);child.native=native
        native.base=0x100000;native.component=0x9999
        native.hook={'target':0x123456,'patch':b'owned','restored':False}
        native.control[1]=self.world.movement._get_address()
        native.control[2]=333;native.control[3]=native.component
        for i in (1,2,3):native.slide_control[i]=native.control[i]
        native.slide_control[4]=ctypes.addressof(native.slide_buffer)
        native.validate=lambda:None
        def read(address,size):
            child.report['native_reads']=child.report.get('native_reads',0)+1
            return native.hook['patch']
        native.read=read
        self.native=native

    def tearDown(self):
        facing.FacingTests.tearDown(self)
        sys.modules.pop(KEY,None)

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def tick(self):
        # Production closes the recorder first, and owns Exit's diagnostic gate.
        self.child.frames+=1
        self.child.slam_trace_window=self.mode=='GroundSlamExit'
        self.native.slide_control[0]=int(self.child.slam_trace_window)
        facing.phase.ProbeTests.tick(self)

    def arm(self):
        c=self.execute();c.armed_at=0;self.tick()
        self.assertTrue(c.active)
        self.assertEqual(self.native.slide_control[0],1)
        return c

    def record(self,caller=0x2e2e17,yaw=90.,component=None):
        i=int(self.native.slide_control[5]);raw=bytearray(RECORD_SIZE)
        struct.pack_into('<4Q',raw,0,1,self.native.base+caller,
                         self.native.component if component is None else component,1)
        struct.pack_into('<4d',raw,32,0.,0.,math.sin(math.radians(yaw)/2),math.cos(math.radians(yaw)/2))
        struct.pack_into('<4d',raw,64,0.,0.,0.,1.)
        struct.pack_into('<3dQ',raw,96,0.,0.,-10.,self.child.frames)
        start=i*RECORD_SIZE
        self.native.slide_buffer[start:start+RECORD_SIZE]=raw
        self.native.slide_control[5]=i+1

    def test_start_and_airborne_requests_are_copied_without_behavioral_writes(self):
        c=self.arm();self.record(caller=0x2eec48)
        self.world.pawn.slam=True;self.world.movement.MovementMode=3
        self.record();self.tick();self.execute();r=self.saved(c)
        self.assertEqual([x['caller_return_rva'] for x in r['rotation_requests']],['0x2eec48','0x2e2e17'])
        self.assertAlmostEqual(r['rotation_requests'][1]['requested_minus_root'],90.)
        self.assertTrue(r['samples'][0]['slam_active'])
        self.assertEqual(r['game_writes'],0);self.assertEqual(r['native_patches_added'],0)
        self.assertGreater(r['native_reads'],0)
        self.assertEqual(set(self.native.control[i] for i in (0,7)),{0})
        self.assertEqual(self.native.slide_control[0],0)
        self.assertFalse(r['errors'])

    def test_f10_detaches_and_closes_owned_gate(self):
        c=self.arm();self.record();height.trigger(facing.phase.mod)
        self.assertFalse(self.producer.routes)
        self.assertEqual(self.native.slide_control[0],0)
        self.assertEqual(self.saved(c)['rotation_request_count'],1)

    def test_production_exit_recording_is_preserved(self):
        c=self.arm();self.mode='GroundSlamExit';self.world.pawn.slam=False
        self.tick();self.execute();self.saved(c)
        self.assertEqual(self.native.slide_control[0],1)
        self.assertFalse(c.record_gate_owned)

    def test_foreign_component_record_cancels_and_closes_gate(self):
        c=self.arm();self.record(component=0x4444);self.tick()
        self.assertEqual(self.saved(c)['status'],'READ_OR_START_FAILED')
        self.assertEqual(self.native.slide_control[0],0)
        self.assertFalse(self.producer.routes)

    def test_owner_replacement_does_not_modify_new_recorder(self):
        c=self.arm();old=self.native
        replacement=NativeTrace(self.child);replacement.slide_control[0]=1
        self.child.native=replacement;self.tick()
        self.assertEqual(self.saved(c)['status'],'READ_OR_START_FAILED')
        self.assertEqual(old.slide_control[0],0)
        self.assertEqual(replacement.slide_control[0],1)

    def test_changed_native_patch_is_rejected_before_arming(self):
        self.native.read=lambda address,size:b'other'
        c=self.execute();c.armed_at=0;self.tick()
        self.assertEqual(self.saved(c)['status'],'READ_OR_START_FAILED')
        self.assertEqual(self.native.slide_control[0],0)

    def test_capacity_stops_without_resetting_shared_buffer(self):
        c=self.arm()
        for _ in range(CAPACITY):self.record()
        self.tick();r=self.saved(c)
        self.assertEqual(r['status'],'RECORD_CAPACITY')
        self.assertEqual(len(r['rotation_requests']),CAPACITY)
        self.assertEqual(self.native.slide_control[5],CAPACITY)
        self.assertEqual(self.native.slide_control[0],0)

    def test_cleanup_requires_game_thread_and_can_be_retried(self):
        c=self.arm()
        with patch.object(runtime_updates,'is_game_thread',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'game thread'):self.execute()
        self.assertTrue(c.active);self.assertTrue(self.producer.routes)
        self.execute();self.saved(c)
        self.assertEqual(self.native.slide_control[0],0)

    def test_invalid_recorded_quaternion_is_rejected(self):
        c=self.arm();self.record()
        self.native.slide_buffer[32:64]=bytes(32)
        self.tick();r=self.saved(c)
        self.assertEqual(r['status'],'READ_OR_START_FAILED')
        self.assertEqual(r['rotation_requests'],[])
        self.assertEqual(self.native.slide_control[0],0)

    def test_buffer_pointer_mismatch_is_rejected_without_dereferencing(self):
        self.native.slide_control[4]=0xDEAD
        c=self.execute();c.armed_at=0;self.tick()
        self.assertEqual(self.saved(c)['status'],'READ_OR_START_FAILED')
        self.assertEqual(self.native.slide_control[0],0)

    def test_output_retry_keeps_recorder_closed_and_hook_detached(self):
        c=self.arm();self.record()
        with patch.object(Path,'write_text',side_effect=OSError('full')):self.execute()
        self.assertFalse(c.output_saved);self.assertFalse(self.producer.routes)
        self.assertEqual(self.native.slide_control[0],0)
        self.execute();self.saved(c)

if __name__=='__main__':unittest.main()
