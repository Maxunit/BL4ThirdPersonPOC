"""Native grenade handback: measured state replay, ownership and hook cleanup."""
import json
from pathlib import Path
from types import SimpleNamespace as S
import unittest
from unittest.mock import patch
import support
from BL4ThirdPersonPOC.omni import grenade_facing as gf
from BL4ThirdPersonPOC.omni.grenade_facing import GrenadeFacing, GrenadeHandoff as Tracker
import test_fixes_0_3_9_12 as old_tests


def script(name='1', pawn=None):
    return S(Class=S(_path_name=lambda: gf.SCRIPT_CLASS), MyActor=pawn,
             _path_name=lambda: '/Test/Offhand_' + name)


class StateTests(unittest.TestCase):
    def test_portable_three_live_wurf_replay(self):
        rows = json.loads((Path(__file__).parent/'fixtures/grenade_recovery_live_20261009.json').read_text())
        objects, model = {}, Tracker()
        for row in rows:
            sources = [objects.setdefault(n, script(n)) for n in row['sources']]
            model.observe(intent=row['intent'], eligible=row['eligible'], scripts=sources,
                          locked=row['locked'], now=row['t'])
            for now in row['throws']: self.assertTrue(model.thrown(sources, now, locked=row['locked']))
        self.assertEqual(model.admitted, 3)
        self.assertEqual(len(model.episodes), 3)
        for ep in model.episodes:
            self.assertEqual(ep['end_reason'], 'RECOVERY_UNLOCKED')
            self.assertGreater(ep['duration_seconds'], .93)
            self.assertLess(ep['duration_seconds'], .96)
            self.assertGreater(ep['t0'] + ep['duration_seconds'] - ep['native_throw_t'], .59)
            # Widget snapshots follow the state update; preserve sampling uncertainty.
            self.assertLess(ep['t0'] + ep['duration_seconds'] - ep['native_throw_t'], .64)
    def test_native_event_ends_admitted_hold_after_key_release(self):
        t, source = Tracker(), script()
        self.assertTrue(t.observe(intent=True, eligible=True, scripts=[source], now=0.))
        self.assertTrue(t.observe(intent=False, eligible=True, scripts=[source], now=.1))
        self.assertTrue(t.thrown([source], .35))
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=.36))
        self.assertEqual(t.episodes[-1]['end_reason'], 'NATIVE_THROW_NO_RECOVERY_LOCK')
    def test_existing_source_does_not_admit_new_press(self):
        source = script(); t = Tracker([source])
        self.assertTrue(t.observe(intent=True, eligible=True, scripts=[source], now=0.))
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=.1))
        self.assertEqual(t.episodes[-1]['end_reason'], 'RELEASED_WITHOUT_ADMISSION')
    def test_script_disappearance_cancels_without_native_event(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0.)
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[], now=.1))
        self.assertEqual(t.episodes[-1]['end_reason'], 'SOURCE_ENDED_WITHOUT_THROW')
    def test_hold_has_no_elapsed_time_or_frame_count_release(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0.)
        for i in range(100):
            self.assertTrue(t.observe(intent=False, eligible=True, scripts=[source], now=100000. + i))
        self.assertTrue(t.thrown([source], 100101.))
    def test_ineligible_cancels_without_rearming_held_input(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0.)
        self.assertFalse(t.observe(intent=True, eligible=False, scripts=[source], now=.1))
        self.assertTrue(t.observe(intent=True, eligible=True, scripts=[source], now=.2))
        self.assertIsNone(t.phase)  # intent only, old script is not re-admitted
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=.3))
    def test_new_source_after_press_is_admitted_without_sample_grace(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[], now=0.)
        self.assertTrue(t.observe(intent=False, eligible=True, scripts=[source], now=.1))
        self.assertTrue(t.thrown([source], .2))
    def test_unrelated_or_unbound_event_does_not_release(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0.)
        self.assertFalse(t.thrown([script('other')], .1))
        self.assertTrue(t.observe(intent=False, eligible=True, scripts=[source], now=.2))
    def test_recovery_waits_for_unlock_and_does_not_rearm_on_relock(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0., locked=True)
        self.assertTrue(t.thrown([source], .35, locked=True))
        self.assertEqual(t.phase, 'RECOVERY')
        self.assertTrue(t.observe(intent=False, eligible=True, scripts=[source], now=999999., locked=True))
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=1000000., locked=False))
        self.assertEqual(t.episodes[-1]['end_reason'], 'RECOVERY_UNLOCKED')
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=1000001., locked=True))
    def test_recovery_ends_on_source_loss_even_if_generic_lock_stays_true(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0., locked=True)
        t.thrown([source], .35, locked=True)
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[], now=.4, locked=True))
        self.assertEqual(t.episodes[-1]['end_reason'], 'SOURCE_ENDED')
    def test_new_action_interrupts_recovery(self):
        t, source = Tracker(), script()
        t.observe(intent=True, eligible=True, scripts=[source], now=0., locked=True)
        t.thrown([source], .35, locked=True)
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[source], now=.4,
                                   locked=True, interrupted=True))
        self.assertEqual(t.episodes[-1]['end_reason'], 'NEW_ACTION')
    def test_lock_without_admitted_throw_never_starts_recovery(self):
        t = Tracker()
        self.assertFalse(t.observe(intent=False, eligible=True, scripts=[], now=0., locked=True))
        self.assertFalse(t.thrown([], .3, locked=True))
        self.assertIsNone(t.phase)


