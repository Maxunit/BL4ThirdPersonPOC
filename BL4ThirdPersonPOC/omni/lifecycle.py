"""Menu/vehicle pause, exact-owner retirement, rebinding and error report persistence."""
from datetime import datetime, timezone
from time import monotonic
from unrealsdk import hooks
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import KEY, TAG, describe, report_path, write_report
from . import settings
from .inputs import NativeBindings
from .session import GameplaySession
from .rebind_cache import RebindCache
from .vehicle_handoff import VehicleHandoff, allow_exit_air
from .profiler import root_span
from . import hitch

class LifecycleSupervisor:
    """Own restart/widget lifecycle subscriptions; retire complete native sessions before restart."""

    def __init__(self, mod, updates):
        self.mod = mod
        self.updates = updates
        self.active = False
        self.busy = False
        self.child = None
        self.started = monotonic()
        self.frames = 0
        self.sequence = 0
        self.registered = []
        self.phase = None
        self.candidate = None
        self.candidate_refs = None
        self.candidate_frames = 0
        self.restart_wait = False
        # Reports live below SETTINGS_DIR; a .sdkmod zip is not writable.
        self.path = report_path(mod, 'player_omnidirectional_gameplay')
        self.diagnostics = settings.diagnostics_enabled()
        self.previous_normal_inputs = None
        self.report = dict(probe='player_omnidirectional_gameplay', integrated=True, diagnostics=self.diagnostics, utc=datetime.now(timezone.utc).isoformat(), events=[], errors=[], retired_sessions=[], native_patches=0, sdk_hooks=0, sdk_hooks_peak=4, rebind_count=0, note='Existing owned Widget PRE lifecycle plus local ClientRestart PRE. Complete native session retirement before pawn restart; owned vehicle-facing and paired exit-air handoff. Current gameplay session report retained; last 16 retired-session summaries. Normal same-owner special states and UI pause; rearm stable normal TPS, or a confirmed personal-vehicle exit with settled on-foot bindings with released configured Sprint/Dash/Crouch/Jump actions, no ADS/slide/sprint/Dash. No elapsed-time scheduler.', scope_limits='Refactored V3 lifecycle; regression after cleanup remains required. Death, FFYL, Second Wind and respawn are not validated. Any ClientRestart retires safely, but rearming still requires the full on-foot guards. Unknown unannounced identity changes, build/ownership/cleanup errors fail closed.')
        # Mod disable reaches finish() through the explicit mod_shutdown stage.
        self.input_owner = None
        self.rebind_cache = RebindCache(self)
        self.vehicle = None

    def event(self, name, **data):
        if self.phase == name and (not data):
            return
        self.report['events'].append(dict(event=name, update_index=self.frames, t=monotonic() - self.started, **data))
        del self.report['events'][:-256]
        if self.phase != name:
            logging.warning(TAG + ' ' + name)
            self.phase = name

    def reset_candidate(self):
        self.candidate = None
        self.candidate_refs = None
        self.candidate_frames = 0

    def install(self):
        # The owned update producer must exist; its widget may still be built
        # later. Routed callbacks only run once that widget ticks on GameThread.
        owner = getattr(self.updates, '_owner', None)
        if owner is None or not getattr(owner, 'active', False):
            raise RuntimeError('Existing update producer required')
        self.active = True
        plans = ((self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.PRE, KEY + '.lifecycle_pre', self.frame), (self.mod.CLIENT_RESTART_FUNCTION, hooks.Type.PRE, KEY + '.restart_pre', self.restart_pre), (self.mod.CLIENT_RESTART_FUNCTION, hooks.Type.POST_UNCONDITIONAL, KEY + '.restart_post', self.restart_post), (self.mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, KEY + '.vehicle', self.vehicle_frame))
        for path, kind, name, callback in plans:
            spec = (path, kind, name)
            if self.updates.has_hook(*spec):
                raise RuntimeError('Lifecycle hook already occupied')
            self.registered.append(spec)
            self.updates.add_hook(*spec, callback)
            if not self.updates.has_hook(*spec):
                raise RuntimeError('Lifecycle hook installation unverified')
        self.report['sdk_hooks'] = len(self.registered)
        self.event('WAITING_ON_FOOT')

    def retire(self, reason):
        from . import profiler
        profiler.cancel(self.mod, "SESSION_RETIRED_" + str(reason))
        self.reset_candidate()
        if self.child is None:
            return
        child = self.child
        with hitch.step('session.retire'):
            try:
                child.disable_special_controls()
            finally:
                child.finish(reason)
        if any((owner.hook is not None for owner in child.owners())):
            raise RuntimeError('Retired gameplay native hooks remain')
        if any((trace.hook is not None for action, rva, owner, trace in child.entries)):
            raise RuntimeError('Retired Circle native hook remains')
        if child.registered:
            raise RuntimeError('Retired gameplay widget subscription remains')
        if getattr(getattr(child, 'grenade_facing', None), 'registered', False):
            raise RuntimeError('Retired grenade subscription remains')
        r = child.report
        self.report['last_retired_gameplay'] = r
        self.report['retired_sessions'].append(dict(sequence=self.sequence, status=r.get('status'), total_sample_count=r.get('total_sample_count'), errors=list(r.get('errors', [])), game_writes=r.get('game_writes'), native_patches=r.get('native_patches'), restoration={k: v for k, v in r.items() if k.endswith('restoration_verified') or k.endswith('restore_verified')}, special_state_edges=r.get('special_state_edges', []), sdk_slide_direction=r.get('sdk_slide_direction')))
        if r.get('collect_pose_diagnostics'):
            self.report['retired_sessions'][-1]['pose_diagnostics'] = self.retained_pose_diagnostics(r)
        del self.report['retired_sessions'][:-16]
        self.child = None
        self.rebind_cache.bones = None
        setattr(self.mod, KEY, getattr(self, 'lifecycle_supervisor', self))
        self.report['native_patches'] = 0
        self.report['sdk_hooks'] = len(self.registered)
        self.event('GAMEPLAY_RETIRED', reason=reason, sequence=self.sequence)

    @staticmethod
    def retained_pose_diagnostics(report):
        # Preserve decisive bounded data when a later session replaces the full report.
        fields = ('update_index', 't', 'actor_rotation', 'camera_rotation',
                  'control_rotation', 'animation_aim', 'is_crouched', 'handoff_state',
                  'movement_input_active', 'input_yaw', 'crouch_follow')
        return dict(crouch_idle_layouts=report.get('crouch_idle_layouts'),
                    crouch_follow_updates=report.get('crouch_follow_updates', 0),
                    crouch_pose_pairs=report.get('crouch_pose_pairs', [])[-128:],
                    head_pose_samples=report.get('head_pose_samples', [])[-128:],
                    transition_samples=[{k: row[k] for k in fields if k in row}
                                        for row in report.get('samples', [])[-256:]])

    def restart_pre(self, obj, args, ret, func):
        if not self.active:
            return
        try:
            if self.child is None and not self.updates.is_game_thread():
                # Cold start: the update producer binds GameThread on this RPC's
                # POST or the first widget Tick. Without a gameplay child there is
                # nothing to retire; rebinding still waits for the on-foot gates.
                self.restart_wait = True
                return
            if not self.updates.is_game_thread():
                raise RuntimeError('ClientRestart outside owned game thread')
            current = self.mod._get_runtime()
            pc = current[0]
            previous = None if self.child is None else self.child.refs[0]()
            if obj != pc and obj != previous:
                return
            if self.vehicle is not None:
                self.vehicle.restart('PRE', obj, args)
                if not self.active:
                    return
            new_pawn = getattr(args, 'NewPawn', None)
            self.event('CLIENT_RESTART_PRE', new_pawn=None if new_pawn is None else describe(new_pawn))
            self.retire('CLIENT_RESTART_NATIVE_HANDOFF')
            self.restart_wait = True
        except Exception as exc:
            self.fail('restart_pre', exc)

    def restart_post(self, obj, args, ret, func):
        if self.active and self.vehicle is not None:
            self.vehicle.restart('POST', obj, args)

    @hitch.root("vehicle")
    @root_span("callback.vehicle")
    def vehicle_frame(self, obj, args, ret, func):
        if not self.active or not self.updates.is_game_thread():
            return
        try:
            if self.vehicle is None:
                self.vehicle = VehicleHandoff(self)
            self.vehicle.frame()
            self.report['vehicle_native_patches'] = 0 if self.vehicle is None else self.vehicle.patch_count()
        except Exception as exc:
            self.fail('vehicle_frame', exc)

    def eligible(self):
        pc, pawn, camera = self.mod._get_runtime()
        if any((o is None for o in (pc, pawn, camera))):
            return (None, 'WAITING_RUNTIME')
        refs = tuple((WeakPointer(o) for o in (pc, pawn, camera)))
        if any((ref() is None for ref in refs)):
            return (None, 'WAITING_LIFETIMES')
        if not self.mod._third_person_enabled:
            return (None, 'TPS_DISABLED')
        if str(pawn.Class.Name) != 'OakCharacter' or bool(self.mod._vehicle_camera_active):
            return (None, 'VEHICLE_NATIVE')
        if bool(pc.bShowMouseCursor) or bool(getattr(self.mod, '_shop_camera_active', False)):
            return (None, 'WAITING_UI')
        if not self.mod._third_person_pushed:
            return (None, 'WAITING_TPS_PUSH')
        if bool(camera.CameraModeState.bIsTransitioning):
            return (None, 'WAITING_CAMERA_TRANSITION')
        if camera.CameraModeInputs.ViewTarget != pawn:
            return (None, 'WAITING_VIEW_TARGET')
        if str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
            return (None, 'WAITING_CAMERA_MODE')
        movement = pawn.OakCharacterMovement
        if (movement is None or int(movement.MovementMode) != 1) and not allow_exit_air(self, pc, pawn, camera, movement):
            air = getattr(self.vehicle, 'air', None)
            return (None, air.wait_reason(self) if air is not None else 'WAITING_GROUNDED')
        if any((bool(getattr(self.mod, k, False)) for k in ('_ads_active', '_slide_active', '_ladder_active'))):
            return (None, 'WAITING_NORMAL_MOVEMENT')
        if bool(pawn.IsCharacterDashing()) or bool(movement.bWantsToDash):
            return (None, 'WAITING_DASH_END')
        if any((bool(getattr(movement, k)) for k in ('bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting'))):
            return (None, 'WAITING_SPRINT_END')
        if self.input_owner is None or not self.input_owner.matches(pc):
            self.input_owner = NativeBindings(pc)
        self.input_owner.begin_frame()
        self.input_owner.maybe_refresh(require_complete=True)
        if any((self.input_owner.snapshot(pc)[role] for role in ('sprint', 'dash', 'crouch', 'jump'))):
            return (None, 'WAITING_INPUT_RELEASE')
        objects = (pc, pawn, camera, movement)
        refs = tuple((WeakPointer(o) for o in objects))
        if any((ref() is None for ref in refs)):
            return (None, 'WAITING_LIFETIMES')
        return ((tuple((int(o._get_address()) for o in objects)), refs), 'ON_FOOT_READY')

    @hitch.root("lifecycle")
    @root_span("callback.lifecycle")
    def frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        self.busy = True
        scoped = None
        try:
            self.frames += 1
            if not self.mod._third_person_enabled:
                if self.child is not None:
                    self.pause_perspective()
                else:
                    self.reset_candidate()
                    self.event('WAITING_TPS_ENABLED')
                return
            if self.child is not None:
                scoped = self.child
                scoped.open_callback_scope()
                pc, pawn, camera, movement = self.child.bound()
                normal_inputs = not bool(pc.bShowMouseCursor) and (not any((bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active')))) and (int(movement.MovementMode) in (1, 3)) and (str(camera.GetActorCameraMode(pawn)) == 'ThirdPerson')
                # Full mapping scans are bounded: count changes, the return to
                # normal input (remaps happen in menus) and a fixed update cadence.
                self.child.inputs.begin_frame()
                self.child.inputs.maybe_refresh(require_complete=normal_inputs,
                                                force=normal_inputs and self.previous_normal_inputs is False)
                self.previous_normal_inputs = normal_inputs
                if not self.child.active:
                    self.report['gameplay_stop_reason'] = self.child.report.get('status')
                    self.report['errors'].append('Gameplay session stopped: ' + str(self.child.report.get('status')))
                    logging.error(TAG + ' STOPPED_ON_ERROR gameplay=' + str(self.child.report.get('status'))
                                  + '; feature off until re-enabled (menu or bl4tps_omni on)')
                    from . import record_failure
                    record_failure('gameplay', RuntimeError(str(self.child.report.get('status'))))
                    self.finish('GAMEPLAY_FAILSAFE')
                    return
                if bool(self.mod._vehicle_camera_active):
                    self.retire('VEHICLE_CAMERA_NATIVE_HANDOFF')
                    self.restart_wait = True
                else:
                    self.child.bound()
                    self.child.observe_ground_input_pose('PRE')
                    return
            candidate, reason = self.eligible()
            if candidate is None:
                self.reset_candidate()
                self.event(reason)
                return
            addresses, refs = candidate
            previous = () if self.candidate_refs is None else tuple((ref() for ref in self.candidate_refs))
            current = tuple((ref() for ref in refs))
            if self.candidate != addresses or len(previous) != len(current) or any((a is None or a != b for a, b in zip(previous, current))):
                self.candidate = addresses
                self.candidate_refs = refs
                self.candidate_frames = 1
                self.event('VERIFY_ON_FOOT_BINDINGS', objects=[hex(a) for a in addresses])
                return
            self.candidate_frames += 1
            if self.candidate_frames < 2:
                return
            child = GameplaySession(self.mod, self.updates)
            self.previous_normal_inputs = None
            child.lifecycle_managed = True
            child.lifecycle_supervisor = self
            self.child = child
            self.sequence += 1
            child.report['lifecycle_session_sequence'] = self.sequence
            with hitch.step('session.install'):
                child.install()
            if self.vehicle is not None and self.vehicle.air is not None and self.vehicle.air.ticket is not None:
                with self.rebind_cache.transaction(child):
                    self.vehicle.air.air_start(child)
            self.restart_wait = False
            self.report['rebind_count'] += 1
            self.report['sdk_hooks'] = len(self.registered) + 1 + int(
                getattr(getattr(self.child, 'grenade_facing', None), 'registered', False))
            self.report['sdk_hooks_peak'] = max(self.report['sdk_hooks_peak'], self.report['sdk_hooks'])
            self.event('ON_FOOT_REBOUND', sequence=self.sequence, objects=[hex(a) for a in addresses])
            self.reset_candidate()
        except Exception as exc:
            self.fail('widget_pre', exc)
        finally:
            if scoped is not None:
                scoped.close_callback_scope()
            self.busy = False

    def pause_perspective(self):
        # Fully restore the gameplay session; retain only lifecycle subscriptions.
        # Cleanup conflicts still propagate to the existing fail-closed path.
        self.retire('PERSPECTIVE_NATIVE_HANDOFF')
        self.event('WAITING_TPS_ENABLED')

    def fail(self, where, exc):
        from . import record_failure
        record_failure(where, exc)
        self.report['errors'].append(dict(where=where, error=repr(exc)[:500]))
        logging.error(TAG + ' STOPPED_ON_ERROR ' + where + ': ' + repr(exc)[:300]
                      + '; feature off until re-enabled (menu or bl4tps_omni on)')
        try:
            self.finish('LIFECYCLE_FAILED')
        except Exception as cleanup:
            setattr(self.mod, KEY, getattr(self, 'lifecycle_supervisor', self))
            logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def finish(self, reason):
        self.active = False
        failures = []
        if self.vehicle is not None:
            try:
                self.vehicle.stop()
                self.report['vehicle_handoff'] = self.vehicle.report
                if self.vehicle.air is not None:
                    self.report['vehicle_exit_air'] = self.vehicle.air.report
                self.vehicle = None
            except Exception as exc:
                failures.append('vehicle: ' + repr(exc))
        self.report['rebind_optimization'] = dict(self.rebind_cache.totals)
        self.report['hitches'] = hitch.snapshot()
        self.rebind_cache.clear()
        if self.child is not None:
            try:
                self.retire(reason)
            except Exception as exc:
                failures.append('gameplay: ' + repr(exc))
                self.child.active = False
                self.report['last_retired_gameplay'] = self.child.report
        for spec in list(self.registered):
            try:
                if self.updates.has_hook(*spec):
                    self.updates.remove_hook(*spec)
                if self.updates.has_hook(*spec):
                    raise RuntimeError('Lifecycle hook removal unverified')
                self.registered.remove(spec)
            except Exception as exc:
                failures.append('lifecycle: ' + repr(exc))
        for failure in failures:
            self.report['errors'].append(dict(where='cleanup', error=failure[:1000]))
        self.report.update(status=reason if not failures else 'CLEANUP_INCOMPLETE', updates_seen=self.frames, duration_seconds=monotonic() - self.started, cleanup_complete=not failures, sdk_hooks=len(self.registered) + (int(self.child.registered) + int(getattr(getattr(self.child, 'grenade_facing', None), 'registered', False)) if self.child is not None else 0), native_patches=(0 if self.child is None else self.child.report.get('native_patches', 0)) + (0 if self.vehicle is None else self.vehicle.patch_count()), cleanup_failures=failures)
        # Production writes a report only when something went wrong.
        saved = None
        if self.diagnostics or failures or self.report['errors']:
            try:
                saved = write_report(self.path, self.report)
            except Exception as exc:
                logging.error(TAG + ' REPORT_SAVE_FAILED ' + repr(exc))
        if failures:
            setattr(self.mod, KEY, self)
            raise RuntimeError('Gameplay inactive; report saved; cleanup incomplete: ' + '; '.join(failures))
        if getattr(self.mod, KEY, None) is self:
            delattr(self.mod, KEY)
        logging.warning(TAG + ' ' + reason + ' sessions=' + str(self.sequence) + ' errors=' + str(len(self.report['errors'])) + ' json=' + str(saved) + ' sdk_hooks=0 native_patches=0')

    def save_report(self, reason='MANUAL_REPORT'):
        """Write the current bounded state without stopping (console 'report')."""
        self.report['rebind_optimization'] = dict(self.rebind_cache.totals)
        self.report['hitches'] = hitch.snapshot()
        self.report['vehicle_native_patches'] = 0 if self.vehicle is None else self.vehicle.patch_count()
        if self.vehicle is not None:
            self.report['vehicle_handoff'] = self.vehicle.report
            if self.vehicle.air is not None:
                self.report['vehicle_exit_air'] = self.vehicle.air.report
        snapshot = dict(self.report, status='RUNNING', snapshot_reason=reason, updates_seen=self.frames, duration_seconds=monotonic() - self.started)
        if self.child is not None:
            snapshot['current_gameplay'] = self.child.report
        return write_report(report_path(self.mod, 'player_omnidirectional_snapshot') if self.path is not None else None, snapshot)


