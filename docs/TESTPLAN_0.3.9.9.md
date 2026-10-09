# Testplan 0.3.9.9 – Ziel-Trace auf Figurentiefe

Installation wie bisher: die `.sdkmod` ersetzen und `__pycache__` löschen.

Zum direkten Vergleich schaltet ihr den Fix mit `bl4tps_aim off` aus und mit `bl4tps_aim on` wieder ein.

## 1. Start
In TPS sollte einmal `[BL4ThirdPersonPOC.AimTrace] ARMED rva=0xC8DA03 native_patches=1` erscheinen.

## 2. Wandkante (eure Screenshots)
1. Dieselbe Stelle wie auf den Screenshots, mit dem AR schießen.
2. Erwartet: Die Kugeln fliegen nach vorn und schlagen nicht an der Wandkante ein.
3. Zum Vergleich `off` und danach `on`.
4. Danach `bl4tps_aim status` eingeben und die Zeile `AIM_TRACE {…}` schicken.

## 3. Gegner oder Objekt im Rücken
- Es fliegen keine Kugeln nach hinten.
- Bitte darauf achten, ob der Kamera-Spin noch auftritt.

## 4. Regression
- Ziele in etwa 3 m, 15 m und 50 m, aus der Hüfte und mit TPS-ADS: Die Treffer liegen am Fadenkreuz.
- Shotgun, SMG und Scharfschützengewehr kurz anspielen.
- Ein Gegner direkt vor der Figur, etwa 1 m entfernt, wird getroffen.
- In FPS ändert sich nichts.
- Fahrzeug, FFYL und Omni laufen wie bisher.

## 5. Beam
Bitte einmal an der Wandkante testen und notieren, ob er sich anders verhält. Wahrscheinlich bleibt er unverändert.

## 6. Feinabstimmung, nur falls nötig
- `bl4tps_aim margin 70`, wenn die Kugeln noch die Kante streifen.
- `bl4tps_aim margin 20`, wenn ganz nahe Gegner vor der Figur nicht getroffen werden.
