"""Real .32 publication paths and existing native record layout; SDK substitutes."""
import ctypes
import math
import struct
from types import SimpleNamespace as S
from unittest.mock import Mock, patch
import unittest

import support
from BL4ThirdPersonPOC.omni import hitch
from BL4ThirdPersonPOC.omni.vehicle_summon import SummonFacing
from BL4ThirdPersonPOC.omni.vehicle_exit import ExitFacing, CAPACITY, RECORD_SIZE
import test_omni_bind_hitch_0_3_9_29 as bind_tests


def bits(yaw):
    return struct.unpack('<Q', struct.pack('<d', yaw))[0]


class SummonWorld:
    def __init__(self):
        self.actor = S(Pitch=0., Yaw=30., Roll=0.)
        self.pawn = S(Class=S(Name='OakCharacter'),
                      OakCharacterMovement=S(MovementMode=1),
                      K2_GetActorRotation=Mock(side_effect=lambda: self.actor),
                      GetLastMovementInputVector=Mock(side_effect=AssertionError('input direction read')))
        self.pc = S()
        self.camera = S(CameraModeState=S(bIsTransitioning=False),
                        CameraModeInputs=S(ViewTarget=self.pawn),
                        GetActorCameraMode=lambda pawn: 'ThirdPerson')
        self.session = S(active=True, special_paused=False)
        facing = self.facing = SummonFacing.__new__(SummonFacing)
        facing.control = [0] * 24
        facing.control[5] = facing.control[13] = facing.control[19] = 2
        facing.frames, facing.boot_consumed = 0, 2
        facing.last_yaw, facing.source = -120., 'old_direction'
        facing.pc_ref, facing.pawn_ref = lambda: self.pc, lambda: self.pawn
        facing.seat_vehicle = facing.seat = None
        facing.owner = S(sup=S(child=self.session), normal=lambda pc: True)
        facing.mod = S(_third_person_pushed=True)

    def tick(self):
        self.facing.frame(self.pc, self.pawn, self.camera)

    @property
    def published_yaw(self):
        return struct.unpack('<d', struct.pack('<Q', self.facing.control[4]))[0]


class SummonBodyTests(unittest.TestCase):
    def test_requested_input_cannot_replace_the_actual_body_yaw(self):
        world = SummonWorld()
        world.tick()
        self.assertEqual(world.published_yaw, 30.)
        self.assertEqual(world.facing.source, 'current_character_body')
        world.pawn.GetLastMovementInputVector.assert_not_called()
        self.assertEqual(world.pawn.K2_GetActorRotation.call_count, 1)
        self.assertEqual(world.facing.control[0], 1)

    def test_idle_turn_and_post_exit_rotation_replace_old_summon_yaw(self):
        world = SummonWorld()
        for yaw in (30., -90., 170., -179., 359.):
            world.actor.Yaw = yaw
            world.tick()
            self.assertAlmostEqual(world.published_yaw, (yaw + 180.) % 360. - 180.)
        self.assertEqual(world.facing.frames, 5)

    def test_nonfinite_body_fails_with_summon_gate_already_closed(self):
        for yaw in (math.nan, math.inf, -math.inf):
            with self.subTest(yaw=yaw):
                world = SummonWorld()
                world.actor.Yaw = yaw
                world.facing.control[0] = 1
                with self.assertRaisesRegex(RuntimeError, 'Nonfinite actor yaw'):
                    world.tick()
                self.assertEqual(world.facing.control[0], 0)
                self.assertEqual(world.published_yaw, 0.)

    def test_paused_or_unready_context_does_not_read_or_publish_body(self):
        for blocked in ('paused', 'inactive', 'camera_transition', 'view_target', 'movement', 'normal'):
            with self.subTest(blocked=blocked):
                world = SummonWorld()
                if blocked == 'paused':
                    world.session.special_paused = True
                elif blocked == 'inactive':
                    world.session.active = False
                elif blocked == 'camera_transition':
                    world.camera.CameraModeState.bIsTransitioning = True
                elif blocked == 'view_target':
                    world.camera.CameraModeInputs.ViewTarget = S()
                elif blocked == 'movement':
                    world.pawn.OakCharacterMovement.MovementMode = 3
                else:
                    world.facing.owner.normal = lambda pc: False
                world.tick()
                world.pawn.K2_GetActorRotation.assert_not_called()
                self.assertEqual(world.facing.control[0], 0)

    def test_expired_local_character_or_foreign_controller_fail_before_body_read(self):
        for changed in ('character', 'controller'):
            with self.subTest(changed=changed):
                world = SummonWorld()
                if changed == 'character':
                    world.facing.pawn_ref = lambda: None
                else:
                    world.facing.pc_ref = lambda: S(foreign=True)
                with self.assertRaisesRegex(RuntimeError, 'local owner expired'):
                    world.tick()
                world.pawn.K2_GetActorRotation.assert_not_called()
                self.assertEqual(world.facing.control[0], 0)

    def test_closed_old_seat_tickets_are_still_cleared(self):
        world = SummonWorld()
        world.tick()
        self.assertEqual([world.facing.control[i] for i in (5, 13, 19)], [0, 0, 0])
        self.assertEqual(world.facing.boot_consumed, 0)


