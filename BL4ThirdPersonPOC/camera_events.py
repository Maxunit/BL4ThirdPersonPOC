"""Own camera-stack bookkeeping and coordinate camera-system handoffs.

The loader supplies mutable state and callback identities. Pop only a verified
owned TPS entry; retire bookkeeping for a proven empty/replaced stack instead.
Native recoil/Beam restoration precedes camera mutation. Vehicle, ladder, slide,
shop, native FPS ADS and selected FFYL transitions suppress normal TPS work.
The selected FFYL strategy owns its cycle; shared lifecycle repair must defer.
The existing camera update orders lifecycle, motion, interaction and diagnostics.
Legacy settle windows are retained; they are documented as a policy exception.
"""

from __future__ import annotations

import struct
import time
from typing import Any

from . import ads_zoom_modifiers
from . import hybrid_ads
from . import tps_recovery
from unrealsdk import logging
from unrealsdk.hooks import Type, add_hook, remove_hook


# Camera stack ownership and lifecycle state; loader remains the owner.
def _persist_camera_stack_owner_impl(*, owner_module) -> None:
    # Persist only primitive values across an Oak RLM reload. UObject wrappers
    # must never survive their world because the native object may be gone.
    snapshot = {
        key: value
        for key, value in owner_module._camera_stack_owner.items()
        if isinstance(value, (bool, int, float, str)) or value is None
    }
    setattr(owner_module.builtins, owner_module.CAMERA_STACK_PERSIST_NAME, snapshot)


def _record_camera_stack_owner_impl(
    pawn: Any, camera_manager: Any, *, owner_module
) -> None:
    owner_module._third_person_pushed = True
    owner_module._camera_stack_owner.update(
        {
            "owned": True,
            "pending_pop": False,
            "pawn_address": owner_module._object_address(pawn),
            "manager_address": owner_module._object_address(camera_manager),
            "reason": "",
            "pushes": int(owner_module._camera_stack_owner.get("pushes", 0)) + 1,
        }
    )
    owner_module._persist_camera_stack_owner()


def _clear_camera_stack_owner_impl(*, owner_module) -> None:
    owner_module._third_person_pushed = False
    owner_module._camera_stack_owner.update(
        {
            "owned": False,
            "pending_pop": False,
            "pawn_address": 0,
            "manager_address": 0,
            "reason": "",
            "pops": int(owner_module._camera_stack_owner.get("pops", 0)) + 1,
        }
    )
    owner_module._persist_camera_stack_owner()


def _retire_camera_stack_owner_impl(reason: str, *, owner_module) -> None:
    """Forget an entry whose owning runtime was authoritatively replaced.

    No native pop is attempted here: a camera mode owned by another pawn or
    camera manager must never be removed through the current runtime.
    """
    previous_pawn = int(owner_module._camera_stack_owner.get("pawn_address", 0))
    previous_manager = int(owner_module._camera_stack_owner.get("manager_address", 0))
    owner_module._third_person_pushed = False
    owner_module._camera_stack_owner.update(
        {
            "owned": False,
            "pending_pop": False,
            "pawn_address": 0,
            "manager_address": 0,
            "reason": "",
            "retirements": int(owner_module._camera_stack_owner.get("retirements", 0))
            + 1,
            "last_retire_reason": reason,
        }
    )
    owner_module._persist_camera_stack_owner()
    logging.warning(
        "[BL4ThirdPersonPOC] CAMERA_STACK_OWNER_RETIRED "
        f"reason={reason!r}, pawn=0x{previous_pawn:016X}, "
        f"manager=0x{previous_manager:016X}; no native pop attempted"
    )


def _defer_camera_pop_impl(reason: str, *, owner_module) -> None:
    owner_module._camera_stack_owner["owned"] = bool(
        owner_module._camera_stack_owner.get("owned")
        or owner_module._third_person_pushed
    )
    owner_module._camera_stack_owner["pending_pop"] = True
    owner_module._camera_stack_owner["reason"] = reason
    owner_module._camera_stack_owner["deferred_pops"] = (
        int(owner_module._camera_stack_owner.get("deferred_pops", 0)) + 1
    )
    owner_module._persist_camera_stack_owner()


def _retry_pending_camera_pop_impl(*, owner_module) -> bool:
    if not owner_module._camera_stack_owner.get("pending_pop"):
        return True
    owner_module._camera_stack_owner["retry_attempts"] = (
        int(owner_module._camera_stack_owner.get("retry_attempts", 0)) + 1
    )
    success = owner_module._pop_third_person(reason="deferred_retry")
    if success:
        owner_module._camera_stack_owner["retry_successes"] = (
            int(owner_module._camera_stack_owner.get("retry_successes", 0)) + 1
        )
        owner_module._persist_camera_stack_owner()
    return success


def _reset_camera_lifecycle_impl(*, owner_module) -> None:
    owner_module._camera_lifecycle = {
        "reason": None,
        "phase": "idle",
        "pending": False,
        "suppress_offsets": False,
        "expected_pawn": 0,
        "direct_default_manager": 0,
        "arrival_seen": False,
        "settled_since": None,
        "repair_done": False,
        "early_handoff_attempted": False,
        "early_handoff_started": None,
        "early_handoff_secondwind": False,
        "early_handoff_offsets_restored": False,
        "last_update": time.perf_counter(),
        "restart_calls": 0,
        "local_restarts": 0,
        "ffyl_entries": 0,
        "ffyl_direct_defaults": 0,
        "runtime_unavailable_frames": 0,
        "offset_suppressions": 0,
        "repair_attempts": 0,
        "repair_successes": 0,
        "preserved_tps": 0,
        "vehicle_discards": 0,
        "vehicle_restart_ignores": 0,
        "errors": 0,
        "last_error": "",
    }


def _arm_camera_lifecycle_impl(
    reason: str, *, expected_pawn: int = 0, owner_module
) -> None:
    owner_module._respawn_camera_state = None
    state = owner_module._camera_lifecycle
    if reason == "client_restart" and owner_module._ffyl_early_handoff_armed:
        # Death/respawn replaces the Second Wind route. Keep native resume
        # pending until this restart produces a verified owned TPS camera,
        # but do not wait for an event belonging to the retired FFYL cycle.
        owner_module._ffyl_early_handoff_armed = False
        logging.info(
            "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_SUPERSEDED_BY_RESTART "
            f"native_resume_pending={owner_module._ffyl_native_resume_pending}"
        )
    state["reason"] = reason
    state["phase"] = "awaiting_arrival" if reason == "client_restart" else "ffyl"
    state["pending"] = True
    state["suppress_offsets"] = reason == "ffyl"
    state["expected_pawn"] = int(expected_pawn)
    state["direct_default_manager"] = 0
    state["arrival_seen"] = reason == "ffyl"
    state["settled_since"] = None
    state["repair_done"] = False
    state["early_handoff_attempted"] = False
    state["early_handoff_started"] = None
    state["early_handoff_secondwind"] = False
    state["early_handoff_offsets_restored"] = False
    logging.info(
        "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_ARMED "
        f"reason={reason!r}, expected_pawn=0x{int(expected_pawn):016X}"
    )


def _discard_camera_lifecycle_impl(reason: str, *, owner_module) -> bool:
    state = owner_module._camera_lifecycle
    if not state.get("pending"):
        return False
    previous_reason = state.get("reason")
    state["pending"] = False
    state["suppress_offsets"] = False
    state["expected_pawn"] = 0
    state["direct_default_manager"] = 0
    state["arrival_seen"] = False
    state["settled_since"] = None
    state["repair_done"] = False
    state["phase"] = f"discarded:{reason}"
    if reason.startswith("vehicle"):
        state["vehicle_discards"] = int(state.get("vehicle_discards", 0)) + 1
    logging.info(
        "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_DISCARDED "
        f"reason={reason!r}, previous_reason={previous_reason!r}"
    )
    return True


def _camera_lifecycle_offset_suppressed_impl(*, owner_module) -> bool:
    state = owner_module._camera_lifecycle
    suppressed = bool(state.get("suppress_offsets", False)) or (
        state.get("phase") == "repairing"
    )
    if suppressed:
        state["offset_suppressions"] = int(state.get("offset_suppressions", 0)) + 1
    return suppressed


# FFYL and ClientRestart events; registered by loader in original order.
def _remove_ffyl_early_handoff_hook_impl(*, owner_module) -> None:
    if owner_module._ffyl_early_handoff_hook_installed:
        remove_hook(
            owner_module.FFYL_EARLY_ENDED_FUNCTION,
            Type.PRE,
            owner_module.FFYL_EARLY_ENDED_IDENTIFIER,
        )
        owner_module._ffyl_early_handoff_hook_installed = False


def _install_ffyl_early_handoff_hook_impl(*, owner_module) -> None:
    try:
        remove_hook(
            owner_module.FFYL_EARLY_ENDED_FUNCTION,
            Type.PRE,
            owner_module.FFYL_EARLY_ENDED_IDENTIFIER,
        )
    except Exception:
        pass
    owner_module._ffyl_early_handoff_hook_installed = False
    try:
        # Oak2 may return False although the callback becomes observable.
        add_hook(
            owner_module.FFYL_EARLY_ENDED_FUNCTION,
            Type.PRE,
            owner_module.FFYL_EARLY_ENDED_IDENTIFIER,
            owner_module._ffyl_early_ended_pre_hook,
        )
        owner_module._ffyl_early_handoff_hook_installed = True
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] FFYL_EARLY_EVENT_HOOK_UNAVAILABLE "
            f"{type(exc).__name__}: {exc}"
        )


def _ffyl_early_ended_pre_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, *, owner_module
) -> None:
    from . import ffyl_strategy_runtime

    if ffyl_strategy_runtime.controls_transition(owner_module):
        return
    if (
        not owner_module._ffyl_early_handoff_armed
        or not owner_module._camera_lifecycle.get("pending")
    ):
        return
    try:
        _pc, pawn, manager = owner_module._get_runtime()
        if (
            pawn is None
            or manager is None
            or str(manager.GetActorCameraMode(pawn)) != "FFYL"
        ):
            return
        exit_reason = str(getattr(args, "Reason", ""))
        if (
            exit_reason == "2" or "SecondWind" in exit_reason
        ) and not owner_module._camera_lifecycle.get("early_handoff_secondwind"):
            owner_module._camera_lifecycle["early_handoff_secondwind"] = True
            logging.warning("[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_SECOND_WIND_SEEN")
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_EVENT_ERROR "
            f"{type(exc).__name__}: {exc}"
        )


