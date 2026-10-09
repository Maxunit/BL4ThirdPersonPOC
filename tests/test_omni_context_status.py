"""Throwable contexts and fail-closed lifecycle status regressions."""
import unittest
from types import SimpleNamespace as S

import support
from BL4ThirdPersonPOC import omni
from BL4ThirdPersonPOC.input_bindings import NativeBindings
from BL4ThirdPersonPOC.omni.common import KEY


class ContextStatusTests(unittest.TestCase):
    def tearDown(self):
        omni._last_failure['reason'] = None

    def test_zoom_disappears_and_returns_without_stale_intent(self):
        pc = support.controller()
        reader = NativeBindings(pc)
        reader.refresh(require_complete=True)
        zoom = pc.PlayerInput.EnhancedActionMappings.pop()
        pc.pressed.add(str(zoom.Key.KeyName))
        reader.maybe_refresh(require_complete=True)
        self.assertFalse(reader.snapshot(pc)['zoom'])
        self.assertTrue(reader.complete)
        pc.PlayerInput.EnhancedActionMappings.append(zoom)
        reader.maybe_refresh(require_complete=True)
        self.assertTrue(reader.snapshot(pc)['zoom'])

    def test_successful_error_cleanup_retains_reason_until_explicit_off(self):
        from BL4ThirdPersonPOC.omni.lifecycle import LifecycleSupervisor
        owner = S(FIRST_PERSON_ANIM_HOOK='widget', CLIENT_RESTART_FUNCTION='restart')
        subscriptions = set()
        updates = S(has_hook=lambda *args: args in subscriptions,
                    remove_hook=lambda *args: subscriptions.discard(args),
                    add_hook=lambda *args: subscriptions.add(args[:-1]))
        state = LifecycleSupervisor(owner, updates)
        setattr(owner, KEY, state)
        state.fail('widget_pre', RuntimeError('test failure'))
        self.assertFalse(omni.is_running(owner))
        self.assertTrue(omni.stopped_after_failure(owner))
        self.assertIn('test failure', omni.status(owner)['last_failure'])
        self.assertFalse(omni.status(owner)['cleanup_pending'])
        self.assertTrue(omni.shutdown(owner))
        self.assertFalse(omni.stopped_after_failure(owner))

    def test_inactive_retained_state_blocks_restart(self):
        state = S(active=False)
        owner = S(**{KEY: state})
        omni.record_failure('cleanup', RuntimeError('still owned'))
        self.assertFalse(omni.is_running(owner))
        self.assertTrue(omni.stopped_after_failure(owner))
        self.assertFalse(omni.start(owner))
        self.assertIs(getattr(owner, KEY), state)


