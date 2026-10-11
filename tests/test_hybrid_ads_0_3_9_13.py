"""0.3.9.13 test build: Hybrid ADS Mode (omni) - hold aims over the shoulder,
Sprint while aiming toggles the native scope."""
import time
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import sys
import types

import support
from BL4ThirdPersonPOC import hybrid_ads

if not hasattr(sys.modules['unrealsdk'], 'find_all'):
    sys.modules['unrealsdk'].find_all = lambda *args: []
if 'unrealsdk.hooks' not in sys.modules:  # ads_events imports Block from it
    _hooks = types.ModuleType('unrealsdk.hooks')
    _hooks.Block = object()
    _hooks.Type = support.sdk.hooks.Type
    _hooks.add_hook = _hooks.remove_hook = lambda *args, **kwargs: None
    sys.modules['unrealsdk.hooks'] = _hooks


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Camera:
    def __init__(self, weapon):
        self.calls = []
        self.CameraModeState = S(bIsTransitioning=False, BaseFOVOffset=-12.0,
                                 CameraLocationOffset=S(X=20.0, Y=75.0, Z=10.0))
        self.CameraModeInputs = S(Weapon=weapon)
        self.mode = 'ThirdPerson'
        self.fail = None

    def SetActorCameraMode(self, pawn, mode, *args):
        if self.fail is not None:
            raise self.fail
        self.calls.append((mode, args[1]))
        self.mode = mode

    def GetActorCameraMode(self, pawn):
        return self.mode


def fake_mod(route='tps', scoped_weapon=0xAA):
    weapon = S(Name='Weapon')
    camera = Camera(weapon)
    pawn = S(Name='Pawn')
    log = []
    mod = S(omni_hybrid_ads=S(value=True), sniper_tps_ads=S(value=False),
            camera_offset_x=S(value=0.0), camera_offset_y=S(value=75.0), camera_offset_z=S(value=10.0),
            _third_person_enabled=True, _third_person_pushed=True, _vehicle_camera_active=False,
            _shop_camera_active=False, _ladder_active=False, _slide_active=False,
            _camera_lifecycle={}, _ads_active=True, _ads_route=route,
            _ads_handoff=dict(held=True, latch_active=False, reticle_rebind_active=False,
                              in_gap=False, route_weapon=scoped_weapon, route_pending=None),
            _ads_tps_state=dict(phase='ads', weapon_address=0xAA, category='sniper_rifle',
                                base_fov=90.0, target_fov=70.0, last_fov=70.0, transition=None,
                                mode_state=camera.CameraModeState, original_offset=0.0,
                                offset_overridden=True),
            _reticle_publish_pending=True, _ads_collector_address=0x55,
            _active_native_state={}, ADS_MIN_DURATION=0.05, ADS_CAMERA_TRANSITION_TIME=0.06,
            time=time, log=log)
    mod.logging = S(info=lambda m: log.append(('info', m)), error=lambda m: log.append(('error', m)))
    mod._get_runtime = lambda: (S(), pawn, camera)
    mod._ads_object_address = lambda obj: 0xAA if obj is weapon else 0xBB if obj is not None else 0
    mod.native_stops = []
    mod._native_active = lambda: True
    mod._native_stop = lambda reason: mod.native_stops.append(reason) or True
    mod._cleanup_ads_handoff = lambda reason: mod._ads_handoff.update(route_weapon=0, route_pending=None)
    mod._ads_zoom_fields = lambda pawn: 'zoom_state=2'
    mod.reticle_hides = []
    mod._hide_hybrid_tps_reticle = lambda identity: mod.reticle_hides.append(identity) or 'hidden'
    mod._classify_ads_weapon = lambda w: ('sniper_rifle', 'test', 'evidence')
    return mod, camera, weapon


class HybridBase(unittest.TestCase):
    def setUp(self):
        hybrid_ads.reset()
        self.running = patch('BL4ThirdPersonPOC.omni.is_running', return_value=True)
        self.running.start()
        self.bound = patch.object(hybrid_ads, 'gameplay_bound', return_value=True)
        self.bound.start()
        self.clock = Clock()
        self.monotonic = patch.object(hybrid_ads, 'monotonic', self.clock)
        self.monotonic.start()

    def tearDown(self):
        self.monotonic.stop()
        self.bound.stop()
        self.running.stop()
        hybrid_ads.reset()


