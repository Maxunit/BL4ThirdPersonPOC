"""Bind pickup geometry and selection to native item-card ownership.

The loader owns mutable state; game_hooks supplies collection/selection algorithms
and camera_math supplies geometry. Gate-2 records native witnesses; the final
selector consumes the published actor identity while preserving near/far policy.
Disable publication before restoring final and Gate-2 hooks. Readback proof and
stopped producers are required before retirement; failure retains quarantine.
Published executable pages and their control/ring buffers remain pinned.
"""

from __future__ import annotations

from typing import Any
from . import pickup_registry
from .native_hook_lifecycle import _native_restore_hook_impl, _native_release_hook_impl


def _item_card_read_component_bounds_impl(
    component: Any,
    *,
    owner_module,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
]:
    if owner_module._item_card_bounds_library is None:
        owner_module._item_card_bounds_library = owner_module.find_object(
            "KismetSystemLibrary",
            "/Script/Engine.Default__KismetSystemLibrary",
        )
    zero_a = owner_module._make_vector(0.0, 0.0, 0.0)
    zero_b = owner_module._make_vector(0.0, 0.0, 0.0)
    result = owner_module._item_card_bounds_library.GetComponentBounds(
        component,
        zero_a,
        zero_b,
        0.0,
    )
    values = list(result) if isinstance(result, tuple) else [result]
    vectors = [value for value in values if all(hasattr(value, axis) for axis in "XYZ")]
    if len(vectors) < 2:
        raise RuntimeError(f"Kismet GetComponentBounds returned {result!r}")
    center, extent = vectors[-2], vectors[-1]
    return (
        (float(center.X), float(center.Y), float(center.Z)),
        (float(extent.X), float(extent.Y), float(extent.Z)),
    )


def _item_card_build_numeric_geometry_impl(
    actor: Any, *, owner_module
) -> dict[str, Any]:
    return owner_module._item_card_build_numeric_geometry_core(
        actor,
        owner_module._item_card_read_component_bounds,
    )


def _item_card_candidate_geometry_impl(
    pc: Any,
    pawn_location: tuple[float, float, float],
    crosshair: tuple[float, float],
    actor: Any,
    *,
    owner_module,
) -> dict[str, Any] | None:
    return owner_module._item_card_candidate_geometry_core(
        pc,
        pawn_location,
        crosshair,
        actor,
        owner_module._item_card_read_component_bounds,
    )


def _item_card_collect_pickups_impl(
    state: dict[str, Any],
    *,
    force_geometry: bool = False,
    settle_addresses: set[int] | None = None,
    owner_module,
) -> tuple[dict[int, str], dict[int, dict[str, Any]], set[int]]:
    return owner_module._item_card_collect_pickups_core(
        state,
        force_geometry=force_geometry,
        settle_addresses=settle_addresses,
        _perf_probe=owner_module._perf_probe,
        find_all=lambda class_name: pickup_registry.collect(owner_module),
        _item_card_build_numeric_geometry=owner_module._item_card_build_numeric_geometry,
        _perf_record_metric=owner_module._perf_record_metric,
    )


def _perf_finish_item_refresh_impl(
    started_ns: int,
    paths: dict[int, str],
    old_paths: dict[int, str],
    rebuild_ns: int,
    *,
    owner_module,
) -> None:
    return owner_module._perf_finish_item_refresh_core(
        started_ns,
        paths,
        old_paths,
        rebuild_ns,
        owner_module._perf_probe,
        owner_module._perf_record_metric,
        owner_module._perf_record_top,
    )


def _item_card_disable_control_impl(state: dict[str, Any], *, owner_module) -> None:
    return owner_module._item_card_disable_control_core(state)


