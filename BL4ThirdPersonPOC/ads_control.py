"""Native ADS presentation owner; input preparation never changes native zoom.

Input callbacks record intent. Existing camera updates and local zoom notifications
observe State 1/2 for entry and State 0/3 for exit. Physical release is independent
of Toggle ADS; no setting offset, latch writes or timing window is required.
"""
from __future__ import annotations
from typing import Any
from unrealsdk import logging
from . import hybrid_ads
from unrealsdk.unreal import WeakPointer


class ADSController:
    """Project native zoom onto the owned camera without owning game input."""

    def __init__(self, mod):
        self.mod = mod
        self.owners = None
        self.last_state = None
        self.entries = 0
        self.exits = 0
        self.last_source = ""
        self.last_error = ""
        self.observing = False

    def snapshot(self):
        return dict(native_state=self.last_state, source=self.last_source,
                    entries=self.entries, exits=self.exits,
                    held=bool(self.mod._ads_handoff.get("held")),
                    last_error=self.last_error)

    def input(self, event):
        mod = self.mod
        if event == mod.EInputEvent.IE_Released:
            mod._ads_handoff["held"] = False
            mod._clear_pending_ads_press("physical_release", outcome="release")
            return
        if event != mod.EInputEvent.IE_Pressed:
            return
        mod._ads_handoff["held"] = True
        if not self._eligible() or mod._ads_active:
            return
        _pc, pawn, camera = mod._get_runtime()
        if pawn is None or camera is None or mod._ffyl_camera_active(pawn, camera):
            return
        # This callback precedes native dispatch. State here may belong to the
        # previous aim; admission happens only in update/zoom notification.
        mod._arm_pending_ads_press(pawn, camera)

    def _eligible(self):
        mod = self.mod
        return (mod._third_person_enabled and mod._third_person_pushed
                and not mod._vehicle_camera_active and not mod._ladder_active
                and not mod._shop_camera_active)

    def update(self, source="camera_update"):
        if self.observing:
            return
        self.observing = True
        try:
            self._observe(source)
        finally:
            self.observing = False

    def _observe(self, source):
        mod = self.mod
        if not self._eligible():
            self.owners = None
            if mod._ads_active or mod._ads_press_intent.get("pending"):
                mod._cancel_hybrid_ads("ads_context_changed")
            return
        pc, pawn, camera = mod._get_runtime()
        if pc is None or pawn is None or camera is None:
            # Runtime loss retires preparation/presentation, never native zoom.
            self.owners = None
            mod._cancel_hybrid_ads("ads_runtime_unavailable", restore=False)
            return
        live = (pc, pawn, camera)
        if self.owners is not None and any(old() != obj for old, obj in zip(self.owners, live)):
            mod._cancel_hybrid_ads("ads_owner_changed", restore=False)
            self.owners = None
        if mod._ffyl_camera_active(pawn, camera):
            mod._cancel_hybrid_ads("ffyl_active")
            self.owners = None
            return
        try:
            state = int(pawn.ZoomState.State)
            if state not in (0, 1, 2, 3):
                raise RuntimeError(f"Unknown native zoom state: {state}")
            self.last_state, self.last_source = state, source
            if state in (1, 2):
                self._enter(pawn, camera)
                if mod._ads_active and self.owners is None:
                    self.owners = tuple(WeakPointer(obj) for obj in live)
            else:
                if mod._ads_active:
                    self._exit(pawn, camera)
                if state == 3:
                    mod._clear_pending_ads_press("native_zoom_exit")
                elif mod._ads_press_intent.get("pending"):
                    mod._note_weak_zoom_signal(pawn, source)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            mod._ads_debug_error("native_ads_observation", exc)
            mod._cancel_hybrid_ads("native_ads_observation_error")

    def _enter(self, pawn, camera):
        mod = self.mod
        if mod._ads_active or camera.CameraModeInputs.Weapon is None:
            return
        ads = mod._ads_tps_state
        calibration = None
        if ads is None and camera.CameraModeState.bIsTransitioning:
            # Native scope return has not yet produced a settled TPS view.
            # Its rendered scope FOV is not a hip calibration.
            return
        # A new weapon must never reverse the outgoing weapon's calibration.
        if isinstance(ads, dict) and ads.get("phase") == "released" and (
            ads.get("weapon_address") != mod._ads_object_address(camera.CameraModeInputs.Weapon)
            or ads.get("manager_address") != mod._ads_object_address(camera)
        ):
            if ads.get("manager_address") == mod._ads_object_address(camera):
                calibration = (float(ads["base_fov"]), float(ads["original_offset"]))
            mod._finish_hybrid_tps_ads()
        if not mod._ads_press_intent.get("pending"):
            mod._arm_pending_ads_press(pawn, camera, source="native_state")
        if not mod._reconcile_pending_ads_press_weapon(pawn, camera, self.last_source):
            return
        mod._activate_confirmed_ads_press(
            pawn, camera, "observed_native_zoom", base_calibration=calibration,
        )
        if mod._ads_active:
            self.entries += 1

    def _exit(self, pawn, camera):
        mod = self.mod
        mod._ads_active = False
        self.exits += 1
        self.owners = None
        mod._clear_pending_ads_press("native_zoom_exit")
        mod._cleanup_ads_handoff("native_zoom_exit")
        if mod._ads_route == "tps":
            mod._release_hybrid_tps_ads()
        else:
            mod._ads_route = "hip"
            mod._ads_debug["native_releases"] += 1
            camera.SetActorCameraMode(
                pawn, "ThirdPerson", "",
                hybrid_ads.release_transition(mod, mod.ADS_CAMERA_TRANSITION_TIME),
                False, True,
            )
        mod._apply_camera_offset()


def _controller(mod):
    controller = getattr(mod, "_ads_controller", None)
    if controller is None:
        controller = mod._ads_controller = ADSController(mod)
    return controller


def _update_pending_ads_press_impl(*, owner_module) -> None:
    """Existing camera-update stage now reconciles entry and exit, not a timer."""
    _controller(owner_module).update()


def _handle_first_person_ads_input_impl(event: Any, *, owner_module) -> None:
    _controller(owner_module).input(event)

def _reset_ads_press_intent_impl(*, owner_module) -> None:
    owner_module._ads_controller = ADSController(owner_module)
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
        "native_entries_prepared": 0,
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
    pawn: Any, camera_manager: Any, *, source: str = "physical", owner_module
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
    state["presses" if source == "physical" else "native_entries_prepared"] += 1
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


def _activate_confirmed_ads_press_impl(
    pawn: Any,
    camera_manager: Any,
    confirmation: str,
    *,
    base_calibration=None,
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

    if owner_module._ads_route == "tps" and not owner_module._ads_active:
        try:
            owner_module._ads_active = True
            owner_module._reverse_hybrid_tps_ads()
            owner_module._ads_handoff["route_weapon"] = owner_module._ads_object_address(
                camera_manager.CameraModeInputs.Weapon
            )
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
                base_calibration=base_calibration,
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

