"""Profiler arithmetic, opt-in ownership, F10 routing and cleanup; no FPS proof."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as S
from unittest.mock import patch
import unittest
import subprocess
import sys

import support
from BL4ThirdPersonPOC.omni import profiler
from BL4ThirdPersonPOC.omni.common import KEY
from BL4ThirdPersonPOC.omni.sampling import SamplingMixin


class ProfilerTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.owner = S(MOD_VERSION='0.3.9.34', SETTINGS_DIR=self.directory.name,
                       logging=support.sdk.logging, _native_read=lambda address, size: bytes(size),
                       _get_runtime=lambda: (None, None, None))
        self.sample = dict(normal_tps_sample=True, movement_input_active=False, horizontal_speed=0.)
        self.child = S(active=True, frames=100, report=dict(samples=[self.sample],
                        lifecycle_session_sequence=1, native_patches=8),
                       bound=lambda: (S(bShowMouseCursor=False), S(),
                            S(GetActorCameraMode=lambda pawn: 'ThirdPerson'), S()))
        self.state = S(active=True, child=self.child, sequence=1, diagnostics=False,
                       updates=S(is_game_thread=lambda: True))
        setattr(self.owner, KEY, self.state)
        self.addCleanup(self.clean)

    def clean(self):
        profiler.cancel(self.owner, 'TEST_CLEANUP')
        profiler._armed = profiler._active = profiler._last = None

    def start(self, mode='total', limit=60):
        profiler.arm(self.owner, mode, 'idle', limit)
        self.assertTrue(profiler.trigger(self.owner))
        self.assertEqual(profiler.status(self.owner)['state'], 'running')
        return profiler._active

    def test_idle_f10_is_not_consumed_or_timed(self):
        self.assertFalse(profiler.trigger(self.owner))
        class Session:
            mod = self.owner
            active = True
            @profiler.root_span('callback.gameplay')
            def frame(self, value):
                return value + 1
        with patch.object(profiler, 'perf_counter_ns', side_effect=AssertionError('disabled timer')):
            self.assertEqual(Session().frame(4), 5)

    def test_nested_scopes_subtract_child_time_without_double_counting(self):
        capture = self.start()
        with patch.object(profiler, 'perf_counter_ns', side_effect=[0, 10000, 20000, 30000]):
            result = capture.measure('parent', lambda: capture.measure('child', lambda: 7))
        self.assertEqual(result, 7)
        self.assertEqual(capture.costs['parent'].inclusive_ns, 30000)
        self.assertEqual(capture.costs['parent'].exclusive_ns, 20000)
        self.assertEqual(capture.costs['child'].exclusive_ns, 10000)

    def test_exception_returns_original_error_and_keeps_stack_balanced(self):
        capture = self.start()
        with self.assertRaisesRegex(RuntimeError, 'gameplay error'):
            capture.measure('test', lambda: (_ for _ in ()).throw(RuntimeError('gameplay error')))
        self.assertEqual(capture.stack, [])
        self.assertEqual(capture.costs['test'].exceptions, 1)

    def test_update_limit_saves_bounded_report_and_deactivates(self):
        capture = self.start()
        for _ in range(60):
            capture.measure('callback.gameplay', lambda session: None, self.child)
        self.assertIsNone(profiler._active)
        report = json.loads(Path(profiler._last['path']).read_text())
        self.assertEqual(report['completed_updates'], 60)
        self.assertEqual(report['update_intervals']['count'], 59)
        self.assertFalse(report['partial'])
        self.assertEqual(report['states'], {'idle': 60})
        self.assertEqual(report['sdk_hooks_added'], 0)
        self.assertEqual(report['native_patches_added'], 0)
        self.assertEqual(report['game_writes_added'], 0)
        self.assertNotIn('fps', report['update_intervals'])

    def test_detail_restores_class_methods_and_module_functions_exactly(self):
        original = SamplingMixin.bound
        read, runtime = self.owner._native_read, self.owner._get_runtime
        capture = self.start('detail')
        self.assertIsNot(SamplingMixin.bound, original)
        self.assertIsNot(self.owner._native_read, read)
        capture.measure('test', lambda: self.owner._native_read(0x10000, size=8))
        self.assertEqual(capture.native_read_calls, 1)
        self.assertEqual(capture.native_read_bytes, 8)
        # Other mod work outside Omni's root is neither timed nor counted.
        self.owner._native_read(0x10000, 8)
        self.assertEqual(capture.native_read_calls, 1)
        profiler.cancel(self.owner)
        self.assertIs(SamplingMixin.bound, original)
        self.assertIs(self.owner._native_read, read)
        self.assertIs(self.owner._get_runtime, runtime)

    def test_other_thread_and_owner_bypass_measurement(self):
        capture = self.start()
        class Session:
            mod = self.owner
            active = True
            report = self.child.report
            @profiler.root_span('callback.gameplay')
            def frame(self):
                return 'ok'
        with patch.object(profiler.threading, 'get_ident', return_value=capture.thread + 1):
            self.assertEqual(Session().frame(), 'ok')
        session = Session()
        session.mod = S()
        self.assertEqual(session.frame(), 'ok')
        self.assertEqual(capture.costs, {})

    def test_cancel_inside_scope_is_deferred_until_original_returns(self):
        capture = self.start('detail')
        patched = SamplingMixin.bound
        def stop():
            profiler.cancel(self.owner, 'SESSION_RETIRED_TEST')
            self.assertIs(profiler._active, capture)
            self.assertIs(SamplingMixin.bound, patched)
            return 9
        self.assertEqual(capture.measure('test', stop), 9)
        self.assertIsNone(profiler._active)
        self.assertIsNot(SamplingMixin.bound, patched)
        self.assertEqual(profiler._last['stop_reason'], 'SESSION_RETIRED_TEST')

    def test_restore_does_not_overwrite_foreign_replacement(self):
        capture = self.start()
        original = self.owner._get_runtime
        capture.patch(self.owner, '_get_runtime', 'runtime')
        other = lambda: 'another owner'
        self.owner._get_runtime = other
        profiler.cancel(self.owner)
        self.assertIs(self.owner._get_runtime, other)
        self.assertFalse(profiler._last['restored'])
        self.owner._get_runtime = original

    def test_install_failure_restores_partial_wrappers_and_preserves_arm(self):
        original = SamplingMixin.bound
        def fail(capture):
            capture.patch(SamplingMixin, 'bound', 'bound')
            raise RuntimeError('install failure')
        profiler.arm(self.owner, 'detail')
        with patch.object(profiler.Capture, 'install_detail', fail):
            self.assertTrue(profiler.trigger(self.owner))
        self.assertIs(SamplingMixin.bound, original)
        self.assertIsNone(profiler._active)
        self.assertEqual(profiler.status(self.owner)['state'], 'armed')

    def test_file_write_failure_restores_first_and_is_reported(self):
        capture = self.start('detail')
        with patch.object(Path, 'write_text', side_effect=OSError('disk error')):
            profiler.cancel(self.owner)
        self.assertIsNone(profiler._active)
        self.assertEqual(capture.patches, [])
        self.assertIn('disk error', profiler._last['save_error'])

    def test_second_f10_stops_early_and_normal_behavior_returns(self):
        self.start()
        self.assertTrue(profiler.trigger(self.owner))
        self.assertEqual(profiler._last['stop_reason'], 'F10_MANUAL_STOP')
        self.assertTrue(profiler._last['partial'])
        self.assertFalse(profiler.trigger(self.owner))

    def test_arming_does_not_install_wrappers_or_start_clock_capture(self):
        original = SamplingMixin.bound
        with patch.object(profiler, 'perf_counter_ns', side_effect=AssertionError('arm timer')):
            profiler.arm(self.owner, 'detail')
        self.assertIs(SamplingMixin.bound, original)
        self.assertIsNone(profiler._active)

    def test_missing_runtime_wrong_thread_and_bad_labels_are_refused(self):
        for label in ('../bad', '', 'x' * 33, '😅'):
            with self.assertRaises(ValueError):
                profiler.arm(self.owner, 'total', label)
        profiler.arm(self.owner, 'total')
        self.state.updates.is_game_thread = lambda: False
        self.assertTrue(profiler.trigger(self.owner))
        self.assertIsNone(profiler._active)
        self.state.updates.is_game_thread = lambda: True
        self.state.child = None
        self.assertTrue(profiler.trigger(self.owner))
        self.assertIsNone(profiler._active)

    def test_exact_distribution_and_zero_updates_are_finite(self):
        self.assertEqual(profiler.distribution([3000000, 1000000, 2000000])['p95_ms'], 3.)
        self.assertEqual(profiler.distribution([])['count'], 0)
        self.assertEqual(profiler.Cost().export(0)['inclusive_ms_per_update'], 0.)

    def test_actual_loader_console_f10_and_gameplay_root(self):
        script = Path(__file__).with_name('omni_profiler_loader_scenario.py')
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(version='0.3.9.38', updates=600, restored=True))


if __name__ == '__main__':
    unittest.main()
