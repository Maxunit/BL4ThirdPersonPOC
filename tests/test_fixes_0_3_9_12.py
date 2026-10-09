"""0.3.9.12: Sprint-fire handoff hardening (B1 read failures, B2 no native request)."""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
from BL4ThirdPersonPOC.omni import animation
from BL4ThirdPersonPOC.omni.animation import AnimationMixin
from BL4ThirdPersonPOC.omni.combat_handoff import NO_REQUEST_SAMPLES, SprintFireHandoff


class Montage:
    """Identity-hashable UAnimMontage stand-in."""

    def __init__(self, name):
        self.Name = name


def step(handoff, weapon, **kw):
    args = dict(fire=False, firing=False, reloading=False, weapon_state='Active',
                sprinting=False, wants_sprint=True, eligible=True,
                pending=False, native_active=False, now=100.0)
    args.update(kw)
    return handoff.observe(weapon, **args)


class NoNativeRequestTests(unittest.TestCase):
    def arm(self, pending=False):
        handoff, weapon = SprintFireHandoff(), object()
        step(handoff, weapon, sprinting=True)
        self.assertTrue(step(handoff, weapon, fire=True, pending=pending))
        return handoff, weapon

    def test_press_without_request_releases_after_one_quiet_sample(self):
        self.assertEqual(NO_REQUEST_SAMPLES, 2)
        handoff, weapon = self.arm()
        self.assertTrue(step(handoff, weapon))           # release sample
        self.assertFalse(step(handoff, weapon))          # one grace sample later
        self.assertEqual(handoff.episodes[-1]['end_reason'], 'NO_NATIVE_REQUEST')
        self.assertEqual(handoff.last_release, 'NO_NATIVE_REQUEST')
        self.assertEqual(handoff.no_request_releases, 1)
        self.assertEqual(handoff.not_admitted_releases, 0)

    def test_light_trigger_held_keeps_the_handoff_while_held(self):
        handoff, weapon = self.arm()
        for _ in range(500):
            self.assertTrue(step(handoff, weapon, fire=True))
        self.assertTrue(step(handoff, weapon))
        self.assertFalse(step(handoff, weapon))

    def test_request_seen_late_keeps_the_native_closure_path(self):
        handoff, weapon = self.arm()
        self.assertTrue(step(handoff, weapon, pending=True))   # visible on the release sample
        for _ in range(20):
            self.assertTrue(step(handoff, weapon, pending=True))
        self.assertTrue(step(handoff, weapon, native_active=True, weapon_state='Using'))
        self.assertFalse(step(handoff, weapon))
        self.assertEqual(handoff.episodes[-1]['end_reason'], 'NATIVE_USE_COMPLETED')

    def test_quiet_count_restarts_when_input_returns(self):
        handoff, weapon = self.arm()
        self.assertTrue(step(handoff, weapon))
        self.assertTrue(step(handoff, weapon, fire=True))
        self.assertTrue(step(handoff, weapon))
        self.assertFalse(step(handoff, weapon))

    def test_valid_requests_never_take_the_no_request_exit(self):
        handoff, weapon = self.arm(pending=True)
        for _ in range(50):
            self.assertTrue(step(handoff, weapon, pending=True))
        self.assertFalse(step(handoff, weapon))
        self.assertEqual(handoff.episodes[-1]['end_reason'], 'NATIVE_REQUEST_CLOSED_WITHOUT_USE')
        self.assertEqual(handoff.no_request_releases, 0)


class CombatHarness:
    """AnimationMixin.read_combat with SDK-shaped stand-ins (not a TestCase)."""

    def build(self):
        self.weapon = S(CurrentState='Active')
        self.other = S(CurrentState='Active', Name='Other')  # distinct object
        self.anim = S(bIsFiring=False, bIsReloading=False)
        self.mesh = S(AnimScriptInstance=self.anim)
        self.pawn = S(Mesh=self.mesh, bIsCrouched=False)
        self.camera = S(CameraModeInputs=S(Weapon=self.weapon))
        self.movement = S(MovementMode=1, CustomMovementMode=0, bIsSprinting=True, bWantsToSprint=True)
        self.pc = S(bShowMouseCursor=False)
        self.keys = dict(fire=False, zoom=False)
        self.samples = []
        self.fail = None
        mod = S(_ads_active=False, _third_person_enabled=True, _slide_active=False)
        self.obj = S(updates=S(is_game_thread=lambda: True),
                     bound=lambda: (self.pc, self.pawn, self.camera, self.movement),
                     combat_refs=(lambda: self.mesh, lambda: self.anim, lambda: self.weapon),
                     mod=mod, inputs=S(snapshot=lambda pc: dict(self.keys)),
                     sprint_fire_activity=S(sample=self.sample),
                     collect_pose_diagnostics=False, combat={}, frames=0, started=0.0,
                     report=dict(combat_transitions=[]))
        self.obj.sample_fire_activity = lambda pawn, weapon: AnimationMixin.sample_fire_activity(
            self.obj, pawn, weapon)
        self.obj.read_throw = lambda pc, anim, combat: AnimationMixin.read_throw(
            self.obj, pc, anim, combat)
        support.LOG.clear()

    def sample(self, pawn, weapon):
        self.samples.append(weapon)
        if self.fail is not None:
            raise self.fail
        return dict(supported=True, pending=True, active=False)

    def read(self):
        AnimationMixin.read_combat(self.obj)
        return self.obj.combat

    def press(self):
        self.read()
        self.keys['fire'] = True
        return self.read()


