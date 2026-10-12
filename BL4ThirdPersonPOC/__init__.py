"""Register the BL4 mod and bind subsystem functions to one mutable owner.

The loader owns options, callback identities, SDK registration and shared state.
Thin wrappers supply this module explicitly; core modules must not import it at
module scope. Keep initialization order: build_mod can invoke enable immediately.
Builtins registries retain native allocations and camera bookkeeping across reload.
Only primitive identities or serial-checked references authorize later access.
Published native code remains pinned until process exit even after restoration.
Native lifetime and handoff contracts are described in docs/NATIVE_LIFECYCLE.md.
"""

from __future__ import annotations

# Available before build_mod invokes the automatic enable callback.
MOD_VERSION = "0.3.9.41"
HYBRID_ADS_AVAILABLE = True  # optional Hybrid diagnostics QA

import builtins
import ctypes
import struct
import sys
from ctypes import wintypes
from typing import Any

from mods_base import (
    BoolOption,
    EInputEvent,
    Game,
    KeybindOption,
    SliderOption,
    SETTINGS_DIR,
    build_mod,
    command,
    get_pc,
    keybind,
)
import unrealsdk as sdk
from unrealsdk import find_all, find_object, logging, make_struct
from unrealsdk.hooks import Block, Type, add_hook, has_hook, remove_hook

import math
import time
import json
from pathlib import Path

assert (
    Game.get_current() == Game.BL4
), "BL4 Third Person PoC only supports Borderlands 4"


BLUEPRINT_UPDATE_CAMERA_FUNCTION = (
    "/Script/Engine.PlayerCameraManager:" "BlueprintUpdateCamera"
)

BLUEPRINT_CAMERA_PROBE_IDENTIFIER = "bl4_third_person_poc.blueprint_camera_probe"

_blueprint_camera_probe_installed = False
_blueprint_camera_probe_calls = 0
_blueprint_camera_probe_last_slide: bool | None = None

THIRD_PERSON_ANIM_HOOK = (
    "/Game/PlayerCharacters/_Shared/Animation/"
    "BPAnim_Player_3rd.BPAnim_Player_3rd_C:"
    "BlueprintThreadSafeUpdateAnimation"
)

FIRST_PERSON_ANIM_HOOK = (
    "/Game/PlayerCharacters/_Shared/Animation/"
    "BPAnim_Player_1st.BPAnim_Player_1st_C:"
    "BlueprintUpdateAnimation"
)

CAMERA_MODE_FUNCTION = "/Script/Engine.PlayerController:" "ClientSetCameraMode"

CAMERA_MODE_PROBE_IDENTIFIER = "bl4_third_person_poc.camera_mode_probe"

_camera_mode_probe_installed = False

HOOK_IDENTIFIER = "bl4_third_person_poc.camera_update"

PUSH_ACTOR_CAMERA_MODE_FUNCTION = (
    "/Script/OakGame.OakPlayerCameraManager:" "PushActorCameraMode"
)

POP_ACTOR_CAMERA_MODE_FUNCTION = (
    "/Script/OakGame.OakPlayerCameraManager:" "PopActorCameraMode"
)

CAMERA_STACK_PROBE_IDENTIFIER = "bl4_third_person_poc.camera_stack_probe"

_camera_stack_probes_installed: list[str] = []

_third_person_enabled = False
_third_person_pushed = False
_ads_active = False
_hooks_installed: list[str] = []

CAMERA_STACK_PERSIST_NAME = "_bl4_tps_camera_stack_owner_v1"
NATIVE_PATCH_QUARANTINE_NAME = "_bl4_tps_native_patch_quarantine_v1"
ACTIVE_NATIVE_STATE_NAME = "_bl4_tps_active_native_state_v1"
RETIRED_NATIVE_STUBS_NAME = "_bl4_tps_retired_native_stubs_v1"
MAX_RETIRED_ITEM_CARD_STUBS = 4096

_camera_stack_owner: dict[str, Any] = {
    "owned": False,
    "pending_pop": False,
    "pawn_address": 0,
    "manager_address": 0,
    "reason": "",
    "pushes": 0,
    "pops": 0,
    "deferred_pops": 0,
    "retry_attempts": 0,
    "retry_successes": 0,
    "retirements": 0,
    "last_retire_reason": "",
}
_persisted_camera_stack_owner = getattr(
    builtins,
    CAMERA_STACK_PERSIST_NAME,
    None,
)
if isinstance(_persisted_camera_stack_owner, dict):
    for _key in tuple(_camera_stack_owner):
        if _key in _persisted_camera_stack_owner:
            _camera_stack_owner[_key] = _persisted_camera_stack_owner[_key]
    _third_person_pushed = bool(_camera_stack_owner.get("owned"))

_native_patch_quarantine = getattr(
    builtins,
    NATIVE_PATCH_QUARANTINE_NAME,
    None,
)
if not isinstance(_native_patch_quarantine, list):
    _native_patch_quarantine: list[dict[str, Any]] = []
    setattr(
        builtins,
        NATIVE_PATCH_QUARANTINE_NAME,
        _native_patch_quarantine,
    )

# RLM can reexecute this module before its previous on_disable callback runs.
# Keep the buffers and original bytes reachable until the native sites have
# actually been restored. A module global alone cannot own a live patch.
_active_native_state = getattr(builtins, ACTIVE_NATIVE_STATE_NAME, None)
if not isinstance(_active_native_state, dict):
    _active_native_state = {}
    setattr(builtins, ACTIVE_NATIVE_STATE_NAME, _active_native_state)

# Removing a jump does not prove that a native thread which entered its stub
# has returned. Keep executable pages and the ctypes buffers they reference
# alive until process exit; never recycle them by elapsed time.
_retired_native_stubs = getattr(builtins, RETIRED_NATIVE_STUBS_NAME, None)
if not isinstance(_retired_native_stubs, list):
    _retired_native_stubs = []
    setattr(builtins, RETIRED_NATIVE_STUBS_NAME, _retired_native_stubs)

_last_anim_slide_states: dict[str, bool] = {}
_camera_hotpath_debug: dict[str, Any] = {}
_slide_perf_probe: dict[str, Any] = {"armed": False}
_perf_probe: dict[str, Any] = {"armed": False}
PERF_MAX_UPDATES = 6000
PERF_MAX_SECONDS = 90.0
PERF_TOP_SAMPLES = 24


def _perf_record_top(top: list[Any], sample: tuple[Any, ...]) -> None:
    """Keep only the largest bounded samples; never print in the camera hook."""
    if len(top) < PERF_TOP_SAMPLES:
        top.append(sample)
    else:
        smallest = min(range(len(top)), key=lambda index: top[index][0])
        if sample[0] > top[smallest][0]:
            top[smallest] = sample


def _perf_record_metric(name: str, ns: int) -> None:
    probe = _perf_probe
    if not probe["armed"]:
        return
    row = probe["metrics"].setdefault(name, [0, 0, 0])
    row[0] += 1
    row[1] += ns
    row[2] = max(row[2], ns)


from .ui_and_commands import _emit_perf_report, _emit_slide_perf_report


@command(
    "bl4tps_perf", description="Capture bounded mod stage and update-interval timings"
)
def perf_probe_toggle(_args: Any) -> None:
    """Start/stop a read-only, bounded in-memory performance report."""
    global _perf_probe
    probe = _perf_probe
    if not probe["armed"] and not probe.get("complete"):
        if not _hooks_installed:
            logging.error("[BL4ThirdPersonPOC] PERF_REFUSED camera hook unavailable")
            return
        if _native_fault:
            logging.error("[BL4ThirdPersonPOC] PERF_REFUSED native fault; restart BL4")
            return
        _perf_probe = {
            "armed": True,
            "complete": False,
            "started_ns": time.perf_counter_ns(),
            "last_hook_ns": 0,
            "frames": 0,
            "metrics": {},
            "slow_work": [],
            "slow_interval": [],
            "slow_item": [],
            "buckets": {},
            "item_scan": None,
            "item_frame": None,
            "auto_start": bool(_native_auto_enabled),
        }
        logging.warning(
            "[BL4ThirdPersonPOC] PERF_ARMED command=bl4tps_perf "
            f"cap_updates={PERF_MAX_UPDATES} cap_seconds={PERF_MAX_SECONDS:.0f} "
            "scope=mod_camera_hook,hook_interval,item_card_parts; "
            "repeat command to stop and print report"
        )
        return
    probe["armed"] = False
    probe["complete"] = False
    _emit_perf_report(probe, _native_auto_enabled, _native_fault)
    from .pickup_registry import emit_summary

    emit_summary(sys.modules[__name__])
    _perf_probe = {"armed": False}


@command(
    "bl4tps_slide_perf", description="Capture one bounded Slide hotpath timing window"
)
def slide_perf_probe_toggle(_args: Any) -> None:
    """Measure camera stages in memory; print only after the test window."""
    global _slide_perf_probe
    if not _slide_perf_probe["armed"]:
        if _native_fault:
            logging.error(
                "[BL4ThirdPersonPOC] SLIDE_PERF_REFUSED native fault; restart game"
            )
            return
        _slide_perf_probe = {
            "armed": True,
            "started_ns": time.perf_counter_ns(),
            "frame": 0,
            "stages": {},
            "top": [],
            "slide_seen": False,
            "auto_at_start": _native_auto_enabled,
        }
        logging.warning(
            "[BL4ThirdPersonPOC] SLIDE_PERF_ARMED "
            f"auto={_native_auto_enabled} cap=32 "
            "tracked=native_ownership,slide,camera_offset,item_card"
        )
        return
    probe = _slide_perf_probe
    probe["armed"] = False
    _emit_slide_perf_report(probe, _native_auto_enabled, _native_fault)


_slide_active = False
_slide_camera_recovery_pending = False
_slide_camera_recovery_pawn = 0
_camera_offset_gate_last = ""

_last_slide_camera_force_time = 0.0

SLIDE_CAMERA_FORCE_COOLDOWN = 0.05

_slide_offset_samples_remaining = 0

_ladder_active = False
_ladder_pending_third_person_enabled: bool | None = None
_ladder_entry_requested = False
_ladder_native_reassertion_logged = False

_vehicle_camera_active = False

# Reconcile camera ownership after FFYL and a local
# ClientRestart are the two proven native paths which can replace the real
# actor camera mode while our bookkeeping still says ThirdPerson is pushed.
CLIENT_RESTART_FUNCTION = "/Script/Engine.PlayerController:ClientRestart"
CLIENT_RESTART_IDENTIFIER = "bl4_third_person_poc.camera_lifecycle.client_restart_post"
CLIENT_RESTART_PRE_IDENTIFIER = (
    "bl4_third_person_poc.camera_lifecycle.vehicle_restart_pre"
)
FFYL_DOWNED_FUNCTION = "/Script/OakGame.OakUIDataCollector_DownState:OnDowned"
FFYL_NATIVE_PRE_IDENTIFIER = "bl4_third_person_poc.ffyl_native_pre"
_ffyl_native_pre_installed = False
CAMERA_LIFECYCLE_SETTLE_SECONDS = 0.120
CAMERA_LIFECYCLE_ARRIVAL_GAP_SECONDS = 0.750

_camera_lifecycle_hook_installed = False
_camera_lifecycle: dict[str, Any] = {}
_ffyl_early_handoff_armed = False
_ffyl_early_handoff_hook_installed = False
_ffyl_native_resume_pending = False
_ffyl_early_auto_enabled = True
FFYL_EARLY_ENDED_FUNCTION = "/Script/OakGame.OakUIDataCollector_DownState:OnDownedEnded"
FFYL_EARLY_ENDED_IDENTIFIER = "bl4_third_person_poc.ffyl_early_handoff_ended"

ADS_CAMERA_TRANSITION_TIME = 0.06

ADS_ZOOM_CHANGE_FUNCTION = "/Script/OakGame.OakUIDataCollector_Weapon:OnZoomInChange"
ADS_ZOOMED_OUT_FUNCTION = "/Script/OakGame.OakUIDataCollector_Weapon:OnZoomedOut"
ADS_ZOOM_CHANGE_IDENTIFIER = "bl4_third_person_poc.hybrid_ads_zoom_change"
ADS_ZOOMED_OUT_IDENTIFIER = "bl4_third_person_poc.hybrid_ads_zoomed_out"
ADS_WEAPON_EQUIPPED_FUNCTION = (
    "/Script/OakGame.OakUIDataCollector_Weapon:OnWeaponEquipped"
)
ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER = (
    "bl4_third_person_poc.hybrid_ads_weapon_equipped_pre"
)
ADS_WEAPON_EQUIPPED_POST_IDENTIFIER = (
    "bl4_third_person_poc.hybrid_ads_weapon_equipped_post"
)
ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION = "/Script/OakGame.OakCharacter:WeaponEquipped"
ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER = (
    "bl4_third_person_poc.hybrid_ads_character_weapon_equipped_pre"
)
ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER = (
    "bl4_third_person_poc.hybrid_ads_character_weapon_equipped_post"
)
ADS_POSE_PROBE_MAX_EVENTS = 240
ADS_POSE_PROBE_MAX_HOOKS = 64

from .ui_and_commands import (
    COLLECTOR_SURFACE_OUTBOUND_TOKENS,
    COLLECTOR_SURFACE_UI_TOKENS,
    COLLECTOR_SURFACE_MAX_FUNCTIONS,
    COLLECTOR_SURFACE_MAX_CLASSES,
    UI_PUBLISH_TOPOLOGY_OWNERS,
    UI_PUBLISH_TOPOLOGY_FUNCTIONS,
)

# Phase 2 diagnostic observer. It is dispatched at the beginning of the four
# existing production callbacks because Oak2 does not permit a second hook at
# the same UFunction/type site. perf_counter() only timestamps event ordering;
# elapsed time never drives a gameplay decision.
from .camera_math import (
    ADS_OPTICAL_ZOOM_RESPONSE,
    ADS_MIN_SAFE_FOV,
    ADS_MAX_SAFE_FOV,
)

ADS_MIN_DURATION = 0.01
ADS_MAX_DURATION = 2.0
from .camera_math import (
    ADS_TYPE_PATHS,
    ADS_TYPE_SUFFIXES,
)

_ads_route = "hip"
_ads_tps_state: dict[str, Any] | None = None
_ads_collector_address = 0
_ads_hooks_installed: list[tuple[str, Any, str]] = []
_ads_debug: dict[str, Any] = {}
_ads_handoff: dict[str, Any] = {}
_ads_press_intent: dict[str, Any] = {}

SERVER_USE_OBJECT_FUNCTION = "/Script/OakGame.OakPlayerController:ServerUseObject"
LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION = (
    "/Script/OakGame.OakPlayerController:ServerUseJunkObject"
)
CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION = (
    "/Script/OakGame.StructuredInteractableUserState:" "ClientSetCurrentInteractable"
)
INTERACTION_REDIRECT_IDENTIFIER = "bl4_third_person_poc.interaction_redirect"
SHOP_CAMERA_HOOK_IDENTIFIER = "bl4_third_person_poc.shop_camera_state"
LEGACY_FLOOR_PICKUP_HOOK_IDENTIFIER = "bl4_third_person_poc.floor_pickup_state"
FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER = "bl4_third_person_poc.floor_pickup_priority"
INTERACTION_TRACE_DISTANCE = 5000.0
INTERACTION_MAX_USE_DISTANCE = 600.0
INTERACTION_REDIRECT_WINDOW = 0.10
INTERACTION_FALLBACK_DELAY = 0.05
# A floor-item fallback may run only after the E key is released and native
# use handlers have had an opportunity to consume the press/hold action.

