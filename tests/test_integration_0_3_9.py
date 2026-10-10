"""Integration tests for 0.3.9: omni subpackage, production mode, action keys, build gate."""
import ast
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S

import support
from support import controller, mapping, session
from BL4ThirdPersonPOC import action_keys, build_gate, input_bindings
from BL4ThirdPersonPOC import omni
from BL4ThirdPersonPOC.omni import common, settings
from BL4ThirdPersonPOC.omni.lifecycle import LifecycleSupervisor

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / 'BL4ThirdPersonPOC'
OMNI = PKG / 'omni'


class CountingController:
    """Controller stub counting key-state getter calls."""

    def __init__(self):
        self.inner = controller()
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def IsInputKeyDown(self, key):
        self.calls += 1
        return self.inner.IsInputKeyDown(key)

    def GetInputAnalogKeyState(self, key):
        self.calls += 1
        return self.inner.GetInputAnalogKeyState(key)


class InputCostTests(unittest.TestCase):
    def bindings(self):
        pc = controller()
        bindings = input_bindings.NativeBindings(pc)
        bindings.refresh(require_complete=True)
        return pc, bindings

    def test_snapshot_evaluates_key_state_once_per_frame(self):
        pc, bindings = self.bindings()
        calls = []
        original = pc.IsInputKeyDown
        pc.IsInputKeyDown = lambda key: calls.append(1) or original(key)
        bindings.begin_frame()
        first = bindings.snapshot(pc)
        per_snapshot = len(calls)
        for _ in range(4):
            self.assertEqual(bindings.snapshot(pc), first)
        self.assertEqual(len(calls), per_snapshot)
        pc.pressed.add('UserBinding_0')
        self.assertFalse(bindings.snapshot(pc)['sprint'], 'cached within the frame')
        bindings.begin_frame()
        self.assertTrue(bindings.snapshot(pc)['sprint'], 'fresh in the next frame')

    def test_without_begin_frame_snapshot_is_always_fresh(self):
        pc, bindings = self.bindings()
        self.assertFalse(bindings.snapshot(pc)['jump'])
        pc.pressed.add('UserBinding_3')
        self.assertTrue(bindings.snapshot(pc)['jump'])

    def test_maybe_refresh_is_bounded_and_reacts_to_changes(self):
        pc, bindings = self.bindings()
        refreshes = bindings.refresh_count
        for _ in range(input_bindings.REFRESH_INTERVAL_UPDATES - 1):
            bindings.maybe_refresh(require_complete=True)
        self.assertEqual(bindings.refresh_count, refreshes, 'no scan inside the cadence')
        bindings.maybe_refresh(require_complete=True)
        self.assertEqual(bindings.refresh_count, refreshes + 1, 'cadence scan')
        bindings.maybe_refresh(force=True)
        self.assertEqual(bindings.refresh_count, refreshes + 2, 'forced scan')
        pc.PlayerInput.EnhancedActionMappings.append(mapping('Action_Fire', 'Extra'))
        bindings.maybe_refresh()
        self.assertEqual(bindings.refresh_count, refreshes + 3, 'count change scan')
        self.assertEqual([str(k.KeyName) for k in bindings.bindings['fire']], ['UserBinding_4', 'Extra'])

    def test_maybe_refresh_keeps_fail_closed_rules(self):
        pc, bindings = self.bindings()
        pc.PlayerInput.EnhancedActionMappings[:] = [
            row for row in pc.PlayerInput.EnhancedActionMappings
            if 'Action_Fire' not in str(row.Action._path_name())]
        with self.assertRaisesRegex(RuntimeError, 'missing: fire'):
            bindings.maybe_refresh(require_complete=True)
        pc.PlayerInput = S()
        with self.assertRaisesRegex(RuntimeError, 'owner changed'):
            bindings.maybe_refresh()


