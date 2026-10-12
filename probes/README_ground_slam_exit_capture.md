# .39 Ground Slam Exit capture

User QA: .39 holds the character correctly during admission and flight, but
GroundSlamExit visibly fights its direction again. This does not establish
whether Actor rotation changes, an animated Root turns against a held Actor,
a pose gate reopens, or the heading hold loses ownership. Record these channels
together before changing native pose suppression again.

1. Keep **0.3.9.39 and Omni enabled**. Stop any other capture/profiler.
2. Put `ground_slam_exit_capture.py` in `sdk_mods` and run:

   ```text
   pyexec ground_slam_exit_capture.py
   ```

3. Close the console, promptly perform one opposite-facing long Slam, and let
   the problematic Exit and TPS return finish. Briefly stand still afterward.
4. Press F10 (or repeat the command) and send `ground_slam_exit_<UTC>.json` from
   `sdk_mods/settings/BL4ThirdPersonPOC_reports`. Its exact path is logged.

This probe accepts .39 only. No new QA build or setting changes are required.
Root/mesh/bone rotations, AimYaw/Pitch and existing SDK rotate-command fields
are sampled at each widget update during GroundSlamExit and the still-owned TPS
return; detail otherwise remains at most 20 Hz. Actor heading and current Omni
controls/counters are recorded each update. A pose gate unexpectedly enabled is
recorded rather than changed or used to abort the capture.

The already installed local movement recorder supplies original requested and
pre-call component quaternions with caller return RVAs. The diagnostic gate is
enabled around normal TPS; the mod retains ownership of Exit recording. Exact
local owner, thread, component, installed patch and bounded allocated buffers
are validated. No new executable patch, producer, timer, actor/animation/camera/
settings writes, or shared-buffer reset. `recorder_gate_writes` are writes to the
existing Python-owned diagnostic recording flag, not behavior controls. Existing
.39 TurnState heading gates, caller selector and Aim/Idle gates are never edited.

One existing widget subscription, maximum 120 seconds / 8000 updates / remaining
capacity of the shared 1024-record buffer. The buffer limit counts native calls,
not frames. Start promptly. If full before arming, a fresh game session is needed.
F10, failure, timeout and shutdown detach the probe and close its recording flag;
production's active Exit recording is preserved. Output can be retried after a
file-writing failure. Cleanup that owns a flag requires the game thread.

SDK reads are sequential, not a rendered-pose or native-call atomic snapshot.
Original requests are recorded before existing Omni argument replacement: they
are not proof of the forwarded rotation or successful application. Cumulative
replacement counts help distinguish blocked attempts but do not attribute each
record to one replacement. Other setters/dispatch paths can bypass this recorder.
`last_widget_update_index` is the legacy production marker, which may be stale in
air. Use the probe interval indices, sample `omni_update`, and observed heading.
Root/torso Euler yaw near vertical pitch is marked as poorly projected. The SDK
rotate command's TargetLocation is stored data, not proof of an active aim target.
Diagnostic overhead is not a performance measurement.

Validation: `python tests/ground_slam_exit_probe_scenario.py`: 15 tests using the
real loader/router and SDK/native-read stubs. Inherited recorder ownership,
bounds, F10, output retry, capacity and cleanup tests remain. New tests preserve
.39 behavior gates; capture every Exit Root change while the Actor stays fixed;
retain dense detail in the owned return and then throttle normal TPS; record an
unexpected pose control; and tolerate missing optional SDK command detail without
losing the core data. No production mod files are changed by this diagnostic.

## .40 support

The script now also accepts .40. Its expected Exit-only Root guard is reflected
in `heading_hold.root_correction_skipped`; `unexpected_slam_pose_controls`
distinguishes that guard from unexpected IdleUpdate/Aim/CrouchAim controls.
Airborne Slam remains Turn/TurnReplace=1/1, Root/Update/Aim/Crouch=0/0/0/0;
Exit and its owned return use 1/1/1/0/0/0. The diagnostic does not alter these.
Sixteen local probe tests now include this .40 distinction.
