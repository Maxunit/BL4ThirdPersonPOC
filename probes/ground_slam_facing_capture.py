"""Read-only .38 Slam actor/mesh/bone facing capture; repeat PyExec/F10 to save."""
from datetime import datetime, timezone
from itertools import islice
import math
from pathlib import Path
import sys
from time import perf_counter_ns
from types import ModuleType

KEY = '_bl4tps_ground_slam_facing_capture'
TAG = '[BL4TPS.SlamFacing]'
MAX_SECONDS = 120
MAX_UPDATES = 8000


def angle(a, b):
    return (a - b + 180.) % 360. - 180.


def toggle():
    retained = sys.modules.get(KEY)
    old = getattr(retained, 'capture', None)
    if old is not None and (old.active or old.registered or not old.output_saved):
        old.finish('MANUAL_STOP')
        return
    mod = sys.modules.get('BL4ThirdPersonPOC')
    if mod is None or getattr(mod, 'MOD_VERSION', None) not in ('0.3.9.38', '0.3.9.39', '0.3.9.40', '0.3.9.41'):
        raise RuntimeError('Load BL4ThirdPersonPOC 0.3.9.38, .39, .40 or .41 first')
    from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
    from BL4ThirdPersonPOC.omni import profiler
    from BL4ThirdPersonPOC.omni.common import KEY as OMNI_KEY
    from unrealsdk.unreal import WeakPointer, BoundFunction
    if height._capture is not None or height._armed is not None:
        raise RuntimeError('Stop the current capture first (F10)')
    if profiler.status(mod)['state'] != 'off':
        raise RuntimeError('Stop the Omni profiler first')
    if runtime_updates._owner is None or not runtime_updates._owner.active:
        raise RuntimeError('Enable the mod in loaded gameplay first')

    class FacingCapture(height.Capture):
        def __init__(self):
            super().__init__(mod, 'slam_facing')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path = Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_facing_'+stamp+'.json')
            self.spec = (mod.FIRST_PERSON_ANIM_HOOK, height.hooks.Type.POST_UNCONDITIONAL,
                         'bl4tps.ground_slam_facing.capture')
            self.waiting = True
            self.armed_at = perf_counter_ns()
            self.last_detail = None
            self.getter_ref = None
            self.anim_ref = None
            self.output_saved = False
            self.previous = None
            self.report.update(probe='ground_slam_facing', limit=MAX_UPDATES,
                max_seconds=MAX_SECONDS, bone_detail_interval_ms=50, events=[],
                note='Read-only sequential owned-widget SDK observations. Actor yaw '
                     'and live Slam state every update; mesh and Root/Spine/Head world '
                     'rotations at most 20 Hz. World bone Euler yaw can be ambiguous '
                     'near vertical pitch; horizontal-forward length is included. '
                     'No proof of animation/render ordering or the identity of a '
                     'native writer. No settings/actor/animation/camera writes, native '
                     'access, new producer or timer. Diagnostic overhead is not FPS.')

        def bind_getter(self):
            fn = self.owner(1).Class._find('IsPerformingGroundSlam')
            props = list(islice(fn._properties(), 3))
            if (str(fn._path_name()) != '/Script/OakGame.OakCharacter:IsPerformingGroundSlam'
                    or not int(fn.FunctionFlags) & 0x10000000 or int(fn.NumParams) != 1
                    or len(props) != 1 or str(props[0].Class.Name) != 'BoolProperty'
                    or not int(props[0].PropertyFlags) & 0x400):
                raise RuntimeError('Reviewed pure Slam getter differs')
            self.getter_ref = WeakPointer(fn)
            self.anim_ref = WeakPointer(self.owner(3).AnimScriptInstance)

        def anim(self):
            anim = self.anim_ref()
            if anim is None or self.owner(3).AnimScriptInstance != anim:
                raise height.OwnerChanged('Facing animation owner changed')
            return anim

        def bone(self, name, actor_yaw):
            rotation = height.coords(self.owner(3).GetSocketRotation(name), ('Pitch', 'Yaw', 'Roll'))
            horizontal = abs(math.cos(math.radians(rotation['Pitch'])))
            return dict(world_rotation=rotation, yaw_minus_actor=angle(rotation['Yaw'], actor_yaw),
                        horizontal_forward_length=horizontal, yaw_well_projected=horizontal > .2)

        def omni_state(self):
            owner = getattr(mod, OMNI_KEY, None)
            child = getattr(owner, 'child', None)
            if child is None or not getattr(child, 'active', False):
                return dict(active=False)
            refs = tuple(ref() for ref in child.refs)
            current = self.current()
            if len(refs) != 4 or refs != (*current[:3], current[4]):
                raise height.OwnerChanged('Facing Omni owner changed')
            return dict(active=True, native_slam_pose=bool(child.ground_slam_pose_native),
                gates=dict(turn=int(child.native.control[0]), turn_replace=int(child.native.control[7]),
                    idle_root=int(child.idle_native.control[0]), idle_update=int(child.idle_update.control[0]),
                    aim=int(child.aim_native.control[0]), crouch_aim=int(child.aim_native.crouch_control[0])),
                last_exit_observation=height.plain(child.report.get('ground_slam_native_ab_rows', [])[-1:]))

        def read_facing(self, tick):
            pc, pawn, camera, mesh, movement = self.current()
            fn = self.getter_ref()
            if fn is None:
                raise height.OwnerChanged('Facing getter metadata expired')
            active = BoundFunction(fn, pawn)()
            if not isinstance(active, bool):
                raise RuntimeError('Slam getter returned a non-bool')
            actor = height.coords(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            row = dict(update=self.frames+1, elapsed_ms=(tick-self.started)/1e6,
                slam_active=active, camera_mode=str(camera.GetActorCameraMode(pawn)),
                camera_transitioning=bool(camera.CameraModeState.bIsTransitioning),
                actor_rotation=actor, movement_mode=int(movement.MovementMode),
                custom_movement_mode=int(movement.CustomMovementMode), omni=self.omni_state())
            if self.previous is not None:
                row['actor_yaw_step'] = angle(actor['Yaw'], self.previous['actor_rotation']['Yaw'])
            if self.last_detail is None or tick-self.last_detail >= 50_000_000:
                self.last_detail = tick
                row['camera_rotation'] = height.coords(camera.GetCameraRotation(), ('Pitch', 'Yaw', 'Roll'))
                row['control_rotation'] = height.coords(pc.GetControlRotation(), ('Pitch', 'Yaw', 'Roll'))
                row['mesh_world_rotation'] = self.optional('mesh_world_rotation', lambda:
                    height.coords(self.owner(3).K2_GetComponentRotation(), ('Pitch', 'Yaw', 'Roll')))
                row['mesh_relative_rotation'] = height.coords(mesh.RelativeRotation, ('Pitch', 'Yaw', 'Roll'))
                row['bone_rotations'] = {name:self.optional('rotation_'+name, lambda name=name:
                    self.bone(name, actor['Yaw'])) for name in ('Spine3', *self.bones)
                    if name in ('Root', 'Spine3', 'Spine5', 'Head')}
                row['animation_aim'] = self.optional('animation_aim', lambda:dict(
                    yaw=height.finite(self.anim().AimYaw), pitch=height.finite(self.anim().AimPitch)))
                child = getattr(getattr(mod, OMNI_KEY, None), 'child', None)
                if child is not None and row['omni']['active']:
                    row['existing_exit_rotation_arguments'] = height.plain(
                        child.report.get('ground_slam_native_records', [])[-2:])
                row['camera_minus_actor'] = angle(row['camera_rotation']['Yaw'], actor['Yaw'])
            self.current();self.anim()
            row['read_cost_ms'] = (perf_counter_ns()-tick)/1e6
            return row

        def frame(self, obj, args, ret, func):
            if not runtime_updates.is_game_thread():
                return
            try:
                tick = perf_counter_ns()
                if (tick-self.armed_at)/1e9 >= MAX_SECONDS:
                    self.try_finish('TIME_LIMIT');return
                if self.waiting:
                    pc, pawn, camera = mod._get_runtime()
                    if (any(o is None for o in (pc, pawn, camera)) or not mod._third_person_enabled
                            or pc.bShowMouseCursor or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson'):
                        return
                    runtime_updates.remove_hook(*self.spec)
                    if runtime_updates.has_hook(*self.spec):
                        raise RuntimeError('Facing arming detach failed')
                    self.registered = False
                    self.started = tick
                    super().start()
                    self.bind_getter()
                    self.waiting = False
                    mod.logging.warning(TAG+' RECORDING limit=8000/120s; perform the opposite-facing Slam, then repeat PyExec/F10.')
                    return
                if not self.active:return
                if not mod._third_person_enabled or getattr(mod, '_vehicle_camera_active', False):
                    self.try_finish('TPS_DISABLED_OR_VEHICLE');return
                row = self.read_facing(tick)
                phase = (row['slam_active'], row['camera_mode'], row['camera_transitioning'])
                if self.previous is None or phase != self.previous['_phase']:
                    self.report['events'].append(dict(update=row['update'],elapsed_ms=row['elapsed_ms'],
                        slam_active=row['slam_active'],mode=row['camera_mode'],
                        transitioning=row['camera_transitioning'],actor_yaw=row['actor_rotation']['Yaw']))
                row['_phase'] = phase
                self.report['samples'].append(row)
                self.previous = row
                self.frames += 1
                if self.frames >= MAX_UPDATES:self.try_finish('UPDATE_LIMIT')
            except Exception as exc:
                self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                self.try_finish('READ_OR_START_FAILED')

        def finish(self, reason):
            self.waiting = False
            for row in self.report['samples']:row.pop('_phase', None)
            super().finish(reason)
            self.output_saved = height._last['status'] != 'OUTPUT_FAILED'
            if self.output_saved:mod.logging.warning(TAG+' SAVED '+str(self.path))

    capture = FacingCapture()
    retained = ModuleType(KEY);retained.capture = capture;sys.modules[KEY] = retained
    height._capture = capture
    try:
        capture.registered = True
        capture.report['sdk_hooks_peak'] = capture.report['sdk_hooks'] = 1
        runtime_updates.add_hook(*capture.spec, capture.frame)
        if not runtime_updates.has_hook(*capture.spec):raise RuntimeError('Facing arming registration failed')
        mod.logging.warning(TAG+' ARMED; close console; repeat PyExec/F10 stops; maximum 120 s or 8000 updates.')
    except Exception:
        capture.finish('ARM_FAILED')
        raise


toggle()
