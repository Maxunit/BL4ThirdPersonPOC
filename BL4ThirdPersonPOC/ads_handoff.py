"""Weapon, camera and reticle identities during native ADS transitions.

Equip callbacks count observations and publish presentation readiness. They never
change ZoomState, force a pose, or restore saved native input flags.
"""
from __future__ import annotations
from typing import Any
from unrealsdk import logging
from . import hybrid_ads, ads_zoom_modifiers


def _request_tps_reticle_publish_impl(reason: str, *, owner_module) -> str:
    """Publish for an observed event; retain guarded readiness refusals."""
    mod = owner_module
    status = mod._publish_tps_reticle(reason)
    mod._reticle_publish_pending = status in ("gate_skipped", "unstable_snapshot")
    state = mod._ads_tps_state
    if isinstance(state, dict):
        state["reticle_readiness_seen"] = None
        state["reticle_publish_weapon"] = state.get("weapon_address", 0)
        state["reticle_last_event"] = reason
        state["reticle_last_status"] = status
    logging.info(
        "[BL4ThirdPersonPOC] TPS_RETICLE_EVENT_RESULT "
        f"reason={reason!r}, status={status!r}, "
        f"gate_fail={mod._reticle_gate_last_fail!r}, pending={mod._reticle_publish_pending}"
    )
    return status


def _retire_reticle_rebind(mod):
    state = mod._ads_handoff
    if state.get("reticle_rebind_active"):
        state["reticle_rebind_active"] = False
        state["reticle_rebind_completions"] += 1
    state["character_handoff_active"] = False


def _publish_equipped_reticle(obj, args, *, owner_module):
    """The native equip body can hide a model published at ADS entry.

    Every actual local POST validates the current presentation identity. The
    callback ordinal belongs to native rearm bookkeeping, not HUD visibility.
    Publisher gates still validate the native weapon owner, readiness and model.
    """
    mod = owner_module
    ads = mod._ads_tps_state
    event_weapon = mod._ads_object_address(getattr(args, "EventWeapon", None))
    if not (
        mod._ads_active and mod._ads_route == "tps"
        and isinstance(ads, dict) and ads.get("phase") == "ads"
        and event_weapon and event_weapon == ads.get("weapon_address")
        == mod._ads_handoff.get("route_weapon")
        and mod._ads_object_address(obj) == mod._ads_collector_address != 0
    ):
        return
    pc, pawn, camera = mod._get_runtime()
    if pc is None or pawn is None or camera is None:
        return
    weapon = camera.CameraModeInputs.Weapon
    if not (
        mod._ads_object_address(camera) == ads.get("manager_address")
        and mod._ads_object_address(weapon) == event_weapon
        and int(pawn.ZoomState.State) in (1, 2)
    ):
        return
    status = mod._request_tps_reticle_publish("weapon_equipped_post")
    # A successful, guarded publication for an active local weapon settles
    # the presentation rebind even when only one callback remained after entry.
    # This does not fabricate a pair or relax the native rearm/modifier gates.
    if status in ("published", "already_visible") and str(weapon.CurrentState) == "Active":
        _retire_reticle_rebind(mod)


def _complete_ads_equip_pair(pawn, *, owner_module):
    """Retire the observed pair; native zoom admission remains authoritative."""
    mod = owner_module
    _retire_reticle_rebind(mod)
    if mod._ads_active and mod._ads_route == "tps" and int(pawn.ZoomState.State) in (1, 2):
        ads_zoom_modifiers.update(mod)

