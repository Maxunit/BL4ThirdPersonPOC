"""Air responsibility; explicit pipeline calls, no historical probe inheritance."""
import math
import struct
from typing import Any
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import TAG, angle, parts, direction

FREEFALL_YAW_RATE = 540.0  # Match the existing ground movement follow.


def freefall_yaw_step(owner, gap, dt):
    """Visual rotation step; preserve native/pending Dash and special modes."""
    _, pawn, _, movement = owner.bound()
    cycle = owner.air_cycle
    dash_pending = bool(cycle and (not cycle.get('prearmed', False)
                        or cycle.get('seen_dash', False) or cycle.get('vector_applied', False)
                        or 'press_observed_update' in cycle))
    freefall = (int(movement.MovementMode) == 3 and int(movement.CustomMovementMode) == 0
                and not bool(pawn.IsCharacterDashing())
                and not bool(movement.bWantsToDash) and not dash_pending)
    return min(abs(gap), FREEFALL_YAW_RATE * min(dt, 0.05)) if freefall else abs(gap)


class AirMixin:

    def use_air_facing(self, reason):
        if reason not in ('JUMP_INPUT', 'AIRBORNE') or self.impulse_index is None:
            return False
        pc, pawn, camera, movement = self.bound()
        if bool(pawn.bIsCrouched) or bool(getattr(self.mod, '_slide_active', False)):
            return False
        if int(movement.MovementMode) == 3:
            return True
        return not bool(self.air_dash_down(pc)) and (not bool(pawn.IsCharacterDashing()))

    def _air_paused_frame(self, obj, args, ret, func, reason):
        if not self.use_air_facing(reason):
            self.air_previous_t = None
            return self._handoff_paused_frame(obj, args, ret, func, reason)
        self.air_frame(obj, args, ret, func, reason)

    def drain_air_vector_records(self):
        sample = self.report['samples'][-1] if self.report['samples'] else {'movement_mode': None}
        records_before = len(self.report['vector_entry_records'])
        self.vector_trace.consume()
        for record in self.report['vector_entry_records'][records_before:]:
            if record['overridden'] and record['phase'] in ('AIR_MOVEMENT_VECTOR', 'AIR_LIVE_INPUT_VECTOR') and (self.air_cycle is None or int(self.vector_trace.control[8]) != 1):
                raise RuntimeError('Unexpected air diagnostic vector replacement')
            if record['phase'] == 'AIR_LIVE_INPUT_VECTOR' and record['overridden']:
                self.air_cycle.update(desired_vector=list(record['desired_input_vector']),
                                      target_source='NATIVE_INPUT_AT_DASH_HELPER',
                                      captured_input_source=record['input_source'],
                                      captured_native_enum=record['native_direction_at_entry'])
                self.report['air_live_targets'][-1].update(self.air_cycle)
                self.air_live_event('AIR_INPUT_CAPTURED_NATIVE', cycle=self.air_cycle['sequence'])
            self.report['air_vector_entry_records'].append(dict(record, observed_at_update=self.frames, observed_movement_mode=sample['movement_mode']))
            self.report['air_vector_entry_total'] += 1
            if record['phase'] in ('AIR_MOVEMENT_VECTOR', 'AIR_LIVE_INPUT_VECTOR') and record['overridden']:
                self.report['air_live_vector_overrides'] += 1
        count = int(self.vector_trace.control[3])
        if self.vector_trace.consumed != count:
            raise RuntimeError('Air vector recycle before consumption')
        self.report['vector_entry_record_total'] += count
        self.vector_trace.control[3] = 0
        self.vector_trace.consumed = 0

    def _air_close_air_cycle(self, outcome):
        if self.air_cycle is None:
            return
        self.vector_trace.control[12] = 0
        if self.vector_ready and self.updates.is_game_thread():
            self.drain_air_vector_records()
        row = dict(self.air_cycle, outcome=outcome, end_update=self.frames)
        row['vector_override_count'] = int(self.vector_trace.control[8])
        row['native_end_observed'] = outcome == 'NATIVE_AIR_DASH_ENDED'
        self.report['air_live_cycles'].append(row)
        if row['native_end_observed']:
            self.report['air_live_completed_cycles'] += 1
        self.air_live_event(outcome, cycle=row['sequence'])
        self.air_cycle = None
        self.air_prearm_weapon_ref = None

    def _air_prepare_air_cycle(self, sample, attempt, *, refresh=False):
        direction = attempt['handler_direction_raw']
        if direction not in (0, 1, 2, 3) or attempt['handler_has_direction_raw'] != 1:
            raise RuntimeError('Air direction binding invalid')
        self.validate_handler()
        trace = self.vector_trace
        cfg = struct.unpack('<Q', trace.read(self.movement_address + 17456, 8))[0]
        if not 65536 <= cfg < 140737488355328:
            raise RuntimeError('Air Dash config invalid')
        raw = trace.read(cfg + 144, 16)
        angles = struct.unpack('<4f', raw)
        factor = struct.unpack('<d', trace.read(trace.base + 163877400, 8))[0]
        if not all((math.isfinite(v) and abs(v) <= 360 for v in angles)) or not math.isfinite(factor) or (not 0 < factor < 0.1):
            raise RuntimeError('Air Dash angles invalid')
        body_yaw = float(sample['input_yaw'] if sample['movement_input_active'] and sample.get('input_yaw') is not None else attempt['actor_after']['Yaw'])
        if not math.isfinite(body_yaw):
            raise RuntimeError('Air body yaw invalid')
        body_radians = math.radians(body_yaw)
        x, y = (math.cos(body_radians), math.sin(body_radians))
        theta = angles[direction] * factor
        pre = (math.cos(theta) * x + math.sin(theta) * y, -math.sin(theta) * x + math.cos(theta) * y, 0.0)
        for enum, native_angle in enumerate(angles):
            offset = 40 + enum * 4
            trace.control[offset] = struct.unpack_from('<I', raw, enum * 4)[0]
            for slot, value in ((offset + 1, math.cos(native_angle * factor)),
                                (offset + 2, math.sin(native_angle * factor))):
                trace.control[slot] = struct.unpack('<Q', struct.pack('<d', value))[0]
        trace.control[8] = 0
        trace.control[13] = direction
        trace.control[14] = cfg
        trace.control[15] = struct.unpack_from('<I', raw, direction * 4)[0]
        for i, value in enumerate(pre, 9):
            trace.control[i] = struct.unpack('<Q', struct.pack('<d', value))[0]
        compensation = []
        for enum, angle in enumerate(angles):
            radians = angle * factor
            vector = (math.cos(radians) * x + math.sin(radians) * y, -math.sin(radians) * x + math.cos(radians) * y, 0.0)
            offset = 16 + enum * 4
            trace.control[offset] = struct.unpack_from('<I', raw, enum * 4)[0]
            for slot, value in enumerate(vector, offset + 1):
                trace.control[slot] = struct.unpack('<Q', struct.pack('<d', value))[0]
            compensation.append(list(vector))
        if refresh:
            cycle = self.air_cycle
            if cycle is None or cycle['vector_applied'] or cycle['seen_dash']:
                raise RuntimeError('Cannot refresh an admitted air dash')
            cycle.update(direction=direction, desired_vector=[x, y, 0.0],
                         captured_body_yaw=body_yaw, input_yaw_at_press=attempt.get('input_yaw'))
            self.report['air_live_targets'][-1].update(
                cycle, precompensated_vector=list(pre), native_angles=list(angles),
                actual_direction_compensation_table=compensation)
            return
        self.air_cycle_sequence += 1
        self.air_cycle = dict(sequence=self.air_cycle_sequence, request_update=self.frames, request_t=sample['t'], direction=direction, desired_vector=[x, y, 0.0], captured_body_yaw=float(attempt['actor_after']['Yaw']), prepared_input_yaw=body_yaw, target_source='INPUT_DIRECTION_PENDING_NATIVE_CAPTURE', input_yaw_at_press=attempt.get('input_yaw'), seen_dash=False, vector_applied=False, peak_horizontal_speed=0.0)
        self.report['air_live_targets'].append(dict(self.air_cycle, precompensated_vector=list(pre), native_angles=list(angles), actual_direction_compensation_table=compensation, angle_factor=factor, action_intent=dict(sample['action_intent'])))
        self.air_live_event('AIR_VECTOR_WINDOW_ARMED', cycle=self.air_cycle_sequence)

    def prearm_air_input(self, sample: dict[str, Any]) -> None:
        """Prepare the native input latch for a settled, free airborne owner."""
        pc, pawn, camera, movement = self.bound()
        if (not self.vector_ready or not self.route_ready
                or sample['movement_mode'] != 3 or self.combat['active']
                or sample['mouse_cursor'] or sample['custom_movement_mode'] != 0
                or pawn.IsCharacterDashing() or movement.bWantsToDash):
            return
        anim = self.clip_anim()
        weapon = camera.CameraModeInputs.Weapon
        if (weapon is None or anim.CurrentWeapon != weapon
                or str(weapon.CurrentState) != 'Active'):
            return
        self.vector_trace.validate_input_sources()
        # This placeholder configures the verified four-enum table. The actual
        # input and native enum are read at the native helper, not from this row.
        attempt = dict(handler_direction_raw=0, handler_has_direction_raw=1,
                       actor_after=sample['actor_rotation'], input_yaw=sample.get('input_yaw'))
        self.prepare_air_cycle(sample, attempt)
        self.air_prearm_weapon_ref = WeakPointer(weapon)
        self.air_cycle.update(prearmed=True, prepared_update=self.frames,
                              target_source='PENDING_NATIVE_INPUT_CAPTURE')
        self.report['air_live_targets'][-1].update(self.air_cycle)
        self.air_live_event('AIR_INPUT_PREPARED', cycle=self.air_cycle['sequence'])

    def air_facing_target(self, sample: dict[str, Any]) -> float:
        """Combat first; then the admitted dash latch, then live movement intent."""
        if self.combat['active']:
            return sample['control_rotation']['Yaw']
        if self.air_cycle is not None and int(self.vector_trace.control[8]) == 1:
            return direction(dict(zip(('X', 'Y', 'Z'), self.air_cycle['desired_vector'])))
        if sample['movement_input_active'] and sample.get('input_yaw') is not None:
            return sample['input_yaw']
        if self.bound()[1].IsCharacterDashing() and sample.get('velocity_yaw') is not None:
            return sample['velocity_yaw']
        return self.air_hold_yaw

    def air_frame(self, obj, args, ret, func, reason):
        press_count = self.air_circle_press_count
        self.air_frame_observe(obj, args, ret, func, reason)
        if not self.active:
            return
        sample = self.report['samples'][-1]
        native_dash = bool(self.bound()[1].IsCharacterDashing())
        if self.air_cycle is not None:
            cycle = self.air_cycle
            if int(self.vector_trace.control[8]) == 1 and (not cycle['vector_applied']):
                cycle['vector_applied'] = True
                self.air_live_event('AIR_VECTOR_APPLIED_ONCE', cycle=cycle['sequence'])
            if native_dash:
                if not cycle['seen_dash']:
                    cycle['seen_dash'] = True
                    cycle['dash_start_update'] = self.frames
                    cycle['dash_start_t'] = sample['t']
                    self.air_live_event('NATIVE_AIR_DASH_STARTED', cycle=cycle['sequence'])
                cycle['peak_horizontal_speed'] = max(cycle['peak_horizontal_speed'], sample['horizontal_speed'])
            if native_dash and cycle.get('prearmed', False) and not cycle['vector_applied']:
                self.close_air_cycle('AIR_NATIVE_INPUT_NOT_CAPTURED')
            elif self.combat['active']:
                self.close_air_cycle('AIR_COMBAT_HANDOFF')
            elif cycle['seen_dash'] and (not native_dash):
                self.close_air_cycle('NATIVE_AIR_DASH_ENDED')
            elif cycle['seen_dash'] and self.frames - cycle['dash_start_update'] >= 64:
                self.close_air_cycle('AIR_OBSERVATION_LIMIT')
            elif (not cycle.get('prearmed', False) or 'press_observed_update' in cycle) and not cycle['vector_applied'] and self.frames - cycle['request_update'] >= 16:
                self.close_air_cycle('AIR_VECTOR_WINDOW_EXPIRED')
            elif cycle.get('prearmed', False) and not cycle['vector_applied'] and not native_dash:
                anim = self.clip_anim()
                weapon = self.bound()[2].CameraModeInputs.Weapon
                if (weapon is None or self.air_prearm_weapon_ref() != weapon
                        or anim.CurrentWeapon != weapon
                        or str(weapon.CurrentState) != 'Active'
                        or any(getattr(anim, name).Sequence != self.clip_forward_ref()
                               for name, _, _, _ in self.clip_originals)):
                    self.close_air_cycle('AIR_INPUT_PREPARATION_WITHDRAWN')
        if self.air_circle_press_count > press_count:
            attempt = self.report['air_dash_attempts'][-1]
            axes = sample['action_intent']
            if self.air_cycle is not None and self.air_cycle.get('prearmed', False):
                self.air_cycle.setdefault('press_observed_update', self.frames)
                self.air_cycle['observed_input_yaw_at_press'] = attempt.get('input_yaw')
                self.air_cycle['request_update'] = self.frames
                self.air_live_event('AIR_INPUT_PRESS_OBSERVED', cycle=self.air_cycle['sequence'])
            elif self.air_cycle is not None or native_dash:
                self.air_live_event('AIR_PRESS_DURING_NATIVE_DASH')
            elif sample['movement_mode'] == 3 and (not self.combat['active']) and sample['movement_input_active']:
                v = sample['last_movement_input']
                if math.hypot(v['X'], v['Y']) > 0.2:
                    self.prepare_air_cycle(sample, attempt)
                else:
                    self.air_live_event('AIR_NO_DIRECTION_INPUT')
        if self.air_cycle is None and not native_dash:
            self.prearm_air_input(sample)
        if self.air_cycle is not None and (not self.air_cycle['vector_applied']) and (not self.combat['active']):
            self.vector_trace.control[0] = 1
            self.vector_trace.control[7] = 1
            self.vector_trace.validate_input_sources()
            self.vector_trace.control[12] = 4
        else:
            self.vector_trace.control[12] = 0
        self.trim_diagnostics()

    def resume_handoff(self):
        self.air_previous_t = None
        self.air_circle_previous = False
        self._handoff_resume_handoff()

    def _air_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Combined air callback outside owned game thread')
            action, reason = self.classify_handoff(*self.bound())
            if self.air_cycle is not None and (action == 'STOP' or int(self.bound()[3].MovementMode) != 3 or (not self.use_air_facing(reason))):
                self.vector_trace.control[12] = 0
                self.drain_air_vector_records()
                if not bool(self.bound()[1].IsCharacterDashing()) and self.air_cycle['seen_dash']:
                    self.close_air_cycle('NATIVE_AIR_DASH_ENDED')
                else:
                    self.close_air_cycle('AIR_STATE_HANDOFF')
            if self.handoff_reason in ('AIR_BODY_FOLLOW', 'AIR_COMBAT_AIM', 'AIR_NATIVE_DASH_FACING') and action == 'RUN':
                self.resume_handoff()
            self._handoff_frame(obj, args, ret, func)
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('COMBINED_AIR_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def _air_pose_frame(self, obj, args, ret, func):
        self._air_frame(obj, args, ret, func)
        if not self.collect_pose_diagnostics:
            return
        if not self.active or not self.report['samples']:
            return
        try:
            sample = self.report['samples'][-1]
            if self.animation_observer_start is None:
                self.animation_observer_start = sample['t']
            if sample['movement_mode'] != 3:
                return
            anim = self.anim_ref()
            pawn = self.bound()[1]
            mesh = pawn.Mesh
            if anim is None or mesh is None or mesh.AnimScriptInstance != anim:
                raise RuntimeError('Dash animation owner changed')
            inputs = {name: int(getattr(anim, name)) for name in self.DASH_INPUTS}
            state = tuple(inputs.values())
            if self.frames % 2 and state == self.animation_observer_last_state:
                return
            self.animation_observer_last_state = state
            players = []
            for name, key in self.DASH_PLAYERS:
                node = getattr(anim, name)
                if str(node.AnimAssetKey.TagName) != key:
                    raise RuntimeError('Reviewed Dash animation key changed: ' + name)
                weight = float(node.BlendWeight)
                time = float(node.InternalTimeAccumulator)
                if not math.isfinite(weight) or not math.isfinite(time):
                    raise RuntimeError('Nonfinite Dash animation observation')
                players.append({'name': name, 'key': key, 'blend_weight': weight, 'time': time})
            row = {'update_index': self.frames, 't': sample['t'], 'inputs': inputs, 'players': players, 'native_is_dashing': bool(pawn.IsCharacterDashing()), 'body_yaw': float(pawn.K2_GetActorRotation().Yaw), 'input_yaw': sample.get('input_yaw'), 'velocity_yaw': sample.get('velocity_yaw'), 'air_cycle': None if self.air_cycle is None else self.air_cycle['sequence']}
            self.report['air_dash_animation_samples'].append(row)
            del self.report['air_dash_animation_samples'][:-512]
            self.report['air_dash_animation_sample_total'] += 1
        except Exception as exc:
            self.report['errors'].append('Dash animation observation: ' + repr(exc)[:500])
            try:
                self.finish('ANIMATION_OBSERVER_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def disarm_jump_idle(self):
        if self.jump_idle_owned:
            self.idle_native.control[0] = 0
            self.idle_update.control[0] = 0
            self.jump_idle_owned = False

    def close_jump(self, reason):
        self.disarm_jump_idle()
        if self.jump_cycle is None:
            return
        c = self.jump_cycle
        c.update(end_update=self.frames, end_reason=reason, root_bypass_delta=int(self.idle_native.control[3]) - c['root_start'], idle_branch_delta=int(self.idle_update.control[3]) - c['idle_start'])
        self.report['jump_idle_ab_cycles'].append(c)
        del self.report['jump_idle_ab_cycles'][:-16]
        self.jump_cycle = None

    def configure_jump_idle(self, free):
        self.disarm_jump_idle()
        pc, pawn, camera, movement = self.bound()
        if int(movement.MovementMode) != 3:
            self.close_jump('LEFT_AIR')
            return
        if self.jump_cycle is None:
            self.jump_sequence += 1
            self.jump_cycle = dict(sequence=self.jump_sequence, phase='B', start_update=self.frames, root_start=int(self.idle_native.control[3]), idle_start=int(self.idle_update.control[3]), eligible_updates=0)
            logging.warning(TAG + ' JUMP_' + self.jump_cycle['phase'] + ' sequence=' + str(self.jump_sequence))
        c = self.jump_cycle
        eligible = free and bool(self.mod._third_person_enabled) and (not pc.bShowMouseCursor) and (str(camera.GetActorCameraMode(pawn)) == 'ThirdPerson') and (int(movement.CustomMovementMode) == 0) and (self.impulse_index is not None) and (not pawn.IsCharacterDashing()) and (not movement.bWantsToDash) and (not self.air_dash_down(pc)) and (not any((bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active'))))
        enabled = c['phase'] == 'B' and eligible and (self.frames - c['start_update'] < 256)
        if enabled:
            for owner in (self.idle_native, self.idle_update):
                if owner.hook is None:
                    raise RuntimeError('Jump IdleTurns binding unavailable')
                owner.validate()
            self.jump_idle_owned = True
            self.idle_native.control[0] = 1
            self.idle_update.control[0] = 1
            c['eligible_updates'] += 1
        anim = self.combat_refs[1]()
        if anim is None:
            raise RuntimeError('Jump animation expired')
        r = dict(sequence=c['sequence'], phase=c['phase'], update=self.frames, enabled=enabled, eligible=eligible, body_yaw=float(pawn.K2_GetActorRotation().Yaw), aim_yaw=float(anim.AimYaw), aim_pitch=float(anim.AimPitch), root_bypass_delta=int(self.idle_native.control[3]) - c['root_start'], idle_branch_delta=int(self.idle_update.control[3]) - c['idle_start'])
        self.report['jump_idle_ab_rows'].append(r)
        del self.report['jump_idle_ab_rows'][:-768]

    def _jump_frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        try:
            self.disarm_jump_idle()
            if self.jump_cycle is not None and int(self.bound()[3].MovementMode) != 3:
                self.close_jump('LEFT_AIR')
            self._special_frame(obj, args, ret, func)
        except Exception as exc:
            self.report['errors'].append('Jump IdleTurns AB: ' + repr(exc)[:500])
            try:
                self.finish('JUMP_IDLE_AB_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def configure_air_pose(self, free):
        # Air facing remains independent. A Slam owns its complete native
        # upper-body pose, rather than our ordinary jump/lean neutralisation.
        pose_free = free and not getattr(self, 'ground_slam_pose_native', False)
        self.aim_native.control[0] = int(pose_free)
        self.configure_jump_idle(pose_free)
        node = self.blend_node()
        if pose_free:
            if self.blend_original is None or int(node.AlphaInputType) != 1 or bool(node.bAlphaBoolEnabled):
                raise RuntimeError('Air Lean input no longer matches reviewed free body binding')
            if not self.blend_pending:
                if bool(node.bInvertAlpha) != self.blend_original:
                    raise RuntimeError('Air Lean changed before activation')
                self.blend_pending = True
                node.bInvertAlpha = False
                self.report['game_writes'] += 1
            if bool(node.bInvertAlpha):
                raise RuntimeError('Air Lean suppression overwritten')
        else:
            self.restore_blend()

    def air_frame_observe(self, obj, args, ret, func, reason):
        self.control[8] = 0
        self.dash_branch.control[0] = 0
        self.dash_branch.control[7] = 0
        air_mode = int(self.bound()[3].MovementMode) == 3
        self.vector_trace.control[12] = 0
        self.vector_trace.control[7] = int(air_mode)
        self.vector_trace.control[0] = int(air_mode)
        self.direction_trace.control[7] = 0
        self.index_trace.control[7] = 0
        self.control[0] = 0
        self.idle_native.control[0] = 0
        self.idle_update.control[0] = 0
        self.audit_owners()
        self.read_combat()
        self.native.control[0] = 1
        self.native.control[7] = 1
        free = not self.combat['active']
        self.configure_air_pose(free)
        if self.air_previous_t is None:
            previous_sample = self.report['samples'][-1] if self.report['samples'] else None
            self.air_hold_yaw = previous_sample['actor_rotation']['Yaw'] if previous_sample else float(self.bound()[1].K2_GetActorRotation().Yaw)
        self._sample_frame(obj, args, ret, func)
        if not self.active:
            return
        sample = self.report['samples'][-1]
        pc, pawn, camera, movement = self.bound()
        sample['sprint_state'] = {n: bool(getattr(movement, n)) for n in ('bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting')}
        if self.cycle_start is not None:
            self.close_cycle('DASH_NATIVE_HANDOFF', sample)
        if self.route_ready:
            self.consume_route()
            self.dash_branch.consume()
            self.pending_entries.clear()
            self.recycle_diagnostics()
        if self.vector_ready:
            self.drain_air_vector_records()
        for trace in (self.direction_trace, self.index_trace):
            if trace.hook is not None:
                trace.consume()
        now = sample['t']
        previous = self.follow_previous_t if self.air_previous_t is None else self.air_previous_t
        dt = min(0.05, max(0.0, now - previous))
        self.air_previous_t = now
        self.follow_previous_t = now
        current = sample['actor_rotation']
        target_yaw = self.air_facing_target(sample)
        if not self.combat['active']:
            self.air_hold_yaw = target_yaw
        gap = angle(target_yaw, current['Yaw'])
        step = min(abs(gap), 1080.0 * dt) if self.combat['active'] else freefall_yaw_step(self, gap, dt)
        if step >= 0.01:
            target = dict(current, Yaw=angle(current['Yaw'] + math.copysign(step, gap), 0.0))
            result = self.set_rotation(pawn, target)
            actual = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            if not result or any((abs(angle(actual[k], target[k])) > 0.1 for k in ('Pitch', 'Yaw', 'Roll'))):
                raise RuntimeError('Air facing setter/readback differs')
        else:
            actual = dict(current)
        native_dash = bool(pawn.IsCharacterDashing())
        circle = bool(self.air_dash_down(pc))
        state = 'AIR_COMBAT_AIM' if self.combat['active'] else 'AIR_NATIVE_DASH_FACING' if native_dash else 'AIR_BODY_FOLLOW'
        sample['handoff_state'] = state
        self.report['air_facing_updates'] += 1
        row = {'update_index': self.frames, 't': now, 'reason': reason, 'state': state, 'actor_before': dict(current), 'actor_after': actual, 'control_yaw': sample['control_rotation']['Yaw'], 'target_yaw': target_yaw, 'velocity_yaw': sample['velocity_yaw'], 'movement_mode': sample['movement_mode'], 'idle_override': bool(self.jump_idle_owned), 'sprint_override': False, 'dash_override': False, 'combat': bool(self.combat['active']), 'native_is_dashing': native_dash, 'circle_down': circle, 'wants_dash': bool(movement.bWantsToDash), 'velocity': dict(sample['velocity']), 'horizontal_speed': sample['horizontal_speed']}
        circle_press = circle and (not self.air_circle_previous)
        self.air_circle_previous = circle
        if circle_press:
            self.air_circle_press_count += 1
        if self.handoff_reason != state or self.frames % 6 == 0 or circle_press:
            self.validate_handler()
            row['action_intent'] = dict(sample['action_intent'])
            row['last_movement_input'] = dict(sample['last_movement_input'])
            row['input_yaw'] = sample['input_yaw']
            row['handler_direction_raw'], row['handler_has_direction_raw'] = struct.unpack('<2B', self.vector_trace.read(self.handler_address + 72, 2))
            row['movement_dash_direction_raw'] = self.vector_trace.read(self.movement_address + 17480, 1)[0]
            if circle_press:
                self.report['air_dash_attempts'].append(dict(row))
            self.report['air_facing_samples'].append(row)
            del self.report['air_facing_samples'][:-512]
        if self.handoff_reason != state:
            self.report['handoff_transitions'].append({'update_index': self.frames, 't': now, 'state': state, 'actor_before_yaw': current['Yaw'], 'actor_after_yaw': actual['Yaw'], 'target_yaw': target_yaw, 'control_yaw': sample['control_rotation']['Yaw']})
            self.handoff_reason = state
            logging.warning(TAG + ' ' + state)
        self.trim_diagnostics()
