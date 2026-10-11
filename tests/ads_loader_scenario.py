"""Import the real loader, dispatch its ADS callbacks, and retire presentation."""
import json
from types import SimpleNamespace as S
import loader_harness as h


def run():
    mod = h.load()
    h.set_build(True)
    pc, pawn = S(address=0x10), S(address=0x20)
    pawn.ZoomState = S(State=0, bWantsToZoom=False, bPendingZoom=False, bTickingZoom=False)
    weapon, collector = S(address=0x40), S(address=0x50)
    camera = S(address=0x30, CameraModeInputs=S(Weapon=weapon),
               CameraCachePrivate=S(POV=S(FOV=90.)), mode="ThirdPerson",
               CameraModeState=S(BaseFOVOffset=0., bIsTransitioning=False))
    camera.SetActorCameraMode = lambda pawn, mode, *args: setattr(camera, "mode", mode)
    camera.GetActorCameraMode = lambda pawn: camera.mode
    mod._get_runtime = lambda: (pc, pawn, camera)
    mod._object_address = mod._ads_object_address = lambda obj: getattr(obj, "address", 0)
    mod._third_person_enabled = mod._third_person_pushed = True
    mod._vehicle_camera_active = mod._ladder_active = mod._shop_camera_active = False
    mod._ffyl_camera_active = lambda pawn, camera: False
    mod._beam_active = mod._native_active = lambda: False
    mod._classify_ads_weapon = lambda weapon: ("pistol", "test", "SDK substitute")
    mod._find_ads_collector = lambda weapon: collector
    mod._find_active_ads_sight = lambda weapon: (S(PuppetZoomFOVScale=.5, ZoomDuration=.15), 0, "Sight")
    mod._apply_camera_offset = lambda: None
    model = dict(visible=True)
    def publish():
        status = "already_visible" if model["visible"] else "published"
        model["visible"] = True
        return {"status": status}
    hidden = []
    def hide(identity):
        hidden.append(identity)
        model["visible"] = False
        return {"status": "hidden"}
    publish.hide_for_scope = hide
    mod._reticle_publisher = publish  # native leaf; all loader wrappers stay real
    mod._ads_hooks_installed = list(range(6))
    mod._reset_hybrid_ads_debug()
    mod._reset_ads_handoff_debug()
    mod._reset_ads_press_intent()
    mod.first_person_ads_mouse_input(mod.EInputEvent.IE_Pressed)
    assert not mod._ads_active
    pawn.ZoomState.State = 1
    mod._hybrid_ads_zoom_change_hook(collector, S(), None, None)
    assert mod._ads_active and mod._ads_route == "tps"
    target = mod._ads_tps_state["target_fov"]
    pawn.ZoomState.State = 3
    mod._update_pending_ads_press()
    assert not mod._ads_active
    camera.CameraModeInputs.Weapon = S(address=0x60, CurrentState="Active")
    camera.CameraCachePrivate.POV.FOV = target
    pawn.ZoomState.State = 1
    mod._update_pending_ads_press()
    assert mod._ads_active and mod._ads_tps_state["base_fov"] == 90.
    assert mod._ads_tps_state["weapon_address"] == 0x60
    args = S(EventWeapon=camera.CameraModeInputs.Weapon)
    mod._hybrid_ads_weapon_equipped_pre_hook(collector, args, None, None)
    model["visible"] = False  # simulated native equip body
    mod._hybrid_ads_weapon_equipped_post_hook(collector, args, None, None)
    assert model["visible"] and mod._ads_handoff["equip_ordinal"] == 1
    assert not mod._ads_handoff["reticle_rebind_active"]
    assert mod._ads_tps_state["reticle_last_event"] == "weapon_equipped_post"
    mod.first_person_ads_mouse_input(mod.EInputEvent.IE_Released)
    pawn.ZoomState.State = 2
    mod._update_pending_ads_press()
    assert mod._ads_active and not mod._ads_handoff["held"]
    mod._update_pending_tps_reticle()  # includes its real lazy module import
    pawn.ZoomState.State = 0
    mod._update_pending_ads_press()
    assert not mod._ads_active
    snapshot = mod._ads_controller.snapshot()
    identity = (pc.address, pawn.address, camera.address, camera.CameraModeInputs.Weapon.address)
    assert mod._hide_hybrid_tps_reticle(identity) == "hidden"
    assert hidden == [identity] and not model["visible"]
    assert mod._reticle_publish_counts["hidden"] == 1
    mod._cancel_hybrid_ads("loader_test_complete")
    assert camera.CameraModeState.BaseFOVOffset == 0.
    assert mod._ads_tps_state is None and mod._ads_route == "hip"
    errors = [message for level, message in h.LOG if level == "error"]
    assert not errors, errors
    return dict(version=mod.MOD_VERSION, snapshot=snapshot, cleaned=True)


if __name__ == "__main__":
    print(json.dumps(run()))