def _item_card_drain_gate2_impl(state: dict[str, Any], *, owner_module) -> None:
    hook = state["gate2_hook"]
    total = owner_module._item_card_hook_counter(hook)
    end = max(0, total - owner_module.ITEM_CARD_GATE2_SAFE_LAG)
    start = int(state["gate2_read_sequence"])
    oldest = max(0, end - owner_module.ITEM_CARD_GATE2_RING_CAPACITY)
    if start < oldest:
        state["gate2_overwritten"] += oldest - start
        start = oldest
    base_address = owner_module.ctypes.addressof(hook["buffer"])
    known = state["pickups"]
    for sequence in range(start, end):
        offset = (
            8
            + (sequence & owner_module.ITEM_CARD_GATE2_RING_MASK)
            * owner_module.ITEM_CARD_GATE2_RECORD_SIZE
        )
        record_address = base_address + offset
        recorded_sequence = int(
            owner_module.ctypes.c_uint64.from_address(record_address).value
        )
        actor = int(owner_module.ctypes.c_uint64.from_address(record_address + 8).value)
        if recorded_sequence != sequence:
            state["gate2_torn"] += 1
            continue
        state["gate2_records"] += 1
        if actor in known:
            state["gate2_known_records"] += 1
            state["gate2_last_seen_update"][actor] = state["update_index"]
    state["gate2_read_sequence"] = end


def _item_card_active_gate2_actors_impl(
    state: dict[str, Any],
    *,
    owner_module,
) -> dict[int, int]:
    return owner_module._item_card_active_gate2_actors_core(state)


def _item_card_refresh_pickups_impl(state: dict[str, Any], *, force: bool = False, owner_module) -> None:
    return pickup_registry.refresh(
        owner_module, state, force,
        lambda state, *, force=False: _item_card_refresh_pickups_original_impl(
            state, force=force, owner_module=owner_module
        ),
    )


def _item_card_refresh_pickups_original_impl(
    state: dict[str, Any],
    *,
    force: bool = False,
    owner_module,
) -> None:
    return owner_module._item_card_refresh_pickups_core(
        state,
        force=force,
        _perf_probe=owner_module._perf_probe,
        _item_card_collect_pickups=owner_module._item_card_collect_pickups,
        _perf_finish_item_refresh=owner_module._perf_finish_item_refresh,
        _retired_native_stubs=owner_module._retired_native_stubs,
        MAX_RETIRED_ITEM_CARD_STUBS=owner_module.MAX_RETIRED_ITEM_CARD_STUBS,
        _item_card_disable_control=owner_module._item_card_disable_control,
        _item_card_hook_counter=owner_module._item_card_hook_counter,
        _native_restore_hook=owner_module._native_restore_hook,
        _native_release_hook=owner_module._native_release_hook,
        _item_card_install_final_hook=owner_module._item_card_install_final_hook,
    )


def _item_card_should_override_impl(*, owner_module) -> bool:
    return bool(
        owner_module._item_card_diagnostic_enabled
        and owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and not owner_module._ads_active
        and not owner_module._vehicle_camera_active
        and not owner_module._ladder_active
        and not owner_module._shop_camera_active
    )


def _item_card_select_impl(
    state: dict[str, Any],
    pc: Any,
    pawn: Any,
    camera_manager: Any,
    *,
    owner_module,
) -> tuple[int, Any, dict[str, Any] | None, int, int]:
    return owner_module._item_card_select_core(state, pc, pawn, camera_manager)


def _item_card_publish_selection_impl(state, actor, actor_object, geometry, raw_count, eligible_count, *, owner_module):
    return pickup_registry.publish(
        owner_module, state, actor, actor_object, geometry, raw_count, eligible_count,
        lambda *args: _item_card_publish_selection_original_impl(*args, owner_module=owner_module),
    )


def _item_card_publish_selection_original_impl(
    state: dict[str, Any],
    actor: int,
    actor_object: Any,
    geometry: dict[str, Any] | None,
    raw_count: int,
    eligible_count: int,
    *,
    owner_module,
) -> None:
    return owner_module._item_card_publish_selection_core(
        state,
        actor,
        actor_object,
        geometry,
        raw_count,
        eligible_count,
    )

