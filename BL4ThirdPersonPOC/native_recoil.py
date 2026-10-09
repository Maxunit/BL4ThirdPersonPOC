"""Apply the measured WeaponLook update to the locally owned TPS Look.

Keep the Look object's type, size and other virtual slots unchanged. A private
vtable replaces only the verified update slot; reflected layout, full function
hashes, executable fingerprint, stack membership and UObject serials gate setup.
The native handoff guard restores that exact private vtable before runtime loss.
FFYL contexts authorize a separate upper-TPS selection; retained lower owners
permit restoration only. Restore before invalidating camera/weapon ownership.
Private vtables and native pins remain reachable after release; disagreements
retain recovery evidence instead of guessing at a raw saved object address.
"""

import hashlib
import ctypes
import struct
from .build_gate import REVIEWED_BUILD
import sys
import types
import traceback
import time
from unrealsdk import find_object, find_all, logging
from unrealsdk.unreal import WeakPointer

TAG = "[BL4ThirdPersonPOC.Recoil]"
EXPECTED = REVIEWED_BUILD
NAMES = ("PushActorCameraMode", "PushActorCameraModeDef", "GetActorCameraMode")
# Cache SDK reflection descriptions only. Live mode, runtime, Look, build
# code bytes and native guard ownership are still checked on every arm.
_SCHEMA_CACHE = None


def cached_type_slot(getter, code):
    """Recognize the measured cached-type getter entries without executing them."""
    start = 0
    if code[:6] == bytes.fromhex("e901000000cc"):
        start = 6
    body = code[start:]
    if body[:7] == bytes.fromhex("4883ec28488b05") and body[11:21] == bytes.fromhex(
        "4885c074054883c428c3"
    ):
        return getter + start + 11 + struct.unpack_from("<i", body, 7)[0]
    if body[:3] == bytes.fromhex("488b05") and body[7:8] == b"\xc3":
        return getter + start + 7 + struct.unpack_from("<i", body, 3)[0]
    raise RuntimeError("Unrecognized type getter entry; no native call attempted")


def decode_fields(data, schema):
    fields = {}
    for field in schema["fields"]:
        name, offset, size, dim = (
            field["name"],
            field["offset"],
            field["element_size"],
            field["array_dim"],
        )
        if offset < 0 or size <= 0 or dim <= 0 or offset + size * dim > len(data):
            raise RuntimeError("Behavior field outside schema bounds: " + name)
        raw = data[offset : offset + size * dim]
        value = {"kind": field["kind"], "raw_hex": raw.hex()}
        if dim == 1:
            kind = field["kind"]
            if kind == "BoolProperty":
                mask = field["mask"]
                if not 0 < mask < (1 << (size * 8)):
                    raise RuntimeError("Behavior bool mask outside bounds: " + name)
                value["value"] = bool(int.from_bytes(raw, "little") & mask)
            elif kind == "FloatProperty" and size == 4:
                value["value"] = struct.unpack("<f", raw)[0]
            elif kind == "DoubleProperty" and size == 8:
                value["value"] = struct.unpack("<d", raw)[0]
            elif kind in (
                "IntProperty",
                "Int8Property",
                "Int16Property",
                "Int64Property",
                "UInt16Property",
                "UInt32Property",
                "UInt64Property",
                "ByteProperty",
                "EnumProperty",
            ):
                value["numeric_value"] = int.from_bytes(
                    raw, "little", signed=kind.startswith("Int")
                )
        fields[name] = value
    return fields


def select_owned_ffyl_runtime(report, raw, manager_address, saved_identity):
    """Resolve the previously owned TPS Look while FFYL has entered the stack.

    This is only called for an explicitly requested restore. Every reference
    comes from the current, coherent stack snapshot; no saved pointer is read
    until its live stack membership has been established.
    """
    if len(saved_identity) != 4 or saved_identity[0] != manager_address:
        raise RuntimeError("FFYL restore owner manager changed")
    stack = report["stack"]
    if stack["count"] != 2 or len(stack["items"]) != 2 or len(raw) != 0x50:
        raise RuntimeError("FFYL restore expects exactly two live stack entries")
    rows = report["runtime_candidates"]
    if len(rows) != 3 or [row["source"] for row in rows] != [
        "stack_0",
        "stack_1",
        "manager_slot_3a48",
    ]:
        raise RuntimeError("FFYL runtime snapshot incomplete")
    owner_matches = [
        index
        for index in range(2)
        if int(rows[index]["instance"], 16) == saved_identity[1]
    ]
    if len(owner_matches) != 1:
        raise RuntimeError("Owned TPS runtime absent or duplicated in FFYL stack")
    index = owner_matches[0]
    owner, current = rows[index], rows[2]
    if rows[1 - index]["instance"] == owner["instance"]:
        raise RuntimeError("FFYL stack aliases TPS runtime")
    if (
        current["instance"] != owner["instance"]
        or current["control"] != owner["control"]
        or report["mode_fname_hex"] != raw[index * 0x28 : index * 0x28 + 8].hex()
    ):
        raise RuntimeError("FFYL current camera no longer owns saved TPS runtime")
    if (
        owner.get("transition") != "0x0"
        or current.get("transition") != "0x0"
        or owner.get("self_reference_matches") is not True
        or owner.get("control_matches") is not True
    ):
        raise RuntimeError("Owned TPS runtime is transitioning or changed")
    definition = report["definitions"].get(owner.get("definition"))
    if definition is None or definition["fields"]["bIsFirstPerson"]["value"]:
        raise RuntimeError("FFYL owner is not a third-person definition")
    runtime_key = owner["instance"]
    candidates = [
        (runtime_key, row, item)
        for row in report["runtime_behavior_lists"][runtime_key]
        for item in row["items"]
        if item.get("type_path") == "/Script/GbxGame.CameraModeBehavior_Look"
    ]
    if (
        len(candidates) != 1
        or candidates[0][1]["offset"] != "0x20"
        or int(candidates[0][2]["address"], 16) != saved_identity[2]
        or int(candidates[0][2]["control"], 16) != saved_identity[3]
    ):
        raise RuntimeError("FFYL TPS Look identity changed")
    return [owner, current], [definition], candidates


