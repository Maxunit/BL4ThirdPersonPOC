"""Coordinate recoil, Beam and camera handoff ownership from existing events.

The loader supplies state. Set/Ladder guards and local PRE/POST tokens prevent
normal native rearming during FFYL, interaction, slide or ladder handoffs.
Activation verifies helper capability, executable/byte guards and current owner.
Release order is collision, origin, recoil, then dependent guards. A failed stage
retains owner state and faults automatic activation; quarantine retries restore
only matching owned bytes. No SDK hook or native patch is installed at import.
Legacy elapsed-time settle gates remain unchanged and are tracked separately.
"""

from __future__ import annotations

from typing import Any


def _resume_native_after_ffyl_if_ready_impl(*, owner_module) -> bool:
    """Rearm native auto only after a verified, stable TPS handoff."""
    if not owner_module._ffyl_native_resume_pending:
        return True
    if owner_module._native_fault:
        owner_module._ffyl_native_resume_pending = False
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] FFYL_NATIVE_RESUME_REFUSED "
            "native fault; leave automatic correction disabled"
        )
        return False
    if (
        owner_module._ffyl_early_handoff_armed
        or owner_module._camera_lifecycle.get("pending")
        or not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._ads_active
        or owner_module._ads_route != "hip"
        or owner_module._slide_active
        or owner_module._vehicle_camera_active
        or owner_module._ladder_active
        or owner_module._shop_camera_active
    ):
        return False
    handoff_started = owner_module._camera_lifecycle.get("early_handoff_started")
    if (
        handoff_started is not None
        and owner_module.time.perf_counter() - float(handoff_started) < 0.85
    ):
        return False
    _pc, pawn, manager = owner_module._get_runtime()
    if pawn is None or manager is None:
        return False
    try:
        state = manager.CameraModeState
        if (
            str(manager.GetActorCameraMode(pawn)) != "ThirdPerson"
            or str(manager.CameraModeInputs.AttachComponent.Name) != "CharacterMesh"
            or state.bIsTransitioning
            or state.bShowViewModel
            or state.bIsColliding
            or not owner_module._ffyl_camera_stack_has_single_tps(manager)
        ):
            return False
        if (
            owner_module._object_address(pawn)
            != int(owner_module._camera_stack_owner.get("pawn_address", 0))
            or owner_module._object_address(manager)
            != int(owner_module._camera_stack_owner.get("manager_address", 0))
            or not owner_module._camera_stack_owner.get("owned")
            or owner_module._native_active()
        ):
            return False
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if owner_module._camera_lifecycle.get("last_error") != error:
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] FFYL_NATIVE_RESUME_CHECK_ERROR " f"{error}"
            )
        owner_module._camera_lifecycle["last_error"] = error
        if "Camera stack layout unverified for build" in error:
            owner_module._ffyl_native_resume_pending = False
        return False
    # Polling was paused while resume was pending, so the FFYL camera may
    # never have been sampled by the PRE-transition gate. The checks above
    # prove the replacement TPS owner and that no native copy remains active.
    owner_module._native_ffyl_pending = False
    owner_module._native_ffyl_pending_pawn = 0
    owner_module._ffyl_native_resume_pending = False
    owner_module._native_auto_enabled = True
    owner_module._native_last_attempt = None
    owner_module.logging.warning(
        "[BL4ThirdPersonPOC] FFYL_NATIVE_AUTO_RESUMED "
        "mode=ThirdPerson stack_count=1 viewmodel=False "
        f"handoff={owner_module._camera_lifecycle.get('reason')!r} pre_gate_cleared=True"
    )
    return True


def _held_ads_rearm_ready(camera: Any, pawn: Any, *, owner_module) -> bool:
    """Permit only the observed native-FPS -> held-TPS-ADS equip handoff.

    The request belongs to a PC/pawn/manager/weapon identity and is consumed
    once. No timeout, broad ADS activation, or replacement of an active owner.
    Native recoil still validates the sole stack entry, live Look and build.
    """
    mod = owner_module
    handoff = mod._ads_handoff
    request = handoff.get("native_tps_rearm")
    ads = mod._ads_tps_state
    if not isinstance(request, dict) or request.get("attempted"):
        return False
    # Hybrid ADS scope exit: same weapon, so no equip callback pair follows.
    same_weapon = bool(request.get("same_weapon"))
    if not (
        handoff.get("held")
        and mod._ads_active
        and mod._ads_route == "tps"
        and isinstance(ads, dict)
        and ads.get("phase") == "ads"
        and ads.get("transition") is None
        and not handoff.get("latch_active")
        and not handoff.get("reticle_rebind_active")
        and (same_weapon or int(handoff.get("equip_ordinal", 0)) >= 2)
        and not mod._ads_press_intent.get("pending")
        and mod._third_person_enabled
        and mod._third_person_pushed
        and not mod._slide_active
        and not mod._ladder_active
        and not mod._vehicle_camera_active
        and not mod._shop_camera_active
        and not mod._camera_lifecycle.get("pending")
        and not mod._native_ffyl_pending
        and not mod._native_npc_pending
        and not mod._native_ladder_handoff_pending
        and not mod._native_slide_handoff_pending
        and not mod._native_fault
        and not mod._native_active()
        and not mod._beam_active()
    ):
        return False
    pc, live_pawn, live_camera = mod._get_runtime()
    if pc is None or live_pawn is None or live_camera is None:
        return False
    weapon = camera.CameraModeInputs.Weapon
    identity = tuple(mod._object_address(x) for x in (pc, pawn, camera, weapon))
    if (
        identity != request.get("identity")
        or mod._object_address(live_pawn) != identity[1]
        or mod._object_address(live_camera) != identity[2]
        or ads.get("manager_address") != identity[2]
        or ads.get("weapon_address") != identity[3]
        or (not same_weapon and handoff.get("incoming_weapon") != identity[3])
        or handoff.get("route_weapon") != identity[3]
    ):
        # A later weapon or player identity never inherits this request.
        handoff.pop("native_tps_rearm", None)
        return False
    return bool(
        identity[3]
        and int(pawn.ZoomState.State) in (1, 2)
        and str(camera.GetActorCameraMode(pawn)) == "ThirdPerson"
        and not camera.CameraModeState.bIsTransitioning
        and not camera.CameraModeState.bIsColliding
        and not mod._looks_like_first_person_fallback()
        and mod._ffyl_camera_stack_has_single_tps(camera)
    )


