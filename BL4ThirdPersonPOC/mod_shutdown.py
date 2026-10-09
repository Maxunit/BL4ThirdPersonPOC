"""Coordinate mod shutdown in explicit native ownership dependency order.

This module owns no runtime state and performs no SDK work at import time.
Subsystems keep their existing restore/retirement contracts; this coordinator
attempts independent stages and retains dependency groups on incomplete release.
It does not promise safe arbitrary reload or in-flight callback quiescence.
"""

from __future__ import annotations

from typing import Any


def shutdown(*, owner_module) -> None:
    """Clean independent owners, then release the shared camera dependency group.

    A failed beta restoration retains its native owner and blocks camera-stack,
    recoil and updater teardown. UI and visibility cleanup still get their own
    attempt. Never interpret an exception or a False result as released ownership.
    """
    from . import runtime_updates
    from . import npc_camera_visibility, placeable_targeting, npc_native_resume
    from . import ground_slam_camera, ffyl_strategy_runtime, pickup_registry, vehicle_camera, vehicle_control
    from . import omni, action_keys, native_aim_origin

    owner_module._respawn_camera_state = None

    cleanup_failures: list[str] = []

    def cleanup_stage(name: str, callback: Any, *, require_success=False) -> bool:
        try:
            result = callback()
            if require_success and result is not True:
                raise RuntimeError("Owner restoration incomplete")
            return True
        except Exception as exc:
            cleanup_failures.append(f"{name}: {type(exc).__name__}: {exc}")
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] DISABLE_STAGE_ERROR "
                f"stage={name!r}, error={type(exc).__name__}: {exc}"
            )
            return False

    # Omnidirectional movement first: it reads the camera/state flags, owns
    # runtime_updates routes and native detours that must restore while the
    # bound pawn, mesh and camera are still the ones it captured.
    omni_restored = cleanup_stage(
        "omni_movement",
        lambda: omni.shutdown(owner_module, "MOD_DISABLED"),
        require_success=True,
    )

    cleanup_stage(
        "pickup_registry", lambda: pickup_registry.stop(owner_module, "mod_disable"),
        require_success=True,
    )

    # These owners do not require popping the gameplay camera or restoring
    # WeaponLook. Visibility stops its producer and retains any deferred pins.
    cleanup_stage("menu_close", lambda: owner_module._menu_close("mod_disable"))
    cleanup_stage(
        "npc_visibility",
        lambda: npc_camera_visibility.shutdown(owner_module, "mod_disable"),
        require_success=True,
    )
    control_restored = cleanup_stage(
        "vehicle_control", vehicle_control.shutdown, require_success=True,
    )
    # Its widget-tick route must be gone before runtime_updates can close.
    keys_restored = cleanup_stage(
        "action_keys", action_keys.shutdown, require_success=True,
    )
    # Restores the 0xC8DA03 aim-trace detour and removes its widget-tick route.
    aim_restored = cleanup_stage(
        "aim_origin", native_aim_origin.shutdown, require_success=True,
    )
    vehicle_restored = cleanup_stage(
        'vehicle_camera', vehicle_camera.shutdown, require_success=True,
    )
    slam_restored = cleanup_stage(
        "ground_slam",
        lambda: ground_slam_camera.shutdown("lifecycle_shutdown"),
        require_success=True,
    )
    ffyl_restored = cleanup_stage(
        "ffyl",
        lambda: ffyl_strategy_runtime.shutdown(owner_module, "mod_disable"),
        require_success=True,
    )
    if not slam_restored:
        owner_module._ground_slam_beta_fault = True
    if not ffyl_restored:
        owner_module._ffyl_beta_fault = True
    if not (slam_restored and ffyl_restored and vehicle_restored and control_restored
            and omni_restored and keys_restored and aim_restored):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] DISABLE_CAMERA_GROUP_RETAINED "
            f"ground_slam_restored={slam_restored} ffyl_restored={ffyl_restored} "
            f"vehicle_camera_restored={vehicle_restored} vehicle_control_restored={control_restored} "
            f"omni_movement_restored={omni_restored} action_keys_restored={keys_restored} "
            f"aim_origin_restored={aim_restored}; "
            "dependent camera/native owners retained; restart game"
        )
        return
    if not cleanup_stage("runtime_updates", runtime_updates.shutdown, require_success=True):
        return
    owner_module._perf_probe["armed"] = False
    owner_module._perf_probe["complete"] = False
    owner_module._ffyl_native_resume_pending = False
    owner_module._native_npc_pending = False
    owner_module._native_ffyl_pending = False
    owner_module._native_ffyl_pending_pawn = 0
    owner_module._ffyl_early_handoff_armed = False
    try:
        owner_module._remove_ffyl_early_handoff_hook()
    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] FFYL_EARLY_HANDOFF_HOOK_REMOVE_FAILED "
            f"{type(exc).__name__}: {exc}"
        )

    def restore_weapon_native() -> bool:
        if owner_module._native_active() or owner_module._active_native_state.get(
            "ladder_default"
        ):
            if owner_module._native_stop("mod_disable") is not True:
                return False
        return (
            not owner_module._native_active()
            and not owner_module._active_native_state.get("ladder_default")
        )

    if not cleanup_stage("weapon_native", restore_weapon_native, require_success=True):
        # The camera-stack pop and ADS reset can replace the Look/runtime whose
        # ownership the failed recoil/beam restoration still needs to validate.
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] DISABLE_CAMERA_GROUP_RETAINED "
            "reason=weapon_native_restore_incomplete; restart game"
        )
        return

    def restore_ladder_guard() -> bool:
        if owner_module._active_native_state.get("ladder_guard") is not None:
            from . import native_ladder_guard

            native_ladder_guard.remove(owner_module)
        return owner_module._active_native_state.get("ladder_guard") is None

    if not cleanup_stage("ladder_guard", restore_ladder_guard, require_success=True):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] DISABLE_CAMERA_GROUP_RETAINED "
            "reason=ladder_guard_restore_incomplete; restart game"
        )
        return
    cleanup_stage("motion_reset", owner_module._dynamic_motion_reset)
    cleanup_stage("reticle_reset", owner_module._reset_reticle_publisher)
    cleanup_stage("mantle_reset", owner_module._reset_mantle_camera_state)
    owner_module._controller_r3_camera_state["pressed_at"] = None
    owner_module._controller_r3_camera_state["handled"] = False

    cleanup_stage("cancel_ads", lambda: owner_module._cancel_hybrid_ads("mod_disable"))

    # Remove the exact camera-stack entry owned by this mod. If runtime or
    # vehicle state makes that unsafe, ownership survives RLM as primitives
    # and a later game-thread update retries the pop.
    def remove_owned_camera() -> None:
        if not (
            owner_module._third_person_pushed
            or owner_module._camera_stack_owner.get("owned")
        ):
            return
        if owner_module._pop_third_person(reason="mod_disable"):
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] ThirdPerson camera removed " "during mod unload"
            )
        else:
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] ThirdPerson camera pop deferred "
                "during mod unload"
            )

    cleanup_stage("camera_stack_pop", remove_owned_camera)

    owner_module._third_person_enabled = False
    owner_module._ads_active = False
    owner_module._slide_active = False
    owner_module._slide_camera_recovery_pending = False
    owner_module._slide_camera_recovery_pawn = 0
    owner_module._camera_offset_gate_last = ""
    owner_module._ladder_active = False
    owner_module._shop_camera_active = False
    owner_module._ladder_pending_third_person_enabled = None
    owner_module._last_anim_slide_states.clear()

    if (
        not owner_module._vehicle_camera_active
        and not owner_module._camera_stack_owner.get("owned")
    ):
        cleanup_stage(
            "reset_camera_offset",
            lambda: owner_module._set_camera_offset(0.0, 0.0, 0.0),
        )

    # Stop the shared game-thread updater before restoring/freeing every
    # native interaction and item-card site it feeds. Every stage is isolated
    # so one failure cannot suppress the remaining cleanup.
    cleanup_stage("camera_updater", owner_module._remove_hooks)
    cleanup_stage(
        "menu_hook",
        lambda: (
            owner_module.remove_hook(
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.POST_UNCONDITIONAL,
                owner_module._MENU_UPDATE_HOOK,
            )
            if owner_module.has_hook(
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.POST_UNCONDITIONAL,
                owner_module._MENU_UPDATE_HOOK,
            )
            else None
        ),
    )
    cleanup_stage(
        "sdk_identifier_reconcile",
        lambda: owner_module._purge_mod_sdk_hooks(include_prompt=False),
    )

    def verify_camera_producers_stopped() -> bool:
        # Verify stable SDK identifiers as well as tracked paths: reload may
        # have reset bookkeeping without unregistering a published callback.
        tracked = set(owner_module._hooks_installed)
        tracked.add(owner_module.FIRST_PERSON_ANIM_HOOK)
        for function_path in tracked:
            if owner_module.has_hook(
                function_path, owner_module.Type.POST, owner_module.HOOK_IDENTIFIER
            ):
                return False
        return not owner_module.has_hook(
            owner_module.FIRST_PERSON_ANIM_HOOK,
            owner_module.Type.POST_UNCONDITIONAL,
            owner_module._MENU_UPDATE_HOOK,
        )

    if not cleanup_stage(
        "camera_producers_stopped",
        verify_camera_producers_stopped,
        require_success=True,
    ):
        # Keep native interaction/item-card allocations and their ownership
        # metadata reachable while a callback can still feed or reference them.
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] DISABLE_NATIVE_DEPENDENTS_RETAINED "
            "reason=camera_producer_still_registered; restart game"
        )
        return
    cleanup_stage("npc_completion", lambda: npc_native_resume.shutdown(owner_module))

    def remove_placeable():
        if not placeable_targeting.shutdown(owner_module):
            raise RuntimeError("Placeable candidate restoration incomplete")

    cleanup_stage("placeable_candidates", remove_placeable)
    cleanup_stage("npc_eligible", owner_module._remove_npc_eligible)
    cleanup_stage(
        "prompt_target",
        lambda: owner_module._remove_interaction_prompt_targeting(report=True),
    )
    cleanup_stage(
        "item_card", lambda: owner_module._remove_item_card_fusion(report=True)
    )
    cleanup_stage("blueprint_probe", owner_module._remove_blueprint_camera_probe)
    cleanup_stage("camera_mode_probe", owner_module._remove_camera_mode_probe)
    cleanup_stage("interaction_hooks", owner_module._remove_interaction_redirect)
    cleanup_stage("hybrid_ads_hooks", owner_module._remove_hybrid_ads_hooks)
    cleanup_stage("camera_lifecycle_hook", owner_module._remove_camera_lifecycle_hook)
    cleanup_stage("ffyl_native_pre_hook", owner_module._remove_ffyl_native_pre_hook)
    cleanup_stage(
        "native_quarantine_retry", owner_module._retry_native_patch_quarantine
    )

    owner_module._vehicle_camera_active = False

    owner_module._floor_pickup_router_address = 0
    owner_module._floor_pickup_native_ready = False

    cleanup_stage("ads_summary", lambda: owner_module._log_hybrid_ads_debug("disable"))
    cleanup_stage(
        "camera_lifecycle_summary",
        lambda: owner_module._log_camera_lifecycle_debug("disable"),
    )
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] SHUTDOWN_SAFETY_SUMMARY "
        f"hotpath_failures={owner_module._camera_hotpath_debug.get('total_failures', 0)}, "
        f"disable_stage_failures={len(cleanup_failures)}, "
        f"tracked_hooks={len(owner_module._hooks_installed) + len(owner_module._ads_hooks_installed)}, "
        f"native_quarantine={len(owner_module._native_patch_quarantine)}, "
        f"retired_native_stubs={len(owner_module._retired_native_stubs)}, "
        f"camera_owned={owner_module._camera_stack_owner.get('owned')}, "
        f"pending_pop={owner_module._camera_stack_owner.get('pending_pop')}, "
        f"pop_reason={owner_module._camera_stack_owner.get('reason')!r}, "
        f"owner_retirements={owner_module._camera_stack_owner.get('retirements', 0)}, "
        f"last_retire_reason="
        f"{owner_module._camera_stack_owner.get('last_retire_reason', '')!r}"
    )
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] Version " f"{owner_module.MOD_VERSION} disabled"
    )