class ReadFailureTests(CombatHarness, unittest.TestCase):
    """read_combat must degrade the handoff, never raise into the omni session."""

    def setUp(self):
        self.build()

    def test_structure_error_disables_only_the_handoff(self):
        self.fail = RuntimeError('Sprint-fire weapon must match exactly one user entry')
        for _ in range(3):
            combat = self.press()
            self.keys['fire'] = False
            self.read()
        self.assertFalse(combat['sprint_fire_handoff'])
        self.assertTrue(combat['active'])  # Fire itself is still combat intent.
        failures = self.obj.report['sprint_fire_read_failures']
        self.assertEqual(list(failures.values()), [3])
        warnings = [m for _, m in support.LOG if 'SPRINT_FIRE_NATIVE_UNAVAILABLE' in m]
        self.assertEqual(len(warnings), 1)

    def test_changed_native_code_is_not_retried(self):
        del self.obj.sprint_fire_activity
        calls = []

        def refuse(mod):
            calls.append(mod)
            raise RuntimeError('Sprint-fire measured code differs at 0x107a06e')

        with patch.object(animation, 'NativeFireActivity', refuse):
            for _ in range(4):
                self.press()
                self.keys['fire'] = False
                self.read()
        self.assertEqual(len(calls), 1)
        self.assertIs(self.obj.sprint_fire_activity, False)
        self.assertEqual(sum(self.obj.report['sprint_fire_read_failures'].values()), 4)

    def test_weapon_swap_during_handoff_is_not_sampled(self):
        self.assertTrue(self.press()['sprint_fire_handoff'])
        before = len(self.samples)
        self.camera.CameraModeInputs.Weapon = self.other
        combat = self.read()
        self.assertEqual(len(self.samples), before)
        self.assertFalse(combat['sprint_fire_handoff'])
        self.assertEqual(self.obj.report['sprint_fire_episodes'][-1]['end_reason'], 'WEAPON_CHANGED')

    def test_unusable_weapon_state_is_not_sampled(self):
        self.weapon.CurrentState = 'Equipping'
        combat = self.press()
        self.assertEqual(self.samples, [])
        self.assertFalse(combat['sprint_fire_handoff'])

    def test_unexpected_exception_types_still_surface(self):
        self.fail = KeyError('defect')
        with self.assertRaises(KeyError):
            self.press()