def _update_pending_tps_reticle_impl(*, owner_module) -> None:
    """Observe readiness changes for a single pending equip publication.

    No pose writes or time-based retry. The native publisher still validates
    build anchors, weapon owner, collector, and model identity before writing.
    A readiness tuple is attempted once; a changed tuple is a new observation.
    """
    mod = owner_module
    if not mod._reticle_publish_pending:
        return
    state = mod._ads_tps_state
    if not (
        isinstance(state, dict)
        and state.get("phase") == "ads"
        and mod._ads_active
        and mod._ads_route == "tps"
        and mod._third_person_enabled
        and mod._third_person_pushed
    ):
        mod._reticle_publish_pending = False
        return
    pc, pawn, manager = mod._get_runtime()
    if pawn is None or manager is None:
        return
    weapon = manager.CameraModeInputs.Weapon
    wa = mod._ads_object_address(weapon)
    if (
        not wa
        or wa != state.get("reticle_publish_weapon")
        or wa != state.get("weapon_address")
        or mod._ads_object_address(manager) != state.get("manager_address")
    ):
        mod._reticle_publish_pending = False
        return
    if (
        state.get("transition") is not None
        or manager.CameraModeState.bIsTransitioning
    ):
        return
    # Only reached after publisher construction verified its native anchors.
    if mod._reticle_publisher is None or mod._reticle_publish_faulted:
        mod._reticle_publish_pending = False
        return
    zoom = int(pawn.ZoomState.State)
    try:
        raw = mod._native_read(wa + 0xD2A, 0x3E)
    except Exception:
        mod._reticle_publish_pending = False
        raise
    ready = (
        zoom,
        raw[0],
        raw[0x36:0x3E],
        int(mod._ads_collector_address),
        int(mod._ads_handoff.get("equip_ordinal", 0)),
    )
    if ready == state.get("reticle_readiness_seen"):
        return
    state["reticle_readiness_seen"] = ready
    if zoom not in (1, 2) or raw[0] != 1:
        return
    status = mod._publish_tps_reticle("weapon_readiness_changed")
    state["reticle_last_event"] = "weapon_readiness_changed"
    state["reticle_last_status"] = status
    mod._reticle_publish_pending = status in ("gate_skipped", "unstable_snapshot")
    mod.logging.info(
        "[BL4ThirdPersonPOC] TPS_RETICLE_READINESS_RESULT "
        f"status={status!r}, zoom={zoom}, callbacks={ready[-1]}, "
        f"gate_fail={mod._reticle_gate_last_fail!r}"
    )


