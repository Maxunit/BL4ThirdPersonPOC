"""Temporary camera-distance test v3 for BL4ThirdPersonPOC 0.3.9.35.

pyexec ground_slam_distance_test_v3.py toggles start / restore-and-save.
F10 also stops. Close other captures first. This probe deliberately changes
only CameraModeState.CameraLocationOffset: up to 80 units backwards during
the validated active Slam. Smooth exit edits only X in the already owned .35
runtime's Python control buffer, with exact prefix/layout/lifetime validation.
No saved settings, FOV, character/animation writes, timers or new native patches.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import math
from pathlib import Path
import sys
import struct
from time import perf_counter_ns
from types import ModuleType

KEY = '_bl4tps_ground_slam_distance_test_v3'
EXTRA_DISTANCE = 80.0
IN_RESPONSE_SECONDS = 0.08
OUT_RESPONSE_SECONDS = 0.06
EXIT_RESPONSE_SECONDS = 0.10
EXIT_OFFSET_PREFIX_SHA256 = '1f9f3cc3a0aaaacf18ff4f612d7c37a93b97ea7af867f94df5b2106f1cdabffb'
MAX_SECONDS = 180
MAX_UPDATES = 16000
GETTER_PATH = '/Script/OakGame.OakCharacter:IsPerformingGroundSlam'
TAG = '[BL4TPS.SlamDistanceV3]'


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
    from BL4ThirdPersonPOC import ground_slam_camera as exit_runtime
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
            super().__init__(mod,'slam_distance_test_v3')
            self.spec=(mod.FIRST_PERSON_ANIM_HOOK,height.hooks.Type.PRE,
                       'bl4tps.ground_slam_distance_test_v3')
            stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
            self.path=Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
                'ground_slam_distance_test_v3_'+stamp+'.json')
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
            self.offset_history=[]
            self.exit_bridge=None
            self.exit_wait_frames=0
            self.exit_declined=False
            self.handoff_pending=False
            self.previous_mode=None
            self.output_saved=False
            self.stop_requested=None
            self.report.update(probe='ground_slam_distance_test_v3',limit=MAX_UPDATES,
                max_seconds=MAX_SECONDS,extra_distance=EXTRA_DISTANCE,
                response_seconds=dict(entry=IN_RESPONSE_SECONDS,ordinary_tps_release=OUT_RESPONSE_SECONDS,
                                      ground_slam_exit=EXIT_RESPONSE_SECONDS),
                camera_offsets_modified=0,camera_offsets_restored=0,events=[],
                settings_writes=0,animation_writes=0,character_writes=0,
                python_setter_wrapper_restored=False,
                exit_control_writes=0,exit_control_restored=False,exit_bridge_status='unused',
                exit_diagnostics=[],offset_history_limit=1024,tps_handoff_fallbacks=0,
                note='Mutating A/B camera probe. Existing owned widget PRE drives '
                     'distance interpolation; ordinary .35 offset setters run unchanged '
                     'then their completed CameraLocationOffset receives one local-X '
                     'addition. Never cumulative across setters. Core state each update, '
                     'camera/body detail at most 20 Hz. PRE samples may show the previous '
                     'camera write. GroundSlamExit uses a captured composed offset: '
                     'v3 fades only our proven X contribution in that existing runtime\'s '
                     'Python-owned control buffer. No process memory reads/writes added, '
                     'machine code changes or new native hooks. Existing .35 native '
                     'consumer applies the updated target. Y/Z/body anchor/rotation stay '
                     'unchanged. An unmatched captured target stays untouched; fallback '
                     'holds the distance through Exit and fades it on TPS return through '
                     'the existing ordinary setter. That fallback returns later than the '
                     'preferred impact release. No FOV/settings/actor/animation changes. '
                     'Not an FPS benchmark.')

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
                        (bool(camera.CameraModeState.bIsTransitioning) and not self.handoff_pending)):
                        return result
                    baseline=height.coords(camera.CameraModeState.CameraLocationOffset)
                    wanted=dict(baseline)
                    wanted['X']-=self.extra
                    if any(abs(v)>512 for v in wanted.values()):
                        raise ValueError('Probe camera offset outside .35 Exit bounds')
                    vector=make_struct('Vector',**wanted)
                    if not self.same_runtime(tuple(mod._get_runtime())):
                        raise height.OwnerChanged('Distance write runtime changed')
                    # Original setter replaced the offset from live profile/motion.
                    # Thus repeated writes apply extra once, never to our old output.
                    camera.CameraModeState.CameraLocationOffset=vector
                    self.last_write=dict(baseline=baseline,wanted=wanted)
                    self.offset_history.append(dict(self.last_write))
                    del self.offset_history[:-1024]
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

        def exit_owner(self,state):
            if (not runtime_updates.is_game_thread() or not getattr(state,'active',False) or
                getattr(state,'mod',None) is not mod or getattr(state,'owner_invalidated',False)):
                return False
            current=tuple(mod._get_runtime())
            if not self.same_runtime(current) or not exit_runtime.owner_matches(state,current):
                return False
            buffer=state.modify
            if ctypes.sizeof(buffer)!=256 or ctypes.addressof(buffer)%8:
                raise RuntimeError('Owned Exit control buffer layout/alignment differs')
            if (struct.unpack_from('<I',buffer.raw,8)[0]!=1 or
                struct.unpack_from('<I',buffer.raw,184)[0]!=1):
                return False
            return True

        def bind_exit(self):
            if self.exit_declined:return False
            state=sys.modules.get(exit_runtime.KEY)
            if state is None or not self.exit_owner(state):
                self.report['exit_bridge_status']='waiting_for_owned_offset'
                return False
            if not struct.unpack_from('<Q',state.modify.raw,40)[0]:
                return False # no active private Exit runtime yet
            if (exit_runtime.OFFSET_PREFIX_SHA256!=EXIT_OFFSET_PREFIX_SHA256 or
                hashlib.sha256(exit_runtime.OFFSET_PREFIX).hexdigest()!=EXIT_OFFSET_PREFIX_SHA256):
                raise RuntimeError('Pinned .35 Exit offset consumer fingerprint differs')
            target=struct.unpack_from('<3d',state.modify.raw,160)
            if not all(math.isfinite(v) and abs(v)<=512 for v in target):
                raise RuntimeError('Owned Exit captured offset outside bounds')
            record=next((r for r in reversed(self.offset_history)
                         if abs(r['wanted']['X']-target[0])<1e-6),None)
            self.report['exit_diagnostics'].append(dict(native_target=list(target),
                sdk_offset=height.coords(self.owner(2).CameraModeState.CameraLocationOffset),
                recorded_writes=len(self.offset_history),
                recent_writes=[dict(base_x=r['baseline']['X'],wanted_x=r['wanted']['X'])
                               for r in self.offset_history[-12:]],
                first_writes=[dict(base_x=r['baseline']['X'],wanted_x=r['wanted']['X'])
                              for r in self.offset_history[:12]],matched=record is not None))
            if record is None:
                self.exit_declined=True
                self.handoff_pending=True
                self.report['exit_bridge_status']='unmatched_target_tps_fallback'
                self.report['tps_handoff_fallbacks']+=1
                mod.logging.warning(TAG+' EXIT_TARGET_UNMATCHED; keeping native target unchanged, smooth TPS return enabled')
                return False
            amount=record['baseline']['X']-record['wanted']['X']
            if not 0.<amount<=EXTRA_DISTANCE+1e-6:
                raise RuntimeError('Captured Exit distance contribution outside bounds')
            base_x=target[0]+amount
            if abs(base_x)>512:
                raise RuntimeError('Exit base X outside bounds')
            self.exit_bridge=dict(state=state,base_x=base_x,last_x=target[0],
                                  captured_yz=target[1:],released=False)
            self.extra=amount
            self.report['exit_bridge']=dict(captured_offset=list(target),base_x=base_x,
                                           captured_extra=amount,consumer_sha256=EXIT_OFFSET_PREFIX_SHA256)
            self.report['exit_bridge_status']='bound'
            return True

        def release_exit(self,dt):
            if self.exit_declined:return
            if self.exit_bridge is None and not self.bind_exit():
                if self.exit_declined:return
                self.exit_wait_frames+=1
                if self.exit_wait_frames>12:
                    self.exit_declined=True
                    self.handoff_pending=True
                    self.report['exit_bridge_status']='unavailable_target_tps_fallback'
                    self.report['tps_handoff_fallbacks']+=1
                return
            self.exit_wait_frames=0
            bridge=self.exit_bridge
            state=bridge['state']
            if not self.exit_owner(state):
                raise height.OwnerChanged('Exit distance owner expired/replaced')
            # A native restore may precede the SDK camera-mode name. Leave an
            # already neutral target alone during that short handoff interval.
            saved=struct.unpack_from('<Q',state.modify.raw,40)[0]
            if not saved:
                if self.extra>0.02:raise RuntimeError('Exit returned before distance release completed')
                return
            current_x=struct.unpack_from('<d',state.modify.raw,160)[0]
            if not math.isfinite(current_x) or abs(current_x-bridge['last_x'])>1e-6:
                raise RuntimeError('Exit X control has another writer')
            self.extra=approach(self.extra,0.,dt,EXIT_RESPONSE_SECONDS)
            target_x=bridge['base_x']-self.extra
            if not math.isfinite(target_x) or abs(target_x)>512:
                raise ValueError('Exit release target outside bounds')
            if target_x!=current_x:
                # This is the mod's own pinned Python control block, not a game
                # pointer or code patch. The existing guarded native consumer
                # already reads this double. Touch X only; preserve native Y/Z.
                struct.pack_into('<d',state.modify,160,target_x)
                bridge['last_x']=target_x
                self.report['exit_control_writes']+=1
            bridge['released']=self.extra==0.
            self.report['exit_bridge_status']='neutral' if bridge['released'] else 'releasing'

        def restore_exit(self):
            bridge=self.exit_bridge
            if bridge is None:return
            state=bridge['state']
            if self.exit_owner(state):
                current_x=struct.unpack_from('<d',state.modify.raw,160)[0]
                if not math.isfinite(current_x) or abs(current_x-bridge['last_x'])>1e-6:
                    raise RuntimeError('Cannot restore Exit X changed by another writer')
                if current_x!=bridge['base_x']:
                    struct.pack_into('<d',state.modify,160,bridge['base_x'])
                    self.report['exit_control_writes']+=1
                # Remove our remaining contribution if the native consumer has
                # already published it; keep the current body/shoulder Y and Z.
                camera=mod._get_runtime()[2]
                actual=height.coords(camera.CameraModeState.CameraLocationOffset)
                if (abs(actual['X']-bridge['last_x'])<1e-6 and
                    abs(actual['X']-bridge['base_x'])>1e-6):
                    actual['X']=bridge['base_x']
                    vector=make_struct('Vector',**actual)
                    if not self.same_runtime(tuple(mod._get_runtime())):
                        raise height.OwnerChanged('Exit restore runtime changed')
                    camera.CameraModeState.CameraLocationOffset=vector
                    self.report['camera_offsets_restored']+=1
                    self.report['game_writes']+=1
            self.report['exit_control_restored']=True
            self.exit_bridge=None

        def request_stop(self,reason):
            if (self.last_write is not None or self.exit_bridge is not None) and not runtime_updates.is_game_thread():
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
                returning=(mode=='ThirdPerson' and self.previous_mode=='GroundSlamExit')
                if mode!='GroundSlamExit' and self.exit_bridge is not None:
                    self.restore_exit()
                if mode=='GroundSlamExit' and not active and self.offset_history:
                    self.release_exit(dt)
                    self.phase=('exit_hold_for_tps' if self.exit_declined else
                                'exit_release' if self.extra else 'exit_settled')
                elif (mode=='ThirdPerson' and self.handoff_pending and not active and
                      self.permitted(pc,pawn,camera)):
                    # Keep the inherited distance on the first TPS write, then
                    # reduce it. Legitimate TPS transitions also receive this
                    # handoff, without admitting any FPS/ADS/foreign mode.
                    if not returning:
                        self.extra=approach(self.extra,0.,dt,EXIT_RESPONSE_SECONDS)
                    self.phase='tps_release' if self.extra else 'idle'
                    if not self.extra:self.handoff_pending=False
                elif not allowed:
                    self.extra=0.
                    self.handoff_pending=False
                    if self.exit_bridge is not None:self.restore_exit()
                    self.restore_last()
                    self.phase='suspended'
                else:
                    if active and self.previous_mode=='ThirdPerson' and self.phase not in ('slam',):
                        self.offset_history.clear() # prove contributions from this Slam only
                        self.exit_declined=False
                        self.exit_wait_frames=0
                    target=EXTRA_DISTANCE if active else 0.
                    self.extra=approach(self.extra,target,dt,
                        IN_RESPONSE_SECONDS if active else OUT_RESPONSE_SECONDS)
                    self.phase='slam' if active else 'release' if self.extra else 'idle'
                self.previous_mode=mode
                row=dict(update=self.frames+1,elapsed_ms=(tick-self.started)/1e6,
                    camera_mode=mode,slam_active=active,extra_distance=self.extra,
                    phase=self.phase,movement_mode=int(movement.MovementMode),
                    custom_movement_mode=int(movement.CustomMovementMode))
                phase=(mode,active,self.phase)
                if phase!=self.last_phase:
                    self.report['events'].append(dict(row))
                    self.last_phase=phase
                    if active or self.phase.startswith('exit_'):
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
                    if self.exit_bridge is not None:
                        row['exit_control_x']=struct.unpack_from('<d',self.exit_bridge['state'].modify.raw,160)[0]
                self.current()
                row['read_cost_ms']=(perf_counter_ns()-tick)/1e6
                self.report['samples'].append(row)
                self.frames+=1
                if self.frames>=MAX_UPDATES:self.try_finish('UPDATE_LIMIT')
            except Exception as exc:
                self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
                self.try_finish('READ_OR_START_FAILED')

        def finish(self,reason):
            if (self.last_write is not None or self.exit_bridge is not None) and not runtime_updates.is_game_thread():
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
            self.restore_exit()
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
