"""Animation responsibility; explicit pipeline calls, no historical probe inheritance."""
from .rebind_cache import layout_query, bone_names
from time import monotonic
import math
import struct
from unrealsdk import find_object
from .common import log as logging
from unrealsdk.unreal import WeakPointer
from .common import TAG, MAX_SAMPLES, describe
from .combat_handoff import SprintFireHandoff
from .carry_throw_handoff import CarryThrowHandoff
from .throw_handoff import FRESH_MONTAGE_SECONDS, ThrowHandoff
from .native_fire_activity import NativeFireActivity
from .weapon_fire_diagnostics import WeaponFireDiagnostics
from .visual_guard import validate_visual
from . import hitch

# Exceptions a native state read can raise; anything else is a real defect.
NATIVE_READ_ERRORS = (RuntimeError, OSError, ValueError, struct.error)
MAX_READ_FAILURE_REASONS = 16
# Montage UFunction failures (missing function, invalid object, bad argument).
MONTAGE_ERRORS = (AttributeError, RuntimeError, TypeError, ValueError)
# Console lines for the first throws of a session; episodes stay in the report.
THROW_LOG_LIMIT = 8

def observe_hybrid_scope(session, pc):
    """Hybrid ADS Mode: a Sprint press while ADS is held toggles the scope.

    BL4 ignores Sprint while zoomed, so the configured Sprint key is only read
    here (rising edge, once per press); the loader performs the camera switch.
    """
    sprint = bool(session.inputs.snapshot(pc).get('sprint', False))
    rising = sprint and not getattr(session, 'hybrid_previous_sprint', False)
    session.hybrid_previous_sprint = sprint
    if not rising or not bool(getattr(session.mod, '_ads_active', False)):
        return None
    from .. import hybrid_ads
    if not hybrid_ads.option_enabled(session.mod):
        return None
    # Do not change the camera inside the gameplay sampling pipeline. Its
    # remaining guards still require the camera observed at frame entry.
    result = hybrid_ads.request_scope(session.mod, session)
    session.report['hybrid_scope_last'] = result
    session.report['hybrid_scope_presses'] = int(session.report.get('hybrid_scope_presses', 0)) + 1
    return result


