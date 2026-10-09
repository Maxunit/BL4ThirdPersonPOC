"""Exercise publication before native input, without executing native detours."""
import math
import struct
import unittest
from types import SimpleNamespace as S
import support  # Install SDK stubs before importing the package.
from BL4ThirdPersonPOC.omni.air import AirMixin


def sample(yaw=45.0):
    return dict(movement_mode=3, movement_input_active=True, input_yaw=yaw,
                control_rotation={'Yaw': 0.0}, actor_rotation={'Yaw': yaw},
                last_movement_input={'X': math.cos(math.radians(yaw)),
                                     'Y': math.sin(math.radians(yaw))},
                action_intent=dict(dash=False, crouch=False, fire=False, zoom=False),
                t=1.0, horizontal_speed=700.0, mouse_cursor=False, custom_movement_mode=0, velocity_yaw=0.0)


class Harness(AirMixin):
    def __init__(self):
        self.active = True
        self.vector_ready = True
        self.route_ready = True
        self.frames = 1
        self.movement_address = 100000
        self.handler_address = 200000
        self.cfg = 300000
        self.combat = {'active': False}
        self.air_cycle = None
        self.air_cycle_sequence = 0
        self.air_circle_press_count = 0
        self.clip_originals = []
        self.weapon = S(CurrentState='Active')
        self.anim = S(CurrentWeapon=self.weapon)
        self.dashing = False
        self.movement = S(bWantsToDash=False)
        self.pawn = S(IsCharacterDashing=lambda: self.dashing)
        self.camera = S(CameraModeInputs=S(Weapon=self.weapon))
        self.vector_trace = S(control=[0] * 64, base=400000, read=self.read, validate_input_sources=lambda: None)
        self.report = dict(samples=[sample()], air_live_targets=[],
                           air_dash_attempts=[], air_live_events=[])
        self.outcomes = []
        self.input_edge = False

    def bound(self):
        return None, self.pawn, self.camera, self.movement

    def clip_anim(self):
        return self.anim

    def validate_handler(self):
        pass

    def read(self, address, size):
        if address == self.handler_address + 72:
            return bytes([0, 1])
        if address == self.movement_address + 17456:
            return struct.pack('<Q', self.cfg)
        if address == self.cfg + 144:
            return struct.pack('<4f', 0, -90, 180, 90)
        if address == self.vector_trace.base + 163877400:
            return struct.pack('<d', math.pi / 180)
        raise AssertionError((address, size))

    def prepare_air_cycle(self, row, attempt):
        self._air_prepare_air_cycle(row, attempt)

    def close_air_cycle(self, outcome):
        self.outcomes.append((outcome, dict(self.air_cycle)))
        self.vector_trace.control[12] = 0
        self.air_cycle = None

    def air_live_event(self, event, **kwargs):
        self.report['air_live_events'].append(event)

    def air_frame_observe(self, *args):
        # Model native processing between UI update callbacks.
        if self.input_edge:
            self.air_circle_press_count += 1
            self.report['air_dash_attempts'].append({})
        self.vector_trace.control[12] = 0

    def trim_diagnostics(self):
        pass


