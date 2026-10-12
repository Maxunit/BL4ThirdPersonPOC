# .40 IdleTurns inputs and code comparison

User QA: .40 retains body heading but the upper body rapidly alternates between
character and camera direction. Skipping only the output Root correction is not
a demonstrated solution. Working hypothesis: the underlying turn selection/input
continues requesting camera-facing direction, potentially switching left/right
near the +/-180-degree boundary. The .39 AimYaw observations support testing that
boundary; they do not confirm the .40 cause or establish exact node input semantics.

Keep .40 and Omni enabled. Put `ground_slam_idle_inputs_capture.py` in sdk_mods.
Stop other captures/profiling. For each of the two cases below:

```text
pyexec ground_slam_idle_inputs_capture.py
```

Close the console, promptly perform one long Slam, let Exit and TPS return finish,
briefly stand still, then press F10 (or repeat the command). Send the timestamped
`ground_slam_idle_inputs_<UTC>.json` from `settings/BL4ThirdPersonPOC_reports`.

- Case A: camera exactly opposite the character (roughly 180-degree difference).
- Case B: rotate the camera 30-45 degrees away from that frontal viewing position
  while retaining the character heading (roughly 135-150-degree difference).

Also report whether the visible twitching differs between the cases. The camera
and body angles are recorded so the files can be distinguished by data. Use the
same height and character/weapon where practical. No setting or code changes
between cases. If the shared native recorder is already full, restart the game;
the script never resets a published buffer. An automatic capacity stop preserves
partial observations but may omit the complete Exit. Ordinary standing no longer
uses native recording capacity; SDK/pose observations still run.

One existing widget subscription; .40 only. Existing controls and overlays are
observed, not changed. No actor/animation/camera/settings writes, new native patch,
producer or timer. Native reads validate the already installed local recorder and
copy bounded code windows. The only published control writes are to the existing
Python-owned diagnostic record flag. Production retains Exit recording ownership.

As in the Exit probe: actor and current gates each update; Root/mesh/bone detail
each owned widget update during Exit/owned return, otherwise at most 20 Hz. New
public scalar fields from the five exact reflected local GbxAnimNode_IdleTurns
receivers are read at most 20 Hz. Schema binding: eight inheritance entries,
256 fields per type, 64 scalar fields per node. Arrays, objects, nested structs
and private/unreflected fields are not traversed. Missing schema is explicitly
reported; individual unavailable scalars are optional errors. Public input fields
may describe configuration rather than live turn selection.

Two native code windows are copied once after binding the installed scoped
workers: Update at 0x186e850 through the adjacent Evaluate entry at 0x186ec26
(982 bytes), and a bounded 512-byte Evaluate window. Build/node/patch identities
come from the existing validated workers. Executable image bounds are checked;
live patches must match their captured owned metadata. Their reviewed original
prologues are restored only in the JSON copy, never in the game. These windows
are for code inspection; they do not constitute a call trace or guarantee exact
function extent. Missing code is reported without altering the live mod.

Limits: 120 s / 8000 updates / remaining 1024 native records. Native requests are
originals before argument replacement, not proof of applied rotation. Private
counters and SDK pose reads are sequential, not an atomic render snapshot. The
legacy native frame marker can be stale outside production Exit recording;
correlate probe interval indices and sample omni_update values. Bone Euler yaw
near vertical pitch is flagged. Diagnostic overhead is not a performance test.
F10/failure/timeout/shutdown detach the capture and close its owned record flag,
preserving a production-owned Exit flag; output failures can be retried.

Validation: `python tests/ground_slam_idle_inputs_probe_scenario.py`:
21 local tests with SDK/native-memory stubs, including the inherited ownership,
cleanup, bounds and per-update Exit data checks; public scalar capture and schema
limits; exact owned-code reconstruction with unchanged live code; foreign patch
rejection; and recording only during the owned Slam/return. These checks validate
the diagnostic workflow, not live inputs, rendered behavior or a working fix.

## .41 diagnostic support

The updated script accepts .40 and .41. The .40 capture exposed only five
non-scalar links (Idle, LeftTurn, RightTurn, TurnToIdle, IdleToTurn) and no public
scalar runtime fields. The new optional `idle_private_state` reads only the
24-byte scalar window at 0x300..0x317 of the same five validated owned receivers.
Those offsets are read by the captured original Update. This fallback runs only
when reconstructed Update code exactly matches SHA256
`6d23c416af99cb4bfda63f2f3f9e96a5f023ef2551412399dda8ecc141ca8dfd`.
Worker identity, scope/vtables, current animation ownership, readable committed
region and bounded read are validated. No pointers from these private fields are
followed. Raw float/guard values are labeled by offset; they are sequential
observations, not proof of a selected input or executed branch. Nonfinite floats
are stored as null. Missing/unreviewed code disables the private layout reader.

During .41 Exit the expected IdleUpdate guard is distinguished from unexpected
Aim controls using `idle_fallback_selected`. Twenty-four local probe scenarios
pass, including exact reviewed private layout/scope, unchanged private memory,
and refusal to read private offsets under unreviewed code. If needed, replace
the previously downloaded .40-only script with this updated copy.