def _update_hybrid_ads_weapon_handoff_impl(
    pawn: Any,
    camera_manager: Any,
    ads_state: dict[str, Any],
    *,
    owner_module,
) -> bool:

    state = owner_module._ads_handoff
    if not (
        owner_module._ads_route == "tps"
        and owner_module._ads_active
        and ads_state.get("phase") == "ads"
    ):
        state["in_gap"] = False
        return False

    try:
        weapon = camera_manager.CameraModeInputs.Weapon
        weapon_address = owner_module._ads_object_address(weapon)
        expected_address = int(ads_state.get("weapon_address", 0))
        if weapon_address == expected_address:
            return False

        if weapon_address == 0:
            state["gap_frames"] += 1
            if not state["in_gap"]:
                state["in_gap"] = True
                state["gap_entries"] += 1
                state["incoming_weapon"] = 0
                state["collector_address"] = 0
                state["equip_ordinal"] = 0
                logging.info(
                    "[BL4ThirdPersonPOC] ADS_HANDOFF_GAP_PRESERVED "
                    f"outgoing=0x{expected_address:016X}"
                )
            owner_module._set_hybrid_tps_fov(
                float(
                    ads_state.get(
                        "last_fov",
                        ads_state.get("target_fov", ads_state["base_fov"]),
                    )
                )
            )
            return True

        category, source, evidence = owner_module._classify_ads_weapon(weapon)
        if category == "sniper_rifle" and not hybrid_ads.sniper_uses_tps(owner_module):
            # This migration changes the native camera mode while ADS is
            # held. Release any TPS Look owner before that Set, including
            # one rearmed after the Slide -> Default handoff.
            if (
                owner_module._native_active()
                or owner_module._active_native_state.get("ladder_default")
            ) and not owner_module._native_stop("tps_ads_to_sniper_pre"):
                raise RuntimeError("Recoil restore failed before FPS ADS migration")
            if ads_state.get("offset_overridden"):
                ads_state["mode_state"].BaseFOVOffset = ads_state["original_offset"]
            owner_module._reticle_publish_pending = False
            owner_module._ads_tps_state = None
            owner_module._ads_collector_address = 0
            owner_module._cleanup_ads_handoff("tps_to_sniper")
            state["route_weapon"] = weapon_address
            state["tps_to_fps"] += 1
            owner_module._ads_active = True
            owner_module._ads_route = "sniper_fps"
            owner_module._set_camera_offset(0.0, 0.0, 0.0)
            camera_manager.SetActorCameraMode(
                pawn,
                "Default",
                "",
                owner_module.ADS_CAMERA_TRANSITION_TIME,
                False,
                True,
            )
            logging.info(
                "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE_MIGRATED "
                "from='tps', to='sniper_fps', "
                f"weapon=0x{weapon_address:016X}, source={source!r}, "
                f"evidence={evidence}"
            )
            return True

        sight, sight_index, sight_name = owner_module._find_active_ads_sight(weapon)
        puppet_scale = owner_module._ads_attribute_float(sight, "PuppetZoomFOVScale")
        duration = owner_module._ads_attribute_float(sight, "ZoomDuration")
        if not 0.1 <= puppet_scale <= 1.5:
            raise RuntimeError(f"Unsafe PuppetZoomFOVScale {puppet_scale}")
        if (
            not owner_module.ADS_MIN_DURATION
            <= duration
            <= owner_module.ADS_MAX_DURATION
        ):
            raise RuntimeError(f"Unsafe ZoomDuration {duration}")

        collector = owner_module._find_ads_collector(weapon)
        base_fov = float(ads_state["base_fov"])
        target_fov, native_mag, effective_mag = owner_module._derive_ads_target_fov(
            base_fov,
            puppet_scale,
        )
        from .ads_zoom_settings import adjust, multiplier
        target_fov, native_mag, effective_mag = adjust(
            owner_module, category, base_fov, (target_fov, native_mag, effective_mag)
        )
        start_fov = owner_module._read_live_ads_fov(camera_manager)
        ads_state.update(
            zoom_multiplier=multiplier(owner_module, category),
            weapon_address=weapon_address,
            target_fov=target_fov,
            duration=duration,
            category=category,
            source=source,
            evidence=evidence,
            sight=f"{sight_index}:{sight_name}",
            puppet_scale=puppet_scale,
        )
        owner_module._ads_collector_address = owner_module._ads_object_address(
            collector
        )
        # Keep the equip callback and reticle gates bound to the newly active
        # TPS weapon once its sight and collector have both been resolved.
        state["route_weapon"] = weapon_address
        owner_module._begin_hybrid_ads_transition(
            "weapon_handoff_retarget",
            start_fov,
            target_fov,
        )
        state["incoming_weapon"] = weapon_address
        state["collector_address"] = owner_module._ads_collector_address
        state["equip_ordinal"] = 0
        state["in_gap"] = False
        state["rebinds"] += 1
        state["reticle_rebind_active"] = True
        state["reticle_rebind_arms"] += 1
        owner_module._request_tps_reticle_publish("weapon_handoff_rebound")
        logging.info(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_REBOUND "
            f"incoming=0x{weapon_address:016X}, category={category!r}, "
            f"start_fov={start_fov:.6f}, target_fov={target_fov:.6f}, "
            f"duration={duration:.6f}, native_mag={native_mag:.6f}, "
            f"effective_mag={effective_mag:.6f}"
        )
        return False
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        owner_module._ads_debug_error("weapon_handoff", exc)
        owner_module._cleanup_ads_handoff("weapon_handoff_error")
        owner_module._cancel_hybrid_ads("weapon_handoff_error")
        return True


