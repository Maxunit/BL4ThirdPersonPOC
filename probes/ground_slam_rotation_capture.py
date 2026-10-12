"""Observe .38 Slam rotation requests using the already installed owned recorder."""
from datetime import datetime, timezone
from itertools import islice
import math
import ctypes
import struct
from pathlib import Path
import sys
from time import perf_counter_ns
from types import ModuleType

KEY = '_bl4tps_ground_slam_rotation_capture'
TAG = '[BL4TPS.SlamRotation]'
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
    if mod is None or getattr(mod, 'MOD_VERSION', None) != '0.3.9.38':
        raise RuntimeError('Load BL4ThirdPersonPOC 0.3.9.38 first')
    from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
    from BL4ThirdPersonPOC.omni import profiler
    from BL4ThirdPersonPOC.omni.common import KEY as OMNI_KEY, quat
    from BL4ThirdPersonPOC.omni.native_rotation import NativeTrace, CAPACITY, RECORD_SIZE
    from unrealsdk.unreal import WeakPointer, BoundFunction
    if height._capture is not None or height._armed is not None:
        raise RuntimeError('Stop the current capture first (F10)')
    if profiler.status(mod)['state'] != 'off':
        raise RuntimeError('Stop the Omni profiler first')
    if runtime_updates._owner is None or not runtime_updates._owner.active:
        raise RuntimeError('Enable .38 in loaded gameplay first')

    class RotationCapture(height.Capture):
        def __init__(self):
            super().__init__(mod, 'slam_rotation')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path = Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_rotation_'+stamp+'.json')
            self.spec = (mod.FIRST_PERSON_ANIM_HOOK, height.hooks.Type.POST_UNCONDITIONAL,
                         'bl4tps.ground_slam_rotation.capture')
            self.waiting = True
            self.armed_at = perf_counter_ns()
            self.last_detail = None
            self.getter_ref = None
            self.anim_ref = None
            self.output_saved = False
            self.previous = None
            self.native_owner = None
            self.child_owner = None
            self.native_cursor = 0
            self.record_gate_owned = False
            self.report.update(probe='ground_slam_rotation', limit=MAX_UPDATES,
                rotation_requests=[], recorder_gate_writes=0, native_record_capacity=CAPACITY,
                max_seconds=MAX_SECONDS, bone_detail_interval_ms=50, events=[],
                note='SDK actor/mesh facing plus bounded copies of the existing owned '
                     'NativeTrace recorder buffer. Temporarily enables only its diagnostic '
                     'recording gate around normal TPS (including the airborne Slam). '
                     'Production retains Exit recording. No rotation, animation, camera '
                     'or settings writes, new native patch, producer or timer. Native '
                     'reads validate the already installed hook and local owner. Requests '
                     'are originals before existing Omni replacement; they do not prove '
                     'the call succeeded. Other rotation paths may bypass this dispatcher. '
                     'Widget observations bound an interval, not exact native timestamps. '
                     'A zero count cannot exclude a writer. Diagnostic overhead is not FPS.')

        def bind_recorder(self):
            child = getattr(getattr(mod, OMNI_KEY, None), 'child', None)
            native = getattr(child, 'native', None)
            if child is None or not child.active or not isinstance(native, NativeTrace):
                raise RuntimeError('Enable fully bound .38 Omni before this probe')
            if native.hook is None or native.hook.get('restored'):
                raise RuntimeError('Owned rotation recorder is not installed')
            self.child_owner, self.native_owner = child, native
            self.check_recorder()
            self.native_cursor = int(native.slide_control[5])
            if not 0 <= self.native_cursor < CAPACITY:
                raise RuntimeError('Recorder already full; restart the game before capturing')
            self.report['native_record_start_index'] = self.native_cursor

        def check_recorder(self):
            self.current()
            child, native = self.child_owner, self.native_owner
            if (getattr(getattr(mod, OMNI_KEY, None), 'child', None) is not child
                    or not child.active or child.native is not native
                    or tuple(ref() for ref in child.refs) != (*self.current()[:3], self.current()[4])
                    or native.hook is None or native.hook.get('restored')):
                raise height.OwnerChanged('Rotation recorder owner changed')
            control = native.slide_control
            if (len(control) != 7 or len(native.slide_buffer) != CAPACITY*RECORD_SIZE
                    or int(control[4]) != ctypes.addressof(native.slide_buffer)
                    or tuple(control[i] for i in (1,2,3)) != tuple(native.control[i] for i in (1,2,3))
                    or int(control[1]) != int(self.owner(4)._get_address())):
                raise height.OwnerChanged('Owned recorder buffer/control differs')
            before = child.report.get('native_reads', 0)
            try:
                native.validate()
                if native.read(native.hook['target'], len(native.hook['patch'])) != native.hook['patch']:
                    raise height.OwnerChanged('Installed recorder patch differs')
            finally:
                self.report['native_reads'] += child.report.get('native_reads', 0)-before
            return child, native

        def copy_requests(self):
            child, native = self.check_recorder()
            count = int(native.slide_control[5])
            if not self.native_cursor <= count <= CAPACITY:
                raise RuntimeError('Owned record count reset or out of bounds')
            for index in range(self.native_cursor, count):
                raw = bytes(native.slide_buffer[index*RECORD_SIZE:(index+1)*RECORD_SIZE])
                committed, caller, component, flags = struct.unpack_from('<4Q', raw)
                if committed != 1 or component != native.component:
                    raise RuntimeError('Native record commit/component differs')
                if not 0 <= caller-native.base < 0x31B8C000:
                    raise RuntimeError('Native caller outside reviewed game image')
                requested, root = quat(raw[32:64]), quat(raw[64:96])
                for value in (requested, root):
                    q = value.get('xyzw', ())
                    if len(q) != 4 or not all(math.isfinite(v) for v in q) or not .99 <= sum(v*v for v in q) <= 1.01:
                        raise RuntimeError('Native recorded quaternion invalid')
                delta = struct.unpack_from('<3d', raw, 96)
                row = dict(index=index, caller_return_rva=hex(caller-native.base),
                    from_turn_state=caller-native.base == 0x2E2E17,
                    requested_quaternion=requested, root_quaternion_before_call=root,
                    requested_minus_root=angle(requested['yaw'], root['yaw']),
                    sweep_argument_low_byte=flags & 0xff,
                    delta_xyz=list(delta) if all(math.isfinite(v) for v in delta) else None,
                    last_widget_update_index=struct.unpack_from('<Q', raw, 120)[0],
                    observed_after_probe_update=self.frames,
                    observed_before_probe_update=self.frames+1)
                self.report['rotation_requests'].append(row)
            self.native_cursor = count
            self.report['native_record_capacity_reached'] = count == CAPACITY
            return count == CAPACITY

        def arm_record_gate(self, row):
            child, native = self.check_recorder()
            mode = row['camera_mode']
            if mode == 'GroundSlamExit':
                # The production observer owns the recording flag in Exit.
                self.record_gate_owned = False
                return
            if mode != 'ThirdPerson' or self.owner(0).bShowMouseCursor or any(
                    bool(getattr(mod, name, False)) for name in (
                        '_ads_active', '_vehicle_camera_active', '_shop_camera_active',
                        '_ladder_active', '_slide_active')):
                self.try_finish('UNSUPPORTED_CONTEXT');return
            if row['slam_active'] and any(row['omni']['gates'].values()):
                raise RuntimeError('Native Slam behavioral overrides were not released')
            native.slide_control[0] = 1
            self.report['recorder_gate_writes'] += 1
            self.record_gate_owned = True

        def close_record_gate(self):
            if not self.record_gate_owned:
                return
            native, child = self.native_owner, self.child_owner
            # Only Python-owned storage captured at binding; never a UObject
            # address. A stopped/replaced owner may have a pinned old buffer,
            # whose flag must also remain closed. Preserve an active production
            # Exit recording window if it took over since our last observation.
            if not (child.active and child.native is native
                    and getattr(getattr(mod, OMNI_KEY, None), 'child', None) is child
                    and child.slam_trace_window):
                native.slide_control[0] = 0
                self.report['recorder_gate_writes'] += 1
            self.record_gate_owned = False

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
                raise height.OwnerChanged('Rotation Omni owner changed')
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
                        raise RuntimeError('Rotation arming detach failed')
                    self.registered = False
                    self.started = tick
                    super().start()
                    self.bind_getter()
                    self.bind_recorder()
                    self.waiting = False
                    self.arm_record_gate(dict(camera_mode='ThirdPerson', slam_active=False))
                    mod.logging.warning(TAG+' RECORDING limit=8000/120s; perform the opposite-facing Slam, then repeat PyExec/F10.')
                    return
                if not self.active:return
                if not mod._third_person_enabled or getattr(mod, '_vehicle_camera_active', False):
                    self.try_finish('TPS_DISABLED_OR_VEHICLE');return
                full = self.copy_requests()
                row = self.read_facing(tick)
                row['omni_update'] = self.child_owner.frames
                row['record_count'] = self.native_cursor
                row['recorder_gate_before_probe'] = int(self.native_owner.slide_control[0])
                phase = (row['slam_active'], row['camera_mode'], row['camera_transitioning'])
                if self.previous is None or phase != self.previous['_phase']:
                    self.report['events'].append(dict(update=row['update'],elapsed_ms=row['elapsed_ms'],
                        slam_active=row['slam_active'],mode=row['camera_mode'],
                        transitioning=row['camera_transitioning'],actor_yaw=row['actor_rotation']['Yaw']))
                row['_phase'] = phase
                self.report['samples'].append(row)
                self.previous = row
                self.frames += 1
                if full:
                    self.try_finish('RECORD_CAPACITY');return
                self.arm_record_gate(row)
                if self.frames >= MAX_UPDATES:self.try_finish('UPDATE_LIMIT')
            except Exception as exc:
                self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                self.try_finish('READ_OR_START_FAILED')

        def finish(self, reason):
            if self.record_gate_owned and not runtime_updates.is_game_thread():
                raise RuntimeError('Close the recorder on the owned game thread; use F10')
            self.close_record_gate()
            if self.active and self.native_owner is not None:
                try:self.copy_requests()
                except Exception as exc:
                    self.report['errors'].append('Final record copy: '+str(exc)[:250])
            self.report['rotation_request_count'] = len(self.report['rotation_requests'])
            self.waiting = False
            for row in self.report['samples']:row.pop('_phase', None)
            super().finish(reason)
            self.output_saved = height._last['status'] != 'OUTPUT_FAILED'
            if self.output_saved:mod.logging.warning(TAG+' SAVED '+str(self.path))

    capture = RotationCapture()
    retained = ModuleType(KEY);retained.capture = capture;sys.modules[KEY] = retained
    height._capture = capture
    try:
        capture.registered = True
        capture.report['sdk_hooks_peak'] = capture.report['sdk_hooks'] = 1
        runtime_updates.add_hook(*capture.spec, capture.frame)
        if not runtime_updates.has_hook(*capture.spec):raise RuntimeError('Rotation arming registration failed')
        mod.logging.warning(TAG+' ARMED; close console; repeat PyExec/F10 stops; maximum 120 s or 8000 updates.')
    except Exception:
        capture.finish('ARM_FAILED')
        raise


toggle()