def _client_restart_pre_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, *, owner_module
) -> None:
    """Restore the player's native Look patch before pawn/camera restart.

    ClientRestart POST can already see a replaced camera (vehicle or travel).
    Never touch an unknown copy once camera ownership has changed.
    """
    if not (
        owner_module._native_active()
        or owner_module._active_native_state.get("ladder_default")
    ):
        return
    try:
        pc, _pawn, _camera = owner_module._get_runtime()
        if not pc or owner_module._object_address(obj) != owner_module._object_address(
            pc
        ):
            return
        new_pawn = getattr(args, "NewPawn", None)
        if new_pawn is None:
            return
        is_vehicle = "OakVehicle" in str(new_pawn.Class.Name) or "OakVehicle" in repr(
            new_pawn
        )
        reason = "vehicle_client_restart_pre" if is_vehicle else "client_restart_pre"
        if not owner_module._native_stop(reason):
            logging.error(
                "[BL4ThirdPersonPOC] CLIENT_RESTART_NATIVE_PRE_RESTORE_FAILED; "
                "restart game before further camera tests"
            )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] CLIENT_RESTART_NATIVE_PRE_ERROR "
            f"{type(exc).__name__}: {exc}"
        )


def _ffyl_downed_pre_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, *, owner_module
) -> None:
    """Release the owned TPS Look before the local downed camera changes it."""
    from . import ffyl_strategy_runtime

    if ffyl_strategy_runtime.handles_down_state(owner_module):
        return
    if not (
        owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and (
            owner_module._native_active()
            or owner_module._active_native_state.get("ladder_default")
        )
        and not owner_module._native_ffyl_pending
    ):
        return
    try:
        _pc, pawn, camera = owner_module._get_runtime()
        if pawn is None or camera is None:
            return
        from . import native_ladder_guard

        native_ladder_guard.remove_default(owner_module, "ffyl_downed_pre")
        if str(camera.GetActorCameraMode(pawn)) != "ThirdPerson":
            return
        try:
            # Diagnostic only: compare the native stack here with the helper's
            # later snapshot. Never dereference the saved Look in this callback.
            window = owner_module._native_read(
                owner_module._object_address(camera) + 0x39A8, 0xB0
            )
            stack_data, stack_count, stack_capacity = struct.unpack_from(
                "<Qii", window, 0x18
            )
            if not 0 <= stack_count <= stack_capacity <= 64:
                raise RuntimeError("FFYL PRE stack header outside bounds")
            first_names = []
            if stack_count:
                if stack_data < 0x10000:
                    raise RuntimeError("FFYL PRE stack pointer outside bounds")
                stack_bytes = owner_module._native_read(
                    stack_data, min(stack_count, 3) * 0x28
                )
                first_names = [
                    stack_bytes[i * 0x28 : i * 0x28 + 8].hex()
                    for i in range(min(stack_count, 3))
                ]
            if (
                owner_module._native_read(
                    owner_module._object_address(camera) + 0x39A8, 0xB0
                )
                != window
            ):
                raise RuntimeError("FFYL PRE stack changed during read")
            logging.warning(
                "[BL4ThirdPersonPOC] FFYL_PRE_STACK "
                f"count={stack_count} capacity={stack_capacity} "
                f"fnames={first_names!r} current={window[0x88:0x90].hex()} "
                f'runtime={struct.unpack_from("<Q", window, 0xA0)[0]:#x} '
                "native_patches=0 diagnostic_writes=0"
            )
        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] FFYL_PRE_STACK_READ_ERROR "
                f"{type(exc).__name__}: {exc}"
            )
        if owner_module._native_stop("ffyl_downed_pre"):
            # OnDowned PRE fires before the native FFYL camera switch. The
            # ordinary camera tick can run in between; do not re-arm there.
            owner_module._native_ffyl_pending = True
            owner_module._native_ffyl_pending_pawn = owner_module._object_address(pawn)
            logging.info(
                "[BL4ThirdPersonPOC] FFYL_NATIVE_PRE_RESTORED "
                f"pawn=0x{owner_module._object_address(pawn):016X}"
            )
        else:
            logging.error(
                "[BL4ThirdPersonPOC] FFYL_NATIVE_PRE_RESTORE_FAILED; "
                "restart game before further native tests"
            )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] FFYL_NATIVE_PRE_ERROR " f"{type(exc).__name__}: {exc}"
        )


def _install_ffyl_native_pre_hook_impl(*, owner_module) -> None:
    try:
        remove_hook(
            owner_module.FFYL_DOWNED_FUNCTION,
            Type.PRE,
            owner_module.FFYL_NATIVE_PRE_IDENTIFIER,
        )
    except Exception:
        pass
    try:
        owner_module._ffyl_native_pre_installed = bool(
            add_hook(
                owner_module.FFYL_DOWNED_FUNCTION,
                Type.PRE,
                owner_module.FFYL_NATIVE_PRE_IDENTIFIER,
                owner_module._ffyl_downed_pre_hook,
            )
        )
        if not owner_module._ffyl_native_pre_installed:
            logging.error(
                "[BL4ThirdPersonPOC] FFYL native PRE hook refused; "
                "native correction will remain inactive"
            )
    except Exception as exc:
        owner_module._ffyl_native_pre_installed = False
        logging.error(
            "[BL4ThirdPersonPOC] FFYL native PRE hook failed; "
            f"native correction will remain inactive: {type(exc).__name__}: {exc}"
        )


def _remove_ffyl_native_pre_hook_impl(*, owner_module) -> None:
    if not owner_module._ffyl_native_pre_installed:
        return
    try:
        remove_hook(
            owner_module.FFYL_DOWNED_FUNCTION,
            Type.PRE,
            owner_module.FFYL_NATIVE_PRE_IDENTIFIER,
        )
        owner_module._ffyl_native_pre_installed = False
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] FFYL native PRE hook removal failed "
            f"{type(exc).__name__}: {exc}"
        )


def _client_restart_post_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, *, owner_module
) -> None:
    if isinstance(owner_module._npc_eligible_state, dict):
        owner_module._npc_reset_tracking(owner_module._npc_eligible_state)
    state = owner_module._camera_lifecycle
    state["restart_calls"] += 1
    try:
        pc, runtime_pawn, _manager = owner_module._get_runtime()
        new_pawn = getattr(args, "NewPawn", None)
        controller_local = (
            owner_module._object_address(obj) != 0
            and owner_module._object_address(pc) != 0
            and owner_module._object_address(obj) == owner_module._object_address(pc)
        )
        pawn_matches = owner_module._object_address(new_pawn) != 0 and (
            owner_module._object_address(runtime_pawn) == 0
            or owner_module._object_address(new_pawn)
            == owner_module._object_address(runtime_pawn)
        )
        logging.info(
            "[BL4ThirdPersonPOC] CLIENT_RESTART_SEEN "
            f"controller_local={controller_local} pawn_matches={pawn_matches} "
            f"tps_enabled={owner_module._third_person_enabled} "
            f"new_pawn=0x{owner_module._object_address(new_pawn):X} "
            f"runtime_pawn=0x{owner_module._object_address(runtime_pawn):X}"
        )
        if not (
            controller_local and pawn_matches and owner_module._third_person_enabled
        ):
            return
        state["local_restarts"] += 1
        if (
            owner_module._vehicle_camera_active
            or owner_module._is_vehicle_camera_view()
        ):
            state["vehicle_restart_ignores"] = (
                int(state.get("vehicle_restart_ignores", 0)) + 1
            )
            owner_module._clear_pending_ads_press("vehicle_client_restart")
            owner_module._discard_camera_lifecycle("vehicle_client_restart")
            logging.info(
                "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_RESTART_IGNORED "
                "reason='vehicle_camera'"
            )
            return
        owner_module._clear_pending_ads_press("client_restart")
        if owner_module._ads_route != "hip" or owner_module._ads_active:
            owner_module._cancel_hybrid_ads("client_restart")
        owner_module._arm_camera_lifecycle(
            "client_restart",
            expected_pawn=owner_module._object_address(new_pawn),
        )
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"client_restart: {type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] CLIENT_RESTART_RECONCILE_ERROR "
            f"{type(exc).__name__}: {exc}"
        )


def _install_camera_lifecycle_hook_impl(*, owner_module) -> None:
    if owner_module._camera_lifecycle_hook_installed:
        owner_module._remove_camera_lifecycle_hook()
    if owner_module._camera_lifecycle_hook_installed:
        logging.error(
            "[BL4ThirdPersonPOC] ClientRestart hook installation refused: "
            "older tracked hook could not be removed"
        )
        return
    try:
        remove_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.PRE,
            owner_module.CLIENT_RESTART_PRE_IDENTIFIER,
        )
    except Exception:
        pass
    try:
        remove_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.POST,
            owner_module.CLIENT_RESTART_IDENTIFIER,
        )
    except Exception:
        pass
    try:
        pre_installed = add_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.PRE,
            owner_module.CLIENT_RESTART_PRE_IDENTIFIER,
            owner_module._client_restart_pre_hook,
        )
        if not pre_installed:
            raise RuntimeError("ClientRestart PRE hook refused")
        post_installed = add_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.POST,
            owner_module.CLIENT_RESTART_IDENTIFIER,
            owner_module._client_restart_post_hook,
        )
        if not post_installed:
            raise RuntimeError("ClientRestart POST hook refused")
        owner_module._camera_lifecycle_hook_installed = True
    except Exception as exc:
        owner_module._camera_lifecycle_hook_installed = False
        try:
            remove_hook(
                owner_module.CLIENT_RESTART_FUNCTION,
                Type.PRE,
                owner_module.CLIENT_RESTART_PRE_IDENTIFIER,
            )
        except Exception:
            pass
        try:
            remove_hook(
                owner_module.CLIENT_RESTART_FUNCTION,
                Type.POST,
                owner_module.CLIENT_RESTART_IDENTIFIER,
            )
        except Exception:
            pass
        logging.error(
            "[BL4ThirdPersonPOC] Could not install ClientRestart "
            f"lifecycle hook: {type(exc).__name__}: {exc}"
        )


def _remove_camera_lifecycle_hook_impl(*, owner_module) -> None:
    if not owner_module._camera_lifecycle_hook_installed:
        return
    try:
        remove_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.PRE,
            owner_module.CLIENT_RESTART_PRE_IDENTIFIER,
        )
        remove_hook(
            owner_module.CLIENT_RESTART_FUNCTION,
            Type.POST,
            owner_module.CLIENT_RESTART_IDENTIFIER,
        )
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not remove ClientRestart "
            f"lifecycle hook: {type(exc).__name__}: {exc}"
        )
        return
    owner_module._camera_lifecycle_hook_installed = False


