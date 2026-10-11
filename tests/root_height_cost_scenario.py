"""Count selected real-camera SDK calls; excludes properties/weak checks and FPS."""
import importlib.util,json,sys
from pathlib import Path
import support
from BL4ThirdPersonPOC import camera_math, camera_events, hybrid_ads, shoulder_blend
import root_height_world


def run(module,enabled,motion,drop):
    root_height_world.cm=module
    owner,w=root_height_world.world()
    owner.root_height_enabled.value=enabled;owner._dynamic_motion_enabled=motion
    owner._ffyl_camera_active=lambda p,c:camera_events._ffyl_camera_active_impl(p,c,owner_module=owner)
    w.values.update(root=898.-drop,spine=1045.-drop)
    hybrid_ads.reset();shoulder_blend.reset()
    for _ in range(180):w.update()
    w.calls.clear()
    for _ in range(600):w.update()
    return dict(updates=600,selected_calls=dict(w.calls),
                selected_ufunctions=sum(w.calls[k] for k in ('actor','mesh','root','spine','camera_mode','exists')),
                final_offset_z=w.camera.CameraModeState.CameraLocationOffset.Z)


def main():
    base=Path(sys.argv[1])/'BL4ThirdPersonPOC/camera_math.py'
    spec=importlib.util.spec_from_file_location('BL4ThirdPersonPOC.camera_math_34',base)
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    out={'note':'Synthetic selected calls only: no property/weak/native counts or FPS.', 'scenarios':{}}
    for motion in (False,True):
        for name,drop in (('ground',0),('perch',44)):
            out['scenarios'][name+('_motion_on' if motion else '_motion_off')]={
              '0.3.9.34':run(legacy,False,motion,drop),
              '0.3.9.35_on':run(camera_math,True,motion,drop),
              '0.3.9.35_off':run(camera_math,False,motion,drop)}
    print(json.dumps(out,indent=2))


if __name__=='__main__':main()
