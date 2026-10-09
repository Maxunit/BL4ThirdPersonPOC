"""Correct only the verified FireBeam camera-prefix collision case.

The coordinator owns the matching recoil/origin/collision pair and restores
collision before origin on camera handoffs. The native stub accepts bounded hit
arrays and retains original results on ambiguous, penetrating or multiple fronts.
Resumed nonblocking entries may precede one confirmed front blocker in TPS ADS.
Cap a resumed prefix for a regular original hit at distance >40 using
min(projected source+20, regular distance-20). Confirmed fronts retain their bytes.
N is the narrow camera query; B is a broad radius-20 query beyond source+20:
N near/penetrating -> original; N free/B free -> remove only guarded start hits;
N free/B one blocker -> require the original front confirmed by B;
N far/B free -> original; N far/B one blocker -> confirmed original front or
the existing same-component normalized resumed hit, never later than N.
Different components require confirmation by nonzero component, distance and
impact within 0.25. Unconfirmed B-only fronts retain the original result.
Near followups require the initial-overlap component, distance <=20, valid time
and impact before prefix-20. General corner-geometry support remains unproven.
The first 64 decisions are retained; correction continues afterward. Native code
and control storage remain pinned. Hit processing is bounded to 32 entries; arrays, record stride and allocation
are expanded together. All geometry/identity guards retain their instructions.
"""

from .native_beam_rear_blocker import extend_recorder
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

TAG = "[BL4ThirdPersonPOC.BeamCollision]"
KEY = "_bl4_tps_beam_collision_owner"
EXPECTED = REVIEWED_BUILD
RVA = 0xA65AF1
ORIGINAL = bytes.fromhex("89c34c8b442468488b4c24784885c9")
ANCHOR_RVA = 0xA65B00
ANCHOR = bytes.fromhex("7454")
LIMIT = 64
HIT_CAPACITY = 32
RECORD_STRIDE = 32768
BASE_BUFFER_SIZE = 0x209000
AUXILIARY_SIZE = 512 + LIMIT * 0x2200
BUFFER_SIZE = BASE_BUFFER_SIZE + AUXILIARY_SIZE  # 64 retained records plus one overflow slot and header.
RETIRED = "_bl4_tps_beam_collision_retired"
COLLISION_IMPLEMENTATION = "guarded-prefix-collision"


