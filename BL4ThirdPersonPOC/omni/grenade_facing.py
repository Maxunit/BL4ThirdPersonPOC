"""Measured grenade-facing recovery; exact local SDK event and session cleanup.

The shared one-hand lock is only a visual handback candidate. It can hold
facing after a measured ThrowGadget only while the same owned offhand script
remains. No elapsed-time admission, release grace or new physical bindings.
"""
from time import monotonic
import unrealsdk
from unrealsdk import hooks, find_object
from unrealsdk.unreal import WeakPointer
from .common import log as logging, TAG
from . import hitch

THROW_FUNCTION = '/Script/OakGame.OakCharacter:ThrowGadget'
SCRIPT_CLASS = '/Game/PlayerCharacters/_Shared/Tricks/Skills/Script_LTrick_HandleOffhand.Script_LTrick_HandleOffhand_C'
READ_ERRORS = (AttributeError, RuntimeError, TypeError, ValueError, OSError)


def describe(obj):
    return None if obj is None else str(obj._path_name())


def append_bounded(rows, row, limit):
    rows.append(row)
    del rows[:-limit]


class GrenadeHandoff:
    """Intent begins facing; a new owned offhand script admits the native hold.

    After local ThrowGadget, an observed one-hand action lock can continue the
    hold only while this same owned offhand source remains present. This lock
    is not specific to grenades; this is a bounded source-based visual QA.
    No elapsed time, sample grace or animation freshness test.
    """
    def __init__(self, baseline=()):
        self.previous_intent = False
        self.baseline = [WeakPointer(obj) for obj in baseline]
        self.source = None
        self.phase = None
        self.episode = None
        self.episodes = []
        self.admitted = 0

    def end(self, reason, now):
        if self.episode is not None:
            self.episode.update(end_reason=reason, duration_seconds=now - self.episode['t0'])
            append_bounded(self.episodes, self.episode, 32)
        self.episode = self.source = self.phase = None

    def observe(self, *, intent, eligible, scripts, now, locked=False, interrupted=False):
        intent = bool(intent)
        rising = intent and not self.previous_intent
        self.previous_intent = intent
        previous = [ref() for ref in self.baseline]
        self.baseline = [WeakPointer(obj) for obj in scripts]
        if not eligible:
            self.end('INELIGIBLE', now)
            return False
        if self.phase == 'RECOVERY' and (rising or interrupted):
            self.end('NEW_ACTION', now)
        if self.phase is None and rising:
            self.phase = 'INTENT'
            self.episode = dict(t0=now, source=None, admitted=False)
        if self.phase == 'INTENT':
            fresh = [obj for obj in scripts if obj not in previous]
            if len(fresh) == 1:
                self.source = WeakPointer(fresh[0])
                self.phase = 'NATIVE_THROW'
                self.episode.update(source=describe(fresh[0]), admitted=True)
                self.admitted += 1
            elif not intent:
                self.end('RELEASED_WITHOUT_ADMISSION', now)
        if self.phase in ('NATIVE_THROW', 'RECOVERY'):
            source = self.source()
            if source is None or source not in scripts:
                self.end('SOURCE_ENDED' if self.phase == 'RECOVERY' else 'SOURCE_ENDED_WITHOUT_THROW', now)
            elif self.phase == 'RECOVERY' and not locked:
                self.end('RECOVERY_UNLOCKED', now)
        return intent or self.phase in ('NATIVE_THROW', 'RECOVERY')

    def thrown(self, scripts, now, locked=False):
        if self.phase != 'NATIVE_THROW' or self.source() not in scripts:
            return False
        self.episode['native_throw_t'] = now
        if locked:
            self.phase = 'RECOVERY'
        else:
            self.end('NATIVE_THROW_NO_RECOVERY_LOCK', now)
        return True


