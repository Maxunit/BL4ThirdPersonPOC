"""Native/input order regressions through real ADS preparation and FOV routing.

The SDK camera/native writer are substitutes. ZoomState rejects every mod write;
the native() method alone simulates the game's committed states. These tests do
not claim Windows/native calling conventions or visual gameplay validation.
"""
import ast
import json
from functools import partial
from pathlib import Path
import time
import subprocess
import sys
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import support
from BL4ThirdPersonPOC import ads_control, ads_events, ads_handoff, camera_math, hybrid_ads


class NativeZoom:
    def __init__(self):
        object.__setattr__(self, "values", dict(State=0, Level=0, bWantsToZoom=False,
                                               bPendingZoom=False, bTickingZoom=False))
        object.__setattr__(self, "writes", [])

    def __getattr__(self, name):
        return self.values[name]

    def __setattr__(self, name, value):
        self.writes.append((name, value))
        raise AssertionError("Mod attempted to write native zoom")

    def native(self, state, **flags):
        self.values.update(State=state, **flags)


class ADSRefactorTests(unittest.TestCase):
    def setUp(self):
        hybrid_ads.reset()
        self.addCleanup(hybrid_ads.reset)
        self.pc = S(address=0x10)
        self.zoom = NativeZoom()
        self.pawn = S(address=0x20, ZoomState=self.zoom)
        self.weapon = S(address=0x40, category="pistol", CurrentState="Active")
        self.collector = S(address=0x50)
        self.camera = S(address=0x30, CameraModeInputs=S(Weapon=self.weapon),
                        CameraCachePrivate=S(POV=S(FOV=90.)), mode="ThirdPerson",
                        CameraModeState=S(BaseFOVOffset=0., bIsTransitioning=False,
                                          bIsColliding=False, bShowViewModel=False))
        self.camera_calls = []
        def set_camera(pawn, mode, *args):
            self.camera_calls.append(mode)
            self.camera.mode = mode
        self.camera.SetActorCameraMode = set_camera
        self.camera.GetActorCameraMode = lambda pawn: self.camera.mode
        self.published, self.errors = [], []
        m = self.mod = S(
            EInputEvent=S(IE_Pressed="press", IE_Released="release", IE_Repeat="repeat"),
            _third_person_enabled=True, _third_person_pushed=True,
            _vehicle_camera_active=False, _ladder_active=False, _shop_camera_active=False,
            _ads_active=False, _ads_route="hip", _ads_tps_state=None,
            _ads_collector_address=0, _ads_hooks_installed=list(range(6)),
            _reticle_publish_pending=False, _active_native_state={}, time=time,
            ADS_CAMERA_TRANSITION_TIME=.15, ADS_MIN_DURATION=.05, ADS_MAX_DURATION=2.,
            ADS_MIN_SAFE_FOV=5., ADS_MAX_SAFE_FOV=170.,
            _camera_feature_options={"global": S(value=1.), "categories": {}},
            omni_hybrid_ads=S(value=False), sniper_tps_ads=S(value=False),
            _beam_active=lambda: False, _native_active=lambda: False,
            _set_camera_offset=lambda *args: None, _apply_camera_offset=lambda: None,
            _ffyl_camera_active=lambda pawn, camera: False,
            _classify_ads_weapon=lambda w: (w.category, "test", "native-owned"),
            _find_ads_collector=lambda w: self.collector,
            _find_active_ads_sight=lambda w: (S(PuppetZoomFOVScale=.5, ZoomDuration=.15), 0, "Sight"),
            _request_tps_reticle_publish=self.published.append,
            _ads_debug_error=lambda stage, exc: self.errors.append((stage, str(exc))),
        )
        m._get_runtime = lambda: (self.pc, self.pawn, self.camera)
        m._ads_object_address = m._object_address = lambda obj: getattr(obj, "address", 0)
        for name in ("_ads_attribute_float", "_derive_ads_target_fov", "_read_live_ads_fov", "_ads_smoothstep"):
            setattr(m, name, getattr(camera_math, name))
        m._native_zoom_confirms_ads = camera_math._read_native_zoom_confirmation
        for module, names in (
            (ads_control, ("_clear_pending_ads_press", "_arm_pending_ads_press",
                           "_prepare_pending_ads_press", "_reconcile_pending_ads_press_weapon",
                           "_activate_confirmed_ads_press", "_note_weak_zoom_signal")),
            (ads_events, ("_start_hybrid_tps_ads", "_reverse_hybrid_tps_ads",
                          "_release_hybrid_tps_ads", "_finish_hybrid_tps_ads", "_cancel_hybrid_ads",
                          "_set_hybrid_tps_fov", "_begin_hybrid_ads_transition")),
            (ads_handoff, ("_cleanup_ads_handoff", "_update_hybrid_ads_weapon_handoff")),
        ):
            for name in names:
                setattr(m, name, partial(getattr(module, name + "_impl"), owner_module=m))
        ads_events._reset_hybrid_ads_debug_impl(owner_module=m)
        ads_handoff._reset_ads_handoff_debug_impl(owner_module=m)
        ads_control._reset_ads_press_intent_impl(owner_module=m)
        self.controller = m._ads_controller

    def tearDown(self):
        self.assertEqual(self.zoom.writes, [])
        self.assertEqual(self.errors, [])

    def press(self):
        ads_control._handle_first_person_ads_input_impl("press", owner_module=self.mod)

    def release(self):
        ads_control._handle_first_person_ads_input_impl("release", owner_module=self.mod)

    def observe(self, state, **flags):
        self.zoom.native(state, **flags)
        ads_control._update_pending_ads_press_impl(owner_module=self.mod)

    def enter(self):
        self.press()
        self.assertFalse(self.mod._ads_active)
        self.observe(1, bWantsToZoom=True, bPendingZoom=True, bTickingZoom=True)
        self.observe(2)
        self.assertTrue(self.mod._ads_active)

    def test_toggle_release_keeps_ads_until_native_exit(self):
        self.enter()
        offset = self.camera.CameraModeState.BaseFOVOffset
        self.release()
        self.assertFalse(self.mod._ads_handoff["held"])
        self.observe(2, bWantsToZoom=False)
        self.assertTrue(self.mod._ads_active)
        self.assertEqual(self.mod._ads_tps_state["phase"], "ads")
        self.assertEqual(self.camera.CameraModeState.BaseFOVOffset, offset)
        self.press()  # pre-dispatch native State is still the old State 2
        self.assertTrue(self.mod._ads_active)
        self.observe(3)
        self.assertFalse(self.mod._ads_active)
        self.assertEqual(self.mod._ads_tps_state["phase"], "released")

    def test_hold_release_waits_for_native_exit(self):
        self.enter()
        self.release()
        self.assertTrue(self.mod._ads_active)
        self.observe(3, bWantsToZoom=False)
        self.assertFalse(self.mod._ads_active)
        self.observe(0)
        self.assertEqual(self.controller.exits, 1)

    def test_stale_native_state_is_not_confirmed_in_input_callback(self):
        self.zoom.native(2)  # trace regression: old aim is about to toggle off
        self.press()
        self.assertFalse(self.mod._ads_active)
        self.assertEqual(self.controller.entries, 0)
        self.observe(3)
        self.observe(0)
        self.assertFalse(self.mod._ads_press_intent["pending"])
        self.assertFalse(self.mod._ads_active)

    def test_release_does_not_admit_old_native_state(self):
        self.press()
        self.zoom.native(2)
        self.release()
        self.assertFalse(self.mod._ads_active)
        self.assertFalse(self.mod._ads_press_intent["pending"])
        self.observe(0)
        self.assertEqual(self.controller.entries, 0)

    def test_toggle_short_tap_enters_after_release_on_native_confirmation(self):
        self.press()
        self.release()
        self.observe(2)
        self.assertTrue(self.mod._ads_active)
        self.assertFalse(self.mod._ads_handoff["held"])
        self.assertEqual(self.mod._ads_press_intent["presses"], 1)
        self.assertEqual(self.mod._ads_press_intent["native_entries_prepared"], 1)

    def test_held_swap_reenters_new_weapon_without_zoom_writes(self):
        self.enter()
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = None
        self.observe(0)
        self.assertFalse(self.mod._ads_active)
        self.assertTrue(self.mod._ads_handoff["held"])
        new = S(address=0x60, category="pistol", CurrentState="Active")
        self.camera.CameraModeInputs.Weapon = new
        self.observe(1)
        self.assertTrue(self.mod._ads_active)
        self.assertEqual(self.mod._ads_tps_state["weapon_address"], 0x60)
        self.assertEqual(self.controller.entries, 2)
        self.release()
        self.observe(2)  # Toggle can stay active after a held swap/release
        self.assertTrue(self.mod._ads_active)

    def test_toggle_unheld_swap_exits_and_stays_hip(self):
        self.enter()
        self.release()
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = S(address=0x60, category="pistol")
        self.observe(0)
        self.assertFalse(self.mod._ads_active)
        self.assertEqual(self.controller.entries, 1)

    def test_swap_resume_does_not_recalibrate_from_outgoing_ads_fov(self):
        self.enter()
        target = self.mod._ads_tps_state["target_fov"]
        self.camera.CameraCachePrivate.POV.FOV = target
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = S(address=0x60, category="pistol")
        self.observe(1)
        self.assertEqual(self.mod._ads_tps_state["base_fov"], 90.)
        self.assertEqual(self.mod._ads_tps_state["target_fov"], target)

    def test_scope_swap_resume_waits_for_native_camera_completion(self):
        self.weapon.category = "sniper_rifle"
        self.enter()
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = S(address=0x60, category="pistol")
        self.camera.CameraCachePrivate.POV.FOV = 30.
        self.camera.CameraModeState.bIsTransitioning = True
        self.observe(1)
        self.assertFalse(self.mod._ads_active)
        self.camera.CameraModeState.bIsTransitioning = False
        self.camera.CameraCachePrivate.POV.FOV = 90.
        self.observe(2)
        self.assertTrue(self.mod._ads_active)
        self.assertEqual(self.mod._ads_tps_state["base_fov"], 90.)

    def test_release_in_swap_gap_does_not_force_resume(self):
        self.enter()
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = None
        self.release()
        self.observe(0)
        self.camera.CameraModeInputs.Weapon = S(address=0x60, category="pistol")
        self.observe(0)
        self.assertFalse(self.mod._ads_active)

    def test_same_weapon_native_reentry_reverses_presentation(self):
        self.enter()
        self.observe(3)
        self.observe(1)
        self.assertTrue(self.mod._ads_active)
        self.assertEqual(self.mod._ads_tps_state["transition"]["kind"], "zoom_in_reversal")
        self.assertEqual(self.mod._ads_handoff["route_weapon"], self.weapon.address)

    def test_finishing_fov_exit_preserves_physical_hold(self):
        self.enter()
        self.observe(3)
        self.mod._finish_hybrid_tps_ads()
        self.assertEqual(self.mod._ads_route, "hip")
        self.assertTrue(self.mod._ads_handoff["held"])
        self.observe(1)
        self.assertTrue(self.mod._ads_active)

    def test_flags_in_idle_or_exit_are_not_ads_confirmation(self):
        for state in (0, 3):
            self.zoom.native(state, bWantsToZoom=255, bPendingZoom=255, bTickingZoom=True)
            self.assertFalse(camera_math._read_native_zoom_confirmation(self.pawn))
            self.controller.update()
            self.assertFalse(self.mod._ads_active)

    def test_sniper_fps_follows_native_state_after_toggle_release(self):
        self.weapon.category = "sniper_rifle"
        self.enter()
        self.assertEqual(self.mod._ads_route, "sniper_fps")
        self.assertEqual(self.camera_calls, ["Default"])
        self.release()
        self.observe(2, bWantsToZoom=False)
        self.assertEqual(self.camera_calls, ["Default"])
        self.observe(0)
        self.assertEqual(self.camera_calls, ["Default", "ThirdPerson"])
        self.assertEqual(self.mod._ads_route, "hip")

    def test_native_resume_enters_sniper_route_from_swap_gap(self):
        self.enter()
        self.observe(3)
        self.camera.CameraModeInputs.Weapon = S(address=0x60, category="sniper_rifle")
        self.observe(1)
        self.assertEqual(self.mod._ads_route, "sniper_fps")
        self.assertTrue(self.mod._ads_handoff["held"])

    def test_context_change_cancels_presentation_and_refuses_entry(self):
        self.enter()
        self.mod._vehicle_camera_active = True
        self.observe(2)
        self.assertFalse(self.mod._ads_active)
        self.assertEqual(self.mod._ads_route, "hip")

    def test_runtime_identity_change_cannot_reverse_old_weapon_calibration(self):
        self.enter()
        old = self.mod._ads_tps_state
        self.pawn = S(address=0x21, ZoomState=self.zoom)
        self.observe(1)
        self.assertIsNot(self.mod._ads_tps_state, old)
        self.assertTrue(self.mod._ads_active)

    def test_local_zoom_notification_observes_native_exit_before_block_decision(self):
        self.enter()
        self.zoom.native(3)
        result = ads_events._hybrid_ads_zoomed_out_hook_impl(
            self.collector, S(), None, None, owner_module=self.mod)
        self.assertIsNone(result)
        self.assertFalse(self.mod._ads_active)

    def test_equip_pair_with_idle_native_zoom_does_not_publish_or_force_pose(self):
        self.enter()
        self.mod._ads_handoff.update(incoming_weapon=self.weapon.address,
                                     collector_address=self.collector.address,
                                     reticle_rebind_active=True)
        self.mod._arm_late_tps_ads_equip_handoff = lambda obj, args: False
        self.mod._native_last_attempt = None
        before = len(self.published)
        self.zoom.native(0)
        args = S(EventWeapon=self.weapon)
        with patch.object(ads_handoff.ads_zoom_modifiers, "update") as native_helper:
            for _ in range(2):
                ads_handoff._hybrid_ads_weapon_equipped_pre_hook_impl(
                    self.collector, args, None, None, owner_module=self.mod)
                ads_handoff._hybrid_ads_weapon_equipped_post_hook_impl(
                    self.collector, args, None, None, owner_module=self.mod)
            native_helper.assert_not_called()
        self.assertEqual(self.mod._ads_handoff["equip_ordinal"], 2)
        self.assertFalse(self.mod._ads_handoff["reticle_rebind_active"])
        self.assertEqual(len(self.published), before)

    def test_reentrant_camera_notification_does_not_duplicate_admission(self):
        self.weapon.category = "sniper_rifle"
        original = self.camera.SetActorCameraMode
        def reentrant(*args):
            self.controller.update("nested_camera_notification")
            original(*args)
        self.camera.SetActorCameraMode = reentrant
        self.enter()
        self.assertEqual(self.controller.entries, 1)
        self.assertEqual(self.camera_calls, ["Default"])


