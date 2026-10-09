"""Maintain the owned TPS camera during GroundSlamExit.

Resolve the selected definition and create a private copy for the live runtime.
InitialRotation bypass and POV writes are scoped to that runtime/definition;
serial-checked owner identity blocks writes after invalidation. Shared camera
entry consumers preserve the original blend. Restore POV/socket/definition
ownership before retiring pinned code, or retain fault state for explicit cleanup.
The original source marks collision behavior unverified; this refactor adds no
native collision proof and does not resolve that gameplay uncertainty.
"""

import ctypes, hashlib, json, struct, sys, time, types, math
from .build_gate import REVIEWED_BUILD
from . import camera_hook_chain as chain
from unrealsdk import find_object
from unrealsdk.unreal import WeakPointer
from pathlib import Path
from datetime import datetime, timezone
from unrealsdk import logging
from unrealsdk.hooks import Type, add_hook, has_hook, remove_hook

KEY = "_bl4tps_ground_slam_beta_owner"
TAG = "[BL4ThirdPersonPOC.GroundSlam]"
TARGET_RVA = 0x1449676
ORIGINAL = b"AWAVAUATVWUSH\x81\xec\x18\x01\x00\x00"
ENTRY_SHA256 = "5a349bce422f8fa507b2fbae0dc899bd014e89484e416b7e7e66400c07fa5163"
PREFIX = (
    b'\x9cPARASI\xba""""""""I9\n\x0f'
    b"\x85?\x01\x00\x00A\x83z\x08\x01\x0f\x854\x01\x00\x00I\xc7\xc3\x01"
    b"\x00\x00\x00\xf0M\x0f\xc1Z\x10I\x81\xfb\x80\x00\x00\x00\x0f\x83\x1a\x01"
    b"\x00\x00I\xc1\xe3\x07O\x8d\\\x1a\x18I\x89\x13H\x8b\x810:\x00"
    b"\x00I\x89C\x08H\x8b\x81H:\x00\x00I\x89C\x18fH\x0f~"
    b"\xd0I\x89C M\x89K(Hc\x81\xc89\x00\x00I\x89C0"
    b"H\x85\xc0t)H\x83\xf8@w,;\x81\xcc9\x00\x00w$H"
    b"k\xc0(L\x8b\x91\xc09\x00\x00I\x81\xfa\x00\x00\x01\x00r\x10I"
    b"\x8bD\x02\xd8\xeb\x0bH\x8b\x81\xa89\x00\x00\xeb\x021\xc0I\x89C"
    b"\x10I\xc7C@\x01\x00\x00\x00I\xc7CP\xff\xff\xff\xffI\xc7C"
    b"h\xff\xff\xff\xffH\x8b\x81\xd89\x00\x00H\x85\xc0t\x0b\x0f\xb6\x80"
    b"L\x01\x00\x00I\x89CpI\x8bC\x18H\x85\xc0t\x15H\x8b@"
    b"\x10I\x89CHH\x85\xc0t\x08\x0f\xb6@\x1cI\x89CPI\x8b"
    b"C0H\x85\xc0tEH\x83\xf8@w?;\x81\xcc9\x00\x00w"
    b"7Hk\xc0(L\x8b\x91\xc09\x00\x00I\x81\xfa\x00\x00\x01\x00r"
    b"#I\x8bD\x02\xf0I\x89CXH\x85\xc0t\x15H\x8b@\x10I"
    b"\x89C`H\x85\xc0t\x08\x0f\xb6@\x1cI\x89ChI\xc7C8"
    b"\x01\x00\x00\x00A[AZX\x9d"
)
PREFIX_SHA256 = "f11b19ea487346e12689348d312d942e7e9da0bbce713a77e93a204c29ff558f"
APPLY_RVA = 0xE5EAA8
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

MODIFY_PREFIX = bytes.fromhex(
    "9c504152415349ba333333333333333349390a0f859700000041837a08010f858c0000004d8b5a284d85db74344c3999483a0000756a4d391b7565498b422049394310755b488b024c39d87414498b42184989431049c742280000000049ff42384c8b1a4d85db74474d391b7542488b42084885c07439493943087533498b421849394310752949837a28007512498b4220498943104d895a2849ff4230eb1041c742400100000041c7420800000000415b415a589d"
)
MODIFY_SHA256 = "7b83cf23887b48255e8554b0256b5d770de2f9c21d087d629e5c512e83047edb"
PREPARE_PREFIX = bytes.fromhex(
    "9c50515241504151415241534881ec88000000f30f7f442420f30f7f4c2430f30f7f542440f30f7f5c2450f30f7f642460f30f7f6c247048b87777777777777777ffd0f30f6f442420f30f6f4c2430f30f6f542440f30f6f5c2450f30f6f642460f30f6f6c24704881c488000000415b415a415941585a59589d"
)

POV_RVA = 6986766
POV_ORIGINAL = b"AWAVATVWSH\x81\xec\x98\x02\x00\x00"
POV_SHA256 = "2c714356521de6e24f04769f08312b96e571b60fa9da2bbdcde0a3d03bba0294"
POV_PREFIX = (
    b"SVWATH\x83\xec(H\x89\xcbH\x89\xd6L\x89\xc7H\xb8"
    b"DDDDDDDD\xff\xd0\x9cPARASI\xbcUU"
    b"UUUUUUI9\x1c$\x0f\x85\xaa\x01\x00\x00A\x83|$"
    b"\x08\x01\x0f\x85\x9e\x01\x00\x00I\xffD$`H\x8b\x06I\x89D$"
    b"HI\xba\x00\x00\x00\x00\x00\x00\xf0\x7fL!\xd0L9\xd0\x0f\x84v"
    b"\x01\x00\x00H\x8bF\x08I\x89D$PI\xba\x00\x00\x00\x00\x00\x00"
    b"\xf0\x7fL!\xd0L9\xd0\x0f\x84W\x01\x00\x00H\x8bF\x10I\x89"
    b"D$XI\xba\x00\x00\x00\x00\x00\x00\xf0\x7fL!\xd0L9\xd0\x0f"
    b"\x848\x01\x00\x00M\x8b\x9c$\x98\x00\x00\x00I\x81\xfb\x00\x04\x00\x00"
    b"\x0f\x83(\x01\x00\x00I\xff\x84$\x98\x00\x00\x00Mi\xdb\xd0\x00\x00"
    b"\x00O\x8d\x9c\x1c\x00\x01\x00\x00A\x8bD$\x0cI\x89\x03H\x8b\x06"
    b"I\x89C\x08H\x8b\x07I\x89C H\x8bF\x08I\x89C\x10H"
    b"\x8bG\x08I\x89C(H\x8bF\x10I\x89C\x18H\x8bG\x10I"
    b"\x89C0H\x8bCHI\x89C8H\x8bCPI\x89C@H"
    b"\x8bCXI\x89CHH\x8b\x83\xa0\x00\x00\x00I\x89CPH\x8b"
    b"\x83\xa8\x00\x00\x00I\x89CXH\x8b\x83\xb0\x00\x00\x00I\x89C`"
    b"H\x8b\x83\xd8\x00\x00\x00I\x89ChH\x8b\x83\xe0\x00\x00\x00I\x89"
    b"CpH\x8b\x83\xe8\x00\x00\x00I\x89CxI\x8b\x84$\xa0\x00\x00"
    b"\x00L\x8b\x90H:\x00\x00M\x89\x93\x80\x00\x00\x00L\x8b\x900:"
    b"\x00\x00M\x89\x93\x88\x00\x00\x00H\x8bC0I\x89\x83\x98\x00\x00\x00"
    b"H\x8bC8I\x89\x83\xa0\x00\x00\x00H\x8bC@I\x89\x83\xa8\x00"
    b"\x00\x00H\x8b\x83\xc0\x00\x00\x00I\x89\x83\xb0\x00\x00\x00H\x8b\x83\xc8"
    b"\x00\x00\x00I\x89\x83\xb8\x00\x00\x00H\x8b\x83\xd0\x00\x00\x00I\x89\x83"
    b"\xc0\x00\x00\x00I\xc7\x83\x90\x00\x00\x00\x01\x00\x00\x00\xeb\x05I\xffD"
    b"$pA[AZX\x9dH\x83\xc4(A\\_^[\xc3"
)
POV_PREFIX_SHA256 = "65a06ddf0bbbfa04b9cd64767ece410625b38d7e8b44fbb9eb6838004ebe248a"

