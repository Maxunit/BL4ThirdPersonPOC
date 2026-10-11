"""Import actual loader and route console/F10 into actual gameplay frame root."""
import json
from pathlib import Path
from types import SimpleNamespace as S

import loader_harness as h


def run():
    mod = h.load()
    from BL4ThirdPersonPOC.omni import profiler
    from BL4ThirdPersonPOC.omni.session import GameplaySession
    from BL4ThirdPersonPOC.omni.common import KEY
    from BL4ThirdPersonPOC.omni.sampling import SamplingMixin

    movement = S()
    pawn = S(OakCharacterMovement=movement, IsCharacterDashing=lambda: False)
    pc = S(bShowMouseCursor=False)
    camera = S(GetActorCameraMode=lambda pawn: 'ThirdPerson')
    mod._get_runtime = lambda: (pc, pawn, camera)
    mod._native_read = lambda address, size: bytes(size)
    original_read, original_bound = mod._native_read, SamplingMixin.bound
    mod._third_person_enabled = mod._third_person_pushed = True
    child = GameplaySession.__new__(GameplaySession)
    child.mod = mod
    child.active, child.busy, child.lifecycle_managed = True, False, True
    child.updates = S(is_game_thread=lambda: True)
    child.refs = tuple(lambda obj=obj: obj for obj in (pc, pawn, camera, movement))
    child.frames = 100
    child.inputs = S(begin_frame=lambda **kw: None, end_frame=lambda: None)
    child.disarm_ground_vector = lambda: None
    child.ground_clip_originals = []
    child.report = dict(samples=[], lifecycle_session_sequence=1, native_patches=0)
    def leaf(*args):
        child.bound()
        mod._native_read(0x10000, 8)
        child.frames += 1
        child.report['samples'] = [dict(normal_tps_sample=True, movement_input_active=False,
                                       horizontal_speed=0., update_index=child.frames)]
    child._ground_pose_frame = leaf  # other gameplay work is outside this wiring test
    state = S(active=True, child=child, sequence=1, diagnostics=False, updates=child.updates)
    setattr(mod, KEY, state)
    mod.omni_movement_console(S(action='profile', value='detail', extra='idle'))
    assert profiler.status(mod)['state'] == 'armed'
    assert SamplingMixin.bound is original_bound
    mod.dump_gameplay_debug_state()
    assert profiler.status(mod)['state'] == 'running'
    assert SamplingMixin.bound is not original_bound
    for _ in range(600):
        child.frame(None, None, None, None)
    assert profiler.status(mod)['state'] == 'off'
    assert SamplingMixin.bound is original_bound and mod._native_read is original_read
    report = json.loads(Path(profiler._last['path']).read_text())
    assert report['completed_updates'] == 600
    assert report['states'] == {'idle': 600}
    assert report['stages']['runtime.bound']['calls'] == 1200
    assert report['native_reads']['calls'] == 600
    assert not any(level == 'error' for level, message in h.LOG), h.LOG
    return dict(version=mod.MOD_VERSION, updates=600, restored=True)


if __name__ == '__main__':
    print(json.dumps(run()))