def _select_owned_retained_tps_runtime(
    report, raw, manager_address, saved_state, *, expected_mode
):
    """Restore only a retained TPS owner under an explicitly allowed camera.

    The lower TPS runtime/Look remains intact while the current camera
    belongs to the upper camera entry. Membership, descriptor, controller and
    saved Look identity must all match a coherent live snapshot. This path
    never activates Recoil and does not modify the upper runtime or stack.
    """
    identity = tuple(getattr(saved_state, "identity", ()))
    if (
        not getattr(saved_state, "active", False)
        or len(identity) != 4
        or identity[0] != manager_address
    ):
        raise RuntimeError("Retained TPS restore owner manager changed or inactive")
    if (
        expected_mode not in ("GroundSlamExit", "DeathCamera")
        or report.get("mode_name") != expected_mode
    ):
        raise RuntimeError(f"Retained TPS restore requires measured {expected_mode} mode")
    if (
        report["stack"]["count"] != 2
        or len(report["stack"]["items"]) != 2
        or len(raw) != 0x50
    ):
        raise RuntimeError("Retained TPS restore expects exactly two live stack entries")
    descriptor = getattr(saved_state, "stack_descriptor", None)
    runtime_control = getattr(saved_state, "runtime_control", None)
    if not descriptor or raw[:24].hex() != descriptor or not runtime_control:
        raise RuntimeError(
            "Retained TPS saved TPS descriptor/controller absent or changed"
        )
    rows = report["runtime_candidates"]
    if len(rows) != 3 or [row["source"] for row in rows] != [
        "stack_0",
        "stack_1",
        "manager_slot_3a48",
    ]:
        raise RuntimeError("Retained TPS runtime snapshot incomplete")
    owner, top, current = rows
    if (
        int(owner["instance"], 16) != identity[1]
        or int(owner["control"], 16) != runtime_control
        or top["instance"] == owner["instance"]
        or top["control"] == owner["control"]
        or current["instance"] != top["instance"]
        or current["control"] != top["control"]
        or report["mode_fname_hex"] != raw[0x28:0x30].hex()
        or raw[:8] == raw[0x28:0x30]
    ):
        raise RuntimeError("Retained TPS owner/top/current stack identity mismatch")
    if any(
        row.get("transition") != "0x0"
        or row.get("self_reference_matches") is not True
        or row.get("control_matches") is not True
        or row.get("runtime_unchanged") is not True
        for row in rows
    ):
        raise RuntimeError("Retained TPS runtime transitioning or changed")
    definition = report["definitions"].get(owner.get("definition"))
    if definition is None or definition["fields"]["bIsFirstPerson"]["value"]:
        raise RuntimeError("Retained TPS saved owner is not third person")
    runtime_key = owner["instance"]
    candidates = [
        (runtime_key, row, item)
        for row in report["runtime_behavior_lists"][runtime_key]
        for item in row["items"]
        if item.get("type_path") == "/Script/GbxGame.CameraModeBehavior_Look"
    ]
    if (
        len(candidates) != 1
        or candidates[0][1]["offset"] != "0x20"
        or int(candidates[0][2]["address"], 16) != identity[2]
        or int(candidates[0][2]["control"], 16) != identity[3]
        or int(candidates[0][2]["vtable"], 16) != saved_state.shadow_vt
    ):
        raise RuntimeError("Retained TPS retained TPS Look identity/vtable changed")
    return [owner], [definition], candidates


def select_owned_ground_slam_runtime(report, raw, manager_address, saved_state):
    return _select_owned_retained_tps_runtime(
        report, raw, manager_address, saved_state, expected_mode="GroundSlamExit"
    )


def select_owned_death_runtime(report, raw, manager_address, saved_state):
    """Release the lower, still-owned TPS Look during direct death; restore only."""
    return _select_owned_retained_tps_runtime(
        report, raw, manager_address, saved_state, expected_mode="DeathCamera"
    )


