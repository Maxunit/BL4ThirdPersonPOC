"""BL4ThirdPersonPOC 0.3.9.35: read-only PyExec Slam signal capture.

Put in your usual PyExec folder (or use the file's absolute path).
Run: pyexec ground_slam_signal_capture.py
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


KEY = '_bl4tps_ground_slam_signal_capture'
MAX_SECONDS = 180
MAX_UPDATES = 16000
DETAIL_INTERVAL_NS = 50_000_000
MATCH = re.compile(r'slam|ground.?pound|in.?air|airborne|falling|landing|'
                   r'locomotion.?state|movement.?state|movement.?mode', re.I)
SCALARS = frozenset(('BoolProperty', 'ByteProperty', 'EnumProperty',
                     'IntProperty', 'Int64Property', 'UInt32Property',
                     'FloatProperty', 'DoubleProperty'))
TAG = '[BL4TPS.SlamSignals]'
PURE_FLAG = 0x10000000
RETURN_FLAG = 0x400
BOOL_GETTERS = frozenset(('isgroundslamming','isgroundslamactive',
                         'isingroundslam','isperforminggroundslam'))
EVENT_MATCH = re.compile(r'start|stop|begin|end|enter|exit|perform|slammed',re.I)


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
    from unrealsdk.unreal import BoundFunction
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
            super().__init__(mod, 'slam_signals')
            stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path = Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_signals_'+stamp+'.json')
            self.spec = (mod.FIRST_PERSON_ANIM_HOOK, height.hooks.Type.POST_UNCONDITIONAL,
                         'bl4tps.ground_slam_signals.capture')
            self.output_saved = False
            self.waiting = True
            self.armed_at = perf_counter_ns()
            self.last_detail_at = None
            self.animation_ref = None
            self.fields = []
            self.disabled_reads = set()
            self.previous_state = None
            self.signal_specs = []
            self.getters = []
            self.function_targets = {}
            self.report.update(probe='ground_slam_signals', limit=MAX_UPDATES,
                max_seconds=MAX_SECONDS, detail_interval_ms=DETAIL_INTERVAL_NS/1e6,
                safety_limits_include_arming_wait=True, field_schema=[], events=[],
                functions=[], delegates=[], signal_events=[], skipped_worker_events=0,
                signal_event_limit=2048, signal_events_dropped=0,
                signal_note='Observe calls to reflected Slam functions and existing '
                            'delegate listeners. A listener may also be invoked by another '
                            'source, and a Start function may reject an attempt. Correlate '
                            'markers with validated pure boolean getters and body/movement. '
                            'Delegate signatures alone are not broadcast notifications. '
                            'No delegates are called, bound, unbound or modified.',
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
                {'controller':0, 'pawn':1, 'movement':4}[name])

        def function_schema(self, fn):
            path = str(fn._path_name())
            hook_path = path if ':' in path else ':'.join(path.rsplit('.',1))
            properties = list(islice(fn._properties(),33))
            if len(properties)>32:
                raise RuntimeError('Signal function parameter limit')
            return dict(name=str(fn.Name), path=path, hook_path=hook_path,
                flags=int(fn.FunctionFlags), num_params=int(fn.NumParams),
                params=[dict(name=str(p.Name),kind=str(p.Class.Name),
                             flags=int(p.PropertyFlags)) for p in properties])

        def observe_function(self, fn, target, source):
            info = self.function_schema(fn)
            path = info['hook_path']
            if ':' not in path:
                raise RuntimeError('Reflected signal function path has no owner')
            if len(self.function_targets)>=12 and path not in self.function_targets:
                self.report.setdefault('signal_hook_limit_reached',True)
                return
            ref = WeakPointer(target)
            entries = self.function_targets.setdefault(path,[])
            entries.append((ref, source, info))

        def discover_signals(self):
            seen = set()
            for name in ('pawn','movement','animation','controller'):
                target = self.target(name)
                if target is None:
                    continue
                parents = list(islice(target.Class._superfields(),65))
                if len(parents)>64:
                    raise RuntimeError('Signal inheritance limit')
                for cls in (target.Class,*parents):
                    for index,fn in enumerate(cls._fields()):
                        if index>=4096:
                            raise RuntimeError('Signal function discovery limit')
                        if str(fn.Class.Name) != 'Function' or 'slam' not in str(fn.Name).lower():
                            continue
                        key=(name,str(fn._path_name()))
                        if key in seen:
                            continue
                        seen.add(key)
                        info = self.function_schema(fn)
                        info['owner'] = name
                        if len(self.report['functions'])>=128:
                            raise RuntimeError('Signal function inventory limit')
                        self.report['functions'].append(info)
                        lower = info['name'].lower()
                        params = info['params']
                        getter = (lower in BOOL_GETTERS and info['flags'] & PURE_FLAG and
                            info['num_params']==1 and len(params)==1 and
                            params[0]['kind']=='BoolProperty' and
                            params[0]['flags'] & RETURN_FLAG)
                        if getter and len(self.getters)<8:
                            self.getters.append((name,WeakPointer(fn),info['name']))
                            info['observed_as'] = 'validated_pure_boolean_getter'
                        elif (not lower.startswith(('get','is','can','has','set')) and
                              'delegatesignature' not in lower and EVENT_MATCH.search(lower)):
                            self.observe_function(fn,target,dict(kind='slam_function',owner=name))
                            info['observed_as'] = 'call_marker'
                        else:
                            info['observed_as'] = 'metadata_only'
            # Enumerate pre-existing listeners. Reading/iterating this SDK
            # wrapper does not modify its invocation list. Never call it.
            for name in ('pawn','movement','animation','controller'):
                target = self.target(name)
                if target is None:
                    continue
                for field in ('OnStartGroundSlam','OnStopGroundSlam'):
                    schema_entry = next((p for cls in (target.Class,*tuple(
                        islice(target.Class._superfields(),65))) for p in islice(cls._properties(),4096)
                        if str(p.Name)==field),None)
                    if schema_entry is None or str(schema_entry.Class.Name) not in (
                        'MulticastInlineDelegateProperty','MulticastDelegateProperty',
                        'MulticastSparseDelegateProperty'):
                        continue
                    self.soft('delegate:'+name+'.'+field,
                              lambda name=name,field=field:self.describe_delegate(name,field))
            for index,(path,entries) in enumerate(self.function_targets.items()):
                spec=(path,height.hooks.Type.POST_UNCONDITIONAL,
                      'bl4tps.ground_slam_signals.event.'+str(index))
                if height.hooks.has_hook(*spec):
                    raise RuntimeError('Signal hook identifier already registered')
                self.signal_specs.append(spec) # includes partial add failures
                height.hooks.add_hook(*spec,self.signal_callback(path))
                if not height.hooks.has_hook(*spec):
                    raise RuntimeError('Signal hook registration unverified')
                self.report['sdk_hooks_peak'] = self.report['sdk_hooks'] = 1+len(self.signal_specs)

        def describe_delegate(self,name,field):
            delegate = getattr(self.target(name),field)
            entry = dict(owner=name,field=field,bindings=[],
                         signature=self.function_schema(delegate._signature))
            self.report['delegates'].append(entry)
            bindings = list(islice(iter(delegate),17))
            if len(bindings)>16:
                entry['binding_limit_reached'] = True
                bindings = bindings[:16]
            for bound in bindings:
                ref = WeakPointer(bound.object)
                obj = ref()
                if obj is None:
                    continue
                info = self.function_schema(bound.func)
                entry['bindings'].append(dict(object=str(obj._path_name()),function=info))
                self.observe_function(bound.func,obj,dict(kind='existing_delegate_listener',
                    delegate_owner=name,delegate_field=field))

        def signal_callback(self,path):
            def callback(obj,args,ret,func):
                if not self.active or self.waiting:
                    return
                if not runtime_updates.is_game_thread():
                    self.report['skipped_worker_events'] += 1
                    return
                # Do not call game getters from a ProcessEvent callback. Only
                # weak identity and reflected scalar argument reads here.
                matched = [entry for entry in self.function_targets[path]
                           if entry[0]() is not None and entry[0]()==obj]
                if not matched:
                    return
                if len(self.report['signal_events'])>=2048:
                    self.report['signal_events_dropped'] += 1
                    return
                event = dict(elapsed_ms=(perf_counter_ns()-self.started)/1e6,
                             last_completed_update=self.frames,path=path,
                             sources=[entry[1] for entry in matched],args={})
                for parameter in matched[0][2]['params']:
                    key,kind = parameter['name'],parameter['kind']
                    if parameter['flags'] & RETURN_FLAG or kind not in SCALARS:
                        continue
                    def read(key=key,kind=kind):
                        value = getattr(args,key)
                        if kind=='BoolProperty':return bool(value)
                        if kind in ('ByteProperty','EnumProperty'):
                            return dict(text=str(value)[:160],value=int(value))
                        if kind in ('FloatProperty','DoubleProperty'):return height.finite(value)
                        return int(value)
                    event['args'][key] = self.soft('event_arg:'+path+':'+key,read)
                self.report['signal_events'].append(event)
            return callback

        def getter_values(self):
            values = {}
            for name,ref,field in self.getters:
                def read(name=name,ref=ref):
                    fn = ref()
                    if fn is None:
                        raise ValueError('Getter function metadata expired')
                    obj = self.target(name)
                    if obj is None:
                        raise height.OwnerChanged('Getter target expired')
                    value = BoundFunction(fn,obj)()
                    if not isinstance(value,bool):
                        raise ValueError('Validated boolean getter returned non-boolean')
                    return value
                values[name+'.'+field] = self.soft('getter:'+name+'.'+field,read)
            return values

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
                candidates=self.field_values(), slam_getters=self.getter_values(),montage=self.montage())
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
                    self.discover_signals()
                    self.report['configured_offset'] = self.soft('configured_offset',lambda:{
                        axis:height.finite(getattr(mod,'camera_offset_'+axis).value) for axis in 'xyz'})
                    self.report['features_at_start'] = {key:bool(getattr(mod,key,False)) for key in (
                        '_dynamic_motion_enabled','_ads_active')}
                    self.report['features_at_start']['omni_enabled'] = bool(
                        mod.omni_movement_experimental.value)
                    mod.logging.warning(TAG+' RECORDING signals; '+str(len(self.signal_specs))+
                        ' observer hooks, '+str(len(self.getters))+' pure getters; repeat PyExec/F10 to save.')
                    return
                if not self.active:
                    return
                if not mod._third_person_enabled or bool(getattr(mod,'_vehicle_camera_active',False)):
                    self.try_finish('TPS_DISABLED_OR_VEHICLE')
                    return
                row = self.read_row()
                state = dict(camera_mode=row['camera_mode'], camera_flags=row['camera_flags'],
                    movement_mode=row['movement_mode'],custom_movement_mode=row['custom_movement_mode'],
                    mouse_cursor=row['mouse_cursor'],candidates=row['candidates'],slam_getters=row['slam_getters'],
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
            self.active = False
            # The singleton remains owned if any observer cannot detach, so
            # rerunning PyExec/off retries and mod shutdown cannot proceed.
            for spec in list(self.signal_specs):
                if height.hooks.has_hook(*spec):
                    height.hooks.remove_hook(*spec)
                if height.hooks.has_hook(*spec):
                    raise RuntimeError('Signal observer removal unverified; retry PyExec/off')
                self.signal_specs.remove(spec)
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
