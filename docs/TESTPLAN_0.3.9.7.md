# Testplan 0.3.9.7 – Messrunde 3

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Am Spielverhalten ändert sich nichts.

## 1. Statische Probe
Mit dem AR in der Hand, im normalen TPS und ohne ADS, `bl4tps_weapon_probe` eingeben. Die Konsolenzeile zeigt jetzt zusätzlich `aim_provider=[…] aim_target=0x…`.

## 2. Live-Probe (ruft zwei Getter des Spiels einmal auf)
1. Dieselbe Stelle wie auf euren Screenshots: dicht an der Wand, das Fadenkreuz liegt über der Wandkante neben der Figur. Dann `bl4tps_weapon_probe live` eingeben.
2. Danach ein paar Schritte weg von der Wand, sodass das Fadenkreuz frei in die Ferne zeigt. Wieder `bl4tps_weapon_probe live` eingeben.
3. Optional: Ein Gegner oder Objekt steht dicht hinter der Figur im Fadenkreuz. Wieder `bl4tps_weapon_probe live` eingeben.

Meine Erwartung: Bei der Wandkante liegt der Zielpunkt nahe an der Kamera, `target_depth` ist also klein und meist `target_in_front_of_pawn=False`. Bei freier Sicht ist `target_depth` groß. Genau diese Zahlen brauche ich, um die Schwelle festzulegen.

Falls das Spiel bei `live` abstürzt oder hängt, bitte melden. Den Aufruf nehme ich dann wieder heraus. Die statische Probe aus Punkt 1 bleibt in jedem Fall verwertbar.

## Zurückschicken
- Die `weapon_probe_*.json`-Dateien, eine aus Punkt 1 und je eine pro Live-Probe.
- Alle Konsolenzeilen mit `WEAPON_PROBE` und `WEAPON_PROBE_LIVE`.
