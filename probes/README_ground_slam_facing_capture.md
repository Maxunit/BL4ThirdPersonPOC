# .38 Ground Slam facing capture

Read-only PyExec probe for the confirmed complete native Slam animation whose
visible character turns toward the camera. Compare actor heading against the
skeletal mesh and animated Root/Spine3/Spine5/Head world rotations before choosing
a heading-only intervention. Bone Euler yaw is flagged when its forward vector
has little horizontal projection; do not interpret a vertical bone as a stable
heading. Sequential SDK observations do not prove a native writer or render order.

1. Keep .38 and Omni enabled; stop other captures and the Omni profiler.
2. Put `ground_slam_facing_capture.py` in `sdk_mods`, then run:

   ```text
   pyexec ground_slam_facing_capture.py
   ```

3. Close the console. Hold the original scenario: camera north, character south.
   Briefly stand still, perform one preferably longer Slam, then stand still again
   for about two seconds after normal TPS returns.
4. Repeat the command or press F10. Send the resulting JSON from
   `sdk_mods/settings/BL4ThirdPersonPOC_reports/ground_slam_facing_<UTC>.json`.
   The console prints its exact path.

The probe adds one subscription to the existing owned widget. No actor,
animation, camera, settings or native-memory writes, no native reads/patches,
producer, input simulation or timer. The existing capture singleton ensures
F10 and mod shutdown detach it before the producer. Limits: 120 seconds / 8000
updates. Actor heading and Slam state every update; pose detail at most 20 Hz.
Omni gates and already-recorded Exit arguments are copied from owned Python data.
Diagnostic overhead is not a performance measurement.

Local validation: `python tests/ground_slam_facing_probe_scenario.py`.
Six real-loader/router scenarios with SDK stubs: distinct actor/bone turns,
fixed actor with animated Root rotation and vertical-yaw flag, F10 cleanup,
foreign animation rejection, game-thread/console arming gates, output retry.
These checks prove capture ownership and data separation, not live game behavior.

The same facing script also accepts .39. In that QA an eligible Slam should
show Turn/TurnReplace = 1/1 with IdleRoot/IdleUpdate/Aim/CrouchAim = 0/0/0/0.
This records the final published state; it does not prove rendering order.
The separate .38 rotation-request probe intentionally remains .38-only.