def _update_item_card_fusion_impl(*, owner_module) -> None:
    pickup_registry.checkpoint(owner_module, 'begin')
    try:
        return owner_module._update_item_card_fusion_core(
            _item_card_state=owner_module._item_card_state,
            _item_card_should_override=owner_module._item_card_should_override,
            _item_card_disable_control=owner_module._item_card_disable_control,
            _item_card_refresh_pickups=owner_module._item_card_refresh_pickups,
            _item_card_hook_counter=owner_module._item_card_hook_counter,
            _item_card_drain_gate2=owner_module._item_card_drain_gate2,
            _get_runtime=owner_module._get_runtime,
            _item_card_select=owner_module._item_card_select,
            _item_card_publish_selection=owner_module._item_card_publish_selection,
        )
    finally:
        pickup_registry.checkpoint(owner_module, 'end')


def _install_item_card_fusion_impl(*, owner_module) -> None:
    """Install Gate-2 observation and final actor selection with pinned control/rings."""
    if owner_module._item_card_state is not None:
        return
    pickup_registry.prepare(owner_module)
    if not owner_module._retry_native_patch_quarantine(kind="item_card"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Item-card fusion disabled: an older "
            "native patch remains quarantined"
        )
        return
    module_base = int(owner_module._kernel32.GetModuleHandleW(None) or 0)
    if not module_base:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Item-card fusion disabled: "
            "main module base unavailable"
        )
        return
    state: dict[str, Any] = {
        "ready": False,
        "active": False,
        "module_base": module_base,
        "gate2_hook": None,
        "final_hook": None,
        "pickups": {},
        "pickup_geometry": {},
        "geometry_settle_pending": set(),
        "geometry_settle_due": 0.0,
        "geometry_settle_started": {},
        "geometry_settle_stable": {},
        "geometry_settle_cursor": 0,
        "geometry_settle_updates": 0,
        "geometry_settle_completed": 0,
        "geometry_settle_timeouts": 0,
        "geometry_settle_max_center_drift": 0.0,
        "geometry_settle_max_axis_delta": 0.0,
        "geometry_background_cursor": 0,
        "geometry_background_attempts": 0,
        "geometry_background_updates": 0,
        "geometry_background_max_center_drift": 0.0,
        "geometry_collapse_rejections": 0,
        "geometry_cache_builds": 0,
        "geometry_cache_attempts": 0,
        "geometry_cache_errors": 0,
        "last_geometry_cache_error": None,
        "geometry_cache_seconds": 0.0,
        "geometry_cache_max_seconds": 0.0,
        "pickup_scan_errors": 0,
        "last_pickup_scan_error": None,
        "pickup_scans": 0,
        "pickup_scan_seconds": 0.0,
        "pickup_scan_max_seconds": 0.0,
        "pending_actor": None,
        "pending_samples": 0,
        "last_selection_source": None,
        "source_transition_events": 0,
        "source_transition_events_dropped": 0,
        "last_pickup_refresh": 0.0,
        "snapshot_rebuilds": 0,
        "update_index": 0,
        "gate2_read_sequence": 0,
        "gate2_last_seen_update": {},
        "gate2_snapshot_preserved": 0,
        "gate2_records": 0,
        "gate2_known_records": 0,
        "gate2_overwritten": 0,
        "gate2_torn": 0,
        "final_calls_completed": 0,
        "selector_samples": 0,
        "selector_seconds": 0.0,
        "selector_max_seconds": 0.0,
        "selector_ray_seconds": 0.0,
        "selector_candidate_seconds": 0.0,
        "selector_policy_seconds": 0.0,
        "numeric_candidate_tests": 0,
        "numeric_ray_hits": 0,
        "obb_inside_samples": 0,
        "obb_empty_samples": 0,
        "obb_overlap_samples": 0,
        "eligible_samples": 0,
        "eligible_overlap_samples": 0,
        "gate2_filtered_samples": 0,
        "near_ab_override": False,
        "near_ab_control_end": None,
        "native_max_world": {},
        "native_peer_center": {},
        "peer_max_world": {},
        "peer_source_actor": {},
        "peer_source_separation": {},
        "peer_limit_updates": 0,
        "surface_peer_samples": 0,
        "surface_peer_limit_updates": 0,
        "surface_peer_missing_geometry": 0,
        "surface_peer_invalid_geometry": 0,
        "surface_peer_min_clearance": owner_module.math.inf,
        "surface_peer_max_clearance": 0.0,
        "auto_peer_test_active": False,
        "fallback_samples": 0,
        "fallback_accepts": 0,
        "fallback_unlearned": 0,
        "fallback_farther": 0,
        "peer_bootstrap_accepts": 0,
        "peer_inward_accepts": 0,
        "peer_bootstrap_no_witness": 0,
        "peer_bootstrap_farther": 0,
        "forced_unlearned_actor": 0,
        "forced_native_saved": None,
        "forced_peer_capture": {},
        "forced_peer_witnesses": {},
        "forced_native_ignored": 0,
        "selection_updates": 0,
        "selection_events": [],
        "selection_events_dropped": 0,
        "geometry_errors": 0,
        "last_geometry_error": None,
        "live_lookup_misses": 0,
        "update_errors": 0,
        "last_update_error": None,
    }
    owner_module._item_card_state = state
    owner_module._active_native_state["item_card"] = state
    try:
        state["gate2_hook"] = owner_module._item_card_install_gate2_hook(module_base)
        state["gate2_read_sequence"] = owner_module._item_card_hook_counter(
            state["gate2_hook"]
        )
        owner_module._item_card_refresh_pickups(state, force=True)
        state["ready"] = True
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] Numeric item-card gate-2/OBB fusion "
            f"ready; visible_pickups={len(state['pickups'])}, "
            f"cached_geometry={len(state['pickup_geometry'])}"
        )
    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Item-card fusion disabled: "
            f"{type(exc).__name__}: {exc}"
        )
        owner_module._remove_item_card_fusion(report=False)