# Camera lifecycle tick uses live loader state and original event sequence.
def _update_camera_lifecycle_impl(*, owner_module) -> None:
    from . import ffyl_strategy_runtime

    if ffyl_strategy_runtime.controls_transition(owner_module):
        return
    state = owner_module._camera_lifecycle
    if not state:
        return

    # A refused native restore leaves an owned Look copy whose current
    # camera ownership is unknown. Repeating repair cannot make it safer;
    # it only scans memory and floods the log every settled frame.
    if (
        state.get("pending")
        and owner_module._native_fault
        and owner_module._native_active()
    ):
        if state.get("phase") != "native_restore_blocked":
            state["phase"] = "native_restore_blocked"
            state["suppress_offsets"] = True
            logging.error(
                "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_NATIVE_BLOCKED "
                "native restore unverified; restart game"
            )
        return

    now = time.perf_counter()
    frame_gap = now - float(state.get("last_update", now))
    state["last_update"] = now

    # ClientRestart is also used for vehicle possession.  While BL4 owns the
    # vehicle camera, lifecycle reconciliation must never touch the shared
    # CameraModeState or push the character's ThirdPerson mode.
    if owner_module._vehicle_camera_active:
        if state.get("reason") == "client_restart":
            owner_module._discard_camera_lifecycle("vehicle_active")
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        if state.get("pending"):
            state["runtime_unavailable_frames"] += 1
            state["suppress_offsets"] = True
        return

    if (
        state.get("pending")
        and state.get("direct_default_manager")
        and (
            owner_module._object_address(pawn) != int(state.get("expected_pawn", 0))
            or owner_module._object_address(camera_manager)
            != int(state["direct_default_manager"])
        )
    ):
        owner_module._discard_camera_lifecycle("direct_default_identity_changed")
        return

    try:
        from . import respawn_camera
        if respawn_camera.update(owner_module):
            return
        mode = str(camera_manager.GetActorCameraMode(pawn))
        transitioning = bool(camera_manager.CameraModeState.bIsTransitioning)
        try:
            attach = str(camera_manager.CameraModeInputs.AttachComponent.Name)
        except Exception:
            attach = repr(
                getattr(camera_manager.CameraModeInputs, "AttachComponent", None)
            )

        if mode == "FFYL" and owner_module._third_person_enabled:
            if state.get("reason") != "ffyl" or not state.get("pending"):
                if owner_module._ads_route != "hip" or owner_module._ads_active:
                    owner_module._cancel_hybrid_ads("ffyl_enter")
                else:
                    owner_module._clear_pending_ads_press("ffyl_enter")
                state["ffyl_entries"] += 1
                owner_module._arm_camera_lifecycle("ffyl")
            if (
                owner_module._ffyl_early_auto_enabled
                and owner_module._ffyl_early_handoff_hook_installed
                and not owner_module._ffyl_early_handoff_armed
                and not state.get("early_handoff_attempted")
                and not owner_module._ffyl_native_resume_pending
                and not owner_module._native_fault
                and not owner_module._native_active()
            ):
                owner_module._ffyl_native_resume_pending = bool(
                    owner_module._native_auto_enabled
                )
                owner_module._native_auto_enabled = False
                owner_module._ffyl_early_handoff_armed = True
                logging.info(
                    "[BL4ThirdPersonPOC] FFYL_EARLY_AUTO_ARMED "
                    f"native_resume_pending={owner_module._ffyl_native_resume_pending}"
                )
            state["suppress_offsets"] = True
            state["settled_since"] = None
            return

        if not state.get("pending") or state.get("repair_done"):
            return

        reason = str(state.get("reason"))
        pawn_address = owner_module._object_address(pawn)
        if reason == "client_restart":
            expected = int(state.get("expected_pawn", 0))
            if expected and pawn_address and pawn_address != expected:
                state["expected_pawn"] = pawn_address
                logging.info(
                    "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_PAWN_CHANGED "
                    f"pawn=0x{pawn_address:016X}"
                )
            if mode != "ThirdPerson" or (
                frame_gap >= owner_module.CAMERA_LIFECYCLE_ARRIVAL_GAP_SECONDS
            ):
                state["arrival_seen"] = True
            if not state.get("arrival_seen"):
                return
            if mode == "ThirdPerson" and attach == "CharacterMesh":
                state["pending"] = False
                state["suppress_offsets"] = False
                state["phase"] = "tps_preserved"
                state["preserved_tps"] += 1
                logging.info(
                    "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_TPS_PRESERVED "
                    "after ClientRestart"
                )
                return

        # Single-use camera handoff: BL4 has already discarded FFYL and its
        # owned stack. Never attempt this while a native Look copy is live.
        if (
            reason == "ffyl"
            and owner_module._ffyl_early_handoff_armed
            and mode == "Default"
        ):
            owner_module._ffyl_early_handoff_armed = False
            if not state.get("early_handoff_secondwind"):
                logging.warning(
                    "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_SKIPPED "
                    "no local Second Wind event"
                )
            elif not transitioning:
                logging.warning(
                    "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_SKIPPED "
                    "Default transition already finished"
                )
            elif (
                owner_module._native_auto_enabled
                or owner_module._native_active()
                or owner_module._native_fault
                or owner_module._ads_active
                or owner_module._vehicle_camera_active
                or owner_module._ladder_active
            ):
                logging.warning(
                    "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_REFUSED "
                    "native or alternate camera route is active"
                )
            else:
                try:
                    if not owner_module._ffyl_camera_stack_empty(camera_manager):
                        raise RuntimeError("Default camera stack is not empty")
                    owner_module._retire_camera_stack_owner(
                        "ffyl_early_default_empty_stack"
                    )
                    state["early_handoff_attempted"] = True
                    state["early_handoff_started"] = now
                    state["phase"] = "early_handoff_pushing"
                    state["suppress_offsets"] = True
                    success = owner_module._push_third_person(transition_time=0.0)
                    logging.warning(
                        "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_PUSH "
                        f"success={success}, default_transitioning=True"
                    )
                    if success:
                        state["phase"] = "early_handoff_monitor"
                        return
                except Exception as exc:
                    logging.error(
                        "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_ABORT "
                        f"error={type(exc).__name__}: {exc}"
                    )

        if (
            reason == "ffyl"
            and state.get("early_handoff_attempted")
            and mode == "ThirdPerson"
        ):
            # Offsets belong to the owned TPS camera as soon as it has fully
            # settled. Keep the lifecycle pending to watch for a later native
            # Default override; native recoil resumes only after that watch.
            offset_ready = False
            if (
                attach == "CharacterMesh"
                and not transitioning
                and not camera_manager.CameraModeState.bShowViewModel
                and not camera_manager.CameraModeState.bIsColliding
                and owner_module._third_person_enabled
                and owner_module._third_person_pushed
                and not owner_module._native_fault
                and not owner_module._native_active()
                and owner_module._camera_stack_owner.get("owned")
                and pawn_address
                == int(owner_module._camera_stack_owner.get("pawn_address", 0))
                and owner_module._object_address(camera_manager)
                == int(owner_module._camera_stack_owner.get("manager_address", 0))
            ):
                try:
                    offset_ready = owner_module._ffyl_camera_stack_has_single_tps(
                        camera_manager
                    )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if state.get("last_error") != error:
                        logging.error(
                            "[BL4ThirdPersonPOC] FFYL_OFFSET_STACK_UNVERIFIED "
                            f"{error}"
                        )
                    state["last_error"] = error
            elapsed = now - float(state.get("early_handoff_started") or now)
            if offset_ready and not state.get("early_handoff_offsets_restored"):
                state["early_handoff_offsets_restored"] = True
                logging.info(
                    "[BL4ThirdPersonPOC] FFYL_TPS_OFFSETS_RESTORED "
                    f"stable owned ThirdPerson camera, elapsed={elapsed:.3f}"
                )
            if elapsed >= 0.85 and offset_ready:
                state["pending"] = False
                state["repair_done"] = True
                state["suppress_offsets"] = False
                state["phase"] = "early_handoff_resumed"
                state["repair_successes"] += 1
                logging.warning(
                    "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_COMPLETE "
                    f"elapsed={elapsed:.3f} "
                    f"native_resume_pending={owner_module._ffyl_native_resume_pending}"
                )
            else:
                state["phase"] = "early_handoff_monitor"
                state["suppress_offsets"] = not offset_ready
            return

        if (
            reason == "ffyl"
            and state.get("early_handoff_attempted")
            and mode == "Default"
        ):
            # BL4 superseded the experimental push. Retire it only if BL4
            # demonstrably emptied the stack, then let shared camera repair run after settle.
            if not owner_module._ffyl_camera_stack_empty(camera_manager):
                state["phase"] = "early_handoff_stack_unverified"
                state["suppress_offsets"] = True
                return
            if (
                owner_module._third_person_pushed
                or owner_module._camera_stack_owner.get("owned")
            ):
                owner_module._retire_camera_stack_owner("ffyl_early_handoff_superseded")
            state["early_handoff_attempted"] = False
            logging.warning(
                "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_SUPERSEDED "
                "shared camera repair remains armed"
            )

        if mode != "Default":
            state["phase"] = "waiting_for_default"
            state["settled_since"] = None
            state["suppress_offsets"] = mode != "ThirdPerson" or reason == "ffyl"
            return

        state["suppress_offsets"] = True
        if transitioning:
            state["phase"] = "default_transition"
            state["settled_since"] = None
            return

        # A fresh ADS press can arrive before the FFYL camera has settled.
        # Leave the repair armed and begin a new settle period after ADS ends.
        if owner_module._ads_active:
            if state.get("phase") != "waiting_for_ads_release":
                logging.info(
                    "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_REPAIR_DEFERRED "
                    f"reason={reason!r}, blocker='ads_active'"
                )
            state["phase"] = "waiting_for_ads_release"
            state["settled_since"] = None
            return

        state["phase"] = "default_settled"
        if state.get("settled_since") is None:
            state["settled_since"] = now
            return
        settled_for = now - float(state["settled_since"])
        if settled_for < owner_module.CAMERA_LIFECYCLE_SETTLE_SECONDS:
            return

        if reason == "ffyl" and (
            owner_module._third_person_pushed
            or owner_module._camera_stack_owner.get("owned")
        ):
            try:
                empty_stack = owner_module._ffyl_camera_stack_empty(camera_manager)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if state.get("last_error") != error:
                    logging.error(
                        "[BL4ThirdPersonPOC] FFYL_STACK_UNVERIFIED "
                        f"error={error}; camera repair deferred"
                    )
                state["errors"] += 1
                state["last_error"] = error
                state["phase"] = "stack_unverified"
                state["settled_since"] = None
                return
            if not empty_stack:
                if state.get("last_error") != "native_camera_stack_nonempty":
                    logging.warning(
                        "[BL4ThirdPersonPOC] FFYL_STACK_NONEMPTY "
                        "waiting for native camera to release stack"
                    )
                state["last_error"] = "native_camera_stack_nonempty"
                state["phase"] = "stack_nonempty"
                state["settled_since"] = None
                return
            owner_module._retire_camera_stack_owner("ffyl_default_empty_stack")

        state["phase"] = "repairing"
        state["repair_attempts"] += 1
        logging.info(
            "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_REPAIR_START "
            f"reason={reason!r}, settled_for={settled_for:.6f}"
        )
        success = bool(owner_module._repair_third_person(automatic=True))
        if success:
            state["pending"] = False
            state["repair_done"] = True
            state["phase"] = "resumed"
            state["suppress_offsets"] = False
            state["repair_successes"] += 1
        else:
            # A refused or transiently unavailable repair must remain
            # eligible for a later frame, without retrying on every frame.
            state["phase"] = "retry_wait"
            state["settled_since"] = None
        logging.info(
            "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_REPAIR_COMPLETE "
            f"reason={reason!r}, success={success}"
        )
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_ERROR " f"{type(exc).__name__}: {exc}"
        )