def _native_slide_ads_ready_impl(camera: Any, pawn: Any, *, owner_module) -> bool:
    """Allow a new Look owner only in settled, locally owned TPS ADS."""
    state = owner_module._ads_tps_state
    if (
        not (
            owner_module._ads_route == "tps"
            and owner_module._ads_active
            and isinstance(state, dict)
            and state.get("phase") == "ads"
            and state.get("transition") is None
            and not owner_module._ads_press_intent.get("pending")
        )
        or not (
            owner_module._third_person_enabled and owner_module._third_person_pushed
        )
        or not owner_module._slide_camera_recovery_pending
        or owner_module._slide_active
        or owner_module._slide_camera_recovery_pawn
        != owner_module._object_address(pawn)
        or owner_module._camera_lifecycle.get("pending")
        or owner_module._ladder_active
        or owner_module._vehicle_camera_active
        or owner_module._shop_camera_active
        or owner_module._native_ffyl_pending
        or owner_module._native_fault
        or owner_module._native_active()
    ):
        return False
    try:
        weapon = camera.CameraModeInputs.Weapon
        return bool(
            weapon is not None
            and state.get("manager_address") == owner_module._object_address(camera)
            and state.get("weapon_address") == owner_module._object_address(weapon)
            and str(camera.GetActorCameraMode(pawn)) == "ThirdPerson"
            and not camera.CameraModeState.bIsTransitioning
            and not camera.CameraModeState.bIsColliding
            and not owner_module._looks_like_first_person_fallback()
            and owner_module._ffyl_camera_stack_has_single_tps(camera)
        )
    except Exception:
        return False


def _native_ads_stack_verified_impl(camera: Any, *, owner_module) -> bool:
    """Measure the ADS native stack guard only during an armed perf probe."""
    if not owner_module._perf_probe["armed"]:
        return owner_module._ffyl_camera_stack_has_single_tps(camera)
    started_ns = owner_module.time.perf_counter_ns()
    try:
        return owner_module._ffyl_camera_stack_has_single_tps(camera)
    finally:
        owner_module._perf_record_metric(
            "ads.stack_verify", owner_module.time.perf_counter_ns() - started_ns
        )


def _native_slide_ads_owner_verified_impl(
    camera: Any,
    pawn: Any,
    recoil: Any,
    *,
    after_slide: bool = False,
    owner_module,
) -> bool:
    """Require the exact Slide or post-Slide Look and its native PRE guard."""
    guard = owner_module._active_native_state.get("ladder_guard")
    phase_matches = (
        not owner_module._slide_active and not owner_module._native_slide_interior
        if after_slide
        else owner_module._slide_active and owner_module._native_slide_interior
    )
    if (
        not phase_matches
        or not owner_module._slide_camera_recovery_pending
        or owner_module._slide_camera_recovery_pawn
        != owner_module._object_address(pawn)
        or owner_module._native_slide_handoff_pending
        or not guard
        or bool(guard.get("slide_interior")) == after_slide
        or not getattr(recoil, "active", False)
    ):
        return False
    identity = tuple(getattr(recoil, "identity", ()))
    control = guard.get("control")
    return bool(
        len(identity) == 4
        and identity == guard.get("owner_identity")
        and identity[0] == owner_module._object_address(camera)
        and control is not None
        and int(control.status) == 0
        and int(control.allow_default) == int(not after_slide)
        and (
            int(control.manager),
            int(control.runtime),
            int(control.look),
            int(control.look_control),
        )
        == identity
    )


def _require_guarded_beam_collision_impl(helper: Any, *, owner_module) -> None:
    "Reject a cached guarded-prefix-collision module before arming native Beam ownership."
    recorder = getattr(helper, "recorder", None)
    constants = getattr(getattr(recorder, "__code__", None), "co_consts", ())
    if (
        getattr(helper, "COLLISION_IMPLEMENTATION", None) != "guarded-prefix-collision"
        or "a80190" not in constants
    ):
        raise RuntimeError(
            "Cached Beam collision helper is not guarded-prefix-collision; "
            "restart BL4 with this build installed"
        )


def _ads_beam_can_hold_impl(camera: Any, pawn: Any, *, owner_module) -> bool:
    """Retain only our exact FireBeam pair and Look across TPS ADS phases."""
    import sys
    from . import native_beam_origin

    if (
        not owner_module._native_auto_enabled
        or owner_module._native_fault
        or not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or owner_module._slide_active
        or owner_module._ladder_active
        or owner_module._vehicle_camera_active
        or owner_module._shop_camera_active
        or owner_module._native_ffyl_pending
        or owner_module._native_slide_handoff_pending
        or owner_module._native_ladder_handoff_pending
        or owner_module._camera_lifecycle.get("pending")
        or owner_module._looks_like_first_person_fallback()
    ):
        return False
    origin, collision, recoil = (
        sys.modules.get(key)
        for key in (
            owner_module._NATIVE_OWNER_KEYS[1],
            owner_module._NATIVE_OWNER_KEYS[0],
            owner_module._NATIVE_OWNER_KEYS[2],
        )
    )
    if any(
        owner is None or not getattr(owner, "active", True)
        for owner in (origin, collision, recoil)
    ):
        return False
    weapon = camera.CameraModeInputs.Weapon
    if (
        weapon is None
        or not native_beam_origin.is_firebeam(weapon)
        or getattr(origin, "weapon_address", 0) != owner_module._object_address(weapon)
        or getattr(collision, "weapon_address", 0)
        != owner_module._object_address(weapon)
        or recoil.identity[0] != owner_module._object_address(camera)
    ):
        return False
    return str(camera.GetActorCameraMode(pawn)) == "ThirdPerson"


