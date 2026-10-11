# 0.3.9.34 – Höhenaufnahme

Mod wie gewohnt ersetzen: Spiel vollständig beenden, alte Version/PyCache
entfernen, nur `dist/BL4ThirdPersonPOC.sdkmod` oder den Quellordner installieren.
.34 behält das Gameplay der .33; sie fügt eine manuell gestartete Diagnose hinzu.
Kein `pyexec` notwendig. Omni-Diagnose muss dafür nicht aktiviert werden.

## Zuerst zwei Vergleichsaufnahmen

Kameraeinstellungen, Motion-Camera-Zustand und Omni-Zustand in beiden Aufnahmen
gleich lassen. Nicht zielen. Kameraneigung und Blickrichtung möglichst beibehalten.

1. **Boden:** Am gezeigten Ort normal auf dem Boden stehen. F1 öffnen:
   `bl4tps_height arm boden`
   Konsole schließen, F10 drücken. Still stehen bleiben, bis die Aufnahme endet.
2. **Geländer:** Auf das gezeigte Geländer steigen und ruhig stehen bleiben.
   In der Konsole: `bl4tps_height arm gelaender`
   Konsole schließen, F10 drücken und wieder bis zum Ende still stehen bleiben.

Die Aufnahme umfasst 600 vorhandene Spiel-Updates. Ende im Session-Log:
`[BL4ThirdPersonPOC.Height] COMPLETE ... updates=600 ... sdk_hooks=0 ... json=...`
Danach diese beiden JSONs senden. Sie beginnen mit `camera_height_boden_` und
`camera_height_gelaender_` und liegen unter
`sdk_mods/settings/BL4ThirdPersonPOC_reports/`.

## Optional: Verlauf des Versatzes

`bl4tps_height arm gelaender_wechsel` auf dem Boden vormerken, Konsole schließen,
F10 drücken. Kurz stehen, aufs Geländer springen und dort ruhig stehen bleiben.
Damit sehen wir den Wechsel des Untergrunds und die Motion-Pose-Anpassung im Verlauf.

Ground Slam später separat: `bl4tps_height arm slam`, Konsole schließen, F10;
kurz normal stehen, springen, Slam ausführen und danach stehen bleiben.
Das Zeitfenster endet weiterhin nach 600 Updates. Der seltene Fehler muss in
diesem Fenster tatsächlich auftreten, damit die Aufnahme ihn erfasst.

## Bedienung

- F10 während der Aufnahme: frühzeitig stoppen und bisherige Daten speichern.
- `bl4tps_height status`: Zustand und letzten Ausgabeort anzeigen.
- `bl4tps_height off`: Vormerkung entfernen bzw. Aufnahme stoppen/speichern.
- Höhenaufnahme und Omni-Profiler werden über den Console-Weg gegenseitig gesperrt.
- Außerhalb dieser Aufnahme bleibt F10 Debug-/ADS-Snapshot bzw. Omni-Profiler.

Die Diagnose erzeugt zusätzliche SDK-Lesezugriffe. Diese Läufe dienen der
Höhenanalyse, nicht einem FPS-Vergleich. Nach Ende wird die einzige vorübergehende
Subscription entfernt; kein neuer Tick-Produzent, Timer oder nativer Hook.
Bei Welt-/Figur-/Mesh-Wechsel endet sie mit `READ_FAILED` und speichert den
bisherigen Verlauf. Fehlende optionale Felder erscheinen unter `optional_errors`.
