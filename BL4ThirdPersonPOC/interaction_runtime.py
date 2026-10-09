"""Manage prompt-query publication and guarded NPC eligibility patches.

The loader owns prompt/NPC state. Prompt PRE publishes a bounded camera query
snapshot; native consumers retain normal Use/range decisions. Restore dependent
placeable/NPC consumers before retiring the prompt infrastructure they reference.
Disable publication, prove SDK hook removal and compare patch/original bytes
before release. Failed restoration retains pins in quarantine, not a freed stub.
The SDK baseline trace is injected to keep geometry and native ownership separate.
"""

from __future__ import annotations

from typing import Any


def _interaction_prompt_trace_base_impl(
    *, owner_module
) -> tuple[tuple[float, float, float], str, str]:
    from . import placeable_targeting

    def baseline():
        return owner_module._interaction_prompt_trace_base_core(
            _get_runtime=owner_module._get_runtime,
            _get_tps_crosshair_screen=owner_module._get_tps_crosshair_screen,
            _make_vector=owner_module._make_vector,
            INTERACTION_TRACE_DISTANCE=owner_module.INTERACTION_TRACE_DISTANCE,
        )

    return placeable_targeting.trace_candidates(owner_module, baseline)


def _interaction_prompt_trace_impl(
    *, owner_module
) -> tuple[tuple[float, float, float], str, str]:
    return owner_module._interaction_prompt_trace_core(
        _npc_eligible_state=owner_module._npc_eligible_state,
        _third_person_enabled=owner_module._third_person_enabled,
        _ads_active=owner_module._ads_active,
        _interaction_prompt_trace_base=owner_module._interaction_prompt_trace_base,
        _get_runtime=owner_module._get_runtime,
        _get_tps_crosshair_screen=owner_module._get_tps_crosshair_screen,
        _make_vector=owner_module._make_vector,
        NPC_ELIGIBLE_CANDIDATE_OFFSET=owner_module.NPC_ELIGIBLE_CANDIDATE_OFFSET,
        _native_require_readable=owner_module._native_require_readable,
        _native_read=owner_module._native_read,
        _get_actor_eye_location=owner_module._get_actor_eye_location,
    )


def _retire_npc_eligible_stub_impl(state: dict[str, Any], *, owner_module) -> None:
    if not state.get("restored"):
        raise RuntimeError("Cannot retire an unrestored NPC candidate patch")
    stub = int(state.get("stub", 0))
    if stub:
        owner_module._retired_native_stubs.append(
            ("npc", stub, state["flags"], state["candidate_slot"])
        )
        state["stub"] = 0


def _restore_owned_query_bytes_impl(
    state: dict, original: bytes, *, owner_module
) -> None:
    """Restore only our patch and grant release only after verified original bytes.

    Caller proves state ownership before invoking this helper. Foreign bytes are
    never overwritten. A failed read/write/readback clears restoration evidence;
    shutdown/quarantine retains backing storage until a later verified retry.
    """
    state["restored"] = False
    original = bytes(original)
    patch = bytes(state["patch"])
    if not original or len(patch) != len(original):
        raise RuntimeError("Query restoration byte lengths differ")
    target = int(state["target"])
    current = owner_module._native_read(target, len(original))
    if current == patch:
        owner_module._native_write_code(target, original)
        if owner_module._native_read(target, len(original)) != original:
            raise RuntimeError("Query restoration readback differs; storage retained")
    elif current != original:
        raise RuntimeError("Query restoration refused; foreign bytes at owned site")
    state["restored"] = True


def _remove_npc_eligible_impl(*, report: bool = True, owner_module) -> None:
    state = owner_module._npc_eligible_state
    if not isinstance(state, dict):
        return
    if owner_module._active_native_state.get("npc") is not state:
        owner_module._npc_eligible_state = None
        return
    owner_module._npc_reset_tracking(state)
    state["ready"] = False
    try:
        _restore_owned_query_bytes_impl(
            state, owner_module.NPC_ELIGIBLE_ORIGINAL, owner_module=owner_module
        )
        owner_module._retire_npc_eligible_stub(state)
    except Exception as exc:
        owner_module._quarantine_native_patch(
            "npc", state, "restore_or_retire_incomplete"
        )
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] NPC_ELIGIBLE_CLEANUP_ERROR "
            f"{type(exc).__name__}: {exc}"
        )
    if report:
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] NPC_ELIGIBLE_SUMMARY "
            f"on_npc={state['on_npc']}, off_npc={state['off_npc']}, "
            f"activations={state['activations']}, inactive_frames={state['inactive_frames']}, "
            f"pawn_resets={state['pawn_resets']}, errors={state['errors']}, "
            f"restored={state['restored']}"
        )
    owner_module._npc_eligible_state = None
    if owner_module._active_native_state.get("npc") is state:
        owner_module._active_native_state.pop("npc", None)