def _update_native_ads_origin_impl(camera: Any, pawn: Any, *, owner_module) -> None:
    """Preserve a verified Beam pair through ADS; own origin after Slide ADS."""
    import sys
    from . import native_beam_origin, native_beam_collision

    owner_module._require_guarded_beam_collision(native_beam_collision)
    ads_state = owner_module._ads_tps_state
    weapon = camera.CameraModeInputs.Weapon
    recoil = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
    collision = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[0])
    origin = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[1])
    slide_ads = owner_module._native_slide_ads_owner_verified(camera, pawn, recoil)
    post_slide_ads = owner_module._native_slide_ads_owner_verified(
        camera, pawn, recoil, after_slide=True
    )
    camera_collision = bool(camera.CameraModeState.bIsColliding)
    ready = bool(
        owner_module._ads_route == "tps"
        and owner_module._ads_active
        and isinstance(ads_state, dict)
        and ads_state.get("phase") == "ads"
        and ads_state.get("transition") is None
        and weapon is not None
        and not (
            owner_module._ads_press_intent.get("pending")
            or owner_module._ads_handoff.get("latch_active")
            or (
                (
                    owner_module._slide_active
                    or owner_module._slide_camera_recovery_pending
                    or owner_module._native_slide_interior
                )
                and not (slide_ads or post_slide_ads)
            )
            or owner_module._native_slide_handoff_pending
            or owner_module._native_ladder_handoff_pending
            or owner_module._ladder_active
            or owner_module._vehicle_camera_active
            or owner_module._shop_camera_active
            or owner_module._native_ffyl_pending
            or owner_module._camera_lifecycle.get("pending")
        )
        and owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and ads_state.get("manager_address") == owner_module._object_address(camera)
        and ads_state.get("weapon_address") == owner_module._object_address(weapon)
        and recoil is not None
        and getattr(recoil, "active", False)
        and recoil.identity[0] == owner_module._object_address(camera)
        and str(camera.GetActorCameraMode(pawn)) == "ThirdPerson"
        and not camera.CameraModeState.bIsTransitioning
        and not owner_module._looks_like_first_person_fallback()
        and (slide_ads or owner_module._native_ads_stack_verified(camera))
    )
    if not ready:
        owner_module._native_ads_origin_attempt = None
        owner_module._native_ads_collision_held = False
        if owner_module._ads_beam_can_hold(camera, pawn):
            return
        if owner_module._beam_active() and not owner_module._native_stop_beam(
            "ads_transition"
        ):
            raise RuntimeError("Beam restore failed during TPS ADS")
        return
    if collision is not None and origin is None:
        if not owner_module._native_stop_beam("ads_collision_without_origin"):
            raise RuntimeError("Beam collision owner lost its origin")
        return
    if origin is not None:
        if int(getattr(origin, "weapon_address", 0)) != owner_module._object_address(
            weapon
        ) or (
            collision is not None
            and int(getattr(collision, "weapon_address", 0))
            != owner_module._object_address(weapon)
        ):
            if not owner_module._native_stop_beam("ads_weapon_changed"):
                raise RuntimeError("Beam restore failed after ADS weapon change")
            return
        if collision is not None and not owner_module._native_ads_pair_logged:
            owner_module._native_ads_pair_logged = True
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] ADS_BEAM_MATRIX_HELD "
                "origin=True collision=True variant=guarded-prefix-collision"
            )
        if camera_collision and not owner_module._native_ads_collision_held:
            owner_module._native_ads_collision_held = True
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] ADS_COLLISION_ORIGIN_HELD "
                "same camera, weapon and native Look owner"
            )
        elif not camera_collision:
            owner_module._native_ads_collision_held = False
            if (
                collision is None
                and not (slide_ads or post_slide_ads)
                and owner_module._native_ads_origin_attempt is None
            ):
                owner_module._native_ads_origin_attempt = (
                    owner_module._object_address(pawn),
                    owner_module._object_address(camera),
                    owner_module._object_address(weapon),
                )
                result = native_beam_collision.apply_or_restore()
                if (
                    result.get("action") == "TPS_CAPPED_PREFIX_ON"
                    and result.get("version") == "guarded-prefix-collision"
                    and result.get("verified") is True
                    and not result.get("errors")
                ):
                    sys.modules[owner_module._NATIVE_OWNER_KEYS[0]].weapon_address = (
                        owner_module._object_address(weapon)
                    )
                    owner_module.logging.warning(
                        "[BL4ThirdPersonPOC] ADS_BEAM_MATRIX_ON "
                        "origin=True collision=True variant=guarded-prefix-collision"
                    )
                elif sys.modules.get(owner_module._NATIVE_OWNER_KEYS[0]) is not None:
                    if not owner_module._native_stop_beam("ads_collision_refused"):
                        raise RuntimeError(
                            "Beam collision restore failed after ADS refusal"
                        )
                else:
                    owner_module.logging.warning(
                        "[BL4ThirdPersonPOC] ADS_BEAM_MATRIX_REFUSED "
                        f'errors={result.get("errors")}'
                    )
        return
    owner_module._native_ads_collision_held = False
    # A collision is allowed to preserve an existing owner, never to install
    # a new native entry patch while the camera is moving against geometry.
    if camera_collision:
        owner_module._native_ads_origin_attempt = None
        return
    identity = (
        owner_module._object_address(pawn),
        owner_module._object_address(camera),
        owner_module._object_address(weapon),
    )
    if identity == owner_module._native_ads_origin_attempt:
        return
    owner_module._native_ads_origin_attempt = identity
    if not native_beam_origin.is_firebeam(weapon):
        return
    result = native_beam_origin.apply_or_restore()
    if result.get("action") == "TPS_QUERY_ORIGIN_ON" and not result.get("errors"):
        sys.modules[owner_module._NATIVE_OWNER_KEYS[1]].weapon_address = identity[2]
        marker = (
            "SLIDE_ADS_ORIGIN_ON"
            if slide_ads
            else "POST_SLIDE_ADS_ORIGIN_ON" if post_slide_ads else "ADS_ORIGIN_ON"
        )
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] "
            f"{marker} "
            "recoil=True beam_origin=True beam_collision=False"
        )
        # A fresh ADS entry may start without a hip Beam owner (e.g. equip
        # during ADS). On the next settled poll the collision guard arms.
        owner_module._native_ads_origin_attempt = None
        return
    if sys.modules.get(owner_module._NATIVE_OWNER_KEYS[1]) is not None:
        if not owner_module._native_stop_beam("ads_origin_refused"):
            raise RuntimeError("Beam origin restore failed after ADS refusal")
    owner_module.logging.warning(
        "[BL4ThirdPersonPOC] ADS_ORIGIN_REFUSED " f'errors={result.get("errors")}'
    )


