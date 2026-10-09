"""Regression: empty Sprint request closes by native state, never a deadline."""
import unittest
from types import SimpleNamespace as S
import support
from BL4ThirdPersonPOC.omni import combat_handoff

class ReadCombatWiringTests(unittest.TestCase):
    """AnimationMixin.read_combat with SDK-shaped stand-ins."""

    def setUp(self):
        from BL4ThirdPersonPOC.omni.animation import AnimationMixin
        self.mixin = AnimationMixin
        self.weapon = S(CurrentState='Active', PostSprintUseDelay=0.2)
        self.anim = S(bIsFiring=False, bIsReloading=False)
        self.mesh = S(AnimScriptInstance=self.anim)
        self.pawn = S(Mesh=self.mesh, bIsCrouched=False)
        self.camera = S(CameraModeInputs=S(Weapon=self.weapon))
        self.movement = S(MovementMode=1, CustomMovementMode=0, bIsSprinting=True, bWantsToSprint=True)
        self.pc = S(bShowMouseCursor=False)
        self.pending = True
        self.keys = dict(fire=False, zoom=False)
        mod = S(_ads_active=False, _third_person_enabled=True, _slide_active=False)
        self.obj = S(updates=S(is_game_thread=lambda: True),
                     bound=lambda: (self.pc, self.pawn, self.camera, self.movement),
                     combat_refs=(lambda: self.mesh, lambda: self.anim, lambda: self.weapon),
                     mod=mod, inputs=S(snapshot=lambda pc: dict(self.keys)),
                     sprint_fire_activity=S(sample=lambda pawn, weapon: dict(supported=True, pending=self.pending, active=False)),
                     collect_pose_diagnostics=False, combat={}, frames=0, started=0.0,
                     report=dict(combat_transitions=[]))
        self.obj.sample_fire_activity = lambda pawn, weapon: AnimationMixin.sample_fire_activity(
            self.obj, pawn, weapon)
        self.obj.read_throw = lambda pc, anim, combat: AnimationMixin.read_throw(
            self.obj, pc, anim, combat)

    def read(self):
        self.mixin.read_combat(self.obj)
        return self.obj.combat

    def test_rejected_sprint_shot_releases_combat_and_reports_it(self):
        clock = [10.0]
        original = combat_handoff.monotonic
        combat_handoff.monotonic = lambda: clock[0]
        support.LOG.clear()
        try:
            self.read()
            self.keys['fire'] = True
            self.assertTrue(self.read()['sprint_fire_handoff'])
            self.keys['fire'] = False
            self.movement.bIsSprinting = False
            self.movement.bWantsToSprint = False
            clock[0] += 0.1
            self.assertTrue(self.read()['active'])
            self.pending = False
            clock[0] += 0.5
            combat = self.read()
        finally:
            combat_handoff.monotonic = original
        self.assertFalse(combat['active'])
        self.assertIsNone(combat['sprint_fire_phase'])
        report = self.obj.report
        self.assertEqual(report['sprint_fire_not_admitted'], 1)
        self.assertEqual(report['sprint_fire_episodes'][-1]['end_reason'], 'NATIVE_REQUEST_CLOSED_WITHOUT_USE')
        self.assertFalse(report['sprint_fire_episodes'][-1]['timer_based_release'])
        self.assertTrue(any('SPRINT_FIRE_NOT_ADMITTED' in m for _, m in support.LOG))


