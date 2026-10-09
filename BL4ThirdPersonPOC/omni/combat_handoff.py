"""Bridge Sprint exit using native pending requests and use activity.

No elapsed-time decisions. The game owns PostSprintUseDelay; we observe its
request closing and the reviewed primary/optional charge activity getters.

0.3.9.12: a press the game never turns into a request (e.g. a gamepad trigger
pulled below the game's actuation point, or Fire consumed by another input
context) produces neither a pending request nor activity. Without an exit the
handoff held combat aim, which pauses omni's Sprint overrides, so a sideways
Sprint could never resume (the 0.3.9.4 lock). Every recorded valid request is
visible in the update that arms the handoff; after the input is released, one
further quiet sample is the grace before NO_NATIVE_REQUEST. Sample count, not
elapsed time.
"""
from time import monotonic
from unrealsdk.unreal import WeakPointer

MAX_EPISODES = 32
# Quiet samples (input released, no Sprint, no request, no use) before a press
# without any native request is released: the release sample plus one grace.
NO_REQUEST_SAMPLES = 2

class SprintFireHandoff:
    """State-based handoff for the reviewed primary and optional charge activity getters."""
    def __init__(self):
        self.weapon_ref = None
        self.phase = None
        self.previous_fire = False
        self.previous_sprint = False
        self.episode = None
        self.episodes = []
        self.not_admitted_releases = 0
        # Keep the baseline animation logger from describing a timed release.
        self.last_release = None
        self.pending_seen = False
        self.quiet_samples = 0
        self.no_request_releases = 0

    def end(self, reason, now):
        if self.episode is not None:
            self.episode.update(end_reason=reason, duration=round(now-self.episode['t0'],4))
            self.episodes.append(self.episode)
            del self.episodes[:-MAX_EPISODES]
        self.episode = None
        self.phase = None
        self.weapon_ref = None
        self.pending_seen = False
        self.quiet_samples = 0

    def observe(self, weapon, *, fire, firing, reloading, weapon_state,
                       sprinting, wants_sprint, eligible, pending, native_active, now=None):
        now = monotonic() if now is None else now  # Diagnostics only.
        self.last_release = None
        rising = bool(fire and not self.previous_fire)
        was_sprint = self.previous_sprint
        self.previous_fire = bool(fire)
        self.previous_sprint = bool(sprinting)
        same = self.weapon_ref is not None and self.weapon_ref() == weapon and weapon is not None
        if self.episode is not None:
            self.episode['updates'] += 1
        if self.phase is not None:
            reason = ('WEAPON_CHANGED' if not same else 'INELIGIBLE' if not eligible
                      else 'RELOADING' if reloading
                      else 'WEAPON_STATE' if weapon_state not in ('Active','Using')
                      else 'SPRINT_RESUMED' if not fire and sprinting else None)
            if reason:
                self.end(reason,now)
        if (self.phase is None and rising and eligible and not reloading and weapon is not None
                and (was_sprint or sprinting) and wants_sprint and weapon_state in ('Active','Using')):
            self.weapon_ref = WeakPointer(weapon)
            if self.weapon_ref() is not None:
                self.phase = 'WAIT_NATIVE_FIRE'
                self.pending_seen = bool(pending)
                self.quiet_samples = 0
                self.episode = dict(t0=now, updates=0, native_use_seen=False,
                                    pending_seen=bool(pending), timer_based_release=False)
        if self.phase is None:
            return False
        self.pending_seen = self.pending_seen or bool(pending)
        self.episode['pending_seen'] = self.pending_seen
        if native_active or firing or weapon_state == 'Using':
            self.phase = 'NATIVE_FIRE_SEEN'
            self.episode['native_use_seen'] = True
        elif (self.phase == 'NATIVE_FIRE_SEEN' and not pending and weapon_state == 'Active'):
            self.end('NATIVE_USE_COMPLETED',now)
        elif (self.phase == 'WAIT_NATIVE_FIRE' and self.pending_seen and not pending
              and not fire and not sprinting and weapon_state == 'Active'):
            self.not_admitted_releases += 1
            self.end('NATIVE_REQUEST_CLOSED_WITHOUT_USE',now)
            self.last_release = 'NATIVE_REQUEST_CLOSED_WITHOUT_USE'
        elif self.phase == 'WAIT_NATIVE_FIRE' and not self.pending_seen:
            if fire or sprinting:
                self.quiet_samples = 0
            else:
                self.quiet_samples += 1
                if self.quiet_samples >= NO_REQUEST_SAMPLES:
                    self.no_request_releases += 1
                    self.end('NO_NATIVE_REQUEST', now)
                    self.last_release = 'NO_NATIVE_REQUEST'
        return self.phase is not None