def _update_native_ownership_impl(*, owner_module) -> None:
    """Reconcile native owners from the existing game-thread camera callback.

    Consume verified PRE handoffs before live Look access. Block activation on
    missing runtime, alternate camera routes, pending local events or faults;
    release old owners before arming a new camera/weapon identity.
    """
    from . import ffyl_strategy_runtime

    if ffyl_strategy_runtime.controls_transition(owner_module):
        # The owned FFYL guard can report an atomic Set restore. Consume that
        # evidence, but do not run ordinary default-guard/native-auto repair.
        owner_module._ladder_guard_consume("ffyl_owned_poll")
        return
    from . import native_ladder_guard

    native_ladder_guard.pre_poll_default(owner_module)
    if not owner_module._ladder_guard_consume("poll"):
        return
    if (
        not owner_module._resume_native_after_ffyl_if_ready()
        or not owner_module._native_auto_enabled
    ):
        return
    if (
        not owner_module._ffyl_native_pre_installed
        or not owner_module._native_npc_post_installed
    ):
        return
    if owner_module._native_fault:
        # A recoil restore may have failed while a temporary native mode was
        # active. Make one ownership-checked attempt after normal TPS returns;
        # never retry after a refusal or recover a Beam/unknown fault here.
        if (
            owner_module._native_fault_source != "recoil_restore"
            or owner_module._native_fault_recovery_attempted
            or not owner_module._native_active()
            or not (
                owner_module._third_person_enabled and owner_module._third_person_pushed
            )
            or owner_module._ads_route != "hip"
            or owner_module._ads_active
            or owner_module._slide_active
            or owner_module._vehicle_camera_active
            or owner_module._shop_camera_active
            or owner_module._camera_lifecycle.get("pending")
        ):
            return
        _pc, recovery_pawn, recovery_camera = owner_module._get_runtime()
        if recovery_pawn is None or recovery_camera is None:
            return
        if (
            str(recovery_camera.GetActorCameraMode(recovery_pawn)) != "ThirdPerson"
            or recovery_camera.CameraModeState.bIsTransitioning
            or recovery_camera.CameraModeState.bIsColliding
            or owner_module._native_zoom_confirms_ads(recovery_pawn)
        ):
            return
        owner_module._native_fault_recovery_attempted = True
        if owner_module._native_stop("settled_tps_recovery"):
            owner_module._native_fault_recovery_attempted = False
        return
    pc, pawn, camera = owner_module._get_runtime()
    native_ladder_guard.update_default(owner_module, pc, pawn, camera)
    if any(x is None for x in (pc, pawn, camera)):
        owner_module._native_npc_pending = False
        if owner_module._native_active() and not owner_module._native_stop(
            "runtime_absent"
        ):
            raise RuntimeError("Native restore failed during runtime loss")
        return
    slide_ads_rearm = False
    if owner_module._native_slide_handoff_pending:
        current_mode = str(camera.GetActorCameraMode(pawn))
        if current_mode == "Slide":
            owner_module._native_slide_seen = True
        if (
            not owner_module._native_slide_seen
            or current_mode != "ThirdPerson"
            or camera.CameraModeState.bIsTransitioning
            or camera.CameraModeState.bIsColliding
            or owner_module._looks_like_first_person_fallback()
            or owner_module._camera_lifecycle.get("pending")
        ):
            return
        if owner_module._slide_active:
            # The first Slide Set retired the old Look. Reown the new copy
            # only after the SDK reports stable TPS and the slide remains
            # active. The new owner's native guard also covers Default exit.
            if not owner_module._is_sliding_now():
                return
            owner_module._native_slide_interior = True
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] SLIDE_INTERIOR_SETTLED stable TPS"
            )
        elif owner_module._slide_camera_recovery_pending:
            # The camera recovery deliberately waits for TPS zoom-out. Its
            # separate recoil Look can safely rearm during a held, settled
            # TPS ADS once the native Default PRE guard has retired it.
            if not owner_module._native_slide_ads_ready(camera, pawn):
                return
            slide_ads_rearm = True
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] SLIDE_HANDOFF_SETTLED stable TPS_ADS"
            )
        else:
            owner_module._native_slide_seen = False
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] SLIDE_HANDOFF_SETTLED stable TPS"
            )
        owner_module._native_slide_handoff_pending = False
        owner_module._native_last_attempt = None
    if owner_module._native_slide_interior and not owner_module._slide_active:
        # A slide ending without the observed Default Set still needs a
        # verified release before normal TPS recovery can rearm the Look.
        if str(camera.GetActorCameraMode(pawn)) == "ThirdPerson" and (
            camera.CameraModeState.bIsTransitioning
            or camera.CameraModeState.bIsColliding
        ):
            return
        if owner_module._native_active() and not owner_module._native_stop(
            "slide_exit_without_default"
        ):
            raise RuntimeError("Slide interior native restore failed at exit")
        owner_module._native_slide_interior = False
        owner_module._native_slide_handoff_pending = True
        owner_module._native_slide_seen = True
        return
    if owner_module._native_ladder_handoff_pending:
        if owner_module._ladder_active or not owner_module._native_ladder_seen:
            return
        if (
            owner_module._camera_lifecycle.get("pending")
            or str(camera.GetActorCameraMode(pawn)) != "ThirdPerson"
            or camera.CameraModeState.bIsTransitioning
            or camera.CameraModeState.bIsColliding
            or owner_module._looks_like_first_person_fallback()
        ):
            return
        # TPS can settle while Spine3 is still carrying the ladder mantle.
        # Keep the native Look unowned until that camera correction releases;
        # MANTLE_END is an observed state transition, not a timed guess.
        if owner_module._mantle_camera_state.get("branch") == "ladder_up" and (
            owner_module._mantle_camera_state.get("active")
            or owner_module._mantle_camera_state.get("releasing")
        ):
            return
        # GC may recover the visible camera while the player is still falling.
        # Leave native Look unowned until Walking, so landing cannot retire an
        # owner acquired during this narrowly scoped recovery handoff.
        try:
            movement = pawn.GbxNavMovement
            if (
                int(movement.MovementMode) != 1
                or int(movement.CustomMovementMode) != 0
                or int(movement.LadderAnimState.PendingType) != 0
                or int(movement.LadderAnimState.CurrentType) != 0
                or int(movement.ReplicatedLadderState.ClimbableType) != 0
            ):
                return
        except Exception:
            return
        owner_module._native_ladder_handoff_pending = False
        owner_module._native_ladder_seen = False
        owner_module._native_last_attempt = None
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] LADDER_HANDOFF_SETTLED stable TPS"
        )
    if owner_module._native_ffyl_pending:
        # One event may precede the native FFYL mode by a camera-update tick.
        # Only the observed change out of ThirdPerson releases this gate.
        exit_mode = str(camera.GetActorCameraMode(pawn))
        if exit_mode == "ThirdPerson":
            return
        # An immediate Second Wind can skip the sampled FFYL camera entirely.
        # Preserve the lifecycle repair for the same local pawn, without
        # assuming that a Second Wind event or an empty stack was observed.
        if (
            exit_mode == "Default"
            and not owner_module._camera_lifecycle.get("pending")
            and not owner_module._native_fault
            and not owner_module._native_active()
            and owner_module._third_person_enabled
            and owner_module._third_person_pushed
            and owner_module._object_address(pawn)
            == owner_module._native_ffyl_pending_pawn
            and owner_module._object_address(camera)
            == int(owner_module._camera_stack_owner.get("manager_address", 0))
            and owner_module._object_address(pawn)
            == int(owner_module._camera_stack_owner.get("pawn_address", 0))
            and not owner_module._is_vehicle_camera_view()
        ):
            owner_module._arm_camera_lifecycle(
                "ffyl", expected_pawn=owner_module._object_address(pawn)
            )
            owner_module._camera_lifecycle["direct_default_manager"] = (
                owner_module._object_address(camera)
            )
            owner_module._camera_lifecycle["phase"] = (
                "direct_default_waiting_for_settle"
            )
            owner_module._camera_lifecycle["ffyl_direct_defaults"] += 1
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] FFYL_DIRECT_DEFAULT_OBSERVED "
                "local pawn matched PRE restore; guarded repair armed"
            )
        owner_module._native_ffyl_pending = False
        owner_module._native_ffyl_pending_pawn = 0
        owner_module.logging.info("[BL4ThirdPersonPOC] FFYL_NATIVE_PRE_TRANSITION_SEEN")
    # ServerUseObject completion may leave TPS unchanged. Release the PRE
    # handoff after the paired POST and a settled camera, or on mode departure.
    from . import npc_native_resume

    if not npc_native_resume.ready(owner_module, pc, camera, pawn):
        return
    # ClientRestart POST arms camera reconciliation. Wait for its settled
    # ThirdPerson result before owning another Look copy.
    if (
        owner_module._camera_lifecycle.get("pending")
        and owner_module._camera_lifecycle.get("reason") == "client_restart"
    ):
        return
    # Recoil survives TPS ADS. Restore the hip collision hook before ADS;
    # the independent origin hook is allowed after the ADS camera settles.
    if (
        owner_module._ads_route == "tps"
        or owner_module._ads_tps_state is not None
        or owner_module._ads_press_intent.get("pending")
        or owner_module._ads_handoff.get("held")
    ):
        if _held_ads_rearm_ready(camera, pawn, owner_module=owner_module):
            request = owner_module._ads_handoff["native_tps_rearm"]
            try:
                owner_module._native_start(allow_tps_ads=True)
                if not owner_module._native_active():
                    raise RuntimeError(
                        "Native TPS ADS activation did not acquire a Look owner"
                    )
                owner_module._ads_handoff.pop("native_tps_rearm", None)
                owner_module.logging.info(
                    "[BL4ThirdPersonPOC] HELD_ADS_REARMED source="
                    + ("hybrid_scope_exit" if request.get("same_weapon") else "native_fps_weapon_handoff")
                )
            except Exception as exc:
                request["attempted"] = True
                owner_module.logging.error(
                    "[BL4ThirdPersonPOC] HELD_ADS_REARM_FAILED "
                    f"{type(exc).__name__}: {exc}"
                )
        owner_module._update_native_ads_origin(camera, pawn)
        if slide_ads_rearm:
            try:
                owner_module._native_start(allow_tps_ads=True)
                # This is a new verified Look. The origin belonged to the
                # retired Slide Look, so arm it again for held ADS now that
                # recoil and its native PRE guard own the replacement.
                owner_module._update_native_ads_origin(camera, pawn)
                owner_module._native_last_attempt = (
                    owner_module._object_address(pawn),
                    owner_module._object_address(camera),
                    owner_module._object_address(camera.CameraModeInputs.Weapon),
                )
                owner_module.logging.warning(
                    "[BL4ThirdPersonPOC] SLIDE_TPS_ADS_REARMED"
                )
            except Exception as exc:
                owner_module.logging.error(
                    "[BL4ThirdPersonPOC] SLIDE_TPS_ADS_REARM_FAILED "
                    f"{type(exc).__name__}: {exc}"
                )
        return
    owner_module._native_ads_origin_attempt = None
    owner_module._native_ads_pair_logged = False
    # ADS origin owns the same native entry as hip origin. Release it before
    # normal hip activation can install origin and collision as a pair.
    import sys

    if (
        sys.modules.get(owner_module._NATIVE_OWNER_KEYS[1]) is not None
        and sys.modules.get(owner_module._NATIVE_OWNER_KEYS[0]) is None
        and not (owner_module._slide_active and owner_module._native_slide_interior)
    ):
        if not owner_module._native_stop_beam("ads_exit"):
            raise RuntimeError("Beam origin restore failed after TPS ADS")
        return
    eligible = (
        owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and owner_module._ads_route == "hip"
        and owner_module._ads_tps_state is None
        and not owner_module._ads_press_intent.get("pending")
        and not owner_module._ads_handoff.get("held")
        and not owner_module._native_zoom_confirms_ads(pawn)
        and not (
            owner_module._ads_active
            or (owner_module._slide_active and not owner_module._native_slide_interior)
            or owner_module._ladder_active
            or owner_module._vehicle_camera_active
            or owner_module._shop_camera_active
        )
        and str(camera.GetActorCameraMode(pawn)) == "ThirdPerson"
    )
    if not eligible:
        if owner_module._native_active() and not owner_module._native_stop(
            "state_change"
        ):
            raise RuntimeError("Native restore failed after TPS state change")
        return
    import sys

    recoil = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
    if recoil is not None and getattr(recoil, "active", False):
        if int(camera._get_address()) != recoil.identity[0]:
            if not owner_module._native_stop("camera_instance_change"):
                raise RuntimeError("Native restore failed after camera instance change")
            return
    origin = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[1])
    if origin is not None:
        weapon = camera.CameraModeInputs.Weapon
        if weapon is None or int(weapon._get_address()) != int(
            getattr(origin, "weapon_address", 0)
        ):
            if not owner_module._native_stop_beam("weapon_change"):
                raise RuntimeError("Beam restore failed on weapon change")
            return
    if camera.CameraModeState.bIsTransitioning or camera.CameraModeState.bIsColliding:
        return
    weapon = camera.CameraModeInputs.Weapon
    if weapon is None:
        return
    identity = (
        int(pawn._get_address()),
        int(camera._get_address()),
        int(weapon._get_address()),
    )
    if identity == owner_module._native_last_attempt:
        return
    owner_module._native_last_attempt = identity
    try:
        owner_module._native_start()
    except Exception as exc:
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] NATIVE_AUTO_START_FAILED {type(exc).__name__}: {exc}"
        )