def _update_hybrid_ads_route_reconciliation_impl(*, owner_module) -> None:
    """Migrate native-FPS ADS to TPS ADS from observed identities/mode."""
    state = owner_module._ads_handoff
    if not (
        owner_module._ads_active
        and owner_module._ads_route in ("sniper_fps", "fallback_fps")
    ):
        return
    if (
        not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._vehicle_camera_active
        or owner_module._ladder_active
        or owner_module._shop_camera_active
    ):
        return

    _pc, pawn, camera_manager = owner_module._get_runtime()
    if pawn is None or camera_manager is None:
        return
    try:
        weapon = camera_manager.CameraModeInputs.Weapon
        weapon_address = owner_module._ads_object_address(weapon)
        if not weapon_address:
            if not state.get("in_gap"):
                state["in_gap"] = True
                state["gap_entries"] += 1
                logging.info(
                    "[BL4ThirdPersonPOC] ADS_ROUTE_GAP_PRESERVED "
                    f"route={owner_module._ads_route!r}, outgoing="
                    f"0x{int(state.get('route_weapon', 0)):016X}"
                )
            state["gap_frames"] += 1
            return

        pending = state.get("route_pending")
        if isinstance(pending, dict):
            if weapon_address != int(pending.get("weapon_address", 0)):
                state["route_pending"] = None
            else:
                mode = str(camera_manager.GetActorCameraMode(pawn))
                if mode != "ThirdPerson":
                    return
                if pending.get("hybrid_same_weapon"):
                    # Hybrid scope exit: same weapon, no equip callbacks follow.
                    # Transfer ADS ownership after the observed native blend.
                    # The held TPS calibration survives the rendered scope FOV.
                    if bool(camera_manager.CameraModeState.bIsTransitioning):
                        return
                    resume = pending.get("hybrid_tps_resume")
                    if resume is not None:
                        owner_module._start_hybrid_tps_ads(
                            camera_manager, str(pending["category"]),
                            str(pending["source"]), str(pending["evidence"]),
                            resume_state=resume,
                        )
                    else:
                        owner_module._start_hybrid_tps_ads(
                            camera_manager, str(pending["category"]),
                            str(pending["source"]), str(pending["evidence"]),
                        )
                    owner_module._request_tps_reticle_publish("hybrid_scope_exit")
                    # The scope released the TPS Look owner; rearm it for the
                    # rest of this hold. Same weapon: no equip pair will follow.
                    state["native_tps_rearm"] = {
                        "identity": (
                            owner_module._ads_object_address(_pc),
                            owner_module._ads_object_address(pawn),
                            owner_module._ads_object_address(camera_manager),
                            weapon_address,
                        ),
                        "attempted": False,
                        "same_weapon": True,
                    }
                    logging.info(
                        "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE_MIGRATED "
                        f"from={pending['from_route']!r}, to='tps', "
                        f"weapon=0x{weapon_address:016X}, gate='hybrid_scope_exit'"
                    )
                    owner_module._apply_camera_offset()
                    return
                if hybrid_ads.active(owner_module) and bool(
                    camera_manager.CameraModeState.bIsTransitioning
                ):
                    # Hybrid weapon swap in the scope: read the TPS base FOV
                    # only after the ThirdPerson blend has settled.
                    return
                owner_module._start_hybrid_tps_ads(
                    camera_manager,
                    str(pending["category"]),
                    str(pending["source"]),
                    str(pending["evidence"]),
                )
                collector_address = int(owner_module._ads_collector_address)
                if not collector_address:
                    raise RuntimeError(
                        "TPS ADS collector unavailable after route migration"
                    )
                state["incoming_weapon"] = weapon_address
                state["collector_address"] = collector_address
                state["equip_ordinal"] = 0
                state["reticle_rebind_active"] = True
                state["reticle_rebind_arms"] += 1
                state["route_weapon"] = weapon_address
                state["fps_to_tps"] += 1
                # A native FPS route retired the previous Look owner. Keep a
                # one-shot request tied to this equip; lifecycle polling waits
                # for the callback pair and the settled TPS runtime.
                state["native_tps_rearm"] = {
                    "identity": (
                        owner_module._ads_object_address(_pc),
                        owner_module._ads_object_address(pawn),
                        owner_module._ads_object_address(camera_manager),
                        weapon_address,
                    ),
                    "attempted": False,
                }
                if hybrid_ads.active(owner_module):
                    # Scope-to-TPS migration waits for the camera blend. The
                    # incoming equip callbacks may already have run by then.
                    # Keep the rebind closed until lifecycle verifies the
                    # settled weapon/collector and successfully owns its Look.
                    # Do not fabricate callbacks or release zoom latches here.
                    state["native_tps_rearm"].update(
                        hybrid_settled_equip=True,
                        collector_address=collector_address,
                    )
                owner_module._request_tps_reticle_publish("fps_to_tps_route")
                logging.info(
                    "[BL4ThirdPersonPOC] ADS_RETICLE_REBIND_ARMED "
                    f"incoming=0x{weapon_address:016X}, "
                    f"collector=0x{collector_address:016X}, "
                    "gate='observed_equip_callbacks'"
                )
                logging.info(
                    "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE_MIGRATED "
                    f"from={pending['from_route']!r}, to='tps', "
                    f"weapon=0x{weapon_address:016X}, "
                    "gate='observed_third_person_mode'"
                )
                owner_module._apply_camera_offset()
                return

        expected_address = int(state.get("route_weapon", 0))
        if weapon_address == expected_address:
            state["in_gap"] = False
            return

        category, source, evidence = owner_module._classify_ads_weapon(weapon)
        state["in_gap"] = False
        if category == "sniper_rifle" and not hybrid_ads.sniper_uses_tps(owner_module):
            state["route_weapon"] = weapon_address
            logging.info(
                "[BL4ThirdPersonPOC] ADS_NATIVE_ROUTE_REBOUND "
                f"route={owner_module._ads_route!r}, weapon=0x{weapon_address:016X}"
            )
            return

        from_route = owner_module._ads_route
        state["route_pending"] = {
            "from_route": from_route,
            "weapon_address": weapon_address,
            "category": category,
            "source": source,
            "evidence": evidence,
        }
        camera_manager.SetActorCameraMode(
            pawn,
            "ThirdPerson",
            "",
            hybrid_ads.return_transition(
                owner_module, owner_module.ADS_CAMERA_TRANSITION_TIME
            ),
            False,
            True,
        )
        logging.info(
            "[BL4ThirdPersonPOC] HYBRID_ADS_ROUTE_MIGRATION_ARMED "
            f"from={from_route!r}, to='tps', "
            f"weapon=0x{weapon_address:016X}, category={category!r}, "
            "gate='observed_third_person_mode'"
        )
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"route_reconcile: {type(exc).__name__}: {exc}"
        owner_module._ads_debug_error("route_reconcile", exc)
        owner_module._cancel_hybrid_ads("route_reconcile_error")


