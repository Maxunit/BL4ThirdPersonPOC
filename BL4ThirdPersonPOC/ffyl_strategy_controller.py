"""Explicit selection/retirement boundary for the simplified FFYL strategy.

Production publishes this controller during enable. Build preflight and a proven
local DownState predicate are required dependencies, not guessed SDK field names.
The caller must use controls_transition to scope shared lifecycle/native-auto work
and route shutdown before releasing the shared camera. Preferences are read only.
"""

from .ffyl_camera_owner import FFYLCameraOwner
from .ffyl_camera_events import FFYLCameraEventBindings


class FFYLStrategyController:
    """Publish owners before hook installation and retain failed cleanup state."""

    def __init__(
        self,
        mod,
        *,
        weak_pointer,
        hooks,
        build_preflight,
        resolve_local_down_state,
        stop_legacy,
        stop_ground_slam,
        owner_factory=FFYLCameraOwner,
        binding_factory=FFYLCameraEventBindings
    ):
        for dependency in (
            weak_pointer,
            build_preflight,
            resolve_local_down_state,
            stop_legacy,
            stop_ground_slam,
            owner_factory,
            binding_factory,
        ):
            if not callable(dependency):
                raise RuntimeError("FFYL strategy dependency unavailable")
        self._mod = mod
        self._weak_pointer = weak_pointer
        self._hooks = hooks
        self._build_preflight = build_preflight
        self._resolve_local_down_state = resolve_local_down_state
        self._stop_legacy = stop_legacy
        self._stop_ground_slam = stop_ground_slam
        self._owner_factory = owner_factory
        self._binding_factory = binding_factory
        self.owner = None
        self.binding = None
        self.faulted = False
        self.failures = []
        self._legacy_release_unverified = False

    @property
    def controls_transition(self):
        return self.binding is not None and self.binding.controls_transition

    def start_if_ready(self):
        """Select once from settled normal TPS; never retry a fault each frame."""
        if self.binding is not None or self.owner is not None or self.faulted:
            return False
        mod = self._mod
        if (
            not mod._third_person_enabled
            or mod.tps_ffyl_beta.value is not True
            or mod._native_fault
        ):
            return False
        try:
            pc, pawn, manager = mod._get_runtime()
            if any(obj is None for obj in (pc, pawn, manager)):
                return False
            if (
                str(manager.GetActorCameraMode(pawn)) != "ThirdPerson"
                or manager.CameraModeState.bIsTransitioning
                or manager.CameraModeState.bShowViewModel
                or bool(pawn.ZoomState.bWantsToZoom)
                or mod._camera_lifecycle.get("pending")
                or getattr(mod, "_native_ffyl_pending", False)
                or getattr(mod, "_ffyl_native_resume_pending", False)
            ):
                return False
            if any(
                bool(getattr(mod, key, False))
                for key in (
                    "_ads_active",
                    "_slide_active",
                    "_vehicle_camera_active",
                    "_shop_camera_active",
                    "_ladder_active",
                )
            ):
                return False
            if self._build_preflight(mod) is not True:
                raise RuntimeError("FFYL build preflight unverified")
            local_predicate = self._resolve_local_down_state(mod)
            if not callable(local_predicate):
                raise RuntimeError("Local DownState ownership unresolved")
            self._legacy_release_unverified = True
            if self._stop_legacy("select_simplified_ffyl") is not True:
                raise RuntimeError("Legacy FFYL release unverified")
            self._legacy_release_unverified = False
            # Publish before SDK registration can run or fail partway through.
            self.owner = self._owner_factory(
                mod,
                weak_pointer=self._weak_pointer,
                stop_ground_slam=self._stop_ground_slam,
            )
            self.binding = self._binding_factory(
                self.owner, mod, hooks=self._hooks, is_local_down_state=local_predicate
            )
            self.binding.install()
            return True
        except Exception as exc:
            self.faulted = True
            self.failures.append("start: " + repr(exc))
            return False

    def retire_if_complete(self):
        """Observe completion only; failed cleanup requires explicit shutdown retry."""
        if self.binding is None:
            return False
        if self.binding.failures or self.binding.cleanup_errors:
            self.faulted = True
            for detail in (*self.binding.failures, *self.binding.cleanup_errors):
                if detail not in self.failures:
                    self.failures.append(detail)
        if not self.binding.cleanup_complete:
            return False
        self.binding = None
        self.owner = None
        return True

    def shutdown(self, reason):
        """Release references only after the selected native/SDK owners verify close."""
        try:
            if self.binding is not None:
                if self.binding.shutdown(reason) is not True:
                    raise RuntimeError("FFYL binding cleanup incomplete")
            elif self.owner is not None:
                if self.owner.close(reason) is not True:
                    raise RuntimeError("FFYL owner cleanup incomplete")
            if self._legacy_release_unverified:
                if self._stop_legacy(reason) is not True:
                    raise RuntimeError("Legacy FFYL cleanup still unverified")
                self._legacy_release_unverified = False
        except Exception as exc:
            self.faulted = True
            self.failures.append("shutdown: " + repr(exc))
            return False
        self.binding = None
        self.owner = None
        self.faulted = False
        self._fault_reported = False
        return True