def _install_npc_eligible_impl(*, owner_module) -> None:
    if isinstance(owner_module._npc_eligible_state, dict):
        return
    if not isinstance(
        owner_module._interaction_prompt_state, dict
    ) or not owner_module._interaction_prompt_state.get("ready"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] NPC eligible targeting unavailable: native prompt not ready"
        )
        return
    if not owner_module._retry_native_patch_quarantine(kind="npc"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] NPC eligible targeting refused: old patch quarantined"
        )
        return
    state = None
    try:
        base = int(owner_module._kernel32.GetModuleHandleW(None) or 0)
        if not base or owner_module._native_read(base, 2) != b"MZ":
            raise RuntimeError("Game module unavailable")
        pe = owner_module.struct.unpack(
            "<I", owner_module._native_read(base + 0x3C, 4)
        )[0]
        if pe >= 0x1000 or owner_module._native_read(base + pe, 4) != b"PE\0\0":
            raise RuntimeError("Unexpected PE header")
        stamp = owner_module.struct.unpack(
            "<I", owner_module._native_read(base + pe + 8, 4)
        )[0]
        if stamp != owner_module.NPC_ELIGIBLE_BUILD:
            raise RuntimeError(f"PE timestamp mismatch: 0x{stamp:08X}")
        target = base + owner_module.NPC_ELIGIBLE_RVA
        if (
            owner_module._native_read(target, len(owner_module.NPC_ELIGIBLE_ORIGINAL))
            != owner_module.NPC_ELIGIBLE_ORIGINAL
        ):
            raise RuntimeError("NPC candidate site fingerprint differs")
        if len(owner_module.NPC_ELIGIBLE_STUB) != 112 or any(
            owner_module.NPC_ELIGIBLE_STUB.count(bytes((value,)) * 8) != 1
            for value in (0x11, 0x22, 0x33, 0x44, 0x55)
        ):
            raise RuntimeError("NPC candidate stub fingerprint differs")
        flags = (owner_module.ctypes.c_uint64 * 3)()
        candidate_slot = owner_module.ctypes.c_uint64(0)
        stub = int(
            owner_module._kernel32.VirtualAlloc(
                None,
                0x1000,
                owner_module._MEM_COMMIT | owner_module._MEM_RESERVE,
                owner_module._PAGE_EXECUTE_READWRITE,
            )
            or 0
        )
        if not stub:
            raise RuntimeError("NPC candidate allocation failed")
        patch = owner_module._native_absolute_jump(stub) + b"\x90" * (
            len(owner_module.NPC_ELIGIBLE_ORIGINAL) - 14
        )
        state = {
            "target": target,
            "patch": patch,
            "stub": stub,
            "flags": flags,
            "candidate_slot": candidate_slot,
            "restored": False,
            "ready": False,
            "npc_ptr": 0,
            "npc_path": None,
            "pawn_ptr": 0,
            "candidate_ready": False,
            "on_npc": 0,
            "off_npc": 0,
            "activations": 0,
            "inactive_frames": 0,
            "pawn_resets": 0,
            "errors": 0,
        }
        owner_module._npc_eligible_state = state
        owner_module._active_native_state["npc"] = state
        payload = (
            owner_module.NPC_ELIGIBLE_STUB.replace(
                b"\x11" * 8,
                owner_module.struct.pack("<Q", owner_module.ctypes.addressof(flags)),
            )
            .replace(
                b"\x55" * 8,
                owner_module.struct.pack(
                    "<Q",
                    owner_module.ctypes.addressof(
                        owner_module._interaction_prompt_state["control"]
                    ),
                ),
            )
            .replace(
                b"\x22" * 8,
                owner_module.struct.pack(
                    "<Q", owner_module.ctypes.addressof(candidate_slot)
                ),
            )
            .replace(
                b"\x33" * 8,
                owner_module.struct.pack(
                    "<Q", base + owner_module.NPC_ELIGIBLE_CONTINUATION_RVA
                ),
            )
            .replace(
                b"\x44" * 8,
                owner_module.struct.pack(
                    "<Q", target + len(owner_module.NPC_ELIGIBLE_ORIGINAL)
                ),
            )
        )
        owner_module.ctypes.memmove(stub, payload, len(payload))
        if not owner_module._kernel32.FlushInstructionCache(
            owner_module._kernel32.GetCurrentProcess(),
            owner_module.ctypes.c_void_p(stub),
            len(payload),
        ):
            raise RuntimeError("NPC candidate instruction-cache flush failed")
        owner_module._native_write_code(target, patch)
        state["ready"] = True
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] NPC eligible targeting ready; native range retained"
        )
    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] NPC eligible targeting disabled: "
            f"{type(exc).__name__}: {exc}"
        )
        if state is not None:
            owner_module._remove_npc_eligible(report=False)


