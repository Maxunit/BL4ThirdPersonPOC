"""BL4ThirdPersonPOC 0.3.9.35: standalone read-only PyExec Slam capture.

Put in your usual PyExec folder (or use the file's absolute path).
Run: pyexec ground_slam_phase_capture.py
Close the console, record idle -> jump -> Slam -> exit -> idle.
Run the same command again to stop and write JSON. F10 also stops this probe.
Safety limits: 180 seconds or 16000 owned updates. No native access or writes
to game state. Uses the installed mod's diagnostic cleanup and update route.
"""
from datetime import datetime, timezone
from itertools import islice
import math
from pathlib import Path
import re
import sys
from time import perf_counter_ns
from types import ModuleType


KEY = '_bl4tps_ground_slam_phase_capture'
MAX_SECONDS = 180
MAX_UPDATES = 16000
DETAIL_INTERVAL_NS = 50_000_000
MATCH = re.compile(r'slam|ground.?pound|in.?air|airborne|falling|landing|'
                   r'locomotion.?state|movement.?state|movement.?mode', re.I)
SCALARS = frozenset(('BoolProperty', 'ByteProperty', 'EnumProperty',
                     'IntProperty', 'Int64Property', 'UInt32Property',
                     'FloatProperty', 'DoubleProperty'))
TAG = '[BL4TPS.SlamPhases]'


def phase_summary(rows):
    """Report observed camera intervals, without claiming gameplay semantics."""
    segments = []
    for row_index, row in enumerate(rows):
        mode = row['camera_mode']
        if not segments or segments[-1]['mode'] != mode:
            previous = rows[row_index-1] if row_index else row
            segments.append(dict(mode=mode, first_observed_ms=row['elapsed_ms'],
                                 entry_bracket_ms=[previous['elapsed_ms'], row['elapsed_ms']],
                                 last_observed_ms=row['elapsed_ms'], updates=0))
        segment = segments[-1]
        segment['last_observed_ms'] = row['elapsed_ms']
        segment['updates'] += 1
    for index, segment in enumerate(segments):
        segment['observed_span_ms'] = segment['last_observed_ms']-segment['first_observed_ms']
        if index+1 < len(segments):
            segment['exit_bracket_ms'] = segments[index+1]['entry_bracket_ms']
    gaps = [b['elapsed_ms']-a['elapsed_ms'] for a,b in zip(rows, rows[1:])]
    return dict(camera_segments=segments,
                first_observed_ground_slam_ms=next((r['elapsed_ms'] for r in rows
                                                   if r['camera_mode']=='GroundSlam'), None),
                first_observed_ground_slam_exit_ms=next((r['elapsed_ms'] for r in rows
                                                   if r['camera_mode']=='GroundSlamExit'), None),
                maximum_sample_gap_ms=max(gaps, default=0),
                interpretation='Camera mode boundaries are observations, not proof of '
                               'Slam admission, physical impact or character action end. '
                               'Correlate candidate fields, montage, movement and camera.')


