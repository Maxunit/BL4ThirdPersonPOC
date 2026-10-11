"""Actual .36 loader, camera scope, setter, menu option and shutdown."""
import json
from types import SimpleNamespace as S
from unittest.mock import patch
import loader_harness as h


def run():
    mod=h.load()
    from root_height_world import world
    from BL4ThirdPersonPOC import ground_slam_distance as d, runtime_updates
    source,w=world()
    for key in ('_get_runtime','_third_person_enabled','_third_person_pushed',
                '_vehicle_camera_active','_shop_camera_active','_slide_active','_ladder_active',
                '_ads_active','_ads_route','_camera_lifecycle','_camera_offset_gate_last',
                '_dynamic_motion_enabled','_ffyl_camera_active','_looks_like_first_person_fallback',
                '_camera_lifecycle_offset_suppressed','camera_offset_x','camera_offset_y','camera_offset_z'):
        setattr(mod,key,getattr(source,key))
    mod._dynamic_motion_enabled=False
    mod._dynamic_motion_reset();mod._reset_mantle_camera_state()
    w.movement.Velocity=S(Z=0.)
    w.pawn.CapsuleComponent=S(K2_GetComponentLocation=lambda:S(X=0.,Y=0.,Z=w.values['actor']),
                            GetScaledCapsuleHalfHeight=lambda:100.)
    slam=False
    w.pawn.IsPerformingGroundSlam=lambda:slam
    getter=S(_path_name=lambda:'/Script/OakGame.OakCharacter:IsPerformingGroundSlam',
             FunctionFlags=0x10000000,NumParams=1,_properties=lambda:iter((
             S(Class=S(Name='BoolProperty'),PropertyFlags=0x400),)))
    w.pawn.Class=S(_find=lambda name:getter)
    names=('WorldContextObject','Start','End','TraceChannel','bTraceComplex','ActorsToIgnore',
           'DrawDebugType','OutHit','bIgnoreSelf','TraceColor','TraceHitColor','DrawTime','ReturnValue')
    props=[S(Name=n,Class=S(Name='OtherProperty')) for n in names]
    props[-1].Class.Name='BoolProperty';props[7].Struct=S(_path_name=lambda:'/Script/Engine.HitResult')
    fn=S(NumParams=13,_properties=lambda:iter(props))
    lib=S(Class=S(_find=lambda name:fn),LineTraceSingle=lambda *args:(True,S(
          ImpactPoint=S(Z=898.),ImpactNormal=S(Z=1.),bBlockingHit=True,bStartPenetrating=False)))
    def frame():
        d.pre_frame(mod,S(InDeltaTime=1/60))
        mod._apply_camera_offset()
        mod._slam_distance_pending=False
        v=w.camera.CameraModeState.CameraLocationOffset
        raw=v.X,v.Y,v.Z
        v.X-=256.
        assert mod._camera_frame is None
        return raw
    with patch.object(runtime_updates,'is_game_thread',return_value=True),patch.object(d,'find_object',return_value=lib):
        for _ in range(5):frame()
        assert mod._ground_slam_distance_state.shift==-256.
        w.movement.MovementMode=3;w.movement.Velocity.Z=-5000.;slam=True
        w.values.update(actor=4000.,mesh=3900.,root=3900.,spine=4047.)
        for _ in range(48):far=frame()
        assert far==(-105.,55.,10.),far
        # Disabling Root still leaves the live Slam distance camera scope valid.
        mod.root_height_enabled.value=False
        assert frame()==far
        w.values.update(actor=1178.,mesh=1078.,root=1078.,spine=1225.)
        near=frame();assert near==(45.,55.,10.),near
        assert mod._ground_slam_distance_state.amount==0.
        w.movement.MovementMode=1;slam=False
        # Existing loader shutdown must retire the distance state before native owners.
        mod._third_person_pushed=False
        mod._on_disable()
        assert mod._ground_slam_distance_state is None
    assert mod.ground_slam_distance_cm.value==150.
    assert mod._camera_feature_options['slam_distance'] is mod.ground_slam_distance_cm
    return dict(version=mod.MOD_VERSION,far=far,near=near,scope_cleared=True,default=150.,shutdown=True)


if __name__=='__main__':print(json.dumps(run()))
