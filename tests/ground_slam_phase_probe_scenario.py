"""Execute the standalone PyExec probe against the real loader/update router.

SDK objects are stubs. Proves capture/cleanup/serialization, not in-game Slam
signals, montage semantics, timing of rendering or performance.
"""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import loader_harness as harness

mod = harness.load()
from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
from test_camera_height_0_3_9_34 import runtime

PROBE = Path(__file__).resolve().parents[1]/'probes/ground_slam_phase_capture.py'
SOURCE = compile(PROBE.read_text(encoding='utf-8'),str(PROBE),'exec')
KEY = '_bl4tps_ground_slam_phase_capture'


def schema(properties):
    return S(_superfields=lambda:(),_properties=lambda:iter(properties))


def prop(name, kind, nested=None):
    return S(Name=name,Class=S(Name=kind),Struct=nested)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        source,self.world = runtime(self.directory.name)
        for key in ('SETTINGS_DIR','_get_runtime','_third_person_enabled',
                    '_dynamic_motion_enabled','_dynamic_motion_state',
                    'camera_offset_x','camera_offset_y','camera_offset_z'):
            setattr(mod,key,getattr(source,key))
        mod._vehicle_camera_active = False
        mod.MOD_VERSION = '0.3.9.35'
        height._armed = height._capture = height._last = None
        sys.modules.pop(KEY,None)
        self.producer = runtime_updates.Owner(mod)
        self.producer.thread = int(mod._kernel32.GetCurrentThreadId())
        self.widget = S(Class=S(),_get_address=lambda:777,RemoveFromParent=lambda:None)
        self.producer.widget_ref = lambda:self.widget
        self.producer.widget_address = 777
        runtime_updates._owner = self.producer
        self.world.pawn.Class = schema([prop('bIsGroundSlamming','BoolProperty')])
        self.world.pawn.bIsGroundSlamming = False
        self.world.movement.Class = schema([prop('MovementMode','ByteProperty')])
        self.anim = S(_get_address=lambda:7,Class=schema([
            prop('GroundSlamState','StructProperty',schema([
                prop('Active','BoolProperty'),prop('Phase','ByteProperty')]))]),
            GroundSlamState=S(Active=False,Phase=0))
        self.world.mesh.AnimScriptInstance = self.anim
        self.clip = None
        self.montage_position = 0.
        self.anim.GetCurrentActiveMontage = lambda:self.clip
        self.anim.Montage_GetPosition = lambda clip:self.montage_position
        self.mode = 'ThirdPerson'
        self.world.camera.GetActorCameraMode = lambda pawn:self.mode
        self.now = 0
        self.ns = {'__name__':'__main__'}
        self.profiler = patch('BL4ThirdPersonPOC.omni.profiler.status',return_value=dict(state='off'))
        self.profiler.start()

    def tearDown(self):
        if height._capture is not None:
            height.shutdown(mod)
        self.profiler.stop()
        height._armed = height._capture = height._last = None
        runtime_updates._owner = None
        sys.modules.pop(KEY,None)
        self.directory.cleanup()

    def execute(self):
        exec(SOURCE,self.ns)
        capture = sys.modules[KEY].capture
        self.ns['perf_counter_ns'] = lambda:self.now
        return capture

    def arm(self):
        capture = self.execute()
        capture.armed_at = 0
        self.tick()
        self.assertTrue(capture.active)
        self.assertEqual(len(self.producer.routes),1)
        return capture

    def tick(self):
        self.now += 16_666_667
        for callback in list(self.producer.routes.values()):
            callback(self.widget,None,None,None)

    def saved(self,capture):
        report = json.loads(capture.path.read_text(encoding='utf-8'))
        self.assertTrue(report['cleanup_complete'])
        self.assertEqual(report['sdk_hooks'],0)
        self.assertEqual(report['game_writes'],0)
        self.assertFalse(self.producer.routes)
        self.assertIsNone(height._capture)
        return report

    def test_long_slam_independent_character_and_camera_end_manual_stop(self):
        capture = self.arm()
        for _ in range(120): self.tick()
        self.world.movement.MovementMode = 3
        self.world.movement.Velocity.Z = -1400
        self.world.movement.CurrentFloor.bWalkableFloor = False
        self.world.pawn.bIsGroundSlamming = True
        self.anim.GroundSlamState.Active = True
        self.anim.GroundSlamState.Phase = 1
        self.mode = 'GroundSlam'
        self.clip = S(_path_name=lambda:'/Game/Test/GroundSlam_Montage')
        for _ in range(1500): self.tick()
        self.assertGreater(capture.frames,600)
        self.assertTrue(capture.active)
        self.mode = 'GroundSlamExit'
        self.world.movement.MovementMode = 1
        self.world.movement.Velocity.Z = 0
        self.world.movement.CurrentFloor.bWalkableFloor = True
        self.anim.GroundSlamState.Phase = 2
        for _ in range(30): self.tick()
        self.mode = 'ThirdPerson'
        for _ in range(30): self.tick()
        self.world.pawn.bIsGroundSlamming = False
        self.anim.GroundSlamState.Active = False
        self.anim.GroundSlamState.Phase = 0
        self.clip = None
        for _ in range(120): self.tick()
        self.assertIs(self.execute(),capture)
        report = self.saved(capture)
        self.assertEqual(report['status'],'MANUAL_STOP')
        segments = report['phase_summary']['camera_segments']
        self.assertEqual([s['mode'] for s in segments],
                         ['ThirdPerson','GroundSlam','GroundSlamExit','ThirdPerson'])
        self.assertGreater(segments[1]['observed_span_ms'],24000)
        self.assertTrue(any(r['camera_mode']=='ThirdPerson' and
            r['candidates']['pawn.bIsGroundSlamming'] for r in report['samples']))
        details = [r for r in report['samples'] if 'camera_cache' in r]
        self.assertLess(len(details),len(report['samples'])//2)
        self.assertTrue(any(e['state']['montage_path'] for e in report['events']))

    def test_f10_stop_and_installed_shutdown_detach(self):
        capture = self.arm()
        self.tick()
        self.assertTrue(height.trigger(mod))
        self.assertEqual(self.saved(capture)['status'],'MANUAL_STOP')
        next_capture = self.arm()
        self.assertIsNot(next_capture,capture)
        self.tick()
        self.assertTrue(height.shutdown(mod))
        self.assertEqual(self.saved(next_capture)['status'],'CANCELLED')
        self.assertTrue(runtime_updates.shutdown())

    def test_armed_cancel_does_not_read_slam_or_leak_route(self):
        self.world.pc.bShowMouseCursor = True
        capture = self.execute()
        capture.armed_at = 0
        self.tick()
        self.assertTrue(capture.waiting)
        self.assertFalse(capture.active)
        self.execute()
        self.assertEqual(self.saved(capture)['completed_updates'],0)

    def test_safety_limits_are_live_until_manual_stop(self):
        for reason in ('TIME_LIMIT','UPDATE_LIMIT'):
            capture = self.arm()
            if reason == 'TIME_LIMIT':
                self.now = 180_000_000_000
            else:
                capture.frames = 15999
            self.tick()
            self.assertEqual(self.saved(capture)['status'],reason)
            self.now = 0

    def test_owner_change_rejects_partial_row_and_detaches(self):
        capture = self.arm()
        self.tick()
        self.world.objects[1] = S(_get_address=lambda:200)
        self.tick()
        report = self.saved(capture)
        self.assertEqual(report['status'],'READ_OR_START_FAILED')
        self.assertEqual(report['completed_updates'],1)

    def test_optional_missing_montage_disabled_and_capture_continues(self):
        del self.anim.GetCurrentActiveMontage
        capture = self.arm()
        for _ in range(5):self.tick()
        self.assertTrue(capture.active)
        self.execute()
        report = self.saved(capture)
        self.assertEqual(report['optional_errors']['current_montage']['count'],1)
        self.assertEqual(report['completed_updates'],5)

    def test_foreign_widget_does_not_sample(self):
        capture = self.arm()
        for callback in list(self.producer.routes.values()):
            callback(S(_get_address=lambda:999),None,None,None)
        self.assertEqual(capture.frames,0)

    def test_output_failure_detaches_and_pyexec_retries_same_report(self):
        capture = self.arm()
        self.tick()
        with patch.object(Path,'write_text',side_effect=OSError('simulated disk error')):
            self.execute()
        self.assertFalse(capture.output_saved)
        self.assertFalse(self.producer.routes)
        self.assertIsNone(height._capture)
        self.assertIs(self.execute(),capture)
        self.assertTrue(capture.output_saved)
        self.assertEqual(self.saved(capture)['completed_updates'],1)

    def test_detach_failure_keeps_owner_for_manual_retry(self):
        capture = self.arm()
        self.tick()
        with patch.object(runtime_updates,'remove_hook',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'removal unverified'):
                self.execute()
        self.assertTrue(capture.registered)
        self.assertIs(height._capture,capture)
        self.assertIs(self.execute(),capture)
        self.assertTrue(capture.output_saved)
        self.saved(capture)

    def test_nonfinite_core_value_drops_partial_row_and_saves_error(self):
        capture = self.arm()
        self.tick()
        self.world.movement.Velocity.Z = float('nan')
        self.tick()
        report = self.saved(capture)
        self.assertEqual(report['completed_updates'],1)
        self.assertTrue(report['errors'])


if __name__ == '__main__':
    unittest.main()
