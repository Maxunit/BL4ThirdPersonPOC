"""Retain the legacy FFYL camera and collision owner for fallback/cleanup.

The selected simple FFYL strategy shuts this owner down before taking control.
Native prefixes, executable fingerprint, reflection schemas and live stack
membership gate writes to perspective masks, socket state and camera offsets.
The legacy outer owner installs camera-entry consumers; the collision owner
uses bounded SDK sweeps and verifies owned bytes before restoration.
Capture buffers are bounded; native callback/control pins survive retirement.
This fallback is not interchangeable with the selected simple FFYL strategy.
"""

import math
import ctypes
import json
import struct
from .build_gate import REVIEWED_BUILD
import sys
import traceback
import types
import time
from datetime import datetime, timezone
from pathlib import Path
from unrealsdk import find_object, logging, make_struct
from unrealsdk.hooks import Type, add_hook, has_hook, remove_hook

from . import camera_hook_chain as chain

TAG = "[BL4ThirdPersonPOC.FFYL]"
EXPECTED = REVIEWED_BUILD
STATE_KEY = "_bl4tps_ffyl_beta_collision"
requested_camera_offset = (-180.0, 45.0, 20.0)


def basis(angles):
    """Convert Euler angles in degrees to the retained camera rotation basis."""
    p, y, r = (math.radians(v) for v in angles)
    cp, sp, cy, sy, cr, sr = (
        math.cos(p),
        math.sin(p),
        math.cos(y),
        math.sin(y),
        math.cos(r),
        math.sin(r),
    )
    return (
        (cp * cy, sr * sp * cy - cr * sy, -cr * sp * cy - sr * sy),
        (cp * sy, sr * sp * sy + cr * cy, sr * cy - cr * sp * sy),
        (sp, -sr * cp, cr * cp),
    )


def compose(left, right):
    """Multiply the two 3x3 rotation bases in the existing camera composition order."""
    return tuple(
        tuple(sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3))
        for i in range(3)
    )


def multiply(matrix, values):
    """Transform a three-component local vector through the supplied basis."""
    return tuple(sum(a * b for a, b in zip(row, values)) for row in matrix)


def local_hit(origin, rotation, start, end, fraction):
    distance = math.dist(start, end)
    # Sphere trace Time is the sphere-centre travel fraction, not ImpactPoint.
    fraction = max(0.0, min(1.0, fraction) - 2.0 / max(distance, 2.0))
    safe = tuple(a + (b - a) * fraction for a, b in zip(start, end))
    transpose = tuple(zip(*rotation))
    return multiply(transpose, tuple(a - b for a, b in zip(safe, origin)))