from .native_memory import (
    INTERACTION_PROMPT_TARGET_RVA,
    INTERACTION_PROMPT_HOOK_LENGTH,
    INTERACTION_PROMPT_TARGET_PREFIX,
    INTERACTION_PROMPT_SAFETY_WINDOW_RVA,
    INTERACTION_PROMPT_SAFETY_WINDOW,
    INTERACTION_PROMPT_UPDATE_IDENTIFIER,
    INTERACTION_PROMPT_NATIVE_RAY_LENGTH,
    NPC_ELIGIBLE_BUILD,
    NPC_ELIGIBLE_RVA,
    NPC_ELIGIBLE_ORIGINAL,
    NPC_ELIGIBLE_CANDIDATE_OFFSET,
    NPC_ELIGIBLE_CONTINUATION_RVA,
    NPC_ELIGIBLE_STUB,
    FLOOR_PICKUP_TARGET_OFFSET,
    FLOOR_PICKUP_CONTEXT_OFFSET,
    FLOOR_PICKUP_ROUTER_EXPECTED_RVA,
    FLOOR_PICKUP_ROUTER_PATTERN,
    FLOOR_PICKUP_AOB_CHUNK_SIZE,
    ITEM_CARD_GATE2_TARGET_RVA,
    ITEM_CARD_GATE2_HOOK_LENGTH,
    ITEM_CARD_GATE2_TARGET_PREFIX,
    ITEM_CARD_GATE2_CONTINUATION_PREFIX,
    ITEM_CARD_GATE2_RECORD_SIZE,
    ITEM_CARD_GATE2_RING_CAPACITY,
    ITEM_CARD_GATE2_RING_MASK,
    ITEM_CARD_GATE2_BUFFER_SIZE,
    ITEM_CARD_FINAL_TARGET_RVA,
    ITEM_CARD_FINAL_HOOK_LENGTH,
    ITEM_CARD_FINAL_TARGET_PREFIX,
    ITEM_CARD_FINAL_CONTINUATION_PREFIX,
    ITEM_CARD_FINAL_RECORD_SIZE,
    ITEM_CARD_FINAL_RING_CAPACITY,
    ITEM_CARD_FINAL_RING_MASK,
    ITEM_CARD_FINAL_BUFFER_SIZE,
    ITEM_CARD_STABLE_SELECTION_SAMPLES,
    ITEM_CARD_GATE2_GRACE_UPDATES,
    ITEM_CARD_GATE2_SAFE_LAG,
    ITEM_CARD_PICKUP_REFRESH_INTERVAL,
    ITEM_CARD_GEOMETRY_STABLE_SAMPLES,
    ITEM_CARD_GEOMETRY_CENTER_EPSILON,
    ITEM_CARD_GEOMETRY_AXIS_EPSILON,
    ITEM_CARD_GEOMETRY_TRACK_TIMEOUT,
    ITEM_CARD_GEOMETRY_TRACK_BUDGET,
    ITEM_CARD_GEOMETRY_BACKGROUND_BUDGET,
    ITEM_CARD_GEOMETRY_COLLAPSE_RATIO,
    ITEM_CARD_MAX_DEBUG_EVENTS,
)

_interaction_redirect_installed = False
_shop_camera_hook_installed = False
_floor_pickup_priority_hook_installed = False
_shop_camera_active = False
_pending_interaction_target: Any = None
_pending_interaction_time = 0.0
_pending_floor_pickup_target: Any = None
_pending_floor_pickup_time = 0.0
_pending_floor_pickup_released = False
_floor_pickup_router_address = 0
_floor_pickup_native_ready = False
_item_card_state: dict[str, Any] | None = _active_native_state.get("item_card")
_pickup_registry_state: dict[str, Any] | None = _active_native_state.get("pickup_registry")
_item_card_diagnostic_enabled = True
_item_card_bounds_library: Any = None
_interaction_prompt_state: dict[str, Any] | None = _active_native_state.get("prompt")
_npc_eligible_state: dict[str, Any] | None = _active_native_state.get("npc")

# The single source of truth for "what does Borderlands 4 itself currently
# consider interactable" - mirrored straight from ClientSetCurrentInteractable
# every time the native game calls it. Covers every interactable class the
# game knows about (lootables, vending machines, Vault Power, quest props,
# future additions, ...) with no hand-maintained whitelist required.
_native_current_interactable: Any = None


class _MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = (
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    )


class _FLOOR_PICKUP_USE_REQUEST(ctypes.Structure):
    _fields_ = (
        ("owner", ctypes.c_void_p),
        ("context", ctypes.c_void_p),
        ("flag_a", ctypes.c_uint8),
        ("flag_b", ctypes.c_uint8),
        ("padding", ctypes.c_uint8 * 6),
    )


class _ITEM_CARD_CONTROL(ctypes.Structure):
    _fields_ = (
        ("enabled", ctypes.c_uint64),
        ("selected_actor", ctypes.c_uint64),
    )


class _INTERACTION_PROMPT_CONTROL(ctypes.Structure):
    _fields_ = (("enabled", ctypes.c_uint64),)


from .native_memory import (
    _MEM_COMMIT,
    _MEM_RESERVE,
    _MEM_RELEASE,
    _MEM_IMAGE,
    _PAGE_NOACCESS,
    _PAGE_GUARD,
    _PAGE_EXECUTE_READWRITE,
    _EXECUTE_PROTECTIONS,
)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_kernel32.GetCurrentProcess.argtypes = ()
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.VirtualQuery.argtypes = (
    wintypes.LPCVOID,
    ctypes.POINTER(_MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
)
_kernel32.VirtualQuery.restype = ctypes.c_size_t
_kernel32.ReadProcessMemory.argtypes = (
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
)
_kernel32.ReadProcessMemory.restype = wintypes.BOOL
_kernel32.VirtualProtect.argtypes = (
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.VirtualProtect.restype = wintypes.BOOL
_kernel32.VirtualAlloc.argtypes = (
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.DWORD,
    wintypes.DWORD,
)
_kernel32.VirtualAlloc.restype = wintypes.LPVOID
_kernel32.VirtualFree.argtypes = (
    wintypes.LPVOID,
    ctypes.c_size_t,
    wintypes.DWORD,
)
_kernel32.VirtualFree.restype = wintypes.BOOL
_kernel32.FlushInstructionCache.argtypes = (
    wintypes.HANDLE,
    wintypes.LPCVOID,
    ctypes.c_size_t,
)
_kernel32.FlushInstructionCache.restype = wintypes.BOOL


camera_offset_x = SliderOption(
    "camera_offset_x",
    0.0,
    -75.0,
    75.0,
    step=1.0,
    is_integer=False,
    display_name="Camera Offset X",
    description="Forward and backward camera offset.",
)

camera_offset_y = SliderOption(
    "camera_offset_y",
    75.0,
    0.0,
    150.0,
    step=1.0,
    is_integer=False,
    display_name="Camera Offset Y",
    description="Left and right shoulder offset.",
)

camera_offset_z = SliderOption(
    "camera_offset_z",
    10.0,
    -65.0,
    85.0,
    step=1.0,
    is_integer=False,
    display_name="Camera Offset Z",
    description="Vertical camera offset.",
)

from .ads_zoom_settings import create_options as _create_camera_feature_options
_camera_feature_options = _create_camera_feature_options(SliderOption, BoolOption)

from .vehicle_camera import RANGES as _VEHICLE_RANGES
vehicle_offset_x, vehicle_offset_y, vehicle_offset_z = tuple(
    SliderOption('vehicle_offset_'+axis, 0.0, float(lo), float(hi),
                 step=1.0, is_integer=False, display_name='Vehicle Offset '+axis.upper(),
                 description=description)
    for axis, (lo, hi), description in zip(
        'xyz', _VEHICLE_RANGES,
        ('Forward/backward vehicle camera offset.',
         'Signed left/right vehicle camera offset.', 'Vertical vehicle camera offset.'))
)

vehicle_camera_relative_drive = BoolOption(
    "vehicle_camera_relative_drive", False, is_hidden=True,
    display_name="Camera-relative Vehicle Driving",
    description="Optional WASD/left-stick directions relative to camera; original driving by default.",
)

def _set_vehicle_control(value: bool) -> None:
    from . import vehicle_control
    checked = bool(value)
    if checked:
        vehicle_control.start(sys.modules[__name__])
    elif not vehicle_control.shutdown():
        raise RuntimeError("Vehicle control cleanup incomplete; option retained")
    vehicle_camera_relative_drive.value = checked
    mod.save_settings()


# Experimental omnidirectional movement (integrated former pyexec lab build).
omni_movement_experimental = BoolOption(
    "omni_movement_experimental", False, is_hidden=True,
    display_name="Omnidirectional Movement (Experimental)",
    description=(
        "Body follows WASD/left-stick direction in third person; manual Sprint, "
        "Sprint action again during Sprint dashes, air dash follows movement input. "
        "Uses your current game key mappings. Default: off."
    ),
)
omni_movement_diagnostics = BoolOption(
    "omni_movement_diagnostics", False, is_hidden=True,
    display_name="Omnidirectional Movement Diagnostics",
    description="Lab diagnostics: pose/weapon discovery, console state messages, JSON report on every stop.",
)
omni_hybrid_ads = BoolOption(
    "omni_hybrid_ads", False, is_hidden=True,
    display_name="Hybrid ADS Mode (Omni)",
    description=(
        "Omni only: holding ADS aims over the shoulder (body faces the view, "
        "regular camera offsets); Sprint while aiming toggles the weapon scope. "
        "TPS zoom uses ADS ZOOM settings. Includes snipers; Sniper ADS applies "
        "when Hybrid is off. Default: off."
    ),
)


def _set_omni_hybrid_ads(value: bool) -> bool:
    omni_hybrid_ads.value = value is True and HYBRID_ADS_AVAILABLE
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] OMNI_SAVE_FAILED {exc}")
    logging.info(f"[BL4ThirdPersonPOC] OMNI_HYBRID_ADS enabled={omni_hybrid_ads.value}")
    return True


def _omni_movement_running() -> bool:
    from . import omni
    return omni.is_running(sys.modules[__name__])


def _omni_movement_caption() -> str:
    if omni_movement_experimental.value is not True:
        return "OFF"
    return "ON" if _omni_movement_running() else "ON - STOPPED (see console)"


def _set_omni_movement(value: bool) -> bool:
    """Start/stop the feature and persist the choice only after it took effect."""
    from . import omni
    owner = sys.modules[__name__]
    requested = value is True
    try:
        omni.settings.set_diagnostics(omni_movement_diagnostics.value is True)
        if requested:
            if not omni.start(owner):
                logging.error(
                    "[BL4ThirdPersonPOC] OMNI_START_REFUSED "
                    f"reason={omni.last_failure()!r}; option unchanged"
                )
                return False
        elif not omni.shutdown(owner, "FEATURE_DISABLED"):
            logging.error(
                "[BL4ThirdPersonPOC] OMNI_DISABLE_REFUSED restoration incomplete; "
                "option retained, retry with bl4tps_omni off"
            )
            return False
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] OMNI_TOGGLE_FAILED {type(exc).__name__}: {exc}")
        return False
    omni_movement_experimental.value = requested
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] OMNI_SAVE_FAILED {exc}")
    logging.info(f"[BL4ThirdPersonPOC] OMNI_MOVEMENT enabled={requested}")
    return True


def _set_omni_diagnostics(value: bool) -> bool:
    from . import omni
    omni_movement_diagnostics.value = value is True
    omni.settings.set_diagnostics(omni_movement_diagnostics.value)
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] OMNI_SAVE_FAILED {exc}")
    owner = sys.modules[__name__]
    # Sessions read the switch when they bind; restart a running feature.
    if omni.is_running(owner) and not omni.restart(owner, "DIAGNOSTICS_CHANGED"):
        logging.error("[BL4ThirdPersonPOC] OMNI_RESTART_FAILED after diagnostics change")
        return False
    return True


sniper_tps_ads = BoolOption(
    "sniper_tps_ads",
    False,
    is_hidden=True,
    display_name="Sniper ADS in Third Person",
    description="Use the existing TPS ADS route for sniper rifles. Default: FPS.",
)

tps_ffyl_beta = BoolOption(
    "tps_ffyl_beta",
    True,
    is_hidden=True,
    display_name="TPS-FFYL (Beta)",
    description="Use the collision-aware third-person FFYL camera. Default: enabled.",
)
tps_ground_slam_beta = BoolOption(
    "tps_ground_slam_beta",
    True,
    is_hidden=True,
    display_name="TPS Ground Slam (Beta)",
    description="Third-person Ground Slam with camera collision and preserved aim. Default: enabled.",
)
_ground_slam_beta_fault = False

ground_slam_distance_cm = SliderOption(
    'ground_slam_distance_cm', 150.0, 0.0, 250.0, step=5.0, is_integer=False,
    is_hidden=True, display_name='Ground Slam Extra Distance',
    description='Additional camera distance in cm during a Ground Slam; 0 disables it.',
)
_camera_feature_options['slam_distance'] = ground_slam_distance_cm

_ffyl_beta_fault = False

# Retain the serialized SDK key so existing hidden-option settings load unchanged.
dynamic_motion_camera_enabled = BoolOption(
    "gow_camera_enabled",
    False,
    is_hidden=True,
    display_name="Dynamic Camera Motion",
    description="Apply Spine3-based camera motion in third person.",
)


root_height_enabled = BoolOption(
    "root_height_enabled", True, is_hidden=True,
    display_name="Grounded Body Height (QA)",
    description="Follow terrain-related body lowering in normal third person.",
)
from . import root_height
_camera_frame = None
root_height.reset(sys.modules[__name__])
_camera_feature_options['root_height'] = root_height_enabled
_camera_feature_options['set_root_height'] = lambda value: _set_root_height_enabled(value)


def _set_root_height_enabled(value: bool) -> None:
    root_height_enabled.value = value is True
    root_height.reset(sys.modules[__name__])
    _dynamic_motion_reset()
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC.RootHeight] SAVE_FAILED {exc}")
    logging.info(f"[BL4ThirdPersonPOC.RootHeight] enabled={root_height_enabled.value}")


def _get_runtime() -> tuple[Any, Any, Any]:
    """Resolve the current local controller, pawn and camera for this call.

    Return missing elements as None during loading; callers must check the full
    required tuple before native/SDK access. This helper is not a UObject serial
    validator and must not be used as permission to dereference a saved address.
    """
    try:
        # Never accept a loading-time controller.  Oak may keep a Python
        # wrapper alive briefly while the underlying UObject is replaced by
        # world streaming; invoking an Unreal function on that wrapper is a
        # native use-after-free which Python cannot catch.
        pc = get_pc()
    except Exception:
        return None, None, None

    if pc is None:
        return None, None, None

    pawn = None
    for attribute in ("Character", "Pawn", "AcknowledgedPawn"):
        try:
            candidate = getattr(pc, attribute)
            if candidate is not None:
                pawn = candidate
                break
        except Exception:
            pass

    try:
        camera_manager = pc.OakPlayerCameraManager
    except Exception:
        camera_manager = None

    return pc, pawn, camera_manager


