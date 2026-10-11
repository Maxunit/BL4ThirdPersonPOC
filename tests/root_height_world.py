"""Replayable SDK world for the real offset/mantle/motion functions."""
from collections import Counter
import inspect
from types import SimpleNamespace as S
from BL4ThirdPersonPOC import camera_math as cm, root_height, motion_settings


def point(z=0):
    return S(X=0.,Y=0.,Z=float(z))


def world():
    calls=Counter();values=dict(actor=1000.,mesh=900.,root=898.,spine=1045.)
    def read(key):
        calls[key]+=1
        return point(values[key])
    def bone(name):
        return read('root' if name=='Root' else 'spine')
    mesh=S(_get_address=lambda:4,K2_GetComponentLocation=lambda:read('mesh'),
           DoesSocketExist=lambda name: calls.update(['exists']) or name=='Root',
           GetSocketLocation=bone)
    floor=S(bBlockingHit=True,bWalkableFloor=True,FloorDist=2.)
    movement=S(MovementMode=1,CustomMovementMode=0,CurrentFloor=floor,
               IsFalling=lambda:movement.MovementMode==3,
               IsMovingOnGround=lambda:movement.MovementMode==1)
    pawn=S(_get_address=lambda:2,Mesh=mesh,OakCharacterMovement=movement,
           CharacterMovement=movement,bIsCrouched=False,
           K2_GetActorLocation=lambda:read('actor'),GetVelocity=lambda:point())
    rotation=S(Pitch=0.,Yaw=0.,Roll=0.,pitch=0.,yaw=0.,roll=0.)
    camera=S(_get_address=lambda:3,CameraModeState=S(POV=S(Rotation=rotation),
        bIsTransitioning=False),CameraCachePrivate=S(POV=S(Rotation=rotation)))
    camera.GetActorCameraMode=lambda p: calls.update(['camera_mode']) or 'ThirdPerson'
    pc=S(_get_address=lambda:1,bShowMouseCursor=False)
    runtime=[pc,pawn,camera]
    owner=S(root_height_enabled=S(value=True),_camera_frame=None,_root_height_state={},
            _dynamic_motion_state={},_mantle_camera_state={},
            _third_person_enabled=True,_third_person_pushed=True,
            _vehicle_camera_active=False,_shop_camera_active=False,_slide_active=False,
            _ladder_active=False,_ads_active=False,_ads_route='hip',
            _camera_lifecycle={},_camera_offset_gate_last='',_dynamic_motion_enabled=True,
            camera_offset_x=S(value=45.),camera_offset_y=S(value=55.),camera_offset_z=S(value=10.),
            _get_runtime=lambda:calls.update(['runtime']) or tuple(runtime),_looks_like_first_person_fallback=lambda:False,
            _camera_lifecycle_offset_suppressed=lambda:False,
            _ffyl_camera_active=lambda p,c:False)
    import unrealsdk
    owner.logging=unrealsdk.logging
    root_height.reset(owner)
    owner._dynamic_motion_reset=lambda:cm._dynamic_motion_reset_impl(owner_module=owner)
    owner._reset_mantle_camera_state=lambda:cm._reset_mantle_camera_state_impl(owner_module=owner)
    owner._dynamic_motion_reset();owner._reset_mantle_camera_state()
    owner._set_camera_offset=lambda *v:calls.update(['offset_setter']) or cm._set_camera_offset_impl(*v,owner_module=owner)
    keys=('_mantle_camera_state','_third_person_enabled','_third_person_pushed',
          '_vehicle_camera_active','_shop_camera_active','_slide_active','_ladder_active',
          '_camera_lifecycle','_set_camera_offset','camera_offset_x','camera_offset_y','camera_offset_z')
    sample_arg = '_camera_frame' in inspect.signature(cm._apply_mantle_camera_offset).parameters
    def mantle(p,c):
        cm._apply_mantle_camera_offset(p,c,**{k:getattr(owner,k) for k in keys},
            _reset_mantle_camera_state=owner._reset_mantle_camera_state,
            **({'_camera_frame':owner._camera_frame} if sample_arg else {}))
    def motion(p,c):
        cm._apply_dynamic_motion_camera_offset(p,c,**{k:getattr(owner,k) for k in keys},
            _dynamic_motion_enabled=owner._dynamic_motion_enabled,_ads_active=owner._ads_active,
            _looks_like_first_person_fallback=owner._looks_like_first_person_fallback,
            _dynamic_motion_state=owner._dynamic_motion_state,
            _dynamic_motion_reset=owner._dynamic_motion_reset,
            motion_parameters=motion_settings.DEFAULTS,
            **({'_camera_frame':owner._camera_frame} if sample_arg else {}))
    owner._apply_mantle_camera_offset=mantle;owner._apply_dynamic_motion_camera_offset=motion
    def update():
        owner._camera_frame={} if owner.root_height_enabled.value else None
        try:
            cm._apply_camera_offset_impl(owner_module=owner)
            offset=camera.CameraModeState.CameraLocationOffset
            return (offset.X,offset.Y,offset.Z),root_height.snapshot(owner)
        finally:
            if owner._camera_frame is None or not owner._camera_frame.get('height_visited'):
                root_height.reset(owner)
            owner._camera_frame=None
    return owner,S(values=values,calls=calls,mesh=mesh,pawn=pawn,movement=movement,
                   floor=floor,camera=camera,pc=pc,rotation=rotation,runtime=runtime,update=update)