class ThrowHandoffTests(unittest.TestCase):
    """Throw episodes hold combat through the montage that starts with them."""

    def setUp(self):
        from BL4ThirdPersonPOC.omni.throw_handoff import ThrowHandoff
        self.throw = ThrowHandoff()
        self.playing = set()
        self.fresh = set()

    def step(self, intent=False, current=None, eligible=True):
        return self.throw.observe(intent=intent, source='gadget', eligible=eligible,
                                  current=current, is_playing=lambda m: m in self.playing,
                                  is_fresh=lambda m: m in self.fresh, now=1.0)

    def test_tap_throw_holds_until_its_montage_ends(self):
        montage = Montage('AM_Throw_Grenade')
        self.assertTrue(self.step(intent=True))
        self.playing.add(montage)
        self.assertTrue(self.step(intent=False, current=montage))
        self.assertEqual(self.throw.last_event, 'MONTAGE')
        for _ in range(40):
            self.assertTrue(self.step(current=montage))
        self.playing.clear()
        self.assertFalse(self.step())
        self.assertEqual(self.throw.episodes[-1]['end_reason'], 'MONTAGE_ENDED')
        self.assertEqual(self.throw.episodes[-1]['montage'], 'AM_Throw_Grenade')

    def test_intent_without_montage_ends_one_sample_after_release(self):
        self.assertTrue(self.step(intent=True))
        self.assertTrue(self.step(intent=True))
        self.assertTrue(self.step())
        self.assertFalse(self.step())
        self.assertEqual(self.throw.episodes[-1]['end_reason'], 'NO_MONTAGE')

    def test_montage_already_playing_at_press_is_not_the_throw(self):
        reload = Montage('AM_Reload')
        self.playing.add(reload)
        self.assertTrue(self.step(intent=True, current=reload))
        self.assertTrue(self.step(current=reload))
        self.assertFalse(self.step(current=reload))
        self.assertEqual(self.throw.episodes[-1]['end_reason'], 'NO_MONTAGE')

    def test_montage_started_by_the_press_itself_is_the_throw(self):
        montage = Montage('AM_Throw_Grenade')
        self.playing.add(montage)
        self.fresh.add(montage)
        self.assertTrue(self.step(intent=True, current=montage))
        self.assertEqual(self.throw.last_event, 'MONTAGE')
        self.fresh.clear()
        self.assertTrue(self.step(current=montage))
        self.playing.clear()
        self.assertFalse(self.step())
        self.assertEqual(self.throw.episodes[-1]['end_reason'], 'MONTAGE_ENDED')

    def test_only_one_fresh_successor_is_followed(self):
        parts = [Montage('AM_Throw_%d' % i) for i in range(4)]
        self.step(intent=True)
        self.playing.add(parts[0])
        self.step(current=parts[0])
        held = []
        for part in parts[1:]:
            self.playing.clear()
            self.playing.add(part)
            self.fresh = {part}
            held.append(self.step(current=part))
        self.assertEqual(held, [True, False, False])
        self.assertEqual(self.throw.episodes[-1]['chained'], ['AM_Throw_1'])

    def test_running_unrelated_montage_does_not_extend_the_hold(self):
        throw, reload = Montage('AM_Throw'), Montage('AM_Reload')
        self.step(intent=True)
        self.playing.add(throw)
        self.step(current=throw)
        self.playing = {reload}
        self.assertFalse(self.step(current=reload))  # not fresh: no chain

    def test_ineligible_ends_the_episode(self):
        self.step(intent=True)
        self.assertFalse(self.step(intent=True, eligible=False))
        self.assertEqual(self.throw.episodes[-1]['end_reason'], 'INELIGIBLE')
        self.assertFalse(self.step(intent=True))  # held key is no new press

    def test_held_key_after_the_montage_keeps_combat(self):
        montage = Montage('AM_Throw')
        self.step(intent=True)
        self.playing.add(montage)
        self.step(intent=True, current=montage)
        self.playing.clear()
        self.assertTrue(self.step(intent=True))
        self.assertFalse(self.step())


class ThrowReadCombatTests(CombatHarness, unittest.TestCase):
    """Existing ordnance montage wiring; carry action has a separate handoff."""

    def setUp(self):
        self.build()
        self.keys['gadget'] = False
        self.current = None
        self.playing = set()
        self.positions = {}
        self.anim.GetCurrentActiveMontage = lambda: self.current
        self.anim.Montage_IsPlaying = lambda m: m in self.playing
        self.anim.Montage_GetPosition = lambda m: self.positions.get(m, 1.0)
        self.movement.bIsSprinting = False
        self.movement.bWantsToSprint = False

    def throw_montage(self):
        self.current = Montage('AM_Throw_Grenade')
        self.playing.add(self.current)

    def test_ordnance_tap_keeps_combat_through_the_montage(self):
        self.assertFalse(self.read()['active'])
        self.keys['gadget'] = True
        self.assertTrue(self.read()['active'])
        self.keys['gadget'] = False
        self.throw_montage()
        combat = self.read()
        self.assertTrue(combat['active'] and combat['throw_hold'])
        self.assertTrue(any('THROW_HOLD source=gadget montage=AM_Throw_Grenade' in m for _, m in support.LOG))
        self.playing.clear()
        self.assertFalse(self.read()['active'])
        self.assertEqual(self.obj.report['throw_episodes'][-1]['end_reason'], 'MONTAGE_ENDED')

    def test_montage_already_started_on_the_press_frame_is_tracked(self):
        self.throw_montage()
        self.positions[self.current] = 0.016
        self.keys['gadget'] = True
        self.assertTrue(self.read()['throw_hold'])
        self.keys['gadget'] = False
        self.positions[self.current] = 0.4
        self.assertTrue(self.read()['throw_hold'])
        self.playing.clear()
        self.assertFalse(self.read()['throw_hold'])
        self.assertEqual(self.obj.report['throw_episodes'][-1]['end_reason'], 'MONTAGE_ENDED')

    def test_fire_without_zoom_is_not_evidence_of_a_carry_throw(self):
        self.obj.inputs.present_roles = frozenset({'fire', 'sprint', 'dash', 'crouch', 'jump', 'zoom'})
        self.keys['fire'] = True
        self.assertFalse(self.read()['throw_intent'])
        self.keys['fire'] = False
        self.read()
        self.obj.inputs.present_roles = frozenset({'fire', 'sprint', 'dash', 'crouch', 'jump'})
        self.keys['fire'] = True
        combat = self.read()
        self.assertTrue(combat['throwable_context'])
        self.assertFalse(combat['throw_intent'])
        self.keys['fire'] = False
        self.throw_montage()
        self.assertFalse(self.read()['throw_hold'])
        self.assertEqual(self.obj.report['throw_episode_count'], 0)

    def test_missing_montage_functions_never_stop_omni(self):
        del self.anim.GetCurrentActiveMontage
        self.keys['gadget'] = True
        self.assertTrue(self.read()['active'])
        self.keys['gadget'] = False
        self.read()
        self.assertFalse(self.read()['active'])
        self.assertIn('AttributeError', self.obj.report['throw_montage_error'])
        warnings = [m for _, m in support.LOG if 'THROW_MONTAGE_UNAVAILABLE' in m]
        self.assertEqual(len(warnings), 1)

    def test_throw_is_ignored_in_menus_and_vehicles(self):
        self.pc.bShowMouseCursor = True
        self.keys['gadget'] = True
        self.assertFalse(self.read()['throw_hold'])


