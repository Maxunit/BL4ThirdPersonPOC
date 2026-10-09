"""Preserve recoil ownership during native ladder and slide camera handoffs.

This module is only entered from native_recoil's verified owner setup.
The Slide FName comes from the live SDK name pool in this process.
The stub performs one owner-checked atomic VTable restore before BL4's
SetActorCameraMode clears the old runtime. Python consumes status later
on the game thread. An unverified restore is never treated as successful.
"""

import ctypes
import hashlib
import struct
from .build_gate import REVIEWED_BUILD

from unrealsdk import logging

TAG = "[BL4ThirdPersonPOC.ModeGuard]"
KEY = "ladder_guard"
TARGET_RVA = 0x129DD6A
PROLOGUE = bytes.fromhex("415741564154565755534883ec50")
CONTINUATION = bytes.fromhex("0f297424400f28f3")
STUB = bytes.fromhex(
    "9c50415041514152415349ba222222222222222241837a40000f851f010000498b024839c10f85130100004885d20f84"
    "0a010000488b02483df7cc010074204d8b5a484c39d87417483d070300000f85ea00000041837a50010f85df00000048"
    "8b81303a0000483da4cc01000f85cc00000083b9c8390000010f85bf0000004c8b81483a00004d3b42080f85ae000000"
    "4c8b89c03900004981f9000001000f829a000000498139a4cc01000f858d0000004d3941180f85830000004d3900757e"
    "498b4210493940087574498b421849394010756a458b48284183f9017c604183f9087f5a4d8b48204981f90000010072"
    "4d498b42204939017544498b422849394108753a4d8b4a20498b42304d8b5a38f04d0fb1197527b80200000048813af7"
    "cc0100741048813a07030000750cb803000000eb05b80100000041894240415b415a41594158589d"
)
STUB_SHA256 = "835f854751d8f46b72a1f92cdd18cf9a834fd43b344c4937668aecee4579a57f"


# GE diagnostic prefix, assembled and checked offline. It only writes a
# local 16-record buffer; flags/RAX/R10/R11 are saved and restored. The existing
# guard instructions and original target prologue are unchanged.
TRACE_CAP = 16
TRACE_PREFIX = bytes.fromhex(
    "9c504152415348b811111111111111114839c175704885d2746b49ba222222222222222241bb01000000f04d0fc11a4983fb10735049c1e3064f8d541a0849890a488b0249894208488b81303a000049894210488b81483a000049894218488b44242049894220488b81c039000049894228488b81c83900004989423049c7423801000000415b415a589d"
)
TRACE_SHA256 = "0056312fefd7ef262c9c653303e9852061a5e073acc3d784103de812e8550811"


def _trace_prefix(manager: int, buffer) -> bytes:
    if (
        len(TRACE_PREFIX) != 139
        or hashlib.sha256(TRACE_PREFIX).hexdigest() != TRACE_SHA256
        or TRACE_PREFIX.count(b"\x11" * 8) != 1
        or TRACE_PREFIX.count(b"\x22" * 8) != 1
        or TRACE_CAP != 16
    ):
        raise RuntimeError("Unverified native Set trace prefix")
    return TRACE_PREFIX.replace(b"\x11" * 8, struct.pack("<Q", manager)).replace(
        b"\x22" * 8, struct.pack("<Q", ctypes.addressof(buffer))
    )


