"""Camera facing for the measured Carry_Throw input context.

The .15 observer measured a configured Action_Carry_Throw press, then
bIsCarrying=False while Carry_Throw stayed mapped until native context removal.
No active UAnimMontage was reported. This tracker uses those observations;
context removal is an input handback, not proof of all animation work ending.
"""
from time import monotonic

MAX_EPISODES = 32


class CarryThrowHandoff:
    def __init__(self):
        self.previous_intent = False
        self.previous_carrying = None
        self.phase = None
        self.episode = None
        self.episodes = []
        self.started = 0

    def end(self, reason, now):
        if self.episode is not None:
            self.episode.update(end_reason=reason, duration=round(now - self.episode['t0'], 4))
            self.episodes.append(self.episode)
            del self.episodes[:-MAX_EPISODES]
        self.episode = self.phase = None

    def observe(self, *, intent, context, carrying, eligible, now=None):
        now = monotonic() if now is None else now  # Report timing only.
        intent = bool(intent)
        rising = intent and not self.previous_intent
        previous_carrying = self.previous_carrying
        self.previous_intent = intent
        self.previous_carrying = carrying
        if self.phase is not None:
            reason = ('INELIGIBLE' if not eligible else
                      'CARRY_CONTEXT_ENDED' if not context else
                      'NEW_CARRIED_OBJECT' if self.phase == 'OBJECT_RELEASED' and carrying is True else None)
            if reason is not None:
                self.end(reason, now)
                return False
        if self.phase is None:
            if not (rising and eligible and context):
                return False
            self.started += 1
            self.episode = dict(t0=now, source='carry_throw',
                                carrying_before=previous_carrying,
                                object_release_observed=False,
                                gate='native_carry_input_context', timer_based_release=False)
            self.phase = 'HELD_INTENT'
        if carrying is None:
            # Without a current state read, only the configured held intent
            # can justify facing. Never retain an unbounded context latch.
            self.phase = 'HELD_INTENT'
        if carrying is False and (previous_carrying is True or self.phase == 'OBJECT_RELEASED'):
            self.phase = 'OBJECT_RELEASED'
            self.episode['object_release_observed'] = True
        if self.phase == 'OBJECT_RELEASED':
            return True  # The native Carry_Throw input context still owns handback.
        if intent:
            return True  # Intent only; no assertion that a throw was admitted.
        self.end('CARRY_STATE_UNAVAILABLE' if carrying is None else 'RELEASED_WITHOUT_OBJECT_RELEASE', now)
        return False
