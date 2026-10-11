"""0.3.9.31: summon seat window, hidden-character camera alignment, QA trace."""
import ctypes
import struct
import unittest
from types import SimpleNamespace as S
from unittest.mock import Mock, patch

import support  # noqa: F401  (installs the SDK fakes)
from BL4ThirdPersonPOC.omni import hitch
from BL4ThirdPersonPOC.omni import summon_seat as seatmod
from BL4ThirdPersonPOC.omni.vehicle_summon import SummonFacing, CAPACITY, RECORD_SIZE


def bits(yaw):
    return struct.unpack('<Q', struct.pack('<d', float(yaw)))[0]


class World:
    """One character, one summoned vehicle, a controller with a writable camera yaw."""

    def __init__(self, camera_yaw=0.0, target=180.0, driver='character', actor_hidden=False,
                 mesh_visible=True, ticket_age=3, vehicle_yaw=None):
        self.character = S(Name='character', bHidden=actor_hidden,
                           Mesh=S(bVisible=mesh_visible, bHiddenInGame=False))
        self.vehicle_yaw = target if vehicle_yaw is None else vehicle_yaw
        self.vehicle = S(Name='OakVehicle_7', Class=S(Name='OakVehicle'), _get_address=lambda: 0x7000,
                         Mesh=S(SkeletalMeshAsset=S(Name='SK_Test')),
                         OakVehicleMovement=S(Class=S(Name='OakWheeledVehicleMovementComponent'), DesiredYaw=0.0),
                         K2_GetActorRotation=lambda: S(Yaw=self.vehicle_yaw))
        self.vehicle.DriverPawn = self.character if driver == 'character' else driver
        self.rotation = S(Pitch=-10.0, Yaw=camera_yaw, Roll=0.0)
        self.writes = []

        def set_rotation(rotator):
            self.writes.append(rotator)
            self.rotation.Yaw = rotator.Yaw
        self.pc = S(ControlRotation=self.rotation, SetControlRotation=set_rotation,
                    PersonalVehicleState=S(Vehicle=self.vehicle))
        summon = SummonFacing.__new__(SummonFacing)
        summon.control = [0] * 24
        summon.buffer = (ctypes.c_ubyte * (CAPACITY * RECORD_SIZE))()
        summon.frames = 1000
        summon.seat = None
        summon.owner = S(report={})
        summon.pawn_ref = lambda: self.character
        if ticket_age is not None:
            struct.pack_into('<QQQQ', summon.buffer, 0, 1, bits(camera_yaw), bits(target), 1000 - ticket_age)
            summon.control[5] = 1
        self.summon = summon

    def run(self, frames, pawn=None):
        for _ in range(frames):
            self.summon.frames += 1
            current = self.vehicle if pawn is None else pawn
            self.summon.seat_frame(self.pc, current, current is self.character)


class SummonTicketTests(unittest.TestCase):
    def test_reads_the_native_record_layout(self):
        world = World(camera_yaw=12.5, target=-170.0)
        ticket = seatmod.summon_ticket(world.summon)
        self.assertEqual((ticket['target'], ticket['camera'], ticket['age']), (-170.0, 12.5, 3))

    def test_old_missing_or_foreign_records_are_no_ticket(self):
        self.assertIsNone(seatmod.summon_ticket(World(ticket_age=None).summon))
        self.assertIsNone(seatmod.summon_ticket(World(ticket_age=seatmod.TICKET_MAX_AGE + 1).summon))
        world = World()
        world.summon.control[5] = CAPACITY + 1
        self.assertIsNone(seatmod.summon_ticket(world.summon))