SOCKET_APPLY_PREFIX = (
    b"\x9cPAPAQARASATAUI\xba3333"
    b"3333I9\n\x0f\x85-\x01\x00\x00A\x83z\x08\x01\x0f\x85"
    b'"\x01\x00\x00M\x8bZ(M\x85\xdb\x0f\x84\x15\x01\x00\x00I\x8bB'
    b" I9C\x10\x0f\x85\xf7\x00\x00\x00L9\x1a\x0f\x85\xfe\x00\x00\x00"
    b"M\x8bC0A\x83{8\x07\x0f\x85\xdf\x00\x00\x00A\x83{<\x07"
    b"\x0f\x8c\xd4\x00\x00\x00A\x83{<@\x0f\x87\xc9\x00\x00\x00M\x85\xc0"
    b"\x0f\x84\xc0\x00\x00\x00A\xb9\x07\x00\x00\x00E1\xe4E1\xedM\x8b"
    b"\x18M\x85\xdb\x0f\x84\xa8\x00\x00\x00I\x83x\x08\x00\x0f\x84\x9d\x00\x00"
    b"\x00I\x8bBpI9\x03u\x10M\x85\xe4\x0f\x85\x8b\x00\x00\x00M"
    b"\x89\xdcM\x8bh\x08I\x83\xc0\x10A\xff\xc9u\xc7M\x85\xe4tv"
    b"A\x81|$\x1c2\x02\x00\x00ukI\x83|$ \x00ucI"
    b"\x83zH\x00ulA\x80|$\x18\x02uTM\x89bHM\x89"
    b"jPI\xc7BX\x02\x00\x00\x00I\x8b\x04$I\x89BxI\x8b"
    b"D$\x08I\x89\x82\x80\x00\x00\x00I\x8bD$\x10I\x89\x82\x88\x00"
    b"\x00\x00I\x8bD$\x18I\x89\x82\x90\x00\x00\x00I\x8bD$ I"
    b"\x89\x82\x98\x00\x00\x00A\xc6D$\x18\x00I\xffB`\xeb\x10A\xc7"
    b"B@\x02\x00\x00\x00A\xc7B\x08\x00\x00\x00\x00A]A\\A["
    b"AZAYAXX\x9d"
)
SOCKET_APPLY_PREFIX_SHA256 = (
    "8712d2234580b19f446aae7d71255911e930f782fdd35ea3b37ec8119c91f92e"
)
SOCKET_RESTORE_PREFIX = (
    b"\x9cPAPAQARASI\xba33333333"
    b"I9\n\x0f\x85\xde\x00\x00\x00A\x83z\x08\x01\x0f\x85\xd3\x00\x00\x00"
    b"I\x83zH\x00\x0f\x84\xc8\x00\x00\x00M\x8bZ(L9\x99H:"
    b"\x00\x00\x0f\x85\xa7\x00\x00\x00L9\x1a\x0f\x84\xae\x00\x00\x00M\x8bC"
    b"0A\x83{8\x07\x0f\x85\x8f\x00\x00\x00A\x83{<\x07\x0f\x8c\x84"
    b"\x00\x00\x00A\x83{<@w}M\x85\xc0txA\xb9\x07\x00\x00"
    b"\x00I\x8bBHI9\x00u`I\x8bBPI9@\x08u_"
    b"M\x8bZHI\x8bBxI9\x03uRI\x8b\x82\x80\x00\x00\x00"
    b"I9C\x08uEI\x8b\x82\x88\x00\x00\x00I9C\x10u8I"
    b"\x8b\x82\x90\x00\x00\x00$\xfdI9C\x18u)I\x8b\x82\x98\x00\x00"
    b"\x00I9C u\x1cA\xc6C\x18\x02I\xc7BH\x00\x00\x00\x00"
    b"I\xffBh\xeb\x19I\x83\xc0\x10A\xff\xc9u\x8eA\xc7B@\x03"
    b"\x00\x00\x00A\xc7B\x08\x00\x00\x00\x00A[AZAYAXX"
    b"\x9d"
)
SOCKET_RESTORE_PREFIX_SHA256 = (
    "220a329b7f8464982c5b8a94422d01426ac5bc26e0d1a4ef25facf2e3292c8af"
)
OFFSET_PREFIX = (
    b"\x9cPARASATI\xba33333333I\xbc"
    b"UUUUUUUUA\x83z\x08\x01\x0f\x85d\x01\x00\x00I"
    b"9\x1c$\x0f\x85Z\x01\x00\x00M\x8b\x1aM\x8b\x9bH:\x00\x00I"
    b"\x83z(\x00\x0f\x84E\x01\x00\x00M9Z(\x0f\x85;\x01\x00\x00"
    b"I\x8bB I9C\x10\x0f\x85\x1d\x01\x00\x00A\x83\xba\xb8\x00\x00"
    b"\x00\x01\x0f\x84\xdc\x00\x00\x00M\x8b\x9c$\x98\x00\x00\x00M\x85\xdb\x0f"
    b"\x84\xfe\x00\x00\x00I\x81\xfb\x00\x04\x00\x00\x0f\x83\xf1\x00\x00\x00I\xff"
    b"\xcbMi\xdb\xd0\x00\x00\x00O\x8d\x9c\x1c\x00\x01\x00\x00I\x83\xbb\x90"
    b"\x00\x00\x00\x01\x0f\x85\xd1\x00\x00\x00I\x8b\x82\xd0\x00\x00\x00I9\x83"
    b"\x88\x00\x00\x00\x0f\x85\xbd\x00\x00\x00I\x8b\x82\xd8\x00\x00\x00I9\x83"
    b"\x80\x00\x00\x00\x0f\x85\xa9\x00\x00\x00I\x8b\x83\xb0\x00\x00\x00I\x89\x82"
    b"\xa0\x00\x00\x00I\x8b\x83\xb8\x00\x00\x00I\x89\x82\xa8\x00\x00\x00I\x8b"
    b"\x83\xc0\x00\x00\x00I\x89\x82\xb0\x00\x00\x00I\xbc\xff\xff\xff\xff\xff\xff"
    b"\xff\x7fI\xbb\x00\x00\x00\x00\x00\x00\x80@I\x8b\x82\xa0\x00\x00\x00L"
    b"!\xe0L9\xd8w\\I\x8b\x82\xa8\x00\x00\x00L!\xe0L9\xd8"
    b"wMI\x8b\x82\xb0\x00\x00\x00L!\xe0L9\xd8w>A\xc7\x82"
    b"\xb8\x00\x00\x00\x01\x00\x00\x00I\x8b\x82\xa0\x00\x00\x00H\x89\x83\xc0\x00"
    b"\x00\x00I\x8b\x82\xa8\x00\x00\x00H\x89\x83\xc8\x00\x00\x00I\x8b\x82\xb0"
    b"\x00\x00\x00H\x89\x83\xd0\x00\x00\x00I\xff\x82\xc0\x00\x00\x00\xeb\x10A"
    b"\xc7B@\x04\x00\x00\x00A\xc7B\x08\x00\x00\x00\x00A\\A[A"
    b"ZX\x9d"
)
OFFSET_PREFIX_SHA256 = (
    "1f9f3cc3a0aaaacf18ff4f612d7c37a93b97ea7af867f94df5b2106f1cdabffb"
)
ROTATION_RVA = 0x12E6384
ROTATION_ORIGINAL = b"AVVWSH\x81\xec\x98\x01\x00\x00fD\x0f)\xbc$\x80\x01\x00\x00"
ROTATION_SHA256 = "ea9f1dc86913486ad911ec5cda0e35469f7319403b9c1f26504a79b9f2a456d9"
ROTATION_GUARD = (
    b'\x9cPARASI\xba""""""""A\x83:\x01'
    b"ukI\xbb33333333A\x83{\x08\x01uZH"
    b"\x85\xc9tUM\x85\xc0tPH\x8b\x01I\xbaDDDDDD"
    b"DDL9\xd0u>I\x8b\x03L9\x80\xd89\x00\x00u2H"
    b"\x8b\x80H:\x00\x00H\x85\xc0t&I9C(u H\x8b@"
    b'\x10I9C u\x16I\xba""""""""\xf0I\xff'
    b"B\x08A[AZX\x9d\xc3A[AZX\x9d\xff%\x00\x00\x00"
    b"\x00UUUUUUUU"
)
ROTATION_GUARD_SHA256 = (
    "caf3b96cea7a0cf75bbbbb7a80cfec0b596abedbddf0b7e7316558a60adde814"
)


