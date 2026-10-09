"""Existing ordnance montage tracker; carried objects use carry_throw_handoff.

Omni turns the body to the camera only for combat signals (ADS, Fire, Zoom,
firing animation). Ordnance is started by its key (``Action_Gadget``),
and its animation can run on after the key is released. Without a combat
signal the body kept facing the movement direction while throwing.

An episode starts on the rising throw intent and holds combat while the intent
is held and while the montage that started with it plays on the bound
3rd-person anim instance (plus one montage that starts as it ends). A montage
counts as the throw's when it appears after the press or is at its start
(position <= FRESH_MONTAGE_SECONDS) on the press sample. State based, no
timers: the episode ends when that montage stops, or, when no new montage
appears, one quiet sample after the intent is released.
"""
from __future__ import annotations

from time import monotonic
from typing import Any, Callable, Optional

from unrealsdk.unreal import WeakPointer

MAX_EPISODES = 32
# Samples without intent and without a new montage before an episode that never
# started an animation ends: the release sample plus one grace sample.
NO_MONTAGE_SAMPLES = 2
# A throw may chain montages (wind-up, release). Follow one successor that has
# just started when the tracked one ends; unrelated later montages end the hold.
MAX_CHAINED_MONTAGES = 1
# Montage position (seconds) up to which a playing montage counts as started by
# this press. The press handler can start the montage before omni samples the
# frame, so the montage is already playing on the rising edge.
FRESH_MONTAGE_SECONDS = 0.15


def montage_name(montage: Any) -> str:
    try:
        return str(montage.Name)
    except (AttributeError, RuntimeError):
        return '<unknown>'


class ThrowHandoff:
    """Throw episode tracker; ``observe`` returns True while combat must hold."""

    def __init__(self) -> None:
        self.phase: Optional[str] = None  # 'WAIT_MONTAGE' | 'MONTAGE'
        self.previous_intent = False
        self.baseline_ref: Optional[WeakPointer] = None
        self.montage_ref: Optional[WeakPointer] = None
        self.quiet_samples = 0
        self.episode: Optional[dict] = None
        self.episodes: list[dict] = []
        self.started = 0
        self.last_event: Optional[str] = None

    def end(self, reason: str, now: float) -> None:
        if self.episode is not None:
            self.episode.update(end_reason=reason, duration=round(now - self.episode['t0'], 4))
            self.episodes.append(self.episode)
            del self.episodes[:-MAX_EPISODES]
        self.episode = None
        self.phase = None
        self.baseline_ref = None
        self.montage_ref = None
        self.quiet_samples = 0

    def track(self, montage: Any) -> None:
        self.phase = 'MONTAGE'
        self.montage_ref = WeakPointer(montage)
        self.episode['montage'] = montage_name(montage)
        self.last_event = 'MONTAGE'

    def needs_montage(self, intent: bool) -> bool:
        """Read the anim instance only while an episode can start or runs."""
        return self.phase is not None or bool(intent)

    def observe(self, *, intent: bool, source: str, eligible: bool, current: Any,
                is_playing: Callable[[Any], bool], is_fresh: Callable[[Any], bool] = lambda m: False,
                now: Optional[float] = None) -> bool:
        """``current`` is GetCurrentActiveMontage() of the bound anim instance;
        ``is_fresh(m)`` tells whether montage ``m`` is at its start."""
        now = monotonic() if now is None else now  # Diagnostics only.
        self.last_event = None
        intent = bool(intent)
        rising = intent and not self.previous_intent
        self.previous_intent = intent
        if self.phase is not None and not eligible:
            self.end('INELIGIBLE', now)
        if self.phase is None:
            if not (rising and eligible):
                return False
            self.started += 1
            self.episode = dict(t0=now, source=source, montage=None, chained=[], updates=0)
            if current is not None and is_fresh(current):
                self.track(current)
                return True
            self.phase = 'WAIT_MONTAGE'
            self.baseline_ref = WeakPointer(current) if current is not None else None
            self.last_event = 'STARTED'
            return True
        self.episode['updates'] += 1
        if self.phase == 'WAIT_MONTAGE':
            baseline = self.baseline_ref() if self.baseline_ref is not None else None
            if current is not None and (current != baseline or is_fresh(current)):
                self.track(current)
                return True
            if intent:
                self.quiet_samples = 0
                return True
            self.quiet_samples += 1
            if self.quiet_samples >= NO_MONTAGE_SAMPLES:
                self.end('NO_MONTAGE', now)
                self.last_event = 'NO_MONTAGE'
                return False
            return True
        montage = self.montage_ref() if self.montage_ref is not None else None
        if montage is not None and is_playing(montage):
            return True
        if (current is not None and current != montage and is_fresh(current)
                and len(self.episode['chained']) < MAX_CHAINED_MONTAGES):
            self.montage_ref = WeakPointer(current)
            self.episode['chained'].append(montage_name(current))
            return True
        if intent:
            # Key still held after the animation (e.g. holding to aim): keep
            # combat for the intent, the montage part of the episode is over.
            return True
        self.end('MONTAGE_ENDED', now)
        self.last_event = 'MONTAGE_ENDED'
        return False
