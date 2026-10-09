"""Register SDK events and implement interaction/item-card event processing.

The loader owns callbacks and mutable state. Prompt traces, candidate geometry,
native gate witnesses and final selection are coordinated from existing updates.
PRE/POST hooks preserve floor-pickup priority and defer to native Use processing.
Diagnostic probes are bounded; menu work runs only while the menu is open.
Camera event functions are re-exported for the loader; shutdown is delegated to
the dependency-aware coordinator. No hooks are installed at module import.
Pickup enumeration and geometry budgets retain the baseline scheduling policy.
"""

from __future__ import annotations

import ctypes
import math
import time
import struct
from typing import Any
from . import runtime_updates
from .mod_shutdown import shutdown as _shutdown_mod_runtime

from mods_base import get_pc
from unrealsdk import find_object, logging, make_struct
from unrealsdk.hooks import Type, add_hook, has_hook, remove_hook
from .camera_math import (
    _get_world_location,
    _item_card_numeric_candidate,
    _item_card_surface_peer_limit,
    _item_card_crosshair_ray,
    _item_card_dot,
)
from .native_memory import (
    ITEM_CARD_GATE2_GRACE_UPDATES,
    ITEM_CARD_STABLE_SELECTION_SAMPLES,
    ITEM_CARD_MAX_DEBUG_EVENTS,
    ITEM_CARD_PICKUP_REFRESH_INTERVAL,
    ITEM_CARD_GEOMETRY_TRACK_BUDGET,
    ITEM_CARD_GEOMETRY_BACKGROUND_BUDGET,
    ITEM_CARD_GEOMETRY_COLLAPSE_RATIO,
    ITEM_CARD_GEOMETRY_CENTER_EPSILON,
    ITEM_CARD_GEOMETRY_AXIS_EPSILON,
    ITEM_CARD_GEOMETRY_STABLE_SAMPLES,
    ITEM_CARD_GEOMETRY_TRACK_TIMEOUT,
)

# ServerUseObject PRE: usables whose interaction pushes StructuredInteraction.
# The owned native state is restored before that push (see the redirect hook).
NATIVE_PRE_RESTORE_USABLES = {
    "OakCharacter": "npc_server_use_pre",
    "OakVendingMachine": "shop_server_use_pre",
}


def _npc_trace_actor(result: Any) -> tuple[Any, Any]:
    if not bool(result[0]):
        return None, None
    hit = result[-1]
    component = getattr(hit, "Component", None)
    return (getattr(component, "Outer", None) if component is not None else None), hit


def _npc_line_trace(library: Any, pc: Any, pawn: Any, start: Any, end: Any) -> Any:
    return library.LineTraceSingle(
        pc,
        start,
        end,
        1,
        True,
        [pawn],
        0,
        make_struct("HitResult"),
        False,
        make_struct("LinearColor", R=1.0, G=0.0, B=0.0, A=1.0),
        make_struct("LinearColor", R=0.0, G=1.0, B=0.0, A=1.0),
        0.0,
    )


def _npc_reset_tracking(state: dict[str, Any], pawn_address: int = 0) -> None:
    state["flags"][0] = 0
    state["flags"][1] = 0
    state["candidate_slot"].value = 0
    state["npc_ptr"] = 0
    state["npc_path"] = None
    state["candidate_ready"] = False
    state["pawn_ptr"] = pawn_address


def _interaction_prompt_trace_base(
    *,
    _get_runtime,
    _get_tps_crosshair_screen,
    _make_vector,
    INTERACTION_TRACE_DISTANCE,
) -> tuple[tuple[float, float, float], str, str]:
    pc, pawn, camera_manager = _get_runtime()
    if pc is None or pawn is None or camera_manager is None:
        raise RuntimeError("Player runtime is not ready")
    screen_x, screen_y = _get_tps_crosshair_screen(pc, camera_manager)
    deproject = pc.DeprojectScreenPositionToWorld(
        screen_x,
        screen_y,
        _make_vector(0.0, 0.0, 0.0),
        _make_vector(0.0, 0.0, 0.0),
    )
    if not bool(deproject[0]):
        raise RuntimeError("TPS crosshair deprojection failed")
    start, direction = deproject[1], deproject[2]
    direction_length = math.sqrt(
        float(direction.X) ** 2 + float(direction.Y) ** 2 + float(direction.Z) ** 2
    )
    if direction_length <= 1.0e-8:
        raise RuntimeError("TPS crosshair direction has zero length")
    unit = (
        float(direction.X) / direction_length,
        float(direction.Y) / direction_length,
        float(direction.Z) / direction_length,
    )
    end_values = (
        float(start.X) + unit[0] * INTERACTION_TRACE_DISTANCE,
        float(start.Y) + unit[1] * INTERACTION_TRACE_DISTANCE,
        float(start.Z) + unit[2] * INTERACTION_TRACE_DISTANCE,
    )
    system_library = find_object(
        "KismetSystemLibrary",
        "/Script/Engine.Default__KismetSystemLibrary",
    )
    trace = system_library.LineTraceSingle(
        pc,
        start,
        _make_vector(*end_values),
        5,  # IO_VaultPower.UseTraceSphere responds to TraceTypeQuery 5
        True,
        [pawn],
        0,
        make_struct("HitResult"),
        True,
        make_struct("LinearColor", R=1.0, G=0.0, B=0.0, A=1.0),
        make_struct("LinearColor", R=0.0, G=1.0, B=0.0, A=1.0),
        0.0,
    )
    if not bool(trace[0]):
        return end_values, "None", "None"

    hit = trace[-1]
    point = getattr(hit, "ImpactPoint", None)
    if point is None:
        point = getattr(hit, "Location", None)
    if point is None:
        point_values = (
            float(start.X) + unit[0] * float(hit.Distance),
            float(start.Y) + unit[1] * float(hit.Distance),
            float(start.Z) + unit[2] * float(hit.Distance),
        )
    else:
        point_values = (float(point.X), float(point.Y), float(point.Z))

    actor = None
    if hit.Component is not None:
        actor = hit.Component.Outer
    if actor is None:
        reference = hit.HitObjectHandle.ReferenceObject
        if reference is not None:
            actor = getattr(reference, "Outer", reference)
    if actor is None:
        return point_values, "None", "None"
    try:
        class_name = str(actor.Class.Name)
    except Exception:
        class_name = type(actor).__name__
    try:
        path = str(actor._path_name())
    except Exception:
        path = repr(actor)
    return point_values, class_name, path


def _interaction_prompt_trace(
    *,
    _npc_eligible_state,
    _third_person_enabled,
    _ads_active,
    _interaction_prompt_trace_base,
    _get_runtime,
    _get_tps_crosshair_screen,
    _make_vector,
    NPC_ELIGIBLE_CANDIDATE_OFFSET,
    _native_require_readable,
    _native_read,
    _get_actor_eye_location,
) -> tuple[tuple[float, float, float], str, str]:
    state = _npc_eligible_state
    if not isinstance(state, dict) or not state.get("ready"):
        return _interaction_prompt_trace_base()
    flags = state["flags"]
    flags[0] = 0
    flags[1] = 0
    baseline = _interaction_prompt_trace_base()
    try:
        if not _third_person_enabled or _ads_active:
            return baseline
        pc, pawn, camera = _get_runtime()
        if pc is None or pawn is None or camera is None:
            return baseline
        pawn_ptr = int(pawn._get_address())
        if pawn_ptr != state["pawn_ptr"]:
            _npc_reset_tracking(state, pawn_ptr)
            state["pawn_resets"] += 1
        library = find_object(
            "KismetSystemLibrary", "/Script/Engine.Default__KismetSystemLibrary"
        )
        sx, sy = _get_tps_crosshair_screen(pc, camera)
        deproject = pc.DeprojectScreenPositionToWorld(
            sx, sy, _make_vector(0.0, 0.0, 0.0), _make_vector(0.0, 0.0, 0.0)
        )
        if not bool(deproject[0]):
            return baseline
        origin, direction = deproject[1:3]
        direction_xyz = tuple(float(getattr(direction, axis)) for axis in "XYZ")
        norm = math.sqrt(sum(axis * axis for axis in direction_xyz))
        if norm <= 1.0e-8:
            return baseline
        camera_end = _make_vector(
            *(
                float(getattr(origin, axis)) + direction_xyz[index] * 5000.0 / norm
                for index, axis in enumerate("XYZ")
            )
        )
        actor, hit = _npc_trace_actor(
            _npc_line_trace(library, pc, pawn, origin, camera_end)
        )
        actor_ptr = int(actor._get_address()) if actor is not None else 0
        if actor_ptr and actor_ptr != pawn_ptr:
            path = str(actor._path_name())
            try:
                npc = find_object("OakCharacter", path)
            except ValueError:
                npc = None
            if npc is not None and int(npc._get_address()) == actor_ptr:
                if actor_ptr != state["npc_ptr"]:
                    state["npc_ptr"] = actor_ptr
                    state["npc_path"] = path
                    state["candidate_slot"].value = 0
                    state["candidate_ready"] = False
        npc_ptr = state["npc_ptr"]
        if not npc_ptr:
            return baseline
        path = state["npc_path"]
        try:
            live_npc = find_object("OakCharacter", path)
        except ValueError:
            live_npc = None
        if live_npc is None or int(live_npc._get_address()) != npc_ptr:
            _npc_reset_tracking(state, pawn_ptr)
            return baseline
        candidate = npc_ptr + NPC_ELIGIBLE_CANDIDATE_OFFSET
        _native_require_readable(candidate, 0x28, "current NPC candidate")
        ready = struct.unpack("<Q", _native_read(candidate + 0x20, 8))[0] == candidate
        if ready != state["candidate_ready"]:
            state["candidate_ready"] = ready
            if ready:
                state["activations"] += 1
        if not ready:
            state["candidate_slot"].value = 0
            state["inactive_frames"] += 1
            return baseline
        state["candidate_slot"].value = candidate
        selected = None
        if actor_ptr == npc_ptr and hit is not None:
            point = hit.ImpactPoint
            eye = _get_actor_eye_location(pawn)
            delta = tuple(
                float(getattr(point, axis) - getattr(eye, axis)) for axis in "XYZ"
            )
            distance = math.sqrt(sum(value * value for value in delta))
            if distance > 1.0e-8:
                ahead = _make_vector(
                    *(
                        float(getattr(point, axis)) + delta[index] * 50.0 / distance
                        for index, axis in enumerate("XYZ")
                    )
                )
                eye_actor, _ = _npc_trace_actor(
                    _npc_line_trace(library, pc, pawn, eye, ahead)
                )
                if eye_actor is not None and int(eye_actor._get_address()) == npc_ptr:
                    selected = tuple(float(getattr(point, axis)) for axis in "XYZ")
        flags[1] = int(selected is not None)
        flags[0] = 1
        if selected is not None:
            state["on_npc"] += 1
            return selected, "OakCharacter", path
        state["off_npc"] += 1
    except Exception as exc:
        flags[0] = 0
        state["errors"] += 1
        if state["errors"] <= 3:
            logging.error(
                "[BL4ThirdPersonPOC] NPC_ELIGIBLE_FRAME_ERROR "
                f"{type(exc).__name__}: {exc}"
            )
    return baseline