def owner_matches(state, current):
    """Check serial-backed UObject lifetime before any native owner read."""
    refs = getattr(state, "owner_refs", ())
    identity = getattr(state, "owner_identity", ())
    if len(refs) != 3 or len(identity) != 3:
        raise RuntimeError("Ground Slam owner lifetime metadata missing")
    owners = tuple(ref() for ref in refs)
    if any(owner is None for owner in owners):
        return False
    if tuple(int(owner._get_address()) for owner in owners) != identity:
        raise RuntimeError("Ground Slam weak owner identity differs")
    return (
        all(value is not None for value in current)
        and tuple(int(value._get_address()) for value in current) == identity
    )


def run():
    """Arm or stop the owned GroundSlamExit camera runtime.

    The owner pins its private definition and callback controls before native
    publishing. Restore owned fields before unlinking consumers; retain any
    uncertain runtime ownership instead of freeing a possibly referenced copy.
    """
    slam_definition = None
    old = sys.modules.get(KEY)
    if old is not None:
        old.stop("manual")
        return
    report = {
        "version": "owned-ground-slam-camera",
        "events": [],
        "sdk_camera_rows": [],
        "errors": [],
        "hook_removal_errors": [],
        "native_patches": 0,
        "game_writes": 0,
        "private_runtime_definition": True,
        "diagnostic_buffer_only": False,
        "initial_rotation_bypass": "Exact SDK state + InitialRotation vtable + active owned Ground Slam runtime + private TPS definition. Other calls retain original processing.",
        "note": "Stage 1 records transition entry and cached stack candidate. Stage 2 records the runtime argument actually handed to apply_runtime_mode, before application. Definition bits 2/4 mean first-person/viewmodel. Private definition changes only flags 0x27 to 0x21 before application; original blend retained. Rotation-only socket disabled and last native TPS composed offset applied before GetPOV; collision unverified. No post-return or rendered-frame proof.",
    }
    state = types.ModuleType(KEY)
    state.active = True
    state.native_hooks = []
    state.hooks = []
    state.mod = None
    control = ctypes.create_string_buffer(24 + 128 * 128)
    state.control = control
    modify = ctypes.create_string_buffer(256)
    state.modify = modify
    state.clone = None
    state.original_definition = None
    state.position_callback = None
    state.position_busy = False
    state.position_original = None
    state.position_written = None
    state.owner_invalidated = False
    view = ctypes.create_string_buffer(256 + 1024 * 208)
    state.view = view
    rotation_gate = ctypes.create_string_buffer(16)
    state.rotation_gate = rotation_gate
    struct.pack_into("<I", rotation_gate, 0, 1)
    behavior_samples = set()
    seen_slam = False
    stable_tail = 0
    started = time.perf_counter()
    frames = 0
    last = None

    def save(reason):
        report["reason"] = reason
        state.report = report
        logging.info(
            f'{TAG} COMPLETE reason={reason} errors={len(report["errors"])} cleanup_complete={report.get("cleanup_complete",False)} initial_rotation_skipped={report.get("initial_rotation_skipped_calls",0)} applies={report.get('definition_applications',0)} restores={report.get('definition_restorations',0)}'
        )
        if report["errors"] or not report.get("cleanup_complete", False):
            if state.mod is not None:
                state.mod._ground_slam_beta_fault = True
            logging.error(
                f'{TAG} restoration details: {report["errors"]}; hook errors={report["hook_removal_errors"]}'
            )

    def stop(reason):
        state.active = False
        struct.pack_into("<I", rotation_gate, 0, 0)
        report["initial_rotation_skipped_calls"] = struct.unpack_from(
            "<Q", rotation_gate.raw, 8
        )[0]
        struct.pack_into("<I", view, 8, 0)
        if (
            state.position_written is not None
            and struct.unpack_from("<Q", modify.raw, 40)[0]
        ):
            try:
                if state.owner_refs[2]() is None:
                    raise RuntimeError("POV manager destroyed; no stale read allowed")
                manager = report["identity"][2]
                live = struct.unpack("<Q", state.mod._native_read(manager + 0x3A48, 8))[
                    0
                ]
                if live != struct.unpack_from("<Q", modify.raw, 40)[0]:
                    raise RuntimeError("POV release owner differs")
                state_pointer = struct.unpack(
                    "<Q", state.mod._native_read(manager + 0x39D8, 8)
                )[0]
                if (
                    state.mod._native_read(state_pointer + 0x30, 24)
                    != state.position_written
                ):
                    raise RuntimeError("POV changed after last owned write")
                count = ctypes.c_size_t()
                if (
                    not state.kernel.WriteProcessMemory(
                        state.process,
                        state_pointer + 0x30,
                        state.position_original,
                        24,
                        ctypes.byref(count),
                    )
                    or count.value != 24
                ):
                    raise RuntimeError("POV release failed")
                if (
                    state.mod._native_read(state_pointer + 0x30, 24)
                    != state.position_original
                ):
                    raise RuntimeError("POV release verification failed")
                report["manual_pov_release"] = True
            except Exception as exc:
                report["errors"].append("POV release: " + repr(exc))
        struct.pack_into("<I", control, 8, 0)
        struct.pack_into("<I", modify, 8, 0)
        saved_socket = struct.unpack_from("<Q", modify.raw, 72)[0]
        if saved_socket:
            try:
                if state.owner_refs[2]() is None:
                    raise RuntimeError(
                        "Socket manager destroyed; no stale read allowed"
                    )
                live = struct.unpack(
                    "<Q", state.mod._native_read(report["identity"][2] + 0x3A48, 8)
                )[0]
                saved_runtime = struct.unpack_from("<Q", modify.raw, 40)[0]
                if live != saved_runtime:
                    raise RuntimeError("Socket runtime no longer verified current")
                array, n, cap = struct.unpack(
                    "<Qii", state.mod._native_read(live + 0x30, 16)
                )
                if n != 7 or not n <= cap <= 64:
                    raise RuntimeError("Socket list bounds differ")
                pairs = state.mod._native_read(array, n * 16)
                owner = struct.unpack_from("<Q", modify.raw, 80)[0]
                if (
                    sum(
                        struct.unpack_from("<QQ", pairs, i * 16)
                        == (saved_socket, owner)
                        for i in range(n)
                    )
                    != 1
                ):
                    raise RuntimeError("Socket owner differs")
                original = modify.raw[120:160]
                expected = original[:24] + bytes([original[24] & ~2]) + original[25:]
                if state.mod._native_read(saved_socket, 40) != expected:
                    raise RuntimeError("Socket content differs")
                count = ctypes.c_size_t()
                payload = bytes([original[24]])
                if (
                    not state.kernel.WriteProcessMemory(
                        state.process,
                        saved_socket + 24,
                        payload,
                        1,
                        ctypes.byref(count),
                    )
                    or count.value != 1
                ):
                    raise RuntimeError("Socket restore failed")
                if state.mod._native_read(saved_socket, 40) != original:
                    raise RuntimeError("Socket restore verification failed")
                struct.pack_into("<Q", modify, 72, 0)
                struct.pack_into(
                    "<Q", modify, 104, struct.unpack_from("<Q", modify.raw, 104)[0] + 1
                )
            except Exception as exc:
                report["errors"].append("Socket restore: " + repr(exc))
        report["socket_applies"] = struct.unpack_from("<Q", modify.raw, 96)[0]
        report["socket_restores"] = struct.unpack_from("<Q", modify.raw, 104)[0]
        report["socket_restored"] = struct.unpack_from("<Q", modify.raw, 72)[0] == 0
        report["offset_writes"] = struct.unpack_from("<Q", modify.raw, 192)[0]
        report["native_tps_offset_target"] = (
            list(struct.unpack_from("<3d", modify.raw, 160))
            if struct.unpack_from("<I", modify.raw, 184)[0]
            else None
        )
        saved_runtime = struct.unpack_from("<Q", modify.raw, 40)[0]
        if saved_runtime:
            try:
                values = state.mod._get_runtime()
                if (
                    any(x is None for x in values)
                    or tuple(int(x._get_address()) for x in values)
                    != report["identity"]
                ):
                    raise RuntimeError(
                        "Cannot restore owned runtime after owner change; private copy retained"
                    )
                live = struct.unpack(
                    "<Q", state.mod._native_read(report["identity"][2] + 0x3A48, 8)
                )[0]
                if (
                    live != saved_runtime
                    or struct.unpack("<Q", state.mod._native_read(live, 8))[0] != live
                ):
                    raise RuntimeError(
                        "Owned runtime no longer verified current; copy retained"
                    )
                # A manual stop during Slam releases our temporary composed state offset.
                if struct.unpack_from("<I", modify.raw, 184)[0]:
                    state_address = struct.unpack(
                        "<Q", state.mod._native_read(report["identity"][2] + 0x39D8, 8)
                    )[0]
                    payload = bytes(24)
                    count = ctypes.c_size_t()
                    if (
                        not state.kernel.WriteProcessMemory(
                            state.process,
                            state_address + 0xC0,
                            payload,
                            24,
                            ctypes.byref(count),
                        )
                        or count.value != 24
                    ):
                        raise RuntimeError("State offset release failed")
                    if state.mod._native_read(state_address + 0xC0, 24) != payload:
                        raise RuntimeError("State offset release not verified")
                    report["manual_offset_release"] = True
                slot = live + 16
                clone_address = ctypes.addressof(state.clone)
                if (
                    struct.unpack("<Q", state.mod._native_read(slot, 8))[0]
                    != clone_address
                ):
                    raise RuntimeError("Owned definition ownership changed")
                payload = struct.pack("<Q", slam_definition)
                count = ctypes.c_size_t()
                if (
                    not state.kernel.WriteProcessMemory(
                        state.process, slot, payload, 8, ctypes.byref(count)
                    )
                    or count.value != 8
                ):
                    raise RuntimeError("Runtime definition restore write failed")
                if state.mod._native_read(slot, 8) != payload:
                    raise RuntimeError("Runtime restore verification failed")
                struct.pack_into("<Q", modify, 40, 0)
                struct.pack_into(
                    "<Q", modify, 56, struct.unpack_from("<Q", modify.raw, 56)[0] + 1
                )
            except Exception as exc:
                report["errors"].append("Runtime restore: " + repr(exc))
        report["definition_applications"] = struct.unpack_from("<Q", modify.raw, 48)[0]
        report["definition_restorations"] = struct.unpack_from("<Q", modify.raw, 56)[0]
        report["definition_fault"] = bool(struct.unpack_from("<I", modify.raw, 64)[0])
        report["game_writes"] = (
            report["definition_applications"]
            + report["definition_restorations"]
            + report["socket_applies"]
            + report["socket_restores"]
            + report["offset_writes"]
            + int(report.get("manual_offset_release", False))
            + report.get("position_writes", 0)
            + int(report.get("manual_pov_release", False))
            + report.get("handoff_offset_writes", 0)
        )
        report["definition_runtime_restored"] = (
            struct.unpack_from("<Q", modify.raw, 40)[0] == 0
        )
        for hook in list(reversed(state.native_hooks)):
            try:
                chain.restore(state.mod, hook)
                if (
                    chain.original_read(
                        state.mod, hook["target"], len(hook["original"])
                    )
                    != hook["original"]
                ):
                    raise RuntimeError("Post-unhook verification failed")
                chain.retire(state.mod, hook)
                state.native_hooks.remove(hook)
            except Exception as exc:
                report["errors"].append("Native restore: " + repr(exc))
        report["native_patches"] = len(state.native_hooks)
        report["restore_verified"] = not state.native_hooks
        for path, kind, name in list(state.hooks):
            try:
                if has_hook(path, kind, name):
                    remove_hook(path, kind, name)
                if has_hook(path, kind, name):
                    raise RuntimeError("Hook remains installed")
                state.hooks.remove((path, kind, name))
            except Exception as exc:
                report["hook_removal_errors"].append(repr(exc))
        raw = control.raw
        count = struct.unpack_from("<Q", raw, 16)[0]
        report["native_calls"] = count
        report["truncated"] = count > 128
        report["native_rows"] = []
        report["cleanup_complete"] = (
            not state.native_hooks
            and not state.hooks
            and report["definition_runtime_restored"]
            and report["socket_restored"]
        )
        view_raw = view.raw
        view_count = struct.unpack_from("<Q", view_raw, 152)[0]
        report["native_pov_calls"] = struct.unpack_from("<Q", view_raw, 96)[0]
        report["native_pov_count"] = view_count
        report["native_pov_rows"] = []
        if (
            reason == "slam_returned_stable_tps_with_tail"
            and not report["definition_applications"]
        ):
            logging.warning(
                f"{TAG} SLAM_NOT_APPLIED preparation_seen={slam_definition is not None}"
            )
        save(reason)
        if report["cleanup_complete"]:
            sys.modules.pop(KEY, None)

    state.stop = stop
    sys.modules[KEY] = state
    try:
        mods = [
            m
            for n, m in list(sys.modules.items())
            if m is not None
            and n.endswith("BL4ThirdPersonPOC")
            and callable(getattr(m, "_get_runtime", None))
        ]
        if len(mods) != 1:
            raise RuntimeError("Expected one mod module")
        mod = mods[0]
        state.mod = mod
        # This integrated module uses the game's fingerprint, native code hashes,
        # SDK schema and live ownership checks below gate native writes.
        # The display version changes independently of those contracts.
        pc, pawn, cam = mod._get_runtime()
        if any(x is None for x in (pc, pawn, cam)):
            raise RuntimeError("Loaded gameplay required")
        identity = tuple(int(x._get_address()) for x in (pc, pawn, cam))
        state.owner_identity = identity
        state.owner_refs = tuple(WeakPointer(x) for x in (pc, pawn, cam))
        if not owner_matches(state, (pc, pawn, cam)):
            raise RuntimeError("Ground Slam owner weak references unavailable")
        if str(cam.GetActorCameraMode(pawn)) != "ThirdPerson" or bool(
            cam.CameraModeState.bIsTransitioning
        ):
            raise RuntimeError("Run in settled TPS")
        if any(
            bool(getattr(mod, n, False))
            for n in (
                "_ads_active",
                "_slide_active",
                "_vehicle_camera_active",
                "_shop_camera_active",
                "_ladder_active",
            )
        ):
            raise RuntimeError("Run outside special camera states")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetModuleHandleW.argtypes = (ctypes.c_wchar_p,)
        kernel.GetModuleHandleW.restype = ctypes.c_void_p
        base = int(kernel.GetModuleHandleW(None) or 0)
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
        state.kernel = kernel
        state.process = kernel.GetCurrentProcess()
        read = lambda address, size: chain.original_read(mod, address, size)
        dos = read(base, 64)
        offset = struct.unpack_from("<I", dos, 60)[0]
        if dos[:2] != b"MZ" or not 64 <= offset <= 0x100000:
            raise RuntimeError("DOS mismatch")
        pe = read(base + offset, 0x60)
        if pe[:4] != b"PE\0\0" or (
            struct.unpack_from("<I", pe, 8)[0],
            struct.unpack_from("<I", pe, 0x50)[0],
            struct.unpack_from("<H", pe, 4)[0],
        ) != REVIEWED_BUILD:
            raise RuntimeError("Build mismatch")
        if (
            read(base + ROTATION_RVA, 22) != ROTATION_ORIGINAL
            or hashlib.sha256(read(base + ROTATION_RVA, 512)).hexdigest()
            != ROTATION_SHA256
        ):
            raise RuntimeError("InitialRotation code changed or hooked")
        if hashlib.sha256(ROTATION_GUARD).hexdigest() != ROTATION_GUARD_SHA256:
            raise RuntimeError("InitialRotation guard changed")
        target = base + TARGET_RVA
        if hashlib.sha256(read(target, 4096)).hexdigest() != ENTRY_SHA256:
            raise RuntimeError("Transition code changed or another hook owns it")
        if (
            read(target, len(ORIGINAL)) != ORIGINAL
            or hashlib.sha256(PREFIX).hexdigest() != PREFIX_SHA256
        ):
            raise RuntimeError("Trace signature mismatch")
        if hashlib.sha256(read(base + APPLY_RVA, 4096)).hexdigest() != APPLY_SHA256:
            raise RuntimeError("Runtime apply code changed or another owner")
        if hashlib.sha256(APPLY_PREFIX).hexdigest() != APPLY_PREFIX_SHA256:
            raise RuntimeError("Apply trace signature mismatch")
        if struct.unpack("<Q", read(identity[2] + 0x39D8, 8))[0] != int(
            cam.CameraModeState._get_address()
        ):
            raise RuntimeError("Native state pointer differs from SDK state")
        live = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
        if not live:
            raise RuntimeError("Missing current runtime")
        definition = struct.unpack("<Q", read(live + 0x10, 8))[0]
        if not definition:
            raise RuntimeError("Missing current definition")
        tps_definition = read(definition, 56)
        schema = find_object("ScriptStruct", "/Script/GbxGame.CameraModeDef")
        if schema is None or int(schema.PropertySize) != 56:
            raise RuntimeError("Definition schema mismatch")
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
        # Resolve the mode name through the SDK pool; capture its definition
        # from the exact selected live runtime before original application.
        kernel.GetProcAddress.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
        kernel.GetProcAddress.restype = ctypes.c_void_p
        sdk_module = int(kernel.GetModuleHandleW("unrealsdk.dll") or 0)
        init_address = int(
            kernel.GetProcAddress(sdk_module, b"_unrealsdk_export__fname_init") or 0
        )
        if init_address < 0x10000:
            raise RuntimeError("SDK FName initializer unavailable")
        raw_name = ctypes.create_string_buffer(8)
        ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32)(
            init_address
        )(raw_name, "GroundSlamExit", 0)
        slam_fname = struct.unpack("<Q", raw_name.raw)[0]
        if not slam_fname or slam_fname >> 32:
            raise RuntimeError("GroundSlamExit FName invalid")
        state.clone = ctypes.create_string_buffer(56)
        if hashlib.sha256(MODIFY_PREFIX).hexdigest() != MODIFY_SHA256:
            raise RuntimeError("Owned runtime stub differs")
        struct.pack_into("<QII", modify, 0, identity[2], 1, 0)

        def prepare(manager, selected_pair):
            nonlocal slam_definition
            try:
                if not state.active or int(manager) != identity[2]:
                    return
                array, count, capacity = struct.unpack(
                    "<Qii", read(identity[2] + 0x39C0, 16)
                )
                if not 1 <= count <= capacity <= 64:
                    return
                top = read(array + (count - 1) * 40, 40)
                if struct.unpack_from("<Q", top, 0)[0] != slam_fname:
                    return
                # A fresh stack entry has no cached runtime yet.
                # apply_runtime already receives the newly constructed instance.
                pair_address = int(selected_pair or 0)
                if pair_address < 0x10000:
                    raise RuntimeError("Selected Slam runtime pair missing")
                # RDX points to a shared-pointer pair, not the runtime object.
                # The verified MODIFY_PREFIX loads runtime=[RDX], owner=[RDX+8].
                runtime_address, runtime_control = struct.unpack(
                    "<QQ", read(pair_address, 16)
                )
                if runtime_address < 0x10000 or runtime_control < 0x10000:
                    raise RuntimeError("Selected Slam runtime pair invalid")
                cached_runtime, cached_control = struct.unpack_from("<QQ", top, 24)
                self_runtime, self_control, definition_address = struct.unpack(
                    "<QQQ", read(runtime_address, 24)
                )
                if (self_runtime, self_control) != (
                    runtime_address,
                    runtime_control,
                ) or definition_address < 0x10000:
                    raise RuntimeError("Selected Slam runtime header differs")
                if cached_runtime:
                    if (cached_runtime, cached_control) != (
                        runtime_address,
                        self_control,
                    ):
                        raise RuntimeError(
                            f"Selected Slam cached owner differs: cached={cached_runtime:#x} incoming={runtime_address:#x}"
                        )
                elif cached_control:
                    raise RuntimeError("Selected Slam empty cache has a control owner")
                report["live_preparation_owner"] = {
                    "pair": hex(pair_address),
                    "runtime": hex(runtime_address),
                    "cached_runtime": hex(cached_runtime),
                    "cache_pending": not bool(cached_runtime),
                }
                if slam_definition is not None:
                    if definition_address not in (
                        slam_definition,
                        ctypes.addressof(state.clone),
                    ):
                        raise RuntimeError("Slam definition changed")
                    return
                original_definition = read(definition_address, 56)
                if (
                    original_definition[:8] != tps_definition[:8]
                    or original_definition[28] != 0x27
                ):
                    raise RuntimeError("Selected Slam definition schema differs")
                blend = struct.unpack_from("<f", original_definition, 24)[0]
                if not math.isfinite(blend) or not 0 <= blend <= 10:
                    raise RuntimeError("Slam blend invalid")
                clone_bytes = bytearray(original_definition)
                clone_bytes[28] = 0x21
                ctypes.memmove(ctypes.addressof(state.clone), bytes(clone_bytes), 56)
                state.original_definition = original_definition
                slam_definition = definition_address
                struct.pack_into(
                    "<QQ", modify, 24, slam_definition, ctypes.addressof(state.clone)
                )
                report["definition_original_hex"] = original_definition.hex()
                report["definition_private_hex"] = bytes(clone_bytes).hex()
                logging.info(
                    f"{TAG} LIVE_DEFINITION_PREPARED runtime={runtime_address:#x} cache_pending={not bool(cached_runtime)}"
                )
            except Exception as exc:
                struct.pack_into("<I", modify, 8, 0)
                struct.pack_into("<I", modify, 64, 4)
                report["errors"].append("Live Slam preparation: " + repr(exc))

        state.prepare_callback = ctypes.WINFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p
        )(prepare)
        socket_schema = find_object(
            "ScriptStruct", "/Script/GbxGame.CameraModeBehavior_OffsetToSocket"
        )
        if socket_schema is None or int(socket_schema.PropertySize) != 40:
            raise RuntimeError("Socket schema differs")
        socket_fields = {str(p.Name): p for p in socket_schema._properties()}
        rotation_field = socket_fields["bSetRotation"]
        if (int(rotation_field.Offset_Internal), int(rotation_field.FieldMask)) != (
            24,
            2,
        ):
            raise RuntimeError("Socket rotation schema differs")
        if struct.unpack("<Q", read(base + 0xB00EA00 + 24, 8))[0] != base + 0x1874A9C:
            raise RuntimeError("Socket update vtable differs")
        for code, expected in (
            (SOCKET_APPLY_PREFIX, SOCKET_APPLY_PREFIX_SHA256),
            (SOCKET_RESTORE_PREFIX, SOCKET_RESTORE_PREFIX_SHA256),
            (OFFSET_PREFIX, OFFSET_PREFIX_SHA256),
        ):
            if hashlib.sha256(code).hexdigest() != expected:
                raise RuntimeError("Spatial prefix differs")
        struct.pack_into("<Q", modify, 112, base + 0xB00EA00)
        struct.pack_into(
            "<Q", modify, 208, struct.unpack("<Q", read(identity[2] + 0x3A30, 8))[0]
        )
        struct.pack_into("<Q", modify, 216, live)
        pawn_point = pawn.K2_GetActorLocation()
        pawn_position = tuple(float(getattr(pawn_point, a)) for a in ("X", "Y", "Z"))
        normal_pov = tuple(
            float(getattr(cam.CameraModeState.POV.Location, a)) for a in ("X", "Y", "Z")
        )
        anchor_delta = tuple(normal_pov[i] - pawn_position[i] for i in range(3))
        if not all(math.isfinite(v) and abs(v) <= 256 for v in anchor_delta):
            raise RuntimeError("Normal TPS relative anchor outside validated bounds")
        report["pawn_anchor_target"] = {
            "relative_offset": list(anchor_delta),
            "captured_pawn": list(pawn_position),
            "captured_pov": list(normal_pov),
            "source": "settled normal TPS POV minus current Pawn location at arming; no hard-coded height",
            "frame_driven_position": True,
        }
        mesh = pawn.Mesh
        if mesh is None or not mesh.DoesSocketExist("Spine3"):
            raise RuntimeError("Spine3 body reference unavailable")
        body_point = mesh.GetSocketLocation("Spine3")
        body_relative_z = float(body_point.Z) - pawn_position[2]
        if not math.isfinite(body_relative_z) or abs(body_relative_z) > 256:
            raise RuntimeError("Body baseline outside bounds")
        tps_runtime = live
        tps_definition_address = definition
        report["body_anchor"] = {
            "socket": "Spine3",
            "rest_relative_z": body_relative_z,
            "vertical_only": True,
            "gain": 1.0,
            "baseline_measured_at_arming": True,
        }
        report["handoff_offset_writes"] = 0
        report["handoff_offset_samples"] = []
        report["callback_gate_counts"] = {}
        report["callback_gate_changes"] = []
        state.last_gate_key = None
        state.return_offset_done = False

        def gate(reason, details=None):
            counts = report["callback_gate_counts"]
            counts[reason] = counts.get(reason, 0) + 1
            details = details or {}
            key = (reason, tuple(sorted((k, str(v)) for k, v in details.items())))
            if (
                key != state.last_gate_key
                and len(report["callback_gate_changes"]) < 256
            ):
                report["callback_gate_changes"].append(
                    {"observer_frame": frames, "reason": reason, **details}
                )
            state.last_gate_key = key

        report["position_writes"] = 0
        report["position_samples"] = []

        def position_before_pov(state_pointer):
            if state.position_busy:
                gate("reentrant")
                return
            state.position_busy = True
            try:
                if not state.active or struct.unpack_from("<I", modify.raw, 8)[0] != 1:
                    gate("disabled")
                    return
                if not owner_matches(state, mod._get_runtime()):
                    state.owner_invalidated = True
                    # Disable this consumer immediately; remove its hooks only
                    # after returning from the native GetPOV invocation.
                    struct.pack_into("<I", modify, 8, 0)
                    struct.pack_into("<I", control, 8, 0)
                    struct.pack_into("<I", view, 8, 0)
                    struct.pack_into("<I", rotation_gate, 0, 0)
                    gate("owner_invalidated")
                    return
                saved = struct.unpack_from("<Q", modify.raw, 40)[0]
                current_native = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
                details = {
                    "saved_slam_runtime": hex(saved),
                    "current_native_runtime": hex(current_native),
                    "expected_tps_runtime": hex(tps_runtime),
                    "definition_applications": struct.unpack_from("<Q", modify.raw, 48)[
                        0
                    ],
                    "state_pointer": hex(int(state_pointer)),
                }
                if not saved:
                    # Native Apply already restored Slam ownership. Only the original
                    # TPS runtime is eligible after at least one owned definition application.
                    if not struct.unpack_from("<Q", modify.raw, 48)[0]:
                        gate("no_definition_application", details)
                        return
                    if current_native != tps_runtime:
                        gate("return_runtime_mismatch", details)
                        return
                    if (
                        struct.unpack("<Q", read(tps_runtime + 16, 8))[0]
                        != tps_definition_address
                    ):
                        gate("return_definition_mismatch", details)
                        return
                    if struct.unpack("<Q", read(identity[2] + 0x39D8, 8))[0] != int(
                        state_pointer
                    ):
                        raise RuntimeError("Return state ownership differs")
                    current = mod._get_runtime()
                    if (
                        any(x is None for x in current)
                        or tuple(int(x._get_address()) for x in current) != identity
                    ):
                        raise RuntimeError("Return pawn identity differs")
                    # Native current runtime + original definition identify TPS here.
                    # The SDK mode name can still report Slam during this first query.
                    old_offset = struct.unpack(
                        "<3d", read(int(state_pointer) + 0xC0, 24)
                    )
                    # CameraModeState offset is already fully composed at GetPOV.
                    # Bridge exactly the first verified return query with the same
                    # measured full TPS offset used during Slam, then relinquish it.
                    if state.return_offset_done:
                        gate("return_bridge_already_complete", details)
                        return
                    if not report["position_writes"]:
                        gate("no_owned_slam_pov", details)
                        return
                    if not struct.unpack_from("<I", modify.raw, 184)[0]:
                        raise RuntimeError("Measured full TPS offset unavailable")
                    target = struct.unpack_from("<3d", modify.raw, 160)
                    if not all(
                        math.isfinite(v) and abs(v) <= 512 for v in old_offset + target
                    ):
                        raise RuntimeError("Composed return offset outside bounds")
                    payload = struct.pack("<3d", *target)
                    count = ctypes.c_size_t()
                    if (
                        not kernel.WriteProcessMemory(
                            state.process,
                            int(state_pointer) + 0xC0,
                            payload,
                            24,
                            ctypes.byref(count),
                        )
                        or count.value != 24
                    ):
                        raise RuntimeError("Return offset write failed")
                    if read(int(state_pointer) + 0xC0, 24) != payload:
                        raise RuntimeError("Return offset verification differs")
                    state.return_offset_done = True
                    gate("return_offset_applied", {**details, "target": list(target)})
                    report["handoff_offset_writes"] += 1
                    report["handoff_offset_samples"].append(
                        {
                            "observer_frame": frames,
                            "before": list(old_offset),
                            "requested": list(target),
                            "runtime": hex(tps_runtime),
                        }
                    )
                    return
                if current_native != saved:
                    gate("saved_slam_but_current_differs", details)
                    return
                if struct.unpack("<Q", read(saved + 16, 8))[0] != ctypes.addressof(
                    state.clone
                ):
                    raise RuntimeError("POV private definition differs")
                if struct.unpack("<Q", read(identity[2] + 0x39D8, 8))[0] != int(
                    state_pointer
                ):
                    raise RuntimeError("POV state owner differs")
                current = mod._get_runtime()
                if (
                    any(x is None for x in current)
                    or tuple(int(x._get_address()) for x in current) != identity
                ):
                    raise RuntimeError("POV pawn identity changed")
                if str(current[2].GetActorCameraMode(current[1])) != "GroundSlamExit":
                    raise RuntimeError("POV mode differs from owned Slam")
                point = current[1].K2_GetActorLocation()
                position = tuple(float(getattr(point, a)) for a in ("X", "Y", "Z"))
                body = current[1].Mesh
                if body is None or int(body._get_address()) != int(mesh._get_address()):
                    raise RuntimeError("Body mesh owner differs")
                body_now = body.GetSocketLocation("Spine3")
                body_delta_z = (float(body_now.Z) - position[2]) - body_relative_z
                if not math.isfinite(body_delta_z) or abs(body_delta_z) > 256:
                    raise RuntimeError("Animated body movement outside bounds")
                desired = (
                    position[0] + anchor_delta[0],
                    position[1] + anchor_delta[1],
                    position[2] + anchor_delta[2] + body_delta_z,
                )
                if not all(math.isfinite(v) and abs(v) < 1e8 for v in desired):
                    raise RuntimeError("POV target outside finite bounds")
                original = read(int(state_pointer) + 0x30, 24)
                payload = struct.pack("<3d", *desired)
                count = ctypes.c_size_t()
                # Save before attempting the write so a partial write remains reportable.
                state.position_original = original
                state.position_written = payload
                if (
                    not kernel.WriteProcessMemory(
                        state.process,
                        int(state_pointer) + 0x30,
                        payload,
                        24,
                        ctypes.byref(count),
                    )
                    or count.value != 24
                ):
                    raise RuntimeError("POV anchor write failed")
                if read(int(state_pointer) + 0x30, 24) != payload:
                    raise RuntimeError("POV anchor verification differs")
                gate("slam_body_applied", details)
                report["position_writes"] += 1
                if len(report["position_samples"]) < 256:
                    report["position_samples"].append(
                        {
                            "observer_frame": frames,
                            "pawn": list(position),
                            "body_delta_z": body_delta_z,
                            "original_pov": list(struct.unpack("<3d", original)),
                            "requested_pov": list(desired),
                        }
                    )
            except BaseException as exc:
                report["errors"].append("Position callback: " + repr(exc))
                struct.pack_into("<I", modify, 64, 5)
                struct.pack_into("<I", modify, 8, 0)
                # Cleanup on the next SDK frame, never while executing this detour.
            finally:
                state.position_busy = False

        state.position_callback = ctypes.WINFUNCTYPE(None, ctypes.c_void_p)(
            position_before_pov
        )
        report["private_definition"] = hex(ctypes.addressof(state.clone))
        struct.pack_into("<QIIQ", control, 0, identity[2], 1, 0, 0)
        report["identity"] = identity
        report["target_rva"] = hex(TARGET_RVA)
        if (
            hashlib.sha256(read(base + POV_RVA, 2303)).hexdigest() != POV_SHA256
            or read(base + POV_RVA, 16) != POV_ORIGINAL
        ):
            raise RuntimeError("GetPOV code differs or another owner")
        if hashlib.sha256(POV_PREFIX).hexdigest() != POV_PREFIX_SHA256:
            raise RuntimeError("GetPOV trace stub differs")
        struct.pack_into("<QII", view, 0, int(cam.CameraModeState._get_address()), 1, 0)
        struct.pack_into("<Q", view, 160, identity[2])

        def snapshot(label):
            if len(report["events"]) >= 600:
                return
            current = mod._get_runtime()
            valid = (
                all(x is not None for x in current)
                and tuple(int(x._get_address()) for x in current) == identity
            )
            row = {
                "label": label,
                "elapsed": time.perf_counter() - started,
                "native_calls": struct.unpack_from("<Q", control.raw, 16)[0],
                "identity_same": valid,
            }
            if valid:
                camera = current[2]
                p = current[1]
                row.update(
                    mode=str(camera.GetActorCameraMode(p)),
                    transitioning=bool(camera.CameraModeState.bIsTransitioning),
                    viewmodel=bool(camera.CameraModeState.bShowViewModel),
                )
            report["events"].append(row)
            return (
                valid,
                row.get("mode"),
                row.get("transitioning"),
                row.get("viewmodel"),
                row["native_calls"],
            )

        def frame(*args):
            nonlocal frames, last, seen_slam, stable_tail
            if not state.active:
                return
            try:
                frames += 1
                current = mod._get_runtime()
                if state.owner_invalidated or not owner_matches(state, current):
                    stop("identity_changed")
                    return
                struct.pack_into("<I", view, 12, frames)
                if struct.unpack_from("<I", modify.raw, 64)[0]:
                    raise RuntimeError(
                        f'Native ownership guard refused code={struct.unpack_from("<I",modify.raw,64)[0]}'
                    )
                if (
                    slam_definition is not None
                    and read(slam_definition, 56) != state.original_definition
                ):
                    raise RuntimeError("Shared Slam definition changed")
                current = mod._get_runtime()
                if (
                    any(x is None for x in current)
                    or tuple(int(x._get_address()) for x in current) != identity
                ):
                    stop("identity_changed")
                    return
                key = (
                    str(current[2].GetActorCameraMode(current[1])),
                    bool(current[2].CameraModeState.bIsTransitioning),
                    bool(current[2].CameraModeState.bShowViewModel),
                    struct.unpack_from("<Q", control.raw, 16)[0],
                )
                if key != last:
                    snapshot("frame_change")
                    last = key
                # A pending Slam owns baselines of one particular normal TPS runtime.
                # FFYL retires/replaces that runtime even if pawn/manager stay the same.
                # Idle preparation can be discarded without any Slam data to restore.
                if not seen_slam and not struct.unpack_from("<Q", modify.raw, 48)[0]:
                    if key[0] == "FFYL":
                        stop("ffyl_invalidated_idle_tps_baseline")
                        return
                    if key[0] == "ThirdPerson" and not key[1]:
                        active_runtime = struct.unpack(
                            "<Q", read(identity[2] + 0x3A48, 8)
                        )[0]
                        if active_runtime != tps_runtime:
                            stop("normal_tps_runtime_replaced")
                            return
                # Keep the most recent native TPS samples available indefinitely.
                # Reset only in settled TPS, on the same game thread as GetPOV.
                if key[0] == "ThirdPerson" and not key[1] and not seen_slam:
                    if struct.unpack_from("<Q", view, 152)[0] > 600:
                        struct.pack_into("<Q", view, 152, 0)
                if key[0] == "GroundSlamExit":
                    seen_slam = True
                if seen_slam and key[0] == "ThirdPerson" and not key[1]:
                    stable_tail += 1
                    if stable_tail >= 24:
                        stop("slam_returned_stable_tps_with_tail")
                        return
                else:
                    stable_tail = 0

            except Exception as exc:
                report["errors"].append("Frame: " + repr(exc))
                stop("frame_error")

        specs = [(mod.FIRST_PERSON_ANIM_HOOK, Type.POST_UNCONDITIONAL, "frame", frame)]
        for path, kind, label, callback in specs:
            name = "bl4_third_person_poc.ground_slam." + label
            if has_hook(path, kind, name):
                raise RuntimeError("Untracked SDK hook exists")
            state.hooks.append((path, kind, name))
            add_hook(path, kind, name, callback)
            if not has_hook(path, kind, name):
                raise RuntimeError("SDK hook refused: " + name)
        for rva, original, prefix, label in (
            (TARGET_RVA, ORIGINAL, PREFIX, "transition"),
            (APPLY_RVA, APPLY_ORIGINAL, APPLY_PREFIX, "apply_runtime"),
        ):

            def build(stub, trampoline, prefix=prefix, label=label):
                code = prefix.replace(
                    b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control))
                )
                if label == "apply_runtime":
                    code += PREPARE_PREFIX.replace(
                        b"\x77" * 8,
                        struct.pack(
                            "<Q",
                            int(
                                ctypes.cast(
                                    state.prepare_callback, ctypes.c_void_p
                                ).value
                            ),
                        ),
                    )
                    code += (
                        SOCKET_RESTORE_PREFIX + MODIFY_PREFIX + SOCKET_APPLY_PREFIX
                    ).replace(b"\x33" * 8, struct.pack("<Q", ctypes.addressof(modify)))
                return (
                    (control, modify, state.clone, state.prepare_callback),
                    control,
                    code + b"\xff\x25\x00\x00\x00\x00" + struct.pack("<Q", trampoline),
                )

            if read(base + rva, len(original)) != original:
                raise RuntimeError("Entry changed before install")
            hook = chain.allocate(
                mod,
                base + rva,
                original,
                len(original),
                build,
                "owned-ground-slam-camera " + label + " trace",
            )
            state.native_hooks.append(hook)
            report["native_patches"] = len(state.native_hooks)
            if not chain.verify(mod, hook):
                raise RuntimeError("Installed patch verification failed")

        def view_build(stub, trampoline):
            code = POV_PREFIX.replace(b"D" * 8, struct.pack("<Q", trampoline)).replace(
                b"U" * 8, struct.pack("<Q", ctypes.addressof(view))
            )
            spatial = OFFSET_PREFIX.replace(
                b"\x33" * 8, struct.pack("<Q", ctypes.addressof(modify))
            ).replace(b"U" * 8, struct.pack("<Q", ctypes.addressof(view)))
            marker = b"\x48\xb8" + struct.pack("<Q", trampoline)
            if code.count(marker) != 1:
                raise RuntimeError("GetPOV call splice differs")
            callback_address = int(
                ctypes.cast(state.position_callback, ctypes.c_void_p).value
            )
            # Existing GetPOV wrapper has 32-byte shadow space and correct Win64 alignment.
            # RCX/RDX/R8 are restored from its saved nonvolatile argument registers.
            callback_code = (
                bytes.fromhex("4889d948b8")
                + struct.pack("<Q", callback_address)
                + bytes.fromhex("ffd04889d94889f24989f8")
            )
            code = code.replace(marker, spatial + callback_code + marker)
            return (view, modify, state.clone, state.position_callback), view, code

        hook = chain.allocate(
            mod,
            base + POV_RVA,
            POV_ORIGINAL,
            16,
            view_build,
            "owned-ground-slam-camera read-only GetPOV output trace",
        )
        state.native_hooks.append(hook)
        report["native_patches"] = len(state.native_hooks)
        if not chain.verify(mod, hook):
            raise RuntimeError("GetPOV installed patch differs")

        def rotation_build(stub, trampoline):
            code = ROTATION_GUARD.replace(
                b"\x22" * 8, struct.pack("<Q", ctypes.addressof(rotation_gate))
            )
            code = code.replace(
                b"\x33" * 8, struct.pack("<Q", ctypes.addressof(modify))
            )
            code = code.replace(b"\x44" * 8, struct.pack("<Q", base + 0xB00E090))
            code = code.replace(b"\x55" * 8, struct.pack("<Q", trampoline))
            return (rotation_gate, modify, state.clone), rotation_gate, code

        hook = chain.allocate(
            mod,
            base + ROTATION_RVA,
            ROTATION_ORIGINAL,
            22,
            rotation_build,
            "owned-ground-slam-camera owned Slam InitialRotation bypass",
        )
        state.native_hooks.append(hook)
        report["native_patches"] = len(state.native_hooks)
        if not chain.verify(mod, hook):
            raise RuntimeError("InitialRotation installed patch differs")
        snapshot("armed")
        logging.info(
            f"{TAG} ARMED implementation=owned-ground-slam-camera native_patches=4 initial_rotation_bypass=owned_slam_only private_runtime_definition=True native_pov_output_trace=True position_sources=True pawn_relative_pov=True measured_body_vertical_delta=True early_tps_composed_offset=True single_return_query=True callback_gate_diagnostics=True socket_rotation_off=True composed_tps_offset=True collision_unverified=True original_blend_unchanged=True"
        )
    except Exception as exc:
        report["errors"].append("Setup: " + repr(exc))
        stop("setup_failed")


