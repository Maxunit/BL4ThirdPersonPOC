"""Validate readable/executable memory and construct native detours.

Use VirtualQuery and bounded reads before decoding native structures. The floor
pickup router uses the existing bounded AOB search plus expected-entry checks;
other sites remain tied to explicit executable/byte fingerprints and RVAs.
Absolute jumps preserve registers. Trampolines copy audited whole instructions;
they are not relocators and do not repair RIP-relative operands automatically.
Writes change protection, flush code and restore protection. Allocation rollback
restores only owned bytes; callers own game-thread use, identity and retirement.
Manager-stack offsets and ctypes layouts apply only to the verified build.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import struct
from .build_gate import REVIEWED_BUILD
from typing import Any

from unrealsdk import logging

# During existing prompt updates, the native override points
# the game's interaction query at
# the TPS crosshair while TPS gameplay is active.  The original query remains
# byte-for-byte native in FPS, ADS, vehicles, ladders, and shops.
INTERACTION_PROMPT_TARGET_RVA = 0x03E542B5
INTERACTION_PROMPT_HOOK_LENGTH = 14
INTERACTION_PROMPT_TARGET_PREFIX = bytes.fromhex(
    "8A 45 71 88 44 24 7F 84 C0 BE 08 00 00 00"
)
INTERACTION_PROMPT_SAFETY_WINDOW_RVA = 0x03E542AF
INTERACTION_PROMPT_SAFETY_WINDOW = bytes.fromhex(
    "0F 8D 40 20 00 00 8A 45 71 88 44 24 7F 84 C0 BE 08 00 00 00 "
    "B8 58 00 00 00 48 0F 45 F0 F2 0F 10 44 35 00"
)
INTERACTION_PROMPT_UPDATE_IDENTIFIER = "bl4_third_person_poc.interaction_prompt_target"
INTERACTION_PROMPT_NATIVE_RAY_LENGTH = 3003.0
# Preserve the game's candidate/range decision for conversation NPCs.
NPC_ELIGIBLE_BUILD = REVIEWED_BUILD[0]
NPC_ELIGIBLE_RVA = 0x03E54995
NPC_ELIGIBLE_ORIGINAL = bytes.fromhex("b101898c24c800000084c00f843a090000")
NPC_ELIGIBLE_CANDIDATE_OFFSET = 0x3A90
NPC_ELIGIBLE_CONTINUATION_RVA = 0x03E552E0
NPC_ELIGIBLE_STUB = bytes.fromhex(
    "9c4152415349ba111111111111111149833a01752d49bb5555555555555555"
    "49833b01751d49bb2222222222222222493b3b750e49837a08007507"
    "f049ff4210b000415b415a9db101898c24c800000084c0"
    "750eff25000000003333333333333333ff25000000004444444444444444"
)
FLOOR_PICKUP_TARGET_OFFSET = 0x530
FLOOR_PICKUP_CONTEXT_OFFSET = 0xDA8
FLOOR_PICKUP_ROUTER_EXPECTED_RVA = 0x00B47002
FLOOR_PICKUP_ROUTER_PATTERN = (
    "41 57 41 56 56 57 55 53 48 81 EC 98 00 00 00 "
    "48 8B 05 ?? ?? ?? ?? 48 31 E0 48 89 84 24 90 00 00 00 "
    "48 85 D2 0F 84 ?? ?? ?? ?? "
    "4C 89 C7 49 89 D6 48 89 CB 48 8D B1 ?? ?? ?? ?? "
    "48 8B 02 4C 8D BC"
)
FLOOR_PICKUP_AOB_CHUNK_SIZE = 4 * 1024 * 1024

# Item-card fusion: Gearbox's native gate 2 retains the intended near/far UI
# policy, while a projected per-pickup OBB supplies the TPS crosshair identity.
ITEM_CARD_GATE2_TARGET_RVA = 0x03E5604C
ITEM_CARD_GATE2_HOOK_LENGTH = 16
ITEM_CARD_GATE2_TARGET_PREFIX = bytes.fromhex(
    "4C 39 F3 0F 94 44 24 28 48 8D 84 24 28 03 00 00"
)
ITEM_CARD_GATE2_CONTINUATION_PREFIX = bytes.fromhex(
    "48 89 44 24 20 4C 89 E1 48 8B 94 24 90 01 00 00"
)
ITEM_CARD_GATE2_RECORD_SIZE = 0x70
ITEM_CARD_GATE2_RING_CAPACITY = 16384
ITEM_CARD_GATE2_RING_MASK = ITEM_CARD_GATE2_RING_CAPACITY - 1
ITEM_CARD_GATE2_BUFFER_SIZE = (
    8 + ITEM_CARD_GATE2_RING_CAPACITY * ITEM_CARD_GATE2_RECORD_SIZE
)

ITEM_CARD_FINAL_TARGET_RVA = 0x03E56206
ITEM_CARD_FINAL_HOOK_LENGTH = 19
ITEM_CARD_FINAL_TARGET_PREFIX = bytes.fromhex(
    "48 8B 8C 24 30 03 00 00 48 85 C9 " "4C 8B BC 24 80 00 00 00"
)
ITEM_CARD_FINAL_CONTINUATION_PREFIX = bytes.fromhex(
    "4C 8B AC 24 88 00 00 00 74 05 E8 80 BE 1A FC"
)
ITEM_CARD_FINAL_RECORD_SIZE = 0x40
ITEM_CARD_FINAL_RING_CAPACITY = 8192
ITEM_CARD_FINAL_RING_MASK = ITEM_CARD_FINAL_RING_CAPACITY - 1
ITEM_CARD_FINAL_BUFFER_SIZE = (
    8 + ITEM_CARD_FINAL_RING_CAPACITY * ITEM_CARD_FINAL_RECORD_SIZE
)

ITEM_CARD_STABLE_SELECTION_SAMPLES = 3
ITEM_CARD_GATE2_GRACE_UPDATES = 2
ITEM_CARD_GATE2_SAFE_LAG = 2
ITEM_CARD_PICKUP_REFRESH_INTERVAL = 0.50
ITEM_CARD_GEOMETRY_STABLE_SAMPLES = 3
ITEM_CARD_GEOMETRY_CENTER_EPSILON = 1.0
ITEM_CARD_GEOMETRY_AXIS_EPSILON = 0.002
ITEM_CARD_GEOMETRY_TRACK_TIMEOUT = 15.0
ITEM_CARD_GEOMETRY_TRACK_BUDGET = 8
ITEM_CARD_GEOMETRY_BACKGROUND_BUDGET = 2
ITEM_CARD_GEOMETRY_COLLAPSE_RATIO = 0.25
ITEM_CARD_MAX_DEBUG_EVENTS = 256


_MEM_COMMIT = 0x1000
_MEM_RESERVE = 0x2000
_MEM_RELEASE = 0x8000
_MEM_IMAGE = 0x1000000
_PAGE_NOACCESS = 0x01
_PAGE_GUARD = 0x100
_PAGE_EXECUTE_READWRITE = 0x40
_EXECUTE_PROTECTIONS = {0x10, 0x20, 0x40, 0x80}


def _native_query(address: int, _kernel32: Any, _MEMORY_BASIC_INFORMATION: type) -> Any:
    mbi = _MEMORY_BASIC_INFORMATION()
    if not _kernel32.VirtualQuery(
        ctypes.c_void_p(address),
        ctypes.byref(mbi),
        ctypes.sizeof(mbi),
    ):
        raise RuntimeError(f"VirtualQuery failed at 0x{address:X}")
    return mbi


def _native_require_readable(
    address: int,
    size: int,
    label: str,
    _native_query,
) -> None:
    """Check committed accessible regions spanning the requested memory range.

    Callers must validate address/size bounds and UObject lifetime separately;
    VirtualQuery is not a lock and does not establish native semantic ownership.
    """
    end = address + size
    cursor = address
    while cursor < end:
        mbi = _native_query(cursor)
        region_end = int(mbi.BaseAddress or 0) + int(mbi.RegionSize)
        protect = int(mbi.Protect)
        if (
            int(mbi.State) != _MEM_COMMIT
            or protect & _PAGE_GUARD
            or (protect & 0xFF) == _PAGE_NOACCESS
        ):
            raise RuntimeError(f"{label} is inaccessible at 0x{cursor:X}")
        if region_end <= cursor:
            raise RuntimeError(f"Invalid memory region for {label}")
        cursor = min(region_end, end)


def _native_require_executable(address: int, label: str, _native_query) -> None:
    """Require a committed executable, nonguarded page for a validated address."""
    mbi = _native_query(address)
    protect = int(mbi.Protect)
    if (
        int(mbi.State) != _MEM_COMMIT
        or protect & _PAGE_GUARD
        or (protect & 0xFF) not in _EXECUTE_PROTECTIONS
    ):
        raise RuntimeError(
            f"{label} is not executable at 0x{address:X}; " f"protect=0x{protect:X}"
        )


def _native_image_size(module_base: int, _native_read) -> int:
    dos_header = _native_read(module_base, 0x40)
    if dos_header[:2] != b"MZ":
        raise RuntimeError("Main module has no MZ header")
    pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
    nt_headers = _native_read(module_base + pe_offset, 0x58)
    if nt_headers[:4] != b"PE\x00\x00":
        raise RuntimeError("Main module has no PE header")
    return int(struct.unpack_from("<I", nt_headers, 0x50)[0])


def _native_executable_regions(module_base: int, image_size: int, _native_query):
    """Yield executable regions belonging to the main image for a bounded scan."""
    image_end = module_base + image_size
    cursor = module_base
    while cursor < image_end:
        mbi = _native_query(cursor)
        region_base = int(mbi.BaseAddress or 0)
        region_end = min(
            region_base + int(mbi.RegionSize),
            image_end,
        )
        protect = int(mbi.Protect)
        if (
            int(mbi.State) == _MEM_COMMIT
            and int(mbi.Type) == _MEM_IMAGE
            and int(mbi.AllocationBase or 0) == module_base
            and not (protect & _PAGE_GUARD)
            and (protect & 0xFF) in _EXECUTE_PROTECTIONS
        ):
            yield max(cursor, region_base), region_end
        if region_end <= cursor:
            raise RuntimeError(f"Invalid image region at 0x{cursor:X}")
        cursor = region_end


def _native_absolute_jump(address: int) -> bytes:
    """Encode a 14-byte x64 absolute jump without clobbering registers."""
    return b"\xff\x25\x00\x00\x00\x00" + struct.pack("<Q", address)


def _native_build_trampoline(
    original: bytes,
    return_address: int,
) -> bytes:
    """Append a return jump to previously audited whole instructions.

    This helper does not decode or relocate RIP-relative instructions. Callers
    must prove that copying the chosen instruction window is valid.
    """
    return original + _native_absolute_jump(return_address)


def _item_card_store_r11(code: bytearray, displacement: int) -> None:
    if displacement <= 0x7F:
        code += b"\x4c\x89\x58" + bytes((displacement,))
    else:
        code += b"\x4c\x89\x98" + struct.pack("<I", displacement)


def _item_card_copy_rbp_qword(
    code: bytearray,
    source: int,
    destination: int,
) -> None:
    code += b"\x4c\x8b\x5d" + bytes((source,))
    _item_card_store_r11(code, destination)


def _item_card_copy_stack_qword(
    code: bytearray,
    source: int,
    destination: int,
) -> None:
    code += b"\x4c\x8b\x9c\x24" + struct.pack("<I", source)
    _item_card_store_r11(code, destination)


def _item_card_rel32(code: bytearray, opcode: bytes) -> int:
    code += opcode
    position = len(code)
    code += b"\0\0\0\0"
    return position


def _item_card_patch_rel32(
    code: bytearray,
    position: int,
    destination: int,
) -> None:
    struct.pack_into("<i", code, position, destination - (position + 4))


def _item_card_build_gate2_stub(
    buffer_address: int,
    trampoline_address: int,
) -> bytes:
    # Native Gate-2 recorder: preserve the audited instruction and register ABI.
    """Build the native eligibility observer with the fixed ring/control ABI.

    The caller provides the verified instruction window, pinned ring storage
    and continuation. This recorder does not select the final item-card actor.
    """
    code = bytearray()
    code += b"\x9c\x50\x41\x52\x41\x53"
    code += b"\x48\xb8" + struct.pack("<Q", buffer_address)
    code += b"\x41\xba\x01\x00\x00\x00"
    code += b"\xf0\x4c\x0f\xc1\x10"
    code += b"\x4d\x89\xd3"
    code += b"\x41\x81\xe2" + struct.pack("<I", ITEM_CARD_GATE2_RING_MASK)
    code += b"\x4d\x69\xd2" + struct.pack("<I", ITEM_CARD_GATE2_RECORD_SIZE)
    code += b"\x4a\x8d\x44\x10\x08"
    _item_card_store_r11(code, 0x00)
    code += b"\x48\x89\x70\x08"
    code += b"\x48\x89\x68\x10"
    code += b"\x44\x0f\xb6\x5d\x71"
    _item_card_store_r11(code, 0x18)
    for source, destination in (
        (0x08, 0x20),
        (0x10, 0x28),
        (0x18, 0x30),
        (0x20, 0x38),
        (0x28, 0x40),
        (0x30, 0x48),
        (0x58, 0x50),
        (0x60, 0x58),
        (0x68, 0x60),
    ):
        _item_card_copy_rbp_qword(code, source, destination)
    code += b"\x41\x5b\x41\x5a\x58\x9d"
    code += _native_absolute_jump(trampoline_address)
    return bytes(code)


def _item_card_build_final_stub(
    control_address: int,
    buffer_address: int,
    trampoline_address: int,
    pickup_actors: tuple[int, ...],
) -> bytes:
    # The authoritative final-actor selector owns the result. An enabled null
    # selection intentionally clears RSI so an FPS-selected card cannot leak
    # through while the TPS crosshair has no gate-2/OBB-qualified pickup.
    """Build the final selector using the caller's published actor/control storage.

    An enabled null selection suppresses a stale native actor. Preserve the
    fixed record layout, register ABI and audited continuation instructions.
    """
    code = bytearray()
    code += b"\x50\x51\x41\x51\x41\x52\x41\x53"
    code += b"\x4c\x8b\xce"
    code += b"\x49\xba" + struct.pack("<Q", control_address)
    code += b"\x4d\x8b\x1a"
    code += b"\x4d\x85\xdb"
    record_native = _item_card_rel32(code, b"\x0f\x84")
    code += b"\x4d\x8b\x5a\x08"
    code += b"\x4d\x85\xdb"
    clear_jump = _item_card_rel32(code, b"\x0f\x84")

    valid_jumps = []
    for actor in pickup_actors:
        code += b"\x48\xb8" + struct.pack("<Q", actor)
        code += b"\x49\x39\xc3"
        valid_jumps.append(_item_card_rel32(code, b"\x0f\x84"))
    invalid_jump = _item_card_rel32(code, b"\xe9")

    valid_label = len(code)
    code += b"\x4c\x89\xde"
    valid_to_record = _item_card_rel32(code, b"\xe9")
    clear_label = len(code)
    code += b"\x31\xf6"
    record_label = len(code)
    _item_card_patch_rel32(code, record_native, record_label)
    _item_card_patch_rel32(code, clear_jump, clear_label)
    _item_card_patch_rel32(code, invalid_jump, record_label)
    _item_card_patch_rel32(code, valid_to_record, record_label)
    for position in valid_jumps:
        _item_card_patch_rel32(code, position, valid_label)

    code += b"\x48\xb8" + struct.pack("<Q", buffer_address)
    code += b"\x41\xba\x01\x00\x00\x00"
    code += b"\xf0\x4c\x0f\xc1\x10"
    code += b"\x4d\x89\xd3"
    code += b"\x41\x81\xe2" + struct.pack("<I", ITEM_CARD_FINAL_RING_MASK)
    code += b"\x4d\x6b\xd2" + bytes((ITEM_CARD_FINAL_RECORD_SIZE,))
    code += b"\x4a\x8d\x44\x10\x08"
    _item_card_store_r11(code, 0x00)
    code += b"\x4c\x89\x48\x08"
    code += b"\x48\x89\x70\x10"
    code += b"\x49\xba" + struct.pack("<Q", control_address)
    code += b"\x4d\x8b\x5a\x08"
    _item_card_store_r11(code, 0x18)
    code += b"\x4d\x8b\x1a"
    _item_card_store_r11(code, 0x20)
    _item_card_copy_stack_qword(code, 0x0E0, 0x28)
    _item_card_copy_stack_qword(code, 0xCF8, 0x30)
    _item_card_copy_stack_qword(code, 0xD08, 0x38)
    code += b"\x41\x5b\x41\x5a\x41\x59\x59\x58"
    code += _native_absolute_jump(trampoline_address)
    return bytes(code)


def _interaction_prompt_xmm_store(
    register: int,
    displacement: int,
) -> bytes:
    if displacement == 0:
        return b"\xf3\x0f\x7f" + bytes((0x04 | (register << 3), 0x24))
    return b"\xf3\x0f\x7f" + bytes((0x44 | (register << 3), 0x24, displacement))


def _interaction_prompt_xmm_load(
    register: int,
    displacement: int,
) -> bytes:
    if displacement == 0:
        return b"\xf3\x0f\x6f" + bytes((0x04 | (register << 3), 0x24))
    return b"\xf3\x0f\x6f" + bytes((0x44 | (register << 3), 0x24, displacement))


def _interaction_prompt_build_stub(
    control_address: int,
    counter_address: int,
    point_pointer_address: int,
    trampoline_address: int,
) -> bytes:
    """Build the live-origin prompt-query shim with an FPS gate."""
    code = bytearray()
    code += b"\x50"  # push rax
    code += b"\x41\x52"  # push r10
    code += b"\x48\x83\xec\x50"  # sub rsp, 0x50
    for register, displacement in enumerate((0x00, 0x10, 0x20, 0x30, 0x40)):
        code += _interaction_prompt_xmm_store(register, displacement)

    code += b"\x48\xb8" + struct.pack("<Q", control_address)
    code += b"\x48\x83\x38\x00"  # cmp qword ptr [rax], 0
    disabled_jump = _item_card_rel32(code, b"\x0f\x84")

    code += b"\x48\xb8" + struct.pack("<Q", counter_address)
    code += b"\xf0\x48\xff\x00"  # lock inc qword ptr [rax]

    # Load one complete immutable target-point buffer through its atomically
    # published pointer.
    code += b"\x49\xba" + struct.pack("<Q", point_pointer_address)
    code += b"\x4d\x8b\x12"  # mov r10, [r10]

    # Match the native query's active origin. The measured query uses the
    # alternate origin is rbp+58/+60/+68 (not the earlier +50 guess).
    code += b"\x80\x7d\x71\x00"
    alternate_jump = len(code) + 1
    code += b"\x75\x00"

    code += b"\xf2\x41\x0f\x10\x02\xf2\x0f\x5c\x45\x08"
    code += b"\xf2\x41\x0f\x10\x4a\x08\xf2\x0f\x5c\x4d\x10"
    code += b"\xf2\x41\x0f\x10\x52\x10\xf2\x0f\x5c\x55\x18"
    common_jump = len(code) + 1
    code += b"\xeb\x00"

    alternate_label = len(code)
    code += b"\xf2\x41\x0f\x10\x02\xf2\x0f\x5c\x45\x58"
    code += b"\xf2\x41\x0f\x10\x4a\x08\xf2\x0f\x5c\x4d\x60"
    code += b"\xf2\x41\x0f\x10\x52\x10\xf2\x0f\x5c\x55\x68"
    common_label = len(code)
    code[alternate_jump] = (alternate_label - (alternate_jump + 1)) & 0xFF
    code[common_jump] = (common_label - (common_jump + 1)) & 0xFF

    # Normalize the point-origin delta to Gearbox's native 3003-unit ray.
    code += b"\x66\x0f\x28\xd8\xf2\x0f\x59\xd8"
    code += b"\x66\x0f\x28\xe1\xf2\x0f\x59\xe1"
    code += b"\xf2\x0f\x58\xdc"
    code += b"\x66\x0f\x28\xe2\xf2\x0f\x59\xe2"
    code += b"\xf2\x0f\x58\xdc\xf2\x0f\x51\xdb"
    code += b"\xf2\x41\x0f\x10\x62\x18"
    code += b"\xf2\x0f\x5e\xe3"
    code += b"\xf2\x0f\x59\xc4\xf2\x0f\x59\xcc\xf2\x0f\x59\xd4"
    code += b"\xf2\x0f\x11\x45\x20"
    code += b"\xf2\x0f\x11\x4d\x28"
    code += b"\xf2\x0f\x11\x55\x30"

    # The native item-card angle gate reads yaw from rbp+0x40, independent
    # of the query ray above. Derive it from the same live-origin ray so a
    # pickup under the TPS crosshair does not fail the native 0.9 dot gate.
    # FLD y; FLD x; FPATAN = atan2(y,x). The x87 stack is balanced before
    # returning, and the preexisting XMM save/restore covers the wrap below.
    code += b"\xdd\x45\x28"  # fld qword ptr [rbp+0x28]
    code += b"\xdd\x45\x20"  # fld qword ptr [rbp+0x20]
    code += b"\xd9\xf3"  # fpatan
    code += b"\x41\xdc\x4a\x20"  # fmul qword ptr [r10+0x20] (180/pi)
    code += b"\xdd\x5d\x40"  # fstp qword ptr [rbp+0x40]
    code += b"\xf2\x0f\x10\x45\x40"  # movsd xmm0,[rbp+0x40]
    code += b"\x66\x0f\x57\xc9"  # xorpd xmm1,xmm1
    code += b"\x66\x0f\x2e\xc1"  # ucomisd xmm0,xmm1
    nonnegative = _item_card_rel32(code, b"\x0f\x83")
    code += b"\xf2\x41\x0f\x58\x42\x28"  # addsd xmm0,[r10+0x28] (360)
    code += b"\xf2\x0f\x11\x45\x40"  # movsd [rbp+0x40],xmm0
    _item_card_patch_rel32(code, nonnegative, len(code))

    restore_label = len(code)
    _item_card_patch_rel32(code, disabled_jump, restore_label)
    for register, displacement in reversed(
        tuple(enumerate((0x00, 0x10, 0x20, 0x30, 0x40)))
    ):
        code += _interaction_prompt_xmm_load(register, displacement)
    code += b"\x48\x83\xc4\x50"
    code += b"\x41\x5a"
    code += b"\x58"
    code += _native_absolute_jump(trampoline_address)
    return bytes(code)


def _native_write_code(
    address: int, data: bytes, *, _kernel32, _PAGE_EXECUTE_READWRITE, _admit=None
) -> None:
    """Write code, flush the instruction cache, and restore page protection.

    The caller supplies validated addresses/bytes and owns synchronization,
    original-byte comparison, readback and rollback. This primitive does not
    decide which game build or patch owner is eligible. Protection restoration
    is attempted even when writing or cache flushing raises.
    """
    old_protect = wintypes.DWORD()
    if not _kernel32.VirtualProtect(
        ctypes.c_void_p(address),
        len(data),
        _PAGE_EXECUTE_READWRITE,
        ctypes.byref(old_protect),
    ):
        raise OSError(
            ctypes.get_last_error(),
            "Item-card VirtualProtect RWX failed",
        )
    try:
        if _admit is not None:
            _admit(old_protect.value)
        ctypes.memmove(address, data, len(data))
        if not _kernel32.FlushInstructionCache(
            _kernel32.GetCurrentProcess(),
            ctypes.c_void_p(address),
            len(data),
        ):
            raise OSError(
                ctypes.get_last_error(),
                "Item-card FlushInstructionCache failed",
            )
    finally:
        restored = wintypes.DWORD()
        if not _kernel32.VirtualProtect(
            ctypes.c_void_p(address),
            len(data),
            old_protect.value,
            ctypes.byref(restored),
        ):
            raise OSError(
                ctypes.get_last_error(),
                "Item-card VirtualProtect restore failed",
            )


def _native_allocate_hook(
    target: int,
    original: bytes,
    hook_length: int,
    stub_data_builder: Any,
    label: str,
    *,
    _kernel32,
    _native_read,
    _native_write_code,
    _native_release_hook,
    _quarantine_native_patch,
) -> dict[str, Any]:
    """Allocate a bounded detour and publish its patch with guarded rollback.

    builder(stub, trampoline) returns (buffer_pin, control_pin, stub_bytes).
    The allocation contains a stub below +0x1800 and a trampoline after it.
    The caller must validate target bytes, instruction boundaries, ABI and game
    build before entering this function. Calls belong on the game thread.

    Returned metadata owns the original bytes, installed patch and Python
    pins. If installation fails, restore only known original/patch bytes;
    quarantine unrecognized ownership instead of freeing reachable memory.
    Published allocations are retired by the supplied hook-retirement helper.
    Existing consumers retain the item_card quarantine category. The pickup
    registry observer uses its distinct control layout and cleanup category.
    """
    stub = int(
        _kernel32.VirtualAlloc(
            None,
            0x2000,
            _MEM_COMMIT | _MEM_RESERVE,
            _PAGE_EXECUTE_READWRITE,
        )
        or 0
    )
    if not stub:
        raise RuntimeError(f"Could not allocate {label} stub")
    trampoline = stub + 0x1800
    try:
        buffer, control, stub_data = stub_data_builder(stub, trampoline)
        trampoline_data = _native_build_trampoline(
            original,
            target + hook_length,
        )
    except Exception:
        _kernel32.VirtualFree(ctypes.c_void_p(stub), 0, _MEM_RELEASE)
        raise
    if len(stub_data) >= 0x1800 or len(trampoline_data) >= 0x800:
        _kernel32.VirtualFree(ctypes.c_void_p(stub), 0, _MEM_RELEASE)
        raise RuntimeError(f"{label} stub exceeded bounded allocation")
    patch = _native_absolute_jump(stub) + b"\x90" * (hook_length - 14)
    hook = {
        "target": target,
        "original": original,
        "patch": patch,
        "stub": stub,
        "trampoline": trampoline,
        "buffer": buffer,
        "control": control,
        "restored": False,
        "patch_attempted": False,
        "label": label,
    }
    try:
        ctypes.memmove(stub, stub_data, len(stub_data))
        ctypes.memmove(trampoline, trampoline_data, len(trampoline_data))
        process = _kernel32.GetCurrentProcess()
        if not _kernel32.FlushInstructionCache(
            process,
            ctypes.c_void_p(stub),
            len(stub_data),
        ):
            raise OSError(
                ctypes.get_last_error(),
                f"{label} stub flush failed",
            )
        if not _kernel32.FlushInstructionCache(
            process,
            ctypes.c_void_p(trampoline),
            len(trampoline_data),
        ):
            raise OSError(
                ctypes.get_last_error(),
                f"{label} trampoline flush failed",
            )
        hook["patch_attempted"] = True
        _native_write_code(target, patch)
        return hook
    except Exception:
        cleanup_failure: Exception | None = None
        try:
            current = _native_read(target, hook_length)
            if current == patch:
                _native_write_code(target, original)
                hook["restored"] = True
            elif current == original:
                hook["restored"] = True
            else:
                raise RuntimeError(
                    f"{label} install rollback refused; bytes changed: "
                    f"{current.hex(' ')}"
                )
            _native_release_hook(hook)
        except Exception as exc:
            cleanup_failure = exc
        if cleanup_failure is not None:
            if label == "pickup registry":
                # The entry observer has its own control layout and cleanup;
                # item-card selection stop must never be applied to this hook.
                quarantine_state = {
                    "hook": hook, "active": False, "errors": [], "error_count": 0,
                }
                quarantine_kind = "pickup_registry"
            else:
                quarantine_state = {
                    "gate2_hook" if "gate-2" in label else "final_hook": hook
                }
                quarantine_kind = "item_card"
            _quarantine_native_patch(
                quarantine_kind,
                quarantine_state,
                f"install_rollback_incomplete:{type(cleanup_failure).__name__}",
            )
            logging.error(
                "[BL4ThirdPersonPOC] Item-card install rollback failure: "
                f"{type(cleanup_failure).__name__}: {cleanup_failure}"
            )
        raise


# ADS delegate layout and native collector association.
def _ads_object_address(value: Any) -> int:
    try:
        return int(value._get_address())
    except Exception:
        return 0


def _ads_property_rows(obj: Any) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    seen: set[tuple[str, int]] = set()
    try:
        fields = tuple(obj.Class._superfields())
    except Exception:
        fields = ()
    for field in fields:
        try:
            properties = tuple(field._properties())
        except Exception:
            continue
        for prop in properties:
            try:
                name = str(prop.Name)
                offset = int(prop.Offset_Internal)
                size = max(1, int(prop.ElementSize) * int(prop.ArrayDim))
            except Exception:
                continue
            key = (name, offset)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name, "offset": offset, "size": size})
    return rows


def _ads_delegate_listener_index(weapon: Any, _native_read) -> int | None:
    row = next(
        (row for row in _ads_property_rows(weapon) if row["name"] == "NotifyZoomingIn"),
        None,
    )
    if row is None:
        return None
    header = _native_read(
        _ads_object_address(weapon) + int(row["offset"]),
        16,
    )
    pointer, count, _capacity = struct.unpack_from("<Qii", header, 0)
    if pointer == 0 or count <= 0:
        return None
    entry = _native_read(pointer, 16)
    object_index, _serial, _fname_index, _fname_number = struct.unpack_from(
        "<iiII",
        entry,
        0,
    )
    return int(object_index)


def _find_ads_collector(weapon: Any, _native_read, find_all) -> Any:
    expected_index = _ads_delegate_listener_index(weapon, _native_read)
    values = tuple(find_all("OakUIDataCollector_Weapon"))
    if expected_index is not None:
        for value in values:
            try:
                if int(value.InternalIndex) == expected_index:
                    return value
            except Exception:
                continue
    if len(values) == 1:
        return values[0]
    raise RuntimeError(
        "Could not uniquely resolve OakUIDataCollector_Weapon; "
        f"delegate_index={expected_index}, candidates={len(values)}"
    )


# Native floor pickup resolution and validated dispatch.
def _resolve_floor_pickup_router(
    *,
    _kernel32,
    _native_read,
    _native_image_size,
    _native_require_executable,
    _native_executable_regions,
) -> int:
    module_base = int(_kernel32.GetModuleHandleW(None) or 0)
    if not module_base:
        raise RuntimeError("Could not resolve main module base")
    image_size = _native_image_size(module_base)
    pattern = [
        None if token == "??" else int(token, 16)
        for token in FLOOR_PICKUP_ROUTER_PATTERN.split()
    ]

    expected = module_base + FLOOR_PICKUP_ROUTER_EXPECTED_RVA
    try:
        expected_bytes = _native_read(expected, len(pattern))
        if all(
            value is None or expected_bytes[index] == value
            for index, value in enumerate(pattern)
        ):
            _native_require_executable(expected, "Use router fast path")
            logging.info(
                "[BL4ThirdPersonPOC] Native floor-pickup router "
                "fast validation passed"
            )
            return expected
        logging.warning(
            "[BL4ThirdPersonPOC] Native floor-pickup router "
            "fast validation did not match; starting AOB fallback scan"
        )
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Native floor-pickup router "
            "fast validation failed; starting AOB fallback scan: "
            f"{type(exc).__name__}: {exc}"
        )

    anchor = bytes(pattern[:15])
    overlap = len(pattern) - 1
    matches: list[int] = []

    for region_start, region_end in _native_executable_regions(
        module_base,
        image_size,
    ):
        cursor = region_start
        carry = b""
        while cursor < region_end:
            amount = min(
                FLOOR_PICKUP_AOB_CHUNK_SIZE,
                region_end - cursor,
            )
            data = carry + _native_read(cursor, amount)
            data_base = cursor - len(carry)
            search_from = 0
            while True:
                hit = data.find(anchor, search_from)
                if hit < 0:
                    break
                if hit + len(pattern) <= len(data) and all(
                    expected is None or data[hit + index] == expected
                    for index, expected in enumerate(pattern)
                ):
                    address = data_base + hit
                    if region_start <= address and address + len(pattern) <= region_end:
                        matches.append(address)
                search_from = hit + 1
            carry = data[-overlap:] if len(data) >= overlap else data
            cursor += amount

    matches = sorted(set(matches))
    if len(matches) != 1:
        raise RuntimeError(f"Use-router AOB is not unique: matches={len(matches)}")
    router = matches[0]
    _native_require_executable(router, "Use router")
    logging.info(
        "[BL4ThirdPersonPOC] Native floor-pickup router resolved by "
        f"AOB fallback scan at rva=0x{router - module_base:X}"
    )
    return router


def _use_native_floor_pickup(
    target_object: Any,
    *,
    _floor_pickup_native_ready,
    _floor_pickup_router_address,
    _get_runtime,
    _native_require_readable,
    _native_read,
    _native_require_executable,
    _FLOOR_PICKUP_USE_REQUEST,
) -> bool:
    if not _floor_pickup_native_ready:
        logging.warning("[BL4ThirdPersonPOC] Native floor pickup unavailable")
        return False

    pc, _pawn, _camera_manager = _get_runtime()
    if pc is None:
        return False

    try:
        pc_address = int(pc._get_address())
        pickup_address = int(target_object._get_address())
        context = pc_address + FLOOR_PICKUP_CONTEXT_OFFSET
        native_target = pickup_address + FLOOR_PICKUP_TARGET_OFFSET

        _native_require_readable(
            pc_address,
            FLOOR_PICKUP_CONTEXT_OFFSET + 8,
            "PlayerController",
        )
        _native_require_readable(
            native_target,
            8,
            "InventoryPickup Use subobject",
        )
        vtable = struct.unpack(
            "<Q",
            _native_read(native_target, 8),
        )[0]
        _native_require_readable(
            vtable,
            0x30,
            "InventoryPickup Use vtable",
        )
        virtual_use = struct.unpack(
            "<Q",
            _native_read(vtable + 0x28, 8),
        )[0]
        _native_require_executable(
            virtual_use,
            "InventoryPickup virtual Use function",
        )
        _native_require_executable(
            _floor_pickup_router_address,
            "cached Use router",
        )

        request = _FLOOR_PICKUP_USE_REQUEST()
        request.owner = pc_address
        request.context = context
        request.flag_a = 0
        request.flag_b = 0
        router_type = ctypes.WINFUNCTYPE(
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        result = router_type(_floor_pickup_router_address)(
            ctypes.c_void_p(context),
            ctypes.c_void_p(native_target),
            ctypes.byref(request),
        )
        logging.info(
            "[BL4ThirdPersonPOC] Native TPS floor pickup used "
            f"{target_object._path_name()}; result=0x{int(result):X}"
        )
        return True
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Native TPS floor pickup failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


# Verified FFYL camera stack snapshots.
def _ffyl_camera_stack_empty(
    camera_manager: Any, *, _kernel32, _native_read, _object_address
) -> bool:
    """Verify the measured build and current empty stack before retiring TPS.

    FFYL and Second Wind replace the game's camera stack without updating our
    Python ownership flag. Only an observed empty native stack authorizes
    forgetting the old TPS entry. A failed read must never authorize a pop.
    """
    base = int(_kernel32.GetModuleHandleW(None) or 0)
    if base < 0x10000:
        raise RuntimeError("BL4 module base unavailable")
    dos = _native_read(base, 64)
    if dos[:2] != b"MZ":
        raise RuntimeError("BL4 DOS header mismatch")
    pe_offset = struct.unpack_from("<I", dos, 60)[0]
    if not 64 <= pe_offset <= 0x100000:
        raise RuntimeError("BL4 PE header outside bounds")
    pe = _native_read(base + pe_offset, 0x60)
    if pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 24)[0] != 0x20B:
        raise RuntimeError("BL4 PE32+ header mismatch")
    build = (
        struct.unpack_from("<I", pe, 8)[0],
        struct.unpack_from("<I", pe, 80)[0],
        struct.unpack_from("<H", pe, 4)[0],
    )
    if build != REVIEWED_BUILD:
        raise RuntimeError(f"Camera stack layout unverified for build {build!r}")

    manager_address = _object_address(camera_manager)
    if manager_address < 0x10000:
        raise RuntimeError("Camera manager address unavailable")
    window = _native_read(manager_address + 0x39A8, 0xB0)
    array, count, capacity = struct.unpack_from("<Qii", window, 0x18)
    if not 0 <= count <= capacity <= 64 or (count and not array):
        raise RuntimeError("Camera stack header outside bounds")
    if window != _native_read(manager_address + 0x39A8, 0xB0):
        raise RuntimeError("Camera stack changed during verification")
    return count == 0


def _ffyl_camera_stack_has_single_tps(
    camera_manager: Any, *, _ffyl_camera_stack_empty, _native_read, _object_address
) -> bool:
    """Check the top live camera entry before restoring native auto mode."""
    # The empty-stack check also enforces the measured executable fingerprint.
    if _ffyl_camera_stack_empty(camera_manager):
        return False
    address = _object_address(camera_manager)
    window = _native_read(address + 0x39A8, 0xB0)
    array, count, capacity = struct.unpack_from("<Qii", window, 0x18)
    if count != 1 or not 1 <= capacity <= 64 or array < 0x10000:
        return False
    top_fname = _native_read(array, 8)
    if window != _native_read(address + 0x39A8, 0xB0):
        return False
    return top_fname == window[0x88:0x90]
