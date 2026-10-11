"""Bounded hitch log for Omni's own game-thread callbacks.

Each Omni root callback (lifecycle PRE, gameplay POST, vehicle POST) is timed
with two perf_counter_ns reads. A callback at or above THRESHOLD_MS is recorded
with its slowest named steps and, up to MAX_CONSOLE lines per game session,
printed to the console. Named steps sit only around one-off work (bind steps,
native install/restore, mapping scans, clip swaps, vehicle transitions).

No timers, hooks, UObject storage or game writes. Times are wall time of the
Python callback including synchronous SDK/native calls; work outside Omni's
callbacks (game streaming, shader compilation, the loader's camera code) is
not visible here. No hitch line during a stutter means Omni did not cause it.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from functools import wraps
from time import monotonic, perf_counter_ns
from typing import Any, Callable
import threading

from unrealsdk import logging as _sdk_logging

TAG = '[OmniHitch]'
THRESHOLD_MS = 4.0
MAX_CONSOLE = 32
MAX_STEPS = 6
RECENT = deque(maxlen=64)
_state: dict[str, Any] = dict(current=None, printed=0, total=0, worst_ms=0.0)


def root(label: str) -> Callable:
    """Time one Omni root callback; nested roots run untimed."""
    def decorate(original: Callable) -> Callable:
        @wraps(original)
        def timed(*args: Any, **kwargs: Any) -> Any:
            if _state['current'] is not None:
                return original(*args, **kwargs)
            record = dict(label=label, thread=threading.get_ident(), steps=[])
            _state['current'] = record
            started = perf_counter_ns()
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = perf_counter_ns() - started
                _state['current'] = None
                if elapsed >= THRESHOLD_MS * 1e6:
                    _record(label, elapsed, record['steps'])
        return timed
    return decorate


@contextmanager
def step(label: str):
    """Name one-off work inside the running root callback; free outside one."""
    record = _state['current']
    if record is None or record['thread'] != threading.get_ident():
        yield
        return
    started = perf_counter_ns()
    try:
        yield
    finally:
        record['steps'].append((label, perf_counter_ns() - started))


def _record(label: str, elapsed: int, steps: list) -> None:
    ms = elapsed / 1e6
    ordered = sorted(steps, key=lambda row: -row[1])[:MAX_STEPS]
    named = [(name, round(ns / 1e6, 2)) for name, ns in ordered]
    RECENT.append(dict(t=round(monotonic(), 3), callback=label, ms=round(ms, 2), steps=named))
    _state['total'] += 1
    _state['worst_ms'] = max(_state['worst_ms'], ms)
    if _state['printed'] >= MAX_CONSOLE:
        return
    _state['printed'] += 1
    detail = ', '.join(name + ' ' + format(value, '.1f') for name, value in named) or 'no named step'
    try:
        _sdk_logging.warning(TAG + ' ' + label + ' ' + format(ms, '.1f') + ' ms: ' + detail)
    except Exception:
        pass


def snapshot() -> dict[str, Any]:
    """Primitive copy for reports."""
    return dict(threshold_ms=THRESHOLD_MS, total=_state['total'], worst_ms=round(_state['worst_ms'], 2),
                console_lines=_state['printed'], recent=list(RECENT))
