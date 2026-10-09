"""Menu widgets, read-only diagnostics, and bounded reporting.

Console command registration and SDK hook ownership remain in the loader.
"""

from __future__ import annotations

import builtins
import json
import math
import time
from typing import Any

from mods_base import get_pc

import unrealsdk as sdk
from unrealsdk import find_all, find_object, logging, make_struct
from .native_memory import _ads_object_address
from .camera_math import _ads_class_name, _ads_object_path

# ui_diagnostics.py
COLLECTOR_SURFACE_OUTBOUND_TOKENS = (
    "notify",
    "broadcast",
    "publish",
    "push",
    "refresh",
    "update",
    "changed",
    "change",
    "invalidate",
    "dirty",
    "bind",
    "data",
    "value",
    "visible",
    "visibility",
    "reticle",
    "crosshair",
)
COLLECTOR_SURFACE_UI_TOKENS = (
    "uidatacollector",
    "ui_data_collector",
    "dataprovider",
    "data_provider",
    "uimodel",
    "ui_model",
    "hud",
    "widget",
    "scaleform",
    "gfx",
    "coherent",
    "reticle",
    "crosshair",
)
COLLECTOR_SURFACE_MAX_FUNCTIONS = 256
COLLECTOR_SURFACE_MAX_CLASSES = 128

# Narrow, read-only topology probe for the native collector -> Cohtml UI
# publication boundary discovered by the 0.3.6ap surface catalog.  Exact
# owners keep the output deterministic and exclude unrelated UI classes.
UI_PUBLISH_TOPOLOGY_OWNERS = (
    "/Script/OakGame.OakUIDataCollector_WeaponStatus",
    "/Script/CohtmlPlugin.CohtmlWidget",
    "/Script/GbxUI.GbxUIView",
    "/Script/GbxUI.GbxUIViewManager",
    "/Script/GbxUI.GbxUISystem",
    "/Script/GbxUICoherent.GbxUICoherentSubsystem",
    "/Script/OakGame.OakUICoherentSubsystem",
    "/Script/GbxUIUMG.GbxUIUMGViewModelWidget",
)
UI_PUBLISH_TOPOLOGY_FUNCTIONS = (
    "/Script/OakGame.OakUIDataCollector_WeaponStatus:OnWeaponChanged",
    "/Script/OakGame.OakUIDataCollector_WeaponStatus:OnWeaponChangeStarted",
    "/Script/OakGame.OakUIDataCollector_WeaponStatus:OnWeaponChangeFinished",
    "/Script/CohtmlPlugin.CohtmlWidget:CreateDataModelFromObject",
    "/Script/CohtmlPlugin.CohtmlWidget:CreateDataModelFromStruct",
    "/Script/CohtmlPlugin.CohtmlWidget:IsReadyForBindings",
    "/Script/CohtmlPlugin.CohtmlWidget:RemoveDataModelFromObject",
    "/Script/CohtmlPlugin.CohtmlWidget:RemoveDataModelFromStruct",
    "/Script/CohtmlPlugin.CohtmlWidget:UpdateWholeDataModelFromObject",
    "/Script/CohtmlPlugin.CohtmlWidget:UpdateWholeDataModelFromStruct",
    "/Script/GbxUIUMG.GbxUIUMGViewModelWidget:RefreshDynamicBindings",
)


def _dump_collector_outbound_surface() -> None:
    logging.info("[BL4ThirdPersonPOC] ===== COLLECTOR OUTBOUND SURFACE START =====")
    try:
        status_objects = tuple(find_all("OakUIDataCollector_WeaponStatus"))
        logging.info(
            "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_STATUS_OBJECTS "
            f"count={len(status_objects)}"
        )
        hierarchy_names: set[str] = {
            "OakUIDataCollector_WeaponStatus",
            "OakUIDataCollector",
        }
        for ordinal, value in enumerate(status_objects[:16]):
            logging.info(
                "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_STATUS_OBJECT "
                f"ordinal={ordinal}, address=0x{_ads_object_address(value):016X}, "
                f"class={_ads_class_name(value)!r}, path={_ads_object_path(value)}"
            )
            try:
                superfields = tuple(value.Class._superfields())
            except Exception as exc:
                superfields = ()
                logging.warning(
                    "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_HIERARCHY_WARNING "
                    f"ordinal={ordinal}, error={type(exc).__name__}: {exc}"
                )
            for depth, field in enumerate(superfields):
                try:
                    name = str(field.Name)
                except Exception:
                    name = _ads_class_name(field)
                hierarchy_names.add(name)
                try:
                    property_count = len(tuple(field._properties()))
                except Exception:
                    property_count = -1
                logging.info(
                    "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_HIERARCHY "
                    f"ordinal={ordinal}, depth={depth}, name={name!r}, "
                    f"path={_ads_object_path(field)}, properties={property_count}"
                )

        function_rows: list[tuple[str, str]] = []
        functions_scanned = 0
        hierarchy_tokens = {name.lower() for name in hierarchy_names if name}
        for function in tuple(find_all("Function")):
            functions_scanned += 1
            path = _ads_object_path(function)
            lower = path.lower()
            if not path.startswith("/Script/") or ":" not in path:
                continue
            owner_path = path.split(":", 1)[0]
            owner_name = owner_path.rsplit(".", 1)[-1].lower()
            hierarchy_match = owner_name in hierarchy_tokens
            ui_match = any(token in lower for token in COLLECTOR_SURFACE_UI_TOKENS)
            outbound_match = any(
                token in lower for token in COLLECTOR_SURFACE_OUTBOUND_TOKENS
            )
            if hierarchy_match:
                function_rows.append(("hierarchy", path))
            elif ui_match and outbound_match:
                function_rows.append(("ui_outbound", path))
        function_rows = sorted(
            set(function_rows),
            key=lambda row: (0 if row[0] == "hierarchy" else 1, row[1]),
        )
        logging.info(
            "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_FUNCTION_SUMMARY "
            f"scanned={functions_scanned}, matched={len(function_rows)}, "
            f"emitted={min(len(function_rows), COLLECTOR_SURFACE_MAX_FUNCTIONS)}, "
            f"hierarchy_names={sorted(hierarchy_names)!r}"
        )
        for index, (reason, path) in enumerate(
            function_rows[:COLLECTOR_SURFACE_MAX_FUNCTIONS]
        ):
            logging.info(
                "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_FUNCTION "
                f"index={index}, reason={reason!r}, path={path}"
            )
        if len(function_rows) > COLLECTOR_SURFACE_MAX_FUNCTIONS:
            logging.warning(
                "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_FUNCTION_TRUNCATED "
                f"omitted={len(function_rows) - COLLECTOR_SURFACE_MAX_FUNCTIONS}"
            )

        class_rows: list[str] = []
        classes_scanned = 0
        for value in tuple(find_all("Class")):
            classes_scanned += 1
            path = _ads_object_path(value)
            lower = path.lower()
            if path.startswith("/Script/") and any(
                token in lower for token in COLLECTOR_SURFACE_UI_TOKENS
            ):
                class_rows.append(path)
        class_rows = sorted(set(class_rows))
        logging.info(
            "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_CLASS_SUMMARY "
            f"scanned={classes_scanned}, matched={len(class_rows)}, "
            f"emitted={min(len(class_rows), COLLECTOR_SURFACE_MAX_CLASSES)}"
        )
        for index, path in enumerate(class_rows[:COLLECTOR_SURFACE_MAX_CLASSES]):
            logging.info(
                "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_CLASS "
                f"index={index}, path={path}"
            )
        if len(class_rows) > COLLECTOR_SURFACE_MAX_CLASSES:
            logging.warning(
                "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_CLASS_TRUNCATED "
                f"omitted={len(class_rows) - COLLECTOR_SURFACE_MAX_CLASSES}"
            )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] COLLECTOR_SURFACE_ERROR "
            f"error={type(exc).__name__}: {exc}"
        )
    finally:
        logging.info("[BL4ThirdPersonPOC] ===== COLLECTOR OUTBOUND SURFACE END =====")


