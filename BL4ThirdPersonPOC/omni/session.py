"""Session state, explicit update pipeline and full independent restoration."""
from datetime import datetime, timezone
from time import monotonic
import ctypes
import math
import threading
from contextlib import nullcontext
from unrealsdk import hooks, find_enum, find_object
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import KEY, TAG, MAX_SAMPLES, FRAME_STRIDE, angle, parts, describe, report_path, write_report
from .rebind_cache import bone_names
from .vehicle_handoff import allow_exit_air
from .inputs import NativeBindings
from . import settings
from .. import hybrid_ads
from .native_rotation import NativeIdleRoot, NativeIdleUpdate, NativeTrace
from .native_free_look import NativeFreeLookAim
from .free_look import publish as publish_free_look
from .native_idle_scope import ScopedIdleRoot, ScopedIdleUpdate
from .native_air_input import LiveAirInputTrace
from .native_movement import CircleEntry_EntryTrace, DASH_INLINE_SPEC, DashBranchTrace, ENTRY_SPECS, EntryTrace, LiveDirectionTrace, LiveIndexTrace, NativeEntryOwner, ROUTE_CAPACITY, ROUTE_RECORD_SIZE, SPRINT_DIRECTION_SPEC, TRACE_SPECS, VectorEntryTrace
from .sampling import SamplingMixin
from .animation import AnimationMixin
from .grenade_facing import GrenadeFacing
from .ground import GroundMixin
from .air import AirMixin
from .slide import SlideMixin
from .slam import SlamMixin
from .diagnostics import DiagnosticsMixin
from .profiler import root_span
from . import hitch

