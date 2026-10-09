"""Override the owned FireBeam query origin before endpoint calculation.

After executable/entry checks, one native detour writes the query origin to
receiver +0x388 for the validated local weapon mode, receiver table and TPS
definition. Original game code then computes direction/endpoints and collision.

0.3.9.12 (beam crosshair/wall edge): the origin is the camera-cache position
moved along the camera-cache view direction to character depth plus margin, the
0.3.9.9 aim-trace rule, so geometry between camera and character (a wall edge
beside the camera, an enemy behind the character) is no longer queried. Pawn
position, margin and the on/off switch come from the shared aim-trace control
block (`bl4tps_aim`). The POV.Rotation offset is resolved by reflection and
checked against the live value; without it the camera position is written as
before. The guarded-prefix collision helper only acts on camera-start queries
and keeps the original result for shifted ones.
The native ownership coordinator manages activation and camera handoff release.
No Python callback runs inside the detour. The first 64 writes are recorded;
correction continues afterward. Restore code, not a potentially stale receiver.
Executable storage and buffers remain pinned for process lifetime.
"""

from .native_memory import _native_absolute_jump
from .native_hook_lifecycle import _exchange_owned_bytes
import ctypes
import hashlib
import math
import struct
from .build_gate import REVIEWED_BUILD
import sys
import types
from unrealsdk import logging, find_all

TAG = "[BL4ThirdPersonPOC.BeamOrigin]"
KEY = "_bl4_tps_beam_origin_owner"
EXPECTED = REVIEWED_BUILD
RVA = 0xA640F0
ORIGINAL = bytes.fromhex("415741565657534881ec90010000")
ANCHOR_RVA = 0xA640FE
ANCHOR = bytes.fromhex("66440f29bc248001000066440f29b4247001000066440f29")
LIMIT = 64
RETIRED = "_bl4_tps_beam_origin_retired"


def is_firebeam(weapon):
    """Read the guarded fire-mode identity before any full patch setup."""
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p
        k.GetCurrentProcess.argtypes = []
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.ReadProcessMemory.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k.ReadProcessMemory.restype = ctypes.c_int
        base = int(k.GetModuleHandleW(None) or 0)
        handle = k.GetCurrentProcess()
        wa = int(weapon._get_address())

        def data_at(address, length):
            if address < 0x10000 or length not in (1, 8, 16):
                raise RuntimeError("Invalid FireBeam identity read")
            result = ctypes.create_string_buffer(length)
            got = ctypes.c_size_t()
            if (
                not k.ReadProcessMemory(
                    handle, address, result, length, ctypes.byref(got)
                )
                or got.value != length
            ):
                raise RuntimeError("FireBeam identity unavailable")
            return result.raw

        data, count, capacity = struct.unpack("<Qii", data_at(wa + 0xBE8, 16))
        index = data_at(wa + 0xBD8, 1)[0]
        if not base or not 0 <= index < count <= capacity <= 32:
            return False
        fire = struct.unpack("<Q", data_at(data + index * 0x88 + 8, 8))[0]
        if not fire:
            return False
        owner = struct.unpack("<Q", data_at(fire + 0x30, 8))[0]
        vt = struct.unpack("<Q", data_at(fire, 8))[0]
        implementation = struct.unpack("<Q", data_at(vt + 0x410, 8))[0]
        return owner == wa and implementation == base + 0x4344586
    except Exception:
        return False