class GateTests(HybridBase):
    def test_active_needs_option_and_running_omni(self):
        mod, _, _ = fake_mod()
        self.assertTrue(hybrid_ads.active(mod))
        self.assertTrue(hybrid_ads.sniper_uses_tps(mod))
        mod.omni_hybrid_ads.value = False
        self.assertFalse(hybrid_ads.active(mod))
        self.assertFalse(hybrid_ads.sniper_uses_tps(mod))
        mod.omni_hybrid_ads.value = True
        with patch('BL4ThirdPersonPOC.omni.is_running', return_value=False):
            self.assertFalse(hybrid_ads.active(mod))
        with patch.object(hybrid_ads, 'gameplay_bound', return_value=False):
            self.assertFalse(hybrid_ads.active(mod), 'no bound omni session reads Sprint')
        mod.sniper_tps_ads.value = True
        mod.omni_hybrid_ads.value = False
        self.assertTrue(hybrid_ads.sniper_uses_tps(mod))



class CameraPositionTests(HybridBase):
    def test_zoom_progress_does_not_change_user_camera_offsets(self):
        mod, _, _ = fake_mod()
        for fov in (90., 80., 70.):
            mod._ads_tps_state['last_fov'] = fov
            for offset in ((0., 75., 10.), (-80., 55., 20.), (120., 75., 10.), (0., 0., 0.)):
                self.assertEqual(hybrid_ads.compensate(mod, *offset), offset)

    def test_zoom_release_and_hybrid_off_keep_regular_offsets(self):
        mod, _, _ = fake_mod()
        for phase in ('ads', 'released'):
            mod._ads_tps_state.update(phase=phase, transition=None)
            self.assertEqual(hybrid_ads.compensate(mod, 20., 75., 10.), (20., 75., 10.))
        mod.omni_hybrid_ads.value = False
        self.assertEqual(hybrid_ads.compensate(mod, 20., 75., 10.), (20., 75., 10.))

    def test_obsolete_dolly_state_cannot_affect_camera_and_is_removed_on_reset(self):
        mod, _, _ = fake_mod()
        hybrid_ads._state['dolly'] = 100.
        self.assertEqual(hybrid_ads.compensate(mod, 20., 75., 10.), (20., 75., 10.))
        hybrid_ads.reset()
        self.assertNotIn('dolly', hybrid_ads.status(mod))
        self.assertNotIn('dolly', hybrid_ads._state)


