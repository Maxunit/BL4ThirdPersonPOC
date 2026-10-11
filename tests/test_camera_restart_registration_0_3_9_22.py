"""SDK collection-append regression: register/dispatch/remove real camera hooks."""
import ast
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as S
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SDK:
    Type = S(PRE='pre', POST='post')
    def __init__(self):
        self.hooks = {}
        self.refuse = None
        self.throw = None
        self.retain = set()
        self.spoof_success = None
    def add(self, path, kind, identifier, callback):
        if identifier == self.throw: raise RuntimeError('SDK registration exception')
        if identifier == self.refuse: return False
        if identifier == self.spoof_success: return True
        spec = (path,kind,identifier)
        if spec in self.hooks: return False
        # Matches unrealsdk collection append: inserts, then returns False.
        collection_exists = any(s[:2] == spec[:2] for s in self.hooks)
        self.hooks[spec] = callback
        return not collection_exists
    def has(self, *spec): return spec in self.hooks
    def remove(self, *spec):
        if spec[-1] not in self.retain: self.hooks.pop(spec,None)
        return False  # Removal must also be checked through has_hook.


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.sdk, self.log = SDK(), []
        tree = ast.parse((ROOT/'BL4ThirdPersonPOC/camera_events.py').read_text())
        funcs = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in
                 ('_install_camera_lifecycle_hook_impl','_remove_camera_lifecycle_hook_impl')]
        self.ns = dict(Type=self.sdk.Type,add_hook=self.sdk.add,has_hook=self.sdk.has,
            remove_hook=self.sdk.remove,logging=S(info=self.log.append,error=self.log.append,
                                                  warning=self.log.append))
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'camera_events.py','exec'),self.ns)
        self.mod = S(_camera_lifecycle_hook_installed=False,CLIENT_RESTART_FUNCTION='restart',
            CLIENT_RESTART_PRE_IDENTIFIER='camera.pre',CLIENT_RESTART_IDENTIFIER='camera.post',
            _client_restart_pre_hook=lambda *args:None,_client_restart_post_hook=lambda *args:None)
        self.mod._remove_camera_lifecycle_hook = self.remove
    def install(self): self.ns['_install_camera_lifecycle_hook_impl'](owner_module=self.mod)
    def remove(self): self.ns['_remove_camera_lifecycle_hook_impl'](owner_module=self.mod)
    def seed(self):
        self.sdk.hooks[('restart','pre','omni.restart_pre')] = object()
        self.sdk.hooks[('restart','post','another.post')] = object()
    def test_false_append_return_registers_both_and_preserves_other_owners(self):
        self.seed()
        foreign = dict(self.sdk.hooks)
        self.install()
        self.assertTrue(self.mod._camera_lifecycle_hook_installed)
        self.assertIs(self.sdk.hooks[('restart','pre','camera.pre')],self.mod._client_restart_pre_hook)
        self.assertIs(self.sdk.hooks[('restart','post','camera.post')],self.mod._client_restart_post_hook)
        self.assertTrue(any('pre_return=False post_return=False' in m for m in self.log))
        self.remove()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,foreign)
    def test_empty_collection_and_reinstallation(self):
        self.install()
        self.install()
        self.assertTrue(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(len(self.sdk.hooks),2)
        self.remove()
        self.assertEqual(self.sdk.hooks,{})
    def test_real_pre_refusal_does_not_install_post(self):
        self.seed()
        foreign = dict(self.sdk.hooks)
        self.sdk.refuse = 'camera.pre'
        self.install()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,foreign)
    def test_real_post_refusal_removes_partial_pre(self):
        self.seed()
        foreign = dict(self.sdk.hooks)
        self.sdk.refuse = 'camera.post'
        self.install()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,foreign)
    def test_registration_exception_cleans_up_partial_hooks(self):
        self.sdk.throw = 'camera.post'
        self.install()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,{})
    def test_true_return_without_registration_is_refused(self):
        self.sdk.spoof_success = 'camera.pre'
        self.install()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,{})
    def test_failed_partial_cleanup_retains_tracking_and_retry(self):
        self.sdk.refuse = 'camera.post'
        self.sdk.retain.add('camera.pre')
        self.install()
        self.assertTrue(self.mod._camera_lifecycle_hook_installed)
        self.assertTrue(self.sdk.has('restart','pre','camera.pre'))
        self.sdk.retain.clear()
        self.remove()
        self.assertFalse(self.mod._camera_lifecycle_hook_installed)
        self.assertEqual(self.sdk.hooks,{})
    def test_silent_removal_failure_prevents_reinstallation(self):
        self.install()
        original = self.sdk.hooks[('restart','pre','camera.pre')]
        self.sdk.retain.add('camera.pre')
        self.remove()
        self.assertTrue(self.mod._camera_lifecycle_hook_installed)
        self.install()
        self.assertIs(self.sdk.hooks[('restart','pre','camera.pre')],original)
        self.assertNotIn(('restart','post','camera.post'),self.sdk.hooks)
    def test_stale_untracked_registration_must_be_removed_before_add(self):
        stale = object()
        self.sdk.hooks[('restart','pre','camera.pre')] = stale
        self.sdk.retain.add('camera.pre')
        self.install()
        self.assertTrue(self.mod._camera_lifecycle_hook_installed)
        self.assertIs(self.sdk.hooks[('restart','pre','camera.pre')],stale)
        self.assertNotIn(('restart','post','camera.post'),self.sdk.hooks)
        self.assertTrue(any('Existing ClientRestart hook removal unverified' in m for m in self.log))


