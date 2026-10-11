"""Compute camera offsets, ADS FOV and projected pickup geometry.

Vector/matrix routines and OBB/ray tests are shared with item-card selection.
Runtime readers obtain current SDK fields; the loader owns mutable motion and
mantle state. Apply offsets only through the caller's camera ownership gates.
Degenerate/nonfinite geometry refuses a candidate or uses the existing fallback.
Optical ADS FOV derives from game attributes within the configured safety bounds.
This module installs no hooks and owns no native code allocations.
"""

from __future__ import annotations

import math
from .settings_validation import bounded_number, position_values
from typing import Any, Callable

from unrealsdk import find_object, logging, make_struct


def _make_vector(x: float, y: float, z: float) -> Any:
    return make_struct(
        "Vector",
        X=float(x),
        Y=float(y),
        Z=float(z),
    )


def _get_world_location(actor: Any) -> Any:
    try:
        return actor.K2_GetActorLocation()
    except Exception:
        return actor.RootComponent.K2_GetComponentLocation()


def _get_actor_eye_location(pawn: Any) -> Any:
    result = pawn.GetActorEyesViewPoint(
        _make_vector(0.0, 0.0, 0.0),
        make_struct(
            "Rotator",
            pitch=0.0,
            yaw=0.0,
            roll=0.0,
        ),
    )
    if not isinstance(result, tuple) or len(result) < 3:
        raise RuntimeError("Unexpected GetActorEyesViewPoint result: " f"{result!r}")
    return result[-2]


def _get_look_at_rotation(start: Any, target: Any) -> Any:
    math_class = find_object(
        "Class",
        "/Script/Engine.KismetMathLibrary",
    )
    result = math_class.ClassDefaultObject.FindLookAtRotation(
        start,
        target,
    )
    if isinstance(result, tuple):
        if not result:
            raise RuntimeError("FindLookAtRotation returned an empty tuple")
        return result[0]
    return result


def _get_tps_crosshair_screen(
    pc: Any,
    camera_manager: Any,
) -> tuple[float, float]:
    pov = camera_manager.CameraCachePrivate.POV
    viewport_result = pc.GetViewportSize(0, 0)
    viewport_x = float(viewport_result[-2])
    viewport_y = float(viewport_result[-1])

    pitch = math.radians(float(pov.Rotation.pitch))
    yaw = math.radians(float(pov.Rotation.yaw))
    forward_point = _make_vector(
        pov.Location.X + math.cos(pitch) * math.cos(yaw) * 10000.0,
        pov.Location.Y + math.cos(pitch) * math.sin(yaw) * 10000.0,
        pov.Location.Z + math.sin(pitch) * 10000.0,
    )
    projection_result = pc.ProjectWorldLocationToScreen(
        forward_point,
        make_struct("Vector2D", X=0.0, Y=0.0),
        False,
    )
    if bool(projection_result[0]):
        projected = projection_result[-1]
        return float(projected.X), float(projected.Y)

    return viewport_x * 0.5, viewport_y * 0.5


def _dynamic_motion_point(value: Any) -> tuple[float, float, float]:
    return tuple(float(getattr(value, axis)) for axis in "XYZ")


def _dynamic_motion_speed(pawn: Any) -> float | None:
    for source in (pawn, getattr(pawn, "CharacterMovement", None)):
        if source is None:
            continue
        for name in ("GetVelocity", "K2_GetVelocity"):
            method = getattr(source, name, None)
            if callable(method):
                try:
                    vx, vy, _ = _dynamic_motion_point(method())
                    if math.isfinite(vx) and math.isfinite(vy):
                        return math.hypot(vx, vy)
                except Exception:
                    pass
        try:
            vx, vy, _ = _dynamic_motion_point(source.Velocity)
            if math.isfinite(vx) and math.isfinite(vy):
                return math.hypot(vx, vy)
        except Exception:
            pass
    return None


def _dynamic_motion_airborne(pawn: Any) -> bool | None:
    movement = getattr(pawn, "CharacterMovement", None)
    if movement is None:
        return None
    for name in ("IsFalling", "K2_IsFalling"):
        method = getattr(movement, name, None)
        if callable(method):
            try:
                return bool(method())
            except Exception:
                pass
    method = getattr(movement, "IsMovingOnGround", None)
    if callable(method):
        try:
            return not bool(method())
        except Exception:
            pass
    return None


def _dynamic_motion_crouched(pawn: Any) -> bool | None:
    for source in (pawn, getattr(pawn, "CharacterMovement", None)):
        if source is not None:
            try:
                return bool(source.bIsCrouched)
            except Exception:
                pass
    return None


ADS_OPTICAL_ZOOM_RESPONSE = 0.55
ADS_MIN_SAFE_FOV = 20.0
ADS_MAX_SAFE_FOV = 170.0


def _ads_attribute_float(obj: Any, name: str) -> float:
    value = getattr(obj, name)
    for member in ("Value", "BaseValue"):
        try:
            return float(getattr(value, member))
        except Exception:
            continue
    return float(value)


def _derive_ads_target_fov(
    base_fov: float,
    puppet_scale: float,
) -> tuple[float, float, float]:
    native_target = float(base_fov) * float(puppet_scale)
    if not ADS_MIN_SAFE_FOV <= native_target <= ADS_MAX_SAFE_FOV:
        raise RuntimeError(
            f"Unsafe native puppet target {native_target} from "
            f"base={base_fov}, scale={puppet_scale}"
        )
    base_tangent = math.tan(math.radians(base_fov) * 0.5)
    native_tangent = math.tan(math.radians(native_target) * 0.5)
    if base_tangent <= 0.0 or native_tangent <= 0.0:
        raise RuntimeError("Invalid FOV tangent while deriving optical zoom")
    native_magnification = base_tangent / native_tangent
    effective_magnification = native_magnification**ADS_OPTICAL_ZOOM_RESPONSE
    target = math.degrees(2.0 * math.atan(base_tangent / effective_magnification))
    if not ADS_MIN_SAFE_FOV <= target <= ADS_MAX_SAFE_FOV:
        raise RuntimeError(
            f"Unsafe optical target {target} from base={base_fov}, "
            f"native_target={native_target}"
        )
    return target, native_magnification, effective_magnification


