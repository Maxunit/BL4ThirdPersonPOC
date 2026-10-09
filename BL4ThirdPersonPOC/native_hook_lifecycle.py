"""Restore owned native code and release hook storage under explicit contracts.

No hook installation, SDK lookup or mutable owner state at import time. Callers
provide their owner module; its existing read/write, retirement and WinAPI
facilities remain authoritative. Published storage keeps its backing references.
"""

from __future__ import annotations

from typing import Any, Callable


def _exchange_owned_bytes(
    read: Callable[[int, int], bytes],
    write: Callable[[int, bytes], None],
    address: int,
    expected: bytes,
    replacement: bytes,
) -> None:
    """Compare, replace and verify a caller-validated native instruction window.

    The caller supplies protection-aware writes, executable/identity checks and
    backing-resource ownership. This is not a cross-thread atomic exchange.
    Roll back only a complete replacement; foreign/partial bytes are retained
    and raise rather than authorizing an overwrite or allocation release.
    """
    if read(address, len(expected)) != expected:
        raise RuntimeError("Patch bytes differ; refusing to overwrite another change")
    try:
        write(address, replacement)
        if read(address, len(replacement)) != replacement:
            raise RuntimeError("Patch readback mismatch")
    except Exception as first:
        # Roll back only a complete expected/replacement state we own.
        current = read(address, len(expected))
        if current == replacement:
            write(address, expected)
        elif current != expected:
            raise RuntimeError(
                "Unrecognized partial bytes; restart the game before continuing"
            ) from first
        raise


def _native_restore_hook_impl(hook: dict[str, Any], *, owner_module) -> None:
    """Restore a shared native hook only over owned bytes, with readback proof.

    This helper also serves interaction and mode guards; it does not relocate
    code or establish executable compatibility for its callers.
    Published stubs are retired separately and keep their backing buffers pinned.
    """
    if hook.get("restored"):
        return
    target = int(hook["target"])
    patch = bytes(hook["patch"])
    original = bytes(hook["original"])
    if not original or len(patch) != len(original):
        raise RuntimeError("Native hook restoration byte lengths differ")
    current = owner_module._native_read(target, len(patch))
    if current == patch:
        owner_module._native_write_code(target, original)
        if owner_module._native_read(target, len(original)) != original:
            raise RuntimeError(f"{hook['label']} restoration readback differs")
    elif current != original:
        raise RuntimeError(
            f"{hook['label']} cleanup refused; bytes changed: " f"{current.hex(' ')}"
        )
    hook["restored"] = True


def _native_release_hook_impl(hook: dict[str, Any], *, owner_module) -> None:
    """Release unpublished allocation or retire published storage with its pins.

    Published storage is never VirtualFree'd here: verified restoration is
    required, and backing references enter the process-lifetime retirement list.
    Only an allocation never attempted at a code site may be freed immediately.
    Historical item-card retirement tags stay unchanged for reload compatibility.
    """
    stub = int(hook.get("stub", 0))
    if not stub:
        return
    if hook.get("patch_attempted"):
        if not hook.get("restored"):
            raise RuntimeError("Cannot retire an unrestored native hook")
        owner_module._retired_native_stubs.append(
            ("item_card", stub, hook.get("buffer"), hook.get("control"))
        )
        hook["stub"] = 0
        return
    if not owner_module._kernel32.VirtualFree(
        owner_module.ctypes.c_void_p(stub),
        0,
        owner_module._MEM_RELEASE,
    ):
        raise OSError(
            owner_module.ctypes.get_last_error(),
            f"{hook['label']} VirtualFree failed",
        )
    hook["stub"] = 0