def _ui_topology_attr(value: Any, name: str) -> str:
    try:
        result = getattr(value, name)
    except Exception as exc:
        return f"<error {type(exc).__name__}: {exc}>"
    try:
        return repr(result)
    except Exception:
        return f"<{type(result).__name__}>"


def _dump_ui_publish_topology() -> None:
    """Catalog exact reflected surfaces without invoking or hooking them."""
    logging.info("[BL4ThirdPersonPOC] ===== UI PUBLISH TOPOLOGY START =====")
    try:
        all_functions = tuple(find_all("Function"))
        function_by_path = {
            _ads_object_path(function): function for function in all_functions
        }
        logging.info(
            "[BL4ThirdPersonPOC] UI_PUBLISH_SCAN "
            f"functions={len(all_functions)}, owners={len(UI_PUBLISH_TOPOLOGY_OWNERS)}, "
            f"targets={len(UI_PUBLISH_TOPOLOGY_FUNCTIONS)}"
        )

        for owner_path in UI_PUBLISH_TOPOLOGY_OWNERS:
            owner_name = owner_path.rsplit(".", 1)[-1]
            owner_class = None
            try:
                owner_class = find_object("Class", owner_path)
            except Exception as exc:
                logging.warning(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_OWNER_LOOKUP_ERROR "
                    f"owner={owner_path}, error={type(exc).__name__}: {exc}"
                )
            owned_functions = sorted(
                path for path in function_by_path if path.startswith(owner_path + ":")
            )
            instances = ()
            try:
                instances = tuple(find_all(owner_name))
            except Exception as exc:
                logging.warning(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_INSTANCE_LOOKUP_ERROR "
                    f"owner={owner_path}, error={type(exc).__name__}: {exc}"
                )
            logging.info(
                "[BL4ThirdPersonPOC] UI_PUBLISH_OWNER "
                f"path={owner_path}, loaded={owner_class is not None}, "
                f"functions={len(owned_functions)}, instances={len(instances)}"
            )
            if owner_class is not None:
                try:
                    superfields = tuple(owner_class._superfields())
                except Exception:
                    superfields = ()
                for depth, field in enumerate(superfields):
                    try:
                        properties = tuple(field._properties())
                    except Exception:
                        properties = ()
                    logging.info(
                        "[BL4ThirdPersonPOC] UI_PUBLISH_OWNER_HIERARCHY "
                        f"owner={owner_path}, depth={depth}, "
                        f"field={_ads_object_path(field)}, properties={len(properties)}"
                    )
                    for ordinal, prop in enumerate(properties):
                        logging.info(
                            "[BL4ThirdPersonPOC] UI_PUBLISH_OWNER_PROPERTY "
                            f"owner={owner_path}, depth={depth}, ordinal={ordinal}, "
                            f"name={_ui_topology_attr(prop, 'Name')}, "
                            f"class={_ads_class_name(prop)!r}, "
                            f"offset={_ui_topology_attr(prop, 'Offset_Internal')}, "
                            f"element_size={_ui_topology_attr(prop, 'ElementSize')}, "
                            f"array_dim={_ui_topology_attr(prop, 'ArrayDim')}, "
                            f"flags={_ui_topology_attr(prop, 'PropertyFlags')}"
                        )
            for ordinal, instance in enumerate(instances[:16]):
                logging.info(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_INSTANCE "
                    f"owner={owner_path}, ordinal={ordinal}, "
                    f"address=0x{_ads_object_address(instance):016X}, "
                    f"class={_ads_class_name(instance)!r}, path={_ads_object_path(instance)}"
                )
            for ordinal, path in enumerate(owned_functions):
                logging.info(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_OWNER_FUNCTION "
                    f"owner={owner_path}, ordinal={ordinal}, path={path}"
                )

        for target_path in UI_PUBLISH_TOPOLOGY_FUNCTIONS:
            function = function_by_path.get(target_path)
            logging.info(
                "[BL4ThirdPersonPOC] UI_PUBLISH_FUNCTION "
                f"path={target_path}, found={function is not None}"
            )
            if function is None:
                continue
            logging.info(
                "[BL4ThirdPersonPOC] UI_PUBLISH_FUNCTION_META "
                f"path={target_path}, address=0x{_ads_object_address(function):016X}, "
                f"class={_ads_class_name(function)!r}, "
                f"flags={_ui_topology_attr(function, 'FunctionFlags')}, "
                f"parms_size={_ui_topology_attr(function, 'ParmsSize')}, "
                f"num_parms={_ui_topology_attr(function, 'NumParms')}, "
                f"return_offset={_ui_topology_attr(function, 'ReturnValueOffset')}"
            )
            try:
                parameters = tuple(function._properties())
            except Exception as exc:
                parameters = ()
                logging.warning(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_FUNCTION_PROPERTIES_ERROR "
                    f"path={target_path}, error={type(exc).__name__}: {exc}"
                )
            logging.info(
                "[BL4ThirdPersonPOC] UI_PUBLISH_FUNCTION_PROPERTIES "
                f"path={target_path}, count={len(parameters)}"
            )
            for ordinal, prop in enumerate(parameters):
                logging.info(
                    "[BL4ThirdPersonPOC] UI_PUBLISH_FUNCTION_PROPERTY "
                    f"path={target_path}, ordinal={ordinal}, "
                    f"name={_ui_topology_attr(prop, 'Name')}, "
                    f"class={_ads_class_name(prop)!r}, "
                    f"offset={_ui_topology_attr(prop, 'Offset_Internal')}, "
                    f"element_size={_ui_topology_attr(prop, 'ElementSize')}, "
                    f"array_dim={_ui_topology_attr(prop, 'ArrayDim')}, "
                    f"flags={_ui_topology_attr(prop, 'PropertyFlags')}, "
                    f"property_class={_ui_topology_attr(prop, 'PropertyClass')}, "
                    f"struct={_ui_topology_attr(prop, 'Struct')}, "
                    f"enum={_ui_topology_attr(prop, 'Enum')}"
                )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] UI_PUBLISH_TOPOLOGY_ERROR "
            f"error={type(exc).__name__}: {exc}"
        )
    finally:
        logging.info("[BL4ThirdPersonPOC] ===== UI PUBLISH TOPOLOGY END =====")


# menu_widgets.py
def _menu_widget(kind: str, owner: Any) -> Any:
    return sdk.construct_object(kind, owner)


def _menu_text(owner: Any, value: str) -> Any:
    label = _menu_widget("TextBlock", owner)
    label.SetText(value)
    label.SetAutoWrapText(True)
    return label


def _menu_sized(owner: Any, child: Any, *, width: int = 0, height: int = 0) -> Any:
    box = _menu_widget("SizeBox", owner)
    if width:
        box.SetWidthOverride(float(width))
    if height:
        box.SetHeightOverride(float(height))
    box.SetContent(child)
    return box


def _menu_gap(owner: Any, height: int) -> None:
    gap = _menu_widget("SizeBox", owner)
    gap.SetHeightOverride(float(height))
    owner.AddChildToVerticalBox(gap)


def _menu_button(owner: Any, label: str, width: int = 120) -> Any:
    button = _menu_widget("Button", owner)
    button.SetContent(_menu_text(button, label))
    owner.AddChildToVerticalBox(_menu_sized(owner, button, width=width, height=44))
    return button


