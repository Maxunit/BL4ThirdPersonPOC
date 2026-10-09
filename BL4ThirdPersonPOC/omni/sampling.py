"""Sampling responsibility; explicit pipeline calls, no historical probe inheritance."""
from time import monotonic, perf_counter_ns
import math
from unrealsdk import make_struct
from .common import log as logging
from .common import TAG, FRAME_STRIDE, angle, parts, direction, movement_input_state

class SamplingMixin:

    def bound(self):
        live = tuple((ref() for ref in self.refs))
        if any((o is None for o in live)):
            raise RuntimeError('Bound gameplay objects expired')
        current = tuple(self.mod._get_runtime())
        if any((o is None for o in current)) or any((a != b for a, b in zip(live[:3], current))):
            raise RuntimeError('Local player or camera changed')
        if live[1].OakCharacterMovement != live[3]:
            raise RuntimeError('Movement component changed')
        return live

    def optional(self, sample, name, read):
        if name in self.report['optional_field_errors']:
            return
        try:
            sample[name] = read()
        except Exception as exc:
            self.report['optional_field_errors'][name] = repr(exc)[:300]

    def jump_down(self, pc):
        return self.inputs.snapshot(pc)['jump']

    def air_dash_down(self, pc):
        actions = self.inputs.snapshot(pc)
        return actions['crouch'] or (int(self.bound()[3].MovementMode) == 3 and actions['dash'])

    def controls_down(self, pc):
        actions = self.inputs.snapshot(pc)
        return any((actions[role] for role in ('sprint', 'dash', 'crouch', 'jump')))

    def _sample_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        self.busy = True
        tick_start = perf_counter_ns()
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Observer callback is not on owned game thread')
            pc, pawn, camera, movement = self.bound()
            self.frames += 1
            if self.frames % FRAME_STRIDE:
                return
            actions = self.inputs.snapshot(pc)
            history = self.report.setdefault('input_mapping_history', [])
            # Metadata reads every bound key name; build it only on a revision edge.
            if not history or history[-1]['revision'] != self.inputs.revision:
                history.append(dict(self.inputs.metadata(), update_index=self.frames))
                del history[:-16]
            actor = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            control = parts(pc.GetControlRotation(), ('Pitch', 'Yaw', 'Roll'))
            view = parts(camera.GetCameraRotation(), ('Pitch', 'Yaw', 'Roll'))
            velocity = parts(movement.Velocity, ('X', 'Y', 'Z'))
            acceleration = parts(movement.Acceleration, ('X', 'Y', 'Z'))
            input_vector = parts(pawn.GetLastMovementInputVector(), ('X', 'Y', 'Z'))
            selected_input = input_vector
            input_phase = 'last'
            pending_input = None
            if int(movement.MovementMode) == 3:
                pending_input = parts(pawn.GetPendingMovementInputVector(), ('X', 'Y', 'Z'))
                if math.hypot(pending_input['X'], pending_input['Y']) > 0.2:
                    selected_input = pending_input
                    input_phase = 'pending'
            input_state = movement_input_state(selected_input)
            mode = str(camera.GetActorCameraMode(pawn))
            ui = bool(pc.bShowMouseCursor)
            special = {f: bool(getattr(self.mod, f, False)) for f in ('_ads_active', '_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active')}
            s = {'t': monotonic() - self.started, 'update_index': self.frames, 'actions': actions, **input_state, 'action_intent': actions, 'action_change': actions != self.previous_actions, 'actor_rotation': actor, 'control_rotation': control, 'camera_rotation': view, 'velocity': velocity, 'acceleration': acceleration, 'last_movement_input': input_vector, 'horizontal_speed': math.hypot(velocity['X'], velocity['Y']), 'velocity_yaw': direction(velocity), 'acceleration_yaw': direction(acceleration), 'input_yaw': direction(selected_input), 'camera_minus_actor': angle(view['Yaw'], actor['Yaw']), 'control_minus_actor': angle(control['Yaw'], actor['Yaw']), 'camera_minus_control': angle(view['Yaw'], control['Yaw']), 'camera_mode': mode, 'mouse_cursor': ui, 'special_states': special, 'movement_mode': int(movement.MovementMode), 'custom_movement_mode': int(movement.CustomMovementMode), 'normal_tps_sample': mode == 'ThirdPerson' and (not ui) and (not any((value for field, value in special.items() if field != '_ads_active'))) and (int(movement.MovementMode) == 1), 'combat': dict(self.combat), 'orientation_flags': {'orient_to_movement': bool(movement.bOrientRotationToMovement), 'controller_desired_rotation': bool(movement.bUseControllerDesiredRotation), 'controller_yaw': bool(pawn.bUseControllerRotationYaw)}}
            s.update(movement_input_vector=selected_input, movement_input_phase=input_phase, pending_movement_input=pending_input)
            if s['velocity_yaw'] is not None:
                s['velocity_minus_camera'] = angle(s['velocity_yaw'], view['Yaw'])
                s['velocity_minus_actor'] = angle(s['velocity_yaw'], actor['Yaw'])
            mesh = getattr(pawn, 'Mesh', None)
            if mesh is not None:
                self.optional(s, 'mesh_relative_rotation', lambda: parts(mesh.RelativeRotation, ('Pitch', 'Yaw', 'Roll')))
                anim = getattr(mesh, 'AnimScriptInstance', None)
                if anim is not None:
                    self.optional(s, 'animation_aim', lambda: parts(anim, ('AimYaw', 'AimPitch')))
            self.previous_actions = actions
            s['sample_cost_us'] = (perf_counter_ns() - tick_start) / 1000.0
            self.report['samples'].append(s)
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('STOPPED_ON_ERROR')
            except Exception as cleanup:
                logging.error(TAG + ' CLEANUP_OR_SAVE_FAILED ' + repr(cleanup))
        finally:
            self.busy = False

    def _root_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Trace callback outside owned game thread')
            pc, pawn, camera, movement = self.bound()
            if not self.ready:
                self.native.install()
                self.ready = True
            self.native.validate()
            self.native.control[6] = self.frames + 1
            self.native.consume()
            before = len(self.report['samples'])
            self._sample_frame(obj, args, ret, func)
            if not self.active:
                return
            if len(self.report['samples']) > before:
                sample = self.report['samples'][-1]
                sample['native_record_end'] = len(self.report['native_records'])
                if not sample['normal_tps_sample']:
                    self.finish('LEFT_NORMAL_TPS')
                    return
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('STOPPED_ON_ERROR')
            except Exception as cleanup:
                logging.error(TAG + ' CLEANUP_OR_SAVE_FAILED rerun to retry ' + repr(cleanup))

    def set_rotation(self, pawn, value):
        if not self.updates.is_game_thread():
            raise RuntimeError('Actor rotation writes require owned game thread')
        self.report['game_writes'] += 1
        return bool(pawn.K2_SetActorRotation(make_struct('/Script/CoreUObject.Rotator', **value), False))

    def _body_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        self._root_frame(obj, args, ret, func)
        if not self.active:
            return
        try:
            sample = self.report['samples'][-1]
            now = sample['t']
            if self.impulse_index is None:
                if not (sample['normal_tps_sample'] and sample['horizontal_speed'] > 100 and sample['movement_input_active']):
                    return
                self.original_rotation = dict(sample['actor_rotation'])
                self.restore_pending = True
                self.impulse_index = self.frames
                self.follow_started_t = now
                self.follow_previous_t = now
                self.native.control[7] = 1
                self.report['block_started_update_index'] = self.frames
                self.report['follow_started_t'] = now
                logging.warning(TAG + ' FOLLOW_ACTIVE WASD/stick direction follows; camera may be moved; no duration limit; rerun to stop and restore')
            dt = min(0.05, max(0.0, now - self.follow_previous_t))
            self.follow_previous_t = now
            combat_active = sample['combat']['active']
            sample['follow_mode'] = 'COMBAT_AIM' if combat_active else 'IDLE_HOLD' if sample['horizontal_speed'] <= 30 else 'MOVEMENT_FOLLOW'
            if sample['follow_mode'] != getattr(self, 'follow_mode', None):
                self.follow_mode = sample['follow_mode']
                logging.warning(TAG + ' ' + self.follow_mode + ' rerun script to stop and restore')
            if not combat_active and (sample['horizontal_speed'] <= 30 or sample['velocity_yaw'] is None):
                return
            target_yaw = sample['control_rotation']['Yaw'] if combat_active else sample['velocity_yaw']
            yaw_rate = 1080.0 if combat_active else 540.0
            pc, pawn, camera, movement = self.bound()
            current = sample['actor_rotation']
            gap = angle(target_yaw, current['Yaw'])
            step = min(abs(gap), yaw_rate * dt)
            target = dict(current, Yaw=angle(current['Yaw'] + math.copysign(step, gap), 0.0))
            if step < 0.01:
                return
            result = self.set_rotation(pawn, target)
            actual = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
            sample['follow'] = {'velocity_target_yaw': sample['velocity_yaw'], 'follow_target_yaw': target_yaw, 'mode': sample['follow_mode'], 'yaw_rate': yaw_rate, 'dt': dt, 'target': target, 'setter_return': result, 'immediate_actor_rotation': actual}
            if not result or any((abs(angle(actual[k], target[k])) > 0.1 for k in ('Pitch', 'Yaw', 'Roll'))):
                raise RuntimeError('Follow setter/readback differs; restore immediately')
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('STOPPED_ON_ERROR')
            except Exception as cleanup:
                logging.error(TAG + ' RESTORE_OR_SAVE_FAILED rerun to retry ' + repr(cleanup))