class LoaderRegressionTests(unittest.TestCase):
    def test_real_loader_dispatch_and_disable_after_false_sdk_append(self):
        script = r'''
import json
from types import SimpleNamespace as S
import loader_harness as h
m=h.load()
h.set_build(True)
h.enable_entry_points(m)
m._on_enable()
h.bind_game_thread(m)
original_runtime=m._get_runtime
from BL4ThirdPersonPOC import camera_events as c
m._remove_camera_lifecycle_hook()
path=m.CLIENT_RESTART_FUNCTION
foreign=(path,h.Type.PRE,'test.foreign.restart')
h.HOOKS[foreign]=lambda *args:None
old_add=c.add_hook
def appended(*args):
    old_add(*args)
    return False
c.add_hook=appended
m._install_camera_lifecycle_hook()
assert m._camera_lifecycle_hook_installed
pre=(path,h.Type.PRE,m.CLIENT_RESTART_PRE_IDENTIFIER)
post=(path,h.Type.POST,m.CLIENT_RESTART_IDENTIFIER)
assert pre in h.HOOKS and post in h.HOOKS
pc=S(_get_address=lambda:0x3000)
pawn=S(Class=S(Name='OakCharacter'),_get_address=lambda:0x1000)
manager=S(_get_address=lambda:0x2000)
m._get_runtime=lambda:(pc,pawn,manager)
m._third_person_enabled=True
m._is_vehicle_camera_view=lambda:False
m._vehicle_camera_active=False
m._native_active=lambda:False
m._active_native_state.clear()
m._ads_active=False
m._ads_route='hip'
h.HOOKS[pre](pc,S(NewPawn=pawn),None,None)
h.HOOKS[post](pc,S(NewPawn=pawn),None,None)
assert m._camera_lifecycle['restart_calls']==1
assert m._camera_lifecycle['local_restarts']==1
assert m._camera_lifecycle['pending']
assert m._camera_lifecycle['reason']=='client_restart'
assert m._camera_lifecycle['expected_pawn']==0x1000
m._get_runtime=original_runtime
m._third_person_enabled=False
m._on_disable()
assert pre not in h.HOOKS and post not in h.HOOKS
assert foreign in h.HOOKS
print('RESULT='+json.dumps(dict(dispatched=True,cleanup=True)))
'''
        run=subprocess.run([sys.executable,'-c',script],cwd=ROOT/'tests',capture_output=True,
                           text=True,timeout=30)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)
        self.assertIn('"dispatched": true',run.stdout)


if __name__ == '__main__': unittest.main()
