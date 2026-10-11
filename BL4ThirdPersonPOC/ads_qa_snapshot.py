"""Capture explicit F10 observations of native ADS and presentation handoff.

Reads the local runtime and publisher's validated reticle snapshot into a JSON
report. No extra hook, model publication or native patch is added. This is a
diagnostic snapshot, not proof that the HUD drew the expected crosshair.
The output path is next to the installed mod directory and errors are recorded.
"""

from datetime import datetime, timezone
from pathlib import Path
import json


def capture(mod):
    """Write an explicit diagnostic JSON snapshot and return the same report.

    Capture/read/output errors are reported without installing a gameplay hook.
    """
    report = {
        "version": mod.MOD_VERSION,
        "source": "F10",
        "errors": [],
        "game_writes": 0,
        "native_patches_added": 0,
        "sdk_hooks_added": 0,
    }
    try:
        pc, pawn, camera = mod._get_runtime()
        report.update(
            route=mod._ads_route,
            ads_active=mod._ads_active,
            native_auto=mod._native_auto_enabled,
            recoil_active=mod._native_active(),
            beam_active=mod._beam_active(),
            native_fault=mod._native_fault,
        )
        if any(x is None for x in (pc, pawn, camera)):
            raise RuntimeError("Loaded local player required")
        weapon = camera.CameraModeInputs.Weapon
        report["identity"] = [
            hex(mod._object_address(x)) for x in (pc, pawn, camera, weapon)
        ]
        report["weapon_path"] = str(weapon._path_name()) if weapon is not None else None
        report["camera_mode"] = str(camera.GetActorCameraMode(pawn))
        report["camera_transitioning"] = bool(camera.CameraModeState.bIsTransitioning)
        report["camera_colliding"] = bool(camera.CameraModeState.bIsColliding)
        report["zoom"] = dict(
            state=int(pawn.ZoomState.State),
            wants=bool(pawn.ZoomState.bWantsToZoom),
            pending=bool(pawn.ZoomState.bPendingZoom),
            ticking=bool(pawn.ZoomState.bTickingZoom),
        )
        report["ads_control"] = mod._ads_controller.snapshot()
        report["handoff"] = {
            k: mod._ads_handoff.get(k)
            for k in (
                "held",
                "incoming_weapon",
                "route_weapon",
                "collector_address",
                "equip_ordinal",
                "reticle_rebind_active",
                "native_tps_rearm",
            )
        }
        ads = mod._ads_tps_state
        report["zoom_modifier_fix"] = (
            None
            if not isinstance(ads, dict)
            else {
                "result": ads.get("zoom_modifier_result"),
                "attempt": ads.get("zoom_modifier_attempt"),
            }
        )
        report["ads_state"] = (
            None
            if not isinstance(ads, dict)
            else {
                k: ads.get(k)
                for k in (
                    "phase",
                    "category",
                    "weapon_address",
                    "manager_address",
                    "target_fov",
                    "last_fov",
                    "transition",
                    "zoom_multiplier",
                    "hybrid_settled_equip",
                    "reticle_last_event",
                    "reticle_last_status",
                )
            }
        )
        report["reticle"] = dict(
            faulted=mod._reticle_publish_faulted,
            pending=mod._reticle_publish_pending,
            last_gate=mod._reticle_gate_last_fail,
            counts=dict(mod._reticle_publish_counts),
        )
        observer = getattr(mod._reticle_publisher, "observe", None)
        if callable(observer):
            report["reticle_model"] = observer()
        else:
            report["reticle_model"] = None
            report["reticle_note"] = (
                "Publisher not initialized; enter TPS ADS before comparison"
            )
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    name = (
        "bl4tps_ads_handoff_"
        + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        + ".json"
    )
    location = Path(mod.__file__).resolve()
    archive = next((p for p in location.parents if p.suffix.lower() == '.sdkmod'), None)
    directory = archive.parent if archive is not None else location.parent.parent
    path = directory / name
    try:
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        mod.logging.info(
            f"[BL4ThirdPersonPOC.ADSHandoff] SNAPSHOT errors={len(report['errors'])} "
            f"route={report.get('route')!r} recoil={report.get('recoil_active')} "
            f"game_writes=0 json={path}"
        )
    except Exception as exc:
        mod.logging.error(
            f"[BL4ThirdPersonPOC.ADSHandoff] OUTPUT_FAILED {type(exc).__name__}: {exc}"
        )
    return report