# camera_diagnostics.py
def _dump_unreal_object(label: str, obj: Any) -> None:
    logging.info(f"[BL4ThirdPersonPOC] ----- {label} -----")

    if obj is None:
        logging.info(f"[BL4ThirdPersonPOC] {label} = None")
        return

    logging.info(f"[BL4ThirdPersonPOC] {label} object = {obj!r}")

    property_names: set[str] = set()

    try:
        unreal_class = obj.Class

        for unreal_struct in unreal_class._superfields():
            for prop in unreal_struct._properties():
                property_names.add(str(prop.Name))

    except Exception as exc:
        logging.warning(
            f"[BL4ThirdPersonPOC] Could not enumerate "
            f"{label} through Class: "
            f"{type(exc).__name__}: {exc}"
        )

    try:
        for name in dir(obj):
            if not name.startswith("_"):
                property_names.add(str(name))
    except Exception as exc:
        logging.warning(
            f"[BL4ThirdPersonPOC] Could not enumerate "
            f"{label} through dir(): "
            f"{type(exc).__name__}: {exc}"
        )

    for name in sorted(property_names):
        try:
            value = getattr(obj, name)

            if callable(value):
                continue

            value_text = repr(value)

            if len(value_text) > 1000:
                value_text = value_text[:1000] + " ... <truncated>"

            logging.info(f"[BL4ThirdPersonPOC] " f"{label}.{name} = {value_text}")

        except Exception as exc:
            logging.warning(
                f"[BL4ThirdPersonPOC] Could not read "
                f"{label}.{name}: "
                f"{type(exc).__name__}: {exc}"
            )


SLIDE_FIELD_TOKENS = (
    "slide",
    "sliding",
    "crouch",
    "movement",
    "locomotion",
    "stance",
    "sprint",
    "ground",
    "fall",
    "action",
    "posture",
)


def _is_interesting_slide_field(name: str) -> bool:
    lower_name = name.lower()

    return any(token in lower_name for token in SLIDE_FIELD_TOKENS)


def _dump_slide_object(label: str, obj: Any) -> None:
    logging.info(f"[BL4ThirdPersonPOC] ----- SLIDE OBJECT: {label} -----")

    if obj is None:
        logging.info(f"[BL4ThirdPersonPOC] {label} = None")
        return

    logging.info(f"[BL4ThirdPersonPOC] {label} object = {obj!r}")

    try:
        names = sorted(
            name
            for name in dir(obj)
            if not name.startswith("_") and _is_interesting_slide_field(name)
        )
    except Exception as exc:
        logging.warning(
            f"[BL4ThirdPersonPOC] Could not enumerate {label}: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    if not names:
        logging.info(f"[BL4ThirdPersonPOC] " f"No matching fields found on {label}")
        return

    for name in names:
        try:
            value = getattr(obj, name)

            if callable(value):
                continue

            value_text = repr(value)

            if len(value_text) > 750:
                value_text = value_text[:750] + " ... <truncated>"

            logging.info(f"[BL4ThirdPersonPOC] " f"{label}.{name} = {value_text}")

        except Exception as exc:
            logging.warning(
                f"[BL4ThirdPersonPOC] Could not read "
                f"{label}.{name}: "
                f"{type(exc).__name__}: {exc}"
            )


def _dump_camera_state_impl(
    _get_runtime,
    _third_person_enabled,
    _third_person_pushed,
    _ads_active,
) -> None:
    pc, pawn, camera_manager = _get_runtime()

    try:
        actor_camera_mode = (
            camera_manager.GetActorCameraMode(pawn)
            if camera_manager is not None and pawn is not None
            else None
        )

        logging.info(
            "[BL4ThirdPersonPOC] " f"GetActorCameraMode = " f"{actor_camera_mode!r}"
        )

    except Exception as exc:
        logging.warning(
            "[BL4ThirdPersonPOC] Could not query "
            "ActorCameraMode: "
            f"{type(exc).__name__}: {exc}"
        )

    logging.info("[BL4ThirdPersonPOC] ===== CAMERA STATE DUMP =====")
    logging.info(
        "[BL4ThirdPersonPOC] "
        f"enabled={_third_person_enabled}, "
        f"pushed={_third_person_pushed}, "
        f"ads={_ads_active}"
    )
    logging.info(
        "[BL4ThirdPersonPOC] " f"pc={pc!r}, pawn={pawn!r}, manager={camera_manager!r}"
    )

    if camera_manager is None:
        logging.warning("[BL4ThirdPersonPOC] No camera manager available")
        return

    try:
        camera_mode_state = camera_manager.CameraModeState
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Could not read CameraModeState: "
            f"{type(exc).__name__}: {exc}"
        )
        camera_mode_state = None

    try:
        camera_mode_inputs = camera_manager.CameraModeInputs
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Could not read CameraModeInputs: "
            f"{type(exc).__name__}: {exc}"
        )
        camera_mode_inputs = None

    _dump_unreal_object(
        "CameraModeState",
        camera_mode_state,
    )
    _dump_unreal_object(
        "CameraModeInputs",
        camera_mode_inputs,
    )

    logging.info("[BL4ThirdPersonPOC] ----- CameraManager mode fields -----")

    try:
        manager_names = sorted(
            name
            for name in dir(camera_manager)
            if "mode" in name.lower()
            or "camera" in name.lower()
            or "view" in name.lower()
        )
    except Exception:
        manager_names = []

    for name in manager_names:
        if name.startswith("_"):
            continue

        try:
            value = getattr(camera_manager, name)

            if callable(value):
                continue

            value_text = repr(value)

            if len(value_text) > 1000:
                value_text = value_text[:1000] + " ... <truncated>"

            logging.info("[BL4ThirdPersonPOC] " f"CameraManager.{name} = {value_text}")

        except Exception:
            pass

    logging.info("[BL4ThirdPersonPOC] ===== END CAMERA STATE DUMP =====")


def _dump_slide_state_impl(
    _get_runtime,
    _third_person_enabled,
    _third_person_pushed,
    _ads_active,
    _last_anim_slide_states,
) -> None:
    _pc, pawn, camera_manager = _get_runtime()

    logging.info("[BL4ThirdPersonPOC] ===== SLIDE STATE DUMP =====")
    logging.info(
        "[BL4ThirdPersonPOC] "
        f"third_person_enabled={_third_person_enabled}, "
        f"third_person_pushed={_third_person_pushed}, "
        f"ads_active={_ads_active}"
    )

    _dump_slide_object(
        "Character",
        pawn,
    )

    movement_objects: dict[str, Any] = {}

    if pawn is not None:
        for attribute in (
            "CharacterMovement",
            "CharacterMovementComponent",
            "MovementComponent",
            "OakCharacterMovement",
        ):
            try:
                value = getattr(pawn, attribute)

                if value is not None:
                    movement_objects[attribute] = value
            except Exception:
                pass

        try:
            for name in dir(pawn):
                if "movement" not in name.lower():
                    continue

                try:
                    value = getattr(pawn, name)

                    if value is None or callable(value):
                        continue

                    if hasattr(value, "Class"):
                        movement_objects[name] = value
                except Exception:
                    pass
        except Exception:
            pass

    for name, movement_object in movement_objects.items():
        _dump_slide_object(
            f"Movement.{name}",
            movement_object,
        )

    for name, is_sliding in sorted(_last_anim_slide_states.items()):
        logging.info(
            "[BL4ThirdPersonPOC] " f"Animation.{name}.bIsSliding = {is_sliding!r}"
        )

    if camera_manager is not None:
        try:
            _dump_slide_object(
                "CameraModeInputs",
                camera_manager.CameraModeInputs,
            )
        except Exception:
            pass

    logging.info("[BL4ThirdPersonPOC] ===== END SLIDE STATE DUMP =====")