def _native_active_impl(*, owner_module) -> bool:
    """Report any retained recoil or Beam registry owner, including cleanup faults."""
    import sys

    return any(
        sys.modules.get(key) is not None and getattr(sys.modules[key], "active", True)
        for key in owner_module._NATIVE_OWNER_KEYS
    )


def _beam_active_impl(*, owner_module) -> bool:
    """Report a retained collision or origin owner; presence is not settled eligibility."""
    import sys

    return any(
        sys.modules.get(key) is not None and getattr(sys.modules[key], "active", True)
        for key in owner_module._NATIVE_OWNER_KEYS[:2]
    )


def _ladder_guard_consume_impl(reason: str, *, owner_module) -> bool:
    """Accept an atomic native PRE restore before accessing old Look memory."""
    import sys
    from . import native_ladder_guard

    guard = owner_module._active_native_state.get("ladder_guard")
    is_ffyl_guard = guard is not None and guard.get("ffyl_upper_tps")
    if not is_ffyl_guard and native_ladder_guard.status(owner_module) not in (1, 2, 3):
        return True
    try:
        if guard is not None and guard.get("ffyl_upper_tps"):
            from . import ffyl_recoil_guard

            if owner_module._beam_active():
                raise RuntimeError("Beam owner unexpected during FFYL recoil handoff")
            recoil = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
            restored = ffyl_recoil_guard.consume(owner_module, recoil)
            if restored:
                owner_module._native_last_attempt = None
                owner_module.logging.warning(
                    f"[BL4ThirdPersonPOC] FFYL_PRE_RESTORED reason={reason}"
                )
            return True
        if owner_module._beam_active():
            # The native Set guard has already retired the old Look copy.
            # Beam's independent global entry patches remain installed until
            # this game-thread handoff; restore collision before origin and
            # keep their executable allocations pinned for in-flight calls.
            if (
                not owner_module._native_stop_beam("mode_guard_handoff")
                or owner_module._beam_active()
            ):
                raise RuntimeError("Beam restore unverified at ModeGuard handoff")
            owner_module.logging.warning(
                "[BL4ThirdPersonPOC] BEAM_GUARD_HANDOFF_RESTORED"
            )
        recoil = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
        restored_mode = native_ladder_guard.consume(owner_module, recoil)
        if restored_mode:
            owner_module._native_last_attempt = None
            if restored_mode == 1:
                owner_module._native_ladder_handoff_pending = True
                owner_module._native_ladder_seen = (
                    native_ladder_guard.default_completed_handoff(owner_module)
                )
                owner_module.logging.warning(
                    f"[BL4ThirdPersonPOC] LADDER_PRE_RESTORED reason={reason}"
                )
            elif restored_mode == 2:
                owner_module._native_slide_handoff_pending = True
                owner_module._native_slide_seen = False
                owner_module._native_slide_interior = False
                owner_module.logging.warning(
                    f"[BL4ThirdPersonPOC] SLIDE_PRE_RESTORED reason={reason}"
                )
            elif restored_mode == 3:
                owner_module._native_slide_handoff_pending = True
                owner_module._native_slide_seen = True
                owner_module._native_slide_interior = False
                owner_module.logging.warning(
                    f"[BL4ThirdPersonPOC] SLIDE_DEFAULT_PRE_RESTORED reason={reason}"
                )
            else:
                raise RuntimeError("Unrecognized native camera guard status")
        return True
    except Exception as exc:
        default_guard = owner_module._active_native_state.get("ladder_default")
        if default_guard is not None:
            default_guard["control"].enabled = 0
        owner_module._native_fault = True
        owner_module._native_fault_source = (
            owner_module._native_fault_source or "ladder_guard_handoff"
        )
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] LADDER_PRE_HANDOFF_FAILED "
            f"reason={reason} error={type(exc).__name__}: {exc}; restart game"
        )
        return False


