"""TPS ADS FOV presentation and collector notifications.

Native zoom owns gameplay state. Equip and reticle identity bookkeeping lives in
ads_handoff; input and authoritative native-state reconciliation in ads_control.
"""

from __future__ import annotations

from typing import Any
import time
from unrealsdk.hooks import Block
from unrealsdk import logging
from . import hybrid_ads


def _start_hybrid_tps_ads_impl(
    camera_manager: Any,
    category: str,
    source: str,
    evidence: str,
    prepared_collector_address: int = 0,
    *,
    resume_state: Any = None,
    base_calibration: Any = None,
    owner_module,
) -> None:

    _pc, local_pawn, _camera = owner_module._get_runtime()
    if (
        owner_module._beam_active()
        and (
            local_pawn is None
            or not owner_module._ads_beam_can_hold(camera_manager, local_pawn)
        )
        and not owner_module._native_stop_beam("ads_start")
    ):
        raise RuntimeError("Beam restore failed before TPS ADS")
    owner_module._cleanup_ads_handoff("tps_ads_start")
    # A scope FOV fade must end at its native value before it is captured below.
    hybrid_ads.finish_fov_fade(owner_module)

    weapon = camera_manager.CameraModeInputs.Weapon
    if weapon is None:
        raise RuntimeError("No equipped weapon is available")
    sight, sight_index, sight_name = owner_module._find_active_ads_sight(weapon)
    puppet_scale = owner_module._ads_attribute_float(sight, "PuppetZoomFOVScale")
    duration = owner_module._ads_attribute_float(sight, "ZoomDuration")
    if not 0.1 <= puppet_scale <= 1.5:
        raise RuntimeError(f"Unsafe PuppetZoomFOVScale {puppet_scale}")
    if not owner_module.ADS_MIN_DURATION <= duration <= owner_module.ADS_MAX_DURATION:
        raise RuntimeError(f"Unsafe ZoomDuration {duration}")

    collector_address = int(prepared_collector_address)
    if not collector_address:
        collector = owner_module._find_ads_collector(weapon)
        collector_address = owner_module._ads_object_address(collector)
    if not collector_address:
        raise RuntimeError("ADS collector address is zero")
    if resume_state is not None:
        if not hybrid_ads.valid_tps_resume(owner_module, camera_manager, weapon, resume_state):
            raise RuntimeError("Hybrid TPS resume owner changed")
        # CameraCache can still contain a blended scope FOV. Reuse the TPS
        # calibration from this same held aim instead of treating it as hip FOV.
        base_fov = float(resume_state["base_fov"])
    elif base_calibration is not None:
        base_fov = float(base_calibration[0])
    else:
        base_fov = owner_module._read_live_ads_fov(camera_manager)
    target_fov, native_mag, effective_mag = owner_module._derive_ads_target_fov(
        base_fov,
        puppet_scale,
    )
    from .ads_zoom_settings import adjust, multiplier
    target_fov, native_mag, effective_mag = adjust(
        owner_module, category, base_fov, (target_fov, native_mag, effective_mag)
    )
    mode_state = camera_manager.CameraModeState
    original_offset = (float(resume_state["original_offset"]) if resume_state is not None
                       else float(base_calibration[1]) if base_calibration is not None
                       else float(mode_state.BaseFOVOffset))
    owner_module._ads_tps_state = {
        "manager_address": owner_module._ads_object_address(camera_manager),
        "weapon_address": owner_module._ads_object_address(weapon),
        "mode_state": mode_state,
        "original_offset": original_offset,
        "base_fov": base_fov,
        "zoom_multiplier": multiplier(owner_module, category),
        "target_fov": target_fov,
        "duration": duration,
        "phase": "ads",
        "transition": None,
        "offset_overridden": False,
        "last_fov": base_fov,
        "category": category,
        "source": source,
        "evidence": evidence,
        "sight": f"{sight_index}:{sight_name}",
        "puppet_scale": puppet_scale,
    }
    owner_module._ads_collector_address = collector_address
    owner_module._ads_route = "tps"
    owner_module._ads_handoff["route_weapon"] = owner_module._ads_object_address(weapon)
    owner_module._ads_debug["tps_presses"] += 1
    owner_module._ads_debug["category_counts"][category] = (
        int(owner_module._ads_debug["category_counts"].get(category, 0)) + 1
    )
    if resume_state is not None:
        owner_module._set_hybrid_tps_fov(target_fov)
        hybrid_ads.complete_tps_resume(owner_module, camera_manager)
    else:
        start_fov = (owner_module._read_live_ads_fov(camera_manager)
                     if base_calibration is not None else base_fov)
        owner_module._begin_hybrid_ads_transition("zoom_in", start_fov, target_fov)
    logging.info(
        "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE "
        f"category={category!r}, route='tps', source={source!r}, "
        f"evidence={evidence}, base_fov={base_fov:.6f}, "
        f"target_fov={target_fov:.6f}, "
        f"puppet_scale={puppet_scale:.6f}, "
        f"native_magnification={native_mag:.6f}, "
        f"effective_magnification={effective_mag:.6f}, "
        f"duration={duration:.6f}, sight={sight_index}:{sight_name}"
    )