# gameplay_diagnostics.py
def _emit_gameplay_debug_state(
    *,
    _reticle_publish_faulted,
    _reticle_publish_counts,
    _third_person_enabled,
    _third_person_pushed,
    _ads_active,
    _ads_route,
    _ladder_active,
    _vehicle_camera_active,
    _shop_camera_active,
    _slide_active,
    _slide_camera_recovery_pending,
    _slide_camera_recovery_pawn,
    _camera_offset_gate_last,
    _camera_stack_owner,
    _camera_hotpath_debug,
    _native_patch_quarantine,
    _item_card_state,
    _item_card_hook_counter,
    _interaction_prompt_state,
    _log_hybrid_ads_debug,
    _log_camera_lifecycle_debug,
) -> None:
    logging.info(
        f"[BL4ThirdPersonPOC] TPS_RETICLE_PUBLISH_STATE faulted={_reticle_publish_faulted}, counts={_reticle_publish_counts}"
    )
    logging.info("[BL4ThirdPersonPOC] ===== GAMEPLAY DEBUG STATE =====")
    logging.info(
        "[BL4ThirdPersonPOC] "
        f"third_person_enabled={_third_person_enabled}, "
        f"third_person_pushed={_third_person_pushed}, "
        f"ads={_ads_active}, ads_route={_ads_route!r}, "
        f"ladder={_ladder_active}, "
        f"vehicle={_vehicle_camera_active}, shop={_shop_camera_active}"
    )
    logging.info(
        "[BL4ThirdPersonPOC] CAMERA_RECOVERY_STATE "
        f"slide={_slide_active}, pending={_slide_camera_recovery_pending}, "
        f"pawn=0x{_slide_camera_recovery_pawn:016X}, "
        f"offset_gate={_camera_offset_gate_last!r}"
    )
    logging.info("[BL4ThirdPersonPOC] camera_stack_owner=" f"{_camera_stack_owner!r}")
    logging.info(
        "[BL4ThirdPersonPOC] camera_hotpath="
        f"{{'total_failures': {_camera_hotpath_debug.get('total_failures', 0)}, "
        f"'failures': {_camera_hotpath_debug.get('failures', {})!r}, "
        f"'last_error': {_camera_hotpath_debug.get('last_error', '')!r}}}, "
        f"native_quarantine={len(_native_patch_quarantine)}"
    )
    logging.info(
        "[BL4ThirdPersonPOC] CAMERA_STAGE_TIME use bl4tps_perf "
        "or bl4tps_slide_perf for bounded stage measurements"
    )
    state = _item_card_state
    if not isinstance(state, dict):
        logging.info("[BL4ThirdPersonPOC] item_card_state=<not installed>")
    else:
        final_hook = state.get("final_hook")
        gate2_hook = state.get("gate2_hook")
        selected = 0
        enabled = 0
        if isinstance(final_hook, dict):
            selected = int(final_hook["control"].selected_actor)
            enabled = int(final_hook["control"].enabled)
        gate2_total = (
            _item_card_hook_counter(gate2_hook) if isinstance(gate2_hook, dict) else 0
        )
        final_total = (
            int(state["final_calls_completed"]) + _item_card_hook_counter(final_hook)
            if isinstance(final_hook, dict)
            else int(state["final_calls_completed"])
        )
        logging.info(
            "[BL4ThirdPersonPOC] ITEM_CARD_STATE "
            f"ready={state['ready']}, active={state['active']}, "
            f"override_enabled={enabled}, "
            f"selected={f'0x{selected:016X}' if selected else '<clear>'}, "
            f"visible_pickups={len(state['pickups'])}, "
            f"gate2_total={gate2_total}, final_total={final_total}, "
            f"updates={state['selection_updates']}, "
            f"geometry_errors={state['geometry_errors']}, "
            f"update_errors={state['update_errors']}"
        )
        logging.info(
            "[BL4ThirdPersonPOC] ITEM_CARD_PERF "
            f"pickup_scans={state['pickup_scans']} "
            f"scan_max_ms={state['pickup_scan_max_seconds'] * 1000:.3f} "
            f"scan_avg_ms={state['pickup_scan_seconds'] * 1000 / max(1, state['pickup_scans']):.3f} "
            f"select_max_ms={state['selector_max_seconds'] * 1000:.3f} "
            f"select_avg_ms={state['selector_seconds'] * 1000 / max(1, state['selector_samples']):.3f}"
        )
        for index, (address, path) in enumerate(sorted(state["pickups"].items())[:32]):
            logging.info(
                "[BL4ThirdPersonPOC] "
                f"item_card_pickup[{index}]=0x{address:016X}, "
                f"path={path}"
            )
    prompt_state = _interaction_prompt_state
    if not isinstance(prompt_state, dict):
        logging.info("[BL4ThirdPersonPOC] prompt_target_state=<not installed>")
    else:
        logging.info(
            "[BL4ThirdPersonPOC] PROMPT_TARGET_STATE "
            f"ready={prompt_state['ready']}, "
            f"active={prompt_state['active']}, "
            f"override_enabled={int(prompt_state['control'].enabled)}, "
            f"native_calls={int(prompt_state['counter'].value)}, "
            f"updates={prompt_state['updates']}, "
            f"transitions={prompt_state['transitions']}, "
            f"update_errors={prompt_state['update_errors']}, "
            f"last_class={prompt_state['last_hit_class']!r}, "
            f"last_path={prompt_state['last_hit_path']}"
        )
    _log_hybrid_ads_debug("F10")
    _log_camera_lifecycle_debug("F10")
    logging.info("[BL4ThirdPersonPOC] ===== END GAMEPLAY DEBUG STATE =====")


# debug_summaries.py
def _log_camera_lifecycle_debug(label: str, _camera_lifecycle: dict[str, Any]) -> None:
    state = _camera_lifecycle
    logging.info(
        "[BL4ThirdPersonPOC] CAMERA_LIFECYCLE_SUMMARY "
        f"label={label!r}, reason={state.get('reason')!r}, "
        f"phase={state.get('phase')!r}, pending={state.get('pending')}, "
        f"restart_calls={state.get('restart_calls', 0)}, "
        f"local_restarts={state.get('local_restarts', 0)}, "
        f"ffyl_entries={state.get('ffyl_entries', 0)}, "
        f"ffyl_direct_defaults={state.get('ffyl_direct_defaults', 0)}, "
        f"runtime_unavailable_frames="
        f"{state.get('runtime_unavailable_frames', 0)}, "
        f"offset_suppressions={state.get('offset_suppressions', 0)}, "
        f"repair_attempts={state.get('repair_attempts', 0)}, "
        f"repair_successes={state.get('repair_successes', 0)}, "
        f"preserved_tps={state.get('preserved_tps', 0)}, "
        f"vehicle_discards={state.get('vehicle_discards', 0)}, "
        f"vehicle_restart_ignores="
        f"{state.get('vehicle_restart_ignores', 0)}, "
        f"errors={state.get('errors', 0)}, "
        f"last_error={state.get('last_error', '')!r}"
    )