def _native_stop_beam_impl(reason: str, *, owner_module) -> bool:
    """Restore beam hooks without removing the owned ThirdPerson Look copy."""
    import sys
    from . import native_beam_collision, native_beam_origin

    collision_report = None
    for helper, key in (
        (native_beam_collision, owner_module._NATIVE_OWNER_KEYS[0]),
        (native_beam_origin, owner_module._NATIVE_OWNER_KEYS[1]),
    ):
        owned = sys.modules.get(key)
        if owned is None or not getattr(owned, "active", True):
            continue
        try:
            result = helper.apply_or_restore()
            if (
                result.get("errors")
                or result.get("action") != "RESTORED"
                or result.get("verified") is not True
            ):
                raise RuntimeError(
                    f'{result.get("action")}: verified={result.get("verified")}, '
                    f'errors={result.get("errors")}'
                )
            if key == owner_module._NATIVE_OWNER_KEYS[0]:
                collision_report = result
        except Exception as exc:
            if not owner_module._native_fault:
                owner_module._native_fault_source = "beam_restore"
            owner_module._native_fault = True
            owner_module.logging.error(
                f"[BL4ThirdPersonPOC] BEAM_RESTORE_FAILED "
                f"reason={reason} error={exc}"
            )
            return False
    owner_module._native_last_attempt = None
    owner_module._native_ads_pair_logged = False
    if collision_report is not None:
        owner_module.logging.warning(
            "[BL4ThirdPersonPOC] BEAM_MATRIX_RESULT "
            f'reason={reason} calls={collision_report.get("observed_calls", 0)} '
            f'replacements={collision_report.get("replacements_applied", 0)} '
            "front_preserved_first64="
            f'{collision_report.get("ads_overlap_front_preserved_first64", 0)}'
        )
    return True


def _native_stop_impl(reason: str, *, owner_module) -> bool:
    """Reverse native dependencies before camera or weapon ownership changes."""
    import sys
    from . import (
        native_beam_collision,
        native_beam_origin,
        native_recoil,
        native_ladder_guard,
    )

    # Stop new FFYL activation before any cleanup attempt, including failures.
    recoil_owner = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
    ffyl_context = getattr(recoil_owner, "ffyl_recoil_context", None)
    if ffyl_context is not None:
        try:
            ffyl_context.revoke_activation()
        except Exception as exc:
            owner_module._native_fault = True
            owner_module._native_fault_source = "ffyl_recoil_context_cleanup"
            owner_module.logging.error(
                f"[BL4ThirdPersonPOC] FFYL_CONTEXT_REVOKE_FAILED reason={reason} error={exc}"
            )
            return False
    try:
        native_ladder_guard.remove_default(owner_module, reason)
    except Exception as exc:
        owner_module._native_fault = True
        owner_module._native_fault_source = "ladder_default_cleanup"
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] LADDER_DEFAULT_REMOVE_FAILED "
            f"reason={reason} error={type(exc).__name__}: {exc}"
        )
        return False
    if not owner_module._ladder_guard_consume(reason):
        return False
    pending_guard = owner_module._active_native_state.get("ladder_guard")
    pending_owner = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
    if (
        pending_guard is not None
        and pending_owner is not None
        and not getattr(pending_owner, "active", False)
    ):
        owner_module._native_fault = True
        owner_module._native_fault_source = "ladder_guard_activation_race"
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] LADDER_ACTIVATION_RACE "
            f"reason={reason}; restart game before native tests"
        )
        return False
    order = (
        (native_beam_collision, owner_module._NATIVE_OWNER_KEYS[0], "RESTORED"),
        (native_beam_origin, owner_module._NATIVE_OWNER_KEYS[1], "RESTORED"),
        (native_recoil, owner_module._NATIVE_OWNER_KEYS[2], "RESTORE"),
    )
    recoil_restored = False
    for helper, key, expected in order:
        owned = sys.modules.get(key)
        if owned is None or not getattr(owned, "active", True):
            continue
        try:
            # Entry can already expose two layers while the ordinary TPS recoil
            # owner is still current (observed after respawn). The simplified
            # owner's cleanup reasons need the same restore-only snapshot proof
            # as legacy DownState PRE. Bound upper-FFYL owners retain their own
            # stronger context path in apply_or_restore; no activation is allowed.
            if (
                key == owner_module._NATIVE_OWNER_KEYS[2]
                and reason == "ffyl_downed_pre"
            ):
                result = helper.apply_or_restore(allow_stacked_ffyl=True, allow_stacked_death=True)
            elif key == owner_module._NATIVE_OWNER_KEYS[2] and reason.startswith(
                "ffyl_camera:"
            ):
                result = helper.apply_or_restore(
                    allow_stacked_ffyl=True,
                    allow_stacked_death=True,
                    allow_owner_manager=True,
                )
            elif key == owner_module._NATIVE_OWNER_KEYS[2] and reason == "state_change":
                result = helper.apply_or_restore(allow_stacked_ground_slam=True, allow_stacked_death=True)
            elif key == owner_module._NATIVE_OWNER_KEYS[2]:
                result = helper.apply_or_restore(allow_owner_manager=True, allow_stacked_death=True)
            else:
                result = helper.apply_or_restore()
            retired = (
                key == owner_module._NATIVE_OWNER_KEYS[2]
                and result.get("action") == "RETIRED"
                and result.get("owner_destroyed_verified") is True
                and result.get("restore_pending") is False
                and not getattr(owned, "active", True)
            )
            if result.get("errors") or (
                result.get("action") != expected and not retired
            ):
                raise RuntimeError(
                    f"{helper.__name__} restore result: "
                    f'{result.get("action")}, {result.get("errors")}'
                )
            if key == owner_module._NATIVE_OWNER_KEYS[2]:
                if not retired and (
                    result.get("ab_verified") is not True
                    or result.get("restore_pending") is not False
                ):
                    raise RuntimeError(
                        "Recoil restore did not verify original Look vtable"
                    )
                recoil_restored = True
            elif result.get("verified") is not True:
                raise RuntimeError(
                    f"{helper.__name__} restore did not verify original bytes"
                )
            if key == owner_module._NATIVE_OWNER_KEYS[0]:
                owner_module.logging.warning(
                    "[BL4ThirdPersonPOC] BEAM_MATRIX_RESULT "
                    f'reason={reason} calls={result.get("observed_calls", 0)} '
                    f'replacements={result.get("replacements_applied", 0)} '
                    "front_preserved_first64="
                    f'{result.get("ads_overlap_front_preserved_first64", 0)}'
                )
        except Exception as exc:
            if not owner_module._native_fault:
                owner_module._native_fault_source = (
                    "recoil_restore"
                    if key == owner_module._NATIVE_OWNER_KEYS[2]
                    else "beam_restore"
                )
                owner_module._native_fault_recovery_attempted = False
            owner_module._native_fault = True
            owner_module.logging.error(
                f"[BL4ThirdPersonPOC] NATIVE_RESTORE_FAILED reason={reason} error={exc}"
            )
            return False
    if owner_module._native_active():
        if not owner_module._native_fault:
            owner_module._native_fault_source = "incomplete_restore"
        owner_module._native_fault = True
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] NATIVE_RESTORE_FAILED reason={reason} "
            "error=owned native state remains after restore"
        )
        return False
    try:
        native_ladder_guard.remove(owner_module)
    except Exception as exc:
        owner_module._native_fault = True
        owner_module._native_fault_source = "ladder_guard_cleanup"
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] LADDER_GUARD_REMOVE_FAILED "
            f"reason={reason} error={type(exc).__name__}: {exc}; restart game"
        )
        return False
    # A previous recoil failure can be transient (e.g. GroundSlamExit).
    # Only a later verified restore or weak-verified owner destruction may clear
    # its latch. Beam/unknown failures remain latched for process safety.
    if (
        owner_module._native_fault
        and owner_module._native_fault_source == "recoil_restore"
        and recoil_restored
    ):
        owner_module._native_fault = False
        owner_module._native_fault_source = None
        owner_module.logging.info(
            f"[BL4ThirdPersonPOC] NATIVE_FAULT_RECOVERED reason={reason}"
        )
    if reason != "failed_activation":
        owner_module._native_last_attempt = None
    owner_module._native_ads_origin_attempt = None
    owner_module._native_slide_interior = False
    owner_module.logging.info(f"[BL4ThirdPersonPOC] NATIVE_STOP reason={reason}")
    return True