NATIVE_TEMPLATE = bytes.fromhex(
    "9c50515241504151415241535355565741544155415641574881ec00010000f30f7f442470f30f7f8c2480000000f30f7f942490000000f3"
    "0f7f9c24a0000000f30f7fa424b0000000f30f7fac24c00000000fae9c24d000000048c78424d800000000000000488dac248001000048bf"
    "0177665544332211f048ff4708488b5d6848b803776655443322114839030f85dd0f0000f048ff471048b80277665544332211483983c800"
    "00000f85c10f000080bbea020000050f85b40f0000f68310030000100f85a70f000083bd68030000100f859a0f000083bda0000000020f85"
    "8d0f000081bda40000000000a0410f857d0f0000488b7570488b06483b83880300000f85690f0000488b4608483b83900300000f85580f00"
    "00488b4610483b83980300000f85470f0000488b83c8000000488b80b00100004885c00f84300f0000488b80c00300004885c00f84200f00"
    "00488b80002500004885c00f84100f0000488b0e483b88101900000f85000f0000488b4e08483b88181900000f85ef0e0000488b4e10483b"
    "88201900000f85de0e0000488b80483a00004885c00f84ce0e0000488b40104885c00f84c10e0000f6401c020f85b70e00008b8da8010000"
    "85c90f8ea90e000081f9000100000f8f9d0e00003b8dac0100000f8f910e0000488b95a00100004885d20f84810e00000fb682ad00000083"
    "e00383f80374104881c200010000ffc975e6e9620e000031c0ba01000000f00fb157180f85500e00004889bc24d8000000b801000000f048"
    "0fc1074989c44883f8407205b84000000048c1e00f488d7c074049ffc448c7070000000048c787c00000000000000048c787c80000000000"
    "000048c787000100000000000048c787080100000000000048c787100100000000000048c787180100000000000048c78738010000000000"
    "0048c787400100000000000048c787680100000000000048c787700100000000000048c787780100000000000048c7878001000000000000"
    "48c78788010000000000004c89a7f800000048895f08488b83c800000048894710488b45a048894718488b85a0000000488947200fb645f0"
    "894728488b85a801000048894730488b85a0010000488987d0000000488b838803000048894770488b839003000048894778488b83980300"
    "0048898780000000488b83a003000048898788000000488b83a803000048898790000000488b83b003000048898798000000488b83b80300"
    "00488987a0000000488b83c0030000488987a8000000488b83c8030000488987b0000000488b5570488b0248894740488b42084889474848"
    "8b421048894750488b9590000000488b0248894758488b420848894760488b4210488947684c8b85a00100004c8d8f000200008b8da80100"
    "0083f9207e05b920000000894f38c7473c01000000c1e105498b004989014983c0084983c108ffc975ee48c74424600000000048c7442468"
    "0000000048c74424500000000048c744245800000000c744245002000000c74424540000803f488b452048894424208b452889442428488d"
    "4424504889442430488b45384889442438488b45404889442440488b4f18488d5424604c8b45704c8b8d90000000ff15640c00000fb6c089"
    "472c488b442468488987c00000004c8b4424604c8987d80000008b4c246885c9785981f9000100007f513b4c246c7f4b85c9743d4d85c074"
    "4283f9207e05b920000000898fc8000000c787cc000000010000004c8d8f00220000c1e105498b004989014983c0084983c108ffc975eeeb"
    "0ac787cc00000001000000488b4c24604885c90f84460b0000ff15d90b0000c7873801000001000000660fefc0f20f108fa0000000f20f5c"
    "4f70f20f598f88000000f20f58c1f20f108fa8000000f20f5c4f78f20f598f90000000f20f58c1f20f108fb0000000f20f5c8f80000000f2"
    "0f598f98000000f20f58c1f20f5805850b0000660f2e057d0b00000f8ace0a00000f86c80a0000660f2e05710b00000f87ba0a0000f20f11"
    "8778010000837f3c010f85a80a00008b4f303b4f380f859c0a000085c90f8e940a000083f9200f8f8b0a00004c8d8700020000410fb680ad"
    "00000083e00383f801754ff3410f5a4808660fefd2660f2eca0f8a600a00000f825a0a0000f20f5c0dfb0a0000660f2e0df30a0000762366"
    "0f2ec8731d660f28c1f3410f5a5008f20f11978001000048c78788010000010000004981c000010000ffc97596f20f118718010000c78738"
    "01000002000000660fefd2f20f108f88000000f20f59c9f20f58d1f20f108f90000000f20f59c9f20f58d1f20f108f98000000f20f59c9f2"
    "0f58d1660f2e15850a00000f8ac60900000f82c0090000660f2e15790a00000f87b2090000c7873801000003000000660fefd2f20f104f58"
    "f20f5c4f40f20f598f88000000f20f58d1f20f104f60f20f5c4f48f20f598f90000000f20f58d1f20f104f68f20f5c4f50f20f598f980000"
    "00f20f58d1660f28d8f20f581dff090000660f2ed30f8a4c0900000f8646090000c787380100000400000083bfcc000000010f852f090000"
    "8b8fc000000085c90f882109000083f9200f8f180900003b8fc80000000f850c0900004c8d870022000031d285c9743b41f680ad00000001"
    "742641f680ad000000020f85e7080000f3410f5a4808660f2ecb0f8ad70800000f86d1080000ffc24981c000010000ffc975c589973c0100"
    "00c7873801000005000000f20f108f88000000f20f59c8f20f584f40f20f118c24e0000000f20f118f20010000f20f108f90000000f20f59"
    "c8f20f584f48f20f118c24e8000000f20f118f28010000f20f108f98000000f20f59c8f20f584f50f20f118c24f0000000f20f118f300100"
    "0048c74424600000000048c744246800000000c74424540000a041488b452048894424208b452889442428488d4424504889442430488b45"
    "384889442438488b45404889442440c7871401000001000000488b4f18488d5424604c8d8424e00000004c8b8d90000000ff15710800000f"
    "b6c0898710010000488b442468488987000100004c8b4424608b4c246885c9785981f9000100007f513b4c246c7f4b85c9743d4d85c07442"
    "83f9207e05b920000000898f08010000c7870c010000010000004c8d8f00420000c1e105498b004989014983c0084983c108ffc975eeeb0a"
    "c7870c0100000100000083bf3c010000000f8528020000c7874001000006000000837f2c000f853407000083bf10010000010f8407020000"
    "83bf10010000000f851a07000083bf0c010000010f850d0700008b8f0001000085c90f88ff06000083f9200f8ff60600003b8f080100000f"
    "85ea0600004c8d870042000085c9741941f680ad000000010f85d10600004981c000010000ffc975e78b4f3083f9010f8cba06000083f920"
    "0f8fb10600003b4f380f85a8060000837f3c010f859e0600004c8b85a00100004531ff41f680ad00000001750541ffc7eb4d41f680ad0000"
    "0002745d41837804000f857006000041837808000f8565060000498b4070483b47400f8557060000498b4078483b47480f8549060000498b"
    "8080000000483b47500f85380600004981c000010000ffc97599c7876801000001000000e977050000f3410f5a4008660fefc9660f2ec10f"
    "8a0a0600000f8604060000660f2e05b50600000f87f6050000f3410f5a4004660f2ec10f8ae60500000f86e0050000660f2e05b10600000f"
    "87d2050000660fefd2f2410f104028f20f5c4740f20f598788000000f20f58d0f2410f104030f20f5c4748f20f598790000000f20f58d0f2"
    "410f104038f20f5c4750f20f598798000000f20f58d0f20f108718010000f20f5c0532060000660f2ed00f8a6f0500000f8369050000498b"
    "80d80000004885c00f84590500004c8b8da0010000448b5730410fb691ad00000083e20383fa03750d493b81d80000000f84ccfeffff4981"
    "c10001000041ffca75d7e92005000083bf10010000010f8513050000c787400100000100000083bf0c010000010f85fc0400008b8f000100"
    "0083f9010f8ced04000083f9200f8fe40400003b8f080100000f85d80400004c8d87004200004531ed410fb680ad00000083e00383f8030f"
    "84ba04000083f801740b83f8020f85ac040000eb0c4d85ed0f85a10400004d89c54981c000010000ffc975c54d85ed0f848a040000c78740"
    "010000020000008b8fc00000004c8d87002200004531f685c97427410fb680ad00000083e00383f801750c4d85f60f85530400004d89c649"
    "81c000010000ffc975d9498b85d80000004885c00f843504000048c78760010000000000004d85f67517837f2c000f851b04000048c78770"
    "01000001000000eb18837f2c010f8504040000493b86d80000000f958760010000c787400100000300000048c78758010000000000008b4f"
    "3083f9200f8fd50300004c8b85a00100004531ff41f680ad00000001750841ffc7e90a010000f3410f5a4808660fefd2660f2eca0f8aa503"
    "00000f829f030000660f2e8f180100000f86b500000041f680ad000000020f85830300004883bf58010000000f8575030000498b80d80000"
    "00493b85d80000000f8561030000f3410f5a5508f20f589718010000f20f5cd1f20f59d2660f2e15240400000f8a3d0300000f8737030000"
    "660fefd2f2410f104828f2410f5c4d28f20f59c9f20f58d1f2410f104830f2410f5c4d30f20f59c9f20f58d1f2410f104838f2410f5c4d38"
    "f20f59c9f20f58d1660f2e15d00300000f8ae90200000f87e30200004c898758010000498b4070483b47400f85ce020000498b4078483b47"
    "480f85c0020000498b8080000000483b47500f85af0200004981c000010000ffc90f85d5feffff41ffc7443bbdac0100000f8f900200004d"
    "85f675104883bf58010000000f847d020000eb3480bf6001000000742b488b87580100004885c00f8462020000f30f5a4008f3410f5a4e08"
    "660f2ec10f8a4d0200000f8747020000c7874001000004000000660fefd2660fefdbf20f104f58f20f5c4f40f20f59c9f20f58d1f20f104f"
    "58f20f5c8f20010000f20f59c9f20f58d9f20f104f60f20f5c4f48f20f59c9f20f58d1f20f104f60f20f5c8f28010000f20f59c9f20f58d9"
    "f20f104f68f20f5c4f50f20f59c9f20f58d1f20f104f68f20f5c8f30010000f20f59c9f20f58d9f20f51d2f20f51dbf3410f5a4504660fef"
    "c9660f2ec10f8aa40100000f869e010000660f2e056f0200000f8790010000f20f59c3f20f588718010000f20f5ec2660f2e05510200000f"
    "8a720100000f876c010000f20f118748010000f3410f5a4508660f2ec10f8a540100000f824e010000f20f588718010000660f2ec20f873c"
    "010000f20f1187500100004d85f67410f3410f5a4e08660f2ec10f871f0100004c8b87580100004d85c075034d89e84c8d8f00630000b920"
    "000000498b004989014983c0084983c108ffc975ee4883bf58010000007541f20f5a8748010000f30f118704630000f20f5a8750010000f3"
    "0f118708630000488b474048898770630000488b474848898778630000488b475048898780630000488bb5a00100004889f2448b9da80100"
    "00f686ad0000000175244989f04989d1b920000000498b004989014983c0084983c108ffc975ee4881c2000100004881c60001000041ffcb"
    "75c783bf680100000174214c8d87006300004989d1b920000000498b004989014983c0084983c108ffc975ee4489bda801000083bf680100"
    "00000f9445f0c7874401000001000000c7874001000005000000488b8424d8000000f048ff4020488b4c24604885c97406ff159900000048"
    "8b87f8000000488907488b8424d80000004885c07407c74018000000000fae9424d0000000f30f6f442470f30f6f8c2480000000f30f6f94"
    "2490000000f30f6f9c24a0000000f30f6fa424b0000000f30f6fac24c00000004881c400010000415f415e415d415c5f5e5d5b415b415a41"
    "5941585a59589d89c34c8b442468488b4c24784885c9ff25140000000f1f4000057766554433221106776655443322110477665544332211"
    "000000000000344000000000000080401ea7e8482effef3f71ac8bdb6800f03f000000000000f03f000000000000b03f"
)