def _log_hybrid_ads_debug(
    label: str,
    _ads_debug: dict[str, Any],
    _ads_route: str,
    _ads_active: bool,
    _ads_press_intent: dict[str, Any],
    _ads_handoff: dict[str, Any],
) -> None:
    elapsed = time.perf_counter() - float(
        _ads_debug.get("started", time.perf_counter())
    )
    logging.info(
        "[BL4ThirdPersonPOC] HYBRID_ADS_SUMMARY "
        f"label={label!r}, seconds={elapsed:.3f}, "
        f"route={_ads_route!r}, active={_ads_active}, "
        f"tps_presses={_ads_debug.get('tps_presses', 0)}, "
        f"tps_releases={_ads_debug.get('tps_releases', 0)}, "
        f"sniper_presses={_ads_debug.get('sniper_presses', 0)}, "
        f"fallback_presses={_ads_debug.get('fallback_presses', 0)}, "
        f"native_releases={_ads_debug.get('native_releases', 0)}, "
        f"completed_cycles={_ads_debug.get('completed_cycles', 0)}, "
        f"interrupted_zoom_ins={_ads_debug.get('interrupted_zoom_ins', 0)}, "
        f"reversed_zoom_outs={_ads_debug.get('reversed_zoom_outs', 0)}, "
        f"ignored_events={_ads_debug.get('ignored_events', 0)}, "
        f"aborts={_ads_debug.get('aborts', 0)}, "
        f"zoom_change_blocked={_ads_debug.get('zoom_change_blocked', 0)}, "
        f"pending_zoom_change_blocked="
        f"{_ads_debug.get('pending_zoom_change_blocked', 0)}, "
        f"zoom_change_native={_ads_debug.get('zoom_change_native', 0)}, "
        f"stale_zoomed_out_blocked="
        f"{_ads_debug.get('stale_zoomed_out_blocked', 0)}, "
        f"zoomed_out_native={_ads_debug.get('zoomed_out_native', 0)}, "
        f"press_intents={_ads_press_intent.get('presses', 0)}, "
        f"press_confirmed={_ads_press_intent.get('confirmed', 0)}, "
        f"deferred_presses="
        f"{_ads_press_intent.get('deferred_presses', 0)}, "
        f"deferred_resolved="
        f"{_ads_press_intent.get('deferred_resolved', 0)}, "
        f"deferred_cancelled="
        f"{_ads_press_intent.get('deferred_cancelled', 0)}, "
        f"throwable_bypasses="
        f"{_ads_press_intent.get('throwable_bypasses', 0)}, "
        f"release_bypasses="
        f"{_ads_press_intent.get('release_bypasses', 0)}, "
        f"press_invalidations="
        f"{_ads_press_intent.get('invalidations', 0)}, "
        f"weak_wants_rejected="
        f"{_ads_press_intent.get('weak_signal_rejections', 0)}, "
        f"press_equip_gaps="
        f"{_ads_press_intent.get('equip_gaps', 0)}, "
        f"press_equip_rebinds="
        f"{_ads_press_intent.get('equip_rebinds', 0)}, "
        f"press_errors={_ads_press_intent.get('errors', 0)}, "
        f"categories={_ads_debug.get('category_counts', {})}, "
        f"handoff_gaps={_ads_handoff.get('gap_entries', 0)}, "
        f"handoff_rebinds={_ads_handoff.get('rebinds', 0)}, "
        f"handoff_equip_pre={_ads_handoff.get('equip_pre', 0)}, "
        f"handoff_equip_post={_ads_handoff.get('equip_post', 0)}, "
        f"handoff_latch_releases="
        f"{_ads_handoff.get('latch_releases', 0)}, "
        f"reticle_rebind_arms="
        f"{_ads_handoff.get('reticle_rebind_arms', 0)}, "
        f"late_equip_arms="
        f"{_ads_handoff.get('late_equip_arms', 0)}, "
        f"character_equip_pre="
        f"{_ads_handoff.get('character_equip_pre', 0)}, "
        f"character_equip_post="
        f"{_ads_handoff.get('character_equip_post', 0)}, "
        f"character_equip_arms="
        f"{_ads_handoff.get('character_equip_arms', 0)}, "
        f"character_equip_reuses="
        f"{_ads_handoff.get('character_equip_reuses', 0)}, "
        f"character_equip_refusals="
        f"{_ads_handoff.get('character_equip_refusals', 0)}, "
        f"character_equip_errors="
        f"{_ads_handoff.get('character_equip_errors', 0)}, "
        f"character_equip_last_reason="
        f"{_ads_handoff.get('character_equip_last_reason', '')!r}, "
        f"reticle_rebind_completions="
        f"{_ads_handoff.get('reticle_rebind_completions', 0)}, "
        f"reticle_rebind_cancellations="
        f"{_ads_handoff.get('reticle_rebind_cancellations', 0)}, "
        f"pose_commit_attempts="
        f"{_ads_handoff.get('pose_commit_attempts', 0)}, "
        f"pose_commits={_ads_handoff.get('pose_commits', 0)}, "
        f"pose_commit_skips={_ads_handoff.get('pose_commit_skips', 0)}, "
        f"route_tps_to_fps={_ads_handoff.get('tps_to_fps', 0)}, "
        f"route_fps_to_tps={_ads_handoff.get('fps_to_tps', 0)}, "
        f"handoff_errors={_ads_handoff.get('errors', 0)}, "
        f"errors={_ads_debug.get('errors', 0)}, "
        f"last_error={_ads_debug.get('last_error', '')!r}"
    )


# perf_reporting.py
def _emit_perf_report(
    probe: dict[str, Any],
    _native_auto_enabled: bool,
    _native_fault: bool,
) -> None:
    elapsed_ms = (time.perf_counter_ns() - probe["started_ns"]) / 1e6
    logging.warning(
        "[BL4ThirdPersonPOC] PERF_RESULT "
        f'updates={probe["frames"]} elapsed_ms={elapsed_ms:.1f} '
        f'auto_start={probe["auto_start"]} auto_end={_native_auto_enabled} '
        f'fault={_native_fault} limit={probe.get("limit", "manual")}; '
        "hook_interval is NOT an engine/GPU frame time"
    )
    for name, (calls, total, maximum) in sorted(probe["metrics"].items()):
        logging.warning(
            "[BL4ThirdPersonPOC] PERF_STAGE "
            f"name={name} calls={calls} "
            f"avg_ms={total/max(calls, 1)/1e6:.3f} "
            f"max_ms={maximum/1e6:.3f}"
        )
    for second, bucket in sorted(probe["buckets"].items()):
        logging.warning(
            "[BL4ThirdPersonPOC] PERF_SECOND "
            f'second={second} updates={bucket["calls"]} '
            f'interval_max_ms={bucket["interval_max"]/1e6:.3f} '
            f'work_max_ms={bucket["work_max"]/1e6:.3f} '
            f'item_max_ms={bucket["item_max"]/1e6:.3f}'
        )
    for kind in ("slow_work", "slow_interval"):
        for (
            magnitude,
            frame,
            since_ns,
            work_ns,
            interval_ns,
            stage,
            stage_ns,
            item,
            slide,
        ) in sorted(probe[kind], key=lambda row: row[0], reverse=True):
            logging.warning(
                "[BL4ThirdPersonPOC] PERF_SLOW "
                f"kind={kind} update={frame} since_ms={since_ns/1e6:.1f} "
                f"work_ms={work_ns/1e6:.3f} "
                f"interval_ms={interval_ns/1e6:.3f} "
                f"top_stage={stage} top_stage_ms={stage_ns/1e6:.3f} "
                f"item={item} slide={slide}"
            )
    for duration, frame, since_ns, scan in sorted(
        probe["slow_item"], key=lambda row: row[0], reverse=True
    ):
        logging.warning(
            "[BL4ThirdPersonPOC] PERF_ITEM "
            f"update={frame} since_ms={since_ns/1e6:.1f} "
            f"total_ms={duration/1e6:.3f} "
            f'found={scan["found"]} new={scan["new"]} '
            f'visible={scan["visible"]} rebuilt={scan["rebuilt"]} '
            f'find_ms={scan["find_ns"]/1e6:.3f} '
            f'inspect_ms={scan["inspect_ns"]/1e6:.3f} '
            f'geometry_ms={scan["geometry_ns"]/1e6:.3f} '
            f'rebuild_ms={scan["rebuild_ns"]/1e6:.3f} '
            f'other_ms={scan["other_ns"]/1e6:.3f}'
        )