# Slide, ladder, vehicle transitions and one-shot diagnostics.
def _sample_slide_camera_offset_impl(phase: str, *, owner_module) -> None:

    if owner_module._slide_offset_samples_remaining <= 0:
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        return

    try:
        current_mode = str(camera_manager.GetActorCameraMode(pawn))

        offset = camera_manager.CameraModeState.CameraLocationOffset

        logging.info(
            "[BL4ThirdPersonPOC] "
            f"SLIDE OFFSET SAMPLE "
            f"phase={phase!r}, "
            f"mode={current_mode!r}, "
            f"offset={offset!r}"
        )

    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not sample "
            "slide camera offset: "
            f"{type(exc).__name__}: {exc}"
        )

    owner_module._slide_offset_samples_remaining -= 1


def _is_sliding_now_impl(*, owner_module) -> bool:
    _pc, pawn, _camera_manager = owner_module._get_runtime()

    if pawn is not None:
        try:
            movement = pawn.CharacterMovement

            if bool(movement.bWantsToSlide):
                return True
        except Exception:
            pass

    if any(owner_module._last_anim_slide_states.values()):
        return True

    return False


def _transition_to_first_person_impl(*, owner_module) -> bool:
    pc, pawn, _camera_manager = owner_module._get_runtime()

    if pc is None:
        return False

    try:
        pc.CameraTransition(
            "FirstPerson",
            "Default",
            0.01,
            False,
            False,
        )

        logging.info(
            "[BL4ThirdPersonPOC] Started fast " "FirstPerson camera transition"
        )
        return True

    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] CameraTransition failed: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        pc.ClientSetCameraMode("Default")

        logging.info("[BL4ThirdPersonPOC] Used Default camera " "mode fallback")
        return True

    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Default camera fallback failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def _update_slide_state_impl(*, owner_module) -> None:

    sliding_now = owner_module._is_sliding_now()

    if sliding_now:
        if owner_module._native_slide_handoff_pending:
            owner_module._native_slide_seen = True
        if not owner_module._slide_active:
            owner_module._slide_active = True
            owner_module._slide_camera_recovery_pending = bool(
                owner_module._third_person_enabled
            )
            _pc, slide_pawn, _manager = owner_module._get_runtime()
            owner_module._slide_camera_recovery_pawn = owner_module._object_address(
                slide_pawn
            )
            owner_module._slide_offset_samples_remaining = 8

            logging.info("[BL4ThirdPersonPOC] Slide started")

        owner_module._sample_slide_camera_offset("before_restore")
        owner_module._restore_slide_third_person()
        owner_module._sample_slide_camera_offset("after_restore")
        return

    if not owner_module._slide_active:
        return

    owner_module._slide_active = False

    logging.info("[BL4ThirdPersonPOC] Slide ended")

    owner_module._restore_slide_third_person()


def _update_slide_camera_recovery_impl(*, owner_module) -> None:

    if not owner_module._slide_camera_recovery_pending or owner_module._slide_active:
        return
    if not owner_module._third_person_enabled:
        owner_module._slide_camera_recovery_pending = False
        owner_module._slide_camera_recovery_pawn = 0
        return
    if (
        owner_module._vehicle_camera_active
        or owner_module._is_vehicle_camera_view()
        or owner_module._shop_camera_active
        or owner_module._ladder_active
        or owner_module._camera_lifecycle.get("pending")
        or (owner_module._ads_active and owner_module._ads_route != "tps")
    ):
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        return
    owner = owner_module._object_address(pawn)
    if (
        owner_module._slide_camera_recovery_pawn
        and owner != owner_module._slide_camera_recovery_pawn
    ):
        logging.info("[BL4ThirdPersonPOC] SLIDE_CAMERA_RECOVERY_DISCARDED pawn_changed")
        owner_module._slide_camera_recovery_pending = False
        owner_module._slide_camera_recovery_pawn = 0
        return
    if not owner_module._third_person_pushed:
        return
    try:
        mode = str(camera_manager.GetActorCameraMode(pawn))
        transitioning = bool(camera_manager.CameraModeState.bIsTransitioning)
    except Exception:
        return
    if transitioning:
        return
    if mode != "ThirdPerson" or owner_module._looks_like_first_person_fallback():
        if not owner_module._restore_slide_third_person():
            return
        try:
            mode = str(camera_manager.GetActorCameraMode(pawn))
        except Exception:
            return
        if mode != "ThirdPerson" or owner_module._looks_like_first_person_fallback():
            return
        logging.info("[BL4ThirdPersonPOC] SLIDE_CAMERA_RECOVERED after_slide")

    # A TPS zoom-out can still produce a native mode transition.  Keep the
    # recovery armed until its route completes and the mode is verified.
    if owner_module._ads_route == "tps":
        return
    owner_module._slide_camera_recovery_pending = False
    owner_module._slide_camera_recovery_pawn = 0


def _recover_missed_ladder_exit(pawn: Any, camera: Any, *, owner_module) -> bool:
    """Recover only a native-observed ladder handoff with an empty stack.

    An owned record can outlive its stack entry both when
    the SDK missed ladder and when it had seen ladder before a later Default.
    The pending native handoff scopes recovery; the seen latch describes
    event history, not live stack ownership. Do not pop the dead entry.
    """
    if (
        not owner_module._native_ladder_handoff_pending
        or owner_module._ladder_active
        or not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._native_fault
        or owner_module._native_ffyl_pending
        or owner_module._ffyl_early_handoff_armed
        or owner_module._ffyl_native_resume_pending
        or owner_module._camera_lifecycle.get("pending")
        or owner_module._vehicle_camera_active
        or owner_module._shop_camera_active
        or owner_module._slide_active
        or owner_module._ads_active
        or owner_module._ads_route != "hip"
        or owner_module._ads_press_intent.get("pending")
        or owner_module._mantle_camera_state.get("active")
        or owner_module._mantle_camera_state.get("releasing")
        or owner_module._active_native_state.get("ladder_guard") is not None
    ):
        return False
    owner = owner_module._camera_stack_owner
    if not owner.get("owned") or owner.get("pending_pop"):
        return False
    if owner_module._object_address(pawn) != int(
        owner.get("pawn_address", 0)
    ) or owner_module._object_address(camera) != int(owner.get("manager_address", 0)):
        return False
    try:
        if (
            str(camera.GetActorCameraMode(pawn)) != "Default"
            or camera.CameraModeState.bIsTransitioning
            or camera.CameraModeState.bIsColliding
            or not camera.CameraModeState.bShowViewModel
            or owner_module._object_address(camera.CameraModeInputs.ViewTarget)
            != owner_module._object_address(pawn)
            or owner_module._is_vehicle_camera_view()
            or owner_module._ffyl_camera_active(pawn, camera)
            or owner_module._native_zoom_confirms_ads(pawn)
            or owner_module._native_active()
            or owner_module._beam_active()
        ):
            return False
        movement = pawn.GbxNavMovement
        ladder = movement.LadderState
        anim = movement.LadderAnimState
        # The measured missed-ladder exit uses movement=3. Accept
        # it only when the live SDK enum explicitly names MOVE_Falling;
        # an unnamed integer or a different enum cannot authorize recovery.
        movement_mode = movement.MovementMode
        falling = (
            type(movement_mode).__name__ == "EMovementMode"
            and getattr(movement_mode, "name", None) == "MOVE_Falling"
            and int(movement_mode) == 3
        )
        # Existing Walking path stays unchanged. Both paths require completed
        # climbing animation, no custom movement, and all camera/owner gates.
        if (
            (int(movement_mode) != 1 and not falling)
            or int(movement.CustomMovementMode) != 0
            or ladder.bClientWasOnLadder
            or ladder.bWantsToBeOnLadder
            or movement.bIsSlidingDownLadder
            or movement.bWantsToLadderSlide
            or int(anim.PendingType) != 0
            or int(anim.CurrentType) != 0
            or int(movement.ReplicatedLadderState.ClimbableType) != 0
            or not owner_module._ffyl_camera_stack_empty(camera)
        ):
            return False
    except Exception:
        # Unknown SDK fields or an unverified stack layout cannot authorize a push.
        return False

    seen_before = bool(owner_module._native_ladder_seen)
    owner_module._retire_camera_stack_owner("ladder_handoff_empty_stack")
    success = owner_module._push_third_person(transition_time=0.0)
    if success:
        # Keep the handoff pending. The existing native lifecycle waits for
        # stable TPS before acquiring any new native Look owner.
        owner_module._native_ladder_seen = True
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] LADDER_EMPTY_STACK_RECOVERED "
            f"empty_stack=True seen_before={seen_before} "
            f'movement={"Falling" if falling else "Walking"} '
            "native_resume=await_stable_tps"
        )
    else:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] LADDER_EMPTY_STACK_PUSH_FAILED; native remains pending"
        )
    return True