def _object_address(value: Any) -> int:
    try:
        return int(value._get_address())
    except Exception:
        return 0


from .game_hooks import (
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
)


def _persist_camera_stack_owner() -> None:
    return _persist_camera_stack_owner_impl(
        owner_module=sys.modules[__name__],
    )


def _record_camera_stack_owner(pawn: Any, camera_manager: Any) -> None:
    return _record_camera_stack_owner_impl(
        pawn,
        camera_manager,
        owner_module=sys.modules[__name__],
    )


def _clear_camera_stack_owner() -> None:
    return _clear_camera_stack_owner_impl(
        owner_module=sys.modules[__name__],
    )


def _retire_camera_stack_owner(reason: str) -> None:
    return _retire_camera_stack_owner_impl(
        reason,
        owner_module=sys.modules[__name__],
    )


def _defer_camera_pop(reason: str) -> None:
    return _defer_camera_pop_impl(
        reason,
        owner_module=sys.modules[__name__],
    )


def _retry_pending_camera_pop() -> bool:
    return _retry_pending_camera_pop_impl(
        owner_module=sys.modules[__name__],
    )


def _reset_camera_lifecycle() -> None:
    return _reset_camera_lifecycle_impl(
        owner_module=sys.modules[__name__],
    )


def _arm_camera_lifecycle(reason: str, *, expected_pawn: int = 0) -> None:
    return _arm_camera_lifecycle_impl(
        reason,
        expected_pawn=expected_pawn,
        owner_module=sys.modules[__name__],
    )


def _discard_camera_lifecycle(reason: str) -> bool:
    return _discard_camera_lifecycle_impl(
        reason,
        owner_module=sys.modules[__name__],
    )


def _camera_lifecycle_offset_suppressed() -> bool:
    return _camera_lifecycle_offset_suppressed_impl(
        owner_module=sys.modules[__name__],
    )


from .native_memory import (
    _ffyl_camera_stack_empty as _memory_ffyl_camera_stack_empty,
    _ffyl_camera_stack_has_single_tps as _memory_ffyl_camera_stack_has_single_tps,
)


def _ffyl_camera_stack_empty(camera_manager: Any) -> bool:
    return _memory_ffyl_camera_stack_empty(
        camera_manager,
        _kernel32=_kernel32,
        _native_read=_native_read,
        _object_address=_object_address,
    )


def _ffyl_camera_stack_has_single_tps(camera_manager: Any) -> bool:
    return _memory_ffyl_camera_stack_has_single_tps(
        camera_manager,
        _ffyl_camera_stack_empty=_ffyl_camera_stack_empty,
        _native_read=_native_read,
        _object_address=_object_address,
    )


from .game_hooks import (
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
)


def _remove_ffyl_early_handoff_hook() -> None:
    return _remove_ffyl_early_handoff_hook_impl(
        owner_module=sys.modules[__name__],
    )


def _install_ffyl_early_handoff_hook() -> None:
    return _install_ffyl_early_handoff_hook_impl(
        owner_module=sys.modules[__name__],
    )


def _ffyl_early_ended_pre_hook(obj: Any, args: Any, ret: Any, func: Any) -> None:
    return _ffyl_early_ended_pre_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


from .game_hooks import _update_camera_lifecycle_impl


def _update_camera_lifecycle() -> None:
    return _update_camera_lifecycle_impl(
        owner_module=sys.modules[__name__],
    )


def _client_restart_pre_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _client_restart_pre_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _ffyl_downed_pre_hook(obj: Any, args: Any, ret: Any, func: Any) -> None:
    return _ffyl_downed_pre_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _install_ffyl_native_pre_hook() -> None:
    return _install_ffyl_native_pre_hook_impl(
        owner_module=sys.modules[__name__],
    )


def _remove_ffyl_native_pre_hook() -> None:
    return _remove_ffyl_native_pre_hook_impl(
        owner_module=sys.modules[__name__],
    )


def _client_restart_post_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _client_restart_post_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _install_camera_lifecycle_hook() -> None:
    return _install_camera_lifecycle_hook_impl(
        owner_module=sys.modules[__name__],
    )


def _remove_camera_lifecycle_hook() -> None:
    return _remove_camera_lifecycle_hook_impl(
        owner_module=sys.modules[__name__],
    )


from .camera_math import (
    _set_camera_offset_impl,
    _dynamic_motion_reset_impl,
    _reset_mantle_camera_state_impl,
)


def _set_camera_offset(x: float, y: float, z: float) -> bool:
    return _set_camera_offset_impl(
        x,
        y,
        z,
        owner_module=sys.modules[__name__],
    )


# Store motion settings outside the package so .sdkmod archives remain read-only.
from .motion_settings import (
    DEFAULTS as _MOTION_DEFAULTS,
    read_parameters as _read_motion_parameters,
)

_dynamic_motion_parameters = dict(_MOTION_DEFAULTS)

_DYNAMIC_MOTION_CHOICE_FILE = Path(SETTINGS_DIR) / "BL4ThirdPersonPOC.camera_motion.json"


from .ui_and_commands import (
    _load_dynamic_motion_choice_impl,
    _save_dynamic_motion_choice_impl,
    _set_dynamic_motion_enabled_impl,
)


def _load_dynamic_motion_choice() -> bool:
    enabled = _load_dynamic_motion_choice_impl(
        owner_module=sys.modules[__name__],
    )
    _dynamic_motion_parameters.update(
        _read_motion_parameters(_DYNAMIC_MOTION_CHOICE_FILE)
    )
    return enabled


def _save_dynamic_motion_choice(value: bool) -> None:
    return _save_dynamic_motion_choice_impl(
        value,
        owner_module=sys.modules[__name__],
    )


# Camera motion stays inside the owned camera updater. No Python
# function replacement survives disable or RLM.
_dynamic_motion_enabled = _load_dynamic_motion_choice()
dynamic_motion_camera_enabled.value = _dynamic_motion_enabled
_dynamic_motion_state: dict[str, Any] = {}


def _dynamic_motion_reset() -> None:
    return _dynamic_motion_reset_impl(
        owner_module=sys.modules[__name__],
    )


_dynamic_motion_reset()


from .camera_math import (
    _apply_dynamic_motion_camera_offset as _apply_dynamic_motion_camera_offset_core,
    _apply_mantle_camera_offset as _apply_mantle_camera_offset_core,
    _dynamic_motion_point,
    _dynamic_motion_speed,
    _dynamic_motion_airborne,
    _dynamic_motion_crouched,
)


def _set_dynamic_motion_enabled(value: bool) -> None:
    return _set_dynamic_motion_enabled_impl(
        value,
        owner_module=sys.modules[__name__],
    )


def _apply_dynamic_motion_camera_offset(pawn: Any, manager: Any) -> None:
    return _apply_dynamic_motion_camera_offset_core(
        pawn,
        manager,
        _dynamic_motion_enabled=_dynamic_motion_enabled,
        motion_parameters=_dynamic_motion_parameters,
        _camera_frame=_camera_frame,
        _mantle_camera_state=_mantle_camera_state,
        _third_person_enabled=_third_person_enabled,
        _third_person_pushed=_third_person_pushed,
        _vehicle_camera_active=_vehicle_camera_active,
        _shop_camera_active=_shop_camera_active,
        _slide_active=_slide_active,
        _ladder_active=_ladder_active,
        _ads_active=_ads_active,
        _camera_lifecycle=_camera_lifecycle,
        _looks_like_first_person_fallback=_looks_like_first_person_fallback,
        _dynamic_motion_state=_dynamic_motion_state,
        _dynamic_motion_reset=_dynamic_motion_reset,
        _set_camera_offset=_set_camera_offset,
        camera_offset_x=camera_offset_x,
        camera_offset_y=camera_offset_y,
        camera_offset_z=camera_offset_z,
    )


_mantle_camera_state: dict[str, Any] = {}


def _reset_mantle_camera_state() -> None:
    return _reset_mantle_camera_state_impl(
        owner_module=sys.modules[__name__],
    )


def _apply_mantle_camera_offset(pawn: Any, manager: Any) -> None:
    return _apply_mantle_camera_offset_core(
        pawn,
        manager,
        _mantle_camera_state=_mantle_camera_state,
        _third_person_enabled=_third_person_enabled,
        _third_person_pushed=_third_person_pushed,
        _vehicle_camera_active=_vehicle_camera_active,
        _shop_camera_active=_shop_camera_active,
        _slide_active=_slide_active,
        _camera_lifecycle=_camera_lifecycle,
        _ladder_active=_ladder_active,
        _reset_mantle_camera_state=_reset_mantle_camera_state,
        _camera_frame=_camera_frame,
        _set_camera_offset=_set_camera_offset,
        camera_offset_x=camera_offset_x,
        camera_offset_y=camera_offset_y,
        camera_offset_z=camera_offset_z,
    )


from .camera_math import _apply_camera_offset_impl


def _apply_camera_offset() -> None:
    global _camera_frame
    from . import shoulder_blend
    owner = sys.modules[__name__]
    previous_frame = _camera_frame
    previous = shoulder_blend.begin(owner)
    _camera_frame = {} if (root_height_enabled.value is True or ground_slam_distance_cm.value > 0) else None
    try:
        return _apply_camera_offset_impl(owner_module=owner)
    finally:
        if _camera_frame is None or not _camera_frame.get('height_visited'):
            root_height.reset(owner)
        _camera_frame = previous_frame
        shoulder_blend.end(previous)


from .game_hooks import (
    _sample_slide_camera_offset_impl,
    _is_sliding_now_impl,
    _transition_to_first_person_impl,
    _update_slide_state_impl,
    _update_slide_camera_recovery_impl,
    _update_ladder_camera_state_impl,
    _update_vehicle_camera_state_impl,
)


def _sample_slide_camera_offset(phase: str) -> None:
    return _sample_slide_camera_offset_impl(
        phase,
        owner_module=sys.modules[__name__],
    )


def _is_sliding_now() -> bool:
    return _is_sliding_now_impl(
        owner_module=sys.modules[__name__],
    )


def _transition_to_first_person() -> bool:
    return _transition_to_first_person_impl(
        owner_module=sys.modules[__name__],
    )


def _update_slide_state() -> None:
    return _update_slide_state_impl(
        owner_module=sys.modules[__name__],
    )


def _update_slide_camera_recovery() -> None:
    return _update_slide_camera_recovery_impl(
        owner_module=sys.modules[__name__],
    )


def _update_ladder_camera_state() -> None:
    return _update_ladder_camera_state_impl(
        owner_module=sys.modules[__name__],
    )


from .camera_math import _camera_is_vehicle_view


def _is_vehicle_camera_view() -> bool:
    return _camera_is_vehicle_view(_get_runtime)


def _update_vehicle_camera_state() -> None:
    return _update_vehicle_camera_state_impl(
        owner_module=sys.modules[__name__],
    )


from .native_lifecycle import (
    _resume_native_after_ffyl_if_ready_impl,
    _native_slide_ads_ready_impl,
    _native_ads_stack_verified_impl,
    _native_slide_ads_owner_verified_impl,
    _require_guarded_beam_collision_impl,
    _ads_beam_can_hold_impl,
    _update_native_ads_origin_impl,
    _update_native_ownership_impl,
    _native_active_impl,
    _beam_active_impl,
    _ladder_guard_consume_impl,
    _native_stop_beam_impl,
    _native_stop_impl,
    _native_start_impl,
)


def _resume_native_after_ffyl_if_ready() -> bool:
    return _resume_native_after_ffyl_if_ready_impl(owner_module=sys.modules[__name__])


def _native_slide_ads_ready(camera: Any, pawn: Any) -> bool:
    return _native_slide_ads_ready_impl(
        camera, pawn, owner_module=sys.modules[__name__]
    )


def _native_ads_stack_verified(camera: Any) -> bool:
    return _native_ads_stack_verified_impl(camera, owner_module=sys.modules[__name__])


def _native_slide_ads_owner_verified(
    camera: Any, pawn: Any, recoil: Any, *, after_slide: bool = False
) -> bool:
    return _native_slide_ads_owner_verified_impl(
        camera,
        pawn,
        recoil,
        after_slide=after_slide,
        owner_module=sys.modules[__name__],
    )


def _require_guarded_beam_collision(helper: Any) -> None:
    return _require_guarded_beam_collision_impl(
        helper, owner_module=sys.modules[__name__]
    )


def _ads_beam_can_hold(camera: Any, pawn: Any) -> bool:
    return _ads_beam_can_hold_impl(camera, pawn, owner_module=sys.modules[__name__])


def _update_native_ads_origin(camera: Any, pawn: Any) -> None:
    return _update_native_ads_origin_impl(
        camera, pawn, owner_module=sys.modules[__name__]
    )


def _update_native_ownership() -> None:
    return _update_native_ownership_impl(owner_module=sys.modules[__name__])


from .camera_events import _camera_update_hook_impl


def _camera_update_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _camera_update_hook_impl(
        obj, args, ret, func, owner_module=sys.modules[__name__]
    )


from .camera_events import (
    _push_third_person_impl,
    _pop_third_person_impl,
    toggle_third_person_impl,
    controller_r3_camera_toggle_impl,
    swap_shoulder_impl,
    _restore_slide_third_person_impl,
)


def _push_third_person(*, transition_time: float = 1.0) -> bool:
    return _push_third_person_impl(
        transition_time=transition_time, owner_module=sys.modules[__name__]
    )


_NATIVE_OWNER_KEYS = (
    "_bl4_tps_beam_collision_owner",
    "_bl4_tps_beam_origin_owner",
    "_bl4_tps_recoil_owner",
)
# native_recoil installs the atomic Slide/Ladder PRE guard only when this is
# true. Beam eligibility below is independent of this required safety guard.
_native_handoff_guard_enabled = True
_native_fault = False
_native_fault_source: str | None = None
_native_fault_recovery_attempted = False
# Native starts automatically when the existing TPS ownership guards permit it.
# The console command can still disable it for the current session.
_native_auto_enabled = True
_native_last_attempt: tuple[int, int, int] | None = None
_native_ads_origin_attempt: tuple[int, int, int] | None = None
_native_ads_collision_held = False
_native_ads_pair_logged = False
_native_npc_pending = False
_native_npc_post_installed = False
_native_npc_context = None
_native_npc_calls = []
_native_ladder_handoff_pending = False
_native_ladder_seen = False
_native_slide_handoff_pending = False
_native_slide_seen = False
_native_slide_interior = False
_native_ffyl_pending = False
_native_ffyl_pending_pawn = 0


def _native_active() -> bool:
    return _native_active_impl(owner_module=sys.modules[__name__])


def _beam_active() -> bool:
    return _beam_active_impl(owner_module=sys.modules[__name__])


def _ladder_guard_consume(reason: str) -> bool:
    return _ladder_guard_consume_impl(reason, owner_module=sys.modules[__name__])


def _native_stop_beam(reason: str) -> bool:
    return _native_stop_beam_impl(reason, owner_module=sys.modules[__name__])


def _native_stop(reason: str) -> bool:
    return _native_stop_impl(reason, owner_module=sys.modules[__name__])


def _native_start(*, allow_tps_ads: bool = False) -> None:
    return _native_start_impl(
        allow_tps_ads=allow_tps_ads, owner_module=sys.modules[__name__]
    )


