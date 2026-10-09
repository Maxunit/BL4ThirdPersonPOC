import ast
import hashlib
import json
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from support import controller, mapping, mapping_schema, session
from BL4ThirdPersonPOC.omni.inputs import NativeBindings
from BL4ThirdPersonPOC.omni.common import movement_input_state, quat, KEY
from BL4ThirdPersonPOC.omni.lifecycle import LifecycleSupervisor

ROOT = Path(__file__).resolve().parents[1]
OMNI = ROOT / 'BL4ThirdPersonPOC' / 'omni'


class InputTests(unittest.TestCase):
    def test_remapping_with_same_count_replaces_previous_binding(self):
        pc = controller()
        adapter = NativeBindings(pc)
        adapter.refresh(require_complete=True)
        pc.pressed.add('UserBinding_0')
        self.assertTrue(adapter.snapshot(pc)['sprint'])
        revision = adapter.revision
        pc.PlayerInput.EnhancedActionMappings[0] = mapping('Action_Sprint', 'ChangedBinding')
        adapter.refresh(require_complete=True)
        self.assertGreater(adapter.revision, revision)
        self.assertFalse(adapter.snapshot(pc)['sprint'])
        pc.pressed.add('ChangedBinding')
        self.assertTrue(adapter.snapshot(pc)['sprint'])

    def test_all_actions_follow_their_configured_bindings(self):
        pc = controller()
        adapter = NativeBindings(pc)
        adapter.refresh(require_complete=True)
        for i, role in enumerate(('sprint', 'dash', 'crouch', 'jump', 'fire', 'zoom')):
            pc.pressed = {'UserBinding_' + str(i)}
            active = adapter.snapshot(pc)
            self.assertEqual([r for r, value in active.items() if value], [role])

    def test_multiple_bindings_ignored_mapping_and_analog_intent(self):
        pc = controller()
        pc.PlayerInput.EnhancedActionMappings.append(mapping('Action_Fire', 'SecondFire'))
        pc.PlayerInput.EnhancedActionMappings.append(mapping('Action_Fire', 'IgnoredFire', ignored=True))
        adapter = NativeBindings(pc)
        adapter.refresh(require_complete=True)
        pc.pressed = {'IgnoredFire'}
        self.assertFalse(adapter.snapshot(pc)['fire'])
        pc.analog['SecondFire'] = 0.5
        self.assertTrue(adapter.snapshot(pc)['fire'])
        pc.analog['SecondFire'] = math.nan
        with self.assertRaisesRegex(RuntimeError, 'Nonfinite'):
            adapter.snapshot(pc)

    def test_missing_schema_owner_or_action_has_no_fallback(self):
        pc = controller()
        pc.PlayerInput.Class = mapping_schema(offset=999)
        with self.assertRaisesRegex(RuntimeError, 'schema'):
            NativeBindings(pc)
        pc = controller()
        adapter = NativeBindings(pc)
        pc.PlayerInput.EnhancedActionMappings.pop(4)
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            adapter.refresh(require_complete=True)
        adapter.refresh(require_complete=False)  # UI can omit gameplay actions.
        self.assertFalse(adapter.complete)
        pc.PlayerInput = S(EnhancedActionMappings=[])
        with self.assertRaisesRegex(RuntimeError, 'owner changed'):
            adapter.snapshot(pc)

    def test_complex_chord_does_not_silently_become_plain_key(self):
        pc = controller()
        pc.PlayerInput.EnhancedActionMappings[0].Triggers = [S(Class=S(Name='InputTriggerChordAction'))]
        with self.assertRaisesRegex(RuntimeError, 'Complex'):
            NativeBindings(pc).refresh(require_complete=True)

    def test_movement_uses_native_vector_not_velocity_or_device(self):
        self.assertFalse(movement_input_state({'X': 0, 'Y': 0})['movement_input_active'])
        self.assertEqual(movement_input_state({'X': .6, 'Y': .8})['movement_input_strength'], 1)
        with self.assertRaises(RuntimeError):
            movement_input_state({'X': math.nan, 'Y': 0})
        self.assertEqual(quat(struct.pack('<4d', 0, 0, 0, 1))['yaw'], 0)


