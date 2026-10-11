"""Temporary camera-distance test for BL4ThirdPersonPOC 0.3.9.35.

pyexec ground_slam_distance_test.py toggles start / restore-and-save.
F10 also stops. Close other captures first. This probe deliberately changes
only CameraModeState.CameraLocationOffset: up to 80 units backwards during
the validated active Slam. Existing .35 camera transitions own GroundSlamExit.
No saved settings, FOV, character/animation writes, timers or native patches.
"""
from datetime import datetime, timezone
from itertools import islice
import json
import math
from pathlib import Path
import sys
from time import perf_counter_ns
from types import ModuleType

KEY = '_bl4tps_ground_slam_distance_test'
EXTRA_DISTANCE = 80.0
IN_RESPONSE_SECONDS = 0.08
OUT_RESPONSE_SECONDS = 0.06
MAX_SECONDS = 180
MAX_UPDATES = 16000
GETTER_PATH = '/Script/OakGame.OakCharacter:IsPerformingGroundSlam'
TAG = '[BL4TPS.SlamDistance]'


def approach(old,target,dt,response):
    if not all(math.isfinite(v) for v in (old,target,dt,response)) or response<=0:
        raise ValueError('Invalid distance interpolation')
    dt = max(0.,min(0.1,dt))
    value = old+(target-old)*(-math.expm1(-dt/response))
    return target if abs(value-target)<0.02 else value


