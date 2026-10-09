"""Scoped native recoil handoff guard for the simplified FFYL route.

Selected by the recoil entry point only with an explicit bound FFYL context.
The FFYL camera owner supplies that context after observing the lower layer.
The native stub restores ONLY
this owner's private Look vtable before SetActorCameraMode clears its runtime.
It does not choose a camera, write the stack, alter input or modify lower FFYL.
The retained ABI, code hash and original entry bytes are verified before install.
The assembly source is in docs/native/ffyl_recoil_guard.s for review. This module
shares the existing Set-hook owner and cleanup rather than adding a second owner.
"""

import ctypes
import hashlib
import struct

from unrealsdk import logging
from . import native_ladder_guard as production

KEY = "ladder_guard"


class FFYLGuardControl(ctypes.Structure):
    _fields_ = production._Control._fields_ + [
        ("lower", ctypes.c_uint64 * 5),
        ("top_descriptor", ctypes.c_uint64 * 3),
    ]


STUB = bytes.fromhex(
    "9c50415041514152415349ba222222222222222241837a40000f8588010000498b024839c10f857c0100004885d20f84"
    "73010000488b81303a0000493b82800000000f855f01000083b9c8390000020f855201000083b9cc390000020f8c4501"
    "000081b9cc390000000100000f8f350100004c8b99c03900004981fb000001000f8221010000498b42584939030f8514"
    "010000498b4260493943080f8506010000498b4268493943100f85f8000000498b4270493943180f85ea000000498b42"
    "78493943200f85dc000000498b8280000000493943280f85cb000000498b8288000000493943300f85ba000000498b82"
    "90000000493943380f85a90000004d8b42084d3943400f859b0000004c3981483a00000f858e0000004d39000f858500"
    "0000498b421049394348757b483981503a0000757249394008756c498b42184939401075624983781800755b458b4828"
    "4183f9017c514183f9407f4b453b482c7f454181782c000100007f3b4d8b48204981f900000100722e498b4220493901"
    "7525498b422849394108751b4d8b4a20498b42304d8b5a38f04d0fb119750841c7424001000000415b415a4159415858"
    "9d"
)
STUB_SHA = "80e63579f195567f05b1016308f9093ae24daee1c81594c2d1851ce8cfed831e"


def install(mod, owner, runtime_control, definition, *, context):
    """Install after upper-TPS ownership/build validation by the recoil caller.

    Context must still permit activation and resolve the original local UObject
    lifetimes. The shared Set owner key, control ABI and machine code are retained.
    Removal uses native_ladder_guard.remove; failed restoration keeps its owner.
    """
    ctx = context.proof_context()
    if (
        ctypes.sizeof(FFYLGuardControl) != 152
        or FFYLGuardControl.status.offset != 64
        or FFYLGuardControl.lower.offset != 88
        or FFYLGuardControl.top_descriptor.offset != 128
        or len(owner.identity) != 4
        or not all(owner.identity)
        or not ctx
        or ctx["manager"] != owner.identity[0]
        or not runtime_control
        or not definition
    ):
        raise RuntimeError("FFYL upper TPS guard context/layout incomplete")
    if mod._active_native_state.get(KEY) is not None:
        raise RuntimeError("Native Set already owned")
    if (
        len(STUB) != 433
        or hashlib.sha256(STUB).hexdigest() != STUB_SHA
        or STUB.count(b"\x22" * 8) != 1
    ):
        raise RuntimeError("FFYL upper TPS guard code differs")
    base = int(mod._kernel32.GetModuleHandleW(None) or 0)
    target = base + production.TARGET_RVA
    original_entry = production.PROLOGUE + production.CONTINUATION
    if not base or mod._native_read(target, len(original_entry)) != original_entry:
        raise RuntimeError("Native Set entry differs")
    lower = bytes.fromhex(owner.owned_lower_entry)
    if lower != ctx["lower_entry"]:
        raise RuntimeError("Guard lower FFYL owner differs")
    top = bytes.fromhex(owner.stack_descriptor)
    control = FFYLGuardControl(
        *owner.identity[:2],
        runtime_control,
        definition,
        owner.identity[2],
        owner.identity[3],
        owner.shadow_vt,
        owner.original_vt,
        0,
        0,
        0,
        0,
        0,
        (ctypes.c_uint64 * 5)(*struct.unpack("<5Q", lower)),
        (ctypes.c_uint64 * 3)(*struct.unpack("<3Q", top)),
    )
    trace = ctypes.create_string_buffer(8 + production.TRACE_CAP * 64)
    control._trace_buffer = trace

    def build(stub, trampoline):
        code = STUB.replace(b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control)))
        return None, control, code + mod._native_absolute_jump(trampoline)

    hook = mod._native_allocate_hook(
        target,
        production.PROLOGUE,
        len(production.PROLOGUE),
        build,
        "owned FFYL top TPS recoil handoff",
    )
    mod._active_native_state[KEY] = dict(
        hook=hook,
        control=control,
        owner_identity=tuple(owner.identity),
        consumed=False,
        slide_interior=False,
        trace_buffer=trace,
        trace_base=base,
        ffyl_upper_tps=True,
    )
    try:
        if mod._native_read(target, len(hook["patch"])) != hook["patch"]:
            raise RuntimeError("FFYL upper TPS Set guard patch readback differs")
    except Exception:
        production.remove(mod)
        raise
    logging.warning("[BL4ThirdPersonPOC.FFYLRecoilGuard] ARMED native_patches=1")


def consume(mod, owner):
    """Acknowledge only this FFYL guard's successful native VTable restoration.

    Native status 1 is set only after the measured compare/exchange succeeds.
    The old Look must not be dereferenced here: BL4 may already have destroyed
    it. Status 0 means no event. Registry ownership and retirement are checked
    separately; cleanup exceptions propagate with the guard still registered.
    """
    state = mod._active_native_state.get(KEY)
    if state is None:
        return 0
    if not state.get("ffyl_upper_tps"):
        raise RuntimeError("FFYL guard cannot consume another Set owner")
    status = int(state["control"].status)
    if status == 0:
        return 0
    if status != 1:
        raise RuntimeError("Unexpected FFYL recoil guard status")
    if (
        owner is None
        or getattr(owner, "active", False) is not True
        or tuple(owner.identity) != state["owner_identity"]
        or state["consumed"]
    ):
        raise RuntimeError("FFYL native restoration has no matching recoil owner")
    state["consumed"] = True
    owner.active = False
    owner.native_pre_restored_mode = "ffyl_upper_tps"
    production.remove(mod)
    return 1