def toggle_legacy_ffyl_collision():
    """Arm or restore the legacy FFYL collision/socket owner.

    Entry requires the verified outer camera owner and supported build/schema.
    Definitions, socket masks and offsets are restored only while ownership
    comparisons agree; cleanup faults retain the backing state.
    """
    previous_state = sys.modules.get(STATE_KEY)
    if previous_state is not None:
        previous_state.restore("manual")
        return
    report = {
        "version": "legacy-ffyl-camera",
        "functions": {},
        "definitions": {},
        "errors": [],
        "limits": [],
        "native_patches": 0,
        "sdk_hooks": 0,
        "game_writes": 0,
        "timers": 0,
        "sdk_offset_writes": 0,
        "samples": [],
        "hook_removal_errors": [],
        "note": "Definition fields interpreted using declared CameraModeDef schema and constructor evidence; shared definition masks 2/4 only; FFYL mode and behavior list unchanged; no activation call.",
    }
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        kernel.GetCurrentProcess.argtypes = ()
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.ReadProcessMemory.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel.ReadProcessMemory.restype = ctypes.c_int
        handle = kernel.GetCurrentProcess()
        base = int(kernel.GetModuleHandleW(None) or 0)
        if not base:
            raise RuntimeError("Main module unavailable")

        def read(address, size):
            if (
                not 0 < size <= 0x10000
                or not 0x10000 <= address < 0x0000800000000000
                or address + size > 0x0000800000000000
            ):
                raise ValueError("Read outside bounded read limits")
            buf = ctypes.create_string_buffer(size)
            got = ctypes.c_size_t()
            ok = kernel.ReadProcessMemory(handle, address, buf, size, ctypes.byref(got))
            if not ok or got.value != size:
                raise OSError(
                    f"ReadProcessMemory failed at {address:#x}, "
                    f"bytes={got.value}/{size}, winerror={ctypes.get_last_error()}"
                )
            return buf.raw

        dos = read(base, 64)
        if dos[:2] != b"MZ":
            raise RuntimeError("DOS header mismatch")
        pe_offset = struct.unpack_from("<I", dos, 60)[0]
        if not 64 <= pe_offset <= 0x100000:
            raise RuntimeError("PE header offset outside bounds")
        pe = read(base + pe_offset, 24)
        if pe[:4] != b"PE\0\0":
            raise RuntimeError("PE signature mismatch")
        machine, section_count, timestamp = struct.unpack_from("<HHI", pe, 4)
        optional_size = struct.unpack_from("<H", pe, 20)[0]
        if not 1 <= section_count <= 96 or not 64 <= optional_size <= 4096:
            raise RuntimeError("PE layout outside bounds")
        optional = read(base + pe_offset + 24, optional_size)
        if struct.unpack_from("<H", optional)[0] != 0x20B:
            raise RuntimeError("Expected PE32+")
        image_size = struct.unpack_from("<I", optional, 56)[0]
        report["build"] = {
            "module_base": hex(base),
            "pe_timestamp": hex(timestamp),
            "size_of_image": hex(image_size),
            "machine": hex(machine),
        }
        if (timestamp, image_size, machine) != EXPECTED:
            raise RuntimeError("Build mismatch; native function reads refused")
        section_data = read(base + pe_offset + 24 + optional_size, section_count * 40)
        executable = []
        for i in range(section_count):
            name, virtual_size, rva, raw_size = struct.unpack_from(
                "<8sIII", section_data, i * 40
            )
            flags = struct.unpack_from("<I", section_data, i * 40 + 36)[0]
            if flags & 0x20000000:
                span = max(virtual_size, raw_size)
                if not 0 < span or rva + span > image_size:
                    raise RuntimeError("Executable section outside image")
                executable.append((base + rva, base + rva + span))
        report["executable_ranges"] = [
            {"start": hex(a), "end": hex(b)} for a, b in executable
        ]
        if not executable:
            raise RuntimeError("No executable sections")
        candidates = [
            m
            for name, m in list(sys.modules.items())
            if m is not None
            and name.endswith("BL4ThirdPersonPOC")
            and callable(getattr(m, "_get_runtime", None))
        ]
        if len(candidates) != 1:
            raise RuntimeError("Expected one loaded TPS mod")
        mod = candidates[0]
        report["mod_version"] = str(mod.mod.version)
        _pc, pawn, cam = mod._get_runtime()
        if _pc is None or pawn is None or cam is None:
            raise RuntimeError("Run in loaded gameplay")
        runtime_identity = tuple(int(x._get_address()) for x in (_pc, pawn, cam))

        def owned_early_transition():
            owner = sys.modules.get(ARM_KEY)
            return (
                owner is not None
                and owner.active
                and getattr(owner, "early_busy", False)
                and struct.unpack_from("<I", owner.view_control, 184)[0] == 2
                and struct.unpack_from("<Q", owner.view_control, 0)[0]
                == int(cam.CameraModeState._get_address())
            )

        if str(cam.GetActorCameraMode(pawn)) != "FFYL" or (
            bool(cam.CameraModeState.bIsTransitioning) and not owned_early_transition()
        ):
            raise RuntimeError("Run during settled FFYL")
        if mod._native_fault or mod._native_active():
            raise RuntimeError(
                "Native correction must be released without a native fault"
            )
        if not callable(getattr(mod, "_set_camera_offset", None)):
            raise RuntimeError("Verified GU offset setter unavailable")

        # Verify the measured fast-path accessor identity/table without executing it.
        channel_anchors = {
            "0x4a950b5": "488b3d4c2c0308",
            "0x4a950c1": "488bb710010000",
            "0x4a950d1": "803d602c030800",
            "0x4a950f2": "4889f0",
        }
        for rva, hx in channel_anchors.items():
            if read(base + int(rva, 16), len(bytes.fromhex(hx))) != bytes.fromhex(hx):
                raise RuntimeError("Camera collision accessor changed: " + rva)
        profile = find_object(
            "CollisionProfile", "/Script/Engine.Default__CollisionProfile"
        )
        if profile is None or int(profile.Class.PropertySize) != 0x170:
            raise RuntimeError("Verified collision profile unavailable")
        profile_address = int(profile._get_address())
        profile_class = int(profile.Class._get_address())
        if (
            struct.unpack("<Q", read(base + 0xCAC7D08, 8))[0] != profile_class
            or struct.unpack("<Q", read(profile_class + 0x110, 8))[0] != profile_address
            or read(base + 0xCAC7D38, 1) == b"\x00"
        ):
            raise RuntimeError("Collision accessor no longer returns SDK profile")
        channel_header = read(profile_address + 0x160, 16)
        channel_ptr, channel_count, channel_capacity = struct.unpack(
            "<Qii", channel_header
        )
        if (
            not 0 < channel_count <= channel_capacity <= 64
            or not 0x10000 <= channel_ptr < 0x800000000000
            or channel_ptr % 4
        ):
            raise RuntimeError("Collision mapping outside bounds")
        channel_bytes = read(channel_ptr, channel_count * 4)
        channels = struct.unpack("<" + "i" * channel_count, channel_bytes)
        if channels.count(4) != 1 or any(not 0 <= x <= 32 for x in channels):
            raise RuntimeError("Camera collision mapping invalid")
        camera_query = channels.index(4)
        if (
            read(profile_address + 0x160, 16) != channel_header
            or read(channel_ptr, channel_count * 4) != channel_bytes
        ):
            raise RuntimeError("Collision mapping changed")
        library = find_object(
            "KismetSystemLibrary", "/Script/Engine.Default__KismetSystemLibrary"
        )
        if (
            library is None
            or find_object(
                "Function", "/Script/Engine.KismetSystemLibrary:SphereTraceSingle"
            )
            is None
        ):
            raise RuntimeError("SDK sphere trace unavailable")
        report["collision"] = {
            "radius": 10.0,
            "native_channel": 4,
            "sdk_trace_query": camera_query,
            "queries": 0,
            "hits": 0,
            "rows": [],
            "model": "POV.Location + (UE(POV.Rotation) * UE(BaseRotationOffset)) * camera offset; other spatial offsets must be zero",
        }
        cs = cam.CameraModeState
        if str(cs.Class._path_name()) != "/Script/GbxGame.CameraModeState":
            raise RuntimeError("Unexpected camera-state class")
        # The GetPOV capture composes the POV quaternion with BaseRotationOffset
        # quaternion; Hamilton product; CameraRotationOffset; final RotateVector.
        # Check the full immutable function; do not call it from this reader.
        composition_anchors = {
            "0x6a9c0e": "4157415641545657534881ec98020000440f29bc2480020000440f29b42470020000440f29ac2460020000440f29a42450020000440f299c2440020000440f29942430020000440f298c2420020000440f298424100200000f29bc24000200000f29b424f00100004c89c74889d64889cb488b05ba5c050c4831e048898424e8010000660f107148f20f10795866440f28352c7b2809660f28c666410f5ec6660f28cf66410f5ece660f3a09c003660f3a09c90366410f59c666410f59ce660f5cf0660f5cf9660f2805247b2809660f59f0660f59f8660f28c6e813c2270966440f28c066440f28d666440f15d666410f28c2e8fac1270966440f28c8660f28c7e8ecc1270966440f28d866440f28e766440f15e766410f28c4e8d3c12709660f28c6e84ac1270966440f28e866410f28c2e83bc12709660f28f0660f28c7e82ec12709660f28f866410f28c4e820c12709f2410f12c3f20f12cff2410f12d5f2410f12d866410f28e1660f14e666410f14f166440f28fb66440f59fc660f59e266440f59f9660f59e166440f573d5fe75509660f59d6660f59f3660f59f0660f57353b7b2809660f58f4660f59d066440f5cfa660f28bba0000000f2440f1083b0000000660f28c766410f5ec666410f28c866410f5ece660f3a09c003660f3a09c90366410f59c666410f59ce660f5cf866440f5cc1660f2805f3792809660f59f866440f59c0660f28c7e8e1c0270966440f28c866440f28df66440f15df66410f28c3e8c8c0270966440f28d066410f28c0e8b9c0270966440f28e066450f28e866450f15e866410f28c5e8a0c02709660f28c7e817c0270966440f28f066410f28c3e808c02709660f28f866410f28c0e8fabf270966440f28c066410f28c5e8ebbf2709f2410f12c4f2410f12d0f2410f12def2410f12e166410f28ea660f14ef66410f14fa660f28cc660f59cd660f59eb660f59ca660f59ea660f570d2de65509660f59df660f59fc660f59f8660f573d097a2809660f58fd660f59d8660f5ccb660f28de660f15de660f28e3660f59e1660f59df660f28c7f2410f12d766450f15ff66410f59ff66440f59f9660fc6c901660fc6c001660f28ea660f59e8660f59d166440f28053202280966410f59e8660f58ec66410f59d0660f58d3660f58fd66410f5cd7f20f12de660f59cb660f59c3660f590df3012809660f58cf66410f59c0660f58c2660f28d1f20f58d1660f28d9660f15d9660f28ebf20f58eb660f28f8f20f58f8660f28e1f20f59e266440f28c1f2440f59c5f20f59cf660f28f3f20f59f5f20f59df66440f28c8f2440f59cf660f15c0f20f59d0f20f59e8f20f59c766450f28d1f2440f58d6f20f103d1800280966440f28dff2450f5cda4c8db42460010000f2450f111e66450f28d0f2440f5cd0f2450f11562066440f28d1f2440f58d5f2450f115640f2440f1015b844190cf2450f115660f2410f58c0f2410f114608f2440f58cc660f28c7f2410f5cc1f2410f114628660f28c3f20f5cc2f2410f1146480f10058644190c410f114668f20f5ccdf2410f114e10f20f58d3f2410f115630f20f58f4f20f5cfef2410f117e504531ff4d897e184d897e384d897e5849bc000000000000f03f4d89667866440f108bd8000000f2440f109be8000000660f2805e0dd760966440f59c866440f59d866410f28c1e82cbe2709660f28f066450f28d166450f15d166410f28c2e814be2709660f28f866410f28c3e806be270966440f28c066450f28e366450f15e366410f28c4e8edbd270966410f28c1e863bd270966440f28c866410f28c2e854bd270966440f28d066410f28c3e845bd270966440f28d866410f28c4e836bd270966410f28c1f2410f59c2488d9424e0000000f20f1102660f28c7f2410f59c1f20f114208f20f1172104c897a18660f28c6f2410f59c0660f28cff2410f59cb660f28d0f2410f59d2f20f5cd1f20f11522066410f28caf2410f59cbf20f59c7f20f58c1f20f114228660f2805c60c280966410f28c8660f57c8f2410f59c9f20f114a304c897a38f2410f59f3660f28cff2410f59c8f20f59fef2410f59f2f20f58f1660f57f0660f137240f2450f59d0f2440f5cd7f2440f115248f2450f59cbf2440f114a504c897a58f20f1005c442190cf20f1142600f1005c042190c0f1142684c8962784c8d7c24604c89f94d89f0e80b881404f2450f105710f2450f100ff2450f105f08f2410f107730f2410f104728f20f11442420f2450f107f20f2450f104750f2410f104748f20f11442428f2450f107740660f57ff66440f2edf750f7a0d660f57c066440f2ec875027b1b66410f28c366410f28c9e8b6bb2709660f28f8f20f593dfaef5909f2450f59c9f2450f59dbf2450f58d90f57c9f2410f51cb66450f57c966450f2ed1750e7a0c660f57c0660f2ec875027b1866410f28c2e86fbb270966440f28c8f2440f590db1ef590966450f28d966440f14df66440f591d8edb760966410f28c3e8e4bb270966440f28d066450f28e366450f15e366410f28c4e8cbbb270966440f28e866410f28c3e83cbb270966440f28d866410f28c4e82dbb2709660f28c8660f57c0f2440f59d066410f28d2f20f59d1f2410f5cd5f2450f59d5f2440f58d1f2440f591d87072809f20f104c2420f2410f59caf2440f59faf2440f58f9f2410f59f3f2410f58f7f20f104c2428f2410f59caf2440f59f2f2440f58f1f2450f59c3f2450f58c666440f2ec0750e7a0c660f57c9660f2ef175027b1666410f28c0660f28cee87eba2709f20f5905c6ee5909f2440f110ff20f117f08f20f114710f20f107340f20f58b380000000f20f107b38f20f587b78f2440f104330f2440f584370f20f1083d0000000f20f588398000000f20f108bc0000000f20f1093c8000000f20f589390000000f20f588b880000004c8d442430f2410f1108f2410f115008f2410f114010488d5c24484889f94889dae8baf6b1fff20f587310f20f587b08f2440f5803f2440f1106f20f117e08f20f117610488b8c24e80100004831e1483b0d9e54050c75690f28b424f00100000f28bc2400020000440f28842410020000440f288c2420020000440f28942430020000440f289c2440020000440f28a42450020000440f28ac2460020000440f28b42470020000440f28bc24800200004881c4980200005b5f5e415c415e415fc3"
        }
        for rva, hx in composition_anchors.items():
            expected = bytes.fromhex(hx)
            live_code = read(base + int(rva, 16), len(expected))
            outer = sys.modules.get(ARM_KEY)
            view_hook = getattr(outer, "view_hook", None)
            if view_hook is not None and int(rva, 16) == POV_RVA:
                length = len(view_hook["original"])
                if live_code[:length] != view_hook["patch"]:
                    raise RuntimeError("Owned GetPOV detour changed")
                live_code = view_hook["original"] + live_code[length:]
            if live_code != expected:
                raise RuntimeError("Reviewed camera rotation composition changed")
        report["composition_evidence"] = {
            "rva": "0x6a9c0e",
            "bytes_verified": 2303,
            "order": "R_POV * R_BaseRotationOffset; CameraRotationOffset must remain zero",
            "native_calls": 0,
        }
        selected = {
            "POV": (0x30, 56),
            "AbsoluteLocationOffset": (0x70, 24),
            "BaseLocationOffset": (0x88, 24),
            "BaseRotationOffset": (0xA0, 24),
            "CameraLocationOffset": (0xC0, 24),
            "CameraRotationOffset": (0xD8, 24),
            "Inputs": (0x28, 8),
        }
        fields = {}
        for owner in [cs.Class, *list(cs.Class._superfields())]:
            for prop in owner._properties():
                name = str(prop.Name)
                if name in selected and name not in fields:
                    fields[name] = (
                        int(prop.Offset_Internal),
                        int(prop.ElementSize),
                        int(prop.ArrayDim),
                    )
        if any(fields.get(k) != (v[0], v[1], 1) for k, v in selected.items()):
            raise RuntimeError("Camera-state spatial schema changed")
        state_address = int(cs._get_address())
        if (
            struct.unpack("<Q", read(int(cam._get_address()) + 0x39D8, 8))[0]
            != state_address
            or struct.unpack("<Q", read(state_address, 8))[0] != base + 0xB00E3D0
        ):
            raise RuntimeError("Camera-state native/SDK identity mismatch")

        outer_target = sys.modules.get(ARM_KEY)
        target = getattr(outer_target, "tps_target", None)
        if target is None or target["identity"] != runtime_identity:
            raise RuntimeError("Verified native TPS offset target unavailable")
        requested_camera_offset = tuple(target["offset"])
        if len(requested_camera_offset) != 3 or not all(
            math.isfinite(v) and abs(v) <= 512 for v in requested_camera_offset
        ):
            raise RuntimeError("TPS target offset outside finite validated bounds")
        report["tps_target_source"] = target
        report["applied_during_blend"] = bool(cam.CameraModeState.bIsTransitioning)
        original_offset = tuple(
            float(getattr(cam.CameraModeState.CameraLocationOffset, axis))
            for axis in ("X", "Y", "Z")
        )
        report["entry_offset_observed"] = list(original_offset)
        if not all(math.isfinite(v) and abs(v) <= 512.0 for v in original_offset):
            raise RuntimeError("Initial FFYL offset outside finite validated bounds")
        if original_offset != (0.0, 0.0, 0.0):
            outer = sys.modules.get(ARM_KEY)
            snapshot = getattr(outer, "early_offset_snapshot", None)
            expected_snapshot = (
                int(cam._get_address()),
                state_address,
                struct.unpack("<Q", read(int(cam._get_address()) + 0x3A48, 8))[0],
                original_offset,
            )
            if (
                outer is None
                or not outer.active
                or not outer.early_busy
                or struct.unpack_from("<I", outer.view_control.raw, 184)[0] != 2
                or snapshot != expected_snapshot
                or struct.unpack("<3d", read(state_address + 0xC0, 24))
                != original_offset
            ):
                raise RuntimeError(
                    "Nonzero initial offset lacks verified early GetPOV ownership"
                )
            report["early_entry_offset_adopted"] = True
        report["offset_override"] = {
            "original": list(original_offset),
            "requested": list(requested_camera_offset),
            "collision_added": True,
        }
        report["manager"] = str(cam._path_name())
        report["mod_tps_flag"] = getattr(mod, "_third_person_enabled", None)
        anchors = {
            "PushActorCameraMode": {
                "rva": 92365206,
                "hex": "564883ec504889d6488b059b97ee064831e0488944244848c744244000000000",
            },
            "PushActorCameraModeDef": {
                "rva": 142148746,
                "hex": "5657534881ecc00000000f29b424b00000004889d6488b059af4f6034831e048",
            },
            "GetActorCameraMode": {
                "rva": 96535664,
                "hex": "56574883ec384c89c64889d7488b05bdf4ae064831e0488944243048c7442428",
            },
        }
        for name, anchor in anchors.items():
            expected = bytes.fromhex(anchor["hex"])
            fn = find_object(
                "Function", "/Script/GbxGame.PlayerCameraModeManager:" + name
            )
            # +0xd8 is the measured executable-pointer metadata slot for these entries.
            if fn is None:
                raise RuntimeError("Camera function unavailable: " + name)
            ptr = struct.unpack("<Q", read(int(fn._get_address()) + 0xD8, 8))[0]
            if ptr != base + anchor["rva"]:
                raise RuntimeError(
                    name + ": measured entry slot changed; refusing follow-up"
                )
            if read(ptr, len(expected)) != expected:
                raise RuntimeError(name + ": entry bytes changed; refusing follow-up")
            report["functions"][name] = {"address": hex(ptr), "anchor_verified": True}
        layout_anchors = {
            "0x1449892": "4989c70f57ff0f29384889781048895818488d48400f2978200f297830e812c1",
            "0x1449d74": "4d893f49395f080f84bb000000f0ff430c4c89ff4883c708488b0f4885c90f85",
            "0x1449f72": "488b86483a00000f57d24885c07417488b40104885c0740e0f2ed67606f6401c",
        }
        for rva_text, expected_hex in layout_anchors.items():
            expected_bytes = bytes.fromhex(expected_hex)
            if read(base + int(rva_text, 16), len(expected_bytes)) != expected_bytes:
                raise RuntimeError("Runtime layout anchor mismatch: " + rva_text)
        report["layout_anchors_verified"] = layout_anchors
        if getattr(mod, "_third_person_enabled", None) is not True:
            raise RuntimeError("Legacy FFYL setup requires TPS")
        call_anchors = {
            "0x14498da": "e8cd56a1ff498b4710486348304885c9",
            "0x1449fbe": "e8e54aa1fff041ff4c2408752d498b04",
            "0x1449ff3": "e8b04aa1fff686f42e0000030f859101",
        }
        for rva, expected_hex in call_anchors.items():
            if (
                read(base + int(rva, 16), len(bytes.fromhex(expected_hex))).hex()
                != expected_hex
            ):
                raise RuntimeError("Camera activation callsite changed: " + rva)
        report["activation_call_anchors"] = call_anchors
        manager_address = int(cam._get_address())
        # Audited stack reader 0x1181315..0x118143d: header +0x39c0, stride 0x28.
        # Audited comparator at 0x11813ad reads the descriptor at +0x39a8.
        # Get implementation at 0x5c1059f returns the mode FName at +0x3a30.
        window = read(manager_address + 0x39A8, 0xB0)
        array_ptr, count, capacity = struct.unpack_from("<Qii", window, 0x18)
        report["manager_address"] = hex(manager_address)
        report["manager_window"] = {"offset": "0x39a8", "hex": window.hex()}
        report["stack"] = {
            "data": hex(array_ptr),
            "count": count,
            "capacity": capacity,
            "stride": "0x28",
            "items": [],
        }
        report["mode_fname_hex"] = window[0x88:0x90].hex()
        # Read the declared schema; constructor evidence supplies the definition path.
        fn = find_object(
            "Function", "/Script/GbxGame.PlayerCameraModeManager:PushActorCameraModeDef"
        )
        prop = next(p for p in fn._properties() if str(p.Name) == "CameraModeDef")
        meta = prop.Struct
        report["declared_def_schema"] = {
            "path": str(meta._path_name()),
            "size": int(meta.PropertySize),
            "fields": [],
        }
        if (
            report["declared_def_schema"]["path"] != "/Script/GbxGame.CameraModeDef"
            or int(meta.PropertySize) != 0x38
        ):
            raise RuntimeError("CameraModeDef schema changed")
        seen = set()
        for owner in [meta, *list(meta._superfields())]:
            for p in owner._properties():
                name = str(p.Name)
                if name in seen:
                    continue
                seen.add(name)
                field = {
                    "name": name,
                    "kind": str(p.Class.Name),
                    "offset": int(p.Offset_Internal),
                    "element_size": int(p.ElementSize),
                    "array_dim": int(p.ArrayDim),
                }
                if field["kind"] == "BoolProperty":
                    field["field_mask"] = int(p.FieldMask)
                report["declared_def_schema"]["fields"].append(field)
        refs = []
        report["base_descriptor_hex"] = window[:24].hex()
        if not 0 <= count <= capacity <= 256 or count > 64:
            raise RuntimeError("Stack count/capacity outside snapshot bounds")
        if count and not array_ptr:
            raise RuntimeError("Nonempty stack with null data")
        raw = read(array_ptr, count * 0x28) if count else b""
        for index in range(count):
            item = raw[index * 0x28 : (index + 1) * 0x28]
            report["stack"]["items"].append({"index": index, "hex": item.hex()})
            refs.append(("stack_" + str(index), item))
        # +0x3a48 is read at RVA 0x1449f72, followed by runtime +0x10.
        # Its role is recorded as a slot, not assumed to be the top stack entry.
        current = window[0xA0:0xB0]
        refs.append(("manager_slot_3a48", bytes(24) + current))
        report["runtime_candidates"] = []
        for label, item in refs:
            pointer, control = struct.unpack_from("<QQ", item, 0x18)
            row = {"source": label, "instance": hex(pointer), "control": hex(control)}
            report["runtime_candidates"].append(row)
            if not pointer:
                row["skipped"] = "Null runtime slot"
                continue
            try:
                runtime = read(pointer, 0x20)
                self_ptr, self_control, definition, transition = struct.unpack(
                    "<QQQQ", runtime
                )
                row.update(
                    runtime_header_hex=runtime.hex(),
                    definition=hex(definition),
                    transition=hex(transition),
                    self_reference_matches=self_ptr == pointer,
                    control_matches=self_control == control,
                )
                if self_ptr != pointer or not control or self_control != control:
                    raise RuntimeError(
                        "Runtime self/control references differ from measured layout"
                    )
                if not definition:
                    raise RuntimeError("Runtime has no mode definition")
                if hex(definition) not in report["definitions"]:
                    data = read(definition, 0x38)
                    result = {
                        "address": hex(definition),
                        "hex": data.hex(),
                        "fields": {},
                    }
                    report["definitions"][hex(definition)] = result
                    for field in report["declared_def_schema"]["fields"]:
                        name, offset, size = (
                            field["name"],
                            field["offset"],
                            field["element_size"],
                        )
                        if (
                            field["array_dim"] != 1
                            or offset < 0
                            or size <= 0
                            or offset + size > len(data)
                        ):
                            raise RuntimeError(
                                "Field outside definition bounds: " + name
                            )
                        value_bytes = data[offset : offset + size]
                        value = {"raw_hex": value_bytes.hex()}
                        kind = field["kind"]
                        if kind == "BoolProperty":
                            mask = field["field_mask"]
                            if not 0 < mask < (1 << (8 * size)):
                                raise RuntimeError("Bool mask outside field: " + name)
                            value.update(
                                mask=mask,
                                value=bool(
                                    int.from_bytes(value_bytes, "little") & mask
                                ),
                            )
                        elif kind == "FloatProperty" and size == 4:
                            value["value"] = struct.unpack("<f", value_bytes)[0]
                        elif kind == "EnumProperty":
                            value["numeric_value"] = int.from_bytes(
                                value_bytes, "little"
                            )
                        elif kind == "ArrayProperty" and size == 16:
                            ap, ac, am = struct.unpack("<Qii", value_bytes)
                            value.update(data=hex(ap), count=ac, capacity=am)
                        result["fields"][name] = value
                    result["unchanged_on_reread"] = read(definition, 0x38) == data
                    if not result["unchanged_on_reread"]:
                        report["limits"].append(
                            label + ": definition changed during read"
                        )
                row["runtime_unchanged"] = read(pointer, 0x20) == runtime
                if not row["runtime_unchanged"]:
                    report["limits"].append(label + ": runtime changed during read")
            except Exception as exc:
                row["read_error"] = str(exc)
                report["errors"].append({"scope": label, "error": str(exc)})
        after = read(manager_address + 0x39A8, 0xB0)
        report["manager_header_unchanged"] = after == window
        if after != window:
            report["limits"].append(
                "Manager changed during read; do not treat snapshot as coherent"
            )
        if count:
            report["stack_bytes_unchanged"] = read(array_ptr, count * 0x28) == raw
            if not report["stack_bytes_unchanged"]:
                report["limits"].append("Stack contents changed during read")

        if report["errors"] or report["limits"]:
            raise RuntimeError("Incomplete or incoherent snapshot; write refused")
        if count != 1 or len(report["definitions"]) != 1:
            raise RuntimeError(
                "Expected one active FFYL stack entry and one definition"
            )
        stack_row, active_row = report["runtime_candidates"]
        if (stack_row["instance"], stack_row["control"]) != (
            active_row["instance"],
            active_row["control"],
        ):
            raise RuntimeError("Pushed mode is not the active runtime")
        if raw[:8] != window[0x88:0x90]:
            raise RuntimeError("Active name differs from FFYL name")
        flag = next(
            f
            for f in report["declared_def_schema"]["fields"]
            if f["name"] == "bIsFirstPerson"
        )
        if (flag["kind"], flag["offset"], flag["element_size"], flag["field_mask"]) != (
            "BoolProperty",
            28,
            1,
            2,
        ):
            raise RuntimeError("First-person field layout changed")
        address = int(active_row["definition"], 16)
        current_def = read(address, 0x38)
        runtime_address = int(active_row["instance"], 16)
        show_flag = next(
            f
            for f in report["declared_def_schema"]["fields"]
            if f["name"] == "bShowViewModel"
        )
        if (
            show_flag["kind"],
            show_flag["offset"],
            show_flag["element_size"],
            show_flag["field_mask"],
        ) != ("BoolProperty", 28, 1, 4):
            raise RuntimeError("Viewmodel field layout changed")
        arm_owner = sys.modules.get(ARM_KEY)
        bridge = getattr(arm_owner, "bridge", None)
        prepared = (
            bridge is not None
            and bridge["address"] == address
            and current_def == bridge["expected"]
        )
        if not prepared:
            raise RuntimeError("Native preparation ownership missing")
        baseline_flag = 0x21
        if (
            current_def[28:30] != bytes([baseline_flag, 0])
            or struct.unpack_from("<i", current_def, 0x30)[0] != 12
        ):
            raise RuntimeError("Not the measured twelve-behavior FFYL baseline")
        runtime_layout_anchors = {
            "0x14498f0": "498d57204889942490000000498d573048899424980000004c8b6028488d0449",
            "0x1449a83": "41807e1101742a49635f388d430141894738413b473c760f488b8c2498000000",
            "0x1449adc": "488b0048c1e3044c89341848897c18084885ff740ef0ff4708f0ff4f080f8454",
        }
        for rva, expected_hex in runtime_layout_anchors.items():
            if (
                read(base + int(rva, 16), len(bytes.fromhex(expected_hex))).hex()
                != expected_hex
            ):
                raise RuntimeError("Runtime behavior layout changed")
        socket_meta = find_object(
            "ScriptStruct", "/Script/GbxGame.CameraModeBehavior_OffsetToSocket"
        )
        if (
            socket_meta is None
            or str(socket_meta._path_name())
            != "/Script/GbxGame.CameraModeBehavior_OffsetToSocket"
            or int(socket_meta.PropertySize) != 40
        ):
            raise RuntimeError("OffsetToSocket metadata unavailable/changed")
        socket_fields = {str(p.Name): p for p in socket_meta._properties()}
        rotation_field = socket_fields["bSetRotation"]
        if (
            str(rotation_field.Class.Name),
            int(rotation_field.Offset_Internal),
            int(rotation_field.ElementSize),
            int(rotation_field.ArrayDim),
            int(rotation_field.FieldMask),
        ) != ("BoolProperty", 24, 1, 1, 2):
            raise RuntimeError("Socket rotation field layout changed")
        behavior_header = read(runtime_address + 0x30, 16)
        behavior_array, behavior_count, behavior_capacity = struct.unpack(
            "<Qii", behavior_header
        )
        if (
            not behavior_array
            or not 0 < behavior_count <= behavior_capacity <= 256
            or behavior_count > 64
        ):
            raise RuntimeError("Post-view-target behavior list outside limits")
        behavior_entries = read(behavior_array, behavior_count * 16)
        targets = []
        for index in range(behavior_count):
            instance, control = struct.unpack_from("<QQ", behavior_entries, index * 16)
            if not instance or not control:
                raise RuntimeError("Null behavior pair")
            if struct.unpack("<Q", read(instance, 8))[0] == base + 0xB00EA00:
                targets.append((index, instance, control))
        if len(targets) != 1:
            raise RuntimeError("Expected one measured OffsetToSocket runtime copy")
        socket_index, socket_address, socket_control = targets[0]
        socket_original = read(socket_address, 40)
        outer = sys.modules.get(ARM_KEY)
        if outer is not None:
            records = outer.socket_records()
            owned = next(
                (
                    r
                    for r in records
                    if r["runtime"] == runtime_address
                    and r["object"] == socket_address
                    and r["control"] == socket_control
                ),
                None,
            )
            if owned is not None:
                expected = bytearray(owned["original"])
                expected[24] &= ~2
                if socket_original != bytes(expected):
                    raise RuntimeError("Early socket ownership differs")
                socket_original = owned["original"]
                report["early_socket_prepared"] = True
        if socket_original[24] != 2 or socket_original[28:36] != bytes.fromhex(
            "3202000000000000"
        ):
            raise RuntimeError("Not the measured rotation-only FFYL socket behavior")
        vt = base + 0xB00EA00
        if (
            struct.unpack("<Q", read(vt + 8, 8))[0] != base + 0x3C34938
            or struct.unpack("<Q", read(vt + 24, 8))[0] != base + 0x1874A9C
        ):
            raise RuntimeError("OffsetToSocket getter/update slots changed")
        getter_code = read(base + 0x3C34938, 21)
        if getter_code[:7] != bytes.fromhex("4883ec28488b05") or getter_code[
            11:
        ] != bytes.fromhex("4885c074054883c428c3"):
            raise RuntimeError("OffsetToSocket type getter changed")
        type_cache = base + 0x3C34938 + 11 + struct.unpack_from("<i", getter_code, 7)[0]
        if not base <= type_cache <= base + image_size - 8 or struct.unpack(
            "<Q", read(type_cache, 8)
        )[0] != int(socket_meta._get_address()):
            raise RuntimeError("OffsetToSocket cached metadata mismatch")
        if (
            read(base + 0x1874A9C, 32).hex()
            != "5657534881ece0000000660f29b424d00000004c89c64889cf488b0584aee80a"
        ):
            raise RuntimeError("OffsetToSocket Update anchor changed")
        socket_expected = (
            socket_original[:24]
            + bytes([socket_original[24] & ~2])
            + socket_original[25:]
        )
        report["socket_override"] = {
            "address": hex(socket_address),
            "runtime": hex(runtime_address),
            "control": hex(socket_control),
            "field": "bSetRotation",
            "offset": 24,
            "mask": 2,
            "original_hex": socket_original.hex(),
            "expected_hex": socket_expected.hex(),
            "target": "Live runtime copy only; shared behavior definition unchanged",
        }

        original = current_def
        desired = original[28] & ~6
        expected_after = original[:28] + bytes([desired]) + original[29:]
        report["action"] = "FFYL_PERSPECTIVE_APPLY"
        if (
            read(manager_address + 0x39A8, 0xB0) != window
            or read(array_ptr, 0x28) != raw
        ):
            raise RuntimeError("Manager/stack changed before write")
        if read(runtime_address, 0x20).hex() != active_row["runtime_header_hex"]:
            raise RuntimeError("Runtime changed before write")
        if read(address, 0x38) != current_def:
            raise RuntimeError("Definition changed before write")
        kernel.WriteProcessMemory.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel.WriteProcessMemory.restype = ctypes.c_int

        def write_byte(value):
            buf = ctypes.c_ubyte(value)
            got = ctypes.c_size_t()
            ok = kernel.WriteProcessMemory(
                handle, address + 28, ctypes.byref(buf), 1, ctypes.byref(got)
            )
            report["game_writes"] += int(got.value)
            if not ok or got.value != 1:
                raise OSError("One-byte write failed: " + str(ctypes.get_last_error()))
            if read(address + 28, 1) != bytes([value]):
                raise RuntimeError("Flag-byte readback mismatch")

        state = types.ModuleType(STATE_KEY)
        state.report = report
        state.active = False
        state.offset_owned = False
        state.socket_owned = False
        state.hooks = []
        state.handoff = False
        state.frames = 0
        state.started = time.perf_counter()
        state.base = base
        state.original = original
        state.expected_after = expected_after
        state.address = address
        state.identity = runtime_identity
        state.restore = None
        sys.modules[STATE_KEY] = state

        def save(label):
            if report["errors"]:
                logging.error(f'{TAG} collision {label}: {report["errors"]}')

        def socket_is_owned():
            fresh = mod._get_runtime()
            if (
                tuple(int(x._get_address()) if x is not None else 0 for x in fresh)
                != state.identity
            ):
                return False
            if str(fresh[2].GetActorCameraMode(fresh[1])) != "FFYL":
                return False
            live_window = read(manager_address + 0x39A8, 0xB0)
            if struct.unpack_from("<QQ", live_window, 0xA0) != (
                runtime_address,
                int(active_row["control"], 16),
            ):
                return False
            if (
                read(runtime_address, 0x18).hex()
                != active_row["runtime_header_hex"][:48]
            ):
                return False
            live_header = read(runtime_address + 0x30, 16)
            live_array, live_count, live_capacity = struct.unpack("<Qii", live_header)
            if (
                not live_array
                or not 0 < live_count <= live_capacity <= 256
                or live_count > 64
            ):
                raise RuntimeError("Live socket owner list outside bounds")
            live_entries = read(live_array, live_count * 16)
            matches = sum(
                struct.unpack_from("<QQ", live_entries, i * 16)
                == (socket_address, socket_control)
                for i in range(live_count)
            )
            return matches == 1

        def write_socket_byte(value):
            buf = ctypes.c_ubyte(value)
            got = ctypes.c_size_t()
            ok = kernel.WriteProcessMemory(
                handle, socket_address + 24, ctypes.byref(buf), 1, ctypes.byref(got)
            )
            report["game_writes"] += int(got.value)
            if (
                not ok
                or got.value != 1
                or read(socket_address + 24, 1) != bytes([value])
            ):
                raise RuntimeError("Socket flag write/readback failed")

        def default_offset_allowed(fresh):
            outer = sys.modules.get(ARM_KEY)
            if not state.handoff or outer is None or not outer.active:
                return False
            return outer.default_offset_owner(fresh)

        def set_offset(values):
            fresh = mod._get_runtime()
            if (
                tuple(int(x._get_address()) if x is not None else 0 for x in fresh)
                != state.identity
            ):
                raise RuntimeError("Offset runtime identity changed")
            mode = str(fresh[2].GetActorCameraMode(fresh[1]))
            if mode != "FFYL" and not (
                mode == "Default" and default_offset_allowed(fresh)
            ):
                raise RuntimeError("Offset mode outside owned FFYL/Second Wind Default")
            report["sdk_offset_writes"] += 1
            if not mod._set_camera_offset(*values):
                raise RuntimeError("GU offset setter refused")
            readback = tuple(
                float(getattr(fresh[2].CameraModeState.CameraLocationOffset, axis))
                for axis in ("X", "Y", "Z")
            )
            if readback != values:
                raise RuntimeError("SDK offset readback differs")

        def collision_offset():
            current = mod._get_runtime()
            if (
                tuple(int(x._get_address()) if x is not None else 0 for x in current)
                != state.identity
            ):
                raise RuntimeError("Collision runtime changed")
            pc, local_pawn, manager = current
            live = manager.CameraModeState
            if int(live._get_address()) != state_address:
                raise RuntimeError("Collision camera-state replaced")
            data = read(state_address + 0x30, 0xC0)
            origin = struct.unpack_from("<3d", data, 0)
            angles = struct.unpack_from("<3d", data, 24)
            offsets = {
                name: list(struct.unpack_from("<3d", data, off - 0x30))
                for name, off in (
                    ("AbsoluteLocationOffset", 0x70),
                    ("BaseLocationOffset", 0x88),
                    ("BaseRotationOffset", 0xA0),
                    ("CameraRotationOffset", 0xD8),
                )
            }
            extras = tuple(v for values in offsets.values() for v in values)
            spatial = {
                "frame": state.frames,
                "elapsed_s": time.perf_counter() - state.started,
                "mode": str(manager.GetActorCameraMode(local_pawn)),
                "transitioning": bool(live.bIsTransitioning),
                "show_viewmodel": bool(live.bShowViewModel),
                "origin": list(origin),
                "angles": list(angles),
                "offsets": offsets,
                "raw_state_30_f0_hex": data.hex(),
                "mod_flags": {
                    name: bool(getattr(mod, name, False))
                    for name in (
                        "_ads_active",
                        "_slide_active",
                        "_ladder_active",
                        "_vehicle_camera_active",
                        "_native_fault",
                    )
                },
                "attach_component": (
                    str(manager.CameraModeInputs.AttachComponent._path_name())
                    if manager.CameraModeInputs.AttachComponent is not None
                    else None
                ),
            }
            spatial["nonzero_fields"] = [
                name
                for name, values in offsets.items()
                if any(not math.isfinite(v) or abs(v) > 1e-8 for v in values)
            ]
            unsupported = [
                name
                for name in spatial["nonzero_fields"]
                if name != "BaseRotationOffset"
            ]
            base_rotation = tuple(offsets["BaseRotationOffset"])
            if any(not math.isfinite(v) or abs(v) > 45.0 for v in base_rotation):
                unsupported.append(
                    "BaseRotationOffset outside +/-45 degree validated bounds"
                )
            if (
                not all(math.isfinite(v) for v in origin + angles + extras)
                or unsupported
            ):
                spatial["unsupported_fields"] = unsupported
                report["spatial_guard_failure"] = spatial
                report["spatial_guard_previous"] = getattr(
                    state, "previous_spatial", None
                )
                raise RuntimeError(
                    "Unsupported FFYL spatial offsets; composition refused: "
                    + ",".join(unsupported)
                )
            state.previous_spatial = spatial
            inputs = live.Inputs
            if (
                inputs is None
                or int(inputs._get_address())
                != struct.unpack("<Q", read(state_address + 0x28, 8))[0]
            ):
                raise RuntimeError("Collision input identity changed")
            v = inputs.CollisionSafeLocation
            start = (float(v.X), float(v.Y), float(v.Z))
            rotation = compose(basis(angles), basis(base_rotation))
            delta = multiply(rotation, requested_camera_offset)
            end = tuple(a + b for a, b in zip(origin, delta))
            if (
                not all(math.isfinite(v) for v in start + end)
                or math.dist(start, origin) > 512
                or math.dist(start, end) > 1024
            ):
                raise RuntimeError("Collision geometry outside validated bounds")

            def vector(v):
                return make_struct("Vector", X=v[0], Y=v[1], Z=v[2])

            started = time.perf_counter()
            # Character ignore provider, called only for this owned FFYL camera
            # sweep. It never changes weapon/use traces or collision responses.
            ignored = [local_pawn]
            provider = getattr(mod, "_ffyl_camera_ignore_provider", None)
            if callable(provider) and spatial["mode"] == "FFYL":
                extra = provider(state.identity)
                if not isinstance(extra, tuple) or len(extra) > 128:
                    raise RuntimeError(
                        "FFYL camera ignore provider returned invalid list"
                    )
                ignored.extend(extra)
            result = library.SphereTraceSingle(
                pc,
                vector(start),
                vector(end),
                10.0,
                camera_query,
                True,
                ignored,
                0,
                make_struct("HitResult"),
                True,
                make_struct("LinearColor"),
                make_struct("LinearColor"),
                0.0,
            )
            if (
                not isinstance(result, (tuple, list))
                or len(result) < 2
                or not isinstance(result[0], bool)
            ):
                raise RuntimeError("Sphere trace return format changed")
            hit = result[0]
            out = requested_camera_offset
            fraction = 1.0
            if hit:
                value = result[-1]
                if bool(value.bStartPenetrating):
                    # Restore only our positional extension for this frame; retain perspective ownership.
                    # Remove our positional extension, including any carried entry offset.
                    # Keep the saved entry snapshot only for rollback, not collision fallback.
                    out = (0.0, 0.0, 0.0)
                    fraction = None
                    report["collision"]["penetration_fallback_frames"] = (
                        report["collision"].get("penetration_fallback_frames", 0) + 1
                    )
                else:
                    fraction = float(value.Time)
                    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
                        raise RuntimeError("Invalid collision hit fraction")
                    out = local_hit(origin, rotation, start, end, fraction)
                    if any(not math.isfinite(x) or abs(x) > 512 for x in out):
                        raise RuntimeError("Collision correction outside bounds")
                    # Reject disagreement between SDK hit centre and returned travel fraction.
                    v = value.Location
                    centre = (float(v.X), float(v.Y), float(v.Z))
                    expected = tuple(a + (b - a) * fraction for a, b in zip(start, end))
                    if (
                        not all(math.isfinite(x) for x in centre)
                        or math.dist(centre, expected) > 2
                    ):
                        raise RuntimeError(
                            "Collision hit centre disagrees with travel fraction"
                        )
            fresh = mod._get_runtime()
            if (
                tuple(int(x._get_address()) if x is not None else 0 for x in fresh)
                != state.identity
                or str(manager.GetActorCameraMode(local_pawn)) != spatial["mode"]
                or (
                    spatial["mode"] != "FFYL"
                    and not (
                        (spatial["mode"] == "Default" and default_offset_allowed(fresh))
                        or (
                            spatial["mode"] == "ThirdPerson"
                            and tps_handoff_allowed(fresh)
                        )
                    )
                )
            ):
                raise RuntimeError("Runtime changed during collision trace")
            if read(state_address + 0x30, 0xC0) != data:
                raise RuntimeError("Camera state changed during collision trace")
            row = {
                "frame": state.frames,
                "start": start,
                "origin": origin,
                "angles": angles,
                "desired": end,
                "base_rotation_offset": base_rotation,
                "hit": hit,
                "fraction": fraction,
                "baseline_fallback": hit and fraction is None,
                "offset": out,
                "cost_ms": (time.perf_counter() - started) * 1000,
            }
            cr = report["collision"]
            cr["queries"] += 1
            cr["hits"] += int(hit)
            has_rotation = any(abs(v) > 1e-8 for v in base_rotation)
            cr["base_rotation_frames"] = cr.get("base_rotation_frames", 0) + int(
                has_rotation
            )
            cr["base_rotation_abs_max"] = max(
                cr.get("base_rotation_abs_max", 0), *(abs(v) for v in base_rotation)
            )
            if len(cr["rows"]) < 40 and (
                state.frames < 3
                or state.frames % 15 == 0
                or hit != getattr(state, "last_hit", None)
                or has_rotation != getattr(state, "last_base_rotation", False)
                or (hit and fraction is None)
                != getattr(state, "last_penetrating", False)
            ):
                cr["rows"].append(row)
            state.last_penetrating = hit and fraction is None
            state.last_hit = hit
            state.last_base_rotation = has_rotation
            return out

        def tps_handoff_allowed(fresh):
            outer = sys.modules.get(ARM_KEY)
            if (
                not state.handoff
                or outer is None
                or not outer.active
                or not outer.early_busy
            ):
                return False
            if struct.unpack_from("<I", outer.view_control, 192)[0] != 2:
                return False
            if (
                tuple(int(x._get_address()) if x is not None else 0 for x in fresh)
                != state.identity
            ):
                return False
            if str(fresh[2].GetActorCameraMode(fresh[1])) != "ThirdPerson":
                return False
            if any(
                bool(getattr(mod, k, False))
                for k in (
                    "_ads_active",
                    "_slide_active",
                    "_ladder_active",
                    "_vehicle_camera_active",
                    "_native_fault",
                )
            ):
                return False
            if mod._native_active() or fresh[2].CameraModeState.bShowViewModel:
                return False
            owner = mod._camera_stack_owner
            return (
                owner.get("owned")
                and owner.get("pawn_address") == state.identity[1]
                and owner.get("manager_address") == state.identity[2]
                and mod._ffyl_camera_stack_has_single_tps(fresh[2])
            )

        def apply_tps_handoff():
            fresh = mod._get_runtime()
            if not state.active or not tps_handoff_allowed(fresh):
                return False
            original = tuple(
                float(getattr(fresh[2].CameraModeState.CameraLocationOffset, a))
                for a in ("X", "Y", "Z")
            )
            configured = tuple(
                float(getattr(mod, "camera_offset_" + a).value) for a in ("x", "y", "z")
            )
            if not all(
                math.isfinite(v) and abs(v) <= 512 for v in original + configured
            ):
                raise RuntimeError("TPS handoff offset bounds differ")
            # GetPOV receives the already composed native CameraLocationOffset.
            # Preserve the captured full TPS target, freshly collision-checked.
            # Menu offsets are recorded for diagnosis, never written at this stage.
            swept = collision_offset()
            values = tuple(swept)
            if not all(math.isfinite(v) and abs(v) <= 512 for v in values):
                raise RuntimeError("TPS swept SDK offset bounds differ")
            if not tps_handoff_allowed(mod._get_runtime()):
                raise RuntimeError("TPS ownership changed after sweep")
            try:
                report["sdk_offset_writes"] += 1
                if not mod._set_camera_offset(*values):
                    raise RuntimeError("TPS handoff setter refused")
                actual = tuple(
                    float(getattr(fresh[2].CameraModeState.CameraLocationOffset, a))
                    for a in ("X", "Y", "Z")
                )
                if actual != values:
                    raise RuntimeError("TPS handoff readback differs")
            except BaseException:
                if tps_handoff_allowed(mod._get_runtime()):
                    mod._set_camera_offset(*original)
                raise
            report["tps_early_handoff"] = {
                "original": original,
                "configured": configured,
                "swept_native": swept,
                "written": values,
                "coordinate_space": "composed_native_offset",
                "before_GetPOV": True,
            }
            return True

        state.apply_tps_handoff = apply_tps_handoff

        def sample(label):
            current = mod._get_runtime()
            row = {
                "label": label,
                "elapsed_s": time.perf_counter() - state.started,
                "identity": [
                    int(x._get_address()) if x is not None else 0 for x in current
                ],
            }
            if all(x is not None for x in current):
                _, current_pawn, manager = current
                cs = manager.CameraModeState
                row.update(
                    mode=str(manager.GetActorCameraMode(current_pawn)),
                    show_viewmodel=bool(cs.bShowViewModel),
                    transitioning=bool(cs.bIsTransitioning),
                    attach_component=(
                        str(manager.CameraModeInputs.AttachComponent._path_name())
                        if manager.CameraModeInputs.AttachComponent is not None
                        else None
                    ),
                    offset=[
                        float(getattr(cs.CameraLocationOffset, axis))
                        for axis in ("X", "Y", "Z")
                    ],
                )
            if len(report["samples"]) < 32:
                report["samples"].append(row)
            return row

        def cleanup():
            failures = []
            for path, kind, name in list(state.hooks):
                try:
                    if has_hook(path, kind, name):
                        remove_hook(path, kind, name)
                    if has_hook(path, kind, name):
                        raise RuntimeError("Owned hook still installed")
                except Exception as exc:
                    failures.append({"hook": name, "error": str(exc)})
            report["hook_removal_errors"] = failures
            if not failures:
                state.hooks.clear()
                if sys.modules.get(STATE_KEY) is state:
                    sys.modules.pop(STATE_KEY, None)

        def restore(reason):
            socket_error = None
            if state.socket_owned:
                try:
                    if socket_is_owned():
                        live_socket = read(socket_address, 40)
                        if live_socket not in (socket_original, socket_expected):
                            raise RuntimeError(
                                "Socket behavior changed outside owned mask; restore refused"
                            )
                        if live_socket != socket_original:
                            write_socket_byte(socket_original[24])
                        if read(socket_address, 40) != socket_original:
                            raise RuntimeError("Socket restore readback differs")
                        report["socket_restore_verified"] = True
                    else:
                        report["socket_restore_skipped"] = (
                            "Runtime/list retired; saved behavior address not dereferenced or written"
                        )
                    state.socket_owned = False
                except Exception as exc:
                    socket_error = str(exc)
                    report["errors"].append(
                        {"scope": "socket_restore", "error": socket_error}
                    )
            if getattr(state, "default_offset_owned", False):
                try:
                    fresh = mod._get_runtime()
                    if (
                        tuple(
                            int(x._get_address()) if x is not None else 0 for x in fresh
                        )
                        == state.identity
                        and str(fresh[2].GetActorCameraMode(fresh[1])) == "Default"
                        and struct.unpack("<Q", read(manager_address + 0x3A48, 8))[0]
                        == state.default_offset_runtime
                    ):
                        v = fresh[2].CameraModeState.CameraLocationOffset
                        live = tuple(float(getattr(v, a)) for a in ("X", "Y", "Z"))
                        if live not in (
                            state.default_offset_original,
                            getattr(
                                state,
                                "default_offset_last",
                                state.default_offset_original,
                            ),
                        ):
                            raise RuntimeError(
                                "Default offset changed outside ownership"
                            )
                        if not mod._set_camera_offset(*state.default_offset_original):
                            raise RuntimeError("Default offset restore refused")
                        v = fresh[2].CameraModeState.CameraLocationOffset
                        if (
                            tuple(float(getattr(v, a)) for a in ("X", "Y", "Z"))
                            != state.default_offset_original
                        ):
                            raise RuntimeError(
                                "Default offset restore readback differs"
                            )
                        report["default_offset_restore_verified"] = True
                    else:
                        report["default_offset_restore_skipped"] = (
                            "Default runtime retired; no stale offset write"
                        )
                    state.default_offset_owned = False
                except Exception as exc:
                    report["errors"].append(
                        {"scope": "default_offset_restore", "error": repr(exc)}
                    )
                    return
            offset_error = None
            if state.offset_owned:
                try:
                    fresh = mod._get_runtime()
                    same_identity = (
                        tuple(
                            int(x._get_address()) if x is not None else 0 for x in fresh
                        )
                        == state.identity
                    )
                    same_mode = (
                        same_identity
                        and str(fresh[2].GetActorCameraMode(fresh[1])) == "FFYL"
                    )
                    if same_mode:
                        set_offset(original_offset)
                        report["offset_restore_verified"] = True
                    else:
                        # A new mode/runtime owns camera state now. Do not clear its offsets.
                        report["offset_restore_skipped"] = (
                            "Runtime or FFYL mode retired; no stale offset write"
                        )
                    state.offset_owned = False
                except Exception as exc:
                    offset_error = str(exc)
                    report["errors"].append(
                        {"scope": "offset_restore", "error": offset_error}
                    )
            try:
                if state.active:
                    # This is a shared Nexus definition, not a retired runtime.
                    # ReadProcessMemory and whole-definition comparison precede
                    # restoration; never chase saved pawn/runtime pointers here.
                    live = read(address, 0x38)
                    if live not in (original, expected_after):
                        raise RuntimeError(
                            "FFYL definition changed outside owned masks; restore refused"
                        )
                    if live != original:
                        write_byte(original[28])
                    if read(address, 0x38) != original:
                        raise RuntimeError("Original FFYL definition readback differs")
                    state.active = False
                    report["restore_verified"] = True
                if not state.offset_owned and not state.socket_owned:
                    cleanup()
                if socket_error is not None:
                    raise RuntimeError(
                        "Definition restored; socket restore failed: " + socket_error
                    )
                if offset_error is not None:
                    raise RuntimeError(
                        "Camera definition restored; offset restore failed: "
                        + offset_error
                    )
                report.update(
                    action="FFYL_PERSPECTIVE_RESTORE",
                    restore_reason=reason,
                    restored=not state.active
                    and not state.offset_owned
                    and not state.socket_owned,
                    frames=state.frames,
                )
                save("restore")
            except Exception as exc:
                report["errors"].append(
                    {"scope": "restore", "error": f"{type(exc).__name__}: {exc}"}
                )
                logging.error(
                    f"{TAG} RESTORE_FAILED {exc}; restart BL4 before continuing"
                )
                save("restore_failed")

        state.restore = restore

        def frame(obj, args, ret, func):
            if not state.active:
                return
            try:
                state.frames += 1
                current = mod._get_runtime()
                current_identity = tuple(
                    int(x._get_address()) if x is not None else 0 for x in current
                )
                if current_identity != state.identity:
                    restore("runtime_changed")
                    return
                mode = str(current[2].GetActorCameraMode(current[1]))
                if (
                    state.handoff
                    and (
                        mode in ("FFYL", "Default")
                        or (
                            mode == "ThirdPerson"
                            and bool(current[2].CameraModeState.bIsTransitioning)
                        )
                    )
                    and mod._third_person_enabled
                ):
                    # Keep a character-relative, freshly swept extension in Default.
                    # No saved world point and no access to retired FFYL behaviors.
                    if mode == "Default":
                        if not default_offset_allowed(current):
                            raise RuntimeError("Default handoff ownership refused")
                        current_runtime = struct.unpack(
                            "<Q", read(manager_address + 0x3A48, 8)
                        )[0]
                        if not getattr(state, "default_offset_owned", False):
                            v = current[2].CameraModeState.CameraLocationOffset
                            state.default_offset_original = tuple(
                                float(getattr(v, a)) for a in ("X", "Y", "Z")
                            )
                            state.default_offset_runtime = current_runtime
                            state.default_offset_owned = True
                        elif current_runtime != state.default_offset_runtime:
                            raise RuntimeError(
                                "Default runtime changed during distance handoff"
                            )
                        values = collision_offset()
                        set_offset(values)
                        state.default_offset_last = values
                        report["default_distance_handoff_last"] = dict(
                            frame=state.frames, offset=list(values)
                        )
                    return
                if mode != "FFYL" or not mod._third_person_enabled:
                    restore("ffyl_mode_or_mod_state_changed")
                    return
                if not socket_is_owned():
                    restore("behavior_owner_retired")
                    return
                if read(socket_address, 40) != socket_expected:
                    raise RuntimeError(
                        "Socket behavior changed during owned camera operation"
                    )
                set_offset(collision_offset())
                if state.frames == 1 or state.frames % 30 == 0:
                    sample("frame")
            except Exception as exc:
                report["errors"].append({"scope": "frame", "error": str(exc)})
                restore("callback_error")

        def ended(obj, args, ret, func):
            try:
                reason = str(getattr(args, "Reason", ""))
                current = mod._get_runtime()
                local_identity = (
                    tuple(
                        int(x._get_address()) if x is not None else 0 for x in current
                    )
                    == state.identity
                )
                mode = (
                    str(current[2].GetActorCameraMode(current[1]))
                    if local_identity
                    else None
                )
                if (
                    state.active
                    and state.handoff
                    and local_identity
                    and (
                        mode in ("FFYL", "Default")
                        or (
                            mode == "ThirdPerson"
                            and bool(current[2].CameraModeState.bIsTransitioning)
                        )
                    )
                ):
                    report.setdefault("duplicate_exit_holds", []).append(
                        {
                            "reason": reason,
                            "mode": mode,
                            "elapsed_s": time.perf_counter() - state.started,
                        }
                    )
                    sample("duplicate_exit_hold")
                    return
                local_ffyl = local_identity and mode == "FFYL"
                if (
                    state.active
                    and local_ffyl
                    and (reason == "2" or "SecondWind" in reason)
                ):
                    state.handoff = True
                    report["secondwind_handoff"] = {
                        "reason": reason,
                        "elapsed_s": time.perf_counter() - state.started,
                    }
                    sample("secondwind_hold_pre")
                    save("handoff")
                    return
            except Exception as exc:
                report["errors"].append({"scope": "handoff", "error": str(exc)})
            # Other exits conservatively restore immediately.

            if state.active:
                try:
                    sample("downed_end_pre")
                except Exception as exc:
                    report["errors"].append({"scope": "exit_sample", "error": str(exc)})
                finally:
                    restore("downed_end_pre")

        def restarting(obj, args, ret, func):
            if state.active and int(obj._get_address()) == state.identity[0]:
                restore("local_client_restart_pre")

        plans = [
            (mod.FFYL_EARLY_ENDED_FUNCTION, Type.PRE, "bl4tps_ffyl_beta.ended", ended),
            (
                mod.CLIENT_RESTART_FUNCTION,
                Type.PRE,
                "bl4tps_ffyl_beta.restart",
                restarting,
            ),
            (
                mod.FIRST_PERSON_ANIM_HOOK,
                Type.POST_UNCONDITIONAL,
                "bl4tps_ffyl_beta.frame",
                frame,
            ),
        ]
        try:
            for path, kind, name, callback in plans:
                if has_hook(path, kind, name):
                    raise RuntimeError(
                        "Untracked legacy-ffyl-camera hook already installed: " + name
                    )
                state.hooks.append((path, kind, name))
                add_hook(path, kind, name, callback)
                if not has_hook(path, kind, name):
                    raise RuntimeError("Owned restore hook refused: " + name)
            report["sdk_hooks"] = len(state.hooks)
            sample("before_apply")
            initial_offset = collision_offset()
            if (
                tuple(int(x._get_address()) for x in mod._get_runtime())
                != runtime_identity
            ):
                raise RuntimeError("Runtime changed before apply")
            if (
                str(cam.GetActorCameraMode(pawn)) != "FFYL"
                or (
                    bool(cam.CameraModeState.bIsTransitioning)
                    and not owned_early_transition()
                )
                or mod._native_fault
                or mod._native_active()
            ):
                raise RuntimeError("FFYL/native state changed before apply")
            if (
                read(manager_address + 0x39A8, 0xB0) != window
                or read(array_ptr, 0x28) != raw
                or read(address, 0x38) != original
            ):
                raise RuntimeError("Camera/definition changed before apply")
            if not socket_is_owned() or read(socket_address, 40) != (
                socket_expected
                if report.get("early_socket_prepared")
                else socket_original
            ):
                raise RuntimeError("Socket owner changed before apply")
            state.active = True  # Retain rollback ownership before touching the byte.
            write_byte(desired)
            if read(address, 0x38) != expected_after:
                raise RuntimeError("Definition differs from expected two-mask change")
            state.socket_owned = True
            write_socket_byte(socket_expected[24])
            if read(socket_address, 40) != socket_expected:
                raise RuntimeError(
                    "Socket behavior differs from expected single-bit change"
                )
            state.offset_owned = True
            set_offset(initial_offset)
            sample("after_apply")
            report.update(
                ab_verified=True,
                after_definition_hex=expected_after.hex(),
                ab_target={
                    "address": hex(address),
                    "offset": 28,
                    "mask": 6,
                    "before_byte": original[28],
                    "requested_byte": desired,
                    "shared_definition_modified": True,
                    "activation_repeated": False,
                },
                transition_control="game_state",
            )
            save("apply")
        except Exception:
            restore("setup_or_apply_rollback")
            raise

    except Exception as exc:
        report["errors"].append(
            {"scope": "setup", "error": f"{type(exc).__name__}: {exc}"}
        )
    if report["errors"]:
        logging.error(f'{TAG} collision refused: {report["errors"]}')


