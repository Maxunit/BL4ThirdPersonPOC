import json
from pathlib import Path
from types import SimpleNamespace as S
import unittest
import support
from BL4ThirdPersonPOC.omni.combat_handoff import SprintFireHandoff


class NativeSprintTests(unittest.TestCase):
    def step(self, h, weapon, **kw):
        args = dict(fire=False, firing=False, reloading=False, weapon_state='Active',
                    sprinting=False, wants_sprint=True, eligible=True,
                    pending=False, native_active=False, now=100.)
        args.update(kw)
        return h.observe(weapon, **args)

    def test_released_pending_request_cannot_expire_with_time(self):
        h, weapon = SprintFireHandoff(), object()
        self.step(h, weapon, sprinting=True)
        self.assertTrue(self.step(h, weapon, fire=True, pending=True))
        self.assertTrue(self.step(h, weapon, pending=True, now=1e9))
        self.assertTrue(self.step(h, weapon, native_active=True, weapon_state='Using'))
        self.assertFalse(self.step(h, weapon))
        self.assertEqual(h.episodes[-1]['end_reason'], 'NATIVE_USE_COMPLETED')

    def test_empty_request_requires_native_closure_and_input_release(self):
        h, weapon = SprintFireHandoff(), object()
        self.step(h, weapon, sprinting=True)
        self.step(h, weapon, fire=True, pending=True)
        self.assertTrue(self.step(h, weapon, fire=True))
        self.assertFalse(self.step(h, weapon))
        self.assertEqual(h.not_admitted_releases, 1)

    def test_charge_activity_holds_without_firing_animation(self):
        h, weapon = SprintFireHandoff(), object()
        self.step(h, weapon, sprinting=True)
        self.step(h, weapon, fire=True, pending=True)
        self.assertTrue(self.step(h, weapon, native_active=True))
        self.assertTrue(self.step(h, weapon, native_active=True, now=1e9))
        self.assertFalse(self.step(h, weapon))

    def test_recorded_regular_charge_and_charge_abort_decisions(self):
        records = json.loads(Path(__file__).with_name('sprint_fire_recorded.json').read_text())
        for record in records:
            for scale in (0.000001, 100):
                h, weapon = SprintFireHandoff(), object()
                for row in record['samples']:
                    self.step(h, weapon, fire=row['fire_intent'], firing=row['firing'],
                              reloading=row['reloading'], weapon_state=row['weapon_state'],
                              sprinting=row['sprinting'], wants_sprint=row['wants_sprint'],
                              pending=row['native_pending'], native_active=row['native_active'],
                              now=row['update'] * scale)
                    self.assertEqual(h.phase, row['qa_phase'], (record['name'], row['update']))
                self.assertEqual(len(h.episodes), record['expected_episodes'])
                self.assertTrue(all(not e['timer_based_release'] for e in h.episodes))


if __name__ == '__main__':
    unittest.main()