class AnimationMixin:

    def validate_visual(self, *, capture=False):
        return validate_visual(self, capture=capture)

    def _visual_bind_visual(self):
        mesh = self.bound()[1].Mesh
        if mesh is None:
            raise RuntimeError('Bound pawn Mesh unavailable')
        for name in ('GetNumBones', 'GetBoneName', 'GetSocketRotation', 'K2_GetComponentRotation'):
            if not callable(getattr(mesh, name, None)):
                raise RuntimeError('Required visual SDK getter unavailable: ' + name)
        self.mesh_ref = WeakPointer(mesh)
        count = int(mesh.GetNumBones())
        if not 1 <= count <= 512:
            raise RuntimeError('Skeleton bone count outside diagnostic bounds')
        if not getattr(self, 'collect_pose_diagnostics', True):
            # The later player bind clears the selection in every mode; the full
            # catalog (one SDK call per bone) is diagnostic report data only.
            self.bones = []
            self.report['visual_binding'] = {'mesh': describe(mesh), 'bone_count': count, 'all_bone_names': [], 'selected_bones': [], 'selection_note': 'Production bind: bone catalog only with pose diagnostics.'}
            return
        names = list(bone_names('visual', self, mesh, count))
        groups = (('root', lambda n: 'root' in n or n in ('origin', 'base')), ('pelvis', lambda n: 'pelvis' in n or 'hips' in n or n == 'hip'), ('spine', lambda n: 'spine' in n), ('neck', lambda n: 'neck' in n), ('head', lambda n: 'head' in n), ('thigh', lambda n: 'thigh' in n))
        chosen = []
        for label, predicate in groups:
            candidates = [n for n in names if predicate(n.lower())]
            selected = [candidates[0]] if candidates else []
            if label == 'spine' and len(candidates) > 1:
                selected.append(candidates[-1])
            for name in selected:
                if name not in chosen:
                    chosen.append(name)
        if len(chosen) < 3:
            for name in names[:4]:
                if name not in chosen:
                    chosen.append(name)
        self.bones = chosen[:8]
        self.report['visual_binding'] = {'mesh': describe(mesh), 'bone_count': count, 'all_bone_names': names, 'selected_bones': self.bones, 'selection_note': 'Name-based diagnostic candidates; semantic roles and facing axes are unverified.'}

    def _visual_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        try:
            if not self.updates.is_game_thread():
                raise RuntimeError('Visual capture requires owned game thread')
            if self.mesh_ref is None:
                self.bind_visual()
            if self.collect_pose_diagnostics:
                row = self.visual()
                self.report['visual_samples'].append(row)
            else:
                # Gameplay still validates the bound animation and AimOffset.
                # Rotations, object descriptions and pose rows are diagnostics.
                self.validate_visual()
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('VISUAL_CAPTURE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' RESTORE_OR_SAVE_FAILED rerun to retry ' + repr(cleanup))
            return
        self._body_frame(obj, args, ret, func)

    def _aim_binding_bind_visual(self):
        self._visual_bind_visual()
        mesh = self.mesh_ref()
        anim = mesh.AnimScriptInstance
        if anim is None:
            raise RuntimeError('Bound animation instance unavailable')
        self.anim_ref = WeakPointer(anim)
        self.anim_address = int(anim._get_address())
        node = getattr(anim, self.NODE_NAME)
        if str(node.RotationChannelName.TagName) != 'RotationChannel.Aim' or str(node.BlendSpaceKey.TagName) != 'AnimSet.Player.3rd.AimO_3rd':
            raise RuntimeError('Reviewed normal AimOffset binding differs')
        for name in self.INPUT_NAMES:
            getattr(anim, name)
        self.report['animation_direction_note'] = 'Read-only animation inputs and the reviewed normal AimOffset node. Direction is compared as a candidate degree angle, not assumed to use Actor space. BlendWeight and ALPHA alone do not prove final pose contribution. Values may come from different animation evaluations.'
        names = self.report['visual_binding']['all_bone_names']
        if 'Spine5' in names:
            self.bones = ['Spine5' if name == 'Weapon_Bones_to_Spine' else name for name in self.bones]
            self.report['visual_binding']['selected_bones'] = self.bones
        self.report['aim_node_binding'] = {'name': self.NODE_NAME, 'channel': 'RotationChannel.Aim', 'blend_space_key': 'AnimSet.Player.3rd.AimO_3rd', 'writes': 0}

    def sample_fire_activity(self, pawn, weapon):
        """Native Sprint-fire state; a read failure disables only the handoff.

        Structure deviations (weapon not in the Weapon-User, unexpected bounds,
        binding changed during capture, changed measured code) return an
        unsupported row and are logged once per reason. Omni keeps running.
        """
        reader = getattr(self, 'sprint_fire_activity', None)
        try:
            if reader is None:
                reader = self.sprint_fire_activity = NativeFireActivity(self.mod)
            if reader is False:
                reason = self.sprint_fire_reader_error
            else:
                return reader.sample(pawn, weapon)
        except NATIVE_READ_ERRORS as exc:
            reason = type(exc).__name__ + ': ' + str(exc)[:160]
            if reader is None:
                # Measured code or build differs: never retry this session.
                self.sprint_fire_activity = False
                self.sprint_fire_reader_error = reason
        failures = self.report.setdefault('sprint_fire_read_failures', {})
        if reason not in failures and len(failures) >= MAX_READ_FAILURE_REASONS:
            reason = 'OTHER'
        failures[reason] = failures.get(reason, 0) + 1
        if failures[reason] == 1:
            logging.warning(TAG + ' SPRINT_FIRE_NATIVE_UNAVAILABLE ' + reason
                            + '; handoff off for this press, omni keeps running')
        return dict(supported=False, pending=False, active=False, reason='READ_FAILED')

    def read_throw(self, pc, anim, combat):
        """Measured carry/grenade handback; legacy fallback for other ordnance."""
        snapshot = self.inputs.snapshot(pc)
        present = getattr(self.inputs, 'present_roles', None)
        throwable_context = bool(present) and 'zoom' not in present
        gadget = bool(snapshot.get('gadget', False))
        carry_intent = bool(snapshot.get('carry_throw', False))
        carry_context = bool(present) and 'carry_throw' in present
        combat['throw_intent'] = gadget or carry_intent
        combat['throwable_context'] = throwable_context
        eligible = (bool(self.mod._third_person_enabled) and not bool(pc.bShowMouseCursor)
                    and not any(bool(getattr(self.mod, name, False)) for name in
                                ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active')))
        carry = getattr(self, 'carry_throw_handoff', None)
        if carry is None:
            carry = self.carry_throw_handoff = CarryThrowHandoff()
            self.report['carry_throw_episodes'] = carry.episodes
        carrying = None
        if carry_context or carry.phase is not None:
            try:
                carrying = bool(anim.bIsCarrying)
            except MONTAGE_ERRORS as exc:
                self.report['carry_throw_state_error'] = type(exc).__name__ + ': ' + str(exc)[:160]
        carry_hold = carry.observe(intent=carry_intent, context=carry_context,
                                   carrying=carrying, eligible=eligible and not bool(self.mod._slide_active))
        self.report['carry_throw_episode_count'] = carry.started
        combat.update(carry_throw_intent=carry_intent, carry_throw_context=carry_context,
                      animation_is_carrying=carrying, carry_throw_hold=carry_hold,
                      carry_throw_phase=carry.phase)
        throw = getattr(self, 'throw_handoff', None)
        if throw is None:
            throw = self.throw_handoff = ThrowHandoff()
            self.report['throw_episodes'] = throw.episodes
        grenade = getattr(self, 'grenade_facing', None)
        grenade_hold = False
        if grenade is not None:
            handled, grenade_hold = grenade.observe(self.bound()[1], snapshot, eligible)
            combat.update(grenade_facing_hold=grenade_hold,
                          grenade_facing_phase=grenade.model.phase)
            if handled:
                # A native admission supersedes legacy freshness/sample heuristics
                # for this press, including its state-driven handback update.
                if throw.episode is not None:
                    grenade.legacy_transfers += 1
                    throw.end('NATIVE_GRENADE_HANDOFF', monotonic())
                throw.previous_intent = gadget
                self.report['throw_episode_count'] = (throw.started + carry.started
                    + grenade.model.admitted - grenade.legacy_transfers)
                return grenade_hold or carry_hold
        intent = gadget
        current = None
        tracking = getattr(self, 'throw_montage_error', None) is None
        if tracking and throw.needs_montage(intent):
            try:
                current = anim.GetCurrentActiveMontage()
            except MONTAGE_ERRORS as exc:
                tracking = False
                self.throw_montage_error = type(exc).__name__ + ': ' + str(exc)[:160]
                self.report['throw_montage_error'] = self.throw_montage_error
                logging.warning(TAG + ' THROW_MONTAGE_UNAVAILABLE ' + self.throw_montage_error
                                + '; throws hold combat only while the key is held')

        def is_playing(montage):
            if not tracking:
                return False
            try:
                return bool(anim.Montage_IsPlaying(montage))
            except MONTAGE_ERRORS:
                return False

        def is_fresh(montage):
            if not tracking:
                return False
            try:
                return 0.0 <= float(anim.Montage_GetPosition(montage)) <= FRESH_MONTAGE_SECONDS
            except MONTAGE_ERRORS:
                return False

        hold = throw.observe(intent=intent, source='gadget',
                             eligible=eligible, current=current, is_playing=is_playing,
                             is_fresh=is_fresh)
        event = throw.last_event
        if event in ('MONTAGE', 'NO_MONTAGE') and throw.started <= THROW_LOG_LIMIT:
            episode = throw.episode if event == 'MONTAGE' else throw.episodes[-1]
            if event == 'MONTAGE':
                logging.info(TAG + ' THROW_HOLD source=' + episode['source']
                             + ' montage=' + str(episode['montage']))
            else:
                logging.warning(TAG + ' THROW_NO_MONTAGE source=' + episode['source']
                                + '; body yaw held only while the key was held')
        self.report['throw_episode_count'] = throw.started + carry.started + (
            grenade.model.admitted - grenade.legacy_transfers if grenade is not None else 0)
        return hold or grenade_hold or carry_hold

    def read_combat(self):
        # One combat observation per owned callback. Clip-swap updates used to
        # evaluate it twice, which advanced the handoff state machines (rising
        # edges, NO_REQUEST_SAMPLES) twice per update while moving.
        if getattr(self, '_callback_scope', False) and getattr(self, '_callback_combat_read', False):
            return
        if not self.updates.is_game_thread():
            raise RuntimeError('Combat observation requires owned game thread')
        pc, pawn, camera, movement = self.bound()
        mesh, anim, weapon = (ref() for ref in self.combat_refs)
        if any((o is None for o in (mesh, anim))):
            raise RuntimeError('Bound combat animation expired')
        if pawn.Mesh != mesh or mesh.AnimScriptInstance != anim:
            raise RuntimeError('Combat animation ownership changed')
        weapon = camera.CameraModeInputs.Weapon
        weapon_state = str(weapon.CurrentState) if weapon is not None else 'None'
        actions = self.inputs.snapshot(pc)
        combat = {'ads_active': bool(self.mod._ads_active), 'fire_intent': actions['fire'], 'zoom_intent': actions['zoom'], 'animation_is_firing': bool(anim.bIsFiring), 'weapon_state': weapon_state, 'animation_is_reloading': bool(anim.bIsReloading)}
        handoff = getattr(self, 'sprint_fire_handoff', None)
        if handoff is None:
            handoff = self.sprint_fire_handoff = SprintFireHandoff()
            self.report['sprint_fire_episodes'] = handoff.episodes
        eligible = (bool(self.mod._third_person_enabled) and not bool(pc.bShowMouseCursor)
                    and int(movement.MovementMode) == 1 and int(movement.CustomMovementMode) == 0
                    and not bool(pawn.bIsCrouched) and not bool(self.mod._slide_active)
                    and not any(bool(getattr(self.mod, name, False)) for name in
                                ('_vehicle_camera_active', '_shop_camera_active', '_ladder_active')))
        pending = native_active = False
        supported = True
        # Read native state only when an episode can arm or is already active,
        # and only for the handoff's own weapon in a usable state: a weapon swap,
        # equip or other state ends or blocks the handoff in observe() first.
        candidate = (handoff.phase is not None or (combat['fire_intent']
                     and not handoff.previous_fire and eligible
                     and (handoff.previous_sprint or bool(movement.bIsSprinting))))
        same_weapon = handoff.weapon_ref is None or handoff.weapon_ref() == weapon
        if (candidate and weapon is not None and same_weapon
                and weapon_state in ('Active', 'Using')):
            native = self.sample_fire_activity(pawn, weapon)
            supported = native['supported']
            pending, native_active = native['pending'], native['active']
            self.report['sprint_fire_native'] = native
        combat['sprint_fire_handoff'] = handoff.observe(
            weapon, fire=combat['fire_intent'], firing=combat['animation_is_firing'],
            reloading=combat['animation_is_reloading'], weapon_state=weapon_state,
            sprinting=bool(movement.bIsSprinting),
            wants_sprint=bool(movement.bWantsToSprint), eligible=eligible and supported,
            pending=pending, native_active=native_active)
        combat['sprint_fire_phase'] = handoff.phase
        if handoff.last_release is not None:
            self.report['sprint_fire_not_admitted'] = handoff.not_admitted_releases
            self.report['sprint_fire_no_request'] = handoff.no_request_releases
            logging.warning(TAG + ' SPRINT_FIRE_NOT_ADMITTED reason=' + handoff.last_release
                            + '; body yaw returned to movement')
        # Reflected weapon-state discovery is a lab diagnostic; production skips it.
        if self.collect_pose_diagnostics:
            diagnostic = getattr(self, 'weapon_fire_diagnostic', None)
            if diagnostic is None:
                diagnostic = self.weapon_fire_diagnostic = WeaponFireDiagnostics(self.report)
            diagnostic.sample(weapon, update=self.frames, phase=handoff.phase,
                              fire=combat['fire_intent'], firing=combat['animation_is_firing'])
        combat['throw_hold'] = self.read_throw(pc, anim, combat)
        observe_hybrid_scope(self, pc)
        combat['active'] = any((combat[k] for k in ('ads_active', 'fire_intent', 'zoom_intent', 'animation_is_firing')))
        combat['active'] = combat['active'] or combat['sprint_fire_handoff'] or combat['throw_hold']
        if combat != self.combat:
            self.report['combat_transitions'].append({'t': monotonic() - self.started, **combat})
        self.combat = combat
        if getattr(self, '_callback_scope', False):
            self._callback_combat_read = True

    def _combat_bind_visual(self):
        self._aim_binding_bind_visual()
        self.aim_native.install()
        self.idle_native.install()
        self.idle_update.install()

    def _combat_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        for name in ('samples', 'visual_samples', 'combat_transitions', 'aim_phases'):
            rows = self.report[name]
            if len(rows) >= MAX_SAMPLES:
                del rows[:len(rows) - MAX_SAMPLES + 1]
        try:
            self.read_combat()
            if self.idle_update.hook is not None and self.native_audit_due(3):
                self.idle_update.validate()
            if self.idle_native.hook is not None and self.native_audit_due(2):
                self.idle_native.validate()
            self.idle_native.control[0] = int(self.impulse_index is not None and (not self.combat['active']))
            self.idle_update.control[0] = self.idle_native.control[0]
            if self.aim_native.hook is not None and self.native_audit_due(1):
                self.aim_native.validate()
            if self.impulse_index is not None:
                elapsed = monotonic() - self.started - self.follow_started_t
                phase = 'COMBAT_ORIGINAL_AIM' if self.combat['active'] else 'B_NEUTRAL_YAW'
                self.aim_native.control[0] = int(phase == 'B_NEUTRAL_YAW')
                if phase != self.phase:
                    self.phase = phase
                    self.report['aim_phases'].append({'phase': phase, 'follow_elapsed': elapsed, 'dispatch_calls': int(self.aim_native.control[4]), 'neutralizations': int(self.aim_native.control[3])})
                    logging.warning(TAG + ' ' + phase + ' change WASD directions and camera; automatic restore')
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('AIM_GUARD_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' RESTORE_OR_SAVE_FAILED rerun to retry ' + repr(cleanup))
            return
        self._visual_frame(obj, args, ret, func)

    def _player_bind_visual(self):
        started = monotonic()
        self._combat_bind_visual()
        self.bones = []
        self.report['visual_binding']['selected_bones'] = []
        anim = self.anim_ref()
        catalog = []
        for name, key in self.PLAYERS:
            node = getattr(anim, name)
            if str(node.AnimAssetKey.TagName) != key:
                raise RuntimeError('Focused player binding changed: ' + name)
            for field in self.FIELDS:
                if not math.isfinite(float(getattr(node, field))):
                    raise RuntimeError('Invalid focused player field: ' + name + '.' + field)
            catalog.append({'name': name, 'key': key, 'GroupName': str(node.GroupName), 'GroupRole': int(node.GroupRole), 'Method': int(node.Method), 'SpeedAxis': int(node.SpeedAxis), 'bScalePlayRateWithSpeed': bool(node.bScalePlayRateWithSpeed), 'bUseGaitScaling': bool(node.GaitScalingState.bUseGaitScaling)})
        self.report['player_node_catalog'] = catalog
        self.player_ready = True
        self.report['visual_binding_cost_us'] = round((monotonic() - started) * 1000000.0, 1)

    def _lean_bind_visual(self):
            self._player_bind_visual()
            anim = self.anim_ref()
            expected = {self.BLEND_NODE: ('AnimNode_ApplyMeshSpaceAdditive', self.BLEND_OFFSET), 'GbxAnimGraphNode_BlendSpacePlayer_7': ('GbxAnimNode_BlendSpacePlayer', self.LEAN_OFFSET)}
            found = {}
            for owner in layout_query('owners', self, anim):
                for prop in layout_query('props', self, anim, owner, ('names', tuple(expected))):
                    name = str(prop.Name)
                    if name not in expected:
                        continue
                    if str(prop.Class.Name) != 'StructProperty':
                        raise RuntimeError('Lean binding property type changed')
                    actual = (str(prop.Struct.Name), int(prop.Offset_Internal))
                    if actual != expected[name]:
                        raise RuntimeError('Lean blend layout changed: ' + name)
                    found[name] = actual
                    if name == self.BLEND_NODE:
                        fields = {str(p.Name): int(p.Offset_Internal) for p in prop.Struct._properties()}
                        if fields.get('Additive') != 40 or fields.get('bInvertAlpha') != 216:
                            raise RuntimeError('Reviewed Lean blend field offsets changed')
            if found != expected:
                raise RuntimeError('Reviewed Lean blend bindings unavailable')
            self.blend_layout_ready = True
            self.blend_node()
            self.report['lean_blend_binding'] = {'node': self.BLEND_NODE, 'offset': self.BLEND_OFFSET, 'lean_player_offset': self.LEAN_OFFSET, 'additive_link_pointer_matches': True}

    def blend_node(self, verify_link=True):
        anim = self.anim_ref()
        mesh = self.mesh_ref()
        if anim is None or mesh is None or self.bound()[1].Mesh != mesh or (mesh.AnimScriptInstance != anim):
            raise RuntimeError('Lean blend animation ownership changed')
        if not self.blend_layout_ready:
            raise RuntimeError('Lean blend layout not validated')
        if not verify_link:
            return getattr(anim, self.BLEND_NODE)
        address = int(anim._get_address())
        raw = self.mod._native_read(address + self.BLEND_OFFSET + 40, 8)
        self.report['native_reads'] += 1
        if len(raw) != 8 or struct.unpack('<Q', raw)[0] != address + self.LEAN_OFFSET:
            raise RuntimeError('Live additive pose link no longer points to reviewed Lean player')
        return getattr(anim, self.BLEND_NODE)

    def restore_blend(self):
        if not self.blend_pending:
            return
        anim = self.anim_ref()
        if anim is None:
            self.report['lean_blend_restore'] = 'BOUND_ANIMATION_EXPIRED_NO_WRITE'
            self.blend_pending = False
            return
        node = getattr(anim, self.BLEND_NODE)
        node.bInvertAlpha = self.blend_original
        self.report['game_writes'] += 1
        if bool(node.bInvertAlpha) != self.blend_original:
            raise RuntimeError('Lean blend restoration readback differs; rerun to retry')
        self.report['lean_blend_restoration_verified'] = True
        self.blend_pending = False

    def _lean_live_frame(self, obj, args, ret, func):
        if not self.active or self.busy:
            return
        self._combat_frame(obj, args, ret, func)
        if not self.active:
            return
        try:
            for name in ('lean_blend_observations', 'lean_live_transitions'):
                rows = self.report[name]
                if len(rows) >= self.LIVE_LIMIT:
                    del rows[:len(rows) - self.LIVE_LIMIT + 1]
            node = self.blend_node(verify_link=self.native_audit_due(10))
            if self.blend_original is None:
                self.blend_original = bool(node.bInvertAlpha)
                if not self.blend_original:
                    raise RuntimeError('Expected original inverted Lean bool input')
            suppress = self.impulse_index is not None and (not self.combat['active'])
            phase = 'FREE_BODY_LEAN_SUPPRESSED' if suppress else 'ORIGINAL_LEAN_COMBAT' if self.combat['active'] else 'WAITING_MOVEMENT'
            if suppress:
                if int(node.AlphaInputType) != 1 or bool(node.bAlphaBoolEnabled):
                    self.finish('LEAN_BOOL_INPUT_CHANGED')
                    return
                if not self.blend_pending:
                    if bool(node.bInvertAlpha) != self.blend_original:
                        raise RuntimeError('Lean invert changed before activation')
                    self.blend_pending = True
                    node.bInvertAlpha = False
                    self.report['game_writes'] += 1
                    if bool(node.bInvertAlpha):
                        raise RuntimeError('Lean suppression readback differs')
                elif bool(node.bInvertAlpha):
                    self.finish('LEAN_INVERT_OVERWRITTEN')
                    return
            else:
                self.restore_blend()
            if phase != self.live_phase:
                self.live_phase = phase
                self.report['lean_live_transitions'].append({'phase': phase, 't': monotonic() - self.started})
                logging.warning(TAG + ' ' + phase + ' rerun script to stop and restore')
            if self.frames % 6 == 0:
                self.report['lean_blend_observations'].append({'update_index': self.frames, 't': monotonic() - self.started, 'phase': phase, 'AlphaInputType': int(node.AlphaInputType), 'bAlphaBoolEnabled': bool(node.bAlphaBoolEnabled), 'bInvertAlpha': bool(node.bInvertAlpha), 'ALPHA': float(node.ALPHA), 'BlendInTime': float(node.AlphaBoolBlend.BlendInTime), 'BlendOutTime': float(node.AlphaBoolBlend.BlendOutTime)})
        except Exception as exc:
            self.report['errors'].append(repr(exc)[:500])
            try:
                self.finish('LEAN_LIVE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def clip_anim(self):
        if not self.updates.is_game_thread():
            raise RuntimeError('Clip access outside game thread')
        anim = self.anim_ref()
        pawn = self.bound()[1]
        mesh = pawn.Mesh
        if anim is None or mesh is None or mesh.AnimScriptInstance != anim:
            raise RuntimeError('Clip animation owner expired/changed')
        if self.clip_anim_ref is not None and self.clip_anim_ref() != anim:
            raise RuntimeError('Clip animation identity changed')
        return anim

    def _air_clips_close_air_cycle(self, outcome):
        self.restore_clips()
        self._air_close_air_cycle(outcome)

    def _air_clips_frame(self, obj, args, ret, func):
        self._air_pose_frame(obj, args, ret, func)
        if not self.active:
            return
        try:
            if self.clip_originals:
                anim = self.clip_anim()
                forward = self.clip_forward_ref()
                slots = {name: bool(getattr(anim, name).Sequence == forward) for name, _, _, _ in self.clip_originals}
                if self.report.get('air_clip_live_matches') != slots:
                    self.report['air_clip_live_matches'] = slots
                    self.clip_event('AIR_CLIP_BINDING_OBSERVED', matches=slots)
        except Exception as exc:
            self.report['errors'].append('Air clip live: ' + repr(exc)[:500])
            try:
                self.finish('AIR_CLIP_LIVE_FAILED')
            except Exception as cleanup:
                logging.error(TAG + ' STOP_FAILED rerun to retry ' + repr(cleanup))

    def _clip_lookup_prepare_air_cycle(self, sample, attempt):
        self._air_prepare_air_cycle(sample, attempt)
        self.observe_clip_timing('BEFORE_EARLY_GETTER_SWAP')
        self.swap_forward_clips()
        self.air_cycle['clip_apply_update'] = self.frames
        self.observe_clip_timing('AFTER_EARLY_GETTER_SWAP')

    def close_air_cycle(self, outcome):
        if self.air_cycle is not None:
            self.observe_clip_timing('CYCLE_END_BEFORE_RESTORE')
        self._air_clips_close_air_cycle(outcome)

    def validate_getter(self):
        if self.report.get('getter_schema') is not None:
            return
        path = '/Script/GbxGame.GbxGameAnimInstance:GetAnimationFromTag'
        fn = find_object('Function', path)
        if fn is None:
            raise RuntimeError('Animation getter metadata unavailable')
        props = list(fn._properties())
        if [(str(p.Name), str(p.Class.Name), int(p.Offset_Internal)) for p in props] != [('InKey', 'StructProperty', 0), ('ReturnValue', 'ObjectProperty', 8)]:
            raise RuntimeError('Animation getter signature differs')
        if str(props[0].Struct._path_name()) != '/Script/GameplayTags.GameplayTag' or str(props[1].PropertyClass._path_name()) != '/Script/Engine.AnimSequenceBase':
            raise RuntimeError('Animation getter parameter classes differ')
        self.report['getter_schema'] = dict(path=path, flags=int(fn.FunctionFlags))

    def air_clip_weapon_binding(self, anim):
        weapon = self.bound()[2].CameraModeInputs.Weapon
        state = 'None' if weapon is None else str(weapon.CurrentState)
        if weapon is None or anim.CurrentWeapon != weapon:
            raise RuntimeError('Air clip weapon/animation ownership is not settled')
        if state not in ('Active', 'Reloading') or (state == 'Reloading' and (not bool(anim.bIsReloading))):
            raise RuntimeError('Air clip query unsupported weapon state: ' + state)
        return (weapon, state)

    def swap_forward_clips(self):
        if self.clip_originals:
            raise RuntimeError('Previous clip snapshot still active')
        anim = self.clip_anim()
        forward = getattr(anim, self.DASH_PLAYERS[0][0])
        if str(forward.AnimAssetKey.TagName) != self.DASH_PLAYERS[0][1]:
            raise RuntimeError('Forward binding changed')
        self.validate_getter()
        weapon, weapon_state_before = self.air_clip_weapon_binding(anim)
        self.report['getter_calls'] += 1
        with hitch.step('clips.air.GetAnimationFromTag'):
            asset = anim.GetAnimationFromTag(forward.AnimAssetKey)
        if self.clip_anim() != anim:
            raise RuntimeError('Animation ownership changed during getter')
        after_weapon, weapon_state_after = self.air_clip_weapon_binding(anim)
        if after_weapon != weapon:
            raise RuntimeError('Weapon ownership changed during getter')
        row = dict(cycle=self.air_cycle['sequence'], update_index=self.frames, weapon=describe(weapon), weapon_state_before=weapon_state_before, weapon_state_after=weapon_state_after, key=str(forward.AnimAssetKey.TagName), result=None if asset is None else describe(asset), forward_sequence=None if forward.Sequence is None else describe(forward.Sequence))
        self.report['getter_results'].append(row)
        del self.report['getter_results'][:-128]
        if asset is None or str(asset.Class.Name) != 'AnimSequence':
            raise RuntimeError('Getter returned no valid Forward AnimSequence')
        rows = []
        for name, key in self.DASH_PLAYERS[1:]:
            node = getattr(anim, name)
            original = node.Sequence
            if str(node.AnimAssetKey.TagName) != key:
                raise RuntimeError('Dash binding changed: ' + name)
            if original is not None and str(original.Class.Name) != 'AnimSequence':
                raise RuntimeError('Dash clip class differs')
            rows.append((name, key, None if original is None else WeakPointer(original), None if original is None else str(original._path_name())))
        self.clip_anim_ref = WeakPointer(anim)
        self.clip_forward_ref = WeakPointer(asset)
        self.clip_originals = rows
        self.report['air_clip_restore_verified'] = False
        self.report['air_clip_live_matches'] = None
        for name, key, ref, path in rows:
            node = getattr(anim, name)
            node.Sequence = asset
            self.report['game_writes'] += 1
            if node.Sequence != asset:
                raise RuntimeError('Forward clip readback differs: ' + name)
        self.report['air_clip_cycles_applied'] += 1
        self.clip_event('EARLY_GETTER_FORWARD_CLIPS', forward_path=str(asset._path_name()), cycle=self.air_cycle['sequence'], updates_after_circle=self.frames - self.air_cycle['request_update'])

    def restore_clips(self):
        if not self.clip_originals:
            return
        anim = self.clip_anim()
        forward = self.clip_forward_ref()
        failures = []
        for name, key, ref, path in self.clip_originals:
            try:
                node = getattr(anim, name)
                original = None if ref is None else ref()
                if ref is not None and original is None:
                    raise RuntimeError('Original clip expired: ' + name)
                if str(node.AnimAssetKey.TagName) != key:
                    raise RuntimeError('Clip key changed: ' + name)
                if node.Sequence == original:
                    continue
                if forward is None or node.Sequence != forward:
                    raise RuntimeError('Unexpected native/third-party clip change: ' + name)
                node.Sequence = original
                self.report['game_writes'] += 1
                if node.Sequence != original:
                    raise RuntimeError('Restore readback differs: ' + name)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError('; '.join(failures))
        self.clip_originals = []
        self.clip_forward_ref = None
        self.clip_anim_ref = None
        self.report['air_clip_restore_verified'] = True
        self.report['air_clip_cycles_restored'] += 1
        self.clip_event('ORIGINAL_CLIPS_RESTORED')

    def ground_clip_anim(self):
        if self.ground_clip_anim_ref is None:
            return self.clip_anim()
        if not self.updates.is_game_thread():
            raise RuntimeError('Ground clip access outside game thread')
        anim = self.ground_clip_anim_ref()
        pawn = None if self.ground_clip_pawn_ref is None else self.ground_clip_pawn_ref()
        mesh = None if self.ground_clip_mesh_ref is None else self.ground_clip_mesh_ref()
        if anim is None or pawn is None or mesh is None:
            raise RuntimeError('Stored ground animation owner expired')
        if pawn.Mesh != mesh or mesh.AnimScriptInstance != anim:
            raise RuntimeError('Stored ground mesh/animation ownership changed')
        return anim

    def swap_ground_forward_clips(self):
        if self.ground_clip_originals:
            raise RuntimeError('Previous clip snapshot still active')
        anim = self.ground_clip_anim()
        forward = getattr(anim, self.DASH_PLAYERS[0][0])
        if str(forward.AnimAssetKey.TagName) != self.DASH_PLAYERS[0][1]:
            raise RuntimeError('Forward binding changed')
        self.validate_getter()
        weapon, weapon_state_before = self.air_clip_weapon_binding(anim)
        self.report['getter_calls'] += 1
        with hitch.step('clips.ground.GetAnimationFromTag'):
            asset = anim.GetAnimationFromTag(forward.AnimAssetKey)
        if self.ground_clip_anim() != anim:
            raise RuntimeError('Animation ownership changed during getter')
        after_weapon, weapon_state_after = self.air_clip_weapon_binding(anim)
        if after_weapon != weapon:
            raise RuntimeError('Weapon ownership changed during getter')
        row = dict(cycle=self.ground_b_completed + 1, update_index=self.frames, weapon=describe(weapon), weapon_state_before=weapon_state_before, weapon_state_after=weapon_state_after, key=str(forward.AnimAssetKey.TagName), result=None if asset is None else describe(asset), forward_sequence=None if forward.Sequence is None else describe(forward.Sequence))
        self.report['getter_results'].append(row)
        del self.report['getter_results'][:-128]
        if asset is None or str(asset.Class.Name) != 'AnimSequence':
            raise RuntimeError('Getter returned no valid Forward AnimSequence')
        rows = []
        for name, key in self.DASH_PLAYERS[1:]:
            node = getattr(anim, name)
            original = node.Sequence
            if str(node.AnimAssetKey.TagName) != key:
                raise RuntimeError('Dash binding changed: ' + name)
            if original is not None and str(original.Class.Name) != 'AnimSequence':
                raise RuntimeError('Dash clip class differs')
            rows.append((name, key, None if original is None else WeakPointer(original), None if original is None else str(original._path_name())))
        self.ground_clip_anim_ref = WeakPointer(anim)
        pawn = self.bound()[1]
        self.ground_clip_pawn_ref = WeakPointer(pawn)
        self.ground_clip_mesh_ref = WeakPointer(pawn.Mesh)
        self.ground_clip_forward_ref = WeakPointer(asset)
        self.ground_clip_originals = rows
        self.report['ground_clip_restore_verified'] = False
        self.report['ground_clip_live_matches'] = None
        for name, key, ref, path in rows:
            node = getattr(anim, name)
            node.Sequence = asset
            self.report['game_writes'] += 1
            if node.Sequence != asset:
                raise RuntimeError('Forward clip readback differs: ' + name)
        self.report['ground_clip_cycles_applied'] += 1
        self.ground_clip_event('EARLY_GETTER_FORWARD_CLIPS', forward_path=str(asset._path_name()), cycle=self.ground_b_completed + 1, updates_after_circle=self.frames - self.ground_clip_arm_update)

    def restore_ground_clips(self):
        if not self.ground_clip_originals:
            return
        anim = self.ground_clip_anim()
        forward = self.ground_clip_forward_ref()
        failures = []
        for name, key, ref, path in self.ground_clip_originals:
            try:
                node = getattr(anim, name)
                if str(node.AnimAssetKey.TagName) != key:
                    raise RuntimeError('Clip key changed: ' + name)
                current = node.Sequence
                original = None if ref is None else ref()
                if current == original and (ref is None or original is not None):
                    continue
                if forward is None or current != forward:
                    self.report['ground_clip_native_replacements'].append(dict(update=self.frames, node=name, sequence=None if current is None else describe(current)))
                    del self.report['ground_clip_native_replacements'][:-128]
                    continue
                if ref is not None and original is None:
                    raise RuntimeError('Original owned clip expired: ' + name)
                node.Sequence = original
                self.report['game_writes'] += 1
                if node.Sequence != original:
                    raise RuntimeError('Restore readback differs: ' + name)
            except Exception as exc:
                failures.append(str(exc))
        if failures:
            raise RuntimeError('; '.join(failures))
        self.ground_clip_originals = []
        self.ground_clip_forward_ref = None
        self.ground_clip_anim_ref = None
        self.ground_clip_pawn_ref = None
        self.ground_clip_mesh_ref = None
        self.report['ground_clip_restore_verified'] = True
        self.report['ground_clip_cycles_restored'] += 1
        self.ground_clip_event('ORIGINAL_CLIPS_RESTORED')
