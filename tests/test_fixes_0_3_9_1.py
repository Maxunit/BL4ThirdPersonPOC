"""0.3.9.1: TPS desync recovery, slide exit hold, full action listing."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as S

import support
from support import mapping, mapping_schema, session
from BL4ThirdPersonPOC import action_keys, tps_recovery


class Camera:
    def __init__(self, mode='Default', transitioning=False):
        self.mode = mode
        self.CameraModeState = S(bIsTransitioning=transitioning)
        self._address = 0x2000

    def GetActorCameraMode(self, pawn):
        return self.mode

    def _get_address(self):
        return self._address


def fake_mod(**overrides):
    camera = Camera()
    pawn = S(Class=S(Name='OakCharacter'), _get_address=lambda: 0x1000)
    pc = S(bShowMouseCursor=False)
    log = []
    mod = S(
        _third_person_enabled=True, _camera_lifecycle={'pending': False, 'reason': None},
        _ads_active=False, _vehicle_camera_active=False, _shop_camera_active=False,
        _ladder_active=False, _slide_active=False, _slide_camera_recovery_pending=False,
        _ads_route='hip', _ladder_pending_third_person_enabled=None,
        _ads_press_intent={'pending': False}, _native_fault=False,
        _camera_stack_owner={'owned': True, 'pawn_address': 0x1000, 'manager_address': 0x2000},
        _native_active=lambda: False, _respawn_camera_state=None,
        _get_runtime=lambda: (pc, pawn, camera), _is_vehicle_camera_view=lambda: False,
        _object_address=lambda obj: 0 if obj is None else int(obj._get_address()),
        logging=S(warning=lambda m: log.append(('warning', m)), error=lambda m: log.append(('error', m)),
                  info=lambda m: log.append(('info', m))),
    )
    armed = []
    retired = []

    def arm(reason, *, expected_pawn=0):
        armed.append((reason, expected_pawn))
        mod._camera_lifecycle.update(pending=True, reason=reason)
    mod._arm_camera_lifecycle = arm
    mod._retire_camera_stack_owner = lambda reason: (retired.append(reason), mod._camera_stack_owner.update(owned=False))
    mod._discard_camera_lifecycle = lambda reason: mod._camera_lifecycle.update(pending=False, phase='discarded:' + reason)
    mod._ffyl_camera_stack_empty = lambda manager: True
    for key, value in overrides.items():
        setattr(mod, key, value)
    return mod, S(camera=camera, pc=pc, pawn=pawn, log=log, armed=armed, retired=retired)


class TPSRecoveryTests(unittest.TestCase):
    def test_arms_once_default_settled_and_retires_empty_stack(self):
        mod, w = fake_mod()
        self.assertIsNone(tps_recovery.update(mod, now=10.0))
        self.assertIsNone(tps_recovery.update(mod, now=10.5), 'still settling')
        self.assertEqual(tps_recovery.update(mod, now=10.8), 'armed')
        self.assertEqual(w.armed, [('tps_desync', 0x1000)])
        self.assertEqual(w.retired, ['tps_desync_empty_stack'])
        self.assertTrue(any('DEFAULT_WHILE_TPS_WANTED' in m for _, m in w.log))

    def test_stale_owner_is_left_to_pop_retirement(self):
        mod, w = fake_mod()
        mod._camera_stack_owner['manager_address'] = 0x9999
        tps_recovery.update(mod, now=0.0)
        self.assertEqual(tps_recovery.update(mod, now=1.0), 'armed')
        self.assertEqual(w.retired, [])
        self.assertTrue(any('stale_owner=True' in m for _, m in w.log))

    def test_intentional_routes_and_transitions_block(self):
        for flag in ('_ads_active', '_vehicle_camera_active', '_shop_camera_active', '_ladder_active',
                     '_slide_active', '_slide_camera_recovery_pending'):
            mod, w = fake_mod(**{flag: True})
            for t in (0.0, 1.0, 2.0):
                self.assertIsNone(tps_recovery.update(mod, now=t), flag)
            self.assertEqual(w.armed, [], flag)
        mod, w = fake_mod(_ads_route='fps')
        self.assertIsNone(tps_recovery.update(mod, now=0.0))
        mod, w = fake_mod()
        mod._camera_lifecycle['pending'] = True
        tps_recovery.update(mod, now=0.0)
        self.assertIsNone(tps_recovery.update(mod, now=2.0))
        mod, w = fake_mod()
        w.camera.CameraModeState.bIsTransitioning = True
        tps_recovery.update(mod, now=0.0)
        self.assertIsNone(tps_recovery.update(mod, now=5.0), 'respawn blend still transitioning')
        mod, w = fake_mod()
        w.pc.bShowMouseCursor = True
        tps_recovery.update(mod, now=0.0)
        self.assertIsNone(tps_recovery.update(mod, now=5.0), 'menus')
        mod, w = fake_mod()
        w.pawn.Class = S(Name='OakVehicle')
        tps_recovery.update(mod, now=0.0)
        self.assertIsNone(tps_recovery.update(mod, now=5.0), 'vehicles')
        mod, w = fake_mod(_third_person_enabled=False)
        tps_recovery.update(mod, now=0.0)
        self.assertIsNone(tps_recovery.update(mod, now=5.0), 'FPS by choice')

    def test_cooldown_attempt_limit_and_episode_reset(self):
        mod, w = fake_mod()
        t = 0.0
        results = []
        for _ in range(200):
            mod._camera_lifecycle['pending'] = False  # repair keeps failing
            results.append(tps_recovery.update(mod, now=t))
            t += 0.1
        self.assertEqual(results.count('armed'), tps_recovery.MAX_ATTEMPTS)
        self.assertEqual(sum(1 for level, m in w.log if 'GAVE_UP' in m), 1)
        w.camera.mode = 'ThirdPerson'
        tps_recovery.update(mod, now=t)
        self.assertEqual(tps_recovery.state(mod)['attempts'], 0, 'healthy TPS ends the episode')

    def test_own_request_resolves_when_tps_returns_by_another_path(self):
        mod, w = fake_mod()
        tps_recovery.update(mod, now=0.0)
        tps_recovery.update(mod, now=1.0)
        self.assertTrue(mod._camera_lifecycle['pending'])
        w.camera.mode = 'ThirdPerson'
        tps_recovery.update(mod, now=1.1)
        self.assertFalse(mod._camera_lifecycle['pending'])
        self.assertEqual(mod._camera_lifecycle['phase'], 'tps_desync_resolved')
        mod, w = fake_mod()
        tps_recovery.update(mod, now=0.0)
        tps_recovery.update(mod, now=1.0)
        mod._vehicle_camera_active = True
        tps_recovery.update(mod, now=1.1)
        self.assertFalse(mod._camera_lifecycle['pending'], 'vehicle supersedes the request')

    def test_other_lifecycles_are_never_touched(self):
        mod, w = fake_mod()
        mod._camera_lifecycle.update(pending=True, reason='client_restart')
        w.camera.mode = 'ThirdPerson'
        tps_recovery.update(mod, now=0.0)
        self.assertTrue(mod._camera_lifecycle['pending'])

    def test_visibly_first_person(self):
        mod, w = fake_mod()
        self.assertTrue(tps_recovery.visibly_first_person(mod))
        w.camera.mode = 'ThirdPerson'
        self.assertFalse(tps_recovery.visibly_first_person(mod))
        w.camera.mode = 'Default'
        mod._slide_active = True
        self.assertFalse(tps_recovery.visibly_first_person(mod))


class RespawnHandoffArmingTests(unittest.TestCase):
    """0.3.9.2: the respawn flight must end at the TPS camera (respawn_camera.py)."""

    def test_respawn_camera_arms_the_existing_client_restart_handoff_once(self):
        mod, w = fake_mod()
        w.camera.mode = 'RespawnCamera'
        self.assertEqual(tps_recovery.update(mod, now=0.0), 'respawn_armed')
        self.assertEqual(w.armed, [('client_restart', 0x1000)])
        mod._camera_lifecycle['pending'] = False  # even if the handoff declined early
        self.assertIsNone(tps_recovery.update(mod, now=0.1), 'once per respawn')
        self.assertEqual(len(w.armed), 1)
        w.camera.mode = 'Default'
        w.camera.CameraModeState.bIsTransitioning = True
        tps_recovery.update(mod, now=0.2)
        w.camera.mode = 'RespawnCamera'
        self.assertEqual(tps_recovery.update(mod, now=30.0), 'respawn_armed', 'next respawn')
        self.assertTrue(any('RESPAWN_CAMERA_SEEN' in m for _, m in w.log))

    def test_existing_client_restart_reconciliation_is_left_alone(self):
        mod, w = fake_mod()
        w.camera.mode = 'RespawnCamera'
        mod._camera_lifecycle.update(pending=True, reason='client_restart')
        self.assertIsNone(tps_recovery.update(mod, now=0.0))
        self.assertEqual(w.armed, [])

    def test_respawn_arming_gates(self):
        for overrides in (dict(_third_person_enabled=False), dict(_vehicle_camera_active=True),
                          dict(_native_fault=True, _native_active=lambda: True)):
            mod, w = fake_mod(**overrides)
            w.camera.mode = 'RespawnCamera'
            tps_recovery.update(mod, now=0.0)
            self.assertEqual(w.armed, [], overrides)


class SlideExitTests(unittest.TestCase):
    def setup_session(self, mode='Default', transitioning=False, recovery=True, sliding=False):
        o, _ = session()
        o.active = True
        o.impulse_index = 1
        o.combat = {'active': False}
        o.native.base = 1000
        rotation = S(Pitch=0., Yaw=90., Roll=0.)
        writes = []

        def set_rotation(pawn, value):
            writes.append(value['Yaw'])
            rotation.Yaw = value['Yaw']
            return True
        o.set_rotation = set_rotation
        pawn = S(K2_GetActorRotation=lambda: rotation, bIsCrouched=True, IsCharacterDashing=lambda: False)
        camera = S(GetActorCameraMode=lambda _: mode, CameraModeState=S(bIsTransitioning=transitioning))
        movement = S(MovementMode=1, CustomMovementMode=0)
        o.bound = lambda: (S(bShowMouseCursor=False), pawn, camera, movement)
        o.mod._third_person_enabled = True
        o.mod._slide_active = sliding
        o.mod._slide_camera_recovery_pending = recovery
        o.mod._vehicle_camera_active = False
        o.mod._shop_camera_active = False
        o.mod._ladder_active = False
        o.jump_down = lambda _: False
        o.air_dash_down = lambda _: False
        o.report['samples'] = [dict(t=1.0, horizontal_speed=0.0, velocity_yaw=None,
                                    control_rotation={'Yaw': 0.0})]
        o.follow_previous_t = 0.98
        return o, rotation, writes, camera

    def test_classification_window(self):
        o, _, _, camera = self.setup_session()
        args = o.bound()
        self.assertEqual(o.classify_handoff(*args), ('PAUSE', 'SLIDE_EXIT'), 'Default during hand-back')
        o, _, _, camera = self.setup_session(mode='ThirdPerson', transitioning=True)
        self.assertEqual(o.classify_handoff(*o.bound()), ('PAUSE', 'SLIDE_EXIT'), 'TPS blend still running')
        o, _, _, camera = self.setup_session(mode='ThirdPerson', transitioning=False)
        self.assertEqual(o.classify_handoff(*o.bound()), ('PAUSE', 'CROUCHED'), 'settled TPS ends the window')
        o, _, _, camera = self.setup_session(recovery=False)
        self.assertEqual(o.classify_handoff(*o.bound())[0], 'STOP', 'Default without slide hand-back')
        o, _, _, camera = self.setup_session(sliding=True)
        self.assertEqual(o.classify_handoff(*o.bound()), ('PAUSE', 'SLIDE'))

    def test_exit_hold_restores_native_turn_to_aim(self):
        o, rotation, writes, _ = self.setup_session()
        o.slide_last_body_yaw = 90.0
        o.slide_exit_frame()
        self.assertEqual(writes, [], 'already on the slide heading')
        self.assertEqual((o.native.control[0], o.native.control[7], o.native.control[8]), (1, 1, 1000 + 3026455))
        rotation.Yaw = 30.0  # native turn toward the aim direction
        o.report['samples'][-1]['t'] = 1.02
        o.slide_exit_frame()
        self.assertEqual(writes[-1], 90.0)
        cycle = o.report['slide_exit_cycles'][-1]
        self.assertAlmostEqual(cycle['max_native_drift'], 60.0)
        self.assertEqual(cycle['end_yaw'], 90.0)

    def test_exit_follows_remaining_slide_velocity_and_yields_to_combat(self):
        o, rotation, writes, _ = self.setup_session()
        o.slide_last_body_yaw = 90.0
        o.report['samples'][-1].update(horizontal_speed=400.0, velocity_yaw=100.0, t=1.0)
        o.slide_exit_frame()
        self.assertAlmostEqual(writes[-1], 90.0 + min(10.0, 540.0 * 0.02))
        o.combat = {'active': True}
        count = len(writes)
        o.slide_exit_frame()
        self.assertEqual(len(writes), count, 'combat aim keeps native control')
        self.assertEqual(o.native.control[7], 0)


class ActionListingTests(unittest.TestCase):
    def test_all_mappings_include_paths_outside_action_root(self):
        rows = [mapping('Action_Zoom', 'RightMouseButton')]
        use = S(Action=S(_path_name=lambda: '/Game/Gbx/Interaction/IA_Use.IA_Use'),
                Key=S(KeyName='E'), bShouldBeIgnored=False, Triggers=[])
        listing = action_keys.list_all_mappings(S(Class=mapping_schema(), EnhancedActionMappings=rows + [use]))
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['actions']['/Game/Gbx/Interaction/IA_Use.IA_Use'], ['E'])


class LoaderToggleRepairTests(unittest.TestCase):
    def test_f5_repairs_instead_of_disabling_an_invisible_tps(self):
        script = Path(__file__).with_name('loader_scenarios.py')
        completed = subprocess.run([sys.executable, str(script), 'toggle_repair'], capture_output=True,
                                   text=True, timeout=120, cwd=str(script.parent))
        line = next((l for l in completed.stdout.splitlines() if l.startswith('RESULT_JSON=')), None)
        self.assertIsNotNone(line, completed.stdout[-2000:] + completed.stderr[-2000:])
        data = json.loads(line[len('RESULT_JSON='):])
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        self.assertEqual(result['repairs'], [False])
        self.assertTrue(result['tps_enabled_after'])
        self.assertTrue(result['stage_registered'])
        self.assertTrue(any('CLIENT_RESTART_SEEN' in m for m in result['restart_log']))



class LoaderDesyncRepairTests(unittest.TestCase):
    def test_stale_tps_after_load_is_repaired_through_the_lifecycle(self):
        script = Path(__file__).with_name('loader_scenarios.py')
        completed = subprocess.run([sys.executable, str(script), 'desync_repair'], capture_output=True,
                                   text=True, timeout=120, cwd=str(script.parent))
        data = json.loads(completed.stdout.split('RESULT_JSON=')[1])
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        self.assertEqual(result['results'], [None, None, 'armed'])
        self.assertIn('resumed', result['phases'])
        self.assertEqual(result['pushes'], [['ThirdPerson', '', '1.0', 'False']], 'one push, no blind pop')
        self.assertFalse(result['lifecycle_pending'])
        self.assertEqual(result['owner']['manager_address'], 0x2000, 'owner follows the new manager')
        self.assertEqual(result['owner']['last_retire_reason'], 'camera_repair:manager_replaced')


class LoaderRespawnWiringTests(unittest.TestCase):
    def test_respawn_camera_reaches_the_respawn_handoff_module(self):
        script = Path(__file__).with_name('loader_scenarios.py')
        completed = subprocess.run([sys.executable, str(script), 'respawn_wiring'], capture_output=True,
                                   text=True, timeout=120, cwd=str(script.parent))
        data = json.loads(completed.stdout.split('RESULT_JSON=')[1])
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        self.assertEqual(result['armed'], 'respawn_armed')
        self.assertEqual(result['lifecycle']['reason'], 'client_restart')
        self.assertTrue(result['lifecycle']['pending'])
        # Outside the game the native blend reader cannot read memory and declines;
        # in game it validates the build and drives the early TPS push.
        self.assertTrue(result['respawn_state_created'])


if __name__ == '__main__':
    unittest.main()
