# 0.3.9.30 – Testplan

Spiel vollständig beenden; alte Mod-Dateien und PyCache entfernen.

1. Nach vorn schauen, Fahrzeug holen, einsteigen, **sofort** aussteigen. Dreimal.
2. Dasselbe nach rechts schauend.
3. Ein paar Meter vorwärts fahren, aussteigen.
4. Rückwärts fahren (zügig), aussteigen: Die Figur schaut in Fahrtrichtung, also nach hinten.
5. Fahren, anhalten, kurz stehen, aussteigen: Die Figur schaut wie das Fahrzeug.

Nach jedem Ausstieg die `[OmniVehicle]`-Zeilen notieren (oder `bl4tps_omni report`,
Abschnitt `vehicle_handoff.exit_facings` und `hitches.notes`).

Falls die Richtung noch kippt: Zeilen `seated`, `exit`, `air_rebind` und
`[OmniBind] ready` des betroffenen Ausstiegs zurückgeben. Daran sieht man, ob der
Yaw beim Summon, beim Ausstieg oder bei Omnis Übernahme falsch wird.

Regression aus .29 (Ruckler-Logger, gestaffeltes Binden) bleibt gültig.
