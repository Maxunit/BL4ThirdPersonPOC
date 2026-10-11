"""Diagnostics responsibility; explicit pipeline calls, no historical probe inheritance."""
from time import monotonic
import math
import struct
from .common import log as logging
from .common import TAG, angle, parts, direction, describe

class DiagnosticsMixin:

    def _visual_visual(self):
        pc, pawn, camera, movement = self.bound()
        mesh = self.mesh_ref()
        if mesh is None or pawn.Mesh != mesh:
            raise RuntimeError('Bound visual Mesh changed')
        row = {'update_index': self.frames + 1, 'phase': 'BLOCK' if self.restore_pending else 'BASELINE', 'actor_rotation': parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll')), 'camera_rotation': parts(camera.GetCameraRotation(), ('Pitch', 'Yaw', 'Roll')), 'mesh_world_rotation': parts(mesh.K2_GetComponentRotation(), ('Pitch', 'Yaw', 'Roll')), 'mesh_relative_rotation': parts(mesh.RelativeRotation, ('Pitch', 'Yaw', 'Roll')), 'bones_world_rotation': {name: parts(mesh.GetSocketRotation(name), ('Pitch', 'Yaw', 'Roll')) for name in self.bones}}
        anim = getattr(mesh, 'AnimScriptInstance', None)
        if anim is not None:
            row['animation_instance'] = describe(anim)
            row['animation_aim'] = parts(anim, ('AimYaw', 'AimPitch'))
        return row

    def _aim_binding_visual(self):
        row = self._visual_visual()
        values, node = self.validate_visual(capture=True)
        row['animation_inputs'] = values
        channel, key = (str(node.RotationChannelName.TagName), str(node.BlendSpaceKey.TagName))
        alpha, weight = (float(node.ALPHA), float(node.BlendWeight))
        row['normal_aim_offset'] = {'channel': channel, 'blend_space_key': key, 'ALPHA': alpha, 'BlendWeight': weight, 'BlendSpace': describe(node.BlendSpace) if node.BlendSpace is not None else None, 'YawAxis': int(node.YawAxis), 'PitchAxis': int(node.PitchAxis)}
        movement = self.bound()[3]
        velocity = parts(movement.Velocity, ('X', 'Y', 'Z'))
        yaw = direction(velocity)
        row['velocity'] = velocity
        if yaw is not None:
            relative_actor = angle(yaw, row['actor_rotation']['Yaw'])
            relative_camera = angle(yaw, row['camera_rotation']['Yaw'])
            row['velocity_yaw'] = yaw
            row['velocity_relative_actor'] = relative_actor
            row['velocity_relative_camera'] = relative_camera
            row['animation_direction_minus_actor_relative_velocity'] = angle(values['Direction'], relative_actor)
            row['animation_direction_minus_camera_relative_velocity'] = angle(values['Direction'], relative_camera)
        return row

    def _combat_visual(self):
        row = self._aim_binding_visual()
        row['aim_ab_phase'] = self.phase or 'BASELINE'
        row['idle_update_branch_overrides'] = int(self.idle_update.control[3])
        row['idle_update_dispatches'] = int(self.idle_update.control[4])
        row['idle_update_override_enabled'] = bool(self.idle_update.control[0])
        row['idle_root_bypasses'] = int(self.idle_native.control[3])
        row['idle_root_guard_dispatches'] = int(self.idle_native.control[4])
        row['idle_root_bypass_enabled'] = bool(self.idle_native.control[0])
        row['aim_dispatch_calls'] = int(self.aim_native.control[4])
        row['aim_yaw_neutralizations'] = int(self.aim_native.control[3])
        return row

    def read_players(self, anim):
        result = {}
        for name, key in self.PLAYERS:
            node = getattr(anim, name)
            values = {field: float(getattr(node, field)) for field in self.FIELDS}
            if not all((math.isfinite(v) for v in values.values())):
                raise RuntimeError('Nonfinite focused player values: ' + name)
            asset = node.BlendSpace
            address = str(int(asset._get_address())) if asset is not None else '0'
            assets = self.report['player_assets']
            if address not in assets:
                if len(assets) >= 32:
                    raise RuntimeError('Focused asset change limit reached')
                assets[address] = describe(asset) if asset is not None else None
            values['asset_address'] = address
            result[name] = values
        return result

    def visual(self):
        started = monotonic()
        row = self._combat_visual()
        if self.collect_pose_diagnostics and (self.player_ready and (self.frames + 1) % self.PLAYER_STRIDE == 0):
            read_started = monotonic()
            try:
                snapshot = {'update_index': self.frames + 1, 't': monotonic() - self.started, 'nodes': self.read_players(self.anim_ref())}
                snapshot['player_read_cost_us'] = round((monotonic() - read_started) * 1000000.0, 1)
                rows = self.report['player_samples']
                if len(rows) >= self.PLAYER_LIMIT:
                    del rows[:len(rows) - self.PLAYER_LIMIT + 1]
                rows.append(snapshot)
            except Exception as exc:
                errors = self.report['player_read_errors']
                message = repr(exc)[:240]
                if message not in errors and len(errors) < 16:
                    errors[message] = self.frames + 1
        row['visual_capture_cost_us'] = round((monotonic() - started) * 1000000.0, 1)
        return row

    def snapshot_sprint(self, sample, movement):
        anim = self.anim_ref()
        if anim is None:
            raise RuntimeError('Sprint animation owner expired')
        players = anim.GbxAnimGraphNode_Locomotion_2.BlendSpacePlayers
        if len(players) != 2:
            raise RuntimeError('Sprint player storage differs')
        values = []
        for player in players:
            weight = float(player.BlendWeight)
            time = float(player.InternalTimeAccumulator)
            if not math.isfinite(weight) or not math.isfinite(time):
                raise RuntimeError('Nonfinite sprint player snapshot')
            values.append({'weight': weight, 'time': time, 'has_asset': player.BlendSpace is not None})
        row = {'update_index': self.frames, 't': sample['t'], 'phase': self.live_sprint_phase, 'actions': dict(sample['actions']), 'is_sprinting': bool(movement.bIsSprinting), 'speed': sample['horizontal_speed'], 'selected_index': struct.unpack('<i', self.native.read(self.selection_addresses['GbxAnimGraphNode_Locomotion_2'] + 52, 4))[0], 'players': values, 'direction_overrides': int(self.direction_trace.control[8]), 'index_overrides': int(self.index_trace.control[8])}
        rows = self.report['live_sprint_animation_samples']
        if len(rows) >= 512:
            del rows[:len(rows) - 511]
        rows.append(row)

    def event(self, event, **extra):
        row = {'event': event, 'update_index': self.frames, 't': monotonic() - self.started, **extra}
        self.report['manual_events'].append(row)
        logging.warning(TAG + ' ' + event)

    def trim_diagnostics(self):
        for value in self.report.values():
            if isinstance(value, list) and len(value) > 512:
                del value[:-512]

    def transition_event(self, reason):
        if reason == self.handoff_reason:
            return
        self.handoff_reason = reason
        self.report['handoff_transitions'].append({'update_index': self.frames, 't': monotonic() - self.started, 'state': reason})
        logging.warning(TAG + ' ' + reason)

    def air_live_event(self, event, **extra):
        self.report['air_live_events'].append(dict(event=event, update_index=self.frames, **extra))
        logging.warning(TAG + ' ' + event)

    def clip_event(self, event, **details):
        self.report['air_clip_events'].append(dict(update_index=self.frames, event=event, **details))
        del self.report['air_clip_events'][:-128]
        logging.warning(TAG + ' ' + event)

    def observe_clip_timing(self, event):
        anim = self.clip_anim()
        cycle = self.air_cycle
        row = dict(event=event, update_index=self.frames, cycle=None if cycle is None else cycle['sequence'], request_update=None if cycle is None else cycle['request_update'], dash_start_update=None if cycle is None else cycle.get('dash_start_update'), players=[])
        weapon = self.bound()[2].CameraModeInputs.Weapon
        row['weapon'] = None if weapon is None else describe(weapon)
        row['weapon_state'] = 'None' if weapon is None else str(weapon.CurrentState)
        for name, key in self.DASH_PLAYERS:
            node = getattr(anim, name)
            asset = node.Sequence
            row['players'].append(dict(name=name, key=str(node.AnimAssetKey.TagName), sequence=None if asset is None else describe(asset), weight=float(node.BlendWeight), time=float(node.InternalTimeAccumulator)))
        self.report['getter_clip_observations'].append(row)
        del self.report['getter_clip_observations'][:-128]

    def _native_entry_entry_counters(self):
        return [dict(action=action, entry_rva=hex(rva), total_calls=int(o.control[8]), enabled_calls=int(o.control[9]), handler_matches=int(o.control[10]), handler_and_thread_matches=int(o.control[11]), records=int(o.control[3]), expected_handler=hex(int(o.control[1])), expected_thread=int(o.control[2]), last_raw_rcx=hex(int(o.control[12])), last_raw_thread=int(o.control[13]), last_raw_caller_address=hex(int(o.control[14]))) for action, rva, o, t in self.entries]

    def entry_counters(self):
        result = self._native_entry_entry_counters()
        for row in result:
            row['records_total'] = self.report['native_circle_entry_record_total']
        return result

    def record_trial(self):
        t = self.ground_trial
        if t is None:
            return
        sample = self.report['samples'][-1]
        pc, pawn, camera, movement = self.bound()
        dash = bool(pawn.IsCharacterDashing())
        slide = bool(self.mod._slide_active)
        if self.cycle_start is None and self.air_cycle is None:
            t['override_count'] = max(t['override_count'], int(self.vector_trace.control[8]))
        t['rows'].append(dict(update=self.frames, native_dash=dash, slide=slide, speed=sample['horizontal_speed'], body_yaw=sample['actor_rotation']['Yaw'], velocity_yaw=sample.get('velocity_yaw'), target_error=None if sample.get('velocity_yaw') is None else angle(sample['velocity_yaw'], t['target_yaw'])))
        if dash and (not t['seen_dash']):
            t['seen_dash'] = True
            t['native_start_update'] = self.frames
        if t['seen_dash'] and (not dash) and ('native_end_update' not in t):
            t['native_end_update'] = self.frames
        outcome = None
        if slide:
            outcome = 'NATIVE_SLIDE_NO_VECTOR_OVERRIDE'
        elif self.cycle_start is not None or self.air_cycle is not None or int(movement.MovementMode) != 1:
            outcome = 'NATIVE_STATE_HANDOFF'
        elif self.combat['active'] or pawn.bIsCrouched:
            outcome = 'COMBAT_OR_CROUCH_HANDOFF'
        elif 'native_end_update' in t:
            outcome = 'NATIVE_DASH_ENDED'
        elif not t['seen_dash'] and self.frames - t['press_update'] >= 16:
            outcome = 'NO_NATIVE_DASH_IN_WINDOW'
        elif self.frames - t['press_update'] >= 96:
            outcome = 'OBSERVATION_LIMIT'
        if outcome:
            self.close_ground_trial(outcome)

    def observe_slide(self, previous):
        sliding = bool(self.mod._slide_active)
        rows = self.report['samples']
        if sliding and (not self.last_slide):
            self.report['sdk_slide_cycle_total'] += 1
            self.slide_cycle = dict(start_update=self.frames, reference='previous widget sample velocity; not an atomic Circle-entry capture', incoming_velocity_yaw=None if previous is None else previous.get('velocity_yaw'), incoming_speed=None if previous is None else previous.get('horizontal_speed'), rows=[])
            self.report['sdk_slide_cycles'].append(self.slide_cycle)
            del self.report['sdk_slide_cycles'][:-64]
        if self.slide_cycle is not None and rows:
            sample = rows[-1]
            target = self.slide_cycle['incoming_velocity_yaw']
            yaw = sample.get('velocity_yaw')
            self.slide_cycle['rows'].append(dict(update=self.frames, t=sample['t'], sliding=sliding, velocity_yaw=yaw, body_yaw=sample['actor_rotation']['Yaw'], camera_yaw=sample['camera_rotation']['Yaw'], speed=sample['horizontal_speed'], incoming_error=None if target is None or yaw is None else angle(yaw, target)))
            del self.slide_cycle['rows'][:-128]
        if not sliding and self.last_slide and (self.slide_cycle is not None):
            self.slide_cycle['end_update'] = self.frames
            self.slide_cycle = None
        self.last_slide = sliding

    def capture_rotate_state(self):
        pc, pawn, camera, movement = self.bound()
        self.validate_rotate_schema(movement)
        command = movement.CurrentRotateToState.CommandData
        raw = self.mod._native_read(int(movement._get_address()) + 12240, 144)
        if len(raw) != 144:
            raise RuntimeError('Short rotation-state read')
        self.report['rotate_state_native_reads'] = self.report.get('rotate_state_native_reads', 0) + 1
        actor = parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll'))
        control = parts(pc.GetControlRotation(), ('Pitch', 'Yaw', 'Roll'))
        camera_rotation = parts(camera.GetCameraRotation(), ('Pitch', 'Yaw', 'Roll'))
        velocity = parts(movement.Velocity, ('X', 'Y', 'Z'))
        values = {name: float(getattr(command, name)) for name in ('Duration', 'InterpSpeed', 'MaxYawRate', 'MaxPitchRate')}
        if not all((math.isfinite(v) for v in values.values())):
            raise RuntimeError('Nonfinite rotation-command parameter')
        target = command.TargetActor
        data = dict(values, TargetActor=None if target is None else describe(target), TargetSocket=str(command.TargetSocket), TargetLocation_storage=parts(command.TargetLocation, ('X', 'Y', 'Z')), bFreezeRotation=bool(command.bFreezeRotation), bUseEasing=bool(command.bUseEasing), bUpdateCamera=bool(command.bUpdateCamera))
        return dict(update=self.frames, t=monotonic(), sliding=bool(self.mod._slide_active), actor_rotation=actor, control_rotation=control, camera_rotation=camera_rotation, velocity=velocity, velocity_yaw=direction(velocity), command=data, state_raw_hex=raw.hex())

    def _slide_pose_capture_head(self):
        pc, pawn, camera, movement = self.bound()
        mesh = self.head_mesh()
        anim = self.head_anim()
        if mesh is None or anim is None or pawn.Mesh != mesh or (mesh.AnimScriptInstance != anim):
            raise RuntimeError('Head pose object lifetime/ownership changed')
        values = {k: float(getattr(anim, k)) for k in ('AimYaw', 'AimPitch', 'AimEnableAlpha', 'HeadEnableAlpha')}
        if not all((math.isfinite(v) for v in values.values())):
            raise RuntimeError('Nonfinite head/Aim input')
        nodes = []
        for name in self.AIM_NODES:
            node = getattr(anim, name)
            weight = float(node.BlendWeight)
            alpha = float(node.ALPHA)
            if not math.isfinite(weight) or not math.isfinite(alpha):
                raise RuntimeError('Nonfinite Aim node weight')
            asset = node.BlendSpace
            nodes.append(dict(name=name, channel=str(node.RotationChannelName.TagName), key=str(node.BlendSpaceKey.TagName), alpha=alpha, blend_weight=weight, alpha_input_type=int(node.AlphaInputType), invert_alpha=bool(node.bInvertAlpha), blend_space=None if asset is None else describe(asset)))
        return dict(update=self.frames, t=monotonic(), sliding=bool(self.mod._slide_active), actor_rotation=parts(pawn.K2_GetActorRotation(), ('Pitch', 'Yaw', 'Roll')), mesh_rotation=parts(mesh.K2_GetComponentRotation(), ('Pitch', 'Yaw', 'Roll')), control_rotation=parts(pc.GetControlRotation(), ('Pitch', 'Yaw', 'Roll')), velocity=parts(movement.Velocity, ('X', 'Y', 'Z')), bone_world_rotations={n: parts(mesh.GetSocketRotation(n), ('Pitch', 'Yaw', 'Roll')) for n in self.BONE_NAMES}, animation_inputs=values, aim_nodes=nodes)

    def capture_head(self):
        row = self._slide_pose_capture_head()
        row['crouched'] = bool(self.bound()[1].bIsCrouched)
        row['crouch_aim_enabled'] = int(self.aim_native.crouch_control[0])
        row['crouch_aim_dispatch_calls'] = int(self.aim_native.crouch_control[4])
        row['crouch_aim_neutralizations'] = int(self.aim_native.crouch_control[3])
        return row

    def state_context(self, objects=None):
        # The special-state stage passes its just-validated bound tuple directly.
        # No storage or reuse across stages/callbacks; standalone diagnostics
        # still resolve the current runtime themselves.
        current = tuple(self.mod._get_runtime()) if objects is None else objects[:3]
        row = dict(update_index=self.frames, t=monotonic() - self.started, flags={k: bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active')}, third_person=bool(self.mod._third_person_enabled))
        if self.collect_pose_diagnostics:
            row['current_objects'] = [None if o is None else describe(o) for o in current]
        live = tuple((ref() for ref in self.refs)) if objects is None else objects
        row['bound_identity_matches'] = [a is not None and b is not None and (a == b) for a, b in zip(live[:3], current)]
        if len(current) == 3 and all((o is not None for o in current)):
            pc, pawn, camera = current
            movement = getattr(pawn, 'OakCharacterMovement', None) if objects is None else objects[3]
            row['mouse_cursor'] = bool(pc.bShowMouseCursor)
            row['camera_mode'] = str(camera.GetActorCameraMode(pawn)) if objects is None else self.camera_mode(pawn, camera)
            if movement is not None:
                row['movement_mode'] = int(movement.MovementMode)
                row['custom_movement_mode'] = int(movement.CustomMovementMode)
                row['movement_identity_matches'] = live[3] is not None and live[3] == movement
        return row

    def save_state_edge(self, row, event):
        if 'current_objects' not in row:
            row = dict(row, current_objects=[describe(o) for o in self.bound()[:3]])
        row = dict(row, event=event)
        self.report['special_state_edges'].append(row)
        del self.report['special_state_edges'][:-256]
        self.report['last_lifecycle_context'] = row
        logging.warning(TAG + ' ' + event + ' movement=' + str(row.get('movement_mode')) + ' custom=' + str(row.get('custom_movement_mode')) + ' camera=' + str(row.get('camera_mode')))

    def consume_slam_records(self):
        before = len(self.report['slide_rotation_arguments'])
        self.native.consume_slide()
        records = self.report['slide_rotation_arguments'][before:]
        if self.slam_trace_window:
            cycle = self.slam_cycle
            for record in records:
                row = dict(record, sequence=None if cycle is None else cycle['sequence'], decoded_at_update=self.frames, observed_interval='GroundSlamExit')
                self.report['ground_slam_native_records'].append(row)
                if cycle is not None:
                    cycle['record_count'] += 1
                    caller = record['caller_return_rva']
                    cycle['caller_counts'][caller] = cycle['caller_counts'].get(caller, 0) + 1
            del self.report['ground_slam_native_records'][:-512]
        self.slam_trace_window = False

    def observe_ground_input_pose(self, phase):
        if not self.collect_pose_diagnostics:
            return
        if not self.active or not self.updates.is_game_thread():
            return
        try:
            pc, pawn, camera, movement = self.bound()
            if int(movement.MovementMode) != 1 or int(movement.CustomMovementMode) != 0:
                return
            if str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
                return
            if bool(pc.bShowMouseCursor) or bool(self.mod._vehicle_camera_active):
                return
            actions = self.inputs.snapshot(pc)
            dashing = bool(pawn.IsCharacterDashing())
            wish = bool(movement.bWantsToDash)
            sprint = bool(movement.bIsSprinting)
            handler = self.validate_handler()
            enum, has = struct.unpack('<2B', self.vector_trace.read(self.handler_address + 72, 2))
            state = (tuple(actions.values()), dashing, wish, sprint, enum, has)
            changed = state != self.ground_observer_state.get(phase)
            self.ground_observer_state[phase] = state
            action = any((actions[k] for k in ('sprint', 'dash', 'crouch')))
            if not changed and (not (action or dashing or wish) or self.frames % 2):
                return
            velocity = movement.Velocity
            vx = float(velocity.X)
            vy = float(velocity.Y)
            speed = math.hypot(vx, vy)
            if not all((math.isfinite(v) for v in (vx, vy, speed))):
                raise RuntimeError('Nonfinite ground observation velocity')
            row = dict(phase=phase, update_index=self.frames, t=monotonic() - self.started, actions=actions, native_dash=dashing, native_dash_wish=wish, native_sprint=sprint, handler_direction=enum, handler_has_direction=has, body_yaw=float(pawn.K2_GetActorRotation().Yaw), camera_yaw=float(pc.GetControlRotation().Yaw), velocity_xy=[vx, vy], speed=speed, velocity_yaw=math.degrees(math.atan2(vy, vx)) if speed > 1 else None, custom_dash_cycle=self.cycle_start, ground_circle_trial=self.ground_trial is not None, input_route_total=self.report.get('input_route_total', 0), players=[])
            last_input = pawn.GetLastMovementInputVector()
            row['last_movement_input_xy'] = [float(last_input.X), float(last_input.Y)]
            row['movement_input_xy'] = row['last_movement_input_xy']
            prepared = getattr(self, 'ground_prepared', None)
            row['prepared_circle_target'] = None if prepared is None else dict(update=prepared['previous_update'], yaw=prepared['target_yaw'], vector=list(prepared['target_vector']))
            anim = self.clip_anim()
            row['animation_inputs'] = {k: int(getattr(anim, k)) for k in self.DASH_INPUTS}
            for name, key in self.DASH_PLAYERS:
                node = getattr(anim, name)
                actual_key = str(node.AnimAssetKey.TagName)
                asset = node.Sequence
                address = 0 if asset is None else int(asset._get_address())
                asset_id = hex(address)
                if asset is not None and asset_id not in self.ground_observer_assets and (len(self.ground_observer_assets) < 64):
                    self.ground_observer_assets[asset_id] = describe(asset)
                weight = float(node.BlendWeight)
                time = float(node.InternalTimeAccumulator)
                if not math.isfinite(weight) or not math.isfinite(time):
                    raise RuntimeError('Nonfinite ground Dash player state')
                row['players'].append(dict(name=name, expected_key=key, key=actual_key, key_matches=actual_key == key, sequence=asset_id, weight=weight, time=time))
            self.report['ground_input_pose_assets'] = dict(self.ground_observer_assets)
            self.report['ground_input_pose_rows'].append(row)
            del self.report['ground_input_pose_rows'][:-1024]
            self.report['ground_input_pose_total'] += 1
        except Exception as exc:
            errors = self.report['ground_input_pose_diagnostic_errors']
            errors.append(dict(phase=phase, update=self.frames, error=repr(exc)[:400]))
            del errors[:-32]

    def ground_clip_event(self, event, **details):
        self.report['ground_clip_events'].append(dict(update=self.frames, event=event, **details))
        del self.report['ground_clip_events'][:-64]
        logging.warning(TAG + ' ' + event)