@command(
    "bl4tps_rc_native",
    description="Toggle automatic TPS recoil and FireBeam correction",
)
def toggle_native_correction(_args: Any) -> None:
    global _native_auto_enabled, _native_last_attempt, _native_ads_origin_attempt
    try:
        if _ffyl_native_resume_pending:
            logging.warning(
                "[BL4ThirdPersonPOC] NATIVE_TOGGLE_DEFERRED "
                "waiting for verified FFYL camera handoff"
            )
            return
        if _native_auto_enabled:
            _native_auto_enabled = False
            if (
                _native_active()
                or _active_native_state.get("ladder_guard")
                or _active_native_state.get("ladder_default")
            ) and not _native_stop("manual"):
                raise RuntimeError("Native restore unverified; restart game")
        else:
            # A PythonSDK mod reload can retain this helper module from the
            # previous build. Refuse before enabling automatic retry.
            from . import native_beam_collision

            _require_guarded_beam_collision(native_beam_collision)
            _native_auto_enabled = True
            _native_last_attempt = None
            _native_ads_origin_attempt = None
            _update_native_ownership()
        logging.info(f"[BL4ThirdPersonPOC] NATIVE_AUTO enabled={_native_auto_enabled}")
    except Exception as exc:
        logging.error(
            f"[BL4ThirdPersonPOC] NATIVE_TOGGLE_FAILED {type(exc).__name__}: {exc}"
        )


@command(
    "bl4tps_ffyl_early_trial", description="Enable automatic early Second Wind handoff"
)
def enable_early_second_wind_handoff(_args: Any) -> None:
    global _ffyl_early_auto_enabled
    _ffyl_early_auto_enabled = True
    logging.info(
        "[BL4ThirdPersonPOC] FFYL_EARLY_AUTO enabled=True; "
        "no command required for future Second Winds"
    )


@command(
    "bl4tps_ffyl_early_auto", description="Toggle automatic early Second Wind handoff"
)
def ffyl_early_auto_toggle(_args: Any) -> None:
    global _ffyl_early_auto_enabled
    if _camera_lifecycle.get("pending") or _ffyl_early_handoff_armed:
        logging.warning(
            "[BL4ThirdPersonPOC] FFYL_EARLY_AUTO_TOGGLE_DEFERRED "
            "wait for camera handoff to complete"
        )
        return
    _ffyl_early_auto_enabled = not _ffyl_early_auto_enabled
    logging.info(
        "[BL4ThirdPersonPOC] FFYL_EARLY_AUTO " f"enabled={_ffyl_early_auto_enabled}"
    )


@command(
    "bl4tps_rc_native_status", description="Read-only TPS recoil and Beam ownership"
)
def report_native_correction_status(_args: Any) -> None:
    """Inspect guarded Beam identity once, without changing native state."""
    try:
        import sys
        from . import native_beam_origin

        _pc, pawn, camera = _get_runtime()
        weapon = camera.CameraModeInputs.Weapon if camera is not None else None
        mode = (
            str(camera.GetActorCameraMode(pawn))
            if camera is not None and pawn is not None
            else "<unavailable>"
        )
        owned = tuple(
            bool(
                sys.modules.get(key) is not None
                and getattr(sys.modules[key], "active", True)
            )
            for key in _NATIVE_OWNER_KEYS
        )
        slide_fname = (
            int(_active_native_state["ladder_guard"]["control"].slide_fname)
            if _active_native_state.get("ladder_guard")
            else 0
        )
        logging.info(
            "[BL4ThirdPersonPOC] NATIVE_STATUS "
            f"auto={_native_auto_enabled} fault={_native_fault} "
            f"ffyl_native_resume_pending={_ffyl_native_resume_pending} "
            f"ffyl_early_handoff_armed={_ffyl_early_handoff_armed} "
            f'lifecycle_reason={_camera_lifecycle.get("reason")!r} '
            f'lifecycle_phase={_camera_lifecycle.get("phase")!r} '
            f'lifecycle_pending={_camera_lifecycle.get("pending")} '
            f"fault_source={_native_fault_source!r} "
            f"recovery_attempted={_native_fault_recovery_attempted} "
            f"ffyl_pre_hook={_ffyl_native_pre_installed} "
            f"ffyl_pre_pending={_native_ffyl_pending} "
            f"ladder_handoff_pending={_native_ladder_handoff_pending} "
            f"ladder_seen={_native_ladder_seen} "
            f"slide_handoff_pending={_native_slide_handoff_pending} "
            f"slide_seen={_native_slide_seen} "
            f"slide_interior={_native_slide_interior} "
            f"tps={_third_person_enabled} mode={mode!r} "
            f"weapon={_object_address(weapon):#x} "
            f"firebeam={native_beam_origin.is_firebeam(weapon) if weapon is not None else False} "
            f"beam_collision_owned={owned[0]} beam_origin_owned={owned[1]} "
            f"recoil_owned={owned[2]} "
            f'ladder_default_installed={bool(_active_native_state.get("ladder_default"))} '
            f'ladder_default_enabled={bool(_active_native_state["ladder_default"]["control"].enabled) if _active_native_state.get("ladder_default") else False} '
            f'ladder_default_replacements={int(_active_native_state["ladder_default"]["control"].replacements) if _active_native_state.get("ladder_default") else 0} '
            f'ladder_guard_installed={bool(_active_native_state.get("ladder_guard"))} '
            f'ladder_guard_status={int(_active_native_state["ladder_guard"]["control"].status) if _active_native_state.get("ladder_guard") else 0} '
            f'guard_allow_default={bool(_active_native_state["ladder_guard"]["control"].allow_default) if _active_native_state.get("ladder_guard") else False} '
            f"slide_fname={slide_fname:#x}"
        )
    except Exception as exc:
        logging.error(
            f"[BL4ThirdPersonPOC] NATIVE_STATUS_FAILED " f"{type(exc).__name__}: {exc}"
        )


def _pop_third_person(
    *, reason: str = "requested", transition_time: float = 1.0
) -> bool:
    return _pop_third_person_impl(
        reason=reason,
        transition_time=transition_time,
        owner_module=sys.modules[__name__],
    )


@keybind(
    "Toggle Third Person",
    "F5",
    display_name="Toggle Third Person",
)
def toggle_third_person() -> None:
    return toggle_third_person_impl(owner_module=sys.modules[__name__])


_controller_r3_camera_state: dict[str, Any] = {
    "pressed_at": None,
    "handled": False,
}
CONTROLLER_R3_CAMERA_HOLD_SECONDS = 0.300


@keybind(
    "Controller R3 Hold Camera Toggle",
    "Gamepad_RightThumbstick",
    display_name="Controller R3 Hold Camera Toggle",
    is_hidden=True,
    is_rebindable=False,
    event_filter=None,
)
def controller_r3_camera_toggle(event: EInputEvent) -> None:
    return controller_r3_camera_toggle_impl(event, owner_module=sys.modules[__name__])


@keybind(
    "Swap Shoulder",
    "F6",
    display_name="Swap Shoulder",
)
def swap_shoulder() -> None:
    return swap_shoulder_impl(owner_module=sys.modules[__name__])


from .ads_control import _reset_ads_press_intent_impl
from .ads_control import _clear_pending_ads_press_impl
from .ads_control import _note_weak_zoom_signal_impl
from .ads_control import _prepare_pending_ads_press_impl
from .ads_control import _arm_pending_ads_press_impl


def _reset_ads_press_intent() -> None:
    return _reset_ads_press_intent_impl(owner_module=sys.modules[__name__])


def _clear_pending_ads_press(reason: str, *, outcome: str = "invalid") -> bool:
    return _clear_pending_ads_press_impl(
        reason,
        outcome=outcome,
        owner_module=sys.modules[__name__],
    )


from .camera_math import _read_native_zoom_confirmation


def _native_zoom_confirms_ads(pawn: Any) -> bool:
    return _read_native_zoom_confirmation(pawn)


def _note_weak_zoom_signal(pawn: Any, source: str) -> None:
    return _note_weak_zoom_signal_impl(
        pawn,
        source,
        owner_module=sys.modules[__name__],
    )


def _prepare_pending_ads_press(weapon: Any, *, collector_address: int = 0) -> None:
    return _prepare_pending_ads_press_impl(
        weapon,
        collector_address=collector_address,
        owner_module=sys.modules[__name__],
    )


def _arm_pending_ads_press(pawn: Any, camera_manager: Any, *, source: str = "physical") -> None:
    return _arm_pending_ads_press_impl(
        pawn,
        camera_manager,
        source=source,
        owner_module=sys.modules[__name__],
    )


_reticle_publisher = None
_reticle_publish_faulted = False
_reticle_publish_counts = {}

# Reticle A/B: event-only publication at confirmed ADS and equip callback pair.
# Retain this boolean for existing diagnostic probes; no per-frame retry is armed.
_reticle_publish_pending = False
_reticle_gate_last_fail = ""


def _reset_reticle_publisher() -> None:
    global _reticle_publisher, _reticle_publish_faulted, _reticle_publish_counts
    global _reticle_publish_pending, _reticle_gate_last_fail
    _reticle_publisher = None
    _reticle_publish_faulted = False
    _reticle_publish_counts = {}
    _reticle_publish_pending = False
    _reticle_gate_last_fail = ""


def _set_ads_reticle_visibility(
    reason: str, *, scope_identity: tuple[int, ...] | None = None
) -> str:
    """One guarded model publication or Hybrid scope handover, without retries."""
    global _reticle_publisher, _reticle_publish_faulted
    if _reticle_publish_faulted:
        return "faulted"
    try:
        if _reticle_publisher is None:
            import sys
            import importlib

            # Force a fresh read from disk every time the publisher is
            # (re)built. `from ._reticle_publish import ...` alone would
            # silently reuse whatever bytecode is already cached in
            # sys.modules from an earlier mod load, even after this file
            # is edited and the mod is hot-reloaded.
            module_name = f"{__package__}._reticle_publish"
            if module_name in sys.modules:
                reticle_module = importlib.reload(sys.modules[module_name])
            else:
                reticle_module = importlib.import_module(module_name)
            _reticle_publisher = reticle_module.create_publisher(sys.modules[__name__])
        result = (
            _reticle_publisher()
            if scope_identity is None
            else _reticle_publisher.hide_for_scope(scope_identity)
        )
        status = result["status"]
        _reticle_publish_counts[status] = _reticle_publish_counts.get(status, 0) + 1
        if status in ("published", "hidden"):
            event = "TPS_RETICLE_PUBLISHED" if status == "published" else "HYBRID_TPS_RETICLE_HIDDEN"
            logging.info(
                f"[BL4ThirdPersonPOC] {event} reason={reason!r} {result}"
            )
        elif scope_identity is not None:
            logging.info(
                f"[BL4ThirdPersonPOC] HYBRID_TPS_RETICLE_HANDOVER "
                f"status={status!r} gate_fail={_reticle_gate_last_fail!r}"
            )
        return status
    except (AttributeError, RuntimeError, TypeError, ValueError, OSError, struct.error) as exc:
        _reticle_publish_faulted = True
        logging.error(
            f"[BL4ThirdPersonPOC] TPS_RETICLE_PUBLISH_DISABLED error={type(exc).__name__}: {exc}"
        )
        return "faulted"


def _publish_tps_reticle(reason: str) -> str:
    return _set_ads_reticle_visibility(reason)


def _hide_hybrid_tps_reticle(identity: tuple[int, ...]) -> str:
    return _set_ads_reticle_visibility("hybrid_scope_enter", scope_identity=identity)


def _request_tps_reticle_publish(reason: str) -> str:
    from .ads_handoff import _request_tps_reticle_publish_impl

    return _request_tps_reticle_publish_impl(reason, owner_module=sys.modules[__name__])


def _update_pending_tps_reticle() -> None:
    from .ads_handoff import _update_pending_tps_reticle_impl

    _update_pending_tps_reticle_impl(owner_module=sys.modules[__name__])


from .camera_events import _ffyl_camera_active_impl
from .ads_control import _activate_confirmed_ads_press_impl
from .ads_control import _reconcile_pending_ads_press_weapon_impl
from .ads_control import _update_pending_ads_press_impl
from .ads_control import _handle_first_person_ads_input_impl


def _ffyl_camera_active(pawn: Any, camera_manager: Any) -> bool:
    return _ffyl_camera_active_impl(
        pawn,
        camera_manager,
        owner_module=sys.modules[__name__],
    )


def _activate_confirmed_ads_press(
    pawn: Any,
    camera_manager: Any,
    confirmation: str,
    *,
    base_calibration=None,
) -> None:
    return _activate_confirmed_ads_press_impl(
        pawn,
        camera_manager,
        confirmation,
        base_calibration=base_calibration,
        owner_module=sys.modules[__name__],
    )


def _reconcile_pending_ads_press_weapon(
    pawn: Any,
    camera_manager: Any,
    source: str,
    *,
    collector_address: int = 0,
) -> bool:
    return _reconcile_pending_ads_press_weapon_impl(
        pawn,
        camera_manager,
        source,
        collector_address=collector_address,
        owner_module=sys.modules[__name__],
    )


def _update_pending_ads_press() -> None:
    return _update_pending_ads_press_impl(owner_module=sys.modules[__name__])


def _handle_first_person_ads_input(event: EInputEvent) -> None:
    return _handle_first_person_ads_input_impl(
        event,
        owner_module=sys.modules[__name__],
    )


@keybind(
    "First-Person ADS Mouse Input",
    "RightMouseButton",
    display_name="First-Person ADS Mouse Input",
    is_hidden=True,
    is_rebindable=False,
    event_filter=None,
)
def first_person_ads_mouse_input(
    event: EInputEvent,
) -> None:
    _handle_first_person_ads_input(event)


@keybind(
    "First-Person ADS Controller Input",
    "Gamepad_LeftTrigger",
    display_name="First-Person ADS Controller Input",
    is_hidden=True,
    is_rebindable=False,
    event_filter=None,
)
def first_person_ads_controller_input(
    event: EInputEvent,
) -> None:
    _handle_first_person_ads_input(event)


from .camera_math import (
    _make_vector,
    _get_world_location,
    _get_actor_eye_location,
    _get_look_at_rotation,
    _get_tps_crosshair_screen,
)


def _native_write_code(address: int, data: bytes) -> None:
    cache = globals().get('_omni_rebind_memory')
    admission = None if cache is None else cache.write_admission(address, data)
    return _native_write_code_impl(
        address,
        data,
        _admit=admission,
        _kernel32=_kernel32,
        _PAGE_EXECUTE_READWRITE=_PAGE_EXECUTE_READWRITE,
    )


from .native_memory import (
    _native_write_code as _native_write_code_impl,
    _native_allocate_hook as _native_allocate_hook_impl,
    _native_absolute_jump,
    _native_build_trampoline,
    _item_card_store_r11,
    _item_card_copy_rbp_qword,
    _item_card_copy_stack_qword,
    _item_card_rel32,
    _item_card_patch_rel32,
    _item_card_build_gate2_stub,
    _item_card_build_final_stub,
)


