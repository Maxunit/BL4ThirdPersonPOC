"""Slam responsibility; explicit pipeline calls, no historical probe inheritance."""
from .common import log as logging
from .common import TAG, angle

class SlamMixin:

    def _slam_state_close_slam(self, reason):
        if self.slam_cycle is None:
            return
        self.slam_cycle.update(end_update=self.frames, end_reason=reason)
        self.report['ground_slam_native_cycles'].append(self.slam_cycle)
        del self.report['ground_slam_native_cycles'][:-32]
        self.slam_cycle = None

    def _slam_state_paused_special_frame(self, obj, args, ret, func):
        self.native.slide_control[0] = 0
        self.consume_slam_records()
        self._special_paused_special_frame(obj, args, ret, func)
        if not self.active:
            return
        pc, pawn, camera, movement = self.bound()
        if str(camera.GetActorCameraMode(pawn)) != 'GroundSlamExit':
            self.close_slam('NATIVE_MODE_CHANGED')
            return
        if self.slam_cycle is None:
            self.slam_sequence += 1
            self.slam_cycle = dict(sequence=self.slam_sequence, start_update=self.frames, actor_yaw=float(pawn.K2_GetActorRotation().Yaw), control_yaw=float(pc.GetControlRotation().Yaw), record_count=0, caller_counts={})
            logging.warning(TAG + ' SLAM_NATIVE_CAPTURE sequence=' + str(self.slam_sequence) + ' recording original native arguments')
        if self.frames % 3 == 0 or self.slam_cycle['start_update'] == self.frames:
            row = self.capture_rotate_state()
            row.update(sequence=self.slam_sequence, camera_mode='GroundSlamExit', movement_mode=int(movement.MovementMode), custom_movement_mode=int(movement.CustomMovementMode))
            self.report['ground_slam_rotate_state_samples'].append(row)
            del self.report['ground_slam_rotate_state_samples'][:-256]
        if self.native.hook is not None:
            self.native.validate()
            self.native.slide_control[6] = self.frames
            if self.native.control[0] or self.native.control[7] or self.vector_trace.control[12]:
                raise RuntimeError('Exit diagnostic behavioral controls unexpectedly enabled')
            self.native.slide_control[0] = 1
            self.slam_trace_window = True

    def _slam_state_frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        try:
            if self.slam_trace_window:
                self.native.slide_control[0] = 0
                self.consume_slam_records()
            if self.slam_cycle is not None:
                pc, pawn, camera, movement = self.bound()
                if str(camera.GetActorCameraMode(pawn)) != 'GroundSlamExit':
                    self.close_slam('LEFT_GROUND_SLAM_EXIT')
            self._jump_frame(obj, args, ret, func)
        except Exception as exc:
            self.report['errors'].append('GroundSlam native observation: ' + repr(exc)[:500])
            try:
                self.finish('GROUND_SLAM_NATIVE_OBSERVER_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def disarm_slam_override(self):
        if self.slam_override_owned:
            self.native.control[0] = 0
            self.native.control[7] = 0
            self.slam_override_owned = False

    def _slam_body_close_slam(self, reason):
        self.disarm_slam_override()
        if self.slam_cycle is not None and 'replacement_count_start' in self.slam_cycle:
            self.slam_cycle['replacement_count_end'] = int(self.native.control[9])
            self.slam_cycle['exit_replacement_count'] = int(self.native.control[9]) - self.slam_cycle['replacement_count_start']
        self._slam_state_close_slam(reason)

    def _slam_body_paused_special_frame(self, obj, args, ret, func):
        self.disarm_slam_override()
        self._slam_state_paused_special_frame(obj, args, ret, func)
        if not self.active or self.slam_cycle is None:
            return
        cycle = self.slam_cycle
        if 'phase' not in cycle:
            cycle.update(phase='B', replacement_count_start=int(self.native.control[9]), eligible_updates=0)
            logging.warning(TAG + ' ' + ('B_NATIVE_ROOT_HOLD' if cycle['phase'] == 'B' else 'A_ORIGINAL_EXIT') + ' sequence=' + str(cycle['sequence']))
        pc, pawn, camera, movement = self.bound()
        free = str(camera.GetActorCameraMode(pawn)) == 'GroundSlamExit' and int(movement.MovementMode) == 1 and (int(movement.CustomMovementMode) == 0) and (self.impulse_index is not None) and (not self.combat['active']) and bool(self.mod._third_person_enabled) and (not bool(pc.bShowMouseCursor)) and (not any((bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active'))))
        elapsed = self.frames - cycle['start_update']
        enabled = cycle['phase'] == 'B' and free and (elapsed < 256) and (self.native.hook is not None)
        if enabled:
            self.native.validate()
            self.native.control[8] = self.native.base + 3026455
            self.native.control[6] = self.frames
            self.native.control[7] = 1
            self.slam_override_owned = True
            self.native.control[0] = 1
            cycle['eligible_updates'] += 1
        body = float(pawn.K2_GetActorRotation().Yaw)
        row = dict(sequence=cycle['sequence'], phase=cycle['phase'], update=self.frames, enabled=enabled, free=free, elapsed_updates=elapsed, body_yaw=body, captured_start_yaw=cycle['actor_yaw'], body_error_from_start=angle(body, cycle['actor_yaw']), control_yaw=float(pc.GetControlRotation().Yaw), replacement_count_delta=int(self.native.control[9]) - cycle['replacement_count_start'])
        self.report['ground_slam_native_ab_rows'].append(row)
        del self.report['ground_slam_native_ab_rows'][:-512]

    def _slam_body_frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        self.disarm_slam_override()
        self._slam_state_frame(obj, args, ret, func)

    def disarm_slam_pose(self):
        if self.slam_pose_owned:
            self.idle_native.control[0] = 0
            self.idle_update.control[0] = 0
            self.aim_native.control[0] = 0
            self.slam_pose_owned = False

    def close_slam(self, reason):
        self.disarm_slam_pose()
        c = self.slam_cycle
        if c is not None and 'pose_root_start' in c:
            c.update(pose_root_delta=int(self.idle_native.control[3]) - c['pose_root_start'], pose_idle_delta=int(self.idle_update.control[3]) - c['pose_idle_start'], pose_aim_delta=int(self.aim_native.control[3]) - c['pose_aim_start'])
        self._slam_body_close_slam(reason)

    def paused_special_frame(self, obj, args, ret, func):
        self.disarm_slam_pose()
        self._slam_body_paused_special_frame(obj, args, ret, func)
        if not self.active or self.slam_cycle is None:
            return
        c = self.slam_cycle
        if 'pose_root_start' not in c:
            c.update(pose_root_start=int(self.idle_native.control[3]), pose_idle_start=int(self.idle_update.control[3]), pose_aim_start=int(self.aim_native.control[3]))
        enabled = bool(self.slam_override_owned)
        if enabled:
            for owner in (self.idle_native, self.idle_update, self.aim_native):
                if owner.hook is None:
                    raise RuntimeError('Slam pose binding unavailable')
                owner.validate()
            self.slam_pose_owned = True
            self.idle_native.control[0] = 1
            self.idle_update.control[0] = 1
            self.aim_native.control[0] = 1
        anim = self.combat_refs[1]()
        if anim is None:
            raise RuntimeError('Slam pose animation expired')
        row = dict(sequence=c['sequence'], phase=c['phase'], update=self.frames, pose_enabled=enabled, body_yaw=float(self.bound()[1].K2_GetActorRotation().Yaw), aim_yaw=float(anim.AimYaw), aim_pitch=float(anim.AimPitch), root_delta=int(self.idle_native.control[3]) - c['pose_root_start'], idle_delta=int(self.idle_update.control[3]) - c['pose_idle_start'], aim_delta=int(self.aim_native.control[3]) - c['pose_aim_start'])
        self.report['ground_slam_pose_ab_rows'].append(row)
        del self.report['ground_slam_pose_ab_rows'][:-512]

    def _slam_pose_frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        self.disarm_slam_pose()
        self._slam_body_frame(obj, args, ret, func)
