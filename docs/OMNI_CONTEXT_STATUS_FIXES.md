# Omni context/status fixes on 0.3.9.9

This overlay contains changed source and test files, not a complete mod build.
Extract into the complete 0.3.9.9 development project and replace matching files.
Build the complete project with `python tools/build_sdkmod.py`.

- Action_Zoom is optional in effective mappings: Throwable contexts can omit it.
  Zoom intent is then false; old keys are discarded. Restored mappings are read
  on context/mapping changes through the existing producer. Required movement
  and fire actions, schema and owner checks remain fail-closed.
- Omni running status now checks the supervisor's active state. Failed cleanup
  retains ownership and blocks re-arming until explicitly cleaned up with off.
  Failure reasons survive successful error cleanup and clear on explicit off
  or successful start. Gameplay failsafe stops also retain their reason.

Validation: 162 Python tests passed (3 skipped). No in-game validation yet.
No native code, addresses, signatures or timer-based synchronization added.

## In-game checks

1. Enable Omni, equip/use/put down a Throwable; check no missing-zoom stop.
2. Return to a regular weapon and check ADS, including rebound ADS keys.
3. Check `bl4tps_omni status` before/after off/on and in normal gameplay.
4. Check map changes, vehicles and normal on-foot rebind.

## Sprint / empty magazine: blocked pending native evidence

The original PostSprintUseDelay + 0.25 s release remains unchanged in this
overlay. Active + not firing cannot distinguish a rejected shot from a valid
deferred shot. Removing the bound alone would either restore the old permanent
latch or release valid queued shots early.

Use the existing weapon diagnostic (no separate probe installation):

- Run `bl4tps_omni diag on`, then `bl4tps_omni on` if needed.
- With a regular loaded weapon, sprint sideways/backwards, tap Fire and release
  before the native shot. Repeat while holding Fire briefly.
- Empty that weapon, perform the same actions, including holding/releasing Fire.
- Immediately run `bl4tps_omni report` and provide the newly saved JSON (ZIP OK).
- Run `bl4tps_omni diag off` afterwards.

The bounded weapon_fire_diagnostic records reflected candidates and native
firing/phase changes. Their meaning must be verified against both runs before
using any candidate as an admission/rejection signal. If the candidates do not
expose such a signal, a targeted native event probe will be needed.

