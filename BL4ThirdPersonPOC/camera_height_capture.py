"""Explicit bounded camera-height observations on the existing owned update route.

No native access, new producer, timers, camera writes or animation writes.
SDK reads are sequential observations, not proof of animation/render ordering.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from time import perf_counter_ns
from unrealsdk import hooks
from unrealsdk.unreal import WeakPointer
from . import runtime_updates

LIMIT = 600
TAG = '[BL4ThirdPersonPOC.Height]'
_armed = None
_capture = None
_last = None


class OwnerChanged(RuntimeError):
    pass


def coords(value, names=('X', 'Y', 'Z')):
    result = {}
    for name in names:
        try:
            raw = getattr(value, name)
        except AttributeError:
            raw = getattr(value, name.lower())
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError('Nonfinite '+name)
        result[name] = number
    return result


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite scalar')
    return number


def plain(value, depth=0):
    """Bounded copy of existing Python diagnostic data, never stringify UObjects."""
    if value is None or isinstance(value, (bool, str, int)):
        return value[:256] if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if depth < 5 and isinstance(value, dict):
        return {str(k)[:80]: plain(v, depth+1) for k,v in list(value.items())[:64]}
    if depth < 5 and isinstance(value, (tuple, list)):
        return [plain(v, depth+1) for v in value[:16]]
    return None


def summarize(rows):
    def group(selected):
        result = {}
        for key in ('spine_actor_z', 'camera_actor_z', 'camera_spine_z',
                    'mesh_actor_z', 'motion_baseline_z', 'motion_filtered_z'):
            values = [row['relative'][key] for row in selected
                      if key in row.get('relative', {})]
            if values:
                result[key] = dict(min=min(values), max=max(values),
                                   mean=sum(values)/len(values), count=len(values))
        return result
    return dict(all=group(rows), last_120=group(rows[-120:]),
                modes=dict(Counter(row.get('camera_mode', '?') for row in rows)),
                colliding_updates=sum(row.get('camera_flags', {}).get('colliding', False)
                                      for row in rows),
                maximum_read_cost_ms=max((r.get('read_cost_ms',0) for r in rows),default=0))


class Capture:
    def __init__(self, mod, label):
        self.mod, self.label = mod, label
        self.spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL,
                     'bl4tps.camera_height.capture')
        self.active = False
        self.registered = False
        self.frames = 0
        self.started = perf_counter_ns()
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        self.path = Path(mod.SETTINGS_DIR)/'BL4ThirdPersonPOC_reports'/(
            'camera_height_'+label+'_'+stamp+'.json')
        self.report = dict(probe='camera_height', version=mod.MOD_VERSION, label=label,
                           utc=datetime.now(timezone.utc).isoformat(), limit=LIMIT,
                           game_writes=0, native_reads=0, native_patches_added=0,
                           sdk_hooks_peak=0, sdk_hooks=0, new_update_producers=0,
                           note='Owned widget POST observations. Sequential SDK reads; '
                                'no shared atomic camera/animation/render snapshot. '
                                'Diagnostic overhead is not an FPS measurement.',
                           samples=[], optional_errors={}, errors=[])
        self.refs = ()
        self.addresses = ()
        self.bones = []

    def owner(self, index):
        obj = self.refs[index]()
        if obj is None or int(obj._get_address()) != self.addresses[index]:
            raise OwnerChanged('Height owner expired/replaced: '+str(index))
        # Component references must still belong to the captured live character.
        if index in (3,4):
            pawn = self.owner(1)
            attached = pawn.Mesh if index == 3 else pawn.OakCharacterMovement
            if attached != obj:
                raise OwnerChanged('Height component owner changed: '+str(index))
        return obj

    def current(self):
        if not runtime_updates.is_game_thread():
            raise OwnerChanged('Height read requires owned game thread')
        live = tuple(self.owner(i) for i in range(5))
        runtime = tuple(self.mod._get_runtime())
        if len(runtime) != 3 or any(o is None for o in runtime) or any(
                a != b for a,b in zip(live[:3],runtime)):
            raise OwnerChanged('Height local runtime changed')
        return live

    def optional(self, key, read):
        try:
            return read()
        except OwnerChanged:
            raise
        except Exception as exc:
            errors = self.report['optional_errors']
            if key in errors:
                errors[key]['count'] += 1
            elif len(errors) < 32:
                errors[key] = dict(count=1, error=type(exc).__name__+': '+str(exc)[:200])
            return None

    def start(self):
        if not runtime_updates.is_game_thread():
            raise RuntimeError('Use F10 in loaded gameplay on the owned game thread')
        pc,pawn,camera = self.mod._get_runtime()
        if any(o is None for o in (pc,pawn,camera)):
            raise RuntimeError('Loaded local character required')
        if not self.mod._third_person_enabled:
            raise RuntimeError('Enable TPS before height capture')
        if pc.bShowMouseCursor or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
            raise RuntimeError('Start on foot in normal TPS with menus closed')
        mesh,movement = pawn.Mesh,pawn.OakCharacterMovement
        if mesh is None or movement is None:
            raise RuntimeError('Local mesh/movement missing')
        objects = (pc,pawn,camera,mesh,movement)
        self.refs = tuple(WeakPointer(o) for o in objects)
        self.addresses = tuple(int(o._get_address()) for o in objects)
        self.current()
        if not self.owner(3).DoesSocketExist('Spine3'):
            raise RuntimeError('Reviewed Spine3 body reference missing')
        # Optional names are probed through SDK existence checks, never offsets.
        for bone in ('Root','Pelvis','pelvis','Head','Spine5',
                     'Foot_L','Foot_R','foot_l','foot_r'):
            exists = self.optional('bone_exists_'+bone,
                                   lambda bone=bone: bool(self.owner(3).DoesSocketExist(bone)))
            if exists:
                self.bones.append(bone)
        self.report['identity'] = dict(zip(('controller','pawn','camera','mesh','movement'),
                                           map(hex,self.addresses)))
        self.report['optional_bones'] = list(self.bones)
        if runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Height subscription already registered')
        self.registered = True  # Covers partial add failures during cleanup.
        self.active = True
        self.report['sdk_hooks_peak'] = self.report['sdk_hooks'] = 1
        runtime_updates.add_hook(*self.spec,self.frame)
        if not runtime_updates.has_hook(*self.spec):
            raise RuntimeError('Height subscription registration unverified')
        self.mod.logging.warning(f'{TAG} START label={self.label} updates={LIMIT} '
                                 'game_writes=0 native_patches_added=0; F10 stops early')

    def read_row(self):
        tick = perf_counter_ns()
        self.current()
        actor = coords(self.owner(1).K2_GetActorLocation())
        spine = coords(self.owner(3).GetSocketLocation('Spine3'))
        row = dict(update=self.frames+1, elapsed_ms=(tick-self.started)/1e6,
                   actor_location=actor, spine_location=spine,
                   actor_rotation=coords(self.owner(1).K2_GetActorRotation(),
                                         ('Pitch','Yaw','Roll')),
                   camera_mode=str(self.owner(2).GetActorCameraMode(self.owner(1))),
                   movement_mode=int(self.owner(4).MovementMode),
                   custom_movement_mode=int(self.owner(4).CustomMovementMode),
                   velocity=coords(self.owner(4).Velocity),
                   crouched=bool(self.owner(1).bIsCrouched),
                   mouse_cursor=bool(self.owner(0).bShowMouseCursor),
                   feature_flags={k: bool(getattr(self.mod,k,False)) for k in (
                       '_third_person_enabled','_ads_active','_vehicle_camera_active',
                       '_shop_camera_active','_ladder_active','_slide_active')})
        row['camera_flags'] = self.optional('camera_flags', lambda: dict(
            colliding=bool(self.owner(2).CameraModeState.bIsColliding),
            transitioning=bool(self.owner(2).CameraModeState.bIsTransitioning))) or {}
        for key,read in (
            ('mesh_location',lambda:coords(self.owner(3).K2_GetComponentLocation())),
            ('mesh_relative_location',lambda:coords(self.owner(3).RelativeLocation)),
            ('mesh_relative_rotation',lambda:coords(self.owner(3).RelativeRotation,
                                                    ('Pitch','Yaw','Roll'))),
            ('camera_cache',lambda:self.camera_pov('CameraCachePrivate')),
            ('camera_state',lambda:self.camera_pov('CameraModeState')),
            ('camera_getter_location',lambda:coords(self.owner(2).GetCameraLocation())),
            ('applied_offset',lambda:coords(self.owner(2).CameraModeState.CameraLocationOffset)),
            ('control_rotation',lambda:coords(self.owner(0).GetControlRotation(),
                                              ('Pitch','Yaw','Roll'))),
            ('floor',self.floor),
            ('capsule',self.capsule),
        ):
            row[key] = self.optional(key,read)
        row['bones'] = {bone:self.optional('bone_'+bone,
                            lambda bone=bone:coords(self.owner(3).GetSocketLocation(bone)))
                        for bone in self.bones}
        row['motion'] = dict(enabled=bool(getattr(self.mod,'_dynamic_motion_enabled',False)),
                             state=plain(getattr(self.mod,'_dynamic_motion_state',{})),
                             parameters=plain(getattr(self.mod,'_dynamic_motion_parameters',{})))
        row['configured_offset'] = self.optional('configured_offset',lambda: {
            axis:finite(getattr(self.mod,'camera_offset_'+axis).value) for axis in 'xyz'})
        from . import root_height
        row['root_height'] = root_height.snapshot(self.mod)
        row['mantle'] = plain(getattr(self.mod,'_mantle_camera_state',{}))
        slam = sys.modules.get('_bl4tps_ground_slam_beta_owner')
        slam_report = getattr(slam,'report',{})
        row['slam_reference'] = {key:plain(slam_report.get(key)) for key in (
            'body_anchor','pawn_anchor_target','position_writes','handoff_offset_writes')}
        relative = row['relative'] = dict(spine_actor_z=spine['Z']-actor['Z'])
        if row['mesh_location'] is not None:
            relative['mesh_actor_z'] = row['mesh_location']['Z']-actor['Z']
        if row['camera_cache'] is not None:
            camera_z = row['camera_cache']['location']['Z']
            relative.update(camera_actor_z=camera_z-actor['Z'],
                            camera_spine_z=camera_z-spine['Z'])
        for source,target in (('baseline','motion_baseline_z'),('filtered','motion_filtered_z')):
            value = row['motion']['state'].get(source)
            if isinstance(value,list) and len(value)==3 and isinstance(value[2],(int,float)):
                relative[target] = value[2]
        self.current()  # Reject partial rows if synchronous SDK work changed ownership.
        row['read_cost_ms'] = (perf_counter_ns()-tick)/1e6
        return row

    def camera_pov(self, attribute):
        pov = getattr(self.owner(2),attribute).POV
        return dict(location=coords(pov.Location),
                    rotation=coords(pov.Rotation,('Pitch','Yaw','Roll')), fov=finite(pov.FOV))

    def floor(self):
        floor = self.owner(4).CurrentFloor
        return dict(floor_dist=finite(floor.FloorDist), line_dist=finite(floor.LineDist),
                    blocking=bool(floor.bBlockingHit),walkable=bool(floor.bWalkableFloor),
                    impact_point=coords(floor.HitResult.ImpactPoint),
                    impact_normal=coords(floor.HitResult.ImpactNormal))

    def capsule(self):
        capsule = self.owner(1).CapsuleComponent
        ref = WeakPointer(capsule)
        obj = ref()
        if obj is None:
            raise ValueError('Capsule unavailable')
        location = coords(obj.K2_GetComponentLocation())
        obj = ref()
        if obj is None or self.owner(1).CapsuleComponent != obj:
            raise OwnerChanged('Capsule owner changed')
        half = finite(obj.GetScaledCapsuleHalfHeight())
        return dict(location=location,half_height=half,bottom_z=location['Z']-half)

    def frame(self,obj,args,ret,func):
        if not self.active or not runtime_updates.is_game_thread():
            return
        try:
            row = self.read_row()
            self.report['samples'].append(row)
            self.frames += 1
        except Exception as exc:
            self.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
            self.try_finish('READ_FAILED')
            return
        if self.frames >= LIMIT:
            self.try_finish('COMPLETE')

    def try_finish(self,reason):
        try:
            self.finish(reason)
        except Exception as exc:
            self.mod.logging.error(f'{TAG} STOP_OR_OUTPUT_FAILED '+repr(exc))

    def finish(self,reason):
        global _capture,_last
        self.active = False
        if self.registered:
            runtime_updates.remove_hook(*self.spec)
            if runtime_updates.has_hook(*self.spec):
                raise RuntimeError('Height subscription removal unverified; retry off')
            self.registered = False
        self.report.update(status=reason,completed_updates=self.frames,sdk_hooks=0,
                           cleanup_complete=True,summary=summarize(self.report['samples']))
        # File output only after detaching, never in every update.
        output_error = None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.path.write_text(json.dumps(self.report,indent=2,ensure_ascii=False,
                                           allow_nan=False),encoding='utf-8')
        except Exception as exc:
            output_error = type(exc).__name__+': '+str(exc)[:200]
        _last = dict(label=self.label,path=str(self.path),updates=self.frames,
                     status=reason if output_error is None else 'OUTPUT_FAILED')
        if _capture is self:
            _capture = None
        if output_error is not None:
            _last['error'] = output_error
            self.mod.logging.error(f'{TAG} OUTPUT_FAILED sdk_hooks=0 '+output_error)
            return
        self.mod.logging.warning(f'{TAG} {reason} label={self.label} updates={self.frames} '
                                 f'errors={len(self.report["errors"])} sdk_hooks=0 '
                                 f'game_writes=0 json={self.path}')


def arm(mod,label='height'):
    global _armed
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',label):
        raise ValueError('Label: 1-40 letters, numbers, underscore or hyphen')
    if _capture is not None:
        raise RuntimeError('Height capture already running; F10 or off stops it')
    from .omni import profiler
    if profiler.status(mod)['state'] != 'off':
        raise RuntimeError('Stop the Omni profiler before arming height capture')
    _armed = (mod,label)
    mod.logging.warning(f'{TAG} ARMED label={label}; close console, then F10')


def trigger(mod):
    global _armed,_capture
    if _capture is not None and _capture.mod is mod:
        try:
            _capture.finish('MANUAL_STOP')
        except Exception as exc:
            mod.logging.error(f'{TAG} STOP_FAILED '+repr(exc))
        return True
    if _armed is None or _armed[0] is not mod:
        return False
    _,label = _armed
    _armed = None
    capture = None
    try:
        capture = _capture = Capture(mod,label)
        capture.start()
    except Exception as exc:
        if capture is None:
            mod.logging.error(f'{TAG} START_FAILED '+repr(exc))
            return True
        capture.report['errors'].append(type(exc).__name__+': '+str(exc)[:300])
        try:
            capture.finish('START_FAILED')
        except Exception as cleanup:
            mod.logging.error(f'{TAG} CLEANUP_FAILED '+repr(cleanup))
    return True


def shutdown(mod):
    global _armed
    if _armed is not None and _armed[0] is mod:
        _armed = None
    if _capture is not None and _capture.mod is mod:
        _capture.finish('CANCELLED')
    return _capture is None or _capture.mod is not mod


def status(mod):
    if _capture is not None and _capture.mod is mod:
        return dict(state='running' if _capture.active else 'cleanup_pending',
                    label=_capture.label,updates=_capture.frames)
    if _armed is not None and _armed[0] is mod:
        return dict(state='armed',label=_armed[1],updates=0)
    return dict(state='off',last=_last)
