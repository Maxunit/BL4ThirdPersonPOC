"""Filter PlaceableActor candidates using the shoulder-camera crosshair ray.

Native interaction eligibility and Use processing remain downstream.

One persistent guarded patch. Game-thread prompt PRE publishes bounded snapshots.
No Use calls, quest names, fixed player positions or gameplay timers.
"""

import ctypes
import hashlib
import math
import struct
from .build_gate import REVIEWED_BUILD
from types import SimpleNamespace
from unrealsdk import find_object, make_struct, logging
from unrealsdk.unreal import WeakPointer

KEY = "placeable_candidates"
TAG = "[BL4ThirdPersonPOC.Placeable]"
ORIGINAL = bytes.fromhex("498d8d80000000488d8424a8020000")
WINDOW_SHA = "9fca95a10162a0463029b36269240c4772609781f6b1a0f35446c2fb0bb2cbc7"
PREFIX = bytes.fromhex(
    "9c504152415349ba222222222222222241833a01754d488b07493b422075444d8b5a084d85db743b498b034883f82077324885c0740f493b7b0874224983c30848ffc875f1f049ff4210415b415a589dff25000000003333333333333333f049ff4218415b415a589d"
)


def suspend(mod):
    state = mod._active_native_state.get(KEY)
    if state is not None:
        struct.pack_into("<I", state["control"], 0, 0)


def shutdown(mod):
    state = mod._active_native_state.get(KEY)
    if state is None:
        return True
    suspend(mod)
    try:
        mod._native_restore_hook(state["hook"])
        if mod._native_read(state["hook"]["target"], len(ORIGINAL)) != ORIGINAL:
            raise RuntimeError("Restoration verification failed")
        mod._native_release_hook(state["hook"])
        mod._active_native_state.pop(KEY, None)
        logging.info(
            f"{TAG} REMOVED blocked={struct.unpack_from('<Q',state['control'].raw,16)[0]} "
            f"passed={struct.unpack_from('<Q',state['control'].raw,24)[0]} cleanup_complete=True"
        )
        return True
    except Exception as exc:
        logging.error(f"{TAG} CLEANUP_FAILED {type(exc).__name__}: {exc}; restart game")
        return False  # Keep allocations and ownership for a subsequent safe cleanup.


def install(mod):
    """Install the build-validated candidate filter only under an owned prompt shim.

    Two bounded provider buffers and control storage share process-lifetime pins.
    Partial native publication is tracked before readback so cleanup can retain it.
    """
    if mod._active_native_state.get(KEY) is not None:
        return
    control = ctypes.create_string_buffer(40)
    buffers = [ctypes.create_string_buffer(8 + 32 * 8) for _ in range(2)]
    # Retired executable allocations pin control and BOTH published buffers.
    control._buffers = buffers
    state = dict(
        control=control,
        buffers=buffers,
        index=0,
        refs=(),
        identity=None,
        failed=False,
        report={"targets_seen": []},
    )
    try:

        base = int(mod._kernel32.GetModuleHandleW(None) or 0)
        read = mod._native_read
        if not base or read(base, 2) != b"MZ":
            raise RuntimeError("Module unavailable")
        pe = struct.unpack("<I", read(base + 60, 4))[0]
        if not 64 <= pe < 0x100000:
            raise RuntimeError("Invalid PE offset")
        hdr = read(base + pe, 0x60)
        if hdr[:4] != b"PE\0\0" or (
            struct.unpack_from("<I", hdr, 8)[0],
            struct.unpack_from("<I", hdr, 0x50)[0],
            struct.unpack_from("<H", hdr, 4)[0],
        ) != REVIEWED_BUILD:
            raise RuntimeError("Game build differs")
        target = base + 0x3E54964
        reject = base + 0x3E552E0
        if hashlib.sha256(read(target, 49)).hexdigest() != WINDOW_SHA:
            raise RuntimeError("Bounds call-site differs")
        if read(reject, 8) != bytes.fromhex("4c8bac2488000000"):
            raise RuntimeError("Candidate rejection continuation differs")
        prompt = mod._interaction_prompt_state
        if (
            not prompt
            or not prompt.get("ready")
            or read(prompt["target"], len(prompt["patch"])) != prompt["patch"]
        ):
            raise RuntimeError("Prompt correction not owned")
        vtable = base + 0xB914850
        if struct.unpack("<Q", read(vtable + 8, 8))[0] != base + 0x933848 or read(
            base + 0x933848, 8
        ) != bytes.fromhex("488d8140fcffffc3"):
            raise RuntimeError("Provider getter differs")
        state["vtable"] = vtable
        struct.pack_into("<Q", control, 32, vtable)
        struct.pack_into("<Q", control, 8, ctypes.addressof(buffers[0]))

        def build(stub, trampoline):
            code = PREFIX.replace(
                b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control))
            ).replace(b"\x33" * 8, struct.pack("<Q", reject))
            return (
                None,
                control,
                code + b"\xff\x25\0\0\0\0" + struct.pack("<Q", trampoline),
            )

        state["hook"] = mod._native_allocate_hook(
            target, ORIGINAL, len(ORIGINAL), build, "PlaceableActor camera candidates"
        )
        mod._active_native_state[KEY] = state
        if read(target, len(ORIGINAL)) != state["hook"]["patch"]:
            raise RuntimeError("Installed native bytes differ")
        logging.info(
            f"{TAG} READY source=camera-placeable-candidates native_patches=1 native_eligibility_retained=True"
        )
    except Exception as exc:
        logging.error(f"{TAG} INSTALL_FAILED {type(exc).__name__}: {exc}")
        if "hook" in state:
            shutdown(mod)