def _update_ladder_camera_state_impl(*, owner_module) -> None:

    if not owner_module._third_person_enabled:
        owner_module._ladder_active = False
        owner_module._ladder_entry_requested = False
        owner_module._ladder_native_reassertion_logged = False
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()

    if pawn is None or camera_manager is None:
        return

    try:
        current_mode = str(camera_manager.GetActorCameraMode(pawn))
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not query "
            "camera mode for ladder handling: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    if current_mode.lower() == "ladder":
        if owner_module._native_ladder_handoff_pending:
            owner_module._native_ladder_seen = True
        if not owner_module._ladder_active:
            owner_module._cancel_hybrid_ads("ladder_enter")
            owner_module._ladder_active = True
            owner_module._ads_active = False
            owner_module._ladder_entry_requested = False
            owner_module._ladder_native_reassertion_logged = False

            logging.info(
                "[BL4ThirdPersonPOC] Ladder camera started; " "ADS state cleared"
            )
            # The generic slide restore refuses to run while owner_module._ladder_active.
            # Request TPS once on native ladder entry instead of fighting the
            # game's ladder mode on every animation update.
            if (
                owner_module._third_person_pushed
                and not owner_module._camera_lifecycle.get("pending")
            ):
                try:
                    camera_manager.SetActorCameraMode(
                        pawn,
                        "ThirdPerson",
                        "",
                        0.0,
                        False,
                        True,
                    )
                    owner_module._ladder_entry_requested = True
                    owner_module._apply_camera_offset()
                    logging.info(
                        "[BL4ThirdPersonPOC] LADDER_TPS_ENTRY_REQUESTED "
                        "native_mode='ladder'"
                    )
                except Exception as exc:
                    logging.error(
                        "[BL4ThirdPersonPOC] LADDER_TPS_ENTRY_FAILED "
                        f"{type(exc).__name__}: {exc}"
                    )
        elif (
            owner_module._ladder_entry_requested
            and not owner_module._ladder_native_reassertion_logged
        ):
            owner_module._ladder_native_reassertion_logged = True
            logging.warning(
                "[BL4ThirdPersonPOC] LADDER_NATIVE_MODE_REASSERTED "
                "after TPS entry request"
            )
        return

    if current_mode == "Default" and _recover_missed_ladder_exit(
        pawn,
        camera_manager,
        owner_module=owner_module,
    ):
        return

    if not owner_module._ladder_active:
        return

    # Solange unser erzwungener ThirdPerson-Mode aktiv ist,
    # befinden wir uns vermutlich noch auf der Leiter.
    if current_mode == "ThirdPerson":
        owner_module._apply_camera_offset()
        return

    # Beim Verlassen setzt BL4 laut Dump wieder Default.
    if current_mode == "Default":
        owner_module._ladder_active = False
        owner_module._ladder_entry_requested = False
        owner_module._ladder_native_reassertion_logged = False

        pending_state = owner_module._ladder_pending_third_person_enabled
        owner_module._ladder_pending_third_person_enabled = None

        if pending_state is not None:
            owner_module._third_person_enabled = pending_state

        logging.info(
            "[BL4ThirdPersonPOC] Ladder camera ended; "
            f"third_person_enabled={owner_module._third_person_enabled}"
        )

        if owner_module._third_person_enabled:
            owner_module._restore_slide_third_person()
        else:
            owner_module._pop_third_person()

        return


def _update_vehicle_camera_state_impl(*, owner_module) -> None:

    vehicle_now = owner_module._is_vehicle_camera_view()

    if vehicle_now:
        if not owner_module._vehicle_camera_active:
            owner_module._cancel_hybrid_ads("vehicle_enter")
            owner_module._vehicle_camera_active = True
            owner_module._ads_active = False
            if owner_module._camera_lifecycle.get("reason") == "client_restart":
                owner_module._discard_camera_lifecycle("vehicle_enter")

            logging.info("[BL4ThirdPersonPOC] " "Vehicle camera started")

            # Nur einmal den vom Character übernommenen
            # Offset entfernen. Danach gehört der State BL4.
            owner_module._set_camera_offset(0.0, 0.0, 0.0)

        return

    if not owner_module._vehicle_camera_active:
        return

    owner_module._vehicle_camera_active = False

    logging.info("[BL4ThirdPersonPOC] Vehicle camera ended")

    if owner_module._third_person_enabled and not owner_module._ads_active:
        if owner_module._third_person_pushed:
            owner_module._restore_slide_third_person()
        else:
            owner_module._push_third_person()

    else:
        if owner_module._third_person_pushed:
            owner_module._pop_third_person()
        else:
            owner_module._set_camera_offset(0.0, 0.0, 0.0)


# Physical ADS press preparation and its native ownership handoff.


def _reset_ads_press_intent_impl(*, owner_module) -> None:
    owner_module._ads_press_intent = {
        "pending": False,
        "pawn_address": 0,
        "manager_address": 0,
        "weapon_address": 0,
        "prepared_category": "",
        "prepared_source": "",
        "prepared_evidence": "",
        "prepared_collector_address": 0,
        "deferred": False,
        "presses": 0,
        "confirmed": 0,
        "deferred_presses": 0,
        "deferred_resolved": 0,
        "deferred_cancelled": 0,
        "throwable_bypasses": 0,
        "release_bypasses": 0,
        "invalidations": 0,
        "weak_signal_seen": False,
        "weak_signal_rejections": 0,
        "equip_gaps": 0,
        "equip_rebinds": 0,
        "errors": 0,
        "last_reason": "",
        "last_error": "",
    }


def _clear_pending_ads_press_impl(
    reason: str, *, outcome: str = "invalid", owner_module
) -> bool:
    state = owner_module._ads_press_intent
    if not state.get("pending"):
        return False
    was_deferred = bool(state.get("deferred"))
    state["pending"] = False
    state["pawn_address"] = 0
    state["manager_address"] = 0
    state["weapon_address"] = 0
    state["prepared_category"] = ""
    state["prepared_source"] = ""
    state["prepared_evidence"] = ""
    state["prepared_collector_address"] = 0
    state["deferred"] = False
    state["weak_signal_seen"] = False
    state["last_reason"] = reason
    if was_deferred and outcome != "confirmed":
        state["deferred_cancelled"] += 1
        logging.info(
            "[BL4ThirdPersonPOC] ADS_PRESS_DEFERRED_CANCELLED "
            f"reason={reason!r}, outcome={outcome!r}"
        )
    if outcome == "throwable":
        state["throwable_bypasses"] += 1
    elif outcome == "release":
        state["release_bypasses"] += 1
    elif outcome != "confirmed":
        state["invalidations"] += 1
    logging.info(
        "[BL4ThirdPersonPOC] ADS_PRESS_INTENT_CLEARED "
        f"reason={reason!r}, outcome={outcome!r}"
    )
    return True


def _note_weak_zoom_signal_impl(pawn: Any, source: str, *, owner_module) -> None:
    state = owner_module._ads_press_intent
    if state.get("weak_signal_seen"):
        return
    zoom = pawn.ZoomState
    if not (
        int(zoom.State) == 0
        and bool(zoom.bWantsToZoom)
        and not bool(zoom.bPendingZoom)
        and not bool(zoom.bTickingZoom)
    ):
        return
    state["weak_signal_seen"] = True
    state["weak_signal_rejections"] += 1
    logging.info(
        "[BL4ThirdPersonPOC] ADS_PRESS_WEAK_WANTS_REJECTED "
        f"source={source!r}, weapon="
        f"0x{int(state.get('weapon_address', 0)):016X}"
    )


def _prepare_pending_ads_press_impl(
    weapon: Any,
    *,
    collector_address: int = 0,
    owner_module,
) -> None:
    state = owner_module._ads_press_intent
    category, source, evidence = owner_module._classify_ads_weapon(weapon)
    state["prepared_category"] = category
    state["prepared_source"] = source
    state["prepared_evidence"] = evidence
    if (
        category != "sniper_rifle" or hybrid_ads.sniper_uses_tps(owner_module)
    ) and len(owner_module._ads_hooks_installed) == 6:
        collector = owner_module._find_ads_collector(weapon)
        discovered_collector_address = owner_module._ads_object_address(collector)
        resolved_collector_address = int(collector_address)
        if (
            resolved_collector_address
            and discovered_collector_address
            and resolved_collector_address != discovered_collector_address
        ):
            raise RuntimeError("Deferred ADS collector does not match current weapon")
        if not resolved_collector_address:
            resolved_collector_address = discovered_collector_address
        if not resolved_collector_address:
            raise RuntimeError("Prepared ADS collector address is zero")
        state["prepared_collector_address"] = resolved_collector_address
    logging.info(
        "[BL4ThirdPersonPOC] ADS_PRESS_INTENT_PREPARED "
        f"category={category!r}, source={source!r}, "
        f"collector=0x{state['prepared_collector_address']:016X}"
    )


def _arm_pending_ads_press_impl(
    pawn: Any, camera_manager: Any, *, owner_module
) -> None:
    # Hold only the exact verified FireBeam pair; all other owners are restored
    # while the old TPS camera copy is still available.
    if (
        owner_module._beam_active()
        and not owner_module._ads_beam_can_hold(camera_manager, pawn)
        and not owner_module._native_stop_beam("ads_press")
    ):
        raise RuntimeError("Beam restore failed at ADS press; restart game")
    state = owner_module._ads_press_intent
    if state.get("pending"):
        owner_module._clear_pending_ads_press("superseded_press")
    state["pending"] = True
    state["pawn_address"] = owner_module._object_address(pawn)
    state["manager_address"] = owner_module._object_address(camera_manager)
    state["weapon_address"] = owner_module._ads_object_address(
        camera_manager.CameraModeInputs.Weapon
    )
    state["prepared_category"] = ""
    state["prepared_source"] = ""
    state["prepared_evidence"] = ""
    state["prepared_collector_address"] = 0
    state["deferred"] = not bool(state["weapon_address"])
    state["weak_signal_seen"] = False
    state["presses"] += 1
    logging.info(
        "[BL4ThirdPersonPOC] ADS_PRESS_INTENT_ARMED "
        f"pawn=0x{state['pawn_address']:016X}, "
        f"manager=0x{state['manager_address']:016X}, "
        f"weapon=0x{state['weapon_address']:016X}"
    )
    if state["deferred"]:
        state["deferred_presses"] += 1
        logging.info(
            "[BL4ThirdPersonPOC] ADS_PRESS_DEFERRED "
            "reason='weapon_unavailable', awaiting='native_zoom_or_release'"
        )
        return
    try:
        weapon = camera_manager.CameraModeInputs.Weapon
        owner_module._prepare_pending_ads_press(weapon)
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"prepare: {type(exc).__name__}: {exc}"
        owner_module._ads_debug_error("press_prepare", exc)


# Confirmed ADS routing and physical input; keybinds stay in the loader.