def resolve_restore_manager(state, current_manager):
    """Use a serial-checked UObject weak reference, never a saved raw manager."""
    identity = tuple(getattr(state, "identity", ()))
    weak = getattr(state, "manager_ref", None)
    if len(identity) != 4 or not callable(weak):
        raise RuntimeError("Native owner lacks verified manager weak reference")
    owner = weak()
    if owner is None:
        # Keep all private VTable buffers pinned. No old runtime/Look read or
        # write is allowed once the owning UObject's serial is invalidated.
        return None
    if int(owner._get_address()) != identity[0]:
        raise RuntimeError("Native owner weak-reference identity differs")
    return owner


def apply_or_restore(
    *,
    allow_stacked_ffyl=False,
    allow_stacked_ground_slam=False,
    allow_stacked_death=False,
    allow_owner_manager=False,
    ffyl_context=None,
):
    """Apply or restore the single production recoil implementation.

    The optional context enables only a serial-bound, observed FFYL upper-TPS
    route. Normal callers retain the one-mode gate. An active owner carries its
    context into restoration automatically; a caller cannot replace that binding.
    The retained lower-layer selector remains restore-only.
    """
    global _SCHEMA_CACHE
    started_ns = time.perf_counter_ns()
    schema_key = None
    schema_cache_hit = False
    schema_scan_ms = None
    report = {
        "version": "owned-tps-weaponlook-update",
        "functions": {},
        "definitions": {},
        "errors": [],
        "limits": [],
        "native_patches": 0,
        "sdk_hooks": 0,
        "game_writes": 0,
        "note": "TPS Look update only -> native WeaponLook Update via private vtable. First call applies; second restores. Beam effect unproven.",
    }
    guard_installed = False
    guard_mod = None
    state = None
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
            if not 0 < size <= 0x10000 or address <= 0:
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
        mod = sys.modules.get("BL4ThirdPersonPOC")
        if mod is None:
            raise RuntimeError("Load the existing mod first")
        _pc, pawn, cam = mod._get_runtime()
        saved_owner = sys.modules.get("_bl4_tps_recoil_owner")
        if (
            allow_owner_manager
            and saved_owner is not None
            and getattr(saved_owner, "active", False)
        ):
            owner_cam = resolve_restore_manager(saved_owner, cam)
            if owner_cam is None:
                saved_owner.active = False
                report.update(
                    action="RETIRED",
                    owner_destroyed_verified=True,
                    restore_pending=False,
                    ab_verified=False,
                )
                logging.info(
                    "[BL4ThirdPersonPOC] RECOIL_OWNER_RETIRED "
                    "manager_weak_expired=True stale_pointer_reads=0 "
                    "game_writes=0 private_buffers_retained=True"
                )
                return report
            if cam is None or int(cam._get_address()) != int(owner_cam._get_address()):
                logging.info("[BL4ThirdPersonPOC] RECOIL_RESTORE_ORIGINAL_MANAGER")
            cam = owner_cam
        if pawn is None or cam is None:
            raise RuntimeError("Run in loaded gameplay")
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
        behavior_prop = next(
            p for p in meta._properties() if str(p.Name) == "behaviors"
        )
        inner = behavior_prop.Inner
        stride = int(inner.ElementSize)
        report["behavior_inner"] = {"kind": str(inner.Class.Name), "stride": stride}
        if str(inner.Class.Name) != "GbxInlineStructProperty" or stride != 24:
            raise RuntimeError("Behavior element differs from measured inline layout")
        base_type = inner.MetaStruct
        report["behavior_inner"]["meta_struct"] = str(base_type._path_name())
        report["behavior_definitions"] = {}
        report["behavior_type_schemas"] = {}
        schema_key = (
            base,
            timestamp,
            image_size,
            machine,
            int(meta._get_address()),
            int(base_type._get_address()),
            stride,
            report["behavior_inner"]["meta_struct"],
        )
        schema_started_ns = time.perf_counter_ns()
        if _SCHEMA_CACHE is not None and _SCHEMA_CACHE["key"] == schema_key:
            report["behavior_type_schemas"] = _SCHEMA_CACHE["schemas"]
            schema_cache_hit = True
        else:
            # SDK enumerates existing metadata; no raw pointer wrapping or
            # native getter invocation. No cache is committed until a fully
            # verified activation completes.
            for type_obj in find_all("ScriptStruct", False):
                if not type_obj._inherits(base_type):
                    continue
                if len(report["behavior_type_schemas"]) >= 256:
                    report["limits"].append("Behavior schema limit 256 reached")
                    break
                schema = {
                    "path": str(type_obj._path_name()),
                    "size": int(type_obj.PropertySize),
                    "fields": [],
                }
                report["behavior_type_schemas"][
                    hex(int(type_obj._get_address()))
                ] = schema
                seen_fields = set()
                for owner in type_obj._superfields():
                    for field in owner._properties():
                        name = str(field.Name)
                        if name in seen_fields:
                            continue
                        seen_fields.add(name)
                        info = {
                            "name": name,
                            "kind": str(field.Class.Name),
                            "offset": int(field.Offset_Internal),
                            "element_size": int(field.ElementSize),
                            "array_dim": int(field.ArrayDim),
                        }
                        if info["kind"] == "BoolProperty":
                            info["mask"] = int(field.FieldMask)
                        schema["fields"].append(info)
        schema_scan_ms = (time.perf_counter_ns() - schema_started_ns) / 1e6

        runtime_layout_anchors = {
            "0x14498f0": "498d57204889942490000000498d573048899424980000004c8b6028488d0449",
            "0x1449a83": "41807e1101742a49635f388d430141894738413b473c760f488b8c2498000000",
            "0x1449adc": "488b0048c1e3044c89341848897c18084885ff740ef0ff4708f0ff4f080f8454",
        }
        for rva, expected in runtime_layout_anchors.items():
            if (
                read(base + int(rva, 16), len(bytes.fromhex(expected))).hex()
                != expected
            ):
                raise RuntimeError("Runtime behavior layout changed: " + rva)
        report["runtime_layout_anchors_verified"] = runtime_layout_anchors
        report["runtime_behavior_lists"] = {}

        def read_runtime_behaviors(pointer):
            key = hex(pointer)
            if key in report["runtime_behavior_lists"]:
                return
            lists = []
            report["runtime_behavior_lists"][key] = lists
            # Constructor chooses +0x20 when bUpdatePreViewTarget==1, otherwise +0x30.
            # Stored records are pairs (copied behavior, shared controller), stride 16.
            for offset in (0x20, 0x30):
                header = read(pointer + offset, 16)
                ap, ac, am = struct.unpack("<Qii", header)
                row = {
                    "offset": hex(offset),
                    "data": hex(ap),
                    "count": ac,
                    "capacity": am,
                    "items": [],
                }
                lists.append(row)
                if not 0 <= ac <= am <= 256 or ac > 64 or (ac and not ap):
                    raise RuntimeError("Runtime behavior list outside bounds")
                entries = read(ap, ac * 16) if ac else b""
                for index in range(ac):
                    instance, control = struct.unpack_from("<QQ", entries, index * 16)
                    item = {
                        "index": index,
                        "address": hex(instance),
                        "control": hex(control),
                    }
                    row["items"].append(item)
                    try:
                        if not instance or not control:
                            raise RuntimeError("Null runtime behavior pair")
                        vt = struct.unpack("<Q", read(instance, 8))[0]
                        getter = struct.unpack("<Q", read(vt + 8, 8))[0]
                        if not any(
                            a <= getter and getter + 64 <= b for a, b in executable
                        ):
                            raise RuntimeError(
                                "Runtime type getter outside executable section"
                            )
                        code = read(getter, 64)
                        cache = cached_type_slot(getter, code)
                        if not base <= cache <= base + image_size - 8:
                            raise RuntimeError("Runtime type cache outside main module")
                        type_ptr = struct.unpack("<Q", read(cache, 8))[0]
                        schema = report["behavior_type_schemas"].get(hex(type_ptr))
                        if schema is None:
                            raise RuntimeError(
                                "Runtime type absent from loaded behavior schemas"
                            )
                        item.update(
                            type_path=schema["path"],
                            vtable=hex(vt),
                            type_address=hex(type_ptr),
                        )
                        if not schema["path"].endswith(
                            (
                                "_OffsetToSocket",
                                "_WeaponLook",
                                "_Look",
                                "_OffsetCrosshair",
                            )
                        ):
                            item["skipped"] = (
                                "Type recorded; values outside selected comparison"
                            )
                            continue
                        if not 24 <= schema["size"] <= 4096:
                            raise RuntimeError("Selected runtime schema outside bounds")
                        data = read(instance, schema["size"])
                        item["hex"] = data.hex()
                        item["fields"] = decode_fields(data, schema)
                        item["unchanged_on_reread"] = read(instance, len(data)) == data
                        if not item["unchanged_on_reread"]:
                            report["limits"].append(
                                "Live behavior changed during read: " + hex(instance)
                            )
                    except Exception as exc:
                        item["error"] = str(exc)
                        report["errors"].append(
                            {
                                "scope": "runtime_" + hex(offset) + "_" + str(index),
                                "error": str(exc),
                            }
                        )
                row["header_unchanged"] = read(pointer + offset, 16) == header
                row["entries_unchanged"] = not ac or read(ap, len(entries)) == entries
                if not row["header_unchanged"] or not row["entries_unchanged"]:
                    report["limits"].append("Runtime behavior list changed during read")

        def read_behaviors(result, definition_data):
            offset = int(behavior_prop.Offset_Internal)
            ap, ac, am = struct.unpack_from("<Qii", definition_data, offset)
            if not 0 <= ac <= am <= 4096 or ac > 64 or (ac and not ap):
                raise RuntimeError("Behavior array outside bounds")
            entries = read(ap, ac * stride) if ac else b""
            result["behavior_entries"] = []
            for index in range(ac):
                entry = entries[index * stride : (index + 1) * stride]
                instance, control, flags = struct.unpack("<QQQ", entry)
                item = {
                    "index": index,
                    "hex": entry.hex(),
                    "definition": hex(instance),
                    "control": hex(control),
                    "flags": hex(flags),
                }
                result["behavior_entries"].append(item)
                if not instance or not control:
                    item["skipped"] = "Empty inline struct"
                    continue
                if hex(instance) in report["behavior_definitions"]:
                    continue
                try:
                    vt = struct.unpack("<Q", read(instance, 8))[0]
                    slots = struct.unpack("<QQ", read(vt, 16))
                    bdef = {"vtable": hex(vt), "vtable_slots": [hex(x) for x in slots]}
                    report["behavior_definitions"][hex(instance)] = bdef
                    getter = slots[
                        1
                    ]  # FGbxDef::get_type SDK default slot; recorded, never invoked.
                    if not any(
                        a <= getter and getter + 256 <= b for a, b in executable
                    ):
                        raise RuntimeError(
                            "Type getter candidate outside executable section"
                        )
                    code = read(getter, 256)
                    bdef["type_getter_rva"] = hex(getter - base)
                    bdef["type_getter_hex"] = code.hex()
                    global_address = cached_type_slot(getter, code)
                    if not base <= global_address <= base + image_size - 8:
                        raise RuntimeError("Type cache address outside main image")
                    type_address = struct.unpack("<Q", read(global_address, 8))[0]
                    bdef["type_cache_address"] = hex(global_address)
                    bdef["type_address"] = hex(type_address)
                    exact_schema = report["behavior_type_schemas"].get(
                        hex(type_address)
                    )
                    if exact_schema is None:
                        raise RuntimeError(
                            "Cached type is null or absent from loaded behavior schemas"
                        )
                    bdef["type_path"] = exact_schema["path"]
                    if not bdef["type_path"].endswith(
                        ("_OffsetToSocket", "_WeaponLook", "_Look", "_OffsetCrosshair")
                    ):
                        bdef["skipped"] = "Outside live-copy comparison"
                        continue
                    size = exact_schema["size"]
                    if not 24 <= size <= 4096:
                        raise RuntimeError("Behavior subtype size outside bounds")
                    bdef["window_basis"] = (
                        "Loaded subtype matched to measured cached getter return"
                    )
                    data = read(instance, size)
                    bdef["data_hex"] = data.hex()
                    bdef["fields"] = decode_fields(data, exact_schema)
                    bdef["type_cache_unchanged"] = (
                        struct.unpack("<Q", read(global_address, 8))[0] == type_address
                    )
                    if not bdef["type_cache_unchanged"]:
                        report["limits"].append(
                            "Behavior type cache changed: " + hex(instance)
                        )
                    bdef["bytes"] = size
                    bdef["unchanged_on_reread"] = read(instance, size) == data
                    if not bdef["unchanged_on_reread"]:
                        report["limits"].append("Behavior changed: " + hex(instance))
                except Exception as exc:
                    item["read_error"] = str(exc)
                    report["errors"].append(
                        {"scope": "behavior_" + str(index), "error": str(exc)}
                    )
            result["behavior_entries_unchanged"] = (
                not ac or read(ap, ac * stride) == entries
            )
            if not result["behavior_entries_unchanged"]:
                report["limits"].append("Behavior array changed during read")

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
                read_runtime_behaviors(pointer)
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
                    read_behaviors(result, data)
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

        # Mutation gate: one settled TPS camera, no unresolved/unstable snapshot.
        if report["errors"] or report["limits"]:
            raise RuntimeError("Snapshot incomplete or changed; no A/B write allowed")
        saved_state = sys.modules.get("_bl4_tps_recoil_owner")
        restoring_owned = bool(
            saved_state is not None and getattr(saved_state, "active", False)
        )
        if restoring_owned:
            saved_identity = tuple(getattr(saved_state, "identity", ()))
            saved_runtime = saved_identity[1] if len(saved_identity) == 4 else 0
            logging.warning(
                "[BL4ThirdPersonPOC] FFYL_RECOIL_RESTORE_GATE "
                f"count={count} capacity={capacity} "
                f'current_fname={report["mode_fname_hex"]} '
                f'stack_fnames={[item["hex"][:16] for item in report["stack"]["items"][:6]]!r} '
                f"manager_matches={bool(saved_identity and saved_identity[0] == manager_address)} "
                f'saved_runtime_in_stack={any(row["source"].startswith("stack_") and int(row["instance"], 16) == saved_runtime for row in report["runtime_candidates"])} '
                f"owner_active={restoring_owned} "
                "native_patches=0 diagnostic_writes=0"
            )
        from .ffyl_recoil_context import resolve_ffyl_recoil_context

        bound_ffyl_context = resolve_ffyl_recoil_context(saved_state, ffyl_context)
        ffyl_proof_inputs = None
        if bound_ffyl_context is not None:
            if not restoring_owned:
                if count != 2:
                    raise RuntimeError(
                        "Bound FFYL activation requires exactly two camera layers"
                    )
                bound_ffyl_context.validate_activation_runtime(_pc, pawn, cam)
            ffyl_proof_inputs = bound_ffyl_context.proof_context(
                for_restore=restoring_owned
            )
        upper_ffyl_tps = bool(bound_ffyl_context is not None and count == 2)
        retained_ffyl_tps_restore = bool(
            upper_ffyl_tps
            and restoring_owned
            and raw[:24].hex() == getattr(saved_state, "stack_descriptor", None)
        )
        stacked_ffyl_restore = bool(
            allow_stacked_ffyl and restoring_owned and count == 2
        )
        stacked_ground_slam_restore = bool(
            allow_stacked_ground_slam and restoring_owned and count == 2
        )
        if (
            stacked_ground_slam_restore
            or upper_ffyl_tps
            or (allow_stacked_death and restoring_owned and count == 2)
        ):
            report["mode_name"] = str(cam.GetActorCameraMode(pawn))
        stacked_death_restore = bool(
            allow_stacked_death
            and restoring_owned
            and count == 2
            and bound_ffyl_context is None
            and report.get("mode_name") == "DeathCamera"
        )
        if (
            count != 1
            and not stacked_ffyl_restore
            and not stacked_ground_slam_restore
            and not stacked_death_restore
            and not upper_ffyl_tps
        ) or (report["mod_tps_flag"] is not True and not restoring_owned):
            raise RuntimeError("Requires normal TPS with exactly one pushed mode")
        if stacked_death_restore:
            live, definitions, candidates = select_owned_death_runtime(
                report, raw, manager_address, saved_state
            )
            report["death_stacked_owner_verified"] = True
        elif retained_ffyl_tps_restore:
            from .ffyl_recoil_ownership import select_ffyl_retained_tps_for_restore

            live, definitions, candidates = select_ffyl_retained_tps_for_restore(
                report, raw, manager_address, saved_state, context=ffyl_proof_inputs
            )
            report["ffyl_retained_tps_restore_verified"] = True
        elif upper_ffyl_tps:
            from .ffyl_recoil_ownership import select_ffyl_upper_tps_runtime

            live, definitions, candidates = select_ffyl_upper_tps_runtime(
                report, raw, manager_address, saved_state, context=ffyl_proof_inputs
            )
            report["ffyl_upper_tps_owner_verified"] = True
        elif stacked_ffyl_restore:
            live, definitions, candidates = select_owned_ffyl_runtime(
                report, raw, manager_address, tuple(saved_state.identity)
            )
            report["ffyl_stacked_owner_verified"] = True
        elif stacked_ground_slam_restore:
            live, definitions, candidates = select_owned_ground_slam_runtime(
                report, raw, manager_address, saved_state
            )
            report["ground_slam_stacked_owner_verified"] = True
        else:
            if report["mode_fname_hex"] != raw[:8].hex():
                raise RuntimeError("Current mode differs from sole pushed TPS mode")
            live = report["runtime_candidates"]
            if len(live) != 2 or live[0]["instance"] != live[1]["instance"]:
                raise RuntimeError("Stack and current runtime differ")
            if any(x.get("transition") != "0x0" for x in live):
                raise RuntimeError("Wait for camera transition to finish")
            definitions = list(report["definitions"].values())
            if (
                len(definitions) != 1
                or definitions[0]["fields"]["bIsFirstPerson"]["value"]
            ):
                raise RuntimeError("Expected third-person definition")
            candidates = [
                (key, row, item)
                for key, lists in report["runtime_behavior_lists"].items()
                for row in lists
                for item in row["items"]
                if item.get("type_path") == "/Script/GbxGame.CameraModeBehavior_Look"
            ]
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one active TPS Look copy")
        runtime_key, runtime_row, target = candidates[0]
        if runtime_row["offset"] != "0x20":
            raise RuntimeError("Look is not in measured pre-view-target list")
        address = int(target["address"], 16)
        if target["address"] in report["behavior_definitions"]:
            raise RuntimeError("Live pointer aliases definition")
        weapon_schema = next(
            s
            for s in report["behavior_type_schemas"].values()
            if s["path"] == "/Script/GbxWeapon.CameraModeBehavior_WeaponLook"
        )
        look_schema = next(
            s
            for s in report["behavior_type_schemas"].values()
            if s["path"] == "/Script/GbxGame.CameraModeBehavior_Look"
        )
        if weapon_schema["size"] != 152 or look_schema["size"] != 144:
            raise RuntimeError("Look schema sizes changed")
        for field in look_schema["fields"]:
            if field not in weapon_schema["fields"]:
                raise RuntimeError("WeaponLook base-field layout differs from Look")
        original_vt = base + 0xB3E9C10
        look_update = base + 0x18749F4
        weapon_update = base + 0x5E8862
        entry_anchors = {
            "0x18749f4": "5657534883ec404c89c64889cf488b0538afe80a4831e048894424388a4119a8",
            "0x5e8862": "41565657534883ec68660f297c2450660f297424404c89c64889cf488b05bc70",
        }
        for rva, expected_hex in entry_anchors.items():
            if (
                read(base + int(rva, 16), len(bytes.fromhex(expected_hex))).hex()
                != expected_hex
            ):
                raise RuntimeError("Measured update entry changed: " + rva)
        if struct.unpack("<Q", read(base + 0xB47F610 + 24, 8))[0] != weapon_update:
            raise RuntimeError("Shared WeaponLook update entry changed")
        if struct.unpack("<Q", read(base + 0xB3E9C10 + 24, 8))[0] != look_update:
            raise RuntimeError("Shared Look update entry changed")
        audited_windows = {
            "0x5e8b2e": (
                256,
                "a50c8018c97c12be15dd862d998dbb859093d404e0eb2db715a363041a67e542",
            ),
            "0x5e8c14": (
                1280,
                "5aad11d6a346798711ed2ad375c1e2180dc941b41ec16e7782198071150cc47e",
            ),
            "0x5e903c": (
                2304,
                "794b36f0229a4c663757a275f0b12deb50f85f866868eab996e170c271cd04b5",
            ),
            "0x5e9876": (
                1280,
                "0e2f7b13434322332c4b1a92ae19a35acfe1093ed9d901ee6cc73aa575418239",
            ),
            "0x5e9d36": (
                4096,
                "4d50d0ace2e7615c3f911235855d9a1af8f4cf7156dfc5a8a07b93ac496b9947",
            ),
            "0x5e8862": (
                716,
                "4e307b8258e0e2540d1972319734886d492ab2031b2ce7b9e872b4fcf4991495",
            ),
        }
        for rva, (length, digest) in audited_windows.items():
            if hashlib.sha256(read(base + int(rva, 16), length)).hexdigest() != digest:
                raise RuntimeError("Audited WeaponLook/helper code changed: " + rva)
        report["audited_update_windows_verified"] = True
        state_key = "_bl4_tps_recoil_owner"
        state = sys.modules.get(state_key)
        if state is None:
            state = types.ModuleType(state_key)
            state.active = False
            state.retained_buffers = []
            sys.modules[state_key] = state
        restoring = state.active
        current_vt = struct.unpack("<Q", read(address, 8))[0]
        identity = (
            manager_address,
            int(runtime_key, 16),
            address,
            int(target["control"], 16),
        )
        if restoring:
            if identity != state.identity or current_vt != state.shadow_vt:
                raise RuntimeError(
                    "Active copy changed; refusing stale-pointer restore. Restart game to reset test."
                )
            desired_vt = state.original_vt
            report["action"] = "RESTORE"
        else:
            if current_vt != original_vt:
                raise RuntimeError("Unexpected live Look vtable")
            # Preserve RTTI at -8 and a generous bounded table neighborhood.
            # Only known slot 3 is changed; no other slot receives an invented target.
            copied = read(original_vt - 8, 0x1008)
            buffer = ctypes.create_string_buffer(copied, len(copied))
            shadow_vt = ctypes.addressof(buffer) + 8
            ctypes.memmove(shadow_vt + 24, struct.pack("<Q", weapon_update), 8)
            expected_copy = bytearray(copied)
            expected_copy[32:40] = struct.pack("<Q", weapon_update)
            if ctypes.string_at(ctypes.addressof(buffer), len(copied)) != bytes(
                expected_copy
            ):
                raise RuntimeError("Private vtable copy verification failed")
            state.retained_buffers.append(buffer)
            state.identity = identity
            state.manager_ref = WeakPointer(cam)
            if state.manager_ref() is None:
                raise RuntimeError("Native owner manager weak reference unavailable")
            state.stack_descriptor = (raw[40:64] if upper_ffyl_tps else raw[:24]).hex()
            state.ffyl_recoil_context = bound_ffyl_context
            if upper_ffyl_tps:
                state.owned_lower_entry = raw[:40].hex()
                state.owned_definition = int(definitions[0]["address"], 16)
            state.runtime_control = int(live[0]["control"], 16)
            state.original_vt = original_vt
            state.shadow_vt = shadow_vt
            desired_vt = shadow_vt
            report["action"] = "TPS_WEAPONLOOK_UPDATE"
        # Revalidate serials immediately before the native ownership checks.
        if bound_ffyl_context is not None:
            bound_ffyl_context.proof_context(for_restore=restoring)
        # Ownership check immediately before changing the live object's vptr.
        if read(manager_address + 0x39A8, 0xB0) != window:
            raise RuntimeError("Camera changed before write")
        if count and read(array_ptr, count * 0x28) != raw:
            raise RuntimeError("Camera stack changed before write")
        if read(int(runtime_key, 16), 0x20) != bytes.fromhex(
            live[0]["runtime_header_hex"]
        ):
            raise RuntimeError("Owned runtime header changed before write")
        for row in report["runtime_behavior_lists"][runtime_key]:
            expected_header = struct.pack(
                "<Qii", int(row["data"], 16), row["count"], row["capacity"]
            )
            if (
                read(int(runtime_key, 16) + int(row["offset"], 16), 16)
                != expected_header
            ):
                raise RuntimeError("Runtime list changed before write")
            entries = b"".join(
                struct.pack("<QQ", int(x["address"], 16), int(x["control"], 16))
                for x in row["items"]
            )
            if entries and read(int(row["data"], 16), len(entries)) != entries:
                raise RuntimeError("Runtime ownership changed before write")
        if read(address, 16) != bytes.fromhex(target["hex"])[:16]:
            raise RuntimeError("Selected behavior identity changed")
        if (
            upper_ffyl_tps
            and not restoring
            and not getattr(mod, "_native_handoff_guard_enabled", False)
        ):
            raise RuntimeError("Bound FFYL recoil requires its native PRE guard")
        if not restoring and getattr(mod, "_native_handoff_guard_enabled", False):
            # Install the native PRE guard BEFORE the old Look receives its
            # Shadow VTable. A failed install leaves the original VTable intact.
            from . import native_ladder_guard

            if upper_ffyl_tps:
                from . import ffyl_recoil_guard

                ffyl_recoil_guard.install(
                    mod,
                    state,
                    int(live[0]["control"], 16),
                    int(definitions[0]["address"], 16),
                    context=bound_ffyl_context,
                )
            else:
                native_ladder_guard.install(
                    mod,
                    state,
                    int(live[0]["control"], 16),
                    int(definitions[0]["address"], 16),
                )
            guard_installed = True
            guard_mod = mod
            if mod._native_fault:
                raise RuntimeError(
                    "LadderGuard activation interrupted; native recoil write refused"
                )
        kernel.WriteProcessMemory.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        )
        kernel.WriteProcessMemory.restype = ctypes.c_int

        def write_vptr(value):
            buf = ctypes.c_uint64(value)
            got = ctypes.c_size_t()
            ok = kernel.WriteProcessMemory(
                handle, address, ctypes.byref(buf), 8, ctypes.byref(got)
            )
            report["game_writes"] += int(got.value)
            if not ok or got.value != 8 or read(address, 8) != struct.pack("<Q", value):
                raise RuntimeError("Live vptr write/readback failed")

        if bound_ffyl_context is not None:
            # Guard allocation may reenter game-thread lifecycle callbacks.
            bound_ffyl_context.proof_context(for_restore=restoring)
        state.active = True  # Retain recovery state before attempting the write.
        try:
            write_vptr(desired_vt)
        except Exception:
            try:
                write_vptr(original_vt)
                state.active = False
                report["rollback"] = "Original vptr restored"
            except Exception as exc:
                report["rollback"] = "FAILED: " + str(exc)
            raise
        state.active = not restoring
        if report.get("ground_slam_stacked_owner_verified"):
            logging.info(
                "[BL4ThirdPersonPOC] GROUND_SLAM_RECOIL_RESTORED "
                f"owner_runtime={runtime_key} look={address:#x} "
                "stack_count=2 original_vtable_verified=True"
            )
        if report.get("death_stacked_owner_verified"):
            logging.info(
                "[BL4ThirdPersonPOC] DEATH_RECOIL_RESTORED "
                f"owner_runtime={runtime_key} look={address:#x} "
                "stack_count=2 original_vtable_verified=True"
            )
        report["ab_verified"] = True
        report["restore_pending"] = state.active
        report["ab_target"] = {
            "address": hex(address),
            "before_vtable": hex(current_vt),
            "after_vtable": hex(desired_vt),
            "original_vtable": hex(original_vt),
            "plain_look_update": hex(look_update),
            "weaponlook_update": hex(weapon_update),
            "changed_private_slot": 3,
            "shared_vtable_modified": False,
            "executable_bytes_modified": False,
        }
        if (
            not restoring
            and not schema_cache_hit
            and schema_key is not None
            and not report["errors"]
            and not report["limits"]
        ):
            _SCHEMA_CACHE = {
                "key": schema_key,
                "schemas": report["behavior_type_schemas"],
            }

    except Exception as exc:
        report["errors"].append(
            {"scope": "setup", "error": f"{type(exc).__name__}: {exc}"}
        )
        if (
            guard_installed
            and state is not None
            and not getattr(state, "active", False)
        ):
            try:
                from . import native_ladder_guard

                native_ladder_guard.remove(guard_mod)
            except Exception as cleanup_exc:
                report["errors"].append(
                    {
                        "scope": "ladder_guard_cleanup",
                        "error": f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                    }
                )
    if report["errors"] or report["limits"]:
        logging.warning(
            f'{TAG} action={report.get("action", "NONE")} '
            f'errors={report["errors"]} limits={report["limits"]}'
        )
    if schema_scan_ms is not None:
        logging.info(
            f"[BL4ThirdPersonPOC] RECOIL_ARM_COST "
            f'action={report.get("action", "NONE")} '
            f"schema_cache_hit={schema_cache_hit} "
            f"schema_ms={schema_scan_ms:.3f} "
            f"total_ms={(time.perf_counter_ns() - started_ns) / 1e6:.3f}"
        )

    return report