def _arm_late_tps_ads_equip_handoff_impl(
    obj: Any,
    args: Any,
    *,
    owner_module,
) -> bool:
    """Adopt equip callbacks that arrive after a mid-swap TPS ADS start."""
    state = owner_module._ads_handoff
    if not (
        owner_module._ads_active
        and owner_module._ads_route == "tps"
        and not int(state.get("incoming_weapon", 0))
        and int(state.get("equip_ordinal", 0)) == 0
    ):
        return False

    try:
        ads_state = owner_module._ads_tps_state
        if not (isinstance(ads_state, dict) and ads_state.get("phase") == "ads"):
            return False

        event_weapon = getattr(args, "EventWeapon", None)
        event_address = owner_module._ads_object_address(event_weapon)
        collector_address = owner_module._ads_object_address(obj)
        route_weapon = int(state.get("route_weapon", 0))
        ads_weapon = int(ads_state.get("weapon_address", 0))
        if not (
            event_address
            and event_address == route_weapon
            and event_address == ads_weapon
            and collector_address
            and collector_address == int(owner_module._ads_collector_address)
        ):
            return False

        _pc, pawn, camera_manager = owner_module._get_runtime()
        if pawn is None or camera_manager is None:
            return False
        current_weapon = owner_module._ads_object_address(
            camera_manager.CameraModeInputs.Weapon
        )
        if current_weapon != event_address:
            return False

        state["incoming_weapon"] = event_address
        state["collector_address"] = collector_address
        state["equip_ordinal"] = 0
        state["reticle_rebind_active"] = True
        state["reticle_rebind_arms"] += 1
        state["late_equip_arms"] += 1
        logging.info(
            "[BL4ThirdPersonPOC] ADS_RETICLE_REBIND_LATE_ARMED "
            f"incoming=0x{event_address:016X}, "
            f"collector=0x{collector_address:016X}, "
            "gate='matching_post_start_equip_pre'"
        )
        return True
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"late_equip_arm: {type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_ERROR "
            f"stage='late_equip_arm', error={type(exc).__name__}: {exc}"
        )
        return False