def _ffyl_camera_active_impl(pawn: Any, camera_manager: Any, *, owner_module) -> bool:
    """Include the serial-bound simple FFYL owner even in ThirdPerson mode."""
    from . import ffyl_strategy_runtime
    if ffyl_strategy_runtime.ads_blocked(owner_module, pawn, camera_manager):
        return True
    try:
        return str(camera_manager.GetActorCameraMode(pawn)) == "FFYL"
    except Exception as exc:
        # If the camera cannot be queried during a known FFYL transition,
        # avoid activating ADS on an unverified mode.
        if (
            owner_module._camera_lifecycle.get("pending")
            and owner_module._camera_lifecycle.get("reason") == "ffyl"
        ):
            logging.warning(
                "[BL4ThirdPersonPOC] FFYL ADS guard could not query "
                f"camera mode: {type(exc).__name__}: {exc}"
            )
            return True
        return False


def _activate_confirmed_ads_press_impl(
    pawn: Any,
    camera_manager: Any,
    confirmation: str,
    *,
    owner_module,
) -> None:

    if owner_module._ffyl_camera_active(pawn, camera_manager):
        owner_module._clear_pending_ads_press("ffyl_camera", outcome="invalid")
        logging.info(
            "[BL4ThirdPersonPOC] FFYL_ADS_BLOCKED stage='confirmation' "
            f"source={confirmation!r}"
        )
        return

    prepared_category = str(owner_module._ads_press_intent.get("prepared_category", ""))
    prepared_source = str(owner_module._ads_press_intent.get("prepared_source", ""))
    prepared_evidence = str(owner_module._ads_press_intent.get("prepared_evidence", ""))
    prepared_collector_address = int(
        owner_module._ads_press_intent.get("prepared_collector_address", 0)
    )
    owner_module._clear_pending_ads_press(confirmation, outcome="confirmed")
    owner_module._ads_press_intent["confirmed"] += 1
    owner_module._ads_handoff["held"] = True

    if owner_module._ads_route == "tps" and not owner_module._ads_active:
        try:
            owner_module._ads_active = True
            owner_module._reverse_hybrid_tps_ads()
            owner_module._request_tps_reticle_publish("ads_reversal")
            owner_module._apply_camera_offset()
        except Exception as exc:
            owner_module._ads_debug_error("tps_reverse", exc)
            owner_module._cancel_hybrid_ads("reverse_failure")
        return

    if owner_module._ads_active or owner_module._ads_route != "hip":
        owner_module._ads_debug["ignored_events"] += 1
        return

    if prepared_category:
        category = prepared_category
        source = prepared_source
        evidence = prepared_evidence
    else:
        try:
            category, source, evidence = owner_module._classify_ads_weapon(
                camera_manager.CameraModeInputs.Weapon
            )
        except Exception as exc:
            owner_module._ads_debug_error("weapon_classification", exc)
            category = "unknown"
            source = "classification_error"
            evidence = f"{type(exc).__name__}: {exc}"

    if (
        category != "sniper_rifle" or hybrid_ads.sniper_uses_tps(owner_module)
    ) and len(owner_module._ads_hooks_installed) == 6:
        try:
            owner_module._start_hybrid_tps_ads(
                camera_manager,
                category,
                source,
                evidence,
                prepared_collector_address,
            )
            owner_module._ads_active = True
            owner_module._request_tps_reticle_publish("confirmed_ads_entry")
            owner_module._apply_camera_offset()
            return
        except Exception as exc:
            owner_module._ads_debug_error("tps_start", exc)
            owner_module._cancel_hybrid_ads("tps_start_fallback")
            logging.warning(
                "[BL4ThirdPersonPOC] TPS ADS setup failed; "
                "falling back to native First-Person ADS"
            )
    elif category != "sniper_rifle" or hybrid_ads.sniper_uses_tps(owner_module):
        logging.warning(
            "[BL4ThirdPersonPOC] Hybrid ADS hooks are incomplete; "
            "falling back to native First-Person ADS"
        )

    # FPS ADS switches the camera definition. Restore its TPS Look copy
    # before SetActorCameraMode replaces it (TPS ADS keeps the same copy).
    if (
        owner_module._native_active()
        or owner_module._active_native_state.get("ladder_default")
    ) and not owner_module._native_stop("fps_ads_start"):
        raise RuntimeError("Recoil restore failed before FPS ADS; restart game")
    owner_module._ads_active = True
    owner_module._ads_route = (
        "sniper_fps" if category == "sniper_rifle" else "fallback_fps"
    )
    owner_module._ads_handoff["route_weapon"] = owner_module._ads_object_address(
        camera_manager.CameraModeInputs.Weapon
    )
    if category == "sniper_rifle":
        owner_module._ads_debug["sniper_presses"] += 1
    else:
        owner_module._ads_debug["fallback_presses"] += 1

    # Native First-Person ADS keeps the established camera route for sniper
    # rifles and as a fail-safe for unsupported weapon layouts.
    owner_module._set_camera_offset(0.0, 0.0, 0.0)

    try:
        camera_manager.SetActorCameraMode(
            pawn,
            "Default",
            "",
            owner_module.ADS_CAMERA_TRANSITION_TIME,
            False,
            True,
        )
        logging.info(
            "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE "
            f"category={category!r}, route={owner_module._ads_route!r}, "
            f"source={source!r}, evidence={evidence}, "
            f"confirmation={confirmation!r}"
        )
    except Exception as exc:
        owner_module._ads_debug_error("native_fps_enter", exc)


def _reconcile_pending_ads_press_weapon_impl(
    pawn: Any,
    camera_manager: Any,
    source: str,
    *,
    collector_address: int = 0,
    owner_module,
) -> bool:
    """Carry an unconfirmed physical press across an observed equip change."""
    state = owner_module._ads_press_intent
    if not state.get("pending"):
        return False
    if owner_module._object_address(pawn) != int(
        state.get("pawn_address", 0)
    ) or owner_module._object_address(camera_manager) != int(
        state.get("manager_address", 0)
    ):
        return False

    weapon = camera_manager.CameraModeInputs.Weapon
    incoming = owner_module._ads_object_address(weapon)
    expected = int(state.get("weapon_address", 0))
    if incoming and incoming == expected and not state.get("deferred"):
        return True

    if not incoming:
        if not state.get("deferred") or expected:
            state["weapon_address"] = 0
            state["prepared_category"] = ""
            state["prepared_source"] = ""
            state["prepared_evidence"] = ""
            state["prepared_collector_address"] = 0
            state["deferred"] = True
            state["weak_signal_seen"] = False
            state["equip_gaps"] += 1
            logging.info(
                "[BL4ThirdPersonPOC] ADS_PRESS_EQUIP_GAP_PRESERVED "
                f"source={source!r}, outgoing=0x{expected:016X}"
            )
        return False

    was_deferred = bool(state.get("deferred"))
    owner_module._prepare_pending_ads_press(
        weapon,
        collector_address=collector_address,
    )
    state["weapon_address"] = incoming
    state["deferred"] = False
    state["weak_signal_seen"] = False
    if was_deferred:
        state["deferred_resolved"] += 1
    else:
        state["equip_rebinds"] += 1
    logging.info(
        "[BL4ThirdPersonPOC] ADS_PRESS_EQUIP_REBOUND "
        f"source={source!r}, incoming=0x{incoming:016X}, "
        f"category={state['prepared_category']!r}, "
        f"deferred={was_deferred}"
    )
    return True


def _update_pending_ads_press_impl(*, owner_module) -> None:
    state = owner_module._ads_press_intent
    if not state.get("pending"):
        return
    if (
        not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._vehicle_camera_active
        or owner_module._ladder_active
        or owner_module._shop_camera_active
    ):
        owner_module._clear_pending_ads_press("camera_state_changed")
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        owner_module._clear_pending_ads_press("runtime_unavailable")
        return
    try:
        if owner_module._ffyl_camera_active(pawn, camera_manager):
            owner_module._clear_pending_ads_press("ffyl_camera", outcome="invalid")
            return
        if not owner_module._reconcile_pending_ads_press_weapon(
            pawn,
            camera_manager,
            "frame",
        ):
            if owner_module._ads_press_intent.get("deferred"):
                return
            owner_module._clear_pending_ads_press("runtime_identity_changed")
            return
        if owner_module._native_zoom_confirms_ads(pawn):
            owner_module._activate_confirmed_ads_press(
                pawn,
                camera_manager,
                "native_zoom_state",
            )
            return
        owner_module._note_weak_zoom_signal(pawn, "frame")
        # No elapsed-time decision is made here.  A real ADS press is
        # confirmed by Oak's zoom state/event; an unconfirmed press remains
        # inert until its physical release (the throwable/use-object path).
        return
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        owner_module._ads_debug_error("press_confirmation", exc)
        owner_module._clear_pending_ads_press("confirmation_error")