def _emit_slide_perf_report(
    probe: dict[str, Any],
    _native_auto_enabled: bool,
    _native_fault: bool,
) -> None:
    logging.warning(
        "[BL4ThirdPersonPOC] SLIDE_PERF_RESULT "
        f'auto_at_start={probe["auto_at_start"]} '
        f"auto_at_end={_native_auto_enabled} "
        f'frames={probe["frame"]} slide_seen={probe["slide_seen"]} '
        f"fault={_native_fault}"
    )
    for name, row in sorted(probe["stages"].items()):
        logging.warning(
            "[BL4ThirdPersonPOC] SLIDE_PERF_STAGE "
            f'name={name} calls={row["calls"]} '
            f'avg_ms={row["total_ns"] / row["calls"] / 1e6:.3f} '
            f'max_ms={row["max_ns"] / 1e6:.3f}'
        )
    for sample in sorted(probe["top"], key=lambda row: row[0], reverse=True):
        elapsed_ns, frame, stage, in_slide, pending, since_ns = sample
        logging.warning(
            "[BL4ThirdPersonPOC] SLIDE_PERF_SLOW "
            f"frame={frame} since_ms={since_ns / 1e6:.1f} "
            f"stage={stage} duration_ms={elapsed_ns / 1e6:.3f} "
            f"slide={in_slide} handoff_pending={pending}"
        )


# Menu lifecycle. The loader owns current state and stable callback identities.
def _menu_close_impl(
    reason: str = "command",
    *,
    _get_menu_state,
    _set_menu_state,
    _menu_hook_installed,
    _menu_hook_remove,
    _MENU_STATE_SLOT,
    camera_offset_x,
    camera_offset_y,
    camera_offset_z,
    mod,
) -> None:
    state = _get_menu_state()
    if state is None or state.get("closed"):
        return
    if reason in ("button", "command") and state.get("numeric_finalize"):
        try:
            state["numeric_finalize"]()
        except Exception as exc:
            logging.error(f"[BL4ThirdPersonPOC] MENU_NUMERIC_COMMIT_FAILED {exc}")
    state["closed"] = True
    state["poll_via_camera_update"] = False
    try:
        if _menu_hook_installed():
            _menu_hook_remove()
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_HOOK_REMOVE_FAILED {exc}")
    if reason in ("button", "command"):
        try:
            for index, (slider, option) in enumerate(
                zip(
                    state["sliders"],
                    (camera_offset_x, camera_offset_y, camera_offset_z),
                )
            ):
                value = float(slider.GetValue())
                if math.isfinite(value):
                    lo, hi = state["ranges"][index]
                    option.value = max(
                        lo,
                        min(
                            hi, int(math.copysign(math.floor(abs(value) + 0.5), value))
                        ),
                    )
                    if state["values"][index] != option.value:
                        state["dirty"] = True
        except Exception as exc:
            logging.error(f"[BL4ThirdPersonPOC] MENU_FINAL_COMMIT_FAILED {exc}")
    try:
        if state.get('vehicle_finalize'):
            state['vehicle_finalize'](reason in ('button', 'command'))
    except Exception as exc:
        logging.error(f'[BL4ThirdPersonPOC] MENU_VEHICLE_COMMIT_FAILED {exc}')
    try:
        if state.get("motion_finalize"):
            state["motion_finalize"](reason in ("button", "command"))
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_MOTION_SAVE_FAILED {exc}")
    try:
        state["root"].RemoveFromParent()
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_REMOVE_FAILED {exc}")
    try:
        pc = get_pc(possibly_loading=True)
        if pc == state["pc"]:
            state["library"].SetInputMode_GameOnly(pc, True)
            pc.bShowMouseCursor = state["cursor"]
            pc.CurrentMouseCursor = state["cursor_shape"]
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_INPUT_RESTORE_FAILED {exc}")
    if state.get("dirty"):
        try:
            mod.save_settings()
            logging.info("[BL4ThirdPersonPOC] MENU_SETTINGS_SAVED")
        except Exception as exc:
            logging.error(
                f"[BL4ThirdPersonPOC] MENU_SETTINGS_SAVE_FAILED {type(exc).__name__}: {exc}"
            )
    if getattr(builtins, _MENU_STATE_SLOT, None) is state:
        delattr(builtins, _MENU_STATE_SLOT)
    _set_menu_state(None)
    logging.info(f"[BL4ThirdPersonPOC] MENU_CLOSED reason={reason!r}")


def _menu_open_impl(
    *,
    _get_menu_state,
    _set_menu_state,
    _menu_close,
    _menu_poll,
    _menu_hook_install,
    _menu_camera_update_ready,
    _MENU_STATE_SLOT,
    _third_person_enabled,
    _get_dynamic_motion_enabled,
    camera_offset_x,
    camera_offset_y,
    camera_offset_z,
    motion_parameters,
    save_motion,
    reset_motion,
    get_sniper_mode,
    set_sniper_mode,
    get_ffyl_mode,
    set_ffyl_mode,
    get_ground_slam_mode,
    set_ground_slam_mode,
    vehicle_options=(),
    get_vehicle_control=None,
    set_vehicle_control=None,
    get_omni_movement=None,
    set_omni_movement=None,
    omni_movement_caption=None,
    get_hybrid_ads=None,
    set_hybrid_ads=None,
    debug_actions=None,
    debug_status=None,
    camera_features=None,
) -> None:
    if _get_menu_state() is not None:
        _menu_close()
        return
    pc = get_pc()
    if pc is None:
        raise RuntimeError("Local player controller unavailable; open the menu after loading")
    if pc.bShowMouseCursor:
        raise RuntimeError("Close the current game/SDK menu first")
    state = dict(
        pc=pc,
        pawn=getattr(pc, "OakCharacter", None),
        closed=False,
        cursor=pc.bShowMouseCursor,
        cursor_shape=pc.CurrentMouseCursor,
        sliders=[],
        labels=[],
        steps=[],
        steps_down=[],
        ranges=[],
        values=[],
        last_write=[0, 0, 0],
        tabs=[],
        tabs_down=[False, False],
        close_down=False,
        dynamic_motion_down=False,
        dirty=False,
    )
    _set_menu_state(state)
    state["close_callback"] = _menu_close
    setattr(builtins, _MENU_STATE_SLOT, state)
    try:
        library = sdk.find_class("WidgetBlueprintLibrary").ClassDefaultObject
        state["library"] = library
        viewport = next(
            (
                obj
                for obj in sdk.find_all(sdk.find_class("GameViewportSubsystem"))
                if not str(obj.Name).startswith("Default__")
            ),
            None,
        )
        if viewport is None:
            raise RuntimeError("Game viewport unavailable")
        root = _menu_widget("UserWidget", pc)
        state["root"] = root
        tree = _menu_widget("WidgetTree", root)
        root.WidgetTree = tree
        from .menu_console import build

        slot = build(
            root,
            tree,
            state,
            (camera_offset_x, camera_offset_y, camera_offset_z),
            _get_dynamic_motion_enabled(),
            motion_parameters,
            save_motion,
            reset_motion,
            get_sniper_mode,
            set_sniper_mode,
            get_ffyl_mode,
            set_ffyl_mode,
            get_ground_slam_mode,
            set_ground_slam_mode,
            vehicle_options=vehicle_options,
            get_vehicle_control=get_vehicle_control,
            set_vehicle_control=set_vehicle_control,
            get_omni_movement=get_omni_movement,
            set_omni_movement=set_omni_movement,
            omni_movement_caption=omni_movement_caption,
            get_hybrid_ads=get_hybrid_ads,
            set_hybrid_ads=set_hybrid_ads,
            debug_actions=debug_actions,
            debug_status=debug_status,
            camera_features=camera_features,
        )
        if not viewport.AddWidget(root, slot):
            raise RuntimeError("Viewport rejected menu")
        if not _menu_hook_install(_menu_poll):
            if not _menu_camera_update_ready():
                raise RuntimeError("Menu hook and camera update dispatcher unavailable")
            state["poll_via_camera_update"] = True
            logging.info("[BL4ThirdPersonPOC] MENU_UPDATE_ROUTE camera_update")
        else:
            state["poll_via_camera_update"] = False
            logging.info("[BL4ThirdPersonPOC] MENU_UPDATE_ROUTE dedicated_hook")
        pc.bShowMouseCursor = True
        pc.CurrentMouseCursor = sdk.find_enum("EMouseCursor").Default
        library.SetInputMode_UIOnlyEx(
            pc, state["close"], sdk.find_enum("EMouseLockMode").DoNotLock, True
        )
        logging.info(
            "[BL4ThirdPersonPOC] MENU_OPEN pages=camera,camera_modes,camera_motion,vehicle,ads_zoom,debug view=camera_console"
        )
    except Exception:
        _menu_close("open_failed")
        raise