def _hybrid_ads_weapon_equipped_pre_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    owner_module._native_last_attempt = None
    if owner_module._beam_active() and not owner_module._native_stop_beam(
        "weapon_equip"
    ):
        logging.error(
            "[BL4ThirdPersonPOC] Beam patch remains armed during weapon event"
        )
    owner_module._arm_late_tps_ads_equip_handoff(obj, args)
    state = owner_module._ads_handoff
    event_weapon = getattr(args, "EventWeapon", None)
    event_address = owner_module._ads_object_address(event_weapon)
    if not (
        int(state.get("equip_ordinal", 0)) < 2
        and event_address
        and event_address == int(state.get("incoming_weapon", 0))
        and owner_module._ads_object_address(obj)
        == int(state.get("collector_address", 0))
    ):
        return
    try:
        _pc, pawn, _manager = owner_module._get_runtime()
        if pawn is None:
            raise RuntimeError("Pawn unavailable at OnWeaponEquipped PRE")
        state["equip_pre"] += 1
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"equip_pre: {type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_ERROR "
            f"stage='equip_pre', error={type(exc).__name__}: {exc}"
        )


def _hybrid_ads_character_weapon_equipped_pre_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    """Bind presentation readiness to the local NotifyEquipped listener."""
    owner_module._native_last_attempt = None
    if owner_module._beam_active() and not owner_module._native_stop_beam(
        "character_weapon_equip"
    ):
        logging.error(
            "[BL4ThirdPersonPOC] Beam patch remains armed during character equip"
        )
    state = owner_module._ads_handoff
    state["character_equip_pre"] += 1
    if not (
        owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and owner_module._ads_active
        and owner_module._ads_route == "tps"
    ):
        return

    try:
        ads_state = owner_module._ads_tps_state
        if not (isinstance(ads_state, dict) and ads_state.get("phase") == "ads"):
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "tps_ads_state_unavailable"
            return

        _pc, pawn, camera_manager = owner_module._get_runtime()
        if pawn is None or camera_manager is None:
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "runtime_unavailable"
            return
        if owner_module._ads_object_address(obj) != owner_module._ads_object_address(
            pawn
        ):
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "nonlocal_character"
            return

        weapon_address = owner_module._ads_object_address(
            camera_manager.CameraModeInputs.Weapon
        )
        route_weapon = int(state.get("route_weapon", 0))
        ads_weapon = int(ads_state.get("weapon_address", 0))
        if not (
            weapon_address
            and weapon_address == route_weapon
            and weapon_address == ads_weapon
            and owner_module._ads_object_address(camera_manager)
            == int(ads_state.get("manager_address", 0))
        ):
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "identity_mismatch"
            logging.warning(
                "[BL4ThirdPersonPOC] ADS_CHARACTER_EQUIP_REFUSED "
                "reason='identity_mismatch', "
                f"current=0x{weapon_address:016X}, "
                f"ads=0x{ads_weapon:016X}, route=0x{route_weapon:016X}"
            )
            return

        incoming_weapon = int(state.get("incoming_weapon", 0))
        collector_address = int(state.get("collector_address", 0))
        if incoming_weapon and incoming_weapon != weapon_address:
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "incoming_mismatch"
            return
        if collector_address and collector_address != int(
            owner_module._ads_collector_address
        ):
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "collector_mismatch"
            return
        if int(state.get("equip_ordinal", 0)) >= 2:
            state["character_equip_refusals"] += 1
            state["character_equip_last_reason"] = "pair_already_complete"
            return

        if not incoming_weapon:
            if not int(owner_module._ads_collector_address):
                state["character_equip_refusals"] += 1
                state["character_equip_last_reason"] = "collector_unavailable"
                return
            state["incoming_weapon"] = weapon_address
            state["collector_address"] = int(owner_module._ads_collector_address)
            state["equip_ordinal"] = 0
            state["reticle_rebind_active"] = True
            state["reticle_rebind_arms"] += 1
            state["character_equip_arms"] += 1
            action = "armed"
        else:
            state["character_equip_reuses"] += 1
            action = "reused"

        state["character_handoff_active"] = True
        state["character_equip_last_reason"] = action
        logging.info(
            "[BL4ThirdPersonPOC] ADS_CHARACTER_EQUIP_HANDOFF "
            f"action={action!r}, weapon=0x{weapon_address:016X}, "
            f"collector=0x{int(state.get('collector_address', 0)):016X}, "
            f"callbacks={int(state.get('equip_ordinal', 0))}, "
            f"{owner_module._ads_zoom_fields(pawn)}"
        )
    except Exception as exc:
        state["character_equip_errors"] += 1
        state["errors"] += 1
        state["character_equip_last_reason"] = f"{type(exc).__name__}: {exc}"
        state["last_error"] = f"character_equip_pre: {type(exc).__name__}: {exc}"
        state["character_handoff_active"] = False
        logging.error(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_ERROR "
            f"stage='character_equip_pre', "
            f"error={type(exc).__name__}: {exc}"
        )


