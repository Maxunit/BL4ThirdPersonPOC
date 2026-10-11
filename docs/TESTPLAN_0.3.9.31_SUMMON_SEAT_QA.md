# 0.3.9.31 – Testplan

Spiel vollständig beenden; alte Mod-Dateien und PyCache entfernen. Omni und die
kamerarelative Fahrzeugsteuerung einschalten.

Figur entgegen der Kamera ausrichten: zur Kamera hin laufen, loslassen.

## Lichtschütze

1. Kamera nach Norden, Figur nach Süden, rufen. Erwartet: Fahrzeug nach Süden,
   die Kamera dreht hinter das Fahrzeug.
2. Figur schräg nach hinten (Südost), rufen. Erwartet wie 1.
3. Figur nach Osten, dann nach Westen, rufen. Erwartet: Fahrzeug in Figurrichtung,
   Kamera bleibt.
4. Nach jedem Rufen kurz losfahren: fährt der Lichtschütze in Kamerarichtung?
5. Aussteigen: Richtung der Figur notieren.

## Gegenprobe normales Fahrzeug

6. Kamera nach Norden, Figur nach Süden, rufen. Erwartet wie in .30: Fahrzeug
   nach Süden, **Kamera bleibt** nach Norden.

## Zurückmelden

Nach jedem Rufen erscheint eine Zeile `[OmniVehicle] summon …` (spätestens beim
Aussteigen; sonst `bl4tps_omni report`, Abschnitt `vehicle_handoff.summon_seats`).
Bitte mindestens zurückgeben:

- eine Zeile vom Lichtschützen aus Schritt 1
- eine Zeile vom normalen Fahrzeug aus Schritt 6

Daran sieht man, wie Omni den Lichtschützen erkennt (`seat`), ob die Kamera
gesetzt wurde (`align`) und ob und wann sich das Fahrzeug gedreht hat
(`turn_frame`, `timeline`).
