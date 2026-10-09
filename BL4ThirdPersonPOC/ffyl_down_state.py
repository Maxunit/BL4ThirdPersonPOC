"""Bind DownState notifications through their live UObject Outer, never a scan.

OnDownedEnded exposes bIsLocal and reason in the recorded reflection schema.
Locality alone does not identify one split-screen controller. Require the live
collector's direct Outer to be our serial-validated controller as well. Unsupported
collector layouts fail closed; no guessed offset or global singleton fallback.
"""

DOWN_STATE_CLASS = "/Script/OakGame.OakUIDataCollector_DownState"


def bind_local_down_state(mod, *, weak_pointer):
    """Create a predicate for one current controller/pawn/manager lifetime.

    The recorded DownState inventory confirms a direct local controller Outer.
    Revalidate that relationship for every notification; never reuse a snapshot
    address as permission. Pawn and manager lifetimes remain part of the binding.
    """
    objects = mod._get_runtime()
    if len(objects) != 3 or any(obj is None for obj in objects):
        raise RuntimeError("Local DownState runtime unavailable")
    identity = tuple(int(obj._get_address()) for obj in objects)
    references = tuple(weak_pointer(obj) for obj in objects)

    def is_local(collector, args):
        if collector is None or getattr(args, "bIsLocal", None) is not True:
            return False
        if str(collector.Class._path_name()) != DOWN_STATE_CLASS:
            return False
        current = mod._get_runtime()
        bound = tuple(ref() for ref in references)
        if (
            len(current) != 3
            or any(obj is None for obj in (*current, *bound))
            or tuple(int(obj._get_address()) for obj in current) != identity
            or tuple(int(obj._get_address()) for obj in bound) != identity
        ):
            raise RuntimeError("Bound DownState runtime lifetime changed")
        outer = collector.Outer
        if outer is None or int(outer._get_address()) != identity[0]:
            return False
        # Serial/lifetime validation also covers the actual Outer wrapper.
        outer_ref = weak_pointer(outer)
        live_outer = outer_ref()
        return live_outer is not None and int(live_outer._get_address()) == identity[0]

    return is_local