# Interactive item-card A/B diagnostics; state remains owned by the loader.
def _item_card_auto_peer_ab_next_impl(state: Any) -> None:
    """Reset or report the production-like automatic peer A/B test."""
    if not isinstance(state, dict) or not state.get("ready"):
        logging.error(
            "[BL4ThirdPersonPOC] AUTO_PEER_AB unavailable; "
            "item-card fusion is not ready"
        )
        return
    if not state.get("active"):
        logging.error(
            "[BL4ThirdPersonPOC] AUTO_PEER_AB unavailable; "
            "enter TPS gameplay before advancing the test"
        )
        return

    final_hook = state.get("final_hook")
    if not isinstance(final_hook, dict):
        logging.error(
            "[BL4ThirdPersonPOC] AUTO_PEER_AB unavailable; "
            "final item-card hook is missing"
        )
        return

    if not state["auto_peer_test_active"]:
        state["native_max_world"].clear()
        state["native_peer_center"].clear()
        state["peer_max_world"].clear()
        state["peer_source_actor"].clear()
        state["peer_source_separation"].clear()
        state["gate2_last_seen_update"].clear()
        state["fallback_samples"] = 0
        state["fallback_accepts"] = 0
        state["fallback_unlearned"] = 0
        state["fallback_farther"] = 0
        state["peer_bootstrap_accepts"] = 0
        state["peer_inward_accepts"] = 0
        state["peer_bootstrap_no_witness"] = 0
        state["peer_bootstrap_farther"] = 0
        state["peer_limit_updates"] = 0
        state["selection_events"].clear()
        state["selection_events_dropped"] = 0
        state["pending_actor"] = None
        state["pending_samples"] = 0
        state["last_selection_source"] = None
        final_hook["control"].selected_actor = 0
        state["auto_peer_test_active"] = True
        logging.warning(
            "[BL4ThirdPersonPOC] AUTO_PEER_AB RESET ACTIVE; "
            "all pickup distance calibrations cleared"
        )
        logging.info(
            "[BL4ThirdPersonPOC] Seed exactly one native full card near "
            "its far boundary, then test the other pickups close, medium, "
            "far, and inward before executing item_card_auto_peer_ab_next() again"
        )
        return

    logging.info(
        "[BL4ThirdPersonPOC] AUTO_PEER_AB_REPORT "
        f"fallback_samples={state['fallback_samples']}, "
        f"fallback_accepts={state['fallback_accepts']}, "
        f"fallback_unlearned={state['fallback_unlearned']}, "
        f"fallback_farther={state['fallback_farther']}, "
        f"peer_bootstrap_accepts={state['peer_bootstrap_accepts']}, "
        f"peer_inward_accepts={state['peer_inward_accepts']}, "
        f"peer_no_witness={state['peer_bootstrap_no_witness']}, "
        f"peer_farther={state['peer_bootstrap_farther']}, "
        f"peer_limit_updates={state['peer_limit_updates']}, "
        f"geometry_errors={state['geometry_errors']}, "
        f"update_errors={state['update_errors']}"
    )
    for index, (address, distance) in enumerate(
        sorted(state["native_max_world"].items())
    ):
        logging.info(
            "[BL4ThirdPersonPOC] "
            f"auto_native[{index}] actor=0x{address:016X}, "
            f"native_max_world={float(distance):.3f}, "
            f"path={state['pickups'].get(address, '<unknown>')}"
        )
    for index, (address, distance) in enumerate(
        sorted(state["peer_max_world"].items())
    ):
        peer = state["peer_source_actor"].get(address, 0)
        separation = state["peer_source_separation"].get(address)
        separation_text = (
            f"{float(separation):.3f}" if separation is not None else "<none>"
        )
        logging.info(
            "[BL4ThirdPersonPOC] "
            f"auto_peer[{index}] actor=0x{address:016X}, "
            f"peer=0x{int(peer):016X}, "
            f"peer_max_world={float(distance):.3f}, "
            f"peer_separation={separation_text}, "
            f"path={state['pickups'].get(address, '<unknown>')}"
        )
    state["auto_peer_test_active"] = False
    logging.warning(
        "[BL4ThirdPersonPOC] AUTO_PEER_AB COMPLETE; automatic policy " "remains active"
    )