def _interaction_prompt_update_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    from . import placeable_targeting

    # Never carry a prior TPS snapshot into a disabled/failed prompt frame.
    placeable_targeting.suspend(owner_module)
    try:
        return owner_module._interaction_prompt_update_hook_core(
            obj,
            args,
            ret,
            func,
            _interaction_prompt_state=owner_module._interaction_prompt_state,
            _item_card_should_override=owner_module._item_card_should_override,
            _interaction_prompt_trace=owner_module._interaction_prompt_trace,
            INTERACTION_PROMPT_NATIVE_RAY_LENGTH=owner_module.INTERACTION_PROMPT_NATIVE_RAY_LENGTH,
        )
    finally:
        prompt = owner_module._interaction_prompt_state
        if not prompt or not prompt.get("active"):
            placeable_targeting.suspend(owner_module)


def _install_interaction_prompt_targeting_impl(*, owner_module) -> None:
    """Install the guarded prompt shim and its existing SDK PRE publisher.

    The double-buffered query snapshot and control remain pinned while native
    consumers can reference them. Partial installation uses owned-byte rollback
    or quarantine; native FPS and alternate camera routes keep baseline behavior.
    """
    if isinstance(owner_module._interaction_prompt_state, dict):
        return
    # The prior module's identifier must be gone before rebinding an RLM
    # callback. A false return from add_hook alone does not prove failure:
    # some Oak2 hook-manager builds append to an existing PRE collection but
    # return false from that insertion branch.
    if owner_module.has_hook(
        owner_module.FIRST_PERSON_ANIM_HOOK,
        owner_module.Type.PRE,
        owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
    ):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Native TPS prompt targeting disabled: "
            "prompt PRE identifier survived SDK hook reconciliation"
        )
        return
    if not owner_module._retry_native_patch_quarantine(kind="prompt"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Native TPS prompt targeting disabled: "
            "an older native patch remains quarantined"
        )
        return
    state: dict[str, Any] | None = None
    try:
        module_base = int(owner_module._kernel32.GetModuleHandleW(None) or 0)
        if not module_base:
            raise RuntimeError("Could not resolve main module base")
        target = module_base + owner_module.INTERACTION_PROMPT_TARGET_RVA
        original = owner_module._native_read(
            target, owner_module.INTERACTION_PROMPT_HOOK_LENGTH
        )
        if original != owner_module.INTERACTION_PROMPT_TARGET_PREFIX:
            raise RuntimeError(
                "Prompt-query prefix mismatch: "
                f"expected={owner_module.INTERACTION_PROMPT_TARGET_PREFIX.hex(' ')}, "
                f"actual={original.hex(' ')}"
            )
        safety = owner_module._native_read(
            module_base + owner_module.INTERACTION_PROMPT_SAFETY_WINDOW_RVA,
            len(owner_module.INTERACTION_PROMPT_SAFETY_WINDOW),
        )
        if safety != owner_module.INTERACTION_PROMPT_SAFETY_WINDOW:
            raise RuntimeError(
                "Prompt-query safety-window mismatch: " f"actual={safety.hex(' ')}"
            )

        control = owner_module._INTERACTION_PROMPT_CONTROL()
        counter = owner_module.ctypes.c_uint64(0)
        point_a = (owner_module.ctypes.c_double * 6)(
            0.0,
            0.0,
            0.0,
            owner_module.INTERACTION_PROMPT_NATIVE_RAY_LENGTH,
            180.0 / owner_module.math.pi,
            360.0,
        )
        point_b = (owner_module.ctypes.c_double * 6)(
            0.0,
            0.0,
            0.0,
            owner_module.INTERACTION_PROMPT_NATIVE_RAY_LENGTH,
            180.0 / owner_module.math.pi,
            360.0,
        )
        point_buffers = (point_a, point_b)
        point_pointer = owner_module.ctypes.c_uint64(
            owner_module.ctypes.addressof(point_a)
        )
        stub = int(
            owner_module._kernel32.VirtualAlloc(
                None,
                0x1000,
                owner_module._MEM_COMMIT | owner_module._MEM_RESERVE,
                owner_module._PAGE_EXECUTE_READWRITE,
            )
            or 0
        )
        if not stub:
            raise RuntimeError("Could not allocate prompt-query stub")
        trampoline = stub + 0x800
        patch = owner_module._native_absolute_jump(stub)
        state = {
            "ready": False,
            "active": False,
            "target": target,
            "original": original,
            "patch": patch,
            "stub": stub,
            "trampoline": trampoline,
            "control": control,
            "counter": counter,
            "point_buffers": point_buffers,
            "point_pointer": point_pointer,
            "active_point_index": 0,
            "hook_installed": False,
            "restored": False,
            "updates": 0,
            "transitions": 0,
            "update_errors": 0,
            "last_update_error": None,
            "last_hit_class": "None",
            "last_hit_path": "None",
            "last_transition": None,
        }
        owner_module._interaction_prompt_state = state
        owner_module._active_native_state["prompt"] = state
        stub_data = owner_module._interaction_prompt_build_stub(
            owner_module.ctypes.addressof(control),
            owner_module.ctypes.addressof(counter),
            owner_module.ctypes.addressof(point_pointer),
            trampoline,
        )
        trampoline_data = owner_module._native_build_trampoline(
            original,
            target + owner_module.INTERACTION_PROMPT_HOOK_LENGTH,
        )
        if len(stub_data) >= 0x800 or len(trampoline_data) >= 0x800:
            raise RuntimeError("Prompt-query stub exceeded bounded layout")
        owner_module.ctypes.memmove(stub, stub_data, len(stub_data))
        owner_module.ctypes.memmove(trampoline, trampoline_data, len(trampoline_data))
        process = owner_module._kernel32.GetCurrentProcess()
        for address, size in (
            (stub, len(stub_data)),
            (trampoline, len(trampoline_data)),
        ):
            if not owner_module._kernel32.FlushInstructionCache(
                process, owner_module.ctypes.c_void_p(address), size
            ):
                raise OSError(
                    owner_module.ctypes.get_last_error(),
                    "Prompt-query instruction-cache flush failed",
                )
        add_reported = bool(
            owner_module.add_hook(
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.PRE,
                owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
                owner_module._interaction_prompt_update_hook,
            )
        )
        installed = bool(
            owner_module.has_hook(
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.PRE,
                owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
            )
        )
        if not installed:
            raise RuntimeError("Prompt-query PRE updater was not installed")
        state["hook_installed"] = True
        if not add_reported:
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] PROMPT_PRE_HOOK_REGISTERED "
                "sdk_add_reported=False, post_add_has_hook=True"
            )
        owner_module._native_write_code(target, patch)
        state["ready"] = True
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] Native TPS prompt targeting ready; "
            f"query_rva=0x{owner_module.INTERACTION_PROMPT_TARGET_RVA:X}"
        )
    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Native TPS prompt targeting disabled: "
            f"{type(exc).__name__}: {exc}"
        )
        if isinstance(state, dict):
            state["control"].enabled = 0
            if state.get("hook_installed"):
                try:
                    owner_module.remove_hook(
                        owner_module.FIRST_PERSON_ANIM_HOOK,
                        owner_module.Type.PRE,
                        owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
                    )
                    state["hook_installed"] = False
                except Exception as cleanup_exc:
                    owner_module.logging.error(
                        "[BL4ThirdPersonPOC] Prompt install rollback hook "
                        f"failure: {type(cleanup_exc).__name__}: {cleanup_exc}"
                    )
            try:
                current = owner_module._native_read(
                    int(state["target"]),
                    owner_module.INTERACTION_PROMPT_HOOK_LENGTH,
                )
                if current == bytes(state["patch"]):
                    owner_module._native_write_code(
                        int(state["target"]), bytes(state["original"])
                    )
                    state["restored"] = True
                elif current == bytes(state["original"]):
                    state["restored"] = True
            except Exception:
                pass
            if state.get("restored") and not state.get("hook_installed"):
                owner_module._retire_prompt_stub(state)
            if (
                state.get("hook_installed")
                or not state.get("restored")
                or int(state.get("stub", 0))
            ):
                owner_module._quarantine_native_patch(
                    "prompt", state, "install_rollback_incomplete"
                )
        owner_module._interaction_prompt_state = None
        if (
            state is not None
            and owner_module._active_native_state.get("prompt") is state
        ):
            owner_module._active_native_state.pop("prompt", None)