def recorder(buffer, weapon, receiver_table, resume, unused=None):
    """Relocate the immutable collision template for one validated native owner.

    The caller owns the control buffer, weapon, receiver-table and resume address.
    Verify template length/hash and each unique relocation sentinel before use.
    The retained nonblocking-guard edit is baseline behavior, not a new patch.
    """
    base = resume - (RVA + len(ORIGINAL))
    if (
        len(NATIVE_TEMPLATE) != 4416
        or hashlib.sha256(NATIVE_TEMPLATE).hexdigest()
        != "9f4ae61bef3a33d2a91317a6f84dfbdb4e100e19cc61c193caae58025954f3de"
    ):
        raise RuntimeError("Guarded native template fingerprint changed")
    blob = bytearray(NATIVE_TEMPLATE)
    if blob[0xBA2:0xBA5] != bytes.fromhex("83f802"):
        raise RuntimeError("Resumed-prefix nonblocking guard changed")
    blob[0xBA2:0xBA5] = bytes.fromhex("a80190")
    for tag, value in (
        (1, buffer),
        (2, weapon),
        (3, receiver_table),
        (4, resume),
        (5, base + 0x38F90E),
        (6, base + 0x20A8),
    ):
        needle = struct.pack("<Q", 0x1122334455667700 + tag)
        if blob.count(needle) != 1:
            raise RuntimeError("Relocation mismatch")
        blob = blob.replace(needle, struct.pack("<Q", value))
    return extend_recorder(bytes(blob), buffer + BASE_BUFFER_SIZE)