import hashlib

APPLY_RVA = 15067816
APPLY_ORIGINAL = b"AWAVVWSH\x83\xec`\x0f)t$P"
APPLY_SHA256 = "97691bfc1c0bfe3a4b62cdab037914f829043565e585cdae1bd8f3108eb7f192"
APPLY_PREFIX = (
    b'\x9cPARASI\xba""""""""I9\n\x0f'
    b"\x85\x12\x01\x00\x00A\x83z\x08\x01\x0f\x85\x07\x01\x00\x00I\xc7\xc3\x01"
    b"\x00\x00\x00\xf0M\x0f\xc1Z\x10I\x81\xfb\x80\x00\x00\x00\x0f\x83\xed\x00"
    b"\x00\x00I\xc1\xe3\x07O\x8d\\\x1a\x18I\x89\x13H\x8b\x810:\x00"
    b"\x00I\x89C\x08H\x8b\x81H:\x00\x00I\x89C\x18fH\x0f~"
    b"\xd0I\x89C M\x89K(Hc\x81\xc89\x00\x00I\x89C0"
    b"H\x85\xc0t)H\x83\xf8@w,;\x81\xcc9\x00\x00w$H"
    b"k\xc0(L\x8b\x91\xc09\x00\x00I\x81\xfa\x00\x00\x01\x00r\x10I"
    b"\x8bD\x02\xd8\xeb\x0bH\x8b\x81\xa89\x00\x00\xeb\x021\xc0I\x89C"
    b"\x10I\xc7C@\x02\x00\x00\x00I\xc7CP\xff\xff\xff\xffI\xc7C"
    b"h\xff\xff\xff\xffH\x8b\x81\xd89\x00\x00H\x85\xc0t\x0b\x0f\xb6\x80"
    b"L\x01\x00\x00I\x89CpI\x8bC\x18H\x85\xc0t\x15H\x8b@"
    b"\x10I\x89CHH\x85\xc0t\x08\x0f\xb6@\x1cI\x89CPH\x8b"
    b"\x02I\x89CXH\x85\xc0t\x15H\x8b@\x10I\x89C`H\x85"
    b"\xc0t\x08\x0f\xb6@\x1cI\x89ChI\xc7C8\x01\x00\x00\x00A"
    b"[AZX\x9d"
)
APPLY_PREFIX_SHA256 = "7913cc7cfa67c499947f7444fac6c8de4fd06fdd4ea62218522d43a356208297"
MODIFY_PREFIX = (
    b"\x9cPAPARASATAUAVI\xbe3333"
    b"3333I9\x0e\x0f\x85o\x03\x00\x00A\x83~\x08\x01\x0f\x85"
    b'd\x03\x00\x00I\xffF\x10L\x8b"M\x85\xe4\x0f\x84T\x03\x00\x00'
    b"M9$$\x0f\x85:\x03\x00\x00H\x8bB\x08H\x85\xc0\x0f\x84-"
    b'\x03\x00\x00I9D$\x08\x0f\x85"\x03\x00\x00M\x8bl$\x10M'
    b"\x85\xed\x0f\x84\x14\x03\x00\x00Hc\x81\xc89\x00\x00H\x85\xc0\x0f\x84"
    b"\xb8\x01\x00\x00H\x83\xf8@\x0f\x87\n\x03\x00\x00;\x81\xcc9\x00\x00"
    b"\x0f\x87\xee\x02\x00\x00Hk\xc0(L\x8b\x91\xc09\x00\x00I\x81\xfa"
    b"\x00\x00\x01\x00\x0f\x82\xd6\x02\x00\x00I\x8bD\x02\xd8I;\x86\xc8\x00"
    b"\x00\x00\x0f\x85\xd4\x02\x00\x00A\x83}0\x0c\x0f\x85\xb9\x02\x00\x00M"
    b"\x8bT$ Mc\\$(M\x85\xdb\x0f\x8e\xa6\x02\x00\x00I\x83"
    b"\xfb@\x0f\x87\x9c\x02\x00\x00E;\\$,\x0f\x87\x91\x02\x00\x00M"
    b"\x85\xd2\x0f\x84\x88\x02\x00\x00E1\xc0I\x8b\x02H\x85\xc0\x0f\x84y"
    b"\x02\x00\x00I\x83z\x08\x00\x0f\x84n\x02\x00\x00H\x8b\x00I;\x86"
    b"\xc0\x00\x00\x00u\x03A\xff\xc0I\x83\xc2\x10I\xff\xcbu\xd1A\x83"
    b"\xf8\x01\x0f\x85L\x02\x00\x00I\x83~ \x00ueA\x80}\x1c'"
    b"\x0f\x85:\x02\x00\x00A\x80}\x1d\x00\x0f\x85/\x02\x00\x00A\x81}"
    b"\x18\x9a\x99\x19?\x0f\x85!\x02\x00\x00M\x89n I\x8bE\x00I"
    b"\x89F@I\x8bE\x08I\x89FHI\x8bE\x10I\x89FPI"
    b"\x8bE\x18I\x89FXI\x8bE I\x89F`I\x8bE(I"
    b"\x89FhI\x8bE0I\x89Fp\xe9\x86\x00\x00\x00M9n "
    b"\x0f\x85\xd6\x01\x00\x00I\x8bF@I9E\x00\x0f\x85\xc8\x01\x00\x00"
    b"I\x8bFHI9E\x08\x0f\x85\xba\x01\x00\x00I\x8bFPI9"
    b"E\x10\x0f\x85\xac\x01\x00\x00I\x8bFXI\xba\xff\xff\xff\xff\x00\xff"
    b"\xff\xffL!\xd0I\xba\x00\x00\x00\x00!\x00\x00\x00L\t\xd0I9"
    b"E\x18\x0f\x85\x84\x01\x00\x00I\x8bF`I9E \x0f\x85v\x01"
    b"\x00\x00I\x8bFhI9E(\x0f\x85h\x01\x00\x00I\x8bFp"
    b"I9E0\x0f\x85Z\x01\x00\x00A\xc6E\x1c!I\xffF0\xe9"
    b"\\\x01\x00\x00A\x83~\x0c\x01\x0f\x85Q\x01\x00\x00H\x8b\x81\xa89"
    b"\x00\x00I;\x86\xd0\x00\x00\x00\x0f\x85=\x01\x00\x00H\x8b\x81H:"
    b"\x00\x00H\x85\xc0\x0f\x84-\x01\x00\x00H\x8b@\x10I;F \x0f"
    b"\x85\x1f\x01\x00\x00I\x83~ \x00\x0f\x84\x14\x01\x00\x00I\x83~("
    b"\x00usA\x80}\x1c'\x0f\x85\xf2\x00\x00\x00A\x80}\x1d\x00\x0f"
    b"\x85\xe7\x00\x00\x00M;n \x0f\x84\xdd\x00\x00\x00M\x89n(I"
    b"\x8bE\x00I\x89\x86\x80\x00\x00\x00I\x8bE\x08I\x89\x86\x88\x00\x00"
    b"\x00I\x8bE\x10I\x89\x86\x90\x00\x00\x00I\x8bE\x18I\x89\x86\x98"
    b"\x00\x00\x00I\x8bE I\x89\x86\xa0\x00\x00\x00I\x8bE(I\x89"
    b"\x86\xa8\x00\x00\x00I\x8bE0I\x89\x86\xb0\x00\x00\x00\xeb\x7fM9"
    b"n(\x0f\x85\x80\x00\x00\x00I\x8b\x86\x80\x00\x00\x00I9E\x00u"
    b"sI\x8b\x86\x88\x00\x00\x00I9E\x08ufI\x8b\x86\x90\x00\x00"
    b"\x00I9E\x10uYI\x8b\x86\x98\x00\x00\x00I\xba\xff\xff\xff\xff"
    b"\x00\xff\xff\xffL!\xd0I\xba\x00\x00\x00\x00!\x00\x00\x00L\t\xd0"
    b"I9E\x18u2I\x8b\x86\xa0\x00\x00\x00I9E u%I"
    b"\x8b\x86\xa8\x00\x00\x00I9E(u\x18I\x8b\x86\xb0\x00\x00\x00I"
    b"9E0u\x0bA\xc6E\x1c!I\xffF8\xeb\x10I\xc7F\x18"
    b"\x01\x00\x00\x00A\xc7F\x08\x00\x00\x00\x00A^A]A\\A["
    b"AZAXX\x9d"
)
MODIFY_SHA256 = "0223aa1928f48712312919520e3d030343551c17a20c96c065b8d3168984221a"
ARM_KEY = "_bl4tps_ffyl_beta_owner"