def _interaction_prompt_update_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    _interaction_prompt_state,
    _item_card_should_override,
    _interaction_prompt_trace,
    INTERACTION_PROMPT_NATIVE_RAY_LENGTH,
) -> None:
    state = _interaction_prompt_state
    if not isinstance(state, dict) or not state.get("ready"):
        return
    control = state["control"]
    if not _item_card_should_override():
        control.enabled = 0
        state["active"] = False
        return
    try:
        point, hit_class, hit_path = _interaction_prompt_trace()
        if not all(math.isfinite(value) for value in point):
            raise RuntimeError(f"Non-finite TPS point: {point!r}")
        active_index = int(state["active_point_index"])
        next_index = 1 - active_index
        target = state["point_buffers"][next_index]
        target[0], target[1], target[2] = point
        target[3] = INTERACTION_PROMPT_NATIVE_RAY_LENGTH
        state["point_pointer"].value = ctypes.addressof(target)
        state["active_point_index"] = next_index
        state["updates"] += 1
        state["last_hit_class"] = hit_class
        state["last_hit_path"] = hit_path
        key = (hit_class, hit_path)
        if key != state.get("last_transition"):
            state["last_transition"] = key
            state["transitions"] += 1
        state["active"] = True
        control.enabled = 1
    except Exception as exc:
        control.enabled = 0
        state["active"] = False
        state["update_errors"] += 1
        state["last_update_error"] = f"{type(exc).__name__}: {exc}"


# Menu hook ownership. Installation remains at the same point in menu open.
def _menu_hook_installed(path: str, identifier: str) -> bool:
    return runtime_updates.has_hook(path, Type.POST_UNCONDITIONAL, identifier)


def _menu_hook_remove(path: str, identifier: str) -> None:
    runtime_updates.remove_hook(path, Type.POST_UNCONDITIONAL, identifier)


def _menu_hook_install(path: str, identifier: str, callback: Any) -> bool:
    # Rebind only this menu's identity; other observers remain untouched.
    kind = Type.POST_UNCONDITIONAL
    try:
        if runtime_updates.has_hook(path, kind, identifier):
            runtime_updates.remove_hook(path, kind, identifier)
        if runtime_updates.has_hook(path, kind, identifier):
            logging.error(
                "[BL4ThirdPersonPOC] MENU_HOOK_REBIND_REFUSED identifier=" + identifier
            )
            return False
        result = runtime_updates.add_hook(path, kind, identifier, callback)
        registered = runtime_updates.has_hook(path, kind, identifier)
        logging.info(
            f"[BL4ThirdPersonPOC] MENU_HOOK_BIND result={result!r} registered={registered}"
        )
        return registered
    except Exception as exc:
        # The caller may use the verified camera updater as its menu dispatcher.
        logging.warning(
            f"[BL4ThirdPersonPOC] MENU_HOOK_BIND_EXCEPTION {type(exc).__name__}: {exc}"
        )
        return False


def _menu_poll_impl(
    _obj: Any,
    _args: Any,
    _ret: Any,
    _func: Any,
    *,
    _get_menu_state,
    _third_person_enabled,
    _menu_close,
    _set_dynamic_motion_enabled,
    _get_dynamic_motion_enabled,
    camera_offset_x,
    camera_offset_y,
    camera_offset_z,
) -> None:
    state = _get_menu_state()
    if state is None or state["closed"]:
        return
    try:
        pc = get_pc()
        if (
            pc != state["pc"]
            or getattr(pc, "OakCharacter", None) != state["pawn"]
        ):
            _menu_close("context_changed")
            return
        if state.get("console"):
            from .menu_console import dispatch

            dispatch(
                state,
                (camera_offset_x, camera_offset_y, camera_offset_z),
                _menu_close,
                _get_dynamic_motion_enabled,
                _set_dynamic_motion_enabled,
            )
            return
        if state["close"].IsPressed() and not state["close_down"]:
            _menu_close("button")
            return
        state["close_down"] = bool(state["close"].IsPressed())
        for index, button in enumerate(state["tabs"]):
            down = bool(button.IsPressed())
            if down and not state["tabs_down"][index]:
                state["switcher"].SetActiveWidgetIndex(index)
            state["tabs_down"][index] = down
        down = bool(state["dynamic_motion_button"].IsPressed())
        if down and not state["dynamic_motion_down"]:
            _set_dynamic_motion_enabled(not _get_dynamic_motion_enabled())
            state["dynamic_motion_label"].SetText(
                f"Dynamic Camera Motion: {'ON' if _get_dynamic_motion_enabled() else 'OFF'}"
            )
        state["dynamic_motion_down"] = down
        now = time.perf_counter_ns()
        for index, (slider, option) in enumerate(
            zip(state["sliders"], (camera_offset_x, camera_offset_y, camera_offset_z))
        ):
            pressed_any = False
            for side, button in enumerate(state["steps"][index]):
                down = bool(button.IsPressed())
                if down and not state["steps_down"][index][side]:
                    lo, hi = state["ranges"][index]
                    new = max(
                        lo, min(hi, state["values"][index] + (-10, -1, 1, 10)[side])
                    )
                    option.value = new
                    state["values"][index] = new
                    state["dirty"] = True
                    slider.SetValue(float(new))
                    state["labels"][index].SetText(
                        f"{'XYZ'[index]}: {new}   [{lo} .. {hi}]"
                    )
                    state["last_write"][index] = now
                    pressed_any = True
                state["steps_down"][index][side] = down
            if pressed_any:
                continue
            raw = float(slider.GetValue())
            if not math.isfinite(raw):
                continue
            lo, hi = state["ranges"][index]
            value = max(
                lo, min(hi, int(math.copysign(math.floor(abs(raw) + 0.5), raw)))
            )
            if (
                value != state["values"][index]
                and now - state["last_write"][index] >= 50_000_000
            ):
                option.value = value
                state["values"][index] = value
                state["dirty"] = True
                slider.SetValue(float(value))
                state["labels"][index].SetText(
                    f"{'XYZ'[index]}: {value}   [{lo} .. {hi}]"
                )
                state["last_write"][index] = now
    except Exception as exc:
        logging.error(
            f"[BL4ThirdPersonPOC] MENU_POLL_FAILED {type(exc).__name__}: {exc}"
        )
        _menu_close("poll_error")


# Read-only camera and stack probes. The loader owns callback identities.
def _camera_mode_request_hook_impl(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
    *,
    _third_person_enabled,
    _third_person_pushed,
    _slide_active,
    _ads_active,
) -> None:
    logging.info("[BL4ThirdPersonPOC] ===== CAMERA MODE REQUEST =====")
    logging.info("[BL4ThirdPersonPOC] " f"caller={obj!r}")
    logging.info("[BL4ThirdPersonPOC] " f"args={args!r}")
    logging.info(
        "[BL4ThirdPersonPOC] "
        f"third_person_enabled={_third_person_enabled}, "
        f"third_person_pushed={_third_person_pushed}, "
        f"slide_active={_slide_active}, "
        f"ads_active={_ads_active}"
    )

    try:
        argument_names = sorted(name for name in dir(args) if not name.startswith("_"))
    except Exception:
        argument_names = []

    for name in argument_names:
        try:
            value = getattr(args, name)

            if callable(value):
                continue

            logging.info("[BL4ThirdPersonPOC] " f"CameraModeArgs.{name} = {value!r}")

        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not read "
                f"CameraModeArgs.{name}: "
                f"{type(exc).__name__}: {exc}"
            )

    logging.info("[BL4ThirdPersonPOC] ===== END CAMERA MODE REQUEST =====")


def _log_camera_stack_request_impl(
    operation: str,
    obj: Any,
    args: Any,
    *,
    _third_person_enabled,
    _third_person_pushed,
    _slide_active,
    _ads_active,
) -> None:
    logging.info("[BL4ThirdPersonPOC] " f"===== {operation.upper()} REQUEST =====")
    logging.info("[BL4ThirdPersonPOC] " f"caller={obj!r}")
    logging.info("[BL4ThirdPersonPOC] " f"args={args!r}")
    logging.info(
        "[BL4ThirdPersonPOC] "
        f"third_person_enabled={_third_person_enabled}, "
        f"third_person_pushed={_third_person_pushed}, "
        f"slide_active={_slide_active}, "
        f"ads_active={_ads_active}"
    )

    try:
        argument_names = sorted(name for name in dir(args) if not name.startswith("_"))
    except Exception:
        argument_names = []

    for name in argument_names:
        try:
            value = getattr(args, name)

            if callable(value):
                continue

            logging.info("[BL4ThirdPersonPOC] " f"{operation}Args.{name} = {value!r}")

        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not read "
                f"{operation}Args.{name}: "
                f"{type(exc).__name__}: {exc}"
            )

    logging.info("[BL4ThirdPersonPOC] " f"===== END {operation.upper()} REQUEST =====")


def _install_camera_stack_probes_impl(
    *,
    _camera_stack_probes_installed,
    _remove_camera_stack_probes,
    PUSH_ACTOR_CAMERA_MODE_FUNCTION,
    POP_ACTOR_CAMERA_MODE_FUNCTION,
    _push_actor_camera_mode_probe,
    _pop_actor_camera_mode_probe,
    CAMERA_STACK_PROBE_IDENTIFIER,
) -> None:
    if _camera_stack_probes_installed:
        _remove_camera_stack_probes()
    if _camera_stack_probes_installed:
        logging.error(
            "[BL4ThirdPersonPOC] Camera-stack probe installation refused: "
            "older tracked probes could not be removed"
        )
        return

    probes = (
        (
            PUSH_ACTOR_CAMERA_MODE_FUNCTION,
            _push_actor_camera_mode_probe,
        ),
        (
            POP_ACTOR_CAMERA_MODE_FUNCTION,
            _pop_actor_camera_mode_probe,
        ),
    )

    for function_path, callback in probes:
        try:
            if add_hook(
                function_path,
                Type.PRE,
                CAMERA_STACK_PROBE_IDENTIFIER,
                callback,
            ):
                _camera_stack_probes_installed.append(function_path)
                logging.info(
                    "[BL4ThirdPersonPOC] Installed "
                    f"camera stack probe: {function_path}"
                )
            else:
                logging.warning(
                    "[BL4ThirdPersonPOC] Camera stack "
                    f"probe already exists: {function_path}"
                )

        except Exception as exc:
            logging.error(
                "[BL4ThirdPersonPOC] Could not install "
                f"camera stack probe {function_path}: "
                f"{type(exc).__name__}: {exc}"
            )


def _remove_camera_stack_probes_impl(
    *, _camera_stack_probes_installed, CAMERA_STACK_PROBE_IDENTIFIER
) -> None:
    remaining = []
    for function_path in _camera_stack_probes_installed:
        try:
            remove_hook(
                function_path,
                Type.PRE,
                CAMERA_STACK_PROBE_IDENTIFIER,
            )
        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not remove "
                f"camera stack probe {function_path}: "
                f"{type(exc).__name__}: {exc}"
            )
            remaining.append(function_path)
    _camera_stack_probes_installed[:] = remaining


