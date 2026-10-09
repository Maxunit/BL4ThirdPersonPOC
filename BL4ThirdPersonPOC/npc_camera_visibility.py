"""Character collision exclusion and local near-camera hiding.

Native exclusion is scoped to the selected live TPS collision producer, its
thread, and its exact scene-query parameters. Walls and unrelated traces retain
original decisions. FFYL uses the same discovered group in its owned SDK sweep.

World actor queries alternate Character/Deco families every 30 camera callbacks.
WeakPointer identities prevent stale object reuse. Hiding owns only entries it
inserts in the local controller's HiddenActors array. Special camera states
pause or release ownership; settled TPS starts a new owner after travel/respawn.

No component collision responses are changed. Native signatures are tied to the
reviewed game build. Small counters replace the diagnostic recording buffers.
The existing camera updater owns update(); there is no extra SDK frame hook.
"""

import ctypes
import hashlib
import math
import struct
from .build_gate import REVIEWED_BUILD
import time
import types
from collections import deque
from unrealsdk import find_object, logging
from unrealsdk.unreal import WeakPointer

KEY = "_npc_camera_visibility_state"
TAG = "[BL4ThirdPersonPOC.CharacterCamera]"
WRAP = (
    b"H\x83\xec8H\x89L$ H\xc7D$(\x00\x00\x00\x00\x9cP"
    b'ARASI\xba""""""""A\x83:\x01u>'
    b"I;J(u8eL\x8b\x1c%H\x00\x00\x001\xc0\xf0M\x0f"
    b"\xb1Z\x08t\x05L9\xd8u I\xffB\x10H\xc7D$H\x01"
    b"\x00\x00\x00I\x83z\x10\x01u\x0cH\x8d\x84$\x18\xff\xff\xffI\x89"
    b"B A[AZX\x9d\xff\x15\x02\x00\x00\x00\xeb\x083333"
    b'3333\x9cPARASI\xba""""""""'
    b"H\x83|$H\x01u%eL\x8b\x1c%H\x00\x00\x00M9Z"
    b"\x08u\x16I\xffJ\x10u\x10I\xc7B \x00\x00\x00\x00I\xc7B"
    b"\x08\x00\x00\x00\x00A[AZX\x9dH\x8dd$8\xc3"
)
CAM_ORIGINAL = b"AWAVAUATVWUSH\x81\xecx\x02\x00\x00"
FILTER_ORIGINAL = b"VWSH\x83\xec L\x89\xc3H\x89\xceA\x8bH\x0c"
OBSERVER = (
    b'\x9cPARASAQI\xba""""""""A\x83'
    b":\x01uzeL\x8b\x1c%H\x00\x00\x00M;Z\x08ukI"
    b"\x83z\x10\x01udI\x8bB H\x85\xc0t[H\x83\xc0`H"
    b"9A\x18uQ\xf0I\xffB@A\x83z\x04\x01uEM\x8bZ"
    b"0M\x85\xdbt<E\x8b\x0bA\x81\xf9\x80\x00\x00\x00w0E\x85"
    b"\xc9t+I\x83\xc3\x08A\x8b\x03A;\x00t\x0bI\x83\xc3\x04A"
    b"\xff\xc9u\xef\xeb\x14\xf0I\xffBH\xc6A\x08\x00AYA[A"
    b"ZX\x9d1\xc0\xc3AYA[AZX\x9d\xff%\x00\x00\x00\x00"
    b"33333333"
)


def xyz(v):
    result = tuple(float(getattr(v, k)) for k in ("X", "Y", "Z"))
    if not all(math.isfinite(x) for x in result):
        raise RuntimeError("Non-finite geometry")
    return result


def capsule_gap(point, center, radius, half_height, up):
    # Closest point on the capsule's central segment in world space.
    length = math.sqrt(sum(x * x for x in up))
    if not math.isfinite(length) or not 0.99 <= length <= 1.01:
        raise RuntimeError("Invalid capsule axis")
    axis = tuple(x / length for x in up)
    delta = tuple(p - c for p, c in zip(point, center))
    extent = half_height - radius
    along = max(-extent, min(extent, sum(d * u for d, u in zip(delta, axis))))
    return math.sqrt(sum((d - along * u) ** 2 for d, u in zip(delta, axis))) - radius