def hit_result(raw):
    """Decode a complete measured native hit-result record for diagnostics.

    Floats are at +4/+8/+160; vectors are doubles; flags at +173 and component
    weak handle at +216. Nonfinite values become text, not gameplay decisions.
    The caller must supply a complete record of the validated build/layout.
    """

    def finite(v):
        return v if math.isfinite(v) else str(v)

    out = {
        "raw_hex": raw.hex(),
        "bBlockingHit": bool(raw[173] & 1),
        "bStartPenetrating": bool(raw[173] & 2),
        "flags_ad": raw[173],
        "component_weak_handle_hex": raw[216:224].hex(),
    }
    for name, off in (("time", 4), ("Distance", 8), ("PenetrationDepth", 160)):
        out[name] = finite(struct.unpack_from("<f", raw, off)[0])
    for name, off in (
        ("Location", 16),
        ("ImpactPoint", 40),
        ("Normal", 64),
        ("ImpactNormal", 88),
        ("TraceStart", 112),
        ("TraceEnd", 136),
    ):
        out[name] = [finite(v) for v in struct.unpack_from("<3d", raw, off)]
    return out


def apply_or_restore():
    """Toggle the owned collision detour after executable and origin verification.

    The coordinator is responsible for local camera eligibility and release
    ordering. An existing registry owner triggers restoration; mismatched bytes
    refuse writes. Return diagnostic status; refusal is not cleanup success.
    """
    report = {
        "version": "guarded-prefix-collision",
        "action": "REFUSED",
        "verified": False,
        "errors": [],
        "sdk_hooks": 0,
        "camera_flag_writes": 0,
        "native_patches": 0,
        "replacements_applied": 0,
        "scope": "Guarded camera-prefix correction with native broad20 continuation; owned origin required",
        "limit": LIMIT,
        "records": [],
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
            report["replacements_applied"] = qword(state.buffer + 32)
            preserved = 0
            for i in range(min(report["observed_calls"], LIMIT)):
                raw = read(state.buffer + 64 + i * RECORD_STRIDE, 400)
                if (
                    struct.unpack_from("<Q", raw)[0] == i + 1
                    and struct.unpack_from("<II", raw, 320) == (5, 1)
                    and struct.unpack_from("<Q", raw, 344)[0] != 0
                ):
                    preserved += 1
            report["ads_overlap_front_preserved_first64"] = preserved
            report["all_callsite_visits"] = qword(state.buffer + 8)
            report["receiver_class_visits"] = qword(state.buffer + 16)
            report["record_note"] = (
                "guarded-prefix-collision processes complete lists up to 32; allows regular nonblocking resumed entries before a confirmed front. First 64 eligible decisions are retained; later decisions are counted. Original confirmed fronts remain byte-identical."
            )
            report["dropped_by_limit"] = max(0, report["observed_calls"] - LIMIT)
            report["action"] = "RESTORED"
            del sys.modules[KEY]
            report["capture_context"] = state.context
            origin_owner = sys.modules.get("_bl4_tps_beam_origin_owner")
            report["origin_still_active_at_stop"] = bool(
                origin_owner is not None
                and origin_owner.base == base
                and read(base + 0xA640F0, len(origin_owner.patch)) == origin_owner.patch
            )
            report["native_patches_scope"] = (
                "Collision only; origin is a separate active patch when reported above"
            )

        else:
            if (
                hashlib.sha256(read(base + 0xA64FEE, 0x1800)).hexdigest()
                != "1f16683d17e3af0f79a58677e24108215a36170a5d253a4e1f584ab5bc083c2d"
            ):
                raise RuntimeError("Collision query code fingerprint changed")
            if read(address, len(ORIGINAL)) != ORIGINAL:
                raise RuntimeError("Capture site differs from original bytes")
            if read(base + ANCHOR_RVA, len(ANCHOR)) != ANCHOR:
                raise RuntimeError("Measured collision callsite changed")
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
                raise RuntimeError(
                    "guarded-prefix-collision requires normal TPS, no ADS"
                )
            origin_owner = sys.modules.get("_bl4_tps_beam_origin_owner")
            if origin_owner is None or origin_owner.base != base:
                raise RuntimeError(
                    "Activate owned-firebeam-origin first; this measurement requires its origin override"
                )
            if read(base + 0xA640F0, len(origin_owner.patch)) != origin_owner.patch:
                raise RuntimeError(
                    "owned-firebeam-origin patch is not active as expected"
                )
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
            if getattr(origin_owner, "fire", None) != fire:
                raise RuntimeError(
                    "owned-firebeam-origin was armed for a different weapon mode; restore and re-arm"
                )
            callee = base + 0x38F90E
            if not any(lo <= callee and callee + 0x800 <= hi for lo, hi in executable):
                raise RuntimeError(
                    "Collision callee code window outside executable image"
                )
            if (
                hashlib.sha256(read(callee, 0x800)).hexdigest()
                != "a2f4f024253abec60d39d686564b56f369b16fda241d16ea8d134a0397b6f5e3"
            ):
                raise RuntimeError("Native query helper code fingerprint changed")
            if not any(lo <= base + 0x20A8 < hi for lo, hi in executable):
                raise RuntimeError("Native cleanup outside executable image")
            report["collision_callee_code"] = {
                "rva": "0x38f90e",
                "hex": read(callee, 0x800).hex(),
            }
            report["before"]["origin_active_verified"] = True
            report["before"]["user_reported_camera_offset"] = [0, 75, 10]
            report["before"][
                "offset_note"
            ] = "User-provided setting, not independently read by this helper"
            state = types.ModuleType(KEY)
            state.base = base
            state.context = report["before"]
            state.buffer = int(k.VirtualAlloc(None, BUFFER_SIZE, 0x3000, 0x04) or 0)
            state.code = int(k.VirtualAlloc(None, 0x2000, 0x3000, 0x04) or 0)
            if not state.buffer or not state.code:
                raise OSError("Recorder allocation failed; no game code changed")
            blob = recorder(state.buffer, wa, base + 0xB7931C0, address + len(ORIGINAL))
            if len(blob) > 0x2000:
                raise RuntimeError("Recorder exceeds allocated code page")
            ctypes.memmove(state.code, blob, len(blob))
            old = ctypes.c_ulong()
            if not k.VirtualProtect(state.code, 0x2000, 0x20, ctypes.byref(old)):
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
            report.update(
                action="TPS_CAPPED_PREFIX_ON", verified=True, native_patches=1
            )
        report["collision_processing_capacity"] = HIT_CAPACITY
        report["bytes"] = read(address, len(ORIGINAL)).hex()
    except Exception as exc:
        report["errors"].append(str(exc))
        report["recovery_state_present"] = KEY in sys.modules
    if report["errors"]:
        logging.warning(f'{TAG} action={report["action"]} error={report["errors"]}')

    return report