def _ads_smoothstep(alpha: float) -> float:
    value = max(0.0, min(1.0, float(alpha)))
    return value * value * (3.0 - 2.0 * value)


def _read_live_ads_fov(camera_manager: Any) -> float:
    try:
        pov = camera_manager.CameraCachePrivate.POV
    except Exception as exc:
        raise RuntimeError(f"CameraCachePrivate.POV unavailable: {exc}") from exc
    for name in ("FOV", "fov"):
        try:
            value = float(getattr(pov, name))
            if ADS_MIN_SAFE_FOV <= value <= ADS_MAX_SAFE_FOV:
                return value
        except Exception:
            continue
    try:
        value = float(camera_manager.DefaultFOV)
        if ADS_MIN_SAFE_FOV <= value <= ADS_MAX_SAFE_FOV:
            return value
    except Exception:
        pass
    raise RuntimeError("No sane live camera FOV could be read")


def _read_native_zoom_confirmation(pawn: Any) -> bool:
    """Require an active native zoom state, never bWantsToZoom alone."""
    zoom = pawn.ZoomState
    native_state = int(zoom.State)
    return native_state in (1, 2)


def _read_ads_zoom_fields(pawn: Any) -> str:
    try:
        zoom = pawn.ZoomState
        return (
            f"state={zoom.State!s}, wants={bool(zoom.bWantsToZoom)}, "
            f"pending={bool(zoom.bPendingZoom)}, "
            f"ticking={bool(zoom.bTickingZoom)}"
        )
    except Exception as exc:
        return f"unavailable={type(exc).__name__}: {exc}"


def _camera_looks_first_person(
    get_runtime: Callable[[], tuple[Any, Any, Any]],
) -> bool:
    _pc, pawn, camera_manager = get_runtime()

    if camera_manager is None:
        return False

    show_viewmodel = False
    first_person_arms = False

    try:
        camera_mode_state = camera_manager.CameraModeState

        show_viewmodel = bool(camera_mode_state.bShowViewModel)
    except Exception:
        pass

    try:
        camera_mode_inputs = camera_manager.CameraModeInputs

        attach_component = str(camera_mode_inputs.AttachComponent)

        first_person_arms = "FirstPersonArms" in attach_component
    except Exception:
        pass

    return show_viewmodel or first_person_arms


def _camera_is_vehicle_view(
    get_runtime: Callable[[], tuple[Any, Any, Any]],
) -> bool:
    _pc, _pawn, camera_manager = get_runtime()

    if camera_manager is None:
        return False

    try:
        inputs = camera_manager.CameraModeInputs
        view_target = inputs.ViewTarget

        if view_target is not None:
            class_name = str(view_target.Class.Name)

            if "OakVehicle" in class_name:
                return True

            if "OakVehicle" in repr(view_target):
                return True
    except Exception:
        pass

    try:
        attach_component = str(camera_manager.CameraModeInputs.AttachComponent)

        return "VehicleMesh" in attach_component
    except Exception:
        return False


