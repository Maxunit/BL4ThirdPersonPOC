"""Production Slam envelope, guarded native handoff and upper-body admission."""
import ctypes
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from types import SimpleNamespace as S
from unittest.mock import Mock, patch
import support
from test_camera_height_0_3_9_34 import runtime
from test_free_look_0_3_9_33 import publisher_session, packed
from BL4ThirdPersonPOC import ground_slam_distance as distance
from BL4ThirdPersonPOC import ground_slam_camera as native
from BL4ThirdPersonPOC.omni.session import GameplaySession
from BL4ThirdPersonPOC.omni.air import AirMixin
from BL4ThirdPersonPOC.omni.free_look import publish


class DistanceTests(unittest.TestCase):
    def setUp(self):
        self.mod,self.w=runtime('/tmp')
        self.mod._third_person_pushed=True
        self.mod.ground_slam_distance_cm=S(value=150.)
        self.mod.tps_ground_slam_beta=S(value=True)
        self.mod._camera_lifecycle=self.mod._mantle_camera_state={}
        self.mod._camera_frame=dict(slam_distance_mode='ThirdPerson')
        self.mod._looks_like_first_person_fallback=lambda:False
        self.mode='ThirdPerson'
        self.w.camera.GetActorCameraMode=lambda pawn:self.mode
        self.slam=False
        self.w.pawn.IsPerformingGroundSlam=Mock(side_effect=lambda:self.slam)
        getter=S(_path_name=lambda:'/Script/OakGame.OakCharacter:IsPerformingGroundSlam',
                 FunctionFlags=0x10000000,NumParams=1,_properties=lambda:iter((
                 S(Class=S(Name='BoolProperty'),PropertyFlags=0x400),)))
        self.w.pawn.Class=S(_find=lambda name:getter)
        names=('WorldContextObject','Start','End','TraceChannel','bTraceComplex',
               'ActorsToIgnore','DrawDebugType','OutHit','bIgnoreSelf','TraceColor',
               'TraceHitColor','DrawTime','ReturnValue')
        props=[S(Name=name,Class=S(Name='OtherProperty')) for name in names]
        props[-1].Class.Name='BoolProperty'
        props[7].Struct=S(_path_name=lambda:'/Script/Engine.HitResult')
        fn=S(NumParams=13,_properties=lambda:iter(props))
        self.floor_z=0.
        self.failed_channels=set()
        self.trace_calls=0
        self.library=S(Class=S(_find=lambda name:fn),LineTraceSingle=self.trace)
        self.lookup=patch.object(distance,'find_object',return_value=self.library)
        self.thread=patch.object(distance.runtime_updates,'is_game_thread',return_value=True)
        self.lookup.start();self.thread.start()
        self.old_native=sys.modules.pop(native.KEY,None)

    def tearDown(self):
        distance.shutdown(self.mod)
        self.lookup.stop();self.thread.stop()
        sys.modules.pop(native.KEY,None)
        if self.old_native is not None:sys.modules[native.KEY]=self.old_native

    def trace(self,*args):
        self.trace_calls+=1
        self.assertEqual(args[5],[self.w.pawn])
        self.assertEqual(args[6],0)
        self.assertTrue(args[8])
        self.assertEqual(args[-1],0.)
        return (args[3] not in self.failed_channels,S(ImpactPoint=S(Z=self.floor_z),
                ImpactNormal=S(Z=1.),bBlockingHit=True,bStartPenetrating=False))

    def step(self,dt=1/60,write=True):
        distance.pre_frame(self.mod,S(InDeltaTime=dt))
        distance.update(self.mod,self.w.pc,self.w.pawn,self.w.camera,self.mode)
        state=self.mod._ground_slam_distance_state
        if write:
            raw=distance.compensate(self.mod,self.w.pc,self.w.pawn,self.w.camera,(45.,55.,10.))
            self.w.camera.CameraModeState.CameraLocationOffset=S(X=raw[0]-256.,Y=raw[1],Z=raw[2])
        return state

    def ready(self):
        for _ in range(5):state=self.step()
        self.assertEqual(state.shift,-256.)
        self.assertEqual(state.channel,0)
        return state

    def air(self,height=3000.,velocity=-5000.):
        self.w.position.Z=100.+self.floor_z+height
        self.w.movement.MovementMode=3
        self.w.movement.Velocity.Z=velocity
        self.slam=True

    def far(self):
        state=self.ready();self.air()
        for _ in range(48):state=self.step()
        self.assertEqual(state.amount,150.)
        return state

    def close(self):
        for height in (1800.,1300.,1000.,800.,600.,400.,250.,180.):
            self.air(height);state=self.step()
        self.assertEqual(state.amount,0.)
        self.assertTrue(self.slam)

    def exit(self,target=None):
        v=self.w.camera.CameraModeState.CameraLocationOffset
        target=target or (v.X, v.Y+.3, v.Z-.4)
        buffer=ctypes.create_string_buffer(256)
        struct.pack_into('<I',buffer,8,1);struct.pack_into('<I',buffer,184,1)
        struct.pack_into('<Q',buffer,40,1234);struct.pack_into('<3d',buffer,160,*target)
        owner=S(active=True,mod=self.mod,owner_invalidated=False,modify=buffer,
                owner_identity=(1,2,3),owner_refs=tuple(lambda o=o:o for o in self.w.objects))
        sys.modules[native.KEY]=owner
        self.mode='GroundSlamExit';self.slam=False
        self.w.movement.MovementMode=1
        self.w.camera.CameraModeState.CameraLocationOffset=S(X=target[0],Y=target[1],Z=target[2])
        return owner

    def test_hold_release_before_impact_and_preserve_native_body_axes(self):
        state=self.far();self.close()
        owner=self.exit();before=owner.modify.raw
        self.step(write=False)
        self.assertEqual(state.status,'exit_neutral')
        self.assertEqual(owner.modify.raw,before)
        self.mode='ThirdPerson';self.step()
        self.assertIsNone(state.bridge)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.X,-211.)

    def test_old_native_snapshot_cannot_reexpand_neutral_camera(self):
        state=self.far()
        early=self.w.camera.CameraModeState.CameraLocationOffset
        target=(early.X,early.Y+.3,early.Z-.4)
        self.close();owner=self.exit(target);self.step(write=False)
        self.assertEqual(state.amount,0.)
        self.assertEqual(struct.unpack_from('<3d',owner.modify.raw,160),(-211.,*target[1:]))

    def test_unmatched_native_target_stays_unchanged_and_tps_release_is_smooth(self):
        state=self.far();owner=self.exit((-444.,55.,10.));before=owner.modify.raw
        self.step(write=False)
        self.assertTrue(state.fallback);self.assertEqual(owner.modify.raw,before)
        self.mode='ThirdPerson';self.w.camera.CameraModeState.bIsTransitioning=True
        values=[self.step().amount]
        self.assertEqual(values[0],150.)
        for _ in range(70):values.append(self.step().amount)
        self.assertEqual(values[-1],0.)
        self.assertTrue(all(a>=b for a,b in zip(values,values[1:])))
        self.assertLess(max(a-b for a,b in zip(values,values[1:])),25.)

    def test_idle_and_ordinary_jump_have_no_extra_or_repeated_floor_trace(self):
        state=self.ready()
        for _ in range(600):self.step()
        self.assertEqual(self.trace_calls,2)
        self.assertEqual(self.w.pawn.IsPerformingGroundSlam.call_count,0)
        self.w.movement.MovementMode=3
        for _ in range(30):self.step()
        self.assertEqual(self.trace_calls,2)
        self.assertEqual(state.amount,0.)

    def test_missing_ground_during_release_does_not_rezoom(self):
        state=self.far();self.air(600.);self.step();before=state.amount
        self.failed_channels.add(state.channel);self.air(2000.)
        self.step();self.assertEqual(state.amount,before)
        self.failed_channels.clear();self.step();self.assertEqual(state.amount,before)

    def test_zero_or_feature_off_and_context_handoffs_remove_extra(self):
        state=self.far()
        self.mod.ground_slam_distance_cm.value=0.;self.step()
        self.assertIsNone(self.mod._ground_slam_distance_state)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.X,-211.)
        self.mod.ground_slam_distance_cm.value=150.;self.w.position.Z=100.
        self.w.movement.MovementMode=1;self.slam=False
        state=self.far();self.mod._ads_active=True;self.step()
        self.assertEqual(state.amount,0.)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.X,-211.)

    def test_calibration_failure_cannot_modify_camera(self):
        self.failed_channels.update((0,1));state=self.step()
        self.assertTrue(state.fault)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.X,-211.)
        self.assertEqual(state.amount,0.)

    def test_foreign_buffer_writer_is_retained_and_blocks_cleanup(self):
        state=self.far();owner=self.exit();self.step(write=False)
        self.assertIsNotNone(state.bridge)
        struct.pack_into('<d',owner.modify,160,-123.)
        with self.assertRaisesRegex(RuntimeError,'another writer'):distance.shutdown(self.mod)
        self.assertIs(self.mod._ground_slam_distance_state,state)
        self.assertEqual(struct.unpack_from('<d',owner.modify.raw,160)[0],-123.)
        owner.active=False

    def test_retired_owner_or_changed_pawn_gets_no_exit_write(self):
        state=self.far();owner=self.exit();self.step(write=False)
        owner.active=False;before=owner.modify.raw
        distance.shutdown(self.mod);self.assertEqual(owner.modify.raw,before)

    def test_shutdown_is_queued_by_caller_if_native_bridge_not_on_game_thread(self):
        self.far();self.exit();self.step(write=False)
        with patch.object(distance.runtime_updates,'is_game_thread',return_value=False):
            self.assertFalse(distance.shutdown(self.mod))
        self.assertTrue(distance.shutdown(self.mod))

    def test_real_setter_preserves_root_and_does_not_accumulate(self):
        from BL4ThirdPersonPOC import camera_math as cm
        state=self.far()
        self.mod.root_height_enabled=S(value=True)
        self.mod._camera_frame=dict(slam_distance_mode='ThirdPerson',height_refs=tuple(lambda o=o:o for o in
            (self.w.pc,self.w.pawn,self.w.camera,self.w.mesh)),height_local=(5.,11.,-44.))
        for _ in range(5):
            self.assertTrue(cm._set_camera_offset_impl(45.,55.,10.,owner_module=self.mod))
            v=self.w.camera.CameraModeState.CameraLocationOffset
            self.assertEqual((v.X,v.Y,v.Z),(-100.,66.,-34.))
        self.mod._camera_frame=None
        cm._set_camera_offset_impl(45.,55.,10.,owner_module=self.mod)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.X,45.)

    def test_six_recorded_slams_return_at_contact_with_150_cm(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/ground_slam_v4_20261011.json').read_text())
        for episode in fixture['episodes']:
            distance.shutdown(self.mod)
            self.w.movement.MovementMode=1;self.w.position.Z=100.;self.mode='ThirdPerson';self.slam=False
            state=self.ready();state.gap=fixture['contact_gap']
            values=[]
            for dt,gap,velocity,original in episode['rows']:
                self.air(gap,velocity);self.step(dt)
                values.append(state.amount)
                self.assertLessEqual(state.amount,150.)
                self.assertLess(abs(state.amount-original*.6),1.5)
            self.assertEqual(values[-1],0.)
            self.exit();self.step(write=False)
            self.assertEqual(state.amount,0.)
            self.assertFalse(state.fallback)

    def test_missing_widget_delta_uses_measured_callback_elapsed_and_zero_delta_pauses(self):
        self.ready();self.air()
        ticks=iter(i*16_666_667 for i in range(55))
        with patch.object(distance,'perf_counter_ns',side_effect=lambda:next(ticks)):
            self.mod._slam_distance_tick=None
            for _ in range(50):distance.step(self.mod,None)
        state=self.mod._ground_slam_distance_state
        self.assertEqual(state.amount,150.)
        self.assertEqual(self.mod._slam_distance_delta_source,'owned_callback_elapsed')
        state.entry=state.amount=50.
        distance.step(self.mod,S(InDeltaTime=0.))
        self.assertEqual(state.amount,50.)
        self.assertEqual(self.mod._slam_distance_delta_source,'widget_InDeltaTime')

    def test_setter_foreign_mode_between_widget_ticks_never_gets_stale_extra(self):
        state=self.far()
        before=len(state.history)
        self.mod._camera_frame['slam_distance_mode']='GroundSlamExit'
        values=distance.compensate(self.mod,self.w.pc,self.w.pawn,self.w.camera,(0.,0.,0.))
        self.assertEqual(values,(0.,0.,0.))
        self.assertEqual(len(state.history),before)
        self.mod._camera_frame={}
        self.assertEqual(distance.compensate(self.mod,self.w.pc,self.w.pawn,self.w.camera,(45.,55.,10.)),(45.,55.,10.))

    def test_failed_subscription_removal_keeps_retry_spec_and_inerts_callback(self):
        state=self.far()
        spec=('widget',0,'owned_distance')
        self.mod._slam_distance_spec=spec
        with patch.object(distance.runtime_updates,'remove_hook',return_value=False),\
             patch.object(distance.runtime_updates,'has_hook',return_value=True):
            self.assertFalse(distance.shutdown(self.mod))
        self.assertEqual(self.mod._slam_distance_spec,spec)
        distance.step(self.mod,S(InDeltaTime=1/60))
        self.assertIsNone(self.mod._ground_slam_distance_state)
        with patch.object(distance.runtime_updates,'remove_hook',return_value=True),\
             patch.object(distance.runtime_updates,'has_hook',return_value=False):
            self.assertTrue(distance.shutdown(self.mod))
        self.assertIsNone(self.mod._slam_distance_spec)


class PoseAdmissionTests(unittest.TestCase):
    def test_real_loader_camera_scope_menu_default_and_shutdown(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('ground_slam_loader_scenario.py'))],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),dict(version='0.3.9.39',far=[-105.,55.,10.],
                         near=[45.,55.,10.],scope_cleared=True,default=150.,shutdown=True))

    def test_real_frame_disables_stale_front_pose_in_air_and_exit_then_resumes(self):
        state,sample=publisher_session()
        session=GameplaySession.__new__(GameplaySession);session.__dict__.update(state.__dict__)
        session.busy=session.lifecycle_managed=False
        session.updates=S(is_game_thread=lambda:True)
        movement=S(MovementMode=3,CustomMovementMode=0)
        slam=True;mode='ThirdPerson'
        pawn=S(IsPerformingGroundSlam=Mock(side_effect=lambda:slam),IsCharacterDashing=lambda:False)
        camera=S(GetActorCameraMode=lambda pawn:mode,CameraModeState=S(bIsTransitioning=False))
        session.native=S(control=[0]*10,hook={},base=0x140000000,validate=Mock())
        session.slam_heading_owned=False
        session.idle_native=S(control=[0]*9);session.idle_update=S(control=[0]*9)
        session.jump_idle_owned=False;session.close_jump=Mock()
        session.bound=lambda:(S(bShowMouseCursor=False),pawn,camera,movement)
        session.inputs=S(begin_frame=lambda **kw:None,end_frame=lambda:None)
        session.disarm_ground_vector=lambda:None;session.ground_clip_originals=[]
        def pipeline(*args):
            # Reproduce the older airborne special phase publishing mode 1.
            session.aim_native.control[0]=session.aim_native.crouch_control[0]=1
            session.free_look_context=movement.MovementMode==1 and mode=='ThirdPerson'
        session._ground_pose_frame=pipeline
        sample['camera_rotation']['Yaw']=180.
        session.aim_native.control[0]=2;session.aim_native.control[5]=packed(0.,0.)
        session.frame(None,None,None,None)
        self.assertEqual((session.aim_native.control[0],session.aim_native.crouch_control[0]),(0,0))
        self.assertTrue(session.ground_slam_pose_native)
        self.assertEqual(pawn.IsPerformingGroundSlam.call_count,1)
        slam=False;mode='GroundSlamExit';movement.MovementMode=1
        session.frame(None,None,None,None)
        self.assertEqual((session.aim_native.control[0],session.aim_native.crouch_control[0]),(0,0))
        mode='ThirdPerson';session.frame(None,None,None,None)
        self.assertFalse(session.ground_slam_pose_native)
        self.assertEqual(session.aim_native.control[0],2)
        self.assertEqual(struct.unpack('<ff',struct.pack('<Q',session.aim_native.control[5])),(0.,0.))

    def test_getter_is_read_once_in_air_scope_and_never_on_ordinary_ground(self):
        session=GameplaySession.__new__(GameplaySession)
        pawn=S(IsPerformingGroundSlam=Mock(return_value=True))
        movement=S(MovementMode=1,CustomMovementMode=0)
        session.open_callback_scope()
        self.assertFalse(session.is_ground_slamming(pawn,movement))
        pawn.IsPerformingGroundSlam.assert_not_called()
        movement.MovementMode=3
        self.assertTrue(session.is_ground_slamming(pawn,movement))
        self.assertTrue(session.is_ground_slamming(pawn,movement))
        pawn.IsPerformingGroundSlam.assert_called_once()
        session.close_callback_scope()

    def test_slam_releases_air_lean_and_jump_pose_but_ordinary_jump_keeps_them(self):
        for slam in (False,True):
            session=GameplaySession.__new__(GameplaySession)
            session.ground_slam_pose_native=slam
            session.aim_native=S(control=[2])
            session.configure_jump_idle=Mock()
            node=S(AlphaInputType=1,bAlphaBoolEnabled=False,bInvertAlpha=True)
            session.blend_node=lambda:node
            session.blend_original=True;session.blend_pending=False
            session.report=dict(game_writes=0)
            session.restore_blend=Mock(side_effect=lambda:setattr(node,'bInvertAlpha',True))
            AirMixin.configure_air_pose(session,True)
            session.configure_jump_idle.assert_called_once_with(not slam)
            self.assertEqual(session.aim_native.control[0],int(not slam))
            self.assertEqual(node.bInvertAlpha,slam)
            self.assertEqual(session.restore_blend.call_count,int(slam))


if __name__=='__main__':unittest.main()
