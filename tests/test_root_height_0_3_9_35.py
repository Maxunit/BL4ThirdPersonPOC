"""Actual camera composition, measured replays, gates and Root/Motion separation."""
import json, math, subprocess, sys, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace as S
import support
from BL4ThirdPersonPOC import root_height, camera_math as cm, hybrid_ads, shoulder_blend
from root_height_world import world

ROOT=Path(__file__).resolve().parents[1]


class RootHeightTests(unittest.TestCase):
    def setUp(self):
        hybrid_ads.reset();shoulder_blend.reset()
        self.owner,self.w=world()

    def lower(self,drop=44):
        self.w.values['root']=self.w.values['mesh']-2-drop
        self.w.values['spine']=self.w.values['root']+147

    def run_frames(self,n=100):
        for _ in range(n):offset,state=self.w.update()
        return offset,state

    def test_start_on_railing_with_motion_off_keeps_persistent_correction(self):
        self.owner._dynamic_motion_enabled=False;self.lower()
        offset,state=self.run_frames(600)
        self.assertAlmostEqual(state['filtered_z'],-44)
        self.assertAlmostEqual(offset[2],10-44)
        self.assertEqual(self.w.values['actor'],1000)
        self.assertEqual(self.w.values['root'],854)
        self.assertEqual(self.w.calls['root'],600)
        self.assertEqual(self.w.calls['exists'],1)

    def test_neutral_ground_and_toggle_off_keep_exact_configured_offset(self):
        offset,state=self.run_frames()
        self.assertEqual(offset,(45,55,10));self.assertEqual(state['filtered_z'],0)
        self.lower();self.run_frames()
        self.owner.root_height_enabled.value=False;self.owner._dynamic_motion_reset()
        before=self.w.calls['root'];offset,state=self.run_frames()
        self.assertEqual(offset,(45,55,10));self.assertEqual(self.w.calls['root'],before)

    def test_return_to_ground_releases_smoothly_without_residual_offset(self):
        self.lower();self.run_frames();self.w.values.update(root=898.,spine=1045.)
        offset,state=self.w.update()
        self.assertGreater(state['filtered_z'],-44);self.assertLess(state['filtered_z'],-30)
        offset,state=self.run_frames()
        self.assertEqual(offset,(45,55,10));self.assertEqual(state['filtered_z'],0)

    def test_pure_root_translation_is_removed_from_motion_but_landing_is_retained(self):
        self.run_frames();self.lower()
        for _ in range(25):self.w.update()
        self.assertAlmostEqual(self.owner._dynamic_motion_state['filtered'][2],0,places=9)
        self.w.values['spine']-=30
        self.w.update();self.w.update()
        self.assertLess(self.owner._dynamic_motion_state['filtered'][2],-.5)

    def test_motion_uses_one_shared_actor_and_spine_read_per_update(self):
        self.run_frames(100)
        self.assertEqual(self.w.calls['actor'],100)
        self.assertEqual(self.w.calls['mesh'],100)
        self.assertEqual(self.w.calls['spine'],100)
        self.assertEqual(self.w.calls['root'],100)

    def test_world_vertical_projection_has_no_horizontal_drift_at_any_pitch(self):
        for pitch in (-90,-65,-20,0,35,80,90):
            for roll in (-40,0,25):
                p,r=math.radians(pitch),math.radians(roll)
                # Independent engine camera axes for yaw zero, in world coordinates.
                axes=((math.cos(p),0,math.sin(p)),
                      (math.sin(p)*math.sin(r),math.cos(r),-math.cos(p)*math.sin(r)),
                      (-math.sin(p)*math.cos(r),math.sin(r),math.cos(p)*math.cos(r)))
                local=root_height.vertical_local(-44,pitch,roll)
                world_delta=tuple(sum(local[i]*axes[i][j] for i in range(3)) for j in range(3))
                self.assertAlmostEqual(world_delta[0],0,places=10)
                self.assertAlmostEqual(world_delta[1],0,places=10)
                self.assertAlmostEqual(world_delta[2],-44,places=10)
        self.lower();self.w.rotation.Pitch=70
        offset,state=self.run_frames()
        expected=root_height.vertical_local(state['filtered_z'],70,0)
        for v,b,d in zip(offset,(45,55,10),expected):self.assertAlmostEqual(v,b+d)

    def test_air_and_crouch_release_without_new_root_height_targets(self):
        for crouch in (False,True):
            self.setUp();self.lower();self.run_frames()
            self.w.pawn.bIsCrouched=crouch
            self.w.movement.MovementMode=1 if crouch else 3
            self.w.values['root']=self.w.values['mesh'] if not crouch else self.w.values['root']
            _,state=self.w.update()
            self.assertEqual(state['target_z'],0)
            self.assertLess(state['filtered_z'],0)
            _,state=self.run_frames()
            self.assertEqual(state['filtered_z'],0)

    def test_unsafe_camera_states_do_not_read_or_publish_root_offsets(self):
        for flag in ('_ads_active','_vehicle_camera_active','_shop_camera_active',
                     '_slide_active','_ladder_active'):
            self.setUp();self.lower();self.run_frames();before=self.w.calls['root']
            setattr(self.owner,flag,True);self.w.update()
            self.assertEqual(self.w.calls['root'],before,flag)
            self.assertEqual(self.owner._root_height_state['filtered_z'],0,flag)
        for gate in ('fps','pending','ffyl','ui','transition','custom'):
            self.setUp();self.lower();self.run_frames();before=self.w.calls['root']
            if gate=='fps':self.w.camera.GetActorCameraMode=lambda p:'GroundSlam'
            if gate=='pending':self.owner._camera_lifecycle['pending']=True
            if gate=='ffyl':self.owner._ffyl_camera_active=lambda p,c:True
            if gate=='ui':self.w.pc.bShowMouseCursor=True
            if gate=='transition':self.w.camera.CameraModeState.bIsTransitioning=True
            if gate=='custom':self.w.movement.CustomMovementMode=1
            self.w.update();self.assertEqual(self.w.calls['root'],before,gate)
            self.assertEqual(self.owner._root_height_state['filtered_z'],0,gate)

    def test_mantle_gate_and_missing_root_are_inert(self):
        self.owner._camera_frame={};self.owner._mantle_camera_state['active']=True
        root_height.prepare(self.owner,self.w.pc,self.w.pawn,self.w.camera)
        self.assertEqual(self.w.calls['root'],0)
        self.setUp();self.w.mesh.DoesSocketExist=lambda name:False
        self.run_frames();self.assertEqual(self.w.calls['root'],0)
        self.assertEqual(self.owner._root_height_state['status'],'missing_root')

    def test_invalid_floor_bone_and_rotation_decline_finitely(self):
        for bad in ('nanroot','huge','nanfloor','floorblock','pitch','roll'):
            self.setUp()
            if bad=='nanroot':self.w.values['root']=float('nan')
            if bad=='huge':self.w.values['root']-=1000
            if bad=='nanfloor':self.w.floor.FloorDist=float('nan')
            if bad=='floorblock':self.w.floor.bBlockingHit=False
            if bad=='pitch':
                self.lower();self.w.rotation.Pitch=float('inf')
            if bad=='roll':
                self.lower();self.w.rotation.Roll=400
            offset,state=self.w.update()
            self.assertEqual(state['status'],'declined',bad)
            self.assertTrue(all(math.isfinite(v) for v in offset))
            self.assertEqual(state['filtered_z'],0)

    def test_rebinding_expired_refs_and_sdk_reentry_discard_old_height(self):
        self.lower();self.run_frames()
        self.owner._root_height_state['refs']=(lambda:None,)*4
        self.w.values.update(root=898.,spine=1045.);_,state=self.w.update()
        self.assertEqual(state['filtered_z'],0)
        self.lower();original=self.w.mesh.GetSocketLocation
        def read(name):
            value=original(name)
            if name=='Root':self.w.runtime[0]=S(_get_address=lambda:100)
            return value
        self.w.mesh.GetSocketLocation=read
        offset,state=self.w.update()
        self.assertEqual(state['filtered_z'],0)
        self.assertEqual(offset,(45,55,10))
        self.assertIsNone(self.owner._camera_frame)

    def test_unscoped_setter_has_no_height_and_declines_foreign_runtime(self):
        self.lower();self.run_frames()
        self.owner._set_camera_offset(0,0,0)
        self.assertEqual(self.w.camera.CameraModeState.CameraLocationOffset.Z,0)
        self.owner._camera_frame={'height_refs':self.owner._root_height_state['refs'],
                                 'height_local':(0,0,-44)}
        self.assertEqual(root_height.compensate(self.owner,None,self.w.pawn,self.w.camera,(0,0,0)),(0,0,0))
        self.owner.root_height_enabled.value=False
        self.assertEqual(root_height.compensate(self.owner,self.w.pc,self.w.pawn,self.w.camera,(0,0,0)),(0,0,0))

    def test_replay_three_measured_captures_keeps_drop_and_restores_ground(self):
        fixture=json.loads((ROOT/'tests/fixtures/root_height_0_3_9_34.json').read_text())
        for label,data in fixture['captures'].items():
            self.setUp();outputs=[]
            for az,mz,rz,sz,fd,mode,pitch,roll in data['samples']:
                self.w.values.update(actor=az,mesh=mz,root=rz,spine=sz)
                self.w.floor.FloorDist=fd;self.w.movement.MovementMode=mode
                self.w.rotation.Pitch=pitch;self.w.rotation.Roll=roll
                offset,state=self.w.update();outputs.append(state.copy())
                self.assertTrue(all(math.isfinite(v) for v in offset))
                self.assertNotEqual(state['status'],'declined',label)
            if label=='gelaender':
                self.assertAlmostEqual(outputs[-1]['filtered_z'],-44.126,delta=.02)
            else:self.assertEqual(outputs[-1]['filtered_z'],0,label)
            if label=='wechsel':
                self.assertLess(outputs[240]['filtered_z'],-42)
                self.assertEqual(outputs[240]['target_z'],outputs[240]['raw_z'])
                self.assertEqual(outputs[280]['target_z'],0)

    def test_menu_click_changes_the_same_option_as_console(self):
        from BL4ThirdPersonPOC import menu_camera_features as menu
        calls=[]
        option=S(value=True)
        def setter(value):
            calls.append(value);option.value=value
        state={'camera_features':{'root_height':option,'set_root_height':setter,
                                 'categories':{}},'ads_page':0}
        with patch('BL4ThirdPersonPOC.menu_console.clicked',side_effect=lambda s,k:k=='feature:root_height'), patch.object(menu,'refresh'):
            menu.dispatch(state)
        self.assertEqual(calls,[False]);self.assertFalse(option.value)
        self.assertTrue(state['dirty'])

    def test_real_loader_option_command_scope_and_cleanup(self):
        result=subprocess.run([sys.executable,str(ROOT/'tests/root_height_loader_scenario.py')],
            cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertEqual(report['version'],'0.3.9.40')
        self.assertTrue(report['menu_option'])
        self.assertLess(report['on_z'],-30)
        self.assertEqual(report['off_z'],10)
        self.assertTrue(report['scope_cleared'])
        self.assertEqual(report['after_disable_z'],0)