def _log_item_card_cleanup_summary_impl(state: dict[str, Any], *, owner_module) -> None:
    """Report diagnostics without participating in native restoration decisions."""
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] ITEM_CARD_SUMMARY "
        f"gate2_records={state['gate2_records']}, "
        f"known={state['gate2_known_records']}, "
        f"overwritten={state['gate2_overwritten']}, "
        f"torn={state['gate2_torn']}, "
        f"snapshot_gate2_preserved="
        f"{state['gate2_snapshot_preserved']}, "
        f"final_calls={state['final_calls_completed']}, "
        f"snapshots={state['snapshot_rebuilds']}, "
        f"samples={state['selector_samples']}, "
        f"obb_inside={state['obb_inside_samples']}, "
        f"obb_empty={state['obb_empty_samples']}, "
        f"obb_overlap={state['obb_overlap_samples']}, "
        f"eligible={state['eligible_samples']}, "
        f"eligible_overlap={state['eligible_overlap_samples']}, "
        f"filtered={state['gate2_filtered_samples']}, "
        f"fallback_samples={state['fallback_samples']}, "
        f"fallback_accepts={state['fallback_accepts']}, "
        f"fallback_unlearned={state['fallback_unlearned']}, "
        f"fallback_farther={state['fallback_farther']}, "
        f"peer_bootstrap_accepts="
        f"{state['peer_bootstrap_accepts']}, "
        f"peer_inward_accepts={state['peer_inward_accepts']}, "
        f"peer_no_witness={state['peer_bootstrap_no_witness']}, "
        f"peer_farther={state['peer_bootstrap_farther']}, "
        f"peer_limit_updates={state['peer_limit_updates']}, "
        f"surface_samples={state['surface_peer_samples']}, "
        f"surface_updates={state['surface_peer_limit_updates']}, "
        f"surface_missing_geometry="
        f"{state['surface_peer_missing_geometry']}, "
        f"surface_invalid_geometry="
        f"{state['surface_peer_invalid_geometry']}, "
        f"surface_min_clearance="
        f"{state['surface_peer_min_clearance']:.3f}, "
        f"surface_max_clearance="
        f"{state['surface_peer_max_clearance']:.3f}, "
        f"forced_native_ignored={state['forced_native_ignored']}, "
        f"source_transitions={state['source_transition_events']}, "
        f"source_transitions_dropped="
        f"{state['source_transition_events_dropped']}, "
        f"selection_updates={state['selection_updates']}, "
        f"selector_avg_ms="
        f"{state['selector_seconds'] * 1000.0 / max(1, state['selector_samples']):.4f}, "
        f"selector_max_ms="
        f"{state['selector_max_seconds'] * 1000.0:.4f}, "
        f"ray_avg_ms="
        f"{state['selector_ray_seconds'] * 1000.0 / max(1, state['selector_samples']):.4f}, "
        f"candidate_avg_ms="
        f"{state['selector_candidate_seconds'] * 1000.0 / max(1, state['selector_samples']):.4f}, "
        f"policy_avg_ms="
        f"{state['selector_policy_seconds'] * 1000.0 / max(1, state['selector_samples']):.4f}, "
        f"numeric_tests={state['numeric_candidate_tests']}, "
        f"ray_hits={state['numeric_ray_hits']}, "
        f"geometry_cache_builds={state['geometry_cache_builds']}, "
        f"geometry_cache_attempts={state['geometry_cache_attempts']}, "
        f"geometry_cache_errors={state['geometry_cache_errors']}, "
        f"geometry_cache_avg_ms="
        f"{state['geometry_cache_seconds'] * 1000.0 / max(1, state['geometry_cache_builds']):.4f}, "
        f"geometry_cache_max_ms="
        f"{state['geometry_cache_max_seconds'] * 1000.0:.4f}, "
        f"settle_updates={state['geometry_settle_updates']}, "
        f"settle_completed={state['geometry_settle_completed']}, "
        f"settle_timeouts={state['geometry_settle_timeouts']}, "
        f"settle_pending={len(state['geometry_settle_pending'])}, "
        f"settle_max_drift="
        f"{state['geometry_settle_max_center_drift']:.3f}, "
        f"settle_max_axis_delta="
        f"{state['geometry_settle_max_axis_delta']:.6f}, "
        f"background_attempts="
        f"{state['geometry_background_attempts']}, "
        f"background_updates="
        f"{state['geometry_background_updates']}, "
        f"background_max_drift="
        f"{state['geometry_background_max_center_drift']:.3f}, "
        f"collapse_rejections="
        f"{state['geometry_collapse_rejections']}, "
        f"pickup_scans={state['pickup_scans']}, "
        f"pickup_scan_avg_ms="
        f"{state['pickup_scan_seconds'] * 1000.0 / max(1, state['pickup_scans']):.4f}, "
        f"pickup_scan_max_ms="
        f"{state['pickup_scan_max_seconds'] * 1000.0:.4f}, "
        f"pickup_scan_errors={state['pickup_scan_errors']}, "
        f"geometry_errors={state['geometry_errors']}, "
        f"live_lookup_misses={state['live_lookup_misses']}, "
        f"update_errors={state['update_errors']}"
    )
    if state.get("last_geometry_cache_error"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Last item-card cache error: "
            f"{state['last_geometry_cache_error']}"
        )
    if state.get("last_pickup_scan_error"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Last pickup scan error: "
            f"{state['last_pickup_scan_error']}"
        )
    if state.get("last_geometry_error"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Last item-card geometry error: "
            f"{state['last_geometry_error']}"
        )
    if state.get("last_update_error"):
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] Last item-card update error: "
            f"{state['last_update_error']}"
        )