# Ordered SDK hook registries; caller retains live ownership lists.
def _install_hybrid_ads_hooks_impl(
    *,
    _ads_hooks_installed,
    _remove_hybrid_ads_hooks,
    ADS_ZOOM_CHANGE_FUNCTION,
    ADS_ZOOM_CHANGE_IDENTIFIER,
    _hybrid_ads_zoom_change_hook,
    ADS_ZOOMED_OUT_FUNCTION,
    ADS_ZOOMED_OUT_IDENTIFIER,
    _hybrid_ads_zoomed_out_hook,
    ADS_WEAPON_EQUIPPED_FUNCTION,
    ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER,
    ADS_WEAPON_EQUIPPED_POST_IDENTIFIER,
    _hybrid_ads_weapon_equipped_pre_hook,
    _hybrid_ads_weapon_equipped_post_hook,
    ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
    ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER,
    ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER,
    _hybrid_ads_character_weapon_equipped_pre_hook,
    _hybrid_ads_character_weapon_equipped_post_hook,
    _ads_debug_error,
) -> None:
    if _ads_hooks_installed:
        _remove_hybrid_ads_hooks()
    if _ads_hooks_installed:
        logging.error(
            "[BL4ThirdPersonPOC] Hybrid ADS hook installation refused: "
            "older tracked hooks could not be removed"
        )
        return
    for function_path, identifier, callback, hook_type in (
        (
            ADS_ZOOM_CHANGE_FUNCTION,
            ADS_ZOOM_CHANGE_IDENTIFIER,
            _hybrid_ads_zoom_change_hook,
            Type.PRE,
        ),
        (
            ADS_ZOOMED_OUT_FUNCTION,
            ADS_ZOOMED_OUT_IDENTIFIER,
            _hybrid_ads_zoomed_out_hook,
            Type.PRE,
        ),
        (
            ADS_WEAPON_EQUIPPED_FUNCTION,
            ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER,
            _hybrid_ads_weapon_equipped_pre_hook,
            Type.PRE,
        ),
        (
            ADS_WEAPON_EQUIPPED_FUNCTION,
            ADS_WEAPON_EQUIPPED_POST_IDENTIFIER,
            _hybrid_ads_weapon_equipped_post_hook,
            Type.POST,
        ),
        (
            ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
            ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER,
            _hybrid_ads_character_weapon_equipped_pre_hook,
            Type.PRE,
        ),
        (
            ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
            ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER,
            _hybrid_ads_character_weapon_equipped_post_hook,
            Type.POST,
        ),
    ):
        try:
            remove_hook(function_path, hook_type, identifier)
        except Exception:
            pass
        try:
            if add_hook(function_path, hook_type, identifier, callback):
                _ads_hooks_installed.append((function_path, hook_type, identifier))
            else:
                raise RuntimeError("add_hook returned False")
        except Exception as exc:
            _ads_debug_error(f"hook_install:{identifier}", exc)
    logging.info(
        "[BL4ThirdPersonPOC] Hybrid ADS hooks "
        f"installed={len(_ads_hooks_installed)}/6"
    )


def _remove_hybrid_ads_hooks_impl(*, _ads_hooks_installed, _ads_debug_error) -> None:
    remaining = []
    for function_path, hook_type, identifier in reversed(_ads_hooks_installed):
        try:
            remove_hook(function_path, hook_type, identifier)
        except Exception as exc:
            _ads_debug_error(f"hook_remove:{identifier}", exc)
            remaining.append((function_path, hook_type, identifier))
    _ads_hooks_installed[:] = reversed(remaining)


def _install_hooks_impl(
    *,
    _hooks_installed,
    _remove_hooks,
    FIRST_PERSON_ANIM_HOOK,
    HOOK_IDENTIFIER,
    _camera_update_hook,
) -> None:
    if _hooks_installed:
        _remove_hooks()
    if _hooks_installed:
        logging.error(
            "[BL4ThirdPersonPOC] Camera updater installation refused: "
            "an older tracked hook could not be removed"
        )
        return

    try:
        add_reported = bool(
            add_hook(
                FIRST_PERSON_ANIM_HOOK,
                Type.POST,
                HOOK_IDENTIFIER,
                _camera_update_hook,
            )
        )
        registered = bool(has_hook(FIRST_PERSON_ANIM_HOOK, Type.POST, HOOK_IDENTIFIER))
        logging.info(
            "[BL4ThirdPersonPOC] CAMERA_UPDATE_HOOK_BIND "
            f"add_reported={add_reported} registered={registered}"
        )
        if registered:
            _hooks_installed.append(FIRST_PERSON_ANIM_HOOK)

            logging.info(
                "[BL4ThirdPersonPOC] Installed "
                "game-thread camera update hook: "
                f"{FIRST_PERSON_ANIM_HOOK}"
            )

    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not install "
            "game-thread camera update hook: "
            f"{type(exc).__name__}: {exc}"
        )


def _remove_hooks_impl(*, _hooks_installed, HOOK_IDENTIFIER) -> None:
    remaining = []
    for function_path in _hooks_installed:
        try:
            remove_hook(
                function_path,
                Type.POST,
                HOOK_IDENTIFIER,
            )
            # Removal return values alone do not prove registration is gone.
            if has_hook(function_path, Type.POST, HOOK_IDENTIFIER):
                raise RuntimeError("Camera updater hook remains registered")
        except Exception as exc:
            logging.warning(
                f"[BL4ThirdPersonPOC] Could not remove hook "
                f"{function_path}: "
                f"{type(exc).__name__}: {exc}"
            )
            remaining.append(function_path)
    _hooks_installed[:] = remaining


# item_card_collection.py — consolidated item-card game-thread behavior.
def _item_card_collect_pickups(
    state: dict[str, Any],
    *,
    force_geometry: bool = False,
    settle_addresses: set[int] | None = None,
    _perf_probe,
    find_all,
    _item_card_build_numeric_geometry,
    _perf_record_metric,
) -> tuple[dict[int, str], dict[int, dict[str, Any]], set[int]]:
    started = time.perf_counter()
    paths: dict[int, str] = {}
    previous_geometry = state.get("pickup_geometry", {})
    geometry = dict(previous_geometry)
    settle = settle_addresses or set()
    build_attempts = 0
    failed: set[int] = set()
    profiling = bool(_perf_probe["armed"])
    find_started_ns = time.perf_counter_ns() if profiling else 0
    pickups = tuple(find_all("InventoryPickup"))
    find_ns = time.perf_counter_ns() - find_started_ns if profiling else 0
    geometry_ns = 0
    for pickup in pickups:
        try:
            path = str(pickup._path_name())
            if "Default__" in path or bool(pickup.bHidden):
                continue
            address = int(pickup._get_address())
            if address:
                paths[address] = path
                if (
                    force_geometry
                    or address not in previous_geometry
                    or address in settle
                ):
                    build_attempts += 1
                    try:
                        geometry_started_ns = time.perf_counter_ns() if profiling else 0
                        geometry[address] = _item_card_build_numeric_geometry(pickup)
                    except Exception as exc:
                        failed.add(address)
                        state["geometry_cache_errors"] += 1
                        state["last_geometry_cache_error"] = (
                            f"actor=0x{address:016X}, path={path}, "
                            f"{type(exc).__name__}: {exc}"
                        )
                    finally:
                        if profiling:
                            geometry_ns += time.perf_counter_ns() - geometry_started_ns
        except Exception as exc:
            state["pickup_scan_errors"] += 1
            state["last_pickup_scan_error"] = f"{type(exc).__name__}: {exc}"
            continue
    geometry = {
        address: value for address, value in geometry.items() if address in paths
    }
    scan_elapsed = time.perf_counter() - started
    if profiling:
        collect_ns = time.perf_counter_ns() - find_started_ns
        inspect_ns = max(0, collect_ns - find_ns - geometry_ns)
        _perf_probe["item_scan"] = {
            "found": len(pickups),
            "visible": len(paths),
            "find_ns": find_ns,
            "inspect_ns": inspect_ns,
            "geometry_ns": geometry_ns,
            "collect_ns": collect_ns,
        }
        _perf_record_metric("item.find", find_ns)
        _perf_record_metric("item.inspect", inspect_ns)
        _perf_record_metric("item.geometry", geometry_ns)
    state["pickup_scans"] += 1
    state["pickup_scan_seconds"] += scan_elapsed
    state["pickup_scan_max_seconds"] = max(
        float(state["pickup_scan_max_seconds"]),
        scan_elapsed,
    )
    if build_attempts:
        state["geometry_cache_builds"] += 1
        state["geometry_cache_attempts"] += build_attempts
        state["geometry_cache_seconds"] += scan_elapsed
        state["geometry_cache_max_seconds"] = max(
            float(state["geometry_cache_max_seconds"]),
            scan_elapsed,
        )
    # Deliberately do not retain UObject wrappers. Only immutable addresses,
    # path strings, and numeric OBB data may outlive this callback.
    return paths, geometry, failed


def _perf_finish_item_refresh(
    started_ns: int,
    paths: dict[int, str],
    old_paths: dict[int, str],
    rebuild_ns: int,
    _perf_probe,
    _perf_record_metric,
    _perf_record_top,
) -> None:
    probe = _perf_probe
    if not probe["armed"]:
        return
    scan = probe.get("item_scan")
    if scan is None:
        return
    total_ns = time.perf_counter_ns() - started_ns
    scan = dict(scan)
    scan["new"] = len(paths.keys() - old_paths.keys())
    scan["rebuilt"] = bool(rebuild_ns)
    scan["rebuild_ns"] = rebuild_ns
    scan["other_ns"] = max(0, total_ns - scan["collect_ns"] - rebuild_ns)
    _perf_record_metric("item.refresh", total_ns)
    _perf_record_metric("item.rebuild", rebuild_ns)
    _perf_record_metric("item.other", scan["other_ns"])
    probe["item_frame"] = scan
    _perf_record_top(
        probe["slow_item"],
        (total_ns, probe["frames"], time.perf_counter_ns() - probe["started_ns"], scan),
    )


# item_card_selection.py — consolidated item-card game-thread behavior.
def _item_card_active_gate2_actors(
    state: dict[str, Any],
) -> dict[int, int]:
    current = int(state["update_index"])
    return {
        actor: current - int(last_seen)
        for actor, last_seen in state["gate2_last_seen_update"].items()
        if current - int(last_seen) <= ITEM_CARD_GATE2_GRACE_UPDATES
    }


