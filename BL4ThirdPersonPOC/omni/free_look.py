"""Free Omni AimOffset input; angular fade, no timers or extra SDK getters."""
import math
import struct
from .common import angle

YAW_LIMIT = 35.0
FADE_START = 60.0
FADE_END = 90.0


def pose_input(camera_yaw, actor_yaw):
    if not math.isfinite(camera_yaw) or not math.isfinite(actor_yaw):
        raise RuntimeError('Free-look camera/body yaw is nonfinite')
    relative = angle(camera_yaw, actor_yaw)
    magnitude = abs(relative)
    if magnitude <= FADE_START:
        alpha = 1.0
    elif magnitude >= FADE_END:
        alpha = 0.0
    else:
        t = (magnitude - FADE_START) / (FADE_END - FADE_START)
        alpha = 1.0 - t * t * (3.0 - 2.0 * t)
    yaw = max(-YAW_LIMIT, min(YAW_LIMIT, relative)) * alpha
    return yaw, alpha


def publish(session):
    """Publish after existing body setters, using this callback's sample only.

    Exact-node/caller filters and the lifecycle's normal disable paths stay in
    force. Native pitch is multiplied by alpha, retaining the game's sign and
    pitch input. One aligned uint64 carries both floats, so worker reads do not
    mix independently published yaw and alpha. This is an update snapshot, not
    an atomic observation of the whole camera/actor/animation evaluation.
    """
    aim = session.aim_native
    controls = (aim.control, aim.crouch_control)
    samples = session.report.get('samples', ())
    sample = samples[-1] if samples else None
    if (not session.active or session.combat.get('active', False)
            or getattr(session, 'ground_slam_pose_native', False)
            or (sample is not None and sample.get('combat', {}).get('active', False))):
        for control in controls:
            control[0] = 0
        return
    eligible = (session.free_look_context
                and session.impulse_index is not None
                and session.cycle_start is None and not session.ground_circle_previous_dash
                and sample is not None and sample['update_index'] == session.frames
                and sample['normal_tps_sample'] and not sample['combat']['active']
                and not session.combat['active'])
    if not eligible:
        # Retain .32's free special-movement behavior; never reopen a closed gate.
        for control in controls:
            if control[0] == 2:
                control[0] = 1
        return
    actor = sample['actor_rotation']
    if 'crouch_follow' in sample:
        actor = sample['crouch_follow']['actor_after']
    elif 'follow' in sample:
        actor = sample['follow']['immediate_actor_rotation']
    try:
        yaw, alpha = pose_input(sample['camera_rotation']['Yaw'], actor['Yaw'])
        packed = struct.unpack('<Q', struct.pack('<ff', yaw, alpha))[0]
    except Exception:
        for control in controls:
            control[0] = 0
        raise
    for control in controls:
        if control[0] in (1, 2):
            control[5] = packed
            control[0] = 2
    if session.collect_pose_diagnostics:
        sample['free_look'] = dict(yaw_input=yaw, pitch_alpha=alpha,
                                   camera_yaw=sample['camera_rotation']['Yaw'],
                                   actor_yaw=actor['Yaw'])