def _native_allocate_hook(
    target: int,
    original: bytes,
    hook_length: int,
    stub_data_builder: Any,
    label: str,
) -> dict[str, Any]:
    return _native_allocate_hook_impl(
        target,
        original,
        hook_length,
        stub_data_builder,
        label,
        _kernel32=_kernel32,
        _native_read=_native_read,
        _native_write_code=_native_write_code,
        _native_release_hook=_native_release_hook,
        _quarantine_native_patch=_quarantine_native_patch,
    )


from .native_hook_lifecycle import _native_restore_hook_impl, _native_release_hook_impl

from .item_card_runtime import (
    _item_card_install_gate2_hook_impl,
    _item_card_install_final_hook_impl,
    _item_card_hook_counter_impl,
)


def _item_card_install_gate2_hook(
    module_base: int,
) -> dict[str, Any]:
    return _item_card_install_gate2_hook_impl(
        module_base, owner_module=sys.modules[__name__]
    )


def _item_card_install_final_hook(
    module_base: int,
    pickup_actors: tuple[int, ...],
) -> dict[str, Any]:
    return _item_card_install_final_hook_impl(
        module_base, pickup_actors, owner_module=sys.modules[__name__]
    )


def _native_restore_hook(hook: dict[str, Any]) -> None:
    return _native_restore_hook_impl(hook, owner_module=sys.modules[__name__])


def _native_release_hook(hook: dict[str, Any]) -> None:
    return _native_release_hook_impl(hook, owner_module=sys.modules[__name__])


def _retire_prompt_stub(state: dict[str, Any]) -> None:
    """Retain restored prompt code and its buffer/control pins until process exit.

    The prompt SDK publisher must already be removed; restored code alone does
    not prove that an in-flight native call has left the stub.
    """
    if not state.get("restored") or state.get("hook_installed"):
        raise RuntimeError("Cannot retire an unrestored prompt hook")
    stub = int(state.get("stub", 0))
    if not stub:
        return
    _retired_native_stubs.append(
        (
            "prompt",
            stub,
            state["control"],
            state["counter"],
            state["point_buffers"],
            state["point_pointer"],
        )
    )
    state["stub"] = 0


def _item_card_hook_counter(hook: dict[str, Any]) -> int:
    return _item_card_hook_counter_impl(hook, owner_module=sys.modules[__name__])


from .camera_math import (
    _item_card_result_value,
    _item_card_quaternion_matrix,
    _item_card_rotator_matrix,
    _item_card_component_basis,
)


from .camera_math import (
    _item_card_determinant,
    _item_card_solve_3x3,
    _item_card_solve_nonnegative,
    _item_card_convex_hull,
    _item_card_point_in_polygon,
    _item_card_segment_distance,
    _item_card_dot,
    _item_card_ray_obb_hit,
    _item_card_numeric_candidate,
)


from .camera_math import _item_card_project


from .item_card_runtime import (
    _item_card_read_component_bounds_impl,
    _item_card_build_numeric_geometry_impl,
    _item_card_candidate_geometry_impl,
    _item_card_collect_pickups_impl,
    _perf_finish_item_refresh_impl,
    _item_card_disable_control_impl,
    _item_card_drain_gate2_impl,
    _item_card_active_gate2_actors_impl,
    _item_card_refresh_pickups_impl,
    _item_card_should_override_impl,
    _item_card_select_impl,
    _item_card_publish_selection_impl,
    _update_item_card_fusion_impl,
    _install_item_card_fusion_impl,
    _remove_item_card_fusion_impl,
    _get_item_card_selected_pickup_impl,
)


def _item_card_read_component_bounds(
    component: Any,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
]:
    return _item_card_read_component_bounds_impl(
        component, owner_module=sys.modules[__name__]
    )


from .camera_math import (
    _item_card_build_numeric_geometry as _item_card_build_numeric_geometry_core,
)


def _item_card_build_numeric_geometry(actor: Any) -> dict[str, Any]:
    return _item_card_build_numeric_geometry_impl(
        actor, owner_module=sys.modules[__name__]
    )


from .camera_math import _item_card_crosshair_ray


from .camera_math import (
    _item_card_candidate_geometry as _item_card_candidate_geometry_core,
)


def _item_card_candidate_geometry(
    pc: Any,
    pawn_location: tuple[float, float, float],
    crosshair: tuple[float, float],
    actor: Any,
) -> dict[str, Any] | None:
    return _item_card_candidate_geometry_impl(
        pc, pawn_location, crosshair, actor, owner_module=sys.modules[__name__]
    )


from .game_hooks import (
    _item_card_collect_pickups as _item_card_collect_pickups_core,
)


def _item_card_collect_pickups(
    state: dict[str, Any],
    *,
    force_geometry: bool = False,
    settle_addresses: set[int] | None = None,
) -> tuple[dict[int, str], dict[int, dict[str, Any]], set[int]]:
    return _item_card_collect_pickups_impl(
        state,
        force_geometry=force_geometry,
        settle_addresses=settle_addresses,
        owner_module=sys.modules[__name__],
    )


from .game_hooks import (
    _perf_finish_item_refresh as _perf_finish_item_refresh_core,
)


def _perf_finish_item_refresh(
    started_ns: int,
    paths: dict[int, str],
    old_paths: dict[int, str],
    rebuild_ns: int,
) -> None:
    return _perf_finish_item_refresh_impl(
        started_ns, paths, old_paths, rebuild_ns, owner_module=sys.modules[__name__]
    )


from .game_hooks import _item_card_disable_control as _item_card_disable_control_core


def _item_card_disable_control(state: dict[str, Any]) -> None:
    return _item_card_disable_control_impl(state, owner_module=sys.modules[__name__])


def _item_card_drain_gate2(state: dict[str, Any]) -> None:
    return _item_card_drain_gate2_impl(state, owner_module=sys.modules[__name__])


from .game_hooks import (
    _item_card_active_gate2_actors as _item_card_active_gate2_actors_core,
)


def _item_card_active_gate2_actors(
    state: dict[str, Any],
) -> dict[int, int]:
    return _item_card_active_gate2_actors_impl(
        state, owner_module=sys.modules[__name__]
    )


from .game_hooks import _item_card_refresh_pickups as _item_card_refresh_pickups_core


def _item_card_refresh_pickups(
    state: dict[str, Any],
    *,
    force: bool = False,
) -> None:
    return _item_card_refresh_pickups_impl(
        state, force=force, owner_module=sys.modules[__name__]
    )


def _item_card_should_override() -> bool:
    return _item_card_should_override_impl(owner_module=sys.modules[__name__])


from .camera_math import _item_card_surface_peer_limit


from .game_hooks import _item_card_select as _item_card_select_core


def _item_card_select(
    state: dict[str, Any],
    pc: Any,
    pawn: Any,
    camera_manager: Any,
) -> tuple[int, Any, dict[str, Any] | None, int, int]:
    return _item_card_select_impl(
        state, pc, pawn, camera_manager, owner_module=sys.modules[__name__]
    )


from .game_hooks import (
    _item_card_publish_selection as _item_card_publish_selection_core,
)


def _item_card_publish_selection(
    state: dict[str, Any],
    actor: int,
    actor_object: Any,
    geometry: dict[str, Any] | None,
    raw_count: int,
    eligible_count: int,
) -> None:
    return _item_card_publish_selection_impl(
        state,
        actor,
        actor_object,
        geometry,
        raw_count,
        eligible_count,
        owner_module=sys.modules[__name__],
    )


from .game_hooks import _update_item_card_fusion as _update_item_card_fusion_core


def _update_item_card_fusion() -> None:
    return _update_item_card_fusion_impl(owner_module=sys.modules[__name__])


from .native_lifecycle import (
    _quarantine_native_patch_impl,
    _retry_native_patch_quarantine_impl,
)


def _quarantine_native_patch(
    kind: str,
    state: dict[str, Any],
    reason: str,
) -> None:
    return _quarantine_native_patch_impl(
        kind, state, reason, owner_module=sys.modules[__name__]
    )


def _retry_native_patch_quarantine(*, kind: str | None = None) -> bool:
    return _retry_native_patch_quarantine_impl(
        kind=kind, owner_module=sys.modules[__name__]
    )


def _install_item_card_fusion() -> None:
    return _install_item_card_fusion_impl(owner_module=sys.modules[__name__])


def _remove_item_card_fusion(*, report: bool = True) -> None:
    return _remove_item_card_fusion_impl(
        report=report, owner_module=sys.modules[__name__]
    )


def _get_item_card_selected_pickup() -> Any:
    return _get_item_card_selected_pickup_impl(owner_module=sys.modules[__name__])


from .native_memory import (
    _interaction_prompt_xmm_store,
    _interaction_prompt_xmm_load,
    _interaction_prompt_build_stub,
)


from .game_hooks import (
    _interaction_prompt_trace_base as _interaction_prompt_trace_base_core,
    _interaction_prompt_trace as _interaction_prompt_trace_core,
    _interaction_prompt_update_hook as _interaction_prompt_update_hook_core,
)


from .interaction_runtime import (
    _interaction_prompt_trace_base_impl,
    _interaction_prompt_trace_impl,
    _retire_npc_eligible_stub_impl,
    _remove_npc_eligible_impl,
    _install_npc_eligible_impl,
    _interaction_prompt_update_hook_impl,
    _install_interaction_prompt_targeting_impl,
    _remove_interaction_prompt_targeting_impl,
    _get_tps_floor_pickup_target_impl,
)


def _interaction_prompt_trace_base() -> tuple[tuple[float, float, float], str, str]:
    return _interaction_prompt_trace_base_impl(owner_module=sys.modules[__name__])


from .game_hooks import (
    _npc_trace_actor,
    _npc_line_trace,
    _npc_reset_tracking,
)


def _interaction_prompt_trace() -> tuple[tuple[float, float, float], str, str]:
    return _interaction_prompt_trace_impl(owner_module=sys.modules[__name__])


def _retire_npc_eligible_stub(state: dict[str, Any]) -> None:
    return _retire_npc_eligible_stub_impl(state, owner_module=sys.modules[__name__])


def _remove_npc_eligible(*, report: bool = True) -> None:
    return _remove_npc_eligible_impl(report=report, owner_module=sys.modules[__name__])


def _install_npc_eligible() -> None:
    return _install_npc_eligible_impl(owner_module=sys.modules[__name__])


def _interaction_prompt_update_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _interaction_prompt_update_hook_impl(
        obj, args, ret, func, owner_module=sys.modules[__name__]
    )


def _install_interaction_prompt_targeting() -> None:
    return _install_interaction_prompt_targeting_impl(
        owner_module=sys.modules[__name__]
    )


def _remove_interaction_prompt_targeting(*, report: bool = True) -> None:
    return _remove_interaction_prompt_targeting_impl(
        report=report, owner_module=sys.modules[__name__]
    )


def _get_tps_floor_pickup_target() -> Any:
    return _get_tps_floor_pickup_target_impl(owner_module=sys.modules[__name__])


def _native_read(address: int, size: int) -> bytes:
    """Read committed memory through the existing bounded/readability checks.

    A complete ReadProcessMemory result is required. This checks accessibility,
    not object identity, build compatibility or concurrent ownership.
    """
    buffer = ctypes.create_string_buffer(size)
    count = ctypes.c_size_t()
    success = bool(
        _kernel32.ReadProcessMemory(
            _kernel32.GetCurrentProcess(),
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(count),
        )
    )
    if not success or int(count.value) != size:
        raise RuntimeError(
            f"ReadProcessMemory failed at 0x{address:X} " f"({count.value}/{size})"
        )
    return bytes(buffer.raw)


from .native_memory import _ads_object_address, _ads_property_rows
from .camera_math import _ads_object_path, _ads_class_name


from .native_memory import (
    _ads_delegate_listener_index as _ads_delegate_listener_index_impl,
    _find_ads_collector as _find_ads_collector_impl,
)


def _ads_delegate_listener_index(weapon: Any) -> int | None:
    return _ads_delegate_listener_index_impl(weapon, _native_read)


def _find_ads_collector(weapon: Any) -> Any:
    return _find_ads_collector_impl(weapon, _native_read, find_all)


from .camera_math import _ads_attribute_float


from .camera_math import _find_active_ads_sight


from .camera_math import _classify_ads_weapon


from .camera_math import _read_live_ads_fov


from .camera_math import _derive_ads_target_fov, _ads_smoothstep


def _ads_debug_error(stage: str, exc: Exception) -> None:
    _ads_debug["errors"] = int(_ads_debug.get("errors", 0)) + 1
    _ads_debug["last_error"] = f"{stage}: {type(exc).__name__}: {exc}"
    logging.error(
        "[BL4ThirdPersonPOC] HYBRID_ADS_ERROR "
        f"stage={stage!r}, error={type(exc).__name__}: {exc}"
    )


from .ads_events import _set_hybrid_tps_fov_impl


def _set_hybrid_tps_fov(value: float) -> None:
    return _set_hybrid_tps_fov_impl(value, owner_module=sys.modules[__name__])


from .ads_events import _begin_hybrid_ads_transition_impl


def _begin_hybrid_ads_transition(
    kind: str,
    start_fov: float,
    target_fov: float,
) -> None:
    return _begin_hybrid_ads_transition_impl(
        kind, start_fov, target_fov, owner_module=sys.modules[__name__]
    )


from .ads_handoff import _reset_ads_handoff_debug_impl


def _reset_ads_handoff_debug() -> None:
    return _reset_ads_handoff_debug_impl(owner_module=sys.modules[__name__])


from .camera_math import _read_ads_zoom_fields


def _ads_zoom_fields(pawn: Any) -> str:
    return _read_ads_zoom_fields(pawn)


from .ads_handoff import _cleanup_ads_handoff_impl


def _cleanup_ads_handoff(reason: str) -> None:
    return _cleanup_ads_handoff_impl(
        reason, owner_module=sys.modules[__name__]
    )


from .ads_handoff import _update_hybrid_ads_weapon_handoff_impl
from .ads_handoff import _update_hybrid_ads_route_reconciliation_impl
from .ads_handoff import _arm_late_tps_ads_equip_handoff_impl
from .ads_handoff import _hybrid_ads_weapon_equipped_pre_hook_impl
from .ads_handoff import _hybrid_ads_character_weapon_equipped_pre_hook_impl
from .ads_handoff import _hybrid_ads_character_weapon_equipped_post_hook_impl
from .ads_handoff import _hybrid_ads_weapon_equipped_post_hook_impl


def _update_hybrid_ads_weapon_handoff(
    pawn: Any,
    camera_manager: Any,
    ads_state: dict[str, Any],
) -> bool:
    return _update_hybrid_ads_weapon_handoff_impl(
        pawn,
        camera_manager,
        ads_state,
        owner_module=sys.modules[__name__],
    )


def _update_hybrid_ads_route_reconciliation() -> None:
    return _update_hybrid_ads_route_reconciliation_impl(
        owner_module=sys.modules[__name__],
    )