def _reverse_hybrid_tps_ads_impl(*, owner_module) -> None:
    state = owner_module._ads_tps_state
    if not isinstance(state, dict) or state.get("phase") != "released":
        raise RuntimeError("No TPS zoom-out is available to reverse")
    _pc, _pawn, camera_manager = owner_module._get_runtime()
    if camera_manager is None:
        raise RuntimeError("Camera manager unavailable during reversal")
    current_fov = owner_module._read_live_ads_fov(camera_manager)
    state["phase"] = "ads"
    owner_module._ads_debug["tps_presses"] += 1
    owner_module._ads_debug["reversed_zoom_outs"] += 1
    owner_module._begin_hybrid_ads_transition(
        "zoom_in_reversal",
        current_fov,
        float(state["target_fov"]),
    )
    logging.info(
        "[BL4ThirdPersonPOC] HYBRID_ADS_REVERSED "
        f"start_fov={current_fov:.6f}, "
        f"target_fov={float(state['target_fov']):.6f}, "
        f"duration={float(state['duration']):.6f}"
    )


def _release_hybrid_tps_ads_impl(*, owner_module) -> None:
    state = owner_module._ads_tps_state
    if not isinstance(state, dict) or state.get("phase") != "ads":
        raise RuntimeError("No active TPS ADS state is available")
    _pc, _pawn, camera_manager = owner_module._get_runtime()
    if camera_manager is None:
        raise RuntimeError("Camera manager unavailable during TPS release")
    transition = state.get("transition")
    if isinstance(transition, dict) and str(transition.get("kind", "")).startswith(
        "zoom_in"
    ):
        owner_module._ads_debug["interrupted_zoom_ins"] += 1
    current_fov = owner_module._read_live_ads_fov(camera_manager)
    state["phase"] = "released"
    owner_module._ads_debug["tps_releases"] += 1
    owner_module._begin_hybrid_ads_transition(
        "zoom_out",
        current_fov,
        float(state["base_fov"]),
    )


def _finish_hybrid_tps_ads_impl(*, owner_module) -> None:

    state = owner_module._ads_tps_state
    if isinstance(state, dict) and state.get("offset_overridden"):
        state["mode_state"].BaseFOVOffset = state["original_offset"]
    owner_module._reticle_publish_pending = False
    owner_module._ads_tps_state = None
    owner_module._ads_collector_address = 0
    owner_module._ads_route = "hip"
    owner_module._cleanup_ads_handoff("tps_ads_complete")
    owner_module._ads_debug["completed_cycles"] += 1