def ads_gate(mode, route, first_person, transitioning):
    """Only TPS hip/TPS ADS is eligible; FPS ADS stays original."""
    if route not in ("hip", "tps", "sniper_fps", "fallback_fps"):
        return "stop"
    if mode not in ("ThirdPerson", "Default", "FirstPerson"):
        return "stop"
    if transitioning or first_person or route in ("sniper_fps", "fallback_fps"):
        return "pause"
    if mode == "ThirdPerson" and route in ("hip", "tps"):
        return "active"
    return "pause"


def lifecycle_gate(mode, route, first_person, transitioning, owned):
    if mode in ("FFYL", "GroundSlamExit"):
        return "active" if owned and not first_person and route == "hip" else "pause"
    if mode == "GroundSlam":
        return "pause"
    return ads_gate(mode, route, first_person, transitioning)


def world_address(obj):
    for _ in range(16):
        if obj is None:
            return None
        if str(obj.Class.Name) == "World":
            return int(obj._get_address())
        obj = obj.Outer
    return None


def eligible(mod):
    if not mod._third_person_enabled or mod._ads_route != "hip":
        return False
    if any(
        bool(getattr(mod, k, False))
        for k in (
            "_ads_active",
            "_slide_active",
            "_ladder_active",
            "_vehicle_camera_active",
            "_shop_camera_active",
        )
    ):
        return False
    pc, pawn, cam = mod._get_runtime()
    return (
        all(o is not None for o in (pc, pawn, cam))
        and str(cam.GetActorCameraMode(pawn)) == "ThirdPerson"
        and not bool(cam.CameraModeState.bIsTransitioning)
        and not mod._looks_like_first_person_fallback()
    )


def shutdown(mod, reason="shutdown"):
    state = getattr(mod, KEY, None)
    if state is None:
        return True
    return state.stop(reason)


def update(mod):
    state = getattr(mod, KEY, None)
    try:
        if state is not None:
            if not state.active:
                state.stop("cleanup_retry")
                return
            if getattr(mod, "_npc_camera_visibility_fault", False):
                state.stop("fault")
                return
            state.tick()
            return
        if not getattr(mod, "_npc_camera_visibility_fault", False) and eligible(mod):
            install(mod)
    except Exception as exc:
        mod._npc_camera_visibility_fault = True
        logging.error(f"{TAG} UPDATE_FAILED {type(exc).__name__}: {exc}")
        shutdown(mod, "update_error")