def _apply_dynamic_motion_camera_offset(
    pawn: Any,
    manager: Any,
    *,
    _dynamic_motion_enabled,
    _mantle_camera_state,
    _third_person_enabled,
    _third_person_pushed,
    _vehicle_camera_active,
    _shop_camera_active,
    _slide_active,
    _ladder_active,
    _ads_active,
    _camera_lifecycle,
    _looks_like_first_person_fallback,
    _dynamic_motion_state,
    _dynamic_motion_reset,
    _set_camera_offset,
    camera_offset_x,
    camera_offset_y,
    camera_offset_z,
    motion_parameters,
    _camera_frame=None,
) -> None:
    if not _dynamic_motion_enabled:
        return
    try:
        mantle = _mantle_camera_state
        eligible = (
            _third_person_enabled
            and _third_person_pushed
            and pawn is not None
            and manager is not None
            and not _vehicle_camera_active
            and not _shop_camera_active
            and not _slide_active
            and not _ladder_active
            and not _ads_active
            and not _camera_lifecycle.get("pending")
            and not mantle.get("active")
            and not mantle.get("releasing")
            and str(manager.GetActorCameraMode(pawn)) == "ThirdPerson"
            and not _looks_like_first_person_fallback()
        )
        if not eligible:
            _dynamic_motion_reset()
            return
        mesh = getattr(pawn, "Mesh", None)
        if mesh is None:
            _dynamic_motion_reset()
            return
        pawn_id = int(pawn._get_address())
        sample = _camera_frame or {}
        if sample.get('sample_pawn') == pawn_id and sample.get('sample_mesh') == int(mesh._get_address()):
            px, py, pz = sample['actor']
            sx, sy, sz = sample['spine']
        else:
            px, py, pz = _dynamic_motion_point(pawn.K2_GetActorLocation())
            sx, sy, sz = _dynamic_motion_point(mesh.GetSocketLocation("Spine3"))
        yaw = math.radians(float(manager.CameraCachePrivate.POV.Rotation.yaw))
        if not all(map(math.isfinite, (px, py, pz, sx, sy, sz, yaw))):
            _dynamic_motion_reset()
            return
        removed = sample.get('motion_root_z')
        root_relative = removed is not None
        removed = float(removed) if root_relative else 0.0
        if not math.isfinite(removed):
            _dynamic_motion_reset()
            return
        relative = (sx - px, sy - py, sz - pz - removed)
        if (
            _dynamic_motion_state["pawn_id"] != pawn_id
            or _dynamic_motion_state["baseline"] is None
        ):
            _dynamic_motion_reset()
            _dynamic_motion_state["pawn_id"] = pawn_id
            _dynamic_motion_state["baseline"] = relative
            _dynamic_motion_state['root_relative'] = root_relative
            _dynamic_motion_state['root_removed_z'] = removed
            return
        # Switch coordinate conventions without adding a fake pose impulse.
        if _dynamic_motion_state.get('root_relative', False) != root_relative:
            bx, by, bz = _dynamic_motion_state['baseline']
            _dynamic_motion_state['baseline'] = (bx, by, bz +
                _dynamic_motion_state.get('root_removed_z', 0.0) - removed)
        _dynamic_motion_state['root_relative'] = root_relative
        _dynamic_motion_state['root_removed_z'] = removed
        baseline = tuple(
            old + (motion_parameters["baseline"] / 100.0) * (new - old)
            for old, new in zip(_dynamic_motion_state["baseline"], relative)
        )
        _dynamic_motion_state["baseline"] = baseline
        wx, wy, wz = (v - b for v, b in zip(relative, baseline))
        local = (
            math.cos(yaw) * wx + math.sin(yaw) * wy,
            -math.sin(yaw) * wx + math.cos(yaw) * wy,
            wz,
        )
        speed = _dynamic_motion_speed(pawn)
        airborne = _dynamic_motion_airborne(pawn)
        crouched = _dynamic_motion_crouched(pawn)
        landing = _dynamic_motion_state["was_airborne"] and airborne is False
        if airborne is not None:
            _dynamic_motion_state["was_airborne"] = airborne
        if crouched is not None:
            previous = _dynamic_motion_state["previous_crouched"]
            if previous is not None and crouched != previous:
                _dynamic_motion_state["crouch_edge"] = (
                    "crouch_pose" if crouched else "rise_pose"
                )
                _dynamic_motion_state["crouch_edge_seen_motion"] = False
            _dynamic_motion_state["previous_crouched"] = crouched
        if _dynamic_motion_state["crouch_edge"] is not None and abs(wz) >= 8.0:
            _dynamic_motion_state["crouch_edge_seen_motion"] = True
        transition = (
            airborne is False
            and _dynamic_motion_state["crouch_edge"] is not None
            and _dynamic_motion_state["crouch_edge_seen_motion"]
            and (speed is None or speed < 300.0)
        )
        if _dynamic_motion_state["crouch_edge_seen_motion"] and abs(wz) < 6.0:
            _dynamic_motion_state["crouch_edge"] = None
            _dynamic_motion_state["crouch_edge_seen_motion"] = False
            transition = False
        if airborne is True:
            gain, phase = motion_parameters["air_gain"] / 100.0, "air"
            _dynamic_motion_state["crouch_edge"] = None
            _dynamic_motion_state["crouch_edge_seen_motion"] = False
        elif landing:
            gain, phase = motion_parameters["landing_gain"] / 100.0, "landing"
        elif transition:
            gain, phase = (
                motion_parameters["crouch_gain"] / 100.0,
                _dynamic_motion_state["crouch_edge"],
            )
        elif speed is None:
            gain, phase = motion_parameters["unknown_gain"] / 100.0, "unknown_speed"
        elif speed >= motion_parameters["fast_speed"]:
            gain, phase = motion_parameters["fast_gain"] / 100.0, "fast_motion"
        elif speed >= motion_parameters["walk_speed"]:
            gain, phase = motion_parameters["walk_gain"] / 100.0, "walk_motion"
        else:
            gain, phase = motion_parameters["still_gain"] / 100.0, (
                "crouched_still" if crouched else "still"
            )
        horizontal_gain = (
            motion_parameters["idle_horizontal"] / 100.0 if phase == "still" else gain
        )
        target = tuple(
            max(-limit, min(limit, axis_gain * scale * value))
            for value, axis_gain, scale, limit in zip(
                local,
                (horizontal_gain, horizontal_gain, gain),
                (motion_parameters["axis_" + axis] / 100.0 for axis in "xyz"),
                (motion_parameters["limit_" + axis] for axis in "xyz"),
            )
        )
        filtered = tuple(
            old + (motion_parameters["filter"] / 100.0) * (new - old)
            for old, new in zip(_dynamic_motion_state["filtered"], target)
        )
        _dynamic_motion_state["filtered"] = filtered
        if max(map(abs, filtered)) >= 0.02:
            _set_camera_offset(
                float(camera_offset_x.value) + filtered[0],
                float(camera_offset_y.value) + filtered[1],
                float(camera_offset_z.value) + filtered[2],
            )
    except Exception as exc:
        logging.error(
            f"[BL4ThirdPersonPOC] DYNAMIC_MOTION_CAMERA_FRAME_FAILED {type(exc).__name__}: {exc}"
        )
        _dynamic_motion_reset()