class VehicleBodyTests(unittest.TestCase):
    def setUp(self):
        self.helper = bind_tests.ExitFacingTests()

    def test_all_four_tap_directions_keep_the_vehicle_orientation_at_every_speed(self):
        for speed in (0., 20., 149., 150., 151., 600.):
            for xy in ((speed, 0.), (-speed, 0.), (0., speed), (0., -speed)):
                with self.subTest(velocity=xy):
                    facing = self.helper.facing()
                    with patch.object(hitch, 'note'):
                        self.helper.publish(facing, xy, body_yaw=73.)
                    self.assertEqual(facing.last_yaw, 73.)
                    self.assertEqual(struct.unpack('<d', struct.pack('<Q', facing.control[6]))[0], 73.)
                    self.assertEqual(facing.source, 'vehicle_body_orientation')

    def test_short_turn_updates_publication_even_before_vehicle_stops(self):
        facing = self.helper.facing()
        with patch.object(hitch, 'note'):
            for yaw, xy in ((0., (0., 0.)), (45., (-500., 0.)),
                            (110., (0., -400.)), (110., (1., 1.))):
                self.helper.publish(facing, xy, body_yaw=yaw)
                self.assertEqual(facing.last_yaw, yaw)

    def test_invalid_body_does_not_publish_a_new_yaw(self):
        facing = self.helper.facing()
        facing.control[6] = bits(55.)
        with self.assertRaisesRegex(RuntimeError, 'Nonfinite SDK value'):
            self.helper.publish(facing, (600., 0.), body_yaw=math.nan)
        self.assertEqual(facing.control[6], bits(55.))

    def test_foreign_driver_is_rejected_before_actor_getter(self):
        facing = self.helper.facing()
        getter = Mock(side_effect=AssertionError('foreign body read'))
        vehicle = S(DriverPawn='other', K2_GetActorRotation=getter)
        pc = S(PersonalVehicleState=S(Vehicle=vehicle), Pawn=vehicle)
        with self.assertRaisesRegex(RuntimeError, 'possession/driver changed'):
            facing.publish_vehicle(pc, vehicle, S())
        getter.assert_not_called()


class NativeExitReportTests(unittest.TestCase):
    def facing(self):
        facing = ExitFacing.__new__(ExitFacing)
        facing.pc_address, facing.pawn_address, facing.movement_address = 0x10000, 0x20000, 0x30000
        facing.control = [0] * 16
        facing.control[3] = 0x40000
        facing.frames = 102
        facing.last_yaw = -45.  # Deliberately differs from what the native exit applied.
        facing.buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        row = [1, facing.pc_address, 0x40000, facing.pawn_address, facing.movement_address,
               bits(0.), bits(120.), bits(0.), bits(73.), 100, 3, bits(-90.), 0, 0, 0, 0]
        return facing, row

    def test_report_decodes_actual_applied_yaw_and_age_from_last_native_record(self):
        facing, row = self.facing()
        struct.pack_into('<16Q', facing.buffer, RECORD_SIZE, *row)
        result = facing.exit_snapshot(2)
        self.assertEqual(result, dict(applied_yaw=73., native_original_yaw=120.,
                         native_camera_yaw=-90., publication_update=100,
                         publication_sequence=3, publication_age_updates=2))
        self.assertEqual(facing.last_yaw, -45.)

    def test_malformed_foreign_or_nonfinite_records_only_fail_the_diagnostic(self):
        for field in (0, 1, 2, 3, 4, 6, 8, 11):
            with self.subTest(field=field):
                facing, row = self.facing()
                row[field] = bits(math.nan) if field in (6, 8, 11) else 0
                struct.pack_into('<16Q', facing.buffer, 0, *row)
                result = facing.exit_snapshot(1)
                self.assertEqual(result['applied_yaw'], '?')
                self.assertIn('native_record_error', result)

    def test_invalid_count_is_bounded_and_report_only(self):
        facing, _ = self.facing()
        for count in (-1, 0, CAPACITY + 1):
            result = facing.exit_snapshot(count)
            self.assertEqual(result['applied_yaw'], '?')
            self.assertIn('native_record_error', result)

    def test_actual_exit_frame_reports_native_yaw_before_clearing_the_seat_buffer(self):
        facing, row = self.facing()
        struct.pack_into('<16Q', facing.buffer, 0, *row)
        facing.control[8], facing.consumed = 1, 0
        facing.gap_control = [0] * 16
        facing.gap_seat_open = False
        component = S()
        movement = S(UpdatedComponent=component)
        character = S(OakCharacterMovement=movement, CharacterMovement=movement,
                      K2_GetActorRotation=lambda: S(Yaw=173.))
        pc, camera = S(GetControlRotation=lambda: S(Yaw=-90.)), S()
        facing.pc_ref, facing.camera_ref = lambda: pc, lambda: camera
        facing.pawn_ref, facing.movement_ref = lambda: character, lambda: movement
        facing.component_ref = lambda: component
        facing.owner = S(report=dict(exit_rotations=0))
        facing.last_speed, facing.source = 400., 'vehicle_body_orientation'
        facing.transition_validate = Mock()
        with patch.object(hitch, 'note'):
            facing.frame(pc, character, camera)
        result = facing.owner.report['exit_facings'][0]
        self.assertEqual(result['applied_yaw'], 73.)
        self.assertEqual(result['character_yaw'], '173')
        self.assertEqual(facing.owner.report['exit_rotations'], 1)
        self.assertEqual(facing.control[8], 0)


if __name__ == '__main__':
    unittest.main()