POV_RVA = 6986766
POV_ORIGINAL = b"AWAVATVWSH\x81\xec\x98\x02\x00\x00"
POV_SHA256 = "2c714356521de6e24f04769f08312b96e571b60fa9da2bbdcde0a3d03bba0294"
VIEW_PREFIX = (
    b"SVWATH\x83\xec(H\x89\xcbH\x89\xd6L\x89\xc7I\xbc"
    b"UUUUUUUUI9\x1c$uiA\x83|$\x08\x01"
    b"uaI\x8b\x84$\xa0\x00\x00\x00H\x81\xb80:\x00\x00\xa4\xcc\x01"
    b"\x00t&H\x81\xb80:\x00\x00g\x96\x02\x00u?A\x83\xbc$"
    b"\xb8\x00\x00\x00\x00u4A\xc7\x84$\xb8\x00\x00\x00\x02\x00\x00\x00\xeb"
    b"\x17A\x83\xbc$\xc0\x00\x00\x00\x03u\x1bA\xc7\x84$\xc0\x00\x00\x00"
    b"\x02\x00\x00\x00H\x89\xd9H\xb8ffffffff\xff\xd0H"
    b"\x89\xd9H\x89\xf2I\x89\xf8H\xb8DDDDDDDD\xff\xd0"
    b"\x9cPARASI\xbcUUUUUUUUI9\x1c$"
    b"\x0f\x85\xaa\x01\x00\x00A\x83|$\x08\x01\x0f\x85\x9e\x01\x00\x00I\xff"
    b"D$`H\x8b\x06I\x89D$HI\xba\x00\x00\x00\x00\x00\x00\xf0"
    b"\x7fL!\xd0L9\xd0\x0f\x84v\x01\x00\x00H\x8bF\x08I\x89D"
    b"$PI\xba\x00\x00\x00\x00\x00\x00\xf0\x7fL!\xd0L9\xd0\x0f\x84"
    b"W\x01\x00\x00H\x8bF\x10I\x89D$XI\xba\x00\x00\x00\x00\x00"
    b"\x00\xf0\x7fL!\xd0L9\xd0\x0f\x848\x01\x00\x00M\x8b\x9c$\x98"
    b"\x00\x00\x00I\x81\xfb\x00\x04\x00\x00\x0f\x83(\x01\x00\x00I\xff\x84$"
    b"\x98\x00\x00\x00Mi\xdb\xd0\x00\x00\x00O\x8d\x9c\x1c\x00\x01\x00\x00A"
    b"\x8bD$\x0cI\x89\x03H\x8b\x06I\x89C\x08H\x8b\x07I\x89C"
    b" H\x8bF\x08I\x89C\x10H\x8bG\x08I\x89C(H\x8bF"
    b"\x10I\x89C\x18H\x8bG\x10I\x89C0H\x8bCHI\x89C"
    b"8H\x8bCPI\x89C@H\x8bCXI\x89CHH\x8b\x83"
    b"\xa0\x00\x00\x00I\x89CPH\x8b\x83\xa8\x00\x00\x00I\x89CXH"
    b"\x8b\x83\xb0\x00\x00\x00I\x89C`H\x8b\x83\xd8\x00\x00\x00I\x89C"
    b"hH\x8b\x83\xe0\x00\x00\x00I\x89CpH\x8b\x83\xe8\x00\x00\x00I"
    b"\x89CxI\x8b\x84$\xa0\x00\x00\x00L\x8b\x90H:\x00\x00M\x89"
    b"\x93\x80\x00\x00\x00L\x8b\x900:\x00\x00M\x89\x93\x88\x00\x00\x00H"
    b"\x8bC0I\x89\x83\x98\x00\x00\x00H\x8bC8I\x89\x83\xa0\x00\x00"
    b"\x00H\x8bC@I\x89\x83\xa8\x00\x00\x00H\x8b\x83\xc0\x00\x00\x00I"
    b"\x89\x83\xb0\x00\x00\x00H\x8b\x83\xc8\x00\x00\x00I\x89\x83\xb8\x00\x00\x00"
    b"H\x8b\x83\xd0\x00\x00\x00I\x89\x83\xc0\x00\x00\x00I\xc7\x83\x90\x00\x00"
    b"\x00\x01\x00\x00\x00\xeb\x05I\xffD$pA[AZX\x9dH\x83"
    b"\xc4(A\\_^[\xc3"
)