class ScopeTests(HybridBase):
    def test_toggle_ads_can_switch_scope_after_physical_release(self):
        mod, camera, _ = fake_mod()
        mod._ads_handoff['held'] = False
        self.assertEqual(hybrid_ads.enter_scope(mod), 'scope_on')
        self.assertFalse(mod._ads_handoff['held'])
        self.assertEqual(hybrid_ads.exit_scope(mod), 'scope_off')
        self.assertFalse(mod._ads_handoff['held'])

    def test_sprint_in_held_tps_ads_enters_the_native_scope(self):
        mod, camera, _ = fake_mod()
        self.assertEqual(hybrid_ads.toggle_scope(mod), 'scope_on')
        self.assertEqual(camera.calls, [('Default', hybrid_ads.SCOPE_BLEND_SECONDS)])
        self.assertEqual((mod._ads_route, mod._ads_active, mod._ads_tps_state), ('sniper_fps', True, None))
        self.assertEqual(mod._ads_handoff['route_weapon'], 0xAA)
        self.assertTrue(mod._ads_handoff['held'])
        self.assertEqual(mod.native_stops, ['hybrid_scope_enter'])
        self.assertFalse(mod._reticle_publish_pending)
        self.assertTrue(hybrid_ads._state['scoped'])
        self.assertEqual(hybrid_ads._state['fade']['start'], (20.0, 75.0, 10.0))
        self.assertTrue(any('HYBRID_SCOPE_ON' in m and 'zoom_state=2' in m for _, m in mod.log))

    def test_non_sniper_uses_the_fallback_fps_route(self):
        mod, _, _ = fake_mod()
        mod._ads_tps_state['category'] = 'assault_rifle'
        hybrid_ads.toggle_scope(mod)
        self.assertEqual(mod._ads_route, 'fallback_fps')

    def test_refusals_leave_everything_untouched(self):
        cases = (
            ('not_holding_tps_ads', lambda m, c: setattr(m, '_ads_route', 'hip')),
            ('camera_transitioning', lambda m, c: setattr(c.CameraModeState, 'bIsTransitioning', True)),
            ('weapon_changed', lambda m, c: setattr(c.CameraModeInputs, 'Weapon', S(Name='Other'))),
            ('weapon_handoff', lambda m, c: m._ads_handoff.update(reticle_rebind_active=True)),
            ('slide_or_ladder', lambda m, c: setattr(m, '_slide_active', True)),
        )
        for reason, prepare in cases:
            with self.subTest(reason):
                hybrid_ads.reset()
                mod, camera, _ = fake_mod()
                prepare(mod, camera)
                self.assertEqual(hybrid_ads.toggle_scope(mod), 'refused:' + reason)
                self.assertEqual(camera.calls, [])
                self.assertFalse(hybrid_ads._state['scoped'])

    def test_second_sprint_returns_to_the_shoulder_aim(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        self.clock.now += 1.0
        camera.CameraModeState.CameraLocationOffset = S(X=0.0, Y=0.0, Z=0.0)  # first person
        self.assertEqual(hybrid_ads.toggle_scope(mod), 'scope_off')
        self.assertEqual(camera.calls[-1], ('ThirdPerson', hybrid_ads.SCOPE_BLEND_SECONDS))
        pending = mod._ads_handoff['route_pending']
        self.assertTrue(pending['hybrid_same_weapon'])
        self.assertEqual((pending['weapon_address'], pending['from_route']), (0xAA, 'sniper_fps'))
        self.assertFalse(hybrid_ads._state['scoped'])
        self.assertEqual(hybrid_ads._state['fade']['kind'], 'in')
        self.assertEqual(hybrid_ads._state['fade']['start'], (0.0, 0.0, 0.0))

    def test_exit_waits_for_a_pending_migration(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        mod._ads_handoff['route_pending'] = dict(weapon_address=0xBB)
        self.assertEqual(hybrid_ads.toggle_scope(mod), 'refused:migration_pending')
        self.assertEqual(len(camera.calls), 1)

    def test_release_while_scoped_blends_back(self):
        mod, _, _ = fake_mod()
        self.assertEqual(hybrid_ads.release_transition(mod, 0.06), 0.06)
        hybrid_ads.toggle_scope(mod)
        self.assertEqual(hybrid_ads.release_transition(mod, 0.06), hybrid_ads.SCOPE_BLEND_SECONDS)
        self.assertFalse(hybrid_ads._state['scoped'])
        self.assertEqual(hybrid_ads._state['scope_releases'], 1)

    def test_camera_errors_are_reported_not_raised(self):
        mod, camera, _ = fake_mod()
        camera.fail = RuntimeError('SetActorCameraMode failed')
        self.assertEqual(hybrid_ads.toggle_scope(mod), 'error')
        # The camera switch comes before any state change: nothing was committed.
        self.assertEqual((mod._ads_route, hybrid_ads._state['scoped']), ('tps', False))
        self.assertIsInstance(mod._ads_tps_state, dict)
        self.assertIsNone(hybrid_ads._state['fade'])
        self.assertIn('SetActorCameraMode failed', hybrid_ads._state['last_error'])
        self.assertTrue(any('HYBRID_SCOPE_FAILED' in m for level, m in mod.log if level == 'error'))

    def test_inactive_mode_never_switches(self):
        mod, camera, _ = fake_mod()
        mod.omni_hybrid_ads.value = False
        self.assertEqual(hybrid_ads.toggle_scope(mod), 'inactive')
        self.assertEqual(camera.calls, [])


class FadeTests(HybridBase):
    def test_scope_entry_fades_the_offset_out_along_the_blend(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (20.0, 75.0, 10.0))
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS / 2
        x, y, z = hybrid_ads.compensate(mod, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(y, 37.5)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        self.assertIsNone(hybrid_ads._state['fade'])
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_fov_offset_returns_to_native_during_the_blend(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        hybrid_ads.update(mod)
        self.assertAlmostEqual(camera.CameraModeState.BaseFOVOffset, -12.0)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS / 2
        hybrid_ads.update(mod)
        self.assertAlmostEqual(camera.CameraModeState.BaseFOVOffset, -6.0)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS
        hybrid_ads.update(mod)
        self.assertEqual(camera.CameraModeState.BaseFOVOffset, 0.0)
        self.assertIsNone(hybrid_ads._state['fov_fade'])

    def test_scope_exit_fades_in_and_holds_until_tps_takes_over(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        self.clock.now += 1.0
        camera.CameraModeState.CameraLocationOffset = S(X=0.0, Y=0.0, Z=0.0)
        hybrid_ads.toggle_scope(mod)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS / 2
        self.assertAlmostEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0)[1], 37.5)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS
        # Blend over but still on the FPS route: retain the regular TPS offset.
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 75.0, 10.0))
        self.assertIsNotNone(hybrid_ads._state['fade'])
        mod._ads_route = 'tps'
        mod._ads_tps_state = dict(phase='ads', base_fov=90.0, target_fov=70.0, last_fov=70.0,
                                  transition=None)
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 75.0, 10.0), (0.0, 75.0, 10.0))
        self.assertIsNone(hybrid_ads._state['fade'])

    def test_release_during_scope_entry_starts_from_the_live_offset(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS / 2
        camera.CameraModeState.CameraLocationOffset = S(X=10.0, Y=37.5, Z=5.0)
        mod._ads_route, mod._ads_active = 'hip', False
        hybrid_ads.release_transition(mod, 0.06)
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 75.0, 10.0), (10.0, 37.5, 5.0))
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS * 2
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 75.0, 10.0), (0.0, 75.0, 10.0))
        self.assertIsNone(hybrid_ads._state['fade'])

    def test_return_fade_holds_while_the_camera_still_blends(self):
        mod, camera, _ = fake_mod(route='hip')
        mod._ads_active = False
        camera.CameraModeState.CameraLocationOffset = S(X=0.0, Y=0.0, Z=0.0)
        hybrid_ads.start_return_fade(mod)
        self.clock.now += 1.0
        camera.CameraModeState.bIsTransitioning = True
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 75.0, 10.0))
        camera.CameraModeState.bIsTransitioning = False
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        self.assertIsNone(hybrid_ads._state['fade'])

    def test_fov_fade_is_finished_with_its_native_value(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        self.clock.now += hybrid_ads.SCOPE_BLEND_SECONDS / 2
        hybrid_ads.update(mod)
        self.assertAlmostEqual(camera.CameraModeState.BaseFOVOffset, -6.0)
        hybrid_ads.finish_fov_fade(mod)
        self.assertEqual(camera.CameraModeState.BaseFOVOffset, 0.0)
        hybrid_ads.toggle_scope(mod)  # leaves fov_fade None; reset(mod) is safe
        hybrid_ads.reset(mod)
        self.assertIsNone(hybrid_ads._state['fov_fade'])

    def test_fov_fade_ends_on_context_change(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        mod._vehicle_camera_active = True
        hybrid_ads.update(mod)
        self.assertEqual(camera.CameraModeState.BaseFOVOffset, 0.0)
        self.assertIsNone(hybrid_ads._state['fov_fade'])

    def test_fades_stop_when_the_camera_context_changes(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        mod._vehicle_camera_active = True
        self.assertEqual(hybrid_ads.compensate(mod, 0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        self.assertIsNone(hybrid_ads._state['fade'])

    def test_scope_flag_is_dropped_when_the_route_leaves_fps(self):
        mod, camera, _ = fake_mod()
        hybrid_ads.toggle_scope(mod)
        mod._ads_route = 'tps'
        hybrid_ads.update(mod)
        self.assertFalse(hybrid_ads._state['scoped'])
        self.assertEqual(hybrid_ads._state['scope_lost'], 1)


class OmniTriggerTests(HybridBase):
    def session(self, mod):
        keys = dict(sprint=False)
        return S(mod=mod, inputs=S(snapshot=lambda pc: dict(keys)), report={}), keys

    def test_one_toggle_per_sprint_press_while_aiming(self):
        from BL4ThirdPersonPOC.omni.animation import observe_hybrid_scope
        mod, _, _ = fake_mod()
        session, keys = self.session(mod)
        calls = []
        with patch.object(hybrid_ads, 'request_scope', lambda m, s: calls.append(m) or 'queued'):
            observe_hybrid_scope(session, None)
            keys['sprint'] = True
            for _ in range(5):
                observe_hybrid_scope(session, None)
            keys['sprint'] = False
            observe_hybrid_scope(session, None)
            keys['sprint'] = True
            observe_hybrid_scope(session, None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(session.report['hybrid_scope_presses'], 2)

    def test_sprint_without_ads_or_option_does_nothing(self):
        from BL4ThirdPersonPOC.omni.animation import observe_hybrid_scope
        mod, _, _ = fake_mod()
        session, keys = self.session(mod)
        calls = []
        with patch.object(hybrid_ads, 'request_scope', lambda m, s: calls.append(m) or 'queued'):
            mod._ads_active = False
            keys['sprint'] = True
            observe_hybrid_scope(session, None)
            keys['sprint'] = False
            observe_hybrid_scope(session, None)
            mod._ads_active = True
            mod.omni_hybrid_ads.value = False
            keys['sprint'] = True
            observe_hybrid_scope(session, None)
        self.assertEqual(calls, [])


class ReconciliationTests(HybridBase):
    """Scope exit: TPS ADS restarts for the same weapon after the ThirdPerson blend."""

    def owner(self):
        mod, camera, weapon = fake_mod(route='sniper_fps')
        mod._ads_handoff['route_pending'] = dict(
            from_route='sniper_fps', weapon_address=0xAA, category='sniper_rifle', source='s',
            evidence='e', hybrid_same_weapon=True)
        mod._ads_handoff.update(gap_entries=0, gap_frames=0, errors=0)
        started, published = [], []

        def start(camera_manager, category, source, evidence):
            started.append(category)
            mod._ads_route = 'tps'
            mod._ads_handoff['route_pending'] = None

        mod._start_hybrid_tps_ads = start
        mod._request_tps_reticle_publish = published.append
        mod._apply_camera_offset = lambda: None
        mod._ads_debug_error = lambda *a: None
        mod._cancel_hybrid_ads = lambda reason: None
        return mod, camera, started, published

    def test_waits_for_the_blend_then_restarts_tps_ads_without_equip_gate(self):
        from BL4ThirdPersonPOC.ads_handoff import _update_hybrid_ads_route_reconciliation_impl as reconcile
        mod, camera, started, published = self.owner()
        camera.CameraModeState.bIsTransitioning = True
        reconcile(owner_module=mod)
        self.assertEqual(started, [])
        camera.CameraModeState.bIsTransitioning = False
        reconcile(owner_module=mod)
        self.assertEqual(started, ['sniper_rifle'])
        self.assertEqual(published, ['hybrid_scope_exit'])
        self.assertNotIn('reticle_rebind_active', [k for k, v in mod._ads_handoff.items() if v is True])
        request = mod._ads_handoff['native_tps_rearm']
        self.assertEqual((request['same_weapon'], request['attempted']), (True, False))
        self.assertEqual(request['identity'][3], 0xAA)

    def test_hybrid_weapon_swap_in_the_scope_waits_and_blends(self):
        from BL4ThirdPersonPOC.ads_handoff import _update_hybrid_ads_route_reconciliation_impl as reconcile
        mod, camera, started, published = self.owner()
        mod._ads_handoff['route_pending'] = None
        mod._ads_handoff['route_weapon'] = 0xCC  # scope was on another weapon
        mod._start_hybrid_tps_ads = lambda *args: (started.append(args[1]), setattr(
            mod, '_ads_collector_address', 0x77), mod._ads_handoff.update(route_pending=None))
        reconcile(owner_module=mod)
        self.assertEqual(camera.calls, [('ThirdPerson', hybrid_ads.SCOPE_BLEND_SECONDS)])
        self.assertEqual(hybrid_ads._state['fade']['kind'], 'in')
        camera.CameraModeState.bIsTransitioning = True
        reconcile(owner_module=mod)
        self.assertEqual(started, [])
        camera.CameraModeState.bIsTransitioning = False
        reconcile(owner_module=mod)
        self.assertEqual(started, ['sniper_rifle'])


class RearmGateTests(unittest.TestCase):
    """The held-ADS native rearm accepts the hybrid same-weapon request."""

    def owner(self, request):
        weapon, pc, pawn = S(Name='W'), S(Name='PC'), S(ZoomState=S(State=2))
        camera = Camera(weapon)
        addresses = {id(weapon): 0xAA, id(pc): 0x10, id(pawn): 0x20, id(camera): 0x30}
        handoff = dict(held=True, latch_active=False, reticle_rebind_active=False,
                       equip_ordinal=0, incoming_weapon=0, route_weapon=0xAA,
                       native_tps_rearm=request)
        mod = S(_ads_handoff=handoff, _ads_active=True, _ads_route='tps',
                _ads_tps_state=dict(phase='ads', transition=None, manager_address=0x30,
                                    weapon_address=0xAA),
                _ads_press_intent={}, _third_person_enabled=True, _third_person_pushed=True,
                _slide_active=False, _ladder_active=False, _vehicle_camera_active=False,
                _shop_camera_active=False, _camera_lifecycle={}, _native_ffyl_pending=False,
                _native_npc_pending=False, _native_ladder_handoff_pending=False,
                _native_slide_handoff_pending=False, _native_fault=False)
        mod._native_active = lambda: False
        mod._beam_active = lambda: False
        mod._get_runtime = lambda: (pc, pawn, camera)
        mod._object_address = lambda obj: addresses.get(id(obj), 0)
        mod._looks_like_first_person_fallback = lambda: False
        mod._ffyl_camera_stack_has_single_tps = lambda cam: True
        camera.CameraModeState.bIsColliding = False
        return mod, camera, pawn

    def test_same_weapon_request_needs_no_equip_pair(self):
        from BL4ThirdPersonPOC.native_lifecycle import _held_ads_rearm_ready
        identity = (0x10, 0x20, 0x30, 0xAA)
        mod, camera, pawn = self.owner(dict(identity=identity, attempted=False, same_weapon=True))
        self.assertTrue(_held_ads_rearm_ready(camera, pawn, owner_module=mod))
        mod, camera, pawn = self.owner(dict(identity=identity, attempted=False))
        self.assertFalse(_held_ads_rearm_ready(camera, pawn, owner_module=mod),
                         'weapon-swap requests still wait for the equip pair')



class LoaderWiringTests(unittest.TestCase):
    def test_option_console_and_disable_reset(self):
        import json
        import subprocess
        from pathlib import Path
        script = Path(__file__).with_name('loader_scenarios.py')
        completed = subprocess.run([sys.executable, str(script), 'hybrid_ads_wiring'], capture_output=True,
                                   text=True, timeout=120, cwd=str(script.parent))
        data = json.loads(completed.stdout.split('RESULT_JSON=')[1])
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        self.assertEqual((result['default'], result['enabled'], result['disabled']), (False, True, False))
        self.assertFalse(result['has_dolly'])
        self.assertEqual(result['zoom'], 'ads_zoom_settings')
        self.assertFalse(result['active'], 'omni is off in this scenario')
        self.assertFalse(result['scoped_after_disable'])
        self.assertTrue(result['registered'])
        self.assertTrue(any('usage: bl4tps_omni hybrid on|off|status' in m for m in result['console']))


if __name__ == '__main__':
    unittest.main()
