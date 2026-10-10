"""Coordinate held-ADS weapon equip, route selection and reticle readiness.

The loader owns handoff dictionaries and registers PRE/POST callbacks. Incoming
weapon, camera and collector identities must agree before pose/latch publication.
Outgoing zoom latches are masked and restored through the observed equip pair;
settled equip first restores native zoom modifiers, then publishes the reticle.
Transient refusals wait for later existing callbacks; attempts and faults are
bounded by identity. FOV blending uses existing camera updates, not new timers.
"""

from __future__ import annotations

from typing import Any
import time
from unrealsdk.hooks import Block
from unrealsdk import logging
from . import ads_zoom_modifiers
from . import hybrid_ads


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
        and mod._ads_handoff.get("held")
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
        or mod._ads_handoff.get("latch_active")
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
        state.get("held")
        and owner_module._ads_route == "tps"
        and owner_module._ads_active
        and ads_state.get("phase") == "ads"
    ):
        state["in_gap"] = False
        return False

    try:
        if state["latch_active"]:
            owner_module._start_ads_handoff_latch_mask(pawn, "frame_enforcement")

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
            state["held"] = True
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
        state.get("held")
        and owner_module._ads_active
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
        state.get("held")
        and owner_module._ads_active
        and owner_module._ads_route == "tps"
        and not int(state.get("incoming_weapon", 0))
        and int(state.get("equip_ordinal", 0)) == 0
        and not state.get("latch_active")
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
        state.get("held")
        and int(state.get("equip_ordinal", 0)) < 2
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
        owner_module._start_ads_handoff_latch_mask(pawn, "equip_pre")
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
    """Begin the equip mask at the first proven NotifyEquipped listener."""
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
        and state.get("held")
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
        owner_module._start_ads_handoff_latch_mask(pawn, "character_equip_pre")
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
        try:
            owner_module._ads_restore_handoff_latches("character_equip_pre_error")
        except Exception:
            pass
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
    state = owner_module._ads_handoff
    event_weapon = getattr(args, "EventWeapon", None)
    event_address = owner_module._ads_object_address(event_weapon)
    if not (
        state.get("held")
        and int(state.get("equip_ordinal", 0)) < 2
        and event_address
        and event_address == int(state.get("incoming_weapon", 0))
        and owner_module._ads_object_address(obj)
        == int(state.get("collector_address", 0))
    ):
        return
    try:
        _pc, pawn, _manager = owner_module._get_runtime()
        if pawn is None:
            raise RuntimeError("Pawn unavailable at OnWeaponEquipped POST")
        state["equip_post"] += 1
        state["equip_ordinal"] += 1
        owner_module._start_ads_handoff_latch_mask(pawn, "equip_post")
        if state["equip_ordinal"] >= 2:
            owner_module._release_ads_handoff_latches(pawn, "equip_callback_pair")
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"equip_post: {type(exc).__name__}: {exc}"
        logging.error(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_ERROR "
            f"stage='equip_post', error={type(exc).__name__}: {exc}"
        )


def _start_hybrid_tps_ads_impl(
    camera_manager: Any,
    category: str,
    source: str,
    evidence: str,
    prepared_collector_address: int = 0,
    *,
    resume_state: Any = None,
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
    owner_module._ads_handoff["held"] = True
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
        owner_module._begin_hybrid_ads_transition("zoom_in", base_fov, target_fov)
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
    owner_module._cleanup_ads_handoff("tps_ads_complete", clear_held=True)
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
    if owner_module._ads_press_intent.get("pending"):
        try:
            _pc, pawn, camera_manager = owner_module._get_runtime()
            if pawn is not None and camera_manager is not None:
                if owner_module._reconcile_pending_ads_press_weapon(
                    pawn,
                    camera_manager,
                    "OnZoomInChange.PRE",
                    collector_address=object_address,
                ) and owner_module._native_zoom_confirms_ads(pawn):
                    owner_module._activate_confirmed_ads_press(
                        pawn,
                        camera_manager,
                        "native_zoom_event",
                    )
        except Exception as exc:
            owner_module._ads_press_intent["errors"] += 1
            owner_module._ads_press_intent["last_error"] = (
                f"deferred_zoom_event: {type(exc).__name__}: {exc}"
            )
            owner_module._ads_debug_error("deferred_zoom_event", exc)
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


def _reset_ads_handoff_debug_impl(*, owner_module) -> None:
    owner_module._ads_handoff = {
        "held": False,
        "in_gap": False,
        "latch_active": False,
        "saved_latches": None,
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
        "pose_commit_attempts": 0,
        "pose_commits": 0,
        "pose_commit_skips": 0,
        "route_weapon": 0,
        "route_pending": None,
        "gap_entries": 0,
        "gap_frames": 0,
        "rebinds": 0,
        "tps_to_fps": 0,
        "fps_to_tps": 0,
        "equip_pre": 0,
        "equip_post": 0,
        "latch_writes": 0,
        "latch_releases": 0,
        "errors": 0,
        "last_error": "",
    }


def _ads_write_zoom_latches_impl(
    pawn: Any,
    *,
    wants: bool,
    pending: bool,
    owner_module,
) -> None:
    zoom = pawn.ZoomState
    zoom.bWantsToZoom = bool(wants)
    zoom.bPendingZoom = bool(pending)
    if bool(zoom.bWantsToZoom) != bool(wants) or bool(zoom.bPendingZoom) != bool(
        pending
    ):
        raise RuntimeError("Zoom latch verification failed")
    owner_module._ads_handoff["latch_writes"] += 1


def _ads_restore_handoff_latches_impl(reason: str, *, owner_module) -> None:
    state = owner_module._ads_handoff
    if not state.get("latch_active"):
        return
    try:
        _pc, pawn, _manager = owner_module._get_runtime()
        if pawn is not None:
            saved = state.get("saved_latches") or {}
            owner_module._ads_write_zoom_latches(
                pawn,
                wants=bool(saved.get("wants", state.get("held", False))),
                pending=bool(saved.get("pending", False)),
            )
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] ADS_HANDOFF_LATCHES_RESTORED " f"reason={reason!r}"
            )
    finally:
        state["latch_active"] = False