def _stop_item_card_publication_impl(state: dict[str, Any], *, owner_module) -> None:
    """Stop Python selection updates and verify the native override is disabled.

    This is not an in-flight reader barrier. Published code/data remain pinned by
    the existing retirement protocol. Missing published control is a failed stop.
    """
    state["ready"] = False
    state["active"] = False
    owner_module._item_card_disable_control(state)
    hook = state.get("final_hook")
    if isinstance(hook, dict):
        control = hook.get("control")
        if control is None:
            if hook.get("patch_attempted"):
                raise RuntimeError("Published item-card control missing")
        elif int(control.enabled) != 0 or int(control.selected_actor) != 0:
            raise RuntimeError("Item-card selection control remains enabled")


def _remove_item_card_fusion_impl(*, report: bool = True, owner_module) -> None:
    """Stop actor publication, restore final/Gate-2 code and retain unresolved storage.

    Each restoration has its own proof. Diagnostic reporting must not grant
    release permission or hide an incomplete native dependency.
    """
    pickup_registry.stop(owner_module, "item_card_remove")
    state = owner_module._item_card_state
    if not isinstance(state, dict):
        owner_module._item_card_bounds_library = None
        return
    if owner_module._active_native_state.get("item_card") is not state:
        owner_module._item_card_state = None
        return  # A different module instance already retired this owner.
    failures = []
    try:
        _stop_item_card_publication_impl(state, owner_module=owner_module)
    except Exception as exc:
        owner_module._quarantine_native_patch(
            "item_card", state, "selection_stop_incomplete"
        )
        owner_module._item_card_state = None
        if owner_module._active_native_state.get("item_card") is state:
            owner_module._active_native_state.pop("item_card", None)
        owner_module._item_card_bounds_library = None
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] ITEM_CARD_SELECTION_STOP_FAILED {type(exc).__name__}: {exc}"
        )
        return
    final_hook = state.get("final_hook")
    gate2_hook = state.get("gate2_hook")
    if isinstance(final_hook, dict):
        try:
            state["final_calls_completed"] += owner_module._item_card_hook_counter(
                final_hook
            )
        except Exception as exc:
            failures.append(exc)
        # Counter diagnostics must never suppress restoration of the code site.
        try:
            owner_module._native_restore_hook(final_hook)
        except Exception as exc:
            failures.append(exc)
    if isinstance(gate2_hook, dict):
        try:
            owner_module._native_restore_hook(gate2_hook)
        except Exception as exc:
            failures.append(exc)
    try:
        if report:
            _log_item_card_cleanup_summary_impl(state, owner_module=owner_module)
    except Exception as exc:
        # Formatting a diagnostic summary is not native release permission.
        failures.append(exc)
    for hook in (final_hook, gate2_hook):
        if isinstance(hook, dict):
            if hook.get("restored"):
                try:
                    owner_module._native_release_hook(hook)
                except Exception as exc:
                    failures.append(exc)
            else:
                owner_module.logging.error(
                    "[BL4ThirdPersonPOC] Refusing to free unrestored "
                    f"{hook.get('label', 'item-card')} stub"
                )
    unresolved = any(
        isinstance(hook, dict)
        and (not hook.get("restored") or int(hook.get("stub", 0)))
        for hook in (final_hook, gate2_hook)
    )
    if unresolved:
        owner_module._quarantine_native_patch(
            "item_card",
            state,
            "restore_or_free_incomplete",
        )
    owner_module._item_card_state = None
    if owner_module._active_native_state.get("item_card") is state:
        owner_module._active_native_state.pop("item_card", None)
    owner_module._item_card_bounds_library = None
    for failure in failures:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Item-card cleanup failure: "
            f"{type(failure).__name__}: {failure}"
        )


