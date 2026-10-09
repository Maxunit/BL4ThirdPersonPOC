import unittest
import support
from BL4ThirdPersonPOC.omni.combat_handoff import SprintFireHandoff


class SprintFireTests(unittest.TestCase):
    def setUp(self):
        self.h = SprintFireHandoff()
        self.weapon = object()

    def step(self, **changes):
        args = dict(fire=False, firing=False, reloading=False,
                    weapon_state='Active', sprinting=False,
                    wants_sprint=True, eligible=True, native_active=False,
                    pending=self.h.phase == 'WAIT_NATIVE_FIRE')
        args.update(changes)
        return self.h.observe(self.weapon, **args)

    def arm(self):
        self.assertFalse(self.step(sprinting=True))
        self.assertTrue(self.step(fire=True))

    def test_delayed_sprint_shot_keeps_aim_until_native_completion(self):
        self.arm()
        for _ in range(4):
            self.assertTrue(self.step())
        self.assertTrue(self.step(weapon_state='Using'))
        self.assertEqual(self.h.phase, 'NATIVE_FIRE_SEEN')
        self.assertTrue(self.step(firing=True, weapon_state='Using'))
        self.assertEqual(self.h.phase, 'NATIVE_FIRE_SEEN')
        self.assertTrue(self.step(weapon_state='Using'))
        self.assertFalse(self.step())

    def test_walk_shot_does_not_arm(self):
        self.assertFalse(self.step(fire=True))
        self.assertFalse(self.step(weapon_state='Using', firing=True))
        self.assertIsNone(self.h.phase)

    def test_native_sprint_resume_cancels_unexecuted_shot(self):
        self.arm()
        self.assertFalse(self.step(sprinting=True))

    def test_native_sprint_wish_clear_does_not_cancel_queued_fire(self):
        self.arm()
        for _ in range(6):
            self.assertTrue(self.step(wants_sprint=False))
        self.assertTrue(self.step(wants_sprint=False, weapon_state='Using'))
        self.assertTrue(self.step(wants_sprint=False, firing=True, weapon_state='Using'))
        self.assertFalse(self.step(wants_sprint=False))

    def test_reload_special_state_and_weapon_state_cancel(self):
        for args in ({'reloading': True}, {'eligible': False},
                     {'weapon_state': 'Unequipping'}):
            with self.subTest(args=args):
                self.setUp()
                self.arm()
                self.assertFalse(self.step(**args))

    def test_weapon_change_and_expiration_cancel(self):
        self.arm()
        self.weapon = object()
        self.assertFalse(self.step())
        self.setUp()
        self.arm()
        self.h.weapon_ref = lambda: None
        self.assertFalse(self.step())

    def test_repeated_observations_do_not_rearm_held_fire(self):
        self.arm()
        self.assertTrue(self.step(fire=True, firing=True, weapon_state='Using'))
        self.assertFalse(self.step(fire=True))
        self.assertFalse(self.step(fire=True, sprinting=True))


if __name__ == '__main__':
    unittest.main()