def _cleanup_ads_handoff_impl(
    reason: str, *, clear_held: bool = False, owner_module
) -> None:
    state = owner_module._ads_handoff
    if not state:
        return
    try:
        owner_module._ads_restore_handoff_latches(reason)
    except Exception as exc:
        state["errors"] += 1
        state["last_error"] = f"latch_cleanup: {type(exc).__name__}: {exc}"
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
    if clear_held:
        state["held"] = False


def _start_ads_handoff_latch_mask_impl(pawn: Any, reason: str, *, owner_module) -> None:
    # Preserve native ADS intent for the local held-TPS handoff, as verified
    # by the latch-mask A/B probe. Retain bookkeeping and release/commit.
    state = owner_module._ads_handoff
    preserve_native_latches = False
    if (
        pawn is not None
        and not owner_module._vehicle_camera_active
        and owner_module._third_person_enabled
        and owner_module._ads_active
        and owner_module._ads_route == "tps"
        and state.get("held")
    ):
        _pc, local_pawn, _camera = owner_module._get_runtime()
        local_address = owner_module._ads_object_address(local_pawn)
        preserve_native_latches = bool(
            local_pawn is not None
            and local_address
            and local_address == owner_module._ads_object_address(pawn)
        )
    if not state["latch_active"]:
        zoom = pawn.ZoomState
        state["saved_latches"] = {
            "wants": bool(zoom.bWantsToZoom),
            "pending": bool(zoom.bPendingZoom),
        }
        state["latch_active"] = True
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_LATCH_TRACKED "
            f"reason={reason!r}, native_intent={preserve_native_latches}, "
            f"{owner_module._ads_zoom_fields(pawn)}"
        )
    if not preserve_native_latches:
        owner_module._ads_write_zoom_latches(pawn, wants=False, pending=False)


def _commit_ads_handoff_pose_impl(pawn: Any, reason: str, *, owner_module) -> None:
    """Publish Zoomed only on the verified equip callback pair."""
    state = owner_module._ads_handoff
    state["pose_commit_attempts"] += 1
    zoom = pawn.ZoomState
    before_state = int(zoom.State)
    if before_state in (1, 2):
        state["pose_commit_skips"] += 1
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_POSE_COMMIT_SKIPPED "
            f"reason={reason!r}, native_state={before_state}"
        )
        return
    if before_state != 0:
        raise RuntimeError(f"Unsafe pose-commit source state {before_state}")
    zoom.State = type(zoom.State)(2)
    if int(zoom.State) != 2:
        raise RuntimeError(f"Zoomed pose-commit verification failed: {zoom.State!r}")
    state["pose_commits"] += 1
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] ADS_HANDOFF_POSE_COMMITTED "
        f"reason={reason!r}, before={before_state}, after={int(zoom.State)}, "
        f"wants={bool(zoom.bWantsToZoom)}, "
        f"pending={bool(zoom.bPendingZoom)}, "
        f"ticking={bool(zoom.bTickingZoom)}, "
        f"incoming=0x{int(state.get('incoming_weapon', 0)):016X}"
    )


def _release_ads_handoff_latches_impl(pawn: Any, reason: str, *, owner_module) -> None:
    state = owner_module._ads_handoff
    if not state["latch_active"]:
        return
    owner_module._ads_write_zoom_latches(pawn, wants=True, pending=True)
    state["latch_active"] = False
    state["latch_releases"] += 1
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] ADS_HANDOFF_LATCH_RELEASED "
        f"reason={reason!r}, callbacks={state['equip_ordinal']}"
    )
    if state.get("reticle_rebind_active"):
        state["reticle_rebind_active"] = False
        state["reticle_rebind_completions"] += 1
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] ADS_HANDOFF_CALLBACK_PAIR_COMPLETED "
            f"incoming=0x{int(state.get('incoming_weapon', 0)):016X}, "
            f"callbacks={state['equip_ordinal']}"
        )
    state["character_handoff_active"] = False
    if (
        state.get("held")
        and owner_module._ads_route == "tps"
        and owner_module._ads_active
        and int(state.get("incoming_weapon", 0))
        and int(state.get("equip_ordinal", 0)) >= 2
    ):
        owner_module._commit_ads_handoff_pose(pawn, reason)
        # Restore incoming weapon modifiers before exposing its ADS reticle.
        # If readiness is incomplete, the camera update retains the same guard
        # and retries once the handoff is settled; applied identities deduplicate.
        ads_zoom_modifiers.update(owner_module)
        owner_module._request_tps_reticle_publish("equip_handoff_complete")
