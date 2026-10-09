"""Initialize the existing local reticle model during confirmed TPS ADS.

The publisher is called by equip/camera events and installs no extra updater.
It verifies native code hashes, bounded model-table snapshots, local player,
weapon and route identity before writing model bytes with readback checks.
Local-PC binding is a candidate; equivalence to the native collector's virtual
and fallback routes is unproven. No model/UObject pointer is retained between
publication attempts. Crosshair presentation still requires gameplay QA.
"""


def create_publisher(mod):
    """Create a guarded publisher using the caller's current local runtime.

    Initialization checks immutable native anchors. Each publish independently
    rechecks model-table and weapon ownership; the closure retains the mod and
    WinAPI functions, not a transient reticle model or UObject.
    """
    import ctypes, struct, hashlib, json
    from ctypes import wintypes
    from unrealsdk import logging

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetModuleHandleW.restype = ctypes.c_void_p
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.ReadProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k.ReadProcessMemory.restype = wintypes.BOOL
    base = k.GetModuleHandleW(None)
    process = k.GetCurrentProcess()

    def read(addr, size):
        if not 0x10000 <= addr < 0x7FFFFFFFFFFF or not 0 < size <= 65536:
            raise RuntimeError("Read bounds refused")
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if (
            not k.ReadProcessMemory(process, addr, buf, size, ctypes.byref(got))
            or got.value != size
        ):
            raise RuntimeError(f"Read failed {addr:#x}, size={size}")
        return buf.raw

    def q(addr):
        return struct.unpack("<Q", read(addr, 8))[0]

    def i(addr):
        return struct.unpack("<i", read(addr, 4))[0]

    def is_type(obj, cls):
        if not obj or not cls:
            return False
        actual = q(obj + 0x10)
        if not actual:
            return False
        depth = i(cls + 0x38)
        actual_depth = i(actual + 0x38)
        if not 0 <= depth <= actual_depth <= 1024:
            return False
        return q(q(actual + 0x30) + depth * 8) == cls + 0x30

    for rva, size, digest in [
        (
            3862014,
            401,
            "3e29d76de88924ffae8010ec3a2dd1cc1e8936dd17ab78d7ff10e4015b3fb0b8",
        ),
        (
            9899534,
            371,
            "6425b949e8760423f4e163b1f836937c00b3f32524786a98d52427db48a58c3b",
        ),
        (
            76318096,
            2132,
            "a463ef265980420cd0b05f55e9184bf8e2356188729b4def80df7c377648effd",
        ),
    ]:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise RuntimeError(f"Native anchor mismatch {rva:#x}")

    def model_snapshot():
        pc, pawn, manager = mod._get_runtime()
        if pc is None or pawn is None or manager is None:
            raise RuntimeError("Loaded local player required")
        pc_addr = int(pc._get_address())
        # Candidate only: the native collector context uses a virtual/fallback route.
        # We do not execute or assume equivalence to that route.
        if not is_type(pc_addr, q(base + 0xCBA5CD0)):
            raise RuntimeError("Local PC fails native context class check")
        owner = q(pc_addr + 0x430)
        if not is_type(owner, q(base + 0xCAE1528)):
            raise RuntimeError("PC+0x430 fails native model-owner class check")
        key = (owner >> 4) & 0xFFFFFFFF
        key = ((key ^ (key >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        key = ((key ^ (key >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        key = (key ^ (key >> 16)) & 0xFFFFFFFF
        root = base + 0xCBCD518
        header = read(root, 0x50)
        data, n, capacity = struct.unpack_from("<Qii", header)
        free = struct.unpack_from("<i", header, 0x34)[0]
        bucket_ptr = struct.unpack_from("<Q", header, 0x40)[0]
        buckets = struct.unpack_from("<i", header, 0x48)[0]
        if (
            not 0 <= free <= n <= capacity <= 4096
            or not 0 < buckets <= 8192
            or buckets & (buckets - 1)
        ):
            raise RuntimeError(
                f"Table bounds refused: {n}/{capacity}, free={free}, buckets={buckets}"
            )
        if n == free:
            raise RuntimeError("No existing model entries")
        bucket_base = bucket_ptr or base + 0xCBCD550
        if not bucket_ptr and buckets > 2:
            raise RuntimeError("Unexpected inline hash size")
        bucket_addr = bucket_base + (key & (buckets - 1)) * 4
        first = i(bucket_addr)
        index = first
        visited = set()
        entry = None
        while index != -1:
            if not 0 <= index < n or index in visited or len(visited) >= 128:
                raise RuntimeError("Invalid or excessive hash chain")
            visited.add(index)
            candidate = read(data + index * 32, 32)
            if struct.unpack_from("<I", candidate)[0] == key:
                entry = candidate
                break
            index = struct.unpack_from("<i", candidate, 24)[0]
        if read(root, 0x50) != header or i(bucket_addr) != first:
            raise RuntimeError("Table changed during observation; result discarded")
        if entry is None:
            raise RuntimeError("Model key not found")
        container = struct.unpack_from("<Q", entry, 8)[0]
        model = q(container + 0xA0)
        raw = read(model + 0x88, 0x30)
        text_ptr, length, text_capacity, counter = struct.unpack_from(
            "<QiiI", raw, 0x18
        )
        if not 0 <= length <= text_capacity <= 4096:
            raise RuntimeError("String bounds refused")
        text_bytes = read(text_ptr, length * 2) if length else b""
        text = text_bytes.decode("utf-16-le", errors="strict").rstrip("\x00")
        if (
            read(model + 0x88, 0x30) != raw
            or q(container + 0xA0) != model
            or read(data + index * 32, 32) != entry
            or read(root, 0x50) != header
        ):
            raise RuntimeError(
                "Model or table changed during observation; result discarded"
            )
        return dict(
            index=index,
            container=hex(container),
            model=hex(model),
            byte_88=raw[0],
            counter_8c=struct.unpack_from("<I", raw, 4)[0],
            byte_90=raw[8],
            counter_94=struct.unpack_from("<I", raw, 12)[0],
            text_a0=text,
            text_length=length,
            text_counter_b0=counter,
            owner=hex(owner),
            binding="local_pc_candidate",
        )

    expected = bytes.fromhex("41 88 87 88 00 00 00 ff c1 41 89 8f 8c 00 00 00")
    if read(base + 0xFC0656, len(expected)) != expected:
        raise RuntimeError("Reticle assignment code mismatch")
    k.WriteProcessMemory.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k.WriteProcessMemory.restype = wintypes.BOOL

    def write(addr, data):
        buf = ctypes.create_string_buffer(data)
        got = ctypes.c_size_t()
        if not k.WriteProcessMemory(
            process, addr, buf, len(data), ctypes.byref(got)
        ) or got.value != len(data):
            raise RuntimeError("Reticle write failed")
        if read(addr, len(data)) != data:
            raise RuntimeError("Reticle write verification failed")

    # No more per-weapon table: BL4 already writes the correct native
    # crosshair model name (e.g. 'crosshair_ar', 'crosshair_chaingun', ...)
    # into text_a0 itself for whatever weapon is equipped. We only need to
    # confirm that whatever is there looks like a real crosshair model
    # (as opposed to an unrelated model that hashed into the same bucket),
    # not know its exact value ahead of time.
    CROSSHAIR_TEXT_PREFIX = "crosshair_"

    def addr(obj):
        return int(obj._get_address()) if obj is not None else 0

    def fail(reason):
        mod._reticle_gate_last_fail = reason
        return None

    def gate():
        state = mod._ads_tps_state
        if not (
            mod._third_person_enabled
            and mod._third_person_pushed
            and mod._ads_active
            and mod._ads_route == "tps"
            and not mod._vehicle_camera_active
            and not mod._ladder_active
            and not mod._shop_camera_active
        ):
            return fail("base_flags")
        if not (isinstance(state, dict) and state.get("phase") == "ads"):
            phase = state.get("phase") if isinstance(state, dict) else repr(state)
            return fail(f"phase={phase!r}")
        category = state.get("category")
        pc, pawn, manager = mod._get_runtime()
        if pc is None or pawn is None or manager is None:
            return fail("runtime_unavailable")
        weapon = manager.CameraModeInputs.Weapon
        wa = addr(weapon)
        if (
            not wa
            or wa != state.get("weapon_address")
            or addr(manager) != state.get("manager_address")
        ):
            return fail(
                f"weapon_or_manager_mismatch wa={wa:#x} "
                f'state_weapon={state.get("weapon_address",0):#x} '
                f'manager={addr(manager):#x} state_manager={state.get("manager_address",0):#x}'
            )
        if wa != mod._ads_handoff.get("route_weapon") or not mod._ads_collector_address:
            return fail(
                f"route_weapon_or_collector wa={wa:#x} "
                f'route_weapon={mod._ads_handoff.get("route_weapon",0):#x} '
                f"collector={mod._ads_collector_address:#x}"
            )
        if int(pawn.ZoomState.State) not in (1, 2) or q(wa + 0x1B0) != addr(pawn):
            return fail(
                f"zoom_state_or_owner zoom_state={int(pawn.ZoomState.State)} "
                f"owner_at_0x1B0={q(wa+0x1B0):#x} pawn={addr(pawn):#x}"
            )
        raw = read(wa + 0xD2A, 0x3E)
        value = struct.unpack_from("<Q", raw, 0x36)[0]
        ga, gb = struct.unpack("<QQ", read(base + 0xCB8CD70, 16))
        if raw[0] != 1 or value in (ga, gb):
            return fail(
                f"weapon_not_ready byte_d2a={raw[0]!r} value_d60={value:#x} "
                f"ga={ga:#x} gb={gb:#x}"
            )
        mod._reticle_gate_last_fail = ""
        return (
            addr(pc),
            addr(pawn),
            addr(manager),
            wa,
            category,
            int(mod._ads_collector_address),
        )

    def publish():
        identity = gate()
        if identity is None:
            return {"status": "gate_skipped"}
        before = model_snapshot()
        if (
            not before["text_a0"].startswith(CROSSHAIR_TEXT_PREFIX)
            or before["byte_90"] != 0
        ):
            logging.info(
                f"[BL4ThirdPersonPOC] TPS_RETICLE_UNEXPECTED_MODEL_TEXT "
                f"category={identity[4]!r}, real_text={before['text_a0']!r}, "
                f"byte_90={before['byte_90']!r}"
            )
            return {"status": "model_mismatch"}
        if before["byte_88"] == 1:
            return {"status": "already_visible"}
        if before["byte_88"] != 0:
            return {"status": "unexpected_value"}
        if gate() != identity or model_snapshot() != before:
            return {"status": "unstable_snapshot"}
        model = int(before["model"], 16)
        counter = before["counter_8c"]
        next_counter = (counter + 1) & 0xFFFFFFFF
        try:
            write(model + 0x88, b"\x01")
            write(model + 0x8C, struct.pack("<I", next_counter))
        except Exception:
            # Best-effort repair only while identity and model ownership match.
            current = model_snapshot()
            if (
                gate() == identity
                and current["model"] == before["model"]
                and current["text_a0"] == before["text_a0"]
                and current["byte_88"] == 1
                and current["counter_8c"] in (counter, next_counter)
            ):
                write(model + 0x88, b"\x00")
                write(
                    model + 0x8C,
                    struct.pack("<I", (current["counter_8c"] + 1) & 0xFFFFFFFF),
                )
            raise
        after = model_snapshot()
        if (
            after["model"] != before["model"]
            or after["byte_88"] != 1
            or after["counter_8c"] != next_counter
        ):
            raise RuntimeError("Reticle publication changed before verification")
        return {
            "status": "published",
            "weapon": hex(identity[3]),
            "model": before["model"],
            "before": 0,
            "after": 1,
            "counter": next_counter,
            "category": identity[4],
        }

    def observe():
        """Read the validated local reticle model for explicit QA snapshots.

        No publication, new native calls, or retained model pointers. These
        bytes are observations, not assumed crosshair-size fields.
        """
        pc, pawn, manager = mod._get_runtime()
        if pc is None or pawn is None or manager is None:
            raise RuntimeError("Loaded local player required")
        identity = tuple(
            addr(x) for x in (pc, pawn, manager, manager.CameraModeInputs.Weapon)
        )
        before = model_snapshot()
        if not before["text_a0"].startswith(CROSSHAIR_TEXT_PREFIX):
            raise RuntimeError("Local model is not a crosshair")
        raw = read(int(before["model"], 16) + 0x88, 0x30)
        after = model_snapshot()
        current = tuple(
            addr(x) for x in (pc, pawn, manager, manager.CameraModeInputs.Weapon)
        )
        if before != after or current != identity:
            raise RuntimeError("Reticle changed during QA observation")
        return dict(identity=identity, model=before, raw_88_b8=raw.hex())

    publish.observe = observe
    return publish