def install(mod):
    """Publish a thread/query-scoped character filter and local hiding owner.

    Native signatures and local serial/world identity gate filter binding.
    Character discovery uses the existing callback budget; HiddenActors cleanup
    removes only entries this owner inserted. Active native calls delay cleanup.
    """
    if getattr(mod, KEY, None) is not None:
        return
    st = types.ModuleType(KEY)
    st.active = True
    st.hooks = []
    st.mod = mod
    control = ctypes.create_string_buffer(128)
    st.control = control
    tables = [ctypes.create_string_buffer(8 + 128 * 4) for _ in range(2)]
    # Retired executable allocations pin both published buffers.
    control._tables = tables
    st.tables = tables
    st.table_slot = 0
    st.visibility = {}
    st.hidden_owned = {}
    st.targets = {}
    st.frames = 0
    st.discovery_class = 0
    report = st.report = dict(
        errors=deque(maxlen=32), native_patches=0, cleanup_complete=False
    )
    report["admissions"] = deque(maxlen=64)
    report["producer_binding_events"] = deque(maxlen=32)
    report["visibility_events"] = deque(maxlen=64)
    report["ads_gate_events"] = deque(maxlen=32)
    report["lifecycle_events"] = deque(maxlen=32)
    setattr(mod, KEY, st)

    def addr(o):
        return int(o._get_address())

    def stop(reason):
        st.active = False
        struct.pack_into("<I", control, 0, 0)
        # Disable the FFYL provider before any restoration can invoke callbacks.
        if (
            hasattr(st, "ignore_provider")
            and getattr(mod, "_ffyl_camera_ignore_provider", None) is st.ignore_provider
        ):
            delattr(mod, "_ffyl_camera_ignore_provider")
        if struct.unpack_from("<Q", control, 16)[0] != 0:
            report["cleanup_deferred"] = True
            return False
        struct.pack_into("<Q", control, 48, 0)
        if hasattr(st, "visibility_cleanup"):
            try:
                st.visibility_cleanup()
            except Exception as exc:
                report["errors"].append("Visibility restore: " + repr(exc))
        for h in list(reversed(st.hooks)):
            try:
                mod._native_restore_hook(h)
                if mod._native_read(h["target"], len(h["original"])) != h["original"]:
                    raise RuntimeError("Restore verification failed")
                mod._native_release_hook(h)
                st.hooks.remove(h)
            except Exception as exc:
                report["errors"].append("Native restore: " + repr(exc))
        clean = not st.hooks and not st.hidden_owned
        report.update(
            reason=reason,
            native_patches=len(st.hooks),
            cleanup_complete=clean,
            calls=struct.unpack_from("<Q", control, 64)[0],
            rejected=struct.unpack_from("<Q", control, 72)[0],
        )
        if report["errors"] or not clean:
            mod._npc_camera_visibility_fault = True
            logging.error(f'{TAG} RESTORE_DETAILS {list(report["errors"])}')
        if clean and getattr(mod, KEY, None) is st:
            setattr(mod, KEY, None)
        mod._character_camera_last_report = report
        logging.info(
            f'{TAG} COMPLETE reason={reason} errors={len(report["errors"])} native_patches={len(st.hooks)} cleanup_complete={clean} rejected={report['rejected']} ffyl_queries={report.get('ffyl_ignore_queries',0)}'
        )
        return clean

    st.stop = stop
    try:
        if getattr(mod, "_ffyl_camera_ignore_provider", None) is not None:
            raise RuntimeError("FFYL ignore provider already owned")
        runtime = mod._get_runtime()
        if any(o is None for o in runtime):
            raise RuntimeError("Loaded gameplay required")
        identity = tuple(addr(o) for o in runtime)
        owner_refs = tuple(WeakPointer(o) for o in runtime)
        player_world = world_address(runtime[1])
        if player_world is None:
            raise RuntimeError("Player world unavailable")
        read = mod._native_read

        def assess():
            now = mod._get_runtime()
            if (
                not all(o is not None for o in now)
                or any(ref() is None for ref in owner_refs)
                or tuple(addr(o) for o in now) != identity
                or world_address(now[1]) != player_world
                or not mod._third_person_enabled
            ):
                return "stop", "runtime_or_tps_changed"
            if any(
                bool(getattr(mod, k, False))
                for k in (
                    "_slide_active",
                    "_ladder_active",
                    "_vehicle_camera_active",
                    "_shop_camera_active",
                )
            ):
                return "stop", "unsupported_camera_state"
            mode = str(now[2].GetActorCameraMode(now[1]))
            route = str(mod._ads_route)
            owned = False
            if mode == "FFYL":
                from . import ffyl_strategy_runtime

                # The simple strategy uses the native TPS producer after its
                # handoff, not the legacy SDK FFYL sweep. Pause the brief FFYL
                # mode until that exact TPS producer becomes available again.
                if ffyl_strategy_runtime.controller(mod) is None:
                    from . import ffyl_legacy_camera

                    owned = ffyl_legacy_camera.owns_visibility_runtime(
                        identity, read=read
                    )
            elif mode == "GroundSlamExit":
                from . import ground_slam_camera

                owned = ground_slam_camera.owns_visibility_runtime(identity, read=read)
            gate = lifecycle_gate(
                mode,
                route,
                bool(mod._looks_like_first_person_fallback()),
                bool(now[2].CameraModeState.bIsTransitioning),
                owned,
            )
            return gate, mode + ":" + route + (":owned" if owned else "")

        def ignore_provider(caller_identity):
            # Invoked directly by our FFYL camera sweep, including the early
            # native handoff callback. No global trace hook or global collision write.
            if (
                not st.active
                or getattr(mod, "_npc_camera_visibility_fault", False)
                or tuple(caller_identity) != identity
                or any(ref() is None for ref in owner_refs)
            ):
                return ()
            now = mod._get_runtime()
            if any(o is None for o in now) or tuple(addr(o) for o in now) != identity:
                return ()
            if (
                world_address(now[1]) != player_world
                or str(now[2].GetActorCameraMode(now[1])) != "FFYL"
            ):
                return ()
            t = time.perf_counter()
            actors = []
            for index, v in tuple(st.targets.items()):
                actor = v["ref"]()
                if actor is None or addr(actor) != v["address"]:
                    continue
                if struct.unpack("<i", read(v["address"] + 12, 4))[0] != index:
                    continue
                actors.append(actor)
            report["ffyl_ignore_queries"] = report.get("ffyl_ignore_queries", 0) + 1
            report["ffyl_ignore_nonempty_queries"] = report.get(
                "ffyl_ignore_nonempty_queries", 0
            ) + int(bool(actors))
            report["ffyl_ignore_max_count"] = max(
                report.get("ffyl_ignore_max_count", 0), len(actors)
            )
            cost("ffyl_ignore_provider", t)
            return tuple(actors)

        st.ignore_provider = ignore_provider
        mod._ffyl_camera_ignore_provider = ignore_provider
        st.gate = "active"
        read = mod._native_read
        base = int(mod._kernel32.GetModuleHandleW(None) or 0)
        st.base = base
        if not base or read(base, 2) != b"MZ":
            raise RuntimeError("Module invalid")
        pe = struct.unpack("<I", read(base + 60, 4))[0]
        if not 64 <= pe <= 0x100000:
            raise RuntimeError("PE offset invalid")
        hdr = read(base + pe, 0x60)
        if hdr[:4] != b"PE\0\0" or (
            struct.unpack_from("<I", hdr, 8)[0],
            struct.unpack_from("<I", hdr, 0x50)[0],
            struct.unpack_from("<H", hdr, 4)[0],
        ) != REVIEWED_BUILD:
            raise RuntimeError("Game build differs")
        for rva, size, digest in (
            (
                0x1873BD8,
                0x6C0,
                "c6b6eef3e719ee8723433d4531519543b08f5ab51b0a2df3b43d41655595ea40",
            ),
            (
                0x23B4E,
                0x3000,
                "382bff1d82853383fdafcc39a0d37f84f940b1621c13be584b71456def37041b",
            ),
            (
                0x344931D,
                0x8000,
                "09981f99184244bab762d21ccefba258bd044bd87a14d3b8f3306bce98c4b792",
            ),
        ):
            if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
                raise RuntimeError("Reviewed code differs at " + hex(rva))

        def bind_receiver():
            # A valid transitional list can have zero or several matching objects.
            # Never select an arbitrary receiver. Failed memory reads stay errors.
            struct.pack_into("<I", control, 0, 0)
            struct.pack_into("<Q", control, 40, 0)
            st.bound_runtime = 0
            owner = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
            producers = []
            components = []
            count = cap = 0
            if owner:
                data, count, cap = struct.unpack("<Qii", read(owner + 0x30, 16))
                if not 0 <= count <= cap <= 64 or (count and not data):
                    raise RuntimeError("Producer list invalid")
                for i in range(count):
                    a = struct.unpack("<Q", read(data + i * 16, 8))[0]
                    if not a:
                        continue
                    vt = struct.unpack("<Q", read(a, 8))[0]
                    entry = struct.unpack("<Q", read(vt + 24, 8))[0] if vt else 0
                    components.append(
                        dict(
                            address=hex(a),
                            vtable=hex(vt),
                            entry_rva=hex(entry - base) if entry else None,
                        )
                    )
                    if entry == base + 0x1873BD8:
                        producers.append(a)
            fresh = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
            stable = fresh == owner
            row = dict(
                runtime=hex(owner),
                current_runtime=hex(fresh),
                component_count=count,
                capacity=cap,
                producer_count=len(producers),
                stable=stable,
                components=components,
            )
            signature = (
                owner,
                fresh,
                count,
                cap,
                tuple(producers),
                tuple((c["address"], c["vtable"], c["entry_rva"]) for c in components),
            )
            if signature != getattr(st, "producer_signature", None):
                report["producer_binding_events"].append(
                    dict(observer_callback=getattr(st, "callbacks", 0), **row)
                )
                st.producer_signature = signature
            if not owner or not stable or len(producers) != 1:
                report["producer_wait_callbacks"] = (
                    report.get("producer_wait_callbacks", 0) + 1
                )
                return None
            receiver = producers[0]
            struct.pack_into("<Q", control, 40, receiver)
            st.bound_runtime = owner
            return receiver

        receiver = bind_receiver()
        if receiver is None:
            stop("producer_not_ready")
            return
        lib = find_object("GameplayStatics", "/Script/Engine.Default__GameplayStatics")
        classes = {
            name: find_object("Class", "/Script/OakGame." + name)
            for name in ("OakCharacter", "OakDecoCharacter")
        }
        if lib is None or any(c is None for c in classes.values()):
            raise RuntimeError("Character classes/world query unavailable")
        fn = find_object(
            "Function", "/Script/Engine.GameplayStatics:GetAllActorsOfClass"
        )
        if fn is None or {str(p.Name) for p in fn._properties()} != {
            "WorldContextObject",
            "ActorClass",
            "OutActors",
        }:
            raise RuntimeError("World query signature differs")

        def unpack_objects(result):
            if (
                isinstance(result, (tuple, list))
                and len(result) == 2
                and (result[0] is Ellipsis or result[0] is None)
            ):
                result = result[1]
            elif (
                isinstance(result, tuple)
                and len(result) == 1
                and not hasattr(result[0], "_path_name")
            ):
                result = result[0]
            if result is None or result is Ellipsis:
                raise RuntimeError("World actor output missing")
            values = list(result)
            if len(values) > 8192:
                raise RuntimeError("World actor output exceeds bound")
            return values

        def cost(label, t):
            ms = (time.perf_counter() - t) * 1000
            entry = report.setdefault("callback_cost", {}).setdefault(
                label, dict(count=0, total_ms=0.0, max_ms=0.0, over_2ms=0)
            )
            entry["count"] += 1
            entry["total_ms"] += ms
            entry["max_ms"] = max(entry["max_ms"], ms)
            entry["over_2ms"] += ms > 2

        def discover(family):
            t = time.perf_counter()
            center = mod._get_runtime()[1].K2_GetActorLocation()
            found = []
            for o in unpack_objects(
                lib.GetAllActorsOfClass(mod._get_runtime()[1], classes[family], [])
            ):
                if o is None:
                    continue
                try:
                    a = addr(o)
                    if a == identity[1]:
                        continue
                    loc = o.K2_GetActorLocation()
                    d2 = sum(
                        (float(getattr(loc, k)) - float(getattr(center, k))) ** 2
                        for k in "XYZ"
                    )
                    if not math.isfinite(d2) or not 0 <= d2 <= 3000**2:
                        continue
                    ref = WeakPointer(o)
                    index = struct.unpack("<i", read(a + 12, 4))[0]
                    if index < 0:
                        continue
                    live = ref()
                    if live is None or addr(live) != a:
                        continue
                    found.append(
                        dict(
                            ref=ref,
                            address=a,
                            index=index,
                            path=str(o._path_name()),
                            family=family,
                            distance=math.sqrt(d2),
                        )
                    )
                except Exception as exc:
                    report["discovery_actor_skips"] = (
                        report.get("discovery_actor_skips", 0) + 1
                    )
            previous = {v["index"] for v in st.targets.values()}
            combined = [v for v in st.targets.values() if v["family"] != family] + found
            combined.sort(key=lambda v: v["distance"])
            st.targets = {v["index"]: v for v in combined[:128]}
            report["capacity_deferrals"] = report.get("capacity_deferrals", 0) + max(
                0, len(combined) - 128
            )
            for index, v in st.targets.items():
                if index not in previous:
                    report["admissions"].append(
                        dict(
                            frame=st.frames, index=index, path=v["path"], family=family
                        )
                    )
            report["active_peak"] = max(report.get("active_peak", 0), len(st.targets))
            cost("discovery", t)

        def publish_live():
            # WeakPointer contains object serial identity; address check prevents reuse.
            indices = []
            for index, v in list(st.targets.items()):
                o = v["ref"]()
                if o is None or addr(o) != v["address"]:
                    st.targets.pop(index, None)
                    report["lifecycle_retirements"] = (
                        report.get("lifecycle_retirements", 0) + 1
                    )
                    continue
                indices.append(index)
            slot = 1 - st.table_slot
            table = tables[slot]
            struct.pack_into("<II", table, 0, len(indices), 0)
            if indices:
                struct.pack_into("<" + "I" * len(indices), table, 8, *indices)
            struct.pack_into("<Q", control, 48, ctypes.addressof(table))
            st.table_slot = slot
            report["published_count"] = len(indices)

        capsule_class = find_object("Class", "/Script/Engine.CapsuleComponent")
        if capsule_class is None:
            raise RuntimeError("Capsule geometry class unavailable")
        pc_ref = owner_refs[0]

        def prepare_visibility(index, v):
            actor = v["ref"]()
            if actor is None:
                return
            bodies = []
            for c in list(actor.K2_GetComponentsByClass(capsule_class))[:16]:
                if c is None or addr(c.GetOwner()) != v["address"]:
                    continue
                r = float(c.GetScaledCapsuleRadius())
                h = float(c.GetScaledCapsuleHalfHeight())
                if math.isfinite(r + h) and 0 < r <= h < 2000:
                    bodies.append(dict(ref=WeakPointer(c), address=addr(c)))
            mesh = find_object("GbxSkeletalMeshComponent", v["path"] + ".CharacterMesh")
            names = []
            mesh_ref = None
            mesh_address = None
            if mesh is not None and addr(mesh.GetOwner()) == v["address"]:
                available = {str(n) for n in mesh.GetAllSocketNames()}
                if "Head" in available:
                    names = [
                        n
                        for n in (
                            "Head",
                            "Neck",
                            "Neck1",
                            "L_Eye",
                            "R_Eye",
                            "UpperTeeth",
                            "LowerTeeth",
                            "Jaw",
                            "FaceRoot",
                        )
                        if n in available
                    ]
                    mesh_ref = WeakPointer(mesh)
                    mesh_address = addr(mesh)
            st.visibility[index] = dict(
                ref=v["ref"],
                address=v["address"],
                path=v["path"],
                bodies=bodies,
                mesh_ref=mesh_ref,
                mesh_address=mesh_address,
                names=names,
            )
            report["visibility_prepared"] = report.get("visibility_prepared", 0) + 1

        def reconcile_visibility(desired):
            # With no requested hides and no owned entries, there is nothing
            # to mutate or restore; foreign visibility is irrelevant to this call.
            if not desired and not st.hidden_owned:
                report["hidden_count"] = 0
                report["visibility_idle_skips"] = (
                    report.get("visibility_idle_skips", 0) + 1
                )
                return
            # Own only entries we inserted; retain every pre-existing/foreign entry.
            pc = pc_ref()
            if pc is None:
                if desired:
                    raise RuntimeError("Visibility controller destroyed")
                st.hidden_owned.clear()
                return
            if addr(pc) != identity[0]:
                raise RuntimeError("Visibility controller identity changed")
            values = list(pc.HiddenActors)
            if len(values) > 256:
                raise RuntimeError("HiddenActors exceeds bound")
            owned_by_address = {}
            for i, v in st.hidden_owned.items():
                live = v["ref"]()
                if live is not None and addr(live) == v["address"]:
                    owned_by_address[v["address"]] = i
            expected = []
            for actor in values:
                if actor is None:
                    expected.append(actor)
                    continue
                owned = owned_by_address.get(addr(actor))
                if owned is None or owned in desired:
                    expected.append(actor)
            present = {addr(a) for a in expected if a is not None}
            for index, v in desired.items():
                actor = v["ref"]()
                if actor is None or addr(actor) != v["address"]:
                    continue
                if v["address"] not in present:
                    # Journal before setter: a partially successful assignment is restorable.
                    st.hidden_owned[index] = v
                    expected.append(actor)
                    present.add(v["address"])
            before = [None if a is None else addr(a) for a in values]
            after = [None if a is None else addr(a) for a in expected]
            if before != after:
                pc.HiddenActors = expected
                report["visibility_writes"] = report.get("visibility_writes", 0) + 1
                if [None if a is None else addr(a) for a in pc.HiddenActors] != after:
                    raise RuntimeError("HiddenActors write verification differs")
            st.hidden_owned = {
                i: v
                for i, v in st.hidden_owned.items()
                if i in desired and v["ref"]() is not None
            }
            report["hidden_peak"] = max(
                report.get("hidden_peak", 0), len(st.hidden_owned)
            )
            report["hidden_count"] = len(st.hidden_owned)

        def update_visibility():
            if struct.unpack_from("<I", control, 4)[0] != 1:
                return
            point = xyz(runtime[2].GetCameraLocation())
            desired = {}
            # Prepare at most one new nearby geometry set per callback.
            prepared = False
            for index, v in list(st.targets.items()):
                actor = v["ref"]()
                if actor is None:
                    continue
                if math.dist(point, xyz(actor.K2_GetActorLocation())) > 1000:
                    continue
                g = st.visibility.get(index)
                if g is None or g["address"] != v["address"] or g["ref"]() is None:
                    if prepared:
                        continue
                    prepared = True
                    try:
                        prepare_visibility(index, v)
                        g = st.visibility.get(index)
                    except Exception:
                        report["geometry_prepare_skips"] = (
                            report.get("geometry_prepare_skips", 0) + 1
                        )
                        continue
                gap = float("inf")
                head_gap = None
                head_bodies = []
                for body in g["bodies"]:
                    c = body["ref"]()
                    if c is None or addr(c) != body["address"]:
                        continue
                    try:
                        r = float(c.GetScaledCapsuleRadius())
                        h = float(c.GetScaledCapsuleHalfHeight())
                        if not math.isfinite(r + h) or not 0 < r <= h < 2000:
                            continue
                        center = xyz(c.K2_GetComponentLocation())
                        distance = math.dist(point, center)
                        # A capsule lies inside its half-height sphere. Outside this
                        # envelope + show margin, its exact axis cannot trigger hide.
                        if distance <= h + 35:
                            gap = min(
                                gap,
                                capsule_gap(point, center, r, h, xyz(c.GetUpVector())),
                            )
                            report["body_exact_queries"] = (
                                report.get("body_exact_queries", 0) + 1
                            )
                        else:
                            report["body_envelope_skips"] = (
                                report.get("body_envelope_skips", 0) + 1
                            )
                        if g["names"] and distance <= 2 * h + 3.35 * r + 35:
                            head_bodies.append((center, r, h))
                    except Exception:
                        report["geometry_read_skips"] = (
                            report.get("geometry_read_skips", 0) + 1
                        )
                mesh = g["mesh_ref"]() if g["mesh_ref"] else None
                body_decides_hide = gap < 35 if index in st.hidden_owned else gap <= 15
                if body_decides_hide:
                    report["head_body_decision_skips"] = (
                        report.get("head_body_decision_skips", 0) + 1
                    )
                if (
                    not body_decides_hide
                    and head_bodies
                    and mesh is not None
                    and addr(mesh) == g["mesh_address"]
                ):
                    try:
                        # Read Head once. The accepted head sphere has radius <3.35r;
                        # distant heads need no remaining socket reads this callback.
                        hc = xyz(mesh.GetSocketLocation("Head"))
                        eligible = [
                            (center, r, h)
                            for center, r, h in head_bodies
                            if math.dist(hc, center) <= 2 * h
                            and math.dist(point, hc) <= 3.35 * r + 35
                        ]
                        if eligible:
                            points = [hc] + [
                                xyz(mesh.GetSocketLocation(n))
                                for n in g["names"]
                                if n != "Head"
                            ]
                            spread = max(math.dist(hc, p) for p in points)
                            for center, r, h in eligible:
                                if not 0 <= spread < 3 * r:
                                    continue
                                hr = max(0.60 * r, spread + 0.35 * r)
                                measured = math.dist(point, hc) - hr
                                head_gap = (
                                    measured
                                    if head_gap is None
                                    else min(head_gap, measured)
                                )
                                gap = min(gap, measured)
                            report["head_landmark_batches"] = (
                                report.get("head_landmark_batches", 0) + 1
                            )
                        else:
                            report["head_landmark_skips"] = (
                                report.get("head_landmark_skips", 0) + 1
                            )
                    except Exception:
                        report["geometry_read_skips"] = (
                            report.get("geometry_read_skips", 0) + 1
                        )
                hide = gap < 35 if index in st.hidden_owned else gap <= 15
                if hide:
                    desired[index] = v
                if hide != (index in st.hidden_owned):
                    report["visibility_events"].append(
                        dict(
                            frame=st.frames,
                            index=index,
                            path=v["path"],
                            hidden=hide,
                            gap=gap if math.isfinite(gap) else None,
                            head_gap=head_gap,
                        )
                    )
            reconcile_visibility(desired)
            st.visibility = {
                i: g
                for i, g in st.visibility.items()
                if i in st.targets or i in st.hidden_owned
            }

        st.visibility_cleanup = lambda: reconcile_visibility({})
        discover("OakCharacter")
        discover("OakDecoCharacter")
        publish_live()

        def frame(*args):
            if not st.active:
                return
            try:
                if struct.unpack_from("<Q", control, 16)[0] != 0:
                    report["publication_deferrals"] = (
                        report.get("publication_deferrals", 0) + 1
                    )
                    return
                struct.pack_into("<Q", control, 48, 0)
                t = time.perf_counter()
                st.callbacks = getattr(st, "callbacks", 0) + 1
                gate, detail = assess()
                if gate == "stop":
                    stop(detail)
                    return
                live_runtime = struct.unpack("<Q", read(identity[2] + 0x3A48, 8))[0]
                sdk_ffyl = gate == "active" and detail.startswith("FFYL:")
                changed = (gate, sdk_ffyl) != (
                    st.gate,
                    getattr(st, "sdk_ffyl", False),
                ) or (
                    gate == "active"
                    and not sdk_ffyl
                    and live_runtime != st.bound_runtime
                )
                st.sdk_ffyl = sdk_ffyl
                if changed:
                    struct.pack_into("<I", control, 0, 0)
                    if gate == "pause":
                        reconcile_visibility({})
                    elif sdk_ffyl:
                        # FFYL has no native TPS collision producer. Keep the
                        # native filter disabled; the owned SDK sweep uses provider.
                        struct.pack_into("<Q", control, 40, 0)
                        st.bound_runtime = 0
                        discover("OakCharacter")
                        discover("OakDecoCharacter")
                    else:
                        receiver_now = bind_receiver()
                        if receiver_now is None:
                            gate = "pause"
                            detail += ":producer_pending"
                            reconcile_visibility({})
                        else:
                            report["receiver"] = hex(receiver_now)
                            discover("OakCharacter")
                            discover("OakDecoCharacter")
                    st.gate = gate
                    report["ads_gate_events"].append(
                        dict(frame=st.frames, state=gate, detail=detail)
                    )
                if (gate, detail) != getattr(st, "last_detail", None):
                    report["lifecycle_events"].append(
                        dict(
                            frame=st.frames,
                            state=gate,
                            detail=detail,
                            runtime=hex(live_runtime),
                        )
                    )
                    st.last_detail = (gate, detail)
                    logging.info(
                        f"{TAG} ROUTE state={gate} detail={detail} actors={len(st.targets)}"
                    )
                if gate == "pause":
                    struct.pack_into("<I", control, 0, 0)
                    reconcile_visibility({})
                    return
                st.frames += 1
                if st.frames % 30 == 0:
                    family = ("OakCharacter", "OakDecoCharacter")[st.discovery_class]
                    discover(family)
                    st.discovery_class = 1 - st.discovery_class
                publish_live()
                struct.pack_into("<I", control, 0, 0 if sdk_ffyl else 1)
                update_visibility()
                cost("steady_with_discovery_and_visibility", t)
                struct.pack_into(
                    "<Q", control, 24, struct.unpack_from("<Q", control, 24)[0] + 1
                )
            except Exception as exc:
                report["errors"].append("Frame: " + repr(exc))
                mod._npc_camera_visibility_fault = True
                stop("frame_failed")

        st.tick = frame

        def filterbuild(stub, trampoline):
            code = OBSERVER.replace(
                b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control))
            ).replace(b"\x33" * 8, struct.pack("<Q", trampoline))
            return None, control, code

        def camerabuild(stub, trampoline):
            code = WRAP.replace(
                b"\x22" * 8, struct.pack("<Q", ctypes.addressof(control))
            ).replace(b"\x33" * 8, struct.pack("<Q", trampoline))
            return None, control, code

        for rva, original, builder in (
            (0x23B4E, FILTER_ORIGINAL, filterbuild),
            (0x1873BD8, CAM_ORIGINAL, camerabuild),
        ):
            if read(base + rva, len(original)) != original:
                raise RuntimeError("Entry changed")
            h = mod._native_allocate_hook(
                base + rva,
                original,
                len(original),
                builder,
                "Character camera collision exclusion",
            )
            st.hooks.append(h)
            if read(h["target"], len(original)) != h["patch"]:
                raise RuntimeError("Installed patch differs")
        struct.pack_into("<I", control, 4, 1)
        struct.pack_into("<I", control, 0, 1)
        report["native_patches"] = len(st.hooks)
        logging.info(
            f"{TAG} READY native_patches={len(st.hooks)} actors={len(st.targets)} ffyl_ignore_provider=True"
        )
    except Exception as exc:
        report["errors"].append("Setup: " + repr(exc))
        mod._npc_camera_visibility_fault = True
        stop("setup_failed")
