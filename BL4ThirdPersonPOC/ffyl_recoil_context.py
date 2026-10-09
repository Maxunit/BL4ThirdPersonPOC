"""Bind FFYL recoil permissions to serial-checked local UObject lifetimes.

The selected camera owner captures the observed lower FFYL stack entry and
passes this explicit context to recoil. Capture double-reads the bounded manager
snapshot; the caller must first validate its build/schema. Raw addresses alone
cannot authorize access after respawn or reuse. Revocation stops activation but
keeps restoration evidence while lifetimes remain valid. Unknown lifetimes refuse
both operations; the cleanup coordinator retains native buffers on uncertainty.
"""

import struct
from types import MappingProxyType


def _validate_lifetimes(identity, references):
    if (
        len(identity) != 3
        or not all(identity)
        or len(references) != 3
        or not all(callable(ref) for ref in references)
    ):
        raise RuntimeError("Incomplete FFYL recoil lifetime binding")
    objects = tuple(ref() for ref in references)
    if any(obj is None for obj in objects) or tuple(
        int(obj._get_address()) for obj in objects
    ) != tuple(identity):
        raise RuntimeError("FFYL recoil UObject lifetime changed")


class BoundFFYLRecoilContext:
    """Observed lower FFYL entry plus references to controller, pawn and manager."""

    def __init__(self, identity, references, lower_entry):
        if (
            len(identity) != 3
            or not all(identity)
            or len(references) != 3
            or not all(callable(ref) for ref in references)
            or len(lower_entry) != 40
        ):
            raise RuntimeError("Incomplete FFYL recoil lifetime binding")
        self._identity = tuple(identity)
        self._references = tuple(references)
        self._lower_entry = bytes(lower_entry)
        self._activation_allowed = True

    def proof_context(self, *, for_restore=False):
        """Revalidate UObject serials before exposing the captured proof inputs.

        Restoration permission is not activation permission. The caller must use
        the restore-only selector for a retained lower TPS runtime. Live stack,
        Look and native code validation remain separate required checks.
        """
        if not for_restore and not self._activation_allowed:
            raise RuntimeError("FFYL recoil activation has been revoked")
        _validate_lifetimes(self._identity, self._references)
        return MappingProxyType(
            {"manager": self._identity[2], "lower_entry": self._lower_entry}
        )

    def validate_activation_runtime(self, controller, pawn, manager):
        """Require the bound lifetime to still be the current local gameplay tuple."""
        objects = (controller, pawn, manager)
        if (
            any(obj is None for obj in objects)
            or tuple(int(obj._get_address()) for obj in objects) != self._identity
        ):
            raise RuntimeError("FFYL recoil is not bound to current local gameplay")
        self.proof_context()

    def revoke_activation(self):
        """Stop new activation before attempting native restoration; idempotent."""
        self._activation_allowed = False


def capture_ffyl_recoil_context(controller, pawn, manager, *, weak_pointer, read):
    """Capture the unique active FFYL stack entry without changing the camera.

    The measured manager layout is specific to the validated game build. The
    caller must run its build/schema guard BEFORE entering this function. Header
    and bounded stack bytes are read twice to reject a changing snapshot; this is
    not a cross-thread barrier. Serial-checked references are checked before and
    after capture. Any read failure or ambiguity propagates without publication.
    """
    objects = (controller, pawn, manager)
    identity = tuple(int(obj._get_address()) for obj in objects)
    references = tuple(weak_pointer(obj) for obj in objects)
    # Validate lifetimes before reading from the captured manager address.
    _validate_lifetimes(identity, references)
    header_address = identity[2] + 0x39A8
    before = read(header_address, 0xB0)
    if len(before) != 0xB0:
        raise RuntimeError("Incomplete FFYL manager snapshot")
    data, count, capacity = struct.unpack_from("<Qii", before, 0x18)
    if not 1 <= count <= capacity <= 256 or count > 64 or data < 0x10000:
        raise RuntimeError("FFYL stack outside bounded capture")
    raw = read(data, count * 40)
    if len(raw) != count * 40:
        raise RuntimeError("Incomplete FFYL stack snapshot")
    matches = [
        raw[i : i + 40]
        for i in range(0, len(raw), 40)
        if raw[i + 24 : i + 40] == before[0xA0:0xB0]
        and raw[i : i + 8] == before[0x88:0x90]
    ]
    if (
        len(matches) != 1
        or str(manager.GetActorCameraMode(pawn)) != "FFYL"
        or read(header_address, 0xB0) != before
        or read(data, len(raw)) != raw
    ):
        raise RuntimeError("FFYL lower layer capture changed")
    _validate_lifetimes(identity, references)
    return BoundFFYLRecoilContext(identity, references, matches[0])


def resolve_ffyl_recoil_context(saved_state, requested_context):
    """Use an active owner's binding for restore; never silently replace it.

    Inactive old state carries no activation permission. New activation requires
    an explicit context from the local FFYL owner. Supplying a context while an
    unrelated normal recoil owner is active is refused before stack selection.
    """
    if saved_state is not None and getattr(saved_state, "active", False):
        owned_context = getattr(saved_state, "ffyl_recoil_context", None)
        if requested_context is not None and requested_context is not owned_context:
            raise RuntimeError("Active recoil FFYL context cannot be replaced")
        return owned_context
    return requested_context