class _Control(ctypes.Structure):
    _fields_ = [
        ("manager", ctypes.c_uint64),
        ("runtime", ctypes.c_uint64),
        ("runtime_control", ctypes.c_uint64),
        ("definition", ctypes.c_uint64),
        ("look", ctypes.c_uint64),
        ("look_control", ctypes.c_uint64),
        ("shadow_vtable", ctypes.c_uint64),
        ("original_vtable", ctypes.c_uint64),
        ("status", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("slide_fname", ctypes.c_uint64),
        ("allow_default", ctypes.c_uint32),
        ("reserved_tail", ctypes.c_uint32),
    ]


def _checked_stub(control_address: int, trampoline: int, mod) -> bytes:
    if (
        len(STUB) != 328
        or hashlib.sha256(STUB).hexdigest() != STUB_SHA256
        or STUB.count(b"\x22" * 8) != 1
    ):
        raise RuntimeError("Unverified ModeGuard native instructions")
    code = STUB.replace(b"\x22" * 8, struct.pack("<Q", control_address))
    return code + mod._native_absolute_jump(trampoline)


def _current_slide_fname(kernel) -> int:
    """Resolve the actual engine FName through the SDK's existing export."""
    kernel.GetProcAddress.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
    kernel.GetProcAddress.restype = ctypes.c_void_p
    sdk_module = int(kernel.GetModuleHandleW("unrealsdk.dll") or 0)
    if sdk_module < 0x10000:
        raise RuntimeError("Loaded unrealsdk.dll module unavailable")
    address = int(
        kernel.GetProcAddress(
            ctypes.c_void_p(sdk_module), b"_unrealsdk_export__fname_init"
        )
        or 0
    )
    if address < 0x10000:
        raise RuntimeError("SDK FName initializer export unavailable")
    init_fname = ctypes.WINFUNCTYPE(
        None, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32
    )(address)
    raw_name = ctypes.create_string_buffer(8)
    init_fname(raw_name, "Slide", 0)
    index, number = struct.unpack("<II", raw_name.raw)
    if index < 0x10000 or number != 0 or index == 0x1CCF7:
        raise RuntimeError("SDK returned invalid Slide FName")
    return index


def install(mod, owner, runtime_control: int, definition: int) -> None:
    """Publish the Set entry guard before replacing the live Look vtable.

    The caller has verified the executable and Look/runtime identity. The native
    control stores only the exact owned vtable pair; status is consumed without
    dereferencing a destroyed Look. Keep trace/control pins on retirement.
    """
    if mod._active_native_state.get(KEY) is not None:
        raise RuntimeError("An older LadderGuard hook still owns Set")
    if (
        ctypes.sizeof(_Control) != 88
        or _Control.status.offset != 0x40
        or _Control.slide_fname.offset != 0x48
        or _Control.allow_default.offset != 0x50
    ):
        raise RuntimeError("LadderGuard control layout changed")
    if not (len(owner.identity) == 4 and all(owner.identity)):
        raise RuntimeError("Missing native recoil owner identity")
    manager, runtime, look, look_control = map(int, owner.identity)
    if (
        not runtime_control
        or not definition
        or not owner.shadow_vt
        or not owner.original_vt
    ):
        raise RuntimeError("LadderGuard owner has incomplete metadata")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    base = int(kernel.GetModuleHandleW(None) or 0)
    # native_recoil has already verified the PE build and exact runtime layout.
    if base < 0x10000 or (
        mod._native_read(base + TARGET_RVA, len(PROLOGUE) + len(CONTINUATION))
        != PROLOGUE + CONTINUATION
    ):
        raise RuntimeError("Unexpected native Set entry or other owner")
    slide_fname = _current_slide_fname(kernel)
    control = _Control(
        manager,
        runtime,
        runtime_control,
        definition,
        look,
        look_control,
        owner.shadow_vt,
        owner.original_vt,
        0,
        0,
        slide_fname,
        int(bool(mod._native_slide_interior)),
        0,
    )

    trace_buffer = ctypes.create_string_buffer(8 + TRACE_CAP * 64)
    # Retired executable allocations retain control. Pin their trace buffer to
    # that same object for exactly the same lifetime, including in-flight calls.
    control._trace_buffer = trace_buffer

    def build(_stub, trampoline):
        return (
            None,
            control,
            (
                _trace_prefix(manager, trace_buffer)
                + _checked_stub(ctypes.addressof(control), trampoline, mod)
            ),
        )

    hook = mod._native_allocate_hook(
        base + TARGET_RVA,
        PROLOGUE,
        len(PROLOGUE),
        build,
        "ladder/slide recoil guard",
    )
    mod._active_native_state[KEY] = {
        "hook": hook,
        "control": control,
        "owner_identity": tuple(owner.identity),
        "consumed": False,
        "slide_interior": bool(mod._native_slide_interior),
        "trace_buffer": trace_buffer,
        "trace_base": base,
    }
    logging.warning(
        f"{TAG} ARMED manager={manager:#x} runtime={runtime:#x} "
        f"look={look:#x} slide_fname={slide_fname:#x} "
        f"allow_default={control.allow_default} native_patches=1"
    )


def status(mod) -> int:
    state = mod._active_native_state.get(KEY)
    if state is None:
        return 0
    return int(state["control"].status)


def remove(mod) -> None:
    """Restore the owned code site before retiring its pinned hook storage.

    Readback or retirement failure raises and leaves the registry entry intact;
    callers must preserve the camera owner needed for a later safe restoration.
    Native trace counters are diagnostic evidence, not release permission.
    """
    state = mod._active_native_state.get(KEY)
    if state is None:
        return
    hook = state["hook"]
    mod._native_restore_hook(hook)
    if mod._native_read(int(hook["target"]), len(PROLOGUE)) != PROLOGUE:
        raise RuntimeError("LadderGuard post-unhook bytes changed")
    # Snapshot after verified unhook; records are committed last by the
    # native prefix. Skip any incomplete slot rather than interpreting it.
    raw = state["trace_buffer"].raw
    calls = struct.unpack_from("<Q", raw)[0]
    base = state["trace_base"]
    logging.warning(
        f"{TAG} NATIVE_SET_TRACE calls={calls} "
        f"stored={min(calls, TRACE_CAP)} truncated={calls > TRACE_CAP} "
        "scope=entry_before_guard"
    )
    for index in range(min(calls, TRACE_CAP)):
        manager, requested, previous, runtime, caller, array, header, committed = (
            struct.unpack_from("<8Q", raw, 8 + index * 64)
        )
        if committed != 1:
            logging.warning(f"{TAG} NATIVE_SET_TRACE_INCOMPLETE index={index}")
            continue
        count, capacity = struct.unpack("<ii", struct.pack("<Q", header))
        caller_rva = (
            hex(caller - base) if base <= caller < base + 0x31B8C000 else "external"
        )
        logging.warning(
            f"{TAG} NATIVE_SET_ENTRY index={index} "
            f"manager={manager:#x} requested_fname={requested:016x} "
            f"previous_fname={previous:016x} runtime={runtime:#x} "
            f"caller={caller:#x} caller_rva={caller_rva} "
            f"stack_array={array:#x} count={count} capacity={capacity}"
        )
    mod._native_release_hook(hook)
    mod._active_native_state.pop(KEY, None)
    logging.warning(
        f"{TAG} REMOVED status={state['control'].status} " "native_patches=0"
    )


def consume(mod, owner) -> int:
    """Consume the native CAS event on the game thread without reading old Look."""
    state = mod._active_native_state.get(KEY)
    if state is None or int(state["control"].status) not in (1, 2, 3):
        return 0
    if (
        owner is None
        or not getattr(owner, "active", False)
        or tuple(owner.identity) != state["owner_identity"]
        or state["consumed"]
    ):
        raise RuntimeError("LadderGuard success has no unique Python owner")
    result = int(state["control"].status)
    if result == 3 and not state["slide_interior"]:
        raise RuntimeError("Default PRE restore without slide interior owner")
    state["consumed"] = True
    # The native lock cmpxchg already verified Shadow -> Original. The old
    # Look may have been destroyed by now: do not dereference it again.
    owner.active = False
    owner.native_pre_restored_mode = (
        "ladder" if result == 1 else "Slide" if result == 2 else "Default"
    )
    logging.warning(
        f"{TAG} NATIVE_PRE_RESTORED mode={owner.native_pre_restored_mode} "
        f"owner={state['owner_identity']!r}"
    )
    remove(mod)
    return result


# Independent native Default-mode wrapper guard. It survives the short ladder
# handoff after the SetActorCameraMode/recoil guard has retired. No SDK hook is
# registered here; the owned wrapper site has its own restore/readback contract.
DEFAULT_KEY = "ladder_default"
DEFAULT_VARIANT = "owned-ladder-default-handoff"
DEFAULT_TARGET_RVA = 0x662897B
DEFAULT_ORIGINAL = bytes.fromhex("44884c242844885424204c89c24989c0")
DEFAULT_CALL = bytes.fromhex("e8da53c7fa")
DEFAULT_RETURN_RVA = 0x6628990
DEFAULT_WRAPPER_RVA = 0x6628922
DEFAULT_WRAPPER_SHA256 = (
    "3e930e71cf07b5d77097b175ea8cf97982ad46011298c22237562aeb3c508a36"
)
DEFAULT_PREFIX = bytes.fromhex(
    "9c504152415349ba2222222222222222493b0a0f8589000000f049ff421041837a0801757d4c8d5c24504d39d875734c8d5c24684c395c2410756749813807030000755e418178080172000075544983781000754d4881b9303a0000f7cc0100754083b9c839000001753783b9cc390000017c2e83b9cc390000407f254c8b99c03900004981fb00000100721549813bf7cc0100750c49c700a4cc0100f049ff4218415b415a589d"
)
DEFAULT_PREFIX_SHA256 = (
    "09752c3e26b85efd5ec97204a896bc987f077a6c0cb3a32879897bdbeb51aa53"
)


class _DefaultControl(ctypes.Structure):
    _fields_ = [
        ("manager", ctypes.c_uint64),
        ("enabled", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("visits", ctypes.c_uint64),
        ("replacements", ctypes.c_uint64),
    ]


def _default_blocked(mod) -> bool:
    return bool(
        not mod._native_auto_enabled
        or mod._native_fault
        or not mod._ffyl_native_pre_installed
        or not mod._third_person_enabled
        or not mod._third_person_pushed
        or mod._vehicle_camera_active
        or mod._shop_camera_active
        or mod._slide_active
        or mod._ads_active
        or mod._ads_route != "hip"
        or mod._native_ffyl_pending
        or mod._ffyl_early_handoff_armed
        or mod._camera_lifecycle.get("pending")
        or not mod._camera_stack_owner.get("owned")
        or mod._camera_stack_owner.get("pending_pop")
    )


def pre_poll_default(mod) -> None:
    """Observe the baseline Default guard before normal native ownership reconciliation."""
    state = mod._active_native_state.get(DEFAULT_KEY)
    if state is None:
        return
    if _default_blocked(mod):
        state["control"].enabled = 0
    if not mod._native_auto_enabled:
        remove_default(mod, "auto_off")


def update_default(mod, pc, pawn, camera) -> None:
    state = mod._active_native_state.get(DEFAULT_KEY)
    if state is None:
        return
    control = state["control"]
    control.enabled = 0  # Fail closed before inspecting runtime identity.
    identity = tuple(mod._object_address(obj) for obj in (pc, pawn, camera))
    if not all(identity) or identity != state["identity"]:
        remove_default(mod, "runtime_identity_change")
        return
    if (
        int(mod._camera_stack_owner.get("pawn_address", 0)) != identity[1]
        or int(mod._camera_stack_owner.get("manager_address", 0)) != identity[2]
    ):
        return
    if not _default_blocked(mod):
        control.enabled = 1


def ensure_default(mod, pc, pawn, camera) -> None:
    """Install once per local camera, after verified recoil/Set guard setup."""

    identity = tuple(mod._object_address(obj) for obj in (pc, pawn, camera))
    if not all(identity) or _default_blocked(mod):
        return
    existing = mod._active_native_state.get(DEFAULT_KEY)
    if existing is not None:
        if existing["identity"] == identity:
            existing["handoff_baseline"] = int(existing["control"].replacements)
            update_default(mod, pc, pawn, camera)
            return
        remove_default(mod, "new_owner")
    # Reuse the build-validated stack reader; offsets below
    # are from the measured native wrapper for the supported executable.
    if not mod._ffyl_camera_stack_has_single_tps(camera):
        raise RuntimeError("Default wrapper arm requires the verified TPS stack")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    base = int(kernel.GetModuleHandleW(None) or 0)
    if base < 0x10000:
        raise RuntimeError("Main module unavailable")
    dos = mod._native_read(base, 64)
    offset = struct.unpack_from("<I", dos, 60)[0]
    if dos[:2] != b"MZ" or not 64 <= offset <= 0x100000:
        raise RuntimeError("Default wrapper DOS header mismatch")
    pe = mod._native_read(base + offset, 0x60)
    actual = (
        struct.unpack_from("<I", pe, 8)[0],
        struct.unpack_from("<I", pe, 80)[0],
        struct.unpack_from("<H", pe, 4)[0],
    )
    if (
        pe[:4] != b"PE\0\0"
        or struct.unpack_from("<H", pe, 24)[0] != 0x20B
        or actual != REVIEWED_BUILD
    ):
        raise RuntimeError("Default wrapper build mismatch")
    if (
        DEFAULT_TARGET_RVA + len(DEFAULT_ORIGINAL) + 5 != DEFAULT_RETURN_RVA
        or DEFAULT_RETURN_RVA + struct.unpack_from("<i", DEFAULT_CALL, 1)[0]
        != TARGET_RVA
        or mod._native_read(base + DEFAULT_TARGET_RVA, 21)
        != DEFAULT_ORIGINAL + DEFAULT_CALL
        or hashlib.sha256(mod._native_read(base + DEFAULT_WRAPPER_RVA, 110)).hexdigest()
        != DEFAULT_WRAPPER_SHA256
    ):
        raise RuntimeError("Default wrapper code changed or another hook owns it")
    if (
        ctypes.sizeof(_DefaultControl) != 32
        or _DefaultControl.enabled.offset != 8
        or _DefaultControl.visits.offset != 16
        or _DefaultControl.replacements.offset != 24
        or len(DEFAULT_PREFIX) != 168
        or DEFAULT_PREFIX.count(b"\x22" * 8) != 1
        or hashlib.sha256(DEFAULT_PREFIX).hexdigest() != DEFAULT_PREFIX_SHA256
    ):
        raise RuntimeError("Default wrapper native control/prefix mismatch")
    control = _DefaultControl(identity[2], 0, 0, 0, 0)

    def build(_stub, trampoline):
        prefix = DEFAULT_PREFIX.replace(
            b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control))
        )
        return None, control, prefix + mod._native_absolute_jump(trampoline)

    hook = mod._native_allocate_hook(
        base + DEFAULT_TARGET_RVA,
        DEFAULT_ORIGINAL,
        len(DEFAULT_ORIGINAL),
        build,
        "local ladder Default guard",
    )
    mod._active_native_state[DEFAULT_KEY] = {
        "hook": hook,
        "control": control,
        "identity": identity,
        "base": base,
        "handoff_baseline": 0,
    }
    if (
        mod._native_read(base + DEFAULT_TARGET_RVA, len(DEFAULT_ORIGINAL))
        != hook["patch"]
    ):
        raise RuntimeError("Default wrapper patch readback failed")
    update_default(mod, pc, pawn, camera)
    logging.warning(
        f"{TAG} LADDER_DEFAULT_ARMED manager={identity[2]:#x} "
        f"enabled={bool(control.enabled)} variant={DEFAULT_VARIANT} "
        "additional_native_patches=1"
    )