def toggle():
    # The retained module survives PyExec's temporary globals. Retry an earlier
    # failed detach/output before starting any second capture.
    retained = sys.modules.get(KEY)
    old = getattr(retained, 'capture', None)
    if old is not None and (old.registered or old.active or not old.output_saved):
        old.finish('MANUAL_STOP')
        return

    mod = sys.modules.get('BL4ThirdPersonPOC')
    if mod is None or getattr(mod, 'MOD_VERSION', None) != '0.3.9.35':
        raise RuntimeError('This probe requires the loaded BL4ThirdPersonPOC 0.3.9.35.')
    from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
    from BL4ThirdPersonPOC.omni import profiler
    from unrealsdk.unreal import WeakPointer

    if height._capture is not None or height._armed is not None:
        raise RuntimeError('Stop the existing height capture before starting this probe.')
    if profiler.status(mod)['state'] != 'off':
        raise RuntimeError('Stop the Omni profiler before starting this probe.')
    producer = runtime_updates._owner
    if producer is None or not producer.active:
        raise RuntimeError('Enable the mod and enter loaded gameplay first.')

    class SlamCapture(height.Capture):
        def __init__(self):
            super().__init__(mod, 'slam_phases')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path = Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_phases_'+stamp+'.json')
            self.spec = (mod.FIRST_PERSON_ANIM_HOOK, height.hooks.Type.POST_UNCONDITIONAL,
                         'bl4tps.ground_slam_phases.capture')
            self.output_saved = False
            self.waiting = True
            self.armed_at = perf_counter_ns()
            self.last_detail_at = None
            self.animation_ref = None
            self.fields = []
            self.disabled_reads = set()
            self.previous_state = None
            self.report.update(probe='ground_slam_phases', limit=MAX_UPDATES,
                max_seconds=MAX_SECONDS, detail_interval_ms=DETAIL_INTERVAL_NS/1e6,
                safety_limits_include_arming_wait=True, field_schema=[], events=[],
                note='Sequential read-only SDK observations on the existing owned widget '
                     'update. Core state every observed update; camera/body detail at most '
                     '20 Hz. No timer, new producer, input simulation, gameplay/camera '
                     'writes or native access. Not an FPS benchmark. Reflected field '
                     'names alone do not establish their gameplay meaning.')

        def soft(self, key, read):
            if key in self.disabled_reads:
                return None
            try:
                return read()
            except height.OwnerChanged:
                raise
            except Exception as exc:
                self.disabled_reads.add(key)
                self.report['optional_errors'][key] = dict(count=1,
                    error=type(exc).__name__+': '+str(exc)[:200], disabled_after_error=True)
                return None

        def animation_owner(self):
            if self.animation_ref is None:
                return None
            anim = self.animation_ref()
            if anim is None or self.owner(3).AnimScriptInstance != anim:
                raise height.OwnerChanged('Slam animation instance expired/replaced')
            return anim

        def target(self, name):
            return self.animation_owner() if name=='animation' else self.owner(
                {'pawn':1, 'movement':4}[name])

        def discover(self, name, schema, path=()):
            if schema is None or len(self.fields) >= 64:
                return
            parents = list(islice(schema._superfields(), 65))
            if len(parents) > 64:
                raise RuntimeError('Reflection inheritance limit')
            seen = set()
            for owner in (schema, *parents):
                for index, prop in enumerate(owner._properties()):
                    if index >= 4096:
                        raise RuntimeError('Reflection property limit')
                    field, kind = str(prop.Name), str(prop.Class.Name)
                    if field in seen:
                        continue
                    seen.add(field)
                    if not path and not MATCH.search(field):
                        continue
                    field_path = (*path, field)
                    entry = dict(owner=name, path='.'.join(field_path), kind=kind)
                    if len(self.report['field_schema']) < 256:
                        self.report['field_schema'].append(entry)
                    if kind in SCALARS:
                        self.fields.append((name, field_path, kind))
                        entry['sampled'] = True
                    elif kind == 'StructProperty' and len(path) < 2:
                        self.discover(name, prop.Struct, field_path)
                    # Never follow arbitrary object references or call guessed functions.
                    if len(self.fields) >= 64:
                        return

        def field_values(self):
            result = {}
            for name, path, kind in self.fields:
                key = name+'.'+'.'.join(path)
                def read(name=name, path=path, kind=kind):
                    value = self.target(name)
                    for field in path:
                        value = getattr(value, field)
                    if kind == 'BoolProperty':
                        return bool(value)
                    if kind in ('EnumProperty', 'ByteProperty'):
                        return dict(text=str(value)[:160], value=int(value))
                    if kind in ('FloatProperty', 'DoubleProperty'):
                        return height.finite(value)
                    return int(value)
                result[key] = self.soft('field:'+key, read)
            return result

        def montage(self):
            anim = self.animation_owner()
            if anim is None:
                return None
            montage = self.soft('current_montage',lambda:self.animation_owner().GetCurrentActiveMontage())
            if montage is None:
                return None
            ref = WeakPointer(montage)
            def read():
                current = ref()
                if current is None:
                    raise ValueError('Montage expired during observation')
                path = str(current._path_name())
                current = ref()
                if current is None:
                    raise ValueError('Montage expired during observation')
                position = height.finite(self.animation_owner().Montage_GetPosition(current))
                return dict(path=path, position_seconds=position)
            return self.soft('montage_details', read)

        def read_row(self):
            tick = perf_counter_ns()
            self.current()
            actor = height.coords(self.owner(1).K2_GetActorLocation())
            movement = self.owner(4)
            row = dict(update=self.frames+1, elapsed_ms=(tick-self.started)/1e6,
                camera_mode=str(self.owner(2).GetActorCameraMode(self.owner(1))),
                actor_location=actor, movement_mode=int(movement.MovementMode),
                custom_movement_mode=int(movement.CustomMovementMode),
                velocity=height.coords(movement.Velocity),
                floor=self.soft('floor', lambda:dict(
                    blocking=bool(self.owner(4).CurrentFloor.bBlockingHit),
                    walkable=bool(self.owner(4).CurrentFloor.bWalkableFloor),
                    floor_dist=height.finite(self.owner(4).CurrentFloor.FloorDist))),
                camera_flags=self.soft('camera_flags', lambda:dict(
                    transitioning=bool(self.owner(2).CameraModeState.bIsTransitioning),
                    colliding=bool(self.owner(2).CameraModeState.bIsColliding))),
                mouse_cursor=bool(self.owner(0).bShowMouseCursor),
                candidates=self.field_values(), montage=self.montage())
            if self.last_detail_at is None or tick-self.last_detail_at >= DETAIL_INTERVAL_NS:
                self.last_detail_at = tick
                row['camera_cache'] = self.soft('camera_cache',lambda:self.camera_pov('CameraCachePrivate'))
                row['camera_state'] = self.soft('camera_state',lambda:self.camera_pov('CameraModeState'))
                row['applied_offset'] = self.soft('applied_offset',lambda:height.coords(
                    self.owner(2).CameraModeState.CameraLocationOffset))
                row['spine_location'] = self.soft('spine',lambda:height.coords(
                    self.owner(3).GetSocketLocation('Spine3')))
                row['root_height'] = height.plain(getattr(mod,'_root_height_state',{}))
                row['motion'] = height.plain(getattr(mod,'_dynamic_motion_state',{}))
                cache = row['camera_cache']
                if cache is not None:
                    delta = {axis:cache['location'][axis]-actor[axis] for axis in 'XYZ'}
                    row['relative'] = dict(camera_actor_z=delta['Z'],
                        camera_actor_distance=math.sqrt(sum(v*v for v in delta.values())))
                    spine = row['spine_location']
                    if spine is not None:
                        row['relative']['camera_spine_z'] = cache['location']['Z']-spine['Z']
                        row['relative']['spine_actor_z'] = spine['Z']-actor['Z']
            self.current()
            self.animation_owner()
            row['read_cost_ms'] = (perf_counter_ns()-tick)/1e6
            return row

        def frame(self, obj, args, ret, func):
            if not runtime_updates.is_game_thread():
                return
            try:
                if (perf_counter_ns()-self.armed_at)/1e9 >= MAX_SECONDS:
                    self.try_finish('TIME_LIMIT')
                    return
                if self.waiting:
                    pc,pawn,camera = mod._get_runtime()
                    if (any(o is None for o in (pc,pawn,camera)) or
                        not mod._third_person_enabled or bool(pc.bShowMouseCursor) or
                        str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson'):
                        return
                    runtime_updates.remove_hook(*self.spec)
                    if runtime_updates.has_hook(*self.spec):
                        raise RuntimeError('Arming subscription removal failed')
                    self.registered = False
                    self.started = perf_counter_ns()
                    super().start()
                    self.waiting = False
                    anim = self.soft('animation_binding',lambda:self.owner(3).AnimScriptInstance)
                    if anim is not None:
                        self.animation_ref = WeakPointer(anim)
                    for name in ('pawn','movement','animation'):
                        def layout(name=name):
                            target = self.target(name)
                            if target is not None:
                                self.discover(name,target.Class)
                        self.soft('schema:'+name,layout)
                    self.report['configured_offset'] = self.soft('configured_offset',lambda:{
                        axis:height.finite(getattr(mod,'camera_offset_'+axis).value) for axis in 'xyz'})
                    self.report['features_at_start'] = {key:bool(getattr(mod,key,False)) for key in (
                        '_dynamic_motion_enabled','_ads_active')}
                    self.report['features_at_start']['omni_enabled'] = bool(
                        mod.omni_movement_experimental.value)
                    mod.logging.warning(TAG+' RECORDING; repeat PyExec or press F10 to save JSON.')
                    return
                if not self.active:
                    return
                if not mod._third_person_enabled or bool(getattr(mod,'_vehicle_camera_active',False)):
                    self.try_finish('TPS_DISABLED_OR_VEHICLE')
                    return
                row = self.read_row()
                state = dict(camera_mode=row['camera_mode'], camera_flags=row['camera_flags'],
                    movement_mode=row['movement_mode'],custom_movement_mode=row['custom_movement_mode'],
                    mouse_cursor=row['mouse_cursor'],candidates=row['candidates'],
                    montage_path=(row['montage'] or {}).get('path'))
                if state != self.previous_state:
                    previous = self.report['samples'][-1] if self.report['samples'] else row
                    self.report['events'].append(dict(update=row['update'],
                        elapsed_ms=row['elapsed_ms'],
                        change_bracket_ms=[previous['elapsed_ms'],row['elapsed_ms']],state=state))
                    self.previous_state = state
                self.report['samples'].append(row)
                self.frames += 1
                if self.frames >= MAX_UPDATES:
                    self.try_finish('UPDATE_LIMIT')
            except Exception as exc:
                self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                self.try_finish('READ_OR_START_FAILED')

        def finish(self, reason):
            self.waiting = False
            try:
                self.report['phase_summary'] = phase_summary(self.report['samples'])
            except Exception as exc:
                self.report['errors'].append('SUMMARY_FAILED: '+type(exc).__name__+': '+str(exc)[:200])
            super().finish(reason)
            self.output_saved = height._last['status'] != 'OUTPUT_FAILED'
            if self.output_saved:
                mod.logging.warning(TAG+' SAVED '+str(self.path))

    capture = SlamCapture()
    retained = ModuleType(KEY)
    retained.capture = capture
    sys.modules[KEY] = retained
    # Adopt the installed diagnostic singleton: F10, console `off` and normal
    # mod shutdown all detach us before the owned producer is destroyed.
    height._capture = capture
    try:
        capture.registered = True
        capture.report['sdk_hooks_peak'] = capture.report['sdk_hooks'] = 1
        runtime_updates.add_hook(*capture.spec,capture.frame)
        if not runtime_updates.has_hook(*capture.spec):
            raise RuntimeError('Probe arming registration unverified')
        mod.logging.warning(TAG+' ARMED; close console. Repeat PyExec to stop; limit 180 s.')
    except Exception:
        capture.finish('ARM_FAILED')
        raise


toggle()