class AlignmentTests(unittest.TestCase):
    def test_hidden_character_behind_camera_gets_camera_behind_vehicle_once(self):
        for kw in (dict(driver=None), dict(actor_hidden=True), dict(mesh_visible=False)):
            with self.subTest(**kw):
                world = World(camera_yaw=0.0, target=180.0, **kw)
                world.run(seatmod.WINDOW + 5)
                self.assertEqual(len(world.writes), 1)
                write = world.writes[0]
                self.assertEqual((write.Pitch, write.Yaw, write.Roll), (-10.0, 180.0, 0.0))
                row = world.summon.owner.report['summon_seats'][0]
                self.assertEqual(row['align'], 'f2:0>180')
                self.assertTrue(row['hidden_from'].startswith('0:'))

    def test_visible_driver_keeps_camera(self):
        world = World(camera_yaw=0.0, target=180.0)
        world.run(seatmod.WINDOW)
        self.assertEqual(world.writes, [])
        self.assertEqual(world.summon.owner.report['summon_seats'][0]['align'], 'visible_driver')

    def test_sideways_gap_keeps_camera_even_when_hidden(self):
        for target in (90.0, -90.0, 45.0):
            with self.subTest(target=target):
                world = World(camera_yaw=0.0, target=target, driver=None)
                world.run(seatmod.WINDOW)
                self.assertEqual(world.writes, [])
                self.assertTrue(world.summon.owner.report['summon_seats'][0]['align'].startswith('kept_gap_'))

    def test_without_summon_ticket_nothing_is_written(self):
        world = World(camera_yaw=0.0, target=180.0, driver=None, ticket_age=None)
        world.run(seatmod.WINDOW)
        self.assertEqual(world.writes, [])
        self.assertEqual(world.summon.owner.report['summon_seats'][0]['align'], 'no_summon_ticket')

    def test_short_hide_is_not_confirmed(self):
        world = World(camera_yaw=0.0, target=180.0, driver=None)
        world.run(seatmod.HIDDEN_CONFIRM_FRAMES - 1)
        world.vehicle.DriverPawn = world.character
        world.run(seatmod.WINDOW)
        self.assertEqual(world.writes, [])

    def test_wraparound_gap(self):
        world = World(camera_yaw=170.0, target=-175.0, driver=None)
        world.run(seatmod.WINDOW)
        self.assertEqual(world.writes, [])
        world = World(camera_yaw=-100.0, target=100.0, driver=None)
        world.run(seatmod.WINDOW)
        self.assertEqual(len(world.writes), 1)


class TraceTests(unittest.TestCase):
    def test_one_line_per_seat_with_timeline_and_turn_frame(self):
        world = World(camera_yaw=0.0, target=180.0, vehicle_yaw=180.0)
        with patch.object(hitch, 'note') as note:
            world.run(5)
            world.vehicle_yaw = 0.0
            world.run(seatmod.WINDOW + 10)
        note.assert_called_once()
        line = note.call_args[0][1]
        for part in ('summon ', 'cls=OakVehicle', 'mesh=SK_Test', 'movement=OakWheeledVehicleMovementComponent',
                     'seat=visible_driver', 'target=180', 'summon_camera=0', 'turn_frame=5', 'end=window',
                     'timeline=0:180/0/0,1:180/0/0'):
            self.assertIn(part, line)

    def test_leaving_early_finishes_and_next_seat_opens_new_window(self):
        world = World()
        with patch.object(hitch, 'note') as note:
            world.run(4)
            world.run(1, pawn=world.character)
            world.run(2)
        note.assert_called_once()
        self.assertIn('end=left_vehicle', note.call_args[0][1])
        self.assertIsNotNone(world.summon.seat)
        self.assertEqual(world.summon.seat.frame, 2)

    def test_failing_read_closes_window_without_raising(self):
        world = World(driver=None)
        world.vehicle.K2_GetActorRotation = Mock(side_effect=RuntimeError('expired'))
        with patch.object(hitch, 'note') as note:
            world.run(3)
        note.assert_called_once()
        self.assertIn('end=error', note.call_args[0][1])
        self.assertEqual(world.writes, [])

    def test_on_foot_without_window_touches_nothing(self):
        world = World()
        world.summon.pawn_ref = Mock(side_effect=AssertionError)
        world.summon.seat_frame(object(), world.character, True)
        self.assertIsNone(world.summon.seat)

    def test_text_never_raises(self):
        self.assertEqual(hitch.text(lambda: 1 / 0), '?')
        self.assertEqual(hitch.text(lambda: 'a b'), 'a_b')
        self.assertEqual(len(hitch.text(lambda: 'x' * 200, 10)), 10)


if __name__ == '__main__':
    unittest.main()