SOCKET_PREFIX = (
    b"\x9cPAPAQARASATAUAVAWI\xbe"
    b"33333333I9\x0e\x0f\x85\t\x02\x00\x00A\x83~"
    b'\x08\x01\x0f\x85\xfe\x01\x00\x00L\x8b"M\x85\xe4\x0f\x84\xf2\x01\x00\x00'
    b"M9$$\x0f\x85\xd8\x01\x00\x00H\x8bB\x08I9D$\x08\x0f"
    b"\x85\xc9\x01\x00\x00I\x8bD$\x10I9F t^A\x83~\x0c"
    b"\x01\x0f\x85\xc3\x01\x00\x00I\x83~(\x00\x0f\x84\xb8\x01\x00\x00I9"
    b"F(\x0f\x85\xae\x01\x00\x00\x83\xb9\xc89\x00\x00\x00\x0f\x85\xa1\x01\x00"
    b"\x00H\x81\xb9\xa89\x00\x00\x07\x03\x00\x00\x0f\x85\x90\x01\x00\x00L\x8b"
    b"\x91H:\x00\x00M\x85\xd2\x0f\x84\x80\x01\x00\x00M\x8bR\x10M9"
    b"V \x0f\x85r\x01\x00\x00\xeb\x0bI\x83~ \x00\x0f\x84e\x01\x00"
    b"\x00M\x8bD$0E\x8bL$8M\x85\xc0\x0f\x84B\x01\x00\x00"
    b"E\x85\xc9\x0f\x8e9\x01\x00\x00A\x83\xf9@\x0f\x87/\x01\x00\x00A"
    b"\x81|$<\x00\x01\x00\x00\x0f\x87 \x01\x00\x00E;L$<\x0f"
    b"\x8f\x15\x01\x00\x00M1\xedM1\xffM\x8b\x10I\x83x\x08\x00\x0f"
    b"\x84\x01\x01\x00\x00M\x85\xd2\x0f\x84\xf8\x00\x00\x00I\x8b\x02I9\x86"
    b"\x00\x01\x00\x00u\x10M\x85\xed\x0f\x85\xe3\x00\x00\x00M\x89\xd5M\x8b"
    b"x\x08I\x83\xc0\x10A\xff\xc9u\xc4M\x85\xed\x0f\x84\xca\x00\x00\x00"
    b"I\x81}\x1c2\x02\x00\x00\x0f\x85\xbc\x00\x00\x00M\x8b\x8e\x08\x01\x00"
    b"\x00M1\xc0M\x8d\x9e@\x01\x00\x00M9\xc8sXM9#u"
    b"JM9k\x08uDM9{\x10\x0f\x85\x91\x00\x00\x00I\x8bE"
    b"\x00I9C\x18\x0f\x85\x83\x00\x00\x00I\x8bE\x08I9C u"
    b"yI\x8bE\x10I9C(uoI\x8bC0$\xfdI9E"
    b"\x18ucI\x8bE I9C8uY\xebgI\xff\xc0I\x83"
    b"\xc3@\xeb\xa3I\x83\xf9\x08sHA\x80}\x18\x02uAM\x89#"
    b"M\x89k\x08M\x89{\x10I\x8bE\x00I\x89C\x18I\x8bE\x08"
    b"I\x89C I\x8bE\x10I\x89C(I\x8bE\x18I\x89C0"
    b"I\x8bE I\x89C8I\xff\x86\x08\x01\x00\x00A\xc6E\x18\x00"
    b"\xeb\x10I\xc7F\x18\x02\x00\x00\x00A\xc7F\x08\x00\x00\x00\x00A_"
    b"A^A]A\\A[AZAYAXX\x9d"
)
SOCKET_SHA256 = "44902831340f963231f806ab98b94789f72c3974291cec21c3e568e71513b893"