def remove_default(mod, reason: str) -> None:
    """Disable first, restore code, then retire pinned executable/control."""
    state = mod._active_native_state.get(DEFAULT_KEY)
    if state is None:
        return
    control = state["control"]
    control.enabled = 0
    hook = state["hook"]
    mod._native_restore_hook(hook)
    if mod._native_read(int(hook["target"]), len(DEFAULT_ORIGINAL)) != DEFAULT_ORIGINAL:
        raise RuntimeError("Default wrapper restore readback failed; state retained")
    mod._native_release_hook(hook)
    mod._active_native_state.pop(DEFAULT_KEY, None)
    logging.warning(
        f"{TAG} LADDER_DEFAULT_RESTORED reason={reason!r} verified=True "
        f"visits={control.visits} replacements={control.replacements} "
        "additional_native_patches=0"
    )


def default_completed_handoff(mod) -> bool:
    """A real native replacement can span the complete Ladder mode between ticks.

    Confirm its new local TPS stack before treating that missed mode as seen.
    Native recoil still waits for the existing stable Walking/mantle gates.
    """
    state = mod._active_native_state.get(DEFAULT_KEY)
    if state is None:
        return False
    replacements = int(state["control"].replacements)
    if replacements <= int(state["handoff_baseline"]):
        return False
    pc, pawn, camera = mod._get_runtime()
    if (
        tuple(mod._object_address(obj) for obj in (pc, pawn, camera))
        != state["identity"]
        or pawn is None
        or camera is None
        or str(camera.GetActorCameraMode(pawn)) != "ThirdPerson"
        or not mod._ffyl_camera_stack_has_single_tps(camera)
    ):
        return False
    state["handoff_baseline"] = replacements
    logging.warning(
        f"{TAG} LADDER_DEFAULT_HANDOFF_CONFIRMED "
        f"replacements={replacements} stack=single_tps"
    )
    return True
