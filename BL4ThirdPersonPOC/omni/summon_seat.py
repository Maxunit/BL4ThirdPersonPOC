"""Summon seat window: QA timeline plus camera alignment for hidden-character vehicles.

After an Omni summon the vehicle spawns facing the character's direction and the
camera keeps its own direction (possession stub). A vehicle that does not seat
the character visibly (no driver, hidden actor or hidden mesh) can turn itself
toward the camera when the camera looks far away from that direction; in game
this showed only for a camera behind the summon direction, never for a sideways
one. For such a seat, once, the camera is put behind the summoned direction when
the gap exceeds ALIGN_MIN_DELTA. All other seats and smaller gaps keep the
camera exactly as before.

Reads happen only inside the bounded window after a seat start; at most one
SetControlRotation per seat. A failing read ends the window, never gameplay.
"""
from __future__ import annotations

import ctypes
import math
import struct

from unrealsdk import make_struct
from unrealsdk.unreal import WeakPointer

from . import hitch

ALIGN_MIN_DELTA = 90.0
HIDDEN_CONFIRM_FRAMES = 3
TICKET_MAX_AGE = 300
WINDOW = 90
SAMPLES = (0, 1, 2, 3, 5, 10, 20, 40, 89)
TURN_DEGREES = 15.0
KEEP = 8
RECORD_SIZE = 64


def wrap(delta: float) -> float:
    return (float(delta) + 180.0) % 360.0 - 180.0


def bits_yaw(bits: int) -> float:
    return struct.unpack('<d', struct.pack('<Q', int(bits)))[0]


def fmt(value: float) -> str:
    return format(float(value), '.0f')


def summon_ticket(summon):
    """Latest summon-getter record (camera yaw in, spawn yaw out) if it is recent."""
    try:
        count = int(summon.control[5])
        if count < 1 or count * RECORD_SIZE > ctypes.sizeof(summon.buffer):
            return None
        flag, original, applied, stamp = struct.unpack_from('<QQQQ', summon.buffer, (count - 1) * RECORD_SIZE)
        age = int(summon.frames) - int(stamp)
        target, camera = bits_yaw(applied), bits_yaw(original)
        if flag != 1 or not 0 <= age <= TICKET_MAX_AGE or not (math.isfinite(target) and math.isfinite(camera)):
            return None
        return dict(target=target, camera=camera, age=age)
    except Exception:
        return None


def _flag(read):
    try:
        return bool(read())
    except Exception:
        return None


def hidden_reasons(vehicle, character) -> list:
    """Why the character is not visibly seated; empty for a normal driver seat."""
    reasons = []
    try:
        driver = vehicle.DriverPawn
        if driver is None:
            reasons.append('no_driver')
        elif driver != character:
            reasons.append('other_driver')
    except Exception:
        pass
    if _flag(lambda: character.bHidden):
        reasons.append('actor_hidden')
    if _flag(lambda: not character.Mesh.bVisible) or _flag(lambda: character.Mesh.bHiddenInGame):
        reasons.append('mesh_hidden')
    return reasons


def mesh_asset(vehicle):
    mesh = vehicle.Mesh
    for name in ('SkeletalMeshAsset', 'SkeletalMesh'):
        try:
            asset = getattr(mesh, name)
        except Exception:
            continue
        if asset is not None:
            return asset.Name
    return None


class SummonSeat:
    """One vehicle seat; finished once by window end, leaving or a failing read."""

    def __init__(self, summon, vehicle):
        self.summon = summon
        self.ref = WeakPointer(vehicle)
        self.ticket = summon_ticket(summon)
        self.frame = 0
        self.hidden_run = 0
        self.align = None
        self.turn_frame = None
        self.samples = []
        self.done = False
        control = summon.control
        address = hitch.text(lambda: int(vehicle._get_address()))
        self.row = dict(
            vehicle=hitch.text(lambda: vehicle.Name),
            cls=hitch.text(lambda: vehicle.Class.Name),
            mesh=hitch.text(lambda: mesh_asset(vehicle)),
            movement=hitch.text(lambda: vehicle.OakVehicleMovement.Class.Name),
            possession=hitch.text(lambda: int(control[12])),
            boot_hold=hitch.text(lambda: int(bool(control[16]) and str(int(control[17])) == address)))

    def step(self, pc, vehicle, character):
        f = self.frame
        self.frame += 1
        vehicle_yaw = float(vehicle.K2_GetActorRotation().Yaw)
        rotation = pc.ControlRotation
        camera_yaw = float(rotation.Yaw)
        reasons = hidden_reasons(vehicle, character)
        if f == 0:
            self.row['seat'] = '+'.join(reasons) or 'visible_driver'
        if reasons and 'hidden_from' not in self.row:
            self.row['hidden_from'] = str(f) + ':' + '+'.join(reasons)
        self.hidden_run = self.hidden_run + 1 if reasons else 0
        target = None if self.ticket is None else self.ticket['target']
        if target is not None and self.turn_frame is None and abs(wrap(vehicle_yaw - target)) > TURN_DEGREES:
            self.turn_frame = f
        if self.align is None and target is not None and self.hidden_run >= HIDDEN_CONFIRM_FRAMES:
            gap = wrap(target - camera_yaw)
            if abs(gap) > ALIGN_MIN_DELTA:
                pc.SetControlRotation(make_struct('Rotator', Pitch=float(rotation.Pitch), Yaw=float(target), Roll=0.0))
                self.align = 'f' + str(f) + ':' + fmt(camera_yaw) + '>' + fmt(target)
                camera_yaw = float(target)
            else:
                self.align = 'kept_gap_' + fmt(gap)
        if f in SAMPLES:
            desired = hitch.value(lambda: vehicle.OakVehicleMovement.DesiredYaw)
            self.samples.append(str(f) + ':' + fmt(vehicle_yaw) + '/' + fmt(camera_yaw) + '/' + desired)
        if self.frame >= WINDOW:
            self.finish('window')

    def finish(self, reason: str) -> None:
        if self.done:
            return
        self.done = True
        ticket = self.ticket
        if self.align is not None:
            align = self.align
        elif ticket is None:
            align = 'no_summon_ticket'
        else:
            align = 'visible_driver'
        self.row.update(
            end=reason, frames=self.frame,
            target='-' if ticket is None else fmt(ticket['target']),
            summon_camera='-' if ticket is None else fmt(ticket['camera']),
            ticket_age='-' if ticket is None else ticket['age'],
            align=align,
            turn_frame='-' if self.turn_frame is None else self.turn_frame,
            timeline=','.join(self.samples) or '-')
        try:
            seats = self.summon.owner.report.setdefault('summon_seats', [])
            seats.append(dict(self.row))
            del seats[:-KEEP]
        except Exception:
            pass
        hitch.note('[OmniVehicle]', 'summon ' + ' '.join(k + '=' + str(v) for k, v in self.row.items()))
