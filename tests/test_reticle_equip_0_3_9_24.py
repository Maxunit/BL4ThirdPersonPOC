"""Reticle invalidation in the native equip body, after an ADS entry publish.

This models a missing lifecycle order in .23, not a claim about live HUD output.
The production entry/equip hooks are real; the model publisher is substituted.
"""
from types import SimpleNamespace as S
import unittest

import support
import test_ads_refactor_0_3_9_23 as ads_tests
from BL4ThirdPersonPOC import ads_handoff, ads_events


class ReticleEquipTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ads_tests.ADSRefactorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(self.fixture.doCleanups)
        self.mod = self.fixture.mod
        self.visible = True
        self.native_ready = True
        self.publications = []
        self.mod._reticle_publish_pending = False
        self.mod._reticle_publisher = object()
        self.mod._reticle_publish_faulted = False
        self.mod._reticle_gate_last_fail = ""
        self.mod._reticle_publish_counts = {}
        self.mod.logging = support.sdk.logging
        self.mod._publish_tps_reticle = self.publish
        self.mod._request_tps_reticle_publish = self.request
        self.mod._arm_late_tps_ads_equip_handoff = lambda obj, args: (
            ads_handoff._arm_late_tps_ads_equip_handoff_impl(obj, args, owner_module=self.mod))
        raw = bytearray(0x3E)
        raw[0] = 1
        raw[0x36] = 2
        self.mod._native_read = lambda address, size: bytes(raw) if self.native_ready else bytes(0x3E)

    def request(self, reason):
        return ads_handoff._request_tps_reticle_publish_impl(reason, owner_module=self.mod)

    def publish(self, reason):
        if not self.native_ready:
            return 'gate_skipped'
        result = 'already_visible' if self.visible else 'published'
        self.visible = True
        self.publications.append((reason, result))
        return result

    def pre(self, weapon=None, collector=None):
        ads_handoff._hybrid_ads_weapon_equipped_pre_hook_impl(
            collector or self.fixture.collector,
            S(EventWeapon=weapon or self.fixture.camera.CameraModeInputs.Weapon),
            None, None, owner_module=self.mod)

    def post(self, weapon=None, collector=None):
        ads_handoff._hybrid_ads_weapon_equipped_post_hook_impl(
            collector or self.fixture.collector,
            S(EventWeapon=weapon or self.fixture.camera.CameraModeInputs.Weapon),
            None, None, owner_module=self.mod)

    def resume_mid_swap(self):
        f = self.fixture
        f.enter()
        f.observe(3)
        f.camera.CameraModeInputs.Weapon = S(address=0x60, category='pistol', CurrentState='Active')
        # First callback is already finished while presentation was released.
        self.pre()
        self.post()
        f.observe(1)
        self.assertTrue(self.visible)
        self.assertFalse(self.mod._reticle_publish_pending)

    def test_remaining_equip_post_republishes_after_native_body_hides_model(self):
        self.resume_mid_swap()
        self.pre()
        self.visible = False  # native OnWeaponEquipped body invalidates the old model
        self.post()
        self.assertTrue(self.visible, 'Remaining callback must republish; no second pair follows')
        self.assertEqual(self.mod._ads_handoff['equip_ordinal'], 1)
        self.assertFalse(self.mod._ads_handoff['reticle_rebind_active'])

    def test_ads_entry_inside_equip_body_can_be_adopted_by_post(self):
        f = self.fixture
        f.enter()
        f.observe(3)
        f.camera.CameraModeInputs.Weapon = S(address=0x60, category='pistol', CurrentState='Active')
        self.pre()  # ADS is inactive here; PRE cannot arm the new identity
        f.observe(1)  # native callback resumes zoom and its notification starts Mod ADS
        self.visible = False  # later code in the same native equip body hides the model
        self.post()
        self.assertTrue(self.visible)

    def test_later_post_is_not_ignored_when_pair_counter_is_already_two(self):
        self.fixture.enter()
        self.mod._ads_handoff.update(incoming_weapon=self.fixture.weapon.address,
            collector_address=self.fixture.collector.address, equip_ordinal=2)
        self.visible = False
        self.post()
        self.assertTrue(self.visible)
        self.assertEqual(self.mod._ads_handoff['equip_ordinal'], 2)

    def test_foreign_weapon_or_collector_cannot_publish(self):
        self.fixture.enter()
        self.visible = False
        self.post(weapon=S(address=0x99))
        self.post(collector=S(address=0x99))
        self.assertFalse(self.visible)

    def test_changed_camera_cannot_publish_from_old_ads_identity(self):
        self.fixture.enter()
        self.fixture.camera.address = 0x31
        self.visible = False
        self.post()
        self.assertFalse(self.visible)

    def test_fps_route_cannot_publish_tps_reticle(self):
        self.fixture.weapon.category = 'sniper_rifle'
        self.fixture.enter()
        self.visible = False
        self.post()
        self.assertFalse(self.visible)

    def test_native_exit_does_not_force_a_reticle(self):
        self.fixture.enter()
        self.fixture.observe(3)
        self.visible = False
        self.post()
        self.assertFalse(self.visible)

    def test_transient_not_ready_post_waits_for_changed_weapon_readiness(self):
        self.resume_mid_swap()
        self.pre()
        self.visible = False
        self.native_ready = False
        self.post()
        self.assertTrue(self.mod._reticle_publish_pending)
        self.mod._ads_tps_state['transition'] = None
        ads_handoff._update_pending_tps_reticle_impl(owner_module=self.mod)
        self.assertFalse(self.visible)
        self.native_ready = True
        ads_handoff._update_pending_tps_reticle_impl(owner_module=self.mod)
        self.assertTrue(self.visible)


if __name__ == '__main__':
    unittest.main()
