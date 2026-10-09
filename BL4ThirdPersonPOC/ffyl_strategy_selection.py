"""Construct the simplified FFYL coordinator with concrete validated dependencies.

Construction does not publish or start the coordinator. The production runtime
publishes it during enable and starts binding only from settled local TPS.
This module reads build, reflection and stack evidence; it does not patch code.
"""

import struct

from .ffyl_down_state import bind_local_down_state, DOWN_STATE_CLASS
from .ffyl_strategy_controller import FFYLStrategyController

# Same reviewed UFunction-entry anchors enforced by the production recoil path.
# +0xd8 is the measured executable-pointer metadata slot for this exact build.
CAMERA_ENTRIES = {
    "PushActorCameraMode": (
        92365206,
        "564883ec504889d6488b059b97ee064831e0488944244848c744244000000000",
    ),
    "PushActorCameraModeDef": (
        142148746,
        "5657534881ecc00000000f29b424b00000004889d6488b059af4f6034831e048",
    ),
    "GetActorCameraMode": (
        96535664,
        "56574883ec384c89c64889d7488b05bdf4ae064831e0488944243048c7442428",
    ),
}
DOWN_STATE_SIGNATURES = {
    "OnDowned": (
        ("bIsAuthority", "BoolProperty", 0, 1),
        ("bIsLocal", "BoolProperty", 1, 1),
    ),
    "OnDownedEnded": (
        ("bIsAuthority", "BoolProperty", 0, 1),
        ("bIsLocal", "BoolProperty", 1, 1),
        ("reason", "EnumProperty", 2, 1),
    ),
}


def verify_selection(mod, *, find_object):
    """Prove normal owned TPS, executable fingerprint, entries and event schema.

    The existing single-stack helper enforces DOS/PE32+/build checks BEFORE its
    manager-layout read. Recoil's later activation still performs its complete
    layout/type/vtable verification; this preflight never grants a write by itself.
    No process-lifetime validity cache is used across reload or game updates.
    """
    runtime = mod._get_runtime()
    if len(runtime) != 3 or any(obj is None for obj in runtime):
        raise RuntimeError("FFYL selection requires local gameplay")
    identity = tuple(int(obj._get_address()) for obj in runtime)
    pc, pawn, manager = runtime
    owner = mod._camera_stack_owner
    if (
        not owner.get("owned")
        or not mod._third_person_pushed
        or (owner.get("pawn_address"), owner.get("manager_address")) != identity[1:]
    ):
        raise RuntimeError("FFYL selection requires owned local TPS")
    if str(manager.GetActorCameraMode(pawn)) != "ThirdPerson":
        raise RuntimeError("FFYL selection requires normal ThirdPerson mode")
    if mod._ffyl_camera_stack_has_single_tps(manager) is not True:
        raise RuntimeError("FFYL selection requires verified single TPS stack")
    base = int(mod._kernel32.GetModuleHandleW(None) or 0)
    if base < 0x10000:
        raise RuntimeError("FFYL executable unavailable")
    read = mod._native_read
    for name, (rva, hex_bytes) in CAMERA_ENTRIES.items():
        function = find_object(
            "Function", "/Script/GbxGame.PlayerCameraModeManager:" + name
        )
        if function is None:
            raise RuntimeError("FFYL camera function missing: " + name)
        pointer_bytes = read(int(function._get_address()) + 0xD8, 8)
        if len(pointer_bytes) != 8:
            raise RuntimeError("FFYL camera entry read incomplete: " + name)
        pointer = struct.unpack("<Q", pointer_bytes)[0]
        expected = bytes.fromhex(hex_bytes)
        if pointer != base + rva or read(pointer, len(expected)) != expected:
            raise RuntimeError("FFYL camera entry differs: " + name)
    for name, expected in DOWN_STATE_SIGNATURES.items():
        function = find_object("Function", DOWN_STATE_CLASS + ":" + name)
        if function is None:
            raise RuntimeError("DownState event missing: " + name)
        actual = []
        for index, prop in enumerate(function._properties()):
            if index >= 16:
                raise RuntimeError("DownState event signature exceeds cap")
            actual.append(
                (
                    str(prop.Name),
                    str(prop.Class.Name),
                    int(prop.Offset_Internal),
                    int(prop.ElementSize),
                )
            )
        if tuple(actual) != expected:
            raise RuntimeError("DownState event schema differs: " + name)
    after = mod._get_runtime()
    if (
        len(after) != 3
        or any(obj is None for obj in after)
        or tuple(int(obj._get_address()) for obj in after) != identity
        or mod._ffyl_camera_stack_has_single_tps(manager) is not True
    ):
        raise RuntimeError("FFYL selection runtime changed during preflight")
    return True


def make_controller(
    mod, *, weak_pointer, hooks, find_object, stop_legacy, stop_ground_slam
):
    """Return an unstarted coordinator; no hooks or module callback replacements.

    The caller must publish it before start_if_ready, and retain it after failures.
    A new local predicate is captured for each prepared cycle, including respawn.
    Explicit stop_legacy remains required, so construction cannot hide cleanup.
    """
    return FFYLStrategyController(
        mod,
        weak_pointer=weak_pointer,
        hooks=hooks,
        build_preflight=lambda current: verify_selection(
            current, find_object=find_object
        ),
        resolve_local_down_state=lambda current: bind_local_down_state(
            current, weak_pointer=weak_pointer
        ),
        stop_legacy=stop_legacy,
        stop_ground_slam=stop_ground_slam,
    )