def _native_start_impl(*, allow_tps_ads: bool = False, owner_module) -> None:
    """Arm recoil once per camera; arm Beam only for a guarded FireBeam."""
    import sys
    from . import (
        native_beam_collision,
        native_beam_origin,
        native_recoil,
        native_ladder_guard,
    )

    if (
        getattr(native_ladder_guard, "DEFAULT_VARIANT", None)
        != "owned-ladder-default-handoff"
    ):
        raise RuntimeError("Cached LadderGuard is not GF; restart BL4")
    owner_module._require_guarded_beam_collision(native_beam_collision)
    if owner_module._native_fault or owner_module._beam_active():
        raise RuntimeError("Beam patch active or recovery failed; restart game")
    pending_owner = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
    if (
        owner_module._active_native_state.get("ladder_guard") is not None
        and pending_owner is not None
        and not getattr(pending_owner, "active", False)
    ):
        raise RuntimeError("LadderGuard activation already in progress")
    if not owner_module._ffyl_native_pre_installed or owner_module._native_ffyl_pending:
        raise RuntimeError("FFYL PRE protection unavailable; native correction refused")
    pc, pawn, camera = owner_module._get_runtime()
    if any(value is None for value in (pc, pawn, camera)):
        raise RuntimeError("Gameplay required")
    ads_ready = bool(
        allow_tps_ads
        and (
            owner_module._native_slide_ads_ready(camera, pawn)
            or _held_ads_rearm_ready(camera, pawn, owner_module=owner_module)
        )
    )
    if (
        not owner_module._third_person_enabled
        or not owner_module._third_person_pushed
        or (
            not ads_ready
            and (
                owner_module._ads_active
                or owner_module._ads_route != "hip"
                or owner_module._ads_tps_state is not None
            )
        )
        or (owner_module._slide_active and not owner_module._native_slide_interior)
        or owner_module._ladder_active
        or owner_module._native_ladder_handoff_pending
        or owner_module._native_slide_handoff_pending
        or owner_module._vehicle_camera_active
        or owner_module._shop_camera_active
    ):
        raise RuntimeError("Settled TPS hip view required")
    if str(camera.GetActorCameraMode(pawn)) != "ThirdPerson":
        raise RuntimeError("Wait for settled ThirdPerson camera mode")
    # Internal components own their precise build, Look copy, and FireBeam guards.
    try:
        owned_recoil = sys.modules.get(owner_module._NATIVE_OWNER_KEYS[2])
        if owned_recoil is None or not getattr(owned_recoil, "active", False):
            recoil = native_recoil.apply_or_restore()
            if recoil.get("errors") or recoil.get("action") != "TPS_WEAPONLOOK_UPDATE":
                raise RuntimeError(f'Recoil refused: {recoil.get("errors")}')
        elif int(camera._get_address()) != owned_recoil.identity[0]:
            raise RuntimeError("Recoil owned by a different camera; restart game")
        native_ladder_guard.ensure_default(owner_module, pc, pawn, camera)
        weapon = camera.CameraModeInputs.Weapon
        # A FireBeam variant is proven only by the two guarded native helpers.
        # Weapon unavailable: recoil remains enabled; beam can be armed after equip.
        if (
            weapon is not None
            and not ads_ready
            and (not owner_module._slide_active or owner_module._native_slide_interior)
            and owner_module._ads_route == "hip"
            and owner_module._ads_tps_state is None
            and not owner_module._ads_active
            and native_beam_origin.is_firebeam(weapon)
        ):
            origin = native_beam_origin.apply_or_restore()
            if origin.get("action") == "TPS_QUERY_ORIGIN_ON" and not origin.get(
                "errors"
            ):
                sys.modules[owner_module._NATIVE_OWNER_KEYS[1]].weapon_address = int(
                    weapon._get_address()
                )
                if owner_module._slide_active:
                    # During Slide, enable only the measured query-origin correction;
                    # leave collision unarmed. Keep the native handoff guard:
                    # the native Default PRE guard retires it before the old
                    # Look copy can be replaced at the Slide exit.
                    owner_module.logging.warning(
                        "[BL4ThirdPersonPOC] SLIDE_BEAM_ORIGIN_ON "
                        "beam_origin=True beam_collision=False"
                    )
                    return
                collision = native_beam_collision.apply_or_restore()
                if (
                    collision.get("action") != "TPS_CAPPED_PREFIX_ON"
                    or collision.get("version") != "guarded-prefix-collision"
                    or collision.get("errors")
                ):
                    raise RuntimeError(
                        f'Beam collision refused: {collision.get("errors")}'
                    )
                sys.modules[owner_module._NATIVE_OWNER_KEYS[0]].weapon_address = int(
                    weapon._get_address()
                )
                owner_module.logging.info(
                    "[BL4ThirdPersonPOC] NATIVE_ON recoil=True beam=True"
                )
                return
            if sys.modules.get(owner_module._NATIVE_OWNER_KEYS[1]) is not None:
                raise RuntimeError(
                    f'Beam origin recovery state after refusal: {origin.get("errors")}'
                )
        owner_module.logging.info(
            "[BL4ThirdPersonPOC] NATIVE_ON recoil=True beam=False"
        )
    except Exception:
        if not owner_module._native_stop("failed_activation"):
            owner_module._native_fault = True
        raise


