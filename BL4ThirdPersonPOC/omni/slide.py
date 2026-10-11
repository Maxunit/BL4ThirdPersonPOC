"""Slide responsibility; explicit pipeline calls, no historical probe inheritance."""
from time import perf_counter_ns
import math
from unrealsdk import find_object
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import TAG, angle, parts
from . import hitch

class SlideMixin:

    def write_slide(self, asset, value):
        launch = asset.LaunchDirection
        launch.RelativeDirection = value
        asset.LaunchDirection = launch
        self.report['game_writes'] += 1
        self.report['sdk_slide_direction']['sdk_writes'] += 1
        if asset.LaunchDirection.RelativeDirection != value:
            raise RuntimeError('Slide direction SDK readback mismatch')

    def apply_slide(self):
        if not self.updates.is_game_thread():
            raise RuntimeError('Slide SDK change requires owned game thread')
        asset = find_object('OakControlledMove', self.SLIDE_PATH)
        if asset is None:
            raise RuntimeError('Loaded Move_Slide asset unavailable')
        original = asset.LaunchDirection.RelativeDirection
        target = type(original)['ParentVelocity2D']
        self.slide_ref = WeakPointer(asset)
        self.slide_original, self.slide_target = (original, target)
        d = self.report['sdk_slide_direction']
        d['original'] = original.name
        d['target'] = target.name
        if original != target:
            self.slide_pending = True
            self.write_slide(asset, target)
        self.slide_ready = True
        d['applied'] = True
        d['already_momentum'] = original == target
        logging.warning(TAG + ' SDK_SLIDE_READY direction=ParentVelocity2D original=' + original.name)

    def verify_slide(self):
        asset = self.slide_ref()
        if asset is None:
            raise RuntimeError('Bound Slide asset expired')
        if asset.LaunchDirection.RelativeDirection != self.slide_target:
            raise RuntimeError('Slide direction changed externally; stopping without reassertion')

    def restore_slide(self):
        d = self.report['sdk_slide_direction']
        if not self.slide_pending:
            d['restored'] = True
            return
        if not self.updates.is_game_thread():
            raise RuntimeError('Slide SDK restore requires owned game thread; rerun')
        asset = self.slide_ref()
        if asset is None:
            d['asset_expired'] = True
            self.slide_pending = False
            d['restored'] = False
            d['restore_status'] = 'ASSET_EXPIRED_NO_LIVE_WRITE'
            return
        current = asset.LaunchDirection.RelativeDirection
        if current == self.slide_target:
            self.write_slide(asset, self.slide_original)
            d['restore_status'] = 'ORIGINAL_VERIFIED'
        elif current == self.slide_original:
            d['restore_status'] = 'ALREADY_ORIGINAL'
        else:
            d['restore_status'] = 'EXTERNAL_CHANGE_PRESERVED'
            d['external_value'] = current.name
            self.slide_pending = False
            d['restored'] = False
            return
        self.slide_pending = False
        d['restored'] = True

    def _slide_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                return
            if not self.slide_ready:
                self._bind_slide()
            self.verify_slide()
            previous = self.report['samples'][-1] if self.report['samples'] else None
            self._ground_vector_frame(obj, args, ret, func)
            if self.active:
                self.observe_slide(previous)
        except Exception as exc:
            self.report['errors'].append('SDK Slide: ' + repr(exc)[:500])
            try:
                self.finish('SDK_SLIDE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def validate_rotate_schema(self, movement):
        if self.rotate_schema_checked:
            return
        # The reviewed field belongs to the movement class, which outlives the
        # session. A rebind on the same class (weak identity and address) reuses
        # the primitive result instead of rescanning every reflected field.
        cache = getattr(getattr(self, 'lifecycle_supervisor', None), 'rebind_cache', None)
        cached = getattr(cache, 'rotate_schema', None)
        cls = movement.Class
        if cached is not None:
            ref, address, schema = cached
            if ref() is not None and ref() == cls and int(cls._get_address()) == address:
                self.report['rotate_state_schema'] = dict(schema, reused_for_same_class=True)
                self.rotate_schema_checked = True
                return
        with hitch.step('bind.rotate_schema'):
            self._scan_rotate_schema(movement)
        if cache is not None and self.rotate_schema_checked:
            cache.rotate_schema = (WeakPointer(cls), int(cls._get_address()), dict(self.report['rotate_state_schema']))

    def _scan_rotate_schema(self, movement):
        if not self.rotate_schema_checked:
            owners = (movement.Class, *tuple(movement.Class._superfields()))
            if len(owners) > 64:
                raise RuntimeError('Movement inheritance limit exceeded')
            matches = []
            seen = set()
            for owner in owners:
                count = 0
                for prop in owner._properties():
                    count += 1
                    if count > 4096:
                        raise RuntimeError('Movement reflection field limit exceeded')
                    if str(prop.Name) != 'CurrentRotateToState':
                        continue
                    address = int(prop._get_address())
                    if address not in seen:
                        seen.add(address)
                        matches.append((owner, prop))
            if len(matches) != 1:
                raise RuntimeError('CurrentRotateToState inherited lookup found ' + str(len(matches)) + ' distinct fields')
            owner, prop = matches[0]
            kind = str(prop.Class.Name)
            offset = int(prop.Offset_Internal)
            if kind != 'StructProperty' or offset != 12240:
                raise RuntimeError('Reviewed CurrentRotateToState schema differs: ' + kind + ' offset=' + hex(offset))
            if str(prop.Struct._path_name()) != '/Script/GbxGame.CharacterRotateToState':
                raise RuntimeError('CurrentRotateToState struct type differs')
            self.report['rotate_state_schema'] = dict(owner=str(owner._path_name()), kind=kind, offset=offset, struct=str(prop.Struct._path_name()), inherited_lookup=True)
            self.rotate_schema_checked = True

    def _slide_state_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                return
            sliding = bool(self.mod._slide_active)
            capture = self.collect_pose_diagnostics and (self.rotate_capture_count % 3 == 0 or sliding != self.rotate_last_slide)
            self.rotate_capture_count += 1
            row = self.capture_rotate_state() if capture else None
            self._slide_frame(obj, args, ret, func)
            if row is not None:
                row['probe_active_after'] = self.active
                self.report['rotate_state_samples'].append(row)
                del self.report['rotate_state_samples'][:-1024]
            self.native.slide_control[0] = int(self.active and bool(self.mod._slide_active))
            self.native.slide_control[6] = self.frames
            self.native.consume_slide()
            self.rotate_last_slide = sliding
        except Exception as exc:
            self.report['errors'].append('RotateState observation: ' + repr(exc)[:500])
            try:
                self.finish('ROTATE_STATE_OBSERVER_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def slide_exit_pending(self, camera, mode, sliding):
        """State-based slide exit window: the loader still restores its TPS camera.

        Begins when the slide flag falls and ends once the loader verified a
        settled ThirdPerson camera (it clears _slide_camera_recovery_pending).
        """
        if sliding or not bool(getattr(self.mod, '_slide_camera_recovery_pending', False)):
            return False
        if mode in ('Slide', 'Default'):
            return True
        return mode == 'ThirdPerson' and bool(camera.CameraModeState.bIsTransitioning)

    def slide_exit_frame(self):
        """Hold the slide heading through BL4's camera hand-back.

        Directional slides end facing away from the aim. Re-enabling the
        TurnState neutralisation and re-asserting the held heading every update
        keeps any native turn-to-aim from rotating the body back to the camera
        while the exit settles. Combat keeps priority (native aim).
        """
        pc, pawn, camera, movement = self.bound()
        sample = self.report['samples'][-1]
        free = not self.combat['active'] and self.impulse_index is not None
        self.native.control[8] = self.native.base + 3026455
        self.native.control[7] = int(free)
        self.native.control[0] = int(free)
        self.aim_native.control[0] = int(free)
        current = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
        if self.slide_exit_yaw is None:
            self.slide_exit_yaw = current['Yaw'] if self.slide_last_body_yaw is None else self.slide_last_body_yaw
            self.report['slide_exit_cycles'].append(dict(start_update=self.frames, start_yaw=self.slide_exit_yaw, actor_yaw_at_start=current['Yaw'], control_yaw=sample['control_rotation']['Yaw']))
            del self.report['slide_exit_cycles'][:-64]
            logging.warning(TAG + ' SLIDE_EXIT_HOLD heading kept through camera hand-back')
        if not free:
            self.slide_exit_yaw = None
            return
        now = sample['t']
        previous = self.follow_previous_t if self.slide_override_t is None else self.slide_override_t
        dt = min(0.05, max(0.0, now - previous))
        self.slide_override_t = now
        self.follow_previous_t = now
        moving = sample['horizontal_speed'] > 30 and sample['velocity_yaw'] is not None
        target_yaw = sample['velocity_yaw'] if moving else self.slide_exit_yaw
        # Step from the heading we own, not from a natively turned actor.
        base = self.slide_exit_yaw
        gap = angle(target_yaw, base)
        step = min(abs(gap), 540.0 * dt)
        held = angle(base + math.copysign(step, gap), 0.0)
        self.slide_exit_yaw = held
        drift = angle(current['Yaw'], held)
        actual = dict(current)
        if abs(drift) >= 0.01:
            target = dict(current, Yaw=held)
            result = self.set_rotation(pawn, target)
            actual = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            if not result or any((abs(angle(actual[k], target[k])) > 0.1 for k in ('Pitch', 'Yaw', 'Roll'))):
                raise RuntimeError('Slide exit body setter/readback differs')
        cycle = self.report['slide_exit_cycles'][-1] if self.report['slide_exit_cycles'] else None
        if cycle is not None:
            cycle['updates'] = cycle.get('updates', 0) + 1
            cycle['max_native_drift'] = max(cycle.get('max_native_drift', 0.0), abs(drift))
            cycle['end_yaw'] = actual['Yaw']

    def _slide_body_paused_frame(self, obj, args, ret, func, reason):
        self._air_paused_frame(obj, args, ret, func, reason)
        if reason == 'SLIDE_EXIT' and self.active and self.report['samples']:
            self.slide_exit_frame()
            return
        if reason != 'SLIDE' or not self.active or (not self.report['samples']):
            if self.active:
                self.slide_exit_yaw = None
            return
        if not self.slide_override_active:
            self.slide_override_active = True
            self.ab_count += 1
            self.slide_override_t = None
            self.slide_hold_rotation = None
            self.report['slide_caller_ab_cycles'].append(dict(phase='A_NATIVE' if self.ab_count == 1 else 'B_CALLER_CORRECTION', start_update=self.frames, override_count_start=int(self.native.control[9])))
            logging.warning(TAG + ' BODY_CORRECTION_RETAINED head phase is recorded separately')
        if self.ab_count != 2:
            return
        pc, pawn, camera, movement = self.bound()
        sample = self.report['samples'][-1]
        free = not self.combat['active'] and self.impulse_index is not None and bool(self.mod._slide_active)
        self.native.control[8] = self.native.base + 91157933
        self.native.control[7] = int(free)
        self.native.control[0] = int(free)
        self.aim_native.control[0] = int(free)
        now = sample['t']
        previous = self.follow_previous_t if self.slide_override_t is None else self.slide_override_t
        dt = min(0.05, max(0.0, now - previous))
        self.slide_override_t = now
        self.follow_previous_t = now
        current = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
        if self.slide_hold_rotation is None:
            self.slide_hold_rotation = current['Yaw']
        target_yaw = sample['velocity_yaw'] if sample['horizontal_speed'] > 30 and sample['velocity_yaw'] is not None else self.slide_hold_rotation
        actual = dict(current)
        if free:
            self.slide_hold_rotation = target_yaw
            self.slide_last_body_yaw = target_yaw
            self.slide_exit_yaw = None
            gap = angle(target_yaw, current['Yaw'])
            step = min(abs(gap), 540.0 * dt)
            if step >= 0.01:
                target = dict(current, Yaw=angle(current['Yaw'] + math.copysign(step, gap), 0.0))
                result = self.set_rotation(pawn, target)
                actual = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
                if not result or any((abs(angle(actual[k], target[k])) > 0.1 for k in ('Pitch', 'Yaw', 'Roll'))):
                    raise RuntimeError('B Slide body setter/readback differs')
        self.report['slide_body_samples'].append(dict(update=self.frames, t=now, free_body=free, actor_before=current, actor_after=actual, target_yaw=target_yaw, velocity_yaw=sample['velocity_yaw'], control_yaw=sample['control_rotation']['Yaw'], after_error=angle(actual['Yaw'], target_yaw), caller_override_count=int(self.native.control[9])))
        del self.report['slide_body_samples'][:-512]

    def _slide_pose_paused_frame(self, obj, args, ret, func, reason):
        if reason == 'SLIDE' and (not self.slide_override_active):
            self.ab_count = 1
        return self._slide_body_paused_frame(obj, args, ret, func, reason)

    def _slide_pose_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                return
            sliding = bool(self.mod._slide_active)
            if self.ready and (not sliding):
                self.native.control[8] = self.native.base + 3026455
            take = self.collect_pose_diagnostics and (self.head_tick % 6 == 0 or sliding != self.head_last_slide)
            self.head_tick += 1
            if take:
                started = perf_counter_ns()
                row = self.capture_head()
                row['capture_cost_us'] = (perf_counter_ns() - started) / 1000.0
                self.report['head_pose_samples'].append(row)
                self.report['head_pose_sample_total'] += 1
                del self.report['head_pose_samples'][:-256]
            self._slide_state_frame(obj, args, ret, func)
            if not self.active:
                return
            if self.slide_override_active and (not bool(self.mod._slide_active)):
                self.report['slide_caller_ab_cycles'][-1].update(end_update=self.frames, override_count_end=int(self.native.control[9]))
                self.slide_override_active = False
                self.slide_override_t = None
                self.slide_hold_rotation = None
            self.head_last_slide = sliding
        except Exception as exc:
            self.report['errors'].append('Head pose observation: ' + repr(exc)[:500])
            try:
                self.finish('HEAD_POSE_OBSERVER_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def paused_frame(self, obj, args, ret, func, reason):
        crouch_pose_before = self.capture_crouch_pose('BEFORE') if reason == 'CROUCHED' and self.collect_pose_diagnostics and self.frames % 6 == 0 else None
        entering = reason == 'SLIDE' and (not self.slide_override_active)
        self._slide_pose_paused_frame(obj, args, ret, func, reason)
        sliding_body = (reason == 'SLIDE' and bool(self.mod._slide_active)) or reason == 'SLIDE_EXIT'
        self.aim_native.crouch_control[0] = int(sliding_body and self.active and bool(self.aim_native.control[0]))
        if reason == 'CROUCHED' and self.active:
            self.crouch_frame()
            if crouch_pose_before is not None:
                rows = self.report.setdefault('crouch_pose_pairs', [])
                rows.append(dict(before=crouch_pose_before, after=self.capture_crouch_pose('AFTER')))
                del rows[:-256]
        if entering and self.active:
            self.report['slide_live_cycle_total'] += 1
            if self.report['slide_caller_ab_cycles']:
                self.report['slide_caller_ab_cycles'][-1]['phase'] = 'LIVE_BODY_AND_CROUCH_AIM'
                self.report['slide_caller_ab_cycles'][-1]['crouch_neutralizations_start'] = int(self.aim_native.crouch_control[3])
            del self.report['slide_caller_ab_cycles'][:-64]
            logging.warning(TAG + ' SLIDE_BODY_AND_HEAD_FOLLOW rerun script to stop and restore')

    def capture_crouch_pose(self, phase):
        """Bounded read-only pose evidence around the existing Crouch pipeline."""
        row = self.capture_head()
        pc, pawn, camera, movement = self.bound()
        node = self.blend_node()
        idle_nodes = self.capture_idle_nodes()
        row.update(phase=phase, crouched=bool(pawn.bIsCrouched),
                   idle_nodes=idle_nodes,
                   pending_input=parts(pawn.GetPendingMovementInputVector(), ('X', 'Y', 'Z')),
                   last_input=parts(pawn.GetLastMovementInputVector(), ('X', 'Y', 'Z')),
                   combat=dict(self.combat),
                   lean=dict(invert=bool(node.bInvertAlpha), alpha=float(node.ALPHA),
                             bool_enabled=bool(node.bAlphaBoolEnabled),
                             pending_restore=self.blend_pending),
                   root_enabled=int(self.native.control[7]),
                   idle_root_enabled=int(self.idle_native.control[0]),
                   idle_update_enabled=int(self.idle_update.control[0]))
        return row

    def capture_idle_nodes(self):
        """Discover actual IdleTurns receivers and scalar state through SDK reflection."""
        anim = self.head_anim()
        pawn = self.bound()[1]
        if anim is None or pawn.Mesh.AnimScriptInstance != anim:
            raise RuntimeError('Crouch Idle animation owner changed')
        layouts = getattr(self, 'crouch_idle_layouts', None)
        if layouts is None:
            found = {}
            owners = (anim.Class, *tuple(anim.Class._superfields()))
            if len(owners) > 64:
                raise RuntimeError('Crouch Idle inheritance limit')
            for owner in owners:
                for index, prop in enumerate(owner._properties()):
                    if index >= 4096:
                        raise RuntimeError('Crouch Idle property limit')
                    if str(prop.Class.Name) != 'StructProperty' or str(prop.Struct.Name) != 'GbxAnimNode_IdleTurns':
                        continue
                    name, offset = str(prop.Name), int(prop.Offset_Internal)
                    if not 0 <= offset <= 0x400000:
                        raise RuntimeError('Crouch Idle offset outside bounds')
                    fields = []
                    for field_index, field in enumerate(prop.Struct._properties()):
                        if field_index >= 256:
                            raise RuntimeError('Crouch Idle field limit')
                        kind = str(field.Class.Name)
                        if kind in ('BoolProperty', 'FloatProperty', 'DoubleProperty', 'IntProperty', 'ByteProperty', 'EnumProperty'):
                            fields.append((str(field.Name), kind, int(field.Offset_Internal)))
                    entry = (offset, tuple(fields))
                    if name in found and found[name] != entry:
                        raise RuntimeError('Crouch Idle reflected layouts conflict')
                    found[name] = entry
            if not found or len(found) > 16:
                raise RuntimeError('Crouch Idle node count outside bounds')
            layouts = tuple((name, *entry) for name, entry in sorted(found.items()))
            self.crouch_idle_layouts = layouts  # Plain names/layouts, no strong game references.
            self.report['crouch_idle_layouts'] = layouts
        result = []
        for name, offset, fields in layouts:
            node = getattr(anim, name)
            address = self.anim_address + offset
            table = int.from_bytes(self.native.read(address, 8), 'little')
            values = {}
            for field_name, kind, field_offset in fields:
                value = getattr(node, field_name)
                values[field_name] = bool(value) if kind == 'BoolProperty' else float(value) if kind in ('FloatProperty', 'DoubleProperty') else str(value)
                if isinstance(values[field_name], float) and not math.isfinite(values[field_name]):
                    raise RuntimeError('Nonfinite Crouch Idle state')
            result.append(dict(name=name, offset=offset,
                               receiver=hex(address), vtable=hex(table),
                               matches_reviewed_idle_vtable=table == self.idle_native.table,
                               is_existing_bound_node=name == self.IDLE_NODE_NAME,
                               values=values))
        return result

    def crouch_frame(self):
        """Rotate crouched locomotion without enabling Sprint/Dash publishers."""
        pc, pawn, camera, movement = self.bound()
        if (not self.mod._third_person_enabled or pc.bShowMouseCursor
                or not pawn.bIsCrouched or int(movement.MovementMode) != 1
                or int(movement.CustomMovementMode) != 0
                or pawn.IsCharacterDashing() or self.mod._slide_active
                or str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson'):
            return
        sample = self.report['samples'][-1]
        current = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
        now = sample['t']
        if self.impulse_index is None:
            if not sample['movement_input_active']:
                return
            self.original_rotation = dict(current)
            self.restore_pending = True
            self.impulse_index = self.frames
            self.follow_started_t = now
            self.follow_previous_t = now
            self.report['block_started_update_index'] = self.frames
            self.report['follow_started_t'] = now
        if not self.ready:
            self._bind_root()
        self.native.validate()
        dt = min(0.05, max(0.0, now - self.follow_previous_t))
        self.follow_previous_t = now
        combat = bool(self.combat['active'])
        free = not combat
        self.native.control[0] = int(free)
        self.native.control[7] = int(free)
        self.native.control[8] = self.native.base + 3026455
        for owner in (self.idle_native, self.idle_update, self.aim_native):
            owner.control[0] = int(free)
        self.aim_native.crouch_control[0] = int(free)
        target_yaw = sample['control_rotation']['Yaw'] if combat else sample['input_yaw'] if sample['movement_input_active'] else current['Yaw']
        gap = angle(target_yaw, current['Yaw'])
        step = min(abs(gap), (1080.0 if combat else 540.0) * dt)
        actual = dict(current)
        if step >= 0.01:
            target = dict(current, Yaw=angle(current['Yaw'] + math.copysign(step, gap), 0.0))
            result = self.set_rotation(pawn, target)
            actual = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            if not result or any(abs(angle(actual[k], target[k])) > 0.1 for k in ('Pitch', 'Yaw', 'Roll')):
                raise RuntimeError('Crouch rotation setter/readback differs')
        sample['crouch_follow'] = dict(combat=combat, target_yaw=target_yaw, actor_after=actual, dt=dt)
        self.report['crouch_follow_updates'] = self.report.get('crouch_follow_updates', 0) + 1

    def _slide_live_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        if not self.updates.is_game_thread():
            return
        if not bool(self.mod._slide_active):
            self.aim_native.crouch_control[0] = 0
        was = self.slide_override_active
        self._slide_pose_frame(obj, args, ret, func)
        if not self.active:
            return
        if was and (not self.slide_override_active) and self.report['slide_caller_ab_cycles']:
            self.report['slide_caller_ab_cycles'][-1]['crouch_neutralizations_end'] = int(self.aim_native.crouch_control[3])
        self.trim_diagnostics()
        del self.report['slide_caller_ab_cycles'][:-64]