def _arm_late_tps_ads_equip_handoff(obj: Any, args: Any) -> bool:
    return _arm_late_tps_ads_equip_handoff_impl(
        obj,
        args,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_weapon_equipped_pre_hook(
    obj: Any, args: Any, ret: Any, func: Any
) -> None:
    return _hybrid_ads_weapon_equipped_pre_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_character_weapon_equipped_pre_hook(
    obj: Any, args: Any, ret: Any, func: Any
) -> None:
    return _hybrid_ads_character_weapon_equipped_pre_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_character_weapon_equipped_post_hook(
    obj: Any, args: Any, ret: Any, func: Any
) -> None:
    return _hybrid_ads_character_weapon_equipped_post_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_weapon_equipped_post_hook(
    obj: Any, args: Any, ret: Any, func: Any
) -> None:
    return _hybrid_ads_weapon_equipped_post_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


from .ads_events import (
    _start_hybrid_tps_ads_impl,
    _reverse_hybrid_tps_ads_impl,
    _release_hybrid_tps_ads_impl,
    _finish_hybrid_tps_ads_impl,
    _update_hybrid_tps_ads_impl,
    _cancel_hybrid_ads_impl,
    _hybrid_ads_zoom_change_hook_impl,
    _hybrid_ads_zoomed_out_hook_impl,
    _reset_hybrid_ads_debug_impl,
)


def _start_hybrid_tps_ads(
    camera_manager: Any,
    category: str,
    source: str,
    evidence: str,
    prepared_collector_address: int = 0,
    *,
    resume_state: Any = None,
    base_calibration: Any = None,
) -> None:
    return _start_hybrid_tps_ads_impl(
        camera_manager,
        category,
        source,
        evidence,
        prepared_collector_address,
        resume_state=resume_state,
        base_calibration=base_calibration,
        owner_module=sys.modules[__name__],
    )


def _reverse_hybrid_tps_ads() -> None:
    return _reverse_hybrid_tps_ads_impl(owner_module=sys.modules[__name__])


def _release_hybrid_tps_ads() -> None:
    return _release_hybrid_tps_ads_impl(owner_module=sys.modules[__name__])


def _finish_hybrid_tps_ads() -> None:
    return _finish_hybrid_tps_ads_impl(owner_module=sys.modules[__name__])


def _update_hybrid_tps_ads() -> None:
    return _update_hybrid_tps_ads_impl(owner_module=sys.modules[__name__])


def _cancel_hybrid_ads(reason: str, *, restore: bool = True) -> None:
    return _cancel_hybrid_ads_impl(
        reason,
        restore=restore,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_zoom_change_hook(obj: Any, args: Any, ret: Any, func: Any) -> Any:
    return _hybrid_ads_zoom_change_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _hybrid_ads_zoomed_out_hook(obj: Any, args: Any, ret: Any, func: Any) -> Any:
    return _hybrid_ads_zoomed_out_hook_impl(
        obj,
        args,
        ret,
        func,
        owner_module=sys.modules[__name__],
    )


def _reset_hybrid_ads_debug() -> None:
    return _reset_hybrid_ads_debug_impl(owner_module=sys.modules[__name__])


from .game_hooks import (
    _install_hybrid_ads_hooks_impl,
    _remove_hybrid_ads_hooks_impl,
)


def _install_hybrid_ads_hooks() -> None:
    _install_hybrid_ads_hooks_impl(
        _ads_hooks_installed=_ads_hooks_installed,
        _remove_hybrid_ads_hooks=_remove_hybrid_ads_hooks,
        ADS_ZOOM_CHANGE_FUNCTION=ADS_ZOOM_CHANGE_FUNCTION,
        ADS_ZOOM_CHANGE_IDENTIFIER=ADS_ZOOM_CHANGE_IDENTIFIER,
        _hybrid_ads_zoom_change_hook=_hybrid_ads_zoom_change_hook,
        ADS_ZOOMED_OUT_FUNCTION=ADS_ZOOMED_OUT_FUNCTION,
        ADS_ZOOMED_OUT_IDENTIFIER=ADS_ZOOMED_OUT_IDENTIFIER,
        _hybrid_ads_zoomed_out_hook=_hybrid_ads_zoomed_out_hook,
        ADS_WEAPON_EQUIPPED_FUNCTION=ADS_WEAPON_EQUIPPED_FUNCTION,
        ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER=ADS_WEAPON_EQUIPPED_PRE_IDENTIFIER,
        ADS_WEAPON_EQUIPPED_POST_IDENTIFIER=ADS_WEAPON_EQUIPPED_POST_IDENTIFIER,
        _hybrid_ads_weapon_equipped_pre_hook=_hybrid_ads_weapon_equipped_pre_hook,
        _hybrid_ads_weapon_equipped_post_hook=_hybrid_ads_weapon_equipped_post_hook,
        ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION=ADS_CHARACTER_WEAPON_EQUIPPED_FUNCTION,
        ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER=ADS_CHARACTER_WEAPON_EQUIPPED_PRE_IDENTIFIER,
        ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER=ADS_CHARACTER_WEAPON_EQUIPPED_POST_IDENTIFIER,
        _hybrid_ads_character_weapon_equipped_pre_hook=_hybrid_ads_character_weapon_equipped_pre_hook,
        _hybrid_ads_character_weapon_equipped_post_hook=_hybrid_ads_character_weapon_equipped_post_hook,
        _ads_debug_error=_ads_debug_error,
    )


def _remove_hybrid_ads_hooks() -> None:
    _remove_hybrid_ads_hooks_impl(
        _ads_hooks_installed=_ads_hooks_installed,
        _ads_debug_error=_ads_debug_error,
    )


from .ui_and_commands import (
    _log_camera_lifecycle_debug as _format_camera_lifecycle_debug,
    _log_hybrid_ads_debug as _format_hybrid_ads_debug,
)


def _log_camera_lifecycle_debug(label: str) -> None:
    _format_camera_lifecycle_debug(label, _camera_lifecycle)


def _log_hybrid_ads_debug(label: str) -> None:
    _format_hybrid_ads_debug(
        label,
        _ads_debug,
        _ads_route,
        _ads_active,
        _ads_press_intent,
        _ads_handoff,
    )


from .native_memory import (
    _native_query as _memory_query,
    _native_require_readable as _memory_require_readable,
    _native_require_executable as _memory_require_executable,
    _native_image_size as _memory_image_size,
    _native_executable_regions as _memory_executable_regions,
    _resolve_floor_pickup_router as _memory_resolve_floor_pickup_router,
    _use_native_floor_pickup as _memory_use_native_floor_pickup,
)


def _native_query(address: int) -> _MEMORY_BASIC_INFORMATION:
    cache = globals().get('_omni_rebind_memory')
    if cache is not None:
        return cache.query_region(address, _native_fresh_query)
    return _native_fresh_query(address)

def _native_fresh_query(address):
    return _memory_query(address, _kernel32, _MEMORY_BASIC_INFORMATION)


def _native_require_readable(
    address: int,
    size: int,
    label: str,
) -> None:
    return _memory_require_readable(address, size, label, _native_query)


def _native_require_executable(address: int, label: str) -> None:
    return _memory_require_executable(address, label, _native_query)


def _native_image_size(module_base: int) -> int:
    return _memory_image_size(module_base, _native_read)


def _native_executable_regions(module_base: int, image_size: int):
    yield from _memory_executable_regions(module_base, image_size, _native_query)


def _resolve_floor_pickup_router() -> int:
    return _memory_resolve_floor_pickup_router(
        _kernel32=_kernel32,
        _native_read=_native_read,
        _native_image_size=_native_image_size,
        _native_require_executable=_native_require_executable,
        _native_executable_regions=_native_executable_regions,
    )


def _initialize_native_floor_pickup() -> None:
    global _floor_pickup_router_address
    global _floor_pickup_native_ready

    _floor_pickup_router_address = 0
    _floor_pickup_native_ready = False
    try:
        router = _resolve_floor_pickup_router()
        _floor_pickup_router_address = router
        _floor_pickup_native_ready = True
        logging.info(
            "[BL4ThirdPersonPOC] Native floor-pickup router " f"ready at 0x{router:X}"
        )
    except Exception as exc:
        logging.error(
            "[BL4ThirdPersonPOC] Native floor pickup disabled: "
            f"{type(exc).__name__}: {exc}"
        )


def _use_native_floor_pickup(target_object: Any) -> bool:
    return _memory_use_native_floor_pickup(
        target_object,
        _floor_pickup_native_ready=_floor_pickup_native_ready,
        _floor_pickup_router_address=_floor_pickup_router_address,
        _get_runtime=_get_runtime,
        _native_require_readable=_native_require_readable,
        _native_read=_native_read,
        _native_require_executable=_native_require_executable,
        _FLOOR_PICKUP_USE_REQUEST=_FLOOR_PICKUP_USE_REQUEST,
    )


from .game_hooks import (
    _get_tps_interaction_target_impl,
    _handle_interaction_input_impl,
    _server_use_object_redirect_hook_impl,
    _cancel_pending_floor_pickup_impl,
    _server_use_junk_object_priority_hook_impl,
    _client_set_current_interactable_hook_impl,
    _update_pending_interaction_fallback_impl,
    _update_pending_floor_pickup_fallback_impl,
)


def _get_tps_interaction_target() -> Any:
    return _get_tps_interaction_target_impl(
        state=sys.modules[__name__],
    )


from .game_hooks import (
    _log_unhandled_tps_interaction_hit as _log_unhandled_tps_interaction_hit_impl,
)


def _log_unhandled_tps_interaction_hit() -> None:
    return _log_unhandled_tps_interaction_hit_impl(
        _get_runtime=_get_runtime,
        _get_tps_crosshair_screen=_get_tps_crosshair_screen,
        _make_vector=_make_vector,
        INTERACTION_TRACE_DISTANCE=INTERACTION_TRACE_DISTANCE,
    )


def _handle_interaction_input(event: EInputEvent) -> None:
    return _handle_interaction_input_impl(
        event,
        state=sys.modules[__name__],
    )


@keybind(
    "TPS Interaction Keyboard Input",
    "E",
    display_name="TPS Interaction Keyboard Input",
    is_hidden=True,
    is_rebindable=False,
    event_filter=None,
)
def tps_interaction_keyboard_input(event: EInputEvent) -> None:
    _handle_interaction_input(event)


@keybind(
    "TPS Interaction Controller Input",
    "Gamepad_FaceButton_Left",
    display_name="TPS Interaction Controller Input",
    is_hidden=True,
    is_rebindable=False,
    event_filter=None,
)
def tps_interaction_controller_input(event: EInputEvent) -> None:
    _handle_interaction_input(event)


def _server_use_object_redirect_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _server_use_object_redirect_hook_impl(
        obj,
        args,
        ret,
        func,
        state=sys.modules[__name__],
    )


def _cancel_pending_floor_pickup(reason: str) -> None:
    return _cancel_pending_floor_pickup_impl(
        reason,
        state=sys.modules[__name__],
    )


def _server_use_junk_object_priority_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _server_use_junk_object_priority_hook_impl(
        obj,
        args,
        ret,
        func,
        state=sys.modules[__name__],
    )


def _client_set_current_interactable_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _client_set_current_interactable_hook_impl(
        obj,
        args,
        ret,
        func,
        state=sys.modules[__name__],
    )


def _update_pending_interaction_fallback() -> None:
    return _update_pending_interaction_fallback_impl(
        state=sys.modules[__name__],
    )


def _update_pending_floor_pickup_fallback() -> None:
    return _update_pending_floor_pickup_fallback_impl(
        state=sys.modules[__name__],
    )


from .game_hooks import (
    _install_interaction_redirect_impl,
    _remove_interaction_redirect_impl,
)


def _install_interaction_redirect() -> None:
    _install_interaction_redirect_impl(
        state=sys.modules[__name__],
        _remove_interaction_redirect=_remove_interaction_redirect,
        SERVER_USE_OBJECT_FUNCTION=SERVER_USE_OBJECT_FUNCTION,
        INTERACTION_REDIRECT_IDENTIFIER=INTERACTION_REDIRECT_IDENTIFIER,
        LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION=LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
        LEGACY_FLOOR_PICKUP_HOOK_IDENTIFIER=LEGACY_FLOOR_PICKUP_HOOK_IDENTIFIER,
        FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER=FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
        CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION=CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
        SHOP_CAMERA_HOOK_IDENTIFIER=SHOP_CAMERA_HOOK_IDENTIFIER,
        _server_use_object_redirect_hook=_server_use_object_redirect_hook,
        _server_use_junk_object_priority_hook=_server_use_junk_object_priority_hook,
        _client_set_current_interactable_hook=_client_set_current_interactable_hook,
    )


def _remove_interaction_redirect() -> None:
    _remove_interaction_redirect_impl(
        state=sys.modules[__name__],
        SERVER_USE_OBJECT_FUNCTION=SERVER_USE_OBJECT_FUNCTION,
        INTERACTION_REDIRECT_IDENTIFIER=INTERACTION_REDIRECT_IDENTIFIER,
        CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION=CLIENT_SET_CURRENT_INTERACTABLE_FUNCTION,
        SHOP_CAMERA_HOOK_IDENTIFIER=SHOP_CAMERA_HOOK_IDENTIFIER,
        LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION=LEGACY_SERVER_USE_JUNK_OBJECT_FUNCTION,
        FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER=FLOOR_PICKUP_PRIORITY_HOOK_IDENTIFIER,
    )


from .ui_and_commands import _dump_unreal_object


from .ui_and_commands import _dump_camera_state_impl as _dump_camera_state_impl_core


def _dump_camera_state_impl() -> None:
    return _dump_camera_state_impl_core(
        _get_runtime,
        _third_person_enabled,
        _third_person_pushed,
        _ads_active,
    )


@keybind(
    "Dump Camera State",
    "F8",
    display_name="Dump Camera State",
)
def dump_camera_state() -> None:
    _dump_camera_state_impl()


from .game_hooks import _repair_third_person as _repair_third_person_impl


def _repair_third_person(*, automatic: bool) -> bool:
    return _repair_third_person_impl(
        automatic=automatic,
        _third_person_enabled=_third_person_enabled,
        _ads_active=_ads_active,
        _vehicle_camera_active=_vehicle_camera_active,
        _shop_camera_active=_shop_camera_active,
        _ladder_active=_ladder_active,
        _get_runtime=_get_runtime,
        _camera_lifecycle=_camera_lifecycle,
        _third_person_pushed=_third_person_pushed,
        _camera_stack_owner=_camera_stack_owner,
        _pop_third_person=_pop_third_person,
        _push_third_person=_push_third_person,
    )


from .ui_and_commands import (
    SLIDE_FIELD_TOKENS,
    _is_interesting_slide_field,
    _dump_slide_object,
    _dump_slide_state_impl,
)


@keybind(
    "Dump Slide State",
    "F9",
    display_name="Dump Slide State",
)
def dump_slide_state() -> None:
    return _dump_slide_state_impl(
        _get_runtime,
        _third_person_enabled,
        _third_person_pushed,
        _ads_active,
        _last_anim_slide_states,
    )


@keybind(
    "Repair Third Person",
    None,
    display_name="Repair Third Person",
)
def repair_third_person() -> None:
    _repair_third_person(automatic=False)


from .ui_and_commands import query_actor_camera_mode as _query_actor_camera_mode_impl


def query_actor_camera_mode() -> None:
    return _query_actor_camera_mode_impl(
        _get_runtime=_get_runtime,
        _apply_camera_offset=_apply_camera_offset,
    )


from .camera_math import _camera_looks_first_person


def _looks_like_first_person_fallback() -> bool:
    return _camera_looks_first_person(_get_runtime)


def _restore_slide_third_person() -> bool:
    return _restore_slide_third_person_impl(owner_module=sys.modules[__name__])


from .game_hooks import (
    _install_camera_mode_probe_impl,
    _remove_camera_mode_probe_impl,
)


def _install_camera_mode_probe() -> None:
    global _camera_mode_probe_installed
    _camera_mode_probe_installed = _install_camera_mode_probe_impl(
        installed=_camera_mode_probe_installed,
        callback=_camera_mode_request_hook,
        function=CAMERA_MODE_FUNCTION,
        identifier=CAMERA_MODE_PROBE_IDENTIFIER,
    )


def _remove_camera_mode_probe() -> None:
    global _camera_mode_probe_installed
    _camera_mode_probe_installed = _remove_camera_mode_probe_impl(
        installed=_camera_mode_probe_installed,
        function=CAMERA_MODE_FUNCTION,
        identifier=CAMERA_MODE_PROBE_IDENTIFIER,
    )


from .game_hooks import (
    _camera_mode_request_hook_impl,
    _log_camera_stack_request_impl,
    _install_camera_stack_probes_impl,
    _remove_camera_stack_probes_impl,
)


def _camera_mode_request_hook(obj: Any, args: Any, ret: Any, func: Any) -> None:
    _camera_mode_request_hook_impl(
        obj,
        args,
        ret,
        func,
        _third_person_enabled=_third_person_enabled,
        _third_person_pushed=_third_person_pushed,
        _slide_active=_slide_active,
        _ads_active=_ads_active,
    )


def _log_camera_stack_request(operation: str, obj: Any, args: Any) -> None:
    _log_camera_stack_request_impl(
        operation,
        obj,
        args,
        _third_person_enabled=_third_person_enabled,
        _third_person_pushed=_third_person_pushed,
        _slide_active=_slide_active,
        _ads_active=_ads_active,
    )


def _push_actor_camera_mode_probe(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    _log_camera_stack_request(
        "PushActorCameraMode",
        obj,
        args,
    )


def _pop_actor_camera_mode_probe(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    _log_camera_stack_request(
        "PopActorCameraMode",
        obj,
        args,
    )


def _install_camera_stack_probes() -> None:
    _install_camera_stack_probes_impl(
        _camera_stack_probes_installed=_camera_stack_probes_installed,
        _remove_camera_stack_probes=_remove_camera_stack_probes,
        PUSH_ACTOR_CAMERA_MODE_FUNCTION=PUSH_ACTOR_CAMERA_MODE_FUNCTION,
        POP_ACTOR_CAMERA_MODE_FUNCTION=POP_ACTOR_CAMERA_MODE_FUNCTION,
        _push_actor_camera_mode_probe=_push_actor_camera_mode_probe,
        _pop_actor_camera_mode_probe=_pop_actor_camera_mode_probe,
        CAMERA_STACK_PROBE_IDENTIFIER=CAMERA_STACK_PROBE_IDENTIFIER,
    )


def _remove_camera_stack_probes() -> None:
    _remove_camera_stack_probes_impl(
        _camera_stack_probes_installed=_camera_stack_probes_installed,
        CAMERA_STACK_PROBE_IDENTIFIER=CAMERA_STACK_PROBE_IDENTIFIER,
    )


from .camera_events import _blueprint_camera_probe_hook_impl


def _blueprint_camera_probe_hook(
    obj: Any,
    args: Any,
    ret: Any,
    func: Any,
) -> None:
    return _blueprint_camera_probe_hook_impl(
        obj, args, ret, func, owner_module=sys.modules[__name__]
    )


from .game_hooks import (
    _install_blueprint_camera_probe_impl,
    _remove_blueprint_camera_probe_impl,
)


def _install_blueprint_camera_probe() -> None:
    global _blueprint_camera_probe_installed
    global _blueprint_camera_probe_calls
    global _blueprint_camera_probe_last_slide
    if _blueprint_camera_probe_installed:
        return
    _blueprint_camera_probe_calls = 0
    _blueprint_camera_probe_last_slide = None
    _blueprint_camera_probe_installed = _install_blueprint_camera_probe_impl(
        installed=False,
        callback=_blueprint_camera_probe_hook,
        function=BLUEPRINT_UPDATE_CAMERA_FUNCTION,
        identifier=BLUEPRINT_CAMERA_PROBE_IDENTIFIER,
    )


def _remove_blueprint_camera_probe() -> None:
    global _blueprint_camera_probe_installed
    global _blueprint_camera_probe_last_slide
    if not _blueprint_camera_probe_installed:
        return
    _blueprint_camera_probe_installed = _remove_blueprint_camera_probe_impl(
        installed=True,
        function=BLUEPRINT_UPDATE_CAMERA_FUNCTION,
        identifier=BLUEPRINT_CAMERA_PROBE_IDENTIFIER,
    )
    if not _blueprint_camera_probe_installed:
        _blueprint_camera_probe_last_slide = None


from .ui_and_commands import (
    _item_card_auto_peer_ab_next_impl,
    _item_card_forced_peer_ab_next_impl,
)


def item_card_auto_peer_ab_next() -> None:
    _item_card_auto_peer_ab_next_impl(_item_card_state)


def item_card_forced_peer_ab_next() -> None:
    _item_card_forced_peer_ab_next_impl(
        _item_card_state,
        _get_runtime=_get_runtime,
        _item_card_select=_item_card_select,
        _item_card_active_gate2_actors=_item_card_active_gate2_actors,
    )


from .ui_and_commands import _emit_gameplay_debug_state


@keybind(
    "Dump Gameplay Debug State",
    "F10",
    display_name="Dump Gameplay Debug State",
)
def dump_gameplay_debug_state() -> None:
    from . import ground_slam_distance
    logging.info(f'[BL4ThirdPersonPOC.SlamDistance] {ground_slam_distance.snapshot(sys.modules[__name__])}')
    from . import camera_height_capture

    if camera_height_capture.trigger(sys.modules[__name__]):
        return
    from .omni import profiler

    if profiler.trigger(sys.modules[__name__]):
        return
    from . import ads_qa_snapshot

    ads_qa_snapshot.capture(sys.modules[__name__])
    _emit_gameplay_debug_state(
        _reticle_publish_faulted=_reticle_publish_faulted,
        _reticle_publish_counts=_reticle_publish_counts,
        _third_person_enabled=_third_person_enabled,
        _third_person_pushed=_third_person_pushed,
        _ads_active=_ads_active,
        _ads_route=_ads_route,
        _ladder_active=_ladder_active,
        _vehicle_camera_active=_vehicle_camera_active,
        _shop_camera_active=_shop_camera_active,
        _slide_active=_slide_active,
        _slide_camera_recovery_pending=_slide_camera_recovery_pending,
        _slide_camera_recovery_pawn=_slide_camera_recovery_pawn,
        _camera_offset_gate_last=_camera_offset_gate_last,
        _camera_stack_owner=_camera_stack_owner,
        _camera_hotpath_debug=_camera_hotpath_debug,
        _native_patch_quarantine=_native_patch_quarantine,
        _item_card_state=_item_card_state,
        _item_card_hook_counter=_item_card_hook_counter,
        _interaction_prompt_state=_interaction_prompt_state,
        _log_hybrid_ads_debug=_log_hybrid_ads_debug,
        _log_camera_lifecycle_debug=_log_camera_lifecycle_debug,
    )


from .ui_and_commands import (
    _dump_collector_outbound_surface,
    _ui_topology_attr,
    _dump_ui_publish_topology,
)

_MENU_STATE_SLOT = "_bl4_tps_camera_menu_state"
_MENU_UPDATE_HOOK = "bl4_third_person_poc.camera_menu"
_camera_menu_state: dict[str, Any] | None = None


from .ui_and_commands import (
    _menu_widget,
    _menu_text,
    _menu_sized,
    _menu_gap,
    _menu_button,
)


from .ui_and_commands import _menu_close_impl, _menu_open_impl
from .game_hooks import (
    _menu_poll_impl,
    _menu_hook_installed as _menu_hook_installed_impl,
    _menu_hook_remove as _menu_hook_remove_impl,
    _menu_hook_install as _menu_hook_install_impl,
)


def _get_menu_state():
    return _camera_menu_state


def _set_menu_state(state):
    global _camera_menu_state
    _camera_menu_state = state


def _set_sniper_mode(value: bool) -> None:
    sniper_tps_ads.value = value is True
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] SNIPER_MODE_SAVE_FAILED {exc}")
    logging.info(f"[BL4ThirdPersonPOC] SNIPER_MODE tps={sniper_tps_ads.value}")


def _set_ffyl_mode(value: bool) -> None:
    from . import ffyl_strategy_runtime

    # Only acknowledge OFF after owned hooks and camera data are restored.
    requested = value is True
    if not requested and not ffyl_strategy_runtime.shutdown(
        sys.modules[__name__], "menu_disabled"
    ):
        logging.error(
            "[BL4ThirdPersonPOC] FFYL_BETA_DISABLE_REFUSED restoration incomplete"
        )
        return
    tps_ffyl_beta.value = requested
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] FFYL_BETA_SAVE_FAILED {exc}")
    ffyl_strategy_runtime.update(sys.modules[__name__])


def _set_ground_slam_mode(value: bool) -> None:
    from . import ground_slam_camera, ground_slam_distance

    requested = value is True
    if not requested and not ground_slam_distance.shutdown_state(sys.modules[__name__]):
        logging.error('[BL4ThirdPersonPOC] GROUND_SLAM_DISTANCE_DISABLE_REFUSED')
        return
    if not requested and not ground_slam_camera.shutdown("menu_disabled"):
        logging.error(
            "[BL4ThirdPersonPOC] GROUND_SLAM_BETA_DISABLE_REFUSED restoration incomplete"
        )
        return
    tps_ground_slam_beta.value = requested
    try:
        mod.save_settings()
    except Exception as exc:
        logging.warning(f"[BL4ThirdPersonPOC] GROUND_SLAM_BETA_SAVE_FAILED {exc}")
    ground_slam_camera.update(sys.modules[__name__])


def _get_dynamic_motion_enabled():
    return _dynamic_motion_enabled


def _menu_close(reason: str = "command") -> None:
    _menu_close_impl(
        reason,
        _get_menu_state=_get_menu_state,
        _set_menu_state=_set_menu_state,
        _menu_hook_installed=lambda: _menu_hook_installed_impl(
            FIRST_PERSON_ANIM_HOOK, _MENU_UPDATE_HOOK
        ),
        _menu_hook_remove=lambda: _menu_hook_remove_impl(
            FIRST_PERSON_ANIM_HOOK, _MENU_UPDATE_HOOK
        ),
        _MENU_STATE_SLOT=_MENU_STATE_SLOT,
        camera_offset_x=camera_offset_x,
        camera_offset_y=camera_offset_y,
        camera_offset_z=camera_offset_z,
        mod=mod,
    )


def _menu_poll(_obj: Any, _args: Any, _ret: Any, _func: Any) -> None:
    _menu_poll_impl(
        _obj,
        _args,
        _ret,
        _func,
        _get_menu_state=_get_menu_state,
        _third_person_enabled=_third_person_enabled,
        _menu_close=_menu_close,
        _set_dynamic_motion_enabled=_set_dynamic_motion_enabled,
        _get_dynamic_motion_enabled=_get_dynamic_motion_enabled,
        camera_offset_x=camera_offset_x,
        camera_offset_y=camera_offset_y,
        camera_offset_z=camera_offset_z,
    )


def _menu_open() -> None:
    _menu_open_impl(
        _get_menu_state=_get_menu_state,
        _set_menu_state=_set_menu_state,
        _menu_close=_menu_close,
        _menu_poll=_menu_poll,
        _menu_hook_install=lambda callback: _menu_hook_install_impl(
            FIRST_PERSON_ANIM_HOOK, _MENU_UPDATE_HOOK, callback
        ),
        _menu_camera_update_ready=lambda: (
            not has_hook(
                FIRST_PERSON_ANIM_HOOK, Type.POST_UNCONDITIONAL, _MENU_UPDATE_HOOK
            )
            and has_hook(FIRST_PERSON_ANIM_HOOK, Type.POST, HOOK_IDENTIFIER)
        ),
        _MENU_STATE_SLOT=_MENU_STATE_SLOT,
        _third_person_enabled=_third_person_enabled,
        _get_dynamic_motion_enabled=_get_dynamic_motion_enabled,
        motion_parameters=_dynamic_motion_parameters,
        save_motion=lambda: _save_dynamic_motion_choice(_dynamic_motion_enabled),
        reset_motion=_dynamic_motion_reset,
        get_sniper_mode=lambda: sniper_tps_ads.value is True,
        set_sniper_mode=_set_sniper_mode,
        get_ffyl_mode=lambda: tps_ffyl_beta.value is True,
        set_ffyl_mode=_set_ffyl_mode,
        camera_features=_camera_feature_options,
        vehicle_options=(vehicle_offset_x, vehicle_offset_y, vehicle_offset_z),
        get_vehicle_control=lambda: vehicle_camera_relative_drive.value is True,
        set_vehicle_control=_set_vehicle_control,
        get_omni_movement=lambda: omni_movement_experimental.value is True,
        set_omni_movement=_set_omni_movement,
        omni_movement_caption=_omni_movement_caption,
        get_hybrid_ads=lambda: HYBRID_ADS_AVAILABLE and omni_hybrid_ads.value is True,
        set_hybrid_ads=_set_omni_hybrid_ads,
        debug_actions={
            "perf": lambda: perf_probe_toggle(None),
            "slide_perf": lambda: slide_perf_probe_toggle(None),
            "camera": _dump_camera_state_impl,
            "slide": dump_slide_state,
            "gameplay": dump_gameplay_debug_state,
            "repair": lambda: _repair_third_person(automatic=False),
        },
        debug_status=lambda: {
            "perf": "REPORT" if _perf_probe.get("complete") else "STOP / REPORT" if _perf_probe.get("armed") else "START",
            "slide_perf": "STOP / REPORT" if _slide_perf_probe.get("armed") else "START",
        },
        get_ground_slam_mode=lambda: tps_ground_slam_beta.value is True,
        set_ground_slam_mode=_set_ground_slam_mode,
        camera_offset_x=camera_offset_x,
        camera_offset_y=camera_offset_y,
        camera_offset_z=camera_offset_z,
    )


@keybind("Open TPS Menu", "F7", display_name="Open/Close TPS Menu")
def toggle_camera_settings_menu() -> None:
    try:
        _menu_open()
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_FAILED {type(exc).__name__}: {exc}")


@command("bl4tps_menu", description="Open/close TPS camera settings menu")
def open_camera_settings_menu(_args: Any) -> None:
    try:
        _menu_open()
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] MENU_FAILED {type(exc).__name__}: {exc}")


@command(
    "bl4tps_debug",
    description="Dump BL4 Third Person gameplay debug state",
)
def dump_gameplay_debug_console(_args: Any) -> None:
    dump_gameplay_debug_state.callback()


@command(
    "bl4tps_itemcard_diag",
    description="Toggle TPS item-card selection for hitch diagnosis",
)
def toggle_item_card_diagnostic(_args: Any) -> None:
    global _item_card_diagnostic_enabled
    _item_card_diagnostic_enabled = not _item_card_diagnostic_enabled
    _update_item_card_fusion()
    logging.info(
        "[BL4ThirdPersonPOC] ITEM_CARD_DIAG " f"enabled={_item_card_diagnostic_enabled}"
    )


@command(
    "bl4tps_collector_surface",
    description="Dump read-only WeaponStatus collector outbound UI surface",
)
def dump_collector_outbound_surface_console(_args: Any) -> None:
    _dump_collector_outbound_surface()


@command(
    "bl4tps_ui_publish_topology",
    description="Dump read-only WeaponStatus to Cohtml UI publish topology",
)
def dump_ui_publish_topology_console(_args: Any) -> None:
    _dump_ui_publish_topology()


@command(
    "bl4tps_omni",
    description=(
        "Omnidirectional movement: on | off | status | report | diag on|off | "
        "hybrid on|off|status | profile total|detail [label]|stop|status"
    ),
)
def omni_movement_console(args: Any) -> None:
    from . import hybrid_ads, omni

    owner = sys.modules[__name__]
    action = args.action
    try:
        if action == "on":
            _set_omni_movement(True)
        elif action == "off":
            _set_omni_movement(False)
        elif action == "report":
            path = omni.save_report(owner, "CONSOLE_REPORT")
            logging.info(f"[BL4ThirdPersonPOC] OMNI_REPORT json={path}")
        elif action == "profile":
            from .omni import profiler

            if args.value in ("total", "detail"):
                from . import camera_height_capture

                if camera_height_capture.status(owner)['state'] != 'off':
                    raise RuntimeError('Stop the height capture before arming the Omni profiler')
                profiler.arm(owner, args.value, args.extra or "idle")
            elif args.value == "stop":
                profiler.cancel(owner)
            elif args.value not in (None, "status"):
                raise ValueError("usage: bl4tps_omni profile total|detail [label]|stop|status")
            logging.info(f"[BL4ThirdPersonPOC] OMNI_PROFILE {profiler.status(owner)}")
            return
        elif action == "diag":
            if args.value not in ("on", "off"):
                logging.info("[BL4ThirdPersonPOC] usage: bl4tps_omni diag on|off")
                return
            _set_omni_diagnostics(args.value == "on")
        elif action == "hybrid":
            if args.value in ("on", "off"):
                _set_omni_hybrid_ads(args.value == "on")
            elif args.value == "zoom":
                logging.info("[BL4ThirdPersonPOC] Hybrid zoom uses the ADS ZOOM menu; no separate zoom cap")
            elif args.value not in (None, "status"):
                logging.info(
                    "[BL4ThirdPersonPOC] usage: bl4tps_omni hybrid on|off|status"
                )
            logging.info(f"[BL4ThirdPersonPOC] OMNI_HYBRID_ADS {hybrid_ads.status(owner)}")
            return
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] OMNI_COMMAND_FAILED {type(exc).__name__}: {exc}")
    logging.info(
        "[BL4ThirdPersonPOC] OMNI_STATUS "
        f"option={omni_movement_experimental.value is True} "
        f"diagnostics_option={omni_movement_diagnostics.value is True} "
        f"hybrid_ads={hybrid_ads.status(owner)} "
        f"{omni.status(owner)}"
    )


