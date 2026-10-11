"""Real loader console/F10 route, using the real existing widget subscriber."""
import json
import tempfile
from types import SimpleNamespace as S
import loader_harness as harness


def run():
    mod=harness.load()
    from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
    from test_camera_height_0_3_9_34 import runtime
    with tempfile.TemporaryDirectory() as directory:
        source,world=runtime(directory)
        for key in ('SETTINGS_DIR','_get_runtime','_third_person_enabled',
                    '_dynamic_motion_enabled','_dynamic_motion_state','_dynamic_motion_parameters',
                    'camera_offset_x','camera_offset_y','camera_offset_z'):
            setattr(mod,key,getattr(source,key))
        producer=runtime_updates.Owner(mod)
        producer.thread=int(mod._kernel32.GetCurrentThreadId())
        widget=S(Class=S(),_get_address=lambda:777)
        producer.widget_ref=lambda:widget
        producer.widget_address=777
        runtime_updates._owner=producer
        mod.camera_height_console.run('arm boden')
        assert height.status(mod)['state']=='armed'
        assert not producer.routes
        mod.dump_gameplay_debug_state()
        capture=height._capture
        assert capture is not None and capture.active
        assert len(producer.routes)==1
        route=next(iter(producer.routes.values()))
        route(S(_get_address=lambda:999),None,None,None)
        assert capture.frames==0
        for _ in range(600):route(widget,None,None,None)
        assert not producer.routes
        assert not height.trigger(mod)
        report=json.loads(capture.path.read_text())
        mod.camera_height_console.run('off')
        return dict(version=report['version'],updates=report['completed_updates'],
                    hooks=report['sdk_hooks'],game_writes=report['game_writes'])


if __name__=='__main__':print(json.dumps(run()))