# Assembled from docs/beam_origin_stub_source.py (keystone); executed in a
# native Linux x64 harness by tests/test_beam_depth_0_3_9_12.py.
TEMPLATE = bytes.fromhex(
    "9c504152415349ba1111111111111111f049ff420849bb22222222222222224c39190f85d5030000f049ff421049bb33333333333333334c3999c80000000f85b90300006683b9ea020000050f85ab030000f68110030000040f859e0300004d8b9bb00100004d85db0f848e0300004d8b9bc00300004d85db0f847e0300004d8b9b002500004d85db0f846e030000498b83483a00004885c00f845e030000488b40104885c00f8451030000f6401c020f85470300004883ec60f30f7f0424f30f7f4c2410498b83101900004889442420498b83181900004889442428498b83201900004889442430660f57c048c74424580000000048b85555555555555555488338010f85ef00000048b866666666666666664c01d849ba399d52a246df913f4c89542450dd00dc4c2450d9fbdd4008dc4c2450d9fbd8cadd5c2438dec9dd5c2440dd5c244848b85555555555555555f20f104020f20f5c442420f20f59442438f20f104828f20f5c4c2428f20f594c2440f20f58c1f20f104830f20f5c4c2430f20f594c2448f20f58c1f20f5880b000000048c744245802000000660f57c9660f2ec17652660f2e4058734bf20f104c2438f20f59c8f20f584c2420f20f114c2420f20f104c2440f20f59c8f20f584c2428f20f114c2428f20f104c2448f20f59c8f20f584c2430f20f114c243048c74424580100000049ba1111111111111111488b442458f049ff84c200410000f2410f118218410000498b831019000049898220410000498b831819000049898228410000498b832019000049898230410000488b44242049898238410000488b44242849898240410000488b44243049898248410000b801000000f0490fc1024883f8400f834e01000048c1e0084d8d54022048c1e80848ffc0498982f800000049894a08488b81c8000000498942104d895a180fb781ea020000418942200fb7811003000041894224488b818803000049894230488b819003000049894238488b819803000049894240488b81a003000049894260488b81a803000049894268488b81b003000049894270488b814004000049894278488b814804000049898280000000488b815004000049898288000000488b81b803000049898290000000488b81c003000049898298000000488b81c8030000498982a0000000488b4424204889818803000049894248488b4424284889819003000049894250488b4424304889819803000049894258498b8310190000498982a8000000498b8318190000498982b0000000498b8320190000498982b8000000f2410f1182c0000000488b442458498982c8000000498b82f8000000498902eb24488b44242048898188030000488b44242848898190030000488b44243048898198030000f30f6f0424f30f6f4c24104883c460415b415a589d415741565657534881ec90010000ff25000000004444444444444444"
)
TEMPLATE_SHA256 = "0d5cd78524dbb3db21c6e2dc71c78668c90ffa718c303b330b22fe814fef2165"
# Sentinel -> value name, and the expected number of occurrences.
SENTINELS = (
    (0x1111111111111111, "buffer", 2),
    (0x2222222222222222, "receiver_table", 1),
    (0x3333333333333333, "weapon", 1),
    (0x4444444444444444, "resume", 1),
    (0x5555555555555555, "depth_control", 2),
    (0x6666666666666666, "rotation_offset", 1),
)
# Buffer layout beyond the 64 records (0x20 + 64 * 0x100 = 0x4020).
DEPTH_COUNTERS = 0x4100  # qwords: [status 0 off, 1 applied, 2 out of range]
DEPTH_LAST = 0x4118      # double depth, 3 doubles camera, 3 doubles written origin
DISABLED_CONTROL = 0x4F00  # zero qword: depth off when no shared control exists
CAMERA_CACHE_LOCATION = 0x1910


def recorder(buffer, weapon, receiver_table, resume, depth_control, rotation_offset):
    """Relocate the verified origin template for the caller's live native owner.

    Buffer, weapon and receiver-table addresses remain pinned by the owner.
    The resume address identifies the validated executable entry, not a scan guess.
    depth_control is the shared aim-trace control block (or a zero qword in the
    buffer); rotation_offset is the manager offset of CameraCachePrivate.POV.Rotation.
    """
    if hashlib.sha256(TEMPLATE).hexdigest() != TEMPLATE_SHA256:
        raise RuntimeError("Beam origin template hash mismatch")
    values = dict(buffer=buffer, weapon=weapon, receiver_table=receiver_table,
                  resume=resume, depth_control=depth_control,
                  rotation_offset=rotation_offset)
    code = TEMPLATE
    for sentinel, name, expected in SENTINELS:
        raw = struct.pack("<Q", sentinel)
        if code.count(raw) != expected:
            raise RuntimeError("Beam origin template sentinel count differs: " + name)
        code = code.replace(raw, struct.pack("<Q", int(values[name])))
    if code[-14:-8] != b"\xff\x25\x00\x00\x00\x00" or code[-8:] != struct.pack("<Q", resume):
        raise RuntimeError("Beam origin template tail differs")
    if code[-14 - len(ORIGINAL):-14] != ORIGINAL:
        raise RuntimeError("Beam origin template does not replay the entry bytes")
    return code