class RestorationTests(unittest.TestCase):
    def test_ground_clips_restore_original_owner_after_runtime_changed(self):
        o, _ = session()
        
        def asset(name):
            return S(name=name, _path_name=lambda: name, Class=S(_path_name=lambda: 'AnimSequence'))
        forward, original, native = asset('forward'), asset('original'), asset('native')
        anim = S(left=S(Sequence=forward, AnimAssetKey=S(TagName='L')),
                 right=S(Sequence=native, AnimAssetKey=S(TagName='R')),
                 back=S(Sequence=forward, AnimAssetKey=S(TagName='B')))
        mesh = S(AnimScriptInstance=anim)
        pawn = S(Mesh=mesh)
        o.ground_clip_anim_ref = lambda: anim
        o.ground_clip_pawn_ref = lambda: pawn
        o.ground_clip_mesh_ref = lambda: mesh
        o.ground_clip_forward_ref = lambda: forward
        o.ground_clip_originals = [('left', 'L', lambda: original, 'original'),
                                  ('right', 'R', lambda: original, 'original'), ('back', 'B', None, None)]
        def changed_runtime():
            raise RuntimeError('New vehicle owner')
        o.bound = changed_runtime
        o.restore_ground_clips()
        self.assertIs(anim.left.Sequence, original)
        self.assertIs(anim.right.Sequence, native)
        self.assertIsNone(anim.back.Sequence)
        self.assertFalse(o.ground_clip_originals)
        self.assertEqual(len(o.report['ground_clip_native_replacements']), 1)

    def test_changed_or_expired_saved_mesh_is_rejected(self):
        o, _ = session()
        anim = S(name='original')
        mesh = S(AnimScriptInstance=S(name='changed'))
        pawn = S(Mesh=mesh)
        o.ground_clip_anim_ref = lambda: anim
        o.ground_clip_pawn_ref = lambda: pawn
        o.ground_clip_mesh_ref = lambda: mesh
        with self.assertRaisesRegex(RuntimeError, 'ownership changed'):
            o.ground_clip_anim()
        o.ground_clip_pawn_ref = lambda: None
        with self.assertRaisesRegex(RuntimeError, 'expired'):
            o.ground_clip_anim()

    def test_complete_finish_attempts_independent_native_cleanup_on_clip_failure(self):
        o, subscriptions = session()
        o.active = True
        o.registered = True
        subscriptions.add(o.spec)
        stopped = []
        for owner in o.owners():
            owner.stop = lambda owner=owner: (stopped.append(owner), setattr(owner, 'hook', None))
        def fail_clip():
            raise RuntimeError('Deliberate clip failure')
        o.restore_ground_clips = fail_clip
        with self.assertRaisesRegex(RuntimeError, 'clip failure'):
            o.finish('FAILED')
        self.assertFalse(o.active)
        self.assertTrue(all(owner in stopped for owner in o.owners()))
        self.assertFalse(subscriptions)

    def test_native_stop_failure_is_counted_and_retry_cleans_remaining_owner(self):
        o, subscriptions = session()
        o.active = True
        o.registered = True
        subscriptions.add(o.spec)
        owners = list(o.owners())
        failed = owners[0]
        failed.hook = object()
        stopped = []
        for owner in owners:
            owner.stop = lambda owner=owner: (stopped.append(owner), setattr(owner, 'hook', None))
        def fail_native():
            raise RuntimeError('Deliberate native stop failure')
        failed.stop = fail_native
        with self.assertRaisesRegex(RuntimeError, 'native stop failure'):
            o.finish('FAILED')
        self.assertFalse(subscriptions)
        self.assertFalse(o.active)
        self.assertEqual(o.report['native_patches'], 1)
        self.assertEqual(o.report['sdk_hooks'], 0)
        self.assertFalse(o.report['cleanup_complete'])
        self.assertTrue(all(owner in stopped for owner in owners[1:]))
        self.assertEqual(o.control[0], 0)
        self.assertEqual(o.vector_trace.control[7], 0)
        failed.stop = lambda: setattr(failed, 'hook', None)
        o.finish('USER_STOP')
        self.assertTrue(o.report['cleanup_complete'])
        self.assertEqual(o.report['native_patches'], 0)

    def test_clean_manual_stop_has_no_remaining_hooks(self):
        o, subscriptions = session()
        o.active = True
        o.registered = True
        subscriptions.add(o.spec)
        for owner in o.owners():
            owner.stop = lambda owner=owner: setattr(owner, 'hook', None)
        o.finish('USER_STOP')
        self.assertFalse(o.active)
        self.assertFalse(subscriptions)
        self.assertEqual(o.report['status'], 'USER_STOP')
        self.assertTrue(o.report['cleanup_complete'])
        self.assertEqual(o.report['native_patches'], 0)
        self.assertEqual(o.report['sdk_hooks'], 0)

    def test_supervisor_persists_cleanup_failure_and_removes_subscriptions(self):
        o, _ = session()
        state = LifecycleSupervisor(o.mod, o.updates)
        state.active = True
        state.child = o
        o.active = True
        o.report['native_patches'] = 2
        state.registered = [('lifecycle',)]
        subscriptions = {('lifecycle',)}
        state.updates.has_hook = lambda *args: args in subscriptions
        state.updates.remove_hook = lambda *args: subscriptions.discard(args)
        def failure(reason):
            raise RuntimeError('Native cleanup failed')
        state.retire = failure
        with tempfile.TemporaryDirectory() as directory:
            state.path = Path(directory) / 'report.json'
            with self.assertRaises(RuntimeError):
                state.finish('FAILED')
            report = json.loads(state.path.read_text())
        self.assertEqual(report['status'], 'CLEANUP_INCOMPLETE')
        self.assertEqual(report['native_patches'], 2)
        self.assertFalse(report['cleanup_complete'])
        self.assertFalse(o.active)
        self.assertFalse(subscriptions)
        self.assertIs(getattr(o.mod, KEY), state)

    def test_waiting_events_are_transitions_not_per_frame_spam(self):
        o, _ = session()
        state = LifecycleSupervisor(o.mod, o.updates)
        for _ in range(500):
            state.event('WAITING_RUNTIME')
        self.assertEqual(len(state.report['events']), 1)
        state.event('VERIFY_ON_FOOT_BINDINGS', objects=['0x1'])
        self.assertEqual(len(state.report['events']), 2)