def _quarantine_native_patch_impl(
    kind: str,
    state: dict[str, Any],
    reason: str,
    *,
    owner_module,
) -> None:
    """Retain failed native restoration state and its backing pins across reload.

    Deduplicate by state identity. The quarantine owns recovery evidence; it
    does not authorize freeing, replacing foreign bytes or rearming the feature.
    """
    for entry in owner_module._native_patch_quarantine:
        if entry.get("state") is state:
            entry["reason"] = reason
            return
    owner_module._native_patch_quarantine.append(
        {
            "kind": kind,
            "state": state,
            "reason": reason,
            "attempts": 0,
        }
    )
    setattr(
        owner_module.builtins,
        owner_module.NATIVE_PATCH_QUARANTINE_NAME,
        owner_module._native_patch_quarantine,
    )
    owner_module.logging.error(
        "[BL4ThirdPersonPOC] NATIVE_PATCH_QUARANTINED "
        f"kind={kind!r}, reason={reason!r}; backing buffers retained"
    )


def _retry_native_patch_quarantine_impl(
    *, kind: str | None = None, owner_module
) -> bool:
    """Retry only supported quarantined owners using their existing release gates.

    Stop item-card publication or remove the prompt publisher before restoring
    dependent hooks. Keep unresolved/unknown entries and report each failure.
    A true result means no matching quarantine entry remains, not native quiescence.
    """
    unresolved: list[dict[str, Any]] = []
    for entry in tuple(owner_module._native_patch_quarantine):
        entry_kind = str(entry.get("kind", "unknown"))
        if kind is not None and entry_kind != kind:
            unresolved.append(entry)
            continue
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        state = entry.get("state")
        failures: list[Exception] = []
        if not isinstance(state, dict):
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] Invalid native quarantine entry "
                f"kind={entry_kind!r}"
            )
            unresolved.append(entry)
            continue
        if entry_kind == "item_card":
            control_stopped = False
            try:
                from .item_card_runtime import _stop_item_card_publication_impl

                _stop_item_card_publication_impl(state, owner_module=owner_module)
                control_stopped = True
            except Exception as exc:
                failures.append(exc)
            for hook_name in (("final_hook", "gate2_hook") if control_stopped else ()):
                hook = state.get(hook_name)
                if not isinstance(hook, dict):
                    continue
                try:
                    owner_module._native_restore_hook(hook)
                    owner_module._native_release_hook(hook)
                except Exception as exc:
                    failures.append(exc)
            resolved = control_stopped and all(
                not isinstance(state.get(name), dict)
                or (state[name].get("restored") and not int(state[name].get("stub", 0)))
                for name in ("final_hook", "gate2_hook")
            )
        elif entry_kind == "pickup_registry":
            try:
                from . import pickup_registry

                current = getattr(owner_module, "_pickup_registry_state", None)
                if current is not state:
                    if isinstance(current, dict) and current.get("active"):
                        raise RuntimeError("Different pickup registry owner remains active")
                    owner_module._pickup_registry_state = state
                resolved = pickup_registry.stop(owner_module, "quarantine_retry")
            except Exception as exc:
                failures.append(exc)
                resolved = False
        elif entry_kind == "prompt":
            try:
                state["control"].enabled = 0
            except Exception as exc:
                failures.append(exc)
            try:
                from .interaction_runtime import _remove_prompt_update_hook_impl

                _remove_prompt_update_hook_impl(state, owner_module=owner_module)
            except Exception as exc:
                failures.append(exc)
            if not state.get("restored"):
                try:
                    from .interaction_runtime import _restore_owned_query_bytes_impl

                    _restore_owned_query_bytes_impl(
                        state, state["original"], owner_module=owner_module
                    )
                except Exception as exc:
                    failures.append(exc)
            if (
                not state.get("hook_installed")
                and state.get("restored")
                and int(state.get("stub", 0))
            ):
                try:
                    owner_module._retire_prompt_stub(state)
                except Exception as exc:
                    failures.append(exc)
            resolved = (
                not state.get("hook_installed")
                and bool(state.get("restored"))
                and not int(state.get("stub", 0))
            )
        elif entry_kind == "npc":
            try:
                owner_module._npc_reset_tracking(state)
                from .interaction_runtime import _restore_owned_query_bytes_impl

                _restore_owned_query_bytes_impl(
                    state, owner_module.NPC_ELIGIBLE_ORIGINAL, owner_module=owner_module
                )
                owner_module._retire_npc_eligible_stub(state)
            except Exception as exc:
                failures.append(exc)
            resolved = bool(state.get("restored")) and not int(state.get("stub", 0))
        else:
            resolved = False
            failures.append(RuntimeError(f"Unknown quarantine kind: {entry_kind}"))
        for failure in failures:
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] Native quarantine retry failure "
                f"kind={entry_kind!r}: {type(failure).__name__}: {failure}"
            )
        if resolved:
            owner_module.logging.info(
                "[BL4ThirdPersonPOC] NATIVE_PATCH_QUARANTINE_CLEARED "
                f"kind={entry_kind!r}, attempts={entry['attempts']}"
            )
        else:
            unresolved.append(entry)
    owner_module._native_patch_quarantine[:] = unresolved
    setattr(
        owner_module.builtins,
        owner_module.NATIVE_PATCH_QUARANTINE_NAME,
        owner_module._native_patch_quarantine,
    )
    return not any(
        kind is None or entry.get("kind") == kind
        for entry in owner_module._native_patch_quarantine
    )
