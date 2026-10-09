"""Owned FKey regressions; SDK substitutes cannot confirm BL4 native behavior."""
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
from BL4ThirdPersonPOC.input_bindings import NativeBindings


class BorrowedKey:
    """A mapping view whose backing storage can become invalid between ticks."""
    def __init__(self, name):
        self.KeyName = name
        self.valid = True

    def __copy__(self):
        # SDK WrappedStruct.__copy__ produces separate Python-owned storage.
        return S(KeyName=self.KeyName, valid=True)


class InputKeyOwnershipTests(unittest.TestCase):
    def setup_reader(self):
        pc = support.controller()
        row = support.mapping('Action_Carry_Throw', 'UserCarry')
        row.Key = BorrowedKey('UserCarry')
        pc.PlayerInput.EnhancedActionMappings.append(row)
        reader = NativeBindings(pc)
        reader.refresh(require_complete=True)
        return pc, row, reader

    def test_expired_mapping_view_cannot_suppress_owned_carry_press(self):
        pc, row, reader = self.setup_reader()
        pc.IsInputKeyDown = lambda key: bool(getattr(key, 'valid', True)) and str(key.KeyName) in pc.pressed
        row.Key.valid = False
        row.Key = BorrowedKey('UserCarry')  # same mapping count and action/key name
        pc.pressed.add('UserCarry')
        reader.begin_frame()
        self.assertTrue(reader.snapshot(pc)['carry_throw'])
        self.assertEqual(reader.refresh_count, 1)
        self.assertTrue(reader.bindings['carry_throw'][0].valid)

    def test_owned_analog_mapping_and_once_per_callback_cache(self):
        pc, row, reader = self.setup_reader()
        pc.GetInputAnalogKeyState = lambda key: .8 if str(key.KeyName) == 'UserCarry' and key.valid else 0.
        row.Key.valid = False
        reader.begin_frame()
        self.assertTrue(reader.snapshot(pc)['carry_throw'])
        pc.GetInputAnalogKeyState = lambda key: 0.
        self.assertTrue(reader.snapshot(pc)['carry_throw'])
        reader.begin_frame()
        self.assertFalse(reader.snapshot(pc)['carry_throw'])

    def test_same_count_user_remap_replaces_owned_binding_at_refresh(self):
        pc, row, reader = self.setup_reader()
        before = reader.revision
        row.Key.KeyName = 'NewUserCarry'
        self.assertEqual(reader.metadata()['bound_keys']['carry_throw'], ['UserCarry'])
        reader.refresh(require_complete=True)
        pc.pressed.add('NewUserCarry')
        self.assertTrue(reader.snapshot(pc)['carry_throw'])
        self.assertEqual(reader.revision, before + 1)
        self.assertEqual(reader.metadata()['bound_keys']['carry_throw'], ['NewUserCarry'])

    def test_copy_failure_cannot_publish_partially_replaced_bindings(self):
        pc, row, reader = self.setup_reader()
        previous = reader.bindings
        with patch('BL4ThirdPersonPOC.input_bindings.copy', side_effect=RuntimeError('SDK copy failed')):
            with self.assertRaisesRegex(RuntimeError, 'SDK copy failed'):
                reader.refresh(require_complete=True)
        self.assertIs(reader.bindings, previous)

    def test_alias_or_changed_name_copy_is_refused(self):
        pc, row, reader = self.setup_reader()
        for substitute in (lambda key: key, lambda key: S(KeyName='Unexpected')):
            with patch('BL4ThirdPersonPOC.input_bindings.copy', substitute):
                with self.assertRaisesRegex(RuntimeError, 'Configured key copy differs'):
                    reader.refresh(require_complete=True)

    def test_ignored_mapping_does_not_produce_owned_throw_binding(self):
        pc, row, reader = self.setup_reader()
        row.bShouldBeIgnored = True
        reader.refresh(require_complete=True)
        pc.pressed.add('UserCarry')
        self.assertIn('carry_throw', reader.present_roles)
        self.assertEqual(reader.bindings['carry_throw'], [])
        self.assertFalse(reader.snapshot(pc)['carry_throw'])


if __name__ == '__main__':
    unittest.main()
