"""Recover native zoom modifiers omitted by a held TPS-ADS weapon handoff.

The game owns modifier values and normal zoom-exit removal. This module calls
only the measured Sight entry helper, once per settled equip identity, when
both runtime lists are empty. It never writes spread, changes ticking state,
installs a detour, or calls the camera-effect numeric update.

Native layout: active use-mode entry +0x28 is Sight; Sight +0x68/+0x78
hold 16-byte applied-effect records. Definition +0x98/+0xA8 contains 112-byte
entries. The entry helper's verified loop establishes these sizes. Direct
native execution is restricted to the verified BL4 executable build.
"""

from __future__ import annotations

import ctypes
import hashlib
import struct
from .build_gate import REVIEWED_BUILD
from unrealsdk import logging
from unrealsdk.unreal import WeakPointer

TAG = "[BL4ThirdPersonPOC.ADSZoom]"
ENTRY_RVA = 0x12FCF6E
SIGHT_TABLE_RVA = 0xB948820
# Measured full entry window, list application body, and list exit body.
CODE_GUARDS = (
    (
        ENTRY_RVA,
        0x1000,
        "1394192119c419fbad89fec670a1e15064935e6ca274db4a80c2c19b83504886",
    ),
    (
        0xC41F42,
        0x10B,
        "6541395db74ea971d3500453db2c0fcd7cc646fdd076e04ba372f43a05653470",
    ),
    (
        0xCC369E,
        0x3E,
        "74cee4f79893ee27c4795e1df939894067fe4bd15cbdc3ab0d16cbc709b13da8",
    ),
)


def list_headers(raw):
    """Decode two bounded native array headers without touching their storage."""
    if len(raw) != 32:
        raise RuntimeError("Zoom list header length differs")
    rows = []
    for offset in (0, 16):
        pointer, count, capacity = struct.unpack_from("<Qii", raw, offset)
        if not 0 <= count <= capacity <= 256 or (count and pointer < 0x10000):
            raise RuntimeError("Zoom list bounds refused")
        rows.append((pointer, count, capacity))
    return rows


def _initialize(mod):
    read = mod._native_read
    base = int(mod._kernel32.GetModuleHandleW(None) or 0)
    if not base or read(base, 2) != b"MZ":
        raise RuntimeError("Module unavailable")
    pe = struct.unpack("<I", read(base + 60, 4))[0]
    if not 64 <= pe <= 0x100000:
        raise RuntimeError("PE offset refused")
    hdr = read(base + pe, 0x60)
    if (
        hdr[:4] != b"PE\0\0"
        or struct.unpack_from("<H", hdr, 24)[0] != 0x20B
        or (
            struct.unpack_from("<I", hdr, 8)[0],
            struct.unpack_from("<I", hdr, 0x50)[0],
            struct.unpack_from("<H", hdr, 4)[0],
        )
        != REVIEWED_BUILD
    ):
        raise RuntimeError("Game build differs")
    for rva, size, digest in CODE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise RuntimeError(f"Zoom code differs at RVA {rva:#x}")
    thread_id = mod._kernel32.GetCurrentThreadId
    thread_id.argtypes = ()
    thread_id.restype = ctypes.c_uint32
    return dict(
        base=base,
        thread=int(thread_id()),
        enter=ctypes.WINFUNCTYPE(None, ctypes.c_void_p)(base + ENTRY_RVA),
        entry_prefix=read(base + ENTRY_RVA, 32),
        previous=None,
        calls=0,
    )