class OmniIntegrationTests(unittest.TestCase):
    def owner(self, settings_dir=None):
        owner = S(FIRST_PERSON_ANIM_HOOK='widget', CLIENT_RESTART_FUNCTION='restart',
                  _third_person_enabled=False, _get_runtime=lambda: (None, None, None))
        if settings_dir is not None:
            owner.SETTINGS_DIR = settings_dir
        return owner

    def updates(self, thread=True):
        registered = set()
        return S(_owner=S(active=True, live_widget=lambda: None),
                 is_game_thread=lambda: thread,
                 has_hook=lambda *args: args in registered,
                 add_hook=lambda *args: registered.add(args[:-1]),
                 remove_hook=lambda *args: registered.discard(args)), registered

    def test_supervisor_arms_without_live_widget_and_never_patches_disable(self):
        updates, registered = self.updates()
        owner = self.owner()
        state = LifecycleSupervisor(owner, updates)
        state.install()
        self.assertEqual(len(registered), 4)
        self.assertFalse(hasattr(owner, '_on_disable_impl'))
        state.finish('USER_STOP')
        self.assertFalse(registered)

    def test_cold_start_client_restart_without_thread_is_not_a_failure(self):
        updates, _ = self.updates(thread=False)
        state = LifecycleSupervisor(self.owner(), updates)
        state.install()
        state.restart_pre(object(), S(NewPawn=None), None, None)
        self.assertTrue(state.active)
        self.assertEqual(state.report['errors'], [])
        self.assertTrue(state.restart_wait)

    def test_report_policy_production_vs_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            for diagnostics, expected in ((False, 0), (True, 1)):
                settings.set_diagnostics(diagnostics)
                updates, _ = self.updates()
                state = LifecycleSupervisor(self.owner(directory), updates)
                state.install()
                state.finish('USER_STOP')
                reports = list((Path(directory) / common.REPORT_DIRECTORY_NAME).glob('*.json'))
                self.assertEqual(len(reports), expected, diagnostics)
            settings.set_diagnostics(False)
            updates, _ = self.updates()
            state = LifecycleSupervisor(self.owner(directory), updates)
            state.install()
            state.fail('test', RuntimeError('boom'))
            reports = list((Path(directory) / common.REPORT_DIRECTORY_NAME).glob('*.json'))
            self.assertEqual(len(reports), 2, 'errors always produce a report')
            self.assertTrue(any(level == 'error' and 'STOPPED_ON_ERROR' in message
                                for level, message in support.LOG))
        settings.set_diagnostics(False)

    def test_report_path_is_never_relative_to_the_package(self):
        self.assertIsNone(common.report_path(S(), 'x'))
        path = common.report_path(S(SETTINGS_DIR='/settings'), 'player_omnidirectional_gameplay')
        self.assertEqual(path.parent, Path('/settings') / common.REPORT_DIRECTORY_NAME)
        for file in OMNI.glob('*.py'):
            self.assertNotIn('Path(__file__)', file.read_text(), file.name)

    def test_report_directory_keeps_newest_files_only(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for index in range(common.MAX_REPORT_FILES + 5):
                common.write_report(folder / f'{common.REPORT_PREFIX}{index:03}.json', {'i': index})
            self.assertEqual(len(list(folder.glob('*.json'))), common.MAX_REPORT_FILES)

    def test_production_messages_are_developer_only(self):
        support.LOG.clear()
        settings.set_diagnostics(False)
        common.log.warning('state')
        settings.set_diagnostics(True)
        common.log.warning('state')
        settings.set_diagnostics(False)
        self.assertEqual([level for level, _ in support.LOG], ['dev_warning', 'warning'])

    def test_session_pins_slide_recording_buffers_and_skips_snapback(self):
        o, _ = session()
        self.assertIs(o.native.control._slide_record_control, o.native.slide_control)
        self.assertIs(o.native.control._slide_record_buffer, o.native.slide_buffer)
        o.restore_pending = True
        o.original_rotation = {'Pitch': 0., 'Yaw': 12., 'Roll': 0.}
        o.set_rotation = lambda *args: self.fail('no actor write on stop')
        o.restore_body_rotation()
        self.assertFalse(o.restore_pending)
        self.assertEqual(o.report['restore']['status'], 'NO_SNAPBACK_NATIVE_ROTATION_RESUMES')

    def test_session_diagnostics_follow_runtime_switch(self):
        settings.set_diagnostics(True)
        o, _ = session()
        self.assertTrue(o.collect_pose_diagnostics)
        settings.set_diagnostics(False)
        o, _ = session()
        self.assertFalse(o.collect_pose_diagnostics)

    def test_start_refuses_unreviewed_build_and_missing_producer(self):
        owner = self.owner()
        original = build_gate.status
        try:
            build_gate.status = lambda _owner: dict(build=(1, 2, 3), reviewed=False, store='epic', reason='x')
            self.assertFalse(omni.start(owner))
            self.assertEqual(omni.last_failure(), 'unreviewed game build')
            build_gate.status = lambda _owner: dict(build=build_gate.REVIEWED_BUILD, reviewed=True)
            sys.modules['BL4ThirdPersonPOC.runtime_updates']._owner = None
            self.assertFalse(omni.start(owner))
            self.assertEqual(omni.last_failure(), 'runtime updates not started')
            self.assertFalse(omni.is_running(owner))
        finally:
            build_gate.status = original

    def test_start_and_shutdown_through_package_api(self):
        owner = self.owner()
        updates_module = sys.modules['BL4ThirdPersonPOC.runtime_updates']
        fake, registered = self.updates()
        original_status = build_gate.status
        saved = {name: getattr(updates_module, name) for name in ('_owner', 'add_hook', 'has_hook', 'remove_hook', 'is_game_thread')}
        try:
            build_gate.status = lambda _owner: dict(build=build_gate.REVIEWED_BUILD, reviewed=True)
            for name in saved:
                setattr(updates_module, name, getattr(fake, name))
            self.assertTrue(omni.start(owner))
            self.assertTrue(omni.is_running(owner))
            self.assertTrue(omni.start(owner), 'idempotent')
            self.assertEqual(omni.status(owner)['phase'], 'WAITING_ON_FOOT')
            self.assertTrue(omni.shutdown(owner, 'FEATURE_DISABLED'))
            self.assertFalse(omni.is_running(owner))
            self.assertFalse(registered)
            self.assertTrue(omni.shutdown(owner), 'idempotent')
        finally:
            build_gate.status = original_status
            for name, value in saved.items():
                setattr(updates_module, name, value)


class FakeKeybind:
    def __init__(self, key):
        self.key = key


def player_input(rows):
    return S(Class=support.mapping_schema(), EnhancedActionMappings=rows)


class ActionKeyTests(unittest.TestCase):
    def test_key_selection_rules(self):
        names = ['RightMouseButton', 'Gamepad_LeftTriggerAxis', 'MouseX', 'ThumbMouseButton']
        self.assertEqual(action_keys.usable_keys(names, 'kbm'), ['RightMouseButton', 'ThumbMouseButton'])
        self.assertEqual(action_keys.usable_keys(names, 'gamepad'), ['Gamepad_LeftTrigger'])
        self.assertEqual(action_keys.choose_key('ThumbMouseButton', names, 'kbm'), 'ThumbMouseButton')
        self.assertEqual(action_keys.choose_key('RightMouseButton', ['C'], 'kbm'), 'C')
        self.assertIsNone(action_keys.choose_key('RightMouseButton', ['Gamepad_LeftX'], 'kbm'))

    def owner(self, rows, pc_extra=None):
        mouse, pad = FakeKeybind('RightMouseButton'), FakeKeybind('Gamepad_LeftTrigger')
        use_kbm, use_pad = FakeKeybind('E'), FakeKeybind('Gamepad_FaceButton_Left')
        pc = S(bShowMouseCursor=False, PlayerInput=player_input(rows), **(pc_extra or {}))
        mod = S(FIRST_PERSON_ANIM_HOOK='widget', _get_runtime=lambda: (pc, None, None),
                logging=S(info=lambda m: support.LOG.append(('info', m)),
                          error=lambda m: support.LOG.append(('error', m))))
        owner = action_keys.Owner(mod, (('ads', 'kbm', mouse), ('ads', 'gamepad', pad),
                                        ('interact', 'kbm', use_kbm), ('interact', 'gamepad', use_pad)))
        owner.active = True
        return owner, pc, (mouse, pad, use_kbm, use_pad)

    def run_frame(self, owner):
        original = action_keys.runtime_updates.is_game_thread
        action_keys.runtime_updates.is_game_thread = lambda: True
        try:
            owner.frame(None, None, None, None)
        finally:
            action_keys.runtime_updates.is_game_thread = original

    def test_remapped_ads_follows_configured_keys_and_interaction_stays(self):
        # No interaction context applied: Action_Use has no rows, E/Square stay.
        rows = [mapping('Action_Zoom', 'C'), mapping('Action_Zoom', 'Gamepad_LeftTriggerAxis'),
                mapping('Action_Fire', 'LeftMouseButton')]
        owner, pc, (mouse, pad, use_kbm, use_pad) = self.owner(rows)
        self.run_frame(owner)
        self.assertEqual((mouse.key, pad.key), ('C', 'Gamepad_LeftTrigger'))
        self.assertEqual((use_kbm.key, use_pad.key), ('E', 'Gamepad_FaceButton_Left'))
        self.assertEqual(owner.state[('interact', 'kbm')]['status'], 'KEPT_NO_CONFIGURED_KEY')

    def test_missing_or_ignored_mapping_keeps_current_key(self):
        rows = [mapping('Action_Zoom', 'C', ignored=True)]
        owner, pc, (mouse, pad, _, _) = self.owner(rows)
        self.run_frame(owner)
        self.assertEqual((mouse.key, pad.key), ('RightMouseButton', 'Gamepad_LeftTrigger'))
        self.assertEqual(owner.state[('ads', 'kbm')]['status'], 'KEPT_NO_CONFIGURED_KEY')

    def test_scans_only_on_change_menu_close_or_cadence(self):
        rows = [mapping('Action_Zoom', 'RightMouseButton')]
        owner, pc, (mouse, _, _, _) = self.owner(rows)
        self.run_frame(owner)
        self.assertEqual(owner.sync_count, 1)
        for _ in range(5):
            self.run_frame(owner)
        self.assertEqual(owner.sync_count, 1)
        pc.bShowMouseCursor = True
        rows[0] = mapping('Action_Zoom', 'V')
        self.run_frame(owner)
        self.assertEqual((owner.sync_count, mouse.key), (1, 'RightMouseButton'), 'no work in menus')
        pc.bShowMouseCursor = False
        self.run_frame(owner)
        self.assertEqual((owner.sync_count, mouse.key), (2, 'V'), 'sync once the menu closed')
        for _ in range(action_keys.SYNC_INTERVAL_UPDATES):
            self.run_frame(owner)
        self.assertEqual(owner.sync_count, 3, 'bounded cadence')

    def test_errors_keep_keys_and_are_reported_once(self):
        owner, pc, (mouse, _, _, _) = self.owner([mapping('Action_Zoom', 'C')])
        pc.PlayerInput.Class = S(_path_name=lambda: '/Script/Other.Class', _superfields=lambda: (), _properties=lambda: [])
        support.LOG.clear()
        self.run_frame(owner)
        owner.menu_open = True
        self.run_frame(owner)
        self.assertEqual(mouse.key, 'RightMouseButton')
        self.assertEqual(sum(1 for level, m in support.LOG if 'SYNC_FAILED' in m), 1)

    def test_list_actions_groups_configured_keys(self):
        rows = [mapping('Action_Zoom', 'RightMouseButton'), mapping('Action_Zoom', 'Gamepad_LeftTrigger'),
                mapping('Action_Use', 'E', ignored=True)]
        listing = action_keys.list_actions(player_input(rows))
        self.assertEqual(listing['actions'], {'Action_Use': ['E (ignored)'],
                                              'Action_Zoom': ['RightMouseButton', 'Gamepad_LeftTrigger']})


def pe_image(stamp, size, machine=0x8664, magic=0x20B):
    image = bytearray(0x400)
    image[0:2] = b'MZ'
    struct.pack_into('<I', image, 60, 0x80)
    image[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', image, 0x80 + 4, machine)
    struct.pack_into('<I', image, 0x80 + 8, stamp)
    struct.pack_into('<H', image, 0x80 + 24, magic)
    struct.pack_into('<I', image, 0x80 + 80, size)
    return bytes(image)


class BuildGateTests(unittest.TestCase):
    def kernel(self, loaded=()):
        return S(GetModuleHandleW=lambda name=None: 0x140000000 if name is None else (1 if name in loaded else 0))

    def reader(self, image):
        return lambda address, size: image[address - 0x140000000:address - 0x140000000 + size]

    def test_reviewed_steam_build(self):
        image = pe_image(0x6AA81051, 0x31B8C000)
        result = build_gate.evaluate(self.reader(image), self.kernel(('steam_api64.dll',)))
        self.assertTrue(result['reviewed'])
        self.assertEqual((result['label'], result['store']), ('steam-2026-09-14', 'steam'))

    def test_other_build_is_refused_with_store_hint(self):
        image = pe_image(0x6B000000, 0x32000000)
        result = build_gate.evaluate(self.reader(image), self.kernel(('EOSSDK-Win64-Shipping.dll',)),
                                     'D:\\Epic Games\\Borderlands4\\OakGame\\Binaries\\Win64\\Borderlands4.exe')
        self.assertFalse(result['reviewed'])
        self.assertEqual(result['store'], 'epic')
        self.assertIn('0x6b000000', build_gate.summary(result))

    def test_unreadable_header_is_refused(self):
        result = build_gate.evaluate(self.reader(b'XX' + bytes(200)), self.kernel())
        self.assertFalse(result['reviewed'])
        self.assertIn('unreadable', result['reason'])

    def test_every_build_literal_points_to_the_gate(self):
        literal = re.compile(r'0x6AA81051|1789399121', re.I)
        audited = {'native_rotation.py', 'native_movement.py'}
        for file in PKG.rglob('*.py'):
            if file.name == 'build_gate.py' or file.name in audited:
                continue
            self.assertIsNone(literal.search(file.read_text()), file.name)
        # The audited V3 worker files keep their reviewed literal; it must match.
        for name in audited:
            text = (OMNI / name).read_text()
            for match in re.finditer(r'build\s*!=\s*\((0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+),\s*(0x[0-9A-Fa-f]+)\)', text):
                self.assertEqual(tuple(int(v, 16) for v in match.groups()), build_gate.REVIEWED_BUILD)


def call_names(function):
    """Call expressions in source order (ast.walk is breadth-first)."""
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    calls.sort(key=lambda node: (node.lineno, node.col_offset))
    return [ast.unparse(node.func) for node in calls]


def function(path, name):
    tree = ast.parse(path.read_text())
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


class LoaderWiringTests(unittest.TestCase):
    def test_shutdown_order(self):
        text = (PKG / 'mod_shutdown.py').read_text()
        self.assertLess(text.index('"omni_movement"'), text.index('"pickup_registry"'))
        self.assertLess(text.index('"action_keys"'), text.index('"runtime_updates"'))
        self.assertIn('and omni_restored and keys_restored', text)

    def test_enable_order(self):
        calls = call_names(function(PKG / 'game_hooks.py', '_on_enable_impl'))
        index = {name: calls.index(name) for name in (
            'omni.shutdown', 'action_keys.shutdown', 'build_gate.status',
            'owner_module._purge_mod_sdk_hooks', 'runtime_updates.start',
            'action_keys.start', 'omni.start')}
        self.assertLess(index['omni.shutdown'], index['build_gate.status'])
        self.assertLess(index['build_gate.status'], index['owner_module._purge_mod_sdk_hooks'])
        self.assertLess(index['runtime_updates.start'], index['action_keys.start'])
        self.assertLess(index['runtime_updates.start'], index['omni.start'])

    def test_omni_never_monkeypatches_the_loader(self):
        for file in OMNI.glob('*.py'):
            text = file.read_text()
            self.assertNotIn('_on_disable_impl', text, file.name)
            self.assertNotIn("sys.modules.get('BL4ThirdPersonPOC", text, file.name)

    def test_build_mod_receives_every_entry_point(self):
        tree = ast.parse((PKG / '__init__.py').read_text())
        assigned = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                    for target in node.targets if isinstance(target, ast.Name)}
        commands = {elt.id for elt in assigned['_MOD_COMMANDS'].elts}
        self.assertTrue({'omni_movement_console', 'dump_input_actions_console',
                         'report_build_gate_console'} <= commands)
        keybinds = {elt.id for elt in assigned['_MOD_KEYBINDS'].elts}
        decorated = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)
                     and any(isinstance(d, ast.Call) and getattr(d.func, 'id', '') == 'keybind'
                             for d in node.decorator_list)}
        self.assertEqual(keybinds, decorated)