def _item_card_select(
    state: dict[str, Any],
    pc: Any,
    pawn: Any,
    camera_manager: Any,
) -> tuple[int, Any, dict[str, Any] | None, int, int]:
    select_started = time.perf_counter()
    ray_started = time.perf_counter()
    ray = _item_card_crosshair_ray(pc, camera_manager)
    pawn_vector = _get_world_location(pawn)
    pawn_location = (
        float(pawn_vector.X),
        float(pawn_vector.Y),
        float(pawn_vector.Z),
    )
    state["selector_ray_seconds"] += time.perf_counter() - ray_started

    # The hot path deliberately touches numeric cache entries only. UObject
    # discovery, hidden-state checks, component bounds, and OBB reconstruction
    # are confined to the half-second snapshot lifecycle above.
    candidate_started = time.perf_counter()
    active = _item_card_active_gate2_actors(state)
    candidates = []
    known = state["pickups"]
    for address, geometry in state["pickup_geometry"].items():
        if address not in known:
            continue
        state["numeric_candidate_tests"] += 1
        candidate = _item_card_numeric_candidate(
            address,
            pawn_location,
            ray,
            geometry,
        )
        if candidate is not None:
            state["numeric_ray_hits"] += 1
            candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            item["normalized_distance"],
            item["world_distance"],
            item["pixel_distance"],
            item["address"],
        )
    )
    state["selector_candidate_seconds"] += time.perf_counter() - candidate_started
    policy_started = time.perf_counter()
    eligible = []
    forced_actor = int(state["forced_unlearned_actor"])
    for item in candidates:
        address = int(item["address"])
        distance = float(item["world_distance"])
        is_forced = bool(forced_actor and address == forced_actor)
        if is_forced and address in active:
            state["forced_native_ignored"] += 1
        if address in active and not is_forced:
            previous = state["native_max_world"].get(address)
            if previous is None or distance > float(previous):
                state["native_max_world"][address] = distance
            state["native_peer_center"][address] = tuple(item["center"])
            state["peer_max_world"].pop(address, None)
            state["peer_source_actor"].pop(address, None)
            state["peer_source_separation"].pop(address, None)
            item["selection_source"] = "native"
            item["learned_distance"] = float(state["native_max_world"][address])
            eligible.append(item)
            continue
        learned = state["native_max_world"].get(address)
        inferred = state["peer_max_world"].get(address)
        had_inferred = inferred is not None
        peer_actor = state["peer_source_actor"].get(address)
        if learned is None:
            locked_witnesses = state["forced_peer_witnesses"]
            if is_forced and locked_witnesses:
                peer_options = [
                    (float(limit), int(peer))
                    for peer, limit in locked_witnesses.items()
                    if peer != address
                ]
            else:
                peer_options = [
                    (
                        math.sqrt(
                            sum(
                                (
                                    float(item["center"][axis])
                                    - float(state["native_peer_center"][peer][axis])
                                )
                                ** 2
                                for axis in range(3)
                            )
                        ),
                        float(limit),
                        int(peer),
                    )
                    for peer, limit in state["native_max_world"].items()
                    if (
                        peer != address
                        and peer != forced_actor
                        and peer in state["pickups"]
                        and peer in state["native_peer_center"]
                    )
                ]
            if peer_options:
                if is_forced and locked_witnesses:
                    best_limit, best_peer = max(
                        peer_options,
                        key=lambda option: (option[0], -option[1]),
                    )
                    best_separation = 0.0
                else:
                    best_separation, best_limit, best_peer = min(
                        peer_options,
                        key=lambda option: (
                            option[0],
                            -option[1],
                            option[2],
                        ),
                    )
                surface_result = _item_card_surface_peer_limit(
                    state,
                    address,
                    best_peer,
                    best_limit,
                )
                if surface_result is None:
                    state["peer_bootstrap_no_witness"] += 1
                    inferred = None
                    peer_actor = None
                    state["peer_max_world"].pop(address, None)
                    state["peer_source_actor"].pop(address, None)
                    state["peer_source_separation"].pop(address, None)
                else:
                    surface_limit, surface_clearance = surface_result
                    previous_peer = peer_actor
                    if (
                        inferred is None
                        or previous_peer != best_peer
                        or abs(float(inferred) - surface_limit) > 1.0e-6
                    ):
                        inferred = surface_limit
                        peer_actor = best_peer
                        state["peer_max_world"][address] = inferred
                        state["peer_source_actor"][address] = peer_actor
                        state["peer_source_separation"][address] = best_separation
                        state["peer_limit_updates"] += 1
                        state["surface_peer_limit_updates"] += 1
                    item["surface_clearance"] = surface_clearance
                if surface_result is not None:
                    peer_actor = best_peer
                    item["peer_actor"] = peer_actor
                    if not had_inferred:
                        if distance <= inferred:
                            state["peer_bootstrap_accepts"] += 1
                            state["fallback_accepts"] += 1
                            item["selection_source"] = (
                                "forced_surface_bootstrap"
                                if is_forced
                                else "surface_bootstrap"
                            )
                            item["learned_distance"] = inferred
                            eligible.append(item)
                            continue
                        state["peer_bootstrap_farther"] += 1
            elif inferred is None:
                state["peer_bootstrap_no_witness"] += 1
        if learned is None:
            learned = inferred
        item["learned_distance"] = learned
        if peer_actor is not None:
            item["peer_actor"] = int(peer_actor)
        if learned is None:
            item["selection_source"] = "rejected_unlearned"
            state["fallback_unlearned"] += 1
        elif distance <= float(learned):
            if address in state["native_max_world"]:
                item["selection_source"] = "inward_fallback"
            else:
                item["selection_source"] = (
                    "forced_surface_inward_fallback"
                    if is_forced
                    else "surface_inward_fallback"
                )
                state["peer_inward_accepts"] += 1
            state["fallback_accepts"] += 1
            eligible.append(item)
        else:
            item["selection_source"] = "rejected_farther"
            state["fallback_farther"] += 1
    state["fallback_samples"] += 1
    state["selector_samples"] += 1
    if candidates:
        state["obb_inside_samples"] += 1
    else:
        state["obb_empty_samples"] += 1
    if len(candidates) > 1:
        state["obb_overlap_samples"] += 1
    if eligible:
        state["eligible_samples"] += 1
    if len(eligible) > 1:
        state["eligible_overlap_samples"] += 1
    if candidates and not eligible:
        state["gate2_filtered_samples"] += 1
    state["selector_policy_seconds"] += time.perf_counter() - policy_started
    elapsed = time.perf_counter() - select_started
    state["selector_seconds"] += elapsed
    state["selector_max_seconds"] = max(
        float(state["selector_max_seconds"]),
        elapsed,
    )
    if not eligible:
        return 0, None, candidates[0] if candidates else None, len(candidates), 0
    selected = eligible[0]
    return (
        int(selected["address"]),
        None,
        selected,
        len(candidates),
        len(eligible),
    )


def _item_card_publish_selection(
    state: dict[str, Any],
    actor: int,
    actor_object: Any,
    geometry: dict[str, Any] | None,
    raw_count: int,
    eligible_count: int,
) -> None:
    if actor == state.get("pending_actor"):
        state["pending_samples"] += 1
    else:
        state["pending_actor"] = actor
        state["pending_samples"] = 1
    hook = state["final_hook"]
    control = hook["control"]
    control.enabled = 1
    if state["pending_samples"] < ITEM_CARD_STABLE_SELECTION_SAMPLES:
        return
    source = (
        geometry.get("selection_source", "clear") if geometry is not None else "clear"
    )
    if actor == int(control.selected_actor):
        if source != state.get("last_selection_source"):
            state["last_selection_source"] = source
            state["source_transition_events"] += 1
            learned = geometry.get("learned_distance") if geometry is not None else None
            if state["source_transition_events"] <= ITEM_CARD_MAX_DEBUG_EVENTS:
                logging.info(
                    "[BL4ThirdPersonPOC] TPS item-card source transition "
                    f"actor={f'0x{actor:016X}' if actor else '<clear>'}, "
                    f"source={source}"
                    + (
                        f", world={geometry['world_distance']:.3f}, "
                        f"learned={float(learned):.3f}"
                        if geometry is not None and learned is not None
                        else ""
                    )
                )
            else:
                state["source_transition_events_dropped"] += 1
        return
    control.selected_actor = actor
    state["last_selection_source"] = source
    state["selection_updates"] += 1
    path = state["pickups"].get(actor, "<clear>")
    detail = ""
    if geometry is not None:
        learned = geometry.get("learned_distance")
        detail = (
            f", world={geometry['world_distance']:.3f}"
            f", normalized={geometry['normalized_distance']:.6f}"
            f", edge_margin={geometry['edge_margin']:.3f}"
            f", source={geometry.get('selection_source', 'unknown')}"
            + (
                f", learned={float(learned):.3f}"
                if learned is not None
                else ", learned=<none>"
            )
            + (
                f", peer=0x{int(geometry['peer_actor']):016X}"
                if geometry.get("peer_actor") is not None
                else ""
            )
            + (
                f", surface_clearance=" f"{float(geometry['surface_clearance']):.3f}"
                if geometry.get("surface_clearance") is not None
                else ""
            )
        )
    logging.info(
        "[BL4ThirdPersonPOC] TPS item-card selection "
        f"actor={f'0x{actor:016X}' if actor else '<clear>'}, "
        f"path={path}, raw_count={raw_count}, "
        f"eligible_count={eligible_count}{detail}"
    )
    if len(state["selection_events"]) < ITEM_CARD_MAX_DEBUG_EVENTS:
        state["selection_events"].append(
            (
                int(state["update_index"]),
                actor,
                path,
                raw_count,
                eligible_count,
            )
        )
    else:
        state["selection_events_dropped"] += 1


# item_card_refresh.py — consolidated item-card game-thread behavior.
def _item_card_refresh_pickups(
    state: dict[str, Any],
    *,
    force: bool = False,
    _perf_probe,
    _item_card_collect_pickups,
    _perf_finish_item_refresh,
    _retired_native_stubs,
    MAX_RETIRED_ITEM_CARD_STUBS,
    _item_card_disable_control,
    _item_card_hook_counter,
    _native_restore_hook,
    _native_release_hook,
    _item_card_install_final_hook,
) -> None:
    now = time.monotonic()
    if (
        not force
        and now - float(state["last_pickup_refresh"])
        < ITEM_CARD_PICKUP_REFRESH_INTERVAL
    ):
        return
    profiling = bool(_perf_probe["armed"])
    started_ns = time.perf_counter_ns() if profiling else 0
    if profiling:
        _perf_probe["item_scan"] = None
    state["last_pickup_refresh"] = now
    old_paths = state["pickups"]
    settle_due = float(state["geometry_settle_due"])
    settle_pending = set(state["geometry_settle_pending"])
    settle_addresses: set[int] = set()
    if settle_pending and settle_due > 0.0 and now >= settle_due:
        ordered = sorted(settle_pending)
        cursor = int(state["geometry_settle_cursor"]) % len(ordered)
        rotated = ordered[cursor:] + ordered[:cursor]
        settle_addresses = set(rotated[:ITEM_CARD_GEOMETRY_TRACK_BUDGET])
        state["geometry_settle_cursor"] = (cursor + len(settle_addresses)) % len(
            ordered
        )
    previous_geometry = state["pickup_geometry"]
    background_addresses: set[int] = set()
    if not force and previous_geometry:
        ordered_background = sorted(
            (
                address
                for address in previous_geometry
                if address in old_paths and address not in settle_addresses
            ),
            key=lambda address: (
                float(
                    previous_geometry[address].get(
                        "radius",
                        math.inf,
                    )
                ),
                int(address),
            ),
        )
        if ordered_background:
            background_cursor = int(state["geometry_background_cursor"]) % len(
                ordered_background
            )
            rotated_background = (
                ordered_background[background_cursor:]
                + ordered_background[:background_cursor]
            )
            background_addresses = set(
                rotated_background[:ITEM_CARD_GEOMETRY_BACKGROUND_BUDGET]
            )
            state["geometry_background_cursor"] = (
                background_cursor + len(background_addresses)
            ) % len(ordered_background)
    refresh_addresses = settle_addresses | background_addresses
    state["geometry_background_attempts"] += len(background_addresses)
    paths, geometry, settle_failed = _item_card_collect_pickups(
        state,
        force_geometry=force,
        settle_addresses=refresh_addresses,
    )
    for address in refresh_addresses:
        if address in settle_failed:
            continue
        before = previous_geometry.get(address)
        after = geometry.get(address)
        if before is None or after is None:
            continue
        old_radius = max(float(before.get("radius", 0.0)), 1.0e-12)
        new_radius = max(float(after.get("radius", 0.0)), 0.0)
        if new_radius / old_radius < ITEM_CARD_GEOMETRY_COLLAPSE_RATIO:
            geometry[address] = before
            state["geometry_collapse_rejections"] += 1
            if address in settle_addresses:
                settle_failed.add(address)
            continue
        if address in background_addresses:
            center_drift = math.sqrt(
                sum(
                    (float(after["center"][axis]) - float(before["center"][axis])) ** 2
                    for axis in range(3)
                )
            )
            state["geometry_background_updates"] += 1
            state["geometry_background_max_center_drift"] = max(
                float(state["geometry_background_max_center_drift"]),
                center_drift,
            )
    state["pickup_geometry"] = geometry
    if settle_addresses:
        remaining: set[int] = settle_pending - settle_addresses
        for address in settle_addresses:
            if address not in paths:
                state["geometry_settle_started"].pop(address, None)
                state["geometry_settle_stable"].pop(address, None)
                continue
            if address in settle_failed:
                state["geometry_settle_stable"][address] = 0
                remaining.add(address)
                continue
            before = previous_geometry.get(address)
            after = geometry.get(address)
            if before is None or after is None:
                state["geometry_settle_stable"][address] = 0
                remaining.add(address)
                continue
            center_drift = math.sqrt(
                sum(
                    (float(after["center"][axis]) - float(before["center"][axis])) ** 2
                    for axis in range(3)
                )
            )
            axis_delta = max(
                1.0
                - abs(
                    _item_card_dot(
                        tuple(before["axes"][axis]),
                        tuple(after["axes"][axis]),
                    )
                )
                for axis in range(3)
            )
            state["geometry_settle_updates"] += 1
            state["geometry_settle_max_center_drift"] = max(
                float(state["geometry_settle_max_center_drift"]),
                center_drift,
            )
            state["geometry_settle_max_axis_delta"] = max(
                float(state["geometry_settle_max_axis_delta"]),
                axis_delta,
            )
            stable = (
                center_drift <= ITEM_CARD_GEOMETRY_CENTER_EPSILON
                and axis_delta <= ITEM_CARD_GEOMETRY_AXIS_EPSILON
            )
            stable_samples = (
                int(state["geometry_settle_stable"].get(address, 0)) + 1
                if stable
                else 0
            )
            state["geometry_settle_stable"][address] = stable_samples
            started = float(state["geometry_settle_started"].get(address, now))
            if stable_samples >= ITEM_CARD_GEOMETRY_STABLE_SAMPLES:
                state["geometry_settle_completed"] += 1
                state["geometry_settle_started"].pop(address, None)
                state["geometry_settle_stable"].pop(address, None)
            elif now - started >= ITEM_CARD_GEOMETRY_TRACK_TIMEOUT:
                state["geometry_settle_timeouts"] += 1
                state["geometry_settle_started"].pop(address, None)
                state["geometry_settle_stable"].pop(address, None)
            else:
                remaining.add(address)
        state["geometry_settle_pending"] = remaining
        state["geometry_settle_due"] = (
            now + ITEM_CARD_PICKUP_REFRESH_INTERVAL if remaining else 0.0
        )
    new_addresses = set(paths) - set(old_paths)
    if state["snapshot_rebuilds"] > 0 and new_addresses:
        state["geometry_settle_pending"].update(new_addresses)
        for address in new_addresses:
            state["geometry_settle_started"][address] = now
            state["geometry_settle_stable"][address] = 0
        state["geometry_settle_due"] = now + ITEM_CARD_PICKUP_REFRESH_INTERVAL
    if set(paths) == set(old_paths) and isinstance(state.get("final_hook"), dict):
        state["pickups"] = paths
        if profiling:
            _perf_finish_item_refresh(started_ns, paths, old_paths, 0)
        return

    if (
        sum(kind == "item_card" for kind, *_ in _retired_native_stubs)
        >= MAX_RETIRED_ITEM_CARD_STUBS
    ):
        _item_card_disable_control(state)
        state["ready"] = False
        logging.error(
            "[BL4ThirdPersonPOC] Item-card fusion suspended: "
            "retired executable-stub budget reached; native selection active"
        )
        if profiling:
            _perf_finish_item_refresh(started_ns, paths, old_paths, 0)
        return

    rebuild_started_ns = time.perf_counter_ns() if profiling else 0
    _item_card_disable_control(state)
    previous_hook = state.get("final_hook")
    if isinstance(previous_hook, dict):
        state["final_calls_completed"] += _item_card_hook_counter(previous_hook)
        _native_restore_hook(previous_hook)
        _native_release_hook(previous_hook)
        state["final_hook"] = None

    state["pickups"] = paths
    state["native_max_world"] = {
        address: distance
        for address, distance in state["native_max_world"].items()
        if address in paths
    }
    state["peer_max_world"] = {
        address: distance
        for address, distance in state["peer_max_world"].items()
        if address in paths
    }
    state["peer_source_actor"] = {
        address: peer
        for address, peer in state["peer_source_actor"].items()
        if address in paths and peer in paths
    }
    state["native_peer_center"] = {
        address: center
        for address, center in state["native_peer_center"].items()
        if address in paths
    }
    state["peer_source_separation"] = {
        address: separation
        for address, separation in state["peer_source_separation"].items()
        if address in state["peer_source_actor"]
    }
    state["peer_max_world"] = {
        address: distance
        for address, distance in state["peer_max_world"].items()
        if address in state["peer_source_actor"]
    }
    state["forced_peer_capture"] = {
        address: distance
        for address, distance in state["forced_peer_capture"].items()
        if address in paths
    }
    state["forced_peer_witnesses"] = {
        address: distance
        for address, distance in state["forced_peer_witnesses"].items()
        if address in paths
    }
    if int(state["forced_unlearned_actor"]) not in paths:
        state["forced_unlearned_actor"] = 0
        state["forced_native_saved"] = None
    # Membership can change repeatedly while a boss loot burst is still
    # spawning. Keep recent Gate-2 evidence only for actors whose address and
    # path identity survived this rebuild; clearing every survivor caused a
    # short all-icon window until native evidence was learned again.
    previous_gate2 = state["gate2_last_seen_update"]
    preserved_gate2 = {
        address: last_seen
        for address, last_seen in previous_gate2.items()
        if address in paths and old_paths.get(address) == paths.get(address)
    }
    state["gate2_snapshot_preserved"] += len(preserved_gate2)
    state["gate2_last_seen_update"] = preserved_gate2
    state["pending_actor"] = None
    state["pending_samples"] = 0
    state["final_hook"] = _item_card_install_final_hook(
        int(state["module_base"]),
        tuple(sorted(paths)),
    )
    state["snapshot_rebuilds"] += 1
    logging.info(
        "[BL4ThirdPersonPOC] Item-card pickup snapshot rebuilt; "
        f"visible_pickups={len(paths)}, "
        f"rebuild={state['snapshot_rebuilds']}"
    )
    if profiling:
        _perf_finish_item_refresh(
            started_ns,
            paths,
            old_paths,
            time.perf_counter_ns() - rebuild_started_ns,
        )


