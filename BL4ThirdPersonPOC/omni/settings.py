"""Runtime configuration of the integrated omnidirectional feature.

Gameplay input has no default key table. Diagnostics are an explicit, runtime
switch owned by the loader option ``omni_movement_diagnostics``; the session
reads it once when it binds, so changing it applies on the next session.

Diagnostics ON keeps the lab behaviour: pose/weapon-fire discovery, console
state messages and a JSON report on every stop. Diagnostics OFF (production)
keeps the bounded gameplay state the pipeline itself needs, routes state
messages to developer logging and writes a report only after errors or an
incomplete cleanup.
"""

_state = {'diagnostics': False}


def diagnostics_enabled():
    return bool(_state['diagnostics'])


def set_diagnostics(value):
    _state['diagnostics'] = value is True


# Historical name kept for comparability of existing reports and tests.
# The session reads diagnostics_enabled() instead of this constant.
COLLECT_POSE_DIAGNOSTICS = False