class SourceAuditTests(unittest.TestCase):
    def test_every_referenced_global_has_a_module_binding(self):
        import builtins
        import symtable
        for file in OMNI.rglob('*.py'):
            table = symtable.symtable(file.read_text(), str(file), 'exec')
            defined = set(table.get_identifiers()) | set(dir(builtins)) | {
                '__file__', '__name__', '__package__', '__loader__', '__spec__', '__builtins__'}
            def check(scope):
                for symbol in scope.get_symbols():
                    if symbol.is_global() and symbol.is_referenced():
                        self.assertIn(symbol.get_name(), defined,
                                      (file.name, scope.get_name(), symbol.get_name()))
                for child in scope.get_children():
                    check(child)
            check(table)

    def test_audited_native_entities_match_original_v3(self):
        audit = json.loads((ROOT / 'docs/omni/native_audit.json').read_text())
        entities = {}
        for file in ('native_rotation.py', 'native_movement.py'):
            for node in ast.parse((OMNI / file).read_text()).body:
                if isinstance(node, ast.ClassDef):
                    entities[node.name] = node
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            entities[target.id] = node
        for name, expected in audit.items():
            # Python 3.13 hides empty fields in ast.dump; the V3 audit was hashed with them.
            options = {'show_empty': True} if sys.version_info >= (3, 13) else {}
            digest = hashlib.sha256(ast.dump(entities[name], **options).encode()).hexdigest()
            self.assertEqual(digest, expected, name)

    def test_no_physical_input_defaults_and_no_hidden_probe_inheritance(self):
        forbidden = {'W', 'A', 'S', 'D', 'LeftShift', 'RightShift', 'SpaceBar', 'LeftControl',
                     'RightControl', 'LeftMouseButton', 'RightMouseButton', 'Gamepad_LeftThumbstick',
                     'Gamepad_FaceButton_Right', 'Gamepad_FaceButton_Bottom', 'Gamepad_LeftTriggerAxis',
                     'Gamepad_RightTriggerAxis', 'Gamepad_LeftX', 'Gamepad_LeftY'}
        for file in OMNI.rglob('*.py'):
            tree = ast.parse(file.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn(node.value, forbidden, (file.name, node.value))
                if isinstance(node, ast.ClassDef):
                    self.assertFalse(node.name.endswith('AB'), (file.name, node.name))
                if (isinstance(node, ast.Attribute) and node.attr in ('IsInputKeyDown', 'GetInputAnalogKeyState')):
                    self.assertEqual(file.name, 'inputs.py')


if __name__ == '__main__':
    unittest.main()