# item_card_runtime.py — consolidated item-card game-thread behavior.
def _item_card_disable_control(state: dict[str, Any]) -> None:
    hook = state.get("final_hook")
    if not isinstance(hook, dict):
        return
    control = hook.get("control")
    if control is not None:
        control.enabled = 0
        control.selected_actor = 0
    state["pending_actor"] = None
    state["pending_samples"] = 0


def _update_item_card_fusion(
    *,
    _item_card_state,
    _item_card_should_override,
    _item_card_disable_control,
    _item_card_refresh_pickups,
    _item_card_hook_counter,
    _item_card_drain_gate2,
    _get_runtime,
    _item_card_select,
    _item_card_publish_selection,
) -> None:
    state = _item_card_state
    if not isinstance(state, dict) or not state.get("ready"):
        return
    try:
        active = _item_card_should_override()
        if not active:
            if state["active"]:
                _item_card_disable_control(state)
                state["active"] = False
                state["gate2_last_seen_update"].clear()
                logging.info(
                    "[BL4ThirdPersonPOC] TPS item-card fusion suspended; "
                    "native selection active"
                )
            return

        if not state["active"]:
            # Reacquire the complete numeric snapshot when TPS becomes active;
            # no UObject wrapper survives the suspended/loading period.
            _item_card_refresh_pickups(state, force=True)
            final_hook = state.get("final_hook")
            if not isinstance(final_hook, dict):
                return
            state["active"] = True
            state["update_index"] += 1
            state["gate2_last_seen_update"].clear()
            state["gate2_read_sequence"] = _item_card_hook_counter(state["gate2_hook"])
            state["pending_actor"] = None
            state["pending_samples"] = 0
            final_hook["control"].enabled = 1
            final_hook["control"].selected_actor = 0
            logging.info(
                "[BL4ThirdPersonPOC] TPS item-card gate-2/OBB " "fusion active"
            )
            return

        _item_card_refresh_pickups(state)
        final_hook = state.get("final_hook")
        if not isinstance(final_hook, dict):
            return
        state["update_index"] += 1
        _item_card_drain_gate2(state)
        pc, pawn, camera_manager = _get_runtime()
        if pc is None or pawn is None or camera_manager is None:
            _item_card_disable_control(state)
            return
        actor, actor_object, geometry, raw_count, eligible_count = _item_card_select(
            state, pc, pawn, camera_manager
        )
        _item_card_publish_selection(
            state,
            actor,
            actor_object,
            geometry,
            raw_count,
            eligible_count,
        )
    except Exception as exc:
        state["update_errors"] += 1
        state["last_update_error"] = f"{type(exc).__name__}: {exc}"
        _item_card_disable_control(state)
        if state["update_errors"] <= 3:
            logging.error(
                "[BL4ThirdPersonPOC] TPS item-card update failed: "
                f"{state['last_update_error']}"
            )


# Interaction diagnostic and camera repair policies.
def _log_unhandled_tps_interaction_hit(
    *, _get_runtime, _get_tps_crosshair_screen, _make_vector, INTERACTION_TRACE_DISTANCE
) -> None:
    """Passively identify quest/objective targets without redirecting them."""
    pc, pawn, camera_manager = _get_runtime()
    if pc is None or pawn is None or camera_manager is None:
        return
    try:
        system_library = find_object(
            "KismetSystemLibrary",
            "/Script/Engine.Default__KismetSystemLibrary",
        )
        screen_x, screen_y = _get_tps_crosshair_screen(pc, camera_manager)
        deproject_result = pc.DeprojectScreenPositionToWorld(
            screen_x,
            screen_y,
            _make_vector(0.0, 0.0, 0.0),
            _make_vector(0.0, 0.0, 0.0),
        )
        if not bool(deproject_result[0]):
            logging.info(
                "[BL4ThirdPersonPOC] TPS unhandled-use probe: "
                "crosshair deprojection failed"
            )
            return
        ray_start, ray_direction = deproject_result[1:3]
        # DrawDebugSphere is a no-op in shipping builds, so we can't verify
        # this visually - but the raw numbers are enough. Log the viewport
        # size alongside the screen point so the offset can be measured
        # precisely against a real screenshot.
        viewport_result = pc.GetViewportSize(0, 0)
        logging.info(
            "[BL4ThirdPersonPOC] TPS_CROSSHAIR_DEBUG "
            f"screen=({screen_x:.1f}, {screen_y:.1f}), "
            f"viewport=({float(viewport_result[-2]):.1f}, "
            f"{float(viewport_result[-1]):.1f})"
        )
        ray_end = _make_vector(
            ray_start.X + ray_direction.X * INTERACTION_TRACE_DISTANCE,
            ray_start.Y + ray_direction.Y * INTERACTION_TRACE_DISTANCE,
            ray_start.Z + ray_direction.Z * INTERACTION_TRACE_DISTANCE,
        )
        trace_result = system_library.LineTraceSingle(
            pc,
            ray_start,
            ray_end,
            0,
            True,
            [pawn],
            0,
            make_struct("HitResult"),
            True,
            make_struct("LinearColor", R=1.0, G=0.0, B=0.0, A=1.0),
            make_struct("LinearColor", R=0.0, G=1.0, B=0.0, A=1.0),
            0.0,
        )
        if not bool(trace_result[0]):
            logging.info("[BL4ThirdPersonPOC] TPS unhandled-use probe: no hit")
            return
        hit = trace_result[-1]
        component = hit.Component
        actor = component.Outer if component is not None else None
        if actor is None:
            reference = hit.HitObjectHandle.ReferenceObject
            if reference is not None:
                actor = getattr(reference, "Outer", reference)
        actor_class = str(actor.Class.Name) if actor is not None else "<none>"
        actor_path = str(actor._path_name()) if actor is not None else "<none>"
        component_class = (
            str(component.Class.Name) if component is not None else "<none>"
        )
        component_path = (
            str(component._path_name()) if component is not None else "<none>"
        )
        logging.info(
            "[BL4ThirdPersonPOC] TPS_UNHANDLED_USE_HIT "
            f"distance={float(hit.Distance):.3f}, "
            f"actor_class={actor_class!r}, actor_path={actor_path}, "
            f"component_class={component_class!r}, "
            f"component_path={component_path}"
        )
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] TPS unhandled-use probe failed: "
            f"{type(exc).__name__}: {exc}"
        )


