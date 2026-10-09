"""0.3.9.3: shop native PRE restore, Action_Use interaction keys, sync diagnostics."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as S

import support
from support import mapping
from BL4ThirdPersonPOC import action_keys

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / 'BL4ThirdPersonPOC'


def run_scenario(name):
    script = Path(__file__).with_name('loader_scenarios.py')
    completed = subprocess.run([sys.executable, str(script), name], capture_output=True,
                               text=True, timeout=120, cwd=str(script.parent))
    data = json.loads(completed.stdout.split('RESULT_JSON=')[1])
    return data


class FakeKeybind:
    def __init__(self, key):
        self.key = key


def owner_for(rows):
    keys = dict(mouse=FakeKeybind('RightMouseButton'), pad=FakeKeybind('Gamepad_LeftTrigger'),
                use_kbm=FakeKeybind('E'), use_pad=FakeKeybind('Gamepad_FaceButton_Left'))
    pc = S(bShowMouseCursor=False,
           PlayerInput=S(Class=support.mapping_schema(), EnhancedActionMappings=rows))
    mod = S(FIRST_PERSON_ANIM_HOOK='widget', _get_runtime=lambda: (pc, None, None),
            logging=S(info=lambda m: support.LOG.append(('info', m)),
                      warning=lambda m: support.LOG.append(('warning', m)),
                      error=lambda m: support.LOG.append(('error', m))))
    owner = action_keys.Owner(mod, (('ads', 'kbm', keys['mouse']), ('ads', 'gamepad', keys['pad']),
                                    ('interact', 'kbm', keys['use_kbm']),
                                    ('interact', 'gamepad', keys['use_pad'])))
    owner.active = True
    return owner, pc, keys


class GameThread:
    def __init__(self, value=True):
        self.value = value

    def __enter__(self):
        self.original = action_keys.runtime_updates.is_game_thread
        action_keys.runtime_updates.is_game_thread = lambda: self.value

    def __exit__(self, *exc):
        action_keys.runtime_updates.is_game_thread = self.original


class InteractionActionTests(unittest.TestCase):
    def test_use_action_is_the_confirmed_interaction_asset(self):
        self.assertEqual(action_keys.ROLE_ACTIONS['interact'], 'Action_Use')

    def test_interaction_follows_a_remapped_use_action_near_an_interactable(self):
        rows = [mapping('Action_Zoom', 'RightMouseButton'), mapping('Action_Use', 'F'),
                mapping('Action_Use', 'Gamepad_FaceButton_Bottom')]
        owner, pc, keys = owner_for(rows)
        with GameThread():
            owner.frame(None, None, None, None)
        self.assertEqual((keys['use_kbm'].key, keys['use_pad'].key), ('F', 'Gamepad_FaceButton_Bottom'))
        self.assertEqual(owner.state[('interact', 'kbm')]['status'], 'FOLLOWING')
        # Interaction context removed: the rows disappear, the keys stay.
        del rows[1:]
        with GameThread():
            owner.frame(None, None, None, None)
        self.assertEqual(owner.sync_count, 2)
        self.assertEqual((keys['use_kbm'].key, keys['use_pad'].key), ('F', 'Gamepad_FaceButton_Bottom'))
        self.assertEqual(owner.state[('interact', 'kbm')]['status'], 'KEPT_NO_CONFIGURED_KEY')

    def test_default_use_mapping_keeps_e_and_square(self):
        rows = [mapping('Action_Use', 'E'), mapping('Action_Use', 'Gamepad_FaceButton_Left')]
        owner, pc, keys = owner_for(rows)
        with GameThread():
            owner.frame(None, None, None, None)
        self.assertEqual((keys['use_kbm'].key, keys['use_pad'].key), ('E', 'Gamepad_FaceButton_Left'))


class SyncDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.saved = action_keys._owner

    def tearDown(self):
        action_keys._owner = self.saved

    def test_skip_reasons_are_counted(self):
        owner, pc, _ = owner_for([mapping('Action_Zoom', 'RightMouseButton')])
        with GameThread(False):
            owner.frame(None, None, None, None)
        pc.bShowMouseCursor = True
        with GameThread():
            owner.frame(None, None, None, None)
        self.assertEqual(owner.skips, {'not_game_thread': 1, 'cursor_shown': 1})
        self.assertEqual((owner.frames, owner.sync_count), (1, 0))

    def test_report_exposes_frames_skips_and_route(self):
        owner, pc, _ = owner_for([])
        owner.registered = True
        action_keys._owner = owner
        original = action_keys.runtime_updates.has_hook
        action_keys.runtime_updates.has_hook = lambda *spec: False
        try:
            report = action_keys.report()
        finally:
            action_keys.runtime_updates.has_hook = original
        for key in ('frames', 'skips', 'route_registered', 'route_restores', 'syncs'):
            self.assertIn(key, report)
        self.assertFalse(report['route_registered'])

    def test_sync_now_restores_a_lost_route_and_syncs(self):
        rows = [mapping('Action_Zoom', 'C')]
        owner, pc, keys = owner_for(rows)
        owner.registered = True
        action_keys._owner = owner
        routes = set()
        saved = (action_keys.runtime_updates.has_hook, action_keys.runtime_updates.add_hook)
        action_keys.runtime_updates.has_hook = lambda *spec: spec in routes
        action_keys.runtime_updates.add_hook = lambda *args: routes.add(args[:3])
        try:
            with GameThread():
                self.assertIsNone(action_keys.sync_now(pc.PlayerInput))
            with GameThread(False):
                self.assertEqual(action_keys.sync_now(pc.PlayerInput), 'not_game_thread')
        finally:
            action_keys.runtime_updates.has_hook, action_keys.runtime_updates.add_hook = saved
        self.assertEqual(owner.route_restores, 1)
        self.assertIn(owner.spec, routes)
        self.assertEqual((owner.sync_count, keys['mouse'].key), (1, 'C'))
        self.assertEqual(owner.mapping_count, 1)
        self.assertFalse(owner.busy)

    def test_sync_now_without_owner(self):
        action_keys._owner = None
        self.assertEqual(action_keys.sync_now(S(EnhancedActionMappings=[])), 'not_running')

    def test_console_command_syncs_before_reporting(self):
        source = (PKG / '__init__.py').read_text()
        body = source.split('def dump_input_actions_console', 1)[1].split('\n\n\n', 1)[0]
        self.assertLess(body.index('action_keys.sync_now(player_input)'),
                        body.index('ACTION_KEY_SYNC {action_keys.report()}'))


class ShopNativePreRestoreTests(unittest.TestCase):
    def test_shop_and_npc_use_restore_native_state_before_structured_interaction(self):
        data = run_scenario('shop_pre_restore')
        self.assertTrue(data['ok'], data.get('error'))
        result = data['result']
        # Vending machine: one PRE restore, no second attempt at the camera pop.
        self.assertEqual(result['after_chest'], ['shop_server_use_pre'])
        self.assertNotIn('camera_pop:requested', result['stops'])
        self.assertTrue(result['pending_after_use'], 'native rearm held until the use completes')
        self.assertTrue(result['shop_active'])
        self.assertEqual(result['pops'], ['ThirdPerson'])
        # Quest NPC route unchanged.
        self.assertEqual(result['stops'], ['shop_server_use_pre', 'npc_server_use_pre'])
        self.assertEqual(result['errors'], [])

    def test_only_structured_interaction_usables_are_listed(self):
        import ast
        tree = ast.parse((PKG / 'game_hooks.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], 'id', '') == 'NATIVE_PRE_RESTORE_USABLES')
        self.assertEqual(ast.literal_eval(node.value), {'OakCharacter': 'npc_server_use_pre',
                                 'OakVendingMachine': 'shop_server_use_pre'})


if __name__ == '__main__':
    unittest.main()