omni_movement_console.add_argument(
    "action", nargs="?", default="status",
    choices=("on", "off", "status", "report", "diag", "hybrid", "profile"),
)
omni_movement_console.add_argument("value", nargs="?", default=None)
omni_movement_console.add_argument("extra", nargs="?", default=None)


@command("bl4tps_root_height", description="Grounded body height QA: on | off | status")
def root_height_console(args: Any) -> None:
    if args.action in ('on', 'off'):
        _set_root_height_enabled(args.action == 'on')
    logging.info(f'[BL4ThirdPersonPOC.RootHeight] {root_height.snapshot(sys.modules[__name__])}')


root_height_console.add_argument('action', nargs='?', default='status', choices=('on','off','status'))


@command("bl4tps_height", description="Camera height diagnostics: arm [label] | off | status; F10 starts/stops")
def camera_height_console(args: Any) -> None:
    from . import camera_height_capture

    owner = sys.modules[__name__]
    try:
        if args.action == 'arm':
            camera_height_capture.arm(owner, args.label or 'height')
        elif args.action == 'off':
            camera_height_capture.shutdown(owner)
        logging.info(f'[BL4ThirdPersonPOC.Height] {camera_height_capture.status(owner)}')
    except Exception as exc:
        logging.error('[BL4ThirdPersonPOC.Height] COMMAND_FAILED '+repr(exc))