def _repair_third_person(
    *,
    automatic: bool,
    _third_person_enabled,
    _ads_active,
    _vehicle_camera_active,
    _shop_camera_active,
    _ladder_active,
    _get_runtime,
    _camera_lifecycle,
    _third_person_pushed,
    _camera_stack_owner,
    _pop_third_person,
    _push_third_person,
) -> bool:
    if (
        not _third_person_enabled
        or _ads_active
        or _vehicle_camera_active
        or _shop_camera_active
        or _ladder_active
    ):
        if automatic:
            logging.info(
                "[BL4ThirdPersonPOC] Automatic ThirdPerson repair skipped; "
                "a native camera route is active"
            )
        return False

    _pc, pawn, camera_manager = _get_runtime()

    if pawn is None or camera_manager is None:
        if not automatic:
            logging.warning(
                "[BL4ThirdPersonPOC] Repair failed: "
                "pawn or camera manager unavailable"
            )
        return False

    if automatic:
        logging.info(
            "[BL4ThirdPersonPOC] Automatically repairing " "FirstPerson camera fallback"
        )
    else:
        logging.info(
            "[BL4ThirdPersonPOC] Manually repairing " "ThirdPerson camera mode"
        )

    # After Second Wind the native mode is already settled at Default.
    # Pop and push execute in this game-thread callback. Avoid blending
    # through that FPS mode for an extra rendered frame on this route only.
    ffyl_repair = automatic and _camera_lifecycle.get("reason") == "ffyl"
    transition_time = 0.0 if ffyl_repair else 1.0
    if ffyl_repair:
        logging.info("[BL4ThirdPersonPOC] FFYL_CAMERA_REPAIR_BLEND duration=0.0")

    if _third_person_pushed or _camera_stack_owner.get("owned"):
        if not _pop_third_person(
            reason="camera_repair", transition_time=transition_time
        ):
            logging.warning(
                "[BL4ThirdPersonPOC] ThirdPerson repair deferred: "
                "the owned camera entry cannot be removed safely yet"
            )
            return False

    if _push_third_person(transition_time=transition_time):
        logging.info("[BL4ThirdPersonPOC] ThirdPerson camera repaired")
        return True

    logging.error("[BL4ThirdPersonPOC] ThirdPerson repair failed")
    return False


# Camera diagnostic hook ownership remains in the loader.
def _install_camera_mode_probe_impl(
    *, installed, callback, function, identifier
) -> bool:
    if installed:
        return True
    try:
        installed = add_hook(function, Type.PRE, identifier, callback)
        if installed:
            logging.info("[BL4ThirdPersonPOC] Installed " "ClientSetCameraMode probe")
        else:
            logging.warning(
                "[BL4ThirdPersonPOC] " "ClientSetCameraMode probe already exists"
            )
    except Exception as exc:
        installed = False
        logging.error(
            "[BL4ThirdPersonPOC] Could not install "
            "ClientSetCameraMode probe: "
            f"{type(exc).__name__}: {exc}"
        )
    return installed


def _remove_camera_mode_probe_impl(*, installed, function, identifier) -> bool:
    if not installed:
        return False
    try:
        remove_hook(function, Type.PRE, identifier)
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not remove "
            "ClientSetCameraMode probe: "
            f"{type(exc).__name__}: {exc}"
        )
        return True
    return False


def _install_blueprint_camera_probe_impl(
    *, installed, callback, function, identifier
) -> bool:
    if installed:
        return True
    try:
        installed = add_hook(function, Type.POST, identifier, callback)
        if installed:
            logging.info("[BL4ThirdPersonPOC] Installed " "BlueprintUpdateCamera probe")
        else:
            logging.warning(
                "[BL4ThirdPersonPOC] " "BlueprintUpdateCamera probe already exists"
            )
    except Exception as exc:
        installed = False
        logging.error(
            "[BL4ThirdPersonPOC] Could not install "
            "BlueprintUpdateCamera probe: "
            f"{type(exc).__name__}: {exc}"
        )
    return installed


def _remove_blueprint_camera_probe_impl(*, installed, function, identifier) -> bool:
    if not installed:
        return False
    try:
        remove_hook(function, Type.POST, identifier)
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not remove "
            "BlueprintUpdateCamera probe: "
            f"{type(exc).__name__}: {exc}"
        )
        return True
    return False


# Interaction hook registry; loader module retains synchronous state.
def _install_interaction_redirect_impl(
    *,
    state,
    _remove_interaction_redirect,
    SERVER_USE_OBJECT_FUNCTION,
    INTERACTION_REDIRECT_IDENTIFIER,
    LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
    LEGACY_FLOOR_PICKUP_HOOK_IDENTIFIER,
    FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
    CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
    SHOP_CAMERA_HOOK_IDENTIFIER,
    _server_use_object_redirect_hook,
    _server_use_junk_object_priority_hook,
    _client_set_current_interactable_hook,
) -> None:

    if (
        state._interaction_redirect_installed
        or state._shop_camera_hook_installed
        or state._floor_pickup_priority_hook_installed
    ):
        _remove_interaction_redirect()
    if (
        state._interaction_redirect_installed
        or state._shop_camera_hook_installed
        or state._floor_pickup_priority_hook_installed
    ):
        logging.error(
            "[BL4ThirdPersonPOC] Interaction hook installation refused: "
            "older tracked hooks could not be removed"
        )
        return

    # Einen möglicherweise durch Hot-Reload verbliebenen
    # Hook mit demselben Identifier zuerst entfernen.
    try:
        remove_hook(
            SERVER_USE_OBJECT_FUNCTION,
            Type.PRE,
            INTERACTION_REDIRECT_IDENTIFIER,
        )
    except Exception:
        pass

    # Clean up the pre-0.3.1 floor-pickup observer during an RLM reload.
    try:
        remove_hook(
            LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
            Type.POST,
            LEGACY_FLOOR_PICKUP_HOOK_IDENTIFIER,
        )
    except Exception:
        pass

    try:
        remove_hook(
            LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
            Type.PRE,
            FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
        )
    except Exception:
        pass

    try:
        remove_hook(
            CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
            Type.POST,
            SHOP_CAMERA_HOOK_IDENTIFIER,
        )
    except Exception:
        pass

    state._interaction_redirect_installed = False
    state._shop_camera_hook_installed = False
    state._floor_pickup_priority_hook_installed = False

    try:
        add_hook(
            SERVER_USE_OBJECT_FUNCTION,
            Type.PRE,
            INTERACTION_REDIRECT_IDENTIFIER,
            _server_use_object_redirect_hook,
        )
        state._interaction_redirect_installed = has_hook(
            SERVER_USE_OBJECT_FUNCTION, Type.PRE, INTERACTION_REDIRECT_IDENTIFIER
        )

        logging.info(
            "[BL4ThirdPersonPOC] Interaction redirect hook "
            f"installed={state._interaction_redirect_installed}"
        )

    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Could not install interaction "
            f"redirect hook: {type(exc).__name__}: {exc}"
        )

    try:
        state._floor_pickup_priority_hook_installed = bool(
            add_hook(
                LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
                Type.PRE,
                FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
                _server_use_junk_object_priority_hook,
            )
        )

        logging.info(
            "[BL4ThirdPersonPOC] Floor-pickup priority hook "
            f"installed={state._floor_pickup_priority_hook_installed}"
        )

    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Could not install floor-pickup priority "
            f"hook: {type(exc).__name__}: {exc}"
        )

    try:
        state._shop_camera_hook_installed = bool(
            add_hook(
                CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
                Type.POST,
                SHOP_CAMERA_HOOK_IDENTIFIER,
                _client_set_current_interactable_hook,
            )
        )

        logging.info(
            "[BL4ThirdPersonPOC] Shop camera hook "
            f"installed={state._shop_camera_hook_installed}"
        )

    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Could not install shop "
            f"camera hook: {type(exc).__name__}: {exc}"
        )


def _remove_interaction_redirect_impl(
    *,
    state,
    SERVER_USE_OBJECT_FUNCTION,
    INTERACTION_REDIRECT_IDENTIFIER,
    CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
    SHOP_CAMERA_HOOK_IDENTIFIER,
    LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
    FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
) -> None:

    if state._interaction_redirect_installed:
        try:
            remove_hook(
                SERVER_USE_OBJECT_FUNCTION,
                Type.PRE,
                INTERACTION_REDIRECT_IDENTIFIER,
            )
        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not remove interaction "
                f"redirect hook: {type(exc).__name__}: {exc}"
            )
        else:
            state._interaction_redirect_installed = False

    if state._shop_camera_hook_installed:
        try:
            remove_hook(
                CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
                Type.POST,
                SHOP_CAMERA_HOOK_IDENTIFIER,
            )
        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not remove shop "
                f"camera hook: {type(exc).__name__}: {exc}"
            )
        else:
            state._shop_camera_hook_installed = False

    if state._floor_pickup_priority_hook_installed:
        try:
            remove_hook(
                LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
                Type.PRE,
                FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
            )
        except Exception as exc:
            logging.warning(
                "[BL4ThirdPersonPOC] Could not remove floor-pickup "
                f"priority hook: {type(exc).__name__}: {exc}"
            )
        else:
            state._floor_pickup_priority_hook_installed = False
    state._shop_camera_active = False
    state._pending_interaction_target = None
    state._pending_interaction_time = 0.0
    state._pending_floor_pickup_target = None
    state._pending_floor_pickup_time = 0.0
    state._pending_floor_pickup_released = False


# Interaction event and fallback behavior; state is the live loader module.
def _get_tps_interaction_target_impl(state) -> Any:
    if (
        not state._third_person_enabled
        or state._ads_active
        or state._vehicle_camera_active
        or state._ladder_active
        or state._shop_camera_active
    ):
        return None

    # Previously: a second, hand-rolled raycast (using a forward point
    # derived from POV rotation rather than the actual TPS crosshair
    # position) plus a hardcoded class whitelist. That silently dropped
    # anything that wasn't LootableObject/OakVendingMachine - Vault Power
    # spheres included - and used a different aim point than the prompt
    # system, so the two could disagree about what's being targeted.
    #
    # ClientSetCurrentInteractable already tells us, straight from the
    # game, exactly which object it currently considers interactable
    # (range-checked and everything) - and it's driven by the same
    # TPS-crosshair-redirected trace the prompt uses. So just trust it.
    return state._native_current_interactable


def _handle_interaction_input_impl(event: EInputEvent, state) -> None:

    if event == state.EInputEvent.IE_Released:
        if state._pending_floor_pickup_target is not None:
            state._pending_floor_pickup_released = True
            logging.info(
                "[BL4ThirdPersonPOC] Deferred TPS floor pickup release; "
                "waiting for native use observers before fallback"
            )
        return

    if event != state.EInputEvent.IE_Pressed:
        return

    state._pending_interaction_target = None
    state._pending_interaction_time = 0.0
    state._pending_floor_pickup_target = None
    state._pending_floor_pickup_time = 0.0
    state._pending_floor_pickup_released = False

    # A known world interactable always outranks the screen-space pickup
    # fallback. Unknown native interactables are protected by the deferred
    # pickup window and the ServerUseObject/ServerUseJunkObject observers.
    target = state._get_tps_interaction_target()
    if target is not None:
        # Vending Machines have distinct native tap and hold actions. A
        # synthetic ServerUseObject(..., bWasHeld=False) after 50 ms turns
        # every hold into an immediate shop-open tap. The continuously
        # redirected native prompt query already supplies the correct TPS
        # target, so preserve Gearbox's complete input timing for this class.
        try:
            if str(target.Class.Name) == "OakVendingMachine":
                logging.info(
                    "[BL4ThirdPersonPOC] Native Vending tap/hold input "
                    "preserved; TPS interaction fallback bypassed"
                )
                return
        except Exception:
            pass

        state._pending_interaction_target = target
        state._pending_interaction_time = time.monotonic()
        return

    floor_pickup = state._get_tps_floor_pickup_target()
    if floor_pickup is None:
        state._log_unhandled_tps_interaction_hit()
        return

    state._pending_floor_pickup_target = floor_pickup
    state._pending_floor_pickup_time = time.monotonic()
    state._pending_floor_pickup_released = False
    logging.info(
        "[BL4ThirdPersonPOC] Deferred TPS floor pickup pending native "
        f"interaction priority: {floor_pickup._path_name()}"
    )