def _update_hybrid_tps_ads_impl(*, owner_module) -> None:
    state = owner_module._ads_tps_state
    if not isinstance(state, dict):
        return
    if (
        not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._vehicle_camera_active
        or owner_module._ladder_active
        or owner_module._shop_camera_active
    ):
        owner_module._cancel_hybrid_ads("camera_state_changed")
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        return
    if owner_module._ads_object_address(camera_manager) != state["manager_address"]:
        owner_module._cancel_hybrid_ads("camera_manager_changed", restore=False)
        return
    if owner_module._ffyl_camera_active(pawn, camera_manager):
        owner_module._cancel_hybrid_ads("ffyl_active")
        owner_module._clear_pending_ads_press("ffyl_active")
        return
    if owner_module._update_hybrid_ads_weapon_handoff(pawn, camera_manager, state):
        return
    weapon = camera_manager.CameraModeInputs.Weapon
    if owner_module._ads_object_address(weapon) != state["weapon_address"]:
        owner_module._cancel_hybrid_ads("weapon_changed")
        return

    from .ads_zoom_settings import adjust, multiplier
    factor = multiplier(owner_module, state.get('category'))
    if state.get('phase') == 'ads' and factor != state.get('zoom_multiplier', 1.0):
        derived = owner_module._derive_ads_target_fov(state['base_fov'], state['puppet_scale'])
        target, _native, _effective = adjust(owner_module, state.get('category'), state['base_fov'], derived)
        state['zoom_multiplier'] = factor
        state['target_fov'] = target
        owner_module._begin_hybrid_ads_transition(
            'settings_retarget', owner_module._read_live_ads_fov(camera_manager), target
        )
    transition = state.get("transition")
    if not isinstance(transition, dict):
        if state.get("phase") == "ads":
            owner_module._set_hybrid_tps_fov(float(state["target_fov"]))
            owner_module._ads_debug["hold_writes"] += 1
        return

    elapsed = time.perf_counter() - float(transition["started"])
    duration = max(owner_module.ADS_MIN_DURATION, float(transition["duration"]))
    alpha = min(1.0, elapsed / duration)
    eased = owner_module._ads_smoothstep(alpha)
    value = (
        float(transition["start_fov"])
        + (float(transition["target_fov"]) - float(transition["start_fov"])) * eased
    )
    owner_module._set_hybrid_tps_fov(value)
    if alpha < 1.0:
        return

    kind = str(transition["kind"])
    target = float(transition["target_fov"])
    state["transition"] = None
    owner_module._set_hybrid_tps_fov(target)
    logging.info(
        "[BL4ThirdPersonPOC] HYBRID_ADS_TRANSITION_COMPLETE "
        f"kind={kind!r}, target={target:.6f}, duration={duration:.6f}"
    )
    if kind == "zoom_out":
        owner_module._finish_hybrid_tps_ads()


def _cancel_hybrid_ads_impl(reason: str, *, restore: bool = True, owner_module) -> None:
    hybrid_ads.cancel_return_fov(owner_module, restore=restore)

    previous_route = owner_module._ads_route
    owner_module._clear_pending_ads_press(reason)
    owner_module._cleanup_ads_handoff(reason)
    state = owner_module._ads_tps_state
    if restore and isinstance(state, dict):
        try:
            _pc, _pawn, current_manager = owner_module._get_runtime()
            if (
                current_manager is not None
                and owner_module._ads_object_address(current_manager)
                == state["manager_address"]
            ):
                current_manager.CameraModeState.BaseFOVOffset = state["original_offset"]
        except Exception as exc:
            owner_module._ads_debug_error("cancel_restore", exc)
    owner_module._ads_active = False
    owner_module._ads_route = "hip"
    owner_module._reticle_publish_pending = False
    owner_module._ads_tps_state = None
    owner_module._ads_collector_address = 0
    if previous_route != "hip":
        owner_module._ads_debug["aborts"] = (
            int(owner_module._ads_debug.get("aborts", 0)) + 1
        )
        logging.warning(
            "[BL4ThirdPersonPOC] HYBRID_ADS_ABORT "
            f"reason={reason!r}, previous_route={previous_route!r}"
        )


