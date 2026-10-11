# 0.3.9.26 – erster Performance-Test

Installiere die Mess-Build nach vollständigem Spielende. Sie enthält .25.
Deine aktuellen Grafik-, DLSS-, FrameGen- und Limit-Einstellungen beibehalten.

## Idle: drei Aufnahmen

1. In normale TPS gehen. Omni-Diagnose ausschalten, falls aktiv:
   `bl4tps_omni diag off`. Das kann die Omni-Session neu binden.
2. Dieselbe Stelle und denselben Blick auf den Boden wie bei deinem Vergleich
   verwenden. Bei Omni aus angezeigte FPS notieren. Omni einschalten und
   bei laufender normaler Gameplay-Session die FPS wieder notieren.
3. `bl4tps_omni profile total idle_a` eingeben. Konsole schließen, F10 drücken.
   Stillstehen und die Kamera unverändert lassen. Nicht erneut F10 drücken.
4. Nach automatischem Abschluss (600 vorhandene Gameplay-Updates) folgt:
   `bl4tps_omni profile detail idle_detail`. Konsole schließen, F10 drücken,
   am gleichen Ort stillstehen. Angezeigte FPS während Detail notieren.
5. Abschließend `bl4tps_omni profile total idle_b` genauso ausführen.

Die Completion-Zeile lautet `[OmniPerformance] COMPLETE ... json=...`.
600 Gameplay-Updates sind eine Ereigniszahl; ihre Dauer hängt von der realen
Callback-Rate ab. Der Profiler misst weder Render- noch FrameGen-FPS selbst.
Die drei JSONs liegen im SDK-Settings-Unterordner `BL4ThirdPersonPOC_reports`
und beginnen mit `omni_performance_idle_...`.
Bitte die drei JSONs und die beobachteten FPS für Omni aus/an sowie Detail senden.
Die grafische Darstellung beim Abschluss kann durch das einmalige Speichern
kurz stottern; das ist nicht Teil der gemessenen Callback-Dauern.

## Danach Bewegung

Wenn Idle vollständig ist, optional dieselbe Sequenz mit Labels `move_a`,
`move_detail`, `move_b` ausführen und während aller drei Aufnahmen vergleichbar
laufen/strafe. Sprint/Dash/Slide/ADS zunächst getrennt halten, damit die Quelle
zugeordnet werden kann. Keine zusätzlichen Hotkeys nötig.

## Status und Abbruch

- `bl4tps_omni profile status`: armed/running/off, Fortschritt, letzter Pfad.
- F10 während eines laufenden Captures: Teilbericht und Stop.
- `bl4tps_omni profile stop`: Arm abbrechen oder Teilbericht und Stop.
- Omni ausschalten, Mod deaktivieren, Sessionwechsel: Capture beenden,
  temporäre Wrapper wiederherstellen. Labels und Reports kennzeichnen Teilmessung.
- Nach Abschluss hat F10 wieder seine bisherige Reticle-/Gameplay-Diagnosefunktion.

Die .25-Hybrid-Reticle-Spieltests sind weiterhin erforderlich; dieser Capture
bestätigt keine Kamera-/Crosshair-Darstellung.
