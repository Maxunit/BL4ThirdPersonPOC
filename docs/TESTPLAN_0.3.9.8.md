# Testplan 0.3.9.8 – Zielursprung auf Figurentiefe

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen. Omni darf an bleiben.

Mit `bl4tps_aim off` und `bl4tps_aim on` lässt sich jederzeit zwischen altem und neuem Verhalten wechseln. Das ist praktisch für den direkten Vergleich.

## 1. Start
1. Ins Spiel laden und TPS einschalten. In der Konsole sollte einmal `[BL4ThirdPersonPOC.AimOrigin] ARMED rva=0x40A6ECA native_patches=1` stehen.
2. `bl4tps_aim status` eingeben. Erwartet: `installed: True`, `reason: 'active'`.

## 2. Wandkante (eure Screenshots)
1. Dieselbe Stelle wie auf den Screenshots, das Fadenkreuz liegt über der Wandkante neben der Figur.
2. Mit dem AR schießen. Erwartet: Die Projektile fliegen nach vorn, wie es Position und Perspektive der Figur entspricht. Keine Einschläge an der Wand neben der Figur.
3. Zum Vergleich `bl4tps_aim off` eingeben, die Wand wird wieder getroffen. Danach `bl4tps_aim on`.

## 3. Gegner oder Objekt im Rücken
1. Ein Gegner oder Objekt steht dicht hinter der Figur im Fadenkreuz.
2. Erwartet: Es fliegen keine Projektile nach hinten.
3. Bitte darauf achten, ob der Kamera-Spin noch auftritt.

## 4. Regression beim Zielen
1. Auf Ziele in etwa 3 m, 15 m und 50 m schießen, aus der Hüfte und mit TPS-ADS. Die Treffer liegen wie bisher am Fadenkreuz.
2. Kurz mit Shotgun (Minigranaten), SMG (Bienen) und Scharfschützengewehr testen.
3. Gegner direkt vor der Figur, etwa einen Meter entfernt: Sie müssen weiterhin getroffen werden.
4. FPS (F5): Es gibt keine Änderung. `bl4tps_aim status` zeigt dort `reason: 'first_person_view'`.
5. Fahrzeug, FFYL, Leiter und Omni im Sprint: wie bisher.

## 5. Beam
In dieser Version ist **keine Änderung** zu erwarten. Der Beam folgt im nächsten Schritt.

## 6. Falls es nicht ganz passt
- Projektile streifen noch die Wandkante: `bl4tps_aim margin 70` eingeben und erneut testen.
- Ganz nahe Gegner vor der Figur werden nicht getroffen: `bl4tps_aim margin 20` eingeben.
- Bitte jeweils notieren, welcher Wert sich am besten anfühlt.

## Zurückschicken
- Nach dem Schießen an der Wand und mit dem Gegner im Rücken die Zeile aus `bl4tps_aim status` schicken. Sie enthält `visits`, `applied`, `skipped`, `mismatch`, `last_origin`, `last_shifted` und `last_depth`.
- Kurze Notizen zu den Punkten 2 bis 5.
- Bei einem Absturz bitte sofort melden. Der Fix lässt sich mit `bl4tps_aim off` abschalten, und die Mod läuft ohne ihn wie in 0.3.9.7.
