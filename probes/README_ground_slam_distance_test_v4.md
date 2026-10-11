# Ground Slam distance test V4 — return during descent

Standalone PyExec camera test for **BL4ThirdPersonPOC 0.3.9.35**.
The production mod and V1–V3 probes remain unchanged.

## Run

1. Stop an older probe/capture first. Keep the Omni profiler off.
2. Put `ground_slam_distance_test_v4.py` in the SDK `sdk_mods` directory.
3. Enable TPS, stand on ordinary walkable ground, then run:

   ```text
   pyexec ground_slam_distance_test_v4.py
   ```

4. Close the console and remain on that ground for about two seconds.
   Look for `[BL4TPS.SlamDistanceV4] ACTIVE`. The standing trace calibration
   happens on the first owned update; the pause also lets the probe compare
   successive raw SDK writes with the camera's composed X offset.
5. Test a long Slam first, then a shorter one. Watch whether the camera holds
   its extra distance high in the air, returns during descent and is already
   neutral when impact switches the camera to `GroundSlamExit`.
6. Wait until normal TPS is back, then repeat the same command or press F10.
   This restores the original setter and saves the report under:

   ```text
   sdk_mods/BL4ThirdPersonPOC_reports/ground_slam_distance_test_v4_<UTC>.json
   ```

The console reports the exact output path. Send that JSON with the visual
result. Automatic stop: 180 seconds or 16,000 sampled updates.

## Behavior

- `EXTRA_DISTANCE = 250.0` cm, explicitly set in this file.
- Entry uses the existing smooth exponential approach, response 0.08 seconds.
- At startup, two downward traces (channels 0 and 1) are compared against the
  standing capsule's `CurrentFloor.FloorDist`. A channel must agree within
  12 cm. Missing/invalid calibration stops before any camera modification.
- During an active native `IsPerformingGroundSlam()` state, one downward trace
  per owned widget update measures capsule-bottom clearance above the hit.
  The standing contact gap is subtracted; pawn collision is ignored and
  debug drawing is disabled. The trace reaches 200 m below the capsule.
- Above 12 m predicted clearance the extra distance is held. Between 12 m and
  a 1 m contact margin, a smoothstep spatial envelope returns it to zero.
  Descending velocity provides one update of lookahead. This uses ground
  proximity rather than a fixed Slam duration. Short Slams receive a smaller
  zoom because their return window has already begun.
- Once return begins, the extra cannot increase again within that Slam,
  including a temporarily missing trace or movement over a lower ledge.
- A lost trace before the return begins retains the entry/hold distance.
  The Exit bridge remains a fallback; a ground miss can therefore return
  later than the intended impact. Terrain selection and visible smoothness
  still need in-game testing.

## Native Exit handoff

The V3 report showed two coordinate spaces: raw SDK setter X and the composed
native Exit X. This probe learns their translation from at least three stable
successive paired observations; the previously observed -256 cm is not a
hardcoded game offset. A captured native target must exactly match a recorded
probe write after that translation. Matching only X intentionally preserves
the live native body/shoulder Y/Z values.

The existing .35 native consumer, prefix SHA-256, 256-byte Python control
layout and current weak owners are checked. Only the proven extra X is
removed from that already-owned control target. A snapshot of an earlier,
larger zoom cannot re-expand an extra already reduced during descent.
Unmatched/foreign targets are left untouched and use the V3 smooth ordinary
TPS fallback instead. No new machine-code patch, process-memory access,
producer, timer, FOV/profile/animation/actor write is introduced.

Existing motion and Root-height calculations run first. Their completed raw
SDK output receives the extra exactly once per setter, avoiding accumulation.
Stopping restores only still-owned values; newer/foreign writes are preserved.

## Local validation

```text
python tests/ground_slam_distance_v4_test_scenario.py
```

14 scenarios use the real .35 loader and update router with SDK object stubs:
long/short descent, neutral before contact, composed and early native snapshots,
trace loss, repeated Slams, ordinary jumps, calibration/signature rejection,
foreign owners/fingerprints, repeated setters, ADS/FPS/vehicles, F10/shutdown,
Root-height preservation with the real production setter, and spatial curve
continuity/lookahead. These checks establish local state/ownership behavior;
they do not establish the game's actual trace collision response, render timing
or performance.
