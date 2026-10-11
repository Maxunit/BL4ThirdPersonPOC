# 0.3.9.32 – kurzer Fahrzeugtest

Spiel vollständig beenden, alte Mod und PyCache entfernen. Eine Variante
installieren: `dist/BL4ThirdPersonPOC.sdkmod` oder Quellordner.
Omni und kamerarelative Fahrzeugsteuerung einschalten. Erst normale TPS ohne ADS
und ohne Menü verwenden. Für diesen Test sind keine Profiler-Aufnahmen nötig.

## 1. Rufen

- Kamera nach vorn, Figur durch Rückwärtslaufen zur Kamera ausrichten, loslassen.
  Fahrzeug rufen: Richtung des gerufenen Fahrzeugs mit der Figur vergleichen.
- Ebenso Figur seitlich ausrichten und rufen.
- Nach einem Fahrzeugausstieg ohne erneutes Laufen direkt wieder rufen.

Mit einem normalen Fahrzeug und dem Lichtschützen gegenprüfen. Beim
Lichtschützen kann die Kamera wie bereits in .31 hinter das Fahrzeug drehen.

## 2. Kurze Steuerimpulse und Ausstieg

- Nach dem Rufen W kurz antippen und direkt aussteigen.
- Separat mit S, A und D wiederholen; jeweils Fahrzeugausrichtung unmittelbar
  vor dem Ausstieg mit der Figur danach vergleichen.
- Einen Fall wiederholen, diesmal nach dem Tipp bis zum Stillstand warten.
- Bei Gelegenheit aus Rückwärtsfahrt oder seitlicher Bewegung aussteigen.
  Gewünscht ist immer die Fahrzeugausrichtung, auch wenn die Fahrtrichtung abweicht.

## Zurückgeben

Den Session-Log oder mindestens die zusammengehörigen Zeilen
`[OmniVehicle] summon`, `[OmniVehicle] exit`, `[OmniVehicle] air_rebind` und
`[OmniBind] ready` schicken. Zusätzlich kurz Fahrzeugtyp, Tipp-Taste und
beobachtete falsche Richtung nennen. Bei einem verbleibenden Fehler kann ein
kurzes Video die sichtbare Fahrzeug-/Figurendrehung ergänzen.

Alternativ `bl4tps_omni report`: relevante Abschnitte sind
`vehicle_handoff.exit_facings` und `vehicle_handoff.summon_seats`.
Die Zeilen sind pro Spielsitzung begrenzt; der Report enthält die letzten Fälle.
