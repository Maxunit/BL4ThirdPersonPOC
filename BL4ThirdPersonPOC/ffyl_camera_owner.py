"""Own one local simplified FFYL camera/recoil handoff cycle.

The coordinator validates the build and shuts down legacy FFYL before creation.
Ground Slam and native dependencies must release before any camera mutation.
Serial-checked controller/pawn/manager identity scopes pop/push and recoil capture.
Successful TPS bookkeeping transfers to the shared camera owner. Uncertain
camera or native cleanup remains a fault. A witnessed uncaptured Second Wind
waits for verified settled Default with an empty stack before recreating TPS.
No timer, hook registration, preference write or callback swap occurs here.
"""

import sys

from .ffyl_recoil_context import capture_ffyl_recoil_context

# Compatibility owner keys until the legacy strategy is retired. They prevent
# both implementations from owning the same FFYL transition at the same time.
LEGACY_FFYL_OWNER_KEYS = ("_bl4tps_ffyl_beta_owner", "_bl4tps_ffyl_beta_collision")
MAX_REPUSHES_PER_CYCLE = 12


class FFYLCameraOwner:
    """One local FFYL cycle, with native cleanup before camera ownership changes."""

    def __init__(self, mod, *, weak_pointer, stop_ground_slam):
        if not callable(stop_ground_slam):
            raise RuntimeError("Ground Slam release dependency unavailable")
        if any(sys.modules.get(key) is not None for key in LEGACY_FFYL_OWNER_KEYS):
            raise RuntimeError(
                "Release the legacy FFYL owner before selecting simplified FFYL"
            )
        objects = mod._get_runtime()
        if len(objects) != 3 or any(obj is None for obj in objects):
            raise RuntimeError("Local FFYL gameplay unavailable")
        self._mod = mod
        self._stop_ground_slam = stop_ground_slam
        self._weak_pointer = weak_pointer
        self._identity = tuple(int(obj._get_address()) for obj in objects)
        self._references = tuple(weak_pointer(obj) for obj in objects)
        self.context = None
        self._entry_blend = None
        self._entry_blend_used = False
        self.closed = False
        self.faulted = False
        self.camera_handoff_uncertain = False
        self.repushes = 0
        self._recoil_attempted = False
        self._recoil_verified = False
        self._current()

    def current_runtime_or_none(self):
        """Resolve the complete weak binding; a replaced/expired lifetime retires it.

        None authorizes cleanup only. SDK/lookup errors still propagate and must
        not be mistaken for an ordinary save-load or possession transition.
        """
        objects = self._mod._get_runtime()
        bound = tuple(ref() for ref in self._references)
        if (
            len(objects) != 3
            or any(obj is None for obj in objects)
            or any(obj is None for obj in bound)
            or tuple(int(obj._get_address()) for obj in objects) != self._identity
            or tuple(int(obj._get_address()) for obj in bound) != self._identity
        ):
            return None
        return objects

    def _current(self):
        objects = self.current_runtime_or_none()
        if objects is None:
            raise RuntimeError("Local FFYL controller/pawn/manager lifetime changed")
        return objects

    def current_runtime(self):
        """Return only the still-bound local objects to the event coordinator."""
        return self._current()

    def matches_restart_controller(self, obj):
        """Authorize cleanup by the live local controller, not its changing pawn.

        ClientRestart also runs on vehicle possession. The current pawn/manager
        can already differ from this binding at PRE; that is why we retire it.
        This permits cleanup only. Camera mutation and recoil activation still
        require the complete bound runtime through _current().
        """
        if obj is None or int(obj._get_address()) != self._identity[0]:
            return False
        bound_pc = self._references[0]()
        current = self._mod._get_runtime()
        current_pc = current[0] if len(current) == 3 else None
        event_pc = self._weak_pointer(obj)()
        if any(pc is None for pc in (bound_pc, current_pc, event_pc)) or any(
            int(pc._get_address()) != self._identity[0]
            for pc in (bound_pc, current_pc, event_pc)
        ):
            raise RuntimeError("Local FFYL restart controller lifetime changed")
        return True

    def _require_open(self):
        if self.closed or self.faulted:
            raise RuntimeError("FFYL camera owner closed or retained after a fault")

    def _require_owned_tps(self):
        owner = self._mod._camera_stack_owner
        if (
            not owner.get("owned")
            or not self._mod._third_person_pushed
            or (owner.get("pawn_address"), owner.get("manager_address"))
            != self._identity[1:]
        ):
            raise RuntimeError("FFYL handoff does not own the local TPS camera layer")

    def release_ground_slam(self):
        """Retire the prior TPS baseline before any FFYL camera replacement.

        The callback must verify removal of Ground Slam's SDK/native hooks and
        private runtime state. False/None blocks our camera mutation. It is also
        called before entry requests, since those can replace TPS before a frame.
        """
        self._require_open()
        self._current()
        try:
            if self._stop_ground_slam("ffyl_camera_entry") is not True:
                raise RuntimeError("Ground Slam release remains unverified")
        except Exception:
            self.faulted = True
            raise

    def release_native(self, reason):
        """Revoke activation, then verify all native dependencies have been released.

        The production stop path handles serial-expired native owners safely.
        It must return explicit True AND leave no active recoil/beam/Set/default
        guard. Failure retains this owner/context and propagates to the coordinator.
        """
        self._entry_blend = None
        if self.closed:
            return
        try:
            if self.context is not None:
                self.context.revoke_activation()
            stopped = self._mod._native_stop("ffyl_camera:" + reason)
            if (
                stopped is not True
                or self._mod._native_active()
                or any(
                    self._mod._active_native_state.get(key) is not None
                    for key in ("ladder_guard", "ladder_default")
                )
            ):
                raise RuntimeError("FFYL native release remains unverified")
        except Exception:
            self.faulted = True
            raise
        self._recoil_verified = False

    def _report_blend_refusal(self, exc):
        self._entry_blend = None
        logger = getattr(self._mod, 'logging', None)
        if logger is not None:
            logger.warning('[BL4ThirdPersonPOC] FFYL_ENTRY_BLEND_REFUSED ' + repr(exc))

    def compensate_entry_offset(self, values):
        if self._entry_blend is None:
            return values
        try:
            self._require_open()
            self._current()
            result = self._entry_blend.apply(self, values)
            if self._entry_blend.done:
                self._entry_blend = None
            return result
        except Exception as exc:
            self._report_blend_refusal(exc)
            return values

    def prepare_camera(self, *, allow_default_exit=False):
        """Replace ONLY the owned TPS layer above the game's observed FFYL layer.

        Matches the measured simple strategy: retain FFYL, pop our owned TPS,
        push ThirdPerson with Default transition, record ownership immediately,
        then reuse the shared shoulder-offset compositor. No offset is hardcoded.
        A push/record failure cannot trigger a blind retry or a clean-close claim.
        """
        self._require_open()
        pc, pawn, manager = self._current()
        mode = str(manager.GetActorCameraMode(pawn))
        is_default_exit = (
            mode == "Default" and allow_default_exit and self.context is not None
        )
        if not self._mod._third_person_enabled or (
            mode != "FFYL" and not is_default_exit
        ):
            raise RuntimeError(
                "FFYL preparation requires FFYL or an explicitly bound Default exit"
            )
        self._require_owned_tps()
        if self.repushes >= MAX_REPUSHES_PER_CYCLE:
            raise RuntimeError("FFYL recovery limit reached")
        self.release_ground_slam()
        self.release_native("before_tps_repush")
        if not is_default_exit:
            self.context = capture_ffyl_recoil_context(
                pc,
                pawn,
                manager,
                weak_pointer=self._weak_pointer,
                read=self._mod._native_read,
            )
        else:
            # Exit reuses restoration evidence only; it does not recapture FFYL
            # or permit fresh recoil activation after Second Wind.
            self.context.proof_context(for_restore=True)
        if not is_default_exit and not self._entry_blend_used:
            self._entry_blend_used = True
            try:
                from .ffyl_entry_blend import EntryBlend
                self._entry_blend = EntryBlend(self._mod, self._weak_pointer)
            except Exception as exc:
                self._report_blend_refusal(exc)
        self._current()
        self._require_owned_tps()
        self.camera_handoff_uncertain = True
        try:
            if (
                self._mod._pop_third_person(
                    reason="ffyl_owned_handoff", transition_time=-1.0
                )
                is not True
            ):
                raise RuntimeError("Owned FFYL TPS pop unverified")
            manager.PushActorCameraMode(pawn, "ThirdPerson", "Default", -1.0, False)
            self._mod._record_camera_stack_owner(pawn, manager)
            self._require_owned_tps()
            self.camera_handoff_uncertain = False
            self.repushes += 1
            self._mod._apply_camera_offset()
        except Exception:
            self.faulted = True
            raise

    def recover_uncaptured_secondwind(self):
        """Recover a witnessed Second Wind that preceded FFYL runtime capture.

        The old TPS can look settled before the game's delayed Default reset.
        Keep native released until Default is actually settled and the reviewed
        stack helper proves that the game discarded all camera entries. Retire
        bookkeeping without popping that empty stack, then create a fresh TPS.
        This is cleanup/recovery only; no FFYL recoil context is fabricated.
        """
        self._require_open()
        pc, pawn, manager = self._current()
        if self.context is not None:
            raise RuntimeError("Uncaptured Second Wind recovery has an FFYL context")
        if (
            not self._mod._third_person_enabled
            or str(manager.GetActorCameraMode(pawn)) != "Default"
            or manager.CameraModeState.bIsTransitioning
            or bool(pawn.ZoomState.bWantsToZoom)
            or any(
                bool(getattr(self._mod, key, False))
                for key in (
                    "_vehicle_camera_active",
                    "_ladder_active",
                    "_shop_camera_active",
                )
            )
        ):
            return False
        self._require_owned_tps()
        if self._mod._ffyl_camera_stack_empty(manager) is not True:
            return False
        self.release_native("uncaptured_secondwind_default")
        self._current()
        self._require_owned_tps()
        if (
            str(manager.GetActorCameraMode(pawn)) != "Default"
            or manager.CameraModeState.bIsTransitioning
            or self._mod._ffyl_camera_stack_empty(manager) is not True
        ):
            return False
        self._mod._retire_camera_stack_owner("ffyl_uncaptured_secondwind_empty_stack")
        self.camera_handoff_uncertain = True
        try:
            manager.PushActorCameraMode(pawn, "ThirdPerson", "Default", -1.0, False)
            self._mod._record_camera_stack_owner(pawn, manager)
            self._require_owned_tps()
            self.camera_handoff_uncertain = False
            self.repushes += 1
            self._mod._apply_camera_offset()
            return True
        except Exception:
            self.faulted = True
            raise

    def arm_recoil_if_ready(self):
        """Try the production recoil path once; preserve the user's native preference.

        Transition, viewmodel, zoom and Beam states wait without arming. The event
        coordinator decides the cycle's exit; this method never redirects a request.
        Unverified activation retains the context for cleanup and never retries.
        """
        self._require_open()
        if self.context is None:
            raise RuntimeError("FFYL recoil requires a prepared camera context")
        _, pawn, manager = self._current()
        if self._recoil_attempted:
            return self._recoil_verified
        if (
            not self._mod._native_auto_enabled
            or str(manager.GetActorCameraMode(pawn)) != "ThirdPerson"
            or manager.CameraModeState.bIsTransitioning
            or manager.CameraModeState.bShowViewModel
            or bool(pawn.ZoomState.bWantsToZoom)
        ):
            return False
        from . import native_beam_origin, native_recoil

        if native_beam_origin.is_firebeam(manager.CameraModeInputs.Weapon):
            return False
        self._recoil_attempted = True
        try:
            if self._mod._native_fault:
                raise RuntimeError("Native fault blocks FFYL recoil activation")
            result = native_recoil.apply_or_restore(ffyl_context=self.context)
            recoil = sys.modules.get(self._mod._NATIVE_OWNER_KEYS[2])
            guard = self._mod._active_native_state.get("ladder_guard")
            if (
                result.get("errors")
                or result.get("limits")
                or result.get("action") != "TPS_WEAPONLOOK_UPDATE"
                or result.get("ab_verified") is not True
                or result.get("restore_pending") is not True
                or result.get("ffyl_upper_tps_owner_verified") is not True
                or recoil is None
                or getattr(recoil, "active", False) is not True
                or getattr(recoil, "ffyl_recoil_context", None) is not self.context
                or guard is None
                or guard.get("ffyl_upper_tps") is not True
                or guard.get("owner_identity") != tuple(recoil.identity)
            ):
                raise RuntimeError("Bound FFYL recoil activation unverified")
            if self._mod._beam_active():
                raise RuntimeError(
                    "Unexpected Beam owner during FFYL recoil activation"
                )
            self._recoil_verified = True
            return True
        except Exception:
            self.faulted = True
            raise

    def close(self, reason):
        """Finish resource cleanup without popping a now-shared TPS camera layer.

        Second Wind/death/Restart/disable coordinators must call this before
        replacing the camera owner. An uncertain pop/push keeps this owner held,
        even if native cleanup succeeded. Verified close is idempotent.
        """
        if self.closed:
            return True
        self.release_native(reason)
        if self.camera_handoff_uncertain:
            raise RuntimeError("FFYL camera handoff remains uncertain; owner retained")
        self.closed = True
        return True