class NativeOwnershipSourceTests(unittest.TestCase):
    def test_real_loader_ads_dispatch_and_cleanup(self):
        script = Path(__file__).with_name("ads_loader_scenario.py")
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["version"], "0.3.9.36")
        self.assertEqual(output["snapshot"]["entries"], 2)
        self.assertEqual(output["snapshot"]["exits"], 2)
        self.assertTrue(output["cleaned"])

    def test_package_contains_no_zoom_struct_assignment(self):
        # The runtime write-refusing object tests exercised paths. This scan
        # also guards removal of unexecuted former State/latch writer branches.
        package = Path(support.PACKAGE_DIR)
        for path in package.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
                aliases = {"ZoomState"}
                for node in ast.walk(function):
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute) and node.value.attr == "ZoomState":
                        aliases.update(t.id for t in node.targets if isinstance(t, ast.Name))
                for node in ast.walk(function):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
                    for target in targets:
                        if isinstance(target, ast.Attribute):
                            direct = isinstance(target.value, ast.Attribute) and target.value.attr == "ZoomState"
                            alias = isinstance(target.value, ast.Name) and target.value.id in aliases
                            self.assertFalse(direct or alias, f"Native zoom assignment in {path.name}:{node.lineno}")


if __name__ == "__main__":
    unittest.main()