class LoaderSmokeTests(unittest.TestCase):
    """Import and drive the real loader under SDK stubs in a fresh interpreter."""

    def run_scenario(self, name):
        completed = subprocess.run([sys.executable, str(Path(__file__).with_name('loader_scenarios.py')), name],
                                   capture_output=True, text=True, timeout=120, cwd=str(Path(__file__).parent))
        line = next((l for l in completed.stdout.splitlines() if l.startswith('RESULT_JSON=')), None)
        self.assertIsNotNone(line, completed.stdout[-2000:] + completed.stderr[-2000:])
        data = json.loads(line[len('RESULT_JSON='):])
        self.assertTrue(data['ok'], data.get('error'))
        return data['result']

    def test_unreviewed_build_installs_nothing(self):
        result = self.run_scenario('unreviewed')
        self.assertEqual(result['hooks'], [])
        self.assertEqual(result['enabled_keybinds'], [])
        self.assertEqual(result['enabled_commands'], ['bl4tps_build'])
        self.assertTrue(result['inactive_logged'])
        self.assertEqual(result['errors_after_disable'], [])

    def test_reviewed_build_with_feature_enables_and_cleans_up(self):
        result = self.run_scenario('reviewed_omni_on')
        enabled, disabled = result['after_enable'], result['after_disable']
        self.assertTrue(enabled['omni_running'])
        self.assertTrue(enabled['action_keys_running'])
        self.assertTrue(any('_player_omnidirectional_gameplay.lifecycle_pre' in r for r in enabled['updates_routes']))
        self.assertTrue(any('bl4tps.action_keys.frame' in r for r in enabled['updates_routes']))
        self.assertEqual(disabled['hooks'], [])
        self.assertFalse(disabled['omni_running'] or disabled['action_keys_running']
                         or disabled['runtime_updates_running'])
        self.assertEqual(disabled['disable_log'], [])

    def test_reviewed_build_without_feature(self):
        result = self.run_scenario('reviewed_omni_off')
        self.assertFalse(result['after_enable']['omni_running'])
        self.assertEqual(result['after_disable']['hooks'], [])

    @unittest.skipUnless((ROOT / 'dist' / 'BL4ThirdPersonPOC.sdkmod').exists(), 'run tools/build_sdkmod.py first')
    def test_loads_from_built_sdkmod_and_writes_reports_outside_it(self):
        result = self.run_scenario('from_sdkmod')
        self.assertIn('BL4ThirdPersonPOC.sdkmod', result['loader_file'])
        self.assertTrue(result['hybrid_on'])
        self.assertFalse(result['hybrid_off'])
        self.assertTrue(result['report_written'])
        self.assertEqual(result['hooks_after_disable'], 0)

    def test_toggle_cycle(self):
        steps = self.run_scenario('toggle_cycle')
        self.assertEqual([(s['option'], s['running'], s['caption']) for s in steps[:3]],
                         [(True, True, 'ON'), (False, False, 'OFF'), (True, True, 'ON')])
        self.assertEqual(steps[3], dict(diag_option=True, diag_runtime=True, running=True))
        self.assertFalse(steps[4]['after_disable_running'])


