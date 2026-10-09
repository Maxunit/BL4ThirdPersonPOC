"""Bind local DownState/camera request events to the selected FFYL owner.

The production coordinator publishes this binding before install, validates the
native build and shuts down legacy FFYL. The direct-Outer/local predicate binds
DownState notifications to the serial-checked local controller. Shared lifecycle
routing defers while this binding controls a transition. Track each stable hook
before installation; failed native or SDK cleanup keeps ownership selected.
"""

import logging

CAMERA_REQUEST_FIELDS = {
    "/Script/OakGame.OakPlayerController:CameraTransition": (
        "NewMode",
        "Transition",
        "BlendTimeOverride",
        "bTeleport",
        "bForceResetMode",
    ),
    "/Script/OakGame.OakPlayerController:ServerCameraTransition": (
        "NewMode",
        "Transition",
        "BlendTimeOverride",
        "bTeleport",
        "bForceResetMode",
    ),
    "/Script/Engine.PlayerController:ClientSetCameraMode": ("NewCamMode",),
}


class FFYLCameraEventBindings:
    """Own the SDK hooks and retain their camera owner until verified cleanup."""

    def __init__(self, owner, mod, *, hooks, is_local_down_state):
        if not callable(is_local_down_state):
            raise RuntimeError("Local DownState ownership predicate required")
        self.owner = owner
        self._mod = mod
        self._hooks_api = hooks
        self._is_local_down_state = is_local_down_state
        self._registered = []
        self.active = False
        self.seen_ffyl = False
        self.second_wind = False
        self.exit_seen = False
        self.awaiting_uncaptured_default = False
        self._request_busy = False
        self.redirected_requests = 0
        self.failures = []
        self.cleanup_errors = []

    def install(self):
        """Register and observe each stable hook ID; track before a partial add.

        False from add_hook is not a refusal if has_hook confirms registration.
        Existing matching IDs are not ours to remove and are refused unchanged.
        Registration failures stop publication and attempt native + SDK cleanup.
        """
        if self.active or self._registered or self.owner.closed:
            raise RuntimeError("FFYL event binding already active, retained or closed")
        api = self._hooks_api
        if not hasattr(api, "Block"):
            raise RuntimeError("SDK hook Block token unavailable")
        plans = [
            (
                self._mod.FFYL_EARLY_ENDED_FUNCTION,
                api.Type.PRE,
                "bl4tps.ffyl_simple.ended",
                self._ended,
            ),
            (
                self._mod.CLIENT_RESTART_FUNCTION,
                api.Type.PRE,
                "bl4tps.ffyl_simple.restart",
                self._restart,
            ),
            (
                self._mod.FIRST_PERSON_ANIM_HOOK,
                api.Type.POST_UNCONDITIONAL,
                "bl4tps.ffyl_simple.frame",
                self._frame,
            ),
        ]
        plans.extend(
            (
                path,
                api.Type.PRE,
                "bl4tps.ffyl_simple.request." + str(index),
                self._request_callback(fields),
            )
            for index, (path, fields) in enumerate(CAMERA_REQUEST_FIELDS.items())
        )
        plans.append(
            (
                self._mod.FFYL_DOWNED_FUNCTION,
                api.Type.PRE,
                "bl4tps.ffyl_simple.downed",
                self._downed,
            )
        )
        # Preflight ALL identifiers before taking ownership of any registration.
        for path, kind, identifier, callback in plans:
            if api.has_hook(path, kind, identifier):
                raise RuntimeError("FFYL SDK hook ID already registered: " + identifier)
        # Callbacks stay inert until every dependency is registered.
        self.active = False
        try:
            for path, kind, identifier, callback in plans:
                spec = (path, kind, identifier)
                self._registered.append(spec)
                api.add_hook(*spec, callback)
                if not api.has_hook(*spec):
                    raise RuntimeError(
                        "FFYL SDK hook registration unverified: " + identifier
                    )
            self.active = True
        except Exception as exc:
            self.failures.append("install: " + repr(exc))
            self.shutdown("hook_install_failed")
            raise

    def shutdown(self, reason):
        """Stop callbacks first; attempt native cleanup and every tracked hook.

        Silent removal failures and lookup errors keep the registration tracked.
        Native failure does not prevent SDK-removal attempts. The coordinator must
        retain this object whenever False is returned, including after pawn change.
        """
        self.active = False
        self.cleanup_errors = []
        try:
            if self.owner.close(reason) is not True:
                raise RuntimeError("FFYL owner close unverified")
        except Exception as exc:
            self.cleanup_errors.append("owner: " + repr(exc))
        api = self._hooks_api
        for spec in list(self._registered):
            try:
                if api.has_hook(*spec):
                    api.remove_hook(*spec)
                if api.has_hook(*spec):
                    raise RuntimeError("FFYL SDK hook remains registered")
                self._registered.remove(spec)
            except Exception as exc:
                self.cleanup_errors.append("hook " + spec[2] + ": " + repr(exc))
        return self.owner.closed and not self._registered and not self.cleanup_errors

    def _fail(self, reason, exc):
        self.failures.append(reason + ": " + repr(exc))
        self.shutdown(reason)

    @property
    def cleanup_complete(self):
        """Only verified native/SDK cleanup permits strategy retirement."""
        return (
            not self.active
            and self.owner.closed
            and not self._registered
            and not self.cleanup_errors
        )

    @property
    def controls_transition(self):
        """Keep shared repair off this cycle, including retained cleanup faults."""
        return (self.active and self.seen_ffyl) or (
            not self.owner.closed
            and (
                self.owner.context is not None
                or self.owner.faulted
                or self.owner.camera_handoff_uncertain
            )
        )

    def _request_callback(self, fields):
        def request(obj, args, ret, func):
            if not self.active or self._request_busy:
                return
            invoked = False
            try:
                pc, pawn, manager = self.owner.current_runtime()
                if obj is None or int(obj._get_address()) != int(pc._get_address()):
                    return
                if (
                    not self._mod._third_person_enabled
                    or self._mod.tps_ffyl_beta.value is not True
                ):
                    self.shutdown("request_feature_or_tps_disabled")
                    return
                values = [getattr(args, field) for field in fields]
                requested = str(values[0])
                if requested != "ThirdPerson":
                    self.owner.release_native("camera_request")
                if requested == "Default" and self.awaiting_uncaptured_default:
                    # Let the observed short-cycle exit discard its native stack.
                    # The frame route repairs only after settled, verified empty Default.
                    return
                redirect = requested == "FFYL" or (
                    requested == "Default" and self.seen_ffyl
                )
                if not redirect:
                    if self.seen_ffyl and requested != "ThirdPerson":
                        self.shutdown("outside_ffyl_request:" + requested)
                    return
                if bool(pawn.ZoomState.bWantsToZoom):
                    self.shutdown("zoom_request_outside_ffyl_scope")
                    return
                if requested == "FFYL":
                    self.owner.release_ground_slam()
                    self.seen_ffyl = True
                values[0] = "ThirdPerson"
                self._request_busy = True
                # After invocation begins, a raised SDK exception may already have
                # changed the camera. Do not execute the original a second time.
                invoked = True
                func(*values)
                self.redirected_requests += 1
                return self._hooks_api.Block
            except Exception as exc:
                if invoked:
                    self.owner.camera_handoff_uncertain = True
                    self.owner.faulted = True
                self._fail("request_error", exc)
                if invoked:
                    return self._hooks_api.Block
            finally:
                self._request_busy = False

        return request

    def _ended(self, obj, args, ret, func):
        if not self.active or not self.seen_ffyl or self.exit_seen:
            return
        try:
            if self._is_local_down_state(obj, args) is not True:
                return
            self.owner.current_runtime()
            # Release before the original game's exit can replace the live Look.
            # Reflection records lower-case reason. Keep the existing SDK alias
            # as a compatibility fallback, but missing data is not a death exit.
            reason_value = getattr(args, "reason", None)
            if reason_value is None:
                reason_value = getattr(args, "Reason", None)
            if reason_value is None:
                raise RuntimeError("DownState exit reason unavailable")
            self.exit_seen = True
            reason = str(reason_value)
            self.second_wind = reason == "2" or "SecondWind" in reason
            self.owner.release_native("downed_ended_pre")
            self.awaiting_uncaptured_default = (
                self.second_wind and self.owner.context is None
            )
            if self.awaiting_uncaptured_default:
                logging.info(
                    "[BL4ThirdPersonPOC.FFYLStrategy] SHORT_EXIT_WAIT "
                    "native_released=True awaiting_settled_empty_default=True"
                )
            if not self.second_wind:
                self.shutdown("non_secondwind_exit")
        except Exception as exc:
            self._fail("exit_error", exc)

    def _downed(self, obj, args, ret, func):
        """Release before entry without arming the legacy resume machinery."""
        if not self.active or self.seen_ffyl:
            return
        try:
            if self._is_local_down_state(obj, args) is not True:
                return
            self.owner.current_runtime()
            self.seen_ffyl = True
            self.owner.release_ground_slam()
            self.owner.release_native("downed_pre")
        except Exception as exc:
            self._fail("entry_error", exc)

    def _restart(self, obj, args, ret, func):
        if not self.active:
            return
        try:
            # Possession may already have replaced the pawn at PRE. Authorize
            # retirement through the still-bound local controller alone; never
            # use this cleanup check to authorize camera mutation or activation.
            if not self.owner.matches_restart_controller(obj):
                return
            self.shutdown("client_restart_pre")
        except Exception as exc:
            self._fail("restart_error", exc)

    def _frame(self, obj, args, ret, func):
        if not self.active:
            return
        try:
            if (
                not self._mod._third_person_enabled
                or self._mod.tps_ffyl_beta.value is not True
            ):
                self.shutdown("feature_or_tps_disabled")
                return
            runtime = self.owner.current_runtime_or_none()
            if runtime is None:
                # The old local controller can disappear before ClientRestart.
                # Retire without camera reads/writes; verified cleanup alone
                # lets the coordinator bind again to settled local TPS.
                if self.shutdown("runtime_changed") is True:
                    logging.info(
                        "[BL4ThirdPersonPOC.FFYLStrategy] RUNTIME_RETIRED "
                        "reason=local_lifetime_changed cleanup_complete=True"
                    )
                return
            pc, pawn, manager = runtime
            mode = str(manager.GetActorCameraMode(pawn))
            if mode == "FFYL" and not self.exit_seen:
                self.seen_ffyl = True
                self.owner.prepare_camera()
            elif mode == "ThirdPerson" and self.seen_ffyl:
                if not self.exit_seen:
                    if self.owner.context is not None:
                        self.owner.arm_recoil_if_ready()
                elif (
                    not manager.CameraModeState.bIsTransitioning
                    and not manager.CameraModeState.bShowViewModel
                    and not self.awaiting_uncaptured_default
                ):
                    self.shutdown("secondwind_settled_tps")
            elif mode == "Default" and self.seen_ffyl:
                if self.awaiting_uncaptured_default:
                    if self.owner.recover_uncaptured_secondwind() is True:
                        self.awaiting_uncaptured_default = False
                        logging.info(
                            "[BL4ThirdPersonPOC.FFYLStrategy] SHORT_EXIT_TPS_PUSHED "
                            "empty_default_verified=True native_released=True"
                        )
                elif self.second_wind:
                    self.owner.prepare_camera(allow_default_exit=True)
                elif self.exit_seen:
                    self.shutdown("non_secondwind_default_exit")
                else:
                    self.shutdown("default_without_observed_ffyl_exit")
            elif self.seen_ffyl and mode not in ("FFYL", "ThirdPerson"):
                self.shutdown("outside_owned_ffyl_camera:" + mode)
        except Exception as exc:
            self._fail("frame_error", exc)