def _fields(struct_type):
    """Reflected properties of a class or struct, including super structs."""
    return {
        str(prop.Name): prop
        for owner in (struct_type, *tuple(struct_type._superfields()))
        for prop in owner._properties()
    }


def camera_cache_layout(manager_class):
    """(location, rotation) manager offsets of CameraCachePrivate.POV by reflection."""
    cache = _fields(manager_class).get("CameraCachePrivate")
    if cache is None or str(cache.Class.Name) != "StructProperty":
        raise RuntimeError("CameraCachePrivate not reflected")
    pov = _fields(cache.Struct).get("POV")
    if pov is None or str(pov.Class.Name) != "StructProperty":
        raise RuntimeError("CameraCacheEntry.POV not reflected")
    view = _fields(pov.Struct)
    location, rotation = view.get("Location"), view.get("Rotation")
    if location is None or rotation is None:
        raise RuntimeError("MinimalViewInfo Location/Rotation not reflected")
    if str(rotation.Struct.Name) != "Rotator":
        raise RuntimeError("POV.Rotation is not a Rotator")
    rotator = _fields(rotation.Struct)
    for name, offset in (("Pitch", 0), ("Yaw", 8)):
        field = rotator.get(name)
        if field is None or str(field.Class.Name) != "DoubleProperty" or int(
            field.Offset_Internal
        ) != offset:
            raise RuntimeError("Rotator layout differs: " + name)
    base = int(cache.Offset_Internal) + int(pov.Offset_Internal)
    return base + int(location.Offset_Internal), base + int(rotation.Offset_Internal)


def depth_source(camera, manager_address, read, control):
    """Validate the depth inputs for the stub; never raises.

    Returns enabled/reason plus the control address and rotation offset to
    relocate. Disabled sources keep the original camera-position write.
    """
    result = dict(enabled=False, reason=None, control=None, rotation_offset=CAMERA_CACHE_LOCATION)
    try:
        if not control:
            raise RuntimeError("shared aim control unavailable")
        location_offset, rotation_offset = camera_cache_layout(camera.Class)
        if location_offset != CAMERA_CACHE_LOCATION:
            raise RuntimeError("POV.Location offset %#x differs from measured 0x1910" % location_offset)
        if not 0x1910 < rotation_offset < 0x3000:
            raise RuntimeError("POV.Rotation offset %#x outside the camera cache" % rotation_offset)
        pov = camera.CameraCachePrivate.POV
        live_location = struct.unpack("<3d", read(manager_address + location_offset, 24))
        live_rotation = struct.unpack("<3d", read(manager_address + rotation_offset, 24))
        expected_location = (float(pov.Location.X), float(pov.Location.Y), float(pov.Location.Z))
        expected_rotation = (float(pov.Rotation.Pitch), float(pov.Rotation.Yaw), float(pov.Rotation.Roll))
        for live, expected in ((live_location, expected_location), (live_rotation, expected_rotation)):
            if not all(math.isfinite(v) and abs(v - e) <= 1e-6 for v, e in zip(live, expected)):
                raise RuntimeError("Camera cache bytes differ from reflected POV")
        # Armed: the stub shifts while the shared control is enabled (bl4tps_aim).
        result.update(enabled=True, reason="armed", control=int(control),
                      rotation_offset=int(rotation_offset))
    except (AttributeError, RuntimeError, OSError, TypeError, ValueError, struct.error) as exc:
        result["reason"] = repr(exc)[:200]
    return result


def depth_counters(read):
    """Beam depth counters of the live owner, or None when no beam owner exists."""
    state = sys.modules.get(KEY)
    if state is None or not getattr(state, "buffer", 0):
        return None
    raw = read(state.buffer + DEPTH_COUNTERS, 0x50)
    off, applied, skipped = struct.unpack_from("<3Q", raw, 0)
    depth = struct.unpack_from("<d", raw, 0x18)[0]
    camera = list(struct.unpack_from("<3d", raw, 0x20))
    origin = list(struct.unpack_from("<3d", raw, 0x38))
    info = getattr(state, "depth", {}) or {}
    return dict(enabled=bool(info.get("enabled")), reason=info.get("reason"),
                off=off, applied=applied, skipped=skipped, last_depth=depth,
                last_camera=camera, last_origin=origin)


