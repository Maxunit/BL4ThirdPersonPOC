"""Gameplay visual ownership/schema guards, independent of pose reporting."""
import math


def validate_visual(session, *, capture=False):
    _, pawn, _, _ = session.bound()
    mesh = session.mesh_ref()
    anim = session.anim_ref()
    if mesh is None or pawn.Mesh != mesh:
        raise RuntimeError('Bound visual Mesh changed')
    if (anim is None or int(anim._get_address()) != session.anim_address
            or mesh.AnimScriptInstance != anim):
        raise RuntimeError('Bound animation instance changed')
    values = {} if capture else None
    for name in session.INPUT_NAMES:
        value = getattr(anim, name)
        if not isinstance(value, bool):
            value = float(value)
            if not math.isfinite(value):
                raise RuntimeError('Nonfinite animation input: ' + name)
        if capture:
            values[name] = value
    node = getattr(anim, session.NODE_NAME)
    channel, key = str(node.RotationChannelName.TagName), str(node.BlendSpaceKey.TagName)
    if channel != 'RotationChannel.Aim' or key != 'AnimSet.Player.3rd.AimO_3rd':
        raise RuntimeError('Normal AimOffset configuration changed')
    if not all(math.isfinite(float(v)) for v in (node.ALPHA, node.BlendWeight)):
        raise RuntimeError('Nonfinite AimOffset values')
    # The return is consumed synchronously, never stored on the session.
    return (values, node) if capture else None