def _apply_mantle_camera_offset(
    pawn: Any,
    manager: Any,
    *,
    _mantle_camera_state,
    _third_person_enabled,
    _third_person_pushed,
    _vehicle_camera_active,
    _shop_camera_active,
    _slide_active,
    _camera_lifecycle,
    _ladder_active,
    _reset_mantle_camera_state,
    _set_camera_offset,
    camera_offset_x,
    camera_offset_y,
    camera_offset_z,
    _camera_frame=None,
) -> None:
    """Follow the animated mesh during a mantle after the normal TPS offset."""
    state = _mantle_camera_state
    try:
        if (
            pawn is None
            or manager is None
            or not _third_person_enabled
            or not _third_person_pushed
            or _vehicle_camera_active
            or _shop_camera_active
            or _slide_active
            or _camera_lifecycle.get("pending")
        ):
            _reset_mantle_camera_state()
            return
        pawn_id = int(pawn._get_address())
        if state["pawn_id"] != pawn_id:
            _reset_mantle_camera_state()
            state["pawn_id"] = pawn_id
        if _ladder_active:
            state["armed_ladder"] = True
        mesh = getattr(pawn, "Mesh", None)
        if mesh is None:
            _reset_mantle_camera_state()
            return

        def loc(component: Any) -> tuple[float, float, float]:
            try:
                value = component.K2_GetComponentLocation()
            except Exception:
                value = component.K2_GetActorLocation()
            return tuple(float(getattr(value, axis)) for axis in "XYZ")

        px, py, pz = loc(pawn)
        mx, my, mz = loc(mesh)
        spine = mesh.GetSocketLocation("Spine3")
        spine_z = float(spine.Z)
        if not all(math.isfinite(v) for v in (px, py, pz, mx, my, mz, spine_z)):
            _reset_mantle_camera_state()
            return
        if _camera_frame is not None:
            sx, sy = float(spine.X), float(spine.Y)
            if math.isfinite(sx) and math.isfinite(sy):
                _camera_frame.update(actor=(px, py, pz), mesh=(mx, my, mz),
                    spine=(sx, sy, spine_z), sample_pawn=pawn_id,
                    sample_mesh=int(mesh._get_address()))
        previous = state["previous"]
        state["previous"] = (pz, spine_z - pz)
        lag_z = mz - pz + 100.0
        lag_xy = math.hypot(mx - px, my - py)
        jump = pz - previous[0] if previous is not None else 0.0
        branch = ""
        if lag_xy >= 40.0 and jump >= 100.0 and lag_z <= -90.0:
            branch = "ladder_up" if state["armed_ladder"] else "ledge_up"
        elif lag_xy >= 40.0 and jump <= -100.0 and lag_z >= 90.0:
            branch = "ledge_down"
        if branch:
            if state["active"] or state["releasing"]:
                logging.info(
                    "[BL4ThirdPersonPOC] MANTLE_RESTART "
                    f"previous={state['branch']} next={branch} "
                    f"during={'release' if state['releasing'] else 'tracking'}"
                )
            state.update(
                active=True,
                releasing=False,
                branch=branch,
                baseline_spine_z=previous[1],
                stable_frames=0,
                just_started=True,
                height_fade_logged=False,
            )
            logging.info(
                "[BL4ThirdPersonPOC] MANTLE_START "
                f"branch={branch} pawn_jump={jump:.1f} "
                f"mesh_lag_z={lag_z:.1f} mesh_lag_xy={lag_xy:.1f}"
            )
        if not state["active"] and not state["releasing"]:
            return
        if state["active"]:
            spine_lag = (spine_z - pz) - state["baseline_spine_z"]
            geometry_settled = lag_xy < 8.0 and abs(lag_z) < 8.0
            pose_settled = abs(spine_lag) < 6.0 and lag_xy < 8.0
            # A quick reverse/repeated climb can leave Spine3 at a new idle
            # pose even though pawn and mesh have already converged. The
            # same three-frame geometry gate used by other mantle branches
            # then supplies a reliable ladder completion signal.
            settled = (
                (pose_settled or geometry_settled)
                if state["branch"] == "ladder_up"
                else geometry_settled
            )
            if settled:
                state["stable_frames"] += 1
            else:
                state["stable_frames"] = 0
            if state["stable_frames"] >= 3:
                state.update(active=False, releasing=True, armed_ladder=False)
                logging.info(
                    "[BL4ThirdPersonPOC] MANTLE_SETTLED "
                    f"branch={state['branch']} spine_lag_z={spine_lag:.1f} "
                    f"mesh_lag_xy={lag_xy:.1f} "
                    f"source={'pose' if pose_settled else 'geometry'}"
                )
            else:
                yaw = math.radians(float(manager.CameraCachePrivate.POV.Rotation.yaw))
                dx, dy = mx - px, my - py
                lx = math.cos(yaw) * dx + math.sin(yaw) * dy
                ly = -math.sin(yaw) * dx + math.cos(yaw) * dy
                length = math.hypot(lx, ly)
                if length > 190.0:
                    lx *= 190.0 / length
                    ly *= 190.0 / length
                dz = max(-250.0, min(250.0, spine_lag))
                if state["branch"] != "ledge_down" and -75.0 <= lag_z <= 8.0:
                    progress = max(0.0, min(1.0, (145.0 - lag_xy) / 135.0))
                    if progress > 0.0 and not state["height_fade_logged"]:
                        state["height_fade_logged"] = True
                        logging.info(
                            "[BL4ThirdPersonPOC] MANTLE_HEIGHT_FADE_START "
                            f"mesh_lag_xy={lag_xy:.1f} spine_lag_z={spine_lag:.1f}"
                        )
                    eased = progress * progress * (3.0 - 2.0 * progress)
                    height_progress = max(0.0, min(1.0, (lag_z + 75.0) / 75.0))
                    height_eased = (
                        height_progress
                        * height_progress
                        * (3.0 - 2.0 * height_progress)
                    )
                    dz *= 1.0 - 0.85 * eased * height_eased
                target = (lx, ly, dz)
        if state["releasing"]:
            target = (0.0, 0.0, 0.0)
        if state["just_started"]:
            filtered = target
            state["just_started"] = False
        else:
            alpha = (
                (0.32 if state["releasing"] else 0.48)
                if state["branch"] == "ledge_down"
                else (0.18 if state["releasing"] else 0.16)
            )
            filtered = tuple(
                old + alpha * (new - old) for old, new in zip(state["filtered"], target)
            )
        state["filtered"] = filtered
        if state["releasing"] and max(map(abs, filtered)) < 1.5:
            branch = state["branch"]
            _reset_mantle_camera_state()
            state["pawn_id"] = pawn_id
            state["previous"] = (pz, spine_z - pz)
            logging.info(f"[BL4ThirdPersonPOC] MANTLE_END branch={branch}")
            return
        _set_camera_offset(
            float(camera_offset_x.value) + filtered[0],
            float(camera_offset_y.value) + filtered[1],
            float(camera_offset_z.value) + filtered[2],
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        last_error = state.get("last_error")
        _reset_mantle_camera_state()
        if detail != last_error:
            logging.error(f"[BL4ThirdPersonPOC] MANTLE_FRAME_FAILED {detail}")
            state["last_error"] = detail


# ADS sight and weapon classification (formerly ads_introspection.py).
ADS_TYPE_PATHS = (
    ("sniper_rifle", "/sniper/"),
    ("assault_rifle", "/assaultrifles/"),
    ("shotgun", "/shotguns/"),
    ("smg", "/smg/"),
    ("pistol", "/pistols/"),
    ("heavy_weapon", "/heavyweapons/"),
)


ADS_TYPE_SUFFIXES = {
    "SR": "sniper_rifle",
    "AR": "assault_rifle",
    "SG": "shotgun",
    "SM": "smg",
    "PS": "pistol",
    "HW": "heavy_weapon",
}


def _ads_object_path(value: Any) -> str:
    if value is None:
        return "<none>"
    try:
        return str(value._path_name())
    except Exception:
        return repr(value)


def _ads_class_name(value: Any) -> str:
    try:
        return str(value.Class.Name)
    except Exception:
        return type(value).__name__


def _find_active_ads_sight(weapon: Any) -> tuple[Any, int, str]:
    current_mode = int(getattr(weapon, "CurrentUseModeIndex", -1))
    candidates: list[tuple[Any, int, str]] = []
    for index, behavior in enumerate(tuple(weapon.behaviors)):
        if _ads_class_name(behavior) != "WeaponBehavior_Sight":
            continue
        name = str(getattr(behavior, "Name", f"index{index}"))
        candidates.append((behavior, index, name))
        if name.startswith(f"UM{current_mode}_"):
            return behavior, index, name
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(
        "Could not uniquely resolve active WeaponBehavior_Sight; "
        f"current_mode={current_mode}, "
        f"candidates={[(index, name) for _obj, index, name in candidates]}"
    )


def _classify_ads_weapon(weapon: Any) -> tuple[str, str, str]:
    if weapon is None:
        raise RuntimeError("No equipped weapon is available")
    body = getattr(weapon, "BodyData", None)
    body_path = _ads_object_path(body)
    lower = body_path.lower().replace("\\", "/")
    for category, token in ADS_TYPE_PATHS:
        if token in lower:
            return category, "BodyData.path", body_path

    try:
        body_name = str(body.Name)
    except Exception:
        body_name = ""
    suffix = body_name.rsplit("_", 1)[-1].upper() if "_" in body_name else ""
    category = ADS_TYPE_SUFFIXES.get(suffix)
    if category is not None:
        return category, "BodyData.name_suffix", body_name
    return "unknown", "safe_tps_fallback", body_path


# item_card_component.py — consolidated pickup camera geometry.
def _item_card_result_value(result: Any) -> Any:
    if isinstance(result, tuple):
        return result[-1] if result else None
    return result


def _item_card_quaternion_matrix(rotation: Any) -> list[list[float]]:
    x, y, z, w = (
        float(rotation.X),
        float(rotation.Y),
        float(rotation.Z),
        float(rotation.W),
    )
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length <= 1e-12:
        raise RuntimeError("Component quaternion has zero length")
    x, y, z, w = x / length, y / length, z / length, w / length
    return [
        [
            1.0 - 2.0 * (y * y + z * z),
            2.0 * (x * y - z * w),
            2.0 * (x * z + y * w),
        ],
        [
            2.0 * (x * y + z * w),
            1.0 - 2.0 * (x * x + z * z),
            2.0 * (y * z - x * w),
        ],
        [
            2.0 * (x * z - y * w),
            2.0 * (y * z + x * w),
            1.0 - 2.0 * (x * x + y * y),
        ],
    ]


def _item_card_rotator_matrix(rotation: Any) -> list[list[float]]:
    pitch = math.radians(float(rotation.Pitch))
    yaw = math.radians(float(rotation.Yaw))
    roll = math.radians(float(rotation.Roll))
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    sr, cr = math.sin(roll), math.cos(roll)
    return [
        [cp * cy, sr * sp * cy - cr * sy, -(cr * sp * cy + sr * sy)],
        [cp * sy, sr * sp * sy + cr * cy, cy * sr - cr * sp * sy],
        [sp, -sr * cp, cr * cp],
    ]


def _item_card_component_basis(component: Any) -> list[list[float]]:
    errors = []
    for name in ("K2_GetComponentToWorld", "GetComponentTransform"):
        try:
            transform = _item_card_result_value(getattr(component, name)())
            return _item_card_quaternion_matrix(transform.Rotation)
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    try:
        rotation = _item_card_result_value(component.K2_GetComponentRotation())
        return _item_card_rotator_matrix(rotation)
    except Exception as exc:
        errors.append(f"K2_GetComponentRotation: {type(exc).__name__}: {exc}")
    raise RuntimeError(" | ".join(errors))


# item_card_geometry.py — consolidated pickup camera geometry.
def _item_card_determinant(matrix: list[list[float]]) -> float:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _item_card_solve_3x3(
    matrix: list[list[float]],
    values: tuple[float, float, float],
) -> tuple[float, float, float]:
    determinant = _item_card_determinant(matrix)
    if abs(determinant) <= 1e-8:
        raise RuntimeError(
            f"Absolute rotation matrix is singular (det={determinant:.12f})"
        )
    columns = []
    for column in range(3):
        replaced = [row[:] for row in matrix]
        for row in range(3):
            replaced[row][column] = values[row]
        columns.append(_item_card_determinant(replaced) / determinant)
    return tuple(columns)  # type: ignore[return-value]


def _item_card_solve_nonnegative(
    matrix: list[list[float]],
    values: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    candidates: list[tuple[float, tuple[float, float, float]]] = []
    for mask in range(1, 8):
        active = [index for index in range(3) if mask & (1 << index)]
        columns = [[matrix[row][column] for row in range(3)] for column in active]
        rhs = [sum(column[row] * values[row] for row in range(3)) for column in columns]
        gram = [
            [sum(left[row] * right[row] for row in range(3)) for right in columns]
            for left in columns
        ]
        try:
            if len(active) == 1:
                if gram[0][0] <= 1e-12:
                    continue
                solved = [rhs[0] / gram[0][0]]
            elif len(active) == 2:
                determinant = gram[0][0] * gram[1][1] - gram[0][1] * gram[1][0]
                if abs(determinant) <= 1e-10:
                    continue
                solved = [
                    (rhs[0] * gram[1][1] - gram[0][1] * rhs[1]) / determinant,
                    (gram[0][0] * rhs[1] - rhs[0] * gram[1][0]) / determinant,
                ]
            else:
                solved = list(_item_card_solve_3x3(gram, tuple(rhs)))
        except RuntimeError:
            continue
        if any(value < -1e-6 or not math.isfinite(value) for value in solved):
            continue
        full = [0.0, 0.0, 0.0]
        for column, value in zip(active, solved):
            full[column] = max(0.0, value)
        residual = math.sqrt(
            sum(
                (
                    sum(matrix[row][column] * full[column] for column in range(3))
                    - values[row]
                )
                ** 2
                for row in range(3)
            )
        )
        candidates.append((residual, tuple(full)))
    if not candidates:
        raise RuntimeError("Could not reconstruct non-negative pickup OBB")
    residual, half_axes = min(candidates, key=lambda item: item[0])
    return half_axes, residual


def _item_card_convex_hull(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    unique = sorted(set(points))
    if len(unique) <= 1:
        return unique

    def cross(
        origin: tuple[float, float],
        left: tuple[float, float],
        right: tuple[float, float],
    ) -> float:
        return (left[0] - origin[0]) * (right[1] - origin[1]) - (
            left[1] - origin[1]
        ) * (right[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0.0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0.0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _item_card_point_in_polygon(
    point: tuple[float, float],
    polygon: list[tuple[float, float]],
) -> bool:
    if len(polygon) < 3:
        return False
    sign = None
    for index, left in enumerate(polygon):
        right = polygon[(index + 1) % len(polygon)]
        value = (right[0] - left[0]) * (point[1] - left[1]) - (right[1] - left[1]) * (
            point[0] - left[0]
        )
        if abs(value) <= 1e-6:
            continue
        current = value > 0.0
        if sign is None:
            sign = current
        elif sign != current:
            return False
    return True


def _item_card_segment_distance(
    point: tuple[float, float],
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    vx, vy = right[0] - left[0], right[1] - left[1]
    wx, wy = point[0] - left[0], point[1] - left[1]
    length_squared = vx * vx + vy * vy
    if length_squared <= 1e-12:
        return math.hypot(wx, wy)
    factor = max(
        0.0,
        min(1.0, (wx * vx + wy * vy) / length_squared),
    )
    return math.hypot(
        point[0] - (left[0] + factor * vx),
        point[1] - (left[1] + factor * vy),
    )


def _item_card_dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _item_card_ray_obb_hit(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    geometry: dict[str, Any],
) -> float | None:
    center = geometry["center"]
    offset = (
        origin[0] - center[0],
        origin[1] - center[1],
        origin[2] - center[2],
    )
    minimum = -math.inf
    maximum = math.inf
    for axis, extent in zip(
        geometry["axes"],
        geometry["half_axes"],
    ):
        local_origin = _item_card_dot(offset, axis)
        local_direction = _item_card_dot(direction, axis)
        if abs(local_direction) <= 1e-10:
            if local_origin < -extent or local_origin > extent:
                return None
            continue
        left = (-extent - local_origin) / local_direction
        right = (extent - local_origin) / local_direction
        if left > right:
            left, right = right, left
        minimum = max(minimum, left)
        maximum = min(maximum, right)
        if maximum < minimum:
            return None
    if maximum < 0.0:
        return None
    return max(0.0, minimum)


def _item_card_numeric_candidate(
    address: int,
    pawn_location: tuple[float, float, float],
    ray: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
    ],
    geometry: dict[str, Any],
) -> dict[str, Any] | None:
    origin, direction = ray
    hit_distance = _item_card_ray_obb_hit(
        origin,
        direction,
        geometry,
    )
    if hit_distance is None:
        return None
    center = geometry["center"]
    center_offset = (
        center[0] - origin[0],
        center[1] - origin[1],
        center[2] - origin[2],
    )
    along = max(0.0, _item_card_dot(center_offset, direction))
    closest = (
        origin[0] + direction[0] * along,
        origin[1] + direction[1] * along,
        origin[2] + direction[2] * along,
    )
    dx = center[0] - closest[0]
    dy = center[1] - closest[1]
    dz = center[2] - closest[2]
    perpendicular = math.sqrt(dx * dx + dy * dy + dz * dz)
    radius = max(float(geometry["radius"]), 1e-9)
    px = center[0] - pawn_location[0]
    py = center[1] - pawn_location[1]
    pz = center[2] - pawn_location[2]
    world_distance = math.sqrt(px * px + py * py + pz * pz)
    return {
        "actor": None,
        "address": address,
        "center": center,
        # Preserve the original sort/debug field names. For the numeric
        # selector these values are expressed in world/ray space.
        "pixel_distance": hit_distance,
        "normalized_distance": perpendicular / radius,
        "world_distance": world_distance,
        "edge_margin": max(0.0, radius - perpendicular),
        "residual": float(geometry["residual"]),
        "ray_hit_distance": hit_distance,
    }


def _item_card_surface_peer_limit(
    state: dict[str, Any],
    target_actor: int,
    peer_actor: int,
    peer_limit: float,
) -> tuple[float, float] | None:
    """Transfer a native witness as distance from the pickup surface."""
    target_geometry = state["pickup_geometry"].get(target_actor)
    peer_geometry = state["pickup_geometry"].get(peer_actor)
    if not isinstance(target_geometry, dict) or not isinstance(
        peer_geometry,
        dict,
    ):
        state["surface_peer_missing_geometry"] += 1
        return None
    target_radius = float(target_geometry.get("radius", 0.0))
    peer_radius = float(peer_geometry.get("radius", 0.0))
    native_limit = float(peer_limit)
    if not (
        math.isfinite(target_radius)
        and math.isfinite(peer_radius)
        and math.isfinite(native_limit)
        and target_radius > 0.0
        and peer_radius > 0.0
    ):
        state["surface_peer_invalid_geometry"] += 1
        return None
    clearance = native_limit - peer_radius
    inferred_limit = clearance + target_radius
    if not (
        math.isfinite(clearance)
        and math.isfinite(inferred_limit)
        and clearance > 0.0
        and inferred_limit > 0.0
    ):
        state["surface_peer_invalid_geometry"] += 1
        return None
    state["surface_peer_samples"] += 1
    state["surface_peer_min_clearance"] = min(
        float(state["surface_peer_min_clearance"]),
        clearance,
    )
    state["surface_peer_max_clearance"] = max(
        float(state["surface_peer_max_clearance"]),
        clearance,
    )
    return inferred_limit, clearance


# item_card_projection.py — consolidated pickup camera geometry.
def _item_card_project(
    pc: Any,
    point: tuple[float, float, float],
) -> tuple[float, float] | None:
    result = pc.ProjectWorldLocationToScreen(
        _make_vector(*point),
        make_struct("Vector2D", X=0.0, Y=0.0),
        False,
    )
    if not bool(result[0]):
        return None
    projected = result[-1]
    return float(projected.X), float(projected.Y)


def _item_card_crosshair_ray(
    pc: Any,
    camera_manager: Any,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
]:
    screen_x, screen_y = _get_tps_crosshair_screen(pc, camera_manager)
    result = pc.DeprojectScreenPositionToWorld(
        screen_x,
        screen_y,
        _make_vector(0.0, 0.0, 0.0),
        _make_vector(0.0, 0.0, 0.0),
    )
    if not bool(result[0]):
        raise RuntimeError("TPS crosshair deprojection failed")
    origin_object, direction_object = result[1], result[2]
    origin = (
        float(origin_object.X),
        float(origin_object.Y),
        float(origin_object.Z),
    )
    direction = (
        float(direction_object.X),
        float(direction_object.Y),
        float(direction_object.Z),
    )
    length = math.sqrt(_item_card_dot(direction, direction))
    if length <= 1e-9:
        raise RuntimeError("TPS crosshair direction has zero length")
    return origin, (
        direction[0] / length,
        direction[1] / length,
        direction[2] / length,
    )


# item_card_numeric_builder.py — consolidated pickup camera geometry.
def _item_card_build_numeric_geometry(
    actor: Any,
    _item_card_read_component_bounds,
) -> dict[str, Any]:
    component = actor.RootComponent
    center, world_extent = _item_card_read_component_bounds(component)
    rotation = _item_card_component_basis(component)
    absolute = [[abs(value) for value in row] for row in rotation]
    half_axes, residual = _item_card_solve_nonnegative(
        absolute,
        world_extent,
    )
    if not any(value > 1e-6 for value in half_axes):
        raise RuntimeError("Pickup OBB has no positive half-axis")
    axes = tuple(
        tuple(float(rotation[row][column]) for row in range(3)) for column in range(3)
    )
    center_values = tuple(float(value) for value in center)
    half_values = tuple(float(value) for value in half_axes)
    return {
        "center": center_values,
        "axes": axes,
        "half_axes": half_values,
        "radius": math.sqrt(
            half_values[0] * half_values[0]
            + half_values[1] * half_values[1]
            + half_values[2] * half_values[2]
        ),
        "residual": float(residual),
    }


# item_card_candidate.py — consolidated pickup camera geometry.
def _item_card_candidate_geometry(
    pc: Any,
    pawn_location: tuple[float, float, float],
    crosshair: tuple[float, float],
    actor: Any,
    _item_card_read_component_bounds,
) -> dict[str, Any] | None:
    component = actor.RootComponent
    center, world_extent = _item_card_read_component_bounds(component)
    rotation = _item_card_component_basis(component)
    absolute = [[abs(value) for value in row] for row in rotation]
    half_axes, residual = _item_card_solve_nonnegative(
        absolute,
        world_extent,
    )
    if not any(value > 1e-6 for value in half_axes):
        return None

    projected: list[tuple[float, float]] = []
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                local = (
                    sx * half_axes[0],
                    sy * half_axes[1],
                    sz * half_axes[2],
                )
                world = tuple(
                    center[row]
                    + sum(rotation[row][column] * local[column] for column in range(3))
                    for row in range(3)
                )
                screen = _item_card_project(pc, world)
                if screen is not None:
                    projected.append(screen)
    hull = _item_card_convex_hull(projected)
    if len(hull) < 3 or not _item_card_point_in_polygon(
        crosshair,
        hull,
    ):
        return None

    projected_center = _item_card_project(pc, center)
    if projected_center is None:
        return None
    pixel_distance = math.hypot(
        projected_center[0] - crosshair[0],
        projected_center[1] - crosshair[1],
    )
    maximum_radius = max(
        math.hypot(
            point[0] - projected_center[0],
            point[1] - projected_center[1],
        )
        for point in hull
    )
    normalized_distance = (
        pixel_distance / maximum_radius if maximum_radius > 1e-9 else 0.0
    )
    world_distance = math.sqrt(
        sum((center[index] - pawn_location[index]) ** 2 for index in range(3))
    )
    edge_margin = min(
        _item_card_segment_distance(
            crosshair,
            hull[index],
            hull[(index + 1) % len(hull)],
        )
        for index in range(len(hull))
    )
    try:
        address = int(actor._get_address())
    except Exception:
        return None
    return {
        "actor": actor,
        "address": address,
        "center": center,
        "pixel_distance": pixel_distance,
        "normalized_distance": normalized_distance,
        "world_distance": world_distance,
        "edge_margin": edge_margin,
        "residual": residual,
    }


# Loader-owned camera motion state and SDK offset setter.
def _set_camera_offset_impl(x: float, y: float, z: float, *, owner_module) -> bool:
    # Refuse invalid coordinates before constructing an Unreal vector.
    if any(
        type(v) not in (int, float) or (type(v) is float and not math.isfinite(v))
        for v in (x, y, z)
    ):
        return False
    x, y, z = (bounded_number(v, 0.0, -2048.0, 2048.0) for v in (x, y, z))
    _pc, pawn, camera_manager = owner_module._get_runtime()
    if camera_manager is None:
        return False
    from . import root_height, shoulder_blend
    x, y, z = root_height.compensate(owner_module, _pc, pawn, camera_manager, (x, y, z))
    x, y, z = shoulder_blend.compensate(x, y, z)
    from . import respawn_camera
    x, y, z = respawn_camera.compensate_offset(owner_module, (x, y, z))
    from . import ffyl_strategy_runtime
    x, y, z = ffyl_strategy_runtime.compensate_entry_offset(owner_module, (x, y, z))
    # Hybrid ADS (omni): scope fades act on the final offset.
    from . import hybrid_ads
    x, y, z = hybrid_ads.compensate(owner_module, x, y, z)
    from . import ground_slam_distance
    x, y, z = ground_slam_distance.compensate(owner_module, _pc, pawn, camera_manager, (x, y, z))
    try:
        camera_mode_state = camera_manager.CameraModeState
        camera_mode_state.CameraLocationOffset = make_struct(
            "Vector",
            X=float(x),
            Y=float(y),
            Z=float(z),
        )
        return True
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not set CameraLocationOffset: "
            f"{type(exc).__name__}: {exc}"
        )
        return False


def _dynamic_motion_reset_impl(*, owner_module) -> None:
    owner_module._dynamic_motion_state.clear()
    owner_module._dynamic_motion_state.update(
        pawn_id=0,
        baseline=None,
        filtered=(0.0, 0.0, 0.0),
        was_airborne=False,
        previous_crouched=None,
        crouch_edge=None,
        crouch_edge_seen_motion=False,
        root_relative=False,
        root_removed_z=0.0,
    )


def _reset_mantle_camera_state_impl(*, owner_module) -> None:
    owner_module._mantle_camera_state.clear()
    owner_module._mantle_camera_state.update(
        pawn_id=0,
        previous=None,
        armed_ladder=False,
        active=False,
        releasing=False,
        baseline_spine_z=None,
        stable_frames=0,
        filtered=(0.0, 0.0, 0.0),
        just_started=False,
        height_fade_logged=False,
        branch="",
        last_error="",
    )


# Apply the loader-owned offset and motion routes.
def _apply_camera_offset_impl(*, owner_module) -> None:
    if owner_module._camera_lifecycle_offset_suppressed():
        owner_module._dynamic_motion_reset()
        owner_module._reset_mantle_camera_state()
        # Lifecycle transitions own the shared camera state.  Clear any TPS
        # offset that was written before the native camera switched modes.
        if (
            not owner_module._vehicle_camera_active
            and not owner_module._shop_camera_active
        ):
            owner_module._set_camera_offset(0.0, 0.0, 0.0)
        return

    if owner_module._vehicle_camera_active or owner_module._shop_camera_active:
        owner_module._dynamic_motion_reset()
        owner_module._reset_mantle_camera_state()
        # Vehicle Camera vollständig BL4 überlassen.
        return

    if (
        owner_module._third_person_enabled
        and owner_module._third_person_pushed
        and (not owner_module._ads_active or owner_module._ads_route == "tps")
    ):
        _pc, pawn, camera_manager = owner_module._get_runtime()
        try:
            mode = (
                str(camera_manager.GetActorCameraMode(pawn))
                if pawn is not None and camera_manager is not None
                else "<runtime unavailable>"
            )
            fps_view = (
                mode == "ThirdPerson"
                and owner_module._looks_like_first_person_fallback()
            )
        except Exception as exc:
            mode = f"<query failed: {type(exc).__name__}>"
            fps_view = False
        from . import ground_slam_distance
        ground_slam_distance.update(owner_module, _pc, pawn, camera_manager, 'Default' if fps_view else mode)
        if mode != "ThirdPerson" or fps_view:
            owner_module._dynamic_motion_reset()
            owner_module._reset_mantle_camera_state()
            reason = f"{mode}:first_person_viewmodel={fps_view}"
            if reason != owner_module._camera_offset_gate_last:
                logging.warning(
                    "[BL4ThirdPersonPOC] TPS_OFFSET_SUPPRESSED "
                    f"mode={mode!r}, fps_view={fps_view}, "
                    f"ads_route={owner_module._ads_route!r}, slide={owner_module._slide_active}"
                )
                owner_module._camera_offset_gate_last = reason
            owner_module._set_camera_offset(0.0, 0.0, 0.0)
            return
        owner_module._camera_offset_gate_last = ""
        hip = position_values(
            (
                owner_module.camera_offset_x,
                owner_module.camera_offset_y,
                owner_module.camera_offset_z,
            )
        )
        owner_module._set_camera_offset(*hip)
        owner_module._apply_mantle_camera_offset(pawn, camera_manager)
        from . import root_height
        root_height.prepare(owner_module, _pc, pawn, camera_manager)
        frame = getattr(owner_module, '_camera_frame', None)
        if frame and frame.get('owner_changed'):
            owner_module._dynamic_motion_reset()
            return
        if frame and any(frame.get('height_local', ())):
            owner_module._set_camera_offset(*hip)
        owner_module._apply_dynamic_motion_camera_offset(pawn, camera_manager)
    else:
        owner_module._dynamic_motion_reset()
        owner_module._reset_mantle_camera_state()
        owner_module._camera_offset_gate_last = ""
        owner_module._set_camera_offset(0.0, 0.0, 0.0)