def _get_item_card_selected_pickup_impl(*, owner_module) -> Any:
    return pickup_registry.selected(
        owner_module,
        lambda: _get_item_card_selected_pickup_original_impl(owner_module=owner_module),
    )


def _get_item_card_selected_pickup_original_impl(*, owner_module) -> Any:
    state = owner_module._item_card_state
    if not isinstance(state, dict) or not state.get("ready") or not state.get("active"):
        return None
    control = state["final_hook"]["control"]
    selected_address = int(control.selected_actor)
    if not selected_address:
        return None
    # Re-resolve the numeric selection at the instant Use is pressed.  The
    # item-card selector intentionally retains no UObject across frames.
    for actor in tuple(owner_module.find_all("InventoryPickup")):
        try:
            if int(actor._get_address()) != selected_address:
                continue
            if bool(actor.bHidden):
                return None
            return actor
        except Exception:
            continue
    return None


def _item_card_install_gate2_hook_impl(
    module_base: int,
    *,
    owner_module,
) -> dict[str, Any]:
    target = module_base + owner_module.ITEM_CARD_GATE2_TARGET_RVA
    original = owner_module._native_read(
        target, owner_module.ITEM_CARD_GATE2_HOOK_LENGTH
    )
    if original != owner_module.ITEM_CARD_GATE2_TARGET_PREFIX:
        raise RuntimeError(
            "Gate-2 prefix mismatch: "
            f"expected={owner_module.ITEM_CARD_GATE2_TARGET_PREFIX.hex(' ')}, "
            f"actual={original.hex(' ')}"
        )
    continuation = owner_module._native_read(
        target + owner_module.ITEM_CARD_GATE2_HOOK_LENGTH,
        len(owner_module.ITEM_CARD_GATE2_CONTINUATION_PREFIX),
    )
    if continuation != owner_module.ITEM_CARD_GATE2_CONTINUATION_PREFIX:
        raise RuntimeError(
            "Gate-2 continuation mismatch: "
            f"expected={owner_module.ITEM_CARD_GATE2_CONTINUATION_PREFIX.hex(' ')}, "
            f"actual={continuation.hex(' ')}"
        )

    def build(_stub: int, trampoline: int):
        buffer = owner_module.ctypes.create_string_buffer(
            owner_module.ITEM_CARD_GATE2_BUFFER_SIZE
        )
        return (
            buffer,
            None,
            owner_module._item_card_build_gate2_stub(
                owner_module.ctypes.addressof(buffer),
                trampoline,
            ),
        )

    return owner_module._native_allocate_hook(
        target,
        original,
        owner_module.ITEM_CARD_GATE2_HOOK_LENGTH,
        build,
        "item-card gate-2",
    )