def _hybrid_ads_character_weapon_equipped_post_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    state = owner_module._ads_handoff
    state["character_equip_post"] += 1
    if not state.get("character_handoff_active"):
        return
    logging.info(
        "[BL4ThirdPersonPOC] ADS_CHARACTER_EQUIP_POST "
        f"character=0x{owner_module._ads_object_address(obj):016X}, "
        f"weapon=0x{int(state.get('incoming_weapon', 0)):016X}, "
        f"callbacks={int(state.get('equip_ordinal', 0))}, "
        "gate='awaiting_collector_pair'"
    )


def _hybrid_ads_weapon_equipped_post_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    owner_module,
) -> None:
    # Entry can occur inside the native callback, after our PRE ran. Bind the
    # resulting current identity here as well, before counting the real POST.
    owner_module._arm_late_tps_ads_equip_handoff(obj, args)
    state = owner_module._ads_handoff
    event_weapon = getattr(args, "EventWeapon", None)
    event_address = owner_module._ads_object_address(event_weapon)
    matched_pair = (
        int(state.get("equip_ordinal", 0)) < 2
        and event_address
        and event_address == int(state.get("incoming_weapon", 0))
        and owner_module._ads_object_address(obj)
        == int(state.get("collector_address", 0))
    )
    try:
        if matched_pair:
            _pc, pawn, _manager = owner_module._get_runtime()
            if pawn is None:
                raise RuntimeError("Pawn unavailable at OnWeaponEquipped POST")
            state["equip_post"] += 1
            state["equip_ordinal"] += 1
            if state["equip_ordinal"] >= 2:
                _complete_ads_equip_pair(pawn, owner_module=owner_module)
        _publish_equipped_reticle(obj, args, owner_module=owner_module)
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"equip_post: {type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_ERROR "
            f"stage='equip_post', error={type(exc).__name__}: {exc}"
        )


def _reset_ads_handoff_debug_impl(*, owner_module) -> None:
    owner_module._ads_handoff = {
        "held": False,
        "in_gap": False,
        "incoming_weapon": 0,
        "collector_address": 0,
        "equip_ordinal": 0,
        "reticle_rebind_active": False,
        "reticle_rebind_arms": 0,
        "late_equip_arms": 0,
        "character_handoff_active": False,
        "character_equip_pre": 0,
        "character_equip_post": 0,
        "character_equip_arms": 0,
        "character_equip_reuses": 0,
        "character_equip_refusals": 0,
        "character_equip_errors": 0,
        "character_equip_last_reason": "",
        "reticle_rebind_completions": 0,
        "reticle_rebind_cancellations": 0,
        "route_weapon": 0,
        "route_pending": None,
        "gap_entries": 0,
        "gap_frames": 0,
        "rebinds": 0,
        "tps_to_fps": 0,
        "fps_to_tps": 0,
        "equip_pre": 0,
        "equip_post": 0,
        "errors": 0,
        "last_error": "",
    }


def _cleanup_ads_handoff_impl(reason: str, *, owner_module) -> None:
    state = owner_module._ads_handoff
    if not state:
        return
    if state.get("reticle_rebind_active"):
        state["reticle_rebind_cancellations"] += 1
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] ADS_RETICLE_REBIND_CANCELLED "
            f"reason={reason!r}, callbacks={state.get('equip_ordinal', 0)}"
        )
    state["reticle_rebind_active"] = False
    state["in_gap"] = False
    state["incoming_weapon"] = 0
    state["collector_address"] = 0
    state["equip_ordinal"] = 0
    state["character_handoff_active"] = False
    state["route_weapon"] = 0
    state["route_pending"] = None
    state.pop("native_tps_rearm", None)