camera_height_console.add_argument('action', nargs='?', default='status', choices=('arm','off','status'))
camera_height_console.add_argument('label', nargs='?', default=None)


# Hidden event keybinds that follow the game's configured action keys.
# (role, device, keybind); see action_keys.ROLE_ACTIONS for confirmed assets.
_ACTION_KEY_BINDINGS = (
    ("ads", "kbm", first_person_ads_mouse_input),
    ("ads", "gamepad", first_person_ads_controller_input),
    ("interact", "kbm", tps_interaction_keyboard_input),
    ("interact", "gamepad", tps_interaction_controller_input),
)


@command(
    "bl4tps_actions",
    description="List game input actions with their configured keys and the keybind sync state",
)
def dump_input_actions_console(args: Any) -> None:
    from . import action_keys

    try:
        pc = _get_runtime()[0]
        player_input = None if pc is None else getattr(pc, "PlayerInput", None)
        if player_input is None:
            logging.info("[BL4ThirdPersonPOC] ACTIONS unavailable: load into gameplay first")
        elif getattr(args, "scope", None) == "all":
            listing = action_keys.list_all_mappings(player_input)
            logging.info(f"[BL4ThirdPersonPOC] ACTIONS_ALL mappings={listing['count']}")
            for path, keys in listing["actions"].items():
                logging.info(f"[BL4ThirdPersonPOC] ACTION_PATH {path}: {', '.join(keys)}")
        else:
            listing = action_keys.list_actions(player_input)
            logging.info(f"[BL4ThirdPersonPOC] ACTIONS root={listing['root']}")
            for asset, keys in listing["actions"].items():
                logging.info(f"[BL4ThirdPersonPOC] ACTION {asset}: {', '.join(keys)}")
        if player_input is not None:
            # Sync now so the report reflects the mappings that are applied
            # at this moment (Action_Use exists only near interactables).
            try:
                skipped = action_keys.sync_now(player_input)
            except Exception as exc:
                skipped = f"{type(exc).__name__}: {exc}"
            if skipped is not None:
                logging.info(f"[BL4ThirdPersonPOC] ACTION_KEY_SYNC_NOW skipped={skipped}")
        logging.info(f"[BL4ThirdPersonPOC] ACTION_KEY_SYNC {action_keys.report()}")
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] ACTIONS_FAILED {type(exc).__name__}: {exc}")


dump_input_actions_console.add_argument("scope", nargs="?", default=None, choices=("all",))


from .game_hooks import _install_hooks_impl, _remove_hooks_impl


def _install_hooks() -> None:
    _install_hooks_impl(
        _hooks_installed=_hooks_installed,
        _remove_hooks=_remove_hooks,
        FIRST_PERSON_ANIM_HOOK=FIRST_PERSON_ANIM_HOOK,
        HOOK_IDENTIFIER=HOOK_IDENTIFIER,
        _camera_update_hook=_camera_update_hook,
    )


def _remove_hooks() -> None:
    _remove_hooks_impl(
        _hooks_installed=_hooks_installed,
        HOOK_IDENTIFIER=HOOK_IDENTIFIER,
    )


from .game_hooks import _purge_mod_sdk_hooks_impl


def _purge_mod_sdk_hooks(*, include_prompt: bool) -> None:
    return _purge_mod_sdk_hooks_impl(
        include_prompt=include_prompt, owner_module=sys.modules[__name__]
    )


from .game_hooks import _on_enable_impl


def _on_enable() -> None:
    return _on_enable_impl(owner_module=sys.modules[__name__])


from .game_hooks import _on_disable_impl


def _on_disable() -> None:
    from . import hybrid_ads, shoulder_blend
    shoulder_blend.reset()
    hybrid_ads.reset(sys.modules[__name__])
    return _on_disable_impl(owner_module=sys.modules[__name__])


@command(
    "bl4tps_build",
    description="Show the detected game build, store and whether native features may run",
)
def report_build_gate_console(_args: Any) -> None:
    from . import build_gate

    try:
        gate = build_gate.status(sys.modules[__name__])
        logging.info(
            "[BL4ThirdPersonPOC] BUILD_GATE "
            f"reviewed={gate['reviewed']} label={gate['label']!r} {build_gate.summary(gate)}"
        )
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] BUILD_GATE_FAILED {type(exc).__name__}: {exc}")


@command(
    "bl4tps_weapon_probe",
    description="Record the equipped weapon's native fire/aim path (read-only); 'live' also calls the two camera aim getters once",
)
def weapon_probe_console(args: Any) -> None:
    from . import native_weapon_probe

    try:
        live = getattr(args, "mode", None) == "live"
        report, path = native_weapon_probe.run(sys.modules[__name__], live=live)
        fire, summary = report["fire"], report["summary"]
        logging.info(
            "[BL4ThirdPersonPOC] WEAPON_PROBE "
            f"weapon={report['weapon'].get('name')!r} fire_class={fire['cls']!r} "
            f"firebeam={fire['is_measured_firebeam']} overrides={summary['override_slots']} "
            f"functions={summary['functions']} camera_cache_readers={len(summary['camera_cache_readers'])} "
            f"holder={report['holder'].get('matches')} holder_functions={summary['holder_functions']} "
            f"holder_camera_cache_readers={len(summary['holder_camera_cache_readers'])} "
            f"aim_provider={report['aim_provider'].get('matches')} "
            f"aim_target={report['aim_provider'].get('aim_target')} "
            f"errors={len(report['errors'])}"
        )
        if "live_aim" in report:
            aim = report["live_aim"]
            logging.info(
                "[BL4ThirdPersonPOC] WEAPON_PROBE_LIVE "
                + (
                    f"valid={aim['valid']} target_distance={aim['target_distance']:.1f} "
                    f"target_depth={aim['target_depth']:.1f} pawn_depth={aim['pawn_depth']:.1f} "
                    f"target_in_front_of_pawn={aim['target_in_front_of_pawn']}"
                    if "target" in aim else str(aim)
                )
            )
        logging.info(f"[BL4ThirdPersonPOC] WEAPON_PROBE_SAVED {path}")
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] WEAPON_PROBE_FAILED {type(exc).__name__}: {exc}")


@command(
    "bl4tps_native_dump",
    description="Read-only: save code windows at RVAs (hex) for offline analysis",
)
def native_dump_console(args: Any) -> None:
    from . import native_weapon_probe

    try:
        rvas = [int(value, 16) for value in args.rva]
        report, path = native_weapon_probe.run_dump(sys.modules[__name__], rvas, int(args.length, 16))
        logging.info(f"[BL4ThirdPersonPOC] NATIVE_DUMP windows={len(report['windows'])} saved={path}")
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] NATIVE_DUMP_FAILED {type(exc).__name__}: {exc}")


weapon_probe_console.add_argument("mode", nargs="?", default=None, choices=("live",))
native_dump_console.add_argument("rva", nargs="+")
native_dump_console.add_argument("--length", default="0x800")


@command(
    "bl4tps_aim",
    description=(
        "TPS aim trace and beam query start at character depth: "
        "status | on | off | margin <cm> | beam_margin <cm>"
    ),
)
def aim_origin_console(args: Any) -> None:
    from . import native_aim_origin

    owner = native_aim_origin.owner()
    if owner is None:
        logging.info("[BL4ThirdPersonPOC] AIM_TRACE not running")
        return
    try:
        if args.action == "on":
            owner.wanted = True
        elif args.action == "off":
            owner.wanted = False
        elif args.action == "margin":
            margin = float(args.value)
            if not 0.0 <= margin <= 200.0:
                raise ValueError("margin must be 0..200 cm")
            owner.margin = margin
        elif args.action == "beam_margin":
            margin = float(args.value)
            if not 0.0 <= margin <= 200.0:
                raise ValueError("beam_margin must be 0..200 cm")
            owner.beam_margin = margin
        logging.info(f"[BL4ThirdPersonPOC] AIM_TRACE {owner.status()}")
    except Exception as exc:
        logging.error(f"[BL4ThirdPersonPOC] AIM_TRACE_FAILED {type(exc).__name__}: {exc}")


aim_origin_console.add_argument(
    "action",
    nargs="?",
    default="status",
    choices=("status", "on", "off", "margin", "beam_margin"),
)
aim_origin_console.add_argument("value", nargs="?", default=None)


_MOD_KEYBINDS = (
    toggle_third_person,
    controller_r3_camera_toggle,
    swap_shoulder,
    toggle_camera_settings_menu,
    repair_third_person,
    first_person_ads_mouse_input,
    first_person_ads_controller_input,
    tps_interaction_keyboard_input,
    tps_interaction_controller_input,
    dump_camera_state,
    dump_slide_state,
    dump_gameplay_debug_state,
)

_MOD_COMMANDS = (
    open_camera_settings_menu,
    weapon_probe_console,
    native_dump_console,
    aim_origin_console,
    perf_probe_toggle,
    slide_perf_probe_toggle,
    toggle_native_correction,
    enable_early_second_wind_handoff,
    ffyl_early_auto_toggle,
    report_native_correction_status,
    toggle_item_card_diagnostic,
    dump_gameplay_debug_console,
    dump_collector_outbound_surface_console,
    dump_ui_publish_topology_console,
    omni_movement_console,
    camera_height_console,
    root_height_console,
    dump_input_actions_console,
    report_build_gate_console,
)

# On an unreviewed build the loader installs nothing and switches off every
# entry point that would act on the game; only the build report stays usable.
_BUILD_GATE_ALLOWED_COMMANDS = (report_build_gate_console,)


mod = build_mod(
    name="BL4 Third Person PoC",
    author="Maxunit & Kira",
    version=MOD_VERSION,
    description="Third-person shoulder camera with weapon-aware ADS, configurable offsets and motion, optional third-person FFYL and Ground Slam, and experimental omnidirectional movement.",
    supported_games=Game.BL4,
    keybinds=list(_MOD_KEYBINDS),
    commands=list(_MOD_COMMANDS),
    options=[
        _camera_feature_options['global'],
        _camera_feature_options['shoulder'],
        *[option for pair in _camera_feature_options['categories'].values() for option in pair],
        vehicle_camera_relative_drive,
        omni_movement_experimental,
        omni_movement_diagnostics,
        omni_hybrid_ads,
        vehicle_offset_x,
        vehicle_offset_y,
        vehicle_offset_z,
        camera_offset_x,
        camera_offset_y,
        camera_offset_z,
        dynamic_motion_camera_enabled,
        root_height_enabled,
        sniper_tps_ads,
        tps_ffyl_beta,
        tps_ground_slam_beta,
        ground_slam_distance_cm,
        KeybindOption.from_keybind(toggle_third_person),
        KeybindOption.from_keybind(swap_shoulder),
        KeybindOption.from_keybind(toggle_camera_settings_menu),
        KeybindOption.from_keybind(repair_third_person),
        KeybindOption.from_keybind(dump_camera_state),
        KeybindOption.from_keybind(dump_slide_state),
        KeybindOption.from_keybind(dump_gameplay_debug_state),
    ],
    on_enable=_on_enable,
    on_disable=_on_disable,
)