class GameplaySession(SamplingMixin, AnimationMixin, GroundMixin, AirMixin, SlideMixin, SlamMixin, DiagnosticsMixin):
    INPUT_NAMES = ('ForwardDirection', 'RightDirection', 'UpDirection', 'Direction', 'ReverseDirection', 'AccelDirection', 'Speed2D', 'Speed2DRaw', 'AimYaw', 'AimPitch', 'AimEnableAlpha', 'HeadEnableAlpha', 'bIsMoving2D', 'bIsMovingOrRotating2D', 'bIsThirdPersonMesh')
    NODE_NAME = 'GbxAnimGraphNode_Rotation_AimOffset_4'
    IDLE_NODE_NAME = 'GbxAnimGraphNode_IdleTurns_2'
    PLAYERS = (('GbxAnimGraphNode_BlendSpacePlayer_9', 'AnimSet.Player.3rd.BS_Move'), ('GbxAnimGraphNode_BlendSpacePlayer_7', 'AnimSet.Player.3rd.BS_Lean'), ('GbxAnimGraphNode_BlendSpacePlayer_8', 'AnimSet.Player.3rd.BS_ADD_Char_BodyPose'))
    FIELDS = ('X', 'Y', 'PlayRate', 'BlendWeight', 'InternalTimeAccumulator', 'Duration')
    PLAYER_STRIDE = 6
    PLAYER_LIMIT = 512
    BLEND_NODE = 'AnimGraphNode_ApplyMeshSpaceAdditive'
    BLEND_OFFSET = 89240
    LEAN_OFFSET = 116464
    LIVE_LIMIT = 512
    DASH_PLAYERS = (('GbxAnimGraphNode_SequencePlayer_35', 'AnimSet.Player.3rd.Dash_F'), ('GbxAnimGraphNode_SequencePlayer_36', 'AnimSet.Player.3rd.Dash_B'), ('GbxAnimGraphNode_SequencePlayer_37', 'AnimSet.Player.3rd.Dash_L'), ('GbxAnimGraphNode_SequencePlayer_38', 'AnimSet.Player.3rd.Dash_R'))
    DASH_INPUTS = ('DashDirection', 'bIsDashing', 'Dashing_Up', 'Dashing_Down', 'Dashing_Left', 'Dashing_Right')
    SLIDE_PATH = '/Game/PlayerCharacters/_Shared/Tricks/ControlledMoves/Move_Slide.Move_Slide'
    BONE_NAMES = ('Root', 'Spine5', 'Neck', 'Neck1', 'Head')
    AIM_NODES = ('GbxAnimGraphNode_Rotation_AimOffset_4', 'GbxAnimGraphNode_Rotation_AimOffset_3', 'GbxAnimGraphNode_Rotation_AimOffset_2', 'GbxAnimGraphNode_Rotation_AimOffset')

    def __init__(self, mod, updates):
        self.mod, self.updates = (mod, updates)
        self.started = monotonic()
        self.frames = 0
        self.busy = False
        self.active = False
        self.registered = False
        self.previous_actions = None
        self.spec = (mod.FIRST_PERSON_ANIM_HOOK, hooks.Type.POST_UNCONDITIONAL, 'bl4tps.player_camera_relative_gameplay_live.frame')
        # Only a standalone (not lifecycle-managed) session saves its own report.
        self.path = report_path(mod, 'player_omnidirectional_session')
        self.report = {'probe': 'player_camera_relative_gameplay_live', 'utc': datetime.now(timezone.utc).isoformat(), 'sdk_hooks_peak': 1, 'sdk_hooks': 0, 'native_patches': 0, 'game_writes': 0, 'native_reads': 0, 'native_data_writes': 0, 'source': 'existing BL4TPS runtime_updates owned widget Tick, game thread', 'frame_stride': FRAME_STRIDE, 'sample_limit': None, 'retained_sample_limit': MAX_SAMPLES, 'note': 'One observation phase per sampled update. No before/after native ordering proof. Actor rotation describes the actor, not animated bone orientation. Movement uses the native pawn input vector; action intent follows current mappings.', 'samples': [], 'errors': []}
        self.native = NativeTrace(self)
        self.grenade_facing = GrenadeFacing(self)
        # NativeTrace publishes slide_control/slide_buffer inside its stub, but
        # its hook metadata pins only control/buffer. Keep both reachable from
        # the pinned control, as NativeSlideCrouchAimYaw does for crouch_control.
        self.native.control._slide_record_control = self.native.slide_control
        self.native.control._slide_record_buffer = self.native.slide_buffer
        self.ready = False
        self.report['native_records'] = []
        self.original_rotation = None
        self.restore_pending = False
        self.impulse_index = None
        self.report['follow_settings'] = {'seconds': None, 'yaw_rate_degrees_per_second': 540.0, 'max_step_seconds': 0.05, 'start_speed': 100.0, 'idle_speed': 30.0, 'combat_yaw_rate_degrees_per_second': 1080.0}
        self.mesh_ref = None
        self.bones = []
        self.report['visual_samples'] = []
        self.aim_native = NativeFreeLookAim(self)
        self.free_look_context = False
        self.ground_slam_pose_native = False
        self.idle_native = ScopedIdleRoot(self)
        self.idle_update = ScopedIdleUpdate(self)
        self.phase = None
        self.report['aim_phases'] = []
        self.combat = {}
        self.report['combat_transitions'] = []
        self.player_ready = False
        self.report['player_samples'] = []
        self.report['player_read_errors'] = {}
        self.report['player_assets'] = {}
        self.report['visual_binding_cost_us'] = 0.0
        self.blend_pending = False
        self.blend_original = None
        self.blend_layout_ready = False
        self.report['lean_blend_phases'] = []
        self.report['lean_blend_observations'] = []
        self.live_phase = None
        self.report['lean_live_transitions'] = []
        self.direction_trace = LiveDirectionTrace(self, SPRINT_DIRECTION_SPEC)
        self.index_trace = LiveIndexTrace(self)
        self.sprint_ready = False
        self.sprint_pending = False
        self.sprint_restart_armed = False
        self.sprint_alignment_updates = 0
        self.sprint_was_aligned = True
        self.sprint_cleanup_error = None
        self.selection_addresses = {}
        self.live_sprint_phase = None
        self.report.update(live_sprint_events=[], live_sprint_animation_samples=[], live_sprint_requests=0)
        self.control = (ctypes.c_uint64 * 9)()
        self.buffer = (ctypes.c_ubyte * (ROUTE_CAPACITY * ROUTE_RECORD_SIZE))()
        self.route = EntryTrace(self, TRACE_SPECS[0])
        self.traces = [self.route]
        self.dash_branch = DashBranchTrace(self, DASH_INLINE_SPEC)
        self.route_ready = False
        self.route_consumed = 0
        self.pending_entries = []
        self.cycle_pending_clear = False
        self.cycle_start = None
        self.cycle_started = False
        self.cycle_end = None
        self.manual_cleanup_error = None
        self.cycle_override_base = 0
        self.branch_override_total = 0
        self.report.update(input_route_records=[], manual_events=[], dash_native_records=[], native_callback_routing='Native Sprint callback routing; exact-owner native Crouch entry publisher retained', route_capacity=ROUTE_CAPACITY, live_sprint_requests=0, automatic_sprint_requests=0, native_end_observed_before_request_clear=False, sample_limit=None, trial_update_limit=None, dash_cycles=[], completed_dash_cycles=0, diagnostic_tail_limit=512, input_route_total=0, dash_native_record_total=0)
        self.vector_trace = LiveAirInputTrace(self, (18917386, '56574883ec7866440f2954246066440f294c2450', 420, '8fb4fd8f7ca792efd5ab49896d5ac80b04be0a3d47667d16d47b34cfda048710', 63875349, 'movement_slot_E60_vector_entry'))
        self.custom_dash_requests = 0
        self.custom_dash_vector = None
        self.custom_dash_input_signature = None
        self.custom_dash_compensation = None
        self.vector_ready = False
        self.vector_cleanup_error = None
        self.report['gate_pair_counts'] = {'MOVEMENT_DIRECTION': {}}
        self.report['vector_entry_records'] = []
        self.report['vector_entry_record_total'] = 0
        self.report['native_input_vector_overrides_total'] = 0
        self.report['sprint_return_observations'] = []
        self.post_observed_cycle = 0
        self.report['ab_vector_targets'] = []
        self.handoff_reason = None
        self.report['handoff_transitions'] = []
        self.air_previous_t = None
        self.air_hold_yaw = None
        self.air_circle_previous = False
        self.air_cycle = None
        self.air_cycle_sequence = 0
        self.air_circle_press_count = 0
        self.report['air_live_events'] = []
        self.report['air_live_cycles'] = []
        self.report['air_live_targets'] = []
        self.report['air_live_completed_cycles'] = 0
        self.report['air_live_vector_overrides'] = 0
        self.report['air_dash_attempts'] = []
        self.report['air_vector_entry_records'] = []
        self.report['air_vector_entry_total'] = 0
        self.report['air_facing_samples'] = []
        self.report['air_facing_updates'] = 0
        self.report['air_dash_animation_samples'] = []
        self.report['air_dash_animation_sample_total'] = 0
        self.animation_observer_last_state = None
        self.animation_observer_start = None
        self.clip_originals = []
        self.clip_forward_ref = None
        self.clip_anim_ref = None
        self.report['air_clip_events'] = []
        self.report['air_clip_cycles_applied'] = 0
        self.report['air_clip_cycles_restored'] = 0
        self.report['air_clip_restore_verified'] = True
        self.report['ground_circle_samples'] = []
        self.report['ground_circle_sample_total'] = 0
        self.report['ground_circle_observed_dash_starts'] = 0
        self.report['ground_circle_observed_dash_ends'] = 0
        self.ground_circle_last_state = None
        self.ground_circle_previous_dash = False
        self.report['getter_calls'] = 0
        self.report['getter_results'] = []
        self.report['getter_clip_observations'] = []
        self.entries = []
        for action, rva, prefix, length, digest, label in ENTRY_SPECS:
            owner = NativeEntryOwner(self)
            trace = CircleEntry_EntryTrace(owner, (rva, prefix, length, digest, 2, label))
            self.entries.append((action, rva, owner, trace))
        self.entry_ready = False
        self.report['native_circle_entries'] = []
        self.ground_stage = 'CAPTURED_MOVEMENT'
        self.ground_trial = None
        self.ground_prepared = None
        self.ground_entry_consumed = 0
        self.ground_wait_release = False
        self.report['ground_native_vector_trials'] = []
        self.report['ground_native_trial_total'] = 0
        self.report['native_circle_entry_record_total'] = 0
        self.slide_ref = None
        self.slide_original = None
        self.slide_target = None
        self.slide_pending = False
        self.slide_ready = False
        self.slide_cycle = None
        self.last_slide = False
        self.report['sdk_slide_direction'] = dict(asset=self.SLIDE_PATH, field='LaunchDirection.RelativeDirection', requested='ParentVelocity2D', scope='shared loaded Slide asset', source='Kevin-hDev Apex Movement: slide_direction.py', applied=False, restored=False, sdk_writes=0)
        self.report['sdk_slide_cycles'] = []
        self.report['sdk_slide_cycle_total'] = 0
        self.rotate_schema_checked = False
        self.rotate_last_slide = None
        self.rotate_capture_count = 0
        self.report['rotate_state_samples'] = []
        self.slide_override_active = False
        self.ab_count = 0
        self.slide_override_t = None
        self.slide_hold_rotation = None
        self.slide_last_body_yaw = None
        self.slide_exit_yaw = None
        self.report['slide_exit_cycles'] = []
        self.report['slide_caller_ab_cycles'] = []
        self.report['slide_body_samples'] = []
        self.head_tick = 0
        self.head_last_slide = None
        self.report['head_pose_samples'] = []
        self.report['head_pose_sample_total'] = 0
        self.report['slide_live_cycle_total'] = 0
        self.report['input_help'] = dict(device='gamepad', sprint='L3 while moving', ground_dash='repeat L3 while sprinting, or native Circle Dash when admitted', air_dash='Circle after jumping; target is body yaw captured at Circle press', crouch='native Circle when standing', slide='native Circle Slide during Sprint when classified as Slide', combat='native ADS/fire aim', stop='rerun this same script')
        self.report['air_clip_equipped_states'] = ['Active', 'Reloading']
        self.special_paused = False
        self.special_signature = None
        self.release_barrier = False
        self.report['special_state_edges'] = []
        self.report['special_pause_updates'] = 0
        self.report['special_resume_count'] = 0
        self.jump_idle_owned = False
        self.jump_cycle = None
        self.jump_sequence = 0
        self.report['jump_idle_ab_cycles'] = []
        self.report['jump_idle_ab_rows'] = []
        self.slam_trace_window = False
        self.slam_sequence = 0
        self.slam_cycle = None
        self.report['ground_slam_native_records'] = []
        self.report['ground_slam_rotate_state_samples'] = []
        self.report['ground_slam_native_cycles'] = []
        self.slam_override_owned = False
        self.slam_heading_owned = False
        self.slam_exit_root_owned = False
        self.report['ground_slam_native_ab_rows'] = []
        self.slam_pose_owned = False
        self.report['ground_slam_pose_ab_rows'] = []
        self.report['input_help'] = dict(device='keyboard/mouse and gamepad; physical standard keys observed, no rebinding', movement='WASD or native left stick; target follows actual horizontal movement', sprint='native Shift/L3 press while moving; no automatic sprint', ground_dash='repeat native Sprint action during Sprint; native ground Dash entries remain observed', air_dash='native Shift in air or Circle; captured body direction with current-weapon Forward clips', crouch_slide='native bindings/classification/resources retained', jump='native Space/Cross', combat='native ADS/fire', stop='rerun same script')
        self.report['unified_input_transitions'] = []
        self.last_input_source = None
        self.ground_observer_state = {}
        self.ground_observer_assets = {}
        self.report.update(ground_input_pose_rows=[], ground_input_pose_total=0, ground_input_pose_assets={}, ground_input_pose_diagnostic_errors=[], ground_input_pose_note='Read-only existing Widget PRE and gameplay POST snapshots. PRE is before the Widget original, not before each native input callback. Native Sprint entry records remain the exact entry evidence. Four Dash players: keys, Sequence identity, weight and time; snapshot reader makes no clip/getter writes; the gameplay clip correction is independent. Blend weights are observed node state, not proof of animation worker evaluation timing. Last 1024 rows; transitions sampled immediately, steady activity every second update. Existing movement, admission/resources, lifecycle and native detours unchanged.')
        self.ground_clip_originals = []
        self.ground_clip_forward_ref = None
        self.ground_clip_anim_ref = None
        self.ground_clip_arm_update = None
        self.ground_clip_weapon_ref = None
        self.ground_clip_pawn_ref = None
        self.ground_clip_mesh_ref = None
        self.ground_b_completed = 0
        self.ground_dash_seen = False
        self.ground_vector_published = False
        self.report.update(ground_clip_events=[], ground_clip_native_replacements=[], ground_clip_cycles_applied=0, ground_clip_cycles_restored=0, ground_clip_restore_verified=True, combined_ground_note='Manual-stop combined gameplay. Confirmed Forward clips prepared for free grounded Dash; existing exact-owner/thread/caller phase-3 helper prepares aligned movement direction before native input. Circle publisher retained. Ground snapshots restored before air/special/combat handoffs and after native Dash. Native admission, charge checks, cooldown, Sprint/Slide classification retained. No new hooks or physical key queries. Combined weapon transitions and ground/air interaction still require gameplay validation.')
        self.report['probe'] = 'player_omnidirectional_gameplay'
        self.report['baseline'] = 'CombinedGroundLive V3; air-input experiment excluded'
        self.report['input_policy'] = 'No physical defaults. Intents from current EnhancedActionMappings; native movement vector and native action callbacks retain classification/admission.'
        self.report['scope_limits'] = 'Refactored validation build. Mapping adapter and call-pipeline require in-game/remap regression. FFYL/respawn/travel/save-load remain unvalidated.'
        self.report['note'] = 'Bounded widget diagnostics are not atomic native pose timing evidence. Original native fingerprint/owner/thread/byte checks retained.'
        self.report['input_help'] = {'movement': 'native movement input', 'sprint': 'configured Sprint action; manual only', 'dash': 'native Dash/Crouch contexts plus repeat Sprint during Sprint', 'jump': 'configured Jump action', 'combat': 'configured Fire/Zoom intent plus native animation/ADS state', 'stop': 'rerun entry script'}
        self.report['lean_blend_experiment'] = 'Confirmed free-body Lean correction; no alternating A/B phase.'
        # Read once per session: the loader option applies to the next binding.
        self.collect_pose_diagnostics = settings.diagnostics_enabled()
        self.report['collect_pose_diagnostics'] = self.collect_pose_diagnostics

    def _sample_install(self):
        owner = getattr(self.updates, '_owner', None)
        if owner is None or not owner.active or owner.live_widget() is None:
            raise RuntimeError('Existing mod update widget unavailable; no producer will be created')
        if getattr(self.mod, '_player_orient_to_movement_ab', None) is not None:
            raise RuntimeError('Restore orient-to-movement A/B first')
        pc, pawn, camera = self.mod._get_runtime()
        if any((o is None for o in (pc, pawn, camera))) or str(pawn.Class.Name) != 'OakCharacter':
            raise RuntimeError('Loaded on-foot local OakCharacter required')
        if not self.mod._third_person_enabled or not self.mod._third_person_pushed:
            raise RuntimeError('Enable normal TPS before arming')
        if bool(pc.bShowMouseCursor) or any((bool(getattr(self.mod, f, False)) for f in ('_ads_active', '_vehicle_camera_active', '_shop_camera_active', '_ladder_active', '_slide_active'))):
            raise RuntimeError('Exit menus, ADS, vehicles and special movement before arming')
        movement = pawn.OakCharacterMovement
        if (movement is None or int(movement.MovementMode) != 1) and not allow_exit_air(self, pc, pawn, camera, movement):
            raise RuntimeError('Grounded walking movement required')
        if str(camera.GetActorCameraMode(pawn)) != 'ThirdPerson':
            raise RuntimeError('Normal ThirdPerson camera mode required')
        self.refs = tuple((WeakPointer(o) for o in (pc, pawn, camera, movement)))
        if any((ref() is None for ref in self.refs)):
            raise RuntimeError('Bound object already expired')
        self.report['objects'] = dict(zip(('controller', 'pawn', 'camera', 'movement'), map(describe, (pc, pawn, camera, movement))))
        for obj, methods in ((pc, ('GetControlRotation',)), (pawn, ('K2_GetActorRotation', 'GetLastMovementInputVector')), (camera, ('GetCameraRotation',))):
            for name in methods:
                if not callable(getattr(obj, name, None)):
                    raise RuntimeError('SDK getter unavailable: ' + name)
        # The supervisor's on-foot gate refreshed this controller's mappings with
        # require_complete in the last updates (count changes refresh at once).
        # Reuse that reader instead of a second full scan in the bind update.
        shared = getattr(getattr(self, 'lifecycle_supervisor', None), 'input_owner', None)
        if shared is not None and shared.matches(pc) and shared.complete:
            self.inputs = shared
        else:
            self.inputs = NativeBindings(pc)
            self.inputs.refresh(require_complete=True)
        self.report['optional_field_errors'] = {}
        if self.updates.has_hook(*self.spec):
            raise RuntimeError('Observer hook identifier already occupied')
        self.active = True
        self.registered = True
        self.updates.add_hook(*self.spec, self.frame)
        if not self.updates.has_hook(*self.spec):
            raise RuntimeError('Observer hook installation unverified')

    def _root_install(self):
        self._sample_install()

    def _body_install(self):
        pawn = self.mod._get_runtime()[1]
        if pawn is None or not callable(getattr(pawn, 'K2_SetActorRotation', None)):
            raise RuntimeError('Actor rotation setter unavailable')
        self._root_install()

    def _combat_install(self):
        pc, pawn, camera = self.mod._get_runtime()
        mesh = pawn.Mesh if pawn is not None else None
        anim = mesh.AnimScriptInstance if mesh is not None else None
        weapon = camera.CameraModeInputs.Weapon if camera is not None else None
        if anim is None or weapon is None:
            raise RuntimeError('Player animation and weapon required')
        for field in ('bIsFiring', 'bIsReloading'):
            if not isinstance(getattr(anim, field), bool):
                raise RuntimeError('Expected boolean animation field: ' + field)
        if anim.CurrentWeapon != weapon:
            raise RuntimeError('Animation weapon ownership not settled')
        self.combat_refs = tuple((WeakPointer(o) for o in (mesh, anim, weapon)))
        self.report['combat_objects'] = dict(zip(('mesh', 'animation', 'weapon'), map(describe, (mesh, anim, weapon))))
        self._body_install()

        self.grenade_facing.install()

    def _sprint_install(self):
        self._combat_install()
        movement = self.bound()[3]
        if any((bool(getattr(movement, n)) for n in ('bWantsToSprint', 'bWantsToStartSprinting', 'bIsSprinting'))):
            raise RuntimeError('Stand still outside sprint before arming')

    def _manual_dash_install(self):
        enum = find_enum('/Script/OakGame.ECharacterDashDirection')
        if tuple((int(getattr(enum, n)) for n in ('Up', 'Left', 'Down', 'Right'))) != (0, 1, 2, 3):
            raise RuntimeError('Reviewed Dash direction enum differs')
        self.dash_enum = enum
        fn = find_object('Function', '/Script/OakGame.OakCharacter:SetWantsToDash')
        if fn is None or [(str(p.Name), str(p.Class.Name)) for p in fn._properties()] != [('bNewWantsToDash', 'BoolProperty'), ('InDirection', 'EnumProperty')]:
            raise RuntimeError('Dash SDK request signature differs')
        self._sprint_install()
        if bool(self.bound()[3].bWantsToDash) or bool(self.bound()[1].IsCharacterDashing()):
            raise RuntimeError('Stand still outside Dash before arming')

    def _manual_dash_owners(self):
        return (self.native, self.aim_native, self.idle_native, self.idle_update, self.direction_trace, self.index_trace, self.route, self.dash_branch)

    def owners(self):
        return (*self._manual_dash_owners(), self.vector_trace)

    def _handoff_disable_handoff_overrides(self):
        self.control[0] = 0
        self.control[8] = 0
        self.native.control[0] = 0
        self.native.control[7] = 0
        for owner in (self.aim_native, self.idle_native, self.idle_update):
            owner.control[0] = 0
        self.direction_trace.control[7] = 0
        self.index_trace.control[7] = 0
        self.dash_branch.control[0] = 0
        self.dash_branch.control[7] = 0
        self.vector_trace.control[0] = 0
        self.vector_trace.control[7] = 0
        self.vector_trace.control[12] = 0
        self.restore_blend()

    def _slide_state_install(self):
        pc, pawn, camera = self.mod._get_runtime()
        if pawn is None:
            raise RuntimeError('Local player unavailable for rotation-state preflight')
        movement = pawn.OakCharacterMovement
        self.validate_rotate_schema(movement)
        command = movement.CurrentRotateToState.CommandData
        for name in ('Duration', 'InterpSpeed', 'MaxYawRate', 'MaxPitchRate', 'TargetActor', 'TargetSocket', 'TargetLocation', 'bFreezeRotation', 'bUseEasing', 'bUpdateCamera'):
            getattr(command, name)
        self._manual_dash_install()

    def install(self):
        pawn = self.mod._get_runtime()[1]
        if pawn is None or pawn.Mesh is None:
            raise RuntimeError('Local mesh missing for head observation')
        mesh = pawn.Mesh
        anim = mesh.AnimScriptInstance
        if anim is None:
            raise RuntimeError('Local animation missing for head observation')
        for method in ('GetNumBones', 'GetBoneName', 'GetSocketRotation', 'K2_GetComponentRotation'):
            if not callable(getattr(mesh, method, None)):
                raise RuntimeError('Required head getter missing: ' + method)
        count = int(mesh.GetNumBones())
        if not 1 <= count <= 512:
            raise RuntimeError('Head skeleton count outside bounds')
        with hitch.step('install.bones'):
            if self.collect_pose_diagnostics or not callable(getattr(mesh, 'GetBoneIndex', None)):
                # Full catalog (one SDK call per bone) only for pose diagnostics.
                names = set(bone_names('head', self, mesh, count))
                missing = [n for n in self.BONE_NAMES if n not in names]
            else:
                missing = [n for n in self.BONE_NAMES if not 0 <= int(mesh.GetBoneIndex(n)) < count]
        if missing:
            raise RuntimeError('Reviewed head/spine bones missing')
        for name in self.AIM_NODES:
            node = getattr(anim, name)
            if str(node.RotationChannelName.TagName) != 'RotationChannel.Aim':
                raise RuntimeError('Reviewed Aim node channel differs: ' + name)
            for field in ('ALPHA', 'BlendWeight', 'AlphaInputType', 'bInvertAlpha', 'BlendSpaceKey', 'BlendSpace'):
                getattr(node, field)
        for name in ('AimYaw', 'AimPitch', 'AimEnableAlpha', 'HeadEnableAlpha'):
            getattr(anim, name)
        self.head_mesh = WeakPointer(mesh)
        self.head_anim = WeakPointer(anim)
        self.report['head_pose_binding'] = dict(mesh=describe(mesh), animation=describe(anim), bones=list(self.BONE_NAMES), aim_nodes=list(self.AIM_NODES))
        self._slide_state_install()
        self.staged_bind = True

    def disable_handoff_overrides(self):
        self.aim_native.crouch_control[0] = 0
        self._handoff_disable_handoff_overrides()

    def _special_disable_special_controls(self):
        for action, rva, owner, trace in self.entries:
            owner.control[16] = 0
            owner.control[0] = 0
        self.disable_handoff_overrides()
        self.native.slide_control[0] = 0

    def discard_special_input(self):
        if self.entry_ready:
            self.consume_entry()
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
        self.ground_prepared = None

    def enter_special(self):
        self.grenade_facing.cancel('SPECIAL_NATIVE_HANDOFF')
        self.disable_special_controls()
        if self.air_cycle is not None:
            self.close_air_cycle('SPECIAL_NATIVE_HANDOFF')
        else:
            self.restore_clips()
        if self.cycle_start is not None:
            movement = self.bound()[3]
            velocity = parts(movement.Velocity, ('X', 'Y', 'Z'))
            self.close_cycle('SPECIAL_NATIVE_HANDOFF', dict(sprint_state={'bIsSprinting': bool(movement.bIsSprinting)}, horizontal_speed=math.hypot(velocity['X'], velocity['Y'])))
        self.close_ground_trial('SPECIAL_NATIVE_HANDOFF')
        self.restore_slide()
        self.slide_ready = False
        self.slide_override_active = False
        self.slide_override_t = None
        self.slide_hold_rotation = None
        self.slide_exit_yaw = None
        self.last_slide = False
        self.slide_cycle = None
        self.air_previous_t = None
        self.air_hold_yaw = None
        self.special_paused = True

    def _special_paused_special_frame(self, obj, args, ret, func):
        self.disable_special_controls()
        self.audit_owners(entries=True)
        self.discard_special_input()
        self.read_combat()
        self._sample_frame(obj, args, ret, func)
        if not self.active:
            return
        self.report['special_pause_updates'] += 1
        self.report['samples'][-1]['handoff_state'] = 'SPECIAL_NATIVE_PAUSE'
        if self.report.get('last_lifecycle_context', {}).get('hybrid_scope_pause'):
            self.report['samples'][-1]['handoff_state'] = 'HYBRID_SCOPE_NATIVE_PAUSE'
            self.report['hybrid_scope_pause_updates'] = self.report.get('hybrid_scope_pause_updates', 0) + 1
        self.trim_diagnostics()

    def _special_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        if not self.updates.is_game_thread():
            return
        try:
            if not self.mod._third_person_enabled and self.lifecycle_managed:
                self.lifecycle_supervisor.pause_perspective()
                return
            objects = self.bound()
            pc, pawn, camera, movement = objects
            context = self.state_context(objects)
            self.report['last_lifecycle_context'] = context
            if not context['third_person']:
                self.save_state_edge(context, 'STOP_TPS_OR_UI')
                self.finish('TPS_OR_UI_CHANGED')
                return
            if context['flags']['_vehicle_camera_active']:
                self.save_state_edge(context, 'STOP_CONTEXT_REQUIRES_REBIND')
                self.finish('UNSUPPORTED_CONTEXT')
                return
            slide = context['flags']['_slide_active']
            # The camera returns from BL4's slide mode only after the slide
            # flag fell; that hand-back belongs to the slide, not a special state.
            exiting = self.slide_exit_pending(camera, context['camera_mode'], slide)
            context['hybrid_scope_pause'] = hybrid_ads.omni_pause_required(self)
            special = self.ground_slam_pose_native or context['hybrid_scope_pause'] or context.get('mouse_cursor', False) or context['flags']['_shop_camera_active'] or context['flags']['_ladder_active'] or (int(movement.MovementMode) not in (1, 3)) or (context['camera_mode'] != 'ThirdPerson' and (not ((slide or exiting) and context['camera_mode'] in ('Slide', 'Default'))))
            buttons = self.controls_down(pc)
            if special:
                signature = (context['movement_mode'], context['custom_movement_mode'], context['camera_mode'], context['flags']['_ladder_active'], context.get('mouse_cursor', False), context['flags']['_shop_camera_active'], context['hybrid_scope_pause'])
                if not self.special_paused:
                    self.enter_special()
                if signature != self.special_signature:
                    self.save_state_edge(context, 'SPECIAL_PAUSED')
                    self.special_signature = signature
                self.release_barrier = True
                self.paused_special_frame(obj, args, ret, func)
                return
            if self.special_paused:
                if buttons:
                    if self.special_signature != 'RELEASE':
                        self.save_state_edge(context, 'WAIT_INPUT_RELEASE')
                        self.special_signature = 'RELEASE'
                    self.paused_special_frame(obj, args, ret, func)
                    return
                self.discard_special_input()
                self.special_paused = False
                self.special_signature = None
                self.release_barrier = False
                self.air_previous_t = None
                self.air_circle_previous = False
                self.ground_wait_release = False
                self.resume_handoff()
                self.report['special_resume_count'] += 1
                self.save_state_edge(context, 'SPECIAL_RESUMED')
            self._slide_live_frame(obj, args, ret, func)
        except Exception as exc:
            self.report['errors'].append('Special-state handoff: ' + repr(exc)[:500])
            try:
                self.disable_special_controls()
                self.finish('SPECIAL_HANDOFF_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def _input_source_frame(self, obj, args, ret, func):
        self._slam_pose_frame(obj, args, ret, func)
        if not self.active or not self.report['samples']:
            return
        row = self.report['samples'][-1]
        source = row['movement_input_source']
        if source != self.last_input_source:
            self.report['unified_input_transitions'].append(dict(update=self.frames, source=source, movement_active=row['movement_input_active'], movement_strength=row['movement_input_strength']))
            del self.report['unified_input_transitions'][:-128]
            self.last_input_source = source

    def _ground_pose_frame(self, obj, args, ret, func):
        cache = getattr(getattr(self, 'lifecycle_supervisor', None), 'rebind_cache', None)
        if cache is not None and self.active and not all((self.ready, self.blend_layout_ready, self.player_ready, self.sprint_ready, self.route_ready, self.vector_ready, self.entry_ready)):
            with cache.transaction(self):
                self._ground_pose_work(obj, args, ret, func)
        else:
            self._ground_pose_work(obj, args, ret, func)

    def _ground_pose_work(self, obj, args, ret, func):
        self._input_source_frame(obj, args, ret, func)
        if self.active and (not self.busy):
            self.observe_ground_input_pose('POST')

    def disarm_ground_vector(self):
        if self.ground_vector_published:
            self.vector_trace.control[7] = 0
            self.ground_vector_published = False

    def prepare_ground(self, sample):
        self._ground_vector_prepare_ground(sample)
        prepared = self.ground_prepared
        if prepared is None:
            return
        pc, pawn, camera, movement = self.bound()
        if bool(pc.bShowMouseCursor) or int(movement.MovementMode) != 1 or int(movement.CustomMovementMode) != 0 or (not sample['normal_tps_sample']) or self.combat['active'] or bool(self.mod._slide_active) or bool(pawn.bIsCrouched) or bool(pawn.IsCharacterDashing()) or bool(movement.bWantsToDash) or (self.cycle_start is not None) or (self.air_cycle is not None) or (sample['horizontal_speed'] <= 100) or (abs(angle(sample['actor_rotation']['Yaw'], sample['velocity_yaw'])) > 5):
            return
        if not self.ground_clip_originals:
            anim = self.ground_clip_anim()
            weapon = camera.CameraModeInputs.Weapon
            state = 'None' if weapon is None else str(weapon.CurrentState)
            if weapon is None or anim.CurrentWeapon != weapon or state not in ('Active', 'Reloading') or (state == 'Reloading' and (not bool(anim.bIsReloading))):
                return
            self.ground_clip_weapon_ref = WeakPointer(weapon)
            self.ground_clip_arm_update = self.frames
            self.swap_ground_forward_clips()
        self.vector_trace.control[0] = 1
        self.vector_trace.control[8] = 0
        self.vector_trace.control[12] = 3
        self.vector_trace.control[7] = 1
        self.ground_vector_published = True

    def prepare_air_cycle(self, sample, attempt):
        self.disarm_ground_vector()
        self.restore_ground_clips()
        self._clip_lookup_prepare_air_cycle(sample, attempt)

    # One-off binding work of a new session. Formerly all of it ran inside the
    # first RUN update (one long frame on load, respawn and vehicle exit). Now
    # at most one step runs per steady RUN update, in the former order; the
    # pipeline starts once every step is done. Paused/special updates keep their
    # original handling. The lazy sites in the pipeline call the same methods.
    BIND_STEPS = ('slide', 'vector', 'visual', 'sprint', 'route', 'root', 'entries')

    def pending_bind_step(self):
        ready = dict(slide=self.slide_ready, vector=self.vector_ready, visual=self.mesh_ref is not None,
                     sprint=self.sprint_ready, route=self.route_ready, root=self.ready,
                     entries=self.entry_ready)
        return next((name for name in self.BIND_STEPS if not ready[name]), None)

    def bind_step(self, pc, pawn, camera, movement):
        """Run one pending bind step on a RUN update; True when this update was used."""
        name = self.pending_bind_step()
        if name is None:
            self.staged_bind = False
            hitch.note('[OmniBind]', 'ready steps=' + str(len(self.report.get('bind_steps', [])))
                       + ' body_yaw=' + hitch.value(lambda: pawn.K2_GetActorRotation().Yaw)
                       + ' camera_yaw=' + hitch.value(lambda: pc.GetControlRotation().Yaw)
                       + ' impulse=' + str(self.impulse_index is not None))
            return False
        if self.classify_handoff(pc, pawn, camera, movement)[0] != 'RUN':
            return False
        cache = getattr(getattr(self, 'lifecycle_supervisor', None), 'rebind_cache', None)
        try:
            with (cache.transaction(self) if cache is not None else nullcontext()):
                getattr(self, '_bind_' + name)()
        except Exception as exc:
            self.report['errors'].append('Bind step ' + name + ': ' + repr(exc)[:500])
            try:
                self.finish('BIND_' + name.upper() + '_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))
            return True
        steps = self.report.setdefault('bind_steps', [])
        steps.append(name)
        return True

    def _bind_slide(self):
        with hitch.step('bind.slide'):
            self.apply_slide()

    def _bind_vector(self):
        with hitch.step('bind.vector'):
            self.vector_trace.install()
            self.vector_ready = True

    def _bind_visual(self):
        with hitch.step('bind.visual'):
            self.bind_visual()

    def _bind_sprint(self):
        with hitch.step('bind.sprint'):
            self.direction_trace.install()
            self.index_trace.install()
            self.sprint_ready = True

    def _bind_route(self):
        with hitch.step('bind.route'):
            self.prepare_native()
            self.route.install()
            self.dash_branch.install()
            self.control[0] = 1
            self.route_ready = True
        self.event('MANUAL_INPUT_READY')

    def _bind_root(self):
        with hitch.step('bind.root'):
            self.native.install()
            self.ready = True

    def _bind_entries(self):
        with hitch.step('bind.entries'):
            for action, rva, o, t in self.entries:
                o.base = self.base
                o.control[1] = self.handler_address
                o.control[2] = threading.get_native_id()
                o.control[4] = ctypes.addressof(o.buffer)
                o.control[7] = self.movement_address
                t.install()
            self.entry_ready = True
            self.report['native_circle_entry_installed'] = True
        logging.warning(TAG + ' NATIVE_ENTRY_READY Action_Crouch; manual-stop combined test')

    # Steady RUN frames re-read the owned native patch/vtable bytes round-robin:
    # at most two audit slots per update, every slot within NATIVE_AUDIT_PERIOD
    # updates. Object identity (bound(), anim address, handler) is still checked
    # every update; resume, rebind and the first update audit every slot.
    NATIVE_AUDIT_PERIOD = 6

    def native_audit_due(self, slot):
        if getattr(self, '_audit_full', True):
            return True
        return getattr(self, '_audit_tick', 0) % self.NATIVE_AUDIT_PERIOD == slot % self.NATIVE_AUDIT_PERIOD

    def audit_owners(self, entries=False):
        """Blanket per-update owner checks of paused paths, on the same round-robin."""
        slots = ((0, self.native), (1, self.aim_native), (2, self.idle_native), (3, self.idle_update),
                 (4, self.route), (5, self.dash_branch), (6, self.direction_trace),
                 (7, self.index_trace), (8, self.vector_trace))
        for slot, owner in slots:
            if owner.hook is not None and self.native_audit_due(slot):
                owner.validate()
        if entries and self.native_audit_due(9):
            for action, rva, owner, trace in self.entries:
                if trace.hook is not None:
                    trace.validate()

    def disable_special_controls(self):
        self.disarm_ground_vector()
        try:
            self.restore_ground_clips()
        finally:
            self._special_disable_special_controls()

    @hitch.root("gameplay")
    @root_span("callback.gameplay")
    def frame(self, obj, args, ret, func):
        if not self.active or self.busy or (not self.updates.is_game_thread()):
            return
        input_scope = None
        self.open_callback_scope()
        self.free_look_context = False
        try:
            if not self.mod._third_person_enabled and self.lifecycle_managed:
                self.lifecycle_supervisor.pause_perspective()
                return
            pc, pawn, camera, movement = self.bound()
            # One configured-key evaluation per owned callback.
            input_scope = self.inputs
            input_scope.begin_frame(coherent=True)
            if getattr(self, 'staged_bind', False) and self.bind_step(pc, pawn, camera, movement):
                return
            self.ground_slam_pose_native = self.native_slam_pose_context(pawn, camera, movement)
            if self.ground_slam_pose_native:
                self.release_native_slam_pose()
                self.close_jump('NATIVE_SLAM_POSE')
            elif (getattr(self, 'slam_heading_owned', False)
                  or getattr(self, 'slam_exit_root_owned', False)):
                # Disarm before normal Omni publishes its own TurnState gates.
                self.disarm_slam_heading()
            dash = self.is_dashing(pawn)
            self.disarm_ground_vector()
            if self.ground_clip_originals:
                anim = self.ground_clip_anim()
                weapon = camera.CameraModeInputs.Weapon
                changed = self.ground_clip_weapon_ref is None or self.ground_clip_weapon_ref() != weapon
                forward = self.ground_clip_forward_ref()
                replaced = any((getattr(anim, n).Sequence != forward for n, _, _, _ in self.ground_clip_originals))
                handoff = int(movement.MovementMode) != 1 or int(movement.CustomMovementMode) != 0 or bool(pc.bShowMouseCursor) or bool(self.mod._vehicle_camera_active) or bool(self.mod._slide_active) or bool(self.mod._ads_active) or bool(pawn.bIsCrouched) or (self.camera_mode(pawn, camera) != 'ThirdPerson')
                self.read_combat()
                if changed or replaced or handoff or self.combat['active'] or (self.ground_dash_seen and (not dash)):
                    self.restore_ground_clips()
                    if self.ground_dash_seen and (not dash):
                        self.ground_b_completed += 1
                    self.ground_dash_seen = False
            if dash and int(movement.MovementMode) == 1 and self.ground_clip_originals:
                self.ground_dash_seen = True
            self._ground_pose_frame(obj, args, ret, func)
            publish_free_look(self)
            if self.ground_slam_pose_native:
                self.publish_native_slam_heading()
            self._audit_tick = getattr(self, '_audit_tick', 0) + 1
            self._audit_full = False
        except Exception as exc:
            self.report['errors'].append('Combined ground gameplay: ' + repr(exc)[:500])
            try:
                self.finish('COMBINED_GROUND_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

        finally:
            self.close_callback_scope()
            if input_scope is not None:
                input_scope.end_frame()

    def restore_body_rotation(self):
        # No snapback to the yaw captured when following started (possibly
        # minutes earlier). Removing the native TurnState/Aim/Idle overrides
        # returns body rotation to the game; the actor keeps its current yaw.
        if not self.restore_pending:
            return
        self.report['restore'] = {'status': 'NO_SNAPBACK_NATIVE_ROTATION_RESUMES',
                                  'follow_start_rotation': self.original_rotation}
        self.restore_pending = False

    def finish(self, reason):
        self.active = False
        # Any later bound() in the unwinding callback validates fully again.
        self.close_callback_scope()
        failures = []

        def attempt(label, operation, sdk_write=False):
            try:
                if sdk_write and (not self.updates.is_game_thread()):
                    raise RuntimeError('SDK restoration requires owned game thread')
                operation()
            except Exception as exc:
                failures.append(label + ': ' + repr(exc))
        self.control[0] = 0
        self.control[8] = 0
        for owner in self.owners():
            control = getattr(owner, 'control', None)
            if control is not None:
                control[0] = 0
        self.native.control[7] = 0
        self.native.slide_control[0] = 0
        self.vector_trace.control[7] = 0
        self.vector_trace.control[12] = 0
        self.direction_trace.control[7] = 0
        self.index_trace.control[7] = 0
        self.dash_branch.control[7] = 0
        self.aim_native.crouch_control[0] = 0
        for action, rva, owner, trace in self.entries:
            owner.control[0] = 0
            owner.control[16] = 0
        self.jump_idle_owned = False
        self.slam_override_owned = False
        self.slam_heading_owned = False
        self.slam_exit_root_owned = False
        if 'ground_slam_heading_hold' in self.report:
            self.report['ground_slam_heading_hold']['enabled'] = False
            self.report['ground_slam_heading_hold']['root_correction_skipped'] = False
        self.slam_pose_owned = False
        attempt('grenade SDK subscription', self.grenade_facing.close)
        if self.air_cycle is not None:
            try:
                self.close_air_cycle('AIR_PROBE_STOP')
            except Exception as exc:
                self.report['errors'].append('Air final diagnostics: ' + repr(exc)[:500])
        attempt('ground clips', self.restore_ground_clips, True)
        attempt('air clips', self.restore_clips, True)
        if not self.clip_originals:
            self.air_cycle = None
        attempt('native Dash request', self.clear_request, True)
        attempt('Sprint intent', self.restore_sprint_intent, True)
        attempt('Slide setting', self.restore_slide, True)
        attempt('Lean blend', self.restore_blend, True)
        attempt('body rotation', self.restore_body_rotation, True)
        attempt('ground cycle bookkeeping', lambda: self.close_ground_trial('STOPPED_' + reason))
        for action, rva, owner, trace in reversed(self.entries):
            attempt('entry ' + action, trace.stop)
        owners = list(self.owners())
        for owner in reversed(owners):
            attempt(type(owner).__name__, owner.stop)
        if self.registered:

            def remove_subscription():
                if self.updates.has_hook(*self.spec):
                    self.updates.remove_hook(*self.spec)
                if self.updates.has_hook(*self.spec):
                    raise RuntimeError('Gameplay subscription removal unverified')
                self.registered = False
            attempt('gameplay subscription', remove_subscription)
        remaining = sum((owner.hook is not None for owner in owners)) + sum((trace.hook is not None for action, rva, owner, trace in self.entries))
        if remaining:
            failures.append('Owned native workers still installed: ' + str(remaining))
        if self.registered:
            failures.append('Gameplay subscription still installed')
        if self.grenade_facing.registered:
            failures.append('Grenade subscription still installed')
        self.report['native_circle_entry_counters'] = self.entry_counters()
        self.report['native_circle_entry_restore_verified'] = all((trace.hook is None for action, rva, owner, trace in self.entries))
        self.report['sprint_native_restoration_verified'] = self.direction_trace.hook is None and self.index_trace.hook is None and (not self.sprint_pending)
        self.report['manual_native_restoration_verified'] = self.route.hook is None and self.dash_branch.hook is None and (not self.cycle_pending_clear)
        self.report['vector_trace_restoration_verified'] = self.vector_trace.hook is None
        self.report['native_input_vector_overrides'] = self.report['native_input_vector_overrides_total']
        self.report.update(status=reason if not failures else 'CLEANUP_INCOMPLETE', sdk_hooks=int(self.registered) + int(self.grenade_facing.registered), native_patches=remaining, updates_seen=self.frames, total_sample_count=self.frames, sample_count=len(self.report['samples']), duration_seconds=monotonic() - self.started, cleanup_complete=not failures, cleanup_failures=failures)
        for failure in failures:
            self.report['errors'].append('Cleanup: ' + failure[:1000])
        if not getattr(self, 'lifecycle_managed', False) and (self.collect_pose_diagnostics or failures or self.report['errors']):
            attempt('report save', lambda: write_report(self.path, self.report))
        if failures:
            self.report['cleanup_complete'] = False
            setattr(self.mod, KEY, getattr(self, 'lifecycle_supervisor', self))
            raise RuntimeError('Inactive; cleanup incomplete: ' + '; '.join(failures))
        if getattr(self.mod, KEY, None) is self:
            delattr(self.mod, KEY)