def toggle_legacy_ffyl_camera():
    """Arm or stop the legacy FFYL native camera-entry consumers.

    The outer owner prepares perspective/socket state and coordinates the inner
    collision owner. The selected simple strategy must stop this before binding
    its own cycle. This is retained fallback behavior, not the normal strategy.
    """
    old = sys.modules.get(ARM_KEY)
    if old is not None:
        old.stop("manual")
        return
    state = types.ModuleType(ARM_KEY)
    state.active = True
    state.hooks = []
    state.native_hook = None
    state.view_hook = None
    state.bridge = None
    state.inner = None
    state.seen_ffyl = False
    state.exit_seen = False
    state.stopping = False
    state.frames = 0
    state.started = time.perf_counter()
    ctrl = ctypes.create_string_buffer(1024)
    trace = ctypes.create_string_buffer(24 + 128 * 128)
    state.control = ctrl
    state.trace = trace
    state.view_control = ctypes.create_string_buffer(256 + 1024 * 208)
    report = {
        "version": "legacy-ffyl-camera",
        "events": [],
        "errors": [],
        "hook_removal_errors": [],
        "transition_samples": [],
        "diagnostic_errors": [],
        "sample_cap": 2400,
        "diagnostic_game_writes": 0,
        "native_patches": 0,
        "timers": 0,
        "cycles": 1,
        "note": "Single-owner runtime-apply hook prepares FFYL perspective flags before activation; original BlendInTime retained. Default is prepared only for an SDK-confirmed Second Wind from FFYL. Owned socket/collision core activates on first settled FFYL observation. No camera-stack rewrite, runtime swap, or settings writes.",
    }
    sys.modules[ARM_KEY] = state
    state.report = report

    def mode_is_idle(value):
        return str(value[2].GetActorCameraMode(value[1])) == "ThirdPerson" and not bool(
            value[2].CameraModeState.bIsTransitioning
        )

    def socket_records():
        raw = ctrl.raw
        count = struct.unpack_from("<Q", raw, 264)[0]
        if count > 8:
            raise RuntimeError("Early socket record bound exceeded")
        return [
            dict(
                runtime=struct.unpack_from("<Q", raw, 320 + i * 64)[0],
                object=struct.unpack_from("<Q", raw, 328 + i * 64)[0],
                control=struct.unpack_from("<Q", raw, 336 + i * 64)[0],
                original=raw[344 + i * 64 : 384 + i * 64],
            )
            for i in range(count)
        ]

    state.socket_records = socket_records

    def default_offset_owner(fresh):
        if not state.active or not state.exit_seen or stats()["secondwind_gate"] != 1:
            return False
        if (
            tuple(int(x._get_address()) if x is not None else 0 for x in fresh)
            != identity
        ):
            return False
        if str(fresh[2].GetActorCameraMode(fresh[1])) != "Default":
            return False
        runtime, owner = struct.unpack("<QQ", read(identity[2] + 0x3A48, 16))
        if not runtime or not owner:
            return False
        header = read(runtime, 24)
        self_ptr, self_control, definition = struct.unpack("<QQQ", header)
        if (self_ptr, self_control) != (runtime, owner):
            return False
        b = prepared("default")
        if (
            b is None
            or definition != b["address"]
            or read(definition, 56) != b["expected"]
        ):
            return False
        array, count, capacity = struct.unpack("<Qii", read(runtime + 0x30, 16))
        if not array or not 0 < count <= capacity <= 256 or count > 64:
            return False
        entries = read(array, count * 16)
        matches = [
            r
            for r in socket_records()
            if r["runtime"] == runtime
            and (r["object"], r["control"])
            in [struct.unpack_from("<QQ", entries, i * 16) for i in range(count)]
        ]
        if len(matches) != 1:
            return False
        r = matches[0]
        expected = bytearray(r["original"])
        expected[24] &= ~2
        return read(r["object"], 40) == bytes(expected) and read(
            identity[2] + 0x3A48, 16
        ) == struct.pack("<QQ", runtime, owner)

    state.default_offset_owner = default_offset_owner

    def stats():
        raw = ctrl.raw
        return {
            "calls": struct.unpack_from("<Q", raw, 16)[0],
            "native_fault": struct.unpack_from("<Q", raw, 24)[0],
            "ffyl_definition": hex(struct.unpack_from("<Q", raw, 32)[0]),
            "default_definition": hex(struct.unpack_from("<Q", raw, 40)[0]),
            "ffyl_preparations": struct.unpack_from("<Q", raw, 48)[0],
            "default_preparations": struct.unpack_from("<Q", raw, 56)[0],
            "secondwind_gate": struct.unpack_from("<I", raw, 12)[0],
        }

    def event(label, **extra):
        if len(report["events"]) < 600:
            report["events"].append(
                dict(
                    label=label,
                    elapsed=time.perf_counter() - state.started,
                    native=stats(),
                    **extra,
                )
            )

    def prepared(kind):
        raw = ctrl.raw
        pointer = struct.unpack_from("<Q", raw, 32 if kind == "ffyl" else 40)[0]
        if not pointer:
            return None
        original = raw[64:120] if kind == "ffyl" else raw[128:184]
        expected = bytearray(original)
        expected[28] = 0x21
        return {
            "address": pointer,
            "original": original,
            "expected": bytes(expected),
            "entered": state.seen_ffyl,
        }

    def capture_tps_target():
        if getattr(state, "tps_target", None) is not None:
            return
        count = struct.unpack_from("<Q", state.view_control, 152)[0]
        if not 0 < count <= 1024:
            raise RuntimeError("Native TPS target trace unavailable")
        for i in range(count - 1, max(-1, count - 257), -1):
            row = struct.unpack_from("<Q15dQQQ6d", state.view_control, 256 + i * 208)
            if row[18] != 1 or row[17] != 0x1CCA4:
                continue
            offset = tuple(row[22:25])
            if not all(math.isfinite(v) and abs(v) <= 512 for v in offset):
                raise RuntimeError("Native TPS target outside validated bounds")
            state.tps_target = {
                "identity": identity,
                "offset": offset,
                "sequence": i,
                "observer_frame": row[0],
                "runtime": hex(row[16]),
                "source": "last owned native ThirdPerson GetPOV offset before FFYL",
            }
            report["tps_target_source"] = state.tps_target
            return
        raise RuntimeError("No recent native ThirdPerson output for FFYL target")

    def sync_bridge():
        b = prepared("ffyl")
        if b is not None:
            if read(b["address"], 56) != b["expected"]:
                raise RuntimeError("Native FFYL preparation changed outside ownership")
            state.bridge = b

    def write(address, data):
        got = ctypes.c_size_t()
        buf = ctypes.create_string_buffer(data)
        if not kernel.WriteProcessMemory(
            handle, address, buf, len(data), ctypes.byref(got)
        ) or got.value != len(data):
            raise RuntimeError("Definition restoration write failed")
        if read(address, len(data)) != data:
            raise RuntimeError("Definition restoration readback failed")
        report["restoration_bytes"] = report.get("restoration_bytes", 0) + len(data)

    def restore_push_wrapper():
        original = getattr(state, "push_original", None)
        wrapper = getattr(state, "push_wrapper", None)
        if original is None:
            return
        if mod._push_third_person is wrapper:
            mod._push_third_person = original
        elif mod._push_third_person is not original:
            raise RuntimeError("TPS push wrapper replaced externally; not overwritten")
        report["push_wrapper_restore_verified"] = mod._push_third_person is original

    def install_push_wrapper():
        original = mod._push_third_person

        def push(*, transition_time=1.0):
            chosen = transition_time
            value = current()
            if (
                state.active
                and state.exit_seen
                and stats()["secondwind_gate"] == 1
                and value is not None
                and str(value[2].GetActorCameraMode(value[1])) == "Default"
                and transition_time == 0.0
            ):
                definition = prepared("default")
                if (
                    definition is None
                    or read(definition["address"], 56) != definition["expected"]
                ):
                    raise RuntimeError("Second Wind Default blend ownership differs")
                chosen = struct.unpack_from("<f", definition["original"], 24)[0]
                if not math.isfinite(chosen) or not 0 < chosen <= 2:
                    raise RuntimeError(
                        "Original Default blend outside validated bounds"
                    )
                event(
                    "tps_push_preserves_game_blend",
                    requested=transition_time,
                    used=chosen,
                )
            return original(transition_time=chosen)

        state.push_original = original
        state.push_wrapper = push
        mod._push_third_person = push

    def release_camera(reason):
        if getattr(state, "camera_released", False):
            return
        try:
            restore_push_wrapper()
        except Exception as exc:
            report["errors"].append("TPS push restoration: " + repr(exc))
        struct.pack_into("<I", state.view_control, 192, 0)
        struct.pack_into("<I", ctrl, 8, 0)
        struct.pack_into("<I", trace, 8, 0)
        if state.native_hook is not None:
            try:
                h = state.native_hook
                chain.restore(mod, h)
                if read(h["target"], len(h["original"])) != h["original"]:
                    raise RuntimeError("Native unhook readback differs")
                chain.retire(mod, h)
                state.native_hook = None
            except Exception as exc:
                report["errors"].append("Native restoration: " + repr(exc))
        inner = sys.modules.get(STATE_KEY)
        if inner is not None:
            inner.restore("legacy_camera_" + reason)
            report["collision_owner"] = inner.report
        if state.inner is not None:
            report["collision_owner"] = state.inner.report
            if state.inner.report["errors"]:
                report["errors"].append(
                    "Collision core reported errors; see collision_owner"
                )
        report["early_socket_restoration"] = []
        for record in socket_records():
            result = {k: hex(v) for k, v in record.items() if k != "original"}
            try:
                if state.native_hook is not None:
                    raise RuntimeError(
                        "Early socket restore deferred while native hook remains"
                    )
                current_runtime = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
                if current_runtime != record["runtime"]:
                    result["status"] = "retired_runtime_not_dereferenced"
                else:
                    header = read(current_runtime, 32)
                    if struct.unpack_from("<Q", header)[0] != current_runtime:
                        raise RuntimeError("Runtime identity differs")
                    array, count, cap = struct.unpack(
                        "<Qii", read(current_runtime + 0x30, 16)
                    )
                    if not array or not 0 < count <= cap <= 256 or count > 64:
                        raise RuntimeError("Behavior list bound differs")
                    entries = read(array, count * 16)
                    if (record["object"], record["control"]) not in [
                        struct.unpack_from("<QQ", entries, i * 16) for i in range(count)
                    ]:
                        # A runtime address can survive/recur after its behavior owner retires.
                        # Confirm the live list is coherent, then never touch the saved object.
                        if (
                            struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
                            != current_runtime
                            or read(current_runtime, 32) != header
                            or read(current_runtime + 0x30, 16)
                            != struct.pack("<Qii", array, count, cap)
                            or read(array, count * 16) != entries
                        ):
                            raise RuntimeError(
                                "Behavior owner changed during retirement check"
                            )
                        result["status"] = "retired_behavior_owner_not_dereferenced"
                        report["early_socket_restoration"].append(result)
                        continue

                    original = record["original"]
                    expected = bytearray(original)
                    expected[24] &= ~2
                    live = read(record["object"], 40)
                    if live not in (original, bytes(expected)):
                        raise RuntimeError("Socket ownership changed")
                    if live != original:
                        write(record["object"] + 24, original[24:25])
                    if read(record["object"], 40) != original:
                        raise RuntimeError("Socket restore readback differs")
                    result["status"] = "restored_verified"
            except Exception as exc:
                result["status"] = "error"
                report["errors"].append("Early socket restoration: " + repr(exc))
            report["early_socket_restoration"].append(result)
        report["early_socket_write_bytes"] = len(socket_records())
        for kind in ("default", "ffyl"):
            try:
                b = prepared(kind)
                if b is None:
                    continue
                if state.native_hook is not None:
                    raise RuntimeError(
                        "Native detour remains; definition restore deferred"
                    )
                if kind == "ffyl" and sys.modules.get(STATE_KEY) is not None:
                    raise RuntimeError("Collision owner still owns FFYL definition")
                live = read(b["address"], 56)
                if live not in (b["original"], b["expected"]):
                    raise RuntimeError("Shared definition changed outside owned fields")
                if live != b["original"]:
                    write(b["address"] + 28, b["original"][28:29])
                if read(b["address"], 56) != b["original"]:
                    raise RuntimeError("Whole-definition restoration differs")
                report[kind + "_restore_verified"] = True
            except Exception as exc:
                report["errors"].append(kind + " restoration: " + repr(exc))
        state.camera_released = not report["errors"]

    def stop(reason):
        if state.stopping:
            return
        state.stopping = True
        state.active = False
        struct.pack_into("<I", ctrl, 8, 0)
        struct.pack_into("<I", trace, 8, 0)
        struct.pack_into("<I", state.view_control, 8, 0)
        if state.view_hook is not None:
            try:
                h = state.view_hook
                chain.restore(mod, h)
                if read(h["target"], len(h["original"])) != h["original"]:
                    raise RuntimeError("GetPOV unhook differs")
                chain.retire(mod, h)
                state.view_hook = None
            except Exception as exc:
                report["errors"].append("GetPOV restoration: " + repr(exc))
        release_camera(reason)
        for spec in list(state.hooks):
            try:
                if has_hook(*spec):
                    remove_hook(*spec)
                if has_hook(*spec):
                    raise RuntimeError("SDK hook remains installed")
                state.hooks.remove(spec)
            except Exception as exc:
                report["hook_removal_errors"].append(repr(exc))
        report["definition_snapshots"] = {
            k: {
                "address": hex(b["address"]),
                "original_hex": b["original"].hex(),
                "prepared_hex": b["expected"].hex(),
            }
            for k in ("ffyl", "default")
            if (b := prepared(k)) is not None
        }
        report["native_definition_write_bytes"] = (
            stats()["ffyl_preparations"] + stats()["default_preparations"]
        )
        report.update(
            reason=reason,
            native=stats(),
            native_patches=int(state.native_hook is not None)
            + int(state.view_hook is not None),
            native_restore_verified=state.native_hook is None
            and state.view_hook is None,
        )
        raw = trace.raw
        count = struct.unpack_from("<Q", raw, 16)[0]
        rows = []
        for i in range(min(count, 128)):
            v = struct.unpack_from("<16Q", raw, 24 + i * 128)
            if v[7] != 1:
                continue
            rows.append(
                dict(
                    sequence=i,
                    current_fname=struct.pack("<Q", v[1]).hex(),
                    candidate_fname=struct.pack("<Q", v[2]).hex(),
                    runtime=hex(v[11]),
                    definition=hex(v[12]),
                    flags_before=None if v[13] == 0xFFFFFFFFFFFFFFFF else v[13],
                    stack_count=v[6],
                    blend=struct.unpack("<f", struct.pack("<Q", v[4])[:4])[0],
                )
            )
        report["native_rows_before_preparation"] = rows
        report["trace_truncated"] = count > 128
        complete = (
            state.native_hook is None
            and not state.hooks
            and sys.modules.get(STATE_KEY) is None
        )
        complete = complete and all(
            report.get(k + "_restore_verified", False)
            for k in ("ffyl", "default")
            if prepared(k) is not None
        )
        complete = (
            complete
            and state.view_hook is None
            and all(r["status"] != "error" for r in report["early_socket_restoration"])
        )
        report["cleanup_complete"] = complete
        raw = state.view_control.raw
        count = struct.unpack_from("<Q", raw, 152)[0]
        report["native_pov_rows"] = []
        for i in range(0):  # production does not serialize native trace records
            values = struct.unpack_from("<Q15dQQQ6d", raw, 256 + i * 208)
            if values[18] == 1:
                report["native_pov_rows"].append(
                    dict(
                        sequence=i,
                        observer_frame=values[0],
                        location=values[1:4],
                        rotation=values[4:7],
                        pov_rotation=values[7:10],
                        base_rotation=values[10:13],
                        camera_rotation_offset=values[13:16],
                        runtime=hex(values[16]),
                        fname=struct.pack("<Q", values[17]).hex(),
                        pov_location=values[19:22],
                        camera_location_offset=values[22:25],
                    )
                )
        report["native_pov_calls"] = struct.unpack_from("<Q", raw, 96)[0]
        report["native_pov_invalid_locations"] = struct.unpack_from("<Q", raw, 112)[0]
        report["native_pov_truncated"] = report["native_pov_calls"] > 1024
        report["getpov_restore_verified"] = state.view_hook is None
        report["handoff_diagnostic"] = (
            "Read-only tail follows lifecycle offsets-restored and pending=false, then 12 native TPS observer frames; CZ entry retained; early owned TPS offset handoff added"
        )
        report["blend_policy"] = (
            "Original FFYL and Default BlendInTime preserved; no timer controls transition"
        )
        report["diagnostic_output_writes"] = 0
        report["native_composition_capture"] = (
            "Output location/rotation, POV location/rotation, base rotation, local camera offsets captured in the same GetPOV call; original outputs unchanged"
        )
        logging.info(
            f'{TAG} COMPLETE reason={reason} errors={len(report["errors"])} cleanup_complete={complete}'
        )
        state.report = report
        if report["errors"] or not complete:
            if mods:
                mods[0]._ffyl_beta_fault = True
            logging.error(
                f'{TAG} restoration details: {report["errors"]}; hook errors={report["hook_removal_errors"]}'
            )
        if complete:
            sys.modules.pop(ARM_KEY, None)
        state.stopping = False

    state.stop = stop
    try:
        mods = [
            m
            for n, m in list(sys.modules.items())
            if m is not None
            and n.endswith("BL4ThirdPersonPOC")
            and callable(getattr(m, "_get_runtime", None))
        ]
        if len(mods) != 1:
            raise RuntimeError("Expected one GU mod")
        mod = mods[0]
        pc, pawn, cam = mod._get_runtime()
        if any(x is None for x in (pc, pawn, cam)):
            raise RuntimeError("Loaded gameplay required")
        identity = tuple(int(x._get_address()) for x in (pc, pawn, cam))
        if (
            not mod._third_person_enabled
            or mod._native_fault
            or str(cam.GetActorCameraMode(pawn)) != "ThirdPerson"
            or bool(cam.CameraModeState.bIsTransitioning)
        ):
            raise RuntimeError("Arm in settled normal TPS without a native fault")
        if any(
            bool(getattr(mod, k, False))
            for k in (
                "_ads_active",
                "_slide_active",
                "_vehicle_camera_active",
                "_shop_camera_active",
                "_ladder_active",
            )
        ):
            raise RuntimeError("Leave special camera state before arming")
        read = lambda address, size: chain.original_read(mod, address, size)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        kernel.GetCurrentProcess.argtypes = ()
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.WriteProcessMemory.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel.WriteProcessMemory.restype = ctypes.c_int
        handle = kernel.GetCurrentProcess()
        base = int(kernel.GetModuleHandleW(None) or 0)
        dos = read(base, 64)
        peoff = struct.unpack_from("<I", dos, 60)[0]
        if dos[:2] != b"MZ" or not 64 <= peoff <= 0x100000:
            raise RuntimeError("DOS layout differs")
        pe = read(base + peoff, 0x60)
        if (
            pe[:4] != b"PE\0\0"
            or (
                struct.unpack_from("<I", pe, 8)[0],
                struct.unpack_from("<I", pe, 0x50)[0],
                struct.unpack_from("<H", pe, 4)[0],
            )
            != EXPECTED
        ):
            raise RuntimeError("Game build differs")
        if (
            hashlib.sha256(read(base + APPLY_RVA, 4096)).hexdigest() != APPLY_SHA256
            or read(base + APPLY_RVA, len(APPLY_ORIGINAL)) != APPLY_ORIGINAL
        ):
            raise RuntimeError(
                "Runtime apply signature differs or another hook owns it"
            )
        if (
            hashlib.sha256(MODIFY_PREFIX).hexdigest() != MODIFY_SHA256
            or hashlib.sha256(APPLY_PREFIX).hexdigest() != APPLY_PREFIX_SHA256
        ):
            raise RuntimeError("Native prefix signature differs")
        if struct.unpack("<Q", read(identity[2] + 0x39D8, 8))[0] != int(
            cam.CameraModeState._get_address()
        ):
            raise RuntimeError("Camera state identity differs")
        schema = find_object("ScriptStruct", "/Script/GbxGame.CameraModeDef")
        if schema is None or int(schema.PropertySize) != 56:
            raise RuntimeError("Camera definition schema unavailable")
        props = {
            str(p.Name): p
            for owner in [schema, *list(schema._superfields())]
            for p in owner._properties()
        }
        for name, mask in (("bIsFirstPerson", 2), ("bShowViewModel", 4)):
            p = props[name]
            if (
                str(p.Class.Name),
                int(p.Offset_Internal),
                int(p.ElementSize),
                int(p.ArrayDim),
                int(p.FieldMask),
            ) != ("BoolProperty", 28, 1, 1, mask):
                raise RuntimeError("Perspective schema differs")
        p = props["BlendInTime"]
        if (
            str(p.Class.Name),
            int(p.Offset_Internal),
            int(p.ElementSize),
            int(p.ArrayDim),
        ) != ("FloatProperty", 24, 4, 1):
            raise RuntimeError("Blend schema differs")
        if struct.unpack("<Q", read(base + 0xB5C94E0 + 24, 8))[0] != base + 0x18E0A3A:
            raise RuntimeError("FFYLPitch identity differs")
        if hashlib.sha256(read(base + POV_RVA, 2303)).hexdigest() != POV_SHA256:
            raise RuntimeError("GetPOV signature differs")
        if hashlib.sha256(SOCKET_PREFIX).hexdigest() != SOCKET_SHA256:
            raise RuntimeError("Socket prefix signature differs")
        if struct.unpack("<Q", read(base + 0xB00EA00 + 24, 8))[0] != base + 0x1874A9C:
            raise RuntimeError("Socket update identity differs")
        if (
            read(base + 0x1874A9C, 32).hex()
            != "5657534881ece0000000660f29b424d00000004c89c64889cf488b0584aee80a"
        ):
            raise RuntimeError("Socket update signature differs")
        struct.pack_into("<Q", ctrl, 256, base + 0xB00EA00)
        struct.pack_into("<QII", ctrl, 0, identity[2], 1, 0)
        struct.pack_into(
            "<QQQ",
            ctrl,
            192,
            base + 0xB5C94E0,
            int.from_bytes(bytes.fromhex("6796020000000000"), "little"),
            0x307,
        )
        struct.pack_into("<QIIQ", trace, 0, identity[2], 1, 0, 0)
        report["identity"] = identity

        def current():
            value = mod._get_runtime()
            if (
                any(x is None for x in value)
                or tuple(int(x._get_address()) for x in value) != identity
            ):
                return None
            return value

        def handoff_snapshot():
            # Only primitive Python state; no extra game writes or native calls.
            lifecycle = getattr(mod, "_camera_lifecycle", None)
            keys = (
                "pending",
                "reason",
                "phase",
                "repair_done",
                "suppress_offsets",
                "early_handoff_attempted",
                "early_handoff_offsets_restored",
            )
            result = {
                "lifecycle": (
                    {k: lifecycle.get(k) for k in keys}
                    if isinstance(lifecycle, dict)
                    else None
                )
            }
            result["native_active"] = bool(mod._native_active())
            result["camera_released"] = bool(getattr(state, "camera_released", False))
            try:
                offsets = [
                    float(getattr(mod, "camera_offset_" + axis).value)
                    for axis in ("x", "y", "z")
                ]
                result["configured_offsets"] = (
                    offsets if all(math.isfinite(x) for x in offsets) else None
                )
            except (AttributeError, TypeError, ValueError):
                result["configured_offsets"] = None
            return result

        def observe_transition(value, mode):
            # Read-only diagnostic. Offsets 0xa70/74/78 are written by the
            # verified activation routine at e5f0de/e5f0e6/e5f0f1.
            # Diagnostic read failure must not abort the established camera owner.
            rows = report["transition_samples"]
            if len(rows) >= report["sample_cap"]:
                report["samples_truncated"] = True
                return
            try:
                manager = identity[2]
                cs = value[2].CameraModeState
                before = read(manager + 0x3A48, 16)
                runtime, control = struct.unpack("<QQ", before)
                if not runtime or not control:
                    return
                header = read(runtime, 32)
                self_ptr, self_control, definition, reserved = struct.unpack(
                    "<QQQQ", header
                )
                if (self_ptr, self_control) != (runtime, control):
                    return
                if mode == "Default" and runtime not in getattr(
                    state, "captured_default", set()
                ):
                    captured = getattr(state, "captured_default", set())
                    captured.add(runtime)
                    state.captured_default = captured
                    behavior_rows = []
                    for phase, offset in (("pre", 0x20), ("post", 0x30)):
                        array, count, capacity = struct.unpack(
                            "<Qii", read(runtime + offset, 16)
                        )
                        if not 0 <= count <= capacity <= 256 or count > 64:
                            raise RuntimeError("Default behavior bounds differ")
                        if count and not array:
                            raise RuntimeError("Default behavior list is null")
                        entries = read(array, count * 16) if count else b""
                        for i in range(count):
                            obj, owner = struct.unpack_from("<QQ", entries, i * 16)
                            if not obj or not owner:
                                raise RuntimeError("Default behavior pair is null")
                            object_header = read(obj, 32)
                            vt = struct.unpack_from("<Q", object_header)[0]
                            behavior_rows.append(
                                dict(
                                    phase=phase,
                                    index=i,
                                    address=hex(obj),
                                    control=hex(owner),
                                    header_hex=object_header.hex(),
                                    vtable_rva=hex(vt - base),
                                    slots_hex=read(vt, 32).hex(),
                                )
                            )
                    report.setdefault("default_behavior_snapshots", []).append(
                        dict(
                            runtime=hex(runtime),
                            definition=hex(definition),
                            rows=behavior_rows,
                        )
                    )
                activation = read(runtime + 0xA70, 9)
                duration, remaining, active = struct.unpack("<ffB", activation)
                if not all(math.isfinite(x) for x in (duration, remaining)):
                    raise RuntimeError("Non-finite runtime blend values")
                state_address = int(cs._get_address())
                pov = struct.unpack("<6d", read(state_address + 0x30, 48))
                camera_offset = struct.unpack("<3d", read(state_address + 0xC0, 24))
                base_rotation = struct.unpack("<3d", read(state_address + 0xA0, 24))
                v = value[2].GetCameraLocation()
                location = [float(v.X), float(v.Y), float(v.Z)]
                if not all(
                    math.isfinite(x)
                    for x in (*pov, *camera_offset, *base_rotation, *location)
                ):
                    raise RuntimeError("Non-finite spatial sample")
                coherent = (
                    read(manager + 0x3A48, 16) == before
                    and read(runtime, 24) == header[:24]
                )
                rows.append(
                    dict(
                        frame=state.frames,
                        elapsed_s=time.perf_counter() - state.started,
                        mode=mode,
                        runtime=hex(runtime),
                        definition=hex(definition),
                        coherent=coherent,
                        transitioning=bool(cs.bIsTransitioning),
                        viewmodel=bool(cs.bShowViewModel),
                        blend_duration=duration,
                        blend_remaining=remaining,
                        blend_active_byte=active,
                        pov_location=list(pov[:3]),
                        pov_rotation=list(pov[3:]),
                        camera_location=location,
                        camera_offset=list(camera_offset),
                        base_rotation=list(base_rotation),
                        native_calls=stats()["calls"],
                        core_active=state.inner is not None and state.inner.active,
                        handoff_state=handoff_snapshot(),
                    )
                )
            except Exception as exc:
                if len(report["diagnostic_errors"]) < 12:
                    report["diagnostic_errors"].append(repr(exc))

        def frame(*args):
            if not state.active:
                return
            try:
                state.frames += 1
                struct.pack_into("<I", state.view_control, 12, state.frames)
                if stats()["native_fault"]:
                    raise RuntimeError(
                        "Native ownership/schema guard refused preparation"
                    )
                value = current()
                if value is None:
                    stop("identity_changed")
                    return
                if mod._native_fault or not mod._third_person_enabled:
                    stop("mod_state_changed")
                    return
                if (
                    not getattr(state, "tail_active", False)
                    and struct.unpack_from("<Q", state.view_control, 152)[0] >= 768
                ):
                    # Same game-thread observer: recycle capture slots without retiring hooks.
                    struct.pack_into("<Q", state.view_control, 152, 0)
                mode = str(value[2].GetActorCameraMode(value[1]))
                transitioning = bool(value[2].CameraModeState.bIsTransitioning)
                if getattr(state, "tail_active", False):
                    if mode != "ThirdPerson" or transitioning:
                        stop("tail_mode_changed")
                        return
                    if (
                        int(value[2].CameraModeState._get_address())
                        != struct.unpack_from("<Q", state.view_control, 0)[0]
                    ):
                        stop("tail_state_changed")
                        return
                    observe_transition(value, mode)
                    count = struct.unpack_from("<Q", state.view_control, 152)[0]
                    if count > 1024:
                        stop("tail_trace_cap")
                        return
                    for i in range(state.tail_cursor, count):
                        row = struct.unpack_from(
                            "<Q15dQQQ", state.view_control, 256 + i * 208
                        )
                        if (
                            row[-1] == 1
                            and row[-2] == 0x1CCA4
                            and row[-3] == state.tail_runtime
                            and row[0] > state.tail_start_frame
                        ):
                            state.tail_frames.add(row[0])
                    state.tail_cursor = count
                    report["tps_tail_observed_frames"] = len(state.tail_frames)
                    snapshot = handoff_snapshot()
                    lifecycle = snapshot["lifecycle"]
                    ready = (
                        lifecycle is not None
                        and lifecycle.get("pending") is False
                        and lifecycle.get("early_handoff_offsets_restored") is True
                    )
                    if ready and getattr(state, "tail_ready_frame", None) is None:
                        state.tail_ready_frame = state.frames
                        event("tps_offsets_handoff_ready", handoff_state=snapshot)
                    ready_frame = getattr(state, "tail_ready_frame", None)
                    observed = (
                        sum(f > ready_frame for f in state.tail_frames)
                        if ready_frame is not None
                        else 0
                    )
                    report["tps_tail_after_handoff_frames"] = observed
                    if observed >= 12:
                        stop("secondwind_tps_tail_complete")
                    return
                sync_bridge()
                observe_transition(value, mode)
                if state.inner is not None:
                    if state.inner.report["errors"]:
                        raise RuntimeError("Collision core reported errors")
                    if sys.modules.get(STATE_KEY) is None and mode == "FFYL":
                        stop("collision_core_retired")
                        return
                key = (
                    mode,
                    transitioning,
                    bool(value[2].CameraModeState.bShowViewModel),
                    stats()["calls"],
                )
                if key != getattr(state, "last", None):
                    event(
                        "frame_change",
                        mode=mode,
                        transitioning=transitioning,
                        viewmodel=key[2],
                    )
                    state.last = key
                if mode == "FFYL":
                    state.seen_ffyl = True
                    if (
                        not transitioning
                        and sys.modules.get(STATE_KEY) is None
                        and state.inner is None
                        and not state.exit_seen
                        and not mod._native_active()
                    ):
                        capture_tps_target()
                        toggle_legacy_ffyl_collision()
                        state.inner = sys.modules.get(STATE_KEY)
                        if state.inner is None or not state.inner.active:
                            raise RuntimeError(
                                "Collision core refused; see collision diagnostics"
                            )
                        event("collision_core_active")
                elif state.exit_seen and mode == "ThirdPerson" and not transitioning:
                    # Release all camera corrections at the same CT state boundary.
                    # Retain only the read-only GetPOV hook and lifecycle observers.
                    release_camera("secondwind_stable_tps")
                    if report["errors"]:
                        stop("tail_camera_release_error")
                        return
                    state.tail_active = True
                    state.tail_start_frame = state.frames
                    state.tail_cursor = struct.unpack_from(
                        "<Q", state.view_control, 152
                    )[0]
                    state.tail_runtime = struct.unpack(
                        "<Q", read(identity[2] + 0x3A48, 8)
                    )[0]
                    state.tail_frames = set()
                    report["tps_tail_requested_frames"] = 12
                    event(
                        "tps_tail_started",
                        runtime=hex(state.tail_runtime),
                        observer_frame=state.frames,
                    )

            except Exception as exc:
                report["errors"].append("Frame: " + repr(exc))
                stop("frame_error")

        def ended(obj, args, ret, func):
            if not state.active:
                return
            if getattr(state, "tail_active", False):
                stop("tail_exit_event")
                return
            try:
                value = current()
                if value is None:
                    return
                mode = str(value[2].GetActorCameraMode(value[1]))
                reason = str(getattr(args, "Reason", ""))
                if state.exit_seen:
                    event("duplicate_exit", mode=mode, reason=reason)
                    return
                if mode != "FFYL":
                    return
                state.exit_seen = True
                state.seen_ffyl = True
                secondwind = reason == "2" or "SecondWind" in reason
                event("exit_pre", mode=mode, reason=reason, secondwind=secondwind)
                if secondwind:
                    struct.pack_into("<I", ctrl, 12, 1)
                    struct.pack_into("<I", state.view_control, 192, 3)
                    inner = sys.modules.get(STATE_KEY)
                    if inner is not None:
                        inner.handoff = True
                else:
                    stop("non_secondwind_exit")
            except Exception as exc:
                report["errors"].append("Exit: " + repr(exc))
                stop("exit_error")

        def restart(obj, *args):
            if state.active and int(obj._get_address()) == identity[0]:
                stop("client_restart_pre")

        def downed(*args):
            if state.active:
                if getattr(state, "tail_active", False):
                    stop("tail_downed")
                    return
                try:
                    sync_bridge()
                    event("downed_pre_after_native")
                except Exception as exc:
                    report["errors"].append("Downed: " + repr(exc))
                    stop("downed_error")

        install_push_wrapper()
        plans = [
            (
                mod.FIRST_PERSON_ANIM_HOOK,
                Type.POST_UNCONDITIONAL,
                "bl4tps_ffyl_beta.outer_observe",
                frame,
            ),
            (
                mod.FFYL_EARLY_ENDED_FUNCTION,
                Type.PRE,
                "bl4tps_ffyl_beta.outer_exit",
                ended,
            ),
            (
                mod.CLIENT_RESTART_FUNCTION,
                Type.PRE,
                "bl4tps_ffyl_beta.outer_restart",
                restart,
            ),
            (
                mod.FFYL_DOWNED_FUNCTION,
                Type.PRE,
                "bl4tps_ffyl_beta.outer_downed",
                downed,
            ),
        ]
        for path, kind, name, callback in plans:
            if has_hook(path, kind, name):
                raise RuntimeError("Untracked SDK hook exists")
            state.hooks.append((path, kind, name))
            add_hook(path, kind, name, callback)
            if not has_hook(path, kind, name):
                raise RuntimeError("SDK hook refused")

        def build(stub, trampoline):
            a = APPLY_PREFIX.replace(
                b"\x22" * 8, struct.pack("<Q", ctypes.addressof(trace))
            )
            b = MODIFY_PREFIX.replace(
                b"\x33" * 8, struct.pack("<Q", ctypes.addressof(ctrl))
            )
            # Pin both controls in the retired-stub ownership tuple.
            c = SOCKET_PREFIX.replace(
                b"\x33" * 8, struct.pack("<Q", ctypes.addressof(ctrl))
            )
            return (
                (trace, ctrl),
                ctrl,
                a + b + c + b"\xff\x25\x00\x00\x00\x00" + struct.pack("<Q", trampoline),
            )

        if read(base + APPLY_RVA, len(APPLY_ORIGINAL)) != APPLY_ORIGINAL:
            raise RuntimeError("Entry changed before install")
        state.native_hook = chain.allocate(
            mod,
            base + APPLY_RVA,
            APPLY_ORIGINAL,
            len(APPLY_ORIGINAL),
            build,
            "legacy-ffyl-camera runtime handoff",
        )
        if not chain.verify(mod, state.native_hook):
            raise RuntimeError("Patch verification differs")
        report["native_patches"] = 1
        event("armed")
        struct.pack_into(
            "<QII", state.view_control, 0, int(cam.CameraModeState._get_address()), 1, 0
        )
        struct.pack_into("<Q", state.view_control, 160, identity[2])
        state.early_busy = False
        report["early_collision_callbacks"] = []

        def early_collision(state_pointer):
            # Same game-thread callback, before original GetPOV. No ctypes
            # exception may escape across the native boundary. Reentry is gated.
            if state.early_busy:
                return
            state.early_busy = True
            started = time.perf_counter()
            status = "not_ready"
            try:
                if not state.active:
                    return
                value = current()
                if value is None:
                    raise RuntimeError("Early collision runtime identity changed")
                cam = value[2]
                if int(cam.CameraModeState._get_address()) != int(state_pointer):
                    raise RuntimeError("Early collision state differs")
                mode = str(cam.GetActorCameraMode(value[1]))
                if mode == "ThirdPerson":
                    if not state.exit_seen or stats()["secondwind_gate"] != 1:
                        return
                    inner = state.inner
                    if inner is None or not inner.active:
                        return
                    if inner.apply_tps_handoff():
                        # The game rebuilds this composed offset each frame during blending.
                        # Re-arm on the actual transition state, never on elapsed time.
                        blending = bool(cam.CameraModeState.bIsTransitioning)
                        struct.pack_into(
                            "<I", state.view_control, 192, 3 if blending else 1
                        )
                        status = (
                            "tps_blend_offsets_before_GetPOV"
                            if blending
                            else "tps_offsets_before_GetPOV"
                        )
                        report["tps_handoff_calls"] = (
                            report.get("tps_handoff_calls", 0) + 1
                        )
                        rows = report.setdefault("tps_blend_handoff_samples", [])
                        if len(rows) < 96:
                            rows.append(
                                dict(
                                    observer_frame=state.frames,
                                    transitioning=blending,
                                    details=inner.report["tps_early_handoff"],
                                )
                            )
                        if report["tps_handoff_calls"] == 1:
                            event(
                                "tps_early_offsets_applied",
                                details=inner.report["tps_early_handoff"],
                            )
                    return
                if mode != "FFYL" or mod._native_active():
                    return
                # Wait for coherent FFYL ownership, not for blend completion.
                if struct.unpack("<i", read(identity[2] + 0x39C8, 4))[0] != 1:
                    return
                sync_bridge()
                state.seen_ffyl = True
                if state.inner is None and sys.modules.get(STATE_KEY) is None:
                    v = cam.CameraModeState.CameraLocationOffset
                    state.early_offset_snapshot = (
                        int(cam._get_address()),
                        int(state_pointer),
                        struct.unpack("<Q", read(int(cam._get_address()) + 0x3A48, 8))[
                            0
                        ],
                        tuple(float(getattr(v, a)) for a in ("X", "Y", "Z")),
                    )
                    capture_tps_target()
                    toggle_legacy_ffyl_collision()
                    state.inner = sys.modules.get(STATE_KEY)
                    if state.inner is None or not state.inner.active:
                        raise RuntimeError(
                            "Early collision core refused; see collision diagnostics"
                        )
                    event("early_collision_core_active")
                if state.inner is None or state.inner.report["errors"]:
                    raise RuntimeError("Early collision core not healthy")
                struct.pack_into("<I", state.view_control, 184, 1)
                status = "applied_before_GetPOV"
            except BaseException as exc:
                status = "error"
                report["errors"].append("Early collision: " + repr(exc))
                report["early_collision_callbacks"].append(
                    dict(
                        status=status,
                        cost_ms=(time.perf_counter() - started) * 1000,
                        offset_snapshot=getattr(state, "early_offset_snapshot", None),
                    )
                )
                stop("early_collision_error")
            finally:
                if struct.unpack_from("<I", state.view_control.raw, 184)[0] == 2:
                    struct.pack_into("<I", state.view_control, 184, 0)
                if struct.unpack_from("<I", state.view_control, 192)[0] == 2:
                    struct.pack_into("<I", state.view_control, 192, 3)
                state.early_busy = False
                state.early_offset_snapshot = None
                if status != "error" and len(report["early_collision_callbacks"]) < 32:
                    report["early_collision_callbacks"].append(
                        dict(
                            status=status,
                            cost_ms=(time.perf_counter() - started) * 1000,
                        )
                    )

        state.early_callback = ctypes.WINFUNCTYPE(None, ctypes.c_void_p)(
            early_collision
        )

        def view_build(stub, trampoline):
            code = (
                VIEW_PREFIX.replace(b"\x44" * 8, struct.pack("<Q", trampoline))
                .replace(
                    b"\x55" * 8, struct.pack("<Q", ctypes.addressof(state.view_control))
                )
                .replace(
                    b"\x66" * 8,
                    struct.pack(
                        "<Q", ctypes.cast(state.early_callback, ctypes.c_void_p).value
                    ),
                )
            )
            return (state.view_control, state.early_callback), state.view_control, code

        state.view_hook = chain.allocate(
            mod,
            base + POV_RVA,
            POV_ORIGINAL,
            16,
            view_build,
            "legacy-ffyl-camera read-only GetPOV trace",
        )
        if not chain.verify(mod, state.view_hook):
            raise RuntimeError("GetPOV patch verification differs")
        logging.info(f"{TAG} ARMED native_patches=2 implementation=legacy-ffyl-camera")
    except Exception as exc:
        report["errors"].append("Setup: " + repr(exc))
        stop("setup_failed")