def trace_candidates(mod, fallback):
    """Publish at most 32 live Placeable providers from a crosshair trace.

    Suspend the native filter before gathering; validate provider layout and
    WeakPointers before flipping buffers. On uncertainty latch failure and use
    the supplied baseline trace without silently enabling an invalid snapshot.
    """
    persistent = mod._active_native_state.get(KEY)
    if persistent is None:
        return fallback()
    suspend(mod)
    if persistent["failed"]:
        return fallback()
    try:
        pc, pawn, cam = mod._get_runtime()
        if (
            any(x is None for x in (pc, pawn, cam))
            or not mod._item_card_should_override()
            or str(cam.GetActorCameraMode(pawn)) != "ThirdPerson"
        ):
            return fallback()
        identity = tuple(mod._object_address(x) for x in (pc, pawn, cam))
        if identity != persistent["identity"]:
            persistent["refs"] = ()
            persistent["identity"] = identity
        pending_providers = []
        pending_refs = []
        report = persistent["report"]
        vtable = persistent["vtable"]
        read = mod._native_read
        state = SimpleNamespace(original=fallback)

        def xyz(v):
            return [float(getattr(v, k)) for k in "XYZ"]

        def trace():
            nonlocal pending_providers, pending_refs
            pending_providers = []
            pending_refs = []
            first = None
            try:
                pc, pawn, cam = mod._get_runtime()
                if (
                    any(x is None for x in (pc, pawn, cam))
                    or not mod._third_person_enabled
                    or mod._ads_active
                ):
                    return state.original()
                sx, sy = mod._get_tps_crosshair_screen(pc, cam)
                proj = pc.DeprojectScreenPositionToWorld(
                    sx,
                    sy,
                    mod._make_vector(0.0, 0.0, 0.0),
                    mod._make_vector(0.0, 0.0, 0.0),
                )
                if not proj[0]:
                    raise RuntimeError("Crosshair deprojection failed")
                start, direction = proj[1:3]
                ray = xyz(direction)
                norm = math.sqrt(sum(x * x for x in ray))
                if not math.isfinite(norm) or norm < 1e-8:
                    raise RuntimeError("Invalid crosshair direction")
                end = mod._make_vector(
                    *(
                        a + d / norm * mod.INTERACTION_TRACE_DISTANCE
                        for a, d in zip(xyz(start), ray)
                    )
                )
                lib = find_object(
                    "KismetSystemLibrary", "/Script/Engine.Default__KismetSystemLibrary"
                )
                result = lib.LineTraceMulti(
                    pc,
                    start,
                    end,
                    5,
                    True,
                    [pawn],
                    0,
                    [],
                    True,
                    make_struct("LinearColor", R=1.0, G=0.0, B=0.0, A=1.0),
                    make_struct("LinearColor", R=0.0, G=1.0, B=0.0, A=1.0),
                    0.0,
                )
                for hit in result[-1]:
                    component = hit.Component
                    actor = component.Outer if component is not None else None
                    eligible = (
                        actor is not None
                        and str(actor.Class.Name) == "PlaceableActor"
                        and not actor.bHidden
                        and actor.bActorEnableCollision
                        and hasattr(actor, "UsabilityConfigInfo")
                    )
                    if not eligible:
                        if hit.bBlockingHit:
                            break
                        continue
                    point = xyz(hit.ImpactPoint)
                    if (
                        not all(math.isfinite(x) for x in point)
                        or not math.isfinite(float(hit.Distance))
                        or hit.Distance < 0
                    ):
                        if hit.bBlockingHit:
                            break
                        continue
                    address = int(actor._get_address())
                    provider = address + 0x3C0
                    if (
                        struct.unpack("<Q", read(provider, 8))[0] != vtable
                        or struct.unpack("<Q", read(provider + 32, 8))[0] != provider
                    ):
                        raise RuntimeError(
                            "Encountered unsupported PlaceableActor provider"
                        )
                    if provider not in pending_providers:
                        if len(pending_providers) >= 32:
                            raise RuntimeError("Placeable overlap set exceeded cap=32")
                        pending_providers.append(provider)
                        pending_refs.append(WeakPointer(actor))
                    target_path = str(actor._path_name())
                    if (
                        target_path not in report["targets_seen"]
                        and len(report["targets_seen"]) < 64
                    ):
                        report["targets_seen"].append(target_path)
                        logging.warning(
                            f"{TAG} TARGET class={actor.Class.Name} path={target_path}"
                        )
                    if first is None:
                        first = (tuple(point), str(actor.Class.Name), target_path)
                    if hit.bBlockingHit:
                        break
                if first is not None:
                    return first
            except Exception as exc:
                report["last_trace_error"] = repr(exc)
            return state.original()

        result = trace()
        if report.get("last_trace_error"):
            raise RuntimeError(report["last_trace_error"])
        if any(ref() is None for ref in pending_refs):
            raise RuntimeError("Candidate retired before publication")
        index = 1 - persistent["index"]
        buffer = persistent["buffers"][index]
        struct.pack_into("<Q", buffer, 0, len(pending_providers))
        for i, provider in enumerate(pending_providers):
            struct.pack_into("<Q", buffer, 8 + 8 * i, provider)
        persistent["refs"] = tuple(pending_refs)
        struct.pack_into("<Q", persistent["control"], 8, ctypes.addressof(buffer))
        persistent["index"] = index
        struct.pack_into("<I", persistent["control"], 0, 1)
        return result
    except Exception as exc:
        suspend(mod)
        persistent["failed"] = True
        logging.error(
            f"{TAG} TRACE_DISABLED {type(exc).__name__}: {exc}; baseline targeting retained"
        )
        return fallback()