def _handle_first_person_ads_input_impl(
    event: EInputEvent,
    *,
    owner_module,
) -> None:

    if (
        event == owner_module.EInputEvent.IE_Released
        and owner_module._ads_press_intent.get("pending")
    ):
        _pc, release_pawn, release_manager = owner_module._get_runtime()
        try:
            if (
                release_pawn is not None
                and release_manager is not None
                and owner_module._reconcile_pending_ads_press_weapon(
                    release_pawn,
                    release_manager,
                    "release",
                )
                and owner_module._native_zoom_confirms_ads(release_pawn)
            ):
                owner_module._activate_confirmed_ads_press(
                    release_pawn,
                    release_manager,
                    "native_zoom_state_on_release",
                )
            else:
                owner_module._clear_pending_ads_press(
                    "released_without_zoom_confirmation",
                    outcome="release",
                )
                owner_module._ads_handoff["held"] = False
                return
        except Exception as exc:
            owner_module._ads_press_intent["errors"] += 1
            owner_module._ads_press_intent["last_error"] = (
                f"release_confirmation: {type(exc).__name__}: {exc}"
            )
            owner_module._clear_pending_ads_press("release_confirmation_error")
            owner_module._ads_handoff["held"] = False
            return

    if event == owner_module.EInputEvent.IE_Released:
        owner_module._ads_handoff["held"] = False
        try:
            if owner_module._ads_handoff.get("latch_active"):
                _pc, release_pawn, _manager = owner_module._get_runtime()
                if release_pawn is not None:
                    owner_module._ads_write_zoom_latches(
                        release_pawn,
                        wants=False,
                        pending=False,
                    )
                owner_module._ads_handoff["latch_active"] = False
        except Exception as exc:
            owner_module._ads_handoff["errors"] += 1
            owner_module._ads_handoff["last_error"] = (
                f"physical_release: {type(exc).__name__}: {exc}"
            )
        owner_module._cleanup_ads_handoff("physical_release")

    if owner_module._vehicle_camera_active or owner_module._shop_camera_active:
        return

    if owner_module._ladder_active:
        return

    if not owner_module._third_person_enabled:
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()

    if pawn is None or camera_manager is None:
        return

    if event == owner_module.EInputEvent.IE_Pressed:
        if owner_module._ffyl_camera_active(pawn, camera_manager):
            owner_module._clear_pending_ads_press("ffyl_camera", outcome="invalid")
            logging.info("[BL4ThirdPersonPOC] FFYL_ADS_BLOCKED stage='press'")
            return
        if owner_module._ads_active or owner_module._ads_route != "hip":
            if not (owner_module._ads_route == "tps" and not owner_module._ads_active):
                owner_module._ads_debug["ignored_events"] += 1
                return
        owner_module._arm_pending_ads_press(pawn, camera_manager)
        try:
            if owner_module._native_zoom_confirms_ads(pawn):
                owner_module._activate_confirmed_ads_press(
                    pawn,
                    camera_manager,
                    "native_zoom_state_immediate",
                )
        except Exception as exc:
            owner_module._ads_press_intent["errors"] += 1
            owner_module._ads_press_intent["last_error"] = (
                f"immediate_confirmation: {type(exc).__name__}: {exc}"
            )
        return

    if event == owner_module.EInputEvent.IE_Released:
        if owner_module._ads_route == "tps" and owner_module._ads_active:
            owner_module._ads_active = False
            try:
                owner_module._release_hybrid_tps_ads()
                owner_module._apply_camera_offset()
            except Exception as exc:
                owner_module._ads_debug_error("tps_release", exc)
                owner_module._cancel_hybrid_ads("release_failure")
            return

        if not owner_module._ads_active:
            return

        owner_module._ads_active = False
        previous_route = owner_module._ads_route
        owner_module._ads_route = "hip"
        owner_module._ads_debug["native_releases"] += 1
        # Hybrid ADS: leaving the scope blends back like the scope exit.
        release_time = hybrid_ads.release_transition(
            owner_module, owner_module.ADS_CAMERA_TRANSITION_TIME
        )

        try:
            camera_manager.SetActorCameraMode(
                pawn,
                "ThirdPerson",
                "",
                release_time,
                False,
                True,
            )

            owner_module._apply_camera_offset()

            logging.info(
                "[BL4ThirdPersonPOC] HYBRID_ADS_RELEASED "
                f"route={previous_route!r}; "
                "SetActorCameraMode -> ThirdPerson"
            )

        except Exception as exc:
            owner_module._ads_debug_error("native_fps_release", exc)


def _push_third_person_impl(*, transition_time: float = 1.0, owner_module) -> bool:
    if owner_module._camera_stack_owner.get("pending_pop"):
        owner_module._retry_pending_camera_pop()
    if owner_module._camera_stack_owner.get("pending_pop"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Refusing ThirdPerson push while a "
            "previous owned camera entry still awaits removal"
        )
        return False
    if owner_module._third_person_pushed or owner_module._camera_stack_owner.get(
        "owned"
    ):
        return True

    _pc, pawn, camera_manager = owner_module._get_runtime()

    if pawn is None or camera_manager is None:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Pawn or camera manager is not available"
        )
        return False

    try:
        camera_manager.PushActorCameraMode(
            pawn,
            "ThirdPerson",
            "",
            transition_time,
            False,
        )

        owner_module._record_camera_stack_owner(pawn, camera_manager)
        owner_module._apply_camera_offset()

        owner_module.logging.info("[BL4ThirdPersonPOC] Pushed ThirdPerson camera mode")
        return True

    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] PushActorCameraMode failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def _pop_third_person_impl(
    *,
    reason: str = "requested",
    transition_time: float = 1.0,
    owner_module,
) -> bool:
    if (
        owner_module._native_active()
        or owner_module._active_native_state.get("ladder_default")
    ) and not owner_module._native_stop("camera_pop:" + reason):
        return False
    if not (
        owner_module._third_person_pushed
        or owner_module._camera_stack_owner.get("owned")
    ):
        owner_module._camera_stack_owner["pending_pop"] = False
        owner_module._persist_camera_stack_owner()
        if not owner_module._vehicle_camera_active:
            owner_module._set_camera_offset(0.0, 0.0, 0.0)
        return True

    if owner_module._vehicle_camera_active:
        owner_module._defer_camera_pop(f"{reason}:vehicle_active")
        return False

    _pc, pawn, camera_manager = owner_module._get_runtime()

    if pawn is None or camera_manager is None:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Cannot pop ThirdPerson: "
            "pawn or camera manager unavailable"
        )
        owner_module._defer_camera_pop(f"{reason}:runtime_unavailable")
        return False

    pawn_address = owner_module._object_address(pawn)
    manager_address = owner_module._object_address(camera_manager)
    owner_pawn = int(owner_module._camera_stack_owner.get("pawn_address", 0))
    owner_manager = int(owner_module._camera_stack_owner.get("manager_address", 0))
    pawn_mismatch = bool(owner_pawn and pawn_address != owner_pawn)
    manager_mismatch = bool(owner_manager and manager_address != owner_manager)
    if pawn_mismatch or manager_mismatch:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Recorded ThirdPerson owner was replaced; "
            "retiring stale ownership without touching the current runtime"
        )
        mismatch = "manager_replaced" if manager_mismatch else "pawn_replaced"
        owner_module._retire_camera_stack_owner(f"{reason}:{mismatch}")
        return True

    try:
        camera_manager.PopActorCameraMode(
            pawn,
            "ThirdPerson",
            "",
            transition_time,
            False,
        )

        owner_module._clear_camera_stack_owner()

        # Während der Vehicle Camera gehört der gemeinsame
        # CameraModeState vollständig Borderlands 4.
        if not owner_module._vehicle_camera_active:
            owner_module._set_camera_offset(0.0, 0.0, 0.0)

        owner_module.logging.info(
            "[BL4ThirdPersonPOC] " "Popped ThirdPerson camera mode"
        )
        return True

    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] "
            "PopActorCameraMode failed: "
            f"{type(exc).__name__}: {exc}"
        )
        owner_module._defer_camera_pop(f"{reason}:native_call_failed")
        return False


def toggle_third_person_impl(*, owner_module) -> None:

    # Check the live view as well as the cached state during vehicle entry.
    # Vehicle offsets must not follow a deferred on-foot perspective change.
    if owner_module._vehicle_camera_active or owner_module._is_vehicle_camera_view():
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] CAMERA_TOGGLE_IGNORED reason=vehicle"
        )
        return

    owner_module._clear_pending_ads_press("third_person_toggle")

    if owner_module._ads_active:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Release ADS before toggling Third Person"
        )
        return

    if owner_module._ads_route != "hip":
        owner_module._cancel_hybrid_ads("third_person_toggle")

    if owner_module._ladder_active:
        current_desired_state = (
            owner_module._ladder_pending_third_person_enabled
            if owner_module._ladder_pending_third_person_enabled is not None
            else owner_module._third_person_enabled
        )

        owner_module._ladder_pending_third_person_enabled = not current_desired_state
        owner_module._ads_active = False

        owner_module.logging.info(
            "[BL4ThirdPersonPOC] Third person "
            f"{'enabled' if owner_module._ladder_pending_third_person_enabled else 'disabled'} "
            "requested while on ladder; "
            "change deferred until ladder exit"
        )
        return

    if owner_module._third_person_enabled and tps_recovery.visibly_first_person(owner_module):
        # The game already shows first person (stale TPS after respawn/load).
        # F5 means "third person" here; repair instead of disabling invisibly.
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] TPS_TOGGLE_REPAIR camera was first-person while TPS was wanted"
        )
        if owner_module._repair_third_person(automatic=False):
            return

    if owner_module._third_person_enabled:
        from . import ffyl_strategy_runtime

        if not ffyl_strategy_runtime.shutdown(owner_module, "toggle_to_fps"):
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] FFYL_TOGGLE_REFUSED cleanup incomplete"
            )
            return
        # Restore the TPS Look vtable while the camera still owns its TPS mode.
        # The native helper verifies the live mode and refuses a restore after
        # _third_person_enabled has already been cleared.
        if (
            owner_module._native_active()
            or owner_module._active_native_state.get("ladder_default")
        ) and not owner_module._native_stop("toggle_to_fps"):
            return
        owner_module._third_person_enabled = False
        owner_module._ads_active = False
        owner_module._slide_camera_recovery_pending = False
        owner_module._slide_camera_recovery_pawn = 0

        if owner_module._vehicle_camera_active:
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] Third person "
                "disabled while in vehicle; "
                "camera change deferred"
            )
            return

        if owner_module._pop_third_person():
            owner_module.logging.info("[BL4ThirdPersonPOC] " "Third person disabled")
        else:
            owner_module._third_person_enabled = True

        return

    owner_module._third_person_enabled = True
    owner_module._ads_active = False

    if owner_module._vehicle_camera_active:
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] Third person "
            "enabled while in vehicle; "
            "camera change deferred"
        )
        return

    if owner_module._push_third_person():
        owner_module.logging.info("[BL4ThirdPersonPOC] " "Third person enabled")
    else:
        owner_module._third_person_enabled = False


def controller_r3_camera_toggle_impl(event: EInputEvent, *, owner_module) -> None:
    """Leave short R3 taps to the game; use a held R3 for TPS/FPS."""
    state = owner_module._controller_r3_camera_state
    if event == owner_module.EInputEvent.IE_Pressed:
        if state["pressed_at"] is None:
            state["pressed_at"] = owner_module.time.perf_counter()
            state["handled"] = False
    elif event == owner_module.EInputEvent.IE_Released:
        state["pressed_at"] = None
        state["handled"] = False
    elif event == owner_module.EInputEvent.IE_Repeat:
        started = state["pressed_at"]
        if started is None or state["handled"]:
            return
        if (
            owner_module.time.perf_counter() - started
            < owner_module.CONTROLLER_R3_CAMERA_HOLD_SECONDS
        ):
            return
        state["handled"] = True
        if owner_module._ads_active:
            return
        # Reuse F5's existing camera-stack, ladder, and vehicle safeguards.
        owner_module.toggle_third_person.callback()


def swap_shoulder_impl(*, owner_module) -> None:
    from . import shoulder_blend
    shoulder_blend.swap(owner_module)

    owner_module.logging.info(
        "[BL4ThirdPersonPOC] Shoulder swapped; "
        f"Y offset = {float(owner_module.camera_offset_y.value):.1f}"
    )