def _hybrid_ads_zoom_change_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> Any:
    object_address = owner_module._ads_object_address(obj)
    from .ads_control import _controller
    # Notification arguments are presentation data, not the state authority.
    # Read the local pawn, never infer activation from a foreign collector.
    _controller(owner_module).update("OnZoomInChange")
    is_local = object_address == owner_module._ads_collector_address
    should_block = (
        is_local and owner_module._ads_route == "tps" and owner_module._ads_active
    )
    if should_block:
        owner_module._ads_debug["zoom_change_blocked"] += 1
        return Block
    pending_collector = int(
        owner_module._ads_press_intent.get("prepared_collector_address", 0)
    )
    pending_block = bool(
        owner_module._ads_press_intent.get("pending")
        and pending_collector
        and object_address == pending_collector
    )
    if pending_block:
        owner_module._ads_debug["pending_zoom_change_blocked"] += 1
        logging.info(
            "[BL4ThirdPersonPOC] "
            "ADS_PENDING_ON_ZOOM_IN_CHANGE_BLOCKED "
            f"collector=0x{pending_collector:016X}, "
            f"category="
            f"{owner_module._ads_press_intent.get('prepared_category', '')!r}"
        )
        return Block
    if is_local:
        owner_module._ads_debug["zoom_change_native"] += 1
    return None


def _hybrid_ads_zoomed_out_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> Any:
    from .ads_control import _controller
    _controller(owner_module).update("OnZoomedOut")
    is_local = (
        owner_module._ads_object_address(obj) == owner_module._ads_collector_address
    )
    should_block = (
        is_local and owner_module._ads_route == "tps" and owner_module._ads_active
    )
    if should_block:
        owner_module._ads_debug["stale_zoomed_out_blocked"] += 1
        return Block
    if is_local:
        owner_module._ads_debug["zoomed_out_native"] += 1
    return None


def _reset_hybrid_ads_debug_impl(*, owner_module) -> None:
    owner_module._ads_debug = {
        "started": time.perf_counter(),
        "tps_presses": 0,
        "tps_releases": 0,
        "sniper_presses": 0,
        "fallback_presses": 0,
        "native_releases": 0,
        "completed_cycles": 0,
        "interrupted_zoom_ins": 0,
        "reversed_zoom_outs": 0,
        "ignored_events": 0,
        "aborts": 0,
        "hold_writes": 0,
        "zoom_change_blocked": 0,
        "pending_zoom_change_blocked": 0,
        "zoom_change_native": 0,
        "stale_zoomed_out_blocked": 0,
        "zoomed_out_native": 0,
        "category_counts": {},
        "errors": 0,
        "last_error": "",
    }


def _set_hybrid_tps_fov_impl(value: float, *, owner_module) -> None:
    state = owner_module._ads_tps_state
    if not isinstance(state, dict):
        return
    safe_value = max(
        owner_module.ADS_MIN_SAFE_FOV,
        min(owner_module.ADS_MAX_SAFE_FOV, float(value)),
    )
    requested_offset = state["original_offset"] + (safe_value - state["base_fov"])
    state["mode_state"].BaseFOVOffset = requested_offset
    observed = float(state["mode_state"].BaseFOVOffset)
    if abs(observed - requested_offset) > 0.001:
        raise RuntimeError(
            "BaseFOVOffset verification failed: "
            f"requested={requested_offset}, observed={observed}"
        )
    state["offset_overridden"] = True
    state["last_fov"] = safe_value


def _begin_hybrid_ads_transition_impl(
    kind: str,
    start_fov: float,
    target_fov: float,
    *,
    owner_module,
) -> None:
    state = owner_module._ads_tps_state
    if not isinstance(state, dict):
        raise RuntimeError("TPS ADS state is unavailable")
    state["transition"] = {
        "kind": kind,
        "started": owner_module.time.perf_counter(),
        "start_fov": float(start_fov),
        "target_fov": float(target_fov),
        "duration": float(state["duration"]),
    }
    owner_module._set_hybrid_tps_fov(start_fov)