def update(mod):
    """Run at equip completion before reticle publication, with a camera-update fallback."""
    handoff, ads = mod._ads_handoff, mod._ads_tps_state
    if not (
        isinstance(ads, dict)
        and ads.get("phase") == "ads"
        and handoff.get("held")
        and mod._ads_active
        and mod._ads_route == "tps"
        and handoff.get("incoming_weapon")
        and int(handoff.get("equip_ordinal", 0)) >= 2
        and not handoff.get("latch_active")
        and not handoff.get("reticle_rebind_active")
        and ads.get("transition") is None
        and mod._third_person_enabled
        and mod._third_person_pushed
    ):
        return
    if (
        any(
            bool(getattr(mod, flag, False))
            for flag in (
                "_slide_active",
                "_ladder_active",
                "_vehicle_camera_active",
                "_shop_camera_active",
                "_native_ffyl_pending",
                "_native_npc_pending",
                "_native_ladder_handoff_pending",
                "_native_slide_handoff_pending",
            )
        )
        or mod._camera_lifecycle.get("pending")
        or mod._ads_press_intent.get("pending")
    ):
        return
    attempted = ads.get("zoom_modifier_attempt")
    if (
        isinstance(attempted, tuple)
        and len(attempted) == 5
        and attempted[2] == ads.get("manager_address")
        and attempted[3]
        == ads.get("weapon_address")
        == handoff.get("incoming_weapon")
        == handoff.get("route_weapon")
        and attempted[4] == int(handoff.get("equip_ordinal", 0))
    ):
        return
    pc, pawn, camera = mod._get_runtime()
    if any(x is None for x in (pc, pawn, camera)):
        return
    weapon = camera.CameraModeInputs.Weapon
    wa = mod._object_address(weapon)
    identity = tuple(mod._object_address(x) for x in (pc, pawn, camera, weapon))
    key = identity + (int(handoff["equip_ordinal"]),)
    if ads.get("zoom_modifier_attempt") == key:
        return
    if (
        not wa
        or wa != handoff.get("incoming_weapon")
        or wa != handoff.get("route_weapon")
        or wa != ads.get("weapon_address")
        or identity[2] != ads.get("manager_address")
    ):
        return
    if (
        int(pawn.ZoomState.State) != 2
        or int(pawn.ZoomState.Level) != 0
        or not pawn.ZoomState.bWantsToZoom
        or str(camera.GetActorCameraMode(pawn)) != "ThirdPerson"
        or camera.CameraModeState.bIsTransitioning
        or camera.CameraModeState.bShowViewModel
    ):
        return
    # A readiness wait is not an attempt. Once the settled identity is ready,
    # even a validation failure is consumed; no repeated native-call retries.
    ads["zoom_modifier_attempt"] = key
    try:
        native = getattr(mod, "_ads_zoom_modifier_native", None)
        if native is None:
            native = _initialize(mod)
            mod._ads_zoom_modifier_native = native
        if int(mod._kernel32.GetCurrentThreadId()) != native["thread"]:
            raise RuntimeError("Native zoom update thread changed")
        base, read = native["base"], mod._native_read

        def checked_read(address, size):
            if not 0x10000 <= address < 0x800000000000 or not 0 < size <= 0x1000:
                raise RuntimeError("Native zoom read bounds refused")
            return read(address, size)

        selection = checked_read(wa + 0xBD8, 0x1C)
        index = selection[0]
        data = struct.unpack_from("<Q", selection, 0x10)[0]
        count = struct.unpack_from("<i", selection, 0x18)[0]
        if not 0 <= index < count <= 256:
            raise RuntimeError("Weapon use-mode bounds refused")
        slot = data + index * 0x88 + 0x28
        component_bytes = checked_read(slot, 8)
        component = struct.unpack("<Q", component_bytes)[0]
        sight, _, _ = mod._find_active_ads_sight(weapon)
        if mod._object_address(sight) != component:
            raise RuntimeError("Reflected Sight and native use-mode differ")
        owners = (pc, pawn, camera, weapon, sight)
        refs = tuple(WeakPointer(x) for x in owners)
        addresses = identity + (component,)
        binding = checked_read(component, 0x40)
        table = struct.unpack_from("<Q", binding, 0)[0]
        definition = struct.unpack_from("<Q", binding, 0x38)[0]
        if (
            table != base + SIGHT_TABLE_RVA
            or struct.unpack_from("<Q", binding, 0x30)[0] != wa
        ):
            raise RuntimeError("Sight local weapon owner differs")
        if struct.unpack("<QQ", checked_read(table + 0x2F0, 16)) != (
            base + ENTRY_RVA,
            base + 0xCC369E,
        ):
            raise RuntimeError("Sight entry/exit binding differs")
        live_raw = checked_read(component + 0x68, 32)
        live = list_headers(live_raw)
        if any(row[1] for row in live):
            ads["zoom_modifier_result"] = "already_active"
            return
        definition_raw = checked_read(definition + 0x98, 32)
        definitions = list_headers(definition_raw)
        expected = [row[1] for row in definitions]
        if not any(expected):
            ads["zoom_modifier_result"] = "no_definition_entries"
            return
        if checked_read(wa + 0x178, 1) != b"\x03":
            raise RuntimeError("Local weapon authority role differs")
        # Do not stack player-side effects if a prior corrected weapon was not
        # retired by the game. Weak references validate lifetime before reads.
        previous = native.get("previous")
        if previous:
            old_weapon, old_sight = (ref() for ref in previous["refs"])
            if old_weapon is not None and old_sight is not None:
                old_addresses = tuple(
                    mod._object_address(x) for x in (old_weapon, old_sight)
                )
                if old_addresses != previous["addresses"]:
                    raise RuntimeError("Previous zoom owner identity differs")
                if old_addresses[1] != component:
                    old_live = list_headers(checked_read(old_addresses[1] + 0x68, 32))
                    if any(row[1] for row in old_live):
                        raise RuntimeError(
                            "Outgoing corrected weapon still has active zoom effects"
                        )
        if read(base + ENTRY_RVA, 32) != native["entry_prefix"]:
            raise RuntimeError("Entry helper was replaced")
        resolved = tuple(ref() for ref in refs)
        if (
            any(x is None for x in resolved)
            or tuple(mod._object_address(x) for x in resolved) != addresses
        ):
            raise RuntimeError("Zoom owner lifetime changed")
        for address, raw in (
            (wa + 0xBD8, selection),
            (slot, component_bytes),
            (component, binding),
            (component + 0x68, live_raw),
            (definition + 0x98, definition_raw),
        ):
            if checked_read(address, len(raw)) != raw:
                raise RuntimeError("Zoom snapshot changed before entry")
        if (
            tuple(mod._object_address(x) for x in mod._get_runtime()) != identity[:3]
            or mod._object_address(camera.CameraModeInputs.Weapon) != wa
        ):
            raise RuntimeError("Current player or equipped weapon changed")
        ads["zoom_modifier_result"] = "entry_attempted"
        native["enter"](component)
        native["calls"] += 1
        native["previous"] = dict(refs=(refs[3], refs[4]), addresses=(wa, component))
        applied = [row[1] for row in list_headers(checked_read(component + 0x68, 32))]
        if applied != expected:
            raise RuntimeError(
                f"Applied list counts differ: expected={expected}, actual={applied}"
            )
        ads["zoom_modifier_result"] = "applied"
        logging.info(
            f'{TAG} HANDOFF_APPLIED weapon={wa:#x} lists={applied} calls={native["calls"]}'
        )
    except Exception as exc:
        ads["zoom_modifier_result"] = "refused"
        logging.error(f"{TAG} HANDOFF_REFUSED {type(exc).__name__}: {exc}")