class GadgetBindingTests(unittest.TestCase):
    """Action_Gadget is an optional role; its complex mappings are skipped, not fatal."""

    def reader(self, *extra):
        from BL4ThirdPersonPOC.input_bindings import NativeBindings
        pc = support.controller()
        pc.PlayerInput.EnhancedActionMappings.extend(extra)
        reader = NativeBindings(pc)
        reader.refresh(require_complete=True)
        return pc, reader

    def test_gadget_key_is_throw_intent(self):
        pc, reader = self.reader(support.mapping('Action_Gadget', 'G'))
        self.assertIn('gadget', reader.present_roles)
        self.assertFalse(reader.snapshot(pc)['gadget'])
        pc.pressed.add('G')
        self.assertTrue(reader.snapshot(pc)['gadget'])

    def test_missing_gadget_mapping_is_not_incomplete(self):
        pc, reader = self.reader()
        self.assertTrue(reader.complete)
        self.assertNotIn('gadget', reader.present_roles)
        self.assertFalse(reader.snapshot(pc)['gadget'])

    def test_chord_gadget_mapping_is_skipped(self):
        chord = S(Class=S(Name='InputTriggerChordAction'))
        pc, reader = self.reader(support.mapping('Action_Gadget', 'G', triggers=(chord,)),
                                 support.mapping('Action_Gadget', 'Gamepad_RightShoulder'))
        self.assertEqual(reader.skipped_optional, 1)
        self.assertEqual([str(k.KeyName) for k in reader.bindings['gadget']], ['Gamepad_RightShoulder'])
        self.assertEqual(reader.metadata()['skipped_optional_mappings'], 1)

    def test_unusable_gadget_rows_are_skipped(self):
        foreign = support.mapping('Action_Gadget', 'G')
        foreign.Action.Class = S(_path_name=lambda: '/Script/Other.InputAction')
        unbound = support.mapping('Action_Gadget', 'None')
        pc, reader = self.reader(foreign, unbound)
        self.assertEqual(reader.skipped_optional, 2)
        self.assertEqual(reader.bindings['gadget'], [])

    def test_chord_on_movement_stays_fail_closed(self):
        from BL4ThirdPersonPOC.input_bindings import NativeBindings
        pc = support.controller()
        chord = S(Class=S(Name='InputTriggerChordAction'))
        pc.PlayerInput.EnhancedActionMappings.append(
            support.mapping('Action_Sprint', 'X', triggers=(chord,)))
        with self.assertRaisesRegex(RuntimeError, 'Complex configured action trigger'):
            NativeBindings(pc).refresh(require_complete=True)

    def test_zoom_absence_marks_the_throwable_context(self):
        pc, reader = self.reader()
        self.assertIn('zoom', reader.present_roles)
        pc.PlayerInput.EnhancedActionMappings[:] = [
            row for row in pc.PlayerInput.EnhancedActionMappings
            if 'Action_Zoom' not in str(row.Action._path_name())]
        reader.maybe_refresh(require_complete=True)
        self.assertNotIn('zoom', reader.present_roles)


if __name__ == '__main__':
    unittest.main()