def _server_use_object_redirect_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, state
) -> None:

    from . import npc_native_resume

    npc_native_resume.begin(state, obj)
    state._cancel_pending_floor_pickup("native ServerUseObject")

    target = state._pending_interaction_target
    target_time = state._pending_interaction_time
    redirected = False
    state._pending_interaction_target = None
    state._pending_interaction_time = 0.0
    if target is not None:
        elapsed = time.monotonic() - target_time

        if elapsed <= state.INTERACTION_REDIRECT_WINDOW:
            try:
                args.Usable = target
                redirected = True
            except Exception as exc:
                logging.error(
                    "[BL4ThirdPersonPOC] Could not redirect "
                    "ServerUseObject args.Usable: "
                    f"{type(exc).__name__}: {exc}"
                )
        else:
            logging.info(
                "[BL4ThirdPersonPOC] TPS interaction candidate "
                f"expired after {elapsed:.3f}s"
            )

    try:
        observed_usable = args.Usable
        logging.info(
            "[BL4ThirdPersonPOC] SERVER_USE_OBJECT "
            f"source={'tps_redirect' if redirected else 'native'}, "
            f"class={str(observed_usable.Class.Name)!r}, "
            f"path={observed_usable._path_name()}"
        )
    except Exception as exc:
        logging.info(
            "[BL4ThirdPersonPOC] SERVER_USE_OBJECT "
            f"source={'tps_redirect' if redirected else 'native'}, "
            f"usable=<unreadable: {type(exc).__name__}: {exc}>"
        )

    # Quest NPCs and vending machines enter StructuredInteraction before the
    # camera hot path gets another frame. Restore while the TPS Look copy is
    # still owned; at ClientSetCurrentInteractable POST the mode stack already
    # carries the interaction entry and the recoil restore refuses (0.3.9.3).
    if not state._native_active() or not (
        state._third_person_enabled and state._third_person_pushed
    ):
        return
    try:
        usable = args.Usable
        usable_class = str(usable.Class.Name) if usable is not None else ""
        reason = NATIVE_PRE_RESTORE_USABLES.get(usable_class)
        if reason is None:
            return
        pc, pawn, camera = state._get_runtime()
        if (
            pc is None
            or pawn is None
            or camera is None
            or state._object_address(obj) != state._object_address(pc)
            or str(camera.GetActorCameraMode(pawn)) != "ThirdPerson"
        ):
            return
        if state._native_stop(reason):
            npc_native_resume.arm(state, obj)
        elif usable_class == "OakCharacter":
            logging.error(
                "[BL4ThirdPersonPOC] NPC_NATIVE_PRE_RESTORE_FAILED; "
                "restart game before further camera tests"
            )
        else:
            # The pop-time attempt and the settled-TPS recoil recovery in
            # native_lifecycle remain responsible, exactly as before 0.3.9.3.
            logging.warning(
                "[BL4ThirdPersonPOC] SHOP_NATIVE_PRE_RESTORE_FAILED; "
                "settled TPS recovery remains armed"
            )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] NPC_NATIVE_PRE_ERROR " f"{type(exc).__name__}: {exc}"
        )


def _cancel_pending_floor_pickup_impl(reason: str, state) -> None:

    target = state._pending_floor_pickup_target
    if target is None:
        return

    try:
        path = str(target._path_name())
    except Exception:
        path = repr(target)

    state._pending_floor_pickup_target = None
    state._pending_floor_pickup_time = 0.0
    state._pending_floor_pickup_released = False
    logging.info(
        "[BL4ThirdPersonPOC] Cancelled deferred TPS floor pickup; "
        f"reason={reason}, target={path}"
    )


def _server_use_junk_object_priority_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, state
) -> None:
    state._cancel_pending_floor_pickup("native ServerUseJunkObject")


def _client_set_current_interactable_hook_impl(
    obj: Any, args: Any, ret: Any, func: Any, state
) -> None:

    try:
        new_interactable = args.NewInteractable
    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not read shop "
            "interactable state: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    # Mirror the native truth unconditionally, before any of the
    # vending-machine-specific branching below. Whatever Borderlands 4
    # itself just named as the current interactable IS the correct TPS
    # target - no class whitelist needed.
    if new_interactable is not state._native_current_interactable:
        try:
            new_desc = (
                f"{new_interactable.Class.Name}" f" ({new_interactable._path_name()})"
                if new_interactable is not None
                else "<none>"
            )
        except Exception:
            new_desc = repr(new_interactable)
        logging.info(f"[BL4ThirdPersonPOC] NATIVE_INTERACTABLE_CHANGED -> {new_desc}")
    state._native_current_interactable = new_interactable

    if not state._shop_camera_active:
        if not state._third_person_enabled or new_interactable is None:
            return
        try:
            interactable_class = str(new_interactable.Class.Name)
        except Exception:
            return
        if interactable_class != "OakVendingMachine":
            return

        state._cancel_hybrid_ads("shop_enter")
        state._shop_camera_active = True
        state._ads_active = False
        if state._third_person_pushed:
            state._pop_third_person()
        logging.info(
            "[BL4ThirdPersonPOC] Shop camera started; confirmed by "
            "ClientSetCurrentInteractable(OakVendingMachine)"
        )
        return

    if new_interactable is not None:
        return

    state._shop_camera_active = False

    if (
        state._third_person_enabled
        and not state._vehicle_camera_active
        and not state._ladder_active
        and not state._ads_active
    ):
        state._push_third_person()

    logging.info(
        "[BL4ThirdPersonPOC] Shop camera ended; "
        f"third_person_enabled={state._third_person_enabled}"
    )


def _update_pending_interaction_fallback_impl(state) -> None:

    target = state._pending_interaction_target
    if target is None:
        return

    elapsed = time.monotonic() - state._pending_interaction_time
    if elapsed < state.INTERACTION_FALLBACK_DELAY:
        return

    # Consume before calling ServerUseObject. The PRE hook therefore sees no
    # pending target and cannot redirect our own fallback call a second time.
    state._pending_interaction_target = None
    state._pending_interaction_time = 0.0

    if (
        not state._third_person_enabled
        or state._ads_active
        or state._vehicle_camera_active
        or state._ladder_active
    ):
        logging.info(
            "[BL4ThirdPersonPOC] TPS interaction fallback cancelled; "
            "camera state changed"
        )
        return

    pc, _pawn, _camera_manager = state._get_runtime()
    if pc is None:
        logging.warning(
            "[BL4ThirdPersonPOC] TPS interaction fallback cancelled; "
            "PlayerController unavailable"
        )
        return

    try:
        pc.ServerUseObject(
            target,
            0,  # EUsabilityType.Primary
            False,  # bWasHeld
        )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] TPS interaction fallback failed: "
            f"{type(exc).__name__}: {exc}"
        )


def _update_pending_floor_pickup_fallback_impl(state) -> None:

    target = state._pending_floor_pickup_target
    if target is None:
        return

    if not state._pending_floor_pickup_released:
        return
    elapsed = time.monotonic() - state._pending_floor_pickup_time

    if (
        not state._third_person_enabled
        or state._ads_active
        or state._vehicle_camera_active
        or state._ladder_active
        or state._shop_camera_active
    ):
        state._cancel_pending_floor_pickup("camera state changed")
        return

    current_target = state._get_tps_floor_pickup_target()
    try:
        target_address = int(target._get_address())
        current_address = (
            int(current_target._get_address()) if current_target is not None else 0
        )
    except Exception as exc:
        state._cancel_pending_floor_pickup(
            f"target validation failed: {type(exc).__name__}: {exc}"
        )
        return

    if current_address != target_address:
        state._cancel_pending_floor_pickup("crosshair target changed")
        return

    # Consume before entering the native router. Any ServerUseJunkObject
    # generated by the fallback itself must not be mistaken for competition.
    state._pending_floor_pickup_target = None
    state._pending_floor_pickup_time = 0.0
    state._pending_floor_pickup_released = False
    logging.info(
        "[BL4ThirdPersonPOC] Deferred TPS floor pickup won release fallback "
        f"after {elapsed:.3f}s: {target._path_name()}"
    )
    state._use_native_floor_pickup(target)


# Keep loader imports stable after the camera-event extraction.
from .camera_events import (
    _persist_camera_stack_owner_impl,
    _record_camera_stack_owner_impl,
    _clear_camera_stack_owner_impl,
    _retire_camera_stack_owner_impl,
    _defer_camera_pop_impl,
    _retry_pending_camera_pop_impl,
    _reset_camera_lifecycle_impl,
    _arm_camera_lifecycle_impl,
    _discard_camera_lifecycle_impl,
    _camera_lifecycle_offset_suppressed_impl,
    _remove_ffyl_early_handoff_hook_impl,
    _install_ffyl_early_handoff_hook_impl,
    _ffyl_early_ended_pre_hook_impl,
    _client_restart_pre_hook_impl,
    _ffyl_downed_pre_hook_impl,
    _install_ffyl_native_pre_hook_impl,
    _remove_ffyl_native_pre_hook_impl,
    _client_restart_post_hook_impl,
    _install_camera_lifecycle_hook_impl,
    _remove_camera_lifecycle_hook_impl,
    _update_camera_lifecycle_impl,
    _sample_slide_camera_offset_impl,
    _is_sliding_now_impl,
    _transition_to_first_person_impl,
    _update_slide_state_impl,
    _update_slide_camera_recovery_impl,
    _update_ladder_camera_state_impl,
    _update_vehicle_camera_state_impl,
)


def _purge_mod_sdk_hooks_impl(*, include_prompt: bool, owner_module) -> None:
    """Drop hooks by stable identifier when RLM has reset module bookkeeping."""
    hooks = (
        (
            owner_module.FIRST_PERSON_ANIM_HOOK,
            owner_module.Type.POST,
            owner_module.HOOK_IDENTIFIER,
        ),
        (
            owner_module.FIRST_PERSON_ANIM_HOOK,
            owner_module.Type.POST_UNCONDITIONAL,
            owner_module._MENU_UPDATE_HOOK,
        ),
        (
            owner_module.CLIENT_RESTART_FUNCTION,
            owner_module.Type.POST,
            owner_module.CLIENT_RESTART_IDENTIFIER,
        ),
        (
            owner_module.CLIENT_RESTART_FUNCTION,
            owner_module.Type.PRE,
            owner_module.CLIENT_RESTART_PRE_IDENTIFIER,
        ),
        (
            owner_module.FFYL_DOWNED_FUNCTION,
            owner_module.Type.PRE,
            owner_module.FFYL_NATIVE_PRE_IDENTIFIER,
        ),
        (
            owner_module.FFYL_EARLY_ENDED_FUNCTION,
            owner_module.Type.PRE,
            owner_module.FFYL_EARLY_ENDED_IDENTIFIER,
        ),
        (
            owner_module.SERVER_USE_OBJECT_FUNCTION,
            owner_module.Type.PRE,
            owner_module.INTERACTION_REDIRECT_IDENTIFIER,
        ),
        (
            owner_module.LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
            owner_module.Type.PRE,
            owner_module.FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
        ),
        (
            owner_module.CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
            owner_module.Type.POST,
            owner_module.SHOP_CAMERA_HOOK_IDENTIFIER,
        ),
        (
            owner_module.CAMERA_MODE_FUNCTION,
            owner_module.Type.PRE,
            owner_module.CAMERA_MODE_PROBE_IDENTIFIER,
        ),
        (
            owner_module.BLUEPRINT_UPDATE_CAMERA_FUNCTION,
            owner_module.Type.POST,
            owner_module.BLUEPRINT_CAMERA_PROBE_IDENTIFIER,
        ),
        (
            owner_module.PUSH_ACTOR_CAMERA_MODE_FUNCTION,
            owner_module.Type.PRE,
            owner_module.CAMERA_STACK_PROBE_IDENTIFIER,
        ),
        (
            owner_module.POP_ACTOR_CAMERA_MODE_FUNCTION,
            owner_module.Type.PRE,
            owner_module.CAMERA_STACK_PROBE_IDENTIFIER,
        ),
        (
            owner_module.ADS_ZOOM_CHANGE_FUNCTION,
            owner_module.Type.PRE,
            owner_module.ADS_ZOOM_CHANGE_IDENTIFIER,
        ),
        (
            owner_module.ADS_ZOOMED_OUT_FUNCTION,
            owner_module.Type.PRE,
            owner_module.ADS_ZOOMED_OUT_IDENTIFIER,
        ),
        (
            owner_module.ADS_WEAPON_EQUIPPED_FUNCTION,
            owner_module.Type.PRE,
            owner_module.ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER,
        ),
        (
            owner_module.ADS_WEAPON_EQUIPPED_FUNCTION,
            owner_module.Type.POST,
            owner_module.ADS_WEAPON_EQUIPPED_POST_IDENTIFIER,
        ),
        (
            owner_module.ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
            owner_module.Type.PRE,
            owner_module.ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER,
        ),
        (
            owner_module.ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
            owner_module.Type.POST,
            owner_module.ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER,
        ),
    ) + (
        (
            (
                owner_module.FIRST_PERSON_ANIM_HOOK,
                owner_module.Type.PRE,
                owner_module.INTERACTION_PROMPT_UPDATE_IDENTIFIER,
            ),
        )
        if include_prompt
        else ()
    )
    failures = []
    for function_path, hook_type, identifier in hooks:
        try:
            owner_module.remove_hook(function_path, hook_type, identifier)
        except Exception as exc:
            failures.append((identifier, type(exc).__name__))
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] SDK_HOOK_RECONCILE "
        f"requested={len(hooks)}, failures={failures}"
    )


