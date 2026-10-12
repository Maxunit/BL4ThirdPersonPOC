"""Slam responsibility; explicit pipeline calls, no historical probe inheritance."""
from .common import log as logging
from .common import TAG, angle

class SlamMixin:

    def native_slam_pose_context(self, pawn, camera, movement):
        mode = self.camera_mode(pawn, camera)
        return (self.is_ground_slamming(pawn, movement) or mode == 'GroundSlamExit'
                or (getattr(self, 'ground_slam_pose_native', False) and mode == 'ThirdPerson'
                    and bool(camera.CameraModeState.bIsTransitioning)))

    def release_native_slam_pose(self):
        # Release every pose input before the Special pipeline. The separate
        # final heading publication may hold only the audited TurnState caller.
        self.native.control[0] = self.native.control[7] = 0
        self.idle_native.control[0] = self.idle_update.control[0] = 0
        self.aim_native.control[0] = self.aim_native.crouch_control[0] = 0
        self.slam_override_owned = self.slam_pose_owned = False
        self.disarm_jump_idle()

    def disarm_slam_heading(self):
        if getattr(self, 'slam_heading_owned', False):
            self.native.control[0] = self.native.control[7] = 0
            self.slam_heading_owned = False
            self.report['ground_slam_heading_hold']['enabled'] = False

    def publish_native_slam_heading(self):
        """Hold only the audited TurnState dispatch; leave skeletal pose native.

        The .38 request capture identifies return RVA 0x2e2e17 at the airborne
        heading change. The existing guarded prefix forwards the component's
        current quaternion for this caller only. No actor setter or saved-yaw
        snapback, no Aim/Idle controls, and no movement-delta interception.
        Publish after the legacy Special pipeline has closed its gates.
        """
        owned = getattr(self, 'slam_heading_owned', False)
        if not getattr(self, 'ground_slam_pose_native', False):
            self.disarm_slam_heading()
            return
        self.native.control[0] = self.native.control[7] = 0
        self.slam_heading_owned = False
        if not self.active or not self.updates.is_game_thread():
            return
        pc, pawn, camera, movement = self.bound()
        mode = self.camera_mode(pawn, camera)
        free = (self.mod._third_person_enabled and mode in ('ThirdPerson', 'GroundSlamExit')
                and self.impulse_index is not None and not self.combat['active']
                and not pc.bShowMouseCursor and not any(bool(getattr(self.mod, name, False))
                    for name in ('_ads_active', '_vehicle_camera_active',
                                 '_shop_camera_active', '_ladder_active', '_slide_active')))
        state = self.report.setdefault('ground_slam_heading_hold',
            dict(enabled=False, eligible_updates=0, caller_return_rva='0x2e2e17'))
        state.update(enabled=False, update=self.frames, camera_mode=mode)
        if not free:
            return
        if any((self.idle_native.control[0], self.idle_update.control[0],
                self.aim_native.control[0], self.aim_native.crouch_control[0])):
            raise RuntimeError('Native Slam pose controls unexpectedly enabled')
        if self.native.hook is None:
            raise RuntimeError('Slam heading requires the installed owned TurnState guard')
        if not owned:
            self.native.validate()
        self.native.control[8] = self.native.base + 0x2E2E17
        self.native.control[7] = 1
        self.native.control[0] = 1
        self.slam_heading_owned = True
        state.update(enabled=True, eligible_updates=state['eligible_updates']+1)

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
            cycle.update(phase='NATIVE_SLAM_POSE', replacement_count_start=int(self.native.control[9]), eligible_updates=0)
            logging.warning(TAG + ' NATIVE_SLAM_POSE sequence=' + str(cycle['sequence']))
        pc, pawn, camera, movement = self.bound()
        free = str(camera.GetActorCameraMode(pawn)) == 'GroundSlamExit' and int(movement.MovementMode) == 1 and (int(movement.CustomMovementMode) == 0) and (self.impulse_index is not None) and (not self.combat['active']) and bool(self.mod._third_person_enabled) and (not bool(pc.bShowMouseCursor)) and (not any((bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active'))))
        elapsed = self.frames - cycle['start_update']
        # This legacy observer never enables the old combined body/pose hold.
        # The final publication can hold only TurnState, with Aim/Idle native.
        enabled = False
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
        enabled = False
        if not self.collect_pose_diagnostics:
            return
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