def toggle():
    retained = sys.modules.get(KEY)
    old = getattr(retained,'capture',None)
    if old is not None and (old.registered or old.active or not old.output_saved):
        old.request_stop('MANUAL_STOP')
        return
    mod = sys.modules.get('BL4ThirdPersonPOC')
    if mod is None or getattr(mod,'MOD_VERSION',None)!='0.3.9.35':
        raise RuntimeError('This distance test requires loaded BL4ThirdPersonPOC 0.3.9.35.')
    from BL4ThirdPersonPOC import camera_height_capture as height, runtime_updates
    from BL4ThirdPersonPOC.omni import profiler
    from unrealsdk import make_struct
    from unrealsdk.unreal import WeakPointer,BoundFunction
    if height._capture is not None or height._armed is not None:
        raise RuntimeError('Stop the current diagnostic capture first (F10 / bl4tps_height off).')
    if profiler.status(mod)['state']!='off':
        raise RuntimeError('Stop the Omni profiler first.')
    if runtime_updates._owner is None or not runtime_updates._owner.active:
        raise RuntimeError('Enable .35 and load gameplay first.')

    class DistanceTest(height.Capture):
        def __init__(self):
            super().__init__(mod,'slam_distance_test')
            self.spec=(mod.FIRST_PERSON_ANIM_HOOK,height.hooks.Type.PRE,
                       'bl4tps.ground_slam_distance_test')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path=Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_distance_test_'+stamp+'.json')
            self.waiting=True
            self.armed_at=perf_counter_ns()
            self.previous_tick=None
            self.last_detail=None
            self.extra=0.
            self.phase='armed'
            self.last_phase=None
            self.original_setter=None
            self.wrapper=None
            self.getter_ref=None
            self.last_write=None
            self.output_saved=False
            self.stop_requested=None
            self.report.update(probe='ground_slam_distance_test',limit=MAX_UPDATES,
                max_seconds=MAX_SECONDS,extra_distance=EXTRA_DISTANCE,
                response_seconds=dict(entry=IN_RESPONSE_SECONDS,ordinary_tps_release=OUT_RESPONSE_SECONDS),
                camera_offsets_modified=0,camera_offsets_restored=0,events=[],
                settings_writes=0,animation_writes=0,character_writes=0,
                python_setter_wrapper_restored=False,
                note='Mutating A/B camera probe. Existing owned widget PRE drives '
                     'distance interpolation; ordinary .35 offset setters run unchanged '
                     'then their completed CameraLocationOffset receives one local-X '
                     'addition. Never cumulative across setters. Core state each update, '
                     'camera/body detail at most 20 Hz. PRE samples may show the previous '
                     'camera write. On GroundSlamExit remove only this extra offset; '
                     'existing .35 camera blend/body follow stays in control. '
                     'No FOV/settings/actor/animation/native changes. Not an FPS benchmark.')

        def permitted(self,pc,pawn,camera):
            if (not mod._third_person_enabled or not mod._third_person_pushed or
                any(bool(getattr(mod,key,False)) for key in ('_ads_active','_slide_active',
                    '_ladder_active','_vehicle_camera_active','_shop_camera_active')) or
                mod._camera_lifecycle.get('pending') or
                mod._camera_lifecycle.get('suppress_offsets') or
                mod._mantle_camera_state.get('active') or
                mod._mantle_camera_state.get('releasing') or bool(pc.bShowMouseCursor)):
                return False
            return not mod._looks_like_first_person_fallback()

        def same_runtime(self,objects):
            if len(self.refs)<3 or len(objects)!=3:
                return False
            return all(saved is not None and saved==current for saved,current in
                       zip((ref() for ref in self.refs[:3]),objects))

        def validate_getter(self):
            fn=self.owner(1).Class._find('IsPerformingGroundSlam')
            props=list(islice(fn._properties(),3))
            if (str(fn._path_name())!=GETTER_PATH or
                not int(fn.FunctionFlags)&0x10000000 or int(fn.NumParams)!=1 or
                len(props)!=1 or str(props[0].Class.Name)!='BoolProperty' or
                not int(props[0].PropertyFlags)&0x400):
                raise RuntimeError('Measured pure Slam getter signature differs')
            self.getter_ref=WeakPointer(fn)
            self.report['getter']=dict(path=GETTER_PATH,flags=int(fn.FunctionFlags))

        def slam_active(self):
            fn=self.getter_ref()
            if fn is None:
                raise height.OwnerChanged('Slam getter metadata expired')
            value=BoundFunction(fn,self.owner(1))()
            if not isinstance(value,bool):
                raise RuntimeError('Slam getter did not return bool')
            return value

        def install_wrapper(self):
            self.original_setter=mod._set_camera_offset
            def wrapped(x,y,z):
                result=self.original_setter(x,y,z)
                if not result or not self.active or self.extra<=0 or not runtime_updates.is_game_thread():
                    return result
                try:
                    pc,pawn,camera=mod._get_runtime()
                    if (not self.same_runtime((pc,pawn,camera)) or
                        not self.permitted(pc,pawn,camera) or
                        str(camera.GetActorCameraMode(pawn))!='ThirdPerson' or
                        bool(camera.CameraModeState.bIsTransitioning)):
                        return result
                    baseline=height.coords(camera.CameraModeState.CameraLocationOffset)
                    wanted=dict(baseline)
                    wanted['X']-=self.extra
                    if any(abs(v)>2048 for v in wanted.values()):
                        raise ValueError('Probe camera offset outside .35 bounds')
                    vector=make_struct('Vector',**wanted)
                    if not self.same_runtime(tuple(mod._get_runtime())):
                        raise height.OwnerChanged('Distance write runtime changed')
                    # Original setter replaced the offset from live profile/motion.
                    # Thus repeated writes apply extra once, never to our old output.
                    camera.CameraModeState.CameraLocationOffset=vector
                    self.last_write=dict(baseline=baseline,wanted=wanted)
                    self.report['camera_offsets_modified']+=1
                    self.report['game_writes']+=1
                except Exception as exc:
                    self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                    self.try_finish('OFFSET_FAILED')
                return result
            self.wrapper=wrapped
            mod._set_camera_offset=wrapped

        def restore_last(self):
            if self.last_write is None:
                return
            if not runtime_updates.is_game_thread():
                raise RuntimeError('Camera restoration needs the owned game thread')
            current=tuple(mod._get_runtime())
            if self.same_runtime(current):
                camera=current[2]
                actual=height.coords(camera.CameraModeState.CameraLocationOffset)
                wanted=self.last_write['wanted']
                if all(abs(actual[a]-wanted[a])<1e-6 for a in 'XYZ'):
                    vector=make_struct('Vector',**self.last_write['baseline'])
                    if not self.same_runtime(tuple(mod._get_runtime())):
                        raise height.OwnerChanged('Restore runtime changed')
                    actual=height.coords(camera.CameraModeState.CameraLocationOffset)
                    if all(abs(actual[a]-wanted[a])<1e-6 for a in 'XYZ'):
                        camera.CameraModeState.CameraLocationOffset=vector
                        self.report['camera_offsets_restored']+=1
                        self.report['game_writes']+=1
            # A replaced owner or newer write owns its own value. Never overwrite it.
            self.last_write=None

        def request_stop(self,reason):
            if self.last_write is not None and not runtime_updates.is_game_thread():
                self.stop_requested=reason
                mod.logging.warning(TAG+' STOP_QUEUED for next owned update')
                return
            self.finish(reason)

        def frame(self,obj,args,ret,func):
            if not runtime_updates.is_game_thread():
                return
            try:
                if self.stop_requested:
                    self.finish(self.stop_requested)
                    return
                tick=perf_counter_ns()
                if (tick-self.armed_at)/1e9>=MAX_SECONDS:
                    self.try_finish('TIME_LIMIT')
                    return
                if self.waiting:
                    pc,pawn,camera=mod._get_runtime()
                    if (any(o is None for o in (pc,pawn,camera)) or
                        not mod._third_person_enabled or bool(pc.bShowMouseCursor) or
                        str(camera.GetActorCameraMode(pawn))!='ThirdPerson'):
                        return
                    runtime_updates.remove_hook(*self.spec)
                    if runtime_updates.has_hook(*self.spec):
                        raise RuntimeError('Arming hook removal failed')
                    self.registered=False
                    self.started=tick
                    super().start()
                    self.validate_getter()
                    self.install_wrapper()
                    self.waiting=False
                    mod.logging.warning(TAG+' ACTIVE: max +80 cm during Slam; repeat PyExec/F10 restores and saves.')
                    return
                if not self.active:
                    return
                pc,pawn,camera,mesh,movement=self.current()
                if not mod._third_person_enabled or bool(mod._vehicle_camera_active):
                    self.try_finish('TPS_DISABLED_OR_VEHICLE')
                    return
                mode=str(camera.GetActorCameraMode(pawn))
                active=self.slam_active()
                self.current() # discard a state query that synchronously rebound runtime
                allowed=(mode=='ThirdPerson' and not bool(camera.CameraModeState.bIsTransitioning)
                         and self.permitted(pc,pawn,camera))
                dt=(tick-self.previous_tick)/1e9 if self.previous_tick is not None else 0.
                if args is not None:
                    delta=getattr(args,'InDeltaTime',None)
                    if delta is not None:
                        dt=height.finite(delta)
                self.previous_tick=tick
                if not allowed:
                    self.extra=0.
                    self.restore_last()
                    self.phase='exit_handoff' if mode=='GroundSlamExit' else 'suspended'
                else:
                    target=EXTRA_DISTANCE if active else 0.
                    self.extra=approach(self.extra,target,dt,
                        IN_RESPONSE_SECONDS if active else OUT_RESPONSE_SECONDS)
                    self.phase='slam' if active else 'release' if self.extra else 'idle'
                row=dict(update=self.frames+1,elapsed_ms=(tick-self.started)/1e6,
                    camera_mode=mode,slam_active=active,extra_distance=self.extra,
                    phase=self.phase,movement_mode=int(movement.MovementMode),
                    custom_movement_mode=int(movement.CustomMovementMode))
                phase=(mode,active,self.phase)
                if phase!=self.last_phase:
                    self.report['events'].append(dict(row))
                    self.last_phase=phase
                    if active or self.phase=='exit_handoff':
                        mod.logging.warning(TAG+' '+self.phase.upper()+' mode='+mode)
                if self.last_detail is None or tick-self.last_detail>=50_000_000:
                    self.last_detail=tick
                    row['applied_offset']=height.coords(camera.CameraModeState.CameraLocationOffset)
                    row['configured_offset']={a:height.finite(getattr(mod,'camera_offset_'+a).value) for a in 'xyz'}
                    row['camera_cache']=self.optional('camera_cache',lambda:self.camera_pov('CameraCachePrivate'))
                    row['actor_location']=height.coords(pawn.K2_GetActorLocation())
                    row['spine_location']=self.optional('spine',lambda:height.coords(mesh.GetSocketLocation('Spine3')))
                    row['motion']=height.plain(mod._dynamic_motion_state)
                    row['root_height']=height.plain(mod._root_height_state)
                self.current()
                row['read_cost_ms']=(perf_counter_ns()-tick)/1e6
                self.report['samples'].append(row)
                self.frames+=1
                if self.frames>=MAX_UPDATES:self.try_finish('UPDATE_LIMIT')
            except Exception as exc:
                self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                self.try_finish('READ_OR_START_FAILED')

        def finish(self,reason):
            if self.last_write is not None and not runtime_updates.is_game_thread():
                self.stop_requested=reason
                raise RuntimeError('Camera cleanup queued for next owned update')
            self.active=False
            self.waiting=False
            self.extra=0.
            if self.registered:
                runtime_updates.remove_hook(*self.spec)
                if runtime_updates.has_hook(*self.spec):
                    raise RuntimeError('Distance hook removal unverified; retry stop')
                self.registered=False
            self.restore_last()
            if self.wrapper is not None:
                if mod._set_camera_offset is self.wrapper:
                    mod._set_camera_offset=self.original_setter
                elif mod._set_camera_offset is not self.original_setter:
                    raise RuntimeError('Camera setter replaced by another owner; cannot restore safely')
            self.report['python_setter_wrapper_restored']=True
            self.report.update(status=reason,completed_updates=self.frames,sdk_hooks=0,
                               cleanup_complete=True,summary=height.summarize(self.report['samples']))
            # Use our own output/logging: the read-only helper's STOP log has
            # a literal game_writes=0, which would misdescribe this camera test.
            error=None
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                self.path.write_text(json.dumps(self.report,indent=2,ensure_ascii=False,
                                               allow_nan=False),encoding='utf-8')
            except Exception as exc:
                error=type(exc).__name__+': '+str(exc)[:200]
            self.output_saved=error is None
            height._last=dict(label=self.label,path=str(self.path),updates=self.frames,
                              status=reason if error is None else 'OUTPUT_FAILED')
            if height._capture is self:height._capture=None
            if error is None:
                mod.logging.warning(TAG+' RESTORED sdk_hooks=0 camera_writes='
                    +str(self.report['game_writes'])+' JSON '+str(self.path))
            else:
                height._last['error']=error
                mod.logging.error(TAG+' OUTPUT_FAILED after restore; retry PyExec: '+error)

    capture=DistanceTest()
    retained=ModuleType(KEY)
    retained.capture=capture
    sys.modules[KEY]=retained
    height._capture=capture
    try:
        capture.registered=True
        capture.report['sdk_hooks_peak']=capture.report['sdk_hooks']=1
        runtime_updates.add_hook(*capture.spec,capture.frame)
        if not runtime_updates.has_hook(*capture.spec):
            raise RuntimeError('Distance probe arming hook unverified')
        mod.logging.warning(TAG+' ARMED; close console. Repeat PyExec/F10 restores. Limit 180 s.')
    except Exception:
        capture.finish('ARM_FAILED')
        raise


toggle()
