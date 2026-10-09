# Testplan 0.3.9.6 – Messrunde 2

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Das Spielverhalten bleibt unverändert.

## Proben
Im normalen TPS, ohne ADS, mit der Waffe in der Hand jeweils `bl4tps_weapon_probe` eingeben:
1. **AR (Hitscan)** – dieselbe Waffe wie in Runde 1
2. **Beam-Waffe** – dieselbe wie in Runde 1
3. Optional die **Shotgun mit Minigranaten**

In der Konsole steht jetzt zusätzlich `holder=[…] holder_functions=… holder_camera_cache_readers=…`. Bitte diese Zeile mitschicken.

## Zurückschicken
- Die neuen `weapon_probe_*.json`. Sie sind etwa 3 MB groß.
- Die `WEAPON_PROBE`-Konsolenzeilen.
