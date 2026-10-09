"""Prove FFYL recoil ownership from a coherent live stack snapshot.

The production recoil entry selects these proofs only for a bound FFYL context
captured by the selected camera owner. The caller serial-checks lifetimes and
retains all build, byte and vtable guards. No SDK call or memory write occurs here.
The upper-TPS selector may authorize activation; the retained lower-TPS selector
authorizes restoration only. Missing or inconsistent evidence raises an error.
Saved owned_definition and owned_lower_entry fields bind restoration proofs
to this build's retained recoil owner. Updates require a full process restart.
"""


def select_ffyl_upper_tps_runtime(
    report, raw, manager_address, saved_state, *, context
):
    """Validate the upper TPS Look over the observed lower FFYL entry.

    Supports initial selection and revalidation of an active recoil owner.
    This proof alone does not authorize writes or replace the native build guard.
    """
    ctx = context
    if not ctx or manager_address != ctx["manager"] or len(raw) != 80:
        raise RuntimeError("Top-TPS bound context or stack differs")
    if report["stack"]["count"] != 2 or raw[:40] != ctx["lower_entry"]:
        raise RuntimeError("Observed lower FFYL entry changed")
    rows = report["runtime_candidates"]
    if len(rows) != 3 or [r["source"] for r in rows] != [
        "stack_0",
        "stack_1",
        "manager_slot_3a48",
    ]:
        raise RuntimeError("Top-TPS runtime snapshot incomplete")
    lower, top, current = rows
    if (
        lower["instance"] == top["instance"]
        or lower["control"] == top["control"]
        or top["instance"] != current["instance"]
        or top["control"] != current["control"]
        or report["mode_fname_hex"] != raw[40:48].hex()
        or raw[:8] == raw[40:48]
        or report.get("mode_name") != "ThirdPerson"
    ):
        raise RuntimeError("Top-TPS current/runtime/descriptor ownership differs")
    if any(
        r.get("transition") != "0x0"
        or r.get("self_reference_matches") is not True
        or r.get("control_matches") is not True
        or r.get("runtime_unchanged") is not True
        for r in rows
    ):
        raise RuntimeError("Top-TPS runtime transitioning or changed")
    definition = report["definitions"].get(top["definition"])
    lower_def = report["definitions"].get(lower["definition"])
    if (
        not definition
        or not lower_def
        or top["definition"] == lower["definition"]
        or definition["fields"]["bIsFirstPerson"]["value"] is not False
        or lower_def["fields"]["bIsFirstPerson"]["value"] is not True
    ):
        raise RuntimeError(
            "Expected separate upper TPS and lower first-person FFYL definitions"
        )
    lower_lists = report["runtime_behavior_lists"][lower["instance"]]
    if not any(
        i.get("type_path") == "/Script/OakGame.CameraModeBehavior_FFYLPitch"
        for row in lower_lists
        for i in row["items"]
    ):
        raise RuntimeError("Lower runtime lacks measured FFYL behavior")
    key = top["instance"]
    candidates = [
        (key, row, item)
        for row in report["runtime_behavior_lists"][key]
        for item in row["items"]
        if item.get("type_path") == "/Script/GbxGame.CameraModeBehavior_Look"
    ]
    if (
        len(candidates) != 1
        or candidates[0][1]["offset"] != "0x20"
        or candidates[0][2]["index"] != 0
    ):
        raise RuntimeError("Expected unique top Look at first pre-view-target entry")
    target = candidates[0][2]
    if saved_state is not None and getattr(saved_state, "active", False):
        identity = (
            manager_address,
            int(key, 16),
            int(target["address"], 16),
            int(target["control"], 16),
        )
        if (
            identity != tuple(saved_state.identity)
            or int(top["control"], 16) != saved_state.runtime_control
            or raw[40:64].hex() != saved_state.stack_descriptor
            or raw[:40].hex() != saved_state.owned_lower_entry
            or int(target["vtable"], 16) != saved_state.shadow_vt
        ):
            raise RuntimeError("Saved upper TPS Look ownership changed")
    return [top, current], [definition], candidates


def select_ffyl_retained_tps_for_restore(
    report, raw, manager_address, saved_state, *, context
):
    """Select a retained TPS owner for restoration after camera replacement.

    No activation and no saved-pointer dereference: the entire runtime and Look
    come from the coherent CURRENT stack snapshot. A disappeared owner refuses.
    """
    identity = tuple(getattr(saved_state, "identity", ()))
    if (
        not context
        or not getattr(saved_state, "active", False)
        or len(identity) != 4
        or identity[0] != manager_address
        or context["manager"] != manager_address
        or report["stack"]["count"] != 2
        or len(raw) != 80
        or raw[:24].hex() != saved_state.stack_descriptor
        or not getattr(saved_state, "owned_definition", None)
    ):
        raise RuntimeError("Retained owned TPS descriptor/owner context differs")
    rows = report["runtime_candidates"]
    if len(rows) != 3 or [r["source"] for r in rows] != [
        "stack_0",
        "stack_1",
        "manager_slot_3a48",
    ]:
        raise RuntimeError("Retained owned runtime snapshot incomplete")
    owner, replacement, current = rows
    if (
        int(owner["instance"], 16) != identity[1]
        or int(owner["control"], 16) != saved_state.runtime_control
        or owner["instance"] == replacement["instance"]
        or owner["control"] == replacement["control"]
        or current["instance"] != replacement["instance"]
        or current["control"] != replacement["control"]
        or report["mode_fname_hex"] != raw[40:48].hex()
        or raw[:8] == raw[40:48]
    ):
        raise RuntimeError("Retained owned TPS/replacement/current references differ")
    if any(
        r.get("self_reference_matches") is not True
        or r.get("control_matches") is not True
        or r.get("runtime_unchanged") is not True
        for r in rows
    ):
        raise RuntimeError("Retained owned runtime identity changed during capture")
    if owner.get("transition") != "0x0":
        raise RuntimeError("Retained owned TPS runtime is transitioning")
    definition = report["definitions"].get(owner["definition"])
    if (
        definition is None
        or int(owner["definition"], 16) != saved_state.owned_definition
        or definition["fields"]["bIsFirstPerson"]["value"] is not False
    ):
        raise RuntimeError("Retained owned TPS definition changed")
    key = owner["instance"]
    candidates = [
        (key, row, item)
        for row in report["runtime_behavior_lists"][key]
        for item in row["items"]
        if item.get("type_path") == "/Script/GbxGame.CameraModeBehavior_Look"
    ]
    if (
        len(candidates) != 1
        or candidates[0][1]["offset"] != "0x20"
        or candidates[0][2]["index"] != 0
        or int(candidates[0][2]["address"], 16) != identity[2]
        or int(candidates[0][2]["control"], 16) != identity[3]
        or int(candidates[0][2]["vtable"], 16) != saved_state.shadow_vt
    ):
        raise RuntimeError("Retained owned private Look owner/vtable changed")
    return [owner], [definition], candidates