def _item_card_forced_peer_ab_next_impl(
    state: Any,
    *,
    _get_runtime,
    _item_card_select,
    _item_card_active_gate2_actors,
) -> None:
    """Advance the locked-peer forced-unlearned A/B test."""
    if not isinstance(state, dict) or not state.get("ready"):
        logging.error(
            "[BL4ThirdPersonPOC] FORCED_PEER_AB unavailable; "
            "item-card fusion is not ready"
        )
        return
    if not state.get("active"):
        logging.error(
            "[BL4ThirdPersonPOC] FORCED_PEER_AB unavailable; "
            "enter TPS gameplay before advancing the test"
        )
        return

    final_hook = state.get("final_hook")
    if not isinstance(final_hook, dict):
        logging.error(
            "[BL4ThirdPersonPOC] FORCED_PEER_AB unavailable; "
            "final item-card hook is missing"
        )
        return

    control = final_hook["control"]
    control.selected_actor = 0
    state["pending_actor"] = None
    state["pending_samples"] = 0
    state["last_selection_source"] = None

    if not state["near_ab_override"]:
        pc, pawn, camera_manager = _get_runtime()
        if pc is None or pawn is None or camera_manager is None:
            logging.error(
                "[BL4ThirdPersonPOC] FORCED_PEER_AB unavailable; "
                "player runtime is not ready"
            )
            return

        native_before = dict(state["native_max_world"])
        peer_before = dict(state["peer_max_world"])
        state["near_ab_override"] = True
        try:
            _actor, _object, geometry, raw_count, _eligible_count = _item_card_select(
                state, pc, pawn, camera_manager
            )
        finally:
            state["near_ab_override"] = False
            state["native_max_world"] = native_before
            state["peer_max_world"] = peer_before
        if geometry is None:
            logging.error(
                "[BL4ThirdPersonPOC] FORCED_PEER_AB arm failed; "
                "the TPS crosshair is not inside a pickup OBB"
            )
            return

        observed_actor = int(geometry["address"])
        captured = dict(state["forced_peer_capture"])
        if not captured:
            active = _item_card_active_gate2_actors(state)
            if observed_actor not in active:
                logging.error(
                    "[BL4ThirdPersonPOC] FORCED_PEER_AB capture failed; "
                    "hold a full native card at medium distance before "
                    "executing item_card_forced_peer_ab_next()"
                )
                return
            native_distance = native_before.get(observed_actor)
            if native_distance is None:
                native_distance = float(geometry["world_distance"])
            state["forced_peer_capture"] = {observed_actor: float(native_distance)}
            logging.warning(
                "[BL4ThirdPersonPOC] FORCED_PEER_AB PEER CAPTURED; "
                f"actor=0x{observed_actor:016X}, "
                f"native_max_world={float(native_distance):.3f}, "
                f"path={state['pickups'].get(observed_actor, '<unknown>')}"
            )
            logging.info(
                "[BL4ThirdPersonPOC] Move directly in front of the chest, "
                "aim a different weapon that only shows its compact icon, "
                "then execute item_card_forced_peer_ab_next() again to arm the override"
            )
            return

        forced_actor = observed_actor
        if forced_actor in captured:
            logging.error(
                "[BL4ThirdPersonPOC] FORCED_PEER_AB arm failed; "
                "the marked target is the captured peer; aim a different "
                "weapon and execute item_card_forced_peer_ab_next() again"
            )
            return
        witnesses = captured

        state["near_ab_control_end"] = {
            "selector_samples": int(state["selector_samples"]),
            "selection_updates": int(state["selection_updates"]),
        }
        state["forced_native_saved"] = native_before.get(forced_actor)
        state["native_max_world"].pop(forced_actor, None)
        state["peer_max_world"].pop(forced_actor, None)
        state["forced_unlearned_actor"] = forced_actor
        state["forced_peer_witnesses"] = dict(witnesses)
        state["near_ab_override"] = True
        state["fallback_samples"] = 0
        state["fallback_accepts"] = 0
        state["fallback_unlearned"] = 0
        state["fallback_farther"] = 0
        state["peer_bootstrap_accepts"] = 0
        state["peer_inward_accepts"] = 0
        state["peer_bootstrap_no_witness"] = 0
        state["peer_bootstrap_farther"] = 0
        state["forced_native_ignored"] = 0
        logging.warning(
            "[BL4ThirdPersonPOC] FORCED_PEER_AB OVERRIDE ACTIVE; "
            f"forced_actor=0x{forced_actor:016X}, raw_count={raw_count}, "
            f"world={float(geometry['world_distance']):.3f}, "
            f"path={state['pickups'].get(forced_actor, '<unknown>')}"
        )
        for index, (address, distance) in enumerate(sorted(witnesses.items())):
            logging.info(
                "[BL4ThirdPersonPOC] "
                f"forced_peer_witness[{index}] actor=0x{address:016X}, "
                f"native_max_world={float(distance):.3f}, "
                f"path={state['pickups'].get(address, '<unknown>')}"
            )
        return

    forced_actor = int(state["forced_unlearned_actor"])
    state["near_ab_override"] = False
    logging.info(
        "[BL4ThirdPersonPOC] FORCED_PEER_AB_REPORT "
        f"forced_actor=0x{forced_actor:016X}, "
        f"fallback_samples={state['fallback_samples']}, "
        f"fallback_accepts={state['fallback_accepts']}, "
        f"fallback_unlearned={state['fallback_unlearned']}, "
        f"fallback_farther={state['fallback_farther']}, "
        f"peer_bootstrap_accepts={state['peer_bootstrap_accepts']}, "
        f"peer_inward_accepts={state['peer_inward_accepts']}, "
        f"peer_no_witness={state['peer_bootstrap_no_witness']}, "
        f"peer_farther={state['peer_bootstrap_farther']}, "
        f"forced_native_ignored={state['forced_native_ignored']}, "
        f"geometry_errors={state['geometry_errors']}, "
        f"update_errors={state['update_errors']}"
    )
    for index, (address, distance) in enumerate(
        sorted(state["native_max_world"].items())
    ):
        logging.info(
            "[BL4ThirdPersonPOC] "
            f"near_ab_final[{index}] actor=0x{address:016X}, "
            f"native_max_world={float(distance):.3f}, "
            f"path={state['pickups'].get(address, '<unknown>')}"
        )
    for index, (address, distance) in enumerate(
        sorted(state["peer_max_world"].items())
    ):
        logging.info(
            "[BL4ThirdPersonPOC] "
            f"peer_ab_final[{index}] actor=0x{address:016X}, "
            f"peer_max_world={float(distance):.3f}, "
            f"path={state['pickups'].get(address, '<unknown>')}"
        )
    logging.warning(
        "[BL4ThirdPersonPOC] FORCED_PEER_AB COMPLETE; "
        "normal selection policy restored"
    )
    state["peer_max_world"].pop(forced_actor, None)
    saved_native = state.get("forced_native_saved")
    if forced_actor and saved_native is not None:
        state["native_max_world"][forced_actor] = float(saved_native)
    state["forced_unlearned_actor"] = 0
    state["forced_native_saved"] = None
    state["forced_peer_capture"].clear()
    state["forced_peer_witnesses"].clear()


# Manual camera mode diagnostic.
def query_actor_camera_mode(*, _get_runtime, _apply_camera_offset) -> None:
    _pc, pawn, camera_manager = _get_runtime()

    if pawn is None or camera_manager is None:
        logging.warning(
            "[BL4ThirdPersonPOC] Camera-mode set test: "
            "pawn or camera manager unavailable"
        )
        return

    try:
        before = camera_manager.GetActorCameraMode(pawn)
    except Exception as exc:
        before = f"<read failed: " f"{type(exc).__name__}: {exc}>"

    logging.info("[BL4ThirdPersonPOC] " "===== SET ACTOR CAMERA MODE TEST =====")
    logging.info("[BL4ThirdPersonPOC] " f"mode_before={before!r}")

    try:
        camera_manager.SetActorCameraMode(
            pawn,
            "ThirdPerson",
            "",
            0.0,
            False,
            False,
        )

        logging.info("[BL4ThirdPersonPOC] " "SetActorCameraMode call succeeded")

    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] "
            "SetActorCameraMode call failed: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    _apply_camera_offset()

    try:
        after = camera_manager.GetActorCameraMode(pawn)
    except Exception as exc:
        after = f"<read failed: " f"{type(exc).__name__}: {exc}>"

    logging.info("[BL4ThirdPersonPOC] " f"mode_after={after!r}")
    logging.info("[BL4ThirdPersonPOC] " "===== END SET ACTOR CAMERA MODE TEST =====")


# Dynamic Camera Motion setting persistence and menu toggle; live state stays in loader.
def _read_dynamic_motion_choice(path: Any) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    if type(data) is not dict or type(data.get("enabled")) is not bool:
        raise ValueError("Invalid Dynamic Camera Motion settings content")
    return data["enabled"]


def _load_dynamic_motion_choice_impl(*, owner_module) -> bool:
    """Read current external settings; fresh installs use the SDK option default."""
    fallback = owner_module.dynamic_motion_camera_enabled.value is True
    try:
        return _read_dynamic_motion_choice(owner_module._DYNAMIC_MOTION_CHOICE_FILE)
    except FileNotFoundError:
        return fallback
    except (OSError, ValueError, TypeError) as exc:
        logging.error(f"[BL4ThirdPersonPOC] DYNAMIC_MOTION_SETTINGS_READ_FAILED {exc}")
        return fallback


def _save_dynamic_motion_choice_impl(value: bool, *, owner_module) -> None:
    owner_module._DYNAMIC_MOTION_CHOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
    staged = owner_module._DYNAMIC_MOTION_CHOICE_FILE.with_suffix(".json.tmp")
    try:
        staged.write_text(
            json.dumps(
                {
                    "version": 2,
                    "enabled": bool(value),
                    "parameters": dict(
                        getattr(owner_module, "_dynamic_motion_parameters", {})
                    ),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        staged.replace(owner_module._DYNAMIC_MOTION_CHOICE_FILE)
    finally:
        if staged.exists():
            staged.unlink()


def _set_dynamic_motion_enabled_impl(value: bool, *, owner_module) -> None:
    owner_module._dynamic_motion_enabled = bool(value)
    owner_module.dynamic_motion_camera_enabled.value = (
        owner_module._dynamic_motion_enabled
    )
    owner_module._dynamic_motion_reset()
    if not owner_module._dynamic_motion_enabled:
        owner_module._apply_camera_offset()
    owner_module._save_dynamic_motion_choice(owner_module._dynamic_motion_enabled)
    try:
        owner_module.mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] DYNAMIC_MOTION_SDK_SAVE_FAILED {exc}")
    logging.info(
        f"[BL4ThirdPersonPOC] DYNAMIC_MOTION_CAMERA enabled={owner_module._dynamic_motion_enabled}"
    )