class ControllerTests(old_tests.CombatHarness, unittest.TestCase):
    def setUp(self):
        self.build()
        self.keys.update(gadget=False, carry_throw=False)
        self.pawn.TrickData = S(InstancedScripts=[])
        self.pawn.OneHandWeaponActionLock = S(bLocked=True)
        self.obj.active = True
        self.obj.mod._get_runtime = lambda: (self.pc, self.pawn, self.camera)
        self.producer = S(active=True)
        self.obj.updates._owner = self.producer
        self.callbacks = {}
        def add(*args): self.callbacks[args[:3]] = args[3]
        def remove(*args): self.callbacks.pop(args, None)
        for name, fn in [('add_hook', add), ('remove_hook', remove),
                         ('has_hook', lambda *args: args in self.callbacks)]:
            p = patch.object(gf.hooks, name, fn, create=True); p.start(); self.addCleanup(p.stop)
        p = patch.object(gf, 'find_object', return_value=S(_properties=lambda: []))
        p.start(); self.addCleanup(p.stop)
        self.facing = self.obj.grenade_facing = GrenadeFacing(self.obj)
        self.addCleanup(self.facing.close)

    def arm(self):
        self.facing.install()
        self.assertTrue(self.facing.supported)

    def start_throw(self):
        self.keys['gadget'] = True
        self.source = script(pawn=self.pawn)
        self.pawn.TrickData.InstancedScripts.append(self.source)
        self.assertTrue(self.read()['throw_hold'])
        self.keys['gadget'] = False

    def test_actual_combat_skips_legacy_montage_and_holds_through_native_recovery(self):
        self.arm(); self.start_throw()
        for _ in range(5): self.assertTrue(self.read()['active'])
        self.assertNotIn('throw_montage_error', self.obj.report)
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.assertEqual(self.read()['grenade_facing_phase'], 'RECOVERY')
        for _ in range(5): self.assertTrue(self.read()['throw_hold'])
        self.pawn.OneHandWeaponActionLock.bLocked = False
        self.assertFalse(self.read()['active'])
        self.assertEqual(self.obj.report['throw_episode_count'], 1)
        self.assertEqual(self.facing.model.episodes[-1]['end_reason'], 'RECOVERY_UNLOCKED')

    def test_wrong_pawn_thread_producer_and_inactive_session_do_not_advance(self):
        self.arm(); self.start_throw()
        self.callbacks[self.facing.spec](S(), None, None, None)
        self.obj.updates.is_game_thread = lambda: False
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.obj.updates.is_game_thread = lambda: True
        self.obj.updates._owner = S(active=True)
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.obj.updates._owner = self.producer
        self.obj.active = False
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.assertEqual(self.facing.model.phase, 'NATIVE_THROW')

    def test_foreign_script_not_admitted_and_legacy_fallback_preserved(self):
        self.arm(); self.keys['gadget'] = True
        self.pawn.TrickData.InstancedScripts.append(script(pawn=S()))
        self.assertTrue(self.read()['active'])
        self.assertEqual(self.facing.model.admitted, 0)
        self.assertEqual(self.obj.throw_handoff.phase, 'WAIT_MONTAGE')

    def test_read_failure_releases_only_grenade_hold(self):
        self.arm(); self.start_throw()
        del self.pawn.TrickData
        self.assertFalse(self.read()['throw_hold'])
        self.assertTrue(self.obj.active)
        self.assertTrue(self.obj.report['grenade_facing_read_failures'])

    def test_signature_mismatch_is_optional_and_registers_nothing(self):
        with patch.object(gf, 'find_object', return_value=S(_properties=lambda: [S()])):
            self.facing.install()
        self.assertFalse(self.facing.supported)
        self.assertFalse(self.callbacks)
        self.assertTrue(self.obj.active)

    def test_partial_registration_rolls_back_without_disabling_omni(self):
        def add(*args):
            self.callbacks[args[:3]] = args[3]
            raise RuntimeError('after-add failure')
        with patch.object(gf.hooks, 'add_hook', add): self.facing.install()
        self.assertFalse(self.callbacks)
        self.assertFalse(self.facing.registered)
        self.assertTrue(self.obj.active)

    def test_remove_failure_retains_ownership_and_disables_callback_until_retry(self):
        self.arm(); self.start_throw()
        with patch.object(gf.hooks, 'remove_hook', lambda *args: None):
            with self.assertRaises(RuntimeError): self.facing.close()
        self.assertTrue(self.facing.registered)
        self.assertFalse(self.facing.supported)
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.assertNotIn('grenade_facing_native_throws', self.obj.report)
        self.facing.close()
        self.assertFalse(self.callbacks)

    def test_collision_does_not_remove_foreign_hook(self):
        foreign = object(); self.callbacks[self.facing.spec] = foreign
        self.facing.install()
        self.facing.close()
        self.assertIs(self.callbacks[self.facing.spec], foreign)
        self.callbacks.clear()

    def test_late_native_admission_transfers_one_legacy_episode(self):
        self.arm(); self.keys['gadget'] = True
        self.assertTrue(self.read()['throw_hold'])
        self.pawn.TrickData.InstancedScripts.append(script(pawn=self.pawn))
        self.assertTrue(self.read()['throw_hold'])
        self.assertEqual(self.obj.report['throw_episode_count'], 1)
        self.assertEqual(self.facing.legacy_transfers, 1)

    def test_special_pause_cancels_recovery_without_rearming_held_source(self):
        self.arm(); self.start_throw()
        self.callbacks[self.facing.spec](self.pawn, None, None, None)
        self.facing.cancel('SPECIAL_NATIVE_HANDOFF')
        self.assertFalse(self.read()['throw_hold'])
        self.assertEqual(self.facing.model.episodes[-1]['end_reason'], 'SPECIAL_NATIVE_HANDOFF')

    def test_carry_context_works_alongside_registered_grenade_hook(self):
        self.arm(); self.obj.inputs.present_roles = {'carry_throw'}
        self.keys['carry_throw'] = True; self.anim.bIsCarrying = True
        self.assertTrue(self.read()['carry_throw_hold'])
        self.assertEqual(self.facing.model.admitted, 0)

    def test_session_finish_closes_native_sdk_subscription(self):
        session, _ = support.session()
        facing = session.grenade_facing
        facing.registered = facing.supported = True
        self.callbacks[facing.spec] = facing.on_throw
        session.finish('UNIT_STOP')
        self.assertFalse(facing.registered)
        self.assertFalse(self.callbacks)
        self.assertEqual(session.report['sdk_hooks'], 0)

    def test_session_cleanup_failure_is_reported_and_retry_closes_hook(self):
        session, _ = support.session()
        facing = session.grenade_facing
        facing.registered = facing.supported = True
        self.callbacks[facing.spec] = facing.on_throw
        with patch.object(gf.hooks, 'remove_hook', lambda *args: None):
            with self.assertRaises(RuntimeError): session.finish('UNIT_STOP')
        self.assertFalse(session.active)
        self.assertFalse(facing.supported)
        self.assertFalse(session.report['cleanup_complete'])
        self.assertEqual(session.report['sdk_hooks'], 1)
        session.finish('UNIT_RETRY')
        self.assertFalse(self.callbacks)
        self.assertTrue(session.report['cleanup_complete'])
        self.assertEqual(session.report['sdk_hooks'], 0)