if __name__ == '__main__':
    unittest.main()


class MenuDispatchTests(unittest.TestCase):
    """Exercise only the new omni branches of menu_console.dispatch with stub widgets."""

    def setUp(self):
        from BL4ThirdPersonPOC import menu_console as ui
        self.ui = ui
        self.saved = {name: getattr(ui, name) for name in (
            'read_slider_changes', 'apply_numeric_inputs', 'apply_step_buttons', 'commit',
            'commit_vehicle', 'reset_vehicle_control', 'reset_motion_controls', 'finalize_motion')}
        ui.read_slider_changes = lambda state: []
        for name in self.saved:
            if name != 'read_slider_changes':
                setattr(ui, name, lambda *args, **kwargs: None)

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(self.ui, name, value)

    def state(self, pressed, omni_on):
        class Check:
            def __init__(self, on):
                self.on = on

            def IsChecked(self):
                return self.on

            def SetIsChecked(self, value):
                self.on = value

        class Label:
            text = None

            def SetText(self, value):
                self.text = value

        option = {'value': omni_on}
        calls = []

        def set_omni(value):
            calls.append(value)
            option['value'] = value

        buttons = {}
        state = dict(page=1, notice=Label(), sniper_label=Label(), ffyl_label=Label(),
                     ground_slam_label=Label(), dynamic_motion_label=Label(), omni_label=Label(),
                     get_sniper_mode=lambda: False, set_sniper_mode=lambda v: None,
                     get_ffyl_mode=lambda: True, set_ffyl_mode=lambda v: None,
                     get_ground_slam_mode=lambda: True, set_ground_slam_mode=lambda v: None,
                     get_omni_movement=lambda: option['value'], set_omni_movement=set_omni,
                     omni_movement_caption=lambda: 'ON' if option['value'] else 'OFF',
                     motion_views=[], buttons=buttons)

        class Buttons(dict):
            def __missing__(self, key):
                value = (Check(key in pressed), None, None, None)
                self[key] = value
                return value
        state['buttons'] = Buttons()
        return state, option, calls

    def run_dispatch(self, state):
        self.ui.dispatch(state, (), lambda *a: None, lambda: False, lambda v: None)

    def test_toggle_button(self):
        state, option, calls = self.state({'modes:omni'}, False)
        self.run_dispatch(state)
        self.assertEqual(calls, [True])
        self.assertEqual(state['omni_label'].text, 'Omni Movement: ON')

    def test_page_reset_and_defaults_switch_feature_off(self):
        for pressed in ({'reset'}, {'defaults'}):
            state, option, calls = self.state(pressed, True)
            self.run_dispatch(state)
            self.assertEqual(calls, [False], pressed)
            self.assertEqual(state['omni_label'].text, 'Omni Movement: OFF')
        state, option, calls = self.state({'reset'}, False)
        self.run_dispatch(state)
        self.assertEqual(calls, [], 'no stop request when already off')


