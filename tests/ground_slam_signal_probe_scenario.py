"""Signal discovery and observer cleanup with real loader/router, SDK stubs."""
from pathlib import Path
import sys
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import ground_slam_phase_probe_scenario as phase
from BL4ThirdPersonPOC import camera_height_capture as height
import unrealsdk.unreal as unreal

PROBE = Path(__file__).resolve().parents[1]/'probes/ground_slam_signal_capture.py'
SOURCE = compile(PROBE.read_text(encoding='utf-8'),str(PROBE),'exec')
KEY = '_bl4tps_ground_slam_signal_capture'


def function(name,flags=0,params=()):
    return S(Name=name,Class=S(Name='Function'),_get_address=lambda:id(name),
        _path_name=lambda:'/Script/Test.Movement.'+name,FunctionFlags=flags,
        NumParams=len(params),_properties=lambda:iter(params))


class SignalProbeTests(phase.ProbeTests):
    def setUp(self):
        super().setUp()
        sys.modules.pop(KEY,None)
        self.getter = function('IsGroundSlamming',0x10000000,(
            S(Name='ReturnValue',Class=S(Name='BoolProperty'),PropertyFlags=0x480),))
        self.start_fn = function('StartGroundSlam')
        self.stop_fn = function('StopGroundSlam')
        self.listener_fn = function('HandleGroundSlamStarted')
        self.start_sig = function('OnStartGroundSlam__DelegateSignature')
        self.stop_sig = function('OnStopGroundSlam__DelegateSignature')
        self.world.movement.slam_active = False
        self.listener = S(_path_name=lambda:'/Game/Transient.SlamListener')
        self.started_delegate = [S(object=self.listener,func=self.listener_fn)]

        class Delegate:
            def __init__(inner,signature,bindings):
                inner._signature,inner.bindings=signature,bindings
            def __iter__(inner): return iter(inner.bindings)
            def __call__(inner,*args): raise AssertionError('Delegate invocation forbidden')
            def add(inner,*args): raise AssertionError('Delegate mutation forbidden')
            def remove(inner,*args): raise AssertionError('Delegate mutation forbidden')

        self.world.movement.OnStartGroundSlam = Delegate(self.start_sig,self.started_delegate)
        self.world.movement.OnStopGroundSlam = Delegate(self.stop_sig,[])
        self.world.movement.Class = phase.schema([
            phase.prop('MovementMode','ByteProperty'),
            phase.prop('OnStartGroundSlam','MulticastInlineDelegateProperty'),
            phase.prop('OnStopGroundSlam','MulticastInlineDelegateProperty')])
        self.world.movement.Class._fields = lambda:iter((self.getter,self.start_fn,self.stop_fn))
        self.world.pc.Class = phase.schema([])
        for obj in (self.world.pawn,self.world.pc,self.anim):
            obj.Class._fields = lambda:iter(())
        self.world.movement._path_name=lambda:'/Game/Transient.PlayerMovement'
        self.getter_calls=0
        def bind(fn,obj):
            self.assertIs(fn,self.getter)
            self.assertIs(obj,self.world.movement)
            def call():
                self.getter_calls += 1
                return obj.slam_active
            return call
        self.binding=patch.object(unreal,'BoundFunction',bind,create=True)
        self.binding.start()

    def tearDown(self):
        super().tearDown()
        self.binding.stop()
        sys.modules.pop(KEY,None)

    def execute(self):
        exec(SOURCE,self.ns)
        capture=sys.modules[KEY].capture
        self.ns['perf_counter_ns']=lambda:self.now
        return capture

    def signal(self,fn,obj):
        path=fn._path_name().rsplit('.',1)
        path=':'.join(path)
        for spec,callback in list(phase.harness.HOOKS.items()):
            if spec[0]==path:
                callback(obj,S(),None,fn)

    def saved(self,capture):
        report=super().saved(capture)
        self.assertFalse(capture.signal_specs)
        self.assertFalse([k for k in phase.harness.HOOKS if
                          k[2].startswith('bl4tps.ground_slam_signals.')])
        return report

    def test_pure_getter_and_start_stop_calls_correlate_and_cleanup(self):
        capture=self.arm()
        self.assertEqual(len(capture.signal_specs),3)
        self.tick()
        self.signal(self.start_fn,self.world.movement)
        self.signal(self.listener_fn,self.listener)
        self.world.movement.slam_active=True
        self.tick()
        self.assertTrue(capture.report['samples'][-1]['slam_getters']['movement.IsGroundSlamming'])
        self.world.movement.slam_active=False
        self.signal(self.stop_fn,self.world.movement)
        self.tick()
        self.execute()
        report=self.saved(capture)
        self.assertEqual(len(report['signal_events']),3)
        self.assertEqual(report['sdk_hooks_peak'],4)
        self.assertEqual(len(report['delegates']),2)
        self.assertEqual(len(self.started_delegate),1)
        self.assertEqual(self.getter_calls,3)

    def test_nonpure_and_wrong_signature_getters_are_metadata_only(self):
        self.getter.FunctionFlags=0
        capture=self.arm()
        self.tick()
        self.assertFalse(capture.getters)
        self.assertEqual(self.getter_calls,0)
        self.execute()
        self.saved(capture)
        self.getter.FunctionFlags=0x10000000
        self.getter.NumParams=2
        capture=self.arm()
        self.assertFalse(capture.getters)

    def test_foreign_listener_and_worker_events_filtered(self):
        capture=self.arm()
        self.signal(self.start_fn,S())
        self.assertFalse(capture.report['signal_events'])
        with patch.object(height.runtime_updates,'is_game_thread',return_value=False):
            self.signal(self.start_fn,self.world.movement)
        self.assertFalse(capture.report['signal_events'])
        self.assertEqual(capture.report['skipped_worker_events'],1)

    def test_signal_remove_failure_keeps_cleanup_owned_for_retry(self):
        capture=self.arm()
        original=height.hooks.remove_hook
        def stuck(path,kind,key):
            if '.event.' in key:return False
            return original(path,kind,key)
        with patch.object(height.hooks,'remove_hook',stuck):
            with self.assertRaisesRegex(RuntimeError,'observer removal unverified'):
                self.execute()
        self.assertIs(height._capture,capture)
        self.assertTrue(capture.signal_specs)
        self.execute()
        self.saved(capture)

    def test_partial_signal_registration_failure_removes_all_observers(self):
        capture=self.execute()
        capture.armed_at=0
        original=height.hooks.add_hook
        def fail(path,kind,key,callback):
            original(path,kind,key,callback)
            if key.endswith('.event.1'):raise RuntimeError('simulated partial add failure')
        with patch.object(height.hooks,'add_hook',fail):self.tick()
        report=self.saved(capture)
        self.assertEqual(report['status'],'READ_OR_START_FAILED')


if __name__=='__main__':unittest.main()
