import unittest
from types import SimpleNamespace as S
import support
from BL4ThirdPersonPOC.omni.air import freefall_yaw_step


class FreefallRotationTests(unittest.TestCase):
    def setUp(self):
        self.dashing = False
        self.movement = S(MovementMode=3, CustomMovementMode=0, bWantsToDash=False)
        pawn = S(IsCharacterDashing=lambda: self.dashing)
        self.owner = S(bound=lambda: (None, pawn, None, self.movement), air_cycle=None)

    def test_freefall_rotation_rate_at_different_frame_rates(self):
        for fps in (30,60,144):
            for gap in (-180,-90,0,90,180):
                self.assertAlmostEqual(freefall_yaw_step(self.owner,gap,1/fps),
                                       min(abs(gap),540/fps))

    def test_prepared_but_unrequested_dash_still_allows_smoothing(self):
        self.owner.air_cycle = {'prearmed':True}
        self.assertEqual(freefall_yaw_step(self.owner,90,1/60),9)

    def test_dash_requests_and_active_dash_preserve_original_step(self):
        for cycle in ({'prearmed':False},{'prearmed':True,'seen_dash':True},
                      {'prearmed':True,'vector_applied':True},
                      {'prearmed':True,'press_observed_update':1}):
            self.owner.air_cycle=cycle
            self.assertEqual(freefall_yaw_step(self.owner,90,1/60),90)
        self.owner.air_cycle=None
        self.dashing=True
        self.assertEqual(freefall_yaw_step(self.owner,90,1/60),90)
        self.dashing=False;self.movement.bWantsToDash=True
        self.assertEqual(freefall_yaw_step(self.owner,90,1/60),90)

    def test_ground_and_special_mode_preserve_original_step(self):
        self.movement.MovementMode=1
        self.assertEqual(freefall_yaw_step(self.owner,90,1/60),90)
        self.movement.MovementMode=3;self.movement.CustomMovementMode=1
        self.assertEqual(freefall_yaw_step(self.owner,90,1/60),90)

    def test_long_update_and_near_target_do_not_overshoot(self):
        self.assertEqual(freefall_yaw_step(self.owner,90,1),27)
        self.assertEqual(freefall_yaw_step(self.owner,2,1/60),2)