def _on_enable_impl(*, owner_module) -> None:
    from . import npc_camera_visibility, vehicle_camera, vehicle_control, runtime_updates
    from . import omni

    # The experimental movement feature depends on runtime_updates and the
    # native helpers below; retire any state that survived a reload first.
    if not omni.shutdown(owner_module, "RELOAD"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Omnidirectional movement cleanup incomplete; restart game"
        )
        return
    if not vehicle_control.shutdown():
        owner_module.logging.error("[BL4ThirdPersonPOC] Vehicle control cleanup incomplete")
        return
    from . import action_keys

    if not action_keys.shutdown():
        owner_module.logging.error("[BL4ThirdPersonPOC] Action key sync cleanup incomplete")
        return
    from . import native_aim_origin

    try:
        aim_clean = native_aim_origin.shutdown()
    except Exception as exc:
        aim_clean = False
        owner_module.logging.error(
            f"[BL4ThirdPersonPOC] Aim-origin restore failed: {type(exc).__name__}: {exc}"
        )
    if not aim_clean:
        owner_module.logging.error("[BL4ThirdPersonPOC] Aim-origin restore incomplete; restart game")
        return
    if not vehicle_camera.shutdown():
        owner_module.logging.error('[BL4ThirdPersonPOC] Vehicle restoration incomplete; restart game')
        return
    if not runtime_updates.shutdown():
        owner_module.logging.error("[BL4ThirdPersonPOC] Update cleanup incomplete")
        return
    if not npc_camera_visibility.shutdown(owner_module, "mod_enable"):
        return
    owner_module._npc_camera_visibility_fault = False
    from . import placeable_targeting, npc_native_resume

    npc_native_resume.shutdown(owner_module)
    if not placeable_targeting.shutdown(owner_module):
        return
    from . import ground_slam_camera

    if not ground_slam_camera.shutdown("lifecycle_shutdown"):
        owner_module._ground_slam_beta_fault = True
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Ground Slam cleanup incomplete; restart game"
        )
        return
    from . import ffyl_strategy_runtime

    if not ffyl_strategy_runtime.shutdown(owner_module, "reload"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] FFYL cleanup incomplete; restart game"
        )
        return
    owner_module._ffyl_beta_fault = False
    owner_module._ground_slam_beta_fault = False
    owner_module._native_auto_enabled = True
    owner_module._ffyl_native_resume_pending = False
    owner_module._native_npc_pending = False
    owner_module._native_ffyl_pending = False
    owner_module._native_ffyl_pending_pawn = 0
    owner_module._ffyl_early_handoff_armed = False
    if (
        owner_module._native_active()
        or owner_module._active_native_state.get("ladder_default")
    ) and not owner_module._native_stop("reload"):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Native restore failed on reload; restart game"
        )
        return
    if owner_module._active_native_state.get("ladder_guard") is not None:
        try:
            from . import native_ladder_guard

            native_ladder_guard.remove(owner_module)
        except Exception as exc:
            owner_module.logging.error(
                "[BL4ThirdPersonPOC] LadderGuard survived reload; "
                f"restart game: {type(exc).__name__}: {exc}"
            )
            return
    from .settings_validation import sanitize_positions

    sanitize_positions(owner_module)
    owner_module._item_card_diagnostic_enabled = True
    owner_module._dynamic_motion_enabled = owner_module._load_dynamic_motion_choice()
    owner_module.dynamic_motion_camera_enabled.value = (
        owner_module._dynamic_motion_enabled
    )
    previous_menu = getattr(owner_module.builtins, owner_module._MENU_STATE_SLOT, None)
    if isinstance(previous_menu, dict):
        previous_close = previous_menu.get("close_callback")
        if callable(previous_close):
            try:
                previous_close("reload")
            except Exception as exc:
                owner_module.logging.error(
                    f"[BL4ThirdPersonPOC] MENU_RELOAD_CLOSE_FAILED {exc}"
                )
    owner_module._dynamic_motion_reset()
    owner_module._reset_reticle_publisher()
    owner_module._reset_mantle_camera_state()
    owner_module._last_slide_camera_force_time = 0.0
    owner_module._ladder_active = False
    owner_module._vehicle_camera_active = False
    owner_module._shop_camera_active = False
    owner_module._ladder_pending_third_person_enabled = None

    owner_module._third_person_enabled = False
    owner_module._third_person_pushed = bool(
        owner_module._camera_stack_owner.get("owned")
    )
    owner_module._ads_active = False
    owner_module._ads_route = "hip"
    owner_module._ads_tps_state = None
    owner_module._ads_collector_address = 0
    owner_module._reset_hybrid_ads_debug()
    owner_module._reset_ads_handoff_debug()
    owner_module._reset_ads_press_intent()
    owner_module._reset_camera_lifecycle()
    owner_module._camera_hotpath_debug.clear()
    owner_module._camera_hotpath_debug.update(
        {"total_failures": 0, "failures": {}, "last_error": "", "timings": {}}
    )

    owner_module._slide_active = False
    owner_module._slide_camera_recovery_pending = False
    owner_module._slide_camera_recovery_pawn = 0
    owner_module._camera_offset_gate_last = ""
    owner_module._last_anim_slide_states.clear()

    # Re-sample before retrying an RLM-persisted camera pop. Treating the
    # initial value as False could touch BL4's shared CameraModeState while a
    # vehicle view is already active.
    owner_module._vehicle_camera_active = owner_module._is_vehicle_camera_view()
    if owner_module._camera_stack_owner.get("pending_pop"):
        owner_module._retry_pending_camera_pop()
    owner_module._retry_native_patch_quarantine()
    if owner_module._active_native_state or owner_module._native_patch_quarantine:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Refusing to enable: native patch "
            "ownership survived reload or restoration failed; "
            "restart the game before enabling the mod"
        )
        return

    # Central build gate: every native table was measured on one executable.
    # On any other build install nothing and switch off the acting entry points.
    from . import build_gate

    gate = build_gate.status(owner_module)
    owner_module._build_gate_status = gate
    if not gate["reviewed"]:
        disabled = []
        for entry in tuple(owner_module._MOD_KEYBINDS) + tuple(owner_module._MOD_COMMANDS):
            if entry in owner_module._BUILD_GATE_ALLOWED_COMMANDS:
                continue
            try:
                entry.disable()
                disabled.append(getattr(entry, "identifier", None) or getattr(entry, "cmd", "?"))
            except Exception as exc:
                owner_module.logging.error(
                    f"[BL4ThirdPersonPOC] BUILD_GATE_DISABLE_FAILED {type(exc).__name__}: {exc}"
                )
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] INACTIVE_UNREVIEWED_BUILD "
            f"{build_gate.summary(gate)}; no hooks or native patches installed; "
            f"{len(disabled)} keybinds/commands switched off; console: bl4tps_build"
        )
        return

    owner_module._purge_mod_sdk_hooks(include_prompt=True)
    # A reexecuted module has empty lists even when Oak2 still holds the old
    # callback. Rebind must succeed before installing dependent native hooks.
    owner_module._hooks_installed.clear()
    owner_module._ads_hooks_installed.clear()
    owner_module._camera_stack_probes_installed.clear()
    owner_module._camera_mode_probe_installed = False
    owner_module._blueprint_camera_probe_installed = False
    owner_module._camera_lifecycle_hook_installed = False
    owner_module._ffyl_native_pre_installed = False
    owner_module._ffyl_early_handoff_hook_installed = False
    owner_module._interaction_redirect_installed = False
    owner_module._floor_pickup_priority_hook_installed = False
    owner_module._shop_camera_hook_installed = False

    # Publish FFYL ownership before the shared updater can run. Gameplay-only
    # build/stack checks wait until a settled local TPS frame, not mod import.
    if ffyl_strategy_runtime.setup(owner_module) is not True:
        return
    owner_module._install_hooks()
    if not owner_module._hooks_installed:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Refusing native install: camera updater did not bind"
        )
        return
    runtime_updates.start(owner_module)
    vehicle_camera.start(owner_module)
    if owner_module.vehicle_camera_relative_drive.value is True:
        vehicle_control.start(owner_module)
    try:
        action_keys.start(owner_module, owner_module._ACTION_KEY_BINDINGS)
    except Exception as exc:
        # Keybinds keep their shipped keys; everything else continues.
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Action key sync unavailable; default keys kept: "
            f"{type(exc).__name__}: {exc}"
        )
    try:
        # TPS aim trace starts at character depth for every weapon; the native
        # detour is written later on the first eligible game-thread frame.
        native_aim_origin.start(owner_module, runtime_updates)
    except Exception as exc:
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Aim-trace correction unavailable: "
            f"{type(exc).__name__}: {exc}"
        )
    omni.settings.set_diagnostics(owner_module.omni_movement_diagnostics.value is True)
    if owner_module.omni_movement_experimental.value is True and not omni.start(owner_module):
        owner_module.logging.error(
            "[BL4ThirdPersonPOC] Omnidirectional movement did not start; "
            "camera features continue without it"
        )
    owner_module._install_item_card_fusion()
    owner_module._install_interaction_prompt_targeting()
    placeable_targeting.install(owner_module)
    owner_module._install_npc_eligible()
    owner_module._install_interaction_redirect()
    npc_native_resume.install(owner_module)
    owner_module._install_hybrid_ads_hooks()
    owner_module._install_camera_lifecycle_hook()
    owner_module._install_ffyl_native_pre_hook()
    owner_module._install_ffyl_early_handoff_hook()
    owner_module._initialize_native_floor_pickup()
    owner_module._install_camera_mode_probe()
    owner_module._install_blueprint_camera_probe()
    if not owner_module._vehicle_camera_active:
        owner_module._set_camera_offset(0.0, 0.0, 0.0)

    owner_module.logging.info(
        "[BL4ThirdPersonPOC] Version "
        f"{owner_module.MOD_VERSION} enabled; native auto starts ON"
    )
    owner_module.logging.info(
        "[BL4ThirdPersonPOC] F5 / hold R3: Third Person, "
        "F6: Swap Shoulder, F8: Camera Dump, "
        "F10: Gameplay Debug State, Console: bl4tps_debug, "
        "bl4tps_ui_publish_topology, bl4tps_menu"
    )


def _on_disable_impl(*, owner_module) -> None:
    """Delegate the loader disable callback to the shutdown coordinator."""
    return _shutdown_mod_runtime(owner_module=owner_module)
