"""Opt-in wall-time profiling on Omni's existing game-thread callbacks.

F10 starts an armed capture outside the console. No producer, native patch,
timer, UObject cache or gameplay-state write is introduced. Detail wrappers
exist only during a capture and are restored without overwriting other owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from time import perf_counter_ns
from typing import Any, Callable
import json
import threading

from .common import KEY, REPORT_DIRECTORY_NAME

TAG = "[OmniPerformance] "
ROOTS = ("callback.lifecycle", "callback.vehicle", "callback.gameplay")
_armed: dict[str, Any] | None = None
_active: Capture | None = None
_last: dict[str, Any] | None = None


@dataclass
class Cost:
    calls: int = 0
    inclusive_ns: int = 0
    exclusive_ns: int = 0
    max_ns: int = 0
    exceptions: int = 0

    def add(self, elapsed: int, children: int, failed: bool) -> None:
        self.calls += 1
        self.inclusive_ns += elapsed
        self.exclusive_ns += max(0, elapsed - children)
        self.max_ns = max(self.max_ns, elapsed)
        self.exceptions += int(failed)

    def export(self, updates: int) -> dict[str, Any]:
        return dict(calls=self.calls, calls_per_update=self.calls / max(1, updates),
                    inclusive_us_per_call=self.inclusive_ns / max(1, self.calls) / 1000,
                    exclusive_us_per_call=self.exclusive_ns / max(1, self.calls) / 1000,
                    inclusive_ms_per_update=self.inclusive_ns / max(1, updates) / 1e6,
                    exclusive_ms_per_update=self.exclusive_ns / max(1, updates) / 1e6,
                    max_inclusive_us=self.max_ns / 1000, exceptions=self.exceptions)


def distribution(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return dict(count=0, mean_ms=None, p50_ms=None, p95_ms=None, max_ms=None)
    ordered = sorted(values)
    return dict(count=len(values), mean_ms=sum(values) / len(values) / 1e6,
                p50_ms=ordered[(len(values) - 1) // 2] / 1e6,
                p95_ms=ordered[max(0, (95 * len(values) + 99) // 100 - 1)] / 1e6,
                max_ms=ordered[-1] / 1e6)


class Capture:
    def __init__(self, owner: Any, mode: str, label: str, updates: int) -> None:
        self.owner, self.mode, self.label, self.limit = owner, mode, label, updates
        self.thread = threading.get_ident()
        self.started_ns = perf_counter_ns()
        self.utc = datetime.now(timezone.utc).isoformat()
        self.costs: dict[str, Cost] = {}
        self.stack: list[list[Any]] = []
        self.patches: list[tuple[Any, str, Any, Any]] = []
        self.completed = 0
        self.stop_reason: str | None = None
        self.intervals: list[int] = []
        self.previous_gameplay_ns: int | None = None
        self.gameplay_times: list[int] = []
        self.states: dict[str, int] = {}
        self.sessions: set[int] = set()
        self.native_read_calls = 0
        self.native_read_bytes = 0
        self.restore_conflicts: list[str] = []
        self.save_error: str | None = None
        self.start_context: dict[str, Any] = {}

    def nested(self) -> bool:
        return bool(self.stack) and threading.get_ident() == self.thread

    def measure(self, label: str, callback: Callable, *args: Any, **kwargs: Any) -> Any:
        started = perf_counter_ns()
        scope = [label, started, 0]
        self.stack.append(scope)
        failed = True
        try:
            result = callback(*args, **kwargs)
            failed = False
            return result
        finally:
            elapsed = perf_counter_ns() - started
            self.stack.pop()
            self.costs.setdefault(label, Cost()).add(elapsed, scope[2], failed)
            if self.stack:
                self.stack[-1][2] += elapsed
            if label == "callback.gameplay":
                if self.previous_gameplay_ns is not None:
                    self.intervals.append(started - self.previous_gameplay_ns)
                self.previous_gameplay_ns = started
                self.gameplay_times.append(elapsed)
                self.completed += 1
                session = args[0]
                self.sessions.add(int(session.report.get("lifecycle_session_sequence", 0)))
                rows = session.report.get("samples", [])
                sample = rows[-1] if rows else {}
                phase = ("special" if not sample.get("normal_tps_sample", False)
                         else "moving" if sample.get("movement_input_active", False)
                         or float(sample.get("horizontal_speed", 0)) > 30 else "idle")
                self.states[phase] = self.states.get(phase, 0) + 1
                if self.completed >= self.limit:
                    self.stop_reason = self.stop_reason or "UPDATE_LIMIT"
            if not self.stack and self.stop_reason is not None:
                self.finish()

    def patch(self, obj: Any, name: str, label: str, *, native_read: bool = False) -> None:
        original = getattr(obj, name)

        @wraps(original)
        def measured(*args: Any, **kwargs: Any) -> Any:
            if _active is not self or not self.nested():
                return original(*args, **kwargs)
            if native_read:
                self.native_read_calls += 1
                self.native_read_bytes += int(args[1] if len(args) > 1 else kwargs["size"])
            return self.measure(label, original, *args, **kwargs)

        self.patches.append((obj, name, original, measured))
        setattr(obj, name, measured)

    def install_detail(self) -> None:
        from .sampling import SamplingMixin
        from .animation import AnimationMixin
        from .diagnostics import DiagnosticsMixin
        from .ground import GroundMixin
        from .air import AirMixin
        from .slide import SlideMixin
        from .session import GameplaySession
        from .inputs import NativeBindings
        from .native_rotation import NativeTrace, NativeSlideCrouchAimYaw
        from .native_idle_scope import IdleScopeMixin
        from .native_movement import DashReturnTrace

        plans = (
            (SamplingMixin, "bound", "runtime.bound"),
            (SamplingMixin, "_sample_frame", "sampling.state"),
            (SamplingMixin, "_body_frame", "rotation.body"),
            (AnimationMixin, "read_combat", "combat.state"),
            (AnimationMixin, "_combat_frame", "animation.combat_and_guards"),
            (DiagnosticsMixin, "visual", "sampling.visual"),
            (AnimationMixin, "validate_visual", "visual.guard"),
            (DiagnosticsMixin, "observe_ground_input_pose", "diagnostics.ground_pose"),
            (GameplaySession, "_special_frame", "pipeline.special"),
            (GroundMixin, "_ground_vector_frame", "pipeline.ground_vector"),
            (GroundMixin, "_native_entry_frame", "pipeline.native_entry"),
            (GroundMixin, "_ground_action_frame", "pipeline.ground_action"),
            (GroundMixin, "_dash_vector_frame", "pipeline.dash"),
            (AirMixin, "_air_frame", "pipeline.air"),
            (SlideMixin, "_slide_live_frame", "pipeline.slide"),
            (NativeBindings, "snapshot", "input.snapshot"),
            (NativeBindings, "maybe_refresh", "input.refresh_check"),
            (NativeBindings, "refresh", "input.full_refresh"),
            (NativeTrace, "validate", "native.rotation_guard"),
            (NativeTrace, "consume", "native.rotation_records"),
            (NativeTrace, "consume_slide", "native.slide_records"),
            (NativeSlideCrouchAimYaw, "validate", "native.aim_guard"),
            (IdleScopeMixin, "validate", "native.idle_scope_guard"),
            (DashReturnTrace, "validate", "native.entry_guard"),
            (DashReturnTrace, "consume", "native.entry_records"),
        )
        for cls, name, label in plans:
            if name not in vars(cls):
                raise RuntimeError(f"Profiler method ownership changed: {cls.__name__}.{name}")
            self.patch(cls, name, label)
        self.patch(self.owner, "_native_read", "native.process_read", native_read=True)
        self.patch(self.owner, "_get_runtime", "runtime.get")

    def restore(self) -> None:
        for obj, name, original, measured in reversed(self.patches):
            if getattr(obj, name) is measured:
                setattr(obj, name, original)
            else:
                self.restore_conflicts.append(name)
        self.patches.clear()

    def finish(self) -> None:
        global _active, _last
        if self.stack:
            return
        ended_ns = perf_counter_ns()
        _active = None
        self.restore()
        measured = sum(self.costs.get(name, Cost()).inclusive_ns for name in ROOTS)
        report = dict(
            version=self.owner.MOD_VERSION, utc=self.utc, mode=self.mode, label=self.label,
            stop_reason=self.stop_reason, completed_updates=self.completed, target_updates=self.limit,
            start_context=self.start_context,
            partial=self.completed < self.limit, elapsed_ms=(ended_ns - self.started_ns) / 1e6,
            states=self.states, lifecycle_sessions=sorted(self.sessions),
            callback_ms_per_gameplay_update=measured / max(1, self.completed) / 1e6,
            gameplay_callback=distribution(self.gameplay_times),
            update_intervals=distribution(self.intervals),
            stages={name: cost.export(self.completed) for name, cost in sorted(self.costs.items())},
            native_reads=(dict(calls=self.native_read_calls, bytes=self.native_read_bytes)
                          if self.mode == "detail" else None),
            restored=not self.restore_conflicts, restore_conflicts=self.restore_conflicts,
            native_patches_added=0, sdk_hooks_added=0, game_writes_added=0,
            scope="Wall time of Omni lifecycle/vehicle/gameplay callbacks and synchronous callees",
            limits=["Includes profiler overhead; compare total/detail/total in the same scene",
                    "Update intervals are widget/gameplay callback intervals, not rendered or FrameGen FPS",
                    "Native detours outside these callbacks, GPU and shared producer/filter overhead are not timed",
                    "Nested inclusive times overlap; rank exclusive_ms_per_update to avoid double counting",
                    "Labels are manual; states summarize existing samples, which can be stale after early returns"],
        )
        _last = report
        filename = "omni_performance_" + self.label + "_" + self.mode + "_" + datetime.now(
            timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".json"
        path = Path(self.owner.SETTINGS_DIR) / REPORT_DIRECTORY_NAME / filename
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            self.save_error = f"{type(exc).__name__}: {exc}"
            report["save_error"] = self.save_error
            self.owner.logging.error(TAG + "SAVE_FAILED " + self.save_error)
            return
        report["path"] = str(path)
        self.owner.logging.info(TAG + f"COMPLETE label={self.label} mode={self.mode} "
                                f"updates={self.completed} callback_ms_per_update="
                                f"{report['callback_ms_per_gameplay_update']:.3f} json={path}")


def root_span(label: str) -> Callable:
    """Only three permanent, inactive-fast-path wrappers; detail is opt-in."""
    def decorate(original: Callable) -> Callable:
        @wraps(original)
        def measured(instance: Any, *args: Any, **kwargs: Any) -> Any:
            capture = _active
            if (capture is None or getattr(instance, "mod", None) is not capture.owner
                    or not getattr(instance, "active", False)
                    or threading.get_ident() != capture.thread):
                return original(instance, *args, **kwargs)
            return capture.measure(label, original, instance, *args, **kwargs)
        return measured
    return decorate


def arm(owner: Any, mode: str, label: str = "idle", updates: int = 600) -> None:
    global _armed
    if mode not in ("total", "detail"):
        raise ValueError("Use total or detail")
    if not label or len(label) > 32 or not all(c.isascii() and (c.isalnum() or c == "_") for c in label):
        raise ValueError("Label must contain 1-32 ASCII letters, digits or underscores")
    if not 60 <= updates <= 6000:
        raise ValueError("Update count must be 60-6000")
    if _active is not None:
        raise RuntimeError("Capture running; F10 stops it or use profile stop")
    state = getattr(owner, KEY, None)
    if state is None or not state.active or state.child is None or not state.child.active:
        raise RuntimeError("Enable Omni and wait for its on-foot gameplay session")
    _armed = dict(owner=owner, mode=mode, label=label, updates=updates)
    owner.logging.info(TAG + f"ARMED mode={mode} label={label} updates={updates}; close console, press F10")


def trigger(owner: Any) -> bool:
    """Consume F10 only when explicitly armed or running for this owner."""
    global _armed, _active
    if _active is not None and _active.owner is owner:
        cancel(owner, "F10_MANUAL_STOP")
        return True
    if _armed is None or _armed["owner"] is not owner:
        return False
    state = getattr(owner, KEY, None)
    try:
        if state is None or not state.active or state.child is None or not state.child.active:
            raise RuntimeError("Omni gameplay session unavailable")
        if not state.updates.is_game_thread():
            raise RuntimeError("F10 must run on the owned game thread")
        pc, pawn, camera, movement = state.child.bound()
        if pc.bShowMouseCursor or str(camera.GetActorCameraMode(pawn)) != "ThirdPerson":
            raise RuntimeError("Start in on-foot TPS with menus closed")
        capture = Capture(owner, _armed["mode"], _armed["label"], _armed["updates"])
        capture.start_context = dict(
            diagnostics=bool(state.diagnostics), session_sequence=int(state.sequence),
            gameplay_update_index=int(state.child.frames),
            native_patches=int(state.child.report.get("native_patches", 0)),
            ready_flags={name: bool(getattr(state.child, name, False)) for name in (
                "ready", "player_ready", "blend_layout_ready", "sprint_ready", "route_ready",
                "vector_ready", "entry_ready")},
        )
        try:
            if capture.mode == "detail":
                capture.install_detail()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            capture.restore()
            raise
        _active = capture
        _armed = None
        owner.logging.info(TAG + f"STARTED mode={capture.mode} label={capture.label}; automatic completion")
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        owner.logging.error(TAG + "START_REFUSED " + str(exc))
    return True


def cancel(owner: Any, reason: str = "MANUAL_STOP") -> None:
    global _armed
    if _armed is not None and _armed["owner"] is owner:
        _armed = None
    if _active is not None and _active.owner is owner:
        _active.stop_reason = reason
        if not _active.stack:
            _active.finish()


def status(owner: Any) -> dict[str, Any]:
    if _active is not None and _active.owner is owner:
        return dict(state="running", mode=_active.mode, label=_active.label,
                    completed_updates=_active.completed, target_updates=_active.limit)
    if _armed is not None and _armed["owner"] is owner:
        return dict(state="armed", mode=_armed["mode"], label=_armed["label"], target_updates=_armed["updates"])
    return dict(state="off", last=None if _last is None else {
        name: _last.get(name) for name in ("path", "mode", "label", "completed_updates", "save_error")})
