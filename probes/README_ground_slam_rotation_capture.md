# .38 Ground Slam rotation-request capture

Use with **0.3.9.38 and Omni enabled**. This is a diagnostic, not a direction fix.
It complements the actor/mesh/Root capture by temporarily enabling the already
installed native movement recorder before admission and during the airborne Slam.
It does not enable TurnState replacement, Aim, IdleRoot or IdleUpdate controls.

1. Put `ground_slam_rotation_capture.py` into `sdk_mods`.
2. At a suitable high ledge, have the camera face the opposite direction from
   the character. Stop other captures/profiling and run:

   ```text
   pyexec ground_slam_rotation_capture.py
   ```

3. Close the console and promptly perform one long Slam. After normal TPS has
   returned, briefly stand still and press F10 (or repeat the command).
4. Send `ground_slam_rotation_<UTC>.json` from
   `sdk_mods/settings/BL4ThirdPersonPOC_reports`. The console prints its path.

One existing widget subscription; no additional producer, timer, executable
patch, rotation/animation/camera/settings writes, or diagnostic-buffer reset.
It does perform native reads to validate the installed hook and current local
movement/component. `recorder_gate_writes` counts writes to the existing
Python-owned diagnostic control flag; these are not behavior controls.

The shared recorder has 1024 records, not 1024 frames. The capture starts at its
existing count and automatically saves when full. Start the Slam promptly. If
already full, a fresh game session supplies a fresh buffer. The probe leaves
production's GroundSlamExit recording flag alone. F10, timeout, failure and mod
shutdown close the probe's flag and detach its subscription; file output can be
retried after failure. Stop requests that own a flag require the game thread.

Records contain original requested quaternion and pre-call component quaternion,
caller return RVA, movement delta and bounding probe update indices. They are
recorded **before** the existing ordinary Omni replacement prefix. A request is
not proof it was applied. SDK gate observations describe the widget observation,
not the gate at each recorded native instruction. Return RVAs identify a call
site; they do not alone establish a semantic function name. Rotation through
another path, or outside an enabled interval, may be absent. In particular, zero
records cannot exclude a writer. `last_widget_update_index` is the legacy native
marker, populated by production's Exit observer; it can be stale in air. Use the
probe interval indices and sample `omni_update` values to correlate air records.
Diagnostic overhead is not an FPS measurement.

## Evidence motivating this capture

User capture `ground_slam_facing_20261012_002747_053451.json` on .38:

- 380 updates, manual stop, no required/optional read errors, cleanup complete.
- Slam starts at update 88 / 1505.54 ms with actor yaw 101.468 degrees.
- Actor changes at 89 and 90 by approximately -45 and -60 degrees, then about
  -3 degrees per update. It reaches -93.532 degrees at 120 / 2040.78 ms.
- GroundSlamExit starts at 161 / 2779.82 ms: the turn finished about 739 ms
  before impact. Camera yaw stayed approximately -78.532 degrees, so the final
  actor heading is about 15 degrees beyond the camera heading.
- Mesh world yaw matches actor yaw in all 20 Hz details during native pose;
  Root yaw relative to actor stays between -0.0174 and 0 degrees.
- All six Omni behavior controls are zero for the 193 native-pose observations.
- The existing Exit arguments expose two records at caller RVA `0x2eec48`, both
  requesting the already-current rotation. These two records cannot identify
  the preceding airborne turn.

These observations locate the visible heading change in the air and separate it
from independent skeletal Root motion. They do not identify the native writer.
The next decision is whether the airborne request comes through the known
TurnState call site or a different dispatch path before a heading-only fix is
chosen. Keep the accepted 150 cm distance and the complete native Slam pose.

Validation: `python tests/ground_slam_rotation_probe_scenario.py`.
Native reads and SDK objects are stubbed. Checks cover admission/air records,
F10/final drain, Exit ownership, foreign record/owner/patch rejection, full-buffer
stop, output retry and game-thread cleanup. These checks do not prove live-game
callback ordering, caller identity or a working direction fix.
