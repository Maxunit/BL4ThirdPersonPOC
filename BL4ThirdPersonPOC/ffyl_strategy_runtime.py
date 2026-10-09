"""Shared runtime routing for an explicitly selected simplified FFYL controller.

Mod enable publishes an inert controller; settled local TPS starts each binding.
A process registry retains ownership across module reexecution. Once selected, a
failed controller remains selected until explicit verified shutdown; legacy must
not silently take over. No SDK work occurs at import time.
"""

import sys
from types import ModuleType

REGISTRY_KEY = "_bl4tps_ffyl_strategy_owner"
TAG = "[BL4ThirdPersonPOC.FFYLStrategy]"


def controller(mod):
    """Find a retained owner even when a reimported mod lost its local reference."""
    attached = getattr(mod, "_ffyl_strategy_controller", None)
    registry = sys.modules.get(REGISTRY_KEY)
    retained = getattr(registry, "controller", None) if registry is not None else None
    if attached is not None and retained is not None and attached is not retained:
        raise RuntimeError("Conflicting local and retained FFYL controllers")
    return attached if attached is not None else retained


def setup(mod):
    """Publish an unstarted production controller after verified prior cleanup.

    Registry publication precedes frame-hook registration in mod enable. Reload
    failures keep the previous object reachable and abort enable. Construction
    does not access gameplay, add hooks, stop recoil, or require a loaded save.
    """
    try:
        previous = controller(mod)
        if previous is not None and previous.shutdown("selection_reload") is not True:
            raise RuntimeError("Retained FFYL cleanup incomplete")
        from unrealsdk import find_object
        from unrealsdk.unreal import WeakPointer
        from unrealsdk import hooks
        from . import ffyl_legacy_camera, ground_slam_camera
        from .ffyl_strategy_selection import make_controller

        selected = make_controller(
            mod,
            weak_pointer=WeakPointer,
            hooks=hooks,
            find_object=find_object,
            stop_legacy=lambda reason: ffyl_legacy_camera.shutdown(reason),
            stop_ground_slam=lambda reason: ground_slam_camera.release_for_ffyl(
                mod, reason
            ),
        )
        registry = ModuleType(REGISTRY_KEY)
        registry.controller = selected
        mod._ffyl_strategy_controller = selected
        sys.modules[REGISTRY_KEY] = registry
        mod.logging.info(
            f"{TAG} SELECTED strategy=simple_owned_tps state=waiting_for_settled_tps"
        )
        return True
    except Exception as exc:
        mod._ffyl_beta_fault = True
        mod.logging.error(f"{TAG} SELECTION_FAILED {type(exc).__name__}: {exc}")
        return False


def report_fault(mod, selected):
    """Report once per retained controller, not once per camera callback."""
    if getattr(selected, "faulted", False) is not True:
        return
    mod._ffyl_beta_fault = True
    if getattr(selected, "_fault_reported", False) is True:
        return
    selected._fault_reported = True
    details = list(getattr(selected, "failures", ()))
    binding = getattr(selected, "binding", None)
    if binding is not None:
        details.extend(binding.failures)
        details.extend(binding.cleanup_errors)
    mod.logging.error(f"{TAG} FAULT state=retained details={details[-8:]}")


def controls_transition(mod):
    selected = controller(mod)
    return selected is not None and selected.controls_transition


def handles_down_state(mod):
    """The selected PRE binding owns entry; do not set legacy resume flags."""
    selected = controller(mod)
    return (
        selected is not None
        and selected.binding is not None
        and selected.binding.active
    )


def update(mod):
    selected = controller(mod)
    if selected is None:
        from . import ffyl_legacy_camera

        ffyl_legacy_camera.update(mod)
        return
    if not mod._third_person_enabled or mod.tps_ffyl_beta.value is not True:
        if selected.shutdown("feature_or_tps_disabled") is not True:
            mod._ffyl_beta_fault = True
        return
    if getattr(selected, "_mod", mod) is not mod:
        mod._ffyl_beta_fault = True
        return  # A reimport must run setup before using the previous mod's binding.
    selected.retire_if_complete()
    if selected.start_if_ready() is True:
        mod.logging.info(
            f"{TAG} ARMED strategy=simple_owned_tps down_state=local_controller"
        )
    report_fault(mod, selected)


def shutdown(mod, reason):
    """Release the selected owner before shared camera/native teardown."""
    try:
        selected = controller(mod)
    except RuntimeError as exc:
        mod.logging.error(f"{TAG} CLEANUP_REFUSED {exc}")
        return False
    if selected is not None:
        return selected.shutdown(reason) is True
    from . import ffyl_legacy_camera

    return ffyl_legacy_camera.shutdown(reason) is True


def compensate_entry_offset(mod, values):
    selected = controller(mod)
    binding = getattr(selected, 'binding', None)
    if binding is None or not binding.active or binding.exit_seen:
        return values
    return binding.owner.compensate_entry_offset(values)


def ads_blocked(mod, pawn, manager):
    """Semantic FFYL state, authorized by the live selected camera owner."""
    selected=controller(mod)
    binding=getattr(selected,'binding',None)
    if binding is None or not binding.active or not binding.seen_ffyl or binding.exit_seen:
        return False
    try:
        _,bound_pawn,bound_manager=binding.owner.current_runtime()
        return (pawn is not None and manager is not None
                and int(pawn._get_address())==int(bound_pawn._get_address())
                and int(manager._get_address())==int(bound_manager._get_address()))
    except Exception:
        # A known active down-state with unverifiable ownership must not enter ADS.
        return True
