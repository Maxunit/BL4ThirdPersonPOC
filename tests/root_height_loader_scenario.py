"""Real loader option, menu binding, console and scoped camera setter."""
import json
from unittest.mock import patch
import loader_harness as h


def run():
    mod=h.load()
    # Import this fixture only after the actual loader is loaded (support's SDK stubs).
    from root_height_world import world
    from BL4ThirdPersonPOC import root_height
    source,w=world()
    for key in ('_get_runtime','_third_person_enabled','_third_person_pushed',
                '_vehicle_camera_active','_shop_camera_active','_slide_active','_ladder_active',
                '_ads_active','_ads_route','_camera_lifecycle','_camera_offset_gate_last',
                '_dynamic_motion_enabled','_ffyl_camera_active','_looks_like_first_person_fallback',
                '_camera_lifecycle_offset_suppressed','camera_offset_x','camera_offset_y','camera_offset_z'):
        setattr(mod,key,getattr(source,key))
    mod._dynamic_motion_reset();mod._reset_mantle_camera_state()
    w.values.update(root=854.,spine=1001.)
    mod.root_height_console.run('on')
    for _ in range(120):mod._apply_camera_offset()
    on_z=w.camera.CameraModeState.CameraLocationOffset.Z
    scope_cleared=mod._camera_frame is None
    with patch('BL4ThirdPersonPOC.shoulder_blend.begin',side_effect=RuntimeError('scope start')):
        try:mod._apply_camera_offset()
        except RuntimeError:pass
        else:raise AssertionError('Scope-start failure was not exercised')
    assert mod._camera_frame is None
    mod._camera_feature_options['set_root_height'](False)
    mod._apply_camera_offset();off_z=w.camera.CameraModeState.CameraLocationOffset.Z
    mod.root_height_console.run('status')
    mod.root_height_console.run('on');mod._apply_camera_offset()
    # Native owners are inert in the stub environment; test actual shutdown reset.
    mod._third_person_pushed=False
    mod._on_disable()
    return dict(version=mod.MOD_VERSION,on_z=on_z,off_z=off_z,scope_cleared=scope_cleared,
        menu_option=mod._camera_feature_options['root_height'] is mod.root_height_enabled,
        after_disable_z=root_height.snapshot(mod)['filtered_z'])


if __name__=='__main__':print(json.dumps(run()))