def _item_card_install_final_hook_impl(
    module_base: int,
    pickup_actors: tuple[int, ...],
    *,
    owner_module,
) -> dict[str, Any]:
    target = module_base + owner_module.ITEM_CARD_FINAL_TARGET_RVA
    original = owner_module._native_read(
        target, owner_module.ITEM_CARD_FINAL_HOOK_LENGTH
    )
    if original != owner_module.ITEM_CARD_FINAL_TARGET_PREFIX:
        raise RuntimeError(
            "Final-actor prefix mismatch: "
            f"expected={owner_module.ITEM_CARD_FINAL_TARGET_PREFIX.hex(' ')}, "
            f"actual={original.hex(' ')}"
        )
    continuation = owner_module._native_read(
        target + owner_module.ITEM_CARD_FINAL_HOOK_LENGTH,
        len(owner_module.ITEM_CARD_FINAL_CONTINUATION_PREFIX),
    )
    if continuation != owner_module.ITEM_CARD_FINAL_CONTINUATION_PREFIX:
        raise RuntimeError(
            "Final-actor continuation mismatch: "
            f"expected={owner_module.ITEM_CARD_FINAL_CONTINUATION_PREFIX.hex(' ')}, "
            f"actual={continuation.hex(' ')}"
        )

    def build(_stub: int, trampoline: int):
        buffer = owner_module.ctypes.create_string_buffer(
            owner_module.ITEM_CARD_FINAL_BUFFER_SIZE
        )
        control = owner_module._ITEM_CARD_CONTROL()
        return (
            buffer,
            control,
            owner_module._item_card_build_final_stub(
                owner_module.ctypes.addressof(control),
                owner_module.ctypes.addressof(buffer),
                trampoline,
                pickup_actors,
            ),
        )

    return owner_module._native_allocate_hook(
        target,
        original,
        owner_module.ITEM_CARD_FINAL_HOOK_LENGTH,
        build,
        "item-card final-actor",
    )


def _item_card_hook_counter_impl(hook: dict[str, Any], *, owner_module) -> int:
    return int(
        owner_module.ctypes.c_uint64.from_address(
            owner_module.ctypes.addressof(hook["buffer"])
        ).value
    )
