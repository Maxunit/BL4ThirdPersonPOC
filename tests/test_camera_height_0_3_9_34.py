"""Actual diagnostic reads, ownership, bounded output and subscription cleanup."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import support
from BL4ThirdPersonPOC import camera_height_capture as height


def point(x=0,y=0,z=0):
    return S(X=x,Y=y,Z=z)


def obj(address,**values):
    return S(_get_address=lambda:address,**values)


def runtime(directory):
    position=point(z=100)
    spine=point(z=160)
    mesh_pos=point(z=10)
    camera_pos=point(z=220)
    rotation=S(Pitch=5,Yaw=10,Roll=0)
    capsule=obj(6,K2_GetComponentLocation=lambda:position,
                GetScaledCapsuleHalfHeight=lambda:100)
    floor=S(FloorDist=0,LineDist=0,bBlockingHit=True,bWalkableFloor=True,
            HitResult=S(ImpactPoint=point(),ImpactNormal=point(z=1)))
    movement=obj(5,MovementMode=1,CustomMovementMode=0,Velocity=point(),CurrentFloor=floor)
    bones={'Spine3':spine,'Head':point(z=190),'Root':point(),'Spine5':point(z=170)}
    mesh=obj(4,RelativeLocation=point(z=-90),RelativeRotation=rotation,
             K2_GetComponentLocation=lambda:mesh_pos,
             DoesSocketExist=lambda name:name in bones,
             GetSocketLocation=lambda name:bones[name])
    pawn=obj(2,Mesh=mesh,OakCharacterMovement=movement,CapsuleComponent=capsule,
             K2_GetActorLocation=lambda:position,K2_GetActorRotation=lambda:rotation,
             bIsCrouched=False)
    pov=S(Location=camera_pos,Rotation=rotation,FOV=90)
    camera=obj(3,CameraCachePrivate=S(POV=pov),
               CameraModeState=S(POV=pov,bIsColliding=False,bIsTransitioning=False,
                                  CameraLocationOffset=point(x=-200,y=60,z=30)),
               GetActorCameraMode=lambda pawn:'ThirdPerson',
               GetCameraLocation=lambda:camera_pos)
    pc=obj(1,bShowMouseCursor=False,GetControlRotation=lambda:rotation)
    runtime_objects=[pc,pawn,camera]
    logs=[]
    mod=S(MOD_VERSION='0.3.9.34',SETTINGS_DIR=directory,FIRST_PERSON_ANIM_HOOK='widget',
          _third_person_enabled=True,_get_runtime=lambda:tuple(runtime_objects),
          logging=S(warning=logs.append,error=logs.append),
          _dynamic_motion_enabled=True,
          _dynamic_motion_state=dict(baseline=(0,0,60),filtered=(0,0,0)),
          _dynamic_motion_parameters=dict(baseline=3.5,still_gain=16),
          camera_offset_x=S(value=-200),camera_offset_y=S(value=60),camera_offset_z=S(value=30))
    return mod,S(position=position,spine=spine,mesh_pos=mesh_pos,camera_pos=camera_pos,
                 pc=pc,pawn=pawn,camera=camera,movement=movement,mesh=mesh,bones=bones,
                 objects=runtime_objects,logs=logs)


class HeightCaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.mod,self.world=runtime(self.directory.name)
        self.routes={}
        self.on_thread=True
        self.patches=[
            patch.object(height.runtime_updates,'is_game_thread',lambda:self.on_thread),
            patch.object(height.runtime_updates,'has_hook',lambda *spec:spec in self.routes),
            patch.object(height.runtime_updates,'add_hook',self.add),
            patch.object(height.runtime_updates,'remove_hook',lambda *spec:self.routes.pop(spec,None)),
            patch('BL4ThirdPersonPOC.omni.profiler.status',return_value=dict(state='off'))]
        for p in self.patches:p.start()
        height._armed=height._capture=height._last=None

    def tearDown(self):
        height._armed=height._capture=height._last=None
        for p in reversed(self.patches):p.stop()
        self.directory.cleanup()

    def add(self,*args):
        self.routes[args[:-1]]=args[-1]

    def start(self,label='boden'):
        height.arm(self.mod,label)
        self.assertTrue(height.trigger(self.mod))
        self.assertEqual(height.status(self.mod)['state'],'running')
        return height._capture

    def test_off_and_arm_do_not_read_runtime_or_add_subscription(self):
        self.mod._get_runtime=lambda:self.fail('unarmed SDK read')
        self.assertFalse(height.trigger(self.mod))
        height.arm(self.mod,'boden')
        self.assertEqual(height.status(self.mod)['state'],'armed')
        self.assertFalse(self.routes)
        height.shutdown(self.mod)
        self.assertEqual(height.status(self.mod)['state'],'off')

    def test_rejects_unsafe_labels_before_arming(self):
        for label in ('../escape','a b','','x'*41):
            with self.assertRaises(ValueError):height.arm(self.mod,label)
        self.assertIsNone(height._armed)

    def test_profiler_exclusivity_and_foreign_trigger(self):
        with patch('BL4ThirdPersonPOC.omni.profiler.status',return_value=dict(state='armed')):
            with self.assertRaisesRegex(RuntimeError,'profiler'):height.arm(self.mod,'floor')
        height.arm(self.mod,'floor')
        self.assertFalse(height.trigger(S()))
        self.assertEqual(height.status(self.mod)['state'],'armed')

    def test_captures_relative_height_camera_pose_motion_and_capsule(self):
        capture=self.start()
        row=capture.read_row()
        self.assertEqual(row['relative'],dict(spine_actor_z=60,mesh_actor_z=-90,
            camera_actor_z=120,camera_spine_z=60,motion_baseline_z=60,motion_filtered_z=0))
        self.assertEqual(row['capsule']['bottom_z'],0)
        self.assertEqual(row['camera_cache']['rotation']['Pitch'],5)
        self.assertEqual(row['camera_cache']['fov'],90)
        self.assertEqual(row['floor']['impact_point']['Z'],0)
        self.assertFalse(row['camera_flags']['colliding'])
        self.assertEqual(row['applied_offset']['Z'],30)
        self.assertEqual(row['configured_offset']['z'],30)

    def test_body_lowering_and_camera_raising_are_distinguishable(self):
        capture=self.start()
        first=capture.read_row()
        self.world.spine.Z-=30
        self.world.mesh_pos.Z-=30
        body=capture.read_row()
        self.assertEqual(body['relative']['spine_actor_z'],30)
        self.assertEqual(body['relative']['camera_actor_z'],first['relative']['camera_actor_z'])
        self.assertEqual(body['relative']['camera_spine_z'],90)
        self.world.spine.Z=160
        self.world.mesh_pos.Z=10
        self.world.camera_pos.Z+=20
        camera=capture.read_row()
        self.assertEqual(camera['relative']['spine_actor_z'],60)
        self.assertEqual(camera['relative']['camera_actor_z'],140)

    def test_600_updates_complete_detach_and_save_strict_json(self):
        capture=self.start()
        for _ in range(height.LIMIT+5):capture.frame(None,None,None,None)
        self.assertEqual(capture.frames,600)
        self.assertFalse(self.routes)
        self.assertIsNone(height._capture)
        report=json.loads(capture.path.read_text())
        self.assertEqual(len(report['samples']),600)
        self.assertEqual(report['status'],'COMPLETE')
        self.assertEqual(report['sdk_hooks'],0)
        self.assertEqual(report['game_writes'],0)
        self.assertEqual(report['summary']['last_120']['camera_spine_z']['count'],120)
        self.assertEqual(report['summary']['modes'],{'ThirdPerson':600})

    def test_f10_manual_stop_and_shutdown_remove_subscription(self):
        for stop in (height.trigger,height.shutdown):
            capture=self.start()
            capture.frame(None,None,None,None)
            self.assertTrue(stop(self.mod))
            self.assertFalse(self.routes)
            self.assertEqual(json.loads(capture.path.read_text())['completed_updates'],1)

    def test_start_off_thread_ui_or_missing_spine_is_refused(self):
        for context in ('thread','ui','spine'):
            self.on_thread=context!='thread'
            self.world.pc.bShowMouseCursor=context=='ui'
            self.world.mesh.DoesSocketExist=lambda name:context!='spine'
            height.arm(self.mod,context)
            height.trigger(self.mod)
            self.assertIsNone(height._capture)
            self.assertFalse(self.routes)
            self.assertEqual(height._last['status'],'START_FAILED')

    def test_expired_replaced_or_rebound_owners_stop_before_core_reads(self):
        for changed in ('weak','runtime','mesh','movement'):
            self.mod,self.world=runtime(self.directory.name)
            capture=self.start(changed)
            self.world.pawn.K2_GetActorLocation=lambda:self.fail('read after owner failure')
            if changed=='weak':capture.refs=(capture.refs[0],lambda:None,*capture.refs[2:])
            elif changed=='runtime':self.world.objects[0]=obj(100)
            elif changed=='mesh':self.world.pawn.Mesh=obj(101)
            else:self.world.pawn.OakCharacterMovement=obj(102)
            capture.frame(None,None,None,None)
            self.assertFalse(self.routes)
            self.assertEqual(capture.frames,0)
            self.assertEqual(capture.report['status'],'READ_FAILED')

    def test_inline_owner_change_discards_partial_row(self):
        capture=self.start()
        def read():
            self.world.objects[0]=obj(900)
            return self.world.spine
        self.world.mesh.GetSocketLocation=lambda name:read()
        capture.frame(None,None,None,None)
        self.assertEqual(capture.frames,0)
        self.assertFalse(capture.report['samples'])
        self.assertFalse(self.routes)

    def test_missing_optional_fields_are_bounded_and_do_not_stop_capture(self):
        capture=self.start()
        del self.world.movement.CurrentFloor
        self.world.camera.CameraCachePrivate.POV.FOV=float('nan')
        for _ in range(3):capture.frame(None,None,None,None)
        self.assertTrue(capture.active)
        self.assertEqual(capture.frames,3)
        self.assertEqual(capture.report['optional_errors']['floor']['count'],3)
        self.assertIsNone(capture.report['samples'][0]['camera_cache'])
        capture.finish('TEST')
        json.loads(capture.path.read_text())

    def test_core_nonfinite_stops_without_committing_invalid_json(self):
        capture=self.start()
        self.world.spine.Z=float('nan')
        capture.frame(None,None,None,None)
        self.assertEqual(capture.frames,0)
        self.assertFalse(self.routes)
        self.assertEqual(json.loads(capture.path.read_text())['status'],'READ_FAILED')

    def test_failed_registration_and_removal_are_retryable(self):
        def fail_add(*args):
            self.add(*args)
            raise RuntimeError('partial add')
        with patch.object(height.runtime_updates,'add_hook',fail_add):
            height.arm(self.mod,'partial')
            height.trigger(self.mod)
        self.assertFalse(self.routes)
        self.assertEqual(height._last['status'],'START_FAILED')
        capture=self.start()
        with patch.object(height.runtime_updates,'remove_hook',lambda *args:None):
            height.trigger(self.mod)
            self.assertEqual(height.status(self.mod)['state'],'cleanup_pending')
        height.shutdown(self.mod)
        self.assertFalse(self.routes)
        self.assertIsNone(height._capture)

    def test_capture_reads_are_forbidden_off_thread(self):
        capture=self.start()
        self.on_thread=False
        self.mod._get_runtime=lambda:self.fail('off-thread read')
        capture.frame(None,None,None,None)
        self.assertEqual(capture.frames,0)
        self.assertTrue(capture.active)

    def test_output_failure_does_not_retain_gameplay_producer(self):
        capture=self.start()
        with patch.object(Path,'write_text',side_effect=OSError('disk unavailable')):
            height.shutdown(self.mod)
        self.assertFalse(self.routes)
        self.assertIsNone(height._capture)
        self.assertEqual(height._last['status'],'OUTPUT_FAILED')
        self.assertTrue(capture.report['cleanup_complete'])

    def test_real_loader_command_f10_and_existing_post_route(self):
        scenario=Path(__file__).with_name('camera_height_loader_scenario.py')
        result=subprocess.run([sys.executable,str(scenario)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report,dict(version='0.3.9.40',updates=600,hooks=0,game_writes=0))

    def test_ground_slam_references_are_plain_read_only_snapshots(self):
        capture=self.start()
        old=sys.modules.get('_bl4tps_ground_slam_beta_owner')
        try:
            sys.modules['_bl4tps_ground_slam_beta_owner']=S(report=dict(
                body_anchor=dict(rest_relative_z=60),pawn_anchor_target=dict(relative_offset=[0,0,120]),
                position_writes=5,handoff_offset_writes=0))
            row=capture.read_row()
            self.assertEqual(row['slam_reference']['body_anchor']['rest_relative_z'],60)
            self.assertEqual(row['slam_reference']['position_writes'],5)
        finally:
            if old is None:sys.modules.pop('_bl4tps_ground_slam_beta_owner',None)
            else:sys.modules['_bl4tps_ground_slam_beta_owner']=old


if __name__=='__main__':unittest.main()