def _remove_prompt_update_hook_impl(state: dict, *, owner_module) -> None:
    """Verify SDK callback removal before allowing prompt storage retirement.

    Used by both initial shutdown and quarantine retry. Unknown registration
    retains the live-hook flag and raises; it never grants release permission.
    """
    # A reload can lose the Python registration flag. Verify the stable PRE
    # identifier before retiring storage referenced by its callback closure.
    try:
        registered = owner_module.has_hook(
            owner_module.FIRST_PERSON_ANIM_HOOK,
            owner_module.Type.PRE,
            owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
        )
        if registered or state.get("hook_installed"):
            owner_module.remove_hook(
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.PRE,
                owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
            )
        if owner_module.has_hook(
            owner_module.FIRST_PERSON_ANIM_HOOK,
            owner_module.Type.PRE,
            owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
        ):
            raise RuntimeError("Prompt updater hook remains registered")
        state["hook_installed"] = False
    except Exception as exc:
        # Unknown registration is treated as still live; quarantine pins state.
        state["hook_installed"] = True
        raise


def _remove_interaction_prompt_targeting_impl(
    *, report: bool = True, owner_module
) -> None:
    """Stop dependent NPC/prompt publication before restoring the owned query shim.

    SDK removal and native readback are separate proofs. Retirement is allowed
    only after both succeed; failures retain state for quarantine recovery.
    """
    state = owner_module._interaction_prompt_state
    if not isinstance(state, dict):
        return
    if owner_module._active_native_state.get("prompt") is not state:
        owner_module._interaction_prompt_state = None
        return  # A different module instance already retired this owner.
    failures: list[Exception] = []
    state["control"].enabled = 0
    state["active"] = False
    try:
        _remove_prompt_update_hook_impl(state, owner_module=owner_module)
    except Exception as exc:
        failures.append(exc)
    try:
        _restore_owned_query_bytes_impl(
            state, state["original"], owner_module=owner_module
        )
    except Exception as exc:
        failures.append(exc)
    if report:
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] PROMPT_TARGET_SUMMARY "
            f"native_calls={int(state['counter'].value)}, "
            f"updates={state['updates']}, "
            f"transitions={state['transitions']}, "
            f"update_errors={state['update_errors']}, "
            f"last_class={state['last_hit_class']!r}, "
            f"last_path={state['last_hit_path']}"
        )
        if state.get("last_update_error"):
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] Last prompt-target update error: "
                f"{state['last_update_error']}"
            )
    if state.get("restored") and not state.get("hook_installed"):
        try:
            owner_module._retire_prompt_stub(state)
        except Exception as exc:
            failures.append(exc)
    else:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Refusing to free unrestored " "prompt-query stub"
        )
    if (
        state.get("hook_installed")
        or not state.get("restored")
        or int(state.get("stub", 0))
    ):
        owner_module._quarantine_native_patch(
            "prompt", state, "restore_or_free_incomplete"
        )
    owner_module._interaction_prompt_state = None
    if owner_module._active_native_state.get("prompt") is state:
        owner_module._active_native_state.pop("prompt", None)
    for failure in failures:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Prompt-target cleanup failure: "
            f"{type(failure).__name__}: {failure}"
        )


def _get_tps_floor_pickup_target_impl(*, owner_module) -> Any:
    if (
        not owner_module._third_person_enabled
        or owner_module._ads_active
        or owner_module._vehicle_camera_active
        or owner_module._ladder_active
        or owner_module._shop_camera_active
    ):
        return None

    # Use the exact same native-gate-2 plus projected-OBB identity which
    # drives the full item card. This removes the old fixed 100-pixel pickup
    # radius and keeps display and Use selection on one authoritative target.
    return owner_module._get_item_card_selected_pickup()