class AirPreparationTests(unittest.TestCase):
    def test_four_diagonals_publish_all_native_enum_compensations(self):
        for yaw in (-135, -45, 45, 135):
            h = Harness()
            h.prearm_air_input(sample(yaw))
            self.assertTrue(h.air_cycle['prearmed'])
            target = h.air_cycle['desired_vector']
            row = h.report['air_live_targets'][-1]
            for angle, pre in zip(row['native_angles'], row['actual_direction_compensation_table']):
                a = math.radians(angle)
                actual = (math.cos(a) * pre[0] - math.sin(a) * pre[1],
                          math.sin(a) * pre[0] + math.cos(a) * pre[1])
                for got, expected in zip(actual, target):
                    self.assertAlmostEqual(got, expected)

    def test_cardinals_unaligned_body_and_no_input_can_prearm(self):
        for yaw in (0, 90, 180, -90):
            h = Harness()
            row = sample(yaw)
            row['actor_rotation']['Yaw'] = 20
            h.prearm_air_input(row)
            self.assertTrue(h.air_cycle['prearmed'])
        h = Harness()
        row = sample()
        row['movement_input_active'] = False
        row['input_yaw'] = None
        h.prearm_air_input(row)
        self.assertTrue(h.air_cycle['prearmed'])
        h = Harness()
        h.combat['active'] = True
        h.prearm_air_input(sample())
        self.assertIsNone(h.air_cycle)

    def test_already_started_native_dash_adopts_prepared_one_shot(self):
        h = Harness()
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertEqual(h.vector_trace.control[12], 4)
        self.assertEqual(h.vector_trace.control[7], 1)
        sequence = h.air_cycle['sequence']
        h.frames += 1
        h.input_edge = True
        h.dashing = True
        h.vector_trace.control[8] = 1
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertEqual(h.air_cycle['sequence'], sequence)
        self.assertTrue(h.air_cycle['vector_applied'])
        self.assertTrue(h.air_cycle['seen_dash'])
        self.assertEqual(h.vector_trace.control[12], 0)
        self.assertNotIn('AIR_PRESS_DURING_NATIVE_DASH', h.report['air_live_events'])
        h.input_edge = False
        h.dashing = False
        h.frames += 1
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertEqual(h.outcomes[0][0], 'NATIVE_AIR_DASH_ENDED')

    def test_no_press_does_not_expire_and_refresh_keeps_single_snapshot(self):
        h = Harness()
        h.air_frame(None, None, None, None, 'AIRBORNE')
        sequence = h.air_cycle['sequence']
        h.frames = 100
        h.report['samples'][-1] = sample(47)
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertEqual(h.air_cycle['sequence'], sequence)
        self.assertEqual(len(h.report['air_live_targets']), 1)
        self.assertEqual(h.air_cycle['captured_body_yaw'], 45)

    def test_native_dash_without_override_is_not_reported_as_corrected(self):
        h = Harness()
        h.air_frame(None, None, None, None, 'AIRBORNE')
        h.dashing = True
        h.frames += 1
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertIsNone(h.air_cycle)
        self.assertEqual(h.vector_trace.control[12], 0)
        self.assertEqual(h.outcomes[0][0], 'AIR_NATIVE_INPUT_NOT_CAPTURED')

    def test_weapon_change_withdraws_and_direction_change_keeps_native_latch_ready(self):
        h = Harness()
        h.air_frame(None, None, None, None, 'AIRBORNE')
        h.report['samples'][-1] = sample(90)
        h.frames += 1
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertIsNotNone(h.air_cycle)
        self.assertEqual(h.vector_trace.control[12], 4)
        h.weapon = S(CurrentState='Reloading')
        h.anim.CurrentWeapon = h.weapon
        h.camera.CameraModeInputs.Weapon = h.weapon
        h.air_frame(None, None, None, None, 'AIRBORNE')
        self.assertIsNone(h.air_cycle)
        self.assertEqual(h.outcomes[0][0], 'AIR_INPUT_PREPARATION_WITHDRAWN')

    def test_facing_uses_input_not_momentum_and_admitted_direction_is_locked(self):
        h = Harness()
        row = sample(135)
        row['velocity_yaw'] = 0.0
        self.assertEqual(h.air_facing_target(row), 135)
        h.air_hold_yaw = 23
        row['movement_input_active'] = False
        self.assertEqual(h.air_facing_target(row), 23)
        h.air_cycle = dict(desired_vector=[0, -1, 0])
        h.vector_trace.control[8] = 1
        self.assertEqual(h.air_facing_target(row), -90)
        row['movement_input_active'] = True
        row['input_yaw'] = 80
        self.assertEqual(h.air_facing_target(row), -90)
        h.combat['active'] = True
        self.assertEqual(h.air_facing_target(row), row['control_rotation']['Yaw'])
