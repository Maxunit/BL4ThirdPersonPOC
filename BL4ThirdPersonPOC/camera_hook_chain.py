"""One native detour per camera entry, with independently removable feature stubs.
All registration/removal occurs on the game thread. Aligned pointer relays keep
original registers/stack intact; retired code and its Python pins remain alive.
"""

import ctypes
import struct

_roots = {}
_retired = []


def _relay(destination):
    # qword at offset 16 is aligned; FF25 skips ten bytes of padding.
    return b"\xff\x25\x0a\x00\x00\x00" + b"\x90" * 10 + struct.pack("<Q", destination)


def _link(address, destination):
    if address % 8:
        raise RuntimeError("Unaligned camera chain relay")
    ctypes.c_uint64.from_address(address).value = destination


def original_read(mod, address, size):
    """Read validated original bytes through this module's owned entry detours.

    Foreign changes are rejected before substituting an original instruction
    window. This is evidence for consumers, not permission to overwrite code.
    """
    data = mod._native_read(address, size)
    for target, root in _roots.items():
        original = root["hook"]["original"]
        if address < target + len(original) and target < address + size:
            verify(mod, root["hook"])
            start, end = max(address, target), min(
                address + size, target + len(original)
            )
            data = (
                data[: start - address]
                + original[start - target : end - target]
                + data[end - address :]
            )
    return data


def verify(mod, hook):
    root = _roots.get(hook["target"])
    if root is None:
        if mod._native_read(hook["target"], len(hook["original"])) != hook["original"]:
            raise RuntimeError("Camera entry restoration differs")
    elif (
        mod._native_read(hook["target"], len(root["hook"]["patch"]))
        != root["hook"]["patch"]
    ):
        raise RuntimeError("Shared camera entry changed outside ownership")
    return True


def _relink(root):
    destination = root["hook"]["trampoline"]
    for item in reversed(root["items"]):
        _link(item["relay_slot"], destination)
        destination = item["stub"]
    _link(root["entry_slot"], destination)


def allocate(mod, target, original, length, builder, label):
    """Publish a feature consumer beneath one shared native entry owner.

    The builder returns pins, control and audited code. Relays use aligned qword
    slots; consumers must register/remove on the game thread. A failure retains
    allocated executable storage and any pins instead of recycling a live page.
    """
    root = _roots.get(target)
    created = root is None
    if created:

        def root_builder(stub, trampoline):
            return None, None, _relay(trampoline)

        native = mod._native_allocate_hook(
            target, original, length, root_builder, "Shared camera entry"
        )
        root = {"hook": native, "items": [], "entry_slot": native["stub"] + 16}
        _roots[target] = root
    elif root["hook"]["original"] != original or len(original) != length:
        raise RuntimeError("Camera hook consumers disagree on original entry")
    verify(mod, root["hook"])
    allocation = int(mod._kernel32.VirtualAlloc(None, 0x2000, 0x3000, 0x40) or 0)
    if not allocation:
        if created:
            mod._native_restore_hook(root["hook"])
            mod._native_release_hook(root["hook"])
            _roots.pop(target)
        raise RuntimeError("Camera consumer allocation failed")
    try:
        pins, control, code = builder(allocation, allocation + 0x1800)
        if len(code) >= 0x1800:
            raise RuntimeError("Camera consumer stub exceeds allocation")
        mod._native_write_code(allocation + 0x1800, _relay(root["hook"]["trampoline"]))
        mod._native_write_code(allocation, code)
        item = {
            "target": target,
            "original": original,
            "patch": root["hook"]["patch"],
            "stub": allocation,
            "relay_slot": allocation + 0x1810,
            "buffer": pins,
            "control": control,
            "label": label,
            "restored": False,
        }
        root["items"].append(item)
        _relink(root)
        return item
    except Exception:
        if "item" in locals() and item in root["items"]:
            root["items"].remove(item)
            _relink(root)
        _retired.append((allocation, locals().get("pins"), locals().get("control")))
        if created and not root["items"]:
            mod._native_restore_hook(root["hook"])
            mod._native_release_hook(root["hook"])
            _roots.pop(target)
        raise


def restore(mod, item):
    """Unlink only this registered consumer and verify the shared entry first.

    Other consumers remain linked. The last consumer restores/releases the root
    owner; failure propagates without claiming successful consumer restoration.
    """
    if item["restored"]:
        return
    root = _roots.get(item["target"])
    if root is None or item not in root["items"]:
        raise RuntimeError("Camera consumer ownership missing")
    verify(mod, item)
    remaining = [entry for entry in root["items"] if entry is not item]
    if remaining:
        root["items"] = remaining
        _relink(root)
    else:
        mod._native_restore_hook(root["hook"])
        mod._native_release_hook(root["hook"])
        _roots.pop(item["target"])
    item["restored"] = True


def retire(mod, item):
    """Pin a restored consumer allocation and its backing objects permanently.

    An unlinked consumer may still contain an in-flight native call. No timeout
    or elapsed-time estimate authorizes freeing its executable page.
    """
    if not item["restored"]:
        raise RuntimeError("Cannot retire active camera consumer")
    if item.get("stub"):
        _retired.append((item["stub"], item.get("buffer"), item.get("control")))
        item["stub"] = 0
