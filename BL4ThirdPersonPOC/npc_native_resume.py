"""Release the NPC PRE handoff on observed ServerUseObject completion.

No timeout: nested local uses are paired by PRE/POST tokens. Camera settle,
mode, stack/Look ownership and all other rearm checks remain in native_lifecycle.
"""

from unrealsdk.hooks import Type, add_hook, has_hook, remove_hook
from unrealsdk import logging

IDENTIFIER = "BL4ThirdPersonPOC.NPCNativeUseCompleted"
TAG = "[BL4ThirdPersonPOC]"


def reset(mod):
    mod._native_npc_pending = False
    mod._native_npc_context = None
    mod._native_npc_calls = []


def begin(mod, obj):
    """Track the local controller's PRE use token, including nested non-NPC calls."""
    if not getattr(mod, "_native_npc_post_installed", False):
        return
    # Track every local use, so nested non-NPC uses cannot release an outer NPC.
    pc, _, _ = mod._get_runtime()
    if pc is None or mod._object_address(obj) != mod._object_address(pc):
        return
    mod._native_npc_calls.append((mod._object_address(obj), object()))


def arm(mod, obj):
    """Hold native rearm until the matching outer NPC use token completes."""
    mod._native_npc_pending = True
    calls = getattr(mod, "_native_npc_calls", [])
    if not calls or calls[-1][0] != mod._object_address(obj):
        mod._native_npc_context = None  # Hold rather than assume completion.
        logging.error(
            f"{TAG} NPC_NATIVE_USE_UNPAIRED; native held until camera mode change"
        )
        return
    mod._native_npc_context = dict(pc=calls[-1][0], token=calls[-1][1], completed=False)


def ended(mod, obj):
    """Complete only the matching local PRE token observed by POST_UNCONDITIONAL."""
    calls = getattr(mod, "_native_npc_calls", [])
    if not calls or calls[-1][0] != mod._object_address(obj):
        return
    _, token = calls.pop()
    context = getattr(mod, "_native_npc_context", None)
    if context is not None and context["token"] is token:
        context["completed"] = True
        logging.info(f"{TAG} NPC_NATIVE_USE_COMPLETED awaiting_settled_camera=True")


def ready(mod, pc, camera, pawn):
    """Release a paired completed use only after observed settled TPS.

    This does not authorize native activation; the remaining camera/weapon/
    recoil/schema gates run afterward. There is no timeout-based completion.
    """
    if not mod._native_npc_pending:
        return True
    mode = str(camera.GetActorCameraMode(pawn))
    if not mod._third_person_enabled or mode != "ThirdPerson":
        mod._native_npc_pending = False
        mod._native_npc_context = None
        return True  # Normal non-TPS eligibility still rejects rearm.
    context = getattr(mod, "_native_npc_context", None)
    if context is None or not context["completed"]:
        return False
    if context["pc"] != mod._object_address(pc):
        reset(mod)
        logging.info(
            f"{TAG} NPC_NATIVE_HANDOFF_RELEASED reason=local_controller_changed"
        )
        return True
    if camera.CameraModeState.bIsTransitioning or mod._camera_lifecycle.get("pending"):
        return False
    mod._native_npc_pending = False
    mod._native_npc_context = None
    logging.info(f"{TAG} NPC_NATIVE_HANDOFF_RELEASED reason=use_completed_settled_tps")
    return True  # Remaining native owner/schema/collision/view/ADS gates run next.


def shutdown(mod):
    mod._native_npc_post_installed = False
    if has_hook(mod.SERVER_USE_OBJECT_FUNCTION, Type.POST_UNCONDITIONAL, IDENTIFIER):
        remove_hook(mod.SERVER_USE_OBJECT_FUNCTION, Type.POST_UNCONDITIONAL, IDENTIFIER)
    if has_hook(mod.SERVER_USE_OBJECT_FUNCTION, Type.POST_UNCONDITIONAL, IDENTIFIER):
        raise RuntimeError("NPC completion hook remains registered")
    reset(mod)


def install(mod):
    shutdown(mod)
    if not mod._interaction_redirect_installed:
        logging.error(f"{TAG} NPC_NATIVE_COMPLETION_UNAVAILABLE missing PRE hook")
        return

    def post(obj, args, ret, func):
        try:
            ended(mod, obj)
        except Exception as exc:
            logging.error(
                f"{TAG} NPC_NATIVE_COMPLETION_ERROR {type(exc).__name__}: {exc}"
            )

    try:
        add_hook(
            mod.SERVER_USE_OBJECT_FUNCTION, Type.POST_UNCONDITIONAL, IDENTIFIER, post
        )
        mod._native_npc_post_installed = has_hook(
            mod.SERVER_USE_OBJECT_FUNCTION, Type.POST_UNCONDITIONAL, IDENTIFIER
        )
        logging.info(
            f"{TAG} NPC_NATIVE_COMPLETION_HOOK installed={mod._native_npc_post_installed}"
        )
    except Exception as exc:
        logging.error(
            f"{TAG} NPC_NATIVE_COMPLETION_UNAVAILABLE {type(exc).__name__}: {exc}"
        )