class GrenadeFacing:
    """One session-owned SDK subscription; optional reads affect this feature only."""
    def __init__(self, session):
        self.session = session
        self.producer = None
        self.registered = self.supported = False
        self.model = GrenadeHandoff()
        self.legacy_transfers = 0
        self.spec = (THROW_FUNCTION, hooks.Type.POST_UNCONDITIONAL,
                     'bl4tps.omni.grenade_facing.throw')
        session.report.update(grenade_facing_episodes=self.model.episodes,
                              grenade_facing_read_failures={}, grenade_facing_sdk_hook=False,
                              grenade_facing_note='Measured offhand/native throw; shared one-hand '
                              'lock handback is visually confirmed for tested grenades only.')

    def failure(self, where, exc):
        failures = self.session.report['grenade_facing_read_failures']
        reason = where + ': ' + type(exc).__name__ + ': ' + str(exc)[:160]
        if reason not in failures and len(failures) >= 16:
            reason = 'OTHER'
        failures[reason] = failures.get(reason, 0) + 1
        if failures[reason] == 1:
            logging.warning(TAG + ' GRENADE_FACING_UNAVAILABLE ' + reason)

    def now(self):
        return monotonic() - self.session.started

    def script_class(self):
        """Measured offhand script class as weak identity; None keeps path checks."""
        cached = getattr(self, 'script_class_ref', None)
        if cached is not None:
            live = cached[0]()
            if live is not None and int(live._get_address()) == cached[1]:
                return live
            self.script_class_ref = None
        if getattr(self, 'script_class_lookups', 0) >= 1 and cached is None:
            return None
        self.script_class_lookups = getattr(self, 'script_class_lookups', 0) + 1
        try:
            cls = unrealsdk.find_class(SCRIPT_CLASS)
        except READ_ERRORS:
            return None
        if cls is None or str(cls._path_name()) != SCRIPT_CLASS:
            return None
        self.script_class_ref = (WeakPointer(cls), int(cls._get_address()))
        return cls

    def scripts(self, pawn):
        rows = pawn.TrickData.InstancedScripts
        if not 0 <= len(rows) <= 32:
            raise RuntimeError('Offhand script list outside diagnostic bound')
        # Class identity instead of a path string per script and update; the
        # path check remains when the class cannot be resolved.
        cls = self.script_class()
        if cls is not None:
            return [obj for obj in rows if obj is not None and obj.Class == cls and obj.MyActor == pawn]
        found = [obj for obj in rows if obj is not None
                 and str(obj.Class._path_name()) == SCRIPT_CLASS and obj.MyActor == pawn]
        if found:
            # First live instance proves the class; later updates compare identity.
            cls = found[0].Class
            self.script_class_ref = (WeakPointer(cls), int(cls._get_address()))
        return found

    def install(self):
        with hitch.step('install.grenade'):
            return self._install()

    def _install(self):
        try:
            function = find_object('Function', THROW_FUNCTION)
            if function is None or tuple(function._properties()):
                raise RuntimeError('Measured ThrowGadget signature differs')
            self.producer = getattr(self.session.updates, '_owner', None)
            if self.producer is None or not self.producer.active:
                raise RuntimeError('Existing gameplay update producer required')
            pawn = self.session.bound()[1]
            baseline = self.scripts(pawn)
            bool(pawn.OneHandWeaponActionLock.bLocked)
        except READ_ERRORS as exc:
            self.failure('install', exc)
            return
        if hooks.has_hook(*self.spec):
            self.failure('install', RuntimeError('Hook identifier occupied; no replacement'))
            return
        self.model.baseline = [WeakPointer(obj) for obj in baseline]
        self.registered = True  # reserve cleanup ownership before SDK registration
        try:
            hooks.add_hook(*self.spec, self.on_throw)
            if not hooks.has_hook(*self.spec):
                raise RuntimeError('Grenade hook registration unverified')
        except Exception as exc:
            self.close()  # removal failure must remain retryable through session.finish
            self.failure('registration', exc)
            return
        self.supported = True
        self.session.report['grenade_facing_sdk_hook'] = True
        self.session.report['sdk_hooks_peak'] = max(2, self.session.report.get('sdk_hooks_peak', 0))

    def cancel(self, reason):
        self.model.end(reason, self.now())

    def observe(self, pawn, snapshot, eligible):
        if not self.supported:
            return False, False
        owned = self.model.phase in ('NATIVE_THROW', 'RECOVERY')
        try:
            hold = self.model.observe(intent=bool(snapshot.get('gadget', False)),
                eligible=eligible, scripts=self.scripts(pawn), now=self.now(),
                locked=bool(pawn.OneHandWeaponActionLock.bLocked),
                interrupted=any(bool(snapshot.get(k, False)) for k in ('fire', 'zoom', 'carry_throw')))
        except READ_ERRORS as exc:
            self.failure('state', exc)
            self.cancel('STATE_UNAVAILABLE')
            return owned, False
        owned = owned or self.model.phase in ('NATIVE_THROW', 'RECOVERY')
        self.session.report['grenade_facing_episode_count'] = self.model.admitted
        return owned, hold

    def on_throw(self, obj, args, ret, func):
        s = self.session
        if (not self.supported or not s.active or not s.updates.is_game_thread()
                or getattr(s.updates, '_owner', None) is not self.producer
                or not self.producer.active):
            return None
        try:
            pc, pawn, camera, movement = s.bound()
            if obj != pawn or s.mod._get_runtime() != (pc, pawn, camera):
                return None
            if self.model.thrown(self.scripts(pawn), self.now(),
                                 locked=bool(pawn.OneHandWeaponActionLock.bLocked)):
                s.report['grenade_facing_native_throws'] = s.report.get('grenade_facing_native_throws', 0) + 1
        except READ_ERRORS as exc:
            self.failure('native_throw', exc)
            self.cancel('STATE_UNAVAILABLE')
        return None  # POST observer never blocks or changes native admission

    def close(self):
        self.supported = False
        self.cancel('SESSION_CLOSED')
        if self.registered:
            if hooks.has_hook(*self.spec):
                hooks.remove_hook(*self.spec)
            if hooks.has_hook(*self.spec):
                raise RuntimeError('Grenade hook removal unverified; cleanup must retry')
            self.registered = False
        self.session.report['grenade_facing_sdk_hook'] = False