def shutdown(reason="mod_disable"):
    owner = sys.modules.get(KEY)
    if owner is not None:
        owner.stop(reason)
    return sys.modules.get(KEY) is None


def release_for_ffyl(mod, reason="ffyl_camera_entry"):
    """Release this mod's Slam owner before FFYL replaces its TPS baseline.

    Called on the game thread before the game's entry request or our pop/push.
    Existing restoration verifies any active private definition/socket; failure
    retains the owner. Never remove another mod/reload instance's owner.
    """
    owner = sys.modules.get(KEY)
    if owner is None:
        return True
    if getattr(owner, "mod", None) is not mod:
        raise RuntimeError("Ground Slam release owner differs")
    owner.stop(reason)
    report = getattr(owner, "report", {})
    return (
        sys.modules.get(KEY) is None
        and report.get("cleanup_complete") is True
        and not report.get("errors")
        and not report.get("hook_removal_errors")
    )


def update(mod):
    """Rearm only from settled local TPS with no conflicting camera transition.

    An existing owner or latched fault suppresses a new installation. The shared
    updater calls this; it creates no separate polling or timer mechanism.
    """
    owner = sys.modules.get(KEY)
    enabled = mod.tps_ground_slam_beta.value is True and mod._third_person_enabled
    if not enabled or mod._native_fault:
        if owner is not None:
            shutdown("feature_or_tps_disabled")
        return
    if owner is not None or getattr(mod, "_ground_slam_beta_fault", False):
        return
    # A simplified FFYL cycle can keep the visible mode at ThirdPerson. Its
    # retained context, rather than mode alone, determines baseline ownership.
    from . import ffyl_strategy_runtime

    if ffyl_strategy_runtime.controls_transition(mod):
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
        # Wait until the FFYL owner has released its completed transition/tail.
        # A newly armed idle FFYL observer (seen_ffyl=False) can coexist normally.
        ffyl_owner = sys.modules.get("_bl4tps_ffyl_beta_owner")
        if ffyl_owner is not None and getattr(ffyl_owner, "seen_ffyl", False):
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
        run()
    except Exception as exc:
        mod._ground_slam_beta_fault = True
        logging.error(f"{TAG} controller refused: {exc}")


def owns_visibility_runtime(identity, *, read) -> bool:
    """Prove the owned GroundSlamExit runtime for character visibility only.

    Caller validates the live local WeakPointers/world/mode first. Preserve the
    selected runtime, private definition and native ownership status checks. Read
    errors propagate; they do not silently authorize camera collision filtering.
    """
    owner = sys.modules.get(KEY)
    if (
        owner is None
        or not getattr(owner, "active", False)
        or tuple(getattr(owner, "owner_identity", ())) != tuple(identity)
        or getattr(owner, "owner_invalidated", True)
        or owner.clone is None
    ):
        return False
    live = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
    saved = struct.unpack_from("<Q", owner.modify, 40)[0]
    return bool(
        live
        and live == saved
        and struct.unpack("<Q", read(live + 16, 8))[0] == ctypes.addressof(owner.clone)
        and not struct.unpack_from("<I", owner.modify, 64)[0]
    )