def shutdown(reason="mod_disable"):
    owner = sys.modules.get(ARM_KEY)
    if owner is not None:
        owner.stop(reason)
    return sys.modules.get(ARM_KEY) is None and sys.modules.get(STATE_KEY) is None


def update(mod):
    """Rearm on verified normal TPS; use game state to finish each cycle."""
    enabled = mod.tps_ffyl_beta.value is True and mod._third_person_enabled
    owner = sys.modules.get(ARM_KEY)
    if not enabled or mod._native_fault:
        if owner is not None:
            shutdown("feature_or_tps_disabled")
        return
    if owner is not None or getattr(mod, "_ffyl_beta_fault", False):
        return
    try:
        pc, pawn, cam = mod._get_runtime()
        if any(x is None for x in (pc, pawn, cam)):
            return
        if (
            str(cam.GetActorCameraMode(pawn)) != "ThirdPerson"
            or cam.CameraModeState.bIsTransitioning
        ):
            return
        if mod._camera_lifecycle.get("pending") or mod._ffyl_native_resume_pending:
            return
        if not mod._camera_stack_owner.get("owned"):
            return
        if any(
            bool(getattr(mod, key, False))
            for key in (
                "_ads_active",
                "_slide_active",
                "_vehicle_camera_active",
                "_shop_camera_active",
                "_ladder_active",
            )
        ):
            return
        toggle_legacy_ffyl_camera()
    except Exception as exc:
        mod._ffyl_beta_fault = True
        logging.error(f"{TAG} controller refused: {exc}")


def owns_visibility_runtime(identity, *, read) -> bool:
    """Prove the existing FFYL camera ownership used by character visibility.

    The caller validates live local WeakPointers/world/mode before this read.
    This is visibility permission only, never permission to activate native recoil
    or overwrite a camera owner. Read errors propagate to the caller's fault gate.
    """
    owner = sys.modules.get(STATE_KEY)
    if (
        owner is None
        or not getattr(owner, "active", False)
        or tuple(getattr(owner, "identity", ())) != tuple(identity)
        or not getattr(owner, "offset_owned", False)
    ):
        return False
    return read(owner.address, 56) == owner.expected_after
