"""Ground responsibility; explicit pipeline calls, no historical probe inheritance."""
from .rebind_cache import layout_query
from time import monotonic
import ctypes
import hashlib
import math
import struct
from ..build_gate import REVIEWED_BUILD
import threading
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import TAG, angle, direction, describe, reflected_fields
from .native_movement import CircleEntry_CAPACITY, TRACE_SPECS

class GroundMixin:

    def bind_visual(self):
            self._lean_bind_visual()
            anim = self.anim_ref()
            props = layout_query('fields', self, anim)
            p = props.get('GbxAnimGraphNode_Locomotion_2')
            if p is None or str(p.Class.Name) != 'StructProperty' or str(p.Struct.Name) != 'GbxAnimNode_Locomotion' or (int(p.Offset_Internal) != 38928):
                raise RuntimeError('Reviewed sprint Locomotion node differs')
            base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
            if hashlib.sha256(self.native.read(base + 25601096, 742)).hexdigest() != 'f863c0088795d163ae37c2bb00fecbb83ca557510584d32d0fc948ad6e1e4033':
                raise RuntimeError('Reviewed Locomotion update code differs')
            node = int(anim._get_address()) + 38928
            if self.native.u64(node) != base + 185185344 or self.native.u64(base + 185185344 + 32) != base + 25601096:
                raise RuntimeError('Reviewed sprint-node update binding differs')
            self.selection_addresses = {'GbxAnimGraphNode_Locomotion_2': node}
            players = anim.GbxAnimGraphNode_Locomotion_2.BlendSpacePlayers
            if len(players) != 2:
                raise RuntimeError('Reviewed two-player sprint layout differs')
            if str(players[0].AnimAssetKey.TagName) != 'AnimSet.Player.3rd.BS_Sprint' or str(players[1].AnimAssetKey.TagName) != 'AnimSet.Player.3rd.Run_B':
                raise RuntimeError('Reviewed sprint player keys differ')

    def restore_sprint_intent(self):
        if not self.sprint_pending:
            return
        movement = self.refs[3]()
        if movement is None:
            raise RuntimeError('Sprint intent owner expired; no write')
        for name, value in self.saved_sprint_intent.items():
            setattr(movement, name, value)
            self.report['game_writes'] += 1
            if bool(getattr(movement, name)) != value:
                raise RuntimeError('Sprint intent restore differs: ' + name)
        self.sprint_pending = False
        self.report['sprint_intent_restoration_verified'] = True

    def validate_handler(self):
        # Handler ownership cannot change inside one owned callback.
        cached = getattr(self, '_callback_handler', None)
        if cached is not None:
            return cached
        handler = self._validate_handler()
        if getattr(self, '_callback_scope', False):
            self._callback_handler = handler
        return handler

    def _validate_handler(self):
        handler, component = (self.handler_ref(), self.component_ref())
        if handler is None or component is None or int(handler._get_address()) != self.handler_address:
            raise RuntimeError('Serial-bound OnFoot handler expired')
        if self.bound()[1].InputComponent != component or handler not in tuple(component.BoundActionHandlerList):
            raise RuntimeError('Local OnFoot handler ownership changed')
        return handler

    def prepare_native(self):
        probe = self.traces[0]
        pc, pawn, camera, movement = self.bound()
        component = pawn.InputComponent
        if component is None:
            raise RuntimeError('Local pawn input component unavailable')
        handlers = component.BoundActionHandlerList
        if len(handlers) > 16:
            raise RuntimeError('Unexpected action handler count')
        matches = [h for h in handlers if h is not None and str(h.Class.Name) == 'OakEnhancedInputActionHandler_OnFoot']
        if len(matches) != 1:
            raise RuntimeError('Expected one SDK-bound OnFoot handler')
        handler = matches[0]
        self.handler_ref, self.component_ref = (WeakPointer(handler), WeakPointer(component))
        self.handler_address = int(handler._get_address())
        self.movement_address = int(movement._get_address())
        self.report['onfoot_handler'] = describe(handler)
        self.base = int(self.mod._kernel32.GetModuleHandleW(None) or 0)
        dos = probe.read(self.base, 64)
        if dos[:2] != b'MZ':
            raise RuntimeError('DOS signature mismatch')
        off = struct.unpack_from('<I', dos, 60)[0]
        if not 64 <= off <= 1048576:
            raise RuntimeError('PE header bounds')
        pe = probe.read(self.base + off, 264)
        build = (struct.unpack_from('<I', pe, 8)[0], struct.unpack_from('<I', pe, 80)[0], struct.unpack_from('<H', pe, 4)[0])
        if pe[:4] != b'PE\x00\x00' or struct.unpack_from('<H', pe, 24)[0] != 523 or build != REVIEWED_BUILD:
            raise RuntimeError('Unreviewed game build')
        self.report['build'] = [hex(v) for v in build]
        if struct.unpack('<Q', probe.read(self.movement_address, 8))[0] != self.base + 191927920:
            raise RuntimeError('Movement vtable differs')
        if struct.unpack('<Q', probe.read(self.handler_address, 8))[0] != self.base + 192168784:
            raise RuntimeError('Reviewed handler vtable differs')
        if struct.unpack('<Q', probe.read(self.base + 192168784 + 84 * 8, 8))[0] != self.base + 68236706:
            raise RuntimeError('OnFoot registration slot differs')
        if hashlib.sha256(probe.read(self.base + 68236706, 2614)).hexdigest() != 'edf2a04a2ab5085fd1dd6e1250fa7321abbb402b0177388540d3122372b5e418':
            raise RuntimeError('OnFoot registration function differs')
        for rva, prefix, size, digest, kind, label in TRACE_SPECS:
            if hashlib.sha256(probe.read(self.base + rva, size)).hexdigest() != digest:
                raise RuntimeError('Reviewed callback differs: ' + label)
        self.control[1] = self.handler_address
        self.control[2] = threading.get_native_id()
        self.control[4] = ctypes.addressof(self.buffer)
        self.control[7] = self.movement_address
        self.validate_handler()

    def consume_route(self):
        count = int(self.control[3])
        if not self.route_consumed <= count <= 512:
            raise RuntimeError('Sprint entry count outside bounds')
        for index in range(self.route_consumed, count):
            data = bytes(self.buffer[index * 128:(index + 1) * 128])
            values = struct.unpack('<16Q', data)
            commit, seq, kind, caller, update, sprint, dash, direction, handler_direction, has_direction = values[:10]
            if commit != 1 or seq != index or kind != 1 or (values[14] != self.handler_address):
                raise RuntimeError('Sprint entry record invalid')
            triple = struct.unpack_from('<3d', data, 80)
            press = triple == (1.0, 0.0, 0.0)
            route = 'FREE_REPEAT_SPRINT' if press and sprint & 4 else 'FREE_START_SPRINT' if press else 'NATIVE_RELEASE'
            row = {'sequence': self.report['input_route_total'] + seq, 'last_widget_update_index': update, 'route': route, 'input_value_xyz': list(triple), 'native_sprint_flags_raw': sprint, 'is_sprinting_at_entry': bool(sprint & 4), 'dash_wish_raw': dash, 'movement_dash_direction_raw': direction, 'handler_dash_direction_raw': handler_direction, 'handler_has_direction_raw': has_direction, 'native_mode_raw': values[13]}
            self.report['input_route_records'].append(row)
            if press and values[13] == 1 and (has_direction == 1):
                self.pending_entries.append(row)
        self.route_consumed = count

    def _manual_dash_request_dash(self, entry):
        if self.cycle_start is not None:
            return
        pawn, movement = (self.bound()[1], self.bound()[3])
        if bool(movement.bWantsToDash) or bool(pawn.IsCharacterDashing()):
            self.event('DASH_INPUT_ALREADY_BUSY', sequence=entry['sequence'])
            return
        requested = int(entry['handler_dash_direction_raw'])
        if entry['handler_has_direction_raw'] != 1 or requested not in (0, 1, 2, 3):
            raise RuntimeError('Captured handler direction invalid')
        saved = self.dash_branch.read(int(movement._get_address()) + 17480, 1)[0]
        if saved not in (0, 1, 2, 3):
            raise RuntimeError('Saved Dash direction outside enum')
        self.cycle_saved_direction = saved
        self.cycle_requested_direction = requested
        self.cycle_pending_clear = True
        self.cycle_start = self.frames
        self.cycle_started = False
        self.cycle_end = None
        self.branch_override_total += int(self.dash_branch.control[8])
        self.dash_branch.control[8] = 0
        self.cycle_override_base = 0
        for name in ('dash_peak_speed', 'dash_start_update', 'dash_end_update', 'dash_last_active_update'):
            self.report.pop(name, None)
        self.dash_branch.control[9] = requested
        self.dash_branch.control[7] = 1
        sample = self.report['samples'][-1]
        self.report['requested_dash'] = {'direction_raw': requested, 'direction_name': ('Up', 'Left', 'Down', 'Right')[requested], 'source': 'OnFoot handler direction captured at native Sprint callback press entry', 'sequence': entry['sequence'], 'actor_yaw': sample['actor_rotation']['Yaw'], 'control_yaw': sample['control_rotation']['Yaw'], 'velocity_yaw': sample['velocity_yaw']}
        pawn.SetWantsToDash(True, self.dash_enum(requested))
        self.invalidate_callback_values()
        self.report['game_writes'] += 1
        data = self.dash_branch.read(int(movement._get_address()) + 17480, 17)
        if data[0] != requested or not data[16] & 1:
            raise RuntimeError('Captured-direction request readback differs')
        self.event('DIRECTION_REQUESTED', sequence=entry['sequence'], saved_direction=saved, requested_direction=requested)

    def clear_request(self):
        if not self.cycle_pending_clear:
            return
        pawn, movement = (self.refs[1](), self.refs[3]())
        if pawn is None or movement is None:
            raise RuntimeError('Dash request owner expired; no write')
        pawn.SetWantsToDash(False, self.dash_enum(self.cycle_saved_direction))
        self.invalidate_callback_values()
        self.report['game_writes'] += 1
        data = self.dash_branch.read(int(movement._get_address()) + 17480, 17)
        if data[0] != self.cycle_saved_direction or data[16] & 1:
            raise RuntimeError('Dash request restore readback differs')
        self.cycle_pending_clear = False
        self.report['dash_request_restoration_verified'] = True

    def _manual_dash_close_cycle(self, outcome, sample):
        self.clear_request()
        self.dash_branch.control[7] = 0
        self.report['dash_cycles'].append({'outcome': outcome, 'request_update': self.cycle_start, 'start_update': self.report.get('dash_start_update'), 'end_update': self.report.get('dash_end_update'), 'requested_dash': dict(self.report.get('requested_dash', {})), 'peak_speed': self.report.get('dash_peak_speed', 0), 'is_sprinting': sample['sprint_state']['bIsSprinting'], 'speed': sample['horizontal_speed']})
        if outcome == 'NATIVE_DASH_ENDED':
            self.report['completed_dash_cycles'] += 1
        self.event(outcome)
        self.cycle_start = None
        self.cycle_started = False
        self.cycle_end = None

    def trial_cycle(self, sample, free, moving):
        pawn, movement = (self.bound()[1], self.bound()[3])
        active = self.is_dashing(pawn)
        if self.cycle_start is not None:
            if active:
                if not self.cycle_started:
                    self.cycle_started = True
                    self.report['dash_start_update'] = self.frames
                    self.event('NATIVE_DASH_STARTED')
                self.report['dash_peak_speed'] = max(self.report.get('dash_peak_speed', 0), sample['horizontal_speed'])
                self.report['dash_last_active_update'] = self.frames
                if not free:
                    self.dash_branch.control[7] = 0
            elif self.cycle_started:
                self.report['native_end_observed_before_request_clear'] = True
                self.report['dash_end_update'] = self.frames
                self.close_cycle('NATIVE_DASH_ENDED', sample)
            elif not free or not moving:
                self.close_cycle('DASH_REQUEST_CONTEXT_CHANGED', sample)
            elif self.frames - self.cycle_start >= 16:
                self.close_cycle('DASH_REQUEST_NOT_STARTED', sample)
            if self.cycle_start is not None:
                if int(self.dash_branch.control[8]) - self.cycle_override_base >= 256:
                    self.finish('DASH_OVERRIDE_CAP')
                    return
                if self.frames - self.cycle_start >= 64:
                    self.finish('DASH_WINDOW_CAP')
                    return
        for entry in self.pending_entries:
            if entry['route'] == 'FREE_START_SPRINT':
                self.event('MANUAL_START_INPUT', sequence=entry['sequence'])
            elif entry['route'] == 'FREE_REPEAT_SPRINT':
                if self.cycle_start is not None or active:
                    self.event('DASH_INPUT_ALREADY_BUSY', sequence=entry['sequence'])
                elif free and moving and bool(movement.bIsSprinting):
                    self.request_dash(entry)
                else:
                    self.event('REPEAT_INPUT_CONTEXT_CHANGED', sequence=entry['sequence'])
        self.pending_entries.clear()

    def recycle_diagnostics(self):
        if not self.updates.is_game_thread():
            raise RuntimeError('Diagnostic recycle outside owned thread')
        if self.control[6] or self.dash_branch.control[6]:
            raise RuntimeError('Diagnostic buffer overflow')
        if self.route_consumed != int(self.control[3]) or self.dash_branch.consumed != int(self.dash_branch.control[3]):
            raise RuntimeError('Diagnostic recycle before complete consumption')
        self.report['input_route_total'] += self.route_consumed
        self.report['dash_native_record_total'] += self.dash_branch.consumed
        self.control[3] = 0
        self.route_consumed = 0
        self.dash_branch.control[3] = 0
        self.dash_branch.consumed = 0

    def _manual_dash_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Manual trial outside owned game thread')
            self.bound()
            if not self.sprint_ready:
                if self.mesh_ref is None:
                    self._bind_visual()
                self._bind_sprint()
            if not self.route_ready:
                self._bind_route()
            self.validate_handler()
            for slot, owner in ((4, self.route), (5, self.dash_branch),
                                (6, self.direction_trace), (7, self.index_trace)):
                if self.native_audit_due(slot):
                    owner.validate()
            self.consume_route()
            self.dash_branch.consume()
            self.recycle_diagnostics()
            self.dash_branch.control[5] = self.frames + 1
            self._lean_live_frame(obj, args, ret, func)
            if not self.active:
                return
            sample = self.report['samples'][-1]
            movement = self.bound()[3]
            moving = sample['movement_input_active'] and sample['horizontal_speed'] > 100 and (sample.get('acceleration_yaw') is not None)
            free = not sample['combat']['active'] and sample['normal_tps_sample'] and (self.impulse_index is not None)
            aligned = abs(sample.get('velocity_minus_actor', 999)) <= 5 and sample.get('acceleration_yaw') is not None and (abs(angle(sample['acceleration_yaw'], sample['actor_rotation']['Yaw'])) <= 5)
            keep = free and moving and (aligned or bool(movement.bIsSprinting))
            self.direction_trace.control[7] = int(keep)
            self.index_trace.control[7] = int(keep)
            self.control[8] = int(free and moving)
            self.control[5] = self.frames
            phase = 'COMBAT_NATIVE' if sample['combat']['active'] else 'IDLE_HOLD' if not moving else 'MANUAL_SPRINT' if bool(movement.bIsSprinting) else 'WALK_READY' if aligned else 'ALIGNING'
            if phase != self.live_sprint_phase:
                self.live_sprint_phase = phase
                self.event(phase)
            sample['manual_sprint_phase'] = phase
            dash_pawn = self.bound()[1]
            sample['sprint_state'] = {n: bool(getattr(movement, n)) for n in ('bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting')}
            sample['dash_state'] = {'wants_dash': bool(movement.bWantsToDash), 'is_dashing': self.is_dashing(dash_pawn), 'last_dash_time': float(movement.LastDashTime)}
            self.direction_trace.consume()
            self.index_trace.consume()
            if self.frames % 12 == 0:
                self.snapshot_sprint(sample, movement)
            self.report['native_patches'] = sum((o.hook is not None for o in self.owners()))
            self.report['native_patches_peak'] = max(self.report.get('native_patches_peak', 0), self.report['native_patches'])
            self.trial_cycle(sample, free, moving)
            if not self.active:
                return
            self.trim_diagnostics()
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('MANUAL_TRIAL_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def request_dash(self, entry):
        if self.cycle_start is not None:
            return
        sample = self.report['samples'][-1]
        requested = int(entry['handler_dash_direction_raw'])
        axes = sample['action_intent']
        pair = (sample['movement_input_source'],)
        if requested not in (0, 1, 2, 3) or sample['movement_input_strength'] < 0.8:
            self.event('REQUIRES_FULL_MOVEMENT_INPUT')
            return
        if sample['combat']['active'] or not sample['normal_tps_sample'] or sample['horizontal_speed'] <= 100:
            self.event('REQUIRES_FREE_GROUNDED_SPRINT')
            return
        velocity = sample['velocity']
        x, y = (velocity['X'], velocity['Y'])
        length = math.hypot(x, y)
        if not math.isfinite(length) or length <= 100:
            raise RuntimeError('Captured movement vector invalid')
        target = (x / length, y / length, 0.0)
        if abs(angle(sample['velocity_yaw'], sample['actor_rotation']['Yaw'])) > 5:
            self.event('WAIT_FOR_ALIGNMENT')
            return
        movement = int(self.bound()[3]._get_address())
        trace = self.vector_trace
        configuration = struct.unpack('<Q', trace.read(movement + 17456, 8))[0]
        if not 65536 <= configuration < 140737488355328:
            raise RuntimeError('Dash direction configuration unavailable')
        raw_angles = trace.read(configuration + 144, 16)
        angles = struct.unpack('<4f', raw_angles)
        if not all((math.isfinite(v) and abs(v) <= 360 for v in angles)):
            raise RuntimeError('Dash angle values outside reviewed range')
        factor = struct.unpack('<d', trace.read(trace.base + 163877400, 8))[0]
        if not math.isfinite(factor) or not 0 < factor < 0.1:
            raise RuntimeError('Native angle conversion factor outside range')
        native_angle = angles[requested]
        theta = native_angle * factor
        cos_theta, sin_theta = (math.cos(theta), math.sin(theta))
        compensated = (cos_theta * target[0] + sin_theta * target[1], -sin_theta * target[0] + cos_theta * target[1], 0.0)
        if not all((math.isfinite(v) for v in compensated)) or abs(math.hypot(*compensated[:2]) - 1) > 1e-09:
            raise RuntimeError('Compensated unit vector invalid')
        trace.control[12] = 1
        trace.control[8] = 0
        trace.control[13] = requested
        trace.control[14] = configuration
        trace.control[15] = struct.unpack_from('<I', raw_angles, requested * 4)[0]
        for index, value in enumerate(compensated, 9):
            trace.control[index] = struct.unpack('<Q', struct.pack('<d', value))[0]
        self.custom_dash_compensation = {'native_direction': requested, 'native_angles_raw': list(angles), 'selected_native_angle_raw': native_angle, 'native_angle_factor': factor, 'precompensated_vector': list(compensated)}
        self.custom_dash_vector = target
        self._manual_dash_request_dash(entry)
        if self.cycle_start is not None:
            self.custom_dash_input_signature = pair
            self.custom_dash_requests += 1
            self.report['ab_vector_targets'].append({'phase': 'MOVEMENT_VECTOR', 'request_update': self.frames, 'movement_vector': list(target), 'movement_yaw': sample['velocity_yaw']})
            self.report['ab_vector_targets'][-1].update(self.custom_dash_compensation)
            self.report['ab_vector_targets'][-1]['action_intent'] = dict(axes)
            self.event('CAPTURED_MOVEMENT_VECTOR')
        else:
            self.vector_trace.control[12] = 0

    def close_cycle(self, outcome, sample):
        phase = 'MOVEMENT_VECTOR'
        self._manual_dash_close_cycle(outcome, sample)
        self.report['dash_cycles'][-1]['ab_phase'] = phase
        self.report['dash_cycles'][-1]['native_rotation'] = dict(self.custom_dash_compensation or {})
        self.report['dash_cycles'][-1]['captured_movement_vector'] = list(self.custom_dash_vector or ())
        self.report['dash_cycles'][-1]['input_vector_override_count'] = int(self.vector_trace.control[8])
        self.report['dash_cycles'][-1]['branch_override_count'] = int(self.dash_branch.control[8])
        self.vector_trace.control[12] = 0
        self.report['last_cycle_outcome'] = outcome

    def _dash_vector_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.vector_ready:
                self._bind_vector()
            if self.native_audit_due(8):
                self.vector_trace.validate()
            self.vector_trace.control[5] = self.frames + 1
            self._manual_dash_frame(obj, args, ret, func)
            if not self.active:
                return
            self.vector_trace.consume()
            self.vector_trace.control[7] = int(self.cycle_start is not None)
            if self.vector_trace.control[6]:
                self.finish('VECTOR_BUFFER_LIMIT')
                return
            count = int(self.vector_trace.control[3])
            if self.vector_trace.consumed != count:
                raise RuntimeError('Vector recycle before full consumption')
            self.report['vector_entry_record_total'] += count
            self.vector_trace.control[3] = 0
            self.vector_trace.consumed = 0
            completed = self.report['completed_dash_cycles']
            if completed > self.post_observed_cycle and self.cycle_start is None and (self.frames - self.report.get('dash_end_update', self.frames) >= 30):
                sample = self.report['samples'][-1]
                self.report['sprint_return_observations'].append({'cycle_number': completed, 'update_index': self.frames, 'is_sprinting': bool(self.bound()[3].bIsSprinting), 'horizontal_speed': sample['horizontal_speed'], 'movement_mode': sample['movement_mode']})
                self.post_observed_cycle = completed
            self.trim_diagnostics()
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('VECTOR_TRACE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def _handoff_classify_handoff(self, pc, pawn, camera, movement):
        mode = self.camera_mode(pawn, camera)
        if not self.mod._third_person_enabled or bool(pc.bShowMouseCursor):
            return ('STOP', 'TPS_OR_UI_CHANGED')
        if any((bool(getattr(self.mod, k, False)) for k in ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active'))):
            return ('STOP', 'UNSUPPORTED_CONTEXT')
        m = int(movement.MovementMode)
        slide = bool(getattr(self.mod, '_slide_active', False))
        exiting = self.slide_exit_pending(camera, mode, slide)
        if m not in (1, 3):
            return ('STOP', 'UNSUPPORTED_MOVEMENT_MODE')
        if mode != 'ThirdPerson' and (not ((slide or exiting) and mode in ('Slide', 'Default'))):
            return ('STOP', 'UNSUPPORTED_CAMERA_MODE')
        if bool(self.jump_down(pc)):
            return ('PAUSE', 'JUMP_INPUT')
        if m == 3:
            return ('PAUSE', 'AIRBORNE')
        if slide:
            return ('PAUSE', 'SLIDE')
        if exiting:
            # BL4 hands the camera back from its slide mode after the slide
            # flag fell. Keep the slide body owner until that has settled,
            # even while Crouch is still held.
            return ('PAUSE', 'SLIDE_EXIT')
        if bool(pawn.bIsCrouched) and not self.is_dashing(pawn):
            return ('PAUSE', 'CROUCHED')
        if bool(self.air_dash_down(pc)):
            return ('PAUSE', 'CIRCLE_INPUT')
        if bool(pawn.bIsCrouched):
            return ('PAUSE', 'CROUCHED')
        if self.cycle_start is None and self.is_dashing(pawn):
            return ('PAUSE', 'NATIVE_DASH')
        return ('RUN', None)

    def _handoff_paused_frame(self, obj, args, ret, func, reason):
        self.disable_handoff_overrides()
        self.audit_owners()
        self.read_combat()
        self._sample_frame(obj, args, ret, func)
        if not self.active:
            return
        sample = self.report['samples'][-1]
        movement = self.bound()[3]
        sample['is_crouched'] = bool(self.bound()[1].bIsCrouched)
        sample['handoff_state'] = reason
        sample['sprint_state'] = {n: bool(getattr(movement, n)) for n in ('bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting')}
        sample['dash_state'] = {'wants_dash': bool(movement.bWantsToDash), 'is_dashing': bool(self.bound()[1].IsCharacterDashing())}
        if self.cycle_start is not None:
            self.close_cycle('DASH_NATIVE_HANDOFF', sample)
        if self.route_ready:
            self.consume_route()
            self.dash_branch.consume()
            self.pending_entries.clear()
            self.recycle_diagnostics()
        if self.vector_ready:
            self.vector_trace.consume()
            count = int(self.vector_trace.control[3])
            if self.vector_trace.consumed != count:
                raise RuntimeError('Paused vector recycle before consumption')
            self.report['vector_entry_record_total'] += count
            self.vector_trace.control[3] = 0
            self.vector_trace.consumed = 0
        for trace in (self.direction_trace, self.index_trace):
            if trace.hook is not None:
                trace.consume()
        self.transition_event('NATIVE_' + reason)
        self.trim_diagnostics()

    def _handoff_resume_handoff(self):
        self._audit_full = True
        if self.route_ready:
            self.consume_route()
            self.dash_branch.consume()
            self.pending_entries.clear()
            self.recycle_diagnostics()
            self.control[0] = 1
            self.dash_branch.control[0] = 1
        if self.ready:
            self.native.control[0] = 1
            self.native.control[7] = int(self.impulse_index is not None)
        if self.vector_ready:
            self.vector_trace.control[0] = 1
        self.follow_previous_t = monotonic() - self.started
        self.transition_event('GROUNDED_RESUMED')

    def _handoff_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Transition outside owned game thread')
            pc, pawn, camera, movement = self.bound()
            action, reason = self.classify_handoff(pc, pawn, camera, movement)
            if action == 'STOP':
                self.finish(reason)
                return
            if action == 'PAUSE':
                self.paused_frame(obj, args, ret, func, reason)
                return
            if self.handoff_reason is not None and self.handoff_reason.startswith('NATIVE_'):
                self.resume_handoff()
            self._dash_vector_frame(obj, args, ret, func)
            if self.active and self.report['samples']:
                self.report['samples'][-1]['handoff_state'] = 'GROUNDED_CONTROL'
                self.report['samples'][-1]['is_crouched'] = bool(pawn.bIsCrouched)
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('TRANSITION_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def classify_handoff(self, pc, pawn, camera, movement):
        action, reason = self._handoff_classify_handoff(pc, pawn, camera, movement)
        if action == 'PAUSE' and reason in ('CIRCLE_INPUT', 'NATIVE_DASH') and (int(movement.MovementMode) == 1):
            combat = bool(getattr(self.mod, '_ads_active', False)) or bool(self.combat.get('active', False)) or self.inputs.snapshot(pc)['zoom'] or self.inputs.snapshot(pc)['fire']
            if self.impulse_index is not None and (not combat) and (not bool(pawn.bIsCrouched)) and (not bool(getattr(self.mod, '_slide_active', False))):
                return ('RUN', None)
        return (action, reason)

    def _ground_action_frame(self, obj, args, ret, func):
        self._air_clips_frame(obj, args, ret, func)
        if not self.active or not self.report['samples']:
            return
        try:
            pc, pawn, camera, movement = self.bound()
            grounded = int(movement.MovementMode) == 1
            circle = bool(self.air_dash_down(pc))
            dash = self.is_dashing(pawn)
            slide = bool(getattr(self.mod, '_slide_active', False))
            state = (grounded, circle, dash, slide, bool(pawn.bIsCrouched), bool(movement.bIsSprinting), self.cycle_start is not None)
            if grounded and dash and (not self.ground_circle_previous_dash):
                self.report['ground_circle_observed_dash_starts'] += 1
            elif self.ground_circle_previous_dash and (not (grounded and dash)):
                self.report['ground_circle_observed_dash_ends'] += 1
            self.ground_circle_previous_dash = bool(grounded and dash)
            if state != self.ground_circle_last_state or (grounded and (circle or dash or slide) and (self.frames % 6 == 0)):
                sample = self.report['samples'][-1]
                self.report['ground_circle_samples'].append(dict(update_index=self.frames, t=sample['t'], grounded=grounded, circle_down=circle, native_is_dashing=dash, native_wants_dash=bool(movement.bWantsToDash), slide=slide, crouched=bool(pawn.bIsCrouched), actual_sprint=bool(movement.bIsSprinting), l3_request_cycle=self.cycle_start is not None, body_rotation=sample['actor_rotation'], control_rotation=sample['control_rotation'], velocity_yaw=sample.get('velocity_yaw'), speed=sample['horizontal_speed'], camera_mode=self.camera_mode(pawn, camera), handoff_state=self.handoff_reason))
                self.report['ground_circle_sample_total'] += 1
                del self.report['ground_circle_samples'][:-512]
                self.ground_circle_last_state = state
        except Exception as exc:
            self.report['errors'].append('Ground Circle observation: ' + repr(exc)[:500])
            try:
                self.finish('GROUND_CIRCLE_OBSERVATION_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def _native_entry_consume_entry(self):
        for action, rva, owner, trace in self.entries:
            count = int(owner.control[3])
            if not owner.consumed <= count <= CircleEntry_CAPACITY:
                raise RuntimeError('Circle entry count invalid')
            for i in range(owner.consumed, count):
                v = struct.unpack('<16Q', bytes(owner.buffer[i * 128:(i + 1) * 128]))
                if v[0] != 1 or v[1] != i or v[2] != 2 or (v[14] != self.handler_address):
                    raise RuntimeError('Circle entry record invalid')
                self.report['native_circle_entries'].append(dict(action=action, entry_rva=hex(rva), sequence=i, caller_return_rva=hex(v[3] - owner.base), last_widget_update=v[4], sprint_flags_raw=v[5], dash_wish_byte_raw=v[6], movement_direction_raw=v[7], handler_direction_raw=v[8], handler_has_direction_raw=v[9], native_mode_raw=v[13]))
            owner.consumed = count
            if owner.control[6]:
                raise RuntimeError('Circle entry buffer limit')

    def _native_entry_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if self.entry_ready:
                if self.native_audit_due(9):
                    for action, rva, o, t in self.entries:
                        t.validate()
                self.consume_entry()
            self._ground_action_frame(obj, args, ret, func)
            if not self.active:
                return
            if self.route_ready and (not self.entry_ready):
                self._bind_entries()
            if self.entry_ready:
                for action, rva, o, t in self.entries:
                    o.control[5] = self.frames
                    o.control[0] = 1
        except Exception as exc:
            self.report['errors'].append('Native Circle counters: ' + repr(exc)[:500])
            try:
                self.finish('NATIVE_ENTRY_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def consume_entry(self):
        self._native_entry_consume_entry()
        for action, rva, o, t in self.entries:
            count = int(o.control[3])
            if o.consumed != count:
                raise RuntimeError('Circle recycle before full consumption')
            self.report['native_circle_entry_record_total'] += count
            o.control[3] = 0
            o.consumed = 0
        del self.report['native_circle_entries'][:-512]

    def _ground_vector_prepare_ground(self, sample):
        owner = self.entries[0][2]
        trace = self.vector_trace
        owner.control[16] = 0
        # Standing still never prepares a vector; skip the handler read then.
        # _manual_dash_frame validated the handler earlier in this update.
        v = sample['velocity']
        length = math.hypot(v['X'], v['Y'])
        if not math.isfinite(length) or length <= 100:
            return
        self.validate_handler()
        direction, has = struct.unpack('<2B', trace.read(self.handler_address + 72, 2))
        if direction not in (0, 1, 2, 3) or has != 1:
            return
        target = [v['X'] / length, v['Y'] / length, 0.0]
        cfg = struct.unpack('<Q', trace.read(self.movement_address + 17456, 8))[0]
        if not 65536 <= cfg < 140737488355328:
            raise RuntimeError('Ground Dash config invalid')
        raw = trace.read(cfg + 144, 16)
        angles = struct.unpack('<4f', raw)
        factor = struct.unpack('<d', trace.read(trace.base + 163877400, 8))[0]
        if not all((math.isfinite(a) and abs(a) <= 360 for a in angles)) or not math.isfinite(factor) or (not 0 < factor < 0.1):
            raise RuntimeError('Ground Dash angle metadata invalid')
        theta = angles[direction] * factor
        pre = [math.cos(theta) * target[0] + math.sin(theta) * target[1], -math.sin(theta) * target[0] + math.cos(theta) * target[1], 0.0]
        trace.control[12] = 0
        trace.control[7] = 0
        trace.control[8] = 0
        trace.control[13] = direction
        trace.control[14] = cfg
        trace.control[15] = struct.unpack_from('<I', raw, direction * 4)[0]
        for n, value in enumerate(pre, 9):
            trace.control[n] = struct.unpack('<Q', struct.pack('<d', value))[0]
        compensation = []
        for enum, native_angle in enumerate(angles):
            radians = native_angle * factor
            vector = [math.cos(radians) * target[0] + math.sin(radians) * target[1], -math.sin(radians) * target[0] + math.cos(radians) * target[1], 0.0]
            offset = 16 + enum * 4
            trace.control[offset] = struct.unpack_from('<I', raw, enum * 4)[0]
            for slot, value in enumerate(vector, offset + 1):
                trace.control[slot] = struct.unpack('<Q', struct.pack('<d', value))[0]
            compensation.append(vector)
        self.ground_prepared = dict(phase=self.ground_stage, target_vector=target, target_yaw=sample['velocity_yaw'], body_yaw_before=sample['actor_rotation']['Yaw'], control_yaw=sample['control_rotation']['Yaw'], previous_update=sample['update_index'], native_enum=direction, config=hex(cfg), native_angles=list(angles), actual_direction_compensation_table=compensation, precompensated_vector=pre, seen_dash=False, override_count=0, rows=[])
        owner.control[17] = ctypes.addressof(trace.control)
        owner.control[16] = 2

    def accept_native_arm(self):
        o = self.entries[0][2]
        count = int(o.control[18])
        if count == self.ground_entry_consumed:
            return
        if count != self.ground_entry_consumed + 1 or self.ground_trial is not None or self.ground_prepared is None:
            raise RuntimeError('Unexpected native Circle arm sequence')
        t = dict(self.ground_prepared)
        t['rows'] = []
        expected = 2
        if int(o.control[21]) != expected or int(o.control[22]) != t['native_enum']:
            raise RuntimeError('Native Circle phase/enum latch differs')
        t['native_entry_previous_widget'] = int(o.control[20])
        t['press_update'] = self.frames + 1
        t['override_count'] = max(t['override_count'], int(self.vector_trace.control[8]))
        t['native_B_arm_total'] = int(o.control[19])
        t['native_armed_before_original_callback'] = True
        self.ground_trial = t
        self.ground_entry_consumed = count
        self.ground_wait_release = True
        self.vector_trace.control[7] = 0
        self.vector_trace.control[12] = 0
        self.event('GROUND_' + t['phase'] + '_NATIVE_ENTRY_CAPTURED')

    def publish_trial(self):
        t = self.ground_trial
        if t is None:
            return
        self.entries[0][2].control[16] = 0
        if self.cycle_start is not None or self.air_cycle is not None:
            return
        pawn = self.bound()[1]
        movement = self.bound()[3]
        permitted = self.frames - t['press_update'] < 16 and int(movement.MovementMode) == 1 and (not self.combat['active']) and (not self.mod._slide_active) and (not pawn.bIsCrouched) and (int(self.vector_trace.control[8]) == 0)
        self.vector_trace.control[0] = 1
        self.vector_trace.control[7] = int(permitted)
        self.vector_trace.control[12] = 3 if permitted else 0

    def close_ground_trial(self, outcome):
        t = self.ground_trial
        if t is None:
            return
        self.entries[0][2].control[16] = 0
        if self.cycle_start is None and self.air_cycle is None:
            self.vector_trace.control[7] = 0
            self.vector_trace.control[12] = 0
        t['outcome'] = outcome
        self.report['ground_native_trial_total'] += 1
        self.report['ground_native_vector_trials'].append(t)
        del self.report['ground_native_vector_trials'][:-128]
        self.ground_trial = None
        self.ground_prepared = None

    def _ground_vector_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            self.accept_native_arm()
            self.publish_trial()
            self._native_entry_frame(obj, args, ret, func)
            if not self.active:
                return
            self.record_trial()
            pc, pawn, camera, movement = self.bound()
            circle = bool(self.air_dash_down(pc))
            if not circle:
                self.ground_wait_release = False
            if self.ground_trial is not None:
                self.publish_trial()
            elif self.entry_ready and self.vector_ready and (not self.ground_wait_release) and self.report['samples'] and (self.impulse_index is not None) and (self.cycle_start is None) and (self.air_cycle is None) and (int(movement.MovementMode) == 1) and (not self.combat['active']) and (not self.mod._slide_active) and (not pawn.bIsCrouched) and (not self.is_dashing(pawn)):
                self.prepare_ground(self.report['samples'][-1])
            else:
                self.entries[0][2].control[16] = 0
                self.ground_prepared = None
        except Exception as exc:
            self.report['errors'].append('Native ground Circle live: ' + repr(exc)[:500])
            try:
                self.finish('GROUND_NATIVE_LIVE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))