def apply_or_restore():
    """Toggle the query-origin detour under its build/weapon/camera guards.

    Restore an existing registry owner without writing through a saved receiver.
    The coordinator must release collision first and interpret action/errors
    explicitly; an exception or refusal never proves native resources released.
    """
    report = {
        "version": "owned-firebeam-origin",
        "action": "REFUSED",
        "verified": False,
        "errors": [],
        "sdk_hooks": 0,
        "camera_flag_writes": 0,
        "native_patches": 0,
        "scope": "TPS query origin override at A640F0 entry; native endpoint calculation follows",
        "limit": LIMIT,
        "records": [],
        "game_write_scope": "receiver+388 position only while eligible TPS beam calls execute",
    }
    state = sys.modules.get(KEY)
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        ptr, size = ctypes.c_void_p, ctypes.c_size_t
        signatures = {
            "GetModuleHandleW": ([ctypes.c_wchar_p], ptr),
            "GetCurrentProcess": ([], ptr),
            "ReadProcessMemory": (
                [ptr, ptr, ptr, size, ctypes.POINTER(size)],
                ctypes.c_int,
            ),
            "WriteProcessMemory": (
                [ptr, ptr, ptr, size, ctypes.POINTER(size)],
                ctypes.c_int,
            ),
            "VirtualProtect": (
                [ptr, size, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)],
                ctypes.c_int,
            ),
            "FlushInstructionCache": ([ptr, ptr, size], ctypes.c_int),
            "VirtualAlloc": ([ptr, size, ctypes.c_ulong, ctypes.c_ulong], ptr),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(k, name)
            fn.argtypes, fn.restype = args, result
        handle = k.GetCurrentProcess()
        base = int(k.GetModuleHandleW(None) or 0)
        if not base:
            raise RuntimeError("Main module unavailable")

        def read(address, count):
            if address < 0x10000 or not 0 < count <= 0x10000:
                raise RuntimeError("Read outside bounds")
            buf, got = ctypes.create_string_buffer(count), size()
            if (
                not k.ReadProcessMemory(handle, address, buf, count, ctypes.byref(got))
                or got.value != count
            ):
                raise OSError("ReadProcessMemory failed")
            return buf.raw

        def qword(address):
            return struct.unpack("<Q", read(address, 8))[0]

        dos = read(base, 64)
        off = struct.unpack_from("<I", dos, 60)[0]
        if dos[:2] != b"MZ" or not 64 <= off <= 0x100000:
            raise RuntimeError("DOS header mismatch")
        pe = read(base + off, 0x60)
        fingerprint = (
            struct.unpack_from("<I", pe, 8)[0],
            struct.unpack_from("<I", pe, 24 + 56)[0],
            struct.unpack_from("<H", pe, 4)[0],
        )
        if (
            pe[:4] != b"PE\0\0"
            or struct.unpack_from("<H", pe, 24)[0] != 0x20B
            or fingerprint != EXPECTED
        ):
            raise RuntimeError("Build fingerprint mismatch; no patch attempted")
        report["build"] = [hex(v) for v in fingerprint]
        section_count = struct.unpack_from("<H", pe, 6)[0]
        optional_size = struct.unpack_from("<H", pe, 20)[0]
        if not 1 <= section_count <= 96 or not 64 <= optional_size <= 4096:
            raise RuntimeError("Unexpected PE layout")
        section_data = read(base + off + 24 + optional_size, section_count * 40)
        executable = []
        for i in range(section_count):
            virtual_size, rva, raw_size = struct.unpack_from(
                "<III", section_data, i * 40 + 8
            )
            flags = struct.unpack_from("<I", section_data, i * 40 + 36)[0]
            span = max(virtual_size, raw_size)
            if flags & 0x20000000 and 0 < span and rva + span <= EXPECTED[1]:
                executable.append((base + rva, base + rva + span))
        address = base + RVA

        patch = state.patch if state is not None else None

        def write(where, data):
            if where != address or data not in (ORIGINAL, patch):
                raise RuntimeError("Write outside exact capture callsite")
            old = ctypes.c_ulong()
            if not k.VirtualProtect(where, len(data), 0x40, ctypes.byref(old)):
                raise OSError("VirtualProtect failed")
            try:
                buf, done = ctypes.create_string_buffer(data), size()
                if not k.WriteProcessMemory(
                    handle, where, buf, len(data), ctypes.byref(done)
                ) or done.value != len(data):
                    raise OSError("WriteProcessMemory failed")
                if not k.FlushInstructionCache(handle, where, len(data)):
                    raise OSError("FlushInstructionCache failed")
            finally:
                unused = ctypes.c_ulong()
                if not k.VirtualProtect(
                    where, len(data), old.value, ctypes.byref(unused)
                ):
                    raise OSError("Page protection restore failed; restart game")

        # Restore is available even if the mod/pawn/weapon is no longer loaded.
        if state is not None:
            if state.base != base:
                raise RuntimeError("Saved patch belongs to another module base")
            current = read(address, len(ORIGINAL))
            if current == patch:
                _exchange_owned_bytes(read, write, address, patch, ORIGINAL)
            elif current != ORIGINAL:
                raise RuntimeError(
                    "Restore refused: bytes changed by another writer; restart game"
                )
            report.update(
                action="RESTORE", verified=read(address, len(ORIGINAL)) == ORIGINAL
            )
            # Keep code/buffer pinned until process exit: an in-flight call may still return.
            retired = sys.modules.get(RETIRED)
            if retired is None:
                retired = types.ModuleType(RETIRED)
                retired.allocations = []
                sys.modules[RETIRED] = retired
            retired.allocations.append(state)
            report["observed_calls"] = qword(state.buffer)
            report["origin_write_count"] = report["observed_calls"]
            report["all_callsite_visits"] = qword(state.buffer + 8)
            report["receiver_class_visits"] = qword(state.buffer + 16)
            report["record_note"] = (
                "First 64 eligible origin writes retained; later writes counted and still applied until restore. Native source update regenerates origin after code restoration."
            )
            report["dropped_by_limit"] = max(0, report["observed_calls"] - LIMIT)
            report["depth"] = depth_counters(read)
            report["action"] = "RESTORED"
            del sys.modules[KEY]
            report["capture_context"] = state.context

        else:
            if (
                hashlib.sha256(read(base + 0xA640F0, 0xF00)).hexdigest()
                != "b03bd28f293342d4b2bb6046053969afb0afa3a0758eb3551020a8b9b4abf2cd"
            ):
                raise RuntimeError("Component transfer code fingerprint changed")
            if read(address, len(ORIGINAL)) != ORIGINAL:
                raise RuntimeError("Capture site differs from original bytes")
            if read(base + ANCHOR_RVA, len(ANCHOR)) != ANCHOR:
                raise RuntimeError("Measured component callsite changed")
            mod = sys.modules.get("BL4ThirdPersonPOC")
            if mod is None or getattr(mod, "_third_person_enabled", None) not in (
                True,
                False,
            ):
                raise RuntimeError("Load the mod and enter settled gameplay first")
            pc, pawn, cam = mod._get_runtime()
            if any(obj is None for obj in (pc, pawn, cam)):
                raise RuntimeError("Loaded gameplay required")
            pa, ca, ma = (int(obj._get_address()) for obj in (pawn, pc, cam))
            if qword(ca + 0x3D0) != pa or qword(ca + 0x2500) != ma:
                raise RuntimeError("Controller/pawn/manager identity mismatch")
            for obj, slot, rva in (
                (ca, 0x7A0, 0xC8D630),
                (ca, 0x788, 0x4A5B172),
                (pa, 0x720, 0xC52566),
                (ma, 0x878, 0x4904A5C),
            ):
                if qword(qword(obj) + slot) != base + rva:
                    raise RuntimeError("Measured virtual method changed")
            runtime = qword(ma + 0x3A48)
            definition = qword(runtime + 0x10) if runtime else 0
            if not definition:
                raise RuntimeError("Camera definition unavailable")
            first_person = bool(read(definition + 0x1C, 1)[0] & 2)
            if first_person == bool(mod._third_person_enabled):
                raise RuntimeError(
                    "Use settled TPS or FPS without ADS or a perspective override"
                )
            if first_person or not mod._third_person_enabled:
                raise RuntimeError("owned-firebeam-origin requires normal TPS, no ADS")
            weapon = cam.CameraModeInputs.Weapon
            if weapon is None:
                raise RuntimeError("Equip the same Beam weapon")
            wa = int(weapon._get_address())
            data, count, capacity = struct.unpack("<Qii", read(wa + 0xBE8, 16))
            index = read(wa + 0xBD8, 1)[0]
            if not 0 <= index < count <= capacity <= 32:
                raise RuntimeError("Weapon use-mode bounds differ")
            fire = qword(data + index * 0x88 + 8)
            if (
                not fire
                or qword(fire + 0x30) != wa
                or qword(qword(fire) + 0x410) != base + 0x4344586
            ):
                raise RuntimeError(
                    "Current weapon is not the measured FireBeam implementation"
                )
            report["before"] = {
                "first_person": first_person,
                "weapon": str(weapon._path_name()),
                "attach_component": str(
                    cam.CameraModeInputs.AttachComponent._path_name()
                ),
            }
            if qword(wa + 0x1B0) != pa or qword(pa + 0x3C0) != ca:
                raise RuntimeError(
                    "Live camera lookup chain differs from measured objects"
                )
            if (
                qword(base + 0xB7931C0 + 0x300) != base + 0x1438B2C
                or qword(base + 0xB7931C0 + 0x308) != base + 0x13E5A42
            ):
                raise RuntimeError("Measured receiver vtable changed")
            if read(base + 0x1438C61, 4) != bytes.fromhex("498b4e20") or read(
                base + 0x1438C6D, 7
            ) != bytes.fromhex("48898bc8000000"):
                raise RuntimeError("Receiver weapon field copy changed")
            if qword(base + 0xB7931C0 + 0x368) != base + RVA:
                raise RuntimeError("Endpoint producer dispatch changed")
            state = types.ModuleType(KEY)
            state.base = base
            state.context = report["before"]
            state.buffer = int(k.VirtualAlloc(None, 0x5000, 0x3000, 0x04) or 0)
            state.code = int(k.VirtualAlloc(None, 0x1000, 0x3000, 0x04) or 0)
            if not state.buffer or not state.code:
                raise OSError("Recorder allocation failed; no game code changed")
            # Depth inputs: the shared aim-trace control block (pawn position,
            # margin, on/off) and the reflected POV.Rotation offset.
            try:
                from . import native_aim_origin

                control = native_aim_origin.shared_control(native_aim_origin.Native())
            except (ImportError, OSError, RuntimeError, AttributeError) as exc:
                control = 0
                logging.warning(f"{TAG} BEAM_DEPTH control unavailable: {exc!r}"[:300])
            depth = depth_source(cam, ma, read, control)
            depth_control = depth["control"] if depth["enabled"] else state.buffer + DISABLED_CONTROL
            state.depth = dict(enabled=depth["enabled"], reason=depth["reason"],
                               rotation_offset=hex(depth["rotation_offset"]))
            report["depth"] = state.depth
            blob = recorder(state.buffer, wa, base + 0xB7931C0, address + len(ORIGINAL),
                            depth_control, depth["rotation_offset"])
            ctypes.memmove(state.code, blob, len(blob))
            old = ctypes.c_ulong()
            if not k.VirtualProtect(state.code, 0x1000, 0x20, ctypes.byref(old)):
                raise OSError("Recorder executable protection failed")
            if not k.FlushInstructionCache(handle, state.code, len(blob)):
                raise OSError("Recorder instruction-cache flush failed")
            patch = _native_absolute_jump(state.code) + b"\x90" * (len(ORIGINAL) - 14)
            state.patch = patch
            state.fire = fire
            sys.modules[KEY] = state  # recovery metadata precedes the code write
            _exchange_owned_bytes(read, write, address, ORIGINAL, patch)
            if bool(read(definition + 0x1C, 1)[0] & 2) != first_person:
                _exchange_owned_bytes(read, write, address, patch, ORIGINAL)
                raise RuntimeError(
                    "Perspective changed during apply; patch restored; run again to retire capture state"
                )
            report.update(action="TPS_QUERY_ORIGIN_ON", verified=True, native_patches=1)
            logging.info(
                f"{TAG} BEAM_DEPTH enabled={state.depth['enabled']} "
                f"reason={state.depth['reason']} rotation={state.depth['rotation_offset']}"
            )
        report["bytes"] = read(address, len(ORIGINAL)).hex()
    except Exception as exc:
        report["errors"].append(str(exc))
        report["recovery_state_present"] = KEY in sys.modules
    if report["errors"] and (state is not None or report.get("recovery_state_present")):
        logging.warning(f'{TAG} action={report["action"]} error={report["errors"]}')

    return report