def _restore_slide_third_person_impl(*, owner_module) -> bool:

    if (
        not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or (owner_module._ads_active and owner_module._ads_route != "tps")
        or owner_module._vehicle_camera_active
        or owner_module._is_vehicle_camera_view()
        or owner_module._shop_camera_active
        or owner_module._ladder_active
        or owner_module._camera_lifecycle.get("pending")
    ):
        return False

    _pc, pawn, camera_manager = owner_module._get_runtime()

    if pawn is None or camera_manager is None:
        return False

    try:
        current_mode = str(camera_manager.GetActorCameraMode(pawn))
    except Exception as exc:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Could not query "
            "camera mode during slide: "
            f"{type(exc).__name__}: {exc}"
        )
        return False

    fallback_detected = (
        current_mode in ("Default", "Slide")
        or owner_module._looks_like_first_person_fallback()
    )

    if not fallback_detected:
        owner_module._apply_camera_offset()
        return True

    now = owner_module.time.monotonic()

    if (
        now - owner_module._last_slide_camera_force_time
        < owner_module.SLIDE_CAMERA_FORCE_COOLDOWN
    ):
        # Der zweite Animations-Hook darf den gerade
        # aufgebauten Mode nicht nochmals zurücksetzen.
        owner_module._apply_camera_offset()
        return True

    owner_module._last_slide_camera_force_time = now

    try:
        camera_manager.SetActorCameraMode(
            pawn,
            "ThirdPerson",
            "",
            (0.16 if current_mode == "Slide" or (current_mode == "Default" and (owner_module._slide_active or owner_module._slide_camera_recovery_pending)) else 0.0),
            False,
            True,
        )

        owner_module._apply_camera_offset()

        owner_module.logging.info(
            "[BL4ThirdPersonPOC] Forced ThirdPerson "
            f"during slide; reported_mode={current_mode!r}"
        )
        return True

    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Could not force "
            "ThirdPerson during slide: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def _camera_update_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    menu_state = owner_module._get_menu_state()
    if (
        menu_state is not None
        and not menu_state.get("closed")
        and menu_state.get("poll_via_camera_update")
    ):
        owner_module._menu_poll(obj, args, ret, func)
    from . import npc_camera_visibility
    from . import ffyl_strategy_runtime

    ffyl_strategy_runtime.update(owner_module)
    from . import ground_slam_camera

    ground_slam_camera.update(owner_module)
    profile = owner_module._perf_probe
    profile_active = bool(profile["armed"])
    if profile_active:
        hook_started_ns = owner_module.time.perf_counter_ns()
        if profile[
            "frames"
        ] >= owner_module.PERF_MAX_UPDATES or hook_started_ns - profile[
            "started_ns"
        ] >= int(
            owner_module.PERF_MAX_SECONDS * 1e9
        ):
            profile["armed"] = False
            profile["complete"] = True
            profile["limit"] = "updates_or_seconds"
            profile_active = False
        else:
            last_hook_ns = profile["last_hook_ns"]
            interval_ns = hook_started_ns - last_hook_ns if last_hook_ns else 0
            profile["last_hook_ns"] = hook_started_ns
            profile["frames"] += 1
            profile["item_frame"] = None
            total_stage_ns = 0
            top_stage = ""
            top_stage_ns = 0
            item_stage_ns = 0
    try:
        anim_name = str(obj.Class.Name)
    except Exception:
        anim_name = type(obj).__name__
    try:
        owner_module._last_anim_slide_states[anim_name] = bool(obj.bIsSliding)
    except Exception:
        owner_module._last_anim_slide_states[anim_name] = False

    stages = (
        ("native_ownership", owner_module._update_native_ownership),
        ("slide", owner_module._update_slide_state),
        ("ladder", owner_module._update_ladder_camera_state),
        ("vehicle", owner_module._update_vehicle_camera_state),
        ("camera_lifecycle", owner_module._update_camera_lifecycle),
        ("pending_camera_pop", owner_module._retry_pending_camera_pop),
        ("tps_recovery", lambda: tps_recovery.update(owner_module)),
        ("pending_ads", owner_module._update_pending_ads_press),
        ("ads_route", owner_module._update_hybrid_ads_route_reconciliation),
        ("hybrid_scope", lambda: hybrid_ads.update(owner_module)),
        ("hybrid_ads", owner_module._update_hybrid_tps_ads),
        ("ads_zoom_modifiers", lambda: ads_zoom_modifiers.update(owner_module)),
        ("reticle_readiness", owner_module._update_pending_tps_reticle),
        ("slide_camera_recovery", owner_module._update_slide_camera_recovery),
        ("item_card", owner_module._update_item_card_fusion),
        ("interaction", owner_module._update_pending_interaction_fallback),
        ("floor_pickup", owner_module._update_pending_floor_pickup_fallback),
        ("camera_offset", owner_module._apply_camera_offset),
        ("npc_camera_visibility", lambda: npc_camera_visibility.update(owner_module)),
    )
    probe = owner_module._slide_perf_probe
    if probe["armed"]:
        probe["frame"] += 1
    timing_active = profile_active or bool(probe["armed"])
    for stage_name, callback in stages:
        stage_started = owner_module.time.perf_counter_ns() if timing_active else 0
        try:
            callback()
        except Exception as exc:
            failures = owner_module._camera_hotpath_debug.setdefault("failures", {})
            failures[stage_name] = int(failures.get(stage_name, 0)) + 1
            owner_module._camera_hotpath_debug["total_failures"] = (
                int(owner_module._camera_hotpath_debug.get("total_failures", 0)) + 1
            )
            owner_module._camera_hotpath_debug["last_error"] = (
                f"{stage_name}: {type(exc).__name__}: {exc}"
            )
            if failures[stage_name] <= 3:
                owner_module.logging.error(
                    "[BL4ThirdPersonPOC] CAMERA_HOTPATH_STAGE_ERROR "
                    f"stage={stage_name!r}, count={failures[stage_name]}, "
                    f"error={type(exc).__name__}: {exc}"
                )
        finally:
            if timing_active:
                stage_ns = owner_module.time.perf_counter_ns() - stage_started
                if profile_active:
                    owner_module._perf_record_metric("stage." + stage_name, stage_ns)
                    total_stage_ns += stage_ns
                    if stage_ns > top_stage_ns:
                        top_stage, top_stage_ns = stage_name, stage_ns
                    if stage_name == "item_card":
                        item_stage_ns = stage_ns
                if probe["armed"] and stage_name in (
                    "native_ownership",
                    "slide",
                    "camera_offset",
                    "item_card",
                ):
                    probe["slide_seen"] |= bool(owner_module._slide_active)
                    measured = probe["stages"].setdefault(
                        stage_name, {"calls": 0, "total_ns": 0, "max_ns": 0}
                    )
                    measured["calls"] += 1
                    measured["total_ns"] += stage_ns
                    measured["max_ns"] = max(measured["max_ns"], stage_ns)
                    if stage_ns >= 1_000_000:
                        sample = (
                            stage_ns,
                            probe["frame"],
                            stage_name,
                            bool(owner_module._slide_active),
                            bool(owner_module._native_slide_handoff_pending),
                            owner_module.time.perf_counter_ns() - probe["started_ns"],
                        )
                        top = probe["top"]
                        if len(top) < 32:
                            top.append(sample)
                        else:
                            smallest = min(range(32), key=lambda index: top[index][0])
                            if stage_ns > top[smallest][0]:
                                top[smallest] = sample

    if profile_active:
        work_ns = owner_module.time.perf_counter_ns() - hook_started_ns
        owner_module._perf_record_metric("hook_work", work_ns)
        owner_module._perf_record_metric("stage_total", total_stage_ns)
        if interval_ns:
            owner_module._perf_record_metric("hook_interval", interval_ns)
        since_ns = hook_started_ns - profile["started_ns"]
        second = since_ns // 1_000_000_000
        bucket = profile["buckets"].setdefault(
            second, {"calls": 0, "interval_max": 0, "work_max": 0, "item_max": 0}
        )
        bucket["calls"] += 1
        bucket["interval_max"] = max(bucket["interval_max"], interval_ns)
        bucket["work_max"] = max(bucket["work_max"], work_ns)
        bucket["item_max"] = max(bucket["item_max"], item_stage_ns)
        item = profile["item_frame"]
        # Only retain bounded slow samples; the hot path never prints.
        sample = (
            work_ns,
            profile["frames"],
            since_ns,
            work_ns,
            interval_ns,
            top_stage,
            top_stage_ns,
            bool(item),
            bool(owner_module._slide_active),
        )
        owner_module._perf_record_top(profile["slow_work"], sample)
        if interval_ns:
            owner_module._perf_record_top(
                profile["slow_interval"], (interval_ns,) + sample[1:]
            )


def _blueprint_camera_probe_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:

    owner_module._blueprint_camera_probe_calls += 1

    slide_changed = (
        owner_module._blueprint_camera_probe_last_slide is None
        or owner_module._blueprint_camera_probe_last_slide != owner_module._slide_active
    )

    if not slide_changed:
        return

    owner_module._blueprint_camera_probe_last_slide = owner_module._slide_active

    owner_module.logging.info(
        "[BL4ThirdPersonPOC] " "===== BLUEPRINT UPDATE CAMERA ====="
    )
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] "
        f"call={owner_module._blueprint_camera_probe_calls}, "
        f"slide_active={owner_module._slide_active}, "
        f"third_person_enabled={owner_module._third_person_enabled}, "
        f"third_person_pushed={owner_module._third_person_pushed}"
    )
    owner_module.logging.info("[BL4ThirdPersonPOC] " f"caller={obj!r}")
    owner_module.logging.info("[BL4ThirdPersonPOC] " f"args={args!r}")
    owner_module.logging.info("[BL4ThirdPersonPOC] " f"ret={ret!r}")

    try:
        state = obj.CameraModeState

        owner_module.logging.info("[BL4ThirdPersonPOC] " f"CameraModeState={state!r}")

        for name in (
            "AttachComponent",
            "bShowViewModel",
            "ViewModelFOV",
            "CameraLocationOffset",
        ):
            try:
                value = getattr(state, name)

                owner_module.logging.info(
                    "[BL4ThirdPersonPOC] " f"CameraModeState.{name} = {value!r}"
                )
            except Exception as exc:
                owner_module.logging.warning(
                    "[BL4ThirdPersonPOC] Could not read "
                    f"CameraModeState.{name}: "
                    f"{type(exc).__name__}: {exc}"
                )

    except Exception as exc:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Could not inspect "
            "BlueprintUpdateCamera state: "
            f"{type(exc).__name__}: {exc}"
        )

    owner_module.logging.info(
        "[BL4ThirdPersonPOC] " "===== END BLUEPRINT UPDATE CAMERA ====="
    )
